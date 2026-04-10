# -*- coding: utf-8 -*-
"""
Руководство к файлу UC_12.py
============================

Назначение:
    Реализация UC-12: Управление коллекциями Qdrant (DevOps/Admin).
    1. Получение информации о коллекции — get_collection_info()
    2. Проверка состояния (Health Check) — count_points()
    3. Удаление коллекции (Destructive) — delete_collection()
    4. Очистка старых данных (Cleanup)

    Use Case: UC-12 из LLM_SERVICE.md
    Actor: Администратор / DevOps / Система мониторинга
    Цель: Управление векторными коллекциями: информация, удаление, очистка.

Архитектура (4 шага UC-12):
    ШАГ 1. Информация о коллекции — QdrantVectorStore.get_collection_info()
    ШАГ 2. Health Check — QdrantVectorStore.count_points()
    ШАГ 3. Удаление коллекции — QdrantVectorStore.delete_collection()
    ШАГ 4. Очистка старых данных

Используемые функции из llm_service.py:
    - load_env_and_validate, QdrantVectorStore

Использование:
    python -m AI.scripts.UC.UC_12 info UC
    python -m AI.scripts.UC.UC_12 count UC
    python -m AI.scripts.UC.UC_12 delete UC --confirm
    python -m AI.scripts.UC.UC_12 list

Зависимости:
    - llm_service.py, python-dotenv, qdrant_client
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

sys.path.insert(0, str(GLOBAL_SERVICES_DIR))

from AI.llm_service import (
    QdrantVectorStore,
    load_env_and_validate,
)

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s | %(levelname)-7s | %(name)s | %(message)s",
)
logger = logging.getLogger(__name__)


async def action_info(vector_store: QdrantVectorStore, collection: str) -> Dict[str, Any]:
    """ШАГ 1. Получение информации о коллекции."""
    logger.info("ШАГ 1. Информация о коллекции '%s' — ОТПРАВЛЯЕМ", collection)
    info = await vector_store.get_collection_info(collection)
    if info:
        logger.info("ШАГ 1. Информация о коллекции '%s' получена — УСПЕХ", collection)
        return {"status": "success", "action": "info", "collection": collection, "info": info}
    else:
        logger.error("ШАГ 1. Коллекция '%s' не найдена или ошибка", collection)
        return {"status": "error", "action": "info", "collection": collection,
                "message": "Коллекция не найдена или ошибка"}


async def action_count(
    vector_store: QdrantVectorStore,
    collection: str,
    filters: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    """ШАГ 2. Проверка состояния (Health Check)."""
    logger.info("ШАГ 2. Подсчёт точек в '%s' (filters=%s) — ОТПРАВЛЯЕМ",
                collection, bool(filters))
    count = await vector_store.count_points(collection, filters=filters)
    logger.info("ШАГ 2. Коллекция '%s' содержит %d точек — УСПЕХ", collection, count)
    return {
        "status": "success", "action": "count", "collection": collection,
        "points_count": count, "filters": filters,
    }


async def action_delete(
    vector_store: QdrantVectorStore,
    collection: str,
    confirm: bool = False,
) -> Dict[str, Any]:
    """ШАГ 3. Удаление коллекции (Destructive)."""
    if not confirm:
        logger.warning("ШАГ 3. Удаление '%s' — ОТМЕНЕНО (требуется --confirm)", collection)
        return {
            "status": "cancelled", "action": "delete", "collection": collection,
            "message": "Удаление требует подтверждения (--confirm). Операция необратима!",
        }

    logger.info("ШАГ 3. Удаление коллекции '%s' — ОТПРАВЛЯЕМ (подтверждено)", collection)
    success = await vector_store.delete_collection(collection)
    if success:
        logger.info("ШАГ 3. Коллекция '%s' удалена — УСПЕХ", collection)
        return {"status": "success", "action": "delete", "collection": collection}
    else:
        logger.error("ШАГ 3. Коллекция '%s' — ОШИБКА удаления", collection)
        return {"status": "error", "action": "delete", "collection": collection,
                "message": "Ошибка удаления"}


async def action_list_collections(vector_store: QdrantVectorStore) -> Dict[str, Any]:
    """Список всех коллекций (бонусная функция)."""
    logger.info("ШАГ LIST. Получение списка коллекций — ОТПРАВЛЯЕМ")
    try:
        collections_response = await vector_store._client.get_collections()
        names = [c.name for c in collections_response.collections]
        logger.info("ШАГ LIST. Найдено %d коллекций — УСПЕХ", len(names))
        return {"status": "success", "action": "list", "collections": names, "count": len(names)}
    except Exception as exc:
        logger.error("ШАГ LIST. ОШИБКА: %s", exc)
        return {"status": "error", "action": "list", "message": str(exc)}


async def main(
    action: str = "info",
    collection: str = "UC",
    confirm: bool = False,
    filters: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    """Основная функция UC-12: Управление коллекциями Qdrant."""
    logger.info("=" * 70)
    logger.info("UC-12: Управление коллекциями Qdrant (DevOps/Admin)")
    logger.info("Действие: %s | Коллекция: %s", action, collection)
    logger.info("=" * 70)

    # ШАГ 0. Конфигурация
    try:
        cfg = load_env_and_validate(str(GLOBAL_SERVICES_DIR))
    except ValueError as exc:
        return {"status": "error", "message": str(exc)}

    vector_store = QdrantVectorStore(
        host=cfg["QDRANT_HOST"],
        port=int(cfg["QDRANT_PORT"]),
        https=False,
    )

    if action == "info":
        return await action_info(vector_store, collection)
    elif action == "count":
        return await action_count(vector_store, collection, filters=filters)
    elif action == "delete":
        return await action_delete(vector_store, collection, confirm=confirm)
    elif action == "list":
        return await action_list_collections(vector_store)
    else:
        return {"status": "error", "message": f"Неизвестное действие: {action}"}


if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser(description="UC-12: Управление коллекциями Qdrant")
    parser.add_argument("action", choices=["info", "count", "delete", "list"],
                        help="Действие")
    parser.add_argument("collection", nargs="?", default="UC", help="Имя коллекции")
    parser.add_argument("--confirm", action="store_true", help="Подтверждение удаления")
    parser.add_argument("--filter-user-id", default=None, help="Фильтр по user_id")
    parser.add_argument("--filter-tags", nargs="*", default=None, help="Фильтр по тегам")
    args = parser.parse_args()

    _filters: Optional[Dict[str, Any]] = None
    if args.filter_user_id or args.filter_tags:
        _filters = {}
        if args.filter_user_id:
            _filters["user_id"] = args.filter_user_id
        if args.filter_tags:
            _filters["tags"] = args.filter_tags

    result = asyncio.run(main(
        action=args.action, collection=args.collection,
        confirm=args.confirm, filters=_filters,
    ))

    print("\n" + "=" * 70)
    print(f"UC-12: {args.action.upper()} ЗАВЕРШЕНО")
    print("=" * 70)
    print(json.dumps(result, ensure_ascii=False, indent=2))

    sys.exit(0 if result.get("status") == "success" else 1)
