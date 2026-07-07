# NeuroGraphIQ KG V3 — LLM 提取主流程标准

Date: 2026-07-03. 定义 LLM 提取的标准管道：脑区池 → 分包 → 配置 → 执行 → 解析 → Mirror KG → 实时反馈。

## 核心原则

1. 所有提取以"包"为最小执行单位
2. 每包独立调用 LLM、独立解析、独立统计
3. 单包失败不中断全局任务
4. 无发现包不算成功也不算失败，单独统计
5. 成功包必须解析出有效业务数据
6. 运行中统计来自后端真实 progress
7. 成功解析结果进入 Mirror KG，不直接写 Final KG
8. Mirror KG 写入复用 canonical key 去重、merge、update
9. 提示词以系统内置模板为主，用户只覆盖任务目标和输出约束
10. 前端弹窗只负责配置和展示，后端 runner 独立完成

## 用户流程（4 步弹窗）

### Step 1：脑区池选择
- 展示已选脑区（中文名、英文名、ID、侧别、Atlas、状态）
- 设置每包脑区数（默认 20，范围 5–50）
- 预计包数预览

### Step 2：LLM 基础配置
- provider / model / temperature / max_tokens
- pack_concurrency / budget_cny / dry_run / skip_existing

### Step 3：提示词目标配置
- 提取目标：连接/功能/回路/回路步骤/回路功能/复合
- 目标表 + schema_version + run_instruction_overlay

### Step 4：Dry Run / 正式提取
- 预估 token、费用、包数
- 超预算阻止执行
- 执行后实时进度面板

## Pack 策略

| 策略 | 说明 |
|------|------|
| region_pack_intra | 每包 N 脑区，提取包内关系 |
| all_pairs_pack | 全脑区展开 pair 后分包 |

## Pack 状态

- `succeeded` — 解析出 ≥1 条有效数据
- `no_findings` — LLM 正常但无发现（不算失败）
- `failed` — LLM 调用/解析失败
- `skipped` — 取消/依赖失败跳过

## Mirror KG 写入规则

- 不写 Final KG
- 不自动审核、不自动晋升
- 去重：canonical key + 置信度优先
- 保留 provenance、source_trace、run_id

## 实施顺序

1. 跑通 1 包最小链路
2. 5 包：失败不中断 + no_findings 统计
3. 96 脑区完整分包 + 并发
4. Mirror KG 写入 + 统计
5. 重试失败包 + 后台任务中心
