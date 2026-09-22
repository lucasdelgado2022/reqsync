CREATE TABLE IF NOT EXISTS id_mappings (
    internalid VARCHAR(255) PRIMARY KEY,
    "3dxid" VARCHAR(255) NOT NULL,
    parent_id VARCHAR(255) REFERENCES id_mappings(internalid) ON DELETE SET NULL,
    content TEXT
);

-- Index for parent lookups (essential for traversing trees/assemblies)
CREATE INDEX IF NOT EXISTS idx_parent_id ON id_mappings(parent_id);

-- Index for 3DX lookups
CREATE INDEX IF NOT EXISTS idx_3dxid ON id_mappings("3dxid");