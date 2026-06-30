# Task 2: Create renderStep3 function

**File:** `frontend/src/pages/llm-extraction/components/PoolExtractionModal.tsx`

Insert the new `renderStep3` function between `renderStep2` and `renderProgress`.

## Exact code to insert

After the `renderStep2` closing `</>` (line just before `// ── Render: progress`), insert:

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

All state variables used here already exist: `primaryTemplateKey`, `primaryTemplate`, `editingPrompt`, `customSystemPrompt`, `customUserPrompt`, `workflowType`, `selectedExtractionIds`, `selectedPairCount`, `selectedPackEstimate`, `pool`.

## Build check
Run: `cd D:\Tool\Coding\IDE\PyCharm\NeuroGraphIQ_KG_V3_1\frontend && npm run build`
Must pass with 0 TypeScript errors.
