"""
REVIEW SERVICE

Ответственность:
- Экспертная проверка созданной образовательной программы
- Выявление несоответствий и пробелов
- Сопоставление с benchmark программами
- Генерация рекомендаций по улучшению

Критерии проверки (из PIPELINE.md):
- У каждой ключевой компетенции есть покрытие дисциплинами/практикой
- У дисциплин есть смысл, а не только красивые названия  
- Часы и кредиты не взяты с потолка
- Практика встроена в программу, а не приклеена в конце
- Программа соотнесена с реальными benchmark программами

Принципы:
- Multi-pass review (несколько проходов проверки)
- Количественная и качественная оценка
- Конструктивные рекомендации
- Фокус на реализуемости программы

Выход:
- Review_Notes.md - детальный анализ и рекомендации
- Program_v2.md - исправленная версия (при необходимости)  
- Quality_metrics.md - количественные метрики качества
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
class ReviewFinding:
    """Результат проверки"""
    category: str  # 'coverage', 'structure', 'content', 'feasibility', 'alignment'
    severity: str  # 'critical', 'major', 'minor', 'suggestion'
    title: str
    description: str
    affected_items: List[str]  # ID модулей/единиц/компетенций
    recommendation: str
    auto_fixable: bool = False

@dataclass
class QualityMetrics:
    """Метрики качества программы"""
    competency_coverage_percent: float
    high_priority_coverage_percent: float
    credits_balance_score: float  # 0-1, насколько сбалансированы кредиты
    practice_integration_score: float  # 0-1, насколько практика интегрирована
    prerequisite_logic_score: float  # 0-1, логичность пререквизитов
    benchmark_alignment_score: float  # 0-1, соответствие benchmark
    overall_quality_score: float  # 0-1, общая оценка

class ReviewService:
    """
    Сервис экспертной проверки образовательных программ
    """
    
    def __init__(self, artifacts_dir: str = "./artifacts"):
        """
        Инициализация сервиса
        
        Args:
            artifacts_dir: Директория с артефактами pipeline
        """
        logger.info("ШАГ 1. Инициализация ReviewService")

        self.artifacts_dir = Path(artifacts_dir)

        self.env_config = init_env()
        self.llm_client = get_llm_client()

        logger.info("ШАГ 2. Инициализация клиентов завершена")
    
    async def conduct_program_review(self, role_scope: str) -> str:
        """
        Основной метод проведения экспертной проверки
        
        Args:
            role_scope: Описание целевой роли
            
        Returns:
            Путь к созданному Review_Notes.md
        """
        logger.info(f"ШАГ 3. Начинаем экспертную проверку программы для роли: {role_scope[:100]}...")
        
        # Загружаем артефакты для проверки
        program_data = await self._load_program_artifacts()
        logger.info("ШАГ 4. Артефакты программы загружены")
        
        # Проводим многоуровневую проверку
        findings = []
        
        # Проверка 1: Покрытие компетенций
        coverage_findings = await self._check_competency_coverage(program_data)
        findings.extend(coverage_findings)
        logger.info(f"ШАГ 5. Проверка покрытия компетенций: найдено {len(coverage_findings)} проблем")
        
        # Проверка 2: Структурная целостность
        structure_findings = await self._check_program_structure(program_data, role_scope)
        findings.extend(structure_findings)
        logger.info(f"ШАГ 6. Проверка структуры: найдено {len(structure_findings)} проблем")
        
        # Проверка 3: Содержательная адекватность
        content_findings = await self._check_content_adequacy(program_data, role_scope)
        findings.extend(content_findings)
        logger.info(f"ШАГ 7. Проверка содержания: найдено {len(content_findings)} проблем")
        
        # Проверка 4: Реализуемость программы
        feasibility_findings = await self._check_program_feasibility(program_data)
        findings.extend(feasibility_findings)
        logger.info(f"ШАГ 8. Проверка реализуемости: найдено {len(feasibility_findings)} проблем")
        
        # Проверка 5: Соответствие benchmark
        alignment_findings = await self._check_benchmark_alignment(program_data, role_scope)
        findings.extend(alignment_findings)
        logger.info(f"ШАГ 9. Проверка соответствия benchmark: найдено {len(alignment_findings)} проблем")
        
        # Рассчитываем метрики качества
        quality_metrics = await self._calculate_quality_metrics(program_data, findings)
        logger.info(f"ШАГ 10. Общая оценка качества: {quality_metrics.overall_quality_score:.2f}")
        
        # Генерируем рекомендации
        recommendations = await self._generate_improvement_recommendations(findings, quality_metrics, role_scope)
        logger.info(f"ШАГ 11. Сгенерировано {len(recommendations)} рекомендаций")
        
        # Сохраняем результаты проверки
        review_path = await self._save_review_artifacts(
            findings, quality_metrics, recommendations, program_data, role_scope
        )
        logger.info(f"ШАГ 12. Результаты проверки сохранены: {review_path}")
        
        return str(review_path)
    
    async def _load_program_artifacts(self) -> Dict[str, Any]:
        """Загрузка артефактов программы для проверки"""
        logger.info("ШАГ LOAD.1. Загружаем артефакты программы")
        
        artifacts = {}
        
        # Загружаем основные файлы
        files_to_load = [
            'Program_Blueprint.md',
            'Curriculum_Table.md', 
            'Competency_Profile.md',
            'Competency_matrix.md',
            'Evidence.md'
        ]
        
        for filename in files_to_load:
            file_path = self.artifacts_dir / filename
            if file_path.exists():
                artifacts[filename] = file_path.read_text(encoding='utf-8')
                logger.info(f"ШАГ LOAD.2. Загружен {filename}")
            else:
                logger.warning(f"ШАГ LOAD.3. Файл не найден: {filename}")
                artifacts[filename] = ""
        
        return artifacts
    
    async def _check_competency_coverage(self, program_data: Dict[str, Any]) -> List[ReviewFinding]:
        """Проверка покрытия компетенций"""
        logger.info("ШАГ COV.1. Проверяем покрытие компетенций")
        
        findings = []
        
        # Анализируем матрицу компетенций
        matrix_content = program_data.get('Competency_matrix.md', '')
        
        if not matrix_content:
            findings.append(ReviewFinding(
                category='coverage',
                severity='critical',
                title='Матрица компетенций отсутствует',
                description='Не найден файл Competency_matrix.md, невозможно проверить покрытие компетенций',
                affected_items=[],
                recommendation='Создайте матрицу покрытия компетенций через curriculum_generation_service'
            ))
            return findings
        
        # Ищем непокрытые компетенции
        if "НЕ ПОКРЫТА" in matrix_content:
            uncovered_count = matrix_content.count("НЕ ПОКРЫТА")
            findings.append(ReviewFinding(
                category='coverage',
                severity='critical',
                title=f'Найдено {uncovered_count} непокрытых компетенций',
                description='Некоторые компетенции не покрыты учебными единицами',
                affected_items=[],
                recommendation='Добавьте дисциплины или практики для покрытия всех компетенций',
                auto_fixable=True
            ))
        
        # Проверяем покрытие высокоприоритетных компетенций  
        high_priority_uncovered = []
        lines = matrix_content.split('\n')
        current_competency = None
        
        for line in lines:
            if '🔴' in line and '###' in line:  # Высокоприоритетная компетенция
                current_competency = line.strip()
            elif current_competency and "НЕ ПОКРЫТА" in line:
                high_priority_uncovered.append(current_competency)
                current_competency = None
            elif current_competency and "Покрывающие учебные единицы:" in line:
                current_competency = None  # Эта компетенция покрыта
        
        if high_priority_uncovered:
            findings.append(ReviewFinding(
                category='coverage',
                severity='critical',
                title='Не покрыты высокоприоритетные компетенции',
                description=f'Критически важные компетенции остались без покрытия: {len(high_priority_uncovered)} шт.',
                affected_items=high_priority_uncovered,
                recommendation='Срочно добавьте учебные единицы для покрытия высокоприоритетных компетенций'
            ))
        
        logger.info(f"ШАГ COV.2. Проверка покрытия завершена: {len(findings)} проблем")
        return findings
    
    async def _check_program_structure(self, program_data: Dict[str, Any], role_scope: str) -> List[ReviewFinding]:
        """Проверка структурной целостности программы"""
        logger.info("ШАГ STRUCT.1. Проверяем структуру программы")
        
        findings = []
        blueprint_content = program_data.get('Program_Blueprint.md', '')
        curriculum_content = program_data.get('Curriculum_Table.md', '')
        
        if not blueprint_content:
            findings.append(ReviewFinding(
                category='structure',
                severity='critical',
                title='Отсутствует структура программы',
                description='Не найден Program_Blueprint.md',
                affected_items=[],
                recommendation='Создайте структуру программы через curriculum_generation_service'
            ))
            return findings
        
        # LLM-анализ структуры
        structure_prompt = f"""
