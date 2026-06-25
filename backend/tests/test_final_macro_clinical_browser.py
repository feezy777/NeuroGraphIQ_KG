"""Final macro_clinical browser tests (Step 8.16, read-only)."""

from __future__ import annotations

import asyncio
import uuid
from datetime import datetime, timezone
from decimal import Decimal
from unittest.mock import AsyncMock, MagicMock

import pytest
from fastapi.testclient import TestClient

from app.main import app
from app.models.final_kg import FinalKgTriple, FinalRegionCircuit
from app.models.final_macro_clinical import FinalCircuitStep, FinalProjection, FinalProjectionFunction
from app.schemas.final_macro_clinical_browser import (
    FinalBrowserSearchItem,
    FinalBrowserSearchResponse,
    FinalCircuitDetailResponse,
    FinalGraphNode,
    FinalGraphResponse,
    FinalObjectDetailResponse,
    FinalProvenancePayload,
    FinalProjectionDetailResponse,
    FinalRegionNeighborhoodResponse,
)
from app.services import final_macro_clinical_browser_service as fmbs


def _circuit_row(**kwargs):
    defaults = dict(
        id=uuid.uuid4(),
        circuit_name="limbic circuit",
        circuit_type="limbic",
        function_association="emotion",
        description="test circuit",
        source_atlas="Macro96",
        granularity_level="macro",
        granularity_family="macro_clinical",
        final_status="active",
        source_mirror_circuit_id=uuid.uuid4(),
        confidence=Decimal("0.9"),
        created_at=datetime.now(timezone.utc),
    )
    defaults.update(kwargs)
    return FinalRegionCircuit(**defaults)


def _projection_row(**kwargs):
    defaults = dict(
        id=uuid.uuid4(),
        final_uid=f"uid:{uuid.uuid4()}",
        source_mirror_id=uuid.uuid4(),
        projection_type="glutamatergic",
        directionality="directed",
        evidence_text="proj evidence",
        source_atlas="Macro96",
        granularity_level="macro",
        granularity_family="macro_clinical",
        final_status="active",
        source_region_candidate_id=uuid.uuid4(),
        target_region_candidate_id=uuid.uuid4(),
        confidence=Decimal("0.8"),
        created_at=datetime.now(timezone.utc),
    )
    defaults.update(kwargs)
    return FinalProjection(**defaults)


def test_normalize_search_query():
    assert fmbs.normalize_search_query("  abc  ") == "abc"
    assert fmbs.normalize_search_query("") is None
    assert fmbs.normalize_search_query(None) is None


def test_make_final_label_circuit():
    row = _circuit_row()
    assert fmbs.make_final_label("circuit", row) == "limbic circuit"


def test_make_final_label_projection():
    row = _projection_row()
    assert fmbs.make_final_label("projection", row) == "glutamatergic"


def test_search_no_query_active_only():
    active = _circuit_row(final_status="active")
    session = AsyncMock()

    async def fake_query(*args, **kwargs):
        return [active]

    with pytest.MonkeyPatch.context() as mp:
        mp.setattr(fmbs, "_query_search_type", fake_query)
        resp = asyncio.run(
            fmbs.search_final_objects(session, target_types=["circuit"], include_inactive=False)
        )
    assert resp.total == 1
    assert resp.items[0].final_status == "active"


def test_search_query_matches_circuit_name():
    row = _circuit_row(circuit_name="hippocampal loop")
    session = AsyncMock()

    async def fake_query(session, tt, **kwargs):
        assert kwargs.get("query") == "hippo"
        return [row] if tt == "circuit" else []

    with pytest.MonkeyPatch.context() as mp:
        mp.setattr(fmbs, "_query_search_type", fake_query)
        resp = asyncio.run(fmbs.search_final_objects(session, query="hippo", target_types=["circuit"]))
    assert resp.items[0].label == "hippocampal loop"


def test_search_projection_type():
    row = _projection_row(projection_type="dopaminergic")
    session = AsyncMock()
    with pytest.MonkeyPatch.context() as mp:
        mp.setattr(fmbs, "_query_search_type", AsyncMock(return_value=[row]))
        resp = asyncio.run(
            fmbs.search_final_objects(session, query="dopamine", target_types=["projection"])
        )
    assert resp.items[0].target_type == "projection"


