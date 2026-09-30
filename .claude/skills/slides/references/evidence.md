# ルールと根拠の対応

全文レポートと出典一覧（約170件）は Notion「Claudeスライド作成｜実践事例と再現性の手法」
https://app.notion.com/p/3e6600398c038173abdcef9a34be981f （追記 2026-09-30「深掘り調査」）。
ここには各ルールの一次根拠だけを置く。

| ルール | 根拠 | 確からしさ |
|---|---|---|
| 生成前ゲート（聴衆・行動・時間） | 読み手情報はAIが推測できず、無いと「誰にでも当てはまる網羅資料」へ平均回帰する。英語圏AI実務の成功例はすべて生成前に安価な承認ゲートを挟む | 実務事例からの推論 |
| 素材不足は書き足さず尋ねる | verbosity compensation: 不確実なほど応答が長くなりヘッジで埋まる（Zhang et al. 2024, GPT-4で50.40%） https://www.emergentmind.com/topics/verbosity-compensation-behavior | LLM研究（QA形式） |
| 「簡潔に」でなく数値上限と lint | 長さのみの報酬で RLHF 改善の大半が再現される（Singhal et al. COLM 2024） https://arxiv.org/abs/2310.03716 ／ 長さ選好はバイアス（LC AlpacaEval） https://arxiv.org/abs/2404.04475 | LLM研究 |
| ゴーストデッキ承認 | McKinsey の ghost deck（タイトルのみの約20%ドラフトで先に合意） http://workingwithmckinsey.blogspot.com/2013/07/McKinsey-presentations-ghost-decks.html ／ 段階生成は一発生成より一貫性3.80対2.00（DocPres, INLG 2024） https://aclanthology.org/2024.inlg-main.18.pdf | 実務＋学術 |
| アクションタイトル（完全文） | Assertion-Evidence: 完全文見出し＋視覚証拠で1週間後の理解が向上（Garner & Alley 2016） http://writing.engr.psu.edu/Garner_et_al_2016.pdf | 教育研究（単一ラボ中心） |
| タイトル連読 | McKinsey のタイトルテスト https://slasaku.jp/column/gaishi-consul-powerpoint-tsutawaru-riyu | 実務 |
| 1枚1メッセージ・根拠3点 | 作業記憶≈4要素、コンサル実務の共通原則 https://constep.jp/column/3801 | 認知科学＋実務 |
| 本文を削る／appendix | coherence 効果 d=0.86、メタ分析 g=1.00（Mayer & Fiorella 2014; Cromley & Chen 2025） | 教育研究（最も強い） |
| 話す文はノートへ | redundancy 効果 d=0.86 | 教育研究 |
| ヘッジを減らし言い切る | 確信口調の回答の平均47%が誤りで、読者はヘッジで信頼を割り引けない（Zhou et al. ACL 2024） https://arxiv.org/abs/2401.06730 | LLM研究 |
| lint による機械検査 | 実デッキ140本の90%超が認知原則違反、観察者は欠陥を言語化できない（Kosslyn 2012） https://www.frontiersin.org/journals/psychology/articles/10.3389/fpsyg.2012.00230/full | 認知科学 |
| Stop hook で強制 | 「LLMが選ぶのを当てにせず、ある行動が常に起きる」 https://code.claude.com/docs/en/hooks-guide | 公式 |
| 数値はコードセル | 手写しの数値は捏造・転記ミスの経路になる。Quarto はコードセルで計算結果を直接埋め込める | 設計判断 |

## 未検証・較正待ち

- 日本語の閾値（本文250字・タイトル40字・15行）は根拠のある値ではなく初期値。最初の2〜3デッキで `scripts/lint_slides.py` の `LIMITS` を較正する。
- budget の目安（1.5分/枚）は folklore。実証が制約するのは総枚数でなく1画面の負荷と1枚1メッセージ。
- 教育研究からビジネス発表への外挿は構造的類推で、直接測定はない。
