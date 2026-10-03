#!/bin/bash
# Спира автоматичното пускане на „Сутрешен вестник“. Файловете и старите броеве остават.

LABEL="com.sutreshen.vestnik"
launchctl bootout "gui/$(id -u)/$LABEL" 2>/dev/null || true
rm -f "$HOME/Library/LaunchAgents/$LABEL.plist"
rm -rf "$HOME/Applications/Сутрешен вестник.app"
echo "Автоматичното пускане е спряно."
