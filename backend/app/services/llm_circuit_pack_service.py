"""Circuit extraction via brain region pack → DeepSeek → parse → write."""

from __future__ import annotations

import asyncio
import json
import logging
import random
import uuid
from datetime import datetime, timezone
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.candidate import CandidateBrainRegion
from app.models.llm_circuit_extraction import CircuitExtractionRun
from app.models.mirror_kg import MirrorCircuitRegion, MirrorRegionCircuit
from app.models.mirror_macro_clinical import MirrorCircuitStep, MirrorCircuitFunction
from app.schemas.mirror_kg import MirrorStatus
from app.schemas.llm_circuit_extraction import (
    CircuitExtractionRequest,
    CircuitExtractionRunRead,
    CircuitExtractionStartResponse,
)
from app.services.llm_field_completion_service import _resolve_model_status
from app.services.llm_providers import get_llm_provider
from app.services.llm_prompt_defaults import DEFAULT_TEMPLATES
from app.services.llm_workflow_cancel_registry import mark_cancelling, is_cancelling, clear as clear_cancel_registry
from app.utils.json_safety import to_jsonable

logger = logging.getLogger(__name__)

CIRCUIT_TEMPLATE_KEY = "same_granularity_circuit_completion_v1"

# ── Rich circuit prompt (extends SAME_GRANULARITY_CIRCUIT_COMPLETION_V1) ─────
# System prompt from the curated template — neuroscientist-level guidance in Chinese.
# User prompt extends the template with circuit types, region roles, constraints,
# AND the nested steps+functions output schema required by the pack service.

_CIRCUIT_USER_PROMPT_EXTENDED = (
    "Identify neural circuits from candidate regions and connections. Output {max_circuits} circuits minimum.\n\n"
    "Types: sensory_circuit|motor_circuit|limbic_circuit|cognitive_control_circuit|memory_related|reward_related|language_related|attention_related|default_mode_related|salience_related|uncertain_circuit|unknown\n"
    "Roles: source|target|hub|relay|modulator|participant\n"
    "2-6 regions per circuit. Use connections first, infer from neuroanatomy if sparse. Confidence 0.05-0.3=weak OK.\n\n"
    "Regions:\n{regions_json}\n\n"
    "Connections:\n{connections_json}\n\n"
    "Functions:\n{functions_json}\n\n"
    "JSON only:"
    '"member_region_ids":["uuid3","uuid4"],"steps":[]}}]}}'
)

_BUILD_CIRCUIT_SYSTEM_PROMPT: str | None = None

def _get_circuit_system_prompt() -> str:
    """Lazy-load the circuit system prompt from curated defaults."""
    global _BUILD_CIRCUIT_SYSTEM_PROMPT
    if _BUILD_CIRCUIT_SYSTEM_PROMPT is None:
        tpl = DEFAULT_TEMPLATES.get(CIRCUIT_TEMPLATE_KEY)
        if tpl is not None:
            _BUILD_CIRCUIT_SYSTEM_PROMPT = tpl.system_prompt
        else:
            _BUILD_CIRCUIT_SYSTEM_PROMPT = (
                "你是神经科学知识图谱数据治理助手，专精于脑回路(circuit)识别与建模。你只能输出 JSON。\n\n"
                "核心原则：\n"
                "- 你的输出是候选回路建议，不是正式事实，需人工审核\n"
                "- 必须参考提供的连接候选和功能候选作为回路推断依据\n"
                "- confidence: 0.8+=强证据, 0.5-0.8=中等, 0.3-0.5=弱证据\n"
                "- 人脑中存在大量回路(数百至数千)，尽可能多地识别有效回路"
            )
    return _BUILD_CIRCUIT_SYSTEM_PROMPT


def _build_region_context_json(candidates: dict, pack_ids: list) -> str:
    """Build rich region JSON with anatomical context for the prompt."""
    regions = []
    for rid in pack_ids:
        c = candidates.get(rid)
        if c is None:
            continue
        entry: dict[str, Any] = {
            "candidate_id": str(rid),
            "name": c.cn_name or c.en_name or c.std_name or str(rid)[:8],
            "atlas": c.source_atlas or "",
            "region_type": getattr(c, "region_type", "") or "",
            "hemisphere": getattr(c, "hemisphere", "") or "",
        }
        # Include functional annotations if available
        func_domains = getattr(c, "functional_domains", None)
        if func_domains:
            entry["functional_domains"] = func_domains
        regions.append(entry)
    return json.dumps(regions, ensure_ascii=False, indent=2)


async def _build_connections_context(session, candidate_ids: list) -> str:
    """Query existing Mirror connections involving the given candidates."""
    try:
        from app.models.mirror_kg import MirrorRegionConnection
        q = select(MirrorRegionConnection).where(
            MirrorRegionConnection.source_region_candidate_id.in_(candidate_ids)
            | MirrorRegionConnection.target_region_candidate_id.in_(candidate_ids)
        ).limit(500)
        result = await session.execute(q)
        rows = result.scalars().all()
        conns = []
        for r in rows:
            conns.append({
                "source_id": str(r.source_region_candidate_id),
                "target_id": str(r.target_region_candidate_id),
                "connection_type": r.connection_type or "unknown",
                "strength": r.strength or "unknown",
                "confidence": r.confidence or 0.5,
            })
        return json.dumps(conns, ensure_ascii=False, indent=2)
    except Exception:
        return "[]"


async def _build_functions_context(session, candidate_ids: list) -> str:
    """Query existing Mirror functions for the given candidates."""
    try:
        from app.models.mirror_kg import MirrorRegionFunction
        q = select(MirrorRegionFunction).where(
            MirrorRegionFunction.region_candidate_id.in_(candidate_ids)
        ).limit(500)
        result = await session.execute(q)
        rows = result.scalars().all()
        funcs = []
        for r in rows:
            funcs.append({
                "region_id": str(r.region_candidate_id),
                "function_en": r.function_term_en or "",
                "function_cn": r.function_term_cn or "",
                "domain": r.function_domain or "",
                "role": r.function_role or "",
            })
        return json.dumps(funcs, ensure_ascii=False, indent=2)
    except Exception:
        return "[]"


def _filter_context_by_pack(all_context_json: str, pack_ids: list) -> str:
    """Filter pre-loaded connection/function context to only items relevant to this pack."""
    if not all_context_json or all_context_json == "[]":
        return "[]"
    try:
        all_items = json.loads(all_context_json)
        if not isinstance(all_items, list):
            return all_context_json
        pack_id_set = {str(pid) for pid in pack_ids}
        filtered = [
            item for item in all_items
            if isinstance(item, dict) and (
                str(item.get("source_id", "")) in pack_id_set
                or str(item.get("target_id", "")) in pack_id_set
                or str(item.get("region_id", "")) in pack_id_set
            )
        ]
        return json.dumps(filtered, ensure_ascii=False, indent=2)
    except (json.JSONDecodeError, TypeError):
        return all_context_json


async def _mark_run_failed(run_id: uuid.UUID, error: str) -> None:
    from app.database import AsyncSessionLocal
    try:
        if AsyncSessionLocal is None: return
        async with AsyncSessionLocal() as s:
            r = await s.get(CircuitExtractionRun, run_id)
            if r and r.status not in ("succeeded", "failed", "cancelled"):
                r.status = "failed"
                r.completed_at = datetime.now(timezone.utc)
                errs = list(r.errors_json or [])
                errs.append(error)
                r.errors_json = to_jsonable(errs)
                await s.commit()
    except Exception:
        logger.exception("[circuit-extraction] mark_failed run=%s", run_id)


