import { useCallback, useMemo, useState } from 'react'

export interface UseBulkSelectionOptions<T> {
  getId: (item: T) => string
  filteredItems: T[]
  pageItems: T[]
}

export function useBulkSelection<T>({
  getId,
  filteredItems,
  pageItems,
}: UseBulkSelectionOptions<T>) {
  const [selectedIds, setSelectedIds] = useState<Set<string>>(new Set())

  const filteredIdSet = useMemo(
    () => new Set(filteredItems.map(getId)),
    [filteredItems, getId],
  )

  const pageIds = useMemo(() => pageItems.map(getId), [pageItems, getId])

  const pageSelectedCount = useMemo(
    () => pageIds.filter(id => selectedIds.has(id)).length,
    [pageIds, selectedIds],
  )

  const allPageSelected = pageItems.length > 0 && pageSelectedCount === pageItems.length
  const somePageSelected = pageSelectedCount > 0 && !allPageSelected

  const allFilteredSelected = useMemo(() => {
    if (filteredItems.length === 0) return false
    return filteredItems.every(item => selectedIds.has(getId(item)))
  }, [filteredItems, selectedIds, getId])

  const selectedCount = selectedIds.size

  const outsideFilterCount = useMemo(() => {
    let count = 0
    selectedIds.forEach(id => {
      if (!filteredIdSet.has(id)) count += 1
    })
    return count
  }, [selectedIds, filteredIdSet])

  const isSelected = useCallback((id: string) => selectedIds.has(id), [selectedIds])

  const toggleOne = useCallback((id: string) => {
    setSelectedIds(prev => {
      const next = new Set(prev)
      if (next.has(id)) next.delete(id)
      else next.add(id)
      return next
    })
  }, [])

  const togglePage = useCallback(() => {
    setSelectedIds(prev => {
      const next = new Set(prev)
      if (allPageSelected) {
        pageIds.forEach(id => next.delete(id))
      } else {
        pageIds.forEach(id => next.add(id))
      }
      return next
    })
  }, [allPageSelected, pageIds])

  const selectAllFiltered = useCallback(() => {
    setSelectedIds(prev => {
      const next = new Set(prev)
      filteredItems.forEach(item => next.add(getId(item)))
      return next
    })
  }, [filteredItems, getId])

  const clearSelection = useCallback(() => {
    setSelectedIds(new Set())
  }, [])

  const keepOnlyFiltered = useCallback(() => {
    setSelectedIds(prev => {
      const next = new Set<string>()
      prev.forEach(id => {
        if (filteredIdSet.has(id)) next.add(id)
      })
      return next
    })
  }, [filteredIdSet])

  /** Keep only the first `max` selected items in filteredItems order. */
  const trimToN = useCallback((max: number) => {
    setSelectedIds(prev => {
      const next = new Set<string>()
      let count = 0
      for (const item of filteredItems) {
        if (count >= max) break
        const id = getId(item)
        if (prev.has(id)) {
          next.add(id)
          count++
        }
      }
      return next
    })
  }, [filteredItems, getId])

  return {
    selectedIds,
    selectedCount,
    pageSelectedCount,
    allPageSelected,
    somePageSelected,
    allFilteredSelected,
    outsideFilterCount,
    toggleOne,
    togglePage,
    selectAllFiltered,
    clearSelection,
    keepOnlyFiltered,
    trimToN,
    isSelected,
  }
}
