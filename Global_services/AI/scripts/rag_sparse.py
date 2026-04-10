# -*- coding: utf-8 -*-
"""
Руководство к файлу build_sparse_cta.py
======================================

Назначение:
    Построить только SPARSE-индекс для документа «Методология.docx»
    (путь: AI/Preconditions/documents/Методология.docx) и выполнить
    тестовые вопросы, включая «Что в тексте говорится про CTA».

Этапы (логируются пошагово):
    ШАГ 1. Загрузка .env и проверка наличия документа.
    ШАГ 2. Инжест документа -> чанки (без dense-векторизации).
    ШАГ 3. SPARSE-векторизация чанков (батчами для экономии памяти).
    ШАГ 4. Создание sparse-only коллекции в Qdrant (если нет) —
            запросы выполняются с увеличенным таймаутом 60 c.
    ШАГ 5. Upsert чанков (только sparse-векторы) в коллекцию.
    ШАГ 6. SPARSE-поиск по списку тестовых запросов (вкл. CTA).

Переменные окружения (Global_services/.env):
    QDRANT_HOST           — хост Qdrant (например, localhost)
    QDRANT_PORT           — порт Qdrant (например, 6333)
    SPARSE_EMBED_MODEL    — модель sparse-векторизации

Запуск (из корня проекта):
    python -m AI.scripts.build_sparse_cta           # индекс + запросы
    python -m AI.scripts.build_sparse_cta --index-only
    python -m AI.scripts.build_sparse_cta --query-only

Примечания:
    - Используются только SparseEmbeddingClient и AsyncQdrantClient без dense-векторов.
    - Коллекция создаётся с единственным sparse-вектором "sparse".
"""
from __future__ import annotations

import argparse
import asyncio
import logging
import os
import time
from typing import Any, Dict, List

# Жёстко выключаем CUDA, чтобы sparse-модель работала на CPU (GPU может не хватить)
os.environ.setdefault("CUDA_VISIBLE_DEVICES", "")

from dotenv import load_dotenv

logger = logging.getLogger(__name__)

DOCUMENT_PATH = os.path.abspath(
    os.path.join(
        os.path.dirname(os.path.abspath(__file__)),
        "..",
        "Preconditions",
        "documents",
        "Методология.docx",
    )
)
DOCUMENT_NAME = "Методология.docx"
COLLECTION_NAME = "methodology_sparse_cta"
SPARSE_BATCH_SIZE = 6  # размер батча при sparse-векторизации
QDRANT_TIMEOUT = 60.0  # таймаут запросов к Qdrant (сек)

TEST_QUERIES = [
    "Что в тексте говорится про CTA",
    "какие CTA упоминаются и где они применяются",
    "как автор предлагает формировать call-to-action",
]


async def ensure_sparse_collection(client: Any, collection: str) -> None:
    """Создаёт sparse-only коллекцию при необходимости (collection_exists v1.8+)."""
    from qdrant_client.models import Modifier, SparseIndexParams, SparseVectorParams

    exists = await client.collection_exists(collection_name=collection)
    if exists:
        logger.info("ШАГ 4. Коллекция %s уже существует", collection)
        return

    logger.info("ШАГ 4. Создаём sparse-only коллекцию: %s (IDF modifier)", collection)
    await client.create_collection(
        collection_name=collection,
        vectors_config={},
        sparse_vectors_config={
            "sparse": SparseVectorParams(
                modifier=Modifier.IDF,
                index=SparseIndexParams(on_disk=False),
            ),
        },
    )
    logger.info("ШАГ 4. УСПЕХ: коллекция %s создана", collection)


