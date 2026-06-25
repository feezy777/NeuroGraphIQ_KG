# NeuroGraphIQ KG V3

脑图谱知识图谱项目 — MVP 1 确定性导入闭环 + Macro96 双链路 + LLM 候选侧提取已上线。

## 当前状态（2026-06-15）

| 组件 | 状态 |
|------|------|
| 架构 / Vibe Coding 指南 | ✅ `docs/NEUROGRAPHIQ_VIBE_CODING_GUIDE.md` |
| GPT 会话同步（**含 §0 实现快照**） | ✅ `docs/GPT_SESSION_SYNC.md` |
| 目标架构（Mirror KG / 同颗粒度 LLM） | ✅ `docs/NEUROGRAPHIQ_KG_V3_TARGET_ARCHITECTURE.md` 等 |
| MVP 1（Registry → Promotion → Final Query） | ✅ |
| Macro96（Excel → raw → candidate 96 行） | ✅ |
| Import Pipeline 工作区 + Rollback | ✅ |
| LLM Extraction（DeepSeek 候选侧字段补全） | ✅ |
| 工作台 UI（15 页） | ✅ `frontend/` |
| 正式库（物理） | **`NeuroGraphIQ_KG_V3`**（DBeaver）；Promotion 目标，当前 dev 写 E2E 库 |
| Mirror KG / connection / circuit / function LLM | ⏳ 仅文档规划 |

## 快速验证

### 后端

```powershell
.\scripts\start-backend.ps1
# → http://127.0.0.1:8002/api/health
# version: 3.3.0-mvp2-llm-extraction
```

### 前端

```powershell
cd frontend
npm run dev
# → http://localhost:5173
```

### 单元测试

```powershell
cd backend
.\.venv\Scripts\python.exe -m pytest tests/ -q
# 371 passed, 9 skipped（2026-06-15）
```

```powershell
cd frontend
npm run build
```

## 目录结构

```
NeuroGraphIQ_KG_V3_1/
├── docs/                    # 架构 + GPT 同步 + 目标设计
├── backend/
│   ├── app/routers/         # FastAPI 路由（MVP 1 + Macro96 + LLM + Pipeline）
│   ├── migrations/          # 001–020 DDL（手动执行）
│   └── tests/
├── frontend/src/pages/      # 15 个工作台页面
└── scripts/
```

## 重建 / 开发指引

1. 阅读 `docs/GPT_SESSION_SYNC.md` **§0 当前实现快照**。
2. 遵循 `docs/NEUROGRAPHIQ_VIBE_CODING_GUIDE.md` 写权限与 `final_*` 边界。
3. 正式库物理名：**`NeuroGraphIQ_KG_V3`**（schema 分粒度）；工作台 dev 常用 `neurographiq_kg_v3_mvp1_e2e`。
4. Macro96 权威池：`docs/MACRO_96_REGION_POOL.md`；与 AAL3 须经 explicit mapping（未实现）。

## 环境

- Python 3.11+、PostgreSQL（本地 5432）
- 当前阶段不使用 Docker 进行日常开发
- 数据库连接：`docs/dbeaver_postgres_connection.md`（如存在）
