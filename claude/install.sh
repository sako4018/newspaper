#!/bin/bash
# Включва автоматичното пускане на „Сутрешен вестник“ всеки ден в 06:00.
#
# macOS не позволява на launchd да чете папката Desktop, затова launchd пуска
# малко приложение („Сутрешен вестник.app“), а то пуска run.sh. Първия път macOS
# пита дали приложението може да ползва Desktop — отговори „Allow“.
set -e

LABEL="com.sutreshen.vestnik"
DIR="$(cd "$(dirname "$0")" && pwd)"
APP="$HOME/Applications/Сутрешен вестник.app"
PLIST="$HOME/Library/LaunchAgents/$LABEL.plist"

chmod +x "$DIR/run.sh"
mkdir -p "$HOME/Applications" "$HOME/Library/LaunchAgents"
rm -rf "$APP"
osacompile -o "$APP" -e "do shell script quoted form of \"$DIR/run.sh\""

cat > "$PLIST" <<EOF
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
    <key>Label</key>
    <string>$LABEL</string>
    <key>ProgramArguments</key>
    <array>
        <string>/usr/bin/open</string>
        <string>-g</string>
        <string>$APP</string>
    </array>
    <!-- Всеки ден в 06:00. Ако Mac спи, се пуска при събуждане. -->
    <key>StartCalendarInterval</key>
    <dict>
        <key>Hour</key>
        <integer>6</integer>
        <key>Minute</key>
        <integer>0</integer>
    </dict>
    <!-- И при влизане в профила (ако Mac е бил изключен в 06:00). -->
    <key>RunAtLoad</key>
    <true/>
</dict>
</plist>
EOF

launchctl bootout "gui/$(id -u)/$LABEL" 2>/dev/null || true
launchctl bootstrap "gui/$(id -u)" "$PLIST"
echo "Готово: вестникът ще се прави всеки ден в 06:00."
