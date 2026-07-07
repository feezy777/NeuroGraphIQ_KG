/**
 * Formal-field column mappings for Data Center.
 * Aligned to real NeuroGraphIQ_KG_V3 database schema (macro_clinical.*).
 * Introspected 2026-06-17; mirror tables remain the data source.
 * Display only — no writes to formal DB.
 */

export type FormalObjectType =
  | 'projection'
  | 'projection_function'
  | 'circuit'
  | 'circuit_step'
  | 'circuit_function'
  | 'region_function'
  | 'circuit_projection_membership'
  | 'triple'
  | 'evidence'
  | 'candidate_region'

/** @deprecated use FormalObjectType */
export type FormalTargetType = FormalObjectType

export type FormalFieldRenderType =
  | 'text'
  | 'id'
  | 'canonical_id'
  | 'status'
  | 'confidence'
  | 'date'
  | 'json'
  | 'badge'

export interface FormalFieldColumn {
  key: string
  label: string
  /** Field name in the formal DB table (NeuroGraphIQ_KG_V3) */
  finalField: string
  /** Mirror table fields to try, in priority order */
  mirrorFieldCandidates: string[]
  required?: boolean
  enrichable?: boolean
  width?: number | string
  renderType?: FormalFieldRenderType
  /** Resolved via getFieldValue custom logic when mirror fields absent */
  derived?: boolean
  /** 'formal' = real formal DB field; 'governance' = mirror pipeline only */
  group?: 'formal' | 'governance'
}

export interface FormalFieldMapping {
  targetType: FormalObjectType
  label: string
  mirrorTable: string
  /** Table name within formalSchema (e.g. 'circuit') */
  finalTable: string
  /** Real DB schema name (e.g. 'macro_clinical') */
  formalSchema: string
  /** Fully-qualified formal table name (e.g. 'macro_clinical.circuit') */
  formalQualifiedName: string
  dataCenterTab: 'mirror' | 'macro' | 'candidates'
  dataCenterSubTab?: string
  implemented: boolean
  columns: FormalFieldColumn[]
}

/** @deprecated use FormalFieldMapping */
export type FormalObjectMapping = FormalFieldMapping & {
  requiredFields: string[]
  enrichableFields: string[]
  readonlyFields: string[]
}

function col(
  key: string,
  label: string,
  finalField: string,
  mirrorFieldCandidates: string[],
  opts: Partial<Omit<FormalFieldColumn, 'key' | 'label' | 'finalField' | 'mirrorFieldCandidates'>> = {},
): FormalFieldColumn {
  return { key, label, finalField, mirrorFieldCandidates, group: 'formal', ...opts }
}

function gov(
  key: string,
  label: string,
  finalField: string,
  mirrorFieldCandidates: string[],
  opts: Partial<Omit<FormalFieldColumn, 'key' | 'label' | 'finalField' | 'mirrorFieldCandidates'>> = {},
): FormalFieldColumn {
  return { key, label, finalField, mirrorFieldCandidates, group: 'governance', ...opts }
}

/** Mirror pipeline governance columns — not formal DB fields */
const GOVERNANCE: FormalFieldColumn[] = [
  gov('mirror_status', 'mirror_status', 'mirror_status', ['mirror_status'], { renderType: 'status' }),
  gov('review_status', 'review_status', 'review_status', ['review_status'], { renderType: 'status' }),
  gov('validation_status', 'validation_status', 'validation_status', ['validation_status'], { derived: true, renderType: 'status' }),
  gov('promotion_status', 'promotion_status', 'promotion_status', ['promotion_status'], { renderType: 'status' }),
  gov('confidence_mirror', 'confidence（Mirror）', 'confidence', ['confidence'], { renderType: 'confidence' }),
  gov('evidence_text_mirror', 'evidence_text（Mirror）', 'evidence_text', ['evidence_text'], { renderType: 'text' }),
  gov('provenance', 'provenance', 'provenance', [], { derived: true, renderType: 'text' }),
]

function withLegacyLists(m: FormalFieldMapping): FormalObjectMapping {
  const requiredFields = m.columns.filter(c => c.required).map(c => c.key)
  const enrichableFields = m.columns.filter(c => c.enrichable).map(c => c.key)
  const readonlyFields = ['id', 'created_at', 'updated_at', 'promotion_status', 'mirror_status']
  return { ...m, requiredFields, enrichableFields, readonlyFields }
}

