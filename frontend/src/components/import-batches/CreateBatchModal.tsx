import { useState, useEffect, useMemo } from 'react'
import { X } from 'lucide-react'
import { ActionButton } from '../ActionButton'
import { StatusBadge } from '../StatusBadge'
import { type NoticeState } from '../Notice'
import { useData } from '../../hooks/useData'
import {
  fetchImportBatchOptions,
  createImportBatch,
  listResources,
  listResourceFiles,
  type ImportBatchDetail,
  type ResourceFile,
  type BatchFileBinding,
} from '../../api/endpoints'
import { readSessionIds, useSessionIds } from '../../hooks/useSessionIds'
import { useI18n } from '../../i18n-context'
import { inferBatchDefaultsFromResource } from '../../utils/batchParserDefaults'
import {
  getFileParserCompatibility,
  isAal3XmlParserKey,
  isMacro96XlsxParserKey,
  isParserCompatibleFile,
} from '../../utils/importBatchParserCompatibility'
import { formatApiErrorMessage } from '../../utils/apiErrorMessage'
import { BatchShortId } from './BatchShortId'
import {
  deriveBatchDefaultsFromFile,
  formatBytes,
  formatFileOptionLabel,
  formatFileRoleInBatchLabel,
  formatResourceLabel,
  isPdfFile,
  isSpreadsheetFile,
} from './batchModalUtils'

