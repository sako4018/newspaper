#!/bin/bash
# Прави инсталатора: dist/Sutreshen-Vestnik.zip с „Инсталирай Сутрешен вестник.app“ вътре.
# Пуска се от Mac с инсталирани инструменти за команден ред (swiftc) и готова .venv (за topics.json).
#   installer/build.sh
set -e
cd "$(dirname "$0")/.."

NAME="Инсталирай Сутрешен вестник"
APP="dist/$NAME.app"
RES="$APP/Contents/Resources"
TMP=$(mktemp -d)

rm -rf dist
mkdir -p "$APP/Contents/MacOS" "$RES/payload"

echo "1/5 Копирам програмата на вестника (само файловете от git)..."
git ls-files -z -- app claude lite setup.py setup.sh start.sh README.md \
    | tar --null -T - -cf - | tar -xf - -C "$RES/payload"

echo "2/5 Списък с темите (topics.json)..."
.venv/bin/python - "$RES/topics.json" <<'EOF'
import json, sys, yaml
with open("lite/catalog.yaml", encoding="utf-8") as f:
    catalog = yaml.safe_load(f)
topics = [{"id": t["id"], "name": t["name"], "about": t.get("about", "")} for t in catalog["topics"]]
with open(sys.argv[1], "w", encoding="utf-8") as f:
    json.dump(topics, f, ensure_ascii=False)
EOF

echo "3/5 Компилирам съветника (Apple Silicon и Intel)..."
# Новото SDK понякога е по-ново от компилатора, затова се пробват всички, от най-новото надолу.
for SDK in $(ls -d /Library/Developer/CommandLineTools/SDKs/MacOSX[0-9]*.*.sdk 2>/dev/null | sort -rV); do
    if swiftc -O -sdk "$SDK" -target arm64-apple-macos12 -o "$TMP/arm64" installer/Wizard.swift 2>"$TMP/err"; then
        break
    fi
    SDK=""
done
if [ -z "$SDK" ]; then
    cat "$TMP/err" >&2
    echo "Не успях да компилирам съветника с нито едно SDK." >&2
    exit 1
fi
echo "    SDK: $(basename "$SDK")"
swiftc -O -sdk "$SDK" -target x86_64-apple-macos12 -o "$TMP/x86_64" installer/Wizard.swift
lipo -create "$TMP/arm64" "$TMP/x86_64" -output "$APP/Contents/MacOS/Installer"

echo "4/5 Икона и Info.plist..."
SDKROOT="$SDK" swift installer/make_icon.swift "$TMP/icon.png"
mkdir -p "$TMP/AppIcon.iconset"
for s in 16 32 128 256 512; do
    sips -z $s $s "$TMP/icon.png" --out "$TMP/AppIcon.iconset/icon_${s}x${s}.png" >/dev/null
    sips -z $((s * 2)) $((s * 2)) "$TMP/icon.png" --out "$TMP/AppIcon.iconset/icon_${s}x${s}@2x.png" >/dev/null
done
iconutil -c icns "$TMP/AppIcon.iconset" -o "$RES/AppIcon.icns"
cat > "$APP/Contents/Info.plist" <<EOF
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
    <key>CFBundleName</key>
    <string>$NAME</string>
    <key>CFBundleDisplayName</key>
    <string>$NAME</string>
    <key>CFBundleIdentifier</key>
    <string>com.sutreshen.vestnik.installer</string>
    <key>CFBundleExecutable</key>
    <string>Installer</string>
    <key>CFBundleIconFile</key>
    <string>AppIcon</string>
    <key>CFBundlePackageType</key>
    <string>APPL</string>
    <key>CFBundleShortVersionString</key>
    <string>1.0</string>
    <key>CFBundleVersion</key>
    <string>1</string>
    <key>LSMinimumSystemVersion</key>
    <string>12.0</string>
    <key>NSHighResolutionCapable</key>
    <true/>
</dict>
</plist>
EOF

echo "5/5 Подпис (без Apple акаунт) и zip..."
codesign --force --deep -s - "$APP"
(cd dist && ditto -c -k --sequesterRsrc --keepParent "$NAME.app" Sutreshen-Vestnik.zip)
rm -rf "$TMP"
echo "Готово: dist/Sutreshen-Vestnik.zip ($(du -h dist/Sutreshen-Vestnik.zip | cut -f1))"
