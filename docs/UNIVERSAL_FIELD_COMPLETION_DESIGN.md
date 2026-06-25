# Universal Field Completion Design

**Task:** Formal-field Data Center Display and Universal DeepSeek Field Completion Design  
**Step:** 10.1 ? design only  
**Date:** 2026-06-17  
**Status:** Step 10.3 backend implemented; Step 10.4 Data Center UI integrated

---

## 1. ????

1. ? **????** ???? `region_field_completion` ??? **????**????? Mirror / candidate ?????
2. ?? provider?**DeepSeek**?`deepseek-chat` ? settings ?? model??
3. ???? **?? Mirror / candidate ?**??? `final_*` / `kg_*`???? approve / promote?
4. ????????`llm_field_completion_runs` + `llm_field_completion_items`?Step 10.3 migration??
5. ? Data Center formal-field ???Human Review?Promotion ?????

---

## 2. ??????????????

| ?? | ?? |
|------|------|
| ? `region_field_completion` | ????????????????????? evidence / confidence |
| ? extraction task ???? | ??????????? |
| ????????????????? | ?? target_type + target_ids ?? |

**???** ?? API??? prompt ????? audit ???? UI ???Data Center?????????

---

## 3. ? region_field_completion ???

| ? | region_field_completion???? | universal field completion??? |
|----|--------------------------------|----------------------------------|
| target | `candidate_brain_regions` | 10 ? target_type |
| task_type | `region_field_completion` | `universal_field_completion` |
| template | `region_field_completion_v1` | `universal_field_completion_v1` |
| ?? | candidate ???? | mirror / candidate ?? |
| API | `POST /region-field-completion` | `POST /field-completion/run` |

**?????** Step 10.3 ?? universal API ??`region_field_completion` ?? `target_type=candidate_region` ? thin wrapper ???????????? endpoint?

---

## 4. ???????target_type?

| target_type | Mirror / ?? | ?? |
|-------------|---------------|------|
| `candidate_region` | `candidate_brain_regions` | ???? |
| `projection` | `mirror_region_connections` | ??/?? |
| `region_function` | `mirror_region_functions` | ???? |
| `circuit` | `mirror_region_circuits` | ?? |
| `circuit_step` | `mirror_circuit_steps` | ???? |
| `projection_function` | `mirror_projection_functions` | ???? |
| `circuit_function` | **planned** `mirror_circuit_functions` | ???? |
| `circuit_projection_membership` | `mirror_circuit_projection_memberships` | ??????? |
| `triple` | `mirror_kg_triples` | ??? |
| `evidence` | `mirror_evidence_records` | ?? |

---

## 5. ??????

? `formalFieldMappings.ts` / ?? registry ???????

- **requiredFields** ? ??? blocking review
- **enrichableFields** ? ?? LLM ??
- **readonlyFields** ? id, created_at, promotion_status ?????
- **suggestOnlyFields** ? ???????????? policy?

**field_scope ???**

| ? | ?? |
|----|------|
| `missing_only` | ?? null/?/unknown ? enrichable ???**??**? |
| `selected_fields` | ? `selected_fields` ?? |
| `all_enrichable_fields` | ?? enrichable??? overwrite_policy ??? |

---

## 6. DeepSeek provider

- **???** `provider: "deepseek"`, `model_name: null` ? settings `get_deepseek_runtime_config().default_model`
- **???** kimi???? extraction ???????
- **dry_run?** ??? provider???? prompt + preview JSON
- **???** mock provider?????? DeepSeek

---

## 7. Prompt ??

### 7.1 Template key

`universal_field_completion_v1`

### 7.2 ????

```json
{
  "target_type": "projection",
  "target_schema": { "...": "formal field definitions" },
  "current_object_json": { "...": "mirror row as JSON" },
  "missing_fields_json": ["evidence_text", "strength"],
  "selected_fields_json": [],
  "related_context_json": {
    "source_region": { "en_name": "..." },
    "target_region": { "en_name": "..." }
  },
  "evidence_json": [ { "evidence_text": "...", "source": "..." } ],
  "final_schema_field_definitions_json": { "...": "from formal mapping" },
  "overwrite_policy": "fill_missing_only"
}
```

### 7.3 System prompt ??

- ??? JSON
- ?????????
- ??? ? `null` + `uncertainty_reason`
- ??????? `allowed_fields`
- ??? final approval / promotion decision
- ?????? **Mirror ????**??????

### 7.4 ?? JSON schema

```json
{
  "field_updates": [
    {
      "field_name": "evidence_text",
      "value": "...",
      "confidence": 0.82,
      "evidence_text": "...",
      "reasoning_summary": "...",
      "uncertainty_reason": null
    }
  ],
  "warnings": []
}
```

---

## 8. API ???Step 10.3 ???

