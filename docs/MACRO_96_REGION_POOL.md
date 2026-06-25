# 宏观 96 脑区标准池 — 数据源与解析规范

> **用途**：定义宏观临床层（`macro` / `macro_clinical`）的 **96 区标准池** 权威来源、字段语义、与 AAL3 全量解析的关系，以及工作台 Excel 解析能力需求。  
> **权威架构**：`docs/NEUROGRAPHIQ_VIBE_CODING_GUIDE.md`  
> **会话同步**：`docs/GPT_SESSION_SYNC.md`

---

## 1. 决策摘要

| 项 | 约定 |
|----|------|
| **96 区标准池权威来源** | `Brain volume list.xlsx`（福耀实习文档） |
| **池规模** | **96 条**（`ID #` = 1 … 96），**不是** AAL3 XML 的 `label_index 1–96` 简单过滤 |
| **AAL3 全量解析** | 保留独立链路（约 166 ROI），用于 atlas label 候选与后续 mapping |
| **96 池与 AAL3 关系** | 96 池是 **临床标准参照系**；AAL3 label → 96 池的对应须经 **显式 mapping**（禁止同名自动合并） |
| **工作台** | 需具备 **Excel（`.xlsx`）解析** 能力，用于导入/刷新标准池 |

---

## 2. 权威源文件

### 2.1 当前提供路径（用户指定）

```
d:\Fuyao\福耀实习\文档\excel\Brain volume list.xlsx
```

### 2.2 建议项目内引用路径（实现阶段复制或软链）

```
backend/data/reference/macro_96/Brain volume list.xlsx
```

> 实现时可将权威 xlsx 复制到仓库 `data/reference/`，便于 CI 与离线校验；**不**把 xlsx 当作 migration 自动执行的一部分。

### 2.3 文件结构（已核对，2026-06-08）

| 属性 | 值 |
|------|-----|
| 工作表 | `Sheet1`（单表） |
| 总行数 | 97（1 行表头 + **96 行数据**） |
| 编码 | UTF-8 单元格文本（含中文列名与中文脑区名） |

### 2.4 列定义

| 列序 | 表头（xlsx） | 建议内部字段 | 类型 | 说明 |
|------|--------------|--------------|------|------|
| A | `ID #` | `pool_index` | int | 标准池序号，**1–96，唯一** |
| B | `Brain Structure` | `en_name` | string | 英文解剖名（含 laterality 语义，如 `left caudate`） |
| C | `脑区中文名称` | `cn_name` | string | 中文脑区名 |

### 2.5 数据样例

| pool_index | en_name | cn_name |
|------------|---------|---------|
| 1 | white matter | 脑白质 |
| 2 | left lateral ventricle | 左侧脑室 |
| 6 | left thalamus proper | 左丘脑本体 |
| 92 | right superior parietal | 右上顶叶 |
| 96 | right insula | 右脑岛 |

---

## 3. 与 AAL3 全量解析的边界

```text
Brain volume list.xlsx (96 标准池)
    ↑ 显式 mapping（后续模块，非本步）
AAL3 XML 全量解析 (~166 ROI) → raw_aal3_region_labels → candidate_brain_regions
```

| 概念 | 96 标准池 | AAL3 全量 |
|------|-----------|-----------|
| 条目数 | **96** | **~166**（依 XML 版本） |
| 主键 | `pool_index` 1–96 | `label_index` + laterality + atlas |
| 来源 | Excel 权威表 | Atlas XML label 字典 |
| 当前 MVP 状态 | ✅ raw + candidate 已通（`parse-macro96` → 96 行 → `generate-macro96-candidates`） | ✅ raw + candidate 已通 |
| 错误做法 | 用 `label_index <= 96` 代替标准池 | 把 166 条直接当作 96 池 |

实测：对项目内完整 AAL3 XML 做 `label_index 1–96` 过滤仅得 **92** 条，与 Excel 96 池 **不一致**，进一步证明必须使用独立标准池文件，不能靠 index 区间替代。

---

## 4. 工作台 Excel 解析能力（✅ 已实现核心链路）

> 实现快照见 `docs/GPT_SESSION_SYNC.md` §0.5；本节保留原始需求描述供对照。

### 4.1 目标

工作台（重建后）与后端需支持用户上传 **`.xlsx`** 作为宏观 96 区标准池来源（或更新版本），流程与现有 File Upload 模块对齐。

### 4.2 用户场景

1. **首次建池**：上传 `Brain volume list.xlsx` → 解析 96 行 → 写入候选/标准池表（**非 `final_*`**，经审核与 promotion 后方可入正式库）。
2. **版本更新**：上传新版 xlsx → 生成新 import batch / 解析 run → 与旧池 diff（后续）。
3. **只读校验**：上传后预览解析结果（96 行、缺列、重复 ID、空名）再确认写入。

### 4.3 解析规则（MVP 建议）

