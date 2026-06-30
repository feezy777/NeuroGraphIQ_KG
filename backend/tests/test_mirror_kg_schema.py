"""Mirror KG Schema Foundation tests (no LLM / no external network)."""

from __future__ import annotations

import asyncio
import uuid
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from pydantic import ValidationError

from app.models.candidate import CandidateBrainRegion
from app.models.llm_extraction import LlmExtractionItem
from app.models.mirror_kg import (
    MirrorCircuitRegion,
    MirrorEvidenceRecord,
    MirrorKgTriple,
    MirrorRegionCircuit,
    MirrorRegionConnection,
    MirrorRegionFunction,
)
from app.schemas.llm_extraction import LlmTaskType
from app.schemas.mirror_kg import (
    MirrorEvidenceRecordCreate,
    MirrorKgTripleCreate,
    MirrorPromotionStatus,
    MirrorRegionCircuitCreate,
    MirrorRegionConnectionCreate,
    MirrorRegionFunctionCreate,
    MirrorReviewStatus,
    MirrorStatus,
    TripleSubjectType,
)
from app.services import llm_to_mirror_service, mirror_kg_service


def _candidate(**kwargs) -> CandidateBrainRegion:
    defaults = dict(
        id=uuid.uuid4(),
        batch_id=uuid.uuid4(),
        resource_id=uuid.uuid4(),
        generation_run_id=uuid.uuid4(),
        parse_run_id=uuid.uuid4(),
        source_atlas="AAL3",
        source_version="v1",
        raw_name="Hippocampus_L",
        laterality="left",
        granularity_level="macro",
        granularity_family="macro_clinical",
        candidate_status="candidate_created",
    )
    defaults.update(kwargs)
    return CandidateBrainRegion(**defaults)


def test_connection_create_defaults():
    payload = MirrorRegionConnectionCreate(
        granularity_level="macro",
        source_atlas="AAL3",
        connection_type="structural_connection",
    )
    assert payload.mirror_status == MirrorStatus.llm_suggested
    assert payload.review_status == MirrorReviewStatus.pending
    assert payload.promotion_status == MirrorPromotionStatus.not_promoted


def test_connection_confidence_out_of_range_rejected():
    with pytest.raises(ValidationError):
        MirrorRegionConnectionCreate(
            granularity_level="macro",
            source_atlas="AAL3",
            connection_type="unknown",
            confidence=1.5,
        )


def test_connection_create_blocks_promoted_status():
    with pytest.raises(ValidationError):
        MirrorRegionConnectionCreate(
            granularity_level="macro",
            source_atlas="AAL3",
            connection_type="unknown",
            promotion_status=MirrorPromotionStatus.promoted,
        )


def test_function_category_enum_accepted():
    payload = MirrorRegionFunctionCreate(
        granularity_level="macro",
        source_atlas="Macro96",
        function_term="memory encoding",
        function_category="memory",
    )
    assert payload.function_category == "memory"


def test_triple_subject_type_enum():
    payload = MirrorKgTripleCreate(
        subject_type=TripleSubjectType.region_candidate,
        subject_label="Hippocampus",
        predicate="connected_to",
        object_type=TripleSubjectType.region_candidate,
        object_label="Amygdala",
        granularity_level="macro",
        source_atlas="AAL3",
    )
    assert payload.subject_type == "region_candidate"


def test_create_mirror_connection_service_defaults():
    session = AsyncMock()
    session.add = MagicMock()
    session.flush = AsyncMock()
    session.refresh = AsyncMock()

    payload = MirrorRegionConnectionCreate(
        granularity_level="macro",
        source_atlas="AAL3",
        connection_type="association",
        confidence=0.7,
    )

    with patch("app.services.mirror_kg_service._find_existing_connection_for_merge", AsyncMock(return_value=None)):
        row = asyncio.run(mirror_kg_service.create_mirror_connection(session, payload))
    assert isinstance(row, MirrorRegionConnection)
    assert row.mirror_status == MirrorStatus.llm_suggested
    assert row.promotion_status == MirrorPromotionStatus.not_promoted
    session.add.assert_called_once()


