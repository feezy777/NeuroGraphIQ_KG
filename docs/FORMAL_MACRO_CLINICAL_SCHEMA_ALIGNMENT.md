# Formal Macro Clinical Schema Alignment

> **文档类型**：正式库 macro_clinical schema 与 Mirror KG 对齐规划  
> **版本**：2026-06-15  
> **状态**：Step 8.6 — Mirror schema 已落地（migration 026）；extraction API 仍为 planned

---

## 1. 背景与问题

用户正式库 `NeuroGraphIQ_KG_V3.macro_clinical` 采用 **region → circuit → circuit_step → projection → function** 的结构化链路，而当前 MVP 2 Mirror KG 提取顺序为 **region 并列补全 connection / function / circuit**，再通过 triple consolidation 汇总。

这导致：

1. `mirror_region_connections` 在正式库语义上更接近 **projection**，而非泛化 “connection”；
2. **circuit_step** 作为回路有序中间层缺失；
3. **projection_function** 与 **circuit_function** 未与 **region_function** 区分；
4. promotion 到 `final_*` 或外部 `NeuroGraphIQ_KG_V3` 前，缺少稳定 schema mapping，易造成字段与关系混乱。

**结论**：在继续 promotion 或新增 extraction API 之前，必须先完成正式库 schema 对齐文档与 Prompt Template 体系（Step 8.5）。

---

## 2. 正式库 macro_clinical 表结构（目标模型）

| 表 | 知识语义 | 说明 |
|----|----------|------|
| **region** | 脑区实体 | 同颗粒度 atlas 节点（Macro96、AAL3、Brainnetome、Julich、Allen 等） |
| **region_function** | 脑区功能 | `region --associated_with_function--> function_term` |
| **circuit** | 回路实体 | 由多个脑区、step、projection 组成的功能/结构回路 |
| **circuit_step** | 回路步骤 | circuit 内有序阶段（如 Papez：hippocampus → fornix → mammillary body → anterior thalamic nucleus） |
| **circuit_function** | 回路功能 | `circuit --associated_with_function--> function_term` |
| **projection** | 投射/连接 | source region → target region 的结构或功能投射 |
| **projection_function** | 投射功能 | `projection --associated_with_function--> function_term` |
| **circuit_projection_membership** | 回路–投射包含关系 | **circuit contains projection** / **projection belongs_to circuit** |

### 2.1 region

- **语义**：同颗粒度脑区节点。
- **来源**：Atlas 导入、candidate promotion、人工 curation。

### 2.2 region_function

- **语义**：脑区层面的功能关联。
- **来源**：LLM region function completion、文献、人工审核、规则整理。

### 2.3 circuit

- **语义**：命名回路，包含多个参与脑区与有序 step。
- **示例**：Papez circuit、default mode network（macro 视角下的简化回路）。

### 2.4 circuit_step

- **语义**：回路内的有序步骤或阶段。
- **step 可表示**：单个 region、region group、functional stage、relay/hub/modulator role。
- **关键字段（目标）**：`step_order`、`step_name`、`step_type`、`region_candidate_id`、`role`、`description`。

**step_type 建议**：`region` | `region_group` | `relay` | `hub` | `modulator` | `functional_stage` | `unknown`

**role 建议**：`source` | `target` | `relay` | `hub` | `modulator` | `participant` | `unknown`

### 2.5 projection

- **语义**：从 source region 到 target region 的连接或投射。
- **来源**：circuit_step 相邻节点推导、LLM 提取、文献、atlas/database、人工审核。
- **注意**：当前 `mirror_region_connections` **应映射为 projection**，不是独立 “connection” 实体族。

### 2.6 projection_function

- **语义**：投射参与的功能过程。
- **示例**：hippocampus → mammillary body 的 projection 参与 memory consolidation。

### 2.7 circuit_function

- **语义**：整条回路层面的功能。
- **示例**：Papez circuit → memory / emotion regulation。

### 2.8 circuit_projection_membership

- **语义**：表达 **circuit contains projection** 与 **projection belongs_to circuit**。
- **用途**：标明 projection 所属 circuit、顺序位置、source/target step；支持双向查询与交叉验证。
- **建议字段**：circuit_id, projection_id, source_step_id, target_step_id, step_order, role_in_circuit, confidence, evidence_text, uncertainty_reason, source_method, verification_status。
- **source_method**：circuit_to_projection | projection_to_circuit | dual_model_consensus | human_curated
- **verification_status**：unverified | circuit_supported | projection_supported | bidirectionally_supported | model_conflict | human_approved | human_rejected