const BASE_MAPPINGS: FormalFieldMapping[] = [
  // ─── macro_clinical.projection ──────────────────────────────────────────────
  {
    targetType: 'projection',
    label: 'Connection / Projection',
    mirrorTable: 'mirror_region_connections',
    finalTable: 'projection',
    formalSchema: 'macro_clinical',
    formalQualifiedName: 'macro_clinical.projection',
    dataCenterTab: 'mirror',
    dataCenterSubTab: 'connections',
    implemented: true,
    columns: [
      col('id', 'id', 'id', ['id'], { renderType: 'id', width: 130 }),
      col('canonical_id', 'canonical_id', 'canonical_id', ['canonical_id'], { renderType: 'canonical_id', width: 200 }),
      col('name_en', 'name_en（英文名）', 'name_en', ['name_en'], { enrichable: true }),
      col('name_cn', 'name_cn（中文名）', 'name_cn', ['name_cn'], { enrichable: true }),
      col('source_region_id', 'source_region_id（起始脑区）', 'source_region_id', ['source_region_candidate_id', 'source_region_final_id', 'source_region_id'], { required: true, renderType: 'id' }),
      col('source_region_name', 'source_region_name（起始脑区名）', 'source_region_name', ['source_region_name_cn', 'source_region_name_en'], { renderType: 'text' }),
      col('target_region_id', 'target_region_id（目标脑区）', 'target_region_id', ['target_region_candidate_id', 'target_region_final_id', 'target_region_id'], { required: true, renderType: 'id' }),
      col('target_region_name', 'target_region_name（目标脑区名）', 'target_region_name', ['target_region_name_cn', 'target_region_name_en'], { renderType: 'text' }),
      col('projection_type', 'projection_type（投射类型）', 'projection_type', ['connection_type', 'projection_type'], { required: true }),
      col('directionality', 'directionality（方向性）', 'directionality', ['directionality'], { enrichable: true }),
      col('strength_score', 'strength_score（强度）', 'strength_score', ['strength', 'strength_score'], { enrichable: true }),
      col('confidence_score', 'confidence_score（置信度）', 'confidence_score', ['confidence', 'confidence_score'], { renderType: 'confidence', enrichable: true }),
      col('evidence_level', 'evidence_level（证据级别）', 'evidence_level', ['evidence_level']),
      col('description', 'description（描述）', 'description', ['description', 'evidence_text'], { enrichable: true }),
      col('remark', 'remark（备注）', 'remark', ['remark']),
      col('attributes', 'attributes（属性）', 'attributes', ['attributes', 'raw_payload_json'], { renderType: 'json' }),
      col('source_db', 'source_db（来源库）', 'source_db', ['source_atlas', 'source_db']),
      col('status', 'status（状态）', 'status', ['status'], { renderType: 'status' }),
      col('data_source_id', 'data_source_id', 'data_source_id', ['data_source_id', 'resource_id'], { renderType: 'id' }),
      col('primary_evidence_id', 'primary_evidence_id', 'primary_evidence_id', ['llm_item_id', 'primary_evidence_id'], { renderType: 'id' }),
      col('external_code', 'external_code', 'external_code', ['external_code']),
      col('species_id', 'species_id', 'species_id', ['species_id']),
      col('created_at', 'created_at', 'created_at', ['created_at'], { renderType: 'date' }),
      col('updated_at', 'updated_at', 'updated_at', ['updated_at'], { renderType: 'date' }),
      ...GOVERNANCE,
    ],
  },

  // ─── macro_clinical.projection_function ─────────────────────────────────────
  {
    targetType: 'projection_function',
    label: 'Projection Function',
    mirrorTable: 'mirror_projection_functions',
    finalTable: 'projection_function',
    formalSchema: 'macro_clinical',
    formalQualifiedName: 'macro_clinical.projection_function',
    dataCenterTab: 'macro',
    dataCenterSubTab: 'projection_functions',
    implemented: true,
    columns: [
      col('id', 'id', 'id', ['id'], { renderType: 'id', width: 130 }),
      col('projection_id', 'projection_id', 'projection_id', ['projection_id'], { renderType: 'id', required: true }),
      col('function_term_en', 'function_term_en（功能术语英文）', 'function_term_en', ['function_term', 'function_term_en', 'function_label'], { required: true, enrichable: true }),
      col('function_term_cn', 'function_term_cn（功能术语中文）', 'function_term_cn', ['function_term_cn'], { enrichable: true }),
      col('function_domain', 'function_domain（功能域）', 'function_domain', ['function_category', 'function_domain'], { enrichable: true }),
      col('function_role', 'function_role（功能角色）', 'function_role', ['relation_type', 'function_role'], { enrichable: true }),
      col('effect_type', 'effect_type（效应类型）', 'effect_type', ['effect_type'], { enrichable: true }),
      col('confidence_score', 'confidence_score（置信度）', 'confidence_score', ['confidence', 'confidence_score'], { renderType: 'confidence', enrichable: true }),
      col('evidence_level', 'evidence_level（证据级别）', 'evidence_level', ['evidence_level']),
      col('description', 'description（描述）', 'description', ['description', 'evidence_text'], { enrichable: true }),
      col('remark', 'remark（备注）', 'remark', ['remark']),
      col('attributes', 'attributes（属性）', 'attributes', ['attributes', 'raw_payload_json'], { renderType: 'json' }),
      col('source_db', 'source_db（来源库）', 'source_db', ['source_atlas', 'source_db']),
      col('status', 'status（状态）', 'status', ['status'], { renderType: 'status' }),
      col('data_source_id', 'data_source_id', 'data_source_id', ['data_source_id', 'resource_id'], { renderType: 'id' }),
      col('primary_evidence_id', 'primary_evidence_id', 'primary_evidence_id', ['llm_item_id', 'primary_evidence_id'], { renderType: 'id' }),
      col('external_code', 'external_code', 'external_code', ['external_code']),
      col('created_at', 'created_at', 'created_at', ['created_at'], { renderType: 'date' }),
      col('updated_at', 'updated_at', 'updated_at', ['updated_at'], { renderType: 'date' }),
      ...GOVERNANCE,
    ],
  },

  // ─── macro_clinical.circuit ──────────────────────────────────────────────────
  {
    targetType: 'circuit',
    label: 'Circuit',
    mirrorTable: 'mirror_region_circuits',
    finalTable: 'circuit',
    formalSchema: 'macro_clinical',
    formalQualifiedName: 'macro_clinical.circuit',
    dataCenterTab: 'mirror',
    dataCenterSubTab: 'circuits',
    implemented: true,
    columns: [
      col('id', 'id', 'id', ['id'], { renderType: 'id', width: 130 }),
      col('canonical_id', 'canonical_id', 'canonical_id', ['canonical_id', 'circuit_name'], { renderType: 'canonical_id', width: 200 }),
      col('name_cn', 'name_cn（中文名）', 'name_cn', ['name_cn', 'circuit_name_cn'], { required: true, enrichable: true }),
      col('name_en', 'name_en（英文名）', 'name_en', ['circuit_name', 'name_en', 'name'], { required: true, enrichable: true }),
      col('circuit_class', 'circuit_class（回路类别）', 'circuit_class', ['circuit_type', 'circuit_class'], { required: true, enrichable: true }),
      col('canonical_start_region_id', 'canonical_start_region_id（起始端标准脑区）', 'canonical_start_region_id', ['canonical_start_region_id'], { enrichable: true, renderType: 'id' }),
      col('canonical_end_region_id', 'canonical_end_region_id（终止端标准脑区）', 'canonical_end_region_id', ['canonical_end_region_id'], { enrichable: true, renderType: 'id' }),
      col('description', 'description（描述）', 'description', ['description', 'function_association'], { enrichable: true }),
      col('remark', 'remark（备注）', 'remark', ['remark']),
      col('attributes', 'attributes（属性）', 'attributes', ['attributes', 'raw_payload_json'], { renderType: 'json' }),
      col('source_db', 'source_db（来源库）', 'source_db', ['source_atlas', 'source_db']),
      col('status', 'status（状态）', 'status', ['status'], { renderType: 'status' }),
      col('data_source_id', 'data_source_id', 'data_source_id', ['data_source_id', 'resource_id'], { renderType: 'id' }),
      col('primary_evidence_id', 'primary_evidence_id', 'primary_evidence_id', ['llm_item_id', 'primary_evidence_id'], { renderType: 'id' }),
      col('external_code', 'external_code', 'external_code', ['external_code']),
      col('species_id', 'species_id', 'species_id', ['species_id']),
      col('created_at', 'created_at', 'created_at', ['created_at'], { renderType: 'date' }),
      col('updated_at', 'updated_at', 'updated_at', ['updated_at'], { renderType: 'date' }),
      ...GOVERNANCE,
    ],
  },

  // ─── macro_clinical.circuit_step ─────────────────────────────────────────────
  {
    targetType: 'circuit_step',
    label: 'Circuit Step',
    mirrorTable: 'mirror_circuit_steps',
    finalTable: 'circuit_step',
    formalSchema: 'macro_clinical',
    formalQualifiedName: 'macro_clinical.circuit_step',
    dataCenterTab: 'macro',
    dataCenterSubTab: 'circuit_steps',
    implemented: true,
    columns: [
      col('id', 'id', 'id', ['id'], { renderType: 'id', width: 130 }),
      col('circuit_id', 'circuit_id', 'circuit_id', ['circuit_id'], { renderType: 'id', required: true }),
      col('step_no', 'step_no（步骤序号）', 'step_no', ['step_order', 'step_no'], { required: true }),
      col('step_name_en', 'step_name_en（步骤英文名）', 'step_name_en', ['step_name', 'step_name_en'], { required: true, enrichable: true }),
      col('step_name_cn', 'step_name_cn（步骤中文名）', 'step_name_cn', ['step_name_cn'], { enrichable: true }),
      col('region_id', 'region_id（关联脑区）', 'region_id', ['region_candidate_id', 'region_final_id', 'region_id'], { enrichable: true, renderType: 'id' }),
      col('projection_id', 'projection_id（关联投射）', 'projection_id', ['projection_id'], { renderType: 'id' }),
      col('role_in_circuit', 'role_in_circuit（回路角色）', 'role_in_circuit', ['role', 'role_in_circuit', 'step_role'], { enrichable: true }),
      col('description', 'description（描述）', 'description', ['description', 'evidence_text'], { enrichable: true }),
      col('remark', 'remark（备注）', 'remark', ['remark']),
      col('attributes', 'attributes（属性）', 'attributes', ['attributes', 'raw_payload_json'], { renderType: 'json' }),
      col('source_db', 'source_db（来源库）', 'source_db', ['source_atlas', 'source_db']),
      col('status', 'status（状态）', 'status', ['status'], { renderType: 'status' }),
      col('data_source_id', 'data_source_id', 'data_source_id', ['data_source_id', 'resource_id'], { renderType: 'id' }),
      col('primary_evidence_id', 'primary_evidence_id', 'primary_evidence_id', ['llm_item_id', 'primary_evidence_id'], { renderType: 'id' }),
      col('created_at', 'created_at', 'created_at', ['created_at'], { renderType: 'date' }),
      col('updated_at', 'updated_at', 'updated_at', ['updated_at'], { renderType: 'date' }),
      ...GOVERNANCE,
    ],
  },

  // ─── macro_clinical.circuit_function ─────────────────────────────────────────
  {
    targetType: 'circuit_function',
    label: 'Circuit Function',
    mirrorTable: 'mirror_circuit_functions',
    finalTable: 'circuit_function',
    formalSchema: 'macro_clinical',
    formalQualifiedName: 'macro_clinical.circuit_function',
    dataCenterTab: 'macro',
    dataCenterSubTab: 'circuit_functions',
    implemented: true,
    columns: [
      col('id', 'id', 'id', ['id'], { renderType: 'id' }),
      col('circuit_id', 'circuit_id', 'circuit_id', ['circuit_id'], { renderType: 'id', required: true }),
      col('function_term_en', 'function_term_en（功能术语英文）', 'function_term_en', ['function_term', 'function_term_en'], { required: true, enrichable: true }),
      col('function_term_cn', 'function_term_cn（功能术语中文）', 'function_term_cn', ['function_term_cn'], { enrichable: true }),
      col('function_domain', 'function_domain（功能域）', 'function_domain', ['function_category', 'function_domain'], { enrichable: true }),
      col('function_role', 'function_role（功能角色）', 'function_role', ['relation_type', 'function_role'], { enrichable: true }),
      col('effect_type', 'effect_type（效应类型）', 'effect_type', ['effect_type'], { enrichable: true }),
      col('confidence_score', 'confidence_score（置信度）', 'confidence_score', ['confidence', 'confidence_score'], { renderType: 'confidence', enrichable: true }),
      col('evidence_level', 'evidence_level（证据级别）', 'evidence_level', ['evidence_level'], { enrichable: true }),
      col('description', 'description（描述）', 'description', ['description', 'evidence_text'], { enrichable: true }),
      col('remark', 'remark（备注）', 'remark', ['remark']),
      col('attributes', 'attributes（属性）', 'attributes', ['attributes', 'raw_payload_json'], { renderType: 'json' }),
      col('source_db', 'source_db（来源库）', 'source_db', ['source_atlas', 'source_db']),
      col('status', 'status（状态）', 'status', ['status'], { renderType: 'status' }),
      col('data_source_id', 'data_source_id', 'data_source_id', ['data_source_id', 'resource_id'], { renderType: 'id' }),
      col('primary_evidence_id', 'primary_evidence_id', 'primary_evidence_id', ['llm_item_id', 'primary_evidence_id'], { renderType: 'id' }),
      col('external_code', 'external_code', 'external_code', ['external_code']),
      col('created_at', 'created_at', 'created_at', ['created_at'], { renderType: 'date' }),
      col('updated_at', 'updated_at', 'updated_at', ['updated_at'], { renderType: 'date' }),
      ...GOVERNANCE,
      gov('llm_run_id', 'llm_run_id', 'llm_run_id', ['llm_run_id'], { renderType: 'id' }),
      gov('llm_item_id', 'llm_item_id', 'llm_item_id', ['llm_item_id'], { renderType: 'id' }),
      gov('batch_id', 'batch_id', 'batch_id', ['batch_id'], { renderType: 'id' }),
      gov('resource_id', 'resource_id', 'resource_id', ['resource_id'], { renderType: 'id' }),
    ],
  },

  // ─── macro_clinical.region_function ──────────────────────────────────────────
  {
    targetType: 'region_function',
    label: 'Region Function',
    mirrorTable: 'mirror_region_functions',
    finalTable: 'region_function',
    formalSchema: 'macro_clinical',
    formalQualifiedName: 'macro_clinical.region_function',
    dataCenterTab: 'mirror',
    dataCenterSubTab: 'functions',
    implemented: true,
    columns: [
      col('id', 'id', 'id', ['id'], { renderType: 'id', width: 130 }),
      col('region_id', 'region_id（脑区）', 'region_id', ['region_candidate_id', 'region_final_id', 'region_id'], { required: true, renderType: 'id' }),
      col('function_term_en', 'function_term_en（功能术语英文）', 'function_term_en', ['function_term', 'function_term_en', 'function_label'], { required: true, enrichable: true }),
      col('function_term_cn', 'function_term_cn（功能术语中文）', 'function_term_cn', ['function_term_cn'], { enrichable: true }),
      col('function_domain', 'function_domain（功能域）', 'function_domain', ['function_category', 'function_domain'], { enrichable: true }),
      col('confidence_score', 'confidence_score（置信度）', 'confidence_score', ['confidence', 'confidence_score'], { renderType: 'confidence', enrichable: true }),
      col('evidence_level', 'evidence_level（证据级别）', 'evidence_level', ['evidence_level']),
      col('description', 'description（描述）', 'description', ['description', 'evidence_text'], { enrichable: true }),
      col('remark', 'remark（备注）', 'remark', ['remark']),
      col('attributes', 'attributes（属性）', 'attributes', ['attributes', 'raw_payload_json'], { renderType: 'json' }),
      col('source_db', 'source_db（来源库）', 'source_db', ['source_atlas', 'source_db']),
      col('status', 'status（状态）', 'status', ['status'], { renderType: 'status' }),
      col('data_source_id', 'data_source_id', 'data_source_id', ['data_source_id', 'resource_id'], { renderType: 'id' }),
      col('primary_evidence_id', 'primary_evidence_id', 'primary_evidence_id', ['llm_item_id', 'primary_evidence_id'], { renderType: 'id' }),
      col('external_code', 'external_code', 'external_code', ['external_code']),
      col('created_at', 'created_at', 'created_at', ['created_at'], { renderType: 'date' }),
      col('updated_at', 'updated_at', 'updated_at', ['updated_at'], { renderType: 'date' }),
      ...GOVERNANCE,
    ],
  },

  // ─── Mirror-only: circuit_projection_membership (no formal counterpart in macro_clinical) ──
  {
    targetType: 'circuit_projection_membership',
    label: 'Circuit–Projection Membership',
    mirrorTable: 'mirror_circuit_projection_memberships',
    finalTable: 'circuit_projection_membership',
    formalSchema: '',
    formalQualifiedName: '',
    dataCenterTab: 'macro',
    dataCenterSubTab: 'memberships',
    implemented: true,
    columns: [
      col('id', 'id', 'id', ['id'], { renderType: 'id', width: 130 }),
      col('circuit_id', 'circuit_id', 'circuit_id', ['circuit_id'], { renderType: 'id', required: true }),
      col('projection_id', 'projection_id', 'projection_id', ['projection_id'], { renderType: 'id', required: true }),
      col('source_step_id', 'source_step_id', 'source_step_id', ['source_step_id'], { renderType: 'id' }),
      col('target_step_id', 'target_step_id', 'target_step_id', ['target_step_id'], { renderType: 'id' }),
      col('role_in_circuit', 'role_in_circuit（回路角色）', 'role_in_circuit', ['role_in_circuit', 'membership_role'], { enrichable: true }),
      col('confidence', 'confidence（置信度）', 'confidence_score', ['confidence', 'confidence_score'], { renderType: 'confidence', enrichable: true }),
      col('source_method', 'source_method', 'source_method', ['source_method']),
      col('verification_status', 'verification_status', 'verification_status', ['verification_status'], { renderType: 'status' }),
      col('cross_validation_status', 'cross_validation_status', 'cross_validation_status', ['cross_validation_status'], { derived: true, renderType: 'status' }),
      col('dual_model_status', 'dual_model_status', 'dual_model_status', ['dual_model_status'], { derived: true, renderType: 'status' }),
      col('created_at', 'created_at', 'created_at', ['created_at'], { renderType: 'date' }),
      ...GOVERNANCE,
    ],
  },

  // ─── Mirror-only: triple ──────────────────────────────────────────────────────
  {
    targetType: 'triple',
    label: 'Triple',
    mirrorTable: 'mirror_kg_triples',
    finalTable: 'triple',
    formalSchema: '',
    formalQualifiedName: '',
    dataCenterTab: 'mirror',
    dataCenterSubTab: 'triples',
    implemented: true,
    columns: [
      col('id', 'id', 'id', ['id'], { renderType: 'id', width: 130 }),
      col('subject_type', 'subject_type', 'subject_type', ['subject_type'], { required: true }),
      col('subject_id', 'subject_id', 'subject_id', ['subject_id'], { renderType: 'id' }),
      col('subject_label', 'subject_label', 'subject_label', ['subject_label'], { required: true }),
      col('predicate', 'predicate', 'predicate', ['predicate'], { required: true }),
      col('object_type', 'object_type', 'object_type', ['object_type'], { required: true }),
      col('object_id', 'object_id', 'object_id', ['object_id'], { renderType: 'id' }),
      col('object_label', 'object_label', 'object_label', ['object_label'], { required: true }),
      col('confidence', 'confidence（置信度）', 'confidence', ['confidence'], { renderType: 'confidence', enrichable: true }),
      col('evidence_count', 'evidence_count', 'evidence_count', ['evidence_count'], { derived: true }),
      col('created_at', 'created_at', 'created_at', ['created_at'], { renderType: 'date' }),
      ...GOVERNANCE,
    ],
  },

  // ─── Mirror-only: evidence ────────────────────────────────────────────────────
  {
    targetType: 'evidence',
    label: 'Evidence',
    mirrorTable: 'mirror_evidence_records',
    finalTable: 'evidence',
    formalSchema: '',
    formalQualifiedName: '',
    dataCenterTab: 'mirror',
    dataCenterSubTab: 'evidence',
    implemented: true,
    columns: [
      col('id', 'id', 'id', ['id'], { renderType: 'id', width: 130 }),
      col('evidence_target_type', 'evidence_target_type', 'evidence_target_type', ['evidence_target_type', 'target_type'], { required: true }),
      col('evidence_target_id', 'evidence_target_id', 'evidence_target_id', ['evidence_target_id', 'target_id'], { renderType: 'id', required: true }),
      col('evidence_text', 'evidence_text（证据文本）', 'evidence_text', ['evidence_text'], { required: true }),
      col('source_document_id', 'source_document_id', 'source_document_id', ['source_document_id', 'source_document'], { enrichable: true }),
      col('source_reference_text', 'source_reference_text', 'source_reference_text', ['source_reference_text', 'source_location'], { enrichable: true }),
      col('confidence', 'confidence（置信度）', 'confidence', ['confidence'], { renderType: 'confidence', enrichable: true }),
      col('llm_run_id', 'llm_run_id', 'llm_run_id', ['llm_run_id'], { renderType: 'id' }),
      gov('mirror_status', 'mirror_status', 'mirror_status', ['mirror_status'], { renderType: 'status' }),
      gov('review_status', 'review_status', 'review_status', ['review_status'], { renderType: 'status' }),
      gov('provenance', 'provenance', 'provenance', [], { derived: true }),
      col('created_at', 'created_at', 'created_at', ['created_at'], { renderType: 'date' }),
    ],
  },

  // ─── Candidate region ─────────────────────────────────────────────────────────
  {
    targetType: 'candidate_region',
    label: 'Candidate Brain Region',
    mirrorTable: 'candidate_brain_regions',
    finalTable: 'region',
    formalSchema: 'macro_clinical',
    formalQualifiedName: 'macro_clinical.region',
    dataCenterTab: 'candidates',
    implemented: true,
    columns: [
      col('id', 'id', 'id', ['id'], { renderType: 'id' }),
      col('en_name', 'name_en（英文名）', 'name_en', ['en_name', 'name_en'], { required: true }),
      col('cn_name', 'name_cn（中文名）', 'name_cn', ['cn_name', 'name_cn'], { enrichable: true }),
      col('std_name', 'std_name', 'std_name', ['std_name'], { enrichable: true }),
      col('laterality', 'laterality', 'laterality', ['laterality'], { enrichable: true }),
      col('source_atlas', 'source_db（来源库）', 'source_db', ['source_atlas', 'source_db']),
      col('granularity_level', 'granularity_level', 'granularity_level', ['granularity_level']),
      col('candidate_status', 'status（状态）', 'status', ['candidate_status', 'status'], { renderType: 'status' }),
      col('created_at', 'created_at', 'created_at', ['created_at'], { renderType: 'date' }),
    ],
  },
]

