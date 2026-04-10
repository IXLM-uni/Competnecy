# -*- coding: utf-8 -*-
"""
Руководство к файлу extract_professions.py
==========================================

Назначение:
    Парсит Professions.html (выгрузку страницы hh.ru/vacancies_by_category) и
    извлекает полный список профессий в CSV-формат:
        Буква;Название профессии;Количество вакансий;Ссылка hh.ru

Структура HTML:
    Каждая строка файла — отдельный <div class="catalog-links..."> с буквой алфавита.
    Внутри — <a class="bloko-link" href="/vacancies/slug">название</a>
    и опционально <span ...>количество</span>.

Использование:
    python Explore/HH/extract_professions.py
    python Explore/HH/extract_professions.py --input info/Professions.html --output output/professions.csv

Выходные файлы:
    output/professions.csv — CSV с разделителем ";"
    Поля: Буква;Название профессии;Количество вакансий;Ссылка hh.ru

ШАГ 1. Загрузка HTML-файла.
ШАГ 2. Парсинг каждой строки (div по буквам алфавита).
ШАГ 3. Извлечение ссылок, названий, количества вакансий.
ШАГ 4. Определение буквы по первому символу названия.
ШАГ 5. Сохранение в CSV.
"""

from __future__ import annotations

import argparse
import csv
import logging
import re
import sys
from pathlib import Path
from typing import Optional

from selectolax.parser import HTMLParser

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
)
logger = logging.getLogger(__name__)

HERE = Path(__file__).resolve().parent
HH_BASE_URL = "https://hh.ru"

CYRILLIC_LETTERS = list("АБВГДЕЁЖЗИЙКЛМНОПРСТУФХЦЧШЩЪЫЬЭЮЯ")
LATIN_LETTERS = list("ABCDEFGHIJKLMNOPQRSTUVWXYZ")


def _normalize_count(raw: str) -> int:
    """
    Конвертирует '3 556' или '45 411' (с nbsp) → int.
    Если не удалось — возвращает 0.
    """
    if not raw:
        return 0
    cleaned = raw.replace("\xa0", "").replace(" ", "").replace(",", "")
    try:
        return int(cleaned)
    except ValueError:
        return 0


def _get_letter(profession_name: str) -> str:
    """
    Определяет первую букву профессии (заглавная).
    Для кириллических названий — кириллическая буква.
    Для латинских — латинская.
    """
    if not profession_name:
        return "?"
    first = profession_name.strip()[0].upper()
    return first


def parse_professions_html(html_content: str) -> list[dict]:
    """
    Парсит HTML-файл страницы с профессиями hh.ru.

    HTML-структура (каждая строка файла = 1 буква алфавита):
        <div class="catalog-links--...">
            <div class="catalog-link--...">
                <a class="bloko-link" href="/vacancies/slug">название</a>
                <span class="bloko-text ...">количество</span>  (опционально)
            </div>
            ...
        </div>

    Returns:
        list[dict] с полями: letter, name, count, url
    """
    logger.info("ШАГ 2. Парсинг HTML, размер=%d байт ...", len(html_content))

    results: list[dict] = []

    # Файл Professions.html — каждая строка содержит один <div> блок с буквой
    # Парсим весь файл целиком через selectolax
    tree = HTMLParser(html_content)

    # Ищем все ссылки-профессии
    all_links = tree.css("a.bloko-link")
    logger.info("ШАГ 2. Найдено ссылок-профессий: %d", len(all_links))

    for link in all_links:
        href = link.attributes.get("href", "")
        if not href.startswith("/vacancies/"):
            continue

        name = link.text(strip=True)
        if not name:
            continue

        # Количество вакансий — в следующем span.bloko-text
        count = 0
        # Ищем sibling span после ссылки (в родительском div)
        parent = link.parent
        if parent:
            spans = parent.css("span.bloko-text")
            for span in spans:
                raw_count = span.text(strip=True)
                candidate = _normalize_count(raw_count)
                if candidate > 0:
                    count = candidate
                    break

        # Полный URL на hh.ru
        full_url = HH_BASE_URL + href

        # Первая буква профессии
        letter = _get_letter(name)

        results.append({
            "letter": letter,
            "name": name,
            "count": count,
            "url": full_url,
        })

    logger.info("ШАГ 2. Распарсено профессий: %d ... УСПЕХ", len(results))
    return results