### 8.1 Run field completion

```
POST /api/llm-extraction/field-completion/run
```

**Request:**

```json
{
  "provider": "deepseek",
  "model_name": "deepseek-chat",
  "target_type": "projection",
  "target_ids": ["uuid-1", "uuid-2"],
  "field_scope": "missing_only",
  "selected_fields": [],
  "dry_run": true,
  "create_mirror_updates": true,
  "create_evidence": true,
  "overwrite_policy": "fill_missing_only",
  "source_context": {
    "include_existing_evidence": true,
    "include_related_objects": true,
    "include_provenance": true
  }
}
```

**?????**

| ?? | ?? |
|------|------|
| provider | ?? deepseek |
| target_type | ? �4 |
| target_ids | ?? UUID |
| field_scope | missing_only / selected_fields / all_enrichable_fields |
| overwrite_policy | fill_missing_only????/ suggest_only / overwrite_with_review |
| dry_run | true ? ? prompt + preview???? |
| create_mirror_updates | true ? ?? field_updates ? mirror?? policy ??? |
| create_evidence | true ? ???? mirror_evidence_records |
| create_mirror_updates | **??** ? final_* / kg_* |

**Response:**

```json
{
  "run_id": "uuid",
  "status": "succeeded",
  "target_type": "projection",
  "target_count": 10,
  "updated_count": 8,
  "skipped_count": 2,
  "field_updates": [
    {
      "target_id": "uuid",
      "field_name": "evidence_text",
      "old_value": null,
      "new_value": "...",
      "confidence": 0.82,
      "evidence_text": "...",
      "update_status": "applied"
    }
  ],
  "warnings": [],
  "errors": []
}
```

**update_status ???** `applied` | `suggested` | `skipped` | `failed`

### 8.2 ?? endpoints?Step 10.3+?

| Method | Path | ?? |
|--------|------|------|
| GET | `/field-completion/runs` | ?? |
| GET | `/field-completion/runs/{id}` | ?? + items |
| GET | `/field-completion/options` | target_types, fields per type, providers |

---

## 9. ?????????

1. ? ? `candidate_brain_regions`?candidate_region?
2. ? ?? `mirror_*` ??? + ?? `mirror_evidence_records`
3. ? ? `llm_field_completion_runs` / `llm_field_completion_items`
4. ? ? `llm_extraction_runs` / `items`?task_type=`universal_field_completion`??? lineage
5. ? ???? `final_*`
6. ? ?? `kg_*`
7. ? ??? `promotion_status` ? `promoted`
8. ? ??? `review_status=approved` / `human_approved`
9. ????? **??** rule validation + human review
10. **overwrite ???** ?????????? ? `suggest_only` ??? items ?? apply

---

## 10. ?????????Step 10.3 migration?

### 10.1 llm_field_completion_runs

| ? | ?? | ?? |
|----|------|------|
| id | UUID PK | |
| target_type | VARCHAR | |
| target_count | INT | |
| provider | VARCHAR | |
| model_name | VARCHAR | |
| field_scope | VARCHAR | |
| selected_fields_json | JSONB | |
| overwrite_policy | VARCHAR | |
| dry_run | BOOL | |
| status | VARCHAR | pending/running/succeeded/failed |
| request_json | JSONB | |
| summary_json | JSONB | updated/skipped counts |
| warnings_json | JSONB | |
| errors_json | JSONB | |
| created_at | TIMESTAMPTZ | |
| completed_at | TIMESTAMPTZ | |

### 10.2 llm_field_completion_items

| ? | ?? | ?? |
|----|------|------|
| id | UUID PK | |
| run_id | UUID FK | |
| target_type | VARCHAR | |
| target_id | UUID | |
| field_name | VARCHAR | |
| old_value_json | JSONB | |
| suggested_value_json | JSONB | |
| applied_value_json | JSONB | |
| confidence | NUMERIC | |
| evidence_text | TEXT | |
| update_status | VARCHAR | |
| error_message | TEXT | |
| created_at | TIMESTAMPTZ | |

**????? migration?**

---

## 11. UI ??

| ?? | Step | ?? |
|------|------|------|
| Data Center ????? | 10.4 ? | ?? ? ???? modal |
| ??? drawer | 10.4 ? | ????? |
| ExtractionResultModal | 10.5 | ???? ? ???? created ids |
| LLM ?? Mirror tab | ?? | ?? Data Center ? filter |

**Modal ???10.4 ???** ?? field_scope / overwrite_policy / provider ? dry_run preview?prompt_preview + suggestions?? ???? ? ?? run/items ? ?? Data Center ???

**Modal ?????** `provider=deepseek`?`model=deepseek-chat`?`field_scope=missing_only`?`overwrite_policy=fill_missing_only`?`dry_run=true`?`create_mirror_updates=true`?`create_evidence=false`?`prompt_template_key=universal_field_completion_v1`?

