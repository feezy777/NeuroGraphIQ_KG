import { useI18n } from '../../i18n-context'
import type { DataCenterTabId } from './dataCenterTypes'

const TAB_KEYS: Record<DataCenterTabId, string> = {
  overview: 'dataCenter.overview',
  raw: 'dataCenter.rawData',
  candidates: 'dataCenter.candidateRegions',
  mirror: 'dataCenter.mirrorKg',
  macro: 'dataCenter.macroClinical',
  final: 'dataCenter.finalKg',
  exports: 'dataCenter.exports',
}

interface Props {
  activeTab: DataCenterTabId
  onTabChange: (tab: DataCenterTabId) => void
}

export function DataCenterTabBar({ activeTab, onTabChange }: Props) {
  const { t } = useI18n()
  return (
    <div className="data-center-tabbar">
      {(Object.keys(TAB_KEYS) as DataCenterTabId[]).map(tab => (
        <button
          key={tab}
          type="button"
          className={`data-center-tab${activeTab === tab ? ' data-center-tab-active' : ''}`}
          onClick={() => onTabChange(tab)}
        >
          {t(TAB_KEYS[tab])}
        </button>
      ))}
    </div>
  )
}
