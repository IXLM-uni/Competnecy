# -*- coding: utf-8 -*-
"""
Руководство к файлу llm_qdrant.py
=================================

Назначение:
    Вынесенный модуль RAG/Qdrant-инфраструктуры из llm_service.py.
    Содержит:
      - DTO для sparse/hybrid конфигурации
      - dense/sparse embedding клиенты
      - vector store интерфейс + реализацию на Qdrant
      - bulk ingest_and_index
      - Retriever

Контракт совместимости:
    Имена классов/функций и сигнатуры сохранены совместимыми с llm_service.py,
    чтобы use-cases работали без изменения импортов.

Техническое правило:
    Чтобы избежать циклических импортов, runtime-зависимости на llm_service.py
    (Snippet, RequestContext, Chunker, DocumentIngestor, FileRef, IndexMetadata)
    подтягиваются локально внутри методов/функций.
"""

from __future__ import annotations

import asyncio
import logging
import uuid
from pathlib import Path
from typing import TYPE_CHECKING, Any, Dict, List, Optional, Tuple

import httpx
from pydantic import BaseModel, Field
from typing_extensions import Literal

if TYPE_CHECKING:
    from AI.llm_service import (
        Chunker,
        DocumentChunk,
        DocumentIngestor,
        IndexMetadata,
        RequestContext,
        Snippet,
    )

logger = logging.getLogger(__name__)


class SparseVectorData(BaseModel):
    """Обёртка sparse-вектора (indices + values) для Qdrant.

    Валидирует, что indices и values одной длины и indices уникальны.
    Используется как единый формат обмена между SparseEmbeddingClient,
    QdrantVectorStore и Retriever.
    """

    indices: List[int] = Field(default_factory=list)
    values: List[float] = Field(default_factory=list)

    def model_post_init(self, __context: Any) -> None:
        if len(self.indices) != len(self.values):
            raise ValueError(
                f"SparseVectorData: длины indices ({len(self.indices)}) "
                f"и values ({len(self.values)}) не совпадают"
            )
        if len(self.indices) != len(set(self.indices)):
            raise ValueError("SparseVectorData: indices содержат дубликаты")

    @property
    def nnz(self) -> int:
        """Количество ненулевых элементов."""
        return len(self.indices)

    @property
    def is_empty(self) -> bool:
        return len(self.indices) == 0

    def to_qdrant(self) -> Any:
        """Конвертация в qdrant_client.models.SparseVector (lazy import)."""
        from qdrant_client.models import SparseVector

        return SparseVector(indices=self.indices, values=self.values)

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "SparseVectorData":
        """Создание из словаря {"indices": [...], "values": [...]}"""
        return cls(
            indices=data.get("indices", []),
            values=data.get("values", []),
        )


class QdrantCollectionConfig(BaseModel):
    """Конфигурация коллекции Qdrant для hybrid search (dense + sparse)."""

    # --- Dense vector ---
    dense_vector_name: str = "dense"
    dense_vector_size: int = 1024
    dense_distance: Literal["Cosine", "Dot", "Euclid", "Manhattan"] = "Cosine"
    dense_on_disk: bool = False

    # --- Sparse vector ---
    sparse_vector_name: str = "sparse"
    sparse_idf: bool = True
    sparse_on_disk: bool = False

    # --- Payload indexes (создаются при ensure_collection) ---
    payload_index_fields: List[str] = Field(
        default_factory=lambda: ["user_id", "document_name", "tags"],
    )

    # --- HNSW (опционально) ---
    hnsw_m: Optional[int] = None
    hnsw_ef_construct: Optional[int] = None
    hnsw_on_disk: bool = False

    # --- Оптимизация ---
    on_disk_payload: bool = False
    indexing_threshold: Optional[int] = None


class HybridSearchConfig(BaseModel):
    """Конфигурация гибридного поиска (dense + sparse → RRF/DBSF fusion)."""

    fusion_type: Literal["rrf", "dbsf"] = "rrf"
    rrf_k: Optional[int] = None
    dense_prefetch_limit_multiplier: int = 3
    sparse_prefetch_limit_multiplier: int = 3
    score_threshold: Optional[float] = None
    with_payload: bool = True
    with_vectors: bool = False


