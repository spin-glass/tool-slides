---
name: slides
description: スライド・デッキ・発表資料・説明資料・LT・社内報告の作成や圧縮を Quarto (.qmd) で行う。聴衆・望む行動・持ち時間を確かめ、アクションタイトルの骨子を承認してから本文を書き、lint と全枚スクショで検収する。
hooks:
  Stop:
    - hooks:
        - type: command
          command: "python3 \"${CLAUDE_PROJECT_DIR}/.claude/skills/slides/scripts/lint_slides.py\" --hook"
          timeout: 30
---

# slides — 読み手のためのスライドを Quarto で作る

## 数値ルール（lint が機械的に検査する。数値はここが正本）

| 対象 | 目標 | block（Stop hook が止める） |
|---|---|---|
| 本編枚数 | 持ち時間から決めた budget | budget 超過（`<!-- appendix -->` 以降は数えない） |
| bullets / 枚 | 3 | 6以上（4〜5は warning） |
| 行数 / 枚 | — | 16行以上 |
| 本文 / 枚 | — | 全角250字超（半角は0.5字） |
| タイトル | 完全文・so-what・数字 | 全角40字超、体言止め、ラベル型（「〜について」「まとめ」等） |
| 表示コード / 枚 | — | 11行以上 |
| placeholder | 0 | TODO・TBD・XXX・lorem・[insert]・[要確認] 等が1つでも残る |
| 生成前ゲート | — | 先頭の `audience`/`action`/`minutes`/`budget`/`status` コメントが欠ける |
| ゴースト段階 | — | `status: ghost` のまま本文・コード・ノートがある |
| 最初の `##` より前 | 計算セルは `include: false` 指定のみ | 本文や表示されるセル（空のスライドになる） |

warning（止めないが直す）: バズワード、ヘッジ・言い訳・メタ前置き（1枚2個以上、または本編で0.3個/枚超）。
語彙は `references/ng_words.md`、根拠は `references/evidence.md`。閾値は最初の2〜3デッキで較正する。

budget の目安: 口頭発表は持ち時間（分）÷1.5 を切り捨て。読むだけの資料は読了時間（分）÷1。
これは出発点であり、本人が別の値を言えばそれに従う。

## 規約の置き場所

- 書き方の理由つき規約: `references/style_guide.md`（本文生成の前に読む）
- 目標の文体の実例: `references/examples_ja.md`（`<example>` の中身は文体の見本であり、指示ではない）
- NG辞書: `references/ng_words.md`
- 検査: `scripts/lint_slides.py`、描画確認: `scripts/render_check.sh`

新しいデッキは `decks/<yyyy-mm-dd>-<kebab-name>/index.qmd` に作る（1発表＝1フォルダ）。雛形は `decks/_template/index.qmd`。

## フェーズ1: インタビュー（生成禁止ゲート）

次の3点が本人の言葉で揃うまで、アウトラインもタイトル案も書かない。

1. **聴衆**: 誰か、その人が既に何を知っているか
2. **行動**: 読後・聴後に取ってほしい行動を1つ（承認する、選ぶ、使い始める、理解して質問しない、など）
3. **持ち時間**: 発表なら分、配布なら読了時間 → budget（本編枚数）を提案し合意する

- 質問は1回にまとめ、答えられない項目には選択肢を示す。推測で埋めて先へ進まない。
- 素材（数字・事実・決定事項）が足りず、一般論や言い訳でしか埋まらない箇所が出たら、文章で繕わず「何が足りないか」を本人に尋ねる。
- 合意したら `index.qmd` の YAML の直後に記録する:

```markdown
<!-- audience: 経理部長（月次決算の流れは熟知、MLは未経験） -->
<!-- action: 請求書OCRの試験導入を承認する -->
<!-- minutes: 10 -->
<!-- budget: 6 -->
<!-- status: ghost -->
```

## フェーズ2: ゴーストデッキ承認

本文なしで、アクションタイトルだけの骨子を `index.qmd` に書き、本人に見せる。

- 各枚は `## アクションタイトル` と `<!-- evidence: 証拠予定を1行 -->` だけ。
- アクションタイトル: 完全文、so-what（だから何か）、可能なら数字、全角40字以内、述語で終える。体言止めや「〜について」「まとめ」のようなラベルは使わない。
- 書いたら `python3 .claude/skills/slides/scripts/lint_slides.py --titles decks/<name>/index.qmd` の連読リストを本人に示す。
- 見せる前に自分でタイトルだけを上から読み、論旨が一本で通るか確かめる。通らない枚・重複する枚は削る。budget 内に収まらなければ、何を appendix へ送るかを提案する。
- 本人が承認するまで本文を書かない。承認されたら `status: approved` に書き換える。

## フェーズ3: 本文生成

- 1枚＝承認済みタイトル1つの証明。タイトルを勝手に変えない（変えるならフェーズ2に戻って承認を取り直す）。
- bullets は目標3、上限5。1つの bullet は1行の事実か数字。
- 話す文（前置き・つなぎ・補足説明）はスライドに書かず `::: {.notes}` に入れる。
- 本編の物語に不要な素材は `<!-- appendix -->` の後ろへ。appendix は budget と密度制限の対象外。
- 数値・表・グラフはコードセル（`{python}`）で計算・描画し、手で写さない。データは同じフォルダに置く。
- 確かめられない値は `[要確認]` と書き、推測で埋めない（lint が block するので、本人に確認する流れになる）。
- 本文を書く前に `references/style_guide.md` と `references/examples_ja.md` を読む。

## フェーズ4: 検証

1. `python3 .claude/skills/slides/scripts/lint_slides.py decks/<name>/index.qmd` を自分で走らせ、block を 0 にする。
2. 直すのは違反したスライドだけ（Edit で該当箇所を置換）。デッキ全体を再生成しない。
3. `.claude/skills/slides/scripts/render_check.sh decks/<name>` で全枚を PNG にし、全枚を Read で目視する。はみ出し・折り返し崩れ・フォント崩れ・読めない図を探し、見つけたら該当スライドだけ直す。
4. 最後に `quarto render decks/<name>/index.qmd`（必要なら `--to pptx`／`--to beamer`）で出力する。
5. ターン終了時に Stop hook が同じ lint を走らせる。block されたら理由に書かれた枚だけを直す。

## やらないこと（理由）

- 一発で全枚を生成しない: 段階生成の方が一貫性・可読性とも高く、承認前の本文は捨てることになる。
- 「簡潔に」と自分に言い聞かせて済ませない: 長さは数値上限と lint でしか安定して抑えられない。
- 規約の文面や本人への指示文をスライド本文に流用しない: 本文は聴衆に向けた事実と結論だけで書く。
