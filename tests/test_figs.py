"""figs.py（Claude Design「スライド型見本」の図）が、デッキと同じ色で描けることを確かめる。

    .venv/bin/python -m unittest discover -s tests
"""
import re
import sys
import unittest
from pathlib import Path

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt  # noqa: E402
from matplotlib.colors import to_hex  # noqa: E402

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / ".claude/skills/slides/scripts"))
import figs  # noqa: E402


def scss(name: str) -> str:
    text = (ROOT / "theme/custom.scss").read_text(encoding="utf-8")
    return re.search(rf"^\${name}:\s*(#[0-9a-f]{{6}})", text, re.M).group(1)


class Colors(unittest.TestCase):
    def test_same_as_theme(self):
        self.assertEqual(figs.BLUE, scss("link-color"))
        self.assertEqual(figs.ORANGE, scss("accent-2"))
        self.assertEqual(figs.MUTED, scss("muted"))
        self.assertEqual(figs.GRAY, scss("series-gray"))
        self.assertEqual(figs.LINE, scss("line"))


class Figures(unittest.TestCase):
    def tearDown(self):
        plt.close("all")

    def test_timeline(self):
        ax = figs.timeline([("試験導入", 0, 0.9), ("並行運用", 1.1, 0.8, figs.ORANGE)], ["1か月目", "2か月目"])
        colors = [to_hex(c.get_facecolor()[0]) for c in ax.collections]
        self.assertEqual(colors, [figs.BLUE, figs.ORANGE])
        self.assertEqual([t.get_text() for t in ax.get_yticklabels()], ["試験導入", "並行運用"])
        self.assertEqual(ax.get_xlim(), (0, 2))

    def test_direction(self):
        ax = figs.direction([("閾値を上げる", [("読み誤り ↓", 0.6), ("「保留」↑", 0.7, figs.ORANGE)]),
                             ("閾値を下げる", [("読み誤り ↑", 0.8)])])
        self.assertEqual([to_hex(p.get_facecolor()) for p in ax.patches], [figs.BLUE, figs.ORANGE, figs.BLUE])
        heads = {t.get_text(): t.get_position()[1] for t in ax.texts}
        self.assertEqual(heads["閾値を上げる"], -0.5)       # 2本の棒の中ほど
        self.assertEqual(heads["閾値を下げる"], -2.4)
        with self.assertRaises(ValueError):
            figs.direction([("x", [("y", 1.5)])])

    def test_bars_highlight_only_claim(self):
        ax = figs.bars(["PDF", "紙のスキャン", "FAX"], [30, 12, 8], highlight="PDF", unit="件")
        self.assertEqual([to_hex(p.get_facecolor()) for p in ax.patches], [figs.BLUE, figs.GRAY, figs.GRAY])
        self.assertIn("30件", [t.get_text() for t in ax.texts])
        with self.assertRaises(ValueError):
            figs.bars(["a"], [1], highlight="b")


if __name__ == "__main__":
    unittest.main()
