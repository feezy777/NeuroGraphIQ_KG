# NeuroGraphIQ KG - 第一阶段基础工具台骨架

本仓库当前实现了“知识图谱基础工具台”第一阶段框架，重点是骨架与边界，不是完整业务算法。

## 本阶段已落地
- IDE 风格主界面：顶部工具栏 / 左侧导航 / 中央工作区 / 右侧 Inspector / 底部日志
- 7 个核心中心页（Tab）：文件中心、标准化中心、校验中心、粒度治理中心、入库中心、配置中心、任务与日志中心
- 9 个后端模块边界（文件、解析、标准化、抽取、校验、粒度、入库、任务、配置）
- 文件状态流骨架与任务状态流骨架
- 统一中间层三层结构（document/content chunk/candidate knowledge unit）
- staging / production 双路径占位
- DeepSeek 全局配置 + 任务覆盖配置占位
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
- `POST /api/files/<file_id>/reparse`
- `POST /api/files/<file_id>/extract`
- `POST /api/files/<file_id>/validate`
- `POST /api/files/<file_id>/map`
- `POST /api/files/<file_id>/stage`
- `POST /api/files/<file_id>/commit`
- `GET /api/tasks/list`
- `GET /api/tasks/<task_id>`
- `GET /api/logs`
- `GET/POST /api/config`

## 说明
- 第一阶段大量使用 placeholder/mock 逻辑（解析、抽取、校验、入库均为可替换骨架）
- 本阶段目标是建立“可运行且可扩展”的边界与状态流，不是完成算法能力
