import { useState, useCallback, useMemo, useEffect } from 'react'
import { PageHeader } from '../components/PageHeader'
import { DataTable, type Column } from '../components/DataTable'
import { StatusBadge } from '../components/StatusBadge'
import { ActionButton } from '../components/ActionButton'
import { ConfirmDialog } from '../components/ConfirmDialog'
import { Notice, type NoticeState } from '../components/Notice'
import { PipelineFilterBanner } from '../components/pipeline/PipelineFilterBanner'
import { useData } from '../hooks/useData'
import {
  fetchPendingReviews, fetchReviewRecords,
  submitReview, reviewDecision,
  type PendingCandidate, type CandidateReviewRecord,
} from '../api/endpoints'
import { ApiError } from '../api/client'
import { readSessionIds, useSessionIds } from '../hooks/useSessionIds'
import { useGlobalGranularity } from '../hooks/useGlobalGranularity'
import { readHashQueryParams, resolvePipelineFilters, pipelineReturnUrl } from '../utils/pipelineNavigation'
import { useI18n } from '../i18n-context'

interface ReviewDecisionState {
  candidateId: string
  candidateLabel: string
  action: 'approve' | 'reject'
  reviewedBy: string
  reason: string
}

export function HumanReviewPage() {
  const { t } = useI18n()
  const { granularity } = useGlobalGranularity()
  const initial = useMemo(() => {
    const q = readHashQueryParams()
    const f = resolvePipelineFilters()
    return { ...f, tab: q.tab === 'records' ? 'records' as const : 'pending' as const }
  }, [])
  const [activeTab, setActiveTab] = useState<'pending' | 'records'>(initial.tab)
  const [queryBatchId] = useState(initial.batch_id ?? '')
  const [fromPipeline] = useState(initial.fromPipeline && Boolean(initial.batch_id))
  const [actionFilter, setActionFilter] = useState('')
  const [notice, setNotice] = useState<NoticeState | null>(null)
  const onClose = useCallback(() => setNotice(null), [])
  const [tick, setTick] = useState(0)
  const reload = () => setTick(t => t + 1)
  const { setIds } = useSessionIds()

  const [submitCandidateId, setSubmitCandidateId] = useState(readSessionIds().candidate_id ?? '')
  const [submitReviewedBy, setSubmitReviewedBy] = useState('local_user')
  const [submitReason, setSubmitReason] = useState('')
  const [submitting, setSubmitting] = useState(false)

  const [decision, setDecision] = useState<ReviewDecisionState | null>(null)
  const [decidingId, setDecidingId] = useState<string | null>(null)

  const { data: pending, loading: pendingLoading } = useData(
    () => fetchPendingReviews({ limit: 100, granularity_level: granularity || undefined }),
    [tick, granularity],
  )
  const { data: records, loading: recordsLoading } = useData(
    () => fetchReviewRecords({ batch_id: queryBatchId || undefined, action: actionFilter || undefined, limit: 100, granularity_level: granularity || undefined }),
    [queryBatchId, actionFilter, tick, granularity],
  )

  useEffect(() => {
    if (fromPipeline && initial.batch_id) {
      setIds({ batch_id: initial.batch_id })
    }
  }, [fromPipeline, initial, setIds])

  async function handleSubmitReview() {
    if (!submitCandidateId.trim()) { setNotice({ type: 'error', message: t('humanReview.needCandidateId') }); return }
    if (!submitReviewedBy.trim()) { setNotice({ type: 'error', message: t('humanReview.needReviewer') }); return }
    setSubmitting(true)
    try {
      await submitReview(submitCandidateId.trim(), { reviewed_by: submitReviewedBy, reason: submitReason || undefined })
      setIds({ candidate_id: submitCandidateId.trim() })
      setNotice({ type: 'success', message: t('humanReview.submitSuccess') })
      setSubmitCandidateId('')
      reload()
    } catch (e) {
      setNotice({ type: 'error', message: e instanceof ApiError ? e.message : String(e) })
    } finally {
      setSubmitting(false)
    }
  }

  async function handleDecision() {
    if (!decision) return
    setDecidingId(decision.candidateId)
    try {
      await reviewDecision(decision.candidateId, {
        action: decision.action,
        reviewed_by: decision.reviewedBy,
        reason: decision.reason || undefined,
      })
      setIds({ candidate_id: decision.candidateId })
      setNotice({
        type: 'success',
        message: t(decision.action === 'approve' ? 'humanReview.approveSuccess' : 'humanReview.rejectSuccess', { label: decision.candidateLabel }),
      })
      setDecision(null)
      reload()
    } catch (e) {
      setNotice({ type: 'error', message: e instanceof ApiError ? e.message : String(e) })
    } finally {
      setDecidingId(null)
    }
  }

  const pendingColumns: Column<PendingCandidate>[] = useMemo(() => [
    { key: 'cn_name', header: t('common.cnName'), render: r => <strong>{r.cn_name ?? r.en_name ?? r.raw_name}</strong> },
    { key: 'en_name', header: t('common.enName'), render: r => r.en_name ?? '—' },
    { key: 'laterality', header: t('common.laterality'), render: r => <StatusBadge status={r.laterality} /> },
    { key: 'candidate_status', header: t('common.status'), render: r => <StatusBadge status={r.candidate_status} /> },
    { key: 'id', header: t('common.id'), render: r => <code className="text-mono" style={{ fontSize: 11 }}>{r.id.slice(0, 10)}…</code> },
    {
      key: 'actions', header: t('common.actions'),
      render: r => r.candidate_status === 'manual_review_pending' ? (
        <div className="row-actions">
          <ActionButton label={t('humanReview.approve')} variant="success"
            loading={decidingId === r.id}
            onClick={() => setDecision({
              candidateId: r.id,
              candidateLabel: r.cn_name ?? r.en_name ?? r.raw_name,
              action: 'approve',
              reviewedBy: 'local_user',
              reason: '',
            })} />
          <ActionButton label={t('humanReview.reject')} variant="danger"
            loading={decidingId === r.id}
            onClick={() => setDecision({
              candidateId: r.id,
              candidateLabel: r.cn_name ?? r.en_name ?? r.raw_name,
              action: 'reject',
              reviewedBy: 'local_user',
              reason: '',
            })} />
        </div>
      ) : null,
    },
  ], [t, decidingId])

  const recordColumns: Column<CandidateReviewRecord>[] = useMemo(() => [
    { key: 'candidate_id', header: t('humanReview.candidate'), render: r => <code className="text-mono" style={{ fontSize: 11 }}>{r.candidate_id.slice(0, 10)}…</code> },
    { key: 'action', header: t('humanReview.action'), render: r => <StatusBadge status={r.action} /> },
    { key: 'reviewed_by', header: t('common.reviewer') },
    { key: 'reason', header: t('common.reason'), render: r => <span title={r.reason ?? ''}>{(r.reason ?? '').slice(0, 40)}</span> },
    { key: 'created_at', header: t('finalRegions.time'), render: r => r.created_at.slice(0, 16).replace('T', ' ') },
  ], [t])

  return (
    <div>
      <PageHeader title={t('humanReview.title')} description={t('humanReview.description')} readonly={false} />
      <Notice notice={notice} onClose={onClose} />

      {fromPipeline && queryBatchId && (
        <PipelineFilterBanner batchId={queryBatchId} onClear={() => setTick(x => x + 1)} />
      )}

      <div className="card">
        <h3 style={{ fontSize: 13, fontWeight: 600, marginBottom: 10 }}>{t('humanReview.submitTitle')}</h3>
        <p style={{ fontSize: 12, color: '#888', marginBottom: 12 }}>
          {t('humanReview.submitHint')}
        </p>
        <div className="form-row">
          <div className="form-field">
            <label className="form-label">{t('common.candidateId')} *</label>
            <input className="form-input" style={{ width: 300 }} placeholder={t('humanReview.candidateIdPlaceholder')}
              value={submitCandidateId} onChange={e => setSubmitCandidateId(e.target.value)} />
          </div>
          <div className="form-field">
            <label className="form-label">{t('common.reviewer')} *</label>
            <input className="form-input" style={{ width: 140 }} value={submitReviewedBy}
              onChange={e => setSubmitReviewedBy(e.target.value)} />
          </div>
          <div className="form-field" style={{ flex: 1 }}>
            <label className="form-label">{t('common.optionalReason')}</label>
            <input className="form-input" value={submitReason} onChange={e => setSubmitReason(e.target.value)} placeholder={t('humanReview.submitReason')} />
          </div>
          <ActionButton label={t('humanReview.submitBtn')} variant="primary" onClick={handleSubmitReview} loading={submitting} />
        </div>
      </div>

      <div className="card">
        <div className="tab-bar">
          <button className={`tab-btn${activeTab === 'pending' ? ' active' : ''}`} onClick={() => setActiveTab('pending')}>
            {t('humanReview.pendingTab', { count: pending?.total ?? '…' })}
          </button>
          <button className={`tab-btn${activeTab === 'records' ? ' active' : ''}`} onClick={() => setActiveTab('records')}>
            {t('humanReview.recordsTab')}
          </button>
        </div>

        {activeTab === 'pending' && (
          <>
            <div className="filter-bar">
              <button className="btn" onClick={reload}>{t('common.refresh')}</button>
            </div>
            <DataTable columns={pendingColumns} rows={pending?.items ?? []} loading={pendingLoading}
              total={pending?.total} getKey={r => r.id} emptyText={t('humanReview.emptyPending')} />
          </>
        )}

        {activeTab === 'records' && (
          <>
            <div className="filter-bar">
              <span className="filter-label">{t('humanReview.action')}：</span>
              <select className="filter-select" value={actionFilter} onChange={e => setActionFilter(e.target.value)}>
                <option value="">{t('common.all')}</option>
                {['submit_review','approve','reject','request_changes','mark_uncertain'].map(a => <option key={a} value={a}>{a}</option>)}
              </select>
              <button className="btn" style={{ marginLeft: 8 }} onClick={reload}>{t('common.refresh')}</button>
            </div>
            <DataTable columns={recordColumns} rows={records?.items ?? []} loading={recordsLoading}
              total={records?.total} getKey={r => r.id} emptyText={t('humanReview.emptyRecords')} />
          </>
        )}
      </div>

      <ConfirmDialog
        open={!!decision}
        title={decision?.action === 'approve' ? t('humanReview.approveTitle') : t('humanReview.rejectTitle')}
        danger={decision?.action === 'reject'}
        confirmLabel={decision?.action === 'approve' ? t('humanReview.confirmApprove') : t('humanReview.confirmReject')}
        onConfirm={handleDecision}
        onCancel={() => setDecision(null)}
        loading={decidingId !== null}
      >
        <div style={{ marginBottom: 10, fontSize: 13 }}>
          <strong>{decision?.candidateLabel}</strong><br />
          <span style={{ fontSize: 12, color: '#888' }}>{t('common.id')}: {decision?.candidateId}</span>
        </div>
        <div className="form-field" style={{ marginBottom: 8 }}>
          <label className="form-label">{t('common.reviewer')}</label>
          <input className="form-input" value={decision?.reviewedBy ?? ''}
            onChange={e => setDecision(d => d ? { ...d, reviewedBy: e.target.value } : null)} />
        </div>
        <div className="form-field">
          <label className="form-label">{t('common.optionalReason')}</label>
          <textarea className="form-textarea" value={decision?.reason ?? ''}
            onChange={e => setDecision(d => d ? { ...d, reason: e.target.value } : null)}
            placeholder={t('humanReview.reviewComment')} style={{ minHeight: 64 }} />
        </div>
      </ConfirmDialog>
    </div>
  )
}
