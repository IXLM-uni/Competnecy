# -*- coding: utf-8 -*-
"""
Руководство к файлу UC_17.py
=============================

Назначение:
    Реализация UC-17: Анализ цитирований статьи (Citation Graph Analysis).
    Тонкий клиент — вся S2-логика делегирована S2Client из llm_service.py.
    Pipeline:
        1. S2Client.get_paper — загрузка метаданных статьи
        2. S2Client.get_paper_citations — цитирующие статьи
        3. S2Client.get_paper_references — ссылки статьи
        4. Агрегация и статистика (timeline, топ-авторы, распределение)
        5. LLM-анализ позиции статьи в научном ландшафте
        6. Возврат структурированного результата

    Use Case: UC-17 из LLM_SERVICE.md
    Actor: Исследователь / PhD-студент / Рецензент
    Цель: Граф цитирований + LLM-анализ влияния статьи.

Используемые классы/функции из llm_service.py:
    - S2Client, S2_RATE_LIMIT_DELAY
    - load_env_and_validate, create_cloudru_openai_client_from_env
    - RequestContext, query_llm_simple, stream_llm_to_stdout

Внешние зависимости:
    - semanticscholar (pip install semanticscholar)
    - llm_service.py, python-dotenv

Использование:
    python -m AI.scripts.UC.UC_17 "649def34f8be52c8b66281af98ae884c09aef38b"
    python -m AI.scripts.UC.UC_17 --paper-id "10.1093/mind/lix.236.433" --max-citations 30
    python -m AI.scripts.UC.UC_17 --paper-id "ARXIV:1706.03762" --stream
"""

from __future__ import annotations

import asyncio
import json
import logging
import os
import sys
from collections import Counter
from pathlib import Path
from typing import Any, Dict, List, Optional

# ---------- Константы ----------
SCRIPT_DIR = Path(__file__).parent.absolute()
AI_DIR = SCRIPT_DIR.parent.parent
GLOBAL_SERVICES_DIR = AI_DIR.parent

DEFAULT_MAX_CITATIONS = 20
DEFAULT_MAX_REFERENCES = 20

sys.path.insert(0, str(GLOBAL_SERVICES_DIR))

from AI.llm_service import (
    RequestContext,
    S2Client,
    S2_RATE_LIMIT_DELAY,
    create_cloudru_openai_client_from_env,
    load_env_and_validate,
    query_llm_simple,
    stream_llm_to_stdout,
)

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s | %(levelname)-7s | %(name)s | %(message)s",
)
logger = logging.getLogger(__name__)

SYSTEM_MSG = (
    "Ты — эксперт по наукометрии и анализу научной литературы. "
    "Проанализируй статью и её граф цитирований. Определи: "
    "1) Основные идеи статьи 2) На чём основана (references) "
    "3) Как повлияла на последующие исследования (citations) "
    "4) Текущая актуальность и значимость."
)


# ============================================================================
# Агрегация
# ============================================================================

def _compute_stats(
    paper: Dict[str, Any],
    citations: List[Dict[str, Any]],
    references: List[Dict[str, Any]],
) -> Dict[str, Any]:
    """Подсчёт статистики по цитированиям и ссылкам."""
    # Годы цитирований
    citation_years = [c["year"] for c in citations if c.get("year")]
    reference_years = [r["year"] for r in references if r.get("year")]

    avg_citation_year = sum(citation_years) / len(citation_years) if citation_years else 0
    avg_reference_year = sum(reference_years) / len(reference_years) if reference_years else 0

    # Распределение по годам (цитирования)
    year_distribution = dict(Counter(citation_years))

    # Топ-цитирующие авторы
    citing_authors: List[str] = []
    for c in citations:
        for a in c.get("authors", []):
            citing_authors.append(a["name"])
    top_citing_authors = [name for name, _ in Counter(citing_authors).most_common(10)]

    # Самые цитируемые citing papers
    top_citing_papers = sorted(citations, key=lambda x: x.get("citationCount", 0), reverse=True)[:5]

    # Ключевые references
    top_references = sorted(references, key=lambda x: x.get("citationCount", 0), reverse=True)[:5]

    return {
        "total_citations_loaded": len(citations),
        "total_references_loaded": len(references),
        "avg_citation_year": round(avg_citation_year, 1),
        "avg_reference_year": round(avg_reference_year, 1),
        "citation_year_range": (min(citation_years) if citation_years else None,
                                 max(citation_years) if citation_years else None),
        "citation_year_distribution": dict(sorted(year_distribution.items())),
        "top_citing_authors": top_citing_authors,
        "top_citing_papers": [
            {"title": p["title"], "year": p.get("year"), "citationCount": p["citationCount"]}
            for p in top_citing_papers
        ],
        "top_references": [
            {"title": p["title"], "year": p.get("year"), "citationCount": p["citationCount"]}
            for p in top_references
        ],
    }


