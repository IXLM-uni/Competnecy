# -*- coding: utf-8 -*-
"""
O*NET Data Tool — загрузка, LLM-маппинг и форматирование профессий.

Использует xlsx файлы из data/ONET/usefull/:
- Occupation Data.xlsx → список 1016 профессий (Title → SOC Code)
- Skills.xlsx → навыки с importance/level
- Knowledge.xlsx → знания с importance/level
- Task Statements.xlsx → описание задач
- Work Context.xlsx → контекст работы
"""

import logging
from pathlib import Path
from typing import Dict, List, Optional

import pandas as pd

logger = logging.getLogger(__name__)

_DATA_DIR = Path(__file__).resolve().parent.parent.parent / "data" / "ONET" / "usefull"

# Cache loaded DataFrames
_cache: Dict[str, pd.DataFrame] = {}


def _load(name: str) -> pd.DataFrame:
    """Загрузка xlsx с кэшированием."""
    if name not in _cache:
        path = _DATA_DIR / name
        if not path.exists():
            logger.warning(f"O*NET файл не найден: {path}")
            return pd.DataFrame()
        _cache[name] = pd.read_excel(path)
        logger.info(f"O*NET loaded {name}: {len(_cache[name])} rows")
    return _cache[name]


def load_occupation_titles() -> List[str]:
    """Загрузить ТОЛЬКО titles — thin list для LLM."""
    df = _load("Occupation Data.xlsx")
    if df.empty:
        return []
    return df["Title"].tolist()


def find_soc_codes(selected_titles: List[str]) -> List[Dict[str, str]]:
    """Case-insensitive поиск SOC codes по title."""
    df = _load("Occupation Data.xlsx")
    if df.empty:
        return []

    # Lowercase index
    title_lower = df["Title"].str.lower()

    results = []
    for title in selected_titles:
        mask = title_lower == title.strip().lower()
        matches = df[mask]
        if matches.empty:
            # Partial match
            mask = title_lower.str.contains(title.strip().lower(), na=False)
            matches = df[mask]
        if not matches.empty:
            row = matches.iloc[0]
            results.append({
                "soc_code": row["O*NET-SOC Code"],
                "title": row["Title"],
                "description": row.get("Description", ""),
            })
        else:
            logger.warning(f"O*NET: не найден SOC code для '{title}'")
    return results


def get_occupation_profile(soc_code: str) -> Dict:
    """Подтянуть полный профиль по SOC code."""
    profile: Dict = {"soc_code": soc_code}

    # Skills (Importance > 3.0, top-10)
    skills_df = _load("Skills.xlsx")
    if not skills_df.empty:
        mask = (skills_df["O*NET-SOC Code"] == soc_code) & (skills_df["Scale ID"] == "IM")
        filtered = skills_df[mask].sort_values("Data Value", ascending=False)
        filtered = filtered[filtered["Data Value"] > 3.0].head(10)
        profile["skills"] = [
            {"name": r["Element Name"], "importance": round(r["Data Value"], 2)}
            for _, r in filtered.iterrows()
        ]
        # Add Level values
        lv_mask = (skills_df["O*NET-SOC Code"] == soc_code) & (skills_df["Scale ID"] == "LV")
        lv_map = dict(zip(skills_df[lv_mask]["Element Name"], skills_df[lv_mask]["Data Value"]))
        for s in profile.get("skills", []):
            s["level"] = round(lv_map.get(s["name"], 0), 2)

    # Knowledge (Importance > 3.0, top-10)
    know_df = _load("Knowledge.xlsx")
    if not know_df.empty:
        mask = (know_df["O*NET-SOC Code"] == soc_code) & (know_df["Scale ID"] == "IM")
        filtered = know_df[mask].sort_values("Data Value", ascending=False)
        filtered = filtered[filtered["Data Value"] > 3.0].head(10)
        profile["knowledge"] = [
            {"name": r["Element Name"], "importance": round(r["Data Value"], 2)}
            for _, r in filtered.iterrows()
        ]
        lv_mask = (know_df["O*NET-SOC Code"] == soc_code) & (know_df["Scale ID"] == "LV")
        lv_map = dict(zip(know_df[lv_mask]["Element Name"], know_df[lv_mask]["Data Value"]))
        for k in profile.get("knowledge", []):
            k["level"] = round(lv_map.get(k["name"], 0), 2)

    # Tasks (Core only)
    tasks_df = _load("Task Statements.xlsx")
    if not tasks_df.empty:
        mask = (tasks_df["O*NET-SOC Code"] == soc_code)
        if "Task Type" in tasks_df.columns:
            mask = mask & (tasks_df["Task Type"] == "Core")
        filtered = tasks_df[mask]
        profile["tasks"] = filtered["Task"].tolist() if "Task" in filtered.columns else []

    # Work Context (top-10 by value)
    wc_df = _load("Work Context.xlsx")
    if not wc_df.empty:
        mask = (wc_df["O*NET-SOC Code"] == soc_code) & (wc_df["Scale ID"] == "CX")
        filtered = wc_df[mask].sort_values("Data Value", ascending=False).head(10)
        profile["work_context"] = [
            {"name": r["Element Name"], "value": round(r["Data Value"], 2)}
            for _, r in filtered.iterrows()
        ]

    return profile


def format_onet_markdown(occ: Dict, profile: Dict) -> str:
    """Форматирование в structured markdown."""
    lines = [
        f"# O*NET: {occ['title']} ({occ['soc_code']})",
        "",
        f"## Description",
        occ.get("description", "N/A"),
        "",
    ]

    # Skills
    if profile.get("skills"):
        lines.append("## Top Skills (by importance)")
        lines.append("| Skill | Importance | Level |")
        lines.append("|---|---|---|")
        for s in profile["skills"]:
            lines.append(f"| {s['name']} | {s['importance']} | {s.get('level', '')} |")
        lines.append("")

    # Knowledge
    if profile.get("knowledge"):
        lines.append("## Top Knowledge Areas")
        lines.append("| Knowledge | Importance | Level |")
        lines.append("|---|---|---|")
        for k in profile["knowledge"]:
            lines.append(f"| {k['name']} | {k['importance']} | {k.get('level', '')} |")
        lines.append("")

    # Tasks
    if profile.get("tasks"):
        lines.append("## Core Tasks")
        for t in profile["tasks"]:
            lines.append(f"- {t}")
        lines.append("")

    # Work Context
    if profile.get("work_context"):
        lines.append("## Work Context")
        for wc in profile["work_context"]:
            lines.append(f"- {wc['name']}: {wc['value']}")
        lines.append("")

    return "\n".join(lines)
