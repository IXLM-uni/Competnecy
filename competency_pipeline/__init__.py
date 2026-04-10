"""
COMPETENCY PIPELINE - Система интеллектуального анализа компетенций

Структура:
- research_ingestion_service: Сбор и нормализация источников 
- evidence_synthesis_service: Синтез evidence из корпуса
- competency_profile_service: Генерация профилей компетенций
- curriculum_generation_service: Создание образовательных программ
- review_service: Экспертная проверка программ
- pipeline_orchestrator: Главный координатор всех этапов

Артефакты сохраняются в markdown-first формате для прозрачности
и человеко-читаемого анализа.

Использует Global_services/AI как базовый LLM/Web/RAG слой.
"""

from .research_ingestion_service import ResearchIngestionService
from .evidence_synthesis_service import EvidenceSynthesisService  
from .competency_profile_service import CompetencyProfileService
from .curriculum_generation_service import CurriculumGenerationService
from .review_service import ReviewService
from .pipeline_orchestrator import CompetencyPipelineOrchestrator

__all__ = [
    "ResearchIngestionService",
    "EvidenceSynthesisService", 
    "CompetencyProfileService",
    "CurriculumGenerationService", 
    "ReviewService",
    "CompetencyPipelineOrchestrator"
]