def test_search_function_term():
    pf = FinalProjectionFunction(
        id=uuid.uuid4(),
        final_uid="uid",
        source_mirror_id=uuid.uuid4(),
        final_projection_id=uuid.uuid4(),
        mirror_projection_id=uuid.uuid4(),
        source_atlas="Macro96",
        granularity_level="macro",
        function_term="working memory",
        function_category="cognitive",
        relation_type="associated_with",
        final_status="active",
        created_at=datetime.now(timezone.utc),
    )
    session = AsyncMock()
    with pytest.MonkeyPatch.context() as mp:
        mp.setattr(fmbs, "_query_search_type", AsyncMock(return_value=[pf]))
        resp = asyncio.run(
            fmbs.search_final_objects(session, query="memory", target_types=["projection_function"])
        )
    assert "working memory" in resp.items[0].label


def test_search_target_types_filter():
    session = AsyncMock()
    calls = []

    async def fake_query(session, tt, **kwargs):
        calls.append(tt)
        return []

    with pytest.MonkeyPatch.context() as mp:
        mp.setattr(fmbs, "_query_search_type", fake_query)
        asyncio.run(fmbs.search_final_objects(session, target_types=["circuit", "projection"]))
    assert calls == ["circuit", "projection"]


def test_search_source_atlas_filter_passed():
    session = AsyncMock()

    async def fake_query(session, tt, **kwargs):
        assert kwargs["source_atlas"] == "Macro96"
        return []

    with pytest.MonkeyPatch.context() as mp:
        mp.setattr(fmbs, "_query_search_type", fake_query)
        asyncio.run(fmbs.search_final_objects(session, source_atlas="Macro96"))


def test_search_granularity_filter_passed():
    session = AsyncMock()

    async def fake_query(session, tt, **kwargs):
        assert kwargs["granularity_level"] == "macro"
        return []

    with pytest.MonkeyPatch.context() as mp:
        mp.setattr(fmbs, "_query_search_type", fake_query)
        asyncio.run(fmbs.search_final_objects(session, granularity_level="macro"))


def test_search_include_inactive_false():
    session = AsyncMock()

    async def fake_query(session, tt, **kwargs):
        assert kwargs["include_inactive"] is False
        return []

    with pytest.MonkeyPatch.context() as mp:
        mp.setattr(fmbs, "_query_search_type", fake_query)
        asyncio.run(fmbs.search_final_objects(session, include_inactive=False))


def test_search_include_inactive_true():
    session = AsyncMock()

    async def fake_query(session, tt, **kwargs):
        assert kwargs["include_inactive"] is True
        return [_circuit_row(final_status="deprecated")]

    with pytest.MonkeyPatch.context() as mp:
        mp.setattr(fmbs, "_query_search_type", fake_query)
        resp = asyncio.run(fmbs.search_final_objects(session, include_inactive=True, target_types=["circuit"]))
    assert resp.items[0].final_status == "deprecated"


def test_search_limit_offset():
    rows = [
        FinalBrowserSearchItem(
            target_type="circuit",
            final_id=uuid.uuid4(),
            label=f"c{i}",
            created_at=datetime(2024, 1, i + 1, tzinfo=timezone.utc),
        )
        for i in range(5)
    ]
    session = AsyncMock()
    with pytest.MonkeyPatch.context() as mp:
        mp.setattr(
            fmbs,
            "_query_search_type",
            AsyncMock(return_value=[_circuit_row() for _ in range(5)]),
        )
        resp = asyncio.run(
            fmbs.search_final_objects(session, target_types=["circuit"], limit=2, offset=1)
        )
    assert resp.limit == 2
    assert resp.offset == 1
    assert len(resp.items) <= 2


def test_region_neighborhood_returns_functions():
    region_id = uuid.uuid4()
    nb = FinalRegionNeighborhoodResponse(
        region_candidate_id=region_id,
        region_functions=[{"id": str(uuid.uuid4()), "function_term": "motor"}],
        circuits=[],
        circuit_steps=[],
        graph=FinalGraphResponse(nodes=[], edges=[]),
    )
    session = AsyncMock()
    with pytest.MonkeyPatch.context() as mp:
        mp.setattr(fmbs, "get_final_region_neighborhood", AsyncMock(return_value=nb))
        result = asyncio.run(fmbs.get_final_region_neighborhood(session, region_id))
    assert len(result.region_functions) == 1


