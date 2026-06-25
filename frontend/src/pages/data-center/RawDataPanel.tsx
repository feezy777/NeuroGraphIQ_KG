import { useI18n } from '../../i18n-context'
import { RawAal3Page } from '../RawAal3Page'
import { RawMacro96Page } from '../RawMacro96Page'
import type { RawDataSubTab } from './dataCenterTypes'

interface Props {
  rawTab: RawDataSubTab
  onRawTabChange: (tab: RawDataSubTab) => void
}

export function RawDataPanel({ rawTab, onRawTabChange }: Props) {
  const { t } = useI18n()
  const subTabs: Array<{ id: RawDataSubTab; label: string }> = [
    { id: 'aal3', label: t('dataCenter.rawAal3') },
    { id: 'macro96', label: t('dataCenter.rawMacro96') },
  ]

  return (
    <div className="data-center-panel">
      <div className="data-center-boundary data-center-boundary-raw">
        {t('dataCenter.boundaryRaw')}
      </div>
      <div className="data-center-subtabbar">
        {subTabs.map(st => (
          <button
            key={st.id}
            type="button"
            className={`data-center-tab${rawTab === st.id ? ' data-center-tab-active' : ''}`}
            onClick={() => onRawTabChange(st.id)}
          >
            {st.label}
          </button>
        ))}
      </div>
      <div className="data-center-embedded-host">
        {rawTab === 'aal3' ? <RawAal3Page embedded /> : <RawMacro96Page embedded />}
      </div>
    </div>
  )
}
