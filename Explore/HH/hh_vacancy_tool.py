# -*- coding: utf-8 -*-
"""
Руководство к файлу hh_vacancy_tool.py
=======================================
 
Назначение:
    Инструмент поиска вакансий на hh.ru через субагентный подход (без RAG, без Qdrant).
    
    Алгоритм:
      1. LLM читает тонкий список названий профессий из professions.md и выбирает топ-10 наиболее
         релевантных для заданного запроса/темы компетенций.
      2. Код восстанавливает url и count выбранных профессий из professions.csv.
      3. Для каждой из 10 профессий выполняется парсинг страницы hh.ru/vacancies/<slug>
         через crawler4ai (получаем список топ вакансий на странице).
      4. По каждой профессии берём топ-10 вакансий из списка, переходим по ссылкам
         и парсим содержание каждой вакансии через crawler4ai.
      5. Сохраняем все вакансии в .md файлы (по одному на профессию).

Использование:
    python Explore/HH/hh_vacancy_tool.py --query "data scientist machine learning"
    python Explore/HH/hh_vacancy_tool.py --query "Python разработчик" --top-professions 5

Переменные окружения (из Global_services/.env):
    CLOUDRU_API_KEY     — API ключ Cloud.ru
    CLOUDRU_BASE_URL    — базовый URL Cloud.ru API
    CLOUDRU_MODEL_NAME  — модель LLM (Qwen/Qwen3-Coder-Next)
    CRAWLER_BASE_URL    — URL Crawler4AI (http://localhost:11235)

Выходные файлы:
    output/hh_vacancies/<profession_slug>_vacancies.md  — вакансии по профессии

ШАГ 1. Загрузка тонкого professions.md как контекст LLM.
ШАГ 2. Загрузка professions.csv как source-of-truth для url/count.
ШАГ 3. LLM выбирает топ-10 профессий по названиям.
ШАГ 4. Краулинг страницы списка вакансий по профессии.
ШАГ 5. Извлечение топ-10 ссылок на вакансии.
ШАГ 6. Краулинг каждой вакансии.
ШАГ 7. Сохранение в .md.
"""

from __future__ import annotations

import argparse
import asyncio
import csv
import json
import logging
import os
import re
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional
from urllib.parse import urlparse

try:
    from dotenv import load_dotenv
except ImportError:
    def load_dotenv(*a, **kw): pass

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
)
logger = logging.getLogger(__name__)

HERE = Path(__file__).resolve().parent
ROOT = HERE.parent.parent
GLOBAL_SERVICES = ROOT / "Global_services"

_root_env_path = ROOT / ".env"
_global_env_path = GLOBAL_SERVICES / ".env"
if _root_env_path.exists():
    load_dotenv(_root_env_path)
    logger.info("ШАГ 0. .env загружен из %s", _root_env_path)
elif _global_env_path.exists():
    load_dotenv(_global_env_path)
    logger.info("ШАГ 0. .env загружен из %s", _global_env_path)

for p in (ROOT, GLOBAL_SERVICES):
    s = str(p)
    if s not in sys.path:
        sys.path.insert(0, s)

HH_BASE = "https://hh.ru"
TOP_PROFESSIONS_DEFAULT = 10
TOP_VACANCIES_PER_PROFESSION = 10
CRAWL_DELAY = 1.5  # секунды между запросами краулера


# ---------------------------------------------------------------------------
# Вспомогательная функция: запрос через Crawler4AI
# ---------------------------------------------------------------------------

async def crawl_url(url: str, crawler_base_url: str, timeout: float = 60.0) -> Optional[str]:
    """
    Краулит URL через Crawler4AI и возвращает markdown-содержимое страницы.
    При ошибке возвращает None.
    """
    endpoint = crawler_base_url.rstrip("/") + "/crawl"
    payload = {
        "urls": [url],
        "priority": 10,
        "extra": {
            "magic": True,
            "scan_full_page": True,
            "exclude_external_links": True,
            "exclude_social_media_links": True,
            "return_format": "fit_markdown",
        },
    }

    logger.info("  Краулинг: %s ...", url)
    try:
        async with httpx.AsyncClient(timeout=timeout + 10) as client:
            resp = await client.post(endpoint, json=payload)
            resp.raise_for_status()
            data = resp.json()

        # Извлекаем fit_markdown или fallback text
        results = data.get("results", [])
        if not results:
            logger.warning("  Краулер вернул пустой results для %s", url)
            return None

        result = results[0]
        content = (
            result.get("fit_markdown")
            or result.get("markdown")
            or result.get("text", "")
        )
        if not content:
            logger.warning("  Нет контента для %s", url)
            return None

        logger.info("  Краулинг %s: %d символов ... УСПЕХ", url, len(content))
        return content

    except Exception as exc:
        logger.error("  Ошибка краулинга %s: %s", url, exc)
        return None