**Step 10.4.1 Real schema alignment?** ???? allowed_fields ???? NeuroGraphIQ_KG_V3 ?? formal schema?`macro_clinical.*`??`name_cn`?`name_en`?`circuit_class`?`description` ??? `enrichable=true`?????????`circuit_class` ?? Mirror ? `circuit_type`?`function_term_en/cn` ?? Mirror ? `function_term`?

---

## 12. ? Data Center ???

- formal ??? + missing badge ????????
- **Step 10.2?** Data Center ???????? / ????????
- **Step 10.4?** ???? placeholder ??? `FieldCompletionModal`??? Universal Field Completion API
- ????? refresh ???missing badge ???Step 10.4 ??
- provenance drawer ?????? field_completion run_id?Step 10.4+ ?????

---

## 13. ? Human Review / Promotion ???

```
Extract ? Mirror (incomplete)
    ? Field Completion (mirror-only)
    ? Rule Validation
    ? Human Review
    ? Promotion ? Final_*
```

???? **???** validation/review?????? `mirror_status` ?? `llm_enriched`?Step 10.3 ???????? approved?

---

## 14. ??????

| Step | ?? |
|------|------|
| 10.1 | ??? + DATA_CENTER_FORMAL_FIELD_ALIGNMENT + mapping |
| 10.2 | ? Data Center formal ? + missing badge + ???? Preview ?? |
| 10.3 | ? migration `032_universal_field_completion.sql` + schemas + registry + service + router + prompt + mock pytest |
| 10.4 | ? Data Center ???? UI + dry_run preview + run/items viewer + table refresh |
| 10.5 | ExtractionResultModal ?? |
| 10.6 | post-completion validation trigger + review queue ?? |

---

## 15. Step 10.3 ????

### 15.1 Migration

`backend/migrations/032_universal_field_completion.sql` ? ???????? migration?

### 15.2 API?????

| Method | Path |
|--------|------|
| POST | `/api/llm-extraction/field-completion/run` |
| GET | `/api/llm-extraction/field-completion/runs` |
| GET | `/api/llm-extraction/field-completion/runs/{run_id}` |
| GET | `/api/llm-extraction/field-completion/items` |

### 15.3 Registry

`backend/app/services/field_completion_registry.py` ? 10 ? target_type?`circuit_function` supported=false ? API 501?

### 15.4 Overwrite policy

| Policy | ?? |
|--------|------|
| `fill_missing_only` | ?????????? |
| `suggest_only` | ?? completion_items??????? |
| `overwrite_with_review` | ??? suggest_only ?? + warning |

### 15.5 dry_run

- ??? DeepSeek / provider
- ?? run status=`dry_run`
- ?? `prompt_preview` + items status=`prompt_preview`
- ??????

### 15.6 ??

`backend/tests/test_llm_field_completion.py` ? 17 tests?mock provider???? DeepSeek ???

---

## 16. Step 10.4 ??????

### 16.1 ??

- `frontend/src/pages/data-center/FieldCompletionModal.tsx` ? ? Modal
- `frontend/src/pages/data-center/fieldCompletionUtils.ts` ? ????
- `FormalObjectTableSection.tsx` / `MirrorKgPanel.tsx` / `MacroClinicalDataPanel.tsx` ? ??? refresh

### 16.2 Modal ??????

| ?? | ??? |
|------|--------|
| provider | deepseek |
| model_name | deepseek-chat |
| field_scope | missing_only |
| overwrite_policy | fill_missing_only |
| dry_run | true?Preview ??? |
| create_mirror_updates | true |
| create_evidence | false |
| prompt_template_key | universal_field_completion_v1 |

### 16.3 ??

1. ?? / ?? / detail drawer ?? Modal
2. ??? Dry Run Preview?? `dry_run=true`??? prompt_preview + suggestions
3. ????????? ???? ? `dry_run=false` ? ?? run/items
4. `onCompleted` ???? Data Center ???MissingFieldsBadge ??
5. Modal tab??? Completion Runs / Items?????

### 16.4 ??

- API 404?`???? API ????`
- `circuit_function`?unsupported???? API
- ???????????

---

## 18. Step 10.4.2 ? Real Formal Field Completion Alignment (2026-06-17)

### 18.1 ??

Step 10.4.1 ????Data Center ????? NeuroGraphIQ_KG_V3 schema??????
`selected_fields` / `allowed_fields` ???? Mirror ????`circuit_name`, `circuit_type`,
`function_term`?????????

### 18.2 ????

#### ?? `field_completion_registry.py`

