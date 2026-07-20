"""Symptom → standardized function → circuit search (read-only, no writes)."""

from __future__ import annotations

import logging
import uuid
from datetime import datetime, timezone
from typing import Any

from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, Field
from sqlalchemy import func, select, text
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import get_db
from app.models.llm_extraction import LlmExtractionRun
from app.models.mirror_kg import MirrorRegionCircuit
from app.models.mirror_macro_clinical import MirrorCircuitFunction, MirrorCircuitStep
from app.models.candidate import CandidateBrainRegion
from app.services.llm_providers import get_llm_provider
from app.services.settings_service import get_deepseek_runtime_config

router = APIRouter()
logger = logging.getLogger(__name__)


# ── Request / Response ──────────────────────────────────────────────────────

class SymptomAnalyzeRequest(BaseModel):
    symptom: str
    mode: str = Field(default="exploratory", description="focused | exploratory")


class SymptomSearchRequest(BaseModel):
    functions: list[str]
    categories: list[str] = []
    mode: str = "exploratory"
    granularity_level: str = "macro"
    implicated_regions: list[str] = []
    neurotransmitters: list[str] = []
    pathway_level: str = "unknown"


class SymptomAnalyzeResponse(BaseModel):
    functions: list[str]
    categories: list[str] = []
    primary_category: str = "other"
    syndrome: str = ""
    implicated_regions: list[str] = []
    neurotransmitters: list[str] = []
    pathway_level: str = "unknown"


class CircuitResult(BaseModel):
    id: str
    circuit_name: str
    circuit_type: str | None = None
    description: str | None = None
    step_count: int = 0
    function_count: int = 0
    matched_functions: list[str]
    match_score: float
    relevance: float = 0.0
    matched_categories: list[str] = []
    steps: list[dict[str, Any]] = []
    function_descriptions: dict[str, str] = {}

    model_config = {"from_attributes": True}


class SymptomSearchResponse(BaseModel):
    circuits: list[CircuitResult]


# ── Analyze — LLM symptom → functions ──────────────────────────────────────

ANALYZE_PROMPT = """You are a senior clinical neurologist. Analyze the patient's symptoms and output structured data for brain circuit matching.

Output ONLY this JSON:
{{
  "syndrome": "most likely clinical syndrome (e.g. Parkinsonism, Essential Tremor, Corticobasal Syndrome)",
  "functions": ["standardized function terms for circuit search"],
  "categories": ["motor","sensory","cognitive","emotional","autonomic","memory","language","attention"],
  "primary_category": "primary domain",
  "implicated_regions": ["brain regions implicated (e.g. substantia_nigra, striatum, thalamus, cerebellum)"],
  "neurotransmitters": ["affected systems (e.g. dopamine, acetylcholine, serotonin, norepinephrine, glutamate, GABA)"],
  "pathway_level": "cortical|subcortical|brainstem|spinal|peripheral"
}}

FOCUSED: 1-2 functions, 2-3 regions. EXPLORATORY: 3-5 functions, 3-5 regions.
Patient: {symptom}
Mode: {mode}"""


@router.post("/analyze", response_model=SymptomAnalyzeResponse)
async def analyze_symptom(body: SymptomAnalyzeRequest):
    cfg = get_deepseek_runtime_config()
    provider = get_llm_provider("deepseek")
    prompt = ANALYZE_PROMPT.format(symptom=body.symptom, mode=body.mode)

    try:
        resp = await provider.complete_json(
            model=cfg.default_model,
            system_prompt="You are a clinical neuroscientist. Output ONLY a JSON object with syndrome, functions, categories, primary_category, implicated_regions, neurotransmitters, pathway_level.",
            user_prompt=prompt, temperature=0.1,
        )
        import ast as _ast, json as _json
        parsed = resp.parsed_json
        if isinstance(parsed, dict) and "_array" in parsed: parsed = parsed["_array"]
        if isinstance(parsed, str):
            for p in (_json.loads, _ast.literal_eval):
                try: parsed = p(parsed); break
                except: continue
        if isinstance(parsed, dict):
            funcs = [str(f) for f in (parsed.get("functions") or [])[:8]]
            cats = [str(c).lower() for c in (parsed.get("categories") or [])][:len(funcs)]
            primary = str(parsed.get("primary_category", cats[0] if cats else "other"))
            syndrome = str(parsed.get("syndrome", ""))
            regions = [str(r).lower().replace(" ", "_") for r in (parsed.get("implicated_regions") or [])]
            nts = [str(n).lower() for n in (parsed.get("neurotransmitters") or [])]
            pathway = str(parsed.get("pathway_level", "subcortical"))
        elif isinstance(parsed, list):
            funcs = [str(f) for f in parsed[:5]]; cats = ["other"]*len(funcs); primary = "other"
            syndrome = ""; regions = []; nts = []; pathway = "unknown"
        else:
            funcs = [body.symptom]; cats = ["other"]; primary = "other"
            syndrome = ""; regions = []; nts = []; pathway = "unknown"
        while len(cats) < len(funcs): cats.append("other")
        return SymptomAnalyzeResponse(functions=funcs, categories=cats, primary_category=primary,
            syndrome=syndrome, implicated_regions=regions, neurotransmitters=nts, pathway_level=pathway)
    except Exception:
        logger.exception("Symptom analyze failed")
        return SymptomAnalyzeResponse(functions=[body.symptom], categories=["other"], primary_category="other")