export const FORMAL_FIELD_MAPPINGS: FormalFieldMapping[] = BASE_MAPPINGS

export const FORMAL_OBJECT_MAPPINGS: FormalObjectMapping[] = BASE_MAPPINGS.map(withLegacyLists)

function payloadOf(item: Record<string, unknown>): Record<string, unknown> | undefined {
  const raw = item.normalized_payload_json ?? item.raw_payload_json
  return raw && typeof raw === 'object' && !Array.isArray(raw) ? (raw as Record<string, unknown>) : undefined
}

function resolveDerived(column: FormalFieldColumn, item: Record<string, unknown>): unknown {
  const payload = payloadOf(item)
  switch (column.key) {
    case 'source_region_id':
      return payload?.source_region_id ?? item.source_region_candidate_id ?? item.source_region_final_id
    case 'target_region_id':
      return payload?.target_region_id ?? item.target_region_candidate_id ?? item.target_region_final_id
    case 'region_id':
      return item.region_candidate_id ?? item.region_final_id
    case 'name_en':
      return item.name_en ?? item.circuit_name ?? payload?.name_en ?? payload?.circuit_name
    case 'name_cn':
      return item.name_cn ?? item.name_zh ?? payload?.name_cn
    case 'validation_status':
      return item.validation_status ?? payload?.validation_status
    case 'cross_validation_status':
      return item.cross_validation_status ?? payload?.cross_validation_status
    case 'dual_model_status':
      return item.dual_model_status ?? payload?.dual_model_status
    case 'evidence_count':
      if (item.evidence_count != null) return item.evidence_count
      return item.evidence_text ? 1 : null
    case 'provenance': {
      const ts = typeof item.created_at === 'string'
        ? item.created_at.slice(0, 16).replace('T', ' ')
        : ''
      const parts: string[] = []
      if (ts) parts.push(ts)
      if (item.llm_run_id) parts.push(`run:${(item.llm_run_id as string).slice(0, 8)}`)
      if (item.batch_id) parts.push(`batch:${(item.batch_id as string).slice(0, 8)}`)
      if (item.source_atlas) parts.push(item.source_atlas as string)
      if (item.created_by) parts.push(`by:${item.created_by}`)
      return parts.length > 0 ? parts.join(' · ') : null
    }
    default:
      return undefined
  }
}

