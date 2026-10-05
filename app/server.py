#!/usr/bin/env python3
"""Локално приложение „Сутрешен вестник“: страница за избор на версия и теми.

Сървърът е само със стандартната библиотека (http.server). PyYAML е нужен единствено за
четене на каталога и записване на профила, затова се пуска с .venv (виж start.sh).
Слуша само на 127.0.0.1.
"""

import json
import os
import re
import secrets
import subprocess
import sys
import threading
import time
import urllib.parse
import urllib.request
import webbrowser
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

try:
    import yaml
except ImportError:
    sys.exit("Липсва PyYAML. Пусни ./start.sh — той подготвя .venv.")

APP = Path(__file__).resolve().parent
ROOT = APP.parent
sys.path.insert(0, str(APP))
import platform_support   # noqa: E402  (всичко, което зависи от системата)

CATALOG = ROOT / "lite" / "catalog.yaml"
PROFILE = ROOT / "lite" / "profile.yaml"      # общ за двете версии, не влиза в git
INDEX = APP / "index.html"
PORTS = range(8765, 8786)
USER_AGENT = "Mozilla/5.0 (Macintosh) SutreshenVestnikApp/1.0"

VERSIONS = {
    "claude": {"script": ROOT / "claude" / "vestnik.py", "cwd": ROOT / "claude",
               "result": ROOT / "claude" / "latest.docx", "download": "Сутрешен вестник.docx"},
    "lite": {"script": ROOT / "lite" / "lite.py", "cwd": ROOT / "lite",
             "result": ROOT / "lite" / "output" / "latest.docx",
             "download": "Сутрешен вестник Lite.docx"},
}

# Готови комплекти теми (идове от каталога); липсващи идове се прескачат.
PRESETS = [
    {"name": "Всичко", "topics": "*"},
    {"name": "Новини", "topics": ["bg", "armenia", "world", "europe", "ukraine", "mideast"]},
    {"name": "Технологии и наука", "topics": ["tech", "ai", "science"]},
    {"name": "Свободно време", "topics": ["sport", "culture", "games", "cars", "curious"]},
    {"name": "Нищо", "topics": []},
]

# Нов потребител: нищо не е избрано предварително (версия и теми избира сам)
DEFAULT_PROFILE = {"version": None, "city": None, "stories_per_topic": 4,
                   "max_stories": 17, "повече": [], "по-малко": [], "никога": []}


# ---------- Каталог и профил ----------

def load_catalog():
    with open(CATALOG, encoding="utf-8") as f:
        return yaml.safe_load(f)


def load_profile(topic_ids):
    profile = dict(DEFAULT_PROFILE, topics=[])
    if PROFILE.exists():
        with open(PROFILE, encoding="utf-8") as f:
            saved = yaml.safe_load(f) or {}
        profile.update({k: v for k, v in saved.items() if k in profile})
        if profile["version"] not in VERSIONS:
            profile["version"] = None
    profile["topics"] = [t for t in profile["topics"] if t in topic_ids]
    return profile


def clean_words(value, name):
    if not isinstance(value, list) or len(value) > 50:
        raise ValueError("Списъкът „{}“ е невалиден.".format(name))
    words = []
    for w in value:
        w = str(w).strip()
        if len(w) > 60:
            raise ValueError("Думата в „{}“ е твърде дълга.".format(name))
        if w and w not in words:
            words.append(w)
    return words


def validate_profile(data, topic_ids):
    """Проверява това, което идва от страницата, и връща профил за записване."""
    if data.get("version") not in VERSIONS:
        raise ValueError("Избери версия: Claude или Lite.")
    topics = data.get("topics")
    if not isinstance(topics, list) or not topics or any(t not in topic_ids for t in topics):
        raise ValueError("Избери поне една тема.")
    city = data.get("city")
    if city is not None:
        try:
            city = {"name": str(city["name"])[:100], "lat": float(city["lat"]), "lon": float(city["lon"])}
        except (KeyError, TypeError, ValueError):
            raise ValueError("Градът е невалиден.")
        if not (-90 <= city["lat"] <= 90 and -180 <= city["lon"] <= 180):
            raise ValueError("Координатите на града са невалидни.")
    try:
        per_topic, max_stories = int(data.get("stories_per_topic", 4)), int(data.get("max_stories", 17))
    except (TypeError, ValueError):
        raise ValueError("Броят истории е невалиден.")
    if not (1 <= per_topic <= 10 and 5 <= max_stories <= 25):
        raise ValueError("Броят истории е извън допустимото.")
    return {
        "version": data["version"],
        "topics": [t for t in topic_ids if t in topics],   # редът е като в каталога
        "city": city,
        "stories_per_topic": per_topic,
        "max_stories": max_stories,
        "повече": clean_words(data.get("повече", []), "повече"),
        "по-малко": clean_words(data.get("по-малко", []), "по-малко"),
        "никога": clean_words(data.get("никога", []), "никога"),
    }


