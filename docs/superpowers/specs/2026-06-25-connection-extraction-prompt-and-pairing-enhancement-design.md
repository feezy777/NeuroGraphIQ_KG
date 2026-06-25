# Connection Extraction Prompt & Pairing Enhancement Design

**Date:** 2026-06-25
**Status:** Approved — A+B combined, C deferred
**Target:** 300+ → 1000-1500 connections (short term), 2000+ (Phase C)

---

## Problem Statement

Current connection extraction produces ~300 connections total. Root causes:

1. **Batch isolation** — candidates selected in separate batches never pair across batches. 3 batches × 20 regions = 570 pairs internally, but 1770 pairs if pooled together.
2. **Overly conservative prompts** — system prompt biases toward "no_connection", treating Mirror KG (candidate layer) as if it were Final KG.
3. **No network context** — each pair evaluated in isolation without visibility into the broader region topology.
4. **No literature priors** — classical neuroanatomical pathways are not hinted to the model.
5. **Missing name denormalization** — `mirror_region_connections` stores only candidate IDs, requiring JOINs for every read.

---

## Solution Overview

### Phase A: Prompt Engineering (low risk, immediate)

| ID | Change | File |
|----|--------|------|
| A1 | Adjust conservatism — Mirror KG is candidate layer, err on recall side | `llm_prompt_defaults.py` |
| A2 | Inject network context into each pack | `llm_prompt_defaults.py` + `llm_connection_extraction_service.py` |
| A3 | Add classical pathway hints to system prompt | `llm_prompt_defaults.py` |

### Phase B: Full Pairing + Smart Filtering (medium risk, immediate)

| ID | Change | File(s) |
|----|--------|---------|
| B1 | Cross-batch candidate pool (new API + table) | New model + service + router |
| B2 | Full all_pairs with priority-based pack ordering | `llm_connection_extraction_service.py` |
| B3 | Concurrency control + pairs_per_pack 20→30 | `llm_connection_extraction_service.py` |
| B4 | Add name columns to `mirror_region_connections` | Migration + model + service |

---

## Detailed Design

### A1: Adjust Conservatism

The Mirror KG is a **candidate staging layer** — all entries require human review before promotion. The prompt should reflect this: bias toward recall, mark low-confidence items explicitly rather than suppressing them.

**Current system prompt (excerpt):**
```
完全无证据时应返回 no_connection
证据不足但存在一般神经解剖学常识支持时，confidence_score 必须偏低
```

**New system prompt (replacement):**
```
置信度分层指南（Mirror KG 候选层，所有候选都需要人工审核）：
- 0.7-1.0 (high): 多文献支持或经典教科书明确描述
- 0.4-0.7 (moderate): 单文献支持或知名数据库收录
- 0.1-0.4 (low): 基于解剖邻近性、已知网络拓扑推断，或一般神经科学常识支持
- 不要因为 confidence 低就不报——低置信度候选恰恰是人工审核最有价值的对象

仅当以下情况才返回 no_connection：
- 两个脑区在解剖学上不可能存在直接连接（如物理隔离、跨物种、不同发育阶段）
- 已有明确文献证据排除该连接

重要：Mirror KG 是候选层，不等同于 final fact。宁可多报低置信度候选供人工审核，
也不要遗漏可能的连接。所有 mirror 对象都标注 mirror_status='llm_suggested'。
```

### A2: Inject Network Context

Each pack currently contains only the 20-30 pairs to evaluate. Add a `batch_context` section:

```json
{
  "batch_context": {
    "total_regions_in_pool": 96,
    "total_pairs_in_pool": 4560,
    "current_pack_index": 5,
    "total_packs": 152,
    "regions_in_current_pack": [
      {"id": "uuid", "name_cn": "...", "name_en": "...", "laterality": "left", "lobe": "frontal"}
    ],
    "region_summary": "本批次涉及 12 个脑区：额叶(4)、颞叶(3)、顶叶(2)、边缘系统(3)"
  },
  "pairs": [...]
}
```

The `build_compact_pair_records` function in `llm_extraction_prompt_engineering.py` will be extended to accept optional `pool_context` and append it.

### A3: Classical Pathway Hints

Add to the system prompt or as a separate `pathway_hints` block in the user prompt:

