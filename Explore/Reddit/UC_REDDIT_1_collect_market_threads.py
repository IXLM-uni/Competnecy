# -*- coding: utf-8 -*-
"""
Руководство к файлу UC_REDDIT_1_collect_market_threads.py
=========================================================

Назначение:
    UC-style entrypoint для Reddit исследования рынка вакансий.
    Основной источник данных Reddit:
      публичные `.json` endpoints без OAuth.
    Сценарий:
      1. LLM генерирует поисковые запросы под тему компетенции
      2. Выполняется поиск тредов Reddit
      3. Для каждого треда извлекаются топ-3 комментария
      4. Сохраняются .md и raw .json артефакты
      5. Формируется JSON-отчёт use-case

Использование:
    python Explore/Reddit/UC_REDDIT_1_collect_market_threads.py --query "Python developer machine learning"

ШАГ 1. Проверка аргументов и выходной директории.
ШАГ 2. Запуск reddit_vacancy_tool.main().
ШАГ 3. Поиск созданных артефактов .md/.json.
ШАГ 4. Сохранение JSON-отчёта UC.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import logging
import re
import sys
from pathlib import Path
from typing import Any, Dict

SCRIPT_DIR = Path(__file__).parent.absolute()
ROOT_DIR = SCRIPT_DIR.parent.parent

if str(ROOT_DIR) not in sys.path:
    sys.path.insert(0, str(ROOT_DIR))

from Explore.Reddit.reddit_vacancy_tool import main as reddit_main

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s | %(levelname)-7s | %(name)s | %(message)s",
)
logger = logging.getLogger(__name__)


async def main(
    query: str,
    output_dir: str,
    subreddits: list[str],
    top_posts: int,
    top_comments: int,
    use_global_search: bool,
) -> Dict[str, Any]:
    logger.info("=" * 80)
    logger.info("UC-REDDIT-1: LLM → Reddit threads → top comments → markdown")
    logger.info("=" * 80)

    out_dir = Path(output_dir)
    report_path = out_dir / "uc_reddit_1_report.json"
    out_dir.mkdir(parents=True, exist_ok=True)

    logger.info("ШАГ 1. Подготовка параметров: query=%r, subreddits=%s", query, subreddits)

    logger.info("ШАГ 2. Запускаем reddit_vacancy_tool.main() — ОТПРАВЛЯЕМ")
    await reddit_main(
        user_query=query,
        output_dir=out_dir,
        subreddits=subreddits,
        top_posts=top_posts,
        top_comments=top_comments,
        use_global_search=use_global_search,
    )
    logger.info("ШАГ 2. Reddit сбор завершён — УСПЕХ")

    logger.info("ШАГ 3. Ищем созданные артефакты в %s", out_dir)
    safe_slug = re.sub(r"[^\w\-]", "_", query.lower().strip())
    safe_slug = re.sub(r"_+", "_", safe_slug)[:50]
    md_files = sorted(str(p) for p in out_dir.glob(f"{safe_slug}_reddit_*.md"))
    json_files = sorted(str(p) for p in out_dir.glob(f"{safe_slug}_reddit_*_raw.json"))
    logger.info("ШАГ 3. Найдено md=%d, json=%d", len(md_files), len(json_files))

    result: Dict[str, Any] = {
        "status": "success",
        "uc": "UC-REDDIT-1",
        "query": query,
        "output_dir": str(out_dir),
        "subreddits": subreddits,
        "top_posts": top_posts,
        "top_comments": top_comments,
        "use_global_search": use_global_search,
        "markdown_files": md_files,
        "raw_json_files": json_files,
    }

    logger.info("ШАГ 4. Сохраняем JSON-отчёт: %s", report_path)
    report_path.write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
    logger.info("ШАГ 4. JSON-отчёт сохранён — УСПЕХ")
    return result


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="UC-REDDIT-1: Reddit исследование рынка вакансий")
    parser.add_argument("--query", required=True, help="Тема / компетенция")
    parser.add_argument(
        "--output-dir",
        default=str(SCRIPT_DIR / "output"),
        help="Директория результата",
    )
    parser.add_argument(
        "--subreddits",
        default="cscareerquestions,jobs,remotework,ExperiencedDevs,datascience,MachineLearning,jobsearch,forhire",
        help="Список subreddits через запятую",
    )
    parser.add_argument("--top-posts", type=int, default=5, help="Топ постов на запрос")
    parser.add_argument("--top-comments", type=int, default=3, help="Топ комментариев на пост")
    parser.add_argument("--no-global-search", action="store_true", help="Отключить глобальный поиск")
    return parser.parse_args()


if __name__ == "__main__":
    args = parse_args()
    subreddits = [item.strip() for item in args.subreddits.split(",") if item.strip()]
    result = asyncio.run(
        main(
            query=args.query,
            output_dir=args.output_dir,
            subreddits=subreddits,
            top_posts=args.top_posts,
            top_comments=args.top_comments,
            use_global_search=not args.no_global_search,
        )
    )

    print("\n" + "=" * 80)
    print("UC-REDDIT-1: REDDIT RESEARCH ЗАВЕРШЁН")
    print("=" * 80)
    print(json.dumps(result, ensure_ascii=False, indent=2))
    sys.exit(0 if result.get("status") == "success" else 1)
