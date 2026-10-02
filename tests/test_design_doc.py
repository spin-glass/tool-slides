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
        self.assertEqual(sorted(set(warnings)), ["heading-number", "mermaid-theme"])   # 短い文書には章ごとの図を求めない

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


class Restatement(unittest.TestCase):
    """同じ数値・全行が同じ列・長い §1・§1 の外の [要確認]・本文に見えている主張ID・原文の中身から決める上限。"""

    CLAIMS = ("id,doc,section,claim,status,evidence,owner,target,note\n"
              "C1,運用設計,§2,手入力から OCR に変える,決定,定例 2026-09-20,経理課,doc,\n"
              "C2,運用設計,§6,上限の数値,未決,,経理課長,doc,\n")

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
        self.assertEqual(hints[0].severity, "info")              # 欠けない場合もあるので止めない
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


if __name__ == "__main__":
    unittest.main()