def _to_uuid(val: Any) -> uuid.UUID | None:
    if val is None: return None
    try: return uuid.UUID(str(val))
    except (ValueError, TypeError): return None


def _is_constraint_error(exc: Exception) -> bool:
    """Check if exception is a DB constraint violation (UniqueViolation, IntegrityError)."""
    name = type(exc).__name__
    module = type(exc).__module__
    return 'IntegrityError' in name or 'UniqueViolation' in name or 'CheckViolation' in name or 'psycopg' in module


def _safe_region_id(val: Any, candidates: dict[uuid.UUID, Any]) -> uuid.UUID | None:
    uid = _to_uuid(val)
    return uid if uid is not None and uid in candidates else None


# Valid circuit_type values per chk_mirror_circuit_type constraint (migration 022)
_VALID_CIRCUIT_TYPES = {
    'sensory_circuit', 'motor_circuit', 'limbic_circuit', 'cognitive_control_circuit',
    'default_mode_related', 'salience_related', 'memory_related', 'reward_related',
    'language_related', 'attention_related', 'uncertain_circuit', 'unknown',
}

# Map LLM output circuit types to valid DB values
_CIRCUIT_TYPE_NORMALIZE: dict[str, str] = {
    'sensory_pathway': 'sensory_circuit',
    'motor_pathway': 'motor_circuit',
    'associative_pathway': 'cognitive_control_circuit',
    'limbic_circuit': 'limbic_circuit',
    'cognitive_circuit': 'cognitive_control_circuit',
    'language_circuit': 'language_related',
    'default_mode_circuit': 'default_mode_related',
    'salience_circuit': 'salience_related',
    'attention_circuit': 'attention_related',
    'thalamocortical_loop': 'sensory_circuit',
    'basal_ganglia_loop': 'motor_circuit',
    'cerebellar_loop': 'motor_circuit',
    'brainstem_circuit': 'sensory_circuit',
    'memory_circuit': 'memory_related',
    'emotion_circuit': 'limbic_circuit',
    'visual_circuit': 'sensory_circuit',
    'auditory_circuit': 'sensory_circuit',
    'somatosensory_circuit': 'sensory_circuit',
    'multisensory_integration': 'cognitive_control_circuit',
    'reward_circuit': 'reward_related',
    'motor_control': 'motor_circuit',
    'executive_function': 'cognitive_control_circuit',
    'emotional_regulation': 'limbic_circuit',
    'functional': 'uncertain_circuit',
    'other': 'uncertain_circuit',
}


def _normalize_circuit_type(raw_type: str) -> str:
    """Map LLM-generated circuit_type to a DB-valid value."""
    if not raw_type:
        return 'uncertain_circuit'
    key = raw_type.strip().lower()
    if key in _VALID_CIRCUIT_TYPES:
        return key
    mapped = _CIRCUIT_TYPE_NORMALIZE.get(key)
    if mapped:
        return mapped
    for valid in _VALID_CIRCUIT_TYPES:
        if valid in key or key in valid:
            return valid
    return 'uncertain_circuit'


# Valid values per DB constraints (migration 026)
_VALID_STEP_TYPES = {'region', 'region_group', 'relay', 'hub', 'modulator', 'functional_stage', 'unknown'}
_VALID_STEP_ROLES = {'source', 'target', 'relay', 'hub', 'modulator', 'participant', 'unknown'}

_STEP_ROLE_NORMALIZE: dict[str, str] = {
    'initiator': 'source', 'integrator': 'hub', 'output': 'target',
    'input': 'source', 'processor': 'hub', 'regulator': 'modulator',
}


def _normalize_step_type(raw: str) -> str:
    v = (raw or '').strip().lower()
    return v if v in _VALID_STEP_TYPES else 'unknown'


def _normalize_step_role(raw: str) -> str:
    v = (raw or '').strip().lower()
    if v in _VALID_STEP_ROLES:
        return v
    return _STEP_ROLE_NORMALIZE.get(v, 'unknown')


def _meta_from_candidate(cand: Any) -> dict[str, Any]:
    """Extract provenance fields from a CandidateBrainRegion or region_map dict."""
    if cand is None:
        return {
            "granularity_level": "macro",
            "granularity_family": None,
            "source_atlas": "",
            "source_version": None,
            "resource_id": None,
            "batch_id": None,
        }
    if isinstance(cand, dict):
        return {
            "granularity_level": cand.get("granularity_level") or "macro",
            "granularity_family": cand.get("granularity_family"),
            "source_atlas": cand.get("atlas") or cand.get("source_atlas") or "",
            "source_version": cand.get("source_version"),
            "resource_id": cand.get("resource_id"),
            "batch_id": cand.get("batch_id"),
        }
    return {
        "granularity_level": getattr(cand, "granularity_level", None) or "macro",
        "granularity_family": getattr(cand, "granularity_family", None),
        "source_atlas": getattr(cand, "source_atlas", None) or "",
        "source_version": getattr(cand, "source_version", None),
        "resource_id": getattr(cand, "resource_id", None),
        "batch_id": getattr(cand, "batch_id", None),
    }


def _build_circuit_orm(
    *,
    cdata: dict[str, Any],
    member_rids: list[Any],
    meta: dict[str, Any],
    created_by: str | None = None,
) -> MirrorRegionCircuit:
    """Build a MirrorRegionCircuit with full datacenter field coverage."""
    conf = float(cdata.get("confidence", 0.7))
    full_name = str(cdata.get("circuit_name", ""))[:512]
    # Derive canonical start/end from member_region_ids (first=start, last=end)
    start_rid = member_rids[0] if member_rids else None
    end_rid = member_rids[-1] if len(member_rids) > 1 else (member_rids[0] if member_rids else None)
    return MirrorRegionCircuit(
        circuit_name=full_name,
        name_cn=str(cdata.get("name_cn", ""))[:512] or full_name,
        circuit_type=_normalize_circuit_type(str(cdata.get("circuit_type", ""))),
        function_association=str(cdata.get("function_association", ""))[:512] or None,
        description=str(cdata.get("description", ""))[:1024] or None,
        confidence=conf,
        circuit_strength=float(cdata.get("circuit_strength", conf)),
        evidence_text=str(cdata.get("evidence_text", ""))[:4000] or None,
        uncertainty_reason=str(cdata.get("uncertainty_reason", ""))[:2000] or None,
        granularity_level=meta["granularity_level"],
        granularity_family=meta.get("granularity_family") or meta["granularity_level"],
        source_atlas=meta["source_atlas"] or "",
        source_version=meta.get("source_version"),
        resource_id=meta.get("resource_id"),
        batch_id=meta.get("batch_id"),
        canonical_start_region_id=start_rid,
        canonical_end_region_id=end_rid,
        mirror_status=MirrorStatus.llm_suggested,
        review_status="pending",
        raw_payload_json=to_jsonable(cdata) if isinstance(cdata, dict) else {},
        normalized_payload_json=to_jsonable({
            "member_region_ids": [str(r) for r in member_rids],
            "circuit_type": cdata.get("circuit_type"),
            "steps_count": len(cdata.get("steps") or []),
        }),
        created_by=created_by,
    )


