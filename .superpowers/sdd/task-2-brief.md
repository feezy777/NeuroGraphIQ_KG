# Task 2: Add Temperature/MaxTokens sliders + prompt preview UI to renderStep2

**File to modify:** `frontend/src/pages/llm-extraction/components/PoolExtractionModal.tsx`

**Interfaces from Task 1 (already committed):**
- `temperature` (float state, default 0.7)
- `maxTokens` (int state, default 4096)
- `showPromptPreview` (bool state)
- `editingPrompt` (bool state)
- `customSystemPrompt` (string state)
- `customUserPrompt` (string state)
- `primaryTemplate` (ExtractionPromptTemplate | undefined)
- `primaryTemplateKey` (string)

## Requirements

### 1. Add "高级参数" section with Temperature + MaxTokens sliders

In `renderStep2`, after the existing `</label>` (Dry run checkbox closing tag) and BEFORE `</div>` (the modal-section closing div), insert:

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

### 2. Add collapsible prompt template preview section

After the advanced params section, still within the `padding: '0 20px', flex: 1, ...` container div, add:

```tsx
          {/* Prompt template preview */}
          <div className="modal-section" style={{ flex: 1, display: 'flex', flexDirection: 'column', minHeight: 0 }}>
            <p
              className="modal-section-title"
              style={{ cursor: 'pointer', userSelect: 'none', display: 'flex', justifyContent: 'space-between', alignItems: 'center' }}
              onClick={() => setShowPromptPreview(!showPromptPreview)}
            >
              <span>提示词模板 {showPromptPreview ? '▾' : '▸'}</span>
              {primaryTemplate && !showPromptPreview && (
                <span style={{ fontWeight: 400, fontSize: 12, color: '#888' }}>{primaryTemplate.key}</span>
              )}
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
                        if (editingPrompt && primaryTemplate) {
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

## Key insertion point

The new sections go INSIDE the step 2 content container div. Find this container:
```
<div style={{ padding: '0 20px', flex: 1, display: 'flex', flexDirection: 'column', overflow: 'hidden' }}>
```
It contains two existing children: `modal-section` (scope summary) and `modal-section` (model config with ModelSelector + dry run). After the ModelSelector modal-section's closing `</div>`, add the two new sections.

## Global Constraints
- Build must pass: `cd D:\Tool\Coding\IDE\PyCharm\NeuroGraphIQ_KG_V3_1\frontend && npm run build` with 0 TypeScript errors
- No new dependencies
- Follow existing inline style patterns (no new CSS classes needed)
- All state variables already exist from Task 1

## Verification
After implementation, run:
```
cd D:\Tool\Coding\IDE\PyCharm\NeuroGraphIQ_KG_V3_1\frontend && npm run build
```
Expected: 0 TypeScript errors, build succeeds.
