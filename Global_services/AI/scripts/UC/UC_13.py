# -*- coding: utf-8 -*-
"""
Руководство к файлу UC_13.py
============================

Назначение:
    Реализация UC-13: Регистрация и использование инструментов (Tool System).
    Полный цикл: определение ToolSpec → регистрация → конфигурация оркестратора →
    LLM вызывает инструменты → обработка результатов → цепочка вызовов.

    Use Case: UC-13 из LLM_SERVICE.md
    Actor: Разработчик / Системный интегратор
    Цель: Расширение функциональности LLM через пользовательские инструменты.

Архитектура (6 шагов UC-13):
    ШАГ 1. Определение инструмента (ToolSpec) — Pydantic-схемы
    ШАГ 2. Регистрация инструмента — ToolRegistry.register()
    ШАГ 3. Конфигурация оркестратора — ChatOrchestrator с ToolExecutor
    ШАГ 4. LLM вызывает инструмент — handle_user_input() с enable_tools
    ШАГ 5. Обработка результата — ToolResult
    ШАГ 6. Цепочка вызовов (iterative) — tool_call_limit

Используемые функции из llm_service.py:
    - load_env_and_validate, create_default_orchestrator_from_env
    - ToolSpec, ToolRegistry, ToolExecutor, ToolRequestContext
    - UserInput, RequestContext, ChatOrchestrator

Использование:
    python -m AI.scripts.UC.UC_13 "Найди информацию о Python и посчитай 100/3"

Зависимости:
    - llm_service.py, python-dotenv, pydantic
"""

from __future__ import annotations

import asyncio
import json
import logging
import random
import sys
from pathlib import Path
from typing import Any, Dict, List, Optional

from pydantic import BaseModel, Field

# ---------- Константы ----------
SCRIPT_DIR = Path(__file__).parent.absolute()
AI_DIR = SCRIPT_DIR.parent.parent
GLOBAL_SERVICES_DIR = AI_DIR.parent
COLLECTION_NAME = "UC"

sys.path.insert(0, str(GLOBAL_SERVICES_DIR))

from AI.llm_service import (
    RequestContext,
    ToolExecutor,
    ToolRegistry,
    ToolRequestContext,
    ToolSpec,
    UserInput,
    create_default_orchestrator_from_env,
    load_env_and_validate,
)

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s | %(levelname)-7s | %(name)s | %(message)s",
)
logger = logging.getLogger(__name__)


# ============================================================================
# ШАГ 1. Определение инструментов (ToolSpec) — Pydantic-схемы
# ============================================================================

class SearchWebArgs(BaseModel):
    query: str = Field(description="Поисковый запрос")

class SearchWebResult(BaseModel):
    query: str
    results: List[str]
    total: int

async def search_web_handler(args: SearchWebArgs, ctx: ToolRequestContext) -> SearchWebResult:
    """Демо: имитация веб-поиска."""
    logger.info("TOOL search_web: query='%s'", args.query)
    # В реальности — HTTP-запрос к поисковому API
    demo_results = [
        f"Результат 1: Статья о {args.query} на Wikipedia",
        f"Результат 2: Документация по {args.query}",
        f"Результат 3: Учебник: введение в {args.query}",
    ]
    return SearchWebResult(query=args.query, results=demo_results, total=len(demo_results))


class CalculatorArgs(BaseModel):
    expression: str = Field(description="Математическое выражение")

class CalculatorResult(BaseModel):
    expression: str
    result: float

async def calculator_handler(args: CalculatorArgs, ctx: ToolRequestContext) -> CalculatorResult:
    """Демо: безопасный калькулятор."""
    logger.info("TOOL calculator: expression='%s'", args.expression)
    allowed = set("0123456789+-*/.() ")
    if not all(c in allowed for c in args.expression):
        raise ValueError(f"Недопустимые символы: {args.expression}")
    result = eval(args.expression, {"__builtins__": {}}, {})
    return CalculatorResult(expression=args.expression, result=float(result))


class RandomFactArgs(BaseModel):
    topic: str = Field(description="Тема для факта")

class RandomFactResult(BaseModel):
    topic: str
    fact: str

async def random_fact_handler(args: RandomFactArgs, ctx: ToolRequestContext) -> RandomFactResult:
    """Демо: случайный факт по теме."""
    logger.info("TOOL random_fact: topic='%s'", args.topic)
    facts = [
        f"Интересный факт о {args.topic}: это одна из самых популярных тем в мире.",
        f"Знаете ли вы, что {args.topic} существует уже более 50 лет?",
        f"Исследования показывают, что {args.topic} становится всё более актуальной темой.",
    ]
    return RandomFactResult(topic=args.topic, fact=random.choice(facts))


# ============================================================================
# Основной пайплайн UC-13
# ============================================================================

