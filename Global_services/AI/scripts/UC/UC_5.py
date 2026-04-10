# -*- coding: utf-8 -*-
"""
Руководство к файлу UC_5.py
===========================

Назначение:
    Реализация UC-5: Генерация структурированных данных (JSON Schema).
    1. Определение JSON-схемы ответа
    2. Подготовка промпта с инструкцией
    3. LLM-запрос с response_format=json_object
    4. Валидация и ремонт JSON через StrictOutputParser + JsonRepairLLM
    5. Возврат валидированного результата

    Use Case: UC-5 из LLM_SERVICE.md
    Actor: Разработчик / API-клиент
    Цель: Получение ответа LLM в строго заданном JSON-формате.

Архитектура (5 шагов UC-5):
    ШАГ 1. Определение схемы — Pydantic-модель + JSON Schema
    ШАГ 2. Подготовка запроса — промпт с инструкцией
    ШАГ 3. LLM-запрос — OpenAIClient.complete() с json_object
    ШАГ 4. Валидация и ремонт — StrictOutputParser + JsonRepairLLM
    ШАГ 5. Возврат результата

Используемые функции из llm_service.py:
    - load_env_and_validate, create_cloudru_openai_client_from_env
    - OpenAIClient, LLMRequest, LLMMessage, RequestContext
    - StrictOutputParser, JsonRepairLLM

Использование:
    python -m AI.scripts.UC.UC_5 "Сгенерируй профиль пользователя"
    python -m AI.scripts.UC.UC_5 --context "Иван Иванов, 30 лет, инженер"

Зависимости:
    - llm_service.py, python-dotenv, pydantic
"""

from __future__ import annotations

import asyncio
import json
import logging
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
    JsonRepairLLM,
    LLMMessage,
    LLMRequest,
    RequestContext,
    StrictOutputParser,
    create_cloudru_openai_client_from_env,
    load_env_and_validate,
)

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s | %(levelname)-7s | %(name)s | %(message)s",
)
logger = logging.getLogger(__name__)


# ---------- Демо-схемы для примера ----------

class UserProfile(BaseModel):
    """Демо-схема: профиль пользователя."""
    name: str = Field(description="Полное имя")
    age: int = Field(description="Возраст")
    occupation: str = Field(description="Профессия")
    skills: List[str] = Field(description="Список навыков (3-5 штук)")
    summary: str = Field(description="Краткое описание (1-2 предложения)")


class ProductCard(BaseModel):
    """Демо-схема: карточка товара."""
    title: str = Field(description="Название товара")
    category: str = Field(description="Категория")
    price_rub: float = Field(description="Цена в рублях")
    features: List[str] = Field(description="Ключевые характеристики (3-5)")
    description: str = Field(description="Описание товара (2-3 предложения)")


# Реестр доступных схем
SCHEMA_REGISTRY: Dict[str, type[BaseModel]] = {
    "user_profile": UserProfile,
    "product_card": ProductCard,
}


