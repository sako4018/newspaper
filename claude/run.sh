#!/bin/bash
# Пуска вестника в автоматичен режим. Извиква се от „Сутрешен вестник.app“.
# Пуска само версията от профила (lite/profile.yaml, ключ version: claude или lite).
# Ако няма профил или ключ, пуска Lite. Темите също се четат от профила.
cd "$(dirname "$0")" || exit 1
export PATH="$HOME/.local/bin:/usr/local/bin:/opt/homebrew/bin:/usr/bin:/bin"
mkdir -p logs
PY=../.venv/bin/python
PROFILE=../lite/profile.yaml
VERSION=$(sed -n 's/^version:[[:space:]]*//p' "$PROFILE" 2>/dev/null | head -n 1 | tr -d "\"' \r")
# Запис при всяко пускане, за да се вижда, че графикът е сработил и коя версия е избрана.
echo "$(date '+%Y-%m-%d %H:%M:%S') run.sh: версия ${VERSION:-lite}" >> logs/schedule.log
# VESTNIK_DRY_RUN=1 само показва какво би пуснало (за проверка)
if [ -n "$VESTNIK_DRY_RUN" ]; then
    echo "версия: ${VERSION:-lite (по подразбиране)}"
    exit 0
fi
# caffeinate -i не позволява на Mac-а да заспи, докато върви скриптът.
if [ "$VERSION" = "claude" ]; then
    caffeinate -i $PY vestnik.py --auto
    CODE=$?
    RESULT=latest.docx
else
    caffeinate -i $PY ../lite/lite.py --auto >> logs/lite.log 2>&1
    CODE=$?
    RESULT=../lite/output/latest.docx
fi
# Печат само ако е включен в профила (print: true) и броят е направен успешно.
PRINT=$(sed -n 's/^print:[[:space:]]*//p' "$PROFILE" 2>/dev/null | head -n 1 | tr -d "\"' \r")
if [ "$CODE" -eq 0 ] && [ "$PRINT" = "true" ]; then
    ./print.sh "$RESULT" >> logs/print.log 2>&1
fi
exit $CODE
