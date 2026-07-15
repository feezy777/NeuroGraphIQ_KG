"""Rule Validation business logic — deterministic checks over candidate_brain_regions.

Boundaries (guide §18.7 / §5.2 / §25):
  - Reads candidate_brain_regions; writes validation side ONLY
    (rule_validation_runs + candidate_rule_validation_results).
  - Does NOT call LLM/Agent, do human review, write review_decision, promote,
    or write final_* / kg_*. Does NOT auto-merge same-name regions (duplicates are
    flagged as warnings only).
  - Advances candidate_created -> rule_validating -> rule_passed / rule_failed via the
    Candidate state machine. Only candidates in candidate_created are processed; others
    are skipped (keeps re-runs idempotent and transitions legal).
  - Does NOT change Import Batch status; records import_batch_events only.
"""

from __future__ import annotations

import logging
import uuid
from datetime import datetime, timezone
from typing import Any

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.candidate import CandidateBrainRegion
from app.models.resource import AtlasResource
from app.models.rule_validation import CandidateRuleValidationResult, RuleValidationRun
from app.schemas.candidate import CandidateStatus, validate_candidate_transition
from app.schemas.import_batch import BatchEventType
from app.schemas.rule_validation import (
    VALID_LATERALITY,
    CandidateRuleStatus,
    RuleSeverity,
    ValidationScope,
)
from app.services import import_batch_service

logger = logging.getLogger(__name__)

VALIDATOR_KEY = "aal3_candidate_rules"
VALIDATOR_VERSION = "v1"


class NoCandidateForValidationError(Exception):
    pass


class CandidateNotFoundError(Exception):
    pass


class ValidationScopeError(Exception):
    pass


class RuleValidationRunNotFoundError(Exception):
    pass


class DuplicateRuleValidationError(Exception):
    def __init__(self, batch_id: uuid.UUID, existing_run_id: uuid.UUID):
        self.batch_id = batch_id
        self.existing_run_id = existing_run_id
        super().__init__(str(existing_run_id))


def _log_action(
    *,
    action: str,
    result: str,
    batch_id: uuid.UUID | None = None,
    validation_run_id: uuid.UUID | None = None,
    error: str | None = None,
) -> None:
    logger.info(
        "event_type=rule_validation action=%s result=%s batch_id=%s validation_run_id=%s error=%s",
        action,
        result,
        batch_id,
        validation_run_id,
        error,
    )


def _check(rule_id: str, check_type: str, severity: RuleSeverity, passed: bool, message: str) -> dict[str, Any]:
    return {
        "rule_id": rule_id,
        "check_type": check_type,
        "severity": severity.value,
        "passed": passed,
        "message": message,
    }


