# Mirror KG 写入时合并原则（Dedup & Merge on Write）

> **文档类型**：数据治理原则 / 工程规范  
> **版本**：2026-06-24  
> **状态**：已批准，待逐步实现  
> **关联文档**：`NEUROGRAPHIQ_VIBE_CODING_GUIDE.md`、`FINAL_KG_TRIPLE_GRAPH_DESIGN.md`

---

## 1. 动机

### 1.1 当前问题

LLM 提取具有天然的不确定性：

- 同一次提取中，分属不同 pack 的相同 pair 可能被 LLM 重复判断
- 不同时间重跑提取（参数调整、模型升级、prompt 优化），相同 pair 会再次写入
- 人工审核时看到大量重复行，无法区分「新增」vs「更新」
- 晋升到 Final 时不知道该选哪条

### 1.2 解决思路

在写入 Mirror KG 时执行**确定性合并**——不是简单跳过，而是智能合并：

```
新提取结果 → 计算 canonical key
  → DB 中已有相同 key 的行？
    → 是：比较置信度，高者胜出，保留双溯源
    → 否：直接 INSERT
```

---

## 2. Canonical Key 定义

每个实体类型有一个确定的 canonical key，用于判断「两个提取结果是否指向同一事实」。

| 实体类型 | Mirror 表 | Canonical Key | 说明 |
|----------|-----------|---------------|------|
| **连接** | `mirror_region_connections` | `(source_region_candidate_id, target_region_candidate_id, connection_type, directionality)` | 无向连接时 source/target 排序后计算 |
| **脑区功能** | `mirror_region_functions` | `(region_candidate_id, function_term)` | 同一脑区不能有两条完全相同的功能术语 |
| **连接功能** | `mirror_projection_functions` | `(projection_id, function_term_en)` | 同一连接不能有两条相同的英文功能 |
| **回路** | `mirror_region_circuits` | `(circuit_name, source_atlas, granularity_level)` | 同图谱同粒度内，回路名唯一 |
| **回路功能** | `mirror_circuit_functions` | `(circuit_id, function_term_en, function_domain, function_role)` | 同回路内功能去重 |
| **三元组** | `mirror_kg_triples` | `(subject_id, predicate, object_id)` | 确定性不去重 |
| **回路步骤** | `mirror_circuit_steps` | `(circuit_id, step_order)` | 同回路内步骤序号的唯一性 |

### 2.1 无向连接的特殊处理

连接如为无向（`undirected` / `bidirectional`），canonical key 计算时必须对 source 和 target 排序：

```python
if directionality in ("undirected", "bidirectional"):
    a, b = sorted((str(source_id), str(target_id)))
else:
    a, b = str(source_id), str(target_id)

canonical_key = (a, b, connection_type, directionality)
```

确保 `A→B` 和 `B→A` 的无向连接被视为同一条。

---

## 3. 合并规则

### 3.1 核心逻辑

```
新行 confidence > 旧行 confidence
  → 用新行字段更新旧行
  → 旧行 mirror_status = superseeded_by_merge（或类似标记）
  → 旧行 provenance_json 保留完整历史
  → 返回旧行 ID（调用方感知为「已存在」）

新行 confidence <= 旧行 confidence
  → 跳过新行
  → 旧行 provenance_json 追加新行的 llm_run_id
  → 返回旧行 ID（调用方感知为「已存在」）

旧行处于 human_review_pending / human_approved 等已进审状态
  → 不自动合并
  → 新行作为独立行写入，标记为 superseded_by_newer 或类似
  → 在审核界面提示「存在更新的候选版本」
```

### 3.2 字段合并策略

| 字段 | confidence 更高时 | confidence 更低时 |
|------|------------------|------------------|
| `connection_type` | ✅ 更新 | 保留旧值 |
| `directionality` | ✅ 更新 | 保留旧值 |
| `strength` | ✅ 更新 | 保留旧值 |
| `modality` | ✅ 更新 | 保留旧值 |
| `confidence` | ✅ 取新值 | 保留旧值（更高） |
| `evidence_text` | ✅ 更新 | 保留旧值 |
| `uncertainty_reason` | ✅ 更新 | 保留旧值 |
| `mirror_status` | 设为 `llm_suggested`（与新建一致） | 不变 |
| `review_status` | ⚠️ 仅当旧行是 `pending` 时才更新 | 不变 |
| `promotion_status` | ❌ 永不修改 | ❌ 永不修改 |
| `llm_run_id` | 添加新 run_id 到 `provenance_json.llm_run_ids[]` | 同左 |
| `llm_item_id` | 添加新 item_id 到 `provenance_json.llm_item_ids[]` | 同左 |

### 3.3 保护规则（不触发合并）

以下情况**永不触发自动合并**，新行以独立候选身份写入：

