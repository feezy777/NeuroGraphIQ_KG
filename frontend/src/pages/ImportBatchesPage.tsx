import { useState, useCallback, useEffect, useMemo } from 'react'
import { X } from 'lucide-react'
import { PageHeader } from '../components/PageHeader'
import { StatusBadge } from '../components/StatusBadge'
import { FormPanel } from '../components/FormPanel'
import { ActionButton } from '../components/ActionButton'
import { Notice, type NoticeState } from '../components/Notice'
import { ConfirmDialog } from '../components/ConfirmDialog'
import { KeyValuePanel } from '../components/KeyValuePanel'
import { LoadingState, ErrorState, EmptyState } from '../components/States'
import { useData } from '../hooks/useData'
import {
  fetchImportBatches,
  fetchImportBatchOptions,
  getImportBatch,
  getImportBatchEvents,
  updateImportBatch,
  updateImportBatchFiles,
  queueBatch,
  startBatch,
  cancelImportBatch,
  filterWorkbenchBatches,
  WORKBENCH_BATCH_STATUS_FILTER_OPTIONS,
  listResources,
  listResourceFiles,
  type ImportBatch,
  type ImportBatchDetail,
  type ImportBatchFileEnriched,
  type ImportBatchEvent,
  type BatchFileBinding,
  type AtlasResource,
  type ResourceFile,
} from '../api/endpoints'
import { ApiError } from '../api/client'
import { readSessionIds, useSessionIds } from '../hooks/useSessionIds'
import { useGlobalGranularity } from '../hooks/useGlobalGranularity'
import { CopyButton } from '../components/CopyButton'
import { useI18n } from '../i18n-context'
import {
  inferBatchDefaultsFromResource,
} from '../utils/batchParserDefaults'
import {
  getFileParserCompatibility,
  isAal3XmlParserKey,
  isMacro96XlsxParserKey,
  isParserCompatibleFile,
} from '../utils/importBatchParserCompatibility'
import { formatApiErrorMessage } from '../utils/apiErrorMessage'
import { CreateBatchModal } from '../components/import-batches/CreateBatchModal'
import {
  emptyBinding,
  formatFileRoleInBatchLabel,
  type FileBindingRow,
} from '../components/import-batches/batchModalUtils'
import {
  canCancelBatch,
  canEditCoreFields,
  canEditDescription,
  canEditFiles,
} from '../utils/batchEditPermissions'

type DetailTab = 'overview' | 'pipeline' | 'files' | 'events' | 'raw'
type ConfirmAction = 'queue' | 'start' | 'cancel'

const TERMINAL_STATUSES = new Set(['completed', 'failed', 'cancelled'])

function formatBytes(value: number | null | undefined): string {
  const size = value ?? 0
  if (size < 1024) return `${size} B`
  if (size < 1024 * 1024) return `${(size / 1024).toFixed(1)} KB`
  return `${(size / 1024 / 1024).toFixed(2)} MB`
}

function formatResourceLabel(r: AtlasResource): string {
  return `${r.source_atlas} | ${r.resource_code} | ${r.source_version} | ${r.granularity_level} | ${r.status}`
}

function formatFileOptionLabel(f: ResourceFile): string {
  const intSt = f.intermediate_status ?? 'unknown'
  const kind = f.latest_intermediate_kind ? ` | ${f.latest_intermediate_kind}` : ''
  return `${f.original_filename} | ${f.file_type} | ${f.file_role} | ${f.status} | ${intSt}${kind} | ${formatBytes(f.file_size)}`
}

function isSpreadsheetFile(f: ResourceFile): boolean {
  const ext = (f.file_ext ?? '').toLowerCase()
  return ext === '.xlsx' || ext === '.xls' || f.file_type === 'spreadsheet'
}

function isPdfFile(f: ResourceFile): boolean {
  const ext = (f.file_ext ?? '').toLowerCase()
  return ext === '.pdf' || f.file_type === 'pdf'
}

function isAal3XmlFile(f: ResourceFile): boolean {
  const name = f.original_filename.toLowerCase()
  return f.file_type === 'label_table' && (f.file_ext?.toLowerCase() === '.xml' || name.endsWith('.xml'))
}

function deriveBatchDefaultsFromFile(resource: AtlasResource | undefined, file: ResourceFile | undefined) {
  const resourceDefaults = inferBatchDefaultsFromResource(resource ?? null)
  if (!file) return resourceDefaults

  if (isSpreadsheetFile(file) && isMacro96Resource(file, resource)) {
    return {
      batchType: resourceDefaults.batchType,
      parserKey: 'macro96_xlsx',
      fileRoleInBatch: 'macro_region_pool_source',
    }
  }

  if (isAal3XmlFile(file)) {
    return {
      batchType: 'atlas_import',
      parserKey: 'aal3_xml',
      fileRoleInBatch: 'label_dictionary',
    }
  }

  if (isSpreadsheetFile(file) || isPdfFile(file)) {
    return {
      batchType: resourceDefaults.batchType,
      parserKey: resourceDefaults.parserKey,
      fileRoleInBatch: file.file_role || resourceDefaults.fileRoleInBatch,
    }
  }

  return {
    batchType: resourceDefaults.batchType,
    parserKey: resourceDefaults.parserKey,
    fileRoleInBatch: resourceDefaults.fileRoleInBatch,
  }
}