export function isFieldValueEmpty(value: unknown): boolean {
  if (value == null || value === '') return true
  if (typeof value === 'string' && value.trim() === '') return true
  if (Array.isArray(value) && value.length === 0) return true
  if (typeof value === 'object' && !Array.isArray(value) && Object.keys(value as object).length === 0) return true
  return false
}

function readOverlayMap(container: unknown): Record<string, unknown> | undefined {
  if (!container || typeof container !== 'object' || Array.isArray(container)) return undefined
  const c = container as Record<string, unknown>
  const nested = c['formal_field_overlay'] ?? c['formalFieldOverlay']
  if (nested && typeof nested === 'object' && !Array.isArray(nested)) {
    return nested as Record<string, unknown>
  }
  return undefined
}

function readOverlayField(container: unknown, fieldKey: string): unknown {
  const overlay = readOverlayMap(container)
  if (overlay && fieldKey in overlay) {
    return overlay[fieldKey]
  }
  return undefined
}

/** Mirror columns that must not fill a different formal field. */
function isForbiddenMirrorCandidate(formalField: string, mirrorField: string): boolean {
  if (formalField === 'name_cn') {
    return mirrorField === 'circuit_name' || mirrorField === 'function_association' || mirrorField === 'circuit_type'
  }
  if (formalField === 'name_en' && mirrorField === 'name_cn') return true
  if (formalField === 'step_name_cn' && (mirrorField === 'step_name' || mirrorField === 'step_order')) return true
  if (formalField === 'function_term_cn' && mirrorField === 'function_term') return true
  return false
}

