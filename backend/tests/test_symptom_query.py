"""Tests for POST /api/symptom-query/conversation — mocked LLM, no real DeepSeek."""

from __future__ import annotations

import json
from unittest.mock import AsyncMock

from fastapi.testclient import TestClient

from app.main import app
from app.services.llm_providers.base import LlmProviderResponse, LlmProviderUsage


def _mock_provider(parsed_json: dict) -> AsyncMock:
    """Build an AsyncMock provider whose complete_json returns a given parsed_json."""
    provider = AsyncMock()
    provider.complete_json.return_value = LlmProviderResponse(
        provider="deepseek",
        model="test-model",
        raw_text=json.dumps(parsed_json, ensure_ascii=False),
        parsed_json=parsed_json,
        usage=LlmProviderUsage(),
        finish_reason="stop",
        request_payload_redacted={},
        response_payload={},
        latency_ms=0,
    )
    return provider


def test_conversation_asking_stage(monkeypatch):
    """LLM returns asking stage — endpoint responds with a follow-up question."""
    mock_provider = _mock_provider({
        "stage": "asking",
        "content": "Do you have tinnitus?",
        "summary": None,
    })
    monkeypatch.setattr(
        "app.routers.symptom_query.get_llm_provider",
        lambda _name: mock_provider,
    )

    client = TestClient(app)
    resp = client.post("/api/symptom-query/conversation", json={
        "messages": [
            {"role": "user", "content": "I have dizziness when I stand up."},
        ],
        "granularity_level": "macro",
    })

    assert resp.status_code == 200
    data = resp.json()
    assert data["stage"] == "asking"
    assert data["content"] == "Do you have tinnitus?"
    assert data["summary"] is None


def test_conversation_empty_messages_returns_asking():
    """Empty messages list triggers early return with an asking response."""
    client = TestClient(app)
    resp = client.post("/api/symptom-query/conversation", json={
        "messages": [],
        "granularity_level": "macro",
    })
    assert resp.status_code == 200
    data = resp.json()
    assert data["stage"] == "asking"
    assert data["content"] is not None


def test_conversation_llm_failure_fallback(monkeypatch):
    """LLM failure triggers graceful fallback using raw user messages as summary."""
    mock_provider = AsyncMock()
    mock_provider.complete_json = AsyncMock(side_effect=Exception("LLM down"))
    monkeypatch.setattr(
        "app.routers.symptom_query.get_llm_provider",
        lambda name: mock_provider,
    )
    monkeypatch.setattr(
        "app.routers.symptom_query.get_deepseek_runtime_config",
        lambda: type("C", (), {"api_key": "sk-test", "default_model": "deepseek-chat"})(),
    )

    client = TestClient(app)
    resp = client.post("/api/symptom-query/conversation", json={
        "messages": [{"role": "user", "content": "I feel dizzy"}],
        "granularity_level": "macro",
    })
    assert resp.status_code == 200
    data = resp.json()
    assert data["stage"] == "summarizing"
    assert "dizzy" in (data["summary"] or "").lower()


# ── Graph — integration test with real DB ─────────────────────────────────────


