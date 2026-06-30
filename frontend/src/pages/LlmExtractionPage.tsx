import React, { useState, useCallback, useMemo, useEffect, useRef } from 'react'
import { ChevronLeft, Sparkles, AlertTriangle } from 'lucide-react'
import { PageHeader } from '../components/PageHeader'
import { DataTable, type Column } from '../components/DataTable'
import { StatusBadge } from '../components/StatusBadge'
import { KeyValuePanel } from '../components/KeyValuePanel'
import { ActionButton } from '../components/ActionButton'
import { ConfirmDialog } from '../components/ConfirmDialog'
import { Notice, type NoticeState } from '../components/Notice'
import { LoadingState, ErrorState, EmptyState } from '../components/States'
import { CopyButton } from '../components/CopyButton'
import { useData } from '../hooks/useData'
import { useSessionScope } from './llm-extraction/hooks/useSessionScope'
import { MacroPipelineCard } from './llm-extraction/tabs/macro/MacroPipelineCard'
import { MacroPipelineOverview } from './llm-extraction/tabs/macro/MacroPipelineOverview'
import { useMacroClinicalPipelineProgress } from './llm-extraction/tabs/macro/useMacroClinicalPipelineProgress'
import type { MacroPipelineStepId } from './llm-extraction/tabs/macro/macroClinicalPipelineTypes'
import { GovernanceDashboard } from './llm-extraction/tabs/governance/GovernanceDashboard'
import type { GovernanceGateId } from './llm-extraction/tabs/governance/governanceTypes'
import { DataFirstCandidatesTab } from './llm-extraction/components/DataFirstCandidatesTab'
import { LlmTaskToolbar } from './llm-extraction/components/LlmTaskToolbar'
import { FinalLinksPanel } from './llm-extraction/components/FinalLinksPanel'
import { MirrorExtractionPanel } from './llm-extraction/components/MirrorExtractionPanel'
import { ExtractionResultPanel } from './llm-extraction/components/ExtractionResultPanel'
import { EXTRACTION_TYPE_CONFIGS } from './llm-extraction/types/extractionConfig'
import { ExtractionRunModal } from './llm-extraction/components/ExtractionRunModal'
import { logCompositeProgressSnapshot, resetExtractionLogDedup } from './llm-extraction/services/llmExtractionLogBridge'
import { emitWorkbenchLog } from '../logging/logBridge'
import { useWorkbenchLog } from '../logging/useWorkbenchLog'
import { CircuitToFunctionsPendingBanner } from './llm-extraction/components/CircuitToFunctionsPendingBanner'
import { formatExtractionApiError } from './llm-extraction/utils/formatExtractionApiError'
import { FieldCompletionTab } from './llm-extraction/components/FieldCompletionTab'
import { QuickExtractionCards } from './llm-extraction/components/QuickExtractionCards'
import { PoolExtractionModal } from './llm-extraction/components/PoolExtractionModal'
import { useCandidatePool, type PoolScope, PoolSetupError } from './llm-extraction/hooks/useCandidatePool'
import {
  type LlmDataTabId,
  type MirrorSubTabId,
  parseLlmDataTab,
  parseMirrorSubTab,
  isCompositeTask,
  type CompositeTaskId,
} from './llm-extraction/llmDataFirstTypes'
import {
  runCompositeExtractionTask,
  COMPOSITE_TASK_SUBSTEP_LABELS,
  COMPOSITE_TASK_LABELS,
  type CompositeSubstepResult,
  type CompositeExtractionResult,
  type CompositeProgressMeta,
  type CompositeExtractionTaskId,
} from './llm-extraction/services/compositeExtractionRunner'
import {
  fetchCandidates,
  fetchLlmExtractionOptions,
  fetchCandidateLlmExtractions,
  extractCandidate,
  extractCandidatesBatch,
  listLlmProviders,
  listLlmTaskTypes,
  listLlmExtractionRuns,
  listLlmExtractionItems,
  runRegionFieldCompletion,
  runSameGranularityConnectionExtraction,
  runSameGranularityFunctionExtraction,
  runSameGranularityCircuitExtraction,
  runCircuitToStepsExtraction,
  runCircuitStepsToProjectionsExtraction,
  runProjectionToFunctionsExtraction,
  runProjectionsToCircuitsExtraction,
  runCircuitProjectionCrossValidation,
  runDualModelVerification,
  listDualModelVerificationExecutionRuns,
  listDualModelVerificationExecutionResults,
  listCircuitProjectionCrossValidationRuns,
  listCircuitProjectionCrossValidationResults,
  listMirrorConnections,
  listMirrorFunctions,
  listMirrorCircuits,
  getMirrorCircuit,
  consolidateMirrorTriples,
  listMirrorTriples,
  runMirrorValidation,
  listMirrorValidationRuns,
  listMirrorValidationResults,
  listMirrorReviewQueue,
  getMirrorReviewDetail,
  submitMirrorReviewAction,
  listMirrorReviewTargetTypes,
  runFinalMacroClinicalPromotion,
  listFinalMacroClinicalPromotionRuns,
  listFinalMacroClinicalPromotionRecords,
  listFinalMacroClinicalObjects,
  searchFinalKgObjects,
  getFinalRegionNeighborhood,
  getFinalCircuitDetail,
  getFinalProjectionDetail,
  getFinalObjectDetail,
  type FinalMacroClinicalPromotionRequest,
  type FinalMacroClinicalPromotionResponse,
  type FinalMacroClinicalPromotionRecordPreview,
  type FinalMacroClinicalPromotionRun,
  type FinalMacroClinicalObject,
  type FinalBrowserSearchItem,
  type FinalBrowserSearchResponse,
  type FinalRegionNeighborhoodResponse,
  type FinalCircuitDetailResponse,
  type FinalProjectionDetailResponse,
  type FinalObjectDetailResponse,
  type FinalGraphResponse,
  type FinalGraphNode,
  type FinalGraphEdge,
  type FinalProvenancePayload,
  runFinalKgExport,
  listFinalKgExports,
  listFinalKgExportFiles,
  getFinalKgExportManifest,
  getFinalKgExportFileUrl,
  type FinalKgExportRequest,
  type FinalKgExportPreviewResponse,
  type FinalKgExportRunResponse,
  type FinalKgExportManifestRead,
  type FinalKgExportFileRead,
  previewMirrorPromotion,
  runMirrorPromotion,
  listMirrorPromotionRuns,
  listFinalConnections,
  listFinalFunctions,
  listFinalCircuits,
  listFinalTriples,
  listMirrorCircuitSteps,
  listMirrorProjectionFunctions,
  listMirrorCircuitProjectionMemberships,
  listMirrorDualModelVerificationRuns,
  listMirrorDualModelVerificationResults,
  type CandidateBrainRegion,
  type MirrorRegionConnection,
  type MirrorRegionFunction,
  type MirrorRegionCircuit,
  type MirrorKgTriple,
  type SameGranularityConnectionExtractionResponse,
  type SameGranularityFunctionExtractionResponse,
  type SameGranularityCircuitExtractionResponse,
  type CircuitToStepsExtractionResponse,
  type CircuitStepsToProjectionsExtractionResponse,
  type ProjectionToFunctionsExtractionResponse,
  type ProjectionsToCircuitsExtractionResponse,
  type CircuitProjectionCrossValidationResponse,
  type CircuitProjectionCrossValidationResultPreview,
  type MirrorCircuitProjectionCrossValidationRun,
  type MirrorCircuitProjectionCrossValidationResult,
  type DualModelVerificationResponse,
  type DualModelVerificationResultPreview,
  type MirrorTripleConsolidationResponse,
  type MirrorTriplePreviewItem,
  type MirrorValidationResponse,
  type MirrorValidationTargetType,
  type MirrorValidationResultPreview,
  type MirrorValidationRun,
  type MirrorValidationResult,
  type MirrorReviewQueueItem,
  type MirrorReviewDetail,
  type MirrorReviewActionResponse,
  type MirrorReviewTargetTypeInfo,
  type MirrorReviewActionType,
  type MirrorPromotionPreviewItem,
  type MirrorPromotionResponse,
  type MirrorPromotionRun,
  type FinalRegionConnection,
  type FinalRegionFunction,
  type FinalRegionCircuit,
  type FinalKgTriple as FinalKgTripleRow,
  type MirrorCircuitRegion,
  type MirrorCircuitStep,
  type MirrorProjectionFunction,
  type MirrorCircuitProjectionMembership,
  type MirrorDualModelVerificationRun,
  type MirrorDualModelVerificationResult,
  type LlmExtraction,
  type LlmSuggestion,
  type LlmExtractionRun,
  type LlmExtractionItem,
  type LlmProviderInfo,
  cancelCompositeWorkflow,
} from '../api/endpoints'
import { ApiError } from '../api/client'
import { readSessionIds } from '../hooks/useSessionIds'
import { useI18n } from '../i18n-context'

const STATUS_OPTIONS = [
  'candidate_created', 'rule_validating', 'rule_passed', 'rule_failed',
  'llm_not_required', 'llm_validating', 'llm_passed', 'llm_conflict',
  'manual_review_pending', 'manual_approved',
]

type TabId = 'region' | 'runs' | 'items' | 'connections' | 'functions' | 'circuits' | 'triples' | 'macroClinical' | 'validation' | 'review' | 'promotion' | 'finalPromotion' | 'finalBrowser' | 'finalExport'

function AdvisoryBanner() {
  const { t } = useI18n()
  return (
    <div className="llm-safety-note" style={{ display: 'flex', alignItems: 'flex-start', gap: 8, marginBottom: 16 }}>
      <AlertTriangle size={16} style={{ flexShrink: 0, marginTop: 1 }} />
      <span>{t('llmExtraction.advisory')}</span>
    </div>
  )
}

function MacroClinicalSchemaReadinessCard() {
  const { t } = useI18n()
  return (
    <details className="macro-clinical-readiness-card card" open>
      <summary>{t('mirror.macroClinical.schemaReadiness')}</summary>
      <p className="macro-clinical-alignment-body">{t('mirror.macroClinical.description')}</p>
      <ul className="macro-clinical-mapping-list">
        <li>mirror_circuit_steps</li>
        <li>mirror_projection_functions</li>
        <li>mirror_circuit_projection_memberships</li>
        <li>mirror_dual_model_verification_runs</li>
        <li>mirror_dual_model_verification_results</li>
      </ul>
      <p className="macro-clinical-schema-only">{t('mirror.macroClinical.schemaOnlyWarning')}</p>
      <p className="macro-clinical-alignment-note">{t('mirror.macroClinical.connectionAsProjectionNote')}</p>
    </details>
  )
}

function CircuitToStepsWorkbench({ onRefreshSteps }: { onRefreshSteps: () => void }) {
  const { t } = useI18n()
  const sess = readSessionIds()
  const f = useMirrorFilters()
  const [circuitTick, setCircuitTick] = useState(0)
  const [selectedCircuitId, setSelectedCircuitId] = useState<string | null>(null)
  const [circuitSearch, setCircuitSearch] = useState('')
  const [provider, setProvider] = useState('deepseek')
  const [modelName, setModelName] = useState('')
  const [maxSteps, setMaxSteps] = useState(12)
  const [includeCircuitRegions, setIncludeCircuitRegions] = useState(true)
  const [createMirrorSteps, setCreateMirrorSteps] = useState(true)
  const [dryRun, setDryRun] = useState(false)
  const [batchFilter, setBatchFilter] = useState(sess.batch_id ?? '')
  const [resourceFilter, setResourceFilter] = useState('')
  const [running, setRunning] = useState(false)
  const [notice, setNotice] = useState<NoticeState | null>(null)
  const [result, setResult] = useState<CircuitToStepsExtractionResponse | null>(null)
  const [showPrompt, setShowPrompt] = useState(false)

  const { data: providersData } = useData(() => listLlmProviders(), [])
  const providers = providersData?.providers ?? []
  const currentProvider = providers.find(p => p.name === provider)

  useEffect(() => {
    if (currentProvider && !modelName) setModelName(currentProvider.default_model)
  }, [currentProvider, modelName])

  const circuitParams = useMemo(() => ({
    source_atlas: f.applied.sourceAtlas || undefined,
    granularity_level: f.applied.granularity || undefined,
    batch_id: batchFilter || undefined,
    resource_id: resourceFilter || undefined,
    limit: 100,
  }), [f.applied, batchFilter, resourceFilter, circuitTick])

  const { data: circuitsData, loading: circuitsLoading, error: circuitsError } = useData(
    () => listMirrorCircuits(circuitParams),
    [circuitParams],
  )
  const circuits = (circuitsData?.items ?? []).filter(c => {
    if (!circuitSearch.trim()) return true
    const q = circuitSearch.toLowerCase()
    return c.circuit_name.toLowerCase().includes(q) || c.id.toLowerCase().includes(q)
  })

  const validate = (): string | null => {
    if (!selectedCircuitId) return t('mirror.macroClinical.circuitRequired')
    if (maxSteps < 2 || maxSteps > 30) return t('mirror.macroClinical.maxSteps') + ': 2–30'
    return null
  }

  const runExtraction = async (previewOnly: boolean) => {
    const err = validate()
    if (err) {
      setNotice({ type: 'error', message: err })
      return
    }
    setRunning(true)
    setNotice(null)
    try {
      const resp = await runCircuitToStepsExtraction({
        provider,
        model_name: modelName || undefined,
        circuit_id: selectedCircuitId!,
        dry_run: previewOnly,
        max_steps: maxSteps,
        include_circuit_regions: includeCircuitRegions,
        create_mirror_records: createMirrorSteps,
      })
      setResult(resp)
      setShowPrompt(previewOnly)
      if (!previewOnly && resp.status === 'succeeded') {
        onRefreshSteps()
        setCircuitTick(x => x + 1)
      }
      setNotice({
        type: resp.warnings?.length ? 'warning' : 'success',
        message: previewOnly ? t('mirror.macroClinical.previewPrompt') : t('mirror.macroClinical.runCircuitToSteps'),
      })
    } catch (e) {
      setNotice({ type: 'error', message: String(e) })
    } finally {
      setRunning(false)
    }
  }

  const circuitCols: Column<MirrorRegionCircuit>[] = useMemo(() => [
    {
      key: 'select',
      header: '',
      render: r => (
        <input
          type="radio"
          name="circuit-to-steps-select"
          checked={selectedCircuitId === r.id}
          onChange={() => setSelectedCircuitId(r.id)}
        />
      ),
    },
    { key: 'id', header: 'circuit_id', render: r => <code className="text-mono" style={{ fontSize: 11 }}>{r.id.slice(0, 10)}…</code> },
    { key: 'circuit_name', header: t('mirror.circuitName'), render: r => r.circuit_name },
    { key: 'circuit_type', header: t('mirror.circuitType'), render: r => r.circuit_type },
    { key: 'function_association', header: 'function', render: r => r.function_association ?? '—' },
    { key: 'confidence', header: t('mirror.confidence'), render: r => <ConfidenceCell value={r.confidence} /> },
    { key: 'mirror_status', header: t('mirror.mirrorStatus'), render: r => <StatusBadge status={r.mirror_status} /> },
    { key: 'review_status', header: t('mirror.reviewStatus'), render: r => <StatusBadge status={r.review_status} /> },
    { key: 'source_atlas', header: 'atlas', render: r => r.source_atlas },
    { key: 'granularity', header: 'granularity', render: r => r.granularity_level },
    { key: 'created_at', header: t('mirror.createdAt'), render: r => r.created_at.slice(0, 19).replace('T', ' ') },
  ], [t, selectedCircuitId])

  return (
    <div className="circuit-to-steps-workbench">
      <h3 className="panel-title">{t('mirror.macroClinical.circuitToSteps')}</h3>
      <p className="macro-clinical-alignment-body">{t('mirror.macroClinical.circuitToStepsDescription')}</p>
      <div className="circuit-to-steps-warning">{t('mirror.macroClinical.stepsMirrorOnlyWarning')}</div>
      <div className="circuit-to-steps-warning">{t('mirror.macroClinical.notFinalWarning')}</div>
      <div className="circuit-to-steps-warning">{t('mirror.macroClinical.notKgWarning')}</div>
      {!dryRun && !currentProvider?.configured && (
        <div className="circuit-to-steps-warning">{t('llm.providerNotConfigured')}</div>
      )}
      {notice && <Notice notice={notice} onClose={() => setNotice(null)} />}
      <div className="circuit-to-steps-control-panel card">
        <label>
          Provider
          <select value={provider} onChange={e => setProvider(e.target.value)}>
            <option value="deepseek">DeepSeek</option>
            <option value="kimi">Kimi</option>
          </select>
        </label>
        <label>
          Model
          <input value={modelName} onChange={e => setModelName(e.target.value)} />
        </label>
        <label>
          {t('mirror.macroClinical.maxSteps')}
          <input type="number" min={2} max={30} value={maxSteps} onChange={e => setMaxSteps(Number(e.target.value))} />
        </label>
        <label className="checkbox-label">
          <input type="checkbox" checked={includeCircuitRegions} onChange={e => setIncludeCircuitRegions(e.target.checked)} />
          {t('mirror.macroClinical.includeCircuitRegions')}
        </label>
        <label className="checkbox-label">
          <input type="checkbox" checked={createMirrorSteps} onChange={e => setCreateMirrorSteps(e.target.checked)} />
          {t('mirror.macroClinical.createMirrorSteps')}
        </label>
        <label className="checkbox-label">
          <input type="checkbox" checked={dryRun} onChange={e => setDryRun(e.target.checked)} />
          dry_run
        </label>
        <div className="filter-bar">
          <input className="filter-input" placeholder="resource_id" value={resourceFilter} onChange={e => setResourceFilter(e.target.value)} />
          <input className="filter-input" placeholder="batch_id" value={batchFilter} onChange={e => setBatchFilter(e.target.value)} />
          <input className="filter-input" placeholder={t('mirror.macroClinical.selectCircuit')} value={circuitSearch} onChange={e => setCircuitSearch(e.target.value)} />
        </div>
        <div className="action-row">
          <ActionButton label={t('mirror.macroClinical.previewPrompt')} onClick={() => runExtraction(true)} disabled={running} />
          <ActionButton
            label={t('mirror.macroClinical.runCircuitToSteps')}
            onClick={() => runExtraction(false)}
            disabled={running || (!dryRun && !currentProvider?.configured)}
            loading={running}
            variant="primary"
          />
          <ActionButton label={t('common.refresh')} onClick={() => { setCircuitTick(x => x + 1); onRefreshSteps() }} />
        </div>
      </div>
      <div className="circuit-to-steps-circuit-table card">
        <DataTable
          columns={circuitCols}
          rows={circuits}
          loading={circuitsLoading}
          error={circuitsError}
          total={circuitsData?.total}
          getKey={r => r.id}
          emptyText={t('mirror.macroClinical.selectCircuit')}
        />
      </div>
      {result && (
        <div className="circuit-to-steps-result-card card">
          <div className="card-title">{t('mirror.macroClinical.circuitToSteps')}</div>
          {result.run_id && <div>run_id: <code>{result.run_id}</code></div>}
          {result.item_id && <div>item_id: <code>{result.item_id}</code></div>}
          {result.input_region_count != null && <div>{t('mirror.macroClinical.inputRegionCount')}: {result.input_region_count}</div>}
          {result.step_count != null && <div>{t('mirror.macroClinical.stepCount')}: {result.step_count}</div>}
          {result.mirror_step_created_count != null && <div>{t('mirror.macroClinical.mirrorStepCreatedCount')}: {result.mirror_step_created_count}</div>}
          {result.mirror_step_skipped_duplicate_count != null && (
            <div>{t('mirror.macroClinical.mirrorStepSkippedDuplicateCount')}: {result.mirror_step_skipped_duplicate_count}</div>
          )}
          {result.warnings?.map((w, i) => <div key={i} className="circuit-to-steps-warning">{w}</div>)}
          {(result.system_prompt || result.user_prompt) && (
            <details className="circuit-to-steps-prompt-preview" open={showPrompt}>
              <summary>{t('mirror.macroClinical.previewPrompt')}</summary>
              {result.system_prompt && <pre>{result.system_prompt}</pre>}
              {result.user_prompt && <pre>{result.user_prompt}</pre>}
            </details>
          )}
        </div>
      )}
    </div>
  )
}

function CircuitStepsToProjectionsWorkbench({
  onRefreshAll,
}: {
  onRefreshAll: () => void
}) {
  const { t } = useI18n()
  const sess = readSessionIds()
  const f = useMirrorFilters()
  const [circuitTick, setCircuitTick] = useState(0)
  const [selectedCircuitId, setSelectedCircuitId] = useState<string | null>(null)
  const [provider, setProvider] = useState('deepseek')
  const [modelName, setModelName] = useState('')
  const [maxProjections, setMaxProjections] = useState(20)
  const [includeExisting, setIncludeExisting] = useState(true)
  const [createMirror, setCreateMirror] = useState(true)
  const [createMemberships, setCreateMemberships] = useState(true)
  const [createTriples, setCreateTriples] = useState(true)
  const [createEvidence, setCreateEvidence] = useState(true)
  const [dryRun, setDryRun] = useState(false)
  const [batchFilter, setBatchFilter] = useState(sess.batch_id ?? '')
  const [resourceFilter, setResourceFilter] = useState('')
  const [running, setRunning] = useState(false)
  const [notice, setNotice] = useState<NoticeState | null>(null)
  const [result, setResult] = useState<CircuitStepsToProjectionsExtractionResponse | null>(null)
  const [showPrompt, setShowPrompt] = useState(false)

  const { data: providersData } = useData(() => listLlmProviders(), [])
  const providers = providersData?.providers ?? []
  const currentProvider = providers.find(p => p.name === provider)

  useEffect(() => {
    if (currentProvider && !modelName) setModelName(currentProvider.default_model)
  }, [currentProvider, modelName])

  const circuitParams = useMemo(() => ({
    source_atlas: f.applied.sourceAtlas || undefined,
    granularity_level: f.applied.granularity || undefined,
    batch_id: batchFilter || undefined,
    resource_id: resourceFilter || undefined,
    limit: 100,
  }), [f.applied, batchFilter, resourceFilter, circuitTick])

  const { data: circuitsData, loading: circuitsLoading, error: circuitsError } = useData(
    () => listMirrorCircuits(circuitParams),
    [circuitParams],
  )
  const circuits = circuitsData?.items ?? []

  const { data: stepsData, loading: stepsLoading } = useData(
    () => selectedCircuitId
      ? listMirrorCircuitSteps({ circuit_id: selectedCircuitId, limit: 100 })
      : Promise.resolve({ items: [], total: 0, limit: 100, offset: 0 }),
    [selectedCircuitId],
  )
  const circuitSteps = (stepsData?.items ?? []).sort((a, b) => a.step_order - b.step_order)

  const validate = (): string | null => {
    if (!selectedCircuitId) return t('mirror.macroClinical.circuitRequired')
    if (circuitSteps.length < 2) return t('mirror.macroClinical.needAtLeastTwoSteps')
    if (maxProjections < 1 || maxProjections > 100) return t('mirror.macroClinical.maxProjections') + ': 1–100'
    if (createMemberships && !createMirror) return t('mirror.macroClinical.membershipRequiresProjection')
    return null
  }

  const runExtraction = async (previewOnly: boolean) => {
    const err = validate()
    if (err) {
      setNotice({ type: 'error', message: err })
      return
    }
    setRunning(true)
    setNotice(null)
    try {
      const resp = await runCircuitStepsToProjectionsExtraction({
        provider,
        model_name: modelName || undefined,
        circuit_id: selectedCircuitId!,
        dry_run: previewOnly,
        max_projections: maxProjections,
        include_existing_projections: includeExisting,
        create_mirror_records: createMirror,
        create_memberships: createMemberships,
        create_triples: createTriples,
        create_evidence: createEvidence,
      })
      setResult(resp)
      setShowPrompt(previewOnly)
      if (!previewOnly && resp.status === 'succeeded') {
        onRefreshAll()
        setCircuitTick(x => x + 1)
      }
      setNotice({
        type: resp.warnings?.length ? 'warning' : 'success',
        message: previewOnly
          ? t('mirror.macroClinical.previewPrompt')
          : t('mirror.macroClinical.runCircuitStepsToProjections'),
      })
    } catch (e) {
      setNotice({ type: 'error', message: String(e) })
    } finally {
      setRunning(false)
    }
  }

  const circuitCols: Column<MirrorRegionCircuit>[] = useMemo(() => [
    {
      key: 'select',
      header: '',
      render: r => (
        <input
          type="radio"
          name="circuit-steps-to-projections-select"
          checked={selectedCircuitId === r.id}
          onChange={() => setSelectedCircuitId(r.id)}
        />
      ),
    },
    { key: 'id', header: 'circuit_id', render: r => <code className="text-mono" style={{ fontSize: 11 }}>{r.id.slice(0, 10)}…</code> },
    { key: 'circuit_name', header: t('mirror.circuitName'), render: r => r.circuit_name },
    { key: 'source_atlas', header: 'atlas', render: r => r.source_atlas },
    { key: 'granularity', header: 'granularity', render: r => r.granularity_level },
  ], [t, selectedCircuitId])

  const stepPreviewCols: Column<MirrorCircuitStep>[] = useMemo(() => [
    { key: 'step_order', header: t('mirror.macroClinical.stepOrder'), render: r => r.step_order },
    { key: 'step_name', header: t('mirror.macroClinical.stepName'), render: r => r.step_name },
    { key: 'step_type', header: t('mirror.macroClinical.stepType'), render: r => r.step_type },
    { key: 'role', header: t('mirror.macroClinical.role'), render: r => r.role },
    { key: 'region_candidate_id', header: 'region', render: r => r.region_candidate_id?.slice(0, 8) ?? '—' },
    { key: 'confidence', header: t('mirror.confidence'), render: r => <ConfidenceCell value={r.confidence} /> },
  ], [t])

  return (
    <div className="circuit-steps-to-projections-workbench">
      <h3 className="panel-title">{t('mirror.macroClinical.circuitStepsToProjections')}</h3>
      <p className="macro-clinical-alignment-body">{t('mirror.macroClinical.circuitStepsToProjectionsDescription')}</p>
      <div className="circuit-steps-to-projections-warning">{t('mirror.macroClinical.projectionMirrorOnlyWarning')}</div>
      <div className="circuit-steps-to-projections-warning">{t('mirror.macroClinical.membershipMeaning')}</div>
      <div className="circuit-steps-to-projections-warning">{t('mirror.macroClinical.notFinalWarning')}</div>
      <div className="circuit-steps-to-projections-warning">{t('mirror.macroClinical.notKgWarning')}</div>
      {!dryRun && !currentProvider?.configured && (
        <div className="circuit-steps-to-projections-warning">{t('llm.providerNotConfigured')}</div>
      )}
      {notice && <Notice notice={notice} onClose={() => setNotice(null)} />}
      <div className="circuit-steps-to-projections-control-panel card">
        <label>Provider
          <select value={provider} onChange={e => setProvider(e.target.value)}>
            <option value="deepseek">DeepSeek</option>
            <option value="kimi">Kimi</option>
          </select>
        </label>
        <label>Model
          <input value={modelName} onChange={e => setModelName(e.target.value)} />
        </label>
        <label>{t('mirror.macroClinical.maxProjections')}
          <input type="number" min={1} max={100} value={maxProjections} onChange={e => setMaxProjections(Number(e.target.value))} />
        </label>
        <label className="checkbox-label">
          <input type="checkbox" checked={includeExisting} onChange={e => setIncludeExisting(e.target.checked)} />
          {t('mirror.macroClinical.includeExistingProjections')}
        </label>
        <label className="checkbox-label">
          <input type="checkbox" checked={createMirror} onChange={e => setCreateMirror(e.target.checked)} />
          {t('mirror.macroClinical.createMirrorProjections')}
        </label>
        <label className="checkbox-label">
          <input type="checkbox" checked={createMemberships} onChange={e => setCreateMemberships(e.target.checked)} />
          {t('mirror.macroClinical.createMemberships')}
        </label>
        <label className="checkbox-label">
          <input type="checkbox" checked={createTriples} onChange={e => setCreateTriples(e.target.checked)} />
          {t('mirror.macroClinical.createProjectionTriples')}
        </label>
        <label className="checkbox-label">
          <input type="checkbox" checked={createEvidence} onChange={e => setCreateEvidence(e.target.checked)} />
          {t('mirror.macroClinical.createProjectionEvidence')}
        </label>
        <label className="checkbox-label">
          <input type="checkbox" checked={dryRun} onChange={e => setDryRun(e.target.checked)} />
          dry_run
        </label>
        <div className="filter-bar">
          <input className="filter-input" placeholder="resource_id" value={resourceFilter} onChange={e => setResourceFilter(e.target.value)} />
          <input className="filter-input" placeholder="batch_id" value={batchFilter} onChange={e => setBatchFilter(e.target.value)} />
        </div>
        <div className="action-row">
          <ActionButton label={t('mirror.macroClinical.previewPrompt')} onClick={() => runExtraction(true)} disabled={running} />
          <ActionButton
            label={t('mirror.macroClinical.runCircuitStepsToProjections')}
            onClick={() => runExtraction(false)}
            disabled={running || (!dryRun && !currentProvider?.configured)}
            loading={running}
            variant="primary"
          />
          <ActionButton label={t('common.refresh')} onClick={() => { setCircuitTick(x => x + 1); onRefreshAll() }} />
        </div>
      </div>
      <div className="circuit-to-steps-circuit-table card">
        <DataTable columns={circuitCols} rows={circuits} loading={circuitsLoading} error={circuitsError} total={circuitsData?.total} getKey={r => r.id} emptyText={t('mirror.macroClinical.selectCircuit')} />
      </div>
      {selectedCircuitId && (
        <div className="circuit-steps-preview-table card">
          <div className="card-title">{t('mirror.macroClinical.stepPreview')} ({circuitSteps.length})</div>
          <DataTable columns={stepPreviewCols} rows={circuitSteps} loading={stepsLoading} getKey={r => r.id} emptyText={t('mirror.macroClinical.needAtLeastTwoSteps')} />
        </div>
      )}
      {result && (
        <div className="circuit-steps-to-projections-result-card card">
          <div className="card-title">{t('mirror.macroClinical.circuitStepsToProjections')}</div>
          {result.run_id && <div>run_id: <code>{result.run_id}</code></div>}
          {result.item_id && <div>item_id: <code>{result.item_id}</code></div>}
          {result.input_step_count != null && <div>{t('mirror.macroClinical.inputStepCount')}: {result.input_step_count}</div>}
          {result.projection_count != null && <div>{t('mirror.macroClinical.projectionCount')}: {result.projection_count}</div>}
          {result.mirror_projection_created_count != null && <div>{t('mirror.macroClinical.mirrorProjectionCreatedCount')}: {result.mirror_projection_created_count}</div>}
          {result.mirror_projection_skipped_duplicate_count != null && (
            <div>{t('mirror.macroClinical.mirrorProjectionSkippedDuplicateCount')}: {result.mirror_projection_skipped_duplicate_count}</div>
          )}
          {result.membership_created_count != null && <div>{t('mirror.macroClinical.membershipCreatedCount')}: {result.membership_created_count}</div>}
          {result.membership_skipped_duplicate_count != null && (
            <div>{t('mirror.macroClinical.membershipSkippedDuplicateCount')}: {result.membership_skipped_duplicate_count}</div>
          )}
          {result.triple_created_count != null && <div>{t('mirror.macroClinical.tripleCreatedCount')}: {result.triple_created_count}</div>}
          {result.evidence_created_count != null && <div>{t('mirror.macroClinical.evidenceCreatedCount')}: {result.evidence_created_count}</div>}
          {result.warnings?.map((w, i) => <div key={i} className="circuit-steps-to-projections-warning">{w}</div>)}
          {(result.system_prompt || result.user_prompt) && (
            <details className="circuit-steps-to-projections-prompt-preview" open={showPrompt}>
              <summary>{t('mirror.macroClinical.previewPrompt')}</summary>
              {result.system_prompt && <pre>{result.system_prompt}</pre>}
              {result.user_prompt && <pre>{result.user_prompt}</pre>}
            </details>
          )}
        </div>
      )}
    </div>
  )
}

function ProjectionToFunctionsWorkbench({
  onRefreshAll,
}: {
  onRefreshAll: () => void
}) {
  const { t } = useI18n()
  const sess = readSessionIds()
  const f = useMirrorFilters()
  const [projTick, setProjTick] = useState(0)
  const [selectedProjectionIds, setSelectedProjectionIds] = useState<string[]>([])
  const [projectionSearch, setProjectionSearch] = useState('')
  const [provider, setProvider] = useState('deepseek')
  const [modelName, setModelName] = useState('')
  const [maxFunctionsPerProjection, setMaxFunctionsPerProjection] = useState(5)
  const [includeCircuitContext, setIncludeCircuitContext] = useState(true)
  const [includeRegionContext, setIncludeRegionContext] = useState(true)
  const [createMirror, setCreateMirror] = useState(true)
  const [createTriples, setCreateTriples] = useState(true)
  const [createEvidence, setCreateEvidence] = useState(true)
  const [dryRun, setDryRun] = useState(false)
  const [batchFilter, setBatchFilter] = useState(sess.batch_id ?? '')
  const [resourceFilter, setResourceFilter] = useState('')
  const [running, setRunning] = useState(false)
  const [notice, setNotice] = useState<NoticeState | null>(null)
  const [result, setResult] = useState<ProjectionToFunctionsExtractionResponse | null>(null)
  const [showPrompt, setShowPrompt] = useState(false)

  const { data: providersData } = useData(() => listLlmProviders(), [])
  const providers = providersData?.providers ?? []
  const currentProvider = providers.find(p => p.name === provider)

  useEffect(() => {
    if (currentProvider && !modelName) setModelName(currentProvider.default_model)
  }, [currentProvider, modelName])

  const projectionParams = useMemo(() => ({
    source_atlas: f.applied.sourceAtlas || undefined,
    granularity_level: f.applied.granularity || undefined,
    batch_id: batchFilter || undefined,
    resource_id: resourceFilter || undefined,
    limit: 100,
  }), [f.applied, batchFilter, resourceFilter, projTick])

  const { data: projectionsData, loading: projectionsLoading, error: projectionsError } = useData(
    () => listMirrorConnections(projectionParams),
    [projectionParams],
  )
  const projections = useMemo(() => {
    const items = projectionsData?.items ?? []
    const q = projectionSearch.trim().toLowerCase()
    if (!q) return items
    return items.filter(p =>
      p.id.toLowerCase().includes(q)
      || (p.source_region_candidate_id ?? '').toLowerCase().includes(q)
      || (p.target_region_candidate_id ?? '').toLowerCase().includes(q)
      || p.connection_type.toLowerCase().includes(q),
    )
  }, [projectionsData, projectionSearch])

  const selectedProjections = useMemo(
    () => projections.filter(p => selectedProjectionIds.includes(p.id)),
    [projections, selectedProjectionIds],
  )

  const { data: membershipData } = useData(
    () => listMirrorCircuitProjectionMemberships({
      ...projectionParams,
      limit: 200,
    }),
    [projectionParams, selectedProjectionIds.join(',')],
  )
  const membershipPreview = useMemo(() => {
    const ids = new Set(selectedProjectionIds)
    return (membershipData?.items ?? []).filter(m => ids.has(m.projection_id))
  }, [membershipData, selectedProjectionIds])

  const toggleProjection = (id: string) => {
    setSelectedProjectionIds(prev =>
      prev.includes(id) ? prev.filter(x => x !== id) : [...prev, id],
    )
  }

  const validate = (): string | null => {
    if (selectedProjectionIds.length === 0) return t('mirror.macroClinical.needAtLeastOneProjection')
    if (selectedProjectionIds.length > 30) return t('mirror.macroClinical.tooManyProjections')
    if (maxFunctionsPerProjection < 1 || maxFunctionsPerProjection > 10) {
      return t('mirror.macroClinical.maxFunctionsPerProjection') + ': 1–10'
    }
    const atlases = new Set(selectedProjections.map(p => p.source_atlas))
    if (atlases.size > 1) return t('mirror.macroClinical.projectionsMustSameAtlas')
    const granularities = new Set(selectedProjections.map(p => p.granularity_level))
    if (granularities.size > 1) return t('mirror.macroClinical.projectionsMustSameGranularity')
    return null
  }

  const runExtraction = async (previewOnly: boolean) => {
    const err = validate()
    if (err) {
      setNotice({ type: 'error', message: err })
      return
    }
    setRunning(true)
    setNotice(null)
    try {
      const resp = await runProjectionToFunctionsExtraction({
        provider,
        model_name: modelName || undefined,
        projection_ids: selectedProjectionIds,
        dry_run: previewOnly,
        max_functions_per_projection: maxFunctionsPerProjection,
        include_circuit_context: includeCircuitContext,
        include_region_context: includeRegionContext,
        create_mirror_records: createMirror,
        create_triples: createTriples,
        create_evidence: createEvidence,
      })
      setResult(resp)
      setShowPrompt(previewOnly)
      if (!previewOnly && resp.status === 'succeeded') {
        onRefreshAll()
        setProjTick(x => x + 1)
      }
      setNotice({
        type: resp.warnings?.length ? 'warning' : 'success',
        message: previewOnly
          ? t('mirror.macroClinical.previewPrompt')
          : t('mirror.macroClinical.projectionToFunctions'),
      })
    } catch (e) {
      setNotice({ type: 'error', message: String(e) })
    } finally {
      setRunning(false)
    }
  }

  const projectionCols: Column<MirrorRegionConnection>[] = useMemo(() => [
    {
      key: 'select',
      header: '',
      render: r => (
        <input
          type="checkbox"
          checked={selectedProjectionIds.includes(r.id)}
          onChange={() => toggleProjection(r.id)}
        />
      ),
    },
    { key: 'id', header: 'projection_id', render: r => <code className="text-mono" style={{ fontSize: 11 }}>{r.id.slice(0, 10)}…</code> },
    { key: 'source', header: 'source region', render: r => r.source_region_candidate_id?.slice(0, 8) ?? '—' },
    { key: 'target', header: 'target region', render: r => r.target_region_candidate_id?.slice(0, 8) ?? '—' },
    { key: 'connection_type', header: 'type', render: r => r.connection_type },
    { key: 'directionality', header: 'direction', render: r => r.directionality },
    { key: 'confidence', header: t('mirror.confidence'), render: r => <ConfidenceCell value={r.confidence} /> },
    { key: 'source_atlas', header: 'atlas', render: r => r.source_atlas },
    { key: 'granularity_level', header: 'granularity', render: r => r.granularity_level },
    { key: 'mirror_status', header: t('mirror.mirrorStatus'), render: r => <StatusBadge status={r.mirror_status} /> },
    { key: 'review_status', header: t('mirror.reviewStatus'), render: r => <StatusBadge status={r.review_status} /> },
    { key: 'created_at', header: t('mirror.createdAt'), render: r => r.created_at.slice(0, 19).replace('T', ' ') },
  ], [t, selectedProjectionIds])

  const membershipPreviewCols: Column<MirrorCircuitProjectionMembership>[] = useMemo(() => [
    { key: 'projection_id', header: 'projection_id', render: r => r.projection_id.slice(0, 8) },
    { key: 'circuit_id', header: 'circuit_id', render: r => r.circuit_id.slice(0, 8) },
    { key: 'role_in_circuit', header: t('mirror.macroClinical.roleInCircuit'), render: r => r.role_in_circuit },
    { key: 'verification_status', header: t('mirror.macroClinical.verificationStatus'), render: r => r.verification_status },
  ], [t])

  return (
    <div className="projection-to-functions-workbench">
      <h3 className="panel-title">{t('mirror.macroClinical.projectionToFunctions')}</h3>
      <p className="macro-clinical-alignment-body">{t('mirror.macroClinical.projectionToFunctionsDescription')}</p>
      <div className="projection-to-functions-warning">{t('mirror.macroClinical.projectionFunctionMirrorOnlyWarning')}</div>
      {!dryRun && !currentProvider?.configured && (
        <div className="projection-to-functions-warning">{t('llm.providerNotConfigured')}</div>
      )}
      {notice && <Notice notice={notice} onClose={() => setNotice(null)} />}
      <div className="projection-to-functions-control-panel card">
        <label>Provider
          <select value={provider} onChange={e => setProvider(e.target.value)}>
            <option value="deepseek">DeepSeek</option>
            <option value="kimi">Kimi</option>
          </select>
        </label>
        <label>Model
          <input value={modelName} onChange={e => setModelName(e.target.value)} />
        </label>
        <label>{t('mirror.macroClinical.maxFunctionsPerProjection')}
          <input type="number" min={1} max={10} value={maxFunctionsPerProjection} onChange={e => setMaxFunctionsPerProjection(Number(e.target.value))} />
        </label>
        <label className="checkbox-label">
          <input type="checkbox" checked={includeCircuitContext} onChange={e => setIncludeCircuitContext(e.target.checked)} />
          {t('mirror.macroClinical.includeCircuitContext')}
        </label>
        <label className="checkbox-label">
          <input type="checkbox" checked={includeRegionContext} onChange={e => setIncludeRegionContext(e.target.checked)} />
          {t('mirror.macroClinical.includeRegionContext')}
        </label>
        <label className="checkbox-label">
          <input type="checkbox" checked={createMirror} onChange={e => setCreateMirror(e.target.checked)} />
          {t('mirror.macroClinical.createProjectionFunctions')}
        </label>
        <label className="checkbox-label">
          <input type="checkbox" checked={createTriples} onChange={e => setCreateTriples(e.target.checked)} />
          {t('mirror.macroClinical.createProjectionFunctionTriples')}
        </label>
        <label className="checkbox-label">
          <input type="checkbox" checked={createEvidence} onChange={e => setCreateEvidence(e.target.checked)} />
          {t('mirror.macroClinical.createProjectionFunctionEvidence')}
        </label>
        <label className="checkbox-label">
          <input type="checkbox" checked={dryRun} onChange={e => setDryRun(e.target.checked)} />
          dry_run
        </label>
        <div className="filter-bar">
          <input className="filter-input" placeholder="resource_id" value={resourceFilter} onChange={e => setResourceFilter(e.target.value)} />
          <input className="filter-input" placeholder="batch_id" value={batchFilter} onChange={e => setBatchFilter(e.target.value)} />
          <input className="filter-input" placeholder={t('mirror.macroClinical.selectProjections')} value={projectionSearch} onChange={e => setProjectionSearch(e.target.value)} />
        </div>
        <div className="action-row">
          <ActionButton label={t('mirror.macroClinical.previewPrompt')} onClick={() => runExtraction(true)} disabled={running} />
          <ActionButton
            label={t('mirror.macroClinical.projectionToFunctions')}
            onClick={() => runExtraction(false)}
            disabled={running || (!dryRun && !currentProvider?.configured)}
            loading={running}
            variant="primary"
          />
          <ActionButton label={t('common.refresh')} onClick={() => { setProjTick(x => x + 1); onRefreshAll() }} />
        </div>
      </div>
      <div className="projection-selection-table card">
        <div className="card-title">{t('mirror.macroClinical.selectProjections')} ({selectedProjectionIds.length})</div>
        <DataTable columns={projectionCols} rows={projections} loading={projectionsLoading} error={projectionsError} total={projectionsData?.total} getKey={r => r.id} emptyText={t('mirror.macroClinical.selectProjections')} />
      </div>
      {selectedProjectionIds.length > 0 && includeCircuitContext && (
        <div className="projection-context-preview card">
          <div className="card-title">
            {t('mirror.macroClinical.projectionContextPreview')} — {t('mirror.macroClinical.circuitContextCount')}: {membershipPreview.length}
          </div>
          <DataTable columns={membershipPreviewCols} rows={membershipPreview} getKey={r => r.id} emptyText="—" />
        </div>
      )}
      {result && (
        <div className="projection-to-functions-result-card card">
          <div className="card-title">{t('mirror.macroClinical.projectionToFunctions')}</div>
          {result.run_id && <div>run_id: <code>{result.run_id}</code></div>}
          {result.item_id && <div>item_id: <code>{result.item_id}</code></div>}
          <div>{t('mirror.macroClinical.projectionCount')}: {result.projection_count}</div>
          {result.circuit_context_count != null && <div>{t('mirror.macroClinical.circuitContextCount')}: {result.circuit_context_count}</div>}
          {result.function_count != null && <div>{t('mirror.macroClinical.projectionFunctionCount')}: {result.function_count}</div>}
          {result.mirror_projection_function_created_count != null && (
            <div>{t('mirror.macroClinical.mirrorProjectionFunctionCreatedCount')}: {result.mirror_projection_function_created_count}</div>
          )}
          {result.mirror_projection_function_skipped_duplicate_count != null && (
            <div>{t('mirror.macroClinical.mirrorProjectionFunctionSkippedDuplicateCount')}: {result.mirror_projection_function_skipped_duplicate_count}</div>
          )}
          {result.triple_created_count != null && <div>{t('mirror.macroClinical.tripleCreatedCount')}: {result.triple_created_count}</div>}
          {result.evidence_created_count != null && <div>{t('mirror.macroClinical.evidenceCreatedCount')}: {result.evidence_created_count}</div>}
          {result.warnings?.map((w, i) => <div key={i} className="projection-to-functions-warning">{w}</div>)}
          {(result.system_prompt || result.user_prompt) && (
            <details className="projection-to-functions-prompt-preview" open={showPrompt}>
              <summary>{t('mirror.macroClinical.previewPrompt')}</summary>
              {result.system_prompt && <pre>{result.system_prompt}</pre>}
              {result.user_prompt && <pre>{result.user_prompt}</pre>}
            </details>
          )}
        </div>
      )}
    </div>
  )
}

function countConnectedComponents(projections: MirrorRegionConnection[]): number {
  const nodes = new Set<string>()
  const adj = new Map<string, Set<string>>()
  const addEdge = (a: string, b: string) => {
    if (!adj.has(a)) adj.set(a, new Set())
    if (!adj.has(b)) adj.set(b, new Set())
    adj.get(a)!.add(b)
    adj.get(b)!.add(a)
  }
  for (const p of projections) {
    const s = p.source_region_candidate_id
    const t = p.target_region_candidate_id
    if (s) nodes.add(s)
    if (t) nodes.add(t)
    if (s && t) addEdge(s, t)
  }
  const visited = new Set<string>()
  let components = 0
  for (const n of nodes) {
    if (visited.has(n)) continue
    components++
    const stack = [n]
    while (stack.length) {
      const cur = stack.pop()!
      if (visited.has(cur)) continue
      visited.add(cur)
      for (const nb of adj.get(cur) ?? []) stack.push(nb)
    }
  }
  return components
}

function ProjectionsToCircuitsWorkbench({
  onRefreshAll,
}: {
  onRefreshAll: () => void
}) {
  const { t } = useI18n()
  const sess = readSessionIds()
  const f = useMirrorFilters()
  const [projTick, setProjTick] = useState(0)
  const [selectedProjectionIds, setSelectedProjectionIds] = useState<string[]>([])
  const [projectionSearch, setProjectionSearch] = useState('')
  const [provider, setProvider] = useState('deepseek')
  const [modelName, setModelName] = useState('')
  const [maxCircuits, setMaxCircuits] = useState(10)
  const [maxStepsPerCircuit, setMaxStepsPerCircuit] = useState(20)
  const [includeExistingCircuits, setIncludeExistingCircuits] = useState(true)
  const [reuseExistingCircuits, setReuseExistingCircuits] = useState(true)
  const [createMirrorCircuits, setCreateMirrorCircuits] = useState(true)
  const [createCircuitSteps, setCreateCircuitSteps] = useState(true)
  const [createMemberships, setCreateMemberships] = useState(true)
  const [createTriples, setCreateTriples] = useState(true)
  const [createEvidence, setCreateEvidence] = useState(true)
  const [dryRun, setDryRun] = useState(false)
  const [batchFilter, setBatchFilter] = useState(sess.batch_id ?? '')
  const [resourceFilter, setResourceFilter] = useState('')
  const [running, setRunning] = useState(false)
  const [notice, setNotice] = useState<NoticeState | null>(null)
  const [result, setResult] = useState<ProjectionsToCircuitsExtractionResponse | null>(null)
  const [showPrompt, setShowPrompt] = useState(false)

  const { data: providersData } = useData(() => listLlmProviders(), [])
  const providers = providersData?.providers ?? []
  const currentProvider = providers.find(p => p.name === provider)

  useEffect(() => {
    if (currentProvider && !modelName) setModelName(currentProvider.default_model)
  }, [currentProvider, modelName])

  const projectionParams = useMemo(() => ({
    source_atlas: f.applied.sourceAtlas || undefined,
    granularity_level: f.applied.granularity || undefined,
    batch_id: batchFilter || undefined,
    resource_id: resourceFilter || undefined,
    limit: 100,
  }), [f.applied, batchFilter, resourceFilter, projTick])

  const { data: projectionsData, loading: projectionsLoading, error: projectionsError } = useData(
    () => listMirrorConnections(projectionParams),
    [projectionParams],
  )
  const projections = useMemo(() => {
    const items = projectionsData?.items ?? []
    const q = projectionSearch.trim().toLowerCase()
    if (!q) return items
    return items.filter(p =>
      p.id.toLowerCase().includes(q)
      || (p.source_region_candidate_id ?? '').toLowerCase().includes(q)
      || (p.target_region_candidate_id ?? '').toLowerCase().includes(q),
    )
  }, [projectionsData, projectionSearch])

  const selectedProjections = useMemo(
    () => projections.filter(p => selectedProjectionIds.includes(p.id)),
    [projections, selectedProjectionIds],
  )

  const graphPreview = useMemo(() => {
    const regionIds = new Set<string>()
    const hubCounts: Record<string, number> = {}
    for (const p of selectedProjections) {
      if (p.source_region_candidate_id) {
        regionIds.add(p.source_region_candidate_id)
        hubCounts[p.source_region_candidate_id] = (hubCounts[p.source_region_candidate_id] ?? 0) + 1
      }
      if (p.target_region_candidate_id) {
        regionIds.add(p.target_region_candidate_id)
        hubCounts[p.target_region_candidate_id] = (hubCounts[p.target_region_candidate_id] ?? 0) + 1
      }
    }
    const hubs = Object.entries(hubCounts).filter(([, c]) => c >= 2).sort((a, b) => b[1] - a[1])
    return {
      projectionCount: selectedProjections.length,
      uniqueRegionCount: regionIds.size,
      connectedComponentCount: countConnectedComponents(selectedProjections),
      hubs,
    }
  }, [selectedProjections])

  const toggleProjection = (id: string) => {
    setSelectedProjectionIds(prev =>
      prev.includes(id) ? prev.filter(x => x !== id) : [...prev, id],
    )
  }

  const validate = (): string | null => {
    if (selectedProjectionIds.length < 2) return t('mirror.macroClinical.needAtLeastTwoProjections')
    if (selectedProjectionIds.length > 100) return t('mirror.macroClinical.tooManyProjectionsForCircuitInference')
    if (maxCircuits < 1 || maxCircuits > 30) return t('mirror.macroClinical.maxCircuits') + ': 1–30'
    if (maxStepsPerCircuit < 2 || maxStepsPerCircuit > 50) return t('mirror.macroClinical.maxStepsPerCircuit') + ': 2–50'
    const atlases = new Set(selectedProjections.map(p => p.source_atlas))
    if (atlases.size > 1) return t('mirror.macroClinical.projectionsMustSameAtlas')
    const granularities = new Set(selectedProjections.map(p => p.granularity_level))
    if (granularities.size > 1) return t('mirror.macroClinical.projectionsMustSameGranularity')
    if (createMemberships && !createMirrorCircuits && !reuseExistingCircuits) {
      return t('mirror.macroClinical.membershipRequiresCircuit')
    }
    return null
  }

  const runExtraction = async (previewOnly: boolean) => {
    const err = validate()
    if (err) {
      setNotice({ type: 'error', message: err })
      return
    }
    setRunning(true)
    setNotice(null)
    try {
      const resp = await runProjectionsToCircuitsExtraction({
        provider,
        model_name: modelName || undefined,
        projection_ids: selectedProjectionIds,
        dry_run: previewOnly,
        max_circuits: maxCircuits,
        max_steps_per_circuit: maxStepsPerCircuit,
        include_existing_circuits: includeExistingCircuits,
        reuse_existing_circuits: reuseExistingCircuits,
        create_mirror_circuits: createMirrorCircuits,
        create_circuit_steps: createCircuitSteps,
        create_memberships: createMemberships,
        create_triples: createTriples,
        create_evidence: createEvidence,
      })
      setResult(resp)
      setShowPrompt(previewOnly)
      if (!previewOnly && resp.status === 'succeeded') {
        onRefreshAll()
        setProjTick(x => x + 1)
      }
      setNotice({
        type: resp.warnings?.length ? 'warning' : 'success',
        message: previewOnly
          ? t('mirror.macroClinical.previewPrompt')
          : t('mirror.macroClinical.projectionsToCircuits'),
      })
    } catch (e) {
      setNotice({ type: 'error', message: String(e) })
    } finally {
      setRunning(false)
    }
  }

  const projectionCols: Column<MirrorRegionConnection>[] = useMemo(() => [
    {
      key: 'select',
      header: '',
      render: r => (
        <input type="checkbox" checked={selectedProjectionIds.includes(r.id)} onChange={() => toggleProjection(r.id)} />
      ),
    },
    { key: 'id', header: 'projection_id', render: r => <code className="text-mono" style={{ fontSize: 11 }}>{r.id.slice(0, 10)}…</code> },
    { key: 'source', header: 'source', render: r => r.source_region_candidate_id?.slice(0, 8) ?? '—' },
    { key: 'target', header: 'target', render: r => r.target_region_candidate_id?.slice(0, 8) ?? '—' },
    { key: 'type', header: 'type', render: r => r.connection_type },
    { key: 'atlas', header: 'atlas', render: r => r.source_atlas },
    { key: 'granularity', header: 'granularity', render: r => r.granularity_level },
  ], [selectedProjectionIds])

  return (
    <div className="projections-to-circuits-workbench">
      <h3 className="panel-title">{t('mirror.macroClinical.projectionsToCircuits')}</h3>
      <p className="macro-clinical-alignment-body">{t('mirror.macroClinical.projectionsToCircuitsDescription')}</p>
      <div className="projections-to-circuits-warning">{t('mirror.macroClinical.projectionsToCircuitsMirrorOnlyWarning')}</div>
      {!dryRun && !currentProvider?.configured && (
        <div className="projections-to-circuits-warning">{t('llm.providerNotConfigured')}</div>
      )}
      {notice && <Notice notice={notice} onClose={() => setNotice(null)} />}
      <div className="projections-to-circuits-control-panel card">
        <label>Provider
          <select value={provider} onChange={e => setProvider(e.target.value)}>
            <option value="deepseek">DeepSeek</option>
            <option value="kimi">Kimi</option>
          </select>
        </label>
        <label>Model<input value={modelName} onChange={e => setModelName(e.target.value)} /></label>
        <label>{t('mirror.macroClinical.maxCircuits')}
          <input type="number" min={1} max={30} value={maxCircuits} onChange={e => setMaxCircuits(Number(e.target.value))} />
        </label>
        <label>{t('mirror.macroClinical.maxStepsPerCircuit')}
          <input type="number" min={2} max={50} value={maxStepsPerCircuit} onChange={e => setMaxStepsPerCircuit(Number(e.target.value))} />
        </label>
        <label className="checkbox-label"><input type="checkbox" checked={includeExistingCircuits} onChange={e => setIncludeExistingCircuits(e.target.checked)} />{t('mirror.macroClinical.includeExistingCircuits')}</label>
        <label className="checkbox-label"><input type="checkbox" checked={reuseExistingCircuits} onChange={e => setReuseExistingCircuits(e.target.checked)} />{t('mirror.macroClinical.reuseExistingCircuits')}</label>
        <label className="checkbox-label"><input type="checkbox" checked={createMirrorCircuits} onChange={e => setCreateMirrorCircuits(e.target.checked)} />{t('mirror.macroClinical.createMirrorCircuits')}</label>
        <label className="checkbox-label"><input type="checkbox" checked={createCircuitSteps} onChange={e => setCreateCircuitSteps(e.target.checked)} />{t('mirror.macroClinical.createInferredCircuitSteps')}</label>
        <label className="checkbox-label"><input type="checkbox" checked={createMemberships} onChange={e => setCreateMemberships(e.target.checked)} />{t('mirror.macroClinical.createInferredMemberships')}</label>
        <label className="checkbox-label"><input type="checkbox" checked={createTriples} onChange={e => setCreateTriples(e.target.checked)} />{t('mirror.macroClinical.createProjectionTriples')}</label>
        <label className="checkbox-label"><input type="checkbox" checked={createEvidence} onChange={e => setCreateEvidence(e.target.checked)} />{t('mirror.macroClinical.createProjectionEvidence')}</label>
        <label className="checkbox-label"><input type="checkbox" checked={dryRun} onChange={e => setDryRun(e.target.checked)} />dry_run</label>
        <div className="filter-bar">
          <input className="filter-input" placeholder="resource_id" value={resourceFilter} onChange={e => setResourceFilter(e.target.value)} />
          <input className="filter-input" placeholder="batch_id" value={batchFilter} onChange={e => setBatchFilter(e.target.value)} />
          <input className="filter-input" placeholder={t('mirror.macroClinical.selectProjectionGraph')} value={projectionSearch} onChange={e => setProjectionSearch(e.target.value)} />
        </div>
        <div className="action-row">
          <ActionButton label={t('mirror.macroClinical.previewPrompt')} onClick={() => runExtraction(true)} disabled={running} />
          <ActionButton label={t('mirror.macroClinical.projectionsToCircuits')} onClick={() => runExtraction(false)} disabled={running || (!dryRun && !currentProvider?.configured)} loading={running} variant="primary" />
          <ActionButton label={t('common.refresh')} onClick={() => { setProjTick(x => x + 1); onRefreshAll() }} />
        </div>
      </div>
      <div className="projection-selection-table card">
        <div className="card-title">{t('mirror.macroClinical.selectProjectionGraph')} ({selectedProjectionIds.length})</div>
        <DataTable columns={projectionCols} rows={projections} loading={projectionsLoading} error={projectionsError} total={projectionsData?.total} getKey={r => r.id} emptyText={t('mirror.macroClinical.selectProjectionGraph')} />
      </div>
      {selectedProjectionIds.length >= 2 && (
        <div className="projection-graph-preview card">
          <div className="card-title">{t('mirror.macroClinical.projectionGraphPreview')}</div>
          <div>{t('mirror.macroClinical.projectionCount')}: {graphPreview.projectionCount}</div>
          <div>{t('mirror.macroClinical.uniqueRegionCount')}: {graphPreview.uniqueRegionCount}</div>
          <div>{t('mirror.macroClinical.connectedComponentCount')}: {graphPreview.connectedComponentCount}</div>
          {graphPreview.hubs.length > 0 && (
            <div className="projection-graph-component-badge">
              hubs: {graphPreview.hubs.map(([id, c]) => `${id.slice(0, 8)}(${c})`).join(', ')}
            </div>
          )}
        </div>
      )}
      {result && (
        <div className="projections-to-circuits-result-card card">
          <div className="card-title">{t('mirror.macroClinical.projectionsToCircuits')}</div>
          {result.run_id && <div>run_id: <code>{result.run_id}</code></div>}
          {result.item_id && <div>item_id: <code>{result.item_id}</code></div>}
          <div>{t('mirror.macroClinical.projectionCount')}: {result.projection_count}</div>
          {result.existing_circuit_context_count != null && <div>{t('mirror.macroClinical.includeExistingCircuits')}: {result.existing_circuit_context_count}</div>}
          {result.inferred_circuit_count != null && <div>{t('mirror.macroClinical.inferredCircuitCount')}: {result.inferred_circuit_count}</div>}
          {result.mirror_circuit_created_count != null && <div>{t('mirror.macroClinical.mirrorCircuitCreatedCount')}: {result.mirror_circuit_created_count}</div>}
          {result.mirror_circuit_reused_count != null && <div>{t('mirror.macroClinical.mirrorCircuitReusedCount')}: {result.mirror_circuit_reused_count}</div>}
          {result.circuit_step_created_count != null && <div>{t('mirror.macroClinical.circuitStepCreatedCount')}: {result.circuit_step_created_count}</div>}
          {result.membership_created_count != null && <div>{t('mirror.macroClinical.membershipCreatedCount')}: {result.membership_created_count}</div>}
          {result.triple_created_count != null && <div>{t('mirror.macroClinical.tripleCreatedCount')}: {result.triple_created_count}</div>}
          {result.warnings?.map((w, i) => <div key={i} className="projections-to-circuits-warning">{w}</div>)}
          {(result.system_prompt || result.user_prompt) && (
            <details className="projections-to-circuits-prompt-preview" open={showPrompt}>
              <summary>{t('mirror.macroClinical.previewPrompt')}</summary>
              {result.system_prompt && <pre>{result.system_prompt}</pre>}
              {result.user_prompt && <pre>{result.user_prompt}</pre>}
            </details>
          )}
        </div>
      )}
    </div>
  )
}

function CircuitProjectionCrossValidationWorkbench({
  onRefreshMemberships,
}: {
  onRefreshMemberships: () => void
}) {
  const { t } = useI18n()
  const sess = readSessionIds()
  const f = useMirrorFilters()
  const [batchFilter, setBatchFilter] = useState(sess.batch_id ?? '')
  const [resourceFilter, setResourceFilter] = useState('')
  const [circuitIdsText, setCircuitIdsText] = useState('')
  const [projectionIdsText, setProjectionIdsText] = useState('')
  const [includeUnverified, setIncludeUnverified] = useState(true)
  const [includeConflicts, setIncludeConflicts] = useState(true)
  const [dryRun, setDryRun] = useState(true)
  const [applyUpdates, setApplyUpdates] = useState(false)
  const [updateBidirectional, setUpdateBidirectional] = useState(true)
  const [updateConflicts, setUpdateConflicts] = useState(false)
  const [limit, setLimit] = useState(1000)
  const [running, setRunning] = useState(false)
  const [showConfirm, setShowConfirm] = useState(false)
  const [notice, setNotice] = useState<NoticeState | null>(null)
  const [result, setResult] = useState<CircuitProjectionCrossValidationResponse | null>(null)
  const [runsTick, setRunsTick] = useState(0)
  const [resultsTick, setResultsTick] = useState(0)
  const [selectedRunId, setSelectedRunId] = useState('')

  const { data: runsData, loading: runsLoading, error: runsError } = useData(
    () => listCircuitProjectionCrossValidationRuns({ limit: 50 }),
    [runsTick],
  )
  const { data: resultsData, loading: resultsLoading, error: resultsError } = useData(
    () => listCircuitProjectionCrossValidationResults({
      run_id: selectedRunId || undefined,
      limit: 100,
    }),
    [resultsTick, selectedRunId],
  )

  const parseIds = (text: string): string[] | undefined => {
    const ids = text.split(/[\s,]+/).map(s => s.trim()).filter(Boolean)
    return ids.length ? ids : undefined
  }

  const buildScope = () => ({
    resource_id: resourceFilter || undefined,
    batch_id: batchFilter || undefined,
    source_atlas: f.applied.sourceAtlas || undefined,
    granularity_level: f.applied.granularity || undefined,
    circuit_ids: parseIds(circuitIdsText),
    projection_ids: parseIds(projectionIdsText),
    include_unverified: includeUnverified,
    include_conflicts: includeConflicts,
  })

  const validate = (): string | null => {
    if (limit < 1 || limit > 5000) return `${t('mirror.validation.limit')}: 1–5000`
    return null
  }

  const runCrossValidation = async (previewOnly: boolean) => {
    const err = validate()
    if (err) {
      setNotice({ type: 'error', message: err })
      return
    }
    setRunning(true)
    setNotice(null)
    try {
      const effectiveDryRun = previewOnly || dryRun
      const resp = await runCircuitProjectionCrossValidation({
        scope: buildScope(),
        dry_run: effectiveDryRun,
        apply_updates: applyUpdates && !effectiveDryRun,
        update_bidirectional: updateBidirectional,
        update_conflicts: updateConflicts,
        limit,
      })
      setResult(resp)
      if (!effectiveDryRun) {
        setRunsTick(x => x + 1)
        setResultsTick(x => x + 1)
        if (resp.run_id) setSelectedRunId(resp.run_id)
        if (applyUpdates) onRefreshMemberships()
      }
      setNotice({
        type: resp.warnings?.length ? 'warning' : 'success',
        message: effectiveDryRun
          ? t('mirror.macroClinical.previewCrossValidation')
          : t('mirror.macroClinical.runCrossValidation'),
      })
    } catch (e) {
      setNotice({ type: 'error', message: e instanceof ApiError ? e.message : String(e) })
    } finally {
      setRunning(false)
      setShowConfirm(false)
    }
  }

  const onRunClick = (previewOnly: boolean) => {
    const err = validate()
    if (err) {
      setNotice({ type: 'error', message: err })
      return
    }
    if (!previewOnly && !dryRun && applyUpdates) {
      setShowConfirm(true)
      return
    }
    runCrossValidation(previewOnly)
  }

  const previewCols: Column<CircuitProjectionCrossValidationResultPreview>[] = useMemo(() => [
    { key: 'circuit_id', header: 'circuit_id', render: r => r.circuit_id.slice(0, 8) },
    { key: 'projection_id', header: 'projection_id', render: r => r.projection_id.slice(0, 8) },
    { key: 'forward', header: 'forward', render: r => r.circuit_to_projection_membership_id?.slice(0, 8) ?? '—' },
    { key: 'reverse', header: 'reverse', render: r => r.projection_to_circuit_membership_id?.slice(0, 8) ?? '—' },
    {
      key: 'validation_status',
      header: 'status',
      render: r => (
        <span className={
          r.validation_status === 'bidirectionally_supported'
            ? 'cross-validation-status-bidirectional'
            : r.validation_status === 'conflict'
              ? 'cross-validation-status-conflict'
              : r.validation_status === 'insufficient_evidence'
                ? 'cross-validation-status-insufficient'
                : ''
        }>{r.validation_status}</span>
      ),
    },
    { key: 'support_level', header: 'support', render: r => r.support_level },
    { key: 'agreement_score', header: t('mirror.macroClinical.agreementScore'), render: r => (
      <span className="cross-validation-score-badge">{r.agreement_score ?? '—'}</span>
    ) },
    { key: 'source_step_agreement', header: t('mirror.macroClinical.sourceStepAgreement'), render: r => String(r.source_step_agreement ?? '—') },
    { key: 'target_step_agreement', header: t('mirror.macroClinical.targetStepAgreement'), render: r => String(r.target_step_agreement ?? '—') },
    { key: 'direction_agreement', header: t('mirror.macroClinical.directionAgreement'), render: r => String(r.direction_agreement ?? '—') },
    { key: 'scope_agreement', header: t('mirror.macroClinical.scopeAgreement'), render: r => String(r.scope_agreement ?? '—') },
    { key: 'conflict_reason', header: t('mirror.macroClinical.conflictReason'), render: r => r.conflict_reason ?? '—' },
  ], [t])

  const runCols: Column<MirrorCircuitProjectionCrossValidationRun>[] = useMemo(() => [
    { key: 'id', header: 'run_id', render: r => <><code className="text-mono" style={{ fontSize: 11 }}>{r.id.slice(0, 10)}…</code><CopyButton value={r.id} label="" /></> },
    { key: 'status', header: 'status', render: r => <StatusBadge status={r.status} /> },
    { key: 'dry_run', header: 'dry_run', render: r => r.dry_run ? 'yes' : 'no' },
    { key: 'apply_updates', header: 'apply', render: r => r.apply_updates ? 'yes' : 'no' },
    { key: 'membership_count', header: 'groups', render: r => r.membership_count },
    { key: 'bidirectional', header: 'bidir', render: r => r.bidirectionally_supported_count },
    { key: 'conflict', header: 'conflict', render: r => r.conflict_count },
    { key: 'updated', header: 'updated', render: r => r.updated_membership_count },
    { key: 'created_at', header: t('mirror.createdAt'), render: r => r.created_at.slice(0, 19).replace('T', ' ') },
  ], [t])

  const resultCols: Column<MirrorCircuitProjectionCrossValidationResult>[] = useMemo(() => [
    { key: 'id', header: 'result_id', render: r => r.id.slice(0, 8) },
    { key: 'run_id', header: 'run_id', render: r => r.run_id.slice(0, 8) },
    { key: 'circuit_id', header: 'circuit', render: r => r.circuit_id.slice(0, 8) },
    { key: 'projection_id', header: 'projection', render: r => r.projection_id.slice(0, 8) },
    { key: 'validation_status', header: 'status', render: r => r.validation_status },
    { key: 'support_level', header: 'support', render: r => r.support_level },
    { key: 'agreement_score', header: 'score', render: r => r.agreement_score ?? '—' },
    { key: 'conflict_reason', header: t('mirror.macroClinical.conflictReason'), render: r => r.conflict_reason ?? '—' },
  ], [t])

  const confirmMessage = updateConflicts
    ? `${t('mirror.macroClinical.crossValidationUpdateConfirm')}\n${t('mirror.macroClinical.crossValidationConflictUpdateConfirm')}`
    : t('mirror.macroClinical.crossValidationUpdateConfirm')

  return (
    <div className="circuit-projection-cross-validation-workbench">
      <h3 className="panel-title">{t('mirror.macroClinical.crossValidation')}</h3>
      <p className="macro-clinical-alignment-body">{t('mirror.macroClinical.crossValidationDescription')}</p>
      <div className="cross-validation-warning">{t('mirror.macroClinical.crossValidationNoLlmWarning')}</div>
      <div className="cross-validation-warning">{t('mirror.macroClinical.crossValidationNotReviewWarning')}</div>
      {notice && <Notice notice={notice} onClose={() => setNotice(null)} />}
      <div className="cross-validation-control-panel card">
        <label>resource_id<input value={resourceFilter} onChange={e => setResourceFilter(e.target.value)} /></label>
        <label>batch_id<input value={batchFilter} onChange={e => setBatchFilter(e.target.value)} /></label>
        <label>circuit_ids<textarea rows={1} value={circuitIdsText} onChange={e => setCircuitIdsText(e.target.value)} placeholder="uuid, uuid" /></label>
        <label>projection_ids<textarea rows={1} value={projectionIdsText} onChange={e => setProjectionIdsText(e.target.value)} placeholder="uuid, uuid" /></label>
        <label>{t('mirror.validation.limit')}<input type="number" min={1} max={5000} value={limit} onChange={e => setLimit(Number(e.target.value))} /></label>
        <label className="checkbox-label"><input type="checkbox" checked={includeUnverified} onChange={e => setIncludeUnverified(e.target.checked)} />{t('mirror.macroClinical.includeUnverified')}</label>
        <label className="checkbox-label"><input type="checkbox" checked={includeConflicts} onChange={e => setIncludeConflicts(e.target.checked)} />{t('mirror.macroClinical.includeConflicts')}</label>
        <label className="checkbox-label"><input type="checkbox" checked={dryRun} onChange={e => setDryRun(e.target.checked)} />dry_run</label>
        <label className="checkbox-label"><input type="checkbox" checked={applyUpdates} disabled={dryRun} onChange={e => setApplyUpdates(e.target.checked)} />{t('mirror.macroClinical.applyCrossValidationUpdates')}</label>
        <label className="checkbox-label"><input type="checkbox" checked={updateBidirectional} onChange={e => setUpdateBidirectional(e.target.checked)} />{t('mirror.macroClinical.updateBidirectional')}</label>
        <label className="checkbox-label"><input type="checkbox" checked={updateConflicts} onChange={e => setUpdateConflicts(e.target.checked)} />{t('mirror.macroClinical.updateConflicts')}</label>
        <div className="filter-bar">
          <button type="button" className="btn" disabled={running} onClick={() => onRunClick(true)}>{t('mirror.macroClinical.previewCrossValidation')}</button>
          <button type="button" className="btn btn-primary" disabled={running} onClick={() => onRunClick(false)}>{t('mirror.macroClinical.runCrossValidation')}</button>
          <button type="button" className="btn" onClick={() => setRunsTick(x => x + 1)}>{t('common.refresh')} Runs</button>
          <button type="button" className="btn" onClick={() => { setResultsTick(x => x + 1); onRefreshMemberships() }}>{t('common.refresh')} Results / Memberships</button>
        </div>
      </div>
      {result && (
        <div className="cross-validation-result-card card">
          <KeyValuePanel entries={[
            { label: 'run_id', value: result.run_id ?? '—' },
            { label: 'membership_count', value: String(result.membership_count) },
            { label: t('mirror.macroClinical.bidirectionallySupportedCount'), value: String(result.bidirectionally_supported_count) },
            { label: t('mirror.macroClinical.conflictCount'), value: String(result.conflict_count) },
            { label: t('mirror.macroClinical.insufficientEvidenceCount'), value: String(result.insufficient_evidence_count) },
            { label: t('mirror.macroClinical.updatedMembershipCount'), value: String(result.updated_membership_count) },
          ]} />
          {result.warnings?.length ? (
            <ul>{result.warnings.map(w => <li key={w} className="cross-validation-warning">{w}</li>)}</ul>
          ) : null}
          {result.results_preview?.length ? (
            <div className="cross-validation-preview-table">
              <h4>Preview</h4>
              <DataTable columns={previewCols} rows={result.results_preview} getKey={r => `${r.circuit_id}-${r.projection_id}-${r.validation_status}`} emptyText="—" />
            </div>
          ) : null}
        </div>
      )}
      <div className="cross-validation-runs-table card" style={{ marginTop: 12 }}>
        <h4>Cross Validation Runs</h4>
        <DataTable columns={runCols} rows={runsData?.items ?? []} loading={runsLoading} error={runsError} total={runsData?.total} getKey={r => r.id} emptyText="—" />
      </div>
      <div className="cross-validation-results-table card" style={{ marginTop: 12 }}>
        <h4>Cross Validation Results</h4>
        <div className="filter-bar" style={{ marginBottom: 8 }}>
          <input className="filter-input" placeholder="run_id filter" value={selectedRunId} onChange={e => setSelectedRunId(e.target.value)} />
          <button type="button" className="btn" onClick={() => setResultsTick(x => x + 1)}>{t('common.apply')}</button>
        </div>
        <DataTable columns={resultCols} rows={resultsData?.items ?? []} loading={resultsLoading} error={resultsError} total={resultsData?.total} getKey={r => r.id} emptyText="—" />
      </div>
      <ConfirmDialog
        open={showConfirm}
        title={t('mirror.macroClinical.runCrossValidation')}
        message={confirmMessage}
        confirmLabel={t('common.confirm')}
        onConfirm={() => runCrossValidation(false)}
        onCancel={() => setShowConfirm(false)}
        loading={running}
      />
    </div>
  )
}

type DualModelObjectType = 'circuit' | 'projection' | 'circuit_projection_membership' | 'projection_function' | 'circuit_step' | 'triple'

function DualModelVerificationWorkbench() {
  const { t } = useI18n()
  const sess = readSessionIds()
  const f = useMirrorFilters()
  const [objectType, setObjectType] = useState<DualModelObjectType>('circuit_projection_membership')
  const [selectedIds, setSelectedIds] = useState<string[]>([])
  const [modelAProvider, setModelAProvider] = useState('deepseek')
  const [modelAName, setModelAName] = useState('')
  const [modelBProvider, setModelBProvider] = useState('kimi')
  const [modelBName, setModelBName] = useState('')
  const [maxObjects, setMaxObjects] = useState(50)
  const [includeCrossValidationContext, setIncludeCrossValidationContext] = useState(true)
  const [includeEvidenceContext, setIncludeEvidenceContext] = useState(true)
  const [includeReviewContext, setIncludeReviewContext] = useState(false)
  const [createResults, setCreateResults] = useState(true)
  const [dryRun, setDryRun] = useState(true)
  const [batchFilter, setBatchFilter] = useState(sess.batch_id ?? '')
  const [resourceFilter, setResourceFilter] = useState('')
  const [objTick, setObjTick] = useState(0)
  const [runsTick, setRunsTick] = useState(0)
  const [running, setRunning] = useState(false)
  const [notice, setNotice] = useState<NoticeState | null>(null)
  const [result, setResult] = useState<DualModelVerificationResponse | null>(null)
  const [showPrompt, setShowPrompt] = useState(false)
  const [selectedRunId, setSelectedRunId] = useState('')

  const { data: providersData } = useData(() => listLlmProviders(), [])
  const providers = providersData?.providers ?? []

  const listParams = useMemo(() => ({
    source_atlas: f.applied.sourceAtlas || undefined,
    granularity_level: f.applied.granularity || undefined,
    batch_id: batchFilter || undefined,
    resource_id: resourceFilter || undefined,
    limit: 100,
  }), [f.applied, batchFilter, resourceFilter, objTick])

  const { data: circuitsData } = useData(() => listMirrorCircuits(listParams), [listParams, objectType])
  const { data: projectionsData } = useData(() => listMirrorConnections(listParams), [listParams, objectType])
  const { data: membershipsData } = useData(() => listMirrorCircuitProjectionMemberships(listParams), [listParams, objectType])
  const { data: projFnData } = useData(() => listMirrorProjectionFunctions(listParams), [listParams, objectType])
  const { data: stepsData } = useData(() => listMirrorCircuitSteps(listParams), [listParams, objectType])
  const { data: triplesData } = useData(() => listMirrorTriples(listParams), [listParams, objectType])

  const selectableObjects = useMemo(() => {
    if (objectType === 'circuit') return (circuitsData?.items ?? []).map(r => ({ id: r.id, label: r.circuit_name, confidence: r.confidence, atlas: r.source_atlas, granularity: r.granularity_level, mirror_status: r.mirror_status, review_status: r.review_status, extra: '' }))
    if (objectType === 'projection') return (projectionsData?.items ?? []).map(r => ({ id: r.id, label: r.id.slice(0, 8), confidence: r.confidence, atlas: r.source_atlas, granularity: r.granularity_level, mirror_status: r.mirror_status, review_status: r.review_status, extra: r.connection_type }))
    if (objectType === 'circuit_projection_membership') return (membershipsData?.items ?? []).map(r => ({ id: r.id, label: r.id.slice(0, 8), confidence: r.confidence, atlas: r.source_atlas, granularity: r.granularity_level, mirror_status: r.mirror_status, review_status: r.review_status, extra: r.verification_status }))
    if (objectType === 'projection_function') return (projFnData?.items ?? []).map(r => ({ id: r.id, label: r.function_term, confidence: r.confidence, atlas: r.source_atlas, granularity: r.granularity_level, mirror_status: r.mirror_status, review_status: r.review_status, extra: '' }))
    if (objectType === 'circuit_step') return (stepsData?.items ?? []).map(r => ({ id: r.id, label: r.step_name, confidence: r.confidence, atlas: r.source_atlas, granularity: r.granularity_level, mirror_status: r.mirror_status, review_status: r.review_status, extra: String(r.step_order) }))
    return (triplesData?.items ?? []).map(r => ({ id: r.id, label: `${r.subject_label} ${r.predicate} ${r.object_label}`, confidence: r.confidence, atlas: r.source_atlas, granularity: r.granularity_level, mirror_status: r.mirror_status, review_status: r.review_status, extra: '' }))
  }, [objectType, circuitsData, projectionsData, membershipsData, projFnData, stepsData, triplesData])

  const { data: dmRunsData, loading: dmRunsLoading } = useData(() => listDualModelVerificationExecutionRuns({ limit: 50 }), [runsTick])
  const { data: dmResultsData, loading: dmResultsLoading } = useData(
    () => listDualModelVerificationExecutionResults({ run_id: selectedRunId || undefined, limit: 100 }),
    [runsTick, selectedRunId],
  )

  const toggleId = (id: string) => setSelectedIds(prev => prev.includes(id) ? prev.filter(x => x !== id) : [...prev, id])

  const validate = (): string | null => {
    if (selectedIds.length < 1 && !batchFilter && !resourceFilter && !f.applied.sourceAtlas) {
      return t('mirror.dualModel.selectObjects')
    }
    if (selectedIds.length > 50) return 'max 50 object_ids'
    if (modelAProvider === modelBProvider) return t('mirror.dualModel.providerMustDiffer')
    if (!dryRun) {
      const pa = providers.find(p => p.name === modelAProvider)
      const pb = providers.find(p => p.name === modelBProvider)
      if (!pa?.configured || !pb?.configured) return t('llm.providerNotConfigured')
    }
    return null
  }

  const runVerification = async (previewOnly: boolean) => {
    const err = validate()
    if (err) { setNotice({ type: 'error', message: err }); return }
    setRunning(true)
    setNotice(null)
    try {
      const effectiveDryRun = previewOnly || dryRun
      const resp = await runDualModelVerification({
        object_type: objectType,
        object_ids: selectedIds.length ? selectedIds : undefined,
        scope: {
          batch_id: batchFilter || undefined,
          resource_id: resourceFilter || undefined,
          source_atlas: f.applied.sourceAtlas || undefined,
          granularity_level: f.applied.granularity || undefined,
        },
        model_a_provider: modelAProvider,
        model_a_name: modelAName || undefined,
        model_b_provider: modelBProvider,
        model_b_name: modelBName || undefined,
        dry_run: effectiveDryRun,
        max_objects: maxObjects,
        include_cross_validation_context: includeCrossValidationContext,
        include_evidence_context: includeEvidenceContext,
        include_review_context: includeReviewContext,
        create_results: createResults,
      })
      setResult(resp)
      setShowPrompt(effectiveDryRun)
      if (!effectiveDryRun) {
        setRunsTick(x => x + 1)
        if (resp.run_id) setSelectedRunId(resp.run_id)
      }
      setNotice({ type: resp.warnings?.length ? 'warning' : 'success', message: effectiveDryRun ? t('mirror.dualModel.previewPrompt') : t('mirror.dualModel.runVerification') })
    } catch (e) {
      setNotice({ type: 'error', message: e instanceof ApiError ? e.message : String(e) })
    } finally {
      setRunning(false)
    }
  }

  const previewCols: Column<DualModelVerificationResultPreview>[] = useMemo(() => [
    { key: 'object_id', header: 'object_id', render: r => r.object_id.slice(0, 8) },
    { key: 'model_a', header: 'DeepSeek', render: r => `${r.model_a_decision ?? '—'} (${r.model_a_confidence ?? '—'})` },
    { key: 'model_b', header: 'Kimi', render: r => `${r.model_b_decision ?? '—'} (${r.model_b_confidence ?? '—'})` },
    { key: 'consensus_status', header: t('mirror.dualModel.consensusStatus'), render: r => (
      <span className={
        r.consensus_status === 'consensus_supported' ? 'dual-model-consensus-supported'
          : r.consensus_status === 'model_conflict' ? 'dual-model-conflict'
            : r.consensus_status === 'insufficient_information' ? 'dual-model-insufficient'
              : r.consensus_status === 'consensus_rejected' ? 'dual-model-consensus-rejected' : ''
      }>{r.consensus_status}</span>
    ) },
    { key: 'consensus_score', header: t('mirror.dualModel.consensusScore'), render: r => r.consensus_score ?? '—' },
    { key: 'priority', header: t('mirror.dualModel.recommendedReviewPriority'), render: r => r.recommended_review_priority },
    { key: 'conflict', header: t('mirror.dualModel.conflictSummary'), render: r => r.conflict_summary ?? '—' },
  ], [t])

  return (
    <div className="dual-model-verification-workbench">
      <h3 className="panel-title">{t('mirror.dualModel.title')}</h3>
      <p className="macro-clinical-alignment-body">{t('mirror.dualModel.description')}</p>
      <div className="dual-model-warning">{t('mirror.dualModel.notReviewWarning')}</div>
      <div className="dual-model-warning">{t('mirror.dualModel.notFinalWarning')}</div>
      {!dryRun && <div className="dual-model-warning">{t('mirror.dualModel.willCallTwoProviders')}</div>}
      {dryRun && <div className="dual-model-warning">{t('mirror.dualModel.dryRunNoProviderCall')}</div>}
      {objectType === 'circuit_projection_membership' && (
        <div className="dual-model-warning">{t('mirror.macroClinical.crossValidation')} — recommend cross validation first.</div>
      )}
      {notice && <Notice notice={notice} onClose={() => setNotice(null)} />}
      <div className="dual-model-control-panel card">
        <label>{t('mirror.dualModel.objectType')}
          <select value={objectType} onChange={e => { setObjectType(e.target.value as DualModelObjectType); setSelectedIds([]) }}>
            <option value="circuit">circuit</option>
            <option value="projection">projection</option>
            <option value="circuit_projection_membership">circuit_projection_membership</option>
            <option value="projection_function">projection_function</option>
            <option value="circuit_step">circuit_step</option>
            <option value="triple">triple</option>
          </select>
        </label>
        <label>{t('mirror.dualModel.modelAProvider')}<select value={modelAProvider} onChange={e => setModelAProvider(e.target.value)}><option value="deepseek">DeepSeek</option></select></label>
        <label>{t('mirror.dualModel.modelAName')}<input value={modelAName} onChange={e => setModelAName(e.target.value)} placeholder="deepseek-chat" /></label>
        <label>{t('mirror.dualModel.modelBProvider')}<select value={modelBProvider} onChange={e => setModelBProvider(e.target.value)}><option value="kimi">Kimi</option></select></label>
        <label>{t('mirror.dualModel.modelBName')}<input value={modelBName} onChange={e => setModelBName(e.target.value)} placeholder="moonshot-v1-8k" /></label>
        <label>max_objects<input type="number" min={1} max={200} value={maxObjects} onChange={e => setMaxObjects(Number(e.target.value))} /></label>
        <label className="checkbox-label"><input type="checkbox" checked={includeCrossValidationContext} onChange={e => setIncludeCrossValidationContext(e.target.checked)} />{t('mirror.dualModel.includeCrossValidationContext')}</label>
        <label className="checkbox-label"><input type="checkbox" checked={includeEvidenceContext} onChange={e => setIncludeEvidenceContext(e.target.checked)} />{t('mirror.dualModel.includeEvidenceContext')}</label>
        <label className="checkbox-label"><input type="checkbox" checked={includeReviewContext} onChange={e => setIncludeReviewContext(e.target.checked)} />{t('mirror.dualModel.includeReviewContext')}</label>
        <label className="checkbox-label"><input type="checkbox" checked={createResults} onChange={e => setCreateResults(e.target.checked)} />create_results</label>
        <label className="checkbox-label"><input type="checkbox" checked={dryRun} onChange={e => setDryRun(e.target.checked)} />dry_run</label>
        <div className="filter-bar">
          <input className="filter-input" placeholder="resource_id" value={resourceFilter} onChange={e => setResourceFilter(e.target.value)} />
          <input className="filter-input" placeholder="batch_id" value={batchFilter} onChange={e => setBatchFilter(e.target.value)} />
          <button type="button" className="btn" onClick={() => setObjTick(x => x + 1)}>{t('common.refresh')}</button>
        </div>
        <div className="filter-bar">
          <button type="button" className="btn" disabled={running} onClick={() => runVerification(true)}>{t('mirror.dualModel.previewPrompt')}</button>
          <button type="button" className="btn btn-primary" disabled={running} onClick={() => runVerification(false)}>{t('mirror.dualModel.runVerification')}</button>
          <button type="button" className="btn" onClick={() => setRunsTick(x => x + 1)}>{t('common.refresh')} Runs/Results</button>
        </div>
      </div>
      <div className="dual-model-object-table card">
        <h4>{t('mirror.dualModel.selectObjects')} ({selectedIds.length})</h4>
        <table className="data-table"><thead><tr><th /><th>id</th><th>label</th><th>confidence</th><th>atlas</th><th>granularity</th><th>mirror</th><th>review</th><th>extra</th></tr></thead>
          <tbody>{selectableObjects.map(o => (
            <tr key={o.id}><td><input type="checkbox" checked={selectedIds.includes(o.id)} onChange={() => toggleId(o.id)} /></td>
              <td><code>{o.id.slice(0, 10)}…</code></td><td>{o.label}</td><td>{o.confidence ?? '—'}</td><td>{o.atlas}</td><td>{o.granularity}</td><td>{o.mirror_status}</td><td>{o.review_status}</td><td>{o.extra}</td></tr>
          ))}</tbody></table>
      </div>
      {result && (
        <div className="dual-model-result-card card">
          <KeyValuePanel entries={[
            { label: 'run_id', value: result.run_id ?? '—' },
            { label: 'model_a_run_id', value: result.model_a_run_id ?? '—' },
            { label: 'model_b_run_id', value: result.model_b_run_id ?? '—' },
            { label: t('mirror.dualModel.consensusSupportedCount'), value: String(result.consensus_supported_count ?? 0) },
            { label: t('mirror.dualModel.modelConflictCount'), value: String(result.model_conflict_count ?? 0) },
            { label: t('mirror.dualModel.insufficientInformationCount'), value: String(result.insufficient_information_count ?? 0) },
            { label: t('mirror.dualModel.needsHumanReviewCount'), value: String(result.needs_human_review_count ?? 0) },
          ]} />
          {showPrompt && (
            <details className="dual-model-prompt-preview" open>
              <summary>Prompt preview</summary>
              <h5>Model A</h5><pre>{result.model_a_system_prompt}</pre><pre>{result.model_a_user_prompt}</pre>
              <h5>Model B</h5><pre>{result.model_b_system_prompt}</pre><pre>{result.model_b_user_prompt}</pre>
            </details>
          )}
          {result.results_preview?.length ? (
            <div className="dual-model-results-table"><DataTable columns={previewCols} rows={result.results_preview} getKey={r => `${r.object_id}-${r.consensus_status}`} emptyText="—" /></div>
          ) : null}
        </div>
      )}
      <div className="dual-model-results-table card" style={{ marginTop: 12 }}>
        <h4>Runs</h4>
        <DataTable columns={[
          { key: 'id', header: 'run_id', render: r => r.id.slice(0, 10) },
          { key: 'task', header: 'object_type', render: r => r.verification_task_type },
          { key: 'a', header: 'model_a', render: r => r.model_a_provider },
          { key: 'b', header: 'model_b', render: r => r.model_b_provider },
          { key: 'status', header: 'status', render: r => r.status },
          { key: 'supported', header: 'supported', render: r => r.consensus_supported_count },
          { key: 'conflict', header: 'conflict', render: r => r.model_conflict_count },
        ]} rows={dmRunsData?.items ?? []} loading={dmRunsLoading} getKey={r => r.id} emptyText="—" />
        <h4 style={{ marginTop: 12 }}>Results</h4>
        <input className="filter-input" placeholder="run_id" value={selectedRunId} onChange={e => setSelectedRunId(e.target.value)} />
        <DataTable columns={[
          { key: 'id', header: 'result_id', render: r => r.id.slice(0, 8) },
          { key: 'object', header: 'object', render: r => r.object_id.slice(0, 8) },
          { key: 'consensus', header: 'consensus', render: r => r.consensus_status },
          { key: 'score', header: 'score', render: r => r.consensus_score ?? '—' },
          { key: 'priority', header: 'priority', render: r => r.recommended_review_priority },
        ]} rows={dmResultsData?.items ?? []} loading={dmResultsLoading} getKey={r => r.id} emptyText="—" />
      </div>
    </div>
  )
}

function MacroClinicalSchemaTab({ dataFirstMode = false }: { dataFirstMode?: boolean }) {
  const { t } = useI18n()
  const sess = readSessionIds()
  const f = useMirrorFilters()
  const [section, setSection] = useState<'steps' | 'projFn' | 'membership' | 'dmRuns' | 'dmResults'>('steps')
  const [tick, setTick] = useState(0)
  const [batchFilter, setBatchFilter] = useState(sess.batch_id ?? '')
  const [resourceFilter, setResourceFilter] = useState('')
  const [expandedStep, setExpandedStep] = useState<MacroPipelineStepId | null>(null)
  const [autoExpanded, setAutoExpanded] = useState(false)
  const { steps: pipelineSteps, nextStep: pipelineNextStep, hasError: pipelineError } = useMacroClinicalPipelineProgress({
    batch_id: batchFilter || undefined,
    resource_id: resourceFilter || undefined,
    source_atlas: f.applied.sourceAtlas || undefined,
    granularity_level: f.applied.granularity || undefined,
  })

  useEffect(() => {
    if (dataFirstMode) return
    if (!autoExpanded && pipelineSteps.some(s => s.status !== 'not_started')) {
      const firstActive = pipelineSteps.find(s => s.status === 'ready' || s.status === 'warning')
      if (firstActive) {
        setExpandedStep(firstActive.id)
        setAutoExpanded(true)
      } else if (pipelineSteps.every(s => s.status === 'completed')) {
        setExpandedStep('dual_model_verification')
        setAutoExpanded(true)
      }
    }
  }, [pipelineSteps, autoExpanded, dataFirstMode])

  const expandAllPipeline = () => setExpandedStep('circuit_to_steps')
  const collapseAllPipeline = () => setExpandedStep(null)

  const toggleStep = (id: MacroPipelineStepId) => {
    setExpandedStep(prev => prev === id ? null : id)
  }

  const listParams = useMemo(() => ({
    source_atlas: f.applied.sourceAtlas || undefined,
    granularity_level: f.applied.granularity || undefined,
    batch_id: batchFilter || undefined,
    resource_id: resourceFilter || undefined,
    limit: 100,
  }), [f.applied, batchFilter, resourceFilter, tick])

  const { data: stepsData, loading: stepsLoading, error: stepsError } = useData(
    () => listMirrorCircuitSteps(listParams),
    [listParams],
  )
  const { data: projFnData, loading: projFnLoading, error: projFnError } = useData(
    () => listMirrorProjectionFunctions(listParams),
    [listParams],
  )
  const { data: membershipData, loading: membershipLoading, error: membershipError } = useData(
    () => listMirrorCircuitProjectionMemberships(listParams),
    [listParams],
  )
  const { data: dmRunsData, loading: dmRunsLoading, error: dmRunsError } = useData(
    () => listMirrorDualModelVerificationRuns(listParams),
    [listParams],
  )
  const { data: dmResultsData, loading: dmResultsLoading, error: dmResultsError } = useData(
    () => listMirrorDualModelVerificationResults(listParams),
    [listParams],
  )

  const stepCols: Column<MirrorCircuitStep>[] = useMemo(() => [
    { key: 'id', header: 'id', render: r => <><code className="text-mono" style={{ fontSize: 11 }}>{r.id.slice(0, 10)}…</code><CopyButton value={r.id} label="" /></> },
    { key: 'circuit_id', header: 'circuit_id', render: r => r.circuit_id.slice(0, 8) },
    { key: 'step_order', header: t('mirror.macroClinical.stepOrder'), render: r => r.step_order },
    { key: 'step_name', header: t('mirror.macroClinical.stepName'), render: r => r.step_name },
    { key: 'step_type', header: t('mirror.macroClinical.stepType'), render: r => r.step_type },
    { key: 'role', header: t('mirror.macroClinical.role'), render: r => r.role },
    { key: 'source_atlas', header: 'atlas', render: r => r.source_atlas },
    { key: 'mirror_status', header: t('mirror.mirrorStatus'), render: r => <StatusBadge status={r.mirror_status} /> },
    { key: 'review_status', header: t('mirror.reviewStatus'), render: r => <StatusBadge status={r.review_status} /> },
  ], [t])

  const projFnCols: Column<MirrorProjectionFunction>[] = useMemo(() => [
    { key: 'id', header: 'id', render: r => <><code className="text-mono" style={{ fontSize: 11 }}>{r.id.slice(0, 10)}…</code><CopyButton value={r.id} label="" /></> },
    { key: 'projection_id', header: 'projection_id', render: r => r.projection_id.slice(0, 8) },
    { key: 'function_term', header: t('mirror.macroClinical.projectionFunction'), render: r => r.function_term },
    { key: 'function_category', header: 'category', render: r => r.function_category },
    { key: 'relation_type', header: 'relation', render: r => r.relation_type },
    { key: 'confidence', header: t('mirror.confidence'), render: r => <ConfidenceCell value={r.confidence} /> },
    { key: 'mirror_status', header: t('mirror.mirrorStatus'), render: r => <StatusBadge status={r.mirror_status} /> },
  ], [t])

  const membershipCols: Column<MirrorCircuitProjectionMembership>[] = useMemo(() => [
    { key: 'id', header: 'id', render: r => <><code className="text-mono" style={{ fontSize: 11 }}>{r.id.slice(0, 10)}…</code><CopyButton value={r.id} label="" /></> },
    { key: 'circuit_id', header: 'circuit', render: r => r.circuit_id.slice(0, 8) },
    { key: 'projection_id', header: 'projection', render: r => r.projection_id.slice(0, 8) },
    { key: 'role_in_circuit', header: t('mirror.macroClinical.roleInCircuit'), render: r => <span className="macro-clinical-membership-badge">{r.role_in_circuit}</span> },
    { key: 'source_method', header: t('mirror.macroClinical.sourceMethod'), render: r => r.source_method },
    { key: 'verification_status', header: t('mirror.macroClinical.verificationStatus'), render: r => <StatusBadge status={r.verification_status} /> },
    { key: 'mirror_status', header: t('mirror.mirrorStatus'), render: r => <StatusBadge status={r.mirror_status} /> },
  ], [t])

  const dmRunCols: Column<MirrorDualModelVerificationRun>[] = useMemo(() => [
    { key: 'id', header: 'id', render: r => <><code className="text-mono" style={{ fontSize: 11 }}>{r.id.slice(0, 10)}…</code><CopyButton value={r.id} label="" /></> },
    { key: 'verification_task_type', header: 'task', render: r => r.verification_task_type },
    { key: 'model_a_provider', header: 'model_a', render: r => r.model_a_provider },
    { key: 'model_b_provider', header: 'model_b', render: r => r.model_b_provider },
    { key: 'status', header: 'status', render: r => <StatusBadge status={r.status} /> },
    { key: 'object_count', header: 'count', render: r => r.object_count },
    { key: 'dry_run', header: 'dry_run', render: r => r.dry_run ? 'yes' : 'no' },
    { key: 'created_at', header: t('mirror.createdAt'), render: r => r.created_at.slice(0, 19).replace('T', ' ') },
  ], [t])

  const dmResultCols: Column<MirrorDualModelVerificationResult>[] = useMemo(() => [
    { key: 'id', header: 'id', render: r => <><code className="text-mono" style={{ fontSize: 11 }}>{r.id.slice(0, 10)}…</code><CopyButton value={r.id} label="" /></> },
    { key: 'object_type', header: 'type', render: r => r.object_type },
    { key: 'object_id', header: 'object_id', render: r => r.object_id.slice(0, 8) },
    { key: 'consensus_status', header: t('mirror.macroClinical.consensusStatus'), render: r => (
      <span className={r.consensus_status === 'model_conflict' ? 'dual-model-conflict-badge' : 'dual-model-consensus-badge'}>
        {r.consensus_status}
      </span>
    ) },
    { key: 'consensus_score', header: 'score', render: r => r.consensus_score ?? '—' },
    { key: 'recommended_review_priority', header: t('mirror.macroClinical.reviewPriority'), render: r => r.recommended_review_priority },
    { key: 'model_a_decision', header: 'deepseek', render: r => r.model_a_decision },
    { key: 'model_b_decision', header: 'kimi', render: r => r.model_b_decision },
  ], [t])

  const sections = [
    { id: 'steps' as const, label: t('mirror.macroClinical.circuitSteps') },
    { id: 'projFn' as const, label: t('mirror.macroClinical.projectionFunctions') },
    { id: 'membership' as const, label: t('mirror.macroClinical.circuitProjectionMemberships') },
    { id: 'dmRuns' as const, label: t('mirror.macroClinical.dualModelVerificationRuns') },
    { id: 'dmResults' as const, label: t('mirror.macroClinical.dualModelVerificationResults') },
  ]

  return (
    <div className="macro-pipeline macro-clinical-schema-panel">
      {dataFirstMode && (
        <div className="llm-macro-data-first-bar">
          <span className="llm-data-first-mode-note">{t('llm.dataFirst.dataFirstMode')}</span>
          <button type="button" className="btn btn-sm" onClick={expandAllPipeline}>展开所有</button>
          <button type="button" className="btn btn-sm" onClick={collapseAllPipeline}>收起所有</button>
        </div>
      )}
      {/* Pipeline Overview */}
      {!dataFirstMode && (
        <MacroPipelineOverview steps={pipelineSteps} nextStep={pipelineNextStep} hasError={pipelineError} />
      )}

      {/* Step 1: Circuit → Steps */}
      <MacroPipelineCard
        step={pipelineSteps[0]}
        expanded={expandedStep === 'circuit_to_steps'}
        onToggle={() => toggleStep('circuit_to_steps')}
        onOpenResults={() => setSection('steps')}
      >
        <CircuitToStepsWorkbench onRefreshSteps={() => setTick(x => x + 1)} />
      </MacroPipelineCard>

      {/* Step 2: Steps → Projections + Memberships */}
      <MacroPipelineCard
        step={pipelineSteps[1]}
        expanded={expandedStep === 'steps_to_projections'}
        onToggle={() => toggleStep('steps_to_projections')}
        onOpenResults={() => setSection('membership')}
      >
        <CircuitStepsToProjectionsWorkbench onRefreshAll={() => setTick(x => x + 1)} />
      </MacroPipelineCard>

      {/* Step 3: Projection → Functions */}
      <MacroPipelineCard
        step={pipelineSteps[2]}
        expanded={expandedStep === 'projection_to_functions'}
        onToggle={() => toggleStep('projection_to_functions')}
        onOpenResults={() => setSection('projFn')}
      >
        <ProjectionToFunctionsWorkbench onRefreshAll={() => setTick(x => x + 1)} />
      </MacroPipelineCard>

      {/* Step 4: Projection Graph → Circuits */}
      <MacroPipelineCard
        step={pipelineSteps[3]}
        expanded={expandedStep === 'projections_to_circuits'}
        onToggle={() => toggleStep('projections_to_circuits')}
        onOpenResults={() => setSection('steps')}
      >
        <ProjectionsToCircuitsWorkbench onRefreshAll={() => setTick(x => x + 1)} />
      </MacroPipelineCard>

      {/* Step 5: Cross Validation */}
      <MacroPipelineCard
        step={pipelineSteps[4]}
        expanded={expandedStep === 'cross_validation'}
        onToggle={() => toggleStep('cross_validation')}
        onOpenResults={() => setSection('membership')}
      >
        <CircuitProjectionCrossValidationWorkbench onRefreshMemberships={() => setTick(x => x + 1)} />
      </MacroPipelineCard>

      {/* Step 6: Dual-Model Verification */}
      <MacroPipelineCard
        step={pipelineSteps[5]}
        expanded={expandedStep === 'dual_model_verification'}
        onToggle={() => toggleStep('dual_model_verification')}
        onOpenResults={() => setSection('dmRuns')}
      >
        <DualModelVerificationWorkbench />
      </MacroPipelineCard>

      {/* Result Tables */}
      <div className="macro-pipeline-result-nav">
        <strong style={{ marginRight: 8, fontSize: 12, color: '#555' }}>结果表：</strong>
        {sections.map(s => (
          <button
            key={s.id}
            type="button"
            className={`macro-pipeline-result-button${section === s.id ? ' active' : ''}`}
            onClick={() => setSection(s.id)}
          >
            {s.label}
          </button>
        ))}
      </div>
      <div className="card macro-clinical-table">
        <MirrorFilterBar
          sourceAtlas={f.sourceAtlas}
          onSourceAtlas={f.setSourceAtlas}
          granularity={f.granularity}
          onGranularity={f.setGranularity}
          mirrorStatus={f.mirrorStatus}
          onMirrorStatus={f.setMirrorStatus}
          reviewStatus={f.reviewStatus}
          onReviewStatus={f.setReviewStatus}
          llmRunId={f.llmRunId}
          onLlmRunId={f.setLlmRunId}
        />
        <div className="filter-bar" style={{ marginBottom: 8 }}>
          <input className="filter-input" placeholder="resource_id" value={resourceFilter} onChange={e => setResourceFilter(e.target.value)} />
          <input className="filter-input" placeholder="batch_id" value={batchFilter} onChange={e => setBatchFilter(e.target.value)} />
          <button type="button" className="btn" onClick={() => { f.apply(); setTick(x => x + 1) }}>{t('common.apply')}</button>
          <button type="button" className="btn" onClick={() => setTick(x => x + 1)}>{t('common.refresh')}</button>
        </div>
        {section === 'steps' && (
          <DataTable columns={stepCols} rows={stepsData?.items ?? []} loading={stepsLoading} error={stepsError} total={stepsData?.total} getKey={r => r.id} emptyText={t('mirror.macroClinical.noCircuitSteps')} />
        )}
        {section === 'projFn' && (
          <DataTable columns={projFnCols} rows={projFnData?.items ?? []} loading={projFnLoading} error={projFnError} total={projFnData?.total} getKey={r => r.id} emptyText={t('mirror.macroClinical.noProjectionFunctions')} />
        )}
        {section === 'membership' && (
          <DataTable columns={membershipCols} rows={membershipData?.items ?? []} loading={membershipLoading} error={membershipError} total={membershipData?.total} getKey={r => r.id} emptyText={t('mirror.macroClinical.noMemberships')} />
        )}
        {section === 'dmRuns' && (
          <DataTable columns={dmRunCols} rows={dmRunsData?.items ?? []} loading={dmRunsLoading} error={dmRunsError} total={dmRunsData?.total} getKey={r => r.id} emptyText={t('mirror.macroClinical.noDualModelRuns')} />
        )}
        {section === 'dmResults' && (
          <DataTable columns={dmResultCols} rows={dmResultsData?.items ?? []} loading={dmResultsLoading} error={dmResultsError} total={dmResultsData?.total} getKey={r => r.id} emptyText={t('mirror.macroClinical.noDualModelResults')} />
        )}
      </div>

      {/* Schema Readiness — collapsed by default */}
      <details className="card" style={{ margin: '12px 0' }}>
        <summary style={{ fontSize: 13, cursor: 'pointer', padding: '8px 0' }}>
          Schema Readiness / 模式说明
        </summary>
        <MacroClinicalSchemaReadinessCard />
      </details>
    </div>
  )
}

function MacroClinicalAlignmentCard() {
  const { t } = useI18n()
  return (
    <details className="macro-clinical-alignment-card card" open>
      <summary>{t('macroClinical.alignmentTitle')}</summary>
      <p className="macro-clinical-alignment-body">{t('macroClinical.alignmentBody')}</p>
      <p className="macro-clinical-alignment-body">{t('macroClinical.recommendedFlow')}</p>
      <ul className="macro-clinical-mapping-list">
        <li>{t('macroClinical.mapConnections')}</li>
        <li>{t('macroClinical.mapFunctions')}</li>
        <li>{t('macroClinical.mapCircuits')}</li>
        <li>{t('macroClinical.mapCircuitRegions')}</li>
        <li>{t('macroClinical.mapTriples')}</li>
        <li>{t('macroClinical.plannedCircuitSteps')}</li>
        <li>{t('macroClinical.plannedProjectionFunctions')}</li>
        <li>{t('macroClinical.plannedMemberships')}</li>
        <li>{t('macroClinical.plannedDualModel')}</li>
      </ul>
      <p className="macro-clinical-alignment-note">{t('macroClinical.plannedPrompts')}</p>
    </details>
  )
}

function MacroClinicalTabMappingNote() {
  const { t } = useI18n()
  return (
    <div className="macro-clinical-tab-mapping-note">{t('macroClinical.tabMappingNote')}</div>
  )
}

function SafetyNotes() {
  const { t } = useI18n()
  return (
    <div style={{ display: 'flex', flexDirection: 'column', gap: 6, marginBottom: 12 }}>
      <div className="llm-safety-note">{t('llm.finalKgNotWritten')}</div>
      <div style={{ fontSize: 11, color: '#888' }}>{t('llm.noApiKeyReturned')}</div>
    </div>
  )
}

function ComparisonRow({ label, current, suggested }: {
  label: string; current: React.ReactNode; suggested: React.ReactNode
}) {
  return (
    <tr>
      <td style={{ fontWeight: 600, whiteSpace: 'nowrap' }}>{label}</td>
      <td style={{ color: '#555' }}>{current ?? <span className="text-muted">—</span>}</td>
      <td style={{ color: '#0958d9' }}>{suggested ?? <span className="text-muted">—</span>}</td>
    </tr>
  )
}

function SuggestionPanel({ candidate, ext }: { candidate: CandidateBrainRegion; ext: LlmExtraction }) {
  const { t } = useI18n()
  const s: LlmSuggestion = ext.structured_result ?? {}
  return (
    <div className="table-wrap">
      <table>
        <thead>
          <tr>
            <th style={{ width: 160 }}>{t('llmExtraction.field')}</th>
            <th>{t('llmExtraction.currentValue')}</th>
            <th>{t('llmExtraction.suggestion')}</th>
          </tr>
        </thead>
        <tbody>
          <ComparisonRow label={t('common.cnName')} current={candidate.cn_name} suggested={s.suggested_cn_name} />
          <ComparisonRow label={t('common.enName')} current={candidate.en_name} suggested={s.suggested_en_name} />
          <ComparisonRow label={t('common.laterality')} current={candidate.laterality} suggested={s.suggested_laterality} />
          <ComparisonRow label={t('llmExtraction.baseName')} current={null} suggested={s.suggested_region_base_name} />
          <ComparisonRow label={t('llmExtraction.aliases')} current={null} suggested={(s.suggested_aliases ?? []).join('、') || null} />
          <ComparisonRow label={t('llmExtraction.descriptionField')} current={null} suggested={s.suggested_description} />
          <ComparisonRow label={t('llmExtraction.confidence')} current={null} suggested={s.confidence != null ? s.confidence.toFixed(2) : null} />
          <ComparisonRow label={t('llmExtraction.evidenceSummary')} current={null} suggested={s.evidence_summary} />
          <ComparisonRow label={t('llmExtraction.riskFlags')} current={null} suggested={(s.risk_flags ?? []).join('、') || null} />
          <ComparisonRow label={t('llmExtraction.needsHumanReview')} current={null} suggested={s.needs_human_review === undefined ? null : (s.needs_human_review ? t('common.yes') : t('common.no'))} />
        </tbody>
      </table>
    </div>
  )
}

function ExtractionCard({ candidate, ext }: { candidate: CandidateBrainRegion; ext: LlmExtraction }) {
  const { t } = useI18n()
  const [showRaw, setShowRaw] = useState(false)
  return (
    <div className="card">
      <div className="card-title" style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center' }}>
        <span>{t('llmExtraction.resultTitle')} · <StatusBadge status={ext.status} /></span>
        <span style={{ fontSize: 11, color: '#888' }}>
          {ext.provider}/{ext.model} · {ext.prompt_version} · {ext.created_at.slice(0, 19).replace('T', ' ')}
        </span>
      </div>
      <SuggestionPanel candidate={candidate} ext={ext} />
      {ext.raw_response && (
        <div style={{ marginTop: 12 }}>
          <button type="button" className="btn btn-sm" onClick={() => setShowRaw(v => !v)}>
            {showRaw ? t('llmExtraction.hideRaw') : t('llmExtraction.showRaw')}
          </button>
          {showRaw && <pre className="llm-response-json" style={{ marginTop: 8 }}>{ext.raw_response}</pre>}
        </div>
      )}
      {ext.error_message && <div className="notice notice-error" style={{ marginTop: 8 }}>{ext.error_message}</div>}
    </div>
  )
}

function CandidateDetail({ candidate, onBack }: { candidate: CandidateBrainRegion; onBack: () => void }) {
  const { t } = useI18n()
  const [extracting, setExtracting] = useState(false)
  const [notice, setNotice] = useState<NoticeState | null>(null)
  const onClose = useCallback(() => setNotice(null), [])
  const { data: options } = useData(() => fetchLlmExtractionOptions(), [])
  const { data, loading, error, reload } = useData(
    () => fetchCandidateLlmExtractions(candidate.id),
    [candidate.id],
  )

  const runExtract = async () => {
    setExtracting(true)
    setNotice(null)
    try {
      await extractCandidate(candidate.id)
      setNotice({ type: 'success', message: t('llmExtraction.extractSuccess') })
      reload()
    } catch (e) {
      const msg = e instanceof ApiError ? e.message : String(e)
      setNotice({ type: 'error', message: t('llmExtraction.extractFailed', { error: msg }) })
    } finally {
      setExtracting(false)
    }
  }

  return (
    <div>
      <PageHeader
        title={candidate.cn_name ?? candidate.en_name ?? candidate.raw_name}
        description={t('llmExtraction.detailDesc')}
        readonly={false}
        actions={
          <div style={{ display: 'flex', gap: 8 }}>
            <ActionButton label={t('llmExtraction.backToList')} onClick={onBack} />
            <ActionButton
              label={extracting ? t('llmExtraction.extracting') : t('llmExtraction.extractBtn')}
              onClick={runExtract}
              disabled={extracting || !(options?.api_key_configured ?? false)}
              loading={extracting}
              variant="primary"
            />
          </div>
        }
      />
      <Notice notice={notice} onClose={onClose} />
      <AdvisoryBanner />
      <div className="card">
        <div className="card-title">{t('llmExtraction.candidateFields')}</div>
        <KeyValuePanel
          entries={[
            { label: t('common.candidateId'), value: <code className="text-mono" style={{ fontSize: 12 }}>{candidate.id}</code> },
            { label: t('finalRegions.rawName'), value: candidate.raw_name },
            { label: t('finalRegions.stdName'), value: candidate.std_name },
            { label: t('common.enName'), value: candidate.en_name },
            { label: t('common.cnName'), value: candidate.cn_name },
            { label: t('common.laterality'), value: <StatusBadge status={candidate.laterality} /> },
            { label: t('finalRegions.atlas'), value: `${candidate.source_atlas} ${candidate.source_version}` },
            { label: t('finalRegions.granularityLevel'), value: `${candidate.granularity_level} / ${candidate.granularity_family}` },
            { label: t('llmExtraction.candidateStatus'), value: <StatusBadge status={candidate.candidate_status} /> },
          ]}
        />
      </div>
      {loading && <LoadingState text={t('llmExtraction.loadingHistory')} />}
      {error && <ErrorState error={error} />}
      {data && data.items.length === 0 && <EmptyState text={t('llmExtraction.emptyHistory')} />}
      {data && data.items.map(ext => <ExtractionCard key={ext.id} candidate={candidate} ext={ext} />)}
    </div>
  )
}

function ProviderPanel({
  providers,
  selectedProvider,
  onProviderChange,
  modelName,
  onModelChange,
  dryRun,
  onDryRunChange,
}: {
  providers: LlmProviderInfo[]
  selectedProvider: string
  onProviderChange: (v: string) => void
  modelName: string
  onModelChange: (v: string) => void
  dryRun: boolean
  onDryRunChange: (v: boolean) => void
}) {
  const { t } = useI18n()
  const current = providers.find(p => p.name === selectedProvider)
  const configured = current?.configured ?? false

  return (
    <div className="llm-provider-panel">
      <div style={{ width: '100%', marginBottom: 4, fontWeight: 600, fontSize: 13 }}>{t('llm.providers')}</div>
      <div style={{ display: 'flex', flexWrap: 'wrap', gap: 8, width: '100%' }}>
        {providers.map(p => (
          <span
            key={p.name}
            className={`llm-provider-badge ${p.configured ? 'configured' : 'not-configured'}`}
          >
            {p.name}: {p.configured ? (p.name === 'kimi' ? t('llm.kimiConfigured') : t('llm.deepseekConfigured')) : t('llm.providerNotConfigured')}
          </span>
        ))}
      </div>
      <label>
        {t('llm.provider')}
        <select className="filter-select" value={selectedProvider} onChange={e => onProviderChange(e.target.value)}>
          {providers.map(p => (
            <option key={p.name} value={p.name}>{p.name}</option>
          ))}
        </select>
      </label>
      <label>
        {t('llm.model')}
        <input
          className="filter-input"
          value={modelName}
          onChange={e => onModelChange(e.target.value)}
          placeholder={current?.default_model ?? ''}
        />
      </label>
      <label style={{ flexDirection: 'row', alignItems: 'center', gap: 8, cursor: 'pointer' }}>
        <input type="checkbox" checked={dryRun} onChange={e => onDryRunChange(e.target.checked)} />
        {t('llm.dryRun')}
      </label>
      {!configured && (
        <div className="notice notice-error" style={{ flex: '1 1 100%' }}>
          {t('llm.providerNotConfigured')}: {selectedProvider}
        </div>
      )}
    </div>
  )
}

function MirrorKgWarning() {
  const { t } = useI18n()
  return (
    <div className="mirror-not-final-warning">
      <AlertTriangle size={16} style={{ flexShrink: 0, marginTop: 1 }} />
      <div>
        <strong>{t('mirror.title')}</strong>
        <div>{t('mirror.notFinalWarning')}</div>
        <div style={{ fontSize: 12, marginTop: 4 }}>{t('mirror.description')}</div>
      </div>
    </div>
  )
}

function ValidationSeverityCell({ severity }: { severity: string }) {
  const cls = `validation-severity-${severity}`
  return <span className={cls}>{severity}</span>
}

function ConfidenceCell({ value }: { value: number | null }) {
  if (value == null) return <>—</>
  return <span className="mirror-confidence-cell">{(value * 100).toFixed(0)}%</span>
}

function EvidenceCell({ text }: { text: string | null }) {
  const { t } = useI18n()
  const [open, setOpen] = useState(false)
  if (!text) return <>—</>
  if (text.length <= 100 && !open) return <span className="mirror-evidence-cell">{text}</span>
  return (
    <span className="mirror-evidence-cell">
      {open ? text : text.slice(0, 100) + '…'}
      <button type="button" className="btn btn-sm" style={{ marginLeft: 4 }} onClick={() => setOpen(v => !v)}>
        {open ? t('llmExtraction.hideRaw') : t('llmExtraction.showRaw')}
      </button>
    </span>
  )
}

function MirrorFilterBar({
  sourceAtlas, onSourceAtlas,
  granularity, onGranularity,
  mirrorStatus, onMirrorStatus,
  reviewStatus, onReviewStatus,
  llmRunId, onLlmRunId,
}: {
  sourceAtlas: string; onSourceAtlas: (v: string) => void
  granularity: string; onGranularity: (v: string) => void
  mirrorStatus: string; onMirrorStatus: (v: string) => void
  reviewStatus: string; onReviewStatus: (v: string) => void
  llmRunId: string; onLlmRunId: (v: string) => void
}) {
  const { t } = useI18n()
  return (
    <div className="mirror-kg-filter-bar filter-bar">
      <input className="filter-input" placeholder={t('mirror.filterBySourceAtlas')} value={sourceAtlas} onChange={e => onSourceAtlas(e.target.value)} />
      <input className="filter-input" placeholder={t('mirror.filterByGranularity')} value={granularity} onChange={e => onGranularity(e.target.value)} />
      <input className="filter-input" placeholder={t('mirror.filterByStatus')} value={mirrorStatus} onChange={e => onMirrorStatus(e.target.value)} />
      <input className="filter-input" placeholder={t('mirror.reviewStatus')} value={reviewStatus} onChange={e => onReviewStatus(e.target.value)} />
      <input className="filter-input" placeholder={t('mirror.llmRunId')} value={llmRunId} onChange={e => onLlmRunId(e.target.value)} />
    </div>
  )
}

function useMirrorFilters() {
  const [sourceAtlas, setSourceAtlas] = useState('')
  const [granularity, setGranularity] = useState('')
  const [mirrorStatus, setMirrorStatus] = useState('')
  const [reviewStatus, setReviewStatus] = useState('')
  const [llmRunId, setLlmRunId] = useState('')
  const [applied, setApplied] = useState({ sourceAtlas: '', granularity: '', mirrorStatus: '', reviewStatus: '', llmRunId: '' })
  const apply = () => setApplied({ sourceAtlas, granularity, mirrorStatus, reviewStatus, llmRunId })
  return {
    sourceAtlas, setSourceAtlas, granularity, setGranularity,
    mirrorStatus, setMirrorStatus, reviewStatus, setReviewStatus,
    llmRunId, setLlmRunId, applied, apply,
  }
}

function MirrorConnectionsTab({ onViewRuns, onViewItems }: {
  onViewRuns?: () => void
  onViewItems?: (runId: string) => void
}) {
  const { t } = useI18n()
  const sess = readSessionIds()
  const f = useMirrorFilters()
  const [tableTick, setTableTick] = useState(0)
  const [checked, setChecked] = useState<Set<string>>(new Set())
  const [provider, setProvider] = useState('deepseek')
  const [modelName, setModelName] = useState('')
  const [pairStrategy, setPairStrategy] = useState<'all_pairs' | 'region_centered'>('all_pairs')
  const [centerCandidateId, setCenterCandidateId] = useState('')
  const [maxPairs, setMaxPairs] = useState(200)
  const [dryRun, setDryRun] = useState(false)
  const [createMirror, setCreateMirror] = useState(true)
  const [createTriples, setCreateTriples] = useState(true)
  const [createEvidence, setCreateEvidence] = useState(true)
  const [batchFilter, setBatchFilter] = useState(sess.batch_id ?? '')
  const [statusFilter, setStatusFilter] = useState('')
  const [running, setRunning] = useState(false)
  const [notice, setNotice] = useState<NoticeState | null>(null)
  const [result, setResult] = useState<SameGranularityConnectionExtractionResponse | null>(null)
  const [showPrompt, setShowPrompt] = useState(false)

  const { data: providersData } = useData(() => listLlmProviders(), [])
  const providers = providersData?.providers ?? []
  const currentProvider = providers.find(p => p.name === provider)

  useEffect(() => {
    if (currentProvider && !modelName) setModelName(currentProvider.default_model)
  }, [currentProvider, modelName])

  const { data: candData, loading: candLoading } = useData(
    () => fetchCandidates({ batch_id: batchFilter || undefined, limit: 200 }),
    [batchFilter],
  )
  const candidates = candData?.items ?? []
  const selected = candidates.filter(c => checked.has(c.id))

  const pairCount = useMemo(() => {
    const n = selected.length
    if (n < 2) return 0
    if (pairStrategy === 'region_centered') return centerCandidateId ? n - 1 : 0
    return (n * (n - 1)) / 2
  }, [selected, pairStrategy, centerCandidateId])

  const params = {
    source_atlas: f.applied.sourceAtlas || undefined,
    granularity_level: f.applied.granularity || undefined,
    mirror_status: f.applied.mirrorStatus || undefined,
    review_status: f.applied.reviewStatus || undefined,
    llm_run_id: f.applied.llmRunId || undefined,
    limit: 100,
  }
  const { data, loading, error } = useData(
    () => listMirrorConnections(params),
    [JSON.stringify(params), tableTick],
  )

  const validateSelection = (): string | null => {
    if (selected.length < 2) return t('llm.connections.selectedCandidates') + ': min 2'
    const atlases = new Set(selected.map(c => c.source_atlas))
    if (atlases.size > 1) return t('llm.connections.crossAtlasNotAllowed')
    const levels = new Set(selected.map(c => c.granularity_level))
    if (levels.size > 1) return t('llm.connections.crossGranularityNotAllowed')
    if (pairStrategy === 'region_centered' && !centerCandidateId) return t('llm.connections.centerCandidate')
    return null
  }

  const runExtraction = async (previewOnly: boolean) => {
    const err = validateSelection()
    if (err) {
      setNotice({ type: 'error', message: err })
      return
    }
    setRunning(true)
    setNotice(null)
    try {
      const res = await runSameGranularityConnectionExtraction({
        provider,
        model_name: modelName || undefined,
        candidate_ids: selected.map(c => c.id),
        scope: {
          batch_id: batchFilter || selected[0]?.batch_id,
          source_atlas: selected[0]?.source_atlas,
          granularity_level: selected[0]?.granularity_level,
          granularity_family: selected[0]?.granularity_family,
        },
        dry_run: previewOnly || dryRun,
        max_candidate_pairs: maxPairs,
        pair_strategy: pairStrategy,
        center_candidate_id: pairStrategy === 'region_centered' ? centerCandidateId : undefined,
        create_mirror_records: createMirror,
        create_triples: createTriples,
        create_evidence: createEvidence,
      })
      setResult(res)
      if (previewOnly || dryRun) setShowPrompt(true)
      else setTableTick(t => t + 1)
      setNotice({
        type: 'success',
        message: previewOnly || dryRun
          ? t('llm.connections.dryRunPromptPreview')
          : t('llm.connections.result'),
      })
    } catch (e) {
      const msg = e instanceof ApiError ? e.message : String(e)
      setNotice({ type: 'error', message: msg })
    } finally {
      setRunning(false)
    }
  }

  const candCols: Column<CandidateBrainRegion>[] = useMemo(() => [
    {
      key: 'sel', header: t('llmExtraction.select'), width: 48,
      render: r => (
        <input type="checkbox" checked={checked.has(r.id)} onChange={e => {
          e.stopPropagation()
          setChecked(prev => {
            const next = new Set(prev)
            if (next.has(r.id)) next.delete(r.id)
            else next.add(r.id)
            return next
          })
        }} onClick={e => e.stopPropagation()} />
      ),
    },
    { key: 'cn_name', header: t('common.cnName'), render: r => r.cn_name ?? r.en_name ?? r.raw_name },
    { key: 'en_name', header: t('common.enName'), render: r => r.en_name ?? '—' },
    { key: 'source_atlas', header: 'atlas', render: r => r.source_atlas },
    { key: 'granularity', header: 'granularity', render: r => `${r.granularity_level}/${r.granularity_family}` },
    { key: 'candidate_status', header: t('llmExtraction.candidateStatus'), render: r => <StatusBadge status={r.candidate_status} /> },
  ], [t, checked])

  const cols: Column<MirrorRegionConnection>[] = useMemo(() => [
    { key: 'id', header: 'connection_id', render: r => <code className="text-mono" style={{ fontSize: 11 }}>{r.id.slice(0, 10)}…</code> },
    { key: 'source', header: t('mirror.sourceRegion'), render: r => r.source_region_candidate_id?.slice(0, 8) ?? '—' },
    { key: 'target', header: t('mirror.targetRegion'), render: r => r.target_region_candidate_id?.slice(0, 8) ?? '—' },
    { key: 'connection_type', header: t('mirror.connectionType'), render: r => r.connection_type },
    { key: 'directionality', header: t('mirror.directionality'), render: r => r.directionality },
    { key: 'confidence', header: t('mirror.confidence'), render: r => <ConfidenceCell value={r.confidence} /> },
    { key: 'evidence_text', header: t('mirror.evidenceText'), render: r => <EvidenceCell text={r.evidence_text} /> },
    { key: 'mirror_status', header: t('mirror.mirrorStatus'), render: r => <StatusBadge status={r.mirror_status} /> },
    { key: 'review_status', header: t('mirror.reviewStatus'), render: r => <StatusBadge status={r.review_status} /> },
    { key: 'promotion_status', header: t('mirror.promotionStatus'), render: r => <StatusBadge status={r.promotion_status} /> },
    { key: 'llm_run_id', header: t('mirror.llmRunId'), render: r => r.llm_run_id?.slice(0, 8) ?? '—' },
    { key: 'created_at', header: t('mirror.createdAt'), render: r => r.created_at.slice(0, 19).replace('T', ' ') },
  ], [t])

  return (
    <div className="mirror-kg-panel llm-connection-workbench">
      <Notice notice={notice} onClose={() => setNotice(null)} />
      <div className="llm-not-final-warning">{t('llm.connections.notFinalWarning')}</div>
      <MacroClinicalTabMappingNote />
      <div className="llm-connection-warning">{t('llm.connections.description')}</div>
      <div className="llm-connection-control-panel card">
        <div className="llm-pair-strategy-panel">
          <label>{t('llm.provider')}
            <select className="filter-select" value={provider} onChange={e => setProvider(e.target.value)}>
              <option value="deepseek">deepseek</option>
              <option value="kimi">kimi</option>
            </select>
          </label>
          <label>{t('llm.model')}
            <input className="filter-input" value={modelName} onChange={e => setModelName(e.target.value)} />
          </label>
          <label>{t('llm.connections.pairStrategy')}
            <select className="filter-select" value={pairStrategy} onChange={e => setPairStrategy(e.target.value as 'all_pairs' | 'region_centered')}>
              <option value="all_pairs">{t('llm.connections.allPairs')}</option>
              <option value="region_centered">{t('llm.connections.regionCentered')}</option>
            </select>
          </label>
          {pairStrategy === 'region_centered' && (
            <label>{t('llm.connections.centerCandidate')}
              <select className="filter-select" value={centerCandidateId} onChange={e => setCenterCandidateId(e.target.value)}>
                <option value="">—</option>
                {selected.map(c => <option key={c.id} value={c.id}>{c.cn_name ?? c.en_name ?? c.raw_name}</option>)}
              </select>
            </label>
          )}
          <label>{t('llm.connections.maxCandidatePairs')}
            <input type="number" className="filter-input" value={maxPairs} onChange={e => setMaxPairs(Number(e.target.value))} />
          </label>
          <label style={{ flexDirection: 'row', alignItems: 'center', gap: 6 }}>
            <input type="checkbox" checked={dryRun} onChange={e => setDryRun(e.target.checked)} />
            {t('llm.dryRun')}
          </label>
          <label style={{ flexDirection: 'row', alignItems: 'center', gap: 6 }}>
            <input type="checkbox" checked={createMirror} onChange={e => setCreateMirror(e.target.checked)} />
            {t('llm.connections.createMirrorRecords')}
          </label>
          <label style={{ flexDirection: 'row', alignItems: 'center', gap: 6 }}>
            <input type="checkbox" checked={createTriples} onChange={e => setCreateTriples(e.target.checked)} />
            {t('llm.connections.createTriples')}
          </label>
          <label style={{ flexDirection: 'row', alignItems: 'center', gap: 6 }}>
            <input type="checkbox" checked={createEvidence} onChange={e => setCreateEvidence(e.target.checked)} />
            {t('llm.connections.createEvidence')}
          </label>
        </div>
        <div className="filter-bar">
          <input className="filter-input" placeholder="batch_id" value={batchFilter} onChange={e => setBatchFilter(e.target.value)} />
          <select className="filter-select" value={statusFilter} onChange={e => setStatusFilter(e.target.value)}>
            <option value="">{t('llmExtraction.allStatus')}</option>
            {STATUS_OPTIONS.map(s => <option key={s} value={s}>{s}</option>)}
          </select>
          <span style={{ fontSize: 12, alignSelf: 'center' }}>
            {t('llm.connections.selectedCandidates')}: {selected.length} · {t('llm.connections.pairCount')}: {pairCount}
          </span>
          <ActionButton label={t('llm.connections.previewPrompt')} onClick={() => runExtraction(true)} disabled={running} />
          <ActionButton label={t('llm.connections.runExtraction')} onClick={() => runExtraction(false)} disabled={running || (!dryRun && !currentProvider?.configured)} loading={running} variant="primary" />
          <button type="button" className="btn" onClick={() => setChecked(new Set())}>clear</button>
        </div>
        <div className="llm-connection-candidate-table">
          <DataTable columns={candCols} rows={candidates.filter(c => !statusFilter || c.candidate_status === statusFilter)} loading={candLoading} getKey={r => r.id} emptyText={t('llmExtraction.emptyList')} />
        </div>
      </div>
      {result && (
        <div className="llm-connection-result-card card llm-mirror-result-summary">
          <div className="card-title">{t('llm.connections.result')}</div>
          {result.run_id && <div>run_id: <code>{result.run_id.slice(0, 12)}…</code> <CopyButton value={result.run_id} label="" /></div>}
          {result.item_id && <div>item_id: <code>{result.item_id.slice(0, 12)}…</code></div>}
          <div>{t('llm.connections.pairCount')}: {result.pair_count}</div>
          {result.connection_count != null && <div>{t('llm.connections.connectionCount')}: {result.connection_count}</div>}
          {result.mirror_connection_created_count != null && <div>{t('llm.connections.mirrorCreatedCount')}: {result.mirror_connection_created_count}</div>}
          {result.triple_created_count != null && <div>{t('llm.connections.tripleCreatedCount')}: {result.triple_created_count}</div>}
          {result.evidence_created_count != null && <div>{t('llm.connections.evidenceCreatedCount')}: {result.evidence_created_count}</div>}
          {result.mirror_connection_skipped_duplicate_count ? <div>{t('llm.connections.skippedDuplicates')}: {result.mirror_connection_skipped_duplicate_count}</div> : null}
          {result.warnings?.length ? <div>warnings: {result.warnings.join('; ')}</div> : null}
          <div style={{ display: 'flex', gap: 8, marginTop: 8 }}>
            {onViewRuns && <button type="button" className="btn btn-sm" onClick={onViewRuns}>{t('llm.connections.viewMirrorConnections')}</button>}
            {result.run_id && onViewItems && <button type="button" className="btn btn-sm" onClick={() => onViewItems(result.run_id!)}>{t('llm.connections.viewRunItems')}</button>}
          </div>
          {(result.system_prompt || result.user_prompt) && (
            <details className="llm-prompt-preview" open={showPrompt}>
              <summary>{t('llm.connections.dryRunPromptPreview')}</summary>
              {result.system_prompt && <pre className="llm-response-json">{result.system_prompt}</pre>}
              {result.user_prompt && <pre className="llm-response-json">{result.user_prompt}</pre>}
            </details>
          )}
        </div>
      )}
      <MirrorKgWarning />
      <div className="card mirror-kg-table">
        <MirrorFilterBar
          sourceAtlas={f.sourceAtlas}
          onSourceAtlas={f.setSourceAtlas}
          granularity={f.granularity}
          onGranularity={f.setGranularity}
          mirrorStatus={f.mirrorStatus}
          onMirrorStatus={f.setMirrorStatus}
          reviewStatus={f.reviewStatus}
          onReviewStatus={f.setReviewStatus}
          llmRunId={f.llmRunId}
          onLlmRunId={f.setLlmRunId}
        />
        <button type="button" className="btn" style={{ marginBottom: 8 }} onClick={f.apply}>{t('common.apply')}</button>
        <DataTable columns={cols} rows={data?.items ?? []} loading={loading} error={error} total={data?.total} getKey={r => r.id} emptyText={t('mirror.noConnections')} />
      </div>
    </div>
  )
}

const FUNCTION_CATEGORIES = [
  'motor', 'sensory', 'visual', 'auditory', 'language', 'memory', 'emotion',
  'executive_control', 'attention', 'autonomic', 'default_mode', 'salience',
  'reward', 'cognitive', 'unknown',
]

const FUNCTION_RELATION_TYPES = [
  'involved_in', 'associated_with', 'necessary_for', 'modulates',
  'participates_in', 'uncertain_association', 'unknown',
]

function MirrorFunctionsTab({ onViewRuns, onViewItems }: {
  onViewRuns?: () => void
  onViewItems?: (runId: string) => void
}) {
  const { t } = useI18n()
  const sess = readSessionIds()
  const f = useMirrorFilters()
  const [tableTick, setTableTick] = useState(0)
  const [checked, setChecked] = useState<Set<string>>(new Set())
  const [provider, setProvider] = useState('deepseek')
  const [modelName, setModelName] = useState('')
  const [maxFunctionsPerRegion, setMaxFunctionsPerRegion] = useState(5)
  const [allowedCategories, setAllowedCategories] = useState<Set<string>>(new Set(FUNCTION_CATEGORIES))
  const [allowedRelations, setAllowedRelations] = useState<Set<string>>(new Set(FUNCTION_RELATION_TYPES))
  const [dryRun, setDryRun] = useState(false)
  const [createMirror, setCreateMirror] = useState(true)
  const [createTriples, setCreateTriples] = useState(true)
  const [createEvidence, setCreateEvidence] = useState(true)
  const [batchFilter, setBatchFilter] = useState(sess.batch_id ?? '')
  const [statusFilter, setStatusFilter] = useState('')
  const [running, setRunning] = useState(false)
  const [notice, setNotice] = useState<NoticeState | null>(null)
  const [result, setResult] = useState<SameGranularityFunctionExtractionResponse | null>(null)
  const [showPrompt, setShowPrompt] = useState(false)

  const { data: providersData } = useData(() => listLlmProviders(), [])
  const providers = providersData?.providers ?? []
  const currentProvider = providers.find(p => p.name === provider)

  useEffect(() => {
    if (currentProvider && !modelName) setModelName(currentProvider.default_model)
  }, [currentProvider, modelName])

  const { data: candData, loading: candLoading } = useData(
    () => fetchCandidates({ batch_id: batchFilter || undefined, limit: 200 }),
    [batchFilter],
  )
  const candidates = candData?.items ?? []
  const selected = candidates.filter(c => checked.has(c.id))

  const params = {
    source_atlas: f.applied.sourceAtlas || undefined,
    granularity_level: f.applied.granularity || undefined,
    mirror_status: f.applied.mirrorStatus || undefined,
    review_status: f.applied.reviewStatus || undefined,
    llm_run_id: f.applied.llmRunId || undefined,
    limit: 100,
  }
  const { data, loading, error } = useData(
    () => listMirrorFunctions(params),
    [JSON.stringify(params), tableTick],
  )

  const toggleCategory = (cat: string) => {
    setAllowedCategories(prev => {
      const next = new Set(prev)
      if (next.has(cat)) next.delete(cat)
      else next.add(cat)
      return next
    })
  }

  const toggleRelation = (rel: string) => {
    setAllowedRelations(prev => {
      const next = new Set(prev)
      if (next.has(rel)) next.delete(rel)
      else next.add(rel)
      return next
    })
  }

  const validateSelection = (): string | null => {
    if (selected.length < 1) return t('llm.functions.selectedCandidates') + ': min 1'
    if (selected.length > 30) return t('llm.functions.selectedCandidates') + ': max 30'
    const atlases = new Set(selected.map(c => c.source_atlas))
    if (atlases.size > 1) return t('llm.functions.crossAtlasNotAllowed')
    const levels = new Set(selected.map(c => c.granularity_level))
    if (levels.size > 1) return t('llm.functions.crossGranularityNotAllowed')
    if (maxFunctionsPerRegion < 1 || maxFunctionsPerRegion > 10) return t('llm.functions.maxFunctionsPerRegion') + ': 1–10'
    return null
  }

  const runExtraction = async (previewOnly: boolean) => {
    const err = validateSelection()
    if (err) {
      setNotice({ type: 'error', message: err })
      return
    }
    setRunning(true)
    setNotice(null)
    try {
      const res = await runSameGranularityFunctionExtraction({
        provider,
        model_name: modelName || undefined,
        candidate_ids: selected.map(c => c.id),
        scope: {
          batch_id: batchFilter || selected[0]?.batch_id,
          source_atlas: selected[0]?.source_atlas,
          granularity_level: selected[0]?.granularity_level,
          granularity_family: selected[0]?.granularity_family,
        },
        dry_run: previewOnly || dryRun,
        max_functions_per_region: maxFunctionsPerRegion,
        allowed_function_categories: [...allowedCategories],
        allowed_relation_types: [...allowedRelations],
        create_mirror_records: createMirror,
        create_triples: createTriples,
        create_evidence: createEvidence,
      })
      setResult(res)
      if (previewOnly || dryRun) setShowPrompt(true)
      else setTableTick(t => t + 1)
      setNotice({
        type: 'success',
        message: previewOnly || dryRun
          ? t('llm.functions.dryRunPromptPreview')
          : t('llm.functions.result'),
      })
    } catch (e) {
      const msg = e instanceof ApiError ? e.message : String(e)
      setNotice({ type: 'error', message: msg })
    } finally {
      setRunning(false)
    }
  }

  const candCols: Column<CandidateBrainRegion>[] = useMemo(() => [
    {
      key: 'sel', header: t('llmExtraction.select'), width: 48,
      render: r => (
        <input type="checkbox" checked={checked.has(r.id)} onChange={e => {
          e.stopPropagation()
          setChecked(prev => {
            const next = new Set(prev)
            if (next.has(r.id)) next.delete(r.id)
            else next.add(r.id)
            return next
          })
        }} onClick={e => e.stopPropagation()} />
      ),
    },
    { key: 'cn_name', header: t('common.cnName'), render: r => r.cn_name ?? r.en_name ?? r.raw_name },
    { key: 'en_name', header: t('common.enName'), render: r => r.en_name ?? '—' },
    { key: 'laterality', header: 'laterality', render: r => r.laterality ?? '—' },
    { key: 'source_atlas', header: 'atlas', render: r => r.source_atlas },
    { key: 'granularity', header: 'granularity', render: r => `${r.granularity_level}/${r.granularity_family}` },
    { key: 'candidate_status', header: t('llmExtraction.candidateStatus'), render: r => <StatusBadge status={r.candidate_status} /> },
    { key: 'id', header: 'id', render: r => <code className="text-mono" style={{ fontSize: 11 }}>{r.id.slice(0, 8)}…</code> },
  ], [t, checked])

  const cols: Column<MirrorRegionFunction>[] = useMemo(() => [
    { key: 'id', header: 'function_id', render: r => <code className="text-mono" style={{ fontSize: 11 }}>{r.id.slice(0, 10)}…</code> },
    { key: 'region', header: t('mirror.region'), render: r => r.region_candidate_id?.slice(0, 8) ?? '—' },
    { key: 'function_term', header: t('mirror.functionTerm'), render: r => r.function_term },
    { key: 'function_category', header: t('mirror.functionCategory'), render: r => r.function_category },
    { key: 'relation_type', header: t('mirror.relationType'), render: r => r.relation_type },
    { key: 'confidence', header: t('mirror.confidence'), render: r => <ConfidenceCell value={r.confidence} /> },
    { key: 'evidence_text', header: t('mirror.evidenceText'), render: r => <EvidenceCell text={r.evidence_text} /> },
    { key: 'mirror_status', header: t('mirror.mirrorStatus'), render: r => <StatusBadge status={r.mirror_status} /> },
    { key: 'review_status', header: t('mirror.reviewStatus'), render: r => <StatusBadge status={r.review_status} /> },
    { key: 'promotion_status', header: t('mirror.promotionStatus'), render: r => <StatusBadge status={r.promotion_status} /> },
    { key: 'llm_run_id', header: t('mirror.llmRunId'), render: r => r.llm_run_id?.slice(0, 8) ?? '—' },
    { key: 'created_at', header: t('mirror.createdAt'), render: r => r.created_at.slice(0, 19).replace('T', ' ') },
  ], [t])

  return (
    <div className="mirror-kg-panel llm-function-workbench">
      <Notice notice={notice} onClose={() => setNotice(null)} />
      <div className="llm-not-final-warning">{t('llm.functions.notFinalWarning')}</div>
      <MacroClinicalTabMappingNote />
      <div className="llm-function-warning">{t('llm.functions.description')}</div>
      <div className="llm-function-control-panel card">
        <div className="llm-function-category-panel">
          <label>{t('llm.provider')}
            <select className="filter-select" value={provider} onChange={e => setProvider(e.target.value)}>
              <option value="deepseek">deepseek</option>
              <option value="kimi">kimi</option>
            </select>
          </label>
          <label>{t('llm.model')}
            <input className="filter-input" value={modelName} onChange={e => setModelName(e.target.value)} />
          </label>
          <label>{t('llm.functions.maxFunctionsPerRegion')}
            <input type="number" className="filter-input" min={1} max={10} value={maxFunctionsPerRegion} onChange={e => setMaxFunctionsPerRegion(Number(e.target.value))} />
          </label>
          <label style={{ flexDirection: 'row', alignItems: 'center', gap: 6 }}>
            <input type="checkbox" checked={dryRun} onChange={e => setDryRun(e.target.checked)} />
            {t('llm.dryRun')}
          </label>
          <label style={{ flexDirection: 'row', alignItems: 'center', gap: 6 }}>
            <input type="checkbox" checked={createMirror} onChange={e => setCreateMirror(e.target.checked)} />
            {t('llm.functions.createMirrorRecords')}
          </label>
          <label style={{ flexDirection: 'row', alignItems: 'center', gap: 6 }}>
            <input type="checkbox" checked={createTriples} onChange={e => setCreateTriples(e.target.checked)} />
            {t('llm.functions.createTriples')}
          </label>
          <label style={{ flexDirection: 'row', alignItems: 'center', gap: 6 }}>
            <input type="checkbox" checked={createEvidence} onChange={e => setCreateEvidence(e.target.checked)} />
            {t('llm.functions.createEvidence')}
          </label>
        </div>
        <div className="llm-function-relation-panel">
          <div className="panel-label">{t('llm.functions.allowedCategories')}</div>
          <div className="checkbox-grid">
            {FUNCTION_CATEGORIES.map(cat => (
              <label key={cat} style={{ flexDirection: 'row', alignItems: 'center', gap: 4, fontSize: 12 }}>
                <input type="checkbox" checked={allowedCategories.has(cat)} onChange={() => toggleCategory(cat)} />
                {cat}
              </label>
            ))}
          </div>
          <div className="panel-label">{t('llm.functions.allowedRelationTypes')}</div>
          <div className="checkbox-grid">
            {FUNCTION_RELATION_TYPES.map(rel => (
              <label key={rel} style={{ flexDirection: 'row', alignItems: 'center', gap: 4, fontSize: 12 }}>
                <input type="checkbox" checked={allowedRelations.has(rel)} onChange={() => toggleRelation(rel)} />
                {rel}
              </label>
            ))}
          </div>
        </div>
        <div className="filter-bar">
          <input className="filter-input" placeholder="batch_id" value={batchFilter} onChange={e => setBatchFilter(e.target.value)} />
          <select className="filter-select" value={statusFilter} onChange={e => setStatusFilter(e.target.value)}>
            <option value="">{t('llmExtraction.allStatus')}</option>
            {STATUS_OPTIONS.map(s => <option key={s} value={s}>{s}</option>)}
          </select>
          <span style={{ fontSize: 12, alignSelf: 'center' }}>
            {t('llm.functions.selectedCandidates')}: {selected.length}
          </span>
          <ActionButton label={t('llm.functions.previewPrompt')} onClick={() => runExtraction(true)} disabled={running} />
          <ActionButton label={t('llm.functions.runExtraction')} onClick={() => runExtraction(false)} disabled={running || (!dryRun && !currentProvider?.configured)} loading={running} variant="primary" />
          <button type="button" className="btn" onClick={() => setChecked(new Set())}>clear</button>
        </div>
        <div className="llm-function-candidate-table">
          <DataTable columns={candCols} rows={candidates.filter(c => !statusFilter || c.candidate_status === statusFilter)} loading={candLoading} getKey={r => r.id} emptyText={t('llmExtraction.emptyList')} />
        </div>
      </div>
      {result && (
        <div className="llm-function-result-card card llm-mirror-result-summary">
          <div className="card-title">{t('llm.functions.result')}</div>
          {result.run_id && <div>run_id: <code>{result.run_id.slice(0, 12)}…</code> <CopyButton value={result.run_id} label="" /></div>}
          {result.item_id && <div>item_id: <code>{result.item_id.slice(0, 12)}…</code></div>}
          <div>{t('llm.functions.selectedCandidates')}: {result.candidate_count}</div>
          {result.function_count != null && <div>{t('llm.functions.functionCount')}: {result.function_count}</div>}
          {result.mirror_function_created_count != null && <div>{t('llm.functions.mirrorCreatedCount')}: {result.mirror_function_created_count}</div>}
          {result.triple_created_count != null && <div>{t('llm.functions.tripleCreatedCount')}: {result.triple_created_count}</div>}
          {result.evidence_created_count != null && <div>{t('llm.functions.evidenceCreatedCount')}: {result.evidence_created_count}</div>}
          {result.mirror_function_skipped_duplicate_count ? <div>{t('llm.functions.skippedDuplicates')}: {result.mirror_function_skipped_duplicate_count}</div> : null}
          {result.warnings?.length ? <div>warnings: {result.warnings.join('; ')}</div> : null}
          <div style={{ display: 'flex', gap: 8, marginTop: 8 }}>
            {onViewRuns && <button type="button" className="btn btn-sm" onClick={onViewRuns}>{t('llm.functions.viewMirrorFunctions')}</button>}
            {result.run_id && onViewItems && <button type="button" className="btn btn-sm" onClick={() => onViewItems(result.run_id!)}>{t('llm.functions.viewRunItems')}</button>}
          </div>
          {(result.system_prompt || result.user_prompt) && (
            <details className="llm-prompt-preview" open={showPrompt}>
              <summary>{t('llm.functions.dryRunPromptPreview')}</summary>
              {result.system_prompt && <pre className="llm-response-json">{result.system_prompt}</pre>}
              {result.user_prompt && <pre className="llm-response-json">{result.user_prompt}</pre>}
            </details>
          )}
        </div>
      )}
      <MirrorKgWarning />
      <div className="card mirror-kg-table">
        <MirrorFilterBar
          sourceAtlas={f.sourceAtlas}
          onSourceAtlas={f.setSourceAtlas}
          granularity={f.granularity}
          onGranularity={f.setGranularity}
          mirrorStatus={f.mirrorStatus}
          onMirrorStatus={f.setMirrorStatus}
          reviewStatus={f.reviewStatus}
          onReviewStatus={f.setReviewStatus}
          llmRunId={f.llmRunId}
          onLlmRunId={f.setLlmRunId}
        />
        <button type="button" className="btn" style={{ marginBottom: 8 }} onClick={f.apply}>{t('common.apply')}</button>
        <DataTable columns={cols} rows={data?.items ?? []} loading={loading} error={error} total={data?.total} getKey={r => r.id} emptyText={t('mirror.noFunctions')} />
      </div>
    </div>
  )
}

const CIRCUIT_TYPES = [
  'sensory_circuit', 'motor_circuit', 'limbic_circuit', 'cognitive_control_circuit',
  'default_mode_related', 'salience_related', 'memory_related', 'reward_related',
  'language_related', 'attention_related', 'uncertain_circuit', 'unknown',
]

function MirrorCircuitsTab({ onViewRuns, onViewItems }: {
  onViewRuns?: () => void
  onViewItems?: (runId: string) => void
}) {
  const { t } = useI18n()
  const sess = readSessionIds()
  const f = useMirrorFilters()
  const [tableTick, setTableTick] = useState(0)
  const [checked, setChecked] = useState<Set<string>>(new Set())
  const [expandedCircuitId, setExpandedCircuitId] = useState<string | null>(null)
  const [expandedRegions, setExpandedRegions] = useState<MirrorCircuitRegion[]>([])
  const [provider, setProvider] = useState('deepseek')
  const [modelName, setModelName] = useState('')
  const [maxCircuits, setMaxCircuits] = useState(10)
  const [minRegions, setMinRegions] = useState(2)
  const [maxRegions, setMaxRegions] = useState(12)
  const [includeConnections, setIncludeConnections] = useState(true)
  const [includeFunctions, setIncludeFunctions] = useState(true)
  const [allowedTypes, setAllowedTypes] = useState<Set<string>>(new Set(CIRCUIT_TYPES))
  const [dryRun, setDryRun] = useState(false)
  const [createMirror, setCreateMirror] = useState(true)
  const [createTriples, setCreateTriples] = useState(true)
  const [createEvidence, setCreateEvidence] = useState(true)
  const [batchFilter, setBatchFilter] = useState(sess.batch_id ?? '')
  const [statusFilter, setStatusFilter] = useState('')
  const [running, setRunning] = useState(false)
  const [notice, setNotice] = useState<NoticeState | null>(null)
  const [result, setResult] = useState<SameGranularityCircuitExtractionResponse | null>(null)
  const [showPrompt, setShowPrompt] = useState(false)

  const { data: providersData } = useData(() => listLlmProviders(), [])
  const providers = providersData?.providers ?? []
  const currentProvider = providers.find(p => p.name === provider)

  useEffect(() => {
    if (currentProvider && !modelName) setModelName(currentProvider.default_model)
  }, [currentProvider, modelName])

  const { data: candData, loading: candLoading } = useData(
    () => fetchCandidates({ batch_id: batchFilter || undefined, limit: 200 }),
    [batchFilter],
  )
  const candidates = candData?.items ?? []
  const selected = candidates.filter(c => checked.has(c.id))

  const scopeParams = useMemo(() => ({
    batch_id: batchFilter || selected[0]?.batch_id || undefined,
    source_atlas: selected[0]?.source_atlas || undefined,
    granularity_level: selected[0]?.granularity_level || undefined,
  }), [batchFilter, selected])

  const { data: connCtx } = useData(
    () => listMirrorConnections({ ...scopeParams, limit: 200 }),
    [JSON.stringify(scopeParams), includeConnections],
  )
  const { data: fnCtx } = useData(
    () => listMirrorFunctions({ ...scopeParams, limit: 200 }),
    [JSON.stringify(scopeParams), includeFunctions],
  )

  const params = {
    source_atlas: f.applied.sourceAtlas || undefined,
    granularity_level: f.applied.granularity || undefined,
    mirror_status: f.applied.mirrorStatus || undefined,
    review_status: f.applied.reviewStatus || undefined,
    llm_run_id: f.applied.llmRunId || undefined,
    limit: 100,
  }
  const { data, loading, error } = useData(
    () => listMirrorCircuits(params),
    [JSON.stringify(params), tableTick],
  )

  const toggleType = (ct: string) => {
    setAllowedTypes(prev => {
      const next = new Set(prev)
      if (next.has(ct)) next.delete(ct)
      else next.add(ct)
      return next
    })
  }

  const validateSelection = (): string | null => {
    if (selected.length < 2) return t('llm.circuits.selectedCandidates') + ': min 2'
    if (selected.length > 50) return t('llm.circuits.selectedCandidates') + ': max 50'
    const atlases = new Set(selected.map(c => c.source_atlas))
    if (atlases.size > 1) return t('llm.circuits.crossAtlasNotAllowed')
    const levels = new Set(selected.map(c => c.granularity_level))
    if (levels.size > 1) return t('llm.circuits.crossGranularityNotAllowed')
    if (maxCircuits < 1 || maxCircuits > 20) return t('llm.circuits.maxCircuits') + ': 1–20'
    if (minRegions < 2) return t('llm.circuits.minRegionsPerCircuit') + ': >=2'
    if (maxRegions < minRegions) return t('llm.circuits.maxRegionsPerCircuit') + ' >= min'
    return null
  }

  const runExtraction = async (previewOnly: boolean) => {
    const err = validateSelection()
    if (err) {
      setNotice({ type: 'error', message: err })
      return
    }
    setRunning(true)
    setNotice(null)
    try {
      const res = await runSameGranularityCircuitExtraction({
        provider,
        model_name: modelName || undefined,
        candidate_ids: selected.map(c => c.id),
        scope: {
          batch_id: batchFilter || selected[0]?.batch_id,
          source_atlas: selected[0]?.source_atlas,
          granularity_level: selected[0]?.granularity_level,
          granularity_family: selected[0]?.granularity_family,
        },
        dry_run: previewOnly || dryRun,
        max_circuits: maxCircuits,
        min_regions_per_circuit: minRegions,
        max_regions_per_circuit: maxRegions,
        include_connection_context: includeConnections,
        include_function_context: includeFunctions,
        allowed_circuit_types: [...allowedTypes],
        create_mirror_records: createMirror,
        create_triples: createTriples,
        create_evidence: createEvidence,
      })
      setResult(res)
      if (previewOnly || dryRun) setShowPrompt(true)
      else setTableTick(t => t + 1)
      setNotice({
        type: 'success',
        message: previewOnly || dryRun
          ? t('llm.circuits.dryRunPromptPreview')
          : t('llm.circuits.result'),
      })
    } catch (e) {
      const msg = e instanceof ApiError ? e.message : String(e)
      setNotice({ type: 'error', message: msg })
    } finally {
      setRunning(false)
    }
  }

  const expandCircuit = async (circuitId: string) => {
    if (expandedCircuitId === circuitId) {
      setExpandedCircuitId(null)
      setExpandedRegions([])
      return
    }
    try {
      const detail = await getMirrorCircuit(circuitId)
      setExpandedCircuitId(circuitId)
      setExpandedRegions(detail.circuit_regions ?? [])
    } catch {
      setExpandedCircuitId(circuitId)
      setExpandedRegions([])
    }
  }

  const candCols: Column<CandidateBrainRegion>[] = useMemo(() => [
    {
      key: 'sel', header: t('llmExtraction.select'), width: 48,
      render: r => (
        <input type="checkbox" checked={checked.has(r.id)} onChange={e => {
          e.stopPropagation()
          setChecked(prev => {
            const next = new Set(prev)
            if (next.has(r.id)) next.delete(r.id)
            else next.add(r.id)
            return next
          })
        }} onClick={e => e.stopPropagation()} />
      ),
    },
    { key: 'cn_name', header: t('common.cnName'), render: r => r.cn_name ?? r.en_name ?? r.raw_name },
    { key: 'en_name', header: t('common.enName'), render: r => r.en_name ?? '—' },
    { key: 'laterality', header: 'laterality', render: r => r.laterality ?? '—' },
    { key: 'source_atlas', header: 'atlas', render: r => r.source_atlas },
    { key: 'granularity', header: 'granularity', render: r => `${r.granularity_level}/${r.granularity_family}` },
    { key: 'candidate_status', header: t('llmExtraction.candidateStatus'), render: r => <StatusBadge status={r.candidate_status} /> },
    { key: 'id', header: 'id', render: r => <code className="text-mono" style={{ fontSize: 11 }}>{r.id.slice(0, 8)}…</code> },
  ], [t, checked])

  const cols: Column<MirrorRegionCircuit>[] = useMemo(() => [
    { key: 'id', header: 'circuit_id', render: r => <code className="text-mono" style={{ fontSize: 11 }}>{r.id.slice(0, 10)}…</code> },
    { key: 'circuit_name', header: t('mirror.circuitName'), render: r => r.circuit_name },
    { key: 'circuit_type', header: t('mirror.circuitType'), render: r => r.circuit_type },
    { key: 'function_association', header: t('mirror.functionAssociation'), render: r => r.function_association ?? '—' },
    { key: 'confidence', header: t('mirror.confidence'), render: r => <ConfidenceCell value={r.confidence} /> },
    { key: 'regions', header: 'regions', render: r => (
      <button type="button" className="btn btn-sm" onClick={() => expandCircuit(r.id)}>
        {expandedCircuitId === r.id ? 'hide' : 'show'}
      </button>
    ) },
    { key: 'mirror_status', header: t('mirror.mirrorStatus'), render: r => <StatusBadge status={r.mirror_status} /> },
    { key: 'review_status', header: t('mirror.reviewStatus'), render: r => <StatusBadge status={r.review_status} /> },
    { key: 'promotion_status', header: t('mirror.promotionStatus'), render: r => <StatusBadge status={r.promotion_status} /> },
    { key: 'llm_run_id', header: t('mirror.llmRunId'), render: r => r.llm_run_id?.slice(0, 8) ?? '—' },
    { key: 'created_at', header: t('mirror.createdAt'), render: r => r.created_at.slice(0, 19).replace('T', ' ') },
  ], [t, expandedCircuitId])

  const contextMissing = includeConnections && includeFunctions
    && (connCtx?.total ?? 0) === 0 && (fnCtx?.total ?? 0) === 0

  return (
    <div className="mirror-kg-panel llm-circuit-workbench">
      <Notice notice={notice} onClose={() => setNotice(null)} />
      <div className="llm-not-final-warning">{t('llm.circuits.notFinalWarning')}</div>
      <MacroClinicalTabMappingNote />
      <div className="llm-circuit-warning">{t('llm.circuits.description')}</div>
      {contextMissing && selected.length >= 2 && (
        <div className="llm-circuit-warning">{t('llm.circuits.contextMissingWarning')}</div>
      )}
      <div className="llm-circuit-control-panel card">
        <div className="llm-circuit-type-panel">
          <label>{t('llm.provider')}
            <select className="filter-select" value={provider} onChange={e => setProvider(e.target.value)}>
              <option value="deepseek">deepseek</option>
              <option value="kimi">kimi</option>
            </select>
          </label>
          <label>{t('llm.model')}
            <input className="filter-input" value={modelName} onChange={e => setModelName(e.target.value)} />
          </label>
          <label>{t('llm.circuits.maxCircuits')}
            <input type="number" className="filter-input" min={1} max={20} value={maxCircuits} onChange={e => setMaxCircuits(Number(e.target.value))} />
          </label>
          <label>{t('llm.circuits.minRegionsPerCircuit')}
            <input type="number" className="filter-input" min={2} value={minRegions} onChange={e => setMinRegions(Number(e.target.value))} />
          </label>
          <label>{t('llm.circuits.maxRegionsPerCircuit')}
            <input type="number" className="filter-input" min={2} value={maxRegions} onChange={e => setMaxRegions(Number(e.target.value))} />
          </label>
          <label style={{ flexDirection: 'row', alignItems: 'center', gap: 6 }}>
            <input type="checkbox" checked={includeConnections} onChange={e => setIncludeConnections(e.target.checked)} />
            {t('llm.circuits.includeConnectionContext')}
          </label>
          <label style={{ flexDirection: 'row', alignItems: 'center', gap: 6 }}>
            <input type="checkbox" checked={includeFunctions} onChange={e => setIncludeFunctions(e.target.checked)} />
            {t('llm.circuits.includeFunctionContext')}
          </label>
          <label style={{ flexDirection: 'row', alignItems: 'center', gap: 6 }}>
            <input type="checkbox" checked={dryRun} onChange={e => setDryRun(e.target.checked)} />
            {t('llm.dryRun')}
          </label>
          <label style={{ flexDirection: 'row', alignItems: 'center', gap: 6 }}>
            <input type="checkbox" checked={createMirror} onChange={e => setCreateMirror(e.target.checked)} />
            {t('llm.circuits.createMirrorRecords')}
          </label>
          <label style={{ flexDirection: 'row', alignItems: 'center', gap: 6 }}>
            <input type="checkbox" checked={createTriples} onChange={e => setCreateTriples(e.target.checked)} />
            {t('llm.circuits.createTriples')}
          </label>
          <label style={{ flexDirection: 'row', alignItems: 'center', gap: 6 }}>
            <input type="checkbox" checked={createEvidence} onChange={e => setCreateEvidence(e.target.checked)} />
            {t('llm.circuits.createEvidence')}
          </label>
        </div>
        <div className="llm-circuit-context-panel">
          <span>{t('llm.circuits.connectionContextCount')}: {includeConnections ? (connCtx?.total ?? 0) : 0}</span>
          <span>{t('llm.circuits.functionContextCount')}: {includeFunctions ? (fnCtx?.total ?? 0) : 0}</span>
          <div className="panel-label">{t('llm.circuits.allowedCircuitTypes')}</div>
          <div className="checkbox-grid">
            {CIRCUIT_TYPES.map(ct => (
              <label key={ct} style={{ flexDirection: 'row', alignItems: 'center', gap: 4, fontSize: 12 }}>
                <input type="checkbox" checked={allowedTypes.has(ct)} onChange={() => toggleType(ct)} />
                {ct}
              </label>
            ))}
          </div>
        </div>
        <div className="filter-bar">
          <input className="filter-input" placeholder="batch_id" value={batchFilter} onChange={e => setBatchFilter(e.target.value)} />
          <select className="filter-select" value={statusFilter} onChange={e => setStatusFilter(e.target.value)}>
            <option value="">{t('llmExtraction.allStatus')}</option>
            {STATUS_OPTIONS.map(s => <option key={s} value={s}>{s}</option>)}
          </select>
          <span style={{ fontSize: 12, alignSelf: 'center' }}>
            {t('llm.circuits.selectedCandidates')}: {selected.length}
          </span>
          <ActionButton label={t('llm.circuits.previewPrompt')} onClick={() => runExtraction(true)} disabled={running} />
          <ActionButton label={t('llm.circuits.runExtraction')} onClick={() => runExtraction(false)} disabled={running || (!dryRun && !currentProvider?.configured)} loading={running} variant="primary" />
          <button type="button" className="btn" onClick={() => setChecked(new Set())}>clear</button>
        </div>
        <div className="llm-circuit-candidate-table">
          <DataTable columns={candCols} rows={candidates.filter(c => !statusFilter || c.candidate_status === statusFilter)} loading={candLoading} getKey={r => r.id} emptyText={t('llmExtraction.emptyList')} />
        </div>
      </div>
      {result && (
        <div className="llm-circuit-result-card card llm-mirror-result-summary">
          <div className="card-title">{t('llm.circuits.result')}</div>
          {result.run_id && <div>run_id: <code>{result.run_id.slice(0, 12)}…</code> <CopyButton value={result.run_id} label="" /></div>}
          {result.item_id && <div>item_id: <code>{result.item_id.slice(0, 12)}…</code></div>}
          <div>{t('llm.circuits.connectionContextCount')}: {result.connection_context_count ?? 0}</div>
          <div>{t('llm.circuits.functionContextCount')}: {result.function_context_count ?? 0}</div>
          {result.circuit_count != null && <div>{t('llm.circuits.circuitCount')}: {result.circuit_count}</div>}
          {result.mirror_circuit_created_count != null && <div>{t('llm.circuits.mirrorCreatedCount')}: {result.mirror_circuit_created_count}</div>}
          {result.circuit_region_created_count != null && <div>{t('llm.circuits.circuitRegionCreatedCount')}: {result.circuit_region_created_count}</div>}
          {result.triple_created_count != null && <div>{t('llm.circuits.tripleCreatedCount')}: {result.triple_created_count}</div>}
          {result.evidence_created_count != null && <div>{t('llm.circuits.evidenceCreatedCount')}: {result.evidence_created_count}</div>}
          {result.mirror_circuit_skipped_duplicate_count ? <div>{t('llm.circuits.skippedDuplicates')}: {result.mirror_circuit_skipped_duplicate_count}</div> : null}
          {result.warnings?.length ? <div>warnings: {result.warnings.join('; ')}</div> : null}
          <div style={{ display: 'flex', gap: 8, marginTop: 8 }}>
            {onViewRuns && <button type="button" className="btn btn-sm" onClick={onViewRuns}>{t('llm.circuits.viewMirrorCircuits')}</button>}
            {result.run_id && onViewItems && <button type="button" className="btn btn-sm" onClick={() => onViewItems(result.run_id!)}>{t('llm.circuits.viewRunItems')}</button>}
          </div>
          {(result.system_prompt || result.user_prompt) && (
            <details className="llm-prompt-preview" open={showPrompt}>
              <summary>{t('llm.circuits.dryRunPromptPreview')}</summary>
              {result.system_prompt && <pre className="llm-response-json">{result.system_prompt}</pre>}
              {result.user_prompt && <pre className="llm-response-json">{result.user_prompt}</pre>}
            </details>
          )}
        </div>
      )}
      {expandedCircuitId && expandedRegions.length > 0 && (
        <div className="llm-circuit-regions-preview card">
          <div className="card-title">involved regions ({expandedCircuitId.slice(0, 8)}…)</div>
          <ul style={{ margin: 0, paddingLeft: 18, fontSize: 12 }}>
            {expandedRegions.map(cr => (
              <li key={cr.id}>{cr.region_candidate_id?.slice(0, 8)} — {cr.role} (#{cr.sort_order})</li>
            ))}
          </ul>
        </div>
      )}
      <MirrorKgWarning />
      <div className="card mirror-kg-table">
        <MirrorFilterBar
          sourceAtlas={f.sourceAtlas}
          onSourceAtlas={f.setSourceAtlas}
          granularity={f.granularity}
          onGranularity={f.setGranularity}
          mirrorStatus={f.mirrorStatus}
          onMirrorStatus={f.setMirrorStatus}
          reviewStatus={f.reviewStatus}
          onReviewStatus={f.setReviewStatus}
          llmRunId={f.llmRunId}
          onLlmRunId={f.setLlmRunId}
        />
        <button type="button" className="btn" style={{ marginBottom: 8 }} onClick={f.apply}>{t('common.apply')}</button>
        <DataTable columns={cols} rows={data?.items ?? []} loading={loading} error={error} total={data?.total} getKey={r => r.id} emptyText={t('mirror.noCircuits')} />
      </div>
    </div>
  )
}

function MirrorTriplesTab() {
  const { t } = useI18n()
  const sess = readSessionIds()
  const f = useMirrorFilters()
  const [tableTick, setTableTick] = useState(0)
  const [sourceTypes, setSourceTypes] = useState<Set<string>>(new Set(['connection', 'function', 'circuit']))
  const [batchFilter, setBatchFilter] = useState(sess.batch_id ?? '')
  const [resourceFilter, setResourceFilter] = useState(sess.resource_id ?? '')
  const [sourceAtlas, setSourceAtlas] = useState('')
  const [granularityLevel, setGranularityLevel] = useState('')
  const [granularityFamily, setGranularityFamily] = useState('')
  const [dryRun, setDryRun] = useState(true)
  const [includeExisting, setIncludeExisting] = useState(false)
  const [limit, setLimit] = useState(1000)
  const [running, setRunning] = useState(false)
  const [showConfirm, setShowConfirm] = useState(false)
  const [notice, setNotice] = useState<NoticeState | null>(null)
  const [result, setResult] = useState<MirrorTripleConsolidationResponse | null>(null)

  const scopeParams = useMemo(() => ({
    batch_id: batchFilter || undefined,
    resource_id: resourceFilter || undefined,
    source_atlas: sourceAtlas || undefined,
    granularity_level: granularityLevel || undefined,
  }), [batchFilter, resourceFilter, sourceAtlas, granularityLevel])

  const { data: connCtx } = useData(
    () => listMirrorConnections({ ...scopeParams, limit: 1 }),
    [JSON.stringify(scopeParams)],
  )
  const { data: fnCtx } = useData(
    () => listMirrorFunctions({ ...scopeParams, limit: 1 }),
    [JSON.stringify(scopeParams)],
  )
  const { data: circCtx } = useData(
    () => listMirrorCircuits({ ...scopeParams, limit: 1 }),
    [JSON.stringify(scopeParams)],
  )

  const params = {
    source_atlas: f.applied.sourceAtlas || undefined,
    granularity_level: f.applied.granularity || undefined,
    mirror_status: f.applied.mirrorStatus || undefined,
    review_status: f.applied.reviewStatus || undefined,
    llm_run_id: f.applied.llmRunId || undefined,
    limit: 100,
  }
  const { data, loading, error } = useData(
    () => listMirrorTriples(params),
    [JSON.stringify(params), tableTick],
  )

  const toggleSource = (st: string) => {
    setSourceTypes(prev => {
      const next = new Set(prev)
      if (next.has(st)) next.delete(st)
      else next.add(st)
      return next
    })
  }

  const validate = (): string | null => {
    if (sourceTypes.size < 1) return t('mirror.triples.sourceTypes') + ': min 1'
    if (limit < 1 || limit > 5000) return t('mirror.triples.limit') + ': 1–5000'
    return null
  }

  const runConsolidation = async (previewOnly: boolean) => {
    const err = validate()
    if (err) {
      setNotice({ type: 'error', message: err })
      return
    }
    setRunning(true)
    setNotice(null)
    try {
      const res = await consolidateMirrorTriples({
        source_types: [...sourceTypes] as Array<'connection' | 'function' | 'circuit'>,
        scope: {
          batch_id: batchFilter || undefined,
          resource_id: resourceFilter || undefined,
          source_atlas: sourceAtlas || undefined,
          granularity_level: granularityLevel || undefined,
          granularity_family: granularityFamily || undefined,
        },
        dry_run: previewOnly || dryRun,
        include_existing: includeExisting,
        limit,
      })
      setResult(res)
      if (!previewOnly && !dryRun) setTableTick(t => t + 1)
      setNotice({
        type: 'success',
        message: previewOnly || dryRun ? t('mirror.triples.preview') : t('mirror.triples.result'),
      })
    } catch (e) {
      setNotice({ type: 'error', message: e instanceof ApiError ? e.message : String(e) })
    } finally {
      setRunning(false)
      setShowConfirm(false)
    }
  }

  const onRunClick = (previewOnly: boolean) => {
    if (!previewOnly && !dryRun) {
      setShowConfirm(true)
      return
    }
    runConsolidation(previewOnly)
  }

  const previewCols: Column<MirrorTriplePreviewItem>[] = useMemo(() => [
    { key: 'subject', header: t('mirror.subject'), render: r => r.subject_label },
    { key: 'predicate', header: t('mirror.predicate'), render: r => <code className="triple-predicate">{r.predicate}</code> },
    { key: 'object', header: t('mirror.object'), render: r => r.object_label },
    { key: 'source_type', header: t('mirror.triples.sourceType'), render: r => <span className="triple-source-badge">{r.source_type}</span> },
    { key: 'confidence', header: t('mirror.confidence'), render: r => <ConfidenceCell value={r.confidence ?? null} /> },
    { key: 'duplicate', header: t('mirror.triples.duplicate'), render: r => r.duplicate ? <span className="triple-duplicate-badge">dup</span> : '—' },
    { key: 'evidence', header: t('mirror.evidenceText'), render: r => <EvidenceCell text={r.evidence_text ?? null} /> },
  ], [t])

  const cols: Column<MirrorKgTriple>[] = useMemo(() => [
    { key: 'id', header: 'triple_id', render: r => <><code className="text-mono" style={{ fontSize: 11 }}>{r.id.slice(0, 10)}…</code> <CopyButton value={r.id} label="" /></> },
    { key: 'subject_type', header: 'subj_type', render: r => r.subject_type },
    { key: 'subject_label', header: t('mirror.subject'), render: r => r.subject_label },
    { key: 'predicate', header: t('mirror.predicate'), render: r => <code className="triple-predicate">{r.predicate}</code> },
    { key: 'object_type', header: 'obj_type', render: r => r.object_type },
    { key: 'object_label', header: t('mirror.object'), render: r => r.object_label },
    { key: 'triple_scope', header: t('mirror.tripleScope'), render: r => r.triple_scope },
    { key: 'confidence', header: t('mirror.confidence'), render: r => <ConfidenceCell value={r.confidence} /> },
    { key: 'mirror_status', header: t('mirror.mirrorStatus'), render: r => <StatusBadge status={r.mirror_status} /> },
    { key: 'review_status', header: t('mirror.reviewStatus'), render: r => <StatusBadge status={r.review_status} /> },
    { key: 'promotion_status', header: t('mirror.promotionStatus'), render: r => <StatusBadge status={r.promotion_status} /> },
    { key: 'source_atlas', header: 'atlas', render: r => r.source_atlas },
    { key: 'granularity', header: 'granularity', render: r => `${r.granularity_level}/${r.granularity_family ?? '—'}` },
    { key: 'created_at', header: t('mirror.createdAt'), render: r => r.created_at.slice(0, 19).replace('T', ' ') },
  ], [t])

  const scopeWarning = !batchFilter && !resourceFilter && !sourceAtlas && !granularityLevel
  const zeroWarnings = [
    sourceTypes.has('connection') && (connCtx?.total ?? 0) === 0 ? 'connection' : null,
    sourceTypes.has('function') && (fnCtx?.total ?? 0) === 0 ? 'function' : null,
    sourceTypes.has('circuit') && (circCtx?.total ?? 0) === 0 ? 'circuit' : null,
  ].filter(Boolean)

  return (
    <div className="mirror-kg-panel triple-consolidation-workbench">
      <Notice notice={notice} onClose={() => setNotice(null)} />
      <div className="triple-consolidation-not-final">{t('mirror.triples.notFinalWarning')}</div>
      <MacroClinicalTabMappingNote />
      <div className="triple-consolidation-warning">{t('mirror.triples.notLlmWarning')}</div>
      <div className="triple-consolidation-warning">{t('mirror.triples.consolidationDescription')}</div>
      {scopeWarning && <div className="triple-consolidation-warning">{t('mirror.triples.scopeWideWarning')}</div>}
      {zeroWarnings.length > 0 && (
        <div className="triple-consolidation-warning">
          {zeroWarnings.join(', ')} count=0 in scope
        </div>
      )}
      <div className="triple-consolidation-control-panel card">
        <div className="triple-consolidation-source-types">
          <span className="panel-label">{t('mirror.triples.sourceTypes')}</span>
          {(['connection', 'function', 'circuit'] as const).map(st => (
            <label key={st} style={{ flexDirection: 'row', alignItems: 'center', gap: 4, fontSize: 12 }}>
              <input type="checkbox" checked={sourceTypes.has(st)} onChange={() => toggleSource(st)} />
              {st === 'connection' ? t('mirror.triples.sourceConnections') : st === 'function' ? t('mirror.triples.sourceFunctions') : t('mirror.triples.sourceCircuits')}
            </label>
          ))}
        </div>
        <div className="filter-bar">
          <input className="filter-input" placeholder="batch_id" value={batchFilter} onChange={e => setBatchFilter(e.target.value)} />
          <input className="filter-input" placeholder="resource_id" value={resourceFilter} onChange={e => setResourceFilter(e.target.value)} />
          <input className="filter-input" placeholder="source_atlas" value={sourceAtlas} onChange={e => setSourceAtlas(e.target.value)} />
          <input className="filter-input" placeholder="granularity_level" value={granularityLevel} onChange={e => setGranularityLevel(e.target.value)} />
          <input className="filter-input" placeholder="granularity_family" value={granularityFamily} onChange={e => setGranularityFamily(e.target.value)} />
          <label>{t('mirror.triples.limit')}
            <input type="number" className="filter-input" min={1} max={5000} value={limit} onChange={e => setLimit(Number(e.target.value))} />
          </label>
          <label style={{ flexDirection: 'row', alignItems: 'center', gap: 6 }}>
            <input type="checkbox" checked={dryRun} onChange={e => setDryRun(e.target.checked)} />
            {t('mirror.triples.dryRun')}
          </label>
          <label style={{ flexDirection: 'row', alignItems: 'center', gap: 6 }}>
            <input type="checkbox" checked={includeExisting} onChange={e => setIncludeExisting(e.target.checked)} />
            {t('mirror.triples.includeExisting')}
          </label>
          <ActionButton label={t('mirror.triples.previewConsolidation')} onClick={() => onRunClick(true)} disabled={running} />
          <ActionButton label={t('mirror.triples.runConsolidation')} onClick={() => onRunClick(false)} disabled={running} variant="primary" />
          <button type="button" className="btn" onClick={() => setTableTick(t => t + 1)}>{t('mirror.triples.refreshTriples')}</button>
        </div>
      </div>
      {result && (
        <div className="triple-consolidation-result-card card">
          <div className="card-title">{t('mirror.triples.result')}</div>
          <div>{t('mirror.triples.sourceCounts')}: connections={result.source_counts.connections ?? 0}, functions={result.source_counts.functions ?? 0}, circuits={result.source_counts.circuits ?? 0}</div>
          <div>{t('mirror.triples.plannedCount')}: {result.planned_triple_count}</div>
          <div>{t('mirror.triples.createdCount')}: {result.created_triple_count}</div>
          <div>{t('mirror.triples.skippedDuplicates')}: {result.skipped_duplicate_count}</div>
          <div>{t('mirror.triples.skippedInvalid')}: {result.skipped_invalid_count}</div>
          {result.existing_triple_count != null && <div>{t('mirror.triples.existingCount')}: {result.existing_triple_count}</div>}
          {result.warnings?.length ? <div>warnings: {result.warnings.join('; ')}</div> : null}
        </div>
      )}
      {result?.triples_preview && result.triples_preview.length > 0 && (
        <div className="triple-consolidation-preview-table card">
          <div className="card-title">{t('mirror.triples.preview')}</div>
          <DataTable columns={previewCols} rows={result.triples_preview} getKey={r => `${r.source_type}-${r.source_id}-${r.predicate}-${r.object_label}`} emptyText={t('mirror.triples.noPreview')} />
        </div>
      )}
      <MirrorKgWarning />
      <div className="card mirror-kg-table">
        <MirrorFilterBar
          sourceAtlas={f.sourceAtlas}
          onSourceAtlas={f.setSourceAtlas}
          granularity={f.granularity}
          onGranularity={f.setGranularity}
          mirrorStatus={f.mirrorStatus}
          onMirrorStatus={f.setMirrorStatus}
          reviewStatus={f.reviewStatus}
          onReviewStatus={f.setReviewStatus}
          llmRunId={f.llmRunId}
          onLlmRunId={f.setLlmRunId}
        />
        <button type="button" className="btn" style={{ marginBottom: 8 }} onClick={f.apply}>{t('common.apply')}</button>
        <DataTable columns={cols} rows={data?.items ?? []} loading={loading} error={error} total={data?.total} getKey={r => r.id} emptyText={t('mirror.noTriples')} />
      </div>
      <ConfirmDialog
        open={showConfirm}
        title={t('mirror.triples.runConsolidation')}
        message={t('mirror.triples.confirmWriteMirrorTriples')}
        confirmLabel={t('common.confirm')}
        onConfirm={() => runConsolidation(false)}
        onCancel={() => setShowConfirm(false)}
        loading={running}
      />
    </div>
  )
}

function MirrorValidationTab() {
  const { t } = useI18n()
  const sess = readSessionIds()
  const LEGACY_TARGETS = ['connection', 'function', 'circuit', 'triple'] as const
  const MACRO_TARGETS = [
    'projection',
    'circuit_step',
    'projection_function',
    'circuit_projection_membership',
    'circuit_projection_cross_validation_result',
    'dual_model_verification_result',
  ] as const
  const TARGET_LABELS: Record<string, string> = {
    connection: 'mirror.validation.connections',
    function: 'mirror.validation.functions',
    circuit: 'mirror.validation.circuits',
    triple: 'mirror.validation.triples',
    projection: 'mirror.validation.targetProjection',
    circuit_step: 'mirror.validation.targetCircuitStep',
    projection_function: 'mirror.validation.targetProjectionFunction',
    circuit_projection_membership: 'mirror.validation.targetCircuitProjectionMembership',
    circuit_projection_cross_validation_result: 'mirror.validation.targetCrossValidationResult',
    dual_model_verification_result: 'mirror.validation.targetDualModelVerificationResult',
  }
  const [targetTypes, setTargetTypes] = useState<Set<string>>(new Set(['connection', 'function', 'circuit', 'triple']))
  const [batchFilter, setBatchFilter] = useState(sess.batch_id ?? '')
  const [resourceFilter, setResourceFilter] = useState(sess.resource_id ?? '')
  const [sourceAtlas, setSourceAtlas] = useState('')
  const [granularityLevel, setGranularityLevel] = useState('')
  const [granularityFamily, setGranularityFamily] = useState('')
  const [dryRun, setDryRun] = useState(true)
  const [applyStatusUpdate, setApplyStatusUpdate] = useState(false)
  const [limit, setLimit] = useState(1000)
  const [running, setRunning] = useState(false)
  const [showConfirm, setShowConfirm] = useState(false)
  const [notice, setNotice] = useState<NoticeState | null>(null)
  const [result, setResult] = useState<MirrorValidationResponse | null>(null)
  const [runsTick, setRunsTick] = useState(0)
  const [resultsTick, setResultsTick] = useState(0)
  const [selectedRunId, setSelectedRunId] = useState('')

  const { data: runsData, loading: runsLoading, error: runsError } = useData(
    () => listMirrorValidationRuns({ limit: 50 }),
    [runsTick],
  )
  const { data: resultsData, loading: resultsLoading, error: resultsError } = useData(
    () => listMirrorValidationResults({ run_id: selectedRunId || undefined, limit: 100 }),
    [resultsTick, selectedRunId],
  )

  const toggleTarget = (tt: string) => {
    setTargetTypes(prev => {
      const next = new Set(prev)
      if (next.has(tt)) next.delete(tt)
      else next.add(tt)
      return next
    })
  }

  const validate = (): string | null => {
    if (targetTypes.size < 1) return t('mirror.validation.targetTypes') + ': min 1'
    if (limit < 1 || limit > 5000) return t('mirror.validation.limit') + ': 1–5000'
    return null
  }

  const runValidation = async (previewOnly: boolean) => {
    const err = validate()
    if (err) {
      setNotice({ type: 'error', message: err })
      return
    }
    setRunning(true)
    setNotice(null)
    try {
      const res = await runMirrorValidation({
        target_types: [...targetTypes] as MirrorValidationTargetType[],
        scope: {
          batch_id: batchFilter || undefined,
          resource_id: resourceFilter || undefined,
          source_atlas: sourceAtlas || undefined,
          granularity_level: granularityLevel || undefined,
          granularity_family: granularityFamily || undefined,
        },
        dry_run: previewOnly || dryRun,
        apply_status_update: applyStatusUpdate && !previewOnly && !dryRun,
        limit,
      })
      setResult(res)
      if (!previewOnly && !dryRun) {
        setRunsTick(x => x + 1)
        setResultsTick(x => x + 1)
        if (res.run_id) setSelectedRunId(res.run_id)
      }
      setNotice({
        type: 'success',
        message: previewOnly || dryRun ? t('mirror.validation.preview') : t('mirror.validation.run'),
      })
    } catch (e) {
      setNotice({ type: 'error', message: e instanceof ApiError ? e.message : String(e) })
    } finally {
      setRunning(false)
      setShowConfirm(false)
    }
  }

  const onRunClick = (previewOnly: boolean) => {
    if (!previewOnly && !dryRun) {
      setShowConfirm(true)
      return
    }
    runValidation(previewOnly)
  }

  const previewCols: Column<MirrorValidationResultPreview>[] = useMemo(() => [
    { key: 'target_type', header: t('mirror.validation.targetTypes'), render: r => r.target_type },
    { key: 'target_id', header: 'target_id', render: r => <code className="text-mono" style={{ fontSize: 11 }}>{r.target_id.slice(0, 10)}…</code> },
    { key: 'rule_code', header: t('mirror.validation.ruleCode'), render: r => <code>{r.rule_code}</code> },
    { key: 'severity', header: t('mirror.validation.severity'), render: r => <ValidationSeverityCell severity={r.severity} /> },
    { key: 'status', header: 'status', render: r => <span className={`validation-status-${r.status}`}>{r.status}</span> },
    { key: 'message', header: t('mirror.validation.message'), render: r => r.message },
  ], [t])

  const runsCols: Column<MirrorValidationRun>[] = useMemo(() => [
    { key: 'id', header: 'run_id', render: r => <><code className="text-mono" style={{ fontSize: 11 }}>{r.id.slice(0, 10)}…</code> <CopyButton value={r.id} label="" /></> },
    { key: 'target_types', header: t('mirror.validation.targetTypes'), render: r => r.target_types.join(', ') },
    { key: 'status', header: 'status', render: r => <StatusBadge status={r.status} /> },
    { key: 'counts', header: 'counts', render: r => `p${r.passed_count}/w${r.warning_count}/f${r.failed_count}/b${r.blocked_count}` },
    { key: 'dry_run', header: t('mirror.validation.dryRun'), render: r => r.dry_run ? 'yes' : 'no' },
    { key: 'apply', header: t('mirror.validation.applyStatusUpdate'), render: r => r.apply_status_update ? 'yes' : 'no' },
    { key: 'created_at', header: t('mirror.createdAt'), render: r => r.created_at.slice(0, 19).replace('T', ' ') },
    { key: 'actions', header: '', render: r => (
      <button type="button" className="btn btn-sm" onClick={() => { setSelectedRunId(r.id); setResultsTick(x => x + 1) }}>
        results
      </button>
    ) },
  ], [t])

  const resultsCols: Column<MirrorValidationResult>[] = useMemo(() => [
    { key: 'id', header: 'result_id', render: r => <code className="text-mono" style={{ fontSize: 11 }}>{r.id.slice(0, 8)}…</code> },
    { key: 'run_id', header: 'run_id', render: r => r.run_id.slice(0, 8) + '…' },
    { key: 'target_type', header: t('mirror.validation.targetTypes'), render: r => r.target_type },
    { key: 'target_id', header: 'target_id', render: r => r.target_id.slice(0, 8) + '…' },
    { key: 'rule_code', header: t('mirror.validation.ruleCode'), render: r => <code>{r.rule_code}</code> },
    { key: 'severity', header: t('mirror.validation.severity'), render: r => <ValidationSeverityCell severity={r.severity} /> },
    { key: 'status', header: 'status', render: r => <span className={`validation-status-${r.status}`}>{r.status}</span> },
    { key: 'message', header: t('mirror.validation.message'), render: r => r.message },
    { key: 'created_at', header: t('mirror.createdAt'), render: r => r.created_at.slice(0, 19).replace('T', ' ') },
  ], [t])

  const scopeWarning = !batchFilter && !resourceFilter && !sourceAtlas && !granularityLevel

  return (
    <div className="mirror-kg-panel mirror-validation-workbench">
      <Notice notice={notice} onClose={() => setNotice(null)} />
      <div className="mirror-validation-not-final">{t('mirror.validation.notFinalWarning')}</div>
      <div className="mirror-validation-warning">{t('mirror.validation.notLlmWarning')}</div>
      <div className="mirror-validation-warning">{t('mirror.validation.description')}</div>
      <div className="mirror-validation-warning">{t('mirror.validation.ruleCheckedExplanation')}</div>
      {scopeWarning && <div className="mirror-validation-warning">{t('mirror.triples.scopeWideWarning')}</div>}
      {applyStatusUpdate && dryRun && (
        <div className="mirror-validation-warning">{t('mirror.validation.dryRunNoStatusUpdate')}</div>
      )}
      <div className="mirror-validation-warning">{t('mirror.validation.macroClinicalDescription')}</div>
      <div className="macro-validation-signal-card card">
        <div>{t('mirror.validation.bidirectionalSignalNote')}</div>
        <div>{t('mirror.validation.dualModelSignalNote')}</div>
        <div className="validation-high-review-priority">{t('mirror.validation.modelConflictReviewNote')}</div>
        <div>{t('mirror.validation.consensusSupportedNotApproved')}</div>
        <div>{t('mirror.validation.consensusRejectedNotRejected')}</div>
        <div>{t('mirror.validation.insufficientInformationNote')}</div>
      </div>
      {targetTypes.has('circuit_projection_cross_validation_result') && (
        <div className="macro-validation-warning">{t('mirror.validation.crossValidationSignalNote')}</div>
      )}
      {targetTypes.has('dual_model_verification_result') && (
        <div className="macro-validation-warning">{t('mirror.validation.dualModelResultSignalNote')}</div>
      )}
      <div className="mirror-validation-control-panel card macro-validation-target-panel">
        <div className="mirror-validation-target-types">
          <span className="panel-label">{t('mirror.validation.targetTypes')}</span>
          {LEGACY_TARGETS.map(tt => (
            <label key={tt} style={{ flexDirection: 'row', alignItems: 'center', gap: 4, fontSize: 12 }}>
              <input type="checkbox" checked={targetTypes.has(tt)} onChange={() => toggleTarget(tt)} />
              {t(TARGET_LABELS[tt])}
            </label>
          ))}
        </div>
        <div className="mirror-validation-target-types">
          <span className="panel-label">{t('mirror.validation.macroClinicalTargets')}</span>
          {MACRO_TARGETS.map(tt => (
            <label key={tt} style={{ flexDirection: 'row', alignItems: 'center', gap: 4, fontSize: 12 }}>
              <input type="checkbox" checked={targetTypes.has(tt)} onChange={() => toggleTarget(tt)} />
              {t(TARGET_LABELS[tt])}
            </label>
          ))}
        </div>
        <div className="filter-bar">
          <input className="filter-input" placeholder="batch_id" value={batchFilter} onChange={e => setBatchFilter(e.target.value)} />
          <input className="filter-input" placeholder="resource_id" value={resourceFilter} onChange={e => setResourceFilter(e.target.value)} />
          <input className="filter-input" placeholder="source_atlas" value={sourceAtlas} onChange={e => setSourceAtlas(e.target.value)} />
          <input className="filter-input" placeholder="granularity_level" value={granularityLevel} onChange={e => setGranularityLevel(e.target.value)} />
          <input className="filter-input" placeholder="granularity_family" value={granularityFamily} onChange={e => setGranularityFamily(e.target.value)} />
          <label>{t('mirror.validation.limit')}
            <input type="number" className="filter-input" min={1} max={5000} value={limit} onChange={e => setLimit(Number(e.target.value))} />
          </label>
          <label style={{ flexDirection: 'row', alignItems: 'center', gap: 6 }}>
            <input type="checkbox" checked={dryRun} onChange={e => setDryRun(e.target.checked)} />
            {t('mirror.validation.dryRun')}
          </label>
          <label style={{ flexDirection: 'row', alignItems: 'center', gap: 6 }}>
            <input type="checkbox" checked={applyStatusUpdate} onChange={e => setApplyStatusUpdate(e.target.checked)} />
            {t('mirror.validation.applyStatusUpdate')}
          </label>
          <ActionButton label={t('mirror.validation.preview')} onClick={() => onRunClick(true)} disabled={running} />
          <ActionButton label={t('mirror.validation.run')} onClick={() => onRunClick(false)} disabled={running} variant="primary" />
          <button type="button" className="btn" onClick={() => setRunsTick(x => x + 1)}>{t('mirror.validation.runs')}</button>
          <button type="button" className="btn" onClick={() => setResultsTick(x => x + 1)}>{t('mirror.validation.results')}</button>
        </div>
      </div>
      {result && (
        <div className="mirror-validation-result-card macro-validation-summary-card card">
          <div className="card-title">{t('mirror.validation.run')}</div>
          <div>{t('mirror.validation.targetCounts')}: {Object.entries(result.target_counts).map(([k, v]) => `${k}=${v}`).join(', ')}</div>
          <div>{t('mirror.validation.passedCount')}: {result.passed_count}</div>
          <div>{t('mirror.validation.warningCount')}: {result.warning_count}</div>
          <div>{t('mirror.validation.failedCount')}: {result.failed_count}</div>
          <div className="validation-severity-blocker">{t('mirror.validation.blockedCount')}: {result.blocked_count}</div>
          {result.high_review_priority_count != null && (
            <div className="validation-high-review-priority">{t('mirror.validation.highReviewPriorityCount')}: {result.high_review_priority_count}</div>
          )}
          <div>{t('mirror.validation.resultCount')}: {result.result_count}</div>
          {result.status_updates && (
            <>
              <div className="validation-rule-checked-badge">{t('mirror.validation.ruleCheckedUpdatedCount')}: {result.status_updates.eligible_rule_checked ?? 0}</div>
              <div>{t('mirror.validation.skippedBlocked')}: {result.status_updates.skipped_blocked ?? 0}</div>
            </>
          )}
          {result.warnings?.length ? <div>warnings: {result.warnings.join('; ')}</div> : null}
        </div>
      )}
      {result?.results_preview && result.results_preview.length > 0 && (
        <div className="mirror-validation-preview-table card">
          <div className="card-title">{t('mirror.validation.resultsPreview')}</div>
          <DataTable columns={previewCols} rows={result.results_preview} getKey={r => `${r.target_type}-${r.target_id}-${r.rule_code}`} emptyText="—" />
        </div>
      )}
      <div className="card mirror-validation-runs-table">
        <div className="card-title">{t('mirror.validation.runs')}</div>
        <DataTable columns={runsCols} rows={runsData?.items ?? []} loading={runsLoading} error={runsError} total={runsData?.total} getKey={r => r.id} emptyText="—" />
      </div>
      <div className="card mirror-validation-results-table">
        <div className="card-title">{t('mirror.validation.results')}{selectedRunId ? ` (${selectedRunId.slice(0, 8)}…)` : ''}</div>
        <DataTable columns={resultsCols} rows={resultsData?.items ?? []} loading={resultsLoading} error={resultsError} total={resultsData?.total} getKey={r => r.id} emptyText="—" />
      </div>
      <ConfirmDialog
        open={showConfirm}
        title={t('mirror.validation.run')}
        message={applyStatusUpdate ? t('mirror.validation.applyStatusUpdateConfirm') : t('mirror.validation.confirmRun')}
        confirmLabel={t('common.confirm')}
        onConfirm={() => runValidation(false)}
        onCancel={() => setShowConfirm(false)}
        loading={running}
      />
    </div>
  )
}

function MirrorReviewTab() {
  const { t } = useI18n()
  const sess = readSessionIds()
  const MACRO_REVIEW_TYPES = [
    'connection', 'function', 'circuit', 'triple', 'projection', 'circuit_step',
    'projection_function', 'circuit_projection_membership',
    'circuit_projection_cross_validation_result', 'dual_model_verification_result',
  ] as const
  const [targetTypes, setTargetTypes] = useState<Set<string>>(new Set(['connection', 'function', 'circuit', 'triple']))
  const [batchFilter, setBatchFilter] = useState(sess.batch_id ?? '')
  const [resourceFilter, setResourceFilter] = useState(sess.resource_id ?? '')
  const [sourceAtlas, setSourceAtlas] = useState('')
  const [granularityLevel, setGranularityLevel] = useState('')
  const [search, setSearch] = useState('')
  const [hasBlocker, setHasBlocker] = useState<boolean | undefined>(undefined)
  const [hasError, setHasError] = useState<boolean | undefined>(undefined)
  const [hasWarning, setHasWarning] = useState<boolean | undefined>(undefined)
  const [hasModelConflict, setHasModelConflict] = useState<boolean | undefined>(undefined)
  const [hasCrossConflict, setHasCrossConflict] = useState<boolean | undefined>(undefined)
  const [consensusStatus, setConsensusStatus] = useState('')
  const [verificationStatus, setVerificationStatus] = useState('')
  const [reviewPriority, setReviewPriority] = useState('')
  const [mirrorStatusFilter, setMirrorStatusFilter] = useState('')
  const [reviewStatusFilter, setReviewStatusFilter] = useState('')
  const [promotionStatusFilter, setPromotionStatusFilter] = useState('')
  const [queueTick, setQueueTick] = useState(0)
  const [selected, setSelected] = useState<MirrorReviewQueueItem | null>(null)
  const [detail, setDetail] = useState<MirrorReviewDetail | null>(null)
  const [detailLoading, setDetailLoading] = useState(false)
  const [reviewer, setReviewer] = useState('reviewer')
  const [reviewerNote, setReviewerNote] = useState('')
  const [editPatch, setEditPatch] = useState<Record<string, string>>({})
  const [running, setRunning] = useState(false)
  const [notice, setNotice] = useState<NoticeState | null>(null)
  const [showApproveConfirm, setShowApproveConfirm] = useState(false)
  const [showRejectConfirm, setShowRejectConfirm] = useState(false)
  const [pendingAction, setPendingAction] = useState<MirrorReviewActionType | null>(null)

  const { data: targetTypeMeta } = useData(() => listMirrorReviewTargetTypes(), [])

  const queueParams = useMemo(() => ({
    target_types: [...targetTypes],
    batch_id: batchFilter || undefined,
    resource_id: resourceFilter || undefined,
    source_atlas: sourceAtlas || undefined,
    granularity_level: granularityLevel || undefined,
    has_blocker: hasBlocker,
    has_error: hasError,
    has_warning: hasWarning,
    has_model_conflict: hasModelConflict,
    has_cross_conflict: hasCrossConflict,
    consensus_status: consensusStatus || undefined,
    verification_status: verificationStatus || undefined,
    recommended_review_priority: reviewPriority || undefined,
    mirror_status: mirrorStatusFilter ? [mirrorStatusFilter] : undefined,
    review_status: reviewStatusFilter ? [reviewStatusFilter] : undefined,
    promotion_status: promotionStatusFilter ? [promotionStatusFilter] : undefined,
    search: search || undefined,
    limit: 100,
  }), [targetTypes, batchFilter, resourceFilter, sourceAtlas, granularityLevel, hasBlocker, hasError, hasWarning, hasModelConflict, hasCrossConflict, consensusStatus, verificationStatus, reviewPriority, mirrorStatusFilter, reviewStatusFilter, promotionStatusFilter, search])

  const { data: queueData, loading: queueLoading, error: queueError } = useData(
    () => listMirrorReviewQueue(queueParams),
    [JSON.stringify(queueParams), queueTick],
  )

  const openDetail = async (item: MirrorReviewQueueItem) => {
    setSelected(item)
    setDetail(null)
    setEditPatch({})
    setReviewerNote('')
    setDetailLoading(true)
    try {
      const d = await getMirrorReviewDetail(item.target_type, item.target_id)
      setDetail(d)
      const init: Record<string, string> = {}
      for (const f of d.editable_fields) {
        const v = d.object_json[f]
        if (v != null) init[f] = String(v)
      }
      setEditPatch(init)
    } catch (e) {
      setNotice({ type: 'error', message: e instanceof ApiError ? e.message : String(e) })
    } finally {
      setDetailLoading(false)
    }
  }

  const valSummary = detail?.latest_validation_summary ?? selected?.latest_validation_summary ?? {}
  const gating = detail?.gating
  const isSignal = (detail?.object_category ?? selected?.object_category) === 'signal_object'
  const canApprove = gating?.can_approve ?? (Boolean(valSummary.validated) && !valSummary.has_blocker && !valSummary.has_error
    && selected?.promotion_status !== 'promoted' && selected?.mirror_status !== 'human_approved')
  const requiresReason = gating?.requires_reviewer_reason ?? Boolean(valSummary.has_warning)

  const runAction = async (action: MirrorReviewActionType, opts?: { skipConfirm?: boolean }) => {
    if (!selected) return
    if (!reviewer.trim()) {
      setNotice({ type: 'error', message: t('mirror.review.reviewer') + ' required' })
      return
    }
    if ((action === 'reject' || action === 'needs_revision' || action === 'comment') && !reviewerNote.trim()) {
      setNotice({ type: 'error', message: action === 'reject' ? t('mirror.review.rejectNoteRequired') : t('mirror.review.revisionNoteRequired') })
      return
    }
    if (action === 'approve' && requiresReason && !reviewerNote.trim()) {
      setNotice({ type: 'error', message: t('mirror.review.approveRequiresReason') })
      return
    }
    if (action === 'approve' && !opts?.skipConfirm) {
      setPendingAction(action)
      setShowApproveConfirm(true)
      return
    }
    if (action === 'reject' && !opts?.skipConfirm) {
      setPendingAction(action)
      setShowRejectConfirm(true)
      return
    }
    if (action === 'edit') {
      const patch: Record<string, unknown> = {}
      for (const [k, v] of Object.entries(editPatch)) {
        if (detail && String(detail.object_json[k] ?? '') !== v) patch[k] = v
      }
      if (Object.keys(patch).length === 0) {
        setNotice({ type: 'error', message: 'no changes' })
        return
      }
    }
    setRunning(true)
    setNotice(null)
    try {
      const patch: Record<string, unknown> = {}
      if (action === 'edit' && detail) {
        for (const [k, v] of Object.entries(editPatch)) {
          if (String(detail.object_json[k] ?? '') !== v) {
            patch[k] = k === 'confidence' || k === 'step_order' ? Number(v) : v
          }
        }
      }
      const res = await submitMirrorReviewAction({
        target_type: selected.target_type,
        target_id: selected.target_id,
        action,
        reviewer: reviewer.trim(),
        reviewer_note: reviewerNote.trim() || undefined,
        edit_patch_json: action === 'edit' ? patch : undefined,
        allow_with_warnings: true,
      })
      setNotice({ type: 'success', message: t('mirror.review.actionSucceeded') })
      if (res.warnings?.length) setNotice({ type: 'success', message: res.warnings.join('; ') })
      setQueueTick(x => x + 1)
      await openDetail({ ...selected, mirror_status: String(res.updated_object?.mirror_status ?? selected.mirror_status), review_status: String(res.updated_object?.review_status ?? selected.review_status), promotion_status: String(res.updated_object?.promotion_status ?? selected.promotion_status) })
    } catch (e) {
      setNotice({ type: 'error', message: e instanceof ApiError ? e.message : t('mirror.review.actionFailed') })
    } finally {
      setRunning(false)
      setShowApproveConfirm(false)
      setShowRejectConfirm(false)
      setPendingAction(null)
    }
  }

  const priorityClass = (p?: string) => {
    if (p === 'urgent') return 'macro-review-priority-urgent'
    if (p === 'high') return 'macro-review-priority-high'
    if (p === 'low') return 'macro-review-priority-low'
    return 'macro-review-priority-normal'
  }

  const typeLabel = (tt: string) => {
    const meta = (targetTypeMeta?.items ?? []).find((m: MirrorReviewTargetTypeInfo) => m.target_type === tt)
    return meta?.label ?? tt
  }

  const queueCols: Column<MirrorReviewQueueItem>[] = useMemo(() => [
    { key: 'target_type', header: t('mirror.review.targetTypes'), render: r => typeLabel(r.target_type) },
    { key: 'display_label', header: t('mirror.review.displayLabel'), render: r => r.target_label ?? r.display_label },
    { key: 'summary', header: t('mirror.review.summary'), render: r => r.target_summary ?? r.summary ?? '—' },
    { key: 'priority', header: t('mirror.review.recommendedPriority'), render: r => (
      <span className={priorityClass(r.recommended_review_priority)}>{r.recommended_review_priority ?? 'normal'}</span>
    )},
    { key: 'counts', header: 'B/E/W', render: r => `${r.blocker_count ?? 0}/${r.error_count ?? 0}/${r.warning_count ?? 0}` },
    { key: 'consensus', header: 'consensus', render: r => r.consensus_status ?? '—' },
    { key: 'verification', header: 'verification', render: r => r.verification_status ?? r.cross_validation_status ?? '—' },
    { key: 'mirror_status', header: t('mirror.mirrorStatus'), render: r => <StatusBadge status={r.mirror_status} /> },
    { key: 'review_status', header: t('mirror.reviewStatus'), render: r => <StatusBadge status={r.review_status} /> },
    { key: 'promotion_status', header: t('mirror.promotionStatus'), render: r => <StatusBadge status={r.promotion_status} /> },
    { key: 'actions', header: '', render: r => (
      <button type="button" className="btn btn-sm" onClick={() => openDetail(r)}>{t('mirror.review.detail')}</button>
    )},
  ], [t, targetTypeMeta])

  const toggleTarget = (tt: string) => {
    setTargetTypes(prev => {
      const next = new Set(prev)
      if (next.has(tt)) next.delete(tt)
      else next.add(tt)
      return next
    })
  }

  const editPreview = detail ? Object.fromEntries(
    detail.editable_fields.filter(f => String(detail.object_json[f] ?? '') !== (editPatch[f] ?? '')).map(f => [f, { before: detail.object_json[f], after: editPatch[f] }]),
  ) : {}

  return (
    <div className="mirror-kg-panel macro-review-workbench mirror-review-workbench">
      <Notice notice={notice} onClose={() => setNotice(null)} />
      <div className="macro-review-not-final-warning mirror-review-not-promotion">{t('mirror.review.notFinalWarning')} {t('mirror.review.notKgWarning')}</div>
      <div className="card-title">{t('mirror.review.macroClinicalTitle')}</div>
      <div className="mirror-review-warning">{t('mirror.review.macroClinicalDescription')}</div>
      <div className="macro-review-filter-panel mirror-review-filter-panel card">
        <div className="mirror-review-target-types">
          {MACRO_REVIEW_TYPES.map(tt => (
            <label key={tt} style={{ flexDirection: 'row', alignItems: 'center', gap: 4, fontSize: 12 }}>
              <input type="checkbox" checked={targetTypes.has(tt)} onChange={() => toggleTarget(tt)} />
              {typeLabel(tt)}
            </label>
          ))}
        </div>
        <div className="filter-bar">
          <input className="filter-input" placeholder="batch_id" value={batchFilter} onChange={e => setBatchFilter(e.target.value)} />
          <input className="filter-input" placeholder="resource_id" value={resourceFilter} onChange={e => setResourceFilter(e.target.value)} />
          <input className="filter-input" placeholder="source_atlas" value={sourceAtlas} onChange={e => setSourceAtlas(e.target.value)} />
          <input className="filter-input" placeholder="granularity_level" value={granularityLevel} onChange={e => setGranularityLevel(e.target.value)} />
          <input className="filter-input" placeholder={t('mirror.review.recommendedPriority')} value={reviewPriority} onChange={e => setReviewPriority(e.target.value)} />
          <input className="filter-input" placeholder="consensus_status" value={consensusStatus} onChange={e => setConsensusStatus(e.target.value)} />
          <input className="filter-input" placeholder="verification_status" value={verificationStatus} onChange={e => setVerificationStatus(e.target.value)} />
          <input className="filter-input" placeholder={t('mirror.mirrorStatus')} value={mirrorStatusFilter} onChange={e => setMirrorStatusFilter(e.target.value)} />
          <input className="filter-input" placeholder={t('mirror.reviewStatus')} value={reviewStatusFilter} onChange={e => setReviewStatusFilter(e.target.value)} />
          <input className="filter-input" placeholder={t('mirror.promotionStatus')} value={promotionStatusFilter} onChange={e => setPromotionStatusFilter(e.target.value)} />
          <input className="filter-input" placeholder="search" value={search} onChange={e => setSearch(e.target.value)} />
          <label><input type="checkbox" checked={hasBlocker === true} onChange={e => setHasBlocker(e.target.checked ? true : undefined)} /> blocker</label>
          <label><input type="checkbox" checked={hasError === true} onChange={e => setHasError(e.target.checked ? true : undefined)} /> error</label>
          <label><input type="checkbox" checked={hasWarning === true} onChange={e => setHasWarning(e.target.checked ? true : undefined)} /> warning</label>
          <label><input type="checkbox" checked={hasModelConflict === true} onChange={e => setHasModelConflict(e.target.checked ? true : undefined)} /> model_conflict</label>
          <label><input type="checkbox" checked={hasCrossConflict === true} onChange={e => setHasCrossConflict(e.target.checked ? true : undefined)} /> cross_conflict</label>
          <button type="button" className="btn" onClick={() => setQueueTick(x => x + 1)}>{t('mirror.review.queue')}</button>
        </div>
      </div>
      <div className="macro-review-layout">
        <div className="card macro-review-queue-table mirror-review-queue-table">
          <div className="card-title">{t('mirror.review.queue')}</div>
          <DataTable columns={queueCols} rows={queueData?.items ?? []} loading={queueLoading} error={queueError} total={queueData?.total} getKey={r => `${r.target_type}-${r.target_id}`} emptyText="—" />
        </div>
        {selected && (
          <div className="card macro-review-detail-panel mirror-review-detail-drawer">
            <div className="card-title">{t('mirror.review.detail')}: {selected.display_label}</div>
            {isSignal && <div className="macro-review-signal-section">{t('mirror.review.signalObject')} — {t('mirror.review.signalActionNote')}</div>}
            {!isSignal && <div className="macro-review-section">{t('mirror.review.domainObject')}</div>}
            {detailLoading && <LoadingState />}
            {detail && !detailLoading && (
              <>
                <div className="macro-review-section">
                  <strong>Object Summary</strong>
                  <pre style={{ fontSize: 11, maxHeight: 160, overflow: 'auto' }}>{JSON.stringify(detail.object_payload ?? detail.object_json, null, 2)}</pre>
                </div>
                {!valSummary.validated && <div className="macro-review-warning mirror-review-warning">{t('mirror.review.validationRequired')}</div>}
                {(valSummary.has_blocker || valSummary.has_error) && <div className="macro-review-blocker mirror-review-warning">{t('mirror.review.approveBlockedByErrors')}</div>}
                <div className="macro-review-section macro-review-validation-panel mirror-review-validation-panel">
                  <strong>{t('mirror.review.validationResults')}</strong>
                  <pre style={{ fontSize: 11, maxHeight: 120, overflow: 'auto' }}>{JSON.stringify(detail.validation_results.slice(0, 10), null, 2)}</pre>
                </div>
                {(detail.cross_validation_results?.length ?? 0) > 0 && (
                  <div className="macro-review-section macro-review-signal-section">
                    <strong>{t('mirror.review.crossValidationSignals')}</strong>
                    <pre style={{ fontSize: 11, maxHeight: 120, overflow: 'auto' }}>{JSON.stringify(detail.cross_validation_results, null, 2)}</pre>
                  </div>
                )}
                {(detail.dual_model_results?.length ?? 0) > 0 && (
                  <div className="macro-review-section macro-review-signal-section">
                    <strong>{t('mirror.review.dualModelSignals')}</strong>
                    <pre style={{ fontSize: 11, maxHeight: 120, overflow: 'auto' }}>{JSON.stringify(detail.dual_model_results, null, 2)}</pre>
                  </div>
                )}
                <div className="macro-review-section mirror-review-evidence-panel">
                  <strong>{t('mirror.review.evidence')}</strong> ({detail.evidence_records.length})
                  <pre style={{ fontSize: 11, maxHeight: 120, overflow: 'auto' }}>{JSON.stringify(detail.evidence_records.slice(0, 5), null, 2)}</pre>
                </div>
                {Object.keys(detail.related_objects ?? {}).length > 0 && (
                  <div className="macro-review-section">
                    <strong>{t('mirror.review.relatedObjects')}</strong>
                    <pre style={{ fontSize: 11, maxHeight: 160, overflow: 'auto' }}>{JSON.stringify(detail.related_objects, null, 2)}</pre>
                  </div>
                )}
                <div className="macro-review-section mirror-review-history-panel">
                  <strong>{t('mirror.review.reviewHistory')}</strong> ({detail.review_records.length})
                </div>
                <div className="macro-review-gating-panel macro-review-section">
                  <strong>{t('mirror.review.gating')}</strong>
                  <ul style={{ fontSize: 12, margin: '4px 0' }}>
                    {(gating?.gating_reasons ?? []).map(r => <li key={r}>{r}</li>)}
                  </ul>
                  <div style={{ fontSize: 12 }}>{t('mirror.review.allowedActions')}: {detail.allowed_actions.join(', ')}</div>
                </div>
                {!isSignal && detail.editable_fields.length > 0 && (
                  <div className="mirror-review-edit-form">
                    <div className="panel-label">{t('mirror.review.allowedEditableFields')}</div>
                    <div className="mirror-review-warning" style={{ fontSize: 11 }}>{t('mirror.review.provenanceNotEditable')}</div>
                    {detail.editable_fields.map(f => (
                      <label key={f} style={{ display: 'block', marginBottom: 6, fontSize: 12 }}>
                        {f}
                        <input className="filter-input" style={{ width: '100%' }} value={editPatch[f] ?? ''} onChange={e => setEditPatch(p => ({ ...p, [f]: e.target.value }))} />
                      </label>
                    ))}
                    {Object.keys(editPreview).length > 0 && (
                      <div className="macro-review-edit-preview">
                        <strong>{t('mirror.review.editBeforeAfterPreview')}</strong>
                        <pre style={{ fontSize: 11 }}>{JSON.stringify(editPreview, null, 2)}</pre>
                      </div>
                    )}
                  </div>
                )}
                <div className="macro-review-action-bar mirror-review-action-bar">
                  <input className="filter-input" placeholder={t('mirror.review.reviewer')} value={reviewer} onChange={e => setReviewer(e.target.value)} />
                  <textarea className="filter-input" placeholder={t('mirror.review.reviewerNote')} value={reviewerNote} onChange={e => setReviewerNote(e.target.value)} rows={2} style={{ width: '100%' }} />
                  <div style={{ display: 'flex', gap: 8, flexWrap: 'wrap' }}>
                    {!isSignal && detail.allowed_actions.includes('approve') && (
                      <ActionButton label={t('mirror.review.approve')} onClick={() => runAction('approve')} disabled={running || !canApprove} variant="primary" />
                    )}
                    {!isSignal && detail.allowed_actions.includes('reject') && (
                      <ActionButton label={t('mirror.review.reject')} onClick={() => runAction('reject')} disabled={running} />
                    )}
                    {!isSignal && detail.allowed_actions.includes('needs_revision') && (
                      <ActionButton label={t('mirror.review.needsRevision')} onClick={() => runAction('needs_revision')} disabled={running} />
                    )}
                    {!isSignal && detail.allowed_actions.includes('edit') && (
                      <ActionButton label={t('mirror.review.saveEdit')} onClick={() => runAction('edit')} disabled={running} />
                    )}
                    {isSignal && detail.allowed_actions.includes('accept_signal') && (
                      <ActionButton label={t('mirror.review.acceptSignal')} onClick={() => runAction('accept_signal')} disabled={running} variant="primary" />
                    )}
                    {isSignal && detail.allowed_actions.includes('dismiss_signal') && (
                      <ActionButton label={t('mirror.review.dismissSignal')} onClick={() => runAction('dismiss_signal')} disabled={running} />
                    )}
                    {detail.allowed_actions.includes('comment') && (
                      <ActionButton label={t('mirror.review.comment')} onClick={() => runAction('comment')} disabled={running} />
                    )}
                    {detail.allowed_actions.includes('flag_for_followup') && (
                      <ActionButton label={t('mirror.review.flagForFollowup')} onClick={() => runAction('flag_for_followup')} disabled={running} />
                    )}
                  </div>
                  {!isSignal && <div style={{ fontSize: 11, color: '#666' }}>{t('mirror.review.editNeedsRevalidation')}</div>}
                </div>
              </>
            )}
          </div>
        )}
      </div>
      <ConfirmDialog
        open={showApproveConfirm}
        title={t('mirror.review.approve')}
        message={t('mirror.review.approveMirrorOnlyConfirm')}
        confirmLabel={t('common.confirm')}
        onConfirm={() => pendingAction && runAction(pendingAction, { skipConfirm: true })}
        onCancel={() => { setShowApproveConfirm(false); setPendingAction(null) }}
        loading={running}
      />
      <ConfirmDialog
        open={showRejectConfirm}
        title={t('mirror.review.reject')}
        message={t('mirror.review.rejectMirrorOnlyConfirm')}
        confirmLabel={t('common.confirm')}
        onConfirm={() => pendingAction && runAction(pendingAction, { skipConfirm: true })}
        onCancel={() => { setShowRejectConfirm(false); setPendingAction(null) }}
        loading={running}
      />
    </div>
  )
}

function FinalProvenancePanel({ provenance }: { provenance: FinalProvenancePayload }) {
  const { t } = useI18n()
  return (
    <div className="final-provenance-panel final-browser-section">
      <div className="card-title">{t('finalBrowser.provenance')}</div>
      <div className="final-browser-action-row">
        {provenance.source_mirror_id && (
          <CopyButton value={String(provenance.source_mirror_id)} label={t('finalBrowser.copySourceMirrorId')} />
        )}
        {provenance.promotion_run_id && (
          <CopyButton value={String(provenance.promotion_run_id)} label="promotion_run_id" />
        )}
      </div>
      <details>
        <summary>{t('finalBrowser.provenance')}</summary>
        <pre className="json-preview">{JSON.stringify(provenance, null, 2)}</pre>
      </details>
      <details>
        <summary>{t('finalBrowser.validationSummary')}</summary>
        <pre className="json-preview">{JSON.stringify(provenance.validation_summary_json ?? {}, null, 2)}</pre>
      </details>
      <details>
        <summary>{t('finalBrowser.reviewSummary')}</summary>
        <pre className="json-preview">{JSON.stringify(provenance.review_summary_json ?? {}, null, 2)}</pre>
      </details>
      <details>
        <summary>{t('finalBrowser.crossValidationSummary')}</summary>
        <pre className="json-preview">{JSON.stringify(provenance.cross_validation_summary_json ?? {}, null, 2)}</pre>
      </details>
      <details>
        <summary>{t('finalBrowser.dualModelSummary')}</summary>
        <pre className="json-preview">{JSON.stringify(provenance.dual_model_summary_json ?? {}, null, 2)}</pre>
      </details>
    </div>
  )
}

function FinalGraphTables({ graph }: { graph: FinalGraphResponse | null | undefined }) {
  const { t } = useI18n()
  if (!graph || (graph.nodes.length === 0 && graph.edges.length === 0)) {
    return <div className="final-browser-empty-state">{t('finalBrowser.emptyGraph')}</div>
  }
  const nodeCols: Column<FinalGraphNode>[] = [
    { key: 'type', header: 'type', render: r => <span className="final-browser-node-badge">{r.type}</span> },
    { key: 'label', header: 'label', render: r => r.label },
    { key: 'final_id', header: 'final_id', render: r => r.final_id?.slice(0, 12) ?? '—' },
  ]
  const edgeCols: Column<FinalGraphEdge>[] = [
    { key: 'type', header: 'type', render: r => <span className="final-browser-edge-badge">{r.type}</span> },
    { key: 'source', header: 'source', render: r => r.source },
    { key: 'target', header: 'target', render: r => r.target },
    { key: 'label', header: 'label', render: r => r.label ?? r.predicate ?? '—' },
  ]
  return (
    <div className="final-graph-view">
      {graph.warnings && graph.warnings.length > 0 && (
        <Notice notice={{ type: 'warning', message: graph.warnings.join('; ') }} onClose={() => {}} />
      )}
      <div className="final-browser-action-row">
        <CopyButton value={JSON.stringify(graph, null, 2)} label={t('finalBrowser.copyGraphJson')} />
      </div>
      <div className="final-browser-section">
        <div className="card-title">{t('finalBrowser.graphNodes')}</div>
        <div className="final-graph-node-table">
          <DataTable columns={nodeCols} rows={graph.nodes} getKey={r => r.id} />
        </div>
      </div>
      <div className="final-browser-section">
        <div className="card-title">{t('finalBrowser.graphEdges')}</div>
        <div className="final-graph-edge-table">
          <DataTable columns={edgeCols} rows={graph.edges} getKey={r => r.id} />
        </div>
      </div>
    </div>
  )
}

function FinalKgBrowserTab() {
  const { t } = useI18n()
  const SEARCH_TYPES = ['circuit', 'circuit_step', 'projection', 'projection_function', 'circuit_projection_membership', 'region_function', 'circuit_function', 'triple', 'evidence'] as const
  const [query, setQuery] = useState('')
  const [targetTypes, setTargetTypes] = useState<Set<string>>(new Set(['circuit', 'projection']))
  const [sourceAtlas, setSourceAtlas] = useState('')
  const [granularityLevel, setGranularityLevel] = useState('')
  const [finalStatus, setFinalStatus] = useState('')
  const [includeInactive, setIncludeInactive] = useState(false)
  const [limit, setLimit] = useState(100)
  const [searchResult, setSearchResult] = useState<FinalBrowserSearchResponse | null>(null)
  const [searching, setSearching] = useState(false)
  const [notice, setNotice] = useState<NoticeState | null>(null)

  const [regionId, setRegionId] = useState('')
  const [regionData, setRegionData] = useState<FinalRegionNeighborhoodResponse | null>(null)
  const [loadingRegion, setLoadingRegion] = useState(false)

  const [circuitDetail, setCircuitDetail] = useState<FinalCircuitDetailResponse | null>(null)
  const [projectionDetail, setProjectionDetail] = useState<FinalProjectionDetailResponse | null>(null)
  const [objectDetail, setObjectDetail] = useState<FinalObjectDetailResponse | null>(null)
  const [graphData, setGraphData] = useState<FinalGraphResponse | null>(null)

  const runSearch = async () => {
    setSearching(true)
    setNotice(null)
    try {
      const res = await searchFinalKgObjects({
        query: query || undefined,
        target_types: [...targetTypes],
        source_atlas: sourceAtlas || undefined,
        granularity_level: granularityLevel || undefined,
        final_status: finalStatus || undefined,
        include_inactive: includeInactive,
        limit,
        offset: 0,
      })
      setSearchResult(res)
    } catch (e) {
      setNotice({ type: 'error', message: e instanceof ApiError ? e.message : String(e) })
    } finally {
      setSearching(false)
    }
  }

  const resetSearch = () => {
    setQuery('')
    setTargetTypes(new Set(['circuit', 'projection']))
    setSourceAtlas('')
    setGranularityLevel('')
    setFinalStatus('')
    setIncludeInactive(false)
    setLimit(100)
    setSearchResult(null)
  }

  const openSearchItem = async (item: FinalBrowserSearchItem) => {
    setObjectDetail(null)
    setCircuitDetail(null)
    setProjectionDetail(null)
    try {
      if (item.target_type === 'circuit') {
        const d = await getFinalCircuitDetail(item.final_id)
        setCircuitDetail(d)
        setGraphData(d.graph)
      } else if (item.target_type === 'projection') {
        const d = await getFinalProjectionDetail(item.final_id)
        setProjectionDetail(d)
        setGraphData(d.graph)
      } else {
        const d = await getFinalObjectDetail(item.target_type, item.final_id)
        setObjectDetail(d)
        setGraphData(null)
      }
    } catch (e) {
      setNotice({ type: 'error', message: e instanceof ApiError ? e.message : String(e) })
    }
  }

  const loadRegion = async (id?: string) => {
    const rid = (id ?? regionId).trim()
    if (!rid) return
    setLoadingRegion(true)
    setNotice(null)
    try {
      const res = await getFinalRegionNeighborhood(rid)
      setRegionData(res)
      setRegionId(rid)
      setGraphData(res.graph)
      setCircuitDetail(null)
      setProjectionDetail(null)
      setObjectDetail(null)
    } catch (e) {
      setNotice({ type: 'error', message: e instanceof ApiError ? e.message : String(e) })
    } finally {
      setLoadingRegion(false)
    }
  }

  const openCircuit = async (cid: string) => {
    try {
      const d = await getFinalCircuitDetail(cid)
      setCircuitDetail(d)
      setProjectionDetail(null)
      setObjectDetail(null)
      setGraphData(d.graph)
    } catch (e) {
      setNotice({ type: 'error', message: e instanceof ApiError ? e.message : String(e) })
    }
  }

  const openProjection = async (pid: string) => {
    try {
      const d = await getFinalProjectionDetail(pid)
      setProjectionDetail(d)
      setCircuitDetail(null)
      setObjectDetail(null)
      setGraphData(d.graph)
    } catch (e) {
      setNotice({ type: 'error', message: e instanceof ApiError ? e.message : String(e) })
    }
  }

  const searchCols: Column<FinalBrowserSearchItem>[] = useMemo(() => [
    { key: 'target_type', header: t('finalBrowser.targetTypes'), render: r => r.target_type },
    { key: 'label', header: 'label', render: r => r.label },
    { key: 'summary', header: 'summary', render: r => r.summary ?? '—' },
    { key: 'source_atlas', header: 'atlas', render: r => r.source_atlas ?? '—' },
    { key: 'granularity', header: t('finalBrowser.granularity'), render: r => r.granularity_level ?? '—' },
    { key: 'confidence', header: 'conf', render: r => r.confidence?.toFixed(2) ?? '—' },
    { key: 'final_status', header: t('finalBrowser.finalStatus'), render: r => <StatusBadge status={r.final_status ?? 'unknown'} /> },
    { key: 'source_mirror_id', header: 'mirror', render: r => r.source_mirror_id?.slice(0, 10) ?? '—' },
    { key: 'created_at', header: 'created', render: r => r.created_at?.slice(0, 19) ?? '—' },
    {
      key: 'actions',
      header: '',
      render: r => (
        <div className="final-browser-action-row">
          <button type="button" className="btn btn-sm" onClick={() => openSearchItem(r)}>{t('finalBrowser.openDetail')}</button>
          <CopyButton value={r.final_id} label="" title={t('finalBrowser.copyFinalId')} />
        </div>
      ),
    },
  ], [t])

  const regionEmpty = regionData && !regionData.circuits.length && !regionData.circuit_steps.length
    && !regionData.outgoing_projections.length && !regionData.incoming_projections.length
    && !regionData.region_functions.length

  return (
    <div className="final-kg-browser card">
      <div className="card-title">{t('finalBrowser.title')}</div>
      <div className="final-readonly-warning">{t('finalBrowser.description')}</div>
      <div className="final-readonly-warning">{t('finalBrowser.noWriteWarning')}</div>
      <div className="final-readonly-warning">{t('finalBrowser.noKgWarning')}</div>
      <div className="final-readonly-warning">{t('finalBrowser.noExternalDbWarning')}</div>
      <div className="final-readonly-warning">{t('finalBrowser.finalOnlyDescription')}</div>
      {notice && <Notice notice={notice} onClose={() => setNotice(null)} />}

      <div className="final-browser-search-panel card">
        <div className="card-title">{t('finalBrowser.searchPanel')}</div>
        <div className="filter-row">
          <input className="filter-input" placeholder={t('finalBrowser.query')} value={query} onChange={e => setQuery(e.target.value)} />
          <input className="filter-input" placeholder="source_atlas" value={sourceAtlas} onChange={e => setSourceAtlas(e.target.value)} />
          <input className="filter-input" placeholder="granularity_level" value={granularityLevel} onChange={e => setGranularityLevel(e.target.value)} />
          <input className="filter-input" placeholder="final_status" value={finalStatus} onChange={e => setFinalStatus(e.target.value)} />
          <input className="filter-input" type="number" placeholder="limit" value={limit} onChange={e => setLimit(Number(e.target.value) || 100)} style={{ width: 80 }} />
          <label><input type="checkbox" checked={includeInactive} onChange={e => setIncludeInactive(e.target.checked)} /> {t('finalBrowser.includeInactive')}</label>
        </div>
        <div className="filter-row">
          {SEARCH_TYPES.map(tt => (
            <label key={tt}>
              <input type="checkbox" checked={targetTypes.has(tt)} onChange={e => {
                setTargetTypes(prev => {
                  const next = new Set(prev)
                  if (e.target.checked) next.add(tt)
                  else next.delete(tt)
                  return next
                })
              }} /> {tt}
            </label>
          ))}
        </div>
        <div className="filter-row">
          <ActionButton label={t('finalBrowser.search')} onClick={runSearch} disabled={searching} variant="primary" />
          <ActionButton label={t('finalBrowser.reset')} onClick={resetSearch} disabled={searching} />
        </div>
        <div className="final-browser-results-table">
          {searchResult && searchResult.items.length === 0 && (
            <div className="final-browser-empty-state">{t('finalBrowser.emptySearch')}</div>
          )}
          {searchResult && searchResult.items.length > 0 && (
            <DataTable columns={searchCols} rows={searchResult.items} getKey={r => `${r.target_type}:${r.final_id}`} />
          )}
        </div>
      </div>

      <div className="final-region-explorer card">
        <div className="card-title">{t('finalBrowser.regionExplorer')}</div>
        <div className="filter-row">
          <input className="filter-input" placeholder={t('finalBrowser.regionCandidateId')} value={regionId} onChange={e => setRegionId(e.target.value)} style={{ minWidth: 320 }} />
          <ActionButton label={t('finalBrowser.loadRegion')} onClick={() => loadRegion()} disabled={loadingRegion} />
        </div>
        {regionData && (
          <>
            <div className="final-summary-card">
              <strong>{regionData.region_label ?? regionData.region_candidate_id}</strong>
              {regionData.source_atlas && <> · {regionData.source_atlas}</>}
              {regionData.granularity_level && <> · {regionData.granularity_level}</>}
            </div>
            {regionEmpty && <div className="final-browser-empty-state">{t('finalBrowser.emptyRegion')}</div>}
            {!regionEmpty && (
              <>
                <SectionList title={t('finalBrowser.regionFunctions')} items={regionData.region_functions} />
                <SectionList title={t('finalBrowser.circuits')} items={regionData.circuits} onClickId={id => openCircuit(id)} idKey="id" labelKey="circuit_name" />
                <SectionList title={t('finalBrowser.circuitSteps')} items={regionData.circuit_steps} labelKey="step_name" />
                <SectionList title={t('finalBrowser.outgoingProjections')} items={regionData.outgoing_projections} onClickId={id => openProjection(id)} idKey="id" labelKey="projection_type" />
                <SectionList title={t('finalBrowser.incomingProjections')} items={regionData.incoming_projections} onClickId={id => openProjection(id)} idKey="id" labelKey="projection_type" />
                <SectionList title={t('finalBrowser.undirectedProjections')} items={regionData.undirected_projections} onClickId={id => openProjection(id)} idKey="id" labelKey="projection_type" />
                <SectionList title={t('finalBrowser.projectionFunctions')} items={regionData.projection_functions} labelKey="function_term" />
                <SectionList title={t('finalBrowser.triples')} items={regionData.triples} labelKey="predicate" />
                <SectionList title={t('finalBrowser.evidence')} items={regionData.evidence} labelKey="evidence_text" />
              </>
            )}
          </>
        )}
      </div>

      {circuitDetail && (
        <div className="final-circuit-detail final-detail-panel card">
          <div className="card-title">{t('finalBrowser.circuitDetail')}</div>
          <div className="final-summary-card">
            {String(circuitDetail.circuit.circuit_name ?? circuitDetail.circuit.id)}
            <CopyButton value={String(circuitDetail.circuit.id)} label={t('finalBrowser.copyFinalId')} />
          </div>
          <div className="final-browser-section">
            <div className="card-title">{t('finalBrowser.stepsTimeline')}</div>
            <div className="final-browser-timeline">
              {circuitDetail.steps.map(s => (
                <div key={String(s.id)} className="final-browser-timeline-item">
                  #{String(s.step_order)} {String(s.step_name)} ({String(s.role ?? '')})
                </div>
              ))}
            </div>
          </div>
          <SectionList title={t('finalBrowser.participantRegions')} items={circuitDetail.participant_regions} labelKey="label" />
          <SectionList title={t('finalBrowser.outgoingProjections')} items={circuitDetail.projections} onClickId={id => openProjection(id)} idKey="id" labelKey="projection_type" />
          <SectionList title={t('finalBrowser.memberships')} items={circuitDetail.memberships} labelKey="role_in_circuit" />
          <SectionList title={t('finalBrowser.regionFunctions')} items={circuitDetail.circuit_functions} labelKey="function_term" />
          <SectionList title={t('finalBrowser.projectionFunctions')} items={circuitDetail.projection_functions_summary} labelKey="function_term" />
          <SectionList title={t('finalBrowser.triples')} items={circuitDetail.triples} labelKey="predicate" />
          <SectionList title={t('finalBrowser.evidence')} items={circuitDetail.evidence} labelKey="evidence_text" />
          <FinalProvenancePanel provenance={circuitDetail.provenance} />
        </div>
      )}

      {projectionDetail && (
        <div className="final-projection-detail final-detail-panel card">
          <div className="card-title">{t('finalBrowser.projectionDetail')}</div>
          <div className="final-summary-card">
            {String(projectionDetail.projection.projection_type ?? projectionDetail.projection.id)}
            <CopyButton value={String(projectionDetail.projection.id)} label={t('finalBrowser.copyFinalId')} />
          </div>
          {projectionDetail.source_region && (
            <div>{t('finalBrowser.sourceRegion')}: {String(projectionDetail.source_region.label)}</div>
          )}
          {projectionDetail.target_region && (
            <div>{t('finalBrowser.targetRegion')}: {String(projectionDetail.target_region.label)}</div>
          )}
          <SectionList title={t('finalBrowser.memberships')} items={projectionDetail.memberships} labelKey="role_in_circuit" />
          <SectionList title={t('finalBrowser.circuits')} items={projectionDetail.circuits} onClickId={id => openCircuit(id)} idKey="id" labelKey="circuit_name" />
          <SectionList title={t('finalBrowser.projectionFunctions')} items={projectionDetail.projection_functions} labelKey="function_term" />
          <SectionList title={t('finalBrowser.triples')} items={projectionDetail.triples} labelKey="predicate" />
          <SectionList title={t('finalBrowser.evidence')} items={projectionDetail.evidence} labelKey="evidence_text" />
          <FinalProvenancePanel provenance={projectionDetail.provenance} />
        </div>
      )}

      {objectDetail && (
        <div className="final-detail-panel card">
          <div className="card-title">{t('finalBrowser.objectDetail')}: {objectDetail.target_type}</div>
          <CopyButton value={objectDetail.final_id} label={t('finalBrowser.copyFinalId')} />
          <pre className="json-preview">{JSON.stringify(objectDetail.object, null, 2)}</pre>
          <SectionList title="related" items={objectDetail.related_objects} labelKey="target_type" />
          <SectionList title={t('finalBrowser.triples')} items={objectDetail.triples} labelKey="predicate" />
          <SectionList title={t('finalBrowser.evidence')} items={objectDetail.evidence} labelKey="evidence_text" />
          <FinalProvenancePanel provenance={objectDetail.provenance} />
        </div>
      )}

      <div className="card">
        <div className="card-title">{t('finalBrowser.graphView')}</div>
        <FinalGraphTables graph={graphData} />
      </div>
    </div>
  )
}

function SectionList({
  title,
  items,
  labelKey = 'label',
  idKey = 'id',
  onClickId,
}: {
  title: string
  items: Record<string, unknown>[]
  labelKey?: string
  idKey?: string
  onClickId?: (id: string) => void
}) {
  if (!items.length) return null
  return (
    <div className="final-browser-section">
      <div className="card-title">{title} ({items.length})</div>
      <ul style={{ margin: 0, paddingLeft: 18, fontSize: 13 }}>
        {items.map((item, i) => {
          const id = item[idKey] != null ? String(item[idKey]) : undefined
          const label = String(item[labelKey] ?? id ?? i)
          return (
            <li key={id ?? i}>
              {onClickId && id ? (
                <button type="button" className="btn-link" onClick={() => onClickId(id)}>{label}</button>
              ) : label}
            </li>
          )
        })}
      </ul>
    </div>
  )
}

function FinalKgExportTab() {
  const { t } = useI18n()
  const EXPORT_TYPES = ['brain_region', 'region_function', 'circuit', 'circuit_step', 'circuit_function', 'projection', 'projection_function', 'circuit_projection_membership', 'triple', 'evidence'] as const
  const [targetTypes, setTargetTypes] = useState<Set<string>>(new Set(['circuit', 'projection', 'brain_region']))
  const [formats, setFormats] = useState<Set<string>>(new Set(['jsonl', 'csv', 'neo4j_csv']))
  const [sourceAtlas, setSourceAtlas] = useState('')
  const [sourceVersion, setSourceVersion] = useState('')
  const [granularityLevel, setGranularityLevel] = useState('')
  const [granularityFamily, setGranularityFamily] = useState('')
  const [resourceId, setResourceId] = useState('')
  const [batchId, setBatchId] = useState('')
  const [finalStatus, setFinalStatus] = useState('')
  const [includeInactive, setIncludeInactive] = useState(false)
  const [includeEvidence, setIncludeEvidence] = useState(true)
  const [includeProvenance, setIncludeProvenance] = useState(true)
  const [includeTriples, setIncludeTriples] = useState(true)
  const [maxNodes, setMaxNodes] = useState(100000)
  const [maxEdges, setMaxEdges] = useState(300000)
  const [exportLabel, setExportLabel] = useState('')
  const [dryRun, setDryRun] = useState(true)
  const [running, setRunning] = useState(false)
  const [notice, setNotice] = useState<NoticeState | null>(null)
  const [preview, setPreview] = useState<FinalKgExportPreviewResponse | null>(null)
  const [runResult, setRunResult] = useState<FinalKgExportRunResponse | null>(null)
  const [exportsTick, setExportsTick] = useState(0)
  const [selectedExportId, setSelectedExportId] = useState('')
  const [manifestJson, setManifestJson] = useState<string>('')

  const { data: exportsData } = useData(() => listFinalKgExports(), [exportsTick])
  const { data: filesData } = useData(
    () => (selectedExportId ? listFinalKgExportFiles(selectedExportId) : Promise.resolve({ export_id: '', files: [] })),
    [selectedExportId, exportsTick],
  )

  const buildPayload = (previewMode: boolean): FinalKgExportRequest => ({
    target_types: [...targetTypes] as FinalKgExportRequest['target_types'],
    formats: [...formats] as FinalKgExportRequest['formats'],
    scope: {
      source_atlas: sourceAtlas || undefined,
      source_version: sourceVersion || undefined,
      granularity_level: granularityLevel || undefined,
      granularity_family: granularityFamily || undefined,
      resource_id: resourceId || undefined,
      batch_id: batchId || undefined,
      final_status: finalStatus || undefined,
      include_inactive: includeInactive,
    },
    dry_run: previewMode,
    include_evidence: includeEvidence,
    include_provenance: includeProvenance,
    include_triples: includeTriples,
    max_nodes: maxNodes,
    max_edges: maxEdges,
    export_label: exportLabel || undefined,
  })

  const runExport = async (previewMode: boolean) => {
    setRunning(true)
    setNotice(null)
    try {
      const res = await runFinalKgExport(buildPayload(previewMode))
      if (res.dry_run) {
        setPreview(res as FinalKgExportPreviewResponse)
        setRunResult(null)
        setNotice({ type: 'success', message: t('finalExport.previewExport') })
      } else {
        const runRes = res as FinalKgExportRunResponse
        setRunResult(runRes)
        setPreview(null)
        setNotice({ type: 'success', message: t('finalExport.runExport') })
        if (runRes.export_id) setSelectedExportId(runRes.export_id)
        setExportsTick(x => x + 1)
      }
    } catch (e) {
      setNotice({ type: 'error', message: e instanceof ApiError ? e.message : String(e) })
    } finally {
      setRunning(false)
    }
  }

  const openManifest = async (exportId: string) => {
    try {
      const m = await getFinalKgExportManifest(exportId)
      setManifestJson(JSON.stringify(m, null, 2))
      setSelectedExportId(exportId)
    } catch (e) {
      setNotice({ type: 'error', message: e instanceof ApiError ? e.message : String(e) })
    }
  }

  const exportListCols: Column<FinalKgExportManifestRead>[] = useMemo(() => [
    { key: 'export_id', header: 'export_id', render: r => r.export_id },
    { key: 'created_at', header: 'created_at', render: r => r.created_at?.slice(0, 19) ?? '—' },
    { key: 'formats', header: t('finalExport.formats'), render: r => r.formats.map(f => <span key={f} className="final-export-format-badge">{f}</span>) },
    { key: 'target_types', header: t('finalExport.targetTypes'), render: r => r.target_types.join(', ') },
    { key: 'nodes', header: 'nodes', render: r => r.counts?.nodes ?? '—' },
    { key: 'edges', header: 'edges', render: r => r.counts?.edges ?? '—' },
    { key: 'warnings', header: 'warnings', render: r => r.warnings?.length ?? 0 },
    {
      key: 'actions',
      header: '',
      render: r => (
        <div className="final-browser-action-row">
          <button type="button" className="btn btn-sm" onClick={() => { setSelectedExportId(r.export_id); openManifest(r.export_id) }}>{t('finalExport.openManifest')}</button>
        </div>
      ),
    },
  ], [t])

  const fileCols: Column<FinalKgExportFileRead>[] = useMemo(() => [
    { key: 'filename', header: 'filename', render: r => r.filename },
    { key: 'size', header: 'size', render: r => `${r.size_bytes} B` },
    { key: 'modified', header: 'modified', render: r => r.modified_at?.slice(0, 19) ?? '—' },
    {
      key: 'actions',
      header: '',
      render: r => (
        <div className="final-browser-action-row">
          <a className="final-export-download-link" href={getFinalKgExportFileUrl(r.export_id, r.filename)} download>{t('finalExport.downloadFile')}</a>
          <CopyButton value={getFinalKgExportFileUrl(r.export_id, r.filename)} label={t('finalExport.copyDownloadUrl')} />
        </div>
      ),
    },
  ], [t])

  return (
    <div className="final-kg-export card">
      <div className="card-title">{t('finalExport.title')}</div>
      <div className="final-export-boundary-warning">{t('finalExport.boundaryWarning')}</div>
      <div className="final-export-boundary-warning">{t('finalExport.noWriteKgWarning')}</div>
      <div className="final-export-boundary-warning">{t('finalExport.noNeo4jConnectionWarning')}</div>
      <div className="final-export-boundary-warning">{t('finalExport.noExternalDbWarning')}</div>
      <div className="final-export-boundary-warning">{t('finalExport.localFilesOnly')}</div>
      {notice && <Notice notice={notice} onClose={() => setNotice(null)} />}

      <div className="final-export-control-panel card">
        <div className="card-title">{t('finalExport.formats')}</div>
        <div className="filter-row">
          {(['jsonl', 'csv', 'neo4j_csv'] as const).map(f => (
            <label key={f}><input type="checkbox" checked={formats.has(f)} onChange={e => {
              setFormats(prev => { const n = new Set(prev); if (e.target.checked) n.add(f); else n.delete(f); return n })
            }} /> {t(`finalExport.${f === 'neo4j_csv' ? 'neo4jCsv' : f}`)}</label>
          ))}
        </div>
        <div className="filter-row">
          {EXPORT_TYPES.map(tt => (
            <label key={tt}><input type="checkbox" checked={targetTypes.has(tt)} onChange={e => {
              setTargetTypes(prev => { const n = new Set(prev); if (e.target.checked) n.add(tt); else n.delete(tt); return n })
            }} /> {tt}</label>
          ))}
        </div>
        <div className="filter-row">
          <input className="filter-input" placeholder="source_atlas" value={sourceAtlas} onChange={e => setSourceAtlas(e.target.value)} />
          <input className="filter-input" placeholder="source_version" value={sourceVersion} onChange={e => setSourceVersion(e.target.value)} />
          <input className="filter-input" placeholder="granularity_level" value={granularityLevel} onChange={e => setGranularityLevel(e.target.value)} />
          <input className="filter-input" placeholder="granularity_family" value={granularityFamily} onChange={e => setGranularityFamily(e.target.value)} />
          <input className="filter-input" placeholder="resource_id" value={resourceId} onChange={e => setResourceId(e.target.value)} />
          <input className="filter-input" placeholder="batch_id" value={batchId} onChange={e => setBatchId(e.target.value)} />
          <input className="filter-input" placeholder="final_status" value={finalStatus} onChange={e => setFinalStatus(e.target.value)} />
          <input className="filter-input" placeholder={t('finalExport.exportLabel')} value={exportLabel} onChange={e => setExportLabel(e.target.value)} />
        </div>
        <div className="filter-row">
          <label><input type="checkbox" checked={includeInactive} onChange={e => setIncludeInactive(e.target.checked)} /> include_inactive</label>
          <label><input type="checkbox" checked={includeEvidence} onChange={e => setIncludeEvidence(e.target.checked)} /> {t('finalExport.includeEvidence')}</label>
          <label><input type="checkbox" checked={includeProvenance} onChange={e => setIncludeProvenance(e.target.checked)} /> {t('finalExport.includeProvenance')}</label>
          <label><input type="checkbox" checked={includeTriples} onChange={e => setIncludeTriples(e.target.checked)} /> {t('finalExport.includeTriples')}</label>
          <label><input type="checkbox" checked={dryRun} onChange={e => setDryRun(e.target.checked)} /> {t('finalExport.dryRun')}</label>
          <input className="filter-input" type="number" placeholder={t('finalExport.maxNodes')} value={maxNodes} onChange={e => setMaxNodes(Number(e.target.value) || 100000)} style={{ width: 100 }} />
          <input className="filter-input" type="number" placeholder={t('finalExport.maxEdges')} value={maxEdges} onChange={e => setMaxEdges(Number(e.target.value) || 300000)} style={{ width: 100 }} />
        </div>
        <div className="filter-row">
          <ActionButton label={t('finalExport.previewExport')} onClick={() => runExport(true)} disabled={running} />
          <ActionButton label={t('finalExport.runExport')} onClick={() => runExport(false)} disabled={running || dryRun} variant="primary" />
          <ActionButton label={t('finalExport.refreshExports')} onClick={() => setExportsTick(x => x + 1)} disabled={running} />
        </div>
      </div>

      {(preview || runResult) && (
        <div className="final-export-preview card">
          <div className="final-export-summary-card">
            <div>{t('finalExport.candidateCounts')}: {preview ? JSON.stringify(preview.candidate_counts) : '—'}</div>
            <div>{t('finalExport.estimatedNodeCount')}: {preview?.estimated_node_count ?? runResult?.counts.nodes ?? '—'}</div>
            <div>{t('finalExport.estimatedEdgeCount')}: {preview?.estimated_edge_count ?? runResult?.counts.edges ?? '—'}</div>
            {runResult?.export_id && <div>export_id: {runResult.export_id}</div>}
            {runResult?.export_dir && <div>{runResult.export_dir}</div>}
          </div>
          {(preview?.warnings?.length ?? runResult?.warnings?.length) ? (
            <div className="final-export-warning">{(preview?.warnings ?? runResult?.warnings ?? []).join('; ')}</div>
          ) : null}
          {preview && preview.sample_nodes.length > 0 && (
            <div className="final-export-sample-table">
              <div className="card-title">{t('finalExport.sampleNodes')}</div>
              <pre className="json-preview">{JSON.stringify(preview.sample_nodes, null, 2)}</pre>
            </div>
          )}
          {preview && preview.sample_edges.length > 0 && (
            <div className="final-export-sample-table">
              <div className="card-title">{t('finalExport.sampleEdges')}</div>
              <pre className="json-preview">{JSON.stringify(preview.sample_edges, null, 2)}</pre>
            </div>
          )}
        </div>
      )}

      <div className="card">
        <div className="card-title">{t('finalExport.exportList')}</div>
        <DataTable columns={exportListCols} rows={exportsData?.items ?? []} getKey={r => r.export_id} />
      </div>

      {selectedExportId && (
        <div className="card">
          <div className="card-title">{t('finalExport.exportFiles')}: {selectedExportId}</div>
          <DataTable columns={fileCols} rows={filesData?.files ?? []} getKey={r => r.filename} />
          {manifestJson && (
            <details className="final-export-preview">
              <summary>{t('finalExport.manifest')}</summary>
              <pre className="json-preview">{manifestJson}</pre>
            </details>
          )}
        </div>
      )}
    </div>
  )
}

function FinalMacroClinicalPromotionTab() {
  const { t } = useI18n()
  const sess = readSessionIds()
  const MACRO_TYPES = ['circuit', 'circuit_step', 'projection', 'projection_function', 'circuit_projection_membership', 'region_function', 'triple'] as const
  const [targetTypes, setTargetTypes] = useState<Set<string>>(new Set(['circuit', 'projection']))
  const [batchFilter, setBatchFilter] = useState(sess.batch_id ?? '')
  const [resourceFilter, setResourceFilter] = useState(sess.resource_id ?? '')
  const [sourceAtlas, setSourceAtlas] = useState('')
  const [granularityLevel, setGranularityLevel] = useState('')
  const [confirmText, setConfirmText] = useState('')
  const [dryRun, setDryRun] = useState(true)
  const [promoteDeps, setPromoteDeps] = useState(true)
  const [allowNoMembership, setAllowNoMembership] = useState(false)
  const [allowConflict, setAllowConflict] = useState(true)
  const [result, setResult] = useState<FinalMacroClinicalPromotionResponse | null>(null)
  const [running, setRunning] = useState(false)
  const [notice, setNotice] = useState<NoticeState | null>(null)
  const [runsTick, setRunsTick] = useState(0)
  const [finalType, setFinalType] = useState('circuit')

  const { data: runsData } = useData(() => listFinalMacroClinicalPromotionRuns({ limit: 20 }), [runsTick])
  const { data: finalData } = useData(() => listFinalMacroClinicalObjects(finalType, { limit: 50 }), [finalType, runsTick])

  const buildPayload = (preview: boolean): FinalMacroClinicalPromotionRequest => ({
    target_types: [...targetTypes] as FinalMacroClinicalPromotionRequest['target_types'],
    scope: {
      batch_id: batchFilter || undefined,
      resource_id: resourceFilter || undefined,
      source_atlas: sourceAtlas || undefined,
      granularity_level: granularityLevel || undefined,
    },
    dry_run: preview,
    confirm_text: preview ? undefined : confirmText,
    promote_dependencies: promoteDeps,
    allow_projection_without_membership: allowNoMembership,
    allow_conflict_with_human_reason: allowConflict,
    promote_triples: true,
    promote_evidence: true,
    limit: 500,
    created_by: 'promotion-ui',
  })

  const runPromotion = async (preview: boolean) => {
    if (!preview && confirmText !== 'PROMOTE HUMAN APPROVED MIRROR TO FINAL') {
      setNotice({ type: 'error', message: t('finalPromotion.confirmTextRequired') })
      return
    }
    setRunning(true)
    setNotice(null)
    try {
      const res = await runFinalMacroClinicalPromotion(buildPayload(preview))
      setResult(res)
      setNotice({ type: 'success', message: preview ? t('finalPromotion.previewPromotion') : t('finalPromotion.runPromotion') })
      if (!preview) setRunsTick(x => x + 1)
    } catch (e) {
      setNotice({ type: 'error', message: e instanceof ApiError ? e.message : String(e) })
    } finally {
      setRunning(false)
    }
  }

  const previewCols: Column<FinalMacroClinicalPromotionRecordPreview>[] = useMemo(() => [
    { key: 'target_type', header: t('finalPromotion.targetTypes'), render: r => r.target_type },
    { key: 'mirror_object_id', header: 'mirror_id', render: r => r.mirror_object_id.slice(0, 10) + '…' },
    { key: 'action', header: 'action', render: r => r.action },
    { key: 'eligibility_status', header: 'status', render: r => r.eligibility_status },
    { key: 'reason', header: 'reason', render: r => r.reason ?? '—' },
    { key: 'risk_flags', header: 'risk', render: r => (r.risk_flags ?? []).join(', ') || '—' },
  ], [t])

  const finalCols: Column<FinalMacroClinicalObject>[] = useMemo(() => [
    { key: 'id', header: 'final_id', render: r => r.id.slice(0, 10) + '…' },
    { key: 'final_uid', header: 'final_uid', render: r => r.final_uid ?? '—' },
    { key: 'label', header: 'label', render: r => r.label ?? '—' },
    { key: 'source_mirror_id', header: 'mirror_id', render: r => r.source_mirror_id?.slice(0, 10) ?? '—' },
    { key: 'source_atlas', header: 'atlas', render: r => r.source_atlas ?? '—' },
    { key: 'final_status', header: 'status', render: r => <StatusBadge status={r.final_status} /> },
  ], [])

  return (
    <div className="final-promotion-workbench mirror-kg-panel">
      <Notice notice={notice} onClose={() => setNotice(null)} />
      <div className="card-title">{t('finalPromotion.title')}</div>
      <div className="final-promotion-warning">{t('finalPromotion.description')}</div>
      <div className="final-promotion-warning">{t('finalPromotion.notLlmWarning')}</div>
      <div className="final-promotion-warning">{t('finalPromotion.notKgWarning')}</div>
      <div className="final-promotion-warning">{t('finalPromotion.notExternalDbWarning')}</div>
      <div className="final-promotion-warning">{t('finalPromotion.humanApprovedOnlyWarning')}</div>
      <div className="final-promotion-warning">{t('finalPromotion.signalNotFactWarning')}</div>
      <div className="final-promotion-control-panel card">
        <div className="mirror-review-target-types">
          {MACRO_TYPES.map(tt => (
            <label key={tt} style={{ fontSize: 12 }}>
              <input type="checkbox" checked={targetTypes.has(tt)} onChange={() => setTargetTypes(prev => { const n = new Set(prev); if (n.has(tt)) n.delete(tt); else n.add(tt); return n })} />
              {tt}
            </label>
          ))}
        </div>
        <div className="filter-bar">
          <input className="filter-input" placeholder="batch_id" value={batchFilter} onChange={e => setBatchFilter(e.target.value)} />
          <input className="filter-input" placeholder="resource_id" value={resourceFilter} onChange={e => setResourceFilter(e.target.value)} />
          <input className="filter-input" placeholder="source_atlas" value={sourceAtlas} onChange={e => setSourceAtlas(e.target.value)} />
          <input className="filter-input" placeholder="granularity_level" value={granularityLevel} onChange={e => setGranularityLevel(e.target.value)} />
          <label><input type="checkbox" checked={dryRun} onChange={e => setDryRun(e.target.checked)} /> dry_run</label>
          <label><input type="checkbox" checked={promoteDeps} onChange={e => setPromoteDeps(e.target.checked)} /> {t('finalPromotion.promoteDependencies')}</label>
          <label><input type="checkbox" checked={allowNoMembership} onChange={e => setAllowNoMembership(e.target.checked)} /> {t('finalPromotion.allowProjectionWithoutMembership')}</label>
          <label><input type="checkbox" checked={allowConflict} onChange={e => setAllowConflict(e.target.checked)} /> {t('finalPromotion.allowConflictWithHumanReason')}</label>
        </div>
        {!dryRun && (
          <input className="filter-input final-promotion-confirmation" placeholder={t('finalPromotion.confirmText')} value={confirmText} onChange={e => setConfirmText(e.target.value)} style={{ width: '100%' }} />
        )}
        <div style={{ display: 'flex', gap: 8, marginTop: 8 }}>
          <ActionButton label={t('finalPromotion.previewPromotion')} onClick={() => runPromotion(true)} disabled={running} />
          <ActionButton label={t('finalPromotion.runPromotion')} onClick={() => runPromotion(false)} disabled={running || dryRun || confirmText !== 'PROMOTE HUMAN APPROVED MIRROR TO FINAL'} variant="primary" />
          <button type="button" className="btn" onClick={() => setRunsTick(x => x + 1)}>{t('finalPromotion.runs')}</button>
        </div>
      </div>
      {result && (
        <div className="final-promotion-summary-card card">
          <div>{t('finalPromotion.candidateCount')}: {result.candidate_count}</div>
          <div>{t('finalPromotion.eligibleCount')}: {result.eligible_count}</div>
          <div>{t('finalPromotion.promotedCount')}: {result.promoted_count}</div>
          <div>{t('finalPromotion.blockedCount')}: {result.blocked_count}</div>
          <div>{t('finalPromotion.duplicateCount')}: {result.duplicate_count}</div>
          <div>{t('finalPromotion.riskFlagCount')}: {result.risk_flag_count}</div>
        </div>
      )}
      {result?.records_preview?.length ? (
        <div className="final-promotion-records-table card">
          <div className="card-title">{t('finalPromotion.recordsPreview')}</div>
          <DataTable columns={previewCols} rows={result.records_preview} getKey={r => `${r.target_type}-${r.mirror_object_id}`} emptyText="—" />
        </div>
      ) : null}
      <div className="final-promotion-runs-table card">
        <div className="card-title">{t('finalPromotion.runs')}</div>
        <DataTable columns={[
          { key: 'id', header: 'run_id', render: r => r.id.slice(0, 10) + '…' },
          { key: 'status', header: 'status', render: r => r.status },
          { key: 'promoted_count', header: t('finalPromotion.promotedCount'), render: r => r.promoted_count },
          { key: 'created_at', header: 'created', render: r => r.created_at },
        ]} rows={runsData?.items ?? []} getKey={r => r.id} emptyText="—" />
      </div>
      <div className="final-objects-browser card">
        <div className="card-title">{t('finalPromotion.finalObjects')}</div>
        <select value={finalType} onChange={e => setFinalType(e.target.value)}>
          {MACRO_TYPES.map(tt => <option key={tt} value={tt}>{tt}</option>)}
        </select>
        <DataTable columns={finalCols} rows={finalData?.items ?? []} getKey={r => r.id} emptyText="—" />
      </div>
    </div>
  )
}

function RunsTab({ onViewRun, filterRunId }: { onViewRun: (runId: string) => void; filterRunId?: string }) {
  const { t } = useI18n()
  const [statusFilter, setStatusFilter] = useState('')
  const { data, loading, error, reload } = useData(
    () => listLlmExtractionRuns({ status: statusFilter || undefined, limit: 100 }),
    [statusFilter],
  )

  useEffect(() => { reload() }, [filterRunId, reload])

  const cols: Column<LlmExtractionRun>[] = useMemo(() => [
    {
      key: 'id', header: t('llmExtraction.runId'),
      render: r => (
        <span style={{ display: 'inline-flex', alignItems: 'center', gap: 4 }}>
          <code className="text-mono" style={{ fontSize: 11 }}>{r.id.slice(0, 10)}…</code>
          <CopyButton value={r.id} label="" />
        </span>
      ),
    },
    { key: 'task_type', header: t('llm.taskType'), render: r => r.task_type },
    { key: 'provider', header: t('llm.provider'), render: r => r.provider },
    { key: 'model_name', header: t('llm.model'), render: r => r.model_name },
    { key: 'status', header: t('llm.runStatus'), render: r => <StatusBadge status={r.status} /> },
    { key: 'input_count', header: t('llm.inputCount'), render: r => r.input_count },
    { key: 'output_count', header: t('llm.outputCount'), render: r => r.output_count },
    { key: 'error_count', header: t('llm.errorCount'), render: r => r.error_count },
    { key: 'batch_id', header: 'batch_id', render: r => r.batch_id ? r.batch_id.slice(0, 8) + '…' : '—' },
    { key: 'created_at', header: t('common.createdAt'), render: r => r.created_at.slice(0, 19).replace('T', ' ') },
    {
      key: 'actions', header: t('common.actions'),
      render: r => (
        <button type="button" className="btn btn-sm" onClick={e => { e.stopPropagation(); onViewRun(r.id) }}>
          {t('llm.viewItems')}
        </button>
      ),
    },
  ], [t, onViewRun])

  return (
    <div className="card llm-run-table">
      <div className="filter-bar">
        <select className="filter-select" value={statusFilter} onChange={e => setStatusFilter(e.target.value)}>
          <option value="">{t('llmExtraction.allStatus')}</option>
          {['created', 'running', 'succeeded', 'partially_succeeded', 'failed', 'cancelled'].map(s => (
            <option key={s} value={s}>{s}</option>
          ))}
        </select>
      </div>
      <DataTable
        columns={cols}
        rows={data?.items ?? []}
        loading={loading}
        error={error}
        total={data?.total}
        getKey={r => r.id}
        emptyText={t('common.empty')}
      />
    </div>
  )
}

function ItemRowJson({ label, data }: { label: string; data: unknown }) {
  const { t } = useI18n()
  if (data == null || (typeof data === 'object' && Object.keys(data as object).length === 0)) return null
  return (
    <details className="llm-raw-response">
      <summary>{label}</summary>
      <pre className="llm-response-json">{JSON.stringify(data, null, 2)}</pre>
    </details>
  )
}

function ItemsTab({ filterRunId }: { filterRunId?: string }) {
  const { t } = useI18n()
  const [runFilter, setRunFilter] = useState(filterRunId ?? '')
  const appliedRunId = runFilter.trim() || undefined
  const { data, loading, error } = useData(
    () => listLlmExtractionItems({ run_id: appliedRunId, limit: 100 }),
    [appliedRunId],
  )

  useEffect(() => {
    if (filterRunId) setRunFilter(filterRunId)
  }, [filterRunId])

  const cols: Column<LlmExtractionItem>[] = useMemo(() => [
    {
      key: 'id', header: 'item_id',
      render: r => (
        <span style={{ display: 'inline-flex', alignItems: 'center', gap: 4 }}>
          <code className="text-mono" style={{ fontSize: 11 }}>{r.id.slice(0, 10)}…</code>
          <CopyButton value={r.id} label="" />
        </span>
      ),
    },
    { key: 'run_id', header: t('llmExtraction.runId'), render: r => r.run_id.slice(0, 10) + '…' },
    { key: 'candidate_id', header: t('common.candidateId'), render: r => r.candidate_id?.slice(0, 10) ?? '—' },
    { key: 'task_type', header: t('llm.taskType'), render: r => r.task_type },
    { key: 'status', header: t('llm.itemStatus'), render: r => <StatusBadge status={r.status} /> },
    { key: 'confidence', header: t('llm.confidence'), render: r => r.confidence != null ? r.confidence.toFixed(2) : '—' },
    { key: 'evidence_text', header: t('llm.evidenceText'), render: r => r.evidence_text ?? '—' },
    { key: 'uncertainty_reason', header: t('llm.uncertaintyReason'), render: r => r.uncertainty_reason ?? '—' },
    {
      key: 'responses', header: t('llm.parsedResponse'),
      render: r => (
        <div style={{ minWidth: 200 }}>
          <ItemRowJson label={t('llm.parsedResponse')} data={r.parsed_response_json} />
          <ItemRowJson label={t('llm.normalizedOutput')} data={r.normalized_output_json} />
          {r.raw_response_text && (
            <details className="llm-raw-response">
              <summary>{t('llm.rawResponse')}</summary>
              <pre className="llm-response-json">{r.raw_response_text}</pre>
            </details>
          )}
        </div>
      ),
    },
    { key: 'created_at', header: t('common.createdAt'), render: r => r.created_at.slice(0, 19).replace('T', ' ') },
  ], [t])

  return (
    <div className="card llm-item-table">
      <div className="filter-bar">
        <input
          className="filter-input"
          placeholder={t('llmExtraction.runId')}
          value={runFilter}
          onChange={e => setRunFilter(e.target.value)}
          onKeyDown={e => e.key === 'Enter' && setRunFilter(runFilter.trim())}
        />
        <button type="button" className="btn" onClick={() => setRunFilter(runFilter.trim())}>{t('common.apply')}</button>
      </div>
      <DataTable
        columns={cols}
        rows={data?.items ?? []}
        loading={loading}
        error={error}
        total={data?.total}
        getKey={r => r.id}
        emptyText={t('common.empty')}
      />
    </div>
  )
}

function RegionTab({
  onSelectCandidate,
  onRunCreated,
}: {
  onSelectCandidate: (c: CandidateBrainRegion) => void
  onRunCreated: (runId: string) => void
}) {
  const { t } = useI18n()
  const sess = readSessionIds()
  const [statusFilter, setStatusFilter] = useState('')
  const [batchId, setBatchId] = useState(sess.batch_id ?? '')
  const [appliedBatchId, setAppliedBatchId] = useState(sess.batch_id ?? '')
  const [checked, setChecked] = useState<Set<string>>(new Set())
  const [tick, setTick] = useState(0)
  const [batching, setBatching] = useState(false)
  const [running, setRunning] = useState(false)
  const [showConfirm, setShowConfirm] = useState(false)
  const [showLegacyConfirm, setShowLegacyConfirm] = useState(false)
  const [notice, setNotice] = useState<NoticeState | null>(null)
  const [provider, setProvider] = useState('deepseek')
  const [modelName, setModelName] = useState('')
  const [dryRun, setDryRun] = useState(false)
  const onClose = useCallback(() => setNotice(null), [])

  const { data: options } = useData(() => fetchLlmExtractionOptions(), [])
  const { data: providersData } = useData(() => listLlmProviders(), [])
  const { data: taskTypes } = useData(() => listLlmTaskTypes(), [])
  const maxBatch = options?.max_batch_size ?? 20
  const apiKeyConfigured = options?.api_key_configured ?? true
  const providers = providersData?.providers ?? []

  useEffect(() => {
    const p = providers.find(x => x.name === provider)
    if (p && !modelName) setModelName(p.default_model)
  }, [providers, provider, modelName])

  const filters = {
    candidate_status: statusFilter || undefined,
    batch_id: appliedBatchId || undefined,
    limit: 200,
  }
  const { data, loading, error } = useData(
    () => fetchCandidates(filters),
    [JSON.stringify(filters), tick],
  )

  const toggle = useCallback((id: string) => {
    setChecked(prev => {
      const next = new Set(prev)
      if (next.has(id)) next.delete(id)
      else {
        if (next.size >= maxBatch) {
          setNotice({ type: 'error', message: t('llmExtraction.batchTooLarge', { max: maxBatch }) })
          return prev
        }
        next.add(id)
      }
      return next
    })
  }, [maxBatch, t])

  const cols: Column<CandidateBrainRegion>[] = useMemo(() => [
    {
      key: 'sel', header: t('llmExtraction.select'), width: 48,
      render: r => (
        <input
          type="checkbox"
          checked={checked.has(r.id)}
          onChange={e => { e.stopPropagation(); toggle(r.id) }}
          onClick={e => e.stopPropagation()}
        />
      ),
    },
    { key: 'cn_name', header: t('common.cnName'), render: r => <strong>{r.cn_name ?? r.en_name ?? r.raw_name}</strong> },
    { key: 'en_name', header: t('common.enName'), render: r => r.en_name ?? '—' },
    { key: 'laterality', header: t('common.laterality'), render: r => <StatusBadge status={r.laterality} /> },
    { key: 'candidate_status', header: t('llmExtraction.candidateStatus'), render: r => <StatusBadge status={r.candidate_status} /> },
    { key: 'id', header: t('common.id'), render: r => <code className="text-mono" style={{ fontSize: 11 }}>{r.id.slice(0, 10)}…</code> },
  ], [t, checked, toggle])

  const runBatch = async () => {
    setShowLegacyConfirm(false)
    setBatching(true)
    setNotice(null)
    try {
      const res = await extractCandidatesBatch([...checked])
      setNotice({
        type: res.failed === 0 ? 'success' : 'error',
        message: t('llmExtraction.batchSuccess', { succeeded: res.succeeded, failed: res.failed, requested: res.requested }),
      })
      setChecked(new Set())
      setTick(t => t + 1)
    } catch (e) {
      const msg = e instanceof ApiError ? e.message : String(e)
      setNotice({ type: 'error', message: t('llmExtraction.batchFailed', { error: msg }) })
    } finally {
      setBatching(false)
    }
  }

  const runInfrastructureCompletion = async () => {
    setShowConfirm(false)
    setRunning(true)
    setNotice(null)
    try {
      const res = await runRegionFieldCompletion({
        provider,
        model_name: modelName || undefined,
        candidate_ids: [...checked],
        dry_run: dryRun,
      })
      setNotice({
        type: res.failed === 0 ? 'success' : 'error',
        message: t('llm.regionCompletionSuccess', { succeeded: res.succeeded, failed: res.failed, runId: res.run_id.slice(0, 8) }),
      })
      onRunCreated(res.run_id)
      setChecked(new Set())
      setTick(t => t + 1)
    } catch (e) {
      const msg = e instanceof ApiError ? e.message : String(e)
      setNotice({ type: 'error', message: t('llm.regionCompletionFailed', { error: msg }) })
    } finally {
      setRunning(false)
    }
  }

  return (
    <>
      <Notice notice={notice} onClose={onClose} />
      {options && !options.api_key_configured && (
        <div className="notice notice-error" style={{ marginBottom: 16 }}>
          <span className="notice-msg">{t('llmExtraction.noApiKey')}</span>
        </div>
      )}
      <SafetyNotes />
      {providers.length > 0 && (
        <ProviderPanel
          providers={providers}
          selectedProvider={provider}
          onProviderChange={setProvider}
          modelName={modelName}
          onModelChange={setModelName}
          dryRun={dryRun}
          onDryRunChange={setDryRun}
        />
      )}
      {taskTypes && taskTypes.task_types.length > 0 && (
        <div className="llm-task-panel">
          {taskTypes.task_types.map(tt => (
            <span key={tt.task_type} className={`llm-task-chip ${tt.implemented ? 'implemented' : 'planned'}`}>
              {tt.task_type}{tt.implemented ? ' ✓' : ' (planned)'}
            </span>
          ))}
        </div>
      )}
      <div className="card">
        <div className="filter-bar">
          <select className="filter-select" value={statusFilter} onChange={e => setStatusFilter(e.target.value)}>
            <option value="">{t('llmExtraction.allStatus')}</option>
            {STATUS_OPTIONS.map(s => <option key={s} value={s}>{s}</option>)}
          </select>
          <input
            className="filter-input"
            placeholder={t('llmExtraction.batchIdFilter')}
            value={batchId}
            onChange={e => setBatchId(e.target.value)}
            onKeyDown={e => e.key === 'Enter' && setAppliedBatchId(batchId.trim())}
          />
          <button type="button" className="btn" onClick={() => setAppliedBatchId(batchId.trim())}>{t('common.apply')}</button>
          <ActionButton
            label={t('llm.executeRegionCompletion', { count: checked.size })}
            onClick={() => setShowConfirm(true)}
            disabled={checked.size === 0 || running || (!dryRun && !providers.find(p => p.name === provider)?.configured)}
            loading={running}
            variant="primary"
          />
          <ActionButton
            label={t('llm.legacyBatchBtn', { count: checked.size })}
            onClick={() => setShowLegacyConfirm(true)}
            disabled={checked.size === 0 || batching || !apiKeyConfigured}
            loading={batching}
          />
          <span style={{ fontSize: 12, color: '#888', alignSelf: 'center' }}>
            <Sparkles size={12} style={{ verticalAlign: -1 }} /> {t('llmExtraction.selected', { count: checked.size, max: maxBatch })}
          </span>
        </div>
        <DataTable
          columns={cols}
          rows={data?.items ?? []}
          loading={loading}
          error={error}
          total={data?.total}
          getKey={r => r.id}
          onRowClick={onSelectCandidate}
          emptyText={t('llmExtraction.emptyList')}
        />
      </div>
      <ConfirmDialog
        open={showConfirm}
        title={t('llm.executeRegionCompletion')}
        message={dryRun
          ? t('llm.dryRun') + ` (${checked.size})`
          : t('llmExtraction.confirmMessage', { count: checked.size })}
        confirmLabel={t('llmExtraction.confirmBtn')}
        onConfirm={runInfrastructureCompletion}
        onCancel={() => setShowConfirm(false)}
        loading={running}
      />
      <ConfirmDialog
        open={showLegacyConfirm}
        title={t('llmExtraction.confirmTitle')}
        message={t('llmExtraction.confirmMessage', { count: checked.size })}
        confirmLabel={t('llmExtraction.confirmBtn')}
        onConfirm={runBatch}
        onCancel={() => setShowLegacyConfirm(false)}
        loading={batching}
      />
    </>
  )
}

function MirrorPromotionTab() {
  const { t } = useI18n()
  const sess = readSessionIds()
  const [targetTypes, setTargetTypes] = useState<Set<string>>(new Set(['connection', 'function', 'circuit', 'triple']))
  const [batchFilter, setBatchFilter] = useState(sess.batch_id ?? '')
  const [resourceFilter, setResourceFilter] = useState(sess.resource_id ?? '')
  const [sourceAtlas, setSourceAtlas] = useState('')
  const [granularityLevel, setGranularityLevel] = useState('')
  const [limit, setLimit] = useState(1000)
  const [operator, setOperator] = useState('operator')
  const [reason, setReason] = useState('')
  const [confirmationText, setConfirmationText] = useState('')
  const [running, setRunning] = useState(false)
  const [showConfirm, setShowConfirm] = useState(false)
  const [notice, setNotice] = useState<NoticeState | null>(null)
  const [preview, setPreview] = useState<MirrorPromotionResponse | null>(null)
  const [runsTick, setRunsTick] = useState(0)
  const [finalTick, setFinalTick] = useState(0)

  const { data: runsData, loading: runsLoading, error: runsError } = useData(
    () => listMirrorPromotionRuns({ limit: 50 }),
    [runsTick],
  )

  const finalScope = {
    batch_id: batchFilter || undefined,
    resource_id: resourceFilter || undefined,
    source_atlas: sourceAtlas || undefined,
    granularity_level: granularityLevel || undefined,
    limit: 50,
  }

  const { data: finalConnData } = useData(() => listFinalConnections(finalScope), [finalTick, batchFilter, resourceFilter, sourceAtlas, granularityLevel])
  const { data: finalFnData } = useData(() => listFinalFunctions(finalScope), [finalTick, batchFilter, resourceFilter, sourceAtlas, granularityLevel])
  const { data: finalCircData } = useData(() => listFinalCircuits(finalScope), [finalTick, batchFilter, resourceFilter, sourceAtlas, granularityLevel])
  const { data: finalTripleData } = useData(() => listFinalTriples(finalScope), [finalTick, batchFilter, resourceFilter, sourceAtlas, granularityLevel])

  const toggleTarget = (tt: string) => {
    setTargetTypes(prev => {
      const next = new Set(prev)
      if (next.has(tt)) next.delete(tt)
      else next.add(tt)
      return next
    })
  }

  const buildPayload = () => ({
    target_types: [...targetTypes] as Array<'connection' | 'function' | 'circuit' | 'triple'>,
    scope: {
      batch_id: batchFilter || undefined,
      resource_id: resourceFilter || undefined,
      source_atlas: sourceAtlas || undefined,
      granularity_level: granularityLevel || undefined,
    },
    limit,
  })

  const runPreview = async () => {
    if (targetTypes.size < 1) {
      setNotice({ type: 'error', message: t('mirror.promotion.targetTypes') + ': min 1' })
      return
    }
    setRunning(true)
    setNotice(null)
    try {
      const res = await previewMirrorPromotion(buildPayload())
      setPreview(res)
      setConfirmationText('')
      setNotice({ type: 'success', message: t('mirror.promotion.preview') })
    } catch (e) {
      setNotice({ type: 'error', message: e instanceof ApiError ? e.message : String(e) })
    } finally {
      setRunning(false)
    }
  }

  const canRun = Boolean(
    preview
    && preview.eligible_count > 0
    && operator.trim()
    && reason.trim()
    && preview.required_confirmation
    && confirmationText === preview.required_confirmation,
  )

  const executePromotion = async () => {
    if (!preview) {
      setNotice({ type: 'error', message: t('mirror.promotion.mustPreviewFirst') })
      return
    }
    if (!canRun) {
      setNotice({ type: 'error', message: t('mirror.promotion.confirmationMismatch') })
      return
    }
    setRunning(true)
    setNotice(null)
    try {
      const res = await runMirrorPromotion({
        ...buildPayload(),
        operator: operator.trim(),
        reason: reason.trim(),
        confirmation_text: confirmationText,
      })
      setPreview(res)
      setRunsTick(x => x + 1)
      setFinalTick(x => x + 1)
      setNotice({ type: 'success', message: t('mirror.promotion.run') })
    } catch (e) {
      setNotice({ type: 'error', message: e instanceof ApiError ? e.message : String(e) })
    } finally {
      setRunning(false)
      setShowConfirm(false)
    }
  }

  const previewCols: Column<MirrorPromotionPreviewItem>[] = useMemo(() => [
    { key: 'target_type', header: t('mirror.promotion.targetTypes'), render: r => r.target_type },
    { key: 'mirror_target_id', header: 'mirror_id', render: r => <code style={{ fontSize: 11 }}>{r.mirror_target_id.slice(0, 10)}…</code> },
    { key: 'display_label', header: t('mirror.review.displayLabel'), render: r => r.display_label },
    { key: 'eligible', header: 'eligible', render: r => r.eligible ? <span className="promotion-eligible-badge">yes</span> : <span className="promotion-ineligible-badge">no</span> },
    { key: 'ineligible_reason', header: t('mirror.promotion.ineligibleReason'), render: r => r.ineligible_reason ?? '—' },
    { key: 'duplicate', header: 'duplicate', render: r => r.duplicate ? 'yes' : 'no' },
    { key: 'final_target_type', header: t('mirror.promotion.finalTargetType'), render: r => r.final_target_type ?? '—' },
    { key: 'planned_action', header: t('mirror.promotion.plannedAction'), render: r => r.planned_action ?? '—' },
    { key: 'confidence', header: 'confidence', render: r => r.confidence ?? '—' },
  ], [t])

  const runsCols: Column<MirrorPromotionRun>[] = useMemo(() => [
    { key: 'id', header: 'run_id', render: r => <code style={{ fontSize: 11 }}>{r.id.slice(0, 10)}…</code> },
    { key: 'target_types', header: t('mirror.promotion.targetTypes'), render: r => r.target_types.join(', ') },
    { key: 'status', header: 'status', render: r => <StatusBadge status={r.status} /> },
    { key: 'object_count', header: t('mirror.promotion.objectCount'), render: r => r.object_count },
    { key: 'eligible_count', header: t('mirror.promotion.eligibleCount'), render: r => r.eligible_count },
    { key: 'promoted_count', header: t('mirror.promotion.promotedCount'), render: r => r.promoted_count },
    { key: 'skipped_duplicate_count', header: t('mirror.promotion.skippedDuplicateCount'), render: r => r.skipped_duplicate_count },
    { key: 'operator', header: t('mirror.promotion.operator'), render: r => r.operator ?? '—' },
    { key: 'reason', header: t('mirror.promotion.reason'), render: r => r.reason ?? '—' },
    { key: 'created_at', header: t('mirror.createdAt'), render: r => r.created_at.slice(0, 19).replace('T', ' ') },
  ], [t])

  const finalConnCols: Column<FinalRegionConnection>[] = useMemo(() => [
    { key: 'id', header: 'id', render: r => r.id.slice(0, 8) + '…' },
    { key: 'connection_type', header: 'type', render: r => r.connection_type },
    { key: 'source_atlas', header: 'atlas', render: r => r.source_atlas },
    { key: 'granularity_level', header: 'gran', render: r => r.granularity_level },
    { key: 'final_status', header: 'status', render: r => <StatusBadge status={r.final_status} /> },
  ], [])

  const finalFnCols: Column<FinalRegionFunction>[] = useMemo(() => [
    { key: 'function_term', header: 'term', render: r => r.function_term },
    { key: 'source_atlas', header: 'atlas', render: r => r.source_atlas },
    { key: 'granularity_level', header: 'gran', render: r => r.granularity_level },
    { key: 'final_status', header: 'status', render: r => <StatusBadge status={r.final_status} /> },
  ], [])

  const finalCircCols: Column<FinalRegionCircuit>[] = useMemo(() => [
    { key: 'circuit_name', header: 'name', render: r => r.circuit_name },
    { key: 'source_atlas', header: 'atlas', render: r => r.source_atlas },
    { key: 'final_status', header: 'status', render: r => <StatusBadge status={r.final_status} /> },
  ], [])

  const finalTripleCols: Column<FinalKgTripleRow>[] = useMemo(() => [
    { key: 'triple', header: 'triple', render: r => `${r.subject_label} ${r.predicate} ${r.object_label}` },
    { key: 'source_atlas', header: 'atlas', render: r => r.source_atlas },
    { key: 'final_status', header: 'status', render: r => <StatusBadge status={r.final_status} /> },
  ], [])

  return (
    <div className="mirror-kg-panel mirror-promotion-workbench">
      <Notice notice={notice} onClose={() => setNotice(null)} />
      <div className="mirror-promotion-warning">{t('mirror.promotion.description')}</div>
      <div className="mirror-promotion-warning">{t('mirror.promotion.notLlmWarning')}</div>
      <div className="mirror-promotion-warning">{t('mirror.promotion.notKgWarning')}</div>
      <div className="mirror-promotion-warning">{t('mirror.promotion.finalButNotExternalWarning')}</div>
      <div className="mirror-promotion-warning">{t('mirror.promotion.notPromotionIfNotApproved')}</div>
      <div className="mirror-promotion-filter-panel card">
        <div className="mirror-review-target-types">
          <span className="panel-label">{t('mirror.promotion.targetTypes')}</span>
          {(['connection', 'function', 'circuit', 'triple'] as const).map(tt => (
            <label key={tt} style={{ flexDirection: 'row', alignItems: 'center', gap: 4, fontSize: 12 }}>
              <input type="checkbox" checked={targetTypes.has(tt)} onChange={() => toggleTarget(tt)} />
              {tt === 'connection' ? t('mirror.review.connections') : tt === 'function' ? t('mirror.review.functions') : tt === 'circuit' ? t('mirror.review.circuits') : t('mirror.review.triples')}
            </label>
          ))}
        </div>
        <div className="filter-bar">
          <input className="filter-input" placeholder="batch_id" value={batchFilter} onChange={e => setBatchFilter(e.target.value)} />
          <input className="filter-input" placeholder="resource_id" value={resourceFilter} onChange={e => setResourceFilter(e.target.value)} />
          <input className="filter-input" placeholder="source_atlas" value={sourceAtlas} onChange={e => setSourceAtlas(e.target.value)} />
          <input className="filter-input" placeholder="granularity_level" value={granularityLevel} onChange={e => setGranularityLevel(e.target.value)} />
          <label>{t('mirror.promotion.limit')}
            <input type="number" className="filter-input" min={1} max={5000} value={limit} onChange={e => setLimit(Number(e.target.value))} />
          </label>
          <input className="filter-input" placeholder={t('mirror.promotion.operator')} value={operator} onChange={e => setOperator(e.target.value)} />
          <input className="filter-input" placeholder={t('mirror.promotion.reason')} value={reason} onChange={e => setReason(e.target.value)} />
          <ActionButton label={t('mirror.promotion.preview')} onClick={runPreview} disabled={running} />
          <ActionButton
            label={t('mirror.promotion.run')}
            onClick={() => {
              if (preview && preview.skipped_ineligible_count > 0) {
                setNotice({ type: 'error', message: `${t('mirror.promotion.skippedIneligibleCount')}: ${preview.skipped_ineligible_count}` })
              }
              if (preview?.warnings?.length) {
                setNotice({ type: 'error', message: preview.warnings.join('; ') })
              }
              setShowConfirm(true)
            }}
            disabled={running || !canRun}
            variant="primary"
          />
          <button type="button" className="btn" onClick={() => setRunsTick(x => x + 1)}>{t('mirror.promotion.runs')}</button>
          <button type="button" className="btn" onClick={() => setFinalTick(x => x + 1)}>{t('mirror.promotion.refreshFinal')}</button>
        </div>
        {preview?.required_confirmation && (
          <div className="mirror-promotion-confirmation">
            {t('mirror.promotion.requiredConfirmation')}: {preview.required_confirmation}
          </div>
        )}
        {preview?.required_confirmation && (
          <input
            className="filter-input mirror-promotion-confirmation"
            style={{ marginTop: 8, width: '100%', fontWeight: 'normal', background: '#fff' }}
            placeholder={t('mirror.promotion.confirmationText')}
            value={confirmationText}
            onChange={e => setConfirmationText(e.target.value)}
          />
        )}
      </div>
      {preview && (
        <div className="mirror-promotion-result-card card">
          <div className="card-title">{t('mirror.promotion.previewItems')}</div>
          <div>{t('mirror.promotion.objectCount')}: {preview.object_count}</div>
          <div>{t('mirror.promotion.eligibleCount')}: {preview.eligible_count}</div>
          <div>{t('mirror.promotion.promotedCount')}: {preview.promoted_count}</div>
          <div>{t('mirror.promotion.skippedDuplicateCount')}: {preview.skipped_duplicate_count}</div>
          <div>{t('mirror.promotion.skippedIneligibleCount')}: {preview.skipped_ineligible_count}</div>
          <div>{t('mirror.promotion.failedCount')}: {preview.failed_count}</div>
          {preview.warnings?.length ? <div className="mirror-promotion-warning">{preview.warnings.join('; ')}</div> : null}
        </div>
      )}
      {preview?.preview_items && preview.preview_items.length > 0 && (
        <div className="mirror-promotion-preview-table card">
          <DataTable columns={previewCols} rows={preview.preview_items} getKey={r => `${r.target_type}-${r.mirror_target_id}`} emptyText="—" />
        </div>
      )}
      <div className="mirror-promotion-runs-table card">
        <div className="card-title">{t('mirror.promotion.runs')}</div>
        {runsLoading ? <LoadingState /> : runsError ? <ErrorState error={String(runsError)} /> : (
          <DataTable columns={runsCols} rows={runsData?.items ?? []} getKey={r => r.id} emptyText="—" />
        )}
      </div>
      <details className="mirror-promotion-final-preview card">
        <summary>{t('mirror.promotion.finalConnections')} / {t('mirror.promotion.finalFunctions')} / {t('mirror.promotion.finalCircuits')} / {t('mirror.promotion.finalTriples')}</summary>
        <div className="card-title">{t('mirror.promotion.finalConnections')} ({finalConnData?.total ?? 0})</div>
        <DataTable columns={finalConnCols} rows={finalConnData?.items ?? []} getKey={r => r.id} emptyText="—" />
        <div className="card-title">{t('mirror.promotion.finalFunctions')} ({finalFnData?.total ?? 0})</div>
        <DataTable columns={finalFnCols} rows={finalFnData?.items ?? []} getKey={r => r.id} emptyText="—" />
        <div className="card-title">{t('mirror.promotion.finalCircuits')} ({finalCircData?.total ?? 0})</div>
        <DataTable columns={finalCircCols} rows={finalCircData?.items ?? []} getKey={r => r.id} emptyText="—" />
        <div className="card-title">{t('mirror.promotion.finalTriples')} ({finalTripleData?.total ?? 0})</div>
        <DataTable columns={finalTripleCols} rows={finalTripleData?.items ?? []} getKey={r => r.id} emptyText="—" />
      </details>
      <ConfirmDialog
        open={showConfirm}
        title={t('mirror.promotion.run')}
        message={t('mirror.promotion.confirmRun')}
        confirmLabel={t('mirror.promotion.run')}
        onConfirm={executePromotion}
        onCancel={() => setShowConfirm(false)}
        loading={running}
      />
    </div>
  )
}

// ── Legacy tab id (internal tab components) ───────────────────────────────────

type LegacyFinalTab = 'finalPromotion' | 'finalBrowser' | 'finalExport' | 'promotion' | 'validation' | 'review' | null

function readHashParams(): URLSearchParams {
  const hash = window.location.hash
  const idx = hash.indexOf('?')
  return new URLSearchParams(idx >= 0 ? hash.slice(idx + 1) : '')
}

function updateHashTab(tab: LlmDataTabId, mirrorSub?: MirrorSubTabId) {
  const params = new URLSearchParams()
  params.set('tab', tab)
  if (mirrorSub) params.set('mirrorTab', mirrorSub)
  const base = window.location.hash.split('?')[0] || '#/llm-extraction'
  window.history.replaceState(null, '', `${base}?${params.toString()}`)
}

// ── CandidateDetailDrawer ─────────────────────────────────────────────────────

function CandidateDetailDrawer({
  candidate,
  onClose,
}: {
  candidate: CandidateBrainRegion | null
  onClose: () => void
}) {
  if (!candidate) return null
  return (
    <>
      <div className="candidate-detail-drawer-backdrop" onClick={onClose} />
      <div className="candidate-detail-drawer-panel">
        <div className="candidate-detail-drawer-close-row">
          <button type="button" className="btn btn-sm" onClick={onClose}>✕ 关闭</button>
        </div>
        <div className="candidate-detail-drawer-body">
          <CandidateDetail candidate={candidate} onBack={onClose} />
        </div>
      </div>
    </>
  )
}

// ── CompositeConfirmDialog ────────────────────────────────────────────────────

const COMPOSITE_SUBSTEP_LABELS: Record<string, string[]> = {
  composite_connection_with_function: ['提取连接 / projection', '提取连接功能 / projection_function'],
  composite_circuit_with_function_and_steps: ['提取回路', '提取回路步骤', '提取回路功能（未实现，将跳过）'],
  composite_triple_generation: ['生成三元组'],
}

function CompositeConfirmDialog({
  taskId,
  provider,
  modelName,
  dryRun,
  debugSinglePack = false,
  onDebugSinglePackChange,
  selectedCount,
  pairCount,
  largeWarning,
  scope,
  onConfirm,
  onCancel,
}: {
  taskId: string
  provider: string
  modelName: string
  dryRun: boolean
  debugSinglePack?: boolean
  onDebugSinglePackChange?: (v: boolean) => void
  selectedCount: number
  pairCount?: number
  largeWarning?: string | null
  scope: Record<string, string | undefined | null>
  onConfirm: () => void
  onCancel: () => void
}) {
  const { t } = useI18n()
  const substeps = COMPOSITE_SUBSTEP_LABELS[taskId] ?? []
  const TASK_NAMES: Record<string, string> = {
    composite_connection_with_function: t('llm.composite.connectionWithFunction'),
    composite_circuit_with_function_and_steps: t('llm.composite.circuitWithFunctionAndSteps'),
    composite_triple_generation: t('llm.composite.tripleGeneration'),
  }
  return (
    <>
      <div className="candidate-detail-drawer-backdrop" onClick={onCancel} />
      <div className="llm-composite-confirm-panel">
        <div className="llm-composite-confirm-header">
          <span className="llm-composite-confirm-title">{t('llm.composite.confirmTitle')}: {TASK_NAMES[taskId]}</span>
        </div>
        <div className="llm-composite-confirm-body">
          <div className="llm-composite-substep-list">
            <div className="llm-composite-substep-label">{t('llm.composite.substeps')}:</div>
            {substeps.map((s, i) => (
              <div key={i} className="llm-composite-substep-preview">{i + 1}. {s}</div>
            ))}
          </div>
          <div className="llm-composite-confirm-meta">
            <span>Provider: <b>{provider}</b></span>
            <span>Model: <b>{modelName || '(default)'}</b></span>
            <span>Dry Run: <b>{dryRun ? 'Yes (no writes)' : 'No (will write mirror_*)'}</b></span>
            {taskId !== 'composite_triple_generation' && (
              <span>{t('llm.composite.substepConnection')} 数量: <b>{selectedCount}</b></span>
            )}
            {pairCount != null && pairCount > 0 && (
              <span>Pair 数: <b>{pairCount}</b></span>
            )}
            {Object.entries(scope).filter(([, v]) => v).map(([k, v]) => (
              <span key={k}>{k}: <b>{v}</b></span>
            ))}
          </div>
          <div className="llm-composite-confirm-boundary">
            <div>⚠ {t('llm.composite.onlyMirrorBoundary')}</div>
            <div>⚠ {t('llm.composite.noFinalNoKg')}</div>
            <div>⚠ {t('llm.validation.noAutoChunk')}</div>
            {!dryRun && <div>⚠ {t('llm.composite.mayCallModel')}</div>}
          </div>
          {largeWarning && (
            <div className="llm-large-selection-warning">{largeWarning}</div>
          )}
          {taskId === 'composite_connection_with_function' && onDebugSinglePackChange && (
            <label className="checkbox-label llm-composite-debug-pack">
              <input
                type="checkbox"
                checked={debugSinglePack}
                onChange={e => onDebugSinglePackChange(e.target.checked)}
              />
              {t('llm.composite.debugSinglePack')}
            </label>
          )}
          {taskId === 'composite_connection_with_function' && debugSinglePack && (
            <div className="llm-composite-debug-pack-hint">{t('llm.composite.debugSinglePackHint')}</div>
          )}
        </div>
        <div className="llm-composite-confirm-actions">
          <button type="button" className="llm-btn llm-btn-ghost" onClick={onCancel}>{t('common.cancel')}</button>
          <button type="button" className="llm-btn llm-btn-primary" onClick={onConfirm}>
            {dryRun ? '预览执行 (Dry Run)' : '确认执行'}
          </button>
        </div>
      </div>
    </>
  )
}

// ── CompositeStatusPanel ──────────────────────────────────────────────────────

const STATUS_ICONS: Record<string, string> = {
  pending: '○',
  running: '⟳',
  succeeded: '✓',
  failed: '✗',
  skipped: '⊘',
}

function CompositeStatusPanel({
  substeps,
  result,
  running,
  onDismiss,
  onViewResults,
}: {
  substeps: import('./llm-extraction/services/compositeExtractionRunner').CompositeSubstepResult[]
  result: import('./llm-extraction/services/compositeExtractionRunner').CompositeExtractionResult | null
  running: boolean
  onDismiss: () => void
  onViewResults: () => void
}) {
  const { t } = useI18n()
  return (
    <div className="llm-composite-substep-panel">
      <div className="llm-composite-substep-header">
        <span>{running ? '正在执行组合任务…' : `完成 · ${result?.status ?? ''}`}</span>
        {!running && (
          <button type="button" className="llm-btn llm-btn-ghost" onClick={onDismiss}>✕</button>
        )}
      </div>
      {substeps.map(step => (
        <div
          key={step.id}
          className={[
            'llm-composite-substep-item',
            `llm-composite-substep-${step.status}`,
          ].join(' ')}
        >
          <span className="llm-composite-substep-icon">{STATUS_ICONS[step.status] ?? '○'}</span>
          <span className="llm-composite-substep-name">{t(step.label)}</span>
          {step.createdCount != null && <span className="llm-composite-substep-count">+{step.createdCount}</span>}
          {step.error && <span className="llm-composite-substep-error">{step.error}</span>}
          {step.warnings?.map((w, i) => (
            <span key={i} className="llm-composite-warning">{w}</span>
          ))}
        </div>
      ))}
      {result && !running && (
        <div className="llm-composite-substep-actions">
          <button type="button" className="llm-btn" onClick={onViewResults}>
            {t('llm.composite.viewResults')}
          </button>
        </div>
      )}
    </div>
  )
}

// ── Candidate count minimums (backend min_length only; max_length removed from schema) ──
// NOTE: >50 is a non-blocking warning only; we do NOT hard-block large selections.
const TASK_CANDIDATE_MINIMUMS: Record<string, number> = {
  region_field_completion:              1,
  same_granularity_function_completion: 1,
  same_granularity_connection_completion: 2,
  composite_connection_with_function:   2,
  same_granularity_circuit_completion:  2,
  composite_circuit_with_function_and_steps: 2,
  composite_triple_generation:          0,
}

const LARGE_CANDIDATE_THRESHOLD = 50
const LARGE_PAIR_THRESHOLD = 200

function getMinCandidateCountForTask(taskId: string): number {
  return TASK_CANDIDATE_MINIMUMS[taskId] ?? 1
}

/** Returns a blocking error message if count < min, otherwise null. */
function getCandidateTooFewError(taskId: string, selectedCount: number): string | null {
  const min = getMinCandidateCountForTask(taskId)
  if (selectedCount < min) {
    return `当前任务至少需要选择 ${min} 个候选脑区，当前只选择了 ${selectedCount} 个。`
  }
  return null
}

/** Returns a non-blocking warning message for large selections, otherwise null. */
function getCandidateLargeCountWarning(taskId: string, selectedCount: number): string | null {
  const warnings: string[] = []
  const isConnection = taskId.includes('connection')
  const isCircuit = taskId.includes('circuit')

  if (selectedCount > LARGE_CANDIDATE_THRESHOLD) {
    warnings.push(
      `当前选择了 ${selectedCount} 个候选脑区，模型输入、费用和运行时间可能明显增加。系统不会自动截断或分批，请确认继续。`,
    )
  }
  if (isConnection) {
    const pairCount = selectedCount * (selectedCount - 1) / 2
    if (pairCount > LARGE_PAIR_THRESHOLD) {
      warnings.push(
        `当前将形成 ${pairCount} 个候选连接 pair。系统不会截断 pair，也不会自动分批，可能导致 prompt 较大或运行时间较长。`,
      )
    }
  } else if (isCircuit && selectedCount > LARGE_CANDIDATE_THRESHOLD) {
    // already covered by general warning above
  } else if (selectedCount > LARGE_CANDIDATE_THRESHOLD && !isConnection) {
    // general warning already added
  }
  return warnings.length ? warnings.join('\n') : null
}

function getPairCountForTask(taskId: string, selectedCount: number): number | undefined {
  if (taskId.includes('connection') && selectedCount >= 2) {
    return selectedCount * (selectedCount - 1) / 2
  }
  return undefined
}

// ── Error boundary (local, does not affect global routing) ─────────────────────

class LlmErrorBoundary extends React.Component<{ children: React.ReactNode }, { hasError: boolean; error: Error | null }> {
  constructor(props: { children: React.ReactNode }) {
    super(props)
    this.state = { hasError: false, error: null }
  }
  static getDerivedStateFromError(error: Error) {
    return { hasError: true, error }
  }
  render() {
    if (this.state.hasError) {
      return (
        <div style={{ padding: 40, textAlign: 'center' }}>
          <h2 style={{ color: '#cf1322', marginBottom: 12 }}>LLM 提取页面加载异常</h2>
          <p style={{ color: '#666', marginBottom: 16, fontSize: 14 }}>
            页面渲染时发生错误，已自动隔离，不影响其他页面。
          </p>
          <details style={{ textAlign: 'left', maxWidth: 600, margin: '0 auto' }}>
            <summary style={{ cursor: 'pointer', color: '#888', fontSize: 13 }}>错误详情</summary>
            <pre style={{ background: '#fff2f0', padding: 12, borderRadius: 6, fontSize: 12, overflow: 'auto', marginTop: 8 }}>
              {this.state.error?.message ?? 'Unknown error'}
            </pre>
          </details>
          <button
            className="llm-btn llm-btn-primary"
            style={{ marginTop: 20 }}
            onClick={() => this.setState({ hasError: false, error: null })}
          >
            重试
          </button>
        </div>
      )
    }
    return this.props.children
  }
}

// ── LlmExtractionPage ─────────────────────────────────────────────────────────

export function LlmExtractionPage() {
  const { t } = useI18n()
  const initialParams = readHashParams()
  const rawTab = initialParams.get('tab')
  const LEGACY_FINAL_TAB_SET = new Set<string>([
    'finalPromotion', 'finalBrowser', 'finalExport', 'promotion', 'validation', 'review',
  ])

  const [activeDataTab, setActiveDataTab] = useState<LlmDataTabId>(() =>
    rawTab && LEGACY_FINAL_TAB_SET.has(rawTab) ? 'finalLinks' : parseLlmDataTab(rawTab),
  )
  const [mirrorSubTab, setMirrorSubTab] = useState<MirrorSubTabId>(() =>
    parseMirrorSubTab(initialParams.get('mirrorTab') ?? rawTab),
  )
  const [mirrorViewMode, setMirrorViewMode] = useState<'table' | 'cards'>('table')
  const [legacyFinalTab, setLegacyFinalTab] = useState<LegacyFinalTab>(() =>
    rawTab && LEGACY_FINAL_TAB_SET.has(rawTab) ? (rawTab as LegacyFinalTab) : null,
  )
  const [selectedCandidate, setSelectedCandidate] = useState<CandidateBrainRegion | null>(null)
  const [highlightRunId, setHighlightRunId] = useState<string | undefined>()
  const [itemsRunFilter, setItemsRunFilter] = useState<string | undefined>()
  const [selectedTask, setSelectedTask] = useState('region_field_completion')
  const [provider, setProvider] = useState('deepseek')
  const [modelName, setModelName] = useState('')
  const [dryRun, setDryRun] = useState(true)
  const [bulkConfirmTrigger, setBulkConfirmTrigger] = useState(0)
  const [batchLoading, setBatchLoading] = useState(false)
  const [selectedCount, setSelectedCount] = useState(0)
  // Composite task state
  const [compositeConfirmOpen, setCompositeConfirmOpen] = useState(false)
  const [compositeRunning, setCompositeRunning] = useState(false)
  const [compositeSubsteps, setCompositeSubsteps] = useState<CompositeSubstepResult[]>([])
  const [compositeResult, setCompositeResult] = useState<CompositeExtractionResult | null>(null)
  const [selectedCandidateIds, setSelectedCandidateIds] = useState<string[]>([])
  const selectedCandidateIdsRef = useRef<string[]>([])
  const handleSelectionIdsChange = useCallback((ids: string[]) => {
    selectedCandidateIdsRef.current = ids
    setSelectedCandidateIds(ids)
  }, [])
  const [candidateMinError, setCandidateMinError] = useState<string | null>(null)
  const [candidateLargeWarning, setCandidateLargeWarning] = useState<string | null>(null)
  const [debugSinglePack, setDebugSinglePack] = useState(false)
  // New simplified run modal
  const [showRunModal, setShowRunModal] = useState(false)
  const [showFullExtractModal, setShowFullExtractModal] = useState(false)
  const [poolPreSyncedForModal, setPoolPreSyncedForModal] = useState(false)
  const [poolWorkflowType, setPoolWorkflowType] = useState('connection_with_function')

  const { setExpanded: setLogConsoleExpanded, errorCount: logErrorCount } = useWorkbenchLog()
  const prevLogErrorCountRef = useRef(0)
  const DISMISSED_RUNS_STORAGE_KEY = 'llm.dismissedWorkflowRunIds'
  const dismissedWorkflowRunIdsRef = useRef<Set<string>>(
    (() => {
      try {
        const raw = sessionStorage.getItem(DISMISSED_RUNS_STORAGE_KEY)
        return new Set<string>(raw ? (JSON.parse(raw) as string[]) : [])
      } catch {
        return new Set<string>()
      }
    })(),
  )
  // Session scope & providers
  const { scope, updateScope, clearScope } = useSessionScope()
  const { data: providersData } = useData(() => listLlmProviders(), [])
  const { data: taskTypesData } = useData(() => listLlmTaskTypes(), [])
  const providers = providersData?.providers ?? []
  const taskTypes = taskTypesData?.task_types ?? []

  const DATA_TAB_LABELS: Record<LlmDataTabId, string> = useMemo(() => ({
    candidates: t('llm.dataFirst.candidates'),
    mirror: t('llm.dataFirst.mirrorExtraction'),
    runs: t('llm.dataFirst.runs'),
    items: t('llm.dataFirst.items'),
    macroClinical: t('llm.dataFirst.macroClinical'),
    finalLinks: t('llm.dataFirst.finalLinks'),
    fieldCompletions: '字段补全',
  }), [t])

  const MIRROR_SUB_LABELS: Record<MirrorSubTabId, string> = useMemo(() => ({
    connections: t('mirror.connections'),
    functions: t('mirror.functions'),
    circuits: t('mirror.circuits'),
    triples: t('mirror.triples'),
  }), [t])

  // ── Candidate pool ──────────────────────────────────────────────────
  // Derived synchronously (useMemo) so it is never null on first paint
  // when session scope is already loaded — avoids a race where
  // openPoolExtractModal calls setPoolCandidates before the useEffect
  // that used to set poolScope has committed.
  const poolScope: PoolScope = useMemo(() => ({
    sourceAtlas: scope.source_atlas || 'AAL3',
    granularityLevel: scope.granularity_level || 'macro',
    granularityFamily: scope.granularity_family || 'macro_clinical',
  }), [scope.source_atlas, scope.granularity_level, scope.granularity_family])

  const {
    pool,
    pooledCandidateIds,
    addCandidates,
    setPoolCandidates,
    clearPool,
    refresh,
  } = useCandidatePool(poolScope)

  const setupExtractionPoolFromCurrentSelection = useCallback(async () => {
    const ids = [...new Set(selectedCandidateIdsRef.current.filter(Boolean))]
    if (ids.length < 2) {
      throw new PoolSetupError('当前没有可加入提取池的候选脑区（至少需要 2 个）')
    }
    const payloadScope: PoolScope = {
      sourceAtlas: scope.source_atlas || 'AAL3',
      granularityLevel: scope.granularity_level || 'macro',
      granularityFamily: scope.granularity_family || 'macro_clinical',
    }
    if (import.meta.env.DEV) {
      console.info('[LlmExtractionPage] setupExtractionPool', {
        selectedIdsLength: ids.length,
        batchId: scope.batch_id || null,
        atlas: payloadScope.sourceAtlas,
        granularity: payloadScope.granularityLevel,
        granularityFamily: payloadScope.granularityFamily,
        candidateIdsSample: ids.slice(0, 3),
      })
    }
    return setPoolCandidates(ids, payloadScope)
  }, [scope.source_atlas, scope.granularity_level, scope.granularity_family, scope.batch_id, setPoolCandidates])

  const openPoolExtractModal = useCallback(async (
    workflowType: string,
    task: string,
  ) => {
    const ids = selectedCandidateIdsRef.current
    if (ids.length < 2) {
      setCandidateMinError('请至少选择 2 个脑区后再提取')
      return
    }
    setCandidateMinError(null)
    setSelectedTask(task)
    setDryRun(false)
    setPoolWorkflowType(workflowType)
    try {
      await setupExtractionPoolFromCurrentSelection()
      setPoolPreSyncedForModal(true)
      setShowFullExtractModal(true)
    } catch (err) {
      console.error('[LlmExtractionPage] setPoolCandidates failed:', err)
      if (err instanceof PoolSetupError) {
        setCandidateMinError(err.message)
      } else {
        setCandidateMinError('设置提取池失败，请重试')
      }
    }
  }, [setupExtractionPoolFromCurrentSelection])

  const switchDataTab = useCallback((tabId: LlmDataTabId) => {
    setActiveDataTab(tabId)
    setLegacyFinalTab(null)
  }, [])

  const handleBatchExtract = useCallback(() => {
    const tooFewError = getCandidateTooFewError(selectedTask, selectedCandidateIds.length)
    if (tooFewError) { setCandidateMinError(tooFewError); return }
    setCandidateMinError(null)
    setCompositeResult(null)
    setCompositeSubsteps([])
    // Auto-add selected candidates to pool (silent, fire-and-forget)
    if (selectedCandidateIds.length > 0) {
      addCandidates(selectedCandidateIds).catch(() => {})
    }
    setShowRunModal(true)
  }, [selectedTask, selectedCandidateIds.length, selectedCandidateIds, addCandidates])

  const handleRunCreated = useCallback((runId: string) => {
    setHighlightRunId(runId)
  }, [])

  const runCompositeTask = useCallback(() => {
    if (!isCompositeTask(selectedTask)) return
    setCompositeConfirmOpen(false)
    setShowRunModal(true)
  }, [selectedTask])

  const navigateToRuns = useCallback(() => switchDataTab('runs'), [switchDataTab])
  const navigateToItems = useCallback((runId: string) => {
    setItemsRunFilter(runId)
    switchDataTab('items')
  }, [switchDataTab])

  const currentProvider = providers.find(p => p.name === provider)

  return (
    <LlmErrorBoundary>
    <div className="llm-data-first-page">
      <div className="llm-data-first-header card">
        <div className="llm-data-first-header-left">
          <div className="llm-data-first-title">{t('llm.dataFirst.title')}</div>
          <div className="llm-data-first-subtitle">{t('llm.dataFirst.subtitle')}</div>
        </div>
        <div className="llm-compact-scope-bar">
          {scope.batch_id && <span className="llm-scope-chip">batch: {scope.batch_id}</span>}
          {scope.resource_id && <span className="llm-scope-chip">resource: {scope.resource_id}</span>}
          {scope.source_atlas && <span className="llm-scope-chip">atlas: {scope.source_atlas}</span>}
          {scope.granularity_level && <span className="llm-scope-chip">gran: {scope.granularity_level}</span>}
          {!scope.batch_id && !scope.resource_id && !scope.source_atlas && !scope.granularity_level && (
            <span className="llm-scope-chip llm-scope-chip-empty">—</span>
          )}
          <button type="button" className="llm-btn llm-btn-ghost" onClick={clearScope}>{t('llm.workflow.clearScope')}</button>
          {currentProvider && (
            <span className={`llm-provider-badge-sm ${currentProvider.configured ? 'configured' : 'not-configured'}`}>
              {provider}: {currentProvider.configured ? 'OK' : 'N/A'}
            </span>
          )}
        </div>
      </div>

      <CircuitToFunctionsPendingBanner />

      <div className="llm-data-first-boundary">
        {t('llm.dataFirst.boundaryShort')}
      </div>

      <LlmTaskToolbar
        taskTypes={taskTypes}
        selectedTask={selectedTask}
        onTaskChange={setSelectedTask}
        providers={providers}
        provider={provider}
        onProviderChange={setProvider}
        modelName={modelName}
        onModelChange={setModelName}
        dryRun={dryRun}
        onDryRunChange={setDryRun}
        selectedCount={selectedCount}
        onBatchExtract={handleBatchExtract}
        onOpenMacroBatch={() => switchDataTab('macroClinical')}
        batchDisabled={activeDataTab !== 'candidates' && !isCompositeTask(selectedTask)}
        batchLoading={batchLoading}
      />

      {/* Quick extraction cards — always visible */}
      {activeDataTab === 'candidates' && (
        <QuickExtractionCards
          selectedCount={selectedCount}
          onExtractFunction={() => {
            void openPoolExtractModal('same_granularity_function_completion', 'same_granularity_function_completion')
          }}
          onExtractConnection={() => {
            void openPoolExtractModal('connection_with_function', 'same_granularity_connection_completion')
          }}
          onExtractCircuit={() => {
            void openPoolExtractModal('circuit_with_function_steps', 'composite_circuit_with_function_and_steps')
          }}
        />
      )}

      {/* Pool indicator — appears when there are pooled candidates */}
      {activeDataTab === 'candidates' && pool && (
        <div style={{
          display: 'flex', alignItems: 'center', justifyContent: 'space-between',
          padding: '10px 16px', marginBottom: 12,
          background: 'linear-gradient(135deg, #eef4ff, #f0f5ff)',
          border: '1px solid #d6e4ff', borderRadius: 10, fontSize: 14,
        }}>
          <span>
            🧠 <strong>{pool.source_atlas}</strong> · {pool.granularity_level}
            &nbsp;当前池 <strong style={{ color: '#2563eb' }}>{pool.candidate_count}</strong> 脑区
            &nbsp;· 预估 <strong>{pool.pair_count?.toLocaleString()}</strong> 对
          </span>
          <div style={{ display: 'flex', gap: 8 }}>
            <button
              className="llm-btn llm-btn-ghost"
              style={{ fontSize: 12 }}
              onClick={async () => {
                if (selectedCandidateIdsRef.current.length < 2) {
                  setCandidateMinError('请至少选择 2 个脑区')
                  return
                }
                setCandidateMinError(null)
                try {
                  await setupExtractionPoolFromCurrentSelection()
                } catch (err) {
                  console.error('[LlmExtractionPage] setPoolCandidates failed:', err)
                  if (err instanceof PoolSetupError) {
                    setCandidateMinError(err.message)
                  } else {
                    setCandidateMinError('设置提取池失败，请重试')
                  }
                }
              }}
              disabled={selectedCount < 2}
            >
              设为提取池 ({selectedCount})
            </button>
            <button
              className="llm-btn"
              style={{ fontSize: 12, background: '#2563eb', color: '#fff', border: 'none', padding: '4px 14px', borderRadius: 6, fontWeight: 500, cursor: 'pointer' }}
              onClick={async () => {
                await openPoolExtractModal('connection_with_function', 'same_granularity_connection_completion')
              }}
            >
              ⚡ 全量提取
            </button>
            <button
              className="llm-btn llm-btn-ghost"
              style={{ fontSize: 12, color: '#cf1322' }}
              onClick={() => { if (confirm('清空候选池？')) clearPool() }}
            >
              清空
            </button>
          </div>
        </div>
      )}


      {candidateMinError && (
        <div className="llm-validation-error">
          <span className="llm-validation-error-msg">{candidateMinError}</span>
          <button
            type="button"
            className="llm-btn llm-btn-xs llm-btn-ghost"
            onClick={() => setCandidateMinError(null)}
          >
            关闭
          </button>
        </div>
      )}
      {!candidateMinError && candidateLargeWarning && (
        <div className="llm-selection-large-warning">
          <span>⚠ {candidateLargeWarning}</span>
          <button
            type="button"
            className="llm-btn llm-btn-xs llm-btn-ghost"
            onClick={() => setCandidateLargeWarning(null)}
          >
            知道了
          </button>
        </div>
      )}

      <div className="llm-data-tabs">
        {(Object.keys(DATA_TAB_LABELS) as LlmDataTabId[]).map(tabId => (
          <button
            key={tabId}
            type="button"
            className={`llm-data-tab${activeDataTab === tabId && !legacyFinalTab ? ' llm-data-tab-active' : ''}`}
            onClick={() => switchDataTab(tabId)}
          >
            {DATA_TAB_LABELS[tabId]}
          </button>
        ))}
      </div>

      <div className="llm-data-first-workspace">
        {legacyFinalTab === 'finalPromotion' && <FinalMacroClinicalPromotionTab />}
        {legacyFinalTab === 'finalBrowser' && <FinalKgBrowserTab />}
        {legacyFinalTab === 'finalExport' && <FinalKgExportTab />}
        {legacyFinalTab === 'promotion' && <MirrorPromotionTab />}
        {legacyFinalTab === 'validation' && (
          <>
            <GovernanceDashboard activeGate="validation" onSwitchGate={() => {}} onJumpToFinalPromotion={() => setLegacyFinalTab('finalPromotion')} />
            <div className="governance-gate-workspace"><MirrorValidationTab /></div>
          </>
        )}
        {legacyFinalTab === 'review' && (
          <>
            <GovernanceDashboard activeGate="review" onSwitchGate={() => {}} onJumpToFinalPromotion={() => setLegacyFinalTab('finalPromotion')} />
            <div className="governance-gate-workspace"><MirrorReviewTab /></div>
          </>
        )}

        {!legacyFinalTab && activeDataTab === 'candidates' && (
          <DataFirstCandidatesTab
            onSelectCandidate={setSelectedCandidate}
            onRunCreated={handleRunCreated}
            selectedTask={selectedTask}
            provider={provider}
            modelName={modelName}
            dryRun={dryRun}
            confirmTrigger={bulkConfirmTrigger}
            scopeBatchId={scope.batch_id}
            onScopeBatchChange={batchId => updateScope({ batch_id: batchId })}
            onBatchStart={() => setBatchLoading(true)}
            onBatchEnd={() => setBatchLoading(false)}
            onSelectionChange={setSelectedCount}
            onSelectionIdsChange={handleSelectionIdsChange}
            pooledCandidateIds={pooledCandidateIds}
          />
        )}
        {!legacyFinalTab && activeDataTab === 'runs' && (
          <RunsTab filterRunId={highlightRunId} onViewRun={navigateToItems} />
        )}
        {!legacyFinalTab && activeDataTab === 'items' && (
          <div>
            <div className="tabs" style={{ marginBottom: 0, display: 'flex', justifyContent: 'space-between', alignItems: 'center' }}>
              <div style={{ display: 'flex' }}>
                {EXTRACTION_TYPE_CONFIGS.filter(c => c.targetType !== 'extraction_item' && c.targetType !== 'validation_result' && c.targetType !== 'review_item' && c.targetType !== 'dual_model_result').map(c => (
                  <button key={c.targetType}
                    className={`tab-btn${mirrorSubTab === c.targetType && mirrorViewMode === 'cards' ? ' active' : ''}`}
                    onClick={() => { setMirrorSubTab(c.targetType as any); setMirrorViewMode('cards') }}
                    style={{ fontSize: 12, padding: '6px 10px' }}
                  >{c.tabLabel}</button>
                ))}
              </div>
              <div className="tabs" style={{ marginBottom: 0 }}>
                <button className={`tab-btn${mirrorViewMode === 'table' ? ' active' : ''}`} onClick={() => setMirrorViewMode('table')}>
                  {t('extraction.viewTable')}
                </button>
              </div>
            </div>
            {mirrorViewMode === 'table' ? (
              <ItemsTab filterRunId={itemsRunFilter} />
            ) : (
              <ExtractionResultPanel
                key={mirrorSubTab}
                config={EXTRACTION_TYPE_CONFIGS.find(c => c.targetType === mirrorSubTab) ?? EXTRACTION_TYPE_CONFIGS[0]}
              />
            )}
          </div>
        )}
        {!legacyFinalTab && activeDataTab === 'mirror' && (
          <MirrorExtractionPanel initialSubTab={mirrorSubTab} />
        )}
        {!legacyFinalTab && activeDataTab === 'macroClinical' && (
          <MacroClinicalSchemaTab dataFirstMode />
        )}
        {!legacyFinalTab && activeDataTab === 'finalLinks' && (
          <FinalLinksPanel />
        )}
        {!legacyFinalTab && activeDataTab === 'fieldCompletions' && (
          <FieldCompletionTab providers={providers} />
        )}
      </div>

      <CandidateDetailDrawer
        candidate={selectedCandidate}
        onClose={() => setSelectedCandidate(null)}
      />

      {/* Extraction run modal — all task types */}
      {showRunModal && (
        <ExtractionRunModal
          taskId={selectedTask}
          provider={provider}
          modelName={modelName}
          dryRun={dryRun}
          selectedCandidateIds={selectedCandidateIds}
          scope={scope}
          debugSinglePack={debugSinglePack}
          onClose={() => setShowRunModal(false)}
          onViewMirror={() => { setShowRunModal(false); switchDataTab('mirror') }}
          onViewItems={() => { setShowRunModal(false); switchDataTab('items') }}
        />
      )}

      <PoolExtractionModal
        open={showFullExtractModal}
        pool={pool}
        pooledCandidateIds={pooledCandidateIds}
        provider={provider}
        modelName={modelName}
        providers={providers}
        workflowType={poolWorkflowType}
        onProviderChange={setProvider}
        onModelChange={setModelName}
        onPoolRefresh={refresh}
        onSetPoolCandidates={setPoolCandidates}
        selectedCandidateIds={selectedCandidateIds}
        candidateLabels={{}}
        skipInitialPoolSync={poolPreSyncedForModal}
        onClose={() => {
          setShowFullExtractModal(false)
          setPoolPreSyncedForModal(false)
        }}
      />
    </div>
    </LlmErrorBoundary>
  )
}
