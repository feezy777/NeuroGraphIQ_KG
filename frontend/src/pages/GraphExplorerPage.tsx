import React, { useEffect, useRef, useState } from 'react'
import * as d3 from 'd3'

interface GraphNode {
  id: string; type: string; label: string; group: string
  name_en?: string; name_cn?: string
}

interface GraphEdge {
  id: string; source: string; target: string; type: string; confidence: number
  verification?: string
}

interface GraphData { nodes: GraphNode[]; edges: GraphEdge[]; stats: Record<string, number> }

const COLORS: Record<string, string> = {
  region: '#3b82f6', circuit: '#f59e0b', connection: '#10b981',
  SOURCE_OF: '#93c5fd', TARGET_OF: '#fca5a5',
  STARTS_AT: '#fcd34d', ENDS_AT: '#f87171', INCLUDES: '#c4b5fd',
}

const NODE_SIZES: Record<string, number> = {
  region: 7, circuit: 5, connection: 3,
}

export function GraphExplorerPage() {
  const [tab, setTab] = useState<'focus' | 'global' | 'data'>('global')
  const [data, setData] = useState<GraphData | null>(null)
  const [loading, setLoading] = useState(true)
  const [search, setSearch] = useState('')
  const [filterType, setFilterType] = useState('all')
  const [minConf, setMinConf] = useState(0)

  useEffect(() => {
    fetch('/api/kg/graph/data?limit_connections=500&include_circuits=true')
      .then(r => r.json()).then(d => { setData(d); setLoading(false) })
      .catch(() => setLoading(false))
  }, [])

  const filtered = data ? {
    nodes: data.nodes.filter(n => {
      if (tab === 'focus' && search) return n.label.toLowerCase().includes(search.toLowerCase())
      if (tab === 'focus' && n.type !== 'region') return false
      return true
    }),
    edges: data.edges.filter(e => {
      if (filterType !== 'all' && e.type !== filterType) return false
      if (e.confidence < minConf) return false
      return true
    }),
  } : null

  return (
    <div style={{ padding: 24, height: 'calc(100vh - 60px)', display: 'flex', flexDirection: 'column' }}>
      <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: 16 }}>
        <div>
          <h2 style={{ margin: 0 }}>🧠 图谱探索</h2>
          <p style={{ color: '#888', fontSize: 13, margin: '4px 0 0' }}>
            {data ? `${data.stats.regions} 脑区 · ${data.stats.connections} 连接 · ${data.stats.circuits} 回路 · ${data.stats.memberships} 映射` : '加载中…'}
          </p>
        </div>
        <div style={{ display: 'flex', gap: 4 }}>
          {(['focus', 'global', 'data'] as const).map(t => (
            <button key={t} className={`btn${tab === t ? ' btn-primary' : ''}`} onClick={() => setTab(t)}>
              {t === 'focus' ? '🔍 聚焦' : t === 'global' ? '🌐 全局' : '📊 数据'}
            </button>
          ))}
        </div>
      </div>

      <div style={{ display: 'flex', gap: 8, marginBottom: 12 }}>
        {tab === 'focus' && (
          <input className="form-input" placeholder="搜索脑区名称…" value={search}
            onChange={e => setSearch(e.target.value)} style={{ width: 200 }} />
        )}
        <select className="form-input" value={filterType} onChange={e => setFilterType(e.target.value)} style={{ width: 140 }}>
          <option value="all">全部关系</option>
          <option value="SOURCE_OF">SOURCE_OF</option>
          <option value="TARGET_OF">TARGET_OF</option>
          <option value="INCLUDES">INCLUDES</option>
          <option value="STARTS_AT">STARTS_AT</option>
          <option value="ENDS_AT">ENDS_AT</option>
        </select>
        <label style={{ fontSize: 12, display: 'flex', alignItems: 'center', gap: 4 }}>
          置信度≥{minConf}
          <input type="range" min={0} max={100} value={minConf * 100} style={{ width: 80 }}
            onChange={e => setMinConf(Number(e.target.value) / 100)} />
        </label>
      </div>

      <div style={{ flex: 1, border: '1px solid var(--border)', borderRadius: 8, overflow: 'hidden', background: '#f8fafc' }}>
        {loading ? (
          <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'center', height: '100%', color: '#888' }}>
            加载中…
          </div>
        ) : tab === 'data' ? (
          <DataView data={data} />
        ) : filtered && filtered.nodes.length > 0 ? (
          <GraphErrorBoundary>
            <ForceGraph nodes={filtered.nodes} edges={filtered.edges} focusMode={tab === 'focus'} />
          </GraphErrorBoundary>
        ) : (
          <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'center', height: '100%', color: '#888' }}>
            暂无数据 — 请检查后端 /api/kg/graph/data 是否可用
          </div>
        )}
      </div>
    </div>
  )
}