class EmbeddingClient:
    """Sentence-transformers embeddings (lazy load, sync → executor)."""

    def __init__(
        self, model_name: str = "sentence-transformers/all-MiniLM-L6-v2",
    ) -> None:
        self._model_name = model_name
        self._model: Any = None

    def _ensure_model(self) -> None:
        if self._model is None:
            from sentence_transformers import SentenceTransformer

            self._model = SentenceTransformer(self._model_name)

    async def embed_texts(
        self, texts: List[str], ctx: "RequestContext",
    ) -> List[List[float]]:
        logger.info(
            "ШАГ EMBED. Векторизация %d текстов: request_id=%s",
            len(texts), ctx.request_id,
        )
        loop = asyncio.get_running_loop()
        self._ensure_model()
        model = self._model

        def _sync() -> List[List[float]]:
            embeddings = model.encode(texts, convert_to_numpy=True)
            return [emb.tolist() for emb in embeddings]

        result = await loop.run_in_executor(None, _sync)
        logger.info("ШАГ EMBED. УСПЕХ: %d векторов", len(result))
        return result


class CloudRuEmbeddingClient(EmbeddingClient):
    """Embedding-клиент через OpenAI-совместимый API Cloud.ru."""

    def __init__(
        self,
        api_key: str,
        base_url: str = "https://foundation-models.api.cloud.ru/v1",
        model_name: str = "BAAI/bge-m3",
        batch_size: int = 64,
    ) -> None:
        self._api_key = api_key
        self._base_url = base_url.rstrip("/")
        self._model_name = model_name
        self._batch_size = batch_size
        self._model: Any = None

    def _ensure_model(self) -> None:
        pass

    async def embed_texts(
        self, texts: List[str], ctx: "RequestContext",
    ) -> List[List[float]]:
        logger.info(
            "ШАГ EMBED (Cloud.ru). Векторизация %d текстов: request_id=%s, model=%s",
            len(texts), ctx.request_id, self._model_name,
        )
        if not texts:
            return []

        all_embeddings: List[List[float]] = []
        url = f"{self._base_url}/embeddings"
        headers = {
            "Authorization": f"Bearer {self._api_key}",
            "Content-Type": "application/json",
        }

        async with httpx.AsyncClient(timeout=120.0) as client:
            for batch_start in range(0, len(texts), self._batch_size):
                batch = texts[batch_start : batch_start + self._batch_size]
                logger.info(
                    "ШАГ EMBED (Cloud.ru). Батч %d..%d из %d",
                    batch_start, batch_start + len(batch), len(texts),
                )
                payload = {
                    "model": self._model_name,
                    "input": batch,
                }
                try:
                    response = await client.post(
                        url, headers=headers, json=payload,
                    )
                    response.raise_for_status()
                    data = response.json()
                    sorted_items = sorted(data["data"], key=lambda x: x["index"])
                    for item in sorted_items:
                        all_embeddings.append(item["embedding"])
                except httpx.HTTPStatusError as exc:
                    logger.error(
                        "ШАГ EMBED (Cloud.ru). ОШИБКА HTTP %d: %s",
                        exc.response.status_code,
                        exc.response.text[:500],
                    )
                    raise
                except Exception as exc:
                    logger.error("ШАГ EMBED (Cloud.ru). ОШИБКА: %s", exc)
                    raise

        logger.info(
            "ШАГ EMBED (Cloud.ru). УСПЕХ: %d векторов", len(all_embeddings),
        )
        return all_embeddings


