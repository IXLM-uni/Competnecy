"""
RESEARCH INGESTION SERVICE

Ответственность:
- Сбор корпуса источников по роли и деятельности
- Нормализация в markdown-формат
- Создание source registry и manifest
- Поддержка множественных источников: web, API, файлы

Источники:
- Вакансии (hh.ru, LinkedIn, Telegram каналы)
- Профстандарты и ESCO
- Научные статьи (Semantic Scholar) 
- Course syllabi
- Документация инструментов
- Экспертные интервью

Выход:
- raw_corpus/ - нормализованные markdown источники
- raw_corpus_manifest.md - индекс источников
- source_registry.md - метаданные источников

Принципы:
- Markdown-first хранение
- Provenance tracking (URL, дата, тип)
- Batch processing для эффективности
- Фильтрация нерелевантного контента
"""

import asyncio
import logging
import json
import hashlib
import sys
import os
from datetime import datetime
from pathlib import Path
from dataclasses import dataclass
from typing import List, Dict, Optional, Any, Union
from urllib.parse import urlparse

from .llm_helpers import init_env, get_llm_client, get_env_config, call_llm, make_ctx

from AI.llm_webcrawler import (
    CrawlerClient,
    CrawlerQueryRewriter
)
from AI.llm_semantic_scholar import (
    S2Client,
    S2SearchFilter
)

logger = logging.getLogger(__name__)

@dataclass
class SourceSpec:
    """Спецификация источника для сбора"""
    source_type: str  # 'web_search', 'hh_vacancies', 'semantic_scholar', 'file_upload', 'telegram', 'reddit', 'onet', 'sonar'
    query: str
    filters: Optional[Dict[str, Any]] = None
    limit: int = 50
    priority: str = 'medium'  # 'high', 'medium', 'low'

@dataclass 
class SourceArtifact:
    """Нормализованный источник"""
    source_id: str
    source_type: str
    title: str
    content: str  # markdown
    url: Optional[str] = None
    metadata: Optional[Dict[str, Any]] = None
    retrieved_at: Optional[str] = None
    relevance_score: Optional[float] = None

