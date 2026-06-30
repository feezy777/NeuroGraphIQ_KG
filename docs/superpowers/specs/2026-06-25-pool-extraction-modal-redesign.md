# Pool Extraction Modal Redesign

**Date:** 2026-06-25
**Status:** Approved
**Replaces:** CandidatePoolBar + FullExtractionModal (previous design)

---

## Problem

1. Top pool bar (`CandidatePoolBar`) never appears because `poolScope` depends on session scope which is often empty
2. User wants pool management + extraction + progress all in one modal
3. Progress needs accurate per-pack stats (not batch-based anymore)

## Solution

**One modal, three states, fixed 900px size.** Pool management, extraction progress, and results all in `PoolExtractionModal`.

---

### State 1: Prepare (池准备)

```
┌──────────────────────────────────────────────────────────┐
│ ⚡ 全量连接提取                                [✕]      │
│                                                          │
│ 📊 候选池                     已累积 67 脑区 · 2,211 对  │
│ ┌────────────────────────────────────────────────────┐   │
│ │ [搜索脑区...]              [+ 从当前选中添加 (12)]  │   │
│ │                                                    │   │
│ │ ☐ 全选  已选 3 项  [移除选中]                      │   │
│ │                                                    │   │
│ │ 脑区名称      │ Batch     │ 加入时间 │ 操作        │   │
│ │ 前额叶皮层     │ AAL3 #1   │ 14:22   │ [✕ 移除]    │   │
│ │ 海马体        │ AAL3 #2   │ 14:25   │ [✕ 移除]    │   │
│ └────────────────────────────────────────────────────┘   │
│                                                          │
│ ⚙️ 模型配置                                              │
│ Provider: [DeepSeek ▼]  Model: [deepseek-v4-pro ▼]      │
│ □ Dry run                                               │
│                                                          │
│                      [取消]    [🚀 开始全量提取]          │
└──────────────────────────────────────────────────────────┘
```

### State 2: Progress (提取中)

```
┌──────────────────────────────────────────────────────────┐
│ ⚡ 提取中...  AAL3 · macro                     [✕]      │
│                                                          │
│ ████████████████░░░░░░░░░░░░░░  47/152 包 (31%)          │
│                                                          │
│ ✅ 成功 44 包    ❌ 异常 3 包                             │
│ 📊 已发现 187 条连接                                      │
│ ⏱ 平均 2.3s/包    ⏳ 预计剩余 ≈ 4 分钟                    │
│                                                          │
│ 最近异常:                                                │
│ pack_12: json_decode_error — 响应截断                    │
│ pack_28: provider_error — 429 rate limit, 已重试         │
│                                                          │
│                      [⏸ 暂停]    [⏹ 取消提取]            │
└──────────────────────────────────────────────────────────┘
```

### State 3: Result (完成)

```
┌──────────────────────────────────────────────────────────┐
│ ✅ 提取完成  AAL3 · macro                      [✕]      │
│                                                          │
│ 📊 结果摘要                                              │
│ 总包数: 152   成功: 145   失败: 7                        │
│ 连接总数: 1,247 条 (已写入 Mirror KG)                    │
│ 耗时: 5 分 48 秒                                         │
│                                                          │
│                      [查看 Mirror KG →]    [关闭]        │
└──────────────────────────────────────────────────────────┘
```

---

## Progress Data: Polling Loop

```typescript
// Frontend polls GET /api/llm-extraction/composite-workflow/{run_id} every 2s
const POLL_INTERVAL = 2000

// From execution_summary in response:
const processedPacks = summary.processed_pack_count ?? 0
const totalPacks = summary.pack_count ?? 0
const successPacks = summary.provider_success_count ?? 0
const failedPacks = summary.failed_pack_count ?? 0
const connectionsFound = summary.parsed_projection_count ?? 0
const recentErrors = summary.pack_summaries
  ?.filter((p: any) => p.parse_error)
  ?.slice(-3) ?? []

// Client-side timing:
const avgPerPack = elapsedSeconds / processedPacks
const remainingSeconds = avgPerPack * (totalPacks - processedPacks)
```

---

## Files Changed

| File | Action |
|------|--------|
| `PoolExtractionModal.tsx` | **New** — replaces CandidatePoolBar + FullExtractionModal |
| `CandidatePoolBar.tsx` | **Delete** |
| `FullExtractionModal.tsx` | **Delete** |
| `useCandidatePool.ts` | **Modify** — add `searchCandidates`, `batchRemove` |
| `LlmExtractionPage.tsx` | **Modify** — remove Bar import, replace with modal trigger |
| `styles.css` | **Modify** — remove pool-bar styles, add fixed modal size |

---

## Fixed Modal Size

```css
.pool-extraction-modal .modal-panel {
  max-width: 900px; width: 90vw;
  min-height: 520px; max-height: 85vh;
}
```

All three states use identical `.modal-panel` — only content area changes.

---

## Self-Review

- ✅ No TBD placeholders
- ✅ Three states clearly defined with exact data mappings
- ✅ Component changes explicit: 1 new, 2 deleted, 3 modified
- ✅ Progress uses real backend fields from execution_summary
