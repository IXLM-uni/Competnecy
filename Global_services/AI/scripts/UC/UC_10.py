# -*- coding: utf-8 -*-
"""
Руководство к файлу UC_10.py
============================

Назначение:
    Реализация UC-10: Классификация документов через Qdrant (Payload-based k-NN).
    1. Загрузка и инжест документа — DocumentIngestor
    2. Генерация эмбеддинга — CloudRuEmbeddingClient
    3. Поиск ближайших соседей с категориями — QdrantVectorStore.search()
    4. Голосование по категориям (k-NN majority voting)
    5. Сохранение документа с категорией (вывод результата)
    6. Демонстрация фильтрации по категориям

    Use Case: UC-10 из LLM_SERVICE.md
    Actor: Администратор / Автоматизированный процесс
    Цель: Автоматическое определение категории через поиск похожих в Qdrant.

Архитектура (6 шагов UC-10):
    ШАГ 1. Загрузка документа — DocumentIngestor.ingest()
    ШАГ 2. Генерация эмбеддинга — CloudRuEmbeddingClient.embed_texts()
    ШАГ 3. Поиск ближайших соседей — Retriever.retrieve()
    ШАГ 4. Голосование по категориям — majority voting
    ШАГ 5. Результат классификации
    ШАГ 6. Демонстрация фильтрации

Используемые функции из llm_service.py:
    - load_env_and_validate, create_rag_clients_from_env
    - DocumentIngestor, FileRef, RequestContext

Использование:
    python -m AI.scripts.UC.UC_10 [путь_к_документу] [--k 5]

Зависимости:
    - llm_service.py, python-dotenv
"""

from __future__ import annotations

import asyncio
import json
import logging
import sys
from collections import Counter
from pathlib import Path
from typing import Any, Dict, List, Optional

# ---------- Константы ----------
SCRIPT_DIR = Path(__file__).parent.absolute()
AI_DIR = SCRIPT_DIR.parent.parent
GLOBAL_SERVICES_DIR = AI_DIR.parent
DOCUMENTS_DIR = AI_DIR / "Preconditions" / "documents"
SPARSE_CACHE_DIR = AI_DIR / "models" / "sparse_cache"
COLLECTION_NAME = "UC"
DEFAULT_K = 5

sys.path.insert(0, str(GLOBAL_SERVICES_DIR))

from AI.llm_service import (
    DocumentIngestor,
    FileRef,
    RequestContext,
    create_rag_clients_from_env,
    load_env_and_validate,
)

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s | %(levelname)-7s | %(name)s | %(message)s",
)
logger = logging.getLogger(__name__)


