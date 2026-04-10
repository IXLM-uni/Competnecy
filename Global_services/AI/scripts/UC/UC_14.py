# -*- coding: utf-8 -*-
"""
Руководство к файлу UC_14.py
============================

Назначение:
    Реализация UC-14: Прямой краулинг URL (Direct URL Crawling).
    1. Получение списка URL
    2. Проверка доступности Crawler — health_check()
    3. Прямой краулинг URL — CrawlerClient.crawl_urls()
    4. Обработка результатов — Snippet-ы
    5. Интеграция с RAG — ContextBuilder / LLM-ответ

    Use Case: UC-14 из LLM_SERVICE.md
    Actor: API-клиент / Внешняя система
    Цель: Извлечение контента с конкретных URL без промежуточного поиска DuckDuckGo.

Архитектура (5 шагов UC-14):
    ШАГ 1. Получение списка URL — валидация формата
    ШАГ 2. Проверка доступности Crawler — CrawlerClient.health_check()
    ШАГ 3. Прямой краулинг URL — CrawlerClient.crawl_urls()
    ШАГ 4. Обработка результатов — фильтрация пустых / ошибочных
    ШАГ 5. Интеграция с RAG — build_web_prompt() + LLM-ответ

Используемые функции из llm_service.py:
    - load_env_and_validate, create_cloudru_openai_client_from_env
    - CrawlerClient, Chunker, RequestContext
    - build_web_prompt, query_llm_simple, stream_llm_to_stdout

Использование:
    python -m AI.scripts.UC.UC_14 "https://example.com" "https://example.org"
    python -m AI.scripts.UC.UC_14 --urls-file urls.txt --query "Резюмируй содержимое"

Зависимости:
    - llm_service.py, python-dotenv, httpx
"""

from __future__ import annotations

import asyncio
import json
import logging
import re
import sys
from pathlib import Path
from typing import Any, Dict, List, Optional

# ---------- Константы ----------
SCRIPT_DIR = Path(__file__).parent.absolute()
AI_DIR = SCRIPT_DIR.parent.parent
GLOBAL_SERVICES_DIR = AI_DIR.parent

DEFAULT_MAX_PAGES = 10
DEFAULT_WORD_COUNT_THRESHOLD = 100
DEFAULT_TIMEOUT = 45.0

sys.path.insert(0, str(GLOBAL_SERVICES_DIR))

