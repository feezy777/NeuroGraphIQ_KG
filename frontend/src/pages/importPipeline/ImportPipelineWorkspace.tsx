import { useMemo, useState, useCallback } from 'react'
import { ActionButton } from '../../components/ActionButton'
import { ConfirmDialog } from '../../components/ConfirmDialog'
import { CopyButton } from '../../components/CopyButton'
import { StatusBadge } from '../../components/StatusBadge'
import { type NoticeState } from '../../components/Notice'
import { useData } from '../../hooks/useData'
import { useSessionIds } from '../../hooks/useSessionIds'
import {
  generateCandidates,
  generateMacro96Candidates,
  getImportBatchPipelineOverview,
  getImportBatchRunHistory,
  type ImportBatchRunHistoryResponse,
  parseAal3,
  parseMacro96Batch,
  queueBatch,
  startBatch,
  validateByBatch,
  cancelImportBatch,
  cloneImportBatch,
  type BoundFilePipelineRead,
  type ImportBatchPipelineOverview,
  type PipelineAction,
} from '../../api/endpoints'
import { BatchCloneDialog } from '../../components/import-batches/BatchCloneDialog'
import { BatchEditModal } from '../../components/import-batches/BatchEditModal'
import { BatchSafeDeleteDialog } from '../../components/import-batches/BatchSafeDeleteDialog'
import { RollbackPreviewModal } from '../../components/import-batches/RollbackPreviewModal'
import { RunHistoryPanel } from '../../components/import-batches/RunHistoryPanel'
import { StageDataPreviewDrawer, type PreviewColumn } from '../../components/pipeline/StageDataPreviewDrawer'
import { PipelineStageDataActions } from '../../components/pipeline/PipelineStageDataActions'
import {
  batchEditDisabledReason,
  canCancelBatch,
  canCloneBatch,
  canEditDescription,
} from '../../utils/batchEditPermissions'
import { formatApiErrorMessage } from '../../utils/apiErrorMessage'
import {
  buildDataSnapshot,
  compatibilityReasonLabel,
  eventTypeLabel,
  getBatchFileCompatibility,
  getTimelineStepCount,
  isAal3Batch,
  isMacro96Batch,
  PIPELINE_TIMELINE_STEPS,
  sortEventsChronological,
  timelineStepState,
  type PipelineDataSnapshot,
} from '../../utils/importPipelineHelpers'
import { useI18n } from '../../i18n-context'
import {
  buildHashUrl,
  buildRunHistoryNavContext,
  buildStageNavContext,
  navigateWithQuery,
  stageViewLabelKey,
  timelineStepToStage,
  type StageNavContext,
} from '../../utils/pipelineNavigation'
import { loadStagePreview } from '../../utils/loadStagePreview'

type ActionKey =
  | 'queue_batch'
  | 'start_batch'
  | 'parse_aal3'
  | 'parse_macro96'
  | 'generate_candidates'
  | 'generate_macro96_candidates'
  | 'validate_batch'

type AsyncActionKey = 'parse_macro96' | 'generate_macro96_candidates'

const ACTION_LABELS: Record<ActionKey, string> = {
  queue_batch: 'Queue Batch',
  start_batch: 'Start Batch',
  parse_aal3: 'Parse AAL3',
  parse_macro96: 'Parse Macro96',
  generate_candidates: 'Generate Candidates',
  generate_macro96_candidates: 'Generate Macro96 Candidates',
  validate_batch: 'Validate Batch',
}

const SUCCESS_KEYS: Record<ActionKey, string> = {
  queue_batch: 'importPipeline.queueSuccess',
  start_batch: 'importPipeline.startSuccess',
  parse_aal3: 'importPipeline.parseSuccess',
  parse_macro96: 'importPipeline.macro96ParseSucceeded',
  generate_candidates: 'importPipeline.generateSuccess',
  generate_macro96_candidates: 'importPipeline.macro96CandidateGenerationSucceeded',
  validate_batch: 'importPipeline.validateSuccess',
}

