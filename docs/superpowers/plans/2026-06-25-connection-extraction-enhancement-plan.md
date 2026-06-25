# Connection Extraction Prompt & Pairing Enhancement — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Boost connection extraction from ~300 to 1000-1500 by fixing prompt conservatism, adding network context/pathway hints, breaking batch isolation with a candidate pool, and enabling concurrent LLM calls with smart pair ordering.

**Architecture:** Two independent tracks — Phase A (Tasks 5-8: prompt-only changes, deploy instantly) and Phase B (Tasks 1-4 + 9-15: new candidate pool infrastructure + name columns + concurrency). Phase A has zero dependencies on Phase B.

**Tech Stack:** Python 3.11+, FastAPI, SQLAlchemy async, PostgreSQL, Pydantic v2, asyncio

**Spec:** `docs/superpowers/specs/2026-06-25-connection-extraction-prompt-and-pairing-enhancement-design.md`

## Global Constraints

- Mirror KG is candidate layer — bias toward recall, not precision
- All LLM output goes to mirror_*, NEVER final_*
- No auto-approve, no auto-promote
- Must preserve existing `all_pairs` and `region_centered` strategies
- New migration files numbered 035, 036
- Cross-batch pool is additive — existing per-batch workflow continues to work

---

## File Map

| File | Action | Responsibility |
|------|--------|----------------|
| `backend/migrations/035_candidate_pools.sql` | Create | candidate_pools + candidate_pool_memberships tables |
| `backend/migrations/036_mirror_connection_names.sql` | Create | Add name columns to mirror_region_connections + backfill |
| `backend/app/models/candidate_pool.py` | Create | CandidatePool + CandidatePoolMembership ORM models |
| `backend/app/schemas/candidate_pool.py` | Create | Pydantic request/response schemas |
| `backend/app/services/candidate_pool_service.py` | Create | Pool CRUD + member management + resolve for extraction |
| `backend/app/routers/candidate_pool.py` | Create | REST API endpoints |
| `backend/app/main.py` | Modify | Register candidate pool router |
| `backend/app/services/llm_prompt_defaults.py` | Modify | A1 conservatism, A3 pathway hints, A2 template vars |
| `backend/app/services/llm_connection_extraction_service.py` | Modify | A2 context injection, B2 priority ordering, B3 concurrency+pack size |
| `backend/app/services/llm_extraction_prompt_engineering.py` | Modify | B2 priority scoring function, pack size constant |
| `backend/app/models/mirror_kg.py` | Modify | B4: Add name columns to MirrorRegionConnection |
| `backend/app/services/llm_to_mirror_service.py` | Modify | B4: Populate name columns on write |
| `backend/app/schemas/llm_composite_workflow.py` | Modify | Add candidate_pool_id field |

---

### Task 1: Migration — Candidate Pool Tables

**Files:**
- Create: `backend/migrations/035_candidate_pools.sql`

**Interfaces:**
- Produces: `candidate_pools` table (id, name, resource_id, batch_id, source_atlas, granularity_level, granularity_family, candidate_count, pair_count, status, created_at, updated_at) + `candidate_pool_memberships` table (id, pool_id FK, candidate_id FK, added_at, added_by)

- [ ] **Step 1: Write the migration SQL**

```sql
-- 035: Candidate Pools — cross-batch candidate accumulation for extraction
-- Manual execution only; the app does not auto-run this file.

CREATE TABLE IF NOT EXISTS candidate_pools (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    name VARCHAR(256),
    resource_id UUID REFERENCES atlas_resources(id) ON DELETE SET NULL,
    batch_id UUID REFERENCES import_batches(id) ON DELETE SET NULL,
    source_atlas VARCHAR(128) NOT NULL,
    granularity_level VARCHAR(32) NOT NULL,
    granularity_family VARCHAR(64),
    candidate_count INT NOT NULL DEFAULT 0,
    pair_count INT NOT NULL DEFAULT 0,
    status VARCHAR(32) NOT NULL DEFAULT 'active',
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

COMMENT ON TABLE candidate_pools IS 'Cross-batch candidate accumulation pools for LLM extraction';
COMMENT ON COLUMN candidate_pools.status IS 'active | locked | archived';

CREATE TABLE IF NOT EXISTS candidate_pool_memberships (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    pool_id UUID NOT NULL REFERENCES candidate_pools(id) ON DELETE CASCADE,
    candidate_id UUID NOT NULL REFERENCES candidate_brain_regions(id) ON DELETE CASCADE,
    added_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    added_by VARCHAR(128),
    UNIQUE(pool_id, candidate_id)
);

COMMENT ON TABLE candidate_pool_memberships IS 'Many-to-many membership linking candidate_pools to candidate_brain_regions';

CREATE INDEX IF NOT EXISTS idx_candidate_pools_status ON candidate_pools(status);
CREATE INDEX IF NOT EXISTS idx_candidate_pools_source_atlas ON candidate_pools(source_atlas);
CREATE INDEX IF NOT EXISTS idx_candidate_pool_memberships_pool ON candidate_pool_memberships(pool_id);
CREATE INDEX IF NOT EXISTS idx_candidate_pool_memberships_candidate ON candidate_pool_memberships(candidate_id);
```

- [ ] **Step 2: Apply migration manually**

```bash
psql -U postgres -d neurographiq_kg_v3_mvp1_e2e -f backend/migrations/035_candidate_pools.sql
```
Expected: `CREATE TABLE` + `CREATE INDEX` x5 without errors.

---

### Task 2: Migration — Mirror Connection Name Columns

**Files:**
- Create: `backend/migrations/036_mirror_connection_names.sql`

**Interfaces:**
- Produces: Four new columns on `mirror_region_connections`: `source_region_name_cn`, `source_region_name_en`, `target_region_name_cn`, `target_region_name_en`

- [ ] **Step 1: Write the migration SQL**

