# -*- coding: utf-8 -*-
"""
Руководство к файлу conftest.py (AI/tests)
==========================================

Назначение:
    Корневой conftest для pytest в директории tests/.
    Импортирует все фикстуры из AI/Preconditions/conftest_e2e.py,
    чтобы e2e.py и другие тесты могли использовать общие фикстуры
    (llm_client, orchestrator, embedding_client, и т.д.)

    Для unit-тестов (test_llm_service.py) фикстуры из conftest_e2e
    не мешают — они используют scope="session" и skip при отсутствии
    переменных окружения.
"""

from AI.Preconditions.conftest_e2e import *  # noqa: F401,F403
