# -*- coding: utf-8 -*-
"""
Центральный модуль-обёртка для pipeline-сервисов.

Решает проблемы:
- Корректная инициализация env из корня проекта
- Единый LLM-клиент (singleton)
- Автоматическое создание RequestContext
- Streaming: stdout (CLI) или SSE queue (web API)
"""

import asyncio
import json
import logging
import os
import sys
import uuid
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional

logger = logging.getLogger(__name__)

# Путь к корню проекта и Global_services
_PROJECT_ROOT = Path(__file__).resolve().parent.parent
_GLOBAL_SERVICES = str(_PROJECT_ROOT / "Global_services")

if _GLOBAL_SERVICES not in sys.path:
    sys.path.insert(0, _GLOBAL_SERVICES)

from AI.llm_service import (  # noqa: E402
    LLMMessage,
    LLMRequest,
    RequestContext,
    create_cloudru_openai_client_from_env,
    load_env_and_validate,
    stream_llm_to_stdout,
    query_llm_simple as _query_llm_simple,
)

# ── Singleton state ──────────────────────────────────────────────────────────
_env_config: Optional[Dict[str, str]] = None
_llm_client = None

# ── SSE queue (None = stdout mode) ───────────────────────────────────────────
_sse_queue: Optional[asyncio.Queue] = None


def set_sse_queue(queue: Optional[asyncio.Queue]) -> None:
    """Установить SSE-очередь. None = fallback на stdout."""
    global _sse_queue
    _sse_queue = queue
    logger.info("llm_helpers: SSE queue %s", "установлена" if queue else "отключена (stdout)")


def get_sse_queue() -> Optional[asyncio.Queue]:
    """Получить текущую SSE-очередь."""
    return _sse_queue


async def emit_sse(event_type: str, data: Any) -> None:
    """Отправить SSE-событие в очередь (если есть)."""
    if _sse_queue is not None:
        await _sse_queue.put({"event": event_type, "data": data})


def init_env() -> Dict[str, str]:
    """Загрузить .env из корня проекта (singleton)."""
    global _env_config
    if _env_config is not None:
        return _env_config

    _env_config = load_env_and_validate(str(_PROJECT_ROOT))
    logger.info("llm_helpers: env загружен из %s", _PROJECT_ROOT)
    return _env_config


def get_env_config() -> Dict[str, str]:
    """Получить env_config (инициализирует при первом вызове)."""
    return init_env()


def get_llm_client():
    """Получить OpenAIClient (singleton, читает из os.environ)."""
    global _llm_client
    if _llm_client is not None:
        return _llm_client

    init_env()  # гарантируем что .env загружен
    _llm_client = create_cloudru_openai_client_from_env()
    logger.info("llm_helpers: LLM-клиент создан")
    return _llm_client


def make_ctx(**kwargs) -> RequestContext:
    """Создать RequestContext с уникальным request_id."""
    return RequestContext(
        request_id=str(uuid.uuid4()),
        **kwargs,
    )


async def _stream_to_sse(
    client,
    prompt: str,
    ctx: RequestContext,
    system_message: str,
    temperature: float,
    max_output_tokens: int,
) -> Optional[str]:
    """Стриминг LLM → SSE queue (каждый токен = event)."""
    try:
        request = LLMRequest(
            messages=[
                LLMMessage(role="system", content=system_message),
                LLMMessage(role="user", content=prompt),
            ],
            model="",
            temperature=temperature,
            max_output_tokens=max_output_tokens,
        )

        collected: List[str] = []
        async for event in client.stream_response(request, ctx):
            if event.kind == "token_delta":
                text = event.data.get("text", "")
                collected.append(text)
                # Шлём каждый токен в SSE
                await emit_sse("token", {"text": text})

        answer = "".join(collected).strip()
        if not answer:
            return None
        return answer

    except Exception as exc:
        logger.error("_stream_to_sse ОШИБКА: %s", exc)
        await emit_sse("error", {"message": str(exc)})
        return None


async def call_llm(
    prompt: str,
    *,
    temperature: float = 0.2,
    max_output_tokens: int = 4096,
    system_message: str = "Ты — полезный ассистент-аналитик. Отвечай структурированно.",
    streaming: bool = True,
) -> Optional[str]:
    """Вызов LLM.

    Режим определяется наличием SSE-очереди:
    - SSE queue есть → токены идут в queue (для web frontend)
    - SSE queue нет → токены идут в stdout (для CLI)
    - streaming=False → non-streaming запрос

    Returns:
        Текст ответа или None при ошибке.
    """
    client = get_llm_client()
    ctx = make_ctx()

    if not streaming:
        return await _query_llm_simple(
            llm_client=client, prompt=prompt, ctx=ctx,
            system_message=system_message, temperature=temperature,
            max_output_tokens=max_output_tokens,
        )

    if _sse_queue is not None:
        return await _stream_to_sse(
            client, prompt, ctx, system_message, temperature, max_output_tokens,
        )
    else:
        return await stream_llm_to_stdout(
            llm_client=client, prompt=prompt, ctx=ctx,
            system_message=system_message, temperature=temperature,
            max_output_tokens=max_output_tokens,
        )
