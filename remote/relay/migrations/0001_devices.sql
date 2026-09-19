-- Secrets are SHA-256 digests only. One activation = one computer + one phone.
CREATE TABLE devices (
    code_hash TEXT PRIMARY KEY,
    code_expires_at INTEGER NOT NULL,
    created_at INTEGER NOT NULL,
    id TEXT UNIQUE,
    write_hash TEXT UNIQUE,
    read_hash TEXT UNIQUE,
    pair_hash TEXT UNIQUE,
    pair_expires_at INTEGER,
    revoked INTEGER NOT NULL DEFAULT 0,
    received_at INTEGER NOT NULL DEFAULT 0,
    status_json TEXT
);