# ---------------------------------------------------------------------------
# LLM: выбор топ профессий
# ---------------------------------------------------------------------------

def load_professions_lookup(csv_path: Path) -> dict[str, dict]:
    """
    Загружает professions.csv и строит lookup по точному названию профессии.
    CSV является source-of-truth для url и count.
    """
    logger.info("ШАГ 2. Загрузка professions.csv из %s ...", csv_path)

    if not csv_path.exists():
        logger.error("ШАГ 2. ОШИБКА: professions.csv не найден: %s", csv_path)
        sys.exit(1)

    lookup: dict[str, dict] = {}
    with csv_path.open(encoding="utf-8", newline="") as f:
        reader = csv.DictReader(f, delimiter=";")
        for row in reader:
            name = (row.get("Название профессии") or "").strip()
            if not name:
                continue
            lookup[name] = {
                "name": name,
                "url": (row.get("Ссылка hh.ru") or "").strip(),
                "count": int((row.get("Количество вакансий") or "0").strip() or "0"),
            }

    logger.info("ШАГ 2. professions.csv загружен: %d профессий ... УСПЕХ", len(lookup))
    return lookup


def extract_profession_names_from_md(professions_md: str) -> list[str]:
    """
    Извлекает названия профессий из тонкого professions.md.
    Формат: одна строка = одно название профессии.
    """
    names = [line.strip() for line in professions_md.splitlines() if line.strip()]
    logger.info("ШАГ 1. Извлечено названий профессий из professions.md: %d ... УСПЕХ", len(names))
    return names


def enrich_selected_professions(selected: list[dict], professions_lookup: dict[str, dict]) -> list[dict]:
    """
    Дополняет выбранные LLM профессии данными из professions.csv.
    """
    logger.info("ШАГ 3.1. Обогащение выбранных профессий данными из professions.csv ...")
    enriched: list[dict] = []

    for item in selected:
        name = (item.get("name") or "").strip()
        if not name:
            continue

        source = professions_lookup.get(name)
        if not source:
            logger.warning("ШАГ 3.1. Профессия не найдена в CSV source-of-truth: %r", name)
            continue

        enriched.append({
            "name": source["name"],
            "url": source["url"],
            "count": source["count"],
            "reason": (item.get("reason") or "").strip(),
        })

    logger.info("ШАГ 3.1. Обогащено профессий: %d ... УСПЕХ", len(enriched))
    return enriched


async def llm_select_top_professions(
    query: str,
    profession_names: list[str],
    api_key: str,
    base_url: str,
    model_name: str,
    top_n: int = 10,
) -> list[dict]:
    """
    Субагент: LLM читает список названий профессий и выбирает топ-N наиболее
    релевантных для заданного запроса.
    
    Возвращает список dict с полями: name, reason.
    """
    import openai

    logger.info("ШАГ 3. LLM субагент: выбор топ-%d профессий для запроса: %r ...", top_n, query)

    system_prompt = f"""Ты — эксперт по рынку труда и компетенциям.
    Твоя задача: на основе запроса пользователя выбрать топ-{top_n} наиболее релевантных
    профессий из предоставленного справочника hh.ru.

    ПРАВИЛА:
    1. Выбирай профессии, максимально соответствующие запросу.
    2. Включай смежные профессии, если они релевантны.
    3. Используй только точные названия из списка.
    4. Возвращай ТОЛЬКО JSON-массив без markdown-обёртки.

    Формат ответа (строго JSON массив):
    [
      {{
        "name": "точное название профессии из справочника",
        "reason": "краткое объяснение релевантности"
      }},
      ...
    ]"""

    professions_context = "\n".join(profession_names)

    user_message = f"""ЗАПРОС: {query}

СПИСОК ПРОФЕССИЙ HH.RU:
    {professions_context}

    Выбери топ-{top_n} профессий наиболее релевантных для запроса "{query}".
    Верни строго JSON массив."""

    client = openai.AsyncOpenAI(api_key=api_key, base_url=base_url)

    try:
        response = await client.chat.completions.create(
            model=model_name,
            messages=[
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_message},
            ],
            temperature=0.1,
            max_tokens=2048,
        )
        raw_content = response.choices[0].message.content.strip()
        logger.info("ШАГ 3. LLM ответ получен (%d символов)", len(raw_content))

        # Извлекаем JSON из ответа
        json_match = re.search(r"\[.*\]", raw_content, re.DOTALL)
        if json_match:
            raw_content = json_match.group(0)

        selected = json.loads(raw_content)
        logger.info("ШАГ 3. LLM выбрал %d профессий ... УСПЕХ", len(selected))

        for i, p in enumerate(selected, 1):
            logger.info(
                "ШАГ 3.  %d. %s: %s",
                i, p.get("name", "?"), p.get("reason", ""),
            )

        return selected[:top_n]

    except Exception as exc:
        logger.error("ШАГ 3. ОШИБКА LLM: %s", exc)
        return []


