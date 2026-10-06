#!/usr/bin/env python3
"""Фалшив `claude` за проверките в GitHub Actions (там няма вход в Claude).

Приема същите аргументи като `claude -p --output-format json ...`, чете промпта от stdin и връща
отговор във формата на истинския: {"type": "result", "is_error": false, "result": "<JSON текст>"}.
Историите са първите новини от промпта (редове "[i] (източник, рубрика) заглавие — резюме"),
така че claude/vestnik.py минава целия път до .docx, без да зависи от AI.
"""

import json
import re
import sys

SECTIONS = ["България", "Армения", "Свят", "Технологии и AI", "Любопитно"]
LINE = re.compile(r"^\[(\d+)\] \((.*?), (.*?)\) (.*?) — (.*)$")


def main():
    prompt = sys.stdin.read()
    stories = []
    for line in prompt.splitlines():
        m = LINE.match(line.strip())
        if not m:
            continue
        i, _source, section, title, summary = m.groups()
        stories.append({
            "title": title[:100] or "Без заглавие",
            "summary": (summary or title)[:300],
            "section": section if section in SECTIONS else "Свят",
            "score": 9 - len(stories),
            "top": len(stories) < 3,
            "ids": [int(i)],
        })
        if len(stories) == 8:
            break
    data = {"day_in_three": "Проверка. Фалшив Claude. Три изречения.", "stories": stories}
    print(json.dumps({"type": "result", "is_error": False, "result": json.dumps(data, ensure_ascii=False)},
                     ensure_ascii=False))


if __name__ == "__main__":
    main()
