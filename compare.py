#!/usr/bin/env python3
"""Честно сравнение на Claude и Lite върху едни и същи новини.

1. Тегли новините ВЕДНЪЖ (всички източници от профила, включително тези само за едната
   версия) и ги записва в кеш: compare/cache/<дата>_<час>.json.
2. Пуска двете версии върху кеша. Всяка прави своя собствена обработка и ползва само
   своите източници (only: claude / only: lite), както в нормалното пускане.
3. Показва колко истории избира всяка, кои са общи, кои са само в едната и какво е
   „Главното днес“. Пълният доклад е в compare/report-<дата>_<час>.md.

Не променя lite/lite.py, claude/vestnik.py, графика и профила.

  .venv/bin/python compare.py                    нов кеш, после двете версии (вика Claude)
  .venv/bin/python compare.py --fetch-only       само тегли и записва кеша
  .venv/bin/python compare.py --cache latest     върху последния кеш (Claude се вика отново)
  .venv/bin/python compare.py --cache latest --reuse-claude   и отговорът на Claude е от кеша
  .venv/bin/python compare.py --hours 24         равни 24 ч за всички теми (иначе hours_back на темата)
  .venv/bin/python compare.py --all-topics       всички теми от каталога, не само от профила
"""

import argparse
import importlib.util
import json
import sys
import time
from collections import Counter
from datetime import datetime
from pathlib import Path
from urllib.parse import urlsplit

import yaml

ROOT = Path(__file__).resolve().parent
OUT = ROOT / "compare"
CACHE_DIR = OUT / "cache"

sys.path.insert(0, str(ROOT / "app"))   # platform_support, нужен и на двете версии


def load_module(name, path):
    """Зарежда файла като модул, без да го променя и без да пуска main()."""
    spec = importlib.util.spec_from_file_location(name, str(path))
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


lite = load_module("vestnik_lite", ROOT / "lite" / "lite.py")
claude = load_module("vestnik_claude", ROOT / "claude" / "vestnik.py")


class FrozenTime:
    """Lite оценява свежестта спрямо „сега“. С това „сега“ е моментът на теглене на кеша,
    за да дава един и същ резултат и при стар кеш. Подава се само на lite."""

    def __init__(self, now):
        self.now = now

    def time(self):
        return self.now

    def __getattr__(self, name):
        return getattr(time, name)


# ---------- 1. Настройки и общо теглене ----------

def load_setup(all_topics):
    catalog = yaml.safe_load(lite.CATALOG.read_text(encoding="utf-8"))
    profile = {}
    if lite.PROFILE.exists():
        profile = yaml.safe_load(lite.PROFILE.read_text(encoding="utf-8")) or {}
    topics = {t["id"]: t for t in catalog["topics"]}
    if all_topics or not profile.get("topics"):
        selected = list(topics)
    else:
        selected = [t for t in profile["topics"] if t in topics]
    return catalog, profile, topics, selected


def fetch_cache(catalog, topics, selected, hours):
    """Всички източници на избраните теми, по веднъж за (адрес, тема)."""
    settings = catalog["settings"]
    now = time.time()
    sources, seen = [], set()
    for t in selected:
        window = hours or topics[t].get("hours_back", settings["hours_back"])
        for src in topics[t]["sources"]:
            if (src["url"], t) in seen:
                continue
            seen.add((src["url"], t))
            sources.append(dict(src, topic=t, topic_name=topics[t]["name"], hours_back=window))
    print("Тегля {} източника от {} теми...".format(len(sources), len(selected)))
    items = lite.fetch_all(sources, settings)   # същият код, който ползва lite
    only = {(s["url"], s["topic"]): s.get("only") for s in sources}
    by_name = {(s["name"], s["topic"]): s for s in sources}
    for it in items:
        src = by_name[(it["source"], it["topic"])]
        it["only"] = only[(src["url"], src["topic"])]
        it["src_url"] = src["url"]
    return {"fetched_at": now, "hours": hours, "topics": selected, "items": items}


