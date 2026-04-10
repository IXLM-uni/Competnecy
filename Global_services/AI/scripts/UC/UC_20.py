# -*- coding: utf-8 -*-
"""
Руководство к файлу UC_20.py
============================

Назначение:
    Реализация UC-20: Безопасная транскрибация крупных аудио (Cloud.ru ASR).
    Скрипт использует UC-20 fallback-пайплайн в ASRClient:
      1) Проверка формата/размера
      2) Сжатие в Opus/AAC без PCM-раздувания
      3) Нарезка на безопасные чанки < лимита
      4) Последовательная очередь отправки чанков с сохранением порядка
      5) Сборка итогового транскрипта и отчёта

Use Case:
    UC-20 из LLM_SERVICE.md

Actor:
    Аналитик / Оператор / Фоновый процесс

Цель:
    Получать стабильную транскрибацию больших аудиофайлов без 413 Payload Too Large.

Используемые функции из llm_service.py:
    - load_env_and_validate
    - create_cloudru_asr_client_from_env
    - ASRClient.transcribe_file
    - RequestContext

Использование:
    python -m AI.scripts.UC.UC_20 --files AI/data/audio/KG_1.ogg AI/data/audio/KG_2.m4a
    python -m AI.scripts.UC.UC_20 --audio-dir AI/data/audio --output AI/data/transcript/uc20_report.md

Зависимости:
    - llm_service.py
    - python-dotenv
    - ffmpeg/ffprobe в PATH (для fallback-пайплайна UC-20)
"""

from __future__ import annotations

import argparse
import asyncio
import json
import logging
import sys
import time
import uuid
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional

# ---------- Пути ----------
SCRIPT_DIR = Path(__file__).parent.absolute()
AI_DIR = SCRIPT_DIR.parent.parent
GLOBAL_SERVICES_DIR = AI_DIR.parent
DEFAULT_AUDIO_DIR = AI_DIR / "data" / "audio"
DEFAULT_OUTPUT_PATH = AI_DIR / "data" / "transcript" / "uc20_transcripts.md"

sys.path.insert(0, str(GLOBAL_SERVICES_DIR))

from AI.llm_service import (  # noqa: E402
    ASRClient,
    RequestContext,
    create_cloudru_asr_client_from_env,
    load_env_and_validate,
)


logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s | %(levelname)-7s | %(name)s | %(message)s",
)
logger = logging.getLogger(__name__)


@dataclass
class Uc20FileResult:
    file_path: str
    file_name: str
    status: str
    source_size_bytes: int
    transcript_text: Optional[str] = None
    transcript_length: int = 0
    processing_time_sec: float = 0.0
    error_message: Optional[str] = None


async def collect_target_files(
    files: Optional[List[str]],
    audio_dir: Optional[str],
) -> List[str]:
    """ШАГ 1. Сбор целевых файлов для UC-20."""
    if files:
        resolved = [str(Path(item)) for item in files]
        logger.info(
            "ШАГ 1. Используем список из --files: %d элементов",
            len(resolved),
        )
        return resolved

    scan_dir = Path(audio_dir) if audio_dir else DEFAULT_AUDIO_DIR
    logger.info("ШАГ 1. Сканируем директорию: %s", scan_dir)

    if not scan_dir.exists() or not scan_dir.is_dir():
        logger.error("ШАГ 1. ОШИБКА: директория не найдена: %s", scan_dir)
        return []

    supported = ASRClient.SUPPORTED_AUDIO_EXTENSIONS
    found: List[str] = []
    for entry in sorted(scan_dir.iterdir()):
        if entry.is_file() and entry.suffix.lower() in supported:
            found.append(str(entry))

    logger.info(
        "ШАГ 1. Найдено %d аудиофайлов с поддерживаемыми расширениями",
        len(found),
    )
    return found


async def validate_files(file_paths: List[str]) -> List[str]:
    """ШАГ 1.1. Базовая валидация файлов."""
    valid: List[str] = []
    for idx, file_path in enumerate(file_paths, start=1):
        path = Path(file_path)
        if not path.exists() or not path.is_file():
            logger.error(
                "ШАГ 1.1.%d. ОШИБКА: файл не найден: %s",
                idx,
                file_path,
            )
            continue

        ext = path.suffix.lower()
        size = path.stat().st_size
        logger.info(
            "ШАГ 1.1.%d. Файл валиден: %s | ext=%s | size=%d bytes",
            idx,
            path.name,
            ext or "(без расширения)",
            size,
        )
        valid.append(str(path))

    logger.info(
        "ШАГ 1.1. Результат валидации: valid=%d, invalid=%d",
        len(valid),
        len(file_paths) - len(valid),
    )
    return valid