# ============================================================================
# Основная функция
# ============================================================================

async def main(
    paper_id: Optional[str] = None,
    max_citations: int = DEFAULT_MAX_CITATIONS,
    max_references: int = DEFAULT_MAX_REFERENCES,
    use_streaming: bool = False,
) -> Dict[str, Any]:
    """Основная функция UC-17: Анализ цитирований."""
    logger.info("=" * 70)
    logger.info("UC-17: Анализ цитирований статьи (Citation Graph Analysis)")
    logger.info("=" * 70)

    if not paper_id:
        paper_id = "ARXIV:1706.03762"  # Attention Is All You Need
        logger.info("Paper ID не предоставлен, используем демо: '%s'", paper_id)

    # ШАГ 0. Конфигурация
    try:
        cfg = load_env_and_validate(str(GLOBAL_SERVICES_DIR))
    except ValueError as exc:
        return {"status": "error", "message": str(exc)}

    llm_client = create_cloudru_openai_client_from_env()
    s2 = S2Client()

    # ────────────────────────────────────────────────────────────────────
    # ШАГ 1. Загрузка метаданных статьи
    # ────────────────────────────────────────────────────────────────────
    logger.info("ШАГ 1. Загрузка метаданных статьи '%s' — ОТПРАВЛЯЕМ", paper_id)

    paper = await s2.get_paper(paper_id)
    if not paper:
        return {"status": "error", "message": f"Статья '{paper_id}' не найдена в Semantic Scholar"}

    authors_str = ", ".join(a["name"] for a in paper.get("authors", [])[:5])
    logger.info("ШАГ 1. Статья \"%s\" (%s, %s) — cit=%d, ref=%d — УСПЕХ",
                paper["title"][:60], paper.get("year", "?"), authors_str[:40],
                paper["citationCount"], paper["referenceCount"])

    await asyncio.sleep(S2_RATE_LIMIT_DELAY)

    # ────────────────────────────────────────────────────────────────────
    # ШАГ 2. Загрузка цитирований
    # ────────────────────────────────────────────────────────────────────
    logger.info("ШАГ 2. Загрузка цитирований (max=%d) — ОТПРАВЛЯЕМ", max_citations)

    citations = await s2.get_paper_citations(paper["paperId"], limit=max_citations)

    for i, c in enumerate(citations[:5], 1):
        logger.info("ШАГ 2.   [%d] %s (%s, cit=%d)",
                    i, c["title"][:50], c.get("year", "?"), c["citationCount"])
    if len(citations) > 5:
        logger.info("ШАГ 2.   ... и ещё %d", len(citations) - 5)

    logger.info("ШАГ 2. Загружено %d цитирований — УСПЕХ", len(citations))

    await asyncio.sleep(S2_RATE_LIMIT_DELAY)

    # ────────────────────────────────────────────────────────────────────
    # ШАГ 3. Загрузка ссылок
    # ────────────────────────────────────────────────────────────────────
    logger.info("ШАГ 3. Загрузка ссылок (references, max=%d) — ОТПРАВЛЯЕМ", max_references)

    references = await s2.get_paper_references(paper["paperId"], limit=max_references)

    for i, r in enumerate(references[:5], 1):
        logger.info("ШАГ 3.   [%d] %s (%s, cit=%d)",
                    i, r["title"][:50], r.get("year", "?"), r["citationCount"])
    if len(references) > 5:
        logger.info("ШАГ 3.   ... и ещё %d", len(references) - 5)

    logger.info("ШАГ 3. Загружено %d ссылок — УСПЕХ", len(references))

    # ────────────────────────────────────────────────────────────────────
    # ШАГ 4. Агрегация и статистика
    # ────────────────────────────────────────────────────────────────────
    logger.info("ШАГ 4. Агрегация и статистика — ОТПРАВЛЯЕМ")

    stats = _compute_stats(paper, citations, references)

    logger.info("ШАГ 4. Агрегация: %d citations, %d references, avg_year=%.0f — УСПЕХ",
                stats["total_citations_loaded"], stats["total_references_loaded"],
                stats["avg_citation_year"])
    if stats["citation_year_range"][0]:
        logger.info("ШАГ 4.   Диапазон цитирований: %d — %d",
                    stats["citation_year_range"][0], stats["citation_year_range"][1])
    logger.info("ШАГ 4.   Топ-цитирующие авторы: %s", ", ".join(stats["top_citing_authors"][:5]))

    # ────────────────────────────────────────────────────────────────────
    # ШАГ 5. LLM-анализ позиции в научном ландшафте
    # ────────────────────────────────────────────────────────────────────
    logger.info("ШАГ 5. LLM-анализ позиции статьи — ОТПРАВЛЯЕМ")

    # Формирование контекста
    paper_section = (
        f"═══ АНАЛИЗИРУЕМАЯ СТАТЬЯ ═══\n"
        f"Название: {paper['title']}\n"
        f"Авторы: {authors_str}\n"
        f"Год: {paper.get('year', 'N/A')}\n"
        f"Venue: {paper.get('venue', 'N/A')}\n"
        f"Цитирований: {paper['citationCount']}\n"
        f"Ссылок: {paper['referenceCount']}\n"
        f"Области: {', '.join(paper.get('fieldsOfStudy', []))}\n"
        f"Abstract: {paper.get('abstract', 'N/A')}\n"
        f"TLDR: {paper.get('tldr', 'N/A')}\n"
    )

    citations_section = "═══ КТО ЦИТИРУЕТ (топ по цитируемости) ═══\n"
    top_cit = sorted(citations, key=lambda x: x.get("citationCount", 0), reverse=True)[:10]
    for i, c in enumerate(top_cit, 1):
        c_authors = ", ".join(a["name"] for a in c.get("authors", [])[:3])
        abstract_short = (c.get("abstract") or "")[:150]
        citations_section += (
            f"  [{i}] {c['title']} ({c.get('year', '?')}) — cit: {c['citationCount']}\n"
            f"      Авторы: {c_authors}\n"
            f"      Abstract: {abstract_short}...\n"
        )

    references_section = "═══ НА КОГО ССЫЛАЕТСЯ (топ по цитируемости) ═══\n"
    top_ref = sorted(references, key=lambda x: x.get("citationCount", 0), reverse=True)[:10]
    for i, r in enumerate(top_ref, 1):
        r_authors = ", ".join(a["name"] for a in r.get("authors", [])[:3])
        abstract_short = (r.get("abstract") or "")[:150]
        references_section += (
            f"  [{i}] {r['title']} ({r.get('year', '?')}) — cit: {r['citationCount']}\n"
            f"      Авторы: {r_authors}\n"
            f"      Abstract: {abstract_short}...\n"
        )

    stats_section = (
        f"═══ СТАТИСТИКА ═══\n"
        f"Средний год цитирований: {stats['avg_citation_year']}\n"
        f"Диапазон: {stats['citation_year_range']}\n"
        f"Топ-цитирующие авторы: {', '.join(stats['top_citing_authors'][:5])}\n"
        f"Распределение по годам: {json.dumps(stats['citation_year_distribution'])}\n"
    )

    prompt = (
        f"{paper_section}\n\n"
        f"{citations_section}\n\n"
        f"{references_section}\n\n"
        f"{stats_section}\n\n"
        f"═══ ЗАДАЧА ═══\n"
        f"Проведи глубокий анализ:\n"
        f"1. Основные идеи и вклад статьи\n"
        f"2. Научный фундамент (ключевые references и их роль)\n"
        f"3. Влияние на последующие исследования (паттерны в citations)\n"
        f"4. Timeline влияния: как менялось цитирование по годам\n"
        f"5. Текущая актуальность и позиция в научном ландшафте\n"
        f"6. Общее резюме: значимость работы\n"
    )

    llm_ctx = RequestContext(request_id="uc17-llm", user_id="uc17_user", mode="chat")

    if use_streaming:
        llm_answer = await stream_llm_to_stdout(
            llm_client, prompt, llm_ctx,
            system_message=SYSTEM_MSG, model=cfg["CLOUDRU_MODEL_NAME"],
        )
    else:
        llm_answer = await query_llm_simple(
            llm_client, prompt, llm_ctx,
            system_message=SYSTEM_MSG, model=cfg["CLOUDRU_MODEL_NAME"],
        )
        if llm_answer:
            print("\n" + "=" * 70 + "\nАНАЛИЗ ЦИТИРОВАНИЙ:\n" + "=" * 70)
            print(llm_answer)
            print("=" * 70)

    logger.info("ШАГ 5. LLM-анализ цитирований — УСПЕХ")

    # ────────────────────────────────────────────────────────────────────
    # ШАГ 6. Возврат результата
    # ────────────────────────────────────────────────────────────────────
    result: Dict[str, Any] = {
        "status": "success" if llm_answer else "error",
        "uc": "UC-17",
        "paper": {
            "paperId": paper["paperId"],
            "title": paper["title"],
            "authors": authors_str,
            "year": paper.get("year"),
            "citationCount": paper["citationCount"],
            "referenceCount": paper["referenceCount"],
            "venue": paper.get("venue", ""),
            "fieldsOfStudy": paper.get("fieldsOfStudy", []),
        },
        "citations_loaded": len(citations),
        "references_loaded": len(references),
        "stats": stats,
        "llm_analysis": llm_answer,
        "llm_analysis_length": len(llm_answer) if llm_answer else 0,
    }
    if not llm_answer:
        result["error"] = "LLM не вернул ответ"

    logger.info("ШАГ 6. Анализ цитирований завершён — УСПЕХ")
    logger.info("РЕЗУЛЬТАТ UC-17: citations=%d, references=%d, answer_len=%d",
                len(citations), len(references), result["llm_analysis_length"])
    return result


