# -*- coding: utf-8 -*-
"""
Руководство к файлу UC_20_silence_probe.py
==========================================

Назначение:
    Диагностический utility для UC-20-safe / silence-aware ASR пайплайна.
    Скрипт не отправляет ничего в Cloud.ru и не делает транскрибацию.
    Он нужен для ручной проверки, по каким порогам тишины разумно резать аудио
    после приведения к тому же формату, который использует UC-20:
      1) Берёт исходный файл (audio/video)
      2) Вырезает первые N секунд
      3) Приводит фрагмент к Opus 16k mono
      4) Прогоняет ffmpeg silencedetect по одному или нескольким noise-порогам
      5) Сохраняет Markdown-отчёт с таймкодами silence_start / silence_end / duration

Use Case:
    Предварительная ручная калибровка порога тишины перед возможной реализацией
    silence-aware chunking и параллельной отправки ASR-чанков.
    Теперь особенно полезен для валидации новых дефолтных параметров ASR-сервиса:
      - threshold = -45 dB
      - минимальная тишина = 5 сек
      - минимальная длина полезного сегмента = 5 минут

Actor:
    Аналитик / Оператор

Цель:
    Получить понятную Markdown-разметку тишины на первых 60 сек подготовленного аудио,
    чтобы вручную оценить, какой silence threshold подходит для конкретного источника.

Использование:
    python -m AI.scripts.UC.UC_20_silence_probe --file AI/data/audio/HSE.mp4
    python -m AI.scripts.UC.UC_20_silence_probe --file AI/data/audio/HSE.mp4 --sample-seconds 180 --thresholds -45 --min-silence-seconds 5
    python -m AI.scripts.UC.UC_20_silence_probe --file AI/data/audio/HSE.mp4 --output AI/data/transcript/hse_silence_probe.md

Зависимости:
    - ffmpeg/ffprobe в PATH
    - Python standard library
"""

from __future__ import annotations

import argparse
import asyncio
import logging
import re
import shutil
import subprocess
import sys
import tempfile
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Dict, List, Optional

SCRIPT_DIR = Path(__file__).parent.absolute()
AI_DIR = SCRIPT_DIR.parent.parent
GLOBAL_SERVICES_DIR = AI_DIR.parent
DEFAULT_OUTPUT_PATH = AI_DIR / "data" / "transcript" / "uc20_silence_probe.md"
DEFAULT_THRESHOLDS = [-45]
DEFAULT_MIN_SILENCE_SECONDS = 5.0
DEFAULT_SAMPLE_SECONDS = 60
DEFAULT_TARGET_BITRATE_KBPS = 48

sys.path.insert(0, str(GLOBAL_SERVICES_DIR))

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s | %(levelname)-7s | %(name)s | %(message)s",
)
logger = logging.getLogger(__name__)

SILENCE_START_RE = re.compile(r"silence_start:\s*(?P<value>-?\d+(?:\.\d+)?)")
SILENCE_END_RE = re.compile(
    r"silence_end:\s*(?P<end>-?\d+(?:\.\d+)?)\s*\|\s*silence_duration:\s*(?P<duration>-?\d+(?:\.\d+)?)",
)


@dataclass
class SilenceInterval:
    start: float
    end: float
    duration: float


async def run_command(cmd: List[str], step: str, description: str) -> subprocess.CompletedProcess[str]:
    logger.info(
        "%s. %s — ОТПРАВЛЯЕМ: %s",
        step,
        description,
        " ".join(cmd),
    )
    process = await asyncio.to_thread(
        subprocess.run,
        cmd,
        capture_output=True,
        text=True,
        check=False,
    )
    if process.returncode != 0:
        stderr = (process.stderr or "").strip()
        logger.error(
            "%s. %s — ОШИБКА: rc=%d, stderr=%s",
            step,
            description,
            process.returncode,
            stderr[:1000],
        )
        raise RuntimeError(
            f"{description} failed: rc={process.returncode}, stderr={stderr[:1000]}"
        )
    logger.info("%s. %s — УСПЕХ", step, description)
    return process


