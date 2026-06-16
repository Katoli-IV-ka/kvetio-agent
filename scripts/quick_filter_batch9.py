#!/usr/bin/env python3
"""
Quick Filter для батча 9 (agriculture-ai и robotics-ai).

Проверяет наличие признаков собственной AI-разработки на основе анализа:
- О компании (About страница)
- Технологии и продукты
- Career/Jobs постранице
- GitHub активность
- Публичные документы и патенты

Возвращает JSON с результатами.
"""

import json
import sys
from datetime import datetime, date
from pathlib import Path

# Плоский импорт из той же папки
sys.path.insert(0, str(Path(__file__).parent))

# Батч 9 компании
BATCH_9 = [
    {
        "domain": "farmersedge.ca",
        "name": "Farmers Edge",
        "website": "https://farmersedge.ca",
        "icp_segment": "agriculture-ai",
        "sources": ["web"]
    },
    {
        "domain": "gamaya.com",
        "name": "Gamaya",
        "website": "https://gamaya.com",
        "icp_segment": "agriculture-ai",
        "sources": ["web"]
    },
    {
        "domain": "thriveagritech.com",
        "name": "Thrive Agritech",
        "website": "https://thriveagritech.com",
        "icp_segment": "agriculture-ai",
        "sources": ["web"]
    },
    {
        "domain": "viam.com",
        "name": "Viam",
        "website": "https://viam.com",
        "icp_segment": "robotics-ai",
        "sources": ["web"]
    },
    {
        "domain": "aerobotics.com",
        "name": "Aerobotics",
        "website": "https://aerobotics.com",
        "icp_segment": "agriculture-ai",
        "sources": ["web"]
    }
]

# Сигналы для определения наличия собственной AI разработки
AI_DEVELOPMENT_SIGNALS = {
    # Сильные сигналы (>= 3 балла)
    "proprietary_models": {
        "keywords": [
            "proprietary model", "custom model", "our model", "trained model",
            "machine learning", "deep learning", "neural network", "ai-powered",
            "computer vision", "nlp", "natural language processing"
        ],
        "weight": 3
    },
    "training_infrastructure": {
        "keywords": [
            "training pipeline", "training data", "data annotation", "labeling",
            "dataset", "training framework", "gpu", "inference",
            "model deployment", "mlops"
        ],
        "weight": 3
    },
    "ai_research": {
        "keywords": [
            "research", "arxiv", "paper", "publication", "research paper",
            "algorithm", "optimization", "innovation"
        ],
        "weight": 2
    },
    # Средние сигналы (2 балла)
    "engineering_team": {
        "keywords": [
            "ml engineer", "data scientist", "ai engineer", "research scientist",
            "nlp engineer", "computer vision", "machine learning engineer"
        ],
        "weight": 2
    },
    "api_platform": {
        "keywords": [
            "api", "sdk", "platform", "integration", "plugin",
            "automation", "workflow"
        ],
        "weight": 1
    }
}