def test_graph_returns_step_level_nodes():
    """Integration: insert circuits+steps with region_candidate_id, verify graph structure.

    Nodes include brain_region type with real region labels and step_order.
    Edges include step_flow (between consecutive steps) and belongs_to (step->circuit).
    co_occurs edges connect brain_region nodes of steps from different circuits
    sharing the same region_candidate_id.
    """
    import asyncio
    import uuid

    from sqlalchemy import text

    from app.database import AsyncSessionLocal
    from fastapi.testclient import TestClient
    from app.main import app

    # ── Test data UUIDs ────────────────────────────────────────────────────
    circuit_a_id = uuid.uuid4()
    circuit_b_id = uuid.uuid4()
    region_1_id = uuid.uuid4()
    region_2_id = uuid.uuid4()
    region_3_id = uuid.uuid4()  # shared by both circuits -> co_occurs

    step_a1_id = uuid.uuid4()
    step_a2_id = uuid.uuid4()
    step_b1_id = uuid.uuid4()
    step_b2_id = uuid.uuid4()

    # Shared synthetic FK targets (these tables exist but we only need IDs)
    _gen_run_id = uuid.uuid4()
    _batch_id = uuid.uuid4()
    _resource_id = uuid.uuid4()
    _parse_run_id = uuid.uuid4()
    _file_id = uuid.uuid4()

    async def _setup():
        async with AsyncSessionLocal() as session:
            # Bypass FK checks during test setup — synthetic IDs are unique
            # and always cleaned up, so referential integrity is not at risk.
            await session.execute(text("SET session_replication_role = replica"))

            # ── candidate_brain_regions ─────────────────────────────────────
            regions = [
                (region_1_id, "Precentral_L", "Precentral_L",
                 "Precentral Gyrus Left", "precentral gyrus"),
                (region_2_id, "Postcentral_R", "Postcentral_R",
                 "Postcentral Gyrus Right", "postcentral gyrus"),
                (region_3_id, "Thalamus_L", "Thalamus_L",
                 "Thalamus Left", "thalamus"),
            ]
            for rid, en_name, raw_name, base_name, std_name in regions:
                await session.execute(text("""
                    INSERT INTO candidate_brain_regions
                        (id, generation_run_id, batch_id, resource_id,
                         parse_run_id, source_raw_label_id, source_raw_table,
                         source_file_id, source_atlas, source_version,
                         raw_name, en_name, std_name, region_base_name,
                         granularity_level, granularity_family,
                         candidate_status, raw_payload, row_index)
                    VALUES
                        (:id, :gen_run, :batch, :res,
                         :parse_run, :src_label, :src_table,
                         :file_id, :atlas, :ver,
                         :raw, :en, :std, :base,
                         :gran, :family,
                         'candidate_created', '{}'::jsonb, 0)
                """), {
                    "id": rid, "gen_run": _gen_run_id, "batch": _batch_id,
                    "res": _resource_id, "parse_run": _parse_run_id,
                    "src_label": uuid.uuid4(), "src_table": "raw_aal3_region_labels",
                    "file_id": _file_id, "atlas": "AAL3", "ver": "v1",
                    "raw": raw_name, "en": en_name, "std": std_name,
                    "base": base_name, "gran": "macro", "family": "macro_clinical",
                })

            # ── mirror_region_circuits ──────────────────────────────────────
            for cid, cname, ctype in [(circuit_a_id, "Motor Circuit A", "motor_circuit"),
                                       (circuit_b_id, "Sensory Circuit B", "sensory_circuit")]:
                await session.execute(text("""
                    INSERT INTO mirror_region_circuits
                        (id, circuit_name, circuit_type,
                         granularity_level, granularity_family,
                         source_atlas, source_version,
                         mirror_status, review_status, promotion_status,
                         raw_payload_json, normalized_payload_json)
                    VALUES
                        (:id, :name, :ctype,
                         :gran, :family,
                         :atlas, :ver,
                         'llm_suggested', 'pending', 'not_promoted',
                         '{}'::jsonb, '{}'::jsonb)
                """), {
                    "id": cid, "name": cname, "ctype": ctype,
                    "gran": "macro", "family": "macro_clinical",
                    "atlas": "AAL3", "ver": "v1",
                })

            # ── mirror_circuit_steps ────────────────────────────────────────
            steps = [
                (step_a1_id, circuit_a_id, region_1_id, 1, "Precentral", "source", "region"),
                (step_a2_id, circuit_a_id, region_3_id, 2, "Thalamus",   "relay", "relay"),
                (step_b1_id, circuit_b_id, region_3_id, 1, "Thalamus",   "source", "region"),
                (step_b2_id, circuit_b_id, region_2_id, 2, "Postcentral", "target", "region"),
            ]
            for sid, cid, rid, order, sname, role, stype in steps:
                await session.execute(text("""
                    INSERT INTO mirror_circuit_steps
                        (id, circuit_id, region_candidate_id,
                         step_order, step_name, step_type, role,
                         granularity_level, granularity_family,
                         source_atlas, source_version,
                         mirror_status, review_status, promotion_status,
                         raw_payload_json, normalized_payload_json)
                    VALUES
                        (:id, :cid, :rid,
                         :ord, :sname, :stype, :role,
                         :gran, :family,
                         :atlas, :ver,
                         'llm_suggested', 'pending', 'not_promoted',
                         '{}'::jsonb, '{}'::jsonb)
                """), {
                    "id": sid, "cid": cid, "rid": rid,
                    "ord": order, "sname": sname, "stype": stype, "role": role,
                    "gran": "macro", "family": "macro_clinical",
                    "atlas": "AAL3", "ver": "v1",
                })
            await session.execute(text("SET session_replication_role = DEFAULT"))
            await session.commit()

    async def _teardown():
        async with AsyncSessionLocal() as session:
            for sid in (step_a1_id, step_a2_id, step_b1_id, step_b2_id):
                await session.execute(
                    text("DELETE FROM mirror_circuit_steps WHERE id = :id"), {"id": sid})
            for cid in (circuit_a_id, circuit_b_id):
                await session.execute(
                    text("DELETE FROM mirror_region_circuits WHERE id = :id"), {"id": cid})
            for rid in (region_1_id, region_2_id, region_3_id):
                await session.execute(
                    text("DELETE FROM candidate_brain_regions WHERE id = :id"), {"id": rid})
            await session.commit()

    loop = asyncio.new_event_loop()
    asyncio.set_event_loop(loop)
    try:
        loop.run_until_complete(_setup())

        client = TestClient(app)
        resp = client.post("/api/symptom-query/graph", json={
            "circuit_ids": [str(circuit_a_id), str(circuit_b_id)],
            "granularity_level": "macro",
        })

        assert resp.status_code == 200, resp.text
        data = resp.json()

        # ── Assert nodes ────────────────────────────────────────────────────
        nodes = data["nodes"]
        assert len(nodes) >= 6, f"expected >=6 nodes, got {len(nodes)}"

        circuit_nodes = [n for n in nodes if n["type"] == "circuit"]
        region_nodes = [n for n in nodes if n["type"] == "brain_region"]

        assert len(circuit_nodes) == 2, f"expected 2 circuit nodes, got {len(circuit_nodes)}"
        assert len(region_nodes) == 4, f"expected 4 brain_region nodes, got {len(region_nodes)}"

        circuit_a_node = next(n for n in circuit_nodes if n["label"] == "Motor Circuit A")
        assert circuit_a_node["id"] == str(circuit_a_id)

        region_labels = {n["label"] for n in region_nodes}
        assert "Precentral_L" in region_labels, f"missing Precentral_L in {region_labels}"
        assert "Postcentral_R" in region_labels, f"missing Postcentral_R in {region_labels}"
        assert "Thalamus_L" in region_labels, f"missing Thalamus_L in {region_labels}"

        # Check step metadata on region nodes
        precentral_nodes = [n for n in region_nodes if n["label"] == "Precentral_L"]
        assert len(precentral_nodes) == 1
        pn = precentral_nodes[0]
        assert pn.get("circuit_id") == str(circuit_a_id)
        assert pn.get("step_order") == 1
        assert pn.get("role") == "source"
        assert pn.get("step_name") == "Precentral"

        # ── Assert edges ────────────────────────────────────────────────────
        edges = data["edges"]

        step_flow_edges = [e for e in edges if e.get("label") == "step_flow"]
        assert len(step_flow_edges) >= 2, f"expected >=2 step_flow edges, got {len(step_flow_edges)}"

        belongs_to_edges = [e for e in edges if e.get("label") == "belongs_to"]
        assert len(belongs_to_edges) >= 4, f"expected >=4 belongs_to edges, got {len(belongs_to_edges)}"

        co_occurs_edges = [e for e in edges if e.get("label") == "co_occurs"]
        assert len(co_occurs_edges) >= 1, (
            f"expected >=1 co_occurs edge (Thalamus shared), got {len(co_occurs_edges)}"
        )

    finally:
        loop.run_until_complete(_teardown())
        loop.close()


def test_conversation_summarizing_stage(monkeypatch):
    """LLM returns summarizing stage — endpoint responds with a clinical summary."""
    mock_provider = _mock_provider({
        "stage": "summarizing",
        "content": None,
        "summary": "Vestibular symptoms suggestive of BPPV",
    })
    monkeypatch.setattr(
        "app.routers.symptom_query.get_llm_provider",
        lambda _name: mock_provider,
    )

    client = TestClient(app)
    resp = client.post("/api/symptom-query/conversation", json={
        "messages": [
            {"role": "user", "content": "I have dizziness when I stand up."},
            {"role": "assistant", "content": "Does the room spin or do you feel faint?"},
            {"role": "user", "content": "The room spins for about 30 seconds."},
        ],
        "granularity_level": "macro",
    })

    assert resp.status_code == 200
    data = resp.json()
    assert data["stage"] == "summarizing"
    assert data["content"] is None
    assert data["summary"] == "Vestibular symptoms suggestive of BPPV"
