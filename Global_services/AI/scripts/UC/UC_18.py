# -*- coding: utf-8 -*-
"""
Руководство к файлу UC_18.py
=============================

Назначение:
    Реализация UC-18: Рекомендации научных статей (Semantic Scholar Recommendations).
    Тонкий клиент — вся S2-логика делегирована S2Client из llm_service.py.
    Pipeline:
        1. S2Client.get_paper — валидация seed-статей
        2. S2Client.get_recommendations_single / get_recommendations_from_lists
        3. LLM-субагент фильтрует и ранжирует рекомендации
        4. Обогащение аннотаций (полные abstracts + tldr)
        5. Финальный LLM-обзор рекомендованных статей
        6. Возврат структурированного результата

    Use Case: UC-18 из LLM_SERVICE.md
    Actor: Исследователь / Студент / Аналитик
    Цель: Персонализированные рекомендации на основе seed-статей + LLM-аннотации.

Используемые классы/функции из llm_service.py:
    - S2Client, S2_RATE_LIMIT_DELAY
    - load_env_and_validate, create_cloudru_openai_client_from_env
    - RequestContext, query_llm_simple, stream_llm_to_stdout
    - JsonRepairLLM

Внешние зависимости:
    - semanticscholar (pip install semanticscholar)
    - llm_service.py, python-dotenv

Использование:
    python -m AI.scripts.UC.UC_18 "649def34f8be52c8b66281af98ae884c09aef38b"
    python -m AI.scripts.UC.UC_18 --seeds "ARXIV:1706.03762" "ARXIV:2005.14165" --top-k 5
"""

from __future__ import annotations

import asyncio
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

DEFAULT_MAX_RECOMMENDATIONS = 20
DEFAULT_TOP_K_FINAL = 5

sys.path.insert(0, str(GLOBAL_SERVICES_DIR))

from AI.llm_service import (
    JsonRepairLLM,
    RequestContext,
    S2Client,
    S2_RATE_LIMIT_DELAY,
    create_cloudru_openai_client_from_env,
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
    "Ты — эксперт по рекомендациям научной литературы. "
    "Анализируй предоставленные статьи, группируй по темам, "
    "указывай связь с seed-статьями и ценность каждой рекомендации."
)


# ============================================================================
# Основная функция
# ============================================================================

