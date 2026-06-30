# Task 1: Change wizardStep type + remove prompt from step 2 + update step 2 footer

**File:** `frontend/src/pages/llm-extraction/components/PoolExtractionModal.tsx`

3 changes:

### 1. Change wizardStep type (line ~213)
Change `useState<1 | 2>(1)` to `useState<1 | 2 | 3>(1)`

### 2. Remove prompt section from renderStep2
Delete the entire `{/* Prompt template preview */}` block — from:
```
        {/* Prompt template preview */}
        <div className="modal-section" style={{ flex: 1, display: 'flex', flexDirection: 'column', minHeight: 0 }}>
```
through to the matching `</div>` that closes this section, which is just before the outer container's `</div>` and `{/* Footer */}`.

Everything between these two markers gets removed:
- The collapsible header with `showPromptPreview` toggle
- The system prompt textarea
- The user prompt textarea
- The editing warning
- The composite workflow notes

### 3. Change step 2 footer
Replace the current footer buttons:
```tsx
        <button className="llm-btn" onClick={() => setWizardStep(1)}>上一步</button>
        <button className="llm-btn" onClick={handleClose}>取消</button>
        <button
          className="llm-btn llm-btn-primary"
          onClick={handleStartExtraction}
          disabled={!pool || selectedExtractionIds.length < 2}
        >
          开始提取 ({selectedExtractionIds.length} 区)
        </button>
```
With:
```tsx
        <button className="llm-btn" onClick={() => setWizardStep(1)}>上一步</button>
        <button className="llm-btn" onClick={handleClose}>取消</button>
        <button
          className="llm-btn llm-btn-primary"
          onClick={() => setWizardStep(3)}
        >
          下一步
        </button>
```

## Build check
Run: `cd D:\Tool\Coding\IDE\PyCharm\NeuroGraphIQ_KG_V3_1\frontend && npm run build`
Must pass with 0 TypeScript errors.