def _add_circuit_memberships(
    session: Any,
    circuit: MirrorRegionCircuit,
    member_rids: list[Any],
    steps: list[dict[str, Any]] | None = None,
) -> None:
    """Write mirror_circuit_regions membership rows for a circuit."""
    role_by_rid: dict[str, str] = {}
    for sdata in steps or []:
        rid = str(sdata.get("region_id", ""))
        if rid:
            role_by_rid[rid] = _normalize_step_role(str(sdata.get("role", "")))
    for idx, rid in enumerate(member_rids):
        try:
            rid_uuid = rid if isinstance(rid, uuid.UUID) else uuid.UUID(str(rid))
        except (ValueError, TypeError):
            continue
        session.add(
            MirrorCircuitRegion(
                circuit_id=circuit.id,
                region_candidate_id=rid_uuid,
                role=role_by_rid.get(str(rid_uuid), "participant"),
                sort_order=idx,
            )
        )


def _build_step_orm(
    *,
    circuit: MirrorRegionCircuit,
    sdata: dict[str, Any],
    region_candidate_id: uuid.UUID | None,
) -> MirrorCircuitStep:
    return MirrorCircuitStep(
        circuit_id=circuit.id,
        step_order=int(sdata.get("step_order", 1)),
        step_name=str(sdata.get("step_name", ""))[:256],
        step_type=_normalize_step_type(str(sdata.get("step_type", ""))),
        role=_normalize_step_role(str(sdata.get("role", ""))),
        description=str(sdata.get("description", ""))[:1024] or None,
        confidence=float(sdata.get("confidence", 0.7)),
        evidence_text=str(sdata.get("evidence_text", ""))[:4000] or None,
        uncertainty_reason=str(sdata.get("uncertainty_reason", ""))[:2000] or None,
        region_candidate_id=region_candidate_id,
        granularity_level=circuit.granularity_level,
        granularity_family=circuit.granularity_family,
        source_atlas=circuit.source_atlas,
        source_version=circuit.source_version,
        resource_id=circuit.resource_id,
        batch_id=circuit.batch_id,
        mirror_status=MirrorStatus.llm_suggested,
        review_status="pending",
        raw_payload_json=to_jsonable(sdata),
        created_by=circuit.created_by,
    )


def _build_function_orm(
    *,
    circuit: MirrorRegionCircuit,
    fdata: dict[str, Any],
) -> MirrorCircuitFunction:
    return MirrorCircuitFunction(
        circuit_id=circuit.id,
        function_term_en=str(fdata.get("function_term_en", ""))[:512],
        function_term_cn=str(fdata.get("function_term_cn", ""))[:512] or None,
        function_domain=str(fdata.get("function_domain", ""))[:256] or None,
        function_role=str(fdata.get("function_role", ""))[:256] or None,
        effect_type=str(fdata.get("effect_type", ""))[:128] or None,
        description=str(fdata.get("description", ""))[:1024] or None,
        confidence=float(fdata.get("confidence", 0.7)),
        evidence_text=str(fdata.get("evidence_text", ""))[:4000] or None,
        uncertainty_reason=str(fdata.get("uncertainty_reason", ""))[:2000] or None,
        granularity_level=circuit.granularity_level,
        granularity_family=circuit.granularity_family,
        source_atlas=circuit.source_atlas,
        source_version=circuit.source_version,
        resource_id=circuit.resource_id,
        batch_id=circuit.batch_id,
        mirror_status=MirrorStatus.llm_suggested,
        review_status="pending",
        raw_payload_json=to_jsonable(fdata),
        created_by=circuit.created_by,
    )


_UUID_FRAGMENT_RE = __import__('re').compile(r'[0-9a-f]{8}', __import__('re').IGNORECASE)


_ALIAS_PATTERN_RE = __import__('re').compile(r'(?:^|_)[rR]\d+(?:$|_)')
_UNKNOWN_RE = __import__('re').compile(r'(?:^|_)unknown(?:$|_)', __import__('re').IGNORECASE)


def _is_valid_circuit_name(name: str) -> bool:
    """Reject circuit names with UUID fragments, aliases, or Chinese characters."""
    if not name or not name.strip():
        return False
    if _UUID_FRAGMENT_RE.search(name):
        return False
    if any('一' <= c <= '鿿' for c in name):
        return False
    return True


def _resolve_alias(alias_or_uuid: str, alias_to_uuid: dict) -> uuid.UUID | None:
    """Resolve LLM output alias (R1) or full UUID to a UUID object."""
    if not alias_or_uuid:
        return None
    # If it looks like a full UUID, convert directly
    if len(alias_or_uuid) > 30 and '-' in alias_or_uuid:
        return _to_uuid(alias_or_uuid)
    # Try alias lookup → get full UUID string → convert to UUID
    resolved = alias_to_uuid.get(alias_or_uuid)
    return _to_uuid(resolved) if resolved else None


def _build_fallback_circuit_name(region_map: dict, region_ids: list) -> str:
    """Generate a readable fallback circuit name from member region names."""
    names = []
    for rid in region_ids[:3]:
        info = region_map.get(str(rid), {})
        name = info.get('name', '') or str(rid)[:8]
        names.append(name.replace(' ', '_').lower())
    suffix = 'circuit' if len(region_ids) <= 3 else 'network'
    return '_'.join(names) + '_' + suffix if names else 'unknown_circuit'


# ── Connection-based circuit extraction ────────────────────────────────────────

_CONN_CIRCUIT_PROMPT = (
    "You are a neuroscientist analyzing brain connectivity data. "
    "Below is a CONNECTION GRAPH and REGION DETAILS mapping.\n\n"
    "TASK: Identify ALL possible brain circuits by finding meaningful paths through this graph.\n"
    "MAXIMIZE OUTPUT — every connection should contribute to at least one circuit.\n\n"
    "HOW TO FIND CIRCUITS:\n"
    "1. Multi-hop chains: R1→R2→R3 forms a 3-region pathway\n"
    "2. Hub-and-spoke: one region connects to many → divergent/convergent circuits\n"
    "3. Reciprocal pairs: R1→R2 and R2→R1 → feedback loop\n"
    "4. 2-region pairs from a single edge are VALID circuits\n"
    "5. Use neuroanatomical knowledge to infer related multi-region circuits\n\n"
    "CIRCUIT TYPES (use exact values): sensory_circuit, motor_circuit, limbic_circuit, "
    "cognitive_control_circuit, default_mode_related, salience_related, memory_related, "
    "reward_related, language_related, attention_related, uncertain_circuit, unknown\n\n"
    "CRITICAL NAMING RULES:\n"
    "- circuit_name MUST use English region names from the REGION DETAILS 'name' field\n"
    "- Example: R1=hippocampus,R2=amygdala → name='hippocampal_amygdalar_memory_circuit'\n"
    "- NEVER use R1/R2 aliases, UUIDs, hex strings, or 'unknown' in circuit_name\n"
    "- name_cn: provide Chinese circuit name\n\n"
    "QUALITY / REQUIRED FIELDS:\n"
    "- At least 5 circuits per pack when possible (up to 20). Speculative (0.05-0.5) are valuable.\n"
    "- evidence_text: brief reasoning basis (required)\n"
    "- uncertainty_reason: when confidence < 0.5 (required for low confidence)\n"
    "- confidence: 0.8+=strong, 0.5-0.8=moderate, 0.05-0.5=speculative\n"
    "- Each circuit must have 2-8 member regions\n"
    "- member_region_ids and step.region_id MUST use aliases like R1, R2\n\n"
    "CONNECTION GRAPH:\n{graph_text}\n\n"
    "REGION DETAILS (use alias for member_region_ids/region_id, use name for circuit_name):\n{regions_json}\n\n"
    "OUTPUT ONLY VALID JSON (no markdown, no prose):\n"
    '{{"circuits":[{{"circuit_name":"hippocampal_amygdalar_memory_circuit","name_cn":"海马杏仁核记忆回路",'
    '"circuit_type":"memory_related","function_association":"emotional_memory_consolidation",'
    '"description":"Hippocampus and amygdala interact to consolidate emotional memories",'
    '"confidence":0.75,"circuit_strength":0.7,'
    '"evidence_text":"Bidirectional hippocampal-amygdala paths are classic emotional memory circuitry",'
    '"uncertainty_reason":"layer specificity incomplete",'
    '"member_region_ids":["R1","R2","R3"],'
    '"steps":[{{"step_order":1,"step_name":"Hippocampus to Amygdala","step_type":"region","role":"source",'
    '"region_id":"R1","confidence":0.8,"evidence_text":"source node of emotional memory path",'
    '"functions":[{{"function_term_en":"memory_encoding","function_term_cn":"记忆编码",'
    '"function_domain":"memory","function_role":"execution","effect_type":"excitatory",'
    '"confidence":0.8,"evidence_text":"encoding role at circuit origin"}}]}}]}}]}}'
)


