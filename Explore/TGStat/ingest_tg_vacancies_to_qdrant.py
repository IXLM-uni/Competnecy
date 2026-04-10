# -*- coding: utf-8 -*-
"""
Руководство к файлу ingest_tg_vacancies_to_qdrant.py
=====================================================

Назначение:
    Берёт список каналов из vacancy_channels.json (или из parse_tgstat_vacancies.py),
    для каждого канала парсит последние 100 сообщений через t.me/s/<username>
    (без Telethon/API-ключей) и индексирует их в Qdrant-коллекцию для
    последующего семантического поиска по вакансиям.

Архитектура:
    ШАГ 1. Загрузка списка каналов из JSON.
    ШАГ 2. Для каждого канала — парсинг 100 сообщений (httpx + selectolax).
    ШАГ 3. Чанкинг сообщений (каждое сообщение = 1 документ).
    ШАГ 4. Dense embedding через Cloud.ru (Qwen3-Embedding-0.6B).
    ШАГ 5. Upsert в Qdrant коллекцию "tg_vacancy_channels".
    ШАГ 6. Сохранение отчёта о результатах.

Использование:
    python Explore/TGStat/ingest_tg_vacancies_to_qdrant.py
    python Explore/TGStat/ingest_tg_vacancies_to_qdrant.py --limit 5 --collection my_vacancies

Переменные окружения (из Global_services/.env):
    CLOUDRU_API_KEY         — API ключ Cloud.ru
    CLOUDRU_EMBED_MODEL     — модель эмбеддингов (Qwen/Qwen3-Embedding-0.6B)
    CLOUDRU_BASE_URL        — базовый URL Cloud.ru API
    QDRANT_HOST             — хост Qdrant (default: localhost)
    QDRANT_PORT             — порт Qdrant (default: 6333)
"""

from __future__ import annotations

import argparse
import asyncio
import json
import logging
import os
import re
import sys
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

import httpx
from dotenv import load_dotenv
from selectolax.parser import HTMLParser

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
)
logger = logging.getLogger(__name__)

HERE = Path(__file__).resolve().parent
ROOT = HERE.parent.parent
GLOBAL_SERVICES = ROOT / "Global_services"

# Загружаем .env
_root_env_path = ROOT / ".env"
_global_env_path = GLOBAL_SERVICES / ".env"
if _root_env_path.exists():
    load_dotenv(_root_env_path)
    logger.info("ШАГ 0. .env загружен из %s", _root_env_path)
elif _global_env_path.exists():
    load_dotenv(_global_env_path)
    logger.info("ШАГ 0. .env загружен из %s", _global_env_path)

# Добавляем Global_services в путь
for p in (ROOT, GLOBAL_SERVICES):
    s = str(p)
    if s not in sys.path:
        sys.path.insert(0, s)

MESSAGES_LIMIT = 100
COLLECTION_NAME = "tg_vacancy_channels"
EMBED_DIM = 1024  # Qwen3-Embedding-0.6B выдаёт 1024
BATCH_SIZE = 32   # точек за один upsert
CRAWL_DELAY = 0.8  # секунды между запросами (вежливая пауза)

HTTP_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (X11; Linux x86_64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/124.0.0.0 Safari/537.36"
    ),
    "Accept-Language": "ru,en;q=0.9",
}


# ---------------------------------------------------------------------------
# Парсинг Telegram канала (t.me/s/<username>)
# ---------------------------------------------------------------------------

async def _fetch_page(client: httpx.AsyncClient, url: str, retries: int = 3) -> str:
    """Загружает HTML-страницу с ретраями."""
    for attempt in range(1, retries + 1):
        try:
            resp = await client.get(url)
            if resp.status_code != 200:
                raise RuntimeError(f"HTTP {resp.status_code}")
            return resp.text
        except Exception as exc:
            logger.warning("Попытка %d/%d ОШИБКА url=%s: %s", attempt, retries, url, exc)
            if attempt < retries:
                await asyncio.sleep(2 * attempt)
    raise RuntimeError(f"Не удалось загрузить {url} после {retries} попыток")


