# Pack 统计审计修复 实施计划

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 修复连接提取中 `ConnectionExecutionAudit` 的 5 个问题——审计字段递增、retry、错误传播、截断控制、no_connection_pack 分类

**Architecture:** 5 个 Fix 全部在后端 `_process_one_pack` 闭包 + diagnostics 层 + 前端 1 个类型字段。不动 DB schema、API 签名、router。

**Tech Stack:** Python/FastAPI/SQLAlchemy (backend), TypeScript/React (frontend)

## Global Constraints

- 最小侵入，不动数据库 schema
- 不动 API 路由签名
- `_process_one_pack` 返回值签名不变
- 向后兼容：旧运行记录的 `execution_summary` 无新字段，前端做缺省处理
- 全量回归不新增失败

**Spec:** `docs/superpowers/specs/2026-06-30-pack-stats-audit-fix-design.md`

---

### Task 1: Fix 1-3 — audit 递增 + retry + error_message 传播

**Files:**
- Modify: `backend/app/services/llm_connection_extraction_service.py:1256-1262, 1283-1284, 1353-1361, 1416-1417, 1658-1661`

**Interfaces:**
- Consumes: `ConnectionExecutionAudit` (has `succeeded_pack_count`, `failed_pack_count`, `processed_pack_count`, `no_connection_pack_count` — defined in Task 3)
- Produces: 无新接口 — 所有改动在闭包内部

**Six locations in one file. `_process_one_pack` 的 4 个 return 路径 + 1 个 retry 位置 + `run.error_message`。**

- [ ] **Step 1: Fix 2 — transport_error retry (line 1261-1262)**

In `_process_one_pack`, change `break` to `continue`:

```python
# BEFORE (line 1261-1262):
                    parsed = None
                    break

# AFTER:
                    parsed = None
                    continue
```

- [ ] **Step 2: Fix 2 — empty_response retry (line 1283-1284)**

Same change:

```python
# BEFORE (line 1283-1284):
                    parsed = None
                    break

# AFTER:
                    parsed = None
                    continue
```

- [ ] **Step 3: Fix 1 — transport_error / empty_response 路径递增 (around line 1359-1361)**

```python
# BEFORE:
            else:
                await _persist_pack_trace(trace)
                return [], [], [], set(), 0

# AFTER:
            else:
                audit.processed_pack_count += 1
                audit.failed_pack_count += 1
                await _persist_pack_trace(trace)
                return [], [], [], set(), 0
```

- [ ] **Step 4: Fix 1 — parse_error 路径递增 (around line 1354-1358)**

```python
# BEFORE:
        if parsed is None:
            if trace.get("parse_error_type") not in {"transport_error", "empty_response"}:
                audit.parse_error_count += 1
                trace["status"] = "parse_error"
                await _persist_pack_trace(trace)
                return [], [], [], set(), 1

# AFTER:
        if parsed is None:
            if trace.get("parse_error_type") not in {"transport_error", "empty_response"}:
                audit.parse_error_count += 1
                audit.processed_pack_count += 1
                audit.failed_pack_count += 1
                trace["status"] = "parse_error"
                await _persist_pack_trace(trace)
                return [], [], [], set(), 1
```

- [ ] **Step 5: Fix 1 — 成功路径递增 (around line 1416-1417)**

```python
# BEFORE:
        await _persist_pack_trace(trace)
        return pack_connections, pack_no, pack_warnings, handled, 0

# AFTER:
        audit.processed_pack_count += 1
        if pack_connections:
            audit.succeeded_pack_count += 1
        else:
            audit.no_connection_pack_count += 1
        await _persist_pack_trace(trace)
        return pack_connections, pack_no, pack_warnings, handled, 0
```

- [ ] **Step 6: Fix 3 — run.error_message 传播 (around line 1658-1661)**

```python
# BEFORE:
    if is_semantic_failure(semantic_outcome):
        item.status = LlmItemStatus.failed
        item.error_message = status_warnings[0] if status_warnings else semantic_outcome
        run.error_count = max(int(run.error_count or 0), 1)

# AFTER:
    if is_semantic_failure(semantic_outcome):
        item.status = LlmItemStatus.failed
        item.error_message = status_warnings[0] if status_warnings else semantic_outcome
        run.error_message = item.error_message
        run.error_count = max(int(run.error_count or 0), 1)
```

- [ ] **Step 7: Commit**

```bash
git add backend/app/services/llm_connection_extraction_service.py
git commit -m "fix: audit pack counters, retry on transport/empty, propagate run error_message"
```

---

### Task 2: Fix 4 — build_execution_summary compact 参数

**Files:**
- Modify: `backend/app/services/llm_connection_parse_diagnostics.py:196-216, 240-245, 254-263`

