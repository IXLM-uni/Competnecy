# -*- coding: utf-8 -*-
"""
Руководство к файлу search_chunks.py
====================================

Назначение:
    Простой скрипт для поиска топ-чанков в коллекции UC.
    Принимает текстовый запрос, векторизует его (dense + sparse)
    и возвращает наиболее релевантные чанки из Qdrant.

Архитектура (4 шага):
    ШАГ 1. Загрузка конфигурации и инициализация клиентов
    ШАГ 2. Генерация эмбеддингов запроса (dense + sparse)
    ШАГ 3. Поиск в Qdrant коллекции UC
    ШАГ 4. Вывод результатов

Используемые классы из llm_service.py:
    - CloudRuEmbeddingClient — dense эмбеддинги через Cloud.ru API
    - SparseEmbeddingClient — sparse эмбеддинги (локальная модель)
    - QdrantVectorStore — поиск в векторном хранилище

Переменные окружения (из Global_services/.env):
    CLOUDRU_API_KEY       — API-ключ Cloud.ru (обязательно)
    CLOUDRU_BASE_URL      — базовый URL (по умолчанию https://foundation-models.api.cloud.ru/v1)
    CLOUDRU_EMBED_MODEL   — модель эмбеддингов (по умолчанию Qwen/Qwen3-Embedding-0.6B)
    QDRANT_HOST           — хост Qdrant (по умолчанию localhost)
    QDRANT_PORT           — порт Qdrant (по умолчанию 6334)

Коллекция:
    Имя коллекции фиксировано: "UC"

Использование:
    # Поиск с дефолтным запросом:
    python -m AI.scripts.search_chunks

    # Поиск с кастомным запросом:
    python -m AI.scripts.search_chunks "мой запрос"

    # Или напрямую:
    python AI/scripts/search_chunks.py "как настроить Docker"

Зависимости:
    - llm_service.py (все классы сервиса)
    - python-dotenv (загрузка .env)
    - qdrant-client
    - sentence-transformers
"""

from __future__ import annotations

import asyncio
import logging
import os
import sys
import uuid
from pathlib import Path
from typing import Any, Dict, List

# ---------- Константы (должны быть ДО импорта AI.llm_service) ----------

SCRIPT_DIR = Path(__file__).parent.absolute()
AI_DIR = SCRIPT_DIR.parent
GLOBAL_SERVICES_DIR = AI_DIR.parent
SPARSE_CACHE_DIR = AI_DIR / "models" / "sparse_cache"

# Имя коллекции фиксировано
COLLECTION_NAME = "UC"

# Дефолтный поисковый запрос
DEFAULT_QUERY = "Что такое системная инженерия"

# Количество топ-результатов
TOP_K = 5

# Добавляем путь для импорта llm_service
sys.path.insert(0, str(GLOBAL_SERVICES_DIR))

from AI.llm_service import RequestContext  # Теперь GLOBAL_SERVICES_DIR определена

# Настройка логирования
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s | %(levelname)-7s | %(name)s | %(message)s",
)
logger = logging.getLogger(__name__)


# ---------- ШАГ 1: Инициализация клиентов ----------

