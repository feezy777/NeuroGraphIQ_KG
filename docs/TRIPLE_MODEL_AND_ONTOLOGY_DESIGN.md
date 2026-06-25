# Triple Model and Ontology Design

> **文档类型**：三元组模型与谓词本体设计  
> **版本**：2026-06-15  
> **状态**：规划文档（本轮仅文档，不实现代码）

---

## 1. Purpose

The **Triple Layer** provides a unified subject–predicate–object query surface over:

- regions;
- connections;
- circuits;
- functions;
- mappings;
- evidence.

Triples exist in two stores:

| Store | Table | Status |
|-------|-------|--------|
| Mirror KG | `mirror_kg_triples` | LLM / curated candidates |
| Final KG | `final_kg_triples` | Human-approved official facts |

---

## 2. Triple Structure

```json
{
  "id": "uuid",
  "subject_type": "region",
  "subject_id": "uuid",
  "subject_label": "Macro96:left hippocampus",
  "predicate": "functionally_connects_to",
  "object_type": "region",
  "object_id": "uuid",
  "object_label": "Macro96:left amygdala",
  "source_granularity": "macro",
  "source_atlas": "Macro96",
  "confidence_score": 0.62,
  "uncertainty_reason": "atlas-level inference",
  "evidence_level": "llm_suggested",
  "review_status": "human_review_pending",
  "llm_generated": true,
  "human_approved": false,
  "llm_run_id": "uuid",
  "review_record_id": null,
  "promotion_record_id": null
}
```

---

## 3. Subject / Object Types

| subject_type / object_type | Description |
|----------------------------|-------------|
| `region` | Brain region entity (candidate, mirror, or final id) |
| `circuit` | Named circuit |
| `function` | Function term or function node |
| `mapping` | Mapping assertion node (optional) |
| `evidence` | Evidence record reference |
| `literal` | String / categorical literal object |

---

## 4. Connection Predicates

Used when subject and object are regions (same granularity unless mapping predicate).

| Predicate | Meaning | Example |
|-----------|---------|---------|
| `structurally_connects_to` | Anatomical connection | Macro96:A --structurally_connects_to--> Macro96:B |
| `functionally_connects_to` | Functional connectivity | Macro96:left hippocampus --functionally_connects_to--> Macro96:left amygdala |
| `effectively_connects_to` | Effective connectivity | … |
| `projects_to` | Directed projection | … |
| `associated_with` | Weak association | … |
| `coactivates_with` | Coactivation | … |
| `has_uncertain_connection_to` | Explicit uncertainty | … |

**Direction**: stored in connection record; triple may include `predicate_modifiers: { directionality: "directed" }`.

---

## 5. Circuit Predicates

| Predicate | Meaning |
|-----------|---------|
| `has_participant_region` | Circuit includes region |
| `has_ordered_participant` | Ordered chain position |
| `instance_of_circuit_type` | circuit_type enum |
| `circuit_connects` | Circuit-level summary edge (optional) |

Example:

```
memory_related_circuit --has_participant_region--> Macro96:left hippocampus
memory_related_circuit --has_participant_region--> Macro96:left amygdala
memory_related_circuit --associated_with_function--> memory
```

---

## 6. Function Predicates

| Predicate | Meaning |
|-----------|---------|
| `associated_with_function` | Region ↔ function term |
| `involved_in_function` | Stronger involvement |
| `necessary_for_function` | Necessity claim (high review bar) |
| `modulates_function` | Modulatory relation |
| `participates_in_process` | Process participation |

Examples:

```
Macro96:Brain stem --associated_with_function--> autonomic_control
Macro96:left putamen --participates_in_process--> motor_control
```

---

## 7. Mapping Predicates

Mapping triples belong to the **Mapping Layer**, not Connection Layer.

| Predicate | Meaning |
|-----------|---------|
| `close_match` | Strong cross-atlas alignment |
| `partial_match` | Partial overlap |
| `related_to` | Weak relation |
| `not_same_as` | Explicit non-equivalence |
| `maps_to_granularity` | Granularity bridge metadata |

Examples:

