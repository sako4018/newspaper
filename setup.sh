#!/bin/bash
# Първоначална настройка за Mac. Цялата работа е в setup.py (той върви и на Windows).
cd "$(dirname "$0")" || exit 1
if ! command -v python3 >/dev/null 2>&1; then
    echo "Няма python3. Инсталирай Python 3.9 или по-нов от python.org и пусни ./setup.sh пак." >&2
    exit 1
fi
exec python3 setup.py "$@"