async def main(
    query: Optional[str] = None,
    tool_call_limit: int = 3,
) -> Dict[str, Any]:
    """Основная функция UC-13: Tool System — полный цикл."""
    logger.info("=" * 70)
    logger.info("UC-13: Регистрация и использование инструментов (Tool System)")
    logger.info("=" * 70)

    if not query:
        query = "Найди информацию о Python и посчитай 100 / 3"
        logger.info("Запрос не указан, используем демо: '%s'", query)

    # ШАГ 0. Конфигурация
    try:
        load_env_and_validate(str(GLOBAL_SERVICES_DIR))
    except ValueError as exc:
        return {"status": "error", "message": str(exc)}

    # ШАГ 1. Определение инструментов
    logger.info("ШАГ 1. Определение спецификаций инструментов — ОТПРАВЛЯЕМ")

    search_spec = ToolSpec(
        name="search_web",
        description="Поиск информации в интернете по запросу",
        args_schema=SearchWebArgs,
        result_schema=SearchWebResult,
        timeout=10.0,
    )
    calc_spec = ToolSpec(
        name="calculator",
        description="Математические вычисления (арифметика)",
        args_schema=CalculatorArgs,
        result_schema=CalculatorResult,
        timeout=3.0,
    )
    fact_spec = ToolSpec(
        name="random_fact",
        description="Получение интересного факта по заданной теме",
        args_schema=RandomFactArgs,
        result_schema=RandomFactResult,
        timeout=5.0,
    )

    logger.info("ШАГ 1. Спецификации 3 инструментов созданы — УСПЕХ")

    # ШАГ 2. Регистрация инструментов
    logger.info("ШАГ 2. Регистрация инструментов — ОТПРАВЛЯЕМ")

    registry = ToolRegistry()
    await registry.register(search_spec, search_web_handler)
    logger.info("ШАГ 2. Инструмент 'search_web' зарегистрирован — УСПЕХ")
    await registry.register(calc_spec, calculator_handler)
    logger.info("ШАГ 2. Инструмент 'calculator' зарегистрирован — УСПЕХ")
    await registry.register(fact_spec, random_fact_handler)
    logger.info("ШАГ 2. Инструмент 'random_fact' зарегистрирован — УСПЕХ")

    openai_tools = registry.get_openai_tools()
    logger.info("ШАГ 2. Всего зарегистрировано %d инструментов — УСПЕХ", len(openai_tools))

    # ШАГ 3. Конфигурация оркестратора
    logger.info("ШАГ 3. Конфигурация оркестратора с ToolExecutor — ОТПРАВЛЯЕМ")

    orchestrator = create_default_orchestrator_from_env(
        collection_name=COLLECTION_NAME,
        enable_sparse=False,
    )
    # Подменяем ToolRegistry и ToolExecutor на наши с зарегистрированными тулами
    orchestrator._tools = registry
    orchestrator._tool_executor = ToolExecutor(registry, concurrency_limit=8)

    logger.info("ШАГ 3. ToolExecutor инициализирован — УСПЕХ")

    # ШАГ 4-6. LLM вызывает инструменты через оркестратор
    logger.info("ШАГ 4-6. Запуск оркестратора с enable_tools=true — ОТПРАВЛЯЕМ")

    user_input = UserInput(
        text=query,
        mode="chat",
        enable_tools=True,
        enable_streaming=False,
    )

    ctx = RequestContext(
        request_id="uc13-tools",
        user_id="uc13_user",
        mode="chat",
        enable_tools=True,
        tool_call_limit=tool_call_limit,
    )

    try:
        orch_result = await orchestrator.handle_user_input(user_input, ctx)
    except Exception as exc:
        logger.error("ШАГ 4-6. ОШИБКА оркестратора: %s", exc)
        return {"status": "error", "message": f"Orchestrator error: {exc}"}

    final_text = orch_result.response_text
    tool_calls_used = [tc.model_dump() for tc in orch_result.tool_calls]

    logger.info("ШАГ 4. LLM вызвал %d инструментов", len(tool_calls_used))
    for tc in tool_calls_used:
        logger.info("  tool='%s' args=%s", tc["name"],
                     json.dumps(tc["arguments"], ensure_ascii=False)[:100])

    logger.info("ШАГ 5. Результаты обработаны — УСПЕХ")
    logger.info("ШАГ 6. Итерации tool calls завершены — УСПЕХ")

    print("\n" + "=" * 70 + "\nОТВЕТ LLM:\n" + "=" * 70)
    print(final_text)
    print("=" * 70)

    result: Dict[str, Any] = {
        "status": "success" if final_text else "error",
        "uc": "UC-13",
        "query": query,
        "registered_tools": [t["function"]["name"] for t in openai_tools],
        "tool_calls": tool_calls_used,
        "tool_calls_count": len(tool_calls_used),
        "tool_call_limit": tool_call_limit,
        "final_answer": final_text,
        "final_answer_length": len(final_text) if final_text else 0,
    }

    logger.info("РЕЗУЛЬТАТ UC-13: status=%s, tools_used=%d, answer_len=%d",
                result["status"], len(tool_calls_used), result["final_answer_length"])
    return result


if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser(description="UC-13: Tool System Demo")
    parser.add_argument("query", nargs="?", default=None, help="Запрос пользователя")
    parser.add_argument("--tool-call-limit", type=int, default=3, help="Лимит tool calls")
    args = parser.parse_args()

    result = asyncio.run(main(query=args.query, tool_call_limit=args.tool_call_limit))

    print("\n" + "=" * 70)
    print("UC-13: TOOL SYSTEM DEMO ЗАВЕРШЁН")
    print("=" * 70)
    print(f"Статус: {result.get('status', 'unknown')}")
    print(f"Зарегистрировано тулов: {len(result.get('registered_tools', []))}")
    print(f"Вызвано тулов: {result.get('tool_calls_count', 0)}")
    print(f"Длина ответа: {result.get('final_answer_length', 0)} символов")

    sys.exit(0 if result.get("status") == "success" else 1)