async function executeAction(action: Exclude<ActionKey, AsyncActionKey>, batchId: string): Promise<void> {
  switch (action) {
    case 'queue_batch': await queueBatch(batchId); break
    case 'start_batch': await startBatch(batchId); break
    case 'parse_aal3': await parseAal3(batchId); break
    case 'generate_candidates': await generateCandidates(batchId); break
    case 'validate_batch': await validateByBatch(batchId); break
  }
}

function IdField({ label, value }: { label: string; value: string }) {
  return (
    <div className="pipeline-header-field">
      <span className="pipeline-header-label">{label}</span>
      <span className="pipeline-header-value">
        <code>{value.slice(0, 10)}…</code>
        <CopyButton value={value} label="" />
      </span>
    </div>
  )
}

function BatchHeaderCard({
  overview,
  onRefresh,
}: {
  overview: ImportBatchPipelineOverview
  onRefresh: () => void
}) {
  const { t } = useI18n()
  const batch = overview.batch
  const macro96 = isMacro96Batch(batch)

  return (
    <section className="pipeline-header-card">
      <div className="pipeline-header-top">
        <div>
          <h2 className="pipeline-header-title">{batch.batch_code}</h2>
          <p className="pipeline-header-sub">
            {macro96 ? t('pipeline.parserDescMacro96') : isAal3Batch(batch) ? t('pipeline.parserDescAal3') : batch.parser_key}
          </p>
        </div>
        <div className="pipeline-header-badges">
          <StatusBadge status={batch.status} />
          <span className={`pipeline-parser-badge${macro96 ? ' pipeline-parser-badge--macro96' : ''}`}>
            {batch.parser_key ?? '—'}
          </span>
        </div>
      </div>
      <div className="pipeline-header-grid">
        <IdField label="Batch ID" value={batch.id} />
        <IdField label={t('pipeline.copyResourceId')} value={batch.resource_id} />
        <div className="pipeline-header-field">
          <span className="pipeline-header-label">{t('importPipeline.batchOverview')}</span>
          <span className="pipeline-header-value">{batch.batch_type}</span>
        </div>
        <div className="pipeline-header-field">
          <span className="pipeline-header-label">{t('pipeline.createdAt')}</span>
          <span className="pipeline-header-value">{batch.created_at?.slice(0, 16) ?? '—'}</span>
        </div>
        <div className="pipeline-header-field">
          <span className="pipeline-header-label">{t('pipeline.updatedAt')}</span>
          <span className="pipeline-header-value">{batch.updated_at?.slice(0, 16) ?? '—'}</span>
        </div>
      </div>
      <div className="pipeline-header-actions">
        <ActionButton label={t('common.refresh')} variant="default" onClick={onRefresh} />
      </div>
    </section>
  )
}

function PipelineTimelineCard({
  overview,
  isMacro96,
  runHistory,
  onRollbackPreview,
  onOpenStageView,
  onOpenStagePreview,
}: {
  overview: ImportBatchPipelineOverview
  isMacro96: boolean
  runHistory: ImportBatchRunHistoryResponse | null
  onRollbackPreview: () => void
  onOpenStageView: (ctx: StageNavContext) => void
  onOpenStagePreview: (ctx: StageNavContext) => void
}) {
  const { t } = useI18n()
  const status = overview.batch.status
  const batchId = overview.batch.id
  const resourceId = overview.batch.resource_id

  return (
    <section className="pipeline-timeline-card">
      <h3 className="pipeline-section-title">{t('pipeline.timeline')}</h3>
      <div className="pipeline-stage-grid">
        {PIPELINE_TIMELINE_STEPS.map(step => {
          const state = timelineStepState(step.statusRank, status)
          const count = getTimelineStepCount(step.key, overview, isMacro96)
          const stageKey = timelineStepToStage(step.key)
          const navCtx = stageKey && runHistory
            ? buildStageNavContext(stageKey, batchId, resourceId, isMacro96, runHistory)
            : null
          return (
            <div key={step.key} className={`pipeline-stage-node pipeline-stage-node-${state}`}>
              <div className="pipeline-stage-node-head">
                <span className="pipeline-stage-node-label">{t(step.labelKey)}</span>
                {count && <span className="pipeline-count-badge">{count}</span>}
              </div>
              <div className="pipeline-stage-node-actions">
                {navCtx && (
                  <PipelineStageDataActions
                    ctx={navCtx}
                    viewLabelKey={stageViewLabelKey(navCtx.stage, isMacro96)}
                    onViewData={() => onOpenStageView(navCtx)}
                    onPreview={() => onOpenStagePreview(navCtx)}
                  />
                )}
                {state === 'done' && (
                  <button type="button" className="pipeline-placeholder-action" onClick={() => onRollbackPreview()}>
                    {t('pipeline.rollbackPreview')}
                  </button>
                )}
              </div>
            </div>
          )
        })}
      </div>
    </section>
  )
}

