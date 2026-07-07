# A4 图谱探索 + A6 字段补全增强 — 设计规格

> **日期**: 2026-07-01
> **状态**: 全部 3 节设计确认
> **范围**: A4 Final KG 图可视化 + A6 Mirror KG 字段补全增强

---

## 决策记录

| # | 决策 | 选择 |
|---|------|------|
| 1 | A6 范围 | **C** — 完整改造：提取结果弹窗 + 数据中心批量补全 + 新 prompt 模板 |
| 2 | A4 入口 | **B** — 独立侧边栏导航入口"图谱探索" |
| 3 | A4 初始视图 | **B** — 全局概览：加载全脑网络，支持筛选/缩放/点击聚焦 |

---

## 一、整体架构

```
┌─ 前端新增 ───────────────────────────────────────────────────────┐
│                                                                  │
│  A4: 图谱探索页 (FinalKgGraphPage)                                │
│  ┌──────────────────────────────────────────────────────────┐    │
│  │  侧边栏 (FinalKgGraphSidebar)                             │    │
│  │  ├─ Atlas/粒度/类型 筛选器                                │    │
│  │  ├─ 脑区搜索（搜索 → 高亮/聚焦节点）                       │    │
│  │  ├─ 选中节点详情（名称/功能/连接数/证据）                   │    │
│  │  └─ 图例（节点类型颜色、边类型样式）                       │    │
│  ├──────────────────────────────────────────────────────────┤    │
│  │  画布 (FinalKgGraphCanvas)                                │    │
│  │  ├─ React Flow / xyflow 力导向布局                         │    │
│  │  ├─ 节点: 脑区 (圆) / 电路 (菱形) / 功能 (三角)            │    │
│  │  ├─ 边: 连接 (实线) / 功能关联 (虚线) / 回路成员 (点线)    │    │
│  │  ├─ 交互: 拖拽/缩放/悬停提示/点击展开邻域/右键菜单         │    │
│  │  └─ Minimap + Controls                                     │    │
│  └──────────────────────────────────────────────────────────┘    │
│                                                                  │
│  A6: 字段补全增强                                                │
│  ┌──────────────────────────────────────────────────────────┐    │
│  │  PoolExtractionModal 结果弹窗 → "字段补全"按钮             │    │
│  │  MirrorKgPanel → 工具栏 "批量字段补全"按钮                 │    │
│  │  新增 prompt 模板: projection_name_cn/en/description       │    │
│  └──────────────────────────────────────────────────────────┘    │
│                                                                  │
├─ 后端新增 ───────────────────────────────────────────────────────┤
│                                                                  │
│  A4: 现有 API 已足够（/api/final-macro-clinical/browser/graph）   │
│  无需新增后端端点                                                │
│                                                                  │
│  A6: 新增 3 个 prompt 模板                                       │
│  ├─ projection_field_completion_name_cn_v1                       │
│  ├─ projection_field_completion_name_en_v1                       │
│  └─ projection_field_completion_description_v1                   │
│                                                                  │
└──────────────────────────────────────────────────────────────────┘
```

---

## 二、A4 图谱探索页

### 2.1 数据流

```
侧边栏筛选器变化
  │ atlas=AAL3, granularity=macro, type=brain_region
  ▼
GET /api/final-macro-clinical/browser/graph
  ?center_type=brain_region
  &depth=1
  &include_functions=true
  &limit=200
  ▼
FinalGraphResponse { nodes: FinalGraphNode[], edges: FinalGraphEdge[] }
  ▼
React Flow 渲染
  ├─ 节点: id → ReactFlowNode { position, data: { label, type, metadata } }
  ├─ 边: id → ReactFlowEdge { source, target, label, animated, style }
  └─ 布局: force-directed 初始布局
  ▼
用户点击节点
  ├─ 侧边栏更新详情
  └─ 可选: 展开邻域 → 追加请求该节点的 graph → 合并 nodes/edges
```

**依赖**：
- `@xyflow/react` — React Flow v12（最新）
- API: 现有 `GET /api/final-macro-clinical/browser/graph`

### 2.2 节点与边设计

**节点类型**：

| 类型 | 形状 | 颜色 | 大小 | 来源数据 |
|------|------|------|------|----------|
| brain_region | 圆形 | 按颗粒度着色 (macro=蓝, meso=绿, sub=橙) | 半径 20px | `final_brain_regions` |
| circuit | 菱形 | 紫色 | 半径 16px | `final_region_circuits` |
| circuit_step | 小圆 | 浅紫 | 半径 12px | `final_circuit_steps` |
| function | 三角 | 金色 | 半径 14px | `final_region_functions` |

**边类型**：

| 类型 | 线型 | 样式 | 来源数据 |
|------|------|------|----------|
| structural_connection | 实线 | 粗 2px，深蓝 | `connection_type=anatomical` |
| functional_connection | 实线 | 粗 2px，橙色 | `connection_type=functional` |
| has_function | 虚线 | 细 1px，金色 | `final_region_functions` |
| circuit_member | 点线 | 细 1px，紫色 | `final_circuit_regions` |
| circuit_step_link | 箭头线 | 粗 1.5px，紫色 | `final_circuit_steps` |
| projection_member | 实线 | 细 1px，灰色 | `final_circuit_projection_memberships` |

**悬停 tooltip**：
- 节点: `label + 类型 + atlas + granularity`
- 边: `connection_type + directionality + confidence`

**右键菜单**：展开邻域 / 查看详情 / 固定位置 / 隐藏

### 2.3 前端文件结构

