import { useState, useEffect, useCallback, useRef } from 'react'
import { ApiError } from '../../../api/client'
import {
  createConnectionPool,
  getConnectionPool,
  addConnectionPoolMembers,
  removeConnectionPoolMembers,
  deleteConnectionPool,
  listConnectionPools,
  replaceConnectionPool,
  type ConnectionPool,
  type ConnectionPoolMember,
} from '../../../api/endpoints'

export interface ConnPoolScope {
  sourceAtlas: string
  granularityLevel: string
}

export class PoolSetupError extends Error {
  constructor(message: string) {
    super(message)
    this.name = 'ConnPoolSetupError'
  }
}

function scopeKey(s: ConnPoolScope): string {
  return `${s.sourceAtlas}::${s.granularityLevel}`
}

function isPoolNotFoundError(err: unknown): boolean {
  if (err instanceof ApiError && err.status === 404) return true
  const msg = err instanceof Error ? err.message : String(err)
  return msg.includes('not found') || msg.includes('404')
}

export function useConnectionPool(scope: ConnPoolScope | null) {
  const [pool, setPool] = useState<ConnectionPool | null>(null)
  const [isLoading, setIsLoading] = useState(false)
  const mountedRef = useRef(true)
  const fetchGenRef = useRef(0)
  const currentKey = scope ? scopeKey(scope) : null

  const listScopePools = useCallback(async () => {
    if (!scope) return []
    const { items } = await listConnectionPools({
      scope_atlas: scope.sourceAtlas,
      scope_granularity: scope.granularityLevel,
      limit: 100,
    })
    return items
  }, [scope?.sourceAtlas, scope?.granularityLevel])

  // Fetch pool when scope changes
  useEffect(() => {
    mountedRef.current = true
    if (!scope) {
      setPool(null)
      return
    }

    const gen = ++fetchGenRef.current
    let cancelled = false
    setIsLoading(true)

    ;(async () => {
      try {
        const items = await listScopePools()
        if (!mountedRef.current || cancelled || gen !== fetchGenRef.current) return

        if (items.length > 0) {
          try {
            const full = await getConnectionPool(items[0].id)
            if (!mountedRef.current || cancelled || gen !== fetchGenRef.current) return
            setPool(full)
          } catch (err) {
            if (!mountedRef.current || cancelled || gen !== fetchGenRef.current) return
            if (isPoolNotFoundError(err)) setPool(null)
          }
        } else {
          setPool(null)
        }
      } catch (err) {
        console.warn('[useConnectionPool] fetch failed:', err)
      } finally {
        if (mountedRef.current && !cancelled && gen === fetchGenRef.current) setIsLoading(false)
      }
    })()

    return () => { cancelled = true }
  }, [currentKey, listScopePools])

  useEffect(() => {
    return () => { mountedRef.current = false }
  }, [])

  const pooledConnectionIds = new Set(
    pool?.memberships?.map((m: ConnectionPoolMember) => m.connection_id) ?? []
  )

  /** Add connections to pool (auto-creates pool if none exists). */
  const addConnections = useCallback(async (connectionIds: string[]) => {
    if (!scope || connectionIds.length === 0) return

    const newIds = connectionIds.filter(id => !pooledConnectionIds.has(id))
    if (newIds.length === 0) return

    try {
      let currentPool = pool
      if (!currentPool) {
        currentPool = await createConnectionPool({
          connection_ids: newIds,
          scope_atlas: scope.sourceAtlas,
          scope_granularity: scope.granularityLevel,
        })
      } else {
        currentPool = await addConnectionPoolMembers(currentPool.id, { connection_ids: newIds })
      }
      if (mountedRef.current) {
        const full = await getConnectionPool(currentPool.id)
        if (mountedRef.current) setPool(full)
      }
    } catch (err) {
      console.error('[useConnectionPool] add failed:', err)
    }
  }, [scope, pool?.id, pooledConnectionIds, currentKey])

  /** Replace pool contents with exactly these connections (idempotent). */
  const setPoolConnections = useCallback(async (
    connectionIds: string[],
    scopeOverride?: ConnPoolScope | null,
  ): Promise<ConnectionPool> => {
    const effectiveScope = scopeOverride ?? scope
    const uniqueIds = [...new Set(connectionIds.filter(Boolean))]

    if (uniqueIds.length < 1) {
      throw new PoolSetupError('至少需要选择 1 条连接')
    }
    if (!effectiveScope?.sourceAtlas || !effectiveScope?.granularityLevel) {
      throw new PoolSetupError('提取范围尚未就绪')
    }

    const payload = {
      connection_ids: uniqueIds,
      scope_atlas: effectiveScope.sourceAtlas,
      scope_granularity: effectiveScope.granularityLevel,
    }

    ++fetchGenRef.current
    try {
      const created = await replaceConnectionPool(payload)
      const full = await getConnectionPool(created.id)
      if (mountedRef.current) setPool(full)
      return full
    } catch (err) {
      console.error('[useConnectionPool] setPoolConnections failed:', err)
      throw err
    }
  }, [scope, currentKey])

  const removeConnection = useCallback(async (connectionId: string) => {
    if (!pool) return
    try {
      await removeConnectionPoolMembers(pool.id, { connection_ids: [connectionId] })
      if (mountedRef.current) {
        const full = await getConnectionPool(pool.id)
        if (mountedRef.current) setPool(full.connection_count > 0 ? full : null)
      }
    } catch (err) {
      if (isPoolNotFoundError(err)) {
        if (mountedRef.current) setPool(null)
        return
      }
      console.warn('[useConnectionPool] remove failed:', err)
    }
  }, [pool?.id])

  const batchRemove = useCallback(async (connectionIds: string[]) => {
    if (!pool || connectionIds.length === 0) return
    try {
      await removeConnectionPoolMembers(pool.id, { connection_ids: connectionIds })
      if (mountedRef.current) {
        const remaining = pool.connection_count - connectionIds.length
        if (remaining <= 0) {
          setPool(null)
        } else {
          const full = await getConnectionPool(pool.id)
          if (mountedRef.current) setPool(full)
        }
      }
    } catch (err) {
      if (isPoolNotFoundError(err)) {
        if (mountedRef.current) setPool(null)
        return
      }
      console.warn('[useConnectionPool] batchRemove failed:', err)
    }
  }, [pool?.id, pool?.connection_count])

  const refresh = useCallback(async () => {
    if (!pool?.id) return
    try {
      const full = await getConnectionPool(pool.id)
      if (mountedRef.current) setPool(full.connection_count > 0 ? full : null)
    } catch (err) {
      if (isPoolNotFoundError(err) && mountedRef.current) setPool(null)
    }
  }, [pool?.id])

  const clearPool = useCallback(async () => {
    if (!pool) return
    try {
      await deleteConnectionPool(pool.id)
    } catch (err) {
      if (!isPoolNotFoundError(err)) console.warn('[useConnectionPool] clear failed:', err)
    } finally {
      if (mountedRef.current) setPool(null)
    }
  }, [pool?.id])

  return {
    pool, pooledConnectionIds, isLoading,
    addConnections, setPoolConnections, removeConnection, batchRemove, clearPool,
    refresh,
  }
}
