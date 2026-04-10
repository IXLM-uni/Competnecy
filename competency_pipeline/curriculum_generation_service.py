"""
CURRICULUM GENERATION SERVICE

Ответственность:
- Преобразование профиля компетенций в структуру образовательной программы
- Создание дисциплин, практик и проектной работы
- Распределение часов и кредитов
- Построение логики семестров и последовательности освоения

Правила преобразования (из PIPELINE.md):
- Теоретическая база -> дисциплина
- Повторяемая отработка действий -> практикум/лаборатория
- Интеграция навыков -> проектный модуль  
- Реальный профессиональный контекст -> практика/стажировка
- Часы и кредиты по сложности/критичности/глубине

Принципы:
- Competency-based design (от компетенций к программе)
- Использование интернета как benchmark источника
- Педагогическая логика построения программы
- Соответствие образовательным стандартам

Выход:
- Program_Blueprint.md - структура образовательной программы
- Curriculum_Table.md - детальный учебный план
- Competency_matrix.md - матрица покрытия компетенций
"""

import asyncio
import logging
import json
import re
from datetime import datetime
from pathlib import Path
from dataclasses import dataclass
from typing import List, Dict, Optional, Any, Tuple

import sys
import os

from .llm_helpers import init_env, get_llm_client, get_env_config, call_llm, make_ctx

_GLOBAL_SERVICES = os.path.join(os.path.dirname(__file__), '..', 'Global_services')
if _GLOBAL_SERVICES not in sys.path:
    sys.path.insert(0, _GLOBAL_SERVICES)

from AI.llm_webcrawler import CrawlerClient

logger = logging.getLogger(__name__)

@dataclass
class CourseUnit:
    """Учебная единица (дисциплина, практика, проект)"""
    unit_id: str
    unit_type: str  # 'discipline', 'lab', 'practice', 'project', 'capstone'
    title: str
    description: str
    semester: int
    credits: int
    lecture_hours: int
    practice_hours: int
    self_study_hours: int
    assessment_type: str  # 'exam', 'test', 'project', 'portfolio'
    covered_competencies: List[str]  # ID компетенций
    prerequisites: List[str]  # ID других единиц
    learning_outcomes: List[str]

@dataclass
class ProgramModule:
    """Модуль образовательной программы"""
    module_id: str
    module_name: str
    description: str
    units: List[CourseUnit]
    total_credits: int
    module_type: str  # 'core', 'specialization', 'elective', 'practice'

