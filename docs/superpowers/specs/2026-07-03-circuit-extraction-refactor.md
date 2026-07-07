# Circuit Extraction Refactor — 回路粗提取

Date: 2026-07-03. Replace the old `circuit_with_function_steps` composite workflow with a single-step, pack-based circuit extraction from the brain region pool.

## 1. 核心流程

```
脑区池（N 个脑区）
  → 打乱排列，按每 pack M 个脑区分组（默认 M=10）
  → 每 pack：构建提示词（列脑区信息）→ 送入 DeepSeek
  → 解析 JSON 输出：circuits[] + circuit_steps[] + circuit_functions[]
  → 写入 MirrorRegionCircuit / MirrorCircuitStep / MirrorCircuitFunction
  → 全 pack 完成后展示汇总结果
```

## 2. 替换旧流程

- 快捷卡片"回路+步骤+功能"的 `onClick` 从触发旧 `circuit_with_function_steps` 改为触发新流程
- 旧 composite workflow step 定义 (`WORKFLOW_STEP_DEFS["circuit_with_function_steps"]`) 保留但不再从 UI 入口触发
- 前端 `PoolExtractionModal` 的回路提取调用新 API

## 3. 后端 API

新建单一端点：

```
POST /api/llm-extraction/circuit-extraction/run
```

请求：
```json
{
  "provider": "deepseek",
  "model_name": "deepseek-chat",
  "candidate_ids": ["uuid1", "uuid2", ...],
  "pool_id": "uuid",
  "pairs_per_pack": 10,
  "temperature": 0.2,
  "max_tokens": 16384,
  "dry_run": false
}
```

响应（非 dry run）：
```json
{
  "run_id": "uuid",
  "status": "pending"
}
```

轮询：
```
GET /api/llm-extraction/circuit-extraction/runs/{run_id}
```

响应（终端）：
```json
{
  "id": "uuid",
  "status": "succeeded",
  "provider": "deepseek",
  "model_name": "deepseek-chat",
  "candidate_count": 96,
  "pack_count": 10,
  "circuit_count": 23,
  "step_count": 67,
  "function_count": 45,
  "result_summary_json": {
    "circuit_created": 23,
    "step_created": 67,
    "function_created": 45,
    "model_call_count": 10,
    "estimated_input_tokens": 50000,
    "estimated_output_tokens": 15000
  },
  "items": [...],
  "errors_json": [],
  "warnings_json": []
}
```

## 4. 提示词设计

输入：每个 pack 包含 M 个脑区的信息（region_name_cn, region_name_en, region_id, atlas, 功能标签等）。

输出 JSON schema：
```json
{
  "circuits": [{
    "circuit_name": "string",
    "circuit_type": "string",
    "function_association": "string",
    "description": "string",
    "confidence": 0.0-1.0,
    "member_region_ids": ["uuid1", "uuid2"],
    "steps": [{
      "step_order": 1,
      "step_name": "string",
      "step_type": "string",
      "role": "string",
      "description": "string",
      "confidence": 0.0-1.0,
      "region_id": "uuid or null",
      "functions": [{
        "function_term_en": "string",
        "function_term_cn": "string",
        "function_domain": "string",
        "function_role": "string",
        "effect_type": "string",
        "description": "string",
        "confidence": 0.0-1.0
      }]
    }]
  }]
}
```

## 5. 写入策略

- 写入 `mirror_region_circuits`、`mirror_circuit_steps`、`mirror_circuit_functions`
- `mirror_status` = 根据 model_name 设置（llm_suggested / llm_v4_pro / llm_reasoner / llm_kimi）
- `review_status` = "pending"
- `promotion_status` 保持默认
- 去重：同 circuit_name + member_region_ids 的回路合并（按置信度优先）
- 不写 final_* / kg_*

## 6. 前端弹窗

复用 `PoolExtractionModal` 模式：
- Step 1：确认脑区池（显示池内脑区列表 + pack 预览）
- Step 2：模型配置（provider / model / temperature / max_tokens / packs_per_pack）
- Step 3：Dry run 预览（估计 pack 数、token 量、费用）
- Step 4：执行 + 实时进度（轮询 run status）

## 7. 暂停/后台运行修复

- 后端 `execute_background` 添加 `_check_cancelled` 检查点（在 pack 之间）
- 前端 poller 正确响应 `cancelled` 状态
- "后台运行"按钮关闭弹窗但不停止后端任务

## 8. 旧代码清理

- 移除 `CompositeWorkflowType.circuit_with_function_steps` 的工作流步骤定义
- 保留 service 函数（`llm_circuit_extraction_service` 等）以备后用
- 确保 `llm_composite_workflow_service` 不影响

## 9. 验收标准

1. 快捷卡片"回路+步骤+功能"正常触发，打开弹窗
2. Pack 脑区 → LLM → 解析 → 写入三表，覆盖所有字段
3. 进度条实时更新（pack N/M）
4. 暂停按钮可中断（pack 间检查取消标志）
5. 后台运行关闭弹窗后任务继续
6. 数据中心 Mirror KG → Circuits / Steps / Functions 可查看结果
7. Dry run 展示预估 token 和费用
8. 旧 composite workflow 入口不影响
