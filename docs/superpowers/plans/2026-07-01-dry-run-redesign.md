# Dry Run Redesign: From Skip-Checkbox to Preview Mode

> **For agentic workers:** Use superpowers:subagent-driven-development.

**Goal:** Replace passive dry run checkbox with active preview mode showing pack plan, token estimates, cost, and optional 1-pack LLM sample.

**Architecture:** Backend adds token estimation to dry run + optional sample pack execution. Frontend deletes 5 scattered checkboxes from LlmExtractionPage, replaces PoolExtractionModal checkbox with mode selector + sample toggle.

**Tech Stack:** FastAPI + React 18 + TypeScript

## Global Constraints

- Build: `cd frontend && npm run build` must pass with 0 TypeScript errors
- Tests: `cd backend && .venv/Scripts/python.exe -m pytest tests/ -q --ignore=tests/test_llm_field_completion.py` must pass
- No new dependencies
- DeepSeek pricing: ¥1/1M input, ¥2/1M output

---

### Task 1: Backend — token estimation in dry run + sample pack

**Files:**
- `backend/app/schemas/llm_composite_workflow.py` — add `dry_run_sample_pack: bool = False`
- `backend/app/services/llm_composite_workflow_service.py` — enhance dry run flow
- `backend/app/services/llm_connection_extraction_service.py` — token estimation for dry run

In `llm_composite_workflow_service.py`, find the connection extraction step handler (`_run_connection_extraction_step` or similar). When `dry_run=True` and the connection service returns with prompts + pack info:

1. Calculate `estimated_input_tokens` by running `estimate_prompt_tokens(system_prompt + user_prompt)` for each pack
2. Calculate `estimated_output_tokens = pair_count * 48` (50 tokens per pair is the existing heuristic)
3. Populate these in the step's `execution_summary`

When `dry_run_sample_pack=True`:
4. After building packs, take ONLY the first pack, call the LLM provider with real API
5. Parse the response using `parse_connection_completion_response()` + `normalize_connection_extraction_payload()`
6. Return the parsed sample (first 3 projections) in `result_summary.dry_run_sample`

In `llm_connection_extraction_service.py`, the dry run early-return at line ~871 already has `system_prompt` and `user_prompt`. Add token estimation:
```python
if dry_run:
    from app.services.field_completion_prompt_engineering import estimate_prompt_tokens
    est_input = sum(estimate_prompt_tokens(system_prompt) + estimate_prompt_tokens(prompt) for prompt in all_prompts)
    est_output = len(pairs) * 48
    result.estimated_input_tokens = est_input
    result.estimated_output_tokens = est_output
    result.system_prompt = system_prompt
    result.user_prompt = user_prompt
    result.unprocessed_pair_count = len(pairs)
    return result
```

### Task 2: Frontend — delete 5 dry run checkboxes from LlmExtractionPage.tsx

**File:** `frontend/src/pages/LlmExtractionPage.tsx`

Delete these 5 dry run blocks (each is ~10-15 lines):

1. Lines ~239-376: `CircuitStepsExtractionWorkbench` — delete `const [dryRun, setDryRun] = useState(false)`, the checkbox, and the `!dryRun && !currentProvider?.configured` guard (change to just `!currentProvider?.configured`)
2. Lines ~449-621: `ProjectionExtractionWorkbench` — same pattern
3. Lines ~687-891: `ProjectionFunctionExtractionWorkbench` — same pattern
4. Lines ~994-1178: `ProjectionToCircuitWorkbench` — same pattern
5. Lines ~1240-1295: `MirrorValidationWorkbench` — delete dryRun state and checkbox

For each: remove `const [dryRun, setDryRun]`, remove the checkbox `<label>`/`<input>`, remove `dry_run: previewOnly` from API calls, change `(!dryRun && !currentProvider?.configured)` → `!currentProvider?.configured`.

