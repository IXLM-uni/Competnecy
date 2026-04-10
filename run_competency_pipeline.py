#!/usr/bin/env python3
"""
CLI RUNNER ДЛЯ COMPETENCY PIPELINE

Скрипт для удобного запуска Competency Intelligence Pipeline из командной строки.
Поддерживает различные режимы запуска и конфигурации.

Использование:
    python run_competency_pipeline.py --role "Data Scientist" --output ./artifacts
    python run_competency_pipeline.py --role "DevOps Engineer" --resume-from evidence_synthesis
    python run_competency_pipeline.py --config pipeline_config.json

Возможности:
- Полный запуск pipeline с нуля
- Возобновление с определенного этапа
- Настройка источников данных
- Интерактивный режим
- Подробный прогресс-репортинг

Требования:
- Python 3.8+
- Настроенные Global_services/AI
- Доступ к интернету для поиска источников
"""

import asyncio
import argparse
import sys
import json
import logging
from pathlib import Path
from typing import Optional, Dict, Any
from datetime import datetime

# Настройка логирования
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    handlers=[
        logging.StreamHandler(sys.stdout),
        logging.FileHandler('competency_pipeline.log', encoding='utf-8')
    ]
)

# Добавляем путь к модулю pipeline
sys.path.append(str(Path(__file__).parent))

try:
    from competency_pipeline.pipeline_orchestrator import (
        CompetencyPipelineOrchestrator,
        PipelineConfig,
        PipelineStage,
        run_full_pipeline,
        resume_pipeline_from_stage,
        create_source_specs_for_role
    )
    from competency_pipeline.research_ingestion_service import SourceSpec
except ImportError as e:
    print(f"❌ Ошибка импорта: {e}")
    print("Убедитесь, что все модули competency_pipeline находятся в правильном месте")
    sys.exit(1)

def print_header():
    """Вывод заголовка приложения"""
    print("=" * 70)
    print("🎓 COMPETENCY INTELLIGENCE PIPELINE")
    print("    Система интеллектуального анализа компетенций")
    print("=" * 70)
    print()

def print_stage_progress(stage: PipelineStage, status: str = "running"):
    """Вывод прогресса этапа"""
    stage_names = {
        PipelineStage.ROLE_FRAMING: "🎯 Определение роли",
        PipelineStage.RESEARCH_INGESTION: "🔍 Сбор источников", 
        PipelineStage.EVIDENCE_SYNTHESIS: "📝 Синтез доказательств",
        PipelineStage.COMPETENCY_PROFILE: "🎯 Профиль компетенций",
        PipelineStage.PROGRAM_BLUEPRINT: "🏗️ Структура программы",
        PipelineStage.CURRICULUM_TABLE: "📋 Учебный план",
        PipelineStage.REVIEW_CORRECTION: "✅ Экспертная проверка"
    }
    
    status_icons = {
        "running": "⏳",
        "completed": "✅", 
        "failed": "❌",
        "skipped": "⏭️"
    }
    
    stage_name = stage_names.get(stage, stage.name)
    status_icon = status_icons.get(status, "❓")
    
    print(f"{status_icon} Этап {stage.value}: {stage_name}")

