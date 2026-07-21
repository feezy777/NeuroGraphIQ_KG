# Molecular 粒度神经回路提取 v2 — 完整架构设计

> 状态：待确认 | 日期：2026-07-21 | 作者：Claude Code

## 1. 概述

基于 574 个正式脑区和 64,313 条有向投射，通过**确定性图算法生成候选拓扑** + **DeepSeek 语义判定**的方式，尽可能完整地发现有意义的神经回路。所有结果进入独立候选池，不写入正式回路库。

## 2. 架构概述

```
┌──────────────────────────────────────────────────────────┐
│  API: POST /api/llm-extraction/molecular-circuit/start   │
│  API: GET  /runs /runs/{id} /cancel /pause /resume       │
├──────────────────────────────────────────────────────────┤
│  Adapter Layer (复用现有通用任务框架)                     │
│  ┌──────────────────────────────────────────────────┐    │
│  │ MolecularCircuitTaskAdapter                       │    │
│  │  - 状态机: pending→running→pause_requested→paused │    │
│  │           →completed/failed/cancelled              │    │
│  │  - 委托: llm_workflow_cancel_registry             │    │
│  │  - 进度: molecular_circuit_extraction_runs 表     │    │
│  │  - 检查点: pack 级可恢复                           │    │
│  └──────────────────────────────────────────────────┘    │
├──────────────────────────────────────────────────────────┤
│  Phase 1: GraphEngine (纯 Python, 无 LLM)                │
│  ┌────────────┐  ┌─────────────┐  ┌──────────────────┐  │
│  │ 图索引构建  │→│ Motif 生成器 │→│ Canonical 去重    │  │
│  │ 邻接表+BFS  │  │ 9 种拓扑类型│  │ + 拓扑预评分      │  │
│  └────────────┘  └─────────────┘  └──────────────────┘  │
│  输出: raw_topology_candidates (JSONL)                    │
├──────────────────────────────────────────────────────────┤
│  Phase 2: ModuleClassifier + Packer                       │
│  ┌──────────────┐  ┌──────────────┐  ┌───────────────┐  │
│  │ 10 模块多标签 │→│ 分包 (100-200│→│ Token 预算控制  │  │
│  │ 分类器       │  │ 候选/pack)   │  │               │  │
│  └──────────────┘  └──────────────┘  └───────────────┘  │
│  输出: packs (JSONL, 可直接送入 LLM)                      │
├──────────────────────────────────────────────────────────┤
│  Phase 3: DeepSeek 语义判定                               │
│  ┌────────────┐  ┌──────────────┐  ┌──────────────────┐  │
│  │ Prompt 构建 │→│ LLM 并发调用  │→│ 结构化 JSON 解析  │  │
│  └────────────┘  └──────────────┘  └──────────────────┘  │
│  输出: reviewed_topology_candidates                       │
├──────────────────────────────────────────────────────────┤
│  Phase 4: QualityGate                                     │
│  ┌──────────────┐  ┌──────────────┐  ┌───────────────┐  │
│  │ 节点/边验证  │→│ 方向/闭环验证 │→│ Canonical 去重  │  │
│  └──────────────┘  └──────────────┘  └───────────────┘  │
│  输出: validated + failed_items                           │
├──────────────────────────────────────────────────────────┤
│  Phase 5: CandidatePool                                   │
│  ┌──────────────────────────────────────────────────┐    │
│  │ mirror_molecular_circuit_candidates 表             │    │
│  │  - canonical_key (幂等)                           │    │
│  │  - extraction_run_id + pack_id (可追溯)           │    │
│  │  - 原始 LLM 响应 + 校验结果                       │    │
│  │  - 不写入 mirror_region_circuits                  │    │
│  └──────────────────────────────────────────────────┘    │
└──────────────────────────────────────────────────────────┘
```

## 3. 文件规划

### 新增文件（全部独立）

| 文件 | 用途 | 行数估算 |
|------|------|---------|
| `backend/app/services/molecular_circuit_graph_engine.py` | 图构建、邻接表、9 种 motif 生成、canonical 去重、拓扑预评分 | ~800 |
| `backend/app/services/molecular_circuit_module_classifier.py` | 10 模块多标签分类、cross-module 标记 | ~300 |
| `backend/app/services/molecular_circuit_prompt_builder.py` | DeepSeek 判定提示词构建、token 估算 | ~400 |
| `backend/app/services/molecular_circuit_quality_gate.py` | 确定性校验、去重合并、failed_items 收集 | ~400 |
| `backend/app/services/molecular_circuit_extraction_service.py` | 主编排、适配器、阶段衔接、检查点 | ~600 |
| `backend/app/routers/molecular_circuit_extraction.py` | REST API（start/list/get/cancel/pause/resume/retry） | ~300 |
| `backend/app/schemas/molecular_circuit_extraction.py` | Pydantic request/response | ~400 |
| `backend/app/models/molecular_circuit_candidate.py` | 候选池 ORM 模型 | ~150 |
| `backend/migrations/20260721_molecular_circuit_candidate_pool.sql` | DDL | ~80 |