```sql
-- 036: Add region name columns to mirror_region_connections
-- Manual execution only; the app does not auto-run this file.

ALTER TABLE mirror_region_connections
  ADD COLUMN IF NOT EXISTS source_region_name_cn VARCHAR(256),
  ADD COLUMN IF NOT EXISTS source_region_name_en VARCHAR(256),
  ADD COLUMN IF NOT EXISTS target_region_name_cn VARCHAR(256),
  ADD COLUMN IF NOT EXISTS target_region_name_en VARCHAR(256);

COMMENT ON COLUMN mirror_region_connections.source_region_name_cn IS 'Source brain region Chinese name at extraction time';
COMMENT ON COLUMN mirror_region_connections.source_region_name_en IS 'Source brain region English name at extraction time';
COMMENT ON COLUMN mirror_region_connections.target_region_name_cn IS 'Target brain region Chinese name at extraction time';
COMMENT ON COLUMN mirror_region_connections.target_region_name_en IS 'Target brain region English name at extraction time';

-- Backfill existing rows from candidate_brain_regions
UPDATE mirror_region_connections mc
SET
  source_region_name_cn = src.cn_name,
  source_region_name_en = src.en_name,
  target_region_name_cn = tgt.cn_name,
  target_region_name_en = tgt.en_name
FROM candidate_brain_regions src, candidate_brain_regions tgt
WHERE mc.source_region_candidate_id = src.id
  AND mc.target_region_candidate_id = tgt.id
  AND mc.source_region_name_cn IS NULL;
```

- [ ] **Step 2: Apply migration**

```bash
psql -U postgres -d neurographiq_kg_v3_mvp1_e2e -f backend/migrations/036_mirror_connection_names.sql
```
Expected: `ALTER TABLE` + backfill completes. Verify with:
```sql
SELECT count(*) FROM mirror_region_connections WHERE source_region_name_cn IS NOT NULL;
```

---

### Task 3: Candidate Pool — Models + Schemas

**Files:**
- Create: `backend/app/models/candidate_pool.py`
- Create: `backend/app/schemas/candidate_pool.py`

**Interfaces:**
- Produces: `CandidatePool` ORM model, `CandidatePoolMembership` ORM model, `CandidatePoolCreate`, `CandidatePoolRead`, `CandidatePoolMembershipRead`, `CandidatePoolListParams` Pydantic schemas

- [ ] **Step 1: Write the ORM models**

```python
# backend/app/models/candidate_pool.py
"""Candidate Pool ORM models — cross-batch candidate accumulation for LLM extraction."""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import Any

from sqlalchemy import DateTime, ForeignKey, Integer, String, UniqueConstraint, func
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.models.base import Base


class CandidatePool(Base):
    __tablename__ = "candidate_pools"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    name: Mapped[str | None] = mapped_column(String(256), nullable=True)
    resource_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("atlas_resources.id", ondelete="SET NULL"), nullable=True
    )
    batch_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("import_batches.id", ondelete="SET NULL"), nullable=True
    )
    source_atlas: Mapped[str] = mapped_column(String(128), nullable=False)
    granularity_level: Mapped[str] = mapped_column(String(32), nullable=False)
    granularity_family: Mapped[str | None] = mapped_column(String(64), nullable=True)
    candidate_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    pair_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    status: Mapped[str] = mapped_column(String(32), nullable=False, default="active")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )

    memberships: Mapped[list["CandidatePoolMembership"]] = relationship(
        "CandidatePoolMembership", back_populates="pool", cascade="all, delete-orphan"
    )


class CandidatePoolMembership(Base):
    __tablename__ = "candidate_pool_memberships"
    __table_args__ = (
        UniqueConstraint("pool_id", "candidate_id", name="uq_pool_candidate"),
    )

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    pool_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("candidate_pools.id", ondelete="CASCADE"), nullable=False
    )
    candidate_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("candidate_brain_regions.id", ondelete="CASCADE"), nullable=False
    )
    added_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    added_by: Mapped[str | None] = mapped_column(String(128), nullable=True)

    pool: Mapped["CandidatePool"] = relationship("CandidatePool", back_populates="memberships")
```

- [ ] **Step 2: Write the Pydantic schemas**

```python
# backend/app/schemas/candidate_pool.py
"""Candidate Pool request/response schemas."""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import Optional

from pydantic import BaseModel, Field


class CandidatePoolCreate(BaseModel):
    name: str | None = None
    candidate_ids: list[uuid.UUID] = Field(..., min_length=2)
    resource_id: uuid.UUID | None = None
    batch_id: uuid.UUID | None = None
    source_atlas: str
    granularity_level: str
    granularity_family: str | None = None


class CandidatePoolMembersAdd(BaseModel):
    candidate_ids: list[uuid.UUID] = Field(..., min_length=1)


class CandidatePoolMembersRemove(BaseModel):
    candidate_ids: list[uuid.UUID] = Field(..., min_length=1)


class CandidatePoolMembershipRead(BaseModel):
    id: uuid.UUID
    pool_id: uuid.UUID
    candidate_id: uuid.UUID
    added_at: datetime
    added_by: str | None = None

    model_config = {"from_attributes": True}


class CandidatePoolRead(BaseModel):
    id: uuid.UUID
    name: str | None = None
    resource_id: uuid.UUID | None = None
    batch_id: uuid.UUID | None = None
    source_atlas: str
    granularity_level: str
    granularity_family: str | None = None
    candidate_count: int
    pair_count: int
    status: str
    created_at: datetime
    updated_at: datetime
    memberships: list[CandidatePoolMembershipRead] = []

    model_config = {"from_attributes": True}


class CandidatePoolListParams(BaseModel):
    source_atlas: str | None = None
    granularity_level: str | None = None
    granularity_family: str | None = None
    status: str | None = None
    limit: int = Field(default=50, ge=1, le=200)
    offset: int = Field(default=0, ge=0)
```

---

### Task 4: Candidate Pool — Service + Router

**Files:**
- Create: `backend/app/services/candidate_pool_service.py`
- Create: `backend/app/routers/candidate_pool.py`
- Modify: `backend/app/main.py`

**Interfaces:**
- Consumes: `CandidatePool`, `CandidatePoolMembership` models, `CandidatePoolCreate` etc. schemas, `CandidateBrainRegion` model
- Produces: REST endpoints at `/api/candidates/pools`, service functions for pool CRUD and member resolution

- [ ] **Step 1: Write the service**

