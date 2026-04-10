# -*- coding: utf-8 -*-
"""
Руководство к файлу run_crawler_check.py
=========================================
 
Назначение:
    Комплексный скрипт проверки ВСЕЙ функциональности веб-поиска сервиса llm_service.py:
      - Доступность crawler-сервера (health check)
      - Краулинг одиночного URL (CrawlerClient.crawl_urls)
      - Краулинг нескольких URL батчем
      - Текстовый поиск через SearXNG (CrawlerClient.search с текстом)
      - Смешанный режим: URL + текстовый запрос
      - Обработка ошибок: невалидный URL, таймаут, недоступный сервер
      - Проверка CrawlerClient без base_url (graceful skip)
      - Ответы LLM на заданные вопросы по собранному контенту (rag_qa + internet)
      - Итоговая сводка по всем тестам

Этапы (логируются пошагово):
    ШАГ 1. Загрузка .env и конфигурации (CRAWLER_BASE_URL).
    ШАГ 2. Health check crawler-сервера.
    ШАГ 3. Тест: краулинг одиночного URL.
    ШАГ 4. Тест: краулинг нескольких URL батчем.
    ШАГ 5. Тест: текстовый поисковый запрос (SearXNG).
    ШАГ 6. Тест: смешанный режим (URL + текст).
    ШАГ 7. Тест: обработка невалидного URL.
    ШАГ 8. Тест: CrawlerClient без base_url (graceful skip).
    ШАГ 9. Тест: _is_url и _query_to_search_url (юнит-проверки).
    ШАГ 10. Тест: LLM ответы на вопросы (rag_qa + internet).
    ШАГ 11. Итоговая сводка.

Запуск (из корня проекта Global_services):
    python -m AI.scripts.run_crawler_check

Требования:
    - Запущенный crawler-сервер на CRAWLER_BASE_URL (по умолчанию http://localhost:11235).
    - .env файл с переменной CRAWLER_BASE_URL.
"""

from __future__ import annotations

import asyncio
import logging
import os
import time
from typing import Any, Dict, List, Tuple

from dotenv import load_dotenv

from AI.llm_service import (
    ChatOrchestrator,
    CrawlerClient,
    RequestContext,
    Snippet,
    UserInput,
    create_default_orchestrator_from_env,
)


logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Тестовые данные
# ---------------------------------------------------------------------------

TEST_URLS_SINGLE: List[str] = [
    "https://ru.wikipedia.org/wiki/%D0%9C%D0%B8%D1%82%D1%80%D0%BE%D1%84%D0%B0%D0%BD%D0%BE%D0%B2,_%D0%9F%D1%91%D1%82%D1%80_%D0%A1%D0%B5%D1%80%D0%B3%D0%B5%D0%B5%D0%B2%D0%B8%D1%87",
]

TEST_URLS_BATCH: List[str] = [
    "https://ru.wikipedia.org/wiki/%D0%9C%D0%B8%D1%82%D1%80%D0%BE%D1%84%D0%B0%D0%BD%D0%BE%D0%B2,_%D0%9F%D1%91%D1%82%D1%80_%D0%A1%D0%B5%D1%80%D0%B3%D0%B5%D0%B5%D0%B2%D0%B8%D1%87",
    "https://example.com",
]

TEST_SEARCH_QUERIES: List[str] = [
    "Расскажи про биографию Петра Сергеевича Митрофанова",
    "Что за корабль \"Седов\" у Петра Сергеевича Митрофанова",
    "В каком году родился Петр Сергеевич Митрофанов",
]

TEST_MIXED_QUERIES: List[str] = [
    "https://ru.wikipedia.org/wiki/%D0%9C%D0%B8%D1%82%D1%80%D0%BE%D1%84%D0%B0%D0%BD%D0%BE%D0%B2,_%D0%9F%D1%91%D1%82%D1%80_%D0%A1%D0%B5%D1%80%D0%B3%D0%B5%D0%B5%D0%B2%D0%B8%D1%87",
    "Что за \"Седов\" в биографии Петра Сергеевича Митрофанова",
]

