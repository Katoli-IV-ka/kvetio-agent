-- Migration 016: default Telegram quickrun preset limit.
--
-- Code defaults now use 5 companies per segment. Existing Supabase projects may
-- already have the seeded nightly-full preset with limit_per_segment = 30, and
-- ensure_seed_presets() intentionally does not overwrite user-created presets.
-- This targeted migration updates only the original seed value.

UPDATE bot_presets
SET config = jsonb_set(config, '{limit_per_segment}', '5'::jsonb, true)
WHERE name = 'nightly-full'
  AND config->>'limit_per_segment' = '30';
