#!/bin/bash
# Пуска вестниците в автоматичен режим. Извиква се от „Сутрешен вестник.app“.
# Първо Lite (бърз е), после Claude. Ако Lite се провали, Claude пак се пуска.
cd "$(dirname "$0")" || exit 1
export PATH="$HOME/.local/bin:/usr/local/bin:/opt/homebrew/bin:/usr/bin:/bin"
mkdir -p logs
../.venv/bin/python ../lite/lite.py --auto >> logs/lite.log 2>&1
exec ../.venv/bin/python vestnik.py --auto
