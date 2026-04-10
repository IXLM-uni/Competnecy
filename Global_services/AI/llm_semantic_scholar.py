# -*- coding: utf-8 -*-
"""
Руководство к файлу llm_semantic_scholar.py
===========================================

Назначение:
    Вынесенный модуль интеграции Semantic Scholar из llm_service.py.
    Содержит:
      - S2SearchFilter
      - S2FieldInference
      - S2Client
      - S2_* константы

Контракт совместимости:
    Публичные имена и сигнатуры сохранены, чтобы use-cases работали
    без изменения импортов через фасад AI.llm_service.

Техническое правило:
    Для избежания циклических импортов runtime-зависимости на llm_service.py
    (LLMRequest/LLMMessage) подтягиваются локально внутри методов.
"""

from __future__ import annotations

import asyncio
import json
import logging
import os
from dataclasses import dataclass
from typing import TYPE_CHECKING, Any, Dict, List, Optional

if TYPE_CHECKING:
    from AI.llm_service import OpenAIClient, RequestContext

logger = logging.getLogger(__name__)


S2_VALID_FIELDS_OF_STUDY: List[str] = [
    "Computer Science", "Medicine", "Chemistry", "Biology",
    "Materials Science", "Physics", "Geology", "Psychology",
    "Art", "History", "Geography", "Sociology", "Business",
    "Political Science", "Economics", "Philosophy", "Mathematics",
    "Engineering", "Environmental Science",
    "Agricultural and Food Sciences", "Education", "Linguistics",
]

S2_PAPER_FIELDS: List[str] = [
    "paperId", "title", "abstract", "year", "citationCount",
    "referenceCount", "authors", "venue", "openAccessPdf",
    "tldr", "fieldsOfStudy",
]

S2_AUTHOR_SEARCH_FIELDS: List[str] = [
    "authorId", "name", "affiliations", "paperCount",
    "citationCount", "hIndex",
]

S2_AUTHOR_DETAIL_FIELDS: List[str] = [
    "authorId", "name", "affiliations", "paperCount",
    "citationCount", "hIndex", "aliases", "homepage", "url",
]

S2_CITATION_FIELDS: List[str] = [
    "paperId", "title", "abstract", "year", "citationCount",
    "authors", "venue",
]

S2_RATE_LIMIT_DELAY: float = 0.6


@dataclass
class S2SearchFilter:
    """Фильтры для поиска статей в Semantic Scholar."""

    fields_of_study: Optional[List[str]] = None
    year: Optional[str] = None
    min_citation_count: Optional[int] = None
    open_access_pdf: bool = False

    def to_api_params(self) -> Dict[str, Any]:
        """Конвертирует фильтры в параметры для SemanticScholar SDK."""
        params: Dict[str, Any] = {}
        if self.fields_of_study:
            valid = [f for f in self.fields_of_study if f in S2_VALID_FIELDS_OF_STUDY]
            if valid:
                params["fields_of_study"] = ",".join(valid)
        if self.year:
            params["year"] = self.year
        if self.min_citation_count is not None:
            params["min_citation_count"] = self.min_citation_count
        if self.open_access_pdf:
            params["open_access_pdf"] = True
        return params


