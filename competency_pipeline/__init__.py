"""Минимальный pipeline: сбор источников + извлечение md-профилей компетенций."""

from .research_ingestion_service import ResearchIngestionService, SourceSpec, SourceArtifact
from .llm_helpers import call_llm, init_env, get_llm_client, make_ctx

__all__ = [
    "ResearchIngestionService",
    "SourceSpec",
    "SourceArtifact",
    "call_llm",
    "init_env",
    "get_llm_client",
    "make_ctx",
]