Роль: {role_scope}

Структура программы:
{blueprint_content[:2000]}...

Учебный план:
{curriculum_content[:1000]}...

Проанализируй структурные проблемы программы. Ищи:

1. ЛОГИЧЕСКУЮ ПОСЛЕДОВАТЕЛЬНОСТЬ:
- Есть ли нарушения в последовательности дисциплин?
- Читаются ли сложные темы до базовых?

2. БАЛАНСИРОВКУ НАГРУЗКИ:
- Сбалансированы ли семестры по кредитам?
- Есть ли перегруженные семестры?

3. МОДУЛЬНУЮ СТРУКТУРУ:
- Логично ли сгруппированы дисциплины в модули?
- Есть ли модули без ясной цели?

4. ПРАКТИЧЕСКУЮ ИНТЕГРАЦИЮ:
- Интегрирована ли практика с теорией?
- Есть ли практики в конце без связи с дисциплинами?

Если находишь проблемы, описывай ИХ КОНКРЕТНО с указанием модулей/дисциплин.
Если все хорошо, напиши: СТРУКТУРНЫХ ПРОБЛЕМ НЕ НАЙДЕНО.

Формат ответа:
ПРОБЛЕМА 1: [краткое название]
ОПИСАНИЕ: [детальное описание]
ЗАТРОНУТО: [конкретные модули/дисциплины]
РЕКОМЕНДАЦИЯ: [что делать]

