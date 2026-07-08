import React, { useCallback, useEffect, useMemo, useRef, useState } from 'react'
import * as d3 from 'd3'

// ── Types ───────────────────────────────────────────────────────────────────

interface RawGraph { nodes: any[]; edges: any[]; stats: Record<string, number> }
interface GNode { id: string; type: string; label: string; group: string; name_en: string; name_cn: string; atlas: string }
interface GEdge { id: string; source: string; target: string; type: string; confidence: number; label: string }

const NODE_COLOR: Record<string, string> = { region: '#3b82f6', circuit: '#f59e0b', connection: '#10b981' }
const NODE_R: Record<string, number> = { region: 7, circuit: 6, connection: 3 }
const EDGE_COLOR: Record<string, string> = {
  structural_connection: '#3b82f6', functional_connectivity: '#f59e0b', projection: '#10b981',
  association: '#8b5cf6', coactivation: '#ec4899', effective_connectivity: '#ef4444',
  uncertain_connection: '#9ca3af', unknown: '#d1d5db',
  STARTS_AT: '#fcd34d', ENDS_AT: '#f87171', INCLUDES: '#c4b5fd',
}
const EDGE_DASH: Record<string, string> = {
  structural_connection: '', functional_connectivity: '6,3', projection: '2,2',
  STARTS_AT: '4,2', ENDS_AT: '4,2', INCLUDES: '6,3',
}

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
    if (!nm.has(e.id) && ct !== 'STARTS_AT' && ct !== 'ENDS_AT' && ct !== 'INCLUDES') {
      nm.set(e.id, { id: e.id, type: 'connection', group: 'connection', label: `${sn.slice(0,15)||'?'}→${tn.slice(0,15)||'?'}`, name_en: '', name_cn: '', atlas: 'Macro96' })
    }
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

  useEffect(() => {
    fetch('/api/kg/graph/data?limit_connections=5000&include_circuits=true')
      .then(r => r.json()).then(d => { setRaw(d); setLoading(false) })
      .catch(e => { setErr(e.message); setLoading(false) })
  }, [])

  const graph = useMemo(() => {
    if (!raw) return null
    try { return normalize(raw) } catch (e: any) { setErr(e.message); return null }
  }, [raw])

  const visEdges = useMemo(() => {
    if (!graph) return []
    return graph.edges.filter(e => {
      if (fType !== 'all' && e.type !== fType) return false
      if (e.confidence < minConf) return false
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
            {raw ? `${raw.stats.regions||0} 脑区 · ${raw.stats.connections||0} 连接 · ${raw.stats.circuits||0} 回路 · ${raw.stats.memberships||0} 映射` : ''}
          </p>
        </div>
        <div style={{ display: 'flex', gap: 4 }}>
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
        {tab==='focus'&&<input className="form-input" placeholder="搜索脑区名称…" value={search} onChange={e=>setSearch(e.target.value)} style={{width:180,fontSize:12}}/>}
        <select className="form-input" value={fType} onChange={e=>setFType(e.target.value)} style={{width:150,fontSize:12}}>
          <option value="all">全部关系</option>
          <option value="structural_connection">结构连接</option>
          <option value="functional_connectivity">功能连接</option>
          <option value="projection">投射</option>
          <option value="STARTS_AT">回路起点</option>
          <option value="ENDS_AT">回路终点</option>
          <option value="INCLUDES">回路包含</option>
        </select>
        <label style={{fontSize:11,display:'flex',alignItems:'center',gap:4}}>
          置信度≥{minConf.toFixed(1)}
          <input type="range" min={0} max={100} value={Math.round(minConf*100)} style={{width:64}} onChange={e=>setMinConf(Number(e.target.value)/100)}/>
        </label>
        {tab==='focus'&&focusNode&&<button className="btn btn-sm" onClick={()=>setFocusNode(null)}>清除聚焦</button>}
      </div>

      <div style={{flex:1,border:'1px solid var(--border)',borderRadius:8,overflow:'hidden',background:'#f8fafc'}}
        onClick={tab==='focus'?()=>setFocusNode(null):undefined}>
        {tab==='data'?<DataView edges={visEdges} graph={graph}/>:<ForceGraph nodes={visNodes} edges={visEdges} focusNode={focusNode} onNodeClick={tab==='focus'?setFocusNode:undefined}/>}
      </div>

      <div style={{display:'flex',gap:16,fontSize:11,color:'#666',marginTop:4,flexWrap:'wrap'}}>
        <span><strong>节点:</strong></span>
        <span><span style={{color:'#3b82f6'}}>●</span> 脑区</span>
        <span><span style={{color:'#f59e0b'}}>●</span> 回路</span>
        <span><span style={{color:'#10b981'}}>●</span> 连接</span>
        <span style={{marginLeft:8}}><strong>边:</strong></span>
        <span>─ 结构连接</span>
        <span style={{borderBottom:'2px dashed #f59e0b'}}>--- 功能连接</span>
        <span style={{borderBottom:'2px dotted #10b981'}}>··· 投射</span>
        <span style={{color:'#fcd34d'}}>─ 回路起止</span>
        <span style={{borderBottom:'2px dashed #c4b5fd'}}>--- 回路包含</span>
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
      <tbody>{edges.slice(0,200).map(e=><tr key={e.id}><td style={td}>{nm.get(e.source)||e.source.slice(0,12)}</td><td style={td}>{nm.get(e.target)||e.target.slice(0,12)}</td><td style={td}>{e.type}</td><td style={td}>{(e.confidence*100).toFixed(0)}%</td><td style={{...td,maxWidth:160,overflow:'hidden',textOverflow:'ellipsis'}}>{e.label}</td></tr>)}</tbody>
    </table>
  </div>
}
const th: React.CSSProperties = { padding: '4px 8px', textAlign: 'left', borderBottom: '2px solid #e5e7eb', position: 'sticky', top: 0, background: '#f1f5f9' }
const td: React.CSSProperties = { padding: '3px 8px', borderBottom: '1px solid #f3f4f6', whiteSpace: 'nowrap' }

// ── Force Graph ─────────────────────────────────────────────────────────────

function ForceGraph({ nodes: _nodes, edges: _edges, focusNode, onNodeClick }: { nodes: GNode[]; edges: GEdge[]; focusNode: string | null; onNodeClick?: (id: string) => void }) {
  const ref = useRef<HTMLDivElement>(null)

  // Rebuild node set from edges: ensure every edge endpoint has a node
  const { nodes, edges } = useMemo(() => {
    const nm = new Map<string, GNode>()
    for (const n of _nodes) nm.set(n.id, n)
    // Add missing endpoint nodes from connection edges
    for (const e of _edges) {
      if (!nm.has(e.source) && e.type !== 'STARTS_AT' && e.type !== 'ENDS_AT' && e.type !== 'INCLUDES') {
        nm.set(e.source, { id: e.source, type: 'connection', group: 'connection', label: e.source.slice(0, 12), name_en: '', name_cn: '', atlas: '' })
      }
      if (!nm.has(e.target) && e.type !== 'STARTS_AT' && e.type !== 'ENDS_AT' && e.type !== 'INCLUDES') {
        nm.set(e.target, { id: e.target, type: 'connection', group: 'connection', label: e.target.slice(0, 12), name_en: '', name_cn: '', atlas: '' })
      }
    }
    // Filter edges: only keep those where both ends are in the node map
    const validEdges = _edges.filter(e => nm.has(e.source) && nm.has(e.target))
    return { nodes: [...nm.values()], edges: validEdges }
  }, [_nodes, _edges])

  useEffect(() => {
    const el = ref.current; if (!el || nodes.length === 0) return
    const W = el.clientWidth || 1000; const H = el.clientHeight || 700
    d3.select(el).html('')

    // Simple canvas-based approach for large data: limit rendering
    const maxRender = 2000
    const renderNodes = nodes.slice(0, maxRender)
    const renderEdges = edges.filter(e => renderNodes.find(n => n.id === e.source) && renderNodes.find(n => n.id === e.target)).slice(0, maxRender)

    if (nodes.length > maxRender) {
      d3.select(el).append('div').style('padding', '20px').style('color', '#888').style('textAlign', 'center')
        .text(`大数据集：${nodes.length} 节点, ${edges.length} 边。渲染前 ${maxRender} 条。`)
    }

    setTimeout(() => {
      d3.select(el).html('')
      drawGraph(el, renderNodes, renderEdges, W, H, focusNode, onNodeClick)
    }, 10)

    return () => {}
  }, [nodes.length, edges.length, focusNode])

  return <div ref={ref} style={{ width: '100%', height: '100%' }} />
}

function drawGraph(el: HTMLDivElement, nodes: GNode[], edges: GEdge[], W: number, H: number, focusNode: string | null, onNodeClick?: (id: string) => void) {
  const svg = d3.select(el).append('svg').attr('width', W).attr('height', H)
  const g = svg.append('g')
  svg.call(d3.zoom<SVGSVGElement, unknown>().scaleExtent([0.05, 5]).on('zoom', (ev) => g.attr('transform', ev.transform)))

  nodes.forEach((n: any) => { n.x = W / 2 + (Math.random() - 0.5) * W * 0.8; n.y = H / 2 + (Math.random() - 0.5) * H * 0.8 })

  const link = g.append('g').selectAll('line').data(edges).join('line')
    .attr('stroke', (d: any) => EDGE_COLOR[d.type] || '#d1d5db')
    .attr('stroke-width', (d: any) => Math.max(0.3, (d.confidence || 0.3) * 1.5))
    .attr('stroke-opacity', (d: any) => Math.min(0.7, 0.15 + (d.confidence || 0.3)))
    .attr('stroke-dasharray', (d: any) => EDGE_DASH[d.type] || '')

  const ng = g.append('g').selectAll('g').data(nodes).join('g')
    .attr('cursor', 'pointer')
    .on('click', (ev: any, d: any) => { ev.stopPropagation(); onNodeClick?.(d.id) })
  ng.append('circle')
    .attr('r', (d: any) => d.id === focusNode ? 10 : (NODE_R[d.type] || 4))
    .attr('fill', (d: any) => d.id === focusNode ? '#ef4444' : (NODE_COLOR[d.type] || '#999'))
    .attr('stroke', '#fff').attr('stroke-width', 1)
  ng.append('text').text((d: any) => (d.label || '').slice(0, 10)).attr('dx', 9).attr('dy', 4).style('font-size', '7px').style('fill', '#555')
  ng.append('title').text((d: any) => `${d.type}: ${d.label}`)
  link.append('title').text((d: any) => `${d.type} | ${((d.confidence||0)*100).toFixed(0)}%\n${d.label}`)

  const sim = d3.forceSimulation(nodes as any)
    .force('link', d3.forceLink(edges).id((d: any) => d.id).distance(30))
    .force('charge', d3.forceManyBody().strength(-60))
    .force('center', d3.forceCenter(W / 2, H / 2))
    .force('collision', d3.forceCollide(6))
    .on('tick', () => {
      link.attr('x1', (d: any) => d.source.x).attr('y1', (d: any) => d.source.y).attr('x2', (d: any) => d.target.x).attr('y2', (d: any) => d.target.y)
      ng.attr('transform', (d: any) => `translate(${d.x},${d.y})`)
    })

  ng.call(d3.drag<SVGGElement, any>()
    .on('start', (ev: any, d: any) => { if (!ev.active) sim.alphaTarget(0.3).restart(); d.fx = d.x; d.fy = d.y })
    .on('drag', (ev: any, d: any) => { d.fx = ev.x; d.fy = ev.y })
    .on('end', (ev: any, d: any) => { if (!ev.active) sim.alphaTarget(0); d.fx = null; d.fy = null }) as any)
}
