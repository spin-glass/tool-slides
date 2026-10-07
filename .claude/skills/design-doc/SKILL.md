---
name: design-doc
description: 設計書（基本設計・ML設計・精度検証・運用設計・移行計画など）のレビュー・改稿（冗長な一般論・繰り返しを削る）と、意思決定者に「決めたことを伝えて齟齬を確かめる」確認型スライドの作成。原資料から主張の表（claims.csv）を作り、設計書は Markdown＋Mermaid（VSCode プレビュー・Notion で表示）、スライドは slides スキルの Quarto で作り、最後に原文と照合する。「設計書が分かりにくい」「意思決定者向けに短く」「決めたことを確認するスライド」で使う。
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
          command: "f=\"${CLAUDE_PROJECT_DIR:-}/.claude/skills/design-doc/scripts/check_doc.py\"; [ -f \"$f\" ] || f=\"$HOME/.claude/skills/design-doc/scripts/check_doc.py\"; [ -f \"$f\" ] || exit 0; exec python3 \"$f\" --hook"
          timeout: 60
        - type: command
          command: "f=\"${CLAUDE_PROJECT_DIR:-}/.claude/skills/slides/scripts/lint_slides.py\"; [ -f \"$f\" ] || f=\"$HOME/.claude/skills/slides/scripts/lint_slides.py\"; [ -f \"$f\" ] || exit 0; exec python3 \"$f\" --hook"
          timeout: 30
---

# design-doc — 設計書と、決めたことを確かめるスライドを同じ主張の表から作る

原資料 → 主張の表（根拠と状態を確かめた共通メモ）→ 設計書／確認型スライド → 原文との照合、の順に作る。設計書の改稿とスライドを別々に書かない。
スライドの作法（聴衆・行動・時間、ゴーストデッキ承認、lint、全枚スクショ）は `slides` スキルに従う。このファイルは手順の骨と block の要点だけで、細目は `references/` にある。

| 読むもの | いつ |
|---|---|
| `references/phases.md` | 各フェーズの全文（主張の表の作り方、11種類のずれ、削る4分類、組み替えの規則、確認型スライド、原文との照合、Notion の修正指示の受け方） |
| `references/rules.md` | check_doc・claims.py・lint が block・warning にする規則の一覧（正本） |
| `references/claims.md` | 主張の表の列と状態、出典（`path`・`rev`・`quote`）との照合 |
| `references/design_doc_guide.md` | 設計書を組み替える前（規約と理由） |
| `references/confirm_deck.md` | 確認型スライドを作るとき |
| `references/ng_doc.md`・`references/evidence.md` | 一般論・前置きの辞書、やらないことと理由 |

## 成果物と置き場所（1案件＝1フォルダ `<yyyy-mm-dd>-<kebab-name>/`）

| 成果物 | ファイル | 雛形 | 検査 |
|---|---|---|---|
| 主張の表 | `claims.csv` | `templates/claims.csv` | `scripts/claims.py` |
| 設計書（組み替え） | `design/<文書名>.md` | `templates/design_doc.md` | `scripts/check_doc.py`（`--render` で Mermaid を PNG にして目視） |
| 確認型スライド | `index.qmd` | tool-slides の `decks/_template_confirm/index.qmd` | slides の `lint_slides.py` と `render_check.sh` |

置き場所と呼び方は `slides` スキルの「デッキの置き場と、スキルの呼び方」に従う（tool-slides の外なら `python3 ~/.claude/skills/design-doc/scripts/...`）。**tool-slides は公開リポジトリなので、仕事の原文・削った段落の一覧・案件の語はコミットしない**（原文は `design/_source/` に置く。.gitignore 済み）。
見本: `decks/2026-10-01-invoice-ocr-confirm/`（架空の題材。確認型5枚＋付録3枚、運用・移行設計の改稿案、主張19件）。

## 規則の要点（一覧は `references/rules.md`）

- block: 確認点が0個・2個以上・全角40字超、確認型のタイトルが全角56字超、一覧の無い `.tbd`、主張の表に無い id・未決を未決と示さない枚、`claims.csv` の列・状態・target の誤りと出典との食い違い、無い章への参照、Mermaid の種類の誤り・描画エラー、placeholder、中身の無い段落、同じ文の繰り返し
- warning（直す）: 読む字数の上限超え、§1 の4要点の欠けと3割超え、前置き1000字超、引く表が読む路の途中、同じ型の章の連続、図の形・ラベル・色・題、太字の段落の多さ、表と同じ図、付録へ散る未決、ほか
- frontmatter の `hooks` は Claude Code だけが読む。**hook に頼らず、`check_doc.py` とスライドの検査はどのエージェントでも終える前に自分で走らせる**（Devin CLI の例は slides の `references/agents.md`）

