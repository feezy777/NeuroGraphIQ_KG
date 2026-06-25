# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project Overview

**NeuroGraphIQ KG V3** — multi-granularity brain knowledge graph system. It ingests brain atlas resources (AAL3, Macro96, Brainnetome, HCP-MMP, etc.), runs deterministic parsing + LLM-assisted extraction, stages knowledge through a Mirror KG, and requires Human Review before Promotion to the Final KG.

- Backend: **FastAPI** (Python 3.11+, SQLAlchemy async, Pydantic v2, PostgreSQL via psycopg3 async)
- Frontend: **React 18 + Vite + TypeScript** (currently being rebuilt; see `frontend/README.md`)
- LLM: **DeepSeek** + **Kimi** via OpenAI-compatible SDK (`app/services/llm_providers/`)
- Database: **PostgreSQL** with schema-based granularity isolation; no Docker for dev

## Quick Start

### Backend

```powershell
# First time: create venv and install deps
cd backend
python -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r requirements.txt

# Copy and configure .env
cp .env.example .env
# Edit .env with your POSTGRES_* and LLM API keys

# Run
.\.venv\Scripts\python.exe run_server.py
# → http://127.0.0.1:8002/api/health
```

Or use the convenience script:

```powershell
.\scripts\start-backend.ps1
```

### Frontend

```powershell
cd frontend
npm install
npm run dev
# → http://localhost:5173
```

> **Note**: Old React workbench was deleted; currently being rebuilt. See `docs/GPT_SESSION_SYNC.md` and `docs/NEUROGRAPHIQ_VIBE_CODING_GUIDE.md` for architecture guidance.

### Backend Tests

```powershell
cd backend
.\.venv\Scripts\python.exe -m pytest tests/ -q
# Run a single test:
.\.venv\Scripts\python.exe -m pytest tests/test_import_batch_crud.py -q -k "test_name"
```

### Frontend Build

```powershell
cd frontend
npm run build
```

## Code Architecture (Big Picture)

### Data Governance Chain (Mandatory)

```
Raw Resource → Raw Parsing → Candidate Generation → Rule Validation
  → LLM Extraction → Mirror KG → Human Review → Promotion → Final KG
```

**Hard boundaries (must NOT cross):**
| Stage | May write | Must NOT write |
|-------|-----------|----------------|
| Raw Parsing | `raw_*`, `staging_*` | `final_*`, Mirror KG |
| Candidate Generation | `candidate_*` | `final_*` |
| LLM Extraction | Mirror KG items, `llm_extraction_*` | `final_*`, auto-approve, auto-promote |
| Human Review | Review records, mirror edit proposals | `final_*` (direct) |
| Promotion | `final_*` + audit | bypass review |

### Backend Structure (`backend/`)

```
backend/app/
├── main.py              — FastAPI entry, registers 30+ routers
├── config.py            — Settings (DB URLs, LLM keys, CORS)
├── database.py          — Async engine, runtime DB switching
├── models/              — SQLAlchemy models organized by domain:
│   ├── resource.py, resource_file.py        — Registry
│   ├── import_batch.py, raw_parsing.py       — Import pipeline
│   ├── candidate.py                          — Candidate DB
│   ├── rule_validation.py                    — Rule validation
│   ├── human_review.py                       — Human review
│   ├── llm_extraction.py, llm_field_completion.py  — LLM extraction
│   ├── mirror_kg.py, mirror_macro_clinical.py       — Mirror KG
│   ├── mirror_validation.py, mirror_review.py       — Mirror validation+review
│   ├── mirror_promotion.py, final_macro_clinical.py — Mirror+Final promotion
│   ├── final_kg.py                           — Final KG query
│   └── promotion.py                          — Legacy promotion
├── schemas/             — Pydantic request/response schemas
├── services/            — Business logic:
│   ├── import_batch_service.py               — Import lifecycle
│   ├── candidate_service.py                  — Candidate generation
│   ├── human_review_service.py               — Review queue
│   ├── llm_extraction_service.py             — LLM run management
│   ├── llm_field_completion_service.py        — Field completion
│   ├── llm_composite_workflow_service.py      — Multi-step LLM orchestration
│   ├── llm_connection_extraction_service.py   — Connection extraction
│   ├── llm_circuit_step_extraction_service.py — Circuit steps
│   ├── llm_circuit_projection_extraction_service.py
│   ├── llm_projection_function_extraction_service.py
│   ├── llm_to_mirror_service.py              — LLM item → Mirror KG
│   ├── llm_providers/                        — Provider abstraction:
│   │   ├── base.py, factory.py
│   │   ├── deepseek.py, kimi.py
│   ├── mirror_* (cross_validation, review, promotion, etc.)
│   ├── final_* (macro_clinical_browser, promotion, export, kg)
│   ├── database_admin_service.py             — Runtime DB switching
│   └── file_normalization_service.py         — File intermediate parsing
├── routers/             — API endpoints (one per domain)
├── parsers/             — Plugin-based file parsers:
│   ├── base_parser.py, registry.py
│   ├── aal3_parser.py, aal3_xml.py
│   ├── brainnetome_parser.py, allen_parser.py
│   ├── hcp_mmp_parser.py, freesurfer_parser.py
│   ├── siibra_parser.py, terminology_parser.py
│   └── macro96_xlsx.py
└── utils/               — llm_client.py, semantic_id.py, hash_utils.py
```

