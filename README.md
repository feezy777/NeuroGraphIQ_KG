# NeuroGraphIQ KG（工作台）

公开仓库：<https://github.com/feezy777/NeuroGraphIQ_KG>

本仓库为「脑区知识图谱」相关 **Web 工作台** 与管线骨架：导入与解析（Excel 优先）、统一中间表示、脑区 / 回路 / 连接等提取与审核流程、**DeepSeek / Kimi（Moonshot）/ 双模型** 与本地规则抽取、任务与版本管理。

- **更新日志（中文）**：[docs/CHANGELOG.md](docs/CHANGELOG.md)
- **同步与发布**： [docs/GITHUB_PUBLISH.md](docs/GITHUB_PUBLISH.md)

## 本阶段已落地
- IDE 风格主界面：顶部工具栏 / 左侧导航 / 中央工作区 / 右侧 Inspector / 底部日志
- 多中心 Tab：文件、标准化、校验、粒度治理、入库、配置、任务与日志；脑区提取与审核（**文件 / 文本 / DeepSeek 或 Kimi 直接生成**、**Kimi+DeepSeek 双模型抽取**、**Allen Brain Atlas RMA 直连拉取 Structure**、结果版本与候选同步）
- 后端模块：文件、解析、标准化、抽取、校验、粒度、入库、任务、配置等；脑区候选 **验证流水线** 与本体规则扩展
- 文件状态流与任务状态流；统一中间层（document / content chunk / candidate）
- staging / production 双路径占位
- **DeepSeek**：全局配置、弹窗内参数与 Prompt 预设/自定义、`deepseek_profiles` 个性化配置
- **Moonshot（Kimi）**：运行时配置（见 `configs/local/runtime.local.yaml.example` 中 `moonshot` 段），用于 Kimi 抽取、双模型与 Kimi 直接生成
- **三层颗粒度（major / sub / allen）**：固定层级与 Allen 约束、非脑区实体拦截、统一 LLM JSON schema；见 `scripts/modules/workbench/extraction/brain_region_granularity.py` 与 `docs/CHANGELOG.md`
- SQL 数据模型骨架（stage/prod schema + 核心表）

## 技术栈
- Backend: Python + Flask
- Frontend: 原生 HTML/CSS/JS（由 Flask 提供）
- Repository: 本地 JSON 状态仓（`artifacts/workbench/state.json`）
- SQL 骨架：`sql/schema/001_workbench_foundation.sql`

## 启动
```powershell
Set-Location -Path "D:\Tool\Coding\IDE\PyCharm\NeuroGraphIQ_KG_V2"
.\.venv\Scripts\Activate.ps1
pip install -r requirements.txt
python -m scripts.ui.run_dashboard
```
浏览器打开：`http://127.0.0.1:8899`

## 入口文件
- 后端主入口：`scripts/ui/dashboard.py`
- 启动入口：`scripts/ui/run_dashboard.py`
- 前端模板：`webapp/templates/index.html`
- 前端交互：`webapp/static/workbench/main.js`
- 前端样式：`webapp/static/styles.css`

## 后端模块结构
- `scripts/modules/workbench/files`
- `scripts/modules/workbench/parsing`
- `scripts/modules/workbench/normalization`
- `scripts/modules/workbench/extraction`
- `scripts/modules/workbench/validation`
- `scripts/modules/workbench/granularity`
- `scripts/modules/workbench/ingestion`
- `scripts/modules/workbench/tasks`
- `scripts/modules/workbench/config`
- 公共域模型与状态仓：`scripts/modules/workbench/common`

## 关键 API 骨架
- `GET /api/status`
- `GET /api/files/list`
- `POST /api/files/upload`
- `GET /api/files/<file_id>`
- `DELETE /api/files/<file_id>`
- `GET /api/files/<file_id>/parsed`
- `POST /api/files/<file_id>/reparse`
- `POST /api/files/<file_id>/renormalize`
- `POST /api/files/<file_id>/extract-regions`
- `POST /api/files/<file_id>/extract-regions-allen`（Allen Brain Atlas RMA，小鼠默认 `graph_id=1`）
- `POST /api/files/<file_id>/extract-circuits`
- `POST /api/files/<file_id>/extract-connections`
- `POST /api/files/<file_id>/validate`
- `POST /api/files/<file_id>/map`
- `POST /api/files/<file_id>/stage`
- `POST /api/files/<file_id>/commit`
- `GET /api/tasks/list`
- `GET /api/tasks/<task_id>`
- `GET /api/runs/<task_id>`
- `GET /api/logs`
- `GET/POST /api/config`
- `GET /api/config/effective-deepseek`
- `GET/POST/DELETE /api/config/deepseek-profiles`
- 脑区候选：`GET /api/files/<file_id>/region-candidates`、`POST /api/candidates/<id>/validation-run`、`POST /api/candidates/<id>/validation-pipeline` 等（详见 `scripts/ui/dashboard.py`）

## 说明
- 第一阶段大量使用 placeholder/mock 逻辑（解析、抽取、校验、入库均为可替换骨架）
- 本阶段目标是建立“可运行且可扩展”的边界与状态流，不是完成算法能力

## Neo4j Export (Region / Connection / Circuit)

### Environment Variables
Set Neo4j connection before write mode:

```powershell
$env:NEO4J_URI = "bolt://localhost:7687"
$env:NEO4J_USER = "neo4j"
$env:NEO4J_PASSWORD = "your_password"
$env:NEO4J_DATABASE = "neo4j"  # optional
```

### Run Export Script
Dry-run (count only, no Neo4j write):

```powershell
python -m scripts.db.export_to_neo4j --granularity all --dry-run
```

Write mode (idempotent MERGE sync):

```powershell
python -m scripts.db.export_to_neo4j --granularity all
```

You can limit scope with:
- `--granularity major`
- `--granularity sub`
- `--granularity allen`
- `--granularity all`

### Query File
Generated query set for brain region / connection / circuit analysis:

- `artifacts/neo4j/brain_connection_circuit_queries.cypher`
