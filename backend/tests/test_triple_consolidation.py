"""Triple consolidation tests (deterministic, no LLM, no network)."""

from __future__ import annotations

import asyncio
import uuid
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from fastapi.testclient import TestClient

from app.models.candidate import CandidateBrainRegion
from app.models.mirror_kg import (
    MirrorCircuitRegion,
    MirrorKgTriple,
    MirrorRegionCircuit,
    MirrorRegionConnection,
    MirrorRegionFunction,
)
from app.schemas.mirror_kg import MirrorReviewStatus, MirrorStatus
from app.services.triple_consolidation_service import (
    ConsolidationScope,
    EmptySourceTypesError,
    ExplicitIdNotFoundError,
    InvalidSourceTypeError,
    ScopeMismatchError,
    build_circuit_triple_candidates,
    build_connection_triple_candidates,
    build_function_triple_candidates,
    consolidate_mirror_triples,
    normalize_triple_key,
    triple_row_key,
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
        raw_name="Hippocampus_L",
        en_name="Hippocampus",
        laterality="left",
        granularity_level="macro",
        granularity_family="macro_clinical",
        candidate_status="rule_passed",
    )
    defaults.update(kwargs)
    return CandidateBrainRegion(**defaults)


def _connection(**kwargs) -> MirrorRegionConnection:
    defaults = dict(
        id=uuid.uuid4(),
        batch_id=uuid.uuid4(),
        resource_id=uuid.uuid4(),
        source_atlas="Macro96",
        granularity_level="macro",
        granularity_family="macro_clinical",
        source_region_candidate_id=uuid.uuid4(),
        target_region_candidate_id=uuid.uuid4(),
        connection_type="functional_connectivity",
        directionality="undirected",
        mirror_status=MirrorStatus.llm_suggested,
        review_status=MirrorReviewStatus.pending,
        promotion_status="not_promoted",
    )
    defaults.update(kwargs)
    return MirrorRegionConnection(**defaults)


def _function(**kwargs) -> MirrorRegionFunction:
    defaults = dict(
        id=uuid.uuid4(),
        batch_id=uuid.uuid4(),
        resource_id=uuid.uuid4(),
        source_atlas="Macro96",
        granularity_level="macro",
        granularity_family="macro_clinical",
        region_candidate_id=uuid.uuid4(),
        function_term="memory",
        function_category="memory",
        relation_type="associated_with",
        mirror_status=MirrorStatus.llm_suggested,
        review_status=MirrorReviewStatus.pending,
        promotion_status="not_promoted",
    )
    defaults.update(kwargs)
    return MirrorRegionFunction(**defaults)


def _circuit(**kwargs) -> MirrorRegionCircuit:
    defaults = dict(
        id=uuid.uuid4(),
        batch_id=uuid.uuid4(),
        resource_id=uuid.uuid4(),
        source_atlas="Macro96",
        granularity_level="macro",
        granularity_family="macro_clinical",
        circuit_name="limbic circuit",
        circuit_type="limbic_circuit",
        function_association="memory",
        mirror_status=MirrorStatus.llm_suggested,
        review_status=MirrorReviewStatus.pending,
        promotion_status="not_promoted",
    )
    defaults.update(kwargs)
    return MirrorRegionCircuit(**defaults)


def test_normalize_triple_key_uses_ids_when_present():
    a, b = uuid.uuid4(), uuid.uuid4()
    key = normalize_triple_key(
        subject_type="region_candidate",
        subject_id=a,
        subject_label="Hippocampus",
        predicate="functionally_connects_to",
        object_type="region_candidate",
        object_id=b,
        object_label="Amygdala",
        triple_scope="same_granularity",
        source_atlas="Macro96",
        granularity_level="macro",
        granularity_family="macro_clinical",
        resource_id=uuid.uuid4(),
        batch_id=uuid.uuid4(),
    )
    assert key[1] == str(a)
    assert key[4] == str(b)


def test_build_connection_triple():
    c1 = _candidate()
    c2 = _candidate(batch_id=c1.batch_id, resource_id=c1.resource_id)
    conn = _connection(
        source_region_candidate_id=c1.id,
        target_region_candidate_id=c2.id,
        connection_type="functional_connectivity",
    )
    warnings: list[str] = []
    cands, skip = build_connection_triple_candidates([conn], {c1.id: c1, c2.id: c2}, warnings)
    assert skip == 0
    assert len(cands) == 1
    assert cands[0].predicate == "functionally_connects_to"
    assert cands[0].source_mirror_connection_id == conn.id


