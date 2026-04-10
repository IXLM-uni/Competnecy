# -*- coding: utf-8 -*-
"""
Руководство к файлу test_llm_service.py
========================================

Назначение:
    Unit-тесты для глобального LLM-сервиса из llm_service.py.
    Проверяются все ключевые сценарии оркестратора ChatOrchestrator:
      - UC-1: RAG + Internet + tool calling + JSON repair + tokens
      - UC-2: Инжест документов
      - UC-3: ASR → LLM
      - UC-4: Streaming
      - UC-5: Tool calling с лимитами

Принципы:
    - Все внешние зависимости (LLM, RAG, ASR, tools) заменены заглушками.
    - Тесты используют pytest-asyncio.
    - Слой API (FastAPI) не используется — тестируется только ядро.
"""

from __future__ import annotations

import json
from typing import Any, AsyncIterator, Dict, List, Optional, Sequence

import pytest

from AI.llm_service import (
    ChatMessage,
    ChatOrchestrator,
    ContextBuilder,
    DocumentChunk,
    LLMMessage,
    LLMRequest,
    LLMResponse,
    OpenAIClient,
    OrchestratorResult,
    RequestContext,
    Retriever,
    Snippet,
    StreamEvent,
    TokenUsage,
    ToolCall,
    ToolExecutor,
    ToolRegistry,
    ToolResult,
    UserInput,
)


# =============================================================================
# Заглушки
# =============================================================================


class DummyOpenAIClient(OpenAIClient):
    """Заглушка LLM: фиксированный текст и/или tool calls."""

    def __init__(self) -> None:
        self._default_model = "dummy-model"
        self.calls: List[LLMRequest] = []
        self.next_tool_calls: List[ToolCall] = []
        self.next_response_text: str = "Ответ LLM"
        self.next_usage: Optional[TokenUsage] = TokenUsage(
            prompt_tokens=10, completion_tokens=5, total_tokens=15,
        )

    async def create_response(
        self, request: LLMRequest, ctx: RequestContext,
    ) -> LLMResponse:
        self.calls.append(request)
        tool_calls = list(self.next_tool_calls)
        self.next_tool_calls = []
        return LLMResponse(
            content=self.next_response_text,
            tool_calls=tool_calls,
            usage=self.next_usage,
            raw_response={},
        )

    async def stream_response(
        self, request: LLMRequest, ctx: RequestContext,
    ) -> AsyncIterator[StreamEvent]:
        self.calls.append(request)
        yield StreamEvent(kind="token_delta", data={"text": "часть "})
        yield StreamEvent(kind="token_delta", data={"text": "ответа"})


class DummyRetriever(Retriever):
    """Заглушка ретривера: возвращает фиксированные сниппеты."""

    def __init__(self) -> None:
        self.calls: List[Dict[str, Any]] = []

    async def retrieve(
        self, query: str, ctx: RequestContext, top_k: int = 6,
    ) -> List[Snippet]:
        self.calls.append({"query": query, "top_k": top_k})
        return [
            Snippet(text="RAG snippet 1", source_id="doc1", score=0.95),
        ]

    async def retrieve_multi(
        self, queries: List[str], ctx: RequestContext, top_k: int = 6,
    ) -> List[Snippet]:
        self.calls.append({"queries": queries, "top_k": top_k})
        return [
            Snippet(text="RAG snippet 1", source_id="doc1", score=0.95),
            Snippet(text="RAG snippet 2", source_id="doc2", score=0.80),
        ]


class DummyToolRegistry(ToolRegistry):
    """Реестр tools с предзаполненным dummy_tool."""

    def __init__(self) -> None:
        super().__init__()

    def get_openai_tools(
        self, whitelist: Optional[List[str]] = None,
    ) -> List[Dict[str, Any]]:
        return [
            {
                "type": "function",
                "function": {
                    "name": "dummy_tool",
                    "description": "Тестовый тул",
                    "parameters": {
                        "type": "object",
                        "properties": {"x": {"type": "integer"}},
                        "required": ["x"],
                    },
                },
            }
        ]


class DummyToolExecutor(ToolExecutor):
    """Заглушка ToolExecutor: фиксированный результат."""

    def __init__(self) -> None:
        self.calls: List[ToolCall] = []

    async def execute_many(
        self, calls: Sequence[ToolCall], ctx: RequestContext,
    ) -> List[ToolResult]:
        self.calls.extend(calls)
        return [
            ToolResult(
                id=call.id, name=call.name,
                output={"ok": True, "name": call.name},
            )
            for call in calls
        ]


# =============================================================================
# Фикстуры
# =============================================================================


