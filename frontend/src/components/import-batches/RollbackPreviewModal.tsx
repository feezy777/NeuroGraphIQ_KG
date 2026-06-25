import { useEffect, useMemo, useState } from 'react'
import { ActionButton } from '../ActionButton'
import { LoadingState } from '../States'
import {
  executeImportBatchRollback,
  getImportBatchRollbackPreview,
  type RollbackExecuteResponse,
  type RollbackPreviewResponse,
} from '../../api/endpoints'
import { formatApiErrorMessage } from '../../utils/apiErrorMessage'
import { useI18n } from '../../i18n-context'

const STATUS_RANK: Record<string, number> = {
  created: 0,
  queued: 1,
  running: 2,
  parsed: 3,
  candidate_generated: 4,
  validated: 5,
  validation_dispatched: 5,
  reviewed: 6,
  promoted: 7,
  completed: 7,
}

const TARGET_OPTIONS = [
  'running',
  'parsed',
  'candidate_generated',
  'validated',
  'reviewed',
] as const

function rollbackTargetsForStatus(status: string): string[] {
  const cur = STATUS_RANK[status] ?? -1
  return TARGET_OPTIONS.filter(t => (STATUS_RANK[t] ?? 99) < cur)
}

const TARGET_I18N: Record<string, string> = {
  running: 'pipeline.rollbackTargetRunning',
  parsed: 'pipeline.rollbackTargetParsed',
  candidate_generated: 'pipeline.rollbackTargetCandidateGenerated',
  validated: 'pipeline.rollbackTargetValidated',
  reviewed: 'pipeline.rollbackTargetReviewed',
}

const PLAN_LABELS: Record<string, string> = {
  raw_parse_runs: 'raw_parse_runs',
  raw_aal3_region_labels: 'raw_aal3_region_labels',
  raw_macro96_region_rows: 'raw_macro96_region_rows',
  candidate_generation_runs: 'candidate_generation_runs',
  candidate_brain_regions: 'candidate_brain_regions',
  rule_validation_runs: 'rule_validation_runs',
  candidate_rule_validation_results: 'candidate_rule_validation_results',
  candidate_review_records: 'candidate_review_records',
  promotion_records: 'promotion_records',
  final_brain_regions: 'final_brain_regions',
}

const RISK_I18N: Record<string, string> = {
  low: 'pipeline.rollbackRiskLow',
  medium: 'pipeline.rollbackRiskMedium',
  high: 'pipeline.rollbackRiskHigh',
  critical: 'pipeline.rollbackRiskCritical',
}