function DataSnapshotCard({ snapshot, isMacro96 }: { snapshot: PipelineDataSnapshot; isMacro96: boolean }) {
  const { t } = useI18n()
  const metrics = [
    { label: isMacro96 ? t('pipeline.macro96RawRows') : t('pipeline.aal3RawLabels'), value: snapshot.rawRowCount },
    { label: isMacro96 ? t('pipeline.macro96CandidateCount') : t('pipeline.aal3CandidateCount'), value: snapshot.candidateCount },
    { label: t('importPipeline.passed'), value: snapshot.validationPassed },
    { label: t('importPipeline.warnings'), value: snapshot.validationWarning },
    { label: t('importPipeline.failed'), value: snapshot.validationFailed },
  ]

  return (
    <section className="pipeline-data-snapshot">
      <h3 className="pipeline-section-title">{t('pipeline.dataSnapshot')}</h3>
      <div className="pipeline-data-metric-grid">
        {metrics.map(m => (
          <div key={m.label} className="pipeline-data-metric">
            <div className="pipeline-data-metric-value">{m.value ?? '—'}</div>
            <div className="pipeline-data-metric-label">{m.label}</div>
          </div>
        ))}
      </div>
      <div className="pipeline-data-snapshot-meta">
        {snapshot.rawParseRunId && (
          <span>parse_run: <code>{snapshot.rawParseRunId.slice(0, 8)}…</code></span>
        )}
        {snapshot.candidateGenerationRunId && (
          <span>gen_run: <code>{snapshot.candidateGenerationRunId.slice(0, 8)}…</code></span>
        )}
        {snapshot.validationRunId && (
          <span>val_run: <code>{snapshot.validationRunId.slice(0, 8)}…</code></span>
        )}
        {!snapshot.rawParseRunId && !snapshot.candidateGenerationRunId && (
          <span className="pipeline-data-unavailable">{t('pipeline.dataUnavailable')}</span>
        )}
      </div>
    </section>
  )
}