async def ensure_ffmpeg_tools() -> Dict[str, str]:
    logger.info("ШАГ 1. Проверяем наличие ffmpeg/ffprobe — ОТПРАВЛЯЕМ")
    ffmpeg_bin = shutil.which("ffmpeg")
    ffprobe_bin = shutil.which("ffprobe")
    if not ffmpeg_bin:
        raise RuntimeError("ffmpeg не найден в PATH")
    if not ffprobe_bin:
        raise RuntimeError("ffprobe не найден в PATH")
    logger.info(
        "ШАГ 1. Инструменты найдены — УСПЕХ: ffmpeg=%s, ffprobe=%s",
        ffmpeg_bin,
        ffprobe_bin,
    )
    return {"ffmpeg": ffmpeg_bin, "ffprobe": ffprobe_bin}


async def probe_duration_seconds(file_path: str, ffprobe_bin: str) -> Optional[float]:
    process = await run_command(
        cmd=[
            ffprobe_bin,
            "-v",
            "error",
            "-show_entries",
            "format=duration",
            "-of",
            "default=noprint_wrappers=1:nokey=1",
            file_path,
        ],
        step="ШАГ 2",
        description="Проверяем длительность исходного файла",
    )
    raw_value = (process.stdout or "").strip()
    if not raw_value:
        return None
    try:
        return float(raw_value)
    except ValueError:
        logger.warning("ШАГ 2. Не удалось распарсить duration: %s", raw_value)
        return None


async def extract_sample_to_wav(
    input_path: str,
    output_path: str,
    ffmpeg_bin: str,
    sample_seconds: int,
) -> None:
    await run_command(
        cmd=[
            ffmpeg_bin,
            "-y",
            "-i",
            input_path,
            "-t",
            str(sample_seconds),
            "-vn",
            "-ac",
            "1",
            "-ar",
            "16000",
            "-c:a",
            "pcm_s16le",
            output_path,
        ],
        step="ШАГ 3",
        description=(
            "Вырезаем первые секунды и нормализуем в WAV 16k mono для точного silencedetect"
        ),
    )


async def compress_sample_to_ogg(
    input_path: str,
    output_path: str,
    ffmpeg_bin: str,
    target_bitrate_kbps: int,
) -> None:
    await run_command(
        cmd=[
            ffmpeg_bin,
            "-y",
            "-i",
            input_path,
            "-vn",
            "-ac",
            "1",
            "-ar",
            "16000",
            "-c:a",
            "libopus",
            "-b:a",
            f"{target_bitrate_kbps}k",
            "-vbr",
            "on",
            "-application",
            "voip",
            output_path,
        ],
        step="ШАГ 4",
        description="Готовим тот же Opus 16k mono формат, что и в UC-20",
    )


async def detect_silence(
    input_path: str,
    ffmpeg_bin: str,
    noise_db: int,
    min_silence_seconds: float,
) -> List[SilenceInterval]:
    process = await run_command(
        cmd=[
            ffmpeg_bin,
            "-hide_banner",
            "-i",
            input_path,
            "-af",
            f"silencedetect=noise={noise_db}dB:d={min_silence_seconds}",
            "-f",
            "null",
            "-",
        ],
        step=f"ШАГ 5 threshold={noise_db}dB",
        description="Выполняем детекцию тишины",
    )
    log_text = "\n".join(
        part for part in [process.stdout or "", process.stderr or ""] if part
    )
    return parse_silence_intervals(log_text)