# ── Search — functions + categories → circuits (weighted relevance) ────────

_VALID_CATEGORIES = frozenset({
    "motor", "sensory", "cognitive", "emotional", "autonomic",
    "memory", "language", "attention", "other",
})

@router.post("/search", response_model=SymptomSearchResponse)
async def search_circuits(
    body: SymptomSearchRequest,
    session: AsyncSession = Depends(get_db),
):
    if not body.functions:
        return SymptomSearchResponse(circuits=[])

    symptom_cats = set(c for c in body.categories if c in _VALID_CATEGORIES)
    if not symptom_cats:
        symptom_cats = {"other"}

    # Broad candidate fetch — all circuits whose functions match any term
    where_parts = []
    params: dict[str, Any] = {}
    for i, fn in enumerate(body.functions):
        key = f"fn{i}"
        where_parts.append(f"(cf.function_domain ILIKE :{key} OR cf.function_term_en ILIKE :{key})")
        params[key] = f"%{fn}%"
    where_clause = " OR ".join(f"({p})" for p in where_parts)

    query = text(f"""
        SELECT DISTINCT c.id, c.circuit_name, c.circuit_type, c.description,
               cf.function_domain, cf.function_term_en, cf.function_role,
               GREATEST(similarity(cf.function_domain, :sim_q), similarity(cf.function_term_en, :sim_q)) as sim
        FROM mirror_circuit_functions cf
        JOIN mirror_region_circuits c ON c.id = cf.circuit_id
        WHERE ({where_clause})
          AND c.granularity_level = :granularity
        LIMIT 500
    """)
    params["granularity"] = body.granularity_level
    params["sim_q"] = " ".join(body.functions)

    rows = (await session.execute(query, params)).fetchall()
    if not rows:
        return SymptomSearchResponse(circuits=[])

    # Group by circuit, compute relevance
    circuit_data: dict[str, dict] = {}
    for row in rows:
        cid = str(row[0])
        fn_domain = (row[4] or "").strip().lower()
        fn_term = (row[5] or "").strip().lower()
        sim = float(row[7] or 0)
        if cid not in circuit_data:
            circuit_data[cid] = {
                "id": cid,
                "circuit_name": row[1] or "Unknown",
                "circuit_type": row[2],
                "description": row[3] or "",
                "sim": sim,
                "fn_domains": set(),
                "matched_functions": [],
                "matched_categories": set(),
            }
        d = circuit_data[cid]
        d["sim"] = max(d["sim"], sim)
        if fn_domain:
            d["fn_domains"].add(fn_domain)
        if fn_term and fn_term not in d["matched_functions"]:
            d["matched_functions"].append(fn_term)

    # ── Professional Multi-Dimensional Clinical Scoring ──────────────────────
    # Dimensions: Semantic (30) + Anatomical (25) + Evidence (20) + Density (15) + Pathway (10)
    # Max score = 100

    implicated_regions = set(r.lower().replace(" ", "_") for r in (body.implicated_regions or []))
    implicated_nts = set(n.lower() for n in (body.neurotransmitters or []))
    pathway_level = (body.pathway_level or "unknown").lower()

    # Collect all circuit IDs for batch queries
    all_cids = [uuid.UUID(cid) for cid in circuit_data]

    # ── Batch: count steps per circuit (for pathway scoring) ────────────
    step_counts: dict[uuid.UUID, int] = {}
    if all_cids:
        sc_rows = (await session.execute(
            select(MirrorCircuitStep.circuit_id, func.count())
            .where(MirrorCircuitStep.circuit_id.in_(all_cids))
            .group_by(MirrorCircuitStep.circuit_id)
        )).fetchall()
        step_counts = {row[0]: row[1] for row in sc_rows}

    # ── Batch: get step region names for anatomical matching ────────────
    step_regions: dict[uuid.UUID, list[str]] = {}
    if all_cids and implicated_regions:
        sr_rows = (await session.execute(
            select(MirrorCircuitStep.circuit_id, CandidateBrainRegion.en_name)
            .join(CandidateBrainRegion, CandidateBrainRegion.id == MirrorCircuitStep.region_candidate_id)
            .where(MirrorCircuitStep.circuit_id.in_(all_cids))
        )).fetchall()
        for cid, ename in sr_rows:
            step_regions.setdefault(cid, []).append((ename or "").lower().replace(" ", "_"))

    # ── Batch: connection confidence for evidence scoring ──────────────
    cm_rows = (await session.execute(text("""
        SELECT mcm.circuit_id, AVG(mrc.confidence)
        FROM mirror_circuit_projection_memberships mcm
        JOIN mirror_region_connections mrc ON mrc.id = mcm.projection_id
        WHERE mcm.circuit_id = ANY(:cids) AND mrc.confidence IS NOT NULL
        GROUP BY mcm.circuit_id
    """), {"cids": all_cids})).fetchall()
    conn_confidence: dict[uuid.UUID, float] = {row[0]: float(row[1] or 0.5) for row in cm_rows}

    # ── Score each circuit ──────────────────────────────────────────────
    scored = []
    for cid, d in circuit_data.items():
        uid = uuid.UUID(cid)

        # Total function count
        func_count = await session.scalar(
            select(func.count()).select_from(MirrorCircuitFunction).where(
                MirrorCircuitFunction.circuit_id == uid
            )
        ) or 1

        # 1. SEMANTIC RELEVANCE (0-30): how well functions match symptom terms
        semantic = min(30, d["sim"] * 35)

        # 2. ANATOMICAL SPECIFICITY (0-25): do circuit regions overlap with implicated regions?
        anatomical = 0
        circ_regions = step_regions.get(uid, [])
        if implicated_regions and circ_regions:
            matched_regions = sum(1 for cr in circ_regions if any(ir in cr or cr in ir for ir in implicated_regions))
            anatomical = min(25, int(matched_regions / max(len(implicated_regions), 1) * 25))

        # 3. EVIDENCE QUALITY (0-20): average connection confidence in this circuit
        avg_conf = conn_confidence.get(uid, 0.5)
        evidence = min(20, int(avg_conf * 20))

        # 4. FUNCTIONAL DENSITY (0-15): how focused is this circuit on matched terms?
        matched_frac = len(d["matched_functions"]) / max(func_count, 1)
        density = min(15, int(matched_frac * 20))

        # 5. PATHWAY SPECIFICITY (0-10): reward well-defined pathways, penalize vague
        pathway_score = 5  # baseline
        name = (d["circuit_name"] or "").lower()
        if any(kw in name for kw in ("basal_ganglia", "cortico_striatal", "thalamocortical", "nigrostriatal", "cerebello_thalamo")):
            pathway_score = 10  # gold-standard defined pathway
        elif any(kw in name for kw in ("unknown", "unspecified", "generic")):
            pathway_score = 1   # penalize vague circuits
        n_steps = step_counts.get(uid, 0)
        if n_steps >= 4: pathway_score += 1  # well-defined, multi-step circuit
        if n_steps <= 1: pathway_score = max(1, pathway_score - 2)

        # Compute total clinical relevance score (max 100)
        relevance = semantic + anatomical + evidence + density + pathway_score
        d["relevance"] = round(relevance, 1)
        d["func_count"] = func_count
        d["score_breakdown"] = {
            "semantic": semantic, "anatomical": anatomical, "evidence": evidence,
            "density": density, "pathway": pathway_score,
        }
        scored.append(d)

    # Mode-based threshold
    threshold = 25 if body.mode == "focused" else 8
    scored = [d for d in scored if d["relevance"] >= threshold]
    scored.sort(key=lambda d: d["relevance"], reverse=True)

    # Build CircuitResult list
    circuits = []
    for d in scored:
        uid = uuid.UUID(d["id"])
        step_count = await session.scalar(
            select(func.count()).select_from(MirrorCircuitStep).where(
                MirrorCircuitStep.circuit_id == uid
            )
        ) or 0
        steps_result = await session.execute(
            select(MirrorCircuitStep).where(MirrorCircuitStep.circuit_id == uid).order_by(MirrorCircuitStep.step_order)
        )
        steps = [{"id": str(s.id), "step_order": s.step_order, "step_name": s.step_name, "step_type": s.step_type, "role": s.role}
                 for s in steps_result.scalars().all()]
        # Load circuit description
        circ_desc = d.get("description", "")
        # Load function descriptions for matched functions
        func_descs: dict[str, str] = {}
        if d["matched_functions"]:
            fd_rows = (await session.execute(
                select(MirrorCircuitFunction.function_term_en, MirrorCircuitFunction.description)
                .where(MirrorCircuitFunction.circuit_id == uid)
                .where(MirrorCircuitFunction.function_term_en.in_(d["matched_functions"][:10]))
            )).fetchall()
            for fen, fdesc in fd_rows:
                if fdesc: func_descs[fen or ""] = fdesc
        circuits.append(CircuitResult(
            id=d["id"], circuit_name=d["circuit_name"], circuit_type=d["circuit_type"],
            description=circ_desc or None,
            step_count=step_count, function_count=d["func_count"],
            matched_functions=d["matched_functions"][:10],
            match_score=round(min(1.0, len(d["matched_functions"]) / max(d["func_count"], 1)), 2),
            relevance=d["relevance"], matched_categories=d.get("matched_categories", []),
            steps=steps, function_descriptions=func_descs,
        ))

    return SymptomSearchResponse(circuits=circuits)


