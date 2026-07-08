import React, { useCallback, useEffect, useMemo, useRef, useState } from 'react'
import * as d3 from 'd3'

// ── Types ───────────────────────────────────────────────────────────────────

interface RawNode { id: string; type: string; label: string; group: string; name_en?: string; name_cn?: string; laterality?: string }
interface RawEdge { id: string; source: string; target: string; type: string; confidence: number; strength?: number; verification?: string; source_name?: string; target_name?: string }

interface NormNode { id: string; type: string; label: string; group: string; name_en: string; name_cn: string; atlas: string }
interface NormEdge { id: string; source: string; target: string; type: string; confidence: number; label: string; evidence: string }
interface GraphData { nodes: RawNode[]; edges: RawEdge[]; stats: Record<string, number> }

// ── Constants ───────────────────────────────────────────────────────────────

const NODE_COLORS: Record<string, string> = { region: '#3b82f6', circuit: '#f59e0b', connection: '#10b981' }
const NODE_SIZES: Record<string, number> = { region: 7, circuit: 6, connection: 3 }
const EDGE_COLORS: Record<string, string> = {
  structural_connection: '#3b82f6', functional_connectivity: '#f59e0b',
  projection: '#10b981', association: '#8b5cf6', coactivation: '#ec4899',
  effective_connectivity: '#ef4444', uncertain_connection: '#9ca3af', unknown: '#d1d5db',
  STARTS_AT: '#fcd34d', ENDS_AT: '#f87171', INCLUDES: '#c4b5fd',
  SOURCE_OF: '#93c5fd', TARGET_OF: '#fca5a5',
}
const EDGE_DASH: Record<string, string> = {
  structural_connection: '', functional_connectivity: '6,3', projection: '2,2',
  effective_connectivity: '', association: '4,4', coactivation: '2,4',
  STARTS_AT: '4,2', ENDS_AT: '4,2', INCLUDES: '6,3',
}

// ── Normalize ───────────────────────────────────────────────────────────────

function normalizeGraph(raw: GraphData): { nodes: NormNode[]; edges: NormEdge[] } {
  const nodeMap = new Map<string, NormNode>()

  // Normalize nodes
  for (const n of raw.nodes) {
    nodeMap.set(n.id, {
      id: n.id, type: n.type, group: n.group,
      label: n.name_en || n.name_cn || n.label || n.id.slice(0, 8),
      name_en: n.name_en || '', name_cn: n.name_cn || '', atlas: 'Macro96',
    })
  }

  // Normalize edges: resolve all possible source/target field names
  const normEdges: NormEdge[] = []
  for (const e of raw.edges) {
    const src = (e as any).source || (e as any).source_id || (e as any).source_region_id || (e as any).from || ''
    const tgt = (e as any).target || (e as any).target_id || (e as any).target_region_id || (e as any).to || ''
    const ctype = e.type || 'unknown'
    const srcName = (e as any).source_name || ''
    const tgtName = (e as any).target_name || ''
    normEdges.push({
      id: e.id, source: String(src), target: String(tgt),
      type: ctype, confidence: e.confidence || 0.3,
      label: srcName && tgtName ? `${srcName} → ${tgtName}` : `${String(src).slice(0,8)}→${String(tgt).slice(0,8)}`,
      evidence: e.type || '',
    })

    // Also create connection nodes from edges that represent connections
    if (!nodeMap.has(e.id) && ctype !== 'STARTS_AT' && ctype !== 'ENDS_AT' && ctype !== 'INCLUDES') {
      nodeMap.set(e.id, {
        id: e.id, type: 'connection', group: 'connection',
        label: `${srcName.slice(0, 15) || '?'} → ${tgtName.slice(0, 15) || '?'}`,
        name_en: '', name_cn: '', atlas: 'Macro96',
      })
    }
  }

  return { nodes: [...nodeMap.values()], edges: normEdges }
}

// ── Main Page ───────────────────────────────────────────────────────────────

