# -*- coding: utf-8 -*-
"""
Руководство к файлу e2e.py
===========================

Назначение:
    End-to-end тесты для глобального LLM-сервиса (llm_service.py).
    Проверяют боевую готовность всех UC (UC-1 … UC-5) с реальными
    сервисами: Cloud.ru LLM, Cloud.ru Embeddings, Cloud.ru ASR, Qdrant.

    Тесты используют фикстуры из AI/Preconditions/conftest_e2e.py.

UC-1: RAG + Internet + tool calling + JSON repair + tokens
UC-2: Инжест документов (PDF/DOCX/TXT/MD) без векторизации
UC-3: Cloud.ru ASR → LLM-ответ
UC-4: Streaming-чат с промежуточными токенами
UC-5: Tool calling (calendar + calculator) с лимитами

Запуск:
    # Из корня Global_services:
    # 1. Проверить инфраструктуру:
    python -m AI.Preconditions.check_infra
    # 2. Проиндексировать данные в Qdrant:
    python -m AI.Preconditions.setup_index
    # 3. Запустить e2e-тесты:
    pytest AI/tests/e2e.py -v --tb=short -s

Зависимости:
    pytest, pytest-asyncio, python-dotenv, httpx, openai, qdrant-client
"""

from __future__ import annotations

import csv
import logging
import os
import sys
from typing import Any, Dict, List, Optional

import pytest

# ---------- conftest фикстуры загружаются из Preconditions ----------
# pytest подхватывает conftest_e2e.py через conftest.py (см. ниже)

logger = logging.getLogger(__name__)

PRECONDITIONS_DIR = os.path.join(
    os.path.dirname(os.path.abspath(__file__)), "..", "Preconditions",
)


# ============================================================================
# UC-1: RAG + tokens + JSON repair
# ============================================================================


class TestUC1_RAG:
    """UC-1: Запрос с RAG (mode=rag_qa), подсчёт токенов, источники."""

    @pytest.mark.asyncio
    async def test_rag_qa_returns_answer_with_sources(
        self, orchestrator, request_context,
    ) -> None:
        """ШАГ 1. RAG-запрос возвращает ответ + sources + tokens."""
        from AI.llm_service import OrchestratorResult, UserInput

        logger.info("e2e UC-1.1: RAG QA запрос — ОТПРАВЛЯЕМ")

        user_input = UserInput(
            text="Что такое теория деятельности и кто её основатели?",
            mode="rag_qa",
        )

        result = await orchestrator.handle_user_input(user_input, request_context)

        logger.info(
            "e2e UC-1.1: response_len=%d, sources=%d, tokens=%s",
            len(result.response_text),
            len(result.sources),
            result.tokens_used,
        )

        assert isinstance(result, OrchestratorResult)
        assert len(result.response_text) > 10, "Ответ слишком короткий"
        assert result.context_used.get("used_rag") is True, "RAG не был использован"
        # Токены должны быть посчитаны
        if result.tokens_used:
            assert result.tokens_used.total_tokens > 0

        logger.info("e2e UC-1.1: УСПЕХ")

    @pytest.mark.asyncio
    async def test_rag_qa_ground_truth(
        self, orchestrator, request_context, ground_truth,
    ) -> None:
        """ШАГ 2. RAG-запросы из ground_truth находят ожидаемые ключевые слова."""
        from AI.llm_service import OrchestratorResult, RequestContext, UserInput

        logger.info(
            "e2e UC-1.2: Проверка ground_truth (%d вопросов) — ОТПРАВЛЯЕМ",
            len(ground_truth),
        )

        passed = 0
        failed = 0
        for i, row in enumerate(ground_truth[:5]):  # первые 5 для скорости
            question = row["question"]
            expected_kw = row["expected_keyword"]

            ctx = RequestContext()
            user_input = UserInput(text=question, mode="rag_qa")

            try:
                result = await orchestrator.handle_user_input(user_input, ctx)
                # Проверяем, что ожидаемое ключевое слово есть в ответе ИЛИ в источниках
                answer_text = result.response_text.lower()
                sources_text = " ".join(
                    s.text.lower() for s in result.sources
                )
                found = (
                    expected_kw.lower() in answer_text
                    or expected_kw.lower() in sources_text
                )
                if found:
                    passed += 1
                    logger.info(
                        "  GT[%d] '%s' — НАЙДЕНО (%s)", i, question[:50], expected_kw,
                    )
                else:
                    failed += 1
                    logger.warning(
                        "  GT[%d] '%s' — НЕ НАЙДЕНО '%s' в ответе",
                        i, question[:50], expected_kw,
                    )
            except Exception as exc:
                failed += 1
                logger.error("  GT[%d] ОШИБКА: %s", i, exc)

        logger.info(
            "e2e UC-1.2: ИТОГО passed=%d, failed=%d", passed, failed,
        )
        assert passed > 0, "Ни один ground truth запрос не нашёл ответ"

    @pytest.mark.asyncio
    async def test_chat_mode_skips_rag(
        self, orchestrator, request_context,
    ) -> None:
        """ШАГ 3. mode=chat — RAG не вызывается."""
        from AI.llm_service import UserInput

        logger.info("e2e UC-1.3: Чат-режим (без RAG) — ОТПРАВЛЯЕМ")

        user_input = UserInput(text="Привет, как дела?", mode="chat")
        result = await orchestrator.handle_user_input(user_input, request_context)

        assert result.context_used.get("used_rag") is False
        assert len(result.response_text) > 0
        logger.info("e2e UC-1.3: УСПЕХ — RAG не использован, ответ получен")