```
Macro96:left hippocampus --close_match--> AAL3:Hippocampus_L
Macro96:left hippocampus --not_same_as--> AAL3:ParaHippocampal_L
```

**Rule**: cross-granularity “same node” merges are forbidden; use mapping triples.

---

## 8. Evidence Predicates

| Predicate | Meaning |
|-----------|---------|
| `supported_by_evidence` | Links fact to evidence record |
| `extracted_from_document` | Document provenance |
| `generated_by_llm_run` | LLM provenance |
| `confirmed_by_reviewer` | Human review provenance |

Evidence triples support audit and export; they do not replace `mirror_evidence_records` tabular storage.

---

## 9. Naming Conventions

### 9.1 Entity labels

```
{source_atlas}:{region_display_name}
```

Examples:

- `Macro96:left hippocampus`
- `AAL3:Hippocampus_L`
- `Brainnetome:A1_L`

### 9.2 Predicate names

- snake_case English verbs;
- stable across UI, API, and export;
- versioned in ontology registry (future `ontology_predicate_registry` — planned).

### 9.3 Triple identity

Suggested unique key (for dedup):

```
(subject_type, subject_id, predicate, object_type, object_id, source_atlas, source_granularity)
```

---

## 10. Uncertainty Expression

Every triple candidate should support:

| Field | Type | Description |
|-------|------|-------------|
| `confidence_score` | float 0–1 | Model confidence |
| `uncertainty_reason` | string | Why uncertain |
| `evidence_level` | enum | parser / manual / llm_suggested / literature / reviewer_confirmed |
| `review_status` | enum | mirrors Mirror KG status subset |
| `llm_generated` | bool | true if LLM originated |
| `human_approved` | bool | false until review |

**UI rule**: low confidence or `llm_generated=true && human_approved=false` must be visually distinct from Final KG triples.

---

## 11. Example Triple Sets

### 11.1 RegionConnection

```
Macro96:left hippocampus --functionally_connects_to--> Macro96:left amygdala
Macro96:left hippocampus --participates_in--> memory_related_circuit
Macro96:left hippocampus --associated_with_function--> memory
```

### 11.2 Function

```
Macro96:Brain stem --associated_with_function--> autonomic_control
Macro96:left putamen --participates_in_process--> motor_control
```

### 11.3 Circuit

```
memory_related_circuit --has_participant_region--> Macro96:left hippocampus
memory_related_circuit --has_participant_region--> Macro96:left amygdala
memory_related_circuit --associated_with_function--> memory
```

### 11.4 Mapping

```
Macro96:left hippocampus --close_match--> AAL3:Hippocampus_L
Macro96:left hippocampus --not_same_as--> AAL3:ParaHippocampal_L
```

---

## 12. KG Export Planning (Phase I)

| Format | Content |
|--------|---------|
| JSONL | one triple per line + lineage metadata |
| CSV | flat triple table for spreadsheets |
| RDF/Turtle | mapped predicates to SKOS / custom ontology IRIs |

Export rules:

- Mirror triples export with `graph=mirror` label;
- Final triples export with `graph=final`;
- never mix without explicit `provenance_status` column.

---

## 13. Relationship to Other Documents

| Document | Relationship |
|----------|--------------|
| `LLM_SAME_GRANULARITY_COMPLETION_DESIGN.md` | Generates `suggested_triple` fields |
| `MIRROR_KG_AND_FINAL_PROMOTION_DESIGN.md` | mirror_kg_triples → final_kg_triples promotion |
| `NEUROGRAPHIQ_KG_V3_TARGET_ARCHITECTURE.md` | Triple Layer in seven-layer model |

---

## 14. Current Implementation Status

| Capability | Status |
|------------|--------|
| `final_brain_regions` | ✅ implemented |
| `mirror_kg_triples` | ❌ not migrated |
| `final_kg_triples` | ❌ not migrated |
| Triple query API | ❌ planned |
| LLM triple generation | ❌ planned |

Legacy `staging_connections` / `kg_connections` in older migrations are **not** the target triple model; new work should follow `mirror_kg_triples` / `final_kg_triples`.

---

*维护说明：新增谓词时必须更新本文件 predicate 表与 `prompt_version`。*
