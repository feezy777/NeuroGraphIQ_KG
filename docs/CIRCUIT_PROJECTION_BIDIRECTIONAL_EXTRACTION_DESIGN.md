# Circuit-Projection Bidirectional Extraction and Dual-Model Verification Design

> **文档类型**：macro_clinical 双向提取与双模型验证设计  
> **版本**：2026-06-15  
> **状态**：Step 8.5b 设计 + Step 8.6 schema foundation 已落地（migration 026）；**circuit_to_steps（8.7）、circuit_steps_to_projections（8.8）、projection_to_functions（8.9）、projections_to_circuits（8.10）、circuit_projection_cross_validation（8.11）、dual_model_verification（8.12）已实现**

---

## 1. 为什么要双向提取

正式库 `macro_clinical` 中，**回路（circuit）** 与 **投射（projection）** 不是独立并列事实，而是 **包含与被包含** 关系：

- **circuit contains projection** — 某条连接/投射属于哪条回路、在回路中的顺序与角色
- **projection belongs_to circuit** — 从连接网络反查所属回路

仅做 **region → connection** 并列 MVP 无法表达：

1. projection 在 circuit 内的 **step_order / role_in_circuit**
2. 由 circuit 推导的 projection 与由 projection graph 反推的 circuit 是否 **一致**
3. 弱证据 coactivation 被误当作确定 circuit 的风险

因此推荐 **方向 A（circuit-first）** 与 **方向 B（projection-first）** 并行，再 **交叉验证** + **DeepSeek/Kimi 双模型验证**，全部结果仅进入 Mirror KG 验证层。

---

## 2. 正式语义对象

| 对象 | 语义 |
|------|------|
| **region** | 同颗粒度脑区节点 |
| **circuit** | 命名回路实体 |
| **circuit_step** | 回路内有序步骤（region / relay / hub / functional_stage 等） |
| **projection** | source region → target region 的结构/功能/有效连接等（Mirror 表：`mirror_region_connections`） |
| **circuit_projection_membership** | **circuit contains projection** / **projection belongs_to circuit** |
| **region_function** | region 级功能 |
| **circuit_function** | circuit 级功能 |
| **projection_function** | projection 级功能 |

### 2.1 circuit_projection_membership（推荐 Mirror 表）

正式库若无独立表，可用 `projection.circuit_id` 表达；**推荐** Mirror 层独立表以便 audit 与双向验证。

| 字段 | 说明 |
|------|------|
| id | UUID |
| circuit_id | 所属 circuit |
| projection_id | 所属 projection |
| source_step_id | 可选，对应 circuit_step |
| target_step_id | 可选 |
| step_order | projection 在 circuit 路径中的顺序 |
| role_in_circuit | main_path / feedback / feedforward / modulatory / relay / parallel_branch / unknown |
| confidence | 0–1 |
| evidence_text | 证据 |
| uncertainty_reason | 不确定性 |
| source_method | circuit_to_projection \| projection_to_circuit \| dual_model_consensus \| human_curated |
| verification_status | unverified \| circuit_supported \| projection_supported \| bidirectionally_supported \| model_conflict \| human_approved \| human_rejected |
| created_at | TIMESTAMPTZ |

---

## 3. 方向 A：circuit → projection

```
region pool
  → regions_to_circuits_v1        → mirror_region_circuits
  → circuit_to_steps_v1           → mirror_circuit_steps
  → circuit_steps_to_projections_v1 → mirror_region_connections (projection 语义)
                                    + circuit_projection_membership (source_method=circuit_to_projection)
```

**逻辑**：先定回路结构与有序 step，再由相邻 step 或 involved regions 生成 projection，并 **同时** 写入 membership。

---

## 4. 方向 B：projection → circuit

```
region pair / projection candidates (projection graph)
  → projections_to_circuits_v1      → inferred circuit candidates + membership suggestions
                                    (source_method=projection_to_circuit)
```

**约束**：

1. 只能使用输入 projection，不凭空跨颗粒度建 circuit
2. 不把 common coactivation 当作确定 circuit
3. 证据弱 → low confidence + uncertainty_reason

---

## 5. 双向交叉验证（Phase 6）

**Prompt**：`circuit_projection_cross_validation_v1`

**输入**：

