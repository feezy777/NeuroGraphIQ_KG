import { useCallback, useEffect, useMemo, useState, type ChangeEvent } from 'react'
import { PageHeader } from '../components/PageHeader'
import { DataTable, type Column } from '../components/DataTable'
import { StatusBadge } from '../components/StatusBadge'
import { FormPanel } from '../components/FormPanel'
import { ActionButton } from '../components/ActionButton'
import { Notice, type NoticeState } from '../components/Notice'
import { ConfirmDialog } from '../components/ConfirmDialog'
import { ResourceDestructiveDeleteModal } from '../components/ResourceDestructiveDeleteModal'
import { KeyValuePanel } from '../components/KeyValuePanel'
import { useData } from '../hooks/useData'
import {
  createResource,
  deleteResource,
  getResource,
  getResourceOptions,
  listResources,
  restoreResource,
  updateResource,
  type AtlasResource,
  type ResourceCreate,
  type ResourceOptions,
  type ResourceUpdate,
} from '../api/endpoints'
import { ApiError } from '../api/client'
import { useSessionIds } from '../hooks/useSessionIds'
import { CopyButton } from '../components/CopyButton'
import { useI18n } from '../i18n-context'
import {
  formatDependencyCounts,
  parseDuplicateResourceDetail,
  type DuplicateResourceDetail,
} from '../utils/duplicateResourceError'
import {
  buildDefaultForm,
  buildMacroPresetForm,
  buildMacroPresetExisting,
  EMPTY_MACRO_PRESET_EXISTING,
  filterFamiliesForGranularity,
  getStoredGranularityKey,
  GRANULARITY_KEYS,
  isAal3AtlasResource,
  isMacro96Resource,
  MACRO_RESOURCE_PRESET_KEYS,
  normalizeMacroPresetKey,
  RESOURCE_GRANULARITY_CONFIG,
  saveGranularityKey,
  type MacroPresetFallbackFlags,
  type MacroResourcePresetKey,
  type ResourceFormDefaults,
  type ResourceGranularityKey,
} from '../config/granularity'

type ResourceFormMode = 'create' | 'edit'

const FALLBACK_OPTIONS: ResourceOptions = {
  resource_type: ['atlas', 'label_table', 'ontology', 'connectivity_matrix', 'literature', 'terminology'],
  species: ['human', 'mouse', 'unknown'],
  granularity_level: ['macro', 'meso', 'micro', 'molecular', 'term'],
  granularity_family: [
    'macro_clinical',
    'meso_anatomical',
    'subregion_connectivity',
    'cytoarchitectonic',
    'histological',
    'molecular',
    'terminology',
  ],
  template_space: ['MNI152', 'fsaverage', 'native', 'unknown', 'not_applicable'],
  status: ['active', 'inactive', 'archived'],
}

function resourceToForm(resource: AtlasResource): ResourceFormDefaults {
  return {
    resource_code: resource.resource_code,
    source_atlas: resource.source_atlas,
    source_version: resource.source_version,
    resource_type: resource.resource_type,
    species: resource.species,
    granularity_level: resource.granularity_level,
    granularity_family: resource.granularity_family,
    template_space: resource.template_space,
    cn_name: resource.cn_name ?? '',
    en_name: resource.en_name ?? '',
    description: resource.description ?? '',
    remark: resource.remark ?? '',
    status: resource.status,
  }
}

function optionalText(value: string): string | undefined {
  const trimmed = value.trim()
  return trimmed ? trimmed : undefined
}

function toCreatePayload(form: ResourceFormDefaults): ResourceCreate {
  return {
    resource_code: form.resource_code.trim(),
    source_atlas: form.source_atlas.trim(),
    source_version: form.source_version.trim(),
    resource_type: form.resource_type,
    species: form.species,
    granularity_level: form.granularity_level,
    granularity_family: form.granularity_family,
    template_space: form.template_space,
    cn_name: optionalText(form.cn_name),
    en_name: optionalText(form.en_name),
    description: optionalText(form.description),
    remark: optionalText(form.remark),
    status: form.status,
  }
}

function toUpdatePayload(form: ResourceFormDefaults): ResourceUpdate {
  return {
    source_atlas: form.source_atlas.trim(),
    source_version: form.source_version.trim(),
    resource_type: form.resource_type,
    species: form.species,
    granularity_level: form.granularity_level,
    granularity_family: form.granularity_family,
    template_space: form.template_space,
    cn_name: form.cn_name.trim(),
    en_name: form.en_name.trim(),
    description: form.description.trim(),
    remark: form.remark.trim(),
    status: form.status,
  }
}

function getErrorMessage(error: unknown): string {
  return error instanceof ApiError || error instanceof Error ? error.message : String(error)
}

function shortId(id: string): string {
  return `${id.slice(0, 8)}...`
}

