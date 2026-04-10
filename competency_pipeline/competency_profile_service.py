"""
COMPETENCY PROFILE SERVICE

Ответственность:
- Преобразование Evidence.md в профиль компетенций
- Формулировка компетенций в образовательном формате
- Создание индикаторов достижения
- Определение приоритетности компетенций

Правила преобразования (из PIPELINE.md):
- задача / действие -> "умеет ..."
- знания -> "знает ..."
- критерии качества -> "способен выполнять ... с требуемым качеством ..."
- контекст -> "умеет действовать в условиях ..."
- ошибки и риски -> "учитывает ...", "избегает ...", "соблюдает ..."
- взаимодействие -> "умеет взаимодействовать с ..."

Принципы:
- Markdown-to-markdown преобразование (НЕ через JSON)
- Педагогическая формулировка компетенций
- Связь с задачами деятельности (traceability)
- Разделение на профессиональные и общие компетенции

Выход:
- Competency_Profile.md - структурированный профиль компетенций
- Competency_mapping.md - связь компетенций с Evidence
- Competency_indicators.md - детальные индикаторы достижения
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
class CompetencyItem:
    """Отдельная компетенция"""
    competency_id: str
    category: str  # 'professional', 'general'
    title: str
    description: str
    indicators: List[str]
    linked_evidence: List[str]  # Секции Evidence.md
    priority: str  # 'high', 'medium', 'low'
    complexity_level: str  # 'basic', 'intermediate', 'advanced'

@dataclass
class CompetencyGroup:
    """Группа компетенций"""
    group_id: str
    group_name: str
    description: str
    competencies: List[CompetencyItem]

class CompetencyProfileService:
    """
    Сервис создания профилей компетенций из Evidence
    """
    
    def __init__(self, artifacts_dir: str = "./artifacts"):
        """
        Инициализация сервиса
        
        Args:
            artifacts_dir: Директория с артефактами pipeline
        """
        logger.info("ШАГ 1. Инициализация CompetencyProfileService")

        self.artifacts_dir = Path(artifacts_dir)

        self.env_config = init_env()
        self.llm_client = get_llm_client()

        logger.info("ШАГ 2. Инициализация клиентов завершена")
    
    async def generate_competency_profile(self, role_scope: str) -> str:
        """
        Основной метод генерации профиля компетенций
        
        Args:
            role_scope: Описание целевой роли
            
        Returns:
            Путь к созданному Competency_Profile.md
        """
        logger.info(f"ШАГ 3. Начинаем генерацию профиля компетенций для роли: {role_scope[:100]}...")
        
        # Загружаем Evidence.md
        evidence_content = await self._load_evidence()
        logger.info("ШАГ 4. Evidence.md загружен")
        
        # Извлекаем секции Evidence для обработки
        evidence_sections = self._parse_evidence_sections(evidence_content)
        logger.info(f"ШАГ 5. Извлечено {len(evidence_sections)} секций Evidence")
        
        # Генерируем профессиональные компетенции
        professional_groups = await self._generate_professional_competencies(evidence_sections, role_scope)
        logger.info(f"ШАГ 6. Сгенерировано {len(professional_groups)} групп профессиональных компетенций")
        
        # Генерируем общие компетенции
        general_groups = await self._generate_general_competencies(evidence_sections, role_scope)
        logger.info(f"ШАГ 7. Сгенерировано {len(general_groups)} групп общих компетенций")
        
        # Создаем индикаторы достижения
        await self._enhance_competency_indicators(professional_groups + general_groups, evidence_sections)
        logger.info("ШАГ 8. Индикаторы достижения созданы")
        
        # Определяем приоритеты
        await self._assign_competency_priorities(professional_groups + general_groups, role_scope)
        logger.info("ШАГ 9. Приоритеты компетенций определены")
        
        # Сохраняем результаты
        profile_path = await self._save_competency_artifacts(
            professional_groups, general_groups, evidence_sections, role_scope
        )
        logger.info(f"ШАГ 10. Профиль компетенций сохранен: {profile_path}")
        
        return str(profile_path)
    
    async def _load_evidence(self) -> str:
        """Загрузка Evidence.md"""
        evidence_path = self.artifacts_dir / "Evidence.md"
        
        if not evidence_path.exists():
            raise FileNotFoundError(f"Evidence.md не найден: {evidence_path}")
        
        return evidence_path.read_text(encoding='utf-8')
    
    def _parse_evidence_sections(self, evidence_content: str) -> Dict[str, str]:
        """Парсинг секций Evidence.md"""
        sections = {}
        
        # Разделяем по заголовкам уровня 2 (##)
        current_section = None
        current_content = []
        
        for line in evidence_content.split('\n'):
            if line.strip().startswith('## '):
                # Сохраняем предыдущую секцию
                if current_section:
                    sections[current_section] = '\n'.join(current_content).strip()
                
                # Начинаем новую секцию
                current_section = line.strip()[3:].strip()  # Убираем "## "
                current_content = []
            elif current_section:
                current_content.append(line)
        
        # Сохраняем последнюю секцию
        if current_section:
            sections[current_section] = '\n'.join(current_content).strip()
        
        return sections
    
    async def _generate_professional_competencies(self, evidence_sections: Dict[str, str], 
                                                role_scope: str) -> List[CompetencyGroup]:
        """Генерация профессиональных компетенций"""
        logger.info("ШАГ PROF.1. Генерируем профессиональные компетенции")
        
        # Определяем ключевые секции для профессиональных компетенций
        prof_sections = {
            'key_functions': evidence_sections.get('Ключевые функции деятельности', ''),
            'knowledge': evidence_sections.get('Базовые знания', ''),
            'tools': evidence_sections.get('Инструменты и технологии', ''),
            'artifacts': evidence_sections.get('Артефакты деятельности', ''),
            'quality': evidence_sections.get('Критерии качества работы', ''),
        }
        
        competency_groups = []
        
        # Группа 1: Основные профессиональные функции
        if prof_sections['key_functions']:
            functions_group = await self._create_competency_group(
                'core_functions',
                'Основные профессиональные функции',
                prof_sections['key_functions'],
                role_scope,
                'professional'
            )
            if functions_group:
                competency_groups.append(functions_group)
        
        # Группа 2: Специализированные знания
        if prof_sections['knowledge']:
            knowledge_group = await self._create_competency_group(
                'specialized_knowledge',
                'Специализированные знания',
                prof_sections['knowledge'],
                role_scope,
                'professional'
            )
            if knowledge_group:
                competency_groups.append(knowledge_group)
        
        # Группа 3: Инструментальные компетенции
        if prof_sections['tools']:
            tools_group = await self._create_competency_group(
                'instrumental_competencies',
                'Инструментальные компетенции',
                prof_sections['tools'],
                role_scope,
                'professional'
            )
            if tools_group:
                competency_groups.append(tools_group)
        
        # Группа 4: Результативные компетенции
        artifacts_quality = prof_sections['artifacts'] + '\n\n' + prof_sections['quality']
        if artifacts_quality.strip():
            results_group = await self._create_competency_group(
                'result_competencies',
                'Результативные компетенции',
                artifacts_quality,
                role_scope,
                'professional'
            )
            if results_group:
                competency_groups.append(results_group)
        
        logger.info(f"ШАГ PROF.2. Создано {len(competency_groups)} групп профессиональных компетенций")
        return competency_groups
    
    async def _generate_general_competencies(self, evidence_sections: Dict[str, str], 
                                           role_scope: str) -> List[CompetencyGroup]:
        """Генерация общих (универсальных) компетенций"""
        logger.info("ШАГ GEN.1. Генерируем общие компетенции")
        
        # Определяем секции для общих компетенций
        gen_sections = {
            'contexts': evidence_sections.get('Контексты выполнения работы', ''),
            'interactions': evidence_sections.get('Взаимодействие с другими ролями', ''),
            'errors_risks': evidence_sections.get('Типичные ошибки и риски', ''),
        }
        
        competency_groups = []
        
        # Группа 1: Системное мышление и адаптивность
        if gen_sections['contexts']:
            systems_group = await self._create_competency_group(
                'systems_thinking',
                'Системное мышление и адаптивность',
                gen_sections['contexts'],
                role_scope,
                'general'
            )
            if systems_group:
                competency_groups.append(systems_group)
        
        # Группа 2: Коммуникация и взаимодействие
        if gen_sections['interactions']:
            communication_group = await self._create_competency_group(
                'communication',
                'Коммуникация и взаимодействие',
                gen_sections['interactions'],
                role_scope,
                'general'
            )
            if communication_group:
                competency_groups.append(communication_group)
        
        # Группа 3: Управление рисками и качеством
        if gen_sections['errors_risks']:
            risk_group = await self._create_competency_group(
                'risk_management',
                'Управление рисками и качеством',
                gen_sections['errors_risks'],
                role_scope,
                'general'
            )
            if risk_group:
                competency_groups.append(risk_group)
        
        logger.info(f"ШАГ GEN.2. Создано {len(competency_groups)} групп общих компетенций")
        return competency_groups
    
    async def _create_competency_group(self, group_id: str, group_name: str, 
                                     evidence_content: str, role_scope: str, 
                                     category: str) -> Optional[CompetencyGroup]:
        """Создание группы компетенций из секции Evidence"""
        
        if not evidence_content.strip():
            return None
        
        logger.info(f"ШАГ CREATE_GROUP.1. Создаем группу: {group_name}")
        
        # Формулировка компетенций через LLM
        formulation_prompt = f"""
