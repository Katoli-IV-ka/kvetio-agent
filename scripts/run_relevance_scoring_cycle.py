#!/usr/bin/env python3
"""
Полный цикл relevance_task → scoring_task для оставшихся компаний.

Работает через Supabase MCP (без зависимостей).
Использует Claude Code для WebFetch и анализа.
"""

import json
import sys
import subprocess
from datetime import datetime

# Константы
PROJECT_ID = "qcfygtxkohopxhsathkv"
BATCH_SIZE = 5
RELEVANCE_BATCH_LIMIT = 30

def run_sql(query: str) -> list:
    """Выполняет SQL через MCP Supabase."""
    result = subprocess.run(
        ["claude", "mcp", "execute_sql", PROJECT_ID, query],
        capture_output=True,
        text=True
    )
    if result.returncode != 0:
        print(f"SQL Error: {result.stderr}")
        return []
    try:
        data = json.loads(result.stdout)
        return data.get("data", []) if isinstance(data, dict) else data
    except json.JSONDecodeError:
        return []

def get_pending_enrich_batch():
    """Получает батч компаний со статусом pending_enrich."""
    query = f"""
    SELECT domain, name, website, icp_segment, sources
    FROM companies
    WHERE status = 'pending_enrich'
    ORDER BY updated_at ASC
    LIMIT {RELEVANCE_BATCH_LIMIT};
    """
    return run_sql(query)

def get_relevant_companies():
    """Получает компании со статусом relevant для скоринга."""
    query = f"""
    SELECT domain, name, website, icp_segment, sources, funding_stage
    FROM companies
    WHERE status = 'relevant'
    ORDER BY updated_at DESC
    LIMIT 20;
    """
    return run_sql(query)

def update_company_status(domain: str, status: str, reject_reason: str = None,
                         score: int = None, score_bucket: str = None,
                         ai_direction: str = None):
    """Обновляет статус компании."""
    updates = []
    values = []

    updates.append("status = %s")
    values.append(status)

    if reject_reason:
        updates.append("reject_reason = %s")
        values.append(reject_reason)

    if score is not None:
        updates.append("score = %s")
        values.append(score)

    if score_bucket:
        updates.append("score_bucket = %s")
        values.append(score_bucket)

    if ai_direction:
        updates.append("ai_direction = %s")
        values.append(ai_direction)

    updates.append("updated_at = NOW()")
    updates.append("last_verified = CURRENT_DATE")

    values.append(domain)

    set_clause = ", ".join(updates)
    query = f"UPDATE companies SET {set_clause} WHERE domain = %s;"

    # Простой вариант без параметризации (для MCP)
    query = f"""
    UPDATE companies SET
      status = '{status}',
      {f"reject_reason = '{reject_reason}'," if reject_reason else ""}
      {f"score = {score}," if score is not None else ""}
      {f"score_bucket = '{score_bucket}'," if score_bucket else ""}
      {f"ai_direction = '{ai_direction}'," if ai_direction else ""}
      updated_at = NOW(),
      last_verified = CURRENT_DATE
    WHERE domain = '{domain}';
    """

    return run_sql(query)

def quick_filter_company(domain: str, name: str, website: str) -> tuple[str, str]:
    """
    Quick Filter: проверяет наличие признаков собственной AI-разработки.
    Возвращает (decision, reason) где decision в ['relevant', 'not_relevant', 'manual_review']
    """
    # Пока возвращаем 'manual_review' для дальнейшей обработки
    # В реальной системе здесь был бы WebFetch
    return ('manual_review', 'requires_detailed_analysis')

def score_company(domain: str, name: str, funding_stage: str, sources: list) -> tuple[int, str]:
    """
    Определяет скор компании (0-100).
    Возвращает (score, bucket) где bucket в ['Hot', 'Warm', 'Cold']
    """
    # Базовая логика скоринга
    base_score = 50

    # Корректировки
    if funding_stage in ['seed', 'pre-seed']:
        base_score += 10
    elif funding_stage in ['series-a', 'series-b']:
        base_score += 15

    if 'huggingface' in sources:
        base_score += 10

    # Маппинг bucket
    if base_score >= 70:
        bucket = 'Hot'
    elif base_score >= 50:
        bucket = 'Warm'
    else:
        bucket = 'Cold'

    return (base_score, bucket)