def create_interactive_config() -> PipelineConfig:
    """Интерактивное создание конфигурации"""
    print("📋 ИНТЕРАКТИВНАЯ НАСТРОЙКА PIPELINE")
    print("-" * 50)
    
    # Основные параметры
    role_scope = input("Введите целевую роль (например 'Data Scientist'): ").strip()
    if not role_scope:
        print("❌ Роль не может быть пустой!")
        sys.exit(1)
    
    artifacts_dir = input("Директория для результатов [./artifacts]: ").strip() or "./artifacts"
    
    try:
        duration = int(input("Длительность программы в семестрах [4]: ") or "4")
    except ValueError:
        duration = 4
        print("⚠️ Использую дефолтную длительность: 4 семестра")
    
    # Источники данных
    print("\n🔍 НАСТРОЙКА ИСТОЧНИКОВ ДАННЫХ")
    use_default_sources = input("Использовать стандартные источники? [y/n]: ").lower() in ['y', 'yes', 'да', '']
    
    source_specs = []
    if use_default_sources:
        source_specs = create_source_specs_for_role(role_scope)
        print(f"✅ Настроено {len(source_specs)} стандартных источников")
    else:
        print("⚠️ Будут использованы базовые источники")
    
    # Дополнительные опции
    print("\n⚙️ ДОПОЛНИТЕЛЬНЫЕ ОПЦИИ")
    skip_stages = []
    
    if input("Пропустить Telegram источники? [y/n]: ").lower() in ['y', 'yes', 'да']:
        # Фильтруем telegram источники
        source_specs = [s for s in source_specs if s.source_type != 'telegram']
        print("✅ Telegram источники исключены")
    
    print("\n✨ Конфигурация готова!")
    print(f"   Роль: {role_scope}")
    print(f"   Директория: {artifacts_dir}")
    print(f"   Семестры: {duration}")
    print(f"   Источников: {len(source_specs)}")
    
    return PipelineConfig(
        role_scope=role_scope,
        artifacts_dir=artifacts_dir,
        program_duration_semesters=duration,
        source_specifications=source_specs,
        skip_stages=skip_stages
    )

def load_config_from_file(config_path: str) -> PipelineConfig:
    """Загрузка конфигурации из JSON файла"""
    config_file = Path(config_path)
    if not config_file.exists():
        print(f"❌ Файл конфигурации не найден: {config_path}")
        sys.exit(1)
    
    try:
        with open(config_file, 'r', encoding='utf-8') as f:
            config_data = json.load(f)
        
        # Конвертируем source_specifications
        source_specs = []
        for spec_data in config_data.get('source_specifications', []):
            source_specs.append(SourceSpec(
                source_type=spec_data['source_type'],
                query=spec_data['query'],
                filters=spec_data.get('filters'),
                limit=spec_data.get('limit', 20),
                priority=spec_data.get('priority', 'medium')
            ))
        
        # Конвертируем skip_stages
        skip_stages = []
        for stage_name in config_data.get('skip_stages', []):
            try:
                skip_stages.append(PipelineStage[stage_name])
            except KeyError:
                print(f"⚠️ Неизвестный этап: {stage_name}")
        
        # Конвертируем resume_from_stage
        resume_from = None
        if config_data.get('resume_from_stage'):
            try:
                resume_from = PipelineStage[config_data['resume_from_stage']]
            except KeyError:
                print(f"⚠️ Неизвестный этап для возобновления: {config_data['resume_from_stage']}")
        
        return PipelineConfig(
            role_scope=config_data['role_scope'],
            artifacts_dir=config_data.get('artifacts_dir', './artifacts'),
            program_duration_semesters=config_data.get('program_duration_semesters', 4),
            source_specifications=source_specs,
            skip_stages=skip_stages,
            resume_from_stage=resume_from
        )
        
    except json.JSONDecodeError as e:
        print(f"❌ Ошибка парсинга JSON: {e}")
        sys.exit(1)
    except Exception as e:
        print(f"❌ Ошибка загрузки конфигурации: {e}")
        sys.exit(1)

def save_example_config():
    """Создание примера конфигурации"""
    example_config = {
        "role_scope": "Data Scientist",
        "artifacts_dir": "./artifacts",
        "program_duration_semesters": 4,
        "source_specifications": [
            {
                "source_type": "web_search",
                "query": "Data Scientist professional requirements skills",
                "limit": 25,
                "priority": "high"
            },
            {
                "source_type": "hh_vacancies", 
                "query": "Data Scientist",
                "limit": 20,
                "priority": "high"
            },
            {
                "source_type": "semantic_scholar",
                "query": "Data Science education curriculum competency-based",
                "limit": 15,
                "priority": "medium"
            }
        ],
        "skip_stages": [],
        "resume_from_stage": None
    }
    
    config_path = "example_pipeline_config.json"
    with open(config_path, 'w', encoding='utf-8') as f:
        json.dump(example_config, f, indent=2, ensure_ascii=False)
    
    print(f"✅ Пример конфигурации сохранен: {config_path}")

