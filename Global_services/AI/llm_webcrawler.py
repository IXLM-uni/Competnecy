# -*- coding: utf-8 -*-
"""
Руководство к файлу llm_webcrawler.py
=====================================
 
Назначение:
    Вынесенный модуль веб-поиска/краулинга из llm_service.py.
    Поиск теперь идёт через SearXNG JSON API, а затем найденные URL
    проходят единый предкраулинговый фильтр URL-кандидатов и только затем
    отправляются в Crawler4AI для извлечения текста страниц.
    Содержит:
      - CrawlerQueryRewriter
      - CrawlerClient

Контракт совместимости:
    Имена классов и сигнатуры методов сохранены совместимыми,
    чтобы use-cases продолжали работать без изменения импортов.

Текущий pipeline:
    ШАГ 1. Search results собираются через SearXNG.
    ШАГ 2. URL нормализуются и дедуплицируются.
    ШАГ 3. URL прогоняются через единый candidate filter со статусом
            allow/skip и reason.
    ШАГ 4. Только allow URL отправляются в Crawl4AI.
    ШАГ 5. Все skip URL подробно логируются для дебага.

Улучшения интеграции Crawl4AI:
    ШАГ 6. В crawler_server передаются продвинутые параметры
            magic / scan_full_page / exclude_external_links /
            exclude_social_media_links / return_format / cache_mode.
    ШАГ 7. HTTP timeout клиента всегда больше server-side timeout,
            чтобы не рвать соединение раньше завершения краулинга.
    ШАГ 8. Приоритет при извлечении контента отдаётся fit_markdown,
            затем text, чтобы экономить токены LLM.
    ШАГ 9. Из crawler_server дополнительно пробрасывается link_anchor_map,
            чтобы downstream-логика видела объект «anchor phrase -> href/context/scope».

Техническое правило:
    Для избегания циклических импортов runtime-зависимости на llm_service.py
    (LLMRequest, LLMMessage, Snippet) подтягиваются локально внутри методов.
"""

from __future__ import annotations

import json
import logging
import os
from typing import TYPE_CHECKING, Any, Dict, List, Optional, Tuple
from urllib.parse import quote_plus
from urllib.parse import parse_qsl, unquote, urlparse

import httpx

if TYPE_CHECKING:
    from AI.llm_service import OpenAIClient, RequestContext, Snippet

logger = logging.getLogger(__name__)

HTTP_TIMEOUT_BUFFER_SECONDS = 10.0

SEARXNG_REQUEST_HEADERS = {
    "Accept": "application/json",
    "User-Agent": "MyPerplexityCrawler/1.0",
    "X-Forwarded-For": "127.0.0.1",
    "X-Real-IP": "127.0.0.1",
}


class CrawlerQueryRewriter:
    """Генерирует поисковые запросы для интернет-поиска (ШАГ 3.2)."""

    def __init__(self, llm_client: "OpenAIClient", count: int = 2) -> None:
        self._llm = llm_client
        self._count = count

    async def rewrite(self, query: str, ctx: "RequestContext") -> List[str]:
        from AI.llm_service import LLMMessage, LLMRequest  # локально: защита от циклического импорта

        logger.info(
            "ШАГ 3.2. CrawlerQueryRewriter — генерируем запросы: request_id=%s",
            ctx.request_id,
        )
        prompt = (
            f"Сформулируй {self._count} поисковых запроса для поисковой системы, "
            f"чтобы найти самую точную и актуальную информацию по теме. "
            f"Запросы должны быть разнообразными: синонимы, смежные аспекты, "
            f"уточняющие формулировки. Верни ТОЛЬКО валидный JSON-массив строк."
            f"\n\nТема: {query}"
        )
        request = LLMRequest(
            messages=[LLMMessage(role="user", content=prompt)],
            model=self._llm._default_model,
            temperature=0.5,
        )
        try:
            response = await self._llm.create_response(request, ctx)
            queries = json.loads(response.content)
            if isinstance(queries, list):
                logger.info(
                    "ШАГ 3.2. CrawlerQueryRewriter — УСПЕХ: %d запросов",
                    len(queries),
                )
                return [str(q) for q in queries[: self._count]]
        except Exception as exc:
            logger.warning(
                "ШАГ 3.2. CrawlerQueryRewriter — ОШИБКА: %s, используем оригинал",
                exc,
            )
        return [query]