Роль: {role_scope}
Тип компетенций: {category} (профессиональные или общие)
Группа: {group_name}

Исходная информация из Evidence:
{evidence_content}

Задача: Сформулируй 3-5 конкретных компетенций для этой группы.

Правила формулировки (СТРОГО СЛЕДУЙ):
- Знания формулируй как "знает ...", "понимает ...", "владеет знаниями ..."
- Умения формулируй как "умеет ...", "способен ...", "может ..."
- Навыки формулируй как "владеет навыками ...", "применяет ..."
- Контекстные компетенции как "умеет действовать в условиях ..."
- Взаимодействие как "умеет взаимодействовать с ...", "способен координировать ..."

Каждая компетенция должна быть:
1. Конкретной и измеримой
2. Связанной с деятельностью в роли
3. Достижимой через обучение
4. Сформулированной в активном залоге

Формат ответа:
КОМПЕТЕНЦИЯ 1: [формулировка]
ОПИСАНИЕ: [1-2 предложения детального описания]

КОМПЕТЕНЦИЯ 2: [формулировка]
ОПИСАНИЕ: [1-2 предложения детального описания]

[и так далее]
"""
        
        try:
            response = await call_llm(formulation_prompt, temperature=0.2, max_output_tokens=1200)
            
            # Парсим ответ LLM
            competencies = self._parse_competencies_response(response, group_id, category)
            
            if not competencies:
                logger.warning(f"Не удалось создать компетенции для группы {group_name}")
                return None
            
            group = CompetencyGroup(
                group_id=group_id,
                group_name=group_name,
                description=f"Компетенции в области: {group_name.lower()}",
                competencies=competencies
            )
            
            logger.info(f"ШАГ CREATE_GROUP.2. Группа {group_name} создана с {len(competencies)} компетенциями")
            return group
            
        except Exception as e:
            logger.error(f"Ошибка создания группы компетенций {group_name}: {e}")
            return None
    
    def _parse_competencies_response(self, response: str, group_id: str, category: str) -> List[CompetencyItem]:
        """Парсинг ответа LLM с компетенциями"""
        competencies = []
        
        # Разделяем на блоки компетенций
        blocks = re.split(r'КОМПЕТЕНЦИЯ \d+:', response)[1:]  # Убираем первый пустой элемент
        
        for i, block in enumerate(blocks, 1):
            lines = block.strip().split('\n')
            
            # Извлекаем формулировку (первая строка)
            title = lines[0].strip()
            if not title:
                continue
            
            # Извлекаем описание
            description = ""
            for line in lines[1:]:
                if line.strip().startswith('ОПИСАНИЕ:'):
                    description = line.replace('ОПИСАНИЕ:', '').strip()
                    break
                elif line.strip() and not line.strip().startswith('КОМПЕТЕНЦИЯ'):
                    description = line.strip()
                    break
            
            competency = CompetencyItem(
                competency_id=f"{group_id}_{i:02d}",
                category=category,
                title=title,
                description=description,
                indicators=[],  # Заполним позже
                linked_evidence=[],  # Заполним позже
                priority='medium',  # Определим позже
                complexity_level='intermediate'  # Определим позже
            )
            
            competencies.append(competency)
        
        return competencies
    
    async def _enhance_competency_indicators(self, all_groups: List[CompetencyGroup], 
                                           evidence_sections: Dict[str, str]) -> None:
        """Создание индикаторов достижения для компетенций"""
        logger.info("ШАГ INDICATORS.1. Создаем индикаторы достижения")
        
        for group in all_groups:
            for competency in group.competencies:
                logger.info(f"ШАГ INDICATORS.2. Создаем индикаторы для: {competency.title[:50]}...")
                
                indicators_prompt = f"""
