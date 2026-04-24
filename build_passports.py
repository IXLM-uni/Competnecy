#!/usr/bin/env python3
"""Stage 3: объединить 5 md-профилей + 5 контекстов → единый каталог паспортов компетенций.

Один LLM-проход + автоматическая валидация:
- Coverage: % строк-компетенций из 5 профилей, покрытых паспортами
- Hallucinations: % технических терминов в паспортах, отсутствующих в корпусе

Цель: 100% coverage, 0% hallucinations. Итерация — ручная: смотреть отчёт, править промпт.

Usage:
    python build_passports.py [--input-dir artifacts/extracted_md] [--role "..."]
"""

import argparse
import asyncio
import logging
import re
import sys
from pathlib import Path

logging.basicConfig(level=logging.INFO, format="[%(levelname)s] %(message)s")
sys.path.insert(0, str(Path(__file__).parent))

from competency_pipeline import call_llm

SOURCES = ["hh", "telegram", "onet", "reddit", "sonar"]

PROMPT_TEMPLATE = """Тебе даны 10 md-файлов по роли: {role}
— 5 профилей компетенций (hh.md, telegram.md, onet.md, reddit.md, sonar.md)
— 5 контекстов роли (hh_context.md, telegram_context.md, onet_context.md, reddit_context.md, sonar_context.md)

Собери единый каталог паспортов компетенций.

ПАСПОРТ — 4 поля + источники:
- Формулировка: глагол 3-го лица + объект, буквально из корпуса
- Инструменты/технологии: конкретные названия (SQL, Power BI, Pandas, BPMN и т.д.), буквально из корпуса
- Контекст применения: домен/ситуация/команды-смежники — из любого из 10 файлов
- Типовые задачи: что решают этой компетенцией — из ЛЮБОГО из 10 файлов (и профили, и контексты)
- Источники: список меток [hh, telegram, onet, reddit, sonar] — в каких из 5 встречалась

ПРАВИЛА:
1. Все термины — только из корпуса. Нет слова в корпусе — нет его в паспорте.
2. Дедуп: одна компетенция, названная в разных источниках разными словами → ОДИН паспорт. В Источники пиши все метки, где она появилась.
3. Ничего не пропускать: каждая bullet-строка из любого из 5 профилей обязана попасть в каталог либо как отдельный паспорт, либо влиться в Инструменты/технологии или Типовые задачи существующего паспорта. НИ ОДНА строка не может просто исчезнуть.
4. Если поле не набирается из корпуса — «не упомянуто». Не выдумывать.
5. ОСОБО ПРО СТРОКИ-ТЕРМИНЫ БЕЗ ГЛАГОЛЬНОЙ ФОРМУЛИРОВКИ. В профилях (особенно reddit) встречаются пункты, состоящие только из названия технологии или термина: «- MongoDB», «- Hadoop», «- MLOps», «- A/B testing», «- Unicorn», «- AI Expert», «- Business Objects». Каждый такой термин ОБЯЗАН попасть в Инструменты/технологии тематически подходящего паспорта (MongoDB/PostgreSQL → паспорт про БД, Hadoop/Spark → паспорт про Big Data, MLOps/A/B testing → паспорт про ML или A/B-тестирование). Если тематический паспорт не подходит — создай отдельный паспорт с формулировкой «Знаком с концепцией {термин}» или «Понимает специфику {термин}».
6. HH-компетенции тоже не пропускать. Даже если формулировка узкая («Экспериментирует с эмбеддингами», «Разрабатывает прототипы диалоговых ассистентов на базе LLM и агентных фреймворков») — каждая становится паспортом или вливается в существующий (например в паспорт про ML/AI).
7. SOFT SKILLS И БИЗНЕС-КОММУНИКАЦИЯ — это тоже компетенции. Формулировки типа «Обладает вниманием к деталям», «Помогает руководителям находить инсайты и точки роста», «Работает в условиях неопределённости» — обязаны попасть в каталог (отдельный soft-skills паспорт или как типовая задача в паспорте про коммуникацию/аналитическое мышление). Никакой soft skill из профиля не имеет права исчезнуть.
8. НЕ ВКЛЮЧАТЬ В КАТАЛОГ. Провайдеры курсов (Skillbox, Productstar, Eduson, T-Education) — это факты о рынке обучения, а не компетенции. Work Style descriptors из onet («Importance of Being Exact or Accurate», «Attention to Detail» как мета-описание) — это характеристики личности, не навыки для обучения, их игнорировать. Контекстуальные факты «Опыт в финансах/банках» — это требование к background, а не компетенция, их игнорировать. Эти три категории в каталог не попадают.

ФОРМАТ ВЫХОДА — строго markdown:

# Каталог паспортов компетенций — {role}

## {Тематическая категория}

### {Формулировка компетенции}
- Инструменты/технологии: {список через запятую или «не упомянуто»}
- Контекст применения: {текст или «не упомянуто»}
- Типовые задачи:
  - {задача 1}
  - {задача 2}
- Источники: [hh, telegram, onet]

САМОПРОВЕРКА (молча, перед выводом, в два прохода):
Проход 1 — ПОЛНОТА: пройди по каждой строке-пункту в каждом из 5 профилей. Для каждой проверь: есть ли паспорт в каталоге, покрывающий её? Если нет — добавь или расширь существующий (вплоть до включения термина в Инструменты).
Проход 2 — ЧИСТОТА: пройди по каждому паспорту. Для каждого термина (инструмент, аббревиатура, название задачи) проверь: встречается ли буквально в одном из 10 файлов? Если нет — удали термин.
Повторяй Проход 1 и Проход 2, пока 0 недостающих и 0 лишних.

После самопроверки выведи ТОЛЬКО итоговый md. Без преамбулы, без отчёта о проверке, без мета-комментариев.

=== HH КОМПЕТЕНЦИИ ===
{hh_md}

=== HH КОНТЕКСТ ===
{hh_context_md}

=== TELEGRAM КОМПЕТЕНЦИИ ===
{telegram_md}

=== TELEGRAM КОНТЕКСТ ===
{telegram_context_md}

=== ONET КОМПЕТЕНЦИИ ===
{onet_md}

=== ONET КОНТЕКСТ ===
{onet_context_md}

=== REDDIT КОМПЕТЕНЦИИ ===
{reddit_md}

=== REDDIT КОНТЕКСТ ===
{reddit_context_md}

=== SONAR КОМПЕТЕНЦИИ ===
{sonar_md}

=== SONAR КОНТЕКСТ ===
{sonar_context_md}

---

Итоговый каталог паспортов:
"""


