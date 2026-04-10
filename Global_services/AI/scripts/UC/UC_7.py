# -*- coding: utf-8 -*-
"""
Руководство к файлу UC_7.py
===========================

Назначение:
    Реализация UC-7: Асинхронная обработка долгих задач с callback (AsyncTaskQueue).
    Демонстрирует паттерн «поставь задачу → получи task_id → получи результат через callback».

    Реализует локальную AsyncTaskQueue + WebhookClient, т.к. эти классы
    не реализованы в llm_service.py как сервисные компоненты.

    Use Case: UC-7 из LLM_SERVICE.md
    Actor: API-клиент / Внешняя система
    Цель: Выполнение тяжёлых операций без блокировки HTTP-запроса.

Архитектура (6 шагов UC-7):
    ШАГ 1. Приём асинхронного запроса — создание AsyncTask
    ШАГ 2. Постановка в очередь — asyncio.Queue
    ШАГ 3. Взятие в работу worker-ом
    ШАГ 4. Фоновая обработка — ChatOrchestrator.handle_user_input()
    ШАГ 5. Завершение и callback — WebhookClient (опционально)
    ШАГ 6. Обработка ошибок и retry

Используемые функции из llm_service.py:
    - load_env_and_validate, create_default_orchestrator_from_env
    - UserInput, RequestContext, OrchestratorResult

Использование:
    python -m AI.scripts.UC.UC_7 "Расскажи о квантовых компьютерах" [--workers 2] [--callback-url URL]

Зависимости:
    - llm_service.py, python-dotenv, httpx
"""

from __future__ import annotations

import asyncio
import hashlib
import hmac
import json
import logging
import sys
import time
import uuid
from dataclasses import dataclass, field
from enum import Enum
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


# ============================================================================
# Локальные DTO для AsyncTaskQueue (не реализованы в llm_service.py)
# ============================================================================

class TaskStatus(str, Enum):
    PENDING = "pending"
    PROCESSING = "processing"
    COMPLETED = "completed"
    FAILED = "failed"


@dataclass
class AsyncTask:
    """Модель асинхронной задачи."""
    task_id: str = field(default_factory=lambda: str(uuid.uuid4()))
    status: TaskStatus = TaskStatus.PENDING
    user_input: Optional[UserInput] = None
    callback_url: Optional[str] = None
    webhook_secret: Optional[str] = None
    max_retries: int = 3
    current_retry: int = 0
    result: Optional[Dict[str, Any]] = None
    error: Optional[str] = None
    created_at: float = field(default_factory=time.time)
    started_at: Optional[float] = None
    completed_at: Optional[float] = None
    progress_percent: int = 0


class WebhookClient:
    """Отправка callback с подписью HMAC-SHA256."""

    @staticmethod
    async def send(task: AsyncTask) -> bool:
        """Отправляет результат задачи на callback_url."""
        if not task.callback_url:
            logger.info("ШАГ WEBHOOK. callback_url не указан — пропускаем")
            return False

        import httpx

        payload = {
            "task_id": task.task_id,
            "status": task.status.value,
            "result": task.result,
            "error": task.error,
            "processing_time": (
                (task.completed_at - task.started_at)
                if task.completed_at and task.started_at else None
            ),
        }
        body = json.dumps(payload, ensure_ascii=False)

        headers: Dict[str, str] = {"Content-Type": "application/json"}
        if task.webhook_secret:
            signature = hmac.new(
                task.webhook_secret.encode(), body.encode(), hashlib.sha256,
            ).hexdigest()
            headers["X-Webhook-Signature"] = f"sha256={signature}"

        logger.info("ШАГ WEBHOOK. Отправляем callback для задачи %s → %s",
                     task.task_id, task.callback_url)

        try:
            async with httpx.AsyncClient(timeout=10.0) as client:
                resp = await client.post(task.callback_url, content=body, headers=headers)
                resp.raise_for_status()
            logger.info("ШАГ WEBHOOK. УСПЕХ: status=%d", resp.status_code)
            return True
        except Exception as exc:
            logger.error("ШАГ WEBHOOK. ОШИБКА: %s", exc)
            return False


