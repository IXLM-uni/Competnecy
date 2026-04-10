# -*- coding: utf-8 -*-
"""
Руководство к файлу crawler_server.py
======================================

Назначение:
    Тонкий FastAPI-сервер поверх библиотеки crawl4ai (AsyncWebCrawler).
    Предоставляет HTTP API для краулинга URL-ов и возврата markdown-контента,
    а также нормализованного JSON всех ссылок, найденных на странице-источнике,
    и агрегированного объекта link_anchor_map формата «фраза ссылки -> список href/context/scope».
    Используется CrawlerClient из llm_service.py (endpoint POST /crawl).

Расширение извлечения ссылок:
    ШАГ LINKS.1. Сначала сервер пытается взять структурированные ссылки из result.links.
    ШАГ LINKS.2. Если result.links пустой, сервер делает fallback-парсинг ссылок из fit_markdown/raw_markdown.
    ШАГ LINKS.3. Если markdown тоже не дал ссылок, сервер делает fallback-парсинг anchor href из cleaned_html.
    ШАГ LINKS.4. После извлечения ссылок сервер строит link_anchor_map, где ключом выступает anchor phrase,
                 а значением — список объектов ссылки без дубликатов.
    Это защищает контракт от версий Crawl4AI, где markdown уже содержит ссылки, а result.links не заполнен.

Расширение контракта Crawl4AI:
    Сервер принимает не только базовые timeout/word_count_threshold,
    но и продвинутые параметры quality/runtime-контура:
        - magic
        - scan_full_page
        - exclude_external_links
        - exclude_social_media_links
        - return_format
        - cache_mode
    Это позволяет клиенту запрашивать fit_markdown, антибот-режим,
    автоскролл и кэширование без изменения внешнего HTTP endpoint.

Endpoints:
    GET  /health         — проверка доступности сервиса.
    POST /crawl          — краулинг одного или нескольких URL, возвращает markdown + метаданные.

Формат запроса POST /crawl:
    {
        "urls": ["https://example.com"],      // список URL для краулинга
        "word_count_threshold": 10,            // опц., мин. кол-во слов в блоке
        "timeout_ms": 30000,                   // опц., таймаут навигации (мс)
        "magic": true,                         // опц., антибот / smart extraction
        "scan_full_page": true,                // опц., автоскролл страницы
        "exclude_external_links": true,        // опц., вычищать внешние ссылки
        "exclude_social_media_links": true,    // опц., вычищать соцсети
        "return_format": "fit_markdown",      // opt., fit_markdown | raw_markdown | text
        "cache_mode": "ENABLED"               // opt., ENABLED | BYPASS | READ_ONLY | WRITE_ONLY
    }

Формат ответа POST /crawl:
    {
        "results": [
            {
                "url": "https://example.com",
                "text": "... markdown контент ...",
                "fit_markdown": "... очищенный markdown ...",
                "links": [{"href": "...", "description": "..."}],
                "links_total": 12,
                "link_anchor_map": {
                    "Узнать больше": [{"href": "https://example.com/docs", "scope": "internal", "context": "..."}]
                },
                "title": "Example Domain",
                "return_format": "fit_markdown",
                "cache_mode": "ENABLED",
                "success": true,
                "error": null
            }
        ]
    }

Запуск (Docker):
    docker build --target crawler4ai -t crawler4ai-local -f AI/Dockerfile .
    docker run -d --name crawler4ai -p 11235:11235 crawler4ai-local

Запуск (локально, для отладки):
    cd Global_services
    pip install "crawl4ai>=0.4" "fastapi" "uvicorn[standard]"
    crawl4ai-setup
    python -m uvicorn AI.crawler_server:app --host 0.0.0.0 --port 11235

Переменные окружения:
    CRAWL4AI_PORT       — порт сервера (по умолчанию 11235).
    CRAWL4AI_TIMEOUT_MS — таймаут навигации по умолчанию (по умолчанию 30000).

Логирование:
    Все шаги логируются в формате «ШАГ N. <описание> — ОТПРАВЛЯЕМ / УСПЕХ / ОШИБКА».

"""
from __future__ import annotations

