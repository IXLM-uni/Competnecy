"""
Руководство к файлу rag_dense.py
================================

Назначение:
    Построить индекс Qdrant по документу «Методология.docx» для:
    1) Dense-only режима (только плотные вектора).
    2) Hybrid режима (dense + sparse, RRF fusion).
    Выполнить тестовые CTA-запросы для проверки поиска.

Этапы (логируются пошагово):
    ШАГ 1. Загрузка .env, проверка документа и параметров.
    ШАГ 2. Индексация: ingest -> chunk -> dense embed (+ опц. sparse) -> upsert.
    ШАГ 3. Поиск: dense или hybrid (по выбору), вывод top_k результатов.

Переменные окружения (Global_services/.env):
    CLOUDRU_API_KEY       — ключ для Cloud.ru Embeddings.
    CLOUDRU_BASE_URL      — base URL Embeddings/LLM (опц., по умолчанию https://foundation-models.api.cloud.ru/v1).
    CLOUDRU_EMBED_MODEL   — модель dense-эмбеддингов (по умолчанию Qwen/Qwen3-Embedding-0.6B).
    SPARSE_EMBED_MODEL    — модель sparse-векторизации (для hybrid, опц.).
    QDRANT_HOST, QDRANT_PORT — подключение к Qdrant (порт по умолчанию 6333).

Запуск (команды выполнять вручную из корня проекта!):
    # Полный цикл hybrid: индексация dense+sparce и поиск
    python -m AI.scripts.rag_dense --mode hybrid

    # Только dense: индексация + поиск
    python -m AI.scripts.rag_dense --mode dense

    # Только индексация (hybrid)
    python -m AI.scripts.rag_dense --mode hybrid --index-only

    # Только поиск (коллекция уже есть)
    python -m AI.scripts.rag_dense --mode hybrid --query-only

Примечания:
    - Dense режим создаёт коллекцию без sparse-векторов.
    - Hybrid режим создаёт коллекцию с именованными dense + sparse векторами и использует RRF fusion.
    - Логирование следует формату «ШАГ N. ... — ОТПРАВЛЯЕМ/УСПЕХ/ОШИБКА».
"""

from __future__ import annotations

import argparse
import asyncio
import logging
import os
import time
from typing import Any, Dict, List, Optional

# Явно выключаем CUDA: все операции на CPU (чтобы избежать OOM на GPU)
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
COLLECTION_NAME_DENSE = "methodology_dense_cta"
COLLECTION_NAME_HYBRID = "methodology_hybrid_cta"
QDRANT_TIMEOUT = 60.0
TEST_QUERIES = [
    "Что в тексте говорится про CTA",
    "какие CTA упоминаются и где они применяются",
    "как автор предлагает формировать call-to-action",
]


def _load_env() -> str:
    """Загрузка .env из корня проекта и возврат пути."""

    env_path = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..", ".env"))
    load_dotenv(env_path)
    logger.info("ШАГ 1. Загружаем .env из %s", env_path)
    return env_path


async def run_indexing(mode: str) -> Dict[str, Any]:
    """Индексация документа: dense-only или hybrid (dense + sparse)."""

    from AI.llm_service import (
        CloudRuEmbeddingClient,
        IndexMetadata,
        QdrantVectorStore,
        SparseEmbeddingClient,
        ingest_and_index,
    )

    _load_env()

    api_key = os.environ.get("CLOUDRU_API_KEY")
    if not api_key:
        logger.error("ШАГ 1. ОШИБКА: CLOUDRU_API_KEY не задан")
        return {"status": "error", "message": "CLOUDRU_API_KEY не задан"}

    qdrant_host = os.environ.get("QDRANT_HOST", "localhost")
    qdrant_port = int(os.environ.get("QDRANT_PORT", "6333"))
    dense_model = os.environ.get("CLOUDRU_EMBED_MODEL", "Qwen/Qwen3-Embedding-0.6B")
    sparse_model = os.environ.get(
        "SPARSE_EMBED_MODEL",
        "opensearch-project/opensearch-neural-sparse-encoding-multilingual-v1",
    )

    if not os.path.isfile(DOCUMENT_PATH):
        logger.error("ШАГ 1. ОШИБКА: документ не найден: %s", DOCUMENT_PATH)
        return {"status": "error", "message": f"Файл не найден: {DOCUMENT_PATH}"}

    logger.info(
        "ШАГ 1. УСПЕХ: qdrant=%s:%d, dense_model=%s, sparse_model=%s, document=%s",
        qdrant_host,
        qdrant_port,
        dense_model,
        sparse_model if mode == "hybrid" else "(skip)",
        DOCUMENT_NAME,
    )

    collection = COLLECTION_NAME_HYBRID if mode == "hybrid" else COLLECTION_NAME_DENSE

    embedding_client = CloudRuEmbeddingClient(
        api_key=api_key,
        base_url=os.environ.get("CLOUDRU_BASE_URL", "https://foundation-models.api.cloud.ru/v1"),
        model_name=dense_model,
    )

    sparse_client = None
    if mode == "hybrid":
        sparse_client = SparseEmbeddingClient(model_name=sparse_model)

    vector_store = QdrantVectorStore(host=qdrant_host, port=qdrant_port, https=False)

    index_metadata = IndexMetadata(
        document_name=DOCUMENT_NAME,
        tags=["cta", "methodology"],
    )

    logger.info(
        "ШАГ 2. Запускаем индексацию: mode=%s, document=%s, collection=%s",
        mode,
        DOCUMENT_NAME,
        collection,
    )

    started = time.time()
    chunks = await ingest_and_index(
        file_paths=[DOCUMENT_PATH],
        embedding_client=embedding_client,
        vector_store=vector_store,
        collection=collection,
        sparse_client=sparse_client,
        index_metadata=index_metadata,
        batch_size=32,
    )
    elapsed = round(time.time() - started, 2)

    report = {
        "status": "success",
        "collection": collection,
        "chunks": len(chunks),
        "elapsed_sec": elapsed,
    }
    logger.info("ШАГ 2. УСПЕХ: индексация завершена %s", report)
    return report


