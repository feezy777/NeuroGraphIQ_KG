"""Mirror KG circuit-projection cross validation — deterministic, no LLM (Step 8.11).

Compares circuit_to_projection vs projection_to_circuit memberships.
Writes cross validation runs/results; optionally updates membership.verification_status.
Does NOT write final_* / kg_*; does NOT modify review_status / promotion_status.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.mirror_kg import MirrorRegionCircuit, MirrorRegionConnection
from app.models.mirror_cross_validation import (
    MirrorCircuitProjectionCrossValidationResult,
    MirrorCircuitProjectionCrossValidationRun,
)
from app.models.mirror_macro_clinical import MirrorCircuitProjectionMembership, MirrorCircuitStep
from app.schemas.mirror_cross_validation import (
    CircuitProjectionCrossValidationStatus,
    CircuitProjectionSupportLevel,
    CrossValidationRunStatus,
)
from app.schemas.mirror_macro_clinical import (
    MirrorMembershipSourceMethod,
    MirrorMembershipVerificationStatus,
)

MAX_CROSS_VALIDATION_LIMIT = 5000
DEFAULT_CROSS_VALIDATION_LIMIT = 1000
PREVIEW_LIMIT = 200

FORWARD_SOURCE_METHODS = frozenset({MirrorMembershipSourceMethod.circuit_to_projection})
REVERSE_SOURCE_METHODS = frozenset({MirrorMembershipSourceMethod.projection_to_circuit})
FORWARD_VERIFICATION = frozenset({MirrorMembershipVerificationStatus.circuit_supported})
REVERSE_VERIFICATION = frozenset({MirrorMembershipVerificationStatus.projection_supported})


class LimitExceededError(ValueError):
    pass


@dataclass
class CrossValidationScope:
    resource_id: uuid.UUID | None = None
    batch_id: uuid.UUID | None = None
    source_atlas: str | None = None
    source_version: str | None = None
    granularity_level: str | None = None
    granularity_family: str | None = None
    circuit_ids: list[uuid.UUID] | None = None
    projection_ids: list[uuid.UUID] | None = None
    membership_ids: list[uuid.UUID] | None = None
    include_unverified: bool = True
    include_conflicts: bool = True


@dataclass
class ComparedPair:
    circuit_id: uuid.UUID
    projection_id: uuid.UUID
    forward: MirrorCircuitProjectionMembership | None
    reverse: MirrorCircuitProjectionMembership | None
    validation_status: str
    support_level: str
    agreement_score: float | None
    source_step_agreement: bool | None
    target_step_agreement: bool | None
    direction_agreement: bool | None
    scope_agreement: bool | None
    conflict_reason: str | None
    details_json: dict[str, Any] = field(default_factory=dict)


@dataclass
class CrossValidationOutcome:
    run_id: uuid.UUID | None
    dry_run: bool
    apply_updates: bool
    membership_count: int
    circuit_supported_count: int
    projection_supported_count: int
    bidirectionally_supported_count: int
    conflict_count: int
    insufficient_evidence_count: int
    updated_membership_count: int
    results_preview: list[dict[str, Any]]
    warnings: list[str]


def _is_forward(m: MirrorCircuitProjectionMembership) -> bool:
    if m.source_method in FORWARD_SOURCE_METHODS:
        return True
    return m.verification_status in FORWARD_VERIFICATION


def _is_reverse(m: MirrorCircuitProjectionMembership) -> bool:
    if m.source_method in REVERSE_SOURCE_METHODS:
        return True
    return m.verification_status in REVERSE_VERIFICATION


def _scope_fields_match(
    a: MirrorCircuitProjectionMembership,
    b: MirrorCircuitProjectionMembership,
) -> bool:
    return (
        a.resource_id == b.resource_id
        and a.batch_id == b.batch_id
        and a.source_atlas == b.source_atlas
        and a.granularity_level == b.granularity_level
    )


def _check_direction_agreement(
    projection: MirrorRegionConnection | None,
    forward: MirrorCircuitProjectionMembership | None,
    reverse: MirrorCircuitProjectionMembership | None,
    source_step: MirrorCircuitStep | None,
    target_step: MirrorCircuitStep | None,
) -> bool | None:
    if projection is None:
        return None
    src_region = projection.source_region_candidate_id
    tgt_region = projection.target_region_candidate_id
    if not src_region or not tgt_region:
        return None
    if source_step is None or target_step is None:
        return None
    if source_step.region_candidate_id != src_region:
        return False
    if target_step.region_candidate_id != tgt_region:
        return False
    return True


def compute_agreement_score(
    *,
    has_forward: bool,
    has_reverse: bool,
    source_step_agreement: bool | None,
    target_step_agreement: bool | None,
    scope_agreement: bool | None,
    direction_agreement: bool | None,
    scope_mismatch: bool,
    entities_missing: bool,
) -> float | None:
    if entities_missing:
        return None
    score = 0.0
    if has_forward and has_reverse:
        score += 0.4
    score += 0.15  # circuit_id consistent within group
    score += 0.15  # projection_id consistent within group
    if source_step_agreement is True:
        score += 0.1
    if target_step_agreement is True:
        score += 0.1
    if scope_agreement is True:
        score += 0.1
    if direction_agreement is True:
        score += 0.1
    if scope_mismatch:
        return min(score, 0.3)
    return min(score, 1.0)


def compare_membership_pair(
    *,
    circuit: MirrorRegionCircuit | None,
    projection: MirrorRegionConnection | None,
    forward: MirrorCircuitProjectionMembership | None,
    reverse: MirrorCircuitProjectionMembership | None,
    source_step: MirrorCircuitStep | None,
    target_step: MirrorCircuitStep | None,
) -> ComparedPair:
    circuit_id = (forward or reverse).circuit_id  # type: ignore[union-attr]
    projection_id = (forward or reverse).projection_id  # type: ignore[union-attr]
    details: dict[str, Any] = {}

    if circuit is None or projection is None:
        return ComparedPair(
            circuit_id=circuit_id,
            projection_id=projection_id,
            forward=forward,
            reverse=reverse,
            validation_status=CircuitProjectionCrossValidationStatus.insufficient_evidence,
            support_level=CircuitProjectionSupportLevel.unknown,
            agreement_score=None,
            source_step_agreement=None,
            target_step_agreement=None,
            direction_agreement=None,
            scope_agreement=None,
            conflict_reason="MISSING_CIRCUIT_OR_PROJECTION" if circuit is None else "MISSING_PROJECTION",
            details_json={"circuit_exists": circuit is not None, "projection_exists": projection is not None},
        )

    if forward is None and reverse is None:
        return ComparedPair(
            circuit_id=circuit_id,
            projection_id=projection_id,
            forward=None,
            reverse=None,
            validation_status=CircuitProjectionCrossValidationStatus.insufficient_evidence,
            support_level=CircuitProjectionSupportLevel.unknown,
            agreement_score=None,
            source_step_agreement=None,
            target_step_agreement=None,
            direction_agreement=None,
            scope_agreement=None,
            conflict_reason="NO_MEMBERSHIPS",
            details_json={},
        )

    if forward is None:
        score = compute_agreement_score(
            has_forward=False,
            has_reverse=True,
            source_step_agreement=None,
            target_step_agreement=None,
            scope_agreement=None,
            direction_agreement=None,
            scope_mismatch=False,
            entities_missing=False,
        )
        return ComparedPair(
            circuit_id=circuit_id,
            projection_id=projection_id,
            forward=None,
            reverse=reverse,
            validation_status=CircuitProjectionCrossValidationStatus.projection_supported_only,
            support_level=CircuitProjectionSupportLevel.weak,
            agreement_score=score,
            source_step_agreement=None,
            target_step_agreement=None,
            direction_agreement=None,
            scope_agreement=None,
            conflict_reason=None,
            details_json={"note": "only projection_to_circuit membership present"},
        )

    if reverse is None:
        score = compute_agreement_score(
            has_forward=True,
            has_reverse=False,
            source_step_agreement=None,
            target_step_agreement=None,
            scope_agreement=None,
            direction_agreement=None,
            scope_mismatch=False,
            entities_missing=False,
        )
        return ComparedPair(
            circuit_id=circuit_id,
            projection_id=projection_id,
            forward=forward,
            reverse=None,
            validation_status=CircuitProjectionCrossValidationStatus.circuit_supported_only,
            support_level=CircuitProjectionSupportLevel.weak,
            agreement_score=score,
            source_step_agreement=None,
            target_step_agreement=None,
            direction_agreement=None,
            scope_agreement=None,
            conflict_reason=None,
            details_json={"note": "only circuit_to_projection membership present"},
        )

    scope_agreement = _scope_fields_match(forward, reverse)
    source_step_agreement: bool | None = None
    target_step_agreement: bool | None = None
    if forward.source_step_id is not None and reverse.source_step_id is not None:
        source_step_agreement = forward.source_step_id == reverse.source_step_id
    if forward.target_step_id is not None and reverse.target_step_id is not None:
        target_step_agreement = forward.target_step_id == reverse.target_step_id

    direction_agreement = _check_direction_agreement(
        projection, forward, reverse, source_step, target_step
    )

    scope_mismatch = not scope_agreement
    direction_conflict = direction_agreement is False

    if scope_mismatch:
        score = compute_agreement_score(
            has_forward=True,
            has_reverse=True,
            source_step_agreement=source_step_agreement,
            target_step_agreement=target_step_agreement,
            scope_agreement=False,
            direction_agreement=direction_agreement,
            scope_mismatch=True,
            entities_missing=False,
        )
        return ComparedPair(
            circuit_id=circuit_id,
            projection_id=projection_id,
            forward=forward,
            reverse=reverse,
            validation_status=CircuitProjectionCrossValidationStatus.conflict,
            support_level=CircuitProjectionSupportLevel.conflicting,
            agreement_score=score,
            source_step_agreement=source_step_agreement,
            target_step_agreement=target_step_agreement,
            direction_agreement=direction_agreement,
            scope_agreement=False,
            conflict_reason="SCOPE_MISMATCH",
            details_json={
                "forward_resource_id": str(forward.resource_id) if forward.resource_id else None,
                "reverse_resource_id": str(reverse.resource_id) if reverse.resource_id else None,
            },
        )

    if direction_conflict:
        score = compute_agreement_score(
            has_forward=True,
            has_reverse=True,
            source_step_agreement=source_step_agreement,
            target_step_agreement=target_step_agreement,
            scope_agreement=True,
            direction_agreement=False,
            scope_mismatch=False,
            entities_missing=False,
        )
        return ComparedPair(
            circuit_id=circuit_id,
            projection_id=projection_id,
            forward=forward,
            reverse=reverse,
            validation_status=CircuitProjectionCrossValidationStatus.conflict,
            support_level=CircuitProjectionSupportLevel.conflicting,
            agreement_score=score,
            source_step_agreement=source_step_agreement,
            target_step_agreement=target_step_agreement,
            direction_agreement=False,
            scope_agreement=True,
            conflict_reason="DIRECTION_STEP_CONFLICT",
            details_json={},
        )

    step_mismatch = (
        (source_step_agreement is False)
        or (target_step_agreement is False)
    )
    score = compute_agreement_score(
        has_forward=True,
        has_reverse=True,
        source_step_agreement=source_step_agreement,
        target_step_agreement=target_step_agreement,
        scope_agreement=True,
        direction_agreement=direction_agreement,
        scope_mismatch=False,
        entities_missing=False,
    )

    if step_mismatch:
        details["step_mismatch_warning"] = True
        support = CircuitProjectionSupportLevel.moderate
        if source_step_agreement is False and target_step_agreement is False:
            support = CircuitProjectionSupportLevel.weak
        return ComparedPair(
            circuit_id=circuit_id,
            projection_id=projection_id,
            forward=forward,
            reverse=reverse,
            validation_status=CircuitProjectionCrossValidationStatus.bidirectionally_supported,
            support_level=support,
            agreement_score=score,
            source_step_agreement=source_step_agreement,
            target_step_agreement=target_step_agreement,
            direction_agreement=direction_agreement,
            scope_agreement=True,
            conflict_reason="STEP_MISMATCH",
            details_json=details,
        )

    return ComparedPair(
        circuit_id=circuit_id,
        projection_id=projection_id,
        forward=forward,
        reverse=reverse,
        validation_status=CircuitProjectionCrossValidationStatus.bidirectionally_supported,
        support_level=CircuitProjectionSupportLevel.strong,
        agreement_score=score if score is not None else 1.0,
        source_step_agreement=source_step_agreement,
        target_step_agreement=target_step_agreement,
        direction_agreement=direction_agreement,
        scope_agreement=True,
        conflict_reason=None,
        details_json=details,
    )


def group_memberships_by_circuit_projection(
    memberships: list[MirrorCircuitProjectionMembership],
) -> dict[tuple[uuid.UUID, uuid.UUID], dict[str, MirrorCircuitProjectionMembership | None]]:
    groups: dict[tuple[uuid.UUID, uuid.UUID], dict[str, MirrorCircuitProjectionMembership | None]] = {}
    for m in memberships:
        key = (m.circuit_id, m.projection_id)
        if key not in groups:
            groups[key] = {"forward": None, "reverse": None}
        if _is_forward(m):
            if groups[key]["forward"] is None:
                groups[key]["forward"] = m
        elif _is_reverse(m):
            if groups[key]["reverse"] is None:
                groups[key]["reverse"] = m
        else:
            if groups[key]["forward"] is None:
                groups[key]["forward"] = m
    return groups


def _apply_scope_filters(stmt, scope: CrossValidationScope):
    if scope.resource_id:
        stmt = stmt.where(MirrorCircuitProjectionMembership.resource_id == scope.resource_id)
    if scope.batch_id:
        stmt = stmt.where(MirrorCircuitProjectionMembership.batch_id == scope.batch_id)
    if scope.source_atlas:
        stmt = stmt.where(MirrorCircuitProjectionMembership.source_atlas == scope.source_atlas)
    if scope.source_version:
        stmt = stmt.where(MirrorCircuitProjectionMembership.source_version == scope.source_version)
    if scope.granularity_level:
        stmt = stmt.where(MirrorCircuitProjectionMembership.granularity_level == scope.granularity_level)
    if scope.granularity_family:
        stmt = stmt.where(MirrorCircuitProjectionMembership.granularity_family == scope.granularity_family)
    if scope.circuit_ids:
        stmt = stmt.where(MirrorCircuitProjectionMembership.circuit_id.in_(scope.circuit_ids))
    if scope.projection_ids:
        stmt = stmt.where(MirrorCircuitProjectionMembership.projection_id.in_(scope.projection_ids))
    if scope.membership_ids:
        stmt = stmt.where(MirrorCircuitProjectionMembership.id.in_(scope.membership_ids))
    if not scope.include_unverified:
        stmt = stmt.where(
            MirrorCircuitProjectionMembership.verification_status.notin_(
                ["unverified", "unknown"]
            )
        )
    if not scope.include_conflicts:
        stmt = stmt.where(
            MirrorCircuitProjectionMembership.verification_status
            != MirrorMembershipVerificationStatus.model_conflict
        )
    return stmt


async def collect_memberships(
    session: AsyncSession,
    scope: CrossValidationScope,
    limit: int,
) -> list[MirrorCircuitProjectionMembership]:
    stmt = select(MirrorCircuitProjectionMembership).order_by(
        MirrorCircuitProjectionMembership.created_at.desc()
    )
    stmt = _apply_scope_filters(stmt, scope)
    stmt = stmt.limit(limit * 4)
    result = await session.execute(stmt)
    return list(result.scalars().all())


def _pair_to_preview(p: ComparedPair) -> dict[str, Any]:
    return {
        "circuit_id": p.circuit_id,
        "projection_id": p.projection_id,
        "circuit_to_projection_membership_id": p.forward.id if p.forward else None,
        "projection_to_circuit_membership_id": p.reverse.id if p.reverse else None,
        "validation_status": p.validation_status,
        "support_level": p.support_level,
        "agreement_score": float(p.agreement_score) if p.agreement_score is not None else None,
        "source_step_agreement": p.source_step_agreement,
        "target_step_agreement": p.target_step_agreement,
        "direction_agreement": p.direction_agreement,
        "scope_agreement": p.scope_agreement,
        "conflict_reason": p.conflict_reason,
        "details_json": p.details_json,
    }


async def apply_membership_verification_updates(
    session: AsyncSession,
    pairs: list[ComparedPair],
    *,
    apply_updates: bool,
    update_bidirectional: bool,
    update_conflicts: bool,
) -> int:
    if not apply_updates:
        return 0
    updated = 0
    for p in pairs:
        if p.validation_status == CircuitProjectionCrossValidationStatus.bidirectionally_supported:
            if not update_bidirectional:
                continue
            new_status = MirrorMembershipVerificationStatus.bidirectionally_supported
        elif p.validation_status == CircuitProjectionCrossValidationStatus.conflict:
            if not update_conflicts:
                continue
            new_status = MirrorMembershipVerificationStatus.model_conflict
        else:
            continue
        for m in (p.forward, p.reverse):
            if m is None:
                continue
            if m.verification_status != new_status:
                m.verification_status = new_status
                updated += 1
    if updated:
        await session.flush()
    return updated


async def persist_cross_validation_run_and_results(
    session: AsyncSession,
    *,
    scope: CrossValidationScope,
    scope_json: dict[str, Any],
    dry_run: bool,
    apply_updates: bool,
    pairs: list[ComparedPair],
    counts: dict[str, int],
    updated_membership_count: int,
) -> uuid.UUID:
    now = datetime.now(timezone.utc)
    run = MirrorCircuitProjectionCrossValidationRun(
        scope_json=scope_json,
        resource_id=scope.resource_id,
        batch_id=scope.batch_id,
        source_atlas=scope.source_atlas,
        source_version=scope.source_version,
        granularity_level=scope.granularity_level,
        granularity_family=scope.granularity_family,
        status=CrossValidationRunStatus.succeeded,
        membership_count=counts["membership_count"],
        circuit_supported_count=counts["circuit_supported_count"],
        projection_supported_count=counts["projection_supported_count"],
        bidirectionally_supported_count=counts["bidirectionally_supported_count"],
        conflict_count=counts["conflict_count"],
        insufficient_evidence_count=counts["insufficient_evidence_count"],
        updated_membership_count=updated_membership_count,
        dry_run=dry_run,
        apply_updates=apply_updates,
        started_at=now,
        finished_at=now,
    )
    session.add(run)
    await session.flush()

    ref_membership = next((p.forward or p.reverse for p in pairs if p.forward or p.reverse), None)
    for p in pairs:
        row = MirrorCircuitProjectionCrossValidationResult(
            run_id=run.id,
            circuit_id=p.circuit_id,
            projection_id=p.projection_id,
            circuit_to_projection_membership_id=p.forward.id if p.forward else None,
            projection_to_circuit_membership_id=p.reverse.id if p.reverse else None,
            validation_status=p.validation_status,
            support_level=p.support_level,
            agreement_score=p.agreement_score,
            source_step_agreement=p.source_step_agreement,
            target_step_agreement=p.target_step_agreement,
            direction_agreement=p.direction_agreement,
            scope_agreement=p.scope_agreement,
            conflict_reason=p.conflict_reason,
            details_json=p.details_json,
            resource_id=ref_membership.resource_id if ref_membership else scope.resource_id,
            batch_id=ref_membership.batch_id if ref_membership else scope.batch_id,
            source_atlas=ref_membership.source_atlas if ref_membership else scope.source_atlas,
            granularity_level=ref_membership.granularity_level if ref_membership else scope.granularity_level,
            granularity_family=ref_membership.granularity_family if ref_membership else scope.granularity_family,
        )
        session.add(row)
    await session.flush()
    return run.id


async def run_circuit_projection_cross_validation(
    session: AsyncSession,
    *,
    scope: CrossValidationScope | None = None,
    dry_run: bool = True,
    apply_updates: bool = False,
    update_bidirectional: bool = True,
    update_conflicts: bool = False,
    limit: int = DEFAULT_CROSS_VALIDATION_LIMIT,
) -> CrossValidationOutcome:
    if limit > MAX_CROSS_VALIDATION_LIMIT:
        raise LimitExceededError(f"limit must be <= {MAX_CROSS_VALIDATION_LIMIT}")

    scope = scope or CrossValidationScope()
    warnings: list[str] = []

    if dry_run and apply_updates:
        apply_updates = False
        warnings.append("DRY_RUN_IGNORES_APPLY_UPDATES")

    memberships = await collect_memberships(session, scope, limit)
    groups = group_memberships_by_circuit_projection(memberships)

    group_keys = list(groups.keys())[:limit]
    pairs: list[ComparedPair] = []

    circuit_cache: dict[uuid.UUID, MirrorRegionCircuit | None] = {}
    projection_cache: dict[uuid.UUID, MirrorRegionConnection | None] = {}
    step_cache: dict[uuid.UUID, MirrorCircuitStep | None] = {}

    async def _get_circuit(cid: uuid.UUID) -> MirrorRegionCircuit | None:
        if cid not in circuit_cache:
            circuit_cache[cid] = await session.get(MirrorRegionCircuit, cid)
        return circuit_cache[cid]

    async def _get_projection(pid: uuid.UUID) -> MirrorRegionConnection | None:
        if pid not in projection_cache:
            projection_cache[pid] = await session.get(MirrorRegionConnection, pid)
        return projection_cache[pid]

    async def _get_step(sid: uuid.UUID | None) -> MirrorCircuitStep | None:
        if sid is None:
            return None
        if sid not in step_cache:
            step_cache[sid] = await session.get(MirrorCircuitStep, sid)
        return step_cache[sid]

    for circuit_id, projection_id in group_keys:
        g = groups[(circuit_id, projection_id)]
        forward = g["forward"]
        reverse = g["reverse"]
        circuit = await _get_circuit(circuit_id)
        projection = await _get_projection(projection_id)

        source_step = None
        target_step = None
        ref = forward or reverse
        if ref:
            source_step = await _get_step(ref.source_step_id)
            target_step = await _get_step(ref.target_step_id)

        if projection and (
            not projection.source_region_candidate_id or not projection.target_region_candidate_id
        ):
            warnings.append(f"PROJECTION_MISSING_REGIONS:{projection_id}")

        pair = compare_membership_pair(
            circuit=circuit,
            projection=projection,
            forward=forward,
            reverse=reverse,
            source_step=source_step,
            target_step=target_step,
        )
        pairs.append(pair)

    counts = {
        "membership_count": len(group_keys),
        "circuit_supported_count": sum(
            1 for p in pairs
            if p.validation_status == CircuitProjectionCrossValidationStatus.circuit_supported_only
        ),
        "projection_supported_count": sum(
            1 for p in pairs
            if p.validation_status == CircuitProjectionCrossValidationStatus.projection_supported_only
        ),
        "bidirectionally_supported_count": sum(
            1 for p in pairs
            if p.validation_status == CircuitProjectionCrossValidationStatus.bidirectionally_supported
        ),
        "conflict_count": sum(
            1 for p in pairs if p.validation_status == CircuitProjectionCrossValidationStatus.conflict
        ),
        "insufficient_evidence_count": sum(
            1 for p in pairs
            if p.validation_status == CircuitProjectionCrossValidationStatus.insufficient_evidence
        ),
    }

    updated_count = 0
    run_id: uuid.UUID | None = None

    if not dry_run:
        updated_count = await apply_membership_verification_updates(
            session,
            pairs,
            apply_updates=apply_updates,
            update_bidirectional=update_bidirectional,
            update_conflicts=update_conflicts,
        )
        scope_json = {
            "resource_id": str(scope.resource_id) if scope.resource_id else None,
            "batch_id": str(scope.batch_id) if scope.batch_id else None,
            "source_atlas": scope.source_atlas,
            "granularity_level": scope.granularity_level,
            "include_unverified": scope.include_unverified,
            "include_conflicts": scope.include_conflicts,
            "limit": limit,
            "update_bidirectional": update_bidirectional,
            "update_conflicts": update_conflicts,
        }
        run_id = await persist_cross_validation_run_and_results(
            session,
            scope=scope,
            scope_json=scope_json,
            dry_run=dry_run,
            apply_updates=apply_updates,
            pairs=pairs,
            counts=counts,
            updated_membership_count=updated_count,
        )
        await session.commit()
    else:
        updated_count = 0

    preview = [_pair_to_preview(p) for p in pairs[:PREVIEW_LIMIT]]

    return CrossValidationOutcome(
        run_id=run_id,
        dry_run=dry_run,
        apply_updates=apply_updates,
        membership_count=counts["membership_count"],
        circuit_supported_count=counts["circuit_supported_count"],
        projection_supported_count=counts["projection_supported_count"],
        bidirectionally_supported_count=counts["bidirectionally_supported_count"],
        conflict_count=counts["conflict_count"],
        insufficient_evidence_count=counts["insufficient_evidence_count"],
        updated_membership_count=updated_count,
        results_preview=preview,
        warnings=warnings,
    )


async def list_cross_validation_runs(
    session: AsyncSession,
    *,
    status: str | None = None,
    resource_id: uuid.UUID | None = None,
    batch_id: uuid.UUID | None = None,
    source_atlas: str | None = None,
    granularity_level: str | None = None,
    limit: int = 50,
    offset: int = 0,
) -> tuple[list[MirrorCircuitProjectionCrossValidationRun], int]:
    stmt = select(MirrorCircuitProjectionCrossValidationRun)
    count_stmt = select(func.count()).select_from(MirrorCircuitProjectionCrossValidationRun)
    if status:
        stmt = stmt.where(MirrorCircuitProjectionCrossValidationRun.status == status)
        count_stmt = count_stmt.where(MirrorCircuitProjectionCrossValidationRun.status == status)
    if resource_id:
        stmt = stmt.where(MirrorCircuitProjectionCrossValidationRun.resource_id == resource_id)
        count_stmt = count_stmt.where(MirrorCircuitProjectionCrossValidationRun.resource_id == resource_id)
    if batch_id:
        stmt = stmt.where(MirrorCircuitProjectionCrossValidationRun.batch_id == batch_id)
        count_stmt = count_stmt.where(MirrorCircuitProjectionCrossValidationRun.batch_id == batch_id)
    if source_atlas:
        stmt = stmt.where(MirrorCircuitProjectionCrossValidationRun.source_atlas == source_atlas)
        count_stmt = count_stmt.where(MirrorCircuitProjectionCrossValidationRun.source_atlas == source_atlas)
    if granularity_level:
        stmt = stmt.where(MirrorCircuitProjectionCrossValidationRun.granularity_level == granularity_level)
        count_stmt = count_stmt.where(
            MirrorCircuitProjectionCrossValidationRun.granularity_level == granularity_level
        )
    total = (await session.execute(count_stmt)).scalar_one()
    stmt = (
        stmt.order_by(MirrorCircuitProjectionCrossValidationRun.created_at.desc())
        .limit(limit)
        .offset(offset)
    )
    rows = list((await session.execute(stmt)).scalars().all())
    return rows, total


async def get_cross_validation_run(
    session: AsyncSession,
    run_id: uuid.UUID,
) -> MirrorCircuitProjectionCrossValidationRun | None:
    return await session.get(MirrorCircuitProjectionCrossValidationRun, run_id)


async def list_cross_validation_results(
    session: AsyncSession,
    *,
    run_id: uuid.UUID | None = None,
    circuit_id: uuid.UUID | None = None,
    projection_id: uuid.UUID | None = None,
    validation_status: str | None = None,
    support_level: str | None = None,
    resource_id: uuid.UUID | None = None,
    batch_id: uuid.UUID | None = None,
    source_atlas: str | None = None,
    granularity_level: str | None = None,
    limit: int = 50,
    offset: int = 0,
) -> tuple[list[MirrorCircuitProjectionCrossValidationResult], int]:
    stmt = select(MirrorCircuitProjectionCrossValidationResult)
    count_stmt = select(func.count()).select_from(MirrorCircuitProjectionCrossValidationResult)
    filters = [
        (run_id, MirrorCircuitProjectionCrossValidationResult.run_id),
        (circuit_id, MirrorCircuitProjectionCrossValidationResult.circuit_id),
        (projection_id, MirrorCircuitProjectionCrossValidationResult.projection_id),
        (validation_status, MirrorCircuitProjectionCrossValidationResult.validation_status),
        (support_level, MirrorCircuitProjectionCrossValidationResult.support_level),
        (resource_id, MirrorCircuitProjectionCrossValidationResult.resource_id),
        (batch_id, MirrorCircuitProjectionCrossValidationResult.batch_id),
        (source_atlas, MirrorCircuitProjectionCrossValidationResult.source_atlas),
        (granularity_level, MirrorCircuitProjectionCrossValidationResult.granularity_level),
    ]
    for val, col in filters:
        if val is not None:
            stmt = stmt.where(col == val)
            count_stmt = count_stmt.where(col == val)
    total = (await session.execute(count_stmt)).scalar_one()
    stmt = (
        stmt.order_by(MirrorCircuitProjectionCrossValidationResult.created_at.desc())
        .limit(limit)
        .offset(offset)
    )
    rows = list((await session.execute(stmt)).scalars().all())
    return rows, total