function isMacro96Resource(file: ResourceFile, resource: AtlasResource | undefined): boolean {
  if (file.file_role === 'macro_region_pool_source') return true
  if (file.latest_intermediate_kind === 'macro_region_table') return true
  return inferBatchDefaultsFromResource(resource ?? null).parserKey === 'macro96_xlsx'
}

function shortId(id: string, copyTitle?: string): React.ReactNode {
  return (
    <span className="import-batch-id-copy" onClick={e => e.stopPropagation()} onKeyDown={e => e.stopPropagation()}>
      <code>{id.slice(0, 8)}…</code>
      <CopyButton value={id} label="" title={copyTitle} ariaLabel={copyTitle} />
    </span>
  )
}

function fmtTime(iso: string | null | undefined): string {
  if (!iso) return '—'
  return iso.slice(0, 19).replace('T', ' ')
}

// 鈹€鈹€ Compact batch list 鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€

function BatchListPane({
  batches,
  loading,
  error,
  selectedId,
  total,
  onSelect,
}: {
  batches: ImportBatch[]
  loading: boolean
  error: string | null
  selectedId: string | null
  total?: number
  onSelect: (id: string) => void
}) {
  const { t } = useI18n()

  function handleRowKeyDown(e: React.KeyboardEvent, id: string) {
    if (e.key === 'Enter' || e.key === ' ') {
      e.preventDefault()
      onSelect(id)
    }
  }

  return (
    <div className="import-batches-list-pane">
      <div className="import-batches-list-header">
        <span>{t('batches.batchList')}</span>
        {total !== undefined && (
          <span className="import-batches-list-count">{t('batches.totalBatches', { total })}</span>
        )}
      </div>
      <div className="import-batches-list-hint">{t('batches.clickRowToView')}</div>
      <div className="import-batches-list-scroll">
        {loading && <LoadingState />}
        {!loading && error && <ErrorState error={error} />}
        {!loading && !error && batches.length === 0 && (
          <EmptyState text={t('importBatches.empty')} />
        )}
        {!loading && !error && batches.length > 0 && (
          <div className="import-batch-list-cards">
            {batches.map(b => (
              <div
                key={b.id}
                role="button"
                tabIndex={0}
                className={`import-batch-list-row${selectedId === b.id ? ' import-batch-list-row--selected' : ''}`}
                onClick={() => onSelect(b.id)}
                onKeyDown={e => handleRowKeyDown(e, b.id)}
                aria-current={selectedId === b.id ? 'true' : undefined}
              >
                <div className="import-batch-row-main">
                  <div className="import-batch-row-left">
                    <div className="import-batch-row-title-row">
                      <span className="import-batch-row-title" title={b.batch_code}>{b.batch_code}</span>
                      <span onClick={e => e.stopPropagation()} onKeyDown={e => e.stopPropagation()}>
                        <CopyButton
                          value={b.batch_code}
                          label=""
                          title={t('batches.copyBatchCode')}
                          ariaLabel={t('batches.copyBatchCode')}
                        />
                      </span>
                    </div>
                    <div className="import-batch-row-meta">
                      {shortId(b.id, t('batches.copyBatchId'))}
                      <span className="import-batch-subline-sep">|</span>
                      {shortId(b.resource_id, t('batches.copyResourceId'))}
                      {b.parser_key && (
                        <>
                          <span className="import-batch-subline-sep">|</span>
                          <span className="import-batch-parser-inline">
                            <span className="import-batch-parser-tag" title={b.parser_key}>{b.parser_key}</span>
                            <CopyButton
                              value={b.parser_key}
                              label=""
                              title={t('batches.copyParserKey')}
                              ariaLabel={t('batches.copyParserKey')}
                            />
                          </span>
                        </>
                      )}
                    </div>
                  </div>
                  <div className="import-batch-row-side">
                    <span className="import-batch-status-compact" title={b.status}>
                      <StatusBadge status={b.status} />
                    </span>
                    <span className="import-batch-created-at">{b.created_at.slice(0, 10)}</span>
                  </div>
                </div>
              </div>
            ))}
          </div>
        )}
      </div>
    </div>
  )
}

// ── Warning block ─────────────────────────────────────────────────────────────