# ── Expand — LLM function term → related terms ─────────────────────────────

class ExpandRequest(BaseModel):
    functions: list[str]


class ExpandResponse(BaseModel):
    expanded: list[str]


@router.post("/expand", response_model=ExpandResponse)
async def expand_functions(body: ExpandRequest):
    """Use LLM to expand function terms into related synonyms for better matching."""
    if not body.functions:
        return ExpandResponse(expanded=[])

    # Get existing function terms from DB for context
    expanded: set[str] = set(body.functions)
    try:
        cfg = get_deepseek_runtime_config()
        provider = get_llm_provider("deepseek")
        prompt = f"""Given these clinical/neuroscientific terms: {", ".join(body.functions)}

For each term, provide BOTH broader category-level terms AND specific related terms that would appear
in a brain circuit functions database. Include the broader functional domain (e.g. "language", "motor",
"memory", "sensory", "cognitive") even if not explicitly mentioned.

Example: "expressive aphasia" → ["language", "language production", "speech", "communication", "verbal expression", "Broca", "linguistic"]
Example: "resting tremor" → ["motor", "motor control", "movement disorder", "basal ganglia", "tremor", "bradykinesia", "parkinsonism"]
Example: "memory loss" → ["memory", "episodic memory", "cognitive", "hippocampal", "amnesia", "consolidation", "recall"]

Output ONLY a JSON array of strings (all expanded terms combined, no duplicates): ["term1", "term2", ...]"""

        resp = await provider.complete_json(
            model=cfg.default_model,
            system_prompt="You expand neuroscience terms for database search. Output ONLY a JSON array.",
            user_prompt=prompt,
            temperature=0.2,
        )
        import ast as _ast, json as _json
        parsed = resp.parsed_json
        if isinstance(parsed, dict) and "_array" in parsed:
            parsed = parsed["_array"]
        if isinstance(parsed, str):
            for parser in (_json.loads, _ast.literal_eval):
                try: parsed = parser(parsed); break
                except Exception: continue
        if isinstance(parsed, list):
            for t in parsed[:20]:
                if t and str(t).strip():
                    expanded.add(str(t).strip())
    except Exception:
        logger.exception("Expand failed")

    return ExpandResponse(expanded=list(expanded))


