import { useMemo, useState } from 'react'

import { type Column } from '../../components/DataTable'

import { StatusBadge } from '../../components/StatusBadge'

import { CopyButton } from '../../components/CopyButton'

import { useData } from '../../hooks/useData'

import { useI18n } from '../../i18n-context'

import {

  listMirrorCircuitSteps,

  listMirrorProjectionFunctions,

  listMirrorCircuitFunctions,

  listMirrorCircuitProjectionMemberships,

  listCircuitProjectionCrossValidationResults,

  listMirrorDualModelVerificationResults,

  type MirrorCircuitProjectionCrossValidationResult,

  type MirrorDualModelVerificationResult,

} from '../../api/endpoints'

import { DataObjectDetailDrawer } from './DataObjectDetailDrawer'

import { DataCenterTableRegion } from './DataCenterTableRegion'

import { FormalObjectTableSection } from './FormalObjectTableSection'

import { FormalObjectDetailDrawer } from './FormalObjectDetailDrawer'

import { FieldCompletionModal } from './FieldCompletionModal'

import { FormalAlignmentCard } from './FormalAlignmentCard'

import { getFormalFieldMapping } from './formalFieldMappings'

import {

  mergeOverlayPatchIntoRows,

  mergeOverlayPatches,

  type FormalRow,

  type OverlayPatch,

} from './fieldCompletionUtils'

import type { MacroClinicalSubTab } from './dataCenterTypes'



interface Props {

  macroTab: MacroClinicalSubTab

  onMacroTabChange: (tab: MacroClinicalSubTab) => void

  batchId: string

  resourceId: string

  sourceAtlas: string

  granularityLevel: string

  onFilterChange: (patch: Partial<{ batchId: string; resourceId: string; sourceAtlas: string; granularityLevel: string }>) => void

}



type MacroRow = FormalRow



const FORMAL_TABS: MacroClinicalSubTab[] = [

  'circuit_steps',

  'projection_functions',

  'memberships',

  'circuit_functions',

]



const VERIFICATION_TABS: MacroClinicalSubTab[] = ['cross_validation', 'dual_model']



const SUB_TABS: MacroClinicalSubTab[] = [...FORMAL_TABS, ...VERIFICATION_TABS]



const TAB_TO_TYPE = {

  circuit_steps: 'circuit_step',

  projection_functions: 'projection_function',

  memberships: 'circuit_projection_membership',

  circuit_functions: 'circuit_function',

} as const



function isCircuitFunctionsInitError(error: string | null | undefined): boolean {

  return Boolean(error?.includes('MIRROR_CIRCUIT_FUNCTIONS_NOT_INITIALIZED'))

}