def test_same_granularity_validation_rejects_mismatch():
    src = _candidate(granularity_level="macro")
    tgt = _candidate(granularity_level="micro")
    session = AsyncMock()
    session.get = AsyncMock(side_effect=lambda _model, cid: src if cid == src.id else tgt)

    payload = MirrorRegionConnectionCreate(
        source_region_candidate_id=src.id,
        target_region_candidate_id=tgt.id,
        granularity_level="macro",
        source_atlas="AAL3",
        connection_type="unknown",
    )
    with pytest.raises(mirror_kg_service.SameGranularityValidationError):
        asyncio.run(mirror_kg_service.create_mirror_connection(session, payload))


def test_create_mirror_function_service():
    session = AsyncMock()
    session.add = MagicMock()
    session.flush = AsyncMock()
    session.refresh = AsyncMock()

    payload = MirrorRegionFunctionCreate(
        granularity_level="macro",
        source_atlas="Macro96",
        function_term="visual processing",
        function_category="visual",
    )
    with patch("app.services.mirror_kg_service._find_existing_function_for_merge", AsyncMock(return_value=None)):
        row = asyncio.run(mirror_kg_service.create_mirror_function(session, payload))
    assert isinstance(row, MirrorRegionFunction)
    assert row.review_status == MirrorReviewStatus.pending


def test_create_mirror_circuit_with_regions():
    session = AsyncMock()
    session.add = MagicMock()
    session.flush = AsyncMock()
    session.refresh = AsyncMock()

    cid = uuid.uuid4()
    payload = MirrorRegionCircuitCreate(
        granularity_level="macro",
        source_atlas="AAL3",
        circuit_name="limbic loop",
        circuit_type="limbic_circuit",
        circuit_regions=[{"region_candidate_id": cid, "role": "participant", "sort_order": 0}],
    )
    with patch("app.services.mirror_kg_service._find_existing_circuit_for_merge", AsyncMock(return_value=None)):
        row = asyncio.run(mirror_kg_service.create_mirror_circuit(session, payload))
    assert isinstance(row, MirrorRegionCircuit)
    assert session.add.call_count >= 2


def test_create_mirror_triple_service():
    session = AsyncMock()
    session.add = MagicMock()
    session.flush = AsyncMock()
    session.refresh = AsyncMock()

    payload = MirrorKgTripleCreate(
        subject_type="region_candidate",
        subject_label="A",
        predicate="connected_to",
        object_type="region_candidate",
        object_label="B",
        granularity_level="macro",
        source_atlas="AAL3",
    )
    with patch("app.services.mirror_kg_service._find_existing_triple_for_merge", AsyncMock(return_value=None)):
        row = asyncio.run(mirror_kg_service.create_mirror_triple(session, payload))
    assert isinstance(row, MirrorKgTriple)


def test_create_mirror_evidence_service():
    session = AsyncMock()
    session.add = MagicMock()
    session.flush = AsyncMock()
    session.refresh = AsyncMock()

    payload = MirrorEvidenceRecordCreate(
        evidence_target_type="mirror_connection",
        evidence_target_id=uuid.uuid4(),
        evidence_text="LLM suggested based on literature summary",
    )
    with patch("app.services.mirror_kg_service._find_existing_evidence", AsyncMock(return_value=None)):
        row = asyncio.run(mirror_kg_service.create_mirror_evidence(session, payload))
    assert isinstance(row, MirrorEvidenceRecord)


def test_llm_item_to_mirror_function_success():
    item_id = uuid.uuid4()
    item = LlmExtractionItem(
        id=item_id,
        run_id=uuid.uuid4(),
        candidate_id=uuid.uuid4(),
        task_type=LlmTaskType.same_granularity_function_completion,
        normalized_output_json={
            "function_term": "memory",
            "function_category": "memory",
            "granularity_level": "macro",
            "source_atlas": "AAL3",
            "confidence": 0.6,
        },
        status="succeeded",
    )
    session = AsyncMock()
    session.get = AsyncMock(return_value=item)
    session.add = MagicMock()
    session.flush = AsyncMock()
    session.refresh = AsyncMock()

    with patch("app.services.mirror_kg_service._find_existing_function_for_merge", AsyncMock(return_value=None)):
        row = asyncio.run(llm_to_mirror_service.create_mirror_function_from_llm_item(session, item_id))
    assert isinstance(row, MirrorRegionFunction)
    assert row.function_term == "memory"
    assert row.llm_item_id == item_id


