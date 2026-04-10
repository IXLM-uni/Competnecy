# -*- coding: utf-8 -*-
"""
Руководство к файлу UC_4.py
===========================

Назначение:
    Реализация UC-4: Streaming-чат с показом промежуточных токенов.
    1. Подготовка UserInput с enable_streaming=True
    2. Инициализация ChatOrchestrator (через create_default_orchestrator_from_env)
    3. Запуск stream_user_input() → обработка StreamEvent
    4. Финализация ответа

Архитектура:
    ШАГ 1. Подготовка UserInput
    ШАГ 2. Создание оркестратора — create_default_orchestrator_from_env()
    ШАГ 3-4. Стрим + обработка событий
    ШАГ 5. Финализация

Используемые функции из llm_service.py:
    - load_env_and_validate, create_default_orchestrator_from_env
    - UserInput, RequestContext, StreamEvent

Использование:
    python -m AI.scripts.UC.UC_4 "Ваш вопрос" [--mode rag_qa] [--enable-tools] [--use-internet]

Зависимости:
    - llm_service.py, python-dotenv
"""

from __future__ import annotations

import argparse
import asyncio
import json
import logging
import sys
from pathlib import Path
from typing import Any, Dict, List, Optional

# ---------- Константы ----------
SCRIPT_DIR = Path(__file__).parent.absolute()
AI_DIR = SCRIPT_DIR.parent.parent
GLOBAL_SERVICES_DIR = AI_DIR.parent
COLLECTION_NAME = "UC"

sys.path.insert(0, str(GLOBAL_SERVICES_DIR))

from AI.llm_service import (
    RequestContext,
    UserInput,
    create_default_orchestrator_from_env,
    load_env_and_validate,
)

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s | %(levelname)-7s | %(name)s | %(message)s",
)
logger = logging.getLogger(__name__)


async def process_stream_events(stream_iterator) -> Dict[str, Any]:
    """ШАГ 3-4. Обработка событий стрима (StreamEvent)."""
    logger.info("ШАГ 3-4. Обработка событий стрима")

    full_text = ""
    sources: List[Dict[str, Any]] = []
    tool_calls: List[Dict[str, Any]] = []
    event_count = 0
    token_count = 0

    async for event in stream_iterator:
        event_count += 1
        kind = event.kind
        data = event.data or {}

        if kind == "init":
            logger.info("ШАГ 3. Событие: init — стрим инициализирован")
        elif kind == "token_delta":
            full_text += data.get("text", "")
            token_count += 1
            print(data.get("text", ""), end="", flush=True)
        elif kind == "tool_call":
            tool_calls.append({"id": data.get("id"), "name": data.get("name"), "arguments": data.get("arguments")})
            logger.info("ШАГ 4. tool_call: %s", data.get("name"))
            print(f"\n[TOOL CALL: {data.get('name')}]\n", flush=True)
        elif kind == "tool_result":
            logger.info("ШАГ 4. tool_result: %s (error=%s)", data.get("name"), data.get("is_error", False))
        elif kind == "rag_progress":
            logger.info("ШАГ 4. rag_progress: %s", event.step)
        elif kind == "internet_progress":
            logger.info("ШАГ 4. internet_progress: %s", event.step)
        elif kind == "final":
            sources = data.get("sources", [])
            tool_calls = data.get("tool_calls", tool_calls)
            logger.info("ШАГ 4. final: text_len=%d, sources=%d", len(data.get("text", "")), len(sources))
        elif kind == "done":
            logger.info("ШАГ 4. done: conversation_id=%s", data.get("conversation_id"))
        elif kind == "error":
            logger.error("ШАГ 4. error: %s", data.get("message", "?"))
            print(f"\n[ERROR: {data.get('message', '?')}]\n", flush=True)

    print("\n")

    logger.info("ШАГ 4. Стрим завершён: events=%d, tokens=%d, text_len=%d", event_count, token_count, len(full_text))
    return {"full_text": full_text, "sources": sources, "tool_calls": tool_calls, "event_count": event_count, "token_count": token_count}