# ---------------------------------------------------------------------------
# HH.ru: извлечение ссылок на вакансии из страницы списка
# ---------------------------------------------------------------------------

def extract_vacancy_links_from_md(md_content: str, profession_url: str, limit: int = 10) -> list[str]:
    """
    Из Markdown-содержимого страницы hh.ru/vacancies/<slug>
    извлекает ссылки на отдельные вакансии (hh.ru/vacancy/<id>).
    """
    # Ищем ссылки вида https://hh.ru/vacancy/123456789
    links = re.findall(r"https://hh\.ru/vacancy/\d+", md_content)
    # Также ищем относительные /vacancy/
    relative = re.findall(r"/vacancy/(\d+)", md_content)
    for vid in relative:
        links.append(f"https://hh.ru/vacancy/{vid}")

    # Дедупликация с сохранением порядка
    seen: set[str] = set()
    unique_links: list[str] = []
    for link in links:
        # Нормализуем — убираем query params
        clean = re.match(r"(https://hh\.ru/vacancy/\d+)", link)
        if clean:
            clean_url = clean.group(1)
            if clean_url not in seen:
                seen.add(clean_url)
                unique_links.append(clean_url)

    logger.info(
        "    Найдено ссылок на вакансии: %d (берём топ-%d)",
        len(unique_links), limit,
    )
    return unique_links[:limit]


# ---------------------------------------------------------------------------
# Краулинг и сохранение вакансий по профессии
# ---------------------------------------------------------------------------

