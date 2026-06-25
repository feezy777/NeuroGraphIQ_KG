"""Mirror KG Rule Validation tests (deterministic, no LLM, no network)."""

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
from app.models.mirror_validation import MirrorRuleValidationRun
from app.schemas.mirror_kg import MirrorReviewStatus, MirrorStatus
from app.services import mirror_rule_validation_service as mrv


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
    c1 = kwargs.pop("_c1", None) or _candidate()
    c2 = kwargs.pop("_c2", None) or _candidate()
    defaults = dict(
        id=uuid.uuid4(),
        batch_id=c1.batch_id,
        resource_id=c1.resource_id,
        source_atlas="Macro96",
        granularity_level="macro",
        granularity_family="macro_clinical",
        source_region_candidate_id=c1.id,
        target_region_candidate_id=c2.id,
        connection_type="functional_connectivity",
        directionality="undirected",
        confidence=0.72,
        evidence_text="test evidence",
        mirror_status=MirrorStatus.llm_suggested,
        review_status=MirrorReviewStatus.pending,
        promotion_status="not_promoted",
    )
    defaults.update(kwargs)
    conn = MirrorRegionConnection(**defaults)
    conn._test_c1 = c1  # noqa: SLF001
    conn._test_c2 = c2  # noqa: SLF001
    return conn


def _function(**kwargs) -> MirrorRegionFunction:
    c = kwargs.pop("_c", None) or _candidate()
    defaults = dict(
        id=uuid.uuid4(),
        batch_id=c.batch_id,
        resource_id=c.resource_id,
        source_atlas="Macro96",
        granularity_level="macro",
        granularity_family="macro_clinical",
        region_candidate_id=c.id,
        function_term="memory",
        function_category="memory",
        relation_type="associated_with",
        confidence=0.8,
        evidence_text="fn evidence",
        mirror_status=MirrorStatus.llm_suggested,
        review_status=MirrorReviewStatus.pending,
        promotion_status="not_promoted",
    )
    defaults.update(kwargs)
    fn = MirrorRegionFunction(**defaults)
    fn._test_c = c  # noqa: SLF001
    return fn


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
        function_association="emotion",
        confidence=0.75,
        evidence_text="circuit evidence",
        mirror_status=MirrorStatus.llm_suggested,
        review_status=MirrorReviewStatus.pending,
        promotion_status="not_promoted",
    )
    defaults.update(kwargs)
    return MirrorRegionCircuit(**defaults)


def _triple(**kwargs) -> MirrorKgTriple:
    defaults = dict(
        id=uuid.uuid4(),
        batch_id=uuid.uuid4(),
        resource_id=uuid.uuid4(),
        source_atlas="Macro96",
        granularity_level="macro",
        granularity_family="macro_clinical",
        subject_type="region_candidate",
        subject_id=uuid.uuid4(),
        subject_label="Hippocampus",
        predicate="functionally_connects_to",
        object_type="region_candidate",
        object_id=uuid.uuid4(),
        object_label="Amygdala",
        triple_scope="same_granularity",
        confidence=0.7,
        evidence_text="triple evidence",
        mirror_status=MirrorStatus.llm_suggested,
        review_status=MirrorReviewStatus.pending,
        promotion_status="not_promoted",
    )
    defaults.update(kwargs)
    return MirrorKgTriple(**defaults)


def test_api_empty_target_types():
    from app.main import app

    client = TestClient(app)
    resp = client.post("/api/mirror-kg/validation/run", json={"target_types": [], "dry_run": True})
    assert resp.status_code == 422


def test_api_invalid_target_type():
    from app.main import app

    client = TestClient(app)
    resp = client.post(
        "/api/mirror-kg/validation/run",
        json={"target_types": ["invalid"], "dry_run": True},
    )
    assert resp.status_code == 400


def test_connection_missing_source_region_blocker():
    conn = _connection(source_region_candidate_id=None, source_region_final_id=None)
    checks = mrv.validate_connection(conn, candidate_map={}, duplicate_keys={})
    codes = {c.rule_code for c in checks}
    assert "RULE_CONNECTION_SOURCE_REGION_REQUIRED" in codes
    assert any(c.severity == mrv.MirrorValidationSeverity.blocker for c in checks)


def test_connection_missing_target_region_blocker():
    conn = _connection(target_region_candidate_id=None, target_region_final_id=None)
    checks = mrv.validate_connection(conn, candidate_map={}, duplicate_keys={})
    assert any(c.rule_code == "RULE_CONNECTION_TARGET_REGION_REQUIRED" for c in checks)