def evaluate_candidate(
    candidate: CandidateBrainRegion,
    *,
    duplicate_label_values: frozenset[Any] = frozenset(),
    duplicate_name_keys: frozenset[Any] = frozenset(),
) -> list[dict[str, Any]]:
    """Run the deterministic rule catalogue against one candidate.

    Pure function (no DB); returns one check dict per rule.
    """
    checks: list[dict[str, Any]] = []

    raw_name = (candidate.raw_name or "").strip()
    checks.append(
        _check(
            "raw_name_not_empty",
            "empty_name",
            RuleSeverity.error,
            bool(raw_name),
            "raw_name is present" if raw_name else "raw_name is empty",
        )
    )

    lat_ok = candidate.laterality in VALID_LATERALITY
    checks.append(
        _check(
            "laterality_valid",
            "laterality_validity",
            RuleSeverity.error,
            lat_ok,
            f"laterality '{candidate.laterality}' is valid"
            if lat_ok
            else f"laterality '{candidate.laterality}' is not a recognised value",
        )
    )

    gran_ok = bool((candidate.granularity_level or "").strip()) and bool(
        (candidate.granularity_family or "").strip()
    )
    checks.append(
        _check(
            "granularity_present",
            "granularity_coverage",
            RuleSeverity.error,
            gran_ok,
            "granularity_level and granularity_family present"
            if gran_ok
            else "granularity_level or granularity_family missing",
        )
    )

    std_ok = bool((candidate.std_name or "").strip())
    checks.append(
        _check(
            "std_name_present",
            "std_name_coverage",
            RuleSeverity.warning,
            std_ok,
            "std_name present" if std_ok else "std_name missing",
        )
    )

    lat_known = candidate.laterality != "unknown"
    checks.append(
        _check(
            "laterality_known",
            "laterality_coverage",
            RuleSeverity.warning,
            lat_known,
            f"laterality resolved to {candidate.laterality}"
            if lat_known
            else "laterality is unknown",
        )
    )

    source_ok = bool((candidate.source_label_id or "").strip()) or candidate.label_value is not None
    checks.append(
        _check(
            "source_id_present",
            "source_id_coverage",
            RuleSeverity.warning,
            source_ok,
            "source_label_id or label_value present"
            if source_ok
            else "no source_label_id and no label_value",
        )
    )

    dup_label = candidate.label_value is not None and candidate.label_value in duplicate_label_values
    checks.append(
        _check(
            "unique_label_value_in_run",
            "duplicate_label_value",
            RuleSeverity.warning,
            not dup_label,
            f"label_value {candidate.label_value} duplicated in run (not merged)"
            if dup_label
            else "label_value is unique within run",
        )
    )

    name_key = _name_laterality_key(candidate)
    dup_name = name_key is not None and name_key in duplicate_name_keys
    checks.append(
        _check(
            "unique_name_laterality_in_run",
            "duplicate_name_laterality",
            RuleSeverity.warning,
            not dup_name,
            "region name + laterality duplicated in run (not merged)"
            if dup_name
            else "region name + laterality is unique within run",
        )
    )

    return checks


def _name_laterality_key(candidate: CandidateBrainRegion) -> tuple[str, str] | None:
    base = (candidate.region_base_name or candidate.raw_name or "").strip().lower()
    if not base:
        return None
    return (base, candidate.laterality)


def summarize_checks(checks: list[dict[str, Any]]) -> tuple[str, int, int, int]:
    """Return (overall_status, error_count, warning_count, info_count)."""
    error_count = sum(1 for c in checks if not c["passed"] and c["severity"] == RuleSeverity.error.value)
    warning_count = sum(
        1 for c in checks if not c["passed"] and c["severity"] == RuleSeverity.warning.value
    )
    info_count = sum(1 for c in checks if not c["passed"] and c["severity"] == RuleSeverity.info.value)
    overall = (
        CandidateRuleStatus.failed.value if error_count > 0 else CandidateRuleStatus.passed.value
    )
    return overall, error_count, warning_count, info_count


def _duplicates(candidates: list[CandidateBrainRegion]) -> tuple[frozenset[Any], frozenset[Any]]:
    label_seen: dict[Any, int] = {}
    name_seen: dict[Any, int] = {}
    for c in candidates:
        if c.label_value is not None:
            label_seen[c.label_value] = label_seen.get(c.label_value, 0) + 1
        key = _name_laterality_key(c)
        if key is not None:
            name_seen[key] = name_seen.get(key, 0) + 1
    dup_labels = frozenset(v for v, n in label_seen.items() if n > 1)
    dup_names = frozenset(k for k, n in name_seen.items() if n > 1)
    return dup_labels, dup_names


async def _select_candidates(
    session: AsyncSession,
    *,
    scope: ValidationScope,
    candidate_id: uuid.UUID | None,
    generation_run_id: uuid.UUID | None,
    batch_id: uuid.UUID | None,
    parse_run_id: uuid.UUID | None,
) -> list[CandidateBrainRegion]:
    stmt = select(CandidateBrainRegion)
    if scope == ValidationScope.candidate:
        stmt = stmt.where(CandidateBrainRegion.id == candidate_id)
    elif scope == ValidationScope.generation_run:
        stmt = stmt.where(CandidateBrainRegion.generation_run_id == generation_run_id)
    elif scope == ValidationScope.batch:
        stmt = stmt.where(CandidateBrainRegion.batch_id == batch_id)
    elif scope == ValidationScope.parse_run:
        stmt = stmt.where(CandidateBrainRegion.parse_run_id == parse_run_id)
    stmt = stmt.order_by(CandidateBrainRegion.row_index)
    return list((await session.execute(stmt)).scalars().all())