async def _resolve_connection_graph(session, connection_ids: list) -> dict:
    """Load Mirror connections and build a graph adjacency structure."""
    from app.models.mirror_kg import MirrorRegionConnection
    q = select(MirrorRegionConnection).where(
        MirrorRegionConnection.id.in_(connection_ids)
    )
    result = await session.execute(q)
    rows = result.scalars().all()

    # Build region registry
    region_ids: set = set()
    edges: list[dict] = []
    for r in rows:
        region_ids.add(r.source_region_candidate_id)
        region_ids.add(r.target_region_candidate_id)
        edges.append({
            "connection_id": str(r.id),
            "source_id": str(r.source_region_candidate_id),
            "target_id": str(r.target_region_candidate_id),
            "type": r.connection_type or "unknown",
            "strength": r.strength or "unknown",
        })

    # Load region labels
    from app.models.candidate import CandidateBrainRegion
    region_list = list(region_ids)
    region_map: dict = {}
    next_fallback = 1
    if region_list:
        rq = select(CandidateBrainRegion).where(CandidateBrainRegion.id.in_(region_list))
        rr = await session.execute(rq)
        for c in rr.scalars().all():
            name = c.cn_name or c.en_name or c.std_name or c.raw_name
            if not name:
                name = f"region_{next_fallback}"
                next_fallback += 1
            region_map[str(c.id)] = {
                "name": name,
                "atlas": c.source_atlas or "",
                "source_atlas": c.source_atlas or "",
                "source_version": c.source_version,
                "granularity_level": c.granularity_level or "macro",
                "granularity_family": c.granularity_family or c.granularity_level,
                "resource_id": c.resource_id,
                "batch_id": c.batch_id,
            }

    # Build graph text
    lines = []
    for e in edges:
        src_name = region_map.get(e["source_id"], {}).get("name", e["source_id"][:8])
        tgt_name = region_map.get(e["target_id"], {}).get("name", e["target_id"][:8])
        lines.append(f"{src_name} → {tgt_name}")

    return {
        "edges": edges,
        "regions": {
            str(rid): region_map.get(str(rid), {"name": str(rid)[:8], "atlas": ""})
            for rid in region_ids
        },
        "graph_text": "\n".join(lines),
    }


def _pack_connections_by_graph(edges: list[dict], connections_per_pack: int) -> list[list[dict]]:
    """Group connections into packs by graph connectivity (connected components / neighborhoods)."""
    if not edges:
        return []
    # Build adjacency: region_id → set of edge indices
    adj: dict[str, set] = {}
    for i, e in enumerate(edges):
        adj.setdefault(e["source_id"], set()).add(i)
        adj.setdefault(e["target_id"], set()).add(i)

    visited: set = set()
    packs: list[list[dict]] = []
    current_pack: list[dict] = []

    # Greedy: for each unvisited edge, add it + its neighbors until pack is full
    for i, e in enumerate(edges):
        if i in visited:
            continue
        if len(current_pack) >= connections_per_pack:
            packs.append(current_pack)
            current_pack = []
        current_pack.append(e)
        visited.add(i)
        # Add neighboring edges (share a region)
        neighbors = adj.get(e["source_id"], set()) | adj.get(e["target_id"], set())
        for ni in neighbors:
            if ni not in visited and len(current_pack) < connections_per_pack:
                current_pack.append(edges[ni])
                visited.add(ni)

    if current_pack:
        packs.append(current_pack)
    return packs


def _build_connection_graph_text(edges: list[dict], region_map: dict, alias_map: dict) -> str:
    """Build connection graph text using ONLY aliases (no names, no UUIDs)."""
    lines = []
    for e in edges:
        src_alias = alias_map.get(e["source_id"], "?")
        tgt_alias = alias_map.get(e["target_id"], "?")
        lines.append(f"{src_alias} → {tgt_alias}")
    return "\n".join(lines)


def _build_region_lookup_json(region_map: dict, region_ids: set) -> tuple[str, dict]:
    """Build region JSON with aliases only + return alias→UUID mapping for backend lookup."""
    regions = []
    alias_to_uuid = {}
    sorted_ids = sorted(region_ids)
    for i, rid in enumerate(sorted_ids):
        alias = f"R{i+1}"
        alias_to_uuid[alias] = str(rid)
        info = region_map.get(str(rid), {"name": f"unknown_region", "atlas": ""})
        regions.append({
            "alias": alias,
            "name": info.get("name", ""),
            "atlas": info.get("atlas", ""),
        })
    return json.dumps(regions, ensure_ascii=False, indent=2), alias_to_uuid


# ── Public API ──────────────────────────────────────────────────────────────

def build_circuit_pack_plan(
    candidate_count: int,
    candidates_per_pack: int,
    shuffle_rounds: int,
) -> dict[str, int | list[int]]:
    """Shared pack plan calculation used by both Dry Run and formal execution."""
    pack_size = max(1, candidates_per_pack)
    rounds = max(1, shuffle_rounds)
    packs_per_round = (candidate_count + pack_size - 1) // pack_size  # ceil
    total_packs = packs_per_round * rounds
    pack_sizes: list[int] = []
    for r in range(rounds):
        for i in range(packs_per_round):
            start = i * pack_size
            pack_sizes.append(min(pack_size, candidate_count - start))
    return {
        "candidate_count": candidate_count,
        "candidates_per_pack": pack_size,
        "shuffle_rounds": rounds,
        "per_round_pack_count": packs_per_round,
        "pack_count": total_packs,
        "pack_sizes": pack_sizes,
    }