import asyncio
import collections
import logging
import os
import re
import time
from enum import Enum
from typing import Any, Dict, List, Optional
from urllib.parse import urlparse

from fastapi import FastAPI, HTTPException
from pydantic import BaseModel, Field

logger = logging.getLogger("crawler_server")
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s | %(levelname)-7s | %(name)s | %(message)s",
)

app = FastAPI(title="Crawler4AI Server", version="1.0.0")

# ---------------------------------------------------------------------------
# Глобальный экземпляр краулера (инициализируется при старте)
# ---------------------------------------------------------------------------

_crawler_instance = None
_crawler_lock = asyncio.Lock()


async def _get_crawler():
    """Ленивая инициализация AsyncWebCrawler (singleton)."""
    global _crawler_instance
    if _crawler_instance is not None:
        return _crawler_instance

    async with _crawler_lock:
        if _crawler_instance is not None:
            return _crawler_instance

        logger.info("ШАГ 0. Инициализация AsyncWebCrawler — ОТПРАВЛЯЕМ")
        try:
            from crawl4ai import AsyncWebCrawler, BrowserConfig

            browser_cfg = BrowserConfig(
                headless=True,
                browser_type="chromium",
                verbose=False,
            )
            crawler = AsyncWebCrawler(config=browser_cfg)
            await crawler.start()
            _crawler_instance = crawler
            logger.info("ШАГ 0. Инициализация AsyncWebCrawler — УСПЕХ")
        except Exception as exc:
            logger.error("ШАГ 0. Инициализация AsyncWebCrawler — ОШИБКА: %s", exc)
            raise

    return _crawler_instance


# ---------------------------------------------------------------------------
# DTO
# ---------------------------------------------------------------------------


class CrawlRequest(BaseModel):
    """Запрос на краулинг."""
    urls: List[str] = Field(..., min_length=1, description="Список URL для краулинга")
    word_count_threshold: int = Field(default=10, description="Мин. слов в текстовом блоке")
    timeout_ms: int = Field(default=30000, description="Таймаут навигации (мс)")
    magic: bool = Field(default=True, description="Включить smart/magic extraction")
    scan_full_page: bool = Field(default=True, description="Включить автоскролл страницы")
    exclude_external_links: bool = Field(default=True, description="Удалять внешние ссылки из markdown")
    exclude_social_media_links: bool = Field(default=True, description="Удалять social media ссылки из markdown")
    return_format: str = Field(default="fit_markdown", description="Предпочитаемый формат ответа: fit_markdown | raw_markdown | text")
    cache_mode: str = Field(default="BYPASS", description="Режим кэша Crawl4AI")


class CrawlResultItem(BaseModel):
    """Результат краулинга одного URL."""
    url: str
    text: str = ""
    fit_markdown: str = ""
    raw_markdown: str = ""
    links: List[Dict[str, Any]] = Field(default_factory=list)
    links_total: int = 0
    link_anchor_map: Dict[str, List[Dict[str, str]]] = Field(default_factory=dict)
    title: str = ""
    return_format: str = "fit_markdown"
    cache_mode: str = "BYPASS"
    success: bool = True
    error: Optional[str] = None


class CrawlResponse(BaseModel):
    """Ответ на запрос краулинга."""
    results: List[CrawlResultItem]


# ---------------------------------------------------------------------------
# Endpoints
# ---------------------------------------------------------------------------


class _ReturnFormat(str, Enum):
    FIT_MARKDOWN = "fit_markdown"
    RAW_MARKDOWN = "raw_markdown"
    TEXT = "text"


def _resolve_cache_mode(cache_mode_value: str):
    from crawl4ai import CacheMode

    normalized = (cache_mode_value or "BYPASS").strip().upper()
    mapping = {
        "ENABLED": CacheMode.ENABLED,
        "BYPASS": CacheMode.BYPASS,
        "READ_ONLY": CacheMode.READ_ONLY,
        "WRITE_ONLY": CacheMode.WRITE_ONLY,
    }
    resolved = mapping.get(normalized, CacheMode.BYPASS)
    logger.info(
        "ШАГ CFG. resolve_cache_mode — requested=%s resolved=%s",
        cache_mode_value,
        normalized if normalized in mapping else "BYPASS",
    )
    return resolved, normalized if normalized in mapping else "BYPASS"


