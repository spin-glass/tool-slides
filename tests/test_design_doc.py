"""design-doc スキルの検査（check_doc.py / claims.py）と、slides の lint の確認型の規則を fixtures で確かめる。

    python3 -m unittest discover -s tests -v
"""
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / ".claude/skills/slides/scripts"))
sys.path.insert(0, str(ROOT / ".claude/skills/design-doc/scripts"))
import check_doc  # noqa: E402
import claims  # noqa: E402
import structure  # noqa: E402
import verbosity  # noqa: E402
import lint_slides as lint  # noqa: E402

NG = lint.load_ng_words()
FIX = ROOT / "tests/fixtures"


def lint_rules(path: Path, severity: str) -> list[str]:
    return [i.rule for i in lint.check_deck(lint.parse_deck(path), NG) if i.severity == severity]


def doc_rules(path: Path, severity: str) -> list[str]:
    return [i.rule for i in check_doc.check_document(path) if i.severity == severity]


class ConfirmDeck(unittest.TestCase):
    def test_minimal_confirm_deck_passes(self):
        self.assertEqual(lint_rules(FIX / "confirm/index.qmd", "block"), [])

    def test_confirm_violations(self):
        blocks = lint_rules(FIX / "confirm_bad/index.qmd", "block")
        for rule in ("check-missing", "check-multiple", "check-length", "claims-unknown",
                     "claims-undecided-hidden", "title-length"):
            self.assertIn(rule, blocks)

    def test_tbd_needs_undecided_list(self):
        self.assertEqual(lint_rules(FIX / "tbd_without_list.qmd", "block"), ["tbd-without-list"])

    def test_title_list_shows_checks_and_claims(self):
        text = lint.title_list(lint.parse_deck(FIX / "confirm/index.qmd"))
        self.assertIn("確認点: 現行の説明に違いがないか", text)
        self.assertIn("主張: C1", text)
        self.assertIn("型: confirm", text)

    def test_ghost_confirm_template_has_check_comments(self):
        deck = lint.parse_deck(ROOT / "decks/_template_confirm/index.qmd")
        self.assertEqual(deck.meta["kind"][1], "confirm")
        self.assertIn("確認点: 担当、工数、時期", lint.title_list(deck))


class Claims(unittest.TestCase):
    def test_valid_table(self):
        rows = claims.load(FIX / "confirm/claims.csv")
        self.assertEqual(claims.validate(rows), [])
        self.assertIn("未決 1", claims.summary(rows))

    def test_invalid_rows(self):
        rows = [{"id": "1x", "doc": "", "section": "", "claim": "", "status": "確定", "evidence": "", "owner": "", "target": "slide", "note": ""},
                {"id": "C2", "doc": "", "section": "", "claim": "a", "status": "事実", "evidence": "", "owner": "", "target": "doc", "note": ""}]
        errors = claims.validate(rows)
        self.assertTrue(any("id は" in e for e in errors))
        self.assertTrue(any("claim が空" in e for e in errors))
        self.assertTrue(any("status は" in e for e in errors))
        self.assertTrue(any("target は" in e for e in errors))
        self.assertTrue(any("evidence" in e for e in errors))
        self.assertTrue(any("doc と section" in e for e in errors))

    def test_sample_deck_table(self):
        rows = claims.load(ROOT / "decks/2026-10-01-invoice-ocr-confirm/claims.csv")
        self.assertEqual(claims.validate(rows), [])


