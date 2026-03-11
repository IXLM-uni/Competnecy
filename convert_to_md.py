import os
from pathlib import Path

import docx
import fitz  # PyMuPDF
import pandas as pd


# --- ФУНКЦИИ ОБРАБОТКИ ФАЙЛОВ ---

def process_xlsx(file_path: Path) -> str:
    """Превращает все листы Excel в Markdown-таблицы."""
    xl = pd.ExcelFile(file_path)
    md_content = []

    for sheet in xl.sheet_names:
        df = xl.parse(sheet)
        if df.empty:
            continue

        md_content.append(f"## Лист: {sheet}\n\n")
        md_content.append(df.to_markdown(index=False, tablefmt="github"))
        md_content.append("\n\n")

    return "".join(md_content)


def process_docx(file_path: Path) -> str:
    """Читает Word, сохраняя заголовки, списки, жирный шрифт и курсив."""
    doc = docx.Document(file_path)
    md_content = []

    for p in doc.paragraphs:
        if not p.text.strip():
            continue

        style_name = p.style.name

        # 1. Заголовки
        if style_name.startswith("Heading"):
            try:
                level = int(style_name.split()[-1])
                md_content.append(f"\n{'#' * level} {p.text.strip()}\n")
            except ValueError:
                md_content.append(f"\n## {p.text.strip()}\n")
            continue

        # 2. Списки
        if "List" in style_name:
            md_content.append(f"- {p.text.strip()}\n")
            continue

        # 3. Обычный текст (жирный/курсив)
        para_text = ""
        for run in p.runs:
            text = run.text
            if not text.strip():
                para_text += text
                continue

            stripped = text.strip()
            formatted = stripped
            if run.bold:
                formatted = f"**{formatted}**"
            if run.italic:
                formatted = f"*{formatted}*"

            para_text += text.replace(stripped, formatted)

        md_content.append(para_text + "\n\n")

    return "".join(md_content)


def process_pdf(file_path: Path) -> str:
    """Извлекает текст из PDF с разделителями страниц."""
    doc = fitz.open(file_path)
    md_content = []

    for page_num, page in enumerate(doc, 1):
        text = page.get_text("text")
        if text.strip():
            md_content.append(f"<!-- Страница {page_num} -->\n")
            md_content.append(text.strip())
            md_content.append("\n\n---\n\n")

    return "".join(md_content)


# --- ГЛАВНАЯ ЛОГИКА ---

def main():
    input_dir = Path("data")
    output_dir = Path("data_md")

    if not input_dir.exists():
        print(f"Папка {input_dir} не найдена! Создаю пустую папку. Положите туда файлы.")
        input_dir.mkdir(parents=True, exist_ok=True)
        return

    output_dir.mkdir(parents=True, exist_ok=True)

    print(f"Начинаем конвертацию файлов из '{input_dir}' в '{output_dir}'...\n")

    for file_path in input_dir.iterdir():
        if not file_path.is_file():
            continue

        ext = file_path.suffix.lower()
        md_text = ""

        try:
            if ext == ".xlsx":
                md_text = process_xlsx(file_path)
            elif ext == ".docx":
                md_text = process_docx(file_path)
            elif ext == ".pdf":
                md_text = process_pdf(file_path)
            else:
                continue  # пропускаем другие файлы

            if md_text.strip():
                out_path = output_dir / f"{file_path.stem}.md"
                out_path.write_text(md_text, encoding="utf-8")
                print(f"[УСПЕХ] {file_path.name} -> {out_path.name}")
            else:
                print(f"[ПУСТО] {file_path.name} (текст не найден)")

        except Exception as e:
            print(f"[ОШИБКА] Не удалось обработать {file_path.name}. Причина: {e}")

    print("\nГотово! Все файлы обработаны.")


if __name__ == "__main__":
    main()
