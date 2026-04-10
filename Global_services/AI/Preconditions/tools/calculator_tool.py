# -*- coding: utf-8 -*-
"""
Руководство к файлу calculator_tool.py
=======================================

Назначение:
    Моковый тул «calculator_tool» для e2e-тестирования UC-5.
    Выполняет базовые арифметические операции и расчёт длительностей.
    Используется для проверки цепочки tool calling в ChatOrchestrator.

Pydantic-схемы:
    CalculatorArgs   — аргументы (expression: str)
    CalculatorResult — результат (result: float, description: str)

Регистрация:
    await register_calculator_tool(registry)
"""

from __future__ import annotations

import logging
import math
from typing import Optional

from pydantic import BaseModel, Field

from AI.llm_service import ToolRegistry, ToolRequestContext, ToolSpec

logger = logging.getLogger(__name__)


# ---------- Pydantic-схемы ----------

class CalculatorArgs(BaseModel):
    expression: str = Field(
        description=(
            "Арифметическое выражение для вычисления, например: "
            "'30 + 60 + 45 + 120' или '255 / 60'"
        ),
    )


class CalculatorResult(BaseModel):
    result: float
    expression: str
    description: str = ""


# ---------- Хендлер ----------

# Допустимые имена для eval (безопасный набор)
_SAFE_NAMES = {
    "abs": abs,
    "round": round,
    "min": min,
    "max": max,
    "sum": sum,
    "int": int,
    "float": float,
    "pow": pow,
    "sqrt": math.sqrt,
    "ceil": math.ceil,
    "floor": math.floor,
    "pi": math.pi,
}


async def _calculator_handler(
    args: BaseModel, ctx: ToolRequestContext,
) -> Optional[BaseModel]:
    expression = getattr(args, "expression", "0")
    logger.info(
        "ШАГ TOOL calculator_tool. Получен запрос: expression='%s', "
        "request_id=%s",
        expression, ctx.request_id,
    )

    try:
        result_value = float(eval(expression, {"__builtins__": {}}, _SAFE_NAMES))
        description = f"Результат вычисления: {expression} = {result_value}"
        logger.info(
            "ШАГ TOOL calculator_tool. УСПЕХ: %s = %s",
            expression, result_value,
        )
        return CalculatorResult(
            result=result_value,
            expression=expression,
            description=description,
        )
    except Exception as exc:
        logger.error(
            "ШАГ TOOL calculator_tool. ОШИБКА: expression='%s', error=%s",
            expression, exc,
        )
        return CalculatorResult(
            result=0.0,
            expression=expression,
            description=f"Ошибка вычисления: {exc}",
        )


# ---------- Регистрация ----------

async def register_calculator_tool(registry: ToolRegistry) -> None:
    spec = ToolSpec(
        name="calculator_tool",
        description=(
            "Вычисляет арифметическое выражение. "
            "Поддерживает +, -, *, /, sqrt, pow, ceil, floor, round, min, max. "
            "Подходит для расчёта длительностей, сумм и конвертаций."
        ),
        args_schema=CalculatorArgs,
        result_schema=CalculatorResult,
        timeout=5.0,
    )
    await registry.register(spec, _calculator_handler)
    logger.info("calculator_tool зарегистрирован в ToolRegistry")
