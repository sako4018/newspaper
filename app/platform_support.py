"""Единствената точка, през която програмите ползват функции, зависещи от системата.

Има реализации за macOS (platform_mac.py) и Windows (platform_windows.py). На друга система функциите не правят
нищо и връщат False, така че вестникът пак се прави, но без отваряне, известия и копие на Desktop.
"""

import shutil
import sys
import time
from pathlib import Path

if sys.platform == "darwin":
    import platform_mac as _impl
elif sys.platform == "win32":
    import platform_windows as _impl
else:
    _impl = None


def supported():
    return _impl is not None


def open_file(path):
    return bool(_impl and _impl.open_file(path))


def reveal_file(path):
    return bool(_impl and _impl.reveal_file(path))


def notify(message):
    if _impl:
        _impl.notify(message)


ARCHIVE_NAME = "Сутрешен вестник"   # папката на Desktop с всички броеве


def save_issue(src):
    """Пази всеки брой в Desktop/Сутрешен вестник/дд.мм.гггг чч.мм.docx (":" и "/" не може в име на файл).

    Нищо не се презаписва: втори брой в същата минута става „... (2).docx“.
    Връща пътя или None, ако няма Desktop.
    """
    if not _impl:
        return None
    desktop = Path(_impl.desktop_dir())
    if not desktop.is_dir():
        return None
    folder = desktop / ARCHIVE_NAME
    folder.mkdir(exist_ok=True)
    stem = time.strftime("%d.%m.%Y %H.%M", time.localtime(Path(src).stat().st_mtime))   # кога е направен броят
    dst, n = folder / (stem + ".docx"), 2
    while dst.exists():
        dst, n = folder / "{} ({}).docx".format(stem, n), n + 1
    shutil.copyfile(src, dst)
    return dst


def schedule_supported():
    return bool(_impl and hasattr(_impl, "schedule_enable"))


def schedule_enabled():
    return bool(schedule_supported() and _impl.schedule_enabled())


def schedule_time():
    """Часът на ежедневното пускане ("06:30"), ако системата позволява да се сменя; иначе None."""
    if not (schedule_supported() and hasattr(_impl, "schedule_time")):
        return None
    return _impl.schedule_time()


def schedule_set(on):
    """Включва или изключва ежедневното пускане. Връща True при успех."""
    if not schedule_supported():
        return False
    return bool(_impl.schedule_enable() if on else _impl.schedule_disable())