def load_corpus(input_dir: Path) -> dict[str, str]:
    """Читает 10 md-файлов."""
    corpus = {}
    for src in SOURCES:
        prof = input_dir / f"{src}.md"
        ctx = input_dir / f"{src}_context.md"
        if not prof.exists() or not ctx.exists():
            raise FileNotFoundError(f"Нет файла для источника {src}: {prof} / {ctx}")
        corpus[f"{src}_md"] = prof.read_text(encoding="utf-8")
        corpus[f"{src}_context_md"] = ctx.read_text(encoding="utf-8")
    return corpus


def extract_competency_bullets(md: str) -> list[str]:
    """Из md профиля вытаскиваем строки-пункты формата `- ...` под заголовками `##`."""
    bullets = []
    for line in md.split("\n"):
        line = line.strip()
        if line.startswith("- ") and len(line) > 4:
            bullets.append(line[2:].strip())
    return bullets


# Кандидаты в «технические термины» для hallucination-проверки:
# заглавные аббревиатуры 2-8 букв, CamelCase/kebab-case названия, слова с цифрами.
TERM_PATTERNS = [
    re.compile(r"\b[A-Z]{2,8}\b"),  # SQL, BPMN, NPS, ETL
    re.compile(r"\b[A-Z][a-z]+(?:[A-Z][a-z]+)+\b"),  # PowerBI, DataLens, Kubernetes
    re.compile(r"\b[A-Za-z]+[0-9]+[A-Za-z]*\b"),  # H3, S2, IFRS9, 115-ФЗ-adj
    re.compile(r"\bApache\s+\w+\b"),  # Apache Airflow, Apache Superset
    re.compile(r"\b[A-Z][a-z]{2,}\b"),  # Python, Tableau, Vertica
]


def extract_terms(text: str) -> set[str]:
    """Извлекает кандидатные технические термины из текста."""
    terms = set()
    for pat in TERM_PATTERNS:
        for m in pat.findall(text):
            if isinstance(m, str) and len(m) >= 2:
                terms.add(m.strip())
    # Фильтр: выкидываем явные русские слова в Capitalize (Python-regex такое ловит)
    terms = {t for t in terms if not re.match(r"^[А-ЯЁ][а-яё]+$", t)}
    return terms


# Компетенции, которые по дизайну НЕ должны попадать в каталог (они не компетенции):
# провайдеры курсов (рыночный факт), work style/trait из onet (черта личности, не навык),
# контекстуальные факты (background требования).
NOT_A_COMPETENCY_MARKERS = [
    "skillbox", "productstar", "eduson", "t-education", "sf education",
    "importance of being exact", "attention to detail",
    "опыт в финансах", "опыт в банк",
]