def _extract_markdown_payload(result: Any) -> Dict[str, str]:
    markdown_obj = getattr(result, "markdown", None)
    fit_markdown = ""
    raw_markdown = ""
    text = ""

    if isinstance(markdown_obj, str):
        raw_markdown = markdown_obj
    elif markdown_obj is not None:
        fit_markdown = str(getattr(markdown_obj, "fit_markdown", "") or "")
        raw_markdown = str(getattr(markdown_obj, "raw_markdown", "") or "")

    text = fit_markdown or raw_markdown or str(getattr(result, "cleaned_html", "") or "")
    return {
        "fit_markdown": fit_markdown,
        "raw_markdown": raw_markdown,
        "text": text,
    }


def _resolve_text_by_format(markdown_payload: Dict[str, str], return_format: str) -> str:
    normalized = (return_format or _ReturnFormat.FIT_MARKDOWN.value).strip().lower()
    if normalized == _ReturnFormat.RAW_MARKDOWN.value:
        return markdown_payload.get("raw_markdown") or markdown_payload.get("fit_markdown") or markdown_payload.get("text") or ""
    if normalized == _ReturnFormat.TEXT.value:
        return markdown_payload.get("text") or markdown_payload.get("fit_markdown") or markdown_payload.get("raw_markdown") or ""
    return markdown_payload.get("fit_markdown") or markdown_payload.get("text") or markdown_payload.get("raw_markdown") or ""


def _normalize_link_text(value: Any) -> str:
    return " ".join(str(value or "").split())


def _build_link_description(anchor_text: str, link_title: str, context: str) -> str:
    for candidate in (context, link_title, anchor_text):
        normalized = _normalize_link_text(candidate)
        if normalized:
            return normalized
    return "Описание ссылки отсутствует"


def _build_link_record(
    *,
    source_url: str,
    page_title: str,
    scope: str,
    href: str,
    anchor_text: str = "",
    link_title: str = "",
    context: str = "",
    rel: str = "",
) -> Dict[str, Any]:
    normalized_href = _normalize_link_text(href)
    normalized_anchor_text = _normalize_link_text(anchor_text)
    normalized_link_title = _normalize_link_text(link_title)
    normalized_context = _normalize_link_text(context)
    normalized_rel = _normalize_link_text(rel)
    domain = urlparse(normalized_href).netloc.lower()
    description = _build_link_description(normalized_anchor_text, normalized_link_title, normalized_context)
    return {
        "source_url": source_url,
        "page_title": page_title,
        "scope": scope,
        "href": normalized_href,
        "anchor_text": normalized_anchor_text,
        "link_title": normalized_link_title,
        "context": normalized_context,
        "description": description,
        "domain": domain,
        "rel": normalized_rel,
    }


def _resolve_link_scope(source_url: str, href: str) -> str:
    source_netloc = urlparse(source_url).netloc.lower()
    href_netloc = urlparse(href).netloc.lower()
    if source_netloc and href_netloc and source_netloc == href_netloc:
        return "internal"
    return "external"


def _deduplicate_links(links: List[Dict[str, Any]], source_url: str, strategy_name: str) -> List[Dict[str, Any]]:
    deduplicated_links: List[Dict[str, Any]] = []
    seen_keys: set[tuple[str, str, str]] = set()
    for item in links:
        href = _normalize_link_text(item.get("href"))
        if not href:
            continue
        key = (
            href,
            _normalize_link_text(item.get("anchor_text")),
            _normalize_link_text(item.get("scope")),
        )
        if key in seen_keys:
            continue
        seen_keys.add(key)
        deduplicated_links.append(item)
    logger.info(
        "ШАГ LINKS.DEDUP. Дедупликация ссылок завершена: strategy=%s source_url=%s before=%d after=%d",
        strategy_name,
        source_url,
        len(links),
        len(deduplicated_links),
    )
    return deduplicated_links


