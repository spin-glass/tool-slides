# ルールと根拠の対応

全文レポートと出典一覧（約170件）は Notion「Claudeスライド作成｜実践事例と再現性の手法」
https://app.notion.com/p/3e6600398c038173abdcef9a34be981f （追記 2026-09-30「深掘り調査」）。
ここには各ルールの一次根拠だけを置く。

| ルール | 根拠 | 確からしさ |
|---|---|---|
| 生成前ゲート（聴衆・行動・時間） | 読み手情報はAIが推測できず、無いと「誰にでも当てはまる網羅資料」へ平均回帰する。英語圏AI実務の成功例はすべて生成前に安価な承認ゲートを挟む | 実務事例からの推論 |
| 素材不足は書き足さず尋ねる | verbosity compensation: 不確実なほど応答が長くなりヘッジで埋まる（Zhang et al. 2024, GPT-4で50.40%） https://www.emergentmind.com/topics/verbosity-compensation-behavior | LLM研究（QA形式） |
| 「簡潔に」でなく数値上限と lint | 長さのみの報酬で RLHF 改善の大半が再現される（Singhal et al. COLM 2024） https://arxiv.org/abs/2310.03716 ／ 長さ選好はバイアス（LC AlpacaEval） https://arxiv.org/abs/2404.04475 | LLM研究 |
| ゴーストデッキ承認 | McKinsey の ghost deck（タイトルのみの約20%ドラフトで先に合意） http://workingwithmckinsey.blogspot.com/2013/07/McKinsey-presentations-ghost-decks.html ／ 段階生成は GPT の一括生成より読みやすさ3.90対2.30（DocPres, INLG 2024。論文5本・評価者2人の小規模評価） https://aclanthology.org/2024.inlg-main.18.pdf | 実務＋学術 |
| アクションタイトル（完全文） | Assertion-Evidence: 完全文見出し＋視覚証拠で1週間後の理解が向上（Garner & Alley 2016） http://writing.engr.psu.edu/Garner_et_al_2016.pdf | 教育研究（単一ラボ中心） |
| タイトル連読 | McKinsey のタイトルテスト https://slasaku.jp/column/gaishi-consul-powerpoint-tsutawaru-riyu | 実務 |
| 1枚1メッセージ・根拠3点 | 作業記憶≈4要素、コンサル実務の共通原則 https://constep.jp/column/3801 | 認知科学＋実務 |
| 本文を削る／appendix | coherence 効果 d=0.86（23/23実験）に対し、見出し・強調を足す signaling は d=0.41（Mayer & Fiorella 2014）。Cromley & Chen 2025 の g=1.00 は論文本体で未確認 | 教育研究（23件の実験すべてで支持） |
| 話す文はノートへ | redundancy 効果 d=0.86 | 教育研究 |
| ヘッジを減らし言い切る | 確信口調の回答の平均47%が誤りで、読者はヘッジで信頼を割り引けない（Zhou et al. ACL 2024） https://arxiv.org/abs/2401.06730 | LLM研究 |
| lint による機械検査 | 実デッキ140本の90%超が認知原則違反、観察者は欠陥を言語化できない（Kosslyn 2012） https://www.frontiersin.org/journals/psychology/articles/10.3389/fpsyg.2012.00230/full | 認知科学 |
| Stop hook で強制 | 「LLMが選ぶのを当てにせず、ある行動が常に起きる」 https://code.claude.com/docs/en/hooks-guide | 公式 |
| 画像で説明する（実例を並べる） | 画像で見せると閾値の判断が良くなるかを直接確かめた研究は未発見。近い結果: 事例単位の表示（Squares）は混同行列より速く正確に性能を読めた（Ren et al. 2017, IEEE TVCG、ML実務者24人。事例は画像ではなく箱で、課題も閾値選びではない） https://www.microsoft.com/en-us/research/publication/squares-supporting-interactive-performance-analysis-multiclass-classifiers/ | HCI研究（隣接・小規模） |
| 見せる画像は規則で選ぶ | 例を見せる説明は作業の成績を上げず、誤った助言でも利用者を従わせた（van der Waa et al. 2021, Artificial Intelligence 291:103404） https://repository.tudelft.nl/record/uuid:bff6a600-f6d9-4486-910b-36c8a847afa3 | HCI研究 |
| ラベルは画像のすぐ下に置く | spatial contiguity: 22件中22件の実験で支持、報告された中央値は1.10（Mayer & Fiorella 2014。表の値から計算し直すと0.95）。同じ章が引くメタ分析では d=0.72（Ginns 2006、37実験） | 教育研究 |
| 言葉だけでなく絵も使う | multimedia principle: 13件中13件で支持、中央値 d=1.35（Mayer 2021。自研究室の実験の中央値で、メタ分析ではない） https://www.cambridge.org/core/books/abs/cambridge-handbook-of-multimedia-learning/multimedia-principle/D09A773C7C5C214FA19D4C9841FBC83B | 教育研究 |
| 数値はコードセル | 手写しの数値は捏造・転記ミスの経路になる。Quarto はコードセルで計算結果を直接埋め込める | 設計判断 |
| 確認型（決めてもらうのではなく、決めたことを伝えて齟齬を確かめる） | 本人の決定（2026-10-01）。1枚1メッセージ（上の行）に確認点1つを足した型 | 本人の決定 |
| 未決を隠さず示す（`.tbd` と「まだ決めていない点」の一覧） | 不確実な箇所を文章で繕うと水増しになる（verbosity compensation、上の行）。Claude Slides ランタイムの `[__]` プレースホルダ方式と同型 | LLM研究＋設計判断 |
| 設計書とスライドを同じ主張の表（claims.csv）から作る | 原文の版・箇所と主張を対応させ、参考値→実績・想定→確約の格上げを機械で見つけるため。最初に適用した設計書4文書では判定規則2通り・組織名3通りのずれが見つかった（2026-10-01 のレビュー） | 設計判断（題材1件） |
| 設計書の一般論・前置き・繰り返しを段落ごと削る（要約で縮めない） | coherence 効果 d=0.86（上の行）。不確実な箇所の水増し（verbosity compensation、上の行）。2か所に書いた定義は片方だけ直されてずれる（最初に適用した4文書の観察） | 教育研究＋LLM研究＋観察（題材1件） |
| 設計書の章の直後に図を1つ、矢印に意味を書く | multimedia principle（上の行）と、C4 の図の点検項目 https://c4model.com/diagrams/checklist ／ arc42 の設計判断の記録 https://docs.arc42.org/section-9/ | 教育研究＋実務 |
| 本文28px・タイトル40px・表24px・注記16px | 3デッキ28枚の棚卸し（Claude Design「スライド型見本」2026-09-30）: 32px×1.6 では2行タイトル＋箇条書き5つで約500px。灰 #6e7781 は16pxで4.6:1、#57606a で6.4:1 | 実測（自分のデッキ3本） |

