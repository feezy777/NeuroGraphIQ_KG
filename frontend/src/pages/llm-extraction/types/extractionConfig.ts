import type {
  Paginated,
  LlmExtractionRun,
} from '../../../api/endpoints'
import {
  listMirrorConnections,
  listMirrorFunctions,
  listMirrorCircuits,
  listMirrorTriples,
  listMirrorCircuitSteps,
  listMirrorProjectionFunctions,
  listMirrorCircuitProjectionMemberships,
  listMirrorCircuitFunctions,
  listMirrorDualModelVerificationResults,
  listMirrorValidationResults,
  listMirrorReviewQueue,
  listLlmExtractionItems,
  listLlmExtractionRuns,
} from '../../../api/endpoints'
import {
  Brain,
  GitBranch,
  Activity,
  Workflow,
  Footprints,
  Zap,
  Link2,
  Cpu,
  CheckCircle2,
  AlertTriangle,
  FileText,
  Layers,
} from 'lucide-react'
import type { LucideIcon } from 'lucide-react'

// ── Detail field descriptor ──────────────────────────────────────────────
export interface DetailField {
  key: string              // field name in the item object
  label: string            // display label
  render?: 'text' | 'badge' | 'confidence' | 'truncated' | 'json' | 'date'
  fallback?: string        // fallback if value is null/undefined
}

// ── Action descriptor ────────────────────────────────────────────────────
export interface ResultAction {
  key: string
  label: string
  icon?: LucideIcon
  /** If true, emit an event; the parent handles navigation/logic */
  handler: 'view-detail' | 'jump-mirror' | 'jump-review' | 'jump-validation' | 'custom'
}

// ── Extraction type config ────────────────────────────────────────────────
export interface ExtractionTypeConfig {
  /** Unique type identifier matching backend target_type */
  targetType: string
  /** Tab label shown in UI */
  tabLabel: string
  /** Icon for result rows */
  icon: LucideIcon
  /** Field used as primary label */
  labelField: string
  /** Optional secondary label field */
  sublabelField?: string
  /** Which status field to use */
  statusField: string
  /** Which confidence field to use */
  confidenceField?: string
  /** Fields shown in expanded card */
  detailFields: DetailField[]
  /** Action buttons shown in expanded card */
  actions: ResultAction[]
  /** Data fetching function */
  fetchFn: (params: Record<string, unknown>) => Promise<Paginated<any>>
  /** Function to fetch runs for filtering */
  fetchRunsFn: (params: Record<string, unknown>) => Promise<Paginated<LlmExtractionRun>>
  /** Empty state message key */
  emptyKey: string
}

// ── Shared detail fields ─────────────────────────────────────────────────
const MIRROR_STATUS_FIELDS: DetailField[] = [
  { key: 'mirror_status', label: 'Mirror Status', render: 'badge' },
  { key: 'review_status', label: 'Review Status', render: 'badge' },
  { key: 'promotion_status', label: 'Promotion Status', render: 'badge' },
]

const CONFIDENCE_EVIDENCE_FIELDS: DetailField[] = [
  { key: 'confidence', label: '置信度', render: 'confidence', fallback: '-' },
  { key: 'evidence_text', label: 'Evidence', render: 'truncated', fallback: '-' },
  { key: 'uncertainty_reason', label: '不确定性', render: 'text', fallback: '-' },
]

const SOURCE_FIELDS: DetailField[] = [
  { key: 'source_atlas', label: 'Atlas', render: 'text', fallback: '-' },
  { key: 'granularity_level', label: 'Granularity', render: 'text', fallback: '-' },
  { key: 'llm_run_id', label: 'LLM Run', render: 'text', fallback: '-' },
]

// ── Fetch wrappers ────────────────────────────────────────────────────────
function mkFetch(fn: (p: any) => Promise<Paginated<any>>): (params: Record<string, unknown>) => Promise<Paginated<any>> {
  return (params: Record<string, unknown>) => fn(params)
}

const fetchRunsByTaskType = (taskType: string): ExtractionTypeConfig['fetchRunsFn'] =>
  (params) => listLlmExtractionRuns({ ...params, task_type: taskType } as any)

