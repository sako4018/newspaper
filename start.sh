#!/bin/bash
# Пуска приложението за избор на версия, теми и град и отваря страницата в браузъра.
# Ако средата още не е подготвена, пуска setup.sh (той после вика пак start.sh).
cd "$(dirname "$0")" || exit 1
if [ ! -x .venv/bin/python ] || ! .venv/bin/python -c "import yaml, feedparser, docx" 2>/dev/null; then
    exec ./setup.sh
fi
exec .venv/bin/python app/server.py "$@"
