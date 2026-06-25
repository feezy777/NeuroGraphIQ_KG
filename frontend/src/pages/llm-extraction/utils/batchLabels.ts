import type { ImportBatch } from '../../../api/endpoints'

export function shortBatchId(id: string): string {
  return id.length > 8 ? `${id.slice(0, 8)}…` : id
}

function formatCreatedDate(iso: string | null | undefined): string | null {
  if (!iso) return null
  try {
    return new Date(iso).toLocaleDateString()
  } catch {
    return null
  }
}

/** Human-readable batch label; batch_id is never the primary display text. */
export function formatImportBatchLabel(
  batch: Pick<ImportBatch, 'id' | 'batch_code' | 'description' | 'remark' | 'parser_key' | 'created_at'>,
  candidateCount?: number,
): string {
  const name =
    batch.description?.trim()
    || batch.batch_code?.trim()
    || batch.remark?.trim()
    || (batch.parser_key ? `${batch.parser_key}` : null)
    || (formatCreatedDate(batch.created_at) ? `${formatCreatedDate(batch.created_at)} · ${shortBatchId(batch.id)}` : null)

  let label = name || `未命名批次 · ${shortBatchId(batch.id)}`
  if (candidateCount != null && candidateCount >= 0) {
    label = `${label}（${candidateCount}）`
  }
  return label
}

export function formatUnknownBatchLabel(batchId: string, candidateCount?: number): string {
  let label = `当前批次 · ${shortBatchId(batchId)}`
  if (candidateCount != null && candidateCount >= 0) {
    label = `${label}（${candidateCount}）`
  }
  return label
}
