# Pipeline Run Report — 2026-06-15

**Status:** PARTIAL — Supabase/Telegram заблокированы; GitHub-discovery выполнен через MCP  
**Дата:** 2026-06-15  
**Сегментов:** 7  
**Источники:** github (единственный доступный)  

---

## Инфраструктурные блокеры (те же, что вчера)

| Компонент | Ошибка |
|---|---|
| **Supabase** | `403 Host not in allowlist: qcfygtxkohopxhsathkv.supabase.co` |
| **Telegram** | `403 Host not in allowlist: api.telegram.org` |
| **HuggingFace API** | `403 Host not in allowlist: huggingface.co` |
| **YC OSS API** | `403 Host not in allowlist: yc-oss.github.io` |
| **Greenhouse** | `403 Host not in allowlist: boards-api.greenhouse.io` |

GitHub Code Search (`api.github.com/search/code`) — **работает** при передаче `GITHUB_TOKEN`.  
GitHub MCP (`mcp__github__*`) — **работает**.

---

## Discover & Verify — результаты по сегментам

### medical-imaging — PARTIAL

| Компания | GitHub Org | Сигналы | Статус |
|---|---|---|---|
| dafne-imaging | `dafne-imaging` | 10 repos, DICOM models, медицинская сегментация | **pending_enrich** |
| NVIDIA Holoscan | `nvidia-holoscan` | 13 repos, sensor processing — дочерняя NVIDIA | not_relevant (too_large) |
| DIDSR/FDA | `DIDSR` | 109 repos, гос. организация (FDA) | not_relevant (government) |
| Open Geospatial Solutions | `opengeos` | геопространственные данные — нерелевантно | not_relevant (wrong_domain) |

Найдено: 4 | pending_enrich: 1 | not_relevant: 3

---

### autonomous-vehicles — LOW SIGNAL

Все 10 найденных org — академические лаборатории (Bonn, Toronto, Montreal, ZJU, BIT) или too_large (Meta Research).  
Сегмент требует YC Browser и Greenhouse для получения стартапов.  

Найдено: 10 | pending_enrich: 0 | not_relevant: 10

---

### speech-and-audio — PARTIAL

| Компания | GitHub Org | Сигналы | Статус |
|---|---|---|---|
| Preferred Networks | `pfnet-research` | 142 repos, JP робото/AI компания, ASR сигналы | **pending_enrich** |
| Kendryte (Canaan Inc) | `kendryte` | 59 repos, IoT AI chips (K210) — edge AI | manual_review |

Найдено: 10 | pending_enrich: 1 | manual_review: 1 | not_relevant: 8

---

### generative-ai — BEST SEGMENT

| Компания | GitHub Org | Score | Сигналы | Статус |
|---|---|---|---|---|
| **Wayve** | `wayveai` | 78 | 69 repos, AV + LLM, `Driving-with-LLMs`, UK startup | **pending_enrich** |
| **Lamini AI** | `lamini-ai` | 72 | 40 repos, LLM fine-tuning platform, US startup | **pending_enrich** |
| **Baichuan Inc** | `baichuan-inc` | 68 | 10 repos, 1051 followers, Baichuan-7B, Chinese LLM | **pending_enrich** |
| **Skit.ai** | `skit-ai` | 65 | 101 repos, Voice AI SaaS, LLM + speech | **pending_enrich** |
| DIVISIO | `DIVISIO-AI` | 45 | 10 repos, divis.io, German AI company | **pending_enrich** |
| Runhouse | `run-house` | 40 | 2 repos — ML infra, не buyer датасетов | triaged_out |

Найдено: 10 | pending_enrich: 5 | triaged_out: 1 | not_relevant: 4

---

### agriculture-ai — NO SIGNAL

GitHub Code Search не вернул org-владельцев для ключевых слов сегмента.  
Все 61 результата по `crop disease` — индивидуальные репозитории студентов.  
Сегмент требует других источников (YC, Crunchbase).  

Найдено: 0

---

### robotics-ai — LOW SIGNAL

| Компания | GitHub Org | Сигналы | Статус |
|---|---|---|---|
| Two Six Technologies | `twosixlabs` | 87 repos, defence/AI, US | manual_review |
| Остальные 9 | — | академические / нерелевантные | not_relevant |

Найдено: 10 | manual_review: 1 | not_relevant: 9

---

### video-photo-ai — PARTIAL

| Компания | GitHub Org | Score | Сигналы | Статус |
|---|---|---|---|---|
| **Sea AI Lab** | `sail-sg` | 52 | 101 repos, 776 followers, SE Asia AI research | **pending_enrich** |
| **Sony Research** | `SonyResearch` | 48 | 61 repos, 356 followers, micro_diffusion | **pending_enrich** |
| Tencent Hunyuan | `Tencent-Hunyuan` | — | too_large (Tencent) | not_relevant |
| Microsoft | `microsoft` | — | too_large | not_relevant |
| Остальные 6 | — | академические | not_relevant |

