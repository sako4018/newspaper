#!/usr/bin/env python3
"""Сутрешен вестник: събира RSS новини, обобщава ги с Claude и прави Word (.docx) вестник."""

import calendar
import difflib
import html
import json
import logging
import re
import shutil
import subprocess
import sys
import tempfile
import time
import urllib.error
import urllib.request
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime
from pathlib import Path
from string import Template

import feedparser
import yaml
from docx import Document
from docx.enum.section import WD_SECTION
from docx.enum.table import WD_ALIGN_VERTICAL
from docx.enum.text import WD_ALIGN_PARAGRAPH
from docx.opc.constants import RELATIONSHIP_TYPE
from docx.oxml import OxmlElement
from docx.oxml.ns import qn
from docx.shared import Cm, Pt, RGBColor

BASE = Path(__file__).resolve().parent
NEWSPAPERS = BASE / "newspapers"
LOGS = BASE / "logs"
SECTIONS = ["България", "Армения", "Свят", "Технологии и AI", "Любопитно"]
USER_AGENT = "Mozilla/5.0 (Macintosh) SutreshenVestnik/1.0"

FONT = "PT Serif"   # шрифт, създаден за кирилица; има го на всеки Mac
INK = RGBColor(0x1C, 0x1A, 0x17)
ACCENT = RGBColor(0x8B, 0x1E, 0x1E)
MUTED = RGBColor(0x6B, 0x64, 0x5A)

WEEKDAYS = ["понеделник", "вторник", "сряда", "четвъртък", "петък", "събота", "неделя"]
MONTHS = ["януари", "февруари", "март", "април", "май", "юни", "юли",
          "август", "септември", "октомври", "ноември", "декември"]

log = logging.getLogger("vestnik")


def setup_logging():
    LOGS.mkdir(exist_ok=True)
    fmt = logging.Formatter("%(asctime)s %(levelname)s %(message)s")
    file_handler = logging.FileHandler(LOGS / "vestnik.log", encoding="utf-8")
    file_handler.setFormatter(fmt)
    console = logging.StreamHandler(sys.stdout)
    console.setFormatter(fmt)
    log.addHandler(file_handler)
    log.addHandler(console)
    log.setLevel(logging.INFO)


def load_config():
    with open(BASE / "sources.yaml", encoding="utf-8") as f:
        return yaml.safe_load(f)


# ---------- 1. Събиране ----------

def clean_text(text, limit=300):
    text = re.sub(r"<[^>]+>", " ", text or "")
    text = html.unescape(re.sub(r"\s+", " ", text)).strip()
    return text[:limit] + ("…" if len(text) > limit else "")


def fetch_source(source, since, limit):
    """Връща списък с новини от един източник. При грешка връща празен списък."""
    try:
        req = urllib.request.Request(source["url"], headers={"User-Agent": USER_AGENT})
        with urllib.request.urlopen(req, timeout=20) as resp:
            feed = feedparser.parse(resp.read())
        items = []
        for entry in feed.entries:
            parsed = entry.get("published_parsed") or entry.get("updated_parsed")
            if parsed and calendar.timegm(parsed) < since:
                continue
            title = clean_text(entry.get("title"), 200)
            if not title or not entry.get("link"):
                continue
            items.append({
                "title": title,
                "summary": clean_text(entry.get("summary")),
                "link": entry.get("link"),
                "source": source["name"],
                "section": source.get("section", ""),
            })
            if len(items) >= limit:
                break
        log.info("OK   %-14s %d новини", source["name"], len(items))
        return items
    except Exception as e:
        log.error("ГРЕШКА %-14s %s: %s", source["name"], source["url"], e)
        return []


def fetch_all(config):
    settings = config["settings"]
    since = time.time() - settings["hours_back"] * 3600
    with ThreadPoolExecutor(max_workers=8) as pool:
        results = pool.map(
            lambda s: fetch_source(s, since, settings["per_source_limit"]),
            config["sources"])
    return [item for items in results for item in items]


# ---------- 2. Махане на очевидни дубликати ----------

def normalize(title):
    return re.sub(r"[^\w ]", "", title.lower())


def dedupe(items):
    kept = []
    for item in items:
        norm = normalize(item["title"])
        if any(difflib.SequenceMatcher(None, norm, normalize(k["title"])).ratio() > 0.85
               for k in kept):
            continue
        kept.append(item)
    return kept


# ---------- 3. Обобщаване с Claude ----------

PROMPT = """Ти си главен редактор на кратък сутрешен вестник на български език.
Читателят се интересува най-вече от: $interests.

По-долу има списък с новини от последните 24 часа. Всяка започва с номер в [квадратни скоби].

Задачи:
1. Обедини новините, които разказват една и съща история (от различни източници), в една.
2. Избери около $max_stories най-важни истории. Предпочитай значими събития пред дребни.
   Включи поне 2 за Армения и поне 2 за технологии/AI, ако има подходящи.
3. За всяка история напиши на български:
   - "title": кратко и ясно заглавие (до 12 думи);
   - "summary": неутрално и фактологично резюме, без измислици. Вестникът трябва да се
     събере на ЕДНА страница: за "top" историите 3 изречения (до 55 думи), за останалите
     2–3 изречения (до 40 думи). Всички резюмета общо — до 600 думи;
   - "section": една от рубриките: $sections;
   - "top": true за 3–5-те най-важни истории за деня, иначе false;
   - "ids": номерата на всички използвани новини от списъка.
4. Напиши "day_in_three": обобщение на деня точно в 3 кратки изречения (общо до 60 думи).

Отговори САМО с валиден JSON, без обяснения и без ```, в този формат:
{"day_in_three": "...", "stories": [{"title": "...", "summary": "...", "section": "...", "top": true, "ids": [1, 5]}]}

НОВИНИ:
$news
"""


def find_claude():
    return shutil.which("claude") or str(Path.home() / ".local/bin/claude")


def extract_json(text):
    start, end = text.find("{"), text.rfind("}")
    if start == -1 or end == -1:
        raise ValueError("В отговора няма JSON")
    return json.loads(text[start:end + 1])


def summarize(items, settings):
    news = "\n".join(
        "[{}] ({}, {}) {} — {}".format(i, it["source"], it["section"], it["title"], it["summary"])
        for i, it in enumerate(items))
    prompt = Template(PROMPT).substitute(
        interests=settings["interests"],
        max_stories=settings["max_stories"],
        sections=", ".join(SECTIONS),
        news=news)

    cmd = [find_claude(), "-p", "--output-format", "json",
           "--model", settings.get("claude_model", "sonnet"),
           "--tools", "", "--no-session-persistence"]
    last_error = None
    for attempt in (1, 2):
        try:
            log.info("Claude обобщава %d новини (опит %d)...", len(items), attempt)
            proc = subprocess.run(cmd, input=prompt, capture_output=True, text=True,
                                  timeout=900, cwd=tempfile.gettempdir())
            if proc.returncode != 0:
                raise RuntimeError("claude върна код {}: {}".format(
                    proc.returncode, (proc.stderr or proc.stdout)[:500]))
            outer = json.loads(proc.stdout)
            if outer.get("is_error"):
                raise RuntimeError("claude грешка: {}".format(outer.get("result")))
            data = extract_json(outer["result"])
            if not data.get("stories"):
                raise ValueError("Няма новини в отговора")
            return data
        except Exception as e:
            last_error = e
            log.warning("Опит %d неуспешен: %s", attempt, e)
    raise RuntimeError("Claude не успя да обобщи новините: {}".format(last_error))