- circuit_derived_projections（方向 A）
- projection_inferred_circuits（方向 B）
- existing_circuit_candidates

**输出**：`cross_validation_results[]`，含 `validation_status`：

| validation_status | 含义 |
|-------------------|------|
| circuit_supported | 仅 A 路径支持 |
| projection_supported | 仅 B 路径支持 |
| bidirectionally_supported | A/B 一致 |
| conflict | A/B 冲突 |
| insufficient_evidence | 证据不足 |
| unknown | 未知 |

**support_level**：strong \| moderate \| weak \| conflicting \| unknown

**规则摘要**：

- A 与 B 对同一 (circuit_id, projection_id) 均支持 → `bidirectionally_supported`
- 仅一侧支持 → `circuit_supported` 或 `projection_supported`
- 一侧支持、一侧否定 → `conflict`，**不自动 reject**，进入人工审核队列
- 两侧 confidence 均 < 0.5 → `insufficient_evidence`

---

## 6. DeepSeek / Kimi 双模型验证（Phase 7）

### 6.1 角色

| Provider | 角色 |
|----------|------|
| **DeepSeek** | 独立生成/验证 structured JSON；不写 final；不 approve；不 promote |
| **Kimi** | 同样输入 **独立** 运行；生成阶段 **不得** 看到 DeepSeek 原始结论 |
| **Comparison** | 仅在 `dual_model_verification_v1` 阶段同时输入两份结构化输出 |

### 6.2 推荐流程

1. DeepSeek run（task + payload）
2. Kimi run（**相同** payload，隔离上下文）
3. normalize outputs（JSON schema 校验）
4. **确定性** comparison（非 LLM）
5. 合成 `dual_model_verification_result` → Mirror 表 `mirror_dual_model_verification_results`（规划）

### 6.3 consensus_status

| 状态 | 条件 | 动作 |
|------|------|------|
| consensus_supported | 两模型 decision 一致且均为 support | confidence 可上调（见 §7） |
| consensus_rejected | 两模型一致 reject | review_priority=normal |
| model_conflict | decision 不一致 | review_priority=**high**，写 conflict record |
| insufficient_information | 两者均低 confidence | review_priority=high |
| needs_human_review | 边界 case | review_priority=high |

**禁止**：双模型一致 **不能** 自动 approve、不能自动 promote、不能写 final / kg_*。

---

## 7. 置信度合成规则（Mirror 建议层）

| 场景 | combined_confidence | consensus_status |
|------|---------------------|------------------|
| 两模型均 support | `min(0.95, avg(model_confidences) + 0.10)` | consensus_supported |
| 一 support，一 uncertain | `avg(model_confidences)` | needs_human_review |
| 冲突 | `min(model_confidences)` | model_conflict |
| 两者均 < 0.5 | `avg(model_confidences)` | insufficient_information |

**注意**：合成 confidence 仅为 Mirror KG 建议，不等于事实；人工审核仍为必须步骤。

---

## 8. Evidence 合并规则

1. 保留各模型独立 `evidence_text` 于 verification record
2. 合成 record 的 `evidence_text` = 简短摘要 + 引用 model_a / model_b evidence id
3. `uncertainty_reason` 在 conflict 时必须非空
4. `risk_flags` 可含：`model_conflict`、`low_confidence`、`needs_literature_verification`、`cross_granularity_risk`

---

## 9. Mirror KG 状态与下游 gate

### 9.1 进入 Mirror KG

- 所有 LLM 输出 → `mirror_status=llm_suggested`
- membership → `verification_status=unverified` 直至 cross-validation / dual-model

### 9.2 Rule Validation 前置

- 对象存在且 source_atlas / granularity 非空
- cross-validation 完成（或显式 skip 标记 + warning）
- 无 deterministic blocker（跨 atlas、跨颗粒度、缺失 region 等）

### 9.3 Human Review 前置

- rule_checked
- 无 blocker/error validation
- `model_conflict` → **必须** 人工审核，不可 auto-approve

### 9.4 Final KG / Promotion 前置

- human_approved + review_status=approved
- bidirectional_supported 或 human 覆盖 conflict
- schema mapping 完成（circuit_step、membership、projection_function 表已落地）
- 强确认 promotion（Step 9 机制）

---

## 10. 完整 Phase 流程（推荐主流程）

