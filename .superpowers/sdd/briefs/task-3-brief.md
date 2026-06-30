# Task 3: Fix 5 Backend — no_connection_pack_count 字段

**Plan:** `docs/superpowers/plans/2026-06-30-pack-stats-audit-fix.md`
**Spec:** `docs/superpowers/specs/2026-06-30-pack-stats-audit-fix-design.md`

## File
- Modify: `backend/app/services/llm_extraction_prompt_engineering.py`

## Global Constraints
- 最小侵入，不动数据库 schema / API 签名 / router
- 向后兼容

## Changes

### 1. Add field to `ConnectionExecutionAudit` dataclass
After line 58 (`succeeded_pack_count: int = 0`), add:
```python
    no_connection_pack_count: int = 0      # packs that succeeded but found zero connections
```

### 2. Add to `to_dict()` 
After the `"succeeded_pack_count"` key in `to_dict()`, add:
```python
            "no_connection_pack_count": self.no_connection_pack_count,
```

## Verification
- `pytest tests/test_connection_parse_diagnostics.py -q` — no regressions
