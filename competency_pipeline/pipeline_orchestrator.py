"""
COMPETENCY PIPELINE ORCHESTRATOR

Ответственность:
- Координация всех этапов Competency Pipeline
- Управление flow от Stage 0 до Stage 6
- Отслеживание состояния pipeline и артефактов
- Обработка ошибок и recovery
- Предоставление progress feedback

6 этапов pipeline (из PIPELINE.md):
Stage 0: Role framing -> role_scope.md
Stage 1: Research ingestion -> raw_corpus/, manifest, registry  
Stage 2: Evidence synthesis -> Evidence.md
Stage 3: Competency profile generation -> Competency_Profile.md
Stage 4: Program blueprint generation -> Program_Blueprint.md
Stage 5: Curriculum table generation -> Curriculum_Table.md  
Stage 6: Review and correction -> Review_Notes.md, Program_v2.md

Принципы:
- Markdown-first artifacts на всех этапах
- Подробное шаговое логирование формата "ШАГ N..."
- Возможность запуска с любого этапа (resume)
- Сохранение traceability между этапами
- Fail-safe с понятными сообщениями об ошибках
"""

import asyncio
import logging
import json
import traceback
from datetime import datetime
from pathlib import Path
from dataclasses import dataclass
from typing import List, Dict, Optional, Any, Callable
from enum import Enum

# Импортируем все сервисы pipeline
from .research_ingestion_service import ResearchIngestionService, SourceSpec
from .evidence_synthesis_service import EvidenceSynthesisService
from .competency_profile_service import CompetencyProfileService
from .curriculum_generation_service import CurriculumGenerationService
from .review_service import ReviewService
from .llm_helpers import emit_sse

logger = logging.getLogger(__name__)

class PipelineStage(Enum):
    """Этапы Competency Pipeline"""
    ROLE_FRAMING = 0
    RESEARCH_INGESTION = 1
    EVIDENCE_SYNTHESIS = 2
    COMPETENCY_PROFILE = 3
    PROGRAM_BLUEPRINT = 4
    CURRICULUM_TABLE = 5
    REVIEW_CORRECTION = 6

@dataclass
class PipelineConfig:
    """Конфигурация pipeline"""
    artifacts_dir: str = "./artifacts"
    role_scope: str = ""
    program_duration_semesters: int = 4
    source_specifications: List[SourceSpec] = None
    skip_stages: List[PipelineStage] = None
    resume_from_stage: Optional[PipelineStage] = None
    
    def __post_init__(self):
        if self.source_specifications is None:
            self.source_specifications = []
        if self.skip_stages is None:
            self.skip_stages = []

@dataclass
class PipelineState:
    """Состояние выполнения pipeline"""
    current_stage: PipelineStage
    completed_stages: List[PipelineStage]
    artifacts_created: Dict[PipelineStage, List[str]]
    errors: List[Dict[str, Any]]
    start_time: datetime
    stage_start_time: Optional[datetime] = None
    
    def __post_init__(self):
        if self.artifacts_created is None:
            self.artifacts_created = {}
        if self.errors is None:
            self.errors = []

