# Extraction Mode 重构 — 从单一全量到成本可控

> **日期**: 2026-07-01
> **状态**: 全部 6 节设计确认
> **范围**: PoolExtractionModal + 后端 planner + Dry Run + 分阶段模型路由

---

## 决策记录

| # | 决策 | 选择 |
|---|------|------|
| 1 | Screening 实现方式 | **A** — 新建独立 `connection_screening_v1` prompt 模板 |
| 2 | Planner 统一 | **A** — `plan_only=false` 时先调 `build_execution_plan()`，通过后再创建 Run |
| 3 | 分阶段模型路由 | **A** — `stage_model_config` dict 按 stage_name 覆盖，不改 extraction service 签名 |
| 4 | skip-existing 时机 | **A** — 在 Planner 中查询并过滤，Dry Run 直接显示准确跳过数 |
| 5 | Prompt 编辑 | **A** — 合并到第 2 页"高级参数"折叠区 |
| 6 | region_centered | **A** — `extraction_mode="region_centered"` 自动设 `pair_strategy="region_centered"` |

---

## 一、数据模型与 API 变更

### 1.1 CompositeWorkflowRunRequest 新增字段

```python
extraction_mode: Literal["balanced", "exhaustive", "region_centered"] = "balanced"
skip_existing_connections: bool = True
skip_existing_functions: bool = True
force_reextract: bool = False
budget_cny: float | None = None
stage_model_config: dict[str, StageModelEntry] = Field(default_factory=dict)
center_region_id: str | None = None
```

`StageModelEntry = {"provider": str, "model": str}`

### 1.2 Workflow Step 定义扩展

`WORKFLOW_STEP_DEFS` 按 `extraction_mode` 动态返回：

| Mode | Step0 | Step1 | Step2 |
|------|-------|-------|-------|
| balanced | `connection_screening` | `connection_detail` | `function_extraction` |
| exhaustive | — | `extract_connections` (现有) | `extract_projection_functions` (现有) |
| region_centered | — | `connection_detail` | `function_extraction` |

Step0 和 Step1 是**同一套连接提取引擎**，区别在于使用的 prompt 模板和 model：
- Step0 → `connection_screening_v1` + deepseek-v4-flash
- Step1 → `same_granularity_connection_completion_v1` + deepseek-v4-pro

### 1.3 llm_usage_history 新增字段

```sql
ALTER TABLE llm_usage_history ADD COLUMN extraction_mode VARCHAR(32);
```

### 1.4 新 Prompt 模板

`connection_screening_v1`：极简 system prompt，输出 schema：

```json
{
  "likely_connections": [
    {"source_id": "uuid", "target_id": "uuid", "label": "positive|uncertain", "confidence": 0.0}
  ],
  "summary": {
    "screened_pair_count": 30,
    "positive_count": 0,
    "uncertain_count": 0
  }
}
```

核心差异 vs 现有 connection extraction：

| 维度 | screening | 现有 extraction |
|------|-----------|----------------|
| 输出内容 | label + confidence | 完整 projection schema |
| JSON token/pair | ~200 | ~400-800 |
| 模型 | deepseek-v4-flash | deepseek-v4-pro |
| 需要 evidence | ❌ | ✅ |
| 需要 connection_type | ❌ | ✅ |
| 写 Mirror KG | ❌ | ✅ |

---

## 二、Planner 统一与执行流

### 核心原则：一份 Plan，两个路径

```
POST /composite-workflows/start { ..., extraction_mode, budget_cny }
  │
  ├─ plan_only=true
  │    └─ build_execution_plan() → ExecutionPlan → 同步返回 200
  │
  └─ plan_only=false
       ├─ build_execution_plan()  ← 同一份 plan
       ├─ 校验: base_cost > budget_cny? → 403 BUDGET_EXCEEDED
       ├─ prepare_composite_workflow()  → 创建 Run + Steps
       ├─ 将 plan 写入 run.result_summary_json.execution_plan
       └─ 后台执行 execute_workflow()
```

### build_execution_plan() 统一入口

```python
async def build_execution_plan(session, request, candidates) -> ExecutionPlan:
    # 1. skip-existing 查询
    existing_conns = await query_existing_canonical_keys(
        canonical_pair_keys_for(candidates), 
        force=request.force_reextract
    )
    existing_funcs = await query_existing_function_projection_ids(
        candidate_ids, 
        force=request.force_reextract
    )
    
    # 2. 根据 extraction_mode 选择 stages
    stage_defs = MODE_STAGE_DEFS[request.extraction_mode]
    
    # 3. 迭代构建
    for stage_def in stage_defs:
        pairs = compute_pairs(strategy, candidates)
        pairs = apply_skip_existing(pairs, existing_conns) if stage_def.key == "connection_detail"
        calls = build_planned_calls(pairs, stage_def, model_config)
        # 对每个 call: tiktoken input + historical output + pricing
    
    # 4. 返回
    return ExecutionPlan(...)
```