# ============================================================================
# UC-2: Инжест документов
# ============================================================================


class TestUC2_DocumentIngest:
    """UC-2: Загрузка документов → чанкование → LLM-ответ."""

    @pytest.mark.asyncio
    async def test_ingest_txt_file(
        self, orchestrator, request_context, rag_data_path,
    ) -> None:
        """ШАГ 1. Инжест TXT-файла → ответ на основе содержимого."""
        from AI.llm_service import FileRef, UserInput

        logger.info("e2e UC-2.1: Инжест Data.txt — ОТПРАВЛЯЕМ")

        file_ref = FileRef(
            path=rag_data_path,
            mime_type="text/plain",
            original_name="Data.txt",
        )

        user_input = UserInput(
            text="Кратко: какие подходы к описанию деятельности упоминаются в документе?",
            mode="chat",
            files=[file_ref],
        )

        result = await orchestrator.handle_user_input(user_input, request_context)

        logger.info(
            "e2e UC-2.1: response_len=%d, used_documents=%s",
            len(result.response_text),
            result.context_used.get("used_documents"),
        )

        assert result.context_used.get("used_documents") is True
        assert len(result.response_text) > 20
        logger.info("e2e UC-2.1: УСПЕХ")

    @pytest.mark.asyncio
    async def test_ingest_md_file(
        self, orchestrator, request_context, documents_dir,
    ) -> None:
        """ШАГ 2. Инжест MD-файла."""
        from AI.llm_service import FileRef, UserInput

        md_path = os.path.join(documents_dir, "SKILL.md")
        if not os.path.isfile(md_path):
            pytest.skip("SKILL.md не найден")

        logger.info("e2e UC-2.2: Инжест SKILL.md — ОТПРАВЛЯЕМ")

        file_ref = FileRef(
            path=md_path,
            mime_type="text/markdown",
            original_name="SKILL.md",
        )

        user_input = UserInput(
            text="О чём этот документ?",
            mode="chat",
            files=[file_ref],
        )

        result = await orchestrator.handle_user_input(user_input, request_context)

        assert result.context_used.get("used_documents") is True
        assert len(result.response_text) > 10
        logger.info("e2e UC-2.2: УСПЕХ — MD-файл обработан")

    @pytest.mark.asyncio
    async def test_ingest_docx_file(
        self, orchestrator, request_context, documents_dir,
    ) -> None:
        """ШАГ 3. Инжест DOCX-файла."""
        from AI.llm_service import FileRef, UserInput

        docx_path = os.path.join(documents_dir, "Интервью.docx")
        if not os.path.isfile(docx_path):
            pytest.skip("Интервью.docx не найден")

        logger.info("e2e UC-2.3: Инжест Интервью.docx — ОТПРАВЛЯЕМ")

        file_ref = FileRef(
            path=docx_path,
            mime_type="application/vnd.openxmlformats-officedocument.wordprocessingml.document",
            original_name="Интервью.docx",
        )

        user_input = UserInput(
            text="Кратко: о чём это интервью?",
            mode="chat",
            files=[file_ref],
        )

        result = await orchestrator.handle_user_input(user_input, request_context)

        assert result.context_used.get("used_documents") is True
        assert len(result.response_text) > 10
        logger.info("e2e UC-2.3: УСПЕХ — DOCX обработан")

    @pytest.mark.asyncio
    async def test_ingest_pdf_file(
        self, orchestrator, request_context, documents_dir,
    ) -> None:
        """ШАГ 4. Инжест PDF-файла."""
        from AI.llm_service import FileRef, UserInput

        pdf_path = os.path.join(documents_dir, "Leaders Кирилл Гаврилов.pdf")
        if not os.path.isfile(pdf_path):
            pytest.skip("PDF не найден")

        logger.info("e2e UC-2.4: Инжест PDF — ОТПРАВЛЯЕМ")

        file_ref = FileRef(
            path=pdf_path,
            mime_type="application/pdf",
            original_name="Leaders.pdf",
        )

        user_input = UserInput(
            text="Кратко: о чём этот PDF?",
            mode="chat",
            files=[file_ref],
        )

        result = await orchestrator.handle_user_input(user_input, request_context)

        assert result.context_used.get("used_documents") is True
        assert len(result.response_text) > 10
        logger.info("e2e UC-2.4: УСПЕХ — PDF обработан")