function WarningBlock({
  title,
  items,
  variant = 'warning',
}: {
  title: string
  items: string[]
  variant?: 'warning' | 'danger' | 'info'
}) {
  if (items.length === 0) return null
  return (
    <div className={`import-batch-warning import-batch-warning--${variant}`}>
      <div className="import-batch-warning-title">{title}</div>
      <ul className="import-batch-warning-list">
        {items.map((w, i) => <li key={i}>{w}</li>)}
      </ul>
    </div>
  )
}

// 鈹€鈹€ Detail panel 鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€

function BatchDetailPanel({
  batchId,
  refreshTick,
  onReloadList,
  onBatchCancelled,
  setNotice,
}: {
  batchId: string
  refreshTick: number
  onReloadList: () => void
  onBatchCancelled?: () => void
  setNotice: (n: NoticeState) => void
}) {
  const { t } = useI18n()
  const { setIds } = useSessionIds()
  const [tab, setTab] = useState<DetailTab>('overview')
  const [editing, setEditing] = useState(false)
  const [saving, setSaving] = useState(false)
  const [confirm, setConfirm] = useState<ConfirmAction | null>(null)
  const [actionLoading, setActionLoading] = useState(false)

  const { data: detail, loading, error, reload } = useData(
    () => getImportBatch(batchId),
    [batchId, refreshTick],
  )

  const { data: eventsData } = useData(
    () => getImportBatchEvents(batchId, { limit: 100 }),
    [batchId, refreshTick],
  )

  const { data: options } = useData(() => fetchImportBatchOptions(), [])
  const batchTypes = options?.batch_type ?? ['atlas_import']
  const fileRoles = options?.file_role_in_batch ?? ['label_dictionary', 'macro_region_pool_source', 'unknown']

  const [editForm, setEditForm] = useState({
    batch_type: 'atlas_import',
    parser_key: '',
    description: '',
    remark: '',
  })
  const [editBindings, setEditBindings] = useState<FileBindingRow[]>([])

  useEffect(() => {
    if (!detail) return
    setEditForm({
      batch_type: detail.batch_type,
      parser_key: detail.parser_key ?? '',
      description: detail.description ?? '',
      remark: detail.remark ?? '',
    })
    setEditBindings(
      detail.files.map(f => ({
        file_id: f.file_id,
        file_role_in_batch: f.file_role_in_batch,
        sort_order: f.sort_order,
      })),
    )
    setEditing(false)
  }, [detail?.id, detail?.updated_at])

  function goToFiles(fileId: string) {
    if (detail) setIds({ batch_id: detail.id, resource_id: detail.resource_id, file_id: fileId })
    window.location.hash = '#/files'
  }

  async function handleSaveEdit() {
    if (!detail) return
    setSaving(true)
    try {
      if (canEditDescription(detail.status)) {
        const body: Record<string, unknown> = {
          description: editForm.description || null,
          remark: editForm.remark || null,
        }
        if (canEditCoreFields(detail.status)) {
          body.batch_type = editForm.batch_type
          body.parser_key = editForm.parser_key || null
        }
        await updateImportBatch(batchId, body)
      }
      if (canEditFiles(detail.status)) {
        const files: BatchFileBinding[] = editBindings
          .filter(b => b.file_id.trim())
          .map((b, i) => ({
            file_id: b.file_id.trim(),
            file_role_in_batch: b.file_role_in_batch,
            sort_order: b.sort_order ?? i,
          }))
        const res = await updateImportBatchFiles(batchId, files)
        if (res.warnings?.length) {
          setNotice({ type: 'warning', message: res.warnings.join('; ') })
        }
      }
      setNotice({ type: 'success', message: t('batches.updateSuccess') })
      setEditing(false)
      reload()
      onReloadList()
    } catch (e) {
      setNotice({ type: 'error', message: t('batches.updateFailed') + ': ' + (e instanceof ApiError ? e.message : String(e)) })
    } finally {
      setSaving(false)
    }
  }

  async function handleConfirmAction() {
    if (!confirm) return
    setActionLoading(true)
    try {
      if (confirm === 'queue') await queueBatch(batchId)
      else if (confirm === 'start') await startBatch(batchId)
      else await cancelImportBatch(batchId)
      setNotice({
        type: 'success',
        message: confirm === 'queue' ? t('batches.queueSuccess')
          : confirm === 'start' ? t('batches.startSuccess')
          : t('batches.cancelSuccess'),
      })
      if (confirm === 'cancel') {
        onBatchCancelled?.()
      } else {
        reload()
        onReloadList()
      }
    } catch (e) {
      setNotice({ type: 'error', message: e instanceof ApiError ? e.message : String(e) })
    } finally {
      setActionLoading(false)
      setConfirm(null)
    }
  }

  if (loading) {
    return <div className="import-batches-detail-pane import-batches-detail-loading">{t('common.loading')}</div>
  }
  if (error) {
    return <div className="import-batches-detail-pane import-batches-detail-error">{error}</div>
  }
  if (!detail) return null

  const readOnlyCore = !canEditCoreFields(detail.status)
  const events = eventsData?.items ?? detail.recent_events ?? []
  const fileWarnings = detail.files.filter(f => f.warning).map(f => f.warning as string)
  const allWarnings = [...(detail.warnings ?? []), ...fileWarnings]

  return (
    <div className="import-batches-detail-pane">
      <div className="import-batch-detail-header">
        <div className="import-batch-detail-title-row">
          <div className="import-batch-detail-title">
            <h2 className="import-batch-detail-code">{detail.batch_code}</h2>
            <StatusBadge status={detail.status} />
          </div>
          <div className="import-batch-detail-meta-row">
            <span>{shortId(detail.id, t('batches.copyBatchId'))}</span>
            <span className="import-batch-subline-sep">|</span>
            <span>{shortId(detail.resource_id, t('batches.copyResourceId'))}</span>
          </div>
          <div className="import-batch-detail-meta-row import-batch-detail-meta-row--secondary">
            <span>{detail.batch_type}</span>
            <span className="import-batch-subline-sep">|</span>
            <span>{detail.parser_key ?? '—'}</span>
            <span className="import-batch-subline-sep">|</span>
            <span>{fmtTime(detail.created_at)}</span>
            <span className="import-batch-subline-sep">|</span>
            <span>{fmtTime(detail.updated_at)}</span>
          </div>
        </div>
      </div>

      <div className="import-batch-action-row">
        <span className="import-batch-action-label">{t('batches.batchActions')}</span>
        <div className="import-batch-action-buttons">
          {detail.status === 'created' && (
            <ActionButton label={t('batches.queue')} variant="default" onClick={() => setConfirm('queue')} />
          )}
          {detail.status === 'queued' && (
            <ActionButton label={t('batches.start')} variant="default" onClick={() => setConfirm('start')} />
          )}
          {canEditCoreFields(detail.status) && !editing && (
            <ActionButton label={t('batches.editBatch')} variant="default" onClick={() => setEditing(true)} />
          )}
          {canCancelBatch(detail.status) && !TERMINAL_STATUSES.has(detail.status) && (
            <ActionButton label={t('batches.cancelBatch')} variant="danger" onClick={() => setConfirm('cancel')} />
          )}
          <CopyButton value={detail.id} title={t('batches.copyBatchId')} ariaLabel={t('batches.copyBatchId')} />
        </div>
      </div>

      {readOnlyCore && detail.status !== 'cancelled' && (
        <WarningBlock title={t('batches.readonlyNotice')} items={[t('batches.cannotEditAfterRunning')]} variant="info" />
      )}

      <WarningBlock title={t('batches.warningTitle')} items={allWarnings} variant="warning" />

      <div className="import-batch-tabs">
        {(['overview', 'pipeline', 'files', 'events', 'raw'] as DetailTab[]).map(k => (
          <button
            key={k}
            type="button"
            className={`import-batch-tab${tab === k ? ' active' : ''}`}
            onClick={() => setTab(k)}
          >
            {k === 'pipeline' ? '导入流程' : t(`batches.${k === 'raw' ? 'rawJson' : k}`)}
          </button>
        ))}
      </div>

      <div className={`import-batch-tab-content import-batch-tab-content--${tab}`}>
        {tab === 'pipeline' && (
          <PipelineTab
            batchId={batchId}
            status={detail.status}
            parserKey={detail.parser_key ?? ''}
            onReload={() => { reload(); onReloadList() }}
            setNotice={setNotice}
          />
        )}
        {tab === 'overview' && (
          <OverviewTab
            detail={detail}
            editing={editing}
            editForm={editForm}
            editBindings={editBindings}
            batchTypes={batchTypes}
            fileRoles={fileRoles}
            saving={saving}
            onEditForm={setEditForm}
            onEditBindings={setEditBindings}
            onSave={handleSaveEdit}
            onCancelEdit={() => setEditing(false)}
            t={t}
          />
        )}
        {tab === 'files' && <FilesTab files={detail.files} onGoToFiles={goToFiles} t={t} />}
        {tab === 'events' && <EventsTab events={events} t={t} />}
        {tab === 'raw' && <RawJsonTab detail={detail} events={events} setNotice={setNotice} t={t} />}
      </div>

      <ConfirmDialog
        open={confirm === 'cancel'}
        title={t('batches.cancelConfirmTitle')}
        message={t('batches.cancelConfirmMessage')}
        onConfirm={handleConfirmAction}
        onCancel={() => setConfirm(null)}
        loading={actionLoading}
      />
      <ConfirmDialog
        open={confirm === 'queue' || confirm === 'start'}
        title={t('importBatches.confirmTitle', { action: confirm ? t(`batches.${confirm}`) : '' })}
        message={t('importBatches.confirmMessage', { id: batchId.slice(0, 12), action: confirm ?? '' })}
        onConfirm={handleConfirmAction}
        onCancel={() => setConfirm(null)}
        loading={actionLoading}
      />
    </div>
  )
}

