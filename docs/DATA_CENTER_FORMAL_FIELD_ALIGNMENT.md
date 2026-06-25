# Data Center Formal Field Alignment

**Task:** Formal-field Data Center Display and Universal DeepSeek Field Completion Design  
**Step:** 10.1 — design; 10.2 UI; 10.3 backend API; 10.4 UI wired; **10.4.1 Real schema alignment (2026-06-17)**  
**Date:** 2026-06-17  
**Status:** Step 10.4.1 — Data Center columns now aligned to NeuroGraphIQ_KG_V3 real DB schema (introspected)

## ⚠️ Step 10.4.1 — Real Formal Schema Alignment

**Date:** 2026-06-17  
**Trigger:** User confirmed formal DB is `NeuroGraphIQ_KG_V3`. Previous `final_region_circuits`, `final_projections` etc. do not exist in the real DB.

### Introspection Results (NeuroGraphIQ_KG_V3)

**Formal schemas discovered:** `macro_clinical`, `fine_cyto`, `meso_anatomical`, `sub_connectivity`, `molecular_attr`  
**Data Center uses `macro_clinical` schema.**

#### macro_clinical.circuit
`id, species_id, canonical_start_region_id, canonical_end_region_id, data_source_id, primary_evidence_id, external_code, name_en, name_cn, circuit_class, description, remark, attributes, source_db, status, created_at, updated_at`

#### macro_clinical.projection
`id, species_id, source_region_id, target_region_id, data_source_id, primary_evidence_id, external_code, name_en, name_cn, projection_type, directionality, strength_score, confidence_score, evidence_level, description, remark, attributes, source_db, status, created_at, updated_at`

#### macro_clinical.circuit_step
`id, circuit_id, step_no, region_id, projection_id, data_source_id, primary_evidence_id, step_name_en, step_name_cn, role_in_circuit, description, remark, attributes, source_db, status, created_at, updated_at`

#### macro_clinical.projection_function
`id, projection_id, data_source_id, primary_evidence_id, external_code, function_term_en, function_term_cn, function_domain, function_role, effect_type, confidence_score, evidence_level, description, remark, attributes, source_db, status, created_at, updated_at`

#### macro_clinical.circuit_function
`id, circuit_id, data_source_id, primary_evidence_id, external_code, function_term_en, function_term_cn, function_domain, function_role, effect_type, confidence_score, evidence_level, description, remark, attributes, source_db, status, created_at, updated_at`

#### macro_clinical.region_function
`id, region_id, data_source_id, primary_evidence_id, external_code, function_term_en, function_term_cn, function_domain, confidence_score, evidence_level, description, remark, attributes, source_db, status, created_at, updated_at`

### Key Changes in formalFieldMappings.ts
- `formalSchema: 'macro_clinical'` added to all mappings
- `formalQualifiedName: 'macro_clinical.circuit'` etc. replaces guessed `final_region_circuits`
- `name_cn（中文名）`, `name_en（英文名）` columns added to circuit, projection
- `circuit_class（回路类别）` replaces `circuit_type` as formal field
- `circuit_step` columns updated: `step_no`, `step_name_en`, `step_name_cn`, `role_in_circuit`
- `projection_function` columns updated: `function_term_en`, `function_term_cn`
- Governance columns marked with `group: 'governance'`, separated in drawer
- `computeMissingFields` skips governance columns
- `FormalAlignmentCard` shows real `formalQualifiedName`
- `FormalObjectDetailDrawer` shows Formal Fields / Governance / Raw JSON sections

### mirror-only boundary
- Data source: Mirror candidate tables (`mirror_region_circuits`, `mirror_region_connections`, etc.)
- Formal alignment: `NeuroGraphIQ_KG_V3.macro_clinical.*` (display only)
- No writes to formal DB; no promotion; no final_* / kg_*

---

---

## 1. 设计目标

