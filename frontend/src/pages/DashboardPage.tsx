import { useCallback, useEffect, useMemo, useState } from 'react'
import { PageHeader } from '../components/PageHeader'
import { StatusBadge } from '../components/StatusBadge'
import { ActionButton } from '../components/ActionButton'
import { ConfirmDialog } from '../components/ConfirmDialog'
import { Notice, type NoticeState } from '../components/Notice'
import { ErrorState } from '../components/States'
import {
  fetchCandidateStatusSummary,
  fetchFinalRegionSummary,
  fetchHealth,
  fetchImportBatches,
  getDatabaseStatus,
  listDatabases,
  listResources,
  switchDatabase,
  type DatabaseListItem,
  type DatabaseSchemaStatus,
  type HealthResponse,
} from '../api/endpoints'
import { ApiError } from '../api/client'
import { SessionIdsPanel } from '../components/SessionIdsPanel'
import { useI18n } from '../i18n-context'

function schemaStatusLabel(t: (k: string) => string, status: DatabaseSchemaStatus): string {
  const key = `dashboard.schemaStatus.${status}`
  const translated = t(key)
  return translated === key ? status : translated
}

export function DashboardPage() {
  const { t } = useI18n()
  const [health, setHealth] = useState<HealthResponse | null>(null)
  const [healthErr, setHealthErr] = useState<string | null>(null)
  const [dbList, setDbList] = useState<DatabaseListItem[]>([])
  const [dbHost, setDbHost] = useState('')
  const [currentDb, setCurrentDb] = useState('')
  const [dbLoading, setDbLoading] = useState(false)
  const [selectedDb, setSelectedDb] = useState('')
  const [switchConfirm, setSwitchConfirm] = useState<string | null>(null)
  const [switching, setSwitching] = useState(false)
  const [notice, setNotice] = useState<NoticeState | null>(null)
  const [sessionOpen, setSessionOpen] = useState(false)
  const [stats, setStats] = useState({
    finalRegions: null as number | null,
    resources: null as number | null,
    batches: null as number | null,
    candidates: null as number | null,
  })

  const quickLinks = useMemo(
    (): [string, string][] => [
      ['#/resources', t('nav.resources')],
      ['#/files', t('nav.files')],
      ['#/import-pipeline', t('nav.importPipeline')],
      ['#/final-regions', t('nav.finalRegions')],
      ['#/settings', t('nav.settings')],
    ],
    [t],
  )

  const loadDashboard = useCallback(async () => {
    setDbLoading(true)
    try {
      const [h, dbStatus, dbs, finalSum, resources, batches, candidates] = await Promise.all([
        fetchHealth(),
        getDatabaseStatus(),
        listDatabases(),
        fetchFinalRegionSummary().catch(() => null),
        listResources({ limit: 1 }).catch(() => null),
        fetchImportBatches({ limit: 1 }).catch(() => null),
        fetchCandidateStatusSummary().catch(() => null),
      ])
      setHealth(h)
      setHealthErr(null)
      setCurrentDb(dbStatus.current_database)
      setDbHost(`${dbStatus.host}:${dbStatus.port}`)
      setDbList(dbs.items)
      setSelectedDb(dbStatus.current_database)

      setStats({
        finalRegions: typeof finalSum?.total === 'number' ? finalSum.total : null,
        resources: resources?.total ?? null,
        batches: batches?.total ?? null,
        candidates: candidates?.total ?? null,
      })
    } catch (e) {
      const msg = e instanceof ApiError || e instanceof Error ? e.message : String(e)
      setHealthErr(msg)
    } finally {
      setDbLoading(false)
    }
  }, [])

  useEffect(() => {
    void loadDashboard()
  }, [loadDashboard])

  async function handleSwitchConfirm() {
    if (!switchConfirm) return
    setSwitching(true)
    try {
      const res = await switchDatabase(switchConfirm)
      setNotice({ type: 'success', message: t('dashboard.switchSuccess', { db: res.current_database }) })
      setSwitchConfirm(null)
      await loadDashboard()
    } catch (e) {
      setNotice({
        type: 'error',
        message: t('dashboard.switchFailed', { error: e instanceof ApiError ? e.message : String(e) }),
      })
    } finally {
      setSwitching(false)
    }
  }

  const selectedDbItem = dbList.find(d => d.name === selectedDb)
  const canSwitch = selectedDbItem?.schema_status === 'mvp1_ready' && selectedDb !== currentDb

  return (
    <div>
      <PageHeader
        title={t('dashboard.title')}
        description={t('dashboard.description')}
        readonly={false}
        actions={<ActionButton label={t('common.refresh')} onClick={() => void loadDashboard()} loading={dbLoading} />}
      />
      <Notice notice={notice} onClose={() => setNotice(null)} />

      <div className="dash-grid">
        <div className="card">
          <div className="card-title">{t('dashboard.backendStatus')}</div>
          {healthErr ? (
            <ErrorState error={t('common.backendUnreachable', { error: healthErr })} />
          ) : health ? (
            <>
              <div style={{ display: 'flex', alignItems: 'center', gap: 8, marginBottom: 6 }}>
                <span className={`dash-status-dot${health.status === 'ok' ? ' online' : ' degraded'}`} />
                <strong style={{ fontSize: 13 }}>{health.status === 'ok' ? t('common.online') : t('dashboard.degraded')}</strong>
                <StatusBadge status={health.status} />
              </div>
              <div className="dash-meta">{t('common.version')}：{health.version}</div>
              <div className="dash-meta">
                {t('common.backend')}：
                <a href="http://127.0.0.1:8002/api/docs" target="_blank" rel="noreferrer" className="dash-link">{t('common.swaggerDocs')}</a>
              </div>
            </>
          ) : (
            <div className="dash-meta">{t('common.connecting')}</div>
          )}
        </div>

        <div className="card">
          <div className="card-title">{t('dashboard.currentDatabase')}</div>
          {currentDb ? (
            <>
              <div className="stat-val" style={{ fontSize: 18 }}>{currentDb}</div>
              <div className="dash-meta">{dbHost}</div>
              {health?.database && (
                <div style={{ marginTop: 8 }}>
                  <StatusBadge status={health.database.schema_status} />
                  {!health.database.connected && (
                    <span className="dash-meta" style={{ marginLeft: 8 }}>{t('dashboard.dbDisconnected')}</span>
                  )}
                </div>
              )}
            </>
          ) : (
            <div className="dash-meta">—</div>
          )}
        </div>
      </div>

      <div className="card dash-db-switch-card">
        <div className="card-title">{t('dashboard.databaseSwitch')}</div>
        <p className="dash-meta" style={{ marginBottom: 10 }}>{t('dashboard.databaseSwitchHint')}</p>
        <div className="dash-db-switch-row">
          <select
            className="filter-select dash-db-select"
            value={selectedDb}
            onChange={e => setSelectedDb(e.target.value)}
            disabled={dbLoading || dbList.length === 0}
          >
            {dbList.map(db => (
              <option key={db.name} value={db.name}>
                {db.name} ({schemaStatusLabel(t, db.schema_status)}){db.is_current ? ' *' : ''}
              </option>
            ))}
          </select>
          <ActionButton
            label={t('dashboard.switchDatabase')}
            variant="primary"
            disabled={!canSwitch}
            onClick={() => setSwitchConfirm(selectedDb)}
          />
        </div>
        {selectedDbItem && (
          <div className="dash-db-detail">
            <StatusBadge status={selectedDbItem.schema_status} />
            {selectedDbItem.notes.length > 0 && (
              <span className="dash-meta">{selectedDbItem.notes.join('; ')}</span>
            )}
            {selectedDbItem.schema_status !== 'mvp1_ready' && (
              <div className="dash-db-warning">{t('dashboard.onlyMvp1Switch')}</div>
            )}
          </div>
        )}
      </div>

      <div className="dash-grid dash-stats-grid">
        <div className="card dash-stat-card">
          <div className="card-title">{t('dashboard.statFinalRegions')}</div>
          <div className="stat-val">{stats.finalRegions ?? '—'}</div>
        </div>
        <div className="card dash-stat-card">
          <div className="card-title">{t('dashboard.statResources')}</div>
          <div className="stat-val">{stats.resources ?? '—'}</div>
        </div>
        <div className="card dash-stat-card">
          <div className="card-title">{t('dashboard.statImportBatches')}</div>
          <div className="stat-val">{stats.batches ?? '—'}</div>
        </div>
        <div className="card dash-stat-card">
          <div className="card-title">{t('dashboard.statCandidates')}</div>
          <div className="stat-val">{stats.candidates ?? '—'}</div>
        </div>
      </div>

      <details className="card dash-session-collapse" open={sessionOpen} onToggle={e => setSessionOpen((e.target as HTMLDetailsElement).open)}>
        <summary className="dash-session-summary">{t('dashboard.sessionIdsToggle')}</summary>
        <SessionIdsPanel />
      </details>

      <div className="card">
        <div className="card-title">{t('dashboard.quickLinks')}</div>
        <div className="quick-links">
          {quickLinks.map(([href, label]) => (
            <a key={href} href={href} className="btn">{label}</a>
          ))}
        </div>
      </div>

      <ConfirmDialog
        open={!!switchConfirm}
        title={t('dashboard.switchConfirmTitle')}
        message={switchConfirm ? t('dashboard.switchConfirmMessage', { db: switchConfirm }) : undefined}
        confirmLabel={t('dashboard.switchDatabase')}
        loading={switching}
        onConfirm={() => void handleSwitchConfirm()}
        onCancel={() => setSwitchConfirm(null)}
      />
    </div>
  )
}
