# tool-slides

読み手のいない・言い訳の多い・枚数の多い AI 生成スライドを、指示ではなく構造で防ぐための Quarto スライド作成環境。
Claude Code の `slides` スキルが「聴衆・行動・持ち時間の確認 → タイトルだけの骨子の承認 → 本文 → lint と全枚スクショ」の順で作り、Stop hook が lint 不合格のまま終わらせない。

**公開ページ（Cloudflare）**: https://tool-slides.toshihiro-engineer.workers.dev （作ったデッキの一覧。revealjs・PDF・pptx）
／ 検証の一覧: https://tool-slides.toshihiro-engineer.workers.dev/experiments/2026-09-30-model-vs-skill/
／ 設計の根拠にした調査（Notion、公開）: https://app.notion.com/p/Claude-3e6600398c038173abdcef9a34be981f

設計の根拠: Notion「[Claudeスライド作成｜実践事例と再現性の手法](https://app.notion.com/p/Claude-3e6600398c038173abdcef9a34be981f)」（追記 2026-09-30）、要約は `.claude/skills/slides/references/evidence.md`。

## 使い方

```sh
python3 -m venv .venv && .venv/bin/pip install -r requirements.txt   # 初回のみ（コードセル実行用）
claude   # 「/slides 〜の発表資料を作って」
```

### どのプロジェクトからでも使えるようにする

`slides` と `design-doc` をユーザーレベルのスキルとして入れる。
リンクなので、このリポジトリを直せばそのまま反映される。

```sh
mkdir -p ~/.claude/skills
ln -s "$PWD/.claude/skills/slides"     ~/.claude/skills/slides
ln -s "$PWD/.claude/skills/design-doc" ~/.claude/skills/design-doc
mkdir -p ~/.claude/agents
ln -s "$PWD/.claude/agents/doc-reviewer.md" ~/.claude/agents/doc-reviewer.md
```

`doc-reviewer` は、書いたセッションとは別のコンテキストで資料を検算するサブエージェント（数値の出典・標本と層化・確定と未決・ノートと本文・本文と出典の射程）。案件に固有の観点と参照資料（数値の一覧・決定の一覧・案件の NG 語）は、呼び出すときにファイルのパスで渡す。案件のパスや数値はこのリポジトリに入れない。

入れたあとは、他のプロジェクトで作業しているときも `python3 ~/.claude/skills/slides/scripts/lint_slides.py <デッキ>/index.qmd` のように呼べる。
**デッキはこのリポジトリの外に置いてよい。** `render_check.sh` は、デッキから上に辿って `_quarto.yml` を持つフォルダが見つかればそのプロジェクトで描画し、見つからなければこのリポジトリの `_quarto.yml`・`theme/`・`filters/` で一時プロジェクトを組んで描画して、1つにまとめた HTML をデッキの隣に置く。どちらでも見た目は同じになる。
描画に使う Python は `$SLIDES_PYTHON` → そのプロジェクトの `.venv` → このリポジトリの `.venv` の順に探す。

**Devin CLI で使う**

Devin は互換として `~/.claude/skills/` を読むので、上のリンクのままスキルは認識される（`/slides`・`/design-doc` で呼べる）。
ゲートは `.devin/hooks.v1.json`（このリポジトリに同梱）。スキルの frontmatter の `hooks` は Claude 専用で、Devin は読まない。
権限は `.devin/config.json`。`.claude/settings.json` の許可設定は Claude 専用。
他のリポジトリで使うときは、そのリポジトリに `.devin/hooks.v1.json` を置き、`CLAUDE_PROJECT_DIR="$DEVIN_PROJECT_DIR" python3 "$HOME/.claude/skills/slides/scripts/lint_slides.py" --hook` を Stop に登録する。
テストを走らせるには `.venv/bin/pip install -r requirements-dev.txt`。

| 操作 | コマンド |
|---|---|
| lint（違反＋タイトル連読） | `python3 .claude/skills/slides/scripts/lint_slides.py decks/<name>/index.qmd` |
| タイトル連読だけ | `python3 .claude/skills/slides/scripts/lint_slides.py --titles decks/<name>/index.qmd` |
| 全枚スクショ | `.claude/skills/slides/scripts/render_check.sh decks/<name>` → `decks/<name>/_check/slide-NN.png` |
| PDF（画面と同じ見た目） | `.claude/skills/slides/scripts/render_check.sh decks/<name> --pdf` → `decks/<name>/<name>.pdf`（検収した PNG を綴じる） |
| 出力 | `QUARTO_PYTHON=.venv/bin/python quarto render decks/<name>/index.qmd`（`--to revealjs` / `pptx` / `beamer`） |
| 群ごとに画像を並べた図を作る | `.venv/bin/python .claude/skills/slides/scripts/imgfig.py groups --table table.csv --thumbs thumbs/ --by true,pred --out groups.png`（ほかに `matrix`、閾値用の `moved`） |
| 設計書の検査（章参照・章ごとの図・Mermaid を PNG に） | `python3 .claude/skills/design-doc/scripts/check_doc.py --render decks/<name>/design/<doc>.md` → `design/_check/<doc>-fig-NN.png` |
| 設計書の削除候補の一覧（原文に使う） | `python3 .claude/skills/design-doc/scripts/check_doc.py --candidates decks/<name>/design/_source/<doc>.md` |
| 設計書の構造（章ごとの読む字数・表の割合・型・参照と、前置き・引く表の位置・同じ型の連続・未決の位置の warning） | `python3 .claude/skills/design-doc/scripts/check_doc.py --structure decks/<name>/design/_source/<doc>.md` |
| 原文と書き直しの比較（字数・段落数・一般論） | `python3 .claude/skills/design-doc/scripts/check_doc.py --original decks/<name>/design/_source/<doc>.md decks/<name>/design/<doc>.md` |
| 主張の表の検査 | `python3 .claude/skills/design-doc/scripts/claims.py decks/<name>/claims.csv` |
| テスト | `.venv/bin/python -m unittest discover -s tests` |

出力先は `_output/decks/<name>/`。新しいデッキは `decks/_template/` をコピーする。

## 具体例の画像で説明するデッキ

型は1つ:「数の主張を、その数の中身の画像で見せる」。切り口（閾値の移動、正解×予測、変更の前後、群ごとの代表、似たもの）が違っても、表を読む → 群に分ける → 並べる → 選び方を書く、の手順は同じ。
見本は `decks/2026-09-30-outlier-threshold-images/`（閾値を動かすと、どの画像が外れ値に移るか）。

- 図は `.claude/skills/slides/scripts/imgfig.py` で描く。`load_table` で表（1行＝1画像）を読み、`split_by`／`cross` で群に分け、`grid_figure`・`panels_figure`・`rows_figure`・`matrix_figure`・`histogram_figure` で並べる。見せる画像は `pick` で規則的に選ぶ。1枚の画像になるので revealjs・pptx・PDF で同じ見た目になる。
- 重い前処理（画像の取得・埋め込み計算）はデッキのフォルダの `prepare.py` に分け、結果の `data/scores.csv`・`data/thumbs/`・`credits.html` をコミットする。描画に必要なのは matplotlib と pillow だけ。
  `uv run --no-project --python 3.12 --with torch==2.14.0 --with transformers==5.16.1 --with pillow --with numpy python decks/<name>/prepare.py all`
- 写真の図は YAML に `fig-format: jpeg` と `fig-dpi: 200` を書く（PNG の約1/4の重さになり、図がスライドの空きに合わせて伸びる）。
- 第三者の画像は、作者・出典の一覧（`credits.html`）を YAML の `resources:` で一緒に公開する。公開に向かない画像は目視で外し、`exclude.csv` に理由を残す。

## スライドの型（Claude Design「スライド型見本」）

各枚の証拠の形から型を1つ選び、骨子で `<!-- type: pair -->` のように書く。型は text・pair（前→後）・outcome（条件→結果）・number（大きな数字）・roles（体制）・timeline（工程表）・direction（関係の向き）・chart・flow（Mermaid）・table・images。
見た目は Claude Design「スライド型見本」の部品で、CSS は `theme/custom.scss`、図は `.claude/skills/slides/scripts/figs.py`（`figs.timeline`・`figs.direction`・`figs.bars`）に実装した。書き方と使い分けは `.claude/skills/slides/references/slide_types.md`。
lint は知らない型と1枚に2つ以上の型を止め、型が無い本編の枚・型の書き方が本文に無い枚・本文の `style=` を warning で知らせる。

## 設計書と、決めたことを確かめるスライド（design-doc スキル）

設計書の改稿と意思決定者向けスライドを、同じ主張の表から作る。原資料 → `claims.csv`（主張ID・原文の箇所・状態: 事実／参考値／方針／想定／提案／決定／未決）→ 設計書（`design/*.md`、Markdown＋Mermaid。VSCode のプレビューと Notion で表示）／確認型スライド（`index.qmd`）→ 原文との照合。
意思決定者には「決めてもらう」のではなく「決めたことを伝えて齟齬を確かめる」（本人の決定 2026-10-01）。確認型は1枚＝決めたこと1つ＋確認点1つで、`<!-- kind: confirm -->` を書くと lint が確認点の帯（`::: {.check}`）・まだ決めていない値（`[要確認]{.tbd}`）・主張の表との対応を検査する。
見本は `decks/2026-10-01-invoice-ocr-confirm/`（架空の題材: 請求書を OCR で読み取る方式への切替。確認型5枚＋付録3枚、運用・移行設計の組み替え案、主張19件）。設計ファイルは Claude Design「スライド型見本」（2026-10-01）。

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
theme/custom.scss                 Noto Sans JP、日本語の禁則、スライドの型の部品（.pair・.outcome・.big・.roles・.tbd・.check）
filters/strip-comments.lua        lint 用の HTML コメントを出力から除く（空スライド防止）
decks/<yyyy-mm-dd>-<name>/index.qmd   1発表 = 1フォルダ
.claude/skills/slides/            スキル本体・規約・例・NG辞書・lint・スクショ・画像の図（imgfig.py）・型の図（figs.py）
.claude/skills/design-doc/        設計書と確認型スライド: 主張の表（claims.py）・設計書の検査（check_doc.py）・規約・雛形
.claude/agents/doc-reviewer.md    検算レビュー用のサブエージェント（案件の観点は呼び出し時にパスで渡す）
decks/<name>/claims.csv, design/  （設計書の案件のみ）主張の表と、組み替えた設計書（Markdown＋Mermaid）
decks/_template_confirm/          確認型スライドの雛形（kind: confirm）
decks/<name>/prepare.py, data/    （画像のデッキのみ）前処理と、その結果のスコア・サムネイル・出典
scripts/publish.sh, wrangler.jsonc  全デッキを出力して Cloudflare に公開
tests/                            lint・imgfig・figs のテスト、lint が block すべき違反サンプル（fixtures/）
```

## Stop hook

`SKILL.md` の frontmatter に Stop hook を宣言している。スキルを呼んだ時点から、そのセッションの間ずっと有効（2026-09-30 に `claude -p` で発火と block→修正を確認）。
hook は git で未コミットの変更がある `decks/**/*.qmd` だけを検査し、違反があれば `{"decision":"block","reason":...}`（先頭10件）を返す。同じセッションで3回続けて block したら、止めずに本人へ知らせる。

スキルを呼ばずに deck を編集したときも検査したい場合は、`.claude/settings.json` に次を足す（スキル側と二重に走る点に注意）:

```json
{"hooks":{"Stop":[{"hooks":[{"type":"command","command":"python3 \"$CLAUDE_PROJECT_DIR/.claude/skills/slides/scripts/lint_slides.py\" --hook"}]}]}}
```

## 既知の制約

- 文字の大きさ（本文28px・タイトル40px・表24px・注記16px）と図の幅（`fig-width: 13.3`）は、3デッキ28枚の棚卸し（Claude Design「スライド型見本」2026-09-30）で決めた値。確認型と設計書の組み替えの効果は未測定（実際に適用した題材は1件、見本は架空の題材）。
- lint の日本語閾値（本文250字・タイトル40字・15行）は初期値。2デッキ作った時点ではどの枚も上限に届かず、据え置いている。タイトルは全角34字を超えると2行になる。
- 画像の図は、サムネイルがスライド上で150px以上（1つの図に12〜16枚まで）が目安。100pxを下回ると中身が読めない。`render_check.sh` が図ごとの大きさの目安を表示する。当初の目安（約100px、48枚まで）では、盲検評価で「画像が小さい」と指摘された（`experiments/2026-09-30-model-vs-skill/`）。見本デッキの4枚目（線の間の46枚の全数、1枚約90px）は、全数を見せること自体が主張なので残してあるが、新しい目安より小さい。
- pptx は、図のあとに文字があるスライドを pandoc が2枚に分ける。pptx が主目的のデッキでは出典をノートへ移す。
- `.claude/settings.json` の許可設定は、このフォルダで Claude Code を一度対話起動して信頼するまで無視される。