1. **数据中心（Data Center）** 中展示的所有 Mirror / Macro Clinical 提取结果，**列定义对齐正式库 final KG / final macro_clinical 字段语义**，使用户在候选层即可预览“晋升后将长什么样”。
2. Mirror 对象仍是 **候选知识层**，展示对齐 **不等于** 自动 promotion，也不写入 `final_*` / `kg_*`。
3. 为每一类对象预留 **missing fields 标记** 与 **字段补全（field completion）入口**（Step 10.2 起实现 UI，Step 10.3+ 实现 API）。
4. 最小侵入：本轮仅文档 + 前端 mapping 常量；不破坏现有 Data Center / LLM 提取功能。

---

## 2. 为什么 Data Center 要按 final KG 字段展示

| 问题 | 对齐后的收益 |
|------|----------------|
| 当前 Mirror 表格列过少（多为 id + status） | 用户无法判断提取结果是否“正式库就绪” |
| Mirror 与 Final 命名不一致（connection vs projection） | 统一展示 label，降低 promotion 前认知成本 |
| 缺少 governance 字段可见性 | review / validation / promotion 状态一屏可见 |
| 字段缺失不可见 | missing fields badge 驱动补全工作流 |

**原则：** Data Center = 数据资产只读浏览 + 轻量操作（Generate Candidates、字段补全）；LLM 提取页 = 抽取 / 验证 / 晋升工作流入口。

---

## 3. Mirror KG 与 Final KG 的边界

```
Candidate ──LLM extract──► Mirror_* ──validation/review──► Promotion ──► Final_* / kg_*
                              ▲
                              │ field completion (DeepSeek)
                              │ 只写 Mirror / candidate
```

| 层级 | 表前缀 | 语义 | Data Center 是否可写 |
|------|--------|------|---------------------|
| Candidate | `candidate_*` | 导入后候选脑区 | Generate Candidates |
| Mirror KG | `mirror_*` | LLM/人工候选事实 | 字段补全（mirror-only） |
| Mirror Macro Clinical | `mirror_circuit_steps` 等 | 宏观临床链路候选 | 字段补全（mirror-only） |
| Final KG | `final_region_*`, `final_kg_*` | 已晋升正式事实 | 只读 |
| Final Macro Clinical | `final_projections` 等 | 已晋升宏观临床 | 只读 |

**禁止：** 字段补全、Data Center 展示对齐、或 LLM 抽取结果 **直接** 写入 `final_*` / `kg_*`。

---

## 4. Mirror 对象仍是候选层，不是 final fact

- `mirror_status` 默认 `llm_suggested`；不等于 `final_status=active`。
- `promotion_status=not_promoted` 在 Mirror 层保持不变，直到用户走 Final Promotion 流程。
- 展示时使用 **正式库字段名** 作为列 header，数据来源仍为 Mirror API；必要时通过 join / 派生列填充（如 region_name）。

---

## 5. 字段展示对齐 final schema ≠ 自动 promotion

对齐仅影响 **UI 列定义、详情 drawer、missing field 检测**；promotion 仍在 `#/llm-extraction` Final 入口或专用 Promotion 页执行，且必须满足 validation + human review 门禁。

---

## 6. 对象类型清单

| # | Data Center 位置 | target_type | Mirror 表 | Final 对齐表 |
|---|------------------|-------------|-----------|--------------|
| 1 | Mirror KG → Connections | `projection` | `mirror_region_connections` | `final_projections` / `final_region_connections` |
| 2 | Mirror KG → Region Functions | `region_function` | `mirror_region_functions` | `final_region_functions` |
| 3 | Mirror KG → Circuits | `circuit` | `mirror_region_circuits` | `final_region_circuits` |
| 4 | Mirror KG → Triples | `triple` | `mirror_kg_triples` | `final_kg_triples` |
| 5 | Mirror KG → Evidence | `evidence` | `mirror_evidence_records` | `final_evidence_records` |
| 6 | Macro Clinical → Circuit Steps | `circuit_step` | `mirror_circuit_steps` | `final_circuit_steps` |
| 7 | Macro Clinical → Projection Functions | `projection_function` | `mirror_projection_functions` | `final_projection_functions` |
| 8 | Macro Clinical → Memberships | `circuit_projection_membership` | `mirror_circuit_projection_memberships` | `final_circuit_projection_memberships` |
| 9 | Macro Clinical → Circuit Functions | `circuit_function` | **`mirror_circuit_functions`** | `final_circuit_functions` |
| 10 | Candidates | `candidate_region` | `candidate_brain_regions` | N/A（晋升前） |