if __name__ == "__main__":
    import argparse

    ap = argparse.ArgumentParser(description="UC-17: Анализ цитирований статьи")
    ap.add_argument("paper_id", nargs="?", default=None,
                    help="S2 Paper ID, DOI, ArXiv ID (напр. ARXIV:1706.03762)")
    ap.add_argument("--max-citations", type=int, default=DEFAULT_MAX_CITATIONS)
    ap.add_argument("--max-references", type=int, default=DEFAULT_MAX_REFERENCES)
    ap.add_argument("--stream", action="store_true")
    args = ap.parse_args()

    try:
        result = asyncio.run(main(
            paper_id=args.paper_id,
            max_citations=args.max_citations,
            max_references=args.max_references,
            use_streaming=args.stream,
        ))

        print("\n" + "=" * 70)
        print("UC-17: АНАЛИЗ ЦИТИРОВАНИЙ ЗАВЕРШЁН")
        print("=" * 70)
        p = result.get("paper", {})
        print(f"Статус: {result.get('status', 'unknown')}")
        print(f"Статья: {p.get('title', 'N/A')} ({p.get('year', '?')})")
        print(f"Авторы: {p.get('authors', 'N/A')}")
        print(f"Цитирований загружено: {result.get('citations_loaded', 0)}")
        print(f"Ссылок загружено: {result.get('references_loaded', 0)}")
        print(f"Длина анализа: {result.get('llm_analysis_length', 0)} символов")

        sys.exit(0 if result.get("status") == "success" else 1)

    except KeyboardInterrupt:
        print("\nПрервано пользователем")
        sys.exit(130)
    except Exception as exc:
        logger.exception("Критическая ошибка в UC-17: %s", exc)
        sys.exit(1)