class SparseEmbeddingClient:
    """Sparse-embedding клиент через sentence-transformers SparseEncoder."""

    def __init__(
        self,
        model_name: str = "opensearch-project/opensearch-neural-sparse-encoding-multilingual-v1",
        cache_dir: Optional[str] = None,
    ) -> None:
        self._model_name = model_name
        self._cache_dir = cache_dir
        self._model: Any = None

    def _ensure_model(self) -> None:
        if self._model is None:
            logger.info(
                "ШАГ SPARSE INIT. Загружаем sparse-модель: %s (cache_dir=%s)",
                self._model_name,
                self._cache_dir,
            )
            from sentence_transformers.sparse_encoder import SparseEncoder

            self._model = SparseEncoder(
                self._model_name,
                cache_folder=self._cache_dir,
                local_files_only=True,
            )
            logger.info("ШАГ SPARSE INIT. УСПЕХ")

    @staticmethod
    def _parse_raw_embedding(emb: Any) -> SparseVectorData:
        """Единый парсер сырого embedding → SparseVectorData."""
        import torch

        if torch.is_tensor(emb):
            emb = emb.to("cpu")
            if emb.is_sparse or emb.is_sparse_csr:
                emb = emb.to_dense()

        if hasattr(emb, "to_dict") and callable(emb.to_dict):
            d = emb.to_dict()
            if isinstance(d, dict) and d:
                indices = [int(k) for k in d.keys()]
                values = [float(v) for v in d.values()]
                return SparseVectorData(indices=indices, values=values)

        if isinstance(emb, dict):
            indices = [int(k) for k in emb.keys()]
            values = [float(v) for v in emb.values()]
            return SparseVectorData(indices=indices, values=values)

        if hasattr(emb, "indices") and hasattr(emb, "values") and not torch.is_tensor(emb):
            raw_idx = emb.indices
            raw_val = emb.values
            if callable(raw_idx):
                raw_idx = raw_idx()
            if callable(raw_val):
                raw_val = raw_val()
            if raw_idx is not None and raw_val is not None:
                indices = list(map(int, raw_idx))
                values = [float(v) for v in raw_val]
                return SparseVectorData(indices=indices, values=values)

        if torch.is_tensor(emb):
            flat = emb.view(-1) if emb.dim() > 1 else emb
            nz_tuple = flat.nonzero(as_tuple=True)
            idx_tensor = nz_tuple[0]
            indices = idx_tensor.tolist()
            values = [float(flat[i]) for i in indices]
            logger.debug(
                "ШАГ SPARSE PARSE (torch). shape=%s, nnz=%d",
                list(emb.shape), len(indices),
            )
            return SparseVectorData(indices=indices, values=values)

        if hasattr(emb, "nonzero"):
            nz = emb.nonzero()
            if len(nz) == 2:
                indices = nz[1].tolist() if hasattr(nz[1], "tolist") else list(nz[1])
                values = [float(emb[0, idx]) for idx in indices]
            elif len(nz) == 1:
                indices = nz[0].tolist() if hasattr(nz[0], "tolist") else list(nz[0])
                values = [float(emb[idx]) for idx in indices]
            else:
                indices, values = [], []
            return SparseVectorData(indices=indices, values=values)

        logger.warning(
            "ШАГ SPARSE PARSE. Не удалось распарсить тип %s — пустой вектор",
            type(emb).__name__,
        )
        return SparseVectorData(indices=[], values=[])

    async def embed_documents(
        self, texts: List[str], ctx: "RequestContext",
    ) -> List[SparseVectorData]:
        logger.info(
            "ШАГ SPARSE EMBED (doc). Sparse-векторизация %d текстов: request_id=%s",
            len(texts), ctx.request_id,
        )
        if not texts:
            return []

        loop = asyncio.get_running_loop()
        self._ensure_model()
        model = self._model
        parse = self._parse_raw_embedding

        def _sync() -> List[SparseVectorData]:
            embs = model.encode_document(texts, convert_to_sparse_tensor=False)
            return [parse(emb) for emb in embs]

        result = await loop.run_in_executor(None, _sync)
        logger.info(
            "ШАГ SPARSE EMBED (doc). УСПЕХ: %d sparse-векторов (nnz: %s)",
            len(result),
            [sv.nnz for sv in result[:5]],
        )
        return result

    async def embed_query(
        self, text: str, ctx: "RequestContext",
    ) -> SparseVectorData:
        logger.info(
            "ШАГ SPARSE EMBED (query). Sparse-векторизация запроса: request_id=%s",
            ctx.request_id,
        )
        loop = asyncio.get_running_loop()
        self._ensure_model()
        model = self._model
        parse = self._parse_raw_embedding

        def _sync() -> SparseVectorData:
            emb = model.encode_query([text], convert_to_sparse_tensor=False)[0]
            return parse(emb)

        result = await loop.run_in_executor(None, _sync)
        logger.info(
            "ШАГ SPARSE EMBED (query). УСПЕХ: nnz=%d",
            result.nnz,
        )
        return result

    async def embed_documents_dict(
        self, texts: List[str], ctx: "RequestContext",
    ) -> List[Dict[str, Any]]:
        results = await self.embed_documents(texts, ctx)
        return [{"indices": sv.indices, "values": sv.values} for sv in results]

    async def embed_query_dict(
        self, text: str, ctx: "RequestContext",
    ) -> Dict[str, Any]:
        result = await self.embed_query(text, ctx)
        return {"indices": result.indices, "values": result.values}


