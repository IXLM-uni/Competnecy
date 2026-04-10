# -*- coding: utf-8 -*-
"""
Руководство к файлу conftest_e2e.py
====================================

Назначение:
    Общие pytest-фикстуры для e2e-тестов (tests/e2e.py).
    Загружает .env, создаёт реальные клиенты Cloud.ru, Qdrant,
    моковые тулзы, тестовое аудио и оркестратор.

    Все фикстуры используют scope="session" где возможно
    для переиспользования тяжёлых ресурсов.

Зависимости:
    pytest, pytest-asyncio, python-dotenv, httpx
"""

from __future__ import annotations

import asyncio
import csv
import logging
import os
from typing import Any, AsyncIterator, Dict, List, Optional

import pytest
import pytest_asyncio

logger = logging.getLogger(__name__)

PRECONDITIONS_DIR = os.path.dirname(os.path.abspath(__file__))


# ============================================================================
# Загрузка .env
# ============================================================================

@pytest.fixture(scope="session", autouse=True)
def load_env() -> None:
    """Загружает переменные окружения из Global_services/.env."""
    from dotenv import load_dotenv

    env_path = os.path.join(PRECONDITIONS_DIR, "..", "..", ".env")
    env_path = os.path.abspath(env_path)
    load_dotenv(env_path)
    logger.info("e2e conftest: .env загружен из %s", env_path)


# ============================================================================
# Cloud.ru клиенты
# ============================================================================

@pytest.fixture(scope="session")
def cloudru_api_key() -> str:
    key = os.environ.get("CLOUDRU_API_KEY", "")
    if not key:
        pytest.skip("CLOUDRU_API_KEY не задан — пропуск e2e")
    return key


@pytest.fixture(scope="session")
def cloudru_base_url() -> str:
    return os.environ.get(
        "CLOUDRU_BASE_URL", "https://foundation-models.api.cloud.ru/v1",
    )


@pytest.fixture(scope="session")
def llm_client(cloudru_api_key: str, cloudru_base_url: str):
    """Реальный OpenAIClient → Cloud.ru."""
    from AI.llm_service import OpenAIClient

    model = os.environ.get("CLOUDRU_MODEL_NAME", "zai-org/GLM-4.7")
    logger.info("e2e conftest: создаём OpenAIClient model=%s", model)
    return OpenAIClient(
        api_key=cloudru_api_key,
        base_url=cloudru_base_url,
        default_model=model,
    )


@pytest.fixture(scope="session")
def embedding_client(cloudru_api_key: str, cloudru_base_url: str):
    """Реальный CloudRuEmbeddingClient → Cloud.ru."""
    from AI.llm_service import CloudRuEmbeddingClient

    model = os.environ.get("CLOUDRU_EMBED_MODEL", "Qwen/Qwen3-Embedding-0.6B")
    logger.info("e2e conftest: создаём CloudRuEmbeddingClient model=%s", model)
    return CloudRuEmbeddingClient(
        api_key=cloudru_api_key,
        base_url=cloudru_base_url,
        model_name=model,
    )


@pytest.fixture(scope="session")
def asr_client(cloudru_api_key: str, cloudru_base_url: str):
    """Реальный ASRClient → Cloud.ru."""
    from AI.llm_service import ASRClient

    model = os.environ.get("ASR_MODEL", "openai/whisper-large-v3")
    logger.info("e2e conftest: создаём ASRClient model=%s", model)
    return ASRClient(
        api_key=cloudru_api_key,
        base_url=cloudru_base_url,
        model=model,
    )


# ============================================================================
# Qdrant
# ============================================================================

@pytest.fixture(scope="session")
def qdrant_store():
    """Реальный QdrantVectorStore."""
    from AI.llm_service import QdrantVectorStore

    host = os.environ.get("QDRANT_HOST", "localhost")
    port = int(os.environ.get("QDRANT_PORT", "6334"))
    logger.info("e2e conftest: создаём QdrantVectorStore %s:%d", host, port)
    return QdrantVectorStore(host=host, port=port, https=False)


