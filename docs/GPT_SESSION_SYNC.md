# GPT 会话同步 — NeuroGraphIQ KG V3（MVP 1 重建进度）

> **用途**：将此文件全文或摘要粘贴给 GPT/Codex，作为下一轮 Vibe Coding 的上下文。  
> **权威架构文档**：`docs/NEUROGRAPHIQ_VIBE_CODING_GUIDE.md`  
> **最后更新**：2026-06-15 · **当前实现快照已同步（§0）** · 详见各模块完成节（§15–§LLM Direction）

---

## 0. 当前实现快照（2026-06-15 同步）

> 本节汇总**仓库当前真实实现**，供 GPT/Codex 快速对齐。细节见后续各 §；架构目标见 `docs/NEUROGRAPHIQ_KG_V3_TARGET_ARCHITECTURE.md`。

### 0.1 版本与测试

| 项 | 当前值 |
|----|--------|
| 后端 API 版本 | `3.3.0-mvp2-llm-extraction`（`backend/app/main.py`） |
| 后端 pytest | **371 passed, 9 skipped**（2026-06-15） |
| 前端 | Vite + React + TS；**15 个页面**；`npm run build` 通过 |
| 开发端口 | 后端 `8002`（`run_server.py`）；前端 Vite `5173` |

### 0.2 数据库拓扑

| 库 | 角色 | 说明 |
|----|------|------|
| **`NeuroGraphIQ_KG_V3`** | **正式库（Final KG）** | 用户 DBeaver 确认；schema：`macro_clinical`、`meso_anatomical`、`sub_connectivity`、`fine_cyto`、`molecular_attr`、`public` |
| `neurographiq_kg_v3_mvp1_e2e` | E2E / 开发测试 | 001–020 migration 主验证库；含 `final_brain_regions`（开发期同库） |
| `neurographiq_kg_v3_wb` | 工作台 | `.env.example` 默认 `DATABASE_URL` |
| `neurographiq_kg_v3_candidate` | 候选 CLI 镜像 | `CANDIDATE_DATABASE_URL` / 当前 `FINAL_DATABASE_URL` 默认 |

**偏差**：Promotion 当前写入 E2E/工作台库内 `final_brain_regions`，**尚未**对接物理正式库 `NeuroGraphIQ_KG_V3`（目标见架构文档 Phase H）。

### 0.3 后端模块（均已注册 router）

| 模块 | 前缀 | 状态 |
|------|------|------|
| Resource Registry | `/api/resources` | ✅ CRUD + 软删 + 破坏性级联删除 |
| Resource Files | `/api/resources/{id}/files`、`/api/files` | ✅ 上传/预览/下载/中间态 |
| File Normalization | `/api/files/{id}/normalize` 等 | ✅ 中间态生成（label_table、macro_region_table 等） |
| Workspace Files | `/api/workspace-files` | ✅ 公共文件池 + attach |
| Import Batches | `/api/import-batches` | ✅ CRUD + 状态机 + **rollback** + **run-history** |
| Raw Parsing AAL3 | `/api/raw-parsing`、`/api/import-batches/{id}/parse-aal3` | ✅ |
| Raw Parsing Macro96 | `parse-macro96`、`/api/raw-parsing/macro96-rows` | ✅ |
| Candidate DB | `/api/candidates` | ✅ AAL3 + **Macro96 分路生成** |
| Rule Validation | `/api/rule-validation` | ✅ |
| Human Review | `/api/human-review` | ✅ |
| Promotion | `/api/promotion` | ✅ → `final_brain_regions` |
| Final DB Query | `/api/final-regions` | ✅ 只读 |
| LLM Extraction | `/api/llm-extraction` | ✅ DeepSeek 候选侧字段补全 |
| Settings | `/api/settings` | ✅ DeepSeek + Kimi 配置项（Kimi 提取 API 未接） |
| Database Admin | `/api/database` | ✅ 连接状态 + 切换库 |
| Workbench Pipeline | `/api/workbench/import-batches/{id}/overview` | ✅ 只读聚合 |

### 0.4 前端页面（15）

| 路由 | 页面 | 要点 |
|------|------|------|
| `#/` | Dashboard | 健康检查、库切换、统计 |
| `#/resources` | Resources | CRUD、Macro 预设、归档/恢复/ purge |
| `#/files` | Files | 资源文件 + Workspace 公共文件；**xlsx 预览已修复** |
| `#/import-batches` | Import Batches | CRUD、parser-aware 文件选择 |
| `#/import-pipeline` | Import Pipeline | 阶段工作区、rollback、re-execute、run-history、阶段数据跳转 |
| `#/raw-aal3` | Raw AAL3 | raw labels 列表 |
| `#/raw-macro96` | Raw Macro96 | 96 行 raw 列表 |
| `#/candidates` | Candidates | 候选脑区 + URL 筛选 |
| `#/llm-extraction` | LLM Extraction | **仅 Region 字段补全**（DeepSeek） |
| `#/rule-validation` | Rule Validation | 批量/单条校验 |
| `#/human-review` | Human Review | 提交/approve/reject |
| `#/promotions` | Promotions | 晋升 + final 查询入口 |
| `#/final-regions` | Final Regions | 只读 |
| `#/settings` | Settings | 语言、DeepSeek/Kimi API、连通性测试 |

### 0.5 双导入链路（均已打通）

**AAL3**：
```
upload XML → batch(parse-aal3) → raw_aal3_region_labels
  → generate-candidates → candidate_brain_regions
  → rule → review → promote → final_brain_regions
```

**Macro96**：
```
upload Brain volume list.xlsx → 中间态 macro_region_table_v1
  → batch(parse-macro96) → raw_macro96_region_rows (96)
  → generate-macro96-candidates → candidate_brain_regions (source_raw_table)
  → rule → review → promote → final_brain_regions
```

AAL3 与 Macro96 **不混表**；禁止对 Macro96 batch 调用 `generate-candidates`（返回 400）。

### 0.6 Migration 清单（001–020，均手动执行）

| # | 文件 | 要点 |
|---|------|------|
| 001–008 | MVP 1 核心 | registry → promotion |
| 009 | `009_llm_extraction.sql` | `candidate_llm_extractions` |
| 010 | `010_file_normalization.sql` | 中间态表 |
| 011 | `011_workspace_files.sql` | 公共文件 |
| 012 | `012_extend_intermediate_artifact_kinds.sql` | macro_region_table 等 |
| 013 | `013_destructive_resource_delete_records.sql` | 级联删除审计 |
| 014–015 | macro role | 文件/批次 macro 角色 |
| 016–017 | Macro96 raw | `raw_macro96_region_rows` + events |
| 018 | Macro96 candidate | `source_raw_table` |
| 019–020 | Rollback | rollback records + event types |

### 0.7 已实现 vs 未实现（与架构目标对比）

| 能力 | 状态 |
|------|------|
| Region 导入 / candidate / review / promote | ✅ |
| Macro96 Excel → raw → candidate（96 行） | ✅ |
| File 中间态 + spreadsheet 预览修复 | ✅ |
| Import Pipeline 工作区 + rollback + 阶段数据查看 | ✅ |
| LLM Region 字段补全（DeepSeek） | ✅ |
| LLM 同颗粒度 connection/circuit/function | ❌ 仅文档 |
| Mirror KG 表与工作台展示 | ❌ 仅文档 |
| Triple candidate / promotion | ❌ 仅文档 |
| Promotion 写入物理库 `NeuroGraphIQ_KG_V3` | ❌ 当前写 E2E/工作台库 |
| Kimi LLM 提取 API | ❌ Settings 有配置项，无提取路由 |

### 0.8 架构文档索引

| 文档 | 内容 |
|------|------|
| `NEUROGRAPHIQ_KG_V3_TARGET_ARCHITECTURE.md` | 七层架构、正式库拓扑、MVP 路线图 |
| `LLM_SAME_GRANULARITY_COMPLETION_DESIGN.md` | LLM 补全任务与 JSON schema（规划） |
| `MIRROR_KG_AND_FINAL_PROMOTION_DESIGN.md` | Mirror KG 与晋升（规划） |
| `TRIPLE_MODEL_AND_ONTOLOGY_DESIGN.md` | 三元组模型（规划） |
| `MACRO_96_REGION_POOL.md` | 96 池 Excel 规范 |

---

## 1. 项目决策（不变）

- 旧 V3 工作台（React UI + legacy staging/kg 路由）已**推翻并清理**。
- 在 `docs/NEUROGRAPHIQ_VIBE_CODING_GUIDE.md` 约束下**从零重建** MVP 1 确定性导入闭环。
- **当前阶段不使用 Docker**；migration **不自动执行**；本地 venv + PostgreSQL + `run_server.py`（端口 8002）。
- Workbench Settings 使用本地 runtime JSON：`backend/data/runtime/settings.local.json`；该文件仅本地运行使用，已加入 `.gitignore`，不得提交 API Key。

---

## 2. MVP 1 执行进度（✅ 10/10 全部完成）

| 步骤 | 模块 | 状态 | 说明 |
|------|------|------|------|
| 1 | Resource Registry | ✅ 已完成 | `atlas_resources` CRUD + 软删除 |
| 2 | File Upload & File Management | ✅ 已完成 | 本地 uploads + SHA256 去重 + `resource_files` |
| 3 | Import Batch / Task | ✅ 已完成 | `import_batches` + 状态机 + 事件日志 |
| 4 | Raw Parsing for AAL3 | ✅ 已完成 | XML label → `raw_aal3_region_labels`（**非 candidate**） |
| 5 | Candidate DB | ✅ 已完成 | raw labels → `candidate_brain_regions`（`candidate_created`），batch→`candidate_generated` |
| 6 | Rule Validation | ✅ 已完成 | 确定性规则 → `rule_validation_runs` + `candidate_rule_validation_results`；candidate→`rule_passed`/`rule_failed` |
| 7 | Human Review | ✅ 已完成 | `candidate_review_records`；candidate→`manual_review_pending`→`manual_approved`/`manual_rejected`（不写 final_*/不 promotion） |
| 8 | Promotion → `final_*` | ✅ 已完成 | `final_brain_regions` + `promotion_records`；candidate→`promoted_to_final`；仅 manual_approved 可晋升；全链路溯源 |
| 9 | Final DB Query | ✅ 已完成 | 只读查询 `final_brain_regions`；关键词搜索；统计摘要；溯源+审计 provenance API；不写任何表 |
| 10A | Workbench UI Foundation | ✅ 已完成 | Vite + React + TS；10 只读页面；hash 路由；Vite proxy；`npm run build` 通过 |
| 10B | Workbench UI Actions | ✅ 已完成 | 最小写操作闭环；8 个写操作页面；4 个新通用组件；`npm run build` 0 错误 |

**第一图谱**：AAL3 macro + **Macro96**（双链路均已实现 raw → candidate）。

**宏观 96 区标准池（✅ 已实现后端 + 工作台链路）**：

- 权威来源：`Brain volume list.xlsx`（`Sheet1`，96 行）；规范：`docs/MACRO_96_REGION_POOL.md`。
- 文件中间态：`macro_region_table_v1`（Files 页自动生成 / 重新生成）。
- Raw：`POST .../parse-macro96` → `raw_macro96_region_rows`（96 行）。
- Candidate：`POST .../generate-macro96-candidates`（**非** `generate-candidates`）。
- 前端：`#/raw-macro96`、`Import Pipeline` Macro96 分支。
- **≠** AAL3 `label_index 1–96` 过滤；与 AAL3 ~166 ROI 并行，经显式 mapping 关联（mapping **未实现**）。

---

## 3. 当前数据主链路（已实现部分）

```text
Resource Registry (atlas_resources)
  → File Upload (resource_files + workspace_files) + File Normalization (中间态)
  → Import Batch (import_batches + files + events)
  → Raw Parsing
      ├─ AAL3: parse-aal3 → raw_aal3_region_labels
      └─ Macro96: parse-macro96 → raw_macro96_region_rows
  → Candidate DB
      ├─ AAL3: generate-candidates
      └─ Macro96: generate-macro96-candidates
  → Rule Validation → Human Review → Promotion (final_brain_regions)
  → Final DB Query (只读 /api/final-regions)
  → LLM Extraction (candidate_llm_extractions，候选侧字段补全)
  → Workbench UI (15 页；Import Pipeline 工作区 + rollback/run-history)
```

**Macro96 手动推进（API，parser_key=macro96_xlsx）：**

```text
POST .../parse-macro96              (running → parsed)
POST .../generate-macro96-candidates (parsed → candidate_generated)
# 后续与 AAL3 相同：rule-validation → submit-review → review → promote
```

**AAL3 手动推进顺序（API）：**

```text
POST /api/import-batches          (status=created)
POST .../queue                    (created → queued)
POST .../start                    (queued → running)
POST .../parse-aal3               (running → parsed，或 failed)
POST .../generate-candidates      (parsed → candidate_generated，或 failed)
POST /api/rule-validation/run?batch_id=...   (candidate_created → rule_passed/rule_failed；不改 batch 状态)
POST /api/candidates/{id}/submit-review      (rule_passed → manual_review_pending；不改 batch 状态)
POST /api/candidates/{id}/review             (manual_review_pending → manual_approved/manual_rejected)
POST /api/candidates/{id}/promote            body {promoted_by, reason}  (manual_approved → promoted_to_final)
```

**重要语义：**

- `batch.parsed` ≠ `candidate_created` ≠ `manual_approved` ≠ 正式入库。
- `raw_aal3_region_labels` 是 **raw_payload**，不是 candidate，不是 `final_*`。
- `candidate_brain_regions` 是 **候选侧**实体（`candidate_status=candidate_created`），不是 `final_*` / `kg_*`。
- 候选**不自动合并同名脑区**，保留 laterality 与全链路溯源（raw_label → file → parse_run → batch → resource）。
- `rule_passed` ≠ `manual_approved` ≠ 正式入库；`rule_failed` **不自动删除**，禁止 promotion。
- Rule Validation **不改 Import Batch 状态**（仅写 `rule_validation_*` 事件），避免 Candidate/Import Batch 状态机混用。
- Human Review **不写 final_*/不 promotion**；`manual_approved` ≠ 正式入库；`manual_rejected` 为终态、**不自动删除**。
- Human Review **不改 Import Batch 状态、不写 import_batch_events**（审计独立落 `candidate_review_records`），避免 Human Review/Import Batch 状态机混用。
- `request_changes` / `mark_uncertain` 仅记录审核动作、**保持 `manual_review_pending`**（Candidate 状态机无"待修改/不确定"状态）。
- Promotion **只写 `final_brain_regions`**（与 `candidate_brain_regions` 是独立表，不合并）；不写 `kg_*`/`legacy staging_*`；不改 Import Batch 状态；幂等（同一 candidate 已有 final 行则 409）。
- `manual_approved → promoted_to_final` 为 Candidate 状态机新增转移（008 migration ALTER 了候选状态 CHECK 约束）。`promoted_to_final` ≠ 正式库最终态（后续 Final DB Query 负责查询；`archived` 仍为软删终态）。
- 三态分离：Import Task / Candidate / Promotion 状态**不得混用**。

---

## 4. 架构硬约束（GPT 必须遵守）

1. 新正式写入主路径：**`final_*`**（仅 Promotion 模块）；**禁止**默认写 `kg_*`。
2. Agent/Parser **只写 candidate/staging**；本步 raw 表也不算 candidate。
3. LLM 按风险触发；`llm_passed ≠ manual_approved`。
4. 不使用 Docker；不自动执行 migration。
5. 不大范围重构；不恢复旧工作台 `PromotionService` / `staging_*` 全量代码。
6. 溯源字段保留：`source_atlas`、`source_version`、`source_file_id`、`batch_id` / `parse_run_id`。

---

## 5. 数据库 Migration（001–020，需手动按序执行）

### MVP 1 核心（001–008）

| 顺序 | 文件 | 表 / 变更 |
|------|------|-----------|
| 1 | `001_resource_registry.sql` | `atlas_resources` |
| 2 | `002_resource_files.sql` | `resource_files` |
| 3 | `003_import_batches.sql` | `import_batches`, `import_batch_files`, `import_batch_events` |
| 4 | `004_raw_parsing_aal3.sql` | `raw_parse_runs`, `raw_aal3_region_labels` |
| 5 | `005_candidate_db.sql` | `candidate_generation_runs`, `candidate_brain_regions` |
| 6 | `006_rule_validation.sql` | `rule_validation_runs`, `candidate_rule_validation_results` |
| 7 | `007_human_review.sql` | `candidate_review_records` |
| 8 | `008_promotion.sql` | `final_brain_regions`, `promotion_records` |

### MVP 1 扩展 + MVP 2（009–020）

| 顺序 | 文件 | 要点 |
|------|------|------|
| 9 | `009_llm_extraction.sql` | `candidate_llm_extractions` |
| 10 | `010_file_normalization.sql` | 文件规范化 run + `file_intermediate_artifacts` |
| 11 | `011_workspace_files.sql` | `workspace_files` 公共文件池 |
| 12 | `012_extend_intermediate_artifact_kinds.sql` | `macro_region_table` 等 kind |
| 13 | `013_destructive_resource_delete_records.sql` | 级联删除审计 |
| 14 | `014_resource_files_macro_role.sql` | macro 文件角色 |
| 15 | `015_import_batch_macro_role.sql` | batch macro 角色 |
| 16 | `016_raw_parsing_macro96.sql` | `raw_macro96_region_rows` |
| 17 | `017_import_batch_events_macro96_types.sql` | Macro96 parse 事件类型 |
| 18 | `018_macro96_candidate_source.sql` | `source_raw_table` 多 raw 源 |
| 19 | `019_import_batch_rollback_records.sql` | rollback 审计 |
| 20 | `020_import_batch_events_rollback_types.sql` | rollback 事件类型 |

**注意：**

- 历史 migration（`init_schema.sql`、`20260520_coarse_grain_schema.sql` 等）含 legacy `atlas_resources` / `kg_*`，**新功能不依赖**。
- 绿库重建：空库依次执行 **001→020**（E2E 库 `neurographiq_kg_v3_mvp1_e2e` 为当前主验证库）。
- 004 依赖 003；005 依赖 003/004；…；018 依赖 016；019–020 依赖 003。

```powershell
# 示例（密码/库名按 .env）
psql -h 127.0.0.1 -U postgres -d neurographiq_kg_v3_wb -f backend/migrations/001_resource_registry.sql
psql ... -f backend/migrations/002_resource_files.sql
psql ... -f backend/migrations/003_import_batches.sql
psql ... -f backend/migrations/004_raw_parsing_aal3.sql
psql ... -f backend/migrations/005_candidate_db.sql
psql ... -f backend/migrations/006_rule_validation.sql
```

---

## 6. 已实现 API 索引

### Resource Registry — `/api/resources`

| 方法 | 路径 | 作用 |
|------|------|------|
| GET | `/options` | 枚举 |
| GET/POST | `` | 列表 / 创建 |
| GET/PATCH/DELETE | `/{resource_id}` | 查 / 改 / 软删 |

### File Upload — `/api/resources/{id}/files` + `/api/files`

| 方法 | 路径 | 作用 |
|------|------|------|
| POST | `/api/resources/{resource_id}/files` | multipart 上传 |
| GET | `/api/resources/{resource_id}/files` | 资源下文件列表 |
| GET/PATCH/DELETE | `/api/files/{file_id}` | 元数据 / 编辑元数据 / 软删 |
| GET | `/api/files/{file_id}/download` | 下载（路径安全校验） |
| GET | `/api/files/{file_id}/preview` | 安全预览（文本截断、图片、二进制元数据） |
| GET | `/api/files/options` | 枚举 |

### Import Batch — `/api/import-batches`

| 方法 | 路径 | 作用 |
|------|------|------|
| GET | `/options` | 枚举 |
| POST/GET | `` | 创建 / 列表 |
| GET | `/{batch_id}` | 详情（含文件 + 最近事件） |
| GET | `/{batch_id}/files` | 关联文件 |
| GET | `/{batch_id}/events` | 事件日志 |
| POST | `/{batch_id}/queue` | created → queued |
| POST | `/{batch_id}/start` | queued → running |
| POST | `/{batch_id}/cancel` | → cancelled |
| POST | `/{batch_id}/fail` | → failed |
| POST | `/{batch_id}/complete` | running → completed |
| POST | `/{batch_id}/status` | 通用状态变更（校验转移） |

### Raw Parsing AAL3

| 方法 | 路径 | 作用 |
|------|------|------|
| GET | `/api/raw-parsing/options` | 枚举 |
| GET | `/api/raw-parsing/aal3-labels` | 按 resource/batch/run 查 raw labels |
| POST | `/api/import-batches/{batch_id}/parse-aal3` | **仅 running batch**；XML label 解析 |
| GET | `/api/import-batches/{batch_id}/parse-runs` | batch 的 parse runs |
| GET | `/api/raw-parse-runs/{parse_run_id}` | parse run 详情 |
| GET | `/api/raw-parse-runs/{parse_run_id}/aal3-labels` | 该 run 的 labels |

### Candidate DB

| 方法 | 路径 | 作用 |
|------|------|------|
| GET | `/api/candidates/options` | 枚举（candidate_status / gen_run_status / laterality） |
| POST | `/api/import-batches/{batch_id}/generate-candidates` | **仅 parsed batch**；raw labels → candidate（parsed → candidate_generated）；可选 `?parse_run_id=` |
| GET | `/api/import-batches/{batch_id}/candidate-runs` | batch 的候选生成 run |
| GET | `/api/candidate-runs/{generation_run_id}` | 生成 run 详情 |
| GET | `/api/candidates/brain-regions` | 候选脑区列表（按 resource/batch/run/parse_run/status/laterality 过滤 + 分页） |
| GET | `/api/candidates/brain-regions/status-summary` | 按 candidate_status 计数汇总 |
| GET | `/api/candidates/brain-regions/{candidate_id}` | 候选脑区详情 |

### Rule Validation

| 方法 | 路径 | 作用 |
|------|------|------|
| GET | `/api/rule-validation/options` | 枚举 + 规则目录（rule catalogue） |
| POST | `/api/rule-validation/run` | 批量校验（query 恰选一：`generation_run_id` / `batch_id` / `parse_run_id`） |
| POST | `/api/candidates/{candidate_id}/validate` | 单条 candidate 校验 |
| GET | `/api/rule-validation/runs` | validation run 列表（按 batch/resource/status 过滤） |
| GET | `/api/rule-validation/runs/{validation_run_id}` | validation run 详情 |
| GET | `/api/rule-validation/runs/{validation_run_id}/results` | 该 run 的逐条 candidate 结果 |
| GET | `/api/candidates/{candidate_id}/validation-results` | 单条 candidate 的校验结果历史 |

**规则（确定性，无 LLM）：** error = 空 `raw_name` / 非法 laterality / 缺 granularity → `rule_failed`；warning = 缺 std_name / laterality unknown / 缺 source_id / run 内重复 label_value / 重复 name+laterality（**仅标记不合并**）。仅处理 `candidate_created` 候选，其它计入 `skipped`。

### Human Review

| 方法 | 路径 | 作用 |
|------|------|------|
| GET | `/api/human-review/options` | 枚举（actions / decision_actions / pending/approved/rejected status） |
| GET | `/api/human-review/pending` | 待审核 candidate 列表（`candidate_status=manual_review_pending`；按 resource/batch/gen_run 过滤 + 分页） |
| POST | `/api/candidates/{candidate_id}/submit-review` | 提交人工审核（`rule_passed/...` → `manual_review_pending`；body：`reviewed_by`+`reason`） |
| POST | `/api/candidates/{candidate_id}/review` | 审核决策（body：`action`+`reviewed_by`+`reason`） |
| GET | `/api/candidates/{candidate_id}/review-records` | 单条 candidate 审核历史 |
| GET | `/api/human-review/records` | 审核记录列表（按 batch/resource/action 过滤） |
| GET | `/api/human-review/records/{record_id}` | 审核记录详情 |

**审核动作 → candidate 状态：** `submit`→`manual_review_pending`；`approve`→`manual_approved`；`reject`→`manual_rejected`；`request_changes`/`mark_uncertain`→**保持 `manual_review_pending`**（仅记录审计）。每条记录含 `action`、`from_status`、`to_status`、`reviewed_by`、`reason`、`snapshot`（审核时 candidate 快照）+ 全链路溯源 id。状态机拦截非法转移（`candidate_created`/`rule_failed` 无法直达 `manual_approved`，强制经 `manual_review_pending`）。**不写 final_*/kg_*，不 promotion，不改 batch 状态。**

### Promotion

| 方法 | 路径 | 作用 |
|------|------|------|
| GET | `/api/promotion/options` | 枚举（promotion_status / final_region_status / promotable/promoted status） |
| POST | `/api/candidates/{candidate_id}/promote` | 晋升（`manual_approved → promoted_to_final`；body：`promoted_by`+`reason`；幂等） |
| GET | `/api/candidates/{candidate_id}/final-region` | 该候选对应的 final 脑区（404 if not promoted） |
| GET | `/api/candidates/{candidate_id}/promotion-records` | 候选晋升历史 |
| GET | `/api/promotion/final-regions` | final 脑区列表（按 resource/batch/status 过滤 + 分页） |
| GET | `/api/promotion/final-regions/{final_region_id}` | final 脑区详情 |
| GET | `/api/promotion/records` | promotion 记录列表（按 batch/resource/status 过滤） |
| GET | `/api/promotion/records/{record_id}` | promotion 记录详情 |

**关键约束（代码强制）：** 仅 `manual_approved` 可晋升；同一 candidate 重复调用返回 409 AlreadyPromotedError（幂等）；`final_brain_regions` 与 `candidate_brain_regions` 独立存储（不合并）；不写 `kg_*`；全链路溯源（candidate_id / resource_id / batch_id / parse_run_id / generation_run_id / source_file_id / source_raw_label_id / latest_review_record_id / latest_validation_result_id）。

### Health

- `GET /api/health` → `version: 3.2.9-mvp1-final-db-query`，modules 含九模块 active。

---

## 7. Import Batch 状态机（已实现）

**允许状态：** `created`, `queued`, `running`, `parsed`, `candidate_generated`, `validation_dispatched`, `completed`, `failed`, `cancelled`

**终态：** `completed`, `cancelled`（不可再变）

**本阶段实际用到的转移：**

- `created → queued → running`
- `running → parsed`（parse-aal3 成功）
- `running → failed`（parse-aal3 失败）
- `running → completed`（手动 complete，非 parse 自动）

**禁止混用 Candidate/Promotion 状态：** `candidate_created`, `rule_passed`, `manual_approved`, `promoted_to_final` 等。

**校验位置：** `app/schemas/import_batch.py` → `validate_import_batch_transition()`

**Candidate 状态机：** 见 `app/schemas/candidate.py` → `CandidateStatus` / `CANDIDATE_ALLOWED_TRANSITIONS` / `validate_candidate_transition()`。终态 `manual_rejected`、`archived`。Rule Validation 已驱动 `candidate_created → rule_validating → rule_passed/rule_failed`；Human Review 已驱动 `rule_passed → manual_review_pending → manual_approved/manual_rejected`；Promotion 已驱动 `manual_approved → promoted_to_final`（`promoted_to_final → archived` 也已定义，留给后续归档）。LLM 将在后续步骤驱动 `llm_*` 转移。

---

## 8. Raw Parsing 行为摘要

- **复用 parser：** `app/parsers/aal3_xml.py` → `parse_aal3_xml()`（**不读 NIfTI**）。
- **适配层：** `app/utils/aal3_laterality.py`, `app/utils/aal3_raw_adapter.py`。
- **输入文件筛选：** `label_dictionary` role / `label_table` type / `.xml|.txt|.csv|.tsv`；**本步仅实际解析 `.xml`**。
- **NIfTI：** 可出现在 batch 中，记入 `input_file_ids`，**不解析体素**。
- **幂等：** 同 `batch_id + parser_key(aal3_xml)` 已有 `succeeded` run → **409**。
- **成功后：** `raw_parse_runs.status=succeeded`，`batch.status=parsed`，写 `parse_started/succeeded` 事件。

---

## 9. 后端代码结构（MVP 1 新增部分）

```
backend/app/
├── models/
│   ├── resource.py          # AtlasResource
│   ├── resource_file.py     # ResourceFile
│   ├── import_batch.py      # ImportBatch, ImportBatchFile, ImportBatchEvent
│   ├── raw_parsing.py       # RawParseRun, RawAal3RegionLabel
│   ├── candidate.py         # CandidateGenerationRun, CandidateBrainRegion
│   ├── rule_validation.py   # RuleValidationRun, CandidateRuleValidationResult
│   ├── human_review.py      # CandidateReviewRecord
│   └── promotion.py         # FinalBrainRegion, PromotionRecord
├── services/
│   └── final_db_query_service.py  # 只读 SELECT；无写操作
├── schemas/                 # 对应 Pydantic + 状态机
├── services/                # 业务逻辑 + logger（无 audit_log 表）
├── routers/                 # FastAPI 路由
├── database.py              # 单库 AsyncSession
├── parsers/                 # 保留：AAL3 等（未改核心）
├── io/staging_csv_exporter.py  # CLI CSV 导出（独立）
└── utils/
    ├── hash_utils.py
    ├── file_meta.py
    ├── aal3_laterality.py
    └── aal3_raw_adapter.py
```

**测试（无 DB 为主）：**

- `test_resource_registry.py` (10)
- `test_resource_files.py` (16)
- `test_import_batches.py` (21)
- `test_raw_parsing_aal3.py` (17)
- `test_candidate_db.py` (15)
- `test_rule_validation.py` (17)
- `test_human_review.py` (13)
- `test_promotion.py` (15)
- `test_final_db_query.py` (7)
- `test_aal3_xml.py` (2)

> 全量：`133 passed`（无 DB）。

```powershell
cd backend
.\.venv\Scripts\python.exe -m pytest tests/ -q
```

---

## 10. 未实现 / 风险

| 项 | 状态 |
|----|------|
| MVP 1 核心链路（001–008 + UI） | ✅ 全部完成 |
| Macro96 raw + candidate（016–018） | ✅ 已实现 |
| File Normalization + Workspace Files（010–011） | ✅ 已实现 |
| Import Pipeline + Rollback（019–020） | ✅ 已实现 |
| LLM Extraction Region 字段（009） | ✅ DeepSeek；不写 final |
| Mirror KG / connection / circuit / function LLM | ❌ 仅架构文档 |
| Promotion → 物理正式库 `NeuroGraphIQ_KG_V3` | ❌ 当前写工作台/E2E 库内 `final_brain_regions` |
| Kimi LLM 提取 | ❌ Settings 有配置，无提取 API |
| `kg_*` 写入 | 永久禁止（新功能路径） |
| `audit_log` 统一表 | 未实现 |
| Celery / Redis 队列 | 未引入 |
| 跨 atlas Explicit Mapping | 未实现 |
| legacy `atlas_resources` 表冲突 | 绿库用 001；旧库需手动处理 |
| API 路径 | 新代码用 `/api/resources`（非旧 `/api/v1/...`） |

---

## 11. 前端 Workbench UI（当前 15 页）

### 页面一览

| 页面 | 路由 | 说明 |
|------|------|------|
| Dashboard | `#/` | 健康、库切换、统计、操作指引 |
| Resources | `#/resources` | CRUD、Macro 预设、归档/恢复/purge |
| Files | `#/files` | 资源文件 + Workspace；中间态；xlsx 预览修复 |
| Import Batches | `#/import-batches` | Batch CRUD、parser-aware 选文件 |
| Import Pipeline | `#/import-pipeline` | 阶段工作区、rollback、re-execute、run-history |
| Raw AAL3 | `#/raw-aal3` | raw_aal3_region_labels |
| Raw Macro96 | `#/raw-macro96` | raw_macro96_region_rows |
| Candidates | `#/candidates` | candidate_brain_regions + URL 筛选 |
| LLM Extraction | `#/llm-extraction` | DeepSeek 候选侧字段补全 |
| Rule Validation | `#/rule-validation` | 规则校验 run + 结果 |
| Human Review | `#/human-review` | 审核队列 + 记录 |
| Promotions | `#/promotions` | promotion_records |
| Final Regions | `#/final-regions` | final_brain_regions（只读） |
| Settings | `#/settings` | 语言、DeepSeek/Kimi API |

### 写操作要点（Step 10B + 后续扩展）
| 页面 | 新增操作 | 后端 API |
|------|---------|---------|
| Resources | 创建 Resource（AAL3 默认值预填） | `POST /api/resources` |
| Files | 上传文件（multipart/form-data） | `POST /api/resources/{id}/files` |
| Import Batches | 创建 Batch；Queue（status=created）；Start（status=queued） | `POST /api/import-batches`；`/{id}/queue`；`/{id}/start` |
| Raw AAL3 | Parse AAL3 | `POST .../parse-aal3` |
| Raw Macro96 | Parse Macro96 | `POST .../parse-macro96` |
| Candidates | Generate（AAL3 / Macro96 分路） | `.../generate-candidates` 或 `.../generate-macro96-candidates` |
| Rule Validation | 按 batch/gen_run/candidate 执行规则校验（二次确认） | `POST /api/rule-validation/run?batch_id=...` 或 `/api/candidates/{id}/validate` |
| Human Review | Submit Review；每行 Approve/Reject（带 reviewer+reason 确认对话框） | `POST /api/candidates/{id}/submit-review`；`/{id}/review` |
| Promotions | 晋升 manual_approved candidate（强确认；不可逆警告） | `POST /api/candidates/{id}/promote` |

### 端到端 UI 操作顺序
```
Create Resource → Upload AAL3 XML → Create Batch → Queue → Start
  → Parse AAL3 → Generate Candidates → Rule Validation
  → Submit Review → Approve → Promote → View Final Regions
```

### 新增组件（Step 10B）
- `ActionButton.tsx` — 带 loading 状态、variant（primary/danger/success/default）
- `ConfirmDialog.tsx` — 模态确认框（支持 children 插槽用于自定义表单字段）
- `Notice.tsx` — 内联成功/错误通知横幅（7 秒自动消失）
- `FormPanel.tsx` — 可折叠表单容器

### Step 10B 风险点
1. **状态机最终校验在后端**：前端按状态显示按钮，但后端仍是唯一权威，409/400 错误会通过 Notice 显示
2. **RuleValidationRun 列表字段**：`RuleValidationRunRead` 使用 `passed_count/failed_count/warning_count/candidate_count`（与 `ValidateResult` 一致）
3. **PendingCandidate vs CandidateBrainRegion**：`fetchPendingReviews` 返回 `PendingCandidate`，字段是 `cn_name/en_name/raw_name/candidate_status`
4. **Promote 操作不可逆**：前端展示强警告，但用户仍需后端数据库层面干预来撤销
5. **无 Docker**：前端 `npm run dev` + 后端 `python run_server.py` 需分别手动启动

## 12. MVP 1 E2E 联调记录（2026-06-08）

### 前置检查

| 检查项 | 结果 |
|--------|------|
| 后端 pytest | ✅ 133 passed |
| GET /api/health | ✅ 200，version `3.2.9-mvp1-final-db-query`，9 模块 active |
| 前端 npm run build | ✅ 0 TypeScript 错误 |
| `.env` 默认库 `neurographiq_kg_v3_wb` | ⚠️ **仍为 legacy schema**（`atlas_code/atlas_name`，无 `resource_code`）；001–008 未应用 |
| 独立 E2E 测试库 `neurographiq_kg_v3_mvp1_e2e` | ✅ 已手动应用 001–008，全链路通过 |

### 默认库阻断说明

`neurographiq_kg_v3_wb` 含 legacy 表（`kg_*`、`staging_*`、`coarse_*` 等 34 张表），`atlas_resources` 为旧 coarse_grain schema。直接在该库执行 `POST /api/resources` 返回 **500**（`resource_code` 列不存在）。

**用户需在以下二选一后，才能在默认库上通过 UI 联调：**

1. **绿库方案（推荐）**：新建库并改 `.env` 的 `DATABASE_URL`：
   ```powershell
   psql -h 127.0.0.1 -U postgres -c "CREATE DATABASE neurographiq_kg_v3_mvp1_e2e;"
   # 依次执行 001–008（见 §5）
   # 修改 backend/.env: DATABASE_URL=postgresql+psycopg_async://postgres:postgres@127.0.0.1:5432/neurographiq_kg_v3_mvp1_e2e
   ```
2. **同库迁移方案（有风险）**：备份后 DROP legacy `atlas_resources`（及依赖 `atlas_labels`），再执行 001–008。

### E2E 执行结果（API 联调，AAL3 全量 XML 166 ROI）

测试文件：`backend/data/archive/c36eea58_d44d141e_AAL3v1_1mm.xml`  
测试库：`neurographiq_kg_v3_mvp1_e2e`（端口 8003）  
脚本：`backend/scripts/e2e_mvp1_test.py`