---

## 7. Mirror table → Final table 映射

### 7.1 连接 / Projection

| 展示列（final 语义） | Mirror 字段 | Final 字段 | 备注 |
|---------------------|-------------|------------|------|
| projection_id / connection_id | `id` | `id` / `final_uid` | Mirror 用 UUID |
| source_region_candidate_id | `source_region_candidate_id` | 同左 | |
| source_region_name | *join candidate* | *join* | 展示派生 |
| target_region_candidate_id | `target_region_candidate_id` | 同左 | |
| target_region_name | *join candidate* | *join* | |
| projection_type / connection_type | `connection_type` | `projection_type` | **列名用 projection_type** |
| directionality | `directionality` | 同左 | |
| strength | `strength` | 同左 | |
| modality | `modality` | 同左 | |
| evidence_summary | `evidence_text` | `evidence_text` | UI label 用 evidence_summary |
| confidence | `confidence` | 同左 | |
| source_atlas | `source_atlas` | 同左 | |
| granularity_level | `granularity_level` | 同左 | |
| granularity_family | `granularity_family` | 同左 | |
| mirror_status | `mirror_status` | — | Mirror only |
| review_status | `review_status` | — | |
| validation_status | *from latest validation run* | `validation_summary_json` | Mirror 无单列，Step 10.2 派生 |
| promotion_status | `promotion_status` | — | |
| provenance | `llm_run_id`, `llm_item_id`, `raw_payload_json` | `provenance_json` | drawer 聚合 |
| created_at | `created_at` | 同左 | |

**Mirror 缺少、Final 有：** `final_uid`, `validation_summary_json`, `review_summary_json`, `cross_validation_summary_json`, `dual_model_summary_json`（promotion 后才有意义；Mirror 展示占位或 “—”）。

### 7.2 连接功能 / Projection Function

| 展示列 | Mirror | Final |
|--------|--------|-------|
| projection_function_id | `id` | `id` |
| projection_id | `projection_id` | `final_projection_id` |
| source/target_region_name | *join via projection* | *join* |
| function_term | `function_term` | 同左 |
| function_category | `function_category` | 同左 |
| relation_type | `relation_type` | 同左 |
| evidence_summary | `evidence_text` | `evidence_text` |
| confidence | `confidence` | 同左 |
| mirror/review/promotion_status | 同 Mirror 标准列 | — |
| provenance | `llm_run_id` 等 | `provenance_json` |
| created_at | `created_at` | 同左 |

### 7.3 回路 / Circuit

| 展示列 | Mirror | Final |
|--------|--------|-------|
| circuit_id | `id` | `id` |
| circuit_name | `circuit_name` | 同左 |
| circuit_type | `circuit_type` | 同左 |
| function_association | `function_association` | — | 过渡字段，对应 circuit_function 语义 |
| involved_regions_summary | *join mirror_circuit_regions* | *join final_circuit_regions* |
| evidence_summary | `evidence_text` | 同左 |
| confidence | `confidence` | 同左 |
| source_atlas / granularity_* | 同左 | 同左 |
| governance 列 | mirror/review/promotion | final_status |

### 7.4 回路步骤 / Circuit Step

| 展示列 | Mirror | Final |
|--------|--------|-------|
| circuit_step_id | `id` | `id` |
| circuit_id | `circuit_id` | `final_circuit_id` |
| circuit_name | *join circuit* | *join* |
| step_order | `step_order` | 同左 |
| step_name | `step_name` | 同左 |
| source_region_candidate_id | `region_candidate_id` | 同左 |
| source_region_name | *join candidate* | *join* |
| target_region_* | — | Final 可有 step 间 target；Mirror 用 `role` + next step 派生 |
| step_role | `role` | `role` |
| evidence_summary | `evidence_text` | 同左 |
| confidence | `confidence` | 同左 |
| governance + provenance | 标准 Mirror 列 | `provenance_json` |

