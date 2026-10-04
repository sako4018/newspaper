"""Пуска вестника в автоматичен режим (за Windows; на Mac това прави run.sh).

Чете версията от lite/profile.yaml (ключ version: claude или lite; по подразбиране Lite),
записва ред в logs/schedule.log и пуска избраната версия с --auto.
Със VESTNIK_DRY_RUN=1 само показва какво би пуснало.
"""

import ctypes
import os
import re
import subprocess
import sys
import time
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parent
PROFILE = ROOT / "lite" / "profile.yaml"


def profile_version():
    try:
        text = PROFILE.read_text(encoding="utf-8")
    except OSError:
        return "lite"
    m = re.search(r"^version:\s*[\"']?(\w+)", text, re.MULTILINE)
    return m.group(1) if m else "lite"


def keep_awake():
    """Не позволява на компютъра да заспи, докато върви скриптът (като caffeinate)."""
    if sys.platform == "win32":
        ES_CONTINUOUS, ES_SYSTEM_REQUIRED = 0x80000000, 0x00000001
        ctypes.windll.kernel32.SetThreadExecutionState(ES_CONTINUOUS | ES_SYSTEM_REQUIRED)


def main():
    version = profile_version()
    logs = HERE / "logs"
    logs.mkdir(exist_ok=True)
    with open(logs / "schedule.log", "a", encoding="utf-8") as f:
        f.write("{} run.py: версия {}\n".format(time.strftime("%Y-%m-%d %H:%M:%S"), version))
    if os.environ.get("VESTNIK_DRY_RUN"):
        print("версия:", version)
        return 0

    keep_awake()
    py = sys.executable
    env = dict(os.environ, PYTHONIOENCODING="utf-8")
    if version == "claude":
        return subprocess.call([py, str(HERE / "vestnik.py"), "--auto"], cwd=str(HERE), env=env)
    with open(logs / "lite.log", "a", encoding="utf-8") as log:
        return subprocess.call([py, str(ROOT / "lite" / "lite.py"), "--auto"], cwd=str(HERE),
                               stdout=log, stderr=subprocess.STDOUT, env=env)


if __name__ == "__main__":
    sys.exit(main())