def _parse_messages(html: str) -> list[dict]:
    """
    Парсит сообщения из HTML web-preview t.me/s/<channel>.
    Возвращает список dict с полями: message_id, text, date, views, url.
    """
    tree = HTMLParser(html)
    messages = []
    
    for item in tree.css(".tgme_widget_message_wrap"):
        # message_id из data-post
        msg_el = item.css_first(".tgme_widget_message")
        if msg_el is None:
            continue
        
        data_post = msg_el.attributes.get("data-post", "")
        msg_id_match = re.search(r"/(\d+)$", data_post)
        if not msg_id_match:
            continue
        msg_id = int(msg_id_match.group(1))
        
        # Текст
        text_el = item.css_first(".tgme_widget_message_text")
        text = text_el.text(strip=True) if text_el else ""
        
        if not text or len(text) < 20:
            continue  # Пропускаем медиа без текста и слишком короткие
        
        # Дата
        date_el = item.css_first(".tgme_widget_message_date time")
        date_str = ""
        if date_el:
            date_str = date_el.attributes.get("datetime", "")
        
        # Просмотры
        views = 0
        views_el = item.css_first(".tgme_widget_message_views")
        if views_el:
            raw = views_el.text(strip=True).replace("\xa0", "").replace(" ", "").replace(",", ".")
            m = re.match(r"^([0-9]+(?:\.[0-9]+)?)([KkMm])?$", raw)
            if m:
                num = float(m.group(1))
                suffix = m.group(2)
                if suffix in ("K", "k"):
                    num *= 1_000
                elif suffix in ("M", "m"):
                    num *= 1_000_000
                views = int(num)
        
        # URL сообщения
        link_el = item.css_first("a.tgme_widget_message_date")
        msg_url = link_el.attributes.get("href", "") if link_el else ""
        
        messages.append({
            "message_id": msg_id,
            "text": text,
            "date": date_str,
            "views": views,
            "url": msg_url,
        })
    
    return messages


async def parse_channel_messages(username: str, limit: int = 100) -> list[dict]:
    """
    Парсит последние `limit` сообщений из Telegram-канала.
    
    ШАГ 2.1. Первая страница.
    ШАГ 2.2. Пагинация через ?before=<id> до накопления `limit` сообщений.
    """
    preview_url = f"https://t.me/s/{username}"
    all_messages: list[dict] = []
    
    async with httpx.AsyncClient(headers=HTTP_HEADERS, timeout=30.0, follow_redirects=True) as client:
        logger.info("  ШАГ 2.1. Первая страница @%s ...", username)
        try:
            first_html = await _fetch_page(client, preview_url)
        except RuntimeError as exc:
            logger.error("  ШАГ 2.1. ОШИБКА @%s: %s", username, exc)
            return []
        
        page_msgs = _parse_messages(first_html)
        all_messages.extend(page_msgs)
        logger.info("  ШАГ 2.1. Первая страница: %d сообщений", len(page_msgs))
        
        # Пагинация
        page_num = 2
        while len(all_messages) < limit and page_msgs:
            known_ids = {m["message_id"] for m in all_messages}
            oldest_id = min(m["message_id"] for m in page_msgs)
            page_url = f"https://t.me/s/{username}?before={oldest_id}"
            
            logger.info("  ШАГ 2.%d. Пагинация before=%d ...", page_num, oldest_id)
            await asyncio.sleep(CRAWL_DELAY)
            
            try:
                page_html = await _fetch_page(client, page_url)
            except RuntimeError as exc:
                logger.error("  ШАГ 2.%d. ОШИБКА: %s — остановка", page_num, exc)
                break
            
            page_msgs = _parse_messages(page_html)
            new_msgs = [m for m in page_msgs if m["message_id"] not in known_ids]
            if not new_msgs:
                logger.info("  ШАГ 2.%d. Нет новых сообщений — конец канала", page_num)
                break
            
            all_messages.extend(new_msgs)
            logger.info(
                "  ШАГ 2.%d. +%d новых, итого=%d",
                page_num, len(new_msgs), len(all_messages),
            )
            page_num += 1
            page_msgs = new_msgs
    
    # Сортируем и берём limit последних
    all_messages.sort(key=lambda m: m["message_id"], reverse=True)
    return all_messages[:limit]


# ---------------------------------------------------------------------------
# Эмбеддинги
# ---------------------------------------------------------------------------

