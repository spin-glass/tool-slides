#!/usr/bin/env bash
# 全デッキを revealjs / PDF / pptx で出力し、一覧ページを付けて Cloudflare Workers（静的アセット、wrangler.jsonc）に公開する。
# 使い方: scripts/publish.sh            （事前に `npx wrangler login`）
#         scripts/publish.sh --no-deploy （出力と一覧ページだけ作る）
set -euo pipefail

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
cd "$ROOT"
export QUARTO_PYTHON="$ROOT/.venv/bin/python"

decks=()
for q in decks/*/index.qmd; do
  [[ "$q" == decks/_* ]] && continue
  decks+=("$q")
done

rm -rf _output   # 消したデッキや古い図を公開しないよう、毎回作り直す

for q in "${decks[@]}"; do
  # revealjs を最後に出す（別形式の出力が index_files/ の補助ファイルを置き換えるため）
  for fmt in pptx beamer revealjs; do
    quarto render "$q" --to "$fmt" --quiet
  done
done

# 検証で作らせたデッキ（experiments/<名前>/site/。各検証の site.py が作る）。
# 容量が大きいので git には入れていない。手元に作ってあるものだけを載せる
for s in experiments/*/site; do
  [[ -f "$s/index.html" ]] || continue
  mkdir -p _output/experiments
  cp -R "$s" "_output/experiments/$(basename "$(dirname "$s")")"
done

# 一覧ページ（新しい順）。タイトルは各 qmd の YAML から取る
"$QUARTO_PYTHON" - "${decks[@]}" <<'PY'
import html, re, sys, pathlib
rows = []
for q in sorted(sys.argv[1:], reverse=True):
    p = pathlib.Path(q)
    text = p.read_text(encoding="utf-8")
    m = re.search(r'^title:\s*"?(.*?)"?\s*$', text, re.M)
    sub = re.search(r'^subtitle:\s*"?(.*?)"?\s*$', text, re.M)
    name = p.parent.name
    rows.append(f'''<li><a class="t" href="decks/{name}/index.html">{html.escape(m.group(1) if m else name)}</a>
<span class="s">{html.escape(sub.group(1) if sub else "")}</span>
<span class="f"><a href="decks/{name}/index.pdf">PDF</a> · <a href="decks/{name}/index.pptx">PPTX</a> · {name[:10]}</span></li>''')
exps = []
for idx in sorted(pathlib.Path("_output/experiments").glob("*/index.html"), reverse=True):
    t = re.search(r"<title>(.*?)</title>", idx.read_text(encoding="utf-8"))
    exps.append(f'''<li><a class="t" href="experiments/{idx.parent.name}/index.html">{t.group(1) if t else idx.parent.name}</a>
<span class="f">{idx.parent.name[:10]}</span></li>''')
exp_html = f'<h2>検証</h2><ul>{"".join(exps)}</ul>' if exps else ""
page = f'''<!doctype html><html lang="ja"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1"><title>tool-slides</title>
<meta name="robots" content="noindex">
<style>
body{{font-family:"Hiragino Sans","Noto Sans JP",sans-serif;max-width:760px;margin:40px auto;padding:0 16px;color:#1f2328;background:#fff}}
h1{{font-size:1.4em}} ul{{list-style:none;padding:0}} li{{padding:14px 0;border-bottom:1px solid #d0d7de}}
a{{color:#0b5cad}} .t{{font-weight:700;font-size:1.1em}} .s,.f{{display:block;color:#57606a;font-size:.9em;margin-top:4px}}
h2{{font-size:1.15em;margin-top:2em}}
</style></head><body><h1>tool-slides</h1><ul>{"".join(rows)}</ul>{exp_html}</body></html>'''
pathlib.Path("_output/index.html").write_text(page, encoding="utf-8")
PY

printf 'User-agent: *\nDisallow: /\n' > _output/robots.txt

[[ "${1:-}" == "--no-deploy" ]] && { echo "built: _output/"; exit 0; }

npx --yes wrangler deploy

# 反映の確認。公開直後の数秒は前の版が返るので、手元の HTML と一致するまで最大60秒待つ
URL="$(sed -n 's/^site-url: *//p' _quarto.yml)"
[[ -n "$URL" ]] || exit 0
pages=()
while IFS= read -r f; do pages+=("${f#_output/}"); done < <(find _output -name index.html -not -path '*/index_files/*' | sort)
for _ in $(seq 1 20); do
  stale=()
  for page in "${pages[@]}"; do
    want="$(shasum -a 256 < "_output/$page" | cut -d' ' -f1)"
    # 公開直後は新しいページが数秒 404 を返す。失敗も「まだ一致しない」として待ち直す（set -e で止めない）
    got="$(curl -fsSL "$URL/$page" 2>/dev/null | shasum -a 256 | cut -d' ' -f1 || true)"
    [[ "$got" == "$want" ]] || stale+=("$page")
  done
  if [[ ${#stale[@]} -eq 0 ]]; then
    echo "公開を確認（${#pages[@]}ページが手元と一致）: $URL"
    exit 0
  fi
  sleep 3
done
echo "WARNING 60秒待っても手元と一致しないページがある: ${stale[*]}" >&2
exit 1
