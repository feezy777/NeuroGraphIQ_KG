# LLM Same-granularity Completion Design

> **文档类型**：LLM 补全任务与输出 schema 设计  
> **版本**：2026-06-15  
> **状态**：规划文档（本轮仅文档，不实现代码、不调用 LLM API）  
> **定位升级**：从「候选脑区字段补全」升级为「同颗粒度脑区知识补全工作台」

---

## 1. Purpose

LLM Extraction in NeuroGraphIQ KG V3 is **not** limited to filling `cn_name`, `en_name`, or aliases on Region Candidates.

Its target role:

```
Brain Region
  → same-granularity connection candidates
  → same-granularity circuit candidates
  → same-granularity function candidates
  → triple candidates
  → Mirror KG
  → human review
  → Final KG
```

Current implementation (MVP 2 Step 1) covers only **region field completion** into `candidate_llm_extractions`. This document defines the **full target design** for subsequent phases.

---

## 2. Core Principles

1. **LLM is not a Final KG writer** — output goes to Mirror KG or candidate-side advisory tables only.
2. **Same-granularity first** — Macro96↔Macro96, AAL3↔AAL3, etc.
3. **Structured JSON only** — every task has a versioned output schema; raw provider response is always stored.
4. **Evidence + uncertainty required** — confidence, uncertainty_reason, needs_human_review default true.
5. **Full lineage** — every item traces to region, resource, batch, candidate, llm_run, prompt, model, reviewer.

---

## 3. Task Types

| task_type | Description | Target mirror object |
|-----------|-------------|---------------------|
| `region_alias_completion` | Aliases and naming variants | mirror_region_facts (optional) |
| `region_description_completion` | Descriptive text for a region | mirror_region_facts |
| `same_granularity_connection_completion` | Region–region connection candidates | mirror_region_connections |
| `same_granularity_circuit_completion` | Multi-region circuit candidates | mirror_region_circuits |
| `same_granularity_function_completion` | Function association candidates | mirror_region_functions |
| `triple_candidate_generation` | Normalized triples from above | mirror_kg_triples |
| `translation` | Cross-language translation | advisory / mirror metadata |
| `evidence_explanation` | Explain why a claim is suggested | mirror_evidence_records |
| `uncertainty_flagging` | Explicit uncertainty annotation | mirror metadata flags |

---

## 4. Provider Abstraction

### 4.1 Supported providers (target)

| Provider | Role |
|----------|------|
| `deepseek` | Primary provider in MVP 2 Step 1 (implemented for region fields) |
| `kimi` | Planned alternate provider with same task contract |
| future | Must implement same `LlmProviderAdapter` interface |

### 4.2 Provider adapter contract (planned)

```typescript
interface LlmProviderAdapter {
  provider: 'deepseek' | 'kimi' | string
  model: string
  extractStructured(input: LlmExtractionTaskInput): Promise<LlmProviderRawResponse>
}
```

### 4.3 Run record fields (minimum)

| Field | Description |
|-------|-------------|
| `llm_run_id` | UUID grouping one or more extraction items |
| `llm_model_provider` | deepseek / kimi |
| `llm_model_name` | e.g. deepseek-chat |
| `prompt_template_id` | stable template identifier |
| `prompt_version` | e.g. v1, v2 |
| `extraction_task_id` | one task within a run |
| `extraction_scope` | region / connection / circuit / function / triple |
| `raw_response` | verbatim provider output |
| `parsed_response` | validated JSON after schema check |
| `status` | pending / succeeded / failed |
| `prompt_tokens`, `completion_tokens`, `latency_ms` | observability |

---

## 5. Input Objects (common envelope)

Every extraction task receives a common envelope plus task-specific payload.

```json
{
  "task_type": "same_granularity_connection_completion",
  "prompt_version": "v1",
  "source_granularity": "macro",
  "source_atlas": "Macro96",
  "source_version": "Brain volume list v1",
  "resource_id": "uuid",
  "import_batch_id": "uuid",
  "candidate_region_id": "uuid",
  "final_region_id": "uuid-or-null",
  "region_metadata": {},
  "optional_evidence_corpus": [],
  "optional_existing_final_kg_snapshot": {},
  "task_payload": {}
}
```

### 5.1 Lineage fields (required on every output item)

