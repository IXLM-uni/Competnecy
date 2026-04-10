# -*- coding: utf-8 -*-
"""
Руководство к файлу UC_19.py
=============================

Назначение:
    Реализация UC-19: Автоматический научный литобзор (Literature Review via Semantic Scholar).
    Тонкий клиент — вся S2-логика делегирована S2Client из llm_service.py.
    Полный pipeline:
        1. LLM генерирует 5 разнообразных поисковых запросов по теме
        1b. S2FieldInference определяет fieldsOfStudy для фильтрации
        2. S2Client.search_papers — массовый поиск с фильтрами
        3. Эмбеддинг + индексация всех статей в Qdrant
        4. LLM-кластеризация: генерация подтем → RAG-поиск → группировка
        5. Map-фаза: LLM-обзор каждого кластера
        6. Reduce-фаза: сборка финального литобзора с библиографией
        7. Возврат структурированного результата

    Use Case: UC-19 из LLM_SERVICE.md
    Actor: Исследователь / PhD-студент / Аналитик
    Цель: Автоматическое формирование структурированного литературного обзора.

Используемые классы/функции из llm_service.py:
    - S2Client, S2SearchFilter, S2_RATE_LIMIT_DELAY
    - load_env_and_validate, create_rag_clients_from_env
    - create_cloudru_openai_client_from_env
    - Chunker, RequestContext
    - query_llm_simple, stream_llm_to_stdout
    - JsonRepairLLM

Внешние зависимости:
    - semanticscholar (pip install semanticscholar)
    - llm_service.py, python-dotenv

Использование:
    python -m AI.scripts.UC.UC_19 "Применение графовых нейронных сетей в drug discovery"
    python -m AI.scripts.UC.UC_19 --topic "LLM agents" --clusters 4 --stream
"""

from __future__ import annotations

import asyncio
import hashlib
import json
import logging
import os
import sys
from pathlib import Path
from typing import Any, Dict, List, Optional

# ---------- Константы ----------
SCRIPT_DIR = Path(__file__).parent.absolute()
AI_DIR = SCRIPT_DIR.parent.parent
GLOBAL_SERVICES_DIR = AI_DIR.parent
SPARSE_CACHE_DIR = AI_DIR / "models" / "sparse_cache"

DEFAULT_SEARCH_QUERIES_COUNT = 5
DEFAULT_PAPERS_PER_QUERY = 15
DEFAULT_MAX_TOTAL_PAPERS = 50
DEFAULT_CLUSTER_COUNT = 4

sys.path.insert(0, str(GLOBAL_SERVICES_DIR))

from AI.llm_service import (
    Chunker,
    JsonRepairLLM,
    RequestContext,
    S2Client,
    S2SearchFilter,
    S2_RATE_LIMIT_DELAY,
    create_cloudru_openai_client_from_env,
    create_rag_clients_from_env,
    load_env_and_validate,
    query_llm_simple,
    stream_llm_to_stdout,
)

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s | %(levelname)-7s | %(name)s | %(message)s",
)
logger = logging.getLogger(__name__)

SYSTEM_MSG_REVIEW = (
    "Ты — эксперт по составлению научных литературных обзоров. "
    "Пиши в академическом стиле, цитируй в формате [Author, Year]. "
    "Структурируй текст: введение, основная часть, заключение."
)


# ============================================================================
# Основная функция
# ============================================================================

