import { useContext } from 'react'
import { WorkbenchLogContext } from './WorkbenchLogContext'

export function useWorkbenchLog() {
  const ctx = useContext(WorkbenchLogContext)
  if (!ctx) {
    throw new Error('useWorkbenchLog must be used within WorkbenchLogProvider')
  }
  return ctx
}