function OverviewTab({
  detail,
  editing,
  editForm,
  editBindings,
  batchTypes,
  fileRoles,
  saving,
  onEditForm,
  onEditBindings,
  onSave,
  onCancelEdit,
  t,
}: {
  detail: ImportBatchDetail
  editing: boolean
  editForm: { batch_type: string; parser_key: string; description: string; remark: string }
  editBindings: FileBindingRow[]
  batchTypes: string[]
  fileRoles: string[]
  saving: boolean
  onEditForm: React.Dispatch<React.SetStateAction<typeof editForm>>
  onEditBindings: React.Dispatch<React.SetStateAction<FileBindingRow[]>>
  onSave: () => void
  onCancelEdit: () => void
  t: (k: string) => string
}) {
  if (editing) {
    return (
      <div className="import-batch-overview-grid import-batch-edit-form">
        {canEditCoreFields(detail.status) && (
          <div className="form-row">
            <div className="form-field">
              <label className="form-label">{t('batches.batchType')}</label>
              <select className="form-select" value={editForm.batch_type}
                onChange={e => onEditForm(f => ({ ...f, batch_type: e.target.value }))}>
                {batchTypes.map(v => <option key={v} value={v}>{v}</option>)}
              </select>
            </div>
            <div className="form-field">
              <label className="form-label">{t('batches.parserKey')}</label>
              <input className="form-input" value={editForm.parser_key}
                onChange={e => onEditForm(f => ({ ...f, parser_key: e.target.value }))} />
            </div>
          </div>
        )}
        {canEditDescription(detail.status) && (
          <div className="form-row">
            <div className="form-field">
              <label className="form-label">{t('common.description')}</label>
              <input className="form-input" value={editForm.description}
                onChange={e => onEditForm(f => ({ ...f, description: e.target.value }))} />
            </div>
            <div className="form-field">
              <label className="form-label">{t('common.remark')}</label>
              <input className="form-input" value={editForm.remark}
                onChange={e => onEditForm(f => ({ ...f, remark: e.target.value }))} />
            </div>
          </div>
        )}
        {canEditFiles(detail.status) && (
          <div>
            <div className="import-batch-section-label">{t('batches.boundFiles')}</div>
            {editBindings.map((b, i) => (
              <div key={i} className="batch-file-binding-row">
                <input className="form-input" value={b.file_id}
                  onChange={e => onEditBindings(rows => rows.map((r, j) => j === i ? { ...r, file_id: e.target.value } : r))} />
                <select className="form-select" value={b.file_role_in_batch}
                  onChange={e => onEditBindings(rows => rows.map((r, j) => j === i ? { ...r, file_role_in_batch: e.target.value } : r))}>
                  {fileRoles.map(r => <option key={r} value={r}>{formatFileRoleInBatchLabel(r, t)}</option>)}
                </select>
                <input className="form-input" type="number" style={{ width: 70 }} value={b.sort_order}
                  onChange={e => onEditBindings(rows => rows.map((r, j) => j === i ? { ...r, sort_order: Number(e.target.value) } : r))} />
              </div>
            ))}
          </div>
        )}
        <div className="import-batch-action-row">
          <ActionButton label={t('common.save')} variant="primary" onClick={onSave} loading={saving} />
          <ActionButton label={t('common.cancel')} variant="default" onClick={onCancelEdit} />
        </div>
      </div>
    )
  }

  return (
    <div className="import-batch-overview-grid">
      <KeyValuePanel entries={[
        { label: t('batches.batchCode'), value: detail.batch_code },
        { label: 'batch_id', value: shortId(detail.id, t('batches.copyBatchId')) },
        { label: t('batches.resourceId'), value: shortId(detail.resource_id, t('batches.copyResourceId')) },
        { label: t('batches.batchType'), value: detail.batch_type },
        { label: t('batches.parserKey'), value: detail.parser_key ?? '—' },
        { label: t('batches.status'), value: <StatusBadge status={detail.status} /> },
        { label: t('batches.createdAt'), value: fmtTime(detail.created_at) },
        { label: t('batches.updatedAt'), value: fmtTime(detail.updated_at) },
      ]} />
      {detail.next_allowed_actions?.length > 0 && (
        <div className="import-batch-next-actions">
          <strong>{t('batches.nextActions')}:</strong>{' '}
          {detail.next_allowed_actions.join(', ')}
        </div>
      )}
    </div>
  )
}

