/**
 * UnplacedRegionsList.tsx — Show 24 unplotted regions with reasons.
 */
interface UnplacedRegion {
  region_id: string
  name_en: string
  name_cn: string
  laterality: string
  mapping_status: string
  reason: string
}

interface Props {
  manualReview: UnplacedRegion[]
  unmapped: UnplacedRegion[]
}

export function UnplacedRegionsList({ manualReview, unmapped }: Props) {
  return (
    <div className="brain-3d-unplaced">
      <h4>空间数据状态</h4>
      <div className="brain-3d-stats">
        <div className="brain-3d-stat">
          <strong>96</strong> 总脑区
        </div>
        <div className="brain-3d-stat brain-3d-stat-ok">
          <strong>72</strong> 已定位
        </div>
        <div className="brain-3d-stat brain-3d-stat-warn">
          <strong>{manualReview.length}</strong> manual_review
        </div>
        <div className="brain-3d-stat brain-3d-stat-muted">
          <strong>{unmapped.length}</strong> unmapped
        </div>
      </div>

      {manualReview.length > 0 && (
        <>
          <h5>Manual Review ({manualReview.length})</h5>
          <table className="brain-3d-table">
            <thead><tr><th>名称</th><th>原因</th></tr></thead>
            <tbody>
              {manualReview.map((r) => (
                <tr key={r.region_id}>
                  <td>{r.name_cn || r.name_en} ({r.laterality})</td>
                  <td>{r.reason}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </>
      )}

      {unmapped.length > 0 && (
        <>
          <h5>Unmapped ({unmapped.length})</h5>
          <table className="brain-3d-table">
            <thead><tr><th>名称</th><th>结构类别</th></tr></thead>
            <tbody>
              {unmapped.map((r) => (
                <tr key={r.region_id}>
                  <td>{r.name_cn || r.name_en} ({r.laterality})</td>
                  <td>{r.reason}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </>
      )}
    </div>
  )
}
