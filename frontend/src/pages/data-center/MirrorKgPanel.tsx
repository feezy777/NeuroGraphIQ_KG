import { useEffect, useMemo, useState, useCallback } from 'react'
import { useData } from '../../hooks/useData'
import { useI18n } from '../../i18n-context'
import {
  listMirrorConnections,
  listMirrorFunctions,
  listMirrorCircuits,
  listMirrorTriples,
  listMirrorEvidence,
  listMirrorProjectionFunctions,
  listMirrorCircuitSteps,
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

// Sub-tabs under each parent tab: { key, label, formalObjectType, listApi }
const SUB_ITEM_DEFS: Record<MirrorKgSubTab, { key: string; label: string; type: string; listApi: (p: any) => Promise<any> }[]> = {
  connections: [
    { key: 'self', label: '连接自身', type: 'projection', listApi: listMirrorConnections },
    { key: 'projection_functions', label: '投影功能', type: 'projection_function', listApi: listMirrorProjectionFunctions },
  ],
  functions: [
    { key: 'self', label: '功能自身', type: 'region_function', listApi: listMirrorFunctions },
  ],
  circuits: [
    { key: 'self', label: '回路自身', type: 'circuit', listApi: listMirrorCircuits },
    { key: 'circuit_steps', label: '步骤', type: 'circuit_step', listApi: listMirrorCircuitSteps },
  ],
  triples: [
    { key: 'self', label: '三元组自身', type: 'triple', listApi: listMirrorTriples },
  ],
  evidence: [
    { key: 'self', label: '证据自身', type: 'evidence', listApi: listMirrorEvidence },
  ],
}

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
  const [page, setPage] = useState(1)
  const [pageSize, setPageSize] = useState(200)
  const [serverTotal, setServerTotal] = useState(0)
  // Sub-tab index within the current parent tab
  const [subIdx, setSubIdx] = useState(0)

  const subDefs = SUB_ITEM_DEFS[mirrorTab]
  const activeSub = subDefs[subIdx] ?? subDefs[0]
  const mapping = getFormalFieldMapping(activeSub.type)
  const refresh = () => setTick(x => x + 1)

  // Reset sub-tab and page when parent tab changes
  useEffect(() => { setSubIdx(0); setPage(1) }, [mirrorTab])

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
    const params: Record<string, any> = { limit: 5000 }  // max backend limit, covers all
    const result = await activeSub.listApi(params)
    const items = result?.items ?? []
    return items.map((item: any) => ({ ...item, id: item.id ?? '' }))
  }, [activeSub])

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

  const resetKeys = [activeSub.key, tick]

  const offset = useMemo(() => (page - 1) * pageSize, [page, pageSize])

  const baseParams = useMemo(() => ({
    limit: pageSize,
    offset,
  }), [pageSize, offset])

  // Data key changes when sub-tab or page or tick changes
  const dataKey = useMemo(
    () => `${mirrorTab}-${activeSub.key}-${JSON.stringify(baseParams)}-${tick}`,
    [mirrorTab, activeSub.key, baseParams, tick],
  )

  const { data: tableData, loading, error } = useData(
    () => activeSub.listApi(baseParams),
    [dataKey],
  )

  const rawItems = (tableData?.items ?? []) as unknown as FormalRow[]
  const activeTotal = (tableData as any)?.total ?? 0

  useEffect(() => {
    if (activeTotal > 0) setServerTotal(activeTotal)
  }, [activeTotal])

  const displayItems = useMemo(
    () => mergeOverlayPatchIntoRows(rawItems, overlayPatch),
    [rawItems, overlayPatch],
  )

  const displaySelected = useMemo(
    () => (selected ? mergeOverlayPatchIntoRows([selected], overlayPatch)[0] : null),
    [selected, overlayPatch],
  )

  const subTabLabels: Record<MirrorKgSubTab, string> = {
    connections: 'Connections / Projections',
    functions: 'Region Functions',
    circuits: 'Circuits',
    triples: 'Triples',
    evidence: 'Evidence',
  }

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

      {/* Sub-sub-tabs */}
      <div className="data-center-subtabbar" style={{ marginTop: 4 }}>
        {subDefs.map((def, i) => (
          <button key={def.key} type="button"
            className={`data-center-tab${i === subIdx ? ' data-center-tab-active' : ''}`}
            onClick={() => { setSubIdx(i); setPage(1); }}>
            {def.label}
          </button>
        ))}
      </div>

      {mapping && (
        <FormalObjectTableSection
          key={`${mirrorTab}-${activeSub.key}`}
          mapping={mapping}
          items={displayItems}
          resetKeys={resetKeys}
          loading={loading}
          error={error}
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