class DesignDoc(unittest.TestCase):
    def test_ok_document(self):
        self.assertEqual(doc_rules(FIX / "design/ok.md", "block"), [])
        self.assertEqual(doc_rules(FIX / "design/ok.md", "warning"), [])

    def test_bad_document(self):
        blocks = doc_rules(FIX / "design/bad.md", "block")
        self.assertEqual(sorted(set(blocks)), ["mermaid-type", "placeholder", "ref-missing"])
        self.assertEqual(blocks.count("ref-missing"), 2)        # §4.2 と 7章
        warnings = doc_rules(FIX / "design/bad.md", "warning")
        self.assertEqual(sorted(set(warnings)), ["heading-number", "mermaid-caption", "mermaid-theme"])   # 短い文書には章ごとの図を求めない

    def test_verbose_document(self):
        doc = FIX / "design/verbose.md"
        blocks = doc_rules(doc, "block")
        self.assertEqual(blocks.count("filler-only"), 2)      # 一般論だけの段落と、一般論だけの箇条書き
        self.assertEqual(blocks.count("dup-sentence"), 1)     # 1章と2章で同じ文
        warnings = doc_rules(doc, "warning")
        for rule in ("filler", "unit-long"):
            self.assertIn(rule, warnings)

    def test_verbose_candidates_keep_informative_units(self):
        _, metrics, cands = verbosity.analyze(FIX / "design/verbose.md")
        lines = {u.text[:12] for u, why in cands if "一般論・前置き・ヘッジだけ" in why}
        self.assertEqual(metrics.candidates, 2)
        self.assertFalse(any("3営業日" in t for t in lines))     # 数字のある項目は削除候補にしない

    def test_cross_document_duplicate(self):
        self.assertIn("cross-dup", doc_rules(FIX / "design_multi/a.md", "block"))

    def test_claims_missing_from_document(self):
        issues = check_doc.check_document(FIX / "design_claims/design/doc.md")
        missing = [i.message for i in issues if i.rule == "claims-unused"]
        self.assertEqual(len(missing), 1)
        self.assertIn("C2", missing[0])
        self.assertNotIn("C3", missing[0])      # target が deck の主張は設計書に無くてよい

    def test_metrics_compare_with_original(self):
        _, verbose, _ = verbosity.analyze(FIX / "design/verbose.md", siblings=False)
        _, clean, _ = verbosity.analyze(FIX / "design/ok.md", siblings=False)
        self.assertGreater(verbose.filler, clean.filler)
        self.assertGreater(verbose.chars, clean.chars)

    def test_sample_document(self):
        doc = ROOT / "decks/2026-10-01-invoice-ocr-confirm/design/operations.md"
        self.assertEqual(doc_rules(doc, "block"), [])
        self.assertEqual(doc_rules(doc, "warning"), [])


class TempDoc(unittest.TestCase):
    """一時フォルダに設計書（と claims.csv・原文）を書いて検査する土台。"""

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.dir = Path(self.tmp.name)

    def tearDown(self):
        self.tmp.cleanup()

    def doc(self, text: str, claims_csv: str = "", source: str = "") -> Path:
        (self.dir / "design").mkdir(exist_ok=True)
        if claims_csv:
            (self.dir / "claims.csv").write_text(claims_csv, encoding="utf-8")
        if source:
            (self.dir / "design/_source").mkdir(exist_ok=True)
            (self.dir / "design/_source/doc.md").write_text(source, encoding="utf-8")
        path = self.dir / "design/doc.md"
        path.write_text(text, encoding="utf-8")
        return path

    def messages(self, path: Path, rule: str) -> list[str]:
        return [i.message for i in check_doc.check_document(path) if i.rule == rule]


