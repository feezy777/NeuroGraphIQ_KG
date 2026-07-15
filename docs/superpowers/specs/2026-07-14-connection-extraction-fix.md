# 连接提取修复计划

**Date**: 2026-07-14

## 问题

| # | 问题 | 根因 |
|---|------|------|
| 1 | 数据不全量入库 | `persist_connection_mirror_records` 只在所有 pack 完成后调用一次，中途中断全丢 |
| 2 | 速度慢 | 串行 pack 处理，每 pack 一次 LLM 调用 |
| 3 | 缺中英文名 | LLM 不返回 name_cn/name_en，需要从 candidate 表 fill |
| 4 | `created_projection_count` 始终为 0 | 同上，persist 在最后才更新计数器 |

## 方案

### 改动范围

只改 1 个文件：`llm_connection_extraction_service.py`

### A. 每包即时提交

在第 1464 行（`normalized_connections.extend(_pn)` 后）加入 per-pack persist：

```python
if create_mirror_records and _pn:
    pk_created, pk_skipped, _, _, pk_warnings, _ = await persist_connection_mirror_records(
        session, run=run, item=item,
        connections=_pn, candidate_map=candidate_map,
        session_seen=session_seen_set,
    )
    await session.commit()
```

- 需新增 `session_seen_set: set[tuple[str,str,str,str]] = set()` 变量（在 pack 循环前初始化）
- 去掉末尾的旧 persist 代码（第 1589 行附近）避免重复写入

### B. 字段齐全（name_cn/name_en）

已有逻辑（第 300-350 行 `_fill_connection_names`），LLM 不返回时从 `candidate_map` 补全。不需要额外改动。

### C. 速度

不在此次改动。独立 API `/same-granularity-connections` 每调用即提交，前端分小 pack 调用即可提速。复合工作流速度由 LLM 响应时间决定，无法在此加速。

### D. 数据质量

删除低质量连接（去重+缺字段）沿用已有的 `DELETE` SQL 逻辑。

## 不变

- 不改变 API 接口
- 不影响其他功能（LLM 提取、字段补全等）
- 不修改数据库结构
- 不修改前端

## 风险

| 风险 | 缓解 |
|------|------|
| per-pack persist 失败中断提取 | try/except 记录错误但继续 |
| 旧 persist 代码与新代码重复写入 | 删除旧代码 |
| session_seen 跨 pack 去重 | 新增 `session_seen_set` 跨 pack 传递 |
