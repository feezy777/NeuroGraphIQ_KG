import { useCallback, useEffect, useState } from 'react'
import { AlertTriangle, CheckCircle2, KeyRound } from 'lucide-react'
import { PageHeader } from '../components/PageHeader'
import { Notice, type NoticeState } from '../components/Notice'
import { LoadingState, ErrorState } from '../components/States'
import { ActionButton } from '../components/ActionButton'
import { KeyValuePanel } from '../components/KeyValuePanel'
import {
  getRuntimeSettings,
  getSettingsOptions,
  testDeepSeekConnection,
  updateRuntimeSettings,
  type RuntimeSettings,
  type SettingsOptions,
} from '../api/endpoints'
import { ApiError } from '../api/client'
import { type Language } from '../i18n'
import { useI18n } from '../i18n-context'

type TabKey = 'language' | 'api' | 'basic'

interface FormState {
  enabled: boolean
  baseUrl: string
  defaultModel: string
  apiKey: string
  explicitClearApiKey: boolean
  timeoutSeconds: number
  maxBatchSize: number
  defaultPageSize: number
  maxPageSize: number
  showDebugPanels: boolean
}

function toFormState(runtime: RuntimeSettings): FormState {
  const deepseek = runtime.api_providers.deepseek
  return {
    enabled: deepseek.enabled,
    baseUrl: deepseek.base_url,
    defaultModel: deepseek.default_model,
    apiKey: '',
    explicitClearApiKey: false,
    timeoutSeconds: deepseek.timeout_seconds,
    maxBatchSize: deepseek.max_batch_size,
    defaultPageSize: runtime.basic.default_page_size,
    maxPageSize: runtime.basic.max_page_size,
    showDebugPanels: runtime.basic.show_debug_panels,
  }
}