from AI.llm_service import (
    Chunker,
    CrawlerClient,
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

SYSTEM_MSG = (
    "Ты — эксперт по анализу веб-контента. Давай точные, структурированные ответы "
    "с указанием источников (URL). Используй ТОЛЬКО предоставленный контекст."
)

URL_PATTERN = re.compile(r"^https?://")


async def main(
    urls: Optional[List[str]] = None,
    query: Optional[str] = None,
    max_pages: int = DEFAULT_MAX_PAGES,
    word_count_threshold: int = DEFAULT_WORD_COUNT_THRESHOLD,
    use_streaming: bool = False,
) -> Dict[str, Any]:
    """Основная функция UC-14: Прямой краулинг URL."""
    logger.info("=" * 70)
    logger.info("UC-14: Прямой краулинг URL (Direct URL Crawling)")
    logger.info("=" * 70)

    if not urls:
        urls = [
            "https://docs.python.org/3/tutorial/index.html",
            "https://docs.python.org/3/library/asyncio.html",
        ]
        logger.info("URL не указаны, используем демо: %s", urls)

    if not query:
        query = "Резюмируй содержимое этих страниц"

    # ШАГ 0. Конфигурация
    try:
        cfg = load_env_and_validate(str(GLOBAL_SERVICES_DIR))
    except ValueError as exc:
        return {"status": "error", "message": str(exc)}

    crawler_base_url = cfg["CRAWLER_BASE_URL"]
    if not crawler_base_url:
        logger.error("ОШИБКА: CRAWLER_BASE_URL не задан (обязательно для UC-14)")
        return {"status": "error", "message": "CRAWLER_BASE_URL не задан"}

    # ШАГ 1. Получение и валидация URL
    logger.info("ШАГ 1. Валидация %d URL — ОТПРАВЛЯЕМ", len(urls))
    valid_urls: List[str] = []
    invalid_urls: List[str] = []

    for url in urls:
        url = url.strip()
        if URL_PATTERN.match(url):
            valid_urls.append(url)
            logger.info("  ✓ %s", url)
        else:
            invalid_urls.append(url)
            logger.warning("  ✗ %s (неверный формат)", url)

    if not valid_urls:
        return {"status": "error", "message": "Нет валидных URL"}

    logger.info("ШАГ 1. Получили %d URL для краулинга — УСПЕХ (отклонено: %d)",
                len(valid_urls), len(invalid_urls))

    ctx = RequestContext(request_id="uc14-crawl", user_id="uc14_user", mode="rag_tool")

    # ШАГ 2. Проверка доступности Crawler
    logger.info("ШАГ 2. Проверка доступности Crawler — ОТПРАВЛЯЕМ")
    crawler_client = CrawlerClient(
        base_url=crawler_base_url,
        max_pages=max_pages,
        word_count_threshold=word_count_threshold,
        timeout=DEFAULT_TIMEOUT,
    )

    try:
        health = await crawler_client.health_check()
        logger.info("ШАГ 2. Crawler статус: %s — УСПЕХ", health.get("status", "ok"))
    except Exception as exc:
        logger.warning("ШАГ 2. Crawler health_check ОШИБКА: %s — продолжаем", exc)

    # ШАГ 3. Прямой краулинг URL
    logger.info("ШАГ 3. Краулинг %d URL — ОТПРАВЛЯЕМ", len(valid_urls))

    try:
        snippets = await crawler_client.crawl_urls(valid_urls, ctx)
    except Exception as exc:
        logger.error("ШАГ 3. ОШИБКА краулинга: %s", exc)
        return {"status": "error", "message": f"Crawl error: {exc}"}

    logger.info("ШАГ 3. Краулинг завершён — УСПЕХ: %d сниппетов из %d URL",
                len(snippets), len(valid_urls))

    # ШАГ 4. Обработка результатов
    logger.info("ШАГ 4. Обработка результатов — ОТПРАВЛЯЕМ")

    # Чанкинг для длинных страниц
    chunker = Chunker(chunk_size_tokens=512, chunk_overlap_tokens=128)
    all_chunks: List[Any] = []

    for i, snippet in enumerate(snippets, 1):
        if not snippet.text or not snippet.text.strip():
            logger.warning("ШАГ 4. Сниппет %d — пустой текст, пропускаем", i)
            continue

        url = snippet.source_id or f"url_{i}"
        title = snippet.metadata.get("title", "")
        logger.info("  [%d] %s — %s (%d символов)", i, url[:60], title[:40], len(snippet.text))

        try:
            chunks = await chunker.split(text=snippet.text, source_id=url)
            for c in chunks:
                c.metadata.update({"url": url, "title": title})
            all_chunks.extend(chunks)
        except Exception as exc:
            logger.warning("ШАГ 4. ОШИБКА чанкинга [%d]: %s", i, exc)

    logger.info("ШАГ 4. Получено %d сниппетов, %d чанков — УСПЕХ",
                len(snippets), len(all_chunks))

    snippets_data = [
        {
            "text": s.text[:500] if s.text else "",
            "source_id": s.source_id,
            "score": s.score,
            "metadata": s.metadata,
        }
        for s in snippets
    ]

    # ШАГ 5. Интеграция с RAG / LLM-ответ
    logger.info("ШАГ 5. Интеграция с LLM — ОТПРАВЛЯЕМ")

    if not all_chunks and not snippets:
        logger.warning("ШАГ 5. Нет контента для LLM — пропускаем")
        llm_answer = None
    else:
        prompt = build_web_prompt(query=query, snippets=snippets, chunks=all_chunks)
        llm_client = create_cloudru_openai_client_from_env()
        llm_ctx = RequestContext(request_id="uc14-llm", user_id="uc14_user", mode="rag_tool")

        if use_streaming:
            llm_answer = await stream_llm_to_stdout(
                llm_client, prompt, llm_ctx, system_message=SYSTEM_MSG,
                model=cfg["CLOUDRU_MODEL_NAME"],
            )
        else:
            llm_answer = await query_llm_simple(
                llm_client, prompt, llm_ctx, system_message=SYSTEM_MSG,
                model=cfg["CLOUDRU_MODEL_NAME"],
            )
            if llm_answer:
                print("\n" + "=" * 70 + "\nОТВЕТ LLM:\n" + "=" * 70)
                print(llm_answer)
                print("=" * 70)

    logger.info("ШАГ 5. Контекст из URL интегрирован — УСПЕХ")

    result: Dict[str, Any] = {
        "status": "success" if snippets else "error",
        "uc": "UC-14",
        "urls_requested": len(valid_urls),
        "urls_invalid": len(invalid_urls),
        "snippets_received": len(snippets),
        "total_chunks": len(all_chunks),
        "query": query,
        "llm_answer": llm_answer,
        "llm_answer_length": len(llm_answer) if llm_answer else 0,
        "sources": snippets_data,
    }
    if not snippets:
        result["error"] = "Краулинг не вернул результатов"

    logger.info("РЕЗУЛЬТАТ UC-14: urls=%d, snippets=%d, chunks=%d, answer_len=%d",
                len(valid_urls), len(snippets), len(all_chunks), result["llm_answer_length"])
    return result


if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser(description="UC-14: Прямой краулинг URL")
    parser.add_argument("urls", nargs="*", help="URL для краулинга")
    parser.add_argument("--urls-file", default=None, help="Файл со списком URL (по одному на строку)")
    parser.add_argument("--query", default=None, help="Запрос к LLM по контенту")
    parser.add_argument("--max-pages", type=int, default=DEFAULT_MAX_PAGES)
    parser.add_argument("--stream", action="store_true")
    args = parser.parse_args()

    _urls = list(args.urls) if args.urls else []
    if args.urls_file:
        try:
            with open(args.urls_file, "r") as f:
                _urls.extend(line.strip() for line in f if line.strip())
        except Exception as exc:
            print(f"Ошибка чтения файла URL: {exc}", file=sys.stderr)
            sys.exit(1)

    try:
        result = asyncio.run(main(
            urls=_urls or None, query=args.query,
            max_pages=args.max_pages, use_streaming=args.stream,
        ))

        print("\n" + "=" * 70)
        print("UC-14: ПРЯМОЙ КРАУЛИНГ URL ЗАВЕРШЁН")
        print("=" * 70)
        print(f"Статус: {result.get('status', 'unknown')}")
        print(f"URL запрошено: {result.get('urls_requested', 0)}")
        print(f"Сниппетов получено: {result.get('snippets_received', 0)}")
        print(f"Чанков: {result.get('total_chunks', 0)}")
        print(f"Длина ответа: {result.get('llm_answer_length', 0)} символов")

        sys.exit(0 if result.get("status") == "success" else 1)

    except KeyboardInterrupt:
        print("\nПрервано пользователем")
        sys.exit(130)
    except Exception as exc:
        logger.exception("Критическая ошибка в UC-14: %s", exc)
        sys.exit(1)