function FilesTab({
  files,
  onGoToFiles,
  t,
}: {
  files: ImportBatchFileEnriched[]
  onGoToFiles: (id: string) => void
  t: (k: string) => string
}) {
  if (files.length === 0) {
    return <div className="import-batch-files-table import-batch-tab-empty">{t('batches.noBoundFiles')}</div>
  }

  return (
    <div className="import-batch-files-table">
      <table>
        <thead>
          <tr>
            <th>{t('batches.fileId')}</th>
            <th>{t('batches.colFilename')}</th>
            <th>{t('batches.fileRoleInBatch')}</th>
            <th>{t('batches.orderIndex')}</th>
            <th>{t('batches.fileStatus')}</th>
            <th>{t('batches.intermediateStatus')}</th>
            <th>{t('batches.colCanParse')}</th>
            <th></th>
          </tr>
        </thead>
        <tbody>
          {files.map(f => {
            const inactive = f.file_status && f.file_status !== 'active'
            const missingInt = f.intermediate_status === 'missing'
            return (
              <tr key={f.id} className={inactive ? 'import-batch-file-row--inactive' : undefined}>
                <td>{shortId(f.file_id, t('batches.fileId'))}</td>
                <td className="import-batch-filename-cell" title={f.original_filename ?? undefined}>
                  {f.original_filename ?? '—'}
                </td>
                <td>{f.file_role_in_batch}</td>
                <td>{f.sort_order}</td>
                <td>
                  <StatusBadge status={f.file_status ?? 'unknown'} />
                  {inactive && <div className="import-batch-file-hint import-batch-file-hint--danger">{t('batches.cannotParse')}</div>}
                </td>
                <td>
                  <span className={missingInt ? 'import-batch-intermediate-missing' : undefined}>
                    {f.intermediate_status ?? '—'}
                  </span>
                  {missingInt && (
                    <div className="import-batch-file-hint import-batch-file-hint--warn">{t('batches.intermediateSuggest')}</div>
                  )}
                  {f.latest_intermediate_artifact_id && (
                    <div className="import-batch-subline">{shortId(f.latest_intermediate_artifact_id)}</div>
                  )}
                </td>
                <td>{f.can_parse ? t('common.yes') : t('common.no')}</td>
                <td>
                  <ActionButton label={t('batches.goToFiles')} variant="default" onClick={() => onGoToFiles(f.file_id)} />
                </td>
              </tr>
            )
          })}
        </tbody>
      </table>
    </div>
  )
}

