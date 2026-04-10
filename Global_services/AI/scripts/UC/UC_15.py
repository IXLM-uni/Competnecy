# -*- coding: utf-8 -*-
"""
Руководство к файлу UC_15.py
=============================

Назначение:
    Реализация UC-15: Deep Academic Research (Semantic Scholar → RAG → LLM).
    Тонкий клиент — вся S2-логика делегирована S2Client из llm_service.py.
    Полный pipeline:
        1. LLM генерирует 3 поисковых запроса по теме пользователя
        1b. S2FieldInference определяет fieldsOfStudy для фильтрации
        2. S2Client.search_papers ищет статьи с фильтрами
        3. LLM-субагент (без истории) отбирает 5 самых релевантных
        4. S2Client.paper_to_text формирует текст выбранных статей
        5. Чанкинг + dense/sparse эмбеддинг + индексация в Qdrant
        6. RAG hybrid search по временной коллекции
        7. Финальный LLM-ответ с цитированием научных источников
        8. Возврат структурированного результата

    Use Case: UC-15 из LLM_SERVICE.md
    Actor: Исследователь / Аналитик / Пользователь
    Цель: Глубокий, подкреплённый научными источниками ответ на произвольный вопрос.

Используемые классы/функции из llm_service.py:
    - S2Client, S2SearchFilter, S2_RATE_LIMIT_DELAY
    - load_env_and_validate, create_rag_clients_from_env
    - create_cloudru_openai_client_from_env
    - Chunker, RequestContext
    - build_rag_prompt, stream_llm_to_stdout, query_llm_simple
    - StrictOutputParser, JsonRepairLLM

Внешние зависимости:
    - semanticscholar (pip install semanticscholar)
    - llm_service.py, python-dotenv, httpx

Использование:
    python -m AI.scripts.UC.UC_15 "Как трансформеры изменили NLP?"
    python -m AI.scripts.UC.UC_15 --query "RAG systems" --top-k 5 --stream
"""

from __future__ import annotations

import asyncio
import hashlib
import json
import logging
import os
import sys
import time
from pathlib import Path
from typing import Any, Dict, List, Optional

# ---------- Константы ----------
SCRIPT_DIR = Path(__file__).parent.absolute()
AI_DIR = SCRIPT_DIR.parent.parent
GLOBAL_SERVICES_DIR = AI_DIR.parent
SPARSE_CACHE_DIR = AI_DIR / "models" / "sparse_cache"

DEFAULT_SEARCH_QUERIES_COUNT = 3
DEFAULT_PAPERS_PER_QUERY = 10
DEFAULT_TOP_K_RELEVANT = 5
DEFAULT_RAG_TOP_K = 8

sys.path.insert(0, str(GLOBAL_SERVICES_DIR))

