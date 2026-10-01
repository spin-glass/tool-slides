"""imgfig.py の閾値・切り口・選び方・並べ方の計算を確かめる。

    .venv/bin/python -m unittest discover -s tests -v
matplotlib の無い環境では読み飛ばす。
"""
import dataclasses
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

    def test_review_sheet_splits_and_keeps_every_image(self):
        items = self.photos([(256, 171)] * 30)
        out = Path(tempfile.mkdtemp()) / "check.jpg"
        files = imgfig.review_sheet(items, out, caption=lambda it: f"ラベル {it['n']}\n題名", per_sheet=24)
        self.assertEqual([f.name for f in files], ["check.jpg", "check-2.jpg"])
        from PIL import Image
        self.assertEqual(Image.open(files[0]).width, 6 * 262 + 8)          # 1枚あたり元の大きさ（256px）＋余白
        self.assertEqual(Image.open(files[1]).width, 6 * 262 + 8)          # 残り6枚

    def test_load_table_finds_originals_next_to_thumbs(self):
        from PIL import Image
        d = Path(tempfile.mkdtemp())
        (d / "thumbs").mkdir()
        (d / "images").mkdir()
        for i in ("a", "b"):
            Image.new("RGB", (256, 171)).save(d / "thumbs" / f"{i}.jpg")
        Image.new("RGB", (1024, 683)).save(d / "images" / "a.jpg")           # b の元の写真は無い
        (d / "t.csv").write_text("id,x\na,1\nb,2\n", encoding="utf-8")
        items = imgfig.load_table(d / "t.csv", d / "thumbs")
        self.assertEqual([it.original.name if it.original else None for it in items], ["a.jpg", None])
        (d / "images" / "a.jpg").unlink()
        (d / "images").rmdir()
        self.assertIsNone(imgfig.load_table(d / "t.csv", d / "thumbs")[0].original)   # images/ が無ければ使わない

    def test_review_sheet_uses_originals_large(self):
        from PIL import Image
        items = []
        for it in self.photos([(256, 171)] * 10):
            big = it.path.with_name(f"{it.id}-big.jpg")
            Image.new("RGB", (1024, 683), (90, 120, 140)).save(big)
            items.append(dataclasses.replace(it, original=big))
        files = imgfig.review_sheet(items, Path(tempfile.mkdtemp()) / "check.jpg")
        self.assertEqual(len(files), 2)                                      # 元の写真は1枚に9つまで
        self.assertEqual(Image.open(files[0]).width, 3 * 486 + 8)            # 長辺480px・3列

    def test_zoom_figure_pairs_whole_photo_and_crop(self):
        report = Path(tempfile.mkdtemp()) / "report.jsonl"
        os.environ["IMGFIG_REPORT"] = str(report)
        try:
            items = self.photos([(256, 171)] * 3)
            imgfig.zoom_figure([(it, (0.6, 0.1, 0.9, 0.4)) for it in items], caption=lambda it: f"ラベル {it['n']}\n拡大")
        finally:
            del os.environ["IMGFIG_REPORT"]
            imgfig.plt.close("all")
        row = json.loads(report.read_text().splitlines()[0])
        self.assertEqual((row["kind"], row["thumbs"]), ("zoom", 6))          # 写真全体と拡大の組が3つ

    def test_locate_image_draws_a_grid(self):
        from PIL import Image
        src = self.photos([(2048, 1365)])[0].path
        out = imgfig.locate_image(src, Path(tempfile.mkdtemp()) / "locate.jpg")
        self.assertEqual(max(Image.open(out).size), 1024)

    def test_check_look_finds_missing_classes_and_mixed_groups(self):
        items = self.photos([(256, 171)] * 3)          # p0: 白鳥とカモ、p1: 白鳥だけ、p2: カモだけ
        d = Path(tempfile.mkdtemp())
        (d / "look.csv").write_text("id,classes,note\np0,白鳥;カモ,奥にハト\np1,白鳥,\np2,カモ,\n", encoding="utf-8")
        looked = imgfig.load_look(items, d / "look.csv")
        self.assertEqual(imgfig.seen(looked[0]), "白鳥＋カモ（奥にハト）")
        self.assertEqual(imgfig.seen(looked[0], note=False), "白鳥＋カモ")
        report = d / "report.jsonl"
        os.environ["IMGFIG_REPORT"] = str(report)
        try:
            imgfig.flow_figure([("白鳥の写真", looked[:2]), ("ラベル 白鳥 → 予測 カモ", looked[2:])],
                               caption=lambda it: it.id if it.id == "p0" else imgfig.seen(it))
            imgfig.grid_figure(looked, caption=imgfig.seen)
            imgfig.grid_figure(looked[:1], caption=lambda it: imgfig.seen(it, note=False))     # note を落とす
        finally:
            del os.environ["IMGFIG_REPORT"]
            imgfig.plt.close("all")
        found = imgfig.check_look(report, d / "look.csv")
        self.assertEqual(len(found), 3, found)                  # p0 の説明に「白鳥・カモ」が無い／見出し「白鳥の写真」に p0／note が無い
        self.assertTrue(any("note: 奥にハト" in f for f in found))
        self.assertTrue(any("p0 の説明" in f for f in found))
        self.assertTrue(any("見出し「白鳥の写真" in f and "p0" in f for f in found))

    def test_closeup_image_shows_whole_photo_and_four_tiles(self):
        from PIL import Image
        it = self.photos([(1024, 683)])[0]
        out = imgfig.closeup_image(it, Path(tempfile.mkdtemp()) / "c.jpg", header="探す: 犬・猫")
        w, h = Image.open(out).size
        self.assertEqual(w, 640 + 10 + 2 * (400 + 10))              # 全体（長辺640px）＋2列の区画（400px）
        self.assertIn(h, range(40 + 2 * (266 + 34), 40 + 2 * (268 + 34) + 1))   # 区画2段（横長の区画は高さ約267px）。全体（427px）より高い

    def test_check_look_asks_closeup_for_absent_classes(self):
        items = self.photos([(256, 171)] * 4)          # p0: 何も写らない、p1: ラベルの白鳥が写らない、p2: 確かめ済み、p3: 写る
        d = Path(tempfile.mkdtemp())
        (d / "look.csv").write_text("id,label_class,classes,note,closeup\np0,白鳥,,サギ,\np1,白鳥,カモ,,\n"
                                    "p2,カモ,,サギ,yes\np3,白鳥,白鳥,,\n", encoding="utf-8")
        self.assertEqual([imgfig.needs_closeup(r) for r in imgfig.csv.DictReader(open(d / "look.csv", encoding="utf-8"))],
                         [True, True, True, False])
        looked = imgfig.load_look(items, d / "look.csv")
        report = d / "report.jsonl"
        os.environ["IMGFIG_REPORT"] = str(report)
        try:
            imgfig.grid_figure(looked, caption=imgfig.seen)
        finally:
            del os.environ["IMGFIG_REPORT"]
            imgfig.plt.close("all")
        found = imgfig.check_look(report, d / "look.csv")
        self.assertEqual(len(found), 1, found)                  # 1つの図に、拡大で確かめていない2枚（p0, p1）
        self.assertIn("2 枚（p0, p1）", found[0])

    def test_unsure_is_neither_present_nor_absent(self):
        items = self.photos([(256, 171)] * 3)          # p0: ガンか決めきれない影、p1: ガンは写らない、p2: note だけ「不明」
        d = Path(tempfile.mkdtemp())
        (d / "look.csv").write_text("id,label_class,classes,unsure,note,closeup\np0,ガン,,ガン,遠くの影,yes\n"
                                    "p1,ガン,,,サギ,yes\np2,ガン,カモ,,奥の鳥は不明,yes\n", encoding="utf-8")
        looked = imgfig.load_look(items, d / "look.csv")
        self.assertEqual(imgfig.seen(looked[0]), "ガン?（遠くの影）")
        self.assertEqual([imgfig.absent(it, "ガン") for it in looked], [False, True, True])
        self.assertEqual([imgfig.present(it, "カモ") for it in looked], [False, False, True])
        report = d / "report.jsonl"
        os.environ["IMGFIG_REPORT"] = str(report)
        try:
            imgfig.flow_figure([("ガンが写っていない", looked[:2]), ("カモ", looked[2:])], caption=imgfig.seen)
        finally:
            del os.environ["IMGFIG_REPORT"]
            imgfig.plt.close("all")
        found = imgfig.check_look(report, d / "look.csv")
        self.assertEqual(len(found), 2, found)          # note に「不明」で unsure が空（p2）／「写っていない」の群に p0
        self.assertTrue(any("unsure 列が空" in f and "p2" in f for f in found))
        self.assertTrue(any("写っていない" in f and "p0" in f for f in found))

    def test_check_counts_finds_label_counts_written_as_content(self):
        d = Path(tempfile.mkdtemp())
        rows = ["id,true_ja,pred_ja"] + [f"g{k},ヤギ,鹿" for k in range(5)] + [f"s{k},ヤギ,羊" for k in range(3)] + \
               ["c0,牛,牛", "d0,鹿,鹿", "h0,羊,羊"]
        (d / "predictions.csv").write_text("\n".join(rows) + "\n", encoding="utf-8")
        look = ["id,label_class,classes,unsure,note,closeup"] + [f"g{k},ヤギ,ヤギ,,,yes" for k in range(5)] + \
               [f"s{k},ヤギ,羊,,,yes" for k in range(3)]
        (d / "look.csv").write_text("\n".join(look) + "\n", encoding="utf-8")
        (d / "index.html").write_text(
            '<section class="slide level2"><h2>誤り8枚のうち、8枚はヤギの写真だ</h2></section>'
            '<section class="slide level2"><h2>ラベルがヤギの写真8枚のうち、5枚はヤギが写る</h2>'
            '<aside class="notes">8枚はヤギの写真</aside></section>', encoding="utf-8")
        found = imgfig.check_counts(d / "index.html", d / "look.csv")
        self.assertEqual(len(found), 1, found)                  # 1枚目だけ（2枚目は「ラベルが」と書き、5枚は合う。ノートは見ない）
        self.assertTrue(found[0].startswith("スライド1"))

    def test_claim_checks_each_count_and_titles_need_claims(self):
        items = self.photos([(256, 171)] * 14)
        geese = items[:6] + items[10:14]               # 文が指す範囲（ガンか黒いハクチョウ）の10枚
        with self.assertRaises(AssertionError):        # 範囲を取り違えた数（8枚）は止まる
            imgfig.claim("14枚のうち8枚は、ガンか黒いハクチョウの写真だ", {14: items, 8: geese})
        with self.assertRaises(AssertionError):        # 文の数を渡し忘れても止まる
            imgfig.claim("14枚のうち10枚は、ガンか黒いハクチョウの写真だ", {10: geese})
        d = Path(tempfile.mkdtemp())
        report = d / "report.jsonl"
        os.environ["IMGFIG_REPORT"] = str(report)
        try:
            imgfig.claim("14枚のうち10枚は、ガンか黒いハクチョウの写真だ", {14: items, 10: geese})
        finally:
            del os.environ["IMGFIG_REPORT"]
        (d / "index.html").write_text(
            '<section id="title-slide" class="quarto-title-block"><h1>t</h1></section>'
            '<section class="slide level2"><h2>14枚のうち10枚は、ガンか黒いハクチョウの写真だ</h2></section>'
            '<section class="slide level2"><h2>誤り51枚のうち12枚はモデルの誤りだ</h2></section>'
            '<section class="slide level2"><h2>1枚目は牧場の写真だ</h2></section>', encoding="utf-8")
        found = imgfig.check_claims(d / "index.html", report)
        self.assertEqual(len(found), 1, found)         # claim の無い3枚目だけ（「1枚目」は数えない）
        self.assertTrue(found[0].startswith("スライド3"))

    def test_claim_names_are_checked_against_the_look_table(self):
        items = self.photos([(256, 171)] * 12)
        d = Path(tempfile.mkdtemp())
        rows = [f"p{n},犬,猫,," for n in range(5)] + [f"p{n},犬,オウム,," for n in (5, 6)] \
            + [f"p{n},犬,猫,,白い猫" for n in (7, 8)] + ["p9,犬,,猫,遠くの影", "p10,犬,,,", "p11,犬,,,"]
        (d / "look.csv").write_text("id,label_class,classes,unsure,note\n" + "\n".join(rows) + "\n", encoding="utf-8")
        looked = imgfig.load_look(items, d / "look.csv")
        report = d / "report.jsonl"
        os.environ["IMGFIG_REPORT"] = str(report)
        try:
            imgfig.claim("ラベルが犬の誤り12枚のうち7枚は、猫かオウムの写真だ", {12: looked, 7: looked[:7]})
            imgfig.claim("ラベルが犬の誤り12枚のうち7枚は、猫かオウムの写真だ。", {12: looked, 7: looked[:7]},
                         outside=looked[7:9])                      # 白い猫を形容で外したと明示すれば知らせない
            imgfig.claim("誤り12枚は犬の写真だ", {12: looked})       # ラベルの数を中身として書いた
            imgfig.claim("猫が写っていない3枚", {3: looked[9:]})      # 決めきれない1枚が入る
            imgfig.claim("ラベルが犬の12枚", {12: looked})           # ラベルで範囲を言う部分は照らさない
            imgfig.claim("猫かどうか決めきれない1枚", {1: looked[9:10]})
        finally:
            del os.environ["IMGFIG_REPORT"]
        warns = [json.loads(line)["warnings"] for line in open(report, encoding="utf-8")]
        self.assertEqual(len(warns[0]), 1, warns[0])
        self.assertIn("p7, p8", warns[0][0])                       # 範囲の残りにも猫が写る
        self.assertEqual(warns[1], [])
        self.assertEqual(len(warns[2]), 1, warns[2])
        self.assertIn("12枚のうち12枚", warns[2][0])
        self.assertEqual(len(warns[3]), 1, warns[3])
        self.assertIn("p9", warns[3][0])
        self.assertEqual(warns[4:], [[], []])
        (d / "index.html").write_text('<section class="slide level2"><h2>誤り12枚は犬の写真だ</h2></section>', encoding="utf-8")
        found = imgfig.check_claims(d / "index.html", report)
        self.assertEqual(len(found), 3, found)                     # claim の食い違い3件（タイトルは claim 済み）

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