### 7.5 回路功能 / Circuit Function（planned）

**现状（Step 10.6.2 更新）：** 已有 `mirror_circuit_functions` 表（migration `033`）；Data Center Circuit Function tab 通过 list/read API 展示 Mirror 数据。migration 未执行时前端显示初始化提示，后端返回 503 `MIRROR_CIRCUIT_FUNCTIONS_NOT_INITIALIZED`。
**过渡：** Data Center 在 Circuit 表增加 `function_association` 列，标记 `completion_eligible: false` 直至 Step 10.3+ 建表。  
**目标对齐：** `final_circuit_functions`（function_term, function_category, relation_type, evidence, confidence）。

### 7.6 脑区功能 / Region Function

对齐 `final_region_functions`：`region_function_id`, `region_candidate_id`, `region_name`, `function_term`, `function_category`, `relation_type`, `evidence_summary`, `confidence`, atlas/granularity, governance 列。

### 7.7 回路–连接 Membership

对齐 `final_circuit_projection_memberships`：`membership_id`, `circuit_id`, `circuit_name`, `projection_id`, `source_step_id`, `target_step_id`, `membership_role` ← `role_in_circuit`, `membership_confidence` ← `confidence`, `source_method`, `verification_status`, cross/dual 状态（Mirror 来自关联 run 或占位）, governance 列。

### 7.8 三元组 / Triple

对齐 `final_kg_triples`：subject_type/id/label, predicate, object_type/id/label, confidence, evidence_count（Mirror 可派生）, governance 列。

### 7.9 证据 / Evidence

对齐 `final_evidence_records`：evidence_id, target_type ← `evidence_target_type`, target_id, evidence_text, source_document ← `source_document_id` / `source_reference_text`, confidence, extraction_run_id ← `llm_run_id`, governance 列。

---

## 8. Data Center Tab 设计

### 8.1 一级 Tab（已实现，保持不变）

1. 总览（Overview）
2. Raw 数据（AAL3 / Macro96）
3. 候选脑区（Candidate Regions）
4. Mirror KG
5. Macro Clinical
6. Final KG
7. 导出文件（Exports）

### 8.2 Mirror KG 二级 Tab

1. Connections / Projections
2. Region Functions
3. Circuits
4. Triples
5. Evidence

### 8.3 Macro Clinical 二级 Tab

1. Circuit Steps
2. Projection Functions
3. Circuit Projection Memberships
4. Circuit Functions（**planned**，Step 10.2 占位 disabled）
5. Cross Validation
6. Dual Model Verification

---

## 9. 各对象正式字段列（Step 10.2 目标列集）

详见 `frontend/src/pages/data-center/formalFieldMappings.ts` 中 `columns` 定义。  
每表统一包含：

- **Identity：** id（short + copy）
- **Semantic：** 正式库对齐业务字段
- **Scope：** source_atlas, granularity_level, granularity_family, batch_id（可选）
- **Governance：** mirror_status, review_status, validation_status（派生）, promotion_status
- **Provenance：** llm_run_id（drawer 详展）
- **Temporal：** created_at

---

## 10. 状态 / Provenance / Review / Promotion 字段

| 字段 | Mirror | 说明 |
|------|--------|------|
| mirror_status | ✅ | llm_suggested / human_edited / … |
| review_status | ✅ | pending / approved / rejected |
| validation_status | 派生 | 最近一次 `mirror_rule_validation_results` |
| promotion_status | ✅ | not_promoted / promoted / blocked |
| provenance | drawer | llm_run_id, llm_item_id, batch_id, resource_id, raw_payload_json |

Final  tab 使用 `final_status` + `provenance_json` / `*_summary_json`（只读）。

---

## 11. Missing fields 标记

**规则（Step 10.2 已实现）：**

