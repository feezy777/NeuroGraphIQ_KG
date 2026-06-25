import { useMemo, useState } from 'react'
import { useI18n } from '../../../i18n-context'
import type { LlmProviderInfo, LlmTaskTypeInfo } from '../../../api/endpoints'
import {
  CANDIDATE_BULK_TASKS,
  MACRO_CLINICAL_TASKS,
  PLANNED_TASKS,
  COMPOSITE_TASKS,
  isCompositeTask,
  isCandidateBulkTask,
  type CompositeTaskId,
} from '../llmDataFirstTypes'

// Advanced single-step tasks (moved out of main flow)
const ADVANCED_SINGLE_TASKS = [
  'region_field_completion',
  'same_granularity_connection_completion',
  'same_granularity_function_completion',
  'same_granularity_circuit_completion',
  'circuit_to_steps',
  'circuit_steps_to_projections',
  'projection_to_functions',
  'projections_to_circuits',
  'dual_model_verification',
]

interface Props {
  taskTypes: LlmTaskTypeInfo[]
  selectedTask: string
  onTaskChange: (task: string) => void
  providers: LlmProviderInfo[]
  provider: string
  onProviderChange: (v: string) => void
  modelName: string
  onModelChange: (v: string) => void
  dryRun: boolean
  onDryRunChange: (v: boolean) => void
  selectedCount: number
  onBatchExtract: () => void
  onOpenMacroBatch?: () => void
  batchDisabled?: boolean
  batchLoading?: boolean
}

const COMPOSITE_CHIP_LABELS: Record<CompositeTaskId, string> = {
  composite_connection_with_function: 'llm.composite.connectionWithFunction',
  composite_circuit_with_function_and_steps: 'llm.composite.circuitWithFunctionAndSteps',
  composite_triple_generation: 'llm.composite.tripleGeneration',
}