```python
# backend/app/services/candidate_pool_service.py
"""Candidate pool CRUD — cross-batch candidate accumulation for LLM extraction."""

from __future__ import annotations

import uuid

from sqlalchemy import func, select, delete
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.candidate_pool import CandidatePool, CandidatePoolMembership
from app.models.candidate import CandidateBrainRegion


def _compute_pair_count(n: int) -> int:
    if n < 2:
        return 0
    return n * (n - 1) // 2


async def create_pool(
    session: AsyncSession,
    *,
    name: str | None,
    candidate_ids: list[uuid.UUID],
    resource_id: uuid.UUID | None,
    batch_id: uuid.UUID | None,
    source_atlas: str,
    granularity_level: str,
    granularity_family: str | None,
) -> CandidatePool:
    # Load candidates to validate scope
    q = select(CandidateBrainRegion).where(CandidateBrainRegion.id.in_(candidate_ids))
    result = await session.execute(q)
    candidates = list(result.scalars().all())
    if len(candidates) < 2:
        raise ValueError("At least 2 valid candidate IDs are required")

    pool = CandidatePool(
        name=name,
        resource_id=resource_id or candidates[0].resource_id,
        batch_id=batch_id,
        source_atlas=source_atlas or candidates[0].source_atlas,
        granularity_level=granularity_level or candidates[0].granularity_level,
        granularity_family=granularity_family or candidates[0].granularity_family,
        candidate_count=len(candidate_ids),
        pair_count=_compute_pair_count(len(candidate_ids)),
    )
    session.add(pool)
    await session.flush()

    for cid in candidate_ids:
        session.add(CandidatePoolMembership(pool_id=pool.id, candidate_id=cid))

    await session.flush()
    return pool


async def get_pool(session: AsyncSession, pool_id: uuid.UUID) -> CandidatePool | None:
    from sqlalchemy.orm import selectinload
    q = (
        select(CandidatePool)
        .where(CandidatePool.id == pool_id)
        .options(selectinload(CandidatePool.memberships))
    )
    result = await session.execute(q)
    return result.scalar_one_or_none()


async def list_pools(
    session: AsyncSession,
    *,
    source_atlas: str | None = None,
    granularity_level: str | None = None,
    granularity_family: str | None = None,
    status: str | None = None,
    limit: int = 50,
    offset: int = 0,
) -> tuple[list[CandidatePool], int]:
    from sqlalchemy.orm import selectinload

    base = select(CandidatePool)
    if source_atlas:
        base = base.where(CandidatePool.source_atlas == source_atlas)
    if granularity_level:
        base = base.where(CandidatePool.granularity_level == granularity_level)
    if granularity_family:
        base = base.where(CandidatePool.granularity_family == granularity_family)
    if status:
        base = base.where(CandidatePool.status == status)

    count_q = select(func.count()).select_from(base.subquery())
    total = int((await session.execute(count_q)).scalar_one() or 0)

    q = (
        base.order_by(CandidatePool.created_at.desc())
        .options(selectinload(CandidatePool.memberships))
        .limit(limit)
        .offset(offset)
    )
    pools = list((await session.execute(q)).scalars().all())
    return pools, total


async def add_members(
    session: AsyncSession,
    pool_id: uuid.UUID,
    candidate_ids: list[uuid.UUID],
) -> CandidatePool:
    pool = await get_pool(session, pool_id)
    if pool is None:
        raise KeyError(f"Pool {pool_id} not found")

    existing = {m.candidate_id for m in pool.memberships}
    new_ids = [cid for cid in candidate_ids if cid not in existing]
    for cid in new_ids:
        session.add(CandidatePoolMembership(pool_id=pool_id, candidate_id=cid))

    pool.candidate_count = len(existing) + len(new_ids)
    pool.pair_count = _compute_pair_count(pool.candidate_count)
    await session.flush()
    await session.refresh(pool)
    return pool


async def remove_members(
    session: AsyncSession,
    pool_id: uuid.UUID,
    candidate_ids: list[uuid.UUID],
) -> CandidatePool:
    pool = await get_pool(session, pool_id)
    if pool is None:
        raise KeyError(f"Pool {pool_id} not found")

    await session.execute(
        delete(CandidatePoolMembership).where(
            CandidatePoolMembership.pool_id == pool_id,
            CandidatePoolMembership.candidate_id.in_(candidate_ids),
        )
    )
    remaining = {m.candidate_id for m in pool.memberships} - set(candidate_ids)
    pool.candidate_count = len(remaining)
    pool.pair_count = _compute_pair_count(pool.candidate_count)
    await session.flush()
    await session.refresh(pool)
    return pool


async def delete_pool(session: AsyncSession, pool_id: uuid.UUID) -> bool:
    pool = await session.get(CandidatePool, pool_id)
    if pool is None:
        return False
    await session.delete(pool)
    await session.flush()
    return True


async def resolve_pool_candidate_ids(
    session: AsyncSession,
    pool_id: uuid.UUID,
) -> list[uuid.UUID]:
    """Resolve all candidate IDs in a pool for extraction use."""
    q = select(CandidatePoolMembership.candidate_id).where(
        CandidatePoolMembership.pool_id == pool_id
    )
    result = await session.execute(q)
    return [row[0] for row in result.all()]
```

- [ ] **Step 2: Write the router**