def _extract_links_from_result_links(result: Any, source_url: str, page_title: str) -> List[Dict[str, Any]]:
    raw_links = getattr(result, "links", None)
    if not isinstance(raw_links, dict):
        logger.info(
            "ШАГ LINKS.1. result.links отсутствует или не dict: source_url=%s raw_type=%s",
            source_url,
            type(raw_links).__name__,
        )
        return []

    normalized_links: List[Dict[str, Any]] = []
    for scope in ("internal", "external"):
        scope_items = raw_links.get(scope, [])
        if not isinstance(scope_items, list):
            logger.info(
                "ШАГ LINKS.1. scope=%s пропущен: ожидался list, получен=%s source_url=%s",
                scope,
                type(scope_items).__name__,
                source_url,
            )
            continue

        for index, raw_item in enumerate(scope_items, start=1):
            if not isinstance(raw_item, dict):
                logger.info(
                    "ШАГ LINKS.1. scope=%s item=%d пропущен: ожидался dict, получен=%s source_url=%s",
                    scope,
                    index,
                    type(raw_item).__name__,
                    source_url,
                )
                continue

            href = _normalize_link_text(raw_item.get("href"))
            if not href:
                logger.info(
                    "ШАГ LINKS.1. scope=%s item=%d пропущен: пустой href source_url=%s",
                    scope,
                    index,
                    source_url,
                )
                continue

            anchor_text = _normalize_link_text(raw_item.get("text"))
            link_title = _normalize_link_text(raw_item.get("title"))
            context = _normalize_link_text(raw_item.get("context"))
            rel = _normalize_link_text(raw_item.get("rel"))
            normalized_links.append(
                _build_link_record(
                    source_url=source_url,
                    page_title=page_title,
                    scope=scope,
                    href=href,
                    anchor_text=anchor_text,
                    link_title=link_title,
                    context=context,
                    rel=rel,
                )
            )

    normalized_links = _deduplicate_links(normalized_links, source_url, "result.links")
    logger.info(
        "ШАГ LINKS.1. Нормализация result.links завершена: source_url=%s page_title=%s total_links=%d",
        source_url,
        page_title[:100],
        len(normalized_links),
    )
    return normalized_links


def _extract_links_from_markdown(markdown_text: str, source_url: str, page_title: str) -> List[Dict[str, Any]]:
    if not markdown_text:
        logger.info("ШАГ LINKS.2. Markdown fallback пропущен: пустой markdown source_url=%s", source_url)
        return []

    markdown_pattern = re.compile(r"\[([^\]]*)\]\((https?://[^)\s]+)(?:\s+\"([^\"]*)\")?\)")
    extracted_links: List[Dict[str, Any]] = []
    for match_index, match in enumerate(markdown_pattern.finditer(markdown_text), start=1):
        anchor_text, href, link_title = match.groups()
        context_start = max(0, match.start() - 160)
        context_end = min(len(markdown_text), match.end() + 160)
        context = markdown_text[context_start:context_end]
        scope = _resolve_link_scope(source_url, href)
        extracted_links.append(
            _build_link_record(
                source_url=source_url,
                page_title=page_title,
                scope=scope,
                href=href,
                anchor_text=anchor_text,
                link_title=link_title or "",
                context=context,
            )
        )
        if match_index <= 5:
            logger.info(
                "ШАГ LINKS.2. Markdown fallback match: source_url=%s match_index=%d href=%s anchor_text=%s",
                source_url,
                match_index,
                href,
                _normalize_link_text(anchor_text)[:120],
            )

    extracted_links = _deduplicate_links(extracted_links, source_url, "markdown")
    logger.info(
        "ШАГ LINKS.2. Markdown fallback завершён: source_url=%s total_links=%d markdown_length=%d",
        source_url,
        len(extracted_links),
        len(markdown_text),
    )
    return extracted_links