@pytest.fixture(scope="session")
def collection_name() -> str:
    return os.environ.get("QDRANT_COLLECTION", "e2e_test")


# ============================================================================
# Retriever
# ============================================================================

@pytest.fixture(scope="session")
def retriever(embedding_client, qdrant_store, collection_name):
    """Реальный Retriever (vector only, без sparse)."""
    from AI.llm_service import Retriever

    logger.info("e2e conftest: создаём Retriever collection=%s", collection_name)
    return Retriever(
        embedding_client=embedding_client,
        vector_store=qdrant_store,
        collection=collection_name,
    )


# ============================================================================
# Моковые тулзы
# ============================================================================

@pytest_asyncio.fixture(scope="session")
async def tool_registry():
    """ToolRegistry с calendar_tool и calculator_tool."""
    from AI.llm_service import ToolRegistry
    from AI.Preconditions.tools import register_mock_tools

    registry = ToolRegistry()
    await register_mock_tools(registry)
    logger.info("e2e conftest: моковые тулзы зарегистрированы")
    return registry


# ============================================================================
# Оркестратор (полный, боевой)
# ============================================================================

@pytest_asyncio.fixture(scope="session")
async def orchestrator(llm_client, retriever, tool_registry, asr_client):
    """Полный ChatOrchestrator с боевыми клиентами."""
    from AI.llm_service import (
        ChatOrchestrator,
        ContextBuilder,
        CrawlerQueryRewriter,
        DocumentIngestor,
        InMemoryConversationStore,
        JsonRepairLLM,
        RagQueryRewriter,
        StrictOutputParser,
        ToolExecutor,
    )

    model = os.environ.get("CLOUDRU_MODEL_NAME", "zai-org/GLM-4.7")
    store = InMemoryConversationStore()
    context_builder = ContextBuilder(default_model=model)
    tool_executor = ToolExecutor(tool_registry)
    rag_rewriter = RagQueryRewriter(llm_client, count=3)
    ingestor = DocumentIngestor()
    json_repair = JsonRepairLLM()
    strict_parser = StrictOutputParser(json_repair)

    orch = ChatOrchestrator(
        conversation_store=store,
        context_builder=context_builder,
        llm_client=llm_client,
        tool_registry=tool_registry,
        tool_executor=tool_executor,
        retriever=retriever,
        rag_rewriter=rag_rewriter,
        crawler_client=None,  # без интернета в e2e
        crawler_rewriter=None,
        document_ingestor=ingestor,
        asr_client=asr_client,
        json_repair=json_repair,
        strict_parser=strict_parser,
    )
    logger.info("e2e conftest: ChatOrchestrator создан")
    return orch


# ============================================================================
# RequestContext
# ============================================================================

@pytest.fixture
def request_context():
    """Свежий RequestContext для каждого теста."""
    from AI.llm_service import RequestContext
    return RequestContext()


# ============================================================================
# Тестовые данные
# ============================================================================

@pytest.fixture(scope="session")
def documents_dir() -> str:
    return os.path.join(PRECONDITIONS_DIR, "documents")


@pytest.fixture(scope="session")
def rag_data_path() -> str:
    return os.path.join(PRECONDITIONS_DIR, "RAG", "Data.txt")


@pytest.fixture(scope="session")
def ground_truth() -> List[Dict[str, str]]:
    """Загружает ground_truth.csv в список словарей."""
    gt_path = os.path.join(PRECONDITIONS_DIR, "RAG", "ground_truth.csv")
    rows: List[Dict[str, str]] = []
    with open(gt_path, "r", encoding="utf-8") as f:
        reader = csv.DictReader(f, delimiter=";")
        for row in reader:
            rows.append(dict(row))
    logger.info("e2e conftest: ground_truth загружен, rows=%d", len(rows))
    return rows


@pytest_asyncio.fixture(scope="session")
async def test_audio_paths():
    """Генерирует тестовые аудио-файлы и возвращает пути."""
    from AI.Preconditions.audio.generate_test_audio import ensure_test_audio_files
    paths = await ensure_test_audio_files()
    logger.info("e2e conftest: тестовые аудио-файлы: %s", paths)
    return paths
