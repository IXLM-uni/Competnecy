# -*- coding: utf-8 -*-
"""
Руководство к файлу generate_test_audio.py
==========================================

Назначение:
    Генерирует тестовые WAV-файлы для e2e-тестирования UC-3 (ASR).
    Создаёт два файла:
      - test_tone.wav   — синусоидальный тон 440 Гц, 2 секунды (позитивный кейс)
      - test_silence.wav — тишина 1 секунда (негативный кейс: пустой транскрипт)

    Не требует внешних зависимостей — использует только стандартную
    библиотеку Python (wave, struct, math).

Использование:
    python AI/Preconditions/audio/generate_test_audio.py

    Файлы создаются в той же директории: AI/Preconditions/audio/
"""

from __future__ import annotations

import logging
import math
import os
import struct
import wave

logger = logging.getLogger(__name__)

AUDIO_DIR = os.path.dirname(os.path.abspath(__file__))


async def generate_tone_wav(
    path: str,
    duration_sec: float = 2.0,
    frequency: float = 440.0,
    sample_rate: int = 16000,
    amplitude: float = 0.8,
) -> str:
    """Генерирует WAV с синусоидальным тоном.

    ШАГ 1. Вычисляем сэмплы синусоиды
    ШАГ 2. Записываем в WAV (PCM 16-bit mono)
    """
    logger.info(
        "ШАГ 1. Генерация тона: freq=%.1f Гц, duration=%.1f с, path=%s",
        frequency, duration_sec, path,
    )
    n_samples = int(sample_rate * duration_sec)
    samples = []
    for i in range(n_samples):
        t = i / sample_rate
        value = amplitude * math.sin(2.0 * math.pi * frequency * t)
        samples.append(int(value * 32767))

    logger.info("ШАГ 2. Запись WAV: samples=%d, sample_rate=%d", n_samples, sample_rate)
    with wave.open(path, "w") as wf:
        wf.setnchannels(1)
        wf.setsampwidth(2)  # 16-bit
        wf.setframerate(sample_rate)
        for s in samples:
            wf.writeframes(struct.pack("<h", s))

    logger.info("ШАГ 2. УСПЕХ: %s (%d bytes)", path, os.path.getsize(path))
    return path


async def generate_silence_wav(
    path: str,
    duration_sec: float = 1.0,
    sample_rate: int = 16000,
) -> str:
    """Генерирует WAV с тишиной (все сэмплы = 0).

    ШАГ 1. Генерируем нулевые сэмплы
    ШАГ 2. Записываем в WAV
    """
    logger.info(
        "ШАГ 1. Генерация тишины: duration=%.1f с, path=%s",
        duration_sec, path,
    )
    n_samples = int(sample_rate * duration_sec)

    logger.info("ШАГ 2. Запись WAV (тишина): samples=%d", n_samples)
    with wave.open(path, "w") as wf:
        wf.setnchannels(1)
        wf.setsampwidth(2)
        wf.setframerate(sample_rate)
        silent_data = struct.pack("<h", 0) * n_samples
        wf.writeframes(silent_data)

    logger.info("ШАГ 2. УСПЕХ: %s (%d bytes)", path, os.path.getsize(path))
    return path


def get_test_tone_path() -> str:
    """Путь к test_tone.wav."""
    return os.path.join(AUDIO_DIR, "test_tone.wav")


def get_test_silence_path() -> str:
    """Путь к test_silence.wav."""
    return os.path.join(AUDIO_DIR, "test_silence.wav")


async def ensure_test_audio_files() -> dict:
    """Создаёт оба тестовых аудио-файла, если их нет. Возвращает пути."""
    tone_path = get_test_tone_path()
    silence_path = get_test_silence_path()

    if not os.path.exists(tone_path):
        await generate_tone_wav(tone_path)
    if not os.path.exists(silence_path):
        await generate_silence_wav(silence_path)

    return {"tone": tone_path, "silence": silence_path}


# --- CLI-точка входа ---
if __name__ == "__main__":
    import asyncio

    logging.basicConfig(level=logging.INFO, format="%(levelname)s | %(message)s")
    paths = asyncio.run(ensure_test_audio_files())
    print(f"Тестовые аудио-файлы созданы:\n  tone:    {paths['tone']}\n  silence: {paths['silence']}")
