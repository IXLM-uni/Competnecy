# -*- coding: utf-8 -*-
"""
Руководство к файлу UC_TGSTAT_1_extract_channels.py
===================================================

Назначение:
    UC-style entrypoint для TGStat сценария извлечения каналов/чатов с вакансиями.
    Сценарий:
      1. Загрузка HTML-файлов Vacancies.html и Vacancies_chats.html
      2. Парсинг карточек каналов/чатов
      3. Сохранение JSON и CSV со списком источников
      4. Сохранение JSON-отчёта use-case

Использование:
    python Explore/TGStat/UC_TGSTAT_1_extract_channels.py
    python Explore/TGStat/UC_TGSTAT_1_extract_channels.py --output-dir Explore/TGStat/output

ШАГ 1. Проверка входных HTML-файлов.
ШАГ 2. Запуск parse_tgstat_vacancies.py.
ШАГ 3. Проверка созданных JSON/CSV артефактов.
ШАГ 4. Сохранение JSON-отчёта.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import logging
import sys
from pathlib import Path
from typing import Any, Dict

SCRIPT_DIR = Path(__file__).parent.absolute()
ROOT_DIR = SCRIPT_DIR.parent.parent

if str(ROOT_DIR) not in sys.path:
    sys.path.insert(0, str(ROOT_DIR))

from Explore.TGStat.parse_tgstat_vacancies import INFO_DIR, main as tgstat_parse_main

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s | %(levelname)-7s | %(name)s | %(message)s",
)
logger = logging.getLogger(__name__)


async def main(output_dir: str) -> Dict[str, Any]:
    logger.info("=" * 80)
    logger.info("UC-TGSTAT-1: Извлечение каналов и чатов с вакансиями из TGStat HTML")
    logger.info("=" * 80)

    out_dir = Path(output_dir)
    report_path = out_dir / "uc_tgstat_1_report.json"
    vacancies_html = INFO_DIR / "Vacancies.html"
    chats_html = INFO_DIR / "Vacancies_chats.html"

    logger.info("ШАГ 1. Проверка входных файлов: %s и %s", vacancies_html, chats_html)
    if not vacancies_html.exists():
        message = f"Файл не найден: {vacancies_html}"
        logger.error("ШАГ 1. ОШИБКА: %s", message)
        return {"status": "error", "uc": "UC-TGSTAT-1", "message": message}

    logger.info("ШАГ 2. Запускаем parse_tgstat_vacancies.main() — ОТПРАВЛЯЕМ")
    tgstat_parse_main(out_dir)
    logger.info("ШАГ 2. Парсинг TGStat завершён — УСПЕХ")

    json_path = out_dir / "vacancy_channels.json"
    csv_path = out_dir / "vacancy_channels.csv"

    logger.info("ШАГ 3. Проверяем артефакты: json=%s, csv=%s", json_path.exists(), csv_path.exists())
    result: Dict[str, Any] = {
        "status": "success" if json_path.exists() and csv_path.exists() else "error",
        "uc": "UC-TGSTAT-1",
        "output_dir": str(out_dir),
        "json_output": str(json_path),
        "csv_output": str(csv_path),
        "input_vacancies_html": str(vacancies_html),
        "input_chats_html": str(chats_html),
    }

    logger.info("ШАГ 4. Сохраняем JSON-отчёт: %s", report_path)
    out_dir.mkdir(parents=True, exist_ok=True)
    report_path.write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
    logger.info("ШАГ 4. JSON-отчёт сохранён — УСПЕХ")
    return result


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="UC-TGSTAT-1: Извлечение vacancy channels из TGStat HTML")
    parser.add_argument(
        "--output-dir",
        default=str(SCRIPT_DIR / "output"),
        help="Директория результата",
    )
    return parser.parse_args()


if __name__ == "__main__":
    args = parse_args()
    result = asyncio.run(main(output_dir=args.output_dir))

    print("\n" + "=" * 80)
    print("UC-TGSTAT-1: EXTRACT CHANNELS ЗАВЕРШЁН")
    print("=" * 80)
    print(json.dumps(result, ensure_ascii=False, indent=2))
    sys.exit(0 if result.get("status") == "success" else 1)