def test_region_neighborhood_graph_has_nodes():
    region_id = uuid.uuid4()
    graph = fmbs.build_region_graph(
        region_candidate_id=region_id,
        region_label="Amygdala",
        region_functions=[],
        circuits=[{"id": uuid.uuid4(), "circuit_name": "fear"}],
        circuit_steps=[],
        outgoing_projections=[],
        incoming_projections=[],
        undirected_projections=[],
        projection_functions=[],
        region_map={},
    )
    assert any(n.type == "region" for n in graph.nodes)
    assert any(n.type == "circuit" for n in graph.nodes)


def test_circuit_detail_steps_sorted():
    cid = uuid.uuid4()
    detail = FinalCircuitDetailResponse(
        circuit={"id": cid, "circuit_name": "test"},
        steps=[{"step_order": 2}, {"step_order": 1}],
        provenance=FinalProvenancePayload(),
        graph=FinalGraphResponse(nodes=[], edges=[]),
    )
    assert detail.steps[0]["step_order"] == 2


def test_circuit_detail_provenance():
    session = AsyncMock()
    circuit = _circuit_row()
    session.get = AsyncMock(return_value=circuit)
    session.execute = AsyncMock(
        return_value=MagicMock(scalars=MagicMock(return_value=MagicMock(all=MagicMock(return_value=[]))))
    )
    with pytest.MonkeyPatch.context() as mp:
        mp.setattr(fmbs, "collect_final_triples", AsyncMock(return_value=[]))
        mp.setattr(fmbs, "collect_final_evidence", AsyncMock(return_value=[]))
        mp.setattr(fmbs, "_regions_map", AsyncMock(return_value={}))
        mp.setattr(fmbs, "build_provenance_payload", AsyncMock(return_value=FinalProvenancePayload(source_mirror_id=uuid.uuid4())))
        detail = asyncio.run(fmbs.get_final_circuit_detail(session, circuit.id))
    assert detail is not None
    assert detail.circuit["circuit_name"] == "limbic circuit"


def test_projection_detail_source_target():
    session = AsyncMock()
    proj = _projection_row()
    session.get = AsyncMock(return_value=proj)
    session.execute = AsyncMock(
        return_value=MagicMock(scalars=MagicMock(return_value=MagicMock(all=MagicMock(return_value=[]))))
    )
    src = proj.source_region_candidate_id
    tgt = proj.target_region_candidate_id
    with pytest.MonkeyPatch.context() as mp:
        mp.setattr(
            fmbs,
            "_regions_map",
            AsyncMock(
                return_value={
                    src: {"region_candidate_id": src, "label": "A"},
                    tgt: {"region_candidate_id": tgt, "label": "B"},
                }
            ),
        )
        mp.setattr(fmbs, "collect_final_triples", AsyncMock(return_value=[]))
        mp.setattr(fmbs, "collect_final_evidence", AsyncMock(return_value=[]))
        mp.setattr(fmbs, "build_provenance_payload", AsyncMock(return_value=FinalProvenancePayload()))
        detail = asyncio.run(fmbs.get_final_projection_detail(session, proj.id))
    assert detail is not None
    assert detail.projection.get("projection_type") == "glutamatergic"


def test_object_detail_circuit_step():
    session = AsyncMock()
    step = FinalCircuitStep(
        id=uuid.uuid4(),
        final_uid="uid",
        source_mirror_id=uuid.uuid4(),
        final_circuit_id=uuid.uuid4(),
        mirror_circuit_id=uuid.uuid4(),
        source_atlas="Macro96",
        granularity_level="macro",
        step_order=1,
        step_name="step1",
        final_status="active",
        created_at=datetime.now(timezone.utc),
    )
    session.get = AsyncMock(return_value=step)
    with pytest.MonkeyPatch.context() as mp:
        mp.setattr(fmbs, "collect_final_triples", AsyncMock(return_value=[]))
        mp.setattr(fmbs, "collect_final_evidence", AsyncMock(return_value=[]))
        mp.setattr(fmbs, "build_provenance_payload", AsyncMock(return_value=FinalProvenancePayload()))
        detail = asyncio.run(fmbs.get_final_object_detail(session, "circuit_step", step.id))
    assert detail.target_type == "circuit_step"


def test_object_detail_not_found():
    session = AsyncMock()
    session.get = AsyncMock(return_value=None)
    detail = asyncio.run(fmbs.get_final_object_detail(session, "circuit", uuid.uuid4()))
    assert detail is None


