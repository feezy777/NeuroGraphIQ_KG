# Final KG 三元组图谱模型与探索设计

> **文档类型**：架构设计 / 知识图谱模型  
> **版本**：2026-06-24  
> **状态**：设计确定，骨架代码已存在  
> **关联文档**：`NEUROGRAPHIQ_VIBE_CODING_GUIDE.md`、`TRIPLE_MODEL_AND_ONTOLOGY_DESIGN.md`、`NEUROGRAPHIQ_KG_V3_TARGET_ARCHITECTURE.md`

---

## 1. 核心概念

### 1.1 知识图谱的三层模型

```
┌────────────────────────────────────────────────────────┐
│                   第一层：实体层 (Nodes)                  │
│  ┌─────────────┐  ┌─────────────┐  ┌─────────────┐    │
│  │   脑区实体   │  │   功能实体   │  │   回路实体   │    │
│  │ BrainRegion │  │   Function  │  │   Circuit   │    │
│  └──────┬──────┘  └──────┬──────┘  └──────┬──────┘    │
│         │               │               │           │
├─────────┼───────────────┼───────────────┼────────────┤
│         第二层：关系层 (Edges / Predicates)              │
│                                                       │
│  脑区 ──连接类型──→ 脑区        (structurally_connects)│
│  脑区 ──has_function─→ 功能    (memory, visual...)    │
│  连接 ──has_function─→ 功能    (projection function)  │
│  回路 ──contains─→ 连接        (circuit membership)  │
│  回路 ──has_function─→ 功能    (circuit function)     │
│  回路 ──has_step─→ 步骤        (ordered step)         │
│  步骤 ──involves─→ 脑区        (step region)          │
│                                                       │
├────────────────────────────────────────────────────────┤
│                   第三层：统一查询层                      │
│             subject ─ predicate ─ object                 │
│             (final_kg_triples 表)                       │
└────────────────────────────────────────────────────────┘
```

### 1.2 设计目标

| 目标 | 说明 |
|------|------|
| **可探索的地图** | 从任意脑区出发，沿连接链路漫游，查看关联功能和回路 |
| **一切可追溯** | 每个三元组、每个实体都有完整的 provenance（来源、版本、LLM run、审核记录） |
| **功能编织** | 脑区有功能、连接有功能、回路有功能——功能是最核心的"元信息"贯穿全文 |
| **回路即结构** | 回路是有序连接链（step_by_step），不是脑区集合，不是无结构标签 |
| **确定性生成** | Triple Consolidation 是确定性转换（不调 LLM），从 Final KG 对象直接推导 |

---

## 2. 实体节点类型

### 2.1 BrainRegion（脑区）

| 源表 | Final 表 | 唯一标识 |
|------|----------|----------|
| `candidate_brain_regions` | `final_brain_regions` | `final_uid` (含 atlas + id) |

**节点属性（三元组中 subject_label / object_label）：**
```
"左海马体 (AAL3:Hippocampus_L)"
```

### 2.2 Projection / Connection（连接）

| 源表 | Final 表 | 唯一标识 |
|------|----------|----------|
| `mirror_region_connections` | `final_projections` | `final_uid` |

**在三元组中，连接作为关系边存在：**
```
subject: 脑区A
predicate: projects_to / structurally_connects_to
object: 脑区B
```

**但连接本身也有功能（ProjectionFunction），所以连接也作为 subject 出现：**
```
subject: 连接P（由 final_uid 标识）
predicate: has_projection_function
object: 功能F（如 "sensorimotor_integration"）
```

### 2.3 Circuit（回路）

| 源表 | Final 表 | 唯一标识 |
|------|----------|----------|
| `mirror_region_circuits` | `final_region_circuits` | `final_uid` |

**回路的三种关系：**

```
回路C — contains_projection → 连接P    (membership)
回路C — has_circuit_function → 功能F  (circuit_function)
回路C — has_step → 步骤S               (circuit_step)
步骤S — involves → 脑区R               (step → region)
```

### 2.4 Function（功能）

