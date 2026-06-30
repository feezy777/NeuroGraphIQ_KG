import { useMemo, useState, useCallback } from 'react'
import { useData } from '../../hooks/useData'
import { useI18n } from '../../i18n-context'
import {
  listMirrorConnections,
  listMirrorFunctions,
  listMirrorCircuits,
  listMirrorTriples,
  listMirrorEvidence,
  updateMirrorConnection,
  deleteMirrorConnection,
  updateMirrorFunction,
  deleteMirrorFunction,
  updateMirrorCircuit,
  deleteMirrorCircuit,
} from '../../api/endpoints'
import { FormalObjectTableSection } from './FormalObjectTableSection'
import { FormalObjectDetailDrawer } from './FormalObjectDetailDrawer'
import { FieldCompletionModal } from './FieldCompletionModal'
import { MultiTargetFieldCompletionModal } from './MultiTargetFieldCompletionModal'
import { resolveCircuitBundleFromCircuitIds } from './circuitBundleUtils'
import type { CircuitBundleFieldCompletionGroup } from './circuitBundleTypes'
import { getFormalFieldMapping } from './formalFieldMappings'
import {
  mergeOverlayPatchIntoRows,
  mergeOverlayPatches,
  type FormalRow,
  type OverlayPatch,
} from './fieldCompletionUtils'
import type { MirrorKgSubTab } from './dataCenterTypes'

interface Props {
  mirrorTab: MirrorKgSubTab
  onMirrorTabChange: (tab: MirrorKgSubTab) => void
  batchId: string
  resourceId: string
  sourceAtlas: string
  granularityLevel: string
  onFilterChange: (patch: Partial<{ batchId: string; resourceId: string; sourceAtlas: string; granularityLevel: string }>) => void
}

const SUB_TABS: MirrorKgSubTab[] = ['connections', 'functions', 'circuits', 'triples', 'evidence']

const TAB_TO_TYPE = {
  connections: 'projection',
  functions: 'region_function',
  circuits: 'circuit',
  triples: 'triple',
  evidence: 'evidence',
} as const

