"""parts.py（図解型の部品）の HTML が期待どおりに出ることを確かめる。D2 の描画（parts.flow）は node が要るので、ここでは
前処理（2行ラベルの箱の高さ）だけを見る。

    python3 -m unittest discover -s tests -v
"""
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / ".claude/skills/slides/scripts"))
import parts  # noqa: E402


class Cards(unittest.TestCase):
    def test_cards_markup(self):
        h = parts.cards([("観測", ["票", "理由"]), ("規則", "版付き"), ("判定", "最終カテゴリ")], arrows=True, highlight="規則", alt="3段")
        self.assertEqual(h.count('<div class="ig-card"') + h.count('<div class="ig-card hl"'), 3)
        self.assertEqual(h.count('class="ig-arrow"'), 2)                 # 矢印はカードの間だけ
        self.assertEqual(h.count('class="ig-card hl"'), 1)               # 推す案だけ青い枠
        self.assertIn('aria-label="3段"', h)                              # alt は図の読み上げ
        self.assertIn('<div class="b">票</div><div class="b">理由</div>', h)   # 行の列は1行ずつ
        self.assertNotIn('class="n"', h)

    def test_cards_numbered_and_escaped(self):
        h = parts.cards([("A<b>", "x&y"), ("B", "z")], numbered=True)
        self.assertIn('<div class="n">1</div>', h)
        self.assertIn("A&lt;b&gt;", h)
        self.assertIn("x&amp;y", h)

    def test_steps_markup(self):
        h = parts.steps([("2層に分ける", "観測と判定"), ("追記する", "出来事として残す")])
        self.assertEqual(h.count('class="row"'), 2)
        self.assertIn('<div class="n">2</div>', h)
        self.assertIn('<div class="t">追記する</div>', h)


class FlowPreprocess(unittest.TestCase):
    def test_multiline_labels_get_taller_boxes(self):
        body = 'direction: right\nA: 画像\nB: "LLM に\\n複数回問う"\nC: "観測\\n属性\\n理由" {class: q}\nD: "1行" {class: go}\nA -> B\n'
        extra = parts._multiline_heights(body)
        self.assertIn("B.height: 110", extra)        # 2行
        self.assertIn("C.height: 146", extra)        # 3行
        self.assertNotIn("D.height", extra)          # 1行は足さない
        self.assertNotIn("A.height", extra)

    def test_explicit_height_is_kept(self):
        body = 'B: "a\\nb"\nB.height: 200\n'
        self.assertEqual(parts._multiline_heights(body), "")

    def test_center_labels_respaces_tspans(self):
        svg = ('<g class="shape" ><rect x="1.000000" y="12.000000" width="220.000000" height="110.000000" rx="8" fill="#fff"/></g>'
               '<text x="10" y="97.000000" class="text-bold" style="text-anchor:middle;font-size:30px">'
               '<tspan x="10" dy="0.000000">規則</tspan><tspan x="10" dy="0.000000">（版付き）</tspan></text>')
        out = parts._center_labels(svg)
        self.assertIn('dy="36.00"', out)                                  # 2行目の送りを行の高さで引き直す（D2 は 0 と測る）
        self.assertNotIn('y="97.000000"', out)                            # 1行目のベースラインを箱の中央に合わせ直す


if __name__ == "__main__":
    unittest.main()