class CompetencyPipelineOrchestrator:
    """
    Главный оркестратор Competency Intelligence Pipeline
    """
    
    def __init__(self, config: PipelineConfig):
        """
        Инициализация оркестратора
        
        Args:
            config: Конфигурация pipeline
        """
        logger.info("ШАГ 1. Инициализация CompetencyPipelineOrchestrator")
        
        self.config = config
        self.artifacts_dir = Path(config.artifacts_dir)
        self.artifacts_dir.mkdir(parents=True, exist_ok=True)
        
        # Инициализируем состояние
        self.state = PipelineState(
            current_stage=config.resume_from_stage or PipelineStage.ROLE_FRAMING,
            completed_stages=[],
            artifacts_created={},
            errors=[],
            start_time=datetime.now()
        )
        
        # Инициализируем сервисы
        self.research_service = ResearchIngestionService(config.artifacts_dir)
        self.evidence_service = EvidenceSynthesisService(config.artifacts_dir)
        self.competency_service = CompetencyProfileService(config.artifacts_dir)
        self.curriculum_service = CurriculumGenerationService(config.artifacts_dir)
        self.review_service = ReviewService(config.artifacts_dir)
        
        # Маппинг этапов на методы
        self.stage_handlers: Dict[PipelineStage, Callable] = {
            PipelineStage.ROLE_FRAMING: self._stage_0_role_framing,
            PipelineStage.RESEARCH_INGESTION: self._stage_1_research_ingestion,
            PipelineStage.EVIDENCE_SYNTHESIS: self._stage_2_evidence_synthesis,
            PipelineStage.COMPETENCY_PROFILE: self._stage_3_competency_profile,
            PipelineStage.PROGRAM_BLUEPRINT: self._stage_4_program_blueprint,
            PipelineStage.CURRICULUM_TABLE: self._stage_5_curriculum_table,
            PipelineStage.REVIEW_CORRECTION: self._stage_6_review_correction
        }
        
        logger.info("ШАГ 2. Инициализация завершена")
    
    async def run_pipeline(self) -> Dict[str, Any]:
        """
        Запуск полного pipeline
        
        Returns:
            Результат выполнения с путями к артефактам
        """
        logger.info("ШАГ 3. Запуск Competency Intelligence Pipeline")
        logger.info(f"ШАГ 3.1. Целевая роль: {self.config.role_scope}")
        logger.info(f"ШАГ 3.2. Директория артефактов: {self.artifacts_dir}")
        logger.info(f"ШАГ 3.3. Начальный этап: {self.state.current_stage.name}")
        
        try:
            # Сохраняем конфигурацию pipeline
            await self._save_pipeline_config()
            
            # Выполняем этапы последовательно
            stages_to_run = self._get_stages_to_run()
            
            for stage in stages_to_run:
                if stage in self.config.skip_stages:
                    logger.info(f"ШАГ {stage.value + 4}. Пропускаем этап {stage.name}")
                    continue
                
                stage_labels = {
                    PipelineStage.ROLE_FRAMING: "Определение роли",
                    PipelineStage.RESEARCH_INGESTION: "Сбор источников",
                    PipelineStage.EVIDENCE_SYNTHESIS: "Синтез Evidence",
                    PipelineStage.COMPETENCY_PROFILE: "Профиль компетенций",
                    PipelineStage.PROGRAM_BLUEPRINT: "Структура программы",
                    PipelineStage.CURRICULUM_TABLE: "Учебный план",
                    PipelineStage.REVIEW_CORRECTION: "Экспертная проверка",
                }

                logger.info(f"ШАГ {stage.value + 4}. Начинаем этап {stage.name}")
                self.state.current_stage = stage
                self.state.stage_start_time = datetime.now()

                await emit_sse("stage", {
                    "stage": stage.name,
                    "status": "started",
                    "label": stage_labels.get(stage, stage.name),
                    "index": stage.value,
                })

                try:
                    handler = self.stage_handlers[stage]
                    artifacts = await handler()

                    self.state.artifacts_created[stage] = artifacts
                    self.state.completed_stages.append(stage)

                    stage_duration = (datetime.now() - self.state.stage_start_time).total_seconds()
                    logger.info(f"ШАГ {stage.value + 4}. Этап {stage.name} завершен за {stage_duration:.1f}с")

                    await emit_sse("stage", {
                        "stage": stage.name,
                        "status": "completed",
                        "label": stage_labels.get(stage, stage.name),
                        "index": stage.value,
                        "duration": round(stage_duration, 1),
                        "artifacts": [Path(a).name for a in artifacts] if artifacts else [],
                    })
                    
                    # Сохраняем промежуточное состояние
                    await self._save_pipeline_state()
                    
                except Exception as e:
                    error_info = {
                        'stage': stage.name,
                        'error': str(e),
                        'traceback': traceback.format_exc(),
                        'timestamp': datetime.now().isoformat()
                    }
                    self.state.errors.append(error_info)
                    
                    logger.error(f"ШАГ {stage.value + 4}. ОШИБКА на этапе {stage.name}: {e}")

                    await emit_sse("error", {
                        "stage": stage.name,
                        "message": str(e),
                    })

                    if stage in [PipelineStage.ROLE_FRAMING, PipelineStage.RESEARCH_INGESTION]:
                        # Критические этапы - прерываем
                        logger.error(f"ШАГ {stage.value + 4}. Критическая ошибка, останавливаем pipeline")
                        raise
                    else:
                        # Некритические этапы - продолжаем с предупреждением
                        logger.warning(f"ШАГ {stage.value + 4}. Некритическая ошибка, продолжаем pipeline")
                        continue
            
            # Генерируем итоговый отчет
            final_report = await self._generate_final_report()
            
            total_duration = (datetime.now() - self.state.start_time).total_seconds()
            logger.info(f"ШАГ 11. Pipeline завершен за {total_duration:.1f}с")

            await emit_sse("done", {
                "success": True,
                "duration": round(total_duration, 1),
                "artifacts_count": sum(len(a) for a in self.state.artifacts_created.values()),
            })

            return {
                'success': True,
                'duration_seconds': total_duration,
                'completed_stages': [s.name for s in self.state.completed_stages],
                'artifacts': dict(self.state.artifacts_created),
                'errors': self.state.errors,
                'final_report': final_report
            }
            
        except Exception as e:
            logger.error(f"ШАГ ERROR. Фатальная ошибка pipeline: {e}")
            logger.error(f"ШАГ ERROR. Traceback: {traceback.format_exc()}")
            
            return {
                'success': False,
                'error': str(e),
                'duration_seconds': (datetime.now() - self.state.start_time).total_seconds(),
                'completed_stages': [s.name for s in self.state.completed_stages],
                'artifacts': dict(self.state.artifacts_created),
                'errors': self.state.errors
            }
    
    def _get_stages_to_run(self) -> List[PipelineStage]:
        """Определение этапов для выполнения"""
        all_stages = list(PipelineStage)
        
        if self.config.resume_from_stage:
            # Запуск с определенного этапа
            start_index = all_stages.index(self.config.resume_from_stage)
            return all_stages[start_index:]
        else:
            # Полный запуск
            return all_stages
    
    async def _stage_0_role_framing(self) -> List[str]:
        """Stage 0: Role framing -> role_scope.md (LLM-анализ роли)"""
        from .llm_helpers import call_llm

        logger.info("ШАГ STAGE0.1. Этап 0 - Role framing")

        if not self.config.role_scope.strip():
            raise ValueError("Не указана целевая роль (role_scope). Невозможно продолжить pipeline.")

        role_scope_path = self.artifacts_dir / "role_scope.md"

        # LLM-анализ роли
        framing_prompt = f"""Ты — эксперт в области профессиональных стандартов и образовательных программ.

Целевая роль: **{self.config.role_scope}**

Проведи детальный анализ этой роли и создай документ Role Scope в формате markdown.
ВАЖНО: Пиши ответ напрямую в markdown, НЕ оборачивай в блок кода (```).
Документ должен содержать:

## Целевая роль
Полное название и краткое описание (2-3 предложения).

## Альтернативные названия (title-синонимы)
Список из 5-10 синонимов этой роли на русском и английском.

## Уровень подготовки
Какой уровень образования и опыта обычно требуется (бакалавриат, магистратура, PhD).

## Отраслевой контекст
В каких отраслях и доменах работает специалист.

## Ключевые домены деятельности
Основные 5-7 направлений профессиональной деятельности.

## Исключения смежных ролей
Какие роли НЕ входят в scope (чтобы не смешивать).

## Гипотезы для поиска
Сформулируй 5-7 поисковых гипотез для Stage 1 (Research Ingestion):
- Какие запросы дадут лучшие результаты для вакансий?
- Какие академические термины помогут в поиске статей?
- Какие ключевые слова для поиска образовательных программ?

## Региональный контекст
Международный и российский рынок — особенности.
"""

        llm_response = await call_llm(framing_prompt, temperature=0.3, max_output_tokens=2000)

        # Убираем markdown code fences если LLM обернул ответ
        if llm_response:
            llm_response = llm_response.strip()
            if llm_response.startswith('```'):
                lines = llm_response.split('\n')
                # Убираем первую строку (```markdown) и последнюю (```)
                if lines[-1].strip() == '```':
                    lines = lines[1:-1]
                else:
                    lines = lines[1:]
                llm_response = '\n'.join(lines).strip()

        if llm_response:
            role_content = f"""# Role Scope Definition

**Дата создания:** {datetime.now().isoformat()}
**Pipeline версия:** Competency Intelligence v1.0
**Целевая роль:** {self.config.role_scope}

---

{llm_response}

---

*Документ создан Competency Pipeline Orchestrator с использованием LLM-анализа*
"""
        else:
            # Fallback — статический шаблон
            logger.warning("ШАГ STAGE0. LLM не ответил, используем статический шаблон")
            role_content = f"""# Role Scope Definition

**Дата создания:** {datetime.now().isoformat()}
**Pipeline версия:** Competency Intelligence v1.0

---

## Целевая роль

**{self.config.role_scope}**

## Описание роли

Роль определяет границы анализа компетенций для образовательной программы.

---

*Документ создан автоматически (fallback)*
"""

        role_scope_path.write_text(role_content, encoding='utf-8')

        logger.info("ШАГ STAGE0.2. Этап 0 завершен - role_scope.md создан")
        return [str(role_scope_path)]
    
    async def _stage_1_research_ingestion(self) -> List[str]:
        """Stage 1: Research ingestion -> raw_corpus/, manifest, registry"""
        logger.info("ШАГ STAGE1.1. Этап 1 - Research ingestion")
        
        # Используем конфигурацию источников или создаем дефолтную
        if not self.config.source_specifications:
            logger.info("ШАГ STAGE1.2. Создаем дефолтную конфигурацию источников")
            self.config.source_specifications = self._create_default_source_specs()
        
        # Запускаем сбор источников
        artifacts = await self.research_service.collect_sources(
            role_scope=self.config.role_scope,
            source_specs=self.config.source_specifications
        )
        
        logger.info(f"ШАГ STAGE1.3. Собрано {len(artifacts)} источников")
        
        # Сохраняем артефакты
        saved_files = await self.research_service.save_artifacts(
            artifacts=artifacts,
            role_scope=self.config.role_scope
        )
        
        logger.info(f"ШАГ STAGE1.4. Этап 1 завершен - {len(saved_files)} файлов создано")
        return list(saved_files.values())
    
    def _create_default_source_specs(self) -> List[SourceSpec]:
        """Создание дефолтной конфигурации источников"""
        return [
            SourceSpec(
                source_type='web_search',
                query=f"{self.config.role_scope} professional requirements skills",
                limit=20,
                priority='high'
            ),
            SourceSpec(
                source_type='hh_vacancies', 
                query=self.config.role_scope,
                limit=15,
                priority='high'
            ),
            SourceSpec(
                source_type='semantic_scholar',
                query=f"{self.config.role_scope} competencies education",
                limit=10,
                priority='medium'
            ),
            SourceSpec(
                source_type='linkedin',
                query=f"{self.config.role_scope} jobs career",
                limit=10,
                priority='medium'
            ),
            SourceSpec(
                source_type='telegram',
                query=f"{self.config.role_scope} career",
                limit=5,
                priority='low'
            )
        ]
    
    async def _stage_2_evidence_synthesis(self) -> List[str]:
        """Stage 2: Evidence synthesis -> Evidence.md"""
        logger.info("ШАГ STAGE2.1. Этап 2 - Evidence synthesis")
        
        evidence_path = await self.evidence_service.synthesize_evidence(
            role_scope=self.config.role_scope
        )
        
        logger.info("ШАГ STAGE2.2. Этап 2 завершен - Evidence.md создан")
        return [evidence_path]
    
    async def _stage_3_competency_profile(self) -> List[str]:
        """Stage 3: Competency profile generation -> Competency_Profile.md"""
        logger.info("ШАГ STAGE3.1. Этап 3 - Competency profile generation")
        
        profile_path = await self.competency_service.generate_competency_profile(
            role_scope=self.config.role_scope
        )
        
        logger.info("ШАГ STAGE3.2. Этап 3 завершен - Competency_Profile.md создан")
        return [profile_path]
    
    async def _stage_4_program_blueprint(self) -> List[str]:
        """Stage 4: Program blueprint generation -> Program_Blueprint.md"""
        logger.info("ШАГ STAGE4.1. Этап 4 - Program blueprint generation")
        
        blueprint_path = await self.curriculum_service.generate_curriculum(
            role_scope=self.config.role_scope,
            program_duration_semesters=self.config.program_duration_semesters
        )
        
        logger.info("ШАГ STAGE4.2. Этап 4 завершен - Program_Blueprint.md создан")
        return [blueprint_path]
    
    async def _stage_5_curriculum_table(self) -> List[str]:
        """Stage 5: Curriculum table generation -> Curriculum_Table.md"""
        from .llm_helpers import call_llm

        logger.info("ШАГ STAGE5.1. Этап 5 - Curriculum table generation")

        curriculum_table_path = self.artifacts_dir / "Curriculum_Table.md"
        competency_matrix_path = self.artifacts_dir / "Competency_matrix.md"

        # Если файлы уже созданы Stage 4 — валидируем
        if curriculum_table_path.exists():
            logger.info("ШАГ STAGE5.2. Curriculum_Table.md уже существует (создан Stage 4)")
        else:
            # Генерируем из Program_Blueprint.md
            blueprint_path = self.artifacts_dir / "Program_Blueprint.md"
            if blueprint_path.exists():
                blueprint_content = blueprint_path.read_text(encoding='utf-8')

                table_prompt = f"""На основе Program Blueprint создай детальный учебный план (Curriculum Table).

Program Blueprint:
{blueprint_content[:4000]}

Для каждой дисциплины укажи:
| Дисциплина | Семестр | Часы | Кредиты | Лекции | Практики | СРС | Форма контроля | Компетенции |

Для каждой практики укажи:
| Практика | Семестр | Часы | Кредиты | Результаты | Артефакты | Критерии оценки |

Создай полноценные таблицы в markdown."""

                response = await call_llm(table_prompt, temperature=0.2, max_output_tokens=3000)

                if response:
                    table_content = f"""# Curriculum Table

**Целевая роль:** {self.config.role_scope}
**Дата создания:** {datetime.now().isoformat()}

---

{response}

---

*Создано Competency Pipeline, Stage 5*
"""
                    curriculum_table_path.write_text(table_content, encoding='utf-8')
                    logger.info("ШАГ STAGE5.2. Curriculum_Table.md сгенерирован из Blueprint")
            else:
                logger.warning("ШАГ STAGE5.2. Program_Blueprint.md не найден, пропускаем генерацию таблицы")

        created_files = []
        if curriculum_table_path.exists():
            created_files.append(str(curriculum_table_path))
        if competency_matrix_path.exists():
            created_files.append(str(competency_matrix_path))

        logger.info(f"ШАГ STAGE5.3. Этап 5 завершен — {len(created_files)} файлов")
        return created_files
    
    async def _stage_6_review_correction(self) -> List[str]:
        """Stage 6: Review and correction -> Review_Notes.md"""
        logger.info("ШАГ STAGE6.1. Этап 6 - Review and correction")
        
        review_path = await self.review_service.conduct_program_review(
            role_scope=self.config.role_scope
        )
        
        logger.info("ШАГ STAGE6.2. Этап 6 завершен - Review_Notes.md создан")
        return [review_path]
    
    async def _save_pipeline_config(self) -> None:
        """Сохранение конфигурации pipeline"""
        config_path = self.artifacts_dir / "pipeline_config.json"
        
        config_data = {
            'role_scope': self.config.role_scope,
            'program_duration_semesters': self.config.program_duration_semesters,
            'artifacts_dir': self.config.artifacts_dir,
            'source_specifications': [
                {
                    'source_type': spec.source_type,
                    'query': spec.query,
                    'filters': spec.filters,
                    'limit': spec.limit,
                    'priority': spec.priority
                }
                for spec in self.config.source_specifications
            ],
            'skip_stages': [stage.name for stage in self.config.skip_stages],
            'resume_from_stage': self.config.resume_from_stage.name if self.config.resume_from_stage else None,
            'created_at': self.state.start_time.isoformat()
        }
        
        config_path.write_text(json.dumps(config_data, indent=2, ensure_ascii=False), encoding='utf-8')
    
    async def _save_pipeline_state(self) -> None:
        """Сохранение текущего состояния pipeline"""
        state_path = self.artifacts_dir / "pipeline_state.json"
        
        state_data = {
            'current_stage': self.state.current_stage.name,
            'completed_stages': [stage.name for stage in self.state.completed_stages],
            'artifacts_created': {
                stage.name: artifacts for stage, artifacts in self.state.artifacts_created.items()
            },
            'errors': self.state.errors,
            'start_time': self.state.start_time.isoformat(),
            'last_update': datetime.now().isoformat()
        }
        
        state_path.write_text(json.dumps(state_data, indent=2, ensure_ascii=False), encoding='utf-8')
    
    async def _generate_final_report(self) -> str:
        """Генерация итогового отчета pipeline"""
        logger.info("ШАГ REPORT.1. Генерация итогового отчета")
        
        report_path = self.artifacts_dir / "Pipeline_Report.md"
        
        total_duration = (datetime.now() - self.state.start_time).total_seconds()
        
        report_content = f"""# Competency Pipeline Report

**Целевая роль:** {self.config.role_scope}
**Дата выполнения:** {datetime.now().isoformat()}
**Общая продолжительность:** {total_duration:.1f} секунд

---

## Обзор выполнения

Pipeline успешно прошел **{len(self.state.completed_stages)} из 7** этапов.

### Выполненные этапы

"""
        
        stage_names = {
            PipelineStage.ROLE_FRAMING: "Role framing",
            PipelineStage.RESEARCH_INGESTION: "Research ingestion", 
            PipelineStage.EVIDENCE_SYNTHESIS: "Evidence synthesis",
            PipelineStage.COMPETENCY_PROFILE: "Competency profile generation",
            PipelineStage.PROGRAM_BLUEPRINT: "Program blueprint generation",
            PipelineStage.CURRICULUM_TABLE: "Curriculum table generation",
            PipelineStage.REVIEW_CORRECTION: "Review and correction"
        }
        
        for i, stage in enumerate(self.state.completed_stages, 1):
            stage_name = stage_names.get(stage, stage.name)
            artifacts = self.state.artifacts_created.get(stage, [])
            
            report_content += f"**{i}. {stage_name}** ✅\n"
            if artifacts:
                report_content += f"   - Создано артефактов: {len(artifacts)}\n"
                for artifact in artifacts[:3]:  # Показываем первые 3
                    artifact_name = Path(artifact).name
                    report_content += f"   - `{artifact_name}`\n"
                if len(artifacts) > 3:
                    report_content += f"   - ... и еще {len(artifacts) - 3} файлов\n"
            report_content += "\n"
        
        # Ошибки
        if self.state.errors:
            report_content += f"### Ошибки и предупреждения ({len(self.state.errors)})\n\n"
            for error in self.state.errors:
                report_content += f"- **{error['stage']}:** {error['error']}\n"
        
        # Основные результаты
        report_content += """
## Основные результаты

Pipeline создал следующие ключевые артефакты:

"""
        
        key_artifacts = [
            "role_scope.md",
            "raw_corpus_manifest.md", 
            "Evidence.md",
            "Competency_Profile.md",
            "Program_Blueprint.md",
            "Curriculum_Table.md",
            "Competency_matrix.md", 
            "Review_Notes.md"
        ]
        
        for artifact in key_artifacts:
            artifact_path = self.artifacts_dir / artifact
            if artifact_path.exists():
                size_kb = artifact_path.stat().st_size / 1024
                report_content += f"- ✅ **{artifact}** ({size_kb:.1f} KB)\n"
            else:
                report_content += f"- ❌ **{artifact}** (не создан)\n"
        
        # Следующие шаги
        report_content += f"""

## Следующие шаги

1. **Изучите Review_Notes.md** - содержит экспертную оценку программы
2. **Проанализируйте Competency_matrix.md** - проверьте покрытие компетенций
3. **Доработайте программу** согласно рекомендациям
4. **Проведите повторную проверку** при необходимости

## Метрики выполнения

- **Успешность:** {len(self.state.completed_stages)}/7 этапов
- **Время выполнения:** {total_duration:.1f} секунд  
- **Создано файлов:** {sum(len(artifacts) for artifacts in self.state.artifacts_created.values())}
- **Ошибок:** {len(self.state.errors)}

---

*Отчет сгенерирован автоматически Competency Pipeline Orchestrator*
"""
        
        report_path.write_text(report_content, encoding='utf-8')
        
        logger.info("ШАГ REPORT.2. Итоговый отчет создан")
        return str(report_path)

