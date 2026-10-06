#!/usr/bin/env python3
"""Връзка между съветника за инсталиране и профила (lite/profile.yaml).

    apply_settings.py --dump        печата профила като JSON (съветникът го зарежда при смяна на настройки)
    apply_settings.py settings.json записва ключовете от JSON файла в профила; другите ключове остават

Вместо city може да има city_name (само име, от инсталатора за Windows): градът се търси в
open-meteo и се взима първият резултат. Ако не се намери, профилът е без град.
"""

import json
import sys
import urllib.parse
import urllib.request
from pathlib import Path

import yaml

PROFILE = Path(__file__).resolve().parent.parent / "lite" / "profile.yaml"
KEYS = ["version", "topics", "city", "stories_per_topic", "max_stories", "schedule_time", "print"]


def load():
    if PROFILE.exists():
        with open(PROFILE, encoding="utf-8") as f:
            return yaml.safe_load(f) or {}
    return {}


def find_city(name):
    url = "https://geocoding-api.open-meteo.com/v1/search?name={}&count=1&language=bg".format(
        urllib.parse.quote(name))
    try:
        req = urllib.request.Request(url, headers={"User-Agent": "SutreshenVestnikSetup/1.0"})
        with urllib.request.urlopen(req, timeout=15) as resp:
            found = json.loads(resp.read()).get("results", [])
    except Exception as e:
        print("Не успях да потърся града: {}".format(e))
        return None
    if not found:
        print("Не намерих град „{}“.".format(name))
        return None
    r = found[0]
    return {"name": r["name"] + (", " + r["country"] if r.get("country") else ""),
            "lat": r["latitude"], "lon": r["longitude"]}


def main():
    if len(sys.argv) != 2:
        sys.exit(__doc__)
    if sys.argv[1] == "--dump":
        print(json.dumps(load(), ensure_ascii=False))
        return
    with open(sys.argv[1], encoding="utf-8-sig") as f:   # -sig: инсталаторът за Windows пише с BOM
        data = json.load(f)
    profile = load()
    if data.get("city_name"):
        name = data["city_name"].strip()
        old = profile.get("city") or {}
        # Същият град като досега (съветникът показва само името): без ново търсене, за да не се
        # изгуби при лоша връзка. Нов град, който не се намери, не трие стария.
        if old.get("name", "").casefold().startswith(name.casefold()):
            data["city"] = old
        else:
            data["city"] = find_city(name) or old or None
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
