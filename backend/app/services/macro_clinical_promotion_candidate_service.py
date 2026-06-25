"""Macro clinical promotion candidate source (Step 10.6.6).

Candidate list/preview only — does NOT write formal macro_clinical tables.
"""

from __future__ import annotations

import uuid
from typing import Any

from sqlalchemy import func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.mirror_macro_clinical import MirrorCircuitFunction
from app.schemas.macro_clinical_promotion_candidate import (
    CircuitFunctionPromotionCandidateItem,
    CircuitFunctionPromotionCandidateListResponse,
    CircuitFunctionPromotionPreviewResponse,
    CircuitFunctionPromotionAttemptResponse,
    PromotionCandidateSourceInfo,
    PromotionReadiness,
)
from app.schemas.mirror_kg import MirrorPromotionStatus, MirrorReviewStatus
from app.services import mirror_macro_clinical_service

CIRCUIT_FUNCTION_SOURCE = PromotionCandidateSourceInfo(
    target_type="circuit_function",
    source_table="mirror_circuit_functions",
    formal_table="macro_clinical.circuit_function",
    formal_schema="macro_clinical",
    model_name="MirrorCircuitFunction",
)

PROMOTION_SOURCE_REGISTRY: dict[str, PromotionCandidateSourceInfo] = {
    "circuit_function": CIRCUIT_FUNCTION_SOURCE,
}

REQUIRED_FORMAL_FIELDS = (
    "circuit_id",
    "function_term_en",
    "function_term_cn",
    "status",
)

LOW_CONFIDENCE_THRESHOLD = 0.7
LOW_EVIDENCE_LEVELS = frozenset({"low", "insufficient"})


class CircuitFunctionPromotionCandidateNotFoundError(Exception):
    def __init__(self, source_id: uuid.UUID):
        self.source_id = source_id
        super().__init__(f"mirror_circuit_function not found: {source_id}")


class ReviewRequiredForPromotionError(Exception):
    code = "REVIEW_REQUIRED"


class FormalCircuitFunctionTableNotInitializedError(Exception):
    code = "FORMAL_CIRCUIT_FUNCTION_TABLE_NOT_INITIALIZED"


class CircuitFunctionActualPromotionDisabledError(Exception):
    code = "CIRCUIT_FUNCTION_PROMOTION_NOT_ENABLED"


def _is_blank(value: Any) -> bool:
    if value is None:
        return True
    if isinstance(value, str) and not value.strip():
        return True
    return False


def _missing_required_fields(obj: MirrorCircuitFunction) -> list[str]:
    missing: list[str] = []
    if not obj.circuit_id:
        missing.append("circuit_id")
    if _is_blank(obj.function_term_en) and _is_blank(obj.function_term_cn):
        missing.append("function_term_en")
        missing.append("function_term_cn")
    status_val = (obj.status or "").strip() if obj.status else ""
    if not status_val:
        missing.append("status")
    return missing


