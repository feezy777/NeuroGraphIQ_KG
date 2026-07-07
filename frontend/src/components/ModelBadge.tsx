// ── Model badge: shows provider + model with distinct color per model ────────

interface ModelInfo {
  label: string
  color: string
  bg: string
  border: string
}

const MODEL_REGISTRY: Record<string, ModelInfo> = {
  // DeepSeek models
  'deepseek-chat':    { label: 'DeepSeek V3',   color: '#0d9488', bg: '#f0fdfa', border: '#99f6e4' },
  'deepseek-v4-pro':  { label: 'DeepSeek V4P',  color: '#4f46e5', bg: '#eef2ff', border: '#c7d2fe' },
  'deepseek-reasoner':{ label: 'DeepSeek R1',   color: '#7c3aed', bg: '#f5f3ff', border: '#ddd6fe' },
  // Kimi models
  'moonshot-v1-auto': { label: 'Kimi',          color: '#059669', bg: '#ecfdf5', border: '#a7f3d0' },
  'moonshot-v1-8k':   { label: 'Kimi 8K',       color: '#16a34a', bg: '#f0fdf4', border: '#bbf7d0' },
  'moonshot-v1-32k':  { label: 'Kimi 32K',      color: '#0891b2', bg: '#ecfeff', border: '#a5f3fc' },
}

function resolveModelInfo(provider?: string, modelName?: string): ModelInfo | null {
  if (!provider && !modelName) return null
  // Try exact model name first
  if (modelName && MODEL_REGISTRY[modelName]) return MODEL_REGISTRY[modelName]
  // Try provider-level fallback
  if (provider) {
    const key = Object.keys(MODEL_REGISTRY).find(k => k.startsWith(provider.toLowerCase()))
    if (key) return MODEL_REGISTRY[key]
  }
  // Unknown model — show as generic
  return {
    label: modelName || provider || '?',
    color: '#6b7280', bg: '#f9fafb', border: '#e5e7eb',
  }
}

interface ModelBadgeProps {
  provider?: string
  modelName?: string
}

export function ModelBadge({ provider, modelName }: ModelBadgeProps) {
  const info = resolveModelInfo(provider, modelName)
  if (!info) return null
  return (
    <span
      className="model-badge"
      style={{
        background: info.bg,
        color: info.color,
        border: `1px solid ${info.border}`,
      }}
    >
      {info.label}
    </span>
  )
}