class Restatement(TempDoc):
    """同じ数値・全行が同じ列・長い §1・§1 の外の [要確認]・本文に見えている主張ID・原文の中身から決める上限。"""

    CLAIMS = ("id,doc,section,claim,status,evidence,owner,target,note\n"
              "C1,運用設計,§2,手入力から OCR に変える,決定,定例 2026-09-20,経理課,doc,\n"
              "C2,運用設計,§6,上限の数値,未決,,経理課長,doc,\n")

    def test_same_number_three_times(self):
        path = self.doc("# 題\n\n## 1. 要点\n\n評価用の質問300件で測る。\n\n"
                        "## 2. 評価\n\n| 項目 | 件数 | 時期 |\n|---|---|---|\n| 評価 | 300件 | 試行後 |\n\n"
                        "質問300件のうち誤りを数える。試行は1か月、並行も1か月、定常も1か月。\n")
        found = self.messages(path, "restated-number")
        self.assertEqual(len(found), 1)
        self.assertIn("300件×3", found[0])
        self.assertNotIn("1か月", found[0])            # 「1」は別々の事実で重なりやすいので数えない

    def test_column_with_one_value(self):
        path = self.doc("# 題\n\n## 1. 要点\n\n| 項目 | 決める担当 | 決め方 |\n|---|---|---|\n"
                        "| 上限 | 経理課長 | 本人に確認 |\n| 誤り率 | 情報システム課 | 本人に確認 |\n| 時間 | 経理課 | 本人に確認 |\n")
        found = self.messages(path, "same-column")
        self.assertEqual(len(found), 1)
        self.assertIn("決め方", found[0])

    def test_long_summary(self):
        body = "経理課が「保留」の項目を毎日20分で確かめ、週次で誤りの記録を30分で見直す。" * 10
        path = self.doc(f"# 題\n\n## 1. 要点\n\n{body}\n\n{body}\n\n## 2. 運用\n\n| 周期 | 作業 | 担当 |\n|---|---|---|\n"
                        "| 日次 | 確認 | 経理課 |\n| 週次 | 見直し | 経理課 |\n| 月次 | 評価 | 情報システム課 |\n")
        self.assertEqual(len(self.messages(path, "summary-long")), 1)

    def test_tbd_outside_summary(self):
        path = self.doc("# 題\n\n## 1. 要点\n\n| 項目 | 担当 | 決め方 |\n|---|---|---|\n| 上限 [要確認] | 経理課長 | 実測 |\n\n"
                        "## 2. 体制\n\n| 担当 | 役割 | 工数 |\n|---|---|---|\n| 経理課 | 確認 | [要確認] |\n")
        found = check_doc.check_document(path)
        tbd = [i for i in found if i.rule == "tbd-outside-summary"]
        self.assertEqual(len(tbd), 1)
        self.assertEqual(tbd[0].line, 13)

    def test_visible_claim_ids(self):
        path = self.doc("# 題\n\n## 1. 要点\n\n| 項目 | 担当 | 決め方 |\n|---|---|---|\n| 上限の数値（C2） | 経理課長 | 実測 |\n\n"
                        "## 2. 全体像\n\n| | 現行 | 変更後 |\n|---|---|---|\n| 入力 | 手入力 | OCR（C1） |\n", self.CLAIMS)
        found = self.messages(path, "claim-id-visible")
        self.assertEqual(len(found), 1)
        self.assertIn("C1（決定", found[0])
        self.assertIn("C2（未決", found[0])             # 未決も本文に見せない（読み手は claims.csv を見ない）
        hidden = self.doc("# 題\n\n## 1. 要点\n\n| 項目 | 担当 | 決め方 |\n|---|---|---|\n| 上限の数値 | 経理課長 | 実測 |\n\n<!-- claims: C2 -->\n\n"
                          "## 2. 全体像\n\n| | 現行 | 変更後 |\n|---|---|---|\n| 入力 | 手入力 | OCR |\n\n<!-- claims: C1 -->\n")
        self.assertEqual(self.messages(hidden, "claim-id-visible"), [])
        self.assertEqual(self.messages(hidden, "claims-unused"), [])    # コメントに書いた ID も「載せた」に数える

    def test_read_limit_from_core(self):
        filler = "\n\n".join(["関係者が密に連携し、継続的に改善することが重要である。"] * 12)
        info = "経理課が「保留」の項目を毎日確かめ、情報システム課が月次で閾値を評価する。"
        source = f"# 原文\n\n## 1. 概要\n\n{info}\n\n{filler}\n"
        _, m0, _ = verbosity.analyze(self.doc("# 仮\n", source=source).parent / "_source/doc.md", siblings=False)
        self.assertGreater(m0.cut, m0.core)                       # 原文の大半が削除候補
        self.assertAlmostEqual(m0.read_limit(), m0.core * 1.5)    # 上限は中身の1.5倍（原文より小さい）
        rewrite = f"# 題\n\n## 1. 要点\n\n{info}\n\n## 2. 運用\n\n{info.replace('経理課が', '担当の経理課が')}\n\n" \
                  "## 3. 体制\n\n経理課と情報システム課の2つの課が、上の確認と評価をそれぞれ受け持つ。\n"
        path = self.doc(rewrite)
        _, m1, _ = verbosity.analyze(path, siblings=False)
        self.assertLess(m1.read, m0.read)                         # 原文よりは短いが
        self.assertEqual(len(self.messages(path, "read-growth")), 1)   # 中身の1.5倍を超える

    def test_column_all_blank(self):
        path = self.doc("# 題\n\n## 1. 要点\n\n| 項目 | 決める担当 | 決め方 |\n|---|---|---|\n"
                        "| 上限 | 経理課長 | |\n| 誤り率 | 情報システム課 | |\n| 時間 | 経理課 | |\n")
        found = self.messages(path, "same-column")
        self.assertEqual(len(found), 1)
        self.assertIn("空欄", found[0])

    def test_halfwidth_label_hint(self):
        path = self.doc("# 題\n\n## 1. 図\n\n```mermaid\nflowchart LR\n  A[スコアが<br>0.7以上] -->|原文 §3| B[0.5以上0.7未満]\n"
                        "  B --> C[3回連続]\n```\n")
        hints = [i for i in check_doc.check_document(path) if i.rule == "mermaid-halfwidth"]
        self.assertEqual(len(hints), 1)
        self.assertEqual(hints[0].severity, "warning")           # 2026-10-05 に辺・ノードの両方で欠けが再現したので、止めないが直す
        self.assertEqual(len(self.messages(path, "mermaid-ref-label")), 1)   # 辺のラベル「原文 §3」は章参照。図の下の文に書く
        listed = hints[0].message.split("）は")[0]                # 案内文の例を除いた、列挙したラベルの部分
        self.assertIn("原文 §3", listed)
        self.assertIn("0.5以上0.7未満", listed)
        self.assertNotIn("スコアが", listed)                    # 全角だけの行が一番長ければ見ない
        self.assertNotIn("3回連続", listed)                     # 半角1字は見ない

    def test_figure_first_only_for_long_documents(self):
        para = "経理課が「保留」の項目を毎日20分で確かめ、週次で誤りの記録を30分で見直す。情報システム課は月次で閾値を評価する。"
        long_doc = "# 題\n\n## 1. 要点\n\n" + "\n\n".join(para.replace("毎日", f"{i}日目に") for i in range(30)) + "\n\n## 2. 運用\n\n本文。\n"
        self.assertGreaterEqual(verbosity.analyze(self.doc(long_doc), siblings=False)[1].read, 1500)
        self.assertEqual(len(self.messages(self.doc(long_doc), "figure-first")), 2)
        self.assertEqual(self.messages(self.doc("# 題\n\n## 1. 要点\n\n短い本文。\n"), "figure-first"), [])

    def test_figure_after_multiline_comment(self):
        path = self.doc("# 題\n\n## 1. 要点\n\n<!-- 1行目\n     2行目 -->\n\n| 項目 | 要点 | 正本 |\n|---|---|---|\n| 変更 | OCR | §1 |\n")
        self.assertEqual(self.messages(path, "figure-first"), [])

    def test_action_sentence_is_not_a_deletion_candidate(self):
        path = self.doc("# 題\n\n## 1. 要点\n\n必要に応じてモデルを再学習する。\n\n継続的に改善することが重要である。\n\n"
                        "止まった期間の入力を再抽出して取り込みを再実行する必要がある。\n\n品質の向上を継続的に推進する。\n")
        issues = check_doc.check_document(path)
        self.assertEqual(sorted(i.line for i in issues if i.rule == "filler-action"), [5, 9])     # 作業の文は warning
        self.assertEqual(sorted(i.line for i in issues if i.rule == "filler-only"), [7, 11])      # 一般論だけ（「を推進する」も）は block
        _, metrics, cands = verbosity.analyze(path, siblings=False)
        self.assertEqual(metrics.candidates, 2)                                                  # 作業の文は削れる量に入れない
        self.assertTrue(any("作業の文" in why for _, why in cands))

    def test_read_limit_excludes_figure_labels(self):
        info = "経理課が「保留」の項目を毎日20分で確かめ、情報システム課が月次で閾値を評価する。"
        source = "# 原文\n\n## 1. 概要\n\n" + "\n\n".join(info.replace("毎日", f"{i}日目に") for i in range(8)) + "\n"
        fig = "\n\n```mermaid\nflowchart LR\n  A[取り込み] --> B[読み取り] --> C[「保留」の確認]\n```\n"
        same = self.doc(source.replace("# 原文", "# 題") + fig, source=source)
        self.assertEqual(self.messages(same, "read-growth"), [])          # 図を足しても上限を超えない
        more = self.doc(source.replace("# 原文", "# 題") + fig + f"\n{info}\n", source=source)
        self.assertEqual(len(self.messages(more, "read-growth")), 1)     # 文章を足せば超える
        self.assertIn("図を除く", self.messages(more, "read-growth")[0])

    def test_tbd_allowed_in_appendix(self):
        path = self.doc("# 題\n\n## 1. 要点\n\n| 項目 | 担当 | 決め方 |\n|---|---|---|\n| 上限 [要確認] | 経理課長 | 実測 |\n\n"
                        "## 付録C 未決の一覧\n\n| 項目 | 担当 |\n|---|---|\n| 通知の経路 [要確認] | 原文に無い |\n")
        self.assertEqual(self.messages(path, "tbd-outside-summary"), [])