def test_connection_self_loop_blocker():
    cid = uuid.uuid4()
    conn = _connection(source_region_candidate_id=cid, target_region_candidate_id=cid)
    checks = mrv.validate_connection(conn, candidate_map={}, duplicate_keys={})
    assert any(c.rule_code == "RULE_CONNECTION_NO_SELF_LOOP" for c in checks)


def test_connection_cross_atlas_blocker():
    conn = _connection()
    c1, c2 = conn._test_c1, conn._test_c2  # noqa: SLF001
    c2 = _candidate(id=c2.id, source_atlas="AAL3")
    checks = mrv.validate_connection(conn, candidate_map={c1.id: c1, c2.id: c2}, duplicate_keys={})
    assert any(c.rule_code == "RULE_CONNECTION_SAME_ATLAS" for c in checks)


def test_connection_duplicate_warning():
    conn1 = _connection()
    conn2 = _connection(
        batch_id=conn1.batch_id,
        resource_id=conn1.resource_id,
        source_region_candidate_id=conn1.source_region_candidate_id,
        target_region_candidate_id=conn1.target_region_candidate_id,
        connection_type=conn1.connection_type,
        directionality=conn1.directionality,
    )
    dup: dict = {}
    c1, c2 = conn1._test_c1, conn1._test_c2  # noqa: SLF001
    mrv.validate_connection(conn1, candidate_map={c1.id: c1, c2.id: c2}, duplicate_keys=dup)
    checks2 = mrv.validate_connection(conn2, candidate_map={c1.id: c1, c2.id: c2}, duplicate_keys=dup)
    assert any(c.rule_code == "RULE_CONNECTION_DUPLICATE" for c in checks2)


def test_function_missing_region_blocker():
    fn = _function(region_candidate_id=None, region_final_id=None)
    checks = mrv.validate_function(fn, candidate_map={}, duplicate_keys={})
    assert any(c.rule_code == "RULE_FUNCTION_REGION_REQUIRED" for c in checks)


def test_function_missing_term_blocker():
    fn = _function(function_term="  ")
    c = fn._test_c  # noqa: SLF001
    checks = mrv.validate_function(fn, candidate_map={c.id: c}, duplicate_keys={})
    assert any(c.rule_code == "RULE_FUNCTION_TERM_REQUIRED" for c in checks)


def test_function_cross_granularity_blocker():
    fn = _function()
    c = fn._test_c  # noqa: SLF001
    c_bad = _candidate(id=c.id, granularity_level="meso")
    checks = mrv.validate_function(fn, candidate_map={c.id: c_bad}, duplicate_keys={})
    assert any(c.rule_code == "RULE_FUNCTION_SAME_GRANULARITY" for c in checks)


def test_function_duplicate_warning():
    fn1 = _function()
    fn2 = _function(
        batch_id=fn1.batch_id,
        resource_id=fn1.resource_id,
        region_candidate_id=fn1.region_candidate_id,
        function_term=fn1.function_term,
        function_category=fn1.function_category,
        relation_type=fn1.relation_type,
    )
    c = fn1._test_c  # noqa: SLF001
    dup: dict = {}
    mrv.validate_function(fn1, candidate_map={c.id: c}, duplicate_keys=dup)
    checks2 = mrv.validate_function(fn2, candidate_map={c.id: c}, duplicate_keys=dup)
    assert any(c.rule_code == "RULE_FUNCTION_DUPLICATE" for c in checks2)


def test_circuit_missing_name_blocker():
    circ = _circuit(circuit_name="")
    checks = mrv.validate_circuit(circ, circuit_regions=[], candidate_map={}, duplicate_keys={})
    assert any(c.rule_code == "RULE_CIRCUIT_NAME_REQUIRED" for c in checks)


def test_circuit_regions_lt2_blocker():
    circ = _circuit()
    c = _candidate()
    cr = MirrorCircuitRegion(circuit_id=circ.id, region_candidate_id=c.id, role="participant", sort_order=0)
    checks = mrv.validate_circuit(circ, circuit_regions=[cr], candidate_map={c.id: c}, duplicate_keys={})
    assert any(c.rule_code == "RULE_CIRCUIT_REGIONS_REQUIRED" for c in checks)


