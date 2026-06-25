import { useMemo, useState } from 'react'
import { ActionButton } from '../ActionButton'
import { CopyButton } from '../CopyButton'
import { LoadingState } from '../States'
import {
  getImportBatchRunHistory,
  type ImportBatchRunHistoryResponse,
} from '../../api/endpoints'
import { formatApiErrorMessage } from '../../utils/apiErrorMessage'
import { eventTypeLabel } from '../../utils/importPipelineHelpers'
import { buildRunHistoryNavContext, type StageNavContext } from '../../utils/pipelineNavigation'
import { useI18n } from '../../i18n-context'
import { useData } from '../../hooks/useData'

type TabKey = 'summary' | 'raw' | 'candidate' | 'validation' | 'rollback' | 'events'

function RunIdCell({ id }: { id: string }) {
  return (
    <span className="pipeline-run-id-cell">
      <code>{id.slice(0, 10)}…</code>
      <CopyButton value={id} label="" />
    </span>
  )
}

function ActiveBadge({ active }: { active: boolean }) {
  const { t } = useI18n()
  return (
    <span className={active ? 'pipeline-run-active-badge' : 'pipeline-run-inactive-badge'}>
      {active ? t('pipeline.runActive') : t('pipeline.runInactive')}
    </span>
  )
}

function fmtTime(v?: string | null) {
  if (!v) return '—'
  try {
    return new Date(v).toLocaleString()
  } catch {
    return v
  }
}

function RunViewActions({
  ctx,
  onView,
  onPreview,
}: {
  ctx: StageNavContext
  onView: (ctx: StageNavContext) => void
  onPreview: (ctx: StageNavContext) => void
}) {
  const { t } = useI18n()
  if (ctx.deleted) {
    return <span className="pipeline-stage-data-deleted">{t('pipeline.stageDataDeletedByRollback')}</span>
  }
  return (
    <div className="pipeline-stage-data-buttons">
      <ActionButton label={t('pipeline.viewStageData')} variant="default" onClick={() => onView(ctx)} />
      <ActionButton label={t('pipeline.previewStageData')} variant="default" onClick={() => onPreview(ctx)} />
    </div>
  )
}

export function RunHistoryPanel({
  batchId,
  refreshTick,
  isMacro96,
  resourceId,
  runHistory: runHistoryProp,
  onViewRaw,
  onViewCandidates,
  onViewValidation,
  onOpenRunView,
  onOpenRunPreview,
}: {
  batchId: string
  refreshTick: number
  isMacro96: boolean
  resourceId: string
  runHistory?: ImportBatchRunHistoryResponse | null
  onViewRaw: (parseRunId?: string) => void
  onViewCandidates: (generationRunId?: string) => void
  onViewValidation: (validationRunId?: string) => void
  onOpenRunView: (ctx: StageNavContext) => void
  onOpenRunPreview: (ctx: StageNavContext) => void
}) {
  const { t } = useI18n()
  const [tab, setTab] = useState<TabKey>('summary')
  const { data: fetched, loading, error, reload } = useData(
    () => getImportBatchRunHistory(batchId),
    [batchId, refreshTick],
  )
  const data = runHistoryProp ?? fetched

  const tabs = useMemo(
    (): { key: TabKey; label: string }[] => [
      { key: 'summary', label: t('pipeline.runHistorySummary') },
      { key: 'raw', label: t('pipeline.rawRuns') },
      { key: 'candidate', label: t('pipeline.candidateRuns') },
      { key: 'validation', label: t('pipeline.validationRuns') },
      { key: 'rollback', label: t('pipeline.rollbackRecords') },
      { key: 'events', label: t('pipeline.events') },
    ],
    [t],
  )

  return (
    <section className="pipeline-run-history">
      <div className="pipeline-run-history-header">
        <h3 className="pipeline-section-title">{t('pipeline.runHistory')}</h3>
        <ActionButton
          label={t('pipeline.refreshRunHistory')}
          variant="default"
          onClick={reload}
        />
      </div>

      <div className="pipeline-run-history-tabs">
        {tabs.map(item => (
          <button
            key={item.key}
            type="button"
            className={`pipeline-run-history-tab${tab === item.key ? ' is-active' : ''}`}
            onClick={() => setTab(item.key)}
          >
            {item.label}
          </button>
        ))}
      </div>

      <div className="pipeline-run-history-body">
        {loading && !runHistoryProp && <LoadingState />}
        {error && !runHistoryProp && <p className="batch-create-warning">{formatApiErrorMessage(error)}</p>}
        {data && (
          <RunHistoryContent
            data={data}
            tab={tab}
            batchId={batchId}
            resourceId={resourceId}
            isMacro96={isMacro96}
            onViewRaw={onViewRaw}
            onViewCandidates={onViewCandidates}
            onViewValidation={onViewValidation}
            onOpenRunView={onOpenRunView}
            onOpenRunPreview={onOpenRunPreview}
          />
        )}
        {!loading && !error && !data && (
          <p className="rollback-preview-only-note">{t('pipeline.noRunHistory')}</p>
        )}
      </div>
    </section>
  )
}

