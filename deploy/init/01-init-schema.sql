-- Core requirement object table
CREATE TABLE IF NOT EXISTS id_mappings (
    internalid VARCHAR(255) PRIMARY KEY,
    "3dxid" VARCHAR(255) NOT NULL,
    content TEXT
);

CREATE INDEX IF NOT EXISTS idx_3dxid ON id_mappings("3dxid");

-- Relationship junction table (supports multiple parents per child)
CREATE TABLE IF NOT EXISTS requirement_connections (
    id SERIAL PRIMARY KEY,
    child_id VARCHAR(255) NOT NULL REFERENCES id_mappings(internalid) ON DELETE CASCADE,
    parent_id VARCHAR(255) NOT NULL REFERENCES id_mappings(internalid) ON DELETE CASCADE,
    connection_3dx_id VARCHAR(255),
    CONSTRAINT uq_child_parent UNIQUE (child_id, parent_id)
);

CREATE INDEX IF NOT EXISTS idx_conn_child ON requirement_connections(child_id);
CREATE INDEX IF NOT EXISTS idx_conn_parent ON requirement_connections(parent_id);
CREATE INDEX IF NOT EXISTS idx_conn_3dxid ON requirement_connections(connection_3dx_id);