功能是贯穿全图的**元信息标签**，它不是独立的 Final 表，而是与连接/回路关联的属性。

| 来源 | 类型 | 对应表 |
|------|------|--------|
| `mirror_projection_functions` | 连接功能 | `final_projection_functions` |
| `mirror_circuit_functions` | 回路功能 | `final_circuit_functions` |
| `final_region_functions` | 脑区功能 | `final_region_functions` |
| `mirror_region_functions` | 脑区功能候选 | `mirror_region_functions` |

---

## 3. 三元组谓词定义（Predicates）

### 3.1 完整谓词表

| 分类 | 谓词 | 主语类型 | 宾语类型 | 来源表 |
|------|------|---------|---------|--------|
| **脑区→脑区** | `structurally_connects_to` | brain_region | brain_region | final_projections |
| | `functionally_connects_to` | brain_region | brain_region | final_projections |
| | `effectively_connects_to` | brain_region | brain_region | final_projections |
| | `projects_to` | brain_region | brain_region | final_projections |
| | `associated_with` | brain_region | brain_region | final_projections |
| | `coactivates_with` | brain_region | brain_region | final_projections |
| | `possibly_connects_to` | brain_region | brain_region | final_projections |
| **脑区→功能** | `has_function` | brain_region | function | final_region_functions |
| | `associated_with_function` | brain_region | function | final_region_functions |
| **连接→功能** | `has_projection_function` | projection | function | final_projection_functions |
| **回路→功能** | `has_circuit_function` | circuit | function | final_circuit_functions |
| **回路→连接** | `contains_projection` | circuit | projection | final_circuit_projection_memberships |
| **回路→步骤** | `has_step` | circuit | circuit_step | final_circuit_steps |
| **步骤→脑区** | `involves_region` | circuit_step | brain_region | final_circuit_steps |

### 3.2 三元组示例

**连接三元组：**
```
左海马体 (AAL3:Hippocampus_L) — structurally_connects_to → 左内嗅皮层 (AAL3:Entorhinal_L)
```

**功能三元组——脑区功能：**
```
左海马体 — has_function → "记忆编码"
左海马体 — has_function → "空间导航"
```

**功能三元组——连接功能：**
```
左海马体→左内嗅皮层连接 — has_projection_function → "记忆信息传递"
```

**回路三元组——回路结构：**
```
海马-内嗅回路 — contains_projection → 左海马体→左内嗅皮层连接
海马-内嗅回路 — has_step → 步骤1
海马-内嗅回路 — has_step → 步骤2
步骤1 — involves_region → 左海马体
步骤2 — involves_region → 左内嗅皮层
```

**回路功能三元组：**
```
海马-内嗅回路 — has_circuit_function → "情景记忆形成"
```

---

## 4. 完整的探索图（Graph Explorer 设计）

### 4.1 以脑区为中心的展开

```
用户搜索：左海马体

┌────────────────────────────────────────────┐
│              左海马体                        │
│  ┌────────────────────────────────────┐    │
│  │ 功能：记忆编码、空间导航             │    │
│  └────────────────────────────────────┘    │
│                                            │
│  ── 连接出去 ──                            │
│  ├── structurally_connects_to → 内嗅皮层    │
│  │     └── 连接功能：记忆信息传递           │
│  ├── functionally_connects_to → 前扣带回   │
│  │     └── 连接功能：情景记忆检索           │
│  └── projects_to → 下托                   │
│                                            │
│  ── 加入回路 ──                            │
│  ├── 海马-内嗅回路                         │
│  │     ├── 步骤：左海马体 → 内嗅皮层       │
│  │     └── 功能：情景记忆形成               │
│  └── Papez回路                             │
│        └── 步骤：海马 → 乳头体 → 前丘脑    │
└────────────────────────────────────────────┘
```

### 4.2 以功能为中心的聚合