export function MirrorKgPanel({
  mirrorTab,
  onMirrorTabChange,
  batchId,
  resourceId,
  sourceAtlas,
  granularityLevel,
  onFilterChange,
}: Props) {
  const { t } = useI18n()
  const [tick, setTick] = useState(0)
  const [selected, setSelected] = useState<FormalRow | null>(null)
  const [detailCompletionOpen, setDetailCompletionOpen] = useState(false)
  const [bundleOpen, setBundleOpen] = useState(false)
  const [bundleLoading, setBundleLoading] = useState(false)
  const [circuitBundle, setCircuitBundle] = useState<CircuitBundleFieldCompletionGroup | null>(null)
  const [bundleWarnings, setBundleWarnings] = useState<string[]>([])
  const [overlayPatch, setOverlayPatch] = useState<OverlayPatch>({})

  const mapping = getFormalFieldMapping(TAB_TO_TYPE[mirrorTab])
  const refresh = () => setTick(x => x + 1)

  const handleSaveField = useCallback(async (rowId: string, field: string, value: unknown) => {
    const body = { [field]: value }
    try {
      if (mirrorTab === 'connections') await updateMirrorConnection(rowId, body)
      else if (mirrorTab === 'functions') await updateMirrorFunction(rowId, body)
      else if (mirrorTab === 'circuits') await updateMirrorCircuit(rowId, body)
      refresh()
    } catch (e) {
      console.error('Failed to update mirror object', e)
    }
  }, [mirrorTab])

  const handleDeleteRow = useCallback(async (rowId: string) => {
    try {
      if (mirrorTab === 'connections') await deleteMirrorConnection(rowId)
      else if (mirrorTab === 'functions') await deleteMirrorFunction(rowId)
      else if (mirrorTab === 'circuits') await deleteMirrorCircuit(rowId)
      refresh()
    } catch (e) {
      console.error('Failed to delete mirror object', e)
    }
  }, [mirrorTab])

  const handleBulkDelete = useCallback(async (ids: string[]) => {
    const deleteFn = mirrorTab === 'connections' ? deleteMirrorConnection
      : mirrorTab === 'functions' ? deleteMirrorFunction
      : mirrorTab === 'circuits' ? deleteMirrorCircuit
      : null
    if (!deleteFn) return
    try {
      for (const id of ids) await deleteFn(id)
      refresh()
    } catch (e) {
      console.error('Failed to bulk delete', e)
    }
  }, [mirrorTab])

  const handleCompletionDone = (patch?: OverlayPatch) => {
    if (patch && Object.keys(patch).length > 0) {
      setOverlayPatch(prev => mergeOverlayPatches(prev, patch))
    }
    refresh()
  }

  // Always load all data (limit=0 = unlimited on backend)
  const baseParams = useMemo(() => ({
    batch_id: batchId || undefined,
    resource_id: resourceId || undefined,
    source_atlas: sourceAtlas || undefined,
    granularity_level: granularityLevel || undefined,
    limit: 0,
  }), [batchId, resourceId, sourceAtlas, granularityLevel])

  const resetKeys = [mirrorTab, batchId, resourceId, sourceAtlas, granularityLevel, tick]

  const { data: connData, loading: connLoading, error: connError } = useData(
    () => listMirrorConnections(baseParams),
    [JSON.stringify(baseParams), tick, mirrorTab],
  )
  const { data: funcData, loading: funcLoading, error: funcError } = useData(
    () => listMirrorFunctions(baseParams),
    [JSON.stringify(baseParams), tick, mirrorTab],
  )
  const { data: circData, loading: circLoading, error: circError } = useData(
    () => listMirrorCircuits(baseParams),
    [JSON.stringify(baseParams), tick, mirrorTab],
  )
  const { data: tripleData, loading: tripleLoading, error: tripleError } = useData(
    () => listMirrorTriples(baseParams),
    [JSON.stringify(baseParams), tick, mirrorTab],
  )
  const { data: evData, loading: evLoading, error: evError } = useData(
    () => listMirrorEvidence({ limit: 0 }),
    [tick, mirrorTab],
  )

  const subTabLabels: Record<MirrorKgSubTab, string> = {
    connections: 'Connections / Projections',
    functions: 'Region Functions',
    circuits: 'Circuits',
    triples: 'Triples',
    evidence: 'Evidence',
  }

  const tabState = {
    connections: { items: (connData?.items ?? []) as unknown as FormalRow[], loading: connLoading, error: connError },
    functions: { items: (funcData?.items ?? []) as unknown as FormalRow[], loading: funcLoading, error: funcError },
    circuits: { items: (circData?.items ?? []) as unknown as FormalRow[], loading: circLoading, error: circError },
    triples: { items: (tripleData?.items ?? []) as unknown as FormalRow[], loading: tripleLoading, error: tripleError },
    evidence: { items: (evData?.items ?? []) as unknown as FormalRow[], loading: evLoading, error: evError },
  }[mirrorTab]

  const displayItems = useMemo(
    () => mergeOverlayPatchIntoRows(tabState.items, overlayPatch),
    [tabState.items, overlayPatch],
  )

  const displaySelected = useMemo(
    () => (selected ? mergeOverlayPatchIntoRows([selected], overlayPatch)[0] : null),
    [selected, overlayPatch],
  )

  return (
    <div className="data-center-panel data-center-formal-tabs">
      <div className="data-center-boundary data-center-boundary-mirror">
        {t('dataCenter.boundaryMirror')}
      </div>
      <p className="data-center-formal-aligned-label">{t('dataCenter.formalAligned')}</p>
      <div className="data-center-subtabbar">
        {SUB_TABS.map(st => (
          <button key={st} type="button"
            className={`data-center-tab${mirrorTab === st ? ' data-center-tab-active' : ''}`}
            onClick={() => onMirrorTabChange(st)}>
            {subTabLabels[st]}
          </button>
        ))}
      </div>
      <div className="data-center-filter-bar">
        <input className="form-input" placeholder={t('dataCenter.batch')} value={batchId}
          onChange={e => onFilterChange({ batchId: e.target.value })} />
        <input className="form-input" placeholder={t('dataCenter.resource')} value={resourceId}
          onChange={e => onFilterChange({ resourceId: e.target.value })} />
        <input className="form-input" placeholder={t('dataCenter.atlas')} value={sourceAtlas}
          onChange={e => onFilterChange({ sourceAtlas: e.target.value })} />
        <input className="form-input" placeholder={t('dataCenter.granularity')} value={granularityLevel}
          onChange={e => onFilterChange({ granularityLevel: e.target.value })} />
        <button type="button" className="btn" onClick={refresh}>{t('dataCenter.refresh')}</button>
        <a className="btn" href="#/llm-extraction">{t('dataCenter.viewInWorkflow')}</a>
      </div>

      {mapping && (
        <FormalObjectTableSection
          key={mirrorTab}
          mapping={mapping}
          items={displayItems}
          resetKeys={resetKeys}
          loading={tabState.loading}
          error={tabState.error}
          emptyText={t('dataCenter.noData')}
          pageSize={999999}
          onOpenDetail={setSelected}
          onRefresh={handleCompletionDone}
          onDeleteSelected={handleBulkDelete}
        />
      )}

      <FormalObjectDetailDrawer
        open={Boolean(selected)}
        row={displaySelected}
        mapping={mapping ?? null}
        onClose={() => setSelected(null)}
        onSave={handleSaveField}
        onDelete={handleDeleteRow}
        onRefresh={refresh}
        onFieldCompletion={() => {
          if (mirrorTab === 'circuits' && selected) {
            setBundleOpen(true)
            setBundleLoading(true)
            setCircuitBundle(null)
            setBundleWarnings([])
            void resolveCircuitBundleFromCircuitIds([selected.id], 'data_center')
              .then(({ bundle, warnings }) => {
                setCircuitBundle(bundle)
                setBundleWarnings(warnings)
              })
              .finally(() => setBundleLoading(false))
            return
          }
          setDetailCompletionOpen(true)
        }}
      />

      {mapping && selected && mirrorTab !== 'circuits' && (
        <FieldCompletionModal
          open={detailCompletionOpen}
          mapping={mapping}
          selectedObjects={[selected]}
          selectedIds={[selected.id]}
          onClose={() => setDetailCompletionOpen(false)}
          onCompleted={handleCompletionDone}
        />
      )}

      {mirrorTab === 'circuits' && (
        <MultiTargetFieldCompletionModal
          open={bundleOpen}
          bundle={circuitBundle}
          resolveWarnings={bundleWarnings}
          loading={bundleLoading}
          onClose={() => setBundleOpen(false)}
          onCompleted={handleCompletionDone}
        />
      )}
    </div>
  )
}