```python
# backend/app/routers/candidate_pool.py
"""Candidate Pool REST API."""

from __future__ import annotations

import uuid

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import get_db
from app.schemas.candidate_pool import (
    CandidatePoolCreate,
    CandidatePoolListParams,
    CandidatePoolMembersAdd,
    CandidatePoolMembersRemove,
    CandidatePoolRead,
)
from app.services import candidate_pool_service as svc

router = APIRouter()


@router.post("/pools", response_model=CandidatePoolRead, status_code=201)
async def create_pool(body: CandidatePoolCreate, db: AsyncSession = Depends(get_db)):
    try:
        pool = await svc.create_pool(
            db,
            name=body.name,
            candidate_ids=body.candidate_ids,
            resource_id=body.resource_id,
            batch_id=body.batch_id,
            source_atlas=body.source_atlas,
            granularity_level=body.granularity_level,
            granularity_family=body.granularity_family,
        )
        await db.commit()
        return pool
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))


@router.get("/pools", response_model=dict)
async def list_pools(
    source_atlas: str | None = None,
    granularity_level: str | None = None,
    granularity_family: str | None = None,
    status: str | None = None,
    limit: int = 50,
    offset: int = 0,
    db: AsyncSession = Depends(get_db),
):
    pools, total = await svc.list_pools(
        db,
        source_atlas=source_atlas,
        granularity_level=granularity_level,
        granularity_family=granularity_family,
        status=status,
        limit=limit,
        offset=offset,
    )
    return {"items": pools, "total": total}


@router.get("/pools/{pool_id}", response_model=CandidatePoolRead)
async def get_pool(pool_id: uuid.UUID, db: AsyncSession = Depends(get_db)):
    pool = await svc.get_pool(db, pool_id)
    if pool is None:
        raise HTTPException(status_code=404, detail="Pool not found")
    return pool


@router.post("/pools/{pool_id}/members", response_model=CandidatePoolRead)
async def add_members(pool_id: uuid.UUID, body: CandidatePoolMembersAdd, db: AsyncSession = Depends(get_db)):
    try:
        pool = await svc.add_members(db, pool_id, body.candidate_ids)
        await db.commit()
        return pool
    except KeyError:
        raise HTTPException(status_code=404, detail="Pool not found")


@router.delete("/pools/{pool_id}/members", response_model=CandidatePoolRead)
async def remove_members(pool_id: uuid.UUID, body: CandidatePoolMembersRemove, db: AsyncSession = Depends(get_db)):
    try:
        pool = await svc.remove_members(db, pool_id, body.candidate_ids)
        await db.commit()
        return pool
    except KeyError:
        raise HTTPException(status_code=404, detail="Pool not found")


@router.delete("/pools/{pool_id}", status_code=204)
async def delete_pool(pool_id: uuid.UUID, db: AsyncSession = Depends(get_db)):
    deleted = await svc.delete_pool(db, pool_id)
    if not deleted:
        raise HTTPException(status_code=404, detail="Pool not found")
    await db.commit()
```

- [ ] **Step 3: Register router in main.py**

In `backend/app/main.py`, add after the existing candidate router imports:

```python
from app.routers import candidate_pool

app.include_router(candidate_pool.router, prefix="/api/candidates", tags=["Candidate Pools"])
```

- [ ] **Step 4: Verify router is registered**

```bash
cd backend && .venv/Scripts/python.exe -c "
from app.main import app
routes = [r.path for r in app.routes if hasattr(r, 'path')]
print([r for r in routes if 'pool' in r])
"
```
Expected: `['/api/candidates/pools', '/api/candidates/pools/{pool_id}', '/api/candidates/pools/{pool_id}/members']`

---

### Task 5: A1 — Adjust Prompt Conservatism

**Files:**
- Modify: `backend/app/services/llm_prompt_defaults.py`

**Interfaces:**
- Modifies: `SAME_GRANULARITY_CONNECTION_COMPLETION_V1.system_prompt`

- [ ] **Step 1: Update system_prompt for recall bias**

Replace the `system_prompt` in `SAME_GRANULARITY_CONNECTION_COMPLETION_V1` (lines 61-93 in current file):

```python
    system_prompt=(
        "你是一名神经科学家、神经解剖学家、脑区连接组专家和医学知识图谱构建专家。"
        "你的任务是基于输入的脑区候选和同粒度脑区 pair，判断是否存在可追溯、可审核的连接关系。\n"
        "You are a neuroscience, neuroanatomy, brain connectivity, and biomedical knowledge graph expert. "
        "Your output must be conservative, evidence-aware, schema-aligned, and suitable for human review before promotion.\n\n"
        "核心原则 — Mirror KG 候选层（非 final fact）：\n"
        "Mirror KG 是候选暂存层，所有 connection 都需要人工审核才能晋升。"
        "因此请偏向召回（宁可多报低置信度候选），而不是偏向精确（宁可漏报）。\n\n"
        "置信度分层指南：\n"
        "- 0.7-1.0 (high): 多文献支持或经典教科书明确描述\n"
        "- 0.4-0.7 (moderate): 单文献支持或知名数据库（如 Brainnetome、HCP）收录\n"
        "- 0.1-0.4 (low): 基于解剖邻近性、已知网络拓扑推断、或一般神经科学常识支持\n"
        "- 即使 confidence 很低也应输出 projection（标记 evidence_level=insufficient），"
        "  不要丢弃——低置信度候选恰恰是人工审核最有价值的对象\n\n"
        "仅当以下情况才返回 no_connection：\n"
        "- 两个脑区在解剖学上不可能存在直接连接（如物理隔离的不同系统）\n"
        "- 已有明确文献证据明确排除该连接\n\n"
        "任务约束：\n"
        "1. 你必须逐一判断输入的每个 pair；\n"
        "2. 每个 pair 必须返回 projection 或 no_connection；\n"
        "3. 不允许忽略 pair；不允许只处理前几个 pair；\n"
        "4. 不允许输出没有 pair_id 的 projection；\n"
        "5. 不允许凭空创造连接；\n"
        "6. 连接方向不确定时 directionality=\"unknown\"；\n"
        "7. 不确定但合理时应输出 projection，confidence 0.1-0.3，evidence_level=insufficient；\n"
        "8. 仅当连接在解剖学上不可能时才使用 no_connection；\n"
        "9. 输出必须使用 mirror_region_connections 对齐字段；\n"
        "10. 不写正式库；不写 final；不写 kg；不自动审核；不自动晋升。\n"
        "禁止跨 atlas。禁止跨颗粒度。禁止按名称自动合并不同 atlas 的脑区。"
        "输出仅为 Mirror KG 候选，不是 final 事实，不是 kg_*，不得声称已通过人工审核。\n"
        "强制输出格式（必须严格遵守）：\n"
        "- 只输出一个 JSON object；\n"
        "- 不要 Markdown；不要 ```json；不要代码块包裹；\n"
        "- 不要解释文字；不要自然语言前缀；不要在 JSON 前后追加任何说明或总结；\n"
        "- JSON 顶层必须且只能包含 projections、no_connections、warnings 三个键；\n"
        "- 每个输入 pair 必须出现在 projections 或 no_connections 中，且必须带 pair_id；\n"
        "- 不知道时放入 no_connections 并写 reason；不允许忽略 pair。\n"
        "无论是否发现连接，都必须返回合法 JSON。"
        "即使所有 pair 都无连接，也必须返回 "
        '{"projections": [], "no_connections": [...], "warnings": []}。'
        "禁止返回自然语言解释。\n"
        "字段命名约定：必须使用 projection_type（不要使用 connection_type），"
        "字段值必须严格使用下方 schema 中定义的值（如 \"anatomical\" 不是 \"structural_connection\"）。"
    ),
