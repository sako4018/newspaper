#!/bin/bash
# Пуска приложението за избор на теми и отваря страницата в браузъра.
# Подготвя .venv, ако още няма (нужен е само PyYAML за самото приложение).
cd "$(dirname "$0")" || exit 1
if [ ! -x .venv/bin/python ]; then
    python3 -m venv .venv || exit 1
fi
.venv/bin/python -c "import yaml" 2>/dev/null || .venv/bin/pip install -q pyyaml || exit 1
exec .venv/bin/python app/server.py "$@"
