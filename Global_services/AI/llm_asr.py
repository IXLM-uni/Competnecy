# -*- coding: utf-8 -*-
"""
Руководство к файлу llm_asr.py
==============================

Назначение:
    Вынесенный ASR-модуль из llm_service.py.
    Содержит модели транскрипции и UC-20-safe / silence-aware пайплайн:
      - TranscriptSegment
      - Transcript
      - ASRClient

    Начиная с текущей версии, fallback-пайплайн ASR по умолчанию умеет:
      - подготавливать аудио в Opus 16k mono
      - искать длинные окна тишины через ffmpeg silencedetect
      - резать запись по тишине с минимальным окном сегмента
      - добивать oversized-сегменты адаптивной временной нарезкой
      - отправлять чанки в ограниченной параллельной очереди
      - собирать итоговый результат в исходном порядке

Контракт совместимости:
    Публичные имена и сигнатуры полностью совместимы с llm_service.py,
    чтобы use-cases продолжали работать без изменений импортов.

Архитектурное правило:
    Это leaf-модуль без жёсткой зависимости от llm_service.py на этапе импорта.
    RequestContext подтягивается локально только там, где требуется конструирование
    дочернего контекста (избежание циклического импорта).
"""

from __future__ import annotations

import asyncio
import dataclasses
import logging
import os
import re
import shutil
import subprocess
import tempfile
from pathlib import Path
from typing import TYPE_CHECKING, List, Optional

import httpx
from pydantic import BaseModel, Field

if TYPE_CHECKING:
    from AI.llm_service import RequestContext

logger = logging.getLogger(__name__)

SILENCE_START_RE = re.compile(r"silence_start:\s*(?P<value>-?\d+(?:\.\d+)?)")
SILENCE_END_RE = re.compile(
    r"silence_end:\s*(?P<end>-?\d+(?:\.\d+)?)\s*\|\s*silence_duration:\s*(?P<duration>-?\d+(?:\.\d+)?)",
)


class TranscriptSegment(BaseModel):
    start: float
    end: float
    text: str
    speaker: Optional[str] = None


class Transcript(BaseModel):
    segments: List[TranscriptSegment] = Field(default_factory=list)
    text: str
    language: Optional[str] = None
    duration: Optional[float] = None


@dataclasses.dataclass(slots=True)
class SilenceInterval:
    start: float
    end: float
    duration: float


@dataclasses.dataclass(slots=True)
class PreparedAudioChunk:
    index: int
    path: str
    start_offset_seconds: float
    expected_duration_seconds: Optional[float]


@dataclasses.dataclass(slots=True)
class PreparedChunkResult:
    index: int
    path: str
    start_offset_seconds: float
    expected_duration_seconds: Optional[float]
    transcript: Transcript