function BoundFilesCard({
  files,
  parserKey,
  onGoToFiles,
}: {
  files: BoundFilePipelineRead[]
  parserKey?: string | null
  onGoToFiles: (fileId: string) => void
}) {
  const { t } = useI18n()
  const macro96 = isMacro96Batch({ parser_key: parserKey })

  if (files.length === 0) {
    return (
      <section className="pipeline-bound-files-card">
        <h3 className="pipeline-section-title">{t('pipeline.boundFiles')}</h3>
        <div className="pipeline-sidebar-empty">{t('importPipeline.noBoundFiles')}</div>
      </section>
    )
  }

  return (
    <section className="pipeline-bound-files-card">
      <h3 className="pipeline-section-title">{t('pipeline.boundFiles')}</h3>
      <div className="pipeline-bound-table-wrap">
        <table className="pipeline-bound-table">
          <thead>
            <tr>
              <th>File ID</th>
              <th>{t('importPipeline.colFilename')}</th>
              <th>Role</th>
              <th>{t('importPipeline.colFileStatus')}</th>
              <th>{t('importPipeline.colIntermediate')}</th>
              <th>{t('pipeline.parserAwareCompatibility')}</th>
              <th>{t('importPipeline.colCanParse')}</th>
              <th>{t('importPipeline.colReason')}</th>
              <th>{t('common.actions')}</th>
            </tr>
          </thead>
          <tbody>
            {files.map(f => {
              const compat = getBatchFileCompatibility(f, parserKey)
              return (
                <tr key={f.file_id}>
                  <td><code>{f.file_id.slice(0, 8)}…</code> <CopyButton value={f.file_id} label="" /></td>
                  <td>{f.original_filename ?? '—'}</td>
                  <td>{f.file_role_in_batch}</td>
                  <td>{f.file_status ?? '—'}</td>
                  <td>{f.intermediate_status ?? '—'}</td>
                  <td>
                    <span className={compat.compatible ? 'pipeline-compatible-badge' : 'pipeline-incompatible-badge'}>
                      {compat.compatible
                        ? (macro96 ? t('pipeline.macro96Compatible') : t('batches.parserCompatible'))
                        : (macro96 ? t('pipeline.macro96Incompatible') : t('batches.parserIncompatible'))}
                    </span>
                  </td>
                  <td>{compat.canParse ? t('common.yes') : t('common.no')}</td>
                  <td>{compatibilityReasonLabel(compat.reason, t)}</td>
                  <td>
                    <button type="button" className="pipeline-link-btn" onClick={() => onGoToFiles(f.file_id)}>
                      {t('importPipeline.goToFileCenter')}
                    </button>
                  </td>
                </tr>
              )
            })}
          </tbody>
        </table>
      </div>
    </section>
  )
}

function EventsCard({ events }: { events: ImportBatchPipelineOverview['events'] }) {
  const { t } = useI18n()
  const [view, setView] = useState<'timeline' | 'table'>('timeline')
  const sorted = useMemo(() => sortEventsChronological(events), [events])

  return (
    <section className="pipeline-events-card">
      <div className="pipeline-events-header">
        <h3 className="pipeline-section-title">{t('importPipeline.events')}</h3>
        <div className="pipeline-events-toggle">
          <button
            type="button"
            className={view === 'timeline' ? 'active' : ''}
            onClick={() => setView('timeline')}
          >
            {t('pipeline.timelineView')}
          </button>
          <button
            type="button"
            className={view === 'table' ? 'active' : ''}
            onClick={() => setView('table')}
          >
            {t('pipeline.tableView')}
          </button>
        </div>
      </div>
      <div className="pipeline-events-body">
        {view === 'timeline' ? (
          <div className="pipeline-events-timeline">
            {[...sorted].reverse().map(ev => (
              <div key={ev.id} className="pipeline-event-item">
                <div className="pipeline-event-time">{ev.created_at?.slice(0, 16) ?? '—'}</div>
                <div className="pipeline-event-type">{eventTypeLabel(ev.event_type, t)}</div>
                <div className="pipeline-event-transition">
                  {ev.from_status ?? '—'} → {ev.to_status ?? '—'}
                </div>
                <div className="pipeline-event-message">{ev.message ?? '—'}</div>
              </div>
            ))}
          </div>
        ) : (
          <table className="pipeline-bound-table">
            <thead>
              <tr>
                <th>Event</th>
                <th>From</th>
                <th>To</th>
                <th>Message</th>
                <th>Time</th>
              </tr>
            </thead>
            <tbody>
              {[...sorted].reverse().map(ev => (
                <tr key={ev.id}>
                  <td>{eventTypeLabel(ev.event_type, t)}</td>
                  <td>{ev.from_status ?? '—'}</td>
                  <td>{ev.to_status ?? '—'}</td>
                  <td>{ev.message ?? '—'}</td>
                  <td>{ev.created_at?.slice(0, 16) ?? '—'}</td>
                </tr>
              ))}
            </tbody>
          </table>
        )}
      </div>
    </section>
  )
}