from AI.llm_service import (
    Chunker,
    JsonRepairLLM,
    RequestContext,
    S2Client,
    S2SearchFilter,
    S2_RATE_LIMIT_DELAY,
    StrictOutputParser,
    build_rag_prompt,
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

SYSTEM_MSG = (
    "Ты — эксперт по анализу научной литературы. Отвечай точно и структурированно, "
    "цитируя источники в формате [Author, Year]. Используй ТОЛЬКО предоставленный "
    "контекст из научных статей."
)


# ============================================================================
# Основная функция
# ============================================================================

async def main(
    query: Optional[str] = None,
    search_queries_count: int = DEFAULT_SEARCH_QUERIES_COUNT,
    papers_per_query: int = DEFAULT_PAPERS_PER_QUERY,
    top_k_relevant: int = DEFAULT_TOP_K_RELEVANT,
    rag_top_k: int = DEFAULT_RAG_TOP_K,
    use_streaming: bool = False,
) -> Dict[str, Any]:
    """Основная функция UC-15: Deep Academic Research."""
    logger.info("=" * 70)
    logger.info("UC-15: Deep Academic Research (Semantic Scholar → RAG → LLM)")
    logger.info("=" * 70)

    if not query:
        query = "How do transformer architectures impact natural language processing?"
        logger.info("Запрос не предоставлен, используем демо: '%s'", query)

    collection_hash = hashlib.md5(query.encode()).hexdigest()[:10]
    collection_name = f"s2_research_{collection_hash}"

    # ШАГ 0. Конфигурация
    try:
        cfg = load_env_and_validate(str(GLOBAL_SERVICES_DIR))
    except ValueError as exc:
        return {"status": "error", "message": str(exc)}

    sparse_dir = cfg["SPARSE_CACHE_DIR"] or str(SPARSE_CACHE_DIR)
    llm_client = create_cloudru_openai_client_from_env()
    json_repair = JsonRepairLLM()
    parser = StrictOutputParser(json_repair)
    s2 = S2Client(llm_client=llm_client)

    # ────────────────────────────────────────────────────────────────────
    # ШАГ 1. Генерация поисковых запросов через LLM
    # ────────────────────────────────────────────────────────────────────
    logger.info("ШАГ 1. Генерация %d поисковых запросов через LLM — ОТПРАВЛЯЕМ", search_queries_count)

    gen_prompt = (
        f"Generate exactly {search_queries_count} diverse search queries in English "
        f"for searching academic papers on Semantic Scholar about the following topic.\n"
        f"Topic: {query}\n\n"
        f"Return ONLY a JSON array of strings, e.g. [\"query1\", \"query2\", \"query3\"]. "
        f"No explanation, no markdown."
    )

    gen_ctx = RequestContext(request_id="uc15-gen-queries", user_id="uc15_user", mode="chat")
    search_queries_raw = await query_llm_simple(
        llm_client, gen_prompt, gen_ctx,
        system_message="You are a research assistant that generates search queries.",
        model=cfg["CLOUDRU_MODEL_NAME"],
    )

    search_queries: List[str] = []
    if search_queries_raw:
        try:
            repaired = await json_repair.repair(search_queries_raw, gen_ctx)
            # Пробуем вытащить JSON-массив
            parsed = json.loads(repaired)
            if isinstance(parsed, list):
                search_queries = [str(q).strip() for q in parsed if q]
            elif isinstance(parsed, dict) and "queries" in parsed:
                search_queries = [str(q).strip() for q in parsed["queries"] if q]
        except Exception as exc:
            logger.warning("ШАГ 1. ОШИБКА парсинга JSON, пытаемся разбить по строкам: %s", exc)

    # Fallback: если не удалось — используем оригинальный запрос
    if not search_queries:
        search_queries = [query]
        logger.warning("ШАГ 1. Fallback: используем оригинальный запрос как единственный поисковый")

    search_queries = search_queries[:search_queries_count]
    for i, sq in enumerate(search_queries, 1):
        logger.info("ШАГ 1.   [%d] %s", i, sq[:80])
    logger.info("ШАГ 1. Сгенерировано %d поисковых запросов — УСПЕХ", len(search_queries))

    # ────────────────────────────────────────────────────────────────────
    # ШАГ 1b. LLM-инференс fieldsOfStudy для фильтрации
    # ────────────────────────────────────────────────────────────────────
    infer_ctx = RequestContext(request_id="uc15-infer-fields", user_id="uc15_user", mode="chat")
    inferred_fields = await s2.infer_fields(query, infer_ctx)
    s2_filter: Optional[S2SearchFilter] = None
    if inferred_fields:
        s2_filter = S2SearchFilter(fields_of_study=inferred_fields)
        logger.info("ШАГ 1b. Инференс fieldsOfStudy: %s — УСПЕХ", inferred_fields)
    else:
        logger.info("ШАГ 1b. fieldsOfStudy не определены — поиск без фильтра")

    # ────────────────────────────────────────────────────────────────────
    # ШАГ 2. Поиск статей в Semantic Scholar (через S2Client)
    # ────────────────────────────────────────────────────────────────────
    logger.info("ШАГ 2. Поиск статей в Semantic Scholar (%d запросов × %d статей) — ОТПРАВЛЯЕМ",
                len(search_queries), papers_per_query)

    all_papers: List[Dict[str, Any]] = []
    seen_ids: set = set()

    for i, sq in enumerate(search_queries, 1):
        logger.info("ШАГ 2.   Запрос %d/%d: '%s' — ОТПРАВЛЯЕМ", i, len(search_queries), sq[:60])
        papers = await s2.search_papers(sq, limit=papers_per_query, filters=s2_filter)
        for p in papers:
            pid = p.get("paperId")
            if pid and pid not in seen_ids:
                seen_ids.add(pid)
                all_papers.append(p)
        logger.info("ШАГ 2.   Запрос %d: найдено %d (новых после дедупликации: %d)",
                    i, len(papers), len(all_papers))
        if i < len(search_queries):
            await asyncio.sleep(S2_RATE_LIMIT_DELAY)

    if not all_papers:
        logger.error("ШАГ 2. ОШИБКА: ни одной статьи не найдено")
        return {"status": "error", "message": "Semantic Scholar не вернул статей"}

    logger.info("ШАГ 2. Найдено %d уникальных статей из %d запросов — УСПЕХ",
                len(all_papers), len(search_queries))

    # ────────────────────────────────────────────────────────────────────
    # ШАГ 3. LLM-субагент отбирает top_k_relevant релевантных
    # ────────────────────────────────────────────────────────────────────
    logger.info("ШАГ 3. LLM-субагент: отбор %d из %d статей — ОТПРАВЛЯЕМ",
                top_k_relevant, len(all_papers))

    papers_summary = []
    for idx, p in enumerate(all_papers):
        abstract_short = (p.get("abstract") or "")[:200]
        authors_short = ", ".join(a["name"] for a in p.get("authors", [])[:3])
        papers_summary.append(
            f"[{idx}] paperId={p['paperId']} | {p.get('title', 'N/A')} | "
            f"{authors_short} | {p.get('year', '?')} | "
            f"cit={p.get('citationCount', 0)} | "
            f"{abstract_short}..."
        )

    filter_prompt = (
        f"User's research question: {query}\n\n"
        f"Below are {len(all_papers)} papers found on Semantic Scholar.\n"
        f"Select exactly {top_k_relevant} most relevant papers for answering the user's question.\n\n"
        + "\n".join(papers_summary) + "\n\n"
        f"Return ONLY a JSON object with key \"selected\" containing an array of indices (0-based). "
        f"Example: {{\"selected\": [0, 3, 7, 12, 15]}}\n"
        f"No explanation."
    )

    filter_ctx = RequestContext(request_id="uc15-filter", user_id="uc15_user", mode="chat")
    filter_raw = await query_llm_simple(
        llm_client, filter_prompt, filter_ctx,
        system_message="You are a research paper relevance filter. Select the most relevant papers.",
        model=cfg["CLOUDRU_MODEL_NAME"],
    )

    selected_indices: List[int] = []
    if filter_raw:
        try:
            repaired = await json_repair.repair(filter_raw, filter_ctx)
            parsed = json.loads(repaired)
            if isinstance(parsed, dict) and "selected" in parsed:
                selected_indices = [int(x) for x in parsed["selected"] if 0 <= int(x) < len(all_papers)]
            elif isinstance(parsed, list):
                selected_indices = [int(x) for x in parsed if 0 <= int(x) < len(all_papers)]
        except Exception as exc:
            logger.warning("ШАГ 3. ОШИБКА парсинга выбора: %s", exc)

    # Fallback: берём top по citationCount
    if not selected_indices or len(selected_indices) < top_k_relevant:
        logger.warning("ШАГ 3. Fallback: выбираем по citationCount")
        sorted_papers = sorted(
            enumerate(all_papers), key=lambda x: x[1].get("citationCount", 0), reverse=True,
        )
        selected_indices = [idx for idx, _ in sorted_papers[:top_k_relevant]]

    selected_indices = selected_indices[:top_k_relevant]
    selected_papers = [all_papers[i] for i in selected_indices]

    for i, p in enumerate(selected_papers, 1):
        logger.info("ШАГ 3.   [%d] %s (%s, cit=%d)",
                    i, p["title"][:60], p.get("year", "?"), p.get("citationCount", 0))
    logger.info("ШАГ 3. LLM-субагент выбрал %d статей из %d — УСПЕХ",
                len(selected_papers), len(all_papers))

    # ────────────────────────────────────────────────────────────────────
    # ШАГ 4. Формирование текстов выбранных статей
    # ────────────────────────────────────────────────────────────────────
    logger.info("ШАГ 4. Загрузка полных данных %d статей — ОТПРАВЛЯЕМ", len(selected_papers))

    paper_texts: List[Dict[str, str]] = []
    for p in selected_papers:
        text = S2Client.paper_to_text(p)
        paper_texts.append({
            "paper_id": p["paperId"],
            "title": p["title"],
            "text": text,
            "year": str(p.get("year", "")),
            "citation_count": p.get("citationCount", 0),
            "authors": ", ".join(a["name"] for a in p.get("authors", [])[:5]),
        })
        logger.info("ШАГ 4.   %s — %d символов", p["title"][:50], len(text))

    logger.info("ШАГ 4. Загружены полные данные %d статей — УСПЕХ", len(paper_texts))

    # ────────────────────────────────────────────────────────────────────
    # ШАГ 5. Чанкинг + эмбеддинг + индексация в Qdrant
    # ────────────────────────────────────────────────────────────────────
    logger.info("ШАГ 5. Чанкинг + индексация в коллекцию '%s' — ОТПРАВЛЯЕМ", collection_name)

    chunker = Chunker(chunk_size_tokens=512, chunk_overlap_tokens=128)
    all_chunks = []
    for pt in paper_texts:
        chunks = await chunker.split(text=pt["text"], source_id=pt["paper_id"])
        for c in chunks:
            c.metadata.update({
                "paper_id": pt["paper_id"],
                "title": pt["title"],
                "year": pt["year"],
                "citation_count": pt["citation_count"],
                "authors": pt["authors"],
            })
        all_chunks.extend(chunks)

    logger.info("ШАГ 5. Чанкинг: %d чанков из %d статей", len(all_chunks), len(paper_texts))

    # Инициализация RAG-клиентов для временной коллекции
    rag_clients = create_rag_clients_from_env(
        collection=collection_name,
        sparse_cache_dir=sparse_dir,
    )
    embedding_client = rag_clients["embedding"]
    sparse_client = rag_clients["sparse"]
    vector_store = rag_clients["vector_store"]
    retriever = rag_clients["retriever"]

    # Ensure collection
    await vector_store.ensure_collection(collection_name)

    # Индексация чанков (dense + sparse)
    idx_ctx = RequestContext(request_id="uc15-index", user_id="uc15_user")
    texts_for_embed = [c.text for c in all_chunks]

    if texts_for_embed:
        # Dense embeddings
        dense_vectors = await embedding_client.embed_texts(texts_for_embed)
        # Sparse embeddings (если есть)
        sparse_vectors = None
        if sparse_client:
            sparse_vectors = await sparse_client.embed_documents(texts_for_embed)

        # Upsert
        points_data = []
        for i, chunk in enumerate(all_chunks):
            payload = {
                "text": chunk.text,
                "source_id": chunk.source_id,
                "document_name": chunk.metadata.get("title", ""),
                "tags": ["s2", "research", chunk.metadata.get("year", "")],
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
        logger.info("ШАГ 5. Индексировано %d чанков из %d статей — УСПЕХ",
                    len(all_chunks), len(paper_texts))
    else:
        logger.warning("ШАГ 5. Нет чанков для индексации")

    # ────────────────────────────────────────────────────────────────────
    # ШАГ 6. RAG-поиск по коллекции статей
    # ────────────────────────────────────────────────────────────────────
    logger.info("ШАГ 6. RAG hybrid search по коллекции '%s' (top_k=%d) — ОТПРАВЛЯЕМ",
                collection_name, rag_top_k)

    rag_ctx = RequestContext(
        request_id="uc15-rag", user_id="uc15_user",
        mode="rag_qa", rag_top_k=rag_top_k,
    )
    snippets = await retriever.retrieve(query, rag_ctx, top_k=rag_top_k)

    snippets_dicts: List[Dict[str, Any]] = [
        {"text": s.text, "source_id": s.source_id, "score": s.score, "metadata": s.metadata}
        for s in snippets
    ]
    for i, s in enumerate(snippets_dicts, 1):
        logger.info("ШАГ 6.   [%d] score=%.3f | paper=%s | %.80s...",
                    i, s["score"], s["source_id"][:20], s["text"])

    logger.info("ШАГ 6. RAG вернул %d сниппетов — УСПЕХ", len(snippets_dicts))

    # ────────────────────────────────────────────────────────────────────
    # ШАГ 7. Финальный LLM-ответ с цитированием
    # ────────────────────────────────────────────────────────────────────
    logger.info("ШАГ 7. Финальный LLM-ответ с цитированием — ОТПРАВЛЯЕМ")

    prompt = build_rag_prompt(query=query, snippets=snippets_dicts)
    llm_ctx = RequestContext(request_id="uc15-llm", user_id="uc15_user", mode="rag_qa")

    if use_streaming:
        llm_answer = await stream_llm_to_stdout(
            llm_client, prompt, llm_ctx,
            system_message=SYSTEM_MSG, model=cfg["CLOUDRU_MODEL_NAME"],
        )
    else:
        llm_answer = await query_llm_simple(
            llm_client, prompt, llm_ctx,
            system_message=SYSTEM_MSG, model=cfg["CLOUDRU_MODEL_NAME"],
        )
        if llm_answer:
            print("\n" + "=" * 70 + "\nОТВЕТ LLM (Deep Academic Research):\n" + "=" * 70)
            print(llm_answer)
            print("=" * 70)

    logger.info("ШАГ 7. Финальный ответ — УСПЕХ")

    # ────────────────────────────────────────────────────────────────────
    # ШАГ 8. Возврат результата
    # ────────────────────────────────────────────────────────────────────
    sources_info = [
        {
            "paper_id": pt["paper_id"],
            "title": pt["title"],
            "authors": pt["authors"],
            "year": pt["year"],
            "citation_count": pt["citation_count"],
        }
        for pt in paper_texts
    ]

    result: Dict[str, Any] = {
        "status": "success" if llm_answer else "error",
        "uc": "UC-15",
        "query": query,
        "search_queries": search_queries,
        "total_papers_found": len(all_papers),
        "papers_selected": len(selected_papers),
        "total_chunks": len(all_chunks),
        "rag_snippets": len(snippets_dicts),
        "collection_name": collection_name,
        "sources": sources_info,
        "llm_answer": llm_answer,
        "llm_answer_length": len(llm_answer) if llm_answer else 0,
    }
    if not llm_answer:
        result["error"] = "LLM не вернул ответ"

    logger.info("ШАГ 8. Deep Academic Research завершён — УСПЕХ")
    logger.info("РЕЗУЛЬТАТ UC-15: papers_found=%d, selected=%d, chunks=%d, rag=%d, answer_len=%d",
                len(all_papers), len(selected_papers), len(all_chunks),
                len(snippets_dicts), result["llm_answer_length"])
    return result


if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser(description="UC-15: Deep Academic Research")
    parser.add_argument("query", nargs="?", default=None, help="Исследовательский запрос")
    parser.add_argument("--queries-count", type=int, default=DEFAULT_SEARCH_QUERIES_COUNT)
    parser.add_argument("--papers-per-query", type=int, default=DEFAULT_PAPERS_PER_QUERY)
    parser.add_argument("--top-k", type=int, default=DEFAULT_TOP_K_RELEVANT)
    parser.add_argument("--rag-top-k", type=int, default=DEFAULT_RAG_TOP_K)
    parser.add_argument("--stream", action="store_true")
    args = parser.parse_args()

    try:
        result = asyncio.run(main(
            query=args.query,
            search_queries_count=args.queries_count,
            papers_per_query=args.papers_per_query,
            top_k_relevant=args.top_k,
            rag_top_k=args.rag_top_k,
            use_streaming=args.stream,
        ))

        print("\n" + "=" * 70)
        print("UC-15: DEEP ACADEMIC RESEARCH ЗАВЕРШЁН")
        print("=" * 70)
        print(f"Статус: {result.get('status', 'unknown')}")
        print(f"Запрос: {result.get('query', 'N/A')}")
        print(f"Статей найдено: {result.get('total_papers_found', 0)}")
        print(f"Отобрано: {result.get('papers_selected', 0)}")
        print(f"Чанков: {result.get('total_chunks', 0)}")
        print(f"RAG-сниппетов: {result.get('rag_snippets', 0)}")
        print(f"Длина ответа: {result.get('llm_answer_length', 0)} символов")
        print(f"Коллекция: {result.get('collection_name', 'N/A')}")

        if result.get("sources"):
            print("\nИсточники:")
            for s in result["sources"]:
                print(f"  - [{s['year']}] {s['title'][:70]} (cit={s['citation_count']})")

        sys.exit(0 if result.get("status") == "success" else 1)

    except KeyboardInterrupt:
        print("\nПрервано пользователем")
        sys.exit(130)
    except Exception as exc:
        logger.exception("Критическая ошибка в UC-15: %s", exc)
        sys.exit(1)
