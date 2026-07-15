"""Tests for POST /api/symptom-query/conversation — mocked LLM, no real DeepSeek."""

from __future__ import annotations

import json
from unittest.mock import AsyncMock

import pytest
from fastapi.testclient import TestClient
from sqlalchemy.exc import DBAPIError

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


def test_graph_returns_circuit_owned_region_graph():
    """Integration: graph contains only circuit regions and circuit-owned edges."""
    import asyncio
    import uuid

    from sqlalchemy import text

    from app.database import AsyncSessionLocal
    from fastapi.testclient import TestClient
    from app.main import app

    # ── Test data UUIDs ────────────────────────────────────────────────────
    circuit_a_id = uuid.uuid4()
    circuit_b_id = uuid.uuid4()
    circuit_c_id = uuid.uuid4()
    circuit_d_id = uuid.uuid4()
    region_1_id = uuid.uuid4()
    region_2_id = uuid.uuid4()
    region_3_id = uuid.uuid4()  # shared by both circuits

    step_a1_id = uuid.uuid4()
    step_a2_id = uuid.uuid4()
    step_a3_id = uuid.uuid4()
    step_b1_id = uuid.uuid4()
    step_b2_id = uuid.uuid4()
    step_c1_id = uuid.uuid4()  # unresolved region, single-step boundary case
    step_d1_id = uuid.uuid4()
    step_d2_id = uuid.uuid4()
    connection_a_id = uuid.uuid4()
    connection_b_id = uuid.uuid4()
    connection_extra_id = uuid.uuid4()
    membership_a_id = uuid.uuid4()
    membership_extra_id = uuid.uuid4()

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
            try:
                await session.execute(text("SET session_replication_role = replica"))
            except DBAPIError:
                await session.rollback()
                pytest.skip("graph integration test requires a PostgreSQL test role with replication privilege")

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
            for cid, cname, ctype in [
                (circuit_a_id, "Motor Circuit A", "motor_circuit"),
                (circuit_b_id, "Sensory Circuit B", "sensory_circuit"),
                (circuit_c_id, "Unresolved Circuit C", "unknown"),
                (circuit_d_id, "Inferred Circuit D", "unknown"),
            ]:
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
                (step_a3_id, circuit_a_id, region_2_id, 3, "Postcentral", "target", "region"),
                (step_b1_id, circuit_b_id, region_3_id, 1, "Thalamus",   "source", "region"),
                (step_b2_id, circuit_b_id, region_2_id, 2, "Postcentral", "target", "region"),
                (step_c1_id, circuit_c_id, None, 1, "Unresolved", "source", "region"),
                (step_d1_id, circuit_d_id, region_2_id, 1, "Postcentral", "source", "region"),
                (step_d2_id, circuit_d_id, region_1_id, 2, "Precentral", "target", "region"),
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

            # Circuit A owns its projection through an explicit membership.
            # Circuit B has a real consecutive-step connection but no membership,
            # so the endpoint must attribute it through the step-pair fallback.
            for connection_id, source_id, target_id, strength in [
                (connection_a_id, region_1_id, region_3_id, "moderate"),
                (connection_b_id, region_3_id, region_2_id, "0.8"),
                (connection_extra_id, region_1_id, region_2_id, "0.7"),
            ]:
                await session.execute(text("""
                    INSERT INTO mirror_region_connections
                        (id, source_region_candidate_id, target_region_candidate_id,
                         granularity_level, granularity_family, source_atlas, source_version,
                         connection_type, directionality, strength, confidence,
                         mirror_status, review_status, promotion_status,
                         raw_payload_json, normalized_payload_json)
                    VALUES
                        (:id, :source_id, :target_id,
                         'macro', 'macro_clinical', 'AAL3', 'v1',
                         'projection', 'directed', :strength, 0.9,
                         'llm_suggested', 'pending', 'not_promoted',
                         '{}'::jsonb, '{}'::jsonb)
                """), {
                    "id": connection_id,
                    "source_id": source_id,
                    "target_id": target_id,
                    "strength": strength,
                })
            for membership_id, projection_id, source_step_id, target_step_id in [
                (membership_a_id, connection_a_id, step_a1_id, step_a2_id),
                # This membership skips the middle step and must not be rendered.
                (membership_extra_id, connection_extra_id, step_a1_id, step_a3_id),
            ]:
                await session.execute(text("""
                    INSERT INTO mirror_circuit_projection_memberships
                        (id, circuit_id, projection_id, source_step_id, target_step_id,
                         granularity_level, granularity_family, source_atlas, source_version,
                         role_in_circuit, source_method, verification_status,
                         mirror_status, review_status, promotion_status,
                         raw_payload_json, normalized_payload_json)
                    VALUES
                        (:id, :circuit_id, :projection_id, :source_step_id, :target_step_id,
                         'macro', 'macro_clinical', 'AAL3', 'v1',
                         'main_path', 'circuit_to_projection', 'circuit_supported',
                         'llm_suggested', 'pending', 'not_promoted',
                         '{}'::jsonb, '{}'::jsonb)
                """), {
                    "id": membership_id,
                    "circuit_id": circuit_a_id,
                    "projection_id": projection_id,
                    "source_step_id": source_step_id,
                    "target_step_id": target_step_id,
                })
            await session.execute(text("SET session_replication_role = DEFAULT"))
            await session.commit()

    async def _teardown():
        async with AsyncSessionLocal() as session:
            for membership_id in (membership_a_id, membership_extra_id):
                await session.execute(
                    text("DELETE FROM mirror_circuit_projection_memberships WHERE id = :id"),
                    {"id": membership_id},
                )
            for connection_id in (connection_a_id, connection_b_id, connection_extra_id):
                await session.execute(
                    text("DELETE FROM mirror_region_connections WHERE id = :id"),
                    {"id": connection_id},
                )
            for sid in (
                step_a1_id, step_a2_id, step_a3_id, step_b1_id, step_b2_id, step_c1_id,
                step_d1_id, step_d2_id,
            ):
                await session.execute(
                    text("DELETE FROM mirror_circuit_steps WHERE id = :id"), {"id": sid})
            for cid in (circuit_a_id, circuit_b_id, circuit_c_id, circuit_d_id):
                await session.execute(
                    text("DELETE FROM mirror_region_circuits WHERE id = :id"), {"id": cid})
            for rid in (region_1_id, region_2_id, region_3_id):
                await session.execute(
                    text("DELETE FROM candidate_brain_regions WHERE id = :id"), {"id": rid})
            await session.commit()

    loop = asyncio.new_event_loop()
    try:
        loop.run_until_complete(_setup())

        client = TestClient(app)
        resp = client.post("/api/symptom-query/graph", json={
            "circuit_ids": [
                str(circuit_a_id), str(circuit_b_id), str(circuit_c_id), str(circuit_d_id),
            ],
            "granularity_level": "macro",
        })

        assert resp.status_code == 200, resp.text
        data = resp.json()

        nodes = data["nodes"]
        assert len(nodes) == 3
        assert all(n["type"] == "brain_region" for n in nodes)
        region_labels = {n["label"] for n in nodes}
        assert "Precentral_L" in region_labels, f"missing Precentral_L in {region_labels}"
        assert "Postcentral_R" in region_labels, f"missing Postcentral_R in {region_labels}"
        assert "Thalamus_L" in region_labels, f"missing Thalamus_L in {region_labels}"

        by_id = {n["id"]: n for n in nodes}
        assert set(by_id[str(region_1_id)]["circuit_ids"]) == {
            str(circuit_a_id), str(circuit_d_id),
        }
        assert set(by_id[str(region_2_id)]["circuit_ids"]) == {
            str(circuit_a_id), str(circuit_b_id), str(circuit_d_id),
        }
        assert set(by_id[str(region_3_id)]["circuit_ids"]) == {
            str(circuit_a_id), str(circuit_b_id),
        }

        edges = {e["id"]: e for e in data["edges"]}
        inferred_edge_id = f"step-flow:{circuit_d_id}:{step_d1_id}:{step_d2_id}"
        assert set(edges) == {str(connection_a_id), str(connection_b_id), inferred_edge_id}
        assert edges[str(connection_a_id)]["circuit_ids"] == [str(circuit_a_id)]
        assert set(edges[str(connection_b_id)]["circuit_ids"]) == {
            str(circuit_a_id), str(circuit_b_id),
        }
        assert edges[inferred_edge_id]["circuit_ids"] == [str(circuit_d_id)]
        assert edges[inferred_edge_id]["type"] == "step_flow"
        assert edges[str(connection_a_id)]["strength"] == "moderate"

    finally:
        loop.run_until_complete(_teardown())
        loop.close()


def test_graph_rejects_invalid_circuit_uuid():
    client = TestClient(app)
    resp = client.post("/api/symptom-query/graph", json={
        "circuit_ids": ["not-a-uuid"],
        "granularity_level": "macro",
    })
    assert resp.status_code == 422


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
