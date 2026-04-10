# Competency Intelligence Pipeline

**Система интеллектуального анализа компетенций для создания образовательных программ**

🎓 Автоматическое создание competency-based образовательных программ из анализа профессиональной деятельности

---

## Обзор

Competency Intelligence Pipeline - это полностью автоматизированная система, которая:

1. **Собирает данные** из множественных источников (вакансии, академические статьи, профстандарты)
2. **Синтезирует evidence** о реальной профессиональной деятельности  
3. **Генерирует профиль компетенций** в образовательном формате
4. **Создает образовательную программу** с дисциплинами, практиками и проектами
5. **Проводит экспертную проверку** качества программы

## Ключевые принципы

- ✅ **Markdown-first** - все артефакты в человеко-читаемом формате
- ✅ **Evidence-based** - программы строятся на анализе реальной деятельности
- ✅ **Traceability** - каждый вывод связан с источниками
- ✅ **Competency-based design** - от компетенций к дисциплинам, не наоборот
- ✅ **Multi-source intelligence** - интеграция web, API и файловых источников

## Архитектура Pipeline

### 6 этапов обработки:

```
Stage 0: Role framing          → role_scope.md
Stage 1: Research ingestion    → raw_corpus/, manifest, registry  
Stage 2: Evidence synthesis    → Evidence.md
Stage 3: Competency profile    → Competency_Profile.md
Stage 4: Program blueprint     → Program_Blueprint.md  
Stage 5: Curriculum table      → Curriculum_Table.md
Stage 6: Review & correction   → Review_Notes.md
```

### Сервисы Pipeline:

- **`research_ingestion_service`** - сбор из web, hh.ru, Telegram, LinkedIn, Semantic Scholar
- **`evidence_synthesis_service`** - markdown-to-markdown синтез доказательств
- **`competency_profile_service`** - генерация образовательных компетенций
- **`curriculum_generation_service`** - создание программ с часами/кредитами/семестрами
- **`review_service`** - multi-pass экспертная проверка качества
- **`pipeline_orchestrator`** - координация всех этапов с error recovery

## Быстрый старт

### Предварительные требования

- Python 3.8+
- Настроенные `Global_services/AI` (LLM, Crawler, Qdrant, Semantic Scholar)
- Доступ к интернету для поиска источников

### Установка

```bash
cd /home/alexander/Projects/Competnecy
# Убедитесь, что Global_services уже настроен
ls Global_services/AI/  # Должны быть llm_service.py, llm_webcrawler.py и т.д.
```

### Простейший запуск

```bash
# Создание программы для Data Scientist
python run_competency_pipeline.py --role "Data Scientist"

# Программа для DevOps Engineer на 6 семестров  
python run_competency_pipeline.py --role "DevOps Engineer" --semesters 6

# Интерактивный режим с настройками
python run_competency_pipeline.py --interactive

# Возобновление с определенного этапа
python run_competency_pipeline.py --role "Product Manager" --resume-from competency_profile
```

### Настройка через конфигурацию

```bash
# Создать пример конфигурации
python run_competency_pipeline.py --create-example-config

# Запуск с конфигурацией
python run_competency_pipeline.py --config example_pipeline_config.json
```

## Примеры конфигурации источников

### Для технических ролей
```python
source_specs = [
    SourceSpec('web_search', 'Senior Python Developer requirements', limit=25, priority='high'),
    SourceSpec('hh_vacancies', 'Python Developer', limit=20, priority='high'),
    SourceSpec('semantic_scholar', 'software engineering education curriculum', limit=15),
    SourceSpec('linkedin', 'Python Developer skills', limit=15),
]
```

### Для бизнес-ролей
```python
source_specs = [
    SourceSpec('web_search', 'Product Manager competencies', limit=25, priority='high'),
    SourceSpec('hh_vacancies', 'Product Manager', limit=20, priority='high'),
    SourceSpec('telegram', 'product management career', limit=10),
    SourceSpec('semantic_scholar', 'MBA curriculum product management', limit=10),
]
```

## Результаты Pipeline

После выполнения в директории `artifacts/` создаются:

### Основные артефакты
- **`Evidence.md`** - структурированный анализ профессиональной деятельности
- **`Competency_Profile.md`** - профиль компетенций с индикаторами достижения  
- **`Program_Blueprint.md`** - структура образовательной программы по модулям
- **`Curriculum_Table.md`** - детальный учебный план с часами/кредитами
- **`Review_Notes.md`** - экспертная оценка качества программы

### Вспомогательные артефакты
- **`role_scope.md`** - определение границ анализируемой роли
- **`raw_corpus_manifest.md`** - индекс собранных источников
- **`Competency_matrix.md`** - матрица покрытия компетенций
- **`Pipeline_Report.md`** - итоговый отчет о выполнении

## Интеграция с Global Services

Pipeline использует готовые сервисы:

- **`AI/llm_service.py`** - LLM orchestration, query processing
- **`AI/llm_webcrawler.py`** - web search, page crawling, content extraction  
- **`AI/llm_semantic_scholar.py`** - academic paper search and analysis
- **`AI/llm_qdrant.py`** - vector storage for RAG (если используется)

### Переменные окружения (.env)

```bash
# LLM
OPENAI_API_KEY=your_key
OPENAI_MODEL=gpt-4
OPENAI_BASE_URL=https://api.openai.com/v1

# Crawler
CRAWLER_BASE_URL=http://localhost:8321

# Semantic Scholar  
S2_API_KEY=your_s2_key
S2_RATE_LIMIT_DELAY=0.6

# Qdrant (опционально)
QDRANT_URL=http://localhost:6333
```

## Продвинутое использование

### Программный интерфейс

```python
from competency_pipeline import run_full_pipeline, create_source_specs_for_role

# Полный запуск
result = await run_full_pipeline(
    role_scope="UX/UI Designer",
    artifacts_dir="./ux_designer_program",
    program_duration_semesters=4
)

# Кастомные источники
source_specs = create_source_specs_for_role("Machine Learning Engineer")
source_specs.append(SourceSpec('file_upload', './custom_ml_standards.pdf'))

result = await run_full_pipeline(
    role_scope="ML Engineer",
    source_specs=source_specs
)
```

### Возобновление после ошибок

```python
from competency_pipeline import resume_pipeline_from_stage, PipelineStage

# Возобновление с этапа компетенций
result = await resume_pipeline_from_stage(
    stage=PipelineStage.COMPETENCY_PROFILE,
    role_scope="Data Analyst",
    artifacts_dir="./existing_artifacts"
)
```

### Кастомизация источников

```python
# Только академические источники
source_specs = [
    SourceSpec('semantic_scholar', 'computer science education curriculum', limit=30),
    SourceSpec('web_search', 'CS degree curriculum university', limit=20),
]

# Исключение социальных сетей
source_specs = create_source_specs_for_role("Software Architect")
source_specs = [s for s in source_specs if s.source_type not in ['telegram', 'linkedin']]
```

## Мониторинг и отладка

### Логирование

```bash
# Подробные логи
python run_competency_pipeline.py --role "DevOps" --verbose

# Кастомный файл логов
python run_competency_pipeline.py --role "DevOps" --log-file ./pipeline.log
```

### Проверка состояния

```bash
# Проверка созданных артефактов
ls -la artifacts/
cat artifacts/Pipeline_Report.md

# Анализ качества программы  
cat artifacts/Review_Notes.md
cat artifacts/Quality_metrics.md
```

## Решение проблем

### Частые ошибки

1. **Ошибка импорта Global_services**
   ```bash
   # Проверьте структуру
   ls Global_services/AI/llm_service.py
   ```

2. **Ошибка подключения к Crawler**
   ```bash
   # Запустите crawler server
   cd Global_services/AI
   python crawler_server.py
   ```

3. **Rate limiting на источниках**
   ```bash
   # Уменьшите лимиты в конфигурации
   "limit": 10  # вместо 25
   ```

### Отладочные опции

```bash
# Пропустить проблемные источники
python run_competency_pipeline.py --role "Analyst" --no-telegram --no-linkedin

# Только веб-источники
python run_competency_pipeline.py --role "Designer" --academic-only

# Минимальная конфигурация
python run_competency_pipeline.py --role "Manager" --semesters 2
```

## Развитие и кастомизация

### Добавление новых источников

1. Расширьте `research_ingestion_service.py`:
   ```python
   async def _collect_custom_source(self, spec: SourceSpec, role_scope: str):
       # Ваша логика сбора данных
       pass
   ```

2. Добавьте обработку в `collect_sources()`:
   ```python
   elif spec.source_type == 'custom_source':
       artifacts = await self._collect_custom_source(spec, role_scope)
   ```

### Кастомизация LLM prompts

Все промпты находятся в соответствующих сервисах:
- Evidence synthesis: `evidence_synthesis_service.py`
- Competency formulation: `competency_profile_service.py`  
- Curriculum generation: `curriculum_generation_service.py`

### Интеграция с внешними системами

```python
# Экспорт в LMS
def export_to_moodle(curriculum_data):
    # Конвертация в Moodle backup format
    pass

# Интеграция с университетскими системами
def sync_with_university_api(program_data):
    # Синхронизация с учебными планами
    pass
```

## Лицензия

MIT License - детали в файле `LICENSE`

## Поддержка

При возникновении проблем:

1. Проверьте логи: `competency_pipeline.log`
2. Изучите `Pipeline_Report.md` в директории артефактов
3. Используйте `--verbose` для детальной диагностики
4. Создайте issue с описанием проблемы и конфигурацией

---

**Создано с использованием Competency Intelligence Pipeline v1.0**
