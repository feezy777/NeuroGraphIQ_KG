# PoolExtractionModal Step 2 提示词工程配置 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 在快速卡片弹窗（PoolExtractionModal）第二步添加 Temperature/MaxTokens 滑条 + 可折叠提示词预览/编辑区，并将参数传入 API 调用。

**Architecture:** 纯前端改动，后端 schema 已完成前置修改。`PoolExtractionModal.tsx` 单文件新增约 100 行（state + UI + API 传参）。

**Tech Stack:** React 18 + TypeScript, Vite build

## Global Constraints

- 不引入新依赖
- 遵守现有 css class 命名（modal-section, modal-section-title, modal-section-row）
- API 类型定义在 `frontend/src/api/endpoints.ts`，不新增 API 端点
- 构建必须通过 `npm run build` 且 0 TypeScript 错误

---

### Task 1: 添加 state + workflowType→template key 映射

**Files:**
- Modify: `frontend/src/pages/llm-extraction/components/PoolExtractionModal.tsx`

**Interfaces:**
- Produces: `temperature` (float state, default 0.7), `maxTokens` (int state, default 4096), `showPromptPreview` (bool), `editingPrompt` (bool), `customSystemPrompt` (string), `customUserPrompt` (string), `promptTemplates` (ExtractionPromptTemplate[]), `primaryTemplateKey` (derived from workflowType)

- [ ] **Step 1: 在 imports 区添加 `getExtractionPromptTemplates` 和 `ExtractionPromptTemplate` 类型**

在 line 3 的 import block 追加两行：
```typescript
import {
  // ... existing imports ...
  getExtractionPromptTemplates,
  type ExtractionPromptTemplate,
} from '../../../api/endpoints'
```

- [ ] **Step 2: 在 state 区添加新状态变量（line ~217 之后，`localPoolId` 之后）**

```typescript
  // ── Prompt engineering ──────────────────────────────────────────────────────
  const [temperature, setTemperature] = useState(0.7)
  const [maxTokens, setMaxTokens] = useState(4096)
  const [showPromptPreview, setShowPromptPreview] = useState(false)
  const [editingPrompt, setEditingPrompt] = useState(false)
  const [customSystemPrompt, setCustomSystemPrompt] = useState('')
  const [customUserPrompt, setCustomUserPrompt] = useState('')
  const [promptTemplates, setPromptTemplates] = useState<ExtractionPromptTemplate[]>([])
```

- [ ] **Step 3: 添加 workflowType→template key 映射函数和模板加载 effect**

在 state 区之后（line ~225 之前），添加常量映射和 effect：

```typescript
  // ── Prompt template key mapping ─────────────────────────────────────────────
  const WORKFLOW_PRIMARY_TEMPLATE: Record<string, string> = {
    connection_with_function: 'same_granularity_connection_completion_v1',
    circuit_with_function_steps: 'same_granularity_circuit_completion_v1',
    same_granularity_function_completion: 'same_granularity_function_completion_v1',
  }

  const primaryTemplateKey = WORKFLOW_PRIMARY_TEMPLATE[workflowType] ?? ''

  // Load prompt templates on open
  useEffect(() => {
    if (!open || promptTemplates.length > 0) return
    getExtractionPromptTemplates('extraction')
      .then(res => setPromptTemplates(res.items ?? []))
      .catch(err => console.error('[PoolExtractionModal] Failed to load templates:', err))
  }, [open, promptTemplates.length])

  // When primaryTemplateKey changes, populate custom prompts from fetched template
  const primaryTemplate = useMemo(
    () => promptTemplates.find(t => t.key === primaryTemplateKey),
    [promptTemplates, primaryTemplateKey],
  )

  useEffect(() => {
    if (primaryTemplate) {
      setCustomSystemPrompt(primaryTemplate.system_prompt)
      setCustomUserPrompt(primaryTemplate.template)
    }
  }, [primaryTemplate?.key])  // reset only when template key changes
```