interface ResourceFormProps {
  form: ResourceFormDefaults
  mode: ResourceFormMode
  options: ResourceOptions
  saving: boolean
  activeGranularity: ResourceGranularityKey
  showAllFamilies: boolean
  macroPreset: MacroResourcePresetKey | null
  presetFallbacks: MacroPresetFallbackFlags
  onToggleAllFamilies: () => void
  onChange: (next: ResourceFormDefaults) => void
  onCancel: () => void
  onSubmit: () => void
  t: (key: string, params?: Record<string, string | number>) => string
}

function MacroPresetSection({
  selected,
  onSelect,
  presetExisting = EMPTY_MACRO_PRESET_EXISTING,
  onUseExisting,
  onRestoreOrPurge,
  t,
}: {
  selected: MacroResourcePresetKey
  onSelect: (key: MacroResourcePresetKey) => void
  presetExisting?: Partial<Record<MacroResourcePresetKey, AtlasResource>>
  onUseExisting: (row: AtlasResource) => void
  onRestoreOrPurge: (row: AtlasResource) => void
  t: (key: string, params?: Record<string, string | number>) => string
}) {
  return (
    <div className="resource-preset-section">
      <div className="resource-preset-section-title">{t('resources.macroPresets.title')}</div>
      <div className="resource-preset-grid">
        {MACRO_RESOURCE_PRESET_KEYS.map(key => {
          const existing = presetExisting?.[key]
          const isActive = existing?.status === 'active' && !existing?.deleted_at
          return (
            <div key={key} className={`resource-preset-card-wrap${selected === key ? ' resource-preset-card-wrap--active' : ''}`}>
              <button
                type="button"
                className={`resource-preset-card${selected === key ? ' resource-preset-card--active' : ''}`}
                onClick={() => onSelect(key)}
              >
                <div className="resource-preset-title">
                  {t(key === 'aal3' ? 'resources.macroPresets.aal3Title' : 'resources.macroPresets.macro96Title')}
                  {existing && (
                    <span className={`resource-preset-exists-badge${isActive ? ' active' : ' archived'}`}>
                      {isActive ? t('resources.presetExistsActive') : t('resources.presetExistsArchived')}
                    </span>
                  )}
                </div>
                <div className="resource-preset-subtitle">
                  {t(key === 'aal3' ? 'resources.macroPresets.aal3Subtitle' : 'resources.macroPresets.macro96Subtitle')}
                </div>
                <div className="resource-preset-description">
                  {t(key === 'aal3' ? 'resources.macroPresets.aal3Description' : 'resources.macroPresets.macro96Description')}
                </div>
              </button>
              {existing && (
                <div className="resource-preset-existing-actions">
                  {isActive ? (
                    <ActionButton
                      label={t('resources.useExistingActiveResource')}
                      onClick={() => onUseExisting(existing)}
                      variant="primary"
                    />
                  ) : (
                    <ActionButton
                      label={t('resources.restoreOrPurge')}
                      onClick={() => onRestoreOrPurge(existing)}
                    />
                  )}
                </div>
              )}
            </div>
          )
        })}
      </div>
    </div>
  )
}

