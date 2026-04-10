# -*- coding: utf-8 -*-
"""
Руководство к файлу UC_8.py
===========================

Назначение:
    Реализация UC-8: Демонстрация Tool Calling (вызов инструментов LLM).
    1. Регистрация демо-инструментов в ToolRegistry
    2. LLM анализирует запрос и выбирает тулы
    3. ToolExecutor параллельно выполняет tool calls
    4. Повторный вызов LLM с результатами tools
    5. Финальный ответ с учетом результатов

    Use Case: UC-8 из LLM_SERVICE.md
    Actor: Разработчик / Демонстрация возможностей
    Цель: Показать работу LLM с вызовом внешних инструментов (function calling).

Архитектура (5 шагов UC-8):
    ШАГ 1. Получение запроса + регистрация тулов
    ШАГ 2. LLM выбирает инструменты — OpenAIClient.complete() с tools
    ШАГ 3. Выполнение tool calls — ToolExecutor.execute_many()
    ШАГ 4. Повторный вызов LLM с результатами
    ШАГ 5. Финальный ответ

Используемые функции из llm_service.py:
    - load_env_and_validate, create_cloudru_openai_client_from_env
    - ToolSpec, ToolRegistry, ToolExecutor, ToolRequestContext
    - OpenAIClient, LLMRequest, LLMMessage, RequestContext, ToolCall

Использование:
    python -m AI.scripts.UC.UC_8 "Какая погода в Москве и сколько будет 25 * 4?"

Зависимости:
    - llm_service.py, python-dotenv, pydantic
"""

from __future__ import annotations

import asyncio
import json
import logging
import math
import sys
from pathlib import Path
from typing import Any, Dict, List, Optional

from pydantic import BaseModel, Field

# ---------- Константы ----------
SCRIPT_DIR = Path(__file__).parent.absolute()
AI_DIR = SCRIPT_DIR.parent.parent
GLOBAL_SERVICES_DIR = AI_DIR.parent

sys.path.insert(0, str(GLOBAL_SERVICES_DIR))

from AI.llm_service import (
    LLMMessage,
    LLMRequest,
    RequestContext,
    ToolCall,
    ToolExecutor,
    ToolRegistry,
    ToolRequestContext,
    ToolSpec,
    create_cloudru_openai_client_from_env,
    load_env_and_validate,
)

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s | %(levelname)-7s | %(name)s | %(message)s",
)
logger = logging.getLogger(__name__)


# ============================================================================
# Демо-инструменты: схемы аргументов, результатов и хендлеры
# ============================================================================

class WeatherArgs(BaseModel):
    city: str = Field(description="Название города")

class WeatherResult(BaseModel):
    city: str
    temperature: float
    condition: str
    humidity: int

async def weather_handler(args: WeatherArgs, ctx: ToolRequestContext) -> WeatherResult:
    """Демо: возвращает фиктивную погоду."""
    logger.info("TOOL weather_handler: city=%s", args.city)
    # В реальности здесь был бы HTTP-запрос к API погоды
    demo_data = {
        "москва": WeatherResult(city="Москва", temperature=15.0, condition="облачно", humidity=68),
        "санкт-петербург": WeatherResult(city="Санкт-Петербург", temperature=10.0, condition="дождь", humidity=85),
    }
    return demo_data.get(args.city.lower(), WeatherResult(
        city=args.city, temperature=20.0, condition="солнечно", humidity=55,
    ))


class CalculateArgs(BaseModel):
    expression: str = Field(description="Математическое выражение для вычисления")

class CalculateResult(BaseModel):
    expression: str
    result: float

async def calculate_handler(args: CalculateArgs, ctx: ToolRequestContext) -> CalculateResult:
    """Демо: безопасный калькулятор."""
    logger.info("TOOL calculate_handler: expression=%s", args.expression)
    allowed = set("0123456789+-*/.() ")
    if not all(c in allowed for c in args.expression):
        raise ValueError(f"Недопустимые символы в выражении: {args.expression}")
    try:
        result = eval(args.expression, {"__builtins__": {}}, {"math": math})
        return CalculateResult(expression=args.expression, result=float(result))
    except Exception as exc:
        raise ValueError(f"Ошибка вычисления: {exc}")