function ManagementActionsBar({
  batchStatus,
  onRefresh,
  onEdit,
  onClone,
  onCancel,
  onRollbackPreview,
}: {
  batchStatus: string
  onRefresh: () => void
  onEdit: () => void
  onClone: () => void
  onCancel: () => void
  onRollbackPreview: () => void
}) {
  const { t } = useI18n()
  const canEdit = canEditDescription(batchStatus)
  const editReason = batchEditDisabledReason(batchStatus, t)

  return (
    <div className="pipeline-management-actions pipeline-crud-actions">
      <span className="pipeline-management-label">{t('pipeline.managementActions')}</span>
      <ActionButton
        label={t('pipeline.editBatch')}
        variant="default"
        disabled={!canEdit}
        onClick={onEdit}
      />
      {!canEdit && editReason && (
        <span className="batch-create-hint">{editReason}</span>
      )}
      <ActionButton
        label={t('pipeline.cloneBatch')}
        variant="default"
        disabled={!canCloneBatch(batchStatus)}
        onClick={onClone}
      />
      <ActionButton
        label={t('pipeline.cancelBatch')}
        variant="danger"
        disabled={!canCancelBatch(batchStatus)}
        onClick={onCancel}
      />
      <ActionButton label={t('pipeline.rollbackPreview')} variant="default" onClick={onRollbackPreview} />
      <ActionButton label={t('common.refresh')} variant="default" onClick={onRefresh} />
      <span className="batch-danger-note">{t('pipeline.noPhysicalDelete')}</span>
    </div>
  )
}