- [ ] **Step 4: 验证 TypeScript 编译**

Run: `cd frontend && npm run build 2>&1 | tail -5`
Expected: `✓ built in ...s`, 0 errors

---

### Task 2: 在 renderStep2 添加高级参数 + 提示词预览 UI

**Files:**
- Modify: `frontend/src/pages/llm-extraction/components/PoolExtractionModal.tsx` (renderStep2 函数)

**Interfaces:**
- Consumes: `temperature`, `maxTokens`, `showPromptPreview`, `editingPrompt`, `customSystemPrompt`, `customUserPrompt`, `primaryTemplate`, `primaryTemplateKey` (from Task 1)
- Produces: UI markup in step 2 body

- [ ] **Step 1: 在 ModelSelector 下方、Dry run 下方，添加高级参数区**

找到 `renderStep2` 中 `<label style={{...}}>Dry run...</label>` 之后、`</div>` (model-section 闭合) 之前，插入：

```tsx
          {/* Advanced params */}
          <div className="modal-section" style={{ marginTop: 12 }}>
            <p className="modal-section-title">高级参数</p>

            {/* Temperature */}
            <div style={{ marginBottom: 12 }}>
              <div style={{ display: 'flex', justifyContent: 'space-between', fontSize: 13, marginBottom: 4 }}>
                <span className="label">Temperature</span>
                <span style={{ color: '#2563eb', fontWeight: 600 }}>{temperature.toFixed(1)}</span>
              </div>
              <input
                type="range"
                min={0}
                max={2}
                step={0.1}
                value={temperature}
                onChange={e => setTemperature(parseFloat(e.target.value))}
                style={{ width: '100%' }}
              />
            </div>

            {/* Max Tokens */}
            <div style={{ marginBottom: 4 }}>
              <div style={{ display: 'flex', justifyContent: 'space-between', fontSize: 13, marginBottom: 4 }}>
                <span className="label">Max Tokens</span>
                <span style={{ color: '#2563eb', fontWeight: 600 }}>{maxTokens}</span>
              </div>
              <input
                type="range"
                min={256}
                max={8192}
                step={256}
                value={maxTokens}
                onChange={e => setMaxTokens(parseInt(e.target.value))}
                style={{ width: '100%' }}
              />
            </div>
          </div>
```

- [ ] **Step 2: 添加可折叠提示词预览区**

在上述高级参数区之后（仍在 `padding: '0 20px', flex: 1, ...` 的 div 内），添加：