### 预算守门

`plan_only=false` 时，如果 `base_cost > budget_cny`，后端返回：
```json
{"code": "BUDGET_EXCEEDED", "base_cost": 6.75, "budget": 5.00, "message": "预计费用超过预算"}
```

---

## 三、分阶段模型路由

### stage_model_config 默认值

```python
DEFAULT_STAGE_MODELS = {
    "balanced": {
        "connection_screening": {"provider": "deepseek", "model": "deepseek-v4-flash"},
        "connection_detail":    {"provider": "deepseek", "model": "deepseek-v4-pro"},
        "function_extraction":  {"provider": "deepseek", "model": "deepseek-v4-flash"},
    },
    "exhaustive": {
        "extract_connections":          {"provider": "deepseek", "model": "deepseek-v4-pro"},
        "extract_projection_functions":  {"provider": "deepseek", "model": "deepseek-v4-flash"},
    },
    "region_centered": {
        "connection_detail":    {"provider": "deepseek", "model": "deepseek-v4-pro"},
        "function_extraction":  {"provider": "deepseek", "model": "deepseek-v4-flash"},
    },
}
```

### 执行时 model 解析

每个 step 执行前从 `stage_model_config` 取对应 `step_key` 的覆盖：

```python
stage_model = stage_model_config.get(step_key, {})
provider = stage_model.get("provider", run.provider)
model = stage_model.get("model", run.model_name)
result = await provider_adapter.complete_text(model=model, ...)
```

---

## 四、Connection Screening（balanced Step0）

### 数据流

```
Step0: connection_screening (deepseek-v4-flash)
  ↓ 输出 likely_connections (label ∈ {positive, uncertain})
  ↓ 筛选 positive + uncertain pair
  ↓
Step1: connection_detail (deepseek-v4-pro)
  ↓ 只处理 Step0 筛选出的 pair
  ↓ 输出完整 projection → 写 Mirror KG
  ↓
Step2: function_extraction (deepseek-v4-flash)
  ↓ 只处理 Step1 新建的 projection
  ↓ 或已有 connection 但缺失 function
  ↓ 输出 MirrorProjectionFunction
```

### skip-existing 在各 step 的影响

- Screening 层：已有 MirrorRegionConnection 的 pair 不进入 Step0（完全跳过）
- Detail 层：Step0 过滤后的 pair 中，再次检查 skip-existing（双重保险）
- Function 层：已有 MirrorProjectionFunction 的 projection 不进入 Step2

DryRunPlan 中显示：
- `total_pairs`
- `skipped_existing_connections`
- `planned_screening_pairs`
- `planned_detail_pairs`
- `skipped_existing_functions`
- `planned_function_items`

---

## 五、前端 PoolExtractionModal 改造

### 两页结构

**第 1 页：脑区池选择**
- 只展示脑区池列表（搜索、全选、取消选择、用外部选中替换、移除选中）
- 显示已选数量和 pair 数
- **不展示模型配置、不展示高级参数**
- 底部：`[取消] [下一步]`

**第 2 页：提取配置**
1. **提取模式卡片组**（三选一 radio）：balanced（默认）/ exhaustive / region_centered
2. **预算与跳过**：budget_cny 输入框 + skip_existing_connections/functions 复选框
3. **分阶段模型路由**：每个 stage 显示当前 model + 下拉选择器
4. **高级参数**（折叠）：temperature, max_tokens, pairs_per_pack, max_provider_attempts, force_reextract, prompt 编辑链接
5. **底部**：`[上一步] [取消] [💰 Dry Run 费用预估]`
   - **无"开始正式提取"按钮** — 必须先 Dry Run

### 关键交互规则

- 切换 extraction_mode → 如果 `userModifiedBudget == false`，自动切换默认预算
- `budget` 输入框：`onChange` 设 `userModifiedBudget = true`，之后切换模式不再覆盖
- region_centered 模式 → 显示 `center_region_id` 下拉选择器（必填，校验后才允许 Dry Run）
- 高级参数默认折叠

---

## 六、DryRunDetailPanel 增强

### 按 extraction_mode 展示不同 stage

- **balanced**：Step0 筛查 → Step1 详情 → Step2 功能
- **exhaustive**：Step1 连接提取 → Step2 功能提取
- **region_centered**：中心脑区连接提取 → 功能提取

### 必须显示字段

- workflow_type, extraction_mode
- candidate_count, total_pair_count
- skipped_existing_connections, skipped_existing_functions
- planned_llm_call_count
- per-stage: input_tokens, expected_output, max_output, base_cost, upper_bound
- budget_cny + exceeds_budget 标志
- pricing_key, estimation_method, cache_strategy