```

- [ ] **Step 2: Run existing connection extraction tests**

```bash
cd backend && .venv/Scripts/python.exe -m pytest tests/ -q -k "connection" 2>&1
```
Expected: All existing tests pass (prompt change should not break parsing).

---

### Task 6: A3 — Add Classical Pathway Hints

**Files:**
- Modify: `backend/app/services/llm_prompt_defaults.py`

**Interfaces:**
- Modifies: `SAME_GRANULARITY_CONNECTION_COMPLETION_V1.user_prompt_template` to include `{{pathway_hints}}`

- [ ] **Step 1: Define pathway hints constant**

Add after `SAME_GRANULARITY_CONNECTION_COMPLETION_V1` definition in `llm_prompt_defaults.py`:

```python
CONNECTION_PATHWAY_HINTS = (
    "经典神经通路参考（如果当前 pair 涉及以下通路中的脑区对，请标注对应通路并给较高 confidence）：\n"
    "1. 默认模式网络 (DMN): 内侧前额叶(mPFC) ↔ 后扣带(PCC) ↔ 角回 ↔ 海马\n"
    "2. 突显网络 (SN): 前岛叶 ↔ 背侧前扣带(dACC) ↔ 杏仁核\n"
    "3. 中央执行网络 (CEN): 背外侧前额叶(dlPFC) ↔ 后顶叶(PPC)\n"
    "4. 边缘系统: 海马 ↔ 杏仁核 ↔ 下丘脑 ↔ 前扣带\n"
    "5. Papez 回路: 海马 → 穹窿 → 乳头体 → 丘脑前核 → 扣带回 → 海马旁回 → 海马\n"
    "6. 基底节环路: 皮质 → 纹状体 → 苍白球 → 丘脑 → 皮质 (直接/间接/超直接)\n"
    "7. 小脑环路: 皮质 → 脑桥 → 小脑 → 丘脑 → 皮质\n"
    "8. 视觉通路: 视网膜 → LGN → V1 → 背侧通路(MT/MST) / 腹侧通路(IT)\n"
    "9. 听觉通路: 耳蜗核 → 上橄榄核 → 下丘 → MGN → A1\n"
    "10. 体感通路: 脊髓 → 丘脑(VPL/VPM) → S1 → S2 → 后顶叶\n"
    "11. 运动通路: M1 → 内囊 → 脑干 → 脊髓 (皮质脊髓束)\n"
    "12. 语言网络: Broca区 ↔ Wernicke区 ↔ 弓状束\n"
    "13. 注意网络: 顶叶(IPS/FEF) ↔ 额叶眼动区(FEF) ↔ 上丘 ↔ 丘脑枕\n"
    "14. 奖赏通路: 腹侧被盖区(VTA) → 伏隔核(NAc) → 前额叶\n"
    "15. 恐惧回路: 杏仁核 ↔ 下丘脑 ↔ 导水管周围灰质(PAG)\n"
)
```

- [ ] **Step 2: Update user_prompt_template to accept pathway_hints**

In `SAME_GRANULARITY_CONNECTION_COMPLETION_V1.user_prompt_template`, insert `{{pathway_hints}}` before the constraint block:

```python
    user_prompt_template=(
        "请基于以下同颗粒度脑区 pair（compact context），逐一判断是否存在合理连接/投射候选。"
        "输出必须是 JSON，不要输出 markdown。\n\n"
        "scope:\n"
        "source_atlas={{source_atlas}}\n"
        "granularity_level={{granularity_level}}\n"
        "granularity_family={{granularity_family}}\n\n"
        "{{pathway_hints}}\n"
        "约束：\n"
        "- 仅在上述 atlas / granularity 内部生成连接；\n"
        "- 每个 pair 必须有 pair_id；\n"
        "- 无连接时写入 no_connections；\n"
        "- 不要把完整 candidate object 或 attributes/raw JSON 复制到输出；\n"
        "- evidence_level 只能是 low / moderate / high / insufficient。\n\n"
        "候选 pair（compact context）：\n{{pairs_json}}\n\n"
        # ... rest unchanged ...
    ),
```

- [ ] **Step 3: Update build_connection_completion_prompt to pass pathway_hints**

In `backend/app/services/llm_connection_extraction_service.py`, update `build_connection_completion_prompt`:

```python
def build_connection_completion_prompt(
    candidates: list[CandidateBrainRegion],
    pair_records: list[dict[str, Any]],
    template_key: str = CONNECTION_TEMPLATE_KEY,
) -> tuple[str, str, dict[str, Any]]:
    tpl = _resolve_template(template_key)
    first = candidates[0]
    pairs_json = json.dumps(pair_records, ensure_ascii=False, indent=2)

    values = {
        "source_atlas": first.source_atlas,
        "granularity_level": first.granularity_level,
        "granularity_family": first.granularity_family or "",
        "pairs_json": pairs_json,
        "pathway_hints": CONNECTION_PATHWAY_HINTS,
    }
    user_prompt = render_user_prompt(tpl, values)
    # ... rest unchanged ...
```

- [ ] **Step 4: Import CONNECTION_PATHWAY_HINTS in connection extraction service**

At top of `llm_connection_extraction_service.py`, add to the import from `llm_extraction_prompt_engineering` or import directly from `llm_prompt_defaults`:

```python
from app.services.llm_prompt_defaults import CONNECTION_PATHWAY_HINTS
```

---

### Task 7: A2 — Network Context Injection

**Files:**
- Modify: `backend/app/services/llm_connection_extraction_service.py`
- Modify: `backend/app/services/llm_prompt_defaults.py`

**Interfaces:**
- Modifies: `build_connection_completion_prompt` to accept optional `pool_context` dict and render `{{batch_context}}` in template

- [ ] **Step 1: Add batch_context to user_prompt_template**

In `SAME_GRANULARITY_CONNECTION_COMPLETION_V1.user_prompt_template`, add `{{batch_context}}` before pairs:

```python
    user_prompt_template=(
        "请基于以下同颗粒度脑区 pair（compact context），逐一判断是否存在合理连接/投射候选。"
        "输出必须是 JSON，不要输出 markdown。\n\n"
        "scope:\n"
        "source_atlas={{source_atlas}}\n"
        "granularity_level={{granularity_level}}\n"
        "granularity_family={{granularity_family}}\n\n"
        "{{batch_context}}\n"
        "{{pathway_hints}}\n"
        "约束：\n"
        # ... rest unchanged ...
    ),