export function ImportPipelineWorkspace({
  batchId,
  refreshTick,
  onActionDone,
  onBatchMutated,
  onSelectBatch,
}: {
  batchId: string
  refreshTick: number
  onActionDone: (notice: NoticeState) => void
  onBatchMutated: () => void
  onSelectBatch: (id: string | null) => void
}) {
  const { t } = useI18n()
  const { setIds } = useSessionIds()
  const [confirm, setConfirm] = useState<{ action: ActionKey } | null>(null)
  const [rollbackOpen, setRollbackOpen] = useState(false)
  const [editOpen, setEditOpen] = useState(false)
  const [cloneOpen, setCloneOpen] = useState(false)
  const [cancelOpen, setCancelOpen] = useState(false)
  const [crudLoading, setCrudLoading] = useState(false)
  const [actioning, setActioning] = useState(false)
  const [innerRefreshTick, setInnerRefreshTick] = useState(0)

  const { data: overview, loading, error } = useData(
    () => getImportBatchPipelineOverview(batchId),
    [batchId, refreshTick, innerRefreshTick],
  )

  const { data: runHistory } = useData(
    () => getImportBatchRunHistory(batchId),
    [batchId, refreshTick, innerRefreshTick],
  )

  const [previewOpen, setPreviewOpen] = useState(false)
  const [previewCtx, setPreviewCtx] = useState<StageNavContext | null>(null)
  const [previewLoading, setPreviewLoading] = useState(false)
  const [previewError, setPreviewError] = useState<string | null>(null)
  const [previewRows, setPreviewRows] = useState<Record<string, unknown>[]>([])
  const [previewColumns, setPreviewColumns] = useState<PreviewColumn[]>([])
  const [previewTotal, setPreviewTotal] = useState(0)
  const [previewApiNotImplemented, setPreviewApiNotImplemented] = useState(false)

  const isMacro96 = isMacro96Batch(overview?.batch)
  const snapshot = useMemo(
    () => (overview ? buildDataSnapshot(overview, isMacro96) : {}),
    [overview, isMacro96],
  )

  function refresh() {
    setInnerRefreshTick(x => x + 1)
  }

  async function handleCloneConfirm() {
    setCrudLoading(true)
    try {
      const cloned = await cloneImportBatch(batchId)
      onActionDone({ type: 'success', message: t('pipeline.cloneBatchSuccess') })
      onBatchMutated()
      onSelectBatch(cloned.id)
      setIds({ batch_id: cloned.id, resource_id: cloned.resource_id })
      setCloneOpen(false)
    } catch (e) {
      onActionDone({ type: 'error', message: formatApiErrorMessage(e) })
    } finally {
      setCrudLoading(false)
    }
  }

  async function handleCancelConfirm() {
    setCrudLoading(true)
    try {
      await cancelImportBatch(batchId)
      onActionDone({ type: 'success', message: t('pipeline.cancelBatchSuccess') })
      onBatchMutated()
      refresh()
      setCancelOpen(false)
    } catch (e) {
      onActionDone({ type: 'error', message: formatApiErrorMessage(e) })
    } finally {
      setCrudLoading(false)
    }
  }

  function goToFileCenter(fileId: string) {
    if (overview) setIds({ resource_id: overview.batch.resource_id, file_id: fileId })
    window.location.hash = '#/files'
  }

  function openStageView(ctx: StageNavContext) {
    if (!overview) return
    if (ctx.deleted) return
    navigateWithQuery(ctx.fullViewPath, ctx.fullViewQuery, {
      batch_id: batchId,
      resource_id: overview.batch.resource_id,
      parse_run_id: ctx.fullViewQuery.parse_run_id,
      generation_run_id: ctx.fullViewQuery.generation_run_id,
      validation_run_id: ctx.fullViewQuery.validation_run_id,
    })
  }

  const openStagePreview = useCallback(async (ctx: StageNavContext) => {
    if (!overview || ctx.deleted) return
    setPreviewCtx(ctx)
    setPreviewOpen(true)
    setPreviewLoading(true)
    setPreviewError(null)
    setPreviewRows([])
    setPreviewApiNotImplemented(false)
    try {
      const active = runHistory?.current_active
      const res = await loadStagePreview(ctx.stage, {
        batchId,
        isMacro96: isMacro96Batch(overview.batch),
        parseRunId: ctx.fullViewQuery.parse_run_id ?? active?.raw_parse_run_id ?? undefined,
        generationRunId: ctx.fullViewQuery.generation_run_id ?? active?.candidate_generation_run_id ?? undefined,
        validationRunId: ctx.fullViewQuery.validation_run_id ?? active?.validation_run_id ?? undefined,
      })
      setPreviewRows(res.rows)
      setPreviewColumns(res.columns)
      setPreviewTotal(res.total)
      setPreviewApiNotImplemented(res.apiNotImplemented)
    } catch (e) {
      setPreviewError(formatApiErrorMessage(e))
    } finally {
      setPreviewLoading(false)
    }
  }, [overview, runHistory, batchId])

  function goToRaw(parseRunId?: string) {
    if (!overview) return
    const macro96 = isMacro96Batch(overview.batch)
    navigateWithQuery(macro96 ? '/raw-macro96' : '/raw-aal3', {
      batch_id: batchId,
      resource_id: overview.batch.resource_id,
      ...(parseRunId ? { parse_run_id: parseRunId } : runHistory?.current_active?.raw_parse_run_id
        ? { parse_run_id: runHistory.current_active.raw_parse_run_id }
        : {}),
    }, { batch_id: batchId, resource_id: overview.batch.resource_id, parse_run_id: parseRunId })
  }

  function goToCandidates(generationRunId?: string) {
    if (!overview) return
    const macro96 = isMacro96Batch(overview.batch)
    navigateWithQuery('/candidates', {
      batch_id: batchId,
      resource_id: overview.batch.resource_id,
      ...(generationRunId ? { generation_run_id: generationRunId } : runHistory?.current_active?.candidate_generation_run_id
        ? { generation_run_id: runHistory.current_active.candidate_generation_run_id }
        : {}),
      ...(runHistory?.current_active?.raw_parse_run_id ? { parse_run_id: runHistory.current_active.raw_parse_run_id } : {}),
      ...(macro96 ? { source_atlas: 'Macro96' } : {}),
    }, {
      batch_id: batchId,
      resource_id: overview.batch.resource_id,
      generation_run_id: generationRunId,
    })
  }

  function goToValidation(validationRunId?: string) {
    if (!overview) return
    navigateWithQuery('/rule-validation', {
      batch_id: batchId,
      ...(validationRunId ? { validation_run_id: validationRunId } : runHistory?.current_active?.validation_run_id
        ? { validation_run_id: runHistory.current_active.validation_run_id }
        : {}),
      ...(runHistory?.current_active?.candidate_generation_run_id
        ? { generation_run_id: runHistory.current_active.candidate_generation_run_id }
        : {}),
    }, { batch_id: batchId, validation_run_id: validationRunId })
  }

  async function handleActionConfirm() {
    if (!confirm) return

    if (confirm.action === 'parse_macro96') {
      setActioning(true)
      try {
        await parseMacro96Batch(batchId)
        onActionDone({ type: 'success', message: t(SUCCESS_KEYS.parse_macro96) })
        refresh()
      } catch (e) {
        onActionDone({ type: 'error', message: formatApiErrorMessage(e) })
      } finally {
        setActioning(false)
        setConfirm(null)
      }
      return
    }

    if (confirm.action === 'generate_macro96_candidates') {
      setActioning(true)
      try {
        await generateMacro96Candidates(batchId)
        onActionDone({ type: 'success', message: t(SUCCESS_KEYS.generate_macro96_candidates) })
        refresh()
      } catch (e) {
        onActionDone({ type: 'error', message: formatApiErrorMessage(e) })
      } finally {
        setActioning(false)
        setConfirm(null)
      }
      return
    }

    setActioning(true)
    try {
      await executeAction(confirm.action as Exclude<ActionKey, AsyncActionKey>, batchId)
      onActionDone({ type: 'success', message: t(SUCCESS_KEYS[confirm.action]) })
      refresh()
    } catch (e) {
      onActionDone({ type: 'error', message: formatApiErrorMessage(e) })
    } finally {
      setActioning(false)
      setConfirm(null)
    }
  }

  if (loading) return <div className="pipeline-overview-empty">{t('common.loading')}</div>
  if (error) return <div className="pipeline-overview-empty" style={{ color: '#ff4d4f' }}>{error}</div>
  if (!overview) return null

  const actionLabelKey = (act: PipelineAction): string => {
    switch (act.action) {
      case 'queue_batch': return 'importPipeline.queueBatch'
      case 'start_batch': return 'importPipeline.startBatch'
      case 'parse_aal3': return 'importPipeline.parseAal3'
      case 'parse_macro96': return 'importPipeline.parseMacro96'
      case 'generate_macro96_candidates': return 'importPipeline.generateMacro96Candidates'
      case 'generate_candidates': return 'importPipeline.generateCandidates'
      case 'validate_batch': return 'importPipeline.validateBatch'
      default: return 'importPipeline.currentAction'
    }
  }

  return (
    <main className="pipeline-main">
      <BatchHeaderCard overview={overview} onRefresh={refresh} />
      <ManagementActionsBar
        batchStatus={overview.batch.status}
        onRefresh={refresh}
        onEdit={() => setEditOpen(true)}
        onClone={() => setCloneOpen(true)}
        onCancel={() => setCancelOpen(true)}
        onRollbackPreview={() => setRollbackOpen(true)}
      />
      <PipelineTimelineCard
        overview={overview}
        isMacro96={isMacro96}
        runHistory={runHistory ?? null}
        onRollbackPreview={() => setRollbackOpen(true)}
        onOpenStageView={openStageView}
        onOpenStagePreview={openStagePreview}
      />
      <section className="pipeline-action-center">
        <h3 className="pipeline-section-title">{t('pipeline.actionCenter')}</h3>
        <div className="pipeline-action-grid">
          {overview.next_allowed_actions.map(act => (
            <div key={act.action} className="pipeline-action-item">
              <ActionButton
                label={t(actionLabelKey(act))}
                variant="primary"
                disabled={!act.enabled}
                onClick={() => act.enabled && setConfirm({ action: act.action as ActionKey })}
              />
              {!act.enabled && act.reason && (
                <div className="pipeline-action-reason">{act.reason}</div>
              )}
            </div>
          ))}
        </div>
        <div className="pipeline-action-aux">
          <ActionButton
            label={isMacro96 ? t('importPipeline.viewRawMacro96') : t('importPipeline.viewAllRawLabels')}
            variant="default"
            onClick={goToRaw}
          />
          <ActionButton
            label={isMacro96 ? t('importPipeline.viewMacro96Candidates') : t('importPipeline.viewAllCandidates')}
            variant="default"
            onClick={goToCandidates}
          />
        </div>
      </section>
      <DataSnapshotCard snapshot={snapshot} isMacro96={isMacro96} />
      <RunHistoryPanel
        batchId={batchId}
        refreshTick={refreshTick + innerRefreshTick}
        isMacro96={isMacro96}
        resourceId={overview.batch.resource_id}
        runHistory={runHistory ?? null}
        onViewRaw={goToRaw}
        onViewCandidates={goToCandidates}
        onViewValidation={goToValidation}
        onOpenRunView={(ctx) => openStageView(ctx)}
        onOpenRunPreview={openStagePreview}
      />
      <BoundFilesCard
        files={overview.bound_files}
        parserKey={overview.batch.parser_key}
        onGoToFiles={goToFileCenter}
      />
      <EventsCard events={overview.events} />

      <ConfirmDialog
        open={!!confirm}
        title={
          confirm?.action === 'parse_macro96'
            ? t('importPipeline.parseMacro96ConfirmTitle')
            : confirm?.action === 'generate_macro96_candidates'
            ? t('importPipeline.generateMacro96CandidatesConfirmTitle')
            : t('importPipeline.confirmAction', { action: confirm ? ACTION_LABELS[confirm.action] : '' })
        }
        message={
          confirm?.action === 'parse_macro96'
            ? t('importPipeline.parseMacro96ConfirmMessage')
            : confirm?.action === 'generate_macro96_candidates'
            ? t('importPipeline.generateMacro96CandidatesConfirmMessage')
            : t('importPipeline.confirmMsg', { action: confirm ? ACTION_LABELS[confirm.action] : '', id: batchId.slice(0, 12) })
        }
        onConfirm={handleActionConfirm}
        onCancel={() => setConfirm(null)}
        loading={actioning}
      />

      <RollbackPreviewModal
        open={rollbackOpen}
        batchId={batchId}
        batchCode={overview.batch.batch_code}
        currentStatus={overview.batch.status}
        onClose={() => setRollbackOpen(false)}
        onSuccess={() => {
          onActionDone({
            type: 'success',
            message: t('pipeline.rollbackExecuteSucceeded'),
          })
          onBatchMutated()
          refresh()
        }}
      />

      <BatchEditModal
        batchId={batchId}
        open={editOpen}
        onClose={() => setEditOpen(false)}
        onSaved={() => {
          onActionDone({ type: 'success', message: t('batches.updateSuccess') })
          onBatchMutated()
          refresh()
        }}
      />

      <BatchCloneDialog
        open={cloneOpen}
        loading={crudLoading}
        batchCode={overview.batch.batch_code}
        onConfirm={handleCloneConfirm}
        onCancel={() => setCloneOpen(false)}
      />

      <BatchSafeDeleteDialog
        open={cancelOpen}
        loading={crudLoading}
        batchCode={overview.batch.batch_code}
        onConfirm={handleCancelConfirm}
        onCancel={() => setCancelOpen(false)}
      />

      <StageDataPreviewDrawer
        open={previewOpen}
        title={previewCtx ? t(stageViewLabelKey(previewCtx.stage, isMacro96)) : t('pipeline.stageDataPreview')}
        loading={previewLoading}
        error={previewError}
        total={previewTotal}
        columns={previewColumns}
        rows={previewRows}
        deleted={previewCtx?.deleted ?? false}
        apiNotImplemented={previewApiNotImplemented}
        fullViewUrl={previewCtx ? buildHashUrl(previewCtx.fullViewPath, { ...previewCtx.fullViewQuery, from_pipeline: '1' }) : null}
        runId={previewCtx?.runId}
        onClose={() => { setPreviewOpen(false); setPreviewCtx(null) }}
        onOpenFullView={() => { if (previewCtx) { openStageView(previewCtx); setPreviewOpen(false) } }}
      />
    </main>
  )
}
