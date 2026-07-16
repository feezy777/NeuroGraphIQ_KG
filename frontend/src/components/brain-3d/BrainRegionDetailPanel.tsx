/**
 * BrainRegionDetailPanel.tsx — Detail panel for a selected brain region.
 */
import type { BrainRegionNode } from '../../lib/brain-spatial/brain3d.types'

interface Props {
  node: BrainRegionNode | null
  onClose: () => void
}

export function BrainRegionDetailPanel({ node, onClose }: Props) {
  if (!node) return null

  const mni = node.representative_point_mni
  const com = node.center_of_mass_mni

  return (
    <div className="brain-3d-detail-panel">
      <div className="brain-3d-detail-header">
        <h3>{node.name_cn || node.name_en}</h3>
        <button onClick={onClose} className="brain-3d-close-btn">✕</button>
      </div>
      <dl className="brain-3d-detail-list">
        <dt>region_id</dt><dd>{node.region_id}</dd>
        <dt>中文名</dt><dd>{node.name_cn || '—'}</dd>
        <dt>英文名</dt><dd>{node.name_en || '—'}</dd>
        <dt>laterality</dt><dd>{node.laterality}</dd>
        <dt>atlas</dt><dd>AAL (Tzourio-Mazoyer 2002)</dd>
        <dt>atlas label</dt><dd>{node.atlas_label ?? '—'}</dd>
        <dt>official atlas name</dt><dd>{node.official_atlas_name ?? '—'}</dd>
        <dt>mapping_status</dt>
        <dd>
          <span className={`brain-3d-badge brain-3d-badge-${node.mapping_status}`}>
            {node.mapping_status}
          </span>
        </dd>
        <dt>representative_point_mni</dt>
        <dd>{mni ? `(${mni.x}, ${mni.y}, ${mni.z})` : '—'}</dd>
        <dt>center_of_mass_mni</dt>
        <dd>{com ? `(${com.x}, ${com.y}, ${com.z})` : '—'}</dd>
        <dt>voxel_count</dt><dd>{node.voxel_count ?? '—'}</dd>
        <dt>coordinate_source</dt><dd>{node.coordinate_source || '—'}</dd>
      </dl>
    </div>
  )
}
