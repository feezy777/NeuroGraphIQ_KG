import { useMemo, useRef, useEffect } from 'react'
import * as d3 from 'd3'

// ── Types ───────────────────────────────────────────────────────────────────

export interface GNode {
  id: string
  type: string
  label: string
  name_en?: string
  name_cn?: string
  [key: string]: any
}

export interface GEdge {
  id: string
  source: string
  target: string
  type: string
  label?: string
  confidence?: number
}

export interface LegendItem {
  color: string
  dash: string
  label: string
}

// ── Default Color / Dash / Radius Maps ──────────────────────────────────────
// (Copied from GraphExplorerPage so callers can override by passing props)

export const NODE_COLOR: Record<string, string> = {
  region: '#3b82f6',
  circuit: '#f59e0b',
  connection: '#10b981',
}
export const NODE_R: Record<string, number> = {
  region: 7,
  circuit: 6,
  connection: 3,
}
export const EDGE_COLOR: Record<string, string> = {
  structural_connection: '#3b82f6',
  functional_connectivity: '#f59e0b',
  projection: '#10b981',
  association: '#8b5cf6',
  coactivation: '#ec4899',
  effective_connectivity: '#ef4444',
  uncertain_connection: '#9ca3af',
  unknown: '#d1d5db',
  STARTS_AT: '#fcd34d',
  ENDS_AT: '#f87171',
  INCLUDES: '#c4b5fd',
}
export const EDGE_DASH: Record<string, string> = {
  structural_connection: '',
  functional_connectivity: '6,3',
  projection: '2,2',
  STARTS_AT: '4,2',
  ENDS_AT: '4,2',
  INCLUDES: '6,3',
}

// ── Props ───────────────────────────────────────────────────────────────────

interface ForceGraphProps {
  nodes: GNode[]
  edges: GEdge[]
  focusNode: string | null
  onNodeClick?: (id: string) => void
  edgeColors?: Record<string, string>
  edgeDashes?: Record<string, string>
  nodeColors?: Record<string, string>
  nodeRadii?: Record<string, number>
  legendItems?: LegendItem[]
  confOpacity?: boolean
  highlightedNodeIds?: Set<string>  // nodes to highlight (e.g., circuit's brain regions)
  highlightedEdgeIds?: Set<string>  // edges to highlight (e.g., circuit's connections)
}

// ── Component ───────────────────────────────────────────────────────────────

