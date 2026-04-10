# -*- coding: utf-8 -*-
"""
Stage 2: Извлечение компетенций из raw_corpus.md → competencies.csv

Параллельно обрабатывает каждый документ из corpus,
извлекает компетенции в CSV формате (тип;формулировка;источник).
"""

import asyncio
import logging
from datetime import datetime
from pathlib import Path
from typing import List, Tuple

from .llm_helpers import call_llm, emit_sse

logger = logging.getLogger(__name__)


class CompetencyExtractor:
    def __init__(self, artifacts_dir: str = "./artifacts"):
        self.artifacts_dir = Path(artifacts_dir)

    def _split_corpus(self, corpus_text: str) -> List[Tuple[str, str, str]]:
        """Разбивает corpus на документы. Возвращает [(source_type, title, content)]."""
        docs = []
        for block in corpus_text.split("\n===\n"):
            block = block.strip()
            if not block or len(block) < 50:
                continue
            # Parse header
            source_type = "unknown"
            title = "Unknown"
            url = ""
            content = block
            if block.startswith("---"):
                parts = block.split("---", 2)
                if len(parts) >= 3:
                    header = parts[1]
                    content = parts[2].strip()
                    for line in header.split("\n"):
                        if line.startswith("SOURCE:"):
                            source_type = line.split(":", 1)[1].strip()
                        elif line.startswith("TITLE:"):
                            title = line.split(":", 1)[1].strip()
                        elif line.startswith("URL:"):
                            url = line.split(":", 1)[1].strip()
            docs.append((source_type, title or url, content))
        return docs

    async def extract_competencies(self, role_scope: str) -> str:
        """Stage 2: извлечение компетенций из raw_corpus.md → competencies.csv"""
        corpus_path = self.artifacts_dir / "raw_corpus.md"
        if not corpus_path.exists():
            raise FileNotFoundError(f"raw_corpus.md не найден: {corpus_path}")

        corpus = corpus_path.read_text(encoding="utf-8")
        docs = self._split_corpus(corpus)
        logger.info(f"ШАГ EXTRACT.1. Разбит corpus: {len(docs)} документов")

        await emit_sse("stage", {"stage": "COMPETENCY_EXTRACTION", "status": "started",
                                  "label": "Извлечение компетенций", "index": 1})

        # Параллельное извлечение компетенций из каждого документа
        async def _extract_from_doc(source_type: str, title: str, content: str) -> str:
            prompt = f"""Из данного источника извлеки конкретные профессиональные компетенции для роли "{role_scope}".

Источник ({source_type}): {title}

Содержимое:
{content[:8000]}

Ответь СТРОГО в CSV формате, без заголовков, разделитель ";":
тип;формулировка;источник

Где тип = knowledge | skill | ability
Формулировка начинается с глагола: "знает...", "умеет...", "владеет..."
Источник = название или URL документа

Пример:
knowledge;знает методы гидрологического моделирования;hh.ru/vacancy/123
skill;умеет применять ГИС для анализа водных ресурсов;Reddit: Hydrology Career
ability;владеет навыками полевых измерений расхода воды;BLS.gov Hydrologists

Извлеки 5-15 компетенций. Только CSV строки, без пояснений."""

            response = await call_llm(prompt, temperature=0.1, max_output_tokens=1000)
            return response or ""

        tasks = [_extract_from_doc(st, title, content) for st, title, content in docs]
        results = await asyncio.gather(*tasks, return_exceptions=True)

        # Собираем CSV
        all_lines = ["тип;формулировка;источник"]
        seen = set()
        for result in results:
            if isinstance(result, str):
                for line in result.strip().split("\n"):
                    line = line.strip()
                    if ";" in line and line.count(";") >= 2:
                        # Убираем маркеры списка
                        line = line.lstrip("- •*")
                        if line not in seen:
                            seen.add(line)
                            all_lines.append(line)

        # Сохраняем
        csv_path = self.artifacts_dir / "competencies.csv"
        csv_path.write_text("\n".join(all_lines), encoding="utf-8")

        # Summary
        knowledge = sum(1 for l in all_lines[1:] if l.startswith("knowledge"))
        skill = sum(1 for l in all_lines[1:] if l.startswith("skill"))
        ability = sum(1 for l in all_lines[1:] if l.startswith("ability"))
        total = len(all_lines) - 1

        summary_path = self.artifacts_dir / "competencies_summary.md"
        summary_path.write_text(f"""# Competencies Summary

**Роль:** {role_scope}
**Дата:** {datetime.now().isoformat()}
**Всего компетенций:** {total}

- **knowledge:** {knowledge}
- **skill:** {skill}
- **ability:** {ability}

Источников обработано: {len(docs)}
""", encoding="utf-8")

        logger.info(f"ШАГ EXTRACT.2. Извлечено {total} компетенций ({knowledge}K/{skill}S/{ability}A)")

        await emit_sse("stage", {"stage": "COMPETENCY_EXTRACTION", "status": "completed",
                                  "label": "Извлечение компетенций", "index": 1,
                                  "artifacts": ["competencies.csv", "competencies_summary.md"]})

        return str(csv_path)
