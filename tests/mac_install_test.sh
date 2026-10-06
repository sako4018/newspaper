#!/bin/bash
# Проверка на инсталатора за Mac от zip до готов брой, както при човек:
#   tests/mac_install_test.sh <Sutreshen-Vestnik.zip> <lite|claude>
# 1. разархивира (ditto, като Safari) и проверява .app: две архитектури, подпис, версия;
# 2. тихо инсталиране (Installer --silent), проверка на файлове, профил, launchd, иконки;
# 3. чака графика (launchd пуска веднага при инсталиране) да направи брой и да го сложи в Desktop/Сутрешен вестник;
# 4. пуска съветника пак без аргументи (смяна на настройки) и гледа, че изборът е запазен;
# 5. деинсталира и проверява, че няма следи.
# За claude слага фалшив claude (tests/fake_claude.py) в ~/.local/bin, защото в GitHub няма вход в Claude.
# Само за машини за проверка: пипа launchd и ~/Library. Не го пускай на собствения си Mac.
set -u
ZIP="$1"
VERSION="$2"
HERE="$(cd "$(dirname "$0")" && pwd)"
NAME="Инсталирай Сутрешен вестник"
INST="$HOME/Library/Application Support/Сутрешен вестник"
PLIST="$HOME/Library/LaunchAgents/com.sutreshen.vestnik.plist"
SETTINGS="$HOME/Applications/Сутрешен вестник – настройки.app"
ALIAS="$HOME/Desktop/Сутрешен вестник – настройки"
ARCHIVE="$HOME/Desktop/Сутрешен вестник"
TAG="[mac $VERSION]"

fail() { echo "::error::$TAG $*"; exit 1; }
note() { echo "::notice::$TAG $*"; }

# ---- 1. zip ----
WORK=$(mktemp -d)
ditto -x -k "$ZIP" "$WORK" || fail "zip-ът не се разархивира"
APP="$WORK/$NAME.app"
BIN="$APP/Contents/MacOS/Installer"
[ -x "$BIN" ] || fail "в zip-а няма $NAME.app"
ARCHS=$(lipo -archs "$BIN")
case "$ARCHS" in *arm64*x86_64*|*x86_64*arm64*) ;; *) fail "съветникът е само за $ARCHS" ;; esac
codesign --verify --deep "$APP" || fail "подписът на .app е счупен"
APPVER=$(/usr/libexec/PlistBuddy -c "Print :CFBundleShortVersionString" "$APP/Contents/Info.plist")
note "zip: $(du -h "$ZIP" | cut -f1), версия $APPVER, $ARCHS"

# ---- фалшив claude ----
if [ "$VERSION" = claude ]; then
    mkdir -p "$HOME/.local/bin"
    printf '#!/bin/sh\nexec /usr/bin/python3 "%s/fake_claude.py" "$@"\n' "$HERE" > "$HOME/.local/bin/claude"
    chmod +x "$HOME/.local/bin/claude"
fi

# ---- 2. инсталиране ----
START=$(date +%s)
"$BIN" --silent --version "$VERSION" --topics bg,world --city Пловдив --time 06:30 --print 0 \
    || fail "тихото инсталиране върна грешка"
for f in ".venv/bin/python" "lite/profile.yaml" "claude/run.sh" "app/apply_settings.py"; do
    [ -e "$INST/$f" ] || fail "липсва $f в Application Support"
done
PROFILE=$(cat "$INST/lite/profile.yaml")
for want in "version: $VERSION" "- bg" "- world" "06:30" "Пловдив"; do
    grep -qF -- "$want" <<<"$PROFILE" || fail "профилът няма '$want'"
done
[ -f "$PLIST" ] || fail "няма LaunchAgent"
[ "$(/usr/libexec/PlistBuddy -c 'Print :StartCalendarInterval:Hour' "$PLIST")" = 6 ] || fail "графикът не е в 6 ч"
[ "$(/usr/libexec/PlistBuddy -c 'Print :StartCalendarInterval:Minute' "$PLIST")" = 30 ] || fail "графикът не е в :30"
launchctl print "gui/$(id -u)/com.sutreshen.vestnik" >/dev/null 2>&1 || fail "launchd не познава задачата"
[ -d "$HOME/Applications/Сутрешен вестник.app" ] || fail "няма помощното приложение за графика"
[ -x "$SETTINGS/Contents/MacOS/Installer" ] || fail "няма „Сутрешен вестник – настройки“ в ~/Applications"
[ -e "$ALIAS" ] || fail "няма иконка на Desktop"
note "инсталирано за $(( $(date +%s) - START )) s: профил, launchd 06:30, помощно приложение, настройки, иконка на Desktop"

# ---- 3. брой от графика ----
if [ "$VERSION" = claude ]; then RESULT="$INST/claude/latest.docx"; else RESULT="$INST/lite/output/latest.docx"; fi
for i in $(seq 120); do   # до 20 минути (Lite тегли и модела за превод първия път)
    [ -f "$RESULT" ] && [ "$(stat -f %m "$RESULT")" -ge "$START" ] && break
    sleep 10
done
if [ -f "$RESULT" ] && [ "$(stat -f %m "$RESULT")" -ge "$START" ]; then
    note "графикът (launchd → помощното приложение → run.sh) направи брой: $(stat -f %z "$RESULT") байта"
else
    tail -20 "$INST/claude/logs/"*.log 2>/dev/null
    fail "графикът не направи брой за 20 минути"
fi
sleep 5
COPY=$(ls "$ARCHIVE" 2>/dev/null | grep -E '^[0-9]{2}\.[0-9]{2}\.[0-9]{4} [0-9]{2}\.[0-9]{2}( \([0-9]+\))?\.docx$' | head -1)
[ -n "$COPY" ] || { grep -h "Копие на Desktop" "$INST/claude/logs/"*.log 2>/dev/null | tail -3; fail "броят не е в Desktop/Сутрешен вестник"; }
note "копие на Desktop: Сутрешен вестник/$COPY"

# ---- 4. смяна на настройките (същият съветник, пуснат пак, без отговори) ----
"$SETTINGS/Contents/MacOS/Installer" --silent || fail "повторното пускане на съветника върна грешка"
PROFILE=$(cat "$INST/lite/profile.yaml")
for want in "version: $VERSION" "- bg" "- world" "06:30" "Пловдив"; do
    grep -qF -- "$want" <<<"$PROFILE" || fail "след повторно пускане профилът няма '$want'"
done
note "повторното пускане запази избора"

# ---- 5. деинсталиране ----
"$SETTINGS/Contents/MacOS/Installer" --silent --uninstall || fail "деинсталирането върна грешка"
sleep 2
[ ! -e "$INST" ] || fail "Application Support остана"
[ ! -e "$PLIST" ] || fail "LaunchAgent остана"
launchctl print "gui/$(id -u)/com.sutreshen.vestnik" >/dev/null 2>&1 && fail "launchd още има задачата"
[ ! -e "$SETTINGS" ] || fail "приложението за настройки остана"
[ ! -e "$ALIAS" ] || fail "иконката на Desktop остана"
[ -d "$ARCHIVE" ] || fail "папката с броевете трябва да остане"
note "деинсталирано; папката с броевете остана"
rm -rf "$ARCHIVE" "$WORK" "$HOME/.local/bin/claude"
echo "$TAG Всичко мина."