def measure_coverage(passports_md: str, profiles: dict[str, str]) -> tuple[float, list[str]]:
    """Coverage: какая доля компетенций из 5 профилей попала в паспорта.
    Маппинг — по наличию хотя бы одного содержательного слова (длина ≥5) из bullet в паспортах.
    Bullet'ы в белом списке исключений (провайдеры курсов / work-style traits / background требования)
    исключаются из знаменателя.
    """
    passports_low = passports_md.lower()
    all_bullets: list[tuple[str, str]] = []
    for src, md in profiles.items():
        for b in extract_competency_bullets(md):
            b_low = b.lower()
            if any(m in b_low for m in NOT_A_COMPETENCY_MARKERS):
                continue  # исключаем не-компетенции из подсчёта
            all_bullets.append((src, b))

    if not all_bullets:
        return 1.0, []

    missing = []
    hit = 0
    for src, b in all_bullets:
        # Содержательные слова: длина ≥5, не служебные
        words = [w.lower() for w in re.findall(r"[A-Za-zА-Яа-яЁё0-9]+", b) if len(w) >= 5]
        if not words:
            hit += 1
            continue
        # Считаем bullet покрытым, если ≥1 содержательное слово появилось в passports_md
        if any(w in passports_low for w in words):
            hit += 1
        else:
            missing.append(f"[{src}] {b[:120]}")

    return hit / len(all_bullets), missing


def measure_hallucinations(passports_md: str, corpus_full: str) -> tuple[float, list[str]]:
    """Hallucinations: какая доля технических терминов в паспортах отсутствует в корпусе."""
    passport_terms = extract_terms(passports_md)
    corpus_low = corpus_full.lower()

    if not passport_terms:
        return 0.0, []

    hallucinated = []
    for t in passport_terms:
        if t.lower() not in corpus_low:
            hallucinated.append(t)

    return len(hallucinated) / len(passport_terms), hallucinated


async def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--input-dir", default="artifacts/extracted_md")
    parser.add_argument("--role", default="Аналитик Данных в банке со знанием xlsx, vba + sql, а также умением подготавливать презентации руководству и автоматизировать процессы")
    parser.add_argument("--output", default="artifacts/extracted_md/competency_passports.md")
    parser.add_argument("--max-tokens", type=int, default=16000)
    args = parser.parse_args()

    input_dir = Path(args.input_dir)
    corpus = load_corpus(input_dir)

    prompt = PROMPT_TEMPLATE.replace("{role}", args.role)
    for key, val in corpus.items():
        prompt = prompt.replace("{" + key + "}", val)
    print(f"[INFO] Промпт: {len(prompt)} символов (~{len(prompt)//4} токенов)")
    print(f"[INFO] Вызываю LLM (max_output_tokens={args.max_tokens})...")

    result = await call_llm(
        prompt,
        temperature=0.0,
        max_output_tokens=args.max_tokens,
        streaming=True,
        system_message="Ты собираешь каталог паспортов компетенций из мульти-источникового корпуса. Только факты из корпуса. 100% покрытие, 0% галлюцинаций.",
    )

    if not result:
        print("[ERROR] LLM вернул пустой ответ")
        return

    output_path = Path(args.output)
    output_path.write_text(result, encoding="utf-8")
    print(f"[OK] Каталог сохранён: {output_path} ({len(result)} символов)")

    # Валидация
    print("\n" + "=" * 60)
    print("ВАЛИДАЦИЯ")
    print("=" * 60)

    profiles = {src: corpus[f"{src}_md"] for src in SOURCES}
    corpus_full = "\n".join(corpus.values())

    coverage, missing = measure_coverage(result, profiles)
    halluc_rate, halluc_terms = measure_hallucinations(result, corpus_full)

    print(f"\n[COVERAGE]  {coverage*100:.1f}% ({len(missing)} недостающих компетенций)")
    print(f"[HALLUCIN]  {halluc_rate*100:.1f}% ({len(halluc_terms)} подозрительных терминов)")

    if missing:
        print(f"\n--- Недостающие компетенции (первые 20) ---")
        for m in missing[:20]:
            print(f"  · {m}")
        if len(missing) > 20:
            print(f"  ... и ещё {len(missing) - 20}")

    if halluc_terms:
        print(f"\n--- Подозрительные термины (первые 30) ---")
        for t in halluc_terms[:30]:
            print(f"  · {t}")
        if len(halluc_terms) > 30:
            print(f"  ... и ещё {len(halluc_terms) - 30}")

    if coverage >= 0.99 and halluc_rate <= 0.01:
        print("\n[✓] ЦЕЛЬ ДОСТИГНУТА: 100% coverage, 0% hallucinations")
    else:
        print("\n[!] ЦЕЛЬ НЕ ДОСТИГНУТА — править промпт и повторить")


if __name__ == "__main__":
    asyncio.run(main())
