# -*- coding: utf-8 -*-
"""
Руководство к файлу calendar_tool.py
=====================================

Назначение:
    Моковый тул «calendar_tool» для e2e-тестирования UC-5.
    Возвращает фиксированный набор событий календаря.
    Используется для проверки цепочки tool calling в ChatOrchestrator.

Pydantic-схемы:
    CalendarArgs   — аргументы (period: str)
    CalendarResult — результат (events: list[CalendarEvent])

Регистрация:
    await register_calendar_tool(registry)
"""

from __future__ import annotations

import logging
from datetime import datetime, timedelta
from typing import List, Optional

from pydantic import BaseModel, Field

from AI.llm_service import ToolRegistry, ToolRequestContext, ToolSpec

logger = logging.getLogger(__name__)


# ---------- Pydantic-схемы ----------

class CalendarEvent(BaseModel):
    title: str
    start: str
    end: str
    duration_minutes: int


class CalendarArgs(BaseModel):
    period: str = Field(
        default="week",
        description="Период: 'today', 'week', 'month'",
    )


class CalendarResult(BaseModel):
    events: List[CalendarEvent] = Field(default_factory=list)
    total_duration_minutes: int = 0


# ---------- Хендлер ----------

async def _calendar_handler(
    args: BaseModel, ctx: ToolRequestContext,
) -> Optional[BaseModel]:
    logger.info(
        "ШАГ TOOL calendar_tool. Получен запрос: period=%s, request_id=%s",
        getattr(args, "period", "week"), ctx.request_id,
    )

    now = datetime.utcnow()
    mock_events = [
        CalendarEvent(
            title="Стендап команды",
            start=(now + timedelta(hours=1)).isoformat(),
            end=(now + timedelta(hours=1, minutes=30)).isoformat(),
            duration_minutes=30,
        ),
        CalendarEvent(
            title="Обзор спринта",
            start=(now + timedelta(days=1)).isoformat(),
            end=(now + timedelta(days=1, hours=1)).isoformat(),
            duration_minutes=60,
        ),
        CalendarEvent(
            title="1-on-1 с тимлидом",
            start=(now + timedelta(days=2)).isoformat(),
            end=(now + timedelta(days=2, minutes=45)).isoformat(),
            duration_minutes=45,
        ),
        CalendarEvent(
            title="Демо для заказчика",
            start=(now + timedelta(days=3)).isoformat(),
            end=(now + timedelta(days=3, hours=2)).isoformat(),
            duration_minutes=120,
        ),
    ]

    total = sum(e.duration_minutes for e in mock_events)
    result = CalendarResult(events=mock_events, total_duration_minutes=total)

    logger.info(
        "ШАГ TOOL calendar_tool. УСПЕХ: events=%d, total_minutes=%d",
        len(mock_events), total,
    )
    return result


# ---------- Регистрация ----------

async def register_calendar_tool(registry: ToolRegistry) -> None:
    spec = ToolSpec(
        name="calendar_tool",
        description=(
            "Читает события календаря за указанный период. "
            "Возвращает список событий с названием, временем и длительностью."
        ),
        args_schema=CalendarArgs,
        result_schema=CalendarResult,
        timeout=5.0,
    )
    await registry.register(spec, _calendar_handler)
    logger.info("calendar_tool зарегистрирован в ToolRegistry")
