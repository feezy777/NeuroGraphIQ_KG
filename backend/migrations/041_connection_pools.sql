-- 041_connection_pools.sql
-- Connection Pool: cross-source connection accumulation for LLM extraction.
-- Analogous to candidate_pools but for MirrorRegionConnection records.

CREATE TABLE IF NOT EXISTS connection_pools (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    name VARCHAR(255),
    scope_atlas VARCHAR(128) NOT NULL,
    scope_granularity VARCHAR(64) NOT NULL,
    source VARCHAR(64) NOT NULL DEFAULT 'manual',
    resource_id UUID REFERENCES atlas_resources(id) ON DELETE SET NULL,
    batch_id UUID REFERENCES import_batches(id) ON DELETE SET NULL,
    connection_count INT NOT NULL DEFAULT 0,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE TABLE IF NOT EXISTS connection_pool_memberships (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    pool_id UUID NOT NULL REFERENCES connection_pools(id) ON DELETE CASCADE,
    connection_id UUID NOT NULL REFERENCES mirror_region_connections(id) ON DELETE CASCADE,
    added_source VARCHAR(64) NOT NULL DEFAULT 'manual',
    added_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    CONSTRAINT uq_conn_pool_member UNIQUE (pool_id, connection_id)
);

CREATE INDEX IF NOT EXISTS idx_conn_pools_scope
    ON connection_pools (scope_atlas, scope_granularity);
CREATE INDEX IF NOT EXISTS idx_conn_pool_members_pool
    ON connection_pool_memberships (pool_id);