def save_profile(profile):
    # Часът и печатът се задават от съветника за инсталиране; страницата не ги пипа.
    if PROFILE.exists():
        with open(PROFILE, encoding="utf-8") as f:
            saved = yaml.safe_load(f) or {}
        for key in ("schedule_time", "print"):
            if key in saved and key not in profile:
                profile[key] = saved[key]
    text = yaml.safe_dump(profile, allow_unicode=True, sort_keys=False)
    tmp = PROFILE.with_suffix(".tmp")
    tmp.write_text(text, encoding="utf-8")
    tmp.replace(PROFILE)


def geocode(name):
    url = "https://geocoding-api.open-meteo.com/v1/search?name={}&count=6&language=bg".format(
        urllib.parse.quote(name))
    req = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
    with urllib.request.urlopen(req, timeout=15) as resp:
        found = json.loads(resp.read()).get("results", [])
    return [{"name": r["name"] + (", " + r["country"] if r.get("country") else ""),
             "lat": r["latitude"], "lon": r["longitude"]} for r in found]


# ---------- Пускане на вестника ----------

class Job:
    """Един вестник се прави наведнъж. Състоянието се чете от страницата през /api/status."""

    def __init__(self):
        self.lock = threading.Lock()
        self.state, self.version, self.lines = "idle", None, []
        self.started = self.finished = None
        self.stories = self.error = None

    def snapshot(self):
        with self.lock:
            end = self.finished or time.time()
            return {"state": self.state, "version": self.version, "lines": self.lines[-25:],
                    "elapsed": round(end - self.started) if self.started else 0,
                    "stories": self.stories, "error": self.error}


JOB = Job()
NOISE = re.compile(r"warn|NotOpenSSL", re.IGNORECASE)


def python_for_scripts():
    venv = ROOT / ".venv" / ("Scripts/python.exe" if sys.platform == "win32" else "bin/python")
    return str(venv) if venv.exists() else sys.executable


def start_job(version):
    cfg = VERSIONS[version]
    with JOB.lock:
        if JOB.state == "running":
            raise RuntimeError("Вестник вече се прави. Изчакай да свърши.")
        JOB.state, JOB.version, JOB.lines = "running", version, []
        JOB.started, JOB.finished, JOB.stories, JOB.error = time.time(), None, None, None
    # --no-desktop: приложението не пипа копието на Desktop (то е за графика в 06:00)
    cmd = [python_for_scripts(), "-u", str(cfg["script"]), "--no-desktop"]
    try:
        proc = subprocess.Popen(cmd, cwd=str(cfg["cwd"]), stdin=subprocess.DEVNULL,
                                stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True,
                                encoding="utf-8", errors="replace", bufsize=1,
                                env=dict(os.environ, PYTHONIOENCODING="utf-8"))
    except OSError as e:
        with JOB.lock:
            JOB.state, JOB.error, JOB.finished = "error", "Не мога да пусна програмата: {}".format(e), time.time()
        return
    threading.Thread(target=watch, args=(proc, version, JOB.started), daemon=True).start()


def watch(proc, version, started):
    for raw in proc.stdout:
        line = raw.rstrip()
        if not line or NOISE.search(line):
            continue
        with JOB.lock:
            JOB.lines.append(line[:300])
            m = re.search(r"\((\d+) истори", line)
            if m:
                JOB.stories = int(m.group(1))
    code = proc.wait()
    result = VERSIONS[version]["result"]
    fresh = result.exists() and result.stat().st_mtime >= started - 2
    with JOB.lock:
        JOB.finished = time.time()
        if code == 0 and fresh:
            JOB.state = "done"
        else:
            JOB.state = "error"
            problems = [l for l in JOB.lines if "ERROR" in l or "Грешка" in l or "Error" in l]
            JOB.error = (problems or JOB.lines or ["Програмата завърши без документ."])[-1]


def last_issues():
    out = {}
    for version, cfg in VERSIONS.items():
        path = cfg["result"]
        if path.exists():
            out[version] = {"mtime": int(path.stat().st_mtime), "size": path.stat().st_size}
    return out


# ---------- HTTP ----------

