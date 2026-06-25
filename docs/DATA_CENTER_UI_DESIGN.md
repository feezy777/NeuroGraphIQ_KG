# Data Center UI Design

**Task:** Data Center Sidebar Consolidation and Knowledge Object Management UI  
**Date:** 2026-06-17  
**Status:** Completed (Step 9.4 + Step 9.5)

---

## 1. 为什么整合 Raw / Candidate / KG 对象

左侧导航原先将 Raw AAL3、Raw Macro96、候选脑区作为三个一级入口，与 LLM 提取页内的 Mirror/Final 对象管理功能重复，用户难以建立“数据资产管理”的统一心智。

**数据中心**成为只读/轻写（Generate Candidates）的数据对象管理入口；**LLM 提取**继续作为抽取/验证/晋升工作流入口。

---

## 2. 左侧导航调整

| 变更 | 说明 |
|------|------|
| 新增 | `数据中心` → `#/data-center` |
| 移除一级 | Raw AAL3 标签、Raw Macro96 行、候选脑区 |
| 保留 | 规则校验、人工审核、晋升记录（后续可合并为治理中心） |

---

## 3. 数据中心 Tab 结构

```
Data Center
├── Overview
├── Raw Data (AAL3 / Macro96)
├── Candidate Regions (Generate Candidates + table + drawer)
├── Mirror KG (connections / functions / circuits / triples / evidence)
├── Macro Clinical (steps / pf / memberships / cross / dual)
├── Final KG (9 object types, read-only)
└── Exports (packages + files + download)
```

---

## 4. Data Center 与 LLM Workflow 边界

| 操作 | Data Center | LLM 提取 |
|------|-------------|----------|
| 查看 Raw/Candidate/Mirror/Final/Export | ✅ | 部分（工作流内） |
| Generate Candidates | ✅（原功能） | ❌ |
| LLM 抽取 | ❌（跳转） | ✅ |
| Validation / Review / Promotion | ❌（跳转） | ✅ |
| Export 执行 | ❌（跳转） | ✅ |

---

## 5. 旧路由兼容

| 旧路由 | 跳转目标 |
|--------|----------|
| `#/raw-aal3` | `#/data-center?tab=raw&rawTab=aal3` |
| `#/raw-macro96` | `#/data-center?tab=raw&rawTab=macro96` |
| `#/candidates` | `#/data-center?tab=candidates` |
| `#/raw-aal3-labels` | 同上 aal3 |
| `#/raw-macro96-rows` | 同上 macro96 |
| `#/candidate-regions` | 同上 candidates |

跳转时显示短暂提示：“该功能已整合到数据中心”。

---

## 6. 对象类型表

| 层级 | 对象类型 | API |
|------|----------|-----|
| Raw | AAL3 labels, Macro96 rows | `fetchRawAal3Labels`, `listRawMacro96Rows` |
| Candidate | brain regions | `fetchCandidates`, `generateCandidates` |
| Mirror KG | connection, function, circuit, triple, evidence | `listMirror*` |
| Macro Clinical | circuit_step, projection_function, membership, cross/dual results | `listMirrorCircuitSteps`, etc. |
| Final KG | circuit, step, projection, … | `listFinalMacroClinicalObjects` |
| Export | packages, files | `listFinalKgExports`, `listFinalKgExportFiles` |

---

## 7. 新增文件

```
frontend/src/pages/data-center/
├── DataCenterPage.tsx
├── dataCenterTypes.ts
├── useDataCenterCounts.ts
├── DataCenterOverview.tsx
├── DataCenterTabBar.tsx
├── DataCenterSummaryCards.tsx
├── RawDataPanel.tsx
├── CandidateRegionsPanel.tsx
├── MirrorKgPanel.tsx
├── MacroClinicalDataPanel.tsx
├── FinalKgDataPanel.tsx
├── ExportPackagesPanel.tsx
├── DataObjectDetailDrawer.tsx
├── LegacyDataCenterRedirect.tsx
└── formalFieldMappings.ts   ← Step 10.1 设计；Step 10.2 已接入 Mirror/Macro 表
```

---

## 8. 后续计划

- 将规则校验、人工审核、晋升记录合并为“治理中心”
- Final Knowledge Pipeline（Promotion → Browser → Export 串联）
- Data Center 与 Session Scope 深度联动（batch/resource 全局 filter）

### 8.1 Formal Field Alignment（Step 10.1 — 设计完成）

**目标：** Mirror KG / Macro Clinical 表格按 **final KG 正式字段** 展示；missing fields badge；字段补全入口占位。

| 文档 | 说明 |
|------|------|
| `docs/DATA_CENTER_FORMAL_FIELD_ALIGNMENT.md` | Mirror→Final 映射、Tab 设计、missing/completion 规则 |
| `docs/UNIVERSAL_FIELD_COMPLETION_DESIGN.md` | 通用 DeepSeek 字段补全 API / prompt / 写入边界 |
| `frontend/src/pages/data-center/formalFieldMappings.ts` | 列定义 + enrichable/required 字段（Step 10.2 接入） |

**实现顺序：** Step 10.2 formal 列 UI → 10.3 后端 API → 10.4 批量补全 UI → 10.5 抽取弹窗 → 10.6 validation/review。

**边界：** 字段补全只写 mirror/candidate；不写 final_* / kg_*；不自动 promote。

---

## 9. Fixed Layout and Pagination（Step 9.5）

### 布局

| 区域 | 行为 |
|------|------|
| 左侧 Sidebar | `position: sticky; height: calc(100vh - topbar); overflow-y: auto` |
| 根 `.layout` | `height: 100vh; overflow: hidden` |
| Data Center 主区 | `main.main-data-center`：`overflow: hidden; flex column` |
| Header / Boundary / Summary / Tab | `data-center-header-static`，不随表格滚动 |
| Filter bar | `data-center-filter-bar`，固定于 panel 顶部 |
| 表格区域 | `data-center-table-scroll` 独立纵向/横向滚动 |
| 表头 | `thead th { position: sticky; top: 0 }` 仅在 `.data-center-table-scroll` 内 |
| 分页器 | `data-center-pagination` 紧贴表格下方，不进入滚动区 |
| 底部日志栏 | `main.main-data-center` 预留 `padding-bottom`（collapsed 40px / expanded 300px） |

### 分页

- **策略**：纯前端分页，不改后端 API
- **每页条数**：固定 20（`DATA_CENTER_PAGE_SIZE`）
- **Hook**：`useDataCenterPagination` — filter/tab 变化时 `resetKeys` 重置 page=1；total 变小时自动修正页码
- **组件**：`DataCenterPagination` — 共 X 条 / 第 A–B 条 / 第 N/M 页 / 上一页 / 下一页
- **封装**：`DataCenterTableRegion` 统一 table + pagination 结构

### 已接入分页的表格

| Panel | 说明 |
|-------|------|
| Raw Data (AAL3 / Macro96) | 二级 tab 各自独立 page，切换 tab 重置 |
| Candidate Regions | Generate Candidates + summary 固定，表格分页 |
| Mirror KG | 各二级 tab 独立分页 |
| Macro Clinical | 各二级 tab 独立分页 |
| Final KG | 各 object type 独立分页 |
| Exports | packages + files 分区各自分页 |
| Overview | 无表格分页；内容区可独立滚动 |

---

## 10. 边界（不变）

- 不改后端 API
- 不改数据库 / migration
- 数据中心不执行 LLM / validation / review / promotion / export run