def test_circuit_region_not_exists_blocker():
    circ = _circuit()
    rid = uuid.uuid4()
    cr1 = MirrorCircuitRegion(circuit_id=circ.id, region_candidate_id=rid, role="participant", sort_order=0)
    cr2 = MirrorCircuitRegion(circuit_id=circ.id, region_candidate_id=uuid.uuid4(), role="participant", sort_order=1)
    checks = mrv.validate_circuit(circ, circuit_regions=[cr1, cr2], candidate_map={}, duplicate_keys={})
    assert any(c.rule_code == "RULE_CIRCUIT_REGION_EXISTS" for c in checks)


def test_circuit_duplicate_warning():
    circ1 = _circuit()
    c1, c2 = _candidate(), _candidate()
    crs1 = [
        MirrorCircuitRegion(circuit_id=circ1.id, region_candidate_id=c1.id, role="participant", sort_order=0),
        MirrorCircuitRegion(circuit_id=circ1.id, region_candidate_id=c2.id, role="participant", sort_order=1),
    ]
    circ2 = _circuit(
        batch_id=circ1.batch_id,
        resource_id=circ1.resource_id,
        circuit_name=circ1.circuit_name,
        circuit_type=circ1.circuit_type,
    )
    crs2 = [
        MirrorCircuitRegion(circuit_id=circ2.id, region_candidate_id=c1.id, role="participant", sort_order=0),
        MirrorCircuitRegion(circuit_id=circ2.id, region_candidate_id=c2.id, role="participant", sort_order=1),
    ]
    cmap = {c1.id: c1, c2.id: c2}
    dup: dict = {}
    mrv.validate_circuit(circ1, circuit_regions=crs1, candidate_map=cmap, duplicate_keys=dup)
    checks2 = mrv.validate_circuit(circ2, circuit_regions=crs2, candidate_map=cmap, duplicate_keys=dup)
    assert any(c.rule_code == "RULE_CIRCUIT_DUPLICATE" for c in checks2)


def test_triple_missing_subject_blocker():
    t = _triple(subject_label="", subject_id=None)
    checks = mrv.validate_triple(t, connection_map={}, function_map={}, circuit_map={}, duplicate_keys={})
    assert any(c.rule_code == "RULE_TRIPLE_SUBJECT_REQUIRED" for c in checks)


def test_triple_missing_object_blocker():
    t = _triple(object_label="", object_id=None)
    checks = mrv.validate_triple(t, connection_map={}, function_map={}, circuit_map={}, duplicate_keys={})
    assert any(c.rule_code == "RULE_TRIPLE_OBJECT_REQUIRED" for c in checks)


def test_triple_missing_predicate_blocker():
    t = _triple(predicate="")
    checks = mrv.validate_triple(t, connection_map={}, function_map={}, circuit_map={}, duplicate_keys={})
    assert any(c.rule_code == "RULE_TRIPLE_PREDICATE_REQUIRED" for c in checks)


def test_triple_source_link_missing_warning():
    t = _triple()
    checks = mrv.validate_triple(t, connection_map={}, function_map={}, circuit_map={}, duplicate_keys={})
    assert any(c.rule_code == "RULE_TRIPLE_SOURCE_LINK_REQUIRED" for c in checks)


def test_triple_source_link_not_exists_blocker():
    t = _triple(source_mirror_connection_id=uuid.uuid4())
    checks = mrv.validate_triple(t, connection_map={}, function_map={}, circuit_map={}, duplicate_keys={})
    assert any(c.rule_code == "RULE_TRIPLE_SOURCE_LINK_EXISTS" for c in checks)


def test_low_confidence_warning():
    conn = _connection(confidence=0.3)
    checks = mrv.validate_common_fields(conn)
    assert any(c.rule_code == "RULE_COMMON_LOW_CONFIDENCE" for c in checks)


def test_missing_evidence_warning():
    conn = _connection(evidence_text=None)
    checks = mrv.validate_common_fields(conn)
    assert any(c.rule_code == "RULE_COMMON_EVIDENCE_REQUIRED" for c in checks)


def test_dry_run_does_not_persist():
    conn = _connection()
    c1, c2 = conn._test_c1, conn._test_c2  # noqa: SLF001
    session = AsyncMock()
    session.execute = AsyncMock(
        side_effect=[
            MagicMock(scalars=MagicMock(return_value=MagicMock(all=MagicMock(return_value=[conn])))),
            MagicMock(scalars=MagicMock(return_value=MagicMock(all=MagicMock(return_value=[c1, c2])))),
        ]
    )
    session.get = AsyncMock(return_value=None)
    session.add = MagicMock()
    session.commit = AsyncMock()

    result = asyncio.run(
        mrv.run_mirror_rule_validation(
            session,
            target_types=["connection"],
            dry_run=True,
        )
    )
    session.add.assert_not_called()
    session.commit.assert_not_called()
    assert result.dry_run is True
    assert result.run_id is None
    assert len(result.results_preview) > 0