```
经典神经通路参考（本批次可能涉及）：
1. 默认模式网络 (DMN): 内侧前额叶(mPFC) ↔ 后扣带(PCC) ↔ 角回 ↔ 海马
2. 突显网络 (SN): 前岛叶 ↔ 背侧前扣带(dACC) ↔ 杏仁核
3. 中央执行网络 (CEN): 背外侧前额叶(dlPFC) ↔ 后顶叶(PPC)
4. 边缘系统: 海马 ↔ 杏仁核 ↔ 下丘脑 ↔ 前扣带
5. Papez 回路: 海马 → 穹窿 → 乳头体 → 丘脑前核 → 扣带回 → 海马旁回 → 海马
6. 基底节环路: 皮质 → 纹状体 → 苍白球 → 丘脑 → 皮质 (直接/间接/超直接通路)
7. 小脑环路: 皮质 → 脑桥 → 小脑 → 丘脑 → 皮质
8. 视觉通路: 视网膜 → LGN → V1 → 背侧通路(MT/MST) / 腹侧通路(IT)
9. 听觉通路: 耳蜗核 → 上橄榄核 → 下丘 → MGN → A1
10. 体感通路: 脊髓 → 丘脑(VPL/VPM) → S1 → S2 → 后顶叶
11. 运动通路: M1 → 内囊 → 脑干 → 脊髓 (皮质脊髓束)
12. 语言网络: Broca区 ↔ Wernicke区 ↔ 弓状束

如果输入 pair 涉及上述通路中的脑区对，请标注相应通路名称和较高 confidence。
```

### B1: Cross-Batch Candidate Pool

**New model: `CandidatePool`**

```python
# backend/app/models/candidate_pool.py
class CandidatePool(Base):
    __tablename__ = "candidate_pools"
    
    id: Mapped[uuid.UUID] = primary_key, default=uuid4
    name: Mapped[str] = String(256), nullable=True  # user-defined label
    resource_id: Mapped[uuid.UUID | None]
    batch_id: Mapped[uuid.UUID | None]
    source_atlas: Mapped[str]
    granularity_level: Mapped[str]
    granularity_family: Mapped[str | None]
    candidate_count: Mapped[int] = default 0
    pair_count: Mapped[int] = default 0
    status: Mapped[str] = default "active"  # active | locked | archived
    created_at, updated_at
```

**New model: `CandidatePoolMembership`**

```python
class CandidatePoolMembership(Base):
    __tablename__ = "candidate_pool_memberships"
    
    id: Mapped[uuid.UUID]
    pool_id: Mapped[uuid.UUID] -> FK candidate_pools.id
    candidate_id: Mapped[uuid.UUID] -> FK candidate_brain_regions.id
    added_at: Mapped[datetime]
    added_by: Mapped[str | None]
```

**API Endpoints:**

| Method | Path | Description |
|--------|------|-------------|
| POST | `/api/candidates/pools` | Create pool from candidate_ids |
| GET | `/api/candidates/pools` | List pools (filter by atlas/granularity) |
| GET | `/api/candidates/pools/{id}` | Get pool + member list |
| POST | `/api/candidates/pools/{id}/members` | Add candidates to pool |
| DELETE | `/api/candidates/pools/{id}/members` | Remove candidates from pool |
| DELETE | `/api/candidates/pools/{id}` | Delete pool |

**Composite workflow integration:**

```python
# New optional field in CompositeWorkflowRunRequest
candidate_pool_id: uuid.UUID | None = None

# When provided, resolve candidate_ids from pool instead of request field
if request.candidate_pool_id:
    candidate_ids = await resolve_pool_members(session, request.candidate_pool_id)
else:
    candidate_ids = request.candidate_ids
```

### B2: Smart Pack Ordering

After generating all pairs via `all_pairs`, apply priority scoring before packing:

```python
def score_pair_priority(
    pair: tuple[uuid.UUID, uuid.UUID],
    candidates: dict[uuid.UUID, CandidateBrainRegion],
    pathway_hints: dict[str, set[frozenset[str]]],
) -> int:
    """Score a pair 0-100 for pack ordering. Higher = earlier pack."""
    src = candidates[pair[0]]
    tgt = candidates[pair[1]]
    score = 0
    
    # Same laterality: +20
    if src.laterality and tgt.laterality and src.laterality == tgt.laterality:
        score += 20
    
    # Same lobe/region group (heuristically derived from name/acronym): +30
    if _same_lobe(src, tgt):
        score += 30
    
    # Matches known pathway: +50
    src_name = (src.en_name or src.cn_name or "").lower()
    tgt_name = (tgt.en_name or tgt.cn_name or "").lower()
    for pathway, region_set in pathway_hints.items():
        if frozenset([src_name, tgt_name]) in region_set:
            score += 50
            break
    
    # Cross-hemisphere (L-R or R-L): -10 (still evaluate, just later)
    if src.laterality and tgt.laterality and src.laterality != tgt.laterality:
        score -= 10
    
    return score
```

