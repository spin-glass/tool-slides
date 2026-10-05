"""lint_slides.py の検査が fixtures で期待どおりに出ることを確かめる。

    python3 -m unittest discover -s tests -v
"""
import subprocess
import sys
import tempfile
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
        self.assertEqual(sorted(rules("image_checks.qmd", "block")), ["hand-count", "image-missing"])
        warnings = [r for r in rules("image_checks.qmd", "warning") if r != "type-missing"]   # 型は test_slide_types で見る
        self.assertEqual(sorted(warnings), ["fig-alt", "image-absolute", "image-alt", "pick-rule"])

    def test_hand_counts_in_image_decks(self):
        deck = lint.parse_deck(ROOT / "tests/fixtures/hand_counts.qmd")
        found = [i for i in lint.check_deck(deck, NG) if i.rule == "hand-count"]
        self.assertEqual(len(found), 1)                      # インライン式・「1枚ずつ」「1枚目」・タイトルは見ない
        self.assertIn("10枚", found[0].message)

    def test_slide_types(self):
        deck = lint.parse_deck(ROOT / "tests/fixtures/slide_types.qmd")
        found = {(i.rule, i.slide.index) for i in lint.check_deck(deck, NG) if i.rule.startswith(("type-", "inline-"))}
        self.assertEqual(found, {("type-markup", 2), ("type-unknown", 3), ("type-multiple", 4),
                                 ("type-missing", 5), ("inline-style", 6)})
        self.assertEqual(sorted(rules("slide_types.qmd", "block")), ["type-multiple", "type-unknown"])
        self.assertIn("型: pair", lint.title_list(deck))

    def test_committed_decks_choose_types(self):
        for qmd in lint.all_decks(ROOT):
            with self.subTest(deck=qmd.parent.name):
                issues = lint.check_deck(lint.parse_deck(qmd), NG)
                self.assertEqual([i.fmt(qmd) for i in issues if i.rule.startswith("type-")], [])

    def test_decided_by_is_optional_meta(self):
        deck = lint.parse_deck(ROOT / "tests/fixtures/image_checks.qmd")
        self.assertIn("decided-by", deck.meta)
        self.assertIn("決めた人", lint.title_list(deck))



def deck_text(body: str, budget: int = 2, status: str = "approved", action: str = "試す") -> str:
    return (f"---\ntitle: t\n---\n\n<!-- audience: 試し -->\n<!-- action: {action} -->\n<!-- minutes: 3 -->\n"
            f"<!-- budget: {budget} -->\n<!-- status: {status} -->\n\n" + body)


TWO = "## 一つ目の枚は短い事実を述べる\n\n<!-- type: text -->\n\n- 事実\n\n## 二つ目の枚も短い事実を述べる\n\n<!-- type: text -->\n\n- 事実\n"


class Feedback(unittest.TestCase):
    """2026-10-05 の利用者の指摘: <style> を字数に数える、承認後の budget・タイトルの変更、選ぶ枚の図、標本の宣言。"""

    def setUp(self):
        self.dir = Path(tempfile.mkdtemp())

    def write(self, text: str) -> Path:
        path = self.dir / "index.qmd"
        path.write_text(text, encoding="utf-8")
        return path

    def rules(self, path: Path, severity: str, baseline=None) -> list[str]:
        return [i.rule for i in lint.check_deck(lint.parse_deck(path), NG, baseline) if i.severity == severity]

    def git(self, *args):
        subprocess.run(["git", *args], cwd=self.dir, check=True, capture_output=True)

    def test_style_blocks_are_not_body_text(self):
        css = "\n".join(f".reveal .pair > div:nth-child({n}) {{ border-left: 6px solid #b35900; padding-left: 24px; }}"
                        for n in range(12))
        path = self.write(deck_text(TWO.replace("- 事実\n\n## 二つ目", f"- 事実\n\n<style>\n{css}\n</style>\n\n## 二つ目", 1)))
        deck = lint.parse_deck(path)
        self.assertNotIn("body-chars", self.rules(path, "block"))
        self.assertEqual(len(deck.slides[0].raw_html), 14)                  # <style>〜</style> は本文に入れない
        self.assertEqual(len(deck.slides[0].body), 1)

    def test_budget_and_titles_changed_after_approval(self):
        path = self.write(deck_text(TWO))
        self.git("init", "-q")
        self.git("add", ".")
        self.git("-c", "user.email=t@example.com", "-c", "user.name=t", "commit", "-qm", "approved")
        three = TWO + "## 三つ目の枚を後から足した\n\n<!-- type: text -->\n\n- 事実\n"
        path.write_text(deck_text(three, budget=3), encoding="utf-8")
        base = lint.approved_baseline(path)
        self.assertIsNotNone(base)
        self.assertIn("budget-changed", self.rules(path, "block", base))
        self.assertIn("approved-title-changed", self.rules(path, "warning", base))
        path.write_text(deck_text(three, budget=3) + "\n<!-- reapproved: 本人「3枚目を足してよい」 2026-10-05 -->\n",
                        encoding="utf-8")
        self.assertNotIn("budget-changed", self.rules(path, "block", base))      # 承認し直した記録があれば止めない
        self.assertNotIn("approved-title-changed", self.rules(path, "warning", base))
        path.write_text(deck_text(three, budget=3) + "\n<!-- reapproved: 承認済み -->\n", encoding="utf-8")
        self.assertIn("budget-changed", self.rules(path, "block", base))         # 本人の原文と日付が無い記録は見ない

    def test_choice_deck_needs_evidence_on_the_last_slide(self):
        body = TWO.replace("## 二つ目の枚も短い事実を述べる", "## 案Bを選ぶ")
        path = self.write(deck_text(body, action="案Aと案Bのどちらを採るか選ぶ"))
        self.assertIn("action-evidence", self.rules(path, "warning"))
        table = body.replace("## 案Bを選ぶ\n\n<!-- type: text -->\n\n- 事実",
                             "## 案Bを選ぶ\n\n<!-- type: table -->\n\n| 案 | 誤り |\n|---|---|\n| A | 9 |\n| B | 4 |")
        path.write_text(deck_text(table, action="案Aと案Bのどちらを採るか選ぶ"), encoding="utf-8")
        self.assertNotIn("action-evidence", self.rules(path, "warning"))
        path.write_text(deck_text(body, action="次の資料で試す"), encoding="utf-8")
        self.assertNotIn("action-evidence", self.rules(path, "warning"))   # 選ぶデッキでなければ見ない

    def test_denominator_is_declared_on_every_slide_with_numbers(self):
        body = ('## 人手で分類し直した写真では、誤りが9枚だった {denominator="人手で分類し直した写真"}\n\n'
                "<!-- type: text -->\n\n- 事実\n\n"
                "## 全体の写真では、誤りが30枚だった\n\n<!-- type: text -->\n\n- 事実\n\n"
                "## 日付と出典だけの枚は数字の枚に入れない\n\n<!-- type: text -->\n\n- 2026-09-30 に集計\n\n"
                "[出典: 調査 2024]{.source}\n")
        path = self.write(deck_text(body, budget=3))
        deck = lint.parse_deck(path)
        self.assertEqual(deck.slides[0].denominator, "人手で分類し直した写真")
        self.assertEqual(deck.slides[0].title, "人手で分類し直した写真では、誤りが9枚だった")
        issues = [i for i in lint.check_deck(deck, NG) if i.rule == "denominator-missing"]
        self.assertEqual([i.slide.index for i in issues], [2])
        self.assertIn("標本: 人手で分類し直した写真", lint.title_list(deck))


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