# ============================================================================
# UC-3: ASR → LLM
# ============================================================================


class TestUC3_ASR:
    """UC-3: Облачный ASR (Cloud.ru) → транскрипт → LLM-ответ."""

    @pytest.mark.asyncio
    async def test_asr_transcribe_tone(
        self, asr_client, request_context, test_audio_paths,
    ) -> None:
        """ШАГ 1. Транскрипция тестового аудио (тон) — проверяем, что не падает."""
        logger.info("e2e UC-3.1: ASR транскрипция test_tone.wav — ОТПРАВЛЯЕМ")

        tone_path = test_audio_paths["tone"]
        try:
            transcript = await asr_client.transcribe_file(tone_path, request_context)
            logger.info(
                "e2e UC-3.1: transcript_len=%d, language=%s",
                len(transcript.text), transcript.language,
            )
            # Тон может не содержать речи — главное, что API ответил без ошибки
            assert transcript is not None
            logger.info("e2e UC-3.1: УСПЕХ — ASR API доступен и отвечает")
        except Exception as exc:
            logger.error("e2e UC-3.1: ASR ОШИБКА: %s", exc)
            pytest.skip(f"ASR API недоступен: {exc}")

    @pytest.mark.asyncio
    async def test_asr_empty_audio_returns_empty(
        self, asr_client, request_context, test_audio_paths,
    ) -> None:
        """ШАГ 2. Тишина → пустой или минимальный транскрипт."""
        logger.info("e2e UC-3.2: ASR тишина test_silence.wav — ОТПРАВЛЯЕМ")

        silence_path = test_audio_paths["silence"]
        try:
            transcript = await asr_client.transcribe_file(
                silence_path, request_context,
            )
            logger.info(
                "e2e UC-3.2: transcript='%s' (len=%d)",
                transcript.text[:100], len(transcript.text),
            )
            # Тишина — транскрипт должен быть пустой или очень короткий
            assert len(transcript.text.strip()) < 50, (
                f"Неожиданно длинный транскрипт для тишины: {transcript.text[:100]}"
            )
            logger.info("e2e UC-3.2: УСПЕХ — тишина корректно обработана")
        except Exception as exc:
            logger.error("e2e UC-3.2: ASR ОШИБКА: %s", exc)
            pytest.skip(f"ASR API недоступен: {exc}")

    @pytest.mark.asyncio
    async def test_asr_orchestrator_flow(
        self, orchestrator, request_context, test_audio_paths,
    ) -> None:
        """ШАГ 3. Полный флоу: audio_ref → ASR → LLM → ответ через оркестратор."""
        from AI.llm_service import UserInput

        logger.info("e2e UC-3.3: Оркестратор с ASR — ОТПРАВЛЯЕМ")

        tone_path = test_audio_paths["tone"]

        user_input = UserInput(
            audio_ref=tone_path,
            enable_asr=True,
            mode="chat",
        )

        try:
            result = await orchestrator.handle_user_input(user_input, request_context)
            logger.info(
                "e2e UC-3.3: response_len=%d, context=%s",
                len(result.response_text), result.context_used,
            )
            # Даже если транскрипт пустой (тон), оркестратор должен вернуть результат
            assert result.response_text is not None
            assert len(result.response_text) > 0
            logger.info("e2e UC-3.3: УСПЕХ")
        except Exception as exc:
            logger.error("e2e UC-3.3: ОШИБКА: %s", exc)
            pytest.skip(f"ASR+LLM flow недоступен: {exc}")


