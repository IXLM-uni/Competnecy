# -*- coding: utf-8 -*-
"""
Руководство к файлу UC_11.py
============================

Назначение:
    Реализация UC-11: Пакетное распознавание аудиофайлов (ASR Batch Processing).
    1. Валидация файлов (формат, размер)
    2. Параллельная транскрипция с asyncio.Semaphore
    3. Сбор результатов и статистики
    4. Формирование детального отчёта

    Use Case: UC-11 из LLM_SERVICE.md
    Actor: Администратор / Фоновый процесс / API-клиент
    Цель: Массовая транскрипция аудиофайлов с контролем конкурентности.

Архитектура (6 шагов UC-11):
    ШАГ 1. Валидация и подготовка файлов
    ШАГ 2. Параллельная транскрипция с семафором — ASRClient.transcribe_file()
    ШАГ 3. Сбор результатов — asyncio.gather()
    ШАГ 4. Пост-обработка (опционально)
    ШАГ 5. Формирование отчёта
    ШАГ 6. Callback (опционально)

Используемые функции из llm_service.py:
    - load_env_and_validate, ASRClient, RequestContext

Использование:
    python -m AI.scripts.UC.UC_11 [путь_к_аудио_директории] [--concurrency 3]

Зависимости:
    - llm_service.py, python-dotenv, httpx
"""

from __future__ import annotations

import asyncio
import json
import logging
import sys
import time
import uuid
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, List, Optional

# ---------- Константы ----------
SCRIPT_DIR = Path(__file__).parent.absolute()
AI_DIR = SCRIPT_DIR.parent.parent
GLOBAL_SERVICES_DIR = AI_DIR.parent
AUDIO_DIR = AI_DIR / "Preconditions" / "audio"

SUPPORTED_AUDIO_EXTENSIONS = (".mp3", ".wav", ".ogg", ".m4a", ".webm")
MAX_FILE_SIZE_BYTES = 40 * 1024 * 1024  # 40 МБ
DEFAULT_CONCURRENCY = 3

sys.path.insert(0, str(GLOBAL_SERVICES_DIR))

from AI.llm_service import (
    ASRClient,
    RequestContext,
    load_env_and_validate,
)

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s | %(levelname)-7s | %(name)s | %(message)s",
)
logger = logging.getLogger(__name__)


# ---------- Локальные DTO ----------

@dataclass
class SingleTranscriptResult:
    """Результат транскрипции одного файла."""
    file_path: str
    file_name: str
    status: str  # "success" | "error" | "skipped"
    transcript_text: Optional[str] = None
    transcript_length: int = 0
    error_message: Optional[str] = None
    processing_time: float = 0.0


@dataclass
class BatchTranscriptResult:
    """Результат пакетной обработки."""
    batch_id: str = field(default_factory=lambda: str(uuid.uuid4()))
    total_files: int = 0
    success_count: int = 0
    error_count: int = 0
    skipped_count: int = 0
    total_processing_time: float = 0.0
    results: List[SingleTranscriptResult] = field(default_factory=list)


def scan_audio_directory(directory: str) -> List[str]:
    """Сканирование директории на аудиофайлы."""
    dir_path = Path(directory)
    if not dir_path.exists() or not dir_path.is_dir():
        return []
    files = []
    for entry in sorted(dir_path.iterdir()):
        if entry.is_file() and entry.suffix.lower() in SUPPORTED_AUDIO_EXTENSIONS:
            files.append(str(entry.absolute()))
    return files


