-- Migration 002: GitHub org metadata cache
-- Stores raw /orgs/{login} API responses with a 30-day TTL managed in Python.

CREATE TABLE IF NOT EXISTS github_org_cache (
    org_login   TEXT PRIMARY KEY,
    data        JSONB NOT NULL,
    cached_at   TIMESTAMPTZ NOT NULL DEFAULT now()
);

COMMENT ON TABLE github_org_cache IS
  'Cache for GitHub /orgs/{login} API responses. TTL enforced in Python (30 days).';
COMMENT ON COLUMN github_org_cache.org_login IS 'GitHub organization login (slug), e.g. "openai"';
COMMENT ON COLUMN github_org_cache.data IS 'Raw JSON response from GET /orgs/{login}';
COMMENT ON COLUMN github_org_cache.cached_at IS 'Timestamp when entry was last fetched and stored';