class AsyncTaskQueue:
    """Очередь задач с worker pool (asyncio.Queue + N параллельных workers)."""

    def __init__(self, num_workers: int = 2) -> None:
        self._queue: asyncio.Queue[AsyncTask] = asyncio.Queue()
        self._num_workers = num_workers
        self._tasks: Dict[str, AsyncTask] = {}
        self._workers: List[asyncio.Task] = []
        self._orchestrator = None

    async def start(self) -> None:
        """Запуск worker pool."""
        logger.info("ШАГ QUEUE. Запуск AsyncTaskQueue: workers=%d", self._num_workers)
        self._orchestrator = create_default_orchestrator_from_env(
            collection_name=COLLECTION_NAME, enable_sparse=False,
        )
        for i in range(self._num_workers):
            worker = asyncio.create_task(self._worker(i))
            self._workers.append(worker)

    async def stop(self) -> None:
        """Остановка worker pool."""
        for w in self._workers:
            w.cancel()
        await asyncio.gather(*self._workers, return_exceptions=True)
        logger.info("ШАГ QUEUE. AsyncTaskQueue остановлена")

    async def enqueue(self, task: AsyncTask) -> str:
        """Постановка задачи в очередь."""
        self._tasks[task.task_id] = task
        await self._queue.put(task)
        logger.info("ШАГ 2. Задача %s поставлена в очередь — УСПЕХ (queue_size=%d)",
                     task.task_id, self._queue.qsize())
        return task.task_id

    def get_task(self, task_id: str) -> Optional[AsyncTask]:
        """Получение задачи по ID."""
        return self._tasks.get(task_id)

    async def _worker(self, worker_id: int) -> None:
        """Worker: берёт задачу из очереди и обрабатывает."""
        logger.info("ШАГ WORKER. Worker %d запущен", worker_id)
        while True:
            try:
                task = await self._queue.get()
                logger.info("ШАГ 3. Задача %s взята в работу worker %d — УСПЕХ",
                             task.task_id, worker_id)

                task.status = TaskStatus.PROCESSING
                task.started_at = time.time()

                try:
                    # ШАГ 4. Фоновая обработка
                    logger.info("ШАГ 4. Обработка задачи %s — В ПРОЦЕССЕ", task.task_id)
                    task.progress_percent = 10

                    ctx = RequestContext(
                        request_id=task.task_id,
                        mode=task.user_input.mode if task.user_input else "chat",
                    )

                    result = await self._orchestrator.handle_user_input(task.user_input, ctx)
                    task.progress_percent = 100

                    task.status = TaskStatus.COMPLETED
                    task.completed_at = time.time()
                    task.result = {
                        "response_text": result.response_text,
                        "sources_count": len(result.sources),
                        "tool_calls_count": len(result.tool_calls),
                    }
                    logger.info("ШАГ 4. Задача %s — ЗАВЕРШЕНА за %.1f сек",
                                 task.task_id, task.completed_at - task.started_at)

                    # ШАГ 5. Callback
                    await WebhookClient.send(task)

                except Exception as exc:
                    # ШАГ 6. Обработка ошибок и retry
                    task.current_retry += 1
                    task.error = str(exc)

                    if task.current_retry < task.max_retries:
                        logger.warning(
                            "ШАГ 6. Задача %s — ОШИБКА, retry %d/%d: %s",
                            task.task_id, task.current_retry, task.max_retries, exc,
                        )
                        task.status = TaskStatus.PENDING
                        # Exponential backoff
                        delay = 2 ** task.current_retry
                        await asyncio.sleep(delay)
                        await self._queue.put(task)
                    else:
                        logger.error(
                            "ШАГ 6. Задача %s — FAILED (исчерпаны попытки %d/%d): %s",
                            task.task_id, task.current_retry, task.max_retries, exc,
                        )
                        task.status = TaskStatus.FAILED
                        task.completed_at = time.time()
                        await WebhookClient.send(task)

                finally:
                    self._queue.task_done()

            except asyncio.CancelledError:
                break


