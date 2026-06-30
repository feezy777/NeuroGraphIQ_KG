# Task 1: Add state + workflowType→template key mapping

**File to modify:** `frontend/src/pages/llm-extraction/components/PoolExtractionModal.tsx`

## Requirements

### 1. Add imports (line 3, in the existing import block from `../../../api/endpoints`)

Add these to the existing destructured import list:
```
getExtractionPromptTemplates,
type ExtractionPromptTemplate,
```

### 2. Add state variables (after line 217, after `localPoolId` state)

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

### 3. Add WORKFLOW_PRIMARY_TEMPLATE mapping + template loading effect + primaryTemplate memo

Insert after the state declarations (before the `// Keep localMembers in sync...` effect, around line 270):

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

  // Primary template from fetched templates
  const primaryTemplate = useMemo(
    () => promptTemplates.find(t => t.key === primaryTemplateKey),
    [promptTemplates, primaryTemplateKey],
  )

  // Populate custom prompts when template loads
  useEffect(() => {
    if (primaryTemplate) {
      setCustomSystemPrompt(primaryTemplate.system_prompt)
      setCustomUserPrompt(primaryTemplate.template)
    }
  }, [primaryTemplate?.key])
```

## Global Constraints
- Build must pass: `cd D:\Tool\Coding\IDE\PyCharm\NeuroGraphIQ_KG_V3_1\frontend && npm run build` with 0 TypeScript errors
- No new dependencies
- Follow existing code style: 2-space indent, camelCase, useMemo for derived values

## Verification
After implementation, run:
```
cd D:\Tool\Coding\IDE\PyCharm\NeuroGraphIQ_KG_V3_1\frontend && npm run build
```
Expected: 0 TypeScript errors, build succeeds.