1. 对每个 `target_type`，读取 mapping 中 `required=true` 的列。
2. 若字段值为 `null` / 空字符串 / 空数组 / 空对象，记为 missing（`computeMissingFields` / `getFieldValue`）。
3. UI：行首 `MissingFieldsBadge`（Complete / Missing N）；详情 drawer 列出缺失字段名。
4. 表级 `FormalAlignmentCard` 显示 aggregate completeness 与 missing count。
5. 批量选择后可点 **字段补全** — Step 10.4 已接入 `POST /api/llm-extraction/field-completion/run`（dry_run preview + execute）。

**实现文件：** `frontend/src/pages/data-center/formalFieldMappings.ts`、`MissingFieldsBadge.tsx`、`FormalObjectTableSection.tsx`

---

## 12. Field completion entry

| 入口 | Step | 行为 |
|------|------|------|
| Data Center 表格工具栏 | 10.4 ✅ | 多选 → `FieldCompletionModal` → dry_run / run |
| 行操作 / 详情 drawer | 10.4 ✅ | 单对象 → 同上 |
| LLM 抽取结果弹窗 | 10.5 | “继续字段补全” |
| Candidate 页 | 已有 | `region_field_completion`（将纳入 universal API） |

**field_scope 与 missing fields 联动（Step 10.4）：** `missing_only` 自动提交缺失且 enrichable 的字段；无可用字段时按钮 disabled 并提示「当前选择对象没有可补全缺失字段」。

---

## 13. Data Center tab 映射（Step 10.2）

| Tab | Sub-tab | FormalObjectType | Mirror table | Final table |
|-----|---------|------------------|--------------|-------------|
| Mirror KG | connections | projection | mirror_region_connections | final_projections |
| Mirror KG | functions | region_function | mirror_region_functions | final_region_functions |
| Mirror KG | circuits | circuit | mirror_region_circuits | final_region_circuits |
| Mirror KG | triples | triple | mirror_kg_triples | final_kg_triples |
| Mirror KG | evidence | evidence | mirror_evidence_records | final_evidence_records |
| Macro Clinical | circuit_steps | circuit_step | mirror_circuit_steps | final_circuit_steps |
| Macro Clinical | projection_functions | projection_function | mirror_projection_functions | final_projection_functions |
| Macro Clinical | memberships | circuit_projection_membership | mirror_circuit_projection_memberships | final_circuit_projection_memberships |
| Macro Clinical | circuit_functions | circuit_function | mirror_circuit_functions | final_circuit_functions |

---

## 14. 后续实现分步计划

| Step | 内容 |
|------|------|
| **10.1** | 本文档 + UNIVERSAL_FIELD_COMPLETION_DESIGN + mapping 文件 + GPT 同步 |
| **10.2** | ✅ Data Center 按 formal 列展示；missing badge；补全按钮占位 |
| **10.3** | ✅ Universal field completion 后端（migration + API + prompt + mock tests） |
| **10.4** | ✅ Data Center 批量字段补全 UI（FieldCompletionModal + dry_run + run/items） |
| **10.4.1** | ✅ Real Formal Schema Alignment（formalFieldMappings 对齐真实 NeuroGraphIQ_KG_V3） |
| **10.4.2** | ✅ selected_fields / allowed_fields 全部改为真实正式字段名；direct write + overlay 机制 |
| **10.5** | ExtractionResultModal → 字段补全 |
| **10.6** | Validation / Review 联动 |

---

## 14. Step 10.4.2 补充说明 — Field Completion 与 Formal Fields 统一

### 14.1 missing_fields 与 selected_fields 统一基于 formalField

- Data Center `MissingFieldsBadge` 计算依据：`computeMissingFields(item, mapping)` 遍历 `column.required && column.group !== 'governance'`，使用 `getFieldValue(item, column)` 读取值，后者现已检查 overlay。
- `FieldCompletionModal` 中可选字段来自 `getEnrichableColumns(mapping).map(c => c.key)` = `c.finalField`（正式字段名）。
- 两者已统一：`name_cn`, `name_en`, `circuit_class` 等正式字段名在 UI 选择和 API 请求中一致。