class DocumentInfoArgs(BaseModel):
    document_id: str = Field(description="ID документа")

class DocumentInfoResult(BaseModel):
    document_id: str
    title: str
    pages: int
    format: str
    size_bytes: int

async def document_info_handler(args: DocumentInfoArgs, ctx: ToolRequestContext) -> DocumentInfoResult:
    """Демо: возвращает фиктивные метаданные документа."""
    logger.info("TOOL document_info_handler: doc_id=%s", args.document_id)
    return DocumentInfoResult(
        document_id=args.document_id,
        title="Отчёт за Q4 2024",
        pages=42,
        format="PDF",
        size_bytes=1_540_000,
    )


async def register_demo_tools(registry: ToolRegistry) -> None:
    """Регистрация всех демо-инструментов."""
    await registry.register(
        ToolSpec(
            name="get_current_weather",
            description="Получение текущей погоды по названию города",
            args_schema=WeatherArgs,
            result_schema=WeatherResult,
            timeout=5.0,
        ),
        weather_handler,
    )
    await registry.register(
        ToolSpec(
            name="calculate",
            description="Математические вычисления (арифметика)",
            args_schema=CalculateArgs,
            result_schema=CalculateResult,
            timeout=3.0,
        ),
        calculate_handler,
    )
    await registry.register(
        ToolSpec(
            name="get_document_info",
            description="Получение метаданных документа по его ID",
            args_schema=DocumentInfoArgs,
            result_schema=DocumentInfoResult,
            timeout=5.0,
        ),
        document_info_handler,
    )
    logger.info("ШАГ 1. Зарегистрировано %d инструментов", 3)


# ============================================================================
# Основной пайплайн UC-8
# ============================================================================

