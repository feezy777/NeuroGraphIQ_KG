# Pack 统计审计修复 — 连接提取成功/失败分类

**日期**: 2026-06-30  
**状态**: 已批准  
**约束**: 最小侵入，不影响其他功能，不动数据库 schema / API 签名 / router

## 背景

LLM 连接提取中 `ConnectionExecutionAudit` 的 `succeeded_pack_count`、`failed_pack_count`、`processed_pack_count` 字段定义了但从未在 pack 循环中被递增，始终为 0。`build_execution_summary()` 每次从 pack_traces 实时计算正确值并返回 dict，但 `audit` 对象本身是脏的。同时 transport_error/empty_response 不会重试，`run.error_message` 不会从 pack 级错误向上传播，pack_summaries 被截断到 20 条丢失历史。

## 成功/失败定义 (选项 B)

| 类别 | 定义 |
|------|------|
| `succeeded_pack_count` | LLM 调用成功 + JSON 解析成功 + **至少提取到 1 条连接** |
| `no_connection_pack_count` | LLM 调用成功 + JSON 解析成功 + **0 条连接**（全是 no_connection） |
| `failed_pack_count` | transport_error / empty_response / parse_error / schema_error |
| `processed_pack_count` | succeeded + no_connection + failed（所有完成 provider 调用的包） |

## 修复清单

### Fix 1: audit 字段从未递增

**文件**: `backend/app/services/llm_connection_extraction_service.py`

在 `_process_one_pack` 闭包的三个 return 点各加 1-2 行：

```
# transport_error / empty_response 路径 (行 ~1361):
audit.processed_pack_count += 1
audit.failed_pack_count += 1
return [], [], [], set(), 0

# parse_error 路径 (行 ~1358):
audit.processed_pack_count += 1
audit.failed_pack_count += 1
return [], [], [], set(), 1

# 成功路径 (行 ~1417):
audit.processed_pack_count += 1
if pack_connections:
    audit.succeeded_pack_count += 1
else:
    audit.no_connection_pack_count += 1
return pack_connections, pack_no, pack_warnings, handled, 0
```

### Fix 2: transport/empty 不重试

**文件**: 同上

`break` → `continue`，让 retry loop 自然重试：

```
# 行 1261-1262:
parsed = None
continue  # 原来是 break — transport_error 也应该允许重试

# 行 1283-1284:
parsed = None
continue  # empty_response 同理
```

`for attempt in range(max_provider_attempts)` 会在 attempt 耗尽后自然退出。
注意：`continue` 之后 `text_result.transport_ok == False`，所以 `raw_text.strip()` 会触发 empty check，或直接跳到 `parsed is None` 处理——逻辑安全。

### Fix 3: run.error_message 不传播

**文件**: 同上

在 `is_semantic_failure` 分支内，设置 item.error_message 后追加 1 行：

```
run.error_message = item.error_message
```

位置：`finalize_connection_extraction_status` 调用之后、persist 之前。

### Fix 4: pack_summaries 截断控制

**文件**: `backend/app/services/llm_connection_parse_diagnostics.py`

`build_execution_summary()` 新增参数 `compact: bool = True`：

- `compact=True`（默认，`_emit_progress` 用）：走现有 `compact_pack_summaries`，保持实时 payload 轻薄
- `compact=False`（最终持久化用）：全部 pack 保留但 **剥离 `prompt_preview`** 字段以控制体积（prompt_preview 含几千字符的 UTF-8）

`compact_pack_summaries()` 新增分支：当输入 traces 数量 ≤ max_recent 时直接返回（不做截断）。最终调用点传 `compact=False`。

### Fix 5: 新增 no_connection_pack_count

**文件**:
- `backend/app/services/llm_extraction_prompt_engineering.py` — `ConnectionExecutionAudit`
- `backend/app/services/llm_connection_parse_diagnostics.py` — `build_execution_summary`
- `frontend/src/pages/llm-extraction/components/PoolExtractionModal.tsx` — 前端展示

**改动**:
1. `ConnectionExecutionAudit` 新增 `no_connection_pack_count: int = 0`
2. `to_dict()` 序列化该字段
3. `build_execution_summary` 计算：`succeeded_pack_count = processed - failed - no_connection`，或从 audit 字段直读
4. 前端 `ProgressData` 类型新增 `noConnectionPackCount`，在提取统计区域展示一行"无连接包"

## 不变性保障

- API 响应格式不变（`execution_summary` 仍是 dict 嵌套，只新增 key）
- 数据库 schema 不变
- Router 层零改动
- `_process_one_pack` 返回值签名不变
- 向后兼容：旧运行记录的 `execution_summary` 无新字段，前端需做缺省处理

## 验证

1. 后端单测：mock provider 返回 transport_error → 验证 `audit.failed_pack_count` 递增 + `run.error_message` 有值
2. 后端单测：mock provider 返回 no_connection JSON → 验证 `audit.no_connection_pack_count` 递增
3. 后端单测：mock provider 返回 1 条连接 → 验证 `audit.succeeded_pack_count` 递增
4. 前端：`npm run build` 零错误
5. 全量回归：`pytest tests/ -q`，不新增失败