async def run_circuit_pack_extraction(
    session: AsyncSession,
    request: CircuitExtractionRequest,
) -> CircuitExtractionStartResponse:
    is_connection_mode = bool(request.connection_ids)
    if is_connection_mode:
        # Connection-based: resolve connections first to count packs
        conn_ids = list(dict.fromkeys(request.connection_ids))
        graph = await _resolve_connection_graph(session, conn_ids)
        edges = graph["edges"]
        packs = _pack_connections_by_graph(edges, request.candidates_per_pack)
        estimated = len(packs)
        input_count = len(conn_ids)
    else:
        candidate_ids = list(dict.fromkeys(request.candidate_ids))
        plan = build_circuit_pack_plan(
            len(candidate_ids), request.candidates_per_pack, request.shuffle_rounds,
        )
        estimated = plan["pack_count"]
        input_count = len(candidate_ids)

    run = CircuitExtractionRun(
        provider=request.provider, model_name=request.model_name,
        candidate_count=input_count, status="pending",
        request_json=to_jsonable(request.model_dump(mode="json")),
        result_summary_json=to_jsonable(dict(
            processed_packs=0, total_packs=estimated,
            circuit_created=0, step_created=0, function_created=0,
        )),
    )
    session.add(run)
    await session.commit()
    await session.refresh(run)
    est_llm_calls = estimated
    est_input = estimated * 2000
    est_output = estimated * 800
    est_cost = (est_input / 1_000_000) * 1.0 + (est_output / 1_000_000) * 2.0
    return CircuitExtractionStartResponse(
        run_id=run.id, status="pending", provider=request.provider,
        model_name=request.model_name, candidate_count=input_count,
        dry_run=False, estimated_packs=estimated,
        estimated_llm_calls=est_llm_calls, estimated_input_tokens=est_input,
        estimated_output_tokens=est_output, estimated_cost_cny=round(est_cost, 4),
    )