class Handler(BaseHTTPRequestHandler):
    server_version = "VestnikApp/1.0"

    def log_message(self, fmt, *args):   # без шум в терминала
        pass

    # --- помощни ---
    def reply(self, status, body, content_type="application/json; charset=utf-8", headers=None):
        if isinstance(body, (dict, list)):
            body = json.dumps(body, ensure_ascii=False).encode("utf-8")
        elif isinstance(body, str):
            body = body.encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        for k, v in (headers or {}).items():
            self.send_header(k, v)
        self.end_headers()
        self.wfile.write(body)

    def error(self, status, message):
        self.reply(status, {"error": message})

    def guard(self, query, post=False):
        """Само от тази страница: проверка на Host, Origin и таен ключ (срещу други сайтове)."""
        srv = self.server
        if self.headers.get("Host", "") not in srv.hosts:
            self.error(403, "Грешен адрес.")
            return False
        if post and self.headers.get("Origin") not in (None, *srv.origins):
            self.error(403, "Грешен произход на заявката.")
            return False
        token = self.headers.get("X-Token") or query.get("t", [""])[0]
        if not secrets.compare_digest(token, srv.token):
            self.error(403, "Липсва ключ — презареди страницата.")
            return False
        return True

    def body_json(self):
        length = int(self.headers.get("Content-Length") or 0)
        if length > 100_000:
            raise ValueError("Заявката е твърде голяма.")
        return json.loads(self.rfile.read(length) or b"{}")

    # --- GET ---
    def do_GET(self):
        url = urllib.parse.urlparse(self.path)
        query = urllib.parse.parse_qs(url.query)
        route = url.path
        if route == "/":
            if self.headers.get("Host", "") not in self.server.hosts:
                return self.error(403, "Грешен адрес.")
            page = INDEX.read_text(encoding="utf-8").replace("__TOKEN__", self.server.token)
            return self.reply(200, page, "text/html; charset=utf-8")
        if not self.guard(query):
            return
        if route == "/api/state":
            return self.state()
        if route == "/api/status":
            return self.reply(200, JOB.snapshot())
        if route == "/api/schedule":
            return self.reply(200, {"supported": platform_support.schedule_supported(),
                                    "enabled": platform_support.schedule_enabled()})
        if route == "/api/geocode":
            name = query.get("q", [""])[0].strip()
            if len(name) < 2:
                return self.reply(200, [])
            try:
                return self.reply(200, geocode(name))
            except Exception as e:
                return self.error(502, "Не мога да търся града: {}".format(e))
        m = re.fullmatch(r"/file/(claude|lite)\.docx", route)
        if m:
            cfg = VERSIONS[m.group(1)]
            if not cfg["result"].exists():
                return self.error(404, "Още няма такъв документ.")
            quoted = urllib.parse.quote(cfg["download"])
            return self.reply(200, cfg["result"].read_bytes(),
                              "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
                              {"Content-Disposition": "attachment; filename*=UTF-8''" + quoted})
        self.error(404, "Няма такава страница.")

    def state(self):
        catalog = load_catalog()
        topics = [{"id": t["id"], "name": t["name"], "about": t.get("about", ""),
                   "hours_back": t.get("hours_back")} for t in catalog["topics"]]
        ids = [t["id"] for t in topics]
        presets = [{"name": p["name"],
                    "topics": ids if p["topics"] == "*" else [t for t in p["topics"] if t in ids]}
                   for p in PRESETS]
        self.reply(200, {"topics": topics, "presets": presets, "profile": load_profile(ids),
                         "last": last_issues(), "can_open": platform_support.supported(),
                         "today": time.strftime("%Y-%m-%d")})

    # --- POST ---
    def do_POST(self):
        url = urllib.parse.urlparse(self.path)
        if not self.guard(urllib.parse.parse_qs(url.query), post=True):
            return
        try:
            data = self.body_json()
        except (ValueError, json.JSONDecodeError) as e:
            return self.error(400, "Невалидна заявка: {}".format(e))
        ids = [t["id"] for t in load_catalog()["topics"]]
        try:
            if url.path in ("/api/profile", "/api/run"):
                profile = validate_profile(data, ids)
                save_profile(profile)
                if url.path == "/api/run":
                    start_job(profile["version"])
                return self.reply(200, {"ok": True, "profile": profile})
            if url.path == "/api/schedule":
                if not platform_support.schedule_supported():
                    return self.error(409, "Ежедневното пускане още не е готово за тази система.")
                on = bool(data.get("on"))
                if on:
                    save_profile(validate_profile(data.get("profile") or {}, ids))
                if not platform_support.schedule_set(on):
                    return self.error(500, "Не успях да {} графика.".format("включа" if on else "изключа"))
                return self.reply(200, {"supported": True, "enabled": platform_support.schedule_enabled()})
            if url.path == "/api/open":
                version = data.get("version")
                if version not in VERSIONS or not VERSIONS[version]["result"].exists():
                    return self.error(404, "Още няма такъв документ.")
                ok = platform_support.open_file(VERSIONS[version]["result"])
                return self.reply(200, {"ok": ok})
        except ValueError as e:
            return self.error(400, str(e))
        except RuntimeError as e:
            return self.error(409, str(e))
        self.error(404, "Няма такава страница.")


class App(ThreadingHTTPServer):
    daemon_threads = True


def make_server():
    for port in PORTS:
        try:
            srv = App(("127.0.0.1", port), Handler)
        except OSError:
            continue
        srv.token = secrets.token_urlsafe(24)
        srv.hosts = {"127.0.0.1:%d" % port, "localhost:%d" % port}
        srv.origins = {"http://" + h for h in srv.hosts}
        return srv, port
    sys.exit("Не намерих свободен порт между 8765 и 8785.")


def main():
    srv, port = make_server()
    url = "http://127.0.0.1:%d/" % port
    print("Сутрешен вестник — приложение: " + url)
    print("Спиране: Ctrl+C")
    if "--no-browser" not in sys.argv:
        threading.Timer(0.5, lambda: webbrowser.open(url)).start()
    try:
        srv.serve_forever()
    except KeyboardInterrupt:
        print("\nСпряно.")


if __name__ == "__main__":
    main()
