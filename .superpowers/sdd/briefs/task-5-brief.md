# Task 5: Backend Tests

**Plan:** `docs/superpowers/plans/2026-06-30-pack-stats-audit-fix.md`

## File
- Modify: `backend/tests/test_connection_parse_diagnostics.py`

## Context
This test file already has helpers (`_candidate`, `_text_result`, `_mock_session`, `_run`, `_item`) and existing tests for `build_execution_summary`, `compact_pack_summaries`, `test_parse_error_increments_success_and_writes_pack_summaries`, `test_fail_fast_stops_after_three_packs`. Use these patterns.

Existing test pattern:
```python
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
            run_connection_extraction(
                session=session,
                run=_run(c1.batch_id, c1.resource_id),
                item=_item(c1.batch_id, c1.resource_id),
                candidate_ids=[c1.id, c2.id],
                provider_name="deepseek",
                model_name="deepseek-chat",
                prompt_template_key="same_granularity_connection_completion_v1",
                debug_single_pack=True,
            )
        )
    summary = result.execution_summary
    assert summary["provider_success_count"] >= 1
```

## Tests to Add

### Test A: audit.failed_pack_count on transport_error
```python
def test_audit_failed_pack_count_increments_on_transport_error():
    """When provider returns transport_ok=False, failed_pack_count increments."""
    c1 = _candidate()
    c2 = _candidate(batch_id=c1.batch_id, resource_id=c1.resource_id)
    response = _text_result("")
    response.transport_ok = False
    response.error = "timeout"
    mock_provider = AsyncMock()
    mock_provider.complete_text = AsyncMock(return_value=response)
    session = _mock_session([c1, c2])
    with patch("app.services.llm_connection_extraction_service.get_llm_provider", return_value=mock_provider), \
         patch("app.services.llm_connection_extraction_service.get_deepseek_runtime_config") as cfg:
        cfg.return_value = MagicMock(api_key="sk-test", default_model="deepseek-chat")
        result = asyncio.run(
            run_connection_extraction(
                session=session,
                run=_run(c1.batch_id, c1.resource_id),
                item=_item(c1.batch_id, c1.resource_id),
                candidate_ids=[c1.id, c2.id],
                provider_name="deepseek",
                model_name="deepseek-chat",
                prompt_template_key="same_granularity_connection_completion_v1",
                debug_single_pack=True,
            )
        )
    summary = result.execution_summary
    assert summary["failed_pack_count"] > 0
    assert summary["processed_pack_count"] > 0
    assert summary["succeeded_pack_count"] == 0
```

### Test B: run.error_message is set on failure
```python
def test_run_error_message_set_on_provider_failure():
    """When semantic outcome is failure, run.error_message is populated."""
    c1 = _candidate()
    c2 = _candidate(batch_id=c1.batch_id, resource_id=c1.resource_id)
    response = _text_result("")
    response.transport_ok = False
    response.error = "timeout"
    mock_provider = AsyncMock()
    mock_provider.complete_text = AsyncMock(return_value=response)
    session = _mock_session([c1, c2])
    run = _run(c1.batch_id, c1.resource_id)
    with patch("app.services.llm_connection_extraction_service.get_llm_provider", return_value=mock_provider), \
         patch("app.services.llm_connection_extraction_service.get_deepseek_runtime_config") as cfg:
        cfg.return_value = MagicMock(api_key="sk-test", default_model="deepseek-chat")
        asyncio.run(
            run_connection_extraction(
                session=session,
                run=run,
                item=_item(c1.batch_id, c1.resource_id),
                candidate_ids=[c1.id, c2.id],
                provider_name="deepseek",
                model_name="deepseek-chat",
                prompt_template_key="same_granularity_connection_completion_v1",
                debug_single_pack=True,
            )
        )
    assert run.error_message is not None
    assert run.error_message != ""
```

## Verification
- `pytest tests/test_connection_parse_diagnostics.py -q` — new tests pass + no regressions
