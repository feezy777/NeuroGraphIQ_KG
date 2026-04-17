# 更新日志

本文档记录 NeuroGraphIQ KG 工作台仓库的主要变更（中文）。详细代码以 Git 提交为准。

---

## [未发布] 2026-04

### 脑区抽取与生成

- **文件 / 文本抽取模式**：在「本地规则」「DeepSeek」之外，新增 **Kimi（Moonshot）** 与 **Kimi + DeepSeek（双模型）**。双模型先跑 Kimi 再跑 DeepSeek，同名（英|中）以 DeepSeek 结果为准合并。
- **直接生成**：方式③ 拆分为 **DeepSeek 直接生成**（弹窗配置）与 **Kimi 直接生成**（使用设置页中的 Moonshot 密钥与模型，请求参数 `provider: kimi`）。
- **抽取服务**：`run_region_extraction` 支持 `kimi` / `multi`，传入 `moonshot_cfg`；`_extract_by_deepseek` 参数化日志前缀与错误前缀，便于 Kimi 与 DeepSeek 共用分批逻辑；新增 `run_direct_llm_regions` 统一直接生成入口。
- **Region V2 管线**：与「仅大模型分批抽取」路径区分，避免 v2 本地路径与 DeepSeek/Kimi/双模型冲突。

### 配置与运行时

- **`runtime.local.yaml.example`**：增加 **moonshot**（Kimi）块：enabled、api_key、base_url、model、temperature。
- **本体规则（pipeline.ontology_rules）**：示例中补充 **bind_on_extract**、**require_binding_for_confirmed** 说明（抽取阶段写入 `review_note.ontology_binding`，严格模式下无 `term_key` 时不允许 confirmed）。
- **说明**：请勿将含真实密钥的 `configs/local/runtime.local.yaml` 提交到公开仓库；请复制 `.example` 为本地文件并自行填写。

### 工作台服务与 API

- **脑区候选**：验证流水线、批量验证、`validation-run`（local / deepseek / multi 等）、版本与候选同步等能力扩展（见 `workbench_service.py`、`dashboard.py`）。
- **本体校验**：`ontology_rules` 与候选校验逻辑增强。
- **入库**：`ingestion_service` 等与颗粒度、未验证库相关的校验与写入扩展。
- **新增模块**：`validation/candidate_validation.py`（候选多模型校验等）。

### 前端（Web 工作台）

- **脑区中心**：抽取下拉选项、直接生成双按钮、方法徽章与筛选（含 kimi、direct_kimi 等）、样式（含 Kimi / 双模型 badge）。
- **审核 / 验证**：交互与表格展示更新（与后端验证 API 对齐）。

### 公共与状态

- **id_utils / state_store**：ID 生成与状态持久化调整，以支持新功能。

---

## 历史版本

更早的提交若未在此列出，请使用 `git log --oneline` 查看。
