#!/usr/bin/env bash
# quarto render（revealjs）→ Chrome headless で全スライドを 1280x720 の PNG にする。
# 出力: <deck>/_check/slide-NN.png（Read で全枚を目視する）
# 使い方: render_check.sh <deck>      （index.qmd を含むフォルダ、または .qmd のパス）
#
# デッキが Quarto プロジェクト（_quarto.yml を持つフォルダ）の中にあれば、そのプロジェクトで描画する。
# 外にあるときは、このスキルのリポジトリの _quarto.yml・theme・filters で一時プロジェクトを組んで描画し、
# 1つにまとめた HTML をデッキの隣に置く。どちらの経路でも見た目は同じになる。
set -euo pipefail

SKILL_DIR="$(cd -P "$(dirname "$0")/.." && pwd)"   # シンボリックリンク経由でも実体を指す
REPO="$(cd -P "$SKILL_DIR/../../.." && pwd)"       # <repo>/.claude/skills/slides の3つ上

TARGET="${1:?usage: render_check.sh <deck>}"
[[ -d "$TARGET" ]] && TARGET="$TARGET/index.qmd"
[[ -f "$TARGET" ]] || { echo "not found: $TARGET" >&2; exit 1; }
QMD="$(cd "$(dirname "$TARGET")" && pwd)/$(basename "$TARGET")"
DECK_DIR="$(dirname "$QMD")"
OUT="$DECK_DIR/_check"

# デッキを含む Quarto プロジェクトを上に辿って探す
PROJECT=""
d="$DECK_DIR"
while [[ "$d" != "/" ]]; do
  if [[ -f "$d/_quarto.yml" ]]; then PROJECT="$d"; break; fi
  d="$(dirname "$d")"
done

# Python: $SLIDES_PYTHON → プロジェクトの .venv → スキルのリポジトリの .venv
PY="${SLIDES_PYTHON:-}"
if [[ -z "$PY" || ! -x "$PY" ]]; then
  PY=""
  for c in ${PROJECT:+"$PROJECT/.venv/bin/python"} "$REPO/.venv/bin/python"; do
    if [[ -x "$c" ]]; then PY="$c"; break; fi
  done
fi
[[ -n "$PY" ]] || { echo ".venv がない: (cd $REPO && python3 -m venv .venv && .venv/bin/pip install -r requirements.txt)" \
                     "／別の Python を使うなら SLIDES_PYTHON=/path/to/python" >&2; exit 1; }
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

# 描画した HTML を、プロジェクトの output-dir の有無にかかわらず見つける
find_html() {  # $1 = プロジェクト根, $2 = 根からの相対パス（.qmd）
  local root="$1" rel="$2" c
  for c in "$root/_output/${rel%.qmd}.html" "$root/${rel%.qmd}.html"; do
    [[ -f "$c" ]] && { echo "$c"; return 0; }
  done
  return 1
}

TMP_PROJECT=""
# if で書く（`[[ … ]] && …` だと、空のときの偽が set -e の下で終了コード1になる）
cleanup() { if [[ -n "$TMP_PROJECT" ]]; then rm -rf "$TMP_PROJECT"; fi; }
trap cleanup EXIT

if [[ -n "$PROJECT" ]]; then
  REL="${QMD#"$PROJECT"/}"
  (cd "$PROJECT" && IMGFIG_REPORT="$NEW" quarto render "$REL" --to revealjs --quiet)
  RENDER_HTML="$(find_html "$PROJECT" "$REL")" || { echo "HTML が出力されていない（${PROJECT}）" >&2; exit 1; }
  HTML="$RENDER_HTML"
else
  # プロジェクトの外。スキルのリポジトリの設定で一時プロジェクトを組む
  for f in "$REPO/_quarto.yml" "$REPO/theme" "$REPO/filters"; do
    [[ -e "$f" ]] || { echo "描画に要る資材が無い: $f" >&2; exit 1; }
  done
  TMP_PROJECT="$(mktemp -d)"
  cp "$REPO/_quarto.yml" "$TMP_PROJECT/_quarto.yml"
  ln -s "$REPO/theme" "$TMP_PROJECT/theme"
  ln -s "$REPO/filters" "$TMP_PROJECT/filters"
  # デッキの ../../.claude/skills/slides/scripts からの import（imgfig・figs）も通るようにする
  ln -s "$REPO/.claude" "$TMP_PROJECT/.claude"
  # デッキはリンクではなくコピーで入れる。リンクだと Quarto が実体の位置を見てプロジェクト外と判断し、
  # _quarto.yml（テーマとフィルタ）が当たらないまま単独描画になる。
  mkdir -p "$TMP_PROJECT/decks"
  cp -R "$DECK_DIR" "$TMP_PROJECT/decks/$(basename "$DECK_DIR")"
  rm -rf "$TMP_PROJECT/decks/$(basename "$DECK_DIR")/_check"
  REL="decks/$(basename "$DECK_DIR")/$(basename "$QMD")"
  # 外に置くデッキは1つにまとめた HTML にする（デッキの隣に資材のフォルダを作らない）
  (cd "$TMP_PROJECT" && IMGFIG_REPORT="$NEW" quarto render "$REL" --to revealjs --quiet -M embed-resources:true)
  RENDER_HTML="$(find_html "$TMP_PROJECT" "$REL")" || { echo "HTML が出力されていない（一時プロジェクト）" >&2; exit 1; }
  HTML="${QMD%.qmd}.html"
  # Quarto が一時プロジェクトの _output ではなく入力の隣へ出す場合もあるため、同じファイルなら複写しない
  if [[ "$(cd "$(dirname "$RENDER_HTML")" && pwd -P)/$(basename "$RENDER_HTML")" != "$(cd "$DECK_DIR" && pwd -P)/$(basename "$HTML")" ]]; then
    cp "$RENDER_HTML" "$HTML"
  fi
  echo "HTML -> ${HTML}（1つにまとめた形）"
