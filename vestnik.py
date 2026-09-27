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

