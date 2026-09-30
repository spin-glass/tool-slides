"""imgfig.py の閾値・切り口・選び方・並べ方の計算を確かめる。

    .venv/bin/python -m unittest discover -s tests -v
matplotlib の無い環境では読み飛ばす。
"""
import json
import os
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / ".claude/skills/slides/scripts"))
os.environ.setdefault("MPLBACKEND", "Agg")      # 図を作るテストで窓を開かない
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
class Layout(unittest.TestCase):
    """並べ方: 1枚が最も大きくなる列数、横長の枠、折り返し、説明文の行数。"""

    def photos(self, sizes):
        from PIL import Image
        d = Path(tempfile.mkdtemp())
        items = []
        for n, (w, h) in enumerate(sizes):
            Image.new("RGB", (w, h), (120, 140, 90)).save(d / f"p{n}.jpg")
            items.append(imgfig.Item(f"p{n}", d / f"p{n}.jpg", attrs={"n": str(n)}))
        return items

    def test_unit_px_is_limited_by_width_or_height(self):
        self.assertEqual(round(imgfig.unit_px(6, 2)), 197)        # 横幅 1180px が先に効く
        self.assertEqual(round(imgfig.unit_px(6, 4)), 100)        # 高さ 400px が先に効く
        self.assertEqual(round(imgfig.unit_px(6, 4, imgfig.SLIDE_BOX_TALL)), 125)

    def test_best_picks_the_largest_thumbnail(self):
        pitch = imgfig.WIDE_CELL + imgfig.CAPTION_H
        best = imgfig._best((n, n, imgfig._rows(12, n) * pitch) for n in range(1, 13))
        self.assertEqual(best, 6)                                  # 12枚は 6列×2段が最大

    def test_cell_is_wide_only_when_most_photos_are_landscape(self):
        landscape, portrait = (256, 171), (171, 256)
        self.assertEqual(imgfig._cell_h(self.photos([landscape] * 7 + [portrait]), None), imgfig.WIDE_CELL)
        self.assertEqual(imgfig._cell_h(self.photos([landscape] * 2 + [portrait] * 2), None), 1.0)
        self.assertEqual(imgfig._cell_h([], None), 1.0)
        self.assertEqual(imgfig._cell_h(self.photos([portrait]), 0.75), 0.75)      # 指定があればそれを使う

    def test_caption_height_counts_lines(self):
        items = self.photos([(256, 171)] * 2)
        self.assertEqual(imgfig._cap_h(items, None), 0.0)
        self.assertEqual(imgfig._cap_h(items, lambda it: "a"), imgfig.CAPTION_H)
        self.assertEqual(imgfig._cap_h(items, lambda it: "a\nb" if it.id == "p1" else "a"),
                         imgfig.CAPTION_H + imgfig.CAPTION_LINE)

    def test_flow_wraps_groups_and_keeps_room_for_headings(self):
        lines = imgfig._flow_lines([12, 3, 3, 3, 2, 1], [2.0] * 6, width=12)
        self.assertEqual([[g for g, *_ in line] for line in lines], [[0], [1, 2, 3], [4, 5]])
        self.assertEqual([cols for _, cols, _, _ in lines[1]], [3, 3, 3])
        self.assertEqual(lines[2][1][2], 2.0)                      # 1枚の群でも、見出しの幅は確保する
        narrow = imgfig._flow_lines([12], [2.0], width=6)
        self.assertEqual(narrow[0][0][1], 6)                       # 幅より多い群は、群の中で折り返す

    def test_figures_report_their_size(self):
        items = self.photos([(256, 171)] * 12)
        report = Path(tempfile.mkdtemp()) / "report.jsonl"
        os.environ["IMGFIG_REPORT"] = str(report)
        try:
            imgfig.grid_figure(items, caption=lambda it: it["n"])
            imgfig.flow_figure([("a", items[:5]), ("b", items[5:7]), ("c", items[7:])], caption=lambda it: "x\ny")
        finally:
            del os.environ["IMGFIG_REPORT"]
            imgfig.plt.close("all")
        rows = [json.loads(line) for line in report.read_text().splitlines()]
        self.assertEqual([(r["kind"], r["thumbs"]) for r in rows], [("grid", 12), ("flow", 12)])
        self.assertEqual(rows[0]["px"], 182)                       # 6列×2段、横長の枠、説明文1行
        self.assertGreaterEqual(rows[0]["px_tall"], rows[0]["px"])


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