def test_build_connection_bidirectional_predicate():
    c1, c2 = _candidate(), _candidate()
    conn = _connection(
        source_region_candidate_id=c1.id,
        target_region_candidate_id=c2.id,
        directionality="bidirectional",
    )
    cands, _ = build_connection_triple_candidates([conn], {c1.id: c1, c2.id: c2}, [])
    assert cands[0].predicate == "bidirectionally_connects_to"


def test_build_function_triple():
    c1 = _candidate()
    fn = _function(region_candidate_id=c1.id, relation_type="involved_in")
    cands, skip = build_function_triple_candidates([fn], {c1.id: c1}, [])
    assert skip == 0
    assert cands[0].predicate == "involved_in_function"
    assert cands[0].source_mirror_function_id == fn.id


def test_build_function_skips_empty_term():
    fn = _function(function_term="  ")
    cands, skip = build_function_triple_candidates([fn], {}, [])
    assert cands == []
    assert skip == 1


def test_build_circuit_triples():
    c1, c2 = _candidate(), _candidate()
    circ = _circuit()
    cr1 = MirrorCircuitRegion(circuit_id=circ.id, region_candidate_id=c1.id, role="participant", sort_order=0)
    cr2 = MirrorCircuitRegion(circuit_id=circ.id, region_candidate_id=c2.id, role="participant", sort_order=1)
    cands, skip = build_circuit_triple_candidates(
        [circ], [cr1, cr2], {c1.id: c1, c2.id: c2}, []
    )
    assert skip == 0
    predicates = {c.predicate for c in cands}
    assert "has_participant_region" in predicates
    assert "associated_with_function" in predicates
    assert all(c.source_mirror_circuit_id == circ.id for c in cands)


def test_duplicate_key_same_session():
    a, b = uuid.uuid4(), uuid.uuid4()
    k1 = normalize_triple_key(
        subject_type="region_candidate", subject_id=a, subject_label="A",
        predicate="p", object_type="region_candidate", object_id=b, object_label="B",
        triple_scope="same_granularity", source_atlas="Macro96", granularity_level="macro",
        granularity_family="macro_clinical", resource_id=None, batch_id=None,
    )
    k2 = normalize_triple_key(
        subject_type="region_candidate", subject_id=a, subject_label="different",
        predicate="p", object_type="region_candidate", object_id=b, object_label="other",
        triple_scope="same_granularity", source_atlas="Macro96", granularity_level="macro",
        granularity_family="macro_clinical", resource_id=None, batch_id=None,
    )
    assert k1 == k2


def test_triple_row_key_from_model():
    row = MirrorKgTriple(
        id=uuid.uuid4(),
        subject_type="region_candidate",
        subject_id=uuid.uuid4(),
        subject_label="Hippocampus",
        predicate="functionally_connects_to",
        object_type="region_candidate",
        object_id=uuid.uuid4(),
        object_label="Amygdala",
        triple_scope="same_granularity",
        granularity_level="macro",
        source_atlas="Macro96",
    )
    assert triple_row_key(row)


def test_api_empty_source_types():
    from app.main import app

    client = TestClient(app)
    resp = client.post("/api/mirror-kg/triples/consolidate", json={"source_types": [], "dry_run": True})
    assert resp.status_code == 422


def test_api_invalid_source_type():
    from app.main import app

    client = TestClient(app)
    resp = client.post(
        "/api/mirror-kg/triples/consolidate",
        json={"source_types": ["invalid"], "dry_run": True},
    )
    assert resp.status_code == 400