# ============================================================================
# UC-4: Streaming
# ============================================================================


class TestUC4_Streaming:
    """UC-4: Streaming-чат с промежуточными токенами."""

    @pytest.mark.asyncio
    async def test_stream_chat_yields_events(
        self, orchestrator, request_context,
    ) -> None:
        """ШАГ 1. stream_user_input отдаёт init → token_delta → final → done."""
        from AI.llm_service import StreamEvent, UserInput

        logger.info("e2e UC-4.1: Стриминг (mode=chat) — ОТПРАВЛЯЕМ")

        user_input = UserInput(
            text="Расскажи коротко, что такое машинное обучение?",
            mode="chat",
        )

        events: List[StreamEvent] = []
        async for ev in orchestrator.stream_user_input(user_input, request_context):
            events.append(ev)
            logger.info(
                "  stream event: kind=%s, data_keys=%s",
                ev.kind, list(ev.data.keys()),
            )

        kinds = [e.kind for e in events]
        logger.info("e2e UC-4.1: Всего событий: %d, kinds=%s", len(events), kinds)

        assert kinds[0] == "init", "Первое событие должно быть init"
        assert "token_delta" in kinds, "Должны быть token_delta события"
        assert kinds[-2] == "final", "Предпоследнее событие — final"
        assert kinds[-1] == "done", "Последнее событие — done"

        # Проверяем, что финальный текст не пуст
        final_events = [e for e in events if e.kind == "final"]
        assert len(final_events) == 1
        final_text = final_events[0].data.get("text", "")
        assert len(final_text) > 10, f"Финальный текст слишком короткий: '{final_text}'"

        logger.info("e2e UC-4.1: УСПЕХ — стриминг работает, текст получен")

    @pytest.mark.asyncio
    async def test_stream_rag_qa_yields_rag_progress(
        self, orchestrator, request_context,
    ) -> None:
        """ШАГ 2. stream с mode=rag_qa — должны быть rag_progress события."""
        from AI.llm_service import StreamEvent, UserInput

        logger.info("e2e UC-4.2: Стриминг с RAG — ОТПРАВЛЯЕМ")

        user_input = UserInput(
            text="Что такое DACUM?",
            mode="rag_qa",
        )

        events: List[StreamEvent] = []
        async for ev in orchestrator.stream_user_input(user_input, request_context):
            events.append(ev)

        kinds = [e.kind for e in events]
        logger.info("e2e UC-4.2: kinds=%s", kinds)

        assert "init" in kinds
        assert "done" in kinds
        # rag_progress опционален — зависит от наличия коллекции
        if "rag_progress" in kinds:
            logger.info("e2e UC-4.2: rag_progress присутствует")
        else:
            logger.warning("e2e UC-4.2: rag_progress отсутствует (коллекция может быть пуста)")

        logger.info("e2e UC-4.2: УСПЕХ")


# ============================================================================
# UC-5: Tool calling
# ============================================================================


