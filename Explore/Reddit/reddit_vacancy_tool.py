# -*- coding: utf-8 -*-
"""
Руководство к файлу reddit_vacancy_tool.py
===========================================

Назначение:
    Инструмент исследования вакансий и рынка труда через Reddit.
    Не использует RAG и Qdrant — весь контекст передаётся напрямую в LLM.
    Базовый источник данных Reddit:
        публичные `.json` endpoints без OAuth и без обязательной регистрации приложения.

    Алгоритм:
      1. LLM читает тему/компетенцию и генерирует топ-5 поисковых запросов для Reddit.
      2. Для каждого запроса выполняется поиск в Reddit (job subreddits + глобально).
      3. Берём топ-N тредов по score/relevance.
      4. Для каждого треда получаем топ-3 комментария.
      5. Сохраняем всё в .md файл.

Целевые subreddits (вакансии и карьера):
    cscareerquestions, jobs, remotework, forhire, jobsearch,
    ExperiencedDevs, datascience, MachineLearning, learnmachinelearning

Использование:
    python Explore/Reddit/reddit_vacancy_tool.py --query "Python developer machine learning"
    python Explore/Reddit/reddit_vacancy_tool.py --query "data scientist" --top-posts 5 --subreddits cscareerquestions,jobs

Переменные окружения (из Competnecy/.env или Global_services/.env):
    CLOUDRU_API_KEY       — API ключ Cloud.ru (обязателен)
    CLOUDRU_BASE_URL      — базовый URL Cloud.ru API
    CLOUDRU_MODEL_NAME    — модель LLM (Qwen/Qwen3-Coder-Next)
    REDDIT_USER_AGENT     — User-Agent строка для публичного .json режима

Legacy / optional:
    REDDIT_CLIENT_ID      — legacy fallback
    REDDIT_CLIENT_SECRET  — legacy fallback
    REDDIT_USERNAME       — legacy fallback
    REDDIT_PASSWORD       — legacy fallback

ШАГ 1. Загрузка конфигурации (.env).
ШАГ 2. LLM генерирует топ-5 поисковых запросов для Reddit.
ШАГ 3. Поиск постов на Reddit по public `.json` endpoints.
ШАГ 4. Получение топ-3 комментариев для каждого поста.
ШАГ 5. Сохранение результатов в .md файл.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import logging
import os
import re
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

from dotenv import load_dotenv

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
)
logger = logging.getLogger(__name__)

HERE = Path(__file__).resolve().parent
ROOT = HERE.parent.parent                          # Competnecy/
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
else:
    logger.warning("ШАГ 0. .env не найден: %s и %s", _root_env_path, _global_env_path)

# Добавляем Global_services в путь для импорта Reddit-клиента
for _p in (ROOT, GLOBAL_SERVICES):
    _s = str(_p)
    if _s not in sys.path:
        sys.path.insert(0, _s)

# Импортируем Reddit клиент
try:
    from Reddit.reddit_client import RedditClient, RedditPost, RedditComment, create_reddit_client_from_env
except ImportError as _e:
    logger.error("Не удалось импортировать RedditClient: %s", _e)
    logger.error("Убедитесь что Global_services/Reddit/reddit_client.py существует")
    sys.exit(1)

# ---------------------------------------------------------------------------
# Константы
# ---------------------------------------------------------------------------

DEFAULT_SUBREDDITS = [
    "cscareerquestions",
    "jobs",
    "remotework",
    "ExperiencedDevs",
    "datascience",
    "MachineLearning",
    "jobsearch",
    "forhire",
]

TOP_POSTS_DEFAULT = 5          # топ постов на запрос
TOP_COMMENTS_DEFAULT = 3       # топ комментариев на пост
LLM_QUERIES_COUNT = 5          # количество запросов генерирует LLM
SEARCH_DELAY = 1.5             # пауза между запросами к Reddit


# ---------------------------------------------------------------------------
# ШАГ 2: LLM генерирует поисковые запросы
# ---------------------------------------------------------------------------

async def llm_generate_reddit_queries(
    user_query: str,
    api_key: str,
    base_url: str,
    model_name: str,
    n_queries: int = LLM_QUERIES_COUNT,
) -> list[str]:
    """
    ШАГ 2. Субагент: LLM генерирует релевантные поисковые запросы для Reddit.

    Args:
        user_query:  тема / компетенция от пользователя
        api_key:     Cloud.ru API ключ
        base_url:    Cloud.ru base URL
        model_name:  имя модели
        n_queries:   сколько запросов генерировать

    Returns:
        list[str] — список поисковых запросов (на английском, Reddit-friendly)
    """
    import openai

    logger.info(
        "ШАГ 2. LLM субагент: генерация %d Reddit-запросов для темы: %r ...",
        n_queries, user_query,
    )

    system_prompt = f"""You are an expert in career research and job market analysis.