- `TargetTypeRegistryEntry` ?????
  - `formal_schema: str` ? ??? schema?? `macro_clinical`?
  - `formal_table: str` ? ??????? `circuit`?
  - `formal_to_mirror: dict[str, str]` ? ????? ? Mirror ORM ???????? direct write?
  - `overlay_field_names: tuple[str, ...]` ? Mirror ??????? overlay ?????
- ?? target_type ? `enrichable_fields` / `required_fields` ??????????

**circuit ???**
```
enrichable_fields: name_en, name_cn, circuit_class, description, remark, attributes, source_db, status
formal_to_mirror: { name_en ? circuit_name, circuit_class ? circuit_type, description ? description }
overlay_field_names: name_cn, remark, attributes, source_db, status, ?
```

**projection_function ???**
```
enrichable_fields: function_term_en, function_term_cn, function_domain, ?
formal_to_mirror: { function_term_en ? function_term, confidence_score ? confidence }
overlay_field_names: function_term_cn, function_domain, function_role, effect_type, ?
```

**projection_function ???? mirror_projections?Step 10.6.10??**

- projection_function extraction ??????? `mirror_region_connections` ? projection_id?
- composite workflow ? `provider_call_count=0` ? connection step ????projection_function step ??? `skipped_dependency_failed`????? LLM ???
- connection step 语义 `succeeded_no_edges` 时 fn step 为 `skipped_no_projection`（persistent status 仍为 succeeded / skipped，非 failed）。
- **no_edges workflow 不产生 Projection**；`projection_function` 与字段补全 **不应消费** no_edges run 的输出（无 projection_id）。
- **`failed_parse_error` workflow 不进入 projection_function**；应显示 dependency failed / 解析失败，而非“未调用模型”。

**LLM extraction workflow 可取消性（Step 10.6.11）**

- 用户可在运行中取消 composite workflow；cancel 后不再调度新 pack，late provider response 不写 mirror。
- cleanup 仅删除 `attributes.composite_workflow_run_id` 匹配的本轮 mirror 候选；field completion 不应消费已取消 run 的 mirror 候选。

**LLM extraction workflow 事件日志（Step 10.6.16）**

- composite workflow 在 `result_summary_json.events` 记录结构化事件（pairs_generated、packs_built、provider_call_start、parse_error 等）；status API 返回 `recent_events`（最近 50 条）。
- 前端日志控制台通过 polling 桥接这些事件，便于诊断 provider 调度与 parser 失败。
- field completion **不应消费** failed / cancelled / cleanup_done workflow 的输出；`provider_call_count=0` 在 running 阶段不是终态失败。

**circuit_step ???**
```
enrichable_fields: step_name_en, step_name_cn, step_no, role_in_circuit, description, ?
formal_to_mirror: { step_name_en ? step_name, description ? description }
overlay_field_names: step_name_cn, step_no, role_in_circuit, ?
```

#### ?? `llm_field_completion_service.py`

- `apply_field_update` ?? `entry` ????????????
  - ???? `overlay_field_names`??? `normalized_payload_json["formal_field_overlay"][field_name]`
  - ???? `formal_to_mirror`?`setattr(target, mirror_col, value)`
  - ????? ORM table columns?????? overlay ??
- `build_target_context` ? `target_schema_json` ?? `formal_database`, `formal_schema`,
  `formal_table`, `overlay_fields`, `readonly_fields`, `note`??? LLM ?????????
- `get_field_value` ???? direct ORM ?????? `normalized_payload_json.formal_field_overlay`?

#### ?? Router `llm_field_completion.py`

- `POST /run`?? `field_scope=selected_fields` ?????? `selected_fields` ??????
  - ?? `resolve_field_name` ??????? ? ?? 422 `INVALID_SELECTED_FIELDS`
  - ?????? `invalid_fields` ??

#### ?? `formalFieldMappings.ts`

- `getFieldValue` ?? overlay ???? mirrorFieldCandidates ?????????
  `normalized_payload_json`, `raw_payload_json`, `attributes`, ???? `formal_field_overlay`
  ?? `column.finalField`????????? overlay ???

#### ?? `fieldCompletionUtils.ts`

- ?? `getEnrichableFormalFields(mapping)` ? ???? enrichable ?? `finalField`???????
- ?? `validateSelectedFormalFields(selectedFields, mapping)` ? ????????????? enrichable ??

### 18.3 write ??

| ???? | ?? | ???? |
|---|---|---|
| direct?Mirror ????? | `description` | `setattr(target, "description", value)` |
| formal_to_mirror??????? | `name_en` ? `circuit_name` | `setattr(target, "circuit_name", value)` |
| overlay?Mirror ???? | `name_cn`, `remark` | `normalized_payload_json["formal_field_overlay"]["name_cn"]` |

### 18.4 ??

- `llm_field_completion_items.field_name` = ????????? `name_cn`?
- `update_status`: `applied` (direct or overlay), `suggested`, `skipped_existing_value`,
  `skipped_invalid_field`, `skipped_target_not_found`, `failed`

