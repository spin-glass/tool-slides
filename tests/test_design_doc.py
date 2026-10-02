"""design-doc スキルの検査（check_doc.py / claims.py）と、slides の lint の確認型の規則を fixtures で確かめる。

    python3 -m unittest discover -s tests -v
"""
import sys
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
        self.assertEqual(sorted(set(warnings)), ["figure-first", "heading-number", "mermaid-theme"])

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


if __name__ == "__main__":
    unittest.main()
