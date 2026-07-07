# 连接提取回路：对齐脑区提取回路配置

**日期**: 2026-07-06  
**状态**: 已确认  
**方案**: B — 独立函数 + 复用工具函数

## 目标

将 `llm_circuit_pack_service.py` 中连接模式的执行代码提取为独立函数 `_execute_connection_based_extraction()`，对齐脑区模式的配置能力，同时**不修改任何脑区模式代码**。

## 架构

```
execute_circuit_extraction_background()
├── if connection_ids:  →  _execute_connection_based_extraction(...)
│   ├── 复用 _get_circuit_system_prompt()
│   ├── 复用 _normalize_circuit_type / _normalize_step_type / _normalize_step_role
│   ├── 复用 _CONN_CIRCUIT_PROMPT（连接图专用 user prompt）
│   ├── 复用 JSON fallback 解析逻辑（strip markdown + json.loads）
│   ├── 复用 MirrorRegionCircuit / MirrorCircuitStep / MirrorCircuitFunction 写入
│   ├── 复用 is_cancelling() 取消检查
│   ├── 串行 pack 循环（graph-aware 分组）
│   └── 复用 progress commit + usage_summary + result_summary
│
└── else:  →  原有脑区代码（完全不动）
```

## 函数签名

```python
async def _execute_connection_based_extraction(
    session: AsyncSession,
    run: CircuitExtractionRun,
    request: CircuitExtractionRequest,
    provider_key: str,
    resolved_model: str,
    tier_status: str,
) -> None:
```

所有入参由调用方已有变量传入，不新增 DB 连接或查询。

## 对齐清单

### 需要对齐的部分

| 配置项 | 操作 |
|--------|------|
| System Prompt | 复用 `_get_circuit_system_prompt()` — 已做 |
| circuit_type 归一化 | 复用 `_normalize_circuit_type()` — 已做 |
| step_type/role 归一化 | 复用 `_normalize_step_type/role()` — 已做 |
| JSON 解析容错 | 补上 `logger.warning` 诊断日志（脑区模式有） |
| 取消检查 | 复用 `is_cancelling(run_id)` — 已做，但只在 pack 循环开始时检查，应每包检查 |
| 进度追踪 | 复用 `counters_lock` + `session.commit()` — 已做 |
| Pack 结果收集 | 统一 `pack_results[pi]` 的 `pack_status` 字段格式 |
| 最终状态写入 | `run.result_summary_json` 字段格式需与脑区模式一致 |
| usage_summary | 字段名需与脑区模式一致 |
| errors/warnings | 字段名需一致 |
| clear_cancel_registry | 有 `await` — 已做 |

### 刻意差异（不须对齐）

| 配置项 | 连接模式 | 脑区模式 |
|--------|---------|---------|
| 分包策略 | graph-aware 连通性分组 | multi-round region shuffle |
| User Prompt | `_CONN_CIRCUIT_PROMPT`（连接图） | `_CIRCUIT_USER_PROMPT_EXTENDED`（脑区列表） |
| Pack 输入类型 | 边列表 `edge_pack` | 脑区 ID 列表 `pack_ids` |
| 并发 | 串行 | 串行 |

## 实现计划

### Phase 1: 提取函数骨架

- 创建 `_execute_connection_based_extraction` 函数
- 从 `execute_circuit_extraction_background` 中移走连接模式逻辑
- 调用方传入 6 个参数

### Phase 2: 对齐 JSON 解析

- 确保 fallback 解析块有 `logger.warning` 日志
- 与脑区模式的 fallback 逻辑一致

### Phase 3: 对齐取消检查

- 每包执行前检查 `is_cancelling(run_id)`

### Phase 4: 对齐进度/结果

- 统一 `pack_results` 字段格式
- 统一 `result_summary_json` 字段名
- 统一 `usage_summary_json` 字段名

## 不变部分

以下文件/函数完全不动：
- `_CIRCUIT_USER_PROMPT_EXTENDED`（脑区模式 user prompt）
- `run_pack` 嵌套函数（脑区模式专用）
- 脑区模式的 shuffle/打包逻辑
- `_build_region_context_json`（脑区模式专用）
- `_build_connections_context` / `_build_functions_context`（脑区模式专用）
