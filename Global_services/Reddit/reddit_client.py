# -*- coding: utf-8 -*-
"""
Руководство к файлу reddit_client.py
=====================================

Назначение:
    Переиспользуемый асинхронный клиент для Reddit Public JSON API.
    Основной режим работы:
      1. Public JSON — публичные .json эндпоинты Reddit без credentials.
         Это основной и рекомендуемый режим для данного проекта.
         Подходит для поиска тредов и чтения комментариев.
         Практический лимит: порядка ~60-100 запросов/мин по IP.

    Дополнительный режим:
      2. OAuth2 / legacy fallback — оставлен только для совместимости со старым кодом.
         Из-за новой политики Reddit выдача новых токенов требует ручного одобрения,
         поэтому этот режим не рассматривается как базовый сценарий интеграции.

Основные методы:
    search_posts(query, subreddits, limit, sort, time_filter) → list[RedditPost]
    get_post_comments(post_id, subreddit, limit, sort)        → list[RedditComment]

Переменные окружения:
    REDDIT_USER_AGENT      — User-Agent строка для public JSON режима

Дополнительные переменные (legacy, optional):
    REDDIT_CLIENT_ID       — Reddit App client_id
    REDDIT_CLIENT_SECRET   — Reddit App client_secret
    REDDIT_USERNAME        — Reddit username (password-flow)
    REDDIT_PASSWORD        — Reddit password

Важно:
    Для задач этого проекта credentials не требуются.
    Поиск и чтение данных выполняются через публичные .json endpoints.

ШАГ 1. Инициализация клиента (public JSON по умолчанию).
ШАГ 2. Поиск постов по запросу (search_posts).
ШАГ 3. Получение топ-N комментариев к посту (get_post_comments).
"""

from __future__ import annotations

import asyncio
import base64
import logging
import os
import time
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Optional

import httpx

logger = logging.getLogger(__name__)

REDDIT_BASE_URL = "https://www.reddit.com"
REDDIT_OAUTH_URL = "https://oauth.reddit.com"
REDDIT_TOKEN_URL = "https://www.reddit.com/api/v1/access_token"
DEFAULT_USER_AGENT = "CompetencyBot/1.0 by CompetencyResearcher"

RATE_LIMIT_DELAY = 1.2   # секунды между запросами (вежливая пауза)
REQUEST_TIMEOUT = 30.0
MAX_RETRIES = 3


# ---------------------------------------------------------------------------
# Структуры данных
# ---------------------------------------------------------------------------

@dataclass
class RedditPost:
    """Пост Reddit (thread)."""
    id: str
    title: str
    selftext: str
    url: str
    permalink: str
    subreddit: str
    author: str
    score: int
    upvote_ratio: float
    num_comments: int
    created_utc: datetime
    is_self: bool
    link_flair_text: Optional[str] = None

    @property
    def full_url(self) -> str:
        return f"https://www.reddit.com{self.permalink}"

    def to_dict(self) -> dict:
        return {
            "id": self.id,
            "title": self.title,
            "selftext": self.selftext,
            "url": self.url,
            "full_url": self.full_url,
            "permalink": self.permalink,
            "subreddit": self.subreddit,
            "author": self.author,
            "score": self.score,
            "upvote_ratio": self.upvote_ratio,
            "num_comments": self.num_comments,
            "created_utc": self.created_utc.isoformat(),
            "is_self": self.is_self,
            "link_flair_text": self.link_flair_text,
        }


@dataclass
class RedditComment:
    """Комментарий Reddit."""
    id: str
    body: str
    author: str
    score: int
    created_utc: datetime
    permalink: str
    depth: int = 0
    replies: list["RedditComment"] = field(default_factory=list)

    def to_dict(self) -> dict:
        return {
            "id": self.id,
            "body": self.body,
            "author": self.author,
            "score": self.score,
            "created_utc": self.created_utc.isoformat(),
            "permalink": self.permalink,
            "depth": self.depth,
        }


# ---------------------------------------------------------------------------
# Клиент
# ---------------------------------------------------------------------------