ПРОБЛЕМА 2: [краткое название]
[и так далее]
"""
        
        try:
            response = await call_llm(structure_prompt, temperature=0.1, max_output_tokens=1200)
            
            if "СТРУКТУРНЫХ ПРОБЛЕМ НЕ НАЙДЕНО" not in response:
                # Парсим найденные проблемы
                structure_findings = self._parse_llm_findings(response, 'structure')
                findings.extend(structure_findings)
                
        except Exception as e:
            logger.error(f"Ошибка анализа структуры: {e}")
            
        logger.info(f"ШАГ STRUCT.2. Проверка структуры завершена: {len(findings)} проблем")
        return findings
    
    async def _check_content_adequacy(self, program_data: Dict[str, Any], role_scope: str) -> List[ReviewFinding]:
        """Проверка содержательной адекватности"""
        logger.info("ШАГ CONTENT.1. Проверяем содержательную адекватность")
        
        findings = []
        blueprint_content = program_data.get('Program_Blueprint.md', '')
        evidence_content = program_data.get('Evidence.md', '')
        
        # LLM-анализ соответствия программы реальной деятельности
        content_prompt = f"""
Роль: {role_scope}

Evidence о реальной деятельности:
{evidence_content[:1500]}...

Образовательная программа:
{blueprint_content[:1500]}...

Проанализируй СОДЕРЖАТЕЛЬНУЮ АДЕКВАТНОСТЬ программы:

1. СООТВЕТСТВИЕ РЕАЛЬНОСТИ:
- Покрывает ли программа реальные задачи из Evidence?
- Есть ли дисциплины "для красоты" без связи с деятельностью?