def _resolve_scope(
    *,
    candidate_id: uuid.UUID | None,
    generation_run_id: uuid.UUID | None,
    batch_id: uuid.UUID | None,
    parse_run_id: uuid.UUID | None,
) -> ValidationScope:
    provided = [
        (ValidationScope.candidate, candidate_id),
        (ValidationScope.generation_run, generation_run_id),
        (ValidationScope.batch, batch_id),
        (ValidationScope.parse_run, parse_run_id),
    ]
    chosen = [scope for scope, value in provided if value is not None]
    if len(chosen) != 1:
        raise ValidationScopeError(
            "exactly one of candidate_id / generation_run_id / batch_id / parse_run_id is required"
        )
    return chosen[0]


async def _count_validation_results_for_batch(
    session: AsyncSession, batch_id: uuid.UUID
) -> int:
    q = (
        select(func.count())
        .select_from(CandidateRuleValidationResult)
        .where(CandidateRuleValidationResult.batch_id == batch_id)
    )
    return int((await session.execute(q)).scalar_one())


async def _latest_succeeded_validation_run(
    session: AsyncSession, batch_id: uuid.UUID
) -> RuleValidationRun | None:
    q = (
        select(RuleValidationRun)
        .where(
            RuleValidationRun.batch_id == batch_id,
            RuleValidationRun.status == "succeeded",
        )
        .order_by(RuleValidationRun.finished_at.desc().nullslast(), RuleValidationRun.created_at.desc())
    )
    return (await session.execute(q)).scalars().first()