Pairs are sorted by descending priority score, then packed. This ensures high-value pairs are processed first.

**No pairs are ever excluded** — priority scoring only affects pack order.

### B3: Concurrency + Pack Size

**Pairs per pack:** 20 → 30

Rationale: Each pair in the compact format is ~80 tokens. 30 pairs × 80 = 2400 tokens input. Modern LLMs (deepseek-v4-pro) handle 16K-64K output comfortably — the bottleneck is output JSON size, not input. 30 pairs should produce ~3000-5000 output tokens, well within limits.

**Concurrency:**

```python
# New config in llm_connection_extraction_service.py
DEFAULT_CONCURRENT_PACKS = 5  # number of parallel LLM calls

async def process_packs_concurrent(
    packs: list[list[dict[str, Any]]],
    provider,
    model_name,
    *,
    concurrency: int = DEFAULT_CONCURRENT_PACKS,
    on_progress: ConnectionProgressCallback | None = None,
) -> list[PackResult]:
    """Process packs with bounded concurrency using asyncio.Semaphore."""
    semaphore = asyncio.Semaphore(concurrency)
    
    async def process_one(pack: list[dict[str, Any]], idx: int) -> PackResult:
        async with semaphore:
            return await call_llm_for_pack(pack, provider, model_name, idx)
    
    # Process all packs, respecting semaphore
    tasks = [process_one(pack, i) for i, pack in enumerate(packs)]
    results = await asyncio.gather(*tasks, return_exceptions=True)
    return results
```

**Frontend progress display:**
- Show: `Pack 47/152 · 187 connections found · 3 packs failed (retrying)`
- Per-pack status: succeeded ✅ / parsing error ⚠️ / provider error ❌

### B4: Name Columns on mirror_region_connections

**Migration:** `backend/migrations/034_mirror_connection_names.sql`

```sql
ALTER TABLE mirror_region_connections
  ADD COLUMN source_region_name_cn VARCHAR(256),
  ADD COLUMN source_region_name_en VARCHAR(256),
  ADD COLUMN target_region_name_cn VARCHAR(256),
  ADD COLUMN target_region_name_en VARCHAR(256);

-- Backfill from candidate_brain_regions
UPDATE mirror_region_connections mc
SET 
  source_region_name_cn = src.cn_name,
  source_region_name_en = src.en_name,
  target_region_name_cn = tgt.cn_name,
  target_region_name_en = tgt.en_name
FROM candidate_brain_regions src, candidate_brain_regions tgt
WHERE mc.source_region_candidate_id = src.id
  AND mc.target_region_candidate_id = tgt.id;
```

**Model update:** Add 4 columns to `MirrorRegionConnection` in `mirror_kg.py`.

**Service update:** On write, populate name columns from candidate lookup (alongside existing ID writes).

---

## Migration & Rollback Strategy

- A1-A3: No migration needed — prompt-only changes, safe to roll back by reverting template strings
- B1: New tables `candidate_pools` + `candidate_pool_memberships` — new migration file, no impact on existing data
- B2-B3: Configuration changes — safe to tune via runtime settings
- B4: ALTER TABLE + backfill — standard migration with UPDATE; no data loss

---

## Success Metrics

| Metric | Before | After (Target) |
|--------|--------|----------------|
| Total connections extracted (96-region pool) | ~300 | 1000-1500 |
| Packs returning 0 connections | 30-40% | <10% |
| Cross-batch connection coverage | 0% (by design) | 100% (pool eliminates batch concept) |
| Per-extraction API calls (96 regions) | ~10-15 (per batch) | ~152 (1 pool, concurrent) |
| Extraction wall-clock time | ~30-60s (single batch) | ~60-120s (full pool, 5x concurrency) |

---

## Out of Scope (Deferred to Phase C)

- Pre-loaded known connection templates from NeuroSynth/BrainMap/Allen Brain Atlas
- Two-stage extraction (seed confirmation → inference)
- Transitive closure reasoning (A→B + B→C → suggest A→C)
- Graph-based extraction (treating all regions as a graph and asking LLM to fill edges)

---

## Spec Self-Review

- ✅ No TBD/TODO placeholders
- ✅ Internal consistency: A+B changes are orthogonal and non-conflicting
- ✅ Scope: Focused on prompt + pairing; Phase C explicitly deferred
- ✅ No ambiguity: Each change has specific file, field, or code pattern targets