# ── Conversation — LLM-powered symptom triage ──────────────────────────────

class ConversationRequest(BaseModel):
    messages: list[dict[str, str]]
    granularity_level: str = "macro"


class ConversationResponse(BaseModel):
    stage: str
    content: str | None = None
    summary: str | None = None


CONVERSATION_PROMPT = """You are a clinical neuroscientist conducting a symptom triage interview. Your goal is to narrow down the patient's symptoms by asking one clarifying question at a time. The user is searching at the {granularity} granularity level. Adapt your terminology accordingly.

Conversation so far:
{messages}

Based on the conversation, decide if you need more information or if you can summarize the symptoms.

If you need more information, respond with:
{{"stage": "asking", "content": "Your single clarifying question here...", "summary": null}}

If you have enough information to form a clinical summary (typically after 2-4 exchanges), respond with:
{{"stage": "summarizing", "content": null, "summary": "Clinical summary of the symptoms..."}}

Reply ONLY with the JSON object, nothing else."""


@router.post("/conversation", response_model=ConversationResponse)
async def conversation_endpoint(body: ConversationRequest):
    """LLM-powered symptom triage conversation — asks clarifying questions or summarizes."""
    if not body.messages:
        return ConversationResponse(stage="asking", content="Please describe your symptoms.")

    try:
        cfg = get_deepseek_runtime_config()
        provider = get_llm_provider("deepseek")

        formatted = "\n".join(
            f"{m['role']}: {m['content']}" for m in body.messages
        )
        prompt = CONVERSATION_PROMPT.replace("{messages}", formatted).replace("{granularity}", body.granularity_level)

        resp = await provider.complete_json(
            model=cfg.default_model,
            system_prompt="You are a clinical neuroscientist. Reply ONLY a JSON object with stage, content, and summary fields.",
            user_prompt=prompt,
            temperature=0.3,
        )

        import ast as _ast, json as _json
        parsed = resp.parsed_json
        # DeepSeek JSON mode wraps arrays in {"_array": [...]}; also handle string-wrapped
        if isinstance(parsed, dict) and "_array" in parsed:
            parsed = parsed["_array"]
        if isinstance(parsed, str):
            for parser in (_json.loads, _ast.literal_eval):
                try:
                    parsed = parser(parsed)
                    break
                except Exception:
                    continue

        if isinstance(parsed, dict):
            stage = str(parsed.get("stage", "asking"))
            content = parsed.get("content")
            summary = parsed.get("summary")
            if stage not in ("asking", "summarizing"):
                stage = "asking"
            return ConversationResponse(
                stage=stage,
                content=str(content) if content is not None else None,
                summary=str(summary) if summary is not None else None,
            )

        # Fallback: use raw user messages as summary
        raw_summary = " ".join(m["content"] for m in body.messages)
        return ConversationResponse(stage="summarizing", summary=raw_summary)

    except Exception:
        logger.exception("Conversation endpoint failed")
        raw_summary = " ".join(m["content"] for m in body.messages)
        return ConversationResponse(stage="summarizing", summary=raw_summary)


