ALTER TABLE id_mappings
    ADD COLUMN IF NOT EXISTS active BOOLEAN NOT NULL DEFAULT TRUE;

ALTER TABLE id_mappings
    ADD COLUMN IF NOT EXISTS release_pending BOOLEAN NOT NULL DEFAULT FALSE;

CREATE TABLE IF NOT EXISTS object_revision_history (
    history_id BIGSERIAL PRIMARY KEY,
    internalid VARCHAR(255) NOT NULL REFERENCES id_mappings(internalid),
    "3dxid" VARCHAR(255) NOT NULL,
    content TEXT,
    object_type VARCHAR(64) NOT NULL,
    recorded_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,
    UNIQUE (internalid, "3dxid")
);

CREATE INDEX IF NOT EXISTS idx_revision_history_3dxid
    ON object_revision_history("3dxid");

CREATE TABLE IF NOT EXISTS connection_history (
    history_id BIGSERIAL PRIMARY KEY,
    child_id VARCHAR(255) NOT NULL REFERENCES id_mappings(internalid),
    parent_id VARCHAR(255) NOT NULL REFERENCES id_mappings(internalid),
    connection_3dx_id VARCHAR(255),
    recorded_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP
);

CREATE INDEX IF NOT EXISTS idx_connection_history_3dxid
    ON connection_history(connection_3dx_id);
