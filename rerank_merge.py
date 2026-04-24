#!/usr/bin/env python3
"""Мёрдж существующего compact.md в паспорта — без повторного LLM-вызова."""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))

from rank_competencies import merge_into_passports, validate_merged, count_by_tier, count_passports


def main() -> None:
    input_dir = Path("artifacts/extracted_md")
    passports = (input_dir / "competency_passports.md").read_text(encoding="utf-8")
    compact = (input_dir / "competencies_ranked.compact.md").read_text(encoding="utf-8")

    input_count = count_passports(passports)
    merged, not_matched, matched, autocorrected = merge_into_passports(passports, compact)

    output_path = input_dir / "competencies_ranked.md"
    output_path.write_text(merged, encoding="utf-8")
    print(f"[OK] {output_path} ({len(merged)} символов)")
    print(f"[INFO] Смаппилось {matched}/{input_count}")
    if autocorrected:
        print(f"[INFO] Автокоррекция Tier: {autocorrected}")

    ok, issues = validate_merged(merged, input_count)
    if ok:
        print("[✓] Валидация пройдена")
    else:
        for i in issues:
            print(f"  · {i}")

    print("\n--- Распределение по tier ---")
    for tier, cnt in count_by_tier(merged).items():
        print(f"  {tier:12s} {cnt}")


if __name__ == "__main__":
    main()