def assess_circuit_function_readiness(
    obj: MirrorCircuitFunction,
    *,
    formal_table_available: bool | None = None,
    for_actual_promote: bool = False,
) -> tuple[PromotionReadiness, list[str], list[str]]:
    """Return readiness, blocking_reasons, warnings."""
    blocking: list[str] = []
    warnings: list[str] = []
    missing = _missing_required_fields(obj)

    if not obj.circuit_id:
        blocking.append("circuit_id is required")
    if _is_blank(obj.function_term_en) and _is_blank(obj.function_term_cn):
        blocking.append("function_term_en or function_term_cn is required")
    if (obj.validation_status or "").lower() == "invalid":
        blocking.append("validation_status is invalid")
    if obj.promotion_status == MirrorPromotionStatus.promoted:
        blocking.append("already promoted")
    if (obj.status or "active").lower() not in {"active", ""} and obj.status:
        blocking.append(f"status must be active (current: {obj.status})")

    if blocking or missing:
        return "blocked", blocking, warnings

    if obj.review_status in {MirrorReviewStatus.pending, "pending"}:
        warnings.append("review_status is pending — manual review required before promotion")
        return "needs_review", [], warnings

    if obj.review_status not in {MirrorReviewStatus.approved, "approved", "reviewed"}:
        warnings.append(f"review_status={obj.review_status} — awaiting approval")
        return "needs_review", [], warnings

    score = obj.confidence_score if obj.confidence_score is not None else obj.confidence
    if score is not None and float(score) < LOW_CONFIDENCE_THRESHOLD:
        warnings.append(f"confidence_score {score} below {LOW_CONFIDENCE_THRESHOLD}")
        return "needs_review", [], warnings

    if (obj.evidence_level or "").lower() in LOW_EVIDENCE_LEVELS:
        warnings.append(f"evidence_level={obj.evidence_level}")
        return "needs_review", [], warnings

    if _is_blank(obj.function_term_cn) and not _is_blank(obj.function_term_en):
        warnings.append("function_term_cn missing")
        return "needs_review", [], warnings

    if _is_blank(obj.function_domain):
        warnings.append("function_domain missing")
        return "needs_review", [], warnings

    if _is_blank(obj.function_role):
        warnings.append("function_role missing")
        return "needs_review", [], warnings

    if for_actual_promote:
        if formal_table_available is False:
            blocking.append("formal macro_clinical.circuit_function table is not initialized")
            return "blocked", blocking, warnings
        blocking.append("actual promotion is not enabled in this release — preview only")
        return "blocked", blocking, warnings

    if obj.review_status == MirrorReviewStatus.approved and not missing:
        return "ready", [], warnings

    return "needs_review", [], warnings


def build_formal_payload_preview(obj: MirrorCircuitFunction) -> dict[str, Any]:
    return {
        "circuit_id": str(obj.circuit_id),
        "function_term_en": obj.function_term_en,
        "function_term_cn": obj.function_term_cn,
        "function_domain": obj.function_domain,
        "function_role": obj.function_role,
        "effect_type": obj.effect_type,
        "confidence_score": float(obj.confidence_score)
        if obj.confidence_score is not None
        else (float(obj.confidence) if obj.confidence is not None else None),
        "evidence_level": obj.evidence_level,
        "description": obj.description,
        "remark": obj.remark,
        "attributes": obj.attributes or {},
        "source_db": obj.source_db,
        "status": obj.status or "active",
    }


def _to_candidate_item(obj: MirrorCircuitFunction) -> CircuitFunctionPromotionCandidateItem:
    readiness, _, warnings = assess_circuit_function_readiness(obj)
    return CircuitFunctionPromotionCandidateItem(
        id=obj.id,
        circuit_id=obj.circuit_id,
        function_term_en=obj.function_term_en,
        function_term_cn=obj.function_term_cn,
        function_domain=obj.function_domain,
        function_role=obj.function_role,
        effect_type=obj.effect_type,
        confidence_score=float(obj.confidence_score)
        if obj.confidence_score is not None
        else (float(obj.confidence) if obj.confidence is not None else None),
        evidence_level=obj.evidence_level,
        review_status=obj.review_status,
        promotion_status=obj.promotion_status,
        validation_status=obj.validation_status,
        status=obj.status,
        readiness=readiness,
        missing_required_fields=_missing_required_fields(obj),
        warnings=warnings,
    )


