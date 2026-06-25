"""Tests for connection_with_function workflow parse / audit behavior."""

from __future__ import annotations

import asyncio
import uuid
from unittest.mock import AsyncMock, MagicMock, patch

from app.schemas.llm_extraction import LlmRunStatus
from app.services.llm_connection_extraction_service import run_same_granularity_connection_extraction
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


def test_connection_prompt_requires_json_only():
    tpl = DEFAULT_TEMPLATES["same_granularity_connection_completion_v1"]
    assert "神经科学家" in tpl.system_prompt
    assert "只输出一个 JSON object" in tpl.system_prompt
    assert "不要 Markdown" in tpl.system_prompt


def test_projection_function_prompt_requires_json_only():
    tpl = DEFAULT_TEMPLATES["projection_to_functions_v1"]
    assert "只输出一个 JSON object" in tpl.system_prompt
    assert "projection_functions" in tpl.user_prompt_template


def _text_result(raw_text: str) -> LlmProviderTextResult:
    return LlmProviderTextResult(
        provider="deepseek",
        model="deepseek-chat",
        raw_text=raw_text,
        usage=LlmProviderUsage(),
        finish_reason="stop",
        transport_ok=True,
        raw_response_preview=raw_text[:2000],
        request_payload_redacted={"json_mode_enabled": True},
        response_payload={"json_mode_enabled": True},
        latency_ms=5,
    )


def test_all_pack_parse_error_outcome_failed_parse_error():
    c1 = _candidate()
    c2 = _candidate(batch_id=c1.batch_id, resource_id=c1.resource_id)
    mock_provider = AsyncMock()
    mock_provider.complete_text = AsyncMock(return_value=_text_result("这不是 JSON，只是自然语言说明。"))
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
            )
        )
    summary = result.execution_summary
    assert summary["parse_error_count"] >= 1
    assert summary["provider_success_count"] >= 1
    assert summary["provider_transport_error_count"] == 0
    assert result.status == LlmRunStatus.failed_parse_error
    assert summary["pack_summaries"]
    assert summary["pack_summaries"][0].get("raw_response_preview")


def test_partial_pack_success_keeps_parsed_no_connections():
    c1 = _candidate()
    c2 = _candidate(batch_id=c1.batch_id, resource_id=c1.resource_id)
    from app.services.llm_extraction_prompt_engineering import make_pair_id

    pair_id = make_pair_id(c1.id, c2.id)
    good_json = (
        '{"projections": [], "no_connections": [{"pair_id": "%s", '
        '"source_region_candidate_id": "%s", "target_region_candidate_id": "%s", "reason": "no evidence"}], '
        '"warnings": []}'
    ) % (pair_id, c1.id, c2.id)
    responses = [_text_result(good_json)]
    mock_provider = AsyncMock()
    mock_provider.complete_text = AsyncMock(side_effect=responses)
    session = _mock_session([c1, c2])
    with patch("app.services.llm_connection_extraction_service.get_llm_provider", return_value=mock_provider), \
         patch("app.services.llm_connection_extraction_service.get_deepseek_runtime_config") as cfg, \
         patch("app.services.llm_connection_extraction_service.DEFAULT_PAIRS_PER_PACK", 1):
        cfg.return_value = MagicMock(api_key="sk-test", default_model="deepseek-chat")
        result = asyncio.run(
            run_same_granularity_connection_extraction(
                session,
                provider_name="deepseek",
                model_name="deepseek-chat",
                candidate_ids=[c1.id, c2.id],
                dry_run=False,
                create_mirror_records=False,
            )
        )
    assert result.no_connection_count >= 1
    assert result.status in {LlmRunStatus.succeeded_no_edges, LlmRunStatus.succeeded}
