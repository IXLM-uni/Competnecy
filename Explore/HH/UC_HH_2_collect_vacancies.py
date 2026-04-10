# -*- coding: utf-8 -*-
"""
Руководство к файлу UC_HH_2_collect_vacancies.py
================================================

Назначение:
    UC-style entrypoint для сценария HH вакансий.
    Сценарий:
      1. Загрузка professions.md
      2. LLM выбирает топ-N профессий
      3. crawler4ai парсит топ вакансий по профессиям
      4. Сохранение .md файлов вакансий
      5. Сохранение JSON-отчёта

Использование:
    python Explore/HH/UC_HH_2_collect_vacancies.py --query "Python developer ML"

ШАГ 1. Проверка входных файлов и конфигурации.
ШАГ 2. Запуск hh_vacancy_tool.py.
ШАГ 3. Поиск созданных markdown-артефактов.
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

from Explore.HH.hh_vacancy_tool import main as hh_main

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s | %(levelname)-7s | %(name)s | %(message)s",
)
logger = logging.getLogger(__name__)


async def main(query: str, professions_md: str, output_dir: str, top_professions: int) -> Dict[str, Any]:
    logger.info("=" * 80)
    logger.info("UC-HH-2: LLM → HH профессии → crawler4ai → вакансии")
    logger.info("=" * 80)

    professions_md_path = Path(professions_md)
    output_path = Path(output_dir)
    report_path = output_path / "uc_hh_2_report.json"

    logger.info("ШАГ 1. Проверка professions.md: %s", professions_md_path)
    if not professions_md_path.exists():
        message = f"Файл professions.md не найден: {professions_md_path}"
        logger.error("ШАГ 1. ОШИБКА: %s", message)
        return {"status": "error", "uc": "UC-HH-2", "message": message}

    logger.info("ШАГ 2. Запускаем hh_vacancy_tool.main() — ОТПРАВЛЯЕМ")
    await hh_main(
        query=query,
        professions_md_path=professions_md_path,
        output_dir=output_path,
        top_professions=top_professions,
    )
    logger.info("ШАГ 2. Сбор вакансий завершён — УСПЕХ")

    logger.info("ШАГ 3. Сканируем output-dir на markdown-файлы вакансий")
    markdown_files = sorted(str(p) for p in output_path.glob("*_vacancies.md"))
    logger.info("ШАГ 3. Найдено markdown-файлов: %d", len(markdown_files))

    result: Dict[str, Any] = {
        "status": "success",
        "uc": "UC-HH-2",
        "query": query,
        "professions_md": str(professions_md_path),
        "output_dir": str(output_path),
        "top_professions": top_professions,
        "markdown_files": markdown_files,
        "markdown_files_count": len(markdown_files),
    }

    logger.info("ШАГ 4. Сохраняем JSON-отчёт: %s", report_path)
    output_path.mkdir(parents=True, exist_ok=True)
    report_path.write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
    logger.info("ШАГ 4. JSON-отчёт сохранён — УСПЕХ")
    return result


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="UC-HH-2: Сбор вакансий HH.ru через LLM + crawler4ai")
    parser.add_argument("--query", required=True, help="Тема / компетенция")
    parser.add_argument(
        "--professions-md",
        default=str(SCRIPT_DIR / "output" / "professions.md"),
        help="Путь к professions.md",
    )
    parser.add_argument(
        "--output-dir",
        default=str(SCRIPT_DIR / "output" / "hh_vacancies"),
        help="Директория результата",
    )
    parser.add_argument(
        "--top-professions",
        type=int,
        default=10,
        help="Сколько профессий выбирать через LLM",
    )
    return parser.parse_args()


if __name__ == "__main__":
    args = parse_args()
    result = asyncio.run(
        main(
            query=args.query,
            professions_md=args.professions_md,
            output_dir=args.output_dir,
            top_professions=args.top_professions,
        )
    )

    print("\n" + "=" * 80)
    print("UC-HH-2: СБОР ВАКАНСИЙ HH ЗАВЕРШЁН")
    print("=" * 80)
    print(json.dumps(result, ensure_ascii=False, indent=2))
    sys.exit(0 if result.get("status") == "success" else 1)