async def embed_texts(texts: list[str], api_key: str, base_url: str, model: str) -> list[list[float]]:
    """
    Получает dense-эмбеддинги через Cloud.ru API (OpenAI-compatible).
    Обрабатывает батчами по BATCH_SIZE.
    """
    import openai
    
    client = openai.AsyncOpenAI(api_key=api_key, base_url=base_url)
    all_embeddings: list[list[float]] = []
    
    for i in range(0, len(texts), BATCH_SIZE):
        batch = texts[i : i + BATCH_SIZE]
        logger.info(
            "  ШАГ 4. Эмбеддинги батч %d-%d / %d ...",
            i + 1, min(i + BATCH_SIZE, len(texts)), len(texts),
        )
        resp = await client.embeddings.create(model=model, input=batch)
        batch_embeddings = [e.embedding for e in resp.data]
        all_embeddings.extend(batch_embeddings)
        await asyncio.sleep(0.2)
    
    return all_embeddings


# ---------------------------------------------------------------------------
# Qdrant: создание коллекции + upsert
# ---------------------------------------------------------------------------

def ensure_qdrant_collection(host: str, port: int, collection: str) -> None:
    """Создаёт коллекцию Qdrant если её нет."""
    from qdrant_client import QdrantClient
    from qdrant_client.models import Distance, VectorParams
    
    client = QdrantClient(host=host, port=port, timeout=30)
    existing = [c.name for c in client.get_collections().collections]
    
    if collection in existing:
        logger.info("ШАГ 3. Коллекция '%s' уже существует — пропуск создания", collection)
        return
    
    logger.info("ШАГ 3. Создание коллекции '%s' (dim=%d, Cosine) ...", collection, EMBED_DIM)
    client.create_collection(
        collection_name=collection,
        vectors_config=VectorParams(size=EMBED_DIM, distance=Distance.COSINE),
    )
    logger.info("ШАГ 3. Коллекция '%s' создана ... УСПЕХ", collection)


async def upsert_to_qdrant(
    host: str,
    port: int,
    collection: str,
    points: list[dict],
) -> int:
    """Upsert точек в Qdrant. Возвращает количество загруженных."""
    from qdrant_client import QdrantClient
    from qdrant_client.models import PointStruct
    
    client = QdrantClient(host=host, port=port, timeout=60)
    total_upserted = 0
    
    for i in range(0, len(points), BATCH_SIZE):
        batch = points[i : i + BATCH_SIZE]
        qdrant_points = [
            PointStruct(
                id=p["id"],
                vector=p["vector"],
                payload=p["payload"],
            )
            for p in batch
        ]
        client.upsert(collection_name=collection, points=qdrant_points)
        total_upserted += len(batch)
        logger.info(
            "  ШАГ 5. Qdrant upsert: батч %d-%d / %d ... УСПЕХ",
            i + 1, min(i + BATCH_SIZE, len(points)), len(points),
        )
    
    return total_upserted


# ---------------------------------------------------------------------------
# Главный оркестратор
# ---------------------------------------------------------------------------