| 步骤 | 结果 | 关键 ID / 数据 |
|------|------|----------------|
| 1. 创建 Resource | ✅ | `resource_id=6c221ca4-3575-4962-a1d7-b6b0e113eb1a` |
| 2. 上传 XML | ✅ | `file_id=753e58da-2f79-413e-b194-1cd971d7c538` |
| 3. 创建 Batch | ✅ | `batch_id=d28e4fa3-da3c-4884-ab67-66e2f9230f0d`，status=created |
| 4. Queue | ✅ | created → queued |
| 5. Start | ✅ | queued → running |
| 6. Parse AAL3 | ✅ | `parse_run_id=16f015b6-81fe-4966-9ac3-27335226463e`，**raw_label_count=166** |
| 7. 查看 raw labels | ✅ | total=166，含 source_label_id/laterality/region_base_name |
| 8. Generate Candidates | ✅ | `generation_run_id=54f302d2-99bf-45ed-ab77-f38f27c7a8cb`，**candidate_count=166** |
| 9. 查看 candidates | ✅ | candidate_status=candidate_created |
| 10. Rule Validation | ✅ | passed=166，failed=0，**warning=2** |
| 11. Submit Review | ✅ | `candidate_id=95383d0e-e2b3-47bf-b0f8-301a35a1930f` → manual_review_pending |
| 12. Approve | ✅ | → manual_approved |
| 13. Promote | ✅ | `final_region_id=ed974bf2-1225-44d8-9d3b-376cc925dde6` |
| 14. Final Regions 查看 | ✅ | status=active，provenance 可追溯 |
| 15. 重复 Promote | ✅ | HTTP 409（already promoted） |

**未写入 kg_***：E2E 测试库无 `kg_*` 表。

### E2E 联调中发现并修复的问题

| 问题 | 原因 | 修复 |
|------|------|------|
| 默认库 Create Resource 500 | legacy `atlas_resources` schema 与 MVP1 ORM 不匹配 | 文档说明 + 建议绿库；未改后端 |
| 前端 Files 页文件大小显示异常 | 接口字段 `file_size` vs 前端 `file_size_bytes` | 修 `endpoints.ts` + `FilesPage.tsx` |
| 前端 Rule Validation 列表计数为空 | 接口字段 `passed_count` vs 前端 `passed` | 修 `endpoints.ts` + `RuleValidationPage.tsx` |
| 前端 Candidates 状态汇总不显示 | 接口 `by_status[].candidate_status` vs 前端 `counts[].status` | 修 `endpoints.ts` + `CandidatesPage.tsx` |
| E2E 脚本 Step 1 误报失败 | POST /api/resources 返回 201 而非 200 | 修 `e2e_mvp1_test.py` 接受 201 |
| httpx 502 on localhost | Windows 系统代理干扰 | E2E 脚本加 `trust_env=False` |

### 绿库切换与 UI Polish（2026-06-08 续）

| 项 | 状态 |
|----|------|
| `backend/.env` DATABASE_URL | ✅ 已指向 `neurographiq_kg_v3_mvp1_e2e` |
| POSTGRES_DB | ✅ 已同步为 `neurographiq_kg_v3_mvp1_e2e` |
| 绿库 001–008 | ✅ 已存在（14 张 MVP1 表） |
| 后端重启后 E2E（:8002） | ✅ 15 步全通过 |
| 前端 UI Polish | ✅ 流水线 ID 面板 + 跨页预填 + 复制按钮 |

**UI 新增（最小）：**
- `useSessionIds` + `SessionIdsPanel`：Dashboard 显示当前流水线 ID，可复制、可清空
- `CopyButton`：Resources/Files/ImportBatches 列表 ID 列可复制
- 各操作页成功后将 ID 写入 sessionStorage，下一页自动预填（resource_id → file_id → batch_id → parse_run_id → candidate_id）

**legacy 库 `neurographiq_kg_v3_wb`：** 保留不动，不再用于 MVP1 联调。

### E2E 仍存风险

1. **AAL3 166 ROI ≠ 96 区标准池**：本次仅验证全量 XML 链路
2. **warning_count=2**：规则校验有 2 条 warning（laterality 相关），不阻断 promotion
3. **后端需重启才加载新 .env**：修改 DATABASE_URL 后必须重启 `run_server.py`

## 13. 给 GPT 的推荐下一步指令

```
MVP 1 绿库已切换，API + UI 流水线 ID 传递已就绪。

下一步建议：浏览器手动验证 + 持续 Bugfix / Polish

任务：
1. 确认 backend 已重启（DATABASE_URL → neurographiq_kg_v3_mvp1_e2e）
2. 浏览器 http://127.0.0.1:5173 按 Dashboard 指引走 12 步
3. 验证各页 Notice / ConfirmDialog / 流水线 ID 预填
4. 记录浏览器端边角问题并最小修复

禁止：写 kg_*、Docker、自动 migration、LLM、批量 promote。
```

---

## 14. 手动端到端验证脚本（AAL3 raw 链路）

```powershell
.\scripts\start-backend.ps1
# Swagger: http://127.0.0.1:8002/api/docs

# 1. POST /api/resources  (AAL3 macro resource)
# 2. POST /api/resources/{id}/files  (XML, file_role=label_dictionary, file_type=label_table)
# 3. POST /api/import-batches  (resource_id + files[].file_id)
# 4. POST /api/import-batches/{id}/queue
# 5. POST /api/import-batches/{id}/start
# 6. POST /api/import-batches/{id}/parse-aal3
# 7. GET  /api/raw-parse-runs/{parse_run_id}/aal3-labels
# 8. POST /api/import-batches/{id}/generate-candidates   (parsed → candidate_generated)
# 9. GET  /api/candidates/brain-regions?batch_id={id}
# 10. GET /api/candidates/brain-regions/status-summary?batch_id={id}
# 11. POST /api/rule-validation/run?batch_id={id}          (candidate_created → rule_passed/rule_failed)
# 12. GET  /api/rule-validation/runs/{validation_run_id}/results
# 13. GET  /api/candidates/brain-regions/status-summary?batch_id={id}   (确认 rule_passed/rule_failed 计数)
# 14. POST /api/candidates/{candidate_id}/submit-review    body {reviewed_by, reason}  (rule_passed → manual_review_pending)
# 15. GET  /api/human-review/pending?batch_id={id}          (待审核队列)
# 16. POST /api/candidates/{candidate_id}/review           body {action: approve|reject|request_changes|mark_uncertain, reviewed_by, reason}
# 17. GET  /api/candidates/{candidate_id}/review-records    (审核历史 + 快照)
# 18. GET  /api/candidates/brain-regions/status-summary?batch_id={id}   (确认 manual_approved/manual_rejected 计数)
# 19. POST /api/candidates/{candidate_id}/promote         body {promoted_by}  (manual_approved → promoted_to_final)
# 20. GET  /api/promotion/final-regions?batch_id={id}      (查看 final 脑区列表)
# 21. GET  /api/candidates/{candidate_id}/final-region     (验证溯源完整)
# 22. GET  /api/candidates/brain-regions/status-summary?batch_id={id}   (确认 promoted_to_final 计数)
```

---

## 15. MVP 2 Step 1：LLM Extraction Workbench（DeepSeek 候选侧提取）

后端版本升至 `3.3.0-mvp2-llm-extraction`。

### 边界（关键）
- **提取 = 候选侧建议性标注**（补全 / 翻译 / 解释），不是事实入库。
- DeepSeek 输出**只**写入新表 `candidate_llm_extractions`（candidate 侧）。
- **不写** `final_*` / `kg_*`，**不**自动 approve，**不**自动 promote。
- **不修改** `candidate_brain_regions.candidate_status`（本步与状态机解耦，刻意不动 `llm_validating/llm_passed/llm_conflict`，避免破坏 `rule_passed → manual_review_pending`）。状态机推进留给后续“LLM 验证”专门步骤。
- 单条提取 + 小批量（≤ 20，`MAX_BATCH_SIZE`），防止误触发大规模付费调用。
- API Key 为空时：调用返回明确错误并记录为 `status=failed` 行，不崩溃、不伪造结果。

### 新增文件
- `backend/migrations/009_llm_extraction.sql` — `candidate_llm_extractions`（含全链路 *_id 溯源 + run_id + provider/model/prompt_version + raw_response + structured_result(JSONB) + token/cost/latency）。**已手动应用到 `neurographiq_kg_v3_mvp1_e2e`**。
- `backend/app/models/llm_extraction.py`、`backend/app/schemas/llm_extraction.py`
- `backend/app/services/deepseek_client.py`（httpx async，`trust_env=False`，`response_format=json_object`）
- `backend/app/services/llm_extraction_service.py`（`extract_one` / `extract_batch` / `list_extractions`）
- `backend/app/routers/llm_extraction.py`
- `frontend/src/pages/LlmExtractionPage.tsx`（导航新增 `LLM Extraction`）
- `backend/app/schemas/settings.py`、`backend/app/services/settings_service.py`、`backend/app/routers/settings.py`
- `frontend/src/pages/SettingsPage.tsx`、`frontend/src/i18n.ts`

### 新增 API
| 方法 | 路径 | 说明 |
| --- | --- | --- |
| GET | `/api/llm-extraction/options` | provider/model/prompt_version/max_batch_size/api_key_configured |
| GET | `/api/llm-extraction` | 列表（按 candidate/batch/resource/run/status 过滤） |
| POST | `/api/llm-extraction/batch` | 批量提取 body `{candidate_ids: [...] ≤20}` |
| POST | `/api/candidates/{candidate_id}/llm-extract` | 单条提取 |
| GET | `/api/candidates/{candidate_id}/llm-extractions` | 该 candidate 的提取历史 |
| GET | `/api/settings/options` | Settings 页面选项（语言、Provider、默认模型）；不返回 API Key |
| GET | `/api/settings/runtime` | 脱敏 runtime 配置；`api_key_configured` + `api_key_masked`，不返回明文 Key |
| PATCH | `/api/settings/runtime` | 保存 DeepSeek 与基础工作台设置；空 `api_key` 不覆盖，`explicit_clear_api_key=true` 才清除 |
| POST | `/api/settings/api-providers/deepseek/test` | 用户点击后测试 DeepSeek 连通性；不保存请求中的 API Key，不写 candidate/final/kg |

### 前端
- 候选列表（多选 ≤20）+ 单条/批量提取；点击行进入对比详情（Candidate/Raw 字段 vs DeepSeek 建议 + 原始输出 + token/延迟）。
- 顶部常驻“提取建议 ≠ 正式事实”警示横幅；API Key 未配置时显式提示。
- **无** final 写入按钮，**无** approve 按钮。
- Settings 页面新增 `#/settings`：语言设置（`localStorage: neurographiq.language`）、DeepSeek API Provider 配置、基础设置（page size/debug panels）。
- API Key 只由后端 runtime settings 保存；前端不写 `localStorage`，页面只显示 masked key；DeepSeek 未配置时 LLM Extraction 禁用提取按钮并跳转 Settings。

### 验证
- 后端 import OK，`/api/llm-extraction/options` → 200（`api_key_configured: false`）。
- `/api/llm-extraction` → 200（空列表，表/ORM 对齐）。
- 前端 `npm run build` 通过。
- 待办：在 `backend/.env` 填入真实 `DEEPSEEK_API_KEY` 后，浏览器端实跑单条/批量提取。

---

## 16. Resource Registry CRUD Completion（2026-06-11）

### 前端新增
- `Resources` 页面补齐资源登记管理闭环：列表查询、详情查看、创建、编辑、停用、刷新、ID 复制。
- 列表新增操作列：查看、编辑、停用、复制 ID。
- 筛选支持：`status`、`source_atlas`、`granularity_level`、`granularity_family`（复用后端已有查询参数）。
- 创建与编辑复用同一个前端表单；编辑模式中 `resource_code` 只读，因为当前后端 `ResourceUpdate` 不允许修改该字段。
- 详情面板展示：`id`、`resource_code`、`source_atlas`、`source_version`、`resource_type`、`species`、`granularity_level`、`granularity_family`、`template_space`、`status`、`en_name`、`cn_name`、`description`、`remark`、`created_at`、`updated_at`。

### 复用后端 API
| 方法 | 路径 | 用途 |
|------|------|------|
| GET | `/api/resources/options` | 表单与筛选枚举 |
| GET | `/api/resources` | 资源列表与筛选 |
| POST | `/api/resources` | 创建资源登记 |
| GET | `/api/resources/{resource_id}` | 查看详情 |
| PATCH | `/api/resources/{resource_id}` | 编辑资源元数据 |
| DELETE | `/api/resources/{resource_id}` | 软删除 / 停用 |

### 删除/停用策略
- 后端 `DELETE /api/resources/{resource_id}` 已是软删除：`deleted_at = now` 且 `status = archived`。
- 不删除已上传文件，不删除导入批次，不删除 raw/candidate/final 数据，不写 `kg_*`。
- 前端二次确认文案明确说明：该操作只停用资源登记记录，不删除下游数据。

### 是否修改后端
- 未修改后端。现有 Resource API 已满足详情、编辑、软删除与筛选需求。
- 未新增 migration。

### i18n 覆盖
- `frontend/src/i18n.ts` 已补齐 Resources CRUD 中文/英文文案，包括标题、说明、表单字段、筛选、详情、成功/失败提示、删除确认和空状态。

### 测试结果
- 前端：`npm run build` 通过（TypeScript 0 错误，Vite build 成功）。
- 后端：未修改后端，因此未运行全量 pytest。

### 风险点
1. `resource_code` 暂不支持编辑，需后端 `ResourceUpdate` 显式加入并处理唯一冲突后才能开放。
2. DELETE 后列表默认隐藏 `deleted_at` 非空记录，因此停用后记录可能从默认列表消失。
3. 当前未实现 keyword/q 搜索；后端未提供该参数，本轮未强行新增。

---

## 17. File Management CRUD + Preview Completion（2026-06-11）

### 页面新增
- `Files` 页面补齐文件管理闭环：按 `resource_id` 查询、上传、详情、元数据编辑、软删除/停用、下载、复制 ID、刷新。
- 列表支持筛选：`resource_id`、`status`、`file_type`、`file_role`。
- 页面布局调整为左侧文件列表 + 右侧文件预览面板。
- 右侧面板包含：基本信息、操作按钮、`Preview` / `Metadata` / `Raw JSON` 三个 tab。
- 上传成功后自动保存 `file_id` 到流水线 ID，刷新列表，并选中新上传文件预览。

### 后端新增/复用 API
| 方法 | 路径 | 状态 |
|------|------|------|
| GET | `/api/files/options` | 复用，并新增 `preview_supported_types` |
| POST | `/api/resources/{resource_id}/files` | 复用 |
| GET | `/api/resources/{resource_id}/files` | 复用，支持 status/type/role |
| GET | `/api/files/{file_id}` | 复用 |
| PATCH | `/api/files/{file_id}` | 新增，用于编辑 `file_type`、`file_role`、`description`、`remark`、`status` |
| DELETE | `/api/files/{file_id}` | 复用软删除 |
| GET | `/api/files/{file_id}/download` | 复用 |
| GET | `/api/files/{file_id}/preview` | 新增 |

### 预览策略
- 文本类：`.xml`、`.json`、`.txt`、`.csv`、`.tsv`、`.md`、`.yaml`、`.yml`、`.rdf`、`.owl`、`.ttl` 最多读取 64KB，并返回 `is_truncated`。
- 图片类：`.png`、`.jpg`、`.jpeg`、`.webp`、`.gif` 返回 `preview_kind=image`；前端使用 download URL 显示图片。
- 二进制/暂不支持：`.nii`、`.nii.gz`、`.npz`、`.npy`、`.pkl`、`.mat`、压缩包、PDF 等不读取正文，只显示元数据。
- 安全边界：预览只接受 `file_id`，不接受任意路径；后端通过数据库记录中的 `storage_path` 解析，且必须位于 upload root 下；不返回服务器绝对路径。
- AAL3 XML 仅显示 XML 文本片段，不重新 parse，不展示 parsed labels。

### 删除/停用策略
- `DELETE /api/files/{file_id}` 为软删除：设置 `deleted_at`，状态改为 `archived`。
- 不删除磁盘文件，不删除 `resource_files` 行，不删除 `import_batch_files`、raw、candidate、final 数据，不写 `kg_*`。

### i18n 覆盖
- `frontend/src/i18n.ts` 已补齐 Files CRUD + preview 中文/英文文案，包括筛选、上传、详情、编辑、下载、停用确认、预览状态、metadata/raw JSON tab 与错误提示。

### 测试结果
- 后端：`.\.venv\Scripts\python.exe -m pytest tests/ -q` → `151 passed`。
- 前端：`npm run build` 通过（TypeScript 0 错误，Vite build 成功）。

### 风险点
1. 当前没有全局 `GET /api/files`，Files 页面仍以 `resource_id` 查询为主。
2. 图片预览依赖 download URL；若文件已 archived 或磁盘缺失，图片不会显示。
3. 预览为轻量文本片段，不提供医学图像/NIfTI 专用渲染。

---

## 18. Workbench Pipeline Optimization / 工作台流程整合优化（规划）

### 当前阶段总结

当前完整打通的是 **AAL3 XML label dictionary 导入链路**；其他图谱资源仍处于资源登记与文件管理能力阶段，尚未实现专用 parser。不要表述为“系统已经支持所有图谱导入”。

已完成：
- MVP 1 后端主链路（Resource Registry → File Upload → Import Batch → Raw Parsing AAL3 → Candidate Generation → Rule Validation → Human Review → Promotion → Final DB Query）。
- AAL3 XML label dictionary 166 ROI E2E，验证了 raw label、candidate、rule validation、review、promotion、final query 全链路。
- Workbench UI Foundation 与 Workbench UI Actions。
- 当前已有页面：Dashboard、Resources、Files、Import Batches、Raw AAL3、Candidates、LLM Extraction、Rule Validation、Human Review、Promotions、Final Regions、Settings。
- Settings 页面、LLM Extraction 页面、Resource CRUD、File CRUD + Preview 已上线。

已通过 E2E：
- AAL3 XML label dictionary 166 ROI 导入链路。
- 绿库 `neurographiq_kg_v3_mvp1_e2e` 上 001-008 migration 后的主链路验证。

待实现 / 待扩展：
- Brainnetome 专用 parser。
- Julich-Brain 专用 parser。
- Allen 专用 parser。
- HCP-MMP / Desikan / Destrieux 专用 parser。
- NIfTI 体素解析。
- Macro 96 Region Pool Excel 落库。
- AAL3 ↔ 96 区 mapping。
- 跨粒度 mapping。
- Graph / Neo4j / RDF / GraphRAG。

### 当前流程评价

当前流程是正确的，不需要推翻。需要优化的是：页面组织方式、ID 流转方式、状态驱动操作、候选详情整合、只读聚合 API、workflow 可视化。

不应该优化成：
- 一键全流程黑箱。
- LLM 主导入库、LLM 自动 approve、LLM 自动 promote。
- 候选/正式混写。
- `rule_passed` 直接写 final。
- `manual_approved` 自动写 final。
- 批量无审查 promote。
- 跨资源同名自动合并。

Workbench 后续应从“按后端模块拆分的调试页”演进到“按用户任务组织的工作流页”。这种演进是 UI 与只读聚合能力优化，不改变后端状态机，不绕过人工审核，也不改变 Promotion 作为唯一写 `final_*` 模块的边界。

---

## 19. Raw Parsing 与 LLM Extraction 的边界

Raw Parsing = 原始解析 / 确定性解析文件内容。它读取已登记文件，通过 parser 将文件内容转成 raw/candidate 侧结构化数据。

LLM Extraction = LLM 建议提取 / 候选侧语言补全与解释。它读取已有 candidate 字段，生成建议性 JSON，供人工审核参考。

AAL3 XML 的确定性解析链路：

```text
AAL3 XML
  → parse_aal3_xml()
  → raw_aal3_region_labels
  → candidate_brain_regions
```

DeepSeek 的候选侧建议链路：

```text
candidate_brain_regions
  → DeepSeek prompt
  → candidate_llm_extractions
  → 人工审核参考
```

必须明确：
1. DeepSeek 不直接读取原始上传文件作为主解析入口。
2. DeepSeek 不写 `raw_aal3_region_labels`。
3. DeepSeek 不写 `final_*`。
4. DeepSeek 不写 `kg_*`。
5. DeepSeek 输出只作为 candidate 侧建议。
6. `llm_passed` 不等于 `manual_approved`。
7. LLM result 不能替代 Rule Validation。
8. LLM result 不能替代 Human Review。
9. Promotion 仍然是唯一写 `final_*` 的模块。

---

## 20. 文件与数据库产物对照

| 阶段 | 是否产生新物理文件 | 输入 | 输出 | 输出形态 |
|------|--------------------|------|------|----------|
| Resource Registry | 否 | JSON 表单 / API 请求体 | `atlas_resources` | 数据库结构化元数据 |
| File Upload | 是，保存原始物理文件 | `multipart/form-data`（文件 + file_type/file_role/description 等） | `resource_files` + `backend/data/uploads` | 原始文件格式不变 + 数据库文件元数据 |
| Import Batch | 否 | `resource_id` + `file_id` | `import_batches` / `import_batch_files` / `import_batch_events` | 数据库批次、文件绑定与事件记录 |
| Raw Parsing AAL3 | 否 | batch 中的 AAL3 XML label 文件 | `raw_parse_runs` / `raw_aal3_region_labels` | 数据库 raw 结构化行，保留 `raw_payload` |
| Candidate Generation | 否 | `raw_aal3_region_labels` | `candidate_generation_runs` / `candidate_brain_regions` | 数据库 candidate 结构化行 |
| Rule Validation | 否 | `candidate_brain_regions` | `rule_validation_runs` / `candidate_rule_validation_results` | 数据库规则校验运行与逐条结果 |
| LLM Extraction | 否 | `candidate_brain_regions` | `candidate_llm_extractions` | 数据库 JSON 建议 + 原始 LLM 输出 |
| Human Review | 否 | 待审核 candidate / reviewer / reason | `candidate_review_records` | 数据库审核记录与 candidate 状态变化 |
| Promotion | 否 | `manual_approved` candidate | `final_brain_regions` / `promotion_records` | 数据库正式实体与晋升审计 |
| Final Query | 否 | 查询参数 | 只读 `final_brain_regions` | 只读 API 响应，不产生新数据 |

整个链路里，磁盘上长期保存的是 File Upload 阶段上传的原始文件；后续主要产物均为 PostgreSQL 结构化数据。Raw/Candidate/Final 不是新物理文件，而是带 provenance 的数据库记录。

---

## 21. 推荐工作台信息架构（规划）

当前页面按后端模块拆分，适合开发调试；后续应演进为按用户任务组织。

推荐结构：

```text
Dashboard
Resources
  └── Resource Detail
Files
Import Pipeline
Candidate Governance
Final Regions
Settings
```

### Dashboard

职责：系统状态、数据库连接、MVP 链路状态、最新任务、快捷入口。Dashboard 负责导航与状态概览，不直接替代各模块的状态机操作。

### Resources

职责：资源登记、资源 CRUD、资源详情、关联文件、关联批次、关联候选与正式数据概览。Resource Detail 以 `resource_id` 为核心，展示资源级 provenance 总览。

### Files

职责：文件上传、文件 CRUD、文件预览、文件元数据。Files 页面只管文件级管理和预览，不做业务解析，不把 parsed labels 展示作为主要职责。

### Import Pipeline

整合页面：Import Batches、Raw AAL3 Labels、Candidates、Rule Validation。

核心对象：`batch_id`。

页面目标：

```text
选择一个 batch
  → 显示绑定文件
  → 显示 batch 状态
  → 显示下一步可执行动作
  → 显示 raw labels
  → 显示 candidates
  → 显示 rule validation results
```

Import Pipeline 不是一键自动流水线，只是状态驱动的聚合界面。它可以聚合展示和操作入口，但不能绕过后端状态机。

### Candidate Governance

整合页面：Candidate detail、Rule Validation result、LLM Extraction result、Human Review records、Promotion records、final region trace。

核心对象：`candidate_id`。

页面目标：

```text
查看 candidate
  → 查看 raw source
  → 查看 rule validation
  → 查看 LLM suggestions
  → submit review
  → approve / reject
  → promote if manual_approved
```

Candidate Governance 不绕过 Human Review，不自动 Promote。LLM suggestions 只作为人工治理参考。

### Final Regions

职责：正式脑区只读查询、provenance、promotion record、source candidate。Final Regions 不提供编辑 final 的功能，不触发 candidate/review/promotion 状态变化。

### Settings

职责：语言、API providers、DeepSeek 配置、基础工作台设置。API Key 只由后端 runtime settings 保存，前端不得保存到 localStorage，也不得明文展示。

---

## 22. Workbench Aggregation API 规划

当前后端表结构可以保持不变。后续为了减少前端重复拼接，可以新增只读聚合 API。

这些 API 是规划能力，当前尚未实现。它们只读，不改变状态，不写 `final_*`，不写 `kg_*`，不调用 LLM。

### `GET /api/workbench/resources/{resource_id}/overview`

规划返回示例：

```json
{
  "resource": {},
  "files_count": 0,
  "batches_count": 0,
  "raw_parse_runs_count": 0,
  "candidate_count": 0,
  "final_regions_count": 0,
  "latest_files": [],
  "latest_batches": []
}
```

### `GET /api/workbench/import-batches/{batch_id}/overview`

规划返回示例：

```json
{
  "batch": {},
  "bound_files": [],
  "parse_runs": [],
  "raw_label_count": 0,
  "generation_runs": [],
  "candidate_count": 0,
  "validation_runs": [],
  "passed_count": 0,
  "failed_count": 0,
  "warning_count": 0,
  "next_allowed_actions": []
}
```

### `GET /api/workbench/candidates/{candidate_id}/governance`

规划返回示例：

```json
{
  "candidate": {},
  "raw_source": {},
  "validation_results": [],
  "llm_results": [],
  "review_records": [],
  "promotion_records": [],
  "final_region": null,
  "next_allowed_actions": []
}
```

---

## 23. 后续建议开发顺序

### Step A：Workbench Browser Manual Verification / Bugfix Polish

目标：浏览器手动走查；修复 UI 细节；修复字段显示；修复 i18n；修复文件预览；修复 ID 复制和右侧详情体验。

### Step B：Import Pipeline Workspace

目标：以 `batch_id` 为核心；整合 Import Batches、Raw AAL3、Candidates、Rule Validation；状态驱动显示可执行动作；不做一键全流程。

### Step C：Candidate Governance Workspace

目标：以 `candidate_id` 为核心；整合 candidate、raw source、rule validation、LLM suggestions、review、promotion；支持人工治理；不自动 approve / promote。

### Step D：Resource Detail Workspace

目标：以 `resource_id` 为核心；展示资源、文件、批次、候选、final 概览；提供资源级 provenance 总览。

### Step E：Macro 96 Region Pool Import

目标：实现 `Brain volume list.xlsx` 解析；建立 macro 96 standard pool；与 AAL3 166 ROI 并行；不用 AAL3 `label_index 1-96` 代替 96 区标准池。

### Step F：Cross-granularity Mapping Workspace

目标：AAL3 ↔ 96 pool；Brainnetome / Julich / Allen 后续 mapping；显式 `mapping_type`；不做同名自动合并。

### Step G：LLM Suggestion Apply / Candidate Edit Review

目标：LLM 建议可视化；人工选择采纳；生成 candidate edit history；不直接写 final。

~~推荐下一步：**Workbench Import Pipeline Workspace**。~~ ✅ 已完成（见 §24）

推荐下一步：**Candidate Governance Workspace**（Step C）。

---

## 24. Workbench Import Pipeline Workspace（已完成）

**完成时间**：2026-06-15

### 新增路由

- 前端路由：`#/import-pipeline`
- 导航名称：中文「导入流水线」/ 英文「Import Pipeline」

### 新增后端模块

| 文件 | 说明 |
|------|------|
| `backend/app/schemas/workbench_pipeline.py` | 只读 schema：`PipelineAction`、`LatestValidationSummary`、`ImportBatchPipelineOverview` |
| `backend/app/services/workbench_pipeline_service.py` | 只读服务：`compute_next_allowed_actions`（纯函数）+ `get_batch_pipeline_overview`（ORM 只读） |
| `backend/app/routers/workbench_pipeline.py` | `GET /api/workbench/import-batches/{batch_id}/overview` |
| `backend/tests/test_workbench_pipeline.py` | 25 tests（纯函数），无 DB 依赖 |

### 新增只读 API

```
GET /api/workbench/import-batches/{batch_id}/overview
```

**返回字段**：
- `batch`：批次基础信息
- `bound_files`：绑定文件列表
- `events`：最近 20 条事件
- `parse_runs`：全部 parse runs
- `raw_label_count`：Raw 标签总数
- `raw_labels_preview`：最多 20 条 Raw 标签预览
- `generation_runs`：全部候选生成运行
- `candidate_count`：候选总数
- `candidate_status_counts`：候选状态统计（Record<string, int>）
- `candidates_preview`：最多 20 条候选预览
- `validation_runs`：最近 10 条规则校验运行
- `latest_validation_summary`：最新已完成校验摘要（passed / failed / warning）
- `next_allowed_actions`：只读建议操作（由 batch.status 计算）

**next_allowed_actions 规则**（纯函数，无副作用）：

| batch.status | action |
|-------------|--------|
| `created` | `queue_batch` |
| `queued` | `start_batch` |
| `running` | `parse_aal3` |
| `parsed` | `generate_candidates` |
| `candidate_generated` | `validate_batch` |
| `validation_dispatched` / `completed` | 空列表 |
| `failed` / `cancelled` | 空列表 |

禁止的 actions（永远不出现）：`submit_review`、`approve`、`promote`、`llm_extract`。

### 新增前端文件

| 文件 | 说明 |
|------|------|
| `frontend/src/pages/ImportPipelinePage.tsx` | 主页面：左侧 Batch 列表 + 右侧 Pipeline Overview |
| `frontend/src/api/endpoints.ts`（修改） | 新增 `PipelineAction`、`ImportBatchPipelineOverview` 等类型和 `getImportBatchPipelineOverview` |
| `frontend/src/App.tsx`（修改） | 新增 `/import-pipeline` 路由 |
| `frontend/src/layout/WorkbenchLayout.tsx`（修改） | 新增导航项（GitBranch 图标） |
| `frontend/src/i18n.ts`（修改） | 新增 50+ `importPipeline.*` 中英文键 |
| `frontend/src/styles.css`（修改） | 新增 pipeline split layout、stepper、metrics、actions panel 等样式 |

### 页面功能

- **左侧**：Import Batch 列表，支持 status / resource_id 筛选，点击选中后右侧更新
- **右侧 Batch Overview**：
  - Batch Summary（代码、状态、资源 ID、类型、Parser）
  - Pipeline Stepper（Created → Queued → Running → Parsed → Candidates → Validated）
  - Next Actions 面板（状态驱动，每个操作须单独 ConfirmDialog 确认）
  - Bound Files 表格
  - Recent Events 表格
  - Parse Runs 表格
  - Raw Labels Preview（最多 20 条 + 总数 + 跳转链接）
  - Candidate Generation Runs 表格
  - Candidates Preview（最多 20 条 + 总数 + 跳转链接）
  - Rule Validation Runs 表格 + 跳转链接
  - Latest Validation Summary（passed / failed / warning 数值卡片）

### 状态驱动操作按钮

| 操作 | 调用已有 API |
|------|------------|
| Queue Batch | `POST /api/import-batches/{id}/queue` |
| Start Batch | `POST /api/import-batches/{id}/start` |
| Parse AAL3 | `POST /api/import-batches/{id}/parse-aal3` |
| Generate Candidates | `POST /api/import-batches/{id}/generate-candidates` |
| Validate Batch | `POST /api/rule-validation/run?batch_id=` |

操作成功后自动刷新 batch 列表和右侧 overview。

### 架构约束（本次实施确认）

- ❌ 不是一键全流程
- ❌ 不包含 Human Review / Promotion 操作按钮
- ❌ 不写 `final_*` / `kg_*`
- ❌ 不调用 LLM / Agent
- ❌ 不新增 migration
- ✅ 严格复用已有 backend API 和 service

### 测试结果

- **backend pytest**：176 passed（含新增 25 tests）
- **frontend npm run build**：TypeScript 0 错误，Vite build 成功

### 风险点

1. `generate_candidates` 如需指定 `parse_run_id`，当前从 endpoint 自动推断（batch 最新 succeeded parse run），无需手动传入
2. 若 batch 有多个 parse runs / candidate runs，overview 只预览最新数据，用户可跳转对应页面查看全量
3. `validation_dispatched` 状态后无自动操作，用户须跳转 Rule Validation 页面查看详情
4. 页面未实现 pagination，batch 列表上限 100 条
5. 此页面不替代现有 Import Batches / Raw AAL3 / Candidates / Rule Validation 页面，仍保留原有路由

### 下一步建议

**Candidate Governance Workspace**（Step C）：以 `candidate_id` 为核心，整合 candidate、raw source、rule validation、LLM suggestions、review、promotion；支持人工治理；不自动 approve / promote。

---

## 25. Resource Registry Granularity Workspace（已完成）

**完成时间**：2026-06-15

### 改造目标

将 `#/resources` 从混合列表改为**按颗粒度分区的资源登记工作台**。用户先选择颗粒度 tab，再在该颗粒度下创建、筛选和查看资源。

### 五个颗粒度 tab

| Tab | granularity_level | 推荐 family | 推荐 atlas | 默认示例 |
|-----|-------------------|-------------|------------|----------|
| Macro 宏观临床 | `macro` | `macro_clinical` | AAL3, Macro96 | `aal3_v1_macro` |
| Meso 中观解剖 | `meso` | `meso_anatomical` | HCP-MMP, Desikan, Destrieux | `hcp_mmp_v1_meso` |
| Micro 微观构筑 | `micro` | subregion_connectivity / cytoarchitectonic / histological | Brainnetome, Julich-Brain, BigBrain | `brainnetome_v1_micro` |
| Molecular 分子图谱 | `molecular` | `molecular` | Allen Human Brain Atlas | `allen_human_brain_atlas_molecular` |
| Term 术语本体 | `term` | `terminology` | InterLex, BrainInfo, UBERON, FMA | `interlex_terms` |

### 关键行为

- 顶部 5 个 tab/card，带资源数量 badge（前端按 `granularity_level` 分别查询 `total`）
- 当前 tab 说明卡（Macro 明确：AAL3 166 ROI ≠ Macro 96 Pool；Macro 96 Pool 尚未落库）
- 创建表单：`granularity_level` 创建时锁定为当前 tab；family 默认只显示推荐值，可切换「高级模式」显示全部
- 列表默认只显示当前 `granularity_level` 的资源；保留 status / source_atlas / granularity_family 筛选
- 选中 tab 持久化到 `localStorage`：`neurographiq.resources.activeGranularity`
- 完整 CRUD 保留：创建、查看、编辑、停用、复制 ID、刷新

### 新增/修改文件

| 文件 | 说明 |
|------|------|
| `frontend/src/config/granularity.ts` | **新增** — 颗粒度配置、默认值构建、family 过滤 |
| `frontend/src/pages/ResourcesPage.tsx` | **重构** — tab 布局 + 隔离列表 + 表单默认值 |
| `frontend/src/i18n.ts` | 新增 30+ `resources.granularity*` 中英文键 |
| `frontend/src/styles.css` | granularity tab / info card / badge 样式 |
| `frontend/src/components/Notice.tsx` | 新增 `warning` 类型 |

### 后端 API 检查

- `GET /api/resources` **已支持** `granularity_level`、`granularity_family`、`source_atlas`、`status` 筛选
- 后端枚举确认：`granularity_level` = macro / meso / micro / molecular / **term**；`resource_type` 无 `molecular_atlas`，Molecular 默认使用 `atlas`
- **后端未修改**

### 架构约束

- ❌ 不新增 migration
- ❌ 不写 `final_*` / `kg_*`
- ❌ 不调用 LLM
- ❌ 不把 AAL3 166 ROI 写成 Macro 96 Pool
- ❌ 不自动创建 batch / 上传文件

### 测试结果

- **frontend npm run build**：TypeScript 0 错误，Vite build 成功
- **backend pytest**：未运行（后端未修改）

### 下一步建议

**Resource Detail Workspace**：以 `resource_id` 为核心，展示资源、文件、批次、候选、final 概览与 provenance 总览。

---

## 26. Dashboard 精简 + 数据库切换（已完成）

**完成时间**：2026-06-15

### Dashboard 改造