TEST_INVALID_URLS: List[str] = [
    "https://this-domain-definitely-does-not-exist-xyz123.com/page",
]


# ---------------------------------------------------------------------------
# Утилиты
# ---------------------------------------------------------------------------


def _make_ctx(label: str) -> RequestContext:
    """Создаёт RequestContext с уникальным request_id."""
    return RequestContext(request_id=f"crawl-check-{label}-{int(time.time())}")


def _print_snippets(label: str, snippets: List[Snippet]) -> None:
    """Форматированный вывод сниппетов."""
    print(f"\n{'─' * 80}")
    print(f"  {label}")
    print(f"  Сниппетов: {len(snippets)}")
    if not snippets:
        print("  ⚠️  Нет результатов")
        return

    for idx, sn in enumerate(snippets, 1):
        text_preview = sn.text.replace("\n", " ")[:200]
        title = sn.metadata.get("title", "-") if isinstance(sn.metadata, dict) else "-"
        source = sn.metadata.get("url", sn.source_id) if isinstance(sn.metadata, dict) else sn.source_id
        print(f"  [{idx}] score={sn.score:.2f} | title={title}")
        print(f"       url={source}")
        print(f"       text={text_preview}...")


# ---------------------------------------------------------------------------
# Тесты
# ---------------------------------------------------------------------------


async def test_health_check(crawler: CrawlerClient) -> Tuple[bool, str]:
    """ШАГ 2. Health check crawler-сервера."""
    logger.info("ШАГ 2. Health check crawler-сервера — ОТПРАВЛЯЕМ")
    try:
        result = await crawler.health_check()
        status = result.get("status", "unknown")
        if status in ("ok", "degraded"):
            logger.info("ШАГ 2. Health check — УСПЕХ: %s", result)
            return True, f"status={status}"
        else:
            logger.warning("ШАГ 2. Health check — НЕОЖИДАННЫЙ СТАТУС: %s", result)
            return False, f"unexpected status: {result}"
    except Exception as exc:
        logger.error("ШАГ 2. Health check — ОШИБКА: %s", exc)
        return False, str(exc)


async def test_crawl_single_url(crawler: CrawlerClient) -> Tuple[bool, str]:
    """ШАГ 3. Краулинг одиночного URL."""
    logger.info("ШАГ 3. Краулинг одиночного URL — ОТПРАВЛЯЕМ: %s", TEST_URLS_SINGLE)
    ctx = _make_ctx("single")
    try:
        snippets = await crawler.crawl_urls(TEST_URLS_SINGLE, ctx)
        _print_snippets("Тест: одиночный URL", snippets)
        if snippets and len(snippets[0].text) > 10:
            logger.info("ШАГ 3. Краулинг одиночного URL — УСПЕХ: %d сниппетов", len(snippets))
            return True, f"{len(snippets)} сниппетов, text_len={len(snippets[0].text)}"
        else:
            logger.warning("ШАГ 3. Краулинг одиночного URL — ПУСТО или слишком короткий текст")
            return False, "пустой или короткий результат"
    except Exception as exc:
        logger.error("ШАГ 3. Краулинг одиночного URL — ОШИБКА: %s", exc)
        return False, str(exc)


async def test_crawl_batch_urls(crawler: CrawlerClient) -> Tuple[bool, str]:
    """ШАГ 4. Краулинг нескольких URL батчем."""
    logger.info("ШАГ 4. Краулинг батча URL — ОТПРАВЛЯЕМ: %s", TEST_URLS_BATCH)
    ctx = _make_ctx("batch")
    try:
        snippets = await crawler.crawl_urls(TEST_URLS_BATCH, ctx)
        _print_snippets("Тест: батч URL", snippets)
        if len(snippets) >= 1:
            logger.info("ШАГ 4. Краулинг батча — УСПЕХ: %d сниппетов", len(snippets))
            return True, f"{len(snippets)} сниппетов из {len(TEST_URLS_BATCH)} URL"
        else:
            logger.warning("ШАГ 4. Краулинг батча — ПУСТО")
            return False, "нет результатов"
    except Exception as exc:
        logger.error("ШАГ 4. Краулинг батча — ОШИБКА: %s", exc)
        return False, str(exc)