def _extract_links_from_html(cleaned_html: str, source_url: str, page_title: str) -> List[Dict[str, Any]]:
    if not cleaned_html:
        logger.info("ШАГ LINKS.3. HTML fallback пропущен: пустой cleaned_html source_url=%s", source_url)
        return []

    anchor_pattern = re.compile(
        r"<a\b(?P<attrs>[^>]*)href=[\"'](?P<href>https?://[^\"']+)[\"'](?P<attrs_tail>[^>]*)>(?P<text>.*?)</a>",
        re.IGNORECASE | re.DOTALL,
    )
    title_pattern = re.compile(r"title=[\"']([^\"']*)[\"']", re.IGNORECASE)
    rel_pattern = re.compile(r"rel=[\"']([^\"']*)[\"']", re.IGNORECASE)
    tag_strip_pattern = re.compile(r"<[^>]+>")
    extracted_links: List[Dict[str, Any]] = []

    for match_index, match in enumerate(anchor_pattern.finditer(cleaned_html), start=1):
        href = match.group("href") or ""
        attrs = f"{match.group('attrs') or ''} {match.group('attrs_tail') or ''}"
        title_match = title_pattern.search(attrs)
        rel_match = rel_pattern.search(attrs)
        anchor_text = tag_strip_pattern.sub(" ", match.group("text") or "")
        context_start = max(0, match.start() - 160)
        context_end = min(len(cleaned_html), match.end() + 160)
        context = tag_strip_pattern.sub(" ", cleaned_html[context_start:context_end])
        scope = _resolve_link_scope(source_url, href)
        extracted_links.append(
            _build_link_record(
                source_url=source_url,
                page_title=page_title,
                scope=scope,
                href=href,
                anchor_text=anchor_text,
                link_title=title_match.group(1) if title_match else "",
                context=context,
                rel=rel_match.group(1) if rel_match else "",
            )
        )
        if match_index <= 5:
            logger.info(
                "ШАГ LINKS.3. HTML fallback match: source_url=%s match_index=%d href=%s anchor_text=%s",
                source_url,
                match_index,
                href,
                _normalize_link_text(anchor_text)[:120],
            )

    extracted_links = _deduplicate_links(extracted_links, source_url, "cleaned_html")
    logger.info(
        "ШАГ LINKS.3. HTML fallback завершён: source_url=%s page_title=%s total_links=%d cleaned_html_length=%d",
        source_url,
        page_title[:100],
        len(extracted_links),
        len(cleaned_html),
    )
    return extracted_links


def _build_link_anchor_map(
    links: List[Dict[str, Any]],
    source_url: str,
    include_context: bool = True,
) -> Dict[str, List[Dict[str, str]]]:
    anchor_map: Dict[str, List[Dict[str, str]]] = collections.defaultdict(list)

    for link_index, link in enumerate(links, start=1):
        phrase = _normalize_link_text(
            link.get("anchor_text") or link.get("description") or link.get("link_title") or ""
        )
        href = _normalize_link_text(link.get("href"))
        if not phrase or not href:
            logger.info(
                "ШАГ LINKS.4. Link anchor map item пропущен: source_url=%s link_index=%d phrase_len=%d href_present=%s",
                source_url,
                link_index,
                len(phrase),
                bool(href),
            )
            continue

        entry: Dict[str, str] = {
            "href": href,
        }
        if include_context:
            entry["scope"] = _normalize_link_text(link.get("scope"))
            entry["context"] = _normalize_link_text(link.get("context"))
            entry["link_title"] = _normalize_link_text(link.get("link_title"))

        already_exists = any(existing.get("href") == href for existing in anchor_map[phrase])
        if already_exists:
            logger.info(
                "ШАГ LINKS.4. Дубликат phrase+href пропущен: source_url=%s link_index=%d phrase=%s href=%s",
                source_url,
                link_index,
                phrase[:120],
                href[:200],
            )
            continue

        anchor_map[phrase].append(entry)

    normalized_anchor_map = dict(anchor_map)
    logger.info(
        "ШАГ LINKS.4. Построение link_anchor_map завершено: source_url=%s phrases_total=%d links_total=%d include_context=%s",
        source_url,
        len(normalized_anchor_map),
        sum(len(items) for items in normalized_anchor_map.values()),
        include_context,
    )
    return normalized_anchor_map