### Frontend Structure (`frontend/`)

```
frontend/src/
├── pages/               — One page per pipeline stage:
│   ├── ResourcesPage, FilesPage
│   ├── ImportBatchesPage, RawAal3Page, RawMacro96Page
│   ├── CandidatesPage, RuleValidationPage
│   ├── LlmExtractionPage, HumanReviewPage
│   ├── PromotionsPage, FinalRegionsPage
│   ├── SettingsPage, DashboardPage, ImportPipelinePage
│   └── data-center/, importPipeline/, llm-extraction/ (sub-UI modules)
├── components/          — Reusable: DataTable, StatusBadge, KeyValuePanel, etc.
├── hooks/               — useData generic fetcher, useSessionIds
├── api/                 — Axios wrapper
└── contexts/            — WorkbenchContext (granularity/source scope)
```

### Database Migrations (`backend/migrations/`)

Hand-written SQL files numbered sequentially (001–033+). Not Alembic-driven.
- `init_schema.sql` — core schema (registry, tasks, staging, knowledge)
- `20260520_coarse_grain_schema.sql` — coarse grain expansion
- Files 009+ cover LLM extraction, Mirror KG, validation/review/promotion

### Granularity System

Brain regions live in separate schemas by granularity family:
| Schema | Granularity | Resources |
|--------|-------------|-----------|
| `macro_clinical` | Macro | AAL3, Macro96 pool |
| `meso_anatomical` | Meso | HCP-MMP, Desikan |
| `sub_connectivity` | Subregion | Brainnetome |
| `fine_cyto` | Cytoarchitectonic | Julich-Brain (siibra) |
| `molecular_attr` | Molecular | Allen Human Brain Atlas |

Cross-granularity mapping uses explicit `mapping_type` (`exact_match`, `part_of`, `overlaps`, etc.) — never implicit name merge.

### Key API Prefixes

| Prefix | Module |
|--------|--------|
| `/api/resources` | Resource Registry |
| `/api/files` | File Upload |
| `/api/import-batches` | Import Batches (task lifecycle) |
| `/api/raw-parsing` | Raw Parsing |
| `/api/candidates` | Candidate DB |
| `/api/rule-validation` | Rule Validation |
| `/api/human-review` | Human Review |
| `/api/promotion` | Promotion |
| `/api/final-regions` | Final DB Query |
| `/api/llm-extraction` | LLM Extraction + Composite Workflow |
| `/api/mirror-kg` | Mirror KG (schema, validation, review, promotion, cross-validation, dual-model) |
| `/api/final-kg` | Final KG |
| `/api/final-macro-clinical` | Final Macro Clinical (browser, promotion, export) |
| `/api/settings` | LLM & system settings |
| `/api/database` | Database admin (runtime DB switch) |
| `/api/workbench` | Workbench pipeline aggregation |

## Critical Development Constraints

1. **`final_*` is the current main path for approved data** — `kg_*` is legacy only. New features must NOT default to writing `kg_*`.
2. **LLM output must never write `final_*` directly** — all LLM output goes to `llm_extraction_*` → Mirror KG → Human Review → Promotion.
3. **LLM calls must be provider-abstracted** via `llm_providers/factory.py`. Tests must mock providers.
4. **Different granularities must NOT be merged** — macro, meso, micro, molecular, term are independently isolated.
5. **Each Import Batch is the core tracking unit** — `import_tasks.id` = batch_id for provenance.
6. **Always read relevant router + service + model + migration before modifying** — never assume table names or API paths.
7. **New fields require a migration SQL file** — no Alembic; hand-written numbered SQL in `backend/migrations/`.
8. **The old React workbench was deleted** — frontend is being rebuilt from scratch per architecture docs in `docs/`.
9. **写入时合并原则** — Mirror KG 写入时，相同 canonical key 的数据自动合并（取高 confidence），保留双溯源。详见 `docs/MIRROR_KG_DEDUP_MERGE_PRINCIPLE.md`。