## 未検証・較正待ち

- 日本語の閾値（本文250字・タイトル40字・15行）は根拠のある値ではなく初期値。最初の2〜3デッキで `scripts/lint_slides.py` の `LIMITS` を較正する。
- budget の目安（1.5分/枚）は folklore。実証が制約するのは総枚数でなく1画面の負荷と1枚1メッセージ。
- 教育研究からビジネス発表への外挿は構造的類推で、直接測定はない。
- 画像で見せる効果そのものは未測定。確かめるなら、表だけの版と画像の版を見せ、「どの線を選ぶか」と「その理由」がどう変わるかを比べる。
- 確認型の効果（意思決定者の理解・所要時間・差し戻し）と、設計書の組み替えの効果は未測定。実際に適用した題材は設計書1件（見本は架空の題材）で、別分野の設計書で確かめてから規則を増やす。
- サムネイルの大きさ（1枚150px以上、1つの図に12〜16枚まで）は、2026-09-30 の検証（`experiments/2026-09-30-model-vs-skill/`）の盲検評価による。当初の目安（約100px、1枚に48枚まで）に従ったデッキは、評価者3名から「1枚70〜100pxで細部が見えない」と指摘され、1枚約190pxで12枚を並べたデッキより画像の点が低かった。評価者は Claude のモデルで、人の聴衆では確かめていない。
