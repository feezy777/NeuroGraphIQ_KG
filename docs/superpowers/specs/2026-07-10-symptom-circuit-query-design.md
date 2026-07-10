# 症状回路查询 — Design Spec

**Date**: 2026-07-10
**Status**: approved

## 功能

用户输入症状描述 → LLM 标准化为功能术语 → 在图谱中检索关联回路 → 列表+图谱双视图展示

## 页面布局

左右分屏：
- 左：回路列表（按影响强度排序，点击跳转详情）
- 右：D3 图谱（全局模式，关联回路高亮，其余灰色半透明，亮度 = 影响强度）

## 查询模式

| 模式 | 说明 |
|------|------|
| 单功能模式 | 用户输入 → LLM 输出 1 个标准化功能 → 检索 |
| 多功能模式 | 用户输入 → LLM 输出 N 个标准化功能 → 检索合并结果 |

## 数据流

```
1. POST /api/symptom-query/analyze
   输入: { symptom: "头晕眼花走路飘", mode: "multi" }
   DeepSeek →
   输出: { functions: ["前庭功能障碍", "本体感觉异常", "视动反射异常"] }

2. POST /api/symptom-query/search
   输入: { functions: [...], granularity_level: "macro" }
   → function_domain 匹配 mirror_circuit_functions
   → circuit_id → mirror_region_circuits + mirror_circuit_steps
   输出: { circuits: [{ id, name, steps, match_score, matched_functions }] }
```

## 影响强度 = 匹配数 / 回路总功能数

## 实现

### 后端 (1 新 router: `symptom_query.py`)

```
/api/symptom-query/analyze  POST  — LLM 症状→功能标准化
/api/symptom-query/search   POST  — 功能→回路检索
```

### 前端 (1 新页面 + 1 侧边栏入口)

```
frontend/src/pages/SymptomQueryPage.tsx  — 主体
frontend/src/layout/WorkbenchLayout.tsx   — 加侧边栏入口
```

复用: `FinalKgGraphCanvas.tsx` — D3 图组件（加 highlightNodes 参数）

## 不改

- 不修改现有功能（LLM 提取、字段补全等）
- 不修改数据库结构
- 只读查询，无写入