### 18.5 ??

- ?? `macro_clinical.*`?????
- ?? `final_*`?`kg_*`
- ??? approve / promote
- ??? DB migration?overlay ???? JSONB ??

### 18.6 API ??????Step 10.4.3?

**????**?`backend/app/main.py`??

```python
app.include_router(
    llm_field_completion.router,
    prefix="/api/llm-extraction/field-completion",
    tags=["Field Completion"],
)
```

**??**?

| ?? | ?? | ?? |
|---|---|---|
| POST | `/run` | dry_run ????? |
| GET | `/runs` | ???`target_type`, `limit`? |
| GET | `/runs/{run_id}` | ?? + items |
| GET | `/items` | ? run_id / target ?? |

**dry_run ????**?`status=dry_run`?`prompt_preview` ? template ? per-target previews???? DeepSeek?

**404 troubleshooting**?

1. ?? `openapi.json` ? `field-completion` ???
2. ???? 8002 ???? `backend/.venv` + ?? `run_server.py`????? Python??
3. ???????`registered llm_field_completion router prefix=/api/llm-extraction/field-completion`?
4. ? dry_run ?? 500 `UndefinedTable`????? `migrations/032_universal_field_completion.sql`?

---

## 19. Step 10.4.4 ? dry_run=false ??? Mirror Overlay ?? (2026-06-17)

### 19.1 apply_field_update

???? `apply_field_update(target, field_name, value, overwrite_policy, entry, run_id, confidence)`?

| ?? | ?? | ???? | item status |
|------|------|----------|-------------|
| readonly | `GLOBAL_READONLY_FIELDS` | ?? | `skipped_readonly_field` |
| overlay | `overlay_field_names`?? `name_cn`? | `normalized_payload_json.formal_field_overlay` | `applied_overlay` |
| direct | `formal_to_mirror` ???? | Mirror ORM ? | `applied_direct` |
| suggest_only | ??? `overwrite_with_review` | ?? | `suggested` |
| fill_missing_only | ????? | ?? | `skipped_existing_value` |

Mirror ??? `attributes` ?? overlay ?? `normalized_payload_json`?JSONB `flag_modified` ???????

### 19.2 run summary

`run.summary_json` ?????`target_count`?`updated_count`?`suggested_count`?`skipped_count`?`failed_count`?`applied_direct_count`?`applied_overlay_count`?`invalid_field_count`?`readonly_field_count`?

`run.status`?`succeeded` / `partially_succeeded` / `failed` / `dry_run`?

### 19.3 item update_status

`applied_direct`?`applied_overlay`??? legacy `applied`??`suggested`?`skipped_existing_value`?`skipped_invalid_field`?`skipped_readonly_field`?`skipped_target_not_found`?`failed`?

### 19.4 Data Center overlay ??

??? `getFieldValue` ? `normalized_payload_json.formal_field_overlay` ??????? Modal ? `applied_overlay` ???Overlay ???badge?

---

## 20. Step 10.5.1 ? Runtime Hook Stabilization and API Registration (2026-06-22)

### 20.1 API ????

| ?? | ???? |
|---|---|
| POST | `/api/llm-extraction/field-completion/run` |
| GET | `/api/llm-extraction/field-completion/runs` |
| GET | `/api/llm-extraction/field-completion/runs/{run_id}` |
| GET | `/api/llm-extraction/field-completion/items` |

??? `backend/app/main.py`?Vite dev proxy ?? `http://127.0.0.1:8002`?

### 20.2 dry_run ????

`POST /run` + `dry_run=true`?

- `status`: `dry_run`
- `prompt_preview`: template + per-target previews?`allowed_fields` ?? NeuroGraphIQ_KG_V3 formal ????? circuit ? `name_cn`, `name_en`, `circuit_class`?
- ??? DeepSeek??? Mirror / ??? / `final_*` / `kg_*`

### 20.3 runs/items ????

| ?? | ?? |
|---|---|
| GET `/runs` | 200?????? `items: []`, `total: 0` |
| GET `/runs/{id}` | ??? ? ??? 404 `{ code: RUN_NOT_FOUND }` |
| GET `/items` | 200???? ? ??? |

### 20.4 404 troubleshooting

1. ???? **8002** ???? `backend/.venv` + `run_server.py`????? Python??
2. ??????`registered llm_field_completion router prefix=/api/llm-extraction/field-completion`?
3. ??? Network 404 ?????????? API ????????????????? tab ???? 404 ???????
4. dry_run 500 `UndefinedTable` ? ?? `migrations/032_universal_field_completion.sql`?

---

## 21. Step 10.5.2 ? dry_run=false Execution and Overlay Display (2026-06-22)

### 21.1 apply_field_update

