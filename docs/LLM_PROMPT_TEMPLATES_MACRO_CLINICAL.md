# LLM Prompt Templates — Macro Clinical

> **文档类型**：macro_clinical 对齐 Prompt Template 设计  
> **版本**：2026-06-15  
> **状态**：Step 8.5 — 设计 + 代码常量（**planned**，`implemented=false`）

所有 template 均：

- **same-granularity only** — 不跨 atlas、不跨 granularity；
- **do not merge by name** — 不同 atlas 同名脑区不自动合并；
- **Mirror KG candidate only** — 不是 final、不是 kg_*、不声称已审核；
- **JSON only** — 禁止 markdown 包裹（除非 provider 剥离 fence）。

代码常量位置：`backend/app/services/llm_prompt_defaults.py`  
Task type 注册：`backend/app/schemas/llm_extraction.py`（`IMPLEMENTED_TASK_TYPES` 不含下列 planned types）

---

## Template 索引

| template_key | task_type | Phase |
|--------------|-----------|-------|
| `regions_to_circuits_v1` | `regions_to_circuits` | 2 |
| `circuit_to_steps_v1` | `circuit_to_steps` | 3 |
| `circuit_steps_to_projections_v1` | `circuit_steps_to_projections` | 4（方向 A + membership） |
| `projections_to_circuits_v1` | `projections_to_circuits` | 5（方向 B） |
| `circuit_projection_cross_validation_v1` | `circuit_projection_cross_validation` | 6 |
| `dual_model_verification_v1` | `dual_model_verification` | 7 |
| `region_to_functions_v1` | `region_to_functions` | 8a |
| `circuit_to_functions_v1` | `circuit_to_functions` | 8b |
| `projection_to_functions_v1` | `projection_to_functions` | 8c |
| `macro_clinical_triple_generation_v1` | `macro_clinical_triple_generation` | 9 |
| `evidence_uncertainty_review_v1` | `evidence_uncertainty_review` | 辅助 |

---

## 1. regions_to_circuits_v1

**用途**：基于一组同颗粒度脑区，推断可能的回路候选。

**输入**：

- source_atlas, granularity_level, granularity_family
- region list（id, name, optional metadata）
- optional known functions / projections
- max_circuits

**输出 JSON**：

```json
{
  "circuits": [
    {
      "circuit_name": "...",
      "circuit_type": "memory_related",
      "involved_region_candidate_ids": ["..."],
      "function_association": "...",
      "description": "...",
      "confidence": 0.0,
      "evidence_text": "...",
      "uncertainty_reason": "...",
      "requires_step_extraction": true
    }
  ]
}
```

**System 强调**：同 atlas、同 granularity、不跨图谱、不同名合并、非 final、证据不足低 confidence。

**Mirror 目标表**：`mirror_region_circuits` + `mirror_circuit_regions`（后续由 step extraction 细化）。

---

## 2. circuit_to_steps_v1

**用途**：把 circuit 拆解为 ordered circuit steps。

**输入**：circuit、circuit 的 involved regions、source_atlas、granularity、optional function_association

**输出 JSON**：

```json
{
  "circuit_steps": [
    {
      "step_order": 1,
      "step_name": "...",
      "step_type": "region",
      "region_candidate_id": "...",
      "role": "source",
      "description": "...",
      "confidence": 0.0,
      "evidence_text": "...",
      "uncertainty_reason": "..."
    }
  ]
}
```

**step_type**：`region` | `region_group` | `relay` | `hub` | `modulator` | `functional_stage` | `unknown`

**role**：`source` | `target` | `relay` | `hub` | `modulator` | `participant` | `unknown`

**Mirror 目标表（规划）**：`mirror_circuit_steps`

---

## 3. circuit_steps_to_projections_v1

**用途**：根据有序 circuit steps 生成 projection，**同时**输出 `circuit_projection_membership`（circuit contains projection）。

**输入**：circuit、ordered circuit_steps、source_atlas、granularity

**输出 JSON**：

```json
{
  "projections": [
    {
      "source_step_order": 1,
      "target_step_order": 2,
      "source_region_candidate_id": "...",
      "target_region_candidate_id": "...",
      "projection_type": "structural_connection",
      "directionality": "directed",
      "strength": "unknown",
      "modality": "literature_prior",
      "role_in_circuit": "main_path",
      "confidence": 0.0,
      "evidence_text": "...",
      "uncertainty_reason": "...",
      "circuit_membership": {
        "circuit_id": "...",
        "source_step_order": 1,
        "target_step_order": 2,
        "membership_confidence": 0.0
      }
    }
  ]
}
```

**role_in_circuit**：main_path | feedback | feedforward | modulatory | relay | parallel_branch | unknown

**Mirror 目标表**：`mirror_region_connections`（projection 语义）+ `mirror_circuit_projection_memberships`

---

## 4. projections_to_circuits_v1

**用途**：反向通过 projection graph 推断可能 circuit（方向 B）。

**输入**：projection list、region list、source_atlas、granularity、optional existing circuits

**输出 JSON**：

```json
{
  "inferred_circuits": [
    {
      "circuit_name": "...",
      "supporting_projection_ids": ["..."],
      "involved_region_candidate_ids": ["..."],
      "possible_step_order": [{"step_order": 1, "region_candidate_id": "..."}],
      "function_association": "...",
      "confidence": 0.0,
      "evidence_text": "...",
      "uncertainty_reason": "..."
    }
  ]
}
```

**约束**：仅使用输入 projection；不跨颗粒度；不把 coactivation 当确定 circuit。

**Mirror 目标表**：membership suggestions（source_method=projection_to_circuit）

