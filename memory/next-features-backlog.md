---
name: next-features-backlog
description: P1-P3 features to implement after P0 items (extraction fault recovery + cost visibility)
metadata:
  type: project
---

## P1 Priority (next after P0)

### 提取结果一键跳转
- After extraction completes, add a button in the result modal to jump directly to Data Center → Mirror KG with filters pre-applied
- PoolExtractionModal result screen needs "查看 Mirror 数据" button

### 导出功能
- Export Mirror/Final KG data as CSV/JSON
- Research use case: download connections/functions/circuits for analysis
- Add export endpoint to mirror_kg.py router

### Mirror → Final 晋升 (A3)
- PromotionsPage: add Mirror → Final promotion flow
- Strong confirmation mechanism
- Integration with existing promotion audit trail
- See CLAUDE.md roadmap Step A3

### Final KG 图可视化 (A4)
- React Flow / xyflow graph visualization
- Node expand/collapse
- Function aggregation
- See docs/FINAL_KG_TRIPLE_GRAPH_DESIGN.md

## P2 Priority

### 提取历史列表
- LLM Extraction page: show historical runs
- Re-run capability from history

### Dry run 预览增强
- Pre-execution estimate: pack count, token count, cost
- "单包预览" mode: run 1 pack with real LLM to preview output

### 跨 Atlas 连接
- Cross-atlas brain region connection extraction
- AAL3 ↔ Brainnetome mapping

## P3 Priority

### 规则校验 UI
- View/enable/disable validation rules
- Rule management interface

### Dashboard 关键指标
- Total connections, pending review count, promotion count
- Global pipeline health view

**Why:** These are the remaining gaps identified in the 2026-06-30 brainstorming session. P0 items (extraction fault recovery + cost visibility) are being implemented first.
**How to apply:** Start with P1 items tomorrow after P0 is complete. Follow priority order.
