"""Circuit -> Connection LLM extraction service.

Inspects circuit semantic data and uses LLM to infer missing
mirror_region_connections. Two modes:
  - multi_connection: N connections per circuit
  - main_pair: 1 region pair per circuit + backfill circuit region IDs
"""

from __future__ import annotations

import asyncio
import json
import logging
import uuid
from datetime import datetime, timezone
from typing import Any

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.candidate import CandidateBrainRegion
from app.models.mirror_kg import MirrorRegionCircuit, MirrorRegionConnection
from app.models.mirror_macro_clinical import MirrorCircuitFunction, MirrorCircuitStep
from app.models.llm_circuit_connection_extraction import (
    LlmCircuitConnectionExtractionItem,
    LlmCircuitConnectionExtractionRun,
)
from app.schemas.llm_circuit_connection_extraction import ExtractionMode
from app.services.llm_field_completion_service import call_provider
from app.utils.json_safety import to_jsonable

logger = logging.getLogger(__name__)

# -- Region name matching ----------------------------------------------------

async def match_region_name(
    session: AsyncSession,
    name: str,
    *,
    pool_batch_id: uuid.UUID | None = None,
) -> uuid.UUID | None:
    """Match an English (or Chinese) region name to a candidate_brain_region.

    Strategy:
    1. Exact match on en_name (case-insensitive)
    2. Substring match (name contains candidate en_name or vice versa)
    3. Match on cn_name if input looks Chinese
    4. Simple word overlap fallback
    """
    import re

    name_lower = name.strip().lower()
    is_chinese = bool(re.search(r'[一-鿿]', name))

    # 1. Exact match on en_name
    stmt = select(CandidateBrainRegion).where(
        func.lower(CandidateBrainRegion.en_name) == name_lower
    )
    if pool_batch_id:
        stmt = stmt.where(CandidateBrainRegion.batch_id == pool_batch_id)
    result = await session.execute(stmt.limit(1))
    match = result.scalar_one_or_none()
    if match:
        return match.id

    # 2. Substring match
    stmt = select(CandidateBrainRegion).where(
        CandidateBrainRegion.en_name.ilike(f"%{name_lower}%")
        | func.lower(CandidateBrainRegion.en_name).in_(
            select(func.lower(CandidateBrainRegion.en_name)).where(
                CandidateBrainRegion.en_name.ilike(f"%{name_lower.split()[-1]}%")
            )
        )
    )
    if pool_batch_id:
        stmt = stmt.where(CandidateBrainRegion.batch_id == pool_batch_id)
    result = await session.execute(stmt.limit(3))
    candidates = list(result.scalars().all())
    if len(candidates) == 1:
        return candidates[0].id
    if candidates:
        # Best match: shortest name that contains all words
        words = set(name_lower.split())
        best = min(candidates, key=lambda c: len(c.en_name or ''))
        return best.id

    # 3. Chinese name match
    if is_chinese:
        stmt = select(CandidateBrainRegion).where(
            CandidateBrainRegion.cn_name == name.strip()
        )
        if pool_batch_id:
            stmt = stmt.where(CandidateBrainRegion.batch_id == pool_batch_id)
        result = await session.execute(stmt.limit(1))
        match = result.scalar_one_or_none()
        if match:
            return match.id

    # 4. Simple word overlap fallback (no external deps)
    words = set(name_lower.split())
    stmt = select(CandidateBrainRegion)
    if pool_batch_id:
        stmt = stmt.where(CandidateBrainRegion.batch_id == pool_batch_id)
    result = await session.execute(stmt)
    best_score = 0
    best_id = None
    for c in result.scalars().all():
        if not c.en_name:
            continue
        c_words = set(c.en_name.lower().split())
        overlap = len(words & c_words)
        if overlap > best_score:
            best_score = overlap
            best_id = c.id
    if best_score >= 1:
        return best_id

    return None


# -- Dedup and write logic ----------------------------------------------------

