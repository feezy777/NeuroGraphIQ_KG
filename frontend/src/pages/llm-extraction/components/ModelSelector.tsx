import { useMemo } from 'react'

export interface ModelPreset {
  label: string
  value: string
  description?: string
}

export const DEEPSEEK_MODELS: ModelPreset[] = [
  { label: 'DeepSeek V4 Pro (deepseek-v4-pro)', value: 'deepseek-v4-pro', description: '最新旗舰版，高精度、强推理' },
  { label: 'DeepSeek V3 (deepseek-chat)', value: 'deepseek-chat', description: '标准版对话模型，速度快、效果好' },
  { label: 'DeepSeek R1 (deepseek-reasoner)', value: 'deepseek-reasoner', description: '增强推理模型，适合复杂逻辑任务' },
]

export const KIMI_MODELS: ModelPreset[] = [
  { label: 'Kimi k1.5 (moonshot-v1-auto)', value: 'moonshot-v1-auto', description: '最新版 Kimi 自动路由模型' },
  { label: 'Kimi k1.5 32k (moonshot-v1-32k)', value: 'moonshot-v1-32k', description: '长上下文版本，适合大批量提取' },
  { label: 'Kimi k1.5 8k (moonshot-v1-8k)', value: 'moonshot-v1-8k', description: '标准版' },
]

interface ModelSelectorProps {
  provider: string
  modelName: string
  onProviderChange: (p: string) => void
  onModelChange: (m: string) => void
  providers: Array<{ name: string; configured: boolean; default_model: string }>
}

export function ModelSelector({
  provider,
  modelName,
  onProviderChange,
  onModelChange,
  providers,
}: ModelSelectorProps) {
  const models = provider === 'kimi' ? KIMI_MODELS : DEEPSEEK_MODELS
  const currentProvider = providers.find(p => p.name === provider)

  const currentModelLabel = useMemo(() => {
    // If typed model name matches a preset value, show its label
    const match = models.find(m => m.value === modelName)
    if (match) return match.label
    // If modelName is empty or custom (typed in), show custom
    return modelName || (models[0]?.value ?? '')
  }, [models, modelName])

  const handleModelSelect = (value: string) => {
    onModelChange(value)
  }

  return (
    <div className="model-selector">
      <div className="model-selector-row">
        {/* Provider */}
        <div className="model-selector-group">
          <label className="model-selector-label">Provider</label>
          <div className="model-selector-providers">
            {providers.filter(p => ['deepseek', 'kimi'].includes(p.name)).map(p => (
              <button
                key={p.name}
                type="button"
                className={`model-provider-btn${provider === p.name ? ' active' : ''}`}
                onClick={() => { onProviderChange(p.name); onModelChange(p.default_model || models[0]?.value || '') }}
              >
                <span className="model-provider-name">{p.name}</span>
                <span className={`model-provider-status ${p.configured ? 'configured' : 'not-configured'}`}>
                  {p.configured ? '已配置' : '未配置'}
                </span>
              </button>
            ))}
          </div>
        </div>

        {/* Model */}
        <div className="model-selector-group">
          <label className="model-selector-label">Model</label>
          <div className="model-selector-models">
            {models.map(m => (
              <button
                key={m.value}
                type="button"
                className={`model-option-btn${modelName === m.value ? ' active' : ''}${!currentProvider?.configured ? ' disabled' : ''}`}
                onClick={() => handleModelSelect(m.value)}
                title={m.description}
              >
                <span className="model-option-value">{m.value}</span>
                {m.description && <span className="model-option-desc">{m.description}</span>}
              </button>
            ))}
          </div>
          {/* Custom model input */}
          <div className="model-custom-row">
            <span className="model-custom-label">或自定义：</span>
            <input
              className="form-input model-custom-input"
              placeholder="输入模型名..."
              value={models.some(m => m.value === modelName) ? '' : modelName}
              onChange={e => onModelChange(e.target.value)}
            />
          </div>
        </div>
      </div>
    </div>
  )
}