function EventsTab({ events, t }: { events: ImportBatchEvent[]; t: (k: string) => string }) {
  const [expanded, setExpanded] = useState<string | null>(null)

  if (events.length === 0) {
    return <div className="import-batch-events-list import-batch-tab-empty">{t('batches.noEvents')}</div>
  }

  return (
    <div className="import-batch-events-list">
      {events.map(e => {
        const hasMeta = e.payload_json && Object.keys(e.payload_json).length > 0
        const isOpen = expanded === e.id
        return (
          <div key={e.id} className="import-batch-event-row">
            <div className="import-batch-event-main">
              <span className="import-batch-event-time">{fmtTime(e.created_at)}</span>
              <span className="import-batch-event-type">{e.event_type}</span>
              {e.from_status && (
                <span className="import-batch-event-transition">
                  {e.from_status} → {e.to_status ?? '—'}
                </span>
              )}
              <span className="import-batch-event-message">{e.message ?? '—'}</span>
              {hasMeta && (
                <button type="button" className="import-batch-event-meta-toggle"
                  onClick={() => setExpanded(isOpen ? null : e.id)}>
                  {t('batches.eventMetadata')}{isOpen ? ' ▲' : ' ▼'}
                </button>
              )}
            </div>
            {isOpen && hasMeta && (
              <pre className="import-batch-event-meta">{JSON.stringify(e.payload_json, null, 2)}</pre>
            )}
          </div>
        )
      })}
    </div>
  )
}

function RawJsonTab({
  detail,
  events,
  setNotice,
  t,
}: {
  detail: ImportBatchDetail
  events: ImportBatchEvent[]
  setNotice: (n: NoticeState) => void
  t: (k: string) => string
}) {
  const json = JSON.stringify({ batch: detail, files: detail.files, events }, null, 2)

  function copyJson() {
    navigator.clipboard.writeText(json).then(() => {
      setNotice({ type: 'success', message: t('batches.rawJsonCopied') })
    }).catch(() => {})
  }

  return (
    <div className="import-batch-raw-json-wrap">
      <div className="import-batch-raw-json-toolbar">
        <ActionButton label={t('batches.copyBatchJson')} variant="default" onClick={copyJson} />
      </div>
      <pre className="import-batch-raw-json">{json}</pre>
    </div>
  )
}

