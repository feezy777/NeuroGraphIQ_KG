import React, { useCallback, useEffect, useMemo, useRef, useState } from 'react'
import * as d3 from 'd3'
import { useGlobalGranularity } from '../hooks/useGlobalGranularity'
import { ForceGraph, GNode, GEdge, LegendItem } from '../components/ForceGraph'

// ── Types ───────────────────────────────────────────────────────────────────

interface RawGraph { nodes: any[]; edges: any[]; stats: Record<string, number> }

const NODE_COLOR: Record<string, string> = { region: '#3b82f6', circuit: '#f59e0b', connection: '#10b981' }
const NODE_R: Record<string, number> = { region: 7, circuit: 6, connection: 3 }
const EDGE_COLOR: Record<string, string> = {
  structural_connection: '#3b82f6', functional_connectivity: '#f59e0b', projection: '#10b981',
  association: '#8b5cf6', coactivation: '#ec4899', effective_connectivity: '#ef4444',
  uncertain_connection: '#9ca3af', unknown: '#d1d5db',
}
const EDGE_DASH: Record<string, string> = {
  structural_connection: '', functional_connectivity: '6,3', projection: '2,2',
  association: '', coactivation: '', effective_connectivity: '', uncertain_connection: '',
}

/** Legend items describing the node & edge color scheme. */
const LEGEND_ITEMS: LegendItem[] = [
  { color: '#3b82f6', dash: '', label: '● 脑区(Region)' },
  { color: '#3b82f6', dash: '', label: '结构连接' },
  { color: '#f59e0b', dash: '6,3', label: '功能连接' },
  { color: '#10b981', dash: '2,2', label: '投射' },
  { color: '#8b5cf6', dash: '', label: '关联' },
  { color: '#ec4899', dash: '', label: '共激活' },
  { color: '#ef4444', dash: '', label: '有效连接' },
  { color: '#9ca3af', dash: '', label: '不确定' },
]

// ── Normalize ───────────────────────────────────────────────────────────────

function normalize(raw: RawGraph): { nodes: GNode[]; edges: GEdge[] } {
  const nm = new Map<string, GNode>()
  for (const n of raw.nodes) {
    nm.set(n.id, { id: n.id, type: n.type, group: n.group, label: n.name_en || n.name_cn || n.label || n.id.slice(0, 8), name_en: n.name_en || '', name_cn: n.name_cn || '', atlas: 'Macro96' })
  }
  const edges: GEdge[] = []
  for (const e of raw.edges) {
    const s = String((e as any).source || (e as any).source_id || (e as any).source_region_id || (e as any).from || '')
    const t = String((e as any).target || (e as any).target_id || (e as any).target_region_id || (e as any).to || '')
    const ct = e.type || 'unknown'
    const sn = (e as any).source_name || ''; const tn = (e as any).target_name || ''
    edges.push({ id: e.id, source: s, target: t, type: ct, confidence: e.confidence || 0.3, label: sn && tn ? `${sn}→${tn}` : `${s.slice(0,8)}→${t.slice(0,8)}` })
  }
  return { nodes: [...nm.values()], edges }
}

// ── Page ────────────────────────────────────────────────────────────────────

