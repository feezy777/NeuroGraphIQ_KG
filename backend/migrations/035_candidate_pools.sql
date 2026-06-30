-- 035: Candidate Pools — cross-batch candidate accumulation for extraction
-- Manual execution only; the app does not auto-run this file.

CREATE TABLE IF NOT EXISTS candidate_pools (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    name VARCHAR(256),
    resource_id UUID REFERENCES atlas_resources(id) ON DELETE SET NULL,
    batch_id UUID REFERENCES import_batches(id) ON DELETE SET NULL,
    source_atlas VARCHAR(128) NOT NULL,
    granularity_level VARCHAR(32) NOT NULL,
    granularity_family VARCHAR(64),
    candidate_count INT NOT NULL DEFAULT 0,
    pair_count INT NOT NULL DEFAULT 0,
    status VARCHAR(32) NOT NULL DEFAULT 'active',
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

COMMENT ON TABLE candidate_pools IS 'Cross-batch candidate accumulation pools for LLM extraction';
COMMENT ON COLUMN candidate_pools.status IS 'active | locked | archived';

CREATE TABLE IF NOT EXISTS candidate_pool_memberships (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    pool_id UUID NOT NULL REFERENCES candidate_pools(id) ON DELETE CASCADE,
    candidate_id UUID NOT NULL REFERENCES candidate_brain_regions(id) ON DELETE CASCADE,
    added_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    added_by VARCHAR(128),
    UNIQUE(pool_id, candidate_id)
);

COMMENT ON TABLE candidate_pool_memberships IS 'Many-to-many membership linking candidate_pools to candidate_brain_regions';

CREATE INDEX IF NOT EXISTS idx_candidate_pools_status ON candidate_pools(status);
CREATE INDEX IF NOT EXISTS idx_candidate_pools_source_atlas ON candidate_pools(source_atlas);
CREATE INDEX IF NOT EXISTS idx_candidate_pool_memberships_pool ON candidate_pool_memberships(pool_id);
CREATE INDEX IF NOT EXISTS idx_candidate_pool_memberships_candidate ON candidate_pool_memberships(candidate_id);
