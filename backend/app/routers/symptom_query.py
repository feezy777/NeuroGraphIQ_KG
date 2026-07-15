"""Symptom → standardized function → circuit search (read-only, no writes)."""

from __future__ import annotations

import logging
import uuid
from typing import Any

from fastapi import APIRouter, Depends
from pydantic import BaseModel, Field
from sqlalchemy import func, select, text
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import get_db
from app.models.llm_extraction import LlmExtractionRun
from app.models.mirror_kg import MirrorRegionCircuit
from app.models.mirror_macro_clinical import MirrorCircuitFunction, MirrorCircuitStep
from app.services.llm_providers import get_llm_provider
from app.services.settings_service import get_deepseek_runtime_config

router = APIRouter()
logger = logging.getLogger(__name__)


# ── Request / Response ──────────────────────────────────────────────────────

class SymptomAnalyzeRequest(BaseModel):
    symptom: str
    mode: str = Field(default="multi", description="single | multi")


class SymptomAnalyzeResponse(BaseModel):
    functions: list[str]


class SymptomSearchRequest(BaseModel):
    functions: list[str]
    granularity_level: str = "macro"


class CircuitResult(BaseModel):
    id: str
    circuit_name: str
    circuit_type: str | None = None
    step_count: int = 0
    function_count: int = 0
    matched_functions: list[str]
    match_score: float
    steps: list[dict[str, Any]] = []

    model_config = {"from_attributes": True}


class SymptomSearchResponse(BaseModel):
    circuits: list[CircuitResult]


# ── Analyze — LLM symptom → functions ──────────────────────────────────────

ANALYZE_PROMPT = """You are a clinical neuroscientist. Convert the patient's symptom description into standardized brain function terms.

Rules:
- For 'multi' mode: return 2-5 distinct function terms that could explain the symptoms
- For 'single' mode: return 1 best-matching function term
- Use standard neuroanatomical function terminology (e.g., "vestibular dysfunction", "proprioceptive processing", "motor coordination")
- Reply ONLY a JSON array of strings, nothing else.

Patient symptoms: {symptom}
Mode: {mode}

Output format: ["function1", "function2", ...]"""


@router.post("/analyze", response_model=SymptomAnalyzeResponse)
async def analyze_symptom(body: SymptomAnalyzeRequest):
    cfg = get_deepseek_runtime_config()
    provider = get_llm_provider("deepseek")
    prompt = ANALYZE_PROMPT.format(symptom=body.symptom, mode=body.mode)

    try:
        resp = await provider.complete_json(
            model=cfg.default_model,
            system_prompt="You are a clinical neuroscientist. Reply ONLY a JSON array of strings.",
            user_prompt=prompt,
            temperature=0.1,
        )
        import ast as _ast, json as _json
        parsed = resp.parsed_json
        # DeepSeek JSON mode wraps array in {"_array": [...]}
        if isinstance(parsed, dict) and "_array" in parsed:
            parsed = parsed["_array"]
        # DeepSeek may return a JSON/Python string instead of parsed object
        if isinstance(parsed, str):
            for parser in (_json.loads, _ast.literal_eval):
                try:
                    parsed = parser(parsed)
                    break
                except Exception:
                    continue
        if isinstance(parsed, list):
            functions = [str(f) for f in parsed[:5]]
        elif isinstance(parsed, dict):
            vals = parsed.get("functions") or list(parsed.values())
            functions = [str(v) for v in vals][:5] if vals else [body.symptom]
        else:
            functions = [body.symptom]
        return SymptomAnalyzeResponse(functions=functions)
    except Exception:
        logger.exception("Symptom analyze failed")
        return SymptomAnalyzeResponse(functions=[body.symptom])


# ── Search — functions → circuits ──────────────────────────────────────────

