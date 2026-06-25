import React, { useState } from 'react'
import { useI18n } from '../../../../i18n-context'
import { useGovernanceProgress } from './useGovernanceProgress'
import type { GovernanceGateId, GovernanceGateProgress, GovernanceSummary } from './governanceTypes'

// ── Gate Progress ─────────────────────────────────────────────────────────────

interface GateProgressProps {
  gates: GovernanceGateProgress[]
  activeGate: GovernanceGateId
  onSwitchGate: (id: GovernanceGateId) => void
}

function GovernanceGateProgress({ gates, activeGate, onSwitchGate }: GateProgressProps) {
  const { t } = useI18n()
  const statusClass = (s: string) => {
    if (s === 'completed') return 'governance-gate-step-completed'
    if (s === 'blocked') return 'governance-gate-step-blocked'
    if (s === 'warning') return 'governance-gate-step-warning'
    if (s === 'ready') return 'governance-gate-step-ready'
    return ''
  }
  const statusIcon = (s: string) => {
    if (s === 'completed') return '✓'
    if (s === 'blocked') return '✕'
    if (s === 'warning') return '!'
    if (s === 'ready') return '→'
    return '○'
  }

  return (
    <div className="governance-gate-progress">
      {gates.map((gate, i) => (
        <React.Fragment key={gate.id}>
          <button
            className={`governance-gate-step ${statusClass(gate.status)} ${activeGate === gate.id ? 'governance-gate-step-active' : ''}`}
            onClick={() => onSwitchGate(gate.id)}
            title={gate.subtitle}
          >
            <span className="governance-gate-step-icon">{statusIcon(gate.status)}</span>
            <span className="governance-gate-step-label">{gate.title}</span>
            <span className="governance-gate-step-pct">{gate.percent}%</span>
            {(gate.blockerCount ?? 0) > 0 && (
              <span className="governance-badge governance-badge-blocker">{gate.blockerCount} {t('llm.governance.blocker')}</span>
            )}
            {(gate.errorCount ?? 0) > 0 && (
              <span className="governance-badge governance-badge-error">{gate.errorCount} {t('llm.governance.error')}</span>
            )}
            {(gate.warningCount ?? 0) > 0 && (
              <span className="governance-badge governance-badge-warning">{gate.warningCount}</span>
            )}
          </button>
          {i < gates.length - 1 && <span className="governance-gate-arrow">→</span>}
        </React.Fragment>
      ))}
    </div>
  )
}

// ── Severity Cards ────────────────────────────────────────────────────────────

function GovernanceSeverityCards({ summary }: { summary: GovernanceSummary }) {
  const { t } = useI18n()
  const cards = [
    {
      key: 'blocker',
      count: summary.blockerCount,
      label: t('llm.governance.blocker'),
      action: t('llm.governance.blockerAction'),
      cls: 'governance-severity-blocker',
    },
    {
      key: 'error',
      count: summary.errorCount,
      label: t('llm.governance.error'),
      action: t('llm.governance.errorAction'),
      cls: 'governance-severity-error',
    },
    {
      key: 'warning',
      count: summary.warningCount,
      label: t('llm.governance.warning'),
      action: t('llm.governance.warningAction'),
      cls: 'governance-severity-warning',
    },
    {
      key: 'info',
      count: summary.infoCount,
      label: t('llm.governance.info'),
      action: t('llm.governance.infoAction'),
      cls: 'governance-severity-info',
    },
  ]
  return (
    <div className="governance-severity-grid">
      {cards.map(c => (
        <div key={c.key} className={`governance-severity-card ${c.cls}`}>
          <div className="governance-severity-count">{c.count}</div>
          <div className="governance-severity-label">{c.label}</div>
          <div className="governance-severity-action">{c.action}</div>
        </div>
      ))}
    </div>
  )
}

// ── Review Summary ────────────────────────────────────────────────────────────

interface ReviewSummaryProps {
  summary: GovernanceSummary
  onOpenReview: () => void
}

function GovernanceReviewSummary({ summary, onOpenReview }: ReviewSummaryProps) {
  const { t } = useI18n()
  const stats = [
    { label: t('llm.governance.reviewQueue'), value: summary.reviewQueueCount, color: '' },
    { label: t('llm.governance.pendingReview'), value: summary.pendingReviewCount, color: 'var(--gov-warning)' },
    { label: t('llm.governance.needsRevision'), value: summary.needsRevisionCount, color: 'var(--gov-error)' },
    { label: t('llm.governance.humanApproved'), value: summary.humanApprovedCount, color: 'var(--gov-success)' },
    { label: t('llm.governance.rejected'), value: summary.rejectedCount, color: 'var(--gov-blocker)' },
  ]
  return (
    <div className="governance-review-summary">
      <div className="governance-section-title">{t('llm.governance.humanReview')}</div>
      <div className="governance-review-cards">
        {stats.map(s => (
          <button
            key={s.label}
            className="governance-review-card"
            onClick={onOpenReview}
            style={{ borderTopColor: s.color || 'var(--gov-neutral)' }}
          >
            <span className="governance-review-card-value" style={{ color: s.color || undefined }}>{s.value}</span>
            <span className="governance-review-card-label">{s.label}</span>
          </button>
        ))}
      </div>
    </div>
  )
}

