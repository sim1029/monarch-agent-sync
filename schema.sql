-- monarch-agent-sync schema
-- Run this once against your Supabase project (Dashboard → SQL Editor)
-- or add it as a migration in your supabase/migrations/ folder.

-- ── Accounts ─────────────────────────────────────────────────────────────────
CREATE TABLE IF NOT EXISTS public.monarch_accounts (
    id                  TEXT PRIMARY KEY,          -- Monarch's account ID
    name                TEXT NOT NULL,
    institution_name    TEXT,
    type                TEXT,                      -- e.g. "checking", "investment"
    subtype             TEXT,
    current_balance     NUMERIC(14,2),
    currency            TEXT DEFAULT 'USD',
    is_closed           BOOLEAN DEFAULT false,
    is_hidden           BOOLEAN DEFAULT false,
    synced_at           TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

-- ── Transactions ──────────────────────────────────────────────────────────────
CREATE TABLE IF NOT EXISTS public.monarch_transactions (
    id                  TEXT PRIMARY KEY,          -- Monarch's transaction ID
    account_id          TEXT REFERENCES public.monarch_accounts(id),
    date                DATE NOT NULL,
    merchant_name       TEXT,
    original_name       TEXT,
    amount              NUMERIC(14,2) NOT NULL,    -- negative = expense, positive = income
    category            TEXT,
    category_group      TEXT,
    is_pending          BOOLEAN DEFAULT false,
    notes               TEXT,
    synced_at           TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS monarch_transactions_date_idx
    ON public.monarch_transactions (date DESC);
CREATE INDEX IF NOT EXISTS monarch_transactions_account_idx
    ON public.monarch_transactions (account_id);

-- ── Balance snapshots ─────────────────────────────────────────────────────────
-- One row per account per sync — lets the agent track net worth over time
CREATE TABLE IF NOT EXISTS public.monarch_balance_snapshots (
    id                  BIGSERIAL PRIMARY KEY,
    account_id          TEXT REFERENCES public.monarch_accounts(id),
    balance             NUMERIC(14,2) NOT NULL,
    snapshot_date       DATE NOT NULL DEFAULT CURRENT_DATE,
    synced_at           TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    UNIQUE (account_id, snapshot_date)             -- one snapshot per account per day
);

CREATE INDEX IF NOT EXISTS monarch_balance_snapshots_date_idx
    ON public.monarch_balance_snapshots (snapshot_date DESC);

-- ── Sync log ─────────────────────────────────────────────────────────────────
-- Tracks each run so the agent knows how fresh the data is
CREATE TABLE IF NOT EXISTS public.monarch_sync_log (
    id                  BIGSERIAL PRIMARY KEY,
    started_at          TIMESTAMPTZ NOT NULL,
    finished_at         TIMESTAMPTZ,
    accounts_synced     INTEGER DEFAULT 0,
    transactions_synced INTEGER DEFAULT 0,
    snapshots_written   INTEGER DEFAULT 0,
    status              TEXT DEFAULT 'running',    -- running | success | error
    error_message       TEXT
);
