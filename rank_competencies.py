#!/usr/bin/env python3
"""Stage 4: ранжировать паспорта компетенций по двухсигнальному скорингу.

Сигнал 1 — частота источников (0-5, из поля Источники в паспорте).
Сигнал 2 — центральность для роли (0-5, LLM на описании роли + 5 контекстах).
Score = S1 + S2, диапазон 0-10.

Tier:
  9-10 Core / 7-8 Important / 5-6 Relevant / 3-4 Specific / 0-2 Peripheral

Вход:
  artifacts/extracted_md/competency_passports.md (128 паспортов)
  artifacts/extracted_md/{src}_context.md × 5
  Описание роли (аргумент или из raw_corpus заголовка).

Выход:
  artifacts/extracted_md/competencies_ranked.md

Валидация:
  — каждый паспорт имеет поля Score и Tier
  — score ∈ [0, 10], tier соответствует score-диапазону
  — все 128 паспортов сохранены
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

TIER_RANGES = [
    (9, 10, "Core"),
    (7, 8, "Important"),
    (5, 6, "Relevant"),
    (3, 4, "Specific"),
    (0, 2, "Peripheral"),
]


def score_to_tier(score: int) -> str:
    for lo, hi, name in TIER_RANGES:
        if lo <= score <= hi:
            return name
    return "Unknown"


PROMPT_TEMPLATE = """Тебе дан каталог паспортов компетенций для роли:
{role}

И 5 контекстов роли.

Задача: для КАЖДОГО паспорта из каталога присвой Score 0-10 и Tier.

АЛГОРИТМ (для каждого паспорта):

Сигнал 1 — Частота источников (0-5).
Смотри «Источники: [...]» в паспорте. Число меток = баллы.

Сигнал 2 — Центральность для роли (0-5).
— 5: компетенция БУКВАЛЬНО в формулировке роли (SQL, xlsx, vba, презентации, автоматизация) ИЛИ в ≥3 контекстах
— 4: в ключевых секциях 2 контекстов (Hard skills / Core Tasks / Доменные кейсы)
— 3: в 1 контексте в ключевых секциях
— 2: косвенно связана с доменом банк/аналитика/данные
— 1: общая, не связана с контекстом
— 0: противоречит роли

Score = S1 + S2 (0-10).
Tier: 9-10 Core | 7-8 Important | 5-6 Relevant | 3-4 Specific | 0-2 Peripheral

ФОРМАТ ВЫХОДА — КОМПАКТНЫЙ, одна строка на паспорт:

### {формулировка компетенции буквально из паспорта}
- Score: N/10 (S1=X, S2=Y) | Tier: {тир} | {короткое обоснование, 1 строка}

Без других полей. Заголовков категорий `## ` не добавляй, разделителей тоже. Только строки `### формулировка` + `- Score:...`.

ПРАВИЛА:
1. Сохрани ВСЕ 128 паспортов. Формулировка — ТОЧНО как в исходнике (после `### `).
2. Score и Tier обязательны. Tier обязан соответствовать Score.
3. Обоснование — 1 короткая строка: ссылка на контекст («в формулировке роли», «hh hard skills», «sonar soft skills») или «общая, не в контекстах».

САМОПРОВЕРКА (молча перед выводом):
— 128 строк `### ` на выходе? нет — добавь
— Каждая строка имеет Score и Tier? нет — добавь
— Score соответствует Tier? нет — исправь

После самопроверки выведи только итоговый список. Без преамбулы, без отчёта.

=== КАТАЛОГ ПАСПОРТОВ ===
{passports}

=== HH КОНТЕКСТ ===
{hh_context}

=== TELEGRAM КОНТЕКСТ ===
{telegram_context}

=== ONET КОНТЕКСТ ===
{onet_context}

=== REDDIT КОНТЕКСТ ===
{reddit_context}

=== SONAR КОНТЕКСТ ===
{sonar_context}

---

