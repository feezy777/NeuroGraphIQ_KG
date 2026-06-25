import { useEffect, useMemo, useState } from 'react'

export const DATA_CENTER_PAGE_SIZE = 20

export interface UseDataCenterPaginationOptions<T> {
  items: T[]
  pageSize?: number
  resetKeys?: unknown[]
}

export function useDataCenterPagination<T>({
  items,
  pageSize = DATA_CENTER_PAGE_SIZE,
  resetKeys = [],
}: UseDataCenterPaginationOptions<T>) {
  const [page, setPage] = useState(1)

  useEffect(() => {
    setPage(1)
  }, [pageSize, ...resetKeys])

  const total = items.length
  const totalPages = total === 0 ? 1 : Math.ceil(total / pageSize)

  useEffect(() => {
    if (total === 0) {
      if (page !== 1) setPage(1)
      return
    }
    if (page > totalPages) setPage(totalPages)
  }, [page, totalPages, total])

  const pagedItems = useMemo(
    () => items.slice((page - 1) * pageSize, page * pageSize),
    [items, page, pageSize],
  )

  const startIndex = total === 0 ? 0 : (page - 1) * pageSize + 1
  const endIndex = total === 0 ? 0 : Math.min(page * pageSize, total)

  return {
    page,
    pageSize,
    total,
    totalPages,
    pagedItems,
    startIndex,
    endIndex,
    setPage,
    resetPage: () => setPage(1),
  }
}