/* ── Pipeline Tab ──────────────────────────────────────────────────────────── */
import { parseAal3, parseMacro96Batch, generateCandidates, generateMacro96Candidates, queueBatch as queueBatchAction, startBatch as startBatchAction } from '../api/endpoints'
import { timelineStepState, PIPELINE_TIMELINE_STEPS } from '../utils/importPipelineHelpers'

const PIPELINE_STEPS_TRUNCATED = PIPELINE_TIMELINE_STEPS.filter(s => s.statusRank <= 4)

interface PipelineTabProps {
  batchId: string
  status: string
  parserKey: string
  onReload: () => void
  setNotice: (n: NoticeState) => void
}

function PipelineTab({ batchId, status, parserKey, onReload, setNotice }: PipelineTabProps) {
  const { t } = useI18n()
  const [actionLoading, setActionLoading] = useState<string | null>(null)

  const stepState = useMemo(() => {
    return PIPELINE_STEPS_TRUNCATED.map(s => ({
      ...s,
      state: timelineStepState(s.statusRank, status),
    }))
  }, [status])

  async function doAction(actionKey: string, action: () => Promise<unknown>) {
    setActionLoading(actionKey)
    try {
      await action()
      setNotice({ type: 'success', message: t('batches.actionSuccess') })
      onReload()
    } catch (e) {
      setNotice({ type: 'error', message: formatApiErrorMessage(e) })
    } finally {
      setActionLoading(null)
    }
  }

  const isMacro96 = parserKey === 'macro96_xlsx'
  const canRunActions = !['completed', 'failed', 'cancelled'].includes(status)

  return (
    <div className="import-batch-pipeline-tab">
      {/* Timeline */}
      <div className="import-batch-pipeline-section">
        <h4 className="import-batch-pipeline-section-title">导入流程</h4>
        <div className="import-batch-timeline">
          {stepState.map((s, i) => (
            <div key={s.key} className={`import-batch-timeline-step import-batch-timeline-step--${s.state}`}>
              <div className="import-batch-timeline-marker">
                {s.state === 'done' ? '●' : s.state === 'current' ? '◎' : '○'}
              </div>
              <div>
                <div className="import-batch-timeline-label">{t(s.labelKey)}</div>
                <div className="import-batch-timeline-status">
                  {s.state === 'done' ? '已完成' : s.state === 'current' ? '处理中' : '待处理'}
                </div>
              </div>
              {i < stepState.length - 1 && <div className="import-batch-timeline-connector" />}
            </div>
          ))}
        </div>
      </div>

      {/* Actions */}
      {canRunActions && (
        <div className="import-batch-pipeline-section">
          <h4 className="import-batch-pipeline-section-title">操作</h4>
          <div className="import-batch-pipeline-actions">
            {status === 'created' && (
              <ActionButton label="队列 (Queue)" variant="default"
                loading={actionLoading === 'queue'}
                onClick={() => doAction('queue', () => queueBatchAction(batchId))} />
            )}
            {status === 'queued' && (
              <ActionButton label="启动 (Start)" variant="default"
                loading={actionLoading === 'start'}
                onClick={() => doAction('start', () => startBatchAction(batchId))} />
            )}
            {['queued', 'running'].includes(status) && isMacro96 && (
              <ActionButton label="解析 Macro96" variant="default"
                loading={actionLoading === 'parse_macro96'}
                onClick={() => doAction('parse_macro96', () => parseMacro96Batch(batchId))} />
            )}
            {['running', 'parsed'].includes(status) && !isMacro96 && (
              <ActionButton label="解析 AAL3" variant="default"
                loading={actionLoading === 'parse_aal3'}
                onClick={() => doAction('parse_aal3', () => parseAal3(batchId))} />
            )}
            {status === 'parsed' && (
              <ActionButton label="生成候选脑区" variant="default"
                loading={actionLoading === 'generate_candidates'}
                onClick={() => doAction('generate_candidates',
                  () => isMacro96 ? generateMacro96Candidates(batchId) : generateCandidates(batchId))} />
            )}
          </div>
        </div>
      )}

      {/* Governance Navigation */}
      <div className="import-batch-pipeline-section">
        <h4 className="import-batch-pipeline-section-title">治理链路</h4>
        <p className="import-batch-pipeline-hint">数据准备完成后，请到以下页面进行校验和审核</p>
        <div className="import-batch-pipeline-nav">
          <a className="btn btn-sm" href="#/rule-validation?batch_id={batchId}">规则校验</a>
          <a className="btn btn-sm" href="#/human-review">人工审核</a>
          <a className="btn btn-sm" href="#/promotions">晋升</a>
          <a className="btn btn-sm" href="#/data-center?tab=mirror">Mirror KG 浏览</a>
          <a className="btn btn-sm" href="#/data-center?tab=final">Final KG 浏览</a>
        </div>
      </div>

      {/* Data Center Link */}
      <div className="import-batch-pipeline-section">
        <h4 className="import-batch-pipeline-section-title">数据查看</h4>
        <p className="import-batch-pipeline-hint">各阶段数据在 Data Center 中统一查看</p>
        <div className="import-batch-pipeline-nav">
          <a className="btn btn-sm" href={'#/data-center?tab=raw&batch_id=' + batchId}>Raw 数据</a>
          <a className="btn btn-sm" href={'#/data-center?tab=candidates&batch_id=' + batchId}>候选脑区</a>
        </div>
      </div>
    </div>
  )
}