```
frontend/src/pages/graph-explorer/
├── FinalKgGraphPage.tsx          # 主页面（侧边栏 + 画布）
├── FinalKgGraphCanvas.tsx        # React Flow 画布
├── FinalKgGraphSidebar.tsx       # 筛选 + 搜索 + 详情 + 图例
├── FinalKgGraphNode.tsx          # 自定义节点渲染
├── FinalKgGraphEdge.tsx          # 自定义边渲染
├── FinalKgGraphPage.css
├── useGraphData.ts               # 数据获取 hook
└── graphLayout.ts                # 布局辅助
```

### 2.4 导航

侧边栏新增入口：
```
仪表盘 → 资源登记 → 文件管理 → 批次管理 → LLM 提取 → 数据中心
→ Mirror KG 浏览 → 规则校验 → 人工审核 → 晋升记录 → 图谱探索 → 设置
```

路由：`/graph-explorer`

---

## 三、A6 字段补全增强

### 3.1 提取结果弹窗 → 字段补全

在 `PoolExtractionModal` 结果页和 `DryRunDetailPanel` 底部增加：

```tsx
<button className="llm-btn llm-btn-secondary"
  onClick={() => {
    // 打开 FieldCompletionModal，预填 target_type=projection,
    // target_ids=本次提取产出的 connection IDs
    // field_scope=missing_only
  }}
>
  📝 字段补全 ({missingFieldCount})
</button>
```

**数据传递**：从 workflow run result 中提取 `created_connection_ids`，传给 `FieldCompletionModal`。

### 3.2 数据中心批量补全

在 `MirrorKgPanel` 连接/回路 Tab 的工具栏新增：

```tsx
<button className="llm-btn llm-btn-secondary"
  disabled={selectedRows.length === 0}
  onClick={() => openFieldCompletionModal(selectedRowIds)}
>
  📝 批量字段补全 ({selectedRows.length})
</button>
```

### 3.3 新增 Prompt 模板

在 `llm_prompt_defaults.py` 中新增 3 个模板：

| Template Key | target_type | field_name | Purpose |
|---|---|---|---|
| `projection_field_completion_name_cn_v1` | projection | name_cn | 连接中文名称补全 |
| `projection_field_completion_name_en_v1` | projection | name_en | 连接英文名称补全 |
| `projection_field_completion_description_v1` | projection | description | 连接描述补全 |

在 `field_completion_prompt_engineering.py` 的 `FIELD_PROMPT_KEY_MAP` 中注册映射。

### 3.4 不做的

- 不新增后端 API（已有 UniversalFieldCompletionService 完整支持 projection）
- 不修改 field_completion_registry（projection 的 enrichable_fields 已包含 name_en/name_cn/description）
- 不修改 Mirror KG 写入逻辑

---

## 四、文件变更清单

### 新建

| 文件 | 用途 |
|------|------|
| `frontend/src/pages/graph-explorer/FinalKgGraphPage.tsx` | 图谱主页面 |
| `frontend/src/pages/graph-explorer/FinalKgGraphCanvas.tsx` | React Flow 画布 |
| `frontend/src/pages/graph-explorer/FinalKgGraphSidebar.tsx` | 筛选/搜索/详情面板 |
| `frontend/src/pages/graph-explorer/FinalKgGraphNode.tsx` | 自定义节点 |
| `frontend/src/pages/graph-explorer/FinalKgGraphEdge.tsx` | 自定义边 |
| `frontend/src/pages/graph-explorer/FinalKgGraphPage.css` | 样式 |
| `frontend/src/pages/graph-explorer/useGraphData.ts` | 数据 hook |
| `frontend/src/pages/graph-explorer/graphLayout.ts` | 布局 |

### 修改

| 文件 | 变更 |
|------|------|
| `frontend/package.json` | 新增 `@xyflow/react` 依赖 |
| `frontend/src/App.tsx` | 注册 `/graph-explorer` 路由 |
| `frontend/src/components/WorkbenchLayout.tsx` | 侧边栏新增"图谱探索"入口 |
| `frontend/src/pages/llm-extraction/components/PoolExtractionModal.tsx` | 结果弹窗增加"字段补全"按钮 |
| `frontend/src/pages/data-center/MirrorKgPanel.tsx` | 工具栏增加"批量字段补全"按钮 |
| `backend/app/services/llm_prompt_defaults.py` | 新增 3 个 projection 字段补全模板 |
| `backend/app/services/field_completion_prompt_engineering.py` | FIELD_PROMPT_KEY_MAP 新增 3 条映射 |

---

## 五、验收标准

### A4 图谱探索

1. 侧边栏新增"图谱探索"菜单入口，点击进入全屏图谱页
2. 默认加载选中 atlas/granularity 的全脑网络图
3. 节点按类型/颜色正确渲染，边按连接类型显示不同样式
4. 支持拖拽、缩放、悬停 tooltip、右键菜单
5. 侧边栏筛选器可切换 atlas/granularity/类型
6. 搜索脑区可定位并高亮节点
7. 点击节点在侧边栏显示详情
8. 点击节点可展开 1 度邻域
9. Minimap 和缩放控件正常工作
10. 不破坏现有 Final KG 数据写入和查询

### A6 字段补全

11. 提取结果弹窗显示"字段补全"按钮，可一键对本次产出连接执行字段补全
12. 数据中心连接/回路表工具栏有"批量字段补全"按钮
13. 3 个新 prompt 模板已注册且可被 UniversalFieldCompletionService 调用
14. 字段补全不破坏已有 Mirror KG 数据和人工审核流程
15. 前端 build 0 TS errors / 后端 tests pass