async def main(
    text: str = "Расскажи о квантовых компьютерах",
    num_workers: int = 2,
    callback_url: Optional[str] = None,
    webhook_secret: Optional[str] = None,
    num_tasks: int = 2,
) -> Dict[str, Any]:
    """Основная функция UC-7: Демонстрация AsyncTaskQueue."""
    logger.info("=" * 70)
    logger.info("UC-7: Асинхронная обработка долгих задач с callback")
    logger.info("Workers: %d | Tasks: %d | Callback: %s",
                num_workers, num_tasks, callback_url or "(нет)")
    logger.info("=" * 70)

    # ШАГ 0. Конфигурация
    try:
        load_env_and_validate(str(GLOBAL_SERVICES_DIR))
    except ValueError as exc:
        return {"status": "error", "message": str(exc)}

    # Создаём очередь и запускаем worker'ов
    queue = AsyncTaskQueue(num_workers=num_workers)
    await queue.start()

    # ШАГ 1. Создание задач
    demo_queries = [
        text,
        "Какие основные парадигмы программирования существуют?",
        "Расскажи о истории интернета",
    ]

    task_ids: List[str] = []
    for i in range(min(num_tasks, len(demo_queries))):
        user_input = UserInput(text=demo_queries[i], mode="chat")
        task = AsyncTask(
            user_input=user_input,
            callback_url=callback_url,
            webhook_secret=webhook_secret,
            max_retries=2,
        )
        logger.info("ШАГ 1. Создана асинхронная задача %s — УСПЕХ (query='%.50s')",
                     task.task_id, demo_queries[i])
        await queue.enqueue(task)
        task_ids.append(task.task_id)

    # Ждём завершения всех задач
    logger.info("Ожидаем завершения всех задач...")
    await queue._queue.join()

    # Собираем результаты
    results: List[Dict[str, Any]] = []
    for tid in task_ids:
        task = queue.get_task(tid)
        if task:
            results.append({
                "task_id": task.task_id,
                "status": task.status.value,
                "processing_time": (
                    f"{task.completed_at - task.started_at:.1f}s"
                    if task.completed_at and task.started_at else "N/A"
                ),
                "result_preview": (
                    task.result.get("response_text", "")[:200]
                    if task.result else None
                ),
                "error": task.error,
            })

    await queue.stop()

    final: Dict[str, Any] = {
        "status": "success",
        "uc": "UC-7",
        "total_tasks": len(task_ids),
        "completed": sum(1 for r in results if r["status"] == "completed"),
        "failed": sum(1 for r in results if r["status"] == "failed"),
        "tasks": results,
    }

    logger.info("РЕЗУЛЬТАТ UC-7: total=%d, completed=%d, failed=%d",
                final["total_tasks"], final["completed"], final["failed"])
    return final


if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser(description="UC-7: AsyncTaskQueue")
    parser.add_argument("text", nargs="?", default="Расскажи о квантовых компьютерах")
    parser.add_argument("--workers", type=int, default=2, help="Количество workers")
    parser.add_argument("--tasks", type=int, default=2, help="Количество задач")
    parser.add_argument("--callback-url", default=None, help="URL для callback")
    parser.add_argument("--webhook-secret", default=None, help="Секрет для подписи")
    args = parser.parse_args()

    result = asyncio.run(main(
        text=args.text, num_workers=args.workers,
        callback_url=args.callback_url, webhook_secret=args.webhook_secret,
        num_tasks=args.tasks,
    ))

    print("\n" + "=" * 70)
    print("UC-7: АСИНХРОННАЯ ОБРАБОТКА ЗАВЕРШЕНА")
    print("=" * 70)
    print(json.dumps(result, ensure_ascii=False, indent=2))

    sys.exit(0 if result.get("status") == "success" else 1)
