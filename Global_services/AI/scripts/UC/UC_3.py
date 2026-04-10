# -*- coding: utf-8 -*-
"""
Руководство к файлу UC_3.py
==========================

Назначение:
    Реализация UC-3: Поиск информации в интернете (Web Search + Crawler).
    1. Генерация поисковых запросов через CrawlerQueryRewriter
    2. Поиск и краулинг через CrawlerClient
    3. Чанкинг crawled-контента
    4. LLM-ответ с указанием веб-источников

Архитектура (6 шагов UC-3):
    ШАГ 1. Валидация запроса
    ШАГ 2. Генерация поисковых запросов — CrawlerQueryRewriter.rewrite()
    ШАГ 3. Поиск и краулинг — CrawlerClient.search()
    ШАГ 4. Чанкинг — Chunker.split()
    ШАГ 5. Промпт — build_web_prompt()
    ШАГ 6. LLM — stream_llm_to_stdout() / query_llm_simple()

Используемые функции из llm_service.py:
    - load_env_and_validate, create_cloudru_openai_client_from_env
    - CrawlerClient, CrawlerQueryRewriter, Chunker
    - build_web_prompt, stream_llm_to_stdout, query_llm_simple
    - RequestContext

Использование:
    python -m AI.scripts.UC.UC_3 "ваш поисковый запрос" [--stream]

Зависимости:
    - llm_service.py, python-dotenv, httpx
"""

from __future__ import annotations

import asyncio
import logging
import sys
from pathlib import Path
from typing import Any, Dict, List, Optional

# ---------- Константы ----------
SCRIPT_DIR = Path(__file__).parent.absolute()
AI_DIR = SCRIPT_DIR.parent.parent
GLOBAL_SERVICES_DIR = AI_DIR.parent

DEFAULT_MAX_RESULTS = 5
DEFAULT_WORD_COUNT_THRESHOLD = 100
DEFAULT_TIMEOUT = 45.0

sys.path.insert(0, str(GLOBAL_SERVICES_DIR))

