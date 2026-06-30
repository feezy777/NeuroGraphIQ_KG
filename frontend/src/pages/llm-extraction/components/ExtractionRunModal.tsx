import { useState, useEffect, useRef, useCallback } from 'react'
import type {
  CompositeExtractionTaskId,
  CompositeExtractionContext,
  CompositeSubstepResult,
  CompositeExtractionResult,
  CompositeExtractionStatus,
} from '../services/compositeExtractionRunner'
import { runCompositeExtractionTask, COMPOSITE_TASK_SUBSTEP_LABELS } from '../services/compositeExtractionRunner'
import {
  runSameGranularityFunctionExtraction,
  runSameGranularityConnectionExtraction,
  runSameGranularityCircuitExtraction,
  runRegionFieldCompletion,
  getExtractionPromptTemplates,
  cancelCompositeWorkflow,
  pauseCompositeWorkflow,
  resumeCompositeWorkflow,
  type ExtractionPromptTemplate,
} from '../../../api/endpoints'
import { ApiError } from '../../../api/client'
import { useData } from '../../../hooks/useData'
import { useI18n } from '../../../i18n-context'

// ── Types ──────────────────────────────────────────────────────────────────
type ModalPhase = 'confirm' | 'running' | 'complete'
type ConfirmTab = 'params' | 'prompt'

type SingleStepTaskId =
  | 'same_granularity_function_completion'
  | 'same_granularity_connection_completion'
  | 'same_granularity_circuit_completion'
  | 'region_field_completion'

type TaskDef = {
  id: string; label: string; type: 'composite' | 'single'
  taskParams?: { key: string; label: string; min: number; max: number; default: number }[]
  promptCategory?: string
}

const BATCH_SIZE = 20 // Process 20 regions per LLM call

const TASK_DEFS: Record<string, TaskDef> = {
  composite_connection_with_function: { id: 'composite_connection_with_function', label: '连接+功能提取', type: 'composite' },
  composite_circuit_with_function_and_steps: { id: 'composite_circuit_with_function_and_steps', label: '回路+步骤+功能提取', type: 'composite',
    taskParams: [{ key: 'max_circuits', label: '最大回路数', min: 1, max: 500, default: 100 }] },
  composite_triple_generation: { id: 'composite_triple_generation', label: '生成三元组', type: 'composite' },
  same_granularity_function_completion: { id: 'same_granularity_function_completion', label: '脑区功能提取', type: 'single',
    taskParams: [{ key: 'max_functions_per_region', label: '每脑区最大功能数', min: 1, max: 20, default: 5 }], promptCategory: 'extraction' },
  same_granularity_connection_completion: { id: 'same_granularity_connection_completion', label: '连接提取', type: 'single',
    taskParams: [{ key: 'max_candidate_pairs', label: '最大候选 pair 数', min: 1, max: 10000, default: 500 }] },
  same_granularity_circuit_completion: { id: 'same_granularity_circuit_completion', label: '回路提取', type: 'single',
    taskParams: [{ key: 'max_circuits', label: '最大回路数', min: 1, max: 100, default: 30 }] },
  region_field_completion: { id: 'region_field_completion', label: '脑区字段补全', type: 'single' },
}

// ── Props ──────────────────────────────────────────────────────────────────
export interface ExtractionRunModalProps {
  taskId: string; provider: string; modelName: string; dryRun: boolean
  selectedCandidateIds: string[]; scope: CompositeExtractionContext['scope']; debugSinglePack?: boolean
  onClose: () => void; onViewMirror: () => void; onViewItems: () => void
}

// ── Helpers ────────────────────────────────────────────────────────────────
const STEP_STATUS_LABELS: Record<string, string> = {
  pending: '等待中', running: '执行中', succeeded: '已完成', failed: '失败',
  skipped: '已跳过', skipped_no_projection: '无投影', skipped_dependency_failed: '前置失败',
  cancelled: '已取消', failed_validation: '校验失败',
}
function formatElapsed(ms: number): string { const s = Math.floor(ms/1000); const m = Math.floor(s/60); return `${m}:${String(s%60).padStart(2,'0')}` }
function overallStatusLabel(s: string): string {
  const m: Record<string,string> = { succeeded:'全部完成', partially_succeeded:'部分完成', failed:'执行失败', dry_run:'Dry Run预览', no_edges:'无连接边', cancelled:'已取消' }
  return m[s] ?? s
}

