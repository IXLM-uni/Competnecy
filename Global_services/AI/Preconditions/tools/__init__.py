# -*- coding: utf-8 -*-
"""
Руководство к файлу __init__.py (Preconditions/tools)
=====================================================

Назначение:
    Пакет с моковыми тулзами для e2e-тестирования UC-5.
    Экспортирует register_mock_tools() для регистрации
    calendar_tool и calculator_tool в ToolRegistry.
"""

from AI.Preconditions.tools.calendar_tool import register_calendar_tool
from AI.Preconditions.tools.calculator_tool import register_calculator_tool

from AI.llm_service import ToolRegistry


async def register_mock_tools(registry: ToolRegistry) -> None:
    """Регистрирует все моковые тулзы в реестре."""
    await register_calendar_tool(registry)
    await register_calculator_tool(registry)


__all__ = [
    "register_mock_tools",
    "register_calendar_tool",
    "register_calculator_tool",
]