**Interfaces:**
- Consumes: `ConnectionExecutionAudit.to_dict()` (now includes `no_connection_pack_count` from Task 3)
- Produces: `build_execution_summary(audit, pack_traces, *, extra=None, compact=True)` — new `compact` kwarg

- [ ] **Step 1: Update compact_pack_summaries to respect total count**

```python
# BEFORE (line 196-216):
def compact_pack_summaries(
    traces: list[dict[str, Any]],
    *,
    max_recent: int = PACK_SUMMARY_MAX_RECENT,
    min_failed_keep: int = PACK_SUMMARY_MIN_FAILED_KEEP,
) -> list[dict[str, Any]]:
    if not traces:
        return []
    finalized = [finalize_pack_trace(t) for t in traces]
    failed = [t for t in finalized if t.get("status") in {"parse_error", "schema_error", "transport_error"}]
    keep_failed = failed[-min_failed_keep:] if failed else []
    recent = finalized[-max_recent:]
    merged: list[dict[str, Any]] = []
    seen_ids: set[str] = set()
    for item in keep_failed + recent:
        key = str(item.get("pack_id", id(item)))
        if key in seen_ids:
            continue
        seen_ids.add(key)
        merged.append(item)
    return merged[-max_recent:] if len(merged) > max_recent else merged

# AFTER:
def compact_pack_summaries(
    traces: list[dict[str, Any]],
    *,
    max_recent: int = PACK_SUMMARY_MAX_RECENT,
    min_failed_keep: int = PACK_SUMMARY_MIN_FAILED_KEEP,
) -> list[dict[str, Any]]:
    if not traces:
        return []
    finalized = [finalize_pack_trace(t) for t in traces]
    # Short-circuit: if total traces fit within max_recent, return all as-is
    if len(finalized) <= max_recent:
        return finalized
    failed = [t for t in finalized if t.get("status") in {"parse_error", "schema_error", "transport_error"}]
    keep_failed = failed[-min_failed_keep:] if failed else []
    recent = finalized[-max_recent:]
    merged: list[dict[str, Any]] = []
    seen_ids: set[str] = set()
    for item in keep_failed + recent:
        key = str(item.get("pack_id", id(item)))
        if key in seen_ids:
            continue
        seen_ids.add(key)
        merged.append(item)
    return merged[-max_recent:] if len(merged) > max_recent else merged
```

- [ ] **Step 2: Add compact param to build_execution_summary**

```python
# BEFORE (line 240-245):
def build_execution_summary(
    audit: ConnectionExecutionAudit,
    pack_traces: list[dict[str, Any]],
    *,
    extra: dict[str, Any] | None = None,
) -> dict[str, Any]:

# AFTER:
def build_execution_summary(
    audit: ConnectionExecutionAudit,
    pack_traces: list[dict[str, Any]],
    *,
    extra: dict[str, Any] | None = None,
    compact: bool = True,
) -> dict[str, Any]:
```

- [ ] **Step 3: Use compact flag + strip prompt_preview when non-compact**

```python
# BEFORE (line 246-247):
    compact = compact_pack_summaries(pack_traces)
    audit.pack_summaries = compact

# AFTER:
    if compact:
        compacted = compact_pack_summaries(pack_traces)
    else:
        # Keep all traces but strip prompt_preview to control payload size
        compacted = [_strip_prompt_preview(finalize_pack_trace(t)) for t in pack_traces]
    audit.pack_summaries = compacted
```

And update later references from `compact` variable name to `compacted`.

- [ ] **Step 4: Add _strip_prompt_preview helper**

Add to `llm_connection_parse_diagnostics.py`:

```python
def _strip_prompt_preview(trace: dict[str, Any]) -> dict[str, Any]:
    """Return trace without prompt_preview to reduce payload size."""
    return {k: v for k, v in trace.items() if k != "prompt_preview"}
```

- [ ] **Step 5: Update final build_execution_summary call in extraction service**

In `llm_connection_extraction_service.py` line ~1670:

```python
# BEFORE:
    execution_summary = build_execution_summary(
        audit,
        pack_traces,
        extra={...},
    )

# AFTER:
    execution_summary = build_execution_summary(
        audit,
        pack_traces,
        extra={...},
        compact=False,
    )
```

- [ ] **Step 6: Use audit fields directly when non-compact**

In `build_execution_summary`, when `compact=False`, skip recompute from pack_summaries since audit fields are accurate (Task 1 fixed them):

