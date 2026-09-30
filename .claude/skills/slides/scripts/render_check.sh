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

# imgfig の図ごとの大きさは、セルの実行時に IMGFIG_REPORT へ書き出される。
# セルが再実行されなかったとき（freeze で変更なし）は、前回の記録をそのまま使う。
REPORT="$OUT/imgfig.jsonl"
PREV="$(cat "$REPORT" 2>/dev/null || true)"
NEW="$(mktemp)"
(cd "$ROOT" && IMGFIG_REPORT="$NEW" quarto render "$REL" --to revealjs --quiet)
[[ -f "$HTML" ]] || { echo "HTML が出力されていない: $HTML" >&2; exit 1; }

rm -rf "$OUT" && mkdir -p "$OUT"
if [[ -s "$NEW" ]]; then cp "$NEW" "$REPORT"; elif [[ -n "$PREV" ]]; then printf '%s\n' "$PREV" > "$REPORT"; fi
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

# 画像を並べた図（imgfig）の、スライド上での1枚の大きさの目安
if [[ -s "$REPORT" ]]; then
  "$PY" - "$REPORT" <<'PYEOF'
import json, sys
rows = [json.loads(line) for line in open(sys.argv[1], encoding="utf-8") if line.strip()]
rows = [r for r in rows if r.get("thumbs")]
if rows:
    print("画像の図: スライド上での1枚の大きさの目安（150px 以上が見やすい。100px 未満は何が写っているかが読めない）")
for n, r in enumerate(rows, 1):
    size = f"約{r['px']}px" if r["px"] == r["px_tall"] else f"約{r['px']}px（bullets を置かなければ約{r['px_tall']}px）"
    note = ""
    if r["px_tall"] < 100:
        note = "  ← 小さい: 見せる枚数を減らす（pick）か、図を分ける。全数は appendix に回せる"
    elif r["px"] < 100:
        note = "  ← bullets を置くと小さい: bullets を減らすか、見せる枚数を減らす"
    print(f"  図{n}: {r['thumbs']}枚 {size}{note}")
PYEOF
fi

# 図の写真ごとの説明・群の見出しを、確認の表（data/look.csv: id, classes, note）と照らす
if [[ -s "$REPORT" && -f "$DECK_DIR/data/look.csv" ]]; then
  "$PY" "$(dirname "$0")/imgfig.py" check-look --report "$REPORT" --look "$DECK_DIR/data/look.csv"
elif [[ -s "$REPORT" ]] && grep -q '"captions": \[{' "$REPORT"; then
  echo "WARNING 写真の図があるが data/look.csv が無い（元の写真で確かめた、写っている対象の表を作る）"
fi

# 図のファイルサイズ（公開ページの重さ）。写真を並べた図は PNG だと1枚1MBを超える
FIG_DIR="${HTML%.html}_files/figure-revealjs"
if [[ -d "$FIG_DIR" ]]; then
  echo "figures: $(du -sk "$FIG_DIR" | cut -f1) KB"
  find "$FIG_DIR" -type f -size +1024k | while read -r f; do
    echo "WARNING 図が1MBを超える: $(basename "$f")（写真の図はデッキの YAML に fig-format: jpeg と fig-dpi: 200 を書く）"
  done
fi
