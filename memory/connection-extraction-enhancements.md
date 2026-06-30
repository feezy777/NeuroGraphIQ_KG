---
name: connection-extraction-enhancements
description: Backend changes for prompt engineering + candidate pool + concurrency (June 2026)
metadata:
  type: project
---

# Connection Extraction Enhancements (2026-06-25)

## Backend Changes Completed

### Prompt Engineering (Phase A)
- **A1: Conservatism adjusted** — `llm_prompt_defaults.py`: Mirror KG is candidate layer, bias toward recall over precision. Confidence 0.1-0.4 allowed as "low confidence candidate, needs human review".
- **A3: 15 classical pathway hints** — `llm_prompt_defaults.py`: DMN, SN, CEN, Papez, basal ganglia, cerebellar, visual, auditory, somatosensory, motor, language, attention, reward, fear pathways injected into prompt.
- **A2: Network context injection** — `llm_connection_extraction_service.py`: `_build_batch_context_json()` adds per-pack region overview with topology hints.

### Pool + Pairing (Phase B)
- **B1: Candidate pool** — Migration 035 (`candidate_pools` + `candidate_pool_memberships` tables). New model, schema, service, router at `/api/candidates/pools`.
- **B2: Priority pair ordering** — `order_pairs_by_priority()` in `llm_extraction_prompt_engineering.py`: same-hemisphere +20, cross-hemisphere -10. No pairs excluded.
- **B3: Concurrency** — `DEFAULT_PAIRS_PER_PACK = 30`, `DEFAULT_CONCURRENT_PACKS = 5`, `asyncio.gather` with `Semaphore(5)` in `llm_connection_extraction_service.py`.
- **B4: Name columns** — Migration 036: `source_region_name_cn/en`, `target_region_name_cn/en` on `mirror_region_connections`. Model + write path updated.

### Test Results
- 1065 passed, 9 pre-existing failures (field_completion, circuit_projection, macro_clinical)

## Key Files Modified
- `backend/app/services/llm_prompt_defaults.py`
- `backend/app/services/llm_connection_extraction_service.py`
- `backend/app/services/llm_extraction_prompt_engineering.py`
- `backend/app/services/candidate_pool_service.py`
- `backend/app/routers/candidate_pool.py`
- `backend/app/models/candidate_pool.py`
- `backend/app/schemas/candidate_pool.py`
- `backend/migrations/035_candidate_pools.sql`
- `backend/migrations/036_mirror_connection_names.sql`

**Why:** These changes aim to boost connection extraction from ~300 to 1000-1500 connections.
**How to apply:** Backend is deployed. Use `candidate_pool_id` in composite workflow requests for full all_pairs extraction.
