# -*- coding: utf-8 -*-
"""
Руководство к файлу __init__.py (Preconditions)
================================================

Назначение:
    Корневой пакет Preconditions для e2e-тестирования.
    Содержит:
      - tools/         — моковые тулзы (calendar, calculator) для UC-5
      - audio/         — генерация тестового аудио для UC-3
      - RAG/           — Data.txt + ground_truth.csv для RAG-тестов
      - documents/     — тестовые документы (PDF, DOCX, MD, XLSX) для UC-2
      - setup_index.py — bulk-индексация в Qdrant
      - check_infra.py — проверка готовности инфраструктуры
"""
