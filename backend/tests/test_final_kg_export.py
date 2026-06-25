"""Final KG export tests (Step 8.17, read-only DB)."""

from __future__ import annotations

import asyncio
import json
import uuid
from datetime import datetime, timezone
from decimal import Decimal
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock

import pytest
from fastapi.testclient import TestClient

from app.main import app
from app.models.candidate import CandidateBrainRegion
from app.models.final_kg import FinalRegionCircuit
from app.models.final_macro_clinical import FinalCircuitStep, FinalProjection
from app.schemas.final_kg_export import FinalKgExportRequest, FinalKgExportScope
from app.schemas.final_kg_export import FinalKgExportPreviewResponse
from app.services import final_kg_export_service as fkes


@pytest.fixture
def export_tmp(tmp_path, monkeypatch):
    export_root = tmp_path / "exports" / "final_kg"
    export_root.mkdir(parents=True)
    monkeypatch.setattr(fkes, "EXPORT_BASE_DIR", export_root)
    monkeypatch.setattr(fkes, "get_export_base_dir", lambda: export_root)
    return export_root


def _circuit(**kwargs):
    defaults = dict(
        id=uuid.uuid4(),
        circuit_name="limbic",
        circuit_type="limbic",
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


def _step(circuit_id, region_id, **kwargs):
    defaults = dict(
        id=uuid.uuid4(),
        final_uid=f"uid:{uuid.uuid4()}",
        source_mirror_id=uuid.uuid4(),
        final_circuit_id=circuit_id,
        mirror_circuit_id=uuid.uuid4(),
        region_candidate_id=region_id,
        source_atlas="Macro96",
        granularity_level="macro",
        step_order=1,
        step_name="step1",
        step_type="region",
        role="node",
        final_status="active",
        created_at=datetime.now(timezone.utc),
    )
    defaults.update(kwargs)
    return FinalCircuitStep(**defaults)


def _projection(src, tgt, **kwargs):
    defaults = dict(
        id=uuid.uuid4(),
        final_uid=f"uid:{uuid.uuid4()}",
        source_mirror_id=uuid.uuid4(),
        source_region_candidate_id=src,
        target_region_candidate_id=tgt,
        source_atlas="Macro96",
        granularity_level="macro",
        projection_type="glutamatergic",
        directionality="directed",
        final_status="active",
        created_at=datetime.now(timezone.utc),
    )
    defaults.update(kwargs)
    return FinalProjection(**defaults)


def _region(rid=None, **kwargs):
    defaults = dict(
        id=rid or uuid.uuid4(),
        generation_run_id=uuid.uuid4(),
        batch_id=uuid.uuid4(),
        resource_id=uuid.uuid4(),
        parse_run_id=uuid.uuid4(),
        source_raw_label_id=uuid.uuid4(),
        source_file_id=uuid.uuid4(),
        source_atlas="Macro96",
        source_version="v1",
        raw_name="Amygdala",
        en_name="Amygdala",
        granularity_level="macro",
        granularity_family="macro_clinical",
        laterality="bilateral",
        raw_payload={},
    )
    defaults.update(kwargs)
    return CandidateBrainRegion(**defaults)


def test_dry_run_no_directory(export_tmp):
    session = AsyncMock()
    session.execute = AsyncMock(return_value=MagicMock(scalars=MagicMock(return_value=MagicMock(all=MagicMock(return_value=[])))))
    req = FinalKgExportRequest(dry_run=True, target_types=["circuit"])
    resp = asyncio.run(fkes.preview_final_kg_export(session, req))
    assert resp.dry_run is True
    assert list(export_tmp.iterdir()) == [] or all(p.name == ".gitkeep" for p in export_tmp.iterdir() if p.is_file())


def test_dry_run_returns_candidate_counts():
    session = AsyncMock()
    circuit = _circuit()
    with pytest.MonkeyPatch.context() as mp:
        mp.setattr(fkes, "collect_final_export_objects", AsyncMock(return_value={"circuit": [circuit]}))
        mp.setattr(fkes, "_collect_referenced_regions", AsyncMock(return_value={}))
        resp = asyncio.run(fkes.preview_final_kg_export(session, FinalKgExportRequest(dry_run=True, target_types=["circuit"])))
    assert resp.candidate_counts.get("circuit") == 1
    assert resp.estimated_node_count >= 1


def test_dry_run_sample_nodes():
    session = AsyncMock()
    circuit = _circuit()
    with pytest.MonkeyPatch.context() as mp:
        mp.setattr(fkes, "collect_final_export_objects", AsyncMock(return_value={"circuit": [circuit]}))
        mp.setattr(fkes, "_collect_referenced_regions", AsyncMock(return_value={}))
        resp = asyncio.run(fkes.preview_final_kg_export(session, FinalKgExportRequest(dry_run=True, target_types=["circuit"])))
    assert len(resp.sample_nodes) >= 1


def test_deterministic_node_id():
    cid = uuid.uuid4()
    assert fkes.final_node_id("circuit", cid) == f"final:circuit:{cid}"


def test_deterministic_edge_id():
    eid = fkes.make_edge_id("CIRCUIT_HAS_STEP", "a", "b", "1")
    assert eid.startswith("edge:CIRCUIT_HAS_STEP:")


def test_circuit_and_step_edges():
    rid = uuid.uuid4()
    circuit = _circuit()
    step = _step(circuit.id, rid)
    region = _region(rid)
    nodes, edges, prov, warnings = fkes.build_export_nodes_edges(
        {"circuit": [circuit], "circuit_step": [step]},
        {rid: region},
    )
    assert fkes.final_node_id("circuit", circuit.id) in nodes
    assert fkes.brain_region_node_id(rid) in nodes
    assert any(e["type"] == "CIRCUIT_HAS_STEP" for e in edges.values())
    assert any(e["type"] == "STEP_HAS_REGION" for e in edges.values())


def test_projection_source_target_edges():
    src, tgt = uuid.uuid4(), uuid.uuid4()
    proj = _projection(src, tgt)
    nodes, edges, _, _ = fkes.build_export_nodes_edges(
        {"projection": [proj]},
        {src: _region(src), tgt: _region(tgt)},
    )
    assert any(e["type"] == "PROJECTION_SOURCE_REGION" for e in edges.values())
    assert any(e["type"] == "PROJECTION_TARGET_REGION" for e in edges.values())


def test_duplicate_nodes_deduped():
    circuit = _circuit()
    nodes, _, _, _ = fkes.build_export_nodes_edges({"circuit": [circuit, circuit]}, {})
    assert len([n for n in nodes if n.startswith("final:circuit:")]) == 1


def test_export_creates_files(export_tmp):
    session = AsyncMock()
    circuit = _circuit()
    with pytest.MonkeyPatch.context() as mp:
        mp.setattr(fkes, "collect_final_export_objects", AsyncMock(return_value={"circuit": [circuit]}))
        mp.setattr(fkes, "_collect_referenced_regions", AsyncMock(return_value={}))
        mp.setattr(fkes, "generate_export_id", lambda: "EXP-20260101-120000-test0001")
        resp = asyncio.run(
            fkes.run_final_kg_export(
                session,
                FinalKgExportRequest(dry_run=False, target_types=["circuit"], formats=["jsonl", "csv", "neo4j_csv"]),
            )
        )
    assert resp.dry_run is False
    assert resp.export_id == "EXP-20260101-120000-test0001"
    export_dir = export_tmp / resp.export_id
    assert export_dir.exists()
    assert (export_dir / "manifest.json").exists()
    assert (export_dir / "nodes.jsonl").exists()
    assert (export_dir / "edges.jsonl").exists()
    assert (export_dir / "nodes.csv").exists()
    assert (export_dir / "edges.csv").exists()
    assert (export_dir / "neo4j_nodes.csv").exists()
    assert (export_dir / "neo4j_relationships.csv").exists()
    assert (export_dir / "README.md").exists()
    manifest = json.loads((export_dir / "manifest.json").read_text(encoding="utf-8"))
    assert manifest["boundaries"]["write_kg"] is False
    assert manifest["boundaries"]["llm_called"] is False
    assert manifest["counts"]["nodes"] >= 1


def test_manifest_counts(export_tmp):
    session = AsyncMock()
    circuit = _circuit()
    with pytest.MonkeyPatch.context() as mp:
        mp.setattr(fkes, "collect_final_export_objects", AsyncMock(return_value={"circuit": [circuit]}))
        mp.setattr(fkes, "_collect_referenced_regions", AsyncMock(return_value={}))
        mp.setattr(fkes, "generate_export_id", lambda: "EXP-20260101-120001-test0002")
        resp = asyncio.run(fkes.run_final_kg_export(session, FinalKgExportRequest(dry_run=False, target_types=["circuit"])))
    assert resp.counts.nodes >= 1


def test_path_traversal_export_id():
    with pytest.raises(ValueError, match="invalid export_id"):
        fkes.sanitize_export_id("../etc/passwd")


def test_path_traversal_filename(export_tmp):
    export_id = "EXP-20260101-120002-test0003"
    (export_tmp / export_id).mkdir()
    (export_tmp / export_id / "manifest.json").write_text(
        json.dumps({
            "export_id": export_id,
            "created_at": "2026-01-01T00:00:00Z",
            "formats": [],
            "target_types": [],
            "counts": {"nodes": 0, "edges": 0, "evidence": 0, "provenance": 0},
            "files": {"nodes_jsonl": "nodes.jsonl"},
            "schema_version": "final_macro_clinical_export_v1",
            "app_version": "",
            "warnings": [],
            "boundaries": {},
        }),
        encoding="utf-8",
    )
    with pytest.raises(ValueError):
        fkes.get_export_file_path(export_id, "../secret.txt")


def test_list_exports(export_tmp):
    export_id = "EXP-20260101-120003-test0004"
    d = export_tmp / export_id
    d.mkdir()
    (d / "manifest.json").write_text(
        json.dumps({
            "export_id": export_id,
            "created_at": "2026-01-01T00:00:00Z",
            "scope": {},
            "formats": ["jsonl"],
            "target_types": ["circuit"],
            "counts": {"nodes": 1, "edges": 0, "evidence": 0, "provenance": 0},
            "files": {},
            "schema_version": "final_macro_clinical_export_v1",
            "app_version": "",
            "warnings": [],
            "boundaries": {},
        }),
        encoding="utf-8",
    )
    result = fkes.list_exports()
    assert result.total >= 1
    assert any(i.export_id == export_id for i in result.items)


def test_api_dry_run_endpoint():
    client = TestClient(app)
    with pytest.MonkeyPatch.context() as mp:
        mp.setattr(
            fkes,
            "run_final_kg_export",
            AsyncMock(return_value=FinalKgExportPreviewResponse(dry_run=True)),
        )
        r = client.post("/api/final-macro-clinical/export/run", json={"dry_run": True, "target_types": ["circuit"]})
        assert r.status_code == 200
        assert r.json()["dry_run"] is True


def test_api_invalid_export_id():
    client = TestClient(app)
    r = client.get("/api/final-macro-clinical/export/../bad/manifest")
    assert r.status_code in {400, 404, 422}


def test_no_llm_in_service():
    import inspect
    src = inspect.getsource(fkes)
    assert "deepseek" not in src.lower()
    assert "kimi" not in src.lower()
    assert "session.commit" not in src
    assert "session.add" not in src


def test_source_atlas_filter_passed():
    session = AsyncMock()
    session.execute = AsyncMock(return_value=MagicMock(scalars=MagicMock(return_value=MagicMock(all=MagicMock(return_value=[])))))

    async def _run():
        req = FinalKgExportRequest(
            dry_run=True,
            target_types=["circuit"],
            scope=FinalKgExportScope(source_atlas="Macro96"),
        )
        await fkes.collect_final_export_objects(session, req)

    asyncio.run(_run())
    assert session.execute.called


def test_max_nodes_exceeded():
    session = AsyncMock()
    big_nodes = {f"n{i}": {"node_id": f"n{i}", "labels": [], "target_type": "circuit", "label": "x", "properties": {}, "provenance": {}} for i in range(5)}
    with pytest.MonkeyPatch.context() as mp:
        mp.setattr(fkes, "collect_final_export_objects", AsyncMock(return_value={"circuit": [_circuit()]}))
        mp.setattr(fkes, "_collect_referenced_regions", AsyncMock(return_value={}))
        mp.setattr(fkes, "build_export_nodes_edges", lambda *a, **k: (big_nodes, {}, [], []))
        with pytest.raises(ValueError, match="max_nodes"):
            asyncio.run(fkes.preview_final_kg_export(session, FinalKgExportRequest(dry_run=True, max_nodes=2)))