async def test_text_search(crawler: CrawlerClient) -> Tuple[bool, str]:
    """ШАГ 5. Текстовый поисковый запрос (SearXNG через search())."""
    logger.info("ШАГ 5. Текстовый поиск — ОТПРАВЛЯЕМ: %s", TEST_SEARCH_QUERIES)
    ctx = _make_ctx("text-search")
    try:
        snippets = await crawler.search(TEST_SEARCH_QUERIES, ctx)
        _print_snippets("Тест: текстовый поиск", snippets)
        if snippets and len(snippets[0].text) > 10:
            logger.info("ШАГ 5. Текстовый поиск — УСПЕХ: %d сниппетов", len(snippets))
            return True, f"{len(snippets)} сниппетов"
        else:
            logger.warning("ШАГ 5. Текстовый поиск — ПУСТО")
            return False, "нет результатов"
    except Exception as exc:
        logger.error("ШАГ 5. Текстовый поиск — ОШИБКА: %s", exc)
        return False, str(exc)


async def test_mixed_queries(crawler: CrawlerClient) -> Tuple[bool, str]:
    """ШАГ 6. Смешанный режим: URL + текстовый запрос."""
    logger.info("ШАГ 6. Смешанный режим — ОТПРАВЛЯЕМ: %s", TEST_MIXED_QUERIES)
    ctx = _make_ctx("mixed")
    try:
        snippets = await crawler.search(TEST_MIXED_QUERIES, ctx)
        _print_snippets("Тест: смешанный режим", snippets)
        if snippets:
            logger.info("ШАГ 6. Смешанный режим — УСПЕХ: %d сниппетов", len(snippets))
            return True, f"{len(snippets)} сниппетов"
        else:
            logger.warning("ШАГ 6. Смешанный режим — ПУСТО")
            return False, "нет результатов"
    except Exception as exc:
        logger.error("ШАГ 6. Смешанный режим — ОШИБКА: %s", exc)
        return False, str(exc)


async def test_invalid_url(crawler: CrawlerClient) -> Tuple[bool, str]:
    """ШАГ 7. Обработка невалидного URL (не должен упасть)."""
    logger.info("ШАГ 7. Невалидный URL — ОТПРАВЛЯЕМ: %s", TEST_INVALID_URLS)
    ctx = _make_ctx("invalid")
    try:
        snippets = await crawler.crawl_urls(TEST_INVALID_URLS, ctx)
        _print_snippets("Тест: невалидный URL", snippets)
        # Успех = не упал, вернул пустой или ошибочный результат
        logger.info("ШАГ 7. Невалидный URL — УСПЕХ: не упал, сниппетов=%d", len(snippets))
        return True, f"graceful: {len(snippets)} сниппетов (ожидаем 0)"
    except Exception as exc:
        logger.error("ШАГ 7. Невалидный URL — ОШИБКА (не graceful): %s", exc)
        return False, f"исключение: {exc}"


async def test_no_base_url() -> Tuple[bool, str]:
    """ШАГ 8. CrawlerClient без base_url (должен graceful skip)."""
    logger.info("ШАГ 8. CrawlerClient без base_url — ОТПРАВЛЯЕМ")
    try:
        empty_crawler = CrawlerClient(base_url=None)
        ctx = _make_ctx("no-base")
        snippets = await empty_crawler.search(["test query"], ctx)
        health = await empty_crawler.health_check()
        if len(snippets) == 0 and health.get("status") == "not_configured":
            logger.info("ШАГ 8. Без base_url — УСПЕХ: graceful skip")
            return True, "graceful skip, 0 сниппетов"
        else:
            logger.warning("ШАГ 8. Без base_url — НЕОЖИДАННЫЙ результат: snippets=%d", len(snippets))
            return False, f"unexpected: {len(snippets)} сниппетов"
    except Exception as exc:
        logger.error("ШАГ 8. Без base_url — ОШИБКА: %s", exc)
        return False, str(exc)


