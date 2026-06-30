---
name: neurographiq-kg-v3-overview
description: Project overview, stack, key paths, running services, and governance chain
metadata:
  type: project
---

# NeuroGraphIQ KG V3 — Project Overview

Multi-granularity brain knowledge graph system. Ingest brain atlas resources → deterministic parsing + LLM extraction → Mirror KG → Human Review → Promotion → Final KG.

## Stack
- Backend: FastAPI (Python 3.11+, SQLAlchemy async, Pydantic v2, PostgreSQL/psycopg3 async)
- Frontend: React 18 + Vite + TypeScript
- LLM: DeepSeek + Kimi via OpenAI-compatible SDK
- DB: PostgreSQL at 127.0.0.1:5432, database `neurographiq_kg_v3_mvp1_e2e`, user/pass `postgres/postgres`

## Running Services
- Backend: `http://127.0.0.1:8002` — start with `cd backend && .venv/Scripts/python.exe run_server.py`
- Frontend: `http://localhost:5173` — start with `cd frontend && npm run dev`

## Governance Chain (MANDATORY)
Raw Resource → Raw Parsing → Candidate Generation → Rule Validation → LLM Extraction → Mirror KG → Human Review → Promotion → Final KG. LLM output NEVER writes final_* directly. Mirror KG is candidate staging layer.

## Key Paths
- Backend code: `backend/app/`
- Models: `backend/app/models/`
- Services: `backend/app/services/`
- Routers: `backend/app/routers/`
- Migrations: `backend/migrations/` (hand-written SQL, numbered 001-036)
- Frontend pages: `frontend/src/pages/`
- LLM extraction components: `frontend/src/pages/llm-extraction/components/`
- Specs: `docs/superpowers/specs/`
- Plans: `docs/superpowers/plans/`

**Why:** Core reference for any work on this project.
**How to apply:** Read before starting any task on this codebase.
