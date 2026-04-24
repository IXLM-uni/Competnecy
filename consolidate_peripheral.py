#!/usr/bin/env python3
"""Stage 3.5: консолидация Peripheral паспортов.

Берёт competencies_ranked.md, находит все Tier=Peripheral, схлопывает 90 штук
«Знаком с концепцией X» в 4 зонтичных паспорта через LLM:
  1. Ориентируется в смежных ролях в данных
  2. Ориентируется в ML/DS-стеке
  3. Ориентируется в GenAI-экосистеме
  4. Ориентируется в MLOps/Cloud-инфраструктуре

Выход: competency_catalog_v2.md — исходные Core+Important+Relevant+Specific +
4 зонтичных Peripheral.
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


PROMPT_CONSOLIDATE = """Тебе дан список Peripheral-паспортов (90 штук) формата «Знаком с концепцией X».
Каждый — это отдельный паспорт, возникший из reddit-one-liner упоминания термина.

Задача: схлопни все 90 в 4 зонтичных паспорта по тематикам.

ЗОНТИЧНЫЕ ПАСПОРТА (ровно эти 4, не больше):

1. **Ориентируется в смежных ролях в data-индустрии**
   (Data Analyst, Data Engineer, Data Scientist, ML Engineer, BI Analyst,
    Database Admin, quants, product analytics, AI Expert, unicorn-роль и т.п.)

2. **Ориентируется в ML/DS-стеке**
   (ML-алгоритмы, фреймворки, методы обработки: classification, regression,
    imputation, cross-validation, PyTorch, TensorFlow, Scikit-learn, SVM, BERT,
    Hadoop, Spark, SAS и т.д.)

3. **Ориентируется в GenAI/LLM-экосистеме**
   (LLM-провайдеры: OpenAI, Gemini, GPT-4o-mini; фреймворки: LangChain, LangGraph,
    LangFlow, Hugging Face; концепции: RAG, embedding, vector DB, similarity search)

4. **Ориентируется в MLOps/Cloud-инфраструктуре**
   (Docker, Kubernetes, CI/CD, infra-as-code, AWS, Azure, GCP, SageMaker, Bedrock,
    MLflow, Pinecone, ChromaDB и т.д.)

ФОРМАТ ВЫХОДА — ровно 4 блока, каждый по шаблону:

### {формулировка зонтичного паспорта}
- **Score:** 2/10 (S1=1, S2=1)
- **Tier:** Peripheral
- **Обоснование:** {1 строка, что это консолидация из reddit-термов}
- Инструменты/технологии: {все конкретные названия из консолидированных паспортов, через запятую}
- Контекст применения: {для каких ситуаций это знание полезно}
- Типовые задачи:
  - Распознаёт термин в профессиональных обсуждениях
  - Понимает место инструмента/роли в ландшафте
- Источники: [reddit]

ПРАВИЛА:
1. В поле Инструменты/технологии собери ВСЕ названия из консолидированных паспортов (буквально). Не выдумывай.
2. Если термин в списке внизу — обязан попасть в Инструменты одного из 4 зонтичных паспортов.
3. Если термин не подходит ни под одну из 4 тематик — ИГНОРИРУЙ (это шум: Oxylabs, HTML scraping, JSON extraction, date filtering, repost detection, occular regression).
4. После 4 блоков выведи одну строку: `### [CONSOLIDATION NOISE IGNORED]: {список проигнорированных терминов}`.

ИСХОДНЫЕ 90 PERIPHERAL-ПАСПОРТОВ:

{peripheral_list}

---

