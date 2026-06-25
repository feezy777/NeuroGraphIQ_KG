import { CopyButton } from '../CopyButton'

export function BatchShortId({ id, copyTitle }: { id: string; copyTitle?: string }) {
  return (
    <span className="import-batch-id-copy" onClick={e => e.stopPropagation()} onKeyDown={e => e.stopPropagation()}>
      <code>{id.slice(0, 8)}…</code>
      <CopyButton value={id} label="" title={copyTitle} ariaLabel={copyTitle} />
    </span>
  )
}
