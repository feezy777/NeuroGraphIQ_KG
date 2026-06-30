# Candidate Pool Frontend Integration Design

**Date:** 2026-06-25
**Status:** Approved
**Depends on:** Backend candidate pool API (already implemented)

---

## Problem Statement

The backend now supports candidate pools for cross-batch, full all_pairs connection extraction. But the frontend has no UI for it — users can't create pools, see accumulated state, or trigger full extractions. The pool feature needs to blend into the existing LLM Extraction page without disrupting the current one-shot extraction workflow.

---

## Design Principles

1. **池对用户几乎不可见** — 后台自动累积，不需用户手动管理
2. **保持现有流程不变** — 直接提取按钮、快速卡片全部保留
3. **准确性优先** — 严格按三元组 (atlas, granularity, family) 分池，不允许跨 atlas 混入
4. **统一弹窗风格** — 全量提取弹窗与系统内其他弹窗视觉一致，但更大

---

## Solution Overview

### 1. Auto-Pool by Scope

系统自动按 `(source_atlas, granularity_level, granularity_family)` 三元组分池：

```
AAL3 + macro + macro_clinical    → Pool A
Brainnetome + sub_connectivity   → Pool B
HCP-MMP + meso_anatomical        → Pool C
```

- 用户选择候选时，前端按候选的 scope 属性自动归类
- 后端 `POST /api/candidates/pools` 创建池时校验一致性
- 混合不同 atlas → 后端 400 拒绝，前端不发送

### 2. Top Status Bar (`CandidatePoolBar`)

固定在 LLM 提取页面顶部（面包屑下方，内容上方），紧凑一行：

```
┌──────────────────────────────────────────────────────────────────┐
│ 🧠 AAL3 · macro    已累积 67/96 脑区 · 预估 2,211 对            │
│ [查看池详情]  [+ 添加选中 (12)]  [⚡ 全量提取]  [清空]          │
└──────────────────────────────────────────────────────────────────┘
```

**显示规则：**
- 当前 scope 的池为空 → 整条隐藏
- 有累积 → 始终显示（包括切换页面后再回来）
- 提取进行中 → 变为进度条模式：`已处理 23/74 包 · 发现 187 条连接 · 3 包异常`

**按钮行为：**
- `查看池详情` → 展开下拉/侧栏，显示池内全部脑区列表，支持移除单个
- `+ 添加选中 (N)` → 把表格中当前勾选的 N 个候选加入池（不触发提取），N=0 时灰色
- `⚡ 全量提取` → 打开全量提取确认弹窗
- `清空` → 二次确认后清空当前池

### 3. Organic Integration with Existing Flow

**直接提取时自动累积：**

用户点击快速提取卡片（连接/功能/回路）时，选中的候选在发送 API 的同时，**静默追加到后台池**。用户无需额外操作。

快速卡片下方增加一行提示：
```
📥 选中的 12 个脑区也会自动加入候选池（当前池共 55→67）
```

**候选表格新增池标记：**
- 已在池中的候选行，行首显示一个小的 🧠 icon（tooltip: "已在提取池中"）
- 全选时如果全部已在池中，状态条更新 count

### 4. Full Extraction Modal (统一风格，加大尺寸)

触发：状态条「全量提取」按钮 或 快速卡片区「全量提取」链接。

```
┌──────────────────────────────────────────────────────────────┐
│  ⚡ 全量连接提取                                    [✕]      │
│                                                              │
│  ┌──────────────────────────────────────────────────────┐   │
│  │ 📊 提取范围                                           │   │
│  │ Atlas:         AAL3                                   │   │
│  │ Granularity:   macro / macro_clinical                 │   │
│  │ 脑区数:        67 / 96                                │   │
│  │ 配对量:        2,211 对 (all_pairs)                   │   │
│  │ 预估包数:      74 包 (30 对/包，5 路并发)             │   │
│  └──────────────────────────────────────────────────────┘   │
│                                                              │
│  ┌──────────────────────────────────────────────────────┐   │
│  │ ⚙️ 模型配置                                           │   │
│  │ Provider:  [DeepSeek ▼]    Model: [deepseek-v4-pro ▼]│   │
│  │ □ Dry run (仅预览，不实际调用 LLM)                    │   │
│  └──────────────────────────────────────────────────────┘   │
│                                                              │
│  ┌──────────────────────────────────────────────────────┐   │
│  │ 📋 提取内容                                           │   │
│  │ ☑ 连接提取 (Connection)                               │   │
│  │ ☐ 连接功能提取 (Projection Function)                  │   │
│  └──────────────────────────────────────────────────────┘   │
│                                                              │
│              [取消]    [🚀 开始全量提取]                     │
└──────────────────────────────────────────────────────────────┘
```

**统一弹窗样式规范（系统内所有弹窗遵循）：**