async def transcribe_single(
    asr_client: ASRClient,
    file_path: str,
    semaphore: asyncio.Semaphore,
    file_index: int,
    total_files: int,
) -> SingleTranscriptResult:
    """Транскрипция одного файла с семафором."""
    file_name = Path(file_path).name

    async with semaphore:
        logger.info("ШАГ 2. Транскрипция файла %d/%d: %s — ОТПРАВЛЯЕМ",
                     file_index, total_files, file_name)
        start_time = time.time()

        ctx = RequestContext(
            request_id=f"uc11-asr-{file_index}",
            user_id="uc11_user",
            mode="chat",
        )

        try:
            transcript = await asr_client.transcribe_file(file_path, ctx)
            elapsed = time.time() - start_time

            text = transcript.text.strip()
            if not text:
                logger.warning("ШАГ 2. Файл %d/%d: %s — пустой транскрипт",
                               file_index, total_files, file_name)
                return SingleTranscriptResult(
                    file_path=file_path, file_name=file_name,
                    status="error", error_message="Пустой транскрипт",
                    processing_time=elapsed,
                )

            logger.info("ШАГ 2. Файл %d/%d: %s — УСПЕХ (len=%d, %.1f сек)",
                         file_index, total_files, file_name, len(text), elapsed)
            return SingleTranscriptResult(
                file_path=file_path, file_name=file_name,
                status="success", transcript_text=text,
                transcript_length=len(text), processing_time=elapsed,
            )

        except Exception as exc:
            elapsed = time.time() - start_time
            logger.error("ШАГ 2. Файл %d/%d: %s — ОШИБКА: %s (%.1f сек)",
                          file_index, total_files, file_name, exc, elapsed)
            return SingleTranscriptResult(
                file_path=file_path, file_name=file_name,
                status="error", error_message=str(exc),
                processing_time=elapsed,
            )