export function GraphExplorerPage() {
  const [tab, setTab] = useState<'focus' | 'global' | 'data'>('global')
  const [raw, setRaw] = useState<RawGraph | null>(null)
  const [loading, setLoading] = useState(true)
  const [err, setErr] = useState<string | null>(null)
  const [search, setSearch] = useState('')
  const [fType, setFType] = useState('all')
  const [minConf, setMinConf] = useState(0)
  const [focusNode, setFocusNode] = useState<string | null>(null)
  const [reloadTick, setReloadTick] = useState(0)
  const [refreshing, setRefreshing] = useState(false)
  const [confOpacity, setConfOpacity] = useState(true)
  const initialLoadRef = useRef(true)
  const { granularity } = useGlobalGranularity()

  useEffect(() => {
    let cancelled = false
    if (initialLoadRef.current) setLoading(true)
    else setRefreshing(true)
    setErr(null)
    fetch(`/api/kg/graph/data?limit_connections=100000&granularity_level=${granularity}`)
      .then(r => r.json())
      .then(d => { if (cancelled) return; setRaw(d); setLoading(false); setRefreshing(false); initialLoadRef.current = false })
      .catch(e => { if (cancelled) return; setErr(e.message); setLoading(false); setRefreshing(false); initialLoadRef.current = false })
    return () => { cancelled = true }
  }, [granularity, reloadTick])

  const graph = useMemo(() => {
    if (!raw) return null
    try { return normalize(raw) } catch (e: any) { setErr(e.message); return null }
  }, [raw])

  const visEdges = useMemo(() => {
    if (!graph) return []
    return graph.edges.filter(e => {
      if (fType !== 'all' && e.type !== fType) return false
      if ((e.confidence ?? 0) < minConf) return false
      return true
    })
  }, [graph, fType, minConf])

  const visNodes = useMemo(() => {
    if (!graph) return []
    const conn = new Set<string>()
    for (const e of visEdges) { conn.add(e.source); conn.add(e.target) }
    let nodes = graph.nodes.filter(n => conn.has(n.id) || n.type === 'region')
    if (tab === 'focus' && focusNode) {
      const hop = new Set<string>([focusNode])
      for (const e of visEdges) { if (e.source === focusNode) hop.add(e.target); if (e.target === focusNode) hop.add(e.source) }
      nodes = nodes.filter(n => hop.has(n.id))
    }
    if (search) nodes = nodes.filter(n => n.label.toLowerCase().includes(search.toLowerCase()))
    return nodes
  }, [graph, visEdges, tab, focusNode, search])

  if (loading) return <div style={{ padding: 40, color: '#888' }}>加载图谱数据…</div>
  if (err) return <div style={{ padding: 40, color: '#dc2626' }}>错误: {err}</div>

  return (
    <div style={{ padding: 16, height: 'calc(100vh - 60px)', display: 'flex', flexDirection: 'column' }}>
      <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: 8 }}>
        <div>
          <h2 style={{ margin: 0, fontSize: 18 }}>🧠 图谱探索</h2>
          <p style={{ color: '#888', fontSize: 12, margin: '2px 0 0' }}>
            {raw ? `粒度: ${granularity} · ${raw.stats.regions||0} 脑区 · ${raw.stats.connections||0} 连接` : ''}
          </p>
        </div>
        <div style={{ display: 'flex', gap: 4 }}>
          <button className="btn btn-sm" onClick={() => setReloadTick(t => t + 1)} disabled={refreshing} title="重新拉取最新数据">
            {refreshing ? '⏳ 刷新中' : '🔄 刷新'}
          </button>
          <button className={`btn btn-sm${confOpacity ? ' btn-primary' : ''}`} onClick={() => setConfOpacity(c => !c)} title="按置信度区分连线明暗">
            {confOpacity ? '📊 置信度' : '📊 统一'}
          </button>
          {(['focus','global','data'] as const).map(t => (
            <button key={t} className={`btn btn-sm${tab===t?' btn-primary':''}`} onClick={()=>setTab(t)}>
              {t==='focus'?'🔍 聚焦':t==='global'?'🌐 全局':'📊 数据'}
            </button>
          ))}
        </div>
      </div>

      <div style={{ fontSize: 11, color: '#666', marginBottom: 4, display: 'flex', gap: 12 }}>
        <span>节点: {visNodes.length}/{graph?.nodes.length||0}</span>
        <span>边: {visEdges.length}/{graph?.edges.length||0}</span>
        {graph && graph.edges.length>0 && visEdges.length===0 && (
          <span style={{ color: '#dc2626' }}>⚠️ 当前筛选条件下无可见连线</span>
        )}
      </div>

      <div style={{ display: 'flex', gap: 8, marginBottom: 8 }}>
        <input className="form-input" placeholder={tab==='focus'?'搜索脑区/回路名称…':'搜索节点名称…'} value={search} onChange={e=>setSearch(e.target.value)} style={{width:180,fontSize:12}}/>
        <select className="form-input" value={fType} onChange={e=>setFType(e.target.value)} style={{width:150,fontSize:12}}>
          <option value="all">全部关系</option>
          <option value="structural_connection">结构连接</option>
          <option value="functional_connectivity">功能连接</option>
          <option value="projection">投射</option>
          <option value="association">关联</option>
          <option value="coactivation">共激活</option>
          <option value="effective_connectivity">有效连接</option>
          <option value="uncertain_connection">不确定</option>
        </select>
        <label style={{fontSize:11,display:'flex',alignItems:'center',gap:4}}>
          置信度≥{minConf.toFixed(1)}
          <input type="range" min={0} max={100} value={Math.round(minConf*100)} style={{width:64}} onChange={e=>setMinConf(Number(e.target.value)/100)}/>
        </label>
        {tab==='focus'&&focusNode&&<button className="btn btn-sm" onClick={()=>setFocusNode(null)}>清除聚焦</button>}
      </div>

      <div style={{flex:1,border:'1px solid var(--border)',borderRadius:8,overflow:'hidden',background:'#f8fafc'}}
        onClick={tab==='focus'?()=>setFocusNode(null):undefined}>
        {tab==='data'?<DataView edges={visEdges} graph={graph}/>:<ForceGraph nodes={visNodes} edges={visEdges} focusNode={focusNode} onNodeClick={tab==='focus'?setFocusNode:undefined} edgeColors={EDGE_COLOR} edgeDashes={EDGE_DASH} nodeColors={NODE_COLOR} nodeRadii={NODE_R} legendItems={LEGEND_ITEMS} confOpacity={confOpacity}/>}
      </div>
    </div>
  )
}

// ── Data View ───────────────────────────────────────────────────────────────

function DataView({ edges, graph }: { edges: GEdge[]; graph: { nodes: GNode[]; edges: GEdge[] } | null }) {
  const nm = useMemo(() => { const m = new Map<string,string>(); if (graph) for (const n of graph.nodes) m.set(n.id, n.label); return m }, [graph])
  return <div style={{padding:8,overflow:'auto',height:'100%',fontSize:11}}>
    <table style={{width:'100%',borderCollapse:'collapse'}}>
      <thead><tr style={{background:'#f1f5f9'}}><th style={th}>source</th><th style={th}>target</th><th style={th}>type</th><th style={th}>conf</th><th style={th}>label</th></tr></thead>
      <tbody>{edges.slice(0,200).map(e=><tr key={e.id}><td style={td}>{nm.get(e.source)||e.source.slice(0,12)}</td><td style={td}>{nm.get(e.target)||e.target.slice(0,12)}</td><td style={td}>{e.type}</td><td style={td}>{((e.confidence ?? 0)*100).toFixed(0)}%</td><td style={{...td,maxWidth:160,overflow:'hidden',textOverflow:'ellipsis'}}>{e.label}</td></tr>)}</tbody>
    </table>
  </div>
}
const th: React.CSSProperties = { padding: '4px 8px', textAlign: 'left', borderBottom: '2px solid #e5e7eb', position: 'sticky', top: 0, background: '#f1f5f9' }
const td: React.CSSProperties = { padding: '3px 8px', borderBottom: '1px solid #f3f4f6', whiteSpace: 'nowrap' }
