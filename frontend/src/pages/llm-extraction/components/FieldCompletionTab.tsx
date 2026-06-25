import { useState, useMemo } from 'react'
import { DataTable, type Column } from '../../../components/DataTable'
import { StatusBadge } from '../../../components/StatusBadge'
import { useData } from '../../../hooks/useData'
import { ModelSelector } from './ModelSelector'
import {
  listMirrorConnections,
  listMirrorCircuits,
  runRegionFieldCompletion,
  type MirrorRegionConnection,
  type MirrorRegionCircuit,
} from '../../../api/endpoints'

type TargetType = 'connection' | 'circuit' | 'circuit_bundle'

interface FieldCompletionTabProps {
  providers: Array<{ name: string; configured: boolean; default_model: string }>
}

export function FieldCompletionTab({ providers }: FieldCompletionTabProps) {
  const [targetType, setTargetType] = useState<TargetType>('connection')
  const [provider, setProvider] = useState('deepseek')
  const [modelName, setModelName] = useState('')
  const [selectedIds, setSelectedIds] = useState<string[]>([])
  const [running, setRunning] = useState(false)
  const [result, setResult] = useState<any>(null)

  const currentProvider = providers.find(p => p.name === provider)
  useMemo(() => {
    if (currentProvider && !modelName) setModelName(currentProvider.default_model)
  }, [currentProvider, modelName])

  const connParams = useMemo(() => ({ limit: 100 }), [])
  const circParams = useMemo(() => ({ limit: 100 }), [])
  const showConn = targetType === 'connection'
  const showCirc = targetType === 'circuit' || targetType === 'circuit_bundle'

  const { data: connections } = useData(
    () => showConn ? listMirrorConnections(connParams) : (Promise.resolve({ items: [], total: 0, limit: 100, offset: 0 }) as any),
    [showConn, connParams],
  )
  const { data: circuits } = useData(
    () => showCirc ? listMirrorCircuits(circParams) : (Promise.resolve({ items: [], total: 0, limit: 100, offset: 0 }) as any),
    [showCirc, circParams],
  )

  const connColumns: Column<MirrorRegionConnection>[] = useMemo(() => [
    { key: '_sel', header: '', width: 36, render: r => (
      <input type="checkbox" checked={selectedIds.includes(r.id)} onChange={() => {
        setSelectedIds(prev => prev.includes(r.id) ? prev.filter(x => x !== r.id) : [...prev, r.id])
      }} />
    )},
    { key: 'source_region_candidate_id', header: '源', render: r => (r.source_region_candidate_id || '—').slice(0, 10) },
    { key: 'target_region_candidate_id', header: '靶', render: r => (r.target_region_candidate_id || '—').slice(0, 10) },
    { key: 'connection_type', header: '类型', width: 120 },
    { key: 'confidence', header: '置信度', width: 70, render: r => r.confidence != null ? Math.round(r.confidence * 100) + '%' : '—' },
    { key: 'mirror_status', header: '状态', width: 80, render: r => <StatusBadge status={r.mirror_status} /> },
  ], [selectedIds])

  const circuitColumns: Column<MirrorRegionCircuit>[] = useMemo(() => [
    { key: '_sel', header: '', width: 36, render: r => (
      <input type="checkbox" checked={selectedIds.includes(r.id)} onChange={() => {
        setSelectedIds(prev => prev.includes(r.id) ? prev.filter(x => x !== r.id) : [...prev, r.id])
      }} />
    )},
    { key: 'circuit_name', header: '回路名称', width: 200 },
    { key: 'circuit_type', header: '类型', width: 120 },
    { key: 'function_association', header: '功能', render: r => r.function_association || '—' },
    { key: 'confidence', header: '置信度', width: 70, render: r => r.confidence != null ? Math.round(r.confidence * 100) + '%' : '—' },
    { key: 'mirror_status', header: '状态', width: 80, render: r => <StatusBadge status={r.mirror_status} /> },
  ], [selectedIds])

  const conns = (connections as any)?.items ?? []
  const circs = (circuits as any)?.items ?? []

  const handleRun = async () => {
    if (selectedIds.length === 0) return
    setRunning(true)
    setResult(null)
    try {
      if (targetType === 'circuit_bundle') {
        setResult({ type: 'bundle', count: selectedIds.length, message: '回路 Bundle 补全请在 Data Center 中操作' })
        return
      }
      for (const id of selectedIds) {
        const res = await runRegionFieldCompletion({
          provider,
          model_name: modelName || undefined,
          candidate_ids: [id],
          dry_run: false,
        })
        setResult(res)
      }
    } catch (e: any) {
      setResult({ error: e.message || String(e) })
    } finally {
      setRunning(false)
    }
  }

  return (
    <div className="field-completion-tab">
      <div className="field-completion-targets">
        <h4 className="panel-title">补全对象</h4>
        <div className="field-completion-type-row">
          {(['connection', 'circuit', 'circuit_bundle'] as TargetType[]).map(t => (
            <button
              key={t}
              className={`field-completion-type-btn${targetType === t ? ' active' : ''}`}
              onClick={() => { setTargetType(t); setSelectedIds([]) }}
            >
              {t === 'connection' ? '连接 (Projection)' : t === 'circuit' ? '回路 (Circuit)' : '回路 Bundle (Circuit + Steps + Functions)'}
            </button>
          ))}
        </div>
      </div>

      <ModelSelector
        provider={provider}
        modelName={modelName}
        onProviderChange={setProvider}
        onModelChange={setModelName}
        providers={providers}
      />

      <div className="field-completion-selection">
        <h4 className="panel-title">选择对象 ({selectedIds.length} 项已选)</h4>
        {showConn ? (
          <DataTable columns={connColumns} rows={conns} getKey={r => r.id} emptyText="暂无连接数据" />
        ) : (
          <DataTable columns={circuitColumns} rows={circs} getKey={r => r.id} emptyText="暂无回路数据" />
        )}
      </div>

      <div className="field-completion-actions">
        <button className="btn btn-primary" disabled={selectedIds.length === 0 || running || !currentProvider?.configured} onClick={handleRun}>
          {running ? '补全中…' : `✨ 执行字段补全 (${selectedIds.length})`}
        </button>
      </div>

      {result && (
        <div className="field-completion-result">
          <pre>{JSON.stringify(result, null, 2)}</pre>
        </div>
      )}
    </div>
  )
}