```
用户搜索：记忆

┌────────────────────────────────────────────┐
│  功能：记忆                                 │
│                                            │
│  ── 具有此功能的脑区 ──                     │
│  ├── 左海马体 (confidence: 0.92)           │
│  ├── 右海马体 (confidence: 0.90)           │
│  ├── 左内嗅皮层 (confidence: 0.85)         │
│  └── 前扣带回 (confidence: 0.45)           │
│                                            │
│  ── 具有此功能的连接 ──                     │
│  ├── 海马体→内嗅皮层 (记忆信息传递)         │
│  └── 海马体→前扣带回 (情景记忆检索)         │
│                                            │
│  ── 具有此功能的回路 ──                     │
│  └── 海马-内嗅回路 (情景记忆形成)           │
└────────────────────────────────────────────┘
```

### 4.3 以回路为中心的展开

```
用户搜索：海马-内嗅回路

┌────────────────────────────────────────────┐
│  海马-内嗅回路                              │
│  功能：情景记忆形成                          │
│                                            │
│  ── 步骤链 ──                              │
│  步骤1: 左海马体 ─────────────────┐        │
│           ↓ 连接 P1 (结构)        │        │
│  步骤2: 左内嗅皮层 ───────────────┤        │
│           ↓ 连接 P2 (功能)        │ 回路组成│
│  步骤3: 左前扣带回 ───────────────┘        │
│                                            │
│  ── 回路功能 ──                            │
│  ├── 情景记忆形成                          │
│  └── 情绪记忆交互                          │
└────────────────────────────────────────────┘
```

---

## 5. 数据闭环总览

### 5.1 完整链路数据流

```
                      LLM 提取阶段
  ┌───────────────────────────────────────────────────┐
  │  candidate_brain_regions                           │
  │      ↓                                             │
  │  LLM Connection Extraction  ──→ mirror_region_connections    │
  │      ↓                                             │
  │  LLM Circuit Extraction     ──→ mirror_region_circuits      │
  │      ↓                                             │
  │  LLM Circuit Steps Extraction ──→ mirror_circuit_steps      │
  │      ↓                                             │
  │  LLM Projection Function Ext  ──→ mirror_projection_functions│
  │      ↓                                             │
  │  LLM Circuit Function Ext    ──→ mirror_circuit_functions   │
  └───────────────────────────────────────────────────┘
                          ↓
                     验证与审核阶段
  ┌───────────────────────────────────────────────────┐
  │  Rule Validation    → mirror_status = rule_checked │
  │  Cross Validation   → membership.verification      │
  │  Dual Model Verify  → consensus/conflict signal    │
  │  Human Review       → review_status = approved     │
  └───────────────────────────────────────────────────┘
                          ↓
                     Promotion 阶段
  ┌───────────────────────────────────────────────────┐
  │  mirror_* ──→ final_* (确定性写入)                 │
  │  镜像层 → 正式库                                  │
  └───────────────────────────────────────────────────┘
                          ↓
                    Triple Consolidation 阶段
  ┌───────────────────────────────────────────────────┐
  │  final_* ──→ final_kg_triples (确定性生成)          │
  │  所有实体和关系 → 统一 subject-predicate-object     │
  └───────────────────────────────────────────────────┘
                          ↓
                    探索与导出阶段
  ┌───────────────────────────────────────────────────┐
  │  Final KG Browser   → 图探索界面                   │
  │  Final KG Export    → CSV / JSON / Neo4j 兼容     │
  └───────────────────────────────────────────────────┘
```

### 5.2 最小闭环验证路径

```
选择 96 脑区
    ↓
LLM 连接提取 (all_pairs, 每个包20对)
    ↓
LLM 连接功能提取 (projection_to_functions)
    ↓
LLM 回路提取 (circuit extraction)
    ↓
LLM 回路步骤提取 (circuit_to_steps)
    ↓
LLM 回路功能提取 (circuit_to_functions)
    ↓
LLM 回路-连接 membership 提取 (circuit_steps_to_projections)
    ↓
Rule Validation (规则校验)
    ↓
Human Review (人工审核)
    ↓
Promotion → final_* (正式库)
    ↓
Triple Consolidation → final_kg_triples (三元组)
    ↓
Final KG Browser 图探索
```