| ?? | ?? | ???? | item status |
|------|------|----------|-------------|
| overlay | `overlay_write_fields` | `normalized_payload_json.formal_field_overlay`?API ?? `attributes`? | `applied_overlay` |
| direct | `direct_write_fields` / `formal_to_mirror` | Mirror ORM ? | `applied_direct` |
| suggest_only / overwrite_with_review | ?? | ?? | `suggested` |
| fill_missing_only + ??? | overlay ? direct ?? | ?? | `skipped_existing_value` |

### 21.2 Registry ?????

- `allowed_fields`?prompt ?????????????
- `direct_write_fields` / `overlay_write_fields`?????
- `readonly_fields`?`id`, `created_at`, `updated_at`

### 21.3 Data Center overlay ??

`getFieldValue` ?????direct formal ? `attributes.formal_field_overlay` ? `normalized_payload_json.formal_field_overlay` ? mirror ??

????? FieldCompletionModal ?? run items??? refresh ? MissingFieldsBadge ???? overlay ? `name_cn` ?????

---

## 22. Step 10.5.3 ? Circuit Bundle Field Completion (2026-06-22)

### 22.1 Circuit Bundle

??????????????**circuit + circuit_step + circuit_function** ?? **Circuit Bundle** ???? UI??? **multi-target group orchestration** ??????? target API?

### 22.2 related-targets API

`GET /field-completion/related-targets?target_type=circuit&target_ids=...&include=circuit_step,circuit_function`

- ????? Mirror / ???
- `circuit_function` mirror ?????? warning + ? ids

### 22.3 Serial execution strategy

Bundle Dry Run / Execute?? circuit ? circuit_step ? circuit_function **??** `POST /run`?`dry_run=true/false`???? provider ???

### 22.4 Partial failure

?? API ?? ? ?? `failed`??????????? updated/skipped/failed?

---

## 23. Step 10.5.4 ? Overlay Display Consistency (2026-06-22)

### 23.1 getFieldValue lookup order

1. `item[formalField]`
2. `attributes.formal_field_overlay[formalField]`?? normalized_payload ??????
3. `__fieldCompletionOverlay[formalField]`?????????
4. mirrorFieldCandidates??? circuit_name?name_cn?function_term?function_term_cn ???????
5. derived fields

### 23.2 MissingFieldsBadge overlay-aware

`computeMissingFields` ?? `getFieldValue` ???overlay ?? `name_cn` / `step_name_cn` / `function_term_cn` ??????

### 23.3 Bundle result applied_overlay

`MultiTargetFieldCompletionModal` ????? run items??? applied ????? `onCompleted(overlayPatch)` ??? Data Center ????

---

## 24. Step 10.5.5 ? JSON Safety and related-targets Troubleshooting (2026-06-22)

### 24.1 JSON safety (`to_jsonable`)

?? JSONB ? FastAPI response ????? `backend/app/utils/json_safety.to_jsonable`?

- `Decimal` ? `float`?score/confidence?
- `datetime` / `date` ? ISO8601 string
- `UUID` ? `str`?`Enum` ? `.value`
- dict/list ??????? ? `str(value)`

### 24.2 Decimal handling

Mirror ORM `Numeric` ???`confidence`?`strength_score` ??? `object_to_json` ? overlay meta ??? jsonable??? prompt ??? commit ??? `Object of type Decimal is not JSON serializable`?

### 24.3 related-targets route troubleshooting

- ?????`GET /api/llm-extraction/field-completion/related-targets`
- Query?`target_type`?`target_ids`???????`include`?? `circuit_step,circuit_function`?
- 404??? `main.py` include prefix?router ???????? `/{param}` ?????????
- `circuit_function` ??????? ids + warning?? 500

### 24.4 JSONB sanitizer ???

`old_value_json` / `suggested_value_json` / `applied_value_json` / `summary_json` / `attributes.formal_field_overlay_meta` ????? `to_jsonable`?

---

## 25. Step 10.5.6 ? Field-specific Prompts and Prompt Workbench (2026-06-22)

### 25.1 Field-specific prompt templates

? `target_type + field_name` ?? prompt?? `circuit_field_completion_name_cn_v1`??fallback ? `universal_field_completion_v1`?

### 25.2 Circuit bundle logic

`circuit_bundle_consistency_v1` ???????????? prompt ?? `bundle_context`?circuit / steps / functions / regions / overlay??

### 25.3 Prompt Workbench

Modal ??????? prompt plan??? `prompt_overrides`?Dry Run ?? `template_plan` / `estimated_model_calls`?

### 25.4 prompt_overrides

???? run ????? DB??? `resolve_prompt_template` ?? override?

### 25.5 consistency_checks ? quality validation

Provider ???? `field_updates` + `evidence_text` + `consistency_checks`?`name_cn` ???????????? mirror ??????

