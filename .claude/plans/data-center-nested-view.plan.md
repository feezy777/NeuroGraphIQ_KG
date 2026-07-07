# Plan: 数据中心嵌套展示

**Complexity**: MEDIUM  
**Scope**: 仅 UI 展示层，不改 API/DB

## 设计

```
导航: 候选脑区 | 连接 | 回路 | 三元组 | 证据  ← 不变

[连接 Tab]
┌─────────────────────────────────────────────┐
│ 工具栏: [AI补全] [选页] [选择全部]          │
├─────────────────────────────────────────────┤
│ ☐ canonical_id    type      dir   conf  ▸  │
│ ☐ hippocampus→amyg structural bi    0.8  ▸  │
│   ├── 📋 关联功能 (3)                       │  ← 展开行
│   │   function_term_en  domain     role     │
│   │   memory_encoding   memory     exec     │
│   │   emotion_detection emotion    gen      │
├─────────────────────────────────────────────┤
│ ☐ amygdala→prefr   functional uni    0.6  ▸  │
└─────────────────────────────────────────────┘

[回路 Tab]
┌─────────────────────────────────────────────┐
│ 工具栏: [AI补全] [选页] [选择全部]          │
├─────────────────────────────────────────────┤
│ ☐ circuit_name                    type  ▸  │
│ ☐ fronto-striato-thalamic_cognitive motor ▸  │
│   ├── 📝 步骤 (3)                           │  ← 展开行
│   │   ├── Step1: 前额叶→纹状体 (source) ▸   │
│   │   │   ⚡ 功能: cognitive_control         │  ← 二级展开
│   │   │   ⚡ 功能: working_memory            │
│   │   ├── Step2: 纹状体→丘脑 (relay)    ▸   │
│   │   └── Step3: 丘脑→前额叶 (output)   ▸   │
└─────────────────────────────────────────────┘
```

## 实现

### 连接展开行
- 点击 ▸ → 调用 `GET /api/mirror-kg/projection-functions?projection_id={id}`
- 内嵌子表：function_term_en, function_domain, function_role
- 复用 `DataTable` 组件

### 回路展开行  
- 点击 ▸ → 调用 `GET /api/mirror-kg/circuits/{id}/steps`（已有）
- 步骤子表 + 每个步骤再展开显示 functions
- 二级展开用简单的 list 展示，不用嵌套 DataTable

### 不变
- 脑区 / 三元组 / 证据 Tab 完全不动
- AI补全弹窗逻辑不动
- 工具栏、筛选、分页不动
