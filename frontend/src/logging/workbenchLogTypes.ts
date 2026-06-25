export type WorkbenchLogLevel = 'debug' | 'info' | 'warning' | 'error'

export type WorkbenchLogSource =
  | 'api'
  | 'frontend'
  | 'window'
  | 'unhandledrejection'
  | 'user-action'
  | 'system'

export type WorkbenchLogEntry = {
  id: string
  timestamp: string
  level: WorkbenchLogLevel
  source: WorkbenchLogSource
  title: string
  message?: string
  method?: string
  url?: string
  status?: number
  statusText?: string
  requestBodyPreview?: unknown
  responseBody?: unknown
  errorName?: string
  errorMessage?: string
  stack?: string
  detail?: unknown
  requestId?: string | null
  pageHash?: string
  tags?: string[]
}

export type WorkbenchLogLevelFilter = WorkbenchLogLevel | 'all' | 'request'

export const MAX_WORKBENCH_LOGS = 200
export const WORKBENCH_LOG_STORAGE_KEY = 'neurographiq.workbench.logs'
export const WORKBENCH_LOG_CONSOLE_EXPANDED_KEY = 'neurographiq.workbench.logConsoleExpanded'
