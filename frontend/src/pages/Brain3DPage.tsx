/**
 * Brain3DPage.tsx — 3D brain map page.
 * Step 1: render data-only view to verify data pipeline.
 * Step 2: add Canvas after confirming data loads correctly.
 */
import { useEffect, useState, useMemo } from 'react'
import { Major96Brain3DView } from '../components/brain-3d/Major96Brain3DView'
import { BrainRegionDetailPanel } from '../components/brain-3d/BrainRegionDetailPanel'
import { UnplacedRegionsList } from '../components/brain-3d/UnplacedRegionsList'
import { fetchRegionNodes, getPlottableNodes } from '../lib/brain-spatial/loadMajor96SpatialData'
import type { BrainRegionNode } from '../lib/brain-spatial/brain3d.types'

export function Brain3DPage() {
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState<string | null>(null)
  const [nodesData, setNodesData] = useState<{
    total: number
    plottable: BrainRegionNode[]
    manualReview: BrainRegionNode[]
    unmapped: BrainRegionNode[]
  } | null>(null)
  const [selectedNode, setSelectedNode] = useState<BrainRegionNode | null>(null)
  const [show3D, setShow3D] = useState(false)

  useEffect(() => {
    fetchRegionNodes()
      .then((data) => {
        const plottable = getPlottableNodes(data)
        setNodesData({
          total: data.nodes.length,
          plottable,
          manualReview: data.nodes.filter((n) => n.mapping_status === 'manual_review') as BrainRegionNode[],
          unmapped: data.nodes.filter((n) => n.mapping_status === 'unmapped') as BrainRegionNode[],
        })
        setLoading(false)
      })
      .catch((e) => {
        setError(e.message)
        setLoading(false)
      })
  }, [])

  const unplacedInfo = useMemo(() => {
    if (!nodesData) return { manualReview: [] as any[], unmapped: [] as any[] }
    return {
      manualReview: nodesData.manualReview.map((r) => ({
        region_id: r.region_id, name_en: r.name_en, name_cn: r.name_cn,
        laterality: r.laterality, mapping_status: 'manual_review',
        reason: getManualReviewReason(r),
      })),
      unmapped: nodesData.unmapped.map((r) => ({
        region_id: r.region_id, name_en: r.name_en, name_cn: r.name_cn,
        laterality: r.laterality, mapping_status: 'unmapped',
        reason: getUnmappedReason(r),
      })),
    }
  }, [nodesData])

  if (loading) {
    return <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'center', height: '100%', color: '#fff', background: '#1a1a2e', fontSize: 18 }}>加载空间数据...</div>
  }
  if (error) {
    return <div style={{ padding: 40, color: '#f44336', background: '#1a1a2e', height: '100%' }}><h3>加载失败</h3><pre>{error}</pre></div>
  }
  if (!nodesData) return null

  // Step 1: show data view, with button to enable 3D
  if (!show3D) {
    return (
      <div style={{ padding: 24, color: '#e0e0e0', background: '#1a1a2e', height: '100%', overflow: 'auto' }}>
        <h2 style={{ margin: '0 0 8px' }}>3D脑图 — 空间数据就绪</h2>
        <p style={{ color: '#888', marginBottom: 16 }}>96个脑区中 <strong style={{ color: '#4caf50' }}>{nodesData.plottable.length}个已定位</strong>，{nodesData.manualReview.length + nodesData.unmapped.length}个暂未绘制</p>

        <button
          onClick={() => setShow3D(true)}
          style={{ padding: '10px 24px', fontSize: 15, background: '#0f3460', color: '#00D4FF', border: '1px solid #00D4FF', borderRadius: 6, cursor: 'pointer', marginBottom: 24 }}
        >
          进入3D视图 (加载Three.js)
        </button>

        <h3>已定位节点 ({nodesData.plottable.length})</h3>
        <table style={{ width: '100%', borderCollapse: 'collapse', fontSize: 13 }}>
          <thead><tr style={{ color: '#888' }}>
            <th style={{ textAlign: 'left', padding: 4 }}>名称</th>
            <th style={{ textAlign: 'left', padding: 4 }}>MNI坐标</th>
            <th style={{ textAlign: 'left', padding: 4 }}>状态</th>
          </tr></thead>
          <tbody>
            {nodesData.plottable.map((n) => (
              <tr key={n.region_id} style={{ borderBottom: '1px solid #1a3a5a' }}>
                <td style={{ padding: 4 }}>{n.name_cn || n.name_en} <span style={{ color: '#888', fontSize: 11 }}>({n.laterality})</span></td>
                <td style={{ padding: 4, fontFamily: 'monospace', fontSize: 12 }}>
                  ({n.representative_point_mni.x}, {n.representative_point_mni.y}, {n.representative_point_mni.z})
                </td>
                <td style={{ padding: 4 }}>
                  <span style={{ background: n.mapping_status === 'verified_exact' ? '#1a472a' : '#1a3a4a', color: n.mapping_status === 'verified_exact' ? '#4caf50' : '#2196f3', padding: '2px 6px', borderRadius: 3, fontSize: 11 }}>
                    {n.mapping_status}
                  </span>
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    )
  }

  // Step 2: full 3D view
  return (
    <div className="brain-3d-page">
      <div className="brain-3d-main">
        <div className="brain-3d-viewer">
          <Major96Brain3DView
            nodes={nodesData.plottable}
            selectedNode={selectedNode}
            onSelectNode={setSelectedNode}
          />
        </div>
        <div className="brain-3d-sidebar">
          <BrainRegionDetailPanel node={selectedNode} onClose={() => setSelectedNode(null)} />
          <UnplacedRegionsList manualReview={unplacedInfo.manualReview} unmapped={unplacedInfo.unmapped} />
        </div>
      </div>
    </div>
  )
}

function getManualReviewReason(r: BrainRegionNode): string {
  const name = (r.name_cn || r.name_en || '').toLowerCase()
  if (name.includes('thalamus') || name.includes('丘脑')) return '丘脑proper为复合结构'
  if (name.includes('brain stem') || name.includes('脑干')) return '脑干为复合结构'
  if (name.includes('accumbens') || name.includes('伏隔')) return '伏隔核不在AAL中'
  if (name.includes('diencephalon') || name.includes('间脑')) return '腹侧间脑为复合结构'
  if (name.includes('forebrain') || name.includes('前脑')) return '基底前脑不在AAL中'
  if (name.includes('vermal') || name.includes('蚓部')) return '小脑蚓部复合分组'
  return '需要人工复核'
}

function getUnmappedReason(r: BrainRegionNode): string {
  const name = (r.name_en || '').toLowerCase()
  if (name.includes('white matter')) return '脑白质'
  if (name.includes('ventricle')) return '脑室系统'
  if (name.includes('csf')) return '脑脊液'
  if (name.includes('cerebellum exterior')) return '小脑外部'
  if (name.includes('cerebellum white')) return '小脑白质'
  return 'AAL未细分'
}