- `source_granularity`
- `source_atlas`
- `source_version`
- `resource_id`
- `import_batch_id`
- `candidate_region_id`
- `final_region_id` (if exists)
- `llm_run_id`
- `llm_model_provider`
- `llm_model_name`
- `prompt_template_id`
- `prompt_version`
- `extraction_task_id`
- `extraction_scope`
- `evidence_text`
- `source_document_id` (optional)
- `reviewer_id` (after review)
- `review_record_id` (after review)
- `promotion_record_id` (after promotion)
- `created_at`, `updated_at`

---

## 6. Connection Completion

### 6.1 Input

| Input | Description |
|-------|-------------|
| `source_region` | Anchor region (candidate or final snapshot) |
| `target_region_candidates` | Same-granularity neighbor list |
| `granularity` | macro / meso / micro / molecular |
| `atlas` | Macro96, AAL3, Brainnetome, etc. |
| `region_metadata` | names, laterality, aliases |
| `optional_evidence_corpus` | text snippets, atlas notes |
| `optional_existing_final_kg_snapshot` | read-only context, not write target |

### 6.2 Output schema

```json
{
  "task_type": "same_granularity_connection_completion",
  "items": [
    {
      "source_region_id": "uuid",
      "target_region_id": "uuid",
      "connection_type": "functional_connectivity",
      "directionality": "directed",
      "strength": "moderate",
      "modality": "resting-state fMRI",
      "evidence_text": "…",
      "confidence": 0.62,
      "uncertainty_reason": "atlas-level inference only",
      "needs_human_review": true,
      "suggested_triple": {
        "subject": "Macro96:left hippocampus",
        "predicate": "functionally_connects_to",
        "object": "Macro96:left amygdala"
      },
      "risk_flags": ["low_evidence", "same_granularity_only"]
    }
  ]
}
```

### 6.3 connection_type enum

- `structural_connection`
- `functional_connectivity`
- `effective_connectivity`
- `projection`
- `association`
- `coactivation`
- `uncertain_connection`

### 6.4 directionality enum

- `directed`
- `undirected`
- `bidirectional`
- `unknown`

---

## 7. Circuit Completion

### 7.1 Input

| Input | Description |
|-------|-------------|
| `region_set` | Same-granularity region IDs |
| `connection_candidates` | Optional pre-existing mirror connections |
| `known_function_context` | Optional function hints |
| `granularity`, `atlas` | Scope guards |

### 7.2 Output schema

```json
{
  "task_type": "same_granularity_circuit_completion",
  "items": [
    {
      "circuit_name": "memory_related_circuit",
      "involved_region_ids": ["uuid", "uuid"],
      "ordered_region_chain": ["uuid-left-hippocampus", "uuid-left-amygdala"],
      "circuit_type": "memory_related",
      "function_association": "memory",
      "evidence_text": "…",
      "confidence": 0.55,
      "needs_human_review": true,
      "suggested_triples": [
        {
          "subject": "memory_related_circuit",
          "predicate": "has_participant_region",
          "object": "Macro96:left hippocampus"
        }
      ]
    }
  ]
}
```

### 7.3 circuit_type enum

- `sensory_circuit`
- `motor_circuit`
- `limbic_circuit`
- `cognitive_control_circuit`
- `default_mode_related`
- `salience_related`
- `memory_related`
- `uncertain_circuit`

---

## 8. Function Completion

### 8.1 Input

| Input | Description |
|-------|-------------|
| `region` | Target region |
| `circuit_candidates` | Optional circuits involving the region |
| `atlas`, `granularity` | Scope |
| `optional_evidence` | Text / document references |

### 8.2 Output schema

```json
{
  "task_type": "same_granularity_function_completion",
  "items": [
    {
      "region_id": "uuid",
      "function_term": "memory",
      "function_category": "memory",
      "relation_type": "associated_with",
      "evidence_text": "…",
      "confidence": 0.58,
      "uncertainty_reason": "literature summary not verified",
      "needs_human_review": true,
      "suggested_triple": {
        "subject": "Macro96:left hippocampus",
        "predicate": "associated_with_function",
        "object": "memory"
      }
    }
  ]
}
```

### 8.3 function_category enum

- `motor`, `sensory`, `visual`, `auditory`, `language`, `memory`, `emotion`
- `executive_control`, `attention`, `autonomic`, `default_mode`, `salience`, `reward`
- `unknown`