```

- [ ] **Step 2: Build batch_context JSON string in build_connection_completion_prompt**

```python
def _build_batch_context_json(
    candidates: list[CandidateBrainRegion],
    pair_records: list[dict[str, Any]],
    pack_index: int,
    total_packs: int,
    total_pairs: int,
) -> str:
    """Build a compact batch context summary for the prompt."""
    regions_in_pack: set[str] = set()
    for pr in pair_records:
        regions_in_pack.add(pr["source_region_name_cn"] or pr["source_region_name_en"] or "")
        regions_in_pack.add(pr["target_region_name_cn"] or pr["target_region_name_en"] or "")
    
    region_list = "\n".join(
        f"  - {c.cn_name or c.en_name} ({c.en_name or ''}) laterality={c.laterality or '?'}"
        for c in candidates
    )
    
    return (
        f"全量脑区池概览：\n"
        f"  本池共 {len(candidates)} 个脑区，全量配对 {total_pairs} 对，共 {total_packs} 包\n"
        f"  当前为第 {pack_index + 1}/{total_packs} 包，本包 {len(pair_records)} 对\n\n"
        f"池内全部脑区：\n{region_list}\n\n"
        f"提示：可利用池内全部脑区的拓扑关系辅助判断——"
        f"如果某对脑区之间虽无直接文献但解剖邻近或参与同一网络，"
        f"应标记为低置信度候选而非 no_connection。"
    )


def build_connection_completion_prompt(
    candidates: list[CandidateBrainRegion],
    pair_records: list[dict[str, Any]],
    template_key: str = CONNECTION_TEMPLATE_KEY,
    *,
    pack_index: int = 0,
    total_packs: int = 1,
    total_pairs: int | None = None,
) -> tuple[str, str, dict[str, Any]]:
    tpl = _resolve_template(template_key)
    first = candidates[0]
    pairs_json = json.dumps(pair_records, ensure_ascii=False, indent=2)
    total = total_pairs if total_pairs is not None else len(pair_records)
    batch_context = _build_batch_context_json(candidates, pair_records, pack_index, total_packs, total)

    values = {
        "source_atlas": first.source_atlas,
        "granularity_level": first.granularity_level,
        "granularity_family": first.granularity_family or "",
        "pairs_json": pairs_json,
        "pathway_hints": CONNECTION_PATHWAY_HINTS,
        "batch_context": batch_context,
    }
    user_prompt = render_user_prompt(tpl, values)
    prompt_json = {
        "template_key": tpl.template_key,
        "prompt_display_name": prompt_display_name(tpl.template_key),
        "version": tpl.version,
        "system_prompt": tpl.system_prompt,
        "user_prompt": user_prompt,
        "pairs_json": pairs_json,
        "pair_count": len(pair_records),
    }
    return tpl.system_prompt, user_prompt, prompt_json
```

- [ ] **Step 3: Update call sites in the pack loop**

In `run_same_granularity_connection_extraction`, update the per-pack `build_connection_completion_prompt` call (around line 934) to pass context:

```python
        pack_system, pack_user, _ = build_connection_completion_prompt(
            candidates, pack, prompt_template_key,
            pack_index=pack_index,
            total_packs=len(packs),
            total_pairs=len(pairs),
        )
```

Also update the initial preview call (around line 692):

```python
    system_prompt, user_prompt, prompt_json = build_connection_completion_prompt(
        candidates, pair_records[: min(len(pair_records), DEFAULT_PAIRS_PER_PACK)], prompt_template_key,
        pack_index=0,
        total_packs=len(packs),
        total_pairs=len(pairs),
    )
```

---

### Task 8: B2 — Priority-Based Pack Ordering

**Files:**
- Modify: `backend/app/services/llm_extraction_prompt_engineering.py`
- Modify: `backend/app/services/llm_connection_extraction_service.py`

**Interfaces:**
- Adds: `score_pair_priority()` function in prompt_engineering
- Modifies: `compute_pairs` to return scored+ordered pairs

- [ ] **Step 1: Add priority scoring function**

In `backend/app/services/llm_extraction_prompt_engineering.py`, add after `build_compact_pair_records`:

```python
def score_pair_priority(
    src_candidate: Any,
    tgt_candidate: Any,
) -> int:
    """Score a candidate pair 0-100 for pack ordering. Higher = earlier pack.
    
    No pairs are ever excluded — this only affects pack order.
    """
    score = 0
    src_name = (src_candidate.en_name or src_candidate.cn_name or "").lower()
    tgt_name = (tgt_candidate.en_name or tgt_candidate.cn_name or "").lower()
    
    # Same laterality: +20
    src_lat = getattr(src_candidate, "laterality", None)
    tgt_lat = getattr(tgt_candidate, "laterality", None)
    if src_lat and tgt_lat and src_lat == tgt_lat:
        score += 20
    
    # Both hemispheres (L-R or R-L): -10 (still evaluate, just later)
    if src_lat and tgt_lat and src_lat != tgt_lat:
        score -= 10
    
    return score


def order_pairs_by_priority(
    pairs: list[tuple[uuid.UUID, uuid.UUID]],
    candidate_map: dict[uuid.UUID, Any],
) -> list[tuple[uuid.UUID, uuid.UUID]]:
    """Sort pairs by descending priority score."""
    scored = [
        (score_pair_priority(candidate_map[a], candidate_map[b]), (a, b))
        for a, b in pairs
    ]
    scored.sort(key=lambda x: x[0], reverse=True)
    return [pair for _, pair in scored]
```

- [ ] **Step 2: Apply ordering in connection extraction flow**

In `run_same_granularity_connection_extraction` (around line 669-675), after `compute_pairs`:

```python
    pairs = compute_pairs(
        [c.id for c in candidates],
        pair_strategy=pair_strategy,
        center_candidate_id=center_candidate_id,
    )
    # Order by priority: same-hemisphere pairs first, cross-hemisphere later
    cand_map = {c.id: c for c in candidates}
    pairs = order_pairs_by_priority(pairs, cand_map)
    pair_records = build_compact_pair_records(candidates, pairs)