def para(i: int) -> str:
    """数字と担当を含む、削除候補にならない段落（約70字）。"""
    return (f"経理課が{i}日目に「保留」の項目を{10 + i}分で確かめ、週次で誤りの記録を見直す。"
            "情報システム課は月次で閾値を評価し、承認を経て反映する。")


def table(rows: int, head: str = "| 要件 | 内容 | 本書の章 |", cell: str = "RQ-{i:02d} | 請求書の項目{i}を読み取る | §3") -> str:
    return "\n".join([head, "|---|---|---|"] + [f"| {cell.format(i=i)} |" for i in range(1, rows + 1)])


class Structure(TempDoc):
    """構造（structure.py）: 前置き・§1・引く表の位置・章の型・読み通す量・読む人・未決の位置・参照する段落の割合・要件ID。"""

    def test_front_matter_summary_reference_and_ids(self):
        meta = "\n\n".join(f"本書は、請求書の取り込みの運用について第{i}の観点から説明する。本節の読み方と記法は次のとおりであり、本書の構成は付録に示す。"
                           for i in range(1, 17))
        body = "\n\n".join(para(i) for i in range(10))
        doc = self.doc(f"# 題\n\n## 1. 位置づけと読み方\n\n{meta}\n\n## 2. 本書が満たす運用要件\n\n{table(12)}\n\n## 3. 日常の運用\n\n{body}\n")
        found = check_doc.check_document(doc)
        rules = {i.rule: i.message for i in found if i.rule in structure.RULES}
        self.assertIn("§3 日常の運用", rules["front-matter-long"])            # 中身が始まるまでに1000字超
        self.assertIn("文書の説明", rules["summary-missing"])               # §1 が位置づけ
        self.assertIn("§2 本書が満たす運用要件", rules["reference-in-path"])  # 引く表の章（表100%・12行）が §3 の前にある
        self.assertIn("RQ-01", rules["opaque-id"])                          # 要件IDが本文に12回
        kinds = [c.kind for c in structure.analyze(doc)[2]]
        self.assertEqual(kinds, ["前置き", "引く表", "本文"])
        # 表を付録へ移し、§1 を要点（4項目）にすれば消える
        fixed = self.doc(f"# 題\n\n## 1. 要点\n\n| 項目 | 要点 |\n|---|---|\n| 何を変えるか | 手入力を OCR に |\n"
                         "| 次へ進む条件 | 読み誤りが手入力以下（原文に無い） |\n| まだ決めていない点 | 2点 |\n| 決めたこと | 原文に決定は無い |\n\n"
                         f"## 2. 日常の運用\n\n{body}\n\n## 付録A 原文の要件表との対応\n\n{table(12)}\n")
        self.assertEqual([i.rule for i in check_doc.check_document(fixed) if i.rule in structure.RULES], [])

    def test_summary_is_judged_by_content_not_title(self):
        body = "\n\n".join(para(i) for i in range(24))
        four = ("| 項目 | 要点 |\n|---|---|\n| 何を変えるか | 手入力を OCR に変える |\n| 次へ進む条件 | 読み誤りが手入力以下（原文に無い） |\n"
                "| まだ決めていない点 | 2点 |\n| 決めたこと | 方式の変更（経理部長、2026-09-20） |\n")
        empty_title = self.doc(f"# 題\n\n## 1. 要点\n\n本書の要点を示す。\n\n## 2. 運用\n\n{body}\n")
        found = self.messages(empty_title, "summary-items")
        self.assertEqual(len(found), 1)                                    # 題を「要点」にしても中身が無ければ通らない
        self.assertIn("次へ進む条件", found[0])
        self.assertIn("決めたこと", found[0])
        self.assertEqual(self.messages(empty_title, "summary-missing"), [])
        meta_title = self.doc(f"# 題\n\n## 1. 位置づけと読み方\n\n{four}\n## 2. 運用\n\n{body}\n")
        self.assertEqual(self.messages(meta_title, "summary-items"), [])  # 4つの要点が揃っていれば題が「位置づけ」でも要点
        self.assertEqual(self.messages(meta_title, "summary-missing"), [])
        self.assertEqual(structure.analyze(meta_title)[2][0].kind, "要点")
        short = self.doc("# 題\n\n## 1. 要点\n\n本書の要点を示す。\n\n## 2. 運用\n\n" + para(1) + "\n")
        self.assertEqual(self.messages(short, "summary-items"), [])       # 短い文書には求めない

    def test_reference_chapter_by_ids_and_reading_guide_by_content(self):
        rows = table(8, cell="RQ-{i:02d} | 請求書の項目{i}を読み取る | §4") + "\n\n" + table(6, cell="RQ-1{i} | 明細{i}を読み取る | §4")
        guide = "\n\n".join(["読み方は次のとおりである。確定していない箇所には [測定待ち] の印を付ける。",
                             "各章の末尾に関連文書を示す。記法は付録の凡例に従う。", "読者は担当者と承認者である。"])
        body = "\n\n".join(para(i) for i in range(20))
        doc = self.doc(f"# 題\n\n## 1. 要点\n\n| 項目 | 要点 |\n|---|---|\n| 変更 | OCR |\n\n## 2. 本書の前提\n\n{guide}\n\n"
                       f"## 3. 本書が満たす運用要件\n\n{rows}\n\n## 4. 日常の運用\n\n{body}\n")
        kinds = [c.kind for c in structure.analyze(doc)[2]]
        self.assertEqual(kinds, ["要点", "前置き", "引く表", "本文"])    # 読み方の章は語で、要件の章は行の合計と ID で拾う
        found = self.messages(doc, "reference-in-path")
        self.assertEqual(len(found), 1)
        self.assertIn("14行・要件ID 14回", found[0])

    def test_same_shape_and_path_long(self):
        def chapter(n: int, parts: int = 20) -> str:
            return (f"## {n}. 章{n}\n\n{para(n)}\n\n| 周期 | 作業 | 担当 |\n|---|---|---|\n| 日次 | 確認 | 経理課 |\n| 週次 | 見直し | 経理課 |\n\n"
                    + "\n\n".join(para(n * 100 + i) for i in range(parts)))
        doc = self.doc("# 題\n\n## 1. 要点\n\n| 項目 | 要点 |\n|---|---|\n| 何を変えるか | OCR |\n\n" + "\n\n".join(chapter(n) for n in range(2, 7)) + "\n")
        same = self.messages(doc, "same-shape")
        self.assertEqual(len(same), 1)
        self.assertIn("§2〜§6 の5章が同じ型「文→表→文」で始まる", same[0])
        # 末尾が違っても（§4 だけ箇条書きで終わる）、先頭3要素が同じなら同じ型
        tail = self.doc(doc.read_text(encoding="utf-8").replace(f"{para(400 + 19)}\n", f"{para(400 + 19)}\n\n- 補足1\n- 補足2\n"))
        self.assertIn("5章", self.messages(tail, "same-shape")[0])
        long = self.messages(doc, "path-long")
        self.assertEqual(len(long), 1)
        self.assertIn("> 6000字", long[0])
        # 3章目を図から始めれば連続は2章で止まる
        varied = self.doc("# 題\n\n## 1. 要点\n\n| 項目 | 要点 |\n|---|---|\n| 何を変えるか | OCR |\n\n" + chapter(2) + "\n\n"
                          + chapter(3).replace(f"## 3. 章3\n\n{para(3)}", "## 3. 章3\n\n```mermaid\nflowchart LR\n  A[入力] --> B[判定]\n```\n\n" + para(3))
                          + "\n\n" + chapter(4, 3) + "\n")
        self.assertEqual(self.messages(varied, "same-shape"), [])

    def test_reader_entry(self):
        head = "# 題\n\n| 項目 | 内容 |\n|---|---|\n| 読む人 | {readers} |\n\n## 1. 要点\n\n| 項目 | 要点 |\n|---|---|\n| 変更 | OCR |\n\n## 2. 運用\n\n" + para(1) + "\n"
        self.assertEqual(len(self.messages(self.doc(head.format(readers="経理課・情報システム課の担当者。可否を判断する人は §1 だけ")), "reader-entry")), 1)
        self.assertEqual(self.messages(self.doc(head.format(readers="経理課（§2）・情報システム課（§2〜§3）の担当者")), "reader-entry"), [])
        self.assertEqual(self.messages(self.doc(head.format(readers="経理課の担当者")), "reader-entry"), [])

    def test_undecided_list_at_end(self):
        body = lambda n: "\n\n".join(para(n * 10 + i) for i in range(6))                    # noqa: E731
        doc = self.doc(f"# 題\n\n## 1. 要点\n\n| 項目 | 要点 |\n|---|---|\n| 変更 | OCR |\n\n"
                       f"## 2. 運用\n\n通知の経路は未確定である（§4）。\n\n{body(2)}\n\n"
                       f"## 3. 判断\n\n閾値は未確定である（§4）。\n\n{body(3)}\n\n待つ時間の上限も未確定である（§4）。\n\n"
                       "## 4. 未確定の事項\n\n| 項目 | 担当 |\n|---|---|\n| 通知の経路 | 原文に無い |\n| 閾値 | 情報システム課 |\n| 待つ時間 | 経理課 |\n")
        found = self.messages(doc, "undecided-at-end")
        self.assertEqual(len(found), 1)
        self.assertIn("3回参照", found[0])
        early = self.doc("# 題\n\n## 1. 要点\n\n| 項目 | 要点 |\n|---|---|\n| 変更 | OCR |\n\n### 1.1 まだ決めていない点\n\n"
                         "| 項目 | 担当 |\n|---|---|\n| 通知の経路 | 原文に無い |\n\n## 2. 運用\n\n通知の経路は未決（§1.1）。\n\n"
                         "## 3. 判断\n\n閾値は未決（§1.1）。待つ時間も未決（§1.1）。\n")
        self.assertEqual(self.messages(early, "undecided-at-end"), [])

    def test_summary_rows(self):
        rows = "\n".join(f"| 項目{i} | 経理課 | 実測{i} |" for i in range(9))
        doc = self.doc(f"# 題\n\n## 1. 要点\n\n### 1.1 まだ決めていない点\n\n| 項目 | 担当 | 決め方 |\n|---|---|---|\n{rows}\n\n## 2. 運用\n\n{para(1)}\n")
        found = self.messages(doc, "summary-rows")
        self.assertEqual(len(found), 1)
        self.assertIn("9行", found[0])

    def test_reference_share(self):
        hop = "詳細は §{n} を見る。"
        doc = self.doc("# 題\n\n## 1. 要点\n\n| 項目 | 要点 |\n|---|---|\n| 変更 | OCR |\n\n"
                       + "\n\n".join(f"## {n}. 章{n}\n\n{hop.format(n=n % 3 + 2)}\n\n{para(n)}{hop.format(n=n % 3 + 2)}\n\n{para(n + 10)}基本設計 §{n} も見る。"
                                     for n in range(2, 5)) + "\n")
        found = self.messages(doc, "ref-share")
        self.assertEqual(len(found), 1)
        self.assertIn("67%（6/9）", found[0])                 # 他の文書への参照（基本設計 §n）は数えない
        external = self.doc("# 題\n\n## 1. 要点\n\n| 項目 | 要点 |\n|---|---|\n| 変更 | OCR |\n\n"
                            + "\n\n".join(f"## {n}. 章{n}\n\n{para(n)}基本設計 §{n} を見る。\n\n{para(n + 10)}未決（§1.1）。" for n in range(2, 5)) + "\n")
        self.assertEqual(self.messages(external, "ref-share"), [])

    def test_sample_document_structure(self):
        _, pre, chapters = structure.analyze(ROOT / "decks/2026-10-01-invoice-ocr-confirm/design/operations.md")
        self.assertEqual([c.kind for c in chapters], ["要点", "本文", "本文", "本文", "本文", "本文", "付録", "付録"])
        self.assertEqual(chapters[0].shape, "表")
        self.assertTrue(chapters[3].shape.startswith("図→"))
        report = structure.report(Path("x.md"), pre, chapters, [])
        self.assertIn("| §5 移行の進め方と体制 |", report)
        self.assertIn("構造の warning なし", report)