### 14.2 getFieldValue 支持 attributes.formal_field_overlay

`getFieldValue` 的查找顺序（Step 10.4.2 更新）：
1. `item[mirrorFieldCandidate]`（Mirror ORM 列）
2. `item.normalized_payload_json.formal_field_overlay[finalField]`
3. `item.raw_payload_json.formal_field_overlay[finalField]`
4. `item.attributes.formal_field_overlay[finalField]`
5. `item.formal_field_overlay[finalField]`（顶层）
6. `resolveDerived(column, item)`（派生）
7. `null`

### 14.3 字段补全后通过 overlay 展示

执行字段补全后：
- 对 Mirror 无直接列的正式字段（如 `name_cn`）：写入 `normalized_payload_json.formal_field_overlay.name_cn`
- 前端刷新后，`getFieldValue` 从 overlay 读取该值并显示在表格/drawer 中
- `MissingFieldsBadge` 数量相应减少

### 14.4 字段补全 API 依赖（Step 10.4.3）

- Data Center 字段补全入口依赖 Step 10.3 API：`POST/GET /api/llm-extraction/field-completion/*`
- Vite 代理目标：`http://127.0.0.1:8002`（见 `frontend/vite.config.ts`）
- API 未启用或后端未重启时，Modal 显示友好提示（非裸 404 刷屏）
- 需手动执行 migration：`backend/migrations/032_universal_field_completion.sql`

## 16. Step 10.4.4 — Overlay 展示与 MissingFieldsBadge 联动 (2026-06-17)

### 16.1 getFieldValue 查找顺序

1. `item[formalField]`（API 直接暴露的正式列）
2. `item.attributes.formal_field_overlay[formalField]` / `formalFieldOverlay`
3. `item.formal_field_overlay[formalField]` / `formalFieldOverlay`（顶层）
4. `item.__fieldCompletionOverlay[formalField]`（补全后本地缓存）
5. `column.mirrorFieldCandidates`（Mirror ORM 列）
6. `normalized_payload_json` / `raw_payload_json` 内 `formal_field_overlay`
7. 派生字段 / 空

### 16.2 MissingFieldsBadge 与 overlay

`computeMissingFields` 使用 `getFieldValue`；overlay 写入 `name_cn` 后 badge 计数减少。

### 16.3 Detail drawer

Formal Fields 区通过同一 `getFieldValue` 显示 overlay 值；Raw JSON / `normalized_payload_json` 可见 `formal_field_overlay`。

### 16.4 Step 10.5.2 — dry_run=false 执行闭环

- 执行成功后 `FieldCompletionModal` 拉取 `GET /runs/{id}` items；`onCompleted` 触发 Mirror 列表 refresh
- Mirror Read schema 返回 computed `attributes`（= `normalized_payload_json`），便于前端 overlay 路径统一
- 自动测试使用 mock provider；用户手动执行时按配置调用 DeepSeek

### 16.5 Step 10.5.3 — Circuit Bundle 默认联动

- **Circuits  tab** 字段补全默认包含：选中 circuit ids + related-targets 解析的 circuit_step / circuit_function ids
- formal field mappings 仍分别按 `macro_clinical.circuit` / `circuit_step` / `circuit_function` 定义；不合并为伪 target_type
- circuit_function mirror 未实现时 UI 显示 unavailable/warning，仍补 circuit 与 step

### 16.6 Step 10.5.4 — Overlay 展示优先

- 正式字段展示统一经 `getFieldValue`；**overlay 优先于 mirror 旧字段**
- `name_cn` / `step_name_cn` / `function_term_cn` 写入 `normalized_payload_json.formal_field_overlay` 后，表格、MissingFieldsBadge、Formal Fields 区同步显示
- Raw JSON 区仍展示完整 `attributes` / `normalized_payload_json`；Formal Fields 与 Raw JSON 分区不变

### 16.7 Step 10.5.6 — 字段级 Prompt 补全