class VectorStore:
    """Интерфейс векторного хранилища (dense + sparse + metadata + фильтры)."""

    async def upsert(
        self,
        collection: str,
        ids: List[str],
        dense_vectors: List[List[float]],
        payloads: List[Dict[str, Any]],
        ctx: "RequestContext",
        sparse_vectors: Optional[List["SparseVectorData"]] = None,
    ) -> None:
        raise NotImplementedError

    async def search(
        self,
        collection: str,
        query_dense: List[float],
        top_k: int,
        ctx: "RequestContext",
        query_sparse: Optional["SparseVectorData"] = None,
        filters: Optional[Dict[str, Any]] = None,
        search_config: Optional["HybridSearchConfig"] = None,
    ) -> List["Snippet"]:
        raise NotImplementedError


class QdrantVectorStore(VectorStore):
    """Реализация VectorStore на базе Qdrant (async)."""

    DEFAULT_COLLECTION_CONFIG = QdrantCollectionConfig()
    DEFAULT_SEARCH_CONFIG = HybridSearchConfig()

    def __init__(
        self,
        host: str = "localhost",
        port: int = 6334,
        https: bool = False,
        collection_config: Optional[QdrantCollectionConfig] = None,
        search_config: Optional[HybridSearchConfig] = None,
    ) -> None:
        from qdrant_client import AsyncQdrantClient

        self._client = AsyncQdrantClient(host=host, port=port, https=https)
        self._ensured_collections: set = set()
        self._config = collection_config or self.DEFAULT_COLLECTION_CONFIG
        self._search_config = search_config or self.DEFAULT_SEARCH_CONFIG

    async def _ensure_collection(self, collection: str, dense_dim: int) -> None:
        if collection in self._ensured_collections:
            return

        logger.info(
            "ШАГ QDRANT ENSURE 1. Проверяем существование коллекции '%s'",
            collection,
        )

        exists = await self._client.collection_exists(
            collection_name=collection,
        )

        if exists:
            logger.info(
                "ШАГ QDRANT ENSURE 1. Коллекция '%s' уже существует — пропускаем",
                collection,
            )
            self._ensured_collections.add(collection)
            return

        from qdrant_client.models import (
            Distance,
            HnswConfigDiff,
            Modifier,
            OptimizersConfigDiff,
            SparseIndexParams,
            SparseVectorParams,
            VectorParams,
        )

        cfg = self._config

        distance_map = {
            "Cosine": Distance.COSINE,
            "Dot": Distance.DOT,
            "Euclid": Distance.EUCLID,
            "Manhattan": Distance.MANHATTAN,
        }
        distance = distance_map.get(cfg.dense_distance, Distance.COSINE)

        actual_dense_dim = dense_dim or cfg.dense_vector_size

        logger.info(
            "ШАГ QDRANT ENSURE 2. Создаём коллекцию '%s': dense_name='%s' dim=%d distance=%s on_disk=%s, sparse_name='%s' idf=%s on_disk=%s",
            collection,
            cfg.dense_vector_name,
            actual_dense_dim,
            cfg.dense_distance,
            cfg.dense_on_disk,
            cfg.sparse_vector_name,
            cfg.sparse_idf,
            cfg.sparse_on_disk,
        )

        dense_params = VectorParams(
            size=actual_dense_dim,
            distance=distance,
            on_disk=cfg.dense_on_disk,
        )

        sparse_params = SparseVectorParams(
            modifier=Modifier.IDF if cfg.sparse_idf else None,
            index=SparseIndexParams(on_disk=cfg.sparse_on_disk),
        )

        hnsw_config = None
        if cfg.hnsw_m or cfg.hnsw_ef_construct or cfg.hnsw_on_disk:
            hnsw_config = HnswConfigDiff(
                m=cfg.hnsw_m,
                ef_construct=cfg.hnsw_ef_construct,
                on_disk=cfg.hnsw_on_disk or None,
            )

        optimizers_config = None
        if cfg.indexing_threshold is not None:
            optimizers_config = OptimizersConfigDiff(
                indexing_threshold=cfg.indexing_threshold,
            )

        await self._client.create_collection(
            collection_name=collection,
            vectors_config={
                cfg.dense_vector_name: dense_params,
            },
            sparse_vectors_config={
                cfg.sparse_vector_name: sparse_params,
            },
            hnsw_config=hnsw_config,
            optimizers_config=optimizers_config,
            on_disk_payload=cfg.on_disk_payload,
        )
        logger.info(
            "ШАГ QDRANT ENSURE 2. Коллекция '%s' создана — УСПЕХ", collection,
        )

        await self._ensure_payload_indexes(collection, cfg.payload_index_fields)

        self._ensured_collections.add(collection)
        logger.info(
            "ШАГ QDRANT ENSURE 3. Коллекция '%s' полностью готова (dense + sparse + payload indexes)",
            collection,
        )

    async def _ensure_payload_indexes(
        self, collection: str, fields: List[str],
    ) -> None:
        if not fields:
            return

        logger.info(
            "ШАГ QDRANT INDEXES. Создаём payload indexes для '%s': %s",
            collection,
            fields,
        )

        for field_name in fields:
            try:
                if field_name == "page":
                    from qdrant_client.models import (
                        IntegerIndexParams,
                        IntegerIndexType,
                    )

                    await self._client.create_payload_index(
                        collection_name=collection,
                        field_name=field_name,
                        field_schema=IntegerIndexParams(
                            type=IntegerIndexType.INTEGER,
                            lookup=True,
                            range=True,
                        ),
                    )
                else:
                    await self._client.create_payload_index(
                        collection_name=collection,
                        field_name=field_name,
                        field_schema="keyword",
                    )
                logger.info(
                    "ШАГ QDRANT INDEXES. Индекс '%s' создан — УСПЕХ",
                    field_name,
                )
            except Exception as exc:
                logger.warning(
                    "ШАГ QDRANT INDEXES. Индекс '%s' — ПРЕДУПРЕЖДЕНИЕ: %s (возможно, уже существует)",
                    field_name,
                    exc,
                )

    async def delete_collection(self, collection: str) -> bool:
        logger.info("ШАГ QDRANT DELETE. Удаляем коллекцию '%s'", collection)
        try:
            result = await self._client.delete_collection(
                collection_name=collection,
            )
            self._ensured_collections.discard(collection)
            logger.info(
                "ШАГ QDRANT DELETE. Коллекция '%s' удалена — УСПЕХ", collection,
            )
            return bool(result)
        except Exception as exc:
            logger.error(
                "ШАГ QDRANT DELETE. ОШИБКА удаления '%s': %s", collection, exc,
            )
            return False

    async def get_collection_info(self, collection: str) -> Optional[Dict[str, Any]]:
        logger.info("ШАГ QDRANT INFO. Запрашиваем информацию о '%s'", collection)
        try:
            info = await self._client.get_collection(
                collection_name=collection,
            )
            result = {
                "status": str(info.status),
                "points_count": info.points_count,
                "indexed_vectors_count": info.indexed_vectors_count,
                "config": str(info.config),
            }
            logger.info(
                "ШАГ QDRANT INFO. Коллекция '%s': status=%s, points=%s",
                collection,
                result["status"],
                result["points_count"],
            )
            return result
        except Exception as exc:
            logger.error(
                "ШАГ QDRANT INFO. ОШИБКА для '%s': %s", collection, exc,
            )
            return None

    async def count_points(
        self, collection: str, filters: Optional[Dict[str, Any]] = None,
    ) -> int:
        logger.info(
            "ШАГ QDRANT COUNT. Считаем точки в '%s', has_filters=%s",
            collection,
            bool(filters),
        )
        try:
            qdrant_filter = self._build_qdrant_filter(filters)
            result = await self._client.count(
                collection_name=collection,
                count_filter=qdrant_filter,
                exact=True,
            )
            count = result.count
            logger.info(
                "ШАГ QDRANT COUNT. Коллекция '%s': %d точек", collection, count,
            )
            return count
        except Exception as exc:
            logger.error(
                "ШАГ QDRANT COUNT. ОШИБКА для '%s': %s", collection, exc,
            )
            return 0

    @staticmethod
    def _build_qdrant_filter(filters: Optional[Dict[str, Any]]) -> Any:
        if not filters:
            return None

        from qdrant_client.models import (
            FieldCondition,
            Filter,
            MatchAny,
            MatchValue,
        )

        must_conditions: List[Any] = []
        for key, value in filters.items():
            if isinstance(value, list):
                must_conditions.append(
                    FieldCondition(key=key, match=MatchAny(any=value)),
                )
            else:
                must_conditions.append(
                    FieldCondition(key=key, match=MatchValue(value=value)),
                )

        if not must_conditions:
            return None

        return Filter(must=must_conditions)

    async def upsert(
        self,
        collection: str,
        ids: List[str],
        dense_vectors: List[List[float]],
        payloads: List[Dict[str, Any]],
        ctx: "RequestContext",
        sparse_vectors: Optional[List["SparseVectorData"]] = None,
    ) -> None:
        logger.info(
            "ШАГ VECTOR UPSERT 1. collection=%s, count=%d, has_sparse=%s: request_id=%s",
            collection,
            len(ids),
            bool(sparse_vectors),
            ctx.request_id,
        )
        if not dense_vectors:
            logger.warning("ШАГ VECTOR UPSERT 1. Нет dense_vectors — пропускаем")
            return

        await self._ensure_collection(collection, len(dense_vectors[0]))

        from qdrant_client.models import PointStruct

        cfg = self._config
        points: List[Any] = []

        for i, (pid, dense_vec, payload) in enumerate(
            zip(ids, dense_vectors, payloads),
        ):
            vector_data: Dict[str, Any] = {
                cfg.dense_vector_name: dense_vec,
            }

            if sparse_vectors and i < len(sparse_vectors):
                sv = sparse_vectors[i]
                if isinstance(sv, dict):
                    sv = SparseVectorData.from_dict(sv)
                if isinstance(sv, SparseVectorData) and not sv.is_empty:
                    vector_data[cfg.sparse_vector_name] = sv.to_qdrant()

            points.append(PointStruct(
                id=pid,
                vector=vector_data,
                payload=payload,
            ))

        logger.info(
            "ШАГ VECTOR UPSERT 2. Отправляем %d точек в Qdrant — ОТПРАВЛЯЕМ",
            len(points),
        )
        await self._client.upsert(
            collection_name=collection,
            points=points,
            wait=True,
        )
        logger.info(
            "ШАГ VECTOR UPSERT 2. УСПЕХ: %d точек записано в '%s'",
            len(points),
            collection,
        )

    async def search(
        self,
        collection: str,
        query_dense: List[float],
        top_k: int,
        ctx: "RequestContext",
        query_sparse: Optional["SparseVectorData"] = None,
        filters: Optional[Dict[str, Any]] = None,
        search_config: Optional["HybridSearchConfig"] = None,
    ) -> List["Snippet"]:
        scfg = search_config or self._search_config
        cfg = self._config

        if isinstance(query_sparse, dict):
            query_sparse = SparseVectorData.from_dict(query_sparse)

        has_sparse = (
            isinstance(query_sparse, SparseVectorData)
            and not query_sparse.is_empty
        )

        logger.info(
            "ШАГ VECTOR SEARCH 1. collection=%s, top_k=%d, has_sparse=%s (nnz=%d), has_filters=%s, fusion=%s: request_id=%s",
            collection,
            top_k,
            has_sparse,
            query_sparse.nnz if has_sparse else 0,
            bool(filters),
            scfg.fusion_type,
            ctx.request_id,
        )

        qdrant_filter = self._build_qdrant_filter(filters)

        from qdrant_client.models import (
            Fusion,
            FusionQuery,
            Prefetch,
        )

        try:
            if has_sparse:
                dense_limit = top_k * scfg.dense_prefetch_limit_multiplier
                sparse_limit = top_k * scfg.sparse_prefetch_limit_multiplier

                prefetch_list = [
                    Prefetch(
                        query=query_dense,
                        using=cfg.dense_vector_name,
                        limit=dense_limit,
                        filter=qdrant_filter,
                    ),
                    Prefetch(
                        query=query_sparse.to_qdrant(),
                        using=cfg.sparse_vector_name,
                        limit=sparse_limit,
                        filter=qdrant_filter,
                    ),
                ]

                if scfg.fusion_type == "dbsf":
                    fusion_query = FusionQuery(fusion=Fusion.DBSF)
                else:
                    fusion_query = FusionQuery(fusion=Fusion.RRF)

                logger.info(
                    "ШАГ VECTOR SEARCH 2. Hybrid query: dense_limit=%d, sparse_limit=%d, fusion=%s — ОТПРАВЛЯЕМ",
                    dense_limit,
                    sparse_limit,
                    scfg.fusion_type,
                )

                res = await self._client.query_points(
                    collection_name=collection,
                    prefetch=prefetch_list,
                    query=fusion_query,
                    limit=top_k,
                    score_threshold=scfg.score_threshold,
                    with_payload=scfg.with_payload,
                    with_vectors=scfg.with_vectors,
                )
            else:
                logger.info(
                    "ШАГ VECTOR SEARCH 2. Dense-only query: top_k=%d — ОТПРАВЛЯЕМ",
                    top_k,
                )
                res = await self._client.query_points(
                    collection_name=collection,
                    query=query_dense,
                    using=cfg.dense_vector_name,
                    limit=top_k,
                    score_threshold=scfg.score_threshold,
                    query_filter=qdrant_filter,
                    with_payload=scfg.with_payload,
                    with_vectors=scfg.with_vectors,
                )

            points = res.points if hasattr(res, "points") else res
        except Exception as exc:
            logger.error(
                "ШАГ VECTOR SEARCH 2. ОШИБКА query_points: %s", exc,
            )
            return []

        from AI.llm_service import Snippet  # локально: защита от циклического импорта

        snippets: List[Snippet] = []
        for point in points:
            payload = point.payload or {}
            snippets.append(Snippet(
                text=str(payload.get("text", "")),
                source_id=str(payload.get("source_id", "")),
                score=getattr(point, "score", 0.0),
                metadata=payload,
            ))
        logger.info(
            "ШАГ VECTOR SEARCH 3. УСПЕХ: %d результатов из '%s'",
            len(snippets),
            collection,
        )
        return snippets