async def transcribe_single_file(
    asr_client: ASRClient,
    file_path: str,
    file_index: int,
    total_files: int,
    semaphore: asyncio.Semaphore,
) -> Uc20FileResult:
    """ШАГ 2.x. Транскрибация одного файла с контролем очереди."""
    async with semaphore:
        path = Path(file_path)
        source_size = path.stat().st_size if path.exists() else 0

        logger.info(
            "ШАГ 2.%d/%d. Начинаем файл: %s (size=%d bytes) — ОТПРАВЛЯЕМ",
            file_index,
            total_files,
            path.name,
            source_size,
        )
        started_at = time.time()

        ctx = RequestContext(
            request_id=f"uc20-{file_index}-{uuid.uuid4().hex[:8]}",
            user_id="uc20_user",
            mode="chat",
            enable_asr=True,
            metadata={
                "uc": "UC-20",
                "file_index": file_index,
                "file_total": total_files,
                "file_name": path.name,
            },
        )

        try:
            transcript = await asr_client.transcribe_file(file_path, ctx)
            text = (transcript.text or "").strip()
            elapsed = time.time() - started_at

            if not text:
                logger.warning(
                    "ШАГ 2.%d/%d. Пустой транскрипт: %s (%.2fs)",
                    file_index,
                    total_files,
                    path.name,
                    elapsed,
                )
                return Uc20FileResult(
                    file_path=file_path,
                    file_name=path.name,
                    status="error",
                    source_size_bytes=source_size,
                    transcript_text=None,
                    transcript_length=0,
                    processing_time_sec=elapsed,
                    error_message="Пустой транскрипт",
                )

            logger.info(
                "ШАГ 2.%d/%d. УСПЕХ: %s, text_len=%d, duration=%.2f",
                file_index,
                total_files,
                path.name,
                len(text),
                float(transcript.duration or 0.0),
            )
            return Uc20FileResult(
                file_path=file_path,
                file_name=path.name,
                status="success",
                source_size_bytes=source_size,
                transcript_text=text,
                transcript_length=len(text),
                processing_time_sec=elapsed,
            )

        except Exception as exc:  # noqa: BLE001
            elapsed = time.time() - started_at
            logger.error(
                "ШАГ 2.%d/%d. ОШИБКА файла %s: %s (%.2fs)",
                file_index,
                total_files,
                path.name,
                exc,
                elapsed,
            )
            return Uc20FileResult(
                file_path=file_path,
                file_name=path.name,
                status="error",
                source_size_bytes=source_size,
                transcript_text=None,
                transcript_length=0,
                processing_time_sec=elapsed,
                error_message=str(exc),
            )


async def build_markdown_report(results: List[Uc20FileResult]) -> str:
    """ШАГ 3. Формирование Markdown-отчёта."""
    now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    lines: List[str] = [
        f"# UC-20: Транскрибация крупных аудио — {now}",
        "",
        "## Сводка",
    ]

    success_count = sum(1 for item in results if item.status == "success")
    error_count = sum(1 for item in results if item.status == "error")
    lines.append(f"- Всего файлов: {len(results)}")
    lines.append(f"- Успешно: {success_count}")
    lines.append(f"- Ошибки: {error_count}")
    lines.append("")

    lines.append("## Детали по файлам")
    for item in results:
        lines.append(
            f"- {item.file_name}: status={item.status}, "
            f"size={item.source_size_bytes} bytes, "
            f"text_len={item.transcript_length}, "
            f"time={item.processing_time_sec:.2f}s"
        )
        if item.error_message:
            lines.append(f"  - error: {item.error_message}")
    lines.append("")

    for item in results:
        lines.append(f"## {item.file_name}")
        if item.transcript_text:
            lines.append(item.transcript_text)
        else:
            lines.append("*(транскрипция не получена)*")
        lines.append("\n---\n")

    return "\n".join(lines)