async def run_pipeline_with_progress(config: PipelineConfig) -> Dict[str, Any]:
    """Запуск pipeline с визуализацией прогресса"""
    print("\n🚀 ЗАПУСК COMPETENCY PIPELINE")
    print("-" * 50)
    print(f"Роль: {config.role_scope}")
    print(f"Артефакты: {config.artifacts_dir}")
    print(f"Начинаем: {datetime.now().strftime('%H:%M:%S')}")
    print()
    
    # Создаем оркестратор
    orchestrator = CompetencyPipelineOrchestrator(config)
    
    # Переопределяем методы для отображения прогресса
    original_stage_handlers = dict(orchestrator.stage_handlers)
    
    for stage, handler in original_stage_handlers.items():
        async def wrapped_handler(stage=stage, handler=handler):
            print_stage_progress(stage, "running")
            try:
                result = await handler()
                print_stage_progress(stage, "completed")
                return result
            except Exception as e:
                print_stage_progress(stage, "failed")
                print(f"   ❌ Ошибка: {e}")
                raise
        
        orchestrator.stage_handlers[stage] = wrapped_handler
    
    # Запускаем pipeline
    try:
        result = await orchestrator.run_pipeline()
        
        print("\n🎉 PIPELINE ЗАВЕРШЕН!")
        print("-" * 50)
        
        if result['success']:
            print("✅ Статус: УСПЕШНО")
            print(f"⏱️ Время выполнения: {result['duration_seconds']:.1f} секунд")
            print(f"📁 Создано файлов: {sum(len(files) for files in result['artifacts'].values())}")
            
            if result['errors']:
                print(f"⚠️ Предупреждений: {len(result['errors'])}")
            
            print(f"\n📋 Основные результаты:")
            print(f"   📄 {result.get('final_report', 'Pipeline_Report.md')}")
            print(f"   📊 Review_Notes.md - экспертная оценка")
            print(f"   🎓 Program_Blueprint.md - образовательная программа")
            
        else:
            print("❌ Статус: ОШИБКА")
            print(f"🔥 Причина: {result.get('error', 'Неизвестная ошибка')}")
        
        return result
        
    except KeyboardInterrupt:
        print("\n⏹️ Выполнение прервано пользователем")
        return {'success': False, 'error': 'Interrupted by user'}
    except Exception as e:
        print(f"\n💥 Фатальная ошибка: {e}")
        return {'success': False, 'error': str(e)}