### 预算守门 UI

| 条件 | 行为 |
|------|------|
| `base_cost > budget` | 按钮禁用 + 红色提示 "超出预算 ¥X" |
| `upper_bound > budget × 2` | 黄色警告，不禁用按钮 |
| 价格未配置 | 显示 "N/A" + 禁用按钮 |

---

## 七、价格配置修正

```toml
# deepseek-v4-flash / deepseek-chat（低成本模型）
[providers.deepseek.models.deepseek-v4-flash]
input_cache_hit = 0.0028      # USD/1M
input_cache_miss = 0.14       # USD/1M  ← 不能配成 0.435
output = 0.28                 # USD/1M  ← 不能配成 0.87

# deepseek-v4-pro（高质量模型）
[providers.deepseek.models.deepseek-v4-pro]
input_cache_hit = 0.003625
input_cache_miss = 0.435      # USD/1M  ← pro 价格
output = 0.87                 # USD/1M  ← pro 价格
```

---

## 八、JSON Repair / Retry（保持现有）

- 保持现有确定性 JSON 修复
- 不新增 LLM repair 调用
- Retry 最多 2 次
- Dry Run 显示 retry risk cost（历史失败率优先，无数据时按 8% 默认）

---

## 九、Usage History 增强

正式运行完成后按 `stage_name` 分开记录：

| stage_name | 说明 |
|------------|------|
| `connection_screening` | balanced Step0 |
| `connection_detail` | balanced/region_centered Step1 |
| `function_extraction` | balanced/region_centered Step2 |
| `extract_connections` | exhaustive Step1 |
| `extract_projection_functions` | exhaustive Step2 |

每条记录含：`workflow_type`, `extraction_mode`, `stage_name`, `provider`, `model`, `pair_count`, `pack_index`, `prompt_tokens`, `completion_tokens`, `total_tokens`, `retry_count`, `actual_cost_cny`, `pricing_version`

---

## 十、文件变更清单

### 新建
| 文件 | 用途 |
|------|------|
| `backend/app/schemas/execution_plan.py` | ExecutionPlan / StagePlan / PlannedCall 等 schema（替代 dry_run_plan.py） |
| `backend/app/services/execution_plan_builder.py` | 统一 planner（替代 dry_run_plan_builder.py） |
| `backend/app/services/skip_existing_service.py` | skip-existing 查询逻辑 |

### 修改
| 文件 | 变更 |
|------|------|
| `schemas/llm_composite_workflow.py` | 新增 extraction_mode 等字段 |
| `routers/llm_composite_workflow.py` | plan_only=false 时先 build_execution_plan |
| `services/llm_composite_workflow_service.py` | 按 extraction_mode 动态选 step defs；分阶段 model 路由；Step0 screening runner |
| `services/llm_prompt_defaults.py` | 新增 connection_screening_v1 模板 |
| `services/llm_extraction_prompt_engineering.py` | 新增 screening prompt builder |
| `pricing/pricing.toml` | 修正 flash/chat 价格 |
| `migrations/039_*.sql` | llm_usage_history 加 extraction_mode 列 |
| `PoolExtractionModal.tsx` | 三步→两步；模式选择卡片；预算控件；移除"开始提取" |
| `DryRunDetailPanel.tsx` | 按 extraction_mode 显示不同 stage；预算守门 |
| `endpoints.ts` | 新增 extraction_mode 等类型 |

### 删除/废弃
| 文件 | 原因 |
|------|------|
| `schemas/dry_run_plan.py` | 被 execution_plan.py 替代 |
| `services/dry_run_plan_builder.py` | 被 execution_plan_builder.py 替代 |

---

## 十一、验收标准

1. ✅ 现有 `connection_with_function` 仍可按 exhaustive 完整运行
2. ✅ 默认打开弹窗时选择 balanced
3. ✅ 第 1 页只展示脑区池，无模型/高级参数
4. ✅ 第 2 页可切换 balanced / exhaustive / region_centered
5. ✅ Dry Run 按不同 extraction_mode 展示不同 stage 和费用
6. ✅ balanced 不对所有 pair 做完整 connection detail（先 screening）
7. ✅ exhaustive 明确标记为高成本全量审计
8. ✅ region_centered 必须选中心脑区后方可 Dry Run
9. ✅ skip_existing 默认开启
10. ✅ 已有连接/功能不会默认重复送入 LLM
11. ✅ 超过预算时前端和后端都拒绝启动
12. ✅ deepseek-v4-flash 和 deepseek-v4-pro 价格区分正确
13. ✅ Dry Run 展示明细，不只有一个总金额
14. ✅ 价格未配置时显示 N/A
15. ✅ 不改 Mirror KG 写入、人工审核、final promotion
16. ✅ 前端 build 0 TS errors / 后端 tests pass