export function SettingsPage() {
  const { language, setLanguage, t } = useI18n()
  const [tab, setTab] = useState<TabKey>('language')
  const [options, setOptions] = useState<SettingsOptions | null>(null)
  const [runtime, setRuntime] = useState<RuntimeSettings | null>(null)
  const [form, setForm] = useState<FormState | null>(null)
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState<string | null>(null)
  const [saving, setSaving] = useState(false)
  const [testing, setTesting] = useState(false)
  const [notice, setNotice] = useState<NoticeState | null>(null)
  const [testResult, setTestResult] = useState<string | null>(null)
  const onClose = useCallback(() => setNotice(null), [])

  useEffect(() => {
    let cancelled = false
    setLoading(true)
    Promise.all([getSettingsOptions(), getRuntimeSettings()])
      .then(([opts, rt]) => {
        if (cancelled) return
        setOptions(opts)
        setRuntime(rt)
        setForm(toFormState(rt))
        setError(null)
      })
      .catch((e: Error) => {
        if (!cancelled) setError(e.message)
      })
      .finally(() => {
        if (!cancelled) setLoading(false)
      })
    return () => { cancelled = true }
  }, [])

  const updateForm = (patch: Partial<FormState>) => {
    setForm(prev => prev ? { ...prev, ...patch } : prev)
  }

  const save = async () => {
    if (!form) return
    setSaving(true)
    setNotice(null)
    setTestResult(null)
    try {
      const updated = await updateRuntimeSettings({
        api_providers: {
          deepseek: {
            enabled: form.enabled,
            base_url: form.baseUrl,
            default_model: form.defaultModel,
            api_key: form.apiKey,
            explicit_clear_api_key: form.explicitClearApiKey,
            timeout_seconds: form.timeoutSeconds,
            max_batch_size: form.maxBatchSize,
          },
        },
        basic: {
          default_page_size: form.defaultPageSize,
          max_page_size: form.maxPageSize,
          show_debug_panels: form.showDebugPanels,
        },
      })
      setRuntime(updated)
      setForm({ ...toFormState(updated), apiKey: '' })
      setNotice({ type: 'success', message: t('settings.saved') })
    } catch (e) {
      const msg = e instanceof ApiError ? e.message : String(e)
      setNotice({ type: 'error', message: t('settings.saveFailed', { error: msg }) })
    } finally {
      setSaving(false)
    }
  }

  const testConnection = async () => {
    if (!form) return
    setTesting(true)
    setNotice(null)
    setTestResult(null)
    try {
      const res = await testDeepSeekConnection({
        base_url: form.baseUrl,
        default_model: form.defaultModel,
        api_key: form.apiKey || undefined,
      })
      if (res.ok) {
        setTestResult(`OK · ${res.model ?? form.defaultModel} · ${res.latency_ms ?? '—'} ms`)
        setNotice({ type: 'success', message: t('settings.testOk') })
      } else {
        setTestResult(res.error_message ?? t('settings.testFailed'))
        setNotice({ type: 'error', message: res.error_message ?? t('settings.testFailed') })
      }
    } catch (e) {
      const msg = e instanceof ApiError ? e.message : String(e)
      setNotice({ type: 'error', message: t('settings.testError', { error: msg }) })
    } finally {
      setTesting(false)
    }
  }

  const tabs: Array<{ key: TabKey; label: string }> = [
    { key: 'language', label: t('settings.language') },
    { key: 'api', label: t('settings.apiProviders') },
    { key: 'basic', label: t('settings.basic') },
  ]

  return (
    <div>
      <PageHeader
        title={t('settings.title')}
        description={t('settings.description')}
        readonly={false}
        actions={
          <ActionButton
            label={saving ? t('settings.saving') : t('settings.save')}
            onClick={save}
            loading={saving}
            disabled={!form}
            variant="primary"
          />
        }
      />
      <Notice notice={notice} onClose={onClose} />

      <div className="settings-boundary">
        <AlertTriangle size={16} />
        <span>{t('settings.boundary')}</span>
      </div>

      {loading && <LoadingState text={t('settings.loading')} />}
      {error && <ErrorState error={error} />}

      {!loading && !error && form && runtime && (
        <div className="card">
          <div className="tabs">
            {tabs.map(item => (
              <button
                key={item.key}
                className={`tab-btn${tab === item.key ? ' active' : ''}`}
                onClick={() => setTab(item.key)}
              >
                {item.label}
              </button>
            ))}
          </div>

          {tab === 'language' && (
            <section className="settings-section">
              <div className="card-title">{t('settings.language')}</div>
              <div className="form-row">
                <label className="form-field settings-field">
                  <span className="form-label">{t('settings.language')}</span>
                  <select
                    className="form-select"
                    value={language}
                    onChange={e => setLanguage(e.target.value as Language)}
                  >
                    {(options?.languages ?? [
                      { value: 'zh-CN', label: '中文' },
                      { value: 'en-US', label: 'English' },
                    ]).map(item => (
                      <option key={item.value} value={item.value}>{item.label}</option>
                    ))}
                  </select>
                  <span className="form-hint">{t('settings.languageHint')}</span>
                </label>
              </div>
            </section>
          )}

          {tab === 'api' && (
            <section className="settings-section">
              <div className="settings-section-head">
                <div>
                  <div className="card-title">{t('settings.deepseekTitle')}</div>
                  <p className="page-desc">{t('settings.deepseekDesc')}</p>
                </div>
                <KeyRound size={20} />
              </div>

              <KeyValuePanel
                entries={[
                  {
                    label: t('settings.apiKeyStatus'),
                    value: runtime.api_providers.deepseek.api_key_configured
                      ? (runtime.api_providers.deepseek.api_key_masked ?? t('common.configured'))
                      : t('common.notConfigured'),
                  },
                  { label: t('common.provider'), value: 'deepseek' },
                  { label: t('common.model'), value: runtime.api_providers.deepseek.default_model },
                ]}
              />

              <div className="settings-form-grid">
                <label className="form-field">
                  <span className="form-label">{t('common.enabled')}</span>
                  <select
                    className="form-select"
                    value={form.enabled ? 'true' : 'false'}
                    onChange={e => updateForm({ enabled: e.target.value === 'true' })}
                  >
                    <option value="true">true</option>
                    <option value="false">false</option>
                  </select>
                </label>
                <label className="form-field">
                  <span className="form-label">{t('settings.baseUrl')}</span>
                  <input className="form-input" value={form.baseUrl} onChange={e => updateForm({ baseUrl: e.target.value })} />
                </label>
                <label className="form-field">
                  <span className="form-label">{t('common.model')}</span>
                  <select className="form-select" value={form.defaultModel} onChange={e => updateForm({ defaultModel: e.target.value })}>
                    {(options?.default_models.deepseek ?? ['deepseek-chat', 'deepseek-reasoner']).map(model => (
                      <option key={model} value={model}>{model}</option>
                    ))}
                  </select>
                </label>
                <label className="form-field">
                  <span className="form-label">{t('settings.apiKey')}</span>
                  <input
                    className="form-input"
                    type="password"
                    value={form.apiKey}
                    placeholder={
                      runtime.api_providers.deepseek.api_key_configured
                        ? t('settings.apiKeyConfiguredPlaceholder', { masked: runtime.api_providers.deepseek.api_key_masked ?? '' })
                        : t('settings.apiKeyPlaceholder')
                    }
                    onChange={e => updateForm({ apiKey: e.target.value, explicitClearApiKey: false })}
                  />
                </label>
                <label className="form-field">
                  <span className="form-label">{t('settings.timeoutSeconds')}</span>
                  <input className="form-input" type="number" min={5} max={120} value={form.timeoutSeconds} onChange={e => updateForm({ timeoutSeconds: Number(e.target.value) })} />
                </label>
                <label className="form-field">
                  <span className="form-label">{t('settings.maxBatchSize')}</span>
                  <input className="form-input" type="number" min={1} max={20} value={form.maxBatchSize} onChange={e => updateForm({ maxBatchSize: Number(e.target.value) })} />
                </label>
              </div>

              <label className="settings-checkbox">
                <input
                  type="checkbox"
                  checked={form.explicitClearApiKey}
                  onChange={e => updateForm({ explicitClearApiKey: e.target.checked, apiKey: '' })}
                />
                {t('settings.clearApiKeyOnSave')}
              </label>

              <div className="settings-actions">
                <ActionButton
                  label={testing ? t('settings.testing') : t('settings.test')}
                  onClick={testConnection}
                  loading={testing}
                  variant="default"
                />
                {testResult && (
                  <span className={testResult.startsWith('OK') ? 'settings-test-ok' : 'settings-test-error'}>
                    {testResult.startsWith('OK') && <CheckCircle2 size={13} />}
                    {testResult}
                  </span>
                )}
              </div>
            </section>
          )}

          {tab === 'basic' && (
            <section className="settings-section">
              <div className="card-title">{t('settings.basic')}</div>
              <div className="settings-form-grid">
                <label className="form-field">
                  <span className="form-label">{t('settings.defaultPageSize')}</span>
                  <input className="form-input" type="number" min={10} max={200} value={form.defaultPageSize} onChange={e => updateForm({ defaultPageSize: Number(e.target.value) })} />
                </label>
                <label className="form-field">
                  <span className="form-label">{t('settings.maxPageSize')}</span>
                  <input className="form-input" type="number" min={50} max={500} value={form.maxPageSize} onChange={e => updateForm({ maxPageSize: Number(e.target.value) })} />
                </label>
                <label className="settings-checkbox">
                  <input
                    type="checkbox"
                    checked={form.showDebugPanels}
                    onChange={e => updateForm({ showDebugPanels: e.target.checked })}
                  />
                  {t('settings.showDebugPanels')}
                </label>
              </div>
            </section>
          )}
        </div>
      )}
    </div>
  )
}
