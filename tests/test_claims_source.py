"""主張の表を出典と照らす検査（claims.py の path・rev・quote）と、claims: required（lint_slides.py）を確かめる。

題材は架空。出典は一時フォルダの git リポジトリに作る。
    .venv/bin/python -m unittest discover -s tests -v
"""
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / ".claude/skills/design-doc/scripts"))
sys.path.insert(0, str(ROOT / ".claude/skills/slides/scripts"))
import claims  # noqa: E402
import lint_slides as lint  # noqa: E402

HEADER = "id,doc,section,claim,status,evidence,owner,target,note,path,rev,quote\n"


def git(repo: Path, *args: str) -> str:
    return subprocess.run(["git", "-C", str(repo), "-c", "user.email=t@example.com", "-c", "user.name=t", *args],
                          capture_output=True, text=True, check=True).stdout.strip()


class SourceChecks(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.repo = Path(self.tmp.name) / "src"
        self.repo.mkdir()
        git(self.repo, "init", "-q")
        self.doc = self.repo / "design.md"
        self.doc.write_text("## 9. 処理\n\n読み取り件数の面では夜間の一括処理で足りる。ただし繁忙期に処理枠を確保できるかは別の問題で、"
                            "専用枠を契約するかは未決である。\n", encoding="utf-8")
        git(self.repo, "add", "-A")
        git(self.repo, "commit", "-q", "-m", "初版")
        self.rev1 = git(self.repo, "rev-parse", "--short", "HEAD")
        self.deck = Path(self.tmp.name) / "deck"
        self.deck.mkdir()

    def tearDown(self):
        self.tmp.cleanup()

    def table(self, body: str) -> list[dict]:
        f = self.deck / "claims.csv"
        f.write_text(HEADER + body, encoding="utf-8")
        return claims.load(f)

    def test_quote_matches_unchanged_source(self):
        rows = self.table(f"C1,設計,§9,読み取り件数の面では夜間の一括処理で足りる,方針,,,deck,,{self.doc},{self.rev1},"
                          "読み取り件数の面では夜間の一括処理で足りる。\n")
        self.assertEqual(claims.validate(rows, self.deck), [])
        self.assertEqual(claims.warnings(rows, self.deck), [])

    def test_changed_source_dropped_qualifier_and_missing_quote(self):
        self.doc.write_text("## 9. 処理\n\n読み取り件数の面では夜間の一括処理で足りる。専用枠は契約する（契約を本線として書く）。\n",
                            encoding="utf-8")
        git(self.repo, "commit", "-q", "-am", "専用枠は契約するを本線にする")
        rows = self.table(f"C1,設計,§9,夜間の一括処理で足りる,方針,,,deck,,{self.doc},{self.rev1},読み取り件数の面では夜間の一括処理で足りる。\n"
                          f"C2,設計,§9,専用枠を契約するかは未決,未決,,設計者,deck,,{self.doc},{self.rev1},専用枠を契約するかは未決である\n"
                          f"C3,設計,§9,夜間の一括処理で足りる,方針,,,deck,,{self.doc},{self.rev1},\n")
        errors = claims.validate(rows, self.deck)
        warns = claims.warnings(rows, self.deck)
        self.assertTrue(any("C1" in e and "source-changed" in e and "1回" in e and "専用枠は契約する" in e for e in errors), errors)
        self.assertTrue(any("C2" in e and "quote-not-found" in e for e in errors), errors)
        self.assertTrue(any("C3" in e and "quote-missing" in e for e in errors), errors)
        self.assertTrue(any("C1" in w and "qualifier-dropped" in w and "の面では" in w for w in warns), warns)

    def test_dirty_source_and_qualifier_words(self):
        self.doc.write_text(self.doc.read_text(encoding="utf-8") + "\n追記。\n", encoding="utf-8")
        rows = self.table(f"C1,設計,§9,読み取り件数の面では夜間の一括処理で足りる,方針,,,deck,,{self.doc},{self.rev1},"
                          "読み取り件数の面では夜間の一括処理で足りる。\n")
        self.assertTrue(any("source-dirty" in w for w in claims.warnings(rows, self.deck)))
        # 「契約」の「約」は限定の語ではない（約は数字の前だけ）
        self.assertEqual([w for w, p in claims.QUALIFIERS if p.search("専用枠を契約する")], [])

    def test_nine_column_table_still_passes(self):
        rows = claims.load(ROOT / "decks/2026-10-01-invoice-ocr-confirm/claims.csv")
        self.assertEqual(claims.validate(rows, ROOT / "decks/2026-10-01-invoice-ocr-confirm"), [])


DECK = """---
title: "架空"
{extra}---

<!-- audience: 検査 -->
<!-- action: 検査する -->
<!-- minutes: 3 -->
<!-- budget: 3 -->
<!-- status: approved -->

## 区切り

## 夜間の一括処理で件数は足りる
<!-- type: text -->

- 読み取り件数の面では夜間の一括処理で足りる。専用枠を契約するかは未決である。

## 専用枠を契約するかは設計者が決める
<!-- type: text -->
{claims}
- 設計者が来月までに決める。
"""


class ClaimsRequired(unittest.TestCase):
    def run_lint(self, deck_text: str, csv: str | None = None, quarto: str | None = None):
        with tempfile.TemporaryDirectory() as d:
            root = Path(d)
            (root / ".git").mkdir()                     # _quarto.yml を探す上限
            deck_dir = root / "decks" / "x"
            deck_dir.mkdir(parents=True)
            if quarto:
                (root / "decks" / "_quarto.yml").write_text(quarto, encoding="utf-8")
            if csv:
                (deck_dir / "claims.csv").write_text(csv, encoding="utf-8")
            qmd = deck_dir / "index.qmd"
            qmd.write_text(deck_text, encoding="utf-8")
            deck = lint.parse_deck(qmd)
            return lint.check_deck(deck, lint.load_ng_words()), lint.scope_line(deck)

    def test_required_in_yaml_blocks_each_main_slide_and_missing_table(self):
        issues, scope = self.run_lint(DECK.format(extra="claims: required\n", claims=""))
        blocks = [(i.rule, i.slide.index if i.slide else 0) for i in issues if i.severity == "block"]
        self.assertIn(("claims-file", 0), blocks)
        self.assertEqual(sorted(n for r, n in blocks if r == "claims-missing"), [2, 3])   # 区切りの枚（本文なし）は除く
        self.assertIn("本編 2枚", scope)
        self.assertIn("claims のある枚 0枚", scope)
        self.assertIn("3文", scope)                                                      # 2文＋1文

    def test_required_in_project_metadata_and_claims_present(self):
        csv = "id,doc,section,claim,status,evidence,owner,target,note\nC2,設計,§9,専用枠を契約するかは未決,未決,,設計者,deck,\n"
        issues, scope = self.run_lint(DECK.format(extra="", claims="<!-- claims: C2 -->"), csv=csv,
                                      quarto="metadata:\n  claims: required\n")
        missing = [i.slide.index for i in issues if i.rule == "claims-missing"]
        self.assertEqual(missing, [2])
        self.assertNotIn("claims-file", [i.rule for i in issues])
        self.assertIn("claims のある枚 1枚", scope)

    def test_not_required_stays_quiet(self):
        issues, _ = self.run_lint(DECK.format(extra="", claims=""))
        self.assertEqual([i.rule for i in issues if i.rule.startswith("claims")], [])


if __name__ == "__main__":
    unittest.main()


class ClaimsTableWithoutDeclaration(unittest.TestCase):
    """claims.csv があるデッキは `claims: required` と同じに扱う（宣言が無くても、claims の無い本編の枚を block）。"""

    def test_claims_csv_means_required(self):
        with tempfile.TemporaryDirectory() as d:
            deck = Path(d) / "index.qmd"
            deck.write_text("---\ntitle: 架空\n---\n\n<!-- audience: 経理部 -->\n<!-- action: 承認する -->\n<!-- minutes: 5 -->\n"
                            "<!-- budget: 2 -->\n<!-- status: approved -->\n\n## 請求書は OCR で読み取ると決めました\n\n"
                            "<!-- claims: C1 -->\n\n- 経理課が保留の項目だけを確かめる\n\n## 読み誤りは月末に経理課が直します\n\n"
                            "- 原本と照らして直す\n", encoding="utf-8")
            (Path(d) / "claims.csv").write_text(
                "id,doc,section,claim,status,evidence,owner,target,note\n"
                "C1,運用設計,§2,請求書は OCR で読み取る,方針,,,deck,\n", encoding="utf-8")
            issues = lint.check_deck(lint.parse_deck(deck), lint.load_ng_words())
            missing = [i for i in issues if i.rule == "claims-missing"]
            self.assertEqual([(i.severity, i.slide.index) for i in missing], [("block", 2)])


class TermsColumn(unittest.TestCase):
    def test_terms_blank_and_malformed(self):
        rows = [dict(id="C1", doc="運用設計", section="§2", claim="保留は確信度が低い項目", status="方針", evidence="", owner="",
                     target="deck", note="", terms=""),
                dict(id="C2", doc="運用設計", section="§3", claim="経理課が直す", status="方針", evidence="", owner="",
                     target="both", note="", terms="直す"),
                dict(id="C3", doc="運用設計", section="§4", claim="月次で見直す", status="方針", evidence="", owner="",
                     target="deck", note="", terms="見直し=レビュー; 月次=毎月"),
                dict(id="C4", doc="運用設計", section="§5", claim="版を上げる", status="方針", evidence="", owner="",
                     target="doc", note="", terms="")]
        warns = claims.warnings(rows)
        self.assertEqual([w.split(":")[0] for w in warns], ["2行目 C1", "3行目 C2"])   # 空欄と形の誤り。doc だけの行は見ない


class SourceTerms(unittest.TestCase):
    def test_lists_source_words_used_verbatim(self):
        with tempfile.TemporaryDirectory() as d:
            deck = Path(d) / "index.qmd"
            deck.write_text("---\ntitle: 架空\n---\n\n## 範囲外の請求書は手で入力します\n\n<!-- claims: C1 -->\n\n- 経理課が入力する\n",
                            encoding="utf-8")
            (Path(d) / "claims.csv").write_text(
                "id,doc,section,claim,status,evidence,owner,target,note,path,rev,quote\n"
                "C1,運用設計,§2,範囲外の請求書は手入力,方針,,,deck,,,,「範囲外」の請求書は経理課が手で入力する\n", encoding="utf-8")
            terms = lint.source_terms(lint.parse_deck(deck))
            self.assertEqual(len(terms), 1)
            self.assertIn("範囲外（C1）", terms[0])
