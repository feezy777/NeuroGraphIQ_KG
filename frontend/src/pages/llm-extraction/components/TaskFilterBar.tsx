import { useState, useEffect, useCallback, useMemo } from 'react'
import type { LlmExtractionRun } from '../../../api/endpoints'
import { useData } from '../../../hooks/useData'
import { useI18n } from '../../../i18n-context'

export interface TaskFilterValue {
  taskType: string
  runId: string
  search: string
}

interface Props {
  /** Function to fetch available runs (already scoped to a task type or all) */
  fetchRuns: (params: Record<string, unknown>) => Promise<{ items: LlmExtractionRun[]; total: number }>
  /** Current filter value */
  value: TaskFilterValue
  /** Called when any filter changes */
  onChange: (value: TaskFilterValue) => void
}

/** Extracts unique task_types from runs */
function uniqueTaskTypes(runs: LlmExtractionRun[]): string[] {
  const seen = new Set<string>()
  for (const r of runs) {
    if (r.task_type) seen.add(r.task_type)
  }
  return Array.from(seen).sort()
}

/** Human-readable label for internal task_type values */
function taskTypeLabel(tt: string): string {
  const map: Record<string, string> = {
    same_granularity_function: '脑区功能',
    same_granularity_connection: '同粒度连接',
    connection_with_function: '连接+功能',
    same_granularity_circuit: '回路',
    circuit_to_steps: '回路→步骤',
    circuit_to_functions: '回路→功能',
    circuit_with_function_steps: '回路+步骤+功能',
    steps_to_projections: '步骤→投影',
    projection_to_functions: '投影→功能',
    projections_to_circuits: '投影→回路',
    circuit_projection_cross_validation: '交叉验证',
    dual_model_verification: '双模型验证',
    triple_generation: '三元组生成',
    region_field_completion: '脑区补全',
    universal_field_completion: '字段补全',
  }
  return map[tt] ?? tt
}

export function TaskFilterBar({ fetchRuns, value, onChange }: Props) {
  const { t } = useI18n()

  // Fetch all runs (limit 200 to collect task types)
  const { data: runsData } = useData(
    () => fetchRuns({ limit: 200 }),
    [],
  )

  const runs = runsData?.items ?? []

  // Available task types from the fetched runs
  const taskTypes = useMemo(() => uniqueTaskTypes(runs), [runs])

  // Runs filtered by selected task type
  const filteredRuns = useMemo(() => {
    if (!value.taskType) return runs
    return runs.filter(r => r.task_type === value.taskType)
  }, [runs, value.taskType])

  function patch(partial: Partial<TaskFilterValue>) {
    // When task type changes, reset run
    if ('taskType' in partial && partial.taskType !== value.taskType) {
      onChange({ ...value, ...partial, runId: '' })
    } else {
      onChange({ ...value, ...partial })
    }
  }

  return (
    <div className="filter-bar" style={{ padding: '8px 0', flexWrap: 'wrap', gap: 6, fontSize: 13 }}>
      {/* Task type dropdown */}
      <span className="filter-label">{t('extraction.filterTaskType')}:</span>
      <select
        className="filter-select"
        value={value.taskType}
        onChange={e => patch({ taskType: e.target.value })}
        style={{ minWidth: 150, fontSize: 13 }}
      >
        <option value="">{t('common.all')}</option>
        {taskTypes.map(tt => (
          <option key={tt} value={tt}>{taskTypeLabel(tt)}</option>
        ))}
      </select>

      {/* Run dropdown */}
      <span className="filter-label" style={{ marginLeft: 8 }}>{t('extraction.filterRun')}:</span>
      <select
        className="filter-select"
        value={value.runId}
        onChange={e => patch({ runId: e.target.value })}
        style={{ minWidth: 220, fontSize: 13 }}
        disabled={filteredRuns.length === 0}
      >
        <option value="">{t('common.all')}</option>
        {filteredRuns.map(r => (
          <option key={r.id} value={r.id}>
            {r.id.slice(0, 8)}… ({r.status}) {r.created_at?.slice(0, 10)}
          </option>
        ))}
      </select>

      {/* Search input */}
      <span className="filter-label" style={{ marginLeft: 8 }}>{t('common.search')}:</span>
      <input
        className="form-input"
        style={{ width: 180, height: 30, fontSize: 13 }}
        placeholder={t('extraction.searchPlaceholder')}
        value={value.search}
        onChange={e => patch({ search: e.target.value })}
      />
    </div>
  )
}