def test_dry_run_does_not_persist():
    c1, c2 = _candidate(), _candidate()
    conn = _connection(
        source_region_candidate_id=c1.id,
        target_region_candidate_id=c2.id,
        batch_id=c1.batch_id,
        resource_id=c1.resource_id,
    )
    session = AsyncMock()
    session.execute = AsyncMock(
        side_effect=[
            MagicMock(scalars=MagicMock(return_value=MagicMock(all=MagicMock(return_value=[conn])))),
            MagicMock(scalars=MagicMock(return_value=MagicMock(all=MagicMock(return_value=[c1, c2])))),
            MagicMock(scalars=MagicMock(return_value=MagicMock(all=MagicMock(return_value=[])))),
        ]
    )
    session.get = AsyncMock(side_effect=lambda model, pk: {c1.id: c1, c2.id: c2, conn.id: conn}.get(pk))

    with patch("app.services.triple_consolidation_service.mirror_kg_service.create_mirror_triple") as create:
        result = asyncio.run(
            consolidate_mirror_triples(
                session,
                source_types=["connection"],
                scope=ConsolidationScope(source_atlas="Macro96", granularity_level="macro"),
                dry_run=True,
            )
        )
        create.assert_not_called()

    assert result.dry_run is True
    assert result.created_triple_count == 0


def test_consolidate_writes_when_not_dry_run():
    c1, c2 = _candidate(), _candidate()
    conn = _connection(
        source_region_candidate_id=c1.id,
        target_region_candidate_id=c2.id,
        batch_id=c1.batch_id,
        resource_id=c1.resource_id,
    )
    session = AsyncMock()
    session.execute = AsyncMock(
        side_effect=[
            MagicMock(scalars=MagicMock(return_value=MagicMock(all=MagicMock(return_value=[conn])))),
            MagicMock(scalars=MagicMock(return_value=MagicMock(all=MagicMock(return_value=[c1, c2])))),
            MagicMock(scalars=MagicMock(return_value=MagicMock(all=MagicMock(return_value=[])))),
        ]
    )
    session.get = AsyncMock(side_effect=lambda model, pk: {c1.id: c1, c2.id: c2, conn.id: conn}.get(pk))
    session.commit = AsyncMock()

    mock_triple = MagicMock()
    mock_triple.id = uuid.uuid4()

    with patch("app.services.triple_consolidation_service.mirror_kg_service.create_mirror_triple", new_callable=AsyncMock) as create:
        create.return_value = mock_triple
        result = asyncio.run(
            consolidate_mirror_triples(
                session,
                source_types=["connection"],
                scope=ConsolidationScope(source_atlas="Macro96", granularity_level="macro"),
                dry_run=False,
            )
        )

    assert result.created_triple_count == 1
    create.assert_called_once()
    session.commit.assert_called_once()


def test_explicit_connection_not_found():
    session = AsyncMock()
    session.get = AsyncMock(return_value=None)
    cid = uuid.uuid4()
    with pytest.raises(ExplicitIdNotFoundError):
        asyncio.run(
            consolidate_mirror_triples(
                session,
                source_types=["connection"],
                connection_ids=[cid],
                dry_run=True,
            )
        )


def test_explicit_scope_mismatch():
    conn = _connection(source_atlas="AAL3")
    session = AsyncMock()
    session.get = AsyncMock(return_value=conn)
    with pytest.raises(ScopeMismatchError):
        asyncio.run(
            consolidate_mirror_triples(
                session,
                source_types=["connection"],
                connection_ids=[conn.id],
                scope=ConsolidationScope(source_atlas="Macro96"),
                dry_run=True,
            )
        )


def test_skips_rejected_sources_in_auto_load():
    conn_ok = _connection(mirror_status=MirrorStatus.llm_suggested)
    conn_bad = _connection(mirror_status=MirrorStatus.human_rejected)
    session = AsyncMock()
    session.execute = AsyncMock(
        side_effect=[
            MagicMock(scalars=MagicMock(return_value=MagicMock(all=MagicMock(return_value=[conn_ok, conn_bad])))),
            MagicMock(scalars=MagicMock(return_value=MagicMock(all=MagicMock(return_value=[])))),
            MagicMock(scalars=MagicMock(return_value=MagicMock(all=MagicMock(return_value=[])))),
        ]
    )
    result = asyncio.run(
        consolidate_mirror_triples(
            session,
            source_types=["connection"],
            dry_run=True,
        )
    )
    assert result.source_counts["connections"] == 1


def test_empty_source_types_raises():
    with pytest.raises(EmptySourceTypesError):
        asyncio.run(consolidate_mirror_triples(AsyncMock(), source_types=[], dry_run=True))


def test_invalid_source_type_raises():
    with pytest.raises(InvalidSourceTypeError):
        asyncio.run(consolidate_mirror_triples(AsyncMock(), source_types=["bad"], dry_run=True))
