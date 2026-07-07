# NeuroGraphIQ KG V3 — API & Architecture Reference (2026-07-03)

## 1. LLM 提取标准管道

```
脑区池 → 分包(每包N脑区) → LLM调用 → JSON解析 → 校验 → Mirror KG写入 → 前端轮询进度
```

核心原则：
- 所有提取以"包"为最小执行单位，每包独立调用LLM、独立解析、独立统计
- 单包失败不中断全局任务
- 无发现包(no_findings)不算失败，单独统计
- 成功解析结果进入 Mirror KG，不写 Final KG
- Mirror KG 写入复用 canonical key 去重/merge/update
- 前端弹窗只负责配置和展示，后端 runner 独立完成

---

## 2. 后端 API 接口

### 2.1 脑区候选池 (Candidate Pool)

```
POST   /api/candidates/pools           → create_pool
POST   /api/candidates/pools/replace    → replace_pool_for_scope (幂等)
GET    /api/candidates/pools            → list_pools
GET    /api/candidates/pools/{id}       → get_pool
DELETE /api/candidates/pools/{id}       → delete_pool
POST   /api/candidates/pools/{id}/members → add_members
DELETE /api/candidates/pools/{id}/members → remove_members
```

### 2.2 连接候选池 (Connection Pool) — 新建

```
POST   /api/connection-pools            → create_pool
POST   /api/connection-pools/replace     → replace_pool_for_scope
GET    /api/connection-pools             → list_pools
GET    /api/connection-pools/{id}        → get_pool
DELETE /api/connection-pools/{id}        → delete_pool
POST   /api/connection-pools/{id}/members → add_members
DELETE /api/connection-pools/{id}/members → remove_members
```

### 2.3 回路提取 (Circuit Pack Extraction) — 新建

```
POST   /api/llm-extraction/circuit-extraction/run          → 创建+启动提取
GET    /api/llm-extraction/circuit-extraction/runs           → 列表查询
GET    /api/llm-extraction/circuit-extraction/runs/{id}     → 获取详情(轮询)
POST   /api/llm-extraction/circuit-extraction/runs/{id}/cancel → 取消
POST   /api/llm-extraction/circuit-extraction/runs/{id}/retry-failed-packs → 重试失败包
```

**请求 `POST /run`**:
```json
{
  "provider": "deepseek",
  "model_name": "deepseek-chat",
  "candidate_ids": ["uuid1", "uuid2", ...],
  "pool_id": "uuid",
  "candidates_per_pack": 25,
  "shuffle_rounds": 3,
  "temperature": 0.5,
  "max_tokens": 16384,
  "pack_concurrency": 1,
  "skip_existing": false,
  "dry_run": false
}
```

**响应 `CircuitExtractionStartResponse`**:
```json
{
  "run_id": "uuid",
  "status": "pending",
  "provider": "deepseek",
  "model_name": "deepseek-chat",
  "candidate_count": 96,
  "dry_run": false,
  "estimated_packs": 12,
  "estimated_llm_calls": 12,
  "estimated_input_tokens": 24000,
  "estimated_output_tokens": 9600,
  "estimated_cost_cny": 0.0432
}
```

**轮询 `GET /runs/{id}` → `CircuitExtractionRunRead`**:
```json
{
  "id": "uuid",
  "provider": "deepseek",
  "model_name": "deepseek-chat",
  "candidate_count": 96,
  "pack_count": 12,
  "circuit_count": 45,
  "step_count": 132,
  "function_count": 89,
  "succeeded_packs": 10,
  "no_findings_packs": 1,
  "failed_packs": 1,
  "status": "partially_succeeded",
  "result_summary_json": {
    "circuit_created": 45,
    "step_created": 132,
    "function_created": 89,
    "pack_count": 12,
    "succeeded_packs": 10,
    "no_findings_packs": 1,
    "failed_packs": 1,
    "processed_packs": 12,
    "total_packs": 12
  },
  "usage_summary_json": {
    "prompt_tokens": 24000,
    "completion_tokens": 9600,
    "total_tokens": 33600,
    "estimated_cost_cny": 0.0432
  },
  "pack_results_json": [
    {
      "pack_index": 0,
      "status": "succeeded",
      "parsed_circuit_count": 5,
      "parsed_step_count": 14,
      "parsed_function_count": 9,
      "mirror_created_count": 28,
      "mirror_merged_count": 2,
      "mirror_skipped_count": 0,
      "prompt_tokens": 2000,
      "completion_tokens": 800,
      "failed_reason": null,
      "warnings": []
    }
  ],
  "errors_json": ["pack 3: timeout"],
  "warnings_json": ["pack 5: LLM returned 0 circuits"]
}
```

### 2.4 字段补全 (Field Completion)

```
POST   /api/llm-extraction/field-completion/run           → 运行字段补全
GET    /api/llm-extraction/field-completion/runs           → 列表
GET    /api/llm-extraction/field-completion/runs/{id}      → 详情
POST   /api/llm-extraction/field-completion/runs/{id}/cancel → 取消
```

### 2.5 复合工作流 (Composite Workflow)