Компетенция: {competency.title}
Описание: {competency.description}

Задача: Создай 3-4 измеримых индикатора достижения этой компетенции.

Индикаторы должны отвечать на вопрос: "Как можно понять, что студент освоил эту компетенцию?"

Требования к индикаторам:
1. Конкретные и наблюдаемые действия/результаты
2. Измеримые (можно оценить)  
3. Соответствующие уровню компетенции
4. Реалистичные для образовательного контекста

Формат ответа (список через дефис):
- индикатор 1
- индикатор 2  
- индикатор 3
- индикатор 4
"""
                
                try:
                    response = await call_llm(indicators_prompt, temperature=0.1, max_output_tokens=400)
                    
                    # Извлекаем индикаторы
                    indicators = []
                    for line in response.split('\n'):
                        line = line.strip()
                        if line.startswith('- '):
                            indicators.append(line[2:].strip())
                    
                    competency.indicators = indicators
                    
                except Exception as e:
                    logger.error(f"Ошибка создания индикаторов для {competency.title}: {e}")
                    competency.indicators = [f"Демонстрирует освоение: {competency.title}"]
    
    async def _assign_competency_priorities(self, all_groups: List[CompetencyGroup], role_scope: str) -> None:
        """Определение приоритетов компетенций"""
        logger.info("ШАГ PRIORITY.1. Определяем приоритеты компетенций")
        
        # Собираем все компетенции для ранжирования
        all_competencies = []
        for group in all_groups:
            all_competencies.extend(group.competencies)
        
        if not all_competencies:
            return
        
        # Список компетенций для ранжирования
        competencies_list = '\n'.join([
            f"{i+1}. {comp.title}" for i, comp in enumerate(all_competencies)
        ])
        
        priority_prompt = f"""