async def ingest_channel(
    channel: dict,
    api_key: str,
    embed_base_url: str,
    embed_model: str,
    qdrant_host: str,
    qdrant_port: int,
    collection: str,
) -> dict:
    """
    Полный цикл ingestion для одного канала.
    Возвращает отчёт {username, messages_found, messages_indexed, status}.
    """
    username = channel["username"]
    logger.info("=" * 60)
    logger.info("КАНАЛ @%s (%s)", username, channel.get("name", ""))
    
    # ШАГ 2. Парсинг сообщений
    logger.info("ШАГ 2. Парсинг %d сообщений @%s ...", MESSAGES_LIMIT, username)
    messages = await parse_channel_messages(username, limit=MESSAGES_LIMIT)
    
    if not messages:
        logger.warning("ШАГ 2. Нет сообщений для @%s (канал закрыт или недоступен)", username)
        return {
            "username": username,
            "name": channel.get("name", ""),
            "messages_found": 0,
            "messages_indexed": 0,
            "status": "no_messages",
        }
    
    logger.info("ШАГ 2. @%s: получено %d сообщений ... УСПЕХ", username, len(messages))
    
    # ШАГ 4. Эмбеддинги
    texts = [m["text"] for m in messages]
    logger.info("ШАГ 4. Генерация эмбеддингов для %d сообщений @%s ...", len(texts), username)
    
    try:
        embeddings = await embed_texts(texts, api_key, embed_base_url, embed_model)
    except Exception as exc:
        logger.error("ШАГ 4. ОШИБКА эмбеддингов @%s: %s", username, exc)
        return {
            "username": username,
            "name": channel.get("name", ""),
            "messages_found": len(messages),
            "messages_indexed": 0,
            "status": f"embed_error: {exc}",
        }
    
    logger.info("ШАГ 4. Эмбеддинги @%s: %d векторов ... УСПЕХ", username, len(embeddings))
    
    # ШАГ 5. Формирование точек для Qdrant
    import hashlib
    points: list[dict] = []
    for msg, emb in zip(messages, embeddings):
        # Детерминированный ID на основе канала + message_id
        uid = int(
            hashlib.sha256(f"{username}:{msg['message_id']}".encode()).hexdigest()[:15],
            16,
        )
        points.append({
            "id": uid,
            "vector": emb,
            "payload": {
                "channel_username": username,
                "channel_name": channel.get("name", ""),
                "channel_subscribers": channel.get("subscribers", 0),
                "peer_type": channel.get("peer_type", "channel"),
                "message_id": msg["message_id"],
                "text": msg["text"],
                "date": msg["date"],
                "views": msg["views"],
                "url": msg["url"],
                "indexed_at": datetime.now(timezone.utc).isoformat(),
            },
        })
    
    # ШАГ 5. Upsert
    logger.info("ШАГ 5. Upsert %d точек в Qdrant @%s ...", len(points), username)
    try:
        upserted = await upsert_to_qdrant(qdrant_host, qdrant_port, collection, points)
    except Exception as exc:
        logger.error("ШАГ 5. ОШИБКА upsert @%s: %s", username, exc)
        return {
            "username": username,
            "name": channel.get("name", ""),
            "messages_found": len(messages),
            "messages_indexed": 0,
            "status": f"upsert_error: {exc}",
        }
    
    logger.info("ШАГ 5. @%s: %d сообщений загружено в Qdrant ... УСПЕХ", username, upserted)
    
    return {
        "username": username,
        "name": channel.get("name", ""),
        "messages_found": len(messages),
        "messages_indexed": upserted,
        "status": "ok",
    }


