#!/usr/bin/env python3
"""Вестник Lite: събира RSS новини и прави вестник като HTML страница — без LLM.

Подборът е с правила: еднаквите истории се обединяват по сходство на текста (TF-IDF),
оценката е свежест + брой източници + твоите теми от preferences.yaml, а резюмето са първите
изречения на самия източник.
"""

import calendar
import html
import json
import logging
import math
import re
import sys
import time
import urllib.request
import webbrowser
from collections import Counter
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime
from pathlib import Path

import feedparser
import yaml

BASE = Path(__file__).resolve().parent
OUTPUT = BASE / "output"
USER_AGENT = "Mozilla/5.0 (Macintosh) VestnikLite/1.0"
SIMILARITY = 0.28        # над тази стойност две новини се броят за една история
TOP_COUNT = 4            # колко истории са „Главното днес“
MAX_PER_SECTION = 5

WEEKDAYS = ["понеделник", "вторник", "сряда", "четвъртък", "петък", "събота", "неделя"]
MONTHS = ["януари", "февруари", "март", "април", "май", "юни", "юли",
          "август", "септември", "октомври", "ноември", "декември"]
# Рубриката от източника е само подсказка: новина от български сайт за чужда тема отива в „Свят“,
# освен ако в текста има някоя от тези думи.
SECTION_KEYWORDS = {
    "България": ["българи", "софи", "радев", "пловдив", "варна", "бургас", "народно събрание",
                 "bulgaria", "sofia", "цар самуил", "евро", "бнб"],
    "Армения": ["армени", "armenia", "ереван", "yerevan", "пашинян", "pashinyan", "карабах",
                "karabakh", "сюник", "syunik", "азербайджан", "azerbaijan", "հայաստան", "հայ",
                "երևան", "փաշինյան", "ադրբեջան"],
}
STOPWORDS = set("""the a an and or of to in on for with at by from is are was were be as it its
this that after over says said new about into amid и в на за от с по се да е са че не при като
към или но през след до този тази това които който които има ще е в на и от за по при как""".split())

log = logging.getLogger("lite")


# ---------- 1. Събиране ----------

def clean_text(text, limit=600):
    text = re.sub(r"<[^>]+>", " ", text or "")
    text = html.unescape(re.sub(r"\s+", " ", text)).strip()
    return text[:limit]


def fetch_source(source, since, limit):
    """Новините от един източник. При грешка връща празен списък."""
    try:
        req = urllib.request.Request(source["url"], headers={"User-Agent": USER_AGENT})
        with urllib.request.urlopen(req, timeout=20) as resp:
            feed = feedparser.parse(resp.read())
        items = []
        for entry in feed.entries:
            parsed = entry.get("published_parsed") or entry.get("updated_parsed")
            ts = calendar.timegm(parsed) if parsed else time.time()
            if ts < since:
                continue
            title = clean_text(entry.get("title"), 200)
            if not title or not entry.get("link"):
                continue
            items.append({
                "title": title,
                "summary": clean_text(entry.get("summary")),
                "link": entry["link"],
                "source": source["name"],
                "section": source.get("section", ""),
                "weight": source.get("weight", 1.0),
                "ts": ts,
            })
            if len(items) >= limit:
                break
        log.info("OK   %-14s %d новини", source["name"], len(items))
        return items
    except Exception as e:
        log.error("ГРЕШКА %-14s %s", source["name"], e)
        return []


def fetch_all(config):
    settings = config["settings"]
    since = time.time() - settings["hours_back"] * 3600
    with ThreadPoolExecutor(max_workers=8) as pool:
        results = pool.map(lambda s: fetch_source(s, since, settings["per_source_limit"]),
                           config["sources"])
    return [item for items in results for item in items]


# ---------- 2. Обединяване на еднакви истории (TF-IDF) ----------

def tokens(item):
    text = (item["title"] + " ") * 2 + item["summary"]
    return [w for w in re.findall(r"\w+", text.lower()) if len(w) > 2 and w not in STOPWORDS]


def vectorize(items):
    docs = [Counter(tokens(it)) for it in items]
    df = Counter(term for doc in docs for term in doc)
    n = len(docs)
    vectors = []
    for doc in docs:
        vec = {t: c * (math.log((n + 1) / (df[t] + 1)) + 1) for t, c in doc.items()}
        norm = math.sqrt(sum(v * v for v in vec.values())) or 1.0
        vectors.append({t: v / norm for t, v in vec.items()})
    return vectors


def cosine(a, b):
    if len(a) > len(b):
        a, b = b, a
    return sum(v * b.get(t, 0.0) for t, v in a.items())


def cluster(items):
    """Групира новините за едно и също събитие. Две новини от един източник не се сливат."""
    vectors = vectorize(items)
    clusters = []   # списъци от индекси
    for i in range(len(items)):
        best, best_sim = None, SIMILARITY
        for c in clusters:
            if any(items[j]["source"] == items[i]["source"] for j in c):
                continue
            sim = max(cosine(vectors[i], vectors[j]) for j in c)
            if sim > best_sim:
                best, best_sim = c, sim
        if best is None:
            clusters.append([i])
        else:
            best.append(i)
    return [[items[i] for i in c] for c in clusters]