```

- [ ] **Step 3: Update imports**

In `llm_connection_extraction_service.py`, add to the import from `llm_extraction_prompt_engineering`:

```python
from app.services.llm_extraction_prompt_engineering import (
    # ... existing imports ...
    order_pairs_by_priority,
)
```

---

### Task 9: B3 — Concurrency + Pack Size Increase

**Files:**
- Modify: `backend/app/services/llm_extraction_prompt_engineering.py`
- Modify: `backend/app/services/llm_connection_extraction_service.py`

**Interfaces:**
- Changes: `DEFAULT_PAIRS_PER_PACK` 20 → 30
- Adds: `DEFAULT_CONCURRENT_PACKS = 5`
- Modifies: pack processing loop to use `asyncio.Semaphore`

- [ ] **Step 1: Increase pack size**

In `backend/app/services/llm_extraction_prompt_engineering.py`:

```python
DEFAULT_PAIRS_PER_PACK = 30  # was 20
```

- [ ] **Step 2: Add concurrent pack processing**

In `backend/app/services/llm_connection_extraction_service.py`, replace the sequential `for pack_index, pack in enumerate(packs):` loop (starting around line 921) with a concurrent version. Add this helper and modify the loop:

```python
import asyncio

DEFAULT_CONCURRENT_PACKS = 5


async def _process_single_pack(
    pack: list[dict[str, Any]],
    pack_index: int,
    candidates: list[CandidateBrainRegion],
    prompt_template_key: str,
    provider,
    resolved_model: str,
    temperature: float,
    max_tokens: int,
    allowed_types: frozenset[str],
    allowed_candidate_ids: set[uuid.UUID],
    total_packs: int,
    total_pairs: int,
    audit: ConnectionExecutionAudit,
    pack_traces: list[dict[str, Any]],
    run: LlmExtractionRun,
    item: LlmExtractionItem,
    composite_workflow_run_id: uuid.UUID | None,
    debug_mode: bool,
    max_provider_attempts: int,
    _persist_pack_trace,
    _log_event,
    _emit_progress,
    on_progress,
) -> tuple[list[dict[str, Any]], list[dict[str, Any]], list[str], set[str], int, bool]:
    """Process one pack — called under semaphore for concurrency control."""
    normalized: list[dict[str, Any]] = []
    no_connections: list[dict[str, Any]] = []
    warnings: list[str] = []
    processed_ids: set[str] = set()
    parse_failures = 0
    fail_fast = False

    # Build prompt
    pack_system, pack_user, _ = build_connection_completion_prompt(
        candidates, pack, prompt_template_key,
        pack_index=pack_index,
        total_packs=total_packs,
        total_pairs=total_pairs,
    )

    # Call LLM with retry
    for attempt in range(max_provider_attempts):
        try:
            response = await provider.chat_completion(
                model=resolved_model,
                messages=[
                    {"role": "system", "content": pack_system},
                    {"role": "user", "content": pack_user},
                ],
                temperature=temperature,
                max_tokens=max_tokens,
            )
            audit.provider_call_count += 1
            audit.provider_success_count += 1
            
            parsed = parse_connection_completion_response(response)
            pack_normalized, pack_warnings = normalize_connection_candidates(
                parsed,
                allowed_candidate_ids=allowed_candidate_ids,
                allowed_connection_types=allowed_types,
            )
            normalized.extend(pack_normalized)
            warnings.extend(pack_warnings)
            
            for conn in pack_normalized:
                pair_id = f"{conn['source_candidate_id']}::{conn['target_candidate_id']}"
                processed_ids.add(pair_id)
            
            no_connections.extend(parsed.get("no_connections", []))
            audit.parsed_projection_count += len(pack_normalized)
            audit.parsed_no_connection_count += len(no_connections)
            break
            
        except Exception as exc:
            audit.provider_call_count += 1
            audit.provider_error_count += 1
            if attempt == max_provider_attempts - 1:
                warnings.append(f"pack[{pack_index}] failed after {max_provider_attempts} attempts: {exc}")
                parse_failures += 1
                audit.parse_error_count += 1

    # Update trace
    pack_trace = {
        "pack_id": f"pack_{pack_index}",
        "pack_index": pack_index,
        "pair_count": len(pack),
        "parsed_count": len(normalized),
        "no_connection_count": len(no_connections),
        "status": "ok" if parse_failures == 0 else "parse_error",
    }
    pack_traces.append(pack_trace)

    return normalized, no_connections, warnings, processed_ids, parse_failures, fail_fast
```

Then in the main flow, replace the sequential loop with:

```python
    semaphore = asyncio.Semaphore(DEFAULT_CONCURRENT_PACKS)
    
    async def _process_with_limit(pack, idx):
        async with semaphore:
            if composite_workflow_run_id and is_cancelling(composite_workflow_run_id):
                return [], [], [], set(), 0, False
            return await _process_single_pack(
                pack, idx, candidates, prompt_template_key, provider,
                resolved_model, temperature, max_tokens, allowed_types,
                allowed_candidate_ids, len(packs), len(pairs),
                audit, pack_traces, run, item,
                composite_workflow_run_id, debug_mode, max_provider_attempts,
                _persist_pack_trace, _log_event, _emit_progress, on_progress,
            )
    
    # Process all packs concurrently with semaphore
    tasks = [_process_with_limit(pack, i) for i, pack in enumerate(packs)]
    results = await asyncio.gather(*tasks)
    
    for norm, no_conns, warns, proc_ids, pf, ff in results:
        normalized_connections.extend(norm)
        all_no_connections.extend(no_conns)
        all_warnings.extend(warns)
        processed_pair_ids.update(proc_ids)
        consecutive_parse_failures += pf
        if ff:
            fail_fast_triggered = True
            break
    
    if fail_fast_triggered:
        remaining_pack_count_skipped = len(packs) - len(results)