```
POST   /api/llm-extraction/composite-workflows/start       → 启动复合提取
GET    /api/llm-extraction/composite-workflows/runs         → 列表
GET    /api/llm-extraction/composite-workflows/runs/{id}   → 详情(轮询)
POST   /api/llm-extraction/composite-workflows/{id}/cancel  → 取消
POST   /api/llm-extraction/composite-workflows/{id}/pause   → 暂停
```

---

## 3. 数据模型

### 3.1 回路提取运行 (circuit_extraction_runs)

```
id, provider, model_name, candidate_count, pack_count
circuit_count, step_count, function_count
succeeded_packs, no_findings_packs, failed_packs
status (pending/running/succeeded/partially_succeeded/failed/cancelled)
request_json, result_summary_json, usage_summary_json, pack_results_json
errors_json, warnings_json
created_at, started_at, completed_at, updated_at
```

### 3.2 Mirror KG 目标表

回路提取写入三个表：

**mirror_region_circuits**: circuit_name, circuit_type, function_association, description, confidence, mirror_status, review_status

**mirror_circuit_steps** (FK→circuit): step_order, step_name, step_type, role, description, confidence, region_candidate_id

**mirror_circuit_functions** (FK→circuit): function_term_en, function_term_cn, function_domain, function_role, effect_type, description, confidence

### 3.3 模型层级 (mirror_status 映射)

```
_MODEL_TIER = {
    "deepseek-reasoner": ("llm_reasoner", 40),
    "deepseek-v4-pro":  ("llm_v4_pro", 30),
    "deepseek-chat":    ("llm_suggested", 20),
    "kimi":             ("llm_kimi", 10),
}
```

镜像状态更新规则：`_should_update_mirror_status` 使用 `>=` 比较优先级，允许同优先级覆盖。

---

## 4. Pack 策略

### 4.1 分包逻辑

当前回路提取使用 `region_pack_intra`：脑区 shuffle → 按 N 个/包分组 → 多轮重复。

```
96 脑区, candidates_per_pack=25, shuffle_rounds=3
→ Round 1: 4 packs (25+25+25+21)
→ Round 2: 4 packs (不同排列)
→ Round 3: 4 packs (不同排列)
→ Total: 12 packs
```

### 4.2 Pack 状态

| 状态 | 条件 |
|------|------|
| succeeded | LLM返回正常 + JSON解析成功 + ≥1条有效数据 |
| no_findings | LLM返回正常 + JSON解析成功 + 0条数据 |
| failed | LLM调用失败/超时/JSON解析失败 |
| skipped | 取消或依赖失败 |

---

## 5. Mirror KG 写入规则

1. 不写 Final KG，不自动审核，不自动晋升
2. circuit_name 作为去重键：同名回路→merge(更高置信度更新) 或 skip
3. 保留 provenance: workflow_run_id, pack_id, provider, model_name, confidence
4. 统计: mirror_created_count, mirror_merged_count, mirror_skipped_count

---

## 6. 前端架构

### 6.1 LLM 提取页 (LlmExtractionPage)

- 🧠脑区 / 🔗连接 切换 → 候选表
- 脑区池指示器 + 连接池指示器
- 三个快速卡片: 🏷️脑区功能 / 🔗连接提取 / ⭕回路提取
- 回路卡片 → 复用 PoolExtractionModal 弹窗(4步配置→执行)

### 6.2 PoolExtractionModal 回路模式

- 使用池的全部成员作为候选 (localMembers.map(m=>m.candidate_id))
- 后端自动多轮 shuffle 分包
- 轮询 GET /runs/{id} 获取进度:
  - 包进度: succeeded/no_findings/failed
  - 回路统计: circuit_count / step_count / function_count
  - token 用量 + 费用预估
- 取消调用 POST /runs/{id}/cancel
- 重试失败包: POST /runs/{id}/retry-failed-packs

### 6.3 后台任务中心 (BackgroundTaskCenter)

- useBackgroundTasks hook 轮询 3 种任务:
  - listFieldCompletionRuns
  - listCompositeWorkflowRuns
  - GET /circuit-extraction/runs (新增)
- BgTask.type: 'field_completion' | 'composite_workflow' | 'circuit_extraction'
- 顶部铃铛下拉 + 任务中心全页面

### 6.4 状态显示标签

| mirror_status | StatusBadge显示 | 颜色 |
|---------------|----------------|------|
| llm_suggested | DeepSeek V3 | blue |
| llm_v4_pro | DeepSeek V4P | indigo |
| llm_reasoner | DeepSeek R1 | purple |
| llm_kimi | Kimi | teal |

---

## 7. 关键技术决策

1. **串行执行**: pack_concurrency=1，每个 pack 串行执行以避免 SQLAlchemy session 并发问题
2. **独立 session 写入**: 每 pack 的 Mirror KG 写入使用独立的 AsyncSessionLocal
3. **取消检查点**: 每 pack 间检查 `_check_cancelled`
4. **多轮 shuffle**: 每轮重新随机排列脑区，同一脑区出现在多个不同包中
5. **去重逻辑**: 同 circuit_name → 比较置信度 → merge(更高) 或 skip(更低)

---

## 8. 现有局限性

1. 回路提取 prompt 模板固定，未暴露用户自定义
2. pack_concurrency 目前=1（串行），高并发需独立 session 改造
3. 无预算守门（前端可预估但不会阻止）
4. task center metric 数量展示
5. 连接池的提取执行尚未完全接入