def cache_path(arg):
    if arg == "latest":
        files = sorted(CACHE_DIR.glob("*.json")) if CACHE_DIR.exists() else []
        if not files:
            sys.exit("Няма запазен кеш. Пусни първо без --cache.")
        return files[-1]
    return Path(arg)


# ---------- 2. Двете версии върху кеша ----------

def run_lite(cache, catalog, profile, topics, selected):
    settings = catalog["settings"]
    items = [dict(it) for it in cache["items"] if it.get("only") != "claude"]
    lite.time = FrozenTime(cache["fetched_at"])
    try:
        items = lite.keep_relevant(items, topics, selected)
        stories = lite.build_stories(items, settings, profile)
        chosen = lite.pick(stories, profile.get("stories_per_topic", 4))
    finally:
        lite.time = time
    return chosen, len(items)


def run_claude(cache, reuse):
    config = claude.load_config()   # настройките и профилът са същите като при нормално пускане
    hours = cache.get("hours")
    if hours:
        config["settings"]["hours_back"] = hours
        config["hours"] = hours
    settings = config["settings"]

    if reuse and cache.get("claude"):
        saved = cache["claude"]
        return saved["data"], saved["items"], False

    # като в load_config: един адрес в две теми се тегли веднъж (първата тема го държи)
    first_topic = {}
    kept = []
    for it in cache["items"]:
        if it.get("only") == "lite":
            continue
        if first_topic.setdefault(it["src_url"], it["topic"]) != it["topic"]:
            continue
        kept.append({
            "title": it["title"],
            "summary": claude.clean_text(it["summary"], settings.get("summary_chars", 300)),
            "link": it["link"], "source": it["source"],
            "section": claude.TOPIC_SECTION.get(it["topic"], "Свят"),
            "topic": it["topic"], "ts": it["ts"],
        })
    items = claude.dedupe(kept)
    items = claude.drop_never(items, config["profile"].get("никога", []))
    items = claude.cap_per_topic(items, settings.get("max_per_topic", 25))
    print("Claude вижда {} новини и обобщава (може да отнеме няколко минути)...".format(len(items)))
    data = claude.summarize(items, settings, config)
    return data, items, True


# ---------- 3. Сравнение ----------

def norm_link(url):
    p = urlsplit(url.strip().lower())
    host = p.netloc[4:] if p.netloc.startswith("www.") else p.netloc
    return host + p.path.rstrip("/")


def claude_story_links(story, items):
    return {norm_link(items[i]["link"]) for i in story.get("ids", [])
            if isinstance(i, int) and 0 <= i < len(items)}


def lite_story_links(story):
    return {norm_link(link) for _, link in story["links"]}


def pair_up(claude_stories, claude_items, lite_stories):
    """Две истории са „общи“, ако делят поне един линк. Най-голямото припокриване първо,
    всяка история участва най-много в една двойка."""
    c_links = [claude_story_links(s, claude_items) for s in claude_stories]
    l_links = [lite_story_links(s) for s in lite_stories]
    cands = sorted(((len(c_links[i] & l_links[j]), i, j)
                    for i in range(len(c_links)) for j in range(len(l_links))
                    if c_links[i] & l_links[j]), reverse=True)
    used_c, used_l, pairs = set(), set(), []
    for shared, i, j in cands:
        if i not in used_c and j not in used_l:
            used_c.add(i)
            used_l.add(j)
            pairs.append((i, j, shared))
    only_c = [i for i in range(len(c_links)) if i not in used_c]
    only_l = [j for j in range(len(l_links)) if j not in used_l]
    return pairs, only_c, only_l


def claude_sources(story, items):
    return sorted({items[i]["source"] for i in story.get("ids", [])
                   if isinstance(i, int) and 0 <= i < len(items)})


def describe_claude(story, items):
    return "{} [{}] оц. {} · {}".format(story["title"], story.get("section", "?"),
                                       story.get("score", "?"),
                                       ", ".join(claude_sources(story, items)))