### 修改文件（最小化）

| 文件 | 修改 |
|------|------|
| `backend/app/main.py` | 注册新 router |
| `backend/app/database.py` | 无需修改（复用现有连接） |

### 不修改的文件

- `llm_circuit_pack_service.py`
- `llm_circuit_extraction_service.py`
- `llm_composite_workflow_service.py`
- `mirror_kg_service.py`
- 任何 `final_*`、`kg_*` 文件

## 4. 适配器设计：复用通用任务框架

现有框架在 `llm_workflow_cancel_registry.py` 提供：
- 内存取消/暂停标志
- `is_cancelling(run_id)` / `mark_cancelling(run_id)`
- `is_pause_requested(run_id)` / `mark_pause_requested(run_id)` / `clear_pause_requested(run_id)`

适配器 `MolecularCircuitTaskAdapter`：

```python
class MolecularCircuitTaskAdapter:
    """Reuse existing task infrastructure without copying state machine."""

    def __init__(self, run_id: uuid.UUID):
        self.run_id = run_id

    async def check_cancelled(self) -> bool:
        return is_cancelling(self.run_id)

    async def check_pause(self) -> None:
        if is_pause_requested(self.run_id):
            await self._persist_pause_state()
            raise TaskPausedError()

    async def checkpoint(self, phase: str, progress: dict) -> None:
        """Write pack-level checkpoint to DB for resume."""
        await update_run_progress(self.run_id, phase, progress)

    async def checkpoint_pack(self, pack_index: int, status: str) -> None:
        """Mark individual pack as done for retry recovery."""
        ...
```

状态迁移：

```
                    ┌─────────┐
                    │ pending │
                    └────┬────┘
                         │ start
                    ┌────▼────┐
              ┌─────│ running │◄──────────┐
              │     └──┬──┬──┘            │
              │        │  │               │
     pause_requested   │  │         resume│
              │        │  │               │
         ┌────▼───┐    │  │          ┌────┴───┐
         │ paused │────┘  │          │ resume  │
         └────────┘       │          └────────┘
                    ┌─────▼──────┐
                    │ cancelling │ (cleanup in progress)
                    └─────┬──────┘
                          │
              ┌───────────┼───────────┐
         ┌────▼───┐  ┌───▼────┐  ┌───▼──────┐
         │cancelled│  │completed│  │failed    │
         └─────────┘  └────────┘  └──────────┘
```

检查点恢复策略：
- 每个 pack 完成后写入 `completed_pack_indices: [0,1,2,...]`
- retry 时读取已完成 packs，只处理剩余
- 幂等写入（canonical_key 保证不会重复）

## 5. 图引擎设计

### 5.1 有向邻接表

```python
class MolecularGraphEngine:
    nodes: dict[str, BrainRegionNode]           # region_id → node
    adjacency: dict[str, set[str]]               # source → {targets}
    reverse_adjacency: dict[str, set[str]]       # target → {sources}
    edges: dict[str, EdgeRecord]                 # edge_id → edge

    # SCC 缓存
    scc_components: list[set[str]]               # 强连通分量
    scc_index: dict[str, int]                    # node → component_id

    # Hub 缓存
    hubs: list[str]                              # top 50 by degree
    hub_neighborhoods: dict[str, set[str]]       # hub → 2-hop neighbors
```

### 5.2 Motif 类型定义

