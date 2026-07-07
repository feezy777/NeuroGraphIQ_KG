# Connection Pool — 连接池扩展设计

Date: 2026-07-03. Extend LLM extraction pipeline to support connection data as candidates, alongside the existing brain region pool.

## 1. 动机

当前 LLM 提取的候选来源只有脑区数据（CandidateBrainRegion），通过 CandidatePool 管理。用户需要：
- 把 Mirror KG 中已有的连接（projection）作为提取候选
- 未来支持 Raw Parsing 阶段的连接数据（如 connectome 数据集）自动流入候选池
- 脑区和连接可以在 LLM 提取页面切换，连接池可像脑区池一样组建和管理

## 2. 数据模型

新建 `connection_pools` 和 `connection_pool_memberships` 表。

```sql
CREATE TABLE connection_pools (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    name VARCHAR(255) NOT NULL,
    scope_atlas VARCHAR(128),
    scope_granularity VARCHAR(64),
    source VARCHAR(64) NOT NULL DEFAULT 'manual',  -- 'raw_parsing' | 'mirror_kg' | 'manual'
    resource_id UUID,
    batch_id UUID,
    connection_count INT DEFAULT 0,
    created_at TIMESTAMPTZ DEFAULT now(),
    updated_at TIMESTAMPTZ DEFAULT now()
);

CREATE TABLE connection_pool_memberships (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    pool_id UUID NOT NULL REFERENCES connection_pools(id) ON DELETE CASCADE,
    connection_id UUID NOT NULL REFERENCES mirror_region_connections(id) ON DELETE CASCADE,
    added_source VARCHAR(64) DEFAULT 'manual',
    added_at TIMESTAMPTZ DEFAULT now(),
    UNIQUE(pool_id, connection_id)
);
```

- 一个 scope 下一个活跃池（`replace_pool_for_scope` 原子替换，跟脑区池一致）
- `source`/`added_source` 区分来源：`raw_parsing` | `mirror_kg` | `manual`

## 3. API

新建 `backend/app/routers/connection_pool.py`，复用候选池模式：

| Method | Path | Purpose |
|--------|------|---------|
| POST | `/api/connection-pools` | 创建连接池 |
| POST | `/api/connection-pools/replace` | 原子替换 scope 下的池（幂等） |
| GET | `/api/connection-pools` | 列表查询（可按 scope 筛选） |
| GET | `/api/connection-pools/{id}` | 获取单个池详情（含成员连接列表） |
| DELETE | `/api/connection-pools/{id}` | 删除连接池 |
| POST | `/api/connection-pools/{id}/members` | 批量添加连接（幂等） |
| DELETE | `/api/connection-pools/{id}/members` | 批量移除连接 |

对应新建：
- `backend/app/services/connection_pool_service.py`
- `backend/app/schemas/connection_pool.py`
- `backend/app/models/connection_pool.py`（ORM）

## 4. 前端

### 4.1 LLM 提取页面改造

在 `LlmExtractionPage.tsx` 顶部新增候选源切换：

| 切换选项 | 候选来源 | 表格 | 池概念 |
|---------|---------|------|--------|
| 脑区 | CandidateBrainRegion | DataFirstCandidatesTab | CandidatePool |
| 连接 | MirrorRegionConnection | ConnectionCandidatesTab（新） | ConnectionPool |

切换后：
- 表格切换为连接列表（从 Mirror KG 查询）
- 池操作映射到 ConnectionPool API
- 快速提取卡片内容随候选类型变化

### 4.2 连接候选 Tab（ConnectionCandidatesTab）

新建组件，复用 DataTable：
- 列：源脑区、靶脑区、连接类型、方向性、强度、置信度、mirror_status
- 筛选：按连接类型、脑区、confidence、mirror_status
- 支持多选 → 加入连接池
- 已入池的连接显示标记

### 4.3 Hook：useConnectionPool

新建 `frontend/src/pages/llm-extraction/hooks/useConnectionPool.ts`，类比 `useCandidatePool.ts`：
- `pool` / `loading` / `error` 状态
- `setPoolCandidates(connectionIds, scope)` → 调用 `POST /replace`
- `addToPool(ids)` / `removeFromPool(ids)`
- `clearPool()`

### 4.4 快速提取卡片适配

现有卡片：脑区功能、连接+功能、回路+步骤+功能

连接池模式下的卡片（新）：
- 连接字段补全 → 对池内连接执行字段补全
- 连接功能提取 → 对池内连接的源/靶脑区提取功能

### 4.5 Mirror KG 表格 → 加入连接池

在 `MirrorKgPanel` 的连接表格操作栏中新增「加入连接池」按钮：
- 选中连接 → 点击 → 调用 `POST /connection-pools/{id}/members`
- 如果当前 scope 下没有连接池，先自动创建

## 5. 提取执行

连接池的提取复用现有 LLM 提取服务，但候选来源不同：

| 场景 | 输入 | 现有服务 |
|------|------|---------|
| 连接字段补全 | connection_pool_memberships → target_ids | `llm_field_completion_service`（已有） |
| 连接功能提取 | 池内连接 → 源/靶脑区 → function extraction | `llm_extraction_service`（已有） |

连接池的提取不需要新的 LLM 提取逻辑——只需要把池成员 ID 列表作为 `target_ids` 传给现有服务。

## 6. Raw Parsing 来源（Phase 2）

未来 connectome 数据集的 Raw Parsing 支持：
- 新增 connectome parser（如 `connectome_csv_parser.py`）
- 解析后创建 `MirrorRegionConnection` 记录，`source = 'raw_parsing'`
- `connection_pools` 的 `source` 字段标记为 `'raw_parsing'`

Phase 1（当前）先实现 Mirror KG 手动选择入池。

## 7. 迁移

新建 migration SQL 文件：
```
backend/migrations/041_connection_pools.sql
```

## 8. 验收标准

1. LLM 提取页面可切换"脑区"/"连接"候选源
2. 连接模式下表格显示 Mirror KG 连接，支持筛选和多选
3. 可创建连接池、添加/移除成员
4. 连接池可触发字段补全
5. Mirror KG 表格可一键将连接加入连接池
6. 一个 scope 下只有一个活跃连接池
7. 不影响现有脑区池功能