```

**Note:** The concurrent refactor is the most complex change. If the full `_process_single_pack` refactor is too risky, a simpler approach keeps the sequential loop but adds `asyncio.gather` inside each iteration for batches of `DEFAULT_CONCURRENT_PACKS` packs:

```python
    # Simpler alternative: batch packs into concurrent groups
    for batch_start in range(0, len(packs), DEFAULT_CONCURRENT_PACKS):
        batch = packs[batch_start:batch_start + DEFAULT_CONCURRENT_PACKS]
        batch_tasks = [
            _process_single_pack(pack, batch_start + i, ...)
            for i, pack in enumerate(batch)
        ]
        batch_results = await asyncio.gather(*batch_tasks)
        # ... aggregate results ...
```

---

### Task 10: B4 — Write Name Columns During Connection Creation

**Files:**
- Modify: `backend/app/models/mirror_kg.py`
- Modify: `backend/app/services/llm_to_mirror_service.py` (or wherever connections are written to DB)

**Interfaces:**
- Adds: 4 name columns to `MirrorRegionConnection` model
- Modifies: connection write path to populate names from candidate lookup

- [ ] **Step 1: Add name columns to MirrorRegionConnection model**

In `backend/app/models/mirror_kg.py`, add after `target_region_final_id` (line 35):

```python
    source_region_name_cn: Mapped[str | None] = mapped_column(String(256), nullable=True)
    source_region_name_en: Mapped[str | None] = mapped_column(String(256), nullable=True)
    target_region_name_cn: Mapped[str | None] = mapped_column(String(256), nullable=True)
    target_region_name_en: Mapped[str | None] = mapped_column(String(256), nullable=True)
```

- [ ] **Step 2: Find the connection write path and add name population**

The connections are written in `llm_connection_extraction_service.py` around the `_connection_exists` check area. Find where `MirrorRegionConnection()` is constructed (search for `MirrorRegionConnection(` in the file). Add name lookups before construction:

```python
    # Build candidate lookup for name denormalization
    cand_name_map: dict[uuid.UUID, tuple[str | None, str | None]] = {
        c.id: (c.cn_name, c.en_name) for c in candidates
    }
```

Then when constructing each connection:

```python
    src_cn, src_en = cand_name_map.get(src_id, (None, None))
    tgt_cn, tgt_en = cand_name_map.get(tgt_id, (None, None))
    
    connection = MirrorRegionConnection(
        # ... existing fields ...
        source_region_name_cn=src_cn,
        source_region_name_en=src_en,
        target_region_name_cn=tgt_cn,
        target_region_name_en=tgt_en,
    )
```

- [ ] **Step 3: Update MirrorRegionConnectionCreate schema (if used)**

Check `backend/app/schemas/mirror_kg.py` for `MirrorRegionConnectionCreate` and add the 4 name fields as optional.

---

### Task 11: Wire candidate_pool_id into Composite Workflow

**Files:**
- Modify: `backend/app/schemas/llm_composite_workflow.py`
- Modify: `backend/app/services/llm_composite_workflow_service.py`

**Interfaces:**
- Adds: `candidate_pool_id` optional field to `CompositeWorkflowRunRequest`
- Modifies: `create_workflow_run` / `run_connection_with_function_workflow` to resolve pool

- [ ] **Step 1: Add field to schema**

In `backend/app/schemas/llm_composite_workflow.py`, in `CompositeWorkflowRunRequest`:

```python
    candidate_pool_id: uuid.UUID | None = Field(
        default=None,
        description="When set, resolve candidate_ids from this pool (overrides candidate_ids field)"
    )
```

- [ ] **Step 2: Resolve pool at workflow start**

In `backend/app/services/llm_composite_workflow_service.py`, in `create_workflow_run` (around line 859):

```python
    candidate_ids = list(request.candidate_ids)
    if request.candidate_pool_id:
        from app.services.candidate_pool_service import resolve_pool_candidate_ids
        candidate_ids = await resolve_pool_candidate_ids(session, request.candidate_pool_id)
        if len(candidate_ids) < 2:
            raise ValueError(f"Pool {request.candidate_pool_id} has fewer than 2 candidates")
```

---

### Task 12: Run Full Test Suite

- [ ] **Step 1: Run all backend tests**

```bash
cd backend && .venv/Scripts/python.exe -m pytest tests/ -q 2>&1
```
Expected: All 294+ tests pass. No regressions.

- [ ] **Step 2: Build frontend**

```bash
cd frontend && npm run build 2>&1
```
Expected: 0 TypeScript errors.

- [ ] **Step 3: Verify migrations apply cleanly**

```bash
psql -U postgres -d neurographiq_kg_v3_mvp1_e2e -f backend/migrations/035_candidate_pools.sql
psql -U postgres -d neurographiq_kg_v3_mvp1_e2e -f backend/migrations/036_mirror_connection_names.sql
```
Expected: No errors.

- [ ] **Step 4: Quick health check**

```bash
curl -s http://127.0.0.1:8002/api/health | python -m json.tool
curl -s http://127.0.0.1:8002/api/candidates/pools | python -m json.tool
```
Expected: health=ok, pools returns `{"items": [], "total": 0}`.

---

## Implementation Order

```
Phase A (deploy first, zero dependencies):
  Task 5 (A1: Conservatism) ──┐
  Task 6 (A3: Pathway Hints) ─┤ can run in parallel
  Task 7 (A2: Network Context)┘

Phase B (depends on migrations):
  Task 1 (Migration 035) ──┐
  Task 2 (Migration 036) ──┤ can run in parallel
                           │
  Task 3 (Models+Schemas) ←┘
  Task 4 (Service+Router)
  Task 8 (B2: Priority Ordering)
  Task 9 (B3: Concurrency+Pack Size)
  Task 10 (B4: Name Columns)
  Task 11 (Wire Pool into Workflow)

Verification:
  Task 12 (Full Test Suite)
```

---

## Spec Coverage Check

| Spec Section | Covered By |
|-------------|------------|
| A1: Adjust conservatism | Task 5 |
| A2: Inject network context | Task 7 |
| A3: Classical pathway hints | Task 6 |
| B1: Cross-batch candidate pool | Tasks 1, 3, 4 |
| B2: Smart pack ordering | Task 8 |
| B3: Concurrency + pack size | Task 9 |
| B4: Name columns | Tasks 2, 10 |
| Wire pool into workflow | Task 11 |
| Migration & rollback | Tasks 1, 2 |
