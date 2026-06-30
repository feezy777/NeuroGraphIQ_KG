import { useI18n } from '../../i18n-context'

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
  disabled = false,
}: DataCenterPaginationProps) {
  const { t } = useI18n()
  const totalPages = total === 0 ? 1 : Math.ceil(total / pageSize)
  const startIndex = total === 0 ? 0 : (page - 1) * pageSize + 1
  const endIndex = total === 0 ? 0 : Math.min(page * pageSize, total)

  return (
    <div className="data-center-pagination">
      <div className="data-center-pagination-meta">
        {total === 0 ? (
          <span>{t('dataCenter.pagination.empty')}</span>
        ) : (
          <>
            <span>{t('dataCenter.pagination.total', { total })}</span>
            <span>{t('dataCenter.pagination.range', { start: startIndex, end: endIndex })}</span>
            <span>{t('dataCenter.pagination.page', { page, totalPages })}</span>
            <span className="data-center-pagination-pagesize">
              {pageSize >= 999999 ? '全部显示' : t('dataCenter.pagination.pageSizeN', { n: pageSize })}
            </span>
          </>
        )}
      </div>
      <div className="data-center-pagination-actions">
        <button
          type="button"
          className="btn"
          disabled={disabled || total === 0 || page <= 1}
          onClick={() => onPageChange(page - 1)}
        >
          {t('dataCenter.pagination.prev')}
        </button>
        <button
          type="button"
          className="btn"
          disabled={disabled || total === 0 || page >= totalPages}
          onClick={() => onPageChange(page + 1)}
        >
          {t('dataCenter.pagination.next')}
        </button>
      </div>
    </div>
  )
}
