import { useCallback, useEffect, useMemo, useState } from 'react'
import { useI18n } from '../../i18n-context'
import { ApiError } from '../../api/client'
import {
  getFieldCompletionPromptTemplates,
  type FieldCompletionPromptTemplate,
} from '../../api/endpoints'

export type PromptOverrides = Record<string, string>

interface TemplatePlanItem {
  target_type?: string
  field_name?: string
  prompt_key?: string
  display_name?: string
  target_count?: number
  uses_deepseek?: boolean
}

interface DeterministicPlanItem {
  target_type?: string
  field_name?: string
  resolver?: string
  uses_deepseek?: boolean
}

interface Props {
  modeLabel: string
  templatePlan?: TemplatePlanItem[]
  estimatedModelCalls?: number
  promptOverrides: PromptOverrides
  onPromptOverridesChange: (next: PromptOverrides) => void
  dryRunPreview?: Record<string, unknown> | null
}

export function PromptWorkbenchSection({
  modeLabel,
  templatePlan = [],
  estimatedModelCalls,
  promptOverrides,
  onPromptOverridesChange,
  dryRunPreview,
}: Props) {
  const { t } = useI18n()
  const [open, setOpen] = useState(false)
  const [templates, setTemplates] = useState<FieldCompletionPromptTemplate[]>([])
  const [selectedKey, setSelectedKey] = useState('circuit_field_completion_name_cn_v1')
  const [editorText, setEditorText] = useState('')
  const [loadError, setLoadError] = useState<string | null>(null)

  useEffect(() => {
    if (!open || templates.length > 0) return
    void getFieldCompletionPromptTemplates()
      .then(res => {
        setTemplates(res.items ?? [])
        if (res.items?.length) setSelectedKey(res.items[0].key)
      })
      .catch(err => {
        if (err instanceof ApiError && err.status === 404) {
          setLoadError(t('dataCenter.promptTemplatesApiUnavailable'))
        } else {
          setLoadError(err instanceof Error ? err.message : String(err))
        }
      })
  }, [open, templates.length])

  const templateByKey = useMemo(() => {
    const map = new Map<string, FieldCompletionPromptTemplate>()
    for (const item of templates) map.set(item.key, item)
    return map
  }, [templates])

  const effectivePlan = useMemo(() => {
    const fromPreview = dryRunPreview?.template_plan
    if (Array.isArray(fromPreview) && fromPreview.length > 0) {
      return fromPreview as TemplatePlanItem[]
    }
    return templatePlan
  }, [dryRunPreview, templatePlan])

  const estimatedCalls = useMemo(() => {
    if (typeof dryRunPreview?.estimated_model_calls === 'number') {
      return dryRunPreview.estimated_model_calls
    }
    return estimatedModelCalls
  }, [dryRunPreview, estimatedModelCalls])

  const estimatedInputTokens = useMemo(() => {
    if (typeof dryRunPreview?.estimated_input_tokens === 'number') {
      return dryRunPreview.estimated_input_tokens
    }
    return undefined
  }, [dryRunPreview])

  const deterministicPlan = useMemo(() => {
    const raw = dryRunPreview?.deterministic_plan
    return Array.isArray(raw) ? (raw as DeterministicPlanItem[]) : []
  }, [dryRunPreview])

  const deterministicFieldNames = useMemo(() => {
    const fromPreview = dryRunPreview?.deterministic_fields
    if (Array.isArray(fromPreview) && fromPreview.length > 0) {
      return fromPreview.map(String)
    }
    const names = new Set<string>()
    for (const row of deterministicPlan) {
      if (row.field_name) names.add(row.field_name)
    }
    return [...names]
  }, [dryRunPreview, deterministicPlan])

  const llmFieldNames = useMemo(() => {
    const fromPreview = dryRunPreview?.llm_fields
    if (Array.isArray(fromPreview) && fromPreview.length > 0) {
      return fromPreview.map(String)
    }
    const names = new Set<string>()
    for (const row of effectivePlan) {
      if (row.field_name) names.add(row.field_name)
    }
    return [...names]
  }, [dryRunPreview, effectivePlan])

  const compactContextEnabled = dryRunPreview?.compact_context_enabled === true

  useEffect(() => {
    const tpl = templateByKey.get(selectedKey)
    if (!tpl) return
    setEditorText(promptOverrides[selectedKey] ?? tpl.template)
  }, [selectedKey, templateByKey, promptOverrides])

  const applyOverride = useCallback(() => {
    onPromptOverridesChange({ ...promptOverrides, [selectedKey]: editorText })
  }, [editorText, onPromptOverridesChange, promptOverrides, selectedKey])

  const resetDefault = useCallback(() => {
    const tpl = templateByKey.get(selectedKey)
    if (!tpl) return
    setEditorText(tpl.template)
    const next = { ...promptOverrides }
    delete next[selectedKey]
    onPromptOverridesChange(next)
  }, [onPromptOverridesChange, promptOverrides, selectedKey, templateByKey])

  return (
    <details
      className="data-center-prompt-workbench"
      open={open}
      onToggle={e => setOpen((e.target as HTMLDetailsElement).open)}
    >
      <summary>{t('dataCenter.promptWorkbench')}</summary>
      <p className="data-center-field-completion-meta">
        {t('dataCenter.promptWorkbenchMode')}: {modeLabel}
      </p>
      {loadError && <p className="data-center-bundle-warning">{loadError}</p>}
      <p className="data-center-field-completion-meta">
        {t('dataCenter.tokenEfficientCompletionHint')}
      </p>
      {(deterministicFieldNames.length > 0 || llmFieldNames.length > 0) && (
        <div className="data-center-prompt-plan">
          <h5>{t('dataCenter.deterministicFieldsSection')}</h5>
          <p className="data-center-field-completion-meta">
            {deterministicFieldNames.length > 0
              ? deterministicFieldNames.join(', ')
              : t('dataCenter.none')}
          </p>
          <p className="data-center-field-completion-meta">{t('dataCenter.canonicalRegionResolverHint')}</p>
          <h5>{t('dataCenter.llmFieldsSection')}</h5>
          <p className="data-center-field-completion-meta">
            {llmFieldNames.length > 0 ? llmFieldNames.join(', ') : t('dataCenter.none')}
          </p>
          {compactContextEnabled && (
            <p className="data-center-field-completion-meta">{t('dataCenter.compactContextEnabled')}</p>
          )}
        </div>
      )}
      {effectivePlan.length > 0 && (
        <div className="data-center-prompt-plan">
          <h5>{t('dataCenter.promptPlan')}</h5>
          {estimatedCalls != null && (
            <p className="data-center-field-completion-meta">
              {t('dataCenter.estimatedModelCalls', { count: String(estimatedCalls) })}
            </p>
          )}
          {estimatedInputTokens != null && (
            <p className="data-center-field-completion-meta">
              {t('dataCenter.estimatedInputTokens', { count: String(estimatedInputTokens) })}
            </p>
          )}
          <table className="data-center-field-completion-items">
            <thead>
              <tr>
                <th>target_type</th>
                <th>field_name</th>
                <th>prompt_key</th>
                <th>resolver / LLM</th>
              </tr>
            </thead>
            <tbody>
              {deterministicPlan.slice(0, 20).map((row, idx) => (
                <tr key={`det-${row.field_name}-${idx}`}>
                  <td>{row.target_type ?? '—'}</td>
                  <td>{row.field_name ?? '—'}</td>
                  <td><code>{row.resolver ?? 'deterministic'}</code></td>
                  <td>{t('dataCenter.resolverDb')}</td>
                </tr>
              ))}
              {effectivePlan.slice(0, 30).map((row, idx) => {
                const tpl = row.prompt_key ? templateByKey.get(row.prompt_key) : undefined
                const displayLabel = tpl?.display_name ?? row.display_name ?? row.prompt_key ?? '—'
                return (
                  <tr key={`${row.prompt_key}-${row.field_name}-${idx}`}>
                    <td>{row.target_type ?? '—'}</td>
                    <td>{row.field_name ?? '—'}</td>
                    <td title={row.prompt_key ?? undefined}><code>{displayLabel}</code></td>
                    <td>{row.uses_deepseek === false ? t('dataCenter.resolverDb') : 'DeepSeek'}</td>
                  </tr>
                )
              })}
            </tbody>
          </table>
        </div>
      )}
      <div className="data-center-prompt-editor">
        <label>
          {t('dataCenter.promptKeySelect')}
          <select value={selectedKey} onChange={e => setSelectedKey(e.target.value)}>
            {templates.map(tpl => (
              <option key={tpl.key} value={tpl.key}>
                {tpl.display_name ? `${tpl.display_name} [${tpl.key}]` : tpl.key}
              </option>
            ))}
          </select>
        </label>
        <textarea
          className="data-center-prompt-textarea"
          rows={12}
          value={editorText}
          onChange={e => setEditorText(e.target.value)}
        />
        <div className="data-center-field-completion-actions">
          <button type="button" className="btn" onClick={resetDefault}>
            {t('dataCenter.promptRestoreDefault')}
          </button>
          <button type="button" className="btn btn-primary" onClick={applyOverride}>
            {t('dataCenter.promptApplyOverride')}
          </button>
        </div>
        {Object.keys(promptOverrides).length > 0 && (
          <p className="data-center-field-completion-meta">
            {t('dataCenter.promptOverridesActive', { count: String(Object.keys(promptOverrides).length) })}
          </p>
        )}
      </div>
    </details>
  )
}
