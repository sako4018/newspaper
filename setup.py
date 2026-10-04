#!/usr/bin/env python3
"""Първоначална настройка за macOS и Windows: подготвя .venv и отваря страницата за избор.

Mac:      python3 setup.py
Windows:  py setup.py
Системата се познава сама. Пуска се веднъж след изтегляне на репото; ако средата вече е
готова, инсталацията се прескача и само се отваря страницата.
"""

import os
import shutil
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent
VENV = ROOT / ".venv"
WINDOWS = sys.platform == "win32"
VENV_PYTHON = VENV / ("Scripts/python.exe" if WINDOWS else "bin/python")


def fail(message):
    print(message, file=sys.stderr)
    sys.exit(1)


def env_ready():
    if not VENV_PYTHON.exists():
        return False
    check = [str(VENV_PYTHON), "-c", "import yaml, feedparser, docx"]
    return subprocess.run(check, capture_output=True).returncode == 0


def main():
    if sys.version_info < (3, 9):
        fail("Python е твърде стар ({}). Нужен е 3.9 или по-нов.".format(sys.version.split()[0]))

    if not env_ready():
        if not VENV_PYTHON.exists():
            print("Създавам виртуална среда (.venv)...")
            if subprocess.call([sys.executable, "-m", "venv", str(VENV)]) != 0:
                fail("Не успях да направя .venv.")
        print("Инсталирам нужните пакети (при първо пускане отнема няколко минути)...")
        pip = [str(VENV_PYTHON), "-m", "pip", "install", "-q"]
        subprocess.call(pip + ["--upgrade", "pip"])
        reqs = ["-r", str(ROOT / "claude" / "requirements.txt"),
                "-r", str(ROOT / "lite" / "requirements.txt")]
        if subprocess.call(pip + reqs) != 0:
            fail("Инсталацията на пакетите не успя. Провери интернет връзката и пусни setup.py пак.")

    if not shutil.which("claude") and not (Path.home() / ".local" / "bin" / "claude").exists():
        print("Забележка: няма команда claude (Claude Code). Тя е нужна само за версията „Claude“;")
        print("версията „Lite“ работи и без нея.")

    print("Готово. Отварям страницата за избор на версия и теми...")
    sys.exit(subprocess.call([str(VENV_PYTHON), str(ROOT / "app" / "server.py")] + sys.argv[1:]))


if __name__ == "__main__":
    main()