# ---------- 3. Оценка и резюме ----------

def contains_any(text, words):
    low = text.lower()
    return sum(1 for w in words if str(w).lower() in low)


def score(group, prefs, hours_back):
    text = " ".join(it["title"] + " " + it["summary"] for it in group)
    newest = max(it["ts"] for it in group)
    fresh = max(0.0, 1 - (time.time() - newest) / 3600 / hours_back)
    sources = len({it["source"] for it in group})
    weight = max(it["weight"] for it in group)
    more = min(contains_any(text, prefs.get("повече", [])), 2) * 2
    less = min(contains_any(text, prefs.get("по-малко", [])), 2) * 2
    return 2 * fresh + 1.5 * min(sources - 1, 4) + (weight - 1) * 2 + more - less


def make_story(group, prefs, hours_back):
    # Заглавие и резюме от най-подробния запис; секция — най-честата
    lead = max(group, key=lambda it: (len(it["summary"]), it["weight"]))
    summary = lead["summary"]
    sentences = re.split(r"(?<=[.!?…])\s+", summary)
    text = ""
    for s in sentences:
        if len(text) >= 160 or s.strip().lower() == lead["title"].strip().lower():
            break
        text = (text + " " + s).strip()
    text = text[:320] + ("…" if len(text) > 320 else "")
    section = Counter(it["section"] for it in group).most_common(1)[0][0] or "Други"
    keywords = SECTION_KEYWORDS.get(section)
    if keywords and not contains_any(lead["title"] + " " + lead["summary"], keywords):
        section = "Свят"
    links, seen = [], set()
    for it in sorted(group, key=lambda it: -it["weight"]):
        if it["source"] not in seen:
            seen.add(it["source"])
            links.append((it["source"], it["link"]))
    return {"title": lead["title"], "summary": text, "section": section, "links": links,
            "score": score(group, prefs, hours_back)}


def build_stories(items, config, prefs):
    never = [str(w).lower() for w in prefs.get("никога", [])]
    stories = []
    for group in cluster(items):
        story = make_story(group, prefs, config["settings"]["hours_back"])
        blob = (story["title"] + " " + story["summary"]).lower()
        if any(w in blob for w in never):
            continue
        stories.append(story)
    stories.sort(key=lambda s: -s["score"])
    return stories


def pick(stories, max_stories):
    """Най-добрите истории като цяло, но не повече от MAX_PER_SECTION в рубрика."""
    per_section, chosen = Counter(), []
    for s in stories:
        if per_section[s["section"]] >= MAX_PER_SECTION:
            continue
        per_section[s["section"]] += 1
        chosen.append(s)
        if len(chosen) >= max_stories:
            break
    for n, s in enumerate(chosen):
        s["top"] = n < TOP_COUNT
    return chosen


# ---------- 4. Времето ----------

WEATHER_CODES = [
    ((0,), "Ясно"), ((1,), "Предимно ясно"), ((2,), "Променлива облачност"),
    ((3,), "Облачно"), ((45, 48), "Мъгла"), ((51, 53, 55, 56, 57), "Ръмеж"),
    ((61,), "Слаб дъжд"), ((63,), "Дъжд"), ((65,), "Силен дъжд"), ((66, 67), "Леден дъжд"),
    ((71, 73, 75, 77), "Сняг"), ((80, 81, 82), "Превалявания"),
    ((85, 86), "Снежни превалявания"), ((95, 96, 99), "Гръмотевични бури"),
]


def fetch_weather(place):
    """Прогноза от Open-Meteo (безплатно, без ключ). При грешка връща None."""
    url = ("https://api.open-meteo.com/v1/forecast?latitude={lat}&longitude={lon}"
           "&daily=weather_code,temperature_2m_max,temperature_2m_min,"
           "precipitation_probability_max,wind_speed_10m_max&timezone=auto"
           "&forecast_days=1").format(**place)
    try:
        req = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
        with urllib.request.urlopen(req, timeout=20) as resp:
            daily = json.loads(resp.read())["daily"]
        code = daily["weather_code"][0]
        text = next((t for codes, t in WEATHER_CODES if code in codes), "Променливо")
        return {"city": place["name"], "text": text,
                "max": round(daily["temperature_2m_max"][0]),
                "min": round(daily["temperature_2m_min"][0]),
                "rain": daily["precipitation_probability_max"][0] or 0,
                "wind": round(daily["wind_speed_10m_max"][0])}
    except Exception as e:
        log.error("ГРЕШКА времето за %s: %s", place.get("name"), e)
        return None


# ---------- 5. HTML ----------

