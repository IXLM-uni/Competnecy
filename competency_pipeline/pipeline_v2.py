# -*- coding: utf-8 -*-
"""
Упрощённый 3-stage pipeline orchestrator.

Stage 1: Сбор источников → raw_corpus.md
Stage 2: Извлечение компетенций → competencies.csv
Stage 3: Генерация программы → program.md + curriculum.csv
"""

import asyncio
import json
import logging
import traceback
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional

from .llm_helpers import emit_sse
from .research_ingestion_service import ResearchIngestionService, SourceSpec
from .competency_extractor import CompetencyExtractor
from .program_generator import ProgramGenerator

logger = logging.getLogger(__name__)


class PipelineV2:
    """3-stage Competency Pipeline."""

    STAGES = [
        ("RESEARCH_INGESTION", "Сбор источников"),
        ("COMPETENCY_EXTRACTION", "Извлечение компетенций"),
        ("PROGRAM_GENERATION", "Генерация программы"),
    ]

    def __init__(self, role: str, artifacts_dir: str = "./artifacts", semesters: int = 4):
        self.role = role
        self.semesters = semesters
        self.artifacts_dir = Path(artifacts_dir)
        self.artifacts_dir.mkdir(parents=True, exist_ok=True)

        self.research_service = ResearchIngestionService(artifacts_dir)
        self.extractor = CompetencyExtractor(artifacts_dir)
        self.generator = ProgramGenerator(artifacts_dir)

    def _build_source_specs(self) -> List[SourceSpec]:
        return [
            SourceSpec(source_type='onet',
                       query=self.role, limit=3, priority='high'),
            SourceSpec(source_type='web_search',
                       query=f'{self.role} job requirements skills competencies',
                       limit=10, priority='high'),
            SourceSpec(source_type='hh_vacancies',
                       query=self.role, limit=10, priority='high'),
            SourceSpec(source_type='web_search',
                       query=f'{self.role} university program curriculum',
                       limit=10, priority='medium'),
            SourceSpec(source_type='telegram',
                       query=f'{self.role} вакансия компетенции',
                       limit=10, priority='low'),
            SourceSpec(source_type='reddit',
                       query=f'{self.role} career skills',
                       limit=5, priority='low'),
        ]

    async def run(self) -> Dict[str, Any]:
        """Запуск 3-stage pipeline."""
        start_time = datetime.now()
        errors: List[str] = []
        artifacts: Dict[str, List[str]] = {}

        logger.info(f"Pipeline V2: роль={self.role}, семестров={self.semesters}")

        # ── Stage 1: Сбор источников ─────────────────────────────────
        try:
            await emit_sse("stage", {"stage": "RESEARCH_INGESTION", "status": "started",
                                      "label": "Сбор источников", "index": 0})

            specs = self._build_source_specs()
            source_artifacts = await self.research_service.collect_sources(self.role, specs)

            saved = await self.research_service.save_corpus(source_artifacts, self.role)

            stage1_dur = (datetime.now() - start_time).total_seconds()
            artifacts["RESEARCH_INGESTION"] = list(saved.values())

            await emit_sse("stage", {"stage": "RESEARCH_INGESTION", "status": "completed",
                                      "label": "Сбор источников", "index": 0,
                                      "duration": round(stage1_dur, 1),
                                      "artifacts": [Path(p).name for p in saved.values()]})

            logger.info(f"Stage 1 done: {len(source_artifacts)} sources in {stage1_dur:.1f}s")

        except Exception as e:
            errors.append(f"Stage 1: {e}")
            logger.error(f"Stage 1 FAILED: {e}\n{traceback.format_exc()}")
            await emit_sse("error", {"stage": "RESEARCH_INGESTION", "message": str(e)})

        # ── Stage 2: Извлечение компетенций ──────────────────────────
        stage2_start = datetime.now()
        try:
            csv_path = await self.extractor.extract_competencies(self.role)
            stage2_dur = (datetime.now() - stage2_start).total_seconds()
            artifacts["COMPETENCY_EXTRACTION"] = [csv_path]
            logger.info(f"Stage 2 done: {csv_path} in {stage2_dur:.1f}s")

        except Exception as e:
            errors.append(f"Stage 2: {e}")
            logger.error(f"Stage 2 FAILED: {e}\n{traceback.format_exc()}")
            await emit_sse("error", {"stage": "COMPETENCY_EXTRACTION", "message": str(e)})

        # ── Stage 3: Генерация программы ─────────────────────────────
        stage3_start = datetime.now()
        try:
            program_path = await self.generator.generate_program(self.role, self.semesters)
            stage3_dur = (datetime.now() - stage3_start).total_seconds()
            artifacts["PROGRAM_GENERATION"] = [program_path]
            logger.info(f"Stage 3 done: {program_path} in {stage3_dur:.1f}s")

        except Exception as e:
            errors.append(f"Stage 3: {e}")
            logger.error(f"Stage 3 FAILED: {e}\n{traceback.format_exc()}")
            await emit_sse("error", {"stage": "PROGRAM_GENERATION", "message": str(e)})

        # ── Done ─────────────────────────────────────────────────────
        total_dur = (datetime.now() - start_time).total_seconds()

        await emit_sse("done", {
            "success": len(errors) == 0,
            "duration": round(total_dur, 1),
            "artifacts_count": sum(len(v) for v in artifacts.values()),
        })

        # Save state
        state_path = self.artifacts_dir / "pipeline_state.json"
        state_path.write_text(json.dumps({
            "role": self.role,
            "stages_completed": list(artifacts.keys()),
            "errors": errors,
            "duration": round(total_dur, 1),
            "timestamp": datetime.now().isoformat(),
        }, ensure_ascii=False, indent=2), encoding="utf-8")

        return {
            "success": len(errors) == 0,
            "duration_seconds": total_dur,
            "artifacts": artifacts,
            "errors": errors,
        }