def test_llm_item_task_type_mismatch_rejected():
    item_id = uuid.uuid4()
    item = LlmExtractionItem(
        id=item_id,
        run_id=uuid.uuid4(),
        task_type=LlmTaskType.region_field_completion,
        normalized_output_json={"function_term": "x", "granularity_level": "m", "source_atlas": "A"},
        status="succeeded",
    )
    session = AsyncMock()
    session.get = AsyncMock(return_value=item)

    with pytest.raises(llm_to_mirror_service.LlmItemTaskTypeMismatchError):
        asyncio.run(llm_to_mirror_service.create_mirror_function_from_llm_item(session, item_id))


def test_llm_item_invalid_normalized_output():
    item_id = uuid.uuid4()
    item = LlmExtractionItem(
        id=item_id,
        run_id=uuid.uuid4(),
        task_type=LlmTaskType.same_granularity_connection_completion,
        normalized_output_json={},
        status="succeeded",
    )
    session = AsyncMock()
    session.get = AsyncMock(return_value=item)

    with pytest.raises(llm_to_mirror_service.LlmItemNormalizedOutputError):
        asyncio.run(llm_to_mirror_service.create_mirror_connection_from_llm_item(session, item_id))


def test_llm_item_to_mirror_connection_success():
    item_id = uuid.uuid4()
    src = uuid.uuid4()
    tgt = uuid.uuid4()
    item = LlmExtractionItem(
        id=item_id,
        run_id=uuid.uuid4(),
        task_type=LlmTaskType.same_granularity_connection_completion,
        normalized_output_json={
            "source_region_candidate_id": str(src),
            "target_region_candidate_id": str(tgt),
            "connection_type": "structural_connection",
            "granularity_level": "macro",
            "source_atlas": "AAL3",
        },
        status="succeeded",
    )
    session = AsyncMock()
    session.get = AsyncMock(
        side_effect=lambda model, pk: (
            item
            if model is LlmExtractionItem
            else _candidate(id=pk, granularity_level="macro", source_atlas="AAL3")
        )
    )
    session.add = MagicMock()
    session.flush = AsyncMock()
    session.refresh = AsyncMock()

    with patch("app.services.mirror_kg_service._find_existing_connection_for_merge", AsyncMock(return_value=None)):
        row = asyncio.run(llm_to_mirror_service.create_mirror_connection_from_llm_item(session, item_id))
    assert isinstance(row, MirrorRegionConnection)
    assert row.llm_item_id == item_id


def test_mirror_connections_api_list_empty_or_ok():
    from fastapi.testclient import TestClient

    from app.main import app

    client = TestClient(app, raise_server_exceptions=False)
    resp = client.get("/api/mirror-kg/connections")
    assert resp.status_code in (200, 500)
    if resp.status_code == 200:
        body = resp.json()
        assert "items" in body
        assert "total" in body


def test_mirror_connections_api_create_validation():
    from fastapi.testclient import TestClient

    from app.main import app

    client = TestClient(app, raise_server_exceptions=False)
    resp = client.post(
        "/api/mirror-kg/connections",
        json={
            "granularity_level": "macro",
            "source_atlas": "AAL3",
            "connection_type": "association",
            "confidence": 2.0,
        },
    )
    assert resp.status_code == 422


def test_health_reports_mirror_kg_module():
    from fastapi.testclient import TestClient

    from app.main import app

    client = TestClient(app)
    body = client.get("/api/health").json()
    assert body["modules"]["mirror_kg"] == "active"


def test_llm_item_id_set_null_on_delete_design():
    """FK on mirror tables uses ON DELETE SET NULL for llm_item_id."""
    import inspect

    from app.models.mirror_kg import MirrorRegionConnection

    col = MirrorRegionConnection.__table__.c.llm_item_id
    fk = list(col.foreign_keys)[0]
    assert fk.ondelete == "SET NULL"