function readOverlayFromItem(item: Record<string, unknown>, fieldKey: string): unknown {
  const local = item.__fieldCompletionOverlay
  if (local && typeof local === 'object' && !Array.isArray(local)) {
    const flat = local as Record<string, unknown>
    if (fieldKey in flat && !isFieldValueEmpty(flat[fieldKey])) {
      return flat[fieldKey]
    }
  }

  const containers = [
    item.attributes,
    item.formal_field_overlay,
    item.formalFieldOverlay,
    item.normalized_payload_json,
    item.raw_payload_json,
  ]
  for (const container of containers) {
    const v = readOverlayField(container, fieldKey)
    if (!isFieldValueEmpty(v)) return v
  }
  return undefined
}

export function isPresentFieldValue(value: unknown): boolean {
  return !isFieldValueEmpty(value)
}

export function getFieldValue(
  item: Record<string, unknown>,
  column: FormalFieldColumn,
  _mapping?: FormalFieldMapping,
): unknown {
  const formalField = column.finalField

  // 1. Direct formal field on row
  const direct = item[formalField]
  if (isPresentFieldValue(direct)) return direct

  // 2–6, 8 + normalized_payload: overlay by formalField
  const overlayFormal = readOverlayFromItem(item, formalField)
  if (isPresentFieldValue(overlayFormal)) return overlayFormal

  // 7–8. Overlay by column.key when distinct from formalField
  if (column.key !== formalField) {
    const overlayKey = readOverlayFromItem(item, column.key)
    if (isPresentFieldValue(overlayKey)) return overlayKey
  }

  // 9. Mirror ORM candidates (never override formal overlay)
  for (const mirrorField of column.mirrorFieldCandidates) {
    if (isForbiddenMirrorCandidate(formalField, mirrorField)) continue
    const v = item[mirrorField]
    if (isPresentFieldValue(v)) return v
  }

  if (column.derived) {
    const derived = resolveDerived(column, item)
    if (isPresentFieldValue(derived)) return derived
  }

  return null
}