## フェーズ0: 原資料を主張の表にする（生成禁止ゲート）

1. 原資料の所在と版を確かめる。読めない原文を要約や記憶で代用しない
2. `claims.csv` を作る（1行＝1主張、原文の箇所を必ず書く、状態は7つ）。**原文の語（実績・目安・想定・必ず・限り・以上／未満）と限定句は言い換えず claim に写す。** 出典がファイルなら `path`・`rev`・`quote` も書く
3. `claims.py <案件>/claims.csv` で検査し、未決の一覧を本人に見せる

本人に尋ねられないときは推奨で仮に決め、note に「仮」と書いて報告の冒頭に出す。決める担当が原文に無ければ「原文に無い」。提案は target none にして報告に回す。細目は `references/phases.md`。

## フェーズ1: 整合と不足を確かめ、先に決める項目を出す

原文を通して読み、11種類のずれ（現行と変更後、用語の混在、判定規則、合格条件と警報の関係、変更の単位、組織名、同じ事象の扱い、合格条件の語、監視に無い切り戻しの指標、段階の表の入る／出る条件、定義の無い語）を探す。一覧と例は `references/phases.md`。
指摘は「編集で直せる／別文書で補える／設計判断が必要／実測が要る」に分け、設計判断は推奨と残る確認を1回でまとめて尋ねる。意思決定者に上げるのは業務側にしか決められないことだけ。

## フェーズ2: 設計書を組み替える（`design/<文書名>.md`）

### 2.1 先に測って削る（組み替えの前に）

冗長さは要約では直らない（条件・例外・担当が落ちる）。縮めるのは「段落を丸ごと削る」と「繰り返しを1か所にまとめる」だけ。

1. 原文を `design/_source/<文書名>.md` に置き、`check_doc.py --candidates`・`--paragraphs`・`--structure` で測る
2. 全段落を「残す／1か所にまとめる／削る／未決にする」に分ける（限定語を外さない、作業の文は残す）
3. 削った段落の一覧は報告に入れ、設計書には書かない
4. 書き終えたら `check_doc.py --render --original <原文> <書き直し>` で読む字数を比べ、block を0にする

### 2.2 組み替える

規約と理由は `references/design_doc_guide.md`、要点の全文は `references/phases.md` の 2.2。本文の中身で始め（冒頭は「扱うこと／読む人／原文／状態」の表と §1 だけ）、引く表は付録へ、§1 は4つの要点（何を変えるか・次へ進む条件の値・まだ決めていない点・決めたこと）だけにする。原文に無い順序・頻度・担当・案を足さない。図は `check_doc.py --render` の PNG を全枚目視する。

## フェーズ3: 確認型スライド

**1枚＝決めたこと1つ＋確認点1つ。** 意思決定者には決めたことを伝えて齟齬を確かめる（決めてもらう構成にしない）。`<!-- kind: confirm -->` と各枚の `<!-- claims: … -->`、1枚目に `::: {.undecided}`。型と見本は `references/confirm_deck.md`、検証は slides のフェーズ4。

## フェーズ4: 原文との照合

状態の格上げ・格下げが無いか、落とした作業・承認・費用・回復が無いか、矛盾を想像で統一していないか、無い参照を作っていないか、読者テスト（何を決めたか・誰が動くか・どの根拠が無いか・いつ進めるか）に答えられるかを確かめて報告する。lint 合格だけで「分かりやすくなった」と言わない。全文は `references/phases.md`。

## Notion の修正指示ページを受けたとき

ページ全文を Notion の接続で取得し（取れなければ貼り付けを頼む）、各指示の「目印」で場所を探して、指示のあるブロックだけをそのまま置き換える。本人が決める点は埋めずに §1.1 の `[要確認]` に足し、`check_doc.py --render` で検査して、置き換えた箇所・止めた指示・残した未決を報告する。手順の全文と、指示ページを書く側の順序は `references/phases.md`。
