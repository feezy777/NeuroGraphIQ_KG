# NeuroGraphIQ KG V3

多粒度脑知识图谱系统——摄入脑图谱资源（AAL3、Macro96），通过确定性解析 + LLM 辅助提取，经 Mirror KG 暂存，人工审核后晋升至 Final KG。

**当前版本**: 4.7.0-mvp2-composite-workflow-stabilization

## 快速启动

### 后端

```powershell
cd backend
.\.venv\Scripts\python.exe run_server.py
# → http://127.0.0.1:8002/api/health
```

### 前端

```powershell
cd frontend
npm run dev
# → http://localhost:5173
```

## 核心功能

### LLM 提取管线

| 功能 | 入口 | 模型建议 | 说明 |
|------|------|---------|------|
| **脑区提取连接** | 脑区 Tab → 设为提取池 → 连接+功能提取 | deepseek-chat | 基于脑区对推断连接/投射候选 |
| **脑区提取回路** | 脑区 Tab → 回路+步骤+功能 | deepseek-v4-pro | 基于脑区识别多跳回路+步骤+功能 |
| **连接提取回路** | 连接 Tab → 勾选连接 → 回路+步骤+功能 | deepseek-chat / v4-pro | 基于已知连接图推断回路 |
| **AI 字段补全** | 数据中心 → 勾选 → AI 补全 | deepseek-chat | 连接 12 字段 / 回路 11 字段独立补全 |

### 数据治理链

```
Raw Resource → Raw Parsing → Candidate Generation → LLM Extraction
  → Mirror KG → Human Review → Promotion → Final KG
```

**硬边界**: LLM 输出只能写 Mirror KG，**禁止**直接写 final_* / kg_*

### AI 字段补全

- 按连接执行：1 次 LLM 调用补全 12 个字段
- 覆盖策略：仅填空值 / 覆盖写入 / 仅建议
- 实时进度条 + 已跳过/已更新统计
- 支持 5000+ 连接批量补全

### 写入时去重

- 连接: `(source, target, type, direction)` 唯一索引
- 回路: `circuit_name` 唯一索引
- 冲突自动合并：高 confidence 覆盖，保留双重溯源

## LLM 配置

| 模型 | 超时 | 用途 |
|------|------|------|
| deepseek-chat (V3) | 120s | 连接提取、字段补全 |
| deepseek-v4-pro | 180s | 回路提取（推理增强） |
| deepseek-reasoner (R1) | 180s | 复杂推理 |

## 数据中心（当前状态）

| 实体 | 数量 | 说明 |
|------|------|------|
| 候选脑区 | 192 | Macro96 |
| 连接 | 4,307 | 唯一 (source, target) |
| 回路 | 292 | 英文命名 |

## 技术栈

- **后端**: FastAPI + SQLAlchemy Async + PostgreSQL + psycopg3
- **前端**: React 18 + Vite + TypeScript
- **LLM**: DeepSeek (V3/V4-Pro) + Kimi，OpenAI 兼容 SDK

## 项目结构

```
├── backend/
│   ├── app/
│   │   ├── models/           # SQLAlchemy ORM
│   │   ├── schemas/          # Pydantic 请求/响应
│   │   ├── services/         # 业务逻辑
│   │   │   ├── llm_providers/  # DeepSeek/Kimi 适配
│   │   │   ├── field_completion_*.py  # AI 字段补全
│   │   │   └── llm_circuit_pack_service.py  # 回路提取
│   │   ├── routers/          # API 路由
│   │   └── parsers/          # 脑图谱解析器插件
│   └── migrations/           # 手写 SQL 迁移
├── frontend/src/
│   ├── pages/
│   │   ├── data-center/      # 数据中心（表格、AI 补全弹窗）
│   │   └── llm-extraction/   # LLM 提取页（向导、进度）
│   └── components/           # 通用组件
├── docs/                     # 架构文档 + 设计 spec
└── .claude/plans/            # 实现计划
```

## 环境

- Python 3.11+ / PostgreSQL 127.0.0.1:5432
- 开发库: `neurographiq_kg_v3_mvp1_e2e`
- 正式库: `NeuroGraphIQ_KG_V3`
- 无 Docker（本地开发）

## License

MIT
