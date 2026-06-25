import { useState, useCallback, useRef, useMemo, useEffect, type ChangeEvent } from 'react'
import { PageHeader } from '../components/PageHeader'
import { DataTable, type Column } from '../components/DataTable'
import { StatusBadge } from '../components/StatusBadge'
import { ActionButton } from '../components/ActionButton'
import { Notice, type NoticeState } from '../components/Notice'
import { ConfirmDialog } from '../components/ConfirmDialog'
import { KeyValuePanel } from '../components/KeyValuePanel'
import { useData } from '../hooks/useData'
import {
  deleteFile,
  getFile,
  getFileDownloadUrl,
  getFileOptions,
  getFilePreview,
  getFileIntermediateStatus,
  getIntermediatePreview,
  listNormalizationRuns,
  normalizeFile,
  listResourceFiles,
  listResources,
  restoreFile,
  updateFile,
  uploadResourceFile,
  uploadWorkspaceFile,
  listWorkspaceFiles,
  getWorkspaceFile,
  updateWorkspaceFile,
  archiveWorkspaceFile,
  getWorkspaceFilePreview,
  getWorkspaceFileDownloadUrl,
  attachWorkspaceFileToResource,
  type AtlasResource,
  type FileOptions,
  type FilePreview,
  type ResourceFile,
  type FileIntermediateStatus,
  type IntermediatePreview,
  type IntermediateArtifact,
  type NormalizationRun,
  type WorkspaceFile,
  type WorkspaceFileAttachRequest,
} from '../api/endpoints'
import { ApiError } from '../api/client'
import { readSessionIds, useSessionIds } from '../hooks/useSessionIds'
import { CopyButton } from '../components/CopyButton'
import { useI18n } from '../i18n-context'
import {
  duplicateDetailIsInactive,
  isMacro96DuplicateFile,
  parseDuplicateFileDetail,
  type DuplicateFileDetail,
} from '../utils/duplicateFileError'
type FileMode = 'resource' | 'workspace'
type PreviewTab = 'preview' | 'metadata' | 'raw' | 'intermediate'

const FILE_MODE_STORAGE_KEY = 'ngiq_files_mode'

function readHashResourceId(): string {
  const hash = window.location.hash.slice(1)
  const q = hash.indexOf('?')
  if (q < 0) return ''
  return new URLSearchParams(hash.slice(q + 1)).get('resource_id') ?? ''
}

function formatResourceLabel(r: AtlasResource): string {
  return `${r.source_atlas} | ${r.resource_code} | ${r.source_version} | ${r.granularity_level} | ${r.status}`
}

function resourceMatchesSearch(r: AtlasResource, query: string): boolean {
  const q = query.trim().toLowerCase()
  if (!q) return true
  return (
    r.resource_code.toLowerCase().includes(q)
    || r.source_atlas.toLowerCase().includes(q)
    || r.source_version.toLowerCase().includes(q)
    || (r.cn_name ?? '').toLowerCase().includes(q)
    || (r.en_name ?? '').toLowerCase().includes(q)
  )
}

interface FileEditForm {
  file_type: string
  file_role: string
  description: string
  remark: string
  status: string
}

const FALLBACK_FILE_OPTIONS: FileOptions = {
  file_type: ['nifti', 'label_table', 'spreadsheet', 'pdf', 'ontology', 'json', 'text', 'connectivity_matrix', 'image', 'other'],
  file_role: ['primary_atlas_volume', 'label_dictionary', 'documentation', 'ontology_source', 'connectivity_source', 'evidence_source', 'metadata', 'auxiliary', 'macro_region_pool_source', 'unknown'],
  status: ['active', 'archived'],
  preview_supported_types: ['.xml', '.json', '.txt', '.csv', '.tsv', '.md', '.png', '.jpg'],
}

function formatBytes(value: number | null | undefined): string {
  const size = value ?? 0
  if (size < 1024) return `${size} B`
  if (size < 1024 * 1024) return `${(size / 1024).toFixed(1)} KB`
  return `${(size / 1024 / 1024).toFixed(2)} MB`
}

function shortText(value: string, length: number): string {
  return value.length > length ? `${value.slice(0, length)}...` : value
}

type IntermediateColStatus = 'ready' | 'missing' | 'failed' | 'archived' | 'unknown'

function pickIntermediateStatus(
  file: ResourceFile,
  selectedId: string | undefined,
  live: FileIntermediateStatus | null,
): IntermediateColStatus {
  if (file.id === selectedId && live?.status) {
    return live.status as IntermediateColStatus
  }
  if (file.intermediate_status) {
    return file.intermediate_status as IntermediateColStatus
  }
  return 'unknown'
}

function intermediateStatusLabel(status: IntermediateColStatus, t: (key: string) => string): string {
  switch (status) {
    case 'ready': return t('files.intermediateReady')
    case 'failed': return t('files.intermediateFailed')
    case 'missing': return t('files.intermediateMissing')
    case 'archived': return t('files.intermediateArchived')
    default: return t('files.intermediateUnknown')
  }
}

function IntermediateStatusBadge({ status, t }: { status: IntermediateColStatus; t: (key: string) => string }) {
  return (
    <span className={`intermediate-status-badge status-${status}`}>
      {intermediateStatusLabel(status, t)}
    </span>
  )
}

function normalizeExtension(filename: string): string {
  const lower = filename.toLowerCase()
  if (lower.endsWith('.nii.gz')) return '.nii.gz'
  const dot = lower.lastIndexOf('.')
  return dot >= 0 ? lower.slice(dot) : ''
}

function suggestFileClassification(
  filename: string,
  opts: FileOptions,
): { fileType: string; fileRole: string; hintKey?: string } {
  const ext = normalizeExtension(filename)
  const name = filename.toLowerCase().replace(/_/g, ' ')
  const pick = (ft: string, fr: string, hintKey?: string) => ({
    fileType: opts.file_type.includes(ft) ? ft : 'other',
    fileRole: opts.file_role.includes(fr) ? fr : 'unknown',
    hintKey,
  })
  if (ext === '.xml') return pick('label_table', 'label_dictionary')
  if (ext === '.xlsx' || ext === '.xls') {
    if (name.includes('brain volume')) return pick('spreadsheet', 'macro_region_pool_source', 'files.suggestBrainVolumeList')
    return pick('spreadsheet', 'auxiliary')
  }
  if (ext === '.csv' || ext === '.tsv') return pick('label_table', 'label_dictionary')
  if (ext === '.pdf') return pick('pdf', 'documentation')
  if (ext === '.nii' || ext === '.nii.gz') return pick('nifti', 'primary_atlas_volume')
  if (ext === '.json') return pick('json', 'metadata')
  if (ext === '.owl' || ext === '.rdf' || ext === '.ttl') return pick('ontology', 'ontology_source')
  if (['.png', '.jpg', '.jpeg', '.webp', '.gif'].includes(ext)) return pick('image', 'auxiliary')
  if (['.mat', '.npy', '.npz'].includes(ext)) return pick('connectivity_matrix', 'connectivity_source')
  if (ext === '.txt' || ext === '.md') return pick('text', 'documentation')
  return pick('other', 'unknown')
}

function isBinarySpreadsheetFile(file: { original_filename?: string | null; file_type?: string | null; mime_type?: string | null } | null | undefined): boolean {
  if (!file) return false
  const name = (file.original_filename || '').toLowerCase()
  const type = (file.file_type || '').toLowerCase()
  const mime = (file.mime_type || '').toLowerCase()
  return (
    name.endsWith('.xlsx')
    || name.endsWith('.xls')
    || type === 'spreadsheet'
    || mime.includes('spreadsheet')
    || mime.includes('excel')
  )
}

function shouldRenderTextPreview(file: { original_filename?: string | null; file_type?: string | null; mime_type?: string | null } | null | undefined): boolean {
  if (!file) return false
  const name = (file.original_filename || '').toLowerCase()
  const type = (file.file_type || '').toLowerCase()
  if (isBinarySpreadsheetFile(file)) return false
  if (name.endsWith('.nii') || name.endsWith('.nii.gz')) return false
  if (name.endsWith('.zip')) return false
  if (type === 'binary') return false
  if (type === 'spreadsheet') return false
  return true
}

function looksLikeBinaryZipText(content: string | null | undefined): boolean {
  if (!content) return false
  return content.startsWith('PK') && (content.includes('docProps') || content.includes('xl/'))
}

function isSpreadsheetIntermediateReady(
  file: ResourceFile | null,
  live: FileIntermediateStatus | null,
): boolean {
  if (!file) return false
  if (file.intermediate_status === 'ready') return true
  if (live?.status === 'ready' || live?.has_active_intermediate) return true
  return live?.latest_artifact_kind === 'macro_region_table'
}

function pickIntermediateKind(
  file: ResourceFile,
  selectedId: string | undefined,
  live: FileIntermediateStatus | null,
): string | null {
  if (file.id === selectedId && live?.latest_artifact_kind) return live.latest_artifact_kind
  return file.latest_intermediate_kind ?? null
}

