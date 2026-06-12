-- Migration 006: таблица contacts — ЛПР для аутрича
-- Stage 2.5 в pipeline: компания прошла квалификацию → находим конкретных людей.
--
-- Применить в Supabase SQL Editor.
-- Идемпотентный: IF NOT EXISTS / DO NOTHING.
-- Зависит от: 001_init.sql (таблица companies, функция update_updated_at)

-- ─── Основная таблица ──────────────────────────────────────────────────────

CREATE TABLE IF NOT EXISTS contacts (
    id                  UUID PRIMARY KEY DEFAULT gen_random_uuid(),

    -- Связь с компанией (soft FK — не ломает при удалении компании из-за статус-машины)
    company_domain      TEXT NOT NULL,

    -- Идентификация
    full_name           TEXT NOT NULL,
    first_name          TEXT,
    last_name           TEXT,

    -- Роль
    title               TEXT,               -- raw title с источника: "Head of ML Platform"
    title_normalized    TEXT,               -- нормализованная категория: "Head of ML" / "CTO" / "Research Lead"
    dm_priority         INTEGER NOT NULL DEFAULT 2
        CHECK (dm_priority BETWEEN 1 AND 3),
    -- 1 = прямой покупатель данных (Head of Data, VP ML, Head of AI)
    -- 2 = influencer (CTO, Co-founder, Research Lead)
    -- 3 = точка входа (Senior ML Engineer, Data Scientist)

    -- Каналы связи
    email               TEXT,
    email_status        TEXT NOT NULL DEFAULT 'unknown'
        CHECK (email_status IN ('verified', 'guessed', 'bounced', 'unknown')),
    -- verified  = прошёл SMTP-верификацию (ZeroBounce / Apollo)
    -- guessed   = сгенерирован по паттерну, не верифицирован
    -- bounced   = верифицирован как несуществующий
    -- unknown   = нет данных
    email_source        TEXT,               -- 'github_commit' / 'apollo' / 'team_page' / 'pattern_verified' / ...
    linkedin_url        TEXT,
    twitter_handle      TEXT,               -- без @
    github_username     TEXT,

    -- Откуда взят контакт
    source_vector       TEXT NOT NULL
        CHECK (source_vector IN (
            'github',           -- GitHub org members + commit emails
            'huggingface',      -- HuggingFace org members
            'team_page',        -- Scraping website /team /about
            'apollo',           -- Apollo.io API
            'wellfound',        -- Wellfound (AngelList)
            'arxiv'             -- arXiv / Papers with Code
        )),
    source_url          TEXT,               -- URL где нашли контакт (evidence)
    confidence          TEXT NOT NULL DEFAULT 'medium'
        CHECK (confidence IN ('high', 'medium', 'low')),
    -- high   = прямое подтверждение роли + верифицированный email
    -- medium = роль известна, email не верифицирован
    -- low    = только имя / неясная роль

    -- Статус аутрича (заполняется вручную в Notion или через будущий CRM)
    outreach_status     TEXT NOT NULL DEFAULT 'not_contacted'
        CHECK (outreach_status IN (
            'not_contacted',    -- ещё не писали
            'contacted',        -- отправили сообщение, ждём
            'replied',          -- ответил (любой ответ)
            'not_interested',   -- явный отказ
            'converted'         -- стал клиентом / назначил встречу
        )),
    outreach_note       TEXT,               -- ручная заметка оператора

    -- Сырые данные для аудита
    raw_payload         JSONB NOT NULL DEFAULT '{}'::jsonb,

    -- Временны́е метки
    created_at          TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at          TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

-- ─── Индексы ─────────────────────────────────────────────────────────────

-- Ключ дедупликации: один человек на компанию
-- UNIQUE по (domain, lower(full_name)) — case-insensitive
CREATE UNIQUE INDEX IF NOT EXISTS idx_contacts_dedup
    ON contacts (company_domain, lower(full_name));

-- Быстрый доступ ко всем контактам компании
CREATE INDEX IF NOT EXISTS idx_contacts_company_domain
    ON contacts (company_domain);

-- Приоритет для операционного просмотра
CREATE INDEX IF NOT EXISTS idx_contacts_priority
    ON contacts (dm_priority, company_domain);

-- Фильтр по статусу email (только записи с email)
CREATE INDEX IF NOT EXISTS idx_contacts_email_status
    ON contacts (email_status)
    WHERE email IS NOT NULL;

-- Очередь аутрича
CREATE INDEX IF NOT EXISTS idx_contacts_outreach
    ON contacts (outreach_status)
    WHERE outreach_status = 'not_contacted';

-- Источник (для анализа качества векторов)
CREATE INDEX IF NOT EXISTS idx_contacts_source_vector
    ON contacts (source_vector);

-- ─── Автообновление updated_at ────────────────────────────────────────────

-- Функция update_updated_at уже создана в 001_init.sql
DROP TRIGGER IF EXISTS trg_contacts_updated_at ON contacts;
CREATE TRIGGER trg_contacts_updated_at
BEFORE UPDATE ON contacts
FOR EACH ROW EXECUTE FUNCTION update_updated_at();

-- ─── Комментарии ─────────────────────────────────────────────────────────

COMMENT ON TABLE contacts IS
    'ЛПР (лица принимающие решения) для каждой квалифицированной компании. '
    'Заполняется Stage 2.5 (DM Enrichment) из 5 источников: '
    'GitHub, HuggingFace, team pages, Apollo.io, Wellfound, arXiv.';

COMMENT ON COLUMN contacts.company_domain IS
    'Нормализованный домен компании — soft FK на companies.domain. '
    'Soft (не REFERENCES) чтобы не блокировать удаление/архивацию компаний.';

COMMENT ON COLUMN contacts.dm_priority IS
    '1=прямой покупатель данных, 2=influencer/champion, 3=точка входа. '
    'Определяется LLM на основе title_normalized.';

COMMENT ON COLUMN contacts.email_status IS
    'verified=прошёл SMTP-проверку, guessed=паттерн без проверки, '
    'bounced=не существует, unknown=нет данных.';

COMMENT ON COLUMN contacts.source_vector IS
    'Вектор, через который найден контакт. Используется для анализа '
    'эффективности каждого источника.';

COMMENT ON COLUMN contacts.raw_payload IS
    'Сырой ответ от источника. Для GitHub: поля /users/{login}. '
    'Для Apollo: поля people object. Используется для аудита и дообогащения.';