async def validate_candidates(
    session: AsyncSession,
    *,
    candidate_id: uuid.UUID | None = None,
    generation_run_id: uuid.UUID | None = None,
    batch_id: uuid.UUID | None = None,
    parse_run_id: uuid.UUID | None = None,
) -> RuleValidationRun:
    """Run deterministic rule validation over the selected candidate scope.

    Processes only candidates in candidate_created; others are skipped.
    Advances processed candidates to rule_passed / rule_failed.
    """
    scope = _resolve_scope(
        candidate_id=candidate_id,
        generation_run_id=generation_run_id,
        batch_id=batch_id,
        parse_run_id=parse_run_id,
    )

    all_candidates = await _select_candidates(
        session,
        scope=scope,
        candidate_id=candidate_id,
        generation_run_id=generation_run_id,
        batch_id=batch_id,
        parse_run_id=parse_run_id,
    )
    if not all_candidates:
        if scope == ValidationScope.candidate:
            raise CandidateNotFoundError(str(candidate_id))
        raise NoCandidateForValidationError("no candidates found for the requested scope")

    target_batch_id = all_candidates[0].batch_id
    resource_id = all_candidates[0].resource_id

    active_result_count = await _count_validation_results_for_batch(session, target_batch_id)
    if active_result_count > 0:
        existing = await _latest_succeeded_validation_run(session, target_batch_id)
        if existing is not None:
            _log_action(
                action="rule_validation",
                result="duplicate_rejected",
                batch_id=target_batch_id,
                validation_run_id=existing.id,
            )
            raise DuplicateRuleValidationError(target_batch_id, existing.id)

    if active_result_count == 0:
        for candidate in all_candidates:
            if candidate.candidate_status != CandidateStatus.candidate_created.value:
                candidate.candidate_status = CandidateStatus.candidate_created.value

    eligible = [c for c in all_candidates if c.candidate_status == CandidateStatus.candidate_created.value]
    skipped_count = len(all_candidates) - len(eligible)

    now = datetime.now(timezone.utc)
    run = RuleValidationRun(
        scope=scope.value,
        batch_id=target_batch_id,
        resource_id=resource_id,
        generation_run_id=generation_run_id,
        parse_run_id=parse_run_id,
        target_candidate_id=candidate_id,
        validator_key=VALIDATOR_KEY,
        validator_version=VALIDATOR_VERSION,
        status="running",
        skipped_count=skipped_count,
        started_at=now,
    )
    session.add(run)
    await session.flush()

    await import_batch_service.record_batch_event(
        session,
        target_batch_id,
        BatchEventType.rule_validation_started.value,
        message=f"rule validation started (scope={scope.value})",
        payload_json={
            "validation_run_id": str(run.id),
            "scope": scope.value,
            "candidate_count": len(eligible),
            "skipped_count": skipped_count,
        },
    )
    _log_action(
        action="rule_validation_started",
        result="success",
        batch_id=target_batch_id,
        validation_run_id=run.id,
    )

    try:
        dup_labels, dup_names = _duplicates(eligible)
        passed_count = 0
        failed_count = 0
        warning_total = 0

        for candidate in eligible:
            checks = evaluate_candidate(
                candidate,
                duplicate_label_values=dup_labels,
                duplicate_name_keys=dup_names,
            )
            overall, error_count, warning_count, info_count = summarize_checks(checks)

            validate_candidate_transition(
                candidate.candidate_status, CandidateStatus.rule_validating
            )
            candidate.candidate_status = CandidateStatus.rule_validating.value
            target_status = (
                CandidateStatus.rule_passed
                if overall == CandidateRuleStatus.passed.value
                else CandidateStatus.rule_failed
            )
            validate_candidate_transition(candidate.candidate_status, target_status)
            candidate.candidate_status = target_status.value

            session.add(
                CandidateRuleValidationResult(
                    validation_run_id=run.id,
                    candidate_id=candidate.id,
                    batch_id=candidate.batch_id,
                    resource_id=candidate.resource_id,
                    generation_run_id=candidate.generation_run_id,
                    parse_run_id=candidate.parse_run_id,
                    overall_status=overall,
                    error_count=error_count,
                    warning_count=warning_count,
                    info_count=info_count,
                    checks=checks,
                )
            )

            if overall == CandidateRuleStatus.passed.value:
                passed_count += 1
            else:
                failed_count += 1
            if warning_count > 0:
                warning_total += 1

        run.status = "succeeded"
        run.candidate_count = len(eligible)
        run.passed_count = passed_count
        run.failed_count = failed_count
        run.warning_count = warning_total
        run.finished_at = datetime.now(timezone.utc)

        await import_batch_service.record_batch_event(
            session,
            target_batch_id,
            BatchEventType.rule_validation_succeeded.value,
            message=(
                f"rule validation succeeded: passed={passed_count} "
                f"failed={failed_count} skipped={skipped_count}"
            ),
            payload_json={
                "validation_run_id": str(run.id),
                "candidate_count": len(eligible),
                "passed_count": passed_count,
                "failed_count": failed_count,
                "warning_count": warning_total,
                "skipped_count": skipped_count,
            },
        )

        await session.commit()
        await session.refresh(run)
        _log_action(
            action="rule_validation_succeeded",
            result="success",
            batch_id=target_batch_id,
            validation_run_id=run.id,
        )
        return run

    except Exception as exc:
        await session.rollback()
        _log_action(
            action="rule_validation_failed",
            result="error",
            batch_id=target_batch_id,
            error=str(exc),
        )
        try:
            failed_run = RuleValidationRun(
                scope=scope.value,
                batch_id=target_batch_id,
                resource_id=resource_id,
                generation_run_id=generation_run_id,
                parse_run_id=parse_run_id,
                target_candidate_id=candidate_id,
                validator_key=VALIDATOR_KEY,
                validator_version=VALIDATOR_VERSION,
                status="failed",
                skipped_count=skipped_count,
                error_message=str(exc),
                started_at=now,
                finished_at=datetime.now(timezone.utc),
            )
            session.add(failed_run)
            await session.flush()
            await import_batch_service.record_batch_event(
                session,
                target_batch_id,
                BatchEventType.rule_validation_failed.value,
                message=f"rule validation failed: {exc}",
                payload_json={"error": str(exc), "validation_run_id": str(failed_run.id)},
            )
            await session.commit()
        except Exception as inner:
            await session.rollback()
            _log_action(
                action="rule_validation_failure_record",
                result="error",
                batch_id=target_batch_id,
                error=str(inner),
            )
        raise


