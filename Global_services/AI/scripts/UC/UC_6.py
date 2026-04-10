# -*- coding: utf-8 -*-
"""
Руководство к файлу UC_6.py
===========================

Назначение:
    Реализация UC-6: RAG-поиск с динамическими фильтрами по метаданным.
    1. Получение запроса с фильтрами (user_id, tags, date_from и т.д.)
    2. Переписывание запроса — RagQueryRewriter
    3. Гибридный поиск с фильтрацией — Retriever.retrieve_multi()
    4. Формирование сниппетов и LLM-ответ

    Use Case: UC-6 из LLM_SERVICE.md
    Actor: Пользователь / Исследователь
    Цель: Поиск по базе знаний с фильтрацией по тегам, датам, авторам.

Архитектура (6 шагов UC-6):
    ШАГ 1. Получение запроса с фильтрами
    ШАГ 2. Переписывание запроса — RagQueryRewriter.rewrite()
    ШАГ 3. Конвертация фильтров → Qdrant Filter (авто через Retriever)
    ШАГ 4. Гибридный поиск с фильтрацией — Retriever.retrieve_multi()
    ШАГ 5. Формирование сниппетов
    ШАГ 6. LLM-ответ с учетом отфильтрованных источников

Используемые функции из llm_service.py:
    - load_env_and_validate, create_rag_clients_from_env
    - create_cloudru_openai_client_from_env, RagQueryRewriter
    - build_rag_prompt, stream_llm_to_stdout, query_llm_simple
    - RequestContext

Использование:
    python -m AI.scripts.UC.UC_6 "поисковый запрос" [--tags tag1 tag2] [--user-id uid]

Зависимости:
    - llm_service.py, python-dotenv
"""

from __future__ import annotations

import asyncio
import json
import logging
import sys
from pathlib import Path
from typing import Any, Dict, List, Optional

# ---------- Константы ----------
SCRIPT_DIR = Path(__file__).parent.absolute()
AI_DIR = SCRIPT_DIR.parent.parent
GLOBAL_SERVICES_DIR = AI_DIR.parent
SPARSE_CACHE_DIR = AI_DIR / "models" / "sparse_cache"
COLLECTION_NAME = "UC"

sys.path.insert(0, str(GLOBAL_SERVICES_DIR))

from AI.llm_service import (
    RagQueryRewriter,
    RequestContext,
    build_rag_prompt,
    create_cloudru_openai_client_from_env,
    create_rag_clients_from_env,
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
    "Ты — эксперт по анализу документов. Давай точные, структурированные ответы "
    "с указанием источников. Используй ТОЛЬКО предоставленный контекст."
)