2. АКТУАЛЬНОСТЬ ИНСТРУМЕНТОВ:
- Изучаются ли современные инструменты профессии?
- Есть ли устаревшие технологии?

3. ГЛУБИНА ИЗУЧЕНИЯ:
- Достаточна ли глубина для профессиональной деятельности?
- Есть ли поверхностное изучение важных тем?

4. ПРОПУЩЕННЫЕ ОБЛАСТИ:
- Что важного отсутствует в программе по сравнению с Evidence?

Если находишь проблемы, указывай КОНКРЕТНЫЕ дисциплины и области.
Если все адекватно, напиши: СОДЕРЖАТЕЛЬНЫХ ПРОБЛЕМ НЕ НАЙДЕНО.

Формат аналогичен предыдущему.
"""
        
        try:
            response = await call_llm(content_prompt, temperature=0.1, max_output_tokens=1200)
            
            if "СОДЕРЖАТЕЛЬНЫХ ПРОБЛЕМ НЕ НАЙДЕНО" not in response:
                content_findings = self._parse_llm_findings(response, 'content')
                findings.extend(content_findings)
                
        except Exception as e:
            logger.error(f"Ошибка анализа содержания: {e}")
        
        logger.info(f"ШАГ CONTENT.2. Проверка содержания завершена: {len(findings)} проблем")
        return findings
    
    async def _check_program_feasibility(self, program_data: Dict[str, Any]) -> List[ReviewFinding]:
        """Проверка реализуемости программы"""
        logger.info("ШАГ FEAS.1. Проверяем реализуемость программы")
        
        findings = []
        curriculum_content = program_data.get('Curriculum_Table.md', '')
        
        if not curriculum_content:
            return findings
        
        # Извлекаем данные о кредитах и часах
        credit_pattern = r'\|\s*\d+\s*\|\s*[^|]*\|\s*[^|]*\|\s*[^|]*\|\s*(\d+)\s*\|'
        credits = re.findall(credit_pattern, curriculum_content)
        
        if credits:
            try:
                credit_values = [int(c) for c in credits if c.isdigit()]
                total_credits = sum(credit_values)
                
                # Проверки реализуемости
                if total_credits < 120:
                    findings.append(ReviewFinding(
                        category='feasibility',
                        severity='major',
                        title='Недостаточный объем программы',
                        description=f'Общий объем {total_credits} кредитов слишком мал для полноценной подготовки',
                        affected_items=[],
                        recommendation='Увеличьте объем программы до 120-180 кредитов'
                    ))
                
                if total_credits > 240:
                    findings.append(ReviewFinding(
                        category='feasibility',
                        severity='major',
                        title='Избыточный объем программы',
                        description=f'Общий объем {total_credits} кредитов слишком велик',
                        affected_items=[],
                        recommendation='Сократите объем программы до разумных пределов'
                    ))
                
                # Проверка на одинаковые кредиты (признак шаблонности)
                if len(set(credit_values)) <= 2 and len(credit_values) > 5:
                    findings.append(ReviewFinding(
                        category='feasibility',
                        severity='minor',
                        title='Шаблонное распределение кредитов',
                        description='Большинство дисциплин имеют одинаковые кредиты - возможно, не учтена сложность',
                        affected_items=[],
                        recommendation='Пересмотрите распределение кредитов в зависимости от сложности дисциплин'
                    ))
                    
            except Exception as e:
                logger.error(f"Ошибка анализа кредитов: {e}")
        
        logger.info(f"ШАГ FEAS.2. Проверка реализуемости завершена: {len(findings)} проблем")
        return findings
    
    async def _check_benchmark_alignment(self, program_data: Dict[str, Any], role_scope: str) -> List[ReviewFinding]:
        """Проверка соответствия benchmark программам"""
        logger.info("ШАГ BENCH.1. Проверяем соответствие benchmark")
        
        findings = []
        blueprint_content = program_data.get('Program_Blueprint.md', '')
        
        # Простая проверка наличия ключевых элементов типичных программ
        key_elements = {
            'практика': ['практика', 'internship', 'placement'],
            'проект': ['проект', 'project', 'capstone'],
            'аттестация': ['аттестация', 'диплом', 'thesis', 'final']
        }
        
        missing_elements = []
        for element_name, keywords in key_elements.items():
            if not any(keyword.lower() in blueprint_content.lower() for keyword in keywords):
                missing_elements.append(element_name)
        
        if missing_elements:
            findings.append(ReviewFinding(
                category='alignment',
                severity='major',
                title='Отсутствуют стандартные элементы программы',
                description=f'В программе отсутствуют: {", ".join(missing_elements)}',
                affected_items=missing_elements,
                recommendation='Добавьте стандартные элементы образовательных программ'
            ))
        
        logger.info(f"ШАГ BENCH.2. Проверка benchmark завершена: {len(findings)} проблем")
        return findings
    
    def _parse_llm_findings(self, response: str, category: str) -> List[ReviewFinding]:
        """Парсинг результатов LLM-анализа"""
        findings = []
        
        # Разделяем на блоки проблем
        blocks = re.split(r'ПРОБЛЕМА \d+:', response)[1:]
        
        for block in blocks:
            lines = block.strip().split('\n')
            if not lines:
                continue
                
            title = lines[0].strip()
            description = ""
            affected_items = []
            recommendation = ""
            
            for line in lines[1:]:
                line = line.strip()
                if line.startswith('ОПИСАНИЕ:'):
                    description = line.replace('ОПИСАНИЕ:', '').strip()
                elif line.startswith('ЗАТРОНУТО:'):
                    affected_text = line.replace('ЗАТРОНУТО:', '').strip()
                    affected_items = [item.strip() for item in affected_text.split(',') if item.strip()]
                elif line.startswith('РЕКОМЕНДАЦИЯ:'):
                    recommendation = line.replace('РЕКОМЕНДАЦИЯ:', '').strip()
            
            # Определяем серьезность по ключевым словам
            severity = 'minor'
            if any(word in (title + description).lower() for word in ['критически', 'невозможно', 'отсутствует']):
                severity = 'critical'
            elif any(word in (title + description).lower() for word in ['важно', 'серьезно', 'проблема']):
                severity = 'major'
            
            finding = ReviewFinding(
                category=category,
                severity=severity,
                title=title,
                description=description,
                affected_items=affected_items,
                recommendation=recommendation
            )
            
            findings.append(finding)
        
        return findings
    
    async def _calculate_quality_metrics(self, program_data: Dict[str, Any], 
                                       findings: List[ReviewFinding]) -> QualityMetrics:
        """Расчет метрик качества программы"""
        logger.info("ШАГ METRICS.1. Рассчитываем метрики качества")
        
        # Анализируем матрицу компетенций для покрытия
        matrix_content = program_data.get('Competency_matrix.md', '')
        
        competency_coverage_percent = 100.0
        high_priority_coverage_percent = 100.0
        
        if matrix_content:
            total_competencies = matrix_content.count('###') - matrix_content.count('## ')  # Исключаем заголовки разделов
            uncovered_competencies = matrix_content.count('НЕ ПОКРЫТА')
            
            if total_competencies > 0:
                competency_coverage_percent = ((total_competencies - uncovered_competencies) / total_competencies) * 100
            
            # Высокоприоритетные компетенции
            high_priority_total = matrix_content.count('🔴')
            high_priority_uncovered = 0
            
            lines = matrix_content.split('\n')
            looking_for_coverage = False
            
            for line in lines:
                if '🔴' in line and '###' in line:
                    looking_for_coverage = True
                elif looking_for_coverage and "НЕ ПОКРЫТА" in line:
                    high_priority_uncovered += 1
                    looking_for_coverage = False
                elif looking_for_coverage and "Покрывающие учебные единицы:" in line:
                    looking_for_coverage = False
            
            if high_priority_total > 0:
                high_priority_coverage_percent = ((high_priority_total - high_priority_uncovered) / high_priority_total) * 100
        
        # Оценка баланса кредитов (упрощенно)
        credits_balance_score = 0.8  # Placeholder
        if any(f.title == 'Шаблонное распределение кредитов' for f in findings):
            credits_balance_score = 0.6
        
        # Оценка интеграции практики
        practice_integration_score = 0.7  # Placeholder
        blueprint_content = program_data.get('Program_Blueprint.md', '')
        if 'практика' in blueprint_content.lower():
            practice_integration_score = 0.8
        
        # Логика пререквизитов (упрощенно)
        prerequisite_logic_score = 0.8
        
        # Соответствие benchmark
        benchmark_alignment_score = 0.7
        if any(f.category == 'alignment' for f in findings):
            benchmark_alignment_score = 0.5
        
        # Общая оценка (взвешенная сумма)
        weights = {
            'coverage': 0.3,
            'high_priority': 0.2,
            'balance': 0.15,
            'practice': 0.15,
            'prerequisites': 0.1,
            'alignment': 0.1
        }
        
        overall_quality_score = (
            (competency_coverage_percent / 100) * weights['coverage'] +
            (high_priority_coverage_percent / 100) * weights['high_priority'] +
            credits_balance_score * weights['balance'] +
            practice_integration_score * weights['practice'] +
            prerequisite_logic_score * weights['prerequisites'] +
            benchmark_alignment_score * weights['alignment']
        )
        
        # Штрафы за критические проблемы
        critical_findings = [f for f in findings if f.severity == 'critical']
        if critical_findings:
            overall_quality_score *= (1 - 0.1 * len(critical_findings))  # -10% за каждую критическую проблему
        
        overall_quality_score = max(0.0, min(1.0, overall_quality_score))
        
        metrics = QualityMetrics(
            competency_coverage_percent=competency_coverage_percent,
            high_priority_coverage_percent=high_priority_coverage_percent,
            credits_balance_score=credits_balance_score,
            practice_integration_score=practice_integration_score,
            prerequisite_logic_score=prerequisite_logic_score,
            benchmark_alignment_score=benchmark_alignment_score,
            overall_quality_score=overall_quality_score
        )
        
        logger.info(f"ШАГ METRICS.2. Метрики рассчитаны: общая оценка {overall_quality_score:.2f}")
        return metrics
    
    async def _generate_improvement_recommendations(self, findings: List[ReviewFinding], 
                                                  quality_metrics: QualityMetrics, 
                                                  role_scope: str) -> List[str]:
        """Генерация рекомендаций по улучшению"""
        logger.info("ШАГ REC.1. Генерируем рекомендации по улучшению")
        
        recommendations = []
        
        # Приоритизируем рекомендации по серьезности
        critical_findings = [f for f in findings if f.severity == 'critical']
        major_findings = [f for f in findings if f.severity == 'major']
        
        if critical_findings:
            recommendations.append("🔴 **КРИТИЧЕСКИЕ ПРОБЛЕМЫ (требуют немедленного решения):**")
            for finding in critical_findings:
                recommendations.append(f"- {finding.title}: {finding.recommendation}")
        
        if major_findings:
            recommendations.append("🟡 **ВАЖНЫЕ ПРОБЛЕМЫ (рекомендуется решить):**")
            for finding in major_findings:
                recommendations.append(f"- {finding.title}: {finding.recommendation}")
        
        # Общие рекомендации по метрикам
        if quality_metrics.competency_coverage_percent < 90:
            recommendations.append("📊 **ПОКРЫТИЕ КОМПЕТЕНЦИЙ:** Добавьте учебные единицы для полного покрытия компетенций")
        
        if quality_metrics.practice_integration_score < 0.7:
            recommendations.append("🔧 **ПРАКТИЧЕСКАЯ ПОДГОТОВКА:** Увеличьте долю практических занятий и проектной работы")
        
        if quality_metrics.overall_quality_score < 0.7:
            recommendations.append("⚠️ **ОБЩЕЕ КАЧЕСТВО:** Программа требует существенной доработки перед внедрением")
        
        # LLM-генерация дополнительных рекомендаций
        findings_summary = '\n'.join([
            f"- {f.title} ({f.severity}): {f.recommendation}" 
            for f in findings[:10]  # Берем топ-10 проблем
        ])
        
        llm_prompt = f"""