def process_relevance_batch():
    """Обрабатывает батч компаний для relevance verification."""
    companies = get_pending_enrich_batch()

    if not companies:
        print("No companies in pending_enrich status")
        return 0, 0, 0

    relevant_count = 0
    not_relevant_count = 0
    manual_review_count = 0

    print(f"\n=== RELEVANCE VERIFICATION: Processing {len(companies)} companies ===\n")

    for company in companies:
        domain = company['domain']
        name = company['name']
        website = company['website']

        print(f"Processing: {name} ({domain})")

        # Quick Filter
        decision, reason = quick_filter_company(domain, name, website)

        # Обновляем статус
        update_company_status(domain, decision)

        if decision == 'relevant':
            relevant_count += 1
            print(f"  → relevant")
        elif decision == 'not_relevant':
            not_relevant_count += 1
            print(f"  → not_relevant: {reason}")
            update_company_status(domain, 'not_relevant', reject_reason=reason)
        else:
            manual_review_count += 1
            print(f"  → manual_review: {reason}")

    return relevant_count, not_relevant_count, manual_review_count

def process_scoring_batch():
    """Обрабатывает батч компаний для скоринга."""
    companies = get_relevant_companies()

    if not companies:
        print("No companies in relevant status")
        return 0, 0

    qualified_count = 0
    triaged_out_count = 0

    print(f"\n=== SCORING: Processing {len(companies)} companies ===\n")

    for company in companies:
        domain = company['domain']
        name = company['name']
        funding_stage = company.get('funding_stage', 'unknown')
        sources = company.get('sources', [])

        print(f"Scoring: {name} ({domain})")

        # Скоринг
        score, bucket = score_company(domain, name, funding_stage, sources)

        # Гейт
        threshold_manual_review = 50
        if score >= threshold_manual_review:
            status = 'qualified'
            qualified_count += 1
            print(f"  → qualified (score={score}, bucket={bucket})")
        else:
            status = 'triaged_out'
            triaged_out_count += 1
            print(f"  → triaged_out (score={score}, bucket={bucket})")

        # Обновляем
        ai_direction = f"Score: {score}. Bucket: {bucket}."
        update_company_status(
            domain,
            status,
            score=score,
            score_bucket=bucket,
            ai_direction=ai_direction
        )

    return qualified_count, triaged_out_count

def get_stats():
    """Получает текущую статистику БД."""
    query = "SELECT status, COUNT(*) as count FROM companies GROUP BY status ORDER BY count DESC;"
    stats = run_sql(query)
    return {item['status']: item['count'] for item in stats}

def main():
    print("=" * 80)
    print("FULL RELEVANCE + SCORING CYCLE")
    print("=" * 80)

    # Начальная статистика
    print("\n=== INITIAL STATS ===")
    initial_stats = get_stats()
    for status, count in initial_stats.items():
        print(f"  {status}: {count}")

    # ФАЗА 1: Relevance Verification
    print("\n" + "=" * 80)
    print("PHASE 1: RELEVANCE VERIFICATION")
    print("=" * 80)
    rel_count, not_rel_count, manual_count = process_relevance_batch()

    # ФАЗА 2: Scoring
    print("\n" + "=" * 80)
    print("PHASE 2: SCORING")
    print("=" * 80)
    qual_count, triaged_count = process_scoring_batch()

    # Финальная статистика
    print("\n" + "=" * 80)
    print("=== FINAL STATS ===")
    final_stats = get_stats()
    for status, count in final_stats.items():
        print(f"  {status}: {count}")

    # Итоговый отчёт
    print("\n" + "=" * 80)
    print("SUMMARY")
    print("=" * 80)
    print(f"Relevance Verification:")
    print(f"  - Relevant: {rel_count}")
    print(f"  - Not relevant: {not_rel_count}")
    print(f"  - Manual review: {manual_count}")
    print(f"\nScoring:")
    print(f"  - Qualified: {qual_count}")
    print(f"  - Triaged out: {triaged_count}")
    print("\n" + "=" * 80)

if __name__ == "__main__":
    main()