export function isValueFromOverlay(
  item: Record<string, unknown>,
  column: FormalFieldColumn,
): boolean {
  const formalField = column.finalField
  const resolved = getFieldValue(item, column)
  if (!isPresentFieldValue(resolved)) return false

  const direct = item[formalField]
  if (isPresentFieldValue(direct) && direct === resolved) return false

  for (const mirrorField of column.mirrorFieldCandidates) {
    if (isForbiddenMirrorCandidate(formalField, mirrorField)) continue
    const v = item[mirrorField]
    if (isPresentFieldValue(v) && v === resolved) return false
  }

  const local = item.__fieldCompletionOverlay
  if (local && typeof local === 'object' && !Array.isArray(local)) {
    const flat = local as Record<string, unknown>
    if (formalField in flat && flat[formalField] === resolved) return true
    if (column.key !== formalField && column.key in flat && flat[column.key] === resolved) return true
  }

  return isPresentFieldValue(readOverlayFromItem(item, formalField))
    || (column.key !== formalField && isPresentFieldValue(readOverlayFromItem(item, column.key)))
}

export function computeMissingFields(
  item: Record<string, unknown>,
  mapping: FormalFieldMapping,
): string[] {
  const missing: string[] = []
  for (const column of mapping.columns) {
    // Check ALL enrichable fields (not just required), skip governance
    if (!column.enrichable) continue
    if (column.group === 'governance') continue
    const value = getFieldValue(item, column)
    if (isFieldValueEmpty(value)) missing.push(column.finalField)
  }
  return missing
}