// ── Configs ───────────────────────────────────────────────────────────────
export const EXTRACTION_TYPE_CONFIGS: ExtractionTypeConfig[] = [
  // ── Core Mirror KG ─────────────────────────────────────────────────────
  {
    targetType: 'connections', // matches MirrorSubTabId
    tabLabel: '连接',
    icon: GitBranch,
    labelField: 'connection_type',
    sublabelField: 'directionality',
    statusField: 'mirror_status',
    confidenceField: 'confidence',
    detailFields: [
      { key: 'connection_type', label: '连接类型', render: 'text' },
      { key: 'directionality', label: '方向性', render: 'badge' },
      { key: 'strength', label: '强度', render: 'text', fallback: '-' },
      { key: 'modality', label: '模态', render: 'text', fallback: '-' },
      ...CONFIDENCE_EVIDENCE_FIELDS,
      ...SOURCE_FIELDS,
      ...MIRROR_STATUS_FIELDS,
    ],
    actions: [
      { key: 'view-detail', label: '查看详情', handler: 'view-detail' },
      { key: 'jump-review', label: '审核', handler: 'jump-review' },
    ],
    fetchFn: mkFetch(listMirrorConnections),
    fetchRunsFn: fetchRunsByTaskType('same_granularity_connection'),
    emptyKey: 'extraction.emptyConnections',
  },
  {
    targetType: 'functions', // matches MirrorSubTabId
    tabLabel: '功能',
    icon: Activity,
    labelField: 'function_term',
    sublabelField: 'function_category',
    statusField: 'mirror_status',
    confidenceField: 'confidence',
    detailFields: [
      { key: 'function_term', label: '功能术语', render: 'text' },
      { key: 'function_category', label: '功能类别', render: 'badge' },
      { key: 'relation_type', label: '关系类型', render: 'badge' },
      ...CONFIDENCE_EVIDENCE_FIELDS,
      ...SOURCE_FIELDS,
      ...MIRROR_STATUS_FIELDS,
    ],
    actions: [
      { key: 'view-detail', label: '查看详情', handler: 'view-detail' },
      { key: 'jump-review', label: '审核', handler: 'jump-review' },
    ],
    fetchFn: mkFetch(listMirrorFunctions),
    fetchRunsFn: fetchRunsByTaskType('same_granularity_function'),
    emptyKey: 'extraction.emptyFunctions',
  },
  {
    targetType: 'circuits', // matches MirrorSubTabId
    tabLabel: '回路',
    icon: Workflow,
    labelField: 'circuit_name',
    sublabelField: 'circuit_type',
    statusField: 'mirror_status',
    confidenceField: 'confidence',
    detailFields: [
      { key: 'circuit_name', label: '回路名', render: 'text' },
      { key: 'circuit_type', label: '回路类型', render: 'badge' },
      { key: 'function_association', label: '功能关联', render: 'text', fallback: '-' },
      { key: 'description', label: '描述', render: 'truncated', fallback: '-' },
      ...CONFIDENCE_EVIDENCE_FIELDS,
      ...SOURCE_FIELDS,
      ...MIRROR_STATUS_FIELDS,
    ],
    actions: [
      { key: 'view-detail', label: '查看详情', handler: 'view-detail' },
      { key: 'jump-review', label: '审核', handler: 'jump-review' },
    ],
    fetchFn: mkFetch(listMirrorCircuits),
    fetchRunsFn: fetchRunsByTaskType('same_granularity_circuit'),
    emptyKey: 'extraction.emptyCircuits',
  },
  {
    targetType: 'triples', // matches MirrorSubTabId
    tabLabel: '三元组',
    icon: Layers,
    labelField: 'predicate',
    sublabelField: 'subject_label',
    statusField: 'mirror_status',
    confidenceField: 'confidence',
    detailFields: [
      { key: 'subject_type', label: '主语类型', render: 'text' },
      { key: 'subject_label', label: '主语', render: 'text' },
      { key: 'predicate', label: '谓词', render: 'text' },
      { key: 'object_type', label: '宾语类型', render: 'text' },
      { key: 'object_label', label: '宾语', render: 'text' },
      { key: 'triple_scope', label: '作用域', render: 'badge' },
      ...CONFIDENCE_EVIDENCE_FIELDS,
      ...SOURCE_FIELDS,
      ...MIRROR_STATUS_FIELDS,
    ],
    actions: [
      { key: 'view-detail', label: '查看详情', handler: 'view-detail' },
      { key: 'jump-review', label: '审核', handler: 'jump-review' },
    ],
    fetchFn: mkFetch(listMirrorTriples),
    fetchRunsFn: fetchRunsByTaskType('triple_generation'),
    emptyKey: 'extraction.emptyTriples',
  },

  // ── Macro Clinical ──────────────────────────────────────────────────────
  {
    targetType: 'circuit_step',
    tabLabel: '回路步骤',
    icon: Footprints,
    labelField: 'step_name',
    sublabelField: 'step_type',
    statusField: 'mirror_status',
    confidenceField: 'confidence',
    detailFields: [
      { key: 'step_name', label: '步骤名', render: 'text' },
      { key: 'step_type', label: '步骤类型', render: 'badge' },
      { key: 'step_order', label: '顺序', render: 'text' },
      { key: 'role', label: '角色', render: 'badge' },
      { key: 'description', label: '描述', render: 'truncated', fallback: '-' },
      ...CONFIDENCE_EVIDENCE_FIELDS,
      ...SOURCE_FIELDS,
      ...MIRROR_STATUS_FIELDS,
    ],
    actions: [
      { key: 'view-detail', label: '查看详情', handler: 'view-detail' },
      { key: 'jump-review', label: '审核', handler: 'jump-review' },
    ],
    fetchFn: mkFetch(listMirrorCircuitSteps),
    fetchRunsFn: fetchRunsByTaskType('circuit_to_steps'),
    emptyKey: 'extraction.emptyCircuitSteps',
  },
  {
    targetType: 'projection_function',
    tabLabel: '投影功能',
    icon: Zap,
    labelField: 'function_term',
    sublabelField: 'function_category',
    statusField: 'mirror_status',
    confidenceField: 'confidence',
    detailFields: [
      { key: 'function_term', label: '功能术语', render: 'text' },
      { key: 'function_category', label: '功能类别', render: 'badge' },
      { key: 'relation_type', label: '关系类型', render: 'badge' },
      ...CONFIDENCE_EVIDENCE_FIELDS,
      ...SOURCE_FIELDS,
      ...MIRROR_STATUS_FIELDS,
    ],
    actions: [
      { key: 'view-detail', label: '查看详情', handler: 'view-detail' },
      { key: 'jump-review', label: '审核', handler: 'jump-review' },
    ],
    fetchFn: mkFetch(listMirrorProjectionFunctions),
    fetchRunsFn: fetchRunsByTaskType('projection_to_functions'),
    emptyKey: 'extraction.emptyProjectionFunctions',
  },
  {
    targetType: 'circuit_projection_membership',
    tabLabel: 'Membership',
    icon: Link2,
    labelField: 'role_in_circuit',
    sublabelField: 'source_method',
    statusField: 'mirror_status',
    confidenceField: 'confidence',
    detailFields: [
      { key: 'role_in_circuit', label: '回路角色', render: 'badge' },
      { key: 'source_method', label: '来源方法', render: 'text' },
      { key: 'step_order', label: '步骤顺序', render: 'text', fallback: '-' },
      { key: 'verification_status', label: '验证状态', render: 'badge' },
      ...CONFIDENCE_EVIDENCE_FIELDS,
      ...SOURCE_FIELDS,
      ...MIRROR_STATUS_FIELDS,
    ],
    actions: [
      { key: 'view-detail', label: '查看详情', handler: 'view-detail' },
      { key: 'jump-review', label: '审核', handler: 'jump-review' },
    ],
    fetchFn: mkFetch(listMirrorCircuitProjectionMemberships),
    fetchRunsFn: fetchRunsByTaskType('projections_to_circuits'),
    emptyKey: 'extraction.emptyMemberships',
  },
  {
    targetType: 'circuit_function',
    tabLabel: '回路功能',
    icon: Cpu,
    labelField: 'function_term_en',
    sublabelField: 'function_domain',
    statusField: 'mirror_status',
    confidenceField: 'confidence_score',
    detailFields: [
      { key: 'function_term_en', label: '功能(EN)', render: 'text' },
      { key: 'function_term_cn', label: '功能(CN)', render: 'text', fallback: '-' },
      { key: 'function_domain', label: '功能域', render: 'badge' },
      { key: 'function_role', label: '功能角色', render: 'badge', fallback: '-' },
      { key: 'effect_type', label: '效应类型', render: 'badge', fallback: '-' },
      { key: 'evidence_level', label: '证据等级', render: 'badge', fallback: '-' },
      ...MIRROR_STATUS_FIELDS,
    ],
    actions: [
      { key: 'view-detail', label: '查看详情', handler: 'view-detail' },
      { key: 'jump-review', label: '审核', handler: 'jump-review' },
    ],
    fetchFn: mkFetch(listMirrorCircuitFunctions),
    fetchRunsFn: fetchRunsByTaskType('circuit_to_functions'),
    emptyKey: 'extraction.emptyCircuitFunctions',
  },

  // ── Validation / Review / Signal ────────────────────────────────────────
  {
    targetType: 'validation_result',
    tabLabel: '校验结果',
    icon: CheckCircle2,
    labelField: 'rule_code',
    sublabelField: 'severity',
    statusField: 'status',
    confidenceField: undefined,
    detailFields: [
      { key: 'target_type', label: '目标类型', render: 'text' },
      { key: 'rule_code', label: '规则', render: 'text' },
      { key: 'severity', label: '严重度', render: 'badge' },
      { key: 'status', label: '状态', render: 'badge' },
      { key: 'message', label: '消息', render: 'text' },
      { key: 'details_json', label: '详情', render: 'json', fallback: '-' },
    ],
    actions: [
      { key: 'view-detail', label: '查看详情', handler: 'view-detail' },
    ],
    fetchFn: mkFetch(listMirrorValidationResults),
    fetchRunsFn: fetchRunsByTaskType(''),
    emptyKey: 'extraction.emptyValidationResults',
  },
  {
    targetType: 'review_item',
    tabLabel: '审核队列',
    icon: AlertTriangle,
    labelField: 'display_label',
    sublabelField: 'target_type',
    statusField: 'review_status',
    confidenceField: 'confidence',
    detailFields: [
      { key: 'target_type', label: '目标类型', render: 'text' },
      { key: 'display_label', label: '标签', render: 'text' },
      { key: 'mirror_status', label: 'Mirror Status', render: 'badge' },
      { key: 'review_status', label: 'Review Status', render: 'badge' },
      { key: 'promotion_status', label: 'Promotion Status', render: 'badge' },
      { key: 'recommended_review_priority', label: '优先级', render: 'badge', fallback: '-' },
      { key: 'blocker_count', label: '阻断', render: 'text', fallback: '0' },
      { key: 'error_count', label: '错误', render: 'text', fallback: '0' },
    ],
    actions: [
      { key: 'view-detail', label: '审核', handler: 'jump-review' },
    ],
    fetchFn: mkFetch(listMirrorReviewQueue),
    fetchRunsFn: fetchRunsByTaskType(''),
    emptyKey: 'extraction.emptyReviewItems',
  },
  {
    targetType: 'dual_model_result',
    tabLabel: '双模型',
    icon: Brain,
    labelField: 'object_type',
    sublabelField: 'consensus_status',
    statusField: 'consensus_status',
    confidenceField: 'consensus_score',
    detailFields: [
      { key: 'object_type', label: '对象类型', render: 'text' },
      { key: 'model_a_provider', label: 'Model A', render: 'text' },
      { key: 'model_a_decision', label: 'A 决策', render: 'badge' },
      { key: 'model_b_provider', label: 'Model B', render: 'text' },
      { key: 'model_b_decision', label: 'B 决策', render: 'badge' },
      { key: 'consensus_status', label: '共识', render: 'badge' },
      { key: 'conflict_summary', label: '冲突摘要', render: 'truncated', fallback: '-' },
      { key: 'recommended_review_priority', label: '审核优先级', render: 'badge', fallback: '-' },
    ],
    actions: [
      { key: 'view-detail', label: '查看详情', handler: 'view-detail' },
    ],
    fetchFn: mkFetch(listMirrorDualModelVerificationResults),
    fetchRunsFn: fetchRunsByTaskType('dual_model_verification'),
    emptyKey: 'extraction.emptyDualModel',
  },

  // ── Raw Extraction Items ────────────────────────────────────────────────
  {
    targetType: 'extraction_item',
    tabLabel: '提取条目',
    icon: FileText,
    labelField: 'task_type',
    sublabelField: 'status',
    statusField: 'status',
    confidenceField: 'confidence',
    detailFields: [
      { key: 'task_type', label: '任务类型', render: 'text' },
      { key: 'item_index', label: '序号', render: 'text' },
      { key: 'status', label: '状态', render: 'badge' },
      { key: 'confidence', label: '置信度', render: 'confidence', fallback: '-' },
      { key: 'evidence_text', label: 'Evidence', render: 'truncated', fallback: '-' },
      { key: 'uncertainty_reason', label: '不确定性', render: 'text', fallback: '-' },
      { key: 'error_message', label: '错误', render: 'text', fallback: '-' },
    ],
    actions: [
      { key: 'view-detail', label: '查看详情', handler: 'view-detail' },
    ],
    fetchFn: mkFetch(listLlmExtractionItems),
    fetchRunsFn: (params) => listLlmExtractionRuns(params as any),
    emptyKey: 'extraction.emptyItems',
  },
]

export function getConfig(targetType: string): ExtractionTypeConfig | undefined {
  return EXTRACTION_TYPE_CONFIGS.find(c => c.targetType === targetType)
}
