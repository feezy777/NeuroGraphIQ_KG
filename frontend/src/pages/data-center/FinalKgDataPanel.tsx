import { useMemo, useState } from 'react'
import { type Column } from '../../components/DataTable'
import { DataCenterTableRegion } from './DataCenterTableRegion'
import { StatusBadge } from '../../components/StatusBadge'
import { CopyButton } from '../../components/CopyButton'
import { useData } from '../../hooks/useData'
import { useI18n } from '../../i18n-context'
import {
  listFinalMacroClinicalObjects,
  getFinalMacroClinicalObject,
  type FinalMacroClinicalObject,
} from '../../api/endpoints'
import { DataObjectDetailDrawer } from './DataObjectDetailDrawer'
import type { FinalKgSubTab } from './dataCenterTypes'

interface Props {
  finalTab: FinalKgSubTab
  onFinalTabChange: (tab: FinalKgSubTab) => void
}

const SUB_TABS: FinalKgSubTab[] = [
  'circuit',
  'circuit_step',
  'projection',
  'projection_function',
  'membership',
  'region_function',
  'circuit_function',
  'triple',
  'evidence',
]

const TAB_TO_TARGET: Record<FinalKgSubTab, string> = {
  circuit: 'circuit',
  circuit_step: 'circuit_step',
  projection: 'projection',
  projection_function: 'projection_function',
  membership: 'circuit_projection_membership',
  region_function: 'region_function',
  circuit_function: 'circuit_function',
  triple: 'triple',
  evidence: 'evidence',
}

const TAB_LABELS: Record<FinalKgSubTab, string> = {
  circuit: 'Final Circuits',
  circuit_step: 'Final Circuit Steps',
  projection: 'Final Projections',
  projection_function: 'Final Projection Functions',
  membership: 'Final Memberships',
  region_function: 'Final Region Functions',
  circuit_function: 'Final Circuit Functions',
  triple: 'Final Triples',
  evidence: 'Final Evidence',
}

export function FinalKgDataPanel({ finalTab, onFinalTabChange }: Props) {
  const { t } = useI18n()
  const [tick, setTick] = useState(0)
  const [selected, setSelected] = useState<FinalMacroClinicalObject | null>(null)
  const [detailLoading, setDetailLoading] = useState(false)
  const [detailExtra, setDetailExtra] = useState<Record<string, unknown> | null>(null)

  const targetType = TAB_TO_TARGET[finalTab]

  const { data, loading, error } = useData(
    () => listFinalMacroClinicalObjects(targetType, { limit: 100 }),
    [targetType, tick],
  )

  const columns = useMemo<Column<FinalMacroClinicalObject>[]>(() => [
    { key: 'id', header: 'final_id', render: r => <code>{r.id.slice(0, 12)}…</code> },
    { key: 'label', header: 'label', render: r => r.label ?? '—' },
    { key: 'final_status', header: t('dataCenter.status'), render: r => <StatusBadge status={r.final_status} /> },
    { key: 'source_mirror_id', header: 'source_mirror_id', render: r => r.source_mirror_id ? <code>{r.source_mirror_id.slice(0, 10)}…</code> : '—' },
    { key: 'source_atlas', header: t('dataCenter.atlas'), render: r => r.source_atlas ?? '—' },
    { key: 'created_at', header: 'created', render: r => r.created_at?.slice(0, 10) ?? '—' },
  ], [t])

  async function openDetail(row: FinalMacroClinicalObject) {
    setSelected(row)
    setDetailExtra(null)
    setDetailLoading(true)
    try {
      const detail = await getFinalMacroClinicalObject(targetType, row.id)
      setDetailExtra(detail as unknown as Record<string, unknown>)
    } catch {
      setDetailExtra(null)
    } finally {
      setDetailLoading(false)
    }
  }

  return (
    <div className="data-center-panel">
      <div className="data-center-boundary data-center-boundary-final">
        {t('dataCenter.boundaryFinal')}
      </div>
      <div className="data-center-subtabbar">
        {SUB_TABS.map(st => (
          <button key={st} type="button"
            className={`data-center-tab${finalTab === st ? ' data-center-tab-active' : ''}`}
            onClick={() => onFinalTabChange(st)}>
            {TAB_LABELS[st]}
          </button>
        ))}
      </div>
      <div className="data-center-filter-bar">
        <button type="button" className="btn" onClick={() => setTick(x => x + 1)}>{t('dataCenter.refresh')}</button>
        <a className="btn" href="#/llm-extraction?tab=finalBrowser">{t('dataCenter.openFinalBrowser')}</a>
        <a className="btn" href="#/llm-extraction?tab=finalExport">{t('dataCenter.openFinalExport')}</a>
      </div>
      <DataCenterTableRegion
        key={finalTab}
        items={data?.items ?? []}
        resetKeys={[finalTab, tick]}
        columns={columns}
        loading={loading}
        error={error}
        emptyText={t('dataCenter.noData')}
        getKey={r => r.id}
        onRowClick={openDetail}
      />

      <DataObjectDetailDrawer
        open={Boolean(selected)}
        title={selected?.label ?? selected?.id ?? ''}
        subtitle={finalTab}
        fields={[
          { label: 'final_id', value: selected?.id },
          { label: 'source_mirror_id', value: selected?.source_mirror_id },
          { label: 'final_status', value: selected?.final_status },
          { label: 'source_atlas', value: selected?.source_atlas },
          { label: 'granularity_level', value: selected?.granularity_level },
          ...(detailExtra ? Object.entries(detailExtra).slice(0, 12).map(([label, value]) => ({
            label,
            value: typeof value === 'object' ? JSON.stringify(value) : String(value ?? ''),
          })) : []),
          ...(detailLoading ? [{ label: '…', value: 'loading' }] : []),
        ]}
        onClose={() => { setSelected(null); setDetailExtra(null) }}
        actions={selected && (
          <>
            <CopyButton value={selected.id} label={t('dataCenter.copyFinalId')} />
            {selected.source_mirror_id && (
              <CopyButton value={selected.source_mirror_id} label={t('dataCenter.copySourceMirrorId')} />
            )}
            <a className="btn" href="#/llm-extraction?tab=finalBrowser">{t('dataCenter.openFinalBrowser')}</a>
          </>
        )}
      />
    </div>
  )
}
