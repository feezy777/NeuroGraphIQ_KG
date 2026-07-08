"""Circuit → Connection extraction tests (mock provider)."""

from __future__ import annotations

import asyncio
import uuid
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.models.candidate import CandidateBrainRegion
from app.schemas.llm_circuit_connection_extraction import (
    CircuitConnectionExtractionRequest,
    ExtractionMode,
)


def _candidate(**kwargs) -> CandidateBrainRegion:
    defaults = dict(
        id=uuid.uuid4(),
        batch_id=uuid.uuid4(),
        resource_id=uuid.uuid4(),
        generation_run_id=uuid.uuid4(),
        parse_run_id=uuid.uuid4(),
        source_atlas="Macro96",
        source_version="v1",
        raw_name="Test Region",
        en_name="left hippocampus",
        cn_name=None,
        laterality="left",
        granularity_level="macro",
        granularity_family="macro_clinical",
        candidate_status="rule_passed",
        raw_payload={},
        row_index=0,
    )
    defaults.update(kwargs)
    return CandidateBrainRegion(**defaults)


def test_region_match_exact_case_insensitive(monkeypatch):
    """match_region_name returns candidate ID for exact case-insensitive match."""
    from app.services.llm_circuit_connection_extraction_service import match_region_name

    candidate = _candidate(en_name="Left Hippocampus")
    session = AsyncMock()
    session.execute = AsyncMock(return_value=MagicMock(
        scalar_one_or_none=MagicMock(return_value=candidate)
    ))

    result = asyncio.run(match_region_name(session, "left hippocampus"))
    assert result == candidate.id


def test_region_match_returns_none_for_unmatched():
    """match_region_name returns None when no region matches."""
    from app.services.llm_circuit_connection_extraction_service import match_region_name

    session = AsyncMock()
    mock_result = MagicMock()
    mock_result.scalar_one_or_none = MagicMock(return_value=None)
    mock_result.scalars = MagicMock(return_value=MagicMock(all=lambda: []))
    session.execute = AsyncMock(return_value=mock_result)

    result = asyncio.run(match_region_name(session, "nonexistent_brain_area_xyz"))
    assert result is None


def test_dedup_creates_new_when_not_exists(monkeypatch):
    """dedup_and_write_connection creates new connection when none exists."""
    from app.services.llm_circuit_connection_extraction_service import dedup_and_write_connection

    session = AsyncMock()
    session.execute = AsyncMock(return_value=MagicMock(scalar_one_or_none=MagicMock(return_value=None)))
    session.flush = AsyncMock()

    sid = uuid.uuid4()
    tid = uuid.uuid4()
    cid, action, reason = asyncio.run(
        dedup_and_write_connection(session, sid, tid, "structural_connection", 0.85, "test evidence", run_id=uuid.uuid4())
    )
    assert action == "created"
    assert cid is not None


def test_dedup_skips_when_higher_confidence_exists():
    """dedup_and_write_connection skips when existing confidence >= new."""
    from app.services.llm_circuit_connection_extraction_service import dedup_and_write_connection
    from app.models.mirror_kg import MirrorRegionConnection

    existing = MirrorRegionConnection(
        id=uuid.uuid4(),
        connection_type="structural_connection",
        confidence=0.9,
        granularity_level="macro",
        source_atlas="test",
        source_region_candidate_id=uuid.uuid4(),
        target_region_candidate_id=uuid.uuid4(),
        mirror_status="llm_suggested",
        review_status="pending",
        promotion_status="not_promoted",
        raw_payload_json={},
        normalized_payload_json={},
    )
    session = AsyncMock()
    session.execute = AsyncMock(return_value=MagicMock(scalar_one_or_none=MagicMock(return_value=existing)))
    session.flush = AsyncMock()

    conn_id, action, reason = asyncio.run(
        dedup_and_write_connection(session, existing.source_region_candidate_id,
                                   existing.target_region_candidate_id,
                                   "functional_connectivity", 0.5, "weaker evidence",
                                   run_id=uuid.uuid4())
    )
    assert action == "skipped"
    assert reason and "existing confidence" in reason.lower()