async def main(
    topic: Optional[str] = None,
    search_queries_count: int = DEFAULT_SEARCH_QUERIES_COUNT,
    papers_per_query: int = DEFAULT_PAPERS_PER_QUERY,
    max_total_papers: int = DEFAULT_MAX_TOTAL_PAPERS,
    cluster_count: int = DEFAULT_CLUSTER_COUNT,
    use_streaming: bool = False,
) -> Dict[str, Any]:
    """Основная функция UC-19: Автоматический научный литобзор."""
    logger.info("=" * 70)
    logger.info("UC-19: Автоматический научный литобзор (Literature Review)")
    logger.info("=" * 70)

    if not topic:
        topic = "Application of large language models as autonomous agents"
        logger.info("Тема не предоставлена, используем демо: '%s'", topic)

    collection_hash = hashlib.md5(topic.encode()).hexdigest()[:10]
    collection_name = f"s2_litreview_{collection_hash}"

    # ШАГ 0. Конфигурация
    try:
        cfg = load_env_and_validate(str(GLOBAL_SERVICES_DIR))
    except ValueError as exc:
        return {"status": "error", "message": str(exc)}

    sparse_dir = cfg["SPARSE_CACHE_DIR"] or str(SPARSE_CACHE_DIR)
    llm_client = create_cloudru_openai_client_from_env()
    json_repair = JsonRepairLLM()
    s2 = S2Client(llm_client=llm_client)

    # ────────────────────────────────────────────────────────────────────
    # ШАГ 1. Генерация разнообразных поисковых запросов
    # ────────────────────────────────────────────────────────────────────
    logger.info("ШАГ 1. Генерация %d поисковых запросов для литобзора — ОТПРАВЛЯЕМ",
                search_queries_count)

    gen_prompt = (
        f"Generate exactly {search_queries_count} diverse search queries in English "
        f"for a comprehensive literature review on the following topic.\n"
        f"Topic: {topic}\n\n"
        f"Cover different aspects: theory/foundations, methods/algorithms, "
        f"applications, datasets/benchmarks, recent advances/surveys.\n"
        f"Return ONLY a JSON array of strings. No explanation, no markdown."
    )

    gen_ctx = RequestContext(request_id="uc19-gen", user_id="uc19_user", mode="chat")
    gen_raw = await query_llm_simple(
        llm_client, gen_prompt, gen_ctx,
        system_message="You generate diverse academic search queries for literature reviews.",
        model=cfg["CLOUDRU_MODEL_NAME"],
    )

    search_queries: List[str] = []
    if gen_raw:
        try:
            repaired = await json_repair.repair(gen_raw, gen_ctx)
            parsed = json.loads(repaired)
            if isinstance(parsed, list):
                search_queries = [str(q).strip() for q in parsed if q]
            elif isinstance(parsed, dict) and "queries" in parsed:
                search_queries = [str(q).strip() for q in parsed["queries"] if q]
        except Exception as exc:
            logger.warning("ШАГ 1. ОШИБКА парсинга: %s", exc)

    if not search_queries:
        search_queries = [topic]
        logger.warning("ШАГ 1. Fallback: используем тему как единственный запрос")

    search_queries = search_queries[:search_queries_count]
    for i, sq in enumerate(search_queries, 1):
        logger.info("ШАГ 1.   [%d] %s", i, sq[:80])
    logger.info("ШАГ 1. Сгенерировано %d поисковых запросов — УСПЕХ", len(search_queries))

    # ────────────────────────────────────────────────────────────────────
    # ШАГ 1b. LLM-инференс fieldsOfStudy для фильтрации
    # ────────────────────────────────────────────────────────────────────
    infer_ctx = RequestContext(request_id="uc19-infer-fields", user_id="uc19_user", mode="chat")
    inferred_fields = await s2.infer_fields(topic, infer_ctx)
    s2_filter: Optional[S2SearchFilter] = None
    if inferred_fields:
        s2_filter = S2SearchFilter(fields_of_study=inferred_fields)
        logger.info("ШАГ 1b. Инференс fieldsOfStudy: %s — УСПЕХ", inferred_fields)
    else:
        logger.info("ШАГ 1b. fieldsOfStudy не определены — поиск без фильтра")

    # ────────────────────────────────────────────────────────────────────
    # ШАГ 2. Массовый поиск статей в Semantic Scholar (через S2Client)
    # ────────────────────────────────────────────────────────────────────
    logger.info("ШАГ 2. Массовый поиск (%d запросов × %d) — ОТПРАВЛЯЕМ",
                len(search_queries), papers_per_query)

    all_papers: List[Dict[str, Any]] = []
    seen_ids: set = set()

    for i, sq in enumerate(search_queries, 1):
        logger.info("ШАГ 2.   Запрос %d/%d: '%s' — ОТПРАВЛЯЕМ",
                    i, len(search_queries), sq[:60])
        papers = await s2.search_papers(sq, limit=papers_per_query, filters=s2_filter)

        new_count = 0
        for p in papers:
            pid = p.get("paperId")
            if pid and pid not in seen_ids and p.get("abstract"):
                seen_ids.add(pid)
                all_papers.append(p)
                new_count += 1
                if len(all_papers) >= max_total_papers:
                    break

        logger.info("ШАГ 2.   Запрос %d: найдено %d, новых %d (всего: %d/%d)",
                    i, len(papers), new_count, len(all_papers), max_total_papers)

        if len(all_papers) >= max_total_papers:
            logger.info("ШАГ 2.   Достигнут лимит %d статей", max_total_papers)
            break
        if i < len(search_queries):
            await asyncio.sleep(S2_RATE_LIMIT_DELAY)

    if not all_papers:
        return {"status": "error", "message": "Не найдено статей с abstract"}

    # Сортируем по citationCount для приоритизации
    all_papers.sort(key=lambda x: x.get("citationCount", 0), reverse=True)
    all_papers = all_papers[:max_total_papers]

    logger.info("ШАГ 2. Собрано %d уникальных статей из %d запросов — УСПЕХ",
                len(all_papers), len(search_queries))

    # ────────────────────────────────────────────────────────────────────
    # ШАГ 3. Эмбеддинг + индексация в Qdrant
    # ────────────────────────────────────────────────────────────────────
    logger.info("ШАГ 3. Эмбеддинг + индексация %d статей в '%s' — ОТПРАВЛЯЕМ",
                len(all_papers), collection_name)

    chunker = Chunker(chunk_size_tokens=512, chunk_overlap_tokens=128)
    all_chunks = []
    paper_id_to_paper: Dict[str, Dict[str, Any]] = {}

    for p in all_papers:
        text = S2Client.paper_embed_text(p)
        chunks = await chunker.split(text=text, source_id=p["paperId"])
        for c in chunks:
            authors_str = ", ".join(a["name"] for a in p.get("authors", [])[:3])
            c.metadata.update({
                "paper_id": p["paperId"],
                "title": p.get("title", ""),
                "year": str(p.get("year", "")),
                "citation_count": p.get("citationCount", 0),
                "authors": authors_str,
                "venue": p.get("venue", ""),
            })
        all_chunks.extend(chunks)
        paper_id_to_paper[p["paperId"]] = p

    logger.info("ШАГ 3. Чанкинг: %d чанков из %d статей", len(all_chunks), len(all_papers))

    # Инициализация RAG и индексация
    rag_clients = create_rag_clients_from_env(
        collection=collection_name,
        sparse_cache_dir=sparse_dir,
    )
    embedding_client = rag_clients["embedding"]
    sparse_client = rag_clients["sparse"]
    vector_store = rag_clients["vector_store"]
    retriever = rag_clients["retriever"]

    await vector_store.ensure_collection(collection_name)

    texts_for_embed = [c.text for c in all_chunks]
    if texts_for_embed:
        dense_vectors = await embedding_client.embed_texts(texts_for_embed)
        sparse_vectors = None
        if sparse_client:
            sparse_vectors = await sparse_client.embed_documents(texts_for_embed)

        points_data = []
        for i, chunk in enumerate(all_chunks):
            payload = {
                "text": chunk.text,
                "source_id": chunk.source_id,
                "document_name": chunk.metadata.get("title", ""),
                "tags": ["s2", "litreview", chunk.metadata.get("year", "")],
                **{f"custom_data.{k}": v for k, v in chunk.metadata.items()},
            }
            point = {
                "id": chunk.id,
                "payload": payload,
                "dense_vector": dense_vectors[i] if i < len(dense_vectors) else None,
            }
            if sparse_vectors and i < len(sparse_vectors):
                point["sparse_vector"] = sparse_vectors[i]
            points_data.append(point)

        await vector_store.upsert_hybrid(collection_name, points_data)

    logger.info("ШАГ 3. Индексировано %d статей в коллекцию '%s' — УСПЕХ",
                len(all_papers), collection_name)

    # ────────────────────────────────────────────────────────────────────
    # ШАГ 4. LLM-кластеризация через генерацию подтем
    # ────────────────────────────────────────────────────────────────────
    logger.info("ШАГ 4. LLM-кластеризация: генерация %d подтем — ОТПРАВЛЯЕМ", cluster_count)

    # Сначала генерируем подтемы через LLM
    titles_sample = "\n".join(
        f"  - {p['title']} ({p.get('year', '?')}, cit={p.get('citationCount', 0)})"
        for p in all_papers[:25]
    )

    cluster_prompt = (
        f"Topic: {topic}\n\n"
        f"Below are titles of {min(25, len(all_papers))} papers found on this topic:\n"
        f"{titles_sample}\n\n"
        f"Generate exactly {cluster_count} distinct subtopics/clusters that group these papers.\n"
        f"Each subtopic should represent a clear thematic direction.\n\n"
        f"Return JSON: {{\"clusters\": [{{\"label\": \"short label\", "
        f"\"description\": \"1-2 sentence description\", "
        f"\"search_query\": \"query to find papers in this cluster\"}}]}}\n"
        f"No explanation outside JSON."
    )

    cluster_ctx = RequestContext(request_id="uc19-cluster", user_id="uc19_user", mode="chat")
    cluster_raw = await query_llm_simple(
        llm_client, cluster_prompt, cluster_ctx,
        system_message="You are an academic topic clustering expert.",
        model=cfg["CLOUDRU_MODEL_NAME"],
    )

    clusters: List[Dict[str, Any]] = []
    if cluster_raw:
        try:
            repaired = await json_repair.repair(cluster_raw, cluster_ctx)
            parsed = json.loads(repaired)
            if isinstance(parsed, dict) and "clusters" in parsed:
                clusters = parsed["clusters"]
            elif isinstance(parsed, list):
                clusters = parsed
        except Exception as exc:
            logger.warning("ШАГ 4. ОШИБКА парсинга кластеров: %s", exc)

    if not clusters:
        clusters = [{"label": topic, "description": topic, "search_query": topic}]
        logger.warning("ШАГ 4. Fallback: один кластер = вся тема")

    clusters = clusters[:cluster_count]

    # Для каждого кластера — RAG-поиск → группировка статей
    cluster_papers: List[Dict[str, Any]] = []
    assigned_paper_ids: set = set()

    for i, cl in enumerate(clusters):
        search_q = cl.get("search_query", cl.get("label", topic))
        logger.info("ШАГ 4.   Кластер %d/%d: '%s' — RAG-поиск",
                    i + 1, len(clusters), cl.get("label", "?")[:50])

        rag_ctx = RequestContext(
            request_id=f"uc19-cluster-{i}", user_id="uc19_user",
            mode="rag_qa", rag_top_k=12,
        )
        snippets = await retriever.retrieve(search_q, rag_ctx, top_k=12)

        # Группируем найденные статьи
        cluster_paper_list = []
        for s in snippets:
            pid = s.source_id
            if pid in paper_id_to_paper and pid not in assigned_paper_ids:
                assigned_paper_ids.add(pid)
                cluster_paper_list.append(paper_id_to_paper[pid])

        cluster_papers.append({
            "label": cl.get("label", f"Cluster {i+1}"),
            "description": cl.get("description", ""),
            "papers": cluster_paper_list,
        })
        logger.info("ШАГ 4.   Кластер '%s': %d статей",
                    cl.get("label", "?")[:30], len(cluster_paper_list))

    # Добавляем неназначенные статьи в наименьший кластер
    unassigned = [p for p in all_papers if p["paperId"] not in assigned_paper_ids]
    if unassigned:
        smallest_cluster = min(cluster_papers, key=lambda x: len(x["papers"]))
        smallest_cluster["papers"].extend(unassigned)
        logger.info("ШАГ 4.   %d неназначенных статей → кластер '%s'",
                    len(unassigned), smallest_cluster["label"][:30])

    logger.info("ШАГ 4. Статьи распределены по %d кластерам — УСПЕХ", len(cluster_papers))

    # ────────────────────────────────────────────────────────────────────
    # ШАГ 5. Map-фаза: LLM-обзор каждого кластера
    # ────────────────────────────────────────────────────────────────────
    logger.info("ШАГ 5. Map-фаза: LLM-обзор %d кластеров — ОТПРАВЛЯЕМ", len(cluster_papers))

    semaphore = asyncio.Semaphore(2)
    cluster_reviews: List[Dict[str, Any]] = []

    async def _review_cluster(idx: int, cl: Dict[str, Any]) -> Dict[str, Any]:
        async with semaphore:
            label = cl["label"]
            papers = cl["papers"]
            logger.info("ШАГ 5.   Кластер %d/%d '%s' (%d статей) — ОТПРАВЛЯЕМ",
                        idx + 1, len(cluster_papers), label[:30], len(papers))

            if not papers:
                return {"label": label, "review": "(Нет статей в кластере)", "papers_count": 0}

            papers_context = ""
            for j, p in enumerate(papers[:10], 1):
                authors_str = ", ".join(a["name"] for a in p.get("authors", [])[:3])
                citation_key = S2Client.paper_citation_key(p)
                abstract_short = (p.get("abstract") or "")[:250]
                papers_context += (
                    f"  [{j}] {citation_key} \"{p['title']}\"\n"
                    f"      Authors: {authors_str} | Venue: {p.get('venue', 'N/A')}\n"
                    f"      Citations: {p.get('citationCount', 0)}\n"
                    f"      Abstract: {abstract_short}...\n\n"
                )

            section_prompt = (
                f"Напиши секцию литературного обзора по подтеме: \"{label}\"\n"
                f"Описание подтемы: {cl.get('description', '')}\n\n"
                f"Статьи в этой секции ({len(papers)}):\n\n{papers_context}\n"
                f"Требования:\n"
                f"- Академический стиль\n"
                f"- Цитируй в формате [Author, Year]\n"
                f"- 3-5 абзацев\n"
                f"- Укажи общие тенденции, ключевые находки, пробелы в исследованиях\n"
            )

            review_ctx = RequestContext(
                request_id=f"uc19-map-{idx}", user_id="uc19_user", mode="chat",
            )
            review_text = await query_llm_simple(
                llm_client, section_prompt, review_ctx,
                system_message=SYSTEM_MSG_REVIEW,
                model=cfg["CLOUDRU_MODEL_NAME"],
            )

            logger.info("ШАГ 5.   Кластер %d/%d '%s' — УСПЕХ (%d символов)",
                        idx + 1, len(cluster_papers), label[:30],
                        len(review_text) if review_text else 0)

            return {
                "label": label,
                "description": cl.get("description", ""),
                "review": review_text or "(Обзор не сгенерирован)",
                "papers_count": len(papers),
                "papers": [
                    {
                        "paper_id": p["paperId"],
                        "title": p["title"],
                        "authors": ", ".join(a["name"] for a in p.get("authors", [])[:3]),
                        "year": p.get("year"),
                        "citation_count": p.get("citationCount", 0),
                        "citation_key": S2Client.paper_citation_key(p),
                    }
                    for p in papers
                ],
            }

    tasks = [_review_cluster(i, cl) for i, cl in enumerate(cluster_papers)]
    cluster_reviews = list(await asyncio.gather(*tasks))

    logger.info("ШАГ 5. Map-фаза завершена: %d секций — УСПЕХ", len(cluster_reviews))

    # ────────────────────────────────────────────────────────────────────
    # ШАГ 6. Reduce-фаза: сборка финального литобзора
    # ────────────────────────────────────────────────────────────────────
    logger.info("ШАГ 6. Reduce-фаза: сборка финального литобзора — ОТПРАВЛЯЕМ")

    sections_text = ""
    for i, cr in enumerate(cluster_reviews, 1):
        sections_text += (
            f"═══ СЕКЦИЯ {i}: {cr['label']} ({cr['papers_count']} статей) ═══\n"
            f"{cr['review']}\n\n"
        )

    # Библиография
    bibliography = []
    for p in all_papers:
        bib_entry = S2Client.paper_citation_key(p)
        authors_str = ", ".join(a["name"] for a in p.get("authors", [])[:5])
        bibliography.append(
            f"  {bib_entry} {authors_str}. \"{p['title']}\". "
            f"{p.get('venue', 'N/A')}, {p.get('year', 'n.d.')}. "
            f"Citations: {p.get('citationCount', 0)}."
        )

    reduce_prompt = (
        f"Тема литобзора: {topic}\n\n"
        f"Ниже представлены {len(cluster_reviews)} секций обзора, написанных по отдельным подтемам.\n\n"
        f"{sections_text}\n"
        f"═══ ЗАДАЧА ═══\n"
        f"Собери из этих секций единый связный литературный обзор:\n"
        f"1. ВВЕДЕНИЕ: актуальность темы, цель обзора, структура\n"
        f"2. ОСНОВНАЯ ЧАСТЬ: интегрируй секции, добавь переходы между ними\n"
        f"3. ЗАКЛЮЧЕНИЕ: основные выводы, тенденции, пробелы, направления будущих исследований\n"
        f"Сохрани все цитирования в формате [Author, Year].\n"
    )

    reduce_ctx = RequestContext(request_id="uc19-reduce", user_id="uc19_user", mode="chat")

    if use_streaming:
        final_review = await stream_llm_to_stdout(
            llm_client, reduce_prompt, reduce_ctx,
            system_message=SYSTEM_MSG_REVIEW, model=cfg["CLOUDRU_MODEL_NAME"],
        )
    else:
        final_review = await query_llm_simple(
            llm_client, reduce_prompt, reduce_ctx,
            system_message=SYSTEM_MSG_REVIEW, model=cfg["CLOUDRU_MODEL_NAME"],
        )
        if final_review:
            print("\n" + "=" * 70 + "\nЛИТЕРАТУРНЫЙ ОБЗОР:\n" + "=" * 70)
            print(final_review)
            print("\n" + "-" * 70 + "\nБИБЛИОГРАФИЯ:\n" + "-" * 70)
            for b in bibliography[:30]:
                print(b)
            if len(bibliography) > 30:
                print(f"  ... и ещё {len(bibliography) - 30} источников")
            print("=" * 70)

    logger.info("ШАГ 6. Финальный литобзор собран — УСПЕХ")

    # ────────────────────────────────────────────────────────────────────
    # ШАГ 7. Возврат результата
    # ────────────────────────────────────────────────────────────────────
    result: Dict[str, Any] = {
        "status": "success" if final_review else "error",
        "uc": "UC-19",
        "topic": topic,
        "search_queries": search_queries,
        "total_papers": len(all_papers),
        "clusters": len(cluster_reviews),
        "collection_name": collection_name,
        "sections": [
            {
                "label": cr["label"],
                "description": cr.get("description", ""),
                "papers_count": cr["papers_count"],
                "review_length": len(cr["review"]),
                "papers": cr.get("papers", []),
            }
            for cr in cluster_reviews
        ],
        "review_text": final_review,
        "review_length": len(final_review) if final_review else 0,
        "bibliography": bibliography,
        "bibliography_count": len(bibliography),
    }
    if not final_review:
        result["error"] = "LLM не вернул обзор"

    logger.info("ШАГ 7. Литобзор завершён — УСПЕХ")
    logger.info(
        "РЕЗУЛЬТАТ UC-19: papers=%d, clusters=%d, review_len=%d, bib=%d",
        len(all_papers), len(cluster_reviews),
        result["review_length"], len(bibliography),
    )
    return result


