-- 012_bot.sql — Telegram management bot tables
-- pipeline_runs: orchestration-level run record (above run_logs)
-- bot_users: allowlist + roles
-- bot_presets: named RunConfig presets
-- bot_dialog_state: /run wizard state (survives web restart)

CREATE TABLE IF NOT EXISTS pipeline_runs (
    id              UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    trigger_type    TEXT NOT NULL,                          -- manual | scheduled | api
    triggered_by    TEXT,                                   -- 'chat:<id>' | 'cron'
    config          JSONB NOT NULL,                         -- RunConfig
    status          TEXT NOT NULL DEFAULT 'queued',         -- draft|queued|running|succeeded|failed|cancelled
    queued_at       TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    started_at      TIMESTAMPTZ,
    finished_at     TIMESTAMPTZ,
    heartbeat_at    TIMESTAMPTZ,
    summary         JSONB,                                  -- counts, per-segment, hot_leads
    error           TEXT,
    tg_chat_id      TEXT,                                   -- live-message target
    tg_message_id   BIGINT                                  -- for editMessageText
);

CREATE INDEX IF NOT EXISTS idx_pipeline_runs_status    ON pipeline_runs (status);
CREATE INDEX IF NOT EXISTS idx_pipeline_runs_queued_at ON pipeline_runs (queued_at DESC);

-- bot_users: allowlist + roles
CREATE TABLE IF NOT EXISTS bot_users (
    chat_id     TEXT PRIMARY KEY,
    username    TEXT,
    role        TEXT NOT NULL DEFAULT 'viewer',             -- admin | viewer
    active      BOOLEAN NOT NULL DEFAULT TRUE,
    added_at    TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

-- bot_presets: named RunConfig snapshots
CREATE TABLE IF NOT EXISTS bot_presets (
    id          UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    name        TEXT UNIQUE NOT NULL,
    config      JSONB NOT NULL,
    owner       TEXT,
    is_default  BOOLEAN NOT NULL DEFAULT FALSE,
    created_at  TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

-- bot_dialog_state: /run wizard state per chat (survives web restart)
CREATE TABLE IF NOT EXISTS bot_dialog_state (
    chat_id     TEXT PRIMARY KEY,
    step        TEXT NOT NULL,
    draft       JSONB NOT NULL DEFAULT '{}'::jsonb,
    updated_at  TIMESTAMPTZ NOT NULL DEFAULT NOW()
);