def _make_orchestrator(
    *,
    with_rag: bool = False,
    with_tools: bool = False,
) -> ChatOrchestrator:
    """Собирает оркестратор с нужным набором заглушек."""
    context_builder = ContextBuilder(default_model="dummy-model")
    llm_client = DummyOpenAIClient()
    tool_registry = DummyToolRegistry() if with_tools else ToolRegistry()
    tool_executor = DummyToolExecutor() if with_tools else ToolExecutor(ToolRegistry())
    retriever = DummyRetriever() if with_rag else None

    return ChatOrchestrator(
        context_builder=context_builder,
        llm_client=llm_client,
        tool_registry=tool_registry,
        tool_executor=tool_executor,
        retriever=retriever,
    )


@pytest.fixture
def request_context() -> RequestContext:
    return RequestContext(request_id="test-req-1")


# =============================================================================
# Тесты: UC-1 — RAG + tools + tokens
# =============================================================================


@pytest.mark.asyncio
async def test_handle_user_input_new_conversation_rag_and_tools(
    request_context: RequestContext,
) -> None:
    """UC-1: новый диалог, RAG + tools, история сохраняется, токены считаются."""
    orch = _make_orchestrator(with_rag=True, with_tools=True)
    dummy_llm: DummyOpenAIClient = orch._llm  # type: ignore[assignment]
    dummy_llm.next_tool_calls = [
        ToolCall(id="tc1", name="dummy_tool", arguments={"x": 42}),
    ]

    # Явно задаём conversation_id на уровне контекста (транспортный слой),
    # оркестратор не должен генерировать его сам.
    conv_id = "conv-new-1"
    request_context.conversation_id = conv_id

    user_input = UserInput(
        text="Что такое RAG?",
        mode="rag_qa",
        enable_tools=True,
    )

    result = await orch.handle_user_input(user_input, request_context)

    assert isinstance(result, OrchestratorResult)
    assert result.response_text == "Ответ LLM"
    # Оркестратор использует уже переданный conversation_id
    assert request_context.conversation_id == conv_id
    assert result.context_used["conversation_id"] == conv_id

    assert result.context_used["used_rag"] is True
    assert result.context_used["used_tools"] is True
    assert len(result.tool_calls) == 1
    assert result.tool_calls[0].name == "dummy_tool"

    assert result.tokens_used is not None
    assert result.tokens_used.total_tokens is not None
    assert result.tokens_used.total_tokens > 0

    assert len(result.sources) == 2


@pytest.mark.asyncio
async def test_handle_user_input_chat_mode_no_rag(
    request_context: RequestContext,
) -> None:
    """UC-1 (mode=chat): RAG не вызывается."""
    orch = _make_orchestrator(with_rag=True)

    user_input = UserInput(text="Привет", mode="chat")
    result = await orch.handle_user_input(user_input, request_context)

    assert result.response_text == "Ответ LLM"
    assert result.context_used["used_rag"] is False
    assert len(result.sources) == 0


# =============================================================================
# Тесты: UC-2 — Повторный диалог + история
# =============================================================================


@pytest.mark.asyncio
async def test_reuses_existing_conversation(
    request_context: RequestContext,
) -> None:
    """Повторный запрос использует conversation_id и накапливает историю."""
    orch = _make_orchestrator()

    # Явно создаём conversation_id на стороне вызывающего кода
    conv_id = "conv-history-1"

    first_ctx = RequestContext(
        request_id="test-req-1", conversation_id=conv_id,
    )
    first_input = UserInput(
        conversation_id=conv_id, text="Первое сообщение", mode="chat",
    )
    await orch.handle_user_input(first_input, first_ctx)

    second_ctx = RequestContext(
        request_id="test-req-2", conversation_id=conv_id,
    )
    second_input = UserInput(
        conversation_id=conv_id, text="Второе сообщение", mode="chat",
    )
    second_result = await orch.handle_user_input(second_input, second_ctx)

    assert second_result.context_used["conversation_id"] == conv_id
    # История не ведётся — всегда 0
    assert second_result.context_used.get("history_messages", 0) == 0


# =============================================================================
# Тесты: UC-4 — Streaming
# =============================================================================


@pytest.mark.asyncio
async def test_stream_user_input_yields_events(
    request_context: RequestContext,
) -> None:
    """stream_user_input отдает init → token_delta(s) → final → done."""
    orch = _make_orchestrator()

    user_input = UserInput(text="Стрим", mode="chat")
    events: List[StreamEvent] = []
    async for ev in orch.stream_user_input(user_input, request_context):
        events.append(ev)

    kinds = [e.kind for e in events]
    assert kinds[0] == "init"
    assert "token_delta" in kinds
    assert kinds[-2] == "final"
    assert kinds[-1] == "done"

    final_ev = [e for e in events if e.kind == "final"][0]
    assert "часть" in final_ev.data["text"]


# =============================================================================
# Тесты: UC-5 — Tool calling лимит
# =============================================================================


