# -*- coding: utf-8 -*-
"""
Руководство к файлу parse_tgstat_vacancies.py
==============================================

Назначение:
    Парсит HTML-файлы TGStat с подборками вакансий:
      - Vacancies.html   (каналы с вакансиями)
      - Vacancies_chats.html (чаты с вакансиями)
    Извлекает: username (@), название канала/чата, подписчики/участники,
    описание, tgstat-ссылку.
    Сохраняет объединённый список в JSON и CSV.

Использование:
    python Explore/TGStat/parse_tgstat_vacancies.py
    python Explore/TGStat/parse_tgstat_vacancies.py --output-dir Explore/TGStat/output

Выходные файлы:
    output/vacancy_channels.json  — полный список (каналы + чаты)
    output/vacancy_channels.csv   — то же в CSV (для просмотра)

ШАГ 1. Загрузка HTML-файлов с диска.
ШАГ 2. Парсинг карточек каналов (peer-item-box).
ШАГ 3. Извлечение username из tgstat.ru-ссылки.
ШАГ 4. Сохранение JSON + CSV.
"""

from __future__ import annotations

import argparse
import csv
import json
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
INFO_DIR = HERE / "info"


# ---------------------------------------------------------------------------
# Парсинг одной HTML-страницы TGStat (channels или chats)
# ---------------------------------------------------------------------------

def _parse_subscribers(text: str) -> int:
    """Конвертирует '804 685' или '1.2K' → int."""
    text = text.replace("\xa0", "").replace(" ", "").replace(",", ".")
    m = re.match(r"^([0-9]+(?:\.[0-9]+)?)([KkMm])?$", text)
    if m:
        num = float(m.group(1))
        suffix = m.group(2)
        if suffix in ("K", "k"):
            num *= 1_000
        elif suffix in ("M", "m"):
            num *= 1_000_000
        return int(num)
    try:
        return int(re.sub(r"\D", "", text))
    except Exception:
        return 0


def _extract_username_from_tgstat(href: str) -> Optional[str]:
    """
    Извлекает username из ссылок вида:
      https://tgstat.ru/channel/@theyseeku  → theyseeku
      https://tgstat.ru/channel/AAAAAEfAkeKlY2M0_yzGyg → None (это хеш, не username)
      https://tgstat.ru/chat/@vacancy_ru → vacancy_ru
    """
    m = re.search(r"/(?:channel|chat)/@([A-Za-z0-9_]+)", href)
    if m:
        return m.group(1)
    return None


def parse_tgstat_html(html_content: str, peer_type: str = "channel") -> list[dict]:
    """
    Парсит HTML-страницу TGStat и возвращает список карточек.
    
    Args:
        html_content: сырой HTML
        peer_type: "channel" или "chat" — тип карточек (влияет на ярлык участников)
    
    Returns:
        list[dict] с полями: username, name, description, subscribers, tgstat_url, peer_type
    """
    logger.info("ШАГ 2. Парсинг HTML (%s), размер=%d байт ...", peer_type, len(html_content))
    tree = HTMLParser(html_content)
    
    results: list[dict] = []
    
    # Все карточки в списке — блок .peer-item-box
    cards = tree.css(".peer-item-box")
    logger.info("ШАГ 2. Найдено карточек: %d", len(cards))
    
    for card in cards:
        # Ссылка на tgstat-страницу канала/чата
        link_el = card.css_first("a.text-body")
        if link_el is None:
            continue
        tgstat_href = link_el.attributes.get("href", "")
        
        # Название
        name_el = card.css_first(".font-16.text-dark")
        name = name_el.text(strip=True) if name_el else ""
        
        # Описание
        desc_el = card.css_first(".font-14.text-muted")
        description = desc_el.text(strip=True) if desc_el else ""
        
        # Подписчики / участники — ищем в .font-12.text-truncate
        subs = 0
        for el in card.css(".font-12.text-truncate"):
            raw = el.text(strip=True)
            nums = re.findall(r"[\d\xa0 ]+", raw)
            for n in nums:
                candidate = _parse_subscribers(n)
                if candidate > 0:
                    subs = candidate
                    break
        
        # Username из tgstat-ссылки
        username = _extract_username_from_tgstat(tgstat_href)
        
        if not username:
            logger.debug("ШАГ 2. Пропуск карточки (нет username): href=%s name=%r", tgstat_href, name)
            continue
        
        results.append({
            "username": username,
            "tg_url": f"https://t.me/s/{username}",
            "name": name,
            "description": description,
            "subscribers": subs,
            "tgstat_url": tgstat_href,
            "peer_type": peer_type,
        })
        logger.debug("ШАГ 2. Добавлен @%s (%s), subs=%d", username, name, subs)
    
    logger.info("ШАГ 2. Успешно распарсено: %d записей из %d карточек", len(results), len(cards))
    return results


