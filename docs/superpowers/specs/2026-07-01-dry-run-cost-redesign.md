# Dry Run 费用估算全面重构 — 设计规格

> **日期**: 2026-07-01
> **状态**: 已确认（10 项决策全部完成）
> **范围**: 后端 + 前端，一次性交付

---

## 决策记录

| # | 决策 | 选择 |
|---|------|------|
| 1 | 范围边界 | **A** — 一次性全部做完（后端 + 前端） |
| 2 | Token 统计方式 | **A** — 引入 `tiktoken` 真实 tokenizer（o200k_base / cl100k_base） |
| 3 | 价格配置存储 | **A** — 后端 TOML + API 端点 |
| 4 | 历史 Usage 存储 | **A** — 新建 `llm_usage_history` 聚合表 |
| 5 | Dry Run 执行路径 | **A** — `plan_only` 模式在 composite workflow 层，不在 extraction service 内分支 |
| 6 | Dry Run 返回方式 | **A** — 同步返回，无轮询 |
| 7 | 旧 dry_run 分支 | **A** — 直接删除所有 extraction service 中的 dry_run 参数和分支 |
| 8 | debug_single_pack | **A** — 保留为独立 API `POST .../preview-pack` |
| 9 | Function extraction 估算 | **A** — 按历史命中率估算，无历史则保守系数 |
| 10 | Migration | **A** — 只建新表，不回填历史数据 |

---

## 架构概览

```
┌─ 前端 ──────────────────────────────────────────────────────────┐
│  PoolExtractionModal / ExtractionRunModal                       │
│    │  plan_only=true                                               │
│    ▼  POST /composite-workflows/start  (同步返回)                  │
│    │  DryRunPlan JSON                                              │
│    ▼  DryRunDetailPanel (新费用明细面板)                            │
│    │  - stage breakdown                                            │
│    │  - call count × token × cost per stage                       │
│    │  - estimation method annotation                              │
│    │  - pricing model used                                        │
│    │  - optional: preview-pack → sample output                    │
├─ 后端 ──────────────────────────────────────────────────────────┤
│  Composite Workflow Router                                       │
│    │  plan_only=true → build_dry_run_plan() → 同步返回            │
│    │  plan_only=false → start_composite_workflow() → 后台执行     │
│    ▼                                                               │
│  DryRunPlanBuilder (新模块)                                       │
│    │  1. 调 prompt builder 构造所有 pack 的真实 messages          │
│    │  2. tiktoken 统计每个 call 的 input tokens                  │
│    │  3. 查 llm_usage_history 估算 output tokens                │
│    │  4. 查 pricing.toml 计算 cost                              │
│    │  5. 处理 retry/repair 风险费用                              │
│    ▼  DryRunPlan (Pydantic model)                                │
│                                                                   │
│  Pricing Module (新)                                              │
│    │  pricing.toml → FastAPI startup → /api/pricing/models      │
│                                                                   │
│  Usage History (新)                                               │
│    │  llm_usage_history 表                                       │
│    │  每次 composite workflow 完成时写入                          │
│    │  Dry Run 时查询聚合历史，算 per-pair 平均                    │
│                                                                   │
│  Cleanup                                                          │
│    │  删除 connection/function extraction service 中 dry_run 分支 │
│    │  删除前端硬编码 estimateCost()                               │
└──────────────────────────────────────────────────────────────────┘
```

---

## 数据结构

### DryRunPlan（API 返回结构）