async def main(
    files: Optional[List[str]] = None,
    audio_dir: Optional[str] = None,
    output: Optional[str] = None,
    concurrency: int = 1,
) -> Dict[str, Any]:
    """Оркестратор UC-20."""
    logger.info("=" * 80)
    logger.info("UC-20: Безопасная транскрибация крупных аудио (Cloud.ru ASR)")
    logger.info("=" * 80)

    # ШАГ 0. Конфигурация
    logger.info("ШАГ 0. Загрузка конфигурации UC-20 — ОТПРАВЛЯЕМ")
    try:
        cfg = load_env_and_validate(str(GLOBAL_SERVICES_DIR))
    except ValueError as exc:
        logger.error("ШАГ 0. ОШИБКА конфигурации: %s", exc)
        return {"status": "error", "uc": "UC-20", "message": str(exc)}

    logger.info("ШАГ 0. Конфигурация загружена — УСПЕХ")
    logger.info(
        "ШАГ 0. ASR params: model=%s, max_payload=%s, chunk_duration=%s, bitrate=%s",
        cfg.get("ASR_MODEL", ""),
        cfg.get("ASR_MAX_PAYLOAD_BYTES", ""),
        cfg.get("ASR_CHUNK_DURATION_SECONDS", ""),
        cfg.get("ASR_TARGET_BITRATE_KBPS", ""),
    )

    # ШАГ 1. Сбор и валидация файлов
    candidates = await collect_target_files(files, audio_dir)
    if not candidates:
        msg = "Нет файлов для обработки"
        logger.error("ШАГ 1. ОШИБКА: %s", msg)
        return {"status": "error", "uc": "UC-20", "message": msg}

    valid_files = await validate_files(candidates)
    if not valid_files:
        msg = "После валидации не осталось файлов"
        logger.error("ШАГ 1. ОШИБКА: %s", msg)
        return {"status": "error", "uc": "UC-20", "message": msg}

    # ШАГ 2. Транскрибация
    queue_size = max(1, int(concurrency))
    logger.info(
        "ШАГ 2. Запускаем очередь транскрибации: files=%d, concurrency=%d",
        len(valid_files),
        queue_size,
    )

    asr_client = create_cloudru_asr_client_from_env()
    semaphore = asyncio.Semaphore(queue_size)

    tasks = [
        transcribe_single_file(
            asr_client=asr_client,
            file_path=file_path,
            file_index=index,
            total_files=len(valid_files),
            semaphore=semaphore,
        )
        for index, file_path in enumerate(valid_files, start=1)
    ]

    started = time.time()
    results = list(await asyncio.gather(*tasks))
    elapsed_total = time.time() - started

    logger.info(
        "ШАГ 2. Очередь завершена: total=%d, elapsed=%.2fs",
        len(results),
        elapsed_total,
    )

    # ШАГ 3. Отчёт
    logger.info("ШАГ 3. Формируем Markdown отчёт — ОТПРАВЛЯЕМ")
    report_md = await build_markdown_report(results)

    output_path = Path(output) if output else DEFAULT_OUTPUT_PATH
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(report_md, encoding="utf-8")
    logger.info("ШАГ 3. Отчёт сохранён: %s — УСПЕХ", output_path)

    # ШАГ 4. Итог
    success_count = sum(1 for item in results if item.status == "success")
    error_count = sum(1 for item in results if item.status == "error")

    result: Dict[str, Any] = {
        "status": "success" if success_count > 0 else "error",
        "uc": "UC-20",
        "total_files": len(results),
        "success_count": success_count,
        "error_count": error_count,
        "elapsed_seconds": round(elapsed_total, 2),
        "output": str(output_path),
        "files": [
            {
                "file_name": item.file_name,
                "status": item.status,
                "source_size_bytes": item.source_size_bytes,
                "transcript_length": item.transcript_length,
                "processing_time_sec": round(item.processing_time_sec, 2),
                "error_message": item.error_message,
            }
            for item in results
        ],
    }

    logger.info(
        "ШАГ 4. UC-20 завершён: success=%d, error=%d, total=%d",
        success_count,
        error_count,
        len(results),
    )
    return result


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="UC-20: Безопасная транскрибация крупных аудио",
    )
    parser.add_argument(
        "--files",
        nargs="*",
        default=None,
        help="Список файлов для обработки",
    )
    parser.add_argument(
        "--audio-dir",
        default=None,
        help="Директория для сканирования (если --files не задан)",
    )
    parser.add_argument(
        "--output",
        default=None,
        help="Путь до markdown-отчёта",
    )
    parser.add_argument(
        "--concurrency",
        type=int,
        default=1,
        help="Параллелизм по файлам (рекомендуется 1)",
    )
    return parser.parse_args()


if __name__ == "__main__":
    args = parse_args()
    try:
        uc_result = asyncio.run(
            main(
                files=args.files,
                audio_dir=args.audio_dir,
                output=args.output,
                concurrency=args.concurrency,
            ),
        )
        print("\n" + "=" * 80)
        print("UC-20: SAFE ASR COMPLETED")
        print("=" * 80)
        print(json.dumps(uc_result, ensure_ascii=False, indent=2))
        sys.exit(0 if uc_result.get("status") == "success" else 1)
    except KeyboardInterrupt:
        print("\nПрервано пользователем")
        sys.exit(130)
    except Exception as exc:  # noqa: BLE001
        logger.exception("Критическая ошибка UC-20: %s", exc)
        sys.exit(1)