async def run_uc4_streaming(
    text: str,
    mode: str = "chat",
    enable_tools: bool = False,
    use_internet: bool = False,
    conversation_id: Optional[str] = None,
) -> Optional[Dict[str, Any]]:
    """Полный пайплайн UC-4: Streaming-чат."""
    logger.info("=" * 60)
    logger.info("UC-4: Streaming-чат | mode=%s | tools=%s | internet=%s", mode, enable_tools, use_internet)
    logger.info("=" * 60)

    # ШАГ 1. Подготовка UserInput
    text = (text or "").strip()
    if not text:
        logger.error("ШАГ 1. ОШИБКА: Текст не предоставлен")
        return None

    user_input = UserInput(
        text=text,
        mode=mode,  # type: ignore[arg-type]
        enable_streaming=True,
        enable_tools=enable_tools,
        use_internet=use_internet,
        conversation_id=conversation_id,
    )
    logger.info("ШАГ 1. UserInput — УСПЕХ: text_len=%d, mode=%s", len(text), mode)

    # ШАГ 2. Создание оркестратора
    enable_sparse = mode in ("rag_qa", "rag_tool")
    orchestrator = create_default_orchestrator_from_env(
        collection_name=COLLECTION_NAME,
        enable_sparse=enable_sparse,
    )
    logger.info("ШАГ 2. ChatOrchestrator — УСПЕХ")

    # ШАГ 3. Запуск стрима
    ctx = RequestContext(
        request_id="uc4-stream",
        conversation_id=conversation_id,
        enable_streaming=True,
        mode=mode,
        use_internet=use_internet,
        enable_tools=enable_tools,
    )

    print("\n" + "=" * 60 + "\nSTREAMING RESPONSE:\n" + "=" * 60)
    stream_result = await process_stream_events(orchestrator.stream_user_input(user_input, ctx))
    print("=" * 60)

    # ШАГ 5. Финализация
    final_result = {
        "conversation_id": conversation_id,
        "mode": mode,
        "enable_streaming": True,
        "enable_tools": enable_tools,
        "use_internet": use_internet,
        "response_text": stream_result["full_text"],
        "sources_count": len(stream_result["sources"]),
        "tool_calls_count": len(stream_result["tool_calls"]),
        "events_processed": stream_result["event_count"],
        "tokens_received": stream_result["token_count"],
    }
    logger.info("ШАГ 5. Финализация — УСПЕХ")
    logger.info("UC-4 ЗАВЕРШЁН УСПЕШНО")

    return final_result


def main():
    """CLI-точка входа для UC-4."""
    parser = argparse.ArgumentParser(description="UC-4: Streaming-чат")
    parser.add_argument("text", nargs="?", default="Расскажи о преимуществах Python для разработки")
    parser.add_argument("--mode", choices=["chat", "rag_qa", "rag_tool"], default="chat")
    parser.add_argument("--enable-tools", action="store_true")
    parser.add_argument("--use-internet", action="store_true")
    parser.add_argument("--conversation-id", type=str, default=None)
    args = parser.parse_args()

    # Загружаем .env через хелпер
    try:
        load_env_and_validate(str(GLOBAL_SERVICES_DIR))
    except ValueError as exc:
        print(f"ОШИБКА конфигурации: {exc}", file=sys.stderr)
        sys.exit(1)

    result = asyncio.run(run_uc4_streaming(
        text=args.text, mode=args.mode,
        enable_tools=args.enable_tools, use_internet=args.use_internet,
        conversation_id=args.conversation_id,
    ))

    if result:
        print("\n" + "=" * 60 + "\nИТОГОВЫЙ РЕЗУЛЬТАТ:\n" + "=" * 60)
        print(json.dumps(result, indent=2, ensure_ascii=False))
        sys.exit(0)
    else:
        print("\nОшибка выполнения UC-4", file=sys.stderr)
        sys.exit(1)


if __name__ == "__main__":
    main()
