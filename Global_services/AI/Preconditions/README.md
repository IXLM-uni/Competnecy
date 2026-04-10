# Preconditions — подготовка к e2e-тестам LLM-сервиса

## Структура

```
Preconditions/
├── __init__.py            # корневой пакет
├── README.md              # это файл
│
├── RAG/
│   ├── Data.txt           # Текст для RAG-индекса (методология описания деятельности)
│   └── ground_truth.csv   # Разметка: вопрос → ожидаемое ключевое слово
│
├── documents/             # Тестовые документы для UC-2 (инжест)
│   ├── Leaders Кирилл Гаврилов.pdf
│   ├── SKILL.md
│   ├── Интервью.docx
│   └── Таблица университетов.xlsx
│
├── audio/                 # Тестовое аудио для UC-3 (ASR)
│   ├── __init__.py
│   ├── generate_test_audio.py   # Генерирует test_tone.wav и test_silence.wav
│   ├── test_tone.wav            # (создаётся при запуске)
│   └── test_silence.wav         # (создаётся при запуске)
│
├── tools/                 # Моковые тулзы для UC-5
│   ├── __init__.py
│   ├── calendar_tool.py   # calendar_tool — фиксированные события
│   └── calculator_tool.py # calculator_tool — safe eval арифметики
│
├── check_infra.py         # Проверка готовности инфраструктуры
├── setup_index.py         # Bulk-индексация документов → Qdrant
└── conftest_e2e.py        # Pytest-фикстуры для e2e-тестов
```

## Пошаговый запуск

### 1. Поднять Qdrant (если ещё не запущен)

```bash
docker run -d --name qdrant -p 6333:6333 -p 6334:6334 qdrant/qdrant
```

### 2. Проверить .env

Файл `Global_services/.env` должен содержать:

```env
CLOUDRU_API_KEY=...
CLOUDRU_EMBED_MODEL=Qwen/Qwen3-Embedding-0.6B
CLOUDRU_BASE_URL=https://foundation-models.api.cloud.ru/v1
CLOUDRU_MODEL_NAME=zai-org/GLM-4.7
```

Опциональные (для Qdrant):
```env
QDRANT_HOST=localhost
QDRANT_PORT=6334
QDRANT_COLLECTION=e2e_test
```

### 3. Проверить инфраструктуру

```bash
cd /home/alexander/Projects/Global_services
python -m AI.Preconditions.check_infra
```

Скрипт последовательно проверяет:
- ШАГ 1: Переменные окружения
- ШАГ 2: Cloud.ru LLM API
- ШАГ 3: Cloud.ru Embedding API
- ШАГ 4: Cloud.ru ASR API
- ШАГ 5: Qdrant
- ШАГ 6: Наличие тестовых данных
- ШАГ 7: Итоговый отчёт

### 4. Проиндексировать данные в Qdrant

```bash
python -m AI.Preconditions.setup_index
```

Скрипт:
1. Собирает файлы из `documents/` и `RAG/Data.txt`
2. Инжестит (парсинг PDF/DOCX/TXT/MD) → чанки
3. Векторизует через Cloud.ru Embedding API
4. Записывает в Qdrant (коллекция `e2e_test`)

### 5. Запустить e2e-тесты

```bash
pytest AI/tests/e2e.py -v --tb=short -s
```

Или только конкретный UC:
```bash
pytest AI/tests/e2e.py -v -k "UC1"    # только RAG
pytest AI/tests/e2e.py -v -k "UC2"    # только документы
pytest AI/tests/e2e.py -v -k "UC3"    # только ASR
pytest AI/tests/e2e.py -v -k "UC4"    # только стриминг
pytest AI/tests/e2e.py -v -k "UC5"    # только tool calling
pytest AI/tests/e2e.py -v -k "Integration"  # интеграционные
```

### 6. Unit-тесты (без внешних сервисов)

```bash
pytest AI/tests/test_llm_service.py -v
```

## Зависимости

```
pytest
pytest-asyncio
python-dotenv
httpx
openai
qdrant-client
pydantic
python-docx     # для DOCX
PyMuPDF         # для PDF (fitz)
```

## Что добавлено в llm_service.py

- **`CloudRuEmbeddingClient`** — Embedding-клиент через Cloud.ru API (вместо локальных sentence-transformers)
- **`ingest_and_index()`** — Bulk-индексация: файлы → ingest → chunk → embed → upsert в Qdrant
- Обновлена фабрика `create_cloudru_embedding_client_from_env()` → возвращает `CloudRuEmbeddingClient`