`#/`` 仪表盘从「操作手册页」调整为简洁工作台首页：

**保留：**
- 后端健康状态（含 database 摘要）
- 当前数据库状态卡片
- 数据库切换 UI
- 核心统计：Final Regions / Resources / Import Batches / Candidates
- Session IDs 折叠面板
- 精简快捷入口（Resources、Files、Import Pipeline、Final Regions、Settings）

**删除：**
- MVP 1 十步完成列表
- 已激活模块完整大列表
- 12 步端到端长操作手册
- 过长 dbNotice 横幅

### 新增 Database Admin API

| 方法 | 路径 | 说明 |
|------|------|------|
| GET | `/api/database/status` | 当前连接库、schema 状态、连通性 |
| GET | `/api/database/databases` | 列出 PostgreSQL 实例全部库 + MVP1 schema 识别 |
| GET | `/api/database/validate?database=` | 验证指定库 MVP1 schema |
| POST | `/api/database/switch` | 切换到 MVP1-ready 库（body: `{ database }`） |

**schema_status 枚举：**
- `mvp1_ready`：001–008 核心表齐全且 `atlas_resources.resource_code` 存在
- `legacy`：含 legacy `atlas_code` 或无 `resource_code`（如 `neurographiq_kg_v3_wb`）
- `partial` / `empty` / `unreachable`

**安全约束：**
- 仅允许切换到 `mvp1_ready` 库
- 不返回密码或完整 DATABASE_URL
- 不创建/删除数据库
- 不自动执行 migration
- 运行时选择持久化到 `backend/data/runtime/database.local.json`（已在 `.gitignore`）
- 切换后 dispose 旧 engine 并 reload `AsyncSessionLocal`

**`/api/health` 增强：** 返回 `database.name`、`connected`、`schema_status`

### 新增/修改文件

| 文件 | 说明 |
|------|------|
| `backend/app/schemas/database_admin.py` | **新增** |
| `backend/app/services/database_admin_service.py` | **新增** |
| `backend/app/routers/database_admin.py` | **新增** |
| `backend/app/database.py` | runtime engine reload |
| `backend/app/main.py` | 注册 router + health 增强 |
| `backend/tests/test_database_admin.py` | **新增** 6 tests |
| `frontend/src/pages/DashboardPage.tsx` | **重构** |
| `frontend/src/api/endpoints.ts` | database API 封装 |
| `frontend/src/i18n.ts` | dashboard 新文案 |
| `frontend/src/styles.css` | dashboard 新样式 |
| `frontend/src/components/Notice.tsx` | 支持 warning 类型（前序任务已有） |

### 架构约束

- ❌ 不新增 migration
- ❌ 不写 `final_*` / `kg_*`
- ❌ 不调用 LLM

### 测试结果

- **backend pytest**：182 passed
- **frontend npm run build**：成功

### 下一步建议

**Resource Detail Workspace**

---

## Workspace Public Files / Dual File Import Modes

### 任务目标

文件中心现在支持两种文件导入方式：

1. **Resource-bound files**（资源文件）：原有逻辑不变。必须先有 `resource_id`，上传至 `backend/data/uploads/{resource_id}/` 目录，`resource_files.resource_id NOT NULL`，可进入 Import Batch / Raw Parsing / Candidate / Promotion / Final 溯源链路。
2. **Workspace public files**（公共文件）：新增方式。无需 `resource_id`，上传至 `backend/data/uploads/workspace/` 目录，存储在 `workspace_files` 表。可预览、编辑元数据、软删除、下载，**但不能直接进入 Import Batch**。

### 架构边界（严格执行）

- `resource_files.resource_id` **仍为 NOT NULL**，未修改。
- `POST /api/resources/{resource_id}/files` 原有接口未修改。
- `workspace_files` 记录不得直接出现在 `import_batch_files`。
- **Attach to Resource** 是公共文件进入正式链路的唯一桥梁：物理复制文件到 resource 目录，创建新 `resource_files` 行，记录 `source_workspace_file_id`。
- 公共文件不得直接 parse、generate candidate、写 `final_*`、写 `kg_*`、调用 LLM。
- 删除公共文件为软删除（`status=archived`），不影响已绑定的 `resource_files`。

### 新增 API（前缀 /api/workspace-files）

| 方法 | 路径 | 说明 |
|------|------|------|
| POST | `/api/workspace-files` | 上传公共文件 |
| GET  | `/api/workspace-files` | 列表 |
| GET  | `/api/workspace-files/{id}` | 详情 |
| PATCH| `/api/workspace-files/{id}` | 编辑元数据 |
| DELETE| `/api/workspace-files/{id}` | 软删除 |
| GET  | `/api/workspace-files/{id}/preview` | 预览 |
| GET  | `/api/workspace-files/{id}/download` | 下载 |
| POST | `/api/workspace-files/{id}/attach-to-resource` | 绑定到资源（进入正式链路的唯一入口） |

### 新增/修改文件

| 文件 | 说明 |
|------|------|
| `backend/migrations/011_workspace_files.sql` | **新增** |
| `backend/app/models/workspace_file.py` | **新增** |
| `backend/app/models/resource_file.py` | 新增 `source_workspace_file_id` |
| `backend/app/schemas/workspace_file.py` | **新增** |
| `backend/app/schemas/resource_file.py` | 新增 `source_workspace_file_id` |
| `backend/app/services/workspace_file_service.py` | **新增** |
| `backend/app/routers/workspace_files.py` | **新增** |
| `backend/app/main.py` | 注册 router |
| `backend/tests/test_workspace_files.py` | **新增** 11 tests |
| `frontend/src/api/endpoints.ts` | WorkspaceFile 类型 + API 函数 |
| `frontend/src/pages/FilesPage.tsx` | 双模式切换 + Workspace UI + Attach 对话框 |
| `frontend/src/i18n.ts` | workspace file i18n（中英文） |
| `frontend/src/styles.css` | file-mode-tabs / storage-scope-badge / attach-dialog |

### 测试结果

- **backend pytest**（test_workspace_files.py）：11 passed
- **frontend npm run build**：TypeScript 0 错误，Vite build 成功

### 不变约束

- 是否修改 resource_files.resource_id：**否**
- 是否允许公共文件进入 Import Batch：**否**
- 是否写入 final_*/kg_*：**否**
- 是否调用 LLM：**否**

---

## File Center Layout Polish

### 任务目标

优化 Files 页面布局，使文件中心成为高效工作台（仅前端布局/交互，无后端变更）。

### 布局优化内容

| 区域 | 优化 |
|------|------|
| 顶部 | PageHeader 右侧保留刷新 + 上传切换；压缩高度 |
| Toolbar | Mode tabs + Resource ID + 筛选器单行紧凑排列 |
| 上传面板 | 默认收起；点击「上传文件」展开；上传成功后自动收起 |
| 主区域 | 62% 列表 + 38% 预览 split layout；min-height calc(100vh - 260px) |
| 文件列表 | 移除独立 ID/SHA256 列；文件名下显示短 ID + copy；table-layout fixed |
| 右侧预览 | sticky + max-height；Tab 内容区 min-height 420px 内部滚动 |
| 空状态 | 紧凑提示，无大块虚线框 |
| 响应式 | ≤1100px 上下堆叠 |

### 修改文件

- `frontend/src/pages/FilesPage.tsx` — 布局重构、折叠上传、compact 表格、preview pane
- `frontend/src/styles.css` — `.files-page`、`.files-toolbar`、`.files-main-split` 等
- `frontend/src/i18n.ts` — 新增 layout 相关中英文 key

### 测试结果

- **frontend npm run build**：TypeScript 0 错误，Vite build 成功

### 不变约束

- 未修改后端 / 数据库 / migration
- 未修改文件上传业务逻辑

### 下一步建议

Import Batch 页面布局优化；Resource Detail Workspace。

---

## File Upload Auto-Normalization Fix

### 问题与根因

| 接口 | 500 根因 |
|------|----------|
| `GET /api/files/{id}/intermediate/runs` | 数据库未执行 `010_file_normalization.sql`，`file_normalization_runs` 表不存在 |
| `GET /api/files/{id}/intermediate` | 同上，`file_intermediate_artifacts` 表不存在 |
| `POST /api/files/{id}/normalize` | 同上，ORM 查询抛未捕获 SQL 异常 → 500 |

**修复**：执行 migration 010 后接口返回 200/404/422；无中间态时返回空结构 `status=missing`，不再 500。

### 实现内容

1. **上传后自动生成中间态**：`POST /api/resources/{resource_id}/files` 保存原始文件后同步调用 `auto_normalize_after_upload`；写入 `file_normalization_runs` + `file_intermediate_artifacts`。
2. **Workspace 公共文件**：`POST /api/workspace-files` 不直接写中间态（无 `resource_id`）；`attach-to-resource` 创建 `resource_files` 后同样自动 normalize。
3. **AAL3 XML** → `artifact_kind=label_table`，`schema_version=intermediate_v1`，`content_jsonb.rows` 供 Raw Parsing 消费。
4. **Raw Parsing AAL3** 优先读取 latest active `label_table` intermediate；缺失时 fallback 原始 XML 并记录 warning。
5. **ResourceFileRead 增强**：响应含 `intermediate_status`、`latest_intermediate_*` 只读摘要字段。
6. **前端 FilesPage**：上传成功后自动显示 ready/failed；Intermediate tab 自动加载；Normalize 按钮改为「重新生成中间态」。

### Migration

| 文件 | 状态 |
|------|------|
| `backend/migrations/010_file_normalization.sql` | 已存在；**未自动执行** |

**手动执行命令（其他环境）：**

```bash
psql -h 127.0.0.1 -U postgres -d neurographiq_kg_v3_mvp1_e2e -f backend/migrations/010_file_normalization.sql
```

本 dev 环境 migration 010 已手动执行。

### 新增/修改后端文件

| 文件 | 说明 |
|------|------|
| `backend/app/services/file_normalization_service.py` | `auto_normalize_after_upload`、`get_intermediate_summary_for_file`、健壮 normalize |
| `backend/app/routers/file_normalization.py` | `/intermediate`、`/intermediate/runs`、`/normalize?force=` |
| `backend/app/routers/resource_files.py` | 上传后 auto-normalize；`_to_resource_file_read` 摘要 |
| `backend/app/services/workspace_file_service.py` | attach 后 auto-normalize |
| `backend/app/schemas/resource_file.py` | intermediate 摘要字段 |
| `backend/app/schemas/file_normalization.py` | 扩展 `FileIntermediateStatusResponse` |
| `backend/tests/test_file_normalization.py` | API 不 500、AAL3 label_table、边界检查 |
| `backend/tests/test_raw_parsing_aal3.py` | intermediate vs XML 输出一致 |

### 前端修改

- `frontend/src/api/endpoints.ts` — ResourceFile intermediate 字段；`normalizeFile(id, force)`；路径 alias
- `frontend/src/pages/FilesPage.tsx` — 上传后 auto-ready/failed UI；Intermediate 列颜色；Regenerate 确认
- `frontend/src/i18n.ts` — auto-normalize / regenerate 中英文
- `frontend/src/styles.css` — intermediate status badge 颜色

### 测试结果

- **backend pytest**：212 passed
- **frontend npm run build**：TypeScript 0 错误，Vite build 成功

### 不变约束

- 是否自动 parse/candidate/final：**否**
- 是否写入 final_*/kg_*：**否**
- 是否调用 LLM：**否**
- 是否自动创建 Import Batch：**否**

### 下一步建议

AAL3 XML 上传 → 自动中间态 → parse-aal3 浏览器端联调。

---

## Intermediate Semantic Normalization Enhancement

### 问题

`.xlsx` / `.pdf` 等文件在 `_dispatch_normalizer` 中无专用分支，落入 `binary_metadata`，仅记录 sha256 / file_size 等文件级信息。

### 实现

| 文件类型 | artifact_kind | normalizer_key |
|----------|---------------|----------------|
| `.xlsx` / `.xls` | `spreadsheet_workbook` (+ 可选 `macro_region_table`) | `spreadsheet_workbook_v1` / `macro_region_table_v1` |
| Brain volume list.xlsx（列匹配 Macro 96） | `macro_region_table` | `macro_region_table_v1` |
| `.pdf` | `pdf_metadata` | `pdf_metadata_v1` |
| `.xml` AAL3 | `label_table` | `aal3_xml_label_table_v1` |
| unknown binary | `binary_metadata` | `generic_metadata_v1` |

### Migration

- `backend/migrations/012_extend_intermediate_artifact_kinds.sql` — 扩展 `artifact_kind` / `source_format` CHECK
- **未自动执行**（dev 环境已手动执行）

```bash
psql -h 127.0.0.1 -U postgres -d neurographiq_kg_v3_mvp1_e2e -f backend/migrations/012_extend_intermediate_artifact_kinds.sql
```

### 新增/修改文件

| 文件 | 说明 |
|------|------|
| `backend/app/utils/intermediate_normalizers.py` | **新增** Excel/PDF/Macro 96 语义 normalizer |
| `backend/app/services/file_normalization_service.py` | 多 artifact/run；扩展 dispatch |
| `backend/app/utils/file_meta.py` | `infer_file_role` / `suggest_file_classification` |
| `backend/app/schemas/resource_file.py` | `macro_region_pool_source` FileRole |
| `backend/migrations/012_extend_intermediate_artifact_kinds.sql` | **新增** |
| `backend/tests/fixtures/brain_volume_list_sample.xlsx` | **新增**（测试 fixture） |
| `backend/tests/test_file_normalization.py` | xlsx/pdf/macro 测试 |
| `frontend/src/pages/FilesPage.tsx` | 上传建议 + Intermediate tab 表格预览 |
| `frontend/src/i18n.ts` / `styles.css` | 文案与样式 |

### 边界（不变）

- macro_region_table **≠** Macro 96 Pool 正式入库
- 不写 candidate / final_* / kg_*
- 不调用 LLM
- 不自动 parse / batch

### 测试结果

- **backend pytest**：218 passed
- **frontend npm run build**：成功

### 下一步建议

Macro 96 Region Pool Import 设计。

---

## Workbench Bottom Log Console

### 目标

全局底部可收起/展开的 **Log Console**，捕获前端 API 错误、500 response body、`window.onerror`、`unhandledrejection` 等，便于调试。

### 新增文件

| 文件 | 说明 |
|------|------|
| `frontend/src/logging/workbenchLogTypes.ts` | 日志类型定义 |
| `frontend/src/logging/logBridge.ts` | client 与 Provider 桥接 |
| `frontend/src/logging/WorkbenchLogContext.tsx` | Log Provider + 全局错误捕获 |
| `frontend/src/logging/useWorkbenchLog.ts` | Hook |
| `frontend/src/components/BottomLogConsole.tsx` | 底部 UI |

### 修改文件

- `frontend/src/api/client.ts` — API 失败时写入日志，保留完整 responseBody
- `frontend/src/main.tsx` — 挂载 `WorkbenchLogProvider`
- `frontend/src/layout/WorkbenchLayout.tsx` — 底部挂载 `BottomLogConsole`
- `frontend/src/i18n.ts` / `styles.css`

### 功能

- 展开/收起；收起时显示错误数 + 最后一条错误摘要
- 筛选 all / error / warning / info / request
- 复制单条 / 复制全部 / 清空
- 最近 200 条；localStorage 可选持久化
- 不写 final_* / kg_*；不改业务逻辑

### 测试结果

- **frontend npm run build**：成功

---

## Import Pipeline Bound File Active-State Guard

### 当前问题

用户在 `#/import-pipeline` 点击「解析 AAL3」时，若 batch 绑定的 label 文件 `status != active`（如 archived），后端 `POST /api/import-batches/{batch_id}/parse-aal3` 返回 **409**，此前前端仍显示可点击按钮，用户点击后才看到错误。

### 修复内容

| 层 | 变更 |
|----|------|
| **后端 parse-aal3** | 继续禁止解析 inactive / archived / deleted 文件；409 `detail` 结构化：`code=BOUND_FILE_NOT_ACTIVE`、`file_id`、`file_status`、`batch_id`、`suggestion` |
| **overview** | `GET /api/workbench/import-batches/{batch_id}/overview` 的 `bound_files[]` 含 `file_status`、`is_active`、`can_parse`、`inactive_reason`、`intermediate_status` 等 |
| **next_allowed_actions** | `batch.status=running` 时，仅当存在 active 且可解析的 label 文件才 `parse_aal3.enabled=true` |
| **前端 Import Pipeline** | Bound Files 展示状态与警告；Parse AAL3 按 overview 禁用并显示 reason；409 展示完整 message；「前往文件中心」写入 session `resource_id` / `file_id` 后跳转 `#/files` |

### 用户修复路径（不自动执行）

1. 在 **文件中心** 将 archived 文件恢复为 active（若 PATCH 支持 status 编辑）；
2. 或 **新建 batch**，绑定 active AAL3 XML → queue → start → Parse AAL3。

### 禁止行为（本轮未做）

- 不自动恢复 / 替换绑定 / 新建 batch / parse / generate / review / promote
- 不放宽 active 校验；不写 final_* / kg_*；不调用 LLM

### 修改文件

- `backend/app/services/raw_parsing_service.py` — `BoundFileNotActiveError`、`evaluate_batch_parse_readiness`、`assess_bound_file_parse_status`
- `backend/app/routers/raw_parsing.py` — 结构化 409
- `backend/app/services/workbench_pipeline_service.py` — enriched `bound_files`、`parse_aal3` 禁用逻辑
- `backend/app/schemas/workbench_pipeline.py` — `BoundFilePipelineRead`
- `frontend/src/pages/ImportPipelinePage.tsx` — 状态展示、按钮禁用、跳转
- `frontend/src/api/endpoints.ts` / `i18n.ts` / `styles.css`
- `backend/tests/test_raw_parsing_aal3.py` / `test_workbench_pipeline.py`

### 测试结果

- **backend pytest**：224 passed
- **frontend npm run build**：成功

### 下一步建议

重新创建 batch 绑定 active AAL3 XML，并完成 parse-aal3 浏览器端联调。

---

## Import Batch CRUD & Management Completion

### 目标

完善 `#/import-batches` 为完整导入批次**管理页**（登记 / 查看 / 编辑 / 绑定文件 / 取消）；`#/import-pipeline` 仍为状态驱动执行页。

### 后端新增/增强

| API | 说明 |
|-----|------|
| `PATCH /api/import-batches/{batch_id}` | 编辑 metadata；`created` 可改 batch_type/parser_key/description/remark；`queued` 仅 description/remark |
| `PATCH /api/import-batches/{batch_id}/files` | 仅 `created` 可替换绑定 files |
| `GET .../files` / detail | 返回 `ImportBatchFileEnrichedRead`：file_status、intermediate_status、can_parse、warning 等 |
| `POST .../cancel` | 复用（无物理 DELETE） |

约束：workspace_file_id 不可直接绑定；inactive file 不可绑定；不级联删 raw/candidate/final；不写 final_* / kg_*。

### 前端

- Split layout：左侧列表 + 右侧详情 Tabs（Overview / Files / Events / Raw JSON）
- 状态驱动：queue / start / cancel；跳转 Import Pipeline（session batch_id）
- `created` 可编辑核心字段与 files；running+ 只读提示

### 测试结果

- **backend pytest**：232 passed
- **frontend npm run build**：成功

### 下一步建议

在浏览器完成 created → queue → start → Import Pipeline parse-aal3 全链路联调。

---

## Import Batch List Interaction Polish

### 修复内容

- 左侧批次列表改为 **card-list**：点击整行选中并加载右侧详情（`role="button"` + Enter/Space）
- 去除行内「查看」「进入导入流水线」按钮；进入流水线保留在右侧详情操作区
- `CopyButton` 扩展 `title` / `ariaLabel`；列表与详情复制按钮 tooltip 明确（Batch ID / Resource ID / Parser Key / Batch Code）
- status badge 与 created_at **分两行**右对齐，长状态（如 `candidate_generated`）不再遮挡日期

### 修改文件

- `frontend/src/components/CopyButton.tsx`
- `frontend/src/pages/ImportBatchesPage.tsx`
- `frontend/src/i18n.ts`
- `frontend/src/styles.css`

### 测试结果

- **frontend npm run build**：成功

### 下一步建议

在 `#/import-batches` 选中 running batch，从右侧进入 Import Pipeline 完成 parse-aal3 联调。

---

## Import Batch Create UX Refinement

### 修复内容

- 点击右上角「创建批次」进入 **完整创建表单视图**（`pageMode: create`），不再在列表上方折叠展开
- 创建批次 **不再要求手填 resource_id / file_id**
- **Resource 选择器**：`GET /api/resources`（active），显示 `source_atlas | resource_code | version | granularity | status`
- **File 文件名选择器**：`GET /api/resources/{id}/files`，仅展示 **active** 文件；选项含 filename / file_type / file_role / status / intermediate / size
- 请求体仍提交 `resource_id` + `files[].file_id`（后台 UUID 隐藏于 UI，摘要卡可短 ID 复制）
- 文件 intermediate：`ready` 绿色提示；`missing` 黄色提示（不阻止创建）
- Excel（`.xlsx`）**不默认** `parser_key=aal3_xml`；显示 Macro 96 未实现提示
- AAL3 XML / AAL3 resource 自动默认 `batch_type=atlas_import`、`parser_key=aal3_xml`、`file_role_in_batch=label_dictionary`
- 创建成功 → 返回列表并选中新建 batch；取消 → 返回列表；不自动 queue/start/parse

### 修改文件

- `frontend/src/pages/ImportBatchesPage.tsx` — `CreateBatchWorkspace` + `pageMode`
- `frontend/src/i18n.ts` — 创建流程中英文文案
- `frontend/src/styles.css` — `.batch-create-*` 样式

### 测试结果

- **frontend npm run build**：成功（TypeScript 0 错误）

### 下一步建议

Import Batch 创建流程浏览器端联调（选 AAL3 resource + XML 文件 → 创建 → 列表选中 → 进入 Import Pipeline）。

---

## Import Batch Create Modal UX Fix

### 修复内容

- 创建批次从 **整页 create mode** 改为 **居中 Modal**（`isCreateModalOpen`），列表 + 详情布局保持不变
- Modal 内 **三列横向布局**：资源选择 | 文件选择 | 批次参数（窄屏自动上下排列）
- 资源 / 文件仍通过名称选择，后台提交 `resource_id` + `file_id`
- 清理 `pageMode === 'create'` 整页切换；组件统一为 `CreateBatchModal`
- 修复潜在 `CreateBatchForm is not defined`（旧组件名残留 / HMR 缓存）：源码中不再引用 `CreateBatchForm`
- Excel 不默认 `aal3_xml`；PDF 显示文档证据提示
- Modal `z-index: 1100`（高于底部日志控制台）；Esc 关闭；右上角关闭按钮

### 修改文件

- `frontend/src/pages/ImportBatchesPage.tsx`
- `frontend/src/i18n.ts`
- `frontend/src/styles.css`

### 测试结果

- **frontend npm run build**：成功

### 下一步建议

Import Batch 创建流程浏览器端联调。

---

## AAL3 Parse Compatibility Guard

### 问题与原因

- batch `f64aa7a5-1db1-4f88-9a5c-25968908cbb2` 等场景：`parse-aal3` 返回 `400 no XML label dictionary produced parse output`
- 根因：batch 绑定了 **非 AAL3 XML** 文件（典型：`Brain volume list.xlsx` + `parser_key=aal3_xml`），旧逻辑因 `file_role_in_batch=label_dictionary` 误判为可解析，循环 skip 非 XML 后输出为空

### 修复内容

**后端**

- `assess_aal3_xml_parser_compatibility()` — 明确排除 xlsx/pdf/nii/图片/spreadsheet intermediate 等
- `parse-aal3` 400 返回结构化 detail：`code=NO_AAL3_XML_LABEL_DICTIONARY` + `bound_files[].reason`
- Workbench overview `bound_files` 增加：`parser_compatible_for_aal3_xml`、`parser_incompatible_reason`、`latest_intermediate_kind/schema`
- `next_allowed_actions.parse_aal3` 在无兼容文件时 `enabled=false`

**前端**

- 创建 batch Modal：`parser_key=aal3_xml` 时仅显示兼容 XML 文件，阻止 xlsx/pdf 创建
- Import Pipeline：Bound Files 显示 parser compatibility；Parse AAL3 禁用 + 原因；Notice 展示 structured detail
- `CreateBatchForm` / `pageMode` 残留已清理（当前使用 `CreateBatchModal` + `isCreateModalOpen`）

### 测试结果

- **backend pytest**：240 passed
- **frontend npm run build**：成功

### 下一步建议

用 active AAL3 XML 文件新建 batch，完成 queue → start → parse-aal3 全链路联调。

---

## Resource Registry Macro Presets: AAL3 and Macro96

### 背景

Macro tab 下创建资源时，表单曾默认偏向 AAL3（`source_atlas=AAL3`、`resource_code=aal3_v1_macro`），无法清晰登记导师整理的 **Brain volume list.xlsx** 对应的 Macro96 标准池资源。

### 实现内容

**Macro tab 新增两个创建预设（并列、可切换）：**

| 预设 | source_atlas | resource_code | 用途 | 后续 parser_key |
|------|--------------|---------------|------|-----------------|
| AAL3 宏观图谱 | AAL3 | aal3_v1_macro | AAL3 XML label dictionary | aal3_xml |
| Macro96 标准池 | Macro96 | macro96_standard_pool_v1 | Brain volume list.xlsx 96 脑区标准池 | macro96_xlsx |

- 预设卡片位于 Macro 说明卡下方；选中项高亮；点击预设打开创建表单并填入对应默认值
- Macro96 表单上方显示说明卡与警告：**Macro96 ≠ AAL3 166 ROI**；Brain volume list.xlsx 不应走 aal3_xml
- `granularity_level` 锁定 `macro`；`granularity_family` 默认 `macro_clinical`
- 后端无 `standard_pool` resource_type 时，前端 fallback 为 `atlas` 并显示黄色提示（语义仍按标准池管理）
- `template_space=not_applicable` 后端已支持；若不可用则 fallback `unknown` 并提示
- Macro tab 资源列表：`resource_code` 列显示 **AAL3 图谱** / **Macro96 标准池** badge，不自动合并
- Macro96 创建成功后：Notice + 可选「前往文件中心上传 Brain volume list.xlsx」；`resource_id` 写入 sessionIds

### 修改文件

- `frontend/src/config/granularity.ts` — `MACRO_RESOURCE_PRESETS`、`buildMacroPresetForm`、识别 helper
- `frontend/src/pages/ResourcesPage.tsx` — 预设卡片、表单默认值、列表 badge、创建成功引导
- `frontend/src/i18n.ts` — 中英文文案
- `frontend/src/styles.css` — `.resource-preset-*`、`.resource-source-badge-*`

### 边界（本轮未做）

- ❌ 不实现 macro96_xlsx parser
- ❌ 不实现 AAL3 ↔ Macro96 mapping
- ❌ 不写 final_* / kg_*
- ❌ 不调用 LLM
- ❌ 不新增 migration / 后端字段

### 关系说明

AAL3 与 Macro96 **并列**于 Macro / macro_clinical 层，**不自动合并**；后续通过 explicit mapping（exact_match、close_match、part_of、overlaps 等）关联。

### 测试结果

- **frontend npm run build**：成功（TypeScript 0 错误）
- **backend**：未修改

### 下一步建议

创建 Macro96 resource，并在文件中心上传 Brain volume list.xlsx。

---

## Resource File Duplicate/List Consistency Fix

### 问题根因（2026-06-15 SQL 核实）

- **resource_id** `5a5220d8-eba3-4c8e-b24e-0585f623d4d8`（`macro96_standard_pool_v1`）**status=active**，存在
- 该 resource 下 **resource_files 行数 = 0**（active 列表 0 条属实）
- **sha256** `5e1b1037…db92d` 仅存在于 **旧 resource** `265de122-ec2b-4907-ab0e-b03cc36d23f4`（2 条 archived），**不在新 resource 下**
- 用户上传 Brain volume list.xlsx 时 `file_role=macro_region_pool_source`，但 DB CHECK `chk_resource_files_file_role` **未包含该 role** → INSERT **IntegrityError**
- 旧代码将所有 IntegrityError 误判为 duplicate，返回 **409 且无 existing_file**，造成「后端说重复、列表 0 条」的严重误导

### 修复内容

**Migration 014** — `014_resource_files_macro_role.sql`：CHECK 增加 `macro_region_pool_source`（需手动执行）

**后端**

- `_integrity_error_is_sha256_duplicate()`：仅 unique index 冲突才视为 duplicate
- 其他约束违反 → **422 FileValidationError**（非假 409）
- duplicate 409 必须返回完整 `existing_file`（含 intermediate 摘要）
- inactive/archived → `DUPLICATE_RESOURCE_FILE_INACTIVE`
- `GET files?status=active|inactive|archived|all`（inactive 别名 archived）
- `POST /api/files/{id}/restore` — 恢复 active
- `POST /api/files/{id}/destructive-delete` — 强确认彻底删除元数据（无下游绑定时可重传同 sha256）
- resource destructive-delete 已清理该 resource 下 `resource_files` 及中间态

**前端 Files**

- duplicate 409 → 自动选中 existing_file；无 existing_file 时 `status=all` 按 sha256 查找
- inactive duplicate → 切换全部状态 +「恢复 active」
- 422 校验失败单独提示（非 duplicate）
- Import Batch 仅允许 active 文件

### 测试结果

