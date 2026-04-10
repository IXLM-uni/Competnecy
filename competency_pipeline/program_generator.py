# -*- coding: utf-8 -*-
"""
Stage 3: Генерация программы из competencies.csv → program.md + curriculum.csv

Один LLM-вызов: читает компетенции, генерирует два документа.
"""

import logging
from datetime import datetime
from pathlib import Path

from .llm_helpers import call_llm, emit_sse

logger = logging.getLogger(__name__)


class ProgramGenerator:
    def __init__(self, artifacts_dir: str = "./artifacts"):
        self.artifacts_dir = Path(artifacts_dir)

    async def generate_program(self, role_scope: str, semesters: int = 4) -> str:
        """Stage 3: competencies.csv → program.md + curriculum.csv"""
        csv_path = self.artifacts_dir / "competencies.csv"
        if not csv_path.exists():
            raise FileNotFoundError(f"competencies.csv не найден: {csv_path}")

        competencies_csv = csv_path.read_text(encoding="utf-8")
        lines = [l for l in competencies_csv.strip().split("\n") if l.strip()]
        total_competencies = len(lines) - 1  # minus header

        logger.info(f"ШАГ PROGRAM.1. Генерация программы для {role_scope} ({total_competencies} компетенций)")

        await emit_sse("stage", {"stage": "PROGRAM_GENERATION", "status": "started",
                                  "label": "Генерация программы", "index": 2})

        prompt = f"""На основе списка компетенций создай образовательную программу для роли "{role_scope}".
Длительность: {semesters} семестра.

Компетенции (CSV):
{competencies_csv}

Создай ДВА документа подряд, разделённых строкой "===CURRICULUM===":

ПЕРВЫЙ ДОКУМЕНТ — описательный markdown:
# Образовательная программа: {role_scope}

## Цель программы
[2-3 предложения]

## Профиль выпускника
[Что умеет выпускник, 5-7 пунктов]

## Модули программы
[3-5 модулей с кратким описанием]

## Практики и стажировки
[Виды практик, когда проводятся]

## Итоговая аттестация
[Формат]

===CURRICULUM===

ВТОРОЙ ДОКУМЕНТ — CSV таблица учебного плана, разделитель ";":
дисциплина;часы;тип;семестр;компетенции

Где тип = теория | практика | лаб | проект
Компетенции = номера строк из competencies.csv через запятую

Сгенерируй 15-25 дисциплин, распределённых по {semesters} семестрам.
Каждая дисциплина 36-108 часов. Суммарно ~2400 часов."""

        response = await call_llm(prompt, temperature=0.3, max_output_tokens=4096)

        if not response:
            logger.error("ШАГ PROGRAM.2. LLM не ответил")
            await emit_sse("error", {"stage": "PROGRAM_GENERATION", "message": "LLM не ответил"})
            return ""

        # Разделяем на два документа
        if "===CURRICULUM===" in response:
            parts = response.split("===CURRICULUM===", 1)
            program_md = parts[0].strip()
            curriculum_csv = parts[1].strip()
        else:
            # Fallback: ищем CSV-подобный блок
            program_md = response
            curriculum_csv = ""

        # Убираем markdown code fences из curriculum
        if curriculum_csv.startswith("```"):
            lines = curriculum_csv.split("\n")
            curriculum_csv = "\n".join(l for l in lines if not l.strip().startswith("```"))

        # Добавляем заголовок если нет
        if curriculum_csv and not curriculum_csv.startswith("дисциплина"):
            curriculum_csv = "дисциплина;часы;тип;семестр;компетенции\n" + curriculum_csv

        # Сохраняем
        program_path = self.artifacts_dir / "program.md"
        program_path.write_text(program_md, encoding="utf-8")

        curriculum_path = self.artifacts_dir / "curriculum.csv"
        if curriculum_csv:
            curriculum_path.write_text(curriculum_csv, encoding="utf-8")

        logger.info(f"ШАГ PROGRAM.2. Сохранено: program.md ({len(program_md)} chars), curriculum.csv ({len(curriculum_csv)} chars)")

        await emit_sse("stage", {"stage": "PROGRAM_GENERATION", "status": "completed",
                                  "label": "Генерация программы", "index": 2,
                                  "artifacts": ["program.md", "curriculum.csv"]})

        return str(program_path)