| # | topolopy_type | anatomical_pattern | 说明 | 复杂度控制 | 上限 |
|---|--------------|-------------------|------|-----------|------|
| 1 | `directed_cycle_3` | closed_circuit | A→B→C→A 三节点闭环 | O(E*d_max)，完全生成 | 10000 |
| 2 | `feedforward_loop_3` | feedforward_motif | A→B, A→C, B→C | O(E*d_max)，完全生成 | 10000 |
| 3 | `reciprocal_pair_3` | feedback_motif | A↔B 且 B↔C 三节点链 | O(E)，完全生成 | 5000 |
| 4 | `convergent_motif` | convergent_motif | A→C, B→C | O(n^2*d_max)，采样 | 5000 |
| 5 | `divergent_motif` | divergent_motif | A→B, A→C | O(n^2*d_max)，采样 | 5000 |
| 6 | `relay_pathway_3_6` | open_pathway | 3-6节点有向中继通路 | BFS bounded depth=6 | 20000 |
| 7 | `closed_loop_4_8` | closed_circuit | 4-8节点闭合环路 | **SCC内 bounded DFS** | 5000 |
| 8 | `cortico_subcortical_loop` | closed_circuit | 皮层↔皮层下回路 | SCC内+hub邻域 | 5000 |
| 9 | `cross_module_loop` | closed_circuit | 跨≥2模块反馈回路 | 模块间+SCC | 5000 |

**组合爆炸控制**：
- 类型 1-3：完整生成（O(E*d_max)，574 节点稠密图可行）
- 类型 4-5：仅对 top-50 hub 生成，每条边最多生成 20 个候选
- 类型 6：BFS 深度上限 6，每节点最多扩展 10 条路径
- 类型 7：仅在 SCC 内部搜索，largest SCC 超过 50 节点时限制 BFS 步数
- 类型 8-9：通过模块标记 + hub 邻域预筛选后 SCC 内搜索
- 全局实时 canonical key 去重（每生成一个候选立即检查是否已存在）
- 预评分 cutoff：topology_score < 0.1 直接丢弃

候选数量估算：

| 类型 | 上限 | 估计实际 |
|------|------|---------|
| directed_cycle_3 | 10000 | ~3000-8000 |
| feedforward_loop_3 | 10000 | ~2000-5000 |
| reciprocal_pair_3 | 5000 | ~1000-3000 |
| convergent/divergent | 10000 | ~5000-8000 |
| relay_pathway_3_6 | 20000 | ~5000-15000 |
| closed_loop_4_8 | 5000 | ~500-3000 |
| cortico_subcortical_loop | 5000 | ~200-1000 |
| cross_module_loop | 5000 | ~500-2000 |
| **总计** | **70000** | **~17000-45000** |

### 5.3 Canonical Key 归一化

```python
def canonical_key_directed_cycle(node_ids: list[str]) -> str:
    """有向环：旋转到字典序最小的起点"""
    rotations = [node_ids[i:] + node_ids[:i] for i in range(len(node_ids))]
    return "::".join(min(rotations))

def canonical_key_pathway(node_ids: list[str]) -> str:
    """开放通路：保持方向，首节点 < 尾节点字典序"""
    if node_ids[0] < node_ids[-1]:
        return "::".join(node_ids)
    return "::".join(reversed(node_ids))

def canonical_key_motif(node_ids: list[str], motif_type: str) -> str:
    """汇聚/发散 motif：排序源节点+目标节点"""
    sources = sorted(node_ids[:-1])
    target = node_ids[-1]
    return f"{motif_type}::{':'.join(sources)}→{target}"
```

全局 `seen: set[str]` 在生成过程中实时去重。

### 5.4 拓扑预评分

进入 DeepSeek 前按以下维度排序：

```python
def topology_pre_score(candidate: RawTopologyCandidate) -> float:
    score = 0.0
    # 1. 拓扑完整性 (0-0.25)
    score += 0.25 * (1.0 if candidate.is_closed else 0.7)
    # 2. 原始边置信度均值 (0-0.25)
    score += 0.25 * avg_edge_confidence(candidate.edges)
    # 3. 证据数量 (0-0.20)
    score += 0.20 * min(1.0, total_evidence_count / 10)
    # 4. 解剖一致性 (0-0.15)
    score += 0.15 * anatomical_consistency(candidate)
    # 5. 模块一致性 (0-0.10)
    score += 0.10 * module_coherence(candidate)
    # 6. 冗余度惩罚 (0-0.05)
    score -= 0.05 * redundancy_penalty(candidate)
    return clamp(score, 0.0, 1.0)
```

排序后 top-N 送入 DeepSeek（剩余暂存为 `raw_low_priority`）。

## 6. 模块分类器

### 6.1 10 个功能模块（多标签）

