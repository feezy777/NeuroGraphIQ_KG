import { useEffect, useRef, useState } from 'react'
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
  STARTS_AT: '#f59e0b', ENDS_AT: '#ef4444', INCLUDES: '#8b5cf6',
}

export function GraphExplorerPage() {
  const [tab, setTab] = useState<'focus' | 'global' | 'data'>('global')
  const [data, setData] = useState<GraphData | null>(null)
  const [loading, setLoading] = useState(true)
  const [search, setSearch] = useState('')
  const [filterType, setFilterType] = useState('all')
  const [minConf, setMinConf] = useState(0)

  useEffect(() => {
    fetch('/api/kg/graph/data?limit_connections=200&include_circuits=true')
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
        ) : (
          <ForceGraph nodes={filtered?.nodes || []} edges={filtered?.edges || []} focusMode={tab === 'focus'} />
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

function ForceGraph({ nodes, edges, focusMode }: { nodes: GraphNode[]; edges: GraphEdge[]; focusMode: boolean }) {
  const ref = useRef<HTMLDivElement>(null)

  useEffect(() => {
    if (!ref.current || nodes.length === 0) return
    const w = ref.current.clientWidth
    const h = ref.current.clientHeight

    const svg = d3.select(ref.current).html('').append('svg').attr('width', w).attr('height', h)
    const g = svg.append('g')

    const zoom = d3.zoom<SVGSVGElement, unknown>().scaleExtent([0.1, 4]).on('zoom', (ev) => g.attr('transform', ev.transform))
    svg.call(zoom)

    const link = g.append('g').selectAll('line').data(edges).join('line')
      .attr('stroke', d => COLORS[d.type] || '#999')
      .attr('stroke-opacity', d => Math.min(1, (d.confidence || 0.3) + 0.3))
      .attr('stroke-width', d => Math.max(0.5, (d.confidence || 0.3) * 2))

    const node = g.append('g').selectAll('circle').data(nodes).join('circle')
      .attr('r', d => d.type === 'region' ? 6 : d.type === 'circuit' ? 5 : 3)
      .attr('fill', d => COLORS[d.type] || '#999')
      .attr('stroke', '#fff').attr('stroke-width', 1)
      .call(d3.drag<SVGCircleElement, GraphNode>()
        .on('start', (ev, d) => { if (!ev.active) sim.alphaTarget(0.3).restart(); d.fx = d.x; d.fy = d.y })
        .on('drag', (ev, d) => { d.fx = ev.x; d.fy = ev.y })
        .on('end', (ev, d) => { if (!ev.active) sim.alphaTarget(0); d.fx = null; d.fy = null }))

    node.append('title').text(d => `${d.type}: ${d.label}`)

    const sim = d3.forceSimulation(nodes as any)
      .force('link', d3.forceLink(edges).id((d: any) => d.id).distance(60))
      .force('charge', d3.forceManyBody().strength(focusMode ? -200 : -80))
      .force('center', d3.forceCenter(w / 2, h / 2))
      .force('collision', d3.forceCollide(10))
      .on('tick', () => {
        link.attr('x1', (d: any) => d.source.x).attr('y1', (d: any) => d.source.y)
            .attr('x2', (d: any) => d.target.x).attr('y2', (d: any) => d.target.y)
        node.attr('cx', (d: any) => d.x).attr('cy', (d: any) => d.y)
      })

    return () => { sim.stop() }
  }, [nodes, edges, focusMode, ref.current?.clientWidth, ref.current?.clientHeight])

  return <div ref={ref} style={{ width: '100%', height: '100%' }} />
}