---

## 6. 前端页面规划

### 6.1 新增 / 改造页面

| 步骤 | 页面 | 操作 | 后端 API |
|------|------|------|----------|
| 1 | **MirrorKG 浏览页**（新建） | 浏览 Mirror KG 中的连接/功能/回路 | `GET /api/mirror-kg/connections` `GET /api/mirror-kg/circuits` |
| 2 | **Mirror 验证页**（集成） | 触发 Rule Validation + 双模型验证 | `POST /api/mirror-kg/validation/run` |
| 3 | **Mirror 审核页**（改造 HumanReviewPage） | 审核通过/拒绝连接/功能/回路 | `POST /api/mirror-kg/review/approve` |
| 4 | **Mirror Promotion 页**（改造 PromotionsPage） | 强确认晋升到 Final KG | `POST /api/mirror-kg/promotion/promote` |
| 5 | **Final KG Browser**（新建 - 图探索） | 可视化图谱探索 | `GET /api/final-macro-clinical/browser/*` |
| 6 | **Triple 浏览**（在 Final KG Browser 中） | subject-predicate-object 展示 | `GET /api/final-kg/triples` |

### 6.2 Final KG Browser 图探索页面设计

#### 视图一：脑区详情图（Region Detail Graph）
- 选中一个脑区，显示：
  - 所有关联的连接（入边 + 出边）
  - 每条连接的功能标签
  - 该脑区参与的回路
  - 该脑区的元功能

#### 视图二：回路结构图（Circuit Structure Graph）
- 选中一个回路，显示：
  - 有序步骤链（step 1 → 2 → 3）
  - 每步关联的脑区
  - 步骤之间的连接（projections）
  - 连接的功能标签
  - 回路的元功能

#### 视图三：功能聚合图（Function Aggregation Graph）
- 选中一个功能，显示：
  - 具有此功能的脑区
  - 具有此功能的连接
  - 具有此功能的回路
  - 跨功能关联

#### 视图四：全局搜索
- 输入脑区名称、功能关键词、回路名称
- 返回匹配节点 + 展开到 1-2 度关系

### 6.3 展示技术选型建议

| 组件 | 用途 | 状态 |
|------|------|------|
| React Flow / xyflow | 节点-边图可视化 | 需引入 |
| Ant Design Table + Tree | 列表/树形浏览（备选） | 已有 |
| ECharts 关系图 | 轻量关系图 | 可选 |

---

## 7. 现有代码对照

### 7.1 已实现的链路

| 链路环节 | 后端 | 前端 | 状态 |
|----------|------|------|------|
| Connection Extraction | `llm_connection_extraction_service.py` | - | ✅ 代码完成 |
| Projection Function Extraction | `llm_projection_function_extraction_service.py` | - | ✅ 代码完成 |
| Circuit Extraction | `llm_circuit_extraction_service.py` | - | ✅ 代码完成 |
| Circuit Step Extraction | `llm_circuit_step_extraction_service.py` | - | ✅ 代码完成 |
| Circuit Function Extraction | `llm_circuit_function_extraction_service.py` | - | ✅ 代码完成 |
| Circuit→Projection Membership | `llm_circuit_projection_extraction_service.py` | - | ✅ 代码完成 |
| Projection→Circuit 反向 | `llm_projection_circuit_extraction_service.py` | - | ✅ 代码完成 |
| Composite Workflow | `llm_composite_workflow_service.py` | - | ✅ 代码完成 |
| Mirror KG CRUD | `mirror_kg_service.py` + `mirror_kg.py` | - | ✅ 代码完成 |
| Mirror Rule Validation | `mirror_validation.py` + Service | - | ✅ 代码完成 |
| Mirror Cross Validation | `mirror_cross_validation.py` + Service | - | ✅ 代码完成 |
| Mirror Dual Model Verify | `mirror_dual_model_verification.py` + Service | - | ✅ 代码完成 |
| Mirror Human Review | `mirror_review.py` + `human_review_service.py` | HumanReviewPage | ✅ 后端 ✅ 前端骨架 |
| Mirror → Final Promotion | `mirror_promotion.py` + `final_macro_clinical_promotion_service.py` | - | ✅ 后端，前端待接 |
| Triple Consolidation | `triple_consolidation_service.py` | - | ✅ 后端，前端待接 |
| Final KG Browser | `final_macro_clinical_browser_service.py` + `final_db_query_service.py` | FinalRegionsPage | ✅ 后端，前端待扩展 |
| Final KG Export | `final_kg_export_service.py` | - | ✅ 后端 |

