import { useCallback, useEffect, useRef, useState, type PointerEvent as ReactPointerEvent } from 'react'
import { useI18n } from '../../../i18n-context'
import {
  getWorkflowDisplayStatus,
  type ExtractionResultModalData,
} from './ExtractionResultModal'

const WIDGET_POS_KEY = 'llm.extractionWidgetPos'
const DEFAULT_POS = { x: 24, y: 96 }

function loadWidgetPos(): { x: number; y: number } {
  try {
    const raw = sessionStorage.getItem(WIDGET_POS_KEY)
    if (!raw) return DEFAULT_POS
    const parsed = JSON.parse(raw) as { x?: number; y?: number }
    if (typeof parsed.x === 'number' && typeof parsed.y === 'number') {
      return { x: parsed.x, y: parsed.y }
    }
  } catch {
    /* ignore */
  }
  return DEFAULT_POS
}

function formatElapsed(ms?: number): string {
  if (ms == null || ms < 0) return '0s'
  const sec = Math.floor(ms / 1000)
  if (sec < 60) return `${sec}s`
  const min = Math.floor(sec / 60)
  return `${min}m ${sec % 60}s`
}

interface Props {
  data: ExtractionResultModalData
  uiPaused: boolean
  onRestore: () => void
  onTogglePause: () => void
}

export function ExtractionRunFloatingWidget({
  data,
  uiPaused,
  onRestore,
  onTogglePause,
}: Props) {
  const { t } = useI18n()
  const [pos, setPos] = useState(loadWidgetPos)
  const dragRef = useRef<{ pointerId: number; startX: number; startY: number; origX: number; origY: number } | null>(null)

  const displayStatus = getWorkflowDisplayStatus(data)
  const runningStep = data.substeps?.find(s => s.status === 'running')
  const connSummary = data.executionSummary ?? data.substeps?.find(s => s.id === 'connection')?.executionSummary
  const providerCalls = connSummary ? Number((connSummary as Record<string, unknown>).provider_call_count ?? 0) : null

  useEffect(() => {
    try {
      sessionStorage.setItem(WIDGET_POS_KEY, JSON.stringify(pos))
    } catch {
      /* ignore */
    }
  }, [pos])

  const onPointerDown = useCallback((e: ReactPointerEvent<HTMLDivElement>) => {
    if ((e.target as HTMLElement).closest('button')) return
    dragRef.current = {
      pointerId: e.pointerId,
      startX: e.clientX,
      startY: e.clientY,
      origX: pos.x,
      origY: pos.y,
    }
    e.currentTarget.setPointerCapture(e.pointerId)
  }, [pos.x, pos.y])

  const onPointerMove = useCallback((e: ReactPointerEvent<HTMLDivElement>) => {
    const drag = dragRef.current
    if (!drag || drag.pointerId !== e.pointerId) return
    const dx = e.clientX - drag.startX
    const dy = e.clientY - drag.startY
    const maxX = Math.max(8, window.innerWidth - 220)
    const maxY = Math.max(8, window.innerHeight - 120)
    setPos({
      x: Math.min(maxX, Math.max(8, drag.origX + dx)),
      y: Math.min(maxY, Math.max(8, drag.origY + dy)),
    })
  }, [])

  const onPointerUp = useCallback((e: ReactPointerEvent<HTMLDivElement>) => {
    if (dragRef.current?.pointerId === e.pointerId) {
      dragRef.current = null
      e.currentTarget.releasePointerCapture(e.pointerId)
    }
  }, [])

  return (
    <div
      className="llm-extraction-floating-widget"
      style={{ left: pos.x, top: pos.y }}
      role="status"
      aria-live="polite"
    >
      <div
        className="llm-extraction-floating-widget-drag"
        onPointerDown={onPointerDown}
        onPointerMove={onPointerMove}
        onPointerUp={onPointerUp}
        onPointerCancel={onPointerUp}
      >
        <span className="llm-extraction-floating-widget-grip">⠿</span>
        <div className="llm-extraction-floating-widget-main" onClick={onRestore} title={t('llm.resultModal.restorePanel')}>
          <div className="llm-extraction-floating-widget-title">{data.taskLabel}</div>
          <div className="llm-extraction-floating-widget-meta">
            <span className={`llm-result-status-tone-${displayStatus.tone}`}>{displayStatus.label}</span>
            {uiPaused && <span className="llm-extraction-floating-paused">{t('llm.resultModal.uiPaused')}</span>}
            <span>{formatElapsed(data.elapsedMs)}</span>
            {!data.indeterminate && data.progressPercent != null && (
              <span>{data.progressPercent}%</span>
            )}
            {providerCalls != null && <span>calls={providerCalls}</span>}
          </div>
          {runningStep && (
            <div className="llm-extraction-floating-widget-step">
              {t(runningStep.label)} · {runningStep.status}
            </div>
          )}
        </div>
        <div className="llm-extraction-floating-widget-actions">
          <button type="button" className="llm-btn llm-btn-xs" onClick={onTogglePause}>
            {uiPaused ? t('llm.resultModal.resumeUi') : t('llm.resultModal.pauseUi')}
          </button>
          <button type="button" className="llm-btn llm-btn-xs llm-btn-primary" onClick={onRestore}>
            {t('llm.resultModal.restorePanel')}
          </button>
        </div>
      </div>
    </div>
  )
}
