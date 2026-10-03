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
import shutil
import subprocess
import sys
import time
import urllib.parse
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
CATALOG = BASE / "catalog.yaml"
PROFILE = BASE / "profile.yaml"   # личният избор на потребителя

WEEKDAYS = ["понеделник", "вторник", "сряда", "четвъртък", "петък", "събота", "неделя"]
MONTHS = ["януари", "февруари", "март", "април", "май", "юни", "юли",
          "август", "септември", "октомври", "ноември", "декември"]
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
                "section": source["topic_name"],
                "topic": source["topic"],
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


def fetch_all(sources, settings):
    since = time.time() - settings["hours_back"] * 3600
    with ThreadPoolExecutor(max_workers=8) as pool:
        results = pool.map(lambda src: fetch_source(src, since, settings["per_source_limit"]),
                           sources)
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
    section = Counter(it["section"] for it in group).most_common(1)[0][0]
    links, seen = [], set()
    for it in sorted(group, key=lambda it: -it["weight"]):
        if it["source"] not in seen:
            seen.add(it["source"])
            links.append((it["source"], it["link"]))
    return {"title": lead["title"], "summary": text, "section": section, "links": links,
            "score": score(group, prefs, hours_back)}


def keep_relevant(items, topics, selected):
    """Тема с keywords (България, Армения) задържа новина само ако съдържа някоя от думите.
    Иначе новината отива в „Свят“, ако потребителят следи тази тема, или се пропуска."""
    kept = []
    for it in items:
        words = topics[it["topic"]].get("keywords")
        if words and not contains_any(it["title"] + " " + it["summary"], words):
            if "world" not in selected:
                continue
            it = dict(it, topic="world", section=topics["world"]["name"])
        kept.append(it)
    return kept


def build_stories(items, settings, prefs):
    never = [str(w).lower() for w in prefs.get("никога", [])]
    stories = []
    for group in cluster(items):
        story = make_story(group, prefs, settings["hours_back"])
        blob = (story["title"] + " " + story["summary"]).lower()
        if any(w in blob for w in never):
            continue
        stories.append(story)
    stories.sort(key=lambda s: -s["score"])
    return stories


def pick(stories, per_topic):
    """До per_topic най-добри истории от всяка избрана тема. Най-високо оценените
    като цяло са „Главното днес“."""
    count, chosen = Counter(), []
    for s in stories:
        if count[s["section"]] < per_topic:
            count[s["section"]] += 1
            chosen.append(s)
    for n, s in enumerate(chosen):
        s["top"] = n < TOP_COUNT
    return chosen


# ---------- 3б. Превод на български (офлайн, с Argos Translate) ----------

TRANSLATION_MODELS = [("en", "bg"), ("ru", "en")]   # руският минава през английски


def detect_lang(text):
    """„en“ за латиница, „ru“ за руски, иначе None (български, арменски и т.н. не се превеждат)."""
    letters = [c for c in text if c.isalpha()]
    if not letters:
        return None
    if sum("a" <= c.lower() <= "z" for c in letters) / len(letters) > 0.8:
        return "en"
    if re.search("[ыэё]", text.lower()):
        return "ru"
    return None


def translate_stories(stories):
    """Превежда на български заглавията и резюметата на чуждоезичните истории."""
    try:
        import argostranslate.package as argos_package
        import argostranslate.translate as argos
    except ImportError:
        log.warning("Няма argostranslate — новините остават на езика на източника")
        return
    installed = {(p.from_code, p.to_code) for p in argos_package.get_installed_packages()}
    missing = [pair for pair in TRANSLATION_MODELS if pair not in installed]
    if missing:
        log.info("Теглене на модели за превод (само първия път): %s", missing)
        argos_package.update_package_index()
        for pkg in argos_package.get_available_packages():
            if (pkg.from_code, pkg.to_code) in missing:
                argos_package.install_from_path(pkg.download())
    for s in stories:
        original = s["title"]
        for key in ("title", "summary"):
            lang = detect_lang(s[key])
            if lang and s[key]:
                try:
                    s[key] = argos.translate(s[key], lang, "bg")
                except Exception as e:
                    log.error("ГРЕШКА превод: %s", e)
        if s["title"] != original:
            s["original"] = original   # показва се под превода, за да се улавят грешките
    log.info("Преведени са %d истории", len(stories))


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
    original = ('<div style="font-size:.8em;color:#6b645a">{}</div>'.format(e(s["original"]))
                if s.get("original") else "")
    return '<article class="{}"><h3>{}</h3>{}{}<div class="src">{}</div></article>'.format(
        "big" if big else "", e(s["title"]), original, summary, links)


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


