import { useState, useCallback, useEffect, useRef } from 'react'
import { ChevronDown, ChevronUp, Copy, Trash2, X } from 'lucide-react'
import { useI18n } from '../i18n-context'
import { useWorkbenchLog } from '../logging/useWorkbenchLog'
import type { WorkbenchLogEntry, WorkbenchLogLevelFilter } from '../logging/workbenchLogTypes'

function formatTime(iso: string): string {
  return iso.slice(11, 19)
}

function entryToText(entry: WorkbenchLogEntry): string {
  const lines = [
    `[${entry.timestamp}] ${entry.level.toUpperCase()} (${entry.source}) ${entry.title}`,
  ]
  if (entry.message) lines.push(`message: ${entry.message}`)
  if (entry.method && entry.url) lines.push(`${entry.method} ${entry.url}`)
  if (entry.status != null) lines.push(`status: ${entry.status} ${entry.statusText ?? ''}`)
  if (entry.requestBodyPreview !== undefined) {
    lines.push(`request: ${JSON.stringify(entry.requestBodyPreview, null, 2)}`)
  }
  if (entry.responseBody !== undefined) {
    lines.push(`response: ${JSON.stringify(entry.responseBody, null, 2)}`)
  }
  if (entry.detail !== undefined) lines.push(`detail: ${JSON.stringify(entry.detail, null, 2)}`)
  if (entry.stack) lines.push(`stack:\n${entry.stack}`)
  return lines.join('\n')
}

function entrySummary(entry: WorkbenchLogEntry): string {
  if (entry.message) return entry.message
  if (entry.status != null) return `HTTP ${entry.status}`
  if (entry.errorMessage) return entry.errorMessage
  return ''
}

function LogEntryRow({ entry }: { entry: WorkbenchLogEntry }) {
  const { t } = useI18n()
  const [open, setOpen] = useState(false)

  const copyOne = useCallback(async () => {
    try {
      await navigator.clipboard.writeText(entryToText(entry))
    } catch {
      // ignore
    }
  }, [entry])

  const summary = entrySummary(entry)

  return (
    <div className={`log-entry log-entry-${entry.level}${open ? ' open' : ''}`}>
      <button type="button" className="log-entry-head" onClick={() => setOpen(o => !o)}>
        <span className={`log-level-badge level-${entry.level}`}>{entry.level}</span>
        <span className="log-source">{entry.source}</span>
        <span className="log-time">{formatTime(entry.timestamp)}</span>
        <span className="log-title">{entry.title}</span>
        {!open && summary && <span className="log-summary">{summary}</span>}
        <span className="log-expand-hint">{open ? '▾' : '▸'}</span>
      </button>
      {open && (
        <div className="log-entry-body">
          {entry.method && entry.url && (
            <div className="log-detail-row">
              <span className="log-detail-label">{t('logConsole.request')}</span>
              <code>{entry.method} {entry.url}</code>
            </div>
          )}
          {entry.status != null && (
            <div className="log-detail-row">
              <span className="log-detail-label">{t('logConsole.status')}</span>
              <span>{entry.status} {entry.statusText ?? ''}</span>
            </div>
          )}
          {entry.pageHash && (
            <div className="log-detail-row">
              <span className="log-detail-label">{t('logConsole.page')}</span>
              <code>{entry.pageHash}</code>
            </div>
          )}
          {entry.message && (
            <div className="log-detail-row">
              <span className="log-detail-label">{t('logConsole.message')}</span>
              <span>{entry.message}</span>
            </div>
          )}
          {entry.requestBodyPreview !== undefined && (
            <div className="log-detail-block">
              <div className="log-detail-label">{t('logConsole.requestBody')}</div>
              <pre>{JSON.stringify(entry.requestBodyPreview, null, 2)}</pre>
            </div>
          )}
          {entry.responseBody !== undefined && (
            <div className="log-detail-block">
              <div className="log-detail-label">{t('logConsole.responseBody')}</div>
              <pre>{JSON.stringify(entry.responseBody, null, 2)}</pre>
            </div>
          )}
          {entry.detail !== undefined && (
            <div className="log-detail-block">
              <div className="log-detail-label">{t('logConsole.detail')}</div>
              <pre>{typeof entry.detail === 'string' ? entry.detail : JSON.stringify(entry.detail, null, 2)}</pre>
            </div>
          )}
          {entry.stack && (
            <div className="log-detail-block">
              <div className="log-detail-label">{t('logConsole.stack')}</div>
              <pre>{entry.stack}</pre>
            </div>
          )}
          <button type="button" className="log-copy-one" onClick={() => void copyOne()}>
            <Copy size={12} /> {t('logConsole.copyEntry')}
          </button>
        </div>
      )}
    </div>
  )
}