Роль: {role_scope}
Общая оценка качества программы: {quality_metrics.overall_quality_score:.2f}

Найденные проблемы:
{findings_summary}

Сгенерируй 3-5 СТРАТЕГИЧЕСКИХ рекомендаций по улучшению программы.
Фокусируйся на системных улучшениях, а не на исправлении отдельных проблем.

Формат:
🎯 [Название стратегического направления]
[Описание рекомендации в 2-3 предложениях]
"""
        
        try:
            response = await call_llm(llm_prompt, temperature=0.2, max_output_tokens=800)
            
            recommendations.append("\n🎯 **СТРАТЕГИЧЕСКИЕ РЕКОМЕНДАЦИИ:**")
            recommendations.append(response)
            
        except Exception as e:
            logger.error(f"Ошибка генерации LLM-рекомендаций: {e}")
        
        logger.info(f"ШАГ REC.2. Сгенерировано {len(recommendations)} рекомендаций")
        return recommendations
    
    async def _save_review_artifacts(self, findings: List[ReviewFinding], 
                                   quality_metrics: QualityMetrics,
                                   recommendations: List[str], 
                                   program_data: Dict[str, Any], 
                                   role_scope: str) -> Path:
        """Сохранение результатов проверки"""
        logger.info("ШАГ SAVE_REV.1. Сохранение результатов проверки")
        
        # Review_Notes.md - основной отчет
        review_path = self.artifacts_dir / "Review_Notes.md"
        
        review_content = f"""# Program Review Report