```python
# backend/app/schemas/dry_run_plan.py

class OutputTokenEstimate(BaseModel):
    """输出 token 多层级估算"""
    schema_min: int              # 最小合法 JSON 按 pair 展开
    expected: int                # 历史 usage 平均 → 若无则 schema_based
    historical_sample_count: int = 0  # 用于计算 expected 的历史样本数
    max_tokens: int              # 当前 stage 的 max_tokens
    estimation_method: Literal["historical_usage", "schema_based", "fallback"]

class CostEstimate(BaseModel):
    """费用估算（多层级）"""
    currency: str = "CNY"
    base_estimated: float       # 无重试的计划费用
    retry_risk: float            # 基于历史失败率的 retry 风险
    repair_risk: float = 0.0     # repair 无额外 LLM 调用，固定 0
    upper_bound: float           # base + max_retry (最坏情况)
    estimation_confidence: Literal["historical", "schema_based", "fallback"]

class PlannedCall(BaseModel):
    """一次计划的 LLM 调用"""
    planned_call_id: str         # UUID
    stage_name: str              # extract_connections / extract_projection_functions
    pack_index: int              # 0-based
    pair_count: int              # 此包包含的 pair 数
    provider: str                # deepseek / kimi
    model: str                   # deepseek-chat / kimi-k2
    input_payload: dict          # 真实 messages (system + user)
    input_token_count: int       # tiktoken 统计
    output_token_estimate: OutputTokenEstimate
    max_output_token_count: int  # max_tokens 参数
    retry_policy: dict           # max_attempts, backoff
    cost_estimate: CostEstimate
    pricing_key: str             # deepseek.chat / kimi.k2 等价格查询键

class StagePlan(BaseModel):
    """一个 Stage 的计划汇总"""
    stage_name: str
    step_order: int
    required: bool
    depends_on: str | None
    planned_call_count: int
    total_input_tokens: int
    total_expected_output_tokens: int
    total_max_output_tokens: int
    total_base_cost: float
    total_retry_risk_cost: float
    total_upper_bound_cost: float
    calls: list[PlannedCall]

class DryRunPlan(BaseModel):
    """完整的 Dry Run 计划"""
    plan_id: str
    workflow_type: str
    provider: str
    model: str
    candidate_count: int
    pair_count: int
    total_pack_count: int          # 所有 stage 的 pack 总和
    total_planned_llm_calls: int   # 所有 stage 的 LLM 调用总和（含每个 pack）
    stages: list[StagePlan]
    pricing_model_version: str     # pricing.toml 版本
    cache_strategy: str            # "conservative_cache_miss"
    estimation_timestamp: str
```

### Pricing 结构

```toml
# backend/app/pricing/pricing.toml
version = "2026-07-01"
default_currency = "CNY"

[providers.deepseek.models.chat]
input_cache_hit = 0.14     # ¥/M tokens
input_cache_miss = 1.0     # ¥/M tokens
output = 2.0               # ¥/M tokens
unit = "per_1m_tokens"
source = "https://api-docs.deepseek.com/quick_start/pricing"
checked_at = "2026-07-01"

[providers.deepseek.models.reasoner]
input_cache_hit = 1.0
input_cache_miss = 4.0
output = 16.0
unit = "per_1m_tokens"
source = "https://api-docs.deepseek.com/quick_start/pricing"
checked_at = "2026-07-01"

[providers.deepseek.models.v4_pro]
input_cache_hit = 1.0
input_cache_miss = 1.0
output = 2.0
unit = "per_1m_tokens"
source = "https://api-docs.deepseek.com/quick_start/pricing"
checked_at = "2026-07-01"

[providers.kimi.models.k2]
input_cache_hit = 8.0
input_cache_miss = 8.0
output = 12.0
unit = "per_1m_tokens"
source = "https://platform.moonshot.cn/docs/pricing"
checked_at = "2026-07-01"
```

### Usage History 表

```sql
CREATE TABLE llm_usage_history (
    id              UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    workflow_run_id UUID NOT NULL,
    workflow_type   VARCHAR(64) NOT NULL,
    stage_name      VARCHAR(64) NOT NULL,
    provider        VARCHAR(32) NOT NULL,
    model           VARCHAR(128) NOT NULL,
    pair_count      INTEGER NOT NULL DEFAULT 0,
    pack_index      INTEGER NOT NULL DEFAULT 0,
    prompt_tokens   INTEGER NOT NULL DEFAULT 0,
    completion_tokens INTEGER NOT NULL DEFAULT 0,
    reasoning_tokens INTEGER,
    total_tokens    INTEGER NOT NULL DEFAULT 0,
    retry_count     INTEGER NOT NULL DEFAULT 0,
    actual_cost     DOUBLE PRECISION,
    pricing_version VARCHAR(32),
    created_at      TIMESTAMP WITH TIME ZONE DEFAULT now()
);

CREATE INDEX idx_usage_history_agg
    ON llm_usage_history (workflow_type, stage_name, provider, model);
```