# ---------- Word документ (оформлението е от claude/vestnik.py) ----------

def build_docx(stories, weather, today, section_order):
    sys.path.insert(0, str(BASE.parent / "claude"))
    import vestnik as v
    from docx import Document
    from docx.enum.section import WD_SECTION
    from docx.enum.text import WD_ALIGN_PARAGRAPH
    from docx.shared import Cm, Pt

    def add_story(story, big=False):
        title = doc.add_paragraph()
        v.spacing(title, before=3, after=0.5, line=1.0)
        title.paragraph_format.keep_with_next = True
        v.set_font(title.add_run(story["title"]), 10.5 if big else 9.5, bold=True)
        if story.get("original"):
            orig = doc.add_paragraph()
            v.spacing(orig, after=0.5, line=1.0)
            orig.paragraph_format.keep_with_next = True
            v.set_font(orig.add_run(story["original"]), 7.5, color=v.MUTED)
        if story["summary"]:
            text = doc.add_paragraph()
            v.spacing(text, after=0.5, line=1.0)
            text.alignment = WD_ALIGN_PARAGRAPH.JUSTIFY
            v.set_font(text.add_run(story["summary"]), 8.5)
        links = doc.add_paragraph()
        v.spacing(links, after=1, line=1.0)
        for n, (name, url) in enumerate(story["links"]):
            if n:
                v.set_font(links.add_run(" · "), 7.5, color=v.MUTED)
            v.add_hyperlink(links, url, name)

    doc = Document()
    section = doc.sections[0]
    section.page_width, section.page_height = Cm(21), Cm(29.7)
    section.left_margin = section.right_margin = Cm(1.0)
    section.top_margin = section.bottom_margin = Cm(0.9)

    kicker = doc.add_paragraph()
    v.spacing(kicker, after=2)
    v.add_border(kicker, "bottom", size=4, color="CFC6B4")
    kicker.alignment = WD_ALIGN_PARAGRAPH.CENTER
    v.set_font(kicker.add_run("{}  ·  {} истории  ·  съставен в {}".format(
        bg_date(today), len(stories), datetime.now().strftime("%H:%M"))), 7.5, color=v.MUTED)

    name = doc.add_paragraph()
    v.spacing(name, after=2)
    name.alignment = WD_ALIGN_PARAGRAPH.CENTER
    v.add_border(name, "bottom", size=12, style="double", space=2)
    v.set_font(name.add_run("Сутрешен вестник Lite"), 26, bold=True)

    if weather:
        line = doc.add_paragraph()
        v.spacing(line, before=3, after=3)
        line.alignment = WD_ALIGN_PARAGRAPH.CENTER
        v.set_font(line.add_run("ВРЕМЕТО ДНЕС · {}   ".format(weather["city"].upper())),
                   7.5, bold=True, color=v.ACCENT)
        v.set_font(line.add_run("{}° / {}° · {} · дъжд {}% · вятър до {} км/ч · {}".format(
            weather["max"], weather["min"], weather["text"], weather["rain"],
            weather["wind"], v.weather_tip(weather))), 8.5)

    body = doc.add_section(WD_SECTION.CONTINUOUS)
    v.set_columns(body, 2)
    breaker = doc.paragraphs[-1]
    v.spacing(breaker, after=3, line=Pt(1))

    top = [s for s in stories if s["top"]]
    if top:
        v.add_heading(doc, "Главното днес", v.ACCENT)
        for s in top:
            add_story(s, big=True)
    for sec_name in section_order + sorted({s["section"] for s in stories} - set(section_order)):
        group = [s for s in stories if not s["top"] and s["section"] == sec_name]
        if group:
            v.add_heading(doc, sec_name)
            for s in group:
                add_story(s)
    return doc


# ---------- Профил: избор на теми при първо пускане ----------

def geocode(name):
    """Намира града по име (Open-Meteo, безплатно). Връща списък с {name, lat, lon}."""
    url = "https://geocoding-api.open-meteo.com/v1/search?name={}&count=5&language=bg".format(
        urllib.parse.quote(name))
    try:
        req = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
        with urllib.request.urlopen(req, timeout=20) as resp:
            found = json.loads(resp.read()).get("results", [])
    except Exception as e:
        log.error("Не мога да търся града: %s", e)
        return []
    return [{"name": r["name"] + (", " + r["country"] if r.get("country") else ""),
             "lat": r["latitude"], "lon": r["longitude"]} for r in found]


