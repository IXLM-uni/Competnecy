# -*- coding: utf-8 -*-
"""
Руководство к файлу UC_2.py
==========================

Назначение:
    Реализация UC-2: Мультимодальный запрос (аудио + RAG поиск по кластеру UC).
    1. ASR-транскрибация аудиофайла через Cloud.ru Whisper
    2. Гибридный RAG-поиск по коллекции "UC" (dense + sparse + RRF fusion)
    3. LLM-ответ с учётом найденных сниппетов

Архитектура (6 шагов UC-2):
    ШАГ 1. ASR — ASRClient.transcribe_file()
    ШАГ 2. Инициализация RAG — create_rag_clients_from_env()
    ШАГ 3. RAG-поиск — Retriever.retrieve()
    ШАГ 4. Промпт — build_rag_prompt()
    ШАГ 5. LLM-стриминг — stream_llm_to_stdout()
    ШАГ 6. Формирование ответа

Используемые функции из llm_service.py:
    - load_env_and_validate, create_rag_clients_from_env
    - ASRClient, create_cloudru_openai_client_from_env
    - build_rag_prompt, stream_llm_to_stdout, RequestContext

Использование:
    python -m AI.scripts.UC.UC_2 [путь_к_аудио]

Зависимости:
    - llm_service.py, python-dotenv
"""

from __future__ import annotations

import asyncio
import logging
import sys
from pathlib import Path
from typing import Any, Dict, List, Optional

# ---------- Константы ----------
SCRIPT_DIR = Path(__file__).parent.absolute()
AI_DIR = SCRIPT_DIR.parent.parent
GLOBAL_SERVICES_DIR = AI_DIR.parent
AUDIO_DIR = AI_DIR / "Preconditions" / "audio"
SPARSE_CACHE_DIR = AI_DIR / "models" / "sparse_cache"
COLLECTION_NAME = "UC"
DEFAULT_AUDIO_FILE = AUDIO_DIR / "Запись.ogg"

sys.path.insert(0, str(GLOBAL_SERVICES_DIR))

from AI.llm_service import (
    ASRClient,
    RequestContext,
    build_rag_prompt,
    create_cloudru_openai_client_from_env,
    create_rag_clients_from_env,
    load_env_and_validate,
    stream_llm_to_stdout,
)

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s | %(levelname)-7s | %(name)s | %(message)s",
)
logger = logging.getLogger(__name__)


async def transcribe_audio(cfg: Dict[str, str], audio_path: str) -> Optional[str]:
    """ШАГ 1. ASR-транскрибация аудиофайла."""
    logger.info("ШАГ 1. ASR-транскрибация файла: %s", audio_path)

    audio_file = Path(audio_path)
    if not audio_file.exists():
        logger.error("ШАГ 1. ОШИБКА: Аудиофайл не найден: %s", audio_path)
        return None

    logger.info("ШАГ 1. Аудиофайл: %s (%d байт)", audio_file.name, audio_file.stat().st_size)

    try:
        asr_client = ASRClient(
            api_key=cfg["CLOUDRU_API_KEY"],
            base_url=cfg["CLOUDRU_BASE_URL"],
        )
        ctx = RequestContext(request_id="uc2-asr", user_id="uc2_user", mode="rag_tool")
        transcript = await asr_client.transcribe_file(str(audio_file.absolute()), ctx)

        text = transcript.text.strip()
        if not text:
            logger.warning("ШАГ 1. ASR вернул пустой текст")
            return None

        logger.info("ШАГ 1. ASR — УСПЕХ: %d символов | %.100s...", len(text), text)
        return text
    except Exception as exc:
        logger.error("ШАГ 1. ОШИБКА транскрибации: %s", exc)
        return None