| # | module_name | 典型脑区 |
|---|-------------|---------|
| 1 | `sensory` | 视觉、听觉、体感、味觉、嗅觉皮层 |
| 2 | `motor` | 初级运动、前运动、辅助运动、小脑 |
| 3 | `attention_salience` | 前扣带回、岛叶、顶叶注意区 |
| 4 | `executive_control` | 背外侧前额叶、前额极 |
| 5 | `learning_memory` | 海马、内嗅皮层、旁海马 |
| 6 | `emotion_reward` | 杏仁核、伏隔核、腹侧被盖区、眶额 |
| 7 | `language_social` | Broca、Wernicke、颞顶联合区 |
| 8 | `interoception_autonomic` | 脑岛、前扣带回、下丘脑、脑干核 |
| 9 | `sleep_arousal` | 脑干网状结构、基底前脑、下丘脑 |
| 10 | `multimodal_default` | 默认模式网络、多感官整合区 |

分类方法：
- 优先使用现有脑区功能标签 (`functional_domains`)
- 补充基于解剖位置的启发式规则
- 信息不足时标记为 `module_uncertain`
- 每个脑区允许 1-3 个标签
- 单独计算 cross-module 候选（至少 2 个不同模块）

### 6.2 分包策略

```python
@dataclass
class PackConfig:
    max_candidates_per_pack: int = 150   # 候选拓扑数
    max_edges_per_pack: int = 400        # 相关边数
    max_tokens_estimate: int = 55000     # 估算 token 上限
    include_cross_module: bool = True    # 每包包含跨模块候选

# 每包内容
class Pack:
    module_name: str
    module_description: str
    candidate_topologies: list[dict]    # 有序节点 + edge_id 列表
    relevant_edges: list[dict]          # 边的详细信息
    region_basics: list[dict]           # 候选脑区基本信息
    functional_labels: dict             # region_id → labels
    cross_module_hubs: list[str]        # 跨模块枢纽脑区
```

## 7. DeepSeek 判定提示词

### 7.1 系统提示词

```
You are an expert in neuroanatomy, systems neuroscience, and brain connectomics.
Your task is to judge whether candidate topological structures constitute
biologically meaningful neural circuits, feedback loops, feedforward pathways,
relay chains, or functional network modules.

CRITICAL RULES:
1. NEVER invent brain regions not present in the input.
2. NEVER invent edges not present in the input.
3. NEVER change the direction of any projection.
4. NEVER infer A→C from A→B and B→C (no transitive closure).
5. You MUST return the complete list of edge_ids constituting each result.
6. For closed loops, verify the LAST node truly projects back to the FIRST.
7. Topologically valid but functionally uncertain candidates MAY be kept at low confidence.
8. Distinguish: canonical textbook circuits, plausible novel combinations, and topology-only structures.
9. Do NOT reject a candidate simply because the region name is unfamiliar.
10. Do NOT output node-rotated duplicates of the same circuit.
11. Do NOT interpret correlational connections as causal projections.
12. When evidence is insufficient, explicitly state the uncertainty.

You will receive candidate topologies with their constituent regions and edges.
For EACH candidate, output a structured JSON judgment.
Do NOT output a summary paragraph — output only the JSON array.
```

### 7.2 输出结构

```json
{
  "circuit_id": "canonical_key",
  "name_en": "string",
  "name_cn": "string",
  "functional_module": ["sensory", "motor"],
  "topology_type": "directed_cycle_3",
  "anatomical_pattern": "closed_circuit",
  "closed_loop": true,
  "nodes": [
    {"order": 1, "region_id": "uuid", "region_name": "string", "role": "source"}
  ],
  "edges": [
    {"order": 1, "edge_id": "uuid", "source_region_id": "uuid", "target_region_id": "uuid",
     "connection_type": "projection", "source_confidence": 0.8}
  ],
  "functional_summary": "string",
  "neuroscience_rationale": "string",
  "evidence_basis": "string",
  "known_status": "canonical|literature_supported|plausible_hypothesis|topology_only",
  "topology_score": 0.85,
  "anatomical_score": 0.7,
  "functional_score": 0.6,
  "evidence_score": 0.5,
  "overall_confidence": 0.66,
  "confidence_level": "medium",
  "uncertainties": ["string"],
  "review_status": "candidate"
}
```

## 8. 质量门

### 8.1 校验规则