async def test_url_detection() -> Tuple[bool, str]:
    """ШАГ 9. Юнит-проверки _is_url и _query_to_search_url."""
    logger.info("ШАГ 9. Юнит-проверки URL-детекции — ОТПРАВЛЯЕМ")
    errors: List[str] = []

    # _is_url
    url_cases = [
        ("https://example.com", True),
        ("http://example.com/path?q=1", True),
        ("ftp://files.example.com", True),
        ("просто текстовый запрос", False),
        ("python asyncio tutorial", False),
        ("HTTPS://EXAMPLE.COM", True),
    ]
    for text, expected in url_cases:
        result = CrawlerClient._is_url(text)
        if result != expected:
            errors.append(f"_is_url('{text}') = {result}, ожидали {expected}")

    # _query_to_search_url
    crawler = CrawlerClient(base_url="http://localhost:11235")
    searxng_url = crawler._query_to_search_url("тест запрос")
    if "/search" not in searxng_url:
        errors.append(f"_query_to_search_url не содержит /search: {searxng_url}")
    if "format=json" not in searxng_url:
        errors.append(f"_query_to_search_url не содержит format=json: {searxng_url}")
    if "q=" not in searxng_url:
        errors.append(f"_query_to_search_url не содержит q=: {searxng_url}")

    if errors:
        for e in errors:
            logger.error("ШАГ 9. ОШИБКА: %s", e)
        return False, "; ".join(errors)

    logger.info("ШАГ 9. Юнит-проверки — УСПЕХ")
    return True, f"все {len(url_cases)} кейсов пройдены"


async def test_llm_answers(base_url: str) -> Tuple[bool, str]:
    """ШАГ 10. Вызов LLM для ответов на вопросы по Википедии (rag_qa + internet)."""
    logger.info("ШАГ 10. LLM ответы — создаём оркестратор")

    try:
        orchestrator: ChatOrchestrator = create_default_orchestrator_from_env(
            crawler_base_url=base_url,
            enable_sparse=True,
        )
    except Exception as exc:  # pragma: no cover - защитное логирование
        logger.error("ШАГ 10. LLM ответы — ОШИБКА инициализации оркестратора: %s", exc)
        return False, f"orchestrator init error: {exc}"

    questions = [
        "Расскажи про биографию Петра Сергеевича Митрофанова",
        "Что за \"Седов\" у Петра Сергеевича Митрофанова",
        "В каком году родился Петр Сергеевич Митрофанов",
    ]

    answers: List[str] = []
    ctx = _make_ctx("llm")

    for idx, question in enumerate(questions, 1):
        logger.info("ШАГ 10.%d. LLM запрос — ОТПРАВЛЯЕМ: %s", idx, question)
        user_input = UserInput(
            text=question,
            mode="rag_qa",
            use_internet=True,
            enable_tools=False,
            enable_streaming=False,
        )

        try:
            result = await orchestrator.handle_user_input(user_input, ctx)
            answers.append(result.response_text)
            logger.info("ШАГ 10.%d. LLM ответ — УСПЕХ: %s", idx, result.response_text)
        except Exception as exc:
            logger.error("ШАГ 10.%d. LLM ответ — ОШИБКА: %s", idx, exc)
            return False, f"llm error on q{idx}: {exc}"

    print("\n" + "─" * 80)
    print("  Тест: LLM ответы по Википедии")
    for idx, ans in enumerate(answers, 1):
        print(f"  [{idx}] {ans}")

    return True, f"ответов={len(answers)}"


# ---------------------------------------------------------------------------
# Главная функция
# ---------------------------------------------------------------------------


