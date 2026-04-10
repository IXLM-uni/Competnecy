"""
Руководство к файлу:
- Назначение: асинхронно транскрибирует указанные аудиофайлы через Cloud.ru ASR (ASRClient из AI.llm_service) и сохраняет общий Markdown-отчёт в data/transcript.
- Использование: `python -m AI.scripts.transcribe_to_md` или `python AI/scripts/transcribe_to_md.py`. При желании можно передать пути к аудио через аргументы CLI `--files <path1> <path2 ...>`.
- Требования: переменная окружения CLOUDRU_API_KEY обязательна; опционально CLOUDRU_BASE_URL и ASR_MODEL. Папки data/audio и data/transcript должны существовать или будут созданы автоматически (transcript создаётся скриптом).
- Логирование: пошаговый формат уровня оркестратора (ШАГ 1/2/3...), каждая операция (CRUD/сервис) логируется до/после. При ошибках фиксируется сообщение и файл.
- Вывод: Markdown-файл `kg_audio_transcript.md` с датой запуска, списком файлов и текстом транскрипции по каждому аудио.
"""
import argparse
import asyncio
import logging
import os
import sys
from datetime import datetime
from pathlib import Path
from typing import List, Optional, Tuple

# --- Пути ---
SCRIPT_DIR = Path(__file__).parent.absolute()
AI_DIR = SCRIPT_DIR.parent
GLOBAL_SERVICES_DIR = AI_DIR.parent
DATA_DIR = AI_DIR / "data"
AUDIO_DIR = DATA_DIR / "audio"
TRANSCRIPT_DIR = DATA_DIR / "transcript"
DEFAULT_OUTPUT_FILE = TRANSCRIPT_DIR / "kg_audio_transcript.md"

sys.path.insert(0, str(GLOBAL_SERVICES_DIR))

from dotenv import load_dotenv  # noqa: E402
from AI.llm_service import (  # noqa: E402
    RequestContext,
    create_cloudru_asr_client_from_env,
)

logger = logging.getLogger("transcribe_to_md")
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
)


async def transcribe_single(file_path: Path, index: int, total: int) -> Tuple[Path, Optional[str]]:
    """
    ШАГ 2.1: транскрибирует один файл через ASRClient.
    Возвращает (путь, текст или None при ошибке).
    """
    logger.info(
        "ШАГ 2.%d/%d. Проверяем файл: %s", index, total, file_path.name,
    )

    if not file_path.exists():
        logger.error(
            "ШАГ 2.%d/%d. ОШИБКА: файл не найден: %s", index, total, file_path,
        )
        return file_path, None

    size = file_path.stat().st_size
    logger.info(
        "ШАГ 2.%d/%d. Файл найден, размер: %d байт — ОТПРАВЛЯЕМ в ASR",
        index,
        total,
        size,
    )

    ctx = RequestContext(
        request_id=f"transcribe-{index}",
        user_id="transcribe_user",
        mode="chat",
    )

    try:
        asr_client = create_cloudru_asr_client_from_env()
        transcript = await asr_client.transcribe_file(str(file_path), ctx)
        text = (transcript.text or "").strip()

        if not text:
            logger.warning(
                "ШАГ 2.%d/%d. Пустой транскрипт (Cloud.ru вернул пустую строку)",
                index,
                total,
            )
            return file_path, None

        logger.info(
            "ШАГ 2.%d/%d. УСПЕХ: %d символов", index, total, len(text),
        )
        return file_path, text

    except Exception as exc:  # noqa: BLE001
        logger.error(
            "ШАГ 2.%d/%d. ОШИБКА транскрибации %s: %s", index, total, file_path, exc,
        )
        return file_path, None


def build_markdown(results: List[Tuple[Path, Optional[str]]]) -> str:
    """ШАГ 3: собирает Markdown-документ по итогам транскрипции."""
    lines: List[str] = []
    timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    lines.append(f"# Транскрипция аудио (Cloud.ru ASR) — {timestamp}")
    lines.append("")

    lines.append("## Список файлов")
    for path, text in results:
        status = "успех" if text else "ошибка"
        size = path.stat().st_size if path.exists() else 0
        lines.append(f"- {path.name} — {status}, размер: {size} байт")
    lines.append("")

    for path, text in results:
        lines.append(f"## {path.name}")
        if text:
            lines.append(text)
        else:
            lines.append("*(не удалось получить транскрипт)*")
        lines.append("\n---\n")

    return "\n".join(lines)


async def main(files: Optional[List[str]] = None, output: Optional[str] = None) -> None:
    """
    Оркестратор: загрузка переменных, валидация путей, транскрибация и сохранение MD.
    Шаги логируются форматом ШАГ N.
    """
    logger.info("ШАГ 0. Начало работы транскрибации")

    # ШАГ 0.1. Загружаем .env
    env_path = GLOBAL_SERVICES_DIR / ".env"
    if env_path.exists():
        load_dotenv(env_path)
        logger.info("ШАГ 0.1. Загружен .env: %s", env_path)
    else:
        logger.warning("ШАГ 0.1. .env не найден: %s", env_path)

    # ШАГ 1. Подготовка путей
    TRANSCRIPT_DIR.mkdir(parents=True, exist_ok=True)
    logger.info("ШАГ 1. Папка для результатов: %s", TRANSCRIPT_DIR)

    target_files = [
        Path(p) for p in (files if files else [
            AUDIO_DIR / "KG_1.ogg",
            AUDIO_DIR / "KG_2.m4a",
        ])
    ]
    logger.info(
        "ШАГ 1. Будут обработаны файлы: %s",
        ", ".join([p.name for p in target_files]),
    )

    # ШАГ 2. Транскрибация
    results: List[Tuple[Path, Optional[str]]] = []
    for idx, path in enumerate(target_files, start=1):
        result = await transcribe_single(path, idx, len(target_files))
        results.append(result)

    # ШАГ 3. Сборка Markdown
    logger.info("ШАГ 3. Формируем Markdown отчёт")
    md_content = build_markdown(results)

    # ШАГ 4. Сохранение файла
    output_path = Path(output) if output else DEFAULT_OUTPUT_FILE
    output_path.write_text(md_content, encoding="utf-8")
    logger.info("ШАГ 4. Отчёт сохранён: %s", output_path)

    # ШАГ 5. Итог
    success_count = sum(1 for _, text in results if text)
    logger.info(
        "ШАГ 5. Готово: %d/%d транскрипций успешны. Выходной файл: %s",
        success_count,
        len(results),
        output_path,
    )


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Транскрибация аудио в Markdown")
    parser.add_argument(
        "--files",
        nargs="*",
        help="Список путей к аудио (по умолчанию KG_1.ogg и KG_2.m4a из data/audio)",
    )
    parser.add_argument(
        "--output",
        help="Путь к выходному .md (по умолчанию data/transcript/kg_audio_transcript.md)",
    )
    return parser.parse_args()


if __name__ == "__main__":
    args = parse_args()
    asyncio.run(main(files=args.files, output=args.output))
