# -*- coding: utf-8 -*-
"""
Руководство к файлу professions_to_md.py
=========================================

Назначение:
    Читает CSV-файл professions.csv (выход extract_professions.py)
    и генерирует тонкий текстовый .md-файл только со списком названий профессий
    для скармливания LLM в hh_vacancy_tool.py с минимальным расходом токенов.

Структура выходного MD:
    account manager
    accountant
    administrative specialist
    ...

Использование:
    python Explore/HH/professions_to_md.py
    python Explore/HH/professions_to_md.py --input output/professions.csv --output output/professions.md

ШАГ 1. Загрузка CSV.
ШАГ 2. Подготовка плоского списка названий профессий.
ШАГ 3. Генерация тонкого Markdown.
ШАГ 4. Сохранение .md файла.
"""

from __future__ import annotations

import argparse
import csv
import logging
import sys
from pathlib import Path

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
)
logger = logging.getLogger(__name__)

HERE = Path(__file__).resolve().parent


def load_csv(csv_path: Path) -> list[dict]:
    """Загружает профессии из CSV с разделителем ';'."""
    logger.info("ШАГ 1. Загрузка CSV из %s ...", csv_path)
    if not csv_path.exists():
        logger.error("ШАГ 1. ОШИБКА: файл не найден: %s", csv_path)
        logger.error("Сначала запустите: python Explore/HH/extract_professions.py")
        sys.exit(1)

    rows: list[dict] = []
    with csv_path.open(encoding="utf-8", newline="") as f:
        reader = csv.DictReader(f, delimiter=";")
        for row in reader:
            rows.append({
                "letter": row.get("Буква", "?").strip(),
                "name": row.get("Название профессии", "").strip(),
                "count": int(row.get("Количество вакансий", "0") or "0"),
                "url": row.get("Ссылка hh.ru", "").strip(),
            })

    logger.info("ШАГ 1. Загружено %d записей ... УСПЕХ", len(rows))
    return rows


def group_by_letter(professions: list[dict]) -> dict[str, list[dict]]:
    """Группирует профессии по первой букве (сохраняя порядок букв из данных)."""
    logger.info("ШАГ 2. Группировка %d профессий по буквам ...", len(professions))
    groups: dict[str, list[dict]] = {}
    for p in professions:
        letter = p["letter"]
        if letter not in groups:
            groups[letter] = []
        groups[letter].append(p)

    # Сортируем буквы
    sorted_groups = dict(sorted(groups.items(), key=lambda x: x[0]))
    logger.info("ШАГ 2. Найдено %d уникальных букв ... УСПЕХ", len(sorted_groups))
    return sorted_groups


def generate_markdown(professions: list[dict], groups: dict[str, list[dict]]) -> str:
    """
    Генерирует Markdown-документ для скармливания LLM.
    Формат максимально компактный: только названия профессий,
    по одной строке на запись, без статистики, ссылок и таблиц.
    """
    logger.info("ШАГ 3. Генерация Markdown (%d профессий) ...", len(professions))

    lines = [p["name"] for p in professions if p.get("name")]

    logger.info("ШАГ 3. Markdown сгенерирован (%d строк) ... УСПЕХ", len(lines))
    return "\n".join(lines)


def main(csv_path: Path, md_path: Path) -> None:
    """
    ШАГ 1. Загрузка CSV.
    ШАГ 2. Подготовка плоского списка названий профессий.
    ШАГ 3. Генерация тонкого Markdown.
    ШАГ 4. Сохранение .md.
    """
    # ШАГ 1-2
    professions = load_csv(csv_path)
    groups = group_by_letter(professions)

    # ШАГ 3
    markdown = generate_markdown(professions, groups)

    # ШАГ 4
    logger.info("ШАГ 4. Сохранение MD → %s ...", md_path)
    md_path.parent.mkdir(parents=True, exist_ok=True)
    md_path.write_text(markdown, encoding="utf-8")
    logger.info("ШАГ 4. MD сохранён (%d байт) ... УСПЕХ", len(markdown.encode()))

    print(f"\n{'='*60}")
    print(f"Markdown сгенерирован:")
    print(f"  Профессий: {len(professions)}")
    print(f"  Файл:      {md_path}")
    print(f"  Размер:    {len(markdown.encode()):,} байт")
    print(f"{'='*60}\n")
    print("Используйте этот тонкий список названий как контекст для LLM в hh_vacancy_tool.py")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(
        description="Конвертация professions.csv → professions.md для LLM"
    )
    parser.add_argument(
        "--input",
        default=str(HERE / "output" / "professions.csv"),
        help="Путь к CSV-файлу (default: output/professions.csv)",
    )
    parser.add_argument(
        "--output",
        default=str(HERE / "output" / "professions.md"),
        help="Путь к выходному MD-файлу (default: output/professions.md)",
    )
    args = parser.parse_args()
    main(Path(args.input), Path(args.output))