Найдено: 10 | pending_enrich: 2 | not_relevant: 8

---

## Scoring Summary

| Метрика | Значение |
|---|---|
| Сегментов всего | 7 |
| Открыто через GitHub | 5 |
| Нет сигналов | 2 (agriculture-ai, autonomous-vehicles) |
| Всего discovered | 54 |
| pending_enrich (Warm ≥45) | **9** |
| manual_review | 2 |
| triaged_out / not_relevant | 43 |

### Top qualified leads (Warm bucket)

| # | Компания | Сегмент | Score | Domain |
|---|---|---|---|---|
| 1 | **Wayve** | generative-ai / AV | 78 | wayve.ai |
| 2 | **Lamini AI** | generative-ai | 72 | — |
| 3 | **Baichuan Inc** | generative-ai | 68 | — |
| 4 | **Skit.ai** | generative-ai / speech | 65 | skit.ai |
| 5 | **dafne-imaging** | medical-imaging | 60 | — |
| 6 | **Preferred Networks** | speech-and-audio | 58 | — |
| 7 | **Sea AI Lab** | video-photo-ai | 52 | sail.sea.com |
| 8 | **Sony Research** | video-photo-ai | 48 | research.sony |
| 9 | **DIVISIO** | generative-ai | 45 | divis.io |

---

## SQL для ручной загрузки (когда Supabase будет доступен)

```sql
INSERT INTO companies (domain, name, website, status, icp_segment, sources, description, last_verified, updated_at)
VALUES
  ('wayve.ai', 'Wayve', 'https://wayve.ai', 'pending_enrich', 'generative-ai',
   '["github"]', 'UK AV+LLM startup, 69 repos, trains foundation models for autonomous driving',
   CURRENT_DATE, NOW()),

  ('lamini.ai', 'Lamini AI', 'https://lamini.ai', 'pending_enrich', 'generative-ai',
   '["github"]', 'US LLM fine-tuning platform, 40 repos, SpeechLLM and routing agents',
   CURRENT_DATE, NOW()),

  ('baichuan-ai.com', 'Baichuan Intelligent Technology', 'https://baichuan-ai.com', 'pending_enrich', 'generative-ai',
   '["github"]', 'Chinese LLM company, trains Baichuan-7B and larger models',
   CURRENT_DATE, NOW()),

  ('skit.ai', 'Skit.ai', 'https://skit.ai', 'pending_enrich', 'speech-and-audio',
   '["github"]', 'Voice AI SaaS, 101 repos, trains SpeechLLM for customer experience',
   CURRENT_DATE, NOW()),

  ('dafne-imaging.github.io', 'dafne-imaging', 'https://github.com/dafne-imaging', 'pending_enrich', 'medical-imaging',
   '["github"]', 'Medical imaging AI, 10 repos, DICOM-based segmentation models',
   CURRENT_DATE, NOW()),

  ('preferred.jp', 'Preferred Networks', 'https://preferred.jp', 'pending_enrich', 'speech-and-audio',
   '["github"]', 'Japanese robotics/AI company, pfnet-research, 142 repos',
   CURRENT_DATE, NOW()),

  ('sail.sea.com', 'Sea AI Lab', 'https://sail.sea.com', 'pending_enrich', 'video-photo-ai',
   '["github"]', 'Sea Ltd AI research lab, 101 repos, 776 followers, diffusion models',
   CURRENT_DATE, NOW()),

  ('research.sony', 'Sony Research', 'https://research.sony', 'pending_enrich', 'video-photo-ai',
   '["github"]', 'Sony AI research lab, 61 repos, micro_diffusion and generative models',
   CURRENT_DATE, NOW()),

  ('divis.io', 'DIVISIO', 'https://divis.io', 'pending_enrich', 'generative-ai',
   '["github"]', 'German AI company, 10 repos, tutorials and LLM classifier examples',
   CURRENT_DATE, NOW())
ON CONFLICT (domain) DO NOTHING;
```

---

## Что нужно сделать для полного pipeline

1. **Добавить в egress allowlist:**
   - `qcfygtxkohopxhsathkv.supabase.co` (критично — без этого не работает ничего)
   - `api.telegram.org` (уведомления)
   - `huggingface.co` (основной источник для 4 сегментов)
   - `yc-oss.github.io` (YC Browser — ключ для AV и medical стартапов)
   - `boards-api.greenhouse.io` (Greenhouse ATS)

2. **Agriculture-ai:** подключить Crunchbase/YC Browser — GitHub не даёт org-сигналов для этого сегмента

3. **Autonomous-vehicles:** те же источники (YC Browser, Greenhouse) — GitHub возвращает только академические лаборатории
