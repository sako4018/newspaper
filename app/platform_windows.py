"""Всичко, което е специфично за Windows: отваряне на файл, известия, папката Desktop и график.

Графикът е задача в Task Scheduler. Не е пробван на истински Windows.
"""

import os
import re
import subprocess
import sys
from pathlib import Path

_ROOT = Path(__file__).resolve().parent.parent
TASK = "Sutreshen Vestnik"
_NO_WINDOW = getattr(subprocess, "CREATE_NO_WINDOW", 0)


def _powershell(command):
    return subprocess.run(["powershell", "-NoProfile", "-NonInteractive", "-Command", command],
                          capture_output=True, creationflags=_NO_WINDOW)


def _q(text):
    """Текст в единични кавички за PowerShell."""
    return "'" + str(text).replace("'", "''") + "'"


def open_file(path):
    try:
        os.startfile(str(path))
        return True
    except OSError:
        return False


def reveal_file(path):
    return subprocess.run(["explorer", "/select,", str(path)]).returncode in (0, 1)


def notify(message, title="Сутрешен вестник"):
    """Балонче в областта за известия."""
    script = (
        "Add-Type -AssemblyName System.Windows.Forms,System.Drawing;"
        "$n = New-Object System.Windows.Forms.NotifyIcon;"
        "$n.Icon = [System.Drawing.SystemIcons]::Information; $n.Visible = $true;"
        "$n.ShowBalloonTip(5000, {t}, {m}, 'Info'); Start-Sleep -Seconds 6; $n.Dispose()"
    ).format(t=_q(title), m=_q(message))
    try:
        subprocess.Popen(["powershell", "-NoProfile", "-WindowStyle", "Hidden", "-Command", script],
                         creationflags=_NO_WINDOW)
    except OSError:
        pass


def desktop_dir():
    """Desktop, включително когато OneDrive го е пренасочил."""
    home = Path.home()
    for candidate in (home / "Desktop", home / "OneDrive" / "Desktop"):
        if candidate.is_dir():
            return candidate
    return home / "Desktop"


# ---- график „всяка сутрин“ (Task Scheduler) ----
def schedule_enabled():
    return _powershell("Get-ScheduledTask -TaskName {} -ErrorAction Stop".format(_q(TASK))).returncode == 0


def schedule_time():
    return _schedule_time()


def _schedule_time():
    """Часът от профила (schedule_time: "06:30"); ако го няма, 06:00."""
    try:
        text = (_ROOT / "lite" / "profile.yaml").read_text(encoding="utf-8")
    except OSError:
        return "06:00"
    m = re.search(r"^schedule_time:\s*[\"']?(\d{1,2}):(\d{2})", text, re.MULTILINE)
    if not m or int(m.group(1)) > 23 or int(m.group(2)) > 59:
        return "06:00"
    return "{:02d}:{:02d}".format(int(m.group(1)), int(m.group(2)))


def schedule_enable():
    """Задача всеки ден в часа от профила; ако компютърът е бил изключен, се пуска при включване."""
    venv_python = _ROOT / ".venv" / "Scripts" / "python.exe"
    python = venv_python if venv_python.exists() else Path(sys.executable)
    windowless = python.with_name("pythonw.exe")      # без черен прозорец
    if windowless.exists():
        python = windowless
    run_py = _ROOT / "claude" / "run.py"
    script = (
        "$a = New-ScheduledTaskAction -Execute {py} -Argument {arg} -WorkingDirectory {wd};"
        "$t = New-ScheduledTaskTrigger -Daily -At {at};"
        "$s = New-ScheduledTaskSettingsSet -StartWhenAvailable -AllowStartIfOnBatteries;"
        "Register-ScheduledTask -TaskName {name} -Action $a -Trigger $t -Settings $s -Force | Out-Null"
    ).format(py=_q(python), arg=_q('"{}"'.format(run_py)), wd=_q(run_py.parent), name=_q(TASK),
             at=_q(_schedule_time()))
    return _powershell(script).returncode == 0


def schedule_disable():
    return _powershell("Unregister-ScheduledTask -TaskName {} -Confirm:$false -ErrorAction Stop"
                       .format(_q(TASK))).returncode == 0