export function LlmTaskToolbar({
  taskTypes,
  selectedTask,
  onTaskChange,
  providers,
  provider,
  onProviderChange,
  modelName,
  onModelChange,
  dryRun,
  onDryRunChange,
  selectedCount,
  onBatchExtract,
  onOpenMacroBatch,
  batchDisabled,
  batchLoading,
}: Props) {
  const { t } = useI18n()
  const [showAdvanced, setShowAdvanced] = useState(false)

  const implemented = useMemo(
    () => new Set(taskTypes.filter(tt => tt.implemented).map(tt => tt.task_type)),
    [taskTypes],
  )

  const batchLabel = useMemo(() => {
    if (selectedTask === 'composite_connection_with_function') return t('llm.composite.batchConnectionWithFunction')
    if (selectedTask === 'composite_circuit_with_function_and_steps') return t('llm.composite.batchCircuitWithFunctionAndSteps')
    if (selectedTask === 'composite_triple_generation') return t('llm.composite.generateTriples')
    if (MACRO_CLINICAL_TASKS.includes(selectedTask)) return t('llm.dataFirst.openMacroBatch')
    if (selectedTask === 'region_field_completion') return t('llm.dataFirst.batchRegionCompletion')
    if (selectedTask === 'same_granularity_connection_completion') return t('llm.composite.singleStepConnection')
    if (selectedTask === 'same_granularity_function_completion') return t('llm.composite.singleStepFunction')
    if (selectedTask === 'same_granularity_circuit_completion') return t('llm.composite.singleStepCircuit')
    if (selectedTask === 'circuit_to_steps') return t('llm.composite.singleStepCircuitSteps')
    if (selectedTask === 'projection_to_functions') return t('llm.composite.singleStepProjectionFunction')
    return t('llm.dataFirst.batchExtract')
  }, [selectedTask, t])

  const currentProvider = providers.find(p => p.name === provider)
  const isMacroTask = MACRO_CLINICAL_TASKS.includes(selectedTask)
  const isComposite = isCompositeTask(selectedTask)
  const isCandidate = isCandidateBulkTask(selectedTask)
  const canBatch = isCandidate || isMacroTask || isComposite
  const needsSelection = isCandidate || isComposite
  const batchDisabledFinal = batchDisabled || !canBatch || (needsSelection && selectedTask !== 'composite_triple_generation' && selectedCount === 0)

  const handleBatch = () => {
    if (isMacroTask) onOpenMacroBatch?.()
    else onBatchExtract()
  }

  return (
    <div className="llm-task-toolbar card">
      <div className="llm-task-toolbar-row">
        {/* Provider */}
        <label className="llm-task-field">
          <span className="llm-field-label">Provider</span>
          <select className="llm-select" value={provider} onChange={e => onProviderChange(e.target.value)}>
            {providers.map(p => (
              <option key={p.name} value={p.name}>{p.name}</option>
            ))}
          </select>
        </label>

        {/* Model */}
        <label className="llm-task-field llm-task-field-grow">
          <span className="llm-field-label">Model</span>
          <input
            className="llm-input"
            value={modelName}
            onChange={e => onModelChange(e.target.value)}
            placeholder={currentProvider?.default_model ?? 'model'}
          />
        </label>

        {/* Dry run */}
        <label className="llm-dry-run-toggle">
          <input type="checkbox" checked={dryRun} onChange={e => onDryRunChange(e.target.checked)} />
          <span>{t('llm.dataFirst.bulkDryRun')}</span>
        </label>

        {/* Batch execute button */}
        <button
          type="button"
          className="llm-btn llm-btn-primary llm-bulk-run-button"
          disabled={batchDisabledFinal}
          onClick={handleBatch}
        >
          {batchLoading ? '…' : batchLabel}
          {needsSelection && selectedCount > 0 ? ` (${selectedCount})` : ''}
        </button>
      </div>

      {/* Main workflow chips */}
      {/* Task type: quick cards above, all tasks in advanced panel below */}
      <div className="llm-composite-task-row">
        <span className="llm-composite-main-label">快速操作卡（上方）· 全部任务（展开↓）</span>
        <button
          type="button"
          className="llm-composite-advanced-toggle llm-btn llm-btn-ghost"
          onClick={() => setShowAdvanced(v => !v)}
        >
          {showAdvanced ? t('llm.composite.hideAdvanced') : t('llm.composite.showAdvanced')} {showAdvanced ? '▲' : '▼'}
        </button>
      </div>

      {/* Advanced single-step panel */}
      {showAdvanced && (
        <div className="llm-composite-advanced-panel">
          <span className="llm-composite-advanced-label">{t('llm.composite.advancedSingleStep')}</span>
          <div style={{ display: 'flex', flexWrap: 'wrap', gap: 6, marginTop: 6 }}>
            {/* Task type select for precise control */}
            <select
              className="llm-select"
              value={ADVANCED_SINGLE_TASKS.includes(selectedTask) ? selectedTask : ''}
              onChange={e => { if (e.target.value) onTaskChange(e.target.value) }}
            >
              <option value="" disabled>{t('llm.dataFirst.taskType')}</option>
              <option value="" disabled>── {t('llm.composite.advancedSingleStep')} ──</option>
              {ADVANCED_SINGLE_TASKS.map(tt => (
                <option key={tt} value={tt} disabled={!implemented.has(tt)}>
                  {tt}{implemented.has(tt) ? '' : ' (N/A)'}
                </option>
              ))}
              <option value="" disabled>── {t('llm.composite.planned')} ──</option>
              {PLANNED_TASKS.map(tt => (
                <option key={tt} value={tt} disabled>{tt} (planned)</option>
              ))}
              <option value="" disabled>── Macro Clinical ──</option>
              {MACRO_CLINICAL_TASKS.map(tt => (
                <option key={tt} value={tt}>{tt}</option>
              ))}
            </select>

            {/* Quick chips for most common single-step tasks */}
            {ADVANCED_SINGLE_TASKS.slice(0, 5).map(tt => {
              const isImpl = implemented.has(tt)
              const isActive = selectedTask === tt
              return (
                <button
                  key={tt}
                  type="button"
                  className={[
                    'llm-task-chip',
                    isImpl ? 'llm-task-chip-implemented' : 'llm-task-chip-planned',
                    isActive ? 'llm-task-chip-active' : '',
                  ].filter(Boolean).join(' ')}
                  disabled={!isImpl}
                  onClick={() => onTaskChange(tt)}
                  title={tt}
                >
                  {tt.replace('same_granularity_', '').replace('_completion', '').replace('_extraction', '')}
                </button>
              )
            })}
          </div>
        </div>
      )}
    </div>
  )
}