- `name_cn` / `step_name_cn` / `function_term_cn` 由字段级 prompt（如 `circuit_field_completion_name_cn_v1`）补全，不再仅依赖泛化 universal prompt
- completion item 的 `reasoning_summary` 含 `prompt_key` 与 consistency 摘要，便于人工审核追溯

### 16.8 Step 10.5.8 — canonical_start/end overlay 与 resolver warning

- `canonical_start_region_id` / `canonical_end_region_id` 由 `canonical_region_resolver` 写入 `formal_field_overlay`；meta.source = `deterministic_canonical_region_resolver`
- Detail Drawer / Formal Fields：overlay 标记 + label（meta.label）+ short id；方向仅由 sort_order 推断时显示「需人工审核」提示
- 与脑区数据对齐：`region_candidate_id` → `candidate_brain_regions` → `final_brain_regions`（如有 promoted）

### 16.9 Step 10.6.1 — Circuit Function Mirror Foundation

- `macro_clinical.circuit_function` 对应 Mirror 表 **`mirror_circuit_functions`**（migration `033_mirror_circuit_functions.sql`）
- 正式字段：`function_term_en/cn`, `function_domain`, `function_role`, `effect_type`, `confidence_score`, `evidence_level`, `description`, `remark`, `attributes`, `source_db`, `status` 等
- 本步仅完成 Mirror Foundation（model + schema）；**Data Center 展示与 list API 在 Step 10.6.2**

### 16.10 Step 10.6.2 — Circuit Function Data Center 展示

- **Mirror source table:** `mirror_circuit_functions` → **Formal table:** `macro_clinical.circuit_function`
- Data Center Macro Clinical → Circuit Functions tab 调用 `GET /api/mirror-kg/circuit-functions`
- **Formal Fields：** id, circuit_id, function_term_en/cn, function_domain, function_role, effect_type, confidence_score, evidence_level, description, remark, attributes, source_db, status, created_at, updated_at
- **Governance：** mirror_status, review_status, validation_status, promotion_status, confidence, evidence_text, provenance, llm_run_id, llm_item_id, batch_id, resource_id
- **Raw JSON：** 完整对象（含 attributes / normalized_payload_json）
- migration 033 未执行：黄色初始化提示 + 503 结构化错误；不显示“0 条数据”
- field completion registry `circuit_function` 仍为 `supported=False`（Step 10.6.4 启用）

### 16.11 Step 10.6.3 — circuit_to_functions 数据来源

- Circuit Function tab 的数据由 `POST /api/llm-extraction/circuit-to-functions` 写入 `mirror_circuit_functions`
- 输入：`mirror_region_circuits`（function_association / description / evidence_text 等）
- 输出：正式对齐字段 function_term_en/cn、function_domain、function_role 等 + governance 字段
- 不写 `macro_clinical.circuit_function` / final_* / kg_*

### 16.12 Step 10.6.4 — Circuit Function 字段补全可用

- **Circuit Function tab** 表格顶栏 / 行级 / 详情 drawer 字段补全按钮可用；`target_type=circuit_function`
- **正式补全字段**：function_term_cn、function_term_en、function_domain、function_role、effect_type、confidence_score、evidence_level、description、remark、source_db、status（不使用 function_association / function_term）
- **direct write**：上述列在 `mirror_circuit_functions` 有直接列时优先 direct write；扩展字段进 `attributes` overlay
- **Circuit Bundle**：related-targets 返回 circuit_function ids；无数据提示先执行 circuit_to_functions；Prompt Workbench 显示 function prompts
- 不写 formal / final_* / kg_*

### 16.13 Step 10.6.5 — Composite workflow 自动生成 Circuit Function

- **Circuit Function tab** 数据可由 composite workflow `circuit_with_function_steps` 自动写入 `mirror_circuit_functions`
- `mirror_circuit_functions` 仍是 Mirror 候选层；不写 `macro_clinical.circuit_function` / final_* / kg_*
- 组合抽取结果 `created_targets` 含 circuit_function ids，可直接进入 Bundle 字段补全

### 16.14 Step 10.6.6 — Circuit Function Promotion Candidate Source

