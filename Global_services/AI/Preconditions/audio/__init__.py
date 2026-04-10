# -*- coding: utf-8 -*-
"""
Руководство к файлу __init__.py (Preconditions/audio)
=====================================================

Назначение:
    Пакет с утилитами генерации тестового аудио для UC-3 (ASR).
    Экспортирует ensure_test_audio_files() и пути к файлам.
"""

from AI.Preconditions.audio.generate_test_audio import (
    ensure_test_audio_files,
    get_test_silence_path,
    get_test_tone_path,
)

__all__ = [
    "ensure_test_audio_files",
    "get_test_tone_path",
    "get_test_silence_path",
]
