#!/bin/bash
# Пуска вестника в автоматичен режим. Извиква се от „Сутрешен вестник.app“.
cd "$(dirname "$0")" || exit 1
export PATH="$HOME/.local/bin:/usr/local/bin:/opt/homebrew/bin:/usr/bin:/bin"
exec ../.venv/bin/python vestnik.py --auto