---

## 3. 当前 Mirror KG 与相关表

| 当前表 | 用途 |
|--------|------|
| `mirror_region_connections` | 同颗粒度 region 对 region 连接候选 |
| `mirror_region_functions` | region 功能候选 |
| `mirror_region_circuits` | 回路候选 |
| `mirror_circuit_regions` | 回路–脑区组成（role + sort_order） |
| `mirror_kg_triples` | 三元组视图 |
| `mirror_evidence_records` | 证据 |
| `mirror_rule_validation_*` | 规则校验 audit |
| `mirror_human_review_records` | 人工审核 audit |
| `final_region_connections` 等 | Step 9 工作库 final 层（**暂缓继续 promotion**） |

### 3.1 当前 LLM extraction（已实现 MVP）

| Task type | 输出 Mirror 表 |
|-----------|----------------|
| `same_granularity_connection_completion` | `mirror_region_connections` |
| `same_granularity_function_completion` | `mirror_region_functions` |
| `same_granularity_circuit_completion` | `mirror_region_circuits` + `mirror_circuit_regions` |
| triple consolidation（确定性） | `mirror_kg_triples` |

**当前顺序（并列式）**：

```
region → connection
region → function
region + connection/function context → circuit → triple
```

---

## 4. Mirror KG → macro_clinical 映射关系

| 当前 Mirror KG | 正式库 macro_clinical | 对齐状态 |
|----------------|----------------------|----------|
| （candidate / final region） | **region** | region promotion 已有 MVP 1 路径 |
| `mirror_region_functions` | **region_function** | 语义接近，缺显式 `function_target_type` |
| `mirror_region_circuits` | **circuit** | 语义接近 |
| `mirror_circuit_regions` | **circuit_step**（部分） | **不完整**：无 step_type、无与 projection 链接 |
| `mirror_region_connections` | **projection** | **命名不一致**；缺 source_step / target_step |
| （缺失） | **circuit_function** | 功能混在 `mirror_region_functions` 或未区分 target |
| `mirror_circuit_steps` | **circuit_step** | Step 8.6 已落地 |
| `mirror_projection_functions` | **projection_function** | Step 8.6 已落地 |
| `mirror_circuit_projection_memberships` | **circuit_projection_membership** | Step 8.6 已落地 |
| `mirror_dual_model_verification_runs/results` | 双模型验证层 | Step 8.6 已落地（记录层，不 auto approve） |
| `mirror_kg_triples` | triple 视图 | 可由上述对象确定性生成 |
| `mirror_evidence_records` | evidence / provenance | 可保留为通用证据层 |

---

## 5. 缺失对象与字段

### 5.1 Mirror 层（Step 8.6 已落地 schema foundation）

1. `mirror_circuit_steps` — ✅ migration 026
2. `mirror_projection_functions` — ✅ migration 026
3. `mirror_circuit_projection_memberships` — ✅ migration 026
4. `mirror_dual_model_verification_runs` / `mirror_dual_model_verification_results` — ✅ migration 026

**仍待实现**：extraction API、rule validation 扩展、promotion 到 final macro_clinical 表、`mirror_cross_validation_results`（可选独立表）。

### 5.2 Final 层缺失（规划，本轮不实现）

1. `final_circuit_steps`
2. `final_projection_functions`
3. projection ↔ circuit_step 外键（`source_step_id` / `target_step_id`）

### 5.3 关系（Step 8.6 部分已落地）

- ✅ `mirror_circuit_projection_memberships` — circuit contains projection / projection belongs_to circuit
- ✅ `mirror_circuit_steps` — step_order / step_type / role
- ✅ `mirror_projection_functions` — projection 级 function_term / category / relation_type
- ⏳ `mirror_cross_validation_results` — A/B 路径交叉验证 audit
- ⏳ final macro_clinical promotion 映射

---

## 6. 推荐 extraction 顺序（双向 + 双模型主流程）