Компактный ранжированный список (128 паспортов):
"""


def load_inputs(input_dir: Path) -> dict[str, str]:
    data = {}
    data["passports"] = (input_dir / "competency_passports.md").read_text(encoding="utf-8")
    for src in SOURCES:
        data[f"{src}_context"] = (input_dir / f"{src}_context.md").read_text(encoding="utf-8")
    return data


def count_passports(md: str) -> int:
    return sum(1 for line in md.split("\n") if line.startswith("### "))


COMPACT_RE = re.compile(
    r"^###\s+(.+?)\n-\s+Score:\s*(\d+)/10\s*\(S1=(\d+),\s*S2=(\d+)\)\s*\|\s*Tier:\s*(\w+)\s*\|\s*(.+?)$",
    re.MULTILINE,
)


def parse_compact(compact_md: str) -> dict[str, dict]:
    """Парсит компактный список от LLM → {formulation: {score, s1, s2, tier, rationale}}."""
    parsed = {}
    for m in COMPACT_RE.finditer(compact_md):
        formulation = m.group(1).strip()
        parsed[formulation] = {
            "score": int(m.group(2)),
            "s1": int(m.group(3)),
            "s2": int(m.group(4)),
            "tier": m.group(5).strip(),
            "rationale": m.group(6).strip(),
        }
    return parsed


def normalize(text: str) -> str:
    """Нормализация для матча: lower + убрать пунктуацию/пробелы."""
    return re.sub(r"[^\wа-яё]+", "", text.lower())


def fuzzy_match(input_formulation: str, parsed: dict[str, dict]) -> dict | None:
    """Сначала точный, потом по нормализованному."""
    if input_formulation in parsed:
        return parsed[input_formulation]
    target_norm = normalize(input_formulation)
    for k, v in parsed.items():
        if normalize(k) == target_norm:
            return v
    return None


def merge_into_passports(passports_md: str, compact_md: str) -> tuple[str, list[str], int, int]:
    """В каждый ### паспорт вставляет Score/Tier/Обоснование из компактного списка.
    Авто-коррекция: Tier пересчитывается по Score (Score — объективный источник истины).
    Возвращает (merged_md, not_matched_formulations, matched_count, autocorrected_count).
    """
    parsed = parse_compact(compact_md)
    lines = passports_md.split("\n")
    out = []
    not_matched = []
    matched = 0
    autocorrected = 0
    i = 0
    while i < len(lines):
        line = lines[i]
        out.append(line)
        if line.startswith("### "):
            formulation = line[4:].strip()
            ranking = fuzzy_match(formulation, parsed)
            if ranking:
                correct_tier = score_to_tier(ranking["score"])
                was_wrong = ranking["tier"] != correct_tier
                if was_wrong:
                    autocorrected += 1
                out.append(f"- **Score:** {ranking['score']}/10 (S1={ranking['s1']}, S2={ranking['s2']})")
                out.append(f"- **Tier:** {correct_tier}")
                out.append(f"- **Обоснование:** {ranking['rationale']}")
                matched += 1
            else:
                out.append("- **Score:** ?/10 (не смапилось)")
                out.append("- **Tier:** Unknown")
                out.append("- **Обоснование:** _не получено от LLM_")
                not_matched.append(formulation)
        i += 1
    return "\n".join(out), not_matched, matched, autocorrected


def validate_merged(merged: str, input_count: int) -> tuple[bool, list[str]]:
    issues = []
    output_count = count_passports(merged)
    if output_count != input_count:
        issues.append(f"Паспортов на входе {input_count}, на выходе {output_count}")

    missing_score = 0
    score_tier_mismatch = 0
    unknown_tier = 0
    for block in re.split(r"^### ", merged, flags=re.MULTILINE)[1:]:
        score_match = re.search(r"\*\*Score:\*\*\s*(\d+)/10", block)
        tier_match = re.search(r"\*\*Tier:\*\*\s*(\w+)", block)
        if not score_match:
            missing_score += 1
            continue
        if tier_match and tier_match.group(1) == "Unknown":
            unknown_tier += 1
            continue
        if score_match and tier_match:
            score = int(score_match.group(1))
            expected = score_to_tier(score)
            if tier_match.group(1) != expected:
                score_tier_mismatch += 1

    if missing_score:
        issues.append(f"Пропущен Score в {missing_score} паспортах")
    if unknown_tier:
        issues.append(f"Unknown tier в {unknown_tier} паспортах (не смаппилось из LLM)")
    if score_tier_mismatch:
        issues.append(f"Score/Tier не совпадают в {score_tier_mismatch} паспортах")

    return len(issues) == 0, issues


def count_by_tier(merged: str) -> dict[str, int]:
    counts = {"Core": 0, "Important": 0, "Relevant": 0, "Specific": 0, "Peripheral": 0, "Unknown": 0}
    for m in re.finditer(r"\*\*Tier:\*\*\s*(\w+)", merged):
        tier = m.group(1)
        if tier in counts:
            counts[tier] += 1
    return counts


def split_passports_into_batches(passports_md: str, batch_size: int) -> list[str]:
    """Разбивает каталог паспортов на батчи по N штук, сохраняя заголовки категорий."""
    lines = passports_md.split("\n")
    batches = []
    current: list[str] = []
    current_category: str | None = None
    passport_count = 0

    for line in lines:
        if line.startswith("## ") and not line.startswith("### "):
            current_category = line
            current.append(line)
            continue
        if line.startswith("### "):
            if passport_count >= batch_size and current:
                batches.append("\n".join(current))
                current = []
                if current_category:
                    current.append(current_category)
                passport_count = 0
            passport_count += 1
        current.append(line)

    if current:
        batches.append("\n".join(current))
    return batches


async def rank_batch(batch_passports: str, data: dict, role: str, max_tokens: int, batch_idx: int) -> str:
    prompt = PROMPT_TEMPLATE.replace("{role}", role).replace("{passports}", batch_passports)
    for k, v in data.items():
        if k != "passports":
            prompt = prompt.replace("{" + k + "}", v)

    print(f"[INFO] Батч {batch_idx}: промпт {len(prompt)} символов (~{len(prompt)//4} токенов)")
    result = await call_llm(
        prompt,
        temperature=0.0,
        max_output_tokens=max_tokens,
        streaming=True,
        system_message="Ты ранжируешь паспорта компетенций по 2-сигнальному скорингу. Обоснование — только факты из контекстов.",
    )
    if not result:
        print(f"[WARN] Батч {batch_idx}: пустой ответ")
        return ""
    print(f"[OK] Батч {batch_idx}: {len(result)} символов")
    return result


async def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--input-dir", default="artifacts/extracted_md")
    parser.add_argument("--role", default="Аналитик Данных в банке со знанием xlsx, vba + sql, а также умением подготавливать презентации руководству и автоматизировать процессы")
    parser.add_argument("--output", default="artifacts/extracted_md/competencies_ranked.md")
    parser.add_argument("--max-tokens", type=int, default=8000)
    parser.add_argument("--batch-size", type=int, default=45)
    args = parser.parse_args()

    input_dir = Path(args.input_dir)
    data = load_inputs(input_dir)

    input_count = count_passports(data["passports"])
    print(f"[INFO] На входе {input_count} паспортов")

    batches = split_passports_into_batches(data["passports"], args.batch_size)
    print(f"[INFO] Разбито на {len(batches)} батчей по ≤{args.batch_size} паспортов")

    # Параллельно все батчи
    tasks = [
        rank_batch(batch, data, args.role, args.max_tokens, i + 1)
        for i, batch in enumerate(batches)
    ]
    results = await asyncio.gather(*tasks)
    result = "\n\n".join(r for r in results if r)

    if not result:
        print("[ERROR] Все батчи пустые")
        return

    # Сохраняем компактный выход для отладки
    compact_path = Path(args.output).with_suffix(".compact.md")
    compact_path.write_text(result, encoding="utf-8")
    print(f"\n[OK] Компактный список сохранён: {compact_path} ({len(result)} символов)")

    # Мёрдж в полные паспорта
    merged, not_matched, matched, autocorrected = merge_into_passports(data["passports"], result)
    output_path = Path(args.output)
    output_path.write_text(merged, encoding="utf-8")
    print(f"[OK] Ранжированные паспорта сохранены: {output_path} ({len(merged)} символов)")
    print(f"[INFO] Смаппилось {matched}/{input_count} паспортов")
    if autocorrected:
        print(f"[INFO] Автокоррекция Tier по Score: {autocorrected} паспортов")

    print("\n" + "=" * 60)
    print("ВАЛИДАЦИЯ")
    print("=" * 60)
    ok, issues = validate_merged(merged, input_count)
    if ok:
        print("[✓] Валидация пройдена")
    else:
        for i in issues:
            print(f"  · {i}")

    if not_matched:
        print(f"\n--- Не смаппившиеся формулировки (первые 10) ---")
        for f in not_matched[:10]:
            print(f"  · {f[:100]}")
        if len(not_matched) > 10:
            print(f"  ... и ещё {len(not_matched) - 10}")

    print("\n--- Распределение по tier ---")
    for tier, cnt in count_by_tier(merged).items():
        print(f"  {tier:12s} {cnt}")


if __name__ == "__main__":
    asyncio.run(main())
