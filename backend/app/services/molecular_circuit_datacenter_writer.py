"""Write validated molecular circuit steps to the candidate-pool and datacenter.

Phase 5 of the Molecular circuit extraction v2 pipeline.  Consumes circuits
that have passed the Quality Gate (Phase 4) and writes them into:

    1. ``mirror_molecular_circuit_candidates`` — circuit-level storage.
    2. ``mirror_kg_triples`` — step-level (edge-level) relation records,
       one per circuit step ("datacenter relation records").

**Critical rules** (spec sections 12-13):
    - Brain-region fields MUST come from ``candidate_brain_regions``, NOT from
      DeepSeek free-text output.
    - ``id`` uses DB-generated UUIDs, never array indices.
    - ``predicate`` inherits from the original connection — never ``related_to``.
    - ``confidence`` from the original connection — NOT from DeepSeek.
    - ``evidence_count`` from the ``mirror_evidence_records`` table.
    - ALL statuses use existing project enums.
    - ``mirror_confidence`` (DeepSeek judgment) stored separately from
      connection ``confidence``.
    - Provenance must be complete and traceable (spec section 12.3 item 18).
    - NEVER write to ``final_*`` / ``kg_*`` tables.
    - NEVER modify ``candidate_brain_regions`` table.

Idempotency is enforced via a composite key:
    ``(extraction_run_id, canonical_key, step_order, edge_id, subject_id,
      predicate, object_id)``

The idempotency hash is stored in the triple's ``raw_payload_json`` under
``"_idempotency_key"`` so that retries, resume, and duplicate submissions
produce exactly one record.
"""

from __future__ import annotations

import hashlib
import logging
import uuid
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.candidate import CandidateBrainRegion
from app.models.mirror_kg import MirrorEvidenceRecord, MirrorKgTriple
from app.models.molecular_circuit_candidate import MirrorMolecularCircuitCandidate
from app.schemas.mirror_kg import (
    MirrorPromotionStatus,
    MirrorReviewStatus,
    MirrorStatus,
)
from app.services.molecular_circuit_datacenter_validator import validate_datacenter_record

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Valid enum values (mirrors app.schemas.mirror_kg for local validation)
# ---------------------------------------------------------------------------

_VALID_REVIEW_STATUSES: set[str] = {
    "pending",
    "approved",
    "rejected",
    "needs_revision",
    "not_required",
}

# ---------------------------------------------------------------------------
# Result types
# ---------------------------------------------------------------------------


@dataclass
class StepWriteResult:
    """Result of writing one circuit step (edge) as a datacenter relation record.

    Attributes:
        step_order: 1-based step index within the circuit.
        edge_id: The original edge UUID as a string.
        status: ``"written"`` | ``"skipped_duplicate"`` | ``"failed"``.
        error: Human-readable error when status is ``"failed"``.
        triple_id: The ``id`` of the created ``MirrorKgTriple``, if any.
    """

    step_order: int
    edge_id: str
    status: str  # "written" | "skipped_duplicate" | "failed"
    error: str = ""
    triple_id: str | None = None


@dataclass
class DatacenterWriteResult:
    """Aggregate result of writing one circuit to the datacenter.

    Attributes:
        circuit_candidate_id: The ``id`` of the inserted
            ``MirrorMolecularCircuitCandidate`` record.
        total_steps: Number of edges/steps in the circuit.
        written: Number of steps successfully written as triples.
        failed: Number of steps that failed.
        skipped_duplicate: Number of steps skipped due to idempotency match.
        step_results: Per-step detail.
        stats: Acceptance metrics per spec section 16.
    """

    circuit_candidate_id: str | None = None
    total_steps: int = 0
    written: int = 0
    failed: int = 0
    skipped_duplicate: int = 0
    step_results: list[StepWriteResult] = field(default_factory=list)
    stats: dict[str, Any] = field(default_factory=dict)


# ---------------------------------------------------------------------------
# Idempotency helpers
# ---------------------------------------------------------------------------


