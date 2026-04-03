# NeuroKG 项目（V2 + V2.1 + Desktop V3）

## 项目简介
NeuroKG 是一个面向脑区知识图谱构建的工程，核心能力包括：
- 本体约束（RDF/OWL + YAML 映射）；
- 基于 DeepSeek 的辅助抽取与粗检验；
- 使用语义文本 ID 的 PostgreSQL 入库流程。

当前数据库采用“按颗粒度分层分表”策略：
- `major_*`
- `sub_*`
- `allen_*`

该方案查询复杂度更高，但层级隔离更强，符合当前阶段需求。

## 主流程
`major` 主链路为：
`anatomy -> major_regions -> major_circuits -> major_connections -> validate -> gate -> export -> load`

V2 中回路生成升级为三层结构：
1. `family_recall`
2. `instance_build`
3. `connection_decompose`

V2.1 文件处理链路为：
`upload -> normalize -> deepseek validation -> auto low-risk fix -> file preview -> extraction`

## 数据流
`data/raw -> data/staging -> data/validated|data/rejected -> data/exports`

工作台运行产物目录：
`artifacts/ui_runs/<run_id>/...`

## 本体门禁（入库前）
在 `Load To DB` 前会执行本体门禁：
- **Core BLOCK**：非法类/关系映射、枚举非法、关键外键不可映射、非法 `relation_type`；
- **Extended WARN**：压缩表达、关键中继节点缺失、证据不足等。

报告输出：
- `exports/reports/ontology_gate_report.json`

门禁阻断时禁止入库。

## SQL 结构
主要 Schema 文件：
- `sql/schema/001_create_schema.sql`
- `sql/schema/002_create_tables_anatomy.sql`
- `sql/schema/003_create_tables_region.sql`
- `sql/schema/004_create_tables_connection.sql`
- `sql/schema/005_create_tables_circuit.sql`
- `sql/schema/006_create_tables_evidence.sql`
- `sql/schema/007_create_tables_relation.sql`
- `sql/schema/008_create_tables_extension.sql`
- `sql/schema/009_create_indexes.sql`
- `sql/schema/010_create_triggers.sql`

其中 `major_connection` 含字段：
- `relation_type`（`direct_structural_connection | indirect_pathway_connection | same_circuit_member`）

## 语义 ID 约定
全库采用语义文本 ID，例如：
- `ORG_HUMAN`
- `SYS_NERVOUS`
- `ORGN_HUMAN_BRAIN`
- `DIV_NON_LOBE_DIVISION_BRAIN`
- `REG_MAJOR_*`
- `CONN_MAJOR_*`
- `CIR_MAJOR_*`
- `EVID_DS_*`

## 本地工作台
### Desktop V3（推荐）
启动命令：
```powershell
.\start_desktop.bat
```
或
```powershell
python -m scripts.desktop.run_desktop
```

Desktop V3 主流程：
`Import Ontology(必需) -> Import Files -> Auto Preprocess Queue(DeepSeek) -> Preview -> Fine Process Router(占位)`

门禁规则：
- 未导入本体：阻断预处理/预览；
- 本体导入失败：阻断预处理/预览。

V1 支持的本体格式：
- `.rdf`、`.owl`、`.xml`（RDF/XML + OWL XML）

V1 支持的文件类型：
- 结构化：`xlsx/csv/tsv/json/jsonl`
- 文本/文档：`txt/md/pdf/docx`
- 本体相关：`rdf/owl/xml`

桌面快捷方式脚本：
```powershell
powershell -ExecutionPolicy Bypass -File .\create_desktop_shortcut_v3.ps1
```

### Web 工作台（仍可用）
启动命令：
```powershell
.\start_workbench.bat
```
或
```powershell
python -m scripts.ui.run_dashboard
```

访问地址：
`http://127.0.0.1:8899`

## 工作台说明
- `Crawler` 模块在 V2.1 为 deferred 状态（不执行真实爬取）；
- `File Preview` 支持多格式分页与按需加载；
- PDF/DOCX 优先原始嵌入，失败时回退解析文本；
- 非结构化输入会阻断 `Start Extraction`；
- 当前 `major` 执行输入为 `.xlsx`，其他结构化格式已支持预览/检验但暂未接入 `major` 执行链路。

## 重建数据库
更新 SQL 后执行：
```powershell
python -m scripts.pipeline.rebuild_schema
```

执行顺序：
1. `drop schema neurokg cascade`
2. `sql/schema/001~010`
3. `sql/seeds/001~002`

## 下一步规划
- 将 V2 回路框架扩展到 `sub`、`allen`；
- 增强本体推理规则（超出当前硬门禁）；
- 补齐非 drop 模式迁移脚本；
- 增加端到端回归数据与运行时/成本监控。