# ---------------------------------------------------------------------------
# Главный сценарий
# ---------------------------------------------------------------------------

def main(output_dir: Path) -> None:
    """
    ШАГ 1. Загрузка HTML-файлов.
    ШАГ 2. Парсинг карточек каналов + чатов.
    ШАГ 3. Дедупликация по username.
    ШАГ 4. Сохранение JSON + CSV.
    """
    output_dir.mkdir(parents=True, exist_ok=True)
    
    # ШАГ 1. Загрузка
    vacancies_html_path = INFO_DIR / "Vacancies.html"
    chats_html_path = INFO_DIR / "Vacancies_chats.html"
    
    logger.info("ШАГ 1. Загрузка HTML-файлов из %s ...", INFO_DIR)
    
    if not vacancies_html_path.exists():
        logger.error("ШАГ 1. ОШИБКА: файл не найден: %s", vacancies_html_path)
        sys.exit(1)
    
    vacancies_html = vacancies_html_path.read_text(encoding="utf-8")
    logger.info("ШАГ 1. Vacancies.html загружен (%d байт) ... УСПЕХ", len(vacancies_html))
    
    chats_html = ""
    if chats_html_path.exists():
        chats_html = chats_html_path.read_text(encoding="utf-8")
        logger.info("ШАГ 1. Vacancies_chats.html загружен (%d байт) ... УСПЕХ", len(chats_html))
    else:
        logger.warning("ШАГ 1. Vacancies_chats.html не найден — пропускаем чаты")
    
    # ШАГ 2. Парсинг
    logger.info("ШАГ 2. Парсинг каналов (Vacancies.html) ...")
    channels = parse_tgstat_html(vacancies_html, peer_type="channel")
    
    chats: list[dict] = []
    if chats_html:
        logger.info("ШАГ 2. Парсинг чатов (Vacancies_chats.html) ...")
        chats = parse_tgstat_html(chats_html, peer_type="chat")
    
    all_entries = channels + chats
    logger.info(
        "ШАГ 2. Итого: каналов=%d, чатов=%d, всего=%d",
        len(channels), len(chats), len(all_entries),
    )
    
    # ШАГ 3. Дедупликация по username
    logger.info("ШАГ 3. Дедупликация по username ...")
    seen: set[str] = set()
    unique: list[dict] = []
    for entry in all_entries:
        key = entry["username"].lower()
        if key not in seen:
            seen.add(key)
            unique.append(entry)
    
    logger.info(
        "ШАГ 3. До дедупликации: %d, после: %d (удалено дублей: %d)",
        len(all_entries), len(unique), len(all_entries) - len(unique),
    )
    
    # ШАГ 4. Сохранение
    json_path = output_dir / "vacancy_channels.json"
    csv_path = output_dir / "vacancy_channels.csv"
    
    logger.info("ШАГ 4. Сохранение JSON → %s ...", json_path)
    json_path.write_text(
        json.dumps(unique, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    
    logger.info("ШАГ 4. Сохранение CSV → %s ...", csv_path)
    with csv_path.open("w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(
            f,
            fieldnames=["username", "tg_url", "name", "description", "subscribers", "tgstat_url", "peer_type"],
            delimiter=";",
        )
        writer.writeheader()
        writer.writerows(unique)
    
    logger.info(
        "ШАГ 4. ГОТОВО. Сохранено %d записей → %s | %s",
        len(unique), json_path, csv_path,
    )
    
    # Краткая статистика
    print(f"\n{'='*60}")
    print(f"Найдено каналов/чатов с вакансиями: {len(unique)}")
    print(f"  Каналы: {len(channels)}")
    print(f"  Чаты:   {len(chats)}")
    print(f"\nТоп-10 по подписчикам:")
    for e in sorted(unique, key=lambda x: x['subscribers'], reverse=True)[:10]:
        print(f"  @{e['username']:<30} {e['subscribers']:>8,} | {e['name']}")
    print(f"{'='*60}\n")
    print(f"JSON: {json_path}")
    print(f"CSV:  {csv_path}")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(
        description="Парсинг TGStat Vacancies HTML → список каналов/чатов"
    )
    parser.add_argument(
        "--output-dir",
        default=str(HERE / "output"),
        help="Директория для сохранения результатов (по умолчанию: Explore/TGStat/output/)",
    )
    args = parser.parse_args()
    main(Path(args.output_dir))
