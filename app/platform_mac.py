"""Всичко, което е специфично за macOS: отваряне на файл, известия, папката Desktop.

За Linux се добавя подобен файл (xdg-open, notify-send, XDG_DESKTOP_DIR) и се включва
в platform_support.py.
"""

import subprocess
from pathlib import Path


def open_file(path):
    """Отваря файла с приложението по подразбиране (Word)."""
    return subprocess.run(["open", str(path)], capture_output=True).returncode == 0


def reveal_file(path):
    """Показва файла във Finder."""
    return subprocess.run(["open", "-R", str(path)], capture_output=True).returncode == 0


def notify(message, title="Сутрешен вестник"):
    """Малко известие в ъгъла на екрана."""
    script = 'display notification "{}" with title "{}"'.format(
        message.replace('"', "'"), title.replace('"', "'"))
    subprocess.run(["osascript", "-e", script], capture_output=True)


def desktop_dir():
    return Path.home() / "Desktop"