- **Promotion candidate source**：`mirror_circuit_functions` → `macro_clinical.circuit_function`（不再使用 `mirror_projection_functions` 作为 circuit_function 替身）
- **API**：`GET /api/mirror-kg/promotion-candidates?target_type=circuit_function`；`GET .../circuit_function/{id}/preview`；`POST .../promote` 仅 gate（不写库）
- **Readiness**：`blocked`（缺 circuit_id / 双空 term / invalid / 已 promoted）；`needs_review`（pending、低 confidence、缺 cn/domain/role）；`ready`（approved + 必填完整 + active + not_promoted）
- **Data Center**：Circuit Function 详情 drawer「晋升候选预览」；pending 显示需人工审核；确认晋升按钮 disabled
- **migration 033 未执行**：503 `MIRROR_CIRCUIT_FUNCTIONS_NOT_INITIALIZED`；正式表缺失时 preview 仍可用，actual promote → `FORMAL_CIRCUIT_FUNCTION_TABLE_NOT_INITIALIZED`
- 不写 formal / final_* / kg_*

## 15. 参考文档

- `docs/FORMAL_MACRO_CLINICAL_SCHEMA_ALIGNMENT.md`
- `docs/MIRROR_KG_AND_FINAL_PROMOTION_DESIGN.md`
- `docs/DATA_CENTER_UI_DESIGN.md`
- `docs/UNIVERSAL_FIELD_COMPLETION_DESIGN.md`
- `frontend/src/pages/data-center/formalFieldMappings.ts`

## 16. Step 10.6.7 �� Circuit Function ȱ����ʱͨ�� circuit_to_functions ���� Mirror ��ѡ (2026-06-22)

- ��ѡ�е� Circuit ���޹��� mirror_circuit_functions��Data Center Bundle ������ʾ����ȡ��·���ܡ���塣
- �û�����ִ�� Dry Run�������� provider����д�⣩��ȷ�� token ����� prompt Ԥ����
- ִ�� Execute ��mirror_circuit_functions д�룬�Զ�ˢ�� related-targets��circuit_function ���Ϊ pending���ɼ����ֶβ�ȫ��
- �ֶβ�ȫ��ɺ󣬲�ȫ�����unction_term_cn, unction_domain, unction_role �ȣ���д mirror_circuit_functions��mirror ��ѡ�㣩��
- **���Զ�����**����ͨ�� promotion-candidates/{id}/preview �˹���˺�ſɽ��� macro_clinical.circuit_function��
- migration 033 δִ��ʱֻ��ʾ��ʼ����ʾ�����ṩ��ȡ��ڡ�

---

## Step 10.6.7: Circuit Function Data Center Behavior (Refactor)

### Circuit Function 缺数据时的 Data Center 行为

- **circuit_function group = no_data**：Data Center Bundle 字段补全弹窗不直接执行抽取。
  - 显示提示：「无 Circuit Function 数据，请先到 LLM 提取中心执行 circuit_to_functions 抽取」。
  - 提供「前往 LLM 提取中心」按钮（写入 sessionStorage circuit_ids，跳转 #/llm-extraction）。
  - 提供「刷新关联对象」按钮（重新 call related-targets，有数据则切换为 pending）。
- **circuit_function group = unavailable（migration 033 missing）**：继续显示初始化提示。

### mirror_circuit_functions 生成路径（重构后）

1. 用户在 LLM 提取中心运行 composite「提取回路 + 功能 + 步骤」，或单独运行 circuit_to_functions 抽取。
2. 抽取结果写入 mirror_circuit_functions。
3. 用户回到 Data Center Bundle，点击「刷新关联对象」，circuit_function 组从 no_data 变为 pending。
4. 再执行 Bundle 字段补全，补全 function_term_cn / function_term_en / function_domain / function_role / evidence_level 等字段。

### 严格禁止（Data Center 侧）

- Data Center Bundle 不调用 circuit_to_functions API。
- Data Center Bundle 不调用 DeepSeek。
- Data Center 字段补全弹窗只处理已有 target_ids。
