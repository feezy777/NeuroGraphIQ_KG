# Field Completion Dialog UX Redesign

## Date: 2026-07-02

## Scope

优化数据中心字段补全弹窗 (`FieldCompletionModal`, `MultiTargetFieldCompletionModal`) 的交互体验。

## Changes

### 1. 固定弹窗尺寸

- `FieldCompletionModal`: `width: 800px, height: 600px`, body 区 `overflow-y: auto`
- `MultiTargetFieldCompletionModal`: `width: 860px, height: 640px`
- 在 `styles.css` 中对 `.data-center-field-completion-modal-panel` 设置固定 `height`
- Header/footer 使用 `flex-shrink: 0` 固定，body 使用 `flex: 1` + `overflow-y: auto`

### 2. 删除提示词工作台

- 移除 `FieldCompletionModal.tsx` 中 `PromptWorkbenchSection` 的 import 和 JSX
- 移除相关 state: `promptOverrides`, `showPromptPreview`
- `buildFieldCompletionRequest` 的 `promptOverrides` 参数改为传 `{}`
- 移除 `MultiTargetFieldCompletionModal.tsx` 中同样内容
- 不影响后端 API（prompt_overrides 字段保留但传空对象）

### 3. 实时补全记录

- `runCompletion` 的 async polling useEffect 在任务 terminal 时：
  ```ts
  const newRun: FieldCompletionRun = {
    id: runId,
    status: detail.status,
    target_type: mapping.targetType,
    target_count: selectedIds.length,
    ...
  }
  setRecentRuns(prev => [newRun, ...prev.slice(0, 19)])
  ```
- 不在 "current" tab 时也能看到新记录出现在 "recent_runs" tab 的 badge 或列表里
- 无需额外 API 请求

### 4. 侧边抽屉详情

- 点击 "最近补全记录" tab 中的记录行时：
  - 右侧滑出抽屉面板（复用 `.data-center-object-detail-drawer` 样式）
  - 显示: run_id, status badge, target_type, target_count, created_at
  - 下方: items 表格（target_id, field_name, old_value, suggested_value, applied_value, status, confidence）
- 抽屉内有关闭按钮和 backdrop 点击关闭
- 点击另一条记录切换抽屉内容

## Files

| File | Change |
|------|--------|
| `styles.css` | 固定弹窗尺寸、抽屉样式 |
| `FieldCompletionModal.tsx` | 尺寸、删提示词、实时记录、抽屉 |
| `MultiTargetFieldCompletionModal.tsx` | 尺寸、删提示词 |

## Verification

- `npm run build` 0 new errors
- 弹窗打开后尺寸固定不随内容变化
- 补全完成后 recent_runs tab 自动出现新记录
- 点击记录可打开侧边抽屉查看详情