def deduplicate(professions: list[dict]) -> list[dict]:
    """Удаляет дублирующиеся профессии (по URL). Сортирует: по букве, потом по убыванию count."""
    logger.info("ШАГ 3. Дедупликация %d записей ...", len(professions))
    seen: set[str] = set()
    unique: list[dict] = []
    for p in professions:
        key = p["url"]
        if key not in seen:
            seen.add(key)
            unique.append(p)
    logger.info(
        "ШАГ 3. До дедупликации: %d, после: %d (удалено: %d)",
        len(professions), len(unique), len(professions) - len(unique),
    )
    # Сортировка: по букве, затем по убыванию количества вакансий
    unique.sort(key=lambda x: (x["letter"], -x["count"], x["name"]))
    return unique


def save_csv(professions: list[dict], csv_path: Path) -> None:
    """Сохраняет профессии в CSV с разделителем ';'."""
    logger.info("ШАГ 5. Сохранение CSV → %s (%d записей) ...", csv_path, len(professions))
    csv_path.parent.mkdir(parents=True, exist_ok=True)
    with csv_path.open("w", newline="", encoding="utf-8") as f:
        writer = csv.writer(f, delimiter=";")
        writer.writerow(["Буква", "Название профессии", "Количество вакансий", "Ссылка hh.ru"])
        for p in professions:
            writer.writerow([p["letter"], p["name"], p["count"], p["url"]])
    logger.info("ШАГ 5. CSV сохранён ... УСПЕХ")


def main(input_html: Path, output_csv: Path) -> None:
    """
    ШАГ 1. Загрузка HTML.
    ШАГ 2. Парсинг профессий.
    ШАГ 3. Дедупликация и сортировка.
    ШАГ 4. Статистика.
    ШАГ 5. Сохранение CSV.
    """
    # ШАГ 1. Загрузка
    logger.info("ШАГ 1. Загрузка HTML из %s ...", input_html)
    if not input_html.exists():
        logger.error("ШАГ 1. ОШИБКА: файл не найден: %s", input_html)
        sys.exit(1)
    html_content = input_html.read_text(encoding="utf-8")
    logger.info("ШАГ 1. HTML загружен (%d байт) ... УСПЕХ", len(html_content))

    # ШАГ 2. Парсинг
    professions = parse_professions_html(html_content)

    if not professions:
        logger.error("ШАГ 2. ОШИБКА: профессии не найдены — проверьте HTML-файл")
        sys.exit(1)

    # ШАГ 3. Дедупликация
    professions = deduplicate(professions)

    # ШАГ 4. Статистика
    total_vacancies = sum(p["count"] for p in professions)
    letters_count: dict[str, int] = {}
    for p in professions:
        letters_count[p["letter"]] = letters_count.get(p["letter"], 0) + 1

    logger.info("ШАГ 4. Статистика:")
    logger.info("  Всего профессий:       %d", len(professions))
    logger.info("  Всего вакансий (сумма): %d", total_vacancies)
    logger.info("  Букв алфавита:          %d", len(letters_count))

    top_by_count = sorted(professions, key=lambda x: -x["count"])[:10]
    logger.info("ШАГ 4. Топ-10 по количеству вакансий:")
    for p in top_by_count:
        logger.info("  %s — %s (%d вакансий)", p["letter"], p["name"], p["count"])

    # ШАГ 5. Сохранение
    save_csv(professions, output_csv)

    print(f"\n{'='*60}")
    print(f"Профессий извлечено: {len(professions)}")
    print(f"Всего вакансий (сумма): {total_vacancies:,}")
    print(f"CSV: {output_csv}")
    print(f"{'='*60}\n")
    print(f"Топ-10 профессий по количеству вакансий:")
    for p in top_by_count:
        print(f"  [{p['letter']}] {p['name']:<50} {p['count']:>8,} вакансий")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(
        description="Парсинг hh.ru Professions.html → CSV (Буква;Профессия;Кол-во;Ссылка)"
    )
    parser.add_argument(
        "--input",
        default=str(HERE / "info" / "Professions.html"),
        help="Путь к HTML-файлу (default: info/Professions.html)",
    )
    parser.add_argument(
        "--output",
        default=str(HERE / "output" / "professions.csv"),
        help="Путь к выходному CSV (default: output/professions.csv)",
    )
    args = parser.parse_args()
    main(Path(args.input), Path(args.output))