if __name__ == "__main__":
    unittest.main()


class Figures(TempDoc):
    """図の形・ラベルの長さ・共通の色・図の下の題・init の版（実際の設計書の図の問題を架空の題材で再現した fixtures）。"""

    FIGS = FIX / "design/figures"

    def fig_doc(self, *names: str, caption: bool = True) -> Path:
        parts = ["# 題\n\n## 1. 図\n"]
        for n in names:
            parts.append("```mermaid\n" + (self.FIGS / f"{n}.mmd").read_text(encoding="utf-8").rstrip() + "\n```\n")
            if caption:
                parts.append("図1 題\n")
        return self.doc("\n".join(parts))

    def rules(self, path: Path) -> list[str]:
        return sorted(i.rule for i in check_doc.check_document(path) if i.rule.startswith("mermaid"))

    def test_rows_without_flow_become_a_table(self):
        for name in ("before-cycles", "before-alert-levels"):
            msgs = self.messages(self.fig_doc(name), "mermaid-shape")
            self.assertEqual(len(msgs), 1, name)
            self.assertIn("表にする", msgs[0])

    def test_straight_line_becomes_a_numbered_list(self):
        msgs = self.messages(self.fig_doc("before-release"), "mermaid-shape")
        self.assertEqual(len(msgs), 1)
        self.assertIn("一本道（6個）", msgs[0])

    def test_branching_figures_are_kept(self):
        for name in ("before-fallback", "before-triage", "before-migration"):
            self.assertEqual(self.messages(self.fig_doc(name), "mermaid-shape"), [], name)

    def test_long_labels_and_sentences(self):
        msgs = self.messages(self.fig_doc("before-alert-levels"), "mermaid-label")
        self.assertEqual(len(msgs), 2)                                      # 長い行と「。」の2文
        self.assertTrue(any("読み取りの停止。" in m for m in msgs))
        edge = self.messages(self.fig_doc("before-triage"), "mermaid-label")
        self.assertTrue(any(">8字" in m for m in edge))                     # 辺の長い条件

    def test_redesigned_figures_pass(self):
        for name in ("after-fallback", "after-triage", "after-migration", "after-release"):
            self.assertEqual(self.rules(self.fig_doc(name)), [], name)

    def test_subgraph_membership_connects_flows(self):
        # まとまり（subgraph）どうしの矢印でつながる3つの流れは、ばらばらの行の並びではない
        self.assertEqual(self.messages(self.fig_doc("after-release"), "mermaid-shape"), [])

    def test_caption_required(self):
        path = self.fig_doc("after-migration", caption=False)
        self.assertEqual(self.rules(path), ["mermaid-caption"])
        ok = self.doc("# 題\n\n## 1. 図\n\n```mermaid\nflowchart LR\n  A --> B\n```\n\n<!-- メモ -->\n\n> 図2 説明\n")
        self.assertEqual(self.messages(ok, "mermaid-caption"), [])

    def test_custom_colors(self):
        text = (self.FIGS / "after-migration.mmd").read_text(encoding="utf-8") + "  classDef ai stroke:#d1495b\n  style P1 fill:#f00\n"
        path = self.doc(f"# 題\n\n## 1. 図\n\n```mermaid\n{text}```\n\n図1 題\n")
        msgs = self.messages(path, "mermaid-classdef")
        self.assertEqual(len(msgs), 1)
        self.assertIn("classDef ai", msgs[0])
        self.assertIn("style P1", msgs[0])

    def test_outdated_init(self):
        old = ('%%{init: {"theme": "base", "flowchart": {"padding": 24, "htmlLabels": false}, '
               '"themeVariables": {"fontSize": "16px"}}}%%')
        path = self.doc(f"# 題\n\n## 1. 図\n\n```mermaid\n{old}\nflowchart LR\n  A --> B\n```\n\n図1 題\n")
        msgs = self.messages(path, "mermaid-theme")
        self.assertEqual(len(msgs), 1)
        self.assertIn("古い版", msgs[0])

    def test_printed_init_and_classes(self):
        self.assertIn('"themeCSS": ".edgeLabel rect{opacity:1}"', check_doc.MERMAID_INIT)
        self.assertTrue(check_doc.MERMAID_INIT.startswith('%%{init: {"theme": "base", "fontFamily"'))
        self.assertEqual(check_doc.MERMAID_CLASSES_TEXT.count("classDef "), 5)
