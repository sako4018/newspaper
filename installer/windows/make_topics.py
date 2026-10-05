#!/usr/bin/env python3
"""Прави topics.isi за setup.iss: Pascal процедура, която добавя темите от lite/catalog.yaml.

    python installer/windows/make_topics.py      (вика се преди компилирането на setup.iss)
"""

from pathlib import Path

import yaml

HERE = Path(__file__).resolve().parent
ROOT = HERE.parent.parent


def pascal(text):
    return "'" + str(text).replace("'", "''") + "'"


def main():
    with open(ROOT / "lite" / "catalog.yaml", encoding="utf-8") as f:
        catalog = yaml.safe_load(f)
    lines = ["// Генерирано от make_topics.py, не се пипа на ръка.",
             "procedure AddTopics(Page: TInputOptionWizardPage);",
             "begin"]
    for t in catalog["topics"]:
        caption = t["name"] + (" (" + t["about"] + ")" if t.get("about") else "")
        lines.append("  Page.Add({}); TopicIds.Add({});".format(pascal(caption), pascal(t["id"])))
    lines.append("end;")
    # С BOM, за да чете Inno Setup кирилицата правилно
    (HERE / "topics.isi").write_text("\n".join(lines) + "\n", encoding="utf-8-sig")
    print("topics.isi: {} теми".format(len(catalog["topics"])))


if __name__ == "__main__":
    main()