详见 [CIRCUIT_PROJECTION_BIDIRECTIONAL_EXTRACTION_DESIGN.md](./CIRCUIT_PROJECTION_BIDIRECTIONAL_EXTRACTION_DESIGN.md)。

```
Phase 1   Region Pool
Phase 2   Regions → Circuits              [regions_to_circuits_v1]
Phase 3   Circuit → Steps                 [circuit_to_steps_v1]
Phase 4   Steps → Projections + membership [circuit_steps_to_projections_v1]  ← 方向 A
Phase 5   Projections → Circuits          [projections_to_circuits_v1]        ← 方向 B
Phase 6   Cross Validation              [circuit_projection_cross_validation_v1]
Phase 7   Dual-Model Verification         [dual_model_verification_v1] DeepSeek + Kimi
Phase 8   Functions (3-way)
Phase 9   Triple Consolidation
Phase 10  Rule Validation
Phase 11  Human Review
Phase 12  Promotion to Final
```

### 6.1 单向 MVP（当前已实现，legacy 并列链路）

- **不删除** 现有 connection / function / circuit extraction API；
- 标记为 **MVP 并列链路**，后续新增 step / projection-first 链路与之并存；
- triple consolidation 扩展输入类型后，可逐步从 step / projection_function 生成 triples。

---

## 7. 为什么暂缓 promotion

Step 9 已实现 `final_region_connections` 等工作库 final 表，但：

1. final 表命名仍用 “connection”，与正式库 **projection** 不一致；
2. 无 circuit_step / projection_function，promotion 后无法对齐 `macro_clinical.circuit_step` 等表；
3. 先完成 schema mapping 与 prompt 契约，再设计 migration 026+，可避免 rework。

**原则**：promotion 前必须完成 Mirror KG ↔ 正式库 schema mapping（见 VIBE_CODING_GUIDE Step 8.5 原则）。

---

## 8. 下一步 migration 规划（仅规划，本轮不执行）

| 序号 | 建议 migration | 内容 |
|------|----------------|------|
| 026 | `mirror_circuit_steps` | step_order, step_type, role, circuit_id |
| 027 | `mirror_circuit_projection_memberships` | circuit_id, projection_id, step_order, verification_status |
| 028 | `mirror_projection_functions` | projection_id, function_term |
| 029 | `mirror_dual_model_verification_results` | deepseek/kimi decision, consensus_status |
| 030 | connection → projection 语义 | semantic_type, source_step_id, target_step_id |
| 031 | function scope 区分 | function_scope: region \| circuit \| projection |
| 032 | final 层对齐 | final_circuit_steps, final_memberships, final_projection_functions |

---

## 9. Prompt 体系

详见 [LLM_PROMPT_TEMPLATES_MACRO_CLINICAL.md](./LLM_PROMPT_TEMPLATES_MACRO_CLINICAL.md)。

本轮已在 `backend/app/services/llm_prompt_defaults.py` 注册 **planned** template keys（`implemented=false`），不接入真实 API。

---

## 11. Final macro_clinical tables（Step 8.15）

| Final 表 | Mirror 来源 | 去重键 |
|---------|------------|--------|
| `final_region_circuits` | `mirror_region_circuits` | atlas + granularity + circuit_name + circuit_type |
| `final_projections` | `mirror_region_connections` (projection) | canonical source/target pair + projection_type + directionality |
| `final_circuit_steps` | `mirror_circuit_steps` | final_circuit_id + step_order |
| `final_circuit_functions` | `circuit.function_association`（可选） | final_circuit_id + function_term |
| `final_projection_functions` | `mirror_projection_functions` | final_projection_id + function_term |
| `final_circuit_projection_memberships` | `mirror_circuit_projection_memberships` | circuit + projection + steps |
| `final_region_functions` | `mirror_region_functions` | region + function_term + category |
| `final_kg_triples` | `mirror_kg_triples` | subject + predicate + object + scope |
| `final_evidence_records` | `mirror_evidence_records` | final target 已存在 |

Promotion gate：human_approved + review approved + validation 无 blocker/error；signal object 不可 promotion。

---

## 9. Final Browser 查询路径（Step 8.16）