def _extract_anchor_map_from_markdown(markdown_text: str, source_url: str) -> Dict[str, List[Dict[str, str]]]:
    if not markdown_text:
        logger.info("ШАГ LINKS.4M. Markdown anchor fallback пропущен: пустой markdown source_url=%s", source_url)
        return {}

    markdown_pattern = re.compile(r"\[([^\]]+)\]\((https?://[^)\s]+)(?:\s+\"([^\"]*)\")?\)")
    anchor_map: Dict[str, List[Dict[str, str]]] = collections.defaultdict(list)
    for match_index, match in enumerate(markdown_pattern.finditer(markdown_text), start=1):
        phrase = _normalize_link_text(match.group(1))
        href = _normalize_link_text(match.group(2))
        link_title = _normalize_link_text(match.group(3) or "")
        if not phrase or not href:
            continue

        context_start = max(0, match.start() - 160)
        context_end = min(len(markdown_text), match.end() + 160)
        context = _normalize_link_text(markdown_text[context_start:context_end])
        scope = _resolve_link_scope(source_url, href)

        already_exists = any(existing.get("href") == href for existing in anchor_map[phrase])
        if already_exists:
            continue

        anchor_map[phrase].append(
            {
                "href": href,
                "scope": scope,
                "context": context,
                "link_title": link_title,
            }
        )
        if match_index <= 5:
            logger.info(
                "ШАГ LINKS.4M. Markdown anchor fallback match: source_url=%s match_index=%d phrase=%s href=%s",
                source_url,
                match_index,
                phrase[:120],
                href[:200],
            )

    normalized_anchor_map = dict(anchor_map)
    logger.info(
        "ШАГ LINKS.4M. Markdown anchor fallback завершён: source_url=%s phrases_total=%d links_total=%d markdown_length=%d",
        source_url,
        len(normalized_anchor_map),
        sum(len(items) for items in normalized_anchor_map.values()),
        len(markdown_text),
    )
    return normalized_anchor_map


def _extract_links_payload(result: Any, source_url: str, page_title: str, markdown_payload: Dict[str, str]) -> List[Dict[str, Any]]:
    links_from_result = _extract_links_from_result_links(result, source_url, page_title)
    if links_from_result:
        logger.info(
            "ШАГ LINKS.FINAL. Используем result.links как источник истины: source_url=%s total_links=%d",
            source_url,
            len(links_from_result),
        )
        return links_from_result

    logger.warning(
        "ШАГ LINKS.FINAL. result.links пустой — включаем markdown fallback: source_url=%s",
        source_url,
    )
    markdown_text = markdown_payload.get("fit_markdown") or markdown_payload.get("raw_markdown") or ""
    links_from_markdown = _extract_links_from_markdown(markdown_text, source_url, page_title)
    if links_from_markdown:
        logger.info(
            "ШАГ LINKS.FINAL. Используем markdown fallback: source_url=%s total_links=%d",
            source_url,
            len(links_from_markdown),
        )
        return links_from_markdown

    logger.warning(
        "ШАГ LINKS.FINAL. Markdown fallback не дал ссылок — включаем HTML fallback: source_url=%s",
        source_url,
    )
    cleaned_html = str(getattr(result, "cleaned_html", "") or "")
    links_from_html = _extract_links_from_html(cleaned_html, source_url, page_title)
    if links_from_html:
        logger.info(
            "ШАГ LINKS.FINAL. Используем HTML fallback: source_url=%s total_links=%d",
            source_url,
            len(links_from_html),
        )
        return links_from_html

    logger.warning(
        "ШАГ LINKS.FINAL. Все стратегии извлечения ссылок вернули 0 результатов: source_url=%s page_title=%s fit_markdown_len=%d raw_markdown_len=%d cleaned_html_len=%d",
        source_url,
        page_title[:100],
        len(markdown_payload.get("fit_markdown", "")),
        len(markdown_payload.get("raw_markdown", "")),
        len(cleaned_html),
    )
    return []