async def main(
    file_path: Optional[str] = None,
    k: int = DEFAULT_K,
) -> Dict[str, Any]:
    """Основная функция UC-10: Классификация через Qdrant k-NN."""
    logger.info("=" * 70)
    logger.info("UC-10: Классификация документов через Qdrant (k-NN)")
    logger.info("Коллекция: %s | k=%d", COLLECTION_NAME, k)
    logger.info("=" * 70)

    # Находим файл
    if not file_path:
        files = DocumentIngestor.scan_directory(str(DOCUMENTS_DIR))
        if not files:
            return {"status": "error", "message": "Нет файлов для классификации"}
        file_path = files[0]
        logger.info("Файл не указан, используем: %s", Path(file_path).name)

    if not Path(file_path).exists():
        return {"status": "error", "message": f"Файл не найден: {file_path}"}

    # ШАГ 0. Конфигурация
    try:
        cfg = load_env_and_validate(str(GLOBAL_SERVICES_DIR))
    except ValueError as exc:
        return {"status": "error", "message": str(exc)}

    sparse_dir = cfg["SPARSE_CACHE_DIR"] or str(SPARSE_CACHE_DIR)
    if not Path(sparse_dir).exists():
        logger.error("ОШИБКА: SPARSE_CACHE_DIR не найден: %s", sparse_dir)
        return {"status": "error", "message": "SPARSE_CACHE_DIR не найден"}

    ctx = RequestContext(request_id="uc10-knn", user_id="uc10_user", mode="rag_qa")

    # ШАГ 1. Загрузка документа
    logger.info("ШАГ 1. Загрузка и инжест документа: %s", Path(file_path).name)
    ingestor = DocumentIngestor()
    file_ref = FileRef(path=file_path, original_name=Path(file_path).name)

    try:
        chunks = await ingestor.ingest(file_ref, ctx)
    except Exception as exc:
        logger.error("ШАГ 1. ОШИБКА инжеста: %s", exc)
        return {"status": "error", "message": f"Ошибка инжеста: {exc}"}

    if not chunks:
        return {"status": "error", "message": "Документ пуст"}

    # Берём текст первых чанков для поиска (до ~2000 символов)
    query_text = " ".join(c.text for c in chunks[:3])[:2000]
    logger.info("ШАГ 1. Документ для классификации получен — УСПЕХ: %d чанков, query_len=%d",
                len(chunks), len(query_text))

    # ШАГ 2. Генерация эмбеддинга (происходит внутри Retriever)
    logger.info("ШАГ 2. Генерация эмбеддинга документа — ОТПРАВЛЯЕМ")
    clients = create_rag_clients_from_env(
        collection=COLLECTION_NAME,
        sparse_cache_dir=sparse_dir,
    )
    retriever = clients["retriever"]
    logger.info("ШАГ 2. Эмбеддинг документа получен — УСПЕХ (через Retriever)")

    # ШАГ 3. Поиск ближайших соседей с категориями
    logger.info("ШАГ 3. Поиск %d ближайших соседей — ОТПРАВЛЯЕМ", k)

    snippets = await retriever.retrieve(query_text, ctx, top_k=k)
    logger.info("ШАГ 3. Найдено %d похожих документов — УСПЕХ", len(snippets))

    neighbors: List[Dict[str, Any]] = []
    for i, s in enumerate(snippets, 1):
        cat = s.metadata.get("category", "unknown")
        neighbors.append({
            "rank": i,
            "source_id": s.source_id,
            "score": s.score,
            "category": cat,
            "text_preview": s.text[:100],
        })
        logger.info("  [%d] score=%.3f | category=%s | %.80s...",
                     i, s.score, cat, s.text)

    # ШАГ 4. Голосование по категориям (k-NN majority voting)
    logger.info("ШАГ 4. Голосование по категориям — ОТПРАВЛЯЕМ")

    category_votes = Counter(n["category"] for n in neighbors)
    total_votes = len(neighbors)

    if total_votes == 0:
        logger.warning("ШАГ 4. Нет соседей для голосования")
        predicted_category = "unknown"
        confidence = 0.0
    else:
        predicted_category, vote_count = category_votes.most_common(1)[0]
        confidence = vote_count / total_votes

    # Проверка на отсутствие размеченных документов
    if predicted_category == "unknown" and confidence == 1.0 and total_votes > 0:
        logger.warning(
            "ШАГ 4. ВНИМАНИЕ: Все %d соседей имеют category=unknown. "
            "В коллекции нет размеченных документов. "
            "Используйте UC-9 для LLM-классификации или проиндексируйте документы с категорией.",
            total_votes
        )

    logger.info("ШАГ 4. Предсказана категория '%s' с уверенностью %.2f — УСПЕХ",
                predicted_category, confidence)
    logger.info("  Голоса: %s", dict(category_votes))

    # ШАГ 5. Результат классификации
    logger.info("ШАГ 5. Документ классифицирован — УСПЕХ")

    # ШАГ 6. Фильтрация по категориям (демо)
    logger.info("ШАГ 6. Категория '%s' доступна для фильтрации в RAG — УСПЕХ",
                predicted_category)
    logger.info("  Пример фильтра: {\"must\": [{\"key\": \"category\", \"match\": {\"value\": \"%s\"}}]}",
                predicted_category)

    result: Dict[str, Any] = {
        "status": "success",
        "uc": "UC-10",
        "file": Path(file_path).name,
        "file_path": file_path,
        "collection": COLLECTION_NAME,
        "k": k,
        "neighbors_found": len(neighbors),
        "neighbors": neighbors,
        "votes": dict(category_votes),
        "predicted_category": predicted_category,
        "confidence": confidence,
    }

    logger.info("РЕЗУЛЬТАТ UC-10: file=%s, category=%s, confidence=%.2f, neighbors=%d",
                result["file"], predicted_category, confidence, len(neighbors))
    return result


if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser(description="UC-10: k-NN классификация через Qdrant")
    parser.add_argument("file", nargs="?", default=None, help="Путь к документу")
    parser.add_argument("--k", type=int, default=DEFAULT_K, help="Количество соседей")
    args = parser.parse_args()

    try:
        result = asyncio.run(main(file_path=args.file, k=args.k))

        print("\n" + "=" * 70)
        print("UC-10: k-NN КЛАССИФИКАЦИЯ ЗАВЕРШЕНА")
        print("=" * 70)
        print(f"Статус: {result.get('status', 'unknown')}")
        print(f"Файл: {result.get('file', 'N/A')}")

        if result.get("status") == "success":
            print(f"Категория: {result['predicted_category']}")
            print(f"Уверенность: {result['confidence']:.2f}")
            print(f"Голоса: {json.dumps(result['votes'], ensure_ascii=False)}")
            print(f"Соседей: {result['neighbors_found']}")
            sys.exit(0)
        else:
            print(f"Ошибка: {result.get('message', 'Unknown')}")
            sys.exit(1)

    except KeyboardInterrupt:
        print("\nПрервано пользователем")
        sys.exit(130)
    except Exception as exc:
        logger.exception("Критическая ошибка в UC-10: %s", exc)
        sys.exit(1)
