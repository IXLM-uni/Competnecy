from datasets import load_dataset


def extract_entities(tokens, tags):
    """Extract BIO spans as (text, label)."""
    entities = []
    current_tokens = []
    current_label = None

    for tok, tag in zip(tokens, tags):
        if tag == "O":
            if current_tokens:
                entities.append((" ".join(current_tokens), current_label))
                current_tokens, current_label = [], None
            continue

        prefix, _, label = tag.partition("-")
        label = label or tag

        if prefix == "B" or prefix not in ("B", "I"):
            if current_tokens:
                entities.append((" ".join(current_tokens), current_label))
            current_tokens, current_label = [tok], label
        else:  # I
            if current_tokens and current_label == label:
                current_tokens.append(tok)
            else:
                current_tokens, current_label = [tok], label

    if current_tokens:
        entities.append((" ".join(current_tokens), current_label))

    return entities


def detokenize(tokens):
    text = " ".join(tokens)
    for p in [" ,", " .", " !", " ?", " :", " ;", " )", " ]", " }"]:
        text = text.replace(p, p[1:])
    for p in ["( ", "[ ", "{ "]:
        text = text.replace(p, p[0])
    return text


def main() -> None:
    ds = load_dataset("jjzha/skillspan", cache_dir="D:/Python/VKR/data")
    train = ds["train"]

    # Сколько уникальных idx вывести
    max_groups = 5
    output_path = "dataset_top10.txt"

    # Группируем первые строки по idx, пока не наберём max_groups уникальных вакансий
    groups = []
    rows_per_group_limit = 50  # на случай длинных вакансий
    idx_order = []
    buckets = {}

    for row in train:
        idx = row["idx"]
        if idx not in buckets:
            if len(idx_order) >= max_groups:
                break
            idx_order.append(idx)
            buckets[idx] = []
        buckets[idx].append(row)
        if len(buckets[idx]) >= rows_per_group_limit:
            continue

    groups = [{"idx": idx, "rows": buckets[idx]} for idx in idx_order]

    lines = []
    lines.append(f"Всего сплитов: {ds}\n")
    lines.append(f"Пишем первые {max_groups} вакансий (групп по idx)\n")

    for g in groups:
        idx = g["idx"]
        # Собираем текст вакансии из строк с этим idx
        row_texts = [detokenize(r["tokens"]) for r in g["rows"]]
        full_text = " \n".join(row_texts)

        # Собираем сущности по всем строкам
        skills = []
        knowledge = []
        for r in g["rows"]:
            tokens = r["tokens"]
            skills.extend(extract_entities(tokens, r["tags_skill"]))
            knowledge.extend(extract_entities(tokens, r["tags_knowledge"]))

        lines.append(f"Вакансия idx={idx}, source={g['rows'][0]['source']}:")
        lines.append("Текст:")
        lines.append(full_text)

        if skills:
            lines.append("Навыки:")
            for text, label in skills:
                lines.append(f"  {text} [{label}]")
        else:
            lines.append("Навыки: нет")

        if knowledge:
            lines.append("Знания:")
            for text, label in knowledge:
                lines.append(f"  {text} [{label}]")
        else:
            lines.append("Знания: нет")

        lines.append("-")

    with open(output_path, "w", encoding="utf-8") as f:
        f.write("\n".join(lines))

    print(f"Сохранено в {output_path}")


if __name__ == "__main__":
    main()
