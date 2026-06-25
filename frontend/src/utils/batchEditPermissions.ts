export function canEditCoreFields(status: string): boolean {
  return status === 'created'
}

export function canEditFiles(status: string): boolean {
  return status === 'created' || status === 'queued'
}

export function canEditDescription(status: string): boolean {
  return status === 'created' || status === 'queued'
}

export function canCancelBatch(status: string): boolean {
  return status === 'created' || status === 'queued' || status === 'running'
}

export function canCloneBatch(status: string): boolean {
  return status !== 'cancelled'
}

export function batchEditDisabledReason(status: string, t: (k: string) => string): string | null {
  if (canEditDescription(status)) return null
  return t('pipeline.batchEditNotAllowedAfterRunning')
}
