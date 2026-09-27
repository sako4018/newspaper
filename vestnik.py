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

