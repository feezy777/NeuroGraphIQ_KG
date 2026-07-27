/**
 * Single source of truth for all background task types.
 * Every consumer (Page, Dropdown, Modal, CancelDialog) references this registry
 * instead of inlining type→icon / type→label / type→cancel mappings.
 */
import type { BgTask } from '../hooks/useBackgroundTasks'
import {
  cancelFieldCompletionRun,
  cancelCompositeWorkflow,
  cancelCircuitExtractionRun,
  cancelCircuitConnectionExtractionRun,
  cancelMolecularCircuitRun,
  pauseCompositeWorkflow,
  pauseMolecularCircuitRun,
} from '../api/endpoints'

export interface TaskTypeDef {
  type: BgTask['type']
  icon: string
  label: (task: BgTask) => string
  cancel: (id: string) => Promise<unknown>
  pause?: (id: string) => Promise<unknown>
  /** Some types don't support pause */
  canPause: boolean
}

const REGISTRY: Record<BgTask['type'], TaskTypeDef> = {
  composite_workflow: {
    type: 'composite_workflow',
    icon: '🔗',
    label: (t) => `LLM 提取 · ${t.targetType ?? ''}`,
    cancel: (id) => cancelCompositeWorkflow(id),
    pause: (id) => pauseCompositeWorkflow(id),
    canPause: true,
  },
  field_completion: {
    type: 'field_completion',
    icon: '🔧',
    label: (t) => `字段补全 · ${t.targetType ?? ''}`,
    cancel: (id) => cancelFieldCompletionRun(id),
    canPause: false,
  },
  circuit_extraction: {
    type: 'circuit_extraction',
    icon: '⭕',
    label: (t) => `回路提取 · ${t.modelName ?? t.provider ?? 'run'}`,
    cancel: (id) => cancelCircuitExtractionRun(id),
    canPause: false,
  },
  circuit_connection_extraction: {
    type: 'circuit_connection_extraction',
    icon: '🔄',
    label: (t) => `回路→连接提取 · ${t.targetType ?? ''}`,
    cancel: (id) => cancelCircuitConnectionExtractionRun(id),
    canPause: false,
  },
  molecular_circuit: {
    type: 'molecular_circuit',
    icon: '🧬',
    label: (t) => `Molecular 回路 · ${t.modelName ?? t.provider ?? 'run'}`,
    cancel: (id) => cancelMolecularCircuitRun(id),
    pause: (id) => pauseMolecularCircuitRun(id),
    canPause: true,
  },
}

/** Look up a task type definition. Falls back to composite_workflow. */
export function getTaskDef(type: string): TaskTypeDef {
  return REGISTRY[type as BgTask['type']] ?? REGISTRY.composite_workflow
}

/** Convenience: cancel any task by ID + type. */
export async function cancelTask(task: BgTask): Promise<void> {
  await REGISTRY[task.type]?.cancel(task.id)
}

/** Convenience: pause any task by ID + type (no-op if unsupported). */
export async function pauseTask(task: BgTask): Promise<void> {
  await REGISTRY[task.type]?.pause?.(task.id)
}

/** All task type keys for filter UIs. */
export const TASK_TYPE_OPTIONS: { key: BgTask['type']; label: string }[] = [
  { key: 'composite_workflow', label: 'LLM 提取' },
  { key: 'field_completion', label: '字段补全' },
  { key: 'circuit_extraction', label: '回路提取' },
  { key: 'molecular_circuit', label: 'Molecular 回路' },
  { key: 'circuit_connection_extraction', label: '回路→连接提取' },
]