async def dedup_and_write_connection(
    session: AsyncSession,
    source_candidate_id: uuid.UUID,
    target_candidate_id: uuid.UUID,
    connection_type: str,
    confidence: float,
    evidence_text: str,
    *,
    run_id: uuid.UUID,
    overwrite_policy: str = "fill_missing_only",
) -> tuple[uuid.UUID | None, str, str | None]:
    """Insert or update a mirror_region_connection via confidence competition.

    Returns: (connection_id, action, reason)
      action: "created" | "updated" | "skipped"
    """
    # Check existing
    stmt = select(MirrorRegionConnection).where(
        MirrorRegionConnection.source_region_candidate_id == source_candidate_id,
        MirrorRegionConnection.target_region_candidate_id == target_candidate_id,
    )
    result = await session.execute(stmt)
    existing = result.scalar_one_or_none()

    conn_type = connection_type or "uncertain_connection"

    if existing is None:
        conn = MirrorRegionConnection(
            id=uuid.uuid4(),
            source_region_candidate_id=source_candidate_id,
            target_region_candidate_id=target_candidate_id,
            connection_type=conn_type,
            confidence=confidence,
            evidence_text=evidence_text,
            mirror_status="llm_suggested",
            granularity_level="macro",
            granularity_family="macro_clinical",
            source_atlas="llm_circuit_connection_extraction",
            raw_payload_json={},
            normalized_payload_json={},
            review_status="pending",
            promotion_status="not_promoted",
        )
        session.add(conn)
        await session.flush()
        return conn.id, "created", None

    # Competition
    existing_confidence = float(existing.confidence or 0)
    if confidence > existing_confidence:
        existing.connection_type = conn_type
        existing.confidence = confidence
        existing.evidence_text = evidence_text
        existing.mirror_status = "llm_suggested"
        await session.flush()
        return existing.id, "updated", f"confidence {existing_confidence} -> {confidence}"
    elif overwrite_policy == "fill_missing_only" and existing.confidence is None:
        existing.confidence = confidence
        existing.evidence_text = evidence_text
        await session.flush()
        return existing.id, "updated", "filled missing confidence"
    else:
        return existing.id, "skipped", f"existing confidence {existing_confidence} >= new {confidence}"


# -- Circuit context builder --------------------------------------------------

async def build_circuit_context(
    session: AsyncSession,
    circuit: MirrorRegionCircuit,
    *,
    include_existing_connections: bool = True,
) -> str:
    """Build the full text context for LLM prompt from circuit + steps + functions."""
    lines = [
        f"Circuit: {circuit.circuit_name or '(unnamed)'}",
        f"Type: {circuit.circuit_type or 'unknown'}",
        f"Description: {circuit.description or ''}",
        f"Function: {circuit.function_association or ''}",
    ]

    # Steps
    step_stmt = (
        select(MirrorCircuitStep)
        .where(MirrorCircuitStep.circuit_id == circuit.id)
        .order_by(MirrorCircuitStep.step_order)
    )
    step_result = await session.execute(step_stmt)
    steps = list(step_result.scalars().all())
    if steps:
        lines.append("\nSteps:")
        for s in steps:
            lines.append(
                f"  {s.step_order}. {s.step_name} (role: {s.role})"
                f"{' -- ' + s.description if s.description else ''}"
            )
    else:
        lines.append("\nSteps: (none)")

    # Functions
    func_stmt = select(MirrorCircuitFunction).where(
        MirrorCircuitFunction.circuit_id == circuit.id
    )
    func_result = await session.execute(func_stmt)
    funcs = list(func_result.scalars().all())
    if funcs:
        lines.append("\nFunctions:")
        for f in funcs:
            parts = []
            if f.function_term_en:
                parts.append(f.function_term_en)
            if f.function_domain:
                parts.append(f"(domain: {f.function_domain})")
            if f.function_role:
                parts.append(f"(role: {f.function_role})")
            lines.append(f"  {' '.join(parts)}")
    else:
        lines.append("\nFunctions: (none)")

    # Existing connections (for dedup avoidance)
    if include_existing_connections:
        # Find candidate regions associated with this circuit's steps
        step_region_ids = [s.region_candidate_id for s in steps if s.region_candidate_id]
        existing_conns = []
        if step_region_ids:
            conn_stmt = (
                select(MirrorRegionConnection)
                .where(
                    MirrorRegionConnection.source_region_candidate_id.in_(step_region_ids)
                    | MirrorRegionConnection.target_region_candidate_id.in_(step_region_ids)
                )
                .limit(20)
            )
            conn_result = await session.execute(conn_stmt)
            existing_conns = list(conn_result.scalars().all())

        if existing_conns:
            lines.append("\nExisting connections (avoid duplicates):")
            for c in existing_conns:
                lines.append(
                    f"  {getattr(c, 'source_region_name_en', '?') or '?'}"
                    f" -> {getattr(c, 'target_region_name_en', '?') or '?'}"
                    f" ({c.connection_type}, conf={c.confidence})"
                )

    return '\n'.join(lines)