fi

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

# 本文が下端を越える・出典行にかかる枚を測る（図の高さを手で決めると、本文が1行増えたときに後から溢れる）。
# 描画した HTML の隣に計測用の写しを置き、Chrome headless の --dump-dom で各スライドの下端の位置を受け取る。
LAYOUT_HTML="${HTML%.html}.__layout.html"
"$PY" - "$HTML" "$LAYOUT_HTML" <<'PYEOF'
import sys
src, dst = sys.argv[1], sys.argv[2]
js = r"""<script>
window.addEventListener('load', function () {
  function run() {
    var H = Reveal.getConfig().height, out = [];
    Reveal.getSlides().forEach(function (s, i) {
      Reveal.slide(i);
      var scale = Reveal.getScale(), top = document.querySelector('.reveal .slides').getBoundingClientRect().top;
      var srcEl = s.querySelector('.source'), srcTop = null, srcBox = null;
      if (srcEl) { srcBox = srcEl.getBoundingClientRect(); srcTop = (srcBox.top - top) / scale; }
      var bottom = 0, over = 0, imgs = [];
      s.querySelectorAll('img, p, li, table, pre, h2, h3, figure, .cell-output-display').forEach(function (el) {
        if (el.closest('aside.notes') || (srcEl && (srcEl === el || srcEl.contains(el) || el.contains(srcEl)))) return;
        var r = el.getBoundingClientRect(); if (!r.height) return;
        var b = (r.bottom - top) / scale; bottom = Math.max(bottom, b);
        if (srcBox && b > srcTop + 2 && r.left < srcBox.right && r.right > srcBox.left) over = Math.max(over, b - srcTop);
      });
      s.querySelectorAll('img').forEach(function (im) {
        if (!im.closest('aside.notes')) imgs.push(Math.round(im.getBoundingClientRect().height / scale));
      });
      out.push({n: i + 1, bottom: Math.round(bottom), height: H, source: srcTop === null ? null : Math.round(srcTop),
                over_source: Math.round(over), imgs: imgs});
    });
    document.body.setAttribute('data-layout', JSON.stringify(out));
  }
  if (Reveal.isReady()) { run(); } else { Reveal.on('ready', run); }
});
</script>"""
html = open(src, encoding="utf-8").read()
i = html.rfind("</body>")
open(dst, "w", encoding="utf-8").write(html[:i] + js + html[i:] if i >= 0 else html + js)
PYEOF
"$CHROME" --headless=new --disable-gpu --hide-scrollbars --window-size=1280,720 \
  --run-all-compositor-stages-before-draw --virtual-time-budget=8000 --dump-dom "file://$LAYOUT_HTML" 2>/dev/null \
  | "$PY" -c '
import html, json, re, sys
m = re.search(r"data-layout=\"([^\"]*)\"", sys.stdin.read())
if not m:
    print("（下端のはみ出しは測れなかった。スクショで確かめる）")
    sys.exit(0)
bad = 0
for r in json.loads(html.unescape(m.group(1))):
    over_edge = r["bottom"] - r["height"]
    over = max(over_edge, r["over_source"] or 0)
    if over <= 8:      # 数px は図の余白の重なり。小さいものは知らせない
        continue
    bad += 1
    src_over = r["over_source"] or 0
    where = (f"下端を約{over_edge}px 越えている" if over_edge >= src_over else
             f"出典行に約{src_over}px かかっている（図の下の余白のこともあるので、スクショで出典が読めるか確かめる）")
    tall = max(r["imgs"] or [0])
    if tall > over:
        k = (tall - over) / tall
        fix = f"図（高さ約{tall}px）を約{k:.2f}倍にすると収まる（imgfig の図なら max_height_in を今の値×{k:.2f}、Quarto の図なら fig-height を同じ割合で縮める）"
    else:
        fix = "箇条書きか表を減らすか、本文をノートへ移す"
    num = r["n"]
    print(f"WARNING スライド{num}: 本文が{where}。{fix}")
print(f"下端のはみ出し: {bad} 枚")
'
rm -f "$LAYOUT_HTML"

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
  "$PY" "$(dirname "$0")/imgfig.py" check-look --report "$REPORT" --look "$DECK_DIR/data/look.csv" --html "$HTML"
elif [[ -s "$REPORT" ]] && grep -q '"captions": \[{' "$REPORT"; then
  echo "WARNING 写真の図があるが data/look.csv が無い（元の写真で確かめた、写っている対象の表を作る）"
fi

# 図のファイルサイズ（公開ページの重さ）。写真を並べた図は PNG だと1枚1MBを超える
FIG_DIR="${RENDER_HTML%.html}_files/figure-revealjs"
if [[ -d "$FIG_DIR" ]]; then
  echo "figures: $(du -sk "$FIG_DIR" | cut -f1) KB"
  find "$FIG_DIR" -type f -size +1024k | while read -r f; do
    echo "WARNING 図が1MBを超える: $(basename "$f")（写真の図はデッキの YAML に fig-format: jpeg と fig-dpi: 200 を書く）"
  done
fi
