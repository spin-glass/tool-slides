"""design-doc の構造の検査のうち、本文のレビュー（2026-10-06）から足した3つを確かめる。

    .venv/bin/python -m unittest discover -s tests -v
"""
import re
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / ".claude/skills/design-doc/scripts"))
import structure  # noqa: E402

FIXTURE = ROOT / "tests/fixtures/design_review/patterns.md"
NEW_RULES = ("bold-lead", "figure-dup", "appendix-scatter")


def found(path: Path) -> dict[str, tuple[int, str]]:
    findings, _, _ = structure.analyze(path)
    return {f.rule: (f.line, f.message) for f in findings if f.rule in NEW_RULES}


class ReviewPatterns(unittest.TestCase):
    def test_patterns_are_found(self):
        got = found(FIXTURE)
        self.assertEqual(sorted(got), sorted(NEW_RULES))
        lines = FIXTURE.read_text(encoding="utf-8").splitlines()
        self.assertTrue(lines[got["bold-lead"][0] - 1].startswith("**"))       # 最初の太字の段落を指す
        self.assertTrue(lines[got["figure-dup"][0] - 1].startswith("```mermaid"))
        self.assertIn("付録B×6", got["appendix-scatter"][1])

    def test_fixed_document_is_quiet(self):
        text = FIXTURE.read_text(encoding="utf-8")
        text = re.sub(r"```mermaid.*?```\n", "", text, flags=re.S)             # 表と同じ図を消す
        text = re.sub(r"^\*\*(.+?)\*\*", r"\1", text, flags=re.M)              # 段落の頭の太字を外す
        text = text.replace("切替は精度検証の条件を満たしてから行う。",
                            "切替は精度検証の条件を満たしてから行う。まだ決めていない点は3件（付録B）。")
        with tempfile.TemporaryDirectory() as d:
            fixed = Path(d) / "patterns.md"
            fixed.write_text(text, encoding="utf-8")
            self.assertEqual(found(fixed), {})

    def test_figure_with_branches_but_different_words_is_not_a_duplicate(self):
        doc = ("# 架空\n\n## 1. 要点\n\n変える。\n\n## 2. 判定\n\n```mermaid\nflowchart LR\n"
               '  A["音を受け取る"] --> B{"閾値を超える"}\n  B -->|"はい"| C["保全課へ通知"]\n  B -->|"いいえ"| D["記録だけ残す"]\n'
               "```\n\n| 周期 | 見るもの | 扱い |\n|---|---|---|\n| 毎時 | 判定の成否 | 失敗で通知 |\n"
               "| 日次 | 誤通知 | 確認 |\n| 月次 | 見逃し | レビュー |\n")
        with tempfile.TemporaryDirectory() as d:
            p = Path(d) / "doc.md"
            p.write_text(doc, encoding="utf-8")
            self.assertNotIn("figure-dup", found(p))

    def test_committed_documents_stay_quiet(self):
        docs = [ROOT / "decks/2026-10-01-invoice-ocr-confirm/design/operations.md",
                ROOT / ".claude/skills/design-doc/templates/design_doc.md", *sorted((ROOT / "tests/fixtures/design").glob("*.md"))]
        for doc in docs:
            with self.subTest(doc=doc.name):
                self.assertEqual(found(doc), {})


if __name__ == "__main__":
    unittest.main()