1. 旧行的 `review_status` 不是 `pending`（已进入人工审核流程）
2. 旧行的 `promotion_status` 是 `promoted`（已晋升到 Final）
3. 旧行的 `mirror_status` 是 `human_rejected` 或 `superseded`
4. 新旧两行的 `source_atlas` 不同（跨图谱，即使 key 相同也不合并）
5. 新旧两行的 `granularity_level` 不同（跨粒度，即使 key 相同也不合并）

---

## 4. Provenance 保留

### 4.1 每次合并保留的 provenance 信息

```json
{
  "llm_run_ids": ["uuid1", "uuid2"],
  "llm_item_ids": ["uuid1", "uuid2"],
  "merged_at": "2026-06-24T15:30:00+08:00",
  "merge_history": [
    {"run_id": "uuid1", "item_id": "...", "confidence": 0.7, "source": "first_extraction"},
    {"run_id": "uuid2", "item_id": "...", "confidence": 0.85, "source": "second_extraction", "action": "updated"}
  ],
  "superseded_count": 0
}
```

### 4.2 被覆盖的旧字段保留

```json
{
  "previous_versions": [
    {"field": "evidence_text", "old_value": "...", "new_value": "...", "merged_at": "..."},
    {"field": "confidence", "old_value": 0.6, "new_value": 0.85, "merged_at": "..."}
  ]
}
```

---

## 5. 实现计划

### Phase 1：连接合并（mirror_region_connections）

| 文件 | 改动 |
|------|------|
| `mirror_kg_service.create_mirror_connection` | 在创建前增加 canonical key 检查 + 合并逻辑 |
| `llm_connection_extraction_service.persist_connection_mirror_records` | 将 `_connection_exists` 的跳过改为调 merge 逻辑 |
| `mirror_kg_service` | 新增 `_merge_or_create_connection` 内部方法 |

### Phase 2：功能合并（mirror_region_functions / mirror_projection_functions）

| 文件 | 改动 |
|------|------|
| `mirror_kg_service.create_mirror_function` | 增加 canonical key 检查 |
| `llm_projection_function_extraction_service` | 写入前调 merge 逻辑 |

### Phase 3：回路/回路功能合并（mirror_region_circuits / mirror_circuit_functions）

| 文件 | 改动 |
|------|------|
| `mirror_kg_service.create_mirror_circuit` | 增加 canonical key 检查 |
| `llm_circuit_function_extraction_service.upsert_mirror_circuit_function` | 增强现有 `fill_missing_only` 为完整 merge |

### Phase 4：Provenance 增强

| 文件 | 改动 |
|------|------|
| Mirror KG 各 model | 在 `provenance_json` 或 `attributes` 中标准化存储合并历史 |
| Admin / Monitor | 新增 `merged_count` 统计接口 |

---

## 6. 验收标准

```text
场景 1：同次提取内
  输入：pack 1 包含 pair A→B，pack 2 也包含 pair A→B
  预期：只写入 1 条连接，取置信度更高的
	
场景 2：不同次提取
  第1次：A→B structural confidence 0.6
  第2次：A→B structural confidence 0.9
  预期：最终只有 1 条，confidence=0.9，provenance 包含两次 run_id

场景 3：低置信度后到
  第1次：A→B structural confidence 0.9
  第2次：A→B structural confidence 0.6
  预期：最终只有 1 条，confidence=0.9（保留第一次的）

场景 4：已审核数据不受影响
  旧行 review_status=human_approved → 新行写入为新独立行
  旧行 promotion_status=promoted → 新行写入为新独立行
```

---

## 7. 不违反的现有原则

| 现有原则 | 本原则是否违反 |
|----------|--------------|
| 禁止跨粒度合并 | ❌ 不违反 — 按 canonical key 合并时要求 `granularity_level` 一致 |
| LLM 不能直接写 final_* | ❌ 不违反 — 只在 Mirror KG 层合并 |
| 禁止同名自动合并 | ❌ 不违反 — 按 canonical key（含 ID）合并，不是按名称 |
| 所有数据必须可追溯 | ❌ 不违反 — provenance 完整保留双溯源 |
| 禁止自动审核 | ❌ 不违反 — 不修改 `review_status`（除非是 pending） |
| 禁止自动 promotion | ❌ 不违反 — 永不修改 `promotion_status` |

---

## 8. 与其他原则的关系

```
写入时合并原则
    ↓ 作用于
Mirror KG 写入层（LLM 写入 / 手动创建）
    ↓ 产生
干净、去重、可追溯的 Mirror KG
    ↓ 便于
人工审核（更少重复项）
    ↓ 便于
晋升到 Final（最佳版本）
    ↓ 便于
Triple Consolidation（确定性去重 → 干净的三元组）
```

---

*维护：新增实体类型时，同步更新 §2 Canonical Key 表和 §5 实现计划。*