### API 变更

```
POST /api/llm-extraction/composite-workflows/start
  Request 新增字段:
    plan_only: bool = false     # true → 同步返回 DryRunPlan
    sample_pack: bool = false   # 保留，用于 preview-pack
  
  plan_only=true 时:
    → 同步返回 DryRunPlan
    → 不创建 DB record
    → 不启动后台任务
  
  plan_only=false 时:
    → 现有行为: 202 Accepted + workflow_run_id

POST /api/llm-extraction/composite-workflows/{run_id}/preview-pack
  → 运行一个真实 sample pack 并返回结果（独立于 Dry Run）

GET  /api/pricing/models
  → 返回所有配置的 provider/model 价格
  → 包括: provider, model, input_cache_hit, input_cache_miss, output, currency, unit, source, checked_at
```

---

## 实现逻辑

### 1. DryRunPlanBuilder（核心新建模块）

**文件**: `backend/app/services/dry_run_plan_builder.py`

```
build_dry_run_plan(request) → DryRunPlan:

1. 验证 candidates ≥ 2，计算 pair_count = n*(n-1)//2

2. 加载 prompt templates（与正式运行同一套）
   - connection extraction: same_granularity_connection_completion_v1
   - function extraction: projection_to_functions_v1

3. 遍历 WORKFLOW_STEP_DEFS[workflow_type]：
   For each stage:
     a. 调用 prompt builder 构造所有 pack 的真实 messages
        - build_compact_pair_records() + pack_pair_records()
        - 每个 pack 渲染完整 system + user prompt（含所有 pair JSON）
        - 如果有 dependency stage，用历史数据估算 items_count
     b. 每个 pack → 一个 PlannedCall
        - input_token_count = tiktoken 编码完整 messages JSON
        - output 走历史→schema→fallback 链
        - max_output = stage 配置的 max_tokens
     c. 查 pricing.toml 计算 cost
     d. 按 retry_policy 计算风险费用

4. 汇总 → StagePlan → DryRunPlan

5. 同步返回（不写 DB）
```

### 2. Output Token 估算链

```
estimate_output_tokens(stage_name, pair_count, items_count, provider, model) → OutputTokenEstimate:

1. 查 llm_usage_history：
   SELECT AVG(completion_tokens / NULLIF(pair_count, 0)) as avg_per_pair,
          COUNT(*) as sample_count
   FROM llm_usage_history
   WHERE workflow_type = $1 AND stage_name = $2 AND provider = $3 AND model = $4

2. 若 sample_count > 0：
   → expected = avg_per_pair * pair_count
   → estimation_method = "historical_usage"
   → historical_sample_count = sample_count

3. 若 sample_count == 0：
   → expected = schema_min * pair_count
   → estimation_method = "schema_based"

4. schema_min 计算：
   - 从 prompt template 提取 JSON schema（response_format）
   - 构造最小合法输出（一条 projection/connection）
   - 字段级 token 统计
   - schema_min = 最小合法对象 token 数 × items_count
```

### 3. Pricing 模块

**文件**: `backend/app/pricing/loader.py`

- 启动时（FastAPI `startup` event）读 `pricing.toml`，缓存为 dict
- `lookup(provider, model) → PriceEntry | None`
- `estimate_cost(input_tokens, output_tokens, price_entry) → float`
- `GET /api/pricing/models` 端点直接 dump 缓存内容
- 未配置模型返回 `price_missing: true`
- `/api/health` 或 `/api/pricing/models` 暴露 `version` 和 `checked_at`

### 4. Usage History 写入

在 `finalize_workflow_run()` 末尾加 hook：
```
for step in workflow_run.steps:
    for pack_summary in step.response_json.execution_summary.pack_summaries:
        if pack has usage data (prompt_tokens + completion_tokens):
            INSERT INTO llm_usage_history (...)
```

- 只在正式运行（`dry_run=false`）时写入
- 每个 pack 写一行
- 写入失败不影响 workflow 状态（log warning + 继续）

### 5. 前端 DryRunDetailPanel

**文件**: `frontend/src/pages/llm-extraction/components/DryRunDetailPanel.tsx`（新建）