class RedditClient:
    """
    Асинхронный клиент для Reddit JSON API.

    Использование как context manager:
        async with RedditClient() as client:
            posts = await client.search_posts("python developer jobs")

    Использование без context manager:
        client = RedditClient()
        posts = await client.search_posts(...)
        await client.close()
    """

    def __init__(
        self,
        client_id: Optional[str] = None,
        client_secret: Optional[str] = None,
        username: Optional[str] = None,
        password: Optional[str] = None,
        user_agent: Optional[str] = None,
    ) -> None:
        self._client_id = client_id or os.getenv("REDDIT_CLIENT_ID", "")
        self._client_secret = client_secret or os.getenv("REDDIT_CLIENT_SECRET", "")
        self._username = username or os.getenv("REDDIT_USERNAME", "")
        self._password = password or os.getenv("REDDIT_PASSWORD", "")
        self._user_agent = user_agent or os.getenv("REDDIT_USER_AGENT", DEFAULT_USER_AGENT)

        self._access_token: Optional[str] = None
        self._token_expires_at: float = 0.0
        self._is_oauth = bool(self._client_id and self._client_secret)

        self._http: Optional[httpx.AsyncClient] = None

        logger.info(
            "ШАГ 1. RedditClient инициализирован: режим=%s, user_agent=%r",
            "oauth2_legacy" if self._is_oauth else "public_json",
            self._user_agent,
        )

    async def __aenter__(self) -> "RedditClient":
        await self._ensure_http()
        return self

    async def __aexit__(self, *_: object) -> None:
        await self.close()

    async def _ensure_http(self) -> None:
        """Создаёт httpx.AsyncClient если не создан."""
        if self._http is None:
            # Reddit блокирует datacenter proxy — обходим напрямую
            import copy
            env = copy.deepcopy(os.environ)
            for k in ("HTTP_PROXY", "HTTPS_PROXY", "http_proxy", "https_proxy"):
                os.environ.pop(k, None)
            try:
                self._http = httpx.AsyncClient(
                    headers={"User-Agent": self._user_agent},
                    timeout=REQUEST_TIMEOUT,
                    follow_redirects=True,
                )
            finally:
                os.environ.update(env)

    async def close(self) -> None:
        """Закрывает httpx.AsyncClient."""
        if self._http is not None:
            await self._http.aclose()
            self._http = None

    # ------------------------------------------------------------------
    # OAuth2 token management
    # ------------------------------------------------------------------

    async def _get_access_token(self) -> str:
        """Получает / обновляет OAuth2 access token (legacy fallback режим)."""
        now = time.time()
        if self._access_token and now < self._token_expires_at - 60:
            return self._access_token

        logger.info("ШАГ 1.1. Обновление OAuth2 токена Reddit ...")
        await self._ensure_http()

        credentials = base64.b64encode(
            f"{self._client_id}:{self._client_secret}".encode()
        ).decode()

        resp = await self._http.post(
            REDDIT_TOKEN_URL,
            data={
                "grant_type": "password",
                "username": self._username,
                "password": self._password,
            },
            headers={
                "Authorization": f"Basic {credentials}",
                "User-Agent": self._user_agent,
            },
        )
        resp.raise_for_status()
        token_data = resp.json()

        self._access_token = token_data["access_token"]
        self._token_expires_at = now + token_data.get("expires_in", 3600)
        logger.info(
            "ШАГ 1.1. OAuth2 токен получен, expires_in=%ss ... УСПЕХ",
            token_data.get("expires_in"),
        )
        return self._access_token

    # ------------------------------------------------------------------
    # HTTP helpers
    # ------------------------------------------------------------------

    def _to_json_url(self, url: str) -> str:
        """Добавляет .json к URL Reddit если нужно."""
        if ".json" in url:
            return url
        if "?" in url:
            base, qs = url.split("?", 1)
            if not base.endswith(".json"):
                base += ".json"
            return f"{base}?{qs}"
        if not url.endswith(".json"):
            return url + ".json"
        return url

    async def _get(self, url: str, params: Optional[dict] = None) -> object:
        """
        Выполняет GET запрос к Reddit API с ретраями и rate-limit обработкой.
        Возвращает распарсенный JSON или пустой dict/list при ошибке.
        """
        await self._ensure_http()

        headers: dict = {}
        if self._is_oauth:
            token = await self._get_access_token()
            headers["Authorization"] = f"Bearer {token}"
            if url.startswith(REDDIT_BASE_URL):
                url = url.replace(REDDIT_BASE_URL, REDDIT_OAUTH_URL)
        else:
            url = self._to_json_url(url)

        for attempt in range(1, MAX_RETRIES + 1):
            try:
                resp = await self._http.get(url, params=params, headers=headers)

                if resp.status_code == 429:
                    wait = int(resp.headers.get("Retry-After", 60))
                    logger.warning(
                        "Reddit 429 rate-limit, ожидание %ds (попытка %d/%d) ...",
                        wait, attempt, MAX_RETRIES,
                    )
                    await asyncio.sleep(wait)
                    continue

                if resp.status_code in (403, 404):
                    logger.warning(
                        "Reddit %d для %s — пропуск", resp.status_code, url
                    )
                    return {}

                resp.raise_for_status()
                return resp.json()

            except httpx.HTTPStatusError as exc:
                logger.warning(
                    "HTTP ошибка %d (попытка %d/%d): %s",
                    exc.response.status_code, attempt, MAX_RETRIES, url,
                )
            except Exception as exc:
                logger.warning(
                    "Ошибка запроса (попытка %d/%d): %s — %s",
                    attempt, MAX_RETRIES, type(exc).__name__, exc,
                )

            if attempt < MAX_RETRIES:
                await asyncio.sleep(2.0 * attempt)

        logger.error("Не удалось выполнить запрос после %d попыток: %s", MAX_RETRIES, url)
        return {}

    # ------------------------------------------------------------------
    # Парсеры структур Reddit
    # ------------------------------------------------------------------

    @staticmethod
    def _parse_post(child: dict) -> Optional[RedditPost]:
        """Парсит дочерний элемент listing (kind=t3) в RedditPost."""
        try:
            if child.get("kind") != "t3":
                return None
            d = child.get("data", {})
            if not d.get("id"):
                return None
            return RedditPost(
                id=d["id"],
                title=d.get("title", ""),
                selftext=d.get("selftext", ""),
                url=d.get("url", ""),
                permalink=d.get("permalink", ""),
                subreddit=d.get("subreddit", ""),
                author=d.get("author", "[deleted]"),
                score=int(d.get("score", 0)),
                upvote_ratio=float(d.get("upvote_ratio", 0.0)),
                num_comments=int(d.get("num_comments", 0)),
                created_utc=datetime.fromtimestamp(
                    float(d.get("created_utc", 0)), tz=timezone.utc
                ),
                is_self=bool(d.get("is_self", False)),
                link_flair_text=d.get("link_flair_text"),
            )
        except Exception as exc:
            logger.debug("Ошибка парсинга поста: %s", exc)
            return None

    @staticmethod
    def _parse_comment(child: dict, depth: int = 0) -> Optional[RedditComment]:
        """Парсит дочерний элемент listing (kind=t1) в RedditComment."""
        try:
            if child.get("kind") != "t1":
                return None
            d = child.get("data", {})
            body = d.get("body", "").strip()
            if not body or body in ("[deleted]", "[removed]"):
                return None
            if not d.get("id"):
                return None
            return RedditComment(
                id=d["id"],
                body=body,
                author=d.get("author", "[deleted]"),
                score=int(d.get("score", 0)),
                created_utc=datetime.fromtimestamp(
                    float(d.get("created_utc", 0)), tz=timezone.utc
                ),
                permalink=d.get("permalink", ""),
                depth=depth,
            )
        except Exception as exc:
            logger.debug("Ошибка парсинга комментария: %s", exc)
            return None

    # ------------------------------------------------------------------
    # Публичные методы
    # ------------------------------------------------------------------

    async def search_posts(
        self,
        query: str,
        subreddits: Optional[list[str]] = None,
        limit: int = 10,
        sort: str = "relevance",
        time_filter: str = "year",
    ) -> list[RedditPost]:
        """
        ШАГ 2. Поиск постов по запросу.

        Args:
            query:       поисковый запрос
            subreddits:  список subreddit для ограничения (None = глобальный поиск)
            limit:       макс. кол-во постов в результате
            sort:        relevance | top | hot | new | comments
            time_filter: hour | day | week | month | year | all

        Returns:
            list[RedditPost] — дедуплицированный, отсортированный по score
        """
        logger.info(
            "ШАГ 2. Reddit поиск: query=%r, subreddits=%r, limit=%d, sort=%s, time=%s ...",
            query, subreddits, limit, sort, time_filter,
        )

        all_posts: list[RedditPost] = []

        if subreddits:
            for i, sub in enumerate(subreddits, 1):
                url = f"{REDDIT_BASE_URL}/r/{sub}/search.json"
                params: dict = {
                    "q": query,
                    "restrict_sr": "1",
                    "sort": sort,
                    "t": time_filter,
                    "limit": min(limit, 25),
                }
                logger.info("  ШАГ 2.%d. Поиск в r/%s ...", i, sub)
                data = await self._get(url, params=params)
                await asyncio.sleep(RATE_LIMIT_DELAY)

                children = (
                    data.get("data", {}).get("children", [])  # type: ignore[union-attr]
                    if isinstance(data, dict)
                    else []
                )
                parsed = [self._parse_post(c) for c in children]
                new_posts = [p for p in parsed if p is not None]
                all_posts.extend(new_posts)
                logger.info("  ШАГ 2.%d. r/%s: %d постов", i, sub, len(new_posts))
        else:
            # Глобальный поиск
            url = f"{REDDIT_BASE_URL}/search.json"
            params = {
                "q": query,
                "sort": sort,
                "t": time_filter,
                "limit": min(limit, 25),
                "type": "link",
            }
            logger.info("  ШАГ 2.1. Глобальный поиск Reddit ...")
            data = await self._get(url, params=params)
            await asyncio.sleep(RATE_LIMIT_DELAY)

            children = (
                data.get("data", {}).get("children", [])  # type: ignore[union-attr]
                if isinstance(data, dict)
                else []
            )
            parsed = [self._parse_post(c) for c in children]
            new_posts = [p for p in parsed if p is not None]
            all_posts.extend(new_posts)
            logger.info("  ШАГ 2.1. Глобально: %d постов", len(new_posts))

        # Дедупликация по id, сортировка по score
        seen: set[str] = set()
        unique: list[RedditPost] = []
        for post in all_posts:
            if post.id not in seen:
                seen.add(post.id)
                unique.append(post)

        unique.sort(key=lambda p: p.score, reverse=True)
        result = unique[:limit]

        logger.info(
            "ШАГ 2. Поиск завершён: всего=%d, уникальных=%d, возвращаем=%d ... УСПЕХ",
            len(all_posts), len(unique), len(result),
        )
        return result

    async def get_post_comments(
        self,
        post_id: str,
        subreddit: str,
        limit: int = 3,
        sort: str = "top",
    ) -> list[RedditComment]:
        """
        ШАГ 3. Получение топ-N комментариев к посту.

        Args:
            post_id:   ID поста (без t3_ префикса)
            subreddit: название subreddit
            limit:     макс. кол-во комментариев
            sort:      top | best | new | controversial | old

        Returns:
            list[RedditComment] — топ комментарии по score
        """
        logger.info(
            "ШАГ 3. Получение комментариев: r/%s/comments/%s, limit=%d, sort=%s ...",
            subreddit, post_id, limit, sort,
        )

        url = f"{REDDIT_BASE_URL}/r/{subreddit}/comments/{post_id}.json"
        params: dict = {
            "sort": sort,
            "limit": limit,
            "depth": 1,
        }

        data = await self._get(url, params=params)
        await asyncio.sleep(RATE_LIMIT_DELAY)

        # Reddit возвращает список из 2 элементов: [0] = пост, [1] = комментарии
        if not isinstance(data, list) or len(data) < 2:
            logger.warning(
                "ШАГ 3. Неожиданный формат ответа для %s/%s", subreddit, post_id
            )
            return []

        children = data[1].get("data", {}).get("children", [])

        comments: list[RedditComment] = []
        for child in children:
            c = self._parse_comment(child, depth=0)
            if c is not None:
                comments.append(c)
            if len(comments) >= limit:
                break

        # Сортируем по score (API возвращает top, но страхуемся)
        comments.sort(key=lambda c: c.score, reverse=True)
        result = comments[:limit]

        logger.info(
            "ШАГ 3. Получено %d комментариев для %s ... УСПЕХ",
            len(result), post_id,
        )
        return result


# ---------------------------------------------------------------------------
# Фабрика из .env
# ---------------------------------------------------------------------------

def create_reddit_client_from_env() -> RedditClient:
    """Создаёт RedditClient из переменных окружения."""
    return RedditClient(
        client_id=os.getenv("REDDIT_CLIENT_ID", ""),
        client_secret=os.getenv("REDDIT_CLIENT_SECRET", ""),
        username=os.getenv("REDDIT_USERNAME", ""),
        password=os.getenv("REDDIT_PASSWORD", ""),
        user_agent=os.getenv("REDDIT_USER_AGENT", DEFAULT_USER_AGENT),
    )