class ResearchIngestionService:
    """
    Сервис сбора и нормализации исследовательских источников
    """
    
    def __init__(self, artifacts_dir: str = "./artifacts"):
        """
        Инициализация сервиса
        
        Args:
            artifacts_dir: Директория для сохранения артефактов
        """
        logger.info("ШАГ 1. Инициализация ResearchIngestionService")

        self.artifacts_dir = Path(artifacts_dir)
        self.raw_corpus_dir = self.artifacts_dir / "raw_corpus"
        self.raw_corpus_dir.mkdir(parents=True, exist_ok=True)

        # Инициализируем через llm_helpers
        self.env_config = init_env()
        self.llm_client = get_llm_client()
        self.crawler_client = CrawlerClient(
            base_url=self.env_config.get('CRAWLER_BASE_URL', 'http://localhost:8001'),
            timeout=10.0,  # Агрессивный таймаут — skip denied быстро
        )
        self.query_rewriter = CrawlerQueryRewriter(llm_client=self.llm_client)
        self.s2_client = S2Client(
            api_key=self.env_config.get('S2_API_KEY'),
            rate_limit_delay=float(self.env_config.get('S2_RATE_LIMIT_DELAY', '0.6')),
            llm_client=self.llm_client,
        )

        logger.info("ШАГ 2. Инициализация клиентов завершена")
        
    async def collect_sources(self, role_scope: str, source_specs: List[SourceSpec]) -> List[SourceArtifact]:
        """
        Основной метод сбора источников
        
        Args:
            role_scope: Описание целевой роли
            source_specs: Список спецификаций источников
            
        Returns:
            Список нормализованных источников
        """
        logger.info(f"ШАГ 3. Начинаем ПАРАЛЛЕЛЬНЫЙ сбор источников для роли: {role_scope[:100]}...")

        # Параллельный сбор из ВСЕХ источников одновременно
        async def _collect_one(i: int, spec: SourceSpec) -> List[SourceArtifact]:
            logger.info(f"ШАГ 4.{i}. [{spec.source_type}] {spec.query[:50]}...")
            try:
                collectors = {
                    'web_search': self._collect_web_sources,
                    'hh_vacancies': self._collect_hh_vacancies,
                    'semantic_scholar': self._collect_academic_papers,
                    'telegram': self._collect_telegram_sources,
                    'linkedin': self._collect_linkedin_sources,
                    'reddit': self._collect_reddit_sources,
                    'onet': self._collect_onet_sources,
                    'sonar': self._collect_sonar_sources,
                    'file_upload': self._process_uploaded_files,
                }
                collector = collectors.get(spec.source_type)
                if not collector:
                    return []
                if spec.source_type == 'file_upload':
                    arts = await collector(spec)
                else:
                    arts = await collector(spec, role_scope)
                logger.info(f"ШАГ 4.{i}. [{spec.source_type}] -> {len(arts)} артефактов")

                # SSE source events
                from .llm_helpers import emit_sse
                for art in arts:
                    await emit_sse("source", {
                        "type": art.source_type,
                        "title": art.title[:80],
                        "url": art.url or "",
                        "score": art.relevance_score,
                    })
                return arts
            except Exception as e:
                logger.error(f"ШАГ 4.{i}. [{spec.source_type}] ОШИБКА: {e}")
                return []

        results = await asyncio.gather(
            *[_collect_one(i, spec) for i, spec in enumerate(source_specs, 1)]
        )

        all_artifacts = []
        for arts in results:
            all_artifacts.extend(arts)

        logger.info(f"ШАГ 5. Всего собрано {len(all_artifacts)} артефактов")

        # Быстрая keyword-фильтрация (без LLM!)
        relevant_artifacts = self._keyword_filter(all_artifacts, role_scope)
        
        logger.info(f"ШАГ 6. После фильтрации осталось {len(relevant_artifacts)} релевантных артефактов")
        
        return relevant_artifacts
    
    @staticmethod
    def _is_denied_content(text: str, title: str = '') -> bool:
        """Быстрая проверка: контент = access denied / captcha / блокировка."""
        if not text or len(text.strip()) < 100:
            return True
        check_text = (title + ' ' + text[:500]).lower()
        deny_signals = [
            'access denied', 'access is denied', '403 forbidden', '401 unauthorized',
            'prove your humanity', 'captcha', 'please verify', 'bot detection',
            'enable javascript', 'checking your browser', 'just a moment',
            'cloudflare', 'are you a robot', 'security check',
        ]
        return any(s in check_text for s in deny_signals)

    @staticmethod
    def _clean_navigation_markdown(raw_text: str) -> str:
        """Удаляет UI-навигацию из крауленных страниц: меню, логотипы, картинки,
        строки из одних ссылок, footer. Применяется к web/hh-выводу crawler.
        """
        import re as _re

        link_only_re = _re.compile(r"^\s*(?:\[[^\]]*\]\([^)]+\)\s*)+\s*$")
        image_re = _re.compile(r"^\s*!\[[^\]]*\]\([^)]+\)")
        footer_markers = (
            "© ", "Все права защищены", "Политика конфиденциальности",
            "Пользовательское соглашение", "Cookie", "Мы используем",
            "Обратная связь", "Подписаться", "Соцсети",
        )

        cleaned = []
        prev_empty = False
        for line in raw_text.split("\n"):
            stripped = line.strip()
            if not stripped:
                if not prev_empty:
                    cleaned.append("")
                prev_empty = True
                continue
            # Картинки
            if image_re.match(stripped):
                continue
            # Только ссылки (меню, навигация)
            if link_only_re.match(stripped):
                continue
            # Footer-маркеры — обрываем парсинг (всё дальше = footer)
            if any(m in stripped for m in footer_markers):
                break
            # Очень длинные JSON-state строки
            if len(stripped) > 1000 and stripped.startswith("{") and "\":" in stripped[:200]:
                continue
            cleaned.append(line)
            prev_empty = False

        return "\n".join(cleaned).strip()

    async def _collect_web_sources(self, spec: SourceSpec, role_scope: str) -> List[SourceArtifact]:
        """Сбор из веб-поиска через CrawlerClient + общая очистка markdown от UI-шума."""
        logger.info(f"ШАГ WEB.1. Переписываем запрос для роли: {spec.query}")
        ctx = make_ctx()

        enhanced_queries = await self.query_rewriter.rewrite(spec.query, ctx)
        logger.info(f"ШАГ WEB.2. Улучшенные запросы: {enhanced_queries}")

        snippets = await self.crawler_client.search(queries=enhanced_queries, ctx=ctx)
        logger.info(f"ШАГ WEB.3. Найдено {len(snippets)} сниппетов")

        artifacts = []
        for snippet in snippets:
            url = snippet.metadata.get('url', snippet.source_id)
            title = snippet.metadata.get('title', 'Untitled')
            if not snippet.text:
                continue
            if self._is_denied_content(snippet.text, title):
                logger.info(f"ШАГ WEB. SKIP denied content: {url[:60]}")
                continue
            cleaned = self._clean_navigation_markdown(snippet.text)
            # Если после очистки осталось почти ничего — это страница-меню/каталог
            if len(cleaned) < 200:
                logger.info(f"ШАГ WEB. SKIP empty after cleanup: {url[:60]} ({len(cleaned)} chars)")
                continue
            artifact = SourceArtifact(
                source_id=self._generate_source_id(url),
                source_type='web_search',
                title=title,
                content=cleaned,
                url=url,
                metadata={
                    'domain': urlparse(url).netloc,
                    'original_query': spec.query,
                    'enhanced_queries': enhanced_queries,
                    'raw_chars': len(snippet.text),
                    'cleaned_chars': len(cleaned),
                    'crawled_at': datetime.now().isoformat()
                },
                retrieved_at=datetime.now().isoformat()
            )
            artifacts.append(artifact)

        return artifacts
    
    async def _collect_hh_vacancies(self, spec: SourceSpec, role_scope: str) -> List[SourceArtifact]:
        """Сбор вакансий с hh.ru через LLM-маппинг профессий + Crawler4AI."""
        logger.info(f"ШАГ HH.1. Сбор вакансий hh.ru для роли: {role_scope}")

        _HH_DIR = Path(__file__).resolve().parent.parent / "Explore" / "HH"
        sys.path.insert(0, str(_HH_DIR)) if str(_HH_DIR) not in sys.path else None

        try:
            from hh_vacancy_tool import (
                load_professions_lookup,
                extract_profession_names_from_md,
                llm_select_top_professions,
                enrich_selected_professions,
                extract_vacancy_links_from_md,
                crawl_url,
            )
        except ImportError as e:
            logger.error(f"ШАГ HH. Не удалось импортировать hh_vacancy_tool: {e}")
            return []

        # 1. Загрузить справочники
        csv_path = _HH_DIR / "output" / "professions.csv"
        md_path = _HH_DIR / "output" / "professions.md"
        if not csv_path.exists() or not md_path.exists():
            logger.warning("ШАГ HH. professions.csv/md не найдены — skip")
            return []

        professions_lookup = load_professions_lookup(csv_path)
        professions_md = md_path.read_text(encoding="utf-8")
        profession_names = extract_profession_names_from_md(professions_md)
        logger.info(f"ШАГ HH.2. Загружено {len(profession_names)} профессий из справочника")

        # 2. LLM выбирает top-3 релевантных профессий из ПОЛНОГО справочника.
        # Старый срез [:200] выкидывал всю кириллицу — для русских ролей терялись
        # ключевые «бизнес-аналитик», «финансовый аналитик», «ведущий аналитик».
        # Промпт явно отделяет ROLE TITLE (что человек делает) от ИНСТРУМЕНТОВ
        # (xlsx/SQL/VBA), ОТРАСЛИ (банк) и ОБЯЗАННОСТЕЙ (автоматизация, презентации) —
        # иначе LLM подменяет «Аналитик данных в банке» на «кредитный аналитик»
        # или «automation test engineer».
        select_prompt = f"""Тебе дан полный справочник профессий с hh.ru. Выбери 3 названия,
которые точнее всего соответствуют ОСНОВНОЙ ПРОФЕССИИ из роли.

Роль: {role_scope}

КАК РАЗОБРАТЬ РОЛЬ:
1. Найди ROLE TITLE — это первые 1-3 слова, обозначающие профессию (например,
   «Аналитик Данных», «Менеджер по продажам», «Frontend Developer»).
2. Всё остальное — это КОНТЕКСТ: отрасль («в банке»), инструменты («со знанием SQL»),
   обязанности («автоматизировать процессы», «готовить презентации»).
3. Контекст НЕ должен подменять ROLE TITLE. Подбирай профессии, аналогичные TITLE.

ANTI-PATTERNS (НЕ делай так):
- Роль «Аналитик данных в банке» → НЕ выбирай «кредитный аналитик»/«финансовый
  аналитик»: они из той же отрасли, но это другая профессия.
- Роль «Аналитик данных, автоматизирует процессы» → НЕ выбирай «automation test engineer»,
  «инженер по автоматизации»: автоматизация — это его обязанность, а не специальность.
- Роль «Аналитик данных, готовит презентации» → НЕ выбирай «бизнес-аналитик»: похоже,
  но bizan работает с требованиями, а не с данными.

Если в списке есть несколько вариантов основной профессии (junior/senior/ведущий) —
бери базовый вариант + один уровневый, если уровень явно указан в роли.

Список профессий ({len(profession_names)} шт., по одной на строку):
{chr(10).join(profession_names)}

Ответь ТОЛЬКО валидным JSON массивом из 3 элементов, без пояснений и markdown:
[{{"name": "точное название из списка", "reason": "почему релевантна"}}]"""

        llm_response = await call_llm(select_prompt, temperature=0.1, max_output_tokens=500, streaming=False)
        selected = []
        if llm_response:
            import re as _re
            json_match = _re.search(r"\[.*\]", llm_response, _re.DOTALL)
            if json_match:
                try:
                    selected = json.loads(json_match.group(0))
                except json.JSONDecodeError:
                    pass
        logger.info(f"ШАГ HH.3. LLM выбрал {len(selected)} профессий: {[s.get('name','?') for s in selected]}")

        # 3. Обогащаем URL из CSV
        enriched = enrich_selected_professions(selected, professions_lookup)
        enriched = [p for p in enriched if p.get("url")]
        logger.info(f"ШАГ HH.4. Обогащено {len(enriched)} профессий с URL")

        # 4. Параллельный crawl профессий → вакансии
        crawler_url = self.env_config.get("CRAWLER_BASE_URL", "http://localhost:8001")
        artifacts: List[SourceArtifact] = []

        async def _crawl_profession(prof: dict) -> List[SourceArtifact]:
            prof_name = prof.get("name", "?")
            prof_url = prof.get("url", "")
            logger.info(f"ШАГ HH.5. Краулинг профессии: {prof_name} → {prof_url}")

            # Crawl listing page через CrawlerClient
            listing_md = None
            try:
                ctx = make_ctx()
                snippets = await self.crawler_client.crawl_urls([prof_url], ctx)
                listing_md = snippets[0].text if snippets else None
            except Exception as e:
                logger.warning(f"ШАГ HH.5. Ошибка краулинга {prof_url}: {e}")

            if not listing_md:
                logger.warning(f"ШАГ HH.5. Не удалось скраулить {prof_url}")
                return []

            # Extract vacancy links
            links = extract_vacancy_links_from_md(listing_md, prof_url, limit=5)
            logger.info(f"ШАГ HH.6. Извлечено {len(links)} ссылок на вакансии для {prof_name}")

            if not links:
                return []

            # Crawl individual vacancies (параллельно)
            ctx = make_ctx()
            vacancy_snippets = await self.crawler_client.crawl_urls(links, ctx)

            prof_artifacts = []
            for vac in vacancy_snippets:
                if vac.text and not self._is_denied_content(vac.text):
                    url = vac.metadata.get("url", vac.source_id)
                    title, clean_text = self._clean_hh_vacancy_markdown(vac.text)
                    prof_artifacts.append(SourceArtifact(
                        source_id=self._generate_source_id(url),
                        source_type="hh_vacancy",
                        title=title,
                        content=clean_text,
                        url=url,
                        metadata={
                            "source": "hh.ru",
                            "profession": prof_name,
                            "query": spec.query,
                            "crawled_at": datetime.now().isoformat(),
                        },
                        retrieved_at=datetime.now().isoformat(),
                    ))
            return prof_artifacts

        # Параллельно для всех профессий
        all_results = await asyncio.gather(
            *[_crawl_profession(p) for p in enriched],
            return_exceptions=True,
        )
        for result in all_results:
            if isinstance(result, list):
                artifacts.extend(result)

        logger.info(f"ШАГ HH.7. Собрано {len(artifacts)} вакансий с hh.ru")
        return artifacts
    
    async def _collect_academic_papers(self, spec: SourceSpec, role_scope: str) -> List[SourceArtifact]:
        """Сбор научных статей через Semantic Scholar"""
        logger.info(f"ШАГ S2.1. Поиск академических статей: {spec.query}")
        ctx = make_ctx()

        # Определяем fields of study для фильтрации
        fields = await self.s2_client.infer_fields(spec.query, ctx)
        logger.info(f"ШАГ S2.2. Определены области: {fields}")

        search_filter = S2SearchFilter(
            fields_of_study=fields[:3] if fields else None,
            year="2015",
            min_citation_count=5
        )

        papers = await self.s2_client.search_papers(
            query=spec.query,
            limit=spec.limit,
            filters=search_filter
        )
        
        logger.info(f"ШАГ S2.3. Найдено {len(papers)} релевантных статей")
        
        artifacts = []
        for paper in papers:
            # Конвертируем в markdown
            paper_text = self.s2_client.paper_to_text(paper)
            
            artifact = SourceArtifact(
                source_id=self._generate_source_id(paper.get('url', paper.get('paperId', 'unknown'))),
                source_type='academic_paper',
                title=paper.get('title', 'Untitled Paper'),
                content=paper_text,
                url=paper.get('url'),
                metadata={
                    'authors': [author.get('name') for author in paper.get('authors', [])],
                    'year': paper.get('year'),
                    'citation_count': paper.get('citationCount', 0),
                    'venue': paper.get('venue'),
                    'fields_of_study': paper.get('fieldsOfStudy', []),
                    'paper_id': paper.get('paperId')
                },
                retrieved_at=datetime.now().isoformat()
            )
            artifacts.append(artifact)
            
        return artifacts
    
    async def _collect_telegram_sources(self, spec: SourceSpec, role_scope: str) -> List[SourceArtifact]:
        """Сбор источников из Telegram — RAG-запрос к Qdrant коллекции tg_vacancy_channels."""
        logger.info(f"ШАГ TG.1. RAG-поиск в Qdrant tg_vacancy_channels: {spec.query}")
        ctx = make_ctx()

        artifacts = []
        try:
            from AI.llm_qdrant import CloudRuEmbeddingClient
            from qdrant_client import AsyncQdrantClient

            # Embed запрос
            embed_client = CloudRuEmbeddingClient(
                api_key=self.env_config['CLOUDRU_API_KEY'],
                base_url=self.env_config.get('CLOUDRU_BASE_URL', 'https://foundation-models.api.cloud.ru/v1'),
                model_name=self.env_config.get('CLOUDRU_EMBED_MODEL', 'Qwen/Qwen3-Embedding-0.6B'),
            )

            # Формируем запрос с контекстом роли
            search_query = f"{role_scope} {spec.query}"
            logger.info(f"ШАГ TG.2. Embedding запроса: {search_query[:80]}...")
            vectors = await embed_client.embed_texts([search_query], ctx)

            if not vectors:
                logger.warning("ШАГ TG.2. Не удалось получить embedding")
                return artifacts

            query_vector = vectors[0]

            # Прямой запрос к Qdrant (unnamed default vector)
            qdrant_host = self.env_config.get('QDRANT_HOST', 'localhost')
            qdrant_port = int(self.env_config.get('QDRANT_PORT', '6333'))
            qdrant = AsyncQdrantClient(host=qdrant_host, port=qdrant_port)

            limit = min(spec.limit, 15)
            logger.info(f"ШАГ TG.3. Qdrant query: collection=tg_vacancy_channels, top_k={limit}")

            results = await qdrant.query_points(
                collection_name='tg_vacancy_channels',
                query=query_vector,
                limit=limit,
                score_threshold=0.50,  # Порог релевантности
                with_payload=True,
            )

            points = results.points if hasattr(results, 'points') else results
            logger.info(f"ШАГ TG.4. Получено {len(points)} результатов из Qdrant")

            for point in points:
                payload = point.payload or {}
                text = payload.get('text', '')
                subscribers = payload.get('channel_subscribers', 0)
                if text and len(text.strip()) > 50:
                    url = payload.get('url', '')
                    channel = payload.get('channel_name', payload.get('channel_username', 'Unknown'))
                    artifact = SourceArtifact(
                        source_id=self._generate_source_id(url or str(point.id)),
                        source_type='telegram_qdrant',
                        title=f"Telegram [{channel}]: {text[:60].strip()}...",
                        content=text,
                        url=url,
                        metadata={
                            'platform': 'telegram',
                            'channel_username': payload.get('channel_username', ''),
                            'channel_name': channel,
                            'channel_subscribers': payload.get('channel_subscribers', 0),
                            'message_id': payload.get('message_id', ''),
                            'date': payload.get('date', ''),
                            'views': payload.get('views', 0),
                            'similarity_score': point.score,
                            'query': spec.query,
                            'retrieved_from': 'qdrant_tg_vacancy_channels',
                            'retrieved_at': datetime.now().isoformat(),
                        },
                        retrieved_at=datetime.now().isoformat(),
                        relevance_score=point.score,
                    )
                    artifacts.append(artifact)

            await qdrant.close()

        except Exception as e:
            import traceback
            logger.error(f"ШАГ TG. ОШИБКА RAG-запроса к Qdrant: {type(e).__name__}: {e}\n{traceback.format_exc()}")

        logger.info(f"ШАГ TG.5. Собрано {len(artifacts)} Telegram источников из Qdrant")
        return artifacts
    
    # Спам-маркеры в Reddit (продвижение курсов / партнёрки / Udemy free deals).
    # Все встречены при сборе для роли «Аналитик данных» — топ-постов от
    # u/slaconsultants*, u/easylearn___ing и т.п., которые забивали корпус мусором.
    _REDDIT_SPAM_TITLE_MARKERS = (
        "sla consultants", "by sla", "udemy", "free deals", "free udemy",
        "enroll in", "best course", "best business analytics course",
        "best data analyst course", "best financial modelling course",
        "job oriented institute", "certified course", "certification course",
        "course online and in delhi", "pwc & ibm certification",
    )
    _REDDIT_SPAM_AUTHOR_MARKERS = ("slaconsultants", "easylearn", "institute_", "courseonline")

    # Тематические subreddits с высокой долей реальных обсуждений работы аналитика
    # данных. Глобальный поиск приводил к r/udemyfreebies и партнёркам — этот
    # белый список их фильтрует на этапе самого Reddit.
    _REDDIT_DATA_SUBREDDITS = (
        "datascience", "analytics", "dataanalysis", "BusinessIntelligence",
        "SQL", "learnsql", "excel", "cscareerquestions", "datasciencejobs",
    )

    @classmethod
    def _is_reddit_spam(cls, post) -> bool:
        title_low = (post.title or "").lower()
        if any(m in title_low for m in cls._REDDIT_SPAM_TITLE_MARKERS):
            return True
        author_low = (post.author or "").lower()
        if any(m in author_low for m in cls._REDDIT_SPAM_AUTHOR_MARKERS):
            return True
        # Низкий score + субреддит про free deals — почти всегда спам
        if (post.score or 0) <= 1 and "freebie" in (post.subreddit or "").lower():
            return True
        return False

    async def _collect_reddit_sources(self, spec: SourceSpec, role_scope: str) -> List[SourceArtifact]:
        """Сбор обсуждений с Reddit — fast-fail на 403/CAPTCHA + спам-фильтр.

        Глобальный поиск отключён: для запросов про data analyst он стабильно
        возвращает партнёрский спам про курсы SLA Consultants и Udemy free deals.
        Вместо этого ищем по белому списку тематических subreddits.
        """
        logger.info(f"ШАГ RD.1. Сбор Reddit источников: {spec.query}")

        _REDDIT_DIR = Path(__file__).resolve().parent.parent / "Explore" / "Reddit"
        if str(_REDDIT_DIR) not in sys.path:
            sys.path.insert(0, str(_REDDIT_DIR))

        try:
            from reddit_client import create_reddit_client_from_env
        except ImportError as exc:
            logger.warning(f"ШАГ RD.1. RedditClient не найден ({exc}) — skip")
            return []

        # Запрашиваем больше чем нужно — после спам-фильтра останется меньше
        limit_posts = min(spec.limit * 3, 30)
        artifacts: List[SourceArtifact] = []

        try:
            async with asyncio.timeout(45):
                async with create_reddit_client_from_env() as client:
                    logger.info(
                        f"ШАГ RD.2. Reddit поиск: query={spec.query!r}, "
                        f"subreddits={list(self._REDDIT_DATA_SUBREDDITS)}, "
                        f"limit={limit_posts} (с запасом под спам-фильтр)"
                    )
                    posts = await client.search_posts(
                        query=spec.query,
                        subreddits=list(self._REDDIT_DATA_SUBREDDITS),
                        limit=limit_posts,
                        sort="relevance",
                        time_filter="year",
                    )
                    spam_count = sum(1 for p in posts if self._is_reddit_spam(p))
                    real_posts = [p for p in posts if not self._is_reddit_spam(p)][:spec.limit]
                    logger.info(
                        f"ШАГ RD.2. Получено {len(posts)} постов "
                        f"(спам отфильтрован: {spam_count}, оставлено: {len(real_posts)})"
                    )

                    for post in real_posts:
                        # Comments-эндпоинт Reddit (`/comments/{id}.json`) сейчас
                        # стабильно отдаёт 403 без OAuth. Раньше работал, теперь нет.
                        # Берём только данные из search (title + selftext) — этого
                        # достаточно для извлечения компетенций, комментарии = бонус.
                        md_lines = [
                            f"# {post.title}", "",
                            f"**r/{post.subreddit}** · u/{post.author} · {post.score} pts",
                            f"**URL:** {post.full_url}", "",
                        ]
                        if post.selftext and post.selftext not in ("[deleted]", "[removed]"):
                            md_lines.append(post.selftext[:2000])
                        artifact = SourceArtifact(
                            source_id=self._generate_source_id(post.full_url),
                            source_type="reddit",
                            title=f"Reddit: {post.title[:80]}",
                            content="\n".join(md_lines),
                            url=post.full_url,
                            metadata={"platform": "reddit", "subreddit": post.subreddit,
                                      "score": post.score,
                                      "query": spec.query, "crawled_at": datetime.now().isoformat()},
                            retrieved_at=datetime.now().isoformat(),
                        )
                        artifacts.append(artifact)

        except (TimeoutError, asyncio.TimeoutError):
            logger.warning("ШАГ RD. Reddit timeout 45с — skip")
        except Exception as exc:
            logger.error(f"ШАГ RD. ОШИБКА Reddit: {exc}")

        logger.info(f"ШАГ RD.4. Собрано {len(artifacts)} Reddit артефактов")
        return artifacts

    async def _collect_linkedin_sources(self, spec: SourceSpec, role_scope: str) -> List[SourceArtifact]:
        """Сбор источников из LinkedIn"""
        logger.info(f"ШАГ LI.1. Поиск LinkedIn контента: {spec.query}")
        ctx = make_ctx()

        linkedin_query = f"{spec.query} site:linkedin.com/jobs OR site:linkedin.com/pulse"
        snippets = await self.crawler_client.search(queries=[linkedin_query], ctx=ctx)

        artifacts = []
        li_snippets = [s for s in snippets if 'linkedin.com' in s.metadata.get('url', s.source_id)]

        if li_snippets:
            logger.info(f"ШАГ LI.2. Найдено {len(li_snippets)} LinkedIn сниппетов")
            for snippet in li_snippets:
                url = snippet.metadata.get('url', snippet.source_id)
                title = f"LinkedIn: {snippet.metadata.get('title', 'Post')}"
                if snippet.text and not self._is_denied_content(snippet.text, title):
                    artifact = SourceArtifact(
                        source_id=self._generate_source_id(url),
                        source_type='linkedin',
                        title=title,
                        content=snippet.text,
                        url=url,
                        metadata={
                            'platform': 'linkedin',
                            'query': spec.query,
                            'crawled_at': datetime.now().isoformat()
                        },
                        retrieved_at=datetime.now().isoformat()
                    )
                    artifacts.append(artifact)

        logger.info(f"ШАГ LI.3. Собрано {len(artifacts)} LinkedIn источников")
        return artifacts
    
    async def _process_uploaded_files(self, spec: SourceSpec) -> List[SourceArtifact]:
        """Обработка загруженных файлов"""
        logger.info(f"ШАГ FILE.1. Обработка файлов: {spec.query}")
        
        # spec.query содержит путь к файлам
        file_path = Path(spec.query)
        artifacts = []
        
        if file_path.is_file():
            files = [file_path]
        elif file_path.is_dir():
            files = list(file_path.glob('**/*'))
            files = [f for f in files if f.is_file()]
        else:
            logger.warning(f"ШАГ FILE.2. Путь не найден: {file_path}")
            return artifacts
            
        logger.info(f"ШАГ FILE.2. Найдено {len(files)} файлов для обработки")
        
        for file in files:
            try:
                content = self._extract_text_from_file(file)
                if content:
                    artifact = SourceArtifact(
                        source_id=self._generate_source_id(str(file)),
                        source_type='uploaded_file',
                        title=file.name,
                        content=content,
                        url=f"file://{file.absolute()}",
                        metadata={
                            'file_type': file.suffix,
                            'file_size': file.stat().st_size,
                            'uploaded_at': datetime.now().isoformat()
                        },
                        retrieved_at=datetime.now().isoformat()
                    )
                    artifacts.append(artifact)
                    
            except Exception as e:
                logger.error(f"ШАГ FILE.3. Ошибка обработки файла {file}: {e}")
                continue
                
        logger.info(f"ШАГ FILE.3. Обработано {len(artifacts)} файлов")
        return artifacts
    
    def _extract_text_from_file(self, file_path: Path) -> str:
        """Извлечение текста из файла"""
        suffix = file_path.suffix.lower()
        
        if suffix == '.md':
            return file_path.read_text(encoding='utf-8')
        elif suffix == '.txt':
            return file_path.read_text(encoding='utf-8')
        elif suffix in ['.pdf', '.docx', '.doc']:
            # Для MVP возвращаем placeholder
            return f"# {file_path.name}\n\n[PDF/DOCX content extraction not implemented yet]"
        else:
            return f"# {file_path.name}\n\n[Unsupported file type: {suffix}]"
    
    # Стоп-слова, которые из role_scope не несут смысла и дают ложные совпадения
    # (например, «в», «для», «со», «также»).
    _ROLE_STOPWORDS = {
        "и", "в", "на", "с", "со", "для", "по", "к", "у", "о", "об", "от", "из",
        "за", "до", "при", "над", "под", "без", "то", "же", "ли", "не", "ни",
        "а", "но", "или", "что", "как", "так", "также", "только", "уже", "ещё",
        "the", "a", "an", "of", "for", "to", "in", "on", "with", "and", "or",
    }

    def _keyword_filter(self, artifacts: List[SourceArtifact], role_scope: str) -> List[SourceArtifact]:
        """Быстрая keyword-фильтрация без LLM (мгновенно).

        Совпадения ищем по prefix-границам слов (\\b{stem}) — substring-матчинг
        пропускал «программу передач» по «программа», а ТВ-каналы по «анал»
        (оно matchится в «канал»). Также считаем role-specific и generic helpers
        отдельно, чтобы по generic слову одна страница не проходила.
        """
        import re as _re

        # 1. Role-specific keywords (из самой роли, без стоп-слов)
        raw_words = [w.strip(".,;:!?()[]\"'«»") for w in role_scope.lower().split()]
        role_specific = {w for w in raw_words if len(w) > 2 and w not in self._ROLE_STOPWORDS}
        # Префиксы для русской флексии («аналитик», «аналитика», «аналитики»):
        # берём первые 5 символов слова. Меньше 5 символов даёт ложные совпадения
        # типа «анал» → «канал», «банк» → «банкет».
        stems = {w[:5] for w in role_specific if len(w) > 6}
        role_specific.update(stems)

        # 2. Generic helpers (служебные термины, не служат основанием для пропуска)
        generic_helpers = {
            "skill", "requirement", "competenc", "curriculum", "education",
            "вакансия", "навык", "компетенц", "программа", "образован",
        }

        def _hits(words: set, text: str) -> int:
            return sum(1 for w in words if _re.search(rf"\b{_re.escape(w)}", text))

        # Источники, которым keyword-фильтр неприменим: они уже структурированы
        # или синтезированы из авторитетного источника, а контент англоязычный —
        # русские role-keywords там не совпадут. ONET — англ. XLSX, Sonar — синтез,
        # Reddit — англ. обсуждения отфильтрованного whitelist subreddits.
        trusted_structured = ('onet', 'sonar', 'reddit')

        filtered = []
        for art in artifacts:
            if self._is_denied_content(art.content, art.title):
                continue
            content_low = (art.title + ' ' + art.content[:2000]).lower()
            role_hits = _hits(role_specific, content_low)
            generic_hits = _hits(generic_helpers, content_low)
            # Score = смешанный, но порог проверяем по role_hits отдельно.
            keyword_score = min(
                1.0,
                (role_hits + generic_hits * 0.3) / max(len(role_specific), 1),
            )

            if art.source_type in trusted_structured:
                # Всегда пропускаем — источник авторитетный/синтезированный.
                art.relevance_score = max(art.relevance_score or 0, keyword_score)
                filtered.append(art)
            elif art.source_type == 'telegram_qdrant':
                # Вектор + keyword
                combined = (art.relevance_score or 0) * 0.5 + keyword_score * 0.5
                art.relevance_score = combined
                if role_hits >= 2 or (art.relevance_score and art.relevance_score > 0.5):
                    filtered.append(art)
            else:
                # hh_vacancy / linkedin / reddit / academic — обычно содержат
                # несколько совпадений по role-specific словам. Web-сниппеты часто
                # короче (1-2 совпадения) — порог снижен. Generic helpers
                # («программа», «вакансия») сами по себе проходными не делают —
                # иначе пропускали бы ТВ-программы и страницы про вакансии в зоопарке.
                art.relevance_score = max(art.relevance_score or 0, keyword_score)
                threshold = 1 if art.source_type == "web_search" else 2
                if role_hits >= threshold:
                    filtered.append(art)

        filtered.sort(key=lambda x: x.relevance_score or 0, reverse=True)
        logger.info(f"ШАГ FILTER. Keyword фильтрация: {len(artifacts)} -> {len(filtered)}")
        return filtered

    async def _filter_and_rank_artifacts(self, artifacts: List[SourceArtifact], role_scope: str) -> List[SourceArtifact]:
        """Фильтрация и ранжирование артефактов по релевантности"""
        logger.info(f"ШАГ RANK.1. Фильтрация {len(artifacts)} артефактов")
        
        # Простая эвристика для MVP
        filtered_artifacts = []
        
        for artifact in artifacts:
            # Базовые фильтры
            if len(artifact.content) < 100:  # Слишком короткий контент
                continue
            if 'error' in artifact.content.lower() or '404' in artifact.content:  # Ошибки краулинга
                continue
                
            # LLM-оценка релевантности (для первых 50 артефактов, чтобы не превысить rate limits)
            if len(filtered_artifacts) < 50:
                relevance_score = await self._assess_relevance(artifact, role_scope)
                artifact.relevance_score = relevance_score
                
                if relevance_score > 0.6:  # Порог релевантности
                    filtered_artifacts.append(artifact)
            else:
                # Простая эвристика для остальных
                artifact.relevance_score = 0.7  # Средняя оценка
                filtered_artifacts.append(artifact)
        
        # Сортируем по релевантности
        filtered_artifacts.sort(key=lambda x: x.relevance_score or 0, reverse=True)
        
        logger.info(f"ШАГ RANK.2. Оставлено {len(filtered_artifacts)} релевантных артефактов")
        return filtered_artifacts
    
    async def _assess_relevance(self, artifact: SourceArtifact, role_scope: str) -> float:
        """LLM-оценка релевантности артефакта"""
        try:
            prompt = f"""Оцени релевантность данного источника для роли: {role_scope}

Источник: {artifact.title}
Тип: {artifact.source_type}
Содержимое (первые 500 символов): {artifact.content[:500]}...

Верни только число от 0.0 до 1.0, где:
- 1.0 = идеально релевантно для роли
- 0.8 = очень релевантно
- 0.6 = умеренно релевантно
- 0.4 = слабо релевантно
- 0.0 = не релевантно

Число:"""

            response = await call_llm(prompt, temperature=0.1, max_output_tokens=10)

            try:
                score = float(response.strip())
                return max(0.0, min(1.0, score))
            except (ValueError, AttributeError):
                return 0.5

        except Exception as e:
            logger.warning(f"Ошибка оценки релевантности: {e}")
            return 0.5
    
    async def _collect_onet_sources(self, spec: SourceSpec, role_scope: str) -> List[SourceArtifact]:
        """Сбор данных из O*NET — LLM выбирает профессии из thin list, данные подтягиваются из xlsx."""
        logger.info(f"ШАГ ONET.1. O*NET lookup для роли: {role_scope}")

        _ONET_DIR = Path(__file__).resolve().parent.parent / "Explore" / "ONET"
        if str(_ONET_DIR) not in sys.path:
            sys.path.insert(0, str(_ONET_DIR))

        try:
            from onet_tool import load_occupation_titles, find_soc_codes, get_occupation_profile, format_onet_markdown
        except ImportError as e:
            logger.error(f"ШАГ ONET. Не удалось импортировать onet_tool: {e}")
            return []

        # 1. Thin list of titles для LLM
        titles = load_occupation_titles()
        if not titles:
            logger.warning("ШАГ ONET. Нет профессий в Occupation Data.xlsx")
            return []
        logger.info(f"ШАГ ONET.2. Загружено {len(titles)} O*NET профессий")

        # 2. LLM выбирает top-3 (подаём ТОЛЬКО titles, не xlsx).
        # Без явных правил LLM подменяет роль контекстом: для «Аналитика данных в банке»
        # выбирал «Computer Systems Analysts» / «Business Intelligence Analysts» вместо
        # точных Data Scientists / Statisticians / Financial Analysts.
        titles_text = "\n".join(titles)
        select_prompt = f"""You are mapping a job role to the closest O*NET occupations.

Role description (may be in Russian):
{role_scope}

HOW TO READ THE ROLE:
1. Extract the ROLE TITLE (the profession itself: data analyst, sales manager, etc.).
2. Treat the rest as CONTEXT: industry ("in a bank"), tools ("SQL, Excel, VBA"),
   responsibilities ("automate processes", "make presentations"). Context must NOT
   override the title.
3. Pick O*NET occupations whose CORE WORK matches the title, even if the industry
   isn't a perfect fit.

ANTI-PATTERNS:
- "Data analyst in a bank" → DO NOT pick "Computer Systems Analysts" (too generic) or
  "Credit Analysts" (different profession). Prefer "Data Scientists",
  "Statisticians", "Business Intelligence Analysts", "Financial Analysts" if multiple
  industry-relevant options exist.
- "Frontend developer who writes SQL" → DO NOT pick "Database Administrators".
- Marketing manager with Excel automation → DO NOT pick "Computer Programmers".

If multiple O*NET occupations are equally relevant, pick variants from different
families (e.g., one closer to data, one closer to the industry) so the corpus has
breadth.

Available O*NET occupations:
{titles_text}

Reply with ONLY a JSON array of 3 exact occupation titles from the list (no markdown):
["Title 1", "Title 2", "Title 3"]"""

        llm_response = await call_llm(select_prompt, temperature=0.1, max_output_tokens=200, streaming=False)
        selected_titles = []
        if llm_response:
            import re as _re
            json_match = _re.search(r"\[.*?\]", llm_response, _re.DOTALL)
            if json_match:
                try:
                    selected_titles = json.loads(json_match.group(0))
                except json.JSONDecodeError:
                    pass
        logger.info(f"ШАГ ONET.3. LLM выбрал: {selected_titles}")

        if not selected_titles:
            return []

        # 3. Case-insensitive match → SOC codes
        occupations = find_soc_codes(selected_titles)
        logger.info(f"ШАГ ONET.4. Найдено {len(occupations)} SOC codes")

        # 4. Подтянуть данные и сформировать артефакты
        artifacts = []
        for occ in occupations:
            profile = get_occupation_profile(occ["soc_code"])
            md_content = format_onet_markdown(occ, profile)
            artifact = SourceArtifact(
                source_id=self._generate_source_id(f"onet_{occ['soc_code']}"),
                source_type="onet",
                title=f"O*NET: {occ['title']} ({occ['soc_code']})",
                content=md_content,
                url=f"https://www.onetonline.org/link/summary/{occ['soc_code']}",
                metadata={
                    "source": "onet",
                    "soc_code": occ["soc_code"],
                    "skills_count": len(profile.get("skills", [])),
                    "knowledge_count": len(profile.get("knowledge", [])),
                    "tasks_count": len(profile.get("tasks", [])),
                },
                retrieved_at=datetime.now().isoformat(),
            )
            artifacts.append(artifact)

        logger.info(f"ШАГ ONET.5. Сформировано {len(artifacts)} O*NET артефактов")
        return artifacts

    async def _collect_sonar_sources(self, spec: SourceSpec, role_scope: str) -> List[SourceArtifact]:
        """Сбор через Perplexity Sonar (OpenRouter) — skill-обёртка.

        Каждый spec → один артефакт с готовым markdown-синтезом от Sonar + список
        исходных URL в metadata. Модель задаётся через spec.filters['model']
        (default 'perplexity/sonar-pro').
        """
        import re as _re

        sonar_python = Path.home() / ".claude" / "skills" / "sonar-search" / ".venv" / "bin" / "python"
        sonar_script = Path.home() / ".claude" / "skills" / "sonar-search" / "search.py"
        if not sonar_python.exists() or not sonar_script.exists():
            logger.warning(f"ШАГ SONAR. Skill не найден: {sonar_script} — skip")
            return []

        filters = spec.filters or {}
        model = filters.get('model', 'perplexity/sonar-pro')
        recency = filters.get('recency')
        domains = filters.get('domains')

        query = f"{role_scope} — {spec.query}" if spec.query else role_scope
        logger.info(f"ШАГ SONAR.1. Запрос [{model}]: {query[:100]}")

        cmd = [str(sonar_python), str(sonar_script), query, "--model", model]
        if recency:
            cmd.extend(["--recency", recency])
        if domains:
            cmd.extend(["--domains", domains])

        try:
            proc = await asyncio.create_subprocess_exec(
                *cmd,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
            )
            try:
                stdout, stderr = await asyncio.wait_for(proc.communicate(), timeout=120)
            except asyncio.TimeoutError:
                proc.kill()
                logger.error("ШАГ SONAR. Timeout 120с — skip")
                return []
        except Exception as exc:
            logger.error(f"ШАГ SONAR. Ошибка запуска subprocess: {exc}")
            return []

        if proc.returncode != 0:
            logger.error(f"ШАГ SONAR. Ненулевой exit code {proc.returncode}: {stderr.decode('utf-8', errors='ignore')[:500]}")
            return []

        response_md = stdout.decode('utf-8').strip()
        if not response_md or len(response_md) < 100:
            logger.warning(f"ШАГ SONAR.2. Слишком короткий ответ ({len(response_md)} chars) — skip")
            return []

        # Разделяем основной текст и блок источников
        main_text = response_md
        sources_md = ""
        for marker in ("\n## Источники\n", "\n## Sources\n"):
            if marker in response_md:
                parts = response_md.split(marker, 1)
                main_text = parts[0].strip()
                sources_md = parts[1].strip()
                break

        # Извлекаем [title](url) из блока источников
        source_refs = _re.findall(r"\[([^\]]+)\]\((https?://[^)]+)\)", sources_md)
        logger.info(f"ШАГ SONAR.2. Получен ответ {len(response_md)} chars, {len(source_refs)} источников")

        artifact = SourceArtifact(
            source_id=self._generate_source_id(f"sonar:{model}:{spec.query or role_scope}"),
            source_type="sonar",
            title=f"Sonar [{model.split('/')[-1]}]: {(spec.query or 'общий запрос')[:70]}",
            content=main_text,
            url=None,
            metadata={
                "model": model,
                "original_query": spec.query,
                "full_query": query,
                "source_refs": [{"title": t, "url": u} for t, u in source_refs],
                "source_refs_count": len(source_refs),
                "crawled_at": datetime.now().isoformat(),
            },
            retrieved_at=datetime.now().isoformat(),
        )
        return [artifact]

    def _extract_hh_vacancy_links(self, content: str) -> List[str]:
        """Извлечение ссылок на вакансии из hh.ru"""
        import re
        # Паттерн для ссылок на вакансии hh.ru
        pattern = r'https?://[^/]*hh\.ru/vacancy/\d+'
        return re.findall(pattern, content)[:20]  # Ограничиваем количество
    
    def _clean_hh_vacancy_markdown(self, raw_text: str) -> tuple:
        """Очистка raw markdown вакансии с hh.ru до полезной части + извлечение title.

        Источник мусора на страницах hh.ru:
          1. Служебный «# Вакансия» из HTML <title>, дублирует реальный заголовок ниже.
          2. Header / cookie-banner / меню до реального заголовка.
          3. После описания вакансии: «## Похожие вакансии», «## Где предстоит работать»,
             «## Адрес», «## Задайте вопрос работодателю», «## О компании» — это секции
             страницы, не имеющие отношения к компетенциям.
          4. Строки JSON-state hh.ru (renderRestriction, advantages, locale ...) —
             встроенный inline data на 100K+ символов в одной строке.
          5. Строки-картинки `![...](...)` и стандартные UI-меню «Войти», «Создать резюме».

        Возвращает (title, cleaned_content). Если реальный title не найден — возвращает
        (fallback_title, raw_text) без очистки.
        """
        lines = raw_text.split("\n")

        # 1. Найти настоящий заголовок: первый «# X», где X != «Вакансия» и не пусто.
        title = "Вакансия hh.ru"
        title_idx = -1
        for i, line in enumerate(lines):
            stripped = line.strip()
            if stripped.startswith("# ") and not stripped.startswith("## "):
                candidate = stripped.lstrip("# ").strip()
                if candidate and candidate.lower() != "вакансия":
                    title = candidate
                    title_idx = i
                    break

        if title_idx < 0:
            return (title, raw_text)

        # 2. Отрезать всё ДО заголовка (header, cookies, меню) и всё ПОСЛЕ перехода
        # к мета-секциям страницы / похожим вакансиям.
        cutoff_markers = (
            "## Похожие вакансии",
            "### Похожие вакансии",
            "## Вакансии из других подборок",
            "### Вакансии из других подборок",
            "## Где предстоит работать",
            "## Адрес",
            "## Задайте вопрос работодателю",
            "## О компании",
            "## Контакты",
        )
        body_end = len(lines)
        for i in range(title_idx + 1, len(lines)):
            stripped = lines[i].strip()
            if any(stripped.startswith(m) for m in cutoff_markers):
                body_end = i
                break

        body = lines[title_idx:body_end]

        # 3. Внутри body выбросить строки-картинки, JSON-state, чистые UI-меню.
        ui_noise_markers = (
            "Напишите телефон",
            "Нажимая «Продолжить»",
            "Создать резюме",
            "[Войти]",
            "Помогите",
            "Cookie",
            "Понятно",
            "файлы cookie",
        )
        clean_body = []
        for line in body:
            stripped = line.strip()
            if not stripped:
                clean_body.append(line)
                continue
            # JSON-state hh: одна строка на десятки KB с {"...":...}
            if len(stripped) > 1000 and stripped.startswith("{") and "\":" in stripped[:200]:
                continue
            # Очень длинные строки без markdown-структуры — почти всегда мусор
            if len(stripped) > 5000:
                continue
            # Строки-картинки целиком: ![...](url) или ![alt](url)![](url)...
            if stripped.startswith("![") and "](" in stripped and not any(c.isalpha() for c in stripped.split("](")[-1][:50]):
                continue
            # UI-маркеры
            if any(m in stripped for m in ui_noise_markers):
                continue
            clean_body.append(line)

        # 4. Схлопнуть подряд идущие пустые строки
        collapsed = []
        prev_empty = False
        for line in clean_body:
            is_empty = not line.strip()
            if is_empty and prev_empty:
                continue
            collapsed.append(line)
            prev_empty = is_empty

        cleaned = "\n".join(collapsed).strip()
        return (title, cleaned)
    
    def _generate_source_id(self, url: str) -> str:
        """Генерация уникального ID источника"""
        return hashlib.md5(url.encode('utf-8')).hexdigest()[:12]
    
    async def save_corpus(self, artifacts: List[SourceArtifact], role_scope: str) -> Dict[str, str]:
        """Конкатенация всех артефактов в единый raw_corpus.md с truncation."""
        MAX_CHARS = 20000  # ~5000 токенов

        corpus_path = self.artifacts_dir / "raw_corpus.md"
        manifest_path = self.artifacts_dir / "raw_corpus_manifest.md"

        # Build corpus
        sections = []
        for art in artifacts:
            truncated = art.content[:MAX_CHARS]
            if len(art.content) > MAX_CHARS:
                truncated += "\n\n[...truncated...]"
            section = f"""---
SOURCE: {art.source_type}
TITLE: {art.title}
URL: {art.url or 'N/A'}
---

{truncated}"""
            sections.append(section)

        corpus_content = f"# Raw Corpus: {role_scope}\n\n" + "\n\n===\n\n".join(sections)
        corpus_path.write_text(corpus_content, encoding='utf-8')

        # Manifest
        manifest_lines = [
            f"# Raw Corpus Manifest",
            f"",
            f"**Роль:** {role_scope}",
            f"**Дата:** {datetime.now().isoformat()}",
            f"**Источников:** {len(artifacts)}",
            f"",
        ]
        by_type: Dict[str, int] = {}
        for art in artifacts:
            by_type[art.source_type] = by_type.get(art.source_type, 0) + 1
        for st, cnt in by_type.items():
            manifest_lines.append(f"- **{st}**: {cnt}")
        manifest_lines.append("")
        for i, art in enumerate(artifacts, 1):
            manifest_lines.append(f"{i}. [{art.source_type}] {art.title[:60]} — {art.url or 'N/A'}")

        manifest_path.write_text("\n".join(manifest_lines), encoding='utf-8')

        logger.info(f"ШАГ CORPUS. Saved raw_corpus.md ({len(sections)} docs, {len(corpus_content)} chars)")
        return {
            "corpus": str(corpus_path),
            "manifest": str(manifest_path),
        }

    async def save_artifacts(self, artifacts: List[SourceArtifact], role_scope: str) -> Dict[str, str]:
        """
        Сохранение артефактов в файловую систему
        
        Returns:
            Словарь с путями к созданным файлам
        """
        logger.info(f"ШАГ SAVE.1. Сохранение {len(artifacts)} артефактов")
        
        # Очищаем директорию
        for existing_file in self.raw_corpus_dir.glob('*.md'):
            existing_file.unlink()
            
        saved_files = {}
        
        # Сохраняем каждый артефакт
        for i, artifact in enumerate(artifacts, 1):
            filename = f"{i:03d}_{artifact.source_type}_{artifact.source_id}.md"
            file_path = self.raw_corpus_dir / filename
            
            # Формируем markdown с метаданными
            markdown_content = f"""---
source_id: {artifact.source_id}
source_type: {artifact.source_type}
title: {artifact.title}
url: {artifact.url or 'N/A'}
retrieved_at: {artifact.retrieved_at}
relevance_score: {artifact.relevance_score or 'N/A'}
metadata: {json.dumps(artifact.metadata or {}, ensure_ascii=False, indent=2)}
---

# {artifact.title}

{artifact.content}
"""
            
            file_path.write_text(markdown_content, encoding='utf-8')
            saved_files[artifact.source_id] = str(file_path)
            
        logger.info(f"ШАГ SAVE.2. Сохранено {len(saved_files)} файлов в {self.raw_corpus_dir}")
        
        # Создаем манифест
        manifest_path = await self._create_manifest(artifacts, role_scope)
        saved_files['manifest'] = str(manifest_path)
        
        # Создаем реестр источников
        registry_path = await self._create_source_registry(artifacts, role_scope)
        saved_files['registry'] = str(registry_path)
        
        logger.info("ШАГ SAVE.3. Все артефакты сохранены успешно")
        return saved_files
    
    async def _create_manifest(self, artifacts: List[SourceArtifact], role_scope: str) -> Path:
        """Создание raw_corpus_manifest.md"""
        manifest_path = self.artifacts_dir / "raw_corpus_manifest.md"
        
        content = f"""# Raw Corpus Manifest

**Целевая роль:** {role_scope}
**Дата создания:** {datetime.now().isoformat()}
**Всего источников:** {len(artifacts)}

## Статистика по типам источников

"""
        
        # Группируем по типам
        by_type = {}
        for artifact in artifacts:
            source_type = artifact.source_type
            if source_type not in by_type:
                by_type[source_type] = []
            by_type[source_type].append(artifact)
            
        for source_type, type_artifacts in by_type.items():
            content += f"- **{source_type}**: {len(type_artifacts)} источников\n"
            
        content += f"\n## Индекс источников\n\n"
        
        for i, artifact in enumerate(artifacts, 1):
            filename = f"{i:03d}_{artifact.source_type}_{artifact.source_id}.md"
            relevance = f"({artifact.relevance_score:.2f})" if artifact.relevance_score else ""
            content += f"{i}. **{artifact.title}** {relevance}\n"
            content += f"   - Тип: {artifact.source_type}\n"
            content += f"   - Файл: `{filename}`\n"
            content += f"   - URL: {artifact.url or 'N/A'}\n\n"
            
        manifest_path.write_text(content, encoding='utf-8')
        return manifest_path
    
    async def _create_source_registry(self, artifacts: List[SourceArtifact], role_scope: str) -> Path:
        """Создание source_registry.md"""
        registry_path = self.artifacts_dir / "source_registry.md"

        # Группируем по типам
        by_type: Dict[str, List[SourceArtifact]] = {}
        for artifact in artifacts:
            st = artifact.source_type
            if st not in by_type:
                by_type[st] = []
            by_type[st].append(artifact)

        content = f"""# Source Registry

**Целевая роль:** {role_scope}
**Дата создания:** {datetime.now().isoformat()}

## Метаданные сбора

### Конфигурация поиска
- LLM Model: {self.env_config.get('CLOUDRU_MODEL_NAME', 'Unknown')}
- Crawler Base URL: {self.env_config.get('CRAWLER_BASE_URL', 'Unknown')}
- S2 API Key: {'Configured' if self.env_config.get('S2_API_KEY') else 'Not configured'}

### Результаты по источникам

"""

        for source_type, type_artifacts in by_type.items():
            scores = [a.relevance_score for a in type_artifacts if a.relevance_score]
            avg_relevance = sum(scores) / len(scores) if scores else 0.0

            content += f"#### {source_type}\n"
            content += f"- Количество: {len(type_artifacts)}\n"
            content += f"- Средняя релевантность: {avg_relevance:.2f}\n"

            top_sources = sorted(type_artifacts, key=lambda x: x.relevance_score or 0, reverse=True)[:3]
            content += "- Топ источники:\n"
            for src in top_sources:
                score_str = f"{src.relevance_score:.2f}" if src.relevance_score else "N/A"
                content += f"  - {src.title} ({score_str})\n"
            content += "\n"

        content += """
## Рекомендации по использованию

1. **Высокая релевантность** (>0.8): Использовать как основу для Evidence.md
2. **Средняя релевантность** (0.6-0.8): Использовать как вспомогательные источники
3. **Низкая релевантность** (<0.6): Исключить из дальнейшего анализа

## Следующие шаги

1. Запустить evidence_synthesis_service для создания Evidence.md
2. Проверить качество источников вручную
3. Дополнить корпус недостающими источниками при необходимости
"""

        registry_path.write_text(content, encoding='utf-8')
        return registry_path