def describe_lite(story):
    return "{} [{}] оц. {:.1f} · {}".format(story["title"], story["section"], story["score"],
                                           ", ".join(src for src, _ in story["links"]))


def compare(c_stories, c_items, l_stories):
    pairs, only_c, only_l = pair_up(c_stories, c_items, l_stories)
    c_top = {i for i, s in enumerate(c_stories) if s.get("top")}
    l_top = {j for j, s in enumerate(l_stories) if s.get("top")}
    pair_of_c = {i: j for i, j, _ in pairs}
    top_both = sum(1 for i in c_top if pair_of_c.get(i) in l_top)
    return {"pairs": pairs, "only_c": only_c, "only_l": only_l, "top_both": top_both,
            "c_top": sorted(c_top), "l_top": sorted(l_top), "pair_of_c": pair_of_c}


def rubric_counts(l_stories, topic_name_to_id):
    count = Counter()
    for s in l_stories:
        count[claude.TOPIC_SECTION.get(topic_name_to_id.get(s["section"]), "Свят")] += 1
    return count


def build_report(cache, c_stories, c_items, l_stories, l_count, trimmed, topic_name_to_id, c_data):
    lines = []
    out = lines.append
    full = compare(c_stories, c_items, l_stories)
    equal = compare(c_stories, c_items, trimmed)

    out("# Сравнение Claude и Lite")
    out("")
    out("Кеш от {} · {} новини общо · прозорец: {}".format(
        datetime.fromtimestamp(cache["fetched_at"]).strftime("%Y-%m-%d %H:%M"),
        len(cache["items"]),
        "{} ч за всички".format(cache["hours"]) if cache.get("hours") else "hours_back на всяка тема"))
    n_claude_in = sum(1 for it in cache["items"] if it.get("only") != "lite")
    n_lite_in = sum(1 for it in cache["items"] if it.get("only") != "claude")
    out("Записи в кеша: за Claude {} (преди дубликати и таван на тема), за Lite {}; "
        "Lite групира {} в истории.".format(n_claude_in, n_lite_in, l_count))
    out("")
    out("## Брой истории")
    out("")
    out("| | Claude | Lite (както е) | Lite (първите {} по оценка) |".format(len(c_stories)))
    out("|---|---|---|---|")
    out("| Избрани истории | {} | {} | {} |".format(len(c_stories), len(l_stories), len(trimmed)))
    out("| Общи с другата | {} | {} | {} |".format(len(full["pairs"]), len(full["pairs"]),
                                                  len(equal["pairs"])))
    out("| Само в тази | {} | {} | {} |".format(len(full["only_c"]), len(full["only_l"]),
                                               len(equal["only_l"])))
    out("")
    out("Общи = делят поне един линк към статия. Втората двойка колони е честното сравнение "
        "при равен брой: Lite е орязан до най-високо оценените, колкото са историите на Claude.")
    out("")

    out("## По рубрики (петте рубрики на Claude)")
    out("")
    l_rub = rubric_counts(l_stories, topic_name_to_id)
    c_rub = Counter(s.get("section", "Свят") for s in c_stories)
    out("| Рубрика | Claude | Lite |")
    out("|---|---|---|")
    for sec in claude.SECTIONS:
        out("| {} | {} | {} |".format(sec, c_rub.get(sec, 0), l_rub.get(sec, 0)))
    out("")

    out("## Главното днес")
    out("")
    out("**Claude** (по оценка):")
    for n, i in enumerate(sorted(full["c_top"], key=lambda i: -c_stories[i].get("score", 0)), 1):
        j = full["pair_of_c"].get(i)
        mark = ("и в Lite като „Главното“" if j in full["l_top"] else
                "в Lite, но не като „Главното“" if j is not None else "няма в Lite")
        out("{}. {} — *{}*".format(n, describe_claude(c_stories[i], c_items), mark))
    out("")
    out("**Lite** (по оценка):")
    c_of_l = {j: i for i, j, _ in full["pairs"]}
    for n, j in enumerate(full["l_top"], 1):
        i = c_of_l.get(j)
        mark = ("и в Claude като „Главното“" if i in full["c_top"] else
                "в Claude, но не като „Главното“" if i is not None else "няма в Claude")
        out("{}. {} — *{}*".format(n, describe_lite(l_stories[j]), mark))
    out("")
    out("Съвпадат като „Главното днес“: {} от {} (Claude) и {} (Lite).".format(
        full["top_both"], len(full["c_top"]), len(full["l_top"])))
    out("")

    out("## Общи истории ({})".format(len(full["pairs"])))
    out("")
    for i, j, shared in sorted(full["pairs"]):
        out("- Claude: {}".format(describe_claude(c_stories[i], c_items)))
        out("  Lite: {}  (общи линкове: {})".format(describe_lite(l_stories[j]), shared))
    out("")
    out("## Само в Claude ({})".format(len(full["only_c"])))
    out("")
    for i in full["only_c"]:
        out("- {}".format(describe_claude(c_stories[i], c_items)))
    out("")
    out("## Само в Lite ({} от всички; {} от първите {})".format(
        len(full["only_l"]), len(equal["only_l"]), len(trimmed)))
    out("")
    for j in full["only_l"]:
        out("- {}{}".format(describe_lite(l_stories[j]), "" if l_stories[j] in trimmed else "  (извън първите {})".format(len(trimmed))))
    out("")
    out("## Денят с 3 изречения (Claude)")
    out("")
    out(c_data.get("day_in_three", ""))
    return "\n".join(lines), full, equal