```python
# BEFORE (line 254-263):
    summary["failed_pack_count"] = sum(
        1
        for p in compact
        if p.get("status") in {"parse_error", "schema_error", "transport_error", "empty_response"}
        or p.get("parse_error")
        or p.get("parse_error_type") in {"json_decode_error", "schema_error", "transport_error", "empty_response"}
    )
    processed_traces = [t for t in pack_traces if t.get("provider_call_finished")]
    summary["processed_pack_count"] = len(processed_traces)
    summary["succeeded_pack_count"] = summary["processed_pack_count"] - summary["failed_pack_count"]

# AFTER:
    if compact:
        summary["failed_pack_count"] = sum(
            1
            for p in compacted
            if p.get("status") in {"parse_error", "schema_error", "transport_error", "empty_response"}
            or p.get("parse_error")
            or p.get("parse_error_type") in {"json_decode_error", "schema_error", "transport_error", "empty_response"}
        )
        processed_traces = [t for t in pack_traces if t.get("provider_call_finished")]
        summary["processed_pack_count"] = len(processed_traces)
        summary["succeeded_pack_count"] = summary["processed_pack_count"] - summary["failed_pack_count"]
    else:
        # Trust audit object directly (fix 1 ensures it's accurate)
        summary["failed_pack_count"] = audit.failed_pack_count
        summary["processed_pack_count"] = audit.processed_pack_count
        summary["succeeded_pack_count"] = audit.succeeded_pack_count
        summary["no_connection_pack_count"] = audit.no_connection_pack_count
```

- [ ] **Step 7: Commit**

```bash
git add backend/app/services/llm_connection_parse_diagnostics.py backend/app/services/llm_connection_extraction_service.py
git commit -m "feat: add compact param to build_execution_summary for full pack history"
```

---

### Task 3: Fix 5 Backend — no_connection_pack_count 字段

**Files:**
- Modify: `backend/app/services/llm_extraction_prompt_engineering.py:41-103`

**Interfaces:**
- Consumes: 无
- Produces: `ConnectionExecutionAudit.no_connection_pack_count: int`, 已由 `to_dict()` 序列化

- [ ] **Step 1: Add field to dataclass**

In `ConnectionExecutionAudit` (line ~57), add after `succeeded_pack_count`:

```python
# AFTER succeeded_pack_count: int = 0 (line 58), add:
    succeeded_pack_count: int = 0          # packs completed without transport/parse failure
    no_connection_pack_count: int = 0      # packs that succeeded but found zero connections
    failed_pack_count: int = 0             # packs that failed (transport, parse, exception)
```

- [ ] **Step 2: Add to to_dict()**

In `to_dict()` (line ~91-93), add after `succeeded_pack_count`:

```python
            "succeeded_pack_count": self.succeeded_pack_count,
            "no_connection_pack_count": self.no_connection_pack_count,
            "failed_pack_count": self.failed_pack_count,
```

- [ ] **Step 3: Commit**

```bash
git add backend/app/services/llm_extraction_prompt_engineering.py
git commit -m "feat: add no_connection_pack_count to ConnectionExecutionAudit"
```

---

### Task 4: Fix 5 Frontend — ProgressData + 显示

**Files:**
- Modify: `frontend/src/pages/llm-extraction/components/PoolExtractionModal.tsx:24-54, 220-237, 566-596, 796-799`

**Interfaces:**
- Consumes: `execution_summary.no_connection_pack_count` (backend key) → `noConnectionPackCount` (frontend camelCase)

- [ ] **Step 1: Add field to ProgressData interface (line ~34)**

Add after `failedPacks`:

```typescript
// AFTER line 31:
  failedPacks: number            // failed_pack_count — transport/parse/exception failures
  noConnectionPacks: number      // no_connection_pack_count — succeeded but zero connections found
```

- [ ] **Step 2: Initialize in default state (line ~226)**

```typescript
// AFTER failedPacks: 0:
    failedPacks: 0,
    noConnectionPacks: 0,
```

- [ ] **Step 3: Initialize in start extraction handler (line ~573)**

```typescript
// AFTER failedPacks: 0:
        failedPacks: 0,
        noConnectionPacks: 0,
```

- [ ] **Step 4: Read from API in polling (after line 796-799)**

After the `noConn` read block, add:

```typescript
        const noConnectionPacks = readProgressMetric(
          terminal ? finalSources : liveSources,
          'no_connection_pack_count',
        ) ?? 0
```

- [ ] **Step 5: Pass to setProgress in polling update (line ~913)**

Add after `failedPacks,` at line ~913:

```typescript
          noConnectionPacks: noConnectionPacks ?? 0,
```

- [ ] **Step 6: Display in stats section — succeeds/fails cards (lines ~1298-1310)**

Find the success/fail pack cards section and add noConnectionPacks card:

```tsx
// AFTER the "失败包" card, add:
<div className="modal-metric-card" style={{ background: progress.noConnectionPacks > 0 ? '#fff7e6' : '#fafafa' }}>
  <div className="metric-label" style={{ color: '#d48806' }}>无连接包</div>
  <div className="metric-value" style={{ color: '#d48806' }}>
    {progress.noConnectionPacks > 0 ? progress.noConnectionPacks : '—'}
  </div>
</div>
```