async def run_search(mode: str, top_k: int = 5) -> None:
    """Поиск по CTA-запросам: dense-only или hybrid (dense + sparse)."""

    from AI.llm_service import (
        CloudRuEmbeddingClient,
        QdrantVectorStore,
        RequestContext,
        SparseEmbeddingClient,
    )

    _load_env()

    qdrant_host = os.environ.get("QDRANT_HOST", "localhost")
    qdrant_port = int(os.environ.get("QDRANT_PORT", "6333"))
    dense_model = os.environ.get("CLOUDRU_EMBED_MODEL", "Qwen/Qwen3-Embedding-0.6B")
    sparse_model = os.environ.get(
        "SPARSE_EMBED_MODEL",
        "opensearch-project/opensearch-neural-sparse-encoding-multilingual-v1",
    )

    collection = COLLECTION_NAME_HYBRID if mode == "hybrid" else COLLECTION_NAME_DENSE

    embedding_client = CloudRuEmbeddingClient(
        api_key=os.environ.get("CLOUDRU_API_KEY", ""),
        base_url=os.environ.get("CLOUDRU_BASE_URL", "https://foundation-models.api.cloud.ru/v1"),
        model_name=dense_model,
    )

    sparse_client: Optional[Any] = None
    if mode == "hybrid":
        sparse_client = SparseEmbeddingClient(model_name=sparse_model)

    vector_store = QdrantVectorStore(host=qdrant_host, port=qdrant_port, https=False)

    ctx = RequestContext(request_id=f"cta-search-{mode}-{int(time.time())}")

    for i, query in enumerate(TEST_QUERIES, 1):
        logger.info("\n" + "=" * 80)
        logger.info("ШАГ 3.%d. Запрос: %s", i, query)

        try:
            dense_embeds = await embedding_client.embed_texts([query], ctx)
            if not dense_embeds:
                raise RuntimeError("Пустой ответ от CloudRuEmbeddingClient.embed_texts")
            q_dense = dense_embeds[0]
        except Exception as exc:
            logger.error("ШАГ 3.%d. ОШИБКА dense embed запроса: %s", i, exc)
            continue

        q_sparse = None
        if sparse_client is not None:
            try:
                q_sparse = await sparse_client.embed_query(query, ctx)
            except Exception as exc:
                logger.error("ШАГ 3.%d. ОШИБКА sparse embed запроса: %s", i, exc)
                q_sparse = None

        try:
            snippets = await vector_store.search(
                collection=collection,
                query_dense=q_dense,
                query_sparse=q_sparse,
                top_k=top_k,
                ctx=ctx,
                filters=None,
                search_config=None,
            )
        except Exception as exc:
            logger.error("ШАГ 3.%d. ОШИБКА поиска: %s", i, exc)
            continue

        logger.info("ШАГ 3.%d. Найдено %d точек", i, len(snippets))
        print("\n❓ Запрос:", query)
        for j, sn in enumerate(snippets, 1):
            text = sn.text.replace("\n", " ")[:200]
            page = sn.metadata.get("page") if isinstance(sn.metadata, dict) else None
            print(f"[{j}] score={sn.score:.4f} page={page} | {text}...")


async def main() -> None:
    parser = argparse.ArgumentParser(description="CTA dense/hybrid RAG скрипт")
    parser.add_argument("--mode", choices=["dense", "hybrid"], default="hybrid", help="Режим индекса/поиска")
    parser.add_argument("--index-only", action="store_true", help="Только индексация")
    parser.add_argument("--query-only", action="store_true", help="Только поиск")
    parser.add_argument("--top-k", type=int, default=5, help="Сколько результатов выводить")
    args = parser.parse_args()

    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    )

    mode = args.mode
    logger.info("Старт rag_dense: mode=%s, index_only=%s, query_only=%s", mode, args.index_only, args.query_only)

    if not args.query_only:
        index_res = await run_indexing(mode)
        logger.info("Индексация завершена: %s", index_res)
        if index_res.get("status") != "success":
            return

    if not args.index_only:
        await run_search(mode=mode, top_k=args.top_k)


async def _entrypoint() -> None:
    await main()


if __name__ == "__main__":
    asyncio.run(_entrypoint())