async def init_clients() -> tuple[Any, Any, Any]:
    """
    ШАГ 1. Загрузка конфигурации и инициализация клиентов.

    Returns:
        Кортеж (embedding_client, sparse_client, vector_store)

    Логирование:
        «ШАГ 1. Загружаем .env — УСПЕХ»
        «ШАГ 1. Создаём клиенты — УСПЕХ»
    """
    logger.info("ШАГ 1. Загрузка конфигурации и инициализация клиентов")

    # Добавляем путь для импорта llm_service
    sys.path.insert(0, str(GLOBAL_SERVICES_DIR))

    from dotenv import load_dotenv
    from AI.llm_service import (
        CloudRuEmbeddingClient,
        QdrantVectorStore,
        SparseEmbeddingClient,
        Snippet,
    )

    # Загружаем .env
    env_path = GLOBAL_SERVICES_DIR / ".env"
    if env_path.exists():
        load_dotenv(env_path)
        logger.info("ШАГ 1. Загружен .env из %s — УСПЕХ", env_path)
    else:
        logger.warning("ШАГ 1. .env не найден, используем переменные окружения")

    # Проверка обязательных переменных
    api_key = os.environ.get("CLOUDRU_API_KEY")
    if not api_key:
        raise ValueError("CLOUDRU_API_KEY не задан в переменных окружения")

    base_url = os.environ.get("CLOUDRU_BASE_URL", "https://foundation-models.api.cloud.ru/v1")
    model_name = os.environ.get("CLOUDRU_EMBED_MODEL", "Qwen/Qwen3-Embedding-0.6B")
    qdrant_host = os.environ.get("QDRANT_HOST", "localhost")
    qdrant_port = int(os.environ.get("QDRANT_PORT", "6334"))
    sparse_cache_dir = os.environ.get("SPARSE_CACHE_DIR", str(SPARSE_CACHE_DIR))

    if not Path(sparse_cache_dir).exists():
        raise ValueError(f"SPARSE_CACHE_DIR не найден: {sparse_cache_dir}")

    logger.info("ШАГ 1. Конфигурация:")
    logger.info("  - Model: %s", model_name)
    logger.info("  - Qdrant: %s:%d", qdrant_host, qdrant_port)

    # Создаём клиенты
    logger.info("ШАГ 1. Создаём CloudRuEmbeddingClient...")
    embedding_client = CloudRuEmbeddingClient(
        api_key=api_key,
        base_url=base_url,
        model_name=model_name,
        batch_size=32,
    )

    logger.info("ШАГ 1. Создаём SparseEmbeddingClient...")
    sparse_client = SparseEmbeddingClient(cache_dir=sparse_cache_dir)

    logger.info("ШАГ 1. Создаём QdrantVectorStore...")
    vector_store = QdrantVectorStore(
        host=qdrant_host,
        port=qdrant_port,
        https=False,
    )

    logger.info("ШАГ 1. Все клиенты созданы — УСПЕХ")

    return embedding_client, sparse_client, vector_store


# ---------- ШАГ 2: Генерация эмбеддингов запроса ----------

async def embed_query(
    query: str,
    embedding_client: Any,
    sparse_client: Any,
    ctx: RequestContext,
) -> tuple[List[float], Dict[str, float]]:
    """
    ШАГ 2. Генерация dense и sparse эмбеддингов для запроса.

    Args:
        query: Текстовый запрос
        embedding_client: Клиент для dense эмбеддингов
        sparse_client: Клиент для sparse эмбеддингов

    Returns:
        Кортеж (dense_vector, sparse_vector)

    Логирование:
        «ШАГ 2. Генерация dense эмбеддинга — ОТПРАВЛЯЕМ / УСПЕХ»
        «ШАГ 2. Генерация sparse эмбеддинга — ОТПРАВЛЯЕМ / УСПЕХ»
    """
    logger.info("ШАГ 2. Генерация эмбеддингов для запроса: '%s'", query[:50])

    # Dense эмбеддинг
    logger.info("ШАГ 2. Генерация dense эмбеддинга — ОТПРАВЛЯЕМ...")
    dense_result = await embedding_client.embed_texts([query], ctx)
    dense_vector = dense_result[0]
    logger.info("ШАГ 2. Dense эмбеддинг получен (dim=%d) — УСПЕХ", len(dense_vector))

    # Sparse эмбеддинг
    logger.info("ШАГ 2. Генерация sparse эмбеддинга — ОТПРАВЛЯЕМ...")
    sparse_vectors = await sparse_client.embed_documents([query], ctx)
    sparse_vector = sparse_vectors[0]
    logger.info("ШАГ 2. Sparse эмбеддинг получен (nnz=%d) — УСПЕХ", sparse_vector.nnz)

    return dense_vector, sparse_vector


# ---------- ШАГ 3: Поиск в Qdrant ----------

