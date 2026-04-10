# -*- coding: utf-8 -*-
"""
Руководство к файлу UC_HH_1_extract_professions.py
=================================================

Назначение:
    UC-style entrypoint для HH направления.
    Сценарий:
      1. Парсинг страницы Professions.html
      2. Сохранение CSV: Буква;Название профессии;Количество вакансий;Ссылка hh.ru
      3. Генерация professions.md для LLM-контекста
      4. Сохранение JSON-отчёта

Использование:
    python Explore/HH/UC_HH_1_extract_professions.py
    python Explore/HH/UC_HH_1_extract_professions.py --input Explore/HH/info/Professions.html --output-dir Explore/HH/output

ШАГ 1. Загрузка HTML-файла профессий HH.
ШАГ 2. Извлечение профессий в CSV.
ШАГ 3. Конвертация CSV в Markdown.
ШАГ 4. Сохранение JSON-отчёта.
"""

from __future__ import annotations

import argparse
import json
import logging
import sys
from pathlib import Path
from typing import Any, Dict

SCRIPT_DIR = Path(__file__).parent.absolute()
ROOT_DIR = SCRIPT_DIR.parent.parent

if str(ROOT_DIR) not in sys.path:
    sys.path.insert(0, str(ROOT_DIR))

from Explore.HH.extract_professions import main as extract_main
from Explore.HH.professions_to_md import main as md_main

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s | %(levelname)-7s | %(name)s | %(message)s",
)
logger = logging.getLogger(__name__)


async def main(input_html: str, output_dir: str) -> Dict[str, Any]:
    logger.info("=" * 80)
    logger.info("UC-HH-1: Извлечение справочника профессий HH.ru")
    logger.info("=" * 80)

    input_path = Path(input_html)
    out_dir = Path(output_dir)
    csv_path = out_dir / "professions.csv"
    md_path = out_dir / "professions.md"
    report_path = out_dir / "uc_hh_1_report.json"

    logger.info("ШАГ 1. Проверка входного HTML: %s", input_path)
    if not input_path.exists():
        message = f"Файл не найден: {input_path}"
        logger.error("ШАГ 1. ОШИБКА: %s", message)
        return {"status": "error", "uc": "UC-HH-1", "message": message}

    logger.info("ШАГ 2. Запускаем extract_professions.py — ОТПРАВЛЯЕМ")
    extract_main(input_path, csv_path)
    logger.info("ШАГ 2. CSV сохранён: %s — УСПЕХ", csv_path)

    logger.info("ШАГ 3. Запускаем professions_to_md.py — ОТПРАВЛЯЕМ")
    md_main(csv_path, md_path)
    logger.info("ШАГ 3. Markdown сохранён: %s — УСПЕХ", md_path)

    result: Dict[str, Any] = {
        "status": "success",
        "uc": "UC-HH-1",
        "input_html": str(input_path),
        "csv_output": str(csv_path),
        "md_output": str(md_path),
    }

    logger.info("ШАГ 4. Сохраняем JSON-отчёт: %s", report_path)
    out_dir.mkdir(parents=True, exist_ok=True)
    report_path.write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
    logger.info("ШАГ 4. JSON-отчёт сохранён — УСПЕХ")
    return result


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="UC-HH-1: Извлечение справочника профессий HH.ru")
    parser.add_argument(
        "--input",
        default=str(SCRIPT_DIR / "info" / "Professions.html"),
        help="Путь к Professions.html",
    )
    parser.add_argument(
        "--output-dir",
        default=str(SCRIPT_DIR / "output"),
        help="Директория результата",
    )
    return parser.parse_args()


if __name__ == "__main__":
    import asyncio

    args = parse_args()
    result = asyncio.run(main(input_html=args.input, output_dir=args.output_dir))

    print("\n" + "=" * 80)
    print("UC-HH-1: ИЗВЛЕЧЕНИЕ СПРАВОЧНИКА HH ЗАВЕРШЕНО")
    print("=" * 80)
    print(json.dumps(result, ensure_ascii=False, indent=2))
    sys.exit(0 if result.get("status") == "success" else 1)