const FILTERS: WorkbenchLogLevelFilter[] = ['all', 'error', 'warning', 'info', 'request']

export function BottomLogConsole() {
  const { t } = useI18n()
  const {
    expanded,
    setExpanded,
    levelFilter,
    setLevelFilter,
    filteredLogs,
    logs,
    clearLogs,
    errorCount,
    lastError,
  } = useWorkbenchLog()

  const consoleRef = useRef<HTMLDivElement>(null)

  // Dynamically set --log-console-actual-height on the layout parent
  // so main content padding matches the actual console height
  useEffect(() => {
    const el = consoleRef.current
    if (!el) return
    const layout = el.closest('.layout') as HTMLElement | null
    if (!layout) return

    const updateHeight = () => {
      const h = el.getBoundingClientRect().height
      layout.style.setProperty('--log-console-actual-height', `${h}px`)
    }

    updateHeight()
    const ro = new ResizeObserver(updateHeight)
    ro.observe(el)
    return () => ro.disconnect()
  }, [expanded, filteredLogs.length])

  const copyAll = useCallback(async () => {
    const text = logs.map(entryToText).join('\n\n---\n\n')
    try {
      await navigator.clipboard.writeText(text)
    } catch {
      // ignore
    }
  }, [logs])

  const collapsedSummary = lastError
    ? `${lastError.title}${lastError.message ? `: ${lastError.message}` : ''}`
    : t('logConsole.noErrors')

  return (
    <div
      ref={consoleRef}
      className={`workbench-log-console${expanded ? ' expanded' : ' collapsed'}`}
      data-error-count={errorCount}
    >
      <div className="log-console-bar">
        <button
          type="button"
          className="log-console-toggle"
          onClick={() => setExpanded(!expanded)}
          title={expanded ? t('logConsole.collapse') : t('logConsole.expand')}
        >
          {expanded ? <ChevronDown size={16} /> : <ChevronUp size={16} />}
          <span className="log-console-title">{t('logConsole.title')}</span>
          {errorCount > 0 && (
            <span className="log-error-count">{errorCount}</span>
          )}
          {!expanded && (
            <span className="log-collapsed-summary" title={collapsedSummary}>
              {collapsedSummary}
            </span>
          )}
        </button>
        <div className="log-console-actions">
          {expanded && (
            <>
              <div className="log-filter-tabs">
                {FILTERS.map(f => (
                  <button
                    key={f}
                    type="button"
                    className={`log-filter-btn${levelFilter === f ? ' active' : ''}`}
                    onClick={() => setLevelFilter(f)}
                  >
                    {t(`logConsole.filter.${f}`)}
                  </button>
                ))}
              </div>
              <button type="button" className="log-action-btn" onClick={() => void copyAll()} title={t('logConsole.copyAll')}>
                <Copy size={14} />
              </button>
              <button type="button" className="log-action-btn" onClick={clearLogs} title={t('logConsole.clear')}>
                <Trash2 size={14} />
              </button>
              <button type="button" className="log-action-btn" onClick={() => setExpanded(false)} title={t('logConsole.collapse')}>
                <X size={14} />
              </button>
            </>
          )}
        </div>
      </div>
      {expanded && (
        <div className="log-console-panel">
          {filteredLogs.length === 0 ? (
            <div className="log-console-empty">{t('logConsole.empty')}</div>
          ) : (
            filteredLogs.map(entry => <LogEntryRow key={entry.id} entry={entry} />)
          )}
        </div>
      )}
    </div>
  )
}
