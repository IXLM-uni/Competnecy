"""
EVIDENCE SYNTHESIS SERVICE

Ответственность:
- Анализ корпуса источников из research_ingestion
- Синтез единого Evidence.md документа 
- Извлечение структурированной информации о деятельности
- Сохранение связности с источниками (traceability)

Процесс синтеза:
1. Source-by-source extraction - извлечение фактов из каждого источника
2. Cross-source consolidation - объединение и дедупликация  
3. Conflict detection - выявление противоречий
4. Final synthesis - сборка финального Evidence.md

Принципы:
- Markdown-to-markdown преобразование (НЕ JSON-first)
- Фактологический подход (источники -> факты -> синтез)
- Traceability (каждый вывод связан с источниками)
- Структурированность без потери контекста

Выход:
- Evidence.md - структурированный анализ деятельности
- Evidence_sources_mapping.md - связь выводов с источниками  
- Evidence_conflicts.md - выявленные противоречия
"""

import asyncio
import logging
import json
import re
from datetime import datetime
from pathlib import Path
from dataclasses import dataclass
from typing import List, Dict, Optional, Any, Tuple

from .llm_helpers import init_env, get_llm_client, call_llm

logger = logging.getLogger(__name__)

@dataclass
class SourceFacts:
    """Факты, извлеченные из одного источника"""
    source_id: str
    source_title: str
    core_role_description: str
    key_activities: List[str]
    knowledge_areas: List[str]
    skills_and_abilities: List[str]
    tools_and_technologies: List[str]
    work_artifacts: List[str]
    quality_criteria: List[str]
    work_contexts: List[str]
    typical_errors_risks: List[str]
    role_interactions: List[str]
    source_strength: str  # 'high', 'medium', 'low'

@dataclass
class EvidenceBlock:
    """Блок синтезированных доказательств"""
    category: str
    content: str
    source_ids: List[str]
    confidence: str  # 'high', 'medium', 'low'
    conflicts: Optional[str] = None

