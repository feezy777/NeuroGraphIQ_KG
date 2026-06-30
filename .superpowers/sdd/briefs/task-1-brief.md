# Task 1: Fix 1-3 — audit 递增 + retry + error_message 传播

**Plan:** `docs/superpowers/plans/2026-06-30-pack-stats-audit-fix.md`
**Spec:** `docs/superpowers/specs/2026-06-30-pack-stats-audit-fix-design.md`

## Files
- Modify: `backend/app/services/llm_connection_extraction_service.py`

## Global Constraints
- 最小侵入，不动数据库 schema
- 不动 API 路由签名
- `_process_one_pack` 返回值签名不变
- 向后兼容
- 全量回归不新增失败

## Changes (6 locations in one file)

### Location 1: transport_error retry (line ~1261-1262)
Change `break` to `continue`:
```python
                    parsed = None
                    continue
```

### Location 2: empty_response retry (line ~1283-1284)
Same — change `break` to `continue`:
```python
                    parsed = None
                    continue
```

### Location 3: transport_error / empty_response path (around line 1359-1361)
Add audit counter increments before return:
```python
            else:
                audit.processed_pack_count += 1
                audit.failed_pack_count += 1
                await _persist_pack_trace(trace)
                return [], [], [], set(), 0
```

### Location 4: parse_error path (around line 1354-1358)
Add audit counter increments:
```python
        if parsed is None:
            if trace.get("parse_error_type") not in {"transport_error", "empty_response"}:
                audit.parse_error_count += 1
                audit.processed_pack_count += 1
                audit.failed_pack_count += 1
                trace["status"] = "parse_error"
                await _persist_pack_trace(trace)
                return [], [], [], set(), 1
```

### Location 5: success path (around line 1416-1417)
Add audit counter increments, distinguishing succeeded vs no_connection:
```python
        audit.processed_pack_count += 1
        if pack_connections:
            audit.succeeded_pack_count += 1
        else:
            audit.no_connection_pack_count += 1
        await _persist_pack_trace(trace)
        return pack_connections, pack_no, pack_warnings, handled, 0
```

### Location 6: run.error_message propagation (around line 1658-1661)
Add 1 line after item.error_message:
```python
    if is_semantic_failure(semantic_outcome):
        item.status = LlmItemStatus.failed
        item.error_message = status_warnings[0] if status_warnings else semantic_outcome
        run.error_message = item.error_message
        run.error_count = max(int(run.error_count or 0), 1)
```

## Verification
- Run `pytest tests/test_connection_parse_diagnostics.py tests/test_debug_single_pack_pipeline.py -q` — must not add failures
- Run `pytest tests/test_llm_composite_workflow.py -q` — must not add failures
