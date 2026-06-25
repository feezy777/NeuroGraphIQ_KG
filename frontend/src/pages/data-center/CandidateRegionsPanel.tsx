import { useI18n } from '../../i18n-context'
import { CandidatesPage } from '../CandidatesPage'

export function CandidateRegionsPanel() {
  const { t } = useI18n()
  return (
    <div className="data-center-panel">
      <div className="data-center-boundary data-center-boundary-candidate">
        {t('dataCenter.boundaryCandidate')}
      </div>
      <div className="data-center-embedded-host">
        <CandidatesPage embedded />
      </div>
    </div>
  )
}