## Superpowers Skills (Installed)

The project has [Superpowers](https://github.com/obra/superpowers) methodology skills installed in `.claude/skills/`. Key skills for project design & planning:

| Skill | File | Purpose |
|-------|------|---------|
| **Brainstorming** | `.claude/skills/brainstorming/SKILL.md` | Design refinement before coding — ask clarifying questions, explore alternatives, present designs in digestible sections, save spec document |
| **Writing Plans** | `.claude/skills/writing-plans/SKILL.md` | Break approved design into bite-size tasks (2-5 min each) with exact file paths, complete code, and verification steps |
| **Executing Plans** | `.claude/skills/executing-plans/SKILL.md` | Execute tasks in batches with human checkpoints, using TDD and subagents |
| **Subagent-Driven Development** | `.claude/skills/subagent-driven-development/SKILL.md` | Dispatch fresh subagents per task with two-stage review (spec compliance, then code quality) |

**To use brainstorming for project planning:**
1. In Claude Code CLI, type `/brainstorming` to start a design discussion
2. Or ask Claude to "use the brainstorming skill" to refine requirements and architecture before coding

---

## Current Session State (2026-06-24)

### Recent Completed Changes

| Area | Change | Files |
|------|--------|-------|
| **LLM Extraction** | Added "字段补全" Tab (连接/回路/Bundle 补全) | `FieldCompletionTab.tsx`, `ModelSelector.tsx`, `ProgressPanel.tsx`, `llmDataFirstTypes.ts` |
| **LLM Extraction** | Added quick extraction cards (脑区功能/连接+功能/回路+步骤+功能) — 选中候选后显示，一键触发 | `LlmExtractionPage.tsx` + CSS |
| **LLM Extraction** | Provider/Model 切换联动修复 — 切换 Provider 自动重置 Model 为默认值 | `LlmExtractionPage.tsx` |
| **LLM Extraction** | Duplicate chips removed from toolbar — 快速卡片与工具栏不再重复 | `LlmTaskToolbar.tsx` |
| **LLM Models** | Added `deepseek-v4-pro` (旗舰), `deepseek-chat` (V3), `deepseek-reasoner` (R1) presets | `ModelSelector.tsx` |
| **Batch Management** | Merged Import Pipeline into ImportBatchesPage — 新增「导入流程」Tab，时间线截断到 Candidate 生成 | `ImportBatchesPage.tsx`, `ImportPipelinePage.tsx` |
| **Navigation** | Removed Import Pipeline from sidebar, moved Data Center under LLM Extraction | `WorkbenchLayout.tsx` |
| **Navigation** | Removed "正式脑区" page from sidebar | `WorkbenchLayout.tsx`, `App.tsx` |
| **Data Center** | Redesigned Overview — 水平流水线卡片 (Raw→Candidate→Mirror→Final) + 需要关注 + 快速入口 | `DataCenterOverview.tsx` + CSS |
| **Data Center** | Raw/Candidate 面板恢复真实数据展示 (从 stub 恢复) | `RawAal3Page.tsx`, `RawMacro96Page.tsx`, `CandidatesPage.tsx` |
| **Data Center** | Mirror KG 面板新增批量删除、行选择高亮、浮动操作栏 | `MirrorKgPanel.tsx`, `FormalObjectTableSection.tsx`, `FormalObjectDetailDrawer.tsx` |
| **Data Center** | 全局风格统一: 医学蓝配色, 斑马纹表格, 卡片式 Tab, 新按钮/徽章系统 | `styles.css` |
| **Backend** | Write-time dedup & merge for Mirror KG connections (Phase 1) | `mirror_kg_service.py` |
| **Backend** | Pause composite workflow (`POST .../pause`) | `llm_composite_workflow_service.py`, `router` |
| **Backend** | PATCH/DELETE endpoints for mirror connections/functions/circuits | `mirror_kg.py`, `mirror_kg_service.py` |
| **Docs** | `FINAL_KG_TRIPLE_GRAPH_DESIGN.md` — 图谱模型设计 | New file |
| **Docs** | `MIRROR_KG_DEDUP_MERGE_PRINCIPLE.md` — 去重合并原则 | New file |
| **Frontend build** | `npm run build` passes with 0 TypeScript errors | — |
| **Backend tests** | 294+ tests passing | — |
| **A1: Mirror Rule Validation 页面** | 在 RuleValidationPage 增加 Mirror KG validation Tab | `RuleValidationPage.tsx`, `MirrorValidationTab.tsx`, `i18n.ts` |

### Current Running Services

| Service | URL | Status |
|---------|-----|--------|
| Frontend | http://localhost:5173 | ✅ dev server |
| Backend | http://127.0.0.1:8002 | ✅ FastAPI v4.7.0 |

### Current Sidebar Navigation Order

```
仪表盘 → 资源登记 → 文件管理 → 批次管理 → LLM 提取 → 数据中心
→ Mirror KG 浏览 → 规则校验 → 人工审核 → 晋升记录 → 设置
```

---

## Next Steps Roadmap (待实现)

### Phase A: Mirror KG → Final KG Full Pipeline (前端串联)

| Step | Task | Details | Depends On |
|------|------|---------|------------|
| A1 | **Mirror Rule Validation 页面** | 在 RuleValidationPage 增加 Mirror KG validation Tab | — |
| A2 | **Mirror Review 页面** | 改造 HumanReviewPage 支持 Mirror KG 对象审核 | — |
| A3 | **Mirror → Final Promotion** | 改造 PromotionsPage 增加 Mirror → Final 晋升，强确认机制 | A2 |
| A4 | **Final KG Browser (图谱探索)** | React Flow / xyflow 图可视化，节点展开/收起，功能聚合 | A3 |
| A5 | **Triple Consolidation 触发** | 在 Promotion 完成后自动触发 Triple consolidation | A3 |
| A6 | **Mirror KG 补全增强** | 连接/回路/回路 Bundle 的 LLM 字段补全（使用 `UniversalFieldCompletionService`） | — |

### Phase B: Extraction Stability & UX

| Step | Task | Details |
|------|------|---------|
| B1 | **进度面板集成** | 将 `ProgressPanel` 接入复合工作流，显示实时进度/暂停/取消 |
| B2 | **暂停/恢复完整链路** | 前端 pause/resume 按钮 + 后端 resume 端点实现 |
| B3 | **每包配对数可调** | 在 Advanced 面板中增加 pairs_per_pack 滑块 (默认20) |
| B4 | **温度/top_p 参数** | 高级选项可展开显示 temperature / top_p 等 |
| B5 | **Dry run 预览增强** | 执行前显示预估包数、token 量、费用估算 |

### Phase C: 用户体验优化

| Step | Task | Details |
|------|------|---------|
| C1 | **提取结果一键跳转** | 提取完成后直接跳转到 Data Center → Mirror KG 查看结果 |
| C2 | **任务历史列表** | 在 LLM Extraction 页面显示历史运行记录，可重新运行 |
| C3 | **数据看板** | 在 Dashboard 页面展示关键指标 (总连接数、待审核数、晋升数) |
| C4 | **批量补全进度** | Field Completion 多选补全时显示进度 |

### Phase D: 核心治理链路

| Step | Task | Details |
|------|------|---------|
| D1 | **写入时合并 Phase 2** | Mirror functions + circuits 去重合并 |
| D2 | **写入时合并 Phase 3** | Mirror circuit_functions 去重合并 |
| D3 | **双模型验证入口** | 在 LLM Extraction 页面或 Macro Clinical Tab 中集成 Dual Model Verification |

### Key Architecture Documents

- `docs/NEUROGRAPHIQ_KG_V3_TARGET_ARCHITECTURE.md` — 目标架构
- `docs/NEUROGRAPHIQ_VIBE_CODING_GUIDE.md` — Vibe Coding 指南（核心约束 3000+ 行）
- `docs/FINAL_KG_TRIPLE_GRAPH_DESIGN.md` — 三元组图谱模型（脑区→连接→功能→回路→三元组）
- `docs/MIRROR_KG_DEDUP_MERGE_PRINCIPLE.md` — 写入时合并原则
- `docs/MACRO_96_REGION_POOL.md` — 96 脑区标准池规范
