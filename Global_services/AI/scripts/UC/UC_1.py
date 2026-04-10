# -*- coding: utf-8 -*-
"""
Руководство к файлу UC_1.py
==========================

Назначение:
    Реализация UC-1: Пакетная индексация документов в RAG (Batch Ingestion).
    Скрипт индексирует ВСЕ документы из папки Preconditions/documents
    в векторное хранилище Qdrant в коллекцию "UC".

    Use Case: UC-1 из LLM_SERVICE.md
    Actor: Администратор системы / Фоновый процесс
    Цель: Массовая загрузка и индексация документов в векторное хранилище.

Архитектура (6 шагов UC-1):
    ШАГ 1. Получение списка файлов — DocumentIngestor.scan_directory()
    ШАГ 2-5. Bulk-индексация — ingest_and_index()
    ШАГ 6. Отчет — generate_indexing_report()

Используемые классы/функции из llm_service.py:
    - load_env_and_validate — загрузка .env + валидация
    - DocumentIngestor.scan_directory — сканирование директории
    - CloudRuEmbeddingClient, SparseEmbeddingClient — эмбеддинги
    - QdrantVectorStore — хранилище векторов в Qdrant
    - ingest_and_index — bulk-индексация
    - IndexMetadata — метаданные индексации
    - generate_indexing_report — формирование отчета

Использование:
    python -m AI.scripts.UC.UC_1

Зависимости:
    - llm_service.py (все классы сервиса)
    - python-dotenv (загрузка .env)
"""

from __future__ import annotations

import asyncio
import logging
import sys
from pathlib import Path
from typing import Any, Dict

# ---------- Настройка путей и импортов ----------
SCRIPT_DIR = Path(__file__).parent.absolute()
AI_DIR = SCRIPT_DIR.parent.parent
GLOBAL_SERVICES_DIR = AI_DIR.parent
DOCUMENTS_DIR = AI_DIR / "Preconditions" / "documents"
SPARSE_CACHE_DIR = AI_DIR / "models" / "sparse_cache"
COLLECTION_NAME = "UC"

sys.path.insert(0, str(GLOBAL_SERVICES_DIR))

from AI.llm_service import (
    CloudRuEmbeddingClient,
    DocumentIngestor,
    IndexMetadata,
    QdrantVectorStore,
    SparseEmbeddingClient,
    generate_indexing_report,
    ingest_and_index,
    load_env_and_validate,
)

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s | %(levelname)-7s | %(name)s | %(message)s",
)
logger = logging.getLogger(__name__)


async def run_batch_indexing(cfg: Dict[str, str], files: list[str]) -> Dict[str, Any]:
    """ШАГ 2-5. Параллельный инжест, чанкинг, эмбеддинги и индексация."""
    logger.info("ШАГ 2-5. Начинаем batch-индексацию %d файлов", len(files))

    embedding_client = CloudRuEmbeddingClient(
        api_key=cfg["CLOUDRU_API_KEY"],
        base_url=cfg["CLOUDRU_BASE_URL"],
        model_name=cfg["CLOUDRU_EMBED_MODEL"],
        batch_size=32,
    )
    sparse_client = SparseEmbeddingClient(
        cache_dir=cfg["SPARSE_CACHE_DIR"] or str(SPARSE_CACHE_DIR),
    )
    vector_store = QdrantVectorStore(
        host=cfg["QDRANT_HOST"],
        port=int(cfg["QDRANT_PORT"]),
        https=False,
    )

    index_metadata = IndexMetadata(
        document_name="UC_documents_batch",
        user_id="admin",
        tags=["UC", "batch_indexing", "preconditions"],
        custom_data={"source": "UC_1.py", "collection": COLLECTION_NAME},
    )

    try:
        chunks = await ingest_and_index(
            file_paths=files,
            embedding_client=embedding_client,
            vector_store=vector_store,
            collection=COLLECTION_NAME,
            sparse_client=sparse_client,
            index_metadata=index_metadata,
            batch_size=4,
        )
        logger.info("ШАГ 2-5. Bulk-индексация завершена — УСПЕХ: %d чанков", len(chunks))
        return {
            "status": "success",
            "files_processed": len(files),
            "total_chunks": len(chunks),
        }
    except Exception as exc:
        logger.error("ШАГ 2-5. ОШИБКА при batch-индексации: %s", exc)
        return {"status": "error", "error": str(exc), "files_processed": 0, "total_chunks": 0}


async def main() -> Dict[str, Any]:
    """Основная функция UC-1: Пакетная индексация документов."""
    logger.info("=" * 70)
    logger.info("UC-1: Пакетная индексация документов в RAG")
    logger.info("Коллекция: %s | Директория: %s", COLLECTION_NAME, DOCUMENTS_DIR)
    logger.info("=" * 70)

    # ШАГ 0. Загрузка конфигурации
    try:
        cfg = load_env_and_validate(str(GLOBAL_SERVICES_DIR))
    except ValueError as exc:
        return {"status": "error", "message": str(exc)}

    sparse_dir = cfg["SPARSE_CACHE_DIR"] or str(SPARSE_CACHE_DIR)
    if not Path(sparse_dir).exists():
        logger.error("ОШИБКА: SPARSE_CACHE_DIR не найден: %s", sparse_dir)
        return {"status": "error", "message": "SPARSE_CACHE_DIR не найден"}

    # ШАГ 1. Получение списка файлов
    files = DocumentIngestor.scan_directory(str(DOCUMENTS_DIR))
    if not files:
        return {"status": "error", "message": "Нет файлов для индексации"}

    for i, f in enumerate(files, 1):
        logger.info("  %d. %s", i, Path(f).name)

    # ШАГ 2-5. Индексация
    results = await run_batch_indexing(cfg, files)

    # ШАГ 6. Отчет
    report_json = generate_indexing_report(
        files_processed=results.get("files_processed", 0),
        total_chunks=results.get("total_chunks", 0),
        collection=COLLECTION_NAME,
        status=results.get("status", "unknown"),
        error=results.get("error") if results.get("status") != "success" else None,
        qdrant_host=cfg["QDRANT_HOST"],
        qdrant_port=int(cfg["QDRANT_PORT"]),
    )
    logger.info("РЕЗУЛЬТАТ UC-1:\n%s", report_json)

    return results


if __name__ == "__main__":
    result = asyncio.run(main())

    print("\n" + "=" * 70)
    print("UC-1: ПАКЕТНАЯ ИНДЕКСАЦИЯ ЗАВЕРШЕНА")
    print("=" * 70)
    print(f"Статус: {result.get('status', 'unknown')}")
    print(f"Коллекция: {COLLECTION_NAME}")
    print(f"Файлов обработано: {result.get('files_processed', 0)}")
    print(f"Всего чанков: {result.get('total_chunks', 0)}")

    if result.get("status") == "error":
        print(f"Ошибка: {result.get('error', result.get('message', 'Unknown'))}")
        sys.exit(1)
    else:
        print("\nУСПЕХ: Все документы проиндексированы в коллекцию 'UC'")
        sys.exit(0)