# Вспомогательные функции для удобства использования

async def run_full_pipeline(role_scope: str, 
                           artifacts_dir: str = "./artifacts",
                           program_duration_semesters: int = 4,
                           source_specs: Optional[List[SourceSpec]] = None) -> Dict[str, Any]:
    """
    Запуск полного pipeline с минимальной конфигурацией
    
    Args:
        role_scope: Описание целевой роли
        artifacts_dir: Директория для артефактов
        program_duration_semesters: Длительность программы
        source_specs: Спецификации источников (опционально)
    
    Returns:
        Результат выполнения pipeline
    """
    config = PipelineConfig(
        role_scope=role_scope,
        artifacts_dir=artifacts_dir,
        program_duration_semesters=program_duration_semesters,
        source_specifications=source_specs or []
    )
    
    orchestrator = CompetencyPipelineOrchestrator(config)
    return await orchestrator.run_pipeline()

async def resume_pipeline_from_stage(stage: PipelineStage,
                                    role_scope: str,
                                    artifacts_dir: str = "./artifacts") -> Dict[str, Any]:
    """
    Возобновление pipeline с определенного этапа
    
    Args:
        stage: Этап для возобновления
        role_scope: Описание целевой роли
        artifacts_dir: Директория с существующими артефактами
    
    Returns:
        Результат выполнения pipeline
    """
    config = PipelineConfig(
        role_scope=role_scope,
        artifacts_dir=artifacts_dir,
        resume_from_stage=stage
    )
    
    orchestrator = CompetencyPipelineOrchestrator(config)
    return await orchestrator.run_pipeline()

