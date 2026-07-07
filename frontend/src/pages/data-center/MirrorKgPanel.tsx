import { useEffect, useMemo, useState, useCallback } from 'react'
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
  // Server-side pagination
  const [page, setPage] = useState(1)
  const [pageSize, setPageSize] = useState(200)
  const [serverTotal, setServerTotal] = useState(0)

  const handlePageSizeChange = useCallback((size: number) => {
    setPageSize(size)
    setPage(1)
  }, [])

  // Reset page when tab or filters change
  useEffect(() => { setPage(1) }, [mirrorTab, batchId, resourceId, sourceAtlas, granularityLevel])

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

  const handleFetchAll = useCallback(async (): Promise<FormalRow[]> => {
    const params: Record<string, any> = { limit: 0 }  // 0 = unlimited on backend
    if (batchId) params.batch_id = batchId
    if (resourceId) params.resource_id = resourceId
    if (sourceAtlas) params.source_atlas = sourceAtlas
    if (granularityLevel) params.granularity_level = granularityLevel
    let result: any
    if (mirrorTab === 'connections') result = await listMirrorConnections(params)
    else if (mirrorTab === 'functions') result = await listMirrorFunctions(params)
    else if (mirrorTab === 'circuits') result = await listMirrorCircuits(params)
    else if (mirrorTab === 'triples') result = await listMirrorTriples(params)
    else return []
    const items = result?.items ?? []
    return items.map((item: any) => ({ ...item, id: item.id ?? '' }))
  }, [mirrorTab, batchId, resourceId, sourceAtlas, granularityLevel])

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

  const handleCompletionDone = useCallback((patch?: OverlayPatch) => {
    if (patch && Object.keys(patch).length > 0) {
      setOverlayPatch(prev => mergeOverlayPatches(prev, patch))
    }
    refresh()
  }, [])

  const resetKeys = [mirrorTab, batchId, resourceId, sourceAtlas, granularityLevel, tick]

  // Server-side pagination: compute offset from page
  const offset = useMemo(() => (page - 1) * pageSize, [page, pageSize])

  const baseParams = useMemo(() => ({
    batch_id: batchId || undefined,
    resource_id: resourceId || undefined,
    source_atlas: sourceAtlas || undefined,
    granularity_level: granularityLevel || undefined,
    limit: pageSize,
    offset,
  }), [batchId, resourceId, sourceAtlas, granularityLevel, pageSize, offset])

  const connKey = useMemo(() => `${mirrorTab}-conn-${JSON.stringify(baseParams)}-${tick}`, [mirrorTab, baseParams, tick])
  const funcKey = useMemo(() => `${mirrorTab}-func-${JSON.stringify(baseParams)}-${tick}`, [mirrorTab, baseParams, tick])
  const circKey = useMemo(() => `${mirrorTab}-circ-${JSON.stringify(baseParams)}-${tick}`, [mirrorTab, baseParams, tick])
  const tripleKey = useMemo(() => `${mirrorTab}-triple-${JSON.stringify(baseParams)}-${tick}`, [mirrorTab, baseParams, tick])
  const evKey = useMemo(() => `${mirrorTab}-ev-${tick}-${page}-${pageSize}`, [mirrorTab, tick, page, pageSize])

  // Only fetch the active tab — others stay null until switched
  const { data: connData, loading: connLoading, error: connError } = useData(
    () => mirrorTab === 'connections' ? listMirrorConnections(baseParams) : Promise.resolve(null as any),
    [connKey],
  )
  const { data: funcData, loading: funcLoading, error: funcError } = useData(
    () => mirrorTab === 'functions' ? listMirrorFunctions(baseParams) : Promise.resolve(null as any),
    [funcKey],
  )
  const { data: circData, loading: circLoading, error: circError } = useData(
    () => mirrorTab === 'circuits' ? listMirrorCircuits(baseParams) : Promise.resolve(null as any),
    [circKey],
  )
  const { data: tripleData, loading: tripleLoading, error: tripleError } = useData(
    () => mirrorTab === 'triples' ? listMirrorTriples(baseParams) : Promise.resolve(null as any),
    [tripleKey],
  )
  const { data: evData, loading: evLoading, error: evError } = useData(
    () => mirrorTab === 'evidence' ? listMirrorEvidence({ limit: pageSize, offset }) : Promise.resolve(null as any),
    [evKey],
  )

  // Derive serverTotal from active tab's API response
  const activeTotal = useMemo(() => {
    const data = mirrorTab === 'connections' ? connData
      : mirrorTab === 'functions' ? funcData
      : mirrorTab === 'circuits' ? circData
      : mirrorTab === 'triples' ? tripleData
      : mirrorTab === 'evidence' ? evData
      : null
    return (data as any)?.total ?? 0
  }, [mirrorTab, connData, funcData, circData, tripleData, evData])

  // Keep serverTotal in sync
  useEffect(() => {
    if (activeTotal > 0) setServerTotal(activeTotal)
  }, [activeTotal])

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
          pageSize={pageSize}
          serverTotal={serverTotal}
          serverPage={page}
          onServerPageChange={setPage}
          onOpenDetail={setSelected}
          onRefresh={handleCompletionDone}
          onDeleteSelected={handleBulkDelete}
          onFetchAll={handleFetchAll}
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
