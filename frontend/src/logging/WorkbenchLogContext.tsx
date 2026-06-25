import {
  createContext,
  useCallback,
  useEffect,
  useMemo,
  useState,
  type ReactNode,
} from 'react'
import { registerWorkbenchLogSink } from './logBridge'
import {
  MAX_WORKBENCH_LOGS,
  WORKBENCH_LOG_CONSOLE_EXPANDED_KEY,
  WORKBENCH_LOG_STORAGE_KEY,
  type WorkbenchLogEntry,
  type WorkbenchLogLevelFilter,
} from './workbenchLogTypes'

export type LogInput = Omit<WorkbenchLogEntry, 'id' | 'timestamp'>

function newId(): string {
  return `${Date.now()}-${Math.random().toString(36).slice(2, 9)}`
}

function currentPageHash(): string {
  return typeof window !== 'undefined' ? window.location.hash || '#/' : '#/'
}

function loadPersistedLogs(): WorkbenchLogEntry[] {
  try {
    const raw = localStorage.getItem(WORKBENCH_LOG_STORAGE_KEY)
    if (!raw) return []
    const parsed = JSON.parse(raw) as WorkbenchLogEntry[]
    return Array.isArray(parsed) ? parsed.slice(0, MAX_WORKBENCH_LOGS) : []
  } catch {
    return []
  }
}

function persistLogs(entries: WorkbenchLogEntry[]): void {
  try {
    localStorage.setItem(WORKBENCH_LOG_STORAGE_KEY, JSON.stringify(entries.slice(0, MAX_WORKBENCH_LOGS)))
  } catch {
    // quota or private mode
  }
}

export interface WorkbenchLogContextValue {
  logs: WorkbenchLogEntry[]
  expanded: boolean
  setExpanded: (v: boolean) => void
  levelFilter: WorkbenchLogLevelFilter
  setLevelFilter: (f: WorkbenchLogLevelFilter) => void
  addLog: (entry: LogInput) => void
  clearLogs: () => void
  errorCount: number
  lastError: WorkbenchLogEntry | null
  filteredLogs: WorkbenchLogEntry[]
}

export const WorkbenchLogContext = createContext<WorkbenchLogContextValue | null>(null)

interface WorkbenchLogProviderProps {
  children: ReactNode
  persist?: boolean
}

export function WorkbenchLogProvider({ children, persist = true }: WorkbenchLogProviderProps) {
  const [logs, setLogs] = useState<WorkbenchLogEntry[]>(() => (persist ? loadPersistedLogs() : []))
  const [expanded, setExpandedState] = useState(() => {
    try {
      return localStorage.getItem(WORKBENCH_LOG_CONSOLE_EXPANDED_KEY) === 'true'
    } catch {
      return false
    }
  })
  const [levelFilter, setLevelFilter] = useState<WorkbenchLogLevelFilter>('all')

  const setExpanded = useCallback((v: boolean) => {
    setExpandedState(v)
    try {
      localStorage.setItem(WORKBENCH_LOG_CONSOLE_EXPANDED_KEY, String(v))
    } catch {
      // ignore
    }
  }, [])

  const addLog = useCallback((entry: LogInput) => {
    const full: WorkbenchLogEntry = {
      ...entry,
      id: newId(),
      timestamp: new Date().toISOString(),
      pageHash: entry.pageHash ?? currentPageHash(),
    }
    setLogs(prev => {
      const next = [full, ...prev].slice(0, MAX_WORKBENCH_LOGS)
      if (persist) persistLogs(next)
      return next
    })
  }, [persist])

  const clearLogs = useCallback(() => {
    setLogs([])
    if (persist) {
      try {
        localStorage.removeItem(WORKBENCH_LOG_STORAGE_KEY)
      } catch {
        // ignore
      }
    }
  }, [persist])

  useEffect(() => {
    registerWorkbenchLogSink(addLog)
    return () => registerWorkbenchLogSink(null)
  }, [addLog])

  useEffect(() => {
    const onError = (event: ErrorEvent) => {
      addLog({
        level: 'error',
        source: 'window',
        title: event.message || 'Window error',
        message: event.message,
        errorName: event.error?.name,
        errorMessage: event.message,
        stack: event.error?.stack,
        detail: { filename: event.filename, lineno: event.lineno, colno: event.colno },
        tags: ['window.onerror'],
      })
    }

    const onRejection = (event: PromiseRejectionEvent) => {
      const reason = event.reason
      const message = reason instanceof Error ? reason.message : String(reason ?? 'Unhandled rejection')
      addLog({
        level: 'error',
        source: 'unhandledrejection',
        title: 'Unhandled promise rejection',
        message,
        errorName: reason instanceof Error ? reason.name : undefined,
        errorMessage: message,
        stack: reason instanceof Error ? reason.stack : undefined,
        detail: reason,
        tags: ['unhandledrejection'],
      })
    }

    window.addEventListener('error', onError)
    window.addEventListener('unhandledrejection', onRejection)
    return () => {
      window.removeEventListener('error', onError)
      window.removeEventListener('unhandledrejection', onRejection)
    }
  }, [addLog])

  const errorCount = useMemo(() => logs.filter(l => l.level === 'error').length, [logs])
  const lastError = useMemo(() => logs.find(l => l.level === 'error') ?? null, [logs])

  const filteredLogs = useMemo(() => {
    if (levelFilter === 'all') return logs
    if (levelFilter === 'request') return logs.filter(l => l.source === 'api')
    return logs.filter(l => l.level === levelFilter)
  }, [logs, levelFilter])

  const value = useMemo<WorkbenchLogContextValue>(() => ({
    logs,
    expanded,
    setExpanded,
    levelFilter,
    setLevelFilter,
    addLog,
    clearLogs,
    errorCount,
    lastError,
    filteredLogs,
  }), [logs, expanded, setExpanded, levelFilter, addLog, clearLogs, errorCount, lastError, filteredLogs])

  return (
    <WorkbenchLogContext.Provider value={value}>
      {children}
    </WorkbenchLogContext.Provider>
  )
}
