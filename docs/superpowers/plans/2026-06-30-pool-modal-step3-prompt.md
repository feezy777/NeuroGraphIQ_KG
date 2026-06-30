# PoolExtractionModal Step 3 Prompt Page Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Move prompt template preview/edit from cramped step 2 into a dedicated step 3, giving textareas full height.

**Architecture:** 3-step wizard: (1) region selection → (2) model + params → (3) prompt review/edit. Single file change in `PoolExtractionModal.tsx` — remove prompt section from `renderStep2`, create `renderStep3`, update navigation. ~50 lines removed from step 2, ~120 lines added as step 3.

**Tech Stack:** React 18 + TypeScript, Vite

## Global Constraints

- Build must pass: `cd frontend && npm run build` with 0 TypeScript errors
- No new dependencies, no new CSS classes
- Follow existing inline style patterns
- `lockedPanelHeight` must apply to both step 2 and step 3 (keep modal size consistent after step 1)
- All existing prompt state (temperature, maxTokens, editingPrompt, customSystemPrompt, customUserPrompt, primaryTemplate, etc.) remains unchanged

---

### Task 1: Change wizardStep type + remove prompt section from step 2 + update step 2 footer

**Files:**
- Modify: `frontend/src/pages/llm-extraction/components/PoolExtractionModal.tsx`

**Interfaces:**
- Produces: `wizardStep` type widened to `1 | 2 | 3`, step 2 footer now says "下一步" instead of "开始提取"

- [ ] **Step 1: Change wizardStep type**

Line 213, change:
```typescript
  const [wizardStep, setWizardStep] = useState<1 | 2>(1)
```
to:
```typescript
  const [wizardStep, setWizardStep] = useState<1 | 2 | 3>(1)
```

- [ ] **Step 2: Remove prompt template section from renderStep2**

Delete lines 1376-1481 (the entire `{/* Prompt template preview */}` section — from `<div className="modal-section" style={{ flex: 1, ...` through its closing `</div>` just before `</div>` (the padding container closing tag)).

The exact block to delete starts at:
```tsx
        {/* Prompt template preview */}
        <div className="modal-section" style={{ flex: 1, display: 'flex', flexDirection: 'column', minHeight: 0 }}>
```
and ends at the matching `</div>` before:
```tsx
      </div>

      {/* Footer */}
```
which is the `padding: '0 20px', flex: 1, ...` container's closing `</div>`.

- [ ] **Step 3: Change step 2 footer buttons**

Replace the step 2 footer (lines 1484-1496):
```tsx
      {/* Footer */}
      <div className="modal-footer">
        <button className="llm-btn" onClick={() => setWizardStep(1)}>上一步</button>
        <button className="llm-btn" onClick={handleClose}>取消</button>
        <button
          className="llm-btn llm-btn-primary"
          onClick={handleStartExtraction}
          disabled={!pool || selectedExtractionIds.length < 2}
        >
          开始提取 ({selectedExtractionIds.length} 区)
        </button>
      </div>
```
with:
```tsx
      {/* Footer */}
      <div className="modal-footer">
        <button className="llm-btn" onClick={() => setWizardStep(1)}>上一步</button>
        <button className="llm-btn" onClick={handleClose}>取消</button>
        <button
          className="llm-btn llm-btn-primary"
          onClick={() => setWizardStep(3)}
        >
          下一步
        </button>
      </div>
```

- [ ] **Step 4: Verify build**

Run: `cd D:\Tool\Coding\IDE\PyCharm\NeuroGraphIQ_KG_V3_1\frontend && npm run build`
Expected: `✓ built` with 0 TypeScript errors

---

### Task 2: Create renderStep3 with prompt template content

**Files:**
- Modify: `frontend/src/pages/llm-extraction/components/PoolExtractionModal.tsx` (insert before `renderProgress`)

**Interfaces:**
- Consumes: `workflowType`, `primaryTemplate`, `primaryTemplateKey`, `showPromptPreview` (always true in step 3), `editingPrompt`, `customSystemPrompt`, `customUserPrompt`, `selectedExtractionIds`
- Produces: `renderStep3()` function

- [ ] **Step 1: Create renderStep3 function**

Insert between `renderStep2` closing `</>` and `renderProgress`, the new step 3:

```tsx
  // ── Render: step 3 (prompt template) ──────────────────────────────────────
  const renderStep3 = () => (
    <>
      <div className="modal-header">
        <h3 style={{ margin: 0, fontSize: 18, fontWeight: 600, color: '#1a1a2e' }}>
          提示词模板
        </h3>
        <button className="btn-close" onClick={handleClose}>x</button>
      </div>

      <div style={{ padding: '0 20px', flex: 1, display: 'flex', flexDirection: 'column', overflow: 'hidden' }}>
        {/* Scope summary */}
        <div className="modal-section">
          <p className="modal-section-title">提取范围</p>
          <div className="modal-section-row">
            <span className="label">{selectedExtractionIds.length} 个脑区 · {selectedPairCount.toLocaleString()} 对 · 约 {selectedPackEstimate} 包</span>
          </div>
        </div>

        {/* Template info */}
        <div className="modal-section">
          <p className="modal-section-title">当前模板</p>
          <div style={{ fontSize: 13, color: '#555' }}>
            <code style={{ fontSize: 12, background: '#f0f2f5', padding: '2px 6px', borderRadius: 3 }}>{primaryTemplateKey || '—'}</code>
            {primaryTemplate && (
              <span style={{ marginLeft: 8, color: '#888' }}>
                {primaryTemplate.display_name ?? primaryTemplate.title}
              </span>
            )}
          </div>
          {!primaryTemplate && (
            <div style={{ fontSize: 12, color: '#999', fontStyle: 'italic', marginTop: 4 }}>加载中或模板不可用...</div>
          )}
        </div>

        {/* Edit toggle */}
        <div style={{ display: 'flex', justifyContent: 'flex-end', marginBottom: 4 }}>
          <button
            type="button"
            className="llm-btn"
            onClick={() => {
              if (editingPrompt && primaryTemplate) {
                setCustomSystemPrompt(primaryTemplate.system_prompt)
                setCustomUserPrompt(primaryTemplate.template)
              }
              setEditingPrompt(!editingPrompt)
            }}
          >
            {editingPrompt ? '恢复默认' : '编辑提示词'}
          </button>
        </div>

        {/* System prompt */}
        <div className="modal-section" style={{ flex: 1, display: 'flex', flexDirection: 'column', minHeight: 0 }}>
          <p className="modal-section-title">System Prompt</p>
          <textarea
            style={{
              flex: 1,
              minHeight: 100,
              width: '100%',
              fontSize: 12,
              fontFamily: 'monospace',
              lineHeight: 1.5,
              border: '1px solid #d0d7e2',
              borderRadius: 4,
              padding: '8px 10px',
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
        <div className="modal-section" style={{ flex: 1.5, display: 'flex', flexDirection: 'column', minHeight: 0 }}>
          <p className="modal-section-title">User Prompt</p>
          <textarea
            style={{
              flex: 1,
              minHeight: 100,
              width: '100%',
              fontSize: 12,
              fontFamily: 'monospace',
              lineHeight: 1.5,
              border: '1px solid #d0d7e2',
              borderRadius: 4,
              padding: '8px 10px',
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
          <div style={{ padding: '8px 12px', marginTop: 8, background: '#fff7e6', borderRadius: 6, fontSize: 12, color: '#d48806' }}>
            ⚠ 输出 JSON schema 由后端固定，修改 prompt 时请保留输出格式要求，否则 LLM 返回的数据无法解析入库。
          </div>
        )}

        {/* Composite workflow note */}
        {(workflowType === 'connection_with_function' || workflowType === 'circuit_with_function_steps') && (
          <div style={{ padding: '8px 12px', marginTop: 8, background: '#f8f9fa', borderRadius: 6, fontSize: 12, color: '#888' }}>
            {workflowType === 'connection_with_function' && (
              <>复合工作流第二步使用 <code>projection_to_functions_v1</code> 模板（后端自动选择）</>
            )}
            {workflowType === 'circuit_with_function_steps' && (
              <>复合工作流多步骤分别使用 <code>circuit_to_steps_v1</code>、<code>circuit_to_functions_extraction_v1</code> 模板（后端自动选择）</>
            )}
          </div>
        )}
      </div>

      {/* Footer */}
      <div className="modal-footer">
        <button className="llm-btn" onClick={() => setWizardStep(2)}>上一步</button>
        <button className="llm-btn" onClick={handleClose}>取消</button>
        <button
          className="llm-btn llm-btn-primary"
          onClick={handleStartExtraction}
          disabled={!pool || selectedExtractionIds.length < 2}
        >
          开始提取 ({selectedExtractionIds.length} 区)
        </button>
      </div>
    </>
  )
```

- [ ] **Step 2: Verify build**

Run: `cd D:\Tool\Coding\IDE\PyCharm\NeuroGraphIQ_KG_V3_1\frontend && npm run build`
Expected: `✓ built` with 0 TypeScript errors

---

### Task 3: Update render dispatcher + lockedPanelHeight for step 3

**Files:**
- Modify: `frontend/src/pages/llm-extraction/components/PoolExtractionModal.tsx` (render dispatcher)

- [ ] **Step 1: Add step 3 to render dispatcher**

At line ~1907, add the step 3 condition:
```tsx
        {modalState === 'prepare' && wizardStep === 1 && renderStep1()}
        {modalState === 'prepare' && wizardStep === 2 && renderStep2()}
        {modalState === 'prepare' && wizardStep === 3 && renderStep3()}
        {modalState === 'progress' && renderProgress()}
        {modalState === 'result' && renderResult()}
```

- [ ] **Step 2: Extend lockedPanelHeight to cover step 3**

At line ~1899, change the minHeight condition from:
```tsx
          minHeight: wizardStep === 2 ? lockedPanelHeight : 520,
```
to:
```tsx
          minHeight: wizardStep !== 1 ? lockedPanelHeight : 520,
```

- [ ] **Step 3: Verify build**

Run: `cd D:\Tool\Coding\IDE\PyCharm\NeuroGraphIQ_KG_V3_1\frontend && npm run build`
Expected: `✓ built` with 0 TypeScript errors

---

### Task 4: Commit

- [ ] **Step 1: Commit all changes**

```bash
git add frontend/src/pages/llm-extraction/components/PoolExtractionModal.tsx
git commit -m "feat: move prompt template to dedicated step 3 in PoolExtractionModal

- Widen wizardStep type from 1|2 to 1|2|3
- Remove cramped prompt section from step 2, keep only model + params
- Add renderStep3 with full-height system/user prompt textareas
- Step 2 footer: 上一步/取消/下一步
- Step 3 footer: 上一步/取消/开始提取
- Extend lockedPanelHeight to cover both step 2 and step 3"
```
