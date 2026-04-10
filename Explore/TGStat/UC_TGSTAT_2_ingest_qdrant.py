# -*- coding: utf-8 -*-
"""
Руководство к файлу UC_TGSTAT_2_ingest_qdrant.py
================================================

Назначение:
    UC-style entrypoint для индексации Telegram-каналов вакансий в Qdrant.
    Сценарий:
      1. Загрузка списка каналов из vacancy_channels.json
      2. Парсинг последних 100 сообщений по каждому каналу
      3. Генерация эмбеддингов Cloud.ru
      4. Upsert в Qdrant
      5. Сохранение JSON-отчёта use-case

Использование:
    python Explore/TGStat/UC_TGSTAT_2_ingest_qdrant.py
    python Explore/TGStat/UC_TGSTAT_2_ingest_qdrant.py --limit 5 --collection tg_vacancy_channels

ШАГ 1. Проверка входного vacancy_channels.json.
ШАГ 2. Запуск ingest_tg_vacancies_to_qdrant.main().
ШАГ 3. Поиск ingestion_report_*.json.
ШАГ 4. Сохранение use-case JSON-отчёта.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import logging
import sys
from pathlib import Path
from typing import Any, Dict, Optional

SCRIPT_DIR = Path(__file__).parent.absolute()
ROOT_DIR = SCRIPT_DIR.parent.parent

if str(ROOT_DIR) not in sys.path:
    sys.path.insert(0, str(ROOT_DIR))

from Explore.TGStat.ingest_tg_vacancies_to_qdrant import main as ingest_main

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s | %(levelname)-7s | %(name)s | %(message)s",
)
logger = logging.getLogger(__name__)


async def main(channels_json: str, collection: str, limit: Optional[int]) -> Dict[str, Any]:
    logger.info("=" * 80)
    logger.info("UC-TGSTAT-2: 100 сообщений/канал → Cloud.ru embeddings → Qdrant")
    logger.info("=" * 80)

    channels_path = Path(channels_json)
    output_dir = SCRIPT_DIR / "output"
    report_path = output_dir / "uc_tgstat_2_report.json"

    logger.info("ШАГ 1. Проверка channels_json: %s", channels_path)
    if not channels_path.exists():
        message = f"Файл не найден: {channels_path}"
        logger.error("ШАГ 1. ОШИБКА: %s", message)
        return {"status": "error", "uc": "UC-TGSTAT-2", "message": message}

    logger.info("ШАГ 2. Запускаем ingest_tg_vacancies_to_qdrant.main() — ОТПРАВЛЯЕМ")
    await ingest_main(
        channels_json=channels_path,
        collection=collection,
        limit=limit,
    )
    logger.info("ШАГ 2. Индексация TG вакансий завершена — УСПЕХ")

    logger.info("ШАГ 3. Ищем ingestion_report_*.json")
    ingestion_reports = sorted(str(p) for p in output_dir.glob("ingestion_report_*.json"))
    latest_report = ingestion_reports[-1] if ingestion_reports else None
    logger.info("ШАГ 3. Найдено отчётов: %d", len(ingestion_reports))

    result: Dict[str, Any] = {
        "status": "success",
        "uc": "UC-TGSTAT-2",
        "channels_json": str(channels_path),
        "collection": collection,
        "limit": limit,
        "latest_ingestion_report": latest_report,
        "all_ingestion_reports": ingestion_reports,
    }

    logger.info("ШАГ 4. Сохраняем JSON-отчёт: %s", report_path)
    output_dir.mkdir(parents=True, exist_ok=True)
    report_path.write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
    logger.info("ШАГ 4. JSON-отчёт сохранён — УСПЕХ")
    return result


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="UC-TGSTAT-2: Индексация TG vacancy channels в Qdrant")
    parser.add_argument(
        "--channels-json",
        default=str(SCRIPT_DIR / "output" / "vacancy_channels.json"),
        help="Путь к vacancy_channels.json",
    )
    parser.add_argument(
        "--collection",
        default="tg_vacancy_channels",
        help="Имя Qdrant-коллекции",
    )
    parser.add_argument(
        "--limit",
        type=int,
        default=None,
        help="Обрабатывать только первые N каналов",
    )
    return parser.parse_args()


if __name__ == "__main__":
    args = parse_args()
    result = asyncio.run(
        main(
            channels_json=args.channels_json,
            collection=args.collection,
            limit=args.limit,
        )
    )

    print("\n" + "=" * 80)
    print("UC-TGSTAT-2: INGEST TO QDRANT ЗАВЕРШЁН")
    print("=" * 80)
    print(json.dumps(result, ensure_ascii=False, indent=2))
    sys.exit(0 if result.get("status") == "success" else 1)
