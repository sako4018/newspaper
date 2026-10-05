#!/bin/bash
# Печата готовия вестник на принтера по подразбиране. Вика се от run.sh, ако в профила е print: true.
# lp печата PDF, а не .docx, затова документът минава през HTML (textutil) и PDF (Chrome без прозорец).
# Пример: ./print.sh latest.docx
cd "$(dirname "$0")" || exit 1
mkdir -p logs
DOCX="$1"
TODAY=$(date +%Y-%m-%d)
STAMP="logs/printed-$TODAY"
CHROME="/Applications/Google Chrome.app/Contents/MacOS/Google Chrome"

log() {
    echo "$(date '+%Y-%m-%d %H:%M:%S') print.sh: $*"
}

if [ -f "$STAMP" ]; then
    log "днешният брой вече е отпечатан"
    exit 0
fi
if [ ! -f "$DOCX" ]; then
    log "няма файл $DOCX"
    exit 1
fi
if [ "$(date -r "$DOCX" +%Y-%m-%d)" != "$TODAY" ]; then
    log "файлът не е от днес, не печатам"
    exit 1
fi
if [ ! -x "$CHROME" ]; then
    log "няма Google Chrome, а без него не мога да направя PDF"
    exit 1
fi

TMP=$(mktemp -d)
textutil -convert html -output "$TMP/vestnik.html" "$DOCX" || { log "textutil не успя"; exit 1; }
"$CHROME" --headless --disable-gpu --no-pdf-header-footer --print-to-pdf-no-header \
    --print-to-pdf="$TMP/vestnik.pdf" "file://$TMP/vestnik.html" 2>/dev/null
if [ ! -s "$TMP/vestnik.pdf" ]; then
    log "Chrome не направи PDF"
    exit 1
fi
# PRINT_PDF_ONLY=1 само прави PDF-а и показва къде е (за проверка без принтер)
if [ -n "$PRINT_PDF_ONLY" ]; then
    log "PDF: $TMP/vestnik.pdf"
    exit 0
fi
if ! lpstat -d 2>/dev/null | grep -q "destination:"; then
    log "няма принтер по подразбиране (System Settings → Printers & Scanners)"
    exit 1
fi
if lp -o media=A4 "$TMP/vestnik.pdf"; then
    touch "$STAMP"
    log "изпратено към принтера"
else
    log "lp не успя"
    exit 1
fi
