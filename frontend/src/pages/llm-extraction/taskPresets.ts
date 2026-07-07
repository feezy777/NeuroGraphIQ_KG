/**
 * Task Preset Registry — maps quick card buttons to extraction presets.
 * Shared between frontend and documented for backend sync.
 */

export interface TaskPreset {
  preset_id: string
  label: string
  input_pool_type: 'region_pool' | 'connection_pool'
  target: string
  prompt_template_key: string
  output_tables: string[]
  endpoint_type: 'field_or_composite' | 'composite_workflow' | 'circuit_extraction'
  pack_strategy?: string
  /** Disabled hint when tab doesn't match */
  disabledHint?: string
}

export const TASK_PRESETS: Record<string, TaskPreset> = {

  region_to_function: {
    preset_id: 'region_to_function',
    label: '脑区功能提取',
    input_pool_type: 'region_pool',
    target: 'region_function',
    prompt_template_key: 'region_function_extraction_v1',
    output_tables: ['mirror_region_functions'],
    endpoint_type: 'field_or_composite',
  },

  region_to_connection: {
    preset_id: 'region_to_connection',
    label: '根据脑区提取连接',
    input_pool_type: 'region_pool',
    target: 'connection',
    prompt_template_key: 'same_granularity_connection_completion_v1',
    output_tables: ['mirror_region_connections', 'mirror_evidence_records'],
    endpoint_type: 'composite_workflow',
  },

  region_to_circuit_steps_functions: {
    preset_id: 'region_to_circuit_steps_functions',
    label: '回路 + 步骤 + 功能',
    input_pool_type: 'region_pool',
    target: 'circuit_steps_functions',
    prompt_template_key: 'circuit_steps_functions_from_regions_v1',
    output_tables: ['mirror_region_circuits', 'mirror_circuit_steps', 'mirror_circuit_functions'],
    endpoint_type: 'circuit_extraction',
    pack_strategy: 'multi_round_region_shuffle_for_circuit',
  },

  connection_to_function: {
    preset_id: 'connection_to_function',
    label: '根据连接提取功能',
    input_pool_type: 'connection_pool',
    target: 'projection_function',
    prompt_template_key: 'projection_to_functions_v1',
    output_tables: ['mirror_projection_functions'],
    endpoint_type: 'composite_workflow',
  },

  connection_to_circuit: {
    preset_id: 'connection_to_circuit',
    label: '根据连接提取回路',
    input_pool_type: 'connection_pool',
    target: 'circuit',
    prompt_template_key: 'circuit_extraction_from_connections_v1',
    output_tables: ['mirror_region_circuits', 'mirror_circuit_steps', 'mirror_circuit_functions'],
    endpoint_type: 'circuit_extraction',
    pack_strategy: 'graph_aware_connection_pack_for_circuit',
  },
}

/** Map (activeTab × cardKey) → preset_id, null = disabled */
export const QUICK_CARD_PRESET_MAP: Record<string, Record<string, string | null>> = {
  region: {
    fn: 'region_to_function',
    conn: 'region_to_connection',
    circuit: 'region_to_circuit_steps_functions',
  },
  connection: {
    fn: null,
    conn: 'connection_to_function',
    circuit: 'connection_to_circuit',
  },
}

/** Build preset log payload */
export function buildPresetLogPayload(
  activeTab: string,
  preset: TaskPreset,
  extra: { pool_id?: string | null; candidate_count?: number; connection_count?: number } = {},
) {
  return {
    activeTab,
    preset_id: preset.preset_id,
    input_pool_type: preset.input_pool_type,
    target: preset.target,
    prompt_template_key: preset.prompt_template_key,
    output_tables: preset.output_tables,
    endpoint_type: preset.endpoint_type,
    pool_id: extra.pool_id ?? null,
    candidate_count: extra.candidate_count ?? 0,
    connection_count: extra.connection_count ?? 0,
  }
}