async def main(
    audio_dir: Optional[str] = None,
    audio_files: Optional[List[str]] = None,
    concurrency: int = DEFAULT_CONCURRENCY,
) -> Dict[str, Any]:
    """Основная функция UC-11: Пакетное распознавание аудиофайлов."""
    logger.info("=" * 70)
    logger.info("UC-11: Пакетное распознавание аудиофайлов (ASR Batch)")
    logger.info("Конкурентность: %d | Директория: %s", concurrency, audio_dir or AUDIO_DIR)
    logger.info("=" * 70)

    # ШАГ 0. Конфигурация
    try:
        cfg = load_env_and_validate(str(GLOBAL_SERVICES_DIR))
    except ValueError as exc:
        return {"status": "error", "message": str(exc)}

    # Получаем список файлов
    if audio_files:
        files = audio_files
    else:
        search_dir = audio_dir or str(AUDIO_DIR)
        files = scan_audio_directory(search_dir)

    if not files:
        logger.warning("Нет аудиофайлов для обработки")
        return {"status": "error", "message": "Нет аудиофайлов"}

    # ШАГ 1. Валидация и подготовка
    logger.info("ШАГ 1. Валидация %d файлов — ОТПРАВЛЯЕМ", len(files))
    valid_files: List[str] = []
    skipped: List[SingleTranscriptResult] = []

    for fp in files:
        p = Path(fp)
        if not p.exists():
            skipped.append(SingleTranscriptResult(
                file_path=fp, file_name=p.name,
                status="skipped", error_message="Файл не найден",
            ))
            continue

        ext = p.suffix.lower()
        if ext not in SUPPORTED_AUDIO_EXTENSIONS:
            skipped.append(SingleTranscriptResult(
                file_path=fp, file_name=p.name,
                status="skipped", error_message=f"Неподдерживаемый формат: {ext}",
            ))
            continue

        size = p.stat().st_size
        if size > MAX_FILE_SIZE_BYTES:
            skipped.append(SingleTranscriptResult(
                file_path=fp, file_name=p.name,
                status="skipped", error_message=f"Превышен лимит размера: {size / 1024 / 1024:.1f} МБ",
            ))
            continue

        valid_files.append(fp)
        logger.info("  ✓ %s (%d байт)", p.name, size)

    logger.info("ШАГ 1. Валидация — УСПЕХ: %d валидных, %d пропущено",
                len(valid_files), len(skipped))

    if not valid_files:
        return {"status": "error", "message": "Нет валидных файлов после проверки"}

    # ШАГ 2. Параллельная транскрипция с семафором
    logger.info("ШАГ 2. Параллельная транскрипция — ОТПРАВЛЯЕМ (concurrency=%d)", concurrency)

    asr_client = ASRClient(
        api_key=cfg["CLOUDRU_API_KEY"],
        base_url=cfg["CLOUDRU_BASE_URL"],
        model=cfg["ASR_MODEL"],
    )
    semaphore = asyncio.Semaphore(concurrency)

    tasks = [
        transcribe_single(asr_client, fp, semaphore, i + 1, len(valid_files))
        for i, fp in enumerate(valid_files)
    ]

    # ШАГ 3. Сбор результатов
    logger.info("ШАГ 3. Сбор результатов — ОЖИДАЕМ")
    start_total = time.time()
    results: List[SingleTranscriptResult] = await asyncio.gather(*tasks)
    total_time = time.time() - start_total

    # Объединяем с пропущенными
    all_results = list(skipped) + list(results)

    success_count = sum(1 for r in all_results if r.status == "success")
    error_count = sum(1 for r in all_results if r.status == "error")
    skipped_count = sum(1 for r in all_results if r.status == "skipped")

    logger.info("ШАГ 3. Собраны результаты транскрипции — УСПЕХ: "
                "success=%d, errors=%d, skipped=%d, total_time=%.1f сек",
                success_count, error_count, skipped_count, total_time)

    # ШАГ 4. Пост-обработка (пропускаем в демо)
    logger.info("ШАГ 4. Пост-обработка — ПРОПУЩЕНА (enable_post_processing=false)")

    # ШАГ 5. Формирование отчёта
    logger.info("ШАГ 5. Формирование отчёта — ОТПРАВЛЯЕМ")

    batch_result = BatchTranscriptResult(
        total_files=len(all_results),
        success_count=success_count,
        error_count=error_count,
        skipped_count=skipped_count,
        total_processing_time=total_time,
        results=all_results,
    )

    logger.info("ШАГ 5. Отчёт сформирован — УСПЕХ")

    # ШАГ 6. Callback (пропускаем в демо)
    logger.info("ШАГ 6. Callback — ПРОПУЩЕН (callback_url не указан)")

    report: Dict[str, Any] = {
        "status": "success",
        "uc": "UC-11",
        "batch_id": batch_result.batch_id,
        "total_files": batch_result.total_files,
        "success_count": batch_result.success_count,
        "error_count": batch_result.error_count,
        "skipped_count": batch_result.skipped_count,
        "total_processing_time": f"{batch_result.total_processing_time:.1f}s",
        "results": [
            {
                "file_name": r.file_name,
                "status": r.status,
                "transcript_length": r.transcript_length,
                "processing_time": f"{r.processing_time:.1f}s",
                "error_message": r.error_message,
                "transcript_preview": (r.transcript_text[:200] if r.transcript_text else None),
            }
            for r in all_results
        ],
    }

    logger.info("РЕЗУЛЬТАТ UC-11: batch_id=%s, total=%d, success=%d, errors=%d",
                batch_result.batch_id, batch_result.total_files,
                batch_result.success_count, batch_result.error_count)
    return report


if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser(description="UC-11: ASR Batch Processing")
    parser.add_argument("audio_dir", nargs="?", default=None, help="Директория с аудиофайлами")
    parser.add_argument("--concurrency", type=int, default=DEFAULT_CONCURRENCY,
                        help="Параллельность")
    args = parser.parse_args()

    try:
        result = asyncio.run(main(audio_dir=args.audio_dir, concurrency=args.concurrency))

        print("\n" + "=" * 70)
        print("UC-11: ПАКЕТНОЕ РАСПОЗНАВАНИЕ ЗАВЕРШЕНО")
        print("=" * 70)
        print(json.dumps(result, ensure_ascii=False, indent=2))

        sys.exit(0 if result.get("status") == "success" else 1)

    except KeyboardInterrupt:
        print("\nПрервано пользователем")
        sys.exit(130)
    except Exception as exc:
        logger.exception("Критическая ошибка в UC-11: %s", exc)
        sys.exit(1)