// ── Promotion Readiness ───────────────────────────────────────────────────────

interface PromotionReadinessProps {
  summary: GovernanceSummary
  onJumpToFinalPromotion: () => void
}

function GovernancePromotionReadiness({ summary, onJumpToFinalPromotion }: PromotionReadinessProps) {
  const { t } = useI18n()
  const canJump = summary.humanApprovedCount > 0
  const isBlocked = summary.blockerCount > 0 || summary.errorCount > 0

  return (
    <div className="governance-promotion-readiness">
      <div className="governance-section-title">{t('llm.governance.promotionReadiness')}</div>
      <div className="governance-promotion-grid">
        <div className="governance-promotion-stat">
          <span className="governance-promotion-value gov-success">{summary.humanApprovedCount}</span>
          <span className="governance-promotion-label">{t('llm.governance.humanApproved')}</span>
        </div>
        <div className="governance-promotion-stat">
          <span className="governance-promotion-value gov-blocker">{summary.blockerCount}</span>
          <span className="governance-promotion-label">{t('llm.governance.blocker')}</span>
        </div>
        <div className="governance-promotion-stat">
          <span className="governance-promotion-value gov-error">{summary.errorCount}</span>
          <span className="governance-promotion-label">{t('llm.governance.error')}</span>
        </div>
        <div className="governance-promotion-stat">
          <span className={`governance-promotion-value ${isBlocked ? 'gov-blocked' : 'gov-success'}`}>
            {isBlocked ? 0 : summary.humanApprovedCount}
          </span>
          <span className="governance-promotion-label">
            {t('llm.governance.promotionReady')}
            <span className="governance-estimated-badge">{t('llm.governance.estimated')}</span>
          </span>
        </div>
      </div>
      <div className="governance-promotion-note">{t('llm.governance.promotionReadinessBoundary')}</div>
      <button
        className="governance-jump-button"
        disabled={!canJump}
        onClick={onJumpToFinalPromotion}
        title={canJump ? t('llm.governance.jumpToFinalPromotion') : t('llm.governance.noObjectsNext')}
      >
        {t('llm.governance.jumpToFinalPromotion')} →
      </button>
    </div>
  )
}

// ── Next Step ─────────────────────────────────────────────────────────────────

function GovernanceNextStep({ nextStepKey }: { nextStepKey: string }) {
  const { t } = useI18n()
  return (
    <div className="governance-next-step">
      <span className="governance-next-step-label">💡 {t('llm.governance.nextStep')}：</span>
      <span>{t(`llm.governance.${nextStepKey}`)}</span>
    </div>
  )
}

// ── Gate Card ─────────────────────────────────────────────────────────────────

interface GateCardProps {
  gate: GovernanceGateProgress
  expanded: boolean
  onToggle: () => void
  children?: React.ReactNode
  summary: GovernanceSummary
  onOpenWorkspace: () => void
}

