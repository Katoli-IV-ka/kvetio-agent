-- 015_drop_bot_runtime_state.sql
-- Remove Telegram bot runtime state that is no longer read by the bot.
-- Keep bot_presets because /presets and /quickrun use it.

DROP TABLE IF EXISTS bot_users;
DROP TABLE IF EXISTS bot_dialog_state;