export function computeCompleteness(
  items: Record<string, unknown>[],
  mapping: FormalFieldMapping,
): number {
  const enrichableCols = mapping.columns.filter(c => c.enrichable && c.group !== 'governance')
  if (enrichableCols.length === 0 || items.length === 0) return 100
  let filled = 0
  let total = 0
  for (const item of items) {
    for (const col of enrichableCols) {
      total += 1
      if (!isFieldValueEmpty(getFieldValue(item, col))) filled += 1
    }
  }
  return Math.round((filled / total) * 100)
}

export function getFormalFieldMapping(type: FormalObjectType): FormalFieldMapping | undefined {
  return FORMAL_FIELD_MAPPINGS.find(m => m.targetType === type)
}

export function getFormalMapping(targetType: FormalObjectType): FormalObjectMapping | undefined {
  return FORMAL_OBJECT_MAPPINGS.find(m => m.targetType === targetType)
}

export function getCompletionEligibleFields(targetType: FormalObjectType): string[] {
  const m = getFormalFieldMapping(targetType)
  if (!m || !m.implemented) return []
  return m.columns.filter(c => c.enrichable && c.group !== 'governance').map(c => c.key)
}

/** @deprecated use computeMissingFields(...).length */
export function countMissingFields(
  targetType: FormalObjectType,
  row: Record<string, unknown>,
): number {
  const m = getFormalFieldMapping(targetType)
  if (!m) return 0
  return computeMissingFields(row, m).length
}

export function getMappingBySubTab(
  tab: 'mirror' | 'macro',
  subTab: string,
): FormalFieldMapping | undefined {
  return FORMAL_FIELD_MAPPINGS.find(
    m => m.dataCenterTab === tab && m.dataCenterSubTab === subTab,
  )
}
