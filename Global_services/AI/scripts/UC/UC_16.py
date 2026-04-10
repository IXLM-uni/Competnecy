# -*- coding: utf-8 -*-
"""
Руководство к файлу UC_16.py
=============================

Назначение:
    Реализация UC-16: Поиск авторов и анализ их работ (Semantic Scholar Author Search).
    Тонкий клиент — вся S2-логика делегирована S2Client из llm_service.py.
    Pipeline:
        1. S2Client.search_authors — поиск авторов
        2. S2Client.get_author — загрузка детальных профилей
        3. S2Client.get_author_papers — топ-публикации (по citationCount)
        4. Формирование контекста для LLM
        5. LLM-анализ профиля исследователя
        6. Возврат структурированного результата

    Use Case: UC-16 из LLM_SERVICE.md
    Actor: Исследователь / Студент / HR-аналитик
    Цель: Найти авторов по теме, загрузить ключевые публикации, LLM-анализ профиля.

Используемые классы/функции из llm_service.py:
    - S2Client, S2_RATE_LIMIT_DELAY
    - load_env_and_validate, create_cloudru_openai_client_from_env
    - RequestContext, query_llm_simple, stream_llm_to_stdout

Внешние зависимости:
    - semanticscholar (pip install semanticscholar)
    - llm_service.py, python-dotenv

Использование:
    python -m AI.scripts.UC.UC_16 "Yoshua Bengio deep learning"
    python -m AI.scripts.UC.UC_16 --query "Geoffrey Hinton" --max-authors 3 --stream
"""

from __future__ import annotations

import asyncio
import json
import logging
import os
import sys
from pathlib import Path
from typing import Any, Dict, List, Optional

# ---------- Константы ----------
SCRIPT_DIR = Path(__file__).parent.absolute()
AI_DIR = SCRIPT_DIR.parent.parent
GLOBAL_SERVICES_DIR = AI_DIR.parent

DEFAULT_MAX_AUTHORS = 3
DEFAULT_PAPERS_PER_AUTHOR = 10

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
    "Ты — эксперт по анализу научных профилей исследователей. "
    "Проанализируй предоставленные данные об авторах и их публикациях. "
    "Для каждого автора укажи: основные направления, ключевые работы, "
    "влияние на область, h-index интерпретацию. Формат: структурированный текст."
)


# ============================================================================
# Основная функция
# ============================================================================