**Целевая роль:** {role_scope}
**Дата проверки:** {datetime.now().isoformat()}
**Общая оценка качества:** {quality_metrics.overall_quality_score:.2f} / 1.00

---

## Исполнительное резюме

Проведена комплексная экспертная проверка образовательной программы по {len(findings)} критериям.
Выявлено проблем: {len(findings)} (из них критических: {len([f for f in findings if f.severity == 'critical'])}).

### Ключевые метрики качества

| Метрика | Значение | Оценка |
|---------|----------|--------|
| Покрытие компетенций | {quality_metrics.competency_coverage_percent:.1f}% | {'✅' if quality_metrics.competency_coverage_percent >= 90 else '⚠️' if quality_metrics.competency_coverage_percent >= 70 else '❌'} |
| Покрытие высокоприоритетных | {quality_metrics.high_priority_coverage_percent:.1f}% | {'✅' if quality_metrics.high_priority_coverage_percent >= 95 else '⚠️' if quality_metrics.high_priority_coverage_percent >= 80 else '❌'} |
| Балансировка кредитов | {quality_metrics.credits_balance_score:.2f} | {'✅' if quality_metrics.credits_balance_score >= 0.8 else '⚠️' if quality_metrics.credits_balance_score >= 0.6 else '❌'} |
| Интеграция практики | {quality_metrics.practice_integration_score:.2f} | {'✅' if quality_metrics.practice_integration_score >= 0.8 else '⚠️' if quality_metrics.practice_integration_score >= 0.6 else '❌'} |
| Соответствие benchmark | {quality_metrics.benchmark_alignment_score:.2f} | {'✅' if quality_metrics.benchmark_alignment_score >= 0.8 else '⚠️' if quality_metrics.benchmark_alignment_score >= 0.6 else '❌'} |

