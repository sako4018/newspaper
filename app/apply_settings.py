#!/usr/bin/env python3
"""Връзка между съветника за инсталиране и профила (lite/profile.yaml).

    apply_settings.py --dump        печата профила като JSON (съветникът го зарежда при смяна на настройки)
    apply_settings.py settings.json записва ключовете от JSON файла в профила; другите ключове остават
"""

import json
import sys
from pathlib import Path

import yaml

PROFILE = Path(__file__).resolve().parent.parent / "lite" / "profile.yaml"
KEYS = ["version", "topics", "city", "stories_per_topic", "max_stories", "schedule_time", "print"]


def load():
    if PROFILE.exists():
        with open(PROFILE, encoding="utf-8") as f:
            return yaml.safe_load(f) or {}
    return {}


def main():
    if len(sys.argv) != 2:
        sys.exit(__doc__)
    if sys.argv[1] == "--dump":
        print(json.dumps(load(), ensure_ascii=False))
        return
    with open(sys.argv[1], encoding="utf-8") as f:
        data = json.load(f)
    profile = load()
    for key in KEYS:
        if key in data:
            profile[key] = data[key]
    for key in ("повече", "по-малко", "никога"):
        profile.setdefault(key, [])
    text = yaml.safe_dump(profile, allow_unicode=True, sort_keys=False)
    tmp = PROFILE.with_suffix(".tmp")
    tmp.write_text(text, encoding="utf-8")
    tmp.replace(PROFILE)
    print("Профилът е записан.")


if __name__ == "__main__":
    main()