async def main(
    query: Optional[str] = None,
    max_authors: int = DEFAULT_MAX_AUTHORS,
    papers_per_author: int = DEFAULT_PAPERS_PER_AUTHOR,
    use_streaming: bool = False,
) -> Dict[str, Any]:
    """Основная функция UC-16: Поиск авторов и анализ их работ."""
    logger.info("=" * 70)
    logger.info("UC-16: Поиск авторов и анализ их работ (Semantic Scholar)")
    logger.info("=" * 70)

    if not query:
        query = "Yoshua Bengio deep learning"
        logger.info("Запрос не предоставлен, используем демо: '%s'", query)

    # ШАГ 0. Конфигурация
    try:
        cfg = load_env_and_validate(str(GLOBAL_SERVICES_DIR))
    except ValueError as exc:
        return {"status": "error", "message": str(exc)}

    llm_client = create_cloudru_openai_client_from_env()
    s2 = S2Client(llm_client=llm_client)

    # ────────────────────────────────────────────────────────────────────
    # ШАГ 1. Поиск авторов в Semantic Scholar
    # ────────────────────────────────────────────────────────────────────
    logger.info("ШАГ 1. Поиск авторов по запросу '%s' (max=%d) — ОТПРАВЛЯЕМ",
                query[:50], max_authors)

    authors = await s2.search_authors(query, limit=max_authors)

    if not authors:
        logger.error("ШАГ 1. ОШИБКА: авторы не найдены")
        return {"status": "error", "message": "Авторы не найдены в Semantic Scholar"}

    for i, a in enumerate(authors, 1):
        aff = ", ".join(a["affiliations"][:2]) if a["affiliations"] else "N/A"
        logger.info("ШАГ 1.   [%d] %s | h=%d | papers=%d | cit=%d | %s",
                    i, a["name"], a["hIndex"], a["paperCount"],
                    a["citationCount"], aff[:40])

    logger.info("ШАГ 1. Найдено %d авторов — УСПЕХ", len(authors))

    # ────────────────────────────────────────────────────────────────────
    # ШАГ 2. Загрузка детальных профилей авторов
    # ────────────────────────────────────────────────────────────────────
    logger.info("ШАГ 2. Загрузка детальных профилей %d авторов — ОТПРАВЛЯЕМ", len(authors))

    detailed_authors: List[Dict[str, Any]] = []
    for i, a in enumerate(authors):
        detail = await s2.get_author(a["authorId"])
        if detail:
            detailed_authors.append(detail)
            logger.info("ШАГ 2.   [%d] %s — загружен (h=%d, aliases=%d)",
                        i + 1, detail["name"], detail["hIndex"], len(detail.get("aliases", [])))
        else:
            detailed_authors.append(a)
            logger.warning("ШАГ 2.   [%d] %s — ОШИБКА, используем базовые данные", i + 1, a["name"])
        if i < len(authors) - 1:
            await asyncio.sleep(S2_RATE_LIMIT_DELAY)

    logger.info("ШАГ 2. Загружены профили %d авторов — УСПЕХ", len(detailed_authors))

    # ────────────────────────────────────────────────────────────────────
    # ШАГ 3. Загрузка топ-публикаций каждого автора
    # ────────────────────────────────────────────────────────────────────
    logger.info("ШАГ 3. Загрузка топ-%d публикаций для %d авторов — ОТПРАВЛЯЕМ",
                papers_per_author, len(detailed_authors))

    authors_with_papers: List[Dict[str, Any]] = []
    total_papers = 0
    for i, author in enumerate(detailed_authors):
        papers = await s2.get_author_papers(author["authorId"], limit=papers_per_author)
        author_entry = {**author, "top_papers": papers}
        authors_with_papers.append(author_entry)
        total_papers += len(papers)
        logger.info("ШАГ 3.   [%d] %s: %d статей загружено (top cit=%d)",
                    i + 1, author["name"], len(papers),
                    papers[0]["citationCount"] if papers else 0)
        if i < len(detailed_authors) - 1:
            await asyncio.sleep(S2_RATE_LIMIT_DELAY)

    logger.info("ШАГ 3. Загружено %d статей для %d авторов — УСПЕХ",
                total_papers, len(authors_with_papers))

    # ────────────────────────────────────────────────────────────────────
    # ШАГ 4. Формирование контекста для LLM
    # ────────────────────────────────────────────────────────────────────
    logger.info("ШАГ 4. Формирование контекста для LLM — ОТПРАВЛЯЕМ")

    context_parts = []
    for author in authors_with_papers:
        aff_str = ", ".join(author.get("affiliations", [])[:3]) or "N/A"
        aliases_str = ", ".join(author.get("aliases", [])[:3]) or "нет"

        author_section = (
            f"═══ АВТОР: {author['name']} ═══\n"
            f"Аффилиация: {aff_str}\n"
            f"h-index: {author.get('hIndex', 0)}\n"
            f"Всего публикаций: {author.get('paperCount', 0)}\n"
            f"Всего цитирований: {author.get('citationCount', 0)}\n"
            f"Альтернативные имена: {aliases_str}\n"
        )
        if author.get("homepage"):
            author_section += f"Домашняя страница: {author['homepage']}\n"

        papers_lines = []
        for j, p in enumerate(author.get("top_papers", []), 1):
            abstract_short = (p.get("abstract") or "")[:200]
            papers_lines.append(
                f"  [{j}] {p['title']} ({p.get('year', '?')}) — cit: {p['citationCount']}\n"
                f"      Venue: {p.get('venue', 'N/A')}\n"
                f"      Abstract: {abstract_short}..."
            )

        author_section += "\nТоп-публикации:\n" + "\n".join(papers_lines)
        context_parts.append(author_section)

    context_text = "\n\n".join(context_parts)
    logger.info("ШАГ 4. Контекст для %d авторов сформирован (%d символов) — УСПЕХ",
                len(authors_with_papers), len(context_text))

    # ────────────────────────────────────────────────────────────────────
    # ШАГ 5. LLM-анализ профилей
    # ────────────────────────────────────────────────────────────────────
    logger.info("ШАГ 5. LLM-анализ профилей авторов — ОТПРАВЛЯЕМ")

    prompt = (
        f"Исследовательский запрос: {query}\n\n"
        f"Ниже представлены данные о {len(authors_with_papers)} авторах из Semantic Scholar.\n\n"
        f"{context_text}\n\n"
        f"═══ ЗАДАЧА ═══\n"
        f"Для каждого автора проанализируй:\n"
        f"1. Основные исследовательские направления\n"
        f"2. Ключевые работы и их значимость\n"
        f"3. Влияние на область (h-index, цитирования)\n"
        f"4. Эволюция исследований (если видна по годам публикаций)\n"
        f"5. Общее резюме: позиция автора в научном сообществе\n"
    )

    llm_ctx = RequestContext(request_id="uc16-llm", user_id="uc16_user", mode="chat")

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
            print("\n" + "=" * 70 + "\nАНАЛИЗ АВТОРОВ:\n" + "=" * 70)
            print(llm_answer)
            print("=" * 70)

    logger.info("ШАГ 5. LLM-анализ профилей — УСПЕХ")

    # ────────────────────────────────────────────────────────────────────
    # ШАГ 6. Возврат результата
    # ────────────────────────────────────────────────────────────────────
    authors_summary = []
    for author in authors_with_papers:
        authors_summary.append({
            "name": author["name"],
            "authorId": author["authorId"],
            "affiliation": ", ".join(author.get("affiliations", [])[:2]) or "N/A",
            "h_index": author.get("hIndex", 0),
            "paper_count": author.get("paperCount", 0),
            "citation_count": author.get("citationCount", 0),
            "top_papers": [
                {
                    "title": p["title"],
                    "year": p.get("year"),
                    "citationCount": p["citationCount"],
                    "venue": p.get("venue", ""),
                }
                for p in author.get("top_papers", [])[:5]
            ],
        })

    result: Dict[str, Any] = {
        "status": "success" if llm_answer else "error",
        "uc": "UC-16",
        "query": query,
        "authors_found": len(authors_with_papers),
        "total_papers_loaded": total_papers,
        "authors": authors_summary,
        "llm_analysis": llm_answer,
        "llm_analysis_length": len(llm_answer) if llm_answer else 0,
    }
    if not llm_answer:
        result["error"] = "LLM не вернул ответ"

    logger.info("ШАГ 6. Анализ авторов завершён — УСПЕХ")
    logger.info("РЕЗУЛЬТАТ UC-16: authors=%d, papers=%d, answer_len=%d",
                len(authors_with_papers), total_papers, result["llm_analysis_length"])
    return result