### 25.6 completion item ??

`reasoning_summary` ? `prompt_key` ? consistency ???`summary_json` ? `model_call_count` / `rejected_count` / `warning_count`?

---

## 26. Step 10.5.8 ? Token-efficient Completion and Canonical Region Resolver (2026-06-22)

### 26.1 deterministic_fields

Registry ?? `deterministic_fields`?`canonical_start_region_id` / `canonical_end_region_id` ? `canonical_region_resolver`?`source_db` / `status` ? ?? resolver????? resolver???? LLM prompt?

### 26.2 canonical_region_resolver

`region_candidate_id` ???`mirror_circuit_regions` ? `candidate_brain_regions` ? `final_brain_regions`?candidate_id ????? promoted final ??? candidate id ?? overlay ??? warning?

### 26.3 compact prompt strategy

`build_compact_field_context` ?? field ??? JSON????? attributes / raw / provenance / run history?

### 26.4 batch prompt by target_type + field_name

???? target ?? provider ???`pack_target_batches` ? token budget??? 6000 input????? pack???? target?

### 26.5 token budget estimator

`estimate_prompt_tokens`??4 chars/token??`summary_json` / dry_run preview ? `estimated_input_tokens`?`estimated_model_calls`?`pack_count`?`deterministic_fields_count`?`llm_fields_count`?

---

## 27. Step 10.6.1 ? Circuit Function Mirror Foundation (2026-06-22)

- ?? `mirror_circuit_functions` migration + `MirrorCircuitFunction` model + schemas
- ????? `macro_clinical.circuit_function` ?????dev ????? schema ??
- `field_completion_registry` ? `circuit_function` ?? `supported=False`?field completion ??? list API ??

## 28. Step 10.6.2 ? Circuit Function Mirror List API (2026-06-22)

- `GET /api/mirror-kg/circuit-functions` + `GET /api/mirror-kg/circuit-functions/{id}` ???
- Data Center Circuit Function tab ???? Mirror ???migration ???? 503 + ???????
- `field_completion_registry` **`supported=True` ?? Step 10.6.4**?????? field completion

## 29. Step 10.6.3 ? circuit_to_functions extraction (2026-06-22)

- `POST /api/llm-extraction/circuit-to-functions` ? `mirror_region_circuits` ?? `mirror_circuit_functions` ??
- deterministic seed + compact context + `circuit_to_functions_extraction_v1` prompt
- dry_run prompt preview?upsert/dedup??? formal/final/kg
- field completion registry ?? Step 10.6.4?function prompts ???

## 30. Step 10.6.4 ? circuit_function field completion + Bundle related-targets (2026-06-22)

- `circuit_function` registry **`supported=True`**?`mirror_circuit_functions` ? mirror source
- **direct_write_fields**?function_term_en/cn?function_domain?function_role?effect_type?confidence_score?evidence_level?description?remark?source_db?status
- **overlay_write_fields**?`attributes` ??????? direct ???
- **compact prompt**?`build_compact_field_context(MirrorCircuitFunction, ...)` ? id/circuit_id/??/?/??/?? circuit+step ??????? attributes/raw/normalized
- **batch by target_type + field_name**?? circuit_function ????? prompt?prompt_preview ? target_type?field_name?prompt_key?target_count?estimated_input_tokens
- **related-targets**?`include=circuit_function` ???? `mirror_circuit_functions`?? ids + extraction warning?migration 033 ??? ? `MIRROR_CIRCUIT_FUNCTIONS_NOT_INITIALIZED`
- ?? formal `macro_clinical.circuit_function` / final_* / kg_*

## 31. Step 10.6.5 ? composite workflow circuit_to_functions (2026-06-22)

- `circuit_with_function_steps` workflow ???extract_circuits ? extract_circuit_steps ? **circuit_to_functions**
- field completion bundle ? **circuit_function ids** ??? composite workflow **`created_targets`**?step_key=circuit_to_functions?
- **circuit_to_functions extraction** ? field completion ????????? Step 10.6.3 ? API ?? service?
- dry_run ?? mirror?migration 033 ?? ? structured step failed

## 32. Step 10.6.6 ? field completion ??? promotion candidate preview (2026-06-22)

- field completion ???? `mirror_circuit_functions` ??? **promotion candidate preview**?`GET .../promotion-candidates/circuit_function/{id}/preview`?
- preview ?? `formal_payload_preview`??? `macro_clinical.circuit_function`?? readiness?**??????**?`review_status=approved` ?? ready?
- actual promote ?? disabled??? formal / final_* / kg_*

---

## 17. ??

- `backend/app/services/llm_extraction_service.py` ? `run_region_field_completion`
- `backend/app/services/llm_prompt_defaults.py` ? template registry
- `docs/DATA_CENTER_FORMAL_FIELD_ALIGNMENT.md`
- `frontend/src/pages/data-center/formalFieldMappings.ts`