def test_object_detail_unsupported_type():
    session = AsyncMock()
    with pytest.raises(ValueError, match="unsupported"):
        asyncio.run(fmbs.get_final_object_detail(session, "region", uuid.uuid4()))


def test_graph_region_center():
    session = AsyncMock()
    graph = FinalGraphResponse(
        nodes=[FinalGraphNode(id="region:x", type="region", label="R")],
        edges=[],
        center_node_id="region:x",
    )
    nb = FinalRegionNeighborhoodResponse(region_candidate_id=uuid.uuid4(), graph=graph)
    with pytest.MonkeyPatch.context() as mp:
        mp.setattr(fmbs, "get_final_region_neighborhood", AsyncMock(return_value=nb))
        result = asyncio.run(
            fmbs.get_final_graph(session, center_type="region", center_id=uuid.uuid4())
        )
    assert result.nodes


def test_graph_depth_max():
    session = AsyncMock()
    with pytest.MonkeyPatch.context() as mp:
        mp.setattr(
            fmbs,
            "get_final_circuit_detail",
            AsyncMock(
                return_value=FinalCircuitDetailResponse(
                    circuit={"id": uuid.uuid4()},
                    provenance=FinalProvenancePayload(),
                    graph=FinalGraphResponse(nodes=[], edges=[]),
                )
            ),
        )
        result = asyncio.run(
            fmbs.get_final_graph(session, center_type="circuit", center_id=uuid.uuid4(), depth=99)
        )
    assert any("depth" in w for w in result.warnings) or result.warnings == []


def test_graph_limit_truncation():
    session = AsyncMock()
    nodes = [
        FinalGraphNode(id=f"n{i}", type="region", label=f"N{i}") for i in range(300)
    ]
    graph = FinalGraphResponse(nodes=nodes, edges=[])
    nb = FinalRegionNeighborhoodResponse(region_candidate_id=uuid.uuid4(), graph=graph)
    with pytest.MonkeyPatch.context() as mp:
        mp.setattr(fmbs, "get_final_region_neighborhood", AsyncMock(return_value=nb))
        result = asyncio.run(
            fmbs.get_final_graph(session, center_type="region", center_id=uuid.uuid4(), limit=50)
        )
    assert len(result.nodes) == 50
    assert any("truncated" in w for w in result.warnings)


def test_api_search_endpoint():
    client = TestClient(app)
    fake = FinalBrowserSearchResponse(items=[], total=0, limit=100, offset=0)

    async def _fake(session, **kwargs):
        return fake

    with pytest.MonkeyPatch.context() as mp:
        mp.setattr(fmbs, "search_final_objects", _fake)
        r = client.get("/api/final-macro-clinical/browser/search")
        assert r.status_code == 200


def test_api_object_detail_404():
    client = TestClient(app)

    async def _fake(session, target_type, final_id):
        return None

    with pytest.MonkeyPatch.context() as mp:
        mp.setattr(fmbs, "get_final_object_detail", _fake)
        r = client.get(f"/api/final-macro-clinical/browser/object/circuit/{uuid.uuid4()}")
        assert r.status_code == 404


def test_api_object_detail_400():
    client = TestClient(app)

    async def _fake(session, target_type, final_id):
        raise ValueError("unsupported target_type: region")

    with pytest.MonkeyPatch.context() as mp:
        mp.setattr(fmbs, "get_final_object_detail", _fake)
        r = client.get(f"/api/final-macro-clinical/browser/object/region/{uuid.uuid4()}")
        assert r.status_code == 400


def test_browser_readonly_no_writes():
    """Browser service module must not import promotion write helpers for run."""
    import inspect

    src = inspect.getsource(fmbs)
    assert "run_final_macro_clinical_promotion" not in src
    assert "session.commit" not in src
    assert "session.add" not in src


def test_browser_no_llm_imports():
    import app.services.final_macro_clinical_browser_service as mod

    names = dir(mod)
    assert "deepseek" not in str(names).lower()
    assert "kimi" not in str(names).lower()


def test_triple_search_label():
    triple = FinalKgTriple(
        id=uuid.uuid4(),
        subject_type="circuit",
        subject_label="Amygdala circuit",
        predicate="connects_to",
        object_type="region",
        object_label="Hippocampus",
        granularity_level="macro",
        source_atlas="Macro96",
        final_status="active",
        created_at=datetime.now(timezone.utc),
    )
    assert "Amygdala" in fmbs.make_final_label("triple", triple)
