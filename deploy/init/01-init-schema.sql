CREATE TABLE IF NOT EXISTS id_mappings (
    internalid VARCHAR(255) PRIMARY KEY,
    "3dxid" VARCHAR(255) NOT NULL,
    content TEXT
);

-- Index for reverse lookup from 3DEXPERIENCE ID to internal ID
CREATE INDEX IF NOT EXISTS idx_3dxid ON id_mappings("3dxid");