class CurriculumGenerationService:
    """
    Сервис генерации образовательных программ из профилей компетенций
    """
    
    def __init__(self, artifacts_dir: str = "./artifacts"):
        """
        Инициализация сервиса
        
        Args:
            artifacts_dir: Директория с артефактами pipeline
        """
        logger.info("ШАГ 1. Инициализация CurriculumGenerationService")

        self.artifacts_dir = Path(artifacts_dir)

        self.env_config = init_env()
        self.llm_client = get_llm_client()
        self.crawler_client = CrawlerClient(
            base_url=self.env_config.get('CRAWLER_BASE_URL', 'http://localhost:8001'),
        )

        logger.info("ШАГ 2. Инициализация клиентов завершена")
    
    async def generate_curriculum(self, role_scope: str, program_duration_semesters: int = 4) -> str:
        """
        Основной метод генерации образовательной программы
        
        Args:
            role_scope: Описание целевой роли
            program_duration_semesters: Длительность программы в семестрах
            
        Returns:
            Путь к созданному Program_Blueprint.md
        """
        logger.info(f"ШАГ 3. Начинаем генерацию программы для роли: {role_scope[:100]}...")
        
        # Загружаем профиль компетенций
        competency_profile = await self._load_competency_profile()
        logger.info("ШАГ 4. Профиль компетенций загружен")
        
        # Анализируем benchmark программы из интернета
        benchmark_programs = await self._collect_benchmark_programs(role_scope)
        logger.info(f"ШАГ 5. Собрано {len(benchmark_programs)} benchmark программ")
        
        # Генерируем модули программы
        program_modules = await self._generate_program_modules(competency_profile, benchmark_programs, role_scope)
        logger.info(f"ШАГ 6. Сгенерировано {len(program_modules)} модулей программы")
        
        # Создаем учебные единицы для каждого модуля
        await self._populate_modules_with_units(program_modules, competency_profile, benchmark_programs, role_scope)
        logger.info("ШАГ 7. Модули заполнены учебными единицами")
        
        # Распределяем по семестрам
        semester_plan = await self._arrange_semester_sequence(program_modules, program_duration_semesters, role_scope)
        logger.info(f"ШАГ 8. Программа распределена по {program_duration_semesters} семестрам")
        
        # Рассчитываем часы и кредиты
        await self._calculate_hours_and_credits(program_modules, benchmark_programs)
        logger.info("ШАГ 9. Часы и кредиты рассчитаны")
        
        # Создаем матрицу покрытия компетенций
        competency_matrix = await self._create_competency_matrix(program_modules, competency_profile)
        logger.info("ШАГ 10. Матрица покрытия компетенций создана")
        
        # Сохраняем результаты
        blueprint_path = await self._save_curriculum_artifacts(
            program_modules, semester_plan, competency_matrix, role_scope, program_duration_semesters
        )
        logger.info(f"ШАГ 11. Образовательная программа сохранена: {blueprint_path}")
        
        return str(blueprint_path)
    
    async def _load_competency_profile(self) -> Dict[str, Any]:
        """Загрузка профиля компетенций"""
        profile_path = self.artifacts_dir / "Competency_Profile.md"
        
        if not profile_path.exists():
            raise FileNotFoundError(f"Competency_Profile.md не найден: {profile_path}")
        
        content = profile_path.read_text(encoding='utf-8')
        
        # Простой парсинг компетенций из markdown
        competencies = []
        current_competency = None
        
        for line in content.split('\n'):
            line = line.strip()
            
            # Обнаружение компетенций по эмодзи приоритета
            if any(emoji in line for emoji in ['🔴', '🟡', '🟢']) and line.startswith('####'):
                if current_competency:
                    competencies.append(current_competency)
                
                # Извлекаем приоритет и название
                if '🔴' in line:
                    priority = 'high'
                elif '🟡' in line:
                    priority = 'medium'  
                else:
                    priority = 'low'
                
                title = line.split(' ', 2)[-1] if len(line.split(' ')) > 2 else line
                
                current_competency = {
                    'title': title,
                    'priority': priority,
                    'description': '',
                    'indicators': [],
                    'category': 'professional'  # Определим точнее позже
                }
            
            elif current_competency and line and not line.startswith('#'):
                if line.startswith('- '):
                    current_competency['indicators'].append(line[2:])
                elif not line.startswith('**'):
                    current_competency['description'] += line + ' '
        
        if current_competency:
            competencies.append(current_competency)
        
        return {
            'competencies': competencies,
            'role_scope': 'Extracted from profile'  # TODO: извлечь из файла
        }
    
    async def _collect_benchmark_programs(self, role_scope: str) -> List[Dict[str, Any]]:
        """Сбор benchmark программ из интернета"""
        logger.info("ШАГ BENCHMARK.1. Поиск benchmark образовательных программ")
        
        # Формируем поисковые запросы (2 запроса для скорости)
        search_queries = [
            f"{role_scope} curriculum university program syllabus",
            f"{role_scope} bachelor master degree educational program",
        ]
        
        benchmark_programs = []

        # Параллельный поиск по всем запросам
        async def _fetch_one_query(i: int, query: str) -> List[Dict[str, Any]]:
            logger.info(f"ШАГ BENCHMARK.2.{i}. Поиск: {query}")
            results = []
            try:
                ctx = make_ctx()
                snippets = await self.crawler_client.search(queries=[query], ctx=ctx)
                valid = [s for s in snippets[:5] if s.text and len(s.text) > 500]

                # Параллельная extraction для всех сниппетов
                if valid:
                    extract_tasks = [self._extract_program_info(s.text) for s in valid]
                    infos = await asyncio.gather(*extract_tasks, return_exceptions=True)
                    for snippet, info in zip(valid, infos):
                        if isinstance(info, Exception):
                            continue
                        url = snippet.metadata.get('url', snippet.source_id)
                        results.append({
                            'title': snippet.metadata.get('title', 'Unknown Program'),
                            'url': url,
                            'content': snippet.text,
                            'extracted_info': info,
                        })
            except Exception as e:
                logger.error(f"Ошибка поиска benchmark по запросу {query}: {e}")
            return results

        all_results = await asyncio.gather(
            *[_fetch_one_query(i, q) for i, q in enumerate(search_queries, 1)]
        )
        for results in all_results:
            benchmark_programs.extend(results)

        logger.info(f"ШАГ BENCHMARK.3. Собрано {len(benchmark_programs)} benchmark программ")
        return benchmark_programs[:6]
    
    async def _extract_program_info(self, program_content: str) -> Dict[str, Any]:
        """Извлечение структурированной информации из программы"""
        
        extraction_prompt = f"""
Образовательная программа:
{program_content[:2000]}...

Извлеки ключевую информацию о структуре программы:

МОДУЛИ И ДИСЦИПЛИНЫ:
[список основных модулей/блоков и дисциплин]

ПРАКТИКИ:
[виды практик, если упоминаются]

КРЕДИТЫ/ЧАСЫ:
[примеры распределения кредитов и часов]

СЕМЕСТРЫ:
[длительность программы, если указана]

ФОРМЫ КОНТРОЛЯ:
[экзамены, зачеты, курсовые, дипломы]

Если информация не найдена, напиши "Не указано".
"""
        
        try:
            response = await call_llm(extraction_prompt, temperature=0.1, max_output_tokens=800)
            
            return {
                'raw_extraction': response,
                'has_modules': 'модуль' in response.lower() or 'блок' in response.lower(),
                'has_practice': 'практик' in response.lower(),
                'has_credits': 'кредит' in response.lower() or 'час' in response.lower(),
                'extracted_at': datetime.now().isoformat()
            }
            
        except Exception as e:
            logger.error(f"Ошибка извлечения информации о программе: {e}")
            return {'raw_extraction': 'Extraction failed', 'extracted_at': datetime.now().isoformat()}
    
    async def _generate_program_modules(self, competency_profile: Dict[str, Any], 
                                       benchmark_programs: List[Dict[str, Any]], 
                                       role_scope: str) -> List[ProgramModule]:
        """Генерация модулей образовательной программы"""
        logger.info("ШАГ MODULES.1. Генерируем модули программы")
        
        # Группируем компетенции для создания модулей
        high_priority_competencies = [c for c in competency_profile['competencies'] if c['priority'] == 'high']
        medium_priority_competencies = [c for c in competency_profile['competencies'] if c['priority'] == 'medium']
        
        # Анализируем benchmark программы для модульной структуры
        benchmark_info = '\n'.join([
            f"Программа: {p['title']}\n{p['extracted_info']['raw_extraction'][:300]}\n---"
            for p in benchmark_programs[:5] if p['extracted_info']['raw_extraction']
        ])
        
        modules_prompt = f"""
Роль: {role_scope}

Высокоприоритетные компетенции:
{chr(10).join([f"- {c['title']}" for c in high_priority_competencies])}

Среднеприоритетные компетенции:
{chr(10).join([f"- {c['title']}" for c in medium_priority_competencies])}

Примеры benchmark программ:
{benchmark_info}

Задача: Создай структуру модулей для образовательной программы.

Принципы:
1. Базовые модули для фундаментальных знаний
2. Профессиональные модули для core компетенций
3. Специализированные модули для advanced компетенций
4. Практический модуль для практик и проектов
5. Итоговая аттестация

Формат ответа:
МОДУЛЬ 1: [Название]
ОПИСАНИЕ: [Краткое описание, 1-2 предложения]
ТИП: [core/specialization/practice/capstone]
КОМПЕТЕНЦИИ: [какие компетенции покрывает]

МОДУЛЬ 2: [Название]
ОПИСАНИЕ: [Краткое описание]
ТИП: [core/specialization/practice/capstone]
КОМПЕТЕНЦИИ: [какие компетенции покрывает]

[и так далее, 4-6 модулей]
"""
        
        try:
            response = await call_llm(modules_prompt, temperature=0.2, max_output_tokens=1500)
            
            modules = self._parse_modules_response(response)
            logger.info(f"ШАГ MODULES.2. Создано {len(modules)} модулей программы")
            return modules
            
        except Exception as e:
            logger.error(f"Ошибка генерации модулей: {e}")
            # Fallback: создаем базовую структуру
            return self._create_fallback_modules()
    
    def _parse_modules_response(self, response: str) -> List[ProgramModule]:
        """Парсинг ответа LLM с модулями"""
        modules = []
        
        # Разделяем на блоки модулей
        blocks = re.split(r'МОДУЛЬ \d+:', response)[1:]
        
        for i, block in enumerate(blocks, 1):
            lines = block.strip().split('\n')
            
            # Извлекаем информацию о модуле
            module_name = lines[0].strip() if lines else f"Модуль {i}"
            
            description = ""
            module_type = "core"
            competencies = []
            
            for line in lines[1:]:
                line = line.strip()
                if line.startswith('ОПИСАНИЕ:'):
                    description = line.replace('ОПИСАНИЕ:', '').strip()
                elif line.startswith('ТИП:'):
                    type_text = line.replace('ТИП:', '').strip().lower()
                    if 'practice' in type_text:
                        module_type = 'practice'
                    elif 'specialization' in type_text:
                        module_type = 'specialization'
                    elif 'capstone' in type_text:
                        module_type = 'capstone'
                elif line.startswith('КОМПЕТЕНЦИИ:'):
                    comp_text = line.replace('КОМПЕТЕНЦИИ:', '').strip()
                    # Простое извлечение компетенций
                    competencies = [comp.strip() for comp in comp_text.split(',') if comp.strip()]
            
            module = ProgramModule(
                module_id=f"module_{i:02d}",
                module_name=module_name,
                description=description,
                units=[],  # Заполним позже
                total_credits=0,  # Рассчитаем позже
                module_type=module_type
            )
            
            modules.append(module)
        
        return modules
    
    def _create_fallback_modules(self) -> List[ProgramModule]:
        """Fallback: базовая структура модулей"""
        return [
            ProgramModule(
                module_id="module_01",
                module_name="Базовые знания",
                description="Фундаментальные знания для профессиональной деятельности",
                units=[],
                total_credits=0,
                module_type="core"
            ),
            ProgramModule(
                module_id="module_02", 
                module_name="Профессиональные компетенции",
                description="Core профессиональные навыки и умения",
                units=[],
                total_credits=0,
                module_type="core"
            ),
            ProgramModule(
                module_id="module_03",
                module_name="Практическое применение",
                description="Практики, лаборатории и проектная работа",
                units=[],
                total_credits=0,
                module_type="practice"
            )
        ]
    
    async def _populate_modules_with_units(self, modules: List[ProgramModule],
                                         competency_profile: Dict[str, Any],
                                         benchmark_programs: List[Dict[str, Any]],
                                         role_scope: str) -> None:
        """Заполнение модулей учебными единицами (параллельно)"""
        logger.info(f"ШАГ UNITS.1. Заполняем {len(modules)} модулей учебными единицами (parallel)")

        # Готовим пары (module, competencies) для параллельной генерации
        module_comp_pairs = []
        for module in modules:
            relevant_competencies = self._get_relevant_competencies_for_module(
                module, competency_profile['competencies']
            )
            module_comp_pairs.append((module, relevant_competencies))

        # Параллельная генерация units для всех модулей
        async def _gen_for_module(mod: ProgramModule, comps: List[Dict[str, Any]]) -> List:
            logger.info(f"ШАГ UNITS.2. Создаем единицы для модуля: {mod.module_name}")
            units = await self._generate_units_for_module(mod, comps, role_scope)
            logger.info(f"ШАГ UNITS.3. Модуль {mod.module_name} заполнен {len(units)} единицами")
            return units

        all_units = await asyncio.gather(
            *[_gen_for_module(mod, comps) for mod, comps in module_comp_pairs],
            return_exceptions=True,
        )

        for module, units in zip(modules, all_units):
            if isinstance(units, Exception):
                logger.error(f"Ошибка генерации units для {module.module_name}: {units}")
                module.units = []
            else:
                module.units = units
    
    def _get_relevant_competencies_for_module(self, module: ProgramModule, 
                                             competencies: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
        """Определение релевантных компетенций для модуля"""
        
        relevant = []
        
        # Простая эвристика основанная на типе модуля
        if module.module_type == 'core':
            # Берем высокоприоритетные компетенции
            relevant = [c for c in competencies if c['priority'] in ['high', 'medium']]
        elif module.module_type == 'specialization':
            # Берем средне- и низкоприоритетные
            relevant = [c for c in competencies if c['priority'] in ['medium', 'low']]
        elif module.module_type == 'practice':
            # Берем все компетенции, связанные с практическими навыками
            relevant = [c for c in competencies if 'умеет' in c['title'].lower() or 'способен' in c['title'].lower()]
        else:
            relevant = competencies
        
        return relevant[:8]  # Ограничиваем количество
    
    async def _generate_units_for_module(self, module: ProgramModule, 
                                       competencies: List[Dict[str, Any]], 
                                       role_scope: str) -> List[CourseUnit]:
        """Генерация учебных единиц для модуля"""
        
        competencies_text = '\n'.join([f"- {c['title']}" for c in competencies])
        
        units_prompt = f"""
Модуль: {module.module_name}
Описание модуля: {module.description}
Тип модуля: {module.module_type}

Компетенции для покрытия:
{competencies_text}

Задача: Создай 3-5 учебных единиц (дисциплин/практик/проектов) для этого модуля.

Правила:
- Теоретические знания -> дисциплина (лекции + семинары)
- Практические навыки -> лаборатория/практикум
- Интеграция навыков -> проект
- Реальная деятельность -> практика

Формат ответа:
ЕДИНИЦА 1: [Название]
ТИП: [discipline/lab/practice/project]
ОПИСАНИЕ: [Что изучается/отрабатывается]
КОМПЕТЕНЦИИ: [ID или названия покрываемых компетенций]

ЕДИНИЦА 2: [Название]
ТИП: [discipline/lab/practice/project]
ОПИСАНИЕ: [Что изучается/отрабатывается]
КОМПЕТЕНЦИИ: [ID или названия покрываемых компетенций]

[и так далее]
"""
        
        try:
            response = await call_llm(units_prompt, temperature=0.2, max_output_tokens=1200)
            
            units = self._parse_units_response(response, module.module_id)
            return units
            
        except Exception as e:
            logger.error(f"Ошибка генерации единиц для модуля {module.module_name}: {e}")
            return []
    
    def _parse_units_response(self, response: str, module_id: str) -> List[CourseUnit]:
        """Парсинг ответа LLM с учебными единицами"""
        units = []
        
        blocks = re.split(r'ЕДИНИЦА \d+:', response)[1:]
        
        for i, block in enumerate(blocks, 1):
            lines = block.strip().split('\n')
            
            # Извлекаем информацию
            title = lines[0].strip() if lines else f"Единица {i}"
            
            unit_type = 'discipline'
            description = ''
            competencies = []
            
            for line in lines[1:]:
                line = line.strip()
                if line.startswith('ТИП:'):
                    type_text = line.replace('ТИП:', '').strip().lower()
                    if 'lab' in type_text:
                        unit_type = 'lab'
                    elif 'practice' in type_text:
                        unit_type = 'practice'
                    elif 'project' in type_text:
                        unit_type = 'project'
                elif line.startswith('ОПИСАНИЕ:'):
                    description = line.replace('ОПИСАНИЕ:', '').strip()
                elif line.startswith('КОМПЕТЕНЦИИ:'):
                    comp_text = line.replace('КОМПЕТЕНЦИИ:', '').strip()
                    competencies = [comp.strip() for comp in comp_text.split(',') if comp.strip()]
            
            unit = CourseUnit(
                unit_id=f"{module_id}_unit_{i:02d}",
                unit_type=unit_type,
                title=title,
                description=description,
                semester=1,  # Определим позже
                credits=3,   # По умолчанию, уточним позже
                lecture_hours=32,
                practice_hours=16,
                self_study_hours=88,
                assessment_type='exam',
                covered_competencies=competencies,
                prerequisites=[],
                learning_outcomes=[]
            )
            
            units.append(unit)
        
        return units
    
    async def _arrange_semester_sequence(self, modules: List[ProgramModule], 
                                       duration_semesters: int, role_scope: str) -> Dict[int, List[str]]:
        """Распределение модулей и единиц по семестрам"""
        logger.info("ШАГ SEMESTER.1. Распределяем программу по семестрам")
        
        all_units = []
        for module in modules:
            all_units.extend(module.units)
        
        # LLM-планирование последовательности
        units_list = '\n'.join([
            f"{unit.unit_id}: {unit.title} ({unit.unit_type})"
            for unit in all_units
        ])
        
        sequence_prompt = f"""
Роль: {role_scope}
Длительность программы: {duration_semesters} семестров

Учебные единицы для распределения:
{units_list}

Задача: Распредели единицы по семестрам с учетом логической последовательности.

Принципы:
1. Базовые теоретические дисциплины - в начале
2. Специализированные дисциплины - в середине
3. Практики и проекты - ближе к концу
4. Равномерная нагрузка по семестрам (примерно 15-20 кредитов)

Формат ответа:
СЕМЕСТР 1:
- [unit_id]: [название]
- [unit_id]: [название]

СЕМЕСТР 2:
- [unit_id]: [название]
- [unit_id]: [название]

[и так далее]
"""
        
        try:
            response = await call_llm(sequence_prompt, temperature=0.1, max_output_tokens=800)
            
            semester_plan = self._parse_semester_sequence(response, all_units)
            
            # Обновляем семестры в учебных единицах
            for semester, unit_ids in semester_plan.items():
                for unit_id in unit_ids:
                    unit = next((u for u in all_units if u.unit_id == unit_id), None)
                    if unit:
                        unit.semester = semester
            
            logger.info(f"ШАГ SEMESTER.2. Программа распределена по {len(semester_plan)} семестрам")
            return semester_plan
            
        except Exception as e:
            logger.error(f"Ошибка планирования семестров: {e}")
            # Fallback: равномерное распределение
            units_per_semester = len(all_units) // duration_semesters
            semester_plan = {}
            for i, unit in enumerate(all_units):
                semester = (i // units_per_semester) + 1
                if semester > duration_semesters:
                    semester = duration_semesters
                unit.semester = semester
                if semester not in semester_plan:
                    semester_plan[semester] = []
                semester_plan[semester].append(unit.unit_id)
            return semester_plan
    
    def _parse_semester_sequence(self, response: str, all_units: List[CourseUnit]) -> Dict[int, List[str]]:
        """Парсинг плана семестров"""
        semester_plan = {}
        current_semester = None
        
        for line in response.split('\n'):
            line = line.strip()
            
            if line.startswith('СЕМЕСТР ') and ':' in line:
                semester_num = int(line.split()[1].replace(':', ''))
                current_semester = semester_num
                if semester_num not in semester_plan:
                    semester_plan[semester_num] = []
            
            elif line.startswith('- ') and current_semester:
                # Извлекаем unit_id
                unit_info = line[2:].strip()
                if ':' in unit_info:
                    unit_id = unit_info.split(':')[0].strip()
                    # Проверяем, что такой unit существует
                    if any(u.unit_id == unit_id for u in all_units):
                        semester_plan[current_semester].append(unit_id)
        
        return semester_plan
    
    async def _calculate_hours_and_credits(self, modules: List[ProgramModule], 
                                         benchmark_programs: List[Dict[str, Any]]) -> None:
        """Расчет часов и кредитов для учебных единиц"""
        logger.info("ШАГ CREDITS.1. Рассчитываем часы и кредиты")
        
        # Простые эвристики для MVP
        type_defaults = {
            'discipline': {'credits': 4, 'lecture': 48, 'practice': 16, 'self_study': 72},
            'lab': {'credits': 2, 'lecture': 16, 'practice': 32, 'self_study': 24},
            'practice': {'credits': 6, 'lecture': 0, 'practice': 108, 'self_study': 108},
            'project': {'credits': 5, 'lecture': 16, 'practice': 64, 'self_study': 100},
            'capstone': {'credits': 12, 'lecture': 0, 'practice': 216, 'self_study': 216}
        }
        
        for module in modules:
            total_credits = 0
            
            for unit in module.units:
                defaults = type_defaults.get(unit.unit_type, type_defaults['discipline'])
                
                unit.credits = defaults['credits']
                unit.lecture_hours = defaults['lecture']
                unit.practice_hours = defaults['practice']
                unit.self_study_hours = defaults['self_study']
                
                total_credits += unit.credits
            
            module.total_credits = total_credits
        
        logger.info("ШАГ CREDITS.2. Расчет часов и кредитов завершен")
    
    async def _create_competency_matrix(self, modules: List[ProgramModule], 
                                      competency_profile: Dict[str, Any]) -> Dict[str, Any]:
        """Создание матрицы покрытия компетенций"""
        logger.info("ШАГ MATRIX.1. Создаем матрицу покрытия компетенций")
        
        competencies = competency_profile['competencies']
        matrix = {}
        
        # Создаем матрицу: компетенция -> покрывающие единицы
        for competency in competencies:
            comp_title = competency['title']
            covering_units = []
            
            for module in modules:
                for unit in module.units:
                    # Простая проверка: есть ли упоминание компетенции в покрытых
                    if any(comp_title.lower() in covered.lower() for covered in unit.covered_competencies):
                        covering_units.append({
                            'unit_id': unit.unit_id,
                            'unit_title': unit.title,
                            'module': module.module_name,
                            'semester': unit.semester
                        })
            
            matrix[comp_title] = {
                'priority': competency['priority'],
                'covering_units': covering_units,
                'coverage_adequate': len(covering_units) > 0
            }
        
        logger.info(f"ШАГ MATRIX.2. Матрица создана для {len(matrix)} компетенций")
        return matrix
    
    async def _save_curriculum_artifacts(self, modules: List[ProgramModule], 
                                       semester_plan: Dict[int, List[str]],
                                       competency_matrix: Dict[str, Any], 
                                       role_scope: str, 
                                       duration_semesters: int) -> Path:
        """Сохранение артефактов образовательной программы"""
        logger.info("ШАГ SAVE_CURR.1. Сохранение артефактов программы")
        
        # Program_Blueprint.md
        blueprint_path = self.artifacts_dir / "Program_Blueprint.md"
        
        blueprint_content = f"""# Program Blueprint

**Целевая роль:** {role_scope}
**Длительность:** {duration_semesters} семестров
**Дата создания:** {datetime.now().isoformat()}

---

## Обзор программы

Образовательная программа подготовки специалистов для роли "{role_scope}".
Программа построена на компетентностном подходе и включает теоретическую подготовку,
практические занятия и проектную деятельность.

### Структура программы

- **Модулей**: {len(modules)}
- **Всего учебных единиц**: {sum(len(m.units) for m in modules)}
- **Общий объем**: {sum(m.total_credits for m in modules)} кредитов

---

## Модули программы

"""
        
        # Добавляем информацию о модулях
        for module in modules:
            blueprint_content += f"### {module.module_name}\n\n"
            blueprint_content += f"**Тип модуля:** {module.module_type.upper()}\n"
            blueprint_content += f"**Описание:** {module.description}\n"
            blueprint_content += f"**Объем:** {module.total_credits} кредитов\n\n"
            
            blueprint_content += "**Учебные единицы:**\n"
            for unit in module.units:
                blueprint_content += f"- **{unit.title}** ({unit.unit_type}, {unit.credits} кр., семестр {unit.semester})\n"
                blueprint_content += f"  {unit.description}\n"
            
            blueprint_content += "\n---\n\n"
        
        # Добавляем план по семестрам
        blueprint_content += "## Распределение по семестрам\n\n"
        
        for semester in sorted(semester_plan.keys()):
            unit_ids = semester_plan[semester]
            total_credits_semester = 0
            
            blueprint_content += f"### Семестр {semester}\n\n"
            
            for unit_id in unit_ids:
                # Находим единицу
                unit = None
                for module in modules:
                    for u in module.units:
                        if u.unit_id == unit_id:
                            unit = u
                            break
                
                if unit:
                    blueprint_content += f"- **{unit.title}** ({unit.credits} кр.)\n"
                    total_credits_semester += unit.credits
            
            blueprint_content += f"\n**Всего кредитов в семестре:** {total_credits_semester}\n\n"
        
        blueprint_path.write_text(blueprint_content, encoding='utf-8')
        
        # Curriculum_Table.md - детальная таблица
        table_path = self.artifacts_dir / "Curriculum_Table.md"
        
        table_content = f"""# Curriculum Table

**Детальный учебный план**

| Семестр | Модуль | Дисциплина | Тип | Кредиты | Лекции | Практика | Сам.работа | Контроль |
|---------|--------|------------|-----|---------|---------|----------|------------|----------|
"""
        
        for module in modules:
            for unit in module.units:
                table_content += f"| {unit.semester} | {module.module_name[:15]}... | {unit.title} | {unit.unit_type} | {unit.credits} | {unit.lecture_hours} | {unit.practice_hours} | {unit.self_study_hours} | {unit.assessment_type} |\n"
        
        # Добавляем итоги
        total_credits = sum(m.total_credits for m in modules)
        total_lecture = sum(u.lecture_hours for m in modules for u in m.units)
        total_practice = sum(u.practice_hours for m in modules for u in m.units)
        total_self_study = sum(u.self_study_hours for m in modules for u in m.units)
        
        table_content += f"\n**ИТОГО:** {total_credits} кредитов, {total_lecture} часов лекций, {total_practice} часов практики, {total_self_study} часов самостоятельной работы\n"
        
        table_path.write_text(table_content, encoding='utf-8')
        
        # Competency_matrix.md - матрица покрытия
        matrix_path = self.artifacts_dir / "Competency_matrix.md"
        
        matrix_content = f"""# Competency Coverage Matrix

**Матрица покрытия компетенций учебными единицами**

## Покрытие по компетенциям

"""
        
        for comp_title, comp_data in competency_matrix.items():
            status_icon = "✅" if comp_data['coverage_adequate'] else "❌"
            priority_icon = "🔴" if comp_data['priority'] == 'high' else "🟡" if comp_data['priority'] == 'medium' else "🟢"
            
            matrix_content += f"### {priority_icon} {comp_title} {status_icon}\n\n"
            
            if comp_data['covering_units']:
                matrix_content += "**Покрывающие учебные единицы:**\n"
                for unit_info in comp_data['covering_units']:
                    matrix_content += f"- {unit_info['unit_title']} (модуль: {unit_info['module']}, семестр {unit_info['semester']})\n"
            else:
                matrix_content += "**⚠️ КОМПЕТЕНЦИЯ НЕ ПОКРЫТА!**\n"
            
            matrix_content += "\n"
        
        # Анализ покрытия
        total_competencies = len(competency_matrix)
        covered_competencies = sum(1 for comp_data in competency_matrix.values() if comp_data['coverage_adequate'])
        coverage_percentage = (covered_competencies / total_competencies * 100) if total_competencies > 0 else 0
        
        matrix_content += f"""
## Анализ покрытия

- **Всего компетенций:** {total_competencies}
- **Покрыто:** {covered_competencies}
- **Процент покрытия:** {coverage_percentage:.1f}%

### Рекомендации

"""
        
        if coverage_percentage < 80:
            matrix_content += "- ⚠️ Низкий процент покрытия компетенций. Необходимо добавить учебные единицы.\n"
        
        uncovered_high_priority = [
            comp_title for comp_title, comp_data in competency_matrix.items()
            if not comp_data['coverage_adequate'] and comp_data['priority'] == 'high'
        ]
        
        if uncovered_high_priority:
            matrix_content += f"- 🔴 Не покрыты высокоприоритетные компетенции: {', '.join(uncovered_high_priority[:3])}\n"
        
        matrix_path.write_text(matrix_content, encoding='utf-8')
        
        logger.info(f"ШАГ SAVE_CURR.2. Образовательная программа сохранена: {blueprint_path}")
        return blueprint_path