function ResourceForm({
  form,
  mode,
  options,
  saving,
  activeGranularity,
  showAllFamilies,
  macroPreset,
  presetFallbacks,
  onToggleAllFamilies,
  onChange,
  onCancel,
  onSubmit,
  t,
}: ResourceFormProps) {
  const config = RESOURCE_GRANULARITY_CONFIG[activeGranularity]
  const familyOptions = filterFamiliesForGranularity(config, options, showAllFamilies)

  const change =
    (key: keyof ResourceFormDefaults) =>
    (event: ChangeEvent<HTMLInputElement | HTMLSelectElement | HTMLTextAreaElement>) => {
      onChange({ ...form, [key]: event.target.value })
    }

  return (
    <FormPanel
      title={mode === 'create'
        ? t('resources.createInGranularity', { granularity: t(config.labelKey) })
        : t('resources.editResource')}
      defaultOpen
    >
      {mode === 'create' && (
        <div className="granularity-info-notice">{t('resources.lockedGranularityNotice')}</div>
      )}

      {mode === 'create' && activeGranularity === 'macro' && macroPreset && (
        <>
          <div className="resource-preset-selected">
            {t('resources.macroPresets.selectedPreset')}:{' '}
            <strong>
              {t(macroPreset === 'aal3' ? 'resources.macroPresets.aal3Title' : 'resources.macroPresets.macro96Title')}
            </strong>
          </div>
          <div className="resource-preset-description-card">
            <div className="resource-preset-description-card-title">
              {t(macroPreset === 'aal3' ? 'resources.macroPresets.aal3Title' : 'resources.macroPresets.macro96Title')}
            </div>
            <p className="resource-preset-description-card-body">
              {t(macroPreset === 'aal3' ? 'resources.macroPresets.aal3FormHint' : 'resources.macroPresets.macro96FormHint')}
            </p>
            {macroPreset === 'macro96' && (
              <div className="resource-preset-warning">{t('resources.macroPresets.macro96Warning')}</div>
            )}
          </div>
          {presetFallbacks.standardPool && (
            <div className="resource-preset-warning">{t('resources.macroPresets.standardPoolFallback')}</div>
          )}
          {presetFallbacks.templateSpace && (
            <div className="resource-preset-warning">{t('resources.macroPresets.templateSpaceFallback')}</div>
          )}
        </>
      )}

      <div className="form-row">
        <div className="form-field resource-form-wide">
          <label className="form-label">{t('resources.resourceCode')} *</label>
          <input
            className="form-input"
            value={form.resource_code}
            onChange={change('resource_code')}
            placeholder={config.default_resource_code}
            disabled={mode === 'edit'}
          />
          {mode === 'edit' && (
            <span className="form-hint">{t('resources.resourceCodeEditHint')}</span>
          )}
        </div>
        <div className="form-field">
          <label className="form-label">{t('resources.sourceAtlas')} *</label>
          <input
            className="form-input"
            value={form.source_atlas}
            onChange={change('source_atlas')}
            placeholder={config.default_source_atlas}
            list={`atlas-suggestions-${activeGranularity}`}
          />
          <datalist id={`atlas-suggestions-${activeGranularity}`}>
            {config.recommended_atlases.map(a => <option key={a} value={a} />)}
          </datalist>
        </div>
        <div className="form-field">
          <label className="form-label">{t('resources.sourceVersion')} *</label>
          <input className="form-input" value={form.source_version} onChange={change('source_version')} placeholder="v1" />
        </div>
      </div>

      <div className="form-row">
        <div className="form-field">
          <label className="form-label">{t('resources.resourceType')}</label>
          <select className="form-select" value={form.resource_type} onChange={change('resource_type')}>
            {options.resource_type.map(v => <option key={v} value={v}>{v}</option>)}
          </select>
        </div>
        <div className="form-field">
          <label className="form-label">{t('resources.species')}</label>
          <select className="form-select" value={form.species} onChange={change('species')}>
            {options.species.map(v => <option key={v} value={v}>{v}</option>)}
          </select>
        </div>
        <div className="form-field">
          <label className="form-label">{t('resources.granularityLevel')}</label>
          <select
            className="form-select"
            value={form.granularity_level}
            onChange={change('granularity_level')}
            disabled={mode === 'create'}
          >
            {options.granularity_level.map(v => <option key={v} value={v}>{v}</option>)}
          </select>
        </div>
        <div className="form-field">
          <label className="form-label">
            {showAllFamilies ? t('resources.allFamilies') : t('resources.recommendedFamilies')}
          </label>
          <select className="form-select" value={form.granularity_family} onChange={change('granularity_family')}>
            {familyOptions.map(v => <option key={v} value={v}>{v}</option>)}
          </select>
          <button type="button" className="granularity-advanced-toggle" onClick={onToggleAllFamilies}>
            {showAllFamilies ? t('resources.recommendedFamilies') : t('resources.advancedFamilyMode')}
          </button>
        </div>
        <div className="form-field">
          <label className="form-label">{t('resources.templateSpace')}</label>
          <select className="form-select" value={form.template_space} onChange={change('template_space')}>
            {options.template_space.map(v => <option key={v} value={v}>{v}</option>)}
          </select>
        </div>
        {mode === 'edit' && (
          <div className="form-field">
            <label className="form-label">{t('resources.status')}</label>
            <select className="form-select" value={form.status} onChange={change('status')}>
              {options.status.map(v => <option key={v} value={v}>{v}</option>)}
            </select>
          </div>
        )}
      </div>

      <div className="form-row">
        <div className="form-field resource-form-wide">
          <label className="form-label">{t('resources.cnName')}</label>
          <input className="form-input" value={form.cn_name} onChange={change('cn_name')} />
        </div>
        <div className="form-field resource-form-wide">
          <label className="form-label">{t('resources.enName')}</label>
          <input className="form-input" value={form.en_name} onChange={change('en_name')} />
        </div>
      </div>

      <div className="form-row">
        <div className="form-field resource-form-text">
          <label className="form-label">{t('resources.descriptionField')}</label>
          <textarea className="form-textarea" value={form.description} onChange={change('description')} />
        </div>
        <div className="form-field resource-form-text">
          <label className="form-label">{t('resources.remark')}</label>
          <textarea className="form-textarea" value={form.remark} onChange={change('remark')} />
        </div>
      </div>

      <div className="settings-actions">
        <ActionButton
          label={mode === 'create' ? t('resources.createResource') : t('common.save')}
          onClick={onSubmit}
          loading={saving}
          variant="primary"
        />
        <ActionButton label={t('common.cancel')} onClick={onCancel} disabled={saving} />
      </div>
    </FormPanel>
  )
}