async def _execute_connection_based_extraction(
    session: AsyncSession,
    run: CircuitExtractionRun,
    request: CircuitExtractionRequest,
    provider_key: str,
    resolved_model: str,
    tier_status: str,
) -> None:
    """Connection-based circuit extraction: resolve connection graph, pack by connectivity, call LLM."""
    from app.database import AsyncSessionLocal
    conn_ids = list(dict.fromkeys(request.connection_ids))
    graph = await _resolve_connection_graph(session, conn_ids)
    edge_packs = _pack_connections_by_graph(graph["edges"], max(5, request.candidates_per_pack))
    region_map = graph["regions"]
    run.pack_count = len(edge_packs)
    await session.commit()
    logger.info("[circuit-extraction][conn] %d connections -> %d packs (size=%d)",
                len(conn_ids), len(edge_packs), request.candidates_per_pack)
    print(f"[circuit-extraction] connection mode: {len(conn_ids)} connections -> {len(edge_packs)} packs", flush=True)

    total_circuits = total_steps = total_functions = 0
    succeeded = no_findings = failed = 0
    pack_results: list[dict] = [{} for _ in edge_packs]
    errors: list[str] = []
    warnings: list[str] = []
    total_prompt_tokens = 0
    total_completion_tokens = 0
    counters_lock = asyncio.Lock()

    for pi, edge_pack in enumerate(edge_packs):
        if is_cancelling(run.id):
            for skipped in range(pi, len(edge_packs)):
                pack_results[skipped] = {"pack_index": skipped, "status": "skipped", "failed_reason": "cancelled"}
            break

        pack_region_ids: set[str] = set()
        for e in edge_pack:
            pack_region_ids.add(e["source_id"])
            pack_region_ids.add(e["target_id"])
        # Build alias map: region_id → R1, R2, ...
        alias_map = {rid: f"R{i+1}" for i, rid in enumerate(sorted(pack_region_ids))}
        graph_text = _build_connection_graph_text(edge_pack, region_map, alias_map)
        regions_json, alias_to_uuid = _build_region_lookup_json(region_map, pack_region_ids)

        local_circuits = local_steps = local_fns = 0
        local_created = local_merged = local_skipped = 0
        prompt_tok = completion_tok = 0

        try:
            user_prompt = _CONN_CIRCUIT_PROMPT.format(graph_text=graph_text, regions_json=regions_json)
            system_prompt = _get_circuit_system_prompt()
            llm = get_llm_provider(provider_key)
            response = await llm.complete_json(
                model=resolved_model, system_prompt=system_prompt,
                user_prompt=user_prompt, temperature=request.temperature,
                max_tokens=request.max_tokens, timeout_seconds=120,
            )
            parsed = response.parsed_json
            raw_text = response.raw_text or ""
            prompt_tok = (response.usage.prompt_tokens or 0) if response.usage else 0
            completion_tok = (response.usage.completion_tokens or 0) if response.usage else 0
            if parsed is None and raw_text:
                logger.warning("[circuit-extraction][conn] pack %s/%s JSON parse failed, raw_text[:500]=%s",
                               pi + 1, len(edge_packs), raw_text[:500])
                cleaned = raw_text.strip()
                if cleaned.startswith("```"):
                    lines = cleaned.split("\n")
                    lines = [l for l in lines if not l.startswith("```")]
                    cleaned = "\n".join(lines).strip()
                try:
                    parsed = json.loads(cleaned)
                    logger.info("[circuit-extraction][conn] pack %s/%s fallback parse succeeded", pi + 1, len(edge_packs))
                except json.JSONDecodeError:
                    pass
            if parsed is None:
                parsed = {}
        except Exception as exc:
            logger.warning("[circuit-extraction][conn] pack %s/%s LLM failed: %s", pi + 1, len(edge_packs), exc)
            async with counters_lock:
                failed += 1
                run.failed_packs = failed
            pack_results[pi] = {"pack_index": pi, "status": "failed", "failed_reason": str(exc)[:200], "warnings": []}
            continue

        circuits_data = parsed.get("circuits", [])
        logger.info("[circuit-extraction][conn] pack %s/%s circuits_count=%s",
                     pi + 1, len(edge_packs), len(circuits_data) if isinstance(circuits_data, list) else '?')
        if circuits_data:
            try:
                async with AsyncSessionLocal() as psession:
                    circuit_names = [str(c.get("circuit_name", ""))[:256] for c in circuits_data if c.get("circuit_name")]
                    existing_map: dict = {}
                    if circuit_names:
                        from app.models.mirror_kg import MirrorRegionCircuit as MRC
                        eq = select(MRC).where(MRC.circuit_name.in_(circuit_names))
                        er = await psession.execute(eq)
                        existing_map = {r.circuit_name: r for r in er.scalars().all()}

                    for cdata in circuits_data:
                        cname = str(cdata.get("circuit_name", ""))[:512]
                        if not _is_valid_circuit_name(cname):
                            local_skipped += 1
                            print(f"[circuit-extraction][conn] REJECTED invalid name: {cname[:120]}", flush=True)
                            continue
                        existing = existing_map.get(cname)
                        if existing and request.skip_existing:
                            local_skipped += 1
                            continue
                        if existing:
                            new_conf = float(cdata.get("confidence", 0.7))
                            if new_conf > (existing.confidence or 0):
                                existing.confidence = new_conf
                                existing.description = str(cdata.get("description", ""))[:1024] or existing.description
                                psession.add(existing)
                                local_merged += 1
                            else:
                                local_skipped += 1
                            continue

                        member_rids = [_resolve_alias(str(rid), alias_to_uuid) for rid in cdata.get("member_region_ids", [])]
                        member_rids = [r for r in member_rids if r is not None]
                        sp = await psession.begin_nested()
                        try:
                            seed_rid = list(pack_region_ids)[0] if pack_region_ids else ""
                            meta = _meta_from_candidate(region_map.get(str(seed_rid)))
                            gran = meta["granularity_level"]
                            full_name = str(cdata.get("circuit_name", ""))[:512]
                            existing = await psession.execute(
                                select(MirrorRegionCircuit).where(
                                    MirrorRegionCircuit.circuit_name == full_name,
                                    MirrorRegionCircuit.granularity_level == gran,
                                )
                            )
                            existing = existing.scalar_one_or_none()
                            if existing:
                                new_conf = float(cdata.get("confidence", 0.7))
                                if new_conf > (existing.confidence or 0):
                                    existing.confidence = new_conf
                                    existing.description = str(cdata.get("description", ""))[:1024] or existing.description
                                    existing.circuit_strength = float(cdata.get("circuit_strength", new_conf))
                                    existing.name_cn = str(cdata.get("name_cn", ""))[:512] or existing.name_cn
                                    if not existing.evidence_text:
                                        existing.evidence_text = str(cdata.get("evidence_text", ""))[:4000] or existing.evidence_text
                                    if not existing.uncertainty_reason:
                                        existing.uncertainty_reason = str(cdata.get("uncertainty_reason", ""))[:2000] or existing.uncertainty_reason
                                    existing.mirror_status = MirrorStatus.llm_suggested
                                    psession.add(existing)
                                local_merged += 1
                                local_circuits += 1
                                circuit = existing
                            else:
                                circuit = _build_circuit_orm(
                                    cdata=cdata,
                                    member_rids=member_rids,
                                    meta=meta,
                                    created_by=f"circuit_pack:{run.id}",
                                )
                                psession.add(circuit)
                                await psession.flush()
                                _add_circuit_memberships(psession, circuit, member_rids, cdata.get("steps"))
                                local_circuits += 1
                                local_created += 1
                        except Exception as exc:
                            await sp.rollback()
                            if not _is_constraint_error(exc):
                                raise
                            eq2 = select(MirrorRegionCircuit).where(MirrorRegionCircuit.circuit_name == cname)
                            er2 = await psession.execute(eq2)
                            existing_circ = er2.scalars().first()
                            if existing_circ:
                                new_conf = float(cdata.get("confidence", 0.7))
                                if new_conf > (existing_circ.confidence or 0):
                                    existing_circ.confidence = new_conf
                                    existing_circ.description = str(cdata.get("description", ""))[:1024] or existing_circ.description
                                    existing_circ.function_association = str(cdata.get("function_association", ""))[:512] or existing_circ.function_association
                                    existing_circ.circuit_type = _normalize_circuit_type(str(cdata.get("circuit_type", ""))) or existing_circ.circuit_type
                                    existing_circ.mirror_status = MirrorStatus.llm_suggested
                                    psession.add(existing_circ)
                                    await psession.flush()
                                    local_merged += 1
                                else:
                                    local_skipped += 1
                                circuit = existing_circ
                            else:
                                local_skipped += 1
                                continue

                        for sdata in cdata.get("steps", []):
                            step_rid_raw = str(sdata.get("region_id", ""))
                            step_rid_str = _resolve_alias(step_rid_raw, alias_to_uuid) or step_rid_raw
                            step_rid = _to_uuid(step_rid_str)
                            step = _build_step_orm(
                                circuit=circuit, sdata=sdata, region_candidate_id=step_rid,
                            )
                            psession.add(step)
                            await psession.flush()
                            local_steps += 1

                            for fdata in sdata.get("functions", []):
                                fn = _build_function_orm(circuit=circuit, fdata=fdata)
                                psession.add(fn)
                                local_fns += 1
                        await psession.commit()
            except Exception as exc:
                logger.warning("[circuit-extraction][conn] pack %s/%s DB write failed: %s", pi + 1, len(edge_packs), exc)
                async with counters_lock:
                    failed += 1
                    run.failed_packs = failed
                pack_results[pi] = {"pack_index": pi, "status": "failed", "failed_reason": str(exc)[:200], "warnings": []}
                continue

        pack_created = local_circuits + local_steps + local_fns
        async with counters_lock:
            total_circuits += local_circuits
            total_steps += local_steps
            total_functions += local_fns
            total_prompt_tokens += prompt_tok
            total_completion_tokens += completion_tok
            if pack_created > 0:
                succeeded += 1
                pack_status = "succeeded"
            else:
                no_findings += 1
                pack_status = "no_findings"
                if not circuits_data:
                    warnings.append(f"pack {pi + 1}: LLM returned 0 circuits")
            run.succeeded_packs = succeeded
            run.no_findings_packs = no_findings
            run.failed_packs = failed
            run.circuit_count = total_circuits
            run.step_count = total_steps
            run.function_count = total_functions
            processed = succeeded + no_findings + failed
            run.result_summary_json = to_jsonable(dict(
                processed_packs=processed, total_packs=len(edge_packs),
                circuit_created=total_circuits, step_created=total_steps,
                function_created=total_functions,
                succeeded_packs=succeeded, no_findings_packs=no_findings, failed_packs=failed,
            ))
            await session.commit()
        logger.info("[circuit-extraction][conn] pack %s/%s status=%s circuits=%s steps=%s functions=%s",
                     pi + 1, len(edge_packs), pack_status, local_circuits, local_steps, local_fns)
        pack_results[pi] = {
            "pack_index": pi, "status": pack_status,
            "parsed_circuit_count": local_circuits, "parsed_step_count": local_steps,
            "parsed_function_count": local_fns,
            "mirror_created_count": local_created, "mirror_merged_count": local_merged,
            "mirror_skipped_count": local_skipped,
            "prompt_tokens": prompt_tok, "completion_tokens": completion_tok,
            "failed_reason": None, "warnings": [],
        }

    # Finalize
    run.succeeded_packs = succeeded
    run.no_findings_packs = no_findings
    run.failed_packs = failed
    run.circuit_count = total_circuits
    run.step_count = total_steps
    run.function_count = total_functions
    if is_cancelling(run.id):
        run.status = "cancelled"
    else:
        run.status = "partially_succeeded" if (failed > 0 or errors) else "succeeded"
    run.completed_at = datetime.now(timezone.utc)
    run.result_summary_json = to_jsonable(dict(
        circuit_created=total_circuits, step_created=total_steps,
        function_created=total_functions, pack_count=len(edge_packs),
        succeeded_packs=succeeded, no_findings_packs=no_findings, failed_packs=failed,
        model_call_count=len(edge_packs), processed_packs=len(edge_packs), total_packs=len(edge_packs),
    ))
    run.usage_summary_json = to_jsonable(dict(
        prompt_tokens=total_prompt_tokens, completion_tokens=total_completion_tokens,
        total_tokens=total_prompt_tokens + total_completion_tokens,
        estimated_cost_cny=round(
            (total_prompt_tokens / 1_000_000) * 1.0 +
            (total_completion_tokens / 1_000_000) * 2.0, 4,
        ),
    ))
    run.pack_results_json = to_jsonable(pack_results)
    run.errors_json = to_jsonable(errors)
    run.warnings_json = to_jsonable(warnings)
    logger.info("[circuit-extraction][conn] DONE succeeded=%s no_findings=%s failed=%s tokens=%s",
                 succeeded, no_findings, failed, total_prompt_tokens + total_completion_tokens)
    await session.commit()
    await clear_cancel_registry(run.id)


