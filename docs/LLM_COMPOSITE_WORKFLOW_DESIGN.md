# LLM Composite Workflow Design

## 1. 设计目标

将 `#/llm-extraction` 页面的组合抽取任务（连接+功能、回路+功能+步骤、三元组生成）从前端内存编排迁移到后端可审计 workflow run，为断点续跑、显式分批、队列任务打基础。

## 2. 数据表

- `llm_composite_workflow_runs` — 一次 composite 执行的主记录
- `llm_composite_workflow_steps` — 子步骤记录，FK 到 run，on delete cascade

Migration: `backend/migrations/031_llm_composite_workflow_runs.sql`（手动执行）

## 3. API

| Method | Path | 说明 |
|--------|------|------|
| POST | `/api/llm-extraction/composite-workflows/run` | 执行 workflow |
| GET | `/api/llm-extraction/composite-workflows/runs` | 列表（limit ≤ 200） |
| GET | `/api/llm-extraction/composite-workflows/runs/{id}` | run + steps |
| GET | `/api/llm-extraction/composite-workflows/runs/{id}/steps` | steps only |

## 4. Workflow types

- `connection_with_function`
- `circuit_with_function_steps`
- `triple_generation`

## 5. Step dependency

```
connection_with_function:
  extract_connections (required)
    └─ extract_projection_functions (optional)

circuit_with_function_steps:
  extract_circuits (required)
    ├─ extract_circuit_steps (optional)
    └─ extract_circuit_functions (optional, not implemented)

triple_generation:
  generate_triples (required, uses consolidate_mirror_triples)
```

## 6. Failure / skip semantics

- 核心 step failed → workflow `failed`；依赖 steps `skipped`
- optional step 未实现或无输入 ids → `skipped` + warning，不伪造成功
- 部分 optional 失败但核心 succeeded → `partially_succeeded`

## 7. Warnings

- 大规模 candidate / pair_count 仅 warning
- `explicit_batching_enabled=true` 时 warning（未实现自动分批）
- projection/circuit ids 缺失时 skipped + warning

## 8. No upper-limit policy

不设置 candidate max_length、不阻断 pair_count、不静默 slice LLM 输出或候选列表。

## 9. Future retry / explicit batching plan

- `POST .../runs/{id}/retry-failed` 从失败子步骤续跑
- 显式 `batch_strategy` / `batch_size` 分批策略
- 结果弹窗与数据中心展示重试 provenance 链