async def get_validation_run(
    session: AsyncSession, validation_run_id: uuid.UUID
) -> RuleValidationRun:
    row = await session.get(RuleValidationRun, validation_run_id)
    if row is None:
        raise RuleValidationRunNotFoundError(str(validation_run_id))
    return row


async def list_validation_runs(
    session: AsyncSession,
    *,
    batch_id: uuid.UUID | None = None,
    resource_id: uuid.UUID | None = None,
    status: str | None = None,
    granularity_level: str | None = None,
    limit: int = 50,
    offset: int = 0,
) -> tuple[list[RuleValidationRun], int]:
    base = select(RuleValidationRun)
    count_q = select(func.count()).select_from(RuleValidationRun)
    if batch_id:
        base = base.where(RuleValidationRun.batch_id == batch_id)
        count_q = count_q.where(RuleValidationRun.batch_id == batch_id)
    if resource_id:
        base = base.where(RuleValidationRun.resource_id == resource_id)
        count_q = count_q.where(RuleValidationRun.resource_id == resource_id)
    if status:
        base = base.where(RuleValidationRun.status == status)
        count_q = count_q.where(RuleValidationRun.status == status)
    if granularity_level:
        base = base.join(AtlasResource, RuleValidationRun.resource_id == AtlasResource.id).where(
            AtlasResource.granularity_level == granularity_level
        )
        count_q = count_q.join(
            AtlasResource, RuleValidationRun.resource_id == AtlasResource.id
        ).where(AtlasResource.granularity_level == granularity_level)

    total = int((await session.execute(count_q)).scalar_one())
    rows = (
        await session.execute(
            base.order_by(RuleValidationRun.created_at.desc()).limit(limit).offset(offset)
        )
    ).scalars().all()
    return list(rows), total


async def list_run_results(
    session: AsyncSession,
    validation_run_id: uuid.UUID,
    *,
    overall_status: str | None = None,
    limit: int = 50,
    offset: int = 0,
) -> tuple[list[CandidateRuleValidationResult], int]:
    base = select(CandidateRuleValidationResult).where(
        CandidateRuleValidationResult.validation_run_id == validation_run_id
    )
    count_q = (
        select(func.count())
        .select_from(CandidateRuleValidationResult)
        .where(CandidateRuleValidationResult.validation_run_id == validation_run_id)
    )
    if overall_status:
        base = base.where(CandidateRuleValidationResult.overall_status == overall_status)
        count_q = count_q.where(CandidateRuleValidationResult.overall_status == overall_status)

    total = int((await session.execute(count_q)).scalar_one())
    rows = (
        await session.execute(base.order_by(CandidateRuleValidationResult.created_at).limit(limit).offset(offset))
    ).scalars().all()
    return list(rows), total


async def list_candidate_results(
    session: AsyncSession,
    candidate_id: uuid.UUID,
    *,
    limit: int = 50,
    offset: int = 0,
) -> tuple[list[CandidateRuleValidationResult], int]:
    base = select(CandidateRuleValidationResult).where(
        CandidateRuleValidationResult.candidate_id == candidate_id
    )
    count_q = (
        select(func.count())
        .select_from(CandidateRuleValidationResult)
        .where(CandidateRuleValidationResult.candidate_id == candidate_id)
    )
    total = int((await session.execute(count_q)).scalar_one())
    rows = (
        await session.execute(
            base.order_by(CandidateRuleValidationResult.created_at.desc()).limit(limit).offset(offset)
        )
    ).scalars().all()
    return list(rows), total