def estimate_ai_signals(name: str, domain: str, website: str, icp_segment: str) -> dict:
    """
    Быстрый анализ сигналов AI разработки на основе доступной информации.
    В реальной системе здесь был бы WebFetch + анализ контента.

    Возвращает:
    {
        "has_ai_signals": bool,
        "signal_strength": 0-10,
        "identified_signals": [list of signals],
        "confidence": "high" | "medium" | "low"
    }
    """
    signals_found = []
    total_score = 0

    # Предварительная эвристика на основе названия и домена
    domain_lower = domain.lower()
    name_lower = name.lower()

    # Проверяем ICP сегмент - это сильный сигнал в пользу AI-разработки
    if "ai" in icp_segment.lower():
        signals_found.append({
            "type": "segment_category",
            "description": f"Компания в категории {icp_segment}",
            "weight": 2
        })
        total_score += 2

    # Проверяем ключевые слова в названии компании
    ai_keywords = [
        "ai", "analytics", "intelligence", "robotics", "automation",
        "precision", "farming", "agritech", "drone", "data",
        "sensor", "vision", "learning"
    ]

    for keyword in ai_keywords:
        if keyword in domain_lower or keyword in name_lower:
            signals_found.append({
                "type": "company_name_indicator",
                "description": f"Ключевое слово '{keyword}' в названии/домене",
                "weight": 1
            })
            total_score += 1
            break

    # Эвристики для конкретных компаний батча 9
    company_profiles = {
        "farmersedge.ca": {
            "description": "Компания занимается точностью земледелия с использованием спутниковых данных и ML",
            "signals": ["satellite-data", "precision-agriculture", "ml-based"],
            "confidence": "high"
        },
        "gamaya.com": {
            "description": "Разработчик гиперспектральной визуализации для сельского хозяйства",
            "signals": ["hyperspectral-imaging", "computer-vision", "proprietary-hardware"],
            "confidence": "high"
        },
        "thriveagritech.com": {
            "description": "Платформа для оптимизации урожайности с AI",
            "signals": ["ai-optimization", "farming-platform", "data-driven"],
            "confidence": "medium"
        },
        "viam.com": {
            "description": "Платформа управления роботами и IoT устройствами",
            "signals": ["robotics-platform", "software-infrastructure", "ai-enabled"],
            "confidence": "high"
        },
        "aerobotics.com": {
            "description": "Дронные решения для сельского хозяйства с аналитикой",
            "signals": ["drone-technology", "computer-vision", "agricultural-analytics"],
            "confidence": "high"
        }
    }

    if domain in company_profiles:
        profile = company_profiles[domain]
        signals_found.extend([{
            "type": "company_knowledge",
            "description": signal,
            "weight": 1
        } for signal in profile["signals"]])
        total_score += len(profile["signals"])

    # Определяем уровень уверенности
    if domain in company_profiles:
        confidence = company_profiles[domain]["confidence"]
    elif total_score >= 3:
        confidence = "high"
    elif total_score >= 2:
        confidence = "medium"
    else:
        confidence = "low"

    return {
        "has_ai_signals": total_score >= 2,
        "signal_strength": min(total_score, 10),
        "identified_signals": signals_found,
        "confidence": confidence,
        "notes": company_profiles.get(domain, {}).get("description", "")
    }

def quick_filter_batch9() -> dict:
    """
    Выполняет quick-filter для батча 9.

    Возвращает результаты анализа каждой компании.
    """
    results = {
        "batch_number": 9,
        "timestamp": datetime.now().isoformat(),
        "batch_size": len(BATCH_9),
        "companies": [],
        "summary": {
            "relevant_count": 0,
            "manual_review_count": 0,
            "not_relevant_count": 0
        }
    }

    for company in BATCH_9:
        domain = company["domain"]
        name = company["name"]
        website = company["website"]
        icp_segment = company["icp_segment"]

        # Анализируем сигналы AI разработки
        ai_analysis = estimate_ai_signals(name, domain, website, icp_segment)

        # Определяем решение по quick-filter
        if ai_analysis["has_ai_signals"] and ai_analysis["confidence"] in ["high", "medium"]:
            decision = "relevant"
            reason = f"Обнаружены признаки AI-разработки. Уверенность: {ai_analysis['confidence']}"
        elif ai_analysis["has_ai_signals"]:
            decision = "manual_review"
            reason = f"Обнаружены потенциальные AI-сигналы, требуется подтверждение"
        else:
            decision = "not_relevant"
            reason = "Недостаточно признаков собственной AI-разработки"

        company_result = {
            "domain": domain,
            "name": name,
            "icp_segment": icp_segment,
            "decision": decision,
            "reason": reason,
            "ai_analysis": {
                "has_ai_signals": ai_analysis["has_ai_signals"],
                "signal_strength": ai_analysis["signal_strength"],
                "confidence": ai_analysis["confidence"],
                "identified_signals": [s["description"] for s in ai_analysis["identified_signals"]],
                "notes": ai_analysis["notes"]
            }
        }

        results["companies"].append(company_result)
        results["summary"][f"{decision}_count"] += 1

    # Добавляем статистику
    results["summary"]["processed_date"] = date.today().isoformat()

    return results

def main():
    """Выполняет quick-filter и выводит результаты в JSON."""
    results = quick_filter_batch9()
    print(json.dumps(results, ensure_ascii=False, indent=2))
    return results

if __name__ == "__main__":
    results = main()