### 7.2 缺失的前端页面（需实现）

| 页面 | 对应 UI 功能 | 工作量评估 |
|------|------------|-----------|
| **MirrorKG 浏览页** | Table 展示 connections/circuits/functions，Tab 切换 | 中 |
| **Final KG Browser - 图谱探索** | React Flow 图可视化，节点展开/收起 | 大 |
| **Final KG Browser - Triple 查询** | 搜索 subject/predicate/object | 中 |
| **Mirror 审核集成** | 在 HumanReviewPage 增加 Mirror KG 审核 Tab | 小 |
| **Promotion 集成** | 在 PromotionsPage 增加 Mirror → Final 晋升 | 中 |

---

## 8. 关键设计决策

### 8.1 回路是有向连接链，不是无结构标签

```
✅ 回路 = [
    步骤1: 脑区A → 连接P1 → 脑区B,
    步骤2: 脑区B → 连接P2 → 脑区C,
    步骤3: 脑区C → 连接P3 → 脑区D,
  ]
  + 回路功能: [...]
  + 回路-连接成员关系: [P1, P2, P3]

❌ 回路 = { 标签: "memory circuit", 脑区: [A, B, C, D] }
```

### 8.2 功能贯穿所有层级

功能出现在三个层级，各有独立表：

| 层级 | 功能表 | 含义 |
|------|--------|------|
| 脑区功能 | `final_region_functions` | "这个脑区做什么" |
| 连接功能 | `final_projection_functions` | "这个连接传递什么信息/执行什么功能" |
| 回路功能 | `final_circuit_functions` | "这个回路整体承担什么功能" |

这三者通过 Triple Consolidation 统一为：
```
subject — has_function → function_term
```

### 8.3 Triple 是确定性生成

`triple_consolidation_service.py` 是纯确定性代码：
- 从 `final_*` 表读取数据
- 用 `CONNECTION_TO_PREDICATE` 映射表确定谓词
- 写入 `final_kg_triples`
- **不调 LLM**
- **不写 final_* / kg_***

### 8.4 Provenance 不可编辑

每个 Final 表和 Triple 表都保留：
- `source_mirror_*_id` → 溯源 Mirror KG
- `promotion_run_id` → 溯源晋升事件
- `review_record_id` → 溯源审核记录
- `llm_run_id` / `llm_item_id` → 溯源 LLM 提取

一旦晋升到 Final，provenance 字段不可编辑。

---

## 9. 回路线索跟踪：最小闭环验收标准

```text
从选择脑区到探索图谱的完整路径：

1. ✅ 前端选择 96 个 Macro96 候选脑区
2. ✅ LLM Connection Extraction 跑通（all_pairs, 20对/包）
3. ✅ 结果写入 mirror_region_connections
4. ✅ 前端 MirrorKG Browser 可浏览 connections
5. ⏳ 前端触发 Rule Validation
6. ⏳ 前端 Human Review → approve
7. ⏳ 前端 Promotion → final_*
8. ⏳ Triple Consolidation → final_kg_triples
9. ⏳ Final KG Browser 展示三元组图谱

验收标准：
- 能从 Final KG Browser 中看到脑区节点
- 点击脑区展开连接（出边/入边）
- 连接上显示功能标签
- 回路显示为有序步骤链
- 功能可聚合展示
```

---

*维护：新增提取类型或关系边时，同步更新 §3 谓词表与 §7 代码对照。*