```python
def validate_circuit(candidate: dict, graph: MolecularGraphEngine) -> ValidationResult:
    checks = []

    # 1. 所有 region_id 属于 574 脑区
    for node in candidate["nodes"]:
        if node["region_id"] not in graph.nodes:
            checks.append(Violation("unknown_region", node["region_id"]))

    # 2. 所有 edge_id 存在
    # 3. source/target 与原始边一致
    # 4. 节点顺序与边顺序连续
    for i, edge in enumerate(candidate["edges"]):
        actual = graph.edges.get(edge["edge_id"])
        if actual is None:
            checks.append(Violation("missing_edge", edge["edge_id"]))
        elif actual.source != edge["source_region_id"] or actual.target != edge["target_region_id"]:
            checks.append(Violation("direction_mismatch", edge["edge_id"]))

    # 5. closed_loop=true 时最后 target == 首节点
    if candidate.get("closed_loop"):
        last_target = candidate["edges"][-1]["target_region_id"]
        first_source = candidate["edges"][0]["source_region_id"]
        if last_target != first_source:
            checks.append(Violation("loop_not_closed", f"{last_target} != {first_source}"))

    # 6. 不存在重复 edge_id
    # 7. 不存在旋转重复（canonical key 已有）

    return ValidationResult(
        passed=len(checks) == 0,
        violations=checks
    )
```

### 8.2 去重合并

- Canonical key 基于节点序列 + 边序列 + topology_type
- 相同 canonical key → 保留 confidence 最高的
- 较短回路完全包含在较长回路中 → 都保留，记录 `parent_circuit_id`
- 名称不同但节点和边完全相同 → 合并，取最高分

## 9. 候选池存储

### 9.1 数据库表

```sql
CREATE TABLE molecular_circuit_candidate_runs (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    status VARCHAR(32) NOT NULL DEFAULT 'pending',
    provider VARCHAR(32), model_name VARCHAR(128),
    candidate_count INT, pack_count INT,
    total_raw_topologies INT, total_passed INT, total_failed INT,
    high_confidence INT DEFAULT 0, medium_confidence INT DEFAULT 0, low_confidence INT DEFAULT 0,
    progress_json JSONB DEFAULT '{}',
    result_summary_json JSONB DEFAULT '{}',
    created_at TIMESTAMPTZ DEFAULT now(), updated_at TIMESTAMPTZ DEFAULT now()
);

CREATE TABLE mirror_molecular_circuit_candidates (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    extraction_run_id UUID REFERENCES molecular_circuit_candidate_runs(id),
    pack_id INT NOT NULL,
    canonical_key VARCHAR(512) NOT NULL,

    -- Topology info
    topology_type VARCHAR(64) NOT NULL,
    anatomical_pattern VARCHAR(64) NOT NULL,
    closed_loop BOOLEAN NOT NULL DEFAULT false,
    node_count INT NOT NULL, edge_count INT NOT NULL,

    -- DeepSeek review
    name_en VARCHAR(512), name_cn VARCHAR(512),
    functional_module JSONB DEFAULT '[]',
    known_status VARCHAR(64),
    overall_confidence FLOAT,
    confidence_level VARCHAR(16),

    -- Scores
    topology_score FLOAT, anatomical_score FLOAT,
    functional_score FLOAT, evidence_score FLOAT,
    pre_score FLOAT,   -- 进入 DeepSeek 前的预评分

    -- Detailed data
    nodes_json JSONB NOT NULL,
    edges_json JSONB NOT NULL,
    llm_raw_response_json JSONB DEFAULT '{}',
    validation_result_json JSONB DEFAULT '{}',

    -- Status tracking
    review_status VARCHAR(32) NOT NULL DEFAULT 'candidate',
    -- candidate | manual_review | rejected | promoted | superseded
    parent_circuit_id UUID,
    created_at TIMESTAMPTZ DEFAULT now(),
    updated_at TIMESTAMPTZ DEFAULT now(),

    UNIQUE(canonical_key, extraction_run_id)
);

CREATE INDEX idx_mcc_run ON mirror_molecular_circuit_candidates(extraction_run_id);
CREATE INDEX idx_mcc_canonical ON mirror_molecular_circuit_candidates(canonical_key);
CREATE INDEX idx_mcc_confidence ON mirror_molecular_circuit_candidates(confidence_level);
CREATE INDEX idx_mcc_type ON mirror_molecular_circuit_candidates(topology_type);
```

### 9.2 JSONL 边界

候选生成阶段（Phase 1-2）使用 JSONL 中间存储：
- `raw_topology_candidates.jsonl` — 所有生成候选（未送审）
- `reviewed_candidates.jsonl` — DeepSeek 返回结果  
- `validated_candidates.jsonl` — 校验通过 + 去重后
- `failed_items.jsonl` — 失败项

数据库仅存储最终结果（Phase 5），JSONL 作为中间临时文件。

### 9.3 幂等性