async def list_circuit_function_promotion_candidates(
    session: AsyncSession,
    *,
    circuit_id: uuid.UUID | None = None,
    resource_id: uuid.UUID | None = None,
    batch_id: uuid.UUID | None = None,
    review_status: str | None = None,
    promotion_status: str | None = None,
    limit: int = 50,
    offset: int = 0,
) -> CircuitFunctionPromotionCandidateListResponse:
    try:
        await mirror_macro_clinical_service.list_mirror_circuit_functions(session, limit=1, offset=0)
    except mirror_macro_clinical_service.MirrorCircuitFunctionsNotInitializedError as exc:
        raise exc

    base = select(MirrorCircuitFunction)
    if circuit_id:
        base = base.where(MirrorCircuitFunction.circuit_id == circuit_id)
    if resource_id:
        base = base.where(MirrorCircuitFunction.resource_id == resource_id)
    if batch_id:
        base = base.where(MirrorCircuitFunction.batch_id == batch_id)
    if review_status:
        base = base.where(MirrorCircuitFunction.review_status == review_status)
    if promotion_status:
        base = base.where(MirrorCircuitFunction.promotion_status == promotion_status)
    else:
        base = base.where(
            MirrorCircuitFunction.promotion_status.in_(
                [MirrorPromotionStatus.not_promoted, MirrorPromotionStatus.failed]
            )
        )

    base = base.where(
        or_(
            MirrorCircuitFunction.status.is_(None),
            MirrorCircuitFunction.status == "active",
        )
    ).where(
        or_(
            MirrorCircuitFunction.validation_status.is_(None),
            func.lower(MirrorCircuitFunction.validation_status) != "invalid",
        )
    )

    count_stmt = select(func.count()).select_from(base.subquery())
    total = int((await session.execute(count_stmt)).scalar_one() or 0)

    stmt = base.order_by(MirrorCircuitFunction.created_at.desc()).limit(limit).offset(offset)
    rows = list((await session.execute(stmt)).scalars().all())

    return CircuitFunctionPromotionCandidateListResponse(
        source=CIRCUIT_FUNCTION_SOURCE,
        items=[_to_candidate_item(row) for row in rows],
        total=total,
        limit=limit,
        offset=offset,
    )


async def preview_circuit_function_promotion_candidate(
    session: AsyncSession,
    source_id: uuid.UUID,
) -> CircuitFunctionPromotionPreviewResponse:
    try:
        await mirror_macro_clinical_service.list_mirror_circuit_functions(session, limit=1, offset=0)
    except mirror_macro_clinical_service.MirrorCircuitFunctionsNotInitializedError as exc:
        raise exc

    obj = await session.get(MirrorCircuitFunction, source_id)
    if obj is None:
        raise CircuitFunctionPromotionCandidateNotFoundError(source_id)

    formal_available = await check_formal_circuit_function_table_available(session)
    readiness, blocking, warnings = assess_circuit_function_readiness(
        obj,
        formal_table_available=formal_available,
    )
    missing = _missing_required_fields(obj)

    return CircuitFunctionPromotionPreviewResponse(
        source_id=obj.id,
        formal_payload_preview=build_formal_payload_preview(obj),
        readiness=readiness,
        blocking_reasons=blocking,
        warnings=warnings,
        missing_required_fields=missing,
        review_status=obj.review_status,
        promotion_status=obj.promotion_status,
        actual_promotion_allowed=False,
    )


async def check_formal_circuit_function_table_available(session: AsyncSession) -> bool:
    try:
        from sqlalchemy import text

        await session.execute(text("SELECT 1 FROM final_circuit_functions LIMIT 0"))
        return True
    except Exception:
        return False


async def attempt_circuit_function_promotion(
    session: AsyncSession,
    source_id: uuid.UUID,
) -> CircuitFunctionPromotionAttemptResponse:
    """Gate actual promotion — preview/list only in Step 10.6.6."""
    preview = await preview_circuit_function_promotion_candidate(session, source_id)

    if preview.review_status in {MirrorReviewStatus.pending, "pending"}:
        raise ReviewRequiredForPromotionError()

    formal_available = await check_formal_circuit_function_table_available(session)
    if not formal_available:
        raise FormalCircuitFunctionTableNotInitializedError()

    raise CircuitFunctionActualPromotionDisabledError()