PAGE = """<!doctype html>
<html lang="bg"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>Вестник Lite — {date}</title>
<style>
:root {{ --bg:#faf7f0; --ink:#1c1a17; --muted:#6b645a; --accent:#8b1e1e; --box:#f3eee3; --line:#cfc6b4; }}
@media (prefers-color-scheme: dark) {{
  :root {{ --bg:#17150f; --ink:#ece6d8; --muted:#a39b8c; --accent:#e08a7a; --box:#221f17; --line:#3a352a; }} }}
body {{ margin:0; background:var(--bg); color:var(--ink); font:17px/1.5 Georgia,'PT Serif',serif; }}
main {{ max-width:960px; margin:0 auto; padding:16px; }}
header {{ text-align:center; border-bottom:3px double var(--ink); padding-bottom:8px; }}
h1 {{ font-size:2.4rem; margin:.2em 0 0; }}
.date {{ color:var(--muted); font-size:.85rem; }}
.weather {{ background:var(--box); padding:10px 14px; margin:14px 0; text-align:center; }}
.weather b {{ color:var(--accent); font-size:.8rem; letter-spacing:.06em; }}
h2 {{ font-size:.85rem; letter-spacing:.08em; text-transform:uppercase; color:var(--ink);
     border-bottom:1px solid var(--line); margin:22px 0 4px; }}
h2.top {{ color:var(--accent); border-color:var(--accent); }}
.cols {{ column-width:300px; column-gap:28px; }}
article {{ break-inside:avoid; margin:8px 0 14px; }}
article h3 {{ margin:0 0 2px; font-size:1.05rem; line-height:1.25; }}
article.big h3 {{ font-size:1.2rem; }}
article p {{ margin:0; font-size:.92rem; text-align:justify; }}
.src {{ font-size:.75rem; color:var(--muted); }}
.src a {{ color:var(--accent); text-decoration:none; }}
footer {{ margin:28px 0 8px; font-size:.75rem; color:var(--muted); text-align:center; }}
</style></head><body><main>
<header><div class="date">{date} · {count} истории · съставен в {time}</div>
<h1>Вестник Lite</h1></header>
{weather}
{body}
<footer>Подбрано автоматично с правила — без изкуствен интелект. Резюметата са от самите източници.</footer>
</main></body></html>
"""


def bg_date(d):
    return "{}, {} {} {} г.".format(WEEKDAYS[d.weekday()].capitalize(), d.day,
                                    MONTHS[d.month - 1], d.year)


def render_story(s, big=False):
    e = html.escape
    links = " · ".join('<a href="{}">{}</a>'.format(e(url, quote=True), e(name))
                       for name, url in s["links"])
    summary = "<p>{}</p>".format(e(s["summary"])) if s["summary"] else ""
    return '<article class="{}"><h3>{}</h3>{}<div class="src">{}</div></article>'.format(
        "big" if big else "", e(s["title"]), summary, links)


def render_weather(w):
    if not w:
        return ""
    return ('<div class="weather"><b>ВРЕМЕТО ДНЕС · {}</b><br>{}° / {}° · {} · дъжд {}% · '
            'вятър до {} км/ч</div>').format(html.escape(w["city"].upper()), w["max"], w["min"],
                                             w["text"], w["rain"], w["wind"])


def render(stories, weather, today, section_order):
    body = []
    top = [s for s in stories if s["top"]]
    if top:
        body.append('<h2 class="top">Главното днес</h2><div class="cols">{}</div>'.format(
            "".join(render_story(s, big=True) for s in top)))
    for name in section_order + sorted({s["section"] for s in stories} - set(section_order)):
        group = [s for s in stories if not s["top"] and s["section"] == name]
        if group:
            body.append("<h2>{}</h2><div class=\"cols\">{}</div>".format(
                html.escape(name), "".join(render_story(s) for s in group)))
    return PAGE.format(date=bg_date(today), count=len(stories),
                       time=datetime.now().strftime("%H:%M"),
                       weather=render_weather(weather), body="\n".join(body))


# ---------- main ----------

def main():
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    today = datetime.now()
    OUTPUT.mkdir(exist_ok=True)
    out = OUTPUT / "{}.html".format(today.strftime("%Y-%m-%d"))
    if "--auto" in sys.argv and "--force" not in sys.argv and (out.exists() or today.hour < 5):
        return

    config = yaml.safe_load((BASE / "sources.yaml").read_text(encoding="utf-8"))
    prefs_file = BASE / "preferences.yaml"
    prefs = yaml.safe_load(prefs_file.read_text(encoding="utf-8")) if prefs_file.exists() else {}
    prefs = prefs or {}

    place = config.get("weather")
    weather = fetch_weather(place) if place else None
    items = fetch_all(config)
    if not items:
        sys.exit("Нито един източник не върна новини")
    stories = pick(build_stories(items, config, prefs), config["settings"]["max_stories"])

    order = []
    for s in config["sources"]:
        if s.get("section") and s["section"] not in order:
            order.append(s["section"])
    page = render(stories, weather, today, order)
    out.write_text(page, encoding="utf-8")
    (OUTPUT / "latest.html").write_text(page, encoding="utf-8")
    log.info("Готово: %s (%d истории от %d новини)", out, len(stories), len(items))
    if "--open" in sys.argv:
        webbrowser.open(out.as_uri())


if __name__ == "__main__":
    main()
