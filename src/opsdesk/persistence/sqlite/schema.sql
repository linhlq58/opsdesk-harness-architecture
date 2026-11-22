-- OpsDesk SQLite schema, version 1 (M01).
--
-- Conventions
--   * Tenant data has a composite primary key (tenant_id, id): tenant is identity.
--   * Timestamps are TEXT in one fixed UTC format: YYYY-MM-DDTHH:MM:SS.ffffffZ
--     Fixed width means string order == time order, so ORDER BY created_at is correct.
--   * Money is two columns: amount as TEXT (exact decimal, never REAL) + currency.
--   * Sets (roles, owned_software, restricted_to) are JSON arrays, sorted.
--   * No foreign keys between entities: referential checks live in the seed loader and
--     services, so this adapter behaves exactly like the in-memory one (contract tests).
--   * CHECK constraints are a last line of defence; the domain models validate first.
--
-- Every statement is idempotent (IF NOT EXISTS), so applying the schema twice is safe.

CREATE TABLE IF NOT EXISTS schema_version (
    version INTEGER NOT NULL
);

CREATE TABLE IF NOT EXISTS tenants (
    id   TEXT PRIMARY KEY,
    name TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS employees (
    tenant_id      TEXT NOT NULL,
    id             TEXT NOT NULL,
    full_name      TEXT NOT NULL,
    email          TEXT NOT NULL,
    department     TEXT NOT NULL,
    roles          TEXT NOT NULL,   -- JSON array
    owned_software TEXT NOT NULL,   -- JSON array
    PRIMARY KEY (tenant_id, id)
);

CREATE TABLE IF NOT EXISTS software (
    id                   TEXT PRIMARY KEY,
    name                 TEXT NOT NULL,
    annual_cost_amount   TEXT NOT NULL,
    annual_cost_currency TEXT NOT NULL,
    restricted_to        TEXT NOT NULL,   -- JSON array, empty = everyone
    requires_admin       INTEGER NOT NULL CHECK (requires_admin IN (0, 1))
);

CREATE TABLE IF NOT EXISTS tickets (
    tenant_id   TEXT NOT NULL,
    id          TEXT NOT NULL,
    reporter_id TEXT NOT NULL,
    assignee_id TEXT,
    title       TEXT NOT NULL,
    description TEXT NOT NULL,
    category    TEXT NOT NULL,
    priority    TEXT NOT NULL,
    status      TEXT NOT NULL CHECK (
        status IN ('open', 'in_progress', 'waiting_on_user', 'resolved', 'closed')
    ),
    asset_tag   TEXT,
    created_at  TEXT NOT NULL,
    updated_at  TEXT NOT NULL,
    PRIMARY KEY (tenant_id, id)
);

CREATE INDEX IF NOT EXISTS ix_tickets_reporter
    ON tickets (tenant_id, reporter_id, created_at);

CREATE TABLE IF NOT EXISTS access_requests (
    tenant_id     TEXT NOT NULL,
    id            TEXT NOT NULL,
    requester_id  TEXT NOT NULL,
    kind          TEXT NOT NULL CHECK (kind IN ('software_licence', 'admin_rights')),
    software_id   TEXT,
    justification TEXT NOT NULL,
    status        TEXT NOT NULL CHECK (
        status IN ('pending_approval', 'approved', 'rejected', 'cancelled')
    ),
    decided_by    TEXT,
    decided_at    TEXT,
    created_at    TEXT NOT NULL,
    PRIMARY KEY (tenant_id, id)
);

CREATE INDEX IF NOT EXISTS ix_access_requests_status
    ON access_requests (tenant_id, status, created_at);