function RunHistoryContent({
  data,
  tab,
  batchId,
  resourceId,
  isMacro96,
  onViewRaw,
  onViewCandidates,
  onViewValidation,
  onOpenRunView,
  onOpenRunPreview,
}: {
  data: ImportBatchRunHistoryResponse
  tab: TabKey
  batchId: string
  resourceId: string
  isMacro96: boolean
  onViewRaw: (parseRunId?: string) => void
  onViewCandidates: (generationRunId?: string) => void
  onViewValidation: (validationRunId?: string) => void
  onOpenRunView: (ctx: StageNavContext) => void
  onOpenRunPreview: (ctx: StageNavContext) => void
}) {
  const { t } = useI18n()
  const activeParseRunId = data.current_active?.raw_parse_run_id ?? undefined

  if (tab === 'summary') {
    const s = data.summary
    return (
      <div className="pipeline-run-history-summary">
        <div className="pipeline-run-history-metric">
          <span>{t('pipeline.currentRowCount')}</span>
          <strong>{s.raw_row_count}</strong>
        </div>
        <div className="pipeline-run-history-metric">
          <span>{t('pipeline.currentCandidateCount')}</span>
          <strong>{s.candidate_count}</strong>
        </div>
        <div className="pipeline-run-history-metric">
          <span>{t('pipeline.currentValidationResultCount')}</span>
          <strong>{s.validation_result_count}</strong>
        </div>
        <div className="pipeline-run-history-metric">
          <span>{t('pipeline.currentActiveRun')}</span>
          <div className="pipeline-run-history-active-ids">
            <div><code>raw</code> {data.current_active?.raw_parse_run_id?.slice(0, 10) ?? '—'}…</div>
            <div><code>gen</code> {data.current_active?.candidate_generation_run_id?.slice(0, 10) ?? '—'}…</div>
            <div><code>val</code> {data.current_active?.validation_run_id?.slice(0, 10) ?? '—'}…</div>
          </div>
        </div>
        <p className="pipeline-reexecute-panel">{t('pipeline.reexecuteFromCurrentStatus')}</p>
        {data.warnings?.map((w, i) => (
          <p key={i} className="pipeline-run-rolledback-note">{w}</p>
        ))}
      </div>
    )
  }

  if (tab === 'raw') {
    if (data.raw_parse_runs.length === 0) {
      return <p className="rollback-preview-only-note">{t('pipeline.noRunHistory')}</p>
    }
    return (
      <div className="pipeline-run-history-table-wrap">
        <table className="pipeline-run-history-table">
          <thead>
            <tr>
              <th>ID</th>
              <th>parser</th>
              <th>status</th>
              <th>{t('pipeline.rolledBackOutput')}</th>
              <th>{t('pipeline.currentRowCount')}</th>
              <th>active</th>
              <th>finished</th>
              <th />
            </tr>
          </thead>
          <tbody>
            {data.raw_parse_runs.map(run => {
              const ctx = buildRunHistoryNavContext('raw', run, batchId, resourceId, isMacro96)
              return (
                <tr key={run.id}>
                  <td><RunIdCell id={run.id} /></td>
                  <td><code>{run.parser_key}</code></td>
                  <td>{run.status}</td>
                  <td>{run.output_count}</td>
                  <td>{run.raw_row_count}</td>
                  <td><ActiveBadge active={run.active} /></td>
                  <td>{fmtTime(run.finished_at)}</td>
                  <td>
                    {run.active ? (
                      <ActionButton label={t('pipeline.viewRaw')} variant="default" onClick={() => onViewRaw(run.id)} />
                    ) : (
                      <RunViewActions ctx={ctx} onView={onOpenRunView} onPreview={onOpenRunPreview} />
                    )}
                  </td>
                </tr>
              )
            })}
          </tbody>
        </table>
        {data.raw_parse_runs.some(r => r.note) && (
          <p className="pipeline-run-rolledback-note">{t('pipeline.outputDeletedByRollback')}</p>
        )}
      </div>
    )
  }

  if (tab === 'candidate') {
    if (data.candidate_generation_runs.length === 0) {
      return <p className="rollback-preview-only-note">{t('pipeline.noRunHistory')}</p>
    }
    return (
      <div className="pipeline-run-history-table-wrap">
        <table className="pipeline-run-history-table">
          <thead>
            <tr>
              <th>ID</th>
              <th>generator</th>
              <th>status</th>
              <th>{t('pipeline.rolledBackOutput')}</th>
              <th>{t('pipeline.currentCandidateCount')}</th>
              <th>active</th>
              <th>finished</th>
              <th />
            </tr>
          </thead>
          <tbody>
            {data.candidate_generation_runs.map(run => {
              const ctx = buildRunHistoryNavContext('candidate', run, batchId, resourceId, isMacro96, activeParseRunId)
              return (
                <tr key={run.id}>
                  <td><RunIdCell id={run.id} /></td>
                  <td><code>{run.generator_key}</code></td>
                  <td>{run.status}</td>
                  <td>{run.output_count}</td>
                  <td>{run.candidate_count}</td>
                  <td><ActiveBadge active={run.active} /></td>
                  <td>{fmtTime(run.finished_at)}</td>
                  <td>
                    {run.active ? (
                      <ActionButton label={t('pipeline.viewCandidates')} variant="default" onClick={() => onViewCandidates(run.id)} />
                    ) : (
                      <RunViewActions ctx={ctx} onView={onOpenRunView} onPreview={onOpenRunPreview} />
                    )}
                  </td>
                </tr>
              )
            })}
          </tbody>
        </table>
        {data.candidate_generation_runs.some(r => !r.active && r.output_count > 0) && (
          <p className="pipeline-run-rolledback-note">{t('pipeline.outputDeletedByRollback')}</p>
        )}
      </div>
    )
  }

  if (tab === 'validation') {
    if (data.rule_validation_runs.length === 0) {
      return <p className="rollback-preview-only-note">{t('pipeline.noRunHistory')}</p>
    }
    return (
      <div className="pipeline-run-history-table-wrap">
        <table className="pipeline-run-history-table">
          <thead>
            <tr>
              <th>ID</th>
              <th>status</th>
              <th>passed</th>
              <th>failed</th>
              <th>{t('pipeline.currentValidationResultCount')}</th>
              <th>active</th>
              <th>finished</th>
              <th />
            </tr>
          </thead>
          <tbody>
            {data.rule_validation_runs.map(run => {
              const ctx = buildRunHistoryNavContext('validation', run, batchId, resourceId, isMacro96)
              return (
                <tr key={run.id}>
                  <td><RunIdCell id={run.id} /></td>
                  <td>{run.status}</td>
                  <td>{run.passed_count}</td>
                  <td>{run.failed_count}</td>
                  <td>{run.result_count}</td>
                  <td><ActiveBadge active={run.active} /></td>
                  <td>{fmtTime(run.finished_at)}</td>
                  <td>
                    {run.active ? (
                      <ActionButton label={t('pipeline.viewValidation')} variant="default" onClick={() => onViewValidation(run.id)} />
                    ) : (
                      <RunViewActions ctx={ctx} onView={onOpenRunView} onPreview={onOpenRunPreview} />
                    )}
                  </td>
                </tr>
              )
            })}
          </tbody>
        </table>
      </div>
    )
  }

  if (tab === 'rollback') {
    if (data.rollback_records.length === 0) {
      return <p className="rollback-preview-only-note">{t('pipeline.rollbackHistory')}: —</p>
    }
    return (
      <div className="pipeline-run-history-table-wrap">
        <table className="pipeline-run-history-table">
          <thead>
            <tr>
              <th>ID</th>
              <th>from</th>
              <th>to</th>
              <th>operator</th>
              <th>deleted</th>
              <th>status</th>
              <th>created</th>
            </tr>
          </thead>
          <tbody>
            {data.rollback_records.map(rec => (
              <tr key={rec.id}>
                <td><RunIdCell id={rec.id} /></td>
                <td><code>{rec.from_status}</code></td>
                <td><code>{rec.target_status}</code></td>
                <td>{rec.operator}</td>
                <td>
                  {Object.entries(rec.deleted_counts || {})
                    .filter(([, n]) => n > 0)
                    .map(([k, n]) => `${k}=${n}`)
                    .join(', ') || '—'}
                </td>
                <td>{rec.status}</td>
                <td>{fmtTime(rec.created_at)}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    )
  }

  return (
    <div className="pipeline-run-history-table-wrap">
      <table className="pipeline-run-history-table">
        <thead>
          <tr>
            <th>type</th>
            <th>from</th>
            <th>to</th>
            <th>message</th>
            <th>time</th>
          </tr>
        </thead>
        <tbody>
          {data.events.map(ev => (
            <tr key={ev.id}>
              <td>{eventTypeLabel(ev.event_type, t)}</td>
              <td>{ev.from_status ?? '—'}</td>
              <td>{ev.to_status ?? '—'}</td>
              <td>{ev.message ?? '—'}</td>
              <td>{fmtTime(ev.created_at)}</td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  )
}
