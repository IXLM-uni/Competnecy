# -*- coding: utf-8 -*-
"""
Руководство к файлу UC_9.py
===========================

Назначение:
    Реализация UC-9: Классификация документов через LLM (LLM-based Classification).
    1. Загрузка и инжест документа — DocumentIngestor
    2. Извлечение ключевых фрагментов — Chunker
    3. Определение списка категорий
    4. LLM-классификация с JSON-ответом
    5. Валидация результата — StrictOutputParser + JsonRepairLLM
    6. Применение метаданных (вывод результата)

    Use Case: UC-9 из LLM_SERVICE.md
    Actor: Администратор / Автоматизированный процесс
    Цель: Автоматическое определение категории документа через LLM-анализ.

Архитектура (6 шагов UC-9):
    ШАГ 1. Загрузка документа — DocumentIngestor.ingest()
    ШАГ 2. Извлечение ключевых фрагментов — первые N чанков
    ШАГ 3. Определение списка категорий
    ШАГ 4. LLM-классификация — OpenAIClient.complete() с json_object
    ШАГ 5. Валидация результата — StrictOutputParser
    ШАГ 6. Применение метаданных

Используемые функции из llm_service.py:
    - load_env_and_validate, create_cloudru_openai_client_from_env
    - DocumentIngestor, FileRef, Chunker, RequestContext
    - OpenAIClient, LLMRequest, LLMMessage
    - StrictOutputParser, JsonRepairLLM

Использование:
    python -m AI.scripts.UC.UC_9 [путь_к_документу] [--categories cat1 cat2 ...]

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
DOCUMENTS_DIR = AI_DIR / "Preconditions" / "documents"

DEFAULT_CATEGORIES = ["legal", "financial", "technical", "medical", "scientific", "other"]
MAX_CONTEXT_TOKENS = 4000
CONFIDENCE_THRESHOLD = 0.7

sys.path.insert(0, str(GLOBAL_SERVICES_DIR))

from AI.llm_service import (
    DocumentIngestor,
    FileRef,
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


# ---------- Схема результата классификации ----------

class ClassificationResult(BaseModel):
    """Результат LLM-классификации документа."""
    category: str = Field(description="Категория документа")
    confidence: float = Field(description="Уверенность классификации от 0 до 1")
    reasoning: str = Field(description="Обоснование выбора категории")


async def main(
    file_path: Optional[str] = None,
    categories: Optional[List[str]] = None,
    confidence_threshold: float = CONFIDENCE_THRESHOLD,
) -> Dict[str, Any]:
    """Основная функция UC-9: Классификация документов через LLM."""
    logger.info("=" * 70)
    logger.info("UC-9: Классификация документов через LLM")
    logger.info("=" * 70)

    cats = categories or DEFAULT_CATEGORIES

    # Находим файл для классификации
    if not file_path:
        files = DocumentIngestor.scan_directory(str(DOCUMENTS_DIR))
        if not files:
            return {"status": "error", "message": "Нет файлов для классификации"}
        file_path = files[0]
        logger.info("Файл не указан, используем первый из Preconditions: %s", Path(file_path).name)

    if not Path(file_path).exists():
        return {"status": "error", "message": f"Файл не найден: {file_path}"}

    # ШАГ 0. Конфигурация
    try:
        cfg = load_env_and_validate(str(GLOBAL_SERVICES_DIR))
    except ValueError as exc:
        return {"status": "error", "message": str(exc)}

    ctx = RequestContext(request_id="uc9-classify", user_id="uc9_user", mode="chat")

    # ШАГ 1. Загрузка документа
    logger.info("ШАГ 1. Загрузка и инжест документа: %s", Path(file_path).name)
    ingestor = DocumentIngestor()
    file_ref = FileRef(path=file_path, original_name=Path(file_path).name)

    try:
        chunks = await ingestor.ingest(file_ref, ctx)
    except Exception as exc:
        logger.error("ШАГ 1. ОШИБКА инжеста: %s", exc)
        return {"status": "error", "message": f"Ошибка инжеста: {exc}"}

    if not chunks:
        return {"status": "error", "message": "Документ пуст или не удалось извлечь текст"}

    logger.info("ШАГ 1. Документ для классификации получен — УСПЕХ: %d чанков", len(chunks))

    # ШАГ 2. Извлечение ключевых фрагментов
    logger.info("ШАГ 2. Извлечение ключевых фрагментов — ОТПРАВЛЯЕМ")
    # Берём первые N чанков (начало документа обычно содержит мета-информацию)
    total_len = 0
    selected_chunks = []
    for chunk in chunks:
        if total_len + len(chunk.text) > MAX_CONTEXT_TOKENS * 4:  # ~4 символа на токен
            break
        selected_chunks.append(chunk)
        total_len += len(chunk.text)

    context_text = "\n\n".join(c.text for c in selected_chunks)
    logger.info("ШАГ 2. Ключевые фрагменты извлечены — УСПЕХ: %d чанков, %d символов",
                len(selected_chunks), len(context_text))

    # ШАГ 3. Определение списка категорий
    logger.info("ШАГ 3. Получен список категорий — УСПЕХ: %s", cats)

    # ШАГ 4. LLM-классификация
    logger.info("ШАГ 4. LLM-классификация — ОТПРАВЛЯЕМ")
    llm_client = create_cloudru_openai_client_from_env()

    categories_str = ", ".join(f'"{c}"' for c in cats)
    schema_str = json.dumps(ClassificationResult.model_json_schema(), ensure_ascii=False, indent=2)

    system_msg = (
        "Ты — эксперт по классификации документов.\n"
        "Проанализируй содержимое документа и определи его категорию.\n"
        "Ответь СТРОГО в формате JSON с полями: category, confidence, reasoning.\n"
        "Не добавляй ничего кроме JSON.\n\n"
        f"JSON Schema:\n{schema_str}"
    )

    user_msg = (
        f"Категории для классификации: [{categories_str}]\n\n"
        f"═══ СОДЕРЖИМОЕ ДОКУМЕНТА ═══\n\n{context_text}\n\n"
        "═══ ЗАДАНИЕ ═══\n"
        "Классифицируй этот документ по ОДНОЙ из указанных категорий.\n"
        "Confidence: 0.0 (не уверен) — 1.0 (полностью уверен).\n"
        "Если документ не подходит ни под одну категорию — используй 'other'."
    )

    request = LLMRequest(
        messages=[
            LLMMessage(role="system", content=system_msg),
            LLMMessage(role="user", content=user_msg),
        ],
        model=cfg["CLOUDRU_MODEL_NAME"],
        temperature=0.1,
        response_format={"type": "json_object"},
    )

    try:
        response = await llm_client.create_response(request, ctx)
        raw_text = response.content
        logger.info("ШАГ 4. LLM-классификация — УСПЕХ: raw_len=%d", len(raw_text))
    except Exception as exc:
        logger.error("ШАГ 4. ОШИБКА запроса к LLM: %s", exc)
        return {"status": "error", "message": f"LLM error: {exc}"}

    # ШАГ 5. Валидация результата
    logger.info("ШАГ 5. Валидация результата классификации — ОТПРАВЛЯЕМ")
    json_repair = JsonRepairLLM()
    parser = StrictOutputParser(json_repair)

    try:
        classification = await parser.parse_json(raw_text, ClassificationResult, ctx)
        logger.info("ШАГ 5. Результат классификации валидирован — УСПЕХ")
    except Exception as exc:
        logger.error("ШАГ 5. ОШИБКА валидации: %s", exc)
        return {"status": "error", "message": f"Validation error: {exc}", "raw_response": raw_text}

    # Проверка: категория из списка
    if classification.category not in cats:
        logger.warning("ШАГ 5. Категория '%s' не в реестре, помечаем как 'other'",
                        classification.category)
        classification.category = "other"

    # Проверка уверенности
    needs_review = classification.confidence < confidence_threshold
    if needs_review:
        logger.warning("ШАГ 5. Низкая уверенность (%.2f < %.2f) — требуется ручная проверка",
                        classification.confidence, confidence_threshold)

    # ШАГ 6. Применение метаданных
    logger.info("ШАГ 6. Категория '%s' (confidence=%.2f) применена к документу — УСПЕХ",
                classification.category, classification.confidence)

    result: Dict[str, Any] = {
        "status": "success",
        "uc": "UC-9",
        "file": Path(file_path).name,
        "file_path": file_path,
        "chunks_analyzed": len(selected_chunks),
        "total_chunks": len(chunks),
        "classification": classification.model_dump(),
        "needs_manual_review": needs_review,
        "available_categories": cats,
    }

    logger.info("РЕЗУЛЬТАТ UC-9: file=%s, category=%s, confidence=%.2f, needs_review=%s",
                result["file"], classification.category,
                classification.confidence, needs_review)
    return result


if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser(description="UC-9: LLM-классификация документов")
    parser.add_argument("file", nargs="?", default=None, help="Путь к документу")
    parser.add_argument("--categories", nargs="*", default=None, help="Список категорий")
    parser.add_argument("--threshold", type=float, default=CONFIDENCE_THRESHOLD,
                        help="Порог уверенности")
    args = parser.parse_args()

    result = asyncio.run(main(
        file_path=args.file, categories=args.categories,
        confidence_threshold=args.threshold,
    ))

    print("\n" + "=" * 70)
    print("UC-9: КЛАССИФИКАЦИЯ ДОКУМЕНТА ЗАВЕРШЕНА")
    print("=" * 70)
    print(f"Статус: {result.get('status', 'unknown')}")
    print(f"Файл: {result.get('file', 'N/A')}")

    if result.get("status") == "success":
        cls = result["classification"]
        print(f"Категория: {cls['category']}")
        print(f"Уверенность: {cls['confidence']:.2f}")
        print(f"Обоснование: {cls['reasoning']}")
        if result.get("needs_manual_review"):
            print("⚠ ТРЕБУЕТСЯ РУЧНАЯ ПРОВЕРКА (низкая уверенность)")
        sys.exit(0)
    else:
        print(f"Ошибка: {result.get('message', 'Unknown')}")
        sys.exit(1)
