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

    cid_list = ",".join(f"'{c}'" for c in body.circuit_ids if c)

    from app.models.mirror_kg import MirrorRegionCircuit
    circ_result = await session.execute(
        select(MirrorRegionCircuit).where(MirrorRegionCircuit.id.in_(cids))
    )
    all_circs = circ_result.scalars().all()
    nodes: list[dict] = []
    edge_set: set[str] = set()
    edges: list[dict] = []
    circ_map: dict[str, str] = {}

    for circ in all_circs:
        cid = str(circ.id)
        name = circ.circuit_name or cid[:12]
        circ_map[name] = cid
        nodes.append({"id": cid, "label": name, "type": "circuit"})

    import re
    region_nodes: dict[str, str] = {}
    for circ_name in circ_map:
        parts = re.split(r'\s*[→\-]+\s*|\s+circuit\s*|\s+pathway\s*|\s+connection\s*', circ_name, flags=re.IGNORECASE)
        for part in parts:
            part = part.strip().lower()
            if len(part) < 3 or part in ('left','right','the','and','or','to','from','unknown'):
                continue
            if part not in region_nodes:
                rid = f"region_{len(region_nodes)}"
                region_nodes[part] = rid
                nodes.append({"id": rid, "label": part.title(), "type": "brain_region"})

    for circ in all_circs:
        cid = str(circ.id)
        circ_parts = re.split(r'\s*[→\-]+\s*|\s+circuit\s*|\s+pathway\s*', circ.circuit_name or '', flags=re.IGNORECASE)
        circ_regions = []
        for part in circ_parts:
            part = part.strip().lower()
            if part in region_nodes:
                rid = region_nodes[part]
                circ_regions.append(rid)
                key = f"{cid}-{rid}"
                if key not in edge_set:
                    edge_set.add(key)
                    edges.append({"id": key, "source": cid, "target": rid, "label": "belongs_to"})
        for i in range(len(circ_regions)):
            for j in range(i+1, len(circ_regions)):
                key = f"{circ_regions[i]}-{circ_regions[j]}"
                if key not in edge_set:
                    edge_set.add(key)
                    edges.append({"id": key, "source": circ_regions[i], "target": circ_regions[j], "label": "co_occurs"})

    return GraphDataResponse(nodes=nodes, edges=edges)