class S2FieldInference:
    """LLM-инференс fieldsOfStudy из запроса и/или истории диалога."""

    _SYSTEM_PROMPT: str = (
        "Ты — классификатор научных областей. "
        "На основе запроса пользователя и (опциональной) истории диалога "
        "определи наиболее подходящие области исследований (fieldsOfStudy) "
        "для поиска в Semantic Scholar.\n\n"
        "Допустимые области:\n"
        + "\n".join(f"- {f}" for f in S2_VALID_FIELDS_OF_STUDY)
        + "\n\nВерни ТОЛЬКО JSON-массив строк (1-3 области). "
        "Если тема слишком общая или не относится ни к одной области — верни пустой массив [].\n"
        "Пример: [\"Computer Science\", \"Mathematics\"]"
    )

    def __init__(self, llm_client: "OpenAIClient") -> None:
        self._llm = llm_client

    async def infer(
        self,
        query: str,
        ctx: "RequestContext",
        history: Optional[List[Dict[str, str]]] = None,
    ) -> List[str]:
        """Определяет подходящие fieldsOfStudy для запроса через LLM."""
        from AI.llm_service import LLMMessage, LLMRequest  # локально: защита от циклического импорта

        logger.info(
            "ШАГ S2 FIELD INFERENCE 1. Определяем fieldsOfStudy для запроса: query_len=%d, has_history=%s, request_id=%s",
            len(query), bool(history), ctx.request_id,
        )

        user_content = f"Запрос: {query}"
        if history:
            history_text = "\n".join(
                f"{m.get('role', 'user')}: {m.get('content', '')[:200]}"
                for m in history[-5:]
            )
            user_content += f"\n\nИстория диалога (последние сообщения):\n{history_text}"

        try:
            request = LLMRequest(
                messages=[
                    LLMMessage(role="system", content=self._SYSTEM_PROMPT),
                    LLMMessage(role="user", content=user_content),
                ],
                model=self._llm._default_model,
                temperature=0.1,
                max_output_tokens=256,
            )
            response = await self._llm.create_response(request, ctx)

            raw = response.content.strip()
            if raw.startswith("```"):
                raw = raw.split("\n", 1)[-1].rsplit("```", 1)[0].strip()

            fields = json.loads(raw)
            if not isinstance(fields, list):
                logger.warning(
                    "ШАГ S2 FIELD INFERENCE 2. LLM вернул не массив: %s",
                    type(fields).__name__,
                )
                return []

            valid = [f for f in fields if f in S2_VALID_FIELDS_OF_STUDY]
            logger.info(
                "ШАГ S2 FIELD INFERENCE 2. УСПЕХ: inferred=%s, valid=%s",
                fields,
                valid,
            )
            return valid

        except Exception as exc:
            logger.warning(
                "ШАГ S2 FIELD INFERENCE 2. ОШИБКА инференса: %s — продолжаем без фильтра fieldsOfStudy",
                exc,
            )
            return []