if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser(description="UC-16: Поиск авторов и анализ их работ")
    parser.add_argument("query", nargs="?", default=None, help="Имя автора или тема")
    parser.add_argument("--max-authors", type=int, default=DEFAULT_MAX_AUTHORS)
    parser.add_argument("--papers-per-author", type=int, default=DEFAULT_PAPERS_PER_AUTHOR)
    parser.add_argument("--stream", action="store_true")
    args = parser.parse_args()

    try:
        result = asyncio.run(main(
            query=args.query,
            max_authors=args.max_authors,
            papers_per_author=args.papers_per_author,
            use_streaming=args.stream,
        ))

        print("\n" + "=" * 70)
        print("UC-16: АНАЛИЗ АВТОРОВ ЗАВЕРШЁН")
        print("=" * 70)
        print(f"Статус: {result.get('status', 'unknown')}")
        print(f"Запрос: {result.get('query', 'N/A')}")
        print(f"Авторов найдено: {result.get('authors_found', 0)}")
        print(f"Статей загружено: {result.get('total_papers_loaded', 0)}")
        print(f"Длина анализа: {result.get('llm_analysis_length', 0)} символов")

        if result.get("authors"):
            print("\nАвторы:")
            for a in result["authors"]:
                print(f"  - {a['name']} (h={a['h_index']}, cit={a['citation_count']}, papers={a['paper_count']})")

        sys.exit(0 if result.get("status") == "success" else 1)

    except KeyboardInterrupt:
        print("\nПрервано пользователем")
        sys.exit(130)
    except Exception as exc:
        logger.exception("Критическая ошибка в UC-16: %s", exc)
        sys.exit(1)
