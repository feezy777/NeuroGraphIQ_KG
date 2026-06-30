---
name: bug-fixes-june-2026
description: Critical bug fixes applied in June 2026 session
metadata:
  type: reference
---

# Bug Fixes (2026-06-25)

## MissingGreenlet in candidate_pool_service.py
**Problem:** `POST /api/candidates/pools` returned 500. Root cause: SQLAlchemy async mode — Pydantic serialization triggered lazy load of `memberships` relationship outside async context.
**Fix:** Added `await session.refresh(pool, ["memberships"])` before `return pool` in `create_pool()`.
**File:** `backend/app/services/candidate_pool_service.py`

## "+ 添加选中" Button Not Working
**Problem:** Button had no visible effect when clicked. Root cause: `pool?.id` was null (auto-add hadn't completed), causing `handleAddSelected` to create a duplicate pool via `createCandidatePool`.
**Fix:** Added `localPoolId` state — auto-add saves the created pool ID; `handleAddSelected` uses `pool?.id || localPoolId` as fallback.
**File:** `frontend/src/pages/llm-extraction/components/PoolExtractionModal.tsx`

## Log Console Blocking Data Table
**Problem:** Fixed `position: fixed` log console with hardcoded 320px padding-bottom wasted space when empty.
**Fix:** `BottomLogConsole.tsx` — ResizeObserver dynamically sets `--log-console-actual-height` CSS variable. CSS uses `var(--log-console-actual-height, var(--log-console-height-expanded))` for exact-fit padding.
**Files:** `frontend/src/components/BottomLogConsole.tsx`, `frontend/src/styles.css`

## Button Styles Reverted to Browser Defaults
**Problem:** Buttons in PoolExtractionModal used `pool-bar-btn` class whose CSS was deleted in a previous cleanup.
**Fix:** Replaced all `pool-bar-btn` with project-standard `llm-btn` / `llm-btn-primary` / `llm-btn-danger`.
**File:** `frontend/src/pages/llm-extraction/components/PoolExtractionModal.tsx`

## Backend 500 on GET /api/candidates/pools (2026-06-26)
**Problem:** `GET /api/candidates/pools` returned 500。Root cause: `list_pools` 返回 ORM objects，FastAPI 无法序列化。
**Fix:** Router 中转为 `[CandidatePoolRead.model_validate(p) for p in pools]`。
**File:** `backend/app/routers/candidate_pool.py`

## MissingGreenlet in add_members / remove_members (2026-06-26)
**Problem:** `add_members`/`remove_members` 调用 `session.refresh(pool)` 未预加载 `memberships`，后续序列化时触发 lazy load → MissingGreenlet。
**Fix:** 改为 `await session.refresh(pool, ["memberships"])`。
**File:** `backend/app/services/candidate_pool_service.py`

## PoolScope always null → useCandidatePool no-op (2026-06-26)
**Problem:** `useSessionScope` 初始化 `source_atlas: ''`、`granularity_level: ''`，从未被设置 → `poolScope` 始终为 null → `addCandidates` 立即返回 → Pool 功能完全不可用。
**Fix:** `useSessionScope` 默认值改为 `source_atlas: 'AAL3'`、`granularity_level: 'macro'`、`granularity_family: 'macro_clinical'`。
**File:** `frontend/src/pages/llm-extraction/hooks/useSessionScope.ts`

## Auto-add useEffect 竞态产生重复 Pool (2026-06-26)
**Problem:** PoolExtractionModal 的 auto-add `useEffect` 与父组件 `addCandidates` 同时创建 Pool → 数据库大量重复。
**Fix:** 移除 auto-add effect，父组件用 `.finally(() => setShowFullExtractModal(true))` 等 Pool 就绪后再打开 Modal。
**Files:** `PoolExtractionModal.tsx`, `LlmExtractionPage.tsx`

## Data Center 显示上限 (2026-06-26)
**Problem:** Mirror KG 页面硬编码 `limit: 500`，后台默认 50/max 5000，前端分页 `DATA_CENTER_PAGE_SIZE=20`，i18n 硬编码"每页 20 条"。即使有 5034 条连接也只显示 500。
**Fix:** 后端 `limit: ge=0, le=100000`（0=unlimited），前端 `limit: 0` 默认加载全部，`pageSize={999999}` 一次性显示。移除每页下拉框，简化 UI。
**Files:** `mirror_kg.py`, `MirrorKgPanel.tsx`, `FormalObjectTableSection.tsx`, `useDataCenterPagination.ts`, `DataCenterPagination.tsx`, `i18n.ts`

## cancel workflow 500: InFailedSqlTransaction (2026-06-26)
**Problem:** `cleanup_composite_workflow_artifacts` 中 DELETE 失败后未 rollback，事务处于 aborted 状态，后续 `mark_workflow_cleanup_summary` → `session.flush()` → InFailedSqlTransaction → 500。
**Fix:** except 块中 `await session.rollback()`，预查询阶段也加了 try/except + rollback，cancel 函数中整个 cleanup 段包在 try/except 中，失败后 rollback → re-query run → 写入 `cleanup_failed`。
**Files:** `llm_composite_workflow_cleanup_service.py`, `llm_composite_workflow_service.py`

## LLM 连接提取 name 字段缺失 (2026-06-26)
**Problem:** prompt 输出 schema 没有 `name_en/name_cn`/`source_region_name_en` 等字段；normalizer 不保留 name 字段；mirror 写入时有列但从未 backfill。
**Fix:** prompt 增加 name 字段要求；normalizer 保留 name；新增 `_fill_connection_names_from_pairs` 兜底函数；执行 Migration 036 backfill UPDATE 补齐 4648 条已有记录的名称。
**Files:** `llm_prompt_defaults.py`, `llm_extraction_prompt_engineering.py`, `llm_connection_extraction_service.py`, `migrations/036_mirror_connection_names.sql`

## Extracted connections = 0 in progress display (2026-06-26)
**Problem:** 前端 polling 用 `rs.created_counts.connections` 取值（progress 中间态为空），且字段名不匹配（`succeeded_pack_count` vs `provider_success_count`），polling 2s 太慢。
**Fix:** 统一 `_n()` 兼容读取 `provider_audit` 和 `result_summary`；polling 改为 1000ms；新增独立 1s 本地 elapsed timer；新增 `updated_projection_count` 统计（合并到已有连接）。
**Files:** `PoolExtractionModal.tsx`, `llm_connection_extraction_service.py`, `llm_composite_workflow_service.py`

**Why:** Reference for future debugging of similar issues.
**How to apply:** Check these patterns before debugging: SQLAlchemy async lazy loading, React prop staleness, CSS class deletion side effects, Pydantic ORM serialization, InFailedSqlTransaction → rollback, provider_audit vs result_summary field name mismatch.