@router.post("/search", response_model=SymptomSearchResponse)
async def search_circuits(
    body: SymptomSearchRequest,
    session: AsyncSession = Depends(get_db),
):
    if not body.functions:
        return SymptomSearchResponse(circuits=[])

    # Build expanded terms: for each function, also include trigram-similar matches
    where_parts = []
    params: dict[str, Any] = {}
    for i, fn in enumerate(body.functions):
        key = f"fn{i}"
        # Exact ILIKE match gets priority
        where_parts.append(f"(cf.function_domain ILIKE :{key} OR cf.function_term_en ILIKE :{key})")
        params[key] = f"%{fn}%"
        # Also add trigram similarity scoring (fallback for fuzzy match)
        tkey = f"tfn{i}"
        where_parts.append(f"similarity(cf.function_domain, :{tkey}) > 0.15")
        where_parts.append(f"similarity(cf.function_term_en, :{tkey}) > 0.15")
        params[tkey] = fn

    where_clause = " OR ".join(f"({p})" for p in where_parts)

    # Query circuits with similarity scoring
    query = text(f"""
        SELECT DISTINCT ON (c.id)
            c.id, c.circuit_name, c.circuit_type,
            cf.function_domain, cf.function_term_en,
            cf.function_role, cf.confidence_score,
            GREATEST(similarity(cf.function_domain, :sim_q), similarity(cf.function_term_en, :sim_q)) as sim
        FROM mirror_circuit_functions cf
        JOIN mirror_region_circuits c ON c.id = cf.circuit_id
        WHERE ({where_clause})
          AND c.granularity_level = :granularity
        ORDER BY c.id, sim DESC, cf.confidence_score DESC NULLS LAST
        LIMIT 50
    """)
    params["granularity"] = body.granularity_level
    params["sim_q"] = " ".join(body.functions)

    result = await session.execute(query, params)
    rows = result.fetchall()

    if not rows:
        return SymptomSearchResponse(circuits=[])

    # Group by circuit
    circuit_data: dict[str, dict] = {}
    for row in rows:
        cid = str(row[0])
        fn_term = row[4] or row[3] or ""
        if cid not in circuit_data:
            circuit_data[cid] = {
                "id": cid,
                "circuit_name": row[1] or "Unknown",
                "circuit_type": row[2],
                "matched_functions": [],
            }
        if fn_term and fn_term not in circuit_data[cid]["matched_functions"]:
            circuit_data[cid]["matched_functions"].append(fn_term)

    # Get step counts & function counts per circuit
    circuit_ids = list(circuit_data.keys())
    circuits = []

    for cid in circuit_ids:
        data = circuit_data[cid]
        uid = uuid.UUID(cid)

        # Count steps
        step_count = await session.scalar(
            select(func.count()).select_from(MirrorCircuitStep).where(
                MirrorCircuitStep.circuit_id == uid
            )
        ) or 0

        # Count total functions
        func_count = await session.scalar(
            select(func.count()).select_from(MirrorCircuitFunction).where(
                MirrorCircuitFunction.circuit_id == uid
            )
        ) or 0

        # Match score = matched / total functions
        total_fn = max(func_count, 1)
        match_score = min(1.0, len(data["matched_functions"]) / total_fn)

        # Get steps detail
        steps_result = await session.execute(
            select(MirrorCircuitStep)
            .where(MirrorCircuitStep.circuit_id == uid)
            .order_by(MirrorCircuitStep.step_order)
        )
        steps = [
            {
                "id": str(s.id),
                "step_order": s.step_order,
                "step_name": s.step_name,
                "step_type": s.step_type,
                "role": s.role,
            }
            for s in steps_result.scalars().all()
        ]

        circuits.append(CircuitResult(
            id=cid,
            circuit_name=data["circuit_name"],
            circuit_type=data["circuit_type"],
            step_count=step_count,
            function_count=func_count,
            matched_functions=data["matched_functions"],
            match_score=round(match_score, 2),
            steps=steps,
        ))

    # Sort by match_score desc
    circuits.sort(key=lambda c: c.match_score, reverse=True)

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
        prompt = f"""Given these brain function terms: {", ".join(body.functions)}

For each term, provide 3-5 related/synonym terms that would appear in a neuroscientific database.
These are used to search a circuit functions table. Focus on related concepts, broader/narrower terms, and synonyms.

Example: "motor coordination" → ["motor control", "movement regulation", "cerebellar motor", "motor execution", "voluntary movement"]
Example: "vestibular dysfunction" → ["balance disorder", "equilibrium", "vertigo", "vestibulo-ocular", "postural control"]

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
        prompt = CONVERSATION_PROMPT.format(messages=formatted, granularity=body.granularity_level)

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
    cids = [uuid.UUID(c) for c in body.circuit_ids if c]
    if not cids:
        return GraphDataResponse(nodes=[], edges=[])

    from app.models.mirror_kg import MirrorRegionCircuit
    circ_result = await session.execute(
        select(MirrorRegionCircuit).where(MirrorRegionCircuit.id.in_(cids))
    )
    all_circs = circ_result.scalars().all()

    nodes: list[dict] = []
    edges: list[dict] = []
    edge_set: set[str] = set()

    # Circuit nodes
    for circ in all_circs:
        cid = str(circ.id)
        nodes.append({
            "id": cid,
            "label": circ.circuit_name or cid[:12],
            "type": "circuit",
        })

    if not all_circs:
        return GraphDataResponse(nodes=nodes, edges=edges)

    steps_query = text("""
        SELECT
            s.id,
            s.circuit_id::text,
            s.step_order,
            s.step_name,
            s.role,
            s.region_candidate_id::text,
            COALESCE(c.en_name, c.std_name, c.raw_name, s.step_name) as region_label
        FROM mirror_circuit_steps s
        LEFT JOIN candidate_brain_regions c ON c.id = s.region_candidate_id
        WHERE s.circuit_id = ANY(:cids)
        ORDER BY s.circuit_id, s.step_order
    """)
    steps_result = await session.execute(steps_query, {"cids": cids})
    step_rows = steps_result.fetchall()

    # Group steps by circuit
    steps_by_circuit: dict[str, list[dict]] = {}

    for row in step_rows:
        sid = str(row[0])
        scid = str(row[1])
        step_order = row[2]
        step_name = row[3] or "Unknown"
        role = row[4] or "unknown"
        region_candidate_id = row[5] if row[5] and row[5] != "None" else None
        region_label = row[6] or step_name

        if scid not in steps_by_circuit:
            steps_by_circuit[scid] = []

        # One node per step (no dedup — enables co_occurs edges across circuits)
        node_id = f"step_{sid[:12]}"

        info = {
            "id": sid,
            "node_id": node_id,
            "circuit_id": scid,
            "step_order": step_order,
            "step_name": step_name,
            "role": role,
            "region_label": region_label,
            "region_candidate_id": region_candidate_id,
        }
        steps_by_circuit[scid].append(info)

        # Add brain_region node
        region_node: dict[str, object] = {
            "id": node_id,
            "type": "brain_region",
            "label": region_label,
            "circuit_id": scid,
            "step_order": step_order,
            "role": role,
            "step_name": step_name,
        }
        if region_candidate_id:
            region_node["region_candidate_id"] = region_candidate_id
        nodes.append(region_node)

        # belongs_to edge: brain_region node -> circuit
        belongs_key = f"belongs_{node_id}_{scid}"
        if belongs_key not in edge_set:
            edge_set.add(belongs_key)
            edges.append({
                "id": belongs_key,
                "source": node_id,
                "target": scid,
                "label": "belongs_to",
            })

    # step_flow edges: consecutive steps within same circuit
    for scid, steps in steps_by_circuit.items():
        for i in range(len(steps) - 1):
            source_id = steps[i]["node_id"]
            target_id = steps[i + 1]["node_id"]
            flow_key = f"flow_{source_id}_{target_id}"
            if flow_key not in edge_set:
                edge_set.add(flow_key)
                edges.append({
                    "id": flow_key,
                    "source": source_id,
                    "target": target_id,
                    "label": "step_flow",
                })

    # co_occurs edges: connect brain_region nodes from DIFFERENT circuits
    # sharing the same region_candidate_id
    region_to_nodes: dict[str, list[dict]] = {}
    for scid, steps in steps_by_circuit.items():
        for step in steps:
            rc_id = step.get("region_candidate_id")
            if rc_id:
                if rc_id not in region_to_nodes:
                    region_to_nodes[rc_id] = []
                region_to_nodes[rc_id].append(step)

    for rc_id, steps in region_to_nodes.items():
        if len(steps) < 2:
            continue
        # Only connect steps from different circuits
        circuit_ids_set = set(s["circuit_id"] for s in steps)
        if len(circuit_ids_set) < 2:
            continue
        for i in range(len(steps)):
            for j in range(i + 1, len(steps)):
                if steps[i]["circuit_id"] != steps[j]["circuit_id"]:
                    si = steps[i]["node_id"]
                    sj = steps[j]["node_id"]
                    co_key = f"co_{si}_{sj}"
                    if co_key not in edge_set:
                        edge_set.add(co_key)
                        edges.append({
                            "id": co_key,
                            "source": si,
                            "target": sj,
                            "label": "co_occurs",
                        })

    return GraphDataResponse(nodes=nodes, edges=edges)

