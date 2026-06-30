# Pool 提取弹窗两步分页 + 脑区名称修正

**日期**: 2026-06-30  
**状态**: 已批准  
**约束**: 不改后端 API，仅改前端 `PoolExtractionModal.tsx`

## 背景

当前"连接 + 功能提取"弹窗将所有内容放在单页中，脑区池表格的"脑区名称"列实际显示 UUID（因 `candidateLabels` 始终为空对象）。需要改为两步分页向导，并让"脑区名称"显示真实中文名。

## 改动范围

仅一个文件：`frontend/src/pages/llm-extraction/components/PoolExtractionModal.tsx`

## 一、两步分页

### 新增状态

```typescript
const [wizardStep, setWizardStep] = useState<1 | 2>(1)
```

打开弹窗/关闭时重置为 1。

### Step 1: 脑区池选择

保留内容：
- 提取范围摘要（Atlas / Granularity / 外部已选 / 池中脑区 / 本次已选 / 本次配对）
- 搜索框 + 操作按钮行（全选 / 取消选择 / 用外部选中替换 / 移除选中）
- 脑区勾选表格
- "池与外部已选不一致"警告横幅

移除内容：
- 模型配置（ModelSelector + Dry run）

底部按钮：**取消 / 下一步**  
"下一步"在 `!pool || selectedExtractionIds.length < 2 || addingMembers || !poolMatchesExternal` 时禁用。

### Step 2: 模型配置

显示内容：
- 简短范围摘要行："已选 {n} 个脑区 · {m} 对 · 约 {k} 包"
- ModelSelector 组件（provider / model / 自定义 model）
- Dry run checkbox

底部按钮：**上一步 / 取消 / 开始提取 ({n} 区)**  
"上一步"切回 Step 1，保留所有勾选状态。  
"开始提取"行为零改动，直接调用现有 `handleStartExtraction`。

## 二、脑区名称修正

### 数据获取

在 pool 加载完成后（`useEffect`），调用 `fetchCandidates({ resource_id: pool.resource_id, limit: 500 })` 拉取候选区数据。从返回值中构建 `candidateLabels: Record<string, string>`：

```typescript
const labels: Record<string, string> = {}
for (const c of candidates) {
  labels[c.id] = c.cn_name ?? c.en_name ?? c.raw_name ?? c.id
}
```

### 表格列调整

| 列 | 当前 | 修改后 |
|----|------|--------|
| ☑ 勾选 | 40px | 40px（不变） |
| # 序号 | 自适应 | 40px |
| 脑区名称 | 显示 `m.label`（= UUID） | 显示 `cn_name ?? en_name ?? shortId` |
| ID | `shortId(m.candidate_id)` | 自适应（不变） |

### 搜索增强

- placeholder: `"搜索 candidate_id..."` → `"搜索 ID 或名称..."`
- 搜索逻辑：同时匹配 `label` + `candidate_id`

## 三、不变部分

- `handleStartExtraction` 零改动
- Progress (`renderProgress`) 和 Result (`renderResult`) 两态完全不动
- `selectedMemberCandidateIds`、`searchTerm` 等所有 state 跨 wizardStep 保持
- 其他 workflowType 的弹窗行为不受影响
- 不修改任何后端 API

## 验证

1. `npm run build` 零 TypeScript 错误
2. 手动验证：打开弹窗 → 勾选脑区 → 下一步 → 上一步 → 勾选状态保留
3. 手动验证：脑区名称列显示中文名而非 UUID
4. 手动验证：搜索可同时匹配中文名和 ID