async def main(
    seed_paper_ids: Optional[List[str]] = None,
    negative_paper_ids: Optional[List[str]] = None,
    max_recommendations: int = DEFAULT_MAX_RECOMMENDATIONS,
    top_k_final: int = DEFAULT_TOP_K_FINAL,
    use_streaming: bool = False,
) -> Dict[str, Any]:
    """Основная функция UC-18: Рекомендации научных статей."""
    logger.info("=" * 70)
    logger.info("UC-18: Рекомендации научных статей (Semantic Scholar Recommendations)")
    logger.info("=" * 70)

    if not seed_paper_ids:
        seed_paper_ids = ["ARXIV:1706.03762"]  # Attention Is All You Need
        logger.info("Seed не указаны, используем демо: %s", seed_paper_ids)

    # ШАГ 0. Конфигурация
    try:
        cfg = load_env_and_validate(str(GLOBAL_SERVICES_DIR))
    except ValueError as exc:
        return {"status": "error", "message": str(exc)}

    llm_client = create_cloudru_openai_client_from_env()
    json_repair = JsonRepairLLM()
    s2 = S2Client()

    # ────────────────────────────────────────────────────────────────────
    # ШАГ 1. Валидация seed-статей
    # ────────────────────────────────────────────────────────────────────
    logger.info("ШАГ 1. Валидация %d seed-статей — ОТПРАВЛЯЕМ", len(seed_paper_ids))

    seed_papers: List[Dict[str, Any]] = []
    for i, pid in enumerate(seed_paper_ids):
        paper = await s2.get_paper(pid)
        if paper:
            seed_papers.append(paper)
            logger.info("ШАГ 1.   [%d] \"%s\" (%s, cit=%d) — УСПЕХ",
                        i + 1, paper["title"][:50], paper.get("year", "?"),
                        paper["citationCount"])
        else:
            logger.warning("ШАГ 1.   [%d] '%s' — НЕ НАЙДЕНА", i + 1, pid)
        if i < len(seed_paper_ids) - 1:
            await asyncio.sleep(S2_RATE_LIMIT_DELAY)

    if not seed_papers:
        return {"status": "error", "message": "Ни одна seed-статья не найдена"}

    logger.info("ШАГ 1. Валидированы %d seed-статей — УСПЕХ", len(seed_papers))

    # ────────────────────────────────────────────────────────────────────
    # ШАГ 2. Запрос рекомендаций из S2
    # ────────────────────────────────────────────────────────────────────
    logger.info("ШАГ 2. Запрос рекомендаций (max=%d) — ОТПРАВЛЯЕМ", max_recommendations)

    valid_seed_ids = [p["paperId"] for p in seed_papers]

    if len(valid_seed_ids) == 1:
        logger.info("ШАГ 2. Одна seed → get_recommended_papers()")
        recommendations = await s2.get_recommendations_single(
            valid_seed_ids[0], limit=max_recommendations,
        )
    else:
        logger.info("ШАГ 2. Несколько seeds → get_recommendations_from_lists()")
        recommendations = await s2.get_recommendations_from_lists(
            valid_seed_ids, negative_paper_ids, limit=max_recommendations,
        )

    if not recommendations:
        logger.error("ШАГ 2. ОШИБКА: S2 не вернул рекомендаций")
        return {"status": "error", "message": "S2 не вернул рекомендаций"}

    for i, r in enumerate(recommendations[:5], 1):
        logger.info("ШАГ 2.   [%d] %s (%s, cit=%d)",
                    i, r["title"][:50], r.get("year", "?"), r["citationCount"])
    if len(recommendations) > 5:
        logger.info("ШАГ 2.   ... и ещё %d", len(recommendations) - 5)

    logger.info("ШАГ 2. S2 вернул %d рекомендаций — УСПЕХ", len(recommendations))

    # ────────────────────────────────────────────────────────────────────
    # ШАГ 3. LLM-фильтрация и ранжирование
    # ────────────────────────────────────────────────────────────────────
    logger.info("ШАГ 3. LLM-фильтрация: отбор %d из %d — ОТПРАВЛЯЕМ",
                top_k_final, len(recommendations))

    seed_context = "\n".join(
        f"  Seed [{i+1}]: {p['title']} ({p.get('year', '?')})"
        for i, p in enumerate(seed_papers)
    )

    recs_summary = []
    for idx, r in enumerate(recommendations):
        abstract_short = (r.get("abstract") or "")[:200]
        authors_short = ", ".join(a["name"] for a in r.get("authors", [])[:3])
        recs_summary.append(
            f"[{idx}] {r['title']} | {authors_short} | {r.get('year', '?')} | "
            f"cit={r['citationCount']} | {abstract_short}..."
        )

    filter_prompt = (
        f"Seed papers (основа для рекомендаций):\n{seed_context}\n\n"
        f"Below are {len(recommendations)} recommended papers from Semantic Scholar.\n"
        f"Select exactly {top_k_final} most valuable papers. For each, provide:\n"
        f"- index (0-based)\n"
        f"- annotation (2-3 sentences why it's valuable)\n"
        f"- relevance_score (1-10)\n\n"
        + "\n".join(recs_summary) + "\n\n"
        f"Return JSON: {{\"selected\": [{{\"index\": 0, \"annotation\": \"...\", \"relevance_score\": 8}}, ...]}}\n"
        f"No explanation outside JSON."
    )

    filter_ctx = RequestContext(request_id="uc18-filter", user_id="uc18_user", mode="chat")
    filter_raw = await query_llm_simple(
        llm_client, filter_prompt, filter_ctx,
        system_message="You are a paper recommendation filter. Select and annotate the most valuable papers.",
        model=cfg["CLOUDRU_MODEL_NAME"],
    )

    selected_with_annotations: List[Dict[str, Any]] = []
    if filter_raw:
        try:
            repaired = await json_repair.repair(filter_raw, filter_ctx)
            parsed = json.loads(repaired)
            items = parsed.get("selected", parsed) if isinstance(parsed, dict) else parsed
            if isinstance(items, list):
                for item in items:
                    idx = int(item.get("index", -1))
                    if 0 <= idx < len(recommendations):
                        selected_with_annotations.append({
                            "index": idx,
                            "annotation": item.get("annotation", ""),
                            "relevance_score": item.get("relevance_score", 5),
                        })
        except Exception as exc:
            logger.warning("ШАГ 3. ОШИБКА парсинга фильтрации: %s", exc)

    # Fallback: по citationCount
    if len(selected_with_annotations) < top_k_final:
        logger.warning("ШАГ 3. Fallback: дополняем по citationCount")
        used_indices = {s["index"] for s in selected_with_annotations}
        sorted_recs = sorted(
            enumerate(recommendations),
            key=lambda x: x[1].get("citationCount", 0),
            reverse=True,
        )
        for idx, _ in sorted_recs:
            if idx not in used_indices and len(selected_with_annotations) < top_k_final:
                selected_with_annotations.append({
                    "index": idx,
                    "annotation": "Высокоцитируемая статья (автоматический отбор)",
                    "relevance_score": 5,
                })

    selected_with_annotations = selected_with_annotations[:top_k_final]

    for s in selected_with_annotations:
        r = recommendations[s["index"]]
        logger.info("ШАГ 3.   [%d] score=%d | %s (%s)",
                    s["index"], s["relevance_score"], r["title"][:50], r.get("year", "?"))

    logger.info("ШАГ 3. LLM отобрал %d из %d рекомендаций — УСПЕХ",
                len(selected_with_annotations), len(recommendations))

    # ────────────────────────────────────────────────────────────────────
    # ШАГ 4. Обогащение аннотаций
    # ────────────────────────────────────────────────────────────────────
    logger.info("ШАГ 4. Обогащение карточек %d статей — ОТПРАВЛЯЕМ",
                len(selected_with_annotations))

    enriched_cards: List[Dict[str, Any]] = []
    for s in selected_with_annotations:
        r = recommendations[s["index"]]
        authors_str = ", ".join(a["name"] for a in r.get("authors", [])[:5])
        card = {
            "paper_id": r["paperId"],
            "title": r["title"],
            "authors": authors_str,
            "year": r.get("year"),
            "venue": r.get("venue", ""),
            "citation_count": r["citationCount"],
            "abstract": r.get("abstract", ""),
            "tldr": r.get("tldr", ""),
            "fields_of_study": r.get("fieldsOfStudy", []),
            "llm_annotation": s["annotation"],
            "relevance_score": s["relevance_score"],
        }
        enriched_cards.append(card)
        logger.info("ШАГ 4.   %s — обогащено", r["title"][:50])

    logger.info("ШАГ 4. Карточки %d статей обогащены — УСПЕХ", len(enriched_cards))

    # ────────────────────────────────────────────────────────────────────
    # ШАГ 5. Финальный LLM-обзор
    # ────────────────────────────────────────────────────────────────────
    logger.info("ШАГ 5. Финальный LLM-обзор рекомендаций — ОТПРАВЛЯЕМ")

    cards_text = ""
    for i, c in enumerate(enriched_cards, 1):
        abstract_short = (c["abstract"] or "")[:300]
        cards_text += (
            f"═══ РЕКОМЕНДАЦИЯ {i} (релевантность: {c['relevance_score']}/10) ═══\n"
            f"Название: {c['title']}\n"
            f"Авторы: {c['authors']}\n"
            f"Год: {c.get('year', 'N/A')} | Venue: {c['venue']}\n"
            f"Цитирований: {c['citation_count']}\n"
            f"Области: {', '.join(c.get('fields_of_study', []))}\n"
            f"Abstract: {abstract_short}...\n"
            f"TLDR: {c.get('tldr', 'N/A')}\n"
            f"LLM-аннотация: {c['llm_annotation']}\n\n"
        )

    review_prompt = (
        f"Seed papers:\n{seed_context}\n\n"
        f"Отобранные рекомендации ({len(enriched_cards)} штук):\n\n"
        f"{cards_text}"
        f"═══ ЗАДАЧА ═══\n"
        f"Сформируй обзор рекомендованных статей:\n"
        f"1. Группировка по темам / направлениям\n"
        f"2. Связь каждой группы с seed-статьями\n"
        f"3. Приоритет чтения (с чего начать)\n"
        f"4. Общее резюме: как рекомендации расширяют тему seed-статей\n"
    )

    llm_ctx = RequestContext(request_id="uc18-review", user_id="uc18_user", mode="chat")

    if use_streaming:
        llm_answer = await stream_llm_to_stdout(
            llm_client, review_prompt, llm_ctx,
            system_message=SYSTEM_MSG, model=cfg["CLOUDRU_MODEL_NAME"],
        )
    else:
        llm_answer = await query_llm_simple(
            llm_client, review_prompt, llm_ctx,
            system_message=SYSTEM_MSG, model=cfg["CLOUDRU_MODEL_NAME"],
        )
        if llm_answer:
            print("\n" + "=" * 70 + "\nОБЗОР РЕКОМЕНДАЦИЙ:\n" + "=" * 70)
            print(llm_answer)
            print("=" * 70)

    logger.info("ШАГ 5. Финальный обзор рекомендаций — УСПЕХ")

    # ────────────────────────────────────────────────────────────────────
    # ШАГ 6. Возврат результата
    # ────────────────────────────────────────────────────────────────────
    seed_info = [
        {
            "paper_id": p["paperId"],
            "title": p["title"],
            "year": p.get("year"),
            "citation_count": p["citationCount"],
        }
        for p in seed_papers
    ]

    result: Dict[str, Any] = {
        "status": "success" if llm_answer else "error",
        "uc": "UC-18",
        "seed_papers": seed_info,
        "total_recommendations": len(recommendations),
        "selected_count": len(enriched_cards),
        "recommendations": enriched_cards,
        "llm_overview": llm_answer,
        "llm_overview_length": len(llm_answer) if llm_answer else 0,
    }
    if not llm_answer:
        result["error"] = "LLM не вернул ответ"

    logger.info("ШАГ 6. Рекомендации статей завершены — УСПЕХ")
    logger.info("РЕЗУЛЬТАТ UC-18: seeds=%d, recs_total=%d, selected=%d, answer_len=%d",
                len(seed_papers), len(recommendations),
                len(enriched_cards), result["llm_overview_length"])
    return result


