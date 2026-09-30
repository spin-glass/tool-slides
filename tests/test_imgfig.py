"""imgfig.py の閾値と「動く画像」の計算を確かめる（描画はしない）。

    .venv/bin/python -m unittest discover -s tests -v
matplotlib の無い環境では読み飛ばす。
"""
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / ".claude/skills/slides/scripts"))
try:
    import imgfig
except ImportError:          # matplotlib / pillow が無い
    imgfig = None


def item(score, normal=True, name="x"):
    return imgfig.Item(f"{name}{score}", Path("none.jpg"), score, normal, name)


@unittest.skipUnless(imgfig, "matplotlib / pillow が必要")
class Thresholds(unittest.TestCase):
    def test_threshold_rejects_floor_of_loss(self):
        scores = [i / 100 for i in range(1, 301)]            # 0.01 .. 3.00
        for loss, expected in ((0.01, 3), (0.05, 15), (0.10, 30), (0.0, 0)):
            t = imgfig.threshold_for_loss(scores, loss)
            self.assertEqual(sum(s > t for s in scores), expected)

    def test_moved_is_the_band_between_thresholds(self):
        items = [item(s) for s in (0.1, 0.2, 0.3, 0.4, 0.5)]
        self.assertEqual([i.score for i in imgfig.moved(items, 0.4, 0.2)], [0.3, 0.4])
        self.assertEqual([i.score for i in imgfig.moved(items, 0.2, 0.4)], [0.3, 0.4])   # 向きによらない
        self.assertEqual(len(imgfig.flagged(items, 0.2)) - len(imgfig.flagged(items, 0.4)), 2)

    def test_pick_evenly_is_deterministic_and_spread(self):
        items = [item(s / 10) for s in range(10)]
        self.assertEqual([i.score for i in imgfig.pick_evenly(items, 2)], [0.2, 0.7])
        self.assertEqual(imgfig.pick_evenly(items[:2], 5), items[:2])


@unittest.skipUnless(imgfig, "matplotlib / pillow が必要")
class Generic(unittest.TestCase):
    """切り口と選び方（閾値に限らない部分）。"""

    def rows(self):
        table = [("a", "cat", "cat", 0.9), ("b", "cat", "dog", 0.6), ("c", "dog", "dog", 0.8),
                 ("d", "dog", "cat", 0.55), ("e", "cat", "dog", 0.7), ("f", "dog", "dog", 0.95)]
        return [imgfig.Item(i, Path("none.jpg"), score=p, attrs={"true": t, "pred": q, "prob": str(p)})
                for i, t, q, p in table]

    def test_attrs(self):
        it = self.rows()[1]
        self.assertEqual((it["true"], it["pred"], it.num("prob"), it.get("missing", "-")), ("cat", "dog", 0.6, "-"))

    def test_split_by_orders_by_size_or_given_order(self):
        wrong = [it for it in self.rows() if it["true"] != it["pred"]]
        groups = imgfig.split_by(wrong, lambda it: (it["true"], it["pred"]))
        self.assertEqual([(k, len(g)) for k, g in groups], [(("cat", "dog"), 2), (("dog", "cat"), 1)])
        ordered = imgfig.split_by(self.rows(), lambda it: it["true"], order=["dog", "cat", "bird"])
        self.assertEqual([(k, len(g)) for k, g in ordered], [("dog", 3), ("cat", 3), ("bird", 0)])

    def test_cross_counts_every_cell(self):
        cells = imgfig.cross(self.rows(), lambda it: it["true"], lambda it: it["pred"])
        self.assertEqual({k: len(v) for k, v in cells.items()},
                         {("cat", "cat"): 1, ("cat", "dog"): 2, ("dog", "dog"): 2, ("dog", "cat"): 1})

    def test_pick_rules(self):
        rows, prob = self.rows(), (lambda it: it.score)
        self.assertEqual([i.id for i in imgfig.pick(rows, 2, "top", key=prob)], ["f", "a"])
        self.assertEqual([i.id for i in imgfig.pick(rows, 2, "bottom", key=prob)], ["d", "b"])
        self.assertEqual([i.id for i in imgfig.pick(rows, 3, "even", key=prob)], ["b", "c", "f"])   # 3等分した各区間の中央
        self.assertEqual(imgfig.pick(rows, 3, "random", seed=1), imgfig.pick(rows, 3, "random", seed=1))
        self.assertEqual(len(imgfig.pick(rows, None)), 6)
        self.assertEqual(len(imgfig.pick(rows, 10, "even")), 6)

    def test_pick_note(self):
        self.assertEqual(imgfig.pick_note(12, 12), "12枚をすべて表示")
        self.assertEqual(imgfig.pick_note(40, 8), "40枚からスコア順に等間隔で8枚を表示")
        self.assertEqual(imgfig.pick_note(40, 5, "top", by="確信度"), "40枚から確信度の大きい順に5枚を表示")

    def test_load_table_keeps_every_column(self):
        deck = ROOT / "decks/2026-09-30-outlier-threshold-images"
        items = imgfig.load_table(deck / "data/scores.csv", deck / "data/thumbs", score_col="score")
        self.assertEqual(len(items), 600)
        self.assertEqual(set(items[0].attrs), {"id", "role", "group", "label", "label_ja", "score"})


@unittest.skipUnless(imgfig, "matplotlib / pillow が必要")
class OutlierDeck(unittest.TestCase):
    """デッキのタイトルに書いた数字が、コミットしたスコアから再現できること。"""

    def test_numbers_in_titles(self):
        deck = ROOT / "decks/2026-09-30-outlier-threshold-images"
        items = imgfig.load_items(deck / "data/scores.csv", deck / "data/thumbs", normal_group="dog")
        cal = [i.score for i in items if i.role == "cal"]
        ev = [i for i in items if i.role == "eval"]
        t = {p: imgfig.threshold_for_loss(cal, p / 100) for p in (1, 5, 10)}

        def counts(a, b):
            m = imgfig.moved(ev, t[a], t[b])
            return sum(i.normal for i in m), sum(not i.normal for i in m)

        self.assertEqual(counts(1, 5), (6, 40))
        self.assertEqual(counts(5, 10), (8, 12))
        self.assertEqual(sorted(i.label for i in ev if not i.normal and i.score <= t[10]), ["オオカミ"] * 3 + ["猫"] * 8)
        self.assertTrue(all(i.path.exists() for i in ev))


if __name__ == "__main__":
    unittest.main()