Your task: given a competency topic, generate {n_queries} targeted Reddit search queries
to find the most relevant discussions about job requirements, skills, career advice,
and hiring practices.

RULES:
1. Queries must be in English (Reddit is predominantly English).
2. Each query should target a different angle: skills, salary, career path, hiring, tools.
3. Queries should be 3-7 words, natural language (not boolean search syntax).
4. Focus on practical career/job information, not academic theory.
5. Return ONLY a JSON array of strings, no markdown, no explanation.

Example output:
["python machine learning engineer skills", "ML engineer interview requirements 2024", ...]"""

    user_message = f"""TOPIC: {user_query}

Generate {n_queries} Reddit search queries to research career opportunities,
required skills, salary expectations, and hiring practices for this topic.
Return strictly a JSON array of {n_queries} strings."""

    client = openai.AsyncOpenAI(api_key=api_key, base_url=base_url)

    try:
        response = await client.chat.completions.create(
            model=model_name,
            messages=[
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_message},
            ],
            temperature=0.3,
            max_tokens=512,
        )
        raw = response.choices[0].message.content.strip()
        logger.info("ШАГ 2. LLM ответ получен (%d символов)", len(raw))

        # Извлекаем JSON массив из ответа
        json_match = re.search(r"\[.*?\]", raw, re.DOTALL)
        if json_match:
            raw = json_match.group(0)

        queries: list[str] = json.loads(raw)
        queries = [q.strip() for q in queries if isinstance(q, str) and q.strip()]
        queries = queries[:n_queries]

        logger.info("ШАГ 2. LLM сгенерировал %d запросов ... УСПЕХ", len(queries))
        for i, q in enumerate(queries, 1):
            logger.info("  Запрос %d: %r", i, q)

        return queries

    except json.JSONDecodeError as exc:
        logger.warning("ШАГ 2. Ошибка парсинга JSON от LLM: %s — raw=%r", exc, raw[:200])
        # Fallback: парсим строки из ответа
        lines = [ln.strip().strip('"').strip("'").strip(",") for ln in raw.split("\n")]
        fallback = [ln for ln in lines if len(ln) > 5 and not ln.startswith("[") and not ln.startswith("]")][:n_queries]
        if fallback:
            logger.info("ШАГ 2. Fallback: извлечено %d запросов из текста", len(fallback))
            return fallback
        # Самый последний fallback — используем запрос пользователя
        logger.warning("ШАГ 2. Fallback: используем исходный запрос пользователя")
        return [user_query]

    except Exception as exc:
        logger.error("ШАГ 2. ОШИБКА LLM: %s", exc)
        return [user_query]


# ---------------------------------------------------------------------------
# ШАГ 3-4: Reddit поиск + комментарии
# ---------------------------------------------------------------------------

async def fetch_reddit_data(
    queries: list[str],
    subreddits: list[str],
    top_posts: int,
    top_comments: int,
    use_global_search: bool = True,
) -> list[dict]:
    """
    ШАГ 3-4. Поиск постов + получение комментариев для всех запросов.

    Для каждого запроса:
      ШАГ 3. Ищем топ-N постов в Reddit.
      ШАГ 4. Для каждого поста получаем топ-3 комментария.

    Returns:
        list[dict] — {query, posts: [{post, comments}]}
    """
    results: list[dict] = []

    async with create_reddit_client_from_env() as client:
        for q_idx, query in enumerate(queries, 1):
            logger.info(
                "\n[Запрос %d/%d] %r ...",
                q_idx, len(queries), query,
            )

            # ШАГ 3. Поиск постов
            logger.info("ШАГ 3.%d. Reddit поиск постов: %r ...", q_idx, query)
            try:
                # Сначала ищем в тематических subreddits
                posts = await client.search_posts(
                    query=query,
                    subreddits=subreddits,
                    limit=top_posts,
                    sort="relevance",
                    time_filter="year",
                )

                # Если мало результатов — добавляем глобальный поиск
                if use_global_search and len(posts) < top_posts:
                    logger.info(
                        "ШАГ 3.%d. Недостаточно постов из subreddits (%d), "
                        "добавляем глобальный поиск ...",
                        q_idx, len(posts),
                    )
                    global_posts = await client.search_posts(
                        query=query,
                        subreddits=None,
                        limit=top_posts,
                        sort="relevance",
                        time_filter="year",
                    )
                    # Дедупликация по id
                    known_ids = {p.id for p in posts}
                    for gp in global_posts:
                        if gp.id not in known_ids:
                            posts.append(gp)
                            known_ids.add(gp.id)

                posts = posts[:top_posts]
                logger.info(
                    "ШАГ 3.%d. Найдено %d постов для запроса %r ... УСПЕХ",
                    q_idx, len(posts), query,
                )

            except Exception as exc:
                logger.error("ШАГ 3.%d. ОШИБКА поиска: %s", q_idx, exc)
                results.append({"query": query, "posts": []})
                continue

            # ШАГ 4. Получение комментариев
            posts_with_comments: list[dict] = []
            for p_idx, post in enumerate(posts, 1):
                logger.info(
                    "  ШАГ 4.%d.%d. Комментарии для поста %r (r/%s) ...",
                    q_idx, p_idx, post.title[:60], post.subreddit,
                )
                try:
                    await asyncio.sleep(SEARCH_DELAY)
                    comments = await client.get_post_comments(
                        post_id=post.id,
                        subreddit=post.subreddit,
                        limit=top_comments,
                        sort="top",
                    )
                    logger.info(
                        "  ШАГ 4.%d.%d. %d комментариев ... УСПЕХ",
                        q_idx, p_idx, len(comments),
                    )
                except Exception as exc:
                    logger.warning(
                        "  ШАГ 4.%d.%d. ОШИБКА комментариев: %s", q_idx, p_idx, exc
                    )
                    comments = []

                posts_with_comments.append({
                    "post": post.to_dict(),
                    "comments": [c.to_dict() for c in comments],
                })

            results.append({
                "query": query,
                "posts": posts_with_comments,
            })

            # Пауза между запросами
            if q_idx < len(queries):
                await asyncio.sleep(SEARCH_DELAY * 2)

    return results


# ---------------------------------------------------------------------------
# ШАГ 5: Генерация .md
# ---------------------------------------------------------------------------

def render_markdown(
    user_query: str,
    queries: list[str],
    results: list[dict],
    subreddits: list[str],
) -> str:
    """
    ШАГ 5. Генерирует Markdown-отчёт из результатов Reddit-поиска.
    """
    logger.info("ШАГ 5. Генерация Markdown-отчёта ...")

    total_posts = sum(len(r["posts"]) for r in results)
    total_comments = sum(
        len(p["comments"])
        for r in results
        for p in r["posts"]
    )

    lines: list[str] = []
    lines.append(f"# Reddit Research: {user_query}")
    lines.append("")
    lines.append(
        f"**Дата сбора:** {datetime.now(timezone.utc).strftime('%Y-%m-%d %H:%M UTC')}"
    )
    lines.append(f"**Запросы LLM:** {len(queries)}")
    lines.append(f"**Найдено тредов:** {total_posts}")
    lines.append(f"**Комментариев:** {total_comments}")
    lines.append(f"**Subreddits:** {', '.join(f'r/{s}' for s in subreddits)}")
    lines.append("")
    lines.append("---")
    lines.append("")

    # Список запросов
    lines.append("## Поисковые запросы (сгенерированы LLM)")
    lines.append("")
    for i, q in enumerate(queries, 1):
        lines.append(f"{i}. `{q}`")
    lines.append("")
    lines.append("---")
    lines.append("")

    # Результаты по каждому запросу
    for r_idx, result in enumerate(results, 1):
        query = result["query"]
        posts = result["posts"]

        lines.append(f"## Запрос {r_idx}: `{query}`")
        lines.append("")

        if not posts:
            lines.append("> *Нет результатов для данного запроса.*")
            lines.append("")
            continue

        for p_idx, item in enumerate(posts, 1):
            post = item["post"]
            comments = item["comments"]

            title = post.get("title", "Без заголовка")
            subreddit = post.get("subreddit", "unknown")
            author = post.get("author", "[deleted]")
            score = post.get("score", 0)
            num_comments = post.get("num_comments", 0)
            full_url = post.get("full_url", post.get("url", ""))
            created = post.get("created_utc", "")[:10] if post.get("created_utc") else ""
            selftext = post.get("selftext", "").strip()
            flair = post.get("link_flair_text", "")

            lines.append(f"### {p_idx}. {title}")
            lines.append("")

            # Мета
            meta_parts = [
                f"r/{subreddit}",
                f"u/{author}",
                f"⬆ {score:,}",
                f"💬 {num_comments}",
            ]
            if created:
                meta_parts.append(created)
            if flair:
                meta_parts.append(f"[{flair}]")
            lines.append("**" + " · ".join(meta_parts) + "**")
            lines.append("")
            lines.append(f"🔗 {full_url}")
            lines.append("")

            # Текст поста (если есть и не слишком длинный)
            if selftext and selftext not in ("[deleted]", "[removed]"):
                max_chars = 1500
                if len(selftext) > max_chars:
                    selftext = selftext[:max_chars] + "\n\n*[текст обрезан...]*"
                lines.append("**Текст поста:**")
                lines.append("")
                lines.append(selftext)
                lines.append("")

            # Комментарии
            if comments:
                lines.append(f"**Топ-{len(comments)} комментариев:**")
                lines.append("")
                for c_idx, comment in enumerate(comments, 1):
                    c_author = comment.get("author", "[deleted]")
                    c_score = comment.get("score", 0)
                    c_body = comment.get("body", "").strip()
                    c_date = comment.get("created_utc", "")[:10]

                    # Обрезаем слишком длинные комментарии
                    max_c_chars = 800
                    if len(c_body) > max_c_chars:
                        c_body = c_body[:max_c_chars] + "\n*[обрезан...]*"

                    lines.append(
                        f"> **#{c_idx}** u/{c_author} · ⬆ {c_score} · {c_date}"
                    )
                    lines.append(">")
                    for body_line in c_body.split("\n"):
                        lines.append(f"> {body_line}")
                    lines.append("")
            else:
                lines.append("*Комментарии недоступны.*")
                lines.append("")

            lines.append("---")
            lines.append("")

    logger.info(
        "ШАГ 5. Markdown сгенерирован: %d строк, %d символов ... УСПЕХ",
        len(lines), sum(len(l) for l in lines),
    )
    return "\n".join(lines)


# ---------------------------------------------------------------------------
# Главный оркестратор
# ---------------------------------------------------------------------------

async def main(
    user_query: str,
    output_dir: Path,
    subreddits: list[str],
    top_posts: int,
    top_comments: int,
    use_global_search: bool,
) -> None:
    """
    Главный оркестратор Reddit Vacancy Tool.

    ШАГ 0. Загрузка конфигурации (.env).
    ШАГ 1. Валидация входных данных.
    ШАГ 2. LLM генерирует поисковые запросы для Reddit.
    ШАГ 3. Поиск постов в Reddit по каждому запросу.
    ШАГ 4. Получение топ-3 комментариев для каждого поста.
    ШАГ 5. Генерация и сохранение .md отчёта.
    """
    # ШАГ 0. Конфигурация
    api_key = os.getenv("CLOUDRU_API_KEY", "")
    base_url = os.getenv("CLOUDRU_BASE_URL", "https://foundation-models.api.cloud.ru/v1")
    model_name = os.getenv("CLOUDRU_MODEL_NAME", "Qwen/Qwen3-Coder-Next")

    logger.info("ШАГ 0. Конфигурация:")
    logger.info("  query=%r", user_query)
    logger.info("  model=%s", model_name)
    logger.info("  subreddits=%s", subreddits)
    logger.info("  top_posts=%d, top_comments=%d", top_posts, top_comments)
    logger.info("  global_search=%s", use_global_search)

    # ШАГ 1. Валидация
    if not api_key:
        logger.error("ШАГ 1. ОШИБКА: CLOUDRU_API_KEY не задан в .env")
        logger.error("Задайте переменную окружения CLOUDRU_API_KEY в Global_services/.env")
        sys.exit(1)

    output_dir.mkdir(parents=True, exist_ok=True)
    logger.info("ШАГ 1. Директория вывода: %s ... УСПЕХ", output_dir)

    # ШАГ 2. LLM генерирует запросы
    queries = await llm_generate_reddit_queries(
        user_query=user_query,
        api_key=api_key,
        base_url=base_url,
        model_name=model_name,
        n_queries=LLM_QUERIES_COUNT,
    )

    if not queries:
        logger.error("ШАГ 2. ОШИБКА: LLM не вернул ни одного запроса")
        sys.exit(1)

    logger.info("ШАГ 2. Запросы для Reddit: %d ... УСПЕХ", len(queries))

    # ШАГ 3-4. Поиск + комментарии
    logger.info(
        "ШАГ 3-4. Поиск в Reddit (%d запросов × топ-%d постов × топ-%d комментариев) ...",
        len(queries), top_posts, top_comments,
    )
    results = await fetch_reddit_data(
        queries=queries,
        subreddits=subreddits,
        top_posts=top_posts,
        top_comments=top_comments,
        use_global_search=use_global_search,
    )

    total_posts_found = sum(len(r["posts"]) for r in results)
    logger.info(
        "ШАГ 3-4. Итого: %d результатов, %d постов ... УСПЕХ",
        len(results), total_posts_found,
    )

    # ШАГ 5. Генерация и сохранение MD
    logger.info("ШАГ 5. Генерация и сохранение .md ...")
    md_content = render_markdown(
        user_query=user_query,
        queries=queries,
        results=results,
        subreddits=subreddits,
    )

    ts = datetime.now().strftime("%Y%m%d_%H%M%S")
    slug = re.sub(r"[^\w\-]", "_", user_query.lower().strip())
    slug = re.sub(r"_+", "_", slug)[:50]
    md_filename = f"{slug}_reddit_{ts}.md"
    md_path = output_dir / md_filename

    md_path.write_text(md_content, encoding="utf-8")
    logger.info(
        "ШАГ 5. Сохранено → %s (%d байт) ... УСПЕХ",
        md_path, len(md_content.encode()),
    )

    # Сохраняем raw JSON (для отладки)
    json_path = output_dir / f"{slug}_reddit_{ts}_raw.json"
    json_data = {
        "user_query": user_query,
        "queries": queries,
        "subreddits": subreddits,
        "top_posts": top_posts,
        "top_comments": top_comments,
        "created_at": datetime.now(timezone.utc).isoformat(),
        "results": results,
    }
    json_path.write_text(json.dumps(json_data, ensure_ascii=False, indent=2), encoding="utf-8")
    logger.info("ШАГ 5. Raw JSON → %s ... УСПЕХ", json_path)

    # Итоговый вывод
    total_comments_count = sum(
        len(p["comments"])
        for r in results
        for p in r["posts"]
    )
    print(f"\n{'='*60}")
    print(f"REDDIT VACANCY TOOL — ЗАВЕРШЕНО")
    print(f"  Тема:             {user_query}")
    print(f"  Reddit-запросов:  {len(queries)}")
    print(f"  Тредов найдено:   {total_posts_found}")
    print(f"  Комментариев:     {total_comments_count}")
    print(f"\n  MD-отчёт: {md_path}")
    print(f"  JSON данные: {json_path}")
    print(f"{'='*60}\n")
    print("Поисковые запросы (сгенерировал LLM):")
    for i, q in enumerate(queries, 1):
        print(f"  {i}. {q}")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(
        description="Reddit Vacancy Tool: LLM → поисковые запросы → Reddit → .md"
    )
    parser.add_argument(
        "--query",
        required=True,
        help="Тема / компетенция (например: 'Python developer machine learning')",
    )
    parser.add_argument(
        "--output-dir",
        default=str(HERE / "output"),
        help="Директория для сохранения результатов (default: Explore/Reddit/output/)",
    )
    parser.add_argument(
        "--subreddits",
        default=",".join(DEFAULT_SUBREDDITS),
        help=(
            "Subreddits через запятую "
            f"(default: {','.join(DEFAULT_SUBREDDITS)})"
        ),
    )
    parser.add_argument(
        "--top-posts",
        type=int,
        default=TOP_POSTS_DEFAULT,
        help=f"Топ-N постов на запрос (default: {TOP_POSTS_DEFAULT})",
    )
    parser.add_argument(
        "--top-comments",
        type=int,
        default=TOP_COMMENTS_DEFAULT,
        help=f"Топ-N комментариев на пост (default: {TOP_COMMENTS_DEFAULT})",
    )
    parser.add_argument(
        "--no-global-search",
        action="store_true",
        help="Не использовать глобальный поиск Reddit (только subreddits)",
    )
    args = parser.parse_args()

    _subreddits = [s.strip() for s in args.subreddits.split(",") if s.strip()]

    asyncio.run(
        main(
            user_query=args.query,
            output_dir=Path(args.output_dir),
            subreddits=_subreddits,
            top_posts=args.top_posts,
            top_comments=args.top_comments,
            use_global_search=not args.no_global_search,
        )
    )
