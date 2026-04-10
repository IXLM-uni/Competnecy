# -*- coding: utf-8 -*-
"""
Руководство к файлу rag_sparse_health.py
=======================================

Назначение:
    Построить sparse-only индекс для PDF «Stress cognitive .pdf»
    (путь: AI/Preconditions/documents/Stress cognitive .pdf) и ответить на
    вопросы о содержании через поиск в Qdrant и вызов LLM.

Этапы (логируются пошагово):
    ШАГ 1. Загрузка .env, чтение параметров и проверка наличия PDF.
    ШАГ 2. Инжест PDF → чанки (text, page, offset, checksum).
    ШАГ 3. Sparse-векторизация чанков батчами (cache_dir указан для кеша модели).
    ШАГ 4. Создание sparse-only коллекции в Qdrant + payload indexes.
    ШАГ 5. Upsert точек (vector.sparse + payload с user_id, документом и т.д.).
    ШАГ 6. Sparse-поиск по вопросам с фильтром по user_id.
    ШАГ 7. LLM-ответ по найденным сниппетам.

Переменные окружения (Global_services/.env):
    QDRANT_HOST, QDRANT_PORT
    SPARSE_EMBED_MODEL
    LLM_API_KEY, LLM_BASE_URL, LLM_MODEL (опционально)
    USER_ID (можно переопределить аргументом CLI)

Запуск (из корня проекта):
    python -m AI.scripts.rag_sparse_health                 # индекс + поиск + LLM
    python -m AI.scripts.rag_sparse_health --index-only
    python -m AI.scripts.rag_sparse_health --query-only
    python -m AI.scripts.rag_sparse_health --top-k 5 --user-id u123 --cache-dir AI/models/sparse_cache

Примечания:
    - Не задаём CUDA_VISIBLE_DEVICES (используем CPU по требованию).
    - Коллекция создаётся sparse-only (modifier=IDF, on_disk=False), dense не используется.
    - Кеш sparse-модели указывается через --cache-dir или env.
"""
from __future__ import annotations

import argparse
import asyncio
import logging
import os
import time
from typing import Any, Dict, List, Optional

from dotenv import load_dotenv

logger = logging.getLogger(__name__)

DOCUMENT_PATH = os.path.abspath(
    os.path.join(
        os.path.dirname(os.path.abspath(__file__)),
        "..",
        "Preconditions",
        "documents",
        "Stress cognitive .pdf",
    )
)
DOCUMENT_NAME = "Stress cognitive .pdf"
COLLECTION_NAME = "stress_cognitive_sparse"
SPARSE_BATCH_SIZE = 6
QDRANT_TIMEOUT = 60.0

TEST_QUERIES = [
    "Что такое OpenBCI",
    "Что такое fNIRS анализ",
    "Какой TLX effort и TLX frustration",
]


def _load_env() -> str:
    env_path = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..", ".env"))
    load_dotenv(env_path)
    logger.info("ШАГ 1. Загружаем .env из %s", env_path)
    return env_path


async def ensure_sparse_collection(client: Any, collection: str) -> None:
    """Создаёт sparse-only коллекцию и payload indexes при отсутствии."""
    from qdrant_client.models import Modifier, PayloadSchemaType, SparseIndexParams, SparseVectorParams

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
    logger.info("ШАГ 4. Коллекция создана, настраиваем payload indexes")
    for field_name, schema in [
        ("user_id", PayloadSchemaType.KEYWORD),
        ("document_name", PayloadSchemaType.KEYWORD),
        ("page", PayloadSchemaType.INTEGER),
    ]:
        try:
            await client.create_payload_index(
                collection_name=collection,
                field_name=field_name,
                field_schema=schema,
            )
            logger.info("ШАГ 4. Payload index создан: %s", field_name)
        except Exception as exc:
            logger.warning("ШАГ 4. Не удалось создать index %s: %s", field_name, exc)
    logger.info("ШАГ 4. УСПЕХ: коллекция %s подготовлена", collection)


async def run_indexing(user_id: str, cache_dir: Optional[str]) -> Dict[str, Any]:
    """Индексация PDF только sparse-векторами."""
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

    _load_env()

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
        "ШАГ 1. УСПЕХ: qdrant=%s:%d, sparse_model=%s, document=%s, user_id=%s, cache_dir=%s",
        qdrant_host,
        qdrant_port,
        sparse_model,
        DOCUMENT_NAME,
        user_id,
        cache_dir,
    )

    # ШАГ 2. Инжест документа -> чанки
    ingestor = DocumentIngestor(Chunker())
    ctx = RequestContext(request_id=f"sparse-index-health-{int(time.time())}")

    file_ref = FileRef(
        path=DOCUMENT_PATH,
        original_name=DOCUMENT_NAME,
        mime_type="application/pdf",
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
    sparse_client = SparseEmbeddingClient(model_name=sparse_model, cache_dir=cache_dir)
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
            logger.info(
                "ШАГ 3. УСПЕХ батча %d..%d: nnz=%s",
                start,
                start + len(batch),
                [v.nnz for v in batch_vectors],
            )
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

    # ШАГ 5. Upsert
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
                    "user_id": user_id,
                },
            )
        )

    await client.upsert(collection_name=COLLECTION_NAME, points=points, wait=True)
    logger.info("ШАГ 5. УСПЕХ: в коллекцию %s записано %d точек", COLLECTION_NAME, len(points))

    return {
        "status": "success",
        "collection": COLLECTION_NAME,
        "chunks": len(points),
    }