async def main(
    query: Optional[str] = None,
    tool_call_limit: int = 3,
) -> Dict[str, Any]:
    """Основная функция UC-8: Демонстрация Tool Calling."""
    logger.info("=" * 70)
    logger.info("UC-8: Демонстрация Tool Calling (вызов инструментов LLM)")
    logger.info("=" * 70)

    if not query:
        query = "Какая погода в Москве и сколько будет 25 * 4?"
        logger.info("Запрос не указан, используем демо: '%s'", query)

    # ШАГ 0. Конфигурация
    try:
        cfg = load_env_and_validate(str(GLOBAL_SERVICES_DIR))
    except ValueError as exc:
        return {"status": "error", "message": str(exc)}

    # ШАГ 1. Получение запроса + регистрация тулов
    logger.info("ШАГ 1. Получен запрос с enable_tools=true — УСПЕХ: '%s'", query[:80])

    registry = ToolRegistry()
    await register_demo_tools(registry)
    executor = ToolExecutor(registry, concurrency_limit=8)

    llm_client = create_cloudru_openai_client_from_env()
    ctx = RequestContext(
        request_id="uc8-tools",
        user_id="uc8_user",
        mode="chat",
        enable_tools=True,
        tool_call_limit=tool_call_limit,
    )

    openai_tools = registry.get_openai_tools()
    logger.info("ШАГ 1. Доступные инструменты: %s",
                [t["function"]["name"] for t in openai_tools])

    # ШАГ 2. LLM анализирует запрос и выбирает тулы
    logger.info("ШАГ 2. LLM выбирает инструменты — ОТПРАВЛЯЕМ")
    messages: List[LLMMessage] = [
        LLMMessage(
            role="system",
            content=(
                "Ты — полезный ассистент с доступом к инструментам. "
                "Используй инструменты для получения актуальной информации. "
                "Вызывай инструменты при необходимости."
            ),
        ),
        LLMMessage(role="user", content=query),
    ]

    request = LLMRequest(
        messages=messages,
        model=cfg["CLOUDRU_MODEL_NAME"],
        tools=openai_tools,
        tool_choice="auto",
    )

    response = await llm_client.create_response(request, ctx)
    logger.info("ШАГ 2. LLM ответил: content_len=%d, tool_calls=%d",
                len(response.content), len(response.tool_calls))

    all_tool_calls: List[Dict[str, Any]] = []
    all_tool_results: List[Dict[str, Any]] = []
    iteration = 0

    while response.tool_calls and iteration < tool_call_limit:
        iteration += 1
        tool_names = [tc.name for tc in response.tool_calls]
        logger.info("ШАГ 2. LLM выбрал инструменты: %s — УСПЕХ", tool_names)

        # ШАГ 3. Выполнение tool calls
        logger.info("ШАГ 3. Выполнение tool calls (итерация %d/%d) — ОТПРАВЛЯЕМ",
                     iteration, tool_call_limit)

        results = await executor.execute_many(response.tool_calls, ctx)

        for tc, tr in zip(response.tool_calls, results):
            all_tool_calls.append({
                "id": tc.id, "name": tc.name, "arguments": tc.arguments,
            })
            all_tool_results.append({
                "id": tr.id, "name": tr.name, "output": tr.output,
                "is_error": tr.is_error, "error_message": tr.error_message,
            })
            status = "ОШИБКА" if tr.is_error else "УСПЕХ"
            logger.info("ШАГ 3.   tool=%s — %s: %s", tc.name, status,
                         json.dumps(tr.output, ensure_ascii=False)[:200])

        logger.info("ШАГ 3. Tool calls выполнены — УСПЕХ (%d результатов)", len(results))

        # ШАГ 4. Повторный вызов LLM с результатами
        logger.info("ШАГ 4. Повторный вызов LLM с результатами tools — ОТПРАВЛЯЕМ")

        # Добавляем assistant message с tool_calls
        assistant_tc_msg = LLMMessage(
            role="assistant",
            content=response.content or "",
            tool_calls=[
                {
                    "id": tc.id, "type": "function",
                    "function": {"name": tc.name, "arguments": json.dumps(tc.arguments, ensure_ascii=False)},
                }
                for tc in response.tool_calls
            ],
        )
        messages.append(assistant_tc_msg)

        # Добавляем tool result messages
        for tr in results:
            content_str = (
                json.dumps(tr.output, ensure_ascii=False)
                if not tr.is_error
                else json.dumps({"error": tr.error_message}, ensure_ascii=False)
            )
            messages.append(LLMMessage(
                role="tool", content=content_str, tool_call_id=tr.id,
            ))

        request = LLMRequest(
            messages=messages,
            model=cfg["CLOUDRU_MODEL_NAME"],
            tools=openai_tools,
            tool_choice="auto",
        )
        response = await llm_client.create_response(request, ctx)
        logger.info("ШАГ 4. LLM получил результаты tools — УСПЕХ (content_len=%d, new_tool_calls=%d)",
                     len(response.content), len(response.tool_calls))

    # ШАГ 5. Финальный ответ
    final_text = response.content
    logger.info("ШАГ 5. Финальный ответ с tool results — УСПЕХ (len=%d)", len(final_text))

    print("\n" + "=" * 70 + "\nОТВЕТ LLM:\n" + "=" * 70)
    print(final_text)
    print("=" * 70)

    result: Dict[str, Any] = {
        "status": "success" if final_text else "error",
        "uc": "UC-8",
        "query": query,
        "tool_calls": all_tool_calls,
        "tool_results": all_tool_results,
        "tool_iterations": iteration,
        "final_answer": final_text,
        "final_answer_length": len(final_text),
    }

    logger.info("РЕЗУЛЬТАТ UC-8: status=%s, tools_used=%d, iterations=%d, answer_len=%d",
                result["status"], len(all_tool_calls), iteration, len(final_text))
    return result


if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser(description="UC-8: Tool Calling Demo")
    parser.add_argument("query", nargs="?", default=None, help="Запрос пользователя")
    parser.add_argument("--tool-call-limit", type=int, default=3, help="Лимит итераций tool calls")
    args = parser.parse_args()

    result = asyncio.run(main(query=args.query, tool_call_limit=args.tool_call_limit))

    print("\n" + "=" * 70)
    print("UC-8: TOOL CALLING DEMO ЗАВЕРШЁН")
    print("=" * 70)
    print(f"Статус: {result.get('status', 'unknown')}")
    print(f"Инструментов вызвано: {len(result.get('tool_calls', []))}")
    print(f"Итераций: {result.get('tool_iterations', 0)}")
    print(f"Длина ответа: {result.get('final_answer_length', 0)} символов")

    sys.exit(0 if result.get("status") == "success" else 1)