# -- Prompt templates ---------------------------------------------------------

_MULTI_CONNECTION_SYSTEM = (
    "You are a neuroscientist identifying missing brain region connections.\n"
    "For the circuit described below, identify ALL possible region-to-region\n"
    "connections that likely exist but may be missing from our database.\n"
    "Use neuroanatomical knowledge and the circuit's step/function context.\n\n"
    "For each connection, provide:\n"
    "- source_name: standard English brain region name (e.g. 'left hippocampus')\n"
    "- target_name: standard English brain region name\n"
    "- connection_type: one of structural_connection, functional_connectivity,\n"
    "  effective_connectivity, projection, association, coactivation,\n"
    "  uncertain_connection, unknown\n"
    "- confidence: 0.0-1.0 based on how certain you are\n"
    "- evidence: brief justification from the circuit context\n\n"
    "Output ONLY a valid JSON array. Do NOT include markdown fences or explanation.\n"
    '[{"source_name":"...","target_name":"...","connection_type":"...","confidence":0.0,"evidence":"..."}]'
)

_MAIN_PAIR_SYSTEM = (
    "You are a neuroscientist. Identify the MAIN entry->exit region pair\n"
    "for the brain circuit described below.\n"
    "This represents the primary anatomical pathway of the circuit.\n\n"
    "Output ONLY valid JSON. Do NOT include markdown fences or explanation.\n"
    '{"start_region_name":"English region name","end_region_name":"English region name",'
    '"connection_type":"structural_connection|functional_connectivity|...","confidence":0.0,'
    '"evidence":"Brief justification from circuit context"}'
)

_MULTI_CONNECTION_USER = (
    "Circuit: {name} ({circuit_type})\n"
    "Description: {description}\n"
    "Context:\n{context}\n\n"
    "Identify ALL possible missing connections for this circuit."
)

_MAIN_PAIR_USER = (
    "Circuit: {name} ({circuit_type})\n"
    "Description: {description}\n"
    "Context:\n{context}\n\n"
    "Identify the MAIN entry->exit region pair for this circuit."
)


# -- Per-circuit execution function -------------------------------------------

