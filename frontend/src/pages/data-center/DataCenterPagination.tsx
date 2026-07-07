import { useState } from 'react'

export interface DataCenterPaginationProps {
  page: number
  pageSize: number
  total: number
  onPageChange: (page: number) => void
  onPageSizeChange?: (pageSize: number) => void
  pageSizeOptions?: number[]
  disabled?: boolean
}

export function DataCenterPagination({
  page,
  pageSize,
  total,
  onPageChange,
  onPageSizeChange,
  pageSizeOptions = [50, 100, 200],
  disabled = false,
}: DataCenterPaginationProps) {
  const totalPages = total === 0 ? 1 : Math.ceil(total / pageSize)
  const start = total === 0 ? 0 : (page - 1) * pageSize + 1
  const end = total === 0 ? 0 : Math.min(page * pageSize, total)
  const [jump, setJump] = useState('')

  const doJump = () => {
    const n = parseInt(jump, 10)
    if (n >= 1 && n <= totalPages) {
      onPageChange(n)
      setJump('')
    }
  }

  return (
    <div className="data-center-pagination">
      <div className="data-center-pagination-meta">
        {total > 0 && <span>{start}–{end} / 共 {total} 条</span>}
        <div style={{ display: 'flex', gap: 4 }}>
          {onPageSizeChange && (
            <select className="data-center-page-size-select" value={pageSize}
              onChange={e => {
                const v = Number(e.target.value)
                onPageSizeChange(v > 0 ? v : total || 99999)
              }}>
              {pageSizeOptions.map(n => <option key={n} value={n}>{n} 条/页</option>)}
              <option value={0}>全部</option>
            </select>
          )}
          {pageSize > 999 && total > 0 && (
            <button className="btn btn-sm" onClick={() => onPageSizeChange?.(200)}>恢复分页</button>
          )}
        </div>
      </div>

      <div className="data-center-pagination-actions">
        {pageSize <= 999 && (
          <>
            <button type="button" className="btn btn-sm" disabled={disabled || page <= 1}
              onClick={() => onPageChange(page - 1)}>上一页</button>
            <span className="data-center-page-info">第 {page} / 共 {totalPages} 页</span>
            <button type="button" className="btn btn-sm" disabled={disabled || page >= totalPages}
              onClick={() => onPageChange(page + 1)}>下一页</button>
            {totalPages > 1 && (
              <span className="data-center-page-jump">
                <input className="data-center-page-jump-input" value={jump}
                  onChange={e => setJump(e.target.value.replace(/\D/g, ''))}
                  onKeyDown={e => e.key === 'Enter' && doJump()}
                  placeholder="页码" />
                <button type="button" className="btn btn-sm" onClick={doJump} disabled={!jump}>跳转</button>
              </span>
            )}
          </>
        )}
        {pageSize > 999 && <span style={{ fontSize: 12, color: '#888' }}>全部 {total} 条</span>}
      </div>
    </div>
  )
}