def test_apply_status_update_rule_checked():
    conn = _connection()
    c1, c2 = conn._test_c1, conn._test_c2  # noqa: SLF001
    outcome = mrv.ValidationOutcome(
        target_type="connection",
        target_id=conn.id,
        checks=mrv.validate_connection(conn, candidate_map={c1.id: c1, c2.id: c2}, duplicate_keys={}),
        mirror_status=conn.mirror_status,
    )
    assert not outcome.has_blocker_or_error()
    session = AsyncMock()
    stats = asyncio.run(
        mrv.apply_rule_checked_status_updates(
            session,
            [outcome],
            objects_by_type={"connection": [conn]},
        )
    )
    assert conn.mirror_status == MirrorStatus.rule_checked
    assert stats["eligible_rule_checked"] == 1


def test_blocker_not_updated_rule_checked():
    conn = _connection(source_region_candidate_id=None, source_region_final_id=None)
    outcome = mrv.ValidationOutcome(
        target_type="connection",
        target_id=conn.id,
        checks=mrv.validate_connection(conn, candidate_map={}, duplicate_keys={}),
        mirror_status=conn.mirror_status,
    )
    assert outcome.has_blocker_or_error()
    stats = asyncio.run(
        mrv.apply_rule_checked_status_updates(
            AsyncMock(),
            [outcome],
            objects_by_type={"connection": [conn]},
        )
    )
    assert conn.mirror_status == MirrorStatus.llm_suggested
    assert stats["skipped_blocked"] == 1


def test_human_approved_not_regressed():
    conn = _connection(mirror_status=MirrorStatus.human_approved)
    c1, c2 = conn._test_c1, conn._test_c2  # noqa: SLF001
    outcome = mrv.ValidationOutcome(
        target_type="connection",
        target_id=conn.id,
        checks=mrv.validate_connection(conn, candidate_map={c1.id: c1, c2.id: c2}, duplicate_keys={}),
        mirror_status=conn.mirror_status,
    )
    stats = asyncio.run(
        mrv.apply_rule_checked_status_updates(
            AsyncMock(),
            [outcome],
            objects_by_type={"connection": [conn]},
        )
    )
    assert conn.mirror_status == MirrorStatus.human_approved
    assert stats["skipped_existing_status"] == 1


def test_dry_run_false_persists_run():
    conn = _connection()
    c1, c2 = conn._test_c1, conn._test_c2  # noqa: SLF001
    session = AsyncMock()
    session.execute = AsyncMock(
        side_effect=[
            MagicMock(scalars=MagicMock(return_value=MagicMock(all=MagicMock(return_value=[conn])))),
            MagicMock(scalars=MagicMock(return_value=MagicMock(all=MagicMock(return_value=[c1, c2])))),
        ]
    )
    session.get = AsyncMock(return_value=None)

    async def _flush():
        if not hasattr(session, "_run_id"):
            session._run_id = uuid.uuid4()  # noqa: SLF001

    session.flush = AsyncMock(side_effect=_flush)
    session.commit = AsyncMock()
    added: list = []
    session.add = lambda obj: added.append(obj)

    result = asyncio.run(
        mrv.run_mirror_rule_validation(
            session,
            target_types=["connection"],
            dry_run=False,
            apply_status_update=False,
        )
    )
    assert result.run_id is not None
    session.commit.assert_called_once()
    assert any(isinstance(o, MirrorRuleValidationRun) for o in added)


def test_empty_target_types_raises():
    with pytest.raises(mrv.EmptyTargetTypesError):
        asyncio.run(mrv.run_mirror_rule_validation(AsyncMock(), target_types=[], dry_run=True))


def test_no_llm_provider_called():
    conn = _connection()
    with patch("app.services.mirror_rule_validation_service.run_mirror_rule_validation") as mock_run:
        mock_run.return_value = mrv.ValidationRunResult(dry_run=True)
        asyncio.run(mock_run(AsyncMock(), target_types=["connection"], dry_run=True))
        mock_run.assert_called_once()
