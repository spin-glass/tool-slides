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

for q in "${decks[@]}"; do
  # revealjs を最後に出す（別形式の出力が index_files/ の補助ファイルを置き換えるため）
  for fmt in pptx beamer revealjs; do
    quarto render "$q" --to "$fmt" --quiet
  done
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
page = f'''<!doctype html><html lang="ja"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1"><title>tool-slides</title>
<meta name="robots" content="noindex">
<style>
body{{font-family:"Hiragino Sans","Noto Sans JP",sans-serif;max-width:760px;margin:40px auto;padding:0 16px;color:#1f2328;background:#fff}}
h1{{font-size:1.4em}} ul{{list-style:none;padding:0}} li{{padding:14px 0;border-bottom:1px solid #d0d7de}}
a{{color:#0b5cad}} .t{{font-weight:700;font-size:1.1em}} .s,.f{{display:block;color:#57606a;font-size:.9em;margin-top:4px}}
</style></head><body><h1>tool-slides</h1><ul>{"".join(rows)}</ul></body></html>'''
pathlib.Path("_output/index.html").write_text(page, encoding="utf-8")
PY

printf 'User-agent: *\nDisallow: /\n' > _output/robots.txt

[[ "${1:-}" == "--no-deploy" ]] && { echo "built: _output/"; exit 0; }

npx --yes wrangler deploy