def _build_step_idempotency_key(
    extraction_run_id: uuid.UUID,
    canonical_key: str,
    step_order: int,
    edge_id: str,
    subject_id: str,
    predicate: str,
    object_id: str,
) -> str:
    """Build a deterministic idempotency key for one step/edge.

    The key is an SHA-256 hex digest of the concatenated inputs.
    """
    raw = f"{extraction_run_id}::{canonical_key}::{step_order}::{edge_id}::{subject_id}::{predicate}::{object_id}"
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()


async def _find_existing_triple_by_idempotency_key(
    session: AsyncSession,
    idempotency_key: str,
) -> MirrorKgTriple | None:
    """Check whether a triple with the given idempotency key already exists.

    The key is stored in ``raw_payload_json`` under ``"_idempotency_key"``.
    """
    stmt = select(MirrorKgTriple).where(
        MirrorKgTriple.raw_payload_json["_idempotency_key"].as_string() == idempotency_key
    ).limit(1)
    return (await session.execute(stmt)).scalar_one_or_none()


# ---------------------------------------------------------------------------
# Core write function
# ---------------------------------------------------------------------------


async def write_circuit_to_datacenter(
    session: AsyncSession,
    circuit: dict[str, Any],
    candidate_regions: dict[str, CandidateBrainRegion],
    extraction_run_id: uuid.UUID,
    pack_id: int,
    prompt_version: str,
    model: str,
    quality_gate_version: str = "v1",
) -> DatacenterWriteResult:
    """Write one validated circuit to the candidate pool and datacenter.

    The pipeline for each circuit is:

        1. Create a ``MirrorMolecularCircuitCandidate`` record (circuit level).
        2. For each edge in the circuit's ``edges`` list, create a
           ``MirrorKgTriple`` record (step-level relation record).
        3. Return detailed acceptance metrics.

    Args:
        session: Async SQLAlchemy session.
        circuit: Validated circuit candidate dict (post-Quality Gate).
        candidate_regions: ``{region_id: CandidateBrainRegion}`` lookup for
            all 574 molecular regions.  The caller is responsible for populating
            this dict **before** calling this function.  Region IDs are UUIDs
            as strings.
        extraction_run_id: ID of the ``MolecularCircuitCandidateRun``.
        pack_id: Pack index that this circuit belonged to.
        prompt_version: Prompt version string used for LLM judgment.
        model: Model name used (e.g. ``"deepseek-v4-pro"``).
        quality_gate_version: Version identifier for the quality gate logic.

    Returns:
        A :class:`DatacenterWriteResult` with per-step detail and aggregate stats.

    Raises:
        ValueError: When a region referenced in the circuit's edges does not
            exist in ``candidate_regions``.  (This is a precondition failure —
            the quality gate should have caught it already.)
    """
    step_results: list[StepWriteResult] = []
    total_steps = 0
    written = 0
    failed = 0
    skipped_duplicate = 0

    edges = circuit.get("edges", [])
    nodes = circuit.get("nodes", [])
    canonical_key = circuit.get("canonical_key", "")
    total_steps = len(edges)

    # ── Phase A: Write circuit-level record ──────────────────────────────
    circuit_candidate = await _write_circuit_candidate(
        session=session,
        circuit=circuit,
        canonical_key=canonical_key,
        extraction_run_id=extraction_run_id,
        pack_id=pack_id,
        prompt_version=prompt_version,
        model=model,
    )
    circuit_candidate_id = str(circuit_candidate.id)
    circuit_candidate_uuid = circuit_candidate.id

    # Metadata flags for acceptance tracking
    all_fields_complete = 0
    region_match_failures = 0
    illegal_predicate_count = 0
    missing_evidence = 0
    illegal_status_count = 0
    duplicate_intercepts = 0
    provenance_complete = 0
    region_match_count = 0
    source_confidence_count = 0
    mirror_confidence_count = 0
    evidence_count_coverage = 0
    mirror_evidence_text_count = 0

    # ── Phase B: Write each edge as a step-level triple ─────────────────
    for edge in edges:
        step_order = edge.get("order", 1)
        edge_id = str(edge.get("edge_id", ""))
        source_id = str(edge.get("source_region_id", ""))
        target_id = str(edge.get("target_region_id", ""))

        # B1: Validate source/target exist in candidate_regions
        source_region = candidate_regions.get(source_id)
        target_region = candidate_regions.get(target_id)

        if source_region is None or target_region is None:
            missing = (
                f"source={source_id}" if source_region is None else ""
            ) + (
                f"; target={target_id}" if target_region is None else ""
            )
            step_results.append(
                StepWriteResult(
                    step_order=step_order,
                    edge_id=edge_id,
                    status="failed",
                    error=f"Region not found in candidate_regions: {missing}",
                )
            )
            failed += 1
            region_match_failures += 1
            continue

        region_match_count += 1

        # B2: Build subject/object from candidate_regions (NEVER DeepSeek)
        subject_type = "region_candidate"
        subject_id_uuid = source_region.id
        subject_label = source_region.en_name or source_region.std_name or source_region.raw_name
        object_type = "region_candidate"
        object_id_uuid = target_region.id
        object_label = target_region.en_name or target_region.std_name or target_region.raw_name

        # B3: predicate from original connection (NEVER made up by LLM)
        predicate = edge.get("connection_type") or edge.get("predicate", "")
        if not predicate or predicate in ("related_to", "associated_with", "unknown", ""):
            # Fallback: use the original connection_type from the edge record
            predicate = edge.get("connection_type", "projection")
        if predicate in ("related_to", "associated_with", "unknown", ""):
            step_results.append(
                StepWriteResult(
                    step_order=step_order,
                    edge_id=edge_id,
                    status="failed",
                    error=f"Illegal predicate: '{predicate}'",
                )
            )
            failed += 1
            illegal_predicate_count += 1
            continue

        # B4: confidence from original connection (NEVER from DeepSeek)
        connection_confidence = edge.get("source_confidence") or edge.get("confidence")

        # B5: evidence_count from evidence table
        evidence_count = await _count_evidence_for_edge(session, edge_id)
        if evidence_count is not None and evidence_count > 0:
            evidence_count_coverage += 1
        else:
            missing_evidence += 1

        # B6: mirror_confidence from DeepSeek (stored separately)
        mirror_confidence = circuit.get("overall_confidence")
        if mirror_confidence is not None:
            mirror_confidence_count += 1

        # B7: mirror_evidence_text from DeepSeek
        mirror_evidence_text = circuit.get("functional_summary") or circuit.get("neuroscience_rationale")
        if mirror_evidence_text:
            mirror_evidence_text_count += 1

        # B8: statuses using existing enums
        review_status = _derive_review_status(circuit.get("confidence_level", "medium"))
        if review_status not in _VALID_REVIEW_STATUSES:
            step_results.append(
                StepWriteResult(
                    step_order=step_order,
                    edge_id=edge_id,
                    status="failed",
                    error=f"Illegal review_status: '{review_status}'",
                )
            )
            failed += 1
            illegal_status_count += 1
            continue

        # B9: Build full provenance (spec section 12.3 item 18)
        provenance = _build_provenance(
            extraction_run_id=extraction_run_id,
            canonical_key=canonical_key,
            step_order=step_order,
            edge_id=edge_id,
            source_region_id=str(source_region.id),
            target_region_id=str(target_region.id),
            circuit_id=str(circuit_candidate.id),
            pack_id=pack_id,
            functional_modules=circuit.get("functional_module", []),
            topology_type=circuit.get("topology_type", ""),
            anatomical_pattern=circuit.get("anatomical_pattern", ""),
            prompt_version=prompt_version,
            model=model,
            quality_gate_version=quality_gate_version,
        )
        if _is_provenance_complete(provenance):
            provenance_complete += 1

        # B10: Idempotency key
        idempotency_key = _build_step_idempotency_key(
            extraction_run_id=extraction_run_id,
            canonical_key=canonical_key,
            step_order=step_order,
            edge_id=edge_id,
            subject_id=str(subject_id_uuid),
            predicate=predicate,
            object_id=str(object_id_uuid),
        )

        # B11: Check for existing triple with this idempotency key
        existing = await _find_existing_triple_by_idempotency_key(session, idempotency_key)
        if existing is not None:
            step_results.append(
                StepWriteResult(
                    step_order=step_order,
                    edge_id=edge_id,
                    status="skipped_duplicate",
                    triple_id=str(existing.id),
                )
            )
            skipped_duplicate += 1
            duplicate_intercepts += 1
            continue

        # B12: Validate then write MirrorKgTriple record
        try:
            raw_payload = {
                "_idempotency_key": idempotency_key,
                "provenance": provenance,
                "extraction_run_id": str(extraction_run_id),
                "canonical_key": canonical_key,
                "step_order": step_order,
                "edge_id": edge_id,
                "evidence_count": evidence_count,
                "mirror_confidence": mirror_confidence,
                "mirror_evidence_text": mirror_evidence_text,
                "functional_modules": circuit.get("functional_module", []),
                "topology_type": circuit.get("topology_type", ""),
                "anatomical_pattern": circuit.get("anatomical_pattern", ""),
                "validation_status": "passed",
            }

            provisional = {
                "id": str(uuid.uuid4()),
                "subject_type": subject_type,
                "subject_id": str(subject_id_uuid),
                "subject_label": subject_label,
                "predicate": predicate,
                "object_type": object_type,
                "object_id": str(object_id_uuid),
                "object_label": object_label,
                "confidence": connection_confidence,
                "evidence_count": evidence_count,
                "mirror_status": MirrorStatus.llm_suggested,
                "review_status": review_status,
                "promotion_status": MirrorPromotionStatus.not_promoted,
                "validation_status": "passed",
                "mirror_confidence": mirror_confidence,
                "mirror_evidence_text": mirror_evidence_text,
                "provenance": provenance,
                "source": str(subject_id_uuid),
                "target": str(object_id_uuid),
                "edge_id": edge_id,
            }
            gate = validate_datacenter_record(
                provisional,
                valid_region_ids=set(candidate_regions.keys()),
            )
            if not gate.passed:
                detail = "; ".join(f"{v.field}: {v.detail}" for v in gate.violations[:5])
                step_results.append(
                    StepWriteResult(
                        step_order=step_order,
                        edge_id=edge_id,
                        status="failed",
                        error=f"datacenter validation failed: {detail}",
                    )
                )
                failed += 1
                continue

            triple = MirrorKgTriple(
                subject_type=subject_type,
                subject_id=subject_id_uuid,
                subject_label=subject_label,
                predicate=predicate,
                object_type=object_type,
                object_id=object_id_uuid,
                object_label=object_label,
                triple_scope="same_granularity",
                granularity_level=getattr(source_region, "granularity_level", None) or "molecular_attr",
                granularity_family=getattr(source_region, "granularity_family", None) or "molecular_attr",
                source_atlas=getattr(source_region, "source_atlas", None) or "unknown",
                source_version=getattr(source_region, "source_version", None),
                confidence=connection_confidence,
                evidence_text=mirror_evidence_text,
                mirror_status=MirrorStatus.llm_suggested,
                review_status=review_status,
                promotion_status=MirrorPromotionStatus.not_promoted,
                raw_payload_json=raw_payload,
                created_by=f"molecular_circuit_extraction:{str(extraction_run_id)}",
            )

            session.add(triple)
            await session.flush()
            await session.refresh(triple)

            if connection_confidence is not None:
                source_confidence_count += 1

            step_results.append(
                StepWriteResult(
                    step_order=step_order,
                    edge_id=edge_id,
                    status="written",
                    triple_id=str(triple.id),
                )
            )
            written += 1

            if (
                subject_label
                and object_label
                and predicate
                and connection_confidence is not None
                and evidence_count is not None
                and mirror_confidence is not None
                and mirror_evidence_text
            ):
                all_fields_complete += 1

        except Exception as exc:
            logger.warning(
                "Failed to write triple for step %d (edge %s): %s",
                step_order, edge_id, exc,
            )
            step_results.append(
                StepWriteResult(
                    step_order=step_order,
                    edge_id=edge_id,
                    status="failed",
                    error=str(exc),
                )
            )
            failed += 1

    # ── Build acceptance stats (spec section 16) ─────────────────────────
    stats: dict[str, Any] = {
        "circuits_generated": 1,
        "total_steps": total_steps,
        "records_written_to_datacenter": written,
        "records_all_fields_complete": all_fields_complete,
        "records_nullable_fields_missing": total_steps - all_fields_complete,
        "region_match_failures": region_match_failures,
        "illegal_predicate_failures": illegal_predicate_count,
        "manual_review_for_missing_evidence": missing_evidence,
        "illegal_status_failures": illegal_status_count,
        "duplicate_intercepts": duplicate_intercepts,
        "provenance_complete_count": provenance_complete,
        "provenance_complete_rate_pct": (
            round(provenance_complete / total_steps * 100, 2) if total_steps > 0 else 0.0
        ),
        "region_match_rate_pct": (
            round(region_match_count / total_steps * 100, 2) if total_steps > 0 else 0.0
        ),
        "source_confidence_coverage_pct": (
            round(source_confidence_count / total_steps * 100, 2) if total_steps > 0 else 0.0
        ),
        "mirror_confidence_coverage_pct": (
            round(mirror_confidence_count / total_steps * 100, 2) if total_steps > 0 else 0.0
        ),
        "evidence_count_coverage_pct": (
            round(evidence_count_coverage / total_steps * 100, 2) if total_steps > 0 else 0.0
        ),
        "mirror_evidence_text_coverage_pct": (
            round(mirror_evidence_text_count / total_steps * 100, 2) if total_steps > 0 else 0.0
        ),
    }

    return DatacenterWriteResult(
        circuit_candidate_id=circuit_candidate_id,
        total_steps=total_steps,
        written=written,
        failed=failed,
        skipped_duplicate=skipped_duplicate,
        step_results=step_results,
        stats=stats,
    )