# ── Graph — circuit IDs → region nodes + connection edges ──────────────────

def _safe_float(value: Any, default: float = 0.0) -> float:
    try:
        return float(value) if value is not None else default
    except (TypeError, ValueError):
        return default


class GraphDataRequest(BaseModel):
    circuit_ids: list[str]
    granularity_level: str = "macro"


class GraphDataResponse(BaseModel):
    nodes: list[dict]
    edges: list[dict]


@router.post("/graph", response_model=GraphDataResponse)
async def get_circuit_graph(
    body: GraphDataRequest,
    session: AsyncSession = Depends(get_db),
):
    """Unified brain-region + connection graph. Each node/edge carries `circuit_ids`
    so the frontend can highlight one circuit's path through the network."""
    try:
        cids = list(dict.fromkeys(uuid.UUID(c) for c in body.circuit_ids if c))
    except (ValueError, TypeError, AttributeError) as exc:
        raise HTTPException(status_code=422, detail="circuit_ids must contain valid UUIDs") from exc
    if not cids:
        return GraphDataResponse(nodes=[], edges=[])

    # ── Step → region mapping per circuit ──────────────────────────────────
    steps_sql = text("""
        SELECT s.id::text, s.circuit_id::text, s.region_candidate_id::text,
               s.step_order, s.step_name,
               COALESCE(cbr.en_name, cbr.std_name, cbr.cn_name, cbr.raw_name, s.step_name) as label,
               COALESCE(cbr.en_name, '') as name_en,
               COALESCE(cbr.cn_name, '') as name_cn
        FROM mirror_circuit_steps s
        LEFT JOIN candidate_brain_regions cbr ON cbr.id = s.region_candidate_id
        WHERE s.circuit_id = ANY(:cids)
          AND s.review_status <> 'rejected'
          AND s.mirror_status NOT IN ('human_rejected', 'superseded')
        ORDER BY s.circuit_id, s.step_order
    """)
    rows = (await session.execute(steps_sql, {"cids": cids})).fetchall()
    if not rows:
        return GraphDataResponse(nodes=[], edges=[])

    # Only real candidate regions become graph nodes. Steps without a resolved
    # region remain visible in the circuit detail list but cannot form graph edges.
    region_circuits: dict[str, set[str]] = {}
    region_metadata: dict[str, dict[str, str]] = {}
    steps_by_circuit: dict[str, list[dict[str, Any]]] = {}
    for row in rows:
        step_id = str(row[0])
        cid = str(row[1])
        rid = str(row[2]) if row[2] else None
        steps_by_circuit.setdefault(cid, []).append({
            "id": step_id,
            "region_id": rid,
            "step_order": row[3],
            "step_name": row[4] or "",
        })
        if not rid:
            # Fallback: steps without resolved region use synthetic ID so the circuit
            # still has visible nodes (otherwise circuits like cortical_thalamic_sensory
            # show "no nodes" even though they have steps).
            rid = f"{cid}:{step_id}"
        region_circuits.setdefault(rid, set()).add(cid)
        if rid not in region_metadata:
            region_metadata[rid] = {
                "label": row[5] or row[4] or "?",
                "name_en": row[6] or "",
                "name_cn": row[7] or "",
            }

    nodes = [
        {
            "id": rid,
            "type": "brain_region",
            **region_metadata[rid],
            "circuit_ids": sorted(region_circuits[rid]),
        }
        for rid in region_circuits
    ]
    if not nodes:
        return GraphDataResponse(nodes=[], edges=[])

    # ── Authoritative circuit → projection memberships ──────────────────────
    membership_sql = text("""
        SELECT m.circuit_id::text, r.id::text,
               r.source_region_candidate_id::text, r.target_region_candidate_id::text,
               r.connection_type, r.confidence, r.strength,
               COALESCE(r.source_region_name_en, '') AS sname,
               COALESCE(r.target_region_name_en, '') AS tname
        FROM mirror_circuit_projection_memberships m
        JOIN mirror_region_connections r ON r.id = m.projection_id
        WHERE m.circuit_id = ANY(:cids)
          AND m.granularity_level = :gran
          AND r.granularity_level = :gran
          AND m.review_status <> 'rejected'
          AND m.verification_status NOT IN ('human_rejected', 'model_conflict')
          AND m.mirror_status NOT IN ('human_rejected', 'superseded')
          AND r.review_status <> 'rejected'
          AND r.mirror_status NOT IN ('human_rejected', 'superseded')
    """)
    membership_rows = (
        await session.execute(membership_sql, {"cids": cids, "gran": body.granularity_level})
    ).fetchall()

    edge_map: dict[str, dict[str, Any]] = {}
    covered_pairs: set[tuple[str, str, str]] = set()

    def add_edge(
        *,
        edge_id: str,
        circuit_id: str,
        source: str,
        target: str,
        edge_type: str,
        confidence: Any,
        strength: Any,
        source_name: str,
        target_name: str,
    ) -> None:
        if source not in region_circuits or target not in region_circuits:
            return
        if (
            circuit_id not in region_circuits[source]
            or circuit_id not in region_circuits[target]
        ):
            return
        existing = edge_map.get(edge_id)
        if existing:
            existing["_circuit_ids"].add(circuit_id)
            return
        edge_map[edge_id] = {
            "id": edge_id,
            "source": source,
            "target": target,
            "type": edge_type or "unknown",
            "confidence": _safe_float(confidence),
            "strength": strength if strength is not None else "",
            "source_name": source_name or region_metadata[source]["label"],
            "target_name": target_name or region_metadata[target]["label"],
            "_circuit_ids": {circuit_id},
        }

    # The visible circuit path is defined strictly by consecutive ordered steps.
    # Memberships may annotate those pairs, but must not expand the graph with
    # unrelated connections incident to one of the circuit's regions.
    adjacent_pairs: list[tuple[str, dict[str, Any], dict[str, Any]]] = []
    valid_pair_keys: set[tuple[str, str, str]] = set()
    for cid, circuit_steps in steps_by_circuit.items():
        for source_step, target_step in zip(circuit_steps, circuit_steps[1:]):
            src = source_step["region_id"]
            tgt = target_step["region_id"]
            if not src or not tgt or src == tgt:
                continue
            adjacent_pairs.append((cid, source_step, target_step))
            valid_pair_keys.add((cid, src, tgt))

    for row in membership_rows:
        cid, edge_id, src, tgt = map(str, row[:4])
        pair_key = (cid, src, tgt)
        if pair_key not in valid_pair_keys:
            continue
        add_edge(
            edge_id=edge_id,
            circuit_id=cid,
            source=src,
            target=tgt,
            edge_type=row[4] or "unknown",
            confidence=row[5],
            strength=row[6],
            source_name=row[7] or "",
            target_name=row[8] or "",
        )
        covered_pairs.add(pair_key)

    # ── Consecutive-step fallback ───────────────────────────────────────────
    # Fetch candidate real connections once, then only use exact directed pairs
    # that are consecutive in a requested circuit.
    fallback_pairs = [
        pair
        for pair in adjacent_pairs
        if (
            pair[0],
            pair[1]["region_id"],
            pair[2]["region_id"],
        ) not in covered_pairs
    ]

    real_connections: dict[tuple[str, str], Any] = {}
    if fallback_pairs:
        rids = list({
            uuid.UUID(step["region_id"])
            for circuit_steps in steps_by_circuit.values()
            for step in circuit_steps
            if step["region_id"]
        })
        fallback_sql = text("""
            SELECT id::text, source_region_candidate_id::text, target_region_candidate_id::text,
                   connection_type, confidence, strength,
                   COALESCE(source_region_name_en, '') AS sname,
                   COALESCE(target_region_name_en, '') AS tname
            FROM mirror_region_connections
            WHERE source_region_candidate_id = ANY(:rids)
              AND target_region_candidate_id = ANY(:rids)
              AND granularity_level = :gran
              AND review_status <> 'rejected'
              AND mirror_status NOT IN ('human_rejected', 'superseded')
            ORDER BY confidence DESC NULLS LAST, id
            LIMIT 5000
        """)
        fallback_rows = (
            await session.execute(fallback_sql, {"rids": rids, "gran": body.granularity_level})
        ).fetchall()
        for row in fallback_rows:
            real_connections.setdefault((str(row[1]), str(row[2])), row)

    for cid, source_step, target_step in fallback_pairs:
        src = source_step["region_id"]
        tgt = target_step["region_id"]
        real = real_connections.get((src, tgt))
        if real:
            add_edge(
                edge_id=str(real[0]),
                circuit_id=cid,
                source=src,
                target=tgt,
                edge_type=real[3] or "unknown",
                confidence=real[4],
                strength=real[5],
                source_name=real[6] or "",
                target_name=real[7] or "",
            )
            continue
        add_edge(
            edge_id=f"step-flow:{cid}:{source_step['id']}:{target_step['id']}",
            circuit_id=cid,
            source=src,
            target=tgt,
            edge_type="step_flow",
            confidence=0.5,
            strength="inferred",
            source_name=region_metadata[src]["label"],
            target_name=region_metadata[tgt]["label"],
        )

    edges = []
    for edge in edge_map.values():
        circuit_ids = sorted(edge.pop("_circuit_ids"))
        edges.append({**edge, "circuit_ids": circuit_ids})
    return GraphDataResponse(nodes=nodes, edges=edges)