| Phase | 内容 | Prompt |
|-------|------|--------|
| 1 | Region Pool | — |
| 2 | Regions → Circuits | regions_to_circuits_v1 |
| 3 | Circuit → Steps | circuit_to_steps_v1 |
| 4 | Steps → Projections + membership | circuit_steps_to_projections_v1 |
| 5 | Projections → Circuits | projections_to_circuits_v1 |
| 6 | Cross Validation | circuit_projection_cross_validation_v1 |
| 7 | Dual-Model Verification | dual_model_verification_v1 |
| 8 | Functions (3-way) | region/circuit/projection_to_functions_v1 |
| 9 | Triple Consolidation | macro_clinical_triple_generation_v1（优先确定性） |
| 10 | Rule Validation | — |
| 11 | Human Review | — |
| 12 | Promotion to Final | — |

---

## 11. Mirror schema foundation（Step 8.6 已落地）

| 表 | 用途 | 状态 |
|----|------|------|
| `mirror_circuit_steps` | 有序 step | ✅ migration 026 + API |
| `mirror_projection_functions` | projection 级功能 | ✅ migration 026 + API |
| `mirror_circuit_projection_memberships` | circuit ↔ projection 包含关系 | ✅ migration 026 + API |
| `mirror_dual_model_verification_runs` | 双模型验证 run 元数据 | ✅ migration 026 + API |
| `mirror_dual_model_verification_results` | DeepSeek/Kimi 对比 audit | ✅ migration 026 + API |
| `mirror_cross_validation_results` | A/B 路径交叉验证 audit | ⏳ 下一步（可选独立表或 JSON 层） |

### 后续 Extraction 输入输出

| Extraction | 输入 | 输出 Mirror 表 | 状态 |
|------------|------|----------------|------|
| Circuit-to-Steps | `mirror_region_circuits` + regions | `mirror_circuit_steps` | ✅ Step 8.7 已实现 |
| Circuit-Steps-to-Projections | `mirror_circuit_steps` | `mirror_region_connections` + `mirror_circuit_projection_memberships` | ✅ Step 8.8 已实现 |
| Projection-to-Functions | `mirror_region_connections` (projection) | `mirror_projection_functions` | ✅ Step 8.9 已实现 |
| Projections-to-Circuits | projection graph | inferred circuits + memberships | ✅ Step 8.10 已实现 |
| Circuit-Projection Cross Validation | circuit + projection memberships | bidirectionally_supported / conflict | ✅ Step 8.11 已实现 |
| Dual-Model Verification | 同上对象 batch | `mirror_dual_model_verification_*` | ✅ Step 8.12 已实现 |
| Macro Clinical Rule Validation | circuit_step / membership / cross / dual result 等 | `mirror_rule_validation_*` | ✅ Step 8.13 已实现 |

---

## 12. 与当前 MVP 关系

- **保留** `same_granularity_connection/function/circuit_completion` API
- 标记为 **legacy 并列 MVP**；新链路为 **macro_clinical 双向主流程**
- `mirror_region_connections` 语义统一为 **projection**
- **Step 8.10 起**：circuit → projection（Step 8.8）与 projection → circuit（Step 8.10）两条链路均已实现
- **Step 8.11 起**：确定性 cross validation 已实现（migration 027）
- **Step 8.12 起**：DeepSeek/Kimi 双模型验证执行已实现；主链路 region→circuit→steps→projection→function、projection→circuit、cross validation、dual model 已闭环
- **Step 8.13 起**：rule validation 已覆盖 macro_clinical 新对象；cross validation 与 dual model verification 信号已纳入 validation 门禁
- **Step 8.14 起**：human review 已覆盖 macro_clinical 新对象；review detail 已展示 circuit/projection/membership/cross/dual evidence chain
- **下一步**应实现 **Final macro_clinical Schema and Promotion**；promotion 必须只接受 human_approved 且 validation 无 blocker/error 的 domain object

---

## 相关文档

- [FORMAL_MACRO_CLINICAL_SCHEMA_ALIGNMENT.md](./FORMAL_MACRO_CLINICAL_SCHEMA_ALIGNMENT.md)
- [LLM_PROMPT_TEMPLATES_MACRO_CLINICAL.md](./LLM_PROMPT_TEMPLATES_MACRO_CLINICAL.md)