function DataView({ data }: { data: GraphData | null }) {
  if (!data) return null
  return (
    <div style={{ padding: 16, overflow: 'auto', height: '100%' }}>
      <h3>图统计</h3>
      <table className="data-center-field-completion-items" style={{ fontSize: 13 }}>
        <tbody>
          {Object.entries(data.stats).map(([k, v]) => (
            <tr key={k}><td><strong>{k}</strong></td><td>{v}</td></tr>
          ))}
        </tbody>
      </table>
      <h3 style={{ marginTop: 16 }}>脑区 (前 20)</h3>
      <table className="data-center-field-completion-items" style={{ fontSize: 12 }}>
        <thead><tr><th>ID</th><th>EN</th><th>CN</th></tr></thead>
        <tbody>
          {data.nodes.filter(n => n.type === 'region').slice(0, 20).map(n => (
            <tr key={n.id}><td><code>{n.id.slice(0, 10)}</code></td><td>{n.name_en}</td><td>{n.name_cn}</td></tr>
          ))}
        </tbody>
      </table>
    </div>
  )
}

class GraphErrorBoundary extends React.Component<{ children: React.ReactNode }, { error: Error | null }> {
  state = { error: null as Error | null }
  static getDerivedStateFromError(e: Error) { return { error: e } }
  render() {
    if (this.state.error) return <div style={{ padding: 40, color: '#dc2626' }}>图谱渲染错误: {this.state.error.message}</div>
    return this.props.children
  }
}

function ForceGraph({ nodes, edges, focusMode }: { nodes: GraphNode[]; edges: GraphEdge[]; focusMode: boolean }) {
  const containerRef = useRef<HTMLDivElement>(null)
  const svgRef = useRef<SVGSVGElement | null>(null)

  useEffect(() => {
    const container = containerRef.current
    if (!container || nodes.length === 0) return
    const w = container.clientWidth || 800
    const h = container.clientHeight || 600

    // Clear previous
    d3.select(container).html('')
    const svg = d3.select(container).append('svg').attr('width', w).attr('height', h)
    svgRef.current = svg.node()
    const g = svg.append('g')

    const zoom = d3.zoom<SVGSVGElement, unknown>().scaleExtent([0.1, 4]).on('zoom', (ev) => g.attr('transform', ev.transform))
    svg.call(zoom)

    // Only keep region nodes + non-membership edges for clean visualization
    const regionNodes = nodes.filter(n => n.type === 'region')
    const circuitNodes = nodes.filter(n => n.type === 'circuit').slice(0, 20)  // limit circuits
    const allNodes = [...regionNodes, ...circuitNodes]
    const nodeIds = new Set(allNodes.map(n => n.id))

    // Keep only edges where both ends are regions or circuits
    const validEdges = edges.filter(e => {
      if (e.type === 'INCLUDES') return false  // skip membership edges (need connection nodes)
      return nodeIds.has(e.source) && nodeIds.has(e.target)
    })

    // Initialize positions
    allNodes.forEach((n: any) => { n.x = w / 2 + (Math.random() - 0.5) * 100; n.y = h / 2 + (Math.random() - 0.5) * 100 })

    const link = g.append('g').selectAll('line').data(validEdges).join('line')
      .attr('stroke', (d: any) => COLORS[d.type] || '#999')
      .attr('stroke-opacity', (d: any) => Math.min(1, (d.confidence || 0.3) + 0.3))
      .attr('stroke-width', (d: any) => Math.max(0.5, (d.confidence || 0.3) * 2))

    const nodeGroup = g.append('g').selectAll('g').data(allNodes).join('g')
    nodeGroup.append('circle')
      .attr('r', (d: any) => NODE_SIZES[d.type] || 4)
      .attr('fill', (d: any) => COLORS[d.type] || '#999')
      .attr('stroke', '#fff').attr('stroke-width', 1)
    nodeGroup.append('text')
      .text((d: any) => d.label.slice(0, 15))
      .attr('dx', 8).attr('dy', 4)
      .style('font-size', '9px')
      .style('fill', '#333')
      .style('pointer-events', 'none')

    nodeGroup.append('title').text((d: any) => `${d.type}: ${d.label}`)

    const sim = d3.forceSimulation(allNodes as any)
      .force('link', d3.forceLink(validEdges).id((d: any) => d.id).distance(60))
      .force('charge', d3.forceManyBody().strength(focusMode ? -200 : -80))
      .force('center', d3.forceCenter(w / 2, h / 2))
      .force('collision', d3.forceCollide(10))
      .on('tick', () => {
        link.attr('x1', (d: any) => d.source.x).attr('y1', (d: any) => d.source.y)
            .attr('x2', (d: any) => d.target.x).attr('y2', (d: any) => d.target.y)
        nodeGroup.attr('transform', (d: any) => `translate(${d.x},${d.y})`)
      })

    const drag = d3.drag<SVGGElement, any>()
      .on('start', (ev: any, d: any) => { if (!ev.active) sim.alphaTarget(0.3).restart(); d.fx = d.x; d.fy = d.y })
      .on('drag', (ev: any, d: any) => { d.fx = ev.x; d.fy = ev.y })
      .on('end', (ev: any, d: any) => { if (!ev.active) sim.alphaTarget(0); d.fx = null; d.fy = null })
    nodeGroup.call(drag as any)

    return () => { sim.stop() }
  }, [nodes.length, edges.length, focusMode])  // stable deps — only re-run when data changes

  return <div ref={containerRef} style={{ width: '100%', height: '100%' }} />
}