async def process_profession(
    profession: dict,
    crawler_base_url: str,
    output_dir: Path,
) -> dict:
    """
    Полный цикл обработки одной профессии:
    ШАГ 3. Краулинг страницы списка вакансий.
    ШАГ 4. Извлечение топ-10 ссылок на вакансии.
    ШАГ 5. Краулинг каждой вакансии.
    ШАГ 6. Сохранение в .md.
    """
    prof_name = profession.get("name", "unknown")
    prof_url = profession.get("url", "")

    if not prof_url:
        logger.warning("  Нет URL для профессии: %s — пропуск", prof_name)
        return {"profession": prof_name, "vacancies_found": 0, "status": "no_url"}

    logger.info("=" * 60)
    logger.info("ПРОФЕССИЯ: %s", prof_name)
    logger.info("URL:       %s", prof_url)

    # ШАГ 3. Краулим страницу со списком вакансий
    logger.info("ШАГ 4. Краулинг страницы со списком вакансий: %s ...", prof_url)
    await asyncio.sleep(CRAWL_DELAY)
    list_md = await crawl_url(prof_url, crawler_base_url)

    if not list_md:
        logger.warning("ШАГ 4. Не удалось получить страницу: %s", prof_url)
        return {"profession": prof_name, "vacancies_found": 0, "status": "crawl_failed"}

    # ШАГ 4. Извлекаем ссылки на вакансии
    logger.info("ШАГ 5. Извлечение ссылок на топ-%d вакансий ...", TOP_VACANCIES_PER_PROFESSION)
    vacancy_links = extract_vacancy_links_from_md(list_md, prof_url, limit=TOP_VACANCIES_PER_PROFESSION)

    if not vacancy_links:
        logger.warning("ШАГ 5. Ссылки на вакансии не найдены в: %s", prof_url)
        return {"profession": prof_name, "vacancies_found": 0, "status": "no_vacancy_links"}

    logger.info("ШАГ 5. Найдено %d ссылок на вакансии ... УСПЕХ", len(vacancy_links))

    # ШАГ 5. Краулим каждую вакансию
    logger.info("ШАГ 6. Краулинг %d вакансий по профессии '%s' ...", len(vacancy_links), prof_name)

    vacancies_data: list[dict] = []
    for idx, vac_url in enumerate(vacancy_links, 1):
        logger.info("  ШАГ 6.%d. Краулинг вакансии %d/%d: %s ...", idx, idx, len(vacancy_links), vac_url)
        await asyncio.sleep(CRAWL_DELAY)
        vac_content = await crawl_url(vac_url, crawler_base_url)

        if not vac_content:
            logger.warning("  ШАГ 6.%d. Не удалось получить вакансию: %s", idx, vac_url)
            continue

        # Извлекаем ID вакансии из URL
        vac_id_match = re.search(r"/vacancy/(\d+)", vac_url)
        vac_id = vac_id_match.group(1) if vac_id_match else str(idx)

        vacancies_data.append({
            "id": vac_id,
            "url": vac_url,
            "content": vac_content,
        })
        logger.info("  ШАГ 6.%d. Вакансия %s: %d символов ... УСПЕХ", idx, vac_id, len(vac_content))

    if not vacancies_data:
        logger.warning("ШАГ 6. Нет данных по вакансиям для: %s", prof_name)
        return {"profession": prof_name, "vacancies_found": 0, "status": "all_crawls_failed"}

    # ШАГ 6. Сохранение в .md
    logger.info("ШАГ 7. Сохранение %d вакансий в MD ...", len(vacancies_data))

    # Slug для имени файла
    slug = re.sub(r"[^\w\-]", "_", prof_name.lower().strip())
    slug = re.sub(r"_+", "_", slug)[:60]

    md_lines: list[str] = []
    md_lines.append(f"# Вакансии: {prof_name}")
    md_lines.append("")
    md_lines.append(f"**Профессия:** [{prof_name}]({prof_url})")
    md_lines.append(f"**Вакансий на странице:** {len(vacancy_links)}")
    md_lines.append(f"**Вакансий спарсено:** {len(vacancies_data)}")
    md_lines.append(f"**Дата сбора:** {datetime.now(timezone.utc).strftime('%Y-%m-%d %H:%M UTC')}")
    if profession.get("reason"):
        md_lines.append(f"**Релевантность:** {profession['reason']}")
    md_lines.append("")
    md_lines.append("---")
    md_lines.append("")

    for vac in vacancies_data:
        md_lines.append(f"## Вакансия {vac['id']}")
        md_lines.append("")
        md_lines.append(f"**URL:** {vac['url']}")
        md_lines.append("")
        md_lines.append(vac["content"])
        md_lines.append("")
        md_lines.append("---")
        md_lines.append("")

    md_content = "\n".join(md_lines)
    md_filename = f"{slug}_vacancies.md"
    md_path = output_dir / md_filename

    md_path.write_text(md_content, encoding="utf-8")
    logger.info("ШАГ 7. Сохранено → %s (%d байт) ... УСПЕХ", md_path, len(md_content.encode()))

    return {
        "profession": prof_name,
        "vacancies_found": len(vacancies_data),
        "md_file": str(md_path),
        "status": "ok",
    }


# ---------------------------------------------------------------------------
# Главный оркестратор
# ---------------------------------------------------------------------------