export function GraphExplorerPage() {
  const [tab, setTab] = useState<'focus' | 'global' | 'data'>('global')
  const [raw, setRaw] = useState<GraphData | null>(null)
  const [loading, setLoading] = useState(true)
  const [search, setSearch] = useState('')
  const [filterType, setFilterType] = useState('all')
  const [minConf, setMinConf] = useState(0)
  const [focusNode, setFocusNode] = useState<string | null>(null)

  useEffect(() => {
    fetch('/api/kg/graph/data?limit_connections=5000&include_circuits=true')
      .then(r => r.json()).then(d => { setRaw(d); setLoading(false) })
      .catch(() => setLoading(false))
  }, [])

  const [graphError, setGraphError] = useState<string | null>(null)
  const graph = useMemo(() => {
    if (!raw) return null
    try { return normalizeGraph(raw) }
    catch (e: any) { setGraphError(e.message); return null }
  }, [raw])

  // Visible edges: apply type + confidence filters
  const visibleEdges = useMemo(() => {
    if (!graph) return []
    return graph.edges.filter(e => {
      if (filterType !== 'all' && e.type !== filterType) return false
      if (e.confidence < minConf) return false
      return true
    })
  }, [graph, filterType, minConf])

  // Visible nodes: nodes connected to visible edges + orphans
  const visibleNodes = useMemo(() => {
    if (!graph) return []
    const connected = new Set<string>()
    for (const e of visibleEdges) { connected.add(e.source); connected.add(e.target) }
    // Focus mode: only 1-hop from focusNode
    if (tab === 'focus' && focusNode) {
      const hop = new Set<string>([focusNode])
      for (const e of visibleEdges) {
        if (e.source === focusNode) hop.add(e.target)
        if (e.target === focusNode) hop.add(e.source)
      }
      return graph.nodes.filter(n => hop.has(n.id))
    }
    // Search filter
    let nodes = graph.nodes.filter(n => connected.has(n.id) || n.type === 'region')
    if (search) nodes = nodes.filter(n => n.label.toLowerCase().includes(search.toLowerCase()))
    return nodes
  }, [graph, visibleEdges, tab, focusNode, search])

  const handleBgClick = useCallback(() => setFocusNode(null), [])

  if (loading) return <div style={{ padding: 40, color: '#888' }}>加载图谱数据…</div>
  if (graphError) return <div style={{ padding: 40, color: '#dc2626' }}>图谱数据错误: {graphError}</div>

  return (
    <div style={{ padding: 16, height: 'calc(100vh - 60px)', display: 'flex', flexDirection: 'column' }}>
      {/* Header */}
      <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: 8 }}>
        <div>
          <h2 style={{ margin: 0, fontSize: 18 }}>🧠 图谱探索</h2>
          <p style={{ color: '#888', fontSize: 12, margin: '2px 0 0' }}>
            {raw ? `${raw.stats.regions} 脑区 · ${raw.stats.connections} 连接 · ${raw.stats.circuits} 回路 · ${raw.stats.memberships} 映射` : ''}
          </p>
        </div>
        <div style={{ display: 'flex', gap: 4 }}>
          {(['focus', 'global', 'data'] as const).map(t => (
            <button key={t} className={`btn btn-sm${tab === t ? ' btn-primary' : ''}`} onClick={() => setTab(t)}>
              {t === 'focus' ? '🔍 聚焦' : t === 'global' ? '🌐 全局' : '📊 数据'}
            </button>
          ))}
        </div>
      </div>

      {/* Debug bar */}
      <div style={{ fontSize: 11, color: '#666', marginBottom: 4, display: 'flex', gap: 12 }}>
        <span>节点: {visibleNodes.length} / {graph?.nodes.length || 0}</span>
        <span>边: {visibleEdges.length} / {graph?.edges.length || 0}</span>
        {graph && graph.edges.length > 0 && visibleEdges.length === 0 && (
          <span style={{ color: '#dc2626' }}>⚠️ 当前筛选条件下无可见连线，请检查关系类型或置信度阈值</span>
        )}
      </div>

      {/* Filters */}
      <div style={{ display: 'flex', gap: 8, marginBottom: 8 }}>
        {tab === 'focus' && (
          <input className="form-input" placeholder="搜索脑区名称…" value={search}
            onChange={e => setSearch(e.target.value)} style={{ width: 180, fontSize: 12 }} />
        )}
        <select className="form-input" value={filterType} onChange={e => setFilterType(e.target.value)} style={{ width: 150, fontSize: 12 }}>
          <option value="all">全部关系</option>
          <option value="structural_connection">结构连接</option>
          <option value="functional_connectivity">功能连接</option>
          <option value="projection">投射</option>
          <option value="STARTS_AT">回路起点</option>
          <option value="ENDS_AT">回路终点</option>
          <option value="INCLUDES">回路包含</option>
        </select>
        <label style={{ fontSize: 11, display: 'flex', alignItems: 'center', gap: 4 }}>
          置信度≥{minConf.toFixed(1)}
          <input type="range" min={0} max={100} value={Math.round(minConf * 100)} style={{ width: 64 }}
            onChange={e => setMinConf(Number(e.target.value) / 100)} />
        </label>
        {tab === 'focus' && focusNode && (
          <button className="btn btn-sm" onClick={() => setFocusNode(null)}>清除聚焦</button>
        )}
      </div>

      {/* Canvas / Data */}
      <div style={{ flex: 1, border: '1px solid var(--border)', borderRadius: 8, overflow: 'hidden', background: '#f8fafc' }}
        onClick={tab === 'focus' ? handleBgClick : undefined}>
        {tab === 'data' ? (
          <EdgeTable edges={visibleEdges} nodes={graph?.nodes || []} />
        ) : (
          <ForceGraph
            nodes={visibleNodes}
            edges={visibleEdges}
            focusMode={tab === 'focus'}
            focusNode={focusNode}
            onNodeClick={tab === 'focus' ? setFocusNode : undefined}
          />
        )}
      </div>

      {/* Legend */}
      <div style={{ display: 'flex', gap: 16, fontSize: 11, color: '#666', marginTop: 4, flexWrap: 'wrap' }}>
        <span><strong>节点:</strong></span>
        <span><span style={{ color: '#3b82f6' }}>●</span> 脑区</span>
        <span><span style={{ color: '#f59e0b' }}>●</span> 回路</span>
        <span><span style={{ color: '#10b981' }}>●</span> 连接</span>
        <span style={{ marginLeft: 8 }}><strong>边:</strong></span>
        <span><span style={{ color: '#3b82f6' }}>─</span> 结构连接</span>
        <span><span style={{ color: '#f59e0b', borderBottom: '2px dashed #f59e0b' }}>---</span> 功能连接</span>
        <span><span style={{ color: '#10b981', borderBottom: '2px dotted #10b981' }}>···</span> 投射</span>
        <span><span style={{ color: '#fcd34d' }}>─</span> 回路起止</span>
        <span><span style={{ color: '#c4b5fd', borderBottom: '2px dashed #c4b5fd' }}>---</span> 回路包含</span>
      </div>
    </div>
  )
}