if __name__ == "__main__":
    import argparse

    ap = argparse.ArgumentParser(description="UC-19: Автоматический научный литобзор")
    ap.add_argument("topic", nargs="?", default=None, help="Тема литобзора")
    ap.add_argument("--queries-count", type=int, default=DEFAULT_SEARCH_QUERIES_COUNT)
    ap.add_argument("--papers-per-query", type=int, default=DEFAULT_PAPERS_PER_QUERY)
    ap.add_argument("--max-papers", type=int, default=DEFAULT_MAX_TOTAL_PAPERS)
    ap.add_argument("--clusters", type=int, default=DEFAULT_CLUSTER_COUNT)
    ap.add_argument("--stream", action="store_true")
    args = ap.parse_args()

    try:
        result = asyncio.run(main(
            topic=args.topic,
            search_queries_count=args.queries_count,
            papers_per_query=args.papers_per_query,
            max_total_papers=args.max_papers,
            cluster_count=args.clusters,
            use_streaming=args.stream,
        ))

        print("\n" + "=" * 70)
        print("UC-19: ЛИТОБЗОР ЗАВЕРШЁН")
        print("=" * 70)
        print(f"Статус: {result.get('status', 'unknown')}")
        print(f"Тема: {result.get('topic', 'N/A')}")
        print(f"Статей: {result.get('total_papers', 0)}")
        print(f"Кластеров: {result.get('clusters', 0)}")
        print(f"Длина обзора: {result.get('review_length', 0)} символов")
        print(f"Библиография: {result.get('bibliography_count', 0)} источников")
        print(f"Коллекция: {result.get('collection_name', 'N/A')}")

        if result.get("sections"):
            print("\nСекции:")
            for s in result["sections"]:
                print(f"  - {s['label']} ({s['papers_count']} статей, "
                      f"{s['review_length']} символов)")

        sys.exit(0 if result.get("status") == "success" else 1)

    except KeyboardInterrupt:
        print("\nПрервано пользователем")
        sys.exit(130)
    except Exception as exc:
        logger.exception("Критическая ошибка в UC-19: %s", exc)
        sys.exit(1)
