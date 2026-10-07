# 数値ルールと、スクショで確かめる数値

`SKILL.md` から移した正本。lint（`scripts/lint_slides.py`）が機械的に検査する規則の一覧と、lint では測れないがスクショで必ず確かめる数値。block と warning の名前は lint の出力と同じ。

## lint が検査する規則

| 対象 | 目標 | block（Stop hook が止める） |
|---|---|---|
| 本編枚数 | 持ち時間から決めた budget | budget 超過（`<!-- appendix -->` 以降は数えない）、承認後に budget を書き換えた（git の HEAD の承認済みの版と比べる） |
| bullets / 枚 | 3 | 6以上（4〜5は warning） |
| 行数 / 枚 | — | 16行以上 |
| 本文 / 枚 | — | 全角250字超（半角は0.5字。`<style>`・`<script>` の中は数えない） |
| タイトル | 完全文・so-what・数字 | 全角40字超、体言止め、ラベル型（「〜について」「まとめ」等） |
| 表示コード / 枚 | — | 11行以上 |
| placeholder | 0 | TODO・TBD・XXX・lorem・[insert]・[要確認] 等が1つでも残る |
| 生成前ゲート | — | 先頭の `audience`/`action`/`minutes`/`budget`/`status` コメントが欠ける |
| ゴースト段階 | — | `status: ghost` のまま本文・コード・ノートがある |
| 最初の `##` より前 | 計算セルは `include: false` 指定のみ | 本文や表示されるセル（空のスライドになる） |
| 画像ファイル | 代替テキストつき | `![…](パス)` のファイルが無い |
| 枚数（写真の図を使うデッキ） | コードの値 | 本文・箇条書き・出典行の「N枚」を手で書き、描画のコードの assert でも検算していない（タイトルは見ない） |
| スライドの型（`<!-- type: pair -->`） | 本編の各枚に1つ（Claude Design「スライド型見本」の部品） | 知らない型、1枚に2つ以上（型が無い・型の書き方が本文に無いは warning） |
| 確認型（`<!-- kind: confirm -->`） | 1枚＝決めたこと1つ＋確認点1つ | 確認点 `::: {.check}` が0個・2個以上・全角40字超、タイトル全角56字超（2行まで）。規約は `design-doc` スキル |
| まだ決めていない値 `[要確認]{.tbd}` | 1枚目の「まだ決めていない点」の一覧に対応 | 一覧 `::: {.undecided}` が無いのに `.tbd` がある |
| 主張の表（デッキのフォルダに `claims.csv` があるとき） | `<!-- claims: C1 -->` の id が表にある | 無い id、未決の主張を未決と示さない枚。表の `path`・`rev`・`quote` で出典と照らし、quote が今の出典に無い（quote-not-found）・rev より後に出典が変わった（source-changed）・path があって quote が無い |
| `claims: required`（デッキの YAML か、上の `_quarto.yml`・`_metadata.yml` の `metadata:`） | 本編の各枚に `<!-- claims: … -->` | claims の無い本編の枚（見出しだけの表紙・区切りは除く）、`claims.csv` が無い |

warning（止めないが直す）: 型が無い（type-missing）・型の書き方が本文に無い（type-markup）・本文に `style=` を直接書く（inline-style）・テーマに定義の無いクラスを書く（class-undefined。例 `{.e4}` は見た目が変わらず素通りする）・`{python}` のセルに `#| fig-width`/`#| fig-height` を書く（cell-fig-size。Jupyter では効かない）、承認後に本編のタイトルが変わった・枚が増えた（approved-title-changed）、行動が「選ぶ・判断する」のデッキで最後の枚に図も表も無い（action-evidence）、標本を宣言したデッキで数字のある枚に宣言が無い（denominator-missing）、バズワード、ヘッジ・言い訳・メタ前置き（1枚2個以上、または本編で0.3個/枚超）、画像の代替テキストなし、図を描くセルに `#| fig-alt:` なし、画像を並べた図に選び方（すべて・等間隔・上位・無作為など）の記載なし。
語彙は `references/ng_words.md`、根拠は `references/evidence.md`。閾値は最初の2〜3デッキで較正する。

このスキルの frontmatter の `hooks` は Claude Code だけが読む（プロジェクトの `.claude/skills/slides` → `~/.claude/skills/slides` の順に lint を探し、どちらも無ければ何もしない）。
**hook に頼らず、フェーズ4の検査はどのエージェントでも自分で走らせる。** Devin CLI の hook（`.devin/hooks.v1.json`）と実行の許可（`.devin/config.json`。`Exec(…)` の書き方）の例は `references/agents.md`。