# ── Clinical Report Generation ──────────────────────────────────────────────

class ReportRequest(BaseModel):
    summary: str
    circuits: list[dict] = []
    graph_nodes: int = 0
    graph_edges: int = 0
    syndrome: str = ""
    implicated_regions: list[str] = []
    neurotransmitters: list[str] = []
    pathway_level: str = ""


class ReportResponse(BaseModel):
    report_markdown: str
    generated_at: str


REPORT_PROMPT = """You are a senior clinical neurologist writing a patient-facing brain health analysis report in Chinese.

## Patient Clinical Data
Summary: {summary}
AI Diagnosis: {syndrome}
Implicated Brain Regions: {regions}
Affected Neurotransmitter Systems: {nts}
Pathway Level: {pathway}

## Brain Circuits Matched by System
{circuit_list}
Network: {node_count} regions, {edge_count} connections.

WRITING RULES:
1. Chinese, patient-facing, professional detail
2. NO markdown artifacts (---, ***, ** wrapping lines). Use 【】 for section headers
3. NO scores, match percentages, confidence numbers
4. Reference actual circuit names and brain regions from the system data
5. Integrate the AI diagnosis ({syndrome}) and implicated regions ({regions}) into the analysis
6. Explain neurotransmitter involvement ({nts}) in plain language
7. Connect each symptom to specific circuits and regions

STRUCTURE:
【一、临床分析】Integrate the syndrome diagnosis, clinical summary, and key symptoms. Reference the implicated brain regions.
【二、大脑回路分析】For top circuits: name, normal function, how affected, involved regions. Include circuit flow diagram.
【三、神经递质与脑电活动】Cover {nts} systems. Explain EEG correlates.
【四、循环系统与脑脊液】Blood supply, drainage, glymphatic clearance relevant to affected regions.
【五、外周器官与神经影响】Gut, heart, skin, autonomic nerves.
【六、综合总结与建议】Patient-friendly summary, medical/lifestyle recommendations.

Output ONLY valid markdown. Use 【】 for headers. No JSON wrapper."""