async def main(channels_json: Path, collection: str, limit: Optional[int]) -> None:
    """
    Главный оркестратор ingestion всех TG-каналов в Qdrant.
    
    ШАГ 0. Загрузка конфигурации (.env).
    ШАГ 1. Загрузка списка каналов из JSON.
    ШАГ 2. Для каждого канала — парсинг сообщений.
    ШАГ 3. Создание/проверка Qdrant-коллекции.
    ШАГ 4. Генерация эмбеддингов.
    ШАГ 5. Upsert в Qdrant.
    ШАГ 6. Сохранение отчёта.
    """
    # ШАГ 0. Конфигурация
    api_key = os.getenv("CLOUDRU_API_KEY", "")
    embed_base_url = os.getenv("CLOUDRU_BASE_URL", "https://foundation-models.api.cloud.ru/v1")
    embed_model = os.getenv("CLOUDRU_EMBED_MODEL", "Qwen/Qwen3-Embedding-0.6B")
    qdrant_host = os.getenv("QDRANT_HOST", "localhost")
    qdrant_port = int(os.getenv("QDRANT_PORT", "6333"))
    
    logger.info("ШАГ 0. Конфигурация:")
    logger.info("  embed_model=%s", embed_model)
    logger.info("  qdrant=%s:%d, collection=%s", qdrant_host, qdrant_port, collection)
    
    if not api_key:
        logger.error("ШАГ 0. ОШИБКА: CLOUDRU_API_KEY не задан в .env")
        sys.exit(1)
    
    # ШАГ 1. Загрузка каналов
    logger.info("ШАГ 1. Загрузка списка каналов из %s ...", channels_json)
    if not channels_json.exists():
        logger.error("ШАГ 1. ОШИБКА: файл не найден: %s", channels_json)
        logger.error("Сначала запустите: python Explore/TGStat/parse_tgstat_vacancies.py")
        sys.exit(1)
    
    with channels_json.open(encoding="utf-8") as f:
        channels: list[dict] = json.load(f)
    
    if limit:
        channels = channels[:limit]
        logger.info("ШАГ 1. Применён лимит: обрабатываем %d каналов", limit)
    
    logger.info("ШАГ 1. Загружено %d каналов/чатов ... УСПЕХ", len(channels))
    
    # ШАГ 3. Создание Qdrant-коллекции
    logger.info("ШАГ 3. Инициализация Qdrant-коллекции '%s' ...", collection)
    try:
        ensure_qdrant_collection(qdrant_host, qdrant_port, collection)
    except Exception as exc:
        logger.error("ШАГ 3. ОШИБКА Qdrant: %s", exc)
        logger.error("Убедитесь что Qdrant запущен: docker-compose up -d qdrant")
        sys.exit(1)
    
    # ШАГ 2-4-5. Обработка каждого канала
    reports: list[dict] = []
    total_channels = len(channels)
    
    for idx, channel in enumerate(channels, 1):
        logger.info(
            "\n[%d/%d] Обработка @%s ...",
            idx, total_channels, channel["username"],
        )
        try:
            report = await ingest_channel(
                channel=channel,
                api_key=api_key,
                embed_base_url=embed_base_url,
                embed_model=embed_model,
                qdrant_host=qdrant_host,
                qdrant_port=qdrant_port,
                collection=collection,
            )
        except Exception as exc:
            logger.error("[%d/%d] ОШИБКА @%s: %s", idx, total_channels, channel["username"], exc)
            report = {
                "username": channel["username"],
                "name": channel.get("name", ""),
                "messages_found": 0,
                "messages_indexed": 0,
                "status": f"unexpected_error: {exc}",
            }
        
        reports.append(report)
        
        # Пауза между каналами чтобы не флудить Telegram
        if idx < total_channels:
            await asyncio.sleep(CRAWL_DELAY * 2)
    
    # ШАГ 6. Сохранение отчёта
    report_dir = HERE / "output"
    report_dir.mkdir(parents=True, exist_ok=True)
    
    ts = datetime.now().strftime("%Y%m%d_%H%M%S")
    report_path = report_dir / f"ingestion_report_{ts}.json"
    
    summary = {
        "collection": collection,
        "total_channels": total_channels,
        "ok_channels": sum(1 for r in reports if r["status"] == "ok"),
        "failed_channels": sum(1 for r in reports if r["status"] != "ok"),
        "total_messages_indexed": sum(r["messages_indexed"] for r in reports),
        "created_at": datetime.now(timezone.utc).isoformat(),
        "channels": reports,
    }
    
    report_path.write_text(json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8")
    logger.info("ШАГ 6. Отчёт сохранён: %s", report_path)
    
    # Итог
    print(f"\n{'='*60}")
    print(f"INGESTION ЗАВЕРШЁН")
    print(f"  Коллекция: {collection}")
    print(f"  Каналов обработано: {total_channels}")
    print(f"  Успешно:  {summary['ok_channels']}")
    print(f"  Ошибки:   {summary['failed_channels']}")
    print(f"  Загружено сообщений: {summary['total_messages_indexed']}")
    print(f"  Отчёт: {report_path}")
    print(f"{'='*60}\n")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(
        description="Ingestion TG-вакансий (100 сообщений/канал) в Qdrant"
    )
    parser.add_argument(
        "--channels-json",
        default=str(HERE / "output" / "vacancy_channels.json"),
        help="Путь к JSON-файлу со списком каналов (из parse_tgstat_vacancies.py)",
    )
    parser.add_argument(
        "--collection",
        default=COLLECTION_NAME,
        help=f"Имя Qdrant-коллекции (default: {COLLECTION_NAME})",
    )
    parser.add_argument(
        "--limit",
        type=int,
        default=None,
        help="Обрабатывать только первые N каналов (для тестирования)",
    )
    args = parser.parse_args()
    
    asyncio.run(
        main(
            channels_json=Path(args.channels_json),
            collection=args.collection,
            limit=args.limit,
        )
    )
