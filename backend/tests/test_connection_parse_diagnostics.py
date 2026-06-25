"""Tests for connection parse diagnostics, fail-fast, and replay API."""

from __future__ import annotations

import asyncio
import uuid
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from fastapi.testclient import TestClient

from app.main import app
from app.schemas.llm_extraction import LlmRunStatus
from app.services.llm_connection_extraction_service import run_same_granularity_connection_extraction
from app.services.llm_connection_parse_diagnostics import (
    build_execution_summary,
    compact_pack_summaries,
    replay_connection_parse_response,
    should_trigger_parse_fail_fast,
)
from app.services.llm_extraction_prompt_engineering import ConnectionExecutionAudit
from app.services.llm_prompt_defaults import DEFAULT_TEMPLATES
from app.services.llm_providers.base import LlmProviderTextResult, LlmProviderUsage


def _candidate(**kwargs):
    from app.models.candidate import CandidateBrainRegion

    cid = kwargs.pop("id", uuid.uuid4())
    batch_id = kwargs.pop("batch_id", uuid.uuid4())
    resource_id = kwargs.pop("resource_id", uuid.uuid4())
    return CandidateBrainRegion(
        id=cid,
        batch_id=batch_id,
        resource_id=resource_id,
        source_atlas=kwargs.pop("source_atlas", "test_atlas"),
        granularity_level=kwargs.pop("granularity_level", "region"),
        granularity_family=kwargs.pop("granularity_family", "macro"),
        en_name=kwargs.pop("en_name", "Region A"),
        cn_name=kwargs.pop("cn_name", "脑区A"),
        **kwargs,
    )


def _mock_session(candidates):
    session = AsyncMock()
    session.commit = AsyncMock()
    session.flush = AsyncMock()
    session.refresh = AsyncMock()

    async def _execute(stmt):
        result = MagicMock()
        result.scalars.return_value.all.return_value = candidates
        result.scalar_one_or_none.return_value = None
        return result

    session.execute = AsyncMock(side_effect=_execute)
    session.add = MagicMock()

    def _refresh(obj):
        if not getattr(obj, "id", None):
            obj.id = uuid.uuid4()

    session.refresh.side_effect = _refresh
    return session


def test_build_execution_summary_syncs_provider_success_from_traces():
    audit = ConnectionExecutionAudit(provider_call_count=1, parse_error_count=1)
    traces = [{
        "pack_id": 0,
        "response_received": True,
        "response_char_count": 100,
        "raw_response_preview": "hello",
        "parse_error": "bad json",
        "parse_error_type": "json_decode_error",
    }]
    summary = build_execution_summary(audit, traces)
    assert summary["provider_success_count"] == 1
    assert summary["parse_error_count"] == 1
    assert summary["pack_summaries"]
    assert summary["pack_summaries"][0]["raw_response_preview"]


def test_compact_pack_summaries_keeps_failed_previews():
    traces = [
        {"pack_id": i, "parse_error": f"err{i}", "raw_response_preview": f"preview{i}"}
        for i in range(25)
    ]
    compact = compact_pack_summaries(traces, max_recent=20, min_failed_keep=3)
    assert len(compact) <= 20
    assert any("preview24" in str(p.get("raw_response_preview", "")) for p in compact)


def test_should_trigger_fail_fast_after_consecutive_parse_errors():
    assert not should_trigger_parse_fail_fast(
        consecutive_parse_failures=3,
        parsed_projection_count=0,
        parsed_no_connection_count=0,
    )
    assert should_trigger_parse_fail_fast(
        consecutive_parse_failures=5,
        parsed_projection_count=0,
        parsed_no_connection_count=0,
    )
    assert not should_trigger_parse_fail_fast(
        consecutive_parse_failures=5,
        parsed_projection_count=0,
        parsed_no_connection_count=1,
    )


def test_replay_api_does_not_call_provider():
    client = TestClient(app)
    resp = client.post(
        "/api/llm-extraction/debug/parse-connection-response",
        json={
            "raw_text": '{"projections": [], "no_connections": [], "warnings": []}',
            "pack_pairs": [],
        },
    )
    assert resp.status_code == 200
    body = resp.json()
    assert body["parsed"] is True