class CrawlerClient:
    """Клиент для веб-краулинга через Crawler4AI (crawler_server.py)."""

    _URL_PREFIXES = ("http://", "https://", "ftp://")
    _DEFAULT_SEARXNG_ENGINE = "google"
    _SKIP_FILE_EXTENSIONS = {
        ".7z", ".apk", ".bz2", ".csv", ".doc", ".docx", ".epub", ".gz", ".iso",
        ".jpeg", ".jpg", ".json", ".mp3", ".mp4", ".ods", ".odt", ".pdf", ".png",
        ".ppt", ".pptx", ".rar", ".rtf", ".tar", ".tgz", ".txt", ".xls", ".xlsx",
        ".xml", ".zip",
    }
    _SKIP_PATH_SEGMENTS = {
        "api", "asset", "assets", "attachment", "attachments", "download", "downloads",
        "export", "exports", "file", "files", "media", "static", "storage", "uploads",
    }
    _SKIP_QUERY_KEYS = {
        "attachment", "asset", "download", "export", "file", "filename", "redirect",
        "redirect_uri", "redirect_url", "target", "to", "url", "u", "uri",
    }
    _SKIP_TRACKING_KEYS = {
        "fbclid", "gclid", "mc_cid", "mc_eid", "mkt_tok", "ref", "ref_src", "spm",
        "src", "trk", "utm_campaign", "utm_content", "utm_id", "utm_medium", "utm_source",
        "utm_term", "yclid",
    }

    def __init__(
        self,
        base_url: Optional[str] = None,
        api_key: Optional[str] = None,
        max_pages: int = 3,
        timeout: float = 45.0,
        word_count_threshold: int = 10,
    ) -> None:
        self._base_url = base_url
        self._api_key = api_key
        self._max_pages = max_pages
        self._timeout = timeout
        self._word_count_threshold = word_count_threshold
        self._searxng_base_url = (os.environ.get("SEARXNG_BASE_URL") or "http://searxng:8080").rstrip("/")
        self._searxng_engine = (os.environ.get("SEARXNG_ENGINE") or self._DEFAULT_SEARXNG_ENGINE).strip() or self._DEFAULT_SEARXNG_ENGINE

    @staticmethod
    def _is_url(text: str) -> bool:
        stripped = text.strip()
        return any(stripped.lower().startswith(p) for p in CrawlerClient._URL_PREFIXES)

    def _query_to_search_url(self, query: str) -> str:
        return (
            f"{self._searxng_base_url}/search"
            f"?q={quote_plus(query)}&format=json&language=ru-RU&engines={quote_plus(self._searxng_engine)}"
        )

    @staticmethod
    def _normalize_search_result_url(raw_url: str) -> str:
        return (raw_url or "").strip()

    @staticmethod
    def _is_search_result_acceptable(url: str) -> bool:
        if not url:
            return False
        parsed = urlparse(url)
        if parsed.scheme not in {"http", "https"}:
            return False
        if not parsed.netloc:
            return False
        lowered_netloc = parsed.netloc.lower()
        if "searx" in lowered_netloc:
            return False
        return True

    @staticmethod
    def _path_has_skippable_extension(path: str) -> bool:
        lowered_path = unquote(path or "").lower().strip()
        return any(lowered_path.endswith(extension) for extension in CrawlerClient._SKIP_FILE_EXTENSIONS)

    @staticmethod
    def _has_skippable_path_segment(path: str) -> bool:
        lowered_path = unquote(path or "").lower()
        path_segments = [segment for segment in lowered_path.split("/") if segment]
        return any(segment in CrawlerClient._SKIP_PATH_SEGMENTS for segment in path_segments)

    @staticmethod
    def _is_probably_tracking_or_redirect_url(parsed_url: Any) -> bool:
        query_pairs = [(key.lower(), value.lower()) for key, value in parse_qsl(parsed_url.query, keep_blank_values=True)]
        query_keys = {key for key, _ in query_pairs}

        if query_keys & CrawlerClient._SKIP_TRACKING_KEYS:
            return True

        redirect_like_keys = query_keys & CrawlerClient._SKIP_QUERY_KEYS
        if redirect_like_keys and parsed_url.path in {"", "/"}:
            return True

        if parsed_url.netloc.lower() in {"l.facebook.com", "lm.facebook.com", "t.co"} and redirect_like_keys:
            return True

        return False

    @staticmethod
    def _has_meaningful_text_context(url: str) -> bool:
        parsed = urlparse(url)
        path_segments = [segment for segment in unquote(parsed.path).split("/") if segment]
        if not path_segments:
            return True

        meaningful_segments = 0
        for segment in path_segments:
            cleaned_segment = segment.strip().lower()
            if len(cleaned_segment) >= 3 and any(char.isalpha() for char in cleaned_segment):
                meaningful_segments += 1
        return meaningful_segments > 0

    def _classify_precrawl_candidate(self, url: str) -> Tuple[str, str]:
        normalized_url = (url or "").strip()
        if not normalized_url:
            return "skip", "empty_url"

        parsed = urlparse(normalized_url)
        if parsed.scheme not in {"http", "https"}:
            return "skip", "unsupported_scheme"

        if not parsed.netloc:
            return "skip", "missing_host"

        if self._path_has_skippable_extension(parsed.path):
            return "skip", "direct_file_url"

        if self._has_skippable_path_segment(parsed.path):
            return "skip", "download_or_asset_endpoint"

        if self._is_probably_tracking_or_redirect_url(parsed):
            return "skip", "tracking_or_redirect_url"

        if not self._has_meaningful_text_context(normalized_url):
            return "skip", "low_text_context"

        return "allow", "content_page_candidate"

    async def _search_query_urls(
        self,
        query: str,
        ctx: "RequestContext",
    ) -> List[str]:
        logger.info(
            "ШАГ INTERNET.1. SearXNG search — НАЧАЛО: request_id=%s query=%s engine=%s base_url=%s limit=%d headers=%s",
            ctx.request_id,
            query,
            self._searxng_engine,
            self._searxng_base_url,
            self._max_pages,
            {
                "Accept": SEARXNG_REQUEST_HEADERS["Accept"],
                "User-Agent": SEARXNG_REQUEST_HEADERS["User-Agent"],
                "X-Forwarded-For": SEARXNG_REQUEST_HEADERS["X-Forwarded-For"],
                "X-Real-IP": SEARXNG_REQUEST_HEADERS["X-Real-IP"],
            },
        )
        search_url = f"{self._searxng_base_url}/search"
        params = {
            "q": query,
            "format": "json",
            "language": "ru-RU",
            "engines": self._searxng_engine,
        }
        accepted_urls: List[str] = []
        seen_urls: set[str] = set()

        async with httpx.AsyncClient(timeout=self._timeout) as client:
            try:
                response = await client.get(search_url, params=params, headers=SEARXNG_REQUEST_HEADERS)
                response.raise_for_status()
                payload = response.json()
            except httpx.HTTPStatusError as exc:
                response_text_preview = exc.response.text[:500] if exc.response is not None else ""
                logger.error(
                    "ШАГ INTERNET.1. SearXNG search — ОШИБКА HTTP: request_id=%s query=%s status=%s url=%s params=%s headers=%s response_preview=%s",
                    ctx.request_id,
                    query,
                    exc.response.status_code if exc.response is not None else "unknown",
                    str(exc.request.url) if exc.request is not None else search_url,
                    params,
                    {
                        "Accept": SEARXNG_REQUEST_HEADERS["Accept"],
                        "User-Agent": SEARXNG_REQUEST_HEADERS["User-Agent"],
                        "X-Forwarded-For": SEARXNG_REQUEST_HEADERS["X-Forwarded-For"],
                        "X-Real-IP": SEARXNG_REQUEST_HEADERS["X-Real-IP"],
                    },
                    response_text_preview,
                )
                return []
            except Exception as exc:
                logger.error(
                    "ШАГ INTERNET.1. SearXNG search — ОШИБКА: request_id=%s query=%s error=%s",
                    ctx.request_id,
                    query,
                    exc,
                )
                return []

        results = payload.get("results", []) if isinstance(payload, dict) else []
        logger.info(
            "ШАГ INTERNET.2. SearXNG search — ОТВЕТ ПОЛУЧЕН: request_id=%s query=%s raw_results=%d",
            ctx.request_id,
            query,
            len(results),
        )

        for result_index, result in enumerate(results, start=1):
            candidate_url = self._normalize_search_result_url(str(result.get("url") or ""))
            if not self._is_search_result_acceptable(candidate_url):
                logger.info(
                    "ШАГ INTERNET.3. SearXNG search — ПРОПУСК RESULT: request_id=%s query=%s result_index=%d url=%s reason=invalid_or_internal",
                    ctx.request_id,
                    query,
                    result_index,
                    candidate_url,
                )
                continue
            if candidate_url in seen_urls:
                logger.info(
                    "ШАГ INTERNET.3. SearXNG search — ПРОПУСК RESULT: request_id=%s query=%s result_index=%d url=%s reason=duplicate",
                    ctx.request_id,
                    query,
                    result_index,
                    candidate_url,
                )
                continue

            seen_urls.add(candidate_url)
            accepted_urls.append(candidate_url)
            logger.info(
                "ШАГ INTERNET.4. SearXNG search — URL ПРИНЯТ: request_id=%s query=%s result_index=%d accepted=%d/%d title=%s url=%s",
                ctx.request_id,
                query,
                result_index,
                len(accepted_urls),
                self._max_pages,
                str(result.get("title") or "")[:120],
                candidate_url,
            )
            if len(accepted_urls) >= self._max_pages:
                break

        logger.info(
            "ШАГ INTERNET.5. SearXNG search — ЗАВЕРШЕНО: request_id=%s query=%s accepted_urls=%d",
            ctx.request_id,
            query,
            len(accepted_urls),
        )
        return accepted_urls

    async def health_check(self) -> Dict[str, Any]:
        if not self._base_url:
            return {"status": "not_configured"}
        async with httpx.AsyncClient(timeout=5.0) as client:
            resp = await client.get(f"{self._base_url}/health")
            resp.raise_for_status()
            return resp.json()

    async def crawl_urls(
        self, urls: List[str], ctx: "RequestContext",
    ) -> List["Snippet"]:
        from AI.llm_service import Snippet  # локально: защита от циклического импорта

        logger.info(
            "ШАГ CRAWL. Краулинг URL-ов: request_id=%s, urls=%d — ОТПРАВЛЯЕМ",
            ctx.request_id,
            len(urls),
        )
        if not self._base_url:
            logger.warning("ШАГ CRAWL. CrawlerClient не настроен (нет base_url) — пропускаем")
            return []

        snippets: List[Snippet] = []
        client_timeout = self._timeout + HTTP_TIMEOUT_BUFFER_SECONDS
        cache_mode = "BYPASS" if "свеж" in str(getattr(ctx, "query", "")).lower() or "новост" in str(getattr(ctx, "query", "")).lower() else "ENABLED"
        crawl_payload: Dict[str, Any] = {
            "urls": urls[: self._max_pages],
            "word_count_threshold": self._word_count_threshold,
            "timeout_ms": int(self._timeout * 1000),
            "magic": True,
            "scan_full_page": True,
            "exclude_social_media_links": True,
            "exclude_external_links": True,
            "return_format": "fit_markdown",
            "cache_mode": cache_mode,
        }
        logger.info(
            "ШАГ CRAWL. Подготовлен payload для crawler_server: request_id=%s timeout_seconds=%.2f client_timeout_seconds=%.2f cache_mode=%s payload=%s",
            ctx.request_id,
            self._timeout,
            client_timeout,
            cache_mode,
            crawl_payload,
        )
        async with httpx.AsyncClient(timeout=client_timeout) as client:
            headers: Dict[str, str] = {"Content-Type": "application/json"}
            if self._api_key:
                headers["Authorization"] = f"Bearer {self._api_key}"

            try:
                response = await client.post(
                    f"{self._base_url}/crawl",
                    json=crawl_payload,
                    headers=headers,
                )
                response.raise_for_status()
                data = response.json()

                for item in data.get("results", []):
                    if not item.get("success"):
                        logger.warning(
                            "ШАГ CRAWL. URL %s — краулинг неуспешен: %s",
                            item.get("url", "?"),
                            item.get("error", "?"),
                        )
                        continue

                    text = str(item.get("fit_markdown") or item.get("text") or "").strip()
                    if not text:
                        logger.info(
                            "ШАГ CRAWL. URL %s — пропуск пустого контента после fit_markdown/text",
                            item.get("url", "?"),
                        )
                        continue

                    snippets.append(Snippet(
                        text=text,
                        source_id=item.get("url", ""),
                        score=1.0,
                        metadata={
                            "url": item.get("url", ""),
                            "title": item.get("title", ""),
                            "return_format": item.get("return_format", "fit_markdown"),
                            "cache_mode": item.get("cache_mode", cache_mode),
                            "link_anchor_map": item.get("link_anchor_map", {}),
                        },
                    ))
            except Exception as exc:
                logger.error(
                    "ШАГ CRAWL. ОШИБКА при краулинге: request_id=%s client_timeout_seconds=%.2f error=%s",
                    ctx.request_id,
                    client_timeout,
                    exc,
                )

        logger.info("ШАГ CRAWL. УСПЕХ: %d сниппетов", len(snippets))
        return snippets

    async def search(
        self, queries: List[str], ctx: "RequestContext",
    ) -> List["Snippet"]:
        logger.info(
            "ШАГ INTERNET. Поиск в интернете: request_id=%s, queries=%d, searxng_base_url=%s, engine=%s",
            ctx.request_id,
            len(queries),
            self._searxng_base_url,
            self._searxng_engine,
        )
        if not self._base_url:
            logger.warning(
                "ШАГ INTERNET. CrawlerClient не настроен (нет base_url) — пропускаем",
            )
            return []

        urls_to_crawl: List[str] = []
        seen_urls_to_crawl: set[str] = set()
        for query_index, q in enumerate(queries[: self._max_pages], start=1):
            if self._is_url(q):
                normalized_url = q.strip()
                if normalized_url not in seen_urls_to_crawl:
                    urls_to_crawl.append(normalized_url)
                    seen_urls_to_crawl.add(normalized_url)
                logger.info(
                    "ШАГ INTERNET.6. Прямой URL принят без поиска: request_id=%s query_index=%d url=%s",
                    ctx.request_id,
                    query_index,
                    normalized_url,
                )
                continue

            logger.info(
                "ШАГ INTERNET.6. Выполняем web search через SearXNG: request_id=%s query_index=%d query=%s",
                ctx.request_id,
                query_index,
                q,
            )
            search_urls = await self._search_query_urls(q, ctx)
            if not search_urls:
                logger.info(
                    "ШАГ INTERNET.7. По запросу не найдено валидных URL: request_id=%s query_index=%d query=%s",
                    ctx.request_id,
                    query_index,
                    q,
                )
                continue

            for search_url in search_urls:
                if search_url in seen_urls_to_crawl:
                    logger.info(
                        "ШАГ INTERNET.7. Пропускаем duplicate URL перед краулингом: request_id=%s query_index=%d url=%s",
                        ctx.request_id,
                        query_index,
                        search_url,
                    )
                    continue
                urls_to_crawl.append(search_url)
                seen_urls_to_crawl.add(search_url)

        if not urls_to_crawl:
            logger.warning(
                "ШАГ INTERNET.8. После SearXNG не осталось URL для краулинга: request_id=%s",
                ctx.request_id,
            )
            return []

        filtered_urls_to_crawl: List[str] = []
        for candidate_index, candidate_url in enumerate(urls_to_crawl, start=1):
            decision, reason = self._classify_precrawl_candidate(candidate_url)
            if decision == "skip":
                logger.info(
                    "ШАГ INTERNET.9. Candidate filter — SKIP: request_id=%s candidate_index=%d status=%s reason=%s url=%s",
                    ctx.request_id,
                    candidate_index,
                    decision,
                    reason,
                    candidate_url,
                )
                continue

            filtered_urls_to_crawl.append(candidate_url)
            logger.info(
                "ШАГ INTERNET.9. Candidate filter — ALLOW: request_id=%s candidate_index=%d status=%s reason=%s url=%s",
                ctx.request_id,
                candidate_index,
                decision,
                reason,
                candidate_url,
            )

        if not filtered_urls_to_crawl:
            logger.warning(
                "ШАГ INTERNET.10. После candidate filter не осталось URL для краулинга: request_id=%s raw_urls=%d",
                ctx.request_id,
                len(urls_to_crawl),
            )
            return []

        logger.info(
            "ШАГ INTERNET.11. Подготовлен список URL для краулинга: request_id=%s raw_urls=%d filtered_urls=%d",
            ctx.request_id,
            len(urls_to_crawl),
            len(filtered_urls_to_crawl),
        )

        snippets = await self.crawl_urls(filtered_urls_to_crawl, ctx)
        logger.info("ШАГ INTERNET. УСПЕХ: %d сниппетов", len(snippets))
        return snippets