export function MacroClinicalDataPanel({

  macroTab,

  onMacroTabChange,

  batchId,

  resourceId,

  sourceAtlas,

  granularityLevel,

  onFilterChange,

}: Props) {

  const { t } = useI18n()

  const [tick, setTick] = useState(0)

  const [selected, setSelected] = useState<MacroRow | null>(null)

  const [legacySelected, setLegacySelected] = useState<MacroRow | null>(null)

  const [detailCompletionOpen, setDetailCompletionOpen] = useState(false)

  const [overlayPatch, setOverlayPatch] = useState<OverlayPatch>({})

  const [circuitId, setCircuitId] = useState('')

  const [functionDomain, setFunctionDomain] = useState('')

  const [functionRole, setFunctionRole] = useState('')



  const formalMapping = macroTab in TAB_TO_TYPE

    ? getFormalFieldMapping(TAB_TO_TYPE[macroTab as keyof typeof TAB_TO_TYPE])

    : undefined



  const refresh = () => setTick(x => x + 1)



  const handleCompletionDone = (patch?: OverlayPatch) => {

    if (patch && Object.keys(patch).length > 0) {

      setOverlayPatch(prev => mergeOverlayPatches(prev, patch))

    }

    refresh()

  }



  const baseParams = useMemo(() => ({

    batch_id: batchId || undefined,

    resource_id: resourceId || undefined,

    source_atlas: sourceAtlas || undefined,

    granularity_level: granularityLevel || undefined,

    limit: 100,

  }), [batchId, resourceId, sourceAtlas, granularityLevel])



  const circuitFunctionParams = useMemo(() => ({

    ...baseParams,

    circuit_id: circuitId || undefined,

    function_domain: functionDomain || undefined,

    function_role: functionRole || undefined,

  }), [baseParams, circuitId, functionDomain, functionRole])



  const { data: stepsData, loading: stepsLoading, error: stepsError } = useData(

    () => listMirrorCircuitSteps(baseParams),

    [JSON.stringify(baseParams), tick, macroTab],

  )

  const { data: pfData, loading: pfLoading, error: pfError } = useData(

    () => listMirrorProjectionFunctions(baseParams),

    [JSON.stringify(baseParams), tick, macroTab],

  )

  const { data: memData, loading: memLoading, error: memError } = useData(

    () => listMirrorCircuitProjectionMemberships(baseParams),

    [JSON.stringify(baseParams), tick, macroTab],

  )

  const { data: cfData, loading: cfLoading, error: cfError } = useData(

    () => listMirrorCircuitFunctions(circuitFunctionParams),

    [JSON.stringify(circuitFunctionParams), tick, macroTab],

  )

  const { data: cvData, loading: cvLoading, error: cvError } = useData(

    () => listCircuitProjectionCrossValidationResults(baseParams),

    [JSON.stringify(baseParams), tick, macroTab],

  )

  const { data: dmData, loading: dmLoading, error: dmError } = useData(

    () => listMirrorDualModelVerificationResults(baseParams),

    [JSON.stringify(baseParams), tick, macroTab],

  )



  const labels: Record<MacroClinicalSubTab, string> = {

    circuit_steps: 'Circuit Steps',

    projection_functions: 'Projection Functions',

    memberships: 'Circuit-Projection Memberships',

    circuit_functions: t('dataCenter.circuitFunctions'),

    cross_validation: 'Cross Validation Results',

    dual_model: 'Dual-Model Results',

  }



  const cvCols: Column<MirrorCircuitProjectionCrossValidationResult>[] = [

    { key: 'id', header: 'id', render: r => <code>{r.id.slice(0, 12)}…</code> },

    { key: 'circuit_id', header: 'circuit_id' },

    { key: 'projection_id', header: 'projection_id' },

    { key: 'validation_status', header: 'validation', render: r => <StatusBadge status={r.validation_status ?? 'unknown'} /> },

  ]



  const dmCols: Column<MirrorDualModelVerificationResult>[] = [

    { key: 'id', header: 'id', render: r => <code>{r.id.slice(0, 12)}…</code> },

    { key: 'object_type', header: 'object_type' },

    { key: 'object_id', header: 'object_id' },

    { key: 'consensus_status', header: 'consensus', render: r => <StatusBadge status={r.consensus_status ?? 'unknown'} /> },

  ]



  const resetKeys = [macroTab, batchId, resourceId, sourceAtlas, granularityLevel, circuitId, functionDomain, functionRole, tick]



  const formalTabState = {

    circuit_steps: { items: (stepsData?.items ?? []) as unknown as MacroRow[], loading: stepsLoading, error: stepsError },

    projection_functions: { items: (pfData?.items ?? []) as unknown as MacroRow[], loading: pfLoading, error: pfError },

    memberships: { items: (memData?.items ?? []) as unknown as MacroRow[], loading: memLoading, error: memError },

    circuit_functions: { items: (cfData?.items ?? []) as unknown as MacroRow[], loading: cfLoading, error: cfError },

  } as const



  const circuitFunctionsInitError = isCircuitFunctionsInitError(formalTabState.circuit_functions.error)



  const displayStepItems = useMemo(

    () => mergeOverlayPatchIntoRows(formalTabState.circuit_steps.items, overlayPatch),

    [formalTabState.circuit_steps.items, overlayPatch],

  )

  const displayPfItems = useMemo(

    () => mergeOverlayPatchIntoRows(formalTabState.projection_functions.items, overlayPatch),

    [formalTabState.projection_functions.items, overlayPatch],

  )

  const displayMemItems = useMemo(

    () => mergeOverlayPatchIntoRows(formalTabState.memberships.items, overlayPatch),

    [formalTabState.memberships.items, overlayPatch],

  )

  const displayCfItems = useMemo(

    () => mergeOverlayPatchIntoRows(formalTabState.circuit_functions.items, overlayPatch),

    [formalTabState.circuit_functions.items, overlayPatch],

  )



  const displaySelected = useMemo(

    () => (selected ? mergeOverlayPatchIntoRows([selected], overlayPatch)[0] : null),

    [selected, overlayPatch],

  )



  return (

    <div className="data-center-panel data-center-formal-tabs">

      <div className="data-center-boundary data-center-boundary-macro">

        {t('dataCenter.boundaryMacro')}

      </div>

      <p className="data-center-formal-aligned-label">{t('dataCenter.formalAligned')}</p>

      <div className="data-center-subtabbar">

        {SUB_TABS.map(st => (

          <button key={st} type="button"

            className={`data-center-tab${macroTab === st ? ' data-center-tab-active' : ''}`}

            onClick={() => onMacroTabChange(st)}>

            {labels[st]}

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

        {macroTab === 'circuit_functions' && (

          <>

            <input className="form-input" placeholder="circuit_id" value={circuitId}

              onChange={e => setCircuitId(e.target.value)} />

            <input className="form-input" placeholder={t('dataCenter.functionDomain')} value={functionDomain}

              onChange={e => setFunctionDomain(e.target.value)} />

            <input className="form-input" placeholder={t('dataCenter.functionRole')} value={functionRole}

              onChange={e => setFunctionRole(e.target.value)} />

          </>

        )}

        <button type="button" className="btn" onClick={refresh}>{t('dataCenter.refresh')}</button>

        <a className="btn" href="#/llm-extraction?tab=macroClinical">{t('dataCenter.viewInWorkflow')}</a>

        <a className="btn" href="#/rule-validation">{t('dataCenter.openValidation')}</a>

        <a className="btn" href="#/human-review">{t('dataCenter.openReview')}</a>

      </div>



      {macroTab === 'circuit_steps' && formalMapping && (

        <FormalObjectTableSection

          key="circuit_steps"

          mapping={formalMapping}

          items={displayStepItems}

          resetKeys={resetKeys}

          loading={formalTabState.circuit_steps.loading}

          error={formalTabState.circuit_steps.error}

          emptyText={t('dataCenter.noData')}

          onOpenDetail={setSelected}

          onRefresh={handleCompletionDone}

        />

      )}

      {macroTab === 'projection_functions' && formalMapping && (

        <FormalObjectTableSection

          key="projection_functions"

          mapping={formalMapping}

          items={displayPfItems}

          resetKeys={resetKeys}

          loading={formalTabState.projection_functions.loading}

          error={formalTabState.projection_functions.error}

          emptyText={t('dataCenter.noData')}

          onOpenDetail={setSelected}

          onRefresh={handleCompletionDone}

        />

      )}

      {macroTab === 'memberships' && formalMapping && (

        <FormalObjectTableSection

          key="memberships"

          mapping={formalMapping}

          items={displayMemItems}

          resetKeys={resetKeys}

          loading={formalTabState.memberships.loading}

          error={formalTabState.memberships.error}

          emptyText={t('dataCenter.noData')}

          onOpenDetail={setSelected}

          onRefresh={handleCompletionDone}

        />

      )}



      {macroTab === 'circuit_functions' && formalMapping && circuitFunctionsInitError && (

        <div className="data-center-formal-table">

          <FormalAlignmentCard mapping={formalMapping} items={[]} />

          <div className="data-center-init-warning">

            <p>{t('dataCenter.mirrorCircuitFunctionsNotInitialized')}</p>

            <p className="data-center-migration-hint">{t('dataCenter.runCircuitFunctionMigration')}</p>

            <code>backend/migrations/033_mirror_circuit_functions.sql</code>

          </div>

        </div>

      )}

      {macroTab === 'circuit_functions' && formalMapping && !circuitFunctionsInitError && (

        <FormalObjectTableSection

          key="circuit_functions"

          mapping={formalMapping}

          items={displayCfItems}

          resetKeys={resetKeys}

          loading={formalTabState.circuit_functions.loading}

          error={formalTabState.circuit_functions.error}

          emptyText={t('dataCenter.noData')}

          onOpenDetail={setSelected}

          onRefresh={handleCompletionDone}

        />

      )}



      {macroTab === 'cross_validation' && (

        <DataCenterTableRegion

          key="cross_validation"

          items={cvData?.items ?? []}

          resetKeys={resetKeys}

          columns={cvCols}

          loading={cvLoading}

          error={cvError}

          emptyText={t('dataCenter.noData')}

          getKey={r => r.id}

          onRowClick={r => setLegacySelected(r as unknown as MacroRow)}

        />

      )}

      {macroTab === 'dual_model' && (

        <DataCenterTableRegion

          key="dual_model"

          items={dmData?.items ?? []}

          resetKeys={resetKeys}

          columns={dmCols}

          loading={dmLoading}

          error={dmError}

          emptyText={t('dataCenter.noData')}

          getKey={r => r.id}

          onRowClick={r => setLegacySelected(r as unknown as MacroRow)}

        />

      )}



      <FormalObjectDetailDrawer

        open={Boolean(selected)}

        row={displaySelected}

        mapping={formalMapping ?? null}

        onClose={() => setSelected(null)}

        onFieldCompletion={() => setDetailCompletionOpen(true)}

      />



      {formalMapping && selected && (

        <FieldCompletionModal

          open={detailCompletionOpen}

          mapping={formalMapping}

          selectedObjects={[selected]}

          selectedIds={[selected.id]}

          onClose={() => setDetailCompletionOpen(false)}

          onCompleted={handleCompletionDone}

        />

      )}



      <DataObjectDetailDrawer

        open={Boolean(legacySelected)}

        title={legacySelected ? String(legacySelected.id).slice(0, 24) : ''}

        subtitle={macroTab}

        fields={legacySelected ? Object.entries(legacySelected).slice(0, 20).map(([label, value]) => ({

          label,

          value: typeof value === 'object' ? JSON.stringify(value) : String(value ?? ''),

        })) : []}

        onClose={() => setLegacySelected(null)}

        actions={legacySelected && (

          <>

            <CopyButton value={legacySelected.id} label={t('dataCenter.copyId')} />

            <a className="btn" href="#/llm-extraction?tab=macroClinical">{t('dataCenter.viewInWorkflow')}</a>

          </>

        )}

      />

    </div>

  )

}