class S2Client:
    """Асинхронный клиент Semantic Scholar API."""

    def __init__(
        self,
        api_key: Optional[str] = None,
        llm_client: Optional["OpenAIClient"] = None,
        rate_limit_delay: float = S2_RATE_LIMIT_DELAY,
    ) -> None:
        self._api_key = api_key or os.environ.get("S2_API_KEY")
        self._rate_limit_delay = rate_limit_delay
        self._sch: Any = None
        self._field_inference: Optional[S2FieldInference] = None
        if llm_client:
            self._field_inference = S2FieldInference(llm_client)
        logger.info(
            "ШАГ S2 CLIENT INIT. api_key=%s, llm_inference=%s, rate_limit=%.2fs",
            "задан" if self._api_key else "нет",
            bool(self._field_inference),
            self._rate_limit_delay,
        )

    def _ensure_client(self) -> Any:
        """Ленивая инициализация клиента SemanticScholar."""
        if self._sch is None:
            from semanticscholar import SemanticScholar

            if self._api_key:
                logger.info(
                    "ШАГ S2 CLIENT. Создаём S2 клиент с API ключом (повышенные лимиты)",
                )
                self._sch = SemanticScholar(api_key=self._api_key)
            else:
                logger.info(
                    "ШАГ S2 CLIENT. Создаём S2 клиент без ключа (1 req/sec)",
                )
                self._sch = SemanticScholar()
        return self._sch

    async def infer_fields(
        self,
        query: str,
        ctx: "RequestContext",
        history: Optional[List[Dict[str, str]]] = None,
    ) -> List[str]:
        """Определяет fieldsOfStudy через LLM (делегирует S2FieldInference)."""
        if not self._field_inference:
            logger.debug(
                "ШАГ S2 INFER. LLM-клиент не задан — пропускаем инференс",
            )
            return []
        return await self._field_inference.infer(query, ctx, history)

    @staticmethod
    def _parse_tldr(obj: Any) -> str:
        tldr_val = getattr(obj, "tldr", None)
        if isinstance(tldr_val, dict):
            return tldr_val.get("text", "")
        if tldr_val is not None:
            return getattr(tldr_val, "text", "") or ""
        return ""

    @staticmethod
    def paper_to_dict(p: Any, include_tldr: bool = True) -> Dict[str, Any]:
        d: Dict[str, Any] = {
            "paperId": getattr(p, "paperId", None),
            "title": getattr(p, "title", None) or "",
            "abstract": getattr(p, "abstract", None) or "",
            "year": getattr(p, "year", None),
            "citationCount": getattr(p, "citationCount", 0) or 0,
            "authors": [
                {"name": getattr(a, "name", "Unknown")}
                for a in (getattr(p, "authors", None) or [])
            ],
            "venue": getattr(p, "venue", None) or "",
            "fieldsOfStudy": getattr(p, "fieldsOfStudy", None) or [],
        }
        if include_tldr:
            d["tldr"] = S2Client._parse_tldr(p)
        oap = getattr(p, "openAccessPdf", None)
        if oap:
            d["openAccessPdf"] = (
                oap if isinstance(oap, dict)
                else {"url": getattr(oap, "url", None)}
            )
        ref_count = getattr(p, "referenceCount", None)
        if ref_count is not None:
            d["referenceCount"] = ref_count or 0
        return d

    @staticmethod
    def author_to_dict(a: Any, extended: bool = False) -> Dict[str, Any]:
        d: Dict[str, Any] = {
            "authorId": getattr(a, "authorId", None),
            "name": getattr(a, "name", "Unknown"),
            "affiliations": getattr(a, "affiliations", None) or [],
            "paperCount": getattr(a, "paperCount", 0) or 0,
            "citationCount": getattr(a, "citationCount", 0) or 0,
            "hIndex": getattr(a, "hIndex", 0) or 0,
        }
        if extended:
            d["aliases"] = getattr(a, "aliases", None) or []
            d["homepage"] = getattr(a, "homepage", None)
            d["url"] = getattr(a, "url", None)
        return d

    @staticmethod
    def paper_embed_text(paper: Dict[str, Any]) -> str:
        title = paper.get("title", "")
        abstract = paper.get("abstract", "")
        return f"{title}. {abstract}" if abstract else title

    @staticmethod
    def paper_citation_key(paper: Dict[str, Any]) -> str:
        authors = paper.get("authors", [])
        first_author = (
            authors[0]["name"].split()[-1] if authors else "Unknown"
        )
        year = paper.get("year", "n.d.")
        if len(authors) > 2:
            return f"[{first_author} et al., {year}]"
        if len(authors) == 2:
            second_author = authors[1]["name"].split()[-1]
            return f"[{first_author} & {second_author}, {year}]"
        return f"[{first_author}, {year}]"

    @staticmethod
    def paper_to_text(paper: Dict[str, Any]) -> str:
        parts = [f"Title: {paper.get('title', 'N/A')}"]
        authors = paper.get("authors", [])
        if authors:
            names = ", ".join(a["name"] for a in authors[:5])
            if len(authors) > 5:
                names += f" et al. ({len(authors)} авторов)"
            parts.append(f"Authors: {names}")
        if paper.get("year"):
            parts.append(f"Year: {paper['year']}")
        if paper.get("venue"):
            parts.append(f"Venue: {paper['venue']}")
        if paper.get("citationCount"):
            parts.append(f"Citations: {paper['citationCount']}")
        if paper.get("abstract"):
            parts.append(f"Abstract: {paper['abstract']}")
        tldr = paper.get("tldr", "")
        if tldr:
            parts.append(f"TL;DR: {tldr}")
        if paper.get("fieldsOfStudy"):
            parts.append(f"Fields: {', '.join(paper['fieldsOfStudy'])}")
        return "\n".join(parts)

    async def search_papers(
        self,
        query: str,
        limit: int = 10,
        fields: Optional[List[str]] = None,
        filters: Optional["S2SearchFilter"] = None,
    ) -> List[Dict[str, Any]]:
        logger.info(
            "ШАГ S2 SEARCH 1. Поиск статей: query='%s', limit=%d, has_filters=%s",
            query[:80], limit, bool(filters),
        )
        sch = self._ensure_client()
        loop = asyncio.get_event_loop()
        _fields = fields or S2_PAPER_FIELDS

        kwargs: Dict[str, Any] = {
            "query": query, "limit": limit, "fields": _fields,
        }
        if filters:
            api_params = filters.to_api_params()
            if "fields_of_study" in api_params:
                kwargs["fields_of_study"] = api_params["fields_of_study"]
            if "year" in api_params:
                kwargs["year"] = api_params["year"]
            if "min_citation_count" in api_params:
                kwargs["min_citation_count"] = api_params["min_citation_count"]
            if "open_access_pdf" in api_params:
                kwargs["open_access_pdf"] = api_params["open_access_pdf"]
            logger.info("ШАГ S2 SEARCH 1. Фильтры API: %s", api_params)

        try:
            results = await loop.run_in_executor(
                None, lambda: sch.search_paper(**kwargs),
            )
            papers = [self.paper_to_dict(p) for p in results]
            logger.info(
                "ШАГ S2 SEARCH 2. УСПЕХ: найдено %d статей", len(papers),
            )
            return papers
        except Exception as exc:
            logger.error(
                "ШАГ S2 SEARCH 2. ОШИБКА поиска '%s': %s", query[:50], exc,
            )
            return []

    async def get_paper(
        self,
        paper_id: str,
        fields: Optional[List[str]] = None,
    ) -> Optional[Dict[str, Any]]:
        logger.info(
            "ШАГ S2 GET PAPER 1. Загрузка статьи: paper_id='%s'",
            paper_id[:50],
        )
        sch = self._ensure_client()
        loop = asyncio.get_event_loop()
        _fields = fields or S2_PAPER_FIELDS

        try:
            result = await loop.run_in_executor(
                None, lambda: sch.get_paper(paper_id, fields=_fields),
            )
            paper = self.paper_to_dict(result)
            logger.info(
                "ШАГ S2 GET PAPER 2. УСПЕХ: '%s' (%s)",
                paper.get("title", "N/A")[:60], paper.get("year"),
            )
            return paper
        except Exception as exc:
            logger.error(
                "ШАГ S2 GET PAPER 2. ОШИБКА загрузки '%s': %s",
                paper_id, exc,
            )
            return None

    async def search_authors(
        self,
        query: str,
        limit: int = 3,
    ) -> List[Dict[str, Any]]:
        logger.info(
            "ШАГ S2 SEARCH AUTHORS 1. Поиск авторов: query='%s', limit=%d",
            query[:80], limit,
        )
        sch = self._ensure_client()
        loop = asyncio.get_event_loop()

        try:
            results = await loop.run_in_executor(
                None,
                lambda: sch.search_author(
                    query, limit=limit, fields=S2_AUTHOR_SEARCH_FIELDS,
                ),
            )
            authors = [self.author_to_dict(a) for a in results]
            logger.info(
                "ШАГ S2 SEARCH AUTHORS 2. УСПЕХ: найдено %d авторов",
                len(authors),
            )
            return authors
        except Exception as exc:
            logger.error(
                "ШАГ S2 SEARCH AUTHORS 2. ОШИБКА поиска '%s': %s",
                query[:50], exc,
            )
            return []

    async def get_author(
        self,
        author_id: str,
    ) -> Optional[Dict[str, Any]]:
        logger.info(
            "ШАГ S2 GET AUTHOR 1. Загрузка автора: author_id='%s'",
            author_id,
        )
        sch = self._ensure_client()
        loop = asyncio.get_event_loop()

        try:
            result = await loop.run_in_executor(
                None,
                lambda: sch.get_author(
                    author_id, fields=S2_AUTHOR_DETAIL_FIELDS,
                ),
            )
            author = self.author_to_dict(result, extended=True)
            logger.info(
                "ШАГ S2 GET AUTHOR 2. УСПЕХ: '%s' (h-index=%d)",
                author.get("name"), author.get("hIndex", 0),
            )
            return author
        except Exception as exc:
            logger.error(
                "ШАГ S2 GET AUTHOR 2. ОШИБКА загрузки автора '%s': %s",
                author_id, exc,
            )
            return None

    async def get_author_papers(
        self,
        author_id: str,
        limit: int = 10,
        fields: Optional[List[str]] = None,
    ) -> List[Dict[str, Any]]:
        logger.info(
            "ШАГ S2 AUTHOR PAPERS 1. Загрузка публикаций автора '%s', limit=%d",
            author_id, limit,
        )
        sch = self._ensure_client()
        loop = asyncio.get_event_loop()
        _fields = fields or [
            "paperId", "title", "abstract", "year",
            "citationCount", "venue", "authors",
        ]

        try:
            results = await loop.run_in_executor(
                None,
                lambda: sch.get_author_papers(
                    author_id, limit=limit, fields=_fields,
                ),
            )
            papers = [
                self.paper_to_dict(p, include_tldr=False) for p in results
            ]
            papers.sort(key=lambda x: x["citationCount"], reverse=True)
            papers = papers[:limit]
            logger.info(
                "ШАГ S2 AUTHOR PAPERS 2. УСПЕХ: %d публикаций загружено",
                len(papers),
            )
            return papers
        except Exception as exc:
            logger.error(
                "ШАГ S2 AUTHOR PAPERS 2. ОШИБКА загрузки статей автора '%s': %s",
                author_id, exc,
            )
            return []

    async def get_paper_citations(
        self,
        paper_id: str,
        limit: int = 20,
        fields: Optional[List[str]] = None,
    ) -> List[Dict[str, Any]]:
        logger.info(
            "ШАГ S2 CITATIONS 1. Загрузка цитирований: paper_id='%s', limit=%d",
            paper_id[:50], limit,
        )
        sch = self._ensure_client()
        loop = asyncio.get_event_loop()
        _fields = fields or S2_CITATION_FIELDS

        try:
            results = await loop.run_in_executor(
                None,
                lambda: sch.get_paper_citations(
                    paper_id, limit=limit, fields=_fields,
                ),
            )
            citations: List[Dict[str, Any]] = []
            for item in results:
                citing = getattr(item, "citingPaper", item)
                if citing is None:
                    continue
                paper_dict = self.paper_to_dict(citing, include_tldr=False)
                if paper_dict.get("paperId"):
                    citations.append(paper_dict)
            logger.info(
                "ШАГ S2 CITATIONS 2. УСПЕХ: %d цитирований загружено",
                len(citations),
            )
            return citations
        except Exception as exc:
            logger.error(
                "ШАГ S2 CITATIONS 2. ОШИБКА загрузки цитирований '%s': %s",
                paper_id, exc,
            )
            return []

    async def get_paper_references(
        self,
        paper_id: str,
        limit: int = 20,
        fields: Optional[List[str]] = None,
    ) -> List[Dict[str, Any]]:
        logger.info(
            "ШАГ S2 REFERENCES 1. Загрузка ссылок: paper_id='%s', limit=%d",
            paper_id[:50], limit,
        )
        sch = self._ensure_client()
        loop = asyncio.get_event_loop()
        _fields = fields or S2_CITATION_FIELDS

        try:
            results = await loop.run_in_executor(
                None,
                lambda: sch.get_paper_references(
                    paper_id, limit=limit, fields=_fields,
                ),
            )
            references: List[Dict[str, Any]] = []
            for item in results:
                cited = getattr(item, "citedPaper", item)
                if cited is None:
                    continue
                paper_dict = self.paper_to_dict(cited, include_tldr=False)
                if paper_dict.get("paperId"):
                    references.append(paper_dict)
            logger.info(
                "ШАГ S2 REFERENCES 2. УСПЕХ: %d ссылок загружено",
                len(references),
            )
            return references
        except Exception as exc:
            logger.error(
                "ШАГ S2 REFERENCES 2. ОШИБКА загрузки ссылок '%s': %s",
                paper_id, exc,
            )
            return []

    async def get_recommendations_single(
        self,
        paper_id: str,
        limit: int = 20,
        fields: Optional[List[str]] = None,
    ) -> List[Dict[str, Any]]:
        logger.info(
            "ШАГ S2 RECS SINGLE 1. Рекомендации для paper_id='%s', limit=%d",
            paper_id[:50], limit,
        )
        sch = self._ensure_client()
        loop = asyncio.get_event_loop()
        _fields = fields or S2_PAPER_FIELDS

        try:
            results = await loop.run_in_executor(
                None,
                lambda: sch.get_recommended_papers(
                    paper_id, limit=limit, fields=_fields,
                ),
            )
            recs = [
                self.paper_to_dict(p)
                for p in results
                if getattr(p, "paperId", None)
            ]
            logger.info(
                "ШАГ S2 RECS SINGLE 2. УСПЕХ: %d рекомендаций получено",
                len(recs),
            )
            return recs
        except Exception as exc:
            logger.error(
                "ШАГ S2 RECS SINGLE 2. ОШИБКА рекомендаций для '%s': %s",
                paper_id, exc,
            )
            return []

    async def get_recommendations_from_lists(
        self,
        positive_ids: List[str],
        negative_ids: Optional[List[str]] = None,
        limit: int = 20,
        fields: Optional[List[str]] = None,
    ) -> List[Dict[str, Any]]:
        logger.info(
            "ШАГ S2 RECS LISTS 1. Рекомендации: positive=%d, negative=%d, limit=%d",
            len(positive_ids), len(negative_ids or []), limit,
        )
        sch = self._ensure_client()
        loop = asyncio.get_event_loop()
        _fields = fields or S2_PAPER_FIELDS
        _negative = negative_ids or []

        try:
            results = await loop.run_in_executor(
                None,
                lambda: sch.get_recommended_papers_from_lists(
                    positive_paper_ids=positive_ids,
                    negative_paper_ids=_negative,
                    limit=limit,
                    fields=_fields,
                ),
            )
            recs = [
                self.paper_to_dict(p)
                for p in results
                if getattr(p, "paperId", None)
            ]
            logger.info(
                "ШАГ S2 RECS LISTS 2. УСПЕХ: %d рекомендаций получено",
                len(recs),
            )
            return recs
        except Exception as exc:
            logger.error(
                "ШАГ S2 RECS LISTS 2. ОШИБКА рекомендаций от списков: %s",
                exc,
            )
            return []
