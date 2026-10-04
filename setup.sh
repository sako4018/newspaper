#!/bin/bash
# Първоначална настройка: подготвя .venv с всичко нужно и отваря страницата за избор.
# Пуска се веднъж след изтегляне на репото: ./setup.sh
cd "$(dirname "$0")" || exit 1

if ! command -v python3 >/dev/null 2>&1; then
    echo "Няма python3. Инсталирай Python 3.9 или по-нов от python.org и пусни ./setup.sh пак." >&2
    exit 1
fi
if ! python3 -c 'import sys; sys.exit(0 if sys.version_info >= (3, 9) else 1)'; then
    echo "Python е твърде стар ($(python3 --version)). Нужен е 3.9 или по-нов." >&2
    exit 1
fi

if [ ! -x .venv/bin/python ]; then
    echo "Създавам виртуална среда (.venv)..."
    python3 -m venv .venv || exit 1
fi
echo "Инсталирам нужните пакети (при първо пускане отнема няколко минути)..."
.venv/bin/pip install -q --upgrade pip
.venv/bin/pip install -q -r claude/requirements.txt -r lite/requirements.txt || {
    echo "Инсталацията на пакетите не успя. Провери интернет връзката и пусни ./setup.sh пак." >&2
    exit 1
}

if ! command -v claude >/dev/null 2>&1 && [ ! -x "$HOME/.local/bin/claude" ]; then
    echo "Забележка: няма команда claude (Claude Code). Тя е нужна само за версията „Claude“;"
    echo "версията „Lite“ работи и без нея."
fi

echo "Готово. Отварям страницата за избор на версия и теми..."
exec .venv/bin/python app/server.py "$@"