class ASRClient:
    """Cloud.ru ASR: POST /audio/transcriptions (multipart/form-data)."""

    MAX_DIRECT_UPLOAD_BYTES = 25 * 1024 * 1024
    DEFAULT_SAFE_UPLOAD_BYTES = 22 * 1024 * 1024
    DEFAULT_CHUNK_DURATION_SECONDS = 300
    MIN_CHUNK_DURATION_SECONDS = 30
    DEFAULT_SILENCE_CHUNKING_ENABLED = True
    DEFAULT_SILENCE_THRESHOLD_DB = -45
    DEFAULT_SILENCE_MIN_DURATION_SECONDS = 5.0
    DEFAULT_SILENCE_MIN_SEGMENT_DURATION_SECONDS = 300.0
    DEFAULT_MAX_PARALLEL_REQUESTS = 5

    SUPPORTED_AUDIO_EXTENSIONS = {
        ".mp3",
        ".wav",
        ".ogg",
        ".m4a",
        ".webm",
        ".opus",
        ".aac",
        ".flac",
        ".mpga",
        ".mpeg",
        ".mp4",
    }

    DIRECT_SEND_EXTENSIONS = {
        ".mp3",
        ".wav",
        ".ogg",
        ".m4a",
        ".webm",
        ".opus",
        ".aac",
        ".flac",
        ".mpga",
        ".mpeg",
        ".mp4",
    }

    def __init__(
        self,
        api_key: str,
        base_url: str = "https://foundation-models.api.cloud.ru/v1",
        model: str = "openai/whisper-large-v3",
        language: Optional[str] = "ru",
        timeout_seconds: float = 180.0,
        max_payload_bytes: int = DEFAULT_SAFE_UPLOAD_BYTES,
        chunk_duration_seconds: int = DEFAULT_CHUNK_DURATION_SECONDS,
        target_bitrate_kbps: int = 48,
        enable_silence_chunking: bool = DEFAULT_SILENCE_CHUNKING_ENABLED,
        silence_threshold_db: int = DEFAULT_SILENCE_THRESHOLD_DB,
        silence_min_duration_seconds: float = DEFAULT_SILENCE_MIN_DURATION_SECONDS,
        silence_min_segment_duration_seconds: float = DEFAULT_SILENCE_MIN_SEGMENT_DURATION_SECONDS,
        max_parallel_requests: int = DEFAULT_MAX_PARALLEL_REQUESTS,
    ) -> None:
        self._api_key = api_key
        self._base_url = base_url.rstrip("/")
        self._model = model
        self._language = language
        self._timeout_seconds = timeout_seconds
        self._max_payload_bytes = max(1 * 1024 * 1024, int(max_payload_bytes))
        self._chunk_duration_seconds = max(
            self.MIN_CHUNK_DURATION_SECONDS,
            int(chunk_duration_seconds),
        )
        self._target_bitrate_kbps = max(16, int(target_bitrate_kbps))
        self._enable_silence_chunking = bool(enable_silence_chunking)
        self._silence_threshold_db = int(silence_threshold_db)
        self._silence_min_duration_seconds = max(0.1, float(silence_min_duration_seconds))
        self._silence_min_segment_duration_seconds = max(
            30.0,
            float(silence_min_segment_duration_seconds),
        )
        self._max_parallel_requests = max(1, min(5, int(max_parallel_requests)))

    async def transcribe(
        self, audio_bytes: bytes, filename: str, ctx: "RequestContext",
    ) -> Transcript:
        payload_size = len(audio_bytes)
        if payload_size > self._max_payload_bytes:
            msg = (
                f"Payload size exceeds safe limit before request: "
                f"{payload_size} > {self._max_payload_bytes}"
            )
            logger.error(
                "ШАГ ASR 0. ОШИБКА валидации payload: request_id=%s, file=%s, %s",
                ctx.request_id,
                filename,
                msg,
            )
            raise ValueError(msg)

        logger.info(
            "ШАГ ASR 1. Отправляем аудио в Cloud.ru — ОЖИДАЕМ 200: "
            "request_id=%s, size=%d bytes",
            ctx.request_id, payload_size,
        )
        url = f"{self._base_url}/audio/transcriptions"
        headers = {"Authorization": f"Bearer {self._api_key}"}

        async with httpx.AsyncClient(timeout=self._timeout_seconds) as client:
            files_payload = {"file": (filename, audio_bytes)}
            data_payload = {"model": self._model}
            if self._language:
                data_payload["language"] = self._language

            try:
                response = await client.post(
                    url, headers=headers, files=files_payload, data=data_payload,
                )
                response.raise_for_status()
                result = response.json()

                text = result.get("text", "")
                if not text.strip():
                    logger.warning(
                        "ШАГ ASR 1. Транскрипт пустой — аудио не распознано: "
                        "request_id=%s", ctx.request_id,
                    )
                    return Transcript(text="", segments=[])

                segments = [
                    TranscriptSegment(
                        start=seg.get("start", 0),
                        end=seg.get("end", 0),
                        text=seg.get("text", ""),
                    )
                    for seg in result.get("segments", [])
                ]

                logger.info(
                    "ШАГ ASR 1. УСПЕХ: request_id=%s, text_len=%d",
                    ctx.request_id, len(text),
                )
                return Transcript(
                    text=text, segments=segments,
                    language=result.get("language"),
                    duration=result.get("duration"),
                )

            except httpx.ReadTimeout as exc:
                logger.error(
                    "ШАГ ASR 1. ОШИБКА: ReadTimeout после %.1f сек: request_id=%s, file=%s",
                    self._timeout_seconds,
                    ctx.request_id,
                    filename,
                )
                raise RuntimeError(
                    f"ASR timeout after {self._timeout_seconds:.1f}s for file {filename}",
                ) from exc
            except httpx.HTTPStatusError as exc:
                logger.error(
                    "ШАГ ASR 1. ОШИБКА: Cloud.ru вернул %d: request_id=%s, file=%s, body=%s",
                    exc.response.status_code,
                    ctx.request_id,
                    filename,
                    exc.response.text[:500],
                )
                raise
            except Exception as exc:
                logger.error(
                    "ШАГ ASR 1. ОШИБКА: request_id=%s, file=%s, error=%s",
                    ctx.request_id,
                    filename,
                    exc,
                )
                raise

    async def transcribe_file(self, file_path: str, ctx: "RequestContext") -> Transcript:
        if not os.path.exists(file_path):
            msg = f"Файл не найден: {file_path}"
            logger.error("ШАГ ASR UC20 1. ОШИБКА: %s", msg)
            raise FileNotFoundError(msg)

        file_size = os.path.getsize(file_path)
        file_ext = Path(file_path).suffix.lower()
        logger.info(
            "ШАГ ASR UC20 1. Получили файл: path=%s, ext=%s, size=%d bytes, safe_limit=%d bytes",
            file_path,
            file_ext or "(без расширения)",
            file_size,
            self._max_payload_bytes,
        )

        direct_reasons: List[str] = []
        if file_ext not in self.DIRECT_SEND_EXTENSIONS:
            direct_reasons.append(
                "формат требует нормализации перед отправкой",
            )
        if file_size > self._max_payload_bytes:
            direct_reasons.append(
                "размер выше безопасного лимита",
            )

        if not direct_reasons:
            logger.info(
                "ШАГ ASR UC20 2. Прямая отправка допустима: ext=%s, size=%d <= %d",
                file_ext,
                file_size,
                self._max_payload_bytes,
            )

            logger.warning(
                "ШАГ ASR UC20 3. Отправляем исходный файл без подготовки: %s",
                file_path,
            )

            try:
                transcript = await self._transcribe_path(
                    file_path=file_path,
                    ctx=ctx,
                    step_label="ШАГ ASR UC20 3",
                )
                if transcript.text.strip():
                    logger.info(
                        "ШАГ ASR UC20 3. УСПЕХ на исходном файле: text_len=%d",
                        len(transcript.text),
                    )
                    return transcript

                logger.warning(
                    "ШАГ ASR UC20 3. Исходный файл дал пустой транскрипт — "
                    "переходим к fallback-пайплайну UC-20",
                )

            except httpx.HTTPStatusError as exc:
                if exc.response.status_code == 413:
                    logger.warning(
                        "ШАГ ASR UC20 3. Получили 413 на исходном файле — "
                        "переходим к fallback-пайплайну UC-20",
                    )
                else:
                    raise
        else:
            logger.info(
                "ШАГ ASR UC20 2. Прямую отправку пропускаем: %s",
                "; ".join(direct_reasons),
            )

        logger.info(
            "ШАГ ASR UC20 4. Запускаем fallback-пайплайн (сжатие/нарезка/очередь)",
        )
        return await self._transcribe_with_preprocess(file_path, ctx)

    async def _transcribe_path(
        self,
        file_path: str,
        ctx: "RequestContext",
        step_label: str,
    ) -> Transcript:
        file_size = os.path.getsize(file_path)
        if file_size > self._max_payload_bytes:
            msg = (
                f"Файл {file_path} превышает safe-порог: "
                f"{file_size} > {self._max_payload_bytes}"
            )
            logger.error(
                "%s. ОШИБКА: %s", step_label, msg
            )
            raise ValueError(msg)

        with open(file_path, "rb") as file_handle:
            audio_bytes = file_handle.read()

        logger.info(
            "%s. Подготовили payload: file=%s, size=%d bytes",
            step_label,
            os.path.basename(file_path),
            len(audio_bytes),
        )
        return await self.transcribe(audio_bytes, os.path.basename(file_path), ctx)

    async def _transcribe_with_preprocess(
        self,
        file_path: str,
        ctx: "RequestContext",
    ) -> Transcript:
        ffmpeg_bin = shutil.which("ffmpeg")
        ffprobe_bin = shutil.which("ffprobe")
        if not ffmpeg_bin:
            logger.error(
                "ШАГ ASR UC20 5. Fallback невозможен: ffmpeg не найден в PATH",
            )
            return Transcript(text="", segments=[])

        with tempfile.TemporaryDirectory(prefix="asr_uc20_") as tmp_dir:
            logger.info(
                "ШАГ ASR UC20 5. Создана рабочая директория fallback: %s",
                tmp_dir,
            )

            chunk_paths = await self._prepare_chunks_for_transcription(
                file_path=file_path,
                work_dir=tmp_dir,
                ffmpeg_bin=ffmpeg_bin,
                ffprobe_bin=ffprobe_bin,
            )

            if not chunk_paths:
                logger.error(
                    "ШАГ ASR UC20 7. Подготовка не вернула чанков — прерываем файл",
                )
                return Transcript(text="", segments=[])

            logger.info(
                "ШАГ ASR UC20 7. Подготовлено %d чанков для очереди запросов",
                len(chunk_paths),
            )
            logger.info(
                "ШАГ ASR UC20 8. Старт ограниченной параллельной очереди отправки чанков: concurrency=%d",
                self._max_parallel_requests,
            )

            merged_text_parts: List[str] = []
            merged_segments: List[TranscriptSegment] = []
            detected_language: Optional[str] = None
            total_chunks = len(chunk_paths)
            chunk_results = await self._transcribe_prepared_chunks(
                chunks=chunk_paths,
                ctx=ctx,
            )

            final_duration = 0.0
            for chunk in chunk_results:
                idx = chunk.index
                chunk_text = (chunk.transcript.text or "").strip()
                if chunk_text:
                    merged_text_parts.append(chunk_text)
                else:
                    logger.warning(
                        "ШАГ ASR UC20 10.%d/%d. Пустой транскрипт чанка: %s",
                        idx,
                        total_chunks,
                        os.path.basename(chunk.path),
                    )

                if chunk.transcript.language and not detected_language:
                    detected_language = chunk.transcript.language

                if chunk.transcript.segments:
                    for seg in chunk.transcript.segments:
                        merged_segments.append(
                            TranscriptSegment(
                                start=float(seg.start) + chunk.start_offset_seconds,
                                end=float(seg.end) + chunk.start_offset_seconds,
                                text=seg.text,
                                speaker=seg.speaker,
                            )
                        )

                chunk_duration = float(
                    chunk.transcript.duration
                    or chunk.expected_duration_seconds
                    or 0.0
                )
                final_duration = max(
                    final_duration,
                    chunk.start_offset_seconds + max(chunk_duration, 0.0),
                )

                logger.info(
                    "ШАГ ASR UC20 10.%d/%d. Чанк завершён: text_len=%d, duration=%.2f, offset_start=%.2f",
                    idx,
                    total_chunks,
                    len(chunk_text),
                    chunk_duration,
                    chunk.start_offset_seconds,
                )

            final_text = "\n\n".join(merged_text_parts).strip()
            if final_text:
                logger.info(
                    "ШАГ ASR UC20 11. Сборка итогового транскрипта — УСПЕХ: chunks=%d, text_len=%d",
                    total_chunks,
                    len(final_text),
                )
            else:
                logger.warning(
                    "ШАГ ASR UC20 11. Итоговый транскрипт пустой: chunks=%d",
                    total_chunks,
                )

            return Transcript(
                text=final_text,
                segments=merged_segments,
                language=detected_language or self._language,
                duration=final_duration if final_duration > 0 else None,
            )

    async def _prepare_chunks_for_transcription(
        self,
        file_path: str,
        work_dir: str,
        ffmpeg_bin: str,
        ffprobe_bin: Optional[str],
    ) -> List[PreparedAudioChunk]:
        source_size = os.path.getsize(file_path)
        source_ext = Path(file_path).suffix.lower()
        source_duration = await self._probe_duration_seconds(file_path, ffprobe_bin)
        logger.info(
            "ШАГ ASR UC20 6. Анализ источника: ext=%s, size=%d bytes, duration=%s",
            source_ext or "(без расширения)",
            source_size,
            f"{source_duration:.2f}s" if source_duration is not None else "unknown",
        )

        needs_conversion = source_ext not in self.DIRECT_SEND_EXTENSIONS
        needs_chunking = source_size > self._max_payload_bytes
        if not needs_conversion and not needs_chunking:
            logger.info(
                "ШАГ ASR UC20 6. Файл формально проходит лимит/формат, "
                "но fallback уже активирован (пустой ответ/413) — выполняем "
                "нормализацию через сжатие для устойчивости",
            )

        prepared_path = os.path.join(
            work_dir,
            f"{Path(file_path).stem}.prepared.ogg",
        )
        await self._compress_audio_for_asr(file_path, prepared_path, ffmpeg_bin)

        prepared_size = os.path.getsize(prepared_path)
        prepared_duration = await self._probe_duration_seconds(prepared_path, ffprobe_bin)
        logger.info(
            "ШАГ ASR UC20 6. Сжатие завершено: file=%s, size=%d bytes, duration=%s",
            prepared_path,
            prepared_size,
            f"{prepared_duration:.2f}s" if prepared_duration is not None else "unknown",
        )

        if self._enable_silence_chunking:
            logger.info(
                "ШАГ ASR UC20 6.3. Silence-aware режим включён: threshold=%sdB, silence_min=%.2fs, segment_min=%.2fs",
                self._silence_threshold_db,
                self._silence_min_duration_seconds,
                self._silence_min_segment_duration_seconds,
            )
            silence_chunks = await self._build_silence_aware_chunks(
                input_path=prepared_path,
                work_dir=work_dir,
                ffmpeg_bin=ffmpeg_bin,
                ffprobe_bin=ffprobe_bin,
                prepared_duration=prepared_duration,
            )
            if silence_chunks:
                return await self._ensure_chunk_payload_limits(
                    chunks=silence_chunks,
                    work_dir=work_dir,
                    ffmpeg_bin=ffmpeg_bin,
                    ffprobe_bin=ffprobe_bin,
                )

            logger.warning(
                "ШАГ ASR UC20 6.3. Silence-aware режим не дал разбиения, используем обычный fallback",
            )

        if prepared_size <= self._max_payload_bytes:
            logger.info(
                "ШАГ ASR UC20 6. Сжатый файл проходит лимит (%d <= %d), отправим 1 запросом",
                prepared_size,
                self._max_payload_bytes,
            )
            return [
                PreparedAudioChunk(
                    index=1,
                    path=prepared_path,
                    start_offset_seconds=0.0,
                    expected_duration_seconds=prepared_duration,
                )
            ]

        logger.warning(
            "ШАГ ASR UC20 6. Сжатый файл всё ещё слишком большой (%d > %d), включаем нарезку",
            prepared_size,
            self._max_payload_bytes,
        )
        plain_chunks = await self._split_audio_into_chunks(
            input_path=prepared_path,
            work_dir=work_dir,
            ffmpeg_bin=ffmpeg_bin,
        )
        normalized_plain_chunks: List[PreparedAudioChunk] = []
        running_offset = 0.0
        for idx, chunk_path in enumerate(plain_chunks, start=1):
            chunk_duration = await self._probe_duration_seconds(chunk_path, ffprobe_bin)
            normalized_plain_chunks.append(
                PreparedAudioChunk(
                    index=idx,
                    path=chunk_path,
                    start_offset_seconds=running_offset,
                    expected_duration_seconds=chunk_duration,
                )
            )
            running_offset += float(chunk_duration or 0.0)
        return normalized_plain_chunks

    async def _transcribe_prepared_chunks(
        self,
        chunks: List[PreparedAudioChunk],
        ctx: "RequestContext",
    ) -> List[PreparedChunkResult]:
        semaphore = asyncio.Semaphore(self._max_parallel_requests)
        total_chunks = len(chunks)

        async def _transcribe_single(chunk: PreparedAudioChunk) -> PreparedChunkResult:
            chunk_size = os.path.getsize(chunk.path)
            if chunk_size > self._max_payload_bytes:
                msg = (
                    f"Чанк превышает лимит после подготовки: {chunk_size} > "
                    f"{self._max_payload_bytes}, chunk={chunk.path}"
                )
                logger.error(
                    "ШАГ ASR UC20 8.%d/%d. ОШИБКА: %s",
                    chunk.index,
                    total_chunks,
                    msg,
                )
                raise RuntimeError(msg)

            chunk_ctx = self._build_chunk_context(ctx, chunk.index, total_chunks, chunk.path)
            logger.info(
                "ШАГ ASR UC20 8.%d/%d. Чанк поставлен в очередь: chunk=%s, size=%d bytes, offset_start=%.2f",
                chunk.index,
                total_chunks,
                os.path.basename(chunk.path),
                chunk_size,
                chunk.start_offset_seconds,
            )

            async with semaphore:
                logger.info(
                    "ШАГ ASR UC20 8.%d/%d. Чанк получил слот очереди: chunk=%s, concurrency_limit=%d — ОТПРАВЛЯЕМ",
                    chunk.index,
                    total_chunks,
                    os.path.basename(chunk.path),
                    self._max_parallel_requests,
                )
                try:
                    chunk_transcript = await self._transcribe_path(
                        file_path=chunk.path,
                        ctx=chunk_ctx,
                        step_label=f"ШАГ ASR UC20 9.{chunk.index}/{total_chunks}",
                    )
                except httpx.HTTPStatusError as exc:
                    if exc.response.status_code == 413:
                        logger.error(
                            "ШАГ ASR UC20 9.%d/%d. Cloud.ru вернул 413 даже после подготовки. "
                            "Рекомендуется уменьшить ASR_MAX_PAYLOAD_BYTES/ASR_CHUNK_DURATION_SECONDS",
                            chunk.index,
                            total_chunks,
                        )
                    raise

            return PreparedChunkResult(
                index=chunk.index,
                path=chunk.path,
                start_offset_seconds=chunk.start_offset_seconds,
                expected_duration_seconds=chunk.expected_duration_seconds,
                transcript=chunk_transcript,
            )

        results = await asyncio.gather(*[_transcribe_single(chunk) for chunk in chunks])
        return sorted(results, key=lambda item: item.index)

    async def _compress_audio_for_asr(
        self,
        input_path: str,
        output_path: str,
        ffmpeg_bin: str,
    ) -> None:
        cmd = [
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
            f"{self._target_bitrate_kbps}k",
            "-vbr",
            "on",
            "-application",
            "voip",
            output_path,
        ]
        await self._run_command(
            cmd=cmd,
            step="ШАГ ASR UC20 6.1",
            description="Сжимаем аудио в Opus 16k mono",
        )

    async def _split_audio_into_chunks(
        self,
        input_path: str,
        work_dir: str,
        ffmpeg_bin: str,
    ) -> List[str]:
        current_chunk_duration = self._chunk_duration_seconds
        max_attempts = 6

        for attempt in range(1, max_attempts + 1):
            chunk_pattern = os.path.join(work_dir, "chunk_%04d.ogg")
            for old_chunk in Path(work_dir).glob("chunk_*.ogg"):
                try:
                    old_chunk.unlink()
                except Exception as exc:  # noqa: BLE001
                    logger.warning(
                        "ШАГ ASR UC20 6.2. Не удалось удалить старый чанк %s: %s",
                        old_chunk,
                        exc,
                    )

            cmd = [
                ffmpeg_bin,
                "-y",
                "-i",
                input_path,
                "-f",
                "segment",
                "-segment_time",
                str(current_chunk_duration),
                "-reset_timestamps",
                "1",
                "-c",
                "copy",
                chunk_pattern,
            ]
            await self._run_command(
                cmd=cmd,
                step="ШАГ ASR UC20 6.2",
                description=(
                    "Нарезаем сжатое аудио на чанки "
                    f"(attempt={attempt}, chunk_duration={current_chunk_duration}s)"
                ),
            )

            chunk_paths = [
                str(path)
                for path in sorted(Path(work_dir).glob("chunk_*.ogg"))
            ]
            if not chunk_paths:
                msg = "ffmpeg не создал чанки при нарезке"
                logger.error("ШАГ ASR UC20 6.2. ОШИБКА: %s", msg)
                raise RuntimeError(msg)

            chunk_sizes = [os.path.getsize(chunk_path) for chunk_path in chunk_paths]
            max_chunk_size = max(chunk_sizes)
            logger.info(
                "ШАГ ASR UC20 6.2. Получено чанков=%d, max_chunk_size=%d bytes, limit=%d",
                len(chunk_paths),
                max_chunk_size,
                self._max_payload_bytes,
            )

            if max_chunk_size <= self._max_payload_bytes:
                logger.info(
                    "ШАГ ASR UC20 6.2. Нарезка УСПЕХ: все чанки проходят лимит",
                )
                return chunk_paths

            logger.warning(
                "ШАГ ASR UC20 6.2. Есть oversized-чанк (%d > %d), уменьшаем длительность сегмента",
                max_chunk_size,
                self._max_payload_bytes,
            )
            if current_chunk_duration <= self.MIN_CHUNK_DURATION_SECONDS:
                break

            ratio = self._max_payload_bytes / max_chunk_size
            next_duration = int(
                max(
                    self.MIN_CHUNK_DURATION_SECONDS,
                    current_chunk_duration * ratio * 0.9,
                )
            )
            if next_duration >= current_chunk_duration:
                next_duration = max(
                    self.MIN_CHUNK_DURATION_SECONDS,
                    current_chunk_duration - 30,
                )
            if next_duration == current_chunk_duration:
                break

            logger.warning(
                "ШАГ ASR UC20 6.2. Корректируем chunk_duration: %d -> %d",
                current_chunk_duration,
                next_duration,
            )
            current_chunk_duration = next_duration

        msg = (
            "Не удалось подобрать безопасный размер чанков. "
            "Уменьшите ASR_TARGET_BITRATE_KBPS или ASR_CHUNK_DURATION_SECONDS"
        )
        logger.error("ШАГ ASR UC20 6.2. ОШИБКА: %s", msg)
        raise RuntimeError(msg)

    async def _build_silence_aware_chunks(
        self,
        input_path: str,
        work_dir: str,
        ffmpeg_bin: str,
        ffprobe_bin: Optional[str],
        prepared_duration: Optional[float],
    ) -> List[PreparedAudioChunk]:
        if prepared_duration is None or prepared_duration <= 0:
            logger.warning(
                "ШАГ ASR UC20 6.3. Неизвестна длительность prepared-файла, silence-aware разбиение пропускаем",
            )
            return []

        silence_intervals = await self._detect_silence_intervals(
            input_path=input_path,
            ffmpeg_bin=ffmpeg_bin,
            noise_db=self._silence_threshold_db,
            min_silence_seconds=self._silence_min_duration_seconds,
        )
        if not silence_intervals:
            logger.info(
                "ШАГ ASR UC20 6.3. Тишина не найдена, silence-aware разбиение не требуется",
            )
            return []

        logger.info(
            "ШАГ ASR UC20 6.3. Найдено окон тишины=%d, строим сегменты",
            len(silence_intervals),
        )
        boundaries = self._build_segment_boundaries_from_silence(
            silence_intervals=silence_intervals,
            total_duration_seconds=prepared_duration,
        )
        if len(boundaries) <= 1:
            logger.info(
                "ШАГ ASR UC20 6.3. После агрегации границ разбиения не появилось",
            )
            return []

        prepared_chunks: List[PreparedAudioChunk] = []
        for idx, (segment_start, segment_end) in enumerate(zip(boundaries, boundaries[1:]), start=1):
            segment_duration = max(0.0, segment_end - segment_start)
            segment_path = os.path.join(work_dir, f"silence_chunk_{idx:04d}.ogg")
            logger.info(
                "ШАГ ASR UC20 6.3.%d. Формируем silence-сегмент: start=%.2f, end=%.2f, duration=%.2f",
                idx,
                segment_start,
                segment_end,
                segment_duration,
            )
            await self._extract_audio_slice(
                input_path=input_path,
                output_path=segment_path,
                ffmpeg_bin=ffmpeg_bin,
                start_seconds=segment_start,
                end_seconds=segment_end,
                step=f"ШАГ ASR UC20 6.3.{idx}",
                description="Вырезаем silence-aware сегмент",
            )
            real_duration = await self._probe_duration_seconds(segment_path, ffprobe_bin)
            prepared_chunks.append(
                PreparedAudioChunk(
                    index=idx,
                    path=segment_path,
                    start_offset_seconds=segment_start,
                    expected_duration_seconds=real_duration or segment_duration,
                )
            )

        logger.info(
            "ШАГ ASR UC20 6.3. Silence-aware сегментация завершена: segments=%d",
            len(prepared_chunks),
        )
        return prepared_chunks

    async def _detect_silence_intervals(
        self,
        input_path: str,
        ffmpeg_bin: str,
        noise_db: int,
        min_silence_seconds: float,
    ) -> List[SilenceInterval]:
        logger.info(
            "ШАГ ASR UC20 6.3.S. Старт silencedetect: file=%s, threshold=%sdB, min_silence=%.2fs",
            input_path,
            noise_db,
            min_silence_seconds,
        )
        process = await asyncio.to_thread(
            subprocess.run,
            [
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
            capture_output=True,
            text=True,
            check=False,
        )
        if process.returncode != 0:
            stderr = (process.stderr or "").strip()
            logger.error(
                "ШАГ ASR UC20 6.3.S. ОШИБКА silencedetect: rc=%d, stderr=%s",
                process.returncode,
                stderr[:1000],
            )
            raise RuntimeError(
                f"silencedetect failed: rc={process.returncode}, stderr={stderr[:1000]}"
            )

        silence_intervals = self._parse_silence_intervals(
            "\n".join(part for part in [process.stdout or "", process.stderr or ""] if part)
        )
        logger.info(
            "ШАГ ASR UC20 6.3.S. Silencedetect завершён: intervals=%d",
            len(silence_intervals),
        )
        return silence_intervals

    def _parse_silence_intervals(self, log_text: str) -> List[SilenceInterval]:
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
                start_value = (
                    current_start
                    if current_start is not None
                    else max(0.0, end_value - duration_value)
                )
                intervals.append(
                    SilenceInterval(
                        start=start_value,
                        end=end_value,
                        duration=duration_value,
                    )
                )
                current_start = None
        return intervals

    def _build_segment_boundaries_from_silence(
        self,
        silence_intervals: List[SilenceInterval],
        total_duration_seconds: float,
    ) -> List[float]:
        boundaries: List[float] = [0.0]
        current_segment_start = 0.0
        for interval in silence_intervals:
            candidate_boundary = max(interval.end, interval.start)
            candidate_duration = candidate_boundary - current_segment_start
            logger.info(
                "ШАГ ASR UC20 6.3.B. Анализ окна тишины: silence_start=%.2f, silence_end=%.2f, current_segment_duration=%.2f",
                interval.start,
                interval.end,
                candidate_duration,
            )
            if candidate_duration >= self._silence_min_segment_duration_seconds:
                boundaries.append(candidate_boundary)
                current_segment_start = candidate_boundary
                logger.info(
                    "ШАГ ASR UC20 6.3.B. Добавляем границу сегмента: boundary=%.2f",
                    candidate_boundary,
                )

        tail_duration = total_duration_seconds - current_segment_start
        if tail_duration < self._silence_min_segment_duration_seconds and len(boundaries) > 1:
            removed_boundary = boundaries.pop()
            logger.warning(
                "ШАГ ASR UC20 6.3.B. Хвост слишком короткий (%.2f < %.2f), удаляем последнюю границу %.2f и объединяем хвост",
                tail_duration,
                self._silence_min_segment_duration_seconds,
                removed_boundary,
            )

        boundaries.append(total_duration_seconds)
        logger.info(
            "ШАГ ASR UC20 6.3.B. Итоговые границы сегментов: %s",
            ", ".join(f"{value:.2f}" for value in boundaries),
        )
        return boundaries

    async def _extract_audio_slice(
        self,
        input_path: str,
        output_path: str,
        ffmpeg_bin: str,
        start_seconds: float,
        end_seconds: float,
        step: str,
        description: str,
    ) -> None:
        duration_seconds = max(0.1, end_seconds - start_seconds)
        await self._run_command(
            cmd=[
                ffmpeg_bin,
                "-y",
                "-ss",
                f"{start_seconds:.3f}",
                "-i",
                input_path,
                "-t",
                f"{duration_seconds:.3f}",
                "-c",
                "copy",
                output_path,
            ],
            step=step,
            description=(
                f"{description} (start={start_seconds:.3f}s, duration={duration_seconds:.3f}s)"
            ),
        )

    async def _ensure_chunk_payload_limits(
        self,
        chunks: List[PreparedAudioChunk],
        work_dir: str,
        ffmpeg_bin: str,
        ffprobe_bin: Optional[str],
    ) -> List[PreparedAudioChunk]:
        normalized_chunks: List[PreparedAudioChunk] = []
        next_index = 1
        for chunk in chunks:
            chunk_size = os.path.getsize(chunk.path)
            if chunk_size <= self._max_payload_bytes:
                normalized_chunks.append(
                    PreparedAudioChunk(
                        index=next_index,
                        path=chunk.path,
                        start_offset_seconds=chunk.start_offset_seconds,
                        expected_duration_seconds=chunk.expected_duration_seconds,
                    )
                )
                logger.info(
                    "ШАГ ASR UC20 6.4.%d. Silence-сегмент проходит лимит: size=%d <= %d",
                    next_index,
                    chunk_size,
                    self._max_payload_bytes,
                )
                next_index += 1
                continue

            logger.warning(
                "ШАГ ASR UC20 6.4.%d. Silence-сегмент oversized: size=%d > %d, включаем временную нарезку",
                next_index,
                chunk_size,
                self._max_payload_bytes,
            )
            segment_work_dir = os.path.join(work_dir, f"oversized_{next_index:04d}")
            os.makedirs(segment_work_dir, exist_ok=True)
            split_paths = await self._split_audio_into_chunks(
                input_path=chunk.path,
                work_dir=segment_work_dir,
                ffmpeg_bin=ffmpeg_bin,
            )
            running_offset = chunk.start_offset_seconds
            for split_path in split_paths:
                split_duration = await self._probe_duration_seconds(split_path, ffprobe_bin)
                normalized_chunks.append(
                    PreparedAudioChunk(
                        index=next_index,
                        path=split_path,
                        start_offset_seconds=running_offset,
                        expected_duration_seconds=split_duration,
                    )
                )
                logger.info(
                    "ШАГ ASR UC20 6.4.%d. Добавлен дочерний чанк oversized-сегмента: file=%s, offset_start=%.2f, duration=%s",
                    next_index,
                    os.path.basename(split_path),
                    running_offset,
                    f"{split_duration:.2f}s" if split_duration is not None else "unknown",
                )
                running_offset += float(split_duration or 0.0)
                next_index += 1

        logger.info(
            "ШАГ ASR UC20 6.4. Нормализация лимитов завершена: total_chunks=%d",
            len(normalized_chunks),
        )
        return normalized_chunks

    async def _probe_duration_seconds(
        self,
        file_path: str,
        ffprobe_bin: Optional[str],
    ) -> Optional[float]:
        if not ffprobe_bin:
            logger.warning(
                "ШАГ ASR UC20 PROBE. ffprobe не найден, длительность не будет определена",
            )
            return None

        cmd = [
            ffprobe_bin,
            "-v",
            "error",
            "-show_entries",
            "format=duration",
            "-of",
            "default=noprint_wrappers=1:nokey=1",
            file_path,
        ]
        process = await asyncio.to_thread(
            subprocess.run,
            cmd,
            capture_output=True,
            text=True,
            check=False,
        )
        if process.returncode != 0:
            logger.warning(
                "ШАГ ASR UC20 PROBE. Не удалось получить duration: file=%s, stderr=%s",
                file_path,
                (process.stderr or "")[:500],
            )
            return None

        raw_value = (process.stdout or "").strip()
        if not raw_value:
            return None
        try:
            return float(raw_value)
        except ValueError:
            logger.warning(
                "ШАГ ASR UC20 PROBE. Некорректный duration '%s' для file=%s",
                raw_value,
                file_path,
            )
            return None

    async def _run_command(
        self,
        cmd: List[str],
        step: str,
        description: str,
    ) -> None:
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
                stderr[:500],
            )
            raise RuntimeError(
                f"{description} failed: rc={process.returncode}, stderr={stderr[:500]}",
            )
        logger.info("%s. %s — УСПЕХ", step, description)

    def _build_chunk_context(
        self,
        ctx: "RequestContext",
        chunk_index: int,
        chunk_total: int,
        chunk_path: str,
    ) -> "RequestContext":
        from AI.llm_service import RequestContext  # локально: защита от циклического импорта

        metadata = dict(ctx.metadata or {})
        metadata.update({
            "asr_parent_request_id": ctx.request_id,
            "asr_chunk_index": chunk_index,
            "asr_chunk_total": chunk_total,
            "asr_chunk_file": os.path.basename(chunk_path),
        })

        child_data = ctx.model_dump()
        child_data["request_id"] = f"{ctx.request_id}-chunk-{chunk_index}"
        child_data["metadata"] = metadata
        return RequestContext(**child_data)