export function CreateBatchModal({  onClose,
  onCreated,
  setNotice,
}: {
  onClose: () => void
  onCreated: (batch: ImportBatchDetail) => void
  setNotice: (n: NoticeState) => void
}) {
  const { t } = useI18n()
  const { setIds } = useSessionIds()
  const sess = readSessionIds()
  const [saving, setSaving] = useState(false)
  const [resourceSearch, setResourceSearch] = useState('')
  const [selectedResourceId, setSelectedResourceId] = useState(sess.resource_id ?? '')
  const [selectedFileId, setSelectedFileId] = useState('')
  const [fileSearch, setFileSearch] = useState('')

  useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      if (e.key === 'Escape' && !saving) onClose()
    }
    window.addEventListener('keydown', onKey)
    return () => window.removeEventListener('keydown', onKey)
  }, [onClose, saving])

  const { data: options } = useData(() => fetchImportBatchOptions(), [])
  const { data: resourcesData, loading: resourcesLoading } = useData(
    () => listResources({ status: 'active', limit: 200 }),
    [],
  )
  const { data: filesData, loading: filesLoading, error: filesError } = useData(
    () => {
      if (!selectedResourceId) {
        return Promise.resolve({ items: [] as ResourceFile[], total: 0, limit: 200, offset: 0 })
      }
      return listResourceFiles(selectedResourceId, { limit: 200, status: 'active' })
    },
    [selectedResourceId],
  )

  const batchTypes = options?.batch_type ?? ['atlas_import', 'label_import', 'metadata_import']
  const fileRoles = useMemo(() => {
    const base = options?.file_role_in_batch ?? [
      'label_dictionary',
      'macro_region_pool_source',
      'primary_atlas_volume',
      'metadata',
      'auxiliary',
      'unknown',
    ]
    return Array.from(new Set([...base, 'macro_region_pool_source']))
  }, [options?.file_role_in_batch])

  const parserKeyOptions = useMemo(
    () => Array.from(new Set([...(options?.parser_key ?? []), 'aal3_xml', 'macro96_xlsx'].filter(Boolean))),
    [options?.parser_key],
  )

  const [form, setForm] = useState({
    batch_type: 'atlas_import',
    parser_key: '',
    file_role_in_batch: 'unknown',
    sort_order: 0,
    description: '',
    remark: '',
  })

  const filteredResources = useMemo(() => {
    const items = resourcesData?.items ?? []
    const q = resourceSearch.trim().toLowerCase()
    if (!q) return items
    return items.filter(r =>
      r.resource_code.toLowerCase().includes(q)
      || r.source_atlas.toLowerCase().includes(q)
      || r.source_version.toLowerCase().includes(q)
      || r.granularity_level.toLowerCase().includes(q)
      || (r.cn_name ?? '').toLowerCase().includes(q)
      || (r.en_name ?? '').toLowerCase().includes(q),
    )
  }, [resourcesData, resourceSearch])

  const selectedResource = useMemo(
    () => resourcesData?.items.find(r => r.id === selectedResourceId),
    [resourcesData, selectedResourceId],
  )

  const resourceParserDefaults = useMemo(
    () => inferBatchDefaultsFromResource(selectedResource ?? null),
    [selectedResource],
  )

  const activeFiles = useMemo(
    () => (filesData?.items ?? []).filter(f => f.status === 'active'),
    [filesData],
  )

  const filteredFiles = useMemo(() => {
    const q = fileSearch.trim().toLowerCase()
    let items = activeFiles
    const parserKey = form.parser_key.trim()
    if (parserKey) {
      items = activeFiles.filter(f => isParserCompatibleFile(f, parserKey, form.file_role_in_batch))
    }
    if (!q) return items
    return items.filter(f =>
      f.original_filename.toLowerCase().includes(q)
      || f.file_type.toLowerCase().includes(q)
      || f.file_role.toLowerCase().includes(q),
    )
  }, [activeFiles, fileSearch, form.parser_key, form.file_role_in_batch])

  const incompatibleActiveFiles = useMemo(() => {
    const parserKey = form.parser_key.trim()
    if (!parserKey) return []
    return activeFiles.filter(f => !isParserCompatibleFile(f, parserKey, form.file_role_in_batch))
  }, [activeFiles, form.parser_key, form.file_role_in_batch])

  const selectedFile = useMemo(
    () => activeFiles.find(f => f.id === selectedFileId),
    [activeFiles, selectedFileId],
  )

  useEffect(() => {
    if (!selectedResourceId) {
      setForm(f => ({
        ...f,
        batch_type: 'atlas_import',
        parser_key: '',
        file_role_in_batch: 'unknown',
        sort_order: 0,
      }))
      return
    }
    const defaults = inferBatchDefaultsFromResource(selectedResource ?? null)
    setForm(f => ({
      ...f,
      batch_type: defaults.batchType,
      parser_key: defaults.parserKey,
      file_role_in_batch: defaults.fileRoleInBatch,
      sort_order: 0,
    }))
  }, [selectedResourceId, selectedResource])

  useEffect(() => {
    if (!selectedFile) return
    const defaults = deriveBatchDefaultsFromFile(selectedResource, selectedFile)
    setForm(f => ({
      ...f,
      batch_type: defaults.batchType,
      parser_key: defaults.parserKey,
      file_role_in_batch: defaults.fileRoleInBatch,
    }))
  }, [selectedFileId, selectedResource, selectedFile])

  useEffect(() => {
    if (!selectedFileId || !form.parser_key.trim()) return
    const f = activeFiles.find(x => x.id === selectedFileId)
    if (f && !isParserCompatibleFile(f, form.parser_key, form.file_role_in_batch)) {
      setSelectedFileId('')
    }
  }, [form.parser_key, form.file_role_in_batch, selectedFileId, activeFiles])

  const selectedFileCompatibility = useMemo(() => {
    if (!selectedFile || !form.parser_key.trim()) return null
    return getFileParserCompatibility(selectedFile, form.parser_key, form.file_role_in_batch)
  }, [selectedFile, form.parser_key, form.file_role_in_batch])

  const createDisabledReason = useMemo(() => {
    if (!selectedResourceId) return t('batches.noResourceSelected')
    if (!form.parser_key.trim()) return t('batches.parserKeyRequired')
    if (!form.file_role_in_batch.trim()) return t('batches.fileRoleInBatchRequired')
    if (!selectedFileId) {
      if (isMacro96XlsxParserKey(form.parser_key)) {
        return filteredFiles.length === 0
          ? t('batches.noMacro96CompatibleFiles')
          : t('batches.selectMacro96XlsxFile')
      }
      if (isAal3XmlParserKey(form.parser_key)) {
        return filteredFiles.length === 0
          ? t('batches.noAal3CompatibleFiles')
          : t('batches.selectAal3XmlFile')
      }
      return t('batches.selectFilePlaceholder')
    }
    const fileForCheck = activeFiles.find(f => f.id === selectedFileId)
    if (!fileForCheck || fileForCheck.status !== 'active') {
      return t('files.cannotUseInactiveFileForBatch')
    }
    const { compatible, reason } = getFileParserCompatibility(
      fileForCheck,
      form.parser_key,
      form.file_role_in_batch,
    )
    if (!compatible) return reason ?? t('batches.fileIncompatibleWithParser')
    return null
  }, [
    selectedResourceId,
    form.parser_key,
    form.file_role_in_batch,
    selectedFileId,
    activeFiles,
    filteredFiles.length,
    t,
  ])

  const fld = (k: keyof typeof form) =>
    (e: React.ChangeEvent<HTMLInputElement | HTMLSelectElement | HTMLTextAreaElement>) =>
      setForm(f => ({ ...f, [k]: k === 'sort_order' ? Number(e.target.value) : e.target.value }))

  async function handleCreate() {
    if (!selectedResourceId) {
      setNotice({ type: 'error', message: t('batches.noResourceSelected') })
      return
    }
    if (!selectedFileId) {
      setNotice({ type: 'error', message: t('batches.selectFilePlaceholder') })
      return
    }
    const fileForCheck = activeFiles.find(f => f.id === selectedFileId)
    if (!fileForCheck) {
      setNotice({ type: 'error', message: t('files.cannotUseInactiveFileForBatch') })
      return
    }
    if (fileForCheck.status !== 'active') {
      setNotice({ type: 'error', message: t('files.cannotUseInactiveFileForBatch') })
      return
    }
    if (fileForCheck && form.parser_key.trim()) {
      const { compatible, reason } = getFileParserCompatibility(
        fileForCheck,
        form.parser_key,
        form.file_role_in_batch,
      )
      if (!compatible) {
        setNotice({
          type: 'error',
          message: reason ?? t('batches.fileIncompatibleWithParser'),
        })
        return
      }
    }
    setSaving(true)
    try {
      const files: BatchFileBinding[] = [{
        file_id: selectedFileId,
        file_role_in_batch: form.file_role_in_batch,
        sort_order: form.sort_order,
      }]
      const res = await createImportBatch({
        resource_id: selectedResourceId,
        batch_type: form.batch_type,
        parser_key: form.parser_key.trim() || undefined,
        files,
        description: form.description.trim() || undefined,
        remark: form.remark.trim() || undefined,
      })
      setIds({ batch_id: res.id, resource_id: res.resource_id, file_id: selectedFileId })
      const msg = res.warnings?.length
        ? `${t('batches.createSuccess')} (${res.warnings.length} warnings)`
        : t('batches.createSuccess')
      setNotice({ type: res.warnings?.length ? 'warning' : 'success', message: msg })
      onCreated(res)
    } catch (e) {
      setNotice({ type: 'error', message: formatApiErrorMessage(e) })
    } finally {
      setSaving(false)
    }
  }

  return (
    <div className="batch-create-modal-backdrop" role="dialog" aria-modal="true" aria-labelledby="batch-create-modal-title">
      <div className="batch-create-modal">
        <div className="batch-create-modal-header">
          <div className="batch-create-modal-header-text">
            <h2 id="batch-create-modal-title" className="batch-create-modal-title">{t('batches.createBatchTitle')}</h2>
            <p className="batch-create-modal-subtitle">{t('batches.createBatchSubtitle')}</p>
          </div>
          <button
            type="button"
            className="batch-create-modal-close"
            onClick={onClose}
            disabled={saving}
            aria-label={t('batches.cancelCreate')}
          >
            <X size={18} />
          </button>
        </div>

        <div className="batch-hidden-id-notice batch-hidden-id-notice--compact">
          <span className="batch-hidden-id-notice-title">{t('batches.hiddenBackendIdsNotice')}</span>
          <span className="batch-hidden-id-notice-text">{t('batches.hiddenBackendIdsNoticeText')}</span>
        </div>

        <div className="batch-create-modal-body">
          <div className="batch-create-modal-grid">
            {/* Column 1: Resource */}
            <div className="batch-create-column">
              <div className="batch-create-column-header">{t('batches.selectResource')}</div>
              <label className="form-label">{t('batches.searchResource')}</label>
              <input
                className="form-input"
                placeholder={t('batches.selectResourcePlaceholder')}
                value={resourceSearch}
                onChange={e => setResourceSearch(e.target.value)}
              />
              {resourcesLoading && <div className="batch-create-hint">{t('common.loading')}</div>}
              {!resourcesLoading && (
                <select
                  className="form-select batch-resource-select"
                  value={selectedResourceId}
                  onChange={e => {
                    const resourceId = e.target.value
                    setSelectedResourceId(resourceId)
                    setSelectedFileId('')
                    setFileSearch('')
                  }}
                >
                  <option value="">{t('batches.selectResourcePlaceholder')}</option>
                  {filteredResources.map(r => (
                    <option key={r.id} value={r.id}>{formatResourceLabel(r)}</option>
                  ))}
                </select>
              )}
              {selectedResource ? (
                <div className="batch-selected-summary">
                  <div className="batch-create-column-subheader">{t('batches.selectedResource')}</div>
                  <div className="batch-summary-grid batch-summary-grid--compact">
                    <div><span className="batch-summary-label">{t('resources.resourceCode')}</span>{selectedResource.resource_code}</div>
                    <div><span className="batch-summary-label">{t('resources.sourceAtlas')}</span>{selectedResource.source_atlas}</div>
                    <div><span className="batch-summary-label">{t('resources.sourceVersion')}</span>{selectedResource.source_version}</div>
                    <div><span className="batch-summary-label">{t('resources.granularityLevel')}</span>{selectedResource.granularity_level}</div>
                    <div><span className="batch-summary-label">{t('resources.granularityFamily')}</span>{selectedResource.granularity_family}</div>
                    <div><span className="batch-summary-label">{t('batches.status')}</span><StatusBadge status={selectedResource.status} /></div>
                    <div className="batch-summary-id">
                      <span className="batch-summary-label">{t('batches.resourceId')}</span>
                      <BatchShortId id={selectedResource.id} copyTitle={t('batches.copyResourceId')} />
                    </div>
                  </div>
                </div>
              ) : (
                <div className="batch-create-hint">{t('batches.noResourceSelected')}</div>
              )}
            </div>

            {/* Column 2: File */}
            <div className="batch-create-column">
              <div className="batch-create-column-header">{t('batches.selectFile')}</div>
              {!selectedResourceId && (
                <div className="batch-create-hint">{t('batches.noResourceSelected')}</div>
              )}
              {selectedResourceId && (
                <>
                  <label className="form-label">{t('batches.searchFile')}</label>
                  {filesLoading && <div className="batch-create-hint">{t('common.loading')}</div>}
                  {filesError && (
                    <div className="batch-create-warning">{t('batches.loadFilesFailed')}: {filesError}</div>
                  )}
                  {!filesLoading && !filesError && activeFiles.length === 0 && (
                    <div className="batch-create-warning">{t('batches.noActiveFilesForResource')}</div>
                  )}
                  {!filesLoading && activeFiles.length > 0 && (
                    <>
                      {isAal3XmlParserKey(form.parser_key) && (
                        <div className="batch-parser-hint batch-create-hint">{t('batches.aal3XmlFileHint')}</div>
                      )}
                      {isMacro96XlsxParserKey(form.parser_key) && (
                        <div className="batch-parser-hint batch-create-hint">{t('batches.macro96XlsxFileHint')}</div>
                      )}
                      <input
                        className="form-input"
                        placeholder={t('batches.selectFilePlaceholder')}
                        value={fileSearch}
                        onChange={e => setFileSearch(e.target.value)}
                      />
                      <select
                        className="form-select batch-file-select"
                        value={selectedFileId}
                        onChange={e => setSelectedFileId(e.target.value)}
                      >
                        <option value="">{t('batches.selectFilePlaceholder')}</option>
                        {filteredFiles.map(f => (
                          <option key={f.id} value={f.id} className="batch-compatible-file-option">
                            {formatFileOptionLabel(f)}
                          </option>
                        ))}
                      </select>
                      {isAal3XmlParserKey(form.parser_key) && filteredFiles.length === 0 && (
                        <div className="batch-create-warning">{t('batches.selectAal3XmlFile')}</div>
                      )}
                      {isMacro96XlsxParserKey(form.parser_key) && filteredFiles.length === 0 && (
                        <div className="batch-create-warning">{t('batches.noMacro96CompatibleFiles')}</div>
                      )}
                      {form.parser_key.trim() && incompatibleActiveFiles.length > 0 && (
                        <div className="batch-incompatible-file-note batch-create-hint">
                          {t('batches.hiddenIncompatibleFiles', {
                            count: incompatibleActiveFiles.length,
                            parser: form.parser_key,
                          })}
                        </div>
                      )}
                    </>
                  )}
                  {selectedFile ? (
                    <div className="batch-selected-summary">
                      <div className="batch-create-column-subheader">{t('batches.selectedFile')}</div>
                      <div className="batch-summary-grid batch-summary-grid--compact">
                        <div><span className="batch-summary-label">{t('batches.fileName')}</span>{selectedFile.original_filename}</div>
                        <div><span className="batch-summary-label">{t('batches.fileType')}</span>{selectedFile.file_type}</div>
                        <div><span className="batch-summary-label">{t('batches.fileRole')}</span>{selectedFile.file_role}</div>
                        <div><span className="batch-summary-label">{t('batches.fileStatus')}</span><StatusBadge status={selectedFile.status} /></div>
                        <div><span className="batch-summary-label">{t('batches.intermediateStatus')}</span>{selectedFile.intermediate_status ?? '—'}</div>
                        {selectedFile.latest_intermediate_kind && (
                          <div><span className="batch-summary-label">{t('files.intermediateKind')}</span>{selectedFile.latest_intermediate_kind}</div>
                        )}
                        <div><span className="batch-summary-label">{t('batches.fileSize')}</span>{formatBytes(selectedFile.file_size)}</div>
                        <div className="batch-summary-id">
                          <span className="batch-summary-label">{t('batches.fileId')}</span>
                          <BatchShortId id={selectedFile.id} copyTitle={t('batches.copyFileId')} />
                        </div>
                      </div>
                      {selectedFile.intermediate_status === 'ready' && (
                        <div className="batch-create-ready">{t('batches.fileIntermediateReady')}</div>
                      )}
                      {selectedFileCompatibility?.warning && (
                        <div className="batch-parser-warning batch-create-warning">
                          {t('batches.fileIntermediateRecommended')}
                        </div>
                      )}
                      {(!selectedFile.intermediate_status || selectedFile.intermediate_status === 'missing') && (
                        <div className="batch-create-warning">{t('batches.fileIntermediateMissing')}</div>
                      )}
                      {isMacro96XlsxParserKey(form.parser_key) && (
                        <div className="batch-create-hint">{t('batches.macro96BatchNextStep')}</div>
                      )}
                      {isSpreadsheetFile(selectedFile) && isAal3XmlParserKey(form.parser_key) && (
                        <div className="batch-create-warning">{t('batches.fileIncompatibleWithAal3')}</div>
                      )}
                      {isPdfFile(selectedFile) && (
                        <div className="batch-create-warning">{t('batches.pdfDocumentationNotice')}</div>
                      )}
                    </div>
                  ) : selectedResourceId && !filesLoading && activeFiles.length > 0 ? (
                    <div className="batch-create-hint">{t('batches.selectFilePlaceholder')}</div>
                  ) : null}
                </>
              )}
            </div>

            {/* Column 3: Batch parameters */}
            <div className="batch-create-column">
              <div className="batch-create-column-header">{t('batches.batchParameters')}</div>
              <div className="form-field">
                <label className="form-label">{t('batches.batchType')}</label>
                <select className="form-select" value={form.batch_type} onChange={fld('batch_type')}>
                  {batchTypes.map(v => <option key={v} value={v}>{v}</option>)}
                </select>
              </div>
              <div className="form-field">
                <label className="form-label">{t('batches.parserKey')}</label>
                <input
                  className="form-input"
                  list="batch-parser-key-options"
                  value={form.parser_key}
                  onChange={fld('parser_key')}
                  placeholder={resourceParserDefaults.parserKey || 'aal3_xml / macro96_xlsx'}
                />
                <datalist id="batch-parser-key-options">
                  {parserKeyOptions.map(v => <option key={v} value={v} />)}
                </datalist>
                {form.parser_key.trim() && (
                  <div className="batch-parser-hint batch-create-hint">
                    {isAal3XmlParserKey(form.parser_key)
                      ? t('batches.parserAal3Xml')
                      : isMacro96XlsxParserKey(form.parser_key)
                        ? t('batches.parserMacro96Xlsx')
                        : resourceParserDefaults.parserDescription}
                  </div>
                )}
              </div>
              <div className="form-field">
                <label className="form-label">{t('batches.fileRoleInBatch')}</label>
                <select className="form-select" value={form.file_role_in_batch} onChange={fld('file_role_in_batch')}>
                  {fileRoles.map(r => (
                    <option key={r} value={r}>{formatFileRoleInBatchLabel(r, t)}</option>
                  ))}
                </select>
                {form.file_role_in_batch === 'macro_region_pool_source' && (
                  <div className="batch-parser-hint batch-create-hint">
                    {t('batches.fileRoleMacroRegionPoolSourceDescription')}
                  </div>
                )}
              </div>
              <div className="form-field">
                <label className="form-label">{t('batches.orderIndex')}</label>
                <input className="form-input" type="number" min={0} value={form.sort_order} onChange={fld('sort_order')} />
              </div>
              <div className="form-field">
                <label className="form-label">{t('common.description')}</label>
                <input className="form-input" value={form.description} onChange={fld('description')} />
              </div>
              <div className="form-field">
                <label className="form-label">{t('common.remark')}</label>
                <input className="form-input" value={form.remark} onChange={fld('remark')} />
              </div>
            </div>
          </div>
        </div>

        <div className="batch-create-modal-footer">
          <ActionButton label={t('batches.cancelCreate')} variant="default" onClick={onClose} disabled={saving} />
          <ActionButton
            label={t('batches.createWithSelectedFile')}
            variant="primary"
            onClick={handleCreate}
            loading={saving}
            disabled={Boolean(createDisabledReason) || saving}
          />
          {createDisabledReason && (
            <div className="batch-create-hint batch-incompatible-file-note">{createDisabledReason}</div>
          )}
        </div>
      </div>
    </div>
  )
}