async def main(
    query: str,
    professions_md_path: Path,
    output_dir: Path,
    top_professions: int,
) -> None:
    """
    Главный оркестратор поиска вакансий на hh.ru.

    ШАГ 0. Загрузка конфигурации.
    ШАГ 1. Загрузка professions.md.
    ШАГ 2. Загрузка professions.csv.
    ШАГ 3. LLM выбирает топ-N профессий.
    ШАГ 4-7. Для каждой профессии: краулинг → парсинг → сохранение.
    ШАГ 8. Сохранение отчёта.
    """
    # ШАГ 0. Конфигурация
    api_key = os.getenv("CLOUDRU_API_KEY", "")
    base_url = os.getenv("CLOUDRU_BASE_URL", "https://foundation-models.api.cloud.ru/v1")
    model_name = os.getenv("CLOUDRU_MODEL_NAME", "Qwen/Qwen3-Coder-Next")
    crawler_base_url = os.getenv("CRAWLER_BASE_URL", "http://localhost:11235")

    logger.info("ШАГ 0. Конфигурация:")
    logger.info("  query=%r", query)
    logger.info("  model=%s", model_name)
    logger.info("  crawler=%s", crawler_base_url)
    logger.info("  top_professions=%d", top_professions)

    if not api_key:
        logger.error("ШАГ 0. ОШИБКА: CLOUDRU_API_KEY не задан в .env")
        sys.exit(1)

    output_dir.mkdir(parents=True, exist_ok=True)

    # ШАГ 1. Загрузка professions.md
    logger.info("ШАГ 1. Загрузка professions.md из %s ...", professions_md_path)

    if not professions_md_path.exists():
        logger.error(
            "ШАГ 1. ОШИБКА: файл не найден: %s",
            professions_md_path,
        )
        logger.error(
            "Запустите сначала:\n"
            "  python Explore/HH/extract_professions.py\n"
            "  python Explore/HH/professions_to_md.py"
        )
        sys.exit(1)

    professions_md = professions_md_path.read_text(encoding="utf-8")
    logger.info("ШАГ 1. professions.md загружен (%d байт) ... УСПЕХ", len(professions_md.encode()))
    profession_names = extract_profession_names_from_md(professions_md)

    professions_csv_path = professions_md_path.with_suffix(".csv")
    professions_lookup = load_professions_lookup(professions_csv_path)

    # ШАГ 3. LLM выбирает топ профессий
    selected_names = await llm_select_top_professions(
        query=query,
        profession_names=profession_names,
        api_key=api_key,
        base_url=base_url,
        model_name=model_name,
        top_n=top_professions,
    )
    selected_professions = enrich_selected_professions(selected_names, professions_lookup)

    if not selected_professions:
        logger.error("ШАГ 3. ОШИБКА: LLM не выбрал ни одной профессии")
        sys.exit(1)

    logger.info("ШАГ 3. Выбрано %d профессий ... УСПЕХ", len(selected_professions))

    # ШАГ 4-7. Обработка каждой профессии последовательно
    reports: list[dict] = []
    for idx, prof in enumerate(selected_professions, 1):
        logger.info(
            "\n[%d/%d] Обработка профессии: %s",
            idx, len(selected_professions), prof.get("name", "?"),
        )
        try:
            report = await process_profession(
                profession=prof,
                crawler_base_url=crawler_base_url,
                output_dir=output_dir,
            )
        except Exception as exc:
            logger.error("[%d/%d] ОШИБКА: %s", idx, len(selected_professions), exc)
            report = {
                "profession": prof.get("name", "?"),
                "vacancies_found": 0,
                "status": f"error: {exc}",
            }
        reports.append(report)

    # ШАГ 8. Сохранение отчёта
    logger.info("\nШАГ 8. Сохранение отчёта ...")
    ts = datetime.now().strftime("%Y%m%d_%H%M%S")
    report_data = {
        "query": query,
        "top_professions": top_professions,
        "model": model_name,
        "created_at": datetime.now(timezone.utc).isoformat(),
        "selected_professions": selected_professions,
        "results": reports,
    }
    report_path = output_dir / f"hh_report_{ts}.json"
    report_path.write_text(json.dumps(report_data, ensure_ascii=False, indent=2), encoding="utf-8")
    logger.info("ШАГ 8. Отчёт → %s ... УСПЕХ", report_path)

    # Итоговый вывод
    print(f"\n{'='*60}")
    print(f"HH.RU VACANCY TOOL — ЗАВЕРШЕНО")
    print(f"  Запрос:          {query}")
    print(f"  Профессий:       {len(selected_professions)}")
    total_vac = sum(r.get("vacancies_found", 0) for r in reports)
    print(f"  Вакансий собрано: {total_vac}")
    print(f"  Отчёт:           {report_path}")
    print(f"\nМД-файлы вакансий:")
    for r in reports:
        status_str = "✓" if r["status"] == "ok" else "✗"
        print(f"  {status_str} {r['profession']}: {r.get('vacancies_found', 0)} вакансий")
        if r.get("md_file"):
            print(f"    → {r['md_file']}")
    print(f"{'='*60}\n")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(
        description="HH.ru Vacancy Tool: LLM → топ профессий → crawler4ai → .md"
    )
    parser.add_argument(
        "--query",
        required=True,
        help="Запрос / тема компетенций (например: 'Python разработчик ML')",
    )
    parser.add_argument(
        "--professions-md",
        default=str(HERE / "output" / "professions.md"),
        help="Путь к файлу professions.md (default: output/professions.md)",
    )
    parser.add_argument(
        "--output-dir",
        default=str(HERE / "output" / "hh_vacancies"),
        help="Директория для сохранения результатов (default: output/hh_vacancies/)",
    )
    parser.add_argument(
        "--top-professions",
        type=int,
        default=TOP_PROFESSIONS_DEFAULT,
        help=f"Сколько профессий выбирать (default: {TOP_PROFESSIONS_DEFAULT})",
    )
    args = parser.parse_args()

    asyncio.run(
        main(
            query=args.query,
            professions_md_path=Path(args.professions_md),
            output_dir=Path(args.output_dir),
            top_professions=args.top_professions,
        )
    )
