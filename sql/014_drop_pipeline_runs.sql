-- Migration 013: drop pipeline_runs table (replaced by Claude Code Routines).
-- bot/worker.py and RunsStore have been removed; pipeline_runs is no longer used.
-- Preserves: bot_presets and run_logs.
-- Idempotent: IF EXISTS.

DROP TABLE IF EXISTS pipeline_runs;