### 8.4 relation_type enum

- `involved_in`
- `associated_with`
- `necessary_for`
- `modulates`
- `participates_in`
- `uncertain_association`

---

## 9. Triple Candidate Generation

Triple generation may be:

- a dedicated `triple_candidate_generation` task; or
- embedded as `suggested_triple` / `suggested_triples` on connection / circuit / function outputs.

Normalized triple records land in **Mirror KG** (`mirror_kg_triples`), not Final KG.

See `TRIPLE_MODEL_AND_ONTOLOGY_DESIGN.md` for predicate vocabulary.

---

## 10. Region Field Completion (current MVP 2 Step 1)

Implemented schema (`LlmSuggestion` in `backend/app/schemas/llm_extraction.py`):

- `suggested_cn_name`, `suggested_en_name`, `suggested_aliases`
- `suggested_description`, `suggested_region_base_name`, `suggested_laterality`
- `confidence`, `evidence_summary`, `risk_flags`, `needs_human_review`

Storage: `candidate_llm_extractions.structured_result` (candidate-side advisory).

**Migration path**: region field suggestions may later also write mirror_region_facts, but must not bypass review for any fact-like promotion.

---

## 11. Workbench Presentation (target)

LLM Extraction page evolves from a single candidate list into tabs:

| Tab | Content |
|-----|---------|
| Region Completion | Current MVP 2 Step 1 behavior |
| Connections | Connection candidates + diff vs Mirror KG |
| Circuits | Circuit graph preview + participant regions |
| Functions | Function panel per region |
| Triples | Triple candidate table |
| Mirror Review Queue | Items pending rule check / human review |

Each tab must show:

- provider / model / prompt_version
- confidence + uncertainty
- evidence excerpt
- review status
- link to source region / batch / resource

**No** “Approve” or “Promote to Final” buttons on LLM tabs.

---

## 12. Risk Controls

| Risk | Control |
|------|---------|
| Hallucinated connections | same-granularity validation, entity existence check, evidence required warning |
| Cross-granularity leakage | explicit mapping-only rule in validator |
| Cost runaway | batch size cap (existing MAX_BATCH_SIZE=20 pattern) |
| Unstructured output | JSON schema validation; failed parse → status=failed row |
| Silent auto-promotion | forbidden by architecture; promotion only after human review |
| Provider lock-in | provider adapter + prompt_template_id versioning |

---

## 13. Path to Mirror KG

```
LLM Extraction Run
  → parse + validate JSON
  → write mirror_* candidate rows (status=llm_suggested)
  → link mirror_llm_run_links
  → optional mirror_evidence_records
  → surface in Workbench Mirror Review Queue
```

LLM output **never** skips Mirror KG to write Final KG.

---

## 14. Path to Final KG

Promotion conditions (all required):

1. mirror item status = `human_approved`
2. rule validation passed (or warnings acknowledged by reviewer)
3. reviewer_id + review_record_id present
4. promotion service maps mirror row → final_* row with full lineage
5. audit in `promotion_records` (or successor promotion audit tables)

---

## 15. Planned API Endpoints (Phase D)

| Method | Path | Purpose |
|--------|------|---------|
| POST | `/api/llm-extraction/region-connections` | Same-granularity connection completion |
| POST | `/api/llm-extraction/region-circuits` | Circuit completion |
| POST | `/api/llm-extraction/region-functions` | Function completion |
| POST | `/api/llm-extraction/triples` | Triple candidate generation |
| POST | `/api/llm-extraction/batch` | Batch extraction (existing pattern) |
| POST | `/api/candidates/{candidate_id}/llm-extract` | Single region field extract (existing) |

---

## 16. Relationship to Existing Code

| Component | Current state |
|-----------|---------------|
| `candidate_llm_extractions` | Region field advisory only |
| `LlmExtractionPage.tsx` | Candidate list + field comparison UI |
| `llm_extraction_service.py` | DeepSeek region field extract |
| Mirror KG tables | **Not yet migrated** — documented in `MIRROR_KG_AND_FINAL_PROMOTION_DESIGN.md` |

---

*维护说明：prompt_version 或 JSON schema 变更时必须 bump `PROMPT_VERSION` 并更新本文件。*