async def _extract_connections_for_circuit(
    session: AsyncSession,
    circuit: MirrorRegionCircuit,
    *,
    mode: str,
    provider_key: str,
    resolved_model: str,
    temperature: float,
    max_tokens: int,
    overwrite_policy: str,
    create_mirror_updates: bool,
    run_id: uuid.UUID,
) -> tuple[list[LlmCircuitConnectionExtractionItem], int, int]:
    """1 LLM call -> N connections extracted for one circuit.

    Returns: (items, connections_created, connections_updated)
    """
    circuit_context = await build_circuit_context(session, circuit)

    if mode == ExtractionMode.MAIN_PAIR:
        system_prompt = _MAIN_PAIR_SYSTEM
        user_prompt = _MAIN_PAIR_USER.format(
            name=circuit.circuit_name or '',
            circuit_type=circuit.circuit_type or '',
            description=circuit.description or '',
            context=circuit_context,
        )
        is_multi = False
    else:
        system_prompt = _MULTI_CONNECTION_SYSTEM
        user_prompt = _MULTI_CONNECTION_USER.format(
            name=circuit.circuit_name or '',
            circuit_type=circuit.circuit_type or '',
            description=circuit.description or '',
            context=circuit_context,
        )
        is_multi = True

    items: list[LlmCircuitConnectionExtractionItem] = []
    connections_created = 0
    connections_updated = 0

    # -- LLM call ----------------------------------------------------------
    try:
        response = await call_provider(
            provider_key,
            model=resolved_model,
            system_prompt=system_prompt,
            user_prompt=user_prompt,
            temperature=temperature,
            max_tokens=max_tokens,
            response_schema=None,
        )
    except Exception as exc:
        logger.warning("Circuit %s: LLM call failed: %s", str(circuit.id)[:12], exc)
        item = LlmCircuitConnectionExtractionItem(
            id=uuid.uuid4(), run_id=run_id, circuit_id=circuit.id,
            action="skipped", action_reason=f"LLM call failed: {exc}",
        )
        session.add(item)
        items.append(item)
        return items, 0, 0

    # -- Parse response ----------------------------------------------------
    raw_text = getattr(response, 'raw_text', '') or ''
    parsed = getattr(response, 'parsed_json', None)
    if not isinstance(parsed, dict) and not isinstance(parsed, list):
        cleaned = raw_text.strip()
        if cleaned.startswith('```'):
            lines = cleaned.split('\n')
            lines = [l for l in lines if not l.startswith('```')]
            cleaned = '\n'.join(lines).strip()
        try:
            parsed = json.loads(cleaned)
        except (json.JSONDecodeError, TypeError):
            # Try regex extraction
            import re
            match = re.search(r'[\{\[].*[\}\]]', cleaned, re.DOTALL)
            if match:
                try:
                    parsed = json.loads(match.group(0))
                except (json.JSONDecodeError, TypeError):
                    pass

    if not parsed:
        item = LlmCircuitConnectionExtractionItem(
            id=uuid.uuid4(), run_id=run_id, circuit_id=circuit.id,
            action="skipped", action_reason="Empty or unparseable LLM response",
        )
        session.add(item)
        items.append(item)
        return items, 0, 0

    # -- Normalize to list -------------------------------------------------
    if isinstance(parsed, dict):
        parsed = [parsed]
    if not isinstance(parsed, list):
        item = LlmCircuitConnectionExtractionItem(
            id=uuid.uuid4(), run_id=run_id, circuit_id=circuit.id,
            action="skipped", action_reason=f"Unexpected response type: {type(parsed).__name__}",
        )
        session.add(item)
        items.append(item)
        return items, 0, 0

    # -- Process each connection -------------------------------------------
    for conn_data in parsed:
        source_name = conn_data.get("source_name") or conn_data.get("start_region_name", "")
        target_name = conn_data.get("target_name") or conn_data.get("end_region_name", "")
        conn_type = conn_data.get("connection_type", "uncertain_connection")
        confidence = float(conn_data.get("confidence", 0.5) or 0.5)
        evidence = conn_data.get("evidence", "") or ""

        if not source_name or not target_name:
            continue

        # Match region names
        source_id = await match_region_name(session, source_name)
        target_id = await match_region_name(session, target_name)

        if source_id is None or target_id is None:
            item = LlmCircuitConnectionExtractionItem(
                id=uuid.uuid4(), run_id=run_id, circuit_id=circuit.id,
                source_region_name=source_name,
                target_region_name=target_name,
                connection_type=conn_type,
                confidence=confidence,
                evidence_text=evidence,
                source_candidate_id=source_id,
                target_candidate_id=target_id,
                action="no_match",
                action_reason=f"Could not match: {source_name if not source_id else ''} -> {target_name if not target_id else ''}",
            )
            session.add(item)
            items.append(item)
            continue

        if not create_mirror_updates:
            item = LlmCircuitConnectionExtractionItem(
                id=uuid.uuid4(), run_id=run_id, circuit_id=circuit.id,
                source_region_name=source_name, target_region_name=target_name,
                source_candidate_id=source_id, target_candidate_id=target_id,
                connection_type=conn_type, confidence=confidence,
                evidence_text=evidence, action="skipped",
                action_reason="create_mirror_updates=False (dry run)",
            )
            session.add(item)
            items.append(item)
            continue

        conn_id, action, reason = await dedup_and_write_connection(
            session, source_id, target_id, conn_type, confidence, evidence,
            run_id=run_id, overwrite_policy=overwrite_policy,
        )

        if action == "created":
            connections_created += 1
        elif action == "updated":
            connections_updated += 1

        # Mode B: backfill circuit start/end region IDs
        if mode == ExtractionMode.MAIN_PAIR and action in ("created", "updated"):
            _backfill_circuit_region_ids(circuit, source_id, target_id, run_id)

        item = LlmCircuitConnectionExtractionItem(
            id=uuid.uuid4(), run_id=run_id, circuit_id=circuit.id,
            source_region_name=source_name, target_region_name=target_name,
            source_candidate_id=source_id, target_candidate_id=target_id,
            connection_type=conn_type, confidence=confidence,
            evidence_text=evidence, connection_id=conn_id,
            action=action, action_reason=reason,
        )
        session.add(item)
        items.append(item)

    return items, connections_created, connections_updated