4 зонтичных паспорта:
"""


def extract_peripheral_block(ranked_md: str) -> tuple[list[str], list[str]]:
    """Разбивает файл на: блоки Peripheral (выкинуть) и всё остальное (сохранить)."""
    lines = ranked_md.split("\n")
    passport_blocks = []  # список (header, lines, tier)
    preamble = []
    i = 0

    # Собираем preamble — всё до первого `## `
    while i < len(lines) and not lines[i].startswith("## "):
        preamble.append(lines[i])
        i += 1

    # Проходим по блокам `### ` (паспорта) и `## ` (категории)
    current_category_line = None
    current_passport: list[str] = []
    current_tier: str | None = None
    all_blocks: list[dict] = []  # {'type': 'category'|'passport', ...}

    def flush_passport():
        nonlocal current_passport, current_tier
        if current_passport:
            all_blocks.append({
                "type": "passport",
                "lines": current_passport[:],
                "tier": current_tier,
            })
            current_passport = []
            current_tier = None

    while i < len(lines):
        line = lines[i]
        if line.startswith("## ") and not line.startswith("### "):
            flush_passport()
            all_blocks.append({"type": "category", "lines": [line]})
        elif line.startswith("### "):
            flush_passport()
            current_passport = [line]
        else:
            if current_passport:
                current_passport.append(line)
                m = re.match(r"^-\s+\*\*Tier:\*\*\s*(\w+)", line.strip())
                if m:
                    current_tier = m.group(1)
            elif all_blocks and all_blocks[-1]["type"] == "category":
                all_blocks[-1]["lines"].append(line)
        i += 1
    flush_passport()

    return preamble, all_blocks


def rebuild_without_peripheral(preamble: list[str], blocks: list[dict]) -> tuple[str, list[str]]:
    """Возвращает (без-peripheral md, список-формулировок-peripheral)."""
    out = list(preamble)
    peripheral_formulations = []
    for block in blocks:
        if block["type"] == "category":
            out.extend(block["lines"])
        else:
            if block["tier"] == "Peripheral":
                peripheral_formulations.append(block["lines"][0])  # `### {formulation}`
                continue
            out.extend(block["lines"])
    return "\n".join(out), peripheral_formulations


async def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--input", default="artifacts/extracted_md/competencies_ranked.md")
    parser.add_argument("--output", default="artifacts/extracted_md/competency_catalog_v2.md")
    parser.add_argument("--max-tokens", type=int, default=5000)
    args = parser.parse_args()

    ranked = Path(args.input).read_text(encoding="utf-8")
    preamble, blocks = extract_peripheral_block(ranked)
    without_peri, peri_formulations = rebuild_without_peripheral(preamble, blocks)

    total = sum(1 for b in blocks if b["type"] == "passport")
    kept = total - len(peri_formulations)
    print(f"[INFO] Всего паспортов: {total}")
    print(f"[INFO] Peripheral для консолидации: {len(peri_formulations)}")
    print(f"[INFO] Остаётся как есть: {kept}")

    # LLM-консолидация 90 peripheral в 4 зонтичных
    peripheral_list = "\n".join(peri_formulations)
    prompt = PROMPT_CONSOLIDATE.replace("{peripheral_list}", peripheral_list)

    print(f"[INFO] Вызываю LLM для консолидации (max_tokens={args.max_tokens}) ...")
    consolidated = await call_llm(
        prompt,
        temperature=0.0,
        max_output_tokens=args.max_tokens,
        streaming=True,
        system_message="Ты консолидируешь 90 мелких reddit-терминов в 4 зонтичных паспорта. Только факты из списка.",
    )

    if not consolidated:
        print("[ERROR] LLM вернул пустой ответ")
        return

    # Добавляем категорию и 4 зонтичных в конец файла
    final = without_peri.rstrip() + "\n\n## Ориентировочные знания (фоновое знакомство с экосистемой)\n\n" + consolidated.strip() + "\n"
    Path(args.output).write_text(final, encoding="utf-8")

    # Подсчёт финала
    new_blocks = re.findall(r"^### ", final, flags=re.MULTILINE)
    print(f"\n[OK] {args.output} ({len(final)} символов)")
    print(f"[INFO] Финальный каталог: {len(new_blocks)} паспортов")
    print(f"[INFO] Уменьшение: {total} → {len(new_blocks)} ({100*(total-len(new_blocks))/total:.0f}%)")


if __name__ == "__main__":
    asyncio.run(main())