lint では測れないが、スクショで必ず確かめる数値:

- タイトルは全角34字を超えると2行になる（1行に収めたいときの目安）。
- 画像を並べる図は、サムネイル1枚がスライド上で150px以上（スライド幅の約1/8）になる枚数にする。目安は1つの図に12〜16枚まで。`render_check.sh` が図ごとの大きさの目安を表示する。
- 写真を並べた図は、デッキの YAML に `fig-format: jpeg` と `fig-dpi: 200` を書く（PNG だと1枚1〜2MB。JPEG にすると図がスライドの空きに合わせて伸びる）。
- 文字の大きさ（`theme/custom.scss`）: 本文28px・行間1.5（42px/行）、タイトル40px（全角34字で2行）、表24px、出典・付録の印・枚数16px。32px×1.6 では2行タイトル＋箇条書き5つで約500px になり図の余地が無かった（3デッキ28枚の棚卸し、Claude Design「スライド型見本」2026-09-30）。
- 図（matplotlib）の文字はスライド上で約20px にする: `_quarto.yml` の `fig-width: 13.3`（幅いっぱい）なら `plt.rcParams["font.size"] = 16`。流れ図の箱の中は20px以上。灰色の文字は `#57606a`（6.4:1）、`#9aa4ae` は枠線と強調しない系列だけ（白地の文字では2.6:1で読めない）。群の色は青 `#0b5cad` と橙 `#b35900`（`imgfig.BLUE` / `imgfig.ORANGE`、scss の `$link-color` / `$accent-2`）。
- 工程表・関係の向き・横棒は `scripts/figs.py` の `figs.timeline`・`figs.direction`・`figs.bars` で描く（Claude Design の見本と同じ色・文字。手で matplotlib を書き直さない）。最初のセルで `figs.setup()`。
- 流れ図は `{mermaid}` のセルで描ける（`_quarto.yml` の `mermaid-format: png` で PNG になり、文字がはみ出さない）。先頭に `python3 .claude/skills/design-doc/scripts/check_doc.py --mermaid-init 24px` の1行を置き、色と文字をデッキにそろえる。数値の図は matplotlib。
- 画像ヒストグラムは1区間1段（`per_bin=(1,1)`）にして写真を約110px以上にする。区間の枚数などの文字は18px以上。
- 図の高さは手で決めると、本文が1行増えたときに後から下端や出典行に溢れる。`render_check.sh` が、本文が下端を越えた枚・出典行や確認点の帯（`position: absolute` の要素）に重なった枚と、図を何倍にすれば収まるか（`max_height_in` や `figsize` の高さに掛ける値）を出す。
- **図の大きさはコードで決める。** `{python}` のセルの `#| fig-height: 1.15` は Jupyter 経路では効かず、`_quarto.yml` の既定（13.3×4.4インチ、画面の約3分の1の高さ）で描かれる（lint が cell-fig-size で知らせる）。自前の matplotlib の図は `fig, ax = plt.subplots(figsize=(13.3, 1.15))` で高さを決める。imgfig の図は `max_height_in`、写真1枚の実寸を揃えるなら `thumb_in`。
- **コードで描いた横長の図は、枚の見出しに `{.nostretch}` を付ける**（`## タイトル {.nostretch}`）。revealjs の auto-stretch は図を枚の空きいっぱいに引き伸ばすので、13.3×1.15 の図でも縦に伸び、下の表が画面の外へ出る。写真を並べた imgfig の図は空きに合わせて伸びてよいので付けない。
- **自前の matplotlib の図は、描く前に `imgfig.use_japanese_font()`（または `figs.setup()`）を呼ぶ。** imgfig・figs の図の関数は中で日本語フォントを設定するが、`plt.subplots` から自分で描く図では呼ばれず、日本語が豆腐（□）になる。
- **枚をまたいで写真の大きさを揃えるときは `thumb_in` を渡す**（例 `imgfig.panels_figure(groups, thumb_in=1.1)`。1枚の幅が1.1インチになる）。`max_height_in` を揃えても、図の高さに説明の行数（2行・3行）が含まれるため写真の大きさが変わる。

budget の目安: 口頭発表は持ち時間（分）÷1.5 を切り捨て。読むだけの資料は読了時間（分）÷1。
これは出発点であり、本人が別の値を言えばそれに従う。