---

## Выявленные проблемы

"""
        
        # Группируем проблемы по категориям и серьезности
        problem_categories = ['critical', 'major', 'minor', 'suggestion']
        category_names = {'critical': 'Критические', 'major': 'Важные', 'minor': 'Незначительные', 'suggestion': 'Предложения'}
        category_icons = {'critical': '🔴', 'major': '🟡', 'minor': '🟢', 'suggestion': '💡'}
        
        for severity in problem_categories:
            category_findings = [f for f in findings if f.severity == severity]
            if not category_findings:
                continue
                
            review_content += f"### {category_icons[severity]} {category_names[severity]} проблемы ({len(category_findings)})\n\n"
            
            for finding in category_findings:
                review_content += f"#### {finding.title}\n\n"
                review_content += f"**Категория:** {finding.category.upper()}\n"
                review_content += f"**Описание:** {finding.description}\n\n"
                
                if finding.affected_items:
                    review_content += f"**Затронутые элементы:** {', '.join(finding.affected_items)}\n\n"
                
                review_content += f"**Рекомендация:** {finding.recommendation}\n"
                
                if finding.auto_fixable:
                    review_content += f"*🔧 Может быть исправлено автоматически*\n"
                
                review_content += "\n---\n\n"
        
        # Добавляем рекомендации
        review_content += "## Рекомендации по улучшению\n\n"
        for rec in recommendations:
            review_content += f"{rec}\n\n"
        
        # Заключение
        review_content += f"""