// 鈹€鈹€ Main page 鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€

export function ImportBatchesPage() {
  const { t } = useI18n()
  const { granularity } = useGlobalGranularity()
  const { setIds } = useSessionIds()
  const [isCreateModalOpen, setIsCreateModalOpen] = useState(false)
  const [statusFilter, setStatusFilter] = useState('')
  const [resourceFilter, setResourceFilter] = useState('')
  const [parserFilter, setParserFilter] = useState('')
  const [selectedId, setSelectedId] = useState<string | null>(() => readSessionIds().batch_id ?? null)
  const [notice, setNotice] = useState<NoticeState | null>(null)
  const [tick, setTick] = useState(0)
  const onClose = useCallback(() => setNotice(null), [])
  const reload = () => setTick(x => x + 1)

  const { data, loading, error } = useData(
    () => fetchImportBatches({
      status: statusFilter || undefined,
      resource_id: resourceFilter.trim() || undefined,
      parser_key: parserFilter.trim() || undefined,
      limit: 100,
      granularity_level: granularity || undefined,
    }),
    [statusFilter, resourceFilter, parserFilter, tick, granularity],
  )

  const visibleBatches = useMemo(
    () => filterWorkbenchBatches(data?.items ?? []),
    [data],
  )

  useEffect(() => {
    if (loading || !data) return
    if (selectedId && !visibleBatches.some(b => b.id === selectedId)) {
      setSelectedId(null)
      setIds({ batch_id: undefined })
    }
  }, [loading, data, visibleBatches, selectedId, setIds])

  function handleBatchCancelled() {
    setSelectedId(null)
    setIds({ batch_id: undefined })
    reload()
  }

  function handleBatchCreated(batch: ImportBatchDetail) {
    setSelectedId(batch.id)
    setIds({ batch_id: batch.id, resource_id: batch.resource_id })
    reload()
    setIsCreateModalOpen(false)
  }

  return (
    <div className="import-batches-page">
      <PageHeader
        title={t('batches.title')}
        description={t('batches.subtitle')}
        readonly={false}
        actions={
          <ActionButton
            label={t('batches.createBatch')}
            variant="primary"
            onClick={() => setIsCreateModalOpen(true)}
          />
        }
      />
      <Notice notice={notice} onClose={onClose} />

      {isCreateModalOpen && (
        <CreateBatchModal
          onClose={() => setIsCreateModalOpen(false)}
          onCreated={handleBatchCreated}
          setNotice={setNotice}
        />
      )}

      <div className="import-batches-toolbar">
        <select className="import-batches-filter-status" value={statusFilter}
          onChange={e => setStatusFilter(e.target.value)}>
          <option value="">{t('batches.status')}: {t('common.all')}</option>
          {WORKBENCH_BATCH_STATUS_FILTER_OPTIONS.map(s =>
            <option key={s} value={s}>{s}</option>)}
        </select>
        <input
          className="import-batches-filter-resource form-input"
          placeholder={t('batches.resourceId')}
          value={resourceFilter}
          onChange={e => setResourceFilter(e.target.value)}
        />
        <input
          className="import-batches-filter-parser form-input"
          placeholder={t('batches.parserKey')}
          value={parserFilter}
          onChange={e => setParserFilter(e.target.value)}
        />
        <ActionButton label={t('common.refresh')} variant="default" onClick={reload} />
      </div>

      <div className="import-batches-management-layout">
        <BatchListPane
          batches={visibleBatches}
          loading={loading}
          error={error}
          selectedId={selectedId}
          total={visibleBatches.length}
          onSelect={setSelectedId}
        />
        {selectedId ? (
          <BatchDetailPanel
            key={selectedId}
            batchId={selectedId}
            refreshTick={tick}
            onReloadList={reload}
            onBatchCancelled={handleBatchCancelled}
            setNotice={setNotice}
          />
        ) : (
          <div className="import-batches-detail-pane import-batches-detail-empty">
            <div className="import-batches-empty-icon">馃搵</div>
            <div>{t('batches.selectBatchToView')}</div>
          </div>
        )}
      </div>
    </div>
  )
}