- [ ] **Step 7: Build check**

```bash
cd frontend && npm run build
```

Expected: zero TypeScript errors.

- [ ] **Step 8: Commit**

```bash
git add frontend/src/pages/llm-extraction/components/PoolExtractionModal.tsx
git commit -m "feat: add noConnectionPackCount to pool extraction progress UI"
```

---

### Task 5: Backend Tests

**Files:**
- Modify: `backend/tests/test_llm_connection_extraction.py` (or closest existing test file)

- [ ] **Step 1: Test — audit counters increment on transport_error**

Add to `backend/tests/test_connection_parse_diagnostics.py`:

```python
def test_audit_failed_pack_count_increments_on_transport_error():
    """When provider returns transport_error, audit.failed_pack_count must increment."""
    c1 = _candidate()
    c2 = _candidate(batch_id=c1.batch_id, resource_id=c1.resource_id)
    # Build a text result with transport_ok=False
    response = _text_result("")
    response.transport_ok = False
    response.error = "timeout"
    response.raw_text = ""
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
    # Verify audit object matches
    assert result._audit.failed_pack_count > 0
    assert result._audit.processed_pack_count > 0
```

- [ ] **Step 2: Test — run.error_message is set on failure**

Add to same file:

```python
def test_run_error_message_set_on_provider_failure():
    """When semantic outcome is failure, run.error_message must be populated."""
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
        result = asyncio.run(
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
    # After execution, run.error_message should be populated
    assert run.error_message is not None
    assert run.error_message != ""
    assert run.error_count >= 1
```

- [ ] **Step 3: Test — audit.succeeded_pack_count + no_connection_pack_count**

Add to same file:

```python
def test_audit_succeeded_pack_count_increments_with_connections():
    """When provider returns connections, succeeded_pack_count increments."""
    c1 = _candidate()
    c2 = _candidate(batch_id=c1.batch_id, resource_id=c1.resource_id)
    json_with_connection = json.dumps({
        "projections": [{
            "source_id": str(c1.id), "target_id": str(c2.id),
            "connection_type": "anatomical", "directionality": "bidirectional",
            "confidence": 0.85, "evidence_level": "moderate",
        }],
        "no_connections": [],
        "warnings": [],
    })
    response = _text_result(json_with_connection)
    mock_provider = AsyncMock()
    mock_provider.complete_text = AsyncMock(return_value=response)
    session = _mock_session([c1, c2])
    with patch("app.services.llm_connection_extraction_service.get_llm_provider", return_value=mock_provider), \
         patch("app.services.llm_connection_extraction_service.get_deepseek_runtime_config") as cfg, \
         patch("app.services.llm_connection_extraction_service.persist_connection_mirror_records") as persist_mock:
        cfg.return_value = MagicMock(api_key="sk-test", default_model="deepseek-chat")
        persist_mock.return_value = asyncio.Future()
        persist_mock.return_value.set_result((0, 0, 0, 0, [], []))  # mock: no mirror writes
        result = asyncio.run(
            run_connection_extraction(
                session=session,
                run=_run(c1.batch_id, c1.resource_id),
                item=_item(c1.batch_id, c1.resource_id),
                candidate_ids=[c1.id, c2.id],
                provider_name="deepseek",
                model_name="deepseek-chat",
                prompt_template_key="same_granularity_connection_completion_v1",
                create_mirror_records=False,
                debug_single_pack=True,
            )
        )
    summary = result.execution_summary
    assert summary["succeeded_pack_count"] > 0
    assert summary["parsed_projection_count"] > 0

- [ ] **Step 4: Run new tests**

```bash
cd backend && .venv/Scripts/python.exe -m pytest tests/test_llm_connection_extraction.py -q -k "audit_failed\|run_error_message\|audit_succeeded"
```

Expected: 3 PASS

- [ ] **Step 5: Commit**

```bash
git add backend/tests/test_llm_connection_extraction.py
git commit -m "test: verify audit pack counters and run.error_message propagation"
```

---

### Task 6: Final Verification

- [ ] **Step 1: Full backend test suite**

```bash
cd backend && .venv/Scripts/python.exe -m pytest tests/ -q
```

Expected: no new failures vs baseline.

- [ ] **Step 2: Frontend build**

```bash
cd frontend && npm run build
```

Expected: zero TypeScript errors.

- [ ] **Step 3: Verify existing tests still match**

```bash
cd backend && .venv/Scripts/python.exe -m pytest tests/test_llm_composite_workflow.py tests/test_llm_connection_extraction.py tests/test_connection_parse_diagnostics.py -q
```

All previously-passing tests must still pass.

- [ ] **Step 4: Final commit (if verification-only changes)**

```bash
git commit -m "chore: final verification — all tests pass, frontend builds"
```
