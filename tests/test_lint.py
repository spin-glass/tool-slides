"""lint_slides.py の検査が fixtures で期待どおりに出ることを確かめる。

    python3 -m unittest discover -s tests -v
"""
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / ".claude/skills/slides/scripts"))
import lint_slides as lint  # noqa: E402

NG = lint.load_ng_words()


def rules(name: str, severity: str) -> list[str]:
    deck = lint.parse_deck(ROOT / "tests/fixtures" / name)
    return [i.rule for i in lint.check_deck(deck, NG) if i.severity == severity]


class Fixtures(unittest.TestCase):
    def test_violations(self):
        blocks = rules("violations.qmd", "block")
        for rule in ("gate-missing", "title-label", "bullets", "placeholder", "title-taigen", "code-lines",
                     "budget", "body-chars", "title-length", "title-missing"):
            self.assertIn(rule, blocks)
        warnings = rules("violations.qmd", "warning")
        for rule in ("hedge", "hedge-density", "buzzword"):
            self.assertIn(rule, warnings)

    def test_ghost_body(self):
        self.assertEqual(rules("ghost_with_body.qmd", "block"), ["ghost-body"])

    def test_images(self):
        self.assertEqual(rules("image_checks.qmd", "block"), ["image-missing"])
        self.assertEqual(sorted(rules("image_checks.qmd", "warning")), ["fig-alt", "image-alt"])

    def test_decided_by_is_optional_meta(self):
        deck = lint.parse_deck(ROOT / "tests/fixtures/image_checks.qmd")
        self.assertIn("decided-by", deck.meta)
        self.assertIn("決めた人", lint.title_list(deck))


class Decks(unittest.TestCase):
    def test_committed_decks_pass(self):
        for qmd in lint.all_decks(ROOT):
            with self.subTest(deck=qmd.parent.name):
                issues = lint.check_deck(lint.parse_deck(qmd), NG)
                self.assertEqual([i.fmt(qmd) for i in issues if i.severity == "block"], [])


class Helpers(unittest.TestCase):
    def test_zen_len(self):
        self.assertEqual(lint.zen_len("犬6枚"), 2.5)

    def test_quoted_words_are_not_hedges(self):
        deck = lint.parse_deck(ROOT / "decks/2026-09-30-ai-slides-verbosity/index.qmd")
        self.assertNotIn("hedge", [i.rule for i in lint.check_deck(deck, NG)])


if __name__ == "__main__":
    unittest.main()