# ---------------------------------------------------------------------------
# Circuit-level write
# ---------------------------------------------------------------------------


async def _write_circuit_candidate(
    session: AsyncSession,
    circuit: dict[str, Any],
    canonical_key: str,
    extraction_run_id: uuid.UUID,
    pack_id: int,
    prompt_version: str,
    model: str,
) -> MirrorMolecularCircuitCandidate:
    """Create a ``MirrorMolecularCircuitCandidate`` record (idempotent).

    Idempotency is enforced by the UNIQUE(canonical_key, extraction_run_id)
    constraint on the table.  If a record with the same key already exists,
    the existing record is returned.
    """
    # Check for existing circuit candidate with same canonical key
    stmt = select(MirrorMolecularCircuitCandidate).where(
        MirrorMolecularCircuitCandidate.canonical_key == canonical_key,
        MirrorMolecularCircuitCandidate.extraction_run_id == extraction_run_id,
    ).limit(1)
    existing = (await session.execute(stmt)).scalar_one_or_none()
    if existing is not None:
        logger.info(
            "Circuit candidate already exists for canonical_key='%s' (run %s) — returning existing.",
            canonical_key, extraction_run_id,
        )
        return existing

    nodes = circuit.get("nodes", [])
    edges = circuit.get("edges", [])
    closed_loop = circuit.get("closed_loop", False)

    candidate = MirrorMolecularCircuitCandidate(
        extraction_run_id=extraction_run_id,
        pack_id=pack_id,
        canonical_key=canonical_key,
        topology_type=circuit.get("topology_type"),
        anatomical_pattern=circuit.get("anatomical_pattern"),
        closed_loop=closed_loop,
        node_count=len(nodes),
        edge_count=len(edges),
        name_en=circuit.get("name_en"),
        name_cn=circuit.get("name_cn"),
        functional_module=circuit.get("functional_module", []),
        known_status=circuit.get("known_status"),
        overall_confidence=circuit.get("overall_confidence"),
        confidence_level=circuit.get("confidence_level"),
        topology_score=circuit.get("topology_score"),
        anatomical_score=circuit.get("anatomical_score"),
        functional_score=circuit.get("functional_score"),
        evidence_score=circuit.get("evidence_score"),
        pre_score=circuit.get("pre_score"),
        nodes_json=nodes,
        edges_json=edges,
        llm_raw_response_json=circuit.get("llm_raw_response_json", {}),
        validation_result_json=circuit.get("validation_result_json", {}),
        review_status="candidate",
    )

    session.add(candidate)
    await session.flush()
    await session.refresh(candidate)
    return candidate