export function ForceGraph({
  nodes: _nodes,
  edges: _edges,
  focusNode,
  onNodeClick,
  edgeColors = EDGE_COLOR,
  edgeDashes = EDGE_DASH,
  nodeColors = NODE_COLOR,
  nodeRadii = NODE_R,
  legendItems,
  confOpacity = true,
  highlightedNodeIds,
  highlightedEdgeIds,
}: ForceGraphProps) {
  const ref = useRef<HTMLDivElement>(null)

  // Rebuild node set from edges: ensure every edge endpoint has a node
  const { nodes, edges } = useMemo(() => {
    const nm = new Map<string, GNode>()
    for (const n of _nodes) nm.set(n.id, n)
    for (const e of _edges) {
      const srcId = String(
        typeof e.source === 'object' ? (e.source as any).id || (e.source as any).name || '' : e.source,
      )
      const tgtId = String(
        typeof e.target === 'object' ? (e.target as any).id || (e.target as any).name || '' : e.target,
      )
      if (!nm.has(srcId) && srcId) {
        nm.set(srcId, { id: srcId, type: 'connection', label: srcId.slice(0, 12) })
      }
      if (!nm.has(tgtId) && tgtId) {
        nm.set(tgtId, { id: tgtId, type: 'connection', label: tgtId.slice(0, 12) })
      }
    }
    const validEdges = _edges.filter(e => {
      const s = String(
        typeof e.source === 'object' ? (e.source as any).id || (e.source as any).name : e.source,
      )
      const t = String(
        typeof e.target === 'object' ? (e.target as any).id || (e.target as any).name : e.target,
      )
      return nm.has(s) && nm.has(t)
    })
    return { nodes: [...nm.values()], edges: validEdges }
  }, [_nodes, _edges])

  useEffect(() => {
    const el = ref.current
    if (!el || nodes.length === 0) return
    const W = el.clientWidth || 1000
    const H = el.clientHeight || 700
    d3.select(el).html('')

    // Soft render ceiling — D3 handles ~20k edges before simulation gets slow.
    // For 100k+ datasets, consider WebGL or canvas-based rendering.
    const maxRender = 200000
    const renderNodes = nodes.slice(0, maxRender)
    // Sort rare edge types LAST so they render on top of common types (e.g. functional
    // edges visible above the dense structural_connection layer in macro graphs).
    const EDGE_TYPE_PRIORITY: Record<string, number> = {
      structural_connection: 0, functional_connectivity: 1, projection: 1,
      association: 2, coactivation: 2, effective_connectivity: 2,
      uncertain_connection: 3, unknown: 3, step_flow: 2, co_occurs: 2, belongs_to: 0,
    }
    const renderEdges = edges
      .filter(
        e =>
          renderNodes.some(n => n.id === e.source) &&
          renderNodes.some(n => n.id === e.target),
      )
      .sort((a, b) => (EDGE_TYPE_PRIORITY[a.type] ?? 0) - (EDGE_TYPE_PRIORITY[b.type] ?? 0))
      .slice(0, maxRender)

    if (nodes.length > maxRender) {
      d3.select(el)
        .append('div')
        .style('padding', '20px')
        .style('color', '#888')
        .style('textAlign', 'center')
        .text(`大数据集：${nodes.length} 节点, ${edges.length} 边。仅渲染前 ${maxRender} 条边。`)
    }

    setTimeout(() => {
      d3.select(el).html('')
      drawGraph(el, renderNodes, renderEdges, W, H, focusNode, onNodeClick, edgeColors, edgeDashes, nodeColors, nodeRadii, undefined, confOpacity, highlightedNodeIds, highlightedEdgeIds)
    }, 10)

    return () => {}
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [nodes.length, edges.length, focusNode, edgeColors, edgeDashes, nodeColors, nodeRadii])

  // Lightweight opacity-only update — avoids expensive force-sim rebuild on toggle
  useEffect(() => {
    const el = ref.current
    if (!el) return
    d3.select(el).selectAll('line')
      .transition().duration(200)
      .attr('stroke-opacity', (d: any) => confOpacity ? Math.min(0.6, 0.08 + (d.confidence || 0.3)) : 0.4)
  }, [confOpacity])

  return (
    <div style={{ width: '100%', height: '100%', display: 'flex', flexDirection: 'column' }}>
      <div ref={ref} style={{ flex: 1, minHeight: 0 }} />
      {legendItems && legendItems.length > 0 && (
        <div
          style={{
            display: 'flex',
            gap: 24,
            fontSize: 11,
            color: '#555',
            marginTop: 6,
            flexWrap: 'wrap',
            lineHeight: '18px',
            alignItems: 'center',
          }}
        >
          {legendItems.map((item, i) => (
            <div key={i} style={{ display: 'flex', alignItems: 'center', gap: 4 }}>
              {item.dash ? (
                <span
                  style={{
                    borderBottom: `2px dashed ${item.color}`,
                    color: item.color,
                    lineHeight: '0.8',
                  }}
                >
                  ╌╌╌
                </span>
              ) : (
                <span style={{ color: item.color }}>━━</span>
              )}
              <span>{item.label}</span>
            </div>
          ))}
        </div>
      )}
    </div>
  )
}

// ── drawGraph (pure D3) ─────────────────────────────────────────────────────

export function drawGraph(
  el: HTMLDivElement,
  nodes: GNode[],
  edges: GEdge[],
  W: number,
  H: number,
  focusNode: string | null,
  onNodeClick?: (id: string) => void,
  edgeColors?: Record<string, string>,
  edgeDashes?: Record<string, string>,
  nodeColors?: Record<string, string>,
  nodeRadii?: Record<string, number>,
  // eslint-disable-next-line @typescript-eslint/no-unused-vars
  _legendItems?: LegendItem[],
  confOpacity = true,
  highlightedNodeIds?: Set<string>,
  highlightedEdgeIds?: Set<string>,
) {
  const ec = edgeColors ?? EDGE_COLOR
  const ed = edgeDashes ?? EDGE_DASH
  const nc = nodeColors ?? NODE_COLOR
  const nr = nodeRadii ?? NODE_R

  d3.select(el).html('')
  const svg = d3.select(el).append('svg').attr('width', W).attr('height', H)
  const g = svg.append('g')
  svg.call(
    d3
      .zoom<SVGSVGElement, unknown>()
      .scaleExtent([0.05, 5])
      .on('zoom', ev => g.attr('transform', ev.transform)),
  )

  // Tooltip div
  const tip = d3
    .select(el)
    .append('div')
    .style('position', 'absolute')
    .style('pointer-events', 'none')
    .style('background', '#1f2937')
    .style('color', '#f9fafb')
    .style('padding', '6px 10px')
    .style('border-radius', '6px')
    .style('font-size', '11px')
    .style('opacity', '0')
    .style('transition', 'opacity 0.15s')
    .style('max-width', '300px')
    .style('z-index', '100')

  // Spread nodes across canvas with random positions
  nodes.forEach((n: any) => {
    n.x = 50 + Math.random() * (W - 100)
    n.y = 50 + Math.random() * (H - 100)
  })

  const link = g
    .append('g')
    .selectAll('line')
    .data(edges)
    .join('line')
    .attr('stroke', (d: any) => highlightedEdgeIds?.has(d.id) ? '#ef4444' : (ec[d.type] || '#d1d5db'))
    .attr('stroke-width', (d: any) => highlightedEdgeIds?.has(d.id) ? 3 : Math.max(0.3, (d.confidence || 0.3) * 1.5))
    .attr('stroke-opacity', (d: any) => highlightedEdgeIds?.has(d.id) ? 0.85 : (confOpacity ? Math.min(0.6, 0.08 + (d.confidence || 0.3)) : 0.4))
    .attr('stroke-dasharray', (d: any) => ed[d.type] || '')
    .attr('style', 'cursor:pointer')
    .on('mouseenter', (ev: any, d: any) => {
      const typeNames: Record<string, string> = {
        structural_connection: '结构连接',
        functional_connectivity: '功能连接',
        projection: '投射',
        association: '关联',
        coactivation: '共激活',
        effective_connectivity: '有效连接',
        STARTS_AT: '回路起点',
        ENDS_AT: '回路终点',
        INCLUDES: '回路包含',
      }
      tip
        .style('opacity', '1')
        .html(
          `<strong>${typeNames[d.type] || d.type}</strong> 置信度:${((d.confidence || 0) * 100).toFixed(0)}%<br/>${d.label}`,
        )
    })
    .on('mousemove', (ev: any) => {
      tip.style('left', ev.offsetX + 12 + 'px').style('top', ev.offsetY - 10 + 'px')
    })
    .on('mouseleave', () => {
      tip.style('opacity', '0')
    })

  const ng = g
    .append('g')
    .selectAll('g')
    .data(nodes)
    .join('g')
    .attr('cursor', 'pointer')
    .on('click', (ev: any, d: any) => {
      ev.stopPropagation()
      onNodeClick?.(d.id)
    })
    .on('mouseenter', (ev: any, d: any) => {
      tip
        .style('opacity', '1')
        .html(`<strong>${d.type}</strong>: ${d.label}<br/>${d.name_en || ''} ${d.name_cn || ''}`.trim())
    })
    .on('mousemove', (ev: any) => {
      tip.style('left', ev.offsetX + 12 + 'px').style('top', ev.offsetY - 10 + 'px')
    })
    .on('mouseleave', () => {
      tip.style('opacity', '0')
    })

  ng.append('circle')
    .attr('r', (d: any) => (d.id === focusNode || highlightedNodeIds?.has(d.id) ? 12 : nr[d.type] || 4))
    .attr('fill', (d: any) => (d.id === focusNode || highlightedNodeIds?.has(d.id) ? '#ef4444' : nc[d.type] || '#999'))
    .attr('stroke', (d: any) => (highlightedNodeIds?.has(d.id) ? '#ef4444' : '#fff'))
    .attr('stroke-width', (d: any) => (highlightedNodeIds?.has(d.id) ? 3 : 1.5))

  ng.append('text')
    .text((d: any) => { const s = (d.label || ''); return s.length > 24 ? s.slice(0, 22) + '…' : s })
    .attr('dx', 9)
    .attr('dy', 4)
    .style('font-size', '7px')
    .style('fill', '#374151')

  // Simulation with strong spreading force
  const sim = d3.forceSimulation(nodes as any)
  sim.force(
    'link',
    d3.forceLink(edges).id((d: any) => d.id).distance(120),
  )
  sim.force('charge', d3.forceManyBody().strength(-600))
  sim.force('center', d3.forceCenter(W / 2, H / 2))
  sim.force('collision', d3.forceCollide(25))
  sim.on('tick', () => {
    link
      .attr('x1', (d: any) => d.source.x)
      .attr('y1', (d: any) => d.source.y)
      .attr('x2', (d: any) => d.target.x)
      .attr('y2', (d: any) => d.target.y)
    ng.attr('transform', (d: any) => `translate(${d.x},${d.y})`)
  })

  // Run simulation longer for better spread
  sim.alpha(1).restart()
  for (let i = 0; i < 300; i++) sim.tick()

  // Drag
  ng.call(
    d3
      .drag<SVGGElement, any>()
      .on('start', (ev: any, d: any) => {
        if (!ev.active) sim.alphaTarget(0.3).restart()
        d.fx = d.x
        d.fy = d.y
      })
      .on('drag', (ev: any, d: any) => {
        d.fx = ev.x
        d.fy = ev.y
      })
      .on('end', (ev: any, d: any) => {
        if (!ev.active) sim.alphaTarget(0)
      }) as any,
  )
}