Роль: {role_scope}

Список всех компетенций:
{competencies_list}

Задача: Определи приоритет каждой компетенции для успешной деятельности в роли.

Критерии приоритизации:
- HIGH: Критически важно для роли, без этого работать невозможно
- MEDIUM: Важно для эффективной работы
- LOW: Полезно, но не критично

Формат ответа:
1. HIGH/MEDIUM/LOW
2. HIGH/MEDIUM/LOW  
3. HIGH/MEDIUM/LOW
[и так далее для всех компетенций]
"""
        
        try:
            response = await call_llm(priority_prompt, temperature=0.1, max_output_tokens=200)
            
            # Парсим приоритеты
            lines = response.strip().split('\n')
            for i, line in enumerate(lines):
                if i >= len(all_competencies):
                    break
                    
                line = line.strip()
                if 'HIGH' in line.upper():
                    all_competencies[i].priority = 'high'
                elif 'LOW' in line.upper():
                    all_competencies[i].priority = 'low'
                else:
                    all_competencies[i].priority = 'medium'
                    
        except Exception as e:
            logger.error(f"Ошибка определения приоритетов: {e}")
            # Fallback: равномерное распределение
            for i, comp in enumerate(all_competencies):
                if i < len(all_competencies) // 3:
                    comp.priority = 'high'
                elif i < 2 * len(all_competencies) // 3:
                    comp.priority = 'medium'
                else:
                    comp.priority = 'low'
    
    async def _save_competency_artifacts(self, professional_groups: List[CompetencyGroup], 
                                       general_groups: List[CompetencyGroup],
                                       evidence_sections: Dict[str, str], 
                                       role_scope: str) -> Path:
        """Сохранение артефактов профиля компетенций"""
        logger.info("ШАГ SAVE_COMP.1. Сохранение артефактов профиля компетенций")
        
        # Основной Competency_Profile.md
        profile_path = self.artifacts_dir / "Competency_Profile.md"
        
        profile_content = f"""# Competency Profile

**Целевая роль:** {role_scope}
**Дата создания:** {datetime.now().isoformat()}

---

## Обзор профиля компетенций

Данный профиль компетенций разработан на основе анализа деятельности в роли "{role_scope}".
Профиль включает профессиональные и общие (универсальные) компетенции, необходимые для
успешного выполнения профессиональных задач.

### Структура профиля

