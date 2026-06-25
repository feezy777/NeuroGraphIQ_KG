import { useState, useCallback, useMemo } from 'react'
import { PageHeader } from '../components/PageHeader'
import { DataTable, type Column } from '../components/DataTable'
import { StatusBadge } from '../components/StatusBadge'
import { ActionButton } from '../components/ActionButton'
import { ConfirmDialog } from '../components/ConfirmDialog'
import { Notice, type NoticeState } from '../components/Notice'
import { useData } from '../hooks/useData'
import { fetchPromotionRecords, promoteCandidate, type PromotionRecord, type PromoteResult } from '../api/endpoints'
import { ApiError } from '../api/client'
import { readSessionIds, useSessionIds } from '../hooks/useSessionIds'
import { useI18n } from '../i18n-context'

export function PromotionsPage() {
  const { t } = useI18n()
  const [statusFilter, setStatusFilter] = useState('')
  const [notice, setNotice] = useState<NoticeState | null>(null)
  const onClose = useCallback(() => setNotice(null), [])
  const [tick, setTick] = useState(0)
  const reload = () => setTick(t => t + 1)
  const { setIds } = useSessionIds()

  const [candidateId, setCandidateId] = useState(readSessionIds().candidate_id ?? '')
  const [promotedBy, setPromotedBy] = useState('local_user')
  const [reason, setReason] = useState('')
  const [promoting, setPromoting] = useState(false)
  const [showConfirm, setShowConfirm] = useState(false)
  const [promoteResult, setPromoteResult] = useState<PromoteResult | null>(null)

  const { data, loading, error } = useData(
    () => fetchPromotionRecords({ status: statusFilter || undefined, limit: 100 }),
    [statusFilter, tick],
  )

  const columns: Column<PromotionRecord>[] = useMemo(() => [
    { key: 'candidate_id', header: t('common.candidateId'), render: r => <code className="text-mono" style={{ fontSize: 11 }}>{r.candidate_id.slice(0, 10)}…</code> },
    { key: 'final_region_id', header: t('common.finalRegionId'), render: r => <code className="text-mono" style={{ fontSize: 11 }}>{(r.final_region_id ?? '—').slice(0, 10)}{r.final_region_id ? '…' : ''}</code> },
    { key: 'status', header: t('common.status'), render: r => <StatusBadge status={r.status} /> },
    { key: 'promoted_by', header: t('common.operator') },
    { key: 'reason', header: t('common.reason'), render: r => <span title={r.reason ?? ''}>{(r.reason ?? '').slice(0, 40)}</span> },
    { key: 'created_at', header: t('finalRegions.time'), render: r => r.created_at.slice(0, 16).replace('T', ' ') },
  ], [t])

  function openConfirm() {
    if (!candidateId.trim()) { setNotice({ type: 'error', message: t('promotions.needCandidateId') }); return }
    if (!promotedBy.trim()) { setNotice({ type: 'error', message: t('promotions.needPromotedBy') }); return }
    setShowConfirm(true)
  }

  async function doPromote() {
    setPromoting(true)
    setShowConfirm(false)
    try {
      const res = await promoteCandidate(candidateId.trim(), { promoted_by: promotedBy, reason: reason || undefined })
      setPromoteResult(res)
      setIds({ final_region_id: res.final_region.id, candidate_id: candidateId.trim() })
      setNotice({ type: 'success', message: t('promotions.promoteSuccess') })
      reload()
    } catch (e) {
      setNotice({ type: 'error', message: e instanceof ApiError ? e.message : String(e) })
    } finally {
      setPromoting(false)
    }
  }

  return (
    <div>
      <PageHeader title={t('promotions.title')} description={t('promotions.description')} readonly={false} />
      <Notice notice={notice} onClose={onClose} />

      <div className="card">
        <h3 style={{ fontSize: 13, fontWeight: 600, marginBottom: 6 }}>{t('promotions.panelTitle')}</h3>
        <p style={{ fontSize: 12, color: '#cf1322', marginBottom: 12, fontWeight: 500 }}>
          {t('promotions.panelWarning')}
        </p>
        <div className="form-row">
          <div className="form-field">
            <label className="form-label">{t('common.candidateId')} *</label>
            <input className="form-input" style={{ width: 300 }} placeholder={t('promotions.candidateIdPlaceholder')}
              value={candidateId} onChange={e => setCandidateId(e.target.value)} />
          </div>
          <div className="form-field">
            <label className="form-label">{t('common.promotedBy')} *</label>
            <input className="form-input" style={{ width: 140 }} value={promotedBy}
              onChange={e => setPromotedBy(e.target.value)} />
          </div>
          <div className="form-field" style={{ flex: 1 }}>
            <label className="form-label">{t('common.optionalReason')}</label>
            <input className="form-input" value={reason} onChange={e => setReason(e.target.value)} placeholder={t('promotions.promoteReason')} />
          </div>
          <ActionButton label={t('promotions.promoteBtn')} variant="danger" onClick={openConfirm} loading={promoting} />
        </div>
        {promoteResult && (
          <div className="result-box" style={{ marginTop: 12 }}>
            <strong>{t('promotions.promoteResult')}</strong>
            <div style={{ marginTop: 4, fontSize: 12 }}>
              <div>{t('common.finalRegionId')}: <code className="text-mono">{promoteResult.final_region.id}</code></div>
              <div>{t('promotions.candidatePromoted')}: <StatusBadge status="promoted_to_final" /></div>
              <div style={{ marginTop: 4 }}>{t('promotions.viewFinalRegions')}</div>
            </div>
          </div>
        )}
      </div>

      <div className="card">
        <div className="filter-bar">
          <span className="filter-label">{t('common.status')}：</span>
          <select className="filter-select" value={statusFilter} onChange={e => setStatusFilter(e.target.value)}>
            <option value="">{t('common.all')}</option>
            {['promoted','reverted','superseded'].map(s => <option key={s} value={s}>{s}</option>)}
          </select>
          <button className="btn" style={{ marginLeft: 8 }} onClick={reload}>{t('common.refresh')}</button>
        </div>
        <DataTable columns={columns} rows={data?.items ?? []} loading={loading} error={error}
          total={data?.total} getKey={r => r.id} emptyText={t('promotions.empty')} />
      </div>

      <ConfirmDialog
        open={showConfirm}
        title={t('promotions.confirmTitle')}
        danger
        confirmLabel={t('promotions.confirmBtn')}
        onConfirm={doPromote}
        onCancel={() => setShowConfirm(false)}
        loading={promoting}
      >
        <div className="dialog-msg" style={{ color: '#8b0000' }}>
          {t('promotions.confirmBody')}
        </div>
        <div style={{ fontSize: 13, marginBottom: 10 }}>
          {t('common.candidateId')}: <code className="text-mono">{candidateId}</code><br />
          {t('common.promotedBy')}: <strong>{promotedBy}</strong>
        </div>
      </ConfirmDialog>
    </div>
  )
}