def parse_silence_intervals(log_text: str) -> List[SilenceInterval]:
    intervals: List[SilenceInterval] = []
    current_start: Optional[float] = None
    for line in log_text.splitlines():
        start_match = SILENCE_START_RE.search(line)
        if start_match:
            current_start = float(start_match.group("value"))
            continue

        end_match = SILENCE_END_RE.search(line)
        if end_match:
            end_value = float(end_match.group("end"))
            duration_value = float(end_match.group("duration"))
            start_value = current_start if current_start is not None else max(0.0, end_value - duration_value)
            intervals.append(
                SilenceInterval(
                    start=start_value,
                    end=end_value,
                    duration=duration_value,
                )
            )
            current_start = None
    return intervals


def format_ts(seconds: float) -> str:
    total_ms = int(round(seconds * 1000))
    ms = total_ms % 1000
    total_seconds = total_ms // 1000
    secs = total_seconds % 60
    total_minutes = total_seconds // 60
    minutes = total_minutes % 60
    hours = total_minutes // 60
    return f"{hours:02d}:{minutes:02d}:{secs:02d}.{ms:03d}"


def build_markdown_report(
    source_file: Path,
    sample_seconds: int,
    min_silence_seconds: float,
    target_bitrate_kbps: int,
    source_duration_seconds: Optional[float],
    prepared_sample_size_bytes: int,
    thresholds_report: Dict[int, List[SilenceInterval]],
) -> str:
    lines: List[str] = []
    lines.append(f"# UC-20 Silence Probe — {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    lines.append("")
    lines.append("## Сводка")
    lines.append(f"- Исходный файл: `{source_file}`")
    lines.append(f"- Длительность исходника: `{source_duration_seconds:.2f}s`" if source_duration_seconds is not None else "- Длительность исходника: `unknown`")
    lines.append(f"- Проанализированный фрагмент: первые `{sample_seconds}` сек")
    lines.append(f"- Формат для анализа: `Opus 16k mono`, дополнительно подготовлен `WAV 16k mono` для silencedetect")
    lines.append(f"- Битрейт prepared-версии UC-20: `{target_bitrate_kbps} kbps`")
    lines.append(f"- Размер prepared sample: `{prepared_sample_size_bytes}` bytes")
    lines.append(f"- Минимальная длительность тишины: `{min_silence_seconds}` сек")
    lines.append("")
    lines.append("## Интерпретация")
    lines.append("- Чем ближе threshold к `0 dB`, тем агрессивнее детектор считает фрагменты тишиной.")
    lines.append("- Обычно для речи имеет смысл сравнивать несколько порогов и руками проверить, где меньше ложных срабатываний.")
    lines.append("- Этот отчёт нужен только для ручной калибровки перед возможным silence-aware chunking.")
    lines.append("")

    for threshold in sorted(thresholds_report.keys(), reverse=True):
        intervals = thresholds_report[threshold]
        lines.append(f"## Threshold {threshold} dB")
        lines.append(f"- Найдено интервалов: `{len(intervals)}`")
        if intervals:
            total_duration = sum(item.duration for item in intervals)
            lines.append(f"- Суммарная длительность тишины: `{total_duration:.3f}` сек")
        else:
            lines.append("- Суммарная длительность тишины: `0.000` сек")
        lines.append("")
        if not intervals:
            lines.append("Тишина не обнаружена.")
            lines.append("")
            continue

        lines.append("| # | start | end | duration_sec |")
        lines.append("|---|-------|-----|--------------|")
        for index, interval in enumerate(intervals, start=1):
            lines.append(
                f"| {index} | `{format_ts(interval.start)}` | `{format_ts(interval.end)}` | `{interval.duration:.3f}` |"
            )
        lines.append("")

    return "\n".join(lines).strip() + "\n"


async def main() -> None:
    parser = argparse.ArgumentParser(
        description="Диагностика silence threshold для UC-20-safe ASR пайплайна",
    )
    parser.add_argument("--file", required=True, help="Путь к исходному audio/video файлу")
    parser.add_argument(
        "--sample-seconds",
        type=int,
        default=DEFAULT_SAMPLE_SECONDS,
        help="Сколько первых секунд анализировать",
    )
    parser.add_argument(
        "--thresholds",
        nargs="+",
        type=int,
        default=DEFAULT_THRESHOLDS,
        help="Набор noise threshold в dB для ffmpeg silencedetect, например: -25 -30 -35 -40",
    )
    parser.add_argument(
        "--min-silence-seconds",
        type=float,
        default=DEFAULT_MIN_SILENCE_SECONDS,
        help="Минимальная длительность тишины для фиксации",
    )
    parser.add_argument(
        "--target-bitrate-kbps",
        type=int,
        default=DEFAULT_TARGET_BITRATE_KBPS,
        help="Битрейт Opus-подготовки как в UC-20",
    )
    parser.add_argument(
        "--output",
        default=str(DEFAULT_OUTPUT_PATH),
        help="Куда сохранить markdown-отчёт",
    )
    args = parser.parse_args()

    logger.info("=" * 80)
    logger.info("UC-20 SILENCE PROBE: PREPARED AUDIO THRESHOLD DIAGNOSTICS")
    logger.info("=" * 80)

    source_file = Path(args.file)
    if not source_file.exists() or not source_file.is_file():
        raise FileNotFoundError(f"Файл не найден: {source_file}")

    if args.sample_seconds <= 0:
        raise ValueError("--sample-seconds должен быть > 0")
    if args.min_silence_seconds <= 0:
        raise ValueError("--min-silence-seconds должен быть > 0")

    tools = await ensure_ffmpeg_tools()
    source_duration = await probe_duration_seconds(str(source_file), tools["ffprobe"])

    output_path = Path(args.output)
    output_path.parent.mkdir(parents=True, exist_ok=True)

    thresholds_report: Dict[int, List[SilenceInterval]] = {}

    with tempfile.TemporaryDirectory(prefix="uc20_silence_probe_") as tmp_dir:
        tmp_path = Path(tmp_dir)
        sample_wav = tmp_path / f"{source_file.stem}.sample.wav"
        sample_ogg = tmp_path / f"{source_file.stem}.sample.prepared.ogg"

        logger.info(
            "ШАГ 3. Старт подготовки sample: file=%s, sample_seconds=%d",
            source_file,
            args.sample_seconds,
        )
        await extract_sample_to_wav(
            input_path=str(source_file),
            output_path=str(sample_wav),
            ffmpeg_bin=tools["ffmpeg"],
            sample_seconds=args.sample_seconds,
        )
        await compress_sample_to_ogg(
            input_path=str(sample_wav),
            output_path=str(sample_ogg),
            ffmpeg_bin=tools["ffmpeg"],
            target_bitrate_kbps=args.target_bitrate_kbps,
        )

        prepared_size = sample_ogg.stat().st_size
        logger.info(
            "ШАГ 4. Prepared sample готов: path=%s, size=%d bytes",
            sample_ogg,
            prepared_size,
        )

        for threshold in args.thresholds:
            intervals = await detect_silence(
                input_path=str(sample_wav),
                ffmpeg_bin=tools["ffmpeg"],
                noise_db=threshold,
                min_silence_seconds=args.min_silence_seconds,
            )
            thresholds_report[threshold] = intervals
            logger.info(
                "ШАГ 5 threshold=%sdB. Детекция завершена: intervals=%d",
                threshold,
                len(intervals),
            )

        report = build_markdown_report(
            source_file=source_file,
            sample_seconds=args.sample_seconds,
            min_silence_seconds=args.min_silence_seconds,
            target_bitrate_kbps=args.target_bitrate_kbps,
            source_duration_seconds=source_duration,
            prepared_sample_size_bytes=prepared_size,
            thresholds_report=thresholds_report,
        )
        output_path.write_text(report, encoding="utf-8")

    logger.info("ШАГ 6. Markdown-отчёт сохранён — УСПЕХ: %s", output_path)
    print(report)


if __name__ == "__main__":
    asyncio.run(main())
