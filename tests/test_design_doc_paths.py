"""design-doc の検査のうち、2026-10-08 の改稿（判定仕様と表を持つ長い設計書）から足した・直したものを確かめる。

    erDiagram の { … } をラベルとして読まない、表にあることを隣の段落に書く（table-dup）、
    §1 の4項目は助言（summary-items）、付録への入口（appendix-scatter）、読む人ごとの経路の長さ（path-long）と
    読まない章への参照（reader-path-dep）。題材はすべて架空。

    .venv/bin/python -m unittest discover -s tests -v
"""
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / ".claude/skills/design-doc/scripts"))
import check_doc  # noqa: E402
import structure  # noqa: E402


def para(i: int) -> str:
    """数字と担当を含む、削除候補にならない段落（約70字）。"""
    return (f"経理課が{i}日目に「保留」の項目を{10 + i}分で確かめ、週次で誤りの記録を見直す。"
            "情報システム課は月次で閾値を評価し、承認を経て反映する。")


SUMMARY = ("## 1. 要点\n\n| 項目 | 要点 |\n|---|---|\n| 何を変えるか | 手入力を OCR に変える |\n"
           "| 次へ進む条件 | 読み誤りが手入力以下（原文に無い） |\n| まだ決めていない点 | 2点 |\n| 決めたこと | 方式の変更（経理部長、2026-09-20） |\n")