| 规则 | 要求 |
|------|------|
| 格式 | `.xlsx`（首版）；`.xls` 可列为后续 |
| 工作表 | 默认 `Sheet1`；可通过 API 参数指定 sheet 名 |
| 表头 | 必须含三列：`ID #`、`Brain Structure`、`脑区中文名称`（允许别名映射，见下） |
| 数据行 | 恰好 **96** 行有效数据；`pool_index` 1–96 各出现一次 |
| 空值 | `pool_index` / `en_name` 不得为空；`cn_name` 允许空但记 warning |
| Laterality | 从 `en_name` 推断（`left`/`right` 前缀等），**不**在 96 池中合并左右为一条 |
| 输出 | 标准化记录 + `raw_payload`（原始行 JSON）保留溯源 |

### 4.4 建议表头别名（解析器兼容）

```text
pool_index  ←  ID # | id | index | pool_id
en_name     ←  Brain Structure | brain_structure | name_en
cn_name     ←  脑区中文名称 | cn_name | name_cn | 中文名称
```

### 4.5 后端模块归属（规划）

| 阶段 | 模块 | 写入目标 |
|------|------|----------|
| 文件登记 | File Upload（已有） | `resource_files`，`file_type=label_table` 或新增 `standard_pool` |
| 解析 | **新增** Excel Standard Pool Parser | 候选侧表（如 `candidate_macro_96_regions` 或统一 candidate 扩展） |
| 校验 | Rule Validation（MVP 1 步 6+） | 96 行完整性、ID 唯一、命名规范 |
| 审核 / 晋级 | Human Review → Promotion | `final_*`（仅 promotion 写） |

**禁止**：Excel 解析结果直接写 `final_*` / `kg_*`；禁止与 AAL3 candidate 自动按名称合并。

### 4.6 建议 API（规划，未实现）

```text
POST /api/resources/{resource_id}/files          # 上传 xlsx（已有）
POST /api/import-batches/{batch_id}/parse-macro-96-pool   # 解析 Excel → 标准池候选
GET  /api/macro-96-pool/regions                  # 列表（pool_index / en / cn / laterality）
GET  /api/macro-96-pool/regions/{pool_index}     # 单条详情
GET  /api/macro-96-pool/options                  # 枚举
```

### 4.7 前端工作台（规划）

| 页面 | 能力 |
|------|------|
| 文件中心 | 上传 `.xlsx`，标记 `file_role=standard_pool` 或 `label_dictionary` |
| 导入任务 | 创建 batch，绑定 xlsx，触发 `parse-macro-96-pool` |
| 解析结果 | 展示 96 行预览表（ID / 英文名 / 中文名 / 推断 laterality） |
| 候选浏览 | 按 `source=macro_96_pool` 过滤 |

---

## 5. 技术依赖

| 依赖 | 用途 | 状态 |
|------|------|------|
| `openpyxl` | 读取 `.xlsx` | 本地 venv 已可安装；**尚未**写入 `requirements.txt` |
| `pandas` | 可选，便于表清洗 | 项目已有 |

实现 Excel 解析模块时，将 `openpyxl` 加入 `backend/requirements.txt`。

---

## 6. 状态机与写权限（不变）

- 96 池记录创建后初始候选状态：`candidate_created`（与 `candidate_brain_regions` 一致，见 §5.2 Candidate 状态机）。
- `candidate_created` ≠ `manual_approved` ≠ 正式入库。
- Agent/Parser **只写 candidate 侧**；promotion 模块独占 `final_*` 写入。

---

## 7. 验收标准（实现 96 池 + Excel 解析时）

- [ ] 解析 `Brain volume list.xlsx` 得到 **恰好 96** 条，`pool_index` 1–96 无缺失无重复
- [ ] 每条保留 `en_name`、`cn_name`、`raw_payload` 与 `source_file_id` 溯源
- [ ] laterality 自 `en_name` 推断，左右不合并
- [ ] 与 AAL3 全量 candidate **分表或分 `source_kind` 存储**，不混为一张「万能脑区表」
- [ ] 工作台可上传 xlsx 并预览解析结果
- [ ] 不写 `final_*` / `kg_*`，不经审核不 promotion

---

## 8. 给后续 AI 的实现提示

```
先读：docs/MACRO_96_REGION_POOL.md（本文件）、docs/GPT_SESSION_SYNC.md、§25 写权限矩阵。

任务：实现宏观 96 标准池 Excel 解析最小闭环（可与 AAL3 并行，不替代 AAL3 全量链路）。
输入：Brain volume list.xlsx（三列：ID # / Brain Structure / 脑区中文名称）。
输出：candidate 侧 96 池表 + 列表/详情 API；可选挂到 import batch 状态机。
禁止：label_index<=96 冒充标准池、同名自动合并、写 final_*/kg_*、Docker、自动 migration。
```

---

*维护：更换 xlsx 版本或列定义时，更新 §2.3–2.5 与 §7 验收项。*