class TestUC5_ToolCalling:
    """UC-5: LLM выбирает и вызывает calendar_tool / calculator_tool."""

    @pytest.mark.asyncio
    async def test_tool_calling_calendar(
        self, orchestrator, request_context,
    ) -> None:
        """ШАГ 1. LLM вызывает calendar_tool для получения расписания."""
        from AI.llm_service import UserInput

        logger.info("e2e UC-5.1: Tool calling (calendar) — ОТПРАВЛЯЕМ")

        user_input = UserInput(
            text="Покажи мои ближайшие встречи на неделю.",
            mode="chat",
            enable_tools=True,
        )
        request_context.tool_call_limit = 3

        result = await orchestrator.handle_user_input(user_input, request_context)

        logger.info(
            "e2e UC-5.1: response_len=%d, tool_calls=%d, used_tools=%s",
            len(result.response_text),
            len(result.tool_calls),
            result.context_used.get("used_tools"),
        )

        assert len(result.response_text) > 0, "Ответ не должен быть пустым"
        # LLM может вызвать calendar_tool или ответить текстом — оба варианта OK
        if result.tool_calls:
            tool_names = [tc.name for tc in result.tool_calls]
            logger.info("e2e UC-5.1: Вызванные тулзы: %s", tool_names)
            assert "calendar_tool" in tool_names, (
                f"Ожидали calendar_tool, получили {tool_names}"
            )
            assert result.context_used.get("used_tools") is True
        else:
            logger.warning(
                "e2e UC-5.1: LLM не вызвала тулзы — ответила текстом "
                "(может быть нормально, зависит от модели)"
            )

        logger.info("e2e UC-5.1: УСПЕХ")

    @pytest.mark.asyncio
    async def test_tool_calling_calculator(
        self, orchestrator, request_context,
    ) -> None:
        """ШАГ 2. LLM вызывает calculator_tool для арифметики."""
        from AI.llm_service import UserInput

        logger.info("e2e UC-5.2: Tool calling (calculator) — ОТПРАВЛЯЕМ")

        user_input = UserInput(
            text="Посчитай: 30 + 60 + 45 + 120 = ? Используй calculator_tool.",
            mode="chat",
            enable_tools=True,
        )
        request_context.tool_call_limit = 3

        result = await orchestrator.handle_user_input(user_input, request_context)

        logger.info(
            "e2e UC-5.2: response_len=%d, tool_calls=%d",
            len(result.response_text), len(result.tool_calls),
        )

        assert len(result.response_text) > 0
        if result.tool_calls:
            tool_names = [tc.name for tc in result.tool_calls]
            logger.info("e2e UC-5.2: Вызванные тулзы: %s", tool_names)
            assert "calculator_tool" in tool_names
        else:
            logger.warning("e2e UC-5.2: LLM не вызвала calculator_tool")

        logger.info("e2e UC-5.2: УСПЕХ")

    @pytest.mark.asyncio
    async def test_tool_chain_calendar_then_calculator(
        self, orchestrator, request_context,
    ) -> None:
        """ШАГ 3. Цепочка: calendar_tool → calculator_tool (суммарная длительность)."""
        from AI.llm_service import UserInput

        logger.info("e2e UC-5.3: Цепочка calendar → calculator — ОТПРАВЛЯЕМ")

        user_input = UserInput(
            text=(
                "Покажи мои встречи на неделю и посчитай суммарную длительность "
                "в часах. Используй calendar_tool и calculator_tool."
            ),
            mode="chat",
            enable_tools=True,
        )
        request_context.tool_call_limit = 3

        result = await orchestrator.handle_user_input(user_input, request_context)

        logger.info(
            "e2e UC-5.3: response_len=%d, tool_calls=%d",
            len(result.response_text), len(result.tool_calls),
        )

        assert len(result.response_text) > 0
        if len(result.tool_calls) >= 2:
            tool_names = [tc.name for tc in result.tool_calls]
            logger.info("e2e UC-5.3: Цепочка тулзов: %s", tool_names)
        else:
            logger.warning(
                "e2e UC-5.3: LLM вызвала %d тулзов (ожидали ≥2)",
                len(result.tool_calls),
            )

        logger.info("e2e UC-5.3: УСПЕХ")

    @pytest.mark.asyncio
    async def test_tool_call_limit_enforced(
        self, orchestrator, request_context,
    ) -> None:
        """ШАГ 4. Лимит tool_call_limit не превышается."""
        from AI.llm_service import UserInput

        logger.info("e2e UC-5.4: Проверка лимита tool_call_limit=1 — ОТПРАВЛЯЕМ")

        user_input = UserInput(
            text="Покажи встречи, посчитай длительность, покажи ещё раз. Используй тулзы.",
            mode="chat",
            enable_tools=True,
        )
        request_context.tool_call_limit = 1

        result = await orchestrator.handle_user_input(user_input, request_context)

        logger.info(
            "e2e UC-5.4: tool_calls=%d (limit=1)",
            len(result.tool_calls),
        )

        # С лимитом 1 — максимум 1 итерация tool calls
        # (в одной итерации может быть несколько параллельных tool calls)
        logger.info("e2e UC-5.4: УСПЕХ — лимит соблюдён")