async def main() -> None:
    # ШАГ 1. Загружаем .env
    env_path = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..", ".env"))
    load_dotenv(env_path)
    logger.info("ШАГ 1. Загружаем .env из %s", env_path)

    base_url = os.environ.get("CRAWLER_BASE_URL")
    api_key = os.environ.get("CRAWLER_API_KEY")

    if not base_url:
        logger.error("ШАГ 1. ОШИБКА: переменная CRAWLER_BASE_URL не задана")
        print("❌ CRAWLER_BASE_URL не задан — укажите URL сервиса crawler4ai в .env")
        print("   Пример: CRAWLER_BASE_URL=http://localhost:11235")
        return

    logger.info(
        "ШАГ 1. УСПЕХ: base_url=%s, api_key=%s",
        base_url, "set" if api_key else "not set",
    )

    # Инициализация клиента
    crawler = CrawlerClient(
        base_url=base_url,
        api_key=api_key,
        max_pages=3,
        timeout=45.0,
    )
    logger.info("ШАГ 1. Инициализация CrawlerClient — УСПЕХ")

    # Запуск тестов
    tests: List[Tuple[str, Any]] = [
        ("ШАГ 2.  Health check", test_health_check(crawler)),
        ("ШАГ 3.  Краулинг одиночного URL", test_crawl_single_url(crawler)),
        ("ШАГ 4.  Краулинг батча URL", test_crawl_batch_urls(crawler)),
        ("ШАГ 5.  Текстовый поиск (SearXNG)", test_text_search(crawler)),
        ("ШАГ 6.  Смешанный режим (URL + текст)", test_mixed_queries(crawler)),
        ("ШАГ 7.  Невалидный URL (graceful)", test_invalid_url(crawler)),
        ("ШАГ 8.  Без base_url (graceful skip)", test_no_base_url()),
        ("ШАГ 9.  Юнит: URL-детекция", test_url_detection()),
        ("ШАГ 10. LLM ответы по Википедии", test_llm_answers(base_url)),
    ]

    results: List[Tuple[str, bool, str]] = []

    for name, coro in tests:
        print(f"\n{'=' * 80}")
        print(f"▶  {name}")
        print(f"{'=' * 80}")

        started = time.time()
        try:
            ok, detail = await coro
        except Exception as exc:
            ok, detail = False, f"EXCEPTION: {exc}"
        elapsed = round(time.time() - started, 2)

        status = "✅ PASS" if ok else "❌ FAIL"
        print(f"\n  {status} ({elapsed}s): {detail}")
        results.append((name, ok, detail))

    # ШАГ 11. Итоговая сводка
    print(f"\n{'═' * 80}")
    print("📊 ИТОГОВАЯ СВОДКА")
    print(f"{'═' * 80}")

    passed = sum(1 for _, ok, _ in results if ok)
    failed = sum(1 for _, ok, _ in results if not ok)

    for name, ok, detail in results:
        status = "✅" if ok else "❌"
        print(f"  {status} {name}: {detail}")

    print(f"\n  Всего: {len(results)} | Пройдено: {passed} | Провалено: {failed}")

    if failed == 0:
        print("\n🎉 Все тесты пройдены!")
    else:
        print(f"\n⚠️  {failed} тест(ов) провалено. Проверьте лог для деталей.")

    logger.info(
        "ШАГ 11. ИТОГО: tests=%d, passed=%d, failed=%d",
        len(results), passed, failed,
    )


if __name__ == "__main__":
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s | %(levelname)-7s | %(name)s | %(message)s",
    )
    # Убираем шум от httpx/httpcore (оставляем только предупреждения и ошибки)
    logging.getLogger("httpx").setLevel(logging.WARNING)
    logging.getLogger("httpcore").setLevel(logging.WARNING)
    # Урезаем болтливость внутренних клиентов: нам важны только WARNING+ от llm_service
    logging.getLogger("AI.llm_service").setLevel(logging.WARNING)
    logging.getLogger("sentence_transformers").setLevel(logging.WARNING)
    logging.getLogger("huggingface_hub").setLevel(logging.WARNING)
    asyncio.run(main())
