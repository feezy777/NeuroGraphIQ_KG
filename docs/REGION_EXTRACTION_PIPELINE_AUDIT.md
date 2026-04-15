# 脑区提取链路审计（问题地图）

## 1. 链路梳理（按实际代码）

| 环节 | 位置 | 说明 |
|------|------|------|
| Excel 解析入口 | `parsing/parsing_service.py` → `_read_xlsx_file` | `openpyxl` 逐行读 sheet，生成 `table_rows`（`sheet, row, values, joined_text`）与 `table_cells`、`raw_text` |
| 「标准 JSON」 | `ParsedDocument` + `state_store` 持久化 | 中间表示为 `document` + `chunks`，非单独「标准 JSON 文件」，但结构统一 |
| 本地规则提取 | `extraction/extraction_service.py` → `_extract_by_local_rules` | 表头映射 `_HEADER_COL_MAP`、KB `_KB`、正则 `_REGION_INLINE_RE` |
| DeepSeek | 同文件 `_extract_by_deepseek`、`_deepseek_prompt_to_regions` | 分批请求、JSON 解析、`normalize_region_llm_row` |
| 「验证」 | `validation/validation_service.py` | **占位**：未对脑区候选做本体校验，仅结构计数 |
| 工作台触发 | `workbench_service.py` → `trigger_extract_regions` / `generate_regions_from_text` | `task` + `log_bus` |
| 日志 | `log_bus` → `state_store.append_task_log`；`StateStore._event` | EXTRACT / DEEPSEEK 等事件 |

## 2. 审计结论（A–G）

| ID | 结论 |
|----|------|
| **A** | 当前以 **直接生成/直接匹配** 为主：**本地**为 KB 精确/部分匹配 + 表头辅助；**DeepSeek** 为「整表/分批文本 → JSON 数组」，**不是**「先大规模候选召回再判定」的架构。 |
| **B** | 存在 **内存内 KB**（`extraction_service._KB_RAW` / `_KB`），**非**独立可维护 registry 文件；别名在 KB 条目中。 |
| **C** | **部分利用**：表头 `_detect_header_col_types`、行内多列 `field_map`；**未**系统利用「列类型（source/target）」「同列统计」「sheet 名」做加权。 |
| **D** | **弱区分**：`region_category_candidate` 有填充，但无单独「回路名/方法名/非解剖」分类器；黑名单仅能通过后续 registry 补强。 |
| **E** | `confidence` 有；**无**统一 `extract_status`（confirmed/review_needed/…）；**无**冲突对标记；未识别常表现为空或低置信单条。 |
| **F** | **无**正式评估集与自动化 precision/recall 脚本（截至审计时）。 |
| **G** | **最可能致差的 5 点**：① 召回策略偏「单点匹配」，复合单元格与跨列上下文利用不足；② LLM 路径历史上偏自由生成，虽已有归一仍缺「候选约束」；③ 无独立停用词/黑名单层；④ 验证服务为占位；⑤ 列语义未建模，备注/方法列与脑区列混抽。 |

## 3. 改造方向（与需求对齐）

- 在 **服务层** 增加可开关 `region_extraction_v2`：**输入标准化 → 高召回候选 → 本地判定与后处理 → evidence 写入**（`review_note` JSON，兼容 PG 列）。
- **不修改** `parsing_service` 主输出结构；**不修改** ingestion 主逻辑。
- DeepSeek **受约束判定**作为 **Phase 4** 可选开关（`deepseek_refine`），默认关，避免一次改崩。
