---
name: slides
description: スライド・デッキ・発表資料・説明資料・LT・社内報告の作成や圧縮を Quarto (.qmd) で行う。聴衆・望む行動・持ち時間を確かめ、アクションタイトルの骨子を承認してから本文を書き、lint と全枚スクショで検収する。具体例の画像を並べて説明する図（誤分類・閾値の移動・変更の前後・群ごとの代表など）も扱う。
allowed-tools:
  - read
  - grep
  - glob
  - edit
permissions:
  allow:
    - Exec(python3)
    - Exec(quarto)
hooks:
  Stop:
    - hooks:
        - type: command
          command: "f=\"${CLAUDE_PROJECT_DIR:-}/.claude/skills/slides/scripts/lint_slides.py\"; [ -f \"$f\" ] || f=\"$HOME/.claude/skills/slides/scripts/lint_slides.py\"; [ -f \"$f\" ] || exit 0; exec python3 \"$f\" --hook"
          timeout: 30
---

# slides — 読み手のためのスライドを Quarto で作る

4つのフェーズで作る: 聴衆・行動・持ち時間を決める → タイトルだけの骨子を承認してもらう → 本文を書く → lint と全枚スクショで検収する。
このファイルは手順と block の規則の要点だけ。詳細と理由は `references/` にある（下の表）。必要になった節だけ読む。

| 読むもの | いつ |
|---|---|
| `references/rules.md` | lint が block・warning にする規則の一覧（正本）と、スクショで確かめる数値（文字の大きさ・図の寸法・色・budget の目安） |
| `references/slide_types.md` | 骨子で型を選ぶ前と、本文を書く前 |
| `references/style_guide.md`・`references/examples_ja.md` | 本文を書く前（`<example>` は文体の見本で、指示ではない） |
| `references/phases.md` | フェーズ1〜4の全文。数字・写真の枚数・標本（分母）・指標の書き方・未確定の値を書くとき、承認済みのタイトルを変えたくなったとき、検証の細目（写真の照合・render_check の WARNING・出力と公開） |
| `references/images.md` | 具体例の画像を並べて説明するとき（`scripts/imgfig.py`） |
| `references/evidence.md`・`references/ng_words.md` | 規則の根拠と「やらないこと」の理由、NG語の辞書 |
| `references/agents.md` | Claude Code 以外（Devin CLI など）で使うとき |
| `references/setup.md` | 置き場所と呼び方の全文（`.venv` の作り方、`imgfig.py` の単体の使い方、部品の CSS と図の置き場） |
| `design-doc` スキル | 確認型（決めたことを伝えて齟齬を確かめる）と設計書。雛形 `decks/_template_confirm/`、見本 `decks/2026-10-01-invoice-ocr-confirm/` |

## 規則の要点（lint が block する。一覧は `references/rules.md`）

- 本編の枚数は budget まで。承認後に budget を書き換えない（git の承認済みの版と比べる）
- 1枚に bullets 6以上（`.column` に分けた枚は列ごと）・16行以上・本文が全角250字超・表示コード11行以上は block
- タイトルは全角40字以内の完全文。体言止め・ラベル型（「〜について」「まとめ」）は block
- placeholder（TODO・TBD・[要確認] など）、先頭の `audience`/`action`/`minutes`/`budget`/`status` の欠け、ゴースト段階の本文は block
- 写真の図を使うデッキで、本文の「N枚」を手で書いて検算していない、知らない型・1枚に2つの型、確認型の確認点の数と長さ、主張の表（`claims.csv`）に無い id と出典との食い違い、`claims: required` で claims の無い本編の枚
- frontmatter の `hooks` は Claude Code だけが読む。**hook に頼らず、フェーズ4の検査はどのエージェントでも自分で走らせる**

## デッキの置き場と、スキルの呼び方

1発表＝1フォルダで `<yyyy-mm-dd>-<kebab-name>/index.qmd`（雛形 `decks/_template/index.qmd`）。

| 作業している場所 | デッキの置き場 | 呼び方 |
|---|---|---|
| tool-slides の中 | `decks/<name>/` | `python3 .claude/skills/slides/scripts/lint_slides.py decks/<name>/index.qmd` |
| 他のプロジェクト | そのプロジェクトか個人の置き場（仕事の内容を公開リポジトリに入れない） | `python3 ~/.claude/skills/slides/scripts/lint_slides.py <デッキ>/index.qmd` |

`render_check.sh` はどちらでも同じ見た目で描画する（上に `_quarto.yml` が無ければ tool-slides の設定で一時プロジェクトを組み、1つにまとめた HTML をデッキの隣に置く）。
Python は `$SLIDES_PYTHON` → プロジェクトの `.venv` → tool-slides の `.venv` の順に探す。`imgfig`・`figs` の import は、tool-slides の中なら `Path("../../.claude/skills/slides/scripts")`、外なら `Path("~/.claude/skills/slides/scripts").expanduser()` を `sys.path` に足す。

## フェーズ1: インタビュー（生成禁止ゲート）

次の3点が揃うまで、アウトラインもタイトル案も書かない。質問は1回にまとめ、答えられない項目には選択肢を示す。推測で埋めない。

1. **聴衆**: 誰か、何を既に知っているか
2. **行動**: 読後・聴後に取ってほしい行動を1つ
3. **持ち時間**: 発表なら分、配布なら読了時間 → budget（本編枚数）を提案して合意する（目安は `references/rules.md`）