from AI.llm_service import (
    Chunker,
    CrawlerClient,
    CrawlerQueryRewriter,
    RequestContext,
    build_web_prompt,
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

SYSTEM_MSG = "Ты — эксперт по анализу информации из интернета. Давай точные, структурированные ответы с указанием источников."


async def main(
    query: Optional[str] = None,
    max_results: int = DEFAULT_MAX_RESULTS,
    word_count_threshold: int = DEFAULT_WORD_COUNT_THRESHOLD,
    use_streaming: bool = False,
) -> Dict[str, Any]:
    """Основная функция UC-3: Поиск информации в интернете."""
    logger.info("=" * 70)
    logger.info("UC-3: Поиск информации в интернете (Web Search + Crawler)")
    logger.info("=" * 70)

    # Получаем запрос
    if not query and len(sys.argv) > 1 and not sys.argv[1].startswith("--"):
        query = sys.argv[1]
    if not query:
        query = "Python async programming best practices"
        logger.info("Запрос не предоставлен, используем демо: '%s'", query)

    # ШАГ 0. Конфигурация
    try:
        cfg = load_env_and_validate(str(GLOBAL_SERVICES_DIR))
    except ValueError as exc:
        return {"status": "error", "message": str(exc)}

    crawler_base_url = cfg["CRAWLER_BASE_URL"]
    if not crawler_base_url:
        logger.error("ОШИБКА: CRAWLER_BASE_URL не задан (обязательно для UC-3)")
        return {"status": "error", "message": "CRAWLER_BASE_URL не задан"}

    # ШАГ 1. Валидация
    query = query.strip()
    if len(query) < 3:
        return {"status": "error", "message": "Запрос слишком короткий (минимум 3 символа)"}
    logger.info("ШАГ 1. Запрос: '%s' (%d символов) — УСПЕХ", query[:50], len(query))

    # Создаём клиенты
    ctx = RequestContext(request_id="uc3", user_id="uc3_user", mode="rag_tool", use_internet=True)
    llm_client = create_cloudru_openai_client_from_env()
    crawler_client = CrawlerClient(
        base_url=crawler_base_url,
        max_pages=max_results,
        word_count_threshold=word_count_threshold,
        timeout=DEFAULT_TIMEOUT,
    )
    chunker = Chunker(chunk_size_tokens=512, chunk_overlap_tokens=128)

    # ШАГ 2. Генерация поисковых запросов
    rewriter = CrawlerQueryRewriter(llm_client=llm_client, count=2)
    try:
        search_queries = await rewriter.rewrite(query, ctx)
    except Exception as exc:
        logger.warning("ШАГ 2. ОШИБКА: %s — используем оригинал", exc)
        search_queries = [query]
    for i, q in enumerate(search_queries, 1):
        logger.info("ШАГ 2.   [%d] %s", i, q[:80])

    # ШАГ 3. Поиск и краулинг
    try:
        snippets = await crawler_client.search(search_queries[:max_results], ctx)
    except Exception as exc:
        logger.error("ШАГ 3. ОШИБКА краулинга: %s", exc)
        snippets = []
    logger.info("ШАГ 3. Краулинг — %d сниппетов", len(snippets))

    # ШАГ 4. Чанкинг
    all_chunks: List[Any] = []
    for i, snippet in enumerate(snippets, 1):
        if not snippet.text or not snippet.text.strip():
            continue
        try:
            chunks = await chunker.split(text=snippet.text, source_id=snippet.source_id or f"web_{i}")
            for c in chunks:
                c.metadata.update({"url": snippet.source_id, "score": snippet.score, **snippet.metadata})
            all_chunks.extend(chunks)
        except Exception as exc:
            logger.warning("ШАГ 4. ОШИБКА чанкинга [%d]: %s", i, exc)
    logger.info("ШАГ 4. Чанкинг — %d чанков из %d сниппетов", len(all_chunks), len(snippets))

    # ШАГ 5. Промпт
    prompt = build_web_prompt(query=query, snippets=snippets, chunks=all_chunks)

    # ШАГ 6. LLM-запрос
    llm_ctx = RequestContext(request_id="uc3-llm", user_id="uc3_user", mode="rag_tool")
    if use_streaming:
        llm_answer = await stream_llm_to_stdout(
            llm_client, prompt, llm_ctx, system_message=SYSTEM_MSG, model=cfg["CLOUDRU_MODEL_NAME"],
        )
    else:
        llm_answer = await query_llm_simple(
            llm_client, prompt, llm_ctx, system_message=SYSTEM_MSG, model=cfg["CLOUDRU_MODEL_NAME"],
        )
        if llm_answer:
            print("\n" + "=" * 70 + "\nОТВЕТ LLM:\n" + "=" * 70)
            print(llm_answer)
            print("=" * 70)

    # Результат
    snippets_data = [
        {"text": s.text[:500] if s.text else "", "source_id": s.source_id, "score": s.score, "metadata": s.metadata}
        for s in snippets
    ]
    result: Dict[str, Any] = {
        "status": "success" if llm_answer else "error",
        "uc": "UC-3",
        "query": query,
        "search_queries": search_queries,
        "crawled_sources": len(snippets),
        "total_chunks": len(all_chunks),
        "llm_answer": llm_answer,
        "llm_answer_length": len(llm_answer) if llm_answer else 0,
        "sources": snippets_data,
    }
    if not llm_answer:
        result["error"] = "LLM не вернул ответ"

    logger.info("РЕЗУЛЬТАТ UC-3: status=%s, sources=%d, chunks=%d, answer_len=%d",
                result["status"], len(snippets), len(all_chunks), result["llm_answer_length"])
    return result


if __name__ == "__main__":
    _query = sys.argv[1] if len(sys.argv) > 1 and not sys.argv[1].startswith("--") else None
    _stream = "--stream" in sys.argv

    try:
        result = asyncio.run(main(query=_query, use_streaming=_stream))

        print("\n" + "=" * 70)
        print("UC-3: ПОИСК В ИНТЕРНЕТЕ ЗАВЕРШЁН")
        print("=" * 70)
        print(f"Статус: {result.get('status', 'unknown')}")
        print(f"Запрос: {result.get('query', 'N/A')}")
        print(f"Источников: {result.get('crawled_sources', 0)}")
        print(f"Чанков: {result.get('total_chunks', 0)}")
        print(f"Длина ответа: {result.get('llm_answer_length', 0)} символов")

        sys.exit(0 if result.get("status") == "success" else 1)

    except KeyboardInterrupt:
        print("\nПрервано пользователем")
        sys.exit(130)
    except Exception as exc:
        logger.exception("Критическая ошибка в UC-3: %s", exc)
        sys.exit(1)