async def generate_structured_data(
    user_query: str,
    schema_name: str = "user_profile",
    context: Optional[str] = None,
    max_retries: int = 2,
) -> Dict[str, Any]:
    """Полный пайплайн UC-5: генерация структурированных данных."""
    logger.info("=" * 70)
    logger.info("UC-5: Генерация структурированных данных (JSON Schema)")
    logger.info("Схема: %s | Запрос: %.80s", schema_name, user_query)
    logger.info("=" * 70)

    # ШАГ 0. Конфигурация
    try:
        cfg = load_env_and_validate(str(GLOBAL_SERVICES_DIR))
    except ValueError as exc:
        return {"status": "error", "message": str(exc)}

    # ШАГ 1. Определение схемы
    logger.info("ШАГ 1. Определение схемы ответа — %s", schema_name)
    if schema_name not in SCHEMA_REGISTRY:
        logger.error("ШАГ 1. ОШИБКА: Неизвестная схема '%s'. Доступные: %s",
                      schema_name, list(SCHEMA_REGISTRY.keys()))
        return {"status": "error", "message": f"Неизвестная схема: {schema_name}"}

    schema_model = SCHEMA_REGISTRY[schema_name]
    json_schema = schema_model.model_json_schema()
    logger.info("ШАГ 1. Получена схема ответа — УСПЕХ: %s, поля=%s",
                schema_name, list(json_schema.get("properties", {}).keys()))

    # ШАГ 2. Подготовка запроса
    logger.info("ШАГ 2. Подготовка промпта с инструкцией — ОТПРАВЛЯЕМ")

    schema_str = json.dumps(json_schema, ensure_ascii=False, indent=2)
    context_block = f"\n\nДополнительный контекст:\n{context}" if context else ""

    system_message = (
        "Ты — ассистент, который генерирует структурированные данные.\n"
        "Ответь СТРОГО в формате JSON по заданной схеме.\n"
        "Не добавляй комментарии, не оборачивай в markdown.\n"
        "Верни ТОЛЬКО валидный JSON-объект.\n\n"
        f"JSON Schema (обязательные поля и типы):\n{schema_str}"
    )

    user_message = f"{user_query}{context_block}"

    logger.info("ШАГ 2. Промпт с инструкцией готов — УСПЕХ (system_len=%d, user_len=%d)",
                len(system_message), len(user_message))

    # ШАГ 3. LLM-запрос с constrained output
    logger.info("ШАГ 3. Запрос к LLM с response_format=json_object — ОТПРАВЛЯЕМ")

    llm_client = create_cloudru_openai_client_from_env()
    ctx = RequestContext(request_id="uc5-structured", user_id="uc5_user", mode="chat")

    request = LLMRequest(
        messages=[
            LLMMessage(role="system", content=system_message),
            LLMMessage(role="user", content=user_message),
        ],
        model=cfg["CLOUDRU_MODEL_NAME"],
        temperature=0.3,
        response_format={"type": "json_object"},
    )

    try:
        response = await llm_client.create_response(request, ctx)
        raw_text = response.content
        logger.info("ШАГ 3. LLM ответил — УСПЕХ: raw_len=%d", len(raw_text))
    except Exception as exc:
        logger.error("ШАГ 3. ОШИБКА запроса к LLM: %s", exc)
        return {"status": "error", "message": f"LLM error: {exc}"}

    # ШАГ 4. Валидация и ремонт JSON
    logger.info("ШАГ 4. Валидация JSON через StrictOutputParser — ОТПРАВЛЯЕМ")

    json_repair = JsonRepairLLM()
    parser = StrictOutputParser(json_repair)

    parsed_model = None
    last_error = None

    for attempt in range(1, max_retries + 1):
        try:
            parsed_model = await parser.parse_json(raw_text, schema_model, ctx)
            logger.info("ШАГ 4. Валидация JSON — УСПЕХ (попытка %d/%d)", attempt, max_retries)
            break
        except json.JSONDecodeError as exc:
            last_error = f"JSONDecodeError: {exc}"
            logger.warning("ШАГ 4. Попытка %d/%d — JSON невалиден: %s", attempt, max_retries, exc)
            # Пробуем ремонт
            raw_text = await json_repair.repair(raw_text, ctx)
        except Exception as exc:
            last_error = f"ValidationError: {exc}"
            logger.warning("ШАГ 4. Попытка %d/%d — Pydantic валидация: %s", attempt, max_retries, exc)
            break

    if parsed_model is None:
        logger.error("ШАГ 4. ОШИБКА — не удалось валидировать JSON после %d попыток: %s",
                      max_retries, last_error)
        return {
            "status": "error",
            "message": f"JSON validation failed: {last_error}",
            "raw_response": raw_text,
        }

    # ШАГ 5. Возврат валидированного результата
    validated_data = parsed_model.model_dump()
    logger.info("ШАГ 5. Структурированный ответ отправлен — УСПЕХ")

    result: Dict[str, Any] = {
        "status": "success",
        "uc": "UC-5",
        "schema_name": schema_name,
        "user_query": user_query,
        "validated_data": validated_data,
        "raw_response": raw_text,
    }

    logger.info("РЕЗУЛЬТАТ UC-5: status=success, schema=%s, fields=%d",
                schema_name, len(validated_data))
    return result


async def main(
    query: Optional[str] = None,
    schema_name: str = "user_profile",
    context: Optional[str] = None,
) -> Dict[str, Any]:
    """CLI-точка входа для UC-5."""
    if not query:
        query = "Сгенерируй профиль разработчика Python с опытом в ML"
        logger.info("Запрос не указан, используем демо: '%s'", query)

    return await generate_structured_data(
        user_query=query,
        schema_name=schema_name,
        context=context,
    )


if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser(description="UC-5: Генерация структурированных данных")
    parser.add_argument("query", nargs="?", default=None, help="Запрос пользователя")
    parser.add_argument("--schema", default="user_profile",
                        choices=list(SCHEMA_REGISTRY.keys()), help="Имя схемы")
    parser.add_argument("--context", default=None, help="Дополнительный контекст")
    args = parser.parse_args()

    result = asyncio.run(main(query=args.query, schema_name=args.schema, context=args.context))

    print("\n" + "=" * 70)
    print("UC-5: ГЕНЕРАЦИЯ СТРУКТУРИРОВАННЫХ ДАННЫХ ЗАВЕРШЕНА")
    print("=" * 70)
    print(f"Статус: {result.get('status', 'unknown')}")
    print(f"Схема: {result.get('schema_name', 'N/A')}")

    if result.get("status") == "success":
        print(f"\nВалидированные данные:")
        print(json.dumps(result["validated_data"], ensure_ascii=False, indent=2))
        sys.exit(0)
    else:
        print(f"Ошибка: {result.get('message', 'Unknown')}")
        sys.exit(1)