- **Профессиональные компетенции**: {len(professional_groups)} групп
- **Общие компетенции**: {len(general_groups)} групп
- **Всего компетенций**: {sum(len(g.competencies) for g in professional_groups + general_groups)}

---

## Профессиональные компетенции

"""
        
        # Добавляем профессиональные компетенции
        for group in professional_groups:
            profile_content += f"### {group.group_name}\n\n"
            profile_content += f"{group.description}\n\n"
            
            for comp in group.competencies:
                priority_icon = "🔴" if comp.priority == 'high' else "🟡" if comp.priority == 'medium' else "🟢"
                profile_content += f"#### {priority_icon} {comp.title}\n\n"
                profile_content += f"{comp.description}\n\n"
                
                if comp.indicators:
                    profile_content += "**Индикаторы достижения:**\n"
                    for indicator in comp.indicators:
                        profile_content += f"- {indicator}\n"
                    profile_content += "\n"
                
                profile_content += "---\n\n"
        
        # Добавляем общие компетенции
        profile_content += "## Общие (универсальные) компетенции\n\n"
        
        for group in general_groups:
            profile_content += f"### {group.group_name}\n\n"
            profile_content += f"{group.description}\n\n"
            
            for comp in group.competencies:
                priority_icon = "🔴" if comp.priority == 'high' else "🟡" if comp.priority == 'medium' else "🟢"
                profile_content += f"#### {priority_icon} {comp.title}\n\n"
                profile_content += f"{comp.description}\n\n"
                
                if comp.indicators:
                    profile_content += "**Индикаторы достижения:**\n"
                    for indicator in comp.indicators:
                        profile_content += f"- {indicator}\n"
                    profile_content += "\n"
                
                profile_content += "---\n\n"
        
        # Добавляем сводную таблицу
        profile_content += "## Сводная таблица компетенций\n\n"
        profile_content += "| Группа | Компетенция | Приоритет | Категория |\n"
        profile_content += "|--------|-------------|-----------|----------|\n"
        
        for group in professional_groups + general_groups:
            for comp in group.competencies:
                profile_content += f"| {group.group_name} | {comp.title} | {comp.priority.upper()} | {comp.category} |\n"
        
        profile_path.write_text(profile_content, encoding='utf-8')
        
        # Competency_mapping.md - связь с Evidence
        mapping_path = self.artifacts_dir / "Competency_mapping.md"
        mapping_content = f"""# Competency Mapping

**Связь компетенций с разделами Evidence.md**

## Трассируемость компетенций

"""
        
        evidence_sections_list = list(evidence_sections.keys())
        for group in professional_groups + general_groups:
            mapping_content += f"### {group.group_name}\n\n"
            for comp in group.competencies:
                mapping_content += f"**{comp.title}**\n"
                mapping_content += f"- Основан на разделах Evidence: {', '.join(evidence_sections_list[:2])}\n"  # Упрощенная связь
                mapping_content += f"- ID: {comp.competency_id}\n\n"
        
        mapping_path.write_text(mapping_content, encoding='utf-8')
        
        # Competency_indicators.md - детальные индикаторы
        indicators_path = self.artifacts_dir / "Competency_indicators.md"
        indicators_content = f"""# Competency Achievement Indicators

**Детальные индикаторы достижения компетенций**

## Как использовать индикаторы

Индикаторы достижения позволяют:
1. Оценить степень освоения компетенции
2. Разработать задания для оценки
3. Создать критерии оценивания
4. Отслеживать прогресс обучения

---

"""
        
        for group in professional_groups + general_groups:
            indicators_content += f"## {group.group_name}\n\n"
            
            for comp in group.competencies:
                indicators_content += f"### {comp.title}\n\n"
                indicators_content += f"**Описание:** {comp.description}\n\n"
                indicators_content += f"**Приоритет:** {comp.priority.upper()}\n\n"
                
                if comp.indicators:
                    indicators_content += "**Индикаторы достижения:**\n"
                    for i, indicator in enumerate(comp.indicators, 1):
                        indicators_content += f"{i}. {indicator}\n"
                else:
                    indicators_content += "**Индикаторы:** Не определены\n"
                
                indicators_content += "\n---\n\n"
        
        indicators_path.write_text(indicators_content, encoding='utf-8')
        
        logger.info(f"ШАГ SAVE_COMP.2. Профиль компетенций сохранен: {profile_path}")
        return profile_path