export function ResourcesPage() {
  const { t } = useI18n()
  const [activeGranularity, setActiveGranularity] = useState<ResourceGranularityKey>(getStoredGranularityKey)
  const [filters, setFilters] = useState({ status: 'active', source_atlas: '', granularity_family: '' })
  const [options, setOptions] = useState<ResourceOptions>(FALLBACK_OPTIONS)
  const [notice, setNotice] = useState<NoticeState | null>(null)
  const [formMode, setFormMode] = useState<ResourceFormMode>('create')
  const [formOpen, setFormOpen] = useState(false)
  const [macroPreset, setMacroPreset] = useState<MacroResourcePresetKey>('aal3')
  const [presetFallbacks, setPresetFallbacks] = useState<MacroPresetFallbackFlags>({})
  const [form, setForm] = useState<ResourceFormDefaults>(() => {
    const { form: initial } = buildMacroPresetForm('aal3', FALLBACK_OPTIONS)
    return initial
  })
  const [showMacro96NextStep, setShowMacro96NextStep] = useState(false)
  const [showAllFamilies, setShowAllFamilies] = useState(false)
  const [editingId, setEditingId] = useState<string | null>(null)
  const [saving, setSaving] = useState(false)
  const [detail, setDetail] = useState<AtlasResource | null>(null)
  const [detailLoading, setDetailLoading] = useState(false)
  const [deleteTarget, setDeleteTarget] = useState<AtlasResource | null>(null)
  const [destructiveDeleteTarget, setDestructiveDeleteTarget] = useState<AtlasResource | null>(null)
  const [destructiveThenRecreate, setDestructiveThenRecreate] = useState(false)
  const [restoreTarget, setRestoreTarget] = useState<AtlasResource | null>(null)
  const [duplicateConflict, setDuplicateConflict] = useState<DuplicateResourceDetail | null>(null)
  const [pendingCreatePayload, setPendingCreatePayload] = useState<ResourceCreate | null>(null)
  const [deleting, setDeleting] = useState(false)
  const [restoring, setRestoring] = useState(false)
  const [countTick, setCountTick] = useState(0)
  const { ids, setIds, clearKey } = useSessionIds()

  const activeConfig = RESOURCE_GRANULARITY_CONFIG[activeGranularity]

  useEffect(() => {
    getResourceOptions()
      .then(setOptions)
      .catch(error => {
        setNotice({ type: 'error', message: t('resources.optionsFailed', { error: getErrorMessage(error) }) })
      })
  }, [t])

  const query = useMemo(
    () => ({
      status: filters.status === 'all' ? undefined : filters.status,
      source_atlas: filters.source_atlas.trim() || undefined,
      granularity_level: activeConfig.granularity_level,
      granularity_family: filters.granularity_family || undefined,
      limit: 100,
    }),
    [filters, activeConfig.granularity_level],
  )

  const { data, loading, error, reload } = useData(
    () => listResources(query),
    [JSON.stringify(query)],
  )

  const { data: allResourcesData, reload: reloadAllResources } = useData(
    () => listResources({ limit: 200 }),
    [countTick],
  )

  const presetExisting = useMemo(
    () => buildMacroPresetExisting(allResourcesData?.items ?? []),
    [allResourcesData],
  )

  const { data: granularityCounts } = useData(
    async () => {
      const entries = await Promise.all(
        GRANULARITY_KEYS.map(async key => {
          const level = RESOURCE_GRANULARITY_CONFIG[key].granularity_level
          const res = await listResources({ granularity_level: level, limit: 1 })
          return [key, res.total] as const
        }),
      )
      return Object.fromEntries(entries) as Record<ResourceGranularityKey, number>
    },
    [countTick, data?.total],
  )

  const onClose = useCallback(() => setNotice(null), [])

  function refreshAll() {
    reload()
    reloadAllResources()
    setCountTick(x => x + 1)
  }

  function selectExistingResource(row: AtlasResource) {
    setDetail(row)
    setIds({ resource_id: row.id })
    setNotice({ type: 'success', message: t('resources.useExistingActiveResource') + `: ${row.resource_code}` })
  }

  function openDestructiveDelete(row: AtlasResource, thenRecreate = false) {
    setDestructiveDeleteTarget(row)
    setDestructiveThenRecreate(thenRecreate)
  }

  function openRestoreOrPurgeFlow(row: AtlasResource) {
    setDetail(row)
    setDuplicateConflict({
      code: 'DUPLICATE_RESOURCE_CODE',
      existing_resource: row,
      can_restore: true,
      can_purge: true,
      resource_code: row.resource_code,
    })
    setNotice({ type: 'warning', message: t('resources.duplicateArchivedResourceAction') })
  }

  useEffect(() => {
    if (error && (error.includes('422') || error.includes('Input should be'))) {
      setNotice({ type: 'error', message: t('resources.filterInvalid') })
    }
  }, [error, t])

  function applyMacroPreset(key: MacroResourcePresetKey, openForm = false) {
    const safeKey = normalizeMacroPresetKey(key)
    const { form: nextForm, fallbacks } = buildMacroPresetForm(safeKey, options)
    setMacroPreset(safeKey)
    setPresetFallbacks(fallbacks)
    setForm(nextForm)
    setShowAllFamilies(false)
    setFilters(f => ({ ...f, source_atlas: '' }))
    if (openForm) {
      setFormMode('create')
      setEditingId(null)
      setFormOpen(true)
    }
  }

  function switchGranularity(key: ResourceGranularityKey) {
    if (key === activeGranularity) return
    if (formOpen && formMode === 'create') {
      setNotice({ type: 'warning', message: t('resources.switchGranularityWarning') })
    }
    setActiveGranularity(key)
    saveGranularityKey(key)
    setShowAllFamilies(false)
    setShowMacro96NextStep(false)
    if (key === 'macro') {
      applyMacroPreset('aal3')
    } else {
      setForm(buildDefaultForm(key, options))
    }
    setFormOpen(false)
    setDetail(null)
    setFilters({ status: 'active', source_atlas: '', granularity_family: '' })
  }

  function validateRequired(): boolean {
    if (!form.resource_code.trim() || !form.source_atlas.trim() || !form.source_version.trim()) {
      setNotice({ type: 'error', message: t('resources.requiredFields') })
      return false
    }
    return true
  }

  function openCreateForm() {
    setFormMode('create')
    setEditingId(null)
    setShowMacro96NextStep(false)
    if (activeGranularity === 'macro') {
      applyMacroPreset(macroPreset)
    } else {
      setForm(buildDefaultForm(activeGranularity, options))
    }
    setShowAllFamilies(false)
    setFormOpen(true)
  }

  async function openEditForm(row: AtlasResource) {
    setFormMode('edit')
    setEditingId(row.id)
    setForm(resourceToForm(row))
    setShowAllFamilies(true)
    setFormOpen(true)
    try {
      const fresh = await getResource(row.id)
      setForm(resourceToForm(fresh))
    } catch (err) {
      setNotice({ type: 'error', message: t('resources.detailFailed', { error: getErrorMessage(err) }) })
    }
  }

  async function openDetails(row: AtlasResource) {
    setDetailLoading(true)
    try {
      const includeArchived = row.status === 'archived' || Boolean(row.deleted_at)
      const fresh = await getResource(row.id, includeArchived)
      setDetail(fresh)
      setIds({ resource_id: fresh.id })
    } catch (err) {
      setNotice({ type: 'error', message: t('resources.detailFailed', { error: getErrorMessage(err) }) })
    } finally {
      setDetailLoading(false)
    }
  }

  async function handleSubmit() {
    if (!validateRequired()) return
    setSaving(true)
    setDuplicateConflict(null)
    const createPayload = formMode === 'create' ? toCreatePayload(form) : null
    try {
      if (formMode === 'create') {
        const created = await createResource(createPayload!)
        setIds({ resource_id: created.id })
        setPendingCreatePayload(null)
        const createdMacro96 = activeGranularity === 'macro' && macroPreset === 'macro96'
        setShowMacro96NextStep(createdMacro96)
        if (createdMacro96) {
          setNotice({
            type: 'success',
            message: t('resources.macroPresets.macro96CreateSuccess', { code: created.resource_code }),
          })
        } else if (activeGranularity === 'macro' && macroPreset === 'aal3') {
          setNotice({
            type: 'success',
            message: `${t('resources.createSuccess', { code: created.resource_code })} ${t('resources.macroPresets.aal3NextStep')}`,
          })
        } else {
          setNotice({ type: 'success', message: t('resources.createSuccess', { code: created.resource_code }) })
        }
      } else if (editingId) {
        const updated = await updateResource(editingId, toUpdatePayload(form))
        setDetail(updated)
        setNotice({ type: 'success', message: t('resources.updateSuccess', { code: updated.resource_code }) })
      }
      setFormOpen(false)
      refreshAll()
    } catch (err) {
      let dup = parseDuplicateResourceDetail(err)
      if (dup && formMode === 'create' && !dup.existing_resource?.id && dup.resource_code) {
        try {
          const found = await listResources({ limit: 200 })
          const row = found.items.find(r => r.resource_code === dup!.resource_code)
          if (row) {
            dup = {
              ...dup,
              existing_resource: row,
              can_restore: row.status !== 'active' || Boolean(row.deleted_at),
              can_destructive_delete: row.status !== 'active' || Boolean(row.deleted_at),
            }
          }
        } catch {
          // keep original dup detail
        }
      }
      if (dup && formMode === 'create') {
        setDuplicateConflict(dup)
        setPendingCreatePayload(createPayload)
        setNotice({ type: 'warning', message: dup.existing_resource?.status === 'active'
          ? t('resources.useExistingActiveResource')
          : t('resources.archivedResourceExists') })
        return
      }
      const key = formMode === 'create' ? 'resources.createFailed' : 'resources.updateFailed'
      setNotice({ type: 'error', message: t(key, { error: getErrorMessage(err) }) })
    } finally {
      setSaving(false)
    }
  }

  async function handleArchive() {
    if (!deleteTarget) return
    setDeleting(true)
    try {
      const archived = await deleteResource(deleteTarget.id)
      setNotice({ type: 'success', message: t('resources.archiveSuccess', { code: archived.resource_code }) })
      if (detail?.id === deleteTarget.id) setDetail(archived)
      setDeleteTarget(null)
      refreshAll()
    } catch (err) {
      setNotice({ type: 'error', message: t('resources.archiveFailed', { error: getErrorMessage(err) }) })
    } finally {
      setDeleting(false)
    }
  }

  async function handleRestore() {
    if (!restoreTarget) return
    setRestoring(true)
    try {
      const restored = await restoreResource(restoreTarget.id)
      setNotice({ type: 'success', message: t('resources.restoreSuccess', { code: restored.resource_code }) })
      setDetail(restored)
      setIds({ resource_id: restored.id })
      setRestoreTarget(null)
      setDuplicateConflict(null)
      refreshAll()
    } catch (err) {
      setNotice({ type: 'error', message: t('resources.restoreFailed', { error: getErrorMessage(err) }) })
    } finally {
      setRestoring(false)
    }
  }

  async function handleDestructiveDeleteSuccess(result: {
    resourceId: string
    resourceCode: string
    thenRecreate: boolean
  }) {
    setDestructiveDeleteTarget(null)
    setDestructiveThenRecreate(false)
    setDuplicateConflict(null)
    if (detail?.id === result.resourceId) setDetail(null)
    if (ids.resource_id === result.resourceId) clearKey('resource_id')
    refreshAll()
    setNotice({
      type: 'success',
      message: t('resources.destructiveDeleteSuccess', { code: result.resourceCode }),
    })
    if (result.thenRecreate && pendingCreatePayload) {
      try {
        const created = await createResource(pendingCreatePayload)
        setIds({ resource_id: created.id })
        setPendingCreatePayload(null)
        setFormOpen(false)
        setNotice({
          type: 'success',
          message: t('resources.createSuccess', { code: created.resource_code }),
        })
        refreshAll()
      } catch (err) {
        setNotice({ type: 'error', message: t('resources.createFailed', { error: getErrorMessage(err) }) })
      }
    }
  }

  const detailEntries = useMemo(() => {
    if (!detail) return []
    return [
      { label: t('common.id'), value: <><code className="text-mono">{detail.id}</code> <CopyButton value={detail.id} /></> },
      { label: t('resources.resourceCode'), value: detail.resource_code },
      { label: t('resources.sourceAtlas'), value: detail.source_atlas },
      { label: t('resources.sourceVersion'), value: detail.source_version },
      { label: t('resources.resourceType'), value: detail.resource_type },
      { label: t('resources.species'), value: detail.species },
      { label: t('resources.granularityLevel'), value: detail.granularity_level },
      { label: t('resources.granularityFamily'), value: detail.granularity_family },
      { label: t('resources.templateSpace'), value: detail.template_space },
      { label: t('resources.status'), value: <StatusBadge status={detail.status} /> },
      { label: t('resources.enName'), value: detail.en_name },
      { label: t('resources.cnName'), value: detail.cn_name },
      { label: t('resources.descriptionField'), value: detail.description },
      { label: t('resources.remark'), value: detail.remark },
      { label: t('resources.createdAt'), value: detail.created_at },
      { label: t('resources.updatedAt'), value: detail.updated_at },
    ]
  }, [detail, t])

  const columns = useMemo<Column<AtlasResource>[]>(() => [
    {
      key: 'id',
      header: t('common.id'),
      render: row => (
        <span className="id-copy-cell">
          <code className="text-mono">{shortId(row.id)}</code>
          <CopyButton value={row.id} label="" />
        </span>
      ),
    },
    {
      key: 'resource_code',
      header: t('resources.resourceCode'),
      render: row => (
        <span className="resource-code-cell">
          <code className="text-mono">{row.resource_code}</code>
          {activeGranularity === 'macro' && isMacro96Resource(row) && (
            <span className="resource-source-badge resource-source-badge--macro96">{t('resources.badges.macro96Pool')}</span>
          )}
          {activeGranularity === 'macro' && isAal3AtlasResource(row) && !isMacro96Resource(row) && (
            <span className="resource-source-badge resource-source-badge--aal3">{t('resources.badges.aal3Atlas')}</span>
          )}
        </span>
      ),
    },
    { key: 'source_atlas', header: t('resources.sourceAtlas'), render: row => <strong>{row.source_atlas}</strong> },
    { key: 'source_version', header: t('resources.sourceVersion') },
    { key: 'resource_type', header: t('resources.resourceType') },
    { key: 'granularity_level', header: t('resources.granularityLevel'), render: row => <StatusBadge status={row.granularity_level} /> },
    { key: 'granularity_family', header: t('resources.granularityFamily') },
    { key: 'status', header: t('resources.status'), render: row => <StatusBadge status={row.status} /> },
    { key: 'created_at', header: t('resources.createdAt'), render: row => row.created_at.slice(0, 10) },
    {
      key: 'actions',
      header: t('common.actions'),
      render: row => {
        const isArchived = row.status === 'archived' || Boolean(row.deleted_at)
        return (
          <div className="row-actions">
            <ActionButton label={t('resources.viewResource')} onClick={() => void openDetails(row)} />
            {!isArchived && (
              <ActionButton label={t('resources.editResource')} onClick={() => void openEditForm(row)} />
            )}
            {!isArchived ? (
              <ActionButton label={t('resources.archiveResource')} onClick={() => setDeleteTarget(row)} variant="danger" />
            ) : (
              <ActionButton label={t('resources.restoreResource')} onClick={() => setRestoreTarget(row)} variant="primary" />
            )}
            <ActionButton
              label={t('resources.destructiveDelete')}
              onClick={() => openDestructiveDelete(row)}
              variant="danger"
            />
            <CopyButton value={row.id} label={t('common.id')} />
          </div>
        )
      },
    },
  ], [t, activeGranularity])

  const familyFilterOptions = filterFamiliesForGranularity(activeConfig, options, false)

  return (
    <div>
      <PageHeader
        title={t('resources.title')}
        description={t('resources.subtitle')}
        readonly={false}
        actions={(
          <>
            <ActionButton label={t('common.refresh')} onClick={refreshAll} />
            <ActionButton label={t('resources.createResource')} onClick={openCreateForm} variant="primary" />
          </>
        )}
      />
      <Notice notice={notice} onClose={onClose} />

      <div className="granularity-tabs">
        {GRANULARITY_KEYS.map(key => {
          const config = RESOURCE_GRANULARITY_CONFIG[key]
          const count = granularityCounts?.[key]
          const selected = key === activeGranularity
          return (
            <button
              key={key}
              type="button"
              className={`granularity-tab${selected ? ' active' : ''}`}
              onClick={() => switchGranularity(key)}
            >
              <span className="granularity-tab-label">{t(config.labelKey)}</span>
              <span className="granularity-tab-subtitle">{t(config.subtitleKey)}</span>
              {count !== undefined && (
                <span className="granularity-count-badge">{count}</span>
              )}
            </button>
          )
        })}
      </div>

      <div className="granularity-info-card">
        <h3 className="granularity-info-title">{t(activeConfig.titleKey)}</h3>
        <p className="granularity-info-desc">{t(activeConfig.descriptionKey)}</p>
        <div className="granularity-info-meta">
          <span>{t('resources.currentGranularity')}: <strong>{activeConfig.granularity_level}</strong></span>
          <span>{t('resources.showingGranularity')}: {t(activeConfig.labelKey)}</span>
          {data && <span>{t('resources.resourceCount')}: <strong>{data.total}</strong></span>}
        </div>
      </div>

      {activeGranularity === 'macro' && (
        <MacroPresetSection
          selected={macroPreset}
          onSelect={key => applyMacroPreset(key, true)}
          presetExisting={presetExisting}
          onUseExisting={selectExistingResource}
          onRestoreOrPurge={openRestoreOrPurgeFlow}
          t={t}
        />
      )}

      {duplicateConflict && (
        <div className="resource-duplicate-actions card">
          <div className="resource-duplicate-title">
            {duplicateConflict.existing_resource?.status === 'active'
              ? t('resources.useExistingActiveResource')
              : t('resources.archivedResourceExists')}
          </div>
          <p className="resource-duplicate-body">{duplicateConflict.suggestion ?? t('resources.restoreOrPurge')}</p>
          {duplicateConflict.existing_resource && (
            <div className="resource-dependency-counts">
              <code>{duplicateConflict.existing_resource.resource_code}</code>
              {' · '}
              <StatusBadge status={duplicateConflict.existing_resource.status ?? 'archived'} />
              {duplicateConflict.dependency_counts && (
                <span className="resource-dependency-counts-detail">
                  {formatDependencyCounts(duplicateConflict.dependency_counts)}
                </span>
              )}
            </div>
          )}
          <div className="resource-duplicate-buttons">
            {duplicateConflict.existing_resource?.id && (
              <ActionButton
                label={t('resources.viewResource')}
                onClick={() => void openDetails(duplicateConflict.existing_resource as AtlasResource)}
              />
            )}
            {duplicateConflict.can_restore && duplicateConflict.existing_resource?.id && (
              <ActionButton
                label={t('resources.restoreResource')}
                onClick={() => setRestoreTarget({
                  id: duplicateConflict.existing_resource!.id,
                  resource_code: duplicateConflict.existing_resource!.resource_code ?? '',
                } as AtlasResource)}
                variant="primary"
              />
            )}
            {duplicateConflict.existing_resource?.status !== 'active' && duplicateConflict.existing_resource?.id && (
              <ActionButton
                label={t('resources.purgeThenRecreate')}
                onClick={() => openDestructiveDelete(
                  duplicateConflict.existing_resource as AtlasResource,
                  true,
                )}
                variant="danger"
              />
            )}
            {duplicateConflict.existing_resource?.status === 'active' && (
              <ActionButton
                label={t('resources.useExistingActiveResource')}
                onClick={() => selectExistingResource(duplicateConflict.existing_resource as AtlasResource)}
                variant="primary"
              />
            )}
            <ActionButton label={t('resources.createNewVersionHint')} onClick={() => {
              setDuplicateConflict(null)
              setNotice({ type: 'warning', message: t('resources.createNewVersionHint') })
            }} />
            <ActionButton label={t('common.cancel')} onClick={() => setDuplicateConflict(null)} />
          </div>
        </div>
      )}

      {showMacro96NextStep && (
        <div className="resource-preset-next-step card">
          <p>{t('resources.macroPresets.macro96NextStep')}</p>
          <ActionButton
            label={t('resources.macroPresets.goUploadBrainVolumeList')}
            onClick={() => { window.location.hash = '#/files' }}
            variant="primary"
          />
        </div>
      )}

      {formOpen && (
        <div className="card granularity-form-section">
          <ResourceForm
            form={form}
            mode={formMode}
            options={options}
            saving={saving}
            activeGranularity={activeGranularity}
            showAllFamilies={showAllFamilies}
            macroPreset={formMode === 'create' && activeGranularity === 'macro' ? macroPreset : null}
            presetFallbacks={presetFallbacks}
            onToggleAllFamilies={() => setShowAllFamilies(v => !v)}
            onChange={setForm}
            onCancel={() => setFormOpen(false)}
            onSubmit={handleSubmit}
            t={t}
          />
        </div>
      )}

      {detail && (
        <div className="card">
          <div className="settings-section-head">
            <div>
              <h2 className="card-title">{t('resources.resourceDetails')}</h2>
              <p className="page-desc">{detail.resource_code} · {detail.source_atlas}</p>
            </div>
            <div className="settings-actions">
              <ActionButton label={t('resources.editResource')} onClick={() => void openEditForm(detail)} />
              <ActionButton label={t('resources.closeDetails')} onClick={() => setDetail(null)} />
            </div>
          </div>
          {detailLoading ? <p className="text-muted">{t('common.loading')}</p> : <KeyValuePanel entries={detailEntries} />}
        </div>
      )}

      <div className="card">
        <div className="filter-bar">
          <span className="filter-label">{t('resources.statusFilter')}</span>
          <select className="filter-select" value={filters.status} onChange={e => setFilters(f => ({ ...f, status: e.target.value }))}>
            <option value="active">{t('resources.statusActiveOnly')}</option>
            <option value="inactive">{t('resources.statusInactive')}</option>
            <option value="archived">{t('resources.statusArchived')}</option>
            <option value="all">{t('resources.statusAll')}</option>
          </select>

          <span className="filter-label">{t('resources.sourceAtlas')}</span>
          <input
            className="filter-input"
            value={filters.source_atlas}
            onChange={e => setFilters(f => ({ ...f, source_atlas: e.target.value }))}
            placeholder={activeGranularity === 'macro' ? t('resources.sourceAtlasFilterHint') : activeConfig.recommended_atlases[0]}
            list={`filter-atlas-${activeGranularity}`}
          />
          <datalist id={`filter-atlas-${activeGranularity}`}>
            {activeConfig.recommended_atlases.map(a => <option key={a} value={a} />)}
          </datalist>

          <span className="filter-label">{t('resources.granularityFamily')}</span>
          <select className="filter-select" value={filters.granularity_family} onChange={e => setFilters(f => ({ ...f, granularity_family: e.target.value }))}>
            <option value="">{t('common.all')}</option>
            {familyFilterOptions.map(family => <option key={family} value={family}>{family}</option>)}
          </select>
        </div>

        <DataTable
          columns={columns}
          rows={data?.items ?? []}
          loading={loading}
          error={error}
          total={data?.total}
          getKey={row => row.id}
          getRowClassName={row => (row.status === 'archived' || row.deleted_at) ? 'resource-archived-row' : undefined}
          emptyText={t('resources.noResourcesInGranularity', { granularity: t(activeConfig.labelKey) })}
        />
      </div>

      <ConfirmDialog
        open={Boolean(deleteTarget)}
        title={t('resources.archiveResourceConfirmTitle')}
        message={deleteTarget ? t('resources.archiveResourceConfirmMessage', {
          code: deleteTarget.resource_code,
          atlas: deleteTarget.source_atlas,
        }) : undefined}
        confirmLabel={t('resources.archiveResource')}
        danger
        loading={deleting}
        onConfirm={handleArchive}
        onCancel={() => setDeleteTarget(null)}
      />

      <ConfirmDialog
        open={Boolean(restoreTarget)}
        title={t('resources.restoreResourceConfirmTitle')}
        message={t('resources.restoreResourceConfirmMessage')}
        confirmLabel={t('resources.restoreResource')}
        loading={restoring}
        onConfirm={() => void handleRestore()}
        onCancel={() => setRestoreTarget(null)}
      />

      <ResourceDestructiveDeleteModal
        open={Boolean(destructiveDeleteTarget)}
        target={destructiveDeleteTarget}
        thenRecreate={destructiveThenRecreate}
        onClose={() => {
          setDestructiveDeleteTarget(null)
          setDestructiveThenRecreate(false)
        }}
        onSuccess={result => void handleDestructiveDeleteSuccess(result)}
        onError={message => setNotice({ type: 'error', message: t('resources.destructiveDeleteFailed', { error: message }) })}
      />
    </div>
  )
}