---

## 5. circuit_projection_cross_validation_v1

**用途**：对比 circuit→projection（A）与 projection→circuit（B）。

**输出 JSON**：

```json
{
  "cross_validation_results": [
    {
      "circuit_id": "...",
      "projection_id": "...",
      "validation_status": "bidirectionally_supported",
      "support_level": "strong",
      "agreement_score": 0.0,
      "conflict_reason": "",
      "evidence_text": "...",
      "uncertainty_reason": "..."
    }
  ]
}
```

**validation_status**：circuit_supported | projection_supported | bidirectionally_supported | conflict | insufficient_evidence | unknown

---

## 6. dual_model_verification_v1

**用途**：DeepSeek/Kimi 双模型验证 circuit/projection/membership。

**输出 JSON**：

```json
{
  "dual_model_verification": [
    {
      "object_type": "circuit_projection_membership",
      "object_id": "...",
      "deepseek_decision": "support",
      "kimi_decision": "support",
      "consensus_status": "consensus_supported",
      "consensus_score": 0.0,
      "conflict_summary": "",
      "recommended_review_priority": "normal",
      "evidence_text": "...",
      "uncertainty_reason": "..."
    }
  ]
}
```

**consensus_status**：consensus_supported | consensus_rejected | model_conflict | insufficient_information | needs_human_review

**禁止**：一致 ≠ 自动 approve / promote / final。

---

## 7. region_to_functions_v1

**用途**：从 region 生成 region_function。

**输入**：单个或批量 region

**输出 JSON**：

```json
{
  "region_functions": [
    {
      "region_candidate_id": "...",
      "function_term": "...",
      "function_category": "memory",
      "relation_type": "associated_with",
      "confidence": 0.0,
      "evidence_text": "...",
      "uncertainty_reason": "..."
    }
  ]
}
```

**Mirror 目标表**：`mirror_region_functions`（`function_scope=region` 规划字段）

**与 MVP 关系**：接近现有 `same_granularity_function_completion_v1`，后续可收敛或并存。

---

## 8. circuit_to_functions_v1

**用途**：从 circuit（含 steps、projections、regions 上下文）生成 circuit_function。

**输入**：circuit_id、circuit_steps、projections、regions

**输出 JSON**：

```json
{
  "circuit_functions": [
    {
      "circuit_id": "...",
      "function_term": "...",
      "function_category": "memory",
      "relation_type": "associated_with",
      "confidence": 0.0,
      "evidence_text": "...",
      "uncertainty_reason": "..."
    }
  ]
}
```

**Mirror 目标表（规划）**：`mirror_circuit_functions` 或 `mirror_region_functions` + `function_scope=circuit`

---

## 9. projection_to_functions_v1

**用途**：从 projection 生成 projection_function。

**输入**：projection、source/target region、circuit context

**输出 JSON**：

```json
{
  "projection_functions": [
    {
      "projection_id": "...",
      "function_term": "...",
      "function_category": "memory",
      "relation_type": "participates_in",
      "confidence": 0.0,
      "evidence_text": "...",
      "uncertainty_reason": "..."
    }
  ]
}
```

**Mirror 目标表（规划）**：`mirror_projection_functions`

---

## 10. macro_clinical_triple_generation_v1

**用途**：把正式 schema 对象整理为 triples（**优先确定性 consolidation**；本 prompt 为复杂语义解释备用）。

**输入**：region、region_function、circuit、circuit_step、projection、**circuit_projection_membership**、circuit_function、projection_function

**必须 predicate**：

- region_has_function
- circuit_has_step
- circuit_contains_projection
- projection_belongs_to_circuit
- projection_has_source_region
- projection_has_target_region
- projection_has_function
- circuit_has_function

**输出 JSON**：

```json
{
  "triples": [
    {
      "subject_type": "circuit",
      "subject_label": "...",
      "predicate": "has_step",
      "object_type": "circuit_step",
      "object_label": "..."
    }
  ]
}
```

**建议 predicate 示例**：

- `has_step` (circuit → circuit_step)
- `has_projection` (circuit → projection)
- `connects_to` / `projects_to` (region → region via projection)
- `associated_with_function` (region/circuit/projection → function)

**Mirror 目标表**：`mirror_kg_triples`

---

## 11. evidence_uncertainty_review_v1

**用途**：对 LLM 输出补充 evidence 质量、uncertainty、risk flags（post-processing / review 辅助）。

**输出 JSON**：

```json
{
  "evidence_quality": "weak",
  "uncertainty_reason": "...",
  "risk_flags": [
    "low_confidence",
    "needs_literature_verification",
    "cross_granularity_risk",
    "model_conflict"
  ]
}
```

**evidence_quality 建议**：`strong` | `moderate` | `weak` | `insufficient`

---

## 与现有 MVP prompt 对照

| MVP（已实现） | macro_clinical（planned） |
|---------------|---------------------------|
| `same_granularity_connection_completion_v1` | `circuit_steps_to_projections_v1`（step-first） |
| `same_granularity_function_completion_v1` | `region_to_functions_v1` |
| `same_granularity_circuit_completion_v1` | `regions_to_circuits_v1` |
| triple consolidation service | `macro_clinical_triple_generation_v1`（LLM 备用） |

---

## 实现状态

| 项 | 状态 |
|----|------|
| 文档 | ✅ Step 8.5b 双向 + 双模型 |
| `llm_prompt_defaults.py` 常量 | ✅ 11 planned templates |
| task-types API | ✅ `implemented=false` |
| extraction API | ❌ 未实现 |
| Mirror 新表 migration | ❌ 下一步 |
