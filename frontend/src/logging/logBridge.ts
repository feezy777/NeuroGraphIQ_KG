import type { WorkbenchLogEntry } from './workbenchLogTypes'

export type LogInput = Omit<WorkbenchLogEntry, 'id' | 'timestamp'>

let sink: ((entry: LogInput) => void) | null = null

export function registerWorkbenchLogSink(fn: ((entry: LogInput) => void) | null): void {
  sink = fn
}

export function emitWorkbenchLog(entry: LogInput): void {
  sink?.(entry)
}