async def search_chunks(
    dense_vector: List[float],
    sparse_vector: Dict[str, float],
    vector_store: Any,
    ctx: RequestContext,
    top_k: int = TOP_K,
) -> List[Snippet]:
    """
    ШАГ 3. Поиск ближайших чанков в коллекции UC.

    Args:
        dense_vector: Dense эмбеддинг запроса
        sparse_vector: Sparse эмбеддинг запроса
        vector_store: Клиент Qdrant
        top_k: Количество результатов

    Returns:
        Список найденных чанков с метаданными

    Логирование:
        «ШАГ 3. Поиск в коллекции UC — ОТПРАВЛЯЕМ»
        «ШАГ 3. Найдено N чанков — УСПЕХ»
    """
    logger.info("ШАГ 3. Поиск в коллекции '%s' (top_k=%d) — ОТПРАВЛЯЕМ...", COLLECTION_NAME, top_k)

    results = await vector_store.search(
        collection=COLLECTION_NAME,
        query_dense=dense_vector,
        query_sparse=sparse_vector,
        top_k=top_k,
        ctx=ctx,
    )

    logger.info("ШАГ 3. Найдено %d чанков — УСПЕХ", len(results))

    return results


# ---------- ШАГ 4: Вывод результатов ----------

def print_results(results: List[Snippet], query: str) -> None:
    """
    ШАГ 4. Вывод результатов поиска.

    Args:
        results: Список найденных чанков
        query: Исходный запрос

    Логирование:
        «ШАГ 4. Вывод результатов — УСПЕХ»
    """
    logger.info("ШАГ 4. Вывод результатов")

    print("\n" + "=" * 70)
    print(f"🔍 РЕЗУЛЬТАТЫ ПОИСКА: '{query}'")
    print("=" * 70)

    if not results:
        print("❌ Ничего не найдено")
        return

    for i, snippet in enumerate(results, 1):
        score = snippet.score
        text = snippet.text[:300]
        doc_name = snippet.metadata.get("document_name", "unknown") if snippet.metadata else "unknown"
        source_id = snippet.source_id

        print(f"\n📄 Результат #{i} (score: {score:.4f})")
        print(f"   Документ: {doc_name}")
        print(f"   Source ID: {source_id}")
        print(f"   Текст: {text}...")
        print("-" * 70)

    logger.info("ШАГ 4. Вывод результатов завершен — УСПЕХ")


# ---------- Основная функция ----------

async def main(query: str | None = None) -> List[Snippet]:
    """
    Основная функция поиска топ-чанков.

    Args:
        query: Поисковый запрос (если None, используется DEFAULT_QUERY или аргументы CLI)

    Returns:
        Список найденных чанков
    """
    # Получаем запрос из аргументов CLI если не передан
    if query is None:
        if len(sys.argv) > 1:
            query = " ".join(sys.argv[1:])
        else:
            query = DEFAULT_QUERY

    logger.info("=" * 70)
    logger.info("🔍 ПОИСК ТОП-ЧАНКОВ В КОЛЛЕКЦИИ UC")
    logger.info("=" * 70)
    logger.info("Запрос: %s", query)

    try:
        # Создаём контекст запроса
        ctx = RequestContext(request_id=f"search-{uuid.uuid4().hex[:8]}")
        logger.info("Создан RequestContext: request_id=%s", ctx.request_id)

        # ШАГ 1: Инициализация
        embedding_client, sparse_client, vector_store = await init_clients()

        # ШАГ 2: Эмбеддинги запроса
        dense_vector, sparse_vector = await embed_query(
            query, embedding_client, sparse_client, ctx
        )

        # ШАГ 3: Поиск в Qdrant
        results = await search_chunks(
            dense_vector, sparse_vector, vector_store, ctx, top_k=TOP_K
        )

        # ШАГ 4: Вывод результатов
        print_results(results, query)

        logger.info("=" * 70)
        logger.info("✅ Поиск завершен успешно")
        logger.info("=" * 70)

        return results

    except Exception as exc:
        logger.error("=" * 70)
        logger.error("❌ ОШИБКА: %s", exc)
        logger.error("=" * 70)
        raise


# ---------- Точка входа ----------

if __name__ == "__main__":
    try:
        results = asyncio.run(main())
        sys.exit(0)
    except Exception:
        sys.exit(1)