async def execute_circuit_extraction_background(
    run_id: uuid.UUID,
    request_payload: dict[str, Any],
) -> None:
    import sys
    print(f"[circuit-extraction] BACKGROUND START run={run_id}", flush=True)
    from app.database import AsyncSessionLocal
    logger.info("[circuit-extraction] background start run=%s", run_id)

    if AsyncSessionLocal is None:
        logger.error("[circuit-extraction] AsyncSessionLocal unavailable")
        print(f"[circuit-extraction] FATAL AsyncSessionLocal=None run={run_id}", flush=True)
        return

    try:
        request = CircuitExtractionRequest.model_validate(request_payload)
    except Exception:
        logger.exception("[circuit-extraction] invalid payload run=%s", run_id)
        print(f"[circuit-extraction] FATAL invalid payload run={run_id}", flush=True)
        await _mark_run_failed(run_id, "Invalid request payload")
        return

    try:
        print(f"[circuit-extraction] entering main loop run={run_id}", flush=True)
        async with AsyncSessionLocal() as session:
            run = await session.get(CircuitExtractionRun, run_id)
            if run is None:
                logger.error("[circuit-extraction] run not found: %s", run_id)
                return
            if is_cancelling(run_id):
                logger.info("[circuit-extraction] already cancelled: %s", run_id)
                return

            run.status = "running"
            run.started_at = datetime.now(timezone.utc)
            await session.commit()

            provider_key = request.provider.lower()
            resolved_model = request.model_name or "deepseek-chat"
            tier_status, _ = _resolve_model_status(resolved_model)
            is_connection_mode = bool(request.connection_ids)

            if is_connection_mode:
                await _execute_connection_based_extraction(
                    session, run, request, provider_key, resolved_model, tier_status,
                )
                return

            # ── Region-based circuit extraction (original path) ─────────────────
            # Load candidates
            q = select(CandidateBrainRegion).where(CandidateBrainRegion.id.in_(request.candidate_ids))
            result = await session.execute(q)
            candidates: dict[uuid.UUID, Any] = {r.id: r for r in result.scalars().all()}

            # Multi-round shuffle: each brain region appears in N different packs
            ids = [cid for cid in request.candidate_ids if cid in candidates]
            rounds = request.shuffle_rounds
            all_packs = []
            for r in range(rounds):
                shuffled = list(ids)
                random.shuffle(shuffled)
                round_packs = [shuffled[i:i + request.candidates_per_pack] for i in range(0, len(shuffled), request.candidates_per_pack)]
                all_packs.extend(round_packs)
            packs = all_packs
            run.pack_count = len(packs)
            await session.commit()
            logger.info("[circuit-extraction] %d candidates x %d rounds -> %d packs (size=%d)",
                         len(ids), rounds, len(packs), request.candidates_per_pack)

            # ── Pre-load connection & function context from Mirror KG ──
            all_candidate_ids = [cid for cid in ids]
            all_connections_json = await _build_connections_context(session, all_candidate_ids)
            all_functions_json = await _build_functions_context(session, all_candidate_ids)
            logger.info("[circuit-extraction] pre-loaded %s connections, %s functions",
                        len(all_connections_json), len(all_functions_json))

            # Shared state protected by locks
            total_circuits = total_steps = total_functions = 0
            succeeded = no_findings = failed = 0
            pack_results: list[dict] = [{} for _ in packs]  # pre-allocate by index
            errors: list[str] = []
            warnings: list[str] = []
            total_prompt_tokens = 0
            total_completion_tokens = 0
            counters_lock = asyncio.Lock()
            semaphore = asyncio.Semaphore(request.pack_concurrency)

            async def run_pack(pi: int, pack_ids: list[uuid.UUID]) -> dict:
                """Execute one pack with its own DB session. Returns pack_result dict."""
                nonlocal total_circuits, total_steps, total_functions
                nonlocal succeeded, no_findings, failed
                nonlocal total_prompt_tokens, total_completion_tokens

                async with semaphore:
                    # Check cancellation
                    if is_cancelling(run_id):
                        return {"pack_index": pi, "status": "skipped", "failed_reason": "cancelled"}

                    # Build rich context from shared data (read-only, no lock needed)
                    regions_json = _build_region_context_json(candidates, pack_ids)
                    conns_json = all_connections_json
                    funcs_json = all_functions_json

                    local_circuits = local_steps = local_fns = 0
                    local_created = local_merged = local_skipped = 0
                    prompt_tok = completion_tok = 0

                    try:
                        user_prompt = _CIRCUIT_USER_PROMPT_EXTENDED.format(
                            regions_json=regions_json,
                            connections_json=conns_json,
                            functions_json=funcs_json,
                            max_circuits=getattr(request, 'max_circuits', 200),
                        )
                        system_prompt = _get_circuit_system_prompt()

                        llm = get_llm_provider(provider_key)
                        response = await llm.complete_json(
                            model=resolved_model, system_prompt=system_prompt,
                            user_prompt=user_prompt, temperature=request.temperature,
                            max_tokens=request.max_tokens, timeout_seconds=120,
                        )
                        parsed = response.parsed_json
                        raw_text = response.raw_text or ""
                        prompt_tok = (response.usage.prompt_tokens or 0) if response.usage else 0
                        completion_tok = (response.usage.completion_tokens or 0) if response.usage else 0
                        # If JSON parsing failed, try harder with raw text
                        if parsed is None and raw_text:
                            logger.warning("[circuit-extraction] pack %s/%s JSON parse failed, len=%s raw_text[:800]=%s",
                                           pi + 1, len(packs), len(raw_text), raw_text[:800])
                            # Fallback: strip markdown fences and try again
                            cleaned = raw_text.strip()
                            if cleaned.startswith("```"):
                                lines = cleaned.split("\n")
                                lines = [l for l in lines if not l.startswith("```")]
                                cleaned = "\n".join(lines).strip()
                            try:
                                parsed = json.loads(cleaned)
                                logger.info("[circuit-extraction] pack %s/%s fallback parse succeeded", pi + 1, len(packs))
                            except json.JSONDecodeError:
                                pass
                        if parsed is None:
                            parsed = {}
                        logger.info("[circuit-extraction] pack %s/%s keys=%s tok_in=%s tok_out=%s",
                                     pi + 1, len(packs), list(parsed.keys()) if parsed else 'none',
                                     prompt_tok, completion_tok)
                    except Exception as exc:
                        logger.warning("[circuit-extraction] pack %s failed: %s", pi + 1, exc)
                        async with counters_lock:
                            failed += 1
                            errors.append(f"pack {pi + 1}: {exc}")
                            run.failed_packs = failed
                        return {"pack_index": pi, "status": "failed",
                                "failed_reason": str(exc)[:200], "warnings": []}

                    circuits_data = parsed.get("circuits", [])
                    logger.info("[circuit-extraction] pack %s/%s parsed=%s circuits_count=%s",
                                 pi + 1, len(packs), 'ok' if parsed else 'empty', len(circuits_data) if isinstance(circuits_data, list) else 'not_list')
                    if circuits_data:
                        async with AsyncSessionLocal() as psession:
                            # Pre-fetch existing circuit names for dedup
                            circuit_names = [str(c.get("circuit_name", ""))[:256] for c in circuits_data if c.get("circuit_name")]
                            if circuit_names:
                                existing_q = select(MirrorRegionCircuit).where(
                                    MirrorRegionCircuit.circuit_name.in_(circuit_names)
                                )
                                existing_result = await psession.execute(existing_q)
                                existing_map = {r.circuit_name: r for r in existing_result.scalars().all()}
                            else:
                                existing_map = {}

                            for cdata in circuits_data:
                                cname = str(cdata.get("circuit_name", ""))[:512]
                                if not _is_valid_circuit_name(cname):
                                    local_skipped += 1
                                    logger.warning("[circuit-extraction] pack %s rejected invalid circuit_name: %s",
                                                   pi + 1, cname[:120])
                                    continue
                                existing = existing_map.get(cname)
                                if existing and request.skip_existing:
                                    local_skipped += 1
                                    continue
                                if existing:
                                    # Merge: update confidence if higher
                                    new_conf = float(cdata.get("confidence", 0.7))
                                    if new_conf > (existing.confidence or 0):
                                        existing.confidence = new_conf
                                        existing.function_association = str(cdata.get("function_association", ""))[:512] or existing.function_association
                                        existing.description = str(cdata.get("description", ""))[:1024] or existing.description
                                        existing.circuit_strength = float(cdata.get("circuit_strength", new_conf))
                                        existing.name_cn = str(cdata.get("name_cn", ""))[:512] or existing.name_cn
                                        psession.add(existing)
                                        local_merged += 1
                                    else:
                                        local_skipped += 1
                                    continue

                                # Build full-field circuit + memberships + nested steps/functions
                                _mids = cdata.get("member_region_ids", [])
                                _mids = _mids if isinstance(_mids, list) else []
                                member_rids = []
                                for mid in _mids:
                                    try:
                                        member_rids.append(uuid.UUID(str(mid)))
                                    except (ValueError, TypeError):
                                        continue
                                meta = _meta_from_candidate(candidates.get(pack_ids[0]) if pack_ids else None)
                                circuit = _build_circuit_orm(
                                    cdata=cdata,
                                    member_rids=member_rids,
                                    meta=meta,
                                    created_by=f"circuit_pack:{run.id}",
                                )
                                psession.add(circuit)
                                await psession.flush()
                                _add_circuit_memberships(psession, circuit, member_rids, cdata.get("steps"))
                                local_circuits += 1
                                local_created += 1

                                for sdata in cdata.get("steps", []):
                                    step = _build_step_orm(
                                        circuit=circuit,
                                        sdata=sdata,
                                        region_candidate_id=_safe_region_id(sdata.get("region_id"), candidates),
                                    )
                                    psession.add(step)
                                    await psession.flush()
                                    local_steps += 1

                                    for fdata in sdata.get("functions", []):
                                        fn = _build_function_orm(circuit=circuit, fdata=fdata)
                                        psession.add(fn)
                                        local_fns += 1
                                await psession.commit()

                    # Update shared counters
                    pack_created = local_circuits + local_steps + local_fns
                    async with counters_lock:
                        total_circuits += local_circuits
                        total_steps += local_steps
                        total_functions += local_fns
                        total_prompt_tokens += prompt_tok
                        total_completion_tokens += completion_tok
                        if pack_created > 0:
                            succeeded += 1
                            pack_status = "succeeded"
                        else:
                            no_findings += 1
                            pack_status = "no_findings"
                            if not circuits_data:
                                warnings.append(f"pack {pi + 1}: LLM returned 0 circuits")

                        run.succeeded_packs = succeeded
                        run.no_findings_packs = no_findings
                        run.failed_packs = failed
                        run.circuit_count = total_circuits
                        run.step_count = total_steps
                        run.function_count = total_functions
                        processed = succeeded + no_findings + failed
                        run.result_summary_json = to_jsonable(dict(
                            processed_packs=processed, total_packs=len(packs),
                            circuit_created=total_circuits, step_created=total_steps,
                            function_created=total_functions,
                        ))
                        await session.commit()
                    logger.info("[circuit-extraction] pack %s/%s status=%s circuits=%s steps=%s functions=%s",
                                 pi + 1, len(packs), pack_status, local_circuits, local_steps, local_fns)

                    return {"pack_index": pi, "status": pack_status,
                            "parsed_circuit_count": local_circuits, "parsed_step_count": local_steps,
                            "parsed_function_count": local_fns,
                            "mirror_created_count": local_created, "mirror_merged_count": local_merged,
                            "mirror_skipped_count": local_skipped,
                            "prompt_tokens": prompt_tok, "completion_tokens": completion_tok,
                            "failed_reason": None, "warnings": []}

            # Execute packs sequentially (avoids async session concurrency issues)
            for pi, pack_ids in enumerate(packs):
                try:
                    result = await run_pack(pi, pack_ids)
                    pack_results[pi] = result
                except Exception as exc:
                    pack_results[pi] = {"pack_index": pi, "status": "failed",
                                       "failed_reason": str(exc)[:200], "warnings": []}
                    async with counters_lock:
                        failed += 1
                        run.failed_packs = failed

            # Finalize
            run.succeeded_packs = succeeded
            run.no_findings_packs = no_findings
            run.failed_packs = failed
            run.circuit_count = total_circuits
            run.step_count = total_steps
            run.function_count = total_functions
            # Finalize — preserve cancelled status if cancel was requested
            if is_cancelling(run_id):
                run.status = "cancelled"
            else:
                run.status = "partially_succeeded" if (failed > 0 or errors) else "succeeded"
            run.completed_at = datetime.now(timezone.utc)
            run.result_summary_json = to_jsonable(dict(
                circuit_created=total_circuits, step_created=total_steps,
                function_created=total_functions, pack_count=len(packs),
                succeeded_packs=succeeded, no_findings_packs=no_findings, failed_packs=failed,
                model_call_count=len(packs), processed_packs=len(packs), total_packs=len(packs),
            ))
            run.usage_summary_json = to_jsonable(dict(
                prompt_tokens=total_prompt_tokens, completion_tokens=total_completion_tokens,
                total_tokens=total_prompt_tokens + total_completion_tokens,
                estimated_cost_cny=round(
                    (total_prompt_tokens / 1_000_000) * 1.0 +
                    (total_completion_tokens / 1_000_000) * 2.0, 4,
                ),
            ))
            run.pack_results_json = to_jsonable(pack_results)
            run.errors_json = to_jsonable(errors)
            run.warnings_json = to_jsonable(warnings)
            logger.info("[circuit-extraction] DONE succeeded=%s no_findings=%s failed=%s tokens=%s cost=%.4f",
                         succeeded, no_findings, failed, total_prompt_tokens + total_completion_tokens,
                         (total_prompt_tokens / 1_000_000) * 1.0 + (total_completion_tokens / 1_000_000) * 2.0)
            await session.commit()
            await clear_cancel_registry(run.id)

    except Exception as exc:
        logger.exception("[circuit-extraction] background failure run=%s", run_id)
        await _mark_run_failed(run_id, f"Background failure: {exc}")
        await clear_cancel_registry(run_id)


async def get_circuit_extraction_run(
    session: AsyncSession, run_id: uuid.UUID,
) -> CircuitExtractionRunRead | None:
    run = await session.get(CircuitExtractionRun, run_id)
    if run is None: return None
    await session.refresh(run)
    return CircuitExtractionRunRead.model_validate(run)


async def cancel_circuit_extraction_run(
    session: AsyncSession, run_id: uuid.UUID,
) -> CircuitExtractionRun | None:
    run = await session.get(CircuitExtractionRun, run_id)
    if run is None: return None
    if run.status not in ("pending", "running"): return run
    await mark_cancelling(run_id)  # Set in-memory flag BEFORE DB write (avoids race)
    run.status = "cancelled"
    run.completed_at = datetime.now(timezone.utc)
    await session.commit()
    await session.refresh(run)
    return run