class EvidenceSynthesisService:
    """
    Сервис синтеза доказательств из корпуса источников
    """
    
    def __init__(self, artifacts_dir: str = "./artifacts"):
        """
        Инициализация сервиса
        
        Args:
            artifacts_dir: Директория с артефактами pipeline
        """
        logger.info("ШАГ 1. Инициализация EvidenceSynthesisService")

        self.artifacts_dir = Path(artifacts_dir)
        self.raw_corpus_dir = self.artifacts_dir / "raw_corpus"

        self.env_config = init_env()
        self.llm_client = get_llm_client()

        logger.info("ШАГ 2. Инициализация клиентов завершена")
    
    async def synthesize_evidence(self, role_scope: str) -> str:
        """
        Основной метод синтеза доказательств
        
        Args:
            role_scope: Описание целевой роли
            
        Returns:
            Путь к созданному Evidence.md
        """
        logger.info(f"ШАГ 3. Начинаем синтез evidence для роли: {role_scope[:100]}...")
        
        # Загружаем корпус источников
        source_files = await self._load_corpus_sources()
        logger.info(f"ШАГ 4. Загружено {len(source_files)} источников")
        
        # Извлекаем факты из каждого источника
        all_facts = []
        for i, source_file in enumerate(source_files, 1):
            logger.info(f"ШАГ 5.{i}. Извлекаем факты из источника: {source_file.name}")
            
            try:
                facts = await self._extract_facts_from_source(source_file, role_scope)
                all_facts.append(facts)
                logger.info(f"ШАГ 5.{i}. Извлечено {len(facts.key_activities)} активностей, {len(facts.knowledge_areas)} знаний")
            except Exception as e:
                logger.error(f"ШАГ 5.{i}. Ошибка обработки источника {source_file.name}: {e}")
                continue
        
        logger.info(f"ШАГ 6. Извлечены факты из {len(all_facts)} источников")
        
        # Консолидируем и дедуплицируем
        consolidated_facts = await self._consolidate_facts(all_facts, role_scope)
        logger.info("ШАГ 7. Консолидация фактов завершена")
        
        # Выявляем конфликты
        conflicts = await self._detect_conflicts(all_facts, role_scope)
        logger.info(f"ШАГ 8. Выявлено {len(conflicts)} потенциальных конфликтов")
        
        # Синтезируем финальный Evidence.md
        evidence_blocks = await self._synthesize_final_evidence(consolidated_facts, conflicts, role_scope)
        logger.info(f"ШАГ 9. Синтезировано {len(evidence_blocks)} блоков evidence")
        
        # Сохраняем результаты
        evidence_path = await self._save_evidence_artifacts(evidence_blocks, conflicts, all_facts, role_scope)
        logger.info(f"ШАГ 10. Evidence сохранен: {evidence_path}")
        
        return str(evidence_path)
    
    async def _load_corpus_sources(self) -> List[Path]:
        """Загрузка файлов корпуса"""
        if not self.raw_corpus_dir.exists():
            raise FileNotFoundError(f"Корпус источников не найден: {self.raw_corpus_dir}")
            
        source_files = list(self.raw_corpus_dir.glob("*.md"))
        
        # Исключаем служебные файлы
        source_files = [f for f in source_files if not f.name.startswith(('manifest', 'registry', 'index'))]
        
        return sorted(source_files)
    
    async def _extract_facts_from_source(self, source_file: Path, role_scope: str) -> SourceFacts:
        """Извлечение фактов из одного источника"""
        
        # Читаем содержимое источника
        content = source_file.read_text(encoding='utf-8')
        
        # Извлекаем метаданные из frontmatter
        metadata = self._parse_frontmatter(content)
        source_id = metadata.get('source_id', source_file.stem)
        source_title = metadata.get('title', source_file.name)
        
        # Извлекаем основное содержимое (убираем frontmatter)
        content_lines = content.split('\n')
        content_start = 0
        if content.startswith('---'):
            for i, line in enumerate(content_lines[1:], 1):
                if line.strip() == '---':
                    content_start = i + 1
                    break
        main_content = '\n'.join(content_lines[content_start:])
        
        # LLM-извлечение структурированных фактов
        extraction_prompt = f"""
Роль для анализа: {role_scope}

Источник: {source_title}
Содержимое: {main_content[:3000]}...

Извлеки из этого источника структурированную информацию, отвечающую на каждый пункт. Если информации нет, напиши "Не указано".

ФОРМАТ ОТВЕТА (строго следуй структуре):

## ОПИСАНИЕ РОЛИ
[Как в источнике описывается суть роли/позиции]

## КЛЮЧЕВЫЕ АКТИВНОСТИ  
- [активность 1]
- [активность 2]
- [...]

## ОБЛАСТИ ЗНАНИЙ
- [область знаний 1]
- [область знаний 2] 
- [...]

## НАВЫКИ И УМЕНИЯ
- [навык 1]
- [умение 2]
- [...]

## ИНСТРУМЕНТЫ И ТЕХНОЛОГИИ
- [инструмент 1]
- [технология 2]
- [...]

## РАБОЧИЕ АРТЕФАКТЫ
- [что создается/производится в работе]
- [результаты деятельности]
- [...]

## КРИТЕРИИ КАЧЕСТВА
- [как оценивается качество работы]
- [критерии успешности]
- [...]

## КОНТЕКСТЫ РАБОТЫ
- [в каких условиях выполняется работа]
- [организационные контексты]
- [...]

## ТИПИЧНЫЕ ОШИБКИ И РИСКИ
- [частые ошибки]
- [профессиональные риски]
- [...]

## ВЗАИМОДЕЙСТВИЕ С РОЛЯМИ
- [с кем взаимодействует]
- [характер взаимодействия]
- [...]

## СИЛА ИСТОЧНИКА
[HIGH/MEDIUM/LOW - оцени надежность и полноту этого источника для понимания роли]
"""

        try:
            response = await call_llm(extraction_prompt, temperature=0.1, max_output_tokens=2000)
            
            # Парсим структурированный ответ
            facts = self._parse_extraction_response(response, source_id, source_title)
            return facts
            
        except Exception as e:
            logger.error(f"Ошибка LLM-извлечения из {source_file.name}: {e}")
            
            # Fallback: создаем пустую структуру
            return SourceFacts(
                source_id=source_id,
                source_title=source_title,
                core_role_description="Извлечение не удалось",
                key_activities=[],
                knowledge_areas=[],
                skills_and_abilities=[],
                tools_and_technologies=[],
                work_artifacts=[],
                quality_criteria=[],
                work_contexts=[],
                typical_errors_risks=[],
                role_interactions=[],
                source_strength='low'
            )
    
    def _parse_frontmatter(self, content: str) -> Dict[str, Any]:
        """Парсинг YAML frontmatter"""
        if not content.startswith('---'):
            return {}
            
        try:
            lines = content.split('\n')
            frontmatter_lines = []
            
            for i, line in enumerate(lines[1:], 1):
                if line.strip() == '---':
                    break
                frontmatter_lines.append(line)
            
            # Простой парсинг ключ-значение (без полного YAML)
            metadata = {}
            for line in frontmatter_lines:
                if ':' in line:
                    key, value = line.split(':', 1)
                    metadata[key.strip()] = value.strip()
                    
            return metadata
        except:
            return {}
    
    def _parse_extraction_response(self, response: str, source_id: str, source_title: str) -> SourceFacts:
        """Парсинг структурированного ответа LLM"""
        
        def extract_section(text: str, section_name: str) -> str:
            pattern = f"## {section_name}\\n(.+?)(?=\\n## |$)"
            match = re.search(pattern, text, re.DOTALL | re.IGNORECASE)
            return match.group(1).strip() if match else "Не указано"
        
        def extract_list_items(text: str) -> List[str]:
            lines = text.split('\n')
            items = []
            for line in lines:
                line = line.strip()
                if line.startswith('- '):
                    items.append(line[2:].strip())
                elif line.startswith('* '):
                    items.append(line[2:].strip())
            return [item for item in items if item and item != "Не указано"]
        
        # Извлекаем секции
        role_desc = extract_section(response, "ОПИСАНИЕ РОЛИ")
        activities_text = extract_section(response, "КЛЮЧЕВЫЕ АКТИВНОСТИ")
        knowledge_text = extract_section(response, "ОБЛАСТИ ЗНАНИЙ")
        skills_text = extract_section(response, "НАВЫКИ И УМЕНИЯ")
        tools_text = extract_section(response, "ИНСТРУМЕНТЫ И ТЕХНОЛОГИИ")
        artifacts_text = extract_section(response, "РАБОЧИЕ АРТЕФАКТЫ")
        quality_text = extract_section(response, "КРИТЕРИИ КАЧЕСТВА")
        contexts_text = extract_section(response, "КОНТЕКСТЫ РАБОТЫ")
        errors_text = extract_section(response, "ТИПИЧНЫЕ ОШИБКИ И РИСКИ")
        interactions_text = extract_section(response, "ВЗАИМОДЕЙСТВИЕ С РОЛЯМИ")
        strength_text = extract_section(response, "СИЛА ИСТОЧНИКА")
        
        # Преобразуем в списки
        activities = extract_list_items(activities_text)
        knowledge = extract_list_items(knowledge_text)
        skills = extract_list_items(skills_text)
        tools = extract_list_items(tools_text)
        artifacts = extract_list_items(artifacts_text)
        quality = extract_list_items(quality_text)
        contexts = extract_list_items(contexts_text)
        errors = extract_list_items(errors_text)
        interactions = extract_list_items(interactions_text)
        
        # Определяем силу источника
        strength_text = strength_text.upper()
        if 'HIGH' in strength_text:
            strength = 'high'
        elif 'LOW' in strength_text:
            strength = 'low'
        else:
            strength = 'medium'
        
        return SourceFacts(
            source_id=source_id,
            source_title=source_title,
            core_role_description=role_desc,
            key_activities=activities,
            knowledge_areas=knowledge,
            skills_and_abilities=skills,
            tools_and_technologies=tools,
            work_artifacts=artifacts,
            quality_criteria=quality,
            work_contexts=contexts,
            typical_errors_risks=errors,
            role_interactions=interactions,
            source_strength=strength
        )
    
    async def _consolidate_facts(self, all_facts: List[SourceFacts], role_scope: str) -> Dict[str, List[str]]:
        """Консолидация и дедупликация фактов"""
        logger.info("ШАГ CONSOLIDATE.1. Начинаем консолидацию фактов")
        
        # Собираем все факты по категориям
        consolidated = {
            'core_descriptions': [],
            'activities': [],
            'knowledge': [],
            'skills': [],
            'tools': [],
            'artifacts': [],
            'quality': [],
            'contexts': [],
            'errors_risks': [],
            'interactions': []
        }
        
        for facts in all_facts:
            consolidated['core_descriptions'].append(facts.core_role_description)
            consolidated['activities'].extend(facts.key_activities)
            consolidated['knowledge'].extend(facts.knowledge_areas)
            consolidated['skills'].extend(facts.skills_and_abilities)
            consolidated['tools'].extend(facts.tools_and_technologies)
            consolidated['artifacts'].extend(facts.work_artifacts)
            consolidated['quality'].extend(facts.quality_criteria)
            consolidated['contexts'].extend(facts.work_contexts)
            consolidated['errors_risks'].extend(facts.typical_errors_risks)
            consolidated['interactions'].extend(facts.role_interactions)
        
        logger.info("ШАГ CONSOLIDATE.2. Собрано фактов по категориям")
        
        # LLM-дедупликация и группировка
        deduplicated = {}
        
        for category, items in consolidated.items():
            if not items:
                deduplicated[category] = []
                continue
                
            logger.info(f"ШАГ CONSOLIDATE.3. Дедупликация категории {category}: {len(items)} элементов")
            
            # Объединяем в текст для LLM
            items_text = '\n'.join([f"- {item}" for item in items if item.strip()])
            
            dedup_prompt = f"""
Роль: {role_scope}
Категория: {category}

Список фактов из разных источников:
{items_text}

Задача: Объедини и дедуплицируй этот список. Убери дубли и очень похожие пункты, но сохрани уникальную информацию.

Правила:
1. Объединяй синонимичные пункты в один  
2. Сохраняй специфичную информацию
3. Убирай общие фразы типа "знание основ"
4. Группируй логически связанные пункты
5. Максимум 15-20 итоговых пунктов

Формат ответа - список через дефис:
- пункт 1
- пункт 2
- ...
"""
            
            try:
                response = await call_llm(dedup_prompt, temperature=0.1, max_output_tokens=1000)
                
                # Извлекаем список
                dedup_items = []
                for line in response.split('\n'):
                    line = line.strip()
                    if line.startswith('- '):
                        dedup_items.append(line[2:].strip())
                
                deduplicated[category] = dedup_items
                logger.info(f"ШАГ CONSOLIDATE.4. Категория {category}: {len(dedup_items)} уникальных элементов")
                
            except Exception as e:
                logger.error(f"Ошибка дедупликации {category}: {e}")
                deduplicated[category] = items[:10]  # Fallback: берем первые 10
        
        logger.info("ШАГ CONSOLIDATE.5. Консолидация завершена")
        return deduplicated
    
    async def _detect_conflicts(self, all_facts: List[SourceFacts], role_scope: str) -> List[Dict[str, Any]]:
        """Выявление конфликтов между источниками"""
        logger.info("ШАГ CONFLICT.1. Поиск конфликтов между источниками")
        
        conflicts = []
        
        # Простая эвристика: сравниваем силу источников и противоречия
        high_strength_sources = [f for f in all_facts if f.source_strength == 'high']
        medium_strength_sources = [f for f in all_facts if f.source_strength == 'medium']
        
        if len(high_strength_sources) < 2:
            logger.info("ШАГ CONFLICT.2. Недостаточно надежных источников для сравнения")
            return conflicts
        
        # LLM-анализ противоречий в описаниях роли
        descriptions = [f.core_role_description for f in high_strength_sources if f.core_role_description != "Не указано"]
        
        if len(descriptions) >= 2:
            conflict_prompt = f"""
Роль для анализа: {role_scope}

Описания роли из разных источников:

{chr(10).join([f"Источник {i+1}: {desc}" for i, desc in enumerate(descriptions)])}

Есть ли между этими описаниями значимые противоречия? 

Если ДА, опиши конфликт в формате:
КОНФЛИКТ: [краткое описание]
ИСТОЧНИКИ: [какие источники]
СУТЬ: [в чем суть противоречия]

Если НЕТ, напиши: НЕТ ЗНАЧИМЫХ КОНФЛИКТОВ
"""
            
            try:
                response = await call_llm(conflict_prompt, temperature=0.1, max_output_tokens=500)
                
                if "НЕТ ЗНАЧИМЫХ КОНФЛИКТОВ" not in response.upper():
                    conflicts.append({
                        'category': 'role_description',
                        'description': response,
                        'sources': [f.source_title for f in high_strength_sources]
                    })
                    
            except Exception as e:
                logger.error(f"Ошибка анализа конфликтов: {e}")
        
        logger.info(f"ШАГ CONFLICT.3. Найдено {len(conflicts)} конфликтов")
        return conflicts
    
    async def _synthesize_final_evidence(self, consolidated_facts: Dict[str, List[str]], 
                                       conflicts: List[Dict[str, Any]], role_scope: str) -> List[EvidenceBlock]:
        """Синтез финального Evidence.md"""
        logger.info("ШАГ SYNTHESIS.1. Начинаем финальный синтез Evidence")
        
        evidence_blocks = []
        
        # Синтезируем каждую секцию Evidence.md
        sections = [
            ('role_core', 'Ядро роли', consolidated_facts['core_descriptions']),
            ('key_functions', 'Ключевые функции деятельности', consolidated_facts['activities']),
            ('knowledge_base', 'Базовые знания', consolidated_facts['knowledge']),
            ('skills_abilities', 'Умения и навыки', consolidated_facts['skills']),
            ('tools_tech', 'Инструменты и технологии', consolidated_facts['tools']),
            ('work_artifacts', 'Артефакты деятельности', consolidated_facts['artifacts']),
            ('quality_criteria', 'Критерии качества работы', consolidated_facts['quality']),
            ('work_contexts', 'Контексты выполнения работы', consolidated_facts['contexts']),
            ('errors_risks', 'Типичные ошибки и риски', consolidated_facts['errors_risks']),
            ('role_interactions', 'Взаимодействие с другими ролями', consolidated_facts['interactions'])
        ]
        
        for section_key, section_title, section_data in sections:
            logger.info(f"ШАГ SYNTHESIS.2. Синтез секции: {section_title}")
            
            if not section_data:
                continue
                
            synthesis_prompt = f"""
Роль: {role_scope}
Секция: {section_title}

Исходные факты из источников:
{chr(10).join([f"- {item}" for item in section_data if item.strip()])}

Задача: Синтезируй эти факты в связный, структурированный текст для секции "{section_title}" в документе Evidence.

Требования:
1. Сохрани всю важную информацию, но сделай текст связным
2. Группируй логически связанные элементы
3. Используй markdown-форматирование (заголовки, списки)
4. Пиши в повествовательном стиле, а не просто списком
5. Укажи ключевые моменты жирным шрифтом
6. Объем: 200-400 слов

Формат ответа - готовый markdown-текст для этой секции.
"""
            
            try:
                response = await call_llm(synthesis_prompt, temperature=0.2, max_output_tokens=800)
                
                evidence_block = EvidenceBlock(
                    category=section_key,
                    content=response.strip(),
                    source_ids=['consolidated'],  # TODO: добавить трекинг источников
                    confidence='medium'  # TODO: вычислять на основе качества источников
                )
                
                evidence_blocks.append(evidence_block)
                
            except Exception as e:
                logger.error(f"Ошибка синтеза секции {section_title}: {e}")
                continue
        
        logger.info(f"ШАГ SYNTHESIS.3. Синтезировано {len(evidence_blocks)} секций Evidence")
        return evidence_blocks
    
    async def _save_evidence_artifacts(self, evidence_blocks: List[EvidenceBlock], 
                                     conflicts: List[Dict[str, Any]], 
                                     all_facts: List[SourceFacts], 
                                     role_scope: str) -> Path:
        """Сохранение артефактов Evidence"""
        logger.info("ШАГ SAVE.1. Сохранение Evidence артефактов")
        
        # Основной Evidence.md
        evidence_path = self.artifacts_dir / "Evidence.md"
        
        evidence_content = f"""# Evidence Analysis

**Целевая роль:** {role_scope}
**Дата анализа:** {datetime.now().isoformat()}
**Источников проанализировано:** {len(all_facts)}

---

"""
        
        # Добавляем секции Evidence
        section_titles = {
            'role_core': '## Ядро роли',
            'key_functions': '## Ключевые функции деятельности', 
            'knowledge_base': '## Базовые знания',
            'skills_abilities': '## Умения и навыки',
            'tools_tech': '## Инструменты и технологии',
            'work_artifacts': '## Артефакты деятельности',
            'quality_criteria': '## Критерии качества работы',
            'work_contexts': '## Контексты выполнения работы',
            'errors_risks': '## Типичные ошибки и риски',
            'role_interactions': '## Взаимодействие с другими ролями'
        }
        
        for block in evidence_blocks:
            title = section_titles.get(block.category, f"## {block.category}")
            evidence_content += f"{title}\n\n{block.content}\n\n---\n\n"
        
        # Добавляем информацию о конфликтах
        if conflicts:
            evidence_content += "## Выявленные противоречия\n\n"
            for conflict in conflicts:
                evidence_content += f"**{conflict['category']}:** {conflict['description']}\n\n"
        
        evidence_path.write_text(evidence_content, encoding='utf-8')
        
        # Sources mapping
        mapping_path = self.artifacts_dir / "Evidence_sources_mapping.md"
        mapping_content = f"""# Evidence Sources Mapping

**Связь выводов Evidence.md с исходными источниками**

## Источники по силе

### Высокая надежность
"""
        
        high_sources = [f for f in all_facts if f.source_strength == 'high']
        for source in high_sources:
            mapping_content += f"- **{source.source_title}** (`{source.source_id}`)\n"
            
        mapping_content += "\n### Средняя надежность\n"
        medium_sources = [f for f in all_facts if f.source_strength == 'medium']
        for source in medium_sources:
            mapping_content += f"- **{source.source_title}** (`{source.source_id}`)\n"
        
        mapping_content += "\n### Низкая надежность\n"
        low_sources = [f for f in all_facts if f.source_strength == 'low']
        for source in low_sources:
            mapping_content += f"- **{source.source_title}** (`{source.source_id}`)\n"
            
        mapping_path.write_text(mapping_content, encoding='utf-8')
        
        # Conflicts detail
        if conflicts:
            conflicts_path = self.artifacts_dir / "Evidence_conflicts.md"
            conflicts_content = f"""# Evidence Conflicts

**Детальный анализ противоречий между источниками**

"""
            for i, conflict in enumerate(conflicts, 1):
                conflicts_content += f"## Конфликт {i}: {conflict['category']}\n\n"
                conflicts_content += f"{conflict['description']}\n\n"
                conflicts_content += f"**Затронутые источники:** {', '.join(conflict['sources'])}\n\n---\n\n"
                
            conflicts_path.write_text(conflicts_content, encoding='utf-8')
        
        logger.info(f"ШАГ SAVE.2. Evidence артефакты сохранены: {evidence_path}")
        return evidence_path