```python
async def upsert_candidate(session, candidate: dict):
    """INSERT ON CONFLICT (canonical_key, extraction_run_id) DO NOTHING"""
    # 已有相同 canonical_key 则跳过 → 重试不重复写入
    ...
```

## 10. API 设计

```
POST /api/llm-extraction/molecular-circuit/start
  Body: MolecularCircuitExtractionRequest
  Response: MolecularCircuitStartResponse (202)

GET  /api/llm-extraction/molecular-circuit/runs
GET  /api/llm-extraction/molecular-circuit/runs/{run_id}
POST /api/llm-extraction/molecular-circuit/runs/{run_id}/cancel
POST /api/llm-extraction/molecular-circuit/runs/{run_id}/pause
POST /api/llm-extraction/molecular-circuit/runs/{run_id}/resume
POST /api/llm-extraction/molecular-circuit/runs/{run_id}/retry-failed
GET  /api/llm-extraction/molecular-circuit/runs/{run_id}/progress
GET  /api/llm-extraction/molecular-circuit/runs/{run_id}/export
```

请求参数：
```python
class MolecularCircuitExtractionRequest(BaseModel):
    provider: str = "deepseek"
    model_name: str = "deepseek-v4-pro"
    functional_modules: list[str] | None = None  # 指定模块，None=全部
    motif_types: list[str] | None = None
    min_path_length: int = 3
    max_path_length: int = 8
    include_low_confidence: bool = True
    confidence_floor: float = 0.05
    pack_candidate_limit: int = 150
    pack_edge_limit: int = 400
    pack_concurrency: int = 2
    retry_failed_only: bool = False  # 仅重试上次失败的 packs
    dry_run: bool = False  # 仅生成拓扑，不调用 LLM
```

## 11. 进度报告

每个阶段汇报：

| 阶段 | 指标 |
|------|------|
| 图构建 | 节点数、边数、SCC 数、hub 数 |
| 候选生成 | 各 motif 类型候选数、去重后、预评分分布 |
| 分包 | 包数、每包 token 估算 |
| LLM 判定 | 已完成包、通过/失败包、当前速度 |
| 校验 | 通过数、拒绝数、重复合并数 |
| 总计 | 高/中/低置信度分布、cost 估算 |

前端通过 `GET /runs/{id}/progress` 轮询。

## 12. 测试矩阵

| # | 测试 | 类型 |
|---|------|------|
| 1 | 三节点闭环正确识别 | 单元 |
| 2 | 前馈环不被误判为闭合回路 | 单元 |
| 3 | 不存在边时禁止 LLM 补边（mock LLM） | 集成 |
| 4 | 方向错误结果被拒绝 | 单元 |
| 5 | 闭环 canonical 去重 | 单元 |
| 6 | 同一路径不同名称合并 | 单元 |
| 7 | 574 节点 + 64K 边性能测试 | 性能 |
| 8 | 分包稳定性（相同输入→相同输出） | 集成 |
| 9 | 暂停/继续/取消/失败重试 | 集成 |
| 10 | 候选池写入 + 幂等性 | 集成 |
| 11 | Major/Sub 粒度回路提取不受影响 | 回归 |
| 12 | 相同输入重复运行一致性 | 集成 |
| 13 | subject/object 均能回查 574 候选脑区 | 集成 |
| 14 | 所有关系回查原始 edge_id | 集成 |
| 15 | 所有关系回查 circuit_id + step_order | 集成 |
| 16 | provenance 完整率 100% | 集成 |
| 17 | DeepSeek 虚构脑区/连接被拦截 | 单元 |
| 18 | 字段缺失无依据默认值被拦截 | 单元 |
| 19 | 幂等写入：重试不重复 | 集成 |
| 20 | 数据中心/回路主表/步骤表数量对账 | 集成 |

验收指标：
- 图构建 < 10s
- 候选生成 < 60s
- 单包 LLM 调用 < 120s
- 所有类型检查通过
- 不影响其他粒度

## 12. 数据中心字段完整写入

通过图算法校验、DeepSeek 语义判定和 Quality Gate 的 Molecular 回路，不仅要写入回路候选主表和步骤表，还要按照现有数据中心的数据结构生成完整的关系记录。

### 12.1 审计要求

先审计数据中心实际数据库字段名、API schema、状态枚举和现有写入方式。界面中的 "confidence（Mirror）""evidence_text（Mirror）" 可能是展示名称，必须使用后端真实字段，不得自行创建重复字段。

### 12.2 回路步骤 → 数据中心关系记录