# ---------------------------------------------------------------------------
# Evidence counting
# ---------------------------------------------------------------------------


async def _count_evidence_for_edge(
    session: AsyncSession,
    edge_id: str,
) -> int:
    """Count evidence records associated with an edge.

    Looks up ``MirrorEvidenceRecord`` rows whose ``evidence_target_id``
    matches the given edge.  If the edge hasn't been promoted to Mirror KG
    yet (no evidence records), returns 0.
    """
    try:
        edge_uuid = uuid.UUID(edge_id)
    except (ValueError, TypeError):
        return 0

    stmt = select(func.count(MirrorEvidenceRecord.id)).where(
        MirrorEvidenceRecord.evidence_target_id == edge_uuid,
    )
    result = await session.execute(stmt)
    count = result.scalar()
    return count or 0


# ---------------------------------------------------------------------------
# Provenance builder
# ---------------------------------------------------------------------------


def _build_provenance(
    extraction_run_id: uuid.UUID,
    canonical_key: str,
    step_order: int,
    edge_id: str,
    source_region_id: str,
    target_region_id: str,
    circuit_id: str,
    pack_id: int,
    functional_modules: list[str],
    topology_type: str,
    anatomical_pattern: str,
    prompt_version: str,
    model: str,
    quality_gate_version: str,
) -> dict[str, Any]:
    """Build a structured provenance dict (spec section 12.3 item 18)."""
    return {
        "extraction_run_id": str(extraction_run_id),
        "workflow_type": "molecular_circuit_extraction_v2",
        "pack_id": pack_id,
        "candidate_id": circuit_id,
        "circuit_id": circuit_id,
        "canonical_key": canonical_key,
        "step_order": step_order,
        "edge_id": edge_id,
        "source_connection_record_id": edge_id,
        "source_region_record_id": source_region_id,
        "target_region_record_id": target_region_id,
        "functional_modules": functional_modules,
        "topology_type": topology_type,
        "anatomical_pattern": anatomical_pattern,
        "graph_algorithm": "molecular_graph_engine_v2",
        "prompt_version": prompt_version,
        "model": model,
        "quality_gate_version": quality_gate_version,
        "raw_response_reference": f"run:{extraction_run_id}/circuit:{canonical_key}",
        "created_by": f"molecular_circuit_extraction:{extraction_run_id}",
        "created_at": datetime.now(timezone.utc).isoformat(),
    }


def _is_provenance_complete(provenance: dict[str, Any]) -> bool:
    """Check that all 20 required provenance fields are present and non-null."""
    required = [
        "extraction_run_id", "workflow_type", "pack_id", "candidate_id",
        "circuit_id", "canonical_key", "step_order", "edge_id",
        "source_connection_record_id", "source_region_record_id",
        "target_region_record_id", "functional_modules", "topology_type",
        "anatomical_pattern", "graph_algorithm", "prompt_version", "model",
        "quality_gate_version", "raw_response_reference", "created_by",
    ]
    for field in required:
        if field not in provenance or provenance[field] is None:
            return False
    return True


# ---------------------------------------------------------------------------
# Review-status derivation (spec section 12.3 rule 13)
# ---------------------------------------------------------------------------


def _derive_review_status(confidence_level: str | None) -> str:
    """Map confidence level to ``MirrorReviewStatus``.

    - ``high`` -> ``pending`` (ready for human review).
    - ``medium`` / ``low`` -> ``needs_revision`` (needs closer look).
    - ``unknown`` / ``None`` -> ``needs_revision`` (conservative default).
    """
    if confidence_level and confidence_level.lower() == "high":
        return MirrorReviewStatus.pending
    return MirrorReviewStatus.needs_revision