async def ingest_and_index(
    file_paths: List[str],
    embedding_client: EmbeddingClient,
    vector_store: VectorStore,
    collection: str,
    chunker: Optional["Chunker"] = None,
    ingestor: Optional["DocumentIngestor"] = None,
    sparse_client: Optional["SparseEmbeddingClient"] = None,
    index_metadata: Optional["IndexMetadata"] = None,
    batch_size: int = 64,
) -> List["DocumentChunk"]:
    """Bulk-индексация: файлы → ingest → chunk → dense+sparse embed → upsert."""

    from AI.llm_service import (  # локально: защита от циклического импорта
        Chunker,
        DocumentIngestor,
        FileRef,
        IndexMetadata,
        RequestContext,
    )

    _chunker = chunker or Chunker()
    _ingestor = ingestor or DocumentIngestor(_chunker)
    ctx = RequestContext(request_id=f"bulk-index-{uuid.uuid4().hex[:8]}")

    _meta = index_metadata or IndexMetadata()

    logger.info(
        "ШАГ INDEX 1. Начинаем bulk-индексацию: request_id=%s, files=%d, collection=%s, document_name=%s, user_id=%s, has_sparse=%s",
        ctx.request_id,
        len(file_paths),
        collection,
        _meta.document_name,
        _meta.user_id,
        bool(sparse_client),
    )

    all_chunks: List[DocumentChunk] = []
    for fpath in file_paths:
        p = Path(fpath)
        if not p.exists():
            logger.warning(
                "ШАГ INDEX 1. Файл не найден, пропускаем: %s", fpath,
            )
            continue

        ext = p.suffix.lower()
        mime_map = {
            ".pdf": "application/pdf",
            ".docx": "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
            ".doc": "application/msword",
            ".html": "text/html",
            ".htm": "text/html",
            ".txt": "text/plain",
            ".md": "text/markdown",
            ".xlsx": "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        }
        file_ref = FileRef(
            path=str(p),
            mime_type=mime_map.get(ext, "text/plain"),
            original_name=p.name,
            size_bytes=p.stat().st_size,
        )

        try:
            chunks = await _ingestor.ingest(file_ref, ctx)
            all_chunks.extend(chunks)
            logger.info(
                "ШАГ INDEX 1. Файл %s → %d чанков", p.name, len(chunks),
            )
        except Exception as exc:
            logger.error(
                "ШАГ INDEX 1. ОШИБКА инжеста %s: %s", p.name, exc,
            )

    if not all_chunks:
        logger.warning("ШАГ INDEX 1. Нет чанков для индексации — выход")
        return []

    logger.info(
        "ШАГ INDEX 2. Всего чанков для векторизации: %d", len(all_chunks),
    )

    meta_payload_base: Dict[str, Any] = {}
    if _meta.document_name:
        meta_payload_base["document_name"] = _meta.document_name
    if _meta.user_id:
        meta_payload_base["user_id"] = _meta.user_id
    if _meta.tags:
        meta_payload_base["tags"] = _meta.tags
    if _meta.custom_data:
        for k, v in _meta.custom_data.items():
            meta_payload_base[f"custom_data.{k}"] = v

    for batch_start in range(0, len(all_chunks), batch_size):
        batch = all_chunks[batch_start : batch_start + batch_size]
        texts = [c.text for c in batch]
        ids = [c.id for c in batch]
        payloads = [
            {
                "text": c.text,
                "source_id": c.source_id,
                "page": c.page,
                "offset": c.offset,
                "checksum": c.checksum,
                **meta_payload_base,
                **c.metadata,
            }
            for c in batch
        ]

        logger.info(
            "ШАГ INDEX 2a. Dense embed батч %d..%d из %d",
            batch_start,
            batch_start + len(batch),
            len(all_chunks),
        )
        try:
            dense_vectors = await embedding_client.embed_texts(texts, ctx)
        except Exception as exc:
            logger.error(
                "ШАГ INDEX 2a. ОШИБКА dense embed батча %d: %s",
                batch_start,
                exc,
            )
            continue

        sparse_vectors: Optional[List[SparseVectorData]] = None
        if sparse_client:
            logger.info(
                "ШАГ INDEX 2b. Sparse embed батч %d..%d из %d",
                batch_start,
                batch_start + len(batch),
                len(all_chunks),
            )
            try:
                sparse_vectors = await sparse_client.embed_documents(texts, ctx)
            except Exception as exc:
                logger.error(
                    "ШАГ INDEX 2b. ОШИБКА sparse embed батча %d: %s",
                    batch_start,
                    exc,
                )
                sparse_vectors = None

        logger.info(
            "ШАГ INDEX 3. Upsert батч %d..%d в collection=%s",
            batch_start,
            batch_start + len(batch),
            collection,
        )
        try:
            await vector_store.upsert(
                collection,
                ids,
                dense_vectors,
                payloads,
                ctx,
                sparse_vectors=sparse_vectors,
            )
        except Exception as exc:
            logger.error(
                "ШАГ INDEX 3. ОШИБКА upsert батча %d: %s",
                batch_start,
                exc,
            )
            continue

    logger.info(
        "ШАГ INDEX FINISH. Bulk-индексация завершена: total_chunks=%d, collection=%s, document_name=%s, user_id=%s",
        len(all_chunks),
        collection,
        _meta.document_name,
        _meta.user_id,
    )
    return all_chunks


class Retriever:
    """RAG-ретривер: dense embed + sparse embed → hybrid search в Qdrant."""

    def __init__(
        self,
        embedding_client: EmbeddingClient,
        vector_store: VectorStore,
        collection: str,
        sparse_client: Optional[SparseEmbeddingClient] = None,
    ) -> None:
        self._emb = embedding_client
        self._vector = vector_store
        self._collection = collection
        self._sparse = sparse_client

    async def retrieve(
        self, query: str, ctx: "RequestContext", top_k: int = 6,
        filters: Optional[Dict[str, Any]] = None,
    ) -> List["Snippet"]:
        logger.info(
            "ШАГ RAG RETRIEVE. query_len=%d, top_k=%d, has_sparse=%s, has_filters=%s: request_id=%s",
            len(query), top_k, bool(self._sparse), bool(filters), ctx.request_id,
        )
        if not query.strip():
            return []

        try:
            dense_vectors = await self._emb.embed_texts([query], ctx)
            query_dense = dense_vectors[0]
        except Exception as exc:
            logger.error("ШАГ RAG RETRIEVE. Dense embed ОШИБКА: %s", exc)
            return []

        query_sparse: Optional[SparseVectorData] = None
        if self._sparse:
            try:
                query_sparse = await self._sparse.embed_query(query, ctx)
            except Exception as exc:
                logger.warning(
                    "ШАГ RAG RETRIEVE. Sparse embed ОШИБКА: %s — продолжаем с только dense",
                    exc,
                )
                query_sparse = None

        try:
            snippets = await self._vector.search(
                self._collection,
                query_dense=query_dense,
                top_k=top_k,
                ctx=ctx,
                query_sparse=query_sparse,
                filters=filters,
            )
        except Exception as exc:
            logger.error("ШАГ RAG RETRIEVE. Search ОШИБКА: %s", exc)
            return []

        logger.info("ШАГ RAG RETRIEVE. УСПЕХ: %d сниппетов", len(snippets))
        return snippets

    async def retrieve_multi(
        self, queries: List[str], ctx: "RequestContext", top_k: int = 6,
        filters: Optional[Dict[str, Any]] = None,
    ) -> List["Snippet"]:
        tasks = [
            self.retrieve(q, ctx, top_k=top_k, filters=filters)
            for q in queries
        ]
        results: List[List[Snippet]] = await asyncio.gather(*tasks)

        seen: set[Tuple[str, str]] = set()
        merged: List[Snippet] = []
        for snippet_list in results:
            for s in snippet_list:
                key = (s.source_id, s.text[:100])
                if key not in seen:
                    seen.add(key)
                    merged.append(s)

        merged.sort(key=lambda s: s.score, reverse=True)
        return merged[:top_k]