显示结构：
```
┌─ Dry Run 费用明细 ──────────────────────────────────────────┐
│  Workflow: 连接+功能提取    Model: deepseek-chat             │
│  Candidates: 116           Pairs: 6,670                     │
│                                                             │
│  Stage 1: 连接提取                  223 包 / 223 calls      │
│    Input:      18,450,000 tokens     (tiktoken 统计)        │
│    Expected:    3,201,600 tokens     (基于 12 次历史运行)    │
│    Max:         8,761,900 tokens     (max_tokens × packs)   │
│    Base cost:   ¥24.85                                       │
│    Retry risk:   ¥2.10              (历史失败率 8.2%)       │
│    Upper bound:  ¥44.38              (max retry × 2)         │
│                                                             │
│  Stage 2: 功能提取                  156 包 / 156 calls      │
│    (按历史每 pair 产出 0.78 条连接推算)                      │
│    Input:      12,300,000 tokens                             │
│    Expected:    2,450,000 tokens     (基于 8 次历史运行)     │
│    Max:         6,500,000 tokens                             │
│    Base cost:   ¥17.80                                       │
│    Retry risk:   ¥1.56                                       │
│    Upper bound:  ¥29.34                                       │
│                                                             │
│  ─────────────────────────────────────────────────────────  │
│  总计 Base:         ¥42.65             (基于历史)            │
│  总计 Upper bound:  ¥73.72             (含 retry 最坏情况)   │
│                                                             │
│  📊 Stage 2 连接数基于历史推算，实际可能有偏差                │
│  💰 价格: DeepSeek CN (2026-07-01)                          │
│  📦 Cache: conservative miss                                │
│                                                             │
│  [运行样本包预览]  [开始正式提取]                             │
└─────────────────────────────────────────────────────────────┘
```

### 6. 清理清单

| 文件 | 操作 | 说明 |
|------|------|------|
| `llm_connection_extraction_service.py` | 删除 `dry_run` 参数及 early return (lines ~873-882) | 不再在此层分支 |
| `llm_connection_extraction_service.py` | 移除函数签名中 `dry_run: bool = False` | 简化接口 |
| `llm_circuit_function_extraction_service.py` | 删除 `status="preview"` 分支 (line ~783) | 清理死代码 |
| `llm_function_extraction_service.py` | 检查并删除 dry_run 分支 | 统一处理 |
| `llm_circuit_extraction_service.py` | 检查并删除 dry_run 分支 | 统一处理 |
| `llm_composite_workflow_service.py` | `invoke_*` 方法移除 `dry_run` 传参 | 适配新接口 |
| `PoolExtractionModal.tsx` | 删除 `estimateCost()` (lines 155-161) | 改用后端数据 |
| `PoolExtractionModal.tsx` | 删除 `computePairCount()` / `estimatePackCount()` (lines 163-171) | 后端计算 |
| `PoolExtractionModal.tsx` | 替换 `renderResult` 中简单费用显示为 DryRunDetailPanel | UI 升级 |
| `PoolExtractionModal.tsx` | 修改 step 2 radio → 传递 `plan_only` 到 API | 入口改造 |
| `compositeExtractionRunner.ts` | 适配 plan_only 同步模式 | 跳过轮询 |
| `endpoints.ts` | 新增 types + API 函数 | 类型定义 |

---

## 验收标准

1. **planned_llm_call_count 一致**：Dry Run 显示的 call 数 = 正式运行实际调用 LLM 的次数（每个 pack 一次，每个 stage 各自统计）
2. **input_tokens 来自真实 prompt**：tiktoken 编码完整 system + user messages，不再出现每包几十 tokens 的错误
3. **connection_with_function 按阶段拆分**：Stage 1 (connection) + Stage 2 (function) 分别显示费用
4. **历史 usage 优先**：有历史数据时用 `historical_usage` 方法估算 expected output
5. **无历史数据时明确标注**：UI 显示 `schema_based` / `fallback` 标签
6. **正式运行完成后显示 actual cost**：对比 estimated vs actual
7. **不改业务逻辑**：`plan_only=false` 时 workflow 执行路径完全不变
8. **Build 通过**：`cd frontend && npm run build` 0 TypeScript errors
9. **Tests 通过**：`cd backend && .venv/Scripts/python.exe -m pytest tests/ -q`
