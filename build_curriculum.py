#!/usr/bin/env python3
"""Stage C: syllabus-скелет из ранжированного каталога.

Из competencies_ranked.md (все 128 паспортов со Score/Tier) выбирает
Core + Important + Relevant и через LLM формирует:
  1. Модули (группировка по паспортам)
  2. Порядок прохождения (prerequisites)
  3. Capstone — интегративный проект

Выход: artifacts/extracted_md/curriculum.md

Ограничение (честное): это SYLLABUS-СКЕЛЕТ, не полная программа.
Без уровней освоения (emerging→mastery) и assessment-критериев — их нет в
рыночном корпусе.
"""

import argparse
import asyncio
import logging
import sys
from pathlib import Path

logging.basicConfig(level=logging.INFO, format="[%(levelname)s] %(message)s")
sys.path.insert(0, str(Path(__file__).parent))

from competency_pipeline import call_llm


PROMPT_CURRICULUM = """Тебе дан каталог паспортов компетенций для роли:
{role}

Паспорта уже размечены Tier: Core / Important / Relevant / Specific / Peripheral.

Задача: построй SYLLABUS-СКЕЛЕТ программы обучения на основе Core + Important + Relevant паспортов.

АЛГОРИТМ:

1. МОДУЛИ. Сгруппируй паспорта Core + Important + Relevant в тематические модули.
   Использовать категории `## ` из каталога как отправную точку, но объединяй/разделяй по смыслу.
   У каждого модуля — от 2 до 6 паспортов.

2. PREREQUISITES. Для каждого модуля определи, какие модули должны быть пройдены раньше.
   Основание: если в поле «Типовые задачи» модуля используется инструмент/знание из другого модуля — это зависимость.
   Пример: «Модуль 3: Построение DWH» требует «Модуль 1: SQL-запросы».

3. ПРОЕКТНЫЕ ЗАДАНИЯ. Для каждого модуля — 2-3 проектных задания из поля «Типовые задачи» паспортов (буквально из каталога).

4. ПОРЯДОК. Определи линейную последовательность модулей с вилками (параллельные ветки).

5. CAPSTONE. Интегративный проект уровня программы, который требует ВСЕ Core-паспорта и большинство Important.
   ТЗ — 2-3 абзаца реалистичного сценария из контекста роли (например, для аналитика банка — реальный кейс со скорингом или фрод-мониторингом).
   В конце — список компетенций, которые capstone проверяет.

ФОРМАТ ВЫХОДА — строго markdown:

# Программа обучения: {role}

## Обзор
- Число модулей: N
- Общее покрытие: X паспортов Core + Y Important + Z Relevant (всего X+Y+Z)
- Capstone: {короткое название}

## Структура модулей

### Модуль 1: {название}
- **Tier-состав:** {X Core, Y Important}
- **Компетенции:**
  - {паспорт 1 из каталога}
  - {паспорт 2}
- **Prerequisite:** нет
- **Проектные задания:**
  - {задание 1 из Типовых задач паспортов}
  - {задание 2}

### Модуль 2: ...

## Порядок прохождения

```
М1 → М2 → М3
      ↓
     М4 (параллельно с М3)
      ↓
     М5 → Capstone
```

## Capstone — интегративный проект

### Название
{название проекта, 1 строка}

### ТЗ
{реалистичный сценарий, 2-3 абзаца, использует доменные кейсы из контекстов роли}

### Проверяемые компетенции
- {список паспортов, которые capstone проверяет}

## Ограничения syllabus-скелета

- **Нет уровней освоения** (emerging/competent/proficient/mastery) — рыночный корпус не содержит этих данных, требует отдельного сбора (syllabi курсов, экспертный совет).
- **Нет assessment-критериев** — нет данных для rubrics. Для полноценной программы нужно добавить либо готовую рамку (Dreyfus / SFIA / Bloom), либо ручную работу методиста.
- Документ — это СКЕЛЕТ, который методист дорабатывает до полноценного curriculum.

ПРАВИЛА:
1. Используй только паспорта из категорий Core + Important + Relevant (не Specific, не Peripheral).
2. Формулировки компетенций и проектных заданий — БУКВАЛЬНО из каталога (не перефразируй).
3. Capstone ТЗ должно быть реалистичным — используй кейсы из контекстов роли (фрод, скоринг, клиентская сегментация для банка).

=== КАТАЛОГ ===
{catalog}

---

Syllabus-скелет:
"""


async def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--catalog", default="artifacts/extracted_md/competencies_ranked.md")
    parser.add_argument("--role", default="Аналитик Данных в банке со знанием xlsx, vba + sql, а также умением подготавливать презентации руководству и автоматизировать процессы")
    parser.add_argument("--output", default="artifacts/extracted_md/curriculum.md")
    parser.add_argument("--max-tokens", type=int, default=8000)
    args = parser.parse_args()

    catalog = Path(args.catalog).read_text(encoding="utf-8")

    prompt = PROMPT_CURRICULUM.replace("{role}", args.role).replace("{catalog}", catalog)
    print(f"[INFO] Промпт: {len(prompt)} символов (~{len(prompt)//4} токенов)")
    print(f"[INFO] Вызываю LLM (max_tokens={args.max_tokens}) ...")

    result = await call_llm(
        prompt,
        temperature=0.0,
        max_output_tokens=args.max_tokens,
        streaming=True,
        system_message="Ты строишь syllabus-скелет программы из ранжированного каталога компетенций. Только Core+Important+Relevant. Формулировки БУКВАЛЬНО из каталога.",
    )

    if not result:
        print("[ERROR] LLM вернул пустой ответ")
        return

    Path(args.output).write_text(result, encoding="utf-8")
    print(f"\n[OK] {args.output} ({len(result)} символов)")


if __name__ == "__main__":
    asyncio.run(main())