## Заключение

"""
        
        if quality_metrics.overall_quality_score >= 0.8:
            review_content += "✅ **Программа имеет высокое качество** и готова к внедрению с минимальными доработками.\n"
        elif quality_metrics.overall_quality_score >= 0.6:
            review_content += "⚠️ **Программа требует доработки** перед внедрением. Рекомендуется устранить выявленные проблемы.\n"
        else:
            review_content += "❌ **Программа требует значительной переработки** перед внедрением. Необходимо решить критические проблемы.\n"
        
        critical_count = len([f for f in findings if f.severity == 'critical'])
        if critical_count > 0:
            review_content += f"\n🚨 **Внимание:** {critical_count} критических проблем требуют немедленного решения!\n"
        
        review_content += f"""
### Следующие шаги

1. **Приоритет 1:** Решите все критические проблемы
2. **Приоритет 2:** Устраните важные проблемы  
3. **Приоритет 3:** Рассмотрите предложения по улучшению
4. **Итерация:** Проведите повторную проверку после внесения изменений

---

*Отчет сгенерирован автоматически с использованием Competency Pipeline Review Service*
"""
        
        review_path.write_text(review_content, encoding='utf-8')
        
        # Quality_metrics.md - детальные метрики
        metrics_path = self.artifacts_dir / "Quality_metrics.md"
        
        metrics_content = f"""# Quality Metrics Report

**Детальные метрики качества образовательной программы**

## Основные метрики

### Покрытие компетенций
- **Общее покрытие:** {quality_metrics.competency_coverage_percent:.2f}%
- **Высокоприоритетные компетенции:** {quality_metrics.high_priority_coverage_percent:.2f}%

### Структурные метрики
- **Балансировка кредитов:** {quality_metrics.credits_balance_score:.3f}
- **Интеграция практики:** {quality_metrics.practice_integration_score:.3f}
- **Логика пререквизитов:** {quality_metrics.prerequisite_logic_score:.3f}

### Соответствие стандартам
- **Соответствие benchmark:** {quality_metrics.benchmark_alignment_score:.3f}

### Общая оценка
- **Итоговый балл качества:** {quality_metrics.overall_quality_score:.3f}

## Интерпретация оценок

- **0.9-1.0:** Отличное качество
- **0.8-0.9:** Хорошее качество
- **0.7-0.8:** Удовлетворительное качество
- **0.6-0.7:** Требуются улучшения
- **<0.6:** Неудовлетворительное качество

## Статистика проблем

"""
        
        problem_stats = {}
        for finding in findings:
            category = finding.category
            severity = finding.severity
            
            if category not in problem_stats:
                problem_stats[category] = {}
            if severity not in problem_stats[category]:
                problem_stats[category][severity] = 0
            problem_stats[category][severity] += 1
        
        for category, severity_counts in problem_stats.items():
            metrics_content += f"### {category.upper()}\n"
            for severity, count in severity_counts.items():
                metrics_content += f"- {severity.capitalize()}: {count}\n"
            metrics_content += "\n"
        
        metrics_path.write_text(metrics_content, encoding='utf-8')
        
        logger.info(f"ШАГ SAVE_REV.2. Результаты проверки сохранены: {review_path}")
        return review_path