def _build_final_link_anchor_map(
    links_payload: List[Dict[str, Any]],
    markdown_payload: Dict[str, str],
    source_url: str,
) -> Dict[str, List[Dict[str, str]]]:
    anchor_map = _build_link_anchor_map(links_payload, source_url, include_context=True)
    if anchor_map:
        logger.info(
            "ШАГ LINKS.5. Используем link_anchor_map из normalized links: source_url=%s phrases_total=%d",
            source_url,
            len(anchor_map),
        )
        return anchor_map

    logger.warning(
        "ШАГ LINKS.5. normalized links не дали anchor map — включаем markdown anchor fallback: source_url=%s",
        source_url,
    )
    markdown_text = markdown_payload.get("fit_markdown") or markdown_payload.get("raw_markdown") or ""
    anchor_map = _extract_anchor_map_from_markdown(markdown_text, source_url)
    if anchor_map:
        logger.info(
            "ШАГ LINKS.5. Используем markdown anchor fallback: source_url=%s phrases_total=%d",
            source_url,
            len(anchor_map),
        )
        return anchor_map

    logger.warning(
        "ШАГ LINKS.5. Все стратегии построения link_anchor_map вернули 0 результатов: source_url=%s fit_markdown_len=%d raw_markdown_len=%d",
        source_url,
        len(markdown_payload.get("fit_markdown", "")),
        len(markdown_payload.get("raw_markdown", "")),
    )
    return {}


@app.get("/health")
async def health() -> Dict[str, str]:
    """Проверка доступности сервиса."""
    logger.info("ШАГ HEALTH. Проверка здоровья — ОТПРАВЛЯЕМ")
    try:
        crawler = await _get_crawler()
        logger.info("ШАГ HEALTH. Проверка здоровья — УСПЕХ")
        return {"status": "ok", "crawler": "ready"}
    except Exception as exc:
        logger.error("ШАГ HEALTH. Проверка здоровья — ОШИБКА: %s", exc)
        return {"status": "degraded", "error": str(exc)}