async def main(
    query: Optional[str] = None,
    filters: Optional[Dict[str, Any]] = None,
    limit: int = 10,
    use_streaming: bool = False,
) -> Dict[str, Any]:
    """Основная функция UC-6: RAG-поиск с динамическими фильтрами."""
    logger.info("=" * 70)
    logger.info("UC-6: RAG-поиск с динамическими фильтрами по метаданным")
    logger.info("=" * 70)

    if not query:
        query = "Основные концепции машинного обучения"
        logger.info("Запрос не указан, используем демо: '%s'", query)

    filters = filters or {}

    # ШАГ 0. Конфигурация
    try:
        cfg = load_env_and_validate(str(GLOBAL_SERVICES_DIR))
    except ValueError as exc:
        return {"status": "error", "message": str(exc)}

    sparse_dir = cfg["SPARSE_CACHE_DIR"] or str(SPARSE_CACHE_DIR)
    if not Path(sparse_dir).exists():
        logger.error("ОШИБКА: SPARSE_CACHE_DIR не найден: %s", sparse_dir)
        return {"status": "error", "message": "SPARSE_CACHE_DIR не найден"}

    # ШАГ 1. Получение запроса с фильтрами
    logger.info("ШАГ 1. Получен запрос с фильтрами — УСПЕХ")
    logger.info("  Запрос: '%s' (%d символов)", query[:80], len(query))
    logger.info("  Фильтры: %s", json.dumps(filters, ensure_ascii=False) if filters else "(нет)")
    logger.info("  Лимит: %d", limit)

    # ШАГ 2. Переписывание запроса
    logger.info("ШАГ 2. Перефразирование запроса — ОТПРАВЛЯЕМ")
    llm_client = create_cloudru_openai_client_from_env()
    rewriter = RagQueryRewriter(llm_client=llm_client, count=3)
    ctx = RequestContext(
        request_id="uc6-rag",
        user_id=filters.get("user_id", "uc6_user"),
        mode="rag_qa",
        rag_top_k=limit,
        rag_filters=filters if filters else None,
    )

    try:
        search_queries = await rewriter.rewrite(query, ctx)
    except Exception as exc:
        logger.warning("ШАГ 2. ОШИБКА: %s — используем оригинал", exc)
        search_queries = [query]

    logger.info("ШАГ 2. Перефразирование запроса — УСПЕХ: %d вариантов", len(search_queries))
    for i, q in enumerate(search_queries, 1):
        logger.info("  [%d] %s", i, q[:80])

    # ШАГ 3. Конвертация фильтров (авто внутри Retriever)
    logger.info("ШАГ 3. Фильтры будут конвертированы в Qdrant Filter автоматически — УСПЕХ")

    # ШАГ 4. Гибридный поиск с фильтрацией
    logger.info("ШАГ 4. Гибридный поиск с фильтрами — ОТПРАВЛЯЕМ")
    clients = create_rag_clients_from_env(
        collection=COLLECTION_NAME,
        sparse_cache_dir=sparse_dir,
    )
    retriever = clients["retriever"]

    snippets = await retriever.retrieve_multi(
        queries=search_queries,
        ctx=ctx,
        top_k=limit,
        filters=filters if filters else None,
    )

    logger.info("ШАГ 4. Поиск с фильтрами — УСПЕХ: %d сниппетов", len(snippets))

    # ШАГ 5. Формирование сниппетов
    logger.info("ШАГ 5. Сниппеты сформированы — УСПЕХ")
    snippets_dicts: List[Dict[str, Any]] = [
        {
            "text": s.text,
            "source_id": s.source_id,
            "score": s.score,
            "metadata": s.metadata,
        }
        for s in snippets
    ]
    for i, s in enumerate(snippets_dicts, 1):
        logger.info("  [%d] score=%.3f | src=%s | %.80s...",
                     i, s["score"], s["source_id"][:30], s["text"])

    # ШАГ 6. LLM-ответ
    logger.info("ШАГ 6. LLM-ответ с фильтрованными источниками — ОТПРАВЛЯЕМ")
    prompt = build_rag_prompt(query=query, snippets=snippets_dicts)
    llm_ctx = RequestContext(request_id="uc6-llm", user_id="uc6_user", mode="rag_qa")

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

    logger.info("ШАГ 6. Ответ с фильтрованными источниками — УСПЕХ")

    result: Dict[str, Any] = {
        "status": "success" if llm_answer else "error",
        "uc": "UC-6",
        "query": query,
        "filters": filters,
        "search_queries": search_queries,
        "collection": COLLECTION_NAME,
        "snippets_found": len(snippets_dicts),
        "snippets": snippets_dicts,
        "llm_answer": llm_answer,
        "llm_answer_length": len(llm_answer) if llm_answer else 0,
    }
    if not llm_answer:
        result["error"] = "LLM не вернул ответ"

    logger.info("РЕЗУЛЬТАТ UC-6: status=%s, snippets=%d, answer_len=%d",
                result["status"], len(snippets_dicts), result["llm_answer_length"])
    return result


if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser(description="UC-6: RAG-поиск с фильтрами")
    parser.add_argument("query", nargs="?", default=None, help="Поисковый запрос")
    parser.add_argument("--tags", nargs="*", default=None, help="Фильтр по тегам")
    parser.add_argument("--user-id", default=None, help="Фильтр по user_id")
    parser.add_argument("--document-name", default=None, help="Фильтр по document_name")
    parser.add_argument("--limit", type=int, default=10, help="Максимум результатов")
    parser.add_argument("--stream", action="store_true", help="Стриминг ответа")
    args = parser.parse_args()

    _filters: Dict[str, Any] = {}
    if args.tags:
        _filters["tags"] = args.tags
    if args.user_id:
        _filters["user_id"] = args.user_id
    if args.document_name:
        _filters["document_name"] = args.document_name

    try:
        result = asyncio.run(main(
            query=args.query, filters=_filters,
            limit=args.limit, use_streaming=args.stream,
        ))

        print("\n" + "=" * 70)
        print("UC-6: RAG-ПОИСК С ФИЛЬТРАМИ ЗАВЕРШЁН")
        print("=" * 70)
        print(f"Статус: {result.get('status', 'unknown')}")
        print(f"Запрос: {result.get('query', 'N/A')}")
        print(f"Фильтры: {json.dumps(result.get('filters', {}), ensure_ascii=False)}")
        print(f"Сниппетов: {result.get('snippets_found', 0)}")
        print(f"Длина ответа: {result.get('llm_answer_length', 0)} символов")

        sys.exit(0 if result.get("status") == "success" else 1)

    except KeyboardInterrupt:
        print("\nПрервано пользователем")
        sys.exit(130)
    except Exception as exc:
        logger.exception("Критическая ошибка в UC-6: %s", exc)
        sys.exit(1)
