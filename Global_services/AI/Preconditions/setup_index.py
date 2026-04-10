# -*- coding: utf-8 -*-
"""
Руководство к файлу setup_index.py
===================================

Назначение:
    Скрипт bulk-индексации: инжест файлов из Preconditions/documents
    и Preconditions/RAG/Data.txt → чанкование → векторизация через
    CloudRuEmbeddingClient → upsert в Qdrant.

    Используется как precondition перед запуском e2e-тестов для UC-1, UC-4.

Переменные окружения:
    CLOUDRU_API_KEY       — API-ключ Cloud.ru (обязательно)
    CLOUDRU_BASE_URL      — базовый URL (по умолчанию https://foundation-models.api.cloud.ru/v1)
    CLOUDRU_EMBED_MODEL   — модель эмбеддингов (по умолчанию Qwen/Qwen3-Embedding-0.6B)
    QDRANT_HOST           — хост Qdrant (по умолчанию localhost)
    QDRANT_PORT           — порт Qdrant (по умолчанию 6334)
    QDRANT_COLLECTION     — имя коллекции (по умолчанию e2e_test)

Использование:
    # из корня проекта Global_services:
    python -m AI.Preconditions.setup_index

    # или напрямую:
    python AI/Preconditions/setup_index.py
"""

from __future__ import annotations

import asyncio
import glob
import logging
import os
import sys

logger = logging.getLogger(__name__)

# ---------- Пути к данным ----------

PRECONDITIONS_DIR = os.path.dirname(os.path.abspath(__file__))
DOCUMENTS_DIR = os.path.join(PRECONDITIONS_DIR, "documents")
RAG_DIR = os.path.join(PRECONDITIONS_DIR, "RAG")

# Поддерживаемые расширения для инжеста
SUPPORTED_EXTENSIONS = (".pdf", ".docx", ".doc", ".html", ".htm", ".txt", ".md")


def _collect_files() -> list[str]:
    """Собирает все поддерживаемые файлы из documents/ и RAG/."""
    files: list[str] = []

    # documents/
    if os.path.isdir(DOCUMENTS_DIR):
        for entry in os.listdir(DOCUMENTS_DIR):
            fpath = os.path.join(DOCUMENTS_DIR, entry)
            if os.path.isfile(fpath) and os.path.splitext(entry)[1].lower() in SUPPORTED_EXTENSIONS:
                files.append(fpath)

    # RAG/Data.txt
    rag_data = os.path.join(RAG_DIR, "Data.txt")
    if os.path.isfile(rag_data):
        files.append(rag_data)

    return sorted(files)


async def run_setup_index() -> dict:
    """Основная функция: инжест + индексация.

    ШАГ 1. Загрузка .env и проверка переменных
    ШАГ 2. Сбор файлов
    ШАГ 3. Создание клиентов (embedding, Qdrant)
    ШАГ 4. Вызов ingest_and_index
    ШАГ 5. Отчёт
    """
    from dotenv import load_dotenv

    # ШАГ 1. Загрузка .env
    env_path = os.path.join(PRECONDITIONS_DIR, "..", "..", ".env")
    env_path = os.path.abspath(env_path)
    load_dotenv(env_path)
    logger.info("ШАГ 1. Загружаем .env из %s", env_path)

    api_key = os.environ.get("CLOUDRU_API_KEY")
    if not api_key:
        logger.error("ШАГ 1. ОШИБКА: CLOUDRU_API_KEY не задан")
        return {"status": "error", "message": "CLOUDRU_API_KEY не задан"}

    qdrant_host = os.environ.get("QDRANT_HOST", "localhost")
    qdrant_port = int(os.environ.get("QDRANT_PORT", "6334"))
    collection = os.environ.get("QDRANT_COLLECTION", "e2e_test")

    logger.info(
        "ШАГ 1. УСПЕХ: qdrant=%s:%d, collection=%s",
        qdrant_host, qdrant_port, collection,
    )

    # ШАГ 2. Сбор файлов
    files = _collect_files()
    logger.info("ШАГ 2. Найдено файлов для индексации: %d", len(files))
    for f in files:
        logger.info("  - %s", os.path.basename(f))

    if not files:
        logger.warning("ШАГ 2. Нет файлов — выход")
        return {"status": "warning", "message": "Нет файлов для индексации"}

    # ШАГ 3. Создание клиентов
    from AI.llm_service import (
        CloudRuEmbeddingClient,
        QdrantVectorStore,
        ingest_and_index,
    )

    embedding_client = CloudRuEmbeddingClient(
        api_key=api_key,
        base_url=os.environ.get(
            "CLOUDRU_BASE_URL", "https://foundation-models.api.cloud.ru/v1",
        ),
        model_name=os.environ.get(
            "CLOUDRU_EMBED_MODEL", "Qwen/Qwen3-Embedding-0.6B",
        ),
    )
    vector_store = QdrantVectorStore(
        host=qdrant_host, port=qdrant_port, https=False,
    )
    logger.info("ШАГ 3. Клиенты созданы: CloudRuEmbeddingClient + QdrantVectorStore")

    # ШАГ 4. Bulk-индексация
    logger.info("ШАГ 4. Запускаем ingest_and_index ...")
    chunks = await ingest_and_index(
        file_paths=files,
        embedding_client=embedding_client,
        vector_store=vector_store,
        collection=collection,
        batch_size=32,
    )

    # ШАГ 5. Отчёт
    report = {
        "status": "success",
        "files_processed": len(files),
        "total_chunks": len(chunks),
        "collection": collection,
        "qdrant": f"{qdrant_host}:{qdrant_port}",
    }
    logger.info("ШАГ 5. Индексация завершена: %s", report)
    return report


# --- CLI-точка входа ---
if __name__ == "__main__":
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s | %(levelname)-7s | %(name)s | %(message)s",
    )
    result = asyncio.run(run_setup_index())
    print(f"\n{'='*60}")
    print(f"Результат индексации: {result}")
    print(f"{'='*60}")