// ── Component ──────────────────────────────────────────────────────────────
export function ExtractionRunModal(props: ExtractionRunModalProps) {
  const { t } = useI18n()
  const { taskId, provider, modelName, dryRun: initialDryRun, selectedCandidateIds, scope, debugSinglePack, onClose, onViewMirror, onViewItems } = props
  const taskDef = TASK_DEFS[taskId] ?? { id: taskId, label: taskId, type: 'single' as const }
  const taskLabel = taskDef.label
  const isComposite = taskDef.type === 'composite'

  const [phase, setPhase] = useState<ModalPhase>('confirm')
  const [confirmTab, setConfirmTab] = useState<ConfirmTab>('params')
  const [dryRun, setDryRun] = useState(initialDryRun)
  const [temperature, setTemperature] = useState(0.7)
  const [maxTokens, setMaxTokens] = useState(4096)
  const [taskParamValues, setTaskParamValues] = useState<Record<string, number>>({})
  const [createMirror, setCreateMirror] = useState(true)
  const [createTriples, setCreateTriples] = useState(true)
  const [createEvidence, setCreateEvidence] = useState(true)
  const [promptTemplateKey, setPromptTemplateKey] = useState('')
  const [systemPrompt, setSystemPrompt] = useState('')
  const [userPrompt, setUserPrompt] = useState('')

  // ── Execution state ────────────────────────────────────────────────────
  const [substeps, setSubsteps] = useState<CompositeSubstepResult[]>([])
  const [result, setResult] = useState<CompositeExtractionResult | null>(null)
  const [elapsedMs, setElapsedMs] = useState(0)
  const [workflowRunId, setWorkflowRunId] = useState<string | undefined>()
  const [error, setError] = useState<string | null>(null)
  // Batch progress
  const [batchProgress, setBatchProgress] = useState({ done: 0, total: 0, created: 0, packDone: 0, packTotal: 0 })
  const timerRef = useRef<ReturnType<typeof setInterval> | null>(null)
  const cancelledRef = useRef(false)
  const abortRef = useRef<AbortController | null>(null)

  const { data: templatesData } = useData(() => getExtractionPromptTemplates(taskDef.promptCategory ?? 'extraction'), [taskDef.promptCategory])
  const templates = templatesData?.items ?? []

  useEffect(() => { if (timerRef.current) clearInterval(timerRef.current) }, [])
  useEffect(() => {
    if (taskDef.taskParams) { const d: Record<string,number> = {}; for (const p of taskDef.taskParams) d[p.key] = p.default; setTaskParamValues(d) }
  }, [taskId])
  useEffect(() => {
    if (promptTemplateKey && templates.length) { const tm = templates.find(t => t.key === promptTemplateKey); if (tm) { setSystemPrompt(tm.system_prompt ?? ''); setUserPrompt(tm.template ?? '') } }
  }, [promptTemplateKey, templates])

  // ── Execution ──────────────────────────────────────────────────────────
  const startExecution = useCallback(async () => {
    setPhase('running'); setError(null); cancelledRef.current = false
    abortRef.current = new AbortController()
    const signal = abortRef.current.signal
    const startTime = Date.now()
    timerRef.current = setInterval(() => setElapsedMs(Date.now() - startTime), 1000)

    const commonParams = {
      provider, model_name: modelName || undefined,
      temperature: temperature !== 0.7 ? temperature : undefined,
      max_tokens: maxTokens !== 4096 ? maxTokens : undefined,
      dry_run: dryRun,
      ...(promptTemplateKey ? { prompt_template_key: promptTemplateKey } : {}),
      ...(systemPrompt.trim() ? { prompt_overrides: { system_prompt: systemPrompt.trim() } } : {}),
    }

    try {
      if (isComposite) {
        // ── Composite: backend workflow with progress tracking ────────────
        setBatchProgress({ done: 0, total: selectedCandidateIds.length, created: 0, packDone: 0, packTotal: 0 })
        const compositeSteps = COMPOSITE_TASK_SUBSTEP_LABELS[taskId as CompositeExtractionTaskId]?.map(
          (label: string, i: number) => ({ id: String(i), label, status: 'pending' as const }),
        ) ?? []
        setSubsteps(compositeSteps)

        const r = await runCompositeExtractionTask(taskId as CompositeExtractionTaskId,
          { provider, modelName, dryRun, selectedCandidateIds, debugSinglePack, scope },
          { onSubstepStart: ()=>{}, onSubstepComplete: ()=>{},
            onProgress: (steps, meta) => {
              if (cancelledRef.current) return
              setSubsteps([...steps])
              if (meta?.workflowRunId) setWorkflowRunId(meta.workflowRunId)
              const totalCreated = steps.reduce((sum, s) => sum + (s.createdCount ?? 0), 0)
              const doneSteps = steps.filter(s => s.status !== 'pending' && s.status !== 'running').length
              // Extract pack progress from connection step's execution summary
              const connStep = steps.find(s => s.id === 'connection')
              const es = connStep?.executionSummary as Record<string, unknown> | undefined
              const packTotal = Number(es?.pack_count ?? 0)
              const packDone = Number(es?.executed_pack_count ?? es?.processed_pack_count ?? 0)
              setBatchProgress({ done: doneSteps, total: steps.length || 1, created: totalCreated, packDone, packTotal })
            } },
          signal)
        setResult(r); setSubsteps(r.substeps)
        const finalCreated = r.substeps.reduce((sum, s) => sum + (s.createdCount ?? 0), 0)
        setBatchProgress({ done: selectedCandidateIds.length, total: selectedCandidateIds.length, created: finalCreated, packDone: 0, packTotal: 0 })
      } else {
        // ── Single-step: batch processing ─────────────────────────────────
        const scopeParam = (scope.batch_id || scope.resource_id) ? {
          ...(scope.batch_id ? { batch_id: scope.batch_id } : {}),
          ...(scope.resource_id ? { resource_id: scope.resource_id } : {}),
          ...(scope.source_atlas ? { source_atlas: scope.source_atlas } : {}),
          ...(scope.granularity_level ? { granularity_level: scope.granularity_level } : {}),
        } : undefined

        const allIds = selectedCandidateIds
        const batches: string[][] = []
        for (let i = 0; i < allIds.length; i += BATCH_SIZE) batches.push(allIds.slice(i, i + BATCH_SIZE))

        setBatchProgress({ done: 0, total: allIds.length, created: 0, packDone: 0, packTotal: 0 })
        const runningSteps: CompositeSubstepResult[] = batches.map((batchIds, i) => ({
          id: `batch-${i}`, label: `批次 ${i + 1}/${batches.length}（脑区 ${i * BATCH_SIZE + 1}-${Math.min((i + 1) * BATCH_SIZE, allIds.length)}）`, status: 'pending' as const,
        }))
        runningSteps[0].status = 'running'
        setSubsteps(runningSteps)

        let totalCreated = 0
        let lastRunId: string | undefined

        for (let bi = 0; bi < batches.length; bi++) {
          if (cancelledRef.current) break
          const batchIds = batches[bi]
          const batchMaxTokens = maxTokens !== 4096 ? Math.min(maxTokens, 8192) : Math.min(8192, Math.max(4096, batchIds.length * 120))
          const bp = { ...commonParams, max_tokens: batchMaxTokens, candidate_ids: batchIds }

          let res: any = null
          let batchCreated = 0
          switch (taskId as SingleStepTaskId) {
            case 'same_granularity_function_completion':
              res = await runSameGranularityFunctionExtraction({ ...bp, scope: scopeParam, max_functions_per_region: taskParamValues.max_functions_per_region, create_mirror_records: !dryRun && createMirror, create_triples: !dryRun && createTriples, create_evidence: !dryRun && createEvidence } as any)
              batchCreated = (res?.function_count ?? res?.mirror_function_created_count ?? 0)
              break
            case 'same_granularity_connection_completion':
              res = await runSameGranularityConnectionExtraction({ ...bp, scope: scopeParam, max_candidate_pairs: taskParamValues.max_candidate_pairs, create_mirror_records: !dryRun && createMirror, create_triples: !dryRun && createTriples, create_evidence: !dryRun && createEvidence } as any)
              batchCreated = (res?.connection_count ?? res?.mirror_connection_created_count ?? 0)
              break
            case 'same_granularity_circuit_completion':
              res = await runSameGranularityCircuitExtraction({ ...bp, scope: scopeParam, max_circuits: taskParamValues.max_circuits, create_mirror_records: !dryRun && createMirror, create_triples: !dryRun && createTriples, create_evidence: !dryRun && createEvidence } as any)
              batchCreated = (res?.circuit_count ?? res?.mirror_circuit_created_count ?? 0)
              break
            case 'region_field_completion':
              res = await runRegionFieldCompletion({ ...bp, candidate_ids: batchIds } as any)
              batchCreated = (res?.succeeded ?? 0)
              break
          }

          totalCreated += batchCreated
          if (res?.run_id) lastRunId = res.run_id

          const doneRegions = Math.min((bi + 1) * BATCH_SIZE, allIds.length)
          setBatchProgress({ done: doneRegions, total: allIds.length, created: totalCreated, packDone: 0, packTotal: 0 })
          // Update this batch's status and counts
          runningSteps[bi] = {
            ...runningSteps[bi],
            status: 'succeeded' as const,
            createdCount: batchCreated,
          }
          // Mark next batch as running
          if (bi + 1 < batches.length) {
            runningSteps[bi + 1] = { ...runningSteps[bi + 1], status: 'running' as const }
          }
          setSubsteps([...runningSteps])
        }

        if (lastRunId) setWorkflowRunId(lastRunId)
      }
    } catch (e) {
      setError(e instanceof ApiError ? e.message : String(e))
      setSubsteps(s => s.map(st => ({ ...st, status: 'failed' as const })))
    } finally {
      if (timerRef.current) clearInterval(timerRef.current)
      setElapsedMs(Date.now() - startTime)
      setPhase('complete')
    }
  }, [taskId, isComposite, provider, modelName, dryRun, temperature, maxTokens, taskParamValues, createMirror, createTriples, createEvidence, promptTemplateKey, systemPrompt, selectedCandidateIds, scope, debugSinglePack, taskLabel])

  const handleCancel = useCallback(async () => {
    cancelledRef.current = true
    if (timerRef.current) clearInterval(timerRef.current)
    // Abort the polling signal so runCompositeExtractionTask stops cleanly
    try { abortRef.current?.abort() } catch (_) { /* ignore */ }
    // Call backend cancel API so the server stops processing
    if (workflowRunId) {
      try {
        await cancelCompositeWorkflow(workflowRunId, { cleanup: true, reason: 'user_cancelled' })
      } catch (_) {
        // Ignore cancel errors — the modal is closing anyway
      }
    }
    onClose()
  }, [onClose, workflowRunId])

  // ── Pause / Resume for ExtractionRunModal ──────────────────────────────
  const [pausing, setPausing] = useState(false)
  const [resuming, setResuming] = useState(false)
  const pauseInFlightRef = useRef(false)

  const handlePause = useCallback(async () => {
    if (!workflowRunId || pauseInFlightRef.current) return
    pauseInFlightRef.current = true
    setPausing(true)
    try {
      await pauseCompositeWorkflow(workflowRunId)
    } catch (err: any) {
      setError(err?.message || String(err))
    } finally {
      pauseInFlightRef.current = false
      setPausing(false)
    }
  }, [workflowRunId])

  const handleResume = useCallback(async () => {
    if (!workflowRunId) return
    setResuming(true)
    try {
      await resumeCompositeWorkflow(workflowRunId)
    } catch (err: any) {
      setError(err?.message || String(err))
    } finally {
      setResuming(false)
    }
  }, [workflowRunId])

  // ── Render helpers ─────────────────────────────────────────────────────
  const renderSlider = (key: string, label: string, value: number, min: number, max: number, step = 0.1) => (
    <div key={key} style={{ marginBottom: 12 }}>
      <div style={{ display: 'flex', justifyContent: 'space-between', fontSize: 14, marginBottom: 4 }}>
        <span>{label}</span>
        <span style={{ color: 'var(--primary)', fontWeight: 600 }}>{step < 1 ? value.toFixed(1) : value}</span>
      </div>
      <input type="range" min={min} max={max} step={step} value={value}
        onChange={e => { const v = step < 1 ? parseFloat(e.target.value) : parseInt(e.target.value)
          if (key === 'temperature') setTemperature(v); else if (key === 'max_tokens') setMaxTokens(v)
          else setTaskParamValues(p => ({ ...p, [key]: v })) }} style={{ width: '100%' }} />
    </div>
  )

  const MODAL_W = 700

  // ── Confirm ────────────────────────────────────────────────────────────
  if (phase === 'confirm') {
    const pairCount = selectedCandidateIds.length >= 2 ? selectedCandidateIds.length * (selectedCandidateIds.length - 1) / 2 : 0
    const batchCount = isComposite ? 1 : Math.ceil(selectedCandidateIds.length / BATCH_SIZE)
    return (
      <div className="modal-overlay" onClick={onClose}>
        <div className="modal-panel" style={{ maxWidth: MODAL_W }} onClick={e => e.stopPropagation()}>
          <div className="modal-header"><h3 style={{ margin: 0, fontSize: 17 }}>{taskLabel}</h3><button className="btn-close" onClick={onClose}>✕</button></div>
          <div className="tabs" style={{ margin: 0, padding: '0 20px' }}>
            <button className={`tab-btn${confirmTab==='params'?' active':''}`} onClick={()=>setConfirmTab('params')} style={{ fontSize: 14 }}>参数</button>
            <button className={`tab-btn${confirmTab==='prompt'?' active':''}`} onClick={()=>setConfirmTab('prompt')} style={{ fontSize: 14 }}>提示词</button>
          </div>
          <div style={{ padding: '14px 20px', fontSize: 15, maxHeight: '55vh', overflowY: 'auto' }}>
            <div style={{ marginBottom: 12, fontSize: 13, color: '#888' }}>
              {provider} / {modelName} · {selectedCandidateIds.length} 候选{batchCount > 1 ? ` · ${batchCount} 批次 (每批${BATCH_SIZE}个)` : ''}{pairCount > 0 ? ` · ${pairCount} pairs` : ''}
            </div>
            {confirmTab === 'params' && (<>
              <div style={{ fontWeight: 600, marginBottom: 10, fontSize: 15 }}>通用参数</div>
              {renderSlider('temperature', 'Temperature', temperature, 0, 2, 0.1)}
              {renderSlider('max_tokens', 'Max Tokens', maxTokens, 256, 8192, 256)}
              {taskDef.taskParams && taskDef.taskParams.length > 0 && (<>
                <div style={{ fontWeight: 600, marginBottom: 10, marginTop: 16, fontSize: 15 }}>任务参数</div>
                {taskDef.taskParams.map(p => renderSlider(p.key, p.label, taskParamValues[p.key] ?? p.default, p.min, p.max, 1))}
              </>)}
              <div style={{ fontWeight: 600, marginBottom: 8, marginTop: 16, fontSize: 15 }}>写入选项</div>
              {[{k:'createMirror',v:createMirror,s:setCreateMirror,l:'create_mirror_records'},{k:'createTriples',v:createTriples,s:setCreateTriples,l:'create_triples'},{k:'createEvidence',v:createEvidence,s:setCreateEvidence,l:'create_evidence'}].map(o=>(
                <label key={o.k} style={{ display: 'block', fontSize: 14, marginBottom: 4, cursor: 'pointer' }}>
                  <input type="checkbox" checked={o.v} onChange={e=>o.s(e.target.checked)} style={{ marginRight: 6 }} />{o.l}
                </label>
              ))}
            </>)}
            {confirmTab === 'prompt' && (<>
              {isComposite ? (
                /* Composite: show each substep with its default template */
                <div>
                  <div style={{ fontSize: 13, color: '#888', marginBottom: 10 }}>
                    复合任务各步骤使用各自的后端默认提示词模板：
                  </div>
                  {(COMPOSITE_TASK_SUBSTEP_LABELS[taskId as CompositeExtractionTaskId] ?? []).map((label: string, i: number) => (
                    <div key={i} style={{ marginBottom: 8, padding: '8px 10px', background: '#fafafa', borderRadius: 4, border: '1px solid #f0f0f0' }}>
                      <div style={{ fontWeight: 600, fontSize: 13, marginBottom: 2 }}>步骤 {i + 1}: {label}</div>
                      <div style={{ fontSize: 11, color: '#888' }}>模板: {['same_granularity_circuit_completion_v1', 'circuit_steps_extraction_v1', 'circuit_to_functions_extraction_v1'][i] ?? 'default'}</div>
                    </div>
                  ))}
                  <div style={{ marginTop: 10 }}>
                    <div style={{ fontWeight: 600, marginBottom: 6, fontSize: 14 }}>自定义 System Prompt（覆盖所有步骤）</div>
                    <textarea className="modal-prompt-textarea" rows={6} value={systemPrompt} onChange={e=>setSystemPrompt(e.target.value)} placeholder="为空则各步骤使用各自后端默认" style={{ fontSize: 13 }} />
                  </div>
                </div>
              ) : (
                /* Single-step: template selector + editable prompts */
                <>
                  <div style={{ display: 'flex', alignItems: 'center', gap: 10, marginBottom: 12 }}>
                    <span style={{ fontSize: 14, color: '#888' }}>模板:</span>
                    <select className="filter-select" style={{ fontSize: 14, flex: 1 }} value={promptTemplateKey} onChange={e=>setPromptTemplateKey(e.target.value)}>
                      <option value="">使用后端默认</option>
                      {templates.map(tm=><option key={tm.key} value={tm.key}>{tm.display_name ?? tm.title ?? tm.key}</option>)}
                    </select>
                    {promptTemplateKey && <button className="btn" style={{ fontSize: 13 }} onClick={()=>{setPromptTemplateKey('');setSystemPrompt('');setUserPrompt('')}}>恢复默认</button>}
                  </div>
                  <div style={{ fontWeight: 600, marginBottom: 6, fontSize: 14 }}>System Prompt</div>
                  <textarea className="modal-prompt-textarea" rows={8} value={systemPrompt} onChange={e=>setSystemPrompt(e.target.value)} placeholder="为空则使用后端默认" style={{ fontSize: 13 }} />
                  <div style={{ fontWeight: 600, marginBottom: 6, marginTop: 12, fontSize: 14 }}>User Prompt（可选）</div>
                  <textarea className="modal-prompt-textarea" rows={5} value={userPrompt} onChange={e=>setUserPrompt(e.target.value)} placeholder="为空则使用后端默认" style={{ fontSize: 13 }} />
                </>
              )}
            </>)}
            <div style={{ marginTop: 14 }}>
              <label style={{ display: 'flex', alignItems: 'center', gap: 8, fontSize: 14, cursor: 'pointer', marginBottom: 10 }}>
                <input type="checkbox" checked={dryRun} onChange={e=>setDryRun(e.target.checked)} />Dry Run（预览不写入）
              </label>
              <div style={{ fontSize: 13, color: '#fa8c16', padding: '8px 12px', background: '#fff7e6', borderRadius: 4 }}>⚠ 只写 mirror_*，不写 final_* / kg_*</div>
            </div>
          </div>
          <div className="modal-footer">
            <button className="btn" onClick={onClose} style={{ fontSize: 14 }}>取消</button>
            <button className="btn btn-primary" onClick={startExecution} style={{ fontSize: 14 }}>确认执行</button>
          </div>
        </div>
      </div>
    )
  }

  // ── Running ────────────────────────────────────────────────────────────
  if (phase === 'running') {
    const pct = batchProgress.total > 0 ? Math.round((batchProgress.done / batchProgress.total) * 100) : undefined
    const packPct = batchProgress.packTotal > 0 ? Math.round((batchProgress.packDone / batchProgress.packTotal) * 100) : undefined
    const progressLabel = isComposite
      ? `步骤 ${batchProgress.done}/${batchProgress.total} · 已生成 ${batchProgress.created}`
      : `已完成 ${batchProgress.done}/${batchProgress.total} · 已生成 ${batchProgress.created}`
    return (
      <div className="modal-overlay">
        <div className="modal-panel" style={{ maxWidth: MODAL_W }}>
          <div className="modal-header"><h3 style={{ margin: 0, fontSize: 17 }}>{taskLabel}</h3><span style={{ fontSize: 14, color: '#888' }}>执行中…</span></div>
          <div style={{ padding: '18px 22px', fontSize: 15 }}>
            <div style={{ marginBottom: 16, fontSize: 14, color: '#888' }}>
              ⏱ {formatElapsed(elapsedMs)}{workflowRunId ? <span style={{ marginLeft: 12, fontSize: 12 }}>Run: <code>{workflowRunId.slice(0,8)}…</code></span> : null}
            </div>
            {/* Progress bar */}
            {pct != null ? (
              <div style={{ marginBottom: 16 }}>
                <div style={{ display: 'flex', justifyContent: 'space-between', fontSize: 14, marginBottom: 6 }}>
                  <span>{progressLabel}</span>
                  <span style={{ color: 'var(--primary)', fontWeight: 600 }}>{pct}%</span>
                </div>
                <div style={{ height: 10, background: '#e8e8e8', borderRadius: 5, overflow: 'hidden' }}>
                  <div style={{ height: '100%', width: `${pct}%`, background: 'var(--primary)', borderRadius: 5, transition: 'width 0.3s' }} />
                </div>
                {batchProgress.created > 0 && (
                  <div style={{ fontSize: 14, marginTop: 6, color: '#389e0d' }}>已生成 {batchProgress.created} 条数据</div>
                )}
              </div>
            ) : (
              <div style={{ marginBottom: 16 }}>
                <div style={{ height: 10, background: '#e8e8e8', borderRadius: 5, overflow: 'hidden' }}>
                  <div style={{ height: '100%', width: '100%', borderRadius: 5,
                    background: 'linear-gradient(90deg, var(--primary) 0%, #69b1ff 50%, var(--primary) 100%)',
                    backgroundSize: '200% 100%', animation: 'modal-progress-pulse 1.5s infinite' }} />
                </div>
              </div>
            )}
            {/* Pack progress (composite connection extraction) */}
            {batchProgress.packTotal > 0 && (
              <div style={{ marginBottom: 14 }}>
                <div style={{ display: 'flex', justifyContent: 'space-between', fontSize: 13, marginBottom: 4 }}>
                  <span style={{ color: '#888' }}>包进度</span>
                  <span style={{ color: 'var(--primary)', fontWeight: 600 }}>
                    {batchProgress.packDone}/{batchProgress.packTotal}
                    {packPct != null ? ` (${packPct}%)` : ''}
                  </span>
                </div>
                <div style={{ height: 6, background: '#e8e8e8', borderRadius: 3, overflow: 'hidden' }}>
                  <div style={{ height: '100%', width: `${packPct ?? 0}%`, background: '#1890ff', borderRadius: 3, transition: 'width 0.3s' }} />
                </div>
              </div>
            )}
            {/* Substep list */}
            {substeps.length === 0 && <div style={{ color: '#888', fontSize: 15, padding: '16px 0' }}>正在启动…</div>}
            {substeps.map(step => (
              <div key={step.id} style={{ display: 'flex', alignItems: 'center', gap: 12, padding: '10px 0', borderBottom: '1px solid #f0f0f0', opacity: step.status==='pending'?0.5:1, fontSize: 15 }}>
                {step.status==='running'&&<span style={{color:'#1890ff',fontSize:18}}>⏳</span>}
                {step.status==='succeeded'&&<span style={{color:'#389e0d',fontSize:18}}>✅</span>}
                {step.status==='failed'&&<span style={{color:'#cf1322',fontSize:18}}>❌</span>}
                {!['running','succeeded','failed'].includes(step.status)&&<span style={{color:'#d9d9d9',fontSize:18}}>○</span>}
                <span style={{ flex: 1 }}>{step.label}</span>
                {step.createdCount != null && step.createdCount > 0 && <span style={{ fontSize: 15, color: '#389e0d', fontWeight: 500 }}>+{step.createdCount}</span>}
              </div>
            ))}
            {error && <div style={{ marginTop: 14, padding: '10px 14px', background: '#fff2f0', borderRadius: 4, fontSize: 14, color: '#cf1322' }}>{error}</div>}
          </div>
          <div className="modal-footer">
            <button className="btn" onClick={handlePause} disabled={pausing} style={{ fontSize: 14 }}>
              {pausing ? '⏳ 暂停中...' : '⏸ 暂停'}
            </button>
            <button className="btn" onClick={handleResume} disabled={resuming} style={{ fontSize: 14 }}>
              {resuming ? '⏳ 继续中...' : '▶ 继续'}
            </button>
            <button className="btn" onClick={handleCancel} style={{ color: '#cf1322', fontSize: 14 }}>取消执行</button>
          </div>
        </div>
      </div>
    )
  }

  // ── Complete ───────────────────────────────────────────────────────────
  const isSuccess = !error
  return (
    <div className="modal-overlay" onClick={onClose}>
      <div className="modal-panel" style={{ maxWidth: MODAL_W }} onClick={e => e.stopPropagation()}>
        <div className="modal-header"><h3 style={{ margin: 0, fontSize: 17 }}>{isSuccess?'✅':'❌'} {taskLabel}</h3><button className="btn-close" onClick={onClose}>✕</button></div>
        <div style={{ padding: '18px 22px', fontSize: 15 }}>
          <div style={{ marginBottom: 10, fontSize: 17, fontWeight: 600 }}>{error ? '执行失败' : overallStatusLabel(result?.status ?? 'succeeded')}</div>
          <div style={{ fontSize: 14, color: '#888', marginBottom: 18 }}>用时 {formatElapsed(elapsedMs)}{workflowRunId ? <span style={{ marginLeft: 12 }}>Run: <code style={{ fontSize: 12 }}>{workflowRunId.slice(0,12)}…</code></span> : null}</div>
          {error && <div style={{ marginBottom: 18, padding: '12px 16px', background: '#fff2f0', borderRadius: 4, fontSize: 15, color: '#cf1322' }}>{error}</div>}
          {substeps.length > 0 && (
            <div style={{ marginBottom: 18 }}>
              {substeps.map(step => (
                <div key={step.id} style={{ display: 'flex', alignItems: 'center', gap: 12, padding: '10px 0', borderBottom: '1px solid #f0f0f0', fontSize: 15 }}>
                  {step.status==='succeeded'&&<span style={{color:'#389e0d',fontSize:18}}>✅</span>}
                  {step.status==='failed'&&<span style={{color:'#cf1322',fontSize:18}}>❌</span>}
                  {!['succeeded','failed'].includes(step.status)&&<span style={{color:'#d9d9d9',fontSize:18}}>○</span>}
                  <span style={{ flex: 1 }}>{step.label}</span>
                  {step.createdCount != null && <span style={{ fontSize: 16, color: '#389e0d', fontWeight: 600 }}>{step.createdCount} 条</span>}
                </div>
              ))}
            </div>
          )}
          {batchProgress.created > 0 && <div style={{ fontSize: 17, fontWeight: 600, color: '#389e0d', marginBottom: 18 }}>共生成 {batchProgress.created} 条数据</div>}
          {result?.warnings && result.warnings.length > 0 && (
            <details style={{ marginBottom: 14, fontSize: 14 }}><summary style={{ cursor: 'pointer', color: '#d48806' }}>⚠ {result.warnings.length} 条警告</summary>
              <div style={{ marginTop: 6, maxHeight: 140, overflow: 'auto' }}>{result.warnings.map((w,i)=><div key={i} style={{ color: '#888', padding: '2px 0' }}>{w}</div>)}</div></details>
          )}
          {dryRun && <div style={{ fontSize: 13, color: '#fa8c16', padding: '10px 14px', background: '#fff7e6', borderRadius: 4, marginBottom: 14 }}>🔍 Dry Run — 未写入数据库</div>}
        </div>
        <div className="modal-footer">
          <button className="btn" onClick={onClose} style={{ fontSize: 14 }}>关闭</button>
          {isSuccess && !dryRun && (<>
            <button className="btn btn-primary" onClick={onViewMirror} style={{ fontSize: 14 }}>查看 Mirror 数据</button>
            <button className="btn" onClick={onViewItems} style={{ fontSize: 14 }}>查看提取条目</button>
          </>)}
        </div>
      </div>
    </div>
  )
}
