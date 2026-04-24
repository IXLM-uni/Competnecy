#!/usr/bin/env python3
"""Только прогон валидатора на существующем competency_passports.md — без LLM."""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))

from build_passports import (
    SOURCES,
    load_corpus,
    measure_coverage,
    measure_hallucinations,
)


def main() -> None:
    input_dir = Path("artifacts/extracted_md")
    corpus = load_corpus(input_dir)
    result = (input_dir / "competency_passports.md").read_text(encoding="utf-8")

    profiles = {src: corpus[f"{src}_md"] for src in SOURCES}
    corpus_full = "\n".join(corpus.values())

    coverage, missing = measure_coverage(result, profiles)
    halluc_rate, halluc_terms = measure_hallucinations(result, corpus_full)

    print(f"[COVERAGE]  {coverage*100:.2f}% ({len(missing)} недостающих)")
    print(f"[HALLUCIN]  {halluc_rate*100:.2f}% ({len(halluc_terms)} подозрительных)")

    if missing:
        print("\n--- Недостающие ---")
        for m in missing:
            print(f"  · {m}")
    if halluc_terms:
        print("\n--- Подозрительные термины ---")
        for t in halluc_terms[:30]:
            print(f"  · {t}")

    if coverage >= 1.0 and halluc_rate == 0.0:
        print("\n[✓] ЦЕЛЬ ДОСТИГНУТА: 100.00% coverage, 0.00% hallucinations")


if __name__ == "__main__":
    main()