function PlanTable({
  title,
  plan,
  emptyHint,
}: {
  title: string
  plan: Record<string, number>
  emptyHint?: string
}) {
  const rows = Object.entries(plan).filter(([, n]) => n > 0)
  if (rows.length === 0) {
    return (
      <div className="rollback-plan-section">
        <h4>{title}</h4>
        <p className="rollback-preview-only-note">{emptyHint ?? '—'}</p>
      </div>
    )
  }
  return (
    <div className="rollback-plan-section">
      <h4>{title}</h4>
      <div className="rollback-plan-table-wrap">
        <table className="rollback-plan-table">
          <thead>
            <tr>
              <th>Object</th>
              <th>Count</th>
            </tr>
          </thead>
          <tbody>
            {rows.map(([key, count]) => (
              <tr key={key}>
                <td><code>{PLAN_LABELS[key] ?? key}</code></td>
                <td>{count}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </div>
  )
}

export function RollbackPreviewModal({
  open,
  batchId,
  batchCode,
  currentStatus,
  onClose,
  onSuccess,
}: {
  open: boolean
  batchId: string
  batchCode: string
  currentStatus: string
  onClose: () => void
  onSuccess?: (result: RollbackExecuteResponse) => void
}) {
  const { t } = useI18n()
  const targets = useMemo(() => rollbackTargetsForStatus(currentStatus), [currentStatus])
  const [targetStatus, setTargetStatus] = useState('')
  const [preview, setPreview] = useState<RollbackPreviewResponse | null>(null)
  const [loading, setLoading] = useState(false)
  const [executing, setExecuting] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const [confirmationText, setConfirmationText] = useState('')
  const [operator, setOperator] = useState('')
  const [reason, setReason] = useState('')

  useEffect(() => {
    if (!open) return
    setTargetStatus(targets[targets.length - 1] ?? '')
    setPreview(null)
    setError(null)
    setConfirmationText('')
    setOperator('')
    setReason('')
  }, [open, batchId, currentStatus, targets])

  useEffect(() => {
    if (!open || !targetStatus) return
    let cancelled = false
    setLoading(true)
    setError(null)
    setConfirmationText('')
    getImportBatchRollbackPreview(batchId, targetStatus)
      .then(data => {
        if (!cancelled) setPreview(data)
      })
      .catch(e => {
        if (!cancelled) setError(formatApiErrorMessage(e))
      })
      .finally(() => {
        if (!cancelled) setLoading(false)
      })
    return () => { cancelled = true }
  }, [open, batchId, targetStatus])

  const confirmationOk = preview != null && confirmationText === preview.required_confirmation
  const operatorOk = operator.trim().length > 0
  const reasonOk = reason.trim().length > 0
  const canExecute = Boolean(
    preview?.supported && confirmationOk && operatorOk && reasonOk && !loading && !executing,
  )

  const handleExecute = async () => {
    if (!preview || !canExecute) return
    setExecuting(true)
    setError(null)
    try {
      const result = await executeImportBatchRollback(batchId, {
        target_status: targetStatus,
        confirmation_text: confirmationText,
        operator: operator.trim(),
        reason: reason.trim(),
        expected_delete_plan: preview.delete_plan,
        expected_dependency_counts: preview.dependency_counts,
      })
      onSuccess?.(result)
      onClose()
    } catch (e) {
      setError(formatApiErrorMessage(e))
    } finally {
      setExecuting(false)
    }
  }

  if (!open) return null

  const riskClass = preview?.risk_level
    ? `rollback-risk-${preview.risk_level}`
    : 'rollback-risk-low'
  const hasFinalDelete = (preview?.delete_plan?.final_brain_regions ?? 0) > 0

  return (
    <div className="dialog-overlay" onClick={e => { if (e.target === e.currentTarget) onClose() }}>
      <div className="rollback-preview-modal rollback-execute-modal dialog-box">
        <div className="dialog-title">{t('pipeline.rollbackExecuteTitle')}</div>

        {targets.length === 0 ? (
          <p className="rollback-preview-only-note">{t('pipeline.rollbackNoAvailableTarget')}</p>
        ) : (
          <>
            <div className="rollback-plan-grid">
              <div>
                <span className="form-label">{t('pipeline.rollbackCurrentStatus')}</span>
                <div><code>{currentStatus}</code></div>
              </div>
              <div>
                <span className="form-label">{t('pipeline.rollbackTargetStatus')}</span>
                <select
                  className="form-select"
                  value={targetStatus}
                  onChange={e => setTargetStatus(e.target.value)}
                >
                  {targets.map(ts => (
                    <option key={ts} value={ts}>
                      {TARGET_I18N[ts] ? t(TARGET_I18N[ts]) : ts}
                    </option>
                  ))}
                </select>
              </div>
              {preview && (
                <div>
                  <span className="form-label">{t('pipeline.rollbackRiskLevel')}</span>
                  <div className={`rollback-risk-badge ${riskClass}`}>
                    {RISK_I18N[preview.risk_level] ? t(RISK_I18N[preview.risk_level]) : preview.risk_level}
                  </div>
                </div>
              )}
            </div>

            {loading && <LoadingState />}
            {error && <p className="batch-create-warning">{error}</p>}

            {preview && !loading && (
              <>
                <PlanTable title={t('pipeline.rollbackWillDelete')} plan={preview.delete_plan} />
                <PlanTable title={t('pipeline.rollbackWillKeep')} plan={preview.keep_plan} />
                <PlanTable
                  title={t('pipeline.rollbackDependencyCounts')}
                  plan={preview.dependency_counts}
                />
                {hasFinalDelete && (
                  <div className="rollback-execute-danger-zone rollback-final-danger">
                    {t('pipeline.rollbackDangerFinalData')}
                  </div>
                )}
                {preview.warnings.length > 0 && (
                  <div className="rollback-warning-list">
                    <h4>{t('pipeline.rollbackWarnings')}</h4>
                    <ul>
                      {preview.warnings.map((w, i) => <li key={i}>{w}</li>)}
                    </ul>
                  </div>
                )}
                <div className="rollback-confirmation-form">
                  <p className="rollback-execute-confirm-note">{t('pipeline.rollbackExecuteConfirm')}</p>
                  <div className="rollback-confirmation-preview">
                    <span className="form-label">{t('pipeline.rollbackRequiredConfirmation')}</span>
                    <code>{preview.required_confirmation}</code>
                  </div>
                  <label className="form-label" htmlFor="rollback-confirmation-input">
                    {t('pipeline.rollbackConfirmationText')}
                  </label>
                  <input
                    id="rollback-confirmation-input"
                    className="form-input rollback-confirmation-input"
                    value={confirmationText}
                    onChange={e => setConfirmationText(e.target.value)}
                    placeholder={t('pipeline.rollbackConfirmationPlaceholder')}
                    autoComplete="off"
                  />
                  {confirmationText.length > 0 && !confirmationOk && (
                    <p className="rollback-confirmation-mismatch">{t('pipeline.rollbackConfirmationMismatch')}</p>
                  )}
                  <label className="form-label" htmlFor="rollback-operator-input">
                    {t('pipeline.rollbackOperator')}
                  </label>
                  <input
                    id="rollback-operator-input"
                    className="form-input rollback-operator-input"
                    value={operator}
                    onChange={e => setOperator(e.target.value)}
                    autoComplete="off"
                  />
                  <label className="form-label" htmlFor="rollback-reason-input">
                    {t('pipeline.rollbackReason')}
                  </label>
                  <textarea
                    id="rollback-reason-input"
                    className="form-textarea rollback-reason-input"
                    rows={3}
                    value={reason}
                    onChange={e => setReason(e.target.value)}
                  />
                </div>
              </>
            )}
          </>
        )}

        <div className="dialog-footer">
          <ActionButton label={t('common.close')} variant="default" onClick={onClose} />
          <ActionButton
            label={t('pipeline.rollbackExecute')}
            variant="danger"
            disabled={!canExecute}
            loading={executing}
            onClick={handleExecute}
          />
        </div>
      </div>
    </div>
  )
}
