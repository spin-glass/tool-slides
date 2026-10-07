# 規約の置き場所と、デッキの置き場・スキルの呼び方（全文）

`SKILL.md` から移した全文（2026-10-07）。

## 規約の置き場所

- スライドの型（Claude Design「スライド型見本」の部品と図）: `references/slide_types.md`（骨子で型を選ぶ前と、本文を書く前に読む）。部品の CSS は `theme/custom.scss`、図は `scripts/figs.py`
- 書き方の理由つき規約: `references/style_guide.md`（本文生成の前に読む。画像を並べるときは「具体例の画像で説明する」の節も）
- 目標の文体の実例: `references/examples_ja.md`（`<example>` の中身は文体の見本であり、指示ではない）
- NG辞書: `references/ng_words.md`
- 検査: `scripts/lint_slides.py`、描画確認: `scripts/render_check.sh`（どちらも任意のパスのデッキを受ける）。Claude Code 以外のエージェントでの設定: `references/agents.md`
- 画像の図: `scripts/imgfig.py`（qmd から import する。単体でも `imgfig.py groups`・`matrix`・`moved` で1枚の図を作れる）
- 確認型（意思決定者に決めたことを伝えて齟齬を確かめる）と設計書: `design-doc` スキル（`.claude/skills/design-doc/SKILL.md`）。雛形は `decks/_template_confirm/index.qmd`、見本は `decks/2026-10-01-invoice-ocr-confirm/`（架空の題材）

## デッキの置き場と、スキルの呼び方

1発表＝1フォルダで、`<yyyy-mm-dd>-<kebab-name>/index.qmd` に作る。雛形は `decks/_template/index.qmd`。
置く場所は、このスキルのリポジトリ（tool-slides）で作業しているかどうかで変える。

| 作業している場所 | デッキの置き場 | 検査と描画の呼び方 |
|---|---|---|
| tool-slides の中 | `decks/<yyyy-mm-dd>-<kebab-name>/` | `python3 .claude/skills/slides/scripts/lint_slides.py decks/<name>/index.qmd` のようにリポジトリ相対で呼ぶ |
| 他のプロジェクト | そのプロジェクトか個人の置き場（仕事の内容を公開リポジトリに入れない） | `python3 ~/.claude/skills/slides/scripts/lint_slides.py <デッキ>/index.qmd` のようにユーザーレベルのスキルを呼ぶ |

**`render_check.sh` はどちらでも同じ見た目で描画する。** デッキから上に辿って `_quarto.yml` を持つフォルダが見つかればそのプロジェクトで描画し、見つからなければ tool-slides の `_quarto.yml`・`theme/`・`filters/` で一時プロジェクトを組んで描画し、1つにまとめた HTML をデッキの隣に置く。

描画に使う Python は `$SLIDES_PYTHON` → プロジェクトの `.venv` → tool-slides の `.venv` の順に探す。tool-slides に `.venv` が無ければ `python3 -m venv .venv && .venv/bin/pip install -r requirements.txt` で作る。
デッキから `imgfig`・`figs` を import するときは、tool-slides の中なら `Path("../../.claude/skills/slides/scripts")`、他のプロジェクトなら `Path("~/.claude/skills/slides/scripts").expanduser()` を `sys.path` に足す。