async def run_sparse_search(top_k: int, user_id: str, cache_dir: Optional[str]) -> List[Dict[str, Any]]:
    """Выполнить sparse-поиск по тестовым вопросам."""
    from AI.llm_service import RequestContext, SparseEmbeddingClient
    from qdrant_client import AsyncQdrantClient
    from qdrant_client.models import FieldCondition, Filter, MatchValue

    _load_env()

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
    sparse_client = SparseEmbeddingClient(model_name=sparse_model, cache_dir=cache_dir)

    ctx = RequestContext(request_id=f"sparse-search-health-{int(time.time())}")
    all_results: List[Dict[str, Any]] = []

    for i, query in enumerate(TEST_QUERIES, 1):
        logger.info("\n" + "=" * 80)
        logger.info("ШАГ 6.%d. Запрос: %s", i, query)
        try:
            q_sparse = await sparse_client.embed_query(query, ctx)
        except Exception as exc:
            logger.error("ШАГ 6.%d. ОШИБКА sparse embed запроса: %s", i, exc)
            continue

        res = await client.query_points(
            collection_name=COLLECTION_NAME,
            query=q_sparse.to_qdrant(),
            using="sparse",
            limit=top_k,
            with_payload=True,
            query_filter=Filter(  # type: ignore[arg-type]
                must=[FieldCondition(key="user_id", match=MatchValue(value=user_id))]
            ),
        )

        points = res.points if hasattr(res, "points") else res
        logger.info("ШАГ 6.%d. Найдено %d точек", i, len(points))
        print("\n❓ Запрос:", query)

        result_items: List[Dict[str, Any]] = []
        for j, p in enumerate(points, 1):
            payload = p.payload or {}
            text = str(payload.get("text", ""))[:200].replace("\n", " ")
            page = payload.get("page", "?")
            score = getattr(p, "score", 0.0)
            print(f"[{j}] score={score:.4f} page={page} | {text}...")
            result_items.append(
                {
                    "score": score,
                    "page": page,
                    "text": payload.get("text", ""),
                }
            )
        all_results.append({"query": query, "results": result_items})

    return all_results


async def run_llm_answers(results: List[Dict[str, Any]], user_id: str, top_k: int) -> None:
    """Сформировать ответы LLM по найденным сниппетам."""
    from AI.llm_service import LLMMessage, LLMRequest, OpenAIClient, RequestContext

    api_key = os.environ.get("LLM_API_KEY")
    base_url = os.environ.get("LLM_BASE_URL")
    model_name = os.environ.get("LLM_MODEL", "gpt-4.1-mini")

    if not api_key:
        logger.error("ШАГ 7. ОШИБКА: LLM_API_KEY не задан")
        return

    client = OpenAIClient(api_key=api_key, base_url=base_url, default_model=model_name)

    for item in results:
        query = item.get("query", "")
        snippets = item.get("results", [])[:top_k]
        if not snippets:
            logger.warning("ШАГ 7. Пропускаем вопрос без сниппетов: %s", query)
            continue

        ctx = RequestContext(request_id=f"llm-answer-health-{int(time.time())}")
        context_parts = []
        for idx, sn in enumerate(snippets, 1):
            context_parts.append(f"[SNIPPET {idx} score={sn.get('score', 0):.3f} p={sn.get('page', '?')}] {sn.get('text', '')}")

        prompt = (
            "Ты — ассистент, отвечающий строго по данным из сниппетов. "
            "Если ответа нет в сниппетах, скажи, что информации нет.\n\n"
            f"Вопрос: {query}\n\n"
            "Сниппеты:\n" + "\n\n".join(context_parts)
        )

        request = LLMRequest(messages=[LLMMessage(role="user", content=prompt)], model=model_name)
        try:
            response = await client.create_response(request, ctx)
            logger.info("ШАГ 7. ЛЛМ-ответ — УСПЕХ: request_id=%s", ctx.request_id)
            print("\n🤖 Ответ ЛЛМ на вопрос:", query)
            print(response.content)
        except Exception as exc:
            logger.error("ШАГ 7. ЛЛМ-ответ — ОШИБКА: %s", exc)


async def main() -> None:
    parser = argparse.ArgumentParser(description="Sparse RAG по Stress cognitive .pdf")
    parser.add_argument("--index-only", action="store_true", help="Только индексация")
    parser.add_argument("--query-only", action="store_true", help="Только поиск/LLM (коллекция готова)")
    parser.add_argument("--top-k", type=int, default=5, help="Сколько результатов выводить")
    parser.add_argument("--user-id", type=str, default=os.environ.get("USER_ID", "demo-user"), help="user_id для payload и фильтра")
    parser.add_argument("--cache-dir", type=str, default=os.environ.get("SPARSE_CACHE_DIR"), help="Локальный кеш sparse-модели")
    args = parser.parse_args()

    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    )

    user_id = args.user_id
    cache_dir = args.cache_dir

    if not args.query_only:
        index_res = await run_indexing(user_id=user_id, cache_dir=cache_dir)
        logger.info("Индексация завершена: %s", index_res)
        if index_res.get("status") != "success":
            return

    if not args.index_only:
        search_results = await run_sparse_search(top_k=args.top_k, user_id=user_id, cache_dir=cache_dir)
        await run_llm_answers(search_results, user_id=user_id, top_k=args.top_k)


if __name__ == "__main__":
    asyncio.run(main())