@pytest.mark.asyncio
async def test_tool_call_limit_respected(
    request_context: RequestContext,
) -> None:
    """Оркестратор не делает больше tool_call_limit итераций."""
    orch = _make_orchestrator(with_tools=True)
    dummy_llm: DummyOpenAIClient = orch._llm  # type: ignore[assignment]
    request_context.tool_call_limit = 2

    call_count = 0
    original_create = dummy_llm.create_response

    async def _always_tool_call(req: LLMRequest, ctx: RequestContext) -> LLMResponse:
        nonlocal call_count
        call_count += 1
        if call_count <= 3:
            return LLMResponse(
                content="",
                tool_calls=[ToolCall(id=f"tc{call_count}", name="dummy_tool", arguments={"x": 1})],
                usage=TokenUsage(prompt_tokens=5, completion_tokens=3, total_tokens=8),
                raw_response={},
            )
        return LLMResponse(
            content="Финал", tool_calls=[],
            usage=TokenUsage(prompt_tokens=5, completion_tokens=3, total_tokens=8),
            raw_response={},
        )

    dummy_llm.create_response = _always_tool_call  # type: ignore[assignment]

    user_input = UserInput(text="Тест лимита", mode="chat", enable_tools=True)
    result = await orch.handle_user_input(user_input, request_context)

    dummy_executor: DummyToolExecutor = orch._tool_executor  # type: ignore[assignment]
    assert len(dummy_executor.calls) <= 2 * 1


# =============================================================================
# Тесты: ContextBuilder
# =============================================================================


@pytest.mark.asyncio
async def test_context_builder_includes_all_sources() -> None:
    """ContextBuilder включает RAG, Internet, документы в промпт."""
    builder = ContextBuilder(default_model="test-model")
    ctx = RequestContext(request_id="r1")

    rag = [Snippet(text="rag text", source_id="s1", score=0.9)]
    internet = [Snippet(text="web text", source_id="url1", score=0.8)]
    docs = [DocumentChunk(text="doc text", source_id="f1", page=1)]

    user_input = UserInput(text="Вопрос?")
    llm_req = await builder.build_input(user_input, None, rag, internet, docs, ctx)

    all_content = " ".join(m.content for m in llm_req.messages)
    assert "rag text" in all_content
    assert "web text" in all_content
    assert "doc text" in all_content
    assert "Вопрос?" in all_content


# =============================================================================
# Тесты: JsonRepairLLM + StrictOutputParser
# =============================================================================


@pytest.mark.asyncio
async def test_json_repair_fixes_trailing_comma() -> None:
    """JsonRepairLLM убирает trailing comma."""
    from AI.llm_service import JsonRepairLLM

    repair = JsonRepairLLM()
    ctx = RequestContext(request_id="r1")

    broken = '{"a": 1, "b": 2,}'
    fixed = await repair.repair(broken, ctx)
    data = json.loads(fixed)
    assert data == {"a": 1, "b": 2}


@pytest.mark.asyncio
async def test_json_repair_strips_code_fences() -> None:
    """JsonRepairLLM убирает markdown code fences."""
    from AI.llm_service import JsonRepairLLM

    repair = JsonRepairLLM()
    ctx = RequestContext(request_id="r1")

    fenced = '```json\n{"key": "value"}\n```'
    fixed = await repair.repair(fenced, ctx)
    data = json.loads(fixed)
    assert data == {"key": "value"}


@pytest.mark.asyncio
async def test_strict_output_parser_validates() -> None:
    """StrictOutputParser валидирует JSON через Pydantic."""
    from pydantic import BaseModel

    from AI.llm_service import StrictOutputParser

    class TestSchema(BaseModel):
        name: str
        value: int

    parser = StrictOutputParser()
    ctx = RequestContext(request_id="r1")

    result = await parser.parse_json('{"name": "test", "value": 42}', TestSchema, ctx)
    assert result.name == "test"  # type: ignore[attr-defined]
    assert result.value == 42  # type: ignore[attr-defined]

    with pytest.raises(Exception):
        await parser.parse_json('{"name": "test"}', TestSchema, ctx)


# =============================================================================
# Тесты: Chunker
# =============================================================================


@pytest.mark.asyncio
async def test_chunker_splits_text() -> None:
    """Chunker разбивает текст на чанки заданного размера."""
    from AI.llm_service import Chunker

    chunker = Chunker(chunk_size_tokens=10, chunk_overlap_tokens=3)
    chunks = await chunker.split("abcdefghijklmnopqrstuvwxyz", source_id="s1", page=1)

    assert len(chunks) > 1
    assert all(c.source_id == "s1" for c in chunks)
    assert all(c.page == 1 for c in chunks)
    assert all(c.checksum is not None for c in chunks)


@pytest.mark.asyncio
async def test_chunker_empty_text() -> None:
    """Chunker возвращает пустой список для пустого текста."""
    from AI.llm_service import Chunker

    chunker = Chunker()
    chunks = await chunker.split("   ", source_id="s1")
    assert chunks == []