# -- Backfill circuit region IDs helper (Mode B only) ------------------------

def _backfill_circuit_region_ids(
    circuit: MirrorRegionCircuit,
    start_region_id: uuid.UUID,
    end_region_id: uuid.UUID,
    run_id: uuid.UUID,
) -> None:
    """Write canonical_start/end_region_id to circuit's overlay (Mode B only)."""
    from sqlalchemy.orm.attributes import flag_modified

    payload = dict(circuit.normalized_payload_json or {})
    overlay = dict(payload.get("formal_field_overlay") or {})
    overlay_meta = dict(payload.get("formal_field_overlay_meta") or {})
    now_iso = datetime.now(timezone.utc).isoformat()

    overlay["canonical_start_region_id"] = str(start_region_id)
    overlay["canonical_end_region_id"] = str(end_region_id)
    overlay_meta["canonical_start_region_id"] = {
        "source": "llm_circuit_connection_extraction",
        "run_id": str(run_id),
        "updated_at": now_iso,
    }
    overlay_meta["canonical_end_region_id"] = {
        "source": "llm_circuit_connection_extraction",
        "run_id": str(run_id),
        "updated_at": now_iso,
    }

    payload["formal_field_overlay"] = overlay
    payload["formal_field_overlay_meta"] = overlay_meta
    circuit.normalized_payload_json = to_jsonable(payload)
    flag_modified(circuit, "normalized_payload_json")


# -- Main orchestrator --------------------------------------------------------

async def execute_circuit_connection_extraction(
    session: AsyncSession,
    run: LlmCircuitConnectionExtractionRun,
    *,
    circuit_ids: list[uuid.UUID],
    mode: str,
    provider_key: str,
    resolved_model: str,
    temperature: float,
    max_tokens: int,
    overwrite_policy: str,
    create_mirror_updates: bool,
    check_cancelled=None,
) -> tuple[list[LlmCircuitConnectionExtractionItem], int, int]:
    """Execute circuit->connection extraction for multiple circuits.

    Returns: (items, connections_created, connections_updated)
    """
    all_items: list[LlmCircuitConnectionExtractionItem] = []
    total_created = 0
    total_updated = 0
    total = len(circuit_ids)
    processed = 0

    for cid in circuit_ids:
        if check_cancelled and await check_cancelled(session, run.id):
            break

        circuit = await session.get(MirrorRegionCircuit, cid)
        if circuit is None:
            item = LlmCircuitConnectionExtractionItem(
                id=uuid.uuid4(), run_id=run.id, circuit_id=None,
                action="skipped", action_reason="Circuit not found",
            )
            session.add(item)
            all_items.append(item)
            processed += 1
            continue

        items, created, updated = await _extract_connections_for_circuit(
            session, circuit,
            mode=mode, provider_key=provider_key,
            resolved_model=resolved_model,
            temperature=temperature, max_tokens=max_tokens,
            overwrite_policy=overwrite_policy,
            create_mirror_updates=create_mirror_updates,
            run_id=run.id,
        )
        all_items.extend(items)
        total_created += created
        total_updated += updated
        processed += 1

        # Progress every 5 circuits
        if processed % 5 == 0 or processed == total:
            run.summary_json = to_jsonable({
                **(run.summary_json or {}),
                "total_circuits": total,
                "processed_circuits": processed,
                "connections_created": total_created,
                "connections_updated": total_updated,
                "items_count": len(all_items),
            })
            from sqlalchemy.orm.attributes import flag_modified
            flag_modified(run, "summary_json")
            await session.commit()

    return all_items, total_created, total_updated