if __name__ == "__main__":
    import argparse

    ap = argparse.ArgumentParser(description="UC-18: Рекомендации научных статей")
    ap.add_argument("seeds", nargs="*", default=None,
                    help="Seed paper IDs (S2 ID, DOI, ArXiv)")
    ap.add_argument("--max-recs", type=int, default=DEFAULT_MAX_RECOMMENDATIONS)
    ap.add_argument("--top-k", type=int, default=DEFAULT_TOP_K_FINAL)
    ap.add_argument("--negative", nargs="*", default=None, help="Negative paper IDs")
    ap.add_argument("--stream", action="store_true")
    args = ap.parse_args()

    _seeds = args.seeds if args.seeds else None

    try:
        result = asyncio.run(main(
            seed_paper_ids=_seeds,
            negative_paper_ids=args.negative,
            max_recommendations=args.max_recs,
            top_k_final=args.top_k,
            use_streaming=args.stream,
        ))

        print("\n" + "=" * 70)
        print("UC-18: РЕКОМЕНДАЦИИ СТАТЕЙ ЗАВЕРШЕНЫ")
        print("=" * 70)
        print(f"Статус: {result.get('status', 'unknown')}")
        print(f"Seeds: {len(result.get('seed_papers', []))}")
        print(f"Рекомендаций найдено: {result.get('total_recommendations', 0)}")
        print(f"Отобрано: {result.get('selected_count', 0)}")
        print(f"Длина обзора: {result.get('llm_overview_length', 0)} символов")

        if result.get("recommendations"):
            print("\nОтобранные статьи:")
            for r in result["recommendations"]:
                print(f"  - [{r.get('year', '?')}] {r['title'][:60]} "
                      f"(cit={r['citation_count']}, rel={r['relevance_score']})")

        sys.exit(0 if result.get("status") == "success" else 1)

    except KeyboardInterrupt:
        print("\nПрервано пользователем")
        sys.exit(130)
    except Exception as exc:
        logger.exception("Критическая ошибка в UC-18: %s", exc)
        sys.exit(1)
