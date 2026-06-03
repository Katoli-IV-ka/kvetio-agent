-- Migration 004: добавить source_page_url в таблицу signals
ALTER TABLE signals
    ADD COLUMN IF NOT EXISTS source_page_url TEXT;

COMMENT ON COLUMN signals.source_page_url IS
    'URL страницы компании в источнике (HF, YC, Greenhouse, GitHub). '
    'Отличается от evidence_url у Greenhouse: evidence_url = вакансия, '
    'source_page_url = board-страница компании.';