@router.post("/report", response_model=ReportResponse)
async def generate_clinical_report(body: ReportRequest):
    """Generate a comprehensive clinical analysis report using DeepSeek."""
    if not body.summary.strip():
        raise HTTPException(status_code=400, detail="Summary is required")

    circuit_lines = []
    for i, c in enumerate(body.circuits[:12], 1):
        name = c.get("circuit_name", c.get("name", "Unknown"))
        ctype = c.get("circuit_type", "")
        desc = c.get("description", "")
        steps = c.get("step_count", 0)
        funcs = c.get("function_count", 0)
        matched = c.get("matched_functions", [])
        step_details = c.get("steps", [])
        # Build rich circuit description with step details
        step_info = ""
        if step_details:
            step_names = [s.get("step_name", "?") for s in step_details[:8]]
            step_info = f" | 步骤: {' → '.join(step_names)}"
        func_info = f" | 功能: {', '.join(matched[:5])}" if matched else ""
        desc_info = f" | 描述: {desc[:120]}" if desc else ""
        circuit_lines.append(
            f"{i}. 【{name}】类型:{ctype or '未知'}{desc_info}{func_info}{step_info}"
        )

    prompt = REPORT_PROMPT.format(
        summary=body.summary,
        syndrome=body.syndrome or "待确认",
        regions=", ".join(body.implicated_regions) if body.implicated_regions else "待分析",
        nts=", ".join(body.neurotransmitters) if body.neurotransmitters else "待分析",
        pathway=body.pathway_level or "unknown",
        circuit_list="\n".join(circuit_lines) or "No circuits matched",
        node_count=body.graph_nodes,
        edge_count=body.graph_edges,
    )

    try:
        cfg = get_deepseek_runtime_config()
        provider = get_llm_provider("deepseek")
        resp = await provider.complete_text(
            model=cfg.default_model,
            system_prompt="You are a clinical neuroscientist. Output ONLY clean markdown, no JSON wrapper.",
            user_prompt=prompt,
            temperature=0.3,
            max_tokens=6000,
            timeout_seconds=180,
        )
        if not resp.transport_ok or not resp.raw_text:
            raise HTTPException(status_code=502, detail=f"LLM call failed: {resp.error}")

        report = resp.raw_text.strip()
        if report.startswith("```"):
            report = report.split("\n", 1)[1]
            if report.endswith("```"):
                report = report[:-3]
        return ReportResponse(
            report_markdown=report,
            generated_at=datetime.now(timezone.utc).isoformat(),
        )
    except HTTPException:
        raise
    except Exception as exc:
        logger.exception("[symptom-query][report] generation failed")
        raise HTTPException(status_code=500, detail=f"Report generation failed: {exc}") from exc


