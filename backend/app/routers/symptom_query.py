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
    categories: list[str] = []
    primary_category: str = "other"


class SymptomSearchRequest(BaseModel):
    functions: list[str]
    categories: list[str] = []
    granularity_level: str = "macro"


class CircuitResult(BaseModel):
    id: str
    circuit_name: str
    circuit_type: str | None = None
    step_count: int = 0
    function_count: int = 0
    matched_functions: list[str]
    match_score: float
    relevance: float = 0.0
    matched_categories: list[str] = []
    steps: list[dict[str, Any]] = []

    model_config = {"from_attributes": True}


class SymptomSearchResponse(BaseModel):
    circuits: list[CircuitResult]


# ── Analyze — LLM symptom → functions ──────────────────────────────────────

ANALYZE_PROMPT = """You are a clinical neuroscientist. Convert the patient's symptom description into standardized brain function terms with categories.

Categories (pick ONE per function): motor, sensory, cognitive, emotional, autonomic, memory, language, attention, other

Rules:
- 'multi' mode: return 2-5 function terms + categories
- 'single' mode: return 1 function term + category
- Use standard neuroanatomical terminology

Output ONLY this JSON object:
{{"functions":["term1","term2"],"categories":["motor","sensory"],"primary_category":"motor"}}

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
            categories = ["other"] * len(functions)
            primary = "other"
        elif isinstance(parsed, dict):
            functions = [str(f) for f in (parsed.get("functions") or [])][:5]
            categories = [str(c) for c in (parsed.get("categories") or [])][:len(functions)]
            primary = str(parsed.get("primary_category", categories[0] if categories else "other"))
        else:
            functions = [body.symptom]
            categories = ["other"]
            primary = "other"
        # Ensure categories match function count
        while len(categories) < len(functions):
            categories.append("other")
        return SymptomAnalyzeResponse(functions=functions, categories=categories, primary_category=primary)
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
        SELECT DISTINCT c.id, c.circuit_name, c.circuit_type,
               cf.function_domain, cf.function_term_en, cf.function_role,
               GREATEST(similarity(cf.function_domain, :sim_q), similarity(cf.function_term_en, :sim_q)) as sim
        FROM mirror_circuit_functions cf
        JOIN mirror_region_circuits c ON c.id = cf.circuit_id
        WHERE ({where_clause})
          AND c.granularity_level = :granularity
        LIMIT 200
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
        fn_domain = (row[3] or "").strip().lower()
        fn_term = (row[4] or "").strip().lower()
        sim = float(row[6] or 0)
        if cid not in circuit_data:
            circuit_data[cid] = {
                "id": cid,
                "circuit_name": row[1] or "Unknown",
                "circuit_type": row[2],
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

    # Weighted relevance scoring per circuit
    scored = []
    for cid, d in circuit_data.items():
        uid = uuid.UUID(cid)
        # Count total functions for density
        func_count = await session.scalar(
            select(func.count()).select_from(MirrorCircuitFunction).where(
                MirrorCircuitFunction.circuit_id == uid
            )
        ) or 1
        # Category match: how many of this circuit's function domains match symptom categories
        circuit_cats = set()
        for fd in d["fn_domains"]:
            for sc in symptom_cats:
                if sc in fd or fd in sc:
                    circuit_cats.add(sc)
        d["matched_categories"] = list(circuit_cats)
        cat_bonus = min(30, len(circuit_cats) * 10)  # 0-30
        sim_score = min(50, d["sim"] * 50)            # 0-50
        density = min(20, len(d["matched_functions"]) / max(func_count, 1) * 20)  # 0-20
        relevance = cat_bonus + sim_score + density
        d["relevance"] = round(relevance, 1)
        d["func_count"] = func_count
        scored.append(d)

    # Filter relevance >= 5 (lenient enough for circuits with sparse function_domain data)
    scored = [d for d in scored if d["relevance"] >= 5]
    scored.sort(key=lambda d: d["relevance"], reverse=True)
    scored = scored[:50]

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
        circuits.append(CircuitResult(
            id=d["id"], circuit_name=d["circuit_name"], circuit_type=d["circuit_type"],
            step_count=step_count, function_count=d["func_count"],
            matched_functions=d["matched_functions"][:10],
            match_score=round(min(1.0, len(d["matched_functions"]) / max(d["func_count"], 1)), 2),
            relevance=d["relevance"], matched_categories=d.get("matched_categories", []),
            steps=steps,
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
    """Unified brain-region + connection graph. Each node/edge carries `circuit_ids`
    so the frontend can highlight one circuit's path through the network."""
    cids = [uuid.UUID(c) for c in body.circuit_ids if c]
    if not cids:
        return GraphDataResponse(nodes=[], edges=[])

    # ── Step → region mapping per circuit ──────────────────────────────────
    steps_sql = text("""
        SELECT s.circuit_id::text, s.region_candidate_id::text,
               COALESCE(cbr.en_name, cbr.std_name, cbr.raw_name, s.step_name) as label,
               s.step_name
        FROM mirror_circuit_steps s
        LEFT JOIN candidate_brain_regions cbr ON cbr.id = s.region_candidate_id
        WHERE s.circuit_id = ANY(:cids)
    """)
    rows = (await session.execute(steps_sql, {"cids": cids})).fetchall()
    if not rows:
        return GraphDataResponse(nodes=[], edges=[])

    # Dedup: use region_candidate_id if present, else fallback to step_name per circuit
    region_circuits: dict[str, set[str]] = {}
    region_labels: dict[str, str] = {}
    for row in rows:
        cid = str(row[0]); rid_raw = row[1]; label = row[2] or row[3] or "?"
        rid = str(rid_raw) if rid_raw else f"{cid}:{label}"
        region_circuits.setdefault(rid, set()).add(cid)
        region_labels[rid] = label

    nodes = [{"id": rid, "type": "brain_region", "label": region_labels[rid],
              "circuit_ids": sorted(region_circuits[rid])} for rid in region_circuits]

    # ── Connections between these brain regions ─────────────────────────────
    rids = list(region_circuits.keys())
    if len(rids) < 2:
        return GraphDataResponse(nodes=nodes, edges=[])

    conn_sql = text("""
        SELECT id::text, source_region_candidate_id::text, target_region_candidate_id::text,
               connection_type, confidence, strength,
               COALESCE(source_region_name_en,'') sname, COALESCE(target_region_name_en,'') tname
        FROM mirror_region_connections
        WHERE source_region_candidate_id = ANY(:rids)
          AND target_region_candidate_id = ANY(:rids)
          AND granularity_level = :gran
        LIMIT 5000
    """)
    cr = (await session.execute(conn_sql, {"rids": rids, "gran": body.granularity_level})).fetchall()

    cid_set = set(str(c) for c in cids)
    edges = []
    for row in cr:
        eid = str(row[0]); src = str(row[1]); tgt = str(row[2])
        ecids = sorted((region_circuits.get(src, set()) | region_circuits.get(tgt, set())) & cid_set)
        edges.append({
            "id": eid, "source": src, "target": tgt,
            "type": row[3] or "unknown", "confidence": float(row[4] or 0),
            "strength": float(row[5] or 0), "source_name": row[6] or "", "target_name": row[7] or "",
            "circuit_ids": ecids,
        })

    return GraphDataResponse(nodes=nodes, edges=edges)