```tsx
          {/* Prompt template preview */}
          <div className="modal-section" style={{ flex: 1, display: 'flex', flexDirection: 'column', minHeight: 0 }}>
            <p
              className="modal-section-title"
              style={{ cursor: 'pointer', userSelect: 'none', display: 'flex', justifyContent: 'space-between', alignItems: 'center' }}
              onClick={() => setShowPromptPreview(!showPromptPreview)}
            >
              <span>提示词模板 {showPromptPreview ? '▾' : '▸'}</span>
              {primaryTemplate && <span style={{ fontWeight: 400, fontSize: 12, color: '#888' }}>{primaryTemplate.key}</span>}
            </p>
            {showPromptPreview && primaryTemplate ? (
              <div style={{ display: 'flex', flexDirection: 'column', gap: 8, flex: 1, minHeight: 0 }}>
                {/* Template info */}
                <div style={{ fontSize: 12, color: '#888' }}>
                  {primaryTemplate.display_name ?? primaryTemplate.title}
                </div>

                {/* System prompt */}
                <div style={{ flex: 1, display: 'flex', flexDirection: 'column', minHeight: 0 }}>
                  <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: 4 }}>
                    <span style={{ fontSize: 12, fontWeight: 600, color: '#555' }}>System Prompt</span>
                    <button
                      type="button"
                      className="llm-btn"
                      style={{ fontSize: 11, padding: '2px 8px' }}
                      onClick={() => {
                        if (editingPrompt) {
                          // Reset to template default
                          setCustomSystemPrompt(primaryTemplate.system_prompt)
                          setCustomUserPrompt(primaryTemplate.template)
                        }
                        setEditingPrompt(!editingPrompt)
                      }}
                    >
                      {editingPrompt ? '恢复默认' : '编辑'}
                    </button>
                  </div>
                  <textarea
                    style={{
                      flex: 1,
                      minHeight: 60,
                      maxHeight: 120,
                      width: '100%',
                      fontSize: 11,
                      fontFamily: 'monospace',
                      border: '1px solid #d0d7e2',
                      borderRadius: 4,
                      padding: '6px 8px',
                      resize: 'vertical',
                      background: editingPrompt ? '#fff' : '#f8f9fa',
                      color: editingPrompt ? '#1a1a2e' : '#666',
                    }}
                    readOnly={!editingPrompt}
                    value={customSystemPrompt}
                    onChange={e => setCustomSystemPrompt(e.target.value)}
                  />
                </div>

                {/* User prompt */}
                <div style={{ flex: 1, display: 'flex', flexDirection: 'column', minHeight: 0 }}>
                  <span style={{ fontSize: 12, fontWeight: 600, color: '#555', marginBottom: 4 }}>User Prompt</span>
                  <textarea
                    style={{
                      flex: 1,
                      minHeight: 60,
                      maxHeight: 120,
                      width: '100%',
                      fontSize: 11,
                      fontFamily: 'monospace',
                      border: '1px solid #d0d7e2',
                      borderRadius: 4,
                      padding: '6px 8px',
                      resize: 'vertical',
                      background: editingPrompt ? '#fff' : '#f8f9fa',
                      color: editingPrompt ? '#1a1a2e' : '#666',
                    }}
                    readOnly={!editingPrompt}
                    value={customUserPrompt}
                    onChange={e => setCustomUserPrompt(e.target.value)}
                  />
                </div>

                {/* Editing warning */}
                {editingPrompt && (
                  <div style={{ padding: '6px 10px', background: '#fff7e6', borderRadius: 4, fontSize: 11, color: '#d48806' }}>
                    ⚠ 输出 JSON schema 由后端固定，修改 prompt 时请保留输出格式要求，否则数据无法解析入库。
                  </div>
                )}

                {/* Composite workflow note */}
                {workflowType === 'connection_with_function' && (
                  <div style={{ fontSize: 11, color: '#888' }}>
                    复合工作流第二步使用 projection_to_functions_v1 模板（后端自动选择）
                  </div>
                )}
                {workflowType === 'circuit_with_function_steps' && (
                  <div style={{ fontSize: 11, color: '#888' }}>
                    复合工作流多步骤分别使用 circuit_to_steps_v1、circuit_to_functions_extraction_v1 模板（后端自动选择）
                  </div>
                )}
              </div>
            ) : showPromptPreview && !primaryTemplate ? (
              <div style={{ fontSize: 12, color: '#999', fontStyle: 'italic' }}>加载中或模板不可用...</div>
            ) : null}
          </div>
```

- [ ] **Step 3: 验证构建**

Run: `cd frontend && npm run build 2>&1 | tail -5`
Expected: `✓ built in ...s`

---

### Task 3: 将 prompt 参数传入 API 调用

**Files:**
- Modify: `frontend/src/pages/llm-extraction/components/PoolExtractionModal.tsx` (handleStartExtraction + handleClose)

**Interfaces:**
- Consumes: `temperature`, `maxTokens`, `customSystemPrompt`, `customUserPrompt`, `primaryTemplate`, `primaryTemplateKey` (from Task 1)
- Modifies: `runSameGranularityFunctionExtraction` and `startCompositeWorkflow` call payloads

- [ ] **Step 1: 在 `handleStartExtraction` 的 function extraction 路径添加参数**

