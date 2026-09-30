#!/usr/bin/env bash
# quarto render（revealjs）→ Chrome headless で全スライドを 1280x720 の PNG にする。
# 出力: <deck>/_check/slide-NN.png（Read で全枚を目視する）
# 使い方: render_check.sh decks/<name>      （index.qmd を含むフォルダ、または .qmd のパス）
set -euo pipefail

ROOT="$(git -C "$(dirname "$0")" rev-parse --show-toplevel 2>/dev/null || (cd "$(dirname "$0")/../../../.." && pwd))"
TARGET="${1:?usage: render_check.sh decks/<name>}"
[[ -d "$TARGET" ]] && TARGET="$TARGET/index.qmd"
[[ -f "$TARGET" ]] || { echo "not found: $TARGET" >&2; exit 1; }
QMD="$(cd "$(dirname "$TARGET")" && pwd)/$(basename "$TARGET")"
DECK_DIR="$(dirname "$QMD")"
REL="${QMD#"$ROOT"/}"
HTML="$ROOT/_output/${REL%.qmd}.html"
OUT="$DECK_DIR/_check"

PY="$ROOT/.venv/bin/python"
[[ -x "$PY" ]] || { echo ".venv がない: uv venv .venv && uv pip install --python .venv/bin/python -r requirements.txt" >&2; exit 1; }
export QUARTO_PYTHON="$PY"

CHROME="${CHROME:-}"
if [[ -z "$CHROME" ]]; then
  for c in "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome" \
           "/Applications/Chromium.app/Contents/MacOS/Chromium" \
           "$(command -v google-chrome || true)" "$(command -v chromium || true)"; do
    [[ -n "$c" && -x "$c" ]] && CHROME="$c" && break
  done
fi
[[ -n "$CHROME" ]] || { echo "Chrome が見つからない（CHROME=... で指定）" >&2; exit 1; }

(cd "$ROOT" && quarto render "$REL" --to revealjs --quiet)
[[ -f "$HTML" ]] || { echo "HTML が出力されていない: $HTML" >&2; exit 1; }

rm -rf "$OUT" && mkdir -p "$OUT"
# スライド数 = タイトルスライド + 各 section.slide（縦スタックは使わない前提）
N=$(grep -oE '<section[^>]*class="[^"]*(quarto-title-block|slide level)' "$HTML" | wc -l | tr -d ' ')
[[ "$N" -gt 0 ]] || { echo "スライドが見つからない" >&2; exit 1; }
for ((i = 0; i < N; i++)); do
  "$CHROME" --headless=new --disable-gpu --hide-scrollbars --window-size=1280,720 \
    --run-all-compositor-stages-before-draw --virtual-time-budget=8000 \
    --screenshot="$OUT/slide-$(printf %02d $((i + 1))).png" "file://$HTML#/$i" >/dev/null 2>&1 &
  # 並列は4本まで
  (( (i + 1) % 4 == 0 )) && wait
done
wait
echo "$N slides -> $OUT"
ls "$OUT"/slide-*.png
