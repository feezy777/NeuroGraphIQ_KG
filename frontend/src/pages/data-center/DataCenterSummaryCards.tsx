import { useI18n } from '../../i18n-context'
import type { DataCenterCounts, DataCenterTabId } from './dataCenterTypes'

interface Props {
  counts: DataCenterCounts
  onNavigate: (tab: DataCenterTabId) => void
}

export function DataCenterSummaryCards({ counts, onNavigate }: Props) {
  const { t } = useI18n()
  const cards = [
    { key: 'raw', label: t('dataCenter.rawCount'), value: counts.rawAal3Count + counts.rawMacro96Count, tab: 'raw' as DataCenterTabId },
    { key: 'candidates', label: t('dataCenter.candidateCount'), value: counts.candidateCount, tab: 'candidates' as DataCenterTabId },
    {
      key: 'mirror',
      label: t('dataCenter.mirrorObjectCount'),
      value: counts.mirrorConnections + counts.mirrorFunctions + counts.mirrorCircuits + counts.mirrorTriples,
      tab: 'mirror' as DataCenterTabId,
    },
    {
      key: 'macro',
      label: t('dataCenter.macroObjectCount'),
      value: counts.macroCircuitSteps + counts.macroProjectionFunctions + counts.macroMemberships,
      tab: 'macro' as DataCenterTabId,
    },
    {
      key: 'final',
      label: t('dataCenter.finalObjectCount'),
      value: counts.finalCircuits + counts.finalProjections + counts.finalSteps + counts.finalFunctions + counts.finalTriples,
      tab: 'final' as DataCenterTabId,
    },
    { key: 'exports', label: t('dataCenter.exportCount'), value: counts.exportCount, tab: 'exports' as DataCenterTabId },
  ]

  return (
    <div className="data-center-summary-grid">
      {cards.map(c => (
        <button
          key={c.key}
          type="button"
          className="data-center-summary-card"
          onClick={() => onNavigate(c.tab)}
        >
          <span className="data-center-summary-value">{c.value}</span>
          <span className="data-center-summary-label">{c.label}</span>
        </button>
      ))}
    </div>
  )
}