def ask_list(question):
    return [w.strip() for w in input(question).split(",") if w.strip()]


def setup(catalog):
    """Пита потребителя какво да следи и записва profile.yaml."""
    topics = catalog["topics"]
    print("\nВестник Lite — какво искаш да следиш?\n")
    for n, t in enumerate(topics, 1):
        print("  {:>2}. {} — {}".format(n, t["name"], t["about"]))
    while True:
        raw = input("\nНомера на темите през запетая (или „всички“): ").strip().lower()
        if raw in ("всички", "all"):
            chosen = list(range(len(topics)))
        else:
            try:
                chosen = [int(x) - 1 for x in raw.replace(" ", "").split(",") if x]
            except ValueError:
                chosen = []
        if chosen and all(0 <= i < len(topics) for i in chosen):
            break
        print("Въведи номера от списъка, например: 1,4,5")

    city = None
    while True:
        name = input("\nГрад за времето (Enter, ако не искаш): ").strip()
        if not name:
            break
        options = geocode(name)
        if not options:
            print("Не намерих такъв град, опитай пак.")
            continue
        for n, o in enumerate(options, 1):
            print("  {}. {}".format(n, o["name"]))
        pick_n = input("Кой от тях? (номер, Enter за 1): ").strip() or "1"
        if pick_n.isdigit() and 1 <= int(pick_n) <= len(options):
            city = options[int(pick_n) - 1]
            break

    print("\nНезадължително — думи през запетая (Enter за пропускане):")
    profile = {
        "topics": [topics[i]["id"] for i in dict.fromkeys(chosen)],
        "city": city,
        "stories_per_topic": 4,
        "повече": ask_list("  Искам повече новини за: "),
        "по-малко": ask_list("  Искам по-малко за: "),
        "никога": ask_list("  Никога не показвай: "),
    }
    PROFILE.write_text(yaml.safe_dump(profile, allow_unicode=True, sort_keys=False),
                       encoding="utf-8")
    print("\nЗаписано в {}. Промяна по-късно: python lite.py --setup\n".format(PROFILE.name))
    return profile


# ---------- main ----------

def main():
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    today = datetime.now()
    OUTPUT.mkdir(exist_ok=True)
    ext = "html" if "--html" in sys.argv else "docx"
    out = OUTPUT / "{}.{}".format(today.strftime("%Y-%m-%d"), ext)
    if "--auto" in sys.argv and "--force" not in sys.argv and (out.exists() or today.hour < 5):
        return

    catalog = yaml.safe_load(CATALOG.read_text(encoding="utf-8"))
    if "--setup" in sys.argv or not PROFILE.exists():
        if "--auto" in sys.argv:
            sys.exit("Няма профил. Пусни ръчно „python lite.py --setup“ и избери теми.")
        profile = setup(catalog)
    else:
        profile = yaml.safe_load(PROFILE.read_text(encoding="utf-8"))

    settings = catalog["settings"]
    topics = {t["id"]: t for t in catalog["topics"]}
    selected = [t for t in profile["topics"] if t in topics]
    sources = [dict(src, topic=t, topic_name=topics[t]["name"])
               for t in selected for src in topics[t]["sources"]]
    if not sources:
        sys.exit("Няма избрани теми. Пусни „python lite.py --setup“.")

    weather = fetch_weather(profile["city"]) if profile.get("city") else None
    items = fetch_all(sources, settings)
    if not items:
        sys.exit("Нито един източник не върна новини")
    items = keep_relevant(items, topics, selected)
    stories = pick(build_stories(items, settings, profile), profile.get("stories_per_topic", 4))

    translate_stories(stories)
    order = [topics[t]["name"] for t in selected]
    latest = OUTPUT / "latest.{}".format(ext)
    if ext == "html":
        page = render(stories, weather, today, order)
        out.write_text(page, encoding="utf-8")
        latest.write_text(page, encoding="utf-8")
    else:
        build_docx(stories, weather, today, order).save(out)
        shutil.copyfile(out, latest)
    log.info("Готово: %s (%d истории от %d новини)", out, len(stories), len(items))
    if "--open" in sys.argv:
        if ext == "html":
            webbrowser.open(out.as_uri())
        else:
            subprocess.run(["open", str(out)])


if __name__ == "__main__":
    main()
