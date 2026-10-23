-- Core requirement object table
CREATE TABLE IF NOT EXISTS id_mappings (
    internalid VARCHAR(255) PRIMARY KEY,
    "3dxid" VARCHAR(255),
    previous_3dxid VARCHAR(255),
    content TEXT,
    object_type VARCHAR(64) NOT NULL,
    active BOOLEAN NOT NULL DEFAULT TRUE,
    release_pending BOOLEAN NOT NULL DEFAULT FALSE
);

CREATE INDEX IF NOT EXISTS idx_3dxid ON id_mappings("3dxid");

-- Relationship junction table (supports multiple parents per child)
CREATE TABLE IF NOT EXISTS requirement_connections (
    id SERIAL PRIMARY KEY,
    child_id VARCHAR(255) NOT NULL REFERENCES id_mappings(internalid) ON DELETE CASCADE,
    parent_id VARCHAR(255) NOT NULL REFERENCES id_mappings(internalid) ON DELETE CASCADE,
    connection_3dx_id VARCHAR(255),
    position INTEGER NOT NULL DEFAULT 0,
    CONSTRAINT uq_child_parent UNIQUE (child_id, parent_id)
);

CREATE INDEX IF NOT EXISTS idx_conn_child ON requirement_connections(child_id);
CREATE INDEX IF NOT EXISTS idx_conn_parent ON requirement_connections(parent_id);
CREATE INDEX IF NOT EXISTS idx_conn_3dxid ON requirement_connections(connection_3dx_id);

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