找到 `runSameGranularityFunctionExtraction({` (line ~554)，在 payload 中添加：

```typescript
        const fnResponse = await runSameGranularityFunctionExtraction({
          provider,
          model_name: modelName || undefined,
          candidate_ids: candidateIds,
          scope,
          dry_run: dryRun,
          create_mirror_records: !dryRun,
          create_triples: !dryRun,
          create_evidence: !dryRun,
          temperature: temperature !== 0.7 ? temperature : undefined,
          max_tokens: maxTokens !== 4096 ? maxTokens : undefined,
          prompt_template_key: primaryTemplateKey || undefined,
        })
```

- [ ] **Step 2: 在 `handleStartExtraction` 的 composite workflow 路径添加参数**

找到 `const payload = {` (line ~586)，在 payload 中添加：

```typescript
      const payload = {
        workflow_type: compositeWorkflowType as 'connection_with_function' | 'circuit_with_function_steps' | 'triple_generation',
        provider,
        model_name: modelName || undefined,
        dry_run: dryRun,
        candidate_ids: candidateIds,
        resource_id: scope.resource_id,
        batch_id: scope.batch_id,
        source_atlas: scope.source_atlas,
        granularity_level: scope.granularity_level,
        granularity_family: scope.granularity_family,
        create_mirror_records: !dryRun,
        create_evidence: !dryRun,
        temperature: temperature !== 0.7 ? temperature : undefined,
        max_tokens: maxTokens !== 4096 ? maxTokens : undefined,
        prompt_template_key: primaryTemplateKey || undefined,
        prompt_overrides: editingPrompt && primaryTemplateKey
          ? { [primaryTemplateKey]: customUserPrompt }
          : undefined,
      }
```

- [ ] **Step 3: 在 `handleClose` 重置 prompt 状态**

找到 `handleClose` 中的 `setDryRun(false)` 行，在之后添加：

```typescript
    setTemperature(0.7)
    setMaxTokens(4096)
    setShowPromptPreview(false)
    setEditingPrompt(false)
    setCustomSystemPrompt('')
    setCustomUserPrompt('')
    setPromptTemplates([])
```

- [ ] **Step 4: 验证构建**

Run: `cd frontend && npm run build 2>&1 | tail -5`
Expected: `✓ built in ...s`, 0 TypeScript errors

---

### Task 4: 集成验证 + 提交

- [ ] **Step 1: 完整构建验证**

```bash
cd frontend && npm run build 2>&1 | tail -5
```
Expected: `✓ built in ...s`

- [ ] **Step 2: 后端测试验证（确认 schema 变更不影响已有测试）**

```bash
cd backend && .venv/Scripts/python.exe -m pytest tests/test_llm_composite_workflow.py tests/test_llm_connection_prompt_engineering.py -q 2>&1 | tail -5
```
Expected: all passed

- [ ] **Step 3: 提交**

```bash
git add frontend/src/pages/llm-extraction/components/PoolExtractionModal.tsx
git add frontend/src/api/endpoints.ts
git add backend/app/schemas/llm_composite_workflow.py
git add backend/app/services/prompt_metadata.py
git add backend/app/services/llm_extraction_prompt_engineering.py
git add backend/app/services/field_completion_prompt_engineering.py
git add backend/app/routers/llm_extraction.py
git add backend/app/routers/llm_field_completion.py
git commit -m "feat: add prompt preview + temperature/max_tokens to PoolExtractionModal step 2

- Add collapsible prompt template preview (system + user) with edit toggle
- Add Temperature (0-2, default 0.7) and Max Tokens (256-8192, default 4096) sliders
- Thread temperature/max_tokens/prompt_overrides into composite and function extraction API calls
- Backend: consolidate prompt metadata into prompt_metadata.py, eliminate duplicate display names
- Backend: add prompt_template_key + prompt_overrides to CompositeWorkflowRunRequest schema"
```