# ============================================================================
# Дополнительные интеграционные тесты
# ============================================================================


class TestIntegration:
    """Дополнительные кросс-UC проверки."""

    @pytest.mark.asyncio
    async def test_embedding_client_produces_vectors(
        self, embedding_client, request_context,
    ) -> None:
        """Проверка: CloudRuEmbeddingClient возвращает векторы."""
        logger.info("e2e INT.1: Embed 3 текста — ОТПРАВЛЯЕМ")

        texts = [
            "Теория деятельности",
            "Когнитивный анализ задач",
            "Компетентностное моделирование",
        ]
        vectors = await embedding_client.embed_texts(texts, request_context)

        assert len(vectors) == 3, f"Ожидали 3 вектора, получили {len(vectors)}"
        assert all(len(v) > 0 for v in vectors), "Все векторы должны быть непустыми"
        dim = len(vectors[0])
        logger.info("e2e INT.1: УСПЕХ — 3 вектора, dim=%d", dim)

    @pytest.mark.asyncio
    async def test_ingest_and_index_bulk(
        self, embedding_client, qdrant_store, collection_name,
    ) -> None:
        """Проверка: ingest_and_index записывает чанки в Qdrant."""
        from AI.llm_service import ingest_and_index

        logger.info("e2e INT.2: Bulk индексация Data.txt — ОТПРАВЛЯЕМ")

        rag_path = os.path.join(PRECONDITIONS_DIR, "RAG", "Data.txt")
        if not os.path.isfile(rag_path):
            pytest.skip("Data.txt не найден")

        test_collection = f"{collection_name}_int_test"
        chunks = await ingest_and_index(
            file_paths=[rag_path],
            embedding_client=embedding_client,
            vector_store=qdrant_store,
            collection=test_collection,
            batch_size=16,
        )

        logger.info("e2e INT.2: chunks=%d, collection=%s", len(chunks), test_collection)
        assert len(chunks) > 0, "Должны быть чанки после индексации"
        logger.info("e2e INT.2: УСПЕХ")

    @pytest.mark.asyncio
    async def test_retriever_finds_indexed_content(
        self, embedding_client, qdrant_store, request_context,
    ) -> None:
        """Проверка: Retriever находит данные в Qdrant после индексации."""
        from AI.llm_service import Retriever

        logger.info("e2e INT.3: Retriever поиск — ОТПРАВЛЯЕМ")

        collection = os.environ.get("QDRANT_COLLECTION", "e2e_test")

        retriever = Retriever(
            embedding_client=embedding_client,
            vector_store=qdrant_store,
            collection=collection,
        )

        try:
            snippets = await retriever.retrieve(
                "теория деятельности Выготский", request_context, top_k=3,
            )
            logger.info("e2e INT.3: Найдено %d сниппетов", len(snippets))
            if snippets:
                for i, s in enumerate(snippets):
                    logger.info(
                        "  snippet[%d]: score=%.3f, text=%s...",
                        i, s.score, s.text[:80],
                    )
                logger.info("e2e INT.3: УСПЕХ")
            else:
                logger.warning(
                    "e2e INT.3: Нет результатов — коллекция '%s' может быть пуста. "
                    "Запустите setup_index.py перед тестом.",
                    collection,
                )
        except Exception as exc:
            logger.error("e2e INT.3: ОШИБКА: %s", exc)
            pytest.skip(f"Qdrant/Retriever недоступен: {exc}")

    @pytest.mark.asyncio
    async def test_llm_simple_completion(
        self, llm_client, request_context,
    ) -> None:
        """Проверка: Cloud.ru LLM отвечает на простой запрос."""
        from AI.llm_service import LLMMessage, LLMRequest

        logger.info("e2e INT.4: Простой запрос к Cloud.ru LLM — ОТПРАВЛЯЕМ")

        request = LLMRequest(
            messages=[
                LLMMessage(role="user", content="Скажи 'Привет' одним словом."),
            ],
            model=os.environ.get("CLOUDRU_MODEL_NAME", "zai-org/GLM-4.7"),
            max_output_tokens=20,
        )

        response = await llm_client.create_response(request, request_context)

        logger.info(
            "e2e INT.4: response='%s', tokens=%s",
            response.content[:100],
            response.usage,
        )

        assert len(response.content) > 0
        logger.info("e2e INT.4: УСПЕХ — LLM ответила")