### Task 3: Frontend — replace dry run checkbox with mode selector in PoolExtractionModal Step 2

**File:** `frontend/src/pages/llm-extraction/components/PoolExtractionModal.tsx`

Replace the current dry run checkbox (lines ~1363-1370) with:

```tsx
          {/* Extraction mode */}
          <div className="modal-section" style={{ marginTop: 12 }}>
            <p className="modal-section-title">提取模式</p>
            <div style={{ display: 'flex', gap: 16 }}>
              <label style={{ display: 'flex', alignItems: 'center', gap: 6, cursor: 'pointer', fontSize: 14 }}>
                <input type="radio" name="extractMode" checked={!dryRun} onChange={() => setDryRun(false)} />
                正式提取
              </label>
              <label style={{ display: 'flex', alignItems: 'center', gap: 6, cursor: 'pointer', fontSize: 14 }}>
                <input type="radio" name="extractMode" checked={dryRun} onChange={() => setDryRun(true)} />
                Dry Run 预览
              </label>
            </div>
            {dryRun && (
              <div style={{ marginTop: 8, padding: '8px 12px', background: '#f0f7ff', borderRadius: 6, fontSize: 12, color: '#555' }}>
                <div>📊 构建所有 packs，估算 token 用量和费用</div>
                <div>🚫 不调用 LLM（除非勾选样本包），不写入数据库</div>
                <label style={{ display: 'flex', alignItems: 'center', gap: 6, marginTop: 6, cursor: 'pointer' }}>
                  <input
                    type="checkbox"
                    checked={dryRunSamplePack}
                    onChange={e => setDryRunSamplePack(e.target.checked)}
                  />
                  <span>运行 1 个样本包（调用真实 LLM 查看输出样例）</span>
                </label>
              </div>
            )}
          </div>
```

Add state: `const [dryRunSamplePack, setDryRunSamplePack] = useState(false)` near the existing `dryRun` state.

Pass `dry_run_sample_pack: dryRun && dryRunSamplePack` to the API payload.

### Task 4: Frontend — show dry run results in PoolExtractionModal

**File:** `frontend/src/pages/llm-extraction/components/PoolExtractionModal.tsx`

In the result screen (`renderResult`), when status is `dry_run`, show enhanced dry run summary:

```tsx
{progress.workflowStatus === 'dry_run' && (
  <div className="modal-section">
    <p className="modal-section-title">Dry Run 预览结果</p>
    <div className="modal-section-row">
      <span className="label">计划包数</span>
      <span className="value">{progress.totalPacks} 包</span>
    </div>
    <div className="modal-section-row">
      <span className="label">预估输入 tokens</span>
      <span className="value">{progress.estimatedInputTokens.toLocaleString()}</span>
    </div>
    <div className="modal-section-row">
      <span className="label">预估输出 tokens</span>
      <span className="value">{progress.estimatedOutputTokens.toLocaleString()}</span>
    </div>
    <div className="modal-section-row">
      <span className="label">预估费用</span>
      <span className="value" style={{ fontWeight: 600, color: '#2563eb' }}>
        {estimateCost(progress.estimatedInputTokens, progress.estimatedOutputTokens)}
      </span>
    </div>
    {progress.connectionsFound > 0 && (
      <div style={{ marginTop: 8, padding: '8px 12px', background: '#f6ffed', borderRadius: 6, fontSize: 12 }}>
        样本包解析到 {progress.connectionsFound} 条连接（仅预览，未写入）
      </div>
    )}
  </div>
)}
```

### Task 5: Add dryRunSamplePack to ProgressData + API types + reset

- Add `dryRunSamplePack` field to ProgressData interface
- Pass `dry_run_sample_pack` through endpoints.ts
- Reset `dryRunSamplePack` on close

### Task 6: Verify

```bash
cd backend && .venv/Scripts/python.exe -m pytest tests/ -q --ignore=tests/test_llm_field_completion.py
cd frontend && npm run build
```
