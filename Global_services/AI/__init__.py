# -*- coding: utf-8 -*-
"""
Руководство к пакету AI
======================

Назначение:
    Пакет AI содержит сервисы для работы с LLM, краулером и чанкингом.
    Основной модуль — llm_service.py с классами:
    - OpenAIClient — клиент для LLM API
    - CrawlerClient — клиент для краулера
    - Chunker — разбиение текста на чанки
    - RequestContext — контекст запроса
    - CrawlerQueryRewriter — генерация поисковых запросов
    - Snippet, DocumentChunk — модели данных

Структура:
    AI/
    ├── __init__.py          # Этот файл (делает AI пакетом)
    ├── llm_service.py       # Основной сервисный модуль
    ├── crawler_server.py    # FastAPI сервер для краулера
    ├── Preconditions/       # Предусловия и валидаторы
    ├── scripts/             # Скрипты use cases (UC_3.py, etc.)
    ├── models/              # LLM модели
    └── tests/               # Тесты

Использование:
    from AI.llm_service import OpenAIClient, CrawlerClient
"""

# Экспортируем основные классы для удобного импорта
# from AI.llm_service import (
#     OpenAIClient,
#     CrawlerClient,
#     Chunker,
#     RequestContext,
#     Snippet,
#     DocumentChunk,
# )
