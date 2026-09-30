# tool-slides

読み手のいない・言い訳の多い・枚数の多い AI 生成スライドを、指示ではなく構造で防ぐための Quarto スライド作成環境。
Claude Code の `slides` スキルが「聴衆・行動・持ち時間の確認 → タイトルだけの骨子の承認 → 本文 → lint と全枚スクショ」の順で作り、Stop hook が lint 不合格のまま終わらせない。

設計の根拠: Notion「Claudeスライド作成｜実践事例と再現性の手法」（追記 2026-09-30）、要約は `.claude/skills/slides/references/evidence.md`。

## 使い方

```sh
uv venv .venv && uv pip install --python .venv/bin/python -r requirements.txt   # 初回のみ（コードセル実行用）
claude   # 「/slides 〜の発表資料を作って」
```

| 操作 | コマンド |
|---|---|
| lint（違反＋タイトル連読） | `python3 .claude/skills/slides/scripts/lint_slides.py decks/<name>/index.qmd` |
| タイトル連読だけ | `python3 .claude/skills/slides/scripts/lint_slides.py --titles decks/<name>/index.qmd` |
| 全枚スクショ | `.claude/skills/slides/scripts/render_check.sh decks/<name>` → `decks/<name>/_check/slide-NN.png` |
| 出力 | `QUARTO_PYTHON=.venv/bin/python quarto render decks/<name>/index.qmd`（`--to revealjs` / `pptx` / `beamer`） |

出力先は `_output/decks/<name>/`。新しいデッキは `decks/_template/` をコピーする。

## 公開（Cloudflare）

```sh
npx wrangler login        # 初回のみ
scripts/publish.sh        # 全デッキを revealjs・PDF・pptx で出力し、一覧ページを付けて公開
```

公開先は https://tool-slides.toshihiro-engineer.workers.dev （Workers の静的アセット、設定は `wrangler.jsonc`）。
URL を知っていれば誰でも閲覧できる。検索避けに `noindex` と `robots.txt` を付けている。
Cloudflare Pages は Workers に統合されたため、`wrangler pages` ではなく `wrangler deploy` を使う。

## 構成

```
_quarto.yml                       revealjs（既定）/ pptx / beamer(PDF, LuaLaTeX + ヒラギノ)
theme/custom.scss                 Noto Sans JP、日本語の禁則
filters/strip-comments.lua        lint 用の HTML コメントを出力から除く（空スライド防止）
decks/<yyyy-mm-dd>-<name>/index.qmd   1発表 = 1フォルダ
.claude/skills/slides/            スキル本体・規約・例・NG辞書・lint・スクショ
tests/fixtures/                   lint が block すべき違反サンプル
```

## Stop hook

`SKILL.md` の frontmatter に Stop hook を宣言している。スキルを呼んだ時点から、そのセッションの間ずっと有効（2026-09-30 に `claude -p` で発火と block→修正を確認）。
hook は git で未コミットの変更がある `decks/**/*.qmd` だけを検査し、違反があれば `{"decision":"block","reason":...}`（先頭10件）を返す。同じセッションで3回続けて block したら、止めずに本人へ知らせる。

スキルを呼ばずに deck を編集したときも検査したい場合は、`.claude/settings.json` に次を足す（スキル側と二重に走る点に注意）:

```json
{"hooks":{"Stop":[{"hooks":[{"type":"command","command":"python3 \"$CLAUDE_PROJECT_DIR/.claude/skills/slides/scripts/lint_slides.py\" --hook"}]}]}}
```

## 既知の制約

- lint の日本語閾値（本文250字・タイトル40字・15行）は初期値。最初の2〜3デッキで `lint_slides.py` の `LIMITS` を較正する。
- pptx は、図のあとに文字があるスライドを pandoc が2枚に分ける。pptx が主目的のデッキでは出典をノートへ移す。
- `.claude/settings.json` の許可設定は、このフォルダで Claude Code を一度対話起動して信頼するまで無視される。