function GovernanceGateCard({ gate, expanded, onToggle, children, summary, onOpenWorkspace }: GateCardProps) {
  const { t } = useI18n()
  const statusClass = {
    not_started: '',
    ready: 'gate-card-ready',
    blocked: 'gate-card-blocked',
    warning: 'gate-card-warning',
    completed: 'gate-card-completed',
  }[gate.status] ?? ''

  const boundaryKey: Record<GovernanceGateId, string> = {
    validation: 'llm.governance.validationBoundary',
    review: 'llm.governance.reviewBoundary',
    promotion_readiness: 'llm.governance.promotionReadinessBoundary',
  }

  const renderMeta = () => {
    if (gate.id === 'validation') {
      return (
        <div className="governance-gate-meta">
          <span>Runs: {summary.validationRunCount}</span>
          {summary.blockerCount > 0 && <span className="gov-blocker">Blocker: {summary.blockerCount}</span>}
          {summary.errorCount > 0 && <span className="gov-error">Error: {summary.errorCount}</span>}
          {summary.warningCount > 0 && <span className="gov-warning">Warning: {summary.warningCount}</span>}
        </div>
      )
    }
    if (gate.id === 'review') {
      return (
        <div className="governance-gate-meta">
          <span>Queue: {summary.reviewQueueCount}</span>
          <span className="gov-success">Approved: {summary.humanApprovedCount}</span>
          {summary.pendingReviewCount > 0 && <span className="gov-warning">Pending: {summary.pendingReviewCount}</span>}
        </div>
      )
    }
    // promotion_readiness
    return (
      <div className="governance-gate-meta">
        <span className="gov-success">Ready (est.): {summary.blockerCount === 0 && summary.errorCount === 0 ? summary.humanApprovedCount : 0}</span>
        {summary.blockerCount > 0 && <span className="gov-blocker">Blocked by: blockers</span>}
      </div>
    )
  }

  return (
    <div className={`governance-gate-card ${statusClass} ${expanded ? 'governance-gate-card-expanded' : ''}`}>
      <div className="governance-gate-card-header" onClick={onToggle}>
        <div className="governance-gate-card-title">
          <span className="governance-gate-card-index">Gate {gate.index + 1}</span>
          <span className="governance-gate-card-name">{gate.title}</span>
          <span className="governance-gate-card-sub">{gate.subtitle}</span>
        </div>
        {renderMeta()}
        <div className="governance-gate-card-actions">
          {gate.id !== 'promotion_readiness' && (
            <button
              className="governance-gate-open-btn"
              onClick={(e) => { e.stopPropagation(); onOpenWorkspace() }}
            >
              {gate.id === 'validation' ? t('llm.governance.openValidationWorkspace') : t('llm.governance.openReviewWorkspace')}
            </button>
          )}
          <span className="governance-gate-toggle">{expanded ? t('llm.governance.collapseGate') : t('llm.governance.expandGate')}</span>
        </div>
      </div>
      {expanded && (
        <div className="governance-gate-card-body">
          <div className="governance-boundary governance-gate-boundary">
            ⚠ {t(boundaryKey[gate.id])}
          </div>
          {children}
        </div>
      )}
    </div>
  )
}

// ── Dashboard (main export) ───────────────────────────────────────────────────

export interface GovernanceDashboardProps {
  activeGate: GovernanceGateId
  onSwitchGate: (id: GovernanceGateId) => void
  onJumpToFinalPromotion: () => void
  refreshKey?: number
}

export function GovernanceDashboard({
  activeGate,
  onSwitchGate,
  onJumpToFinalPromotion,
  refreshKey = 0,
}: GovernanceDashboardProps) {
  const { t } = useI18n()
  const { summary, gates, recommendedNextStep, loading, refresh } = useGovernanceProgress(refreshKey)
  const [expandedGate, setExpandedGate] = useState<GovernanceGateId | null>(null)

  const toggleGate = (id: GovernanceGateId) =>
    setExpandedGate(prev => (prev === id ? null : id))

  if (loading && summary.validationRunCount === 0 && !summary.hasApiError) {
    return <div className="governance-dashboard governance-loading">Loading governance status…</div>
  }

  return (
    <div className="governance-dashboard">
      {/* Top boundary notice */}
      <div className="governance-boundary">
        ⚠ {t('llm.governance.boundary')}
      </div>

      {/* API error warning */}
      {summary.hasApiError && (
        <div className="notice notice-warning" style={{ margin: '8px 0' }}>
          {summary.warnings.join(' · ')}
        </div>
      )}

      {/* Overview section */}
      <div className="governance-overview">
        <div className="governance-overview-header">
          <h3 className="governance-overview-title">{t('llm.governance.title')}</h3>
          <button className="governance-refresh-btn" onClick={refresh} title="Refresh">↻</button>
        </div>

        {/* Gate Progress */}
        <div className="governance-section-label">{t('llm.governance.gateProgress')}</div>
        <GovernanceGateProgress gates={gates} activeGate={activeGate} onSwitchGate={onSwitchGate} />

        {/* Next Step */}
        <GovernanceNextStep nextStepKey={recommendedNextStep} />

        {/* Severity Cards */}
        <GovernanceSeverityCards summary={summary} />

        {/* Review Summary */}
        <GovernanceReviewSummary
          summary={summary}
          onOpenReview={() => onSwitchGate('review')}
        />

        {/* Promotion Readiness */}
        <GovernancePromotionReadiness
          summary={summary}
          onJumpToFinalPromotion={onJumpToFinalPromotion}
        />
      </div>

      {/* Gate Cards */}
      <div className="governance-gate-cards">
        {gates.map(gate => (
          <GovernanceGateCard
            key={gate.id}
            gate={gate}
            expanded={expandedGate === gate.id}
            onToggle={() => toggleGate(gate.id)}
            summary={summary}
            onOpenWorkspace={() => onSwitchGate(gate.id)}
          >
            {gate.id === 'promotion_readiness' && (
              <GovernancePromotionReadiness
                summary={summary}
                onJumpToFinalPromotion={onJumpToFinalPromotion}
              />
            )}
          </GovernanceGateCard>
        ))}
      </div>
    </div>
  )
}