```css
.modal-overlay {
  /* 全屏半透明遮罩，居中 */
  background: rgba(0, 0, 0, 0.45);
  z-index: 1000;
  display: flex; align-items: center; justify-content: center;
}
.modal-panel {
  background: #fff; border-radius: 12px; box-shadow: 0 8px 40px rgba(0,0,0,0.12);
  max-width: 720px; width: 90vw; max-height: 85vh; overflow-y: auto;
  padding: 28px 32px;
}
.modal-panel.wide {
  max-width: 900px;  /* 全量提取弹窗专用 */
}
.modal-header {
  display: flex; justify-content: space-between; align-items: center;
  margin-bottom: 24px; padding-bottom: 16px;
  border-bottom: 1px solid #f0f0f0;
}
.modal-header h3 { margin: 0; font-size: 18px; font-weight: 600; color: #1a1a2e; }
.modal-footer {
  margin-top: 28px; padding-top: 16px;
  border-top: 1px solid #f0f0f0;
  display: flex; justify-content: flex-end; gap: 12px;
}
.modal-section {
  background: #f8f9fc; border-radius: 8px; padding: 16px 20px;
  margin-bottom: 16px;
}
.modal-section-title {
  font-size: 13px; font-weight: 600; color: #6b7280;
  text-transform: uppercase; letter-spacing: 0.5px; margin-bottom: 12px;
}
```

**尺寸规范：**
- 普通弹窗: `max-width: 720px`
- 全量提取弹窗: `max-width: 900px`（加 `.wide` class）
- 两者共用相同的 header/footer/section 结构

### 5. 进度模式

提取进行中，顶部状态条切换为进度模式：

```
┌──────────────────────────────────────────────────────────────┐
│ ⚡ 提取中  AAL3 · macro                                      │
│ ████████████░░░░░░  47/74 包  ·  已发现 187 条连接           │
│ [查看详情]  [⏸ 暂停]                                        │
└──────────────────────────────────────────────────────────────┘
```

进度条使用项目统一的医学蓝 `#2563eb`，平滑动画。

---

## Component Tree

```
LlmExtractionPage
├── CandidatePoolBar          ← NEW: 顶部状态条
│   ├── PoolStatus (显示累积计数)
│   ├── PoolActions (按钮组)
│   └── PoolProgress (提取进行中时替换)
├── DataFirstCandidatesTab    ← MODIFY: 行首池标记 + 自动追加
│   └── (existing candidate table)
├── LlmTaskToolbar            ← UNCHANGED
├── Quick Extraction Cards    ← MODIFY: 底部加自动累积提示
├── FullExtractionModal       ← NEW: 全量提取确认弹窗
│   ├── ExtractionScopePanel
│   ├── ModelSelector (复用现有)
│   └── ExtractionTypeCheckboxes
└── ExtractionResultModal     ← UNCHANGED
```

---

## API Dependencies (all already implemented)

| Method | Endpoint | Usage |
|--------|----------|-------|
| POST | `/api/candidates/pools` | 创建/获取当前 scope 的池 |
| GET | `/api/candidates/pools?source_atlas=&granularity_level=` | 查询池状态 |
| POST | `/api/candidates/pools/{id}/members` | 添加候选到池 |
| DELETE | `/api/candidates/pools/{id}/members` | 从池中移除候选 |
| DELETE | `/api/candidates/pools/{id}` | 清空池 |
| POST | `/api/llm-extraction/composite-workflow` | 触发提取（传 `candidate_pool_id`） |
| GET | `/api/llm-extraction/composite-workflow/{id}` | 轮询进度 |

---

## Files to Create/Modify

| File | Action | Description |
|------|--------|-------------|
| `frontend/src/pages/llm-extraction/components/CandidatePoolBar.tsx` | Create | 顶部状态条组件 |
| `frontend/src/pages/llm-extraction/components/FullExtractionModal.tsx` | Create | 全量提取确认弹窗 |
| `frontend/src/pages/llm-extraction/hooks/useCandidatePool.ts` | Create | 池状态管理 hook |
| `frontend/src/api/endpoints.ts` | Modify | 新增 pool API 函数 |
| `frontend/src/pages/LlmExtractionPage.tsx` | Modify | 集成状态条 + 弹窗 + 自动追加逻辑 |
| `frontend/src/pages/llm-extraction/components/DataFirstCandidatesTab.tsx` | Modify | 行首池标记 + 选中自动追加 |
| `frontend/src/styles.css` | Modify | 统一弹窗样式 |

---

## Spec Self-Review

- ✅ No TBD/TODO placeholders
- ✅ Internal consistency: pool bar + modal + auto-accumulate all reference same hook
- ✅ Scope: Focused on frontend UI only; backend already done
- ✅ No ambiguity: exact component tree, API mapping, CSS specs
- ✅ Unified modal style specified with exact CSS values