@router.post("/report/pdf")
async def generate_clinical_report_pdf(body: ReportRequest):
    """Generate professional A4 PDF report and return as downloadable file."""
    if not body.summary.strip():
        raise HTTPException(status_code=400, detail="Summary required")

    # ── Generate markdown via DeepSeek (same as /report) ────────────────
    circuit_lines = []
    for i, c in enumerate(body.circuits[:12], 1):
        name = c.get("circuit_name", c.get("name", "Unknown"))
        ctype = c.get("circuit_type", "")
        desc = c.get("description", "")
        matched = c.get("matched_functions", [])
        step_details = c.get("steps", [])
        step_info = ""
        if step_details:
            step_names = [s.get("step_name", "?") for s in step_details[:8]]
            step_info = f" | steps: {' > '.join(step_names)}"
        func_info = f" | functions: {', '.join(matched[:5])}" if matched else ""
        desc_info = f" | {desc[:120]}" if desc else ""
        circuit_lines.append(
            f"{i}. {name} [{ctype or 'unknown'}]{desc_info}{func_info}{step_info}"
        )

    prompt = REPORT_PROMPT.format(
        summary=body.summary,
        syndrome=body.syndrome or "待确认",
        regions=", ".join(body.implicated_regions) if body.implicated_regions else "待分析",
        nts=", ".join(body.neurotransmitters) if body.neurotransmitters else "待分析",
        pathway=body.pathway_level or "unknown",
        circuit_list="\n".join(circuit_lines) or "No circuits matched",
        node_count=body.graph_nodes,
        edge_count=body.graph_edges,
    )

    try:
        cfg = get_deepseek_runtime_config()
        provider = get_llm_provider("deepseek")
        resp = await provider.complete_text(
            model=cfg.default_model,
            system_prompt="You are a clinical neuroscientist. Output ONLY clean markdown, no JSON wrapper.",
            user_prompt=prompt, temperature=0.3, max_tokens=6000, timeout_seconds=180,
        )
        if not resp.transport_ok or not resp.raw_text:
            raise HTTPException(status_code=502, detail=f"LLM failed: {resp.error}")
        report = resp.raw_text.strip()
        if report.startswith("```"): report = report.split("\n", 1)[1]
        if report.endswith("```"): report = report[:-3]
    except HTTPException:
        raise
    except Exception as exc:
        raise HTTPException(status_code=500, detail=str(exc)) from exc

    # ── Build professional PDF ──────────────────────────────────────────
    from app.services.report_pdf_builder import generate_report_pdf

    buf = generate_report_pdf(report, body.circuits)

    return StreamingResponse(
        buf,
        media_type="application/pdf",
        headers={"Content-Disposition": "attachment; filename=brain_analysis_report.pdf"},
    )