@app.post("/crawl", response_model=CrawlResponse)
async def crawl(request: CrawlRequest) -> CrawlResponse:
    """Краулинг URL-ов: загрузка страниц и возврат markdown-контента."""
    logger.info(
        "ШАГ 1. Получен запрос на краулинг: urls=%d, word_count_threshold=%d, timeout_ms=%d, magic=%s, scan_full_page=%s, exclude_external_links=%s, exclude_social_media_links=%s, return_format=%s, cache_mode=%s",
        len(request.urls), request.word_count_threshold, request.timeout_ms,
        request.magic,
        request.scan_full_page,
        request.exclude_external_links,
        request.exclude_social_media_links,
        request.return_format,
        request.cache_mode,
    )

    try:
        crawler = await _get_crawler()
    except Exception as exc:
        logger.error("ШАГ 1. Краулер недоступен — ОШИБКА: %s", exc)
        raise HTTPException(status_code=503, detail=f"Crawler not ready: {exc}")

    from crawl4ai import CrawlerRunConfig

    resolved_cache_mode, resolved_cache_mode_name = _resolve_cache_mode(request.cache_mode)
    run_cfg = CrawlerRunConfig(
        cache_mode=resolved_cache_mode,
        word_count_threshold=request.word_count_threshold,
        page_timeout=request.timeout_ms,
        magic=request.magic,
        scan_full_page=request.scan_full_page,
        exclude_external_links=request.exclude_external_links,
        exclude_social_media_links=request.exclude_social_media_links,
    )
    logger.info(
        "ШАГ 1.1. CrawlerRunConfig собран: cache_mode=%s page_timeout=%d word_count_threshold=%d magic=%s scan_full_page=%s exclude_external_links=%s exclude_social_media_links=%s",
        resolved_cache_mode_name,
        request.timeout_ms,
        request.word_count_threshold,
        request.magic,
        request.scan_full_page,
        request.exclude_external_links,
        request.exclude_social_media_links,
    )

    results: List[CrawlResultItem] = []

    for idx, url in enumerate(request.urls, 1):
        logger.info("ШАГ 2.%d. Краулинг URL: %s — ОТПРАВЛЯЕМ", idx, url)
        started = time.time()

        try:
            result = await crawler.arun(url=url, config=run_cfg)
            elapsed = round(time.time() - started, 2)

            if result.success:
                markdown_payload = _extract_markdown_payload(result)
                response_text = _resolve_text_by_format(markdown_payload, request.return_format)

                title = ""
                if hasattr(result, "metadata") and isinstance(result.metadata, dict):
                    title = result.metadata.get("title", "")
                normalized_source_url = str(getattr(result, "url", "") or url)
                links_payload = _extract_links_payload(result, normalized_source_url, title, markdown_payload)
                link_anchor_map = _build_final_link_anchor_map(links_payload, markdown_payload, normalized_source_url)

                logger.info(
                    "ШАГ 2.%d. Краулинг URL: %s — УСПЕХ: response_text_len=%d fit_markdown_len=%d raw_markdown_len=%d title='%s' links_total=%d anchor_phrases_total=%d return_format=%s cache_mode=%s elapsed=%.2fs",
                    idx,
                    url,
                    len(response_text),
                    len(markdown_payload.get("fit_markdown", "")),
                    len(markdown_payload.get("raw_markdown", "")),
                    title[:50],
                    len(links_payload),
                    len(link_anchor_map),
                    request.return_format,
                    resolved_cache_mode_name,
                    elapsed,
                )
                results.append(CrawlResultItem(
                    url=normalized_source_url,
                    text=response_text,
                    fit_markdown=markdown_payload.get("fit_markdown", ""),
                    raw_markdown=markdown_payload.get("raw_markdown", ""),
                    links=links_payload,
                    links_total=len(links_payload),
                    link_anchor_map=link_anchor_map,
                    title=title,
                    return_format=request.return_format,
                    cache_mode=resolved_cache_mode_name,
                    success=True,
                ))
            else:
                error_msg = getattr(result, "error_message", "Unknown error")
                logger.warning(
                    "ШАГ 2.%d. Краулинг URL: %s — ОШИБКА краулинга: %s, elapsed=%.2fs",
                    idx, url, error_msg, elapsed,
                )
                results.append(CrawlResultItem(
                    url=url,
                    text="",
                    fit_markdown="",
                    raw_markdown="",
                    links=[],
                    links_total=0,
                    link_anchor_map={},
                    title="",
                    return_format=request.return_format,
                    cache_mode=resolved_cache_mode_name,
                    success=False,
                    error=str(error_msg),
                ))

        except Exception as exc:
            elapsed = round(time.time() - started, 2)
            logger.error(
                "ШАГ 2.%d. Краулинг URL: %s — ИСКЛЮЧЕНИЕ: %s, elapsed=%.2fs",
                idx, url, exc, elapsed,
            )
            results.append(CrawlResultItem(
                url=url,
                text="",
                fit_markdown="",
                raw_markdown="",
                links=[],
                links_total=0,
                link_anchor_map={},
                title="",
                return_format=request.return_format,
                cache_mode=resolved_cache_mode_name,
                success=False,
                error=str(exc),
            ))

    logger.info(
        "ШАГ 3. Краулинг завершён: всего=%d, успешных=%d, ошибок=%d",
        len(results),
        sum(1 for r in results if r.success),
        sum(1 for r in results if not r.success),
    )
    return CrawlResponse(results=results)


@app.on_event("shutdown")
async def shutdown():
    """Корректное завершение краулера."""
    global _crawler_instance
    if _crawler_instance is not None:
        logger.info("Завершение работы краулера...")
        try:
            await _crawler_instance.close()
        except Exception as exc:
            logger.warning("Ошибка при закрытии краулера: %s", exc)
        _crawler_instance = None


# ---------------------------------------------------------------------------
# Точка входа (для запуска через python -m)
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    import uvicorn

    port = int(os.environ.get("CRAWL4AI_PORT", "11235"))
    logger.info("Запуск crawler_server на порту %d", port)
    uvicorn.run(
        "AI.crawler_server:app",
        host="0.0.0.0",
        port=port,
        log_level="info",
    )