async def run_indexing() -> Dict[str, Any]:
    """Индексация документа только sparse-векторами."""
    from AI.llm_service import (
        Chunker,
        DocumentIngestor,
        FileRef,
        RequestContext,
        SparseEmbeddingClient,
        SparseVectorData,
    )
    from qdrant_client import AsyncQdrantClient
    from qdrant_client.models import PointStruct

    # ШАГ 1. Загрузка .env
    env_path = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..", ".env"))
    load_dotenv(env_path)
    logger.info("ШАГ 1. Загружаем .env из %s", env_path)

    qdrant_host = os.environ.get("QDRANT_HOST", "localhost")
    qdrant_port = int(os.environ.get("QDRANT_PORT", "6333"))
    sparse_model = os.environ.get(
        "SPARSE_EMBED_MODEL",
        "opensearch-project/opensearch-neural-sparse-encoding-multilingual-v1",
    )

    if not os.path.isfile(DOCUMENT_PATH):
        logger.error("ШАГ 1. ОШИБКА: документ не найден: %s", DOCUMENT_PATH)
        return {"status": "error", "message": f"Файл не найден: {DOCUMENT_PATH}"}

    logger.info(
        "ШАГ 1. УСПЕХ: qdrant=%s:%d, sparse_model=%s, document=%s",
        qdrant_host,
        qdrant_port,
        sparse_model,
        DOCUMENT_NAME,
    )

    # ШАГ 2. Инжест документа -> чанки
    ingestor = DocumentIngestor(Chunker())
    ctx = RequestContext(request_id=f"sparse-index-cta-{int(time.time())}")

    file_ref = FileRef(
        path=DOCUMENT_PATH,
        original_name=DOCUMENT_NAME,
        mime_type="application/vnd.openxmlformats-officedocument.wordprocessingml.document",
    )
    try:
        chunks = await ingestor.ingest(file_ref, ctx)
    except Exception as exc:
        logger.error("ШАГ 2. ОШИБКА инжеста: %s", exc)
        return {"status": "error", "message": str(exc)}

    if not chunks:
        logger.error("ШАГ 2. ОШИБКА: инжест вернул 0 чанков")
        return {"status": "error", "message": "Нет чанков"}

    logger.info("ШАГ 2. УСПЕХ: получено %d чанков", len(chunks))

    # ШАГ 3. SPARSE-векторизация чанков
    sparse_client = SparseEmbeddingClient(model_name=sparse_model)
    texts = [c.text for c in chunks]
    sparse_vectors: List[SparseVectorData] = []

    for start in range(0, len(texts), SPARSE_BATCH_SIZE):
        batch = texts[start : start + SPARSE_BATCH_SIZE]
        logger.info(
            "ШАГ 3. Sparse-векторизация батча %d..%d из %d (CPU)",
            start,
            start + len(batch),
            len(texts),
        )
        try:
            batch_vectors = await sparse_client.embed_documents(batch, ctx)
            sparse_vectors.extend(batch_vectors)
        except Exception as exc:
            logger.error("ШАГ 3. ОШИБКА sparse-векторизации батча %d: %s", start, exc)
            return {"status": "error", "message": str(exc)}

    logger.info("ШАГ 3. УСПЕХ: %d sparse-векторов", len(sparse_vectors))

    # ШАГ 4. Создание коллекции (если нет)
    client = AsyncQdrantClient(
        host=qdrant_host,
        port=qdrant_port,
        timeout=QDRANT_TIMEOUT,
    )
    await ensure_sparse_collection(client, COLLECTION_NAME)

    # ШАГ 5. Upsert (SparseVectorData → to_qdrant())
    points: List[PointStruct] = []
    for chunk, sv in zip(chunks, sparse_vectors):
        points.append(
            PointStruct(
                id=chunk.id,
                vector={"sparse": sv.to_qdrant()},
                payload={
                    "text": chunk.text,
                    "source_id": chunk.source_id,
                    "page": chunk.page,
                    "offset": chunk.offset,
                    "checksum": chunk.checksum,
                    "document_name": DOCUMENT_NAME,
                },
            )
        )

    await client.upsert(collection_name=COLLECTION_NAME, points=points)
    logger.info("ШАГ 5. УСПЕХ: в коллекцию %s записано %d точек", COLLECTION_NAME, len(points))

    return {
        "status": "success",
        "collection": COLLECTION_NAME,
        "chunks": len(points),
    }


async def run_sparse_search(top_k: int = 5) -> None:
    """Выполнить sparse-поиск по CTA-вопросам."""
    from AI.llm_service import RequestContext, SparseEmbeddingClient
    from qdrant_client import AsyncQdrantClient

    env_path = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..", ".env"))
    load_dotenv(env_path)
    logger.info("ШАГ 1 (поиск). Загружаем .env из %s", env_path)

    qdrant_host = os.environ.get("QDRANT_HOST", "localhost")
    qdrant_port = int(os.environ.get("QDRANT_PORT", "6333"))
    sparse_model = os.environ.get(
        "SPARSE_EMBED_MODEL",
        "opensearch-project/opensearch-neural-sparse-encoding-multilingual-v1",
    )

    client = AsyncQdrantClient(
        host=qdrant_host,
        port=qdrant_port,
        timeout=QDRANT_TIMEOUT,
    )
    sparse_client = SparseEmbeddingClient(model_name=sparse_model)

    ctx = RequestContext(request_id=f"sparse-search-cta-{int(time.time())}")

    for i, query in enumerate(TEST_QUERIES, 1):
        logger.info("\n" + "=" * 80)
        logger.info("ШАГ 2.%d. Запрос: %s", i, query)
        try:
            q_sparse = await sparse_client.embed_query(query, ctx)
        except Exception as exc:
            logger.error("ШАГ 2.%d. ОШИБКА sparse embed запроса: %s", i, exc)
            continue

        res = await client.query_points(
            collection_name=COLLECTION_NAME,
            query=q_sparse.to_qdrant(),
            using="sparse",
            limit=top_k,
            with_payload=True,
        )

        points = res.points if hasattr(res, "points") else res
        logger.info("ШАГ 2.%d. Найдено %d точек", i, len(points))
        print("\n❓ Запрос:", query)
        for j, p in enumerate(points, 1):
            payload = p.payload or {}
            text = str(payload.get("text", ""))[:200].replace("\n", " ")
            page = payload.get("page", "?")
            score = getattr(p, "score", 0.0)
            print(f"[{j}] score={score:.4f} page={page} | {text}...")


async def main() -> None:
    parser = argparse.ArgumentParser(description="Sparse CTA индекс + поиск")
    parser.add_argument("--index-only", action="store_true", help="Только индексация")
    parser.add_argument("--query-only", action="store_true", help="Только поиск (коллекция уже есть)")
    parser.add_argument("--top-k", type=int, default=5, help="Сколько результатов выводить")
    args = parser.parse_args()

    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    )

    if not args.query_only:
        index_res = await run_indexing()
        logger.info("Индексация завершена: %s", index_res)
        if index_res.get("status") != "success":
            return

    if not args.index_only:
        await run_sparse_search(top_k=args.top_k)


if __name__ == "__main__":
    asyncio.run(main())
