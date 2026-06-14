# Pipeline Run Report — 2026-06-14

**Status:** PARTIAL FAILURE — критические инфраструктурные блокеры  
**Дата:** 2026-06-14  
**Сегментов:** 7  

---

## Инфраструктурные блокеры (критические)

| Компонент | Ошибка | Влияние |
|---|---|---|
| **Supabase** | `403 Forbidden` — хост `qcfygtxkohopxhsathkv.supabase.co` не в egress allowlist | Невозможно читать/писать данные, скоринг невозможен |
| **Telegram** | `403 Forbidden` на bot token | Уведомления не доставляются |
| **Source scripts** | `403` на huggingface.co, github.com, yc-oss API — заблокированы egress policy | Все адаптеры-скрипты падают |

**Необходимые действия:**
1. Добавить `qcfygtxkohopxhsathkv.supabase.co` в network egress allowlist среды выполнения
2. Проверить `TELEGRAM_BOT_TOKEN` — бот возможно заблокирован или токен истёк
3. Добавить `huggingface.co`, `api.github.com`, `api.github.com/orgs`, `yc-oss.github.io` в egress allowlist

---

## Результаты по сегментам

### medical-imaging — ERROR
- Источники: все заблокированы
- Найдено: 0 / Сохранено: 0

### autonomous-vehicles — ERROR
- Источники: все заблокированы
- Найдено: 0 / Сохранено: 0

### speech-and-audio — PARTIAL (только HF MCP)

| Компания | HF Org | Сигналы |
|---|---|---|
| Argmax Inc | `argmaxinc` | 5.9M скачиваний whisperkit-coreml, US startup, ASR on-device |
| Systran | `Systran` | faster-whisper, 634K–989K downloads, EU/France |
| Kyutai | `kyutai` | pocket-tts, arxiv:2509.06926, French AI lab |

Найдено: 3 | Сохранено в Supabase: 0 (заблокировано)

### generative-ai — PARTIAL (только HF MCP)

| Компания | HF Org | Сигналы |
|---|---|---|
| Mistral AI | `mistralai` | 2.2M downloads Mistral-7B-v0.3, EU/France, Series B |
| DeepSeek AI | `deepseek-ai` | 21.5K downloads, trains own LLMs (CN) |
| LLM360 | `LLM360` | K2-Chat, transparent LLM training, US |
| Trendyol | `Trendyol` | Turkish LLM models (TR — не в ICP географиях) |

Найдено: 4 | Сохранено в Supabase: 0 (заблокировано)

### agriculture-ai — ERROR
- Источники: все заблокированы, HF MCP не вернул релевантных организаций
- Найдено: 0 / Сохранено: 0

### robotics-ai — ERROR
- Источники: все заблокированы, HF MCP не вернул релевантных организаций
- Найдено: 0 / Сохранено: 0

### video-photo-ai — PARTIAL (только HF MCP)

| Компания | HF Org | Сигналы |
|---|---|---|
| Stability AI | `stabilityai` | 1M downloads SDXL, stable-video-diffusion, UK/US |

Найдено: 1 | Сохранено в Supabase: 0 (заблокировано)

---

## Итоги

| Метрика | Значение |
|---|---|
| Сегментов всего | 7 |
| Сегментов OK | 0 |
| Сегментов PARTIAL | 3 |
| Сегментов ERROR | 4 |
| Найдено (HF MCP) | 8 |
| Сохранено в Supabase | 0 |
| Enriched / Notion | 0 |
| Критических ошибок | 3 |

---

## Что нужно сделать вручную

Когда Supabase станет доступен — загрузить эти 8 компаний через:
```sql
-- Примеры для speech-and-audio
INSERT INTO companies (domain, name, website, status, icp_segment, sources, description)
VALUES
  ('argmaxinc.com', 'Argmax Inc', 'https://argmaxinc.com', 'pending_enrich', 'speech-and-audio', '["huggingface"]', 'On-device ASR/ML startup, 5.9M HF downloads on whisperkit-coreml'),
  ('systran.net', 'Systran', 'https://systran.net', 'pending_enrich', 'speech-and-audio', '["huggingface"]', 'French translation/speech company, trains faster-whisper models'),
  ('kyutai.org', 'Kyutai', 'https://kyutai.org', 'pending_enrich', 'speech-and-audio', '["huggingface"]', 'French AI lab, trains own TTS models'),
  ('mistral.ai', 'Mistral AI', 'https://mistral.ai', 'pending_enrich', 'generative-ai', '["huggingface"]', 'EU AI company, trains own LLMs (Mistral, Mixtral)'),
  ('deepseek.com', 'DeepSeek AI', 'https://deepseek.com', 'pending_enrich', 'generative-ai', '["huggingface"]', 'Chinese AI lab, trains own LLMs'),
  ('llm360.ai', 'LLM360', 'https://llm360.ai', 'pending_enrich', 'generative-ai', '["huggingface"]', 'US transparent LLM training initiative'),
  ('stability.ai', 'Stability AI', 'https://stability.ai', 'pending_enrich', 'video-photo-ai', '["huggingface"]', 'UK/US, trains stable-diffusion and stable-video-diffusion')
ON CONFLICT (domain) DO NOTHING;
```