## 33. Step 10.6.7 ?? Bundle Auto Circuit Function Extraction and Bilingual Prompt Engineering (2026-06-22)

### no_data ?? extraction_needed ??

- BundleGroupStatus ?? 'no_data'??????????????????? circuit ????? circuit_function ???????
- ?????? 'unavailable'??migration 033 ??????? 'skipped'???? target IDs ?????????????

### Bundle ?? circuit_to_functions extraction

- MultiTargetFieldCompletionModal ??? circuit_function ??? 
o_data ????????????
- ?????????? POST /api/llm-extraction/circuit-to-functions???????? API????
- Dry Run??dry_run=true ?? ?????? provider???? estimated_model_calls??estimated_input_tokens??prompt_preview??
- Execute??dry_run=false ?? ???? provider??? mirror_circuit_functions???????? related-targets??circuit_function ???? pending??
- utoExtractEnabled checkbox??Bundle execute ??? circuit_function ? 
o_data ?? checkbox=true??????????????????

### bilingual prompt display_name

- PROMPT_TEMPLATE_METADATA �????�???? display_name??????????????Prompt key ????
- list_field_completion_prompt_template_items ??? display_name??Prompt Workbench ??????? Preview ?????????????

### neuroscience expert prompt role

- circuit_to_functions_extraction_v1 system_prompt ?????????????????? + ?????? + ????????????
- _FIELD_COMPLETION_ROLE ???????????? + ???????????????
- 4?? circuit_function ????? prompt ???? _CF_QUALITY_CONSTRAINTS??CN/EN ?????????domain ???evidence_level �?????? function_association???????????????

### token estimate ???

- extraction panel ?????????�????? tokens????? Dry Run ??????????

---

## Step 10.6.7 Refactor: Field Completion vs. Extraction Boundary

### ?????Step 10.6.7 ????

| ?? | ?? |
|------|------|
| Data Center Bundle ?????? | ????? Mirror ??????????????? extraction API |
| LLM ???? | circuit_to_functions ???Dry Run/Execute??composite workflow?DeepSeek ?? |
| Field Completion Prompt Workbench | ??? field completion prompt?circuit/step/function ????? |
| Extraction Prompt Workbench | ??? extraction prompt?GET /api/llm-extraction/prompt-templates?|

### Bundle no_data ???????

- circuit_function ?????no_data?? ?????? + ??? LLM ??????????
- ???????????? circuit_to_functions ???
- ???? LLM ?????? mirror_circuit_functions???????????

### Field Completion prompt ? Extraction prompt ??

- GET /api/llm-extraction/field-completion/prompt-templates ??? field completion prompts?
- GET /api/llm-extraction/prompt-templates?category=extraction ??? extraction prompts?? circuit_to_functions_extraction_v1??
- circuit_to_functions_extraction_v1 ???? Data Center ???? Prompt Workbench?

## Cancelled Workflow Candidates & Field Completion (Step 10.6.13)

- 已取消 / cleanup_done 的 workflow 所产生的本轮 Mirror 候选会被物理删除（按 `attributes.composite_workflow_run_id` 精准匹配），因此不会再进入字段补全的 related-targets。
- 字段补全在收集 related targets 时只应读取仍存在的 Mirror 候选；cleanup 后这些候选已不存在，自然不会被引用。
- Trace 层（llm_extraction_items / runs / composite steps）不物理删除，仅标记 cancelled，仅用于审计，不作为字段补全数据源。

## Projection Parser Dependency for projection_function (Step 10.6.14)

- projection_function 依赖 connection/projection 抽取阶段的 parser 成功：只有 parser 成功解析出 projection 并写入 mirror_region_connections 后，projection_ids 才会传给 projection_function 步骤。
- 当 connection 步骤为 failed_parse_error（DeepSeek 返回不可解析）时，projection_function 必须 skipped_dependency_failed，不能从原始 candidate pair 直接生成 function，也不能进入字段补全。
- parse_error 的 pack 不产生 projection，因此不会有对应 projection_function 候选进入后续字段补全 related-targets。

## Parse-error run and field completion boundary (Step 10.6.19)

- **parse_error run 不进入 projection_function**：fail-fast 或连续 parse_error 导致 `failed_parse_error` 时，workflow 停止剩余 pack；projection_function 步骤为 `skipped_dependency_failed`。
- **failed pack 不进入字段补全**：仅 parser 成功并写入 mirror_region_connections 的 projection 才会成为 projection_function / field completion 的 related targets。
- 调试时应先用 `debug_single_pack` 查看 `raw_response_preview`，再修 parser/prompt；避免 114 pack 全量 parse_error 后继续字段补全链路。
