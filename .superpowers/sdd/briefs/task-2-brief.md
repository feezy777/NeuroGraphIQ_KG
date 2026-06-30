# Task 2: Fix 4 — build_execution_summary compact 参数

**Plan:** `docs/superpowers/plans/2026-06-30-pack-stats-audit-fix.md`
**Spec:** `docs/superpowers/specs/2026-06-30-pack-stats-audit-fix-design.md`

## Files
- Modify: `backend/app/services/llm_connection_parse_diagnostics.py`
- Modify: `backend/app/services/llm_connection_extraction_service.py` (one call site only)

## Global Constraints
- 最小侵入，不动数据库 schema / API 签名 / router
- 向后兼容
- 全量回归不新增失败

## Changes

### 1. Add `_strip_prompt_preview` helper (in diagnostics.py)

```python
def _strip_prompt_preview(trace: dict[str, Any]) -> dict[str, Any]:
    """Return trace without prompt_preview to reduce payload size."""
    return {k: v for k, v in trace.items() if k != "prompt_preview"}
```

### 2. Add short-circuit to `compact_pack_summaries`

When total traces ≤ max_recent (20), return all finalized traces as-is without filtering/merging.

### 3. Add `compact: bool = True` param to `build_execution_summary`

When compact=False, keep all traces but strip prompt_preview. When compact=True (default), use existing compact logic. Also when compact=False, trust audit object fields directly (they're accurate after Task 1 fix).

### 4. Update the final call site in extraction_service.py

At the final `build_execution_summary()` call (~line 1670), pass `compact=False`.

## Verification
- `pytest tests/test_connection_parse_diagnostics.py -q` — no regressions
- `pytest tests/test_llm_composite_workflow.py -q` — no regressions