每个通过校验的回路步骤生成一条数据中心关系记录。例如 A → B → C → A 应生成：A→B、B→C、C→A。

脑区相关字段必须从系统现有候选脑区表读取，使用候选脑区表中的正式 `region_id`、中文名、英文名、实体类型和其他标准字段。禁止直接使用 DeepSeek 返回的自由文本名称作为正式脑区字段，禁止创建候选脑区表中不存在的新脑区。

### 12.3 字段填写规则

| # | 字段 | 规则 |
|---|------|------|
| 1 | `id` | 使用项目现有 ID 生成机制；由数据库/UUID 生成器生成；禁止使用数组下标或可能重复的临时编号 |
| 2 | `subject_type` | 使用候选脑区表和数据中心现有的正式脑区实体类型；不得另行创造新枚举 |
| 3 | `subject_id` | 当前回路步骤中 source 脑区对应的候选脑区正式 ID；必须能唯一匹配 574 个候选脑区之一 |
| 4 | `subject_label` | 从候选脑区表读取标准显示名称；不使用 DeepSeek 自行改写的名称覆盖正式名称 |
| 5 | `predicate` | 优先继承 64,313 条原始连接中的正式关系类型；不得把所有边统一写成 `related_to`；不得由 LLM 创造新的关系类型 |
| 6 | `object_type` | 使用候选脑区表和数据中心现有的正式脑区实体类型 |
| 7 | `object_id` | 当前回路步骤中 target 脑区对应的候选脑区正式 ID |
| 8 | `object_label` | 从候选脑区表读取目标脑区标准名称；不使用 DeepSeek 自由生成名称覆盖 |
| 9 | `confidence` | 填写原始连接记录中的基础置信度；如一条边有多条原始记录，按系统已有聚合规则计算；禁止让 DeepSeek 替代；原始连接确实无置信度时保留 null 进入人工复核 |
| 10 | `evidence_count` | 优先使用原始连接记录的证据数量；从关联证据表确定性统计；不允许 DeepSeek 估算；数值必须与实际可追溯证据记录一致 |
| 11 | `created_at` | 使用数据中心现有时间生成规则；不复制原始连接的旧时间 |
| 12 | `mirror_status` | 使用现有状态枚举；本阶段生成的数据均属于镜像候选数据，不得标记为正式数据 |
| 13 | `review_status` | 高置信度+Quality Gate 通过→待审核；中低置信度→人工复核；拓扑/字段校验失败→拒绝；必须映射为项目当前已有枚举 |
| 14 | `validation_status` | Quality Gate 全部通过后填写验证通过状态；任一项失败不得标记通过 |
| 15 | `promotion_status` | 不得自动正式入库；默认使用未晋升状态；即使置信度很高也不得自动标记已晋升 |
| 16 | `mirror_confidence` | 使用后端实际对应字段；填写 DeepSeek 对当前回路步骤的语义判断置信度(0~1)；与原始连接 `confidence` 分开保存 |
| 17 | `mirror_evidence_text` | 使用后端实际对应字段；DeepSeek 基于当前输入数据形成的简洁语义解释；不得伪造论文标题/DOI/实验结论；原始证据文本与 Mirror 解释必须分开保存 |
| 18 | `provenance` | 结构化来源信息，至少包含: `extraction_run_id`, `workflow_type`, `pack_id`, `candidate_id`, `circuit_id`, `canonical_key`, `step_order`, `edge_id`, `source_connection_record_id`, `source_region_record_id`, `target_region_record_id`, `functional_modules`, `topology_type`, `anatomical_pattern`, `graph_algorithm`, `prompt_version`, `model`, `quality_gate_version`, `raw_response_reference`, `created_by` |

### 12.4 新增文件

| 文件 | 用途 |
|------|------|
| `backend/app/services/molecular_circuit_datacenter_writer.py` | 数据中心关系记录写入 + 字段映射 |
| `backend/app/services/molecular_circuit_datacenter_validator.py` | Data Center Record Quality Gate |

## 13. 脑区字段权威来源

候选脑区表是 Molecular 脑区实体的唯一权威来源。

写入前必须建立 `regionById`、`regionByCanonicalName`、`regionAliasIndex`，但最终关联只能以正式脑区 ID 确认。