def parse_arguments():
    """Парсинг аргументов командной строки"""
    parser = argparse.ArgumentParser(
        description='Competency Intelligence Pipeline - система анализа компетенций',
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Примеры использования:
  %(prog)s --role "Data Scientist" 
  %(prog)s --role "DevOps Engineer" --output ./my_artifacts --semesters 6
  %(prog)s --config my_config.json
  %(prog)s --interactive
  %(prog)s --resume-from competency_profile --role "Product Manager"
  %(prog)s --create-example-config
        """
    )
    
    # Основные параметры
    parser.add_argument('--role', type=str, help='Целевая роль для анализа')
    parser.add_argument('--output', type=str, default='./artifacts', 
                       help='Директория для артефактов (по умолчанию: ./artifacts)')
    parser.add_argument('--semesters', type=int, default=4,
                       help='Длительность программы в семестрах (по умолчанию: 4)')
    
    # Режимы работы
    parser.add_argument('--interactive', '-i', action='store_true',
                       help='Интерактивный режим настройки')
    parser.add_argument('--config', type=str,
                       help='Путь к JSON файлу с конфигурацией')
    parser.add_argument('--create-example-config', action='store_true',
                       help='Создать пример файла конфигурации')
    
    # Управление выполнением
    parser.add_argument('--resume-from', type=str,
                       choices=['role_framing', 'research_ingestion', 'evidence_synthesis', 
                              'competency_profile', 'program_blueprint', 'curriculum_table', 
                              'review_correction'],
                       help='Возобновить с определенного этапа')
    
    # Опции источников
    parser.add_argument('--no-telegram', action='store_true',
                       help='Исключить Telegram источники')
    parser.add_argument('--no-linkedin', action='store_true', 
                       help='Исключить LinkedIn источники')
    parser.add_argument('--academic-only', action='store_true',
                       help='Использовать только академические источники')
    
    # Отладка
    parser.add_argument('--verbose', '-v', action='store_true',
                       help='Подробный вывод')
    parser.add_argument('--log-file', type=str,
                       help='Файл для логов (по умолчанию: competency_pipeline.log)')
    
    return parser.parse_args()

def setup_logging(verbose: bool = False, log_file: Optional[str] = None):
    """Настройка логирования"""
    level = logging.DEBUG if verbose else logging.INFO
    
    handlers = [logging.StreamHandler(sys.stdout)]
    
    if log_file:
        handlers.append(logging.FileHandler(log_file, encoding='utf-8'))
    
    logging.basicConfig(
        level=level,
        format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
        handlers=handlers,
        force=True
    )

def create_config_from_args(args) -> PipelineConfig:
    """Создание конфигурации из аргументов командной строки"""
    
    # Определяем этап для возобновления
    resume_from = None
    if args.resume_from:
        stage_mapping = {
            'role_framing': PipelineStage.ROLE_FRAMING,
            'research_ingestion': PipelineStage.RESEARCH_INGESTION,
            'evidence_synthesis': PipelineStage.EVIDENCE_SYNTHESIS,
            'competency_profile': PipelineStage.COMPETENCY_PROFILE,
            'program_blueprint': PipelineStage.PROGRAM_BLUEPRINT,
            'curriculum_table': PipelineStage.CURRICULUM_TABLE,
            'review_correction': PipelineStage.REVIEW_CORRECTION
        }
        resume_from = stage_mapping[args.resume_from]
    
    # Создаем спецификации источников
    source_specs = create_source_specs_for_role(args.role)
    
    # Применяем фильтры источников
    if args.no_telegram:
        source_specs = [s for s in source_specs if s.source_type != 'telegram']
    
    if args.no_linkedin:
        source_specs = [s for s in source_specs if s.source_type != 'linkedin']
    
    if args.academic_only:
        source_specs = [s for s in source_specs if s.source_type in ['semantic_scholar', 'web_search']]
        # Оставляем только академические запросы в web_search
        for spec in source_specs:
            if spec.source_type == 'web_search':
                spec.query += " academic research education"
    
    return PipelineConfig(
        role_scope=args.role,
        artifacts_dir=args.output,
        program_duration_semesters=args.semesters,
        source_specifications=source_specs,
        resume_from_stage=resume_from
    )

async def main():
    """Главная функция"""
    args = parse_arguments()
    
    # Настройка логирования
    setup_logging(args.verbose, args.log_file)
    
    print_header()
    
    # Специальные команды
    if args.create_example_config:
        save_example_config()
        return
    
    # Определяем конфигурацию
    config = None
    
    if args.interactive:
        config = create_interactive_config()
    elif args.config:
        config = load_config_from_file(args.config)
    elif args.role:
        config = create_config_from_args(args)
    else:
        print("❌ Не указана роль для анализа!")
        print("Используйте --role 'Название роли' или --interactive для настройки")
        print("Для справки: python run_competency_pipeline.py --help")
        sys.exit(1)
    
    # Проверяем конфигурацию
    if not config.role_scope.strip():
        print("❌ Роль не может быть пустой!")
        sys.exit(1)
    
    # Запускаем pipeline
    result = await run_pipeline_with_progress(config)
    
    # Определяем код выхода
    sys.exit(0 if result['success'] else 1)

if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        print("\n⏹️ Выполнение прервано")
        sys.exit(1)
    except Exception as e:
        print(f"\n💥 Неожиданная ошибка: {e}")
        sys.exit(1)