def _text_result(raw_text: str) -> LlmProviderTextResult:
    from app.services.llm_json_utils import raw_response_preview

    return LlmProviderTextResult(
        provider="deepseek",
        model="deepseek-chat",
        raw_text=raw_text,
        usage=LlmProviderUsage(),
        finish_reason="stop",
        transport_ok=True,
        raw_response_preview=raw_response_preview(raw_text),
        response_payload={"json_mode_enabled": True},
        request_payload_redacted={"json_mode_enabled": True},
    )


def test_parse_error_increments_success_and_writes_pack_summaries():
    c1 = _candidate()
    c2 = _candidate(batch_id=c1.batch_id, resource_id=c1.resource_id)
    response = _text_result("纯自然语言，不是 JSON")
    mock_provider = AsyncMock()
    mock_provider.complete_text = AsyncMock(return_value=response)
    session = _mock_session([c1, c2])
    with patch("app.services.llm_connection_extraction_service.get_llm_provider", return_value=mock_provider), \
         patch("app.services.llm_connection_extraction_service.get_deepseek_runtime_config") as cfg:
        cfg.return_value = MagicMock(api_key="sk-test", default_model="deepseek-chat")
        result = asyncio.run(
            run_same_granularity_connection_extraction(
                session,
                provider_name="deepseek",
                model_name="deepseek-chat",
                candidate_ids=[c1.id, c2.id],
                dry_run=False,
                create_mirror_records=False,
                debug_single_pack=True,
            )
        )
    summary = result.execution_summary
    assert summary["provider_success_count"] >= 1
    assert summary["parse_error_count"] >= 1
    assert summary["provider_transport_error_count"] == 0
    assert summary["pack_summaries"]
    assert summary["pack_summaries"][0].get("raw_response_preview")
    assert summary.get("debug_mode") is True


def test_fail_fast_stops_after_three_packs():
    c1 = _candidate()
    c2 = _candidate(batch_id=c1.batch_id, resource_id=c1.resource_id)
    c3 = _candidate(batch_id=c1.batch_id, resource_id=c1.resource_id)
    c4 = _candidate(batch_id=c1.batch_id, resource_id=c1.resource_id)
    bad = _text_result("not json")
    mock_provider = AsyncMock()
    mock_provider.complete_text = AsyncMock(return_value=bad)
    session = _mock_session([c1, c2, c3, c4])
    with patch("app.services.llm_connection_extraction_service.get_llm_provider", return_value=mock_provider), \
         patch("app.services.llm_connection_extraction_service.get_deepseek_runtime_config") as cfg, \
         patch("app.services.llm_connection_extraction_service.DEFAULT_PAIRS_PER_PACK", 1):
        cfg.return_value = MagicMock(api_key="sk-test", default_model="deepseek-chat")
        result = asyncio.run(
            run_same_granularity_connection_extraction(
                session,
                provider_name="deepseek",
                model_name="deepseek-chat",
                candidate_ids=[c1.id, c2.id, c3.id, c4.id],
                dry_run=False,
                create_mirror_records=False,
                parse_error_fail_fast_threshold=3,
            )
        )
    summary = result.execution_summary
    assert summary.get("fail_fast_triggered") is True
    assert summary.get("remaining_pack_count_skipped", 0) >= 1
    assert mock_provider.complete_text.call_count <= 6


def test_prompt_requires_json_even_when_no_connections():
    tpl = DEFAULT_TEMPLATES["same_granularity_connection_completion_v1"]
    assert "即使所有 pair 都无连接" in tpl.system_prompt
    assert "禁止返回自然语言解释" in tpl.system_prompt


def test_replay_connection_parse_response_no_db():
    out = replay_connection_parse_response(
        '{"projections": [], "no_connections": [], "warnings": []}',
        [],
    )
    assert out["parsed"] is True
    assert out["parsed_projection_count"] == 0