async def main(audio_path: Optional[str] = None) -> Dict[str, Any]:
    """Основная функция UC-2: Мультимодальный запрос (аудио + RAG)."""
    logger.info("=" * 70)
    logger.info("UC-2: Мультимодальный запрос (аудио + RAG по кластеру UC)")
    logger.info("Коллекция: %s | Аудио: %s", COLLECTION_NAME, audio_path or DEFAULT_AUDIO_FILE)
    logger.info("=" * 70)

    # ШАГ 0. Конфигурация
    try:
        cfg = load_env_and_validate(str(GLOBAL_SERVICES_DIR))
    except ValueError as exc:
        return {"status": "error", "message": str(exc)}

    sparse_dir = cfg["SPARSE_CACHE_DIR"] or str(SPARSE_CACHE_DIR)
    if not Path(sparse_dir).exists():
        logger.error("ОШИБКА: SPARSE_CACHE_DIR не найден: %s", sparse_dir)
        return {"status": "error", "message": "SPARSE_CACHE_DIR не найден"}

    audio_file = str(Path(audio_path) if audio_path else DEFAULT_AUDIO_FILE)

    # ШАГ 1. ASR-транскрибация
    transcript = await transcribe_audio(cfg, audio_file)
    if not transcript:
        return {"status": "error", "message": "ASR-транскрибация не удалась"}

    # ШАГ 2. Инициализация RAG-клиентов
    clients = create_rag_clients_from_env(
        collection=COLLECTION_NAME,
        sparse_cache_dir=sparse_dir,
    )
    retriever = clients["retriever"]

    # ШАГ 3. RAG-поиск
    ctx = RequestContext(request_id="uc2-rag", user_id="uc2_user", mode="rag_tool", rag_top_k=6)
    snippets = await retriever.retrieve(transcript, ctx, top_k=6)

    snippets_dicts: List[Dict[str, Any]] = [
        {"text": s.text, "source_id": s.source_id, "score": s.score, "metadata": s.metadata}
        for s in snippets
    ]
    for i, s in enumerate(snippets_dicts, 1):
        logger.info("ШАГ 3.   [%d] score=%.3f | %.100s...", i, s["score"], s["text"])

    # ШАГ 4. Промпт
    prompt = build_rag_prompt(query=transcript, snippets=snippets_dicts)

    # ШАГ 5. LLM-стриминг
    llm_client = create_cloudru_openai_client_from_env()
    llm_ctx = RequestContext(request_id="uc2-llm", user_id="uc2_user", mode="rag_tool")
    llm_answer = await stream_llm_to_stdout(
        llm_client=llm_client,
        prompt=prompt,
        ctx=llm_ctx,
        system_message="Ты — эксперт по анализу научных документов. Давай точные, структурированные ответы с указанием источников.",
        model=cfg["CLOUDRU_MODEL_NAME"],
    )

    # ШАГ 6. Результат
    result: Dict[str, Any] = {
        "status": "success" if llm_answer else "error",
        "uc": "UC-2",
        "collection": COLLECTION_NAME,
        "transcript": transcript,
        "transcript_length": len(transcript),
        "rag_results": {"found": len(snippets_dicts), "snippets": snippets_dicts},
        "llm_answer": llm_answer,
        "llm_answer_length": len(llm_answer) if llm_answer else 0,
    }
    if not llm_answer:
        result["error"] = "LLM не вернул ответ"

    logger.info("РЕЗУЛЬТАТ UC-2: status=%s, snippets=%d, answer_len=%d",
                result["status"], len(snippets_dicts), result["llm_answer_length"])
    return result


if __name__ == "__main__":
    _audio = sys.argv[1] if len(sys.argv) > 1 else None
    result = asyncio.run(main(audio_path=_audio))

    print("\n" + "=" * 70)
    print("UC-2: МУЛЬТИМОДАЛЬНЫЙ ЗАПРОС ЗАВЕРШЁН")
    print("=" * 70)
    print(f"Статус: {result.get('status', 'unknown')}")
    print(f"Длина транскрипта: {result.get('transcript_length', 0)} символов")
    print(f"Найдено сниппетов: {result.get('rag_results', {}).get('found', 0)}")
    print(f"Длина ответа LLM: {result.get('llm_answer_length', 0)} символов")

    if result.get("status") == "error":
        print(f"Ошибка: {result.get('error', result.get('message', 'Unknown'))}")
        sys.exit(1)
    else:
        print("\nУСПЕХ: UC-2 выполнен")
        sys.exit(0)