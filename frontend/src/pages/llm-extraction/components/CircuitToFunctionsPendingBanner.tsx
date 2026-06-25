/**
 * Banner shown in the LLM Extraction Center when the user was redirected from
 * Data Center Bundle because no mirror_circuit_functions exist for the selected
 * circuits.  Reads circuit IDs from sessionStorage and displays a hint to run
 * the composite "circuit + steps + functions" workflow or the standalone
 * circuit_to_functions extraction.
 */
import { useEffect, useState } from 'react'
import { useI18n } from '../../../i18n-context'

const SESSION_KEY_IDS = 'pendingCircuitFunctionExtractionCircuitIds'
const SESSION_KEY_SRC = 'pendingCircuitFunctionExtractionSource'

interface Props {
  onDismiss?: () => void
}

export function CircuitToFunctionsPendingBanner({ onDismiss }: Props) {
  const { t } = useI18n()
  const [circuitIds, setCircuitIds] = useState<string[]>([])

  useEffect(() => {
    try {
      const raw = sessionStorage.getItem(SESSION_KEY_IDS)
      if (raw) setCircuitIds(JSON.parse(raw) as string[])
    } catch {
      // ignore parse errors
    }
  }, [])

  const dismiss = () => {
    sessionStorage.removeItem(SESSION_KEY_IDS)
    sessionStorage.removeItem(SESSION_KEY_SRC)
    setCircuitIds([])
    onDismiss?.()
  }

  if (circuitIds.length === 0) return null

  return (
    <div className="llm-extraction-cf-pending-banner">
      <strong>{t('llmExtraction.cfPendingBannerTitle')}</strong>
      <p>{t('llmExtraction.cfPendingBannerDesc', { count: String(circuitIds.length) })}</p>
      <p className="llm-extraction-cf-pending-ids">
        {t('llmExtraction.cfPendingCircuitIds')}: {circuitIds.slice(0, 5).join(', ')}{circuitIds.length > 5 ? ` …+${circuitIds.length - 5}` : ''}
      </p>
      <button type="button" className="btn btn-sm" onClick={dismiss}>
        {t('llmExtraction.cfPendingDismiss')}
      </button>
    </div>
  )
}