class Doc(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()

    def tearDown(self):
        self.tmp.cleanup()

    def doc(self, text: str, name: str = "doc.md") -> Path:
        p = Path(self.tmp.name) / name
        p.write_text(text, encoding="utf-8")
        return p

    def issues(self, path: Path, rule: str):
        return [i for i in check_doc.check_document(path) if i.rule == rule]


class ErDiagram(Doc):
    def test_entity_attributes_are_not_labels(self):
        er = ("# 架空\n\n## 1. データ\n\n```mermaid\nerDiagram\n  INVOICE ||--o{ LINE_ITEM : has\n"
              "  INVOICE {\n    string invoice_id PK\n    date issued_on\n    int total_yen\n  }\n"
              "  LINE_ITEM {\n    string item_id PK\n    string invoice_id FK\n  }\n```\n\n図1 請求書と明細\n")
        p = self.doc(er)
        for rule in ("mermaid-diamond", "mermaid-halfwidth", "mermaid-ref-label"):
            self.assertEqual(self.issues(p, rule), [], rule)
        self.assertEqual(structure.mermaid_labels(er.splitlines()), [])        # figure-dup の比べる語にもしない

    def test_flowchart_diamond_is_still_checked(self):
        fc = ("# 架空\n\n## 1. 判定\n\n```mermaid\nflowchart LR\n  A[\"受け取る\"] --> B{\"金額の読み取りの自信が閾値以上\"}\n```\n\n"
              "図1 判定\n")
        self.assertEqual(len(self.issues(self.doc(fc), "mermaid-diamond")), 1)


class TableDup(Doc):
    TEXT = """# 架空

## 1. 要点

請求書の読み取りを OCR に変える。

## 2. 書き戻し

書き戻しの処理が更新するのは2つの列だけである。

| 列 | 入れる値 |
|---|---|
| 状態 | 読み取り済み |
| 更新日時 | 処理した時刻 |

次の指標は使わない。いずれも検証済みの理由がある。

| 指標 | 使わない理由 |
|---|---|
| 平均処理時間 | 請求書の枚数で変わる |
| 再読み取りの回数 | 担当者の操作で変わる |
| 画像の解像度 | 取り込み装置で決まる |

読み誤りが出たら経理課が月末までに直す。

| 種類 | 直し方 | 担当 |
|---|---|---|
| 金額 | 原本と照らす | 経理課 |
| 日付 | 原本と照らす | 経理課 |
| 取引先 | 台帳と照らす | 経理課 |

表1 読み誤りの直し方（3種類）

| 段階 | 期間 |
|---|---|
| 試験 | 1か月 |
| 本番 | 以降 |
"""

    def test_paragraphs_restating_the_table(self):
        found = {i.line: i.message for i in self.issues(self.doc(self.TEXT), "table-dup")}
        lines = self.TEXT.splitlines()
        self.assertEqual(sorted(lines[n - 1][:6] for n in found), ["書き戻しの処", "次の指標は使"])
        msgs = " ".join(found.values())
        self.assertIn("表の行数（2行）", msgs)                       # 「2つの列」は行数の言い直し
        self.assertIn("使わない理由", msgs)                          # 見出しの語を並べただけの段落
        # 表に無いこと（いつまでに直すか）を書いた段落と、「表1 …」の題は出さない

    def test_sample_document_is_quiet(self):
        sample = ROOT / "decks/2026-10-01-invoice-ocr-confirm/design/operations.md"
        self.assertEqual(self.issues(sample, "table-dup"), [])


class SummaryAndAppendix(Doc):
    def test_summary_items_is_advice(self):
        body = "\n\n".join(para(i) for i in range(24))
        found = self.issues(self.doc(f"# 架空\n\n## 1. 要点\n\n本書の要点を示す。\n\n## 2. 運用\n\n{body}\n"), "summary-items")
        self.assertEqual([i.severity for i in found], ["info"])           # 4行は必須にしない（助言）
        self.assertIn("助言", found[0].message)

    def test_appendix_entry_in_summary_is_enough(self):
        refs = "\n\n".join(f"項目{i}の閾値は未確定である（付録B）。経理課が{i}日目に確かめる。" for i in range(6))
        base = "# 架空\n\n## 1. 要点\n\n{s1}\n\n## 2. 運用\n\n" + refs + "\n\n## 付録B 未確定の値\n\n| 値 | 担当 |\n|---|---|\n| 閾値 | 経理課 |\n"
        self.assertEqual(len(self.issues(self.doc(base.format(s1="手入力を OCR に変える。")), "appendix-scatter")), 1)
        # 件数が無くても、§1 に付録への入口があれば出さない（件数は §1 の「まだ決めていない点」と二重になる）
        self.assertEqual(self.issues(self.doc(base.format(s1="手入力を OCR に変える。まだ決めていない値は付録B。")), "appendix-scatter"), [])


class ReaderPaths(Doc):
    def head(self, readers: str) -> str:
        return f"# 架空\n\n| 項目 | 内容 |\n|---|---|\n| 読む人 | {readers} |\n\n{SUMMARY}\n"

    def chapter(self, n: int, paras: int, extra: str = "") -> str:
        return f"## {n}. 章{n}\n\n" + (extra + "\n\n" if extra else "") + "\n\n".join(para(n * 100 + i) for i in range(paras))

    def test_path_long_is_measured_per_reader(self):
        chapters = "\n\n".join(self.chapter(n, 36) for n in range(2, 6))      # 1章 約2300字 × 4章
        whole = self.doc(self.head("経理課の担当者") + chapters + "\n", "whole.md")
        self.assertEqual(len(self.issues(whole, "path-long")), 1)             # 読む人ごとの章が無ければ文書全体で測る
        split = self.doc(self.head("経理課（§2〜§3）・情報システム課（§4〜§5）の担当者") + chapters + "\n", "split.md")
        self.assertEqual(self.issues(split, "path-long"), [])                 # 読む人ごとの経路は約4600字
        heavy = self.doc(self.head("経理課（§2〜§4）・情報システム課（§5）の担当者") + chapters + "\n", "heavy.md")
        found = self.issues(heavy, "path-long")
        self.assertEqual(len(found), 1)
        self.assertIn("「経理課」（§2〜§4）", found[0].message)

    def test_reader_path_dependency(self):
        text = (self.head("経理課（§2）・情報システム課（§3）の担当者")
                + self.chapter(2, 3, "読み誤りの直し方は §3.1 の表に従う。未決は §1.1、閾値の案は §4 にある。") + "\n\n"
                + self.chapter(3, 3) + "\n\n## 4. 提案（未採択）\n\n" + para(1) + "\n")
        found = self.issues(self.doc(text), "reader-path-dep")
        self.assertEqual(len(found), 1)
        self.assertIn("「経理課」", found[0].message)
        self.assertIn("1回", found[0].message)                                # §1.1 と提案の章（§4）は数えない
        self.assertIn("§3.1", found[0].message)


if __name__ == "__main__":
    unittest.main()


class WritingPatterns(Doc):
    """2026-10-08 の設計書の修正パターン（言い訳の括弧・補足の言い直し・独自の語・数え直した数・冒頭の表・識別子）。"""

    def test_excuse_paren(self):
        p = self.doc("# 架空\n\n## 1. 取り込み\n\n請求書は日次で取り込む（月次では締めに間に合わないため）。"
                     "金額は原本と照らす（台帳では確認できない）。担当は経理課（課長が決める）。\n")
        found = self.issues(p, "excuse-paren")
        self.assertEqual(len(found), 1)
        self.assertIn("2か所", found[0].message)

    def test_restated_decision(self):
        text = ("# 架空\n\n## 2. 取り込み\n\n**請求書は届いた日のうちに OCR で読み取る。**\n\n#### 補足\n\n"
                "- 請求書は届いた日のうちに OCR で読み取る。締めの前日に集中しないため。\n"
                "- 読み取りの失敗は翌朝にまとめて再実行する。\n")
        found = self.issues(self.doc(text), "restated-decision")
        self.assertEqual(len(found), 1)
        self.assertEqual(text.splitlines()[found[0].line - 1][:6], "- 請求書は")

    def test_coined_term_reads_project_file(self):
        (Path(self.tmp.name) / "plans").mkdir()
        (Path(self.tmp.name) / "plans/doc_ng_phrases.md").write_text("# NG\n\n- 自動読取ライン → OCR の読み取り\n", encoding="utf-8")
        p = self.doc("# 架空\n\n## 1. 取り込み\n\n請求書は自動読取ラインで日次に読む。「自動読取ライン」という語は使わない。\n")
        found = self.issues(p, "coined-term")
        self.assertEqual(len(found), 1)
        self.assertIn("OCR の読み取り", found[0].message)

    def test_recounted_number(self):
        text = ("# 架空\n\n## 2. 例外\n\nこの方式で読めない書類が3種類ある。手で入力する。経理課が月末に見直す。\n\n"
                "読めない書類は経理課が月末までに手で入力し、件数を記録する。\n\n"
                "| 書類 | 理由 |\n|---|---|\n| 手書き | 字形がそろわない |\n| FAX | 解像度が低い |\n| 外国語 | 辞書が無い |\n\n"
                "表1 読めない書類（3種類）\n")
        found = self.issues(self.doc(text), "recounted-number")
        self.assertEqual([text.splitlines()[i.line - 1][:6] for i in found], ["この方式で読"])   # 表の題は数を書いてよい

    def test_doc_header_items(self):
        body = "\n\n".join(para(i) for i in range(24))
        head = "# 架空\n\n| 項目 | 内容 |\n|---|---|\n| この文書が扱うこと | 運用 |\n| 読む人 | 経理課 |\n{extra}\n" + SUMMARY + "\n## 2. 運用\n\n" + body + "\n"
        found = self.issues(self.doc(head.format(extra="")), "doc-header")
        self.assertEqual(len(found), 1)
        self.assertIn("関連文書・版", found[0].message)
        self.assertEqual(self.issues(self.doc(head.format(extra="| 関連文書 | 無い |\n| 版 | 1.0（2026-10-08） |")), "doc-header"), [])

    def test_opaque_id_includes_decision_numbers(self):
        body = "\n\n".join(f"経理課が{i}日目に確かめる（決定#{i + 10}）。" for i in range(6))
        found = self.issues(self.doc("# 架空\n\n## 1. 運用\n\n" + body + "\n"), "opaque-id")
        self.assertEqual(len(found), 1)
        self.assertIn("#10", found[0].message)

    def test_obvious_sentences_are_counted(self):
        import verbosity
        ng = verbosity.load_ng()
        for text in ("要件は4つの束に分かれる", "本書はこの3つを扱わない", "上表の範囲を満たすことである"):
            self.assertTrue(any(c == "obvious" for c, _ in verbosity.filler_hits(text, ng)), text)