def create_source_specs_for_role(role_scope: str) -> List[SourceSpec]:
    """
    Создание оптимальных спецификаций источников для роли
    
    Args:
        role_scope: Описание роли
    
    Returns:
        Список спецификаций источников
    """
    return [
        # Высокоприоритетные источники
        SourceSpec(
            source_type='web_search',
            query=f"{role_scope} job requirements skills competencies",
            limit=25,
            priority='high'
        ),
        SourceSpec(
            source_type='hh_vacancies',
            query=role_scope,
            limit=20,
            priority='high'
        ),
        
        # Среднеприоритетные источники
        SourceSpec(
            source_type='semantic_scholar',
            query=f"{role_scope} education curriculum competency-based",
            limit=15,
            priority='medium'
        ),
        SourceSpec(
            source_type='linkedin',
            query=f"{role_scope} professional skills",
            limit=15,
            priority='medium'
        ),
        SourceSpec(
            source_type='web_search',
            query=f"{role_scope} university program curriculum",
            limit=15,
            priority='medium'
        ),
        
        # Дополнительные источники
        SourceSpec(
            source_type='telegram',
            query=f"{role_scope} career development",
            limit=10,
            priority='low'
        ),
        SourceSpec(
            source_type='reddit',
            query=f"{role_scope} career skills requirements",
            limit=15,
            priority='low'
        )
    ]