// ── Edge Table ──────────────────────────────────────────────────────────────

function EdgeTable({ edges, nodes }: { edges: NormEdge[]; nodes: NormNode[] }) {
  const nameMap = useMemo(() => {
    const m = new Map<string, string>()
    for (const n of nodes) m.set(n.id, n.label)
    return m
  }, [nodes])
  return (
    <div style={{ padding: 8, overflow: 'auto', height: '100%', fontSize: 11 }}>
      <table style={{ width: '100%', borderCollapse: 'collapse' }}>
        <thead><tr style={{ background: '#f1f5f9' }}>
          <th style={th}>source</th><th style={th}>target</th><th style={th}>type</th><th style={th}>conf</th><th style={th}>label</th>
        </tr></thead>
        <tbody>
          {edges.slice(0, 200).map(e => (
            <tr key={e.id}>
              <td style={td} title={e.source}>{nameMap.get(e.source) || e.source.slice(0, 12)}</td>
              <td style={td} title={e.target}>{nameMap.get(e.target) || e.target.slice(0, 12)}</td>
              <td style={td}>{e.type}</td>
              <td style={td}>{(e.confidence * 100).toFixed(0)}%</td>
              <td style={{ ...td, maxWidth: 160, overflow: 'hidden', textOverflow: 'ellipsis' }}>{e.label}</td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  )
}
const th: React.CSSProperties = { padding: '4px 8px', textAlign: 'left', borderBottom: '2px solid #e5e7eb', position: 'sticky', top: 0, background: '#f1f5f9' }
const td: React.CSSProperties = { padding: '3px 8px', borderBottom: '1px solid #f3f4f6', whiteSpace: 'nowrap' }

// ── Force Graph ─────────────────────────────────────────────────────────────

function ForceGraph({ nodes, edges, focusMode, focusNode, onNodeClick }: {
  nodes: NormNode[]; edges: NormEdge[]; focusMode: boolean
  focusNode: string | null; onNodeClick?: (id: string) => void
}) {
  const containerRef = useRef<HTMLDivElement>(null)

  useEffect(() => {
    const container = containerRef.current
    if (!container || nodes.length === 0) return
    const W = container.clientWidth || 1000
    const H = container.clientHeight || 700

    d3.select(container).html('')

    // Show placeholders while large datasets load
    if (nodes.length > 500 || edges.length > 2000) {
      d3.select(container).append('div').style('padding', '20px').style('color', '#888')
        .text(`渲染中… ${nodes.length} 节点, ${edges.length} 边`)
    }

    // Render with a small delay to avoid blocking UI
    let sim: d3.Simulation<any, any> | null = null
    const timer = setTimeout(() => {
      d3.select(container).html('')
      sim = renderGraph(container, nodes, edges, W, H, focusNode, onNodeClick)
    }, 50)

    return () => { clearTimeout(timer); sim?.stop() }
  }, [nodes.length, edges.length, focusNode])

  return <div ref={containerRef} style={{ width: '100%', height: '100%' }} />
}

function renderGraph(
  container: HTMLDivElement, nodes: NormNode[], edges: NormEdge[],
  W: number, H: number, focusNode: string | null,
  onNodeClick?: (id: string) => void,
) {
    const svg = d3.select(container).append('svg').attr('width', W).attr('height', H)
    const g = svg.append('g')

    svg.call(d3.zoom<SVGSVGElement, unknown>().scaleExtent([0.05, 5]).on('zoom', (ev) => g.attr('transform', ev.transform)))

    // Links
    const link = g.append('g').selectAll('line').data(edges).join('line')
      .attr('stroke', (d: any) => EDGE_COLORS[d.type] || '#d1d5db')
      .attr('stroke-width', (d: any) => Math.max(0.5, (d.confidence || 0.3) * 2))
      .attr('stroke-opacity', (d: any) => Math.min(0.9, 0.3 + (d.confidence || 0.3)))
      .attr('stroke-dasharray', (d: any) => EDGE_DASH[d.type] || '')
      .attr('style', 'pointer-events: none')
    link.append('title').text((d: any) => `${d.type} | conf:${((d.confidence||0)*100).toFixed(0)}%\n${d.label}`)

    // Nodes
    const nodeG = g.append('g').selectAll('g').data(nodes).join('g')
      .attr('cursor', 'pointer')
      .on('click', (ev: any, d: any) => { ev.stopPropagation(); onNodeClick?.(d.id) })

    nodeG.append('circle')
      .attr('r', (d: any) => NODE_SIZES[d.type] || 4)
      .attr('fill', (d: any) => NODE_COLORS[d.type] || '#999')
      .attr('stroke', '#fff').attr('stroke-width', 1.5)

    nodeG.append('text')
      .text((d: any) => (d.label || '').slice(0, 12))
      .attr('dx', 9).attr('dy', 4)
      .style('font-size', '8px').style('fill', '#555').style('pointer-events', 'none')

    nodeG.append('title').text((d: any) => `${d.type}: ${d.label}\n${d.name_en || ''} ${d.name_cn || ''}`)

    // Init positions
    nodes.forEach((n: any, i: number) => {
      n.x = W / 2 + (Math.random() - 0.5) * W * 0.8
      n.y = H / 2 + (Math.random() - 0.5) * H * 0.8
    })

    // Highlight focused node
    if (focusNode) {
      nodeG.selectAll('circle')
        .attr('fill', (d: any) => d.id === focusNode ? '#ef4444' : NODE_COLORS[d.type] || '#999')
        .attr('r', (d: any) => d.id === focusNode ? 10 : (NODE_SIZES[d.type] || 4))
    }

    const sim = d3.forceSimulation(nodes as any)
      .force('link', d3.forceLink(edges).id((d: any) => d.id).distance(50))
      .force('charge', d3.forceManyBody().strength(-120))
      .force('center', d3.forceCenter(W / 2, H / 2))
      .force('collision', d3.forceCollide(8))
      .on('tick', () => {
        link.attr('x1', (d: any) => d.source.x).attr('y1', (d: any) => d.source.y)
            .attr('x2', (d: any) => d.target.x).attr('y2', (d: any) => d.target.y)
        nodeG.attr('transform', (d: any) => `translate(${d.x},${d.y})`)
      })

    // Drag
    nodeG.call(d3.drag<SVGGElement, any>()
      .on('start', (ev: any, d: any) => { if (!ev.active) sim.alphaTarget(0.3).restart(); d.fx = d.x; d.fy = d.y })
      .on('drag', (ev: any, d: any) => { d.fx = ev.x; d.fy = ev.y })
      .on('end', (ev: any, d: any) => { if (!ev.active) sim.alphaTarget(0); d.fx = null; d.fy = null }) as any)

    return sim
  }

  return <div ref={containerRef} style={{ width: '100%', height: '100%' }} />
}