function IntermediatePreviewTable({ columns, rows }: { columns: string[]; rows: Record<string, unknown>[] }) {
  if (!rows.length) return null
  return (
    <div className="intermediate-table-wrap">
      <table className="intermediate-preview-table">
        <thead>
          <tr>{columns.map(c => <th key={c}>{c}</th>)}</tr>
        </thead>
        <tbody>
          {rows.map((row, i) => (
            <tr key={i}>
              {columns.map(c => <td key={c}>{String(row[c] ?? '')}</td>)}
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  )
}

function renderArtifactDetail(artifact: IntermediateArtifact, t: (key: string, vars?: Record<string, string>) => string) {
  const content = artifact.content_jsonb ?? {}
  const preview = artifact.preview_jsonb ?? {}
  const meta = artifact.metadata_jsonb ?? {}

  if (artifact.artifact_kind === 'spreadsheet_workbook') {
    const sheets = (content.sheets as Array<Record<string, unknown>> | undefined) ?? []
    const primary = sheets[0]
    const previewRows = (preview.rows_preview as Record<string, unknown>[] | undefined)
      ?? (primary?.rows_preview as Record<string, unknown>[] | undefined) ?? []
    const cols = (preview.columns as string[] | undefined)
      ?? (primary?.columns as string[] | undefined) ?? []
    return (
      <div className="intermediate-artifact-block">
        <div className="intermediate-artifact-title">{t('files.artifactSpreadsheetWorkbook')}</div>
        <div className="intermediate-meta-grid">
          <span className="intermediate-meta-label">{t('files.sheetCount')}</span>
          <span className="intermediate-meta-value">{String(meta.sheet_count ?? sheets.length)}</span>
          {primary && (
            <>
              <span className="intermediate-meta-label">{t('files.primarySheet')}</span>
              <span className="intermediate-meta-value">{String(preview.primary_sheet ?? primary.sheet_name ?? '')}</span>
              <span className="intermediate-meta-label">{t('files.intermediateRows')}</span>
              <span className="intermediate-meta-value">{String(primary.row_count ?? artifact.row_count ?? '')}</span>
            </>
          )}
        </div>
        {cols.length > 0 && <div className="intermediate-section-title">{t('files.columns')}: {cols.join(', ')}</div>}
        <IntermediatePreviewTable columns={cols} rows={previewRows} />
      </div>
    )
  }

  if (artifact.artifact_kind === 'macro_region_table') {
    const rows = (content.rows as Record<string, unknown>[] | undefined)
      ?? (preview.rows_preview as Record<string, unknown>[] | undefined)
      ?? []
    const cols = ['region_index', 'en_name', 'cn_name']
    const schema = String(content.schema ?? meta.schema ?? 'macro_region_table_v1')
    const rowCount = Number(artifact.row_count ?? content.row_count ?? rows.length)
    const sourceFormat = String(content.source_format ?? meta.source_format ?? 'xlsx')
    const sourceSheet = String(content.source_sheet ?? preview.source_sheet ?? '')
    return (
      <div className="intermediate-artifact-block file-macro-table-preview">
        <div className="intermediate-artifact-title">{t('files.macroRegionTablePreview')}</div>
        <div className="file-intermediate-summary intermediate-meta-grid">
          <span className="intermediate-meta-label">schema</span>
          <span className="intermediate-meta-value">{schema}</span>
          <span className="intermediate-meta-label">{t('files.intermediateRows')}</span>
          <span className="intermediate-meta-value">{rowCount}</span>
          <span className="intermediate-meta-label">source_format</span>
          <span className="intermediate-meta-value">{sourceFormat}</span>
          {sourceSheet && (
            <>
              <span className="intermediate-meta-label">{t('files.primarySheet')}</span>
              <span className="intermediate-meta-value">{sourceSheet}</span>
            </>
          )}
        </div>
        <div className="file-macro-table-wrapper">
          <IntermediatePreviewTable columns={cols} rows={rows} />
        </div>
        {rows.length === 0 && (
          <pre className="files-code-preview">{JSON.stringify(preview ?? content, null, 2)}</pre>
        )}
      </div>
    )
  }

  if (artifact.artifact_kind === 'pdf_metadata') {
    return (
      <div className="intermediate-artifact-block">
        <div className="intermediate-artifact-title">{t('files.artifactPdfMetadata')}</div>
        <div className="intermediate-meta-grid">
          {meta.page_count != null && (
            <>
              <span className="intermediate-meta-label">{t('files.pageCount')}</span>
              <span className="intermediate-meta-value">{String(meta.page_count)}</span>
            </>
          )}
          <span className="intermediate-meta-label">{t('files.textExtraction')}</span>
          <span className="intermediate-meta-value">{String(meta.text_extraction ?? 'not_implemented')}</span>
        </div>
        <div className="intermediate-label-note">{t('files.pdfNoOcrNote')}</div>
      </div>
    )
  }

  if (artifact.artifact_kind === 'binary_metadata') {
    return (
      <div className="intermediate-artifact-block">
        <div className="intermediate-artifact-title">{t('files.artifactBinaryMetadata')}</div>
        <div className="intermediate-hint-bar intermediate-hint-warning">{t('files.binaryMetadataOnlyNote')}</div>
      </div>
    )
  }

  if (artifact.artifact_kind === 'label_table') {
    const rows = (preview.rows_preview as Record<string, unknown>[] | undefined) ?? []
    const cols = (content.columns as string[] | undefined) ?? []
    return (
      <div className="intermediate-artifact-block">
        <div className="intermediate-artifact-title">{t('files.artifactLabelTable')}</div>
        <div className="intermediate-label-note">{t('files.intermediateLabelTableNote')}</div>
        <IntermediatePreviewTable columns={cols.slice(0, 6)} rows={rows} />
      </div>
    )
  }

  return (
    <div className="intermediate-artifact-block">
      <div className="intermediate-artifact-title">{artifact.artifact_kind}</div>
      <pre className="files-code-preview">{JSON.stringify(preview ?? meta ?? content, null, 2)}</pre>
    </div>
  )
}

function getErrorMessage(error: unknown): string {
  return error instanceof ApiError || error instanceof Error ? error.message : String(error)
}

function toEditForm(file: ResourceFile): FileEditForm {
  return {
    file_type: file.file_type,
    file_role: file.file_role,
    description: file.description ?? '',
    remark: file.remark ?? '',
    status: file.status,
  }
}

function FileNameCell({ name, id }: { name: string; id: string }) {
  return (
    <div className="files-name-cell">
      <span className="files-name-text" title={name}>{name}</span>
      <span className="files-sub-id">
        <code className="text-mono">{shortText(id, 8)}</code>
        <CopyButton value={id} label="" />
      </span>
    </div>
  )
}

function CompactEmpty({ text }: { text: string }) {
  return <div className="files-empty-compact">{text}</div>
}

export function FilesPage() {
  const { t } = useI18n()

  // ── Mode ──────────────────────────────────────────────────────────────────
  const [fileMode, setFileMode] = useState<FileMode>(
    () => (localStorage.getItem(FILE_MODE_STORAGE_KEY) === 'workspace' ? 'workspace' : 'resource')
  )
  function switchMode(mode: FileMode) {
    setFileMode(mode)
    localStorage.setItem(FILE_MODE_STORAGE_KEY, mode)
  }

  const initSession = readSessionIds()
  const [selectedResourceId, setSelectedResourceId] = useState(
    readHashResourceId() || initSession.resource_id || '',
  )
  const [resourceSearch, setResourceSearch] = useState('')
  const [sessionResourceMissing, setSessionResourceMissing] = useState(false)
  const [attachResourceId, setAttachResourceId] = useState('')
  const [attachResourceSearch, setAttachResourceSearch] = useState('')
  const [statusFilter, setStatusFilter] = useState('active')
  const [typeFilter, setTypeFilter] = useState('')
  const [roleFilter, setRoleFilter] = useState('')
  const [fileRole, setFileRole] = useState('label_dictionary')
  const [fileType, setFileType] = useState('label_table')
  const [description, setDescription] = useState('')
  const [remark, setRemark] = useState('')
  const [uploading, setUploading] = useState(false)
  const [saving, setSaving] = useState(false)
  const [deleting, setDeleting] = useState(false)
  const [notice, setNotice] = useState<NoticeState | null>(null)
  const [options, setOptions] = useState<FileOptions>(FALLBACK_FILE_OPTIONS)
  const [selectedFile, setSelectedFile] = useState<ResourceFile | null>(null)
  const [preview, setPreview] = useState<FilePreview | null>(null)
  const [previewLoading, setPreviewLoading] = useState(false)
  const [previewTab, setPreviewTab] = useState<PreviewTab>('preview')
  const [editOpen, setEditOpen] = useState(false)
  const [editForm, setEditForm] = useState<FileEditForm | null>(null)
  const [deleteTarget, setDeleteTarget] = useState<ResourceFile | null>(null)
  const [intermediateStatus, setIntermediateStatus] = useState<FileIntermediateStatus | null>(null)
  const [intermediatePreview, setIntermediatePreview] = useState<IntermediatePreview | null>(null)
  const [intermediateRuns, setIntermediateRuns] = useState<NormalizationRun[]>([])
  const [intermediateLoadError, setIntermediateLoadError] = useState<string | null>(null)
  const [normalizing, setNormalizing] = useState(false)
  const [regenerateConfirmOpen, setRegenerateConfirmOpen] = useState(false)
  const [uploadPanelOpen, setUploadPanelOpen] = useState(false)
  const [uploadSuggestHint, setUploadSuggestHint] = useState<string | null>(null)
  const [duplicateHint, setDuplicateHint] = useState<{
    inactive: boolean
    macro96: boolean
    filename?: string
    fileId?: string
  } | null>(null)
  const [restoreTarget, setRestoreTarget] = useState<ResourceFile | null>(null)
  const [restoring, setRestoring] = useState(false)

  // ── Workspace state ───────────────────────────────────────────────────────
  const [wsFiles, setWsFiles] = useState<WorkspaceFile[]>([])
  const [wsTotal, setWsTotal] = useState(0)
  const [wsLoading, setWsLoading] = useState(false)
  const [wsSelected, setWsSelected] = useState<WorkspaceFile | null>(null)
  const [wsPreview, setWsPreview] = useState<FilePreview | null>(null)
  const [wsPreviewLoading, setWsPreviewLoading] = useState(false)
  const [wsUploading, setWsUploading] = useState(false)
  const [wsTypeFilter, setWsTypeFilter] = useState('')
  const [wsRoleFilter, setWsRoleFilter] = useState('')
  const [wsIncludeArchived, setWsIncludeArchived] = useState(false)
  const [wsDeleteTarget, setWsDeleteTarget] = useState<WorkspaceFile | null>(null)
  const [wsDeletingId, setWsDeletingId] = useState<string | null>(null)
  const [attachTarget, setAttachTarget] = useState<WorkspaceFile | null>(null)
  const [attachForm, setAttachForm] = useState({ file_type: '', file_role: '', description: '', remark: '' })
  const [attaching, setAttaching] = useState(false)
  const [attachResult, setAttachResult] = useState<ResourceFile | null>(null)
  const [wsPreviewTab, setWsPreviewTab] = useState<'preview' | 'metadata'>('preview')
  const wsFileRef = useRef<HTMLInputElement>(null)

  const fileRef = useRef<HTMLInputElement>(null)
  const onClose = useCallback(() => setNotice(null), [])
  const { setIds } = useSessionIds()

  useEffect(() => {
    getFileOptions()
      .then(setOptions)
      .catch(error => setNotice({ type: 'error', message: t('files.optionsFailed', { error: getErrorMessage(error) }) }))
  }, [t])

  useEffect(() => {
    if (!selectedFile || fileMode !== 'resource') return
    if (isBinarySpreadsheetFile(selectedFile) && isSpreadsheetIntermediateReady(selectedFile, intermediateStatus)) {
      setPreviewTab('intermediate')
      return
    }
    if (!isBinarySpreadsheetFile(selectedFile)) {
      setPreviewTab('preview')
    }
  }, [selectedFile?.id, selectedFile?.file_type, selectedFile?.intermediate_status, intermediateStatus?.status, intermediateStatus?.has_active_intermediate, fileMode])

  const { data: resourcesData, loading: resourcesLoading } = useData(
    () => listResources({ limit: 200 }),
    [],
  )

  const filteredResources = useMemo(() => {
    const items = resourcesData?.items ?? []
    return items.filter(r => resourceMatchesSearch(r, resourceSearch))
  }, [resourcesData, resourceSearch])

  const attachFilteredResources = useMemo(() => {
    const items = resourcesData?.items ?? []
    return items.filter(r => resourceMatchesSearch(r, attachResourceSearch))
  }, [resourcesData, attachResourceSearch])

  const selectedResource = useMemo(
    () => resourcesData?.items.find(r => r.id === selectedResourceId),
    [resourcesData, selectedResourceId],
  )

  useEffect(() => {
    if (!resourcesData?.items || !selectedResourceId) {
      setSessionResourceMissing(false)
      return
    }
    const found = resourcesData.items.some(r => r.id === selectedResourceId)
    setSessionResourceMissing(!found)
  }, [resourcesData, selectedResourceId])

  function handleResourceChange(nextId: string) {
    setSelectedResourceId(nextId)
    setSelectedFile(null)
    setPreview(null)
    setDuplicateHint(null)
    setSessionResourceMissing(false)
    if (nextId) {
      setIds({ resource_id: nextId })
    }
  }

  function openAttachDialog(target: WorkspaceFile) {
    setAttachTarget(target)
    setAttachResourceId(selectedResourceId)
    setAttachResourceSearch('')
    setAttachForm({
      file_type: target.file_type,
      file_role: target.file_role,
      description: '',
      remark: '',
    })
    setAttachResult(null)
  }

  const query = useMemo(
    () => ({
      status: statusFilter || 'active',
      file_type: typeFilter || undefined,
      file_role: roleFilter || undefined,
      limit: 100,
    }),
    [statusFilter, typeFilter, roleFilter],
  )

  const { data, loading, error, reload } = useData(
    () => selectedResourceId ? listResourceFiles(selectedResourceId, query) : Promise.resolve({ items: [], total: 0, limit: 100, offset: 0 }),
    [selectedResourceId, JSON.stringify(query)],
  )

  function handleUploadFileSelected(e: ChangeEvent<HTMLInputElement>) {
    const file = e.target.files?.[0]
    if (!file) { setUploadSuggestHint(null); return }
    const suggestion = suggestFileClassification(file.name, options)
    setFileType(suggestion.fileType)
    setFileRole(suggestion.fileRole)
    setUploadSuggestHint(suggestion.hintKey ? t(suggestion.hintKey) : t('files.suggestTypeApplied', {
      type: suggestion.fileType,
      role: suggestion.fileRole,
    }))
  }

  async function selectFile(row: ResourceFile, opts?: { allowArchived?: boolean }) {
    const allowArchived = opts?.allowArchived ?? row.status !== 'active'
    setSelectedFile(row)
    setPreview(null)
    setEditOpen(false)
    setIntermediateStatus(null)
    setIntermediatePreview(null)
    setIntermediateRuns([])
    setIntermediateLoadError(null)
    setPreviewLoading(true)
    try {
      const [detail, nextPreview] = await Promise.all([
        getFile(row.id, allowArchived),
        allowArchived && row.status !== 'active'
          ? Promise.resolve(null)
          : getFilePreview(row.id).catch(() => null),
      ])
      setSelectedFile(detail)
      setPreview(nextPreview)
      setEditForm(toEditForm(detail))
      setIds({ file_id: detail.id, resource_id: detail.resource_id })
      if (detail.status === 'active') {
        void loadIntermediateData(row.id)
      }
    } catch (error) {
      setNotice({ type: 'error', message: t('files.previewErrorWithDetail', { error: getErrorMessage(error) }) })
    } finally {
      setPreviewLoading(false)
    }
  }

  async function loadIntermediateData(fileId: string) {
    setIntermediateLoadError(null)
    try {
      const [status, runs] = await Promise.all([
        getFileIntermediateStatus(fileId),
        listNormalizationRuns(fileId),
      ])
      setIntermediateStatus(status)
      setIntermediateRuns(runs)
      if (status.has_active_intermediate) {
        try {
          const preview = await getIntermediatePreview(fileId)
          setIntermediatePreview(preview)
        } catch {
          setIntermediatePreview(null)
        }
      } else {
        setIntermediatePreview(null)
      }
    } catch (error) {
      setIntermediateLoadError(getErrorMessage(error))
    }
  }

  // ── Workspace handlers ───────────────────────────────────────────────────
  async function loadWsFiles() {
    setWsLoading(true)
    try {
      const result = await listWorkspaceFiles({
        file_type: wsTypeFilter || undefined,
        file_role: wsRoleFilter || undefined,
        include_archived: wsIncludeArchived,
        limit: 100,
      })
      setWsFiles(result.items)
      setWsTotal(result.total)
    } catch (err) {
      setNotice({ type: 'error', message: getErrorMessage(err) })
    } finally {
      setWsLoading(false)
    }
  }

  useEffect(() => {
    if (fileMode === 'workspace') void loadWsFiles()
  }, [fileMode, wsTypeFilter, wsRoleFilter, wsIncludeArchived])

  async function selectWsFile(row: WorkspaceFile) {
    setWsSelected(row)
    setWsPreview(null)
    setWsPreviewTab('preview')
    setWsPreviewLoading(true)
    try {
      const [detail, preview] = await Promise.all([getWorkspaceFile(row.id), getWorkspaceFilePreview(row.id)])
      setWsSelected(detail)
      setWsPreview(preview)
    } catch (err) {
      setNotice({ type: 'error', message: getErrorMessage(err) })
    } finally {
      setWsPreviewLoading(false)
    }
  }

  async function handleWsUpload() {
    const files = wsFileRef.current?.files
    if (!files || files.length === 0) { setNotice({ type: 'error', message: t('files.needFile') }); return }
    const fd = new FormData()
    fd.append('file', files[0])
    if (options.file_type[0]) fd.append('file_type', 'other')
    setWsUploading(true)
    try {
      const res = await uploadWorkspaceFile(fd)
      setNotice({ type: 'success', message: t('files.workspaceUploadSuccess', { name: res.original_filename }) })
      if (wsFileRef.current) wsFileRef.current.value = ''
      setUploadPanelOpen(false)
      await loadWsFiles()
      await selectWsFile(res)
    } catch (err) {
      setNotice({ type: 'error', message: t('files.workspaceUploadFailed', { error: getErrorMessage(err) }) })
    } finally {
      setWsUploading(false)
    }
  }

  async function handleWsArchive() {
    if (!wsDeleteTarget) return
    setWsDeletingId(wsDeleteTarget.id)
    try {
      await archiveWorkspaceFile(wsDeleteTarget.id)
      setNotice({ type: 'success', message: t('files.deleteSuccess') })
      if (wsSelected?.id === wsDeleteTarget.id) setWsSelected(null)
      setWsDeleteTarget(null)
      await loadWsFiles()
    } catch (err) {
      setNotice({ type: 'error', message: getErrorMessage(err) })
    } finally {
      setWsDeletingId(null)
    }
  }

  async function handleAttach() {
    if (!attachTarget) return
    if (!attachResourceId) { setNotice({ type: 'error', message: t('files.needSelectResource') }); return }
    setAttaching(true)
    setAttachResult(null)
    try {
      const body: WorkspaceFileAttachRequest = {
        resource_id: attachResourceId,
        file_type: attachForm.file_type || undefined,
        file_role: attachForm.file_role || undefined,
        description: attachForm.description || undefined,
        remark: attachForm.remark || undefined,
      }
      const rf = await attachWorkspaceFileToResource(attachTarget.id, body)
      setAttachResult(rf)
      setIds({ file_id: rf.id, resource_id: rf.resource_id })
      setNotice({ type: 'success', message: t('files.attachSuccess', { id: rf.id }) })
    } catch (err) {
      setNotice({ type: 'error', message: t('files.attachFailed', { error: getErrorMessage(err) }) })
    } finally {
      setAttaching(false)
    }
  }

  const columns = useMemo<Column<ResourceFile>[]>(() => [
    {
      key: 'original_filename',
      header: t('files.originalFilename'),
      render: r => <FileNameCell name={r.original_filename} id={r.id} />,
    },
    { key: 'file_type', header: t('files.fileType'), width: 90 },
    { key: 'file_role', header: t('files.fileRole'), width: 110, render: r => <StatusBadge status={r.file_role} /> },
    { key: 'file_size', header: t('files.fileSize'), width: 72, render: r => formatBytes(r.file_size) },
    { key: 'status', header: t('common.status'), width: 72, render: r => <StatusBadge status={r.status} /> },
    {
      key: 'intermediate',
      header: t('files.intermediateStatus'),
      width: 120,
      render: r => {
        const status = pickIntermediateStatus(r, selectedFile?.id, intermediateStatus)
        const kind = pickIntermediateKind(r, selectedFile?.id, intermediateStatus)
        return (
          <div className="intermediate-col-cell">
            <IntermediateStatusBadge status={status} t={t} />
            {status === 'ready' && kind && (
              <span className="intermediate-kind-tag" title={kind}>{kind}</span>
            )}
          </div>
        )
      },
    },
    { key: 'created_at', header: t('files.createdAt'), width: 120, render: r => r.created_at.slice(0, 16).replace('T', ' ') },
    {
      key: 'actions',
      header: t('files.fileActions'),
      width: 140,
      render: r => (
        <div className="row-actions" onClick={e => e.stopPropagation()}>
          <ActionButton label={t('files.preview')} onClick={() => void selectFile(r)} />
          <ActionButton label={t('files.download')} onClick={() => window.open(getFileDownloadUrl(r.id), '_blank')} />
          <ActionButton label={t('files.deactivateFile')} onClick={() => setDeleteTarget(r)} variant="danger" disabled={r.status === 'archived'} />
        </div>
      ),
    },
  ], [t, selectedFile, intermediateStatus])

  function renderResourceSummary(resource: AtlasResource) {
    return (
      <div className="files-resource-summary">
        <div className="files-resource-summary-title">{t('files.resourceSummary')}</div>
        <div className="files-resource-summary-grid">
          <span className="files-resource-summary-label">{t('files.resourceCode')}</span>
          <span className="files-resource-summary-value"><code>{resource.resource_code}</code></span>
          <span className="files-resource-summary-label">{t('files.sourceAtlas')}</span>
          <span className="files-resource-summary-value">{resource.source_atlas}</span>
          <span className="files-resource-summary-label">{t('files.sourceVersion')}</span>
          <span className="files-resource-summary-value">{resource.source_version}</span>
          <span className="files-resource-summary-label">{t('resources.resourceType')}</span>
          <span className="files-resource-summary-value">{resource.resource_type}</span>
          <span className="files-resource-summary-label">{t('files.granularity')}</span>
          <span className="files-resource-summary-value">{resource.granularity_level} / {resource.granularity_family}</span>
          <span className="files-resource-summary-label">{t('files.resourceStatus')}</span>
          <span className="files-resource-summary-value"><StatusBadge status={resource.status} /></span>
          {resource.cn_name && (
            <>
              <span className="files-resource-summary-label">{t('resources.cnName')}</span>
              <span className="files-resource-summary-value">{resource.cn_name}</span>
            </>
          )}
          {resource.en_name && (
            <>
              <span className="files-resource-summary-label">{t('resources.enName')}</span>
              <span className="files-resource-summary-value">{resource.en_name}</span>
            </>
          )}
          <span className="files-resource-summary-label">{t('files.backendResourceId')}</span>
          <span className="files-resource-summary-value">
            <code className="text-mono">{shortText(resource.id, 12)}</code>
            <CopyButton value={resource.id} label={t('files.copyResourceId')} />
          </span>
        </div>
        <div className="files-backend-id-note">{t('files.backendIdsHiddenText')}</div>
      </div>
    )
  }

  function renderResourceSelector(
    value: string,
    onChange: (id: string) => void,
    search: string,
    onSearchChange: (q: string) => void,
    options: AtlasResource[],
    loading: boolean,
  ) {
    return (
      <div className="files-resource-selector">
        <div className="files-resource-toolbar">
          <div className="files-toolbar-field grow files-resource-search">
            <label>{t('files.searchResource')}</label>
            <input
              className="form-input"
              placeholder={t('files.searchResource')}
              value={search}
              onChange={e => onSearchChange(e.target.value)}
            />
          </div>
          <div className="files-toolbar-field grow">
            <label>{t('files.selectResource')}</label>
            {loading ? (
              <div className="files-resource-loading">{t('common.loading')}</div>
            ) : (
              <select
                className="form-select files-resource-option"
                value={value}
                onChange={e => onChange(e.target.value)}
              >
                <option value="">{t('files.selectResourcePlaceholder')}</option>
                {options.map(r => (
                  <option key={r.id} value={r.id}>{formatResourceLabel(r)}</option>
                ))}
              </select>
            )}
          </div>
        </div>
      </div>
    )
  }

  async function handleDuplicateUpload(detail: DuplicateFileDetail) {
    if (fileRef.current) fileRef.current.value = ''
    setDescription('')
    setRemark('')
    setUploadPanelOpen(false)

    const existing = detail.existing_file
    const inactive = duplicateDetailIsInactive(detail)

    if (inactive) {
      setStatusFilter('all')
      setDuplicateHint({
        inactive: true,
        macro96: isMacro96DuplicateFile(existing),
        filename: existing?.original_filename,
        fileId: existing?.id,
      })
      setNotice({ type: 'warning', message: t('files.duplicateFileInactive') })
    } else {
      setDuplicateHint({
        inactive: false,
        macro96: isMacro96DuplicateFile(existing),
        filename: existing?.original_filename,
        fileId: existing?.id,
      })
      setNotice({ type: 'warning', message: t('files.duplicateFileSelected') })
    }

    let fileId = existing?.id
    if (!fileId && detail.sha256 && selectedResourceId) {
      try {
        const list = await listResourceFiles(selectedResourceId, { status: 'all', limit: 100 })
        const match = list.items.find(f => f.sha256 === detail.sha256)
        fileId = match?.id
      } catch {
        // fall through
      }
    }

    if (fileId) {
      setIds({ resource_id: selectedResourceId, file_id: fileId })
      reload()
      try {
        const fresh = await getFile(fileId, true)
        await selectFile(fresh, { allowArchived: true })
        setPreviewTab(inactive ? 'metadata' : 'intermediate')
        if (!inactive) {
          void loadIntermediateData(fileId)
        }
      } catch {
        if (inactive) {
          setNotice({
            type: 'warning',
            message: `${t('files.duplicateFileInactive')} ${t('files.switchedToAllStatuses')}`,
          })
        } else {
          setNotice({
            type: 'warning',
            message: `${t('files.duplicateFileSelected')} ${t('files.duplicateFileRefreshHint')}`,
          })
        }
      }
    } else {
      await handleShowAllAndFindDuplicate(detail.sha256)
      setNotice({
        type: 'warning',
        message: inactive
          ? `${t('files.duplicateWithoutExistingFile')} ${t('files.switchedToAllStatuses')}`
          : t('files.noDuplicateExistingFileReturned'),
      })
    }
  }

  async function handleShowAllAndFindDuplicate(sha256?: string) {
    if (!selectedResourceId || !sha256) return
    setStatusFilter('all')
    try {
      const list = await listResourceFiles(selectedResourceId, { status: 'all', limit: 200 })
      const match = list.items.find(f => f.sha256 === sha256)
      if (match) {
        await selectFile(match, { allowArchived: true })
        setDuplicateHint({
          inactive: match.status !== 'active',
          macro96: isMacro96DuplicateFile(match),
          filename: match.original_filename,
          fileId: match.id,
        })
      }
    } catch {
      // ignore
    }
    reload()
  }

  async function handleRestoreActive() {
    if (!restoreTarget) return
    setRestoring(true)
    try {
      const updated = await restoreFile(restoreTarget.id)
      setNotice({ type: 'success', message: t('files.restoreFileActiveSuccess') })
      setRestoreTarget(null)
      setDuplicateHint(null)
      setStatusFilter('active')
      reload()
      await selectFile(updated)
      setPreviewTab('intermediate')
      void loadIntermediateData(updated.id)
    } catch (error) {
      setNotice({ type: 'error', message: t('files.restoreFileActiveFailed', { error: getErrorMessage(error) }) })
    } finally {
      setRestoring(false)
    }
  }

  async function handleUpload() {
    if (!selectedResourceId) { setNotice({ type: 'error', message: t('files.needSelectResource') }); return }
    const files = fileRef.current?.files
    if (!files || files.length === 0) { setNotice({ type: 'error', message: t('files.needFile') }); return }
    const fd = new FormData()
    fd.append('file', files[0])
    fd.append('file_role', fileRole)
    fd.append('file_type', fileType)
    if (description) fd.append('description', description)
    if (remark) fd.append('remark', remark)
    setUploading(true)
    setDuplicateHint(null)
    try {
      const res = await uploadResourceFile(selectedResourceId, fd)
      setIds({ file_id: res.id, resource_id: selectedResourceId })
      if (res.intermediate_status === 'ready') {
        setNotice({ type: 'success', message: t('files.uploadAndNormalizeSuccess', { name: res.original_filename }) })
      } else if (res.intermediate_status === 'failed') {
        setNotice({
          type: 'error',
          message: t('files.uploadSuccessButNormalizeFailed', {
            name: res.original_filename,
            error: res.latest_intermediate_error ?? t('files.intermediateFailed'),
          }),
        })
      } else {
        setNotice({ type: 'success', message: t('files.uploadSuccess', { name: res.original_filename }) })
      }
      reload()
      if (fileRef.current) fileRef.current.value = ''
      setDescription('')
      setRemark('')
      setUploadPanelOpen(false)
      await selectFile(res)
      setPreviewTab('intermediate')
      void loadIntermediateData(res.id)
    } catch (e) {
      const dupDetail = parseDuplicateFileDetail(e)
      if (dupDetail) {
        await handleDuplicateUpload(dupDetail)
      } else if (e instanceof ApiError && e.status === 422) {
        setNotice({ type: 'error', message: t('files.uploadValidationFailed', { error: getErrorMessage(e) }) })
      } else {
        setNotice({ type: 'error', message: t('files.uploadFailed', { error: getErrorMessage(e) }) })
      }
    } finally {
      setUploading(false)
    }
  }

  async function handleNormalize(force = false) {
    if (!selectedFile) return
    setNormalizing(true)
    try {
      const result = await normalizeFile(selectedFile.id, force)
      const rows = result.artifacts[0]?.row_count ?? 0
      const kind = result.artifacts[0]?.artifact_kind ?? ''
      setNotice({ type: 'success', message: t('files.normalizeSuccess', { kind, rows: String(rows) }) })
      await loadIntermediateData(selectedFile.id)
      reload()
    } catch (error) {
      setNotice({ type: 'error', message: t('files.normalizeFailed', { error: getErrorMessage(error) }) })
    } finally {
      setNormalizing(false)
      setRegenerateConfirmOpen(false)
    }
  }

  async function handleUpdate() {
    if (!selectedFile || !editForm) return
    setSaving(true)
    try {
      const updated = await updateFile(selectedFile.id, {
        file_type: editForm.file_type,
        file_role: editForm.file_role,
        description: editForm.description.trim() || null,
        remark: editForm.remark.trim() || null,
        status: editForm.status,
      })
      setSelectedFile(updated)
      setEditForm(toEditForm(updated))
      setEditOpen(false)
      setNotice({ type: 'success', message: t('files.updateSuccess') })
      reload()
      await selectFile(updated)
    } catch (error) {
      setNotice({ type: 'error', message: t('files.updateFailed', { error: getErrorMessage(error) }) })
    } finally {
      setSaving(false)
    }
  }

  async function handleDelete() {
    if (!deleteTarget) return
    setDeleting(true)
    try {
      await deleteFile(deleteTarget.id)
      setNotice({ type: 'success', message: t('files.deleteSuccess') })
      if (selectedFile?.id === deleteTarget.id) {
        setSelectedFile(null)
        setPreview(null)
        setEditOpen(false)
      }
      setDeleteTarget(null)
      reload()
    } catch (error) {
      setNotice({ type: 'error', message: t('files.deleteFailed', { error: getErrorMessage(error) }) })
    } finally {
      setDeleting(false)
    }
  }

  function updateEditForm(key: keyof FileEditForm) {
    return (event: ChangeEvent<HTMLInputElement | HTMLSelectElement | HTMLTextAreaElement>) => {
      setEditForm(current => current ? { ...current, [key]: event.target.value } : current)
    }
  }

  const metadataEntries = useMemo(() => {
    if (!selectedFile) return []
    return [
      { label: t('common.id'), value: <><code className="text-mono">{selectedFile.id}</code> <CopyButton value={selectedFile.id} /></> },
      { label: t('files.resourceId'), value: <><code className="text-mono">{selectedFile.resource_id}</code> <CopyButton value={selectedFile.resource_id} /></> },
      { label: t('files.originalFilename'), value: selectedFile.original_filename },
      { label: t('files.storedFilename'), value: selectedFile.stored_filename },
      { label: t('files.fileType'), value: selectedFile.file_type },
      { label: t('files.fileRole'), value: selectedFile.file_role },
      { label: t('files.mimeType'), value: selectedFile.mime_type },
      { label: t('files.sha256'), value: <><code className="text-mono" title={selectedFile.sha256}>{shortText(selectedFile.sha256, 16)}</code> <CopyButton value={selectedFile.sha256} label={t('files.copySha')} /></> },
      { label: t('files.fileSize'), value: formatBytes(selectedFile.file_size) },
      { label: t('files.storagePath'), value: selectedFile.storage_path },
      { label: t('files.statusFilter'), value: <StatusBadge status={selectedFile.status} /> },
      { label: t('files.createdAt'), value: selectedFile.created_at },
      { label: t('files.updatedAt'), value: selectedFile.updated_at },
      { label: t('files.description'), value: selectedFile.description },
      { label: t('files.remark'), value: selectedFile.remark },
    ]
  }, [selectedFile, t])

  const rawJsonPayload = useMemo(() => {
    if (!selectedFile) return null
    const payload: Record<string, unknown> = { file: selectedFile }
    if (intermediateStatus) payload.intermediate_status = intermediateStatus
    if (intermediatePreview) payload.intermediate_preview = intermediatePreview
    if (preview) {
      if (shouldRenderTextPreview(selectedFile) && !looksLikeBinaryZipText(preview.content)) {
        payload.file_preview = preview
      } else {
        payload.file_preview = {
          file_id: preview.file_id,
          filename: preview.filename,
          file_type: preview.file_type,
          mime_type: preview.mime_type,
          preview_kind: preview.preview_kind,
          size_bytes: preview.size_bytes,
          metadata: preview.metadata,
          content: null,
          blocked_reason: t('files.rawBinaryPreviewBlocked'),
        }
      }
    }
    return payload
  }, [selectedFile, preview, intermediateStatus, intermediatePreview, t])

  function renderSpreadsheetPreviewHint() {
    if (!selectedFile) return null
    const ready = isSpreadsheetIntermediateReady(selectedFile, intermediateStatus)
    const kind = pickIntermediateKind(selectedFile, selectedFile.id, intermediateStatus)
    return (
      <div className="file-preview-hint-card file-binary-preview-blocked">
        <div className="file-preview-hint-title">{t('files.previewBinarySpreadsheetTitle')}</div>
        <p className="file-preview-hint-body">{t('files.previewBinarySpreadsheetMessage')}</p>
        {ready ? (
          <>
            <div className="file-intermediate-summary">
              <div>{t('files.previewIntermediateReady')}</div>
              {kind && <div><code>{kind}</code></div>}
              <div className="file-preview-tab-warning">{t('files.previewUseIntermediate')}</div>
            </div>
            <div className="files-actions-row" style={{ marginTop: 8 }}>
              <ActionButton label={t('files.switchToIntermediate')} variant="primary" onClick={() => setPreviewTab('intermediate')} />
              <ActionButton label={t('files.downloadOriginalFile')} variant="default" onClick={() => window.open(getFileDownloadUrl(selectedFile.id), '_blank')} />
            </div>
          </>
        ) : (
          <>
            <div className="file-preview-tab-warning">{t('files.intermediateNotReady')}</div>
            <p>{t('files.generateIntermediateFirst')}</p>
            <div className="files-actions-row" style={{ marginTop: 8 }}>
              <ActionButton
                label={normalizing ? t('files.normalizing') : t('files.generateIntermediate')}
                variant="primary"
                loading={normalizing}
                onClick={() => void handleNormalize(false)}
              />
              <ActionButton label={t('files.downloadOriginalFile')} variant="default" onClick={() => window.open(getFileDownloadUrl(selectedFile.id), '_blank')} />
            </div>
          </>
        )}
      </div>
    )
  }

  function renderPreview() {
    if (!selectedFile) return <CompactEmpty text={t('files.selectFileToPreview')} />
    if (previewLoading) return <CompactEmpty text={t('common.loading')} />
    if (isBinarySpreadsheetFile(selectedFile) || looksLikeBinaryZipText(preview?.content) || (preview && !shouldRenderTextPreview(selectedFile))) {
      return renderSpreadsheetPreviewHint()
    }
    if (!preview) return <CompactEmpty text={t('files.selectFileToPreview')} />
    if (preview.preview_kind === 'missing') return <CompactEmpty text={t('files.previewMissing')} />
    if (preview.preview_kind === 'image') {
      return <img className="file-preview-image" src={getFileDownloadUrl(selectedFile.id)} alt={selectedFile.original_filename} />
    }
    if (preview.preview_kind === 'unsupported' || preview.preview_kind === 'binary') {
      return <CompactEmpty text={t('files.previewUnsupportedBinary')} />
    }
    if (preview.preview_kind === 'error') return <CompactEmpty text={preview.error_message ?? t('files.previewError')} />
    return (
      <>
        {preview.is_truncated && (
          <div className="preview-warning">{t('files.previewTruncated', { kb: Math.round(preview.max_bytes / 1024) })}</div>
        )}
        <pre className="files-code-preview preview-code"><code>{preview.content}</code></pre>
      </>
    )
  }

  function renderResourcePreviewPane() {
    return (
      <aside className="files-preview-pane files-preview-sticky card">
        {selectedFile ? (
          <>
            <div className="files-preview-header">
              <div className="filename" title={selectedFile.original_filename}>{selectedFile.original_filename}</div>
              <div className="files-preview-meta">
                <StatusBadge status={selectedFile.status} />
                <span className="meta-sep">·</span>
                <span>{selectedFile.file_type}</span>
                <span className="meta-sep">·</span>
                <span>{selectedFile.file_role}</span>
                <span className="meta-sep">·</span>
                <span>{formatBytes(selectedFile.file_size)}</span>
                <span className="storage-scope-badge resource">{t('files.storageScopeResource')}</span>
              </div>
            </div>
            <div className="files-actions-row">
              <ActionButton label={t('files.preview')} onClick={() => setPreviewTab('preview')} />
              <ActionButton label={t('files.download')} onClick={() => window.open(getFileDownloadUrl(selectedFile.id), '_blank')} disabled={selectedFile.status !== 'active'} />
              <ActionButton label={t('files.editFile')} onClick={() => { setEditForm(toEditForm(selectedFile)); setEditOpen(true) }} />
              {selectedFile.status !== 'active' && (
                <ActionButton
                  label={t('files.restoreFileActive')}
                  onClick={() => setRestoreTarget(selectedFile)}
                  variant="primary"
                />
              )}
              <ActionButton
                label={normalizing ? t('files.normalizing') : t('files.regenerateIntermediate')}
                onClick={() => setRegenerateConfirmOpen(true)}
                loading={normalizing}
                variant="primary"
              />
              <ActionButton label={t('files.deactivateFile')} onClick={() => setDeleteTarget(selectedFile)} variant="danger" disabled={selectedFile.status === 'archived'} />
              <CopyButton value={selectedFile.id} label={t('files.copyId')} />
            </div>
          </>
        ) : (
          <div className="files-preview-header">
            <div className="filename">{t('files.previewPanel')}</div>
            <div className="files-preview-meta">{t('files.selectedFile')}</div>
          </div>
        )}

        {selectedFile && selectedFile.status !== 'active' && (
          <div className="file-inactive-warning" style={{ margin: '0 12px 8px' }}>
            {t('files.cannotUseInactiveFileForBatch')}
          </div>
        )}

        {selectedFile && selectedFile.status === 'active' && selectedFile.intermediate_status === 'failed' && selectedFile.latest_intermediate_error && (
          <div className="intermediate-hint-bar intermediate-hint-failed" style={{ margin: '0 12px 8px' }}>
            <span>⚠</span>
            <span>{t('files.uploadSuccessButNormalizeFailed', { name: selectedFile.original_filename, error: selectedFile.latest_intermediate_error })}</span>
          </div>
        )}

        {selectedFile && selectedFile.intermediate_status === 'ready' && (
          <div className="intermediate-hint-bar intermediate-hint-ready" style={{ margin: '0 12px 8px' }}>
            <span>✓</span>
            <span>{t('files.intermediateStoredInDatabase')}</span>
          </div>
        )}

        {editOpen && editForm && (
          <div className="files-edit-inline">
            <div className="form-row">
              <div className="form-field">
                <label className="form-label">{t('files.fileType')}</label>
                <select className="form-select" value={editForm.file_type} onChange={updateEditForm('file_type')}>
                  {options.file_type.map(v => <option key={v} value={v}>{v}</option>)}
                </select>
              </div>
              <div className="form-field">
                <label className="form-label">{t('files.fileRole')}</label>
                <select className="form-select" value={editForm.file_role} onChange={updateEditForm('file_role')}>
                  {options.file_role.map(v => <option key={v} value={v}>{v}</option>)}
                </select>
              </div>
              <div className="form-field">
                <label className="form-label">{t('files.statusFilter')}</label>
                <select className="form-select" value={editForm.status} onChange={updateEditForm('status')}>
                  {options.status.map(v => <option key={v} value={v}>{v}</option>)}
                </select>
              </div>
            </div>
            <div className="form-row">
              <div className="form-field file-form-text">
                <label className="form-label">{t('files.description')}</label>
                <textarea className="form-textarea" rows={2} value={editForm.description} onChange={updateEditForm('description')} />
              </div>
              <div className="form-field file-form-text">
                <label className="form-label">{t('files.remark')}</label>
                <textarea className="form-textarea" rows={2} value={editForm.remark} onChange={updateEditForm('remark')} />
              </div>
            </div>
            <div className="settings-actions">
              <ActionButton label={t('common.save')} onClick={handleUpdate} loading={saving} variant="primary" />
              <ActionButton label={t('common.cancel')} onClick={() => setEditOpen(false)} disabled={saving} />
            </div>
          </div>
        )}

        <div className="files-preview-tabs tabs">
          <button className={`tab-btn${previewTab === 'preview' ? ' active' : ''}`} onClick={() => setPreviewTab('preview')}>{t('files.preview')}</button>
          <button className={`tab-btn${previewTab === 'metadata' ? ' active' : ''}`} onClick={() => setPreviewTab('metadata')}>{t('files.metadata')}</button>
          <button className={`tab-btn${previewTab === 'intermediate' ? ' active' : ''}`} onClick={() => setPreviewTab('intermediate')}>
            {t('files.intermediate')}
            {(intermediateStatus?.has_active_intermediate || selectedFile?.intermediate_status === 'ready') && (
              <span style={{ marginLeft: 4, color: '#389e0d', fontSize: 10 }}>●</span>
            )}
            {(intermediateStatus?.status === 'failed' || selectedFile?.intermediate_status === 'failed') && (
              <span style={{ marginLeft: 4, color: '#cf1322', fontSize: 10 }}>●</span>
            )}
          </button>
          <button className={`tab-btn${previewTab === 'raw' ? ' active' : ''}`} onClick={() => setPreviewTab('raw')}>{t('files.rawJson')}</button>
        </div>

        <div className="files-tab-content">
          {previewTab === 'preview' && renderPreview()}
          {previewTab === 'metadata' && (
            selectedFile
              ? <div className="files-metadata-grid"><KeyValuePanel entries={metadataEntries} /></div>
              : <CompactEmpty text={t('files.selectFileToPreview')} />
          )}
          {previewTab === 'intermediate' && renderIntermediate()}
          {previewTab === 'raw' && (
            selectedFile
              ? <pre className="files-code-preview preview-code"><code>{JSON.stringify(rawJsonPayload, null, 2)}</code></pre>
              : <CompactEmpty text={t('files.selectFileToPreview')} />
          )}
        </div>
      </aside>
    )
  }

  function renderIntermediate() {
    if (!selectedFile) return <CompactEmpty text={t('files.selectFileToPreview')} />

    return (
      <div className="intermediate-section">
        {intermediateLoadError && (
          <div className="intermediate-hint-bar intermediate-hint-failed">
            <span>⚠</span>
            <span>{t('files.intermediateLoadFailed', { error: intermediateLoadError })}</span>
          </div>
        )}
        {!intermediateStatus ? (
          <CompactEmpty text={t('common.loading')} />
        ) : (
          <>
            <div className="intermediate-meta-grid">
              <span className="intermediate-meta-label">{t('files.intermediateStatus')}</span>
              <span className="intermediate-meta-value">
                <IntermediateStatusBadge
                  status={(intermediateStatus.status ?? (intermediateStatus.has_active_intermediate ? 'ready' : 'missing')) as IntermediateColStatus}
                  t={t}
                />
              </span>
              {intermediateStatus.latest_artifact_kind && (
                <>
                  <span className="intermediate-meta-label">{t('files.intermediateKind')}</span>
                  <span className="intermediate-meta-value">{intermediateStatus.latest_artifact_kind}</span>
                </>
              )}
              {intermediateStatus.artifact_count > 0 && (
                <>
                  <span className="intermediate-meta-label">{t('files.artifactCount')}</span>
                  <span className="intermediate-meta-value">{intermediateStatus.artifact_count}</span>
                </>
              )}
              {intermediateStatus.latest_run_status && (
                <>
                  <span className="intermediate-meta-label">{t('files.latestRunStatus')}</span>
                  <span className="intermediate-meta-value">
                    <StatusBadge status={intermediateStatus.latest_run_status} />
                  </span>
                </>
              )}
              {intermediateStatus.latest_run_error && (
                <>
                  <span className="intermediate-meta-label">{t('files.latestRunError')}</span>
                  <span className="intermediate-meta-value" style={{ color: '#cf1322' }}>{intermediateStatus.latest_run_error}</span>
                </>
              )}
            </div>

            {intermediateStatus.status === 'failed' && (
              <div className="intermediate-hint-bar intermediate-hint-failed">
                <ActionButton
                  label={t('files.normalizeRetry')}
                  onClick={() => void handleNormalize(true)}
                  loading={normalizing}
                  variant="primary"
                />
              </div>
            )}

            {intermediateStatus.has_active_intermediate && intermediateStatus.latest_artifact_kind === 'label_table' && (
              <div className="intermediate-label-note">{t('files.intermediateLabelTableNote')}</div>
            )}

            {(intermediateStatus.artifacts ?? []).length > 0 ? (
              (intermediateStatus.artifacts ?? []).map(art => (
                <div key={art.id}>{renderArtifactDetail(art, t)}</div>
              ))
            ) : intermediatePreview ? (
              <>
                <div className="intermediate-section-title" style={{ marginTop: 10 }}>{t('files.intermediatePreview')}</div>
                {intermediatePreview.artifact_kind === 'macro_region_table' ? (
                  renderArtifactDetail({
                    id: intermediatePreview.artifact_id,
                    artifact_kind: 'macro_region_table',
                    content_jsonb: {
                      rows: (intermediatePreview.preview?.rows_preview as Record<string, unknown>[] | undefined)
                        ?? (intermediatePreview.preview?.rows as Record<string, unknown>[] | undefined),
                      row_count: intermediatePreview.row_count,
                      schema: intermediatePreview.metadata?.schema,
                      source_format: intermediatePreview.source_format,
                      source_sheet: intermediatePreview.preview?.source_sheet ?? intermediatePreview.metadata?.source_sheet,
                    },
                    preview_jsonb: intermediatePreview.preview ?? {},
                    metadata_jsonb: intermediatePreview.metadata ?? {},
                    row_count: intermediatePreview.row_count,
                  } as unknown as IntermediateArtifact, t)
                ) : (
                  <pre className="files-code-preview">{JSON.stringify(intermediatePreview.preview ?? intermediatePreview.metadata, null, 2)}</pre>
                )}
              </>
            ) : null}

            <div className="intermediate-section-title" style={{ marginTop: 10 }}>{t('files.intermediateRuns')}</div>
            {intermediateRuns.length === 0 ? (
              <CompactEmpty text={t('files.noIntermediateRuns')} />
            ) : (
              intermediateRuns.map(run => (
                <div key={run.id} className="intermediate-run-row">
                  <StatusBadge status={run.status} />
                  <span className="intermediate-run-code">{run.run_code}</span>
                  <span style={{ color: '#888', fontSize: 11 }}>{run.normalizer_key}</span>
                  <span style={{ marginLeft: 'auto', fontSize: 11, color: '#888' }}>
                    {run.created_at.slice(0, 16).replace('T', ' ')}
                  </span>
                  {run.warning_count > 0 && (
                    <span style={{ color: '#d4910a', fontSize: 11 }}>⚠ {run.warning_count}</span>
                  )}
                </div>
              ))
            )}
          </>
        )}
      </div>
    )
  }

  function renderUploadPanel() {
    if (!uploadPanelOpen) return null
    if (fileMode === 'workspace') {
      return (
        <div className="files-upload-panel card">
          <div className="files-upload-panel-title">{t('files.uploadPanel')} — {t('files.workspaceFiles')}</div>
          <div className="files-upload-row">
            <div className="files-toolbar-field grow">
              <label>{t('files.selectFile')} *</label>
              <input type="file" ref={wsFileRef} className="form-input" />
            </div>
            <ActionButton label={wsUploading ? t('common.loading') : t('files.uploadWorkspaceFile')} onClick={handleWsUpload} loading={wsUploading} variant="primary" />
          </div>
        </div>
      )
    }
    if (!selectedResourceId) {
      return (
        <div className="files-upload-panel card">
          <CompactEmpty text={t('files.needSelectResource')} />
        </div>
      )
    }
    return (
      <div className="files-upload-panel card">
        <div className="files-upload-panel-title">{t('files.uploadPanel')} — {t('files.resourceFiles')}</div>
        <div className="files-upload-row">
          <div className="files-toolbar-field grow">
            <label>{t('files.selectFile')} *</label>
            <input type="file" ref={fileRef} className="form-input" onChange={handleUploadFileSelected} />
          </div>
          <div className="files-toolbar-field sm">
            <label>{t('files.fileRole')}</label>
            <select className="form-select" value={fileRole} onChange={e => setFileRole(e.target.value)}>
              {options.file_role.map(r => <option key={r} value={r}>{r}</option>)}
            </select>
          </div>
          <div className="files-toolbar-field sm">
            <label>{t('files.fileType')}</label>
            <select className="form-select" value={fileType} onChange={e => setFileType(e.target.value)}>
              {options.file_type.map(v => <option key={v} value={v}>{v}</option>)}
            </select>
          </div>
        </div>
        {uploadSuggestHint && (
          <div className="intermediate-hint-bar intermediate-hint-ready" style={{ marginBottom: 8 }}>
            <span>ℹ</span>
            <span>{uploadSuggestHint}</span>
          </div>
        )}
        <div className="files-upload-row">
          <div className="files-toolbar-field grow">
            <label>{t('files.description')}</label>
            <input className="form-input" value={description} onChange={e => setDescription(e.target.value)} placeholder={t('files.optionalDesc')} />
          </div>
          <div className="files-toolbar-field grow">
            <label>{t('files.remark')}</label>
            <input className="form-input" value={remark} onChange={e => setRemark(e.target.value)} placeholder={t('files.optionalDesc')} />
          </div>
          <ActionButton label={uploading ? t('common.loading') : t('files.uploadFile')} onClick={handleUpload} loading={uploading} variant="primary" />
        </div>
      </div>
    )
  }

  function renderToolbar() {
    return (
      <div className="files-toolbar-card card">
        <div className="files-mode-tabs">
          <button type="button" className={`files-mode-tab${fileMode === 'resource' ? ' active' : ''}`} onClick={() => switchMode('resource')}>
            {t('files.resourceFiles')}
          </button>
          <button type="button" className={`files-mode-tab${fileMode === 'workspace' ? ' active' : ''}`} onClick={() => switchMode('workspace')}>
            {t('files.workspaceFiles')}
          </button>
        </div>
        {fileMode === 'resource' ? (
          <div className="files-toolbar">
            <div className="files-mode-notice-inline resource">{t('files.resourceFilesDescription')}</div>
            {renderResourceSelector(
              selectedResourceId,
              handleResourceChange,
              resourceSearch,
              setResourceSearch,
              filteredResources,
              resourcesLoading,
            )}
            {sessionResourceMissing && (
              <div className="files-resource-missing-warning">{t('files.resourceNotFound')}</div>
            )}
            {selectedResource && renderResourceSummary(selectedResource)}
            <div className="files-filter-section-label">{t('files.filterFiles')}</div>
            <div className="files-toolbar-field sm">
              <label>{t('files.statusFilter')}</label>
              <select className="form-select" value={statusFilter} onChange={e => setStatusFilter(e.target.value)}>
                <option value="active">{t('files.statusActiveOnly')}</option>
                <option value="archived">{t('files.statusArchivedOnly')}</option>
                <option value="all">{t('files.showAllStatuses')}</option>
              </select>
            </div>
            {statusFilter !== 'active' && (
              <div className="file-status-filter-note">{t('files.showAllStatusesHint')}</div>
            )}
            <div className="files-toolbar-field sm">
              <label>{t('files.fileTypeFilter')}</label>
              <select className="form-select" value={typeFilter} onChange={e => setTypeFilter(e.target.value)}>
                <option value="">{t('common.all')}</option>
                {options.file_type.map(v => <option key={v} value={v}>{v}</option>)}
              </select>
            </div>
            <div className="files-toolbar-field sm">
              <label>{t('files.fileRoleFilter')}</label>
              <select className="form-select" value={roleFilter} onChange={e => setRoleFilter(e.target.value)}>
                <option value="">{t('common.all')}</option>
                {options.file_role.map(v => <option key={v} value={v}>{v}</option>)}
              </select>
            </div>
            {selectedResource && (
              <div className="files-toolbar-hint">
                {t('files.selectedResource')}: <strong>{selectedResource.resource_code}</strong>
                {' · '}{selectedResource.source_atlas}
              </div>
            )}
          </div>
        ) : (
          <div className="files-toolbar">
            <div className="files-mode-notice-inline workspace">{t('files.workspaceFilesDescription')}</div>
            <div className="files-toolbar-field sm">
              <label>{t('files.fileTypeFilter')}</label>
              <select className="form-select" value={wsTypeFilter} onChange={e => setWsTypeFilter(e.target.value)}>
                <option value="">{t('common.all')}</option>
                {options.file_type.map(v => <option key={v} value={v}>{v}</option>)}
              </select>
            </div>
            <div className="files-toolbar-field sm">
              <label>{t('files.fileRoleFilter')}</label>
              <select className="form-select" value={wsRoleFilter} onChange={e => setWsRoleFilter(e.target.value)}>
                <option value="">{t('common.all')}</option>
                {options.file_role.map(v => <option key={v} value={v}>{v}</option>)}
              </select>
            </div>
            <div className="files-toolbar-field sm" style={{ alignSelf: 'flex-end' }}>
              <label style={{ display: 'flex', alignItems: 'center', gap: 6, cursor: 'pointer', marginTop: 18 }}>
                <input type="checkbox" checked={wsIncludeArchived} onChange={e => setWsIncludeArchived(e.target.checked)} />
                {t('files.archiveWorkspaceFile')}
              </label>
            </div>
            <div className="files-toolbar-actions">
              <ActionButton label={t('common.refresh')} onClick={loadWsFiles} />
            </div>
          </div>
        )}
      </div>
    )
  }

  function renderWorkspaceMode() {
    const wsColumns: Column<WorkspaceFile>[] = [
      { key: 'original_filename', header: t('files.originalFilename'), render: r => <FileNameCell name={r.original_filename} id={r.id} /> },
      { key: 'file_type', header: t('files.fileType'), width: 90 },
      { key: 'file_role', header: t('files.fileRole'), width: 110, render: r => <StatusBadge status={r.file_role} /> },
      { key: 'file_size_bytes', header: t('files.fileSize'), width: 72, render: r => formatBytes(r.file_size_bytes) },
      { key: 'status', header: t('common.status'), width: 72, render: r => <StatusBadge status={r.status} /> },
      { key: 'created_at', header: t('files.createdAt'), width: 120, render: r => r.created_at.slice(0, 16).replace('T', ' ') },
      {
        key: 'actions',
        header: t('files.fileActions'),
        width: 160,
        render: r => (
          <div className="row-actions" onClick={e => e.stopPropagation()}>
            <ActionButton label={t('files.attachToResource')} onClick={() => openAttachDialog(r)} variant="primary" />
            <ActionButton label={t('files.download')} onClick={() => window.open(getWorkspaceFileDownloadUrl(r.id), '_blank')} />
            <ActionButton label={t('files.archiveWorkspaceFile')} onClick={() => setWsDeleteTarget(r)} variant="danger" disabled={r.status === 'archived'} />
          </div>
        ),
      },
    ]

    return (
      <>
        <div className="files-main-split">
          <div className="files-list-pane card">
            <div className="files-list-header">
              <span>{t('files.fileList')}</span>
              <span className="count">{t('common.totalRecords', { total: wsTotal })}</span>
            </div>
            <div className="files-table-compact">
              <DataTable
                columns={wsColumns}
                rows={wsFiles}
                loading={wsLoading}
                total={wsTotal}
                getKey={r => r.id}
                onRowClick={row => void selectWsFile(row)}
                getRowClassName={row => row.id === wsSelected?.id ? 'selected-row' : undefined}
                emptyText={t('files.emptyWithResource')}
              />
            </div>
          </div>

          <aside className="files-preview-pane files-preview-sticky card">
            {wsSelected ? (
              <>
                <div className="files-preview-header">
                  <div className="filename" title={wsSelected.original_filename}>{wsSelected.original_filename}</div>
                  <div className="files-preview-meta">
                    <StatusBadge status={wsSelected.status} />
                    <span className="meta-sep">·</span>
                    <span>{wsSelected.file_type}</span>
                    <span className="meta-sep">·</span>
                    <span>{wsSelected.file_role}</span>
                    <span className="meta-sep">·</span>
                    <span>{formatBytes(wsSelected.file_size_bytes)}</span>
                    <span className="storage-scope-badge workspace">{t('files.storageScopeWorkspace')}</span>
                  </div>
                </div>
                <div className="files-actions-row">
                  <ActionButton label={t('files.attachToResource')} onClick={() => openAttachDialog(wsSelected)} variant="primary" />
                  <ActionButton label={t('files.download')} onClick={() => window.open(getWorkspaceFileDownloadUrl(wsSelected.id), '_blank')} />
                  <ActionButton label={t('files.archiveWorkspaceFile')} onClick={() => setWsDeleteTarget(wsSelected)} variant="danger" disabled={wsSelected.status === 'archived'} />
                  <CopyButton value={wsSelected.id} label={t('files.copyId')} />
                </div>
                <div className="files-mode-notice-inline workspace" style={{ margin: '0 12px 8px' }}>{t('files.workspaceFileCannotImportDirectly')}</div>
              </>
            ) : (
              <div className="files-preview-header">
                <div className="filename">{t('files.previewPanel')}</div>
                <div className="files-preview-meta">{t('files.noFileSelected')}</div>
              </div>
            )}

            <div className="files-preview-tabs tabs">
              <button type="button" className={`tab-btn${wsPreviewTab === 'preview' ? ' active' : ''}`} onClick={() => setWsPreviewTab('preview')}>{t('files.preview')}</button>
              <button type="button" className={`tab-btn${wsPreviewTab === 'metadata' ? ' active' : ''}`} onClick={() => setWsPreviewTab('metadata')}>{t('files.metadata')}</button>
            </div>

            <div className="files-tab-content">
              {wsPreviewTab === 'preview' && (
                <>
                  {!wsSelected && <CompactEmpty text={t('files.selectFileToPreview')} />}
                  {wsSelected && wsPreviewLoading && <CompactEmpty text={t('common.loading')} />}
                  {wsSelected && !wsPreviewLoading && wsPreview && (
                    isBinarySpreadsheetFile(wsSelected) || looksLikeBinaryZipText(wsPreview.content)
                      ? (
                        <div className="file-preview-hint-card file-binary-preview-blocked">
                          <div className="file-preview-hint-title">{t('files.previewBinarySpreadsheetTitle')}</div>
                          <p className="file-preview-hint-body">{t('files.previewBinarySpreadsheetMessage')}</p>
                        </div>
                      )
                      : wsPreview.preview_kind === 'image'
                      ? <img className="file-preview-image" src={getWorkspaceFileDownloadUrl(wsSelected.id)} alt={wsSelected.original_filename} />
                      : wsPreview.preview_kind === 'unsupported' || wsPreview.preview_kind === 'binary'
                        ? <CompactEmpty text={t('files.previewUnsupportedBinary')} />
                        : wsPreview.preview_kind === 'missing'
                          ? <CompactEmpty text={t('files.previewMissing')} />
                          : <>{wsPreview.is_truncated && <div className="preview-warning">{t('files.previewTruncated', { kb: Math.round(wsPreview.max_bytes / 1024) })}</div>}<pre className="files-code-preview preview-code"><code>{wsPreview.content}</code></pre></>
                  )}
                </>
              )}
              {wsPreviewTab === 'metadata' && wsSelected && (
                <div className="files-metadata-grid">
                  <KeyValuePanel entries={[
                    { label: t('files.workspaceFileId'), value: <><code className="text-mono">{wsSelected.id}</code><CopyButton value={wsSelected.id} /></> },
                    { label: t('files.fileType'), value: wsSelected.file_type },
                    { label: t('files.fileRole'), value: wsSelected.file_role },
                    { label: t('files.sha256'), value: <><code className="text-mono" title={wsSelected.sha256}>{shortText(wsSelected.sha256, 16)}</code><CopyButton value={wsSelected.sha256} label={t('files.copySha')} /></> },
                    { label: t('files.fileSize'), value: formatBytes(wsSelected.file_size_bytes) },
                    { label: t('common.status'), value: <StatusBadge status={wsSelected.status} /> },
                    { label: t('files.createdAt'), value: wsSelected.created_at?.slice(0, 16).replace('T', ' ') },
                  ]} />
                </div>
              )}
              {wsPreviewTab === 'metadata' && !wsSelected && <CompactEmpty text={t('files.selectFileToPreview')} />}
            </div>
          </aside>
        </div>

        {/* Attach to Resource Dialog */}
        {attachTarget && (
          <div className="attach-dialog-overlay" onClick={() => !attaching && setAttachTarget(null)}>
            <div className="attach-dialog" onClick={e => e.stopPropagation()}>
              <div className="attach-dialog-title">{t('files.attachToResourceTitle')}</div>
              <div className="attach-dialog-desc">{t('files.attachToResourceDescription')}</div>
              <div className="form-row" style={{ flexDirection: 'column', gap: 8 }}>
                {renderResourceSelector(
                  attachResourceId,
                  setAttachResourceId,
                  attachResourceSearch,
                  setAttachResourceSearch,
                  attachFilteredResources,
                  resourcesLoading,
                )}
                {attachResourceId && (() => {
                  const attachResource = resourcesData?.items.find(r => r.id === attachResourceId)
                  return attachResource ? renderResourceSummary(attachResource) : null
                })()}
                <div className="form-field">
                  <label className="form-label">{t('files.fileType')}</label>
                  <select className="form-select" value={attachForm.file_type} onChange={e => setAttachForm(f => ({ ...f, file_type: e.target.value }))}>
                    {options.file_type.map(v => <option key={v} value={v}>{v}</option>)}
                  </select>
                </div>
                <div className="form-field">
                  <label className="form-label">{t('files.fileRole')}</label>
                  <select className="form-select" value={attachForm.file_role} onChange={e => setAttachForm(f => ({ ...f, file_role: e.target.value }))}>
                    {options.file_role.map(v => <option key={v} value={v}>{v}</option>)}
                  </select>
                </div>
                <div className="form-field">
                  <label className="form-label">{t('files.description')}</label>
                  <input className="form-input" value={attachForm.description} onChange={e => setAttachForm(f => ({ ...f, description: e.target.value }))} />
                </div>
              </div>
              {attachResult && (
                <div className="attach-success-panel">
                  <div>{t('files.boundResourceFileCreated')}</div>
                  <div className="attach-success-id">{attachResult.id}</div>
                  <div style={{ marginTop: 6, display: 'flex', gap: 8 }}>
                    <button className="btn btn-sm" onClick={() => { switchMode('resource'); handleResourceChange(attachResult.resource_id); setAttachTarget(null) }}>{t('files.switchToResourceFiles')}</button>
                    <CopyButton value={attachResult.id} label={t('files.resourceFileId')} />
                  </div>
                </div>
              )}
              <div className="settings-actions" style={{ marginTop: 12 }}>
                {!attachResult && <ActionButton label={t('files.attachToResource')} onClick={handleAttach} loading={attaching} variant="primary" disabled={!attachResourceId} />}
                <ActionButton label={t('common.cancel')} onClick={() => setAttachTarget(null)} disabled={attaching} />
              </div>
            </div>
          </div>
        )}

        <ConfirmDialog
          open={Boolean(wsDeleteTarget)}
          title={t('files.archiveWorkspaceFileConfirmTitle')}
          message={t('files.archiveWorkspaceFileConfirmMessage')}
          confirmLabel={t('files.archiveWorkspaceFile')}
          danger
          loading={wsDeletingId !== null}
          onConfirm={handleWsArchive}
          onCancel={() => setWsDeleteTarget(null)}
        />
      </>
    )
  }

  function handleRefresh() {
    if (fileMode === 'workspace') void loadWsFiles()
    else reload()
  }

  return (
    <div className="files-page">
      <PageHeader
        title={t('files.title')}
        description={t('files.subtitle')}
        readonly={false}
        actions={(
          <>
            <ActionButton
              label={t('common.refresh')}
              onClick={handleRefresh}
              disabled={fileMode === 'resource' && !selectedResourceId}
            />
            <ActionButton
              label={uploadPanelOpen ? t('files.hideUploadPanel') : t('files.showUploadPanel')}
              onClick={() => setUploadPanelOpen(o => !o)}
              variant="primary"
              disabled={fileMode === 'resource' && !selectedResourceId}
            />
          </>
        )}
      />
      <Notice notice={notice} onClose={onClose} />

      {duplicateHint && !duplicateHint.inactive && (
        <div className="file-duplicate-notice card">
          <div className="file-duplicate-notice-title">{t('files.duplicateFileTitle')}</div>
          <p className="file-duplicate-notice-body">{t('files.duplicateFileMessage')}</p>
          {duplicateHint.filename && (
            <div className="file-existing-selected">
              {t('files.existingFileSelected')}: <strong>{duplicateHint.filename}</strong>
              {duplicateHint.fileId && (
                <span className="file-existing-selected-id">
                  <code className="text-mono">{shortText(duplicateHint.fileId, 12)}</code>
                  <CopyButton value={duplicateHint.fileId} label="" />
                </span>
              )}
            </div>
          )}
          {duplicateHint.macro96 && (
            <p className="file-duplicate-macro96-hint">{t('files.macro96ExistingFileNextStep')}</p>
          )}
          <div className="file-duplicate-actions">
            {selectedFile && selectedFile.status === 'active' && (
              selectedFile.intermediate_status !== 'ready'
              && intermediateStatus?.status !== 'ready'
              && !intermediateStatus?.has_active_intermediate
            ) && (
              <ActionButton
                label={normalizing ? t('files.normalizing') : t('files.generateIntermediate')}
                onClick={() => void handleNormalize(false)}
                loading={normalizing}
                variant="primary"
              />
            )}
            {selectedFile?.status === 'active' && (
              <ActionButton
                label={t('files.useExistingFileForBatch')}
                onClick={() => { window.location.hash = '#/import-batches' }}
                variant="primary"
              />
            )}
            {duplicateHint.fileId && (
              <CopyButton value={duplicateHint.fileId} label={t('files.copyId')} />
            )}
          </div>
        </div>
      )}

      {duplicateHint?.inactive && (
        <div className="file-duplicate-notice file-inactive-warning card">
          <div className="file-duplicate-notice-title">{t('files.duplicateFileTitle')}</div>
          <p className="file-duplicate-notice-body">{t('files.duplicateFileInactive')}</p>
          {duplicateHint.filename && (
            <div className="file-existing-selected">
              {t('files.existingFileSelected')}: <strong>{duplicateHint.filename}</strong>
              {duplicateHint.fileId && (
                <span className="file-existing-selected-id">
                  <code className="text-mono">{shortText(duplicateHint.fileId, 12)}</code>
                  <CopyButton value={duplicateHint.fileId} label="" />
                </span>
              )}
            </div>
          )}
          <div className="file-restore-actions">
            {selectedFile && selectedFile.status !== 'active' && (
              <ActionButton
                label={t('files.restoreFileActive')}
                onClick={() => setRestoreTarget(selectedFile)}
                variant="primary"
              />
            )}
            {duplicateHint.fileId && !selectedFile && (
              <ActionButton
                label={t('files.restoreFileActive')}
                onClick={() => setRestoreTarget({ id: duplicateHint.fileId! } as ResourceFile)}
                variant="primary"
              />
            )}
          </div>
        </div>
      )}

      {renderToolbar()}
      {renderUploadPanel()}

      {fileMode === 'workspace' && renderWorkspaceMode()}

      {fileMode === 'resource' && (
        <>
          <div className="files-main-split">
            <div className="files-list-pane card">
              <div className="files-list-header">
                <span>{t('files.fileList')}{selectedResource ? ` — ${selectedResource.resource_code}` : ''}</span>
                <span className="count">{data?.total !== undefined ? t('common.totalRecords', { total: data.total }) : ''}</span>
              </div>
              {!selectedResourceId && <div className="preview-warning" style={{ margin: '8px 12px' }}>{t('files.noResourceSelected')}</div>}
              <div className="files-table-compact">
                <DataTable
                  columns={columns}
                  rows={data?.items ?? []}
                  loading={loading}
                  error={error}
                  total={data?.total}
                  getKey={r => r.id}
                  onRowClick={row => void selectFile(row)}
                  getRowClassName={row => row.id === selectedFile?.id ? 'selected-row' : undefined}
                  emptyText={selectedResourceId ? t('files.noFilesForSelectedResource') : t('files.noResourceSelected')}
                />
              </div>
            </div>
            {renderResourcePreviewPane()}
          </div>

          <ConfirmDialog
            open={regenerateConfirmOpen}
            title={t('files.regenerateIntermediateConfirmTitle')}
            message={t('files.regenerateIntermediateConfirmMessage')}
            confirmLabel={t('files.regenerateIntermediate')}
            loading={normalizing}
            onConfirm={() => void handleNormalize(true)}
            onCancel={() => setRegenerateConfirmOpen(false)}
          />

          <ConfirmDialog
            open={Boolean(deleteTarget)}
            title={t('files.deleteConfirmTitle')}
            message={deleteTarget ? t('files.deleteConfirmMessage') : undefined}
            confirmLabel={t('files.deactivateFile')}
            danger
            loading={deleting}
            onConfirm={handleDelete}
            onCancel={() => setDeleteTarget(null)}
          />

          <ConfirmDialog
            open={Boolean(restoreTarget)}
            title={t('files.restoreFileActiveConfirmTitle')}
            message={t('files.restoreFileActiveConfirmMessage')}
            confirmLabel={t('files.restoreFileActive')}
            loading={restoring}
            onConfirm={() => void handleRestoreActive()}
            onCancel={() => setRestoreTarget(null)}
          />
        </>
      )}
    </div>
  )
}