def main():
    ap = argparse.ArgumentParser(description="Сравнение на Claude и Lite върху един общ кеш")
    ap.add_argument("--cache", help="път до кеш или „latest“; без него се тегли нов")
    ap.add_argument("--fetch-only", action="store_true", help="само тегли и записва кеша")
    ap.add_argument("--reuse-claude", action="store_true", help="отговорът на Claude е от кеша")
    ap.add_argument("--hours", type=int, help="равен прозорец в часове за всички теми")
    ap.add_argument("--all-topics", action="store_true", help="всички теми от каталога")
    args = ap.parse_args()

    catalog, profile, topics, selected = load_setup(args.all_topics)
    CACHE_DIR.mkdir(parents=True, exist_ok=True)

    if args.cache:
        path = cache_path(args.cache)
        cache = json.loads(path.read_text(encoding="utf-8"))
        selected = [t for t in cache["topics"] if t in topics]
        print("Ползвам кеша {}".format(path))
    else:
        cache = fetch_cache(catalog, topics, selected, args.hours)
        stamp = datetime.fromtimestamp(cache["fetched_at"]).strftime("%Y-%m-%d_%H%M")
        path = CACHE_DIR / "{}.json".format(stamp)
        path.write_text(json.dumps(cache, ensure_ascii=False), encoding="utf-8")
        print("Кешът е записан: {} ({} новини)".format(path, len(cache["items"])))
    if args.fetch_only:
        return
    if not cache["items"]:
        sys.exit("Кешът е празен")

    l_stories, l_count = run_lite(cache, catalog, profile, topics, selected)
    c_data, c_items, fresh = run_claude(cache, args.reuse_claude)
    if fresh:
        cache["claude"] = {"data": c_data, "items": c_items}
        path.write_text(json.dumps(cache, ensure_ascii=False), encoding="utf-8")
    c_stories = claude.rank_stories(c_data["stories"], c_items)

    trimmed = l_stories[:len(c_stories)]   # l_stories вече са по низходяща оценка
    name_to_id = {t["name"]: t["id"] for t in topics.values()}
    report, full, equal = build_report(cache, c_stories, c_items, l_stories, l_count,
                                       trimmed, name_to_id, c_data)
    report_path = OUT / "report-{}.md".format(path.stem)
    report_path.write_text(report, encoding="utf-8")
    print()
    print(report)
    print()
    print("Докладът е записан: {}".format(report_path))


if __name__ == "__main__":
    main()