- **backend pytest tests/**：通过
- **frontend npm run build**：通过

### 下一步建议

恢复并选中已有 Brain volume list.xlsx 后，创建 `macro96_xlsx` 导入批次。

---

## Import Batch Parser-aware File Selection Fix

### 问题

- 创建批次弹窗 `CreateBatchModal` 初始 `parser_key` 硬编码为 **`aal3_xml`**
- 选择 Macro96 resource 后未根据 `source_atlas` / `resource_code` 切换 parser
- Step 2 文件过滤仅实现 `aal3_xml` 兼容逻辑，**Brain volume list.xlsx** 被当作不兼容文件隐藏

### 修复

**前端 Import Batches**

- `inferBatchDefaultsFromResource()`：AAL3 → `aal3_xml` + `label_dictionary`；Macro96 → `macro96_xlsx` + `macro_region_pool_source`
- 选择 resource 后自动更新 `batch_type` / `parser_key` / `file_role_in_batch` 并清空已选文件
- `getFileParserCompatibility()`：AAL3 XML 与 Macro96 Excel 分离过滤
- Step 2 / Step 3 parser-aware 提示文案；创建按钮按兼容性禁用并显示原因
- Import Pipeline：`parser_key=macro96_xlsx` 时显示「解析 Macro96」，不误导为 AAL3 parse

**后端（最小扩展）**

- `FileRoleInBatch.macro_region_pool_source` + migration `015_import_batch_macro_role.sql`（批次绑定 role）

### 测试结果

- **frontend npm run build**：通过
- **backend pytest tests/**：通过

### 下一步建议

用 Macro96 resource + Brain volume list.xlsx 创建 `macro96_xlsx` 批次后，实现 `parse-macro96` API。

---

## Import Batch Macro96 File Role Support

### 问题

- 前端 Macro96 批次正确发送 `file_role_in_batch=macro_region_pool_source`
- 旧版后端 `FileRoleInBatch` 枚举与 DB CHECK 未包含该值 → **422**
- 运行中的 uvicorn 进程（8002）若未重启，仍返回旧 options 列表（无 `macro_region_pool_source`）

### 修复

**后端**

- `FileRoleInBatch.macro_region_pool_source`（`backend/app/schemas/import_batch.py`）
- Migration `015_import_batch_macro_role.sql` — `chk_import_batch_files_role` CHECK 扩展（**手动执行，不自动跑**）
- `GET /api/import-batches/options` 自动从 enum 返回全部 file roles

**前端**

- Macro96 默认 `file_role_in_batch=macro_region_pool_source` 不变
- 下拉显示友好标签 + 描述文案（i18n）

### 测试结果

- **backend pytest tests/**：通过（含 schema / options / integration create）
- **frontend npm run build**：通过
- **重启 backend 后** options 含 `macro_region_pool_source`，Macro96 batch POST **201**

### 下一步建议

创建 Macro96 批次成功后，实现 `parse-macro96` API。

---

## Files Page Resource Selector UX Refinement

### 变更摘要

- **#/files** 资源文件模式不再要求手填 **Resource ID** UUID
- 顶部改为 **资源搜索 + 下拉选择器**（`source_atlas | resource_code | version | granularity | status`）
- 选中后显示 **资源摘要卡**（含 resource_code、source_atlas、版本、颗粒度、状态、中英文名；**resource_id 短 ID + copy**，非主输入）
- 列表标题显示当前 **resource_code**；空状态区分「未选资源」与「当前资源暂无文件」
- **上传 / 查询 / duplicate 处理** 均使用内部 `selectedResourceId`，API 仍为 `GET|POST /api/resources/{resource_id}/files`
- Session 中已有 `resource_id` 时自动反查选中；列表中不存在则显示 warning 要求重选
- 兼容 hash query：`#/files?resource_id=...`
- **公共文件 → Attach to Resource** 对话框同样使用资源选择器，不再手填 UUID

### 修改文件

- `frontend/src/pages/FilesPage.tsx` — 资源选择器、摘要卡、session 反查、上传/duplicate/attach 联动
- `frontend/src/i18n.ts` — 中英文 `files.selectResource*` 等文案
- `frontend/src/styles.css` — `.files-resource-*` 样式

### 边界（本轮未做）

- ❌ 不修改后端业务逻辑 / migration / 数据库
- ❌ 不写 final_* / kg_*
- ❌ 不调用 LLM
- ❌ 公共文件（workspace）模式 UI 除 Attach 外不变

### 测试结果

- **frontend npm run build**：成功（TypeScript 0 错误，Vite build 成功）
- **backend**：未修改

### 下一步建议

在文件中心选择 AAL3 / Macro96 资源，上传 Brain volume list.xlsx，确认 duplicate 与恢复 active 流程；随后在批次管理用 macro96_xlsx parser 创建批次。

---

## Resource Archive / Restore / Purge Semantics

### 问题根因

- 工作台「删除资源」实际调用 `DELETE /api/resources/{id}` → **软删除（archive）**，设置 `deleted_at` + `status=archived`
- `resource_code` **唯一约束**仍生效，archived 资源仍占用编码
- 默认列表 `deleted_at IS NULL`，用户看不到 archived 资源，误以为已删除，重建同 code 时 409

### 数据库核实（macro96_standard_pool_v1）

- **仍存在**：`id=63dd6d39-5c35-4509-96ec-3929f72dd56d`，`status=archived`，`deleted_at` 非空
- **依赖**：files=0, batches=0, raw=0, candidates=0, final=0 → **允许 purge**

### 后端策略

- `DELETE /api/resources/{id}` → archive（不变）
- `POST /api/resources/{id}/restore` → 恢复 active（检查无其他 active 同 code）
- `POST /api/resources/{id}/purge` → 无依赖时物理删除
- `GET /api/resources?status=active|archived|all`
- `POST /api/resources` duplicate 409 → `DUPLICATE_RESOURCE_CODE` + `existing_resource` + `can_restore` + `can_purge` + `dependency_counts`

### 前端

- 资源页状态筛选：active / archived / all
- 「归档」替代「删除」文案
- archived 行：恢复 / 彻底删除
- duplicate 409：恢复 / purge 后重建 / 改 code
- Macro96 preset 显示已存在状态

### 测试结果

- **backend pytest tests/**：252 passed
- **frontend npm run build**：成功（TypeScript 0 错误）

### 下一步建议

在 #/resources 切换「全部」，对 macro96_standard_pool_v1 执行 purge 或 restore，然后重建或继续使用。

---

## Destructive Cascade Resource Delete

### 用户决策

- 即使资源存在下游依赖，操作员在**强确认**后也可**级联彻底删除**该资源及全部关联数据
- 删除完成后 **释放 `resource_code`**，允许重新创建同名资源
- 归档（archive）仍保留为可选操作，但资源页主「彻底删除」走 destructive cascade

### 新增 API

- `GET /api/resources/{resource_id}/delete-preview` — 只读依赖统计 + `required_confirmation: DELETE {resource_code}`
- `POST /api/resources/{resource_id}/destructive-delete` — body: `confirmation_text`, `operator`, `reason`, `delete_physical_files`（默认 false）

### 删除顺序（下游 → 上游）

`promotion_records` → `final_brain_regions` → `candidate_llm_extractions` → `candidate_rule_validation_results` → `candidate_review_records` → `rule_validation_runs` → `candidate_brain_regions` → `candidate_generation_runs` → `raw_aal3_region_labels` → `raw_macro96_region_rows`（若表存在）→ `raw_parse_runs` → `import_batch_events` → `import_batch_files` → `import_batches` → `file_intermediate_artifacts` → `file_normalization_runs` → `resource_files` → `atlas_resources`

### 审计表

- `backend/migrations/013_destructive_resource_delete_records.sql` → `destructive_resource_delete_records`
- **不自动执行 migration**；表不存在时服务降级为日志审计

### 前端

- 资源行：归档 / 恢复 / **彻底删除**（危险确认弹窗）
- 弹窗展示 delete-preview、dependency_counts、确认文本 `DELETE {resource_code}`、operator、reason、可选物理文件删除
- duplicate 409（archived/inactive）：恢复 / **彻底删除后重新创建** / 改 code
- 删除成功后刷新列表、清除 session `resource_id`（若命中）

### 测试结果

- **backend pytest tests/**：258 passed（含 `test_resource_destructive_delete.py`）
- **frontend npm run build**：成功（TypeScript 0 错误）

### 下一步建议

1. 手动执行 migration 013 以启用 DB 审计表
2. 在 #/resources 对 `macro96_standard_pool_v1` 验证 destructive delete + 重建
3. 若有下游数据资源，先 preview 再 destructive delete，确认 dependency_counts 与 DB 一致

---

## Resource Delete/Recreate Crash Fix and Backend API Completion

### 问题根因

- **purgeTarget undefined**：旧版 ResourcesPage 引用 `purgeTarget` 但未定义；已统一为 `destructiveDeleteTarget`
- **Should have a queue**：由上述运行时崩溃引发 React 内部错误；Hook 均在组件顶层，无条件下调用
- **status=all 422**：UI「全部」曾传 `status=all`；`cleanResourceParams()` / `sanitizeResourceQuery()` 过滤；后端 router 也将 `all` 归一为不传
- **delete-preview 404**：多为后端未重启，旧进程无新路由
- **resource_code 409**：archived 资源仍占用 code；需 destructive-delete 释放

### 修复摘要

- 前端：`ResourceDestructiveDeleteModal`、`destructiveDeleteTarget`、duplicate 409 回查列表、preview 404 容错
- 后端：`GET delete-preview`、`POST destructive-delete`、duplicate detail 增强（`delete_preview_url`、`can_destructive_delete`）
- DB 状态（2026-06-15）：`macro96_standard_pool_v1` 在 `neurographiq_kg_v3_mvp1_e2e` 中**已删除**，可直接重建

### 测试结果

- **backend pytest tests/**：258+ passed
- **frontend npm run build**：成功

### 下一步建议

重启后端后验证 delete-preview；创建 `macro96_standard_pool_v1`；上传 Brain volume list.xlsx

---

## Resource Page Status Filter and Macro Preset Bugfix

### 修复摘要

- **422**：前端 `status=all` 不再传给 `GET /api/resources`；`sanitizeResourceQuery()` 在 `endpoints.ts` 统一过滤
- **preset 查询**：`listResources({ limit: 200 })` 替代 `status=all`
- **reading 'aal3'**：`buildMacroPresetExisting` + `EMPTY_MACRO_PRESET_EXISTING` + 可选链 `presetExisting?.[key]`
- **筛选**：切换 Macro preset 时清空 `source_atlas` 过滤；新增 inactive 状态选项

### 测试结果

- **frontend npm run build**：成功
- **backend**：未修改

---

---

## Macro96 Raw Parsing Backend Foundation

### 背景

Macro96 链路在本轮之前已完成：
- Macro96 resource 可登记、Brain volume list.xlsx 可上传
- 文件中心可生成 `macro_region_table_v1` 中间态
- Import Batch 可创建 `parser_key=macro96_xlsx`、`file_role_in_batch=macro_region_pool_source`
- Import Pipeline 显示"Macro96 解析器尚未实现"

本轮实现后端 raw parsing 最小闭环，不做 candidate generation / mapping / final_* / kg_*。

### 新增数据库 SQL

| 文件 | 内容 |
|------|------|
| `backend/migrations/016_raw_parsing_macro96.sql` | 新增 `raw_macro96_region_rows` 表；扩展 `import_batch_events.event_type` CHECK 加入 `parse_macro96_started/succeeded/failed` |

**是否自动执行：否**，需手动执行。

### 新增/修改后端文件

| 文件 | 类型 | 说明 |
|------|------|------|
| `backend/app/models/raw_macro96.py` | 新增 | `RawMacro96RegionRow` ORM model |
| `backend/app/schemas/macro96_raw_parsing.py` | 新增 | `ParseMacro96Response`、`RawMacro96RegionRowRead`、`RawMacro96RegionRowListResponse` |
| `backend/app/parsers/macro96_xlsx.py` | 新增 | `parse_macro96_table_from_intermediate()` 纯函数解析器 |
| `backend/app/schemas/raw_parsing.py` | 修改 | `ParserKey` enum 加入 `macro96_xlsx` |
| `backend/app/models/__init__.py` | 修改 | 导出 `RawMacro96RegionRow` |
| `backend/app/services/raw_parsing_service.py` | 修改 | 新增 `parse_macro96_for_batch()`、`list_macro96_rows()`；引入 Macro96 相关错误类 |
| `backend/app/routers/raw_parsing.py` | 修改 | 新增 `POST /{batch_id}/parse-macro96`、`GET /macro96-rows` |
| `backend/app/services/workbench_pipeline_service.py` | 修改 | `compute_next_allowed_actions()` 支持 `parser_key`；Macro96 返回 `parse_macro96` action |
| `backend/tests/test_raw_parsing_macro96.py` | 新增 | 28 个 unit test |

### 新增 API

| 方法 | 路径 | 说明 |
|------|------|------|
| `POST` | `/api/import-batches/{batch_id}/parse-macro96` | 触发 Macro96 raw parsing，返回 `ParseMacro96Response` |
| `GET` | `/api/raw-parsing/macro96-rows` | 查询 `raw_macro96_region_rows`，支持 resource_id/batch_id/parse_run_id/source_file_id/limit/offset |

### Parser 行为

- **输入**：`FileIntermediateArtifact.content_jsonb`（`artifact_kind=macro_region_table`）
- **中间态**：必须有 `schema=macro_region_table_v1`，rows 非空
- **输出**：`raw_macro96_region_rows` 每行含 row_index/region_index/en_name/cn_name/source_sheet/raw_payload
- **错误处理**：schema 不匹配 → `Macro96IntermediateInvalidError`；rows 空/重复 region_index/bad region_index → `Macro96ParseError`；缺 intermediate → 400
- **幂等**：已有 `succeeded` run 的 batch 再次调用返回 409

### 是否生成 candidate

**否**

### 是否写入 final_* / kg_*

**否**

### 是否调用 LLM / Agent

**否**

### 测试结果

```
backend pytest tests/: 295 passed, 7 skipped (async tests skipped — no pytest-asyncio)
test_raw_parsing_macro96.py: 28 passed, 7 skipped
全套 tests/ 通过
```

### 下一步建议

实现 RawMacro96Page，展示 raw_macro96_region_rows 列表。

---

## § Import Pipeline parse-macro96 Frontend Integration

**完成时间**：2026-06-15

### 本次实现模块

Frontend Import Pipeline 接入 parse-macro96。

### 实际修改文件

- `frontend/src/api/endpoints.ts`：新增 `ParseMacro96Response`、`parseMacro96Batch`、`RawMacro96Row`、`RawMacro96RowListResponse`、`listRawMacro96Rows`
- `frontend/src/pages/ImportPipelinePage.tsx`：全面 parser-aware 改造
- `frontend/src/i18n.ts`：新增 Macro96 解析相关中英文 i18n 键
- `frontend/src/styles.css`：新增 `.pipeline-parse-result-card`、`.pipeline-raw-next-step`、`.pipeline-compatible-badge`、`.pipeline-incompatible-badge`
- `backend/app/services/raw_parsing_service.py`：新增 `evaluate_macro96_parse_readiness`
- `backend/app/services/workbench_pipeline_service.py`：`get_batch_pipeline_overview` 改为 parser-aware，Macro96 批次使用 `evaluate_macro96_parse_readiness`

### 前端 parser-aware 逻辑

| parser_key | 显示 | 调用 |
|-----------|------|------|
| `aal3_xml` | "解析 AAL3" | `parseAal3Batch` |
| `macro96_xlsx` | "解析 Macro96" | `parseMacro96Batch` |
| 空/未知 | 禁用 | 不调用任何 parser |

### Macro96 行为

- `parser_key=macro96_xlsx` → 按钮显示"解析 Macro96"
- 调用 `POST /api/import-batches/{batch_id}/parse-macro96`
- 成功后显示结果卡片（`parse_run_id`、`row_count`、`source_file_id`、`parser_key`、`status`）
- 提供"查看 Raw Macro96"入口（跳转 `#/raw-macro96`，携带 session ids）
- Macro96 parsed 后 Candidates 区域提示"尚未实现"

### 按钮启用逻辑（Macro96）

后端 `evaluate_macro96_parse_readiness` 检查：
1. 存在 `macro_region_pool_source` 文件且 `active`
2. 该文件存在 `macro_region_table` intermediate（`artifact_kind=macro_region_table`，`schema=macro_region_table_v1`）
3. 如缺中间态 → `parse_macro96` action `enabled=false`，前端显示禁用原因

### AAL3 是否受影响

**否**，`parser_key=aal3_xml` 仍走原有 `parseAal3` 逻辑，`evaluate_batch_parse_readiness` 不变。

### 是否生成 candidate

**否**

### 是否写入 final_* / kg_*

**否**

### 是否调用 LLM / Agent

**否**

### 测试结果

```
frontend: npm run build — TypeScript 0 errors, Vite build ✓ (495.70 kB JS)
backend pytest tests/: 295 passed, 7 skipped — 无新增失败
```

### 下一步建议

实现 RawMacro96Page：展示 raw_macro96_region_rows 列表（按 parse_run_id 过滤，支持分页）。

---

---

## § Macro96 Event Constraint Fix

**完成时间**：2026-06-15

### 问题根因

`POST /api/import-batches/{batch_id}/parse-macro96` 返回 500：

```
psycopg.errors.CheckViolation
关系 "import_batch_events" 的新列违反了检查约束 "chk_import_batch_events_type"
```

- 服务写入了 `parse_macro96_started`、`parse_macro96_succeeded`，但数据库 CHECK 约束（来自 migration 006）不包含这些值。
- Migration 016 从未被应用：016 的 ALTER TABLE 会丢失 `candidate_generation_*` 和 `rule_validation_*`（已有存量事件），所以无法安全运行。
- `BatchEventType` Python enum 也缺少这三个值。

### 数据库检查结果

| 项目 | 结果 |
|------|------|
| batch_id | `977f8a40-372d-47f3-bf6d-7ba1705eb13b` |
| raw_parse_runs 遗留 | 否（事务已完全回滚） |
| raw_macro96_region_rows 遗留 | 否（表不存在，migration 016 未应用） |
| batch.status | `running`（无部分写入） |
| 清理 SQL 需要 | 否 |

### 新增 migration

`backend/migrations/017_import_batch_events_macro96_types.sql`

内容：
1. `CREATE TABLE IF NOT EXISTS raw_macro96_region_rows`（幂等，016 从未执行）
2. 重建 `chk_import_batch_events_type` 包含所有事件类型（003–006 所有原有值 + 新增 Macro96 3 个）

已手动应用到 dev DB。

### 后端修改

- `backend/app/schemas/import_batch.py`：`BatchEventType` 新增 `parse_macro96_started`、`parse_macro96_succeeded`、`parse_macro96_failed`
- `backend/tests/test_raw_parsing_macro96.py`：新增 3 个测试（enum 包含 Macro96 事件、不丢失旧事件、migration 017 约束覆盖所有 enum 值）

### 验证结果（手动）

```
POST /api/import-batches/977f8a40.../parse-macro96
→ 200 OK
  parse_run_id: 308de9ff-18e7-4d4c-92ec-66c3dda7a870
  row_count: 96
  status: succeeded

import_batches.status = parsed
import_batch_events: parse_macro96_started / parse_macro96_succeeded / status_changed
raw_macro96_region_rows COUNT = 96
```

### 是否生成 candidate / 写 final_* / kg_* / 调 LLM

全部：**否**

### 测试结果

```
backend pytest tests/: 298 passed, 7 skipped — 无新增失败
```

### 下一步建议

实现 RawMacro96Page，展示 raw_macro96_region_rows 列表。

---

## § Macro96 Candidate Generation Foundation

**完成时间**：2026-06-15

### 当前错误原因

用户点击旧 `POST /generate-candidates` 返回 `no raw labels found for parse run`。

- **不是** Excel 中间态问题；**不是** Macro96 parser 未提取脑区。
- 旧 AAL3 candidate generator 只查 `raw_aal3_region_labels`；Macro96 raw 在 `raw_macro96_region_rows` 分表存储。

### 数据库检查结果（batch `0f4b8fbf-…`）

| 项目 | 值 |
|------|-----|
| parser_key | macro96_xlsx |
| status | parsed → candidate_generated（生成后） |
| parse_run | 9b347dad… succeeded, output_count=96 |
| raw_macro96_region_rows | 96 行 |

### 新增 migration

`backend/migrations/018_macro96_candidate_source.sql`

- 移除 `candidate_brain_regions.source_raw_label_id` 对 `raw_aal3_region_labels` 的 FK
- 新增 `source_raw_table` 列（`raw_aal3_region_labels` / `raw_macro96_region_rows`）
- **不自动执行**；已手动应用到 dev DB

### 后端修改

| 文件 | 变更 |
|------|------|
| `backend/app/utils/macro96_laterality.py` | laterality 推断（left/right/bilateral/midline/unknown） |
| `backend/app/services/macro96_candidate_service.py` | `generate_macro96_candidates_for_batch` |
| `backend/app/services/candidate_service.py` | Macro96 batch 调旧接口返回 `WrongCandidateGeneratorForMacro96Error` |
| `backend/app/routers/candidate.py` | `POST /generate-macro96-candidates` |
| `backend/app/models/candidate.py` | 新增 `source_raw_table`，移除 AAL3-only FK |
| `backend/app/schemas/candidate.py` | `GenerateMacro96CandidatesResponse` |
| `backend/app/services/workbench_pipeline_service.py` | parsed + macro96 → `generate_macro96_candidates` action |

### 前端修改

- `endpoints.ts`：`generateMacro96Candidates`
- `ImportPipelinePage.tsx`：Macro96 parsed 显示"生成 Macro96 候选"，结果卡片，查看候选入口
- `i18n.ts`：Macro96 candidate generation 中英文文案

### 手动验证

```
POST .../generate-candidates (Macro96 batch)
→ 400 WRONG_CANDIDATE_GENERATOR_FOR_MACRO96

POST .../generate-macro96-candidates
→ 200 candidate_count=96, batch_status=candidate_generated
```

### 是否自动生成 mapping

**否**

### 是否写入 final_* / kg_* / 调 LLM

全部：**否**

### 测试结果

```
backend pytest tests/: 311 passed, 9 skipped
frontend npm run build: TypeScript 0 errors, Vite build ✓
```

### 下一步建议

Macro96 candidates 生成后，执行 Rule Validation 联调。

---

## Import Pipeline Workspace Layout Foundation

**日期**：2026-06-15  
**任务**：Import Pipeline Workspace Layout and Action Entry Foundation（Step 1）  
**范围**：仅前端布局与操作入口；不执行破坏性回退/删除；不修改后端。

### 目标

将 `#/import-pipeline` 重构为 **批次导航 + 工作区** 布局，补齐状态总览、阶段数据展示、parser-aware 绑定文件兼容性，以及 CRUD / 回退占位入口。

### 页面结构

| 区域 | 说明 |
|------|------|
| 左侧 Batch Navigator | 紧凑卡片：batch_code、status、parser_key、resource 简称、进度占位、created_at；筛选：status / parser / batch code / resource_id |
| Batch Header | 批次摘要：code、短 ID + Copy、status、resource、parser、时间戳、parser 说明 |
| Pipeline Timeline | 8 阶段（Created → Promoted）；完成/当前/未完成；数据计数占位；查看数据链接；回退占位按钮 |
| Action Center | 按 status + parser_key 显示下一步动作（AAL3 / Macro96 分流）；辅助动作：查看 Raw/Candidates、刷新 |
| Data Snapshot | `PipelineDataSnapshot` metric grid：parse run、candidate gen、validation 等 |
| Bound Files | parser-aware 兼容性（Macro96 不再走 AAL3 判断） |
| Events | Timeline / Table 双视图；Macro96 事件中文 i18n |

### Macro96 Bound Files 修复

**问题**：Macro96 xlsx 显示 `可解析：否`，原因 `xlsx file cannot be parsed by aal3_xml`（误用后端 AAL3 字段 `can_parse` / `parser_incompatible_reason`）。

**修复**：`getBatchFileCompatibility(file, parserKey)` — Macro96 走 `getMacro96BoundFileCompatibility`（检查 `macro_region_pool_source`、`intermediate_status=ready`、`macro_region_table`）。

### CRUD / Rollback 入口（本轮仅占位）

| 操作 | 本轮行为 |
|------|----------|
| 刷新 | 真实可用 |
| Queue / Start / Parse / Generate / Validate | 保留原有真实 API 调用 |
| 编辑 / 复制 / 归档 / 删除 | 占位弹窗 → Step 2 |
| 回退预览 / 回退到此步 | 占位弹窗 → Step 3/4 |

### 新增/修改文件

| 文件 | 变更 |
|------|------|
| `frontend/src/pages/ImportPipelinePage.tsx` | 薄包装：BatchNavigator + ImportPipelineWorkspace |
| `frontend/src/pages/importPipeline/BatchNavigator.tsx` | 新建：左侧批次导航 |
| `frontend/src/pages/importPipeline/ImportPipelineWorkspace.tsx` | 新建：右侧 6 区工作区 |
| `frontend/src/utils/importPipelineHelpers.ts` | 新建：parser helpers、timeline、compatibility、snapshot |
| `frontend/src/api/endpoints.ts` | `ParserKey`、`ImportBatchStatus`、`isMacro96Batch`、`isAal3Batch` |
| `frontend/src/i18n.ts` | `pipeline.*` 中英文文案 |
| `frontend/src/styles.css` | `.pipeline-workspace`、sidebar、stage grid、metric grid 等 |

### 是否修改后端 / migration / 删除数据 / 回退 / final_* / kg_* / LLM

全部：**否**

### 测试结果

```
frontend npm run build: TypeScript 0 errors, Vite build ✓
```

### 下一步建议

实现 **Import Pipeline CRUD 基础**（Step 2）：查看、编辑 created/queued batch、归档/取消、删除入口、复制、状态筛选，与 ImportBatchesPage 逻辑复用。

---

## Import Pipeline CRUD Foundation

**日期**：2026-06-15  
**任务**：Import Pipeline CRUD Foundation（Step 2）

### 实现内容

1. **Pipeline 页面批次级 CRUD 管理入口**：创建、编辑、复制、取消、刷新
2. **共享组件**：`CreateBatchModal`、`BatchEditModal`、`BatchFileBindingsEditor`、`BatchCloneDialog`、`BatchSafeDeleteDialog`
3. **后端 clone / attach / detach / update file binding API**
4. **parser-aware 文件绑定校验**：`import_batch_parser_compat.py`
5. **queued 批次修改绑定文件后自动 reset → created**

### 后端新增 API

| API | 说明 |
|-----|------|
| `POST /api/import-batches/{id}/clone` | 复制 batch 配置，status=created，不复制下游数据 |
| `POST /api/import-batches/{id}/files` | attach 单文件 |
| `PATCH /api/import-batches/{id}/files/{file_id}` | 更新 role/sort_order |
| `DELETE /api/import-batches/{id}/files/{file_id}` | detach 绑定 |

已有复用：`PATCH /batch`、`PATCH /files`（全量替换）、`POST /cancel`

### 删除语义

- **非物理删除**：取消 = `status → cancelled`
- **不删除** raw/candidate/validation/review/promotion/final
- **archive/restore 未实现**（DB status CHECK 无 archived）

### 禁止项

- 无 rollback execute
- 无 destructive delete
- 无 final_* / kg_* / LLM

### 测试结果

```
backend pytest tests/: 317 passed, 9 skipped
frontend npm run build: TypeScript 0 errors, Vite build ✓
```

### 下一步建议

实现 **Import Batch rollback-preview 后端**（Step 3）。

---

## Import Batch Rollback Preview Backend Foundation

**日期**：2026-06-15  
**任务**：Import Batch Rollback Preview Backend Foundation（Step 3）

### 新增 API

```
GET /api/import-batches/{batch_id}/rollback-preview?target_status=parsed
```

只读返回 `RollbackPreviewResponse`：`delete_plan`、`keep_plan`、`dependency_counts`、`risk_level`、`required_confirmation`、`warnings`。

### 回退预览规则

- **target_status**：running / parsed / candidate_generated / validated / reviewed
- **不支持**：target=created/queued；current=failed/cancelled/archived/created/queued
- **层级删除**：按 LAYER_RANK 计算 delete vs keep
- **validation_dispatched** 映射为 validated 同级（rank 5）
- **completed** 映射为 promoted 同级（rank 7）

### AAL3 / Macro96

- 所有表按 `batch_id` 计数
- AAL3：`raw_aal3_region_labels`；Macro96：`raw_macro96_region_rows`
- `final_brain_regions` 有 `batch_id`，可可靠 scoped

### 前端轻量接入

- `getImportBatchRollbackPreview` + `RollbackPreviewModal`
- Import Pipeline 回退预览按钮调用 API，仅展示，不执行

### 禁止项

- 无 rollback execute
- 无删除数据
- 无 batch.status 修改
- 无 final_* / kg_* / LLM

### 测试结果

```
backend pytest tests/: 329 passed, 9 skipped
frontend npm run build: ✓
```

### 下一步建议

实现 **Import Batch rollback execute** 强确认接口（Step 4）。

---

## Import Batch Rollback Execute Strong Confirmation

**日期**：2026-06-15  
**任务**：Import Batch Rollback Execute Strong Confirmation（Step 4）

### 新增 API

```
POST /api/import-batches/{batch_id}/rollback
```

请求体 `RollbackExecuteRequest`：`target_status`、`confirmation_text`、`operator`、`reason`、可选 `expected_delete_plan` / `expected_dependency_counts`。

返回 `RollbackExecuteResponse`：`deleted_counts`、`kept_counts`、`batch_status`、`rollback_record_id`、`events_written`。

### 核心规则

- **必须先 preview**：execute 内部调用同一 `build_rollback_preview`，与 GET rollback-preview 共用 delete_plan 计算
- **强确认**：`confirmation_text` 必须严格等于 preview 的 `required_confirmation`；`operator` / `reason` 非空
- **409 stale preview**：`expected_delete_plan` 或 `expected_dependency_counts` 与当前 preview 不一致时拒绝执行
- **事务内删除**：按 FK 安全顺序删除，失败 rollback，不写半删除状态
- **只删当前 batch**：所有 DELETE 限定 `batch_id`；禁止按 `resource_id` 粗暴删除
- **parser-aware raw**：Macro96 删 `raw_macro96_region_rows`；AAL3 删 `raw_aal3_region_labels`（由 delete_plan 层 rank 决定）
- **target → batch.status**：validated/reviewed 映射为 DB 的 `validation_dispatched`（无 reviewed 枚举）

### 删除顺序（下游 → 上游）

1. promotion_records  
2. final_brain_regions  
3. candidate_review_records  
4. candidate_rule_validation_results  
5. rule_validation_runs  
6. candidate_brain_regions  
7. candidate_generation_runs  
8. raw_macro96_region_rows / raw_aal3_region_labels  
9. raw_parse_runs  

不删除：import_batch_files、resource_files、file_intermediate_artifacts、atlas_resources、历史 import_batch_events。

### 审计与事件

- 新表 `import_batch_rollback_records`（migration 019）
- 事件类型 `rollback_started` / `rollback_succeeded` / `rollback_failed`（migration 020）
- 成功写 `rollback_started` + `rollback_succeeded` + `status_changed`
- 失败写 `rollback_failed` audit（独立 commit 尝试）

### 前端

- `RollbackPreviewModal` 升级为 preview + execute 两段式
- 必须输入 confirmation / operator / reason 才启用 danger execute 按钮
- `final_brain_regions > 0` 时红色 danger 区域
- 成功后刷新 batch / events / data snapshot

### 禁止项

- 不删 resource_files / intermediate / atlas_resources
- 不自动 re-parse / generate / validate / review / promote
- 不写 kg_*
- 不调用 LLM

### 测试结果

```
backend pytest tests/: 356 passed, 9 skipped
frontend npm run build: TypeScript 0 errors, Vite build ✓
```

### 需要手动执行的 SQL

```powershell
# 按 .env DATABASE_URL 中的库名替换 neurographiq
psql -U postgres -d neurographiq -f backend/migrations/019_import_batch_rollback_records.sql
psql -U postgres -d neurographiq -f backend/migrations/020_import_batch_events_rollback_types.sql
```

### 下一步建议

完善回退后的重新执行链路，使用户可以从 parsed 重新生成 candidates、重新 validation，并在页面上直观看到新旧 run 的差异。

---

## Import Pipeline Re-execution and Run History Foundation

**日期**：2026-06-15  
**任务**：Import Pipeline Re-execution and Run History Foundation（Step 5）

### 新增 API

```
GET /api/import-batches/{batch_id}/run-history
```

只读返回各阶段 run 历史、rollback records、summary 当前有效产物计数、`current_active` run IDs。

### 幂等逻辑修复（以当前有效数据为准）

- **parse**：succeeded parse run 存在且 raw rows > 0 才阻止重复 parse
- **generate candidates / macro96**：`candidate_brain_regions` count > 0 才 409；rollback 后 count=0 允许重新生成
- **rule validation**：`candidate_rule_validation_results` count > 0 才 409；rollback 删除 results 后重置 candidate 为 `candidate_created` 再 validation
- **Action Center**：`compute_next_allowed_actions` 基于 raw/candidate/validation 当前计数启用/禁用按钮

### Run History active 判断

- raw parse run active：该 run 的 raw_row_count > 0
- candidate generation run active：该 run 的 candidate_count > 0
- validation run active：该 run 的 result_count > 0
- AAL3 用 `raw_aal3_region_labels`；Macro96 用 `raw_macro96_region_rows`

### 前端

- `RunHistoryPanel`：Summary / Raw / Candidate / Validation / Rollback / Events tabs
- inactive run 显示「产物已被回退删除」
- 动作成功后 refresh overview + run history

### 禁止项

- 不恢复已删除 run；不 undo rollback；不自动全链路重跑；不写 kg_*；不调用 LLM

### 是否新增 migration

**否**

### 测试结果

```
backend pytest tests/: 370 passed, 9 skipped
frontend npm run build: TypeScript 0 errors, Vite build ✓
```

### 下一步建议

实现阶段级数据查看与跳转联动，使用户可以从 Pipeline 的 Raw/Candidate/Validation 节点直接打开对应数据列表并带入 batch_id/run_id 筛选。

---

## Import Pipeline Stage-level Data View and Navigation Linking

**日期**：2026-06-15  
**任务**：Import Pipeline Stage-level Data View and Navigation Linking（Step 6）

### 阶段节点数据入口

- Import Pipeline Timeline 每个数据阶段（Parsed / Candidates / Validated / Reviewed / Promoted）增加 **查看数据**、**预览数据（前 10 条）**、**复制 run_id**。
- `StageDataPreviewDrawer` 轻量预览；支持打开完整数据页。
- inactive run 且产物已被 rollback 删除时显示「该阶段产物已被回退删除」，禁用跳转。

### Parser-aware 跳转

| 阶段 | AAL3 | Macro96 |
|------|------|---------|
| Parsed | `#/raw-aal3?batch_id=…&parse_run_id=…` | `#/raw-macro96?batch_id=…&parse_run_id=…` |
| Candidates | `#/candidates?batch_id=…&generation_run_id=…` | 同上 + `source_atlas=Macro96` |
| Validated | `#/rule-validation?batch_id=…&validation_run_id=…` | 同左 |
| Reviewed | `#/human-review?batch_id=…&tab=records` | 同左 |
| Promoted | `#/final-regions?batch_id=…&resource_id=…` | 同左 |

### 新增页面

- **`RawMacro96Page`**（`#/raw-macro96`）：只读列表 `GET /api/raw-parsing/macro96-rows`，支持 batch_id / parse_run_id / resource_id 筛选；与 RawAal3Page 分离。

### URL query + sessionIds 联动

- **URL query 为主**（可分享、刷新不丢筛选）；`sessionStorage`（`ngiq_pipeline_ids`）为辅。
- 目标页面顶部 `PipelineFilterBanner` 显示「已应用来自导入流水线的筛选条件」，提供返回 Pipeline / 清除筛选。
- `useSessionIds` 扩展 `validation_run_id`、`rollback_record_id`。

### 目标页面筛选

- `RawAal3Page`、`RawMacro96Page`、`CandidatesPage`、`RuleValidationPage`、`HumanReviewPage` 自动读取 hash query 并应用筛选。
- `fetchCandidates` 前端支持 `generation_run_id` / `parse_run_id`；新增 `fetchRuleValidationRunResults(validationRunId)` 供预览 drawer 使用。

### Run History 联动

- active run：查看数据带对应 run_id 跳转。
- inactive run + 当前 count=0：显示产物已删除，仅允许预览/查看 rollback 记录语义提示。

### 后端变更

**本轮未修改后端 API**（已有 batch_id / parse_run_id / generation_run_id 筛选满足需求）。

### 禁止项

- 不修改 raw/candidate/validation/review/promotion/final 数据；不执行 rollback；不写 kg_*；不调用 LLM。

### 测试结果

```
backend pytest tests/: 370 passed, 9 skipped
frontend npm run build: TypeScript 0 errors, Vite build ✓
```

### 下一步建议

实现阶段级数据导出和审计报告，使用户可以从 Pipeline 一键导出当前 batch 的 raw/candidate/validation/rollback 摘要。

---

## Files Page Spreadsheet Preview Minimal Fix

**日期**：2026-06-15  
**任务**：Files Page Spreadsheet Preview Minimal Fix

### 问题根因

- `.xlsx` MIME 类型含 `spreadsheetml`/`xml` 字样，后端 `_preview_kind()` 误判为 `xml`，将 zip 二进制按 UTF-8 解码后在「预览」tab 显示 `PK... docProps...` 乱码。
- 前端 `renderPreview()` 无条件渲染 `preview.content` 文本，未对 spreadsheet 做兜底。

### 修复

**后端（最小）**
- `resource_file_service._preview_kind()`：`.xlsx`/`.xls` 加入 binary unsupported；spreadsheet MIME 不再走 xml 分支；仅 `application/xml` / `text/xml` 或 `.xml` 扩展名才视为 xml。

**前端**
- `isBinarySpreadsheetFile` / `shouldRenderTextPreview` / `looksLikeBinaryZipText` 辅助函数。
- spreadsheet「预览」tab 显示可读提示卡片，引导「中间态」或「生成中间态」；保留下载按钮。
- spreadsheet 且 intermediate ready 时默认 active tab 为 `intermediate`。
- `macro_region_table` 中间态 tab 表格化展示 `region_index / en_name / cn_name`（全量 rows，可滚动）。
- Raw JSON tab 剥离二进制 `content`，仅输出 metadata / intermediate JSON。
- `FilesPage.tsx` 已正确 `import { Notice }` — 当前源码无缺失；如浏览器仍报错需 hard refresh。

### 禁止项

- 不改上传/下载/normalization/parse；不写 final_* / kg_*；不调用 LLM。

### 测试结果

```
backend pytest tests/test_resource_files.py::test_preview_xlsx_not_treated_as_xml tests/test_resource_files.py::test_preview_xml_text_file_truncates -q: 2 passed
frontend npm run build: TypeScript 0 errors, Vite build ✓
```

### 下一步建议

继续实现阶段级数据导出和审计报告。

---

## LLM-based Same-granularity KG Completion and Mirror KG Direction

**日期**：2026-06-15  
**任务**：NeuroGraphIQ KG V3 Documentation Expansion for LLM-based Same-granularity Connections, Circuits, Functions, and Mirror-KG Promotion  
**范围**：**仅文档** — 不实现代码、不改数据库、不新增 migration、不调用 LLM API

### 用户明确目标（修正）

NeuroGraphIQ KG V3 **不只是**导入 AAL3 / Macro96 脑区名称，也**不只是** `candidate → final_brain_regions`。最终目标是：

1. 以**同颗粒度脑区**为基础，通过 LLM（DeepSeek 或 Kimi）补全 connections / circuits / functions；
2. 形成结构化 **triple candidates**；
3. LLM 结果先进入 **Mirror KG（正式库镜像层）**，**不能直接写正式库**；
4. 工作台直接展现连接、回路、功能；
5. **人工审核**通过后 promotion 进入正式库 — 物理 PostgreSQL 数据库 **`NeuroGraphIQ_KG_V3`**（非工作台库、非 E2E 测试库）；
6. 全链路可追溯（脑区、资源、批次、候选、LLM run、prompt、模型、人审）。

### 正式库物理拓扑（用户确认，2026-06-15）

**正式库 = DBeaver 中的 PostgreSQL 数据库 `NeuroGraphIQ_KG_V3`**，按 schema 分粒度：

| Schema | 粒度族 |
|--------|--------|
| `macro_clinical` | 宏观临床（AAL3、Macro96） |
| `meso_anatomical` | 中观解剖 |
| `sub_connectivity` | 亚区连接 |
| `fine_cyto` | 细胞构筑 |
| `molecular_attr` | 分子属性 |
| `public` | 公共 |

工作台 / 测试库（`neurographiq_kg_v3_mvp1_e2e`、`neurographiq_kg_v3_wb` 等）用于 candidate / Mirror KG / 人审流水线；Promotion 目标库为 **`NeuroGraphIQ_KG_V3`**。MVP 1 在 E2E 库内的 `final_brain_regions` 为开发期同库实现，与上述正式库拓扑应对齐。

### 当前实现 vs 目标

| 能力 | 当前 | 目标 |
|------|------|------|
| LLM 页面定位 | 候选侧脑区字段补全（`candidate_llm_extractions`） | 同颗粒度知识补全工作台 |
| Connection / Circuit / Function | 未实现 | Mirror KG + 工作台 tab |
| Mirror KG 表 | 未 migration | `mirror_region_*`, `mirror_kg_triples` 等（见设计文档） |
| Triple promotion | 未实现 | mirror → final_kg_triples |
| Final regions | ✅ MVP 1 已实现 | 扩展至 connection/circuit/function |

### 新增文档

| 文档 | 内容 |
|------|------|
| `docs/NEUROGRAPHIQ_KG_V3_TARGET_ARCHITECTURE.md` | 七层架构、治理链路、MVP 路线图、术语 |
| `docs/LLM_SAME_GRANULARITY_COMPLETION_DESIGN.md` | LLM 任务类型、JSON schema、三类核心补全、工作台 |
| `docs/MIRROR_KG_AND_FINAL_PROMOTION_DESIGN.md` | Mirror KG 定义、状态机、晋升、表规划 |
| `docs/TRIPLE_MODEL_AND_ONTOLOGY_DESIGN.md` | 三元组模型、谓词、不确定性、导出 |

### 核心原则（摘要）

1. **LLM 不是正式库写入者** — 不写 final_*，不 auto approve / promote。
2. **同颗粒度优先** — Macro96↔Macro96；跨颗粒度走 Explicit Mapping。
3. **连接 / 回路 / 功能是独立知识层** — 不塞进 brain region 字段。
4. **Mirror KG 是正式库前置层** — llm_suggested → rule_checked → human_review → promoted_to_final。
5. **人工审核是进入正式库的唯一门槛**（mirror 知识对象）。
6. **全事实可追溯** — resource / batch / candidate / llm_run / prompt / reviewer / promotion。

### 数据边界图

```mermaid
flowchart LR
    Resource[Brain Atlas / Region Resource]
    Raw[Raw Parsing]
    Candidate[Region Candidate]
    LLM[LLM Same-granularity Completion]
    Mirror[Mirror KG]
    Rule[Rule Validation]
    Review[Human Review]
    Promote[Promotion]
    Final[Final NeuroGraphIQ_KG_V3]

    Resource --> Raw
    Raw --> Candidate
    Candidate --> LLM
    LLM --> Mirror
    Mirror --> Rule
    Rule --> Review
    Review --> Promote
    Promote --> Final
```

### 推荐开发顺序（Phase A–I）

- **Phase A**（本轮）：文档与 schema 设计 ✅
- **Phase B**：LLM Provider Abstraction（DeepSeek / Kimi）
- **Phase C**：Mirror KG Schema migration
- **Phase D**：Same-granularity Completion API
- **Phase E**：Workbench UI（Region / Connections / Circuits / Functions / Triples / Mirror Review Queue）
- **Phase F–I**：Rule Validation → Human Review → Promotion → Visualization/Query

### 禁止项（本轮）

- 不改代码 / 数据库 / migration
- 不写 final_* / kg_*
- 不调用 LLM

### 下一步建议

Phase B：实现 LLM Provider Abstraction（DeepSeek + Kimi 统一 task contract + run record）。

---

## LLM Extraction Infrastructure Foundation（Step 1 · 2026-06-15）

### 完成内容

1. **LLM Provider 抽象**：`backend/app/services/llm_providers/` — `LlmProvider` Protocol、`DeepSeekProvider`、`KimiProvider`、`get_llm_provider()` factory。
2. **DeepSeek Provider**：从 Settings runtime 读取 api_key / base_url / model / temperature / max_tokens；OpenAI-compatible chat completions；JSON 输出解析；日志不输出 api key。
3. **Kimi Provider 框架**：同接口；OpenAI-compatible；未配置时返回明确错误。
4. **Migration 021**（未自动执行）：`llm_prompt_templates`、`llm_extraction_runs`、`llm_extraction_items` + 索引。
5. **ORM / Schema**：`LlmPromptTemplate`、`LlmExtractionRun`、`LlmExtractionItem`；任务类型枚举 `LlmTaskType`；run/item 状态枚举。
6. **Region field completion 接入新 run/item**：`POST /api/llm-extraction/region-field-completion`；成功 item 同步写 legacy `candidate_llm_extractions`（旧页面兼容）。
7. **新 API**：
   - `GET /api/llm-extraction/providers`
   - `GET /api/llm-extraction/task-types`
   - `GET /api/llm-extraction/runs`、`GET /api/llm-extraction/runs/{run_id}`
   - `GET /api/llm-extraction/items`
   - `POST /api/llm-extraction/run-task`（未实现 task 返回 501）
8. **前端 LLM Extraction 页**：Tabs — Region 补全 / Runs / Items + Connections/Functions/Circuits/Triples 规划占位；Provider 选择、dry_run、Runs/Items 表格。
9. **Settings**：Kimi runtime 配置字段（api_key / base_url / model / temperature / max_tokens）；providers API 仅返回 configured，不返回 key。

### 仍为 planned（本轮未实现）

- `same_granularity_connection_completion`
- `same_granularity_function_completion`
- `same_granularity_circuit_completion`
- `triple_candidate_generation`
- Mirror KG 表写入
- final_* / kg_* 写入
- 自动 approve / promote / human review

### 数据边界（本轮）

- LLM 输出 → `llm_extraction_runs` + `llm_extraction_items`（+ legacy `candidate_llm_extractions` for region_field_completion）
- **不写** Mirror KG
- **不写** final_* / kg_*

### 测试

- `backend/tests/test_llm_extraction_infrastructure.py`：providers / task-types / dry_run / mock provider / JSON fence 解析 / 未配置 provider 400 等
- 全量 pytest：**384 passed**, 9 skipped
- 前端 `npm run build`：成功（TypeScript 0 错误）

### 版本

- Backend：`3.4.0-mvp2-llm-infrastructure`

### 下一步建议

**Step 2 — Mirror KG Schema Foundation**：新增 `mirror_region_connections`、`mirror_region_circuits`、`mirror_region_functions`、`mirror_kg_triples`、`mirror_evidence_records` 等镜像层表，为 connection/function/circuit/triple 的 LLM 输出建立正式库前置层。

---

## Mirror KG Schema Foundation（Step 2 · 2026-06-15）

### 完成内容

1. **Migration 022**（已手动执行于 `neurographiq_kg_v3_mvp1_e2e`）：`mirror_region_connections`、`mirror_region_functions`、`mirror_region_circuits`、`mirror_circuit_regions`、`mirror_kg_triples`、`mirror_evidence_records` + 索引。
2. **ORM**：`backend/app/models/mirror_kg.py`
3. **Schemas**：`backend/app/schemas/mirror_kg.py` — 状态/类型枚举、Create/Read/List；Create 禁止 `promotion_status=promoted`；confidence 0–1。
4. **Services**：
   - `mirror_kg_service.py` — create/list/get；同颗粒度 connection 校验
   - `llm_to_mirror_service.py` — `create_mirror_*_from_llm_item`（不自动触发）
5. **API** `/api/mirror-kg/*` — connections / functions / circuits / triples / evidence 的 GET list、GET detail、POST create
6. **前端**：LLM Extraction 页 Connections/Functions/Circuits/Triples tabs 升级为 Mirror KG 只读列表 + 筛选 + “不是 final fact” 警告
7. **LLM 溯源**：mirror 表 `llm_run_id` / `llm_item_id` FK，`ON DELETE SET NULL`

### 本轮未实现

- 真实 LLM connection/function/circuit/triple 提取
- Human Review / Promotion
- final_* / kg_* 写入
- 自动从所有 LLM items 批量生成 mirror

### 测试

- `backend/tests/test_mirror_kg_schema.py` — schema 默认值、confidence 校验、llm_item 转换、FK SET NULL 等
- 全量 pytest：**403 passed**, 9 skipped
- 前端 `npm run build`：成功

### 版本

- Backend：`3.5.0-mvp2-mirror-kg-schema`

### 下一步建议

**Step 3 — Same-granularity Connection Extraction**：实现 DeepSeek/Kimi 同颗粒度 connection 补全，将 LLM item 结构化写入 `mirror_region_connections` 与 `mirror_kg_triples`。

---

## Same-granularity Connection Extraction to Mirror KG（Step 3 · 2026-06-15）

### 完成内容

1. **任务类型**：`same_granularity_connection_completion` 标记为 implemented
2. **API**：`POST /api/llm-extraction/same-granularity-connections`
3. **Service**：`backend/app/services/llm_connection_extraction_service.py`
   - 同 source_atlas / granularity 校验
   - `all_pairs` / `region_centered` pair 策略
   - `max_candidate_pairs` 上限（默认 200）
   - Prompt template `same_granularity_connection_completion_v1`
   - JSON 解析 + normalize
   - 1 run + 1 item  per extraction
4. **Mirror KG 写入**（可选 flags）：
   - `mirror_region_connections`（去重：undirected A-B/B-A）
   - `mirror_kg_triples`（predicate 由 connection_type 映射）
   - `mirror_evidence_records`（evidence_text 非空时）
5. **默认状态**：`mirror_status=llm_suggested`，`review_status=pending`，`promotion_status=not_promoted`
6. **前端**：Connections tab 支持候选选择、pair 策略、dry_run、执行与 Mirror 列表刷新
7. **`/run-task`**：connection task 路由到新 API

### 不做

- function / circuit extraction
- human review / promotion
- final_* / kg_*

### 测试

- `backend/tests/test_llm_connection_extraction.py`
- 全量 pytest：**416 passed**, 9 skipped
- 前端 build：成功

### 版本

- Backend：`3.6.0-mvp2-connection-extraction`

### 下一步建议

**Step 4 — Same-granularity Function Extraction**：将脑区功能候选写入 `mirror_region_functions` 并生成 function triples。

---

## Same-granularity Function Extraction to Mirror KG（Step 4 · 2026-06-15）

### 完成内容

1. **任务类型**：`same_granularity_function_completion` 标记为 implemented
2. **API**：`POST /api/llm-extraction/same-granularity-functions`
3. **Service**：`backend/app/services/llm_function_extraction_service.py`
   - 同 source_atlas / granularity 校验（1–30 候选）
   - region-centered：每脑区最多 `max_functions_per_region`（默认 5）
   - Prompt template `same_granularity_function_completion_v1`
   - JSON 解析 + normalize（非法 category/relation → unknown；空 function_term / 未知 candidate 跳过）
   - 1 run + 1 item per extraction
4. **Mirror KG 写入**（可选 flags）：
   - `mirror_region_functions`（去重：region + normalized function_term + category + relation_type）
   - `mirror_kg_triples`（predicate 由 relation_type 映射）
   - `mirror_evidence_records`（evidence_text 非空时）
5. **默认状态**：`mirror_status=llm_suggested`，`review_status=pending`，`promotion_status=not_promoted`
6. **前端**：Functions tab 支持候选选择、category/relation 多选、dry_run、执行与 Mirror 列表刷新
7. **`/run-task`**：function task 路由到新 API

### 不做

- circuit extraction
- human review / promotion
- final_* / kg_*

### 测试

- `backend/tests/test_llm_function_extraction.py`
- 全量 pytest：**432 passed**, 9 skipped
- 前端 build：成功

### 版本

- Backend：`3.7.0-mvp2-function-extraction`

### 下一步建议

**Step 5 — Same-granularity Circuit Extraction**：将连接与功能上下文整合为 `mirror_region_circuits`、`mirror_circuit_regions` 与 circuit triples。

---

## Same-granularity Circuit Extraction to Mirror KG（Step 5 · 2026-06-15）

### 完成内容

1. **任务类型**：`same_granularity_circuit_completion` 标记为 implemented
2. **API**：`POST /api/llm-extraction/same-granularity-circuits`
3. **Service**：`backend/app/services/llm_circuit_extraction_service.py`
   - 同 source_atlas / granularity 校验（2–50 候选）
   - 可选 mirror connections / functions 作为 context（同 scope 自动加载或显式 ID）
   - `max_circuits` / `min_regions_per_circuit` / `max_regions_per_circuit`
   - Prompt template `same_granularity_circuit_completion_v1`
   - JSON 解析 + normalize；非法 region 跳过；不足 min 跳过 circuit
   - 1 run + 1 item per extraction
4. **Mirror KG 写入**（可选 flags）：
   - `mirror_region_circuits` + `mirror_circuit_regions`
   - `mirror_kg_triples`（has_participant_region + associated_with_function）
   - `mirror_evidence_records`（evidence_text 非空时）
5. **默认状态**：`mirror_status=llm_suggested`，`review_status=pending`，`promotion_status=not_promoted`
6. **前端**：Circuits tab 完整 workbench；context 计数；involved regions 展开
7. **`/run-task`**：circuit task 路由到新 API

### 不做

- human review / promotion
- final_* / kg_*
- Triple Candidate Generation Consolidation（下一步）

### 测试

- `backend/tests/test_llm_circuit_extraction.py`
- 全量 pytest：**449 passed**, 9 skipped
- 前端 build：成功

### 版本

- Backend：`3.8.0-mvp2-circuit-extraction`

### 下一步建议

**Triple Candidate Generation Consolidation**：将 connection/function/circuit mirror candidates 统一整理为可审核 triple 队列。

---

## Triple Candidate Generation Consolidation（Step 6）

**日期**：2026-06-15  
**版本**：`3.9.0-mvp2-triple-consolidation`

### 目标

从 Mirror connections / functions / circuits 确定性生成或补齐 `mirror_kg_triples` 三元组候选，统一去重与筛选，为后续 Triple Review Queue 和 Promotion 做准备。

### 实现要点

1. **确定性 triple consolidation service**（`backend/app/services/triple_consolidation_service.py`）
   - 从 `mirror_region_connections` 生成 connection triples
   - 从 `mirror_region_functions` 生成 function triples
   - 从 `mirror_region_circuits` + `mirror_circuit_regions` 生成 circuit triples
   - 支持按 batch / resource / source_atlas / granularity / mirror_status / review_status 筛选
   - 支持 `dry_run` 预览（不写数据库）
   - 支持 canonical key 去重（DB 已存在 + session 内重复均跳过）
   - 支持重新补齐缺失 triples

2. **API**：`POST /api/mirror-kg/triples/consolidate`
   - 请求：`MirrorTripleConsolidationRequest`（source_types、scope、filters、dry_run、limit 等）
   - 响应：`MirrorTripleConsolidationResponse`（source_counts、planned/created/skipped counts、triples_preview、warnings）

3. **Triple 规则**
   - Connection：`connection_type` → predicate 映射；`bidirectional` → `bidirectionally_connects_to`
   - Function：`relation_type` → predicate 映射；object 为 `function_term`
   - Circuit：`has_participant_region`（circuit → region）；`associated_with_function`（circuit → function_association）

4. **前端 Triples tab** 升级为 Triple Consolidation Workbench
   - source_types 多选、scope 筛选、dry_run / include_existing / limit
   - 预览三元组 / 生成补齐三元组（写操作需确认）
   - 结果卡片 + preview 表 + triples 表刷新

### 边界（严格执行）

- **不调用 LLM**（DeepSeek / Kimi / 任何 provider）
- **不写** `final_*` / `kg_*`
- **不自动 approve / promote / human review**
- **仅写** `mirror_kg_triples`
- **不新增 migration**（复用 022 mirror_kg schema）

### 测试

- `backend/tests/test_triple_consolidation.py`
- 全量 pytest：**466 passed**, 9 skipped
- 前端 build：成功

### 版本

- Backend：`3.9.0-mvp2-triple-consolidation`

### 下一步建议

**Mirror KG Rule Validation**：对 connections / functions / circuits / triples 进行确定性规则校验并生成 validation results。

---

## Mirror KG Rule Validation（Step 7）

**日期**：2026-06-15  
**版本**：`4.0.0-mvp2-mirror-rule-validation`

### 目标

对 Mirror KG 中的 connections / functions / circuits / triples 进行确定性规则校验，写入 validation runs/results，可选将通过校验的对象标记为 `rule_checked`。

### 实现要点

1. **Migration**：`backend/migrations/023_mirror_kg_rule_validation.sql`
   - `mirror_rule_validation_runs`
   - `mirror_rule_validation_results`

2. **Service**：`backend/app/services/mirror_rule_validation_service.py`
   - 通用规则 + connection/function/circuit/triple 专用规则
   - dry_run / apply_status_update
   - 去重检测（connection/function/circuit/triple duplicate warnings）

3. **API**（`/api/mirror-kg/validation`）
   - `POST /run`
   - `GET /runs`、`GET /runs/{run_id}`
   - `GET /results`

4. **前端**：LlmExtractionPage 新增 Mirror Validation tab

### 边界

- **不调用 LLM**
- **不写** `final_*` / `kg_*`
- **rule_checked ≠ human approved**
- **不自动 review / promote**
- **Migration 不自动执行**

### 测试

- `backend/tests/test_mirror_rule_validation.py`
- 全量 pytest：**495 passed**, 9 skipped
- 前端 build：成功

### 版本

- Backend：`4.0.0-mvp2-mirror-rule-validation`

### 下一步建议

**Mirror KG Human Review Queue**：对 rule_checked 且无 blocker 的对象进行人工审核。

---

## Mirror KG Human Review Queue（Step 8）

**日期**：2026-06-15  
**版本**：`4.1.0-mvp2-mirror-human-review`

### 目标

对 Mirror KG connections / functions / circuits / triples 提供人工审核队列，支持 approve / reject / needs_revision / edit / comment，保留完整 review record。

### 实现要点

1. **Migration**：`backend/migrations/024_mirror_kg_human_review.sql` — `mirror_human_review_records`
2. **Service**：`backend/app/services/mirror_review_service.py`
   - 审核队列（默认 rule_checked + pending/needs_revision）
   - validation gating（无 validation / blocker 不可 approve）
   - 白名单字段 edit
   - approve → human_approved + approved；reject → human_rejected + blocked；edit → needs_revision
3. **API**（`/api/mirror-kg/review`）：queue / detail / action / records
4. **前端**：LlmExtractionPage Mirror Review tab

### 边界

- **不调用 LLM**；**不写 final_* / kg_***
- **approve ≠ promotion**；**human_approved ≠ final fact**
- **Migration 不自动执行**

### 测试

- `backend/tests/test_mirror_review_queue.py`
- 全量 pytest：**513 passed**, 9 skipped
- 前端 build：成功

### 版本

- Backend：`4.1.0-mvp2-mirror-human-review`

### 下一步建议

**Mirror KG Promotion to Final KG**：将 human_approved 对象晋升到 final_* 正式表。

---

## Mirror KG Promotion to Final KG（Step 9）

**日期**：2026-06-15  
**版本**：`4.2.0-mvp2-mirror-promotion`

### 目标

将 human_approved + review_status=approved 且无 blocker/error 的 Mirror KG 对象，经强确认 promotion 写入当前工作库 `final_*` 表，并保留完整 promotion audit。

### 新增表（Migration `025_mirror_kg_promotion_to_final.sql`，**不自动执行**）

- `final_region_connections`
- `final_region_functions`
- `final_region_circuits`
- `final_circuit_regions`
- `final_kg_triples`
- `final_evidence_records`
- `mirror_promotion_runs`
- `mirror_promotion_records`

（复用已有 `final_brain_regions` / candidate `promotion_records`，本轮不扩展其 scope。）

### 实现要点

1. **Service**：`backend/app/services/mirror_promotion_service.py`
   - eligibility：human_approved + approved + not_promoted + approve review record + no blocker/error
   - dry_run preview + 强确认 `PROMOTE MIRROR KG TO FINAL: {types} COUNT {n}`
   - final duplicate detection（connection/function/circuit/triple）
   - promote + evidence + mirror source 状态更新 + audit
2. **API**
   - `/api/mirror-kg/promotion/preview|run|runs|records`
   - `/api/final-kg/connections|functions|circuits|triples|evidence`（只读）
3. **前端**：LlmExtractionPage **Mirror Promotion** tab

### 边界

- **不调用 LLM**；**不写 kg_***；**不对接外部物理正式库 NeuroGraphIQ_KG_V3**
- **human_approved ≠ final** — 必须经 promotion 强确认
- **warning 不阻止 promotion**（但 UI 显示）
- **Migration 不自动执行**

### 测试

- `backend/tests/test_mirror_promotion_to_final.py`
- 全量 pytest：**536 passed**, 9 skipped
- 前端 build：成功

### 版本

- Backend：`4.2.0-mvp2-mirror-promotion`

### 下一步建议

**Final KG Browser and Export**：集中浏览 final connections/functions/circuits/triples，并支持 JSONL/CSV 导出，作为后续同步到物理正式库 NeuroGraphIQ_KG_V3 的输入。

---

## Formal Macro Clinical Schema Alignment and Prompt Template Foundation（Step 8.5）

**日期**：2026-06-15  
**版本**：`4.2.1-mvp2-macro-clinical-schema-alignment`

### 背景

用户正式库 `NeuroGraphIQ_KG_V3.macro_clinical` 包含：region、region_function、circuit、circuit_step、circuit_function、projection、projection_function。当前 MVP 为并列式 region→connection/function/circuit，与正式库 **region→circuit→circuit_step→projection→function** 链路不一致。

### 本轮完成

1. 新增 `docs/FORMAL_MACRO_CLINICAL_SCHEMA_ALIGNMENT.md` — Mirror KG ↔ macro_clinical 映射、缺失对象、推荐 extraction 顺序、暂缓 promotion 原因
2. 新增 `docs/LLM_PROMPT_TEMPLATES_MACRO_CLINICAL.md` — 8 个 planned prompt 完整设计
3. `llm_prompt_defaults.py` — 8 个 template 常量（含 `output_schema_json`）
4. `llm_extraction.py` — 8 个 planned task types（`implemented=false`）
5. 前端 LLM Extraction 页 — macro_clinical 对齐说明卡片 + tab 映射提示

### 映射要点

- `mirror_region_connections` → **projection**
- `mirror_region_functions` → **region_function**
- `mirror_region_circuits` → **circuit**
- `mirror_circuit_regions` → **circuit_step 早期形式（不完整）**
- 缺失：**circuit_step**、**projection_function**

### 边界

- **不调用 LLM**；**不写 Mirror KG**；**不写 final_* / kg_***
- **不新增 extraction API**；**不继续 promotion**
- **不新增 migration**

### 测试

- 全量 pytest：**536+ passed**（含 planned task type 501 测试）
- 前端 build：成功

### 下一步建议

**Mirror Circuit Step, Projection Function, and Circuit-Projection Membership Schema Foundation** — 补齐 `mirror_circuit_steps`、`mirror_projection_functions`，并将 `mirror_region_connections` 明确对齐为 projection 语义。

---

## Circuit-Projection Bidirectional Extraction and Dual-Model Verification Design（Step 8.5b）

**日期**：2026-06-15  
**版本**：`4.2.2-mvp2-circuit-projection-bidirectional-design`

### 背景

用户进一步明确正式库逻辑：系统不仅要从脑区提取回路，也必须提取**连接/投射与回路之间的包含关系**。正式推理链路应是双向的：

- **方向 A**：region → circuit → circuit_step → projection → projection belongs_to circuit → function
- **方向 B**：projection graph → circuit candidate → circuit contains projection → step order verification

正式库 `macro_clinical` 表结构包括：region、region_function、circuit、circuit_step、circuit_function、projection、projection_function，以及推荐的 **circuit_projection_membership**。

### 本轮完成

1. 新增 `docs/CIRCUIT_PROJECTION_BIDIRECTIONAL_EXTRACTION_DESIGN.md` — 双向提取、交叉验证、双模型验证、confidence 合成、Mirror→validation→review→promotion 门禁
2. 更新 `docs/FORMAL_MACRO_CLINICAL_SCHEMA_ALIGNMENT.md` — 补充 circuit_projection_membership、双向流程、缺失 Mirror 表
3. 更新 `docs/LLM_PROMPT_TEMPLATES_MACRO_CLINICAL.md` — **11** 个 planned prompt（含 projections_to_circuits、cross_validation、dual_model）
4. `llm_prompt_defaults.py` — 11 个 template 常量（含 membership、双模型 schema）
5. `llm_extraction.py` — 11 个 planned task types（`implemented=false`）
6. 前端 LLM Extraction 页 — 双向提取 + 双模型 + 规划 Mirror 表说明卡片

### 映射要点

- `mirror_region_connections` → **projection**
- `mirror_circuit_regions` → **circuit_step 早期形式（不完整）**
- 缺失：**circuit_step**、**projection_function**、**circuit_projection_membership**、**dual_model_verification**
- DeepSeek/Kimi 当前仅为 **provider**，非双模型一致性审核层

### 边界

- **不调用 LLM**；**不写 Mirror KG**；**不写 final_* / kg_***
- **不新增 extraction API**；**不继续 promotion**
- **不新增 migration**

### 测试

- 全量 pytest（含 11 planned task type 501 测试）
- 前端 build：成功

### 下一步建议

**Mirror Circuit Step, Projection Function, Circuit-Projection Membership, and Dual-Model Verification Schema Foundation** — 实现 `mirror_circuit_steps`、`mirror_projection_functions`、`mirror_circuit_projection_memberships`、`mirror_dual_model_verification_results` 表（migration 026+）。

---

## Mirror Circuit Step, Projection Function, Circuit-Projection Membership, and Dual-Model Verification Schema Foundation（Step 8.6）

**日期**：2026-06-15  
**版本**：`4.2.3-mvp2-mirror-macro-clinical-schema-foundation`

### 本轮完成

1. 新增 migration `026_mirror_macro_clinical_alignment_schema.sql`（**未自动执行**）
2. 新增 5 张 Mirror 表：`mirror_circuit_steps`、`mirror_projection_functions`、`mirror_circuit_projection_memberships`、`mirror_dual_model_verification_runs`、`mirror_dual_model_verification_results`
3. 新增 `mirror_macro_clinical.py` models / schemas / service / router
4. 基础 list/create/get API（`/api/mirror-kg/circuit-steps` 等）
5. 前端 LLM Extraction 页新增 **Macro Clinical Schema** tab + schema readiness 说明卡片
6. `mirror_region_connections` 在 migration COMMENT 与文档中明确为 **projection** 语义（表名不变）

### 边界

- **不实现**真实 circuit_to_steps / projection_to_functions / dual_model extraction API
- **不调用 LLM**；**不写 final_* / kg_***；**不 promotion**；**不 auto approve/review**
- POST 仅为基础 schema foundation 创建能力

### 测试

- backend pytest（含 `test_mirror_macro_clinical_schema.py`）
- frontend build

### 下一步建议

**实现 Circuit-to-Steps Extraction** — 将 `regions_to_circuits` 生成的 `mirror_region_circuits` 拆解为 `mirror_circuit_steps`（same-granularity、mirror-only、no final）。

---

## Circuit-to-Steps Extraction to Mirror Circuit Steps（Step 8.7）

**日期**：2026-06-15  
**版本**：`4.2.4-mvp2-circuit-to-steps-extraction`

### 本轮完成

1. 实现 **circuit_to_steps** 真实 extraction API：`POST /api/llm-extraction/circuit-to-steps`
2. 输入：`mirror_region_circuits`（必填 `circuit_id`）；可选 `mirror_circuit_regions` 作为 involved regions 上下文
3. 使用 DeepSeek / Kimi + `circuit_to_steps_v1` prompt 拆解 ordered steps
4. LLM 原始输出写入 `llm_extraction_runs` / `llm_extraction_items`（raw / parsed / normalized JSON）
5. 结构化 step 写入 `mirror_circuit_steps`（`create_mirror_records=true` 时）
6. 支持 `dry_run` prompt preview；支持 `max_steps`、duplicate step_order 跳过
7. `/api/llm-extraction/run-task` 分派 `circuit_to_steps`（`implemented=true`）
8. 前端 Macro Clinical Schema tab 新增 **Circuit-to-Steps Workbench**
9. 测试 mock provider；修复 settings/provider 测试不依赖本地 `.env` API key

### 边界

- **不写** `final_*` / `kg_*`；**不** auto approve / review / promote
- **不实现** circuit_steps_to_projections / projections_to_circuits / dual_model_verification 真实执行
- **不生成** projection / projection_function / membership
- 复用 migration 026 `mirror_circuit_steps` 表（**未新增 migration**）

### 测试

- backend pytest 全量（含 `test_llm_circuit_step_extraction.py`）
- frontend build

### 下一步建议

**实现 Circuit-Steps-to-Projections Extraction** — 将 `mirror_circuit_steps` 转换为 `mirror_region_connections`（projection）并写入 `mirror_circuit_projection_memberships`。

---

## Circuit-Steps-to-Projections Extraction to Mirror Projections and Memberships（Step 8.8）

**日期**：2026-06-15  
**版本**：`4.2.5-mvp2-circuit-steps-to-projections-extraction`

### 本轮完成

1. 实现 **circuit_steps_to_projections** 真实 extraction API：`POST /api/llm-extraction/circuit-steps-to-projections`
2. 输入：`mirror_region_circuits` + `mirror_circuit_steps`（可选 `step_ids` 过滤）
3. 使用 DeepSeek / Kimi + `circuit_steps_to_projections_v1` prompt 生成 projection + membership
4. projection 写入 `mirror_region_connections`（`macro_clinical_semantic_type=projection` 写入 normalized_payload_json）
5. membership 写入 `mirror_circuit_projection_memberships`（`source_method=circuit_to_projection`，`verification_status=circuit_supported`）
6. 可选生成 projection triples（4 条/projection）与 projection evidence
7. LLM 输出写入 `llm_extraction_runs` / `llm_extraction_items`
8. 支持 dry_run、duplicate projection 复用、membership 去重
9. `/run-task` 分派 `circuit_steps_to_projections`（`implemented=true`）
10. 前端 Macro Clinical Schema tab 新增 **Circuit-Steps-to-Projections Workbench**

### 边界

- **不写** `final_*` / `kg_*`；**不** auto approve / review / promote
- **不实现** projection_to_functions / projections_to_circuits / dual_model_verification
- 复用 migration 026 表（**未新增 migration**）

### 测试

- backend pytest 599 passed（含 `test_llm_circuit_projection_extraction.py`）
- frontend build

### 下一步建议

**实现 Projections-to-Circuits Reverse Extraction** — 将 projection graph 反向推断 circuit candidates，并与已有 circuit/membership 形成交叉验证基础。

---

## Projection-to-Functions Extraction to Mirror Projection Functions（Step 8.9）

**日期**：2026-06-15  
**版本**：`4.2.6-mvp2-projection-to-functions-extraction`

### 本轮完成

1. 实现 **projection_to_functions** 真实 extraction API：`POST /api/llm-extraction/projection-to-functions`
2. 输入：`mirror_region_connections`（projection 语义）；可选 circuit membership 与 source/target region 上下文
3. 使用 DeepSeek / Kimi + `projection_to_functions_v1` prompt 生成 projection_function
4. 结构化输出写入 `mirror_projection_functions`（`macro_clinical_semantic_type=projection_function`）
5. LLM 原始/解析/归一化输出写入 `llm_extraction_runs` / `llm_extraction_items`
6. 支持 dry_run、同 atlas/同 granularity 校验、duplicate projection_function 跳过
7. 可选生成 projection_function triples（connection → function）与 evidence（schema 不支持独立 target 时仅存 object + warning）
8. `/run-task` 分派 `projection_to_functions`（`implemented=true`）
9. 前端 Macro Clinical Schema tab 新增 **Projection-to-Functions Workbench**
10. 测试 mock provider，不调用真实 DeepSeek/Kimi

### 边界

- **不写** `final_*` / `kg_*`；**不** auto approve / review / promote
- **不实现** projections_to_circuits / circuit_projection_cross_validation / dual_model_verification
- 复用 migration 026 表（**未新增 migration**）

### 测试

- backend pytest 全量（含 `test_llm_projection_function_extraction.py`）
- frontend build

### 下一步建议

**实现 Projections-to-Circuits Reverse Extraction** — 将 projection graph 反向推断 circuit candidates，并与已有 circuit/membership 形成交叉验证基础。

---

## Projections-to-Circuits Reverse Extraction to Mirror Circuits and Memberships（Step 8.10）

**日期**：2026-06-15  
**版本**：`4.2.7-mvp2-projections-to-circuits-extraction`

### 本轮完成

1. 实现 **projections_to_circuits** 真实 extraction API：`POST /api/llm-extraction/projections-to-circuits`
2. 输入：`mirror_region_connections`（projection graph）；`projection_ids` 2–100，必须同 source_atlas、同 granularity
3. 使用 DeepSeek / Kimi + `projections_to_circuits_v1` prompt 反向推断 circuit candidates
4. inferred circuit 写入 `mirror_region_circuits`（`source_method=projection_to_circuit` 写入 normalized_payload_json）
5. 可选写入 `mirror_circuit_steps`（possible step order）
6. supporting projection 与 circuit 关系写入 `mirror_circuit_projection_memberships`（`source_method=projection_to_circuit`，`verification_status=projection_supported`）
7. LLM 原始/解析/归一化输出写入 `llm_extraction_runs` / `llm_extraction_items`
8. 支持 dry_run、include/reuse existing circuits、duplicate circuit/step/membership 跳过
9. 可选生成 circuit / membership 相关 mirror_kg_triples 与 mirror_evidence_records（membership evidence 不支持独立 target 时 warning）
10. `/run-task` 分派 `projections_to_circuits`（`implemented=true`）
11. 前端 Macro Clinical Schema tab 新增 **Projections-to-Circuits Workbench**（projection graph 多选、graph preview、dry_run、结果卡片）
12. 测试 mock provider，不调用真实 DeepSeek/Kimi

### 边界

- **不写** `final_*` / `kg_*`；**不** auto approve / review / promote
- **不实现** circuit_projection_cross_validation / dual_model_verification
- 复用 migration 026 表（**未新增 migration**）

### 测试

- backend pytest 全量（含 `test_llm_projection_circuit_extraction.py`）
- frontend build

### 下一步建议

**实现 Circuit-Projection Cross Validation** — 对 circuit_to_projection 与 projection_to_circuit 两条链路生成的 memberships 进行确定性交叉验证，输出 `bidirectionally_supported` / `conflict` / `insufficient_evidence`。

---

## Circuit-Projection Cross Validation（Step 8.11）

**日期**：2026-06-15  
**版本**：`4.2.8-mvp2-circuit-projection-cross-validation`

### 本轮完成

1. 新增 migration **027**：`mirror_circuit_projection_cross_validation_runs` / `mirror_circuit_projection_cross_validation_results`
2. 实现确定性交叉验证 API：`POST /api/mirror-kg/circuit-projection-cross-validation/run`
3. 对比 `circuit_to_projection` 与 `projection_to_circuit` memberships（分组 key：`circuit_id + projection_id`）
4. 输出 validation_status：`bidirectionally_supported` / `circuit_supported_only` / `projection_supported_only` / `conflict` / `insufficient_evidence`
5. 支持 dry_run（不写 run/result/不更新 membership）
6. 支持 apply_updates 更新 membership.verification_status（bidirectionally_supported / model_conflict）
7. 不改 review_status / promotion_status；不写 final_* / kg_*；不写 llm_extraction_runs/items
8. 列表 API：runs / results / get run
9. 前端 Macro Clinical Schema tab 新增 **Circuit-Projection Cross Validation Workbench**

### 边界

- **不调用** DeepSeek/Kimi/任何 LLM
- **bidirectionally_supported ≠ human_approved**；**conflict ≠ rejected**
- **不** auto approve / review / promote
- migration **未自动执行**

### 测试

- backend pytest 全量（含 `test_mirror_circuit_projection_cross_validation.py`）
- frontend build

### 下一步建议

**实现 Dual-Model Verification Execution** — 对 circuit/projection/membership/projection_function 分别调用 DeepSeek 与 Kimi，记录 consensus_supported / model_conflict / insufficient_information。

---

## Dual-Model Verification Execution（Step 8.12）

**日期**：2026-06-15  
**版本**：`4.2.9-mvp2-dual-model-verification-execution`

### 本轮完成

1. 实现 **dual_model_verification** 真实执行 API：`POST /api/mirror-kg/dual-model-verification/run`
2. DeepSeek（model_a）与 Kimi（model_b）**独立**调用，互不暴露对方原始输出
3. 后端 **确定性比较** consensus（不调用第三次 LLM）
4. 支持 object_type：circuit / projection / circuit_projection_membership / projection_function / circuit_step / triple
5. 写入两个 `llm_extraction_runs/items`（task_type=dual_model_verification）+ `mirror_dual_model_verification_runs/results`
6. 输出 consensus_supported / consensus_rejected / model_conflict / insufficient_information / needs_human_review
7. 支持 dry_run、scope 自动收集、cross validation context
8. `/run-task` 分派 `dual_model_verification`（implemented=true）
9. 前端 Macro Clinical Schema tab 新增 **Dual-Model Verification Workbench**

### 边界

- **不修改**被验证对象的 mirror_status / review_status / promotion_status
- **不写** final_* / kg_*；**不** auto approve / review / promote
- consensus_supported ≠ human_approved；model_conflict ≠ rejected
- 复用 migration 026 表（**未新增 migration**）

### 测试

- backend pytest 全量（含 `test_mirror_dual_model_verification_execution.py`）
- frontend build

### 下一步建议

**扩展 Mirror Human Review Queue** — 支持 circuit_step、projection_function、circuit_projection_membership、cross_validation_result、dual_model_verification_result，并在审核详情中展示完整 evidence / cross validation / dual-model 信号链。

---

## Macro Clinical Mirror Rule Validation Extension（Step 8.13）

**日期**：2026-06-15  
**版本**：`4.3.0-mvp2-macro-clinical-rule-validation`

### 本轮完成

1. 扩展 **Mirror Rule Validation** 覆盖 macro_clinical 对象：circuit_step、projection_function、circuit_projection_membership、circuit_projection_cross_validation_result、dual_model_verification_result、projection（alias）
2. circuit / triple 补充 macro_clinical 专属规则（predicate、steps、memberships、cross/dual 冲突信号）
3. cross validation / dual model 信号纳入审核前门禁：**conflict / consensus_rejected / insufficient_information 不自动 reject**；**consensus_supported / bidirectionally_supported 不自动 approve**
4. migration **028** 扩展 `mirror_rule_validation_results.target_type` CHECK constraint
5. 前端 Mirror Validation tab 增加 Macro Clinical target 多选、signal notes、high review priority / rule_checked summary
6. 新增 `test_mirror_rule_validation_macro_clinical.py`（29+ 用例）

### 边界

- **不调用 LLM**；不写 llm_extraction_runs/items
- **不写** final_* / kg_*；**不** auto approve / review / promote
- apply_status_update 仅将无 blocker/error 的对象 **mirror_status=rule_checked**
- **不修改** review_status / promotion_status
- cross_validation_result / dual_model_verification_result **无 mirror_status**，不更新

### 测试

- backend pytest：**701 passed**, 9 skipped
- frontend build

### 下一步建议

**设计并实现 Final macro_clinical Schema and Promotion** — 将 human_approved 且 validation 无 blocker/error 的 projection、circuit、circuit_step、projection_function、membership、triple 晋升到 final_* 正式表。

---

## Macro Clinical Mirror Human Review Queue Extension（Step 8.14）

**日期**：2026-06-15  
**版本**：`4.3.1-mvp2-macro-clinical-human-review`

### 本轮完成

1. 扩展 **Mirror Human Review Queue** 覆盖 macro_clinical 领域对象：projection、circuit_step、projection_function、circuit_projection_membership、region_function（alias）
2. 扩展审核 **信号对象**：circuit_projection_cross_validation_result、dual_model_verification_result
3. review detail 展示 validation results、evidence、cross validation signals、dual-model signals、related objects、gating / allowed actions
4. 新增 review actions：**accept_signal**、**dismiss_signal**、**flag_for_followup**；signal object 使用 accept/dismiss，不直接 approve/reject 领域对象
5. approve 仅表示 Mirror **human_approved**；reject 仅阻止 promotion，不删除对象
6. migration **029** 扩展 `mirror_human_review_records.target_type` 与 `action` CHECK constraint
7. 前端 Mirror Review tab 扩展为 **Macro Clinical Review Workbench**（filters、queue 列、detail 分区、domain/signal 动作、edit before/after preview）
8. 新增 `test_mirror_human_review_macro_clinical.py`

### 边界

- **不调用 LLM**（DeepSeek/Kimi/任何 provider）；不写 llm_extraction_runs/items
- **不写** final_* / kg_*；**不** auto approve / reject / promote
- signal action **不修改** linked domain object review_status
- accept_signal **不等于** approve domain object
- human_approved **不等于** final

### 测试

- backend pytest（含 macro clinical human review 用例）
- frontend build

### 下一步建议

**设计并实现 Final macro_clinical Schema and Promotion** — human_approved 且 validation 无 blocker/error 的 domain object 经 promotion 写入 final_*。

---

## Final macro_clinical Schema and Promotion（Step 8.15）

**日期**：2026-06-15  
**版本**：`4.4.0-mvp2-final-macro-clinical-promotion`

### 本轮完成

1. migration **030** — 新增 `final_projections`、`final_circuit_steps`、`final_circuit_functions`、`final_projection_functions`、`final_circuit_projection_memberships`、`final_macro_clinical_promotion_runs/records`；扩展 legacy final 表 provenance 字段
2. **复用** `final_region_circuits` / `final_region_functions` / `final_kg_triples` / `final_evidence_records` 作为 circuit / region_function / triple / evidence 目标表
3. `final_macro_clinical_promotion_service` — dry_run preview、confirm_text 强确认、eligibility gate、dependency promotion、duplicate 幂等、risk flags
4. API `/api/final-macro-clinical/promotion/*` 与 `/api/final-macro-clinical/objects/*`
5. 前端 **Final Promotion** tab（LlmExtractionPage）
6. 测试 `test_final_macro_clinical_promotion.py`

### 边界

- **写** final_*（dry_run=false 且 confirm 正确时）
- **不写** kg_* / 外部 NeuroGraphIQ_KG_V3
- **不调用 LLM**
- signal object 不可 promotion；cross/dual 仅作 provenance/risk metadata

### 下一步建议

**实现 Final KG Export / Sync Preparation** — 将 final_* 只读导出为 JSONL / CSV / Neo4j-compatible nodes/edges，为后续外部 NeuroGraphIQ_KG_V3 同步做准备，但仍不直接写外部正式库。

---

## Final KG Browser and Query Workbench（Step 8.16）

**日期**：2026-06-15  
**版本**：`4.5.0-mvp2-final-kg-browser`

### 本轮完成

1. **只读 Browser API** — `/api/final-macro-clinical/browser/search|region|circuit|projection|object|graph`
2. `final_macro_clinical_browser_service` — search、region neighborhood、circuit/projection detail、generic object detail、graph JSON、provenance payload
3. 前端 **Final KG Browser** tab（位于 Final Promotion 之后）— Search / Region Explorer / Circuit Detail / Projection Detail / Graph View
4. 测试 `test_final_macro_clinical_browser.py`（30+ 用例）

### 支持查询

- circuit、circuit_step、projection、projection_function、circuit_projection_membership、region_function、circuit_function、triple、evidence
- region neighborhood：functions、circuits、steps、projections、triples、evidence、graph
- provenance drill-down：source_mirror_id、promotion_run_id、promotion_record、validation/review/cross/dual summaries

### 边界

- **只读** — 不写 final_* / mirror_* / kg_* / 外部正式库
- **不调用 LLM**
- **不执行 promotion**
- graph JSON 仅用于前端展示

### 下一步建议

**External Sync Adapter Design and Dry-Run Validator** — 对接外部库前先做连接配置校验、schema mapping 校验、duplicate preview、dry-run import plan，但仍不直接写外部库。

---

## Final KG Export / Sync Preparation（Step 8.17）

**日期**：2026-06-15  
**版本**：`4.6.0-mvp2-final-kg-export`

### 本轮完成

1. **Final KG Export API** — `/api/final-macro-clinical/export/run|list|{id}/manifest|files|download`
2. `final_kg_export_service` — 从 final_* 只读构建 nodes/edges，写本地 `data/exports/final_kg/<export_id>/`
3. 支持 **JSONL** nodes/edges、**CSV** nodes/edges、**Neo4j-compatible CSV**、evidence/provenance jsonl、manifest.json、README.md
4. dry_run preview（不写文件）；real export 生成文件包
5. 前端 **Final KG Export** tab（LlmExtractionPage，位于 Final KG Browser 之后）
6. 测试 `test_final_kg_export.py`；文档 `docs/FINAL_KG_EXPORT_FORMAT.md`

### 边界

- **只读** final_*（SELECT）
- **不写** mirror_* / kg_* / 外部正式库
- **不连接 Neo4j**；不执行 Cypher / neo4j-admin import
- **不调用 LLM**；**不执行 promotion**
- 导出路径限定 `data/exports/final_kg/`；export_id / filename 防 path traversal

### 下一步建议

**External Sync Adapter Design and Dry-Run Validator**

---

## LLM Extraction Workflow UI Refactor（Step 9.1）

**日期**：2026-06-16  
**任务**：LLM Extraction Workflow UI Refactor with Stage Progress System

### 本轮完成

1. **LLM 提取页面改为 5 阶段工作流**：候选与运行 → Mirror 抽取 → Mirror 治理 → Final 晋升 → Final 知识层
2. **新增 Global Workflow Progress Bar**：横向 5 段进度条，点击可跳转阶段，每段显示完成百分比和 warning 数
3. **新增 Stage Rail**：左侧纵向阶段导航，显示状态 badge、进度百分比、阶段内 checklist
4. **新增 Next Step Recommendation**：底部根据当前进度计算下一步操作建议
5. **Candidate Detail 改为 Drawer**：不再整页替换，右侧 640px 抽屉，可关闭后回到原阶段
6. **Final Promotion / Browser / Export 形成线性流水线**：Final 晋升（Stage 4）→ Final 知识层（Stage 5），各有阶段边界提示
7. **新增 useSessionScope hook**：统一管理 resource_id / batch_id / source_atlas / granularity_level
8. **新增 useWorkflowProgress hook**：轻量 API 调用（limit=1）计算各阶段进度，API 失败降级为 warning
9. **新增 i18n 键**：`llm.workflow.*` 系列，中英双语
10. **新增 CSS 类**：`.llm-workflow-*`, `.workflow-progress-*`, `.workflow-stage-rail-*`, `.candidate-detail-drawer-*` 等

### 新增文件

```
frontend/src/pages/llm-extraction/
├── workflow/
│   ├── workflowTypes.ts
│   ├── useWorkflowProgress.ts
│   ├── WorkflowProgressBar.tsx
│   ├── WorkflowStageRail.tsx
│   └── WorkflowNextStep.tsx
└── hooks/
    └── useSessionScope.ts
docs/LLM_EXTRACTION_FRONTEND_REFACTOR_SPEC.md（新增）
```

### Tab 映射

| 原 Tab | 新阶段 |
|---|---|
| region / runs / items | Stage 1：候选与运行 |
| connections / functions / circuits / triples / macroClinical | Stage 2：Mirror 抽取 |
| validation / review | Stage 3：Mirror 治理 |
| finalPromotion / promotion（旧链路） | Stage 4：Final 晋升 |
| finalBrowser / finalExport | Stage 5：Final 知识层 |

### 边界（不变）

- **不改后端 API**
- **不改数据库 / migration**
- **不改业务边界**
- **不调用 LLM / 写 final_* / 写 kg_***
- **不删除任何现有功能**

### 下一步建议

**Round 2 UI 精修**：将 Macro Clinical 内部 6 个子流程改为"纵向 Pipeline Cards + 每步状态 + 一键跳转"

---

## Macro Clinical Pipeline UI Refinement（Step 9.2）

**日期**：2026-06-17  
**任务**：Macro Clinical Pipeline Cards with Step Status, Jump Actions, and Compact Workspaces

### 本轮完成

1. **Macro Clinical 内部改为 Pipeline Cards**：6 个子流程从全部展开变为纵向可折叠卡片
2. **新增 MacroPipelineOverview**：总进度条、警告计数、推荐下一步、边界说明
3. **新增 MacroPipelineCard**：每个步骤的紧凑头部（状态、输入/输出计数、操作按钮）+ 展开区
4. **新增 useMacroClinicalPipelineProgress**：只读 hook，limit=1 探测 7 个 API 判断各步骤状态
5. **6 个子流程按顺序展示**：Circuit→Steps / Steps→Projections / Projection→Functions / Projections→Circuits / Cross Validation / Dual-Model Verification
6. **自动展开逻辑**：首次进入自动展开第一个 ready/warning 步骤
7. **Result Nav**：底部快速跳转 5 个结果表（Circuit Steps / Projection Functions / Memberships / DM Runs / DM Results）
8. **Step 5/6 boundary notice**：Cross Validation 和 Dual Model 分别显示专属边界提示
9. **原有工作区完整保留**：所有 6 个 Workbench 函数不做任何修改，只改外层容器

### 新增文件

```
frontend/src/pages/llm-extraction/tabs/macro/
├── macroClinicalPipelineTypes.ts
├── useMacroClinicalPipelineProgress.ts
├── MacroPipelineCard.tsx
└── MacroPipelineOverview.tsx
```

### 边界（不变）

- **不改后端 API**
- **不改数据库 / migration**
- **不改业务边界**
- **不调用 LLM / 写 final_* / 写 kg_***
- **不删除任何现有功能**（6 个 Workbench 完整保留）

### 下一步建议

**Round 3**：为 Mirror Governance 阶段增加"Validation → Review"审核门禁面板，把 blocker/error/warning、review queue、human_approved 数量做成可操作的治理仪表盘。

---

## Mirror Governance Gate Dashboard（Step 9.3）

**日期**：2026-06-17  
**任务**：Mirror Governance Gate Dashboard for Validation → Review → Promotion Readiness

### 本轮完成

1. **Governance 阶段改为门禁 Dashboard**：原 Validation / Review 二级 Tab 改为三段门禁面板，顶部统一显示 GovernanceDashboard
2. **新增 GovernanceGateProgress**：横向三段门禁条（Rule Validation → Human Review → Promotion Ready），含状态图标、百分比、badge
3. **新增 GovernanceSeverityCards**：四张卡片（Blocker / Error / Warning / Info）显示数量和推荐动作
4. **新增 GovernanceReviewSummary**：Review Queue / Pending / Needs Revision / Human Approved / Rejected 五张统计卡，点击跳转 Review 工作区
5. **新增 GovernancePromotionReadiness**：human_approved 数、blocker/error 数、估算可晋升数、"进入 Final Promotion"按钮（切换 Stage，不执行 promotion）
6. **新增 GovernanceNextStep**：按 7 条优先规则推荐下一步操作
7. **新增 GovernanceGateCard**：可展开的 Gate 卡片，含边界提示和工作区跳转按钮
8. **新增 useGovernanceProgress**：轻量 hook，limit=1 分别查询 validation runs、severity 四级结果数、review queue 各状态计数，API 失败时降级显示警告
9. **原 Validation / Review 功能完整保留**：`MirrorValidationTab` 和 `MirrorReviewTab` 保持原有实现，渲染在 Dashboard 下方 `.governance-gate-workspace` 容器中

### 新增文件

```
frontend/src/pages/llm-extraction/tabs/governance/
├── governanceTypes.ts
├── useGovernanceProgress.ts
└── GovernanceDashboard.tsx
```

### 边界（不变）

- **不改后端 API**
- **不改数据库 / migration**
- **不改业务边界**
- **不调用 LLM**
- **不写 final_* / 写 mirror_* / 写 kg_***
- **不执行 review action 或 promotion**
- **build 成功（tsc 0 errors，Vite OK）**

---

## Data Center Sidebar Consolidation（Step 9.4）

**日期**：2026-06-17  
**任务**：Data Center Sidebar Consolidation and Knowledge Object Management UI

### 本轮完成

1. **新增数据中心一级导航**：`#/data-center`，图标 Layers
2. **移除一级导航**：Raw AAL3 标签、Raw Macro96 行、候选脑区
3. **Data Center 7 Tab**：Overview / Raw Data / Candidate Regions / Mirror KG / Macro Clinical / Final KG / Exports
4. **复用原页面**：RawAal3Page、RawMacro96Page、CandidatesPage 以 `embedded` 模式嵌入
5. **Candidate drawer**：点击候选行打开详情 drawer，支持 Copy ID、跳转 LLM 工作流
6. **Mirror/Macro/Final/Export 只读列表**：filter + detail drawer + 工作流跳转
7. **useDataCenterCounts**：limit=1 轻量统计 Overview summary cards
8. **旧路由兼容**：`/raw-aal3`、`/raw-macro96`、`/candidates` 及别名自动 redirect

### 新增文件

见 `docs/DATA_CENTER_UI_DESIGN.md` §7

### 边界（不变）

- **不改后端 API**
- **不改数据库 / migration**
- **数据中心不执行 LLM / validation / review / promotion / export run**
- **Generate Candidates 保留**（原候选脑区功能）
- **build 成功（tsc 0 errors，Vite OK）**

---

## Data Center Fixed Layout and Pagination（Step 9.5）

**日期**：2026-06-17  
**任务**：Data Center Fixed Navigation, Independent Data Scroll Area, and 20-row Pagination

### 本轮完成

1. **Sidebar 固定**：`.layout` 100vh + overflow hidden；sidebar sticky，不随右侧滚动
2. **Data Center 固定布局**：header / boundary / summary / tab / filter 静态；仅 `data-center-table-scroll` 滚动
3. **前端分页**：每页 20 条；`useDataCenterPagination` + `DataCenterPagination` + `DataCenterTableRegion`
4. **各 Panel 接入**：Raw / Candidate / Mirror / Macro / Final / Export 全部表格分页
5. **Candidate 特殊处理**：Generate Candidates 卡片 + status summary + filter 固定；表格单独滚动
6. **Raw 二级 tab**：AAL3 / Macro96 各自独立 page，切换 tab 重置
7. **底部日志栏避让**：`main.main-data-center` padding-bottom 随 log console 展开/收起变化
8. **i18n**：新增 `dataCenter.pagination.*` 等文案

### 新增文件

```
frontend/src/pages/data-center/
├── useDataCenterPagination.ts
├── DataCenterPagination.tsx
└── DataCenterTableRegion.tsx
```

### 边界（不变）

- **不改后端 API**
- **不改数据库 / migration**
- **不改业务边界**
- **build 成功（tsc 0 errors，Vite OK）**

---

## LLM Data-First Batch Extraction Layout（Step 9.6）

**日期**：2026-06-17  
**任务**：LLM Extraction Data-First Layout with Multi-select, Select-all, and Batch Extraction

### 本轮完成

1. **去除默认 WorkflowProgressBar / StageRail / NextStep**（组件文件保留）
2. **Data-first 布局**：compact header + task toolbar + 6 个 data tab
3. **候选表多选**：checkbox、当前页全选、筛选结果全选、跨页选择
4. **批量提取**：region_field_completion + same_granularity connection/function/circuit
5. **BulkRunStatusPanel** 进度与错误展示
6. **Macro Clinical** 保留 Pipeline，data-first 模式默认折叠
7. **Legacy URL 兼容**：`?tab=finalBrowser` 等仍可用

### 新增文件

见 `docs/LLM_EXTRACTION_FRONTEND_REFACTOR_SPEC.md` §13.7

### 边界（不变）

- **不改后端 API**
- **不改数据库 / migration**
- **不改业务边界**
- **build 成功（tsc 0 errors，Vite OK）**

---

## LLM Data-First UI Polish（Step 9.7）

**日期**：2026-06-17  
**任务**：LLM Extraction Data-First UI Polish and Runtime Error Fix

### 本轮完成

1. **确认并清理 useWorkflowProgress 残留引用**（data-first 页不再调用；无 WorkflowProgressBar/StageRail）
2. **统一 LLM 页面视觉**：card 风格 header/toolbar/filter/table
3. **修复操作列竖排**：固定 action 列宽 + nowrap
4. **scoped 控件样式**：llm-btn / llm-input / llm-select
5. **修复 selectedCount 回传**：批量按钮正确启用
6. **Final Links 卡片化**；Boundary 单行压缩

### 边界（不变）

- **不改后端 API**
- **不改数据库 / migration**
- **不改业务边界**
- **不恢复横向进度条 / StageRail**
- **build 成功（tsc 0 errors，Vite OK）**

---

## Step 9.8：Mirror 提取邻近 Tab + 批量选择（2026-06-17）

### 任务名
LLM Extraction Candidate + Mirror Extraction Adjacent Tabs with Selection and Pagination

### 主要变更
1. **Tab 顺序调整**：候选数据 → Mirror 提取 → 运行记录 → 结果条目 → Macro Clinical → Final 入口
2. **"Mirror 对象"改名为"Mirror 提取"**（`llm.dataFirst.mirrorExtraction` i18n key）
3. **新增 `MirrorExtractionPanel.tsx`**：连接/功能/回路/三元组 4 个子表，各自独立 selection + 分页
4. **Mirror 子表多选**：复用 `useBulkSelection` hook
5. **Mirror 子表分页**：前端分页，默认 100，选项 [50, 100, 200]
6. **Batch Bar**：展示已选数，提供跳转规则校验/人工审核按钮
7. **详情 Drawer**：轻量 JSON 详情，只读，不执行任何写操作
8. **i18n 新增**：`mirrorExtraction`、`connections`、`functions`、`circuits`、`triples` 等键
9. **CSS 新增**：`.llm-mirror-extraction-panel`、`.llm-mirror-batch-bar`、`.llm-selection-chip` 等

### 约束保证
- **不改后端 API**
- **不改数据库 / migration**
- **不改业务边界**
- **不调用 LLM，不写 final/kg**
- **候选数据 tab / Macro Clinical / Data Center 不受影响**
- **build 成功（tsc 0 errors，Vite OK）**

---

## Step 9.9：Mirror 提取 HTTP 422 修复（2026-06-17）

### 任务名
Mirror Extraction API Limit Fix for Data-First LLM Page

### 问题
- Mirror 提取 tab 请求 `limit=500`，后端 FastAPI/Pydantic 限制 `limit <= 200`，返回 HTTP 422

### 修复
1. 新增 `frontend/src/pages/llm-extraction/llmTableLimits.ts`：`API_MAX_LIMIT=200`、`clampApiLimit()`
2. `MirrorExtractionPanel.tsx` 四个子表 `limit: 500` → `limit: API_MAX_LIMIT`
3. `DataFirstCandidatesTab.tsx` `limit: 500` → `clampApiLimit(API_MAX_LIMIT)`
4. 友好错误展示：limit 422 不再直接显示原始 JSON
5. 筛选栏显示"已加载 N / 共 M 条"提示（当 API total > loaded）

### 约束
- **不改后端 API / 数据库 / migration / 业务边界**
- Mirror 多选、分页、data-first 样式保留

---

## Step 9.10：组合式 LLM 提取工作流按钮（2026-06-17）

### 任务名
Composite LLM Extraction Workflow Buttons

### 主要变更
1. **主按钮改为组合式流程**：候选字段补全 / 提取连接+连接功能 / 提取回路+功能+步骤 / 生成三元组
2. **原单步按钮收进"高级/单步任务"折叠区**
3. **新增 `compositeExtractionRunner.ts`**：前端编排已有 API，支持串行子步骤
4. **连接+功能**：先跑 connection extraction，再 listMirrorConnections 取 IDs，再跑 projection_to_functions
5. **回路+功能+步骤**：先跑 circuit extraction，再 listMirrorCircuits，再逐 circuit 跑 circuit_to_steps；circuit_to_functions 未实现 = SKIPPED
6. **三元组**：调用 consolidateMirrorTriples（已有）
7. **CompositeConfirmDialog**：执行前弹出确认，列出子步骤、provider、dry_run、boundary
8. **CompositeStatusPanel**：实时显示每个子步骤状态（pending/running/succeeded/failed/skipped）
9. **i18n + CSS**：新增 `llm.composite.*` 系列 key

### 约束
- **不改后端 API**
- **不改数据库 / migration**
- **不改业务边界**
- **endpoint 缺失 = skipped + warning，不假装成功**
- **build 成功（tsc 0 errors，Vite OK）**

---

*维护说明：每完成一个模块，更新 §2 进度表、§6 API、§9 代码树与版本号。*

---

## Step 9.14：全面放开抽取上限 + 结果弹窗 + 数据中心接入（2026-06-17）

### 任务名
Open-ended LLM Extraction Limits with Result Modal and Data Center Integration

### 用户要求
全面放开 LLM 抽取业务上限；保留 min 校验；大规模任务只 warning；抽取完成后弹窗显示结果；结果写入 mirror_* 并在数据中心可查看。

### 主要变更

**后端 schema**
- `BatchExtractRequest` / `RegionFieldCompletionRequest`：移除 `candidate_ids max_length=MAX_BATCH_SIZE`
- `ProjectionToFunctionsExtractionRequest` / `ProjectionsToCircuitsExtractionRequest`：移除 `projection_ids max_length`

**后端 services — 移除阻断/截断**
- `llm_connection_extraction_service.py`：移除 `MAX_CONNECTION_CANDIDATES` 阻断；`pair_count > max_candidate_pairs` 改为 warning 继续执行
- `llm_function_extraction_service.py`：移除 `MAX_FUNCTION_CANDIDATES` 阻断；`max_functions_per_region` 不再 skip，只 warning
- `llm_circuit_extraction_service.py`：移除 `MAX_CIRCUIT_CANDIDATES` 阻断；`max_circuits` / `max_regions_per_circuit` 不再截断
- `llm_circuit_step_extraction_service.py`：移除 `max_steps` 截断
- `llm_circuit_projection_extraction_service.py`：移除 `max_projections` 截断
- `llm_projection_function_extraction_service.py`：移除 `max_functions_per_projection` skip
- `llm_projection_circuit_extraction_service.py`：移除 `max_circuits` / `max_steps_per_circuit` 截断

**前端**
- `useBulkExtraction.ts`：connection/function/circuit 任务不再 auto-chunk（一次发送全部 candidate_ids）
- `ExtractionResultModal.tsx`：新增抽取结果弹窗（状态、子步骤、created counts、warnings、写入目标、跳转按钮）
- `LlmExtractionPage.tsx`：组合任务完成后弹出结果弹窗；确认框显示 pairCount 和大规模 warning
- 保留 min=2（connection/circuit）/ min=1（function/field）前端拦截
- 列表 API limit=200 保持不变（UI 分页，非抽取上限）

### 约束
- **不改数据库 / migration**
- **不限制 50 / 不限制 pair 数**
- **不自动分批**
- **build 成功；backend pytest 50 passed**

---

## Step 9.15：Server-side Composite LLM Extraction Workflow Run（2026-06-17）

### 任务名
Server-side Composite LLM Extraction Workflow Run for Connection+Function, Circuit+Function+Steps, and Triple Generation

### 用户要求
将前端组合编排下沉为可追踪、可审计、可重试的后端 composite workflow；前端优先调用后端 API，保留前端 fallback。

### 主要变更

**Migration `031_llm_composite_workflow_runs.sql`（未自动执行）**
- 新增 `llm_composite_workflow_runs`：workflow_type / status / scope / candidate_ids / pair_count / result_summary / warnings / errors
- 新增 `llm_composite_workflow_steps`：step_key / status / llm_run_id / created_counts / warnings / errors

**后端**
- `models/llm_composite_workflow.py`：`LlmCompositeWorkflowRun` / `LlmCompositeWorkflowStep`
- `schemas/llm_composite_workflow.py`：request/response enums 与 read models
- `services/llm_composite_workflow_service.py`：三类 workflow 编排，复用现有单步 extraction / triple consolidation services
- `routers/llm_composite_workflow.py`：
  - `POST /api/llm-extraction/composite-workflows/run`
  - `GET /api/llm-extraction/composite-workflows/runs`
  - `GET /api/llm-extraction/composite-workflows/runs/{id}`
  - `GET /api/llm-extraction/composite-workflows/runs/{id}/steps`

**支持的 workflow**
- `connection_with_function`：extract_connections → extract_projection_functions
- `circuit_with_function_steps`：extract_circuits → extract_circuit_steps → extract_circuit_functions（未实现则 skipped）
- `triple_generation`：generate_triples（`consolidate_mirror_triples`）

**前端**
- `endpoints.ts`：composite workflow API 与类型
- `compositeExtractionRunner.ts`：优先 backend composite API；404 时 fallback 前端编排
- `ExtractionResultModal.tsx`：显示 `workflow_run_id`、server-side workflow 标记、后端 substeps

**测试**
- `tests/test_llm_composite_workflow.py`：14 passed（mock services，不调用真实 LLM）

### 约束
- **不修改既有 mirror_* / final_* / kg_* 表结构**
- **不写 final_* / kg_*；不 promotion / export**
- **不限制候选数量 / pair_count（仅 warning）**
- **不默认自动分批**
- **不恢复 WorkflowProgressBar / StageRail**

---

## Step 9.16：移除仍存在的 candidate_ids max_length=50（2026-06-17）

### 任务名
Remove Remaining Pydantic candidate_ids max_length=50 from Active LLM Extraction Schemas

### 根因
HTTP 422 `List should have at most 50 items` 发生在 **Pydantic request validation**，早于 service。Step 9.14 已从 `backend/app/schemas/llm_extraction.py` 移除 `max_length=50`；若用户仍见该错误，通常是 **旧后端进程未重启**。

### 修复
- 确认 active route schemas（`SameGranularityCircuitExtractionRequest` 等）仅保留 `min_length`，无 `max_length`
- 新增 `tests/test_llm_schema_candidate_limits.py`：96 UUID 构造 + route 层非 max_length 422 断言
- 前端 `formatExtractionApiError.ts`：检测 stale max_length=50 并提示重启后端
- **必须重启后端** 后验证

### 约束
- 不改数据库 / migration
- 不把 50 改成 96
- 不自动截断 / 分批

---

## Step 9.17：Composite Workflow Service Invocation Signature Fix（2026-06-17）

### 任务名
Fix Composite Workflow Service Invocation Signature for Circuit Extraction

### 根因
`llm_composite_workflow_service.py` 向 `run_same_granularity_circuit_extraction(..., scope=...)` 传参，但 service 只接受 `scope_resource_id` / `scope_batch_id`（与 router 一致），导致 Step 1 TypeError，Step 2/3 skipped。connection workflow 存在相同问题。

### 修复
- 新增 adapter：`build_*_extraction_request` + `invoke_*_extraction`
- 构造 `SameGranularityCircuitExtractionRequest` / `SameGranularityConnectionExtractionRequest` 等 schema
- 调用方式与 `backend/app/routers/llm_extraction.py` 单步 endpoint 完全一致
- 不传 unsupported keyword（如 `scope=`）
- `normalize_step_error` 对 unexpected keyword TypeError 给出友好前缀

### 测试
- `test_llm_composite_workflow.py` 新增 invoke adapter 测试 + 96 candidate workflow 测试
- 47 passed

### 约束
- 不改数据库 / API 契约 / 单步 service 签名
- 不重新引入候选上限

---

## Step 9.18：Composite Workflow 500 Hardening + Runtime Progress Modal and Polling（2026-06-17）

### 任务名
Composite Workflow 500 Hardening with Runtime Progress Modal and Polling

### 500 根因
1. `circuit_to_steps` 写入 `llm_extraction_runs.scope_type='single_circuit'`，但 DB check constraint 不允许该值 → CheckViolation
2. Session 进入 PendingRollbackError，composite workflow 更新 step 状态时再次异常 → 裸 **500 Internal Server Error**

### 修复
- `llm_circuit_step_extraction_service.py` / `llm_projection_function_extraction_service.py`：`scope_type` 改为 `manual_selection`（无 migration）
- Composite service：per-step try/except、savepoint（circuit_to_steps 循环）、`_recover_unhandled_workflow_failure`
- Router `/run`：结构化错误，不再裸 500；workflow run 创建后失败仍返回 `workflow_run_id` + steps
- 新增 `POST /composite-workflows/start`（202）+ BackgroundTasks + `GET /runs/{id}` 轮询
- `progress_percent`：step 等权重；running=0.5；succeeded/skipped/failed=1.0
- `none_if_blank()` 规范化空 scope 字符串
- 前端：`startCompositeWorkflow` + poll；`ExtractionResultModal` 运行中进度条与子步骤状态
- 不恢复 WorkflowProgressBar / StageRail；不重新引入候选上限

### 测试
- `test_llm_composite_workflow.py`：23 passed
- `frontend npm run build`：成功

### 约束
- 不改数据库 / 无新 migration
- 不写 final_* / kg_*；不 promotion / export

---

## Step 9.20：LLM 候选数据区批次名称下拉 + 预览表恢复（2026-06-17）

### 任务名
Fix LLM Extraction Candidate Batch Name Selector and Restore Candidate Preview Table

### 问题
1. 候选 tab 筛选栏显示 batch_id UUID 文本输入框，用户无法按批次名称选择
2. 候选预览表格区域 flex 布局 `min-height: 0` 导致 tbody 可视高度塌陷，96 条数据存在但行不可见

### 修复
- `DataFirstCandidatesTab`：UUID 输入改为 `fetchImportBatches` 批次名称下拉；`batch_id` 仅内部 value
- 复用 `ImportBatch.description` / `batch_code` 作为显示名；未知批次显示「当前批次 · shortId」
- 应用后同步 `useSessionScope` + sessionStorage `batch_id`
- CSS：`.llm-table-shell` / `.llm-table-scroll` 最小高度 360px；`.llm-candidate-preview-card` 420px
- 空批次显示「当前批次没有候选数据」
- 本轮不处理 composite workflow 500 / 后端改动

---

## Step 9.21：LLM 提取 data-first 布局压缩 + 候选表格扩展（2026-06-17）

### 任务名
LLM Extraction Data-first Layout Compaction and Candidate Table Expansion

### 问题
1. `#/llm-extraction` 上方 header / warning / toolbar / tabs / filter 占用过多垂直空间，候选表格可视区域过小
2. 候选表格 flex 子项 `.llm-table-scroll` 使用 `min-height: 360px` 而非 `min-height: 0`，在 column flex 布局中无法正确占满剩余高度，tbody 几乎不可见
3. 控制台 `useSessionIds is not defined`：`LlmExtractionPage` 直接调用 `useSessionIds()` 但缺少 import
4. 控制台 `useI18n must be used within I18nProvider`：组件树因上述 ReferenceError 崩溃后的级联错误；`main.tsx` 已正确包裹 `I18nProvider`
5. 红色「至少需要选择 N 个候选」在页面加载时即显示，未等用户点击执行

### 修复
- **布局**：`main.main-llm-data-first` + `.llm-data-first-page` + `.llm-data-first-workspace` 全链 flex column；顶部 chrome 压缩（header 58–68px、boundary 32–34px、toolbar ≤100px、tabs 36px、filter 44–52px、selection bar 40–44px）
- **候选表格**：`DataFirstCandidatesTab` 使用 `llm-candidate-tab` → `llm-candidate-table-shell`（min-height 420px）→ `llm-candidate-table-scroll`（flex:1, min-height:0, overflow:auto）→ pagination（flex-shrink:0）
- **日志栏避让**：`main-llm-data-first` padding-bottom 预留 `--log-console-height-collapsed/expanded`
- **session hook**：`useSessionScope` 内部统一调用 `useSessionIds`；`LlmExtractionPage` 移除裸 `useSessionIds()` 调用
- **校验提示**：`candidateMinError` 仅在 `handleBatchExtract` 点击后设置；mount 时只更新非阻断 `candidateLargeWarning`
- 移除重复 `.llm-table-scroll { min-height: 360px }` 规则

### 约束
- 不改数据库 / 无新 migration
- 不改后端 composite workflow 500
- 不恢复 WorkflowProgressBar / StageRail
- 不写 final_* / kg_*

---

## Step 9.22：Composite Workflow 后端链路稳定化（2026-06-17）

### 任务名
Stabilize Backend Composite Workflow: Start/Poll, Active Schema Limit Removal, Structured Errors, and Progress Tracking

### 问题
1. 旧后端进程未重启：`/composite-workflows/start` 404；`/run` 仍走旧代码
2. `/run` 裸 500：`circuit_to_steps` 曾写 `scope_type=single_circuit`，违反 `chk_llm_extraction_run_scope_type` → PendingRollbackError
3. active schema max_length=50 在旧进程上仍可能生效
4. pair_count 阻断已改为 warning-only，需确认旧逻辑已清除

### 修复
- `BACKEND_VERSION=4.7.0-mvp2-composite-workflow-stabilization` + startup 日志
- `/composite-workflows/start` 202 + BackgroundTasks 后台执行
- `/composite-workflows/runs/{id}` 返回 steps + progress_percent
- `/run` 捕获 CompositeWorkflowHandledError，返回结构化 failed（非裸 500）
- `candidate_ids` 无 max_length=50；pair_count 仅 warning
- `circuit_to_steps` 使用 `scope_type=manual_selection`；step 失败 session.rollback()
- 前端 start+poll + 友好错误压缩 + /start 404 回退 /run

### 约束
- 不重新引入候选上限 / pair 阻断 / 自动分批
- 复用 migration 031，不新增 migration

---

## Step 10.1：Data Center 正式字段对齐 + 通用 DeepSeek 字段补全设计（2026-06-17）

### 任务名
Formal-field Data Center Display and Universal DeepSeek Field Completion Design

### 用户要求
1. 提取结果（回路、步骤、功能、连接等）在数据中心按 **final KG 正式字段** 展示
2. Mirror 仍为候选层，展示对齐不等于 promotion
3. 每次提取结果可继续 **通用字段补全**；默认 DeepSeek；只写 Mirror/candidate，不写 final/kg

### 产出
- 新增 `docs/DATA_CENTER_FORMAL_FIELD_ALIGNMENT.md`
- 新增 `docs/UNIVERSAL_FIELD_COMPLETION_DESIGN.md`
- 新增 `frontend/src/pages/data-center/formalFieldMappings.ts`（未接入 UI）
- 更新 `docs/DATA_CENTER_UI_DESIGN.md`、`LLM_EXTRACTION_FRONTEND_REFACTOR_SPEC.md`
- 分步计划 Step 10.2–10.6

### 约束
- 本轮不写 final_* / kg_*；不改 DB；不调用 DeepSeek；不大改 Data Center / LLM 提取 UI

---

## Step 10.2：Data Center Mirror KG / Macro Clinical 正式字段展示（2026-06-17）

### 任务名
Data Center Formal-field Display for Mirror KG and Macro Clinical Objects

### 产出
- 完善 `frontend/src/pages/data-center/formalFieldMappings.ts`（`FormalObjectType`、`getFieldValue`、`computeMissingFields`、`computeCompleteness`）
- 新增 `FormalObjectTableSection`、`FormalAlignmentCard`、`MissingFieldsBadge`、`FieldCompletionPlaceholderModal`、`FormalObjectDetailDrawer`
- 改造 `MirrorKgPanel.tsx`、`MacroClinicalDataPanel.tsx`（正式列 + missing badge + 字段补全占位）
- Macro Clinical 新增 `circuit_functions` 子 tab（planned empty state）
- i18n + CSS（`.data-center-formal-*`、`.data-center-missing-*`）
- 更新 `DATA_CENTER_FORMAL_FIELD_ALIGNMENT.md`、`UNIVERSAL_FIELD_COMPLETION_DESIGN.md`、`LLM_EXTRACTION_FRONTEND_REFACTOR_SPEC.md`

### 约束
- 不调用 DeepSeek；不实现字段补全 API；不改 DB / migration；不写 final_* / kg_*；不 promotion / export
- Cross Validation / Dual Model 子 tab 保留原简表（后续补齐 formal 列与多选）

---

## Step 10.3：Universal Field Completion 后端基础（2026-06-17）

### 任务名
Universal DeepSeek Field Completion Backend Foundation

### 产出
- 新增 `backend/migrations/032_universal_field_completion.sql`（`llm_field_completion_runs` / `llm_field_completion_items`）
- 新增 `backend/app/models/llm_field_completion.py`
- 新增 `backend/app/schemas/llm_field_completion.py`
- 新增 `backend/app/services/field_completion_registry.py`
- 新增 `backend/app/services/llm_field_completion_service.py`
- 新增 `backend/app/routers/llm_field_completion.py`
- 注册 `universal_field_completion_v1` prompt template
- 新增 `backend/tests/test_llm_field_completion.py`（17 tests，mock provider，无真实 DeepSeek）
- 可选：`frontend/src/api/endpoints.ts` 新增 field completion API 函数（Data Center 仍用 Preview 占位）

### API
- `POST /api/llm-extraction/field-completion/run`
- `GET /api/llm-extraction/field-completion/runs`
- `GET /api/llm-extraction/field-completion/runs/{run_id}`
- `GET /api/llm-extraction/field-completion/items`

### 约束
- mirror/candidate 写入 only；`fill_missing_only` 默认；dry_run 不调用 provider
- 不写 final_* / kg_*；不自动 approve / promote
- `circuit_function` → 501（mirror_circuit_functions 未实现）
- migration 不自动执行

---

## Step 10.4：Data Center Universal Field Completion UI Integration（2026-06-17）

### 任务名
Data Center Universal Field Completion UI Integration

### 产出
- 新增 `frontend/src/pages/data-center/FieldCompletionModal.tsx` — 参数区、dry_run preview、执行确认、结果展示、最近 Runs / Items tab
- 新增 `frontend/src/pages/data-center/fieldCompletionUtils.ts` — target_type 映射、request 构建、missing/completable 字段计算、错误分类
- 改造 `FormalObjectTableSection.tsx` — 顶部/行级打开真实 Modal；`onRefresh` 回调；无选中时禁用
- 改造 `MirrorKgPanel.tsx`、`MacroClinicalDataPanel.tsx` — detail drawer 字段补全；表格 refresh
- 更新 `frontend/src/i18n.ts`（`dataCenter.fieldCompletion*` 中英 key）
- 更新 `frontend/src/styles.css`（`.data-center-field-completion-*`）
- 保留 `FieldCompletionPlaceholderModal.tsx` 作为 fallback 文档参考（入口已切换至 FieldCompletionModal）

### 行为
- 多选 / 行级 / detail drawer 三种入口
- 默认 `provider=deepseek`、`model=deepseek-chat`、`field_scope=missing_only`、`overwrite_policy=fill_missing_only`、`dry_run=true`
- Dry Run Preview → prompt_preview + field update suggestions；成功后启用「执行字段补全」
- 执行前确认弹窗；`dry_run=false` + `create_mirror_updates=true`；完成后 `onCompleted` 刷新当前表
- Modal 内 tab：当前结果 / 最近 Completion Runs / Items（`listFieldCompletionRuns` limit=20）
- API 404/501/503 友好降级，不崩溃
- `circuit_function` 显示 unsupported（mirror_circuit_functions 未实现）

### 约束
- mirror/candidate 写入 only；不写 final_* / kg_*；不自动 approve / promote / export
- 自动测试不调用真实 DeepSeek；`npm run build` 通过
- 不改数据库 / migration；不改后端 service（Step 10.3 已就绪）

---

## Step 10.4.1：Data Center Real Formal Schema Alignment（2026-06-17）

### 任务名
Real Formal Schema Alignment for Data Center Based on NeuroGraphIQ_KG_V3

### 背景
Step 10.2–10.4 中 Data Center formal mapping 使用了概念化的 `final_region_circuits`、`final_projections` 等表名，这些表名不存在于真实正式库。用户反馈 Data Center 中没有 `name_cn`，并确认正式库名称为 `NeuroGraphIQ_KG_V3`，正式 schema 为 `macro_clinical`。

### DB Introspection 结果（NeuroGraphIQ_KG_V3）

| 正式表 | 关键字段 |
|--------|---------|
| `macro_clinical.circuit` | id, name_cn, name_en, circuit_class, canonical_start_region_id, canonical_end_region_id, description, remark, attributes, source_db, status, created_at, updated_at |
| `macro_clinical.projection` | id, name_cn, name_en, projection_type, source_region_id, target_region_id, directionality, strength_score, confidence_score, evidence_level, ... |
| `macro_clinical.circuit_step` | id, circuit_id, step_no, step_name_en, step_name_cn, region_id, projection_id, role_in_circuit, ... |
| `macro_clinical.projection_function` | id, projection_id, function_term_en, function_term_cn, function_domain, function_role, effect_type, confidence_score, ... |
| `macro_clinical.circuit_function` | id, circuit_id, function_term_en, function_term_cn, function_domain, function_role, effect_type, confidence_score, ... |
| `macro_clinical.region_function` | id, region_id, function_term_en, function_term_cn, function_domain, confidence_score, ... |

### 产出
- **formalFieldMappings.ts**：
  - `FormalFieldMapping` 新增 `formalSchema` 和 `formalQualifiedName` 字段
  - `FormalFieldColumn` 新增 `group?: 'formal' | 'governance'`
  - 所有 circuit / projection / circuit_step / projection_function / circuit_function / region_function 映射重写为真实 DB 字段
  - `name_cn（中文名）`、`name_en（英文名）`、`circuit_class（回路类别）` 等中英标注列加入
  - GOVERNANCE 列标记 `group: 'governance'`，不再参与 formal completeness 计算
- **FormalAlignmentCard.tsx**：显示 `NeuroGraphIQ_KG_V3` + `formalQualifiedName`
- **FormalObjectDetailDrawer.tsx**：分组显示 Formal Fields / Governance / Provenance / Raw JSON
- **i18n.ts**：新增 formalDatabase、formalSchema、formalQualifiedName、formalFieldsSection、governanceFields、mirrorCandidateLayer、notWrittenToFormalDb、missingFormalFields 等 key
- **styles.css**：新增 `.data-center-json-pre`、`.data-center-detail-notice`
- **npm run build** 通过（TypeScript 0 错误）

### 重要说明
- `name_cn` 在 Mirror 表中通常不存在（Mirror 提取不产生中文名）→ 计入 missing → 需字段补全
- `circuit_class` 从 Mirror 的 `circuit_type` 字段映射（语义近似，正式字段用 circuit_class）
- Mirror 数据来源不变（`mirror_region_circuits` 等），仅 display alignment 修正

### 约束
- 不改数据库；不新增 migration；不写正式库；不改后端 API；不自动审核/晋升

---

## Step 9.13：最小侵入修复 — 移除候选数上限 + 修复运行时错误（2026-06-17）

### 任务名
Minimal Invasive LLM Extraction Error Hardening without 50-candidate Hard Limit

### 用户明确要求
**不把 50 作为候选抽取硬限制**。>50 个候选只显示非阻断 warning；min=2 保留。

### 主要变更

**后端 schema**

1. `SameGranularityCircuitExtractionRequest.candidate_ids`: 移除 `max_length=50`，保留 `min_length=2`
2. `SameGranularityConnectionExtractionRequest.candidate_ids`: 移除 `max_length=30`，保留 `min_length=2`
3. `SameGranularityFunctionExtractionRequest.candidate_ids`: 移除 `max_length=30`，保留 `min_length=1`
4. 96 个候选不再因 schema max_length=50 被拒绝；1 个候选执行 connection/circuit 仍返回 422

**前端 compositeExtractionRunner.ts**

5. 移除 `CANDIDATE_LIMITS`（含 max 值），改为 `CANDIDATE_MINIMUMS`（仅 min 值）
6. 移除 `>max` 硬拦截（之前 >50 会返回 failed_validation）
7. 保留 `<min` 的 failed_validation（<2 个候选时不执行）
8. 新增：>50 个候选时在 warnings 数组中记录非阻断 warning

**前端 LlmExtractionPage.tsx**

9. 删除 `TASK_CANDIDATE_LIMITS`（含 max 值）
10. 删除 `validateCandidateCountForTask`（max 检查）
11. 新增 `TASK_CANDIDATE_MINIMUMS` 和 `getMinCandidateCountForTask`（仅 min）
12. 新增 `getCandidateLargeCountWarning`：>50 时显示非阻断 warning
13. 状态从 `candidateValidationError` 拆分为 `candidateMinError`（阻断）+ `candidateLargeWarning`（非阻断）
14. 删除 `trimSelectionFn` 状态（不再需要"仅保留前 N 个"）
15. 删除 `onTrimSelectionReady` prop 调用

**前端 DataFirstCandidatesTab.tsx**

16. 删除 `onTrimSelectionReady` prop（不再需要）
17. 删除关联 effect（该 effect 是 Hook 顺序错误的来源）

**i18n**

18. 删除 max-blocking 相关文案（candidateTooMany, maxCandidateHint, keepFirstMax, circuitMaxHint, backendTooLongFriendly）
19. 新增大批量 warning 文案（largeSelectionWarning, largePairWarning, circuitToStepsFriendlyError, skippedBecausePreviousFailed）

**CSS**

20. `.llm-validation-error` 改为红色（blocking error）
21. 新增 `.llm-selection-large-warning` 黄色（non-blocking warning）

### 约束
- **不改数据库 / migration**
- **不限制 50** — 50 只作为 warning 阈值
- **保留 min_length=2** for connection/circuit
- **不自动分批**
- **build 成功（tsc 0 errors）**
- **backend pytest: 24 passed**

---

## Step 9.12：回路抽取候选数上限校验与组合 Runner 防御（2026-06-17）

### 任务名
Circuit Extraction Candidate Count Upper Bound Validation and Composite Runner Guard

### 问题现象
用户选择 96 个候选后点击"提取回路+功能+步骤"，前端直接发送请求到后端，后端返回 HTTP 422：
- `candidate_ids` 最多 50 项，实际 96 项
- Step A circuit failed → Step B/C 被跳过
- 后端 circuit-to-steps 500（无结构化错误消息）

### 根因
1. `SameGranularityCircuitExtractionRequest.candidate_ids` max_length=50
2. `SameGranularityConnectionExtractionRequest.candidate_ids` max_length=30
3. 前端无候选数校验，允许任意数量直接请求后端
4. 后端 circuit-to-steps endpoint 缺少 catch-all Exception handler，非预期异常泄漏为裸 500

### 主要变更

**前端**

1. **`useBulkSelection.ts`**：新增 `trimToN(max)` 方法，保留前 N 个已选项（按 filteredItems 顺序）
2. **`compositeExtractionRunner.ts`**：
   - 新增 `CANDIDATE_LIMITS` 常量，记录各任务候选数上限（connection=30, circuit=50）
   - `SubstepStatus` 新增 `'failed_validation'`
   - `CompositeExtractionResult` 新增 `validationError?: string` 字段
   - `runConnectionWithFunction` 执行前检查 min=2/max=30，超出则返回 `failed_validation` 结果，不发请求
   - `runCircuitWithFunctionAndSteps` 执行前检查 min=2/max=50，超出则返回 `failed_validation` 结果，不发请求
3. **`LlmExtractionPage.tsx`**：
   - 新增 `TASK_CANDIDATE_LIMITS` 常量（所有任务的 min/max）
   - 新增 `validateCandidateCountForTask(taskId, count)` 函数
   - `handleBatchExtract` 在进入确认对话框前先做校验，失败时设置 `candidateValidationError` 并 return
   - 新增 `candidateValidationError` 状态，任务/候选数变化时自动清除
   - 新增 `trimSelectionFn` 状态，接收来自 DataFirstCandidatesTab 的 trim 回调
   - 工具栏下方显示内联校验错误块，包含"仅保留前 N 个"和"关闭"快捷操作
4. **`DataFirstCandidatesTab.tsx`**：新增 `onTrimSelectionReady` prop，挂载后将 `selection.trimToN` 传给父组件
5. **`i18n.ts`**：新增 `llm.validation.*` 和 `llm.composite.failedValidation` 系列 key（中英双语）
6. **`styles.css`**：新增 `.llm-validation-error`、`.llm-selection-limit-actions`、`.llm-btn-xs`、`.llm-btn-warning` 样式

**后端**

7. **`routers/llm_extraction.py`**：在 circuit-to-steps 端点末尾新增 `except Exception as exc` catch-all，返回结构化 500（不改 API 契约）
8. **`tests/test_llm_circuit_step_extraction_validation.py`**：新增 4 个防御性测试：缺失 circuit_id → 422，未知 circuit_id → 404，意外异常 → 结构化 500，非法请求体 → 非 500

### 任务上限汇总

| 任务 | min | max |
|------|-----|-----|
| region_field_completion | 1 | 20 |
| same_granularity_function_completion | 1 | 30 |
| same_granularity_connection_completion | 2 | 30 |
| composite_connection_with_function | 2 | 30 |
| same_granularity_circuit_completion | 2 | 50 |
| composite_circuit_with_function_and_steps | 2 | 50 |
| composite_triple_generation | 0 | ∞ |

### 不自动分批回路抽取
回路抽取依赖同批候选内的关联性，自动分批可能丢失跨批回路关系产生不完整结果。
本轮策略：超过 50 个时前端阻止请求，提示用户手动缩减，提供"仅保留前 50 个"快捷操作。

### 约束
- **不改数据库 / migration**
- **不改后端 API 契约**（仅增加 catch-all 防御）
- **不改业务边界**
- **不自动分批回路抽取**
- **build 成功（tsc 0 errors，Vite OK）**
- **backend pytest: 4 new + 20 existing = 全部通过**

---

## Step 10.4.2 — Real Formal Field Completion Alignment (2026-06-17)

### 完成内容

1. 后端 `field_completion_registry.py` 全面重写：enrichable_fields 改为真实正式字段名
   - circuit: name_en, name_cn, circuit_class, description, remark, attributes, source_db, status
   - projection_function: function_term_en, function_term_cn, function_domain, function_role, effect_type
   - circuit_step: step_name_en, step_name_cn, step_no, role_in_circuit, description
   - 新增 formal_to_mirror（direct write），overlay_field_names（无 Mirror 列 → overlay）
2. 后端 llm_field_completion_service.py：apply_field_update 新增 entry 参数，实现 direct/overlay 分路
3. 后端 Router：field_scope=selected_fields 时预校验字段名，422 INVALID_SELECTED_FIELDS
4. 前端 formalFieldMappings.ts：getFieldValue 支持 overlay 读取
5. 前端 fieldCompletionUtils.ts：新增 getEnrichableFormalFields / validateSelectedFormalFields

### 约束（已保证）

- 不写正式库 macro_clinical.* / final_* / kg_*
- 不新增 migration（overlay 写入现有 JSONB 列）
- 不调用真实 DeepSeek（测试中）
- 不自动 approve / promote

### 测试结果

- Backend pytest: 39 passed, 0 failures
- Frontend build: 0 TypeScript errors, Vite OK

---

## Step 10.4.3 — Field Completion API Registration and Runtime Stabilization (2026-06-17)

### 问题

1. 前端调用 `/api/llm-extraction/field-completion/run` 与 `/runs` 返回 **404** — 运行中的后端进程为旧代码（系统 Python，未加载 field-completion router）。
2. `useSessionScope` 内部调用 `useSessionIds()` hook，在 LlmExtractionPage 引发 hook 链 / ReferenceError。
3. migration `032_universal_field_completion.sql` 未执行时 dry_run 返回 **500**（表不存在）。

### 修复

1. **重启后端**：使用 `backend/.venv` + `run_server.py`（端口 8002）；`main.py` 增加 startup 日志确认 router 注册。
2. **useSessionScope**：改为直接读写 `sessionStorage`，不再调用 `useSessionIds()` hook。
3. **FieldCompletionModal**：runs 列表 404 时显示友好 warning，同一 modal 生命周期内不重复请求。
4. **i18n**：更新 `apiNotEnabled` / `fieldCompletionRunsUnavailable` 文案（提示重启后端）。
5. **migration**：在开发库 `neurographiq_kg_v3_mvp1_e2e` 手动执行 `032_universal_field_completion.sql`。

### 验证

- POST `/field-completion/run` dry_run=true → 200，`status=dry_run`，含 `prompt_preview`
- GET `/field-completion/runs` → 200，不再 404

---

## Step 10.4.4 — Execute Universal Field Completion with Mirror Overlay Write (2026-06-17)

### 目标

`dry_run=false` 时调用 provider（测试 mock），解析 `field_updates`，写入 Mirror 候选层 direct 列或 `normalized_payload_json.formal_field_overlay`，审计写入 `llm_field_completion_items`，Data Center 刷新后通过 `getFieldValue` 显示 overlay。

### 后端

1. **`apply_field_update`**：`applied_direct` / `applied_overlay` / `skipped_readonly_field` 等细分 status
2. **overlay write**：`name_cn` 等无 Mirror 列字段 → `normalized_payload_json["formal_field_overlay"]` + `formal_field_overlay_meta`
3. **direct write**：`name_en` → `circuit_name`，`circuit_class` → `circuit_type`，`description` 等同名列
4. **provider**：`dry_run=false` 调用 DeepSeek；pytest monkeypatch mock，不调用真实 API
5. **run summary**：`summary_json` 含 `applied_overlay_count`、`applied_direct_count`、`invalid_field_count` 等
6. **不写**：`macro_clinical.*`、`final_*`、`kg_*`；不自动审核/晋升/export

### 前端

1. **`getFieldValue`**：优先 formal 列 → `attributes.formal_field_overlay` → 顶层 overlay → `__fieldCompletionOverlay` → mirror 列 → `normalized_payload_json` overlay
2. **`FieldCompletionModal`**：执行确认文案（Mirror-only、fill_missing_only）；结果表显示 overlay/direct badge 与 `error_message`
3. 执行成功后 `onCompleted` 刷新表格；`MissingFieldsBadge` 与 overlay 联动

### 测试

- `backend/tests/test_llm_field_completion.py`：**42 passed**（mock provider、overlay/direct write、invalid/readonly skip、malformed JSON 不 500）
- `frontend npm run build`：通过

### 下一步

Step 10.5：LLM 抽取结果弹窗「继续字段补全」，携带 created target ids 与 formal `selected_fields`。

---

## Step 10.5.1 — Runtime Hook Stabilization and Field Completion API Registration (2026-06-22)

### 任务名
Fix Runtime Hook Errors and Register Field Completion API

### 问题定位

1. **useI18n provider**：`main.tsx` 已用 `<I18nProvider>` 包裹 `<App />`；此前 `useSessionIds is not defined` 导致组件树崩溃后出现级联 `useI18n must be used within I18nProvider`。
2. **useSessionIds 未定义**：`LlmExtractionPage` 曾裸调 `useSessionIds()` 且无 import；现统一为 `readSessionIds()` + `useSessionScope()`（sessionStorage 直读写，不再嵌套 `useSessionIds()` hook）。
3. **Should have a queue**：`useSessionScope` 内部曾调用 `useSessionIds()`，与页面层大量 `useData` 叠加引发 hook 顺序异常；`FieldCompletionModal` / `ExtractionResultModal` 已确保全部 hook 在 `if (!open) return null` 之前。
4. **POST/GET field-completion 404**：运行中后端为旧进程（系统 Python 或未加载 `llm_field_completion` router）；正确路径为 `/api/llm-extraction/field-completion/*`，监听 **8002**（`run_server.py` + `.venv`）。

### 修复项

1. **I18nProvider**：保持 `main.tsx` 结构 `<I18nProvider><WorkbenchLogProvider><App /></WorkbenchLogProvider></I18nProvider>`。
2. **Session hook**：`LlmExtractionPage` 使用 `useSessionScope`；子 tab 使用 `readSessionIds()`；禁止混用裸 `useSessionIds()`。
3. **Hook 顺序**：`LlmExtractionPage` 顶层 hook 无条件调用；modal 组件 hook 在 early return 之前。
4. **后端注册**：`backend/app/main.py` 注册 `llm_field_completion.router`，prefix=`/api/llm-extraction/field-completion`；startup 日志打印 router prefix。
5. **dry_run preview**：`POST /run` + `dry_run=true` 返回结构化 JSON（含 `prompt_preview`）；不调用 DeepSeek、不写 Mirror/正式库/final/kg。
6. **runs/items**：`GET /runs`、`GET /items` 返回 200（空列表亦可）；`GET /runs/{id}` 找不到返回结构化 404。
7. **前端 404 降级**：`FieldCompletionModal` POST 404 显示友好提示；最近补全记录 tab 懒加载，404 后同 modal 生命周期内不重复请求。

### 约束（已保证）

- 不写正式库 `macro_clinical.*` / `final_*` / `kg_*`
- 不调用真实 DeepSeek 做自动测试
- 不大改 Data Center / LLM Extraction UI

### 测试

- `frontend npm run build`：通过
- `backend pytest tests/test_llm_field_completion.py -q`：**42 passed**
- 手动：`GET/POST /api/llm-extraction/field-completion/*` 在 8002 不再 404；`#/llm-extraction` 控制台无 useSessionIds / hook queue 错误

---

## Step 10.5.2 — Universal Field Completion Execution with Mirror Overlay Write (2026-06-22)

### 任务名
Universal Field Completion Execution with Mirror Overlay Write and Data Center Refresh

### 后端

1. **dry_run=false 执行闭环**：`run_universal_field_completion` 创建 run → 调 provider → 解析 `field_updates` → `apply_field_update`（direct / overlay）→ 写 `llm_field_completion_items` → `summary_json` → 返回 response。
2. **Registry**：`allowed_fields` / `direct_write_fields` / `overlay_write_fields` / `readonly_fields`；circuit 对齐 `macro_clinical.circuit` 正式字段。
3. **Overlay 写入**：无 Mirror 列的 formal 字段（如 `name_cn`）写入 `normalized_payload_json.formal_field_overlay` + `formal_field_overlay_meta`（物理存储；API 以 `attributes` 别名暴露）。
4. **Direct 写入**：`name_en` → `circuit_name`，`circuit_class` → `circuit_type`，`description` 等同名列；`fill_missing_only` 不覆盖非空值。
5. **Provider 解析**：`parse_field_completion_provider_response` 支持 JSON string / markdown / content 包装；legacy 字段名（如 `circuit_name`）→ `skipped_invalid_field`。
6. **Response**：新增 `applied_overlay_count` / `applied_direct_count` / `summary_json`。

### 前端

1. **getFieldValue**：`formalFieldMappings.ts` 按 overlay 查找顺序读取 `attributes.formal_field_overlay` 与 `normalized_payload_json`。
2. **FieldCompletionModal**：执行成功后拉取 run detail items；展示 summary + items 表（Overlay/Direct/Skipped badge）；`onCompleted` 刷新表格。
3. **Mirror list API**：Read schema 增加 computed `attributes`（= `normalized_payload_json`）。

### 约束

- 不写正式库 `macro_clinical.*` / `final_*` / `kg_*`
- 自动测试 mock provider，不调用真实 DeepSeek
- 无新 migration

### 测试

- `pytest tests/test_llm_field_completion.py -q`：**47 passed**
- `frontend npm run build`：通过

---

## Step 10.5.3 — Circuit Bundle Field Completion (2026-06-22)

### 任务名
Circuit Bundle Field Completion for Circuit + Circuit Step + Circuit Function

### 问题

字段补全工作台原先每次只能补单个 `target_type`（circuit / circuit_step / circuit_function 三选一）。回路业务上三类对象应联动补全。

### 后端

1. **新增只读 API**：`GET /api/llm-extraction/field-completion/related-targets`
   - `target_type=circuit` + `target_ids` + `include=circuit_step,circuit_function`
   - `circuit_step`：查 `mirror_circuit_steps.circuit_id IN (...)`
   - `circuit_function`：`mirror_circuit_functions` 未实现 → 空 group + warning，不 500
2. **保留**现有单 target `POST /field-completion/run`；不新增跨 target 写入 API。
3. **不写**正式库 / final_* / kg_*；不调用 provider（只读接口）。

### 前端

1. **`MultiTargetFieldCompletionModal`**：一次任务展示 Circuit / Step / Function 三组；串行 dry_run / execute。
2. **Data Center → Mirror KG → Circuits**：顶部/行级/详情「字段补全」默认打开 Circuit Bundle modal。
3. **LLM 抽取结果弹窗**：有 circuit/step/function created counts 时主按钮为「一键补全回路组合」。
4. **`getFieldCompletionRelatedTargets`** + `circuitBundleUtils` / `extractionToFieldCompletion.ts`。
5. **partial failure**：某组失败不阻断其他组；circuit_function 无数据显示 planned/unavailable。

### 约束

- 不写正式库 / final_* / kg_*；不自动审核/晋升/export
- 自动测试 mock provider；用户 `dry_run=false` 执行 bundle 时按组调用 DeepSeek
- 无 DB migration

---

## Step 10.5.4 — Overlay Display Consistency after Circuit Bundle Field Completion (2026-06-22)

### 任务名
Overlay Display Consistency after Circuit Bundle Field Completion

### 前端

1. **统一 `getFieldValue` 读取顺序**：formal 直读 → attributes/normalized_payload `formal_field_overlay` → `__fieldCompletionOverlay` 本地缓存 → mirror 候选（禁止跨字段冒充）。
2. **`computeMissingFields` / MissingFieldsBadge / 表格 / Detail drawer** 全部复用 `getFieldValue`；缺失 tooltip 显示 formal field 名。
3. **Bundle / 单对象补全执行后**：从 run items 提取 `applied_overlay`，合并 `__fieldCompletionOverlay` 至表格行，再 `onRefresh` 拉取持久化 overlay。
4. **Overlay 来源标识**：表格与 drawer 显示轻量 “Overlay” badge。

### 后端

- Mirror list Read schema 已含 computed `attributes`（= `normalized_payload_json`）；新增 circuit_step overlay schema 测试。
- overlay 写入路径不变（`write_to_overlay` + `flag_modified`）；不写正式库/final/kg。

### 测试

- `pytest tests/test_llm_field_completion.py -q`：51 passed
- `frontend npm run build`：通过

---

## Step 10.5.5 — Fix Related Targets Route and Decimal JSON Serialization (2026-06-22)

### 任务名
Fix Field Completion Related Targets Route and Decimal JSON Serialization

### Bug 1 — related-targets 404

- 确认 `GET /api/llm-extraction/field-completion/related-targets` 注册于 `llm_field_completion.router`（prefix `/api/llm-extraction/field-completion`）。
- 将 `/related-targets` 固定路径移至 router 顶部（在 `/run` 之前），避免未来泛型路由吞路径。
- service `get_related_field_completion_targets`：circuit 直返；circuit_step 查 `mirror_circuit_steps.circuit_id`；circuit_function 不可用返回 warning，不 500。
- 404 常见原因：旧后端进程未重启；修复后需重启 `run_server.py`。

### Bug 2 — Decimal JSON serialization 500

- 根因：ORM `Numeric`（如 `confidence`）经 `object_to_json` 进入 prompt `json.dumps` / JSONB 列。
- 新增 `backend/app/utils/json_safety.py`：`to_jsonable()` / `json_dumps_safe()`（Decimal→float，datetime/UUID/Enum 递归处理）。
- 应用点：`object_to_json`、`write_to_overlay`、`build_target_context`、`build_universal_prompt`、item JSONB、`summary_json` / `warnings_json` / `errors_json` / `request_json`、API response。
- `dry_run=false` mock provider 测试：target 含 Decimal confidence 不再 500。

### 约束

- 不写正式库 / final_* / kg_*；无 DB migration；自动测试 mock provider。
- `pytest tests/test_llm_field_completion.py -q`：55 passed。

---

## Step 10.5.6 — Prompt Workbench and Circuit-Logic Field Completion (2026-06-22)

### 任务名
Prompt Workbench and Circuit-Logic Field Completion Prompt Engineering

### 后端

- 新增 12 个字段级 prompt template key + `circuit_bundle_consistency_v1`；保留 `universal_field_completion_v1` fallback。
- `select_field_completion_prompt_key(target_type, field_name)` 按字段选 prompt。
- 执行流程改为 **per target × per field** 独立 prompt + provider 调用；Circuit 家族先跑 bundle consistency（可选）。
- `build_circuit_bundle_context` 带入 circuit / steps / functions / regions / overlay。
- `UniversalFieldCompletionRequest.prompt_overrides` 支持本次执行临时覆盖 prompt。
- `dry_run` 的 `prompt_preview` 含 `template_plan`、`estimated_model_calls`、previews。
- 质量校验：正式 field_name、中文字段含中文、consistency_checks 写入 reasoning_summary。
- 只读 API：`GET /api/llm-extraction/field-completion/prompt-templates`。

### 前端

- `MultiTargetFieldCompletionModal` / `FieldCompletionModal` 新增折叠「提示词工作台」：prompt plan、key 选择、textarea 编辑、恢复默认、prompt_overrides 提交。

### 约束

- 不写正式库 / final_* / kg_*；无 migration；自动测试 mock provider。
- `pytest tests/test_llm_field_completion.py -q`：62 passed；`npm run build` 通过。

---

## Step 10.5.8 — Token-efficient Field Completion and Deterministic Canonical Region Resolver (2026-06-22)

### 任务名
Token-efficient Field Completion and Deterministic Canonical Region Resolver

### 后端

- 新增 `canonical_region_resolver.py`：`resolve_circuit_canonical_regions`、`resolve_region_candidate_to_canonical`；优先级：mirror_circuit_regions → payload circuit_regions → involved_region_candidate_ids → circuit_name → description。
- `field_completion_registry`：`deterministic_fields`（canonical_start/end → canonical_region_resolver；source_db / status → 默认 resolver）；不进入 DeepSeek prompt。
- `field_completion_execution.py`：先 deterministic resolver 写 overlay，再 batched LLM（同 target_type + field_name 批量 compact prompt）。
- `field_completion_prompt_engineering.py`：`build_compact_field_context`、`estimate_prompt_tokens`、`pack_target_batches`、`build_batch_field_prompt`；默认 input token budget 6000。
- `run_universal_field_completion`：summary 增加 `deterministic_applied_count`、`llm_applied_count`、`resolver_warning_count`、`estimated_input_tokens`、`pack_count`；dry_run preview 含 `deterministic_plan`、`deterministic_fields`、`llm_fields`、`compact_context_enabled`。
- completion item 审计：resolver 来源 `deterministic_canonical_region_resolver`；overlay meta 含 label / source。

### 前端

- Prompt Workbench：展示 deterministic / LLM 字段、estimated model calls、estimated input tokens、compact context 提示。
- Detail Drawer：canonical_start/end overlay 显示 label + short id；sort_order 推断方向时显示审核提示。

### 约束

- 不写正式库 macro_clinical.* / final_* / kg_*；无 migration；自动测试不调用真实 DeepSeek。
- `pytest tests/test_llm_field_completion.py -q`：71 passed；`npm run build` 通过。

---

## Step 10.6.1 — Circuit Function Mirror Foundation (2026-06-22)

### 任务名
Circuit Function Mirror Foundation

### 后端

- 新增 migration `033_mirror_circuit_functions.sql`：`mirror_circuit_functions` 表（正式字段 + Mirror 治理字段 + overlay JSONB）。
- 新增 `MirrorCircuitFunction` ORM model（`backend/app/models/mirror_macro_clinical.py`）。
- 新增 Pydantic schemas：`MirrorCircuitFunctionBase/Create/Update/Read/ListResponse`。
- 注册 model 于 `backend/app/models/__init__.py`。
- Decimal 字段在 Read schema 中 coerce 为 float，避免 JSON 序列化错误。

### 正式表 introspection

- 连接 dev 库中 **无** `macro_clinical` schema / `macro_clinical.circuit_function` 表。
- Mirror 字段对齐依据：`docs/DATA_CENTER_FORMAL_FIELD_ALIGNMENT.md` 文档化正式字段列表。

### 约束

- 不写正式库 / final_* / kg_*；**不自动执行 migration**。
- 本轮无 list/read API、无 Data Center、无 extraction、无 field completion registry、无 promotion。
- `pytest tests/test_mirror_circuit_function_foundation.py -q` 通过。

### 下一步

- Step 10.6.3：实现 circuit_to_functions LLM extraction service，将回路功能抽取结果写入 mirror_circuit_functions，不写正式库/final/kg。

---

## Step 10.6.2 — Circuit Function Mirror List API and Data Center Display (2026-06-22)

### 任务名
Circuit Function Mirror List API and Data Center Display

### 后端

- 新增 `GET /api/mirror-kg/circuit-functions` list API（filters: limit/offset/batch_id/resource_id/circuit_id/function_domain/function_role/effect_type/review_status/validation_status/promotion_status/mirror_status/status/q）。
- 新增 `GET /api/mirror-kg/circuit-functions/{id}` read API。
- `mirror_circuit_functions` 表未初始化时返回 HTTP 503 + `MIRROR_CIRCUIT_FUNCTIONS_NOT_INITIALIZED`（不裸 500）。
- `MirrorCircuitFunctionRead` Decimal 字段 JSON 安全；`attributes` 原样返回。
- 新增 `backend/tests/test_mirror_circuit_function_api.py`。

### 前端

- `endpoints.ts`：`listMirrorCircuitFunctions` / `getMirrorCircuitFunction`。
- Data Center Macro Clinical → Circuit Function tab 接入真实 Mirror 数据（`FormalObjectTableSection` + detail drawer + MissingFieldsBadge）。
- migration 未执行时显示黄色初始化提示（非“0 条数据”/非 planned empty）。
- `formalFieldMappings.ts`：`circuit_function.implemented = true`；i18n + CSS 初始化提示样式。

### 约束

- 不写正式库 / final_* / kg_*；**不自动执行 migration**；不调用 DeepSeek。
- 不实现 circuit_to_functions extraction；不启用 field_completion registry `supported=True`。
- `pytest tests/test_mirror_circuit_function_foundation.py -q`、`test_mirror_circuit_function_api.py -q`、`test_mirror_macro_clinical_schema.py -q` 通过；`npm run build` 通过。

### 下一步

- Step 10.6.4：启用 field_completion registry，让 circuit_function 支持字段补全。

---

## Step 10.6.3 — Circuit-to-Functions LLM Extraction Service (2026-06-22)

### 任务名
Circuit-to-Functions LLM Extraction Service to MirrorCircuitFunction

### 后端

- 新增 `POST /api/llm-extraction/circuit-to-functions`。
- 新增 `llm_circuit_function_extraction_service.py`：seed extraction、compact context、prompt、parse/validate、upsert/dedup。
- 新增 prompt template `circuit_to_functions_extraction_v1`。
- 写入 `mirror_circuit_functions`；`mirror_macro_clinical_service.create_circuit_function`。
- dry_run=true：prompt_preview + seed_count，不调用 provider、不写库。
- migration 033 未执行：503 `MIRROR_CIRCUIT_FUNCTIONS_NOT_INITIALIZED`。
- 新增 `backend/tests/test_llm_circuit_function_extraction.py`。

### 约束

- 不写正式库 / final_* / kg_*；不改 field_completion registry / related-targets / composite workflow / promotion。
- 自动测试 mock provider；用户 dry_run=false 时按 provider 配置调用 DeepSeek。

### 下一步

- Step 10.6.4：启用 circuit_function field completion registry。

---

## Step 10.6.4 — Enable Circuit Function Field Completion Registry and Bundle Related Targets (2026-06-22)

### 任务名
Enable Circuit Function Field Completion Registry and Bundle Related Targets

### 后端

- `field_completion_registry`：`target_type=circuit_function` **`supported=True`**；`model_class=MirrorCircuitFunction`。
- `allowed_fields` / `enrichable_fields` / `readonly_fields` / `direct_write_fields` / `overlay_write_fields` 对齐 `macro_clinical.circuit_function` 正式字段（function_term_cn/en、function_domain、function_role 等）。
- `llm_field_completion_service.load_targets`：从 `mirror_circuit_functions` 读取；migration 033 未执行返回 503 `MIRROR_CIRCUIT_FUNCTIONS_NOT_INITIALIZED`。
- `build_compact_field_context`：circuit_function 专用 compact context（不含完整 attributes/raw/normalized payload）。
- `select_field_completion_prompt_key`：function_term_cn/en、function_domain、function_role 等 prompt key；batch by target_type + field_name。
- `GET /field-completion/related-targets`：`include=circuit_function` 查询 `mirror_circuit_functions`；无数据时 warning「Run circuit_to_functions extraction first」，不再返回 not implemented。
- 测试：`test_llm_field_completion.py` 增补 registry / dry_run / mock write / related-targets / migration 503 覆盖。

### 前端

- `FieldCompletionModal` / Circuit Function tab：字段补全可用；`target_type=circuit_function`；正式字段 function_term_cn/en、function_domain、function_role 等。
- `circuitBundleUtils` / `MultiTargetFieldCompletionModal`：circuit_function 不再 unavailable；0 ids 显示「先执行 circuit_to_functions 抽取」；migration 未初始化显示 033 提示。
- `PromptWorkbenchSection`：Bundle dry_run preview 显示 circuit_function prompts（function_term_cn 等）、estimated_model_calls、compact context。

### 约束

- 不写正式库 / final_* / kg_*；不改 composite workflow / promotion / export。
- 自动测试 mock provider；dry_run=true 不调用 DeepSeek；用户 dry_run=false 手动执行时按 provider 调用。

### 下一步

- Step 10.6.5：把 circuit_to_functions 接入 composite workflow，让「提取回路 + 功能 + 步骤」自动执行 Circuit Function 抽取。

---

## Step 10.6.5 — Enable Circuit-to-Functions in Composite Workflow (2026-06-22)

### 任务名
Enable Circuit-to-Functions in Composite Workflow

### 后端

- `CIRCUIT_TO_FUNCTIONS_ENABLED=True`；`run_circuit_with_function_steps_workflow` 在 circuit_steps 后调用 `run_circuit_to_functions_extraction`。
- `circuit_ids` 来自 extract_circuits 步骤（strict resolve：created_ids / llm_run_id，不随机拉全库）。
- dry_run=true：circuit_to_functions dry_run preview，不写 mirror；step succeeded + warning。
- dry_run=false：写 `mirror_circuit_functions`；step response 含 `created_targets`（target_type=circuit_function）。
- workflow 顶层 `created_targets` / `result_summary.created_targets` 汇总 circuit + circuit_function。
- migration 033 未执行：step failed + `MIRROR_CIRCUIT_FUNCTIONS_NOT_INITIALIZED`，workflow 不裸 500。
- 新增 `backend/tests/test_llm_composite_workflow_circuit_functions.py`。

### 前端

- `compositeExtractionRunner`：服务端 workflow 读取 `created_targets`；fallback 路径调用 `runCircuitToFunctionsExtraction`。
- `ExtractionResultModal`：显示 circuit_function created_count；migration / no-signal 友好提示；bundle 可携带 function ids。
- i18n：`llmExtraction.extractCircuitFunctions` 等；substep 标签去掉「计划中」。

### 约束

- 不写正式库 / final_* / kg_*；不改 promotion / field_completion registry / Data Center 架构。

### 下一步

- Step 10.6.6：Promotion 候选源改为真实 mirror_circuit_functions，替换 projection_function 替身，仍需人工审核后才能晋升。
- Step 10.6.7（初版）：Bundle 无 circuit_function 数据时可直接调用 circuit-to-functions 抽取；Prompt Workbench 改为中英文双名称；Prompt 增加神经科学专家角色设定；保持 token-efficient；不写正式库/final/kg。
- Step 10.6.7（重构）：Refactor Circuit Function Extraction into LLM Extraction Center — 从 Bundle 字段补全弹窗移除所有抽取逻辑；no_data 改为"前往 LLM 提取中心"跳转；新增 GET /api/llm-extraction/prompt-templates 区分 extraction/field completion prompt；LLM 提取中心增加 CircuitToFunctionsPendingBanner。

---

## Step 10.6.6 — Circuit Function Promotion Candidate Source from MirrorCircuitFunction (2026-06-22)

### 完成内容

1. **Promotion 候选源 registry**：`circuit_function` → `mirror_circuit_functions` → `macro_clinical.circuit_function`（`macro_clinical_promotion_candidate_service.PROMOTION_SOURCE_REGISTRY`）。
2. **替换 projection_function 替身**：`final_macro_clinical_promotion_service.collect_promotion_candidates` 与 duplicate 检测改为 `MirrorCircuitFunction`；`promote_circuit_function` 不再从 projection_function 推导。
3. **Candidate list / preview API**：
   - `GET /api/mirror-kg/promotion-candidates?target_type=circuit_function`
   - `GET /api/mirror-kg/promotion-candidates/circuit_function/{id}/preview`
   - `POST .../promote` 返回 `REVIEW_REQUIRED` / `FORMAL_CIRCUIT_FUNCTION_TABLE_NOT_INITIALIZED` / `CIRCUIT_FUNCTION_PROMOTION_NOT_ENABLED`
4. **Readiness 规则**：blocked / needs_review / ready；pending 不可 actual promote。
5. **Data Center**：Circuit Function 详情 drawer 增加「晋升候选预览」区（formal_payload_preview + readiness + warnings）。
6. **migration 033 未执行**：503 `MIRROR_CIRCUIT_FUNCTIONS_NOT_INITIALIZED` 友好提示。

### 约束（本轮仍遵守）

- 不写 `macro_clinical.circuit_function` / final_* / kg_*；不自动审核；不调用 DeepSeek；`promote_circuit_function` 与 POST promote 均 gate 为 preview-only。

### 测试

- `tests/test_circuit_function_promotion_candidate_source.py`（13 cases）
- 与 10.6.2–10.6.5 相关 pytest 一并通过（114 passed）

### 下一步

- 人工审核队列：circuit_function 候选从 needs_review → approved 后，再实现受控正式库晋升。

---

## Step 10.6.7 — Bundle Auto Circuit Function Extraction and Bilingual Prompt Engineering (2026-06-22)

### 完成内容

1. **Bundle no_data → 抽取入口**：
   - `MultiTargetFieldCompletionModal` 检测 `circuit_function` 组为 `no_data` 时，显示抽取面板（`bundleExtractCircuitFunctions`）。
   - 提供「Dry Run 抽取回路功能」和「执行抽取回路功能」按钮，直接调用已有 `POST /api/llm-extraction/circuit-to-functions`（不新增 API）。
   - Dry Run：不调用 DeepSeek，不写库，展示 `estimated_model_calls`、`estimated_input_tokens`、`prompt_preview`。
   - Execute：写 `mirror_circuit_functions`，自动刷新 related-targets，`circuit_function` 组切换为 `pending`。
2. **Bundle 自动抽取 checkbox**：「无 Circuit Function 数据时，先自动抽取回路功能」（默认启用，执行 Bundle 时先抽取再字段补全）。
3. **token 消耗提示**：extraction panel 显示估算调用次数和 tokens，明确 Dry Run 不调用模型。
4. **migration 缺失 gate**：`isMigrationMissing` 时只显示初始化提示，不显示抽取按钮。
5. **Prompt Workbench 中英文双名称**：
   - `PROMPT_TEMPLATE_METADATA` 增加 `display_name` 字段。
   - `list_field_completion_prompt_template_items` 输出 `display_name`。
   - `FieldCompletionPromptTemplateItem` schema 增加 `display_name: str | None`。
   - `FieldCompletionPromptTemplate` TypeScript 接口增加 `display_name: string | null`。
   - Prompt 选择器显示「中文名（English Name）[key]」。
   - Prompt Preview 表格的 `prompt_key` 列 hover title 显示原始 key，内容显示 display_name。
6. **神经科学专家角色设定**（`llm_prompt_defaults.py`）：
   - `circuit_to_functions_extraction_v1`：system_prompt 更换为完整神经科学家角色 + 抽取约束 + 禁止旧字段名。
   - `_FIELD_COMPLETION_ROLE`：更换为神经科学家角色 + "只补全当前字段，不输出旧字段名" 约束。
7. **Circuit function 字段补全质量约束**（`_CF_QUALITY_CONSTRAINTS`）：
   - 4个 circuit_function 字段补全 prompt 均加入完整输出质量约束（CN/EN 双名、domain 简洁、role 描述、score 范围、evidence_level 枚举、不写 function_association、不晋升正式库）。
8. **warning normalizer 持续生效**（Step 10.6.6 已加，本轮复用）：旧 "not implemented yet" → 统一 i18n 提示。

### 约束（本轮遵守）

- 不写 `macro_clinical.circuit_function` / final_* / kg_*；不自动审核；不自动晋升；
- 自动测试不调用真实 DeepSeek；dry_run 不调用 provider；
- 只有用户点击「执行抽取」或 Bundle execute + checkbox=true 时才调用 provider；
- migration 033 未执行时显示初始化提示，不显示抽取按钮。

### 测试

- `tests/test_llm_circuit_function_extraction.py` + `tests/test_llm_field_completion.py`：90 passed
- Frontend: TypeScript 0 错误，Vite build 成功

### 下一步

- 人工审核队列：把 Circuit Function 抽取和补全结果统一进入 needs_review，审核通过后再允许受控晋升。

---

## Step 10.6.7 (Refactor) — Refactor Circuit Function Extraction into LLM Extraction Center (2026-06-22)

### 完成内容

1. **Bundle 字段补全弹窗（MultiTargetFieldCompletionModal）移除所有抽取逻辑**：
   - 移除 `runCircuitToFunctionsExtraction` 调用、`autoExtractEnabled` checkbox、蓝色抽取面板、Dry Run/Execute 按钮。
   - `runBundle` 不再自动调用 circuit_to_functions。
   - circuit_function group 只处理已有 target_ids。

2. **no_data 状态改为引导至 LLM 提取中心**：
   - 显示"无 Circuit Function 数据：请先到 LLM 提取中心执行 circuit_to_functions 抽取..."（i18n: `bundleCfNoDataTitle` / `bundleCfNoDataDesc`）。
   - 「前往 LLM 提取中心」按钮写入 `sessionStorage.pendingCircuitFunctionExtractionCircuitIds` 后跳转 `#/llm-extraction`。
   - 「刷新关联对象」按钮重新调用 `related-targets`，有数据则变为 pending。

3. **Prompt Workbench 拆分**：
   - `field_completion_prompt_engineering.py` 中 `PROMPT_TEMPLATE_METADATA` 移除 `circuit_to_functions_extraction_v1`（不混入字段补全 Workbench）。
   - 新增 `EXTRACTION_PROMPT_METADATA` + `list_extraction_prompt_template_items()`（含 `circuit_to_functions_extraction_v1`、`circuit_to_steps_v1`、`same_granularity_circuit_completion_v1`）。

4. **后端新增 extraction prompt templates API**：
   - `GET /api/llm-extraction/prompt-templates?category=extraction`
   - 返回 `ExtractionPromptTemplateListResponse`，包含 `display_name`（中英文双名称）、`category`、`description`。
   - Schema：`ExtractionPromptTemplateItem` / `ExtractionPromptTemplateListResponse`。

5. **前端 API**：
   - `endpoints.ts` 新增 `ExtractionPromptTemplate` 接口和 `getExtractionPromptTemplates()` 函数。

6. **LLM 提取中心新增 CircuitToFunctionsPendingBanner**：
   - 读取 `sessionStorage.pendingCircuitFunctionExtractionCircuitIds`，显示蓝色提示条。
   - 提示用户选择 composite workflow 或直接运行 circuit_to_functions 抽取。

### 约束（本轮遵守）

- 不写正式库 / final_* / kg_*；不自动审核；不自动晋升。
- 字段补全弹窗不直接调用 DeepSeek。
- 不删除 circuit_to_functions API；不删除 composite workflow；不删除 circuit_function 字段补全。
- migration 033 未执行时继续显示初始化提示（`isMigrationMissing`）。
- no_data 与 migration missing 保持区分。

### 测试

- `tests/test_llm_circuit_function_extraction.py`：13 passed
- `tests/test_llm_field_completion.py`（新增分离测试）：90 passed（4 pre-existing unrelated failures not introduced by this step）
- Frontend: TypeScript 0 错误，Vite build 成功

### 下一步建议

继续做 LLM 提取中心的「回路/步骤/功能」统一任务配置面板，让三类抽取共享 provider、token estimate、prompt override 和 created_targets 结果汇总。

---

## Step 10.6.8 — Composite Workflow Optional UUID Normalization (2026-06-22)

### 完成内容

1. **修复 composite workflow start 422**：
   - 根因：前端 `useSessionScope` 未设置 resource 时发送 `resource_id: ""`，Pydantic 在 handler 之前校验失败。
   - 这不是 DeepSeek 或 workflow 业务错误，而是请求参数校验错误。

2. **后端 schema 防御**（`backend/app/schemas/llm_composite_workflow.py`）：
   - `CompositeWorkflowRunRequest` 增加 `@field_validator`：`resource_id` / `batch_id` 空字符串 → `None`。
   - `candidate_ids` 过滤空字符串；非法非空 UUID 仍返回 422。
   - `source_atlas` / `granularity_level` 等 optional 字符串空值 → `None`。

3. **前端 payload 清理**（`frontend/src/api/payloadUtils.ts` + `endpoints.ts`）：
   - 新增 `normalizeOptionalUuid`、`filterNonEmptyIds`、`omitUndefined`。
   - `startCompositeWorkflow` / `runCompositeWorkflow` 发送前调用 `normalizeCompositeWorkflowPayload`。
   - 未选择 resource 时 `resource_id` 字段被省略，不再发送 `""`。

4. **422 错误 UX**（`compositeExtractionRunner.ts`）：
   - `formatValidation422Message` 识别 `resource_id` / `batch_id` 校验失败，显示清晰中文提示。

### 约束（本轮遵守）

- 不改 DeepSeek provider；不改 workflow 业务逻辑；不写正式库 / final_* / kg_*；不自动审核 / 晋升 / export。

### 测试

- `tests/test_llm_composite_workflow_request_validation.py`：8 passed
- `tests/test_llm_composite_workflow.py`：23 passed
- Frontend: TypeScript 0 错误，Vite build 成功

### 下一步建议

重新执行 connection_with_function workflow；若不再 422，再根据新的业务错误或抽取结果继续修复。

---

## Step 10.6.9 — Connection and Projection Function Prompt Engineering (2026-06-22)

### 完成内容

1. **connection / projection extraction prompt 工程**（`llm_prompt_defaults.py`）：
   - `same_granularity_connection_completion_v1` 加入神经科学家/连接组专家角色；
   - 要求逐 pair 输出 `projections` 或 `no_connections`；禁止无 pair_id 的 projection；
   - 输出对齐 mirror_region_connections / macro_clinical.projection；不写正式库/final/kg。

2. **projection_function extraction prompt 工程**：
   - `projection_to_functions_v1` 加入脑区连接功能专家角色；
   - 强调 function_term_cn/en、function_domain、function_role、evidence_level 约束；
   - 只能基于已有 projection_id 生成 projection_function。

3. **compact pair context + pack 拆分**（`llm_extraction_prompt_engineering.py` + `llm_connection_extraction_service.py`）：
   - 每个 pair 只传 compact 字段（pair_id、region names、granularity、atlas）；
   - 4560 pairs 按 pack 拆分（DEFAULT_PAIRS_PER_PACK=40），不截断总任务；
   - dry_run / execute 返回 `prompt_preview`（含 prompt_key、prompt_display_name、pack_count、token estimate）。

4. **provider 返回校验**：
   - 缺少 pair_id / 未知 pair_id 的 projection 被 rejected；
   - 未返回的 pair 计入 `unprocessed_pair_count`；
   - `output_count=0` 且无 no_connections → failed；全部 no_connections → `succeeded_no_edges`。

5. **display_name 中英文双名称**（EXTRACTION_PROMPT_METADATA）：
   - same_granularity_connection_completion_v1、projection_to_functions_v1、connection_with_function。

6. **composite workflow** 连接步骤根据 `result.status` / `unprocessed_pair_count` 判定，不再空返回即 succeeded。

### 约束

- 不写正式库 / final_* / kg_*；自动测试不调用真实 DeepSeek。

### 测试

- `tests/test_llm_connection_prompt_engineering.py`：13 passed
- `tests/test_llm_connection_extraction.py` + `tests/test_llm_composite_workflow.py`：36 passed

### 下一步建议

重新执行 connection_with_function workflow，确认 pack 进度、created_targets 与 projection_function 步骤衔接正常。

---

## Step 10.6.10 — Connection Workflow Provider Call Execution Fix (2026-06-22)

### 完成内容

1. **修复 connection_with_function 未真正调用 provider 的判定与阻断**：
   - `ConnectionExecutionAudit` 记录 `provider_call_count`、`prompt_sent_count`、`pack_summaries` 等 14 项指标；
   - 写入 `run.scope_json.execution_summary`、`item.prompt_json.pack_traces`、`ConnectionExtractionResult.execution_summary`；
   - `dry_run=false` 且 `pair_count>0` 时 `provider_call_count=0` → `failed_provider_not_called`（不再 succeeded）。

2. **provider 空返回 vs 未调用 vs all no_connections 区分**：
   - 未调用：`failed_provider_not_called`；
   - 已调用但空/不可解析：`failed_provider_empty_response` / `failed_parse_error`；
   - 全部 no_connections：`succeeded_no_edges`；
   - `output_count` 仅计 mirror 新建连接数。

3. **composite workflow 状态修正**：
   - projection step 依赖失败 → `skipped_dependency_failed`；
   - 无连接 → workflow `no_edges`，fn step `skipped_no_projection`；
   - provider 失败不再显示 step succeeded + workflow partially_succeeded。

4. **created_connection_ids** 从 persist 返回，供 projection_function step 使用。

5. **前端 ExtractionResultModal** 展示 provider 调用审计与红/黄/绿文案区分。

6. **测试**：`tests/test_connection_with_function_provider_call.py`（mock provider，不调用真实 DeepSeek）。

### 约束

- 不写正式库 / final_* / kg_*；不自动审核/晋升/export。

### 下一步建议

重新执行 connection_with_function workflow；先看 `provider_call_count` 是否大于 0，再判断是 prompt 太保守、模型空返回，还是 mirror 写入失败。

---

## Step 10.6.11 — Cancelable LLM Extraction Workflow and Current-run Cleanup (2026-06-23)

### 完成内容

1. **Cancel API**：`POST /api/llm-extraction/composite-workflows/{workflow_run_id}/cancel`（`cleanup=true` 时清理本轮 Mirror 候选）。
2. **Cancel registry**：进程内 `mark_cancelling` / `is_cancelling` / `cancel_tasks`；pack 调度前、provider 返回后、DB 写入前检查取消。
3. **Cleanup service**：`cleanup_composite_workflow_artifacts` 按 `attributes.composite_workflow_run_id` 与 step `llm_run_id` 删除本轮 mirror_* / 标记 llm trace cancelled；保留 composite workflow 审计记录。
4. **Mirror 标记**：写入 `raw_payload_json.attributes.composite_workflow_run_id`（无 migration）。
5. **前端**：运行中关闭弹窗 → 确认「取消本轮并清空」→ 调用 cancel API；展示 cancelling / cleanup_done / cleanup_failed 与重试清理。

### 约束

- 不写正式库 / final_* / kg_*；不按 batch_id 粗暴删除；自动测试不调用真实 DeepSeek。

### 下一步建议

实现真正的「暂停 / 继续」机制，用持久化 pack 状态恢复未完成的 provider packs。

---

## Step 10.6.12 — Fix Duplicate commit_progress in Step Status Update (2026-06-23)

### 完成内容

1. **修复** `_connection_progress` 向 `_us()` 重复传入 `commit_progress`，导致 `update_workflow_step_status() got multiple values for keyword argument 'commit_progress'`。
2. **`_sanitize_step_update_kwargs`**：从 step update kwargs 剥离控制参数 `commit_progress`。
3. connection_with_function 可继续进入 provider 调用链；provider_call_count 审计与依赖跳过规则不变。

### 约束

- 不写正式库 / final_* / kg_*。

## Step 10.6.13 — Robust Workflow Cancellation, Provider Execution, Cleanup Race Fix, and Result Modal State Machine (2026-06-23)

### 问题定位

1. **关闭后弹窗反复出现**：`pollCompositeWorkflowRun` 的 `TERMINAL_WORKFLOW_STATUSES` 仅包含 `succeeded/partially_succeeded/failed/dry_run`，`cleanup_done`/`cancelled`/`no_edges` 不在其中 → 轮询 `while(true)` 永不退出，每次 `onProgress` 都用 `prev ?? {默认}` 重建 modal，导致关闭后被重新弹出。
2. **cleanup_done 被显示为成功**：`onProgress` 从不写入 `status`，初始 modal 默认 `status:'succeeded'`，所以卡片一直显示“成功”；`mapServerStatus` 对 `cleanup_done` 落到默认分支。
3. **StaleDataError 直接原因**：`cleanup_composite_workflow_artifacts` 物理 `delete(LlmExtractionItem)`，后台 provider/step task 之后再 flush UPDATE 该行 → `expected to update 1 row(s); 0 were matched`。
4. **provider_call_count=0**：截图为用户极早取消（pack 循环第 0 次即 break），属于“用户主动取消”场景，而非 bug；状态机需区分。

### 后端修复

1. **cleanup 不再物理删除 trace**：`llm_extraction_items` 改为 `UPDATE status=cancelled`（行仍存在，后台 ORM UPDATE 仍匹配 1 行），`llm_extraction_runs`/`steps`/`runs` 标记 cancelled/cleanup_done；仅 `mirror_*` 候选物理删除（按 `attributes.composite_workflow_run_id` 精准匹配，禁止按 batch_id）。
2. **`LlmItemStatus.cancelled`** 新增。
3. **StaleDataError 防御**：`update_workflow_step_status`、connection extraction `_emit_progress`/取消提交/最终提交均 `try/except StaleDataError`：若 `is_cancelling` 则 warning + rollback 忽略；否则继续抛出。
4. **`is_workflow_cancelled_or_cancelling(session, id)`**：in-process registry + 持久化 run 状态双重判断。
5. **cancel API 幂等**：run 已处于 `cleanup_done/cleanup_failed/cancelled` 时直接返回当前状态与 deleted，不重复清理。
6. **provider_call_count 状态机**：取消 → cancelled/cleanup_done（call_count 可为 0，不报 failed_provider_not_called）；未取消且 call_count=0 → failed_provider_not_called（由 `finalize_connection_extraction_status` 处理）。

### 前端修复

1. **`dismissedWorkflowRunIds`（ref + sessionStorage）**：关闭/取消成功后写入；`onProgress` 与最终结果 setter 中 `prev === null` 直接返回 null，且 dismissed run 不再自动打开。
2. **`TERMINAL_WORKFLOW_STATUSES`** 补全 cancelled/cleanup_done/cleanup_failed/no_edges/failed_* 等，轮询正确终止。
3. **`mapServerStatus`** 映射 cancelling/cancelled→cancelled、cleanup_*→cleanup_done/cleanup_failed、no_edges、failed_provider_not_called。
4. **状态显示修正**：`resolveDisplayStatus` 优先采用后端权威 workflowStatus（取消/清理/失败类），`cleanup_done`→“已取消并清理”，禁止显示成功。
5. **Provider 审计增强**：新增 `prompt_sent_count`、`late_provider_response_ignored`；按状态输出诊断文案（未真正调用模型 / 已取消并清理 / late response ignored / 解析失败 / 无连接）。
6. **关闭按钮**：运行中点击 → 取消确认弹窗 → `cancelCompositeWorkflow(cleanup:true)` → cleanup_done 后关闭、停止轮询、不再弹出；已结束点击 → 仅关闭并 dismiss。

### 是否实现暂停

未实现“暂停/恢复”。本轮实现的是“取消本轮 + 清理 + 防重复弹窗 + late task 忽略”。

### 测试

- backend：`test_composite_workflow_cancel_cleanup.py`(+幂等/不物理删 item/helper)、`test_connection_with_function_provider_call.py`、`test_llm_composite_workflow_status_update.py`、`test_llm_composite_workflow*.py` 全部通过。
- frontend：`npm run build` TS 0 错误，Vite 构建成功。

### 约束

- 不写正式库 / final_* / kg_*；不自动审核 / 晋升 / export；自动测试不调用真实 DeepSeek。

## Step 10.6.14 — Fix DeepSeek Response Parsing for Connection Extraction (2026-06-23)

### 问题定位

- provider 已被调用（provider_call_count=3、prompt_sent_count=3），不是“未调用”。
- 返回内容无法解析：连接抽取 pack 循环里 parse 失败时同时 `parse_error_count += 1` 且 `provider_error_count += 1`，`finalize` 又先判 `provider_error_count>0 and provider_success_count==0 → failed_provider_error`，把 parse error 混成了 transport/provider error。
- 原 parser（`parse_llm_json_response`）只做最朴素的 fence/首尾大括号截取，对 **截断 JSON**（40 pairs/pack × 完整 schema 超过 max_tokens=4000，DeepSeek 输出被截断）无能为力；也没有保存 raw_response_preview 供调试。

### 后端修复

1. **`llm_json_utils` 重写**：`parse_llm_json_response` 接受 dict/list/message-obj/str；新增 `extract_json_object_from_text`（fenced → 平衡大括号 object → 平衡中括号 array → 截断 salvage）、`_repair_json_text`（尾随逗号 + 常见全角标点）、`raw_response_preview`（≤2000 字符）。新增 `LlmJsonParseError(json.JSONDecodeError)`，带 `preview`/`error_type`，向后兼容旧 `except json.JSONDecodeError`。
2. **schema 兼容**：新增 `normalize_connection_extraction_payload`，支持 projections/projection/connections/edges/relations 别名、no_connection/no_edges 别名、顶层数组、并按 source/target 回补缺失 pair_id。
3. **parse vs transport 分离**：`ConnectionExecutionAudit` 新增 `provider_transport_error_count`、`schema_error_count`、`rejected_item_count`。规则：transport error → transport_error_count；收到内容即 `provider_success_count+=1`；JSON 解析失败 → 只 `parse_error_count+=1`；schema 不符 → `schema_error_count+=1`。
4. **raw_response_preview**：每个 pack trace 记录 pack_id/provider/model/prompt_display_name/response_char_count/raw_response_preview/parse_error/parse_error_type/parsed_counts/rejected_item_count。
5. **prompt 加严**：connection prompt 增加“只输出一个 JSON object / 不要 Markdown / 不要解释文字 / 顶层只含 projections,no_connections,warnings”；projection_function prompt 同步加“只输出一个 JSON object / 每个必须带 projection_id”。
6. **JSON mode**：DeepSeek provider 已使用 `response_format={"type":"json_object"}`（capability 已具备，未改动通用 abstraction，不影响 Kimi）。
7. **截断缓解**：connection 默认 `max_tokens` 4000 → 8000，降低大 pack JSON 截断概率。
8. **workflow 状态**：`finalize_connection_extraction_status` 用 `provider_transport_error_count` 判 failed_provider_error；`parse_error_count`/`schema_error_count`>0 且无产出 → failed_parse_error；全 no_connections → succeeded_no_edges；projection_function parse 失败 → failed_parse_error。

### 前端修复

- Provider 调用审计新增 provider_transport_error_count / parse_error_count / schema_error_count / rejected_item_count；新增可折叠 `FailedPackPreviews`（展示每个失败 pack 的 parse_error 与 raw_response_preview）。
- 诊断文案区分：parse/schema 错误→“返回内容无法解析为要求的 JSON，请展开 raw response preview”；transport 错误→“传输失败，请检查网络/Key/限流”。

### 测试

- backend：新增 `tests/test_llm_json_utils.py`（纯 JSON / fenced / 前后文字 / 截断 salvage / 别名 / pair_id 回补 / 不可解析 raise）；`tests/test_connection_with_function_provider_call.py` 增加 markdown 解析、parse vs transport 分离、status=failed_parse_error。全部通过。
- frontend：`npm run build` 通过（TS 0 错误）。
- 备注：仓库中存在 11 个与本任务无关的既有失败（field_completion overlay、circuit_projection max_projections、projection API 校验码、max_functions 归一化），均不在本次改动模块内。

### 约束

- 不写正式库 / final_* / kg_*；不自动审核 / 晋升 / export；不做第二次 LLM repair；自动测试不调用真实 DeepSeek。

## Step 10.6.15 — Fix LLM Extraction Frontend Runtime ReferenceErrors (2026-06-23)

### 问题

- `LlmExtractionPage.tsx`：`dismissedWorkflowRunIdsRef` 使用 `useRef` 但未从 `react` 导入 → 浏览器 `ReferenceError: useRef is not defined`。
- `ExtractionResultModal.tsx`：JSX 引用 `displayStatus` 但变量未定义/命名不一致 → `ReferenceError: displayStatus is not defined`。

### 修复

1. `LlmExtractionPage.tsx`：`import { ..., useRef } from 'react'`。
2. `ExtractionResultModal.tsx`：统一为 `getWorkflowDisplayStatus(data)` 返回 `{ status, label, tone }`；JSX 使用 `displayStatus.label` / `displayStatus.tone`；`cleanup_done` → “已取消并清理”（muted），不再显示为成功。
3. `styles.css`：补充 tone 与 cleanup/cancel/parse 状态样式。

### 测试

- `npm run build` 通过（TS 0 错误）。

## Step 10.6.16 — Provider Scheduling Diagnostics, Runtime Logs, and Premature Warning Fix (2026-06-23)

### 问题

- workflow `running` 初期（pack 构建 / 调度阶段）`provider_call_count=0` 时，前端 `ExtractionResultModal` 立即显示红色“未真正调用模型”。
- 提取过程中的 pack 调度、provider 调用、parse error 等后端事件未进入前端日志控制台，无法诊断 provider 是未调度、排队、传输失败还是 parser 失败。

### 后端修复

1. 新增 `llm_workflow_event_log.py`：`append_workflow_event` 写入 `workflow_run.result_summary_json.events`（最多存 200 条，API 返回最近 50 条）；脱敏 API key，截断 `raw_response_preview`/`prompt_preview`。
2. `llm_connection_extraction_service.py` 关键路径打事件：`pairs_generated`、`packs_built`、`prompt_built`、`provider_call_start/success/transport_error/empty_response`、`provider_response_parse_error/schema_error/parsed`、`projections_created`、`provider_not_called`、`late_provider_response_ignored`。
3. `llm_composite_workflow_service.py`：workflow status / run read 返回 `recent_events`；`_connection_progress` 在 running 超过 60s 且仍无 prompt/provider 调用时打 `provider_scheduling_delayed`（warning，不终止任务）；`finalize_workflow_run` 保留已有 events。
4. `failed_provider_not_called` 仍仅在 step 终态由 `finalize_connection_extraction_status` 判定；running 中不设失败。

### 前端修复

1. `resolveProviderAudit`：running + `provider_call_count=0` → 蓝色 info“正在构建 pack / 等待调度”；超过 60s 无 prompt → 黄色 warning；红色“未真正调用模型”仅在终态 failed / `failed_provider_not_called` / 非 cancelled 的 step 结束。
2. `ExtractionResultModal` 新增可折叠 **Workflow Events** 面板（error 自动展开）；audit 区按 tone 着色，不再因 `provider_call_count=0` 一律红色。
3. `compositeExtractionRunner` polling 将 `recent_events` 经 `emitWorkbenchLog` 写入日志控制台（`event_id` 去重）；`LlmExtractionPage` 同步 `recentEvents` 到弹窗。

### 测试

- `tests/test_llm_workflow_events.py`（events 记录、脱敏、recent_events、终态 failed_provider_not_called、cancel 不 failed）。
- `tests/test_connection_with_function_provider_call.py`、`tests/test_llm_composite_workflow*.py` 通过。
- `npm run build` 通过。

### 约束

- 不写正式库 / final_* / kg_*；不自动审核 / 晋升 / export；自动测试不调用真实 DeepSeek。

## Step 10.6.17 — Separate Persistent Run Status from Semantic Workflow Outcome (2026-06-23)

### 问题

- `connection_with_function` 在模型已调用、解析成功、全部 pair 判为 `no_connection` 后，后端尝试写入 `llm_extraction_runs.status='succeeded_no_edges'`，触发 PostgreSQL `chk_llm_extraction_run_status` CHECK 失败。
- workflow 被错误标记 `failed`，`projection_function` 显示 `skipped_dependency_failed`（Step 1 并未失败）。

### 根因

- 业务语义状态（`succeeded_no_edges`、`failed_parse_error` 等）被直接写入 DB `status` 列；而 `llm_extraction_runs.status` 仅允许：`created` / `running` / `succeeded` / `partially_succeeded` / `failed` / `cancelled`。
- 语义 outcome 应写入 `scope_json.outcome` / `display_status` / `semantic_status`（API 层）；composite workflow 写入 `result_summary_json`。

### 后端修复

1. 新增 `llm_status_utils.py`：`map_semantic_outcome_to_persistent_run_status()`、`apply_persistent_run_status()`、`is_semantic_failure()`、`is_semantic_no_edges()`。
2. `llm_connection_extraction_service.py`：no_edges 时 `run.status=succeeded`，`scope_json.outcome=succeeded_no_edges`，`has_edges=false`，`no_connection_count` 写入 scope。
3. `llm_composite_workflow_service.py`：no_edges workflow `status=succeeded`，`result_summary_json.outcome=succeeded_no_edges`；fn step `skipped_no_projection`（非 dependency failed）；日志改为 “Connection extraction completed with no projections; skipping projection function extraction.”
4. `llm_projection_function_extraction_service.py`：非法细分 status 改走 `apply_persistent_run_status()`。
5. API response 增加 `outcome` / `display_status` / `semantic_status`；DB `status` 始终合法。

### 前端修复

1. `compositeExtractionRunner`：`resolveWorkflowSemanticStatus()` 优先级 `display_status → outcome → semantic_status → status`；polling / 完成态传递 `workflowOutcome`。
2. `ExtractionResultModal`：`getWorkflowDisplayStatus` 优先 semantic outcome；`succeeded_no_edges` → “未生成连接”（warning）；`skipped_no_projection` → “无连接可提取功能”（muted）；`cleanup_done` 不显示成功。
3. running 阶段 `provider_call_count=0` 不因 no_edges 终态误报红色失败。

### 测试

- `tests/test_llm_status_mapping.py`（CHECK 允许值映射、no_edges 不写非法 status、scope_json.outcome）。
- `tests/test_connection_with_function_provider_call.py`、`tests/test_llm_composite_workflow*.py` 通过（68 passed）。
- `test_connection_with_function_workflow.py`：未发现（覆盖在 status_mapping + provider_call 测试中）。
- `npm run build` 通过。

### 约束

- **未修改**数据库 CHECK 约束；不写正式库 / final_* / kg_*；不自动审核 / 晋升 / export；自动测试不调用真实 DeepSeek。

## Step 10.6.18 — Fix DeepSeek JSON Parse Failures in Connection Extraction (2026-06-23)

### 问题

- `connection_with_function` 已调用 DeepSeek（`provider_call_count>0`），但多个 pack 返回文本无法解析为 JSON（`parse_error_count` 增长），导致 projection / no_connection 处理无法进行。
- 运行中 `pack_summaries` 未及时写入 progress，前端无法展开 `raw_response_preview`；`provider_success_count` 与 `parse_error_count` 展示易混淆。

### 后端修复

1. **`llm_json_utils.py`**：增强 `extract_json_object_from_text`（BOM 清理、多 JSON 块、schema 关键字优选、截断修复）；新增 `normalize_connection_completion_payload` / `parse_connection_completion_response`；兼容 `links` / `no_relations`、顶层 array。
2. **`llm_connection_extraction_service.py`**：始终从 `raw_text` 解析（不依赖 provider 预解析）；progress 实时写入 `pack_summaries` + `raw_response_preview`；`provider_success_count` 与 `response_received_count` 对齐；pack 级 `max_tokens` 动态放大；parse 失败最多 retry 1 次 provider。
3. **`llm_extraction_prompt_engineering.py`**：字段别名（source_id / confidence / strength 等）；`failed_pack_count` 审计字段。
4. **`llm_providers/deepseek.py`**：默认 JSON mode，`response_format` 被拒时 fallback 普通模式并记录 `json_mode_enabled`。
5. Prompt（`same_granularity_connection_completion_v1` / `projection_to_functions_v1`）已含“只输出 JSON object、不要 Markdown”约束。

### 前端修复

1. **`ExtractionResultModal`**：解析失败详情面板（pack_id、parse_error、raw_response_preview）；`provider_success_count` 与 `parse_error_count` 分开展示；成功次数说明文案。
2. **`i18n.ts` / `styles.css`**：新增解析失败与 audit 说明字符串。

### 测试

- `tests/test_llm_json_utils.py`、`tests/test_connection_with_function_provider_call.py`、`tests/test_connection_with_function_workflow.py`（新建）通过。
- 81 passed（相关 llm extraction 套件）；`npm run build` 通过。

### 约束

- 不写正式库 / final_* / kg_*；不用第二个 LLM 修 JSON；自动测试不调用真实 DeepSeek。

## Step 10.6.19 — Force Raw Response Capture, Parse Replay, and Parse-error Fail-fast (2026-06-23)

### 问题

- `connection_with_function` 已调用 DeepSeek（`provider_call_count>0`），但每个 pack 均 `parse_error`；`pack_summaries=[]`，前端无法查看 `raw_response_preview`。
- `provider_success_count=0` 与 `parse_error_count>0` 并存，审计语义错误。
- 无 fail-fast，114 个 pack 持续消耗 token；progress callback 未稳定写入 pack traces。

### 后端修复

1. **`llm_providers/base.py` / `deepseek.py`**：`LlmProviderResponse` 统一 `raw_text` + `parsed_json` + `transport_ok`；HTTP 成功且有正文时 `raw_text` 必非空，JSON parse 失败也不丢 raw text。
2. **`llm_connection_parse_diagnostics.py`**（新）：`build_execution_summary`、`compact_pack_summaries`、`finalize_pack_trace`、`should_trigger_parse_fail_fast`、`replay_connection_parse_response`。
3. **`llm_connection_extraction_service.py`**：progress 三参 `(run, audit, summary)`；每 pack 必 append `pack_summary`（含 `raw_response_preview` ≤2000、`prompt_preview` ≤1000）；`provider_success_count` 与 `response_received_count` 对齐；前 3 个连续 parse_error 且 projection/no_connection 均为 0 时 fail-fast；`debug_single_pack` / `debug_max_packs` 限 pack 数。
4. **`llm_composite_workflow_service.py`**：`_connection_progress` 将 `pack_summaries` 写入 step `response_json` 顶层。
5. **`llm_extraction.py`**：`POST /api/llm-extraction/debug/parse-connection-response`（不调 provider、不写库）。
6. **`llm_prompt_defaults.py`**：加严“无连接也必须返回合法 JSON；禁止自然语言/Markdown”。
7. DeepSeek connection 调用默认 `response_format={"type":"json_object"}`，失败 fallback 并记录 `json_mode_enabled`。

### 前端修复

1. **`ExtractionResultModal`**：fail-fast 文案；`parse_error_count>0` 且 `pack_summaries` 为空时红色内部诊断；`provider_success_count` 说明 + 统计异常黄条；解析失败详情含 `raw_response_preview` 可展开。
2. **`i18n.ts`**：fail-fast / missing pack_summaries / audit anomaly 字符串。

### 测试

- `tests/test_connection_parse_diagnostics.py`（新）、`test_llm_json_utils.py`、`test_connection_with_function_provider_call.py`、`test_connection_with_function_workflow.py`：48 passed。
- `npm run build` 通过。

### 约束

- 不写正式库 / final_* / kg_*；不自动审核 / 晋升 / export；自动测试不调用真实 DeepSeek；不再盲跑 114 pack（先用 `debug_single_pack`）。

### 手动验证

1. `debug_single_pack=true` 或 `debug_max_packs=1`，`dry_run=false`，检查 `provider_call_count=1`、`pack_summaries[0].raw_response_preview`。
2. 根据 preview 修 prompt/parser/pack_size，再 `debug_max_packs=3` 小批量验证。

## Step 10.6.20 — Trace and Fix Raw Response Capture Persistence Chain (2026-06-23)

### 问题

- composite workflow 运行中 `provider_call_count` / `parse_error_count` 增长，但 `provider_success_count=0`、`pack_summaries=[]`，`raw_response_preview` 不可见。
- 根因：connection extraction 仍走 `complete_json`；pack trace 未在 raw_text 到达时立即 upsert；progress 未同步 `run.result_summary_json`；JSONB 未 `flag_modified`；前端只读 `execution_summary.pack_summaries` 单一路径。

### 后端修复

1. **`LlmProviderTextResult` + `complete_text`**（DeepSeek/Kimi）：raw_text-first，JSON parse 仅在 connection parser 层；`extract_raw_text_from_response` 多字段 fallback。
2. **`llm_connection_extraction_service.py`**：每 pack `try/finally` + `_persist_pack_trace`；`complete_text(json_mode=True)`；raw_text 到达即写 `raw_response_preview`；`reassign_jsonb` + `flag_modified`。
3. **`llm_connection_parse_diagnostics.py`**：`upsert_pack_trace`、`merge_provider_audit`、`validate_connection_progress_invariants`（`PACK_SUMMARIES_MISSING_FOR_PARSE_ERRORS` / `PROVIDER_SUCCESS_COUNT_INCONSISTENT`）。
4. **`llm_composite_workflow_service.py`**：progress 同步 `provider_audit` + `pack_summaries` 到 step `response_json` 与 `run.result_summary_json`；`_step_read` / `_run_read` 合并多路径；`flag_modified` on JSONB columns。

### 前端修复

1. **`resolvePackSummaries` 多路径读取**：`provider_audit` → `execution_summary` → `result_summary` → workflow events。
2. **composite 确认框**：`debug_single_pack` 勾选“调试模式：只运行 1 个 pack”。
3. **诊断 UI**：pack_summaries 缺失红色提示；fail-fast / audit anomaly 保留。

### 测试

- `tests/test_connection_raw_response_capture.py`（新）+ 相关套件 **52 passed**；`npm run build` 通过。

### 约束

- 不写正式库 / final_* / kg_*；自动测试不调用真实 DeepSeek；默认 debug_single_pack 避免盲跑 114 pack。