规则：
1. source 和 target 都必须在 574 个候选脑区中存在
2. ID 匹配成功后，subject_label 和 object_label 从候选脑区表重新读取
3. 原始连接名称/DeepSeek 名称与候选脑区名称不一致时，以候选脑区表为准
4. 名称差异写入 `provenance` 或 `validation_issues`
5. 不允许只根据名称创建脑区
6. 不允许多个未知脑区共用一个 `unknown_region`
7. 任一端无法匹配候选脑区时，该步骤进入 `failed_items`，不得写入数据中心
8. 不得在本工作流中修改候选脑区表内容

## 14. 字段完整性门 (Data Center Record Quality Gate)

写入数据中心前增加专门的校验。至少验证：

- `id` 非空且唯一
- `subject_type`/`object_type` 合法
- `subject_id`/`object_id` 存在
- `subject_label`/`object_label` 非空
- `predicate` 合法（不为 `related_to` 等无意义默认值）
- `confidence` 为 null 或 0~1 合法数值
- `evidence_count` 为非负整数
- `created_at` 有效
- 所有状态字段符合现有枚举
- `mirror_confidence` 为 0~1
- `mirror_evidence_text` 非空或明确标记缺失原因
- `provenance` 包含全部必要追溯字段
- source 与 target 和原始 edge_id 完全一致
- 同一 run 重试不会重复写入相同步骤

**禁止为了"填满字段"而伪造内容。** 字段无法可靠获得时：
- Schema 允许为空→保留 null，记录 `missing_fields`
- Schema 不允许为空→不得写入有效候选池，进入人工复核或失败清单
- 不得使用"未知""暂无""0.5"等无依据默认值绕过校验

## 15. 幂等写入与事务

回路候选主记录、回路步骤记录和数据中心关系记录必须在可控事务中写入。

幂等键至少包含：`extraction_run_id` + `canonical_key` + `step_order` + `edge_id` + `subject_id` + `predicate` + `object_id`。

- 失败重试、任务恢复和重复提交不得产生重复记录
- 单条步骤写入失败时：不得造成半条记录；应记录具体失败字段和错误原因；不得导致已完成的其他包结果丢失；回路主记录与步骤记录的一致性必须可校验

## 16. 最终验收统计

任务汇总中增加：

| 指标 | 说明 |
|------|------|
| 生成回路候选数 | total circuits |
| 生成步骤总数 | total steps |
| 成功写入数据中心关系数 | records written to datacenter |
| 字段全部完整的关系数 | records with all fields |
| 可空字段缺失的关系数 | records with nullable fields missing |
| 因脑区无法匹配而拒绝的步骤数 | region match failures |
| 因 predicate 非法而拒绝的步骤数 | illegal predicate |
| 因证据字段缺失进入人工复核数量 | manual review for missing evidence |
| 因状态字段非法而失败的数量 | illegal status enum |
| 重复关系拦截数量 | duplicate intercepts |
| `provenance` 完整率 | % with full provenance |
| subject/object 与候选脑区表一致率 | % region match |
| 原始 confidence 覆盖率 | % with source confidence |
| Mirror confidence 覆盖率 | % with mirror confidence |
| evidence_count 覆盖率 | % with evidence count |
| Mirror evidence_text 覆盖率 | % with mirror evidence text |

**验收要求：**
1. 写入数据中心的 subject 和 object 均能回查到 574 个候选脑区
2. 所有关系均能回查原始 edge_id
3. 所有关系均能回查所属 circuit_id 和 step_order
4. 所有关系均具备完整 provenance
5. 不存在 DeepSeek 虚构脑区
6. 不存在 DeepSeek 虚构连接
7. 不存在字段缺失但被静默填入无依据默认值
8. 不写入正式库
9. 不影响 Major、Sub 及其他粒度现有数据
10. 数据中心、回路候选主表和步骤表之间数量关系可以对账

## 17. 文件清单（更新）

```
新: backend/app/services/molecular_circuit_graph_engine.py
新: backend/app/services/molecular_circuit_module_classifier.py
新: backend/app/services/molecular_circuit_prompt_builder.py
新: backend/app/services/molecular_circuit_quality_gate.py
新: backend/app/services/molecular_circuit_datacenter_writer.py
新: backend/app/services/molecular_circuit_datacenter_validator.py
新: backend/app/services/molecular_circuit_extraction_service.py
新: backend/app/routers/molecular_circuit_extraction.py
新: backend/app/schemas/molecular_circuit_extraction.py
新: backend/app/models/molecular_circuit_candidate.py
新: backend/migrations/20260721_molecular_circuit_candidate_pool.sql
改: backend/app/main.py (注册 router)
```

---

**Spec 完成。请审核，确认后我将用 writing-plans skill 拆分为实施计划。**