| 入口 | API | 返回 |
|------|-----|------|
| 关键词搜索 | `GET /api/final-macro-clinical/browser/search` | circuit / step / projection / function / membership / triple / evidence |
| 脑区邻域 | `GET /api/final-macro-clinical/browser/region/{region_candidate_id}` | functions、circuits、steps、out/in/undirected projections、triples、evidence、graph |
| 回路详情 | `GET /api/final-macro-clinical/browser/circuit/{final_circuit_id}` | steps（step_order）、memberships、projections、participant_regions、provenance |
| 投射详情 | `GET /api/final-macro-clinical/browser/projection/{final_projection_id}` | source/target region、circuits、memberships、projection_functions、provenance |
| 通用对象 | `GET /api/final-macro-clinical/browser/object/{type}/{id}` | object、related、triples、evidence、promotion_record |
| 图谱 JSON | `GET /api/final-macro-clinical/browser/graph` | nodes / edges（展示用） |

**Provenance drill-down 字段**：`source_mirror_type`、`source_mirror_id`、`promotion_run_id`、`promotion_record_id`、`validation_summary_json`、`review_summary_json`、`cross_validation_summary_json`、`dual_model_summary_json`、`provenance_json`。

**Graph 节点/边映射**：region ↔ circuit（participates_in）、circuit ↔ step（contains_step）、step ↔ region（at_region）、projection ↔ region（source/target）、projection ↔ function（has_function）、circuit ↔ projection（contains/membership）。

---

## 10. Export nodes/edges 映射（Step 8.17）

| Final 来源 | Export node_id | Labels |
|-----------|----------------|--------|
| candidate_brain_regions（引用） | `candidate_region:<uuid>` | BrainRegion |
| final_region_circuits | `final:circuit:<uuid>` | Circuit, FinalObject |
| final_circuit_steps | `final:circuit_step:<uuid>` | CircuitStep, FinalObject |
| final_projections | `final:projection:<uuid>` | Projection, FinalObject |
| final_projection_functions | `final:projection_function:<uuid>` | ProjectionFunction, Function, FinalObject |
| final_circuit_projection_memberships | `final:circuit_projection_membership:<uuid>` | CircuitProjectionMembership, FinalObject |
| final_region_functions | `final:region_function:<uuid>` | RegionFunction, Function, FinalObject |
| final_circuit_functions | `final:circuit_function:<uuid>` | CircuitFunction, Function, FinalObject |
| final_kg_triples | `final:triple:<uuid>` | Triple, FinalObject |
| final_evidence_records | `final:evidence:<uuid>` | Evidence, FinalObject |

**Edge types**：REGION_HAS_FUNCTION、REGION_PARTICIPATES_IN_CIRCUIT、CIRCUIT_HAS_STEP、STEP_HAS_REGION、CIRCUIT_CONTAINS_PROJECTION、PROJECTION_BELONGS_TO_CIRCUIT、PROJECTION_SOURCE_REGION、PROJECTION_TARGET_REGION、PROJECTION_HAS_FUNCTION、CIRCUIT_HAS_FUNCTION、OBJECT_HAS_EVIDENCE、TRIPLE_SUBJECT、TRIPLE_OBJECT。

**Provenance 字段**：source_mirror_type、source_mirror_id、promotion_run_id、promotion_record_id、validation/review/cross/dual summaries → `provenance.jsonl` + node/edge provenance_json。

详见 [FINAL_KG_EXPORT_FORMAT.md](./FINAL_KG_EXPORT_FORMAT.md)。

---

## 11. 相关文档

- [CIRCUIT_PROJECTION_BIDIRECTIONAL_EXTRACTION_DESIGN.md](./CIRCUIT_PROJECTION_BIDIRECTIONAL_EXTRACTION_DESIGN.md)
- [LLM_PROMPT_TEMPLATES_MACRO_CLINICAL.md](./LLM_PROMPT_TEMPLATES_MACRO_CLINICAL.md)
- [LLM_SAME_GRANULARITY_COMPLETION_DESIGN.md](./LLM_SAME_GRANULARITY_COMPLETION_DESIGN.md)
- [MIRROR_KG_AND_FINAL_PROMOTION_DESIGN.md](./MIRROR_KG_AND_FINAL_PROMOTION_DESIGN.md)
- [TRIPLE_MODEL_AND_ONTOLOGY_DESIGN.md](./TRIPLE_MODEL_AND_ONTOLOGY_DESIGN.md)