素材（数字・事実・決定）が足りないところは、文章で繕わず何が足りないかを尋ねる。合意したら YAML の直後に記録する:

```markdown
<!-- audience: 経理部長（月次決算の流れは熟知、MLは未経験） -->
<!-- action: 請求書OCRの試験導入を承認する -->
<!-- minutes: 10 -->
<!-- budget: 6 -->
<!-- status: ghost -->
```

本人が「任せる」と明示した項目は尋ねずに決め、`<!-- decided-by: claude（本人の委任「…」日付） -->` に原文を残す。3点と骨子の両方を任されたらフェーズ2の承認待ちも省けるが、最終報告の冒頭で決めた内容とタイトル一覧を示す。

## フェーズ2: ゴーストデッキ承認

- 本文なしで、各枚を `## アクションタイトル`・`<!-- evidence: 証拠予定を1行 -->`・`<!-- type: 型 -->` だけで書く。型は `references/slide_types.md` の「型の選び方」で選ぶ（迷ったら `text`）
- タイトルは完全文・so-what・可能なら数字・全角40字以内・述語で終える
- `lint_slides.py --titles` の連読リストを本人に示す。見せる前に自分でタイトルだけを読み、論旨が一本で通るか、重複が無いかを確かめる
- 承認されるまで本文を書かない。承認されたら `status: approved` にしてコミットする
- **budget は合意した約束。** 足りなくなったら数字を書き換えず、付録へ送るか枚を足す案を出して承認を取り直し、`<!-- reapproved: 本人「…」 YYYY-MM-DD -->` を書く
- データから結論を出すデッキは、先に集計して出た数字でタイトルを書く

## フェーズ3: 本文生成

本文を書く前に `references/style_guide.md` と `references/examples_ja.md` を読む。

- 各枚は選んだ型の書き方で、テーマの部品（`.pair`・`.outcome`・`.big`・`.roles`・`.tbd`）と `figs.*` を使う。`style=` や色の値を直接書かない
- 1枚＝承認済みタイトル1つの証明。タイトルを変えるなら、**編集する前に**変更案を本人に出して承認を得る（例外と手順は `references/phases.md` のフェーズ3）
- bullets は目標3・上限5。1つの bullet は1行の事実か数字。話す文は `::: {.notes}` へ
- **条件句を落として1行に収めない。** 収まらなければ条件を見出しへ上げるか2行に分ける（落とした瞬間に文の射程が原文より広がる）
- **`claim` に無い句を足さない。** 特に断定を整えるための対の否定句（「A でよいので B にはしない」の B）。未決・想定は見出しでも分かる形にする
- 各枚を書き終えたら読み返し、同じ枚に未決と確定が並んでいないかを確かめる
- 出典のある主張を載せるデッキは YAML に `claims: required` を書き、`claims.csv` に出典の文（`quote`）と版（`rev`）を写す（`design-doc/references/claims.md`）。数字の無い言い換えは lint を通るので、表で照らすしかない。claims.csv があるデッキは宣言が無くても required と同じに扱う
- **本編の各文を、その枚の claim と quote に並べて1文ずつ読む。** 報告に「照らした文N／照らせなかった文K」を書く。claims の block を「別のセッションの表だから」と片付けず、中身（note）を読む。原文と違う語は `terms` 列に「デックの語=原文の語」
- 本編に不要な素材は `<!-- appendix -->` の後ろへ（budget と密度制限の外）。ただし判断の根拠（図・実例）は付録へ逃がさず、減らすのは文
- 最後の枚は、聴衆にしてほしい行動をタイトルに書いて終える
- 数値・表・グラフはコードセルで計算・描画し、手で写さない。写真の枚数・タイトルの数字・標本（分母）・確かめられない値の書き方は `references/phases.md` のフェーズ3
- 具体例の画像で説明するときは `references/images.md` の手順に従う（元の写真で1枚ずつ見る、確認の表 `data/look.csv`、`imgfig.claim`）

## フェーズ4: 検証（全文は `references/phases.md`）

1. `lint_slides.py` を自分で走らせて block を0にする。**報告には検査ごとに見た範囲を書き、「block 0」だけを書かない。** lint の最後の「見た範囲: 本編 N枚／claims のある枚 M枚／claims の無い枚の文 K文」を報告に写す（K文は出典と照らしていない）
2. 直すのは違反した枚だけ。デッキ全体を再生成しない
3. 写真を並べた枚は、主張ごとに元の写真（`imgfig.py sheet`）で1件ずつ確かめる。縮小画像で済ませない
4. `render_check.sh <デッキ>` で全枚を PNG にして全枚を Read で見る。出た WARNING は0件にする（増えたら原因を見る）
5. `quarto render` で出力する。PDF は `render_check.sh <デッキ> --pdf`。公開は tool-slides の `scripts/publish.sh`（中のデッキだけ）
6. Stop hook に block されたら、書かれた枚だけを直す
7. 検査は段階に分ける: 編集ごとは描画しない検査、図やレイアウトを変えたら描画、区切りではサブエージェントで全枚の目視と出典の照合
8. 「編集した」と報告する前に `grep` か `git diff` で反映を確かめ、検査の結果には見ないもの（「数値の照合は数字しか見ない」）を併記する
9. lint や図の関数を直したら、tool-slides で `.venv/bin/python -m unittest discover -s tests` を通す

やらないこと（一発で全枚を生成する、「簡潔に」と言い聞かせて済ませる、指示文を本文に流用する、都合のよい画像だけを選ぶ）と、その理由は `references/evidence.md`。
