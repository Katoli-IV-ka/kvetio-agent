-- Migration 015: drop selected unused DB objects.
--
-- User decision 2026-06-16:
-- - github_org_cache is not present in live DB and the cache layer is being removed.
-- - recent_leads and pipeline_stats are dashboard-only views with no live code consumers.
--
-- This migration intentionally does not drop companies scoring/status columns.
-- Idempotent: all drops use IF EXISTS.

DROP VIEW IF EXISTS recent_leads;
DROP VIEW IF EXISTS pipeline_stats;
DROP TABLE IF EXISTS github_org_cache;
