#!/usr/bin/env python3
"""スライド用の「具体例の画像」の図を matplotlib で描く。

型は1つ: 数の主張を、その数の中身の画像で見せる。
  1. 表を読む          items = load_table("data/table.csv", "data/thumbs")      # 1行 = 1画像
  2. 切り口で群に分ける   groups = split_by(items, lambda it: (it["true"], it["pred"]))
  3. 見せる画像を選ぶ    shown = pick(group, 12, how="even")   # 全数 / 等間隔 / 上位 / 無作為。選び方は pick_note で書く
  4. 並べる             grid_figure（1群） / panels_figure（2〜3群の対比） / rows_figure（群が多い・1枚と相手）
                       matrix_figure（2軸の表） / histogram_figure（数値の軸に沿う）

閾値の切り口には近道がある: threshold_for_loss / flagged / moved / moved_figure。

図は1枚の画像になるので revealjs / pptx / PDF のどれでも同じ見た目で出る。
寸法は「1単位 = サムネイル1枚の幅」で組み、文字は単位に比例させる。横12インチの図で1単位が1インチ前後
（スライド上で約100px）になる枚数に抑えると、サムネイルの中身とラベルが読める。小さすぎると警告を出す。

qmd からの使い方:
    import sys; sys.path.insert(0, "../../.claude/skills/slides/scripts")
    import imgfig
    items = imgfig.load_table("data/table.csv", "data/thumbs")
    wrong = [it for it in items if it["true"] != it["pred"]]
    imgfig.rows_figure([(f"{t} → {p}", g) for (t, p), g in imgfig.split_by(wrong, lambda it: (it["true"], it["pred"]))]);

CLI（qmd を書かずに1枚の図にする）:
    python imgfig.py groups --table table.csv --thumbs thumbs/ --by true,pred --where result=wrong --out groups.png
    python imgfig.py matrix --table table.csv --thumbs thumbs/ --row true --col pred --out matrix.png
    python imgfig.py moved  --scores scores.csv --thumbs thumbs/ --normal-group dog --from-loss 0.01 --to-loss 0.05 --out moved.png
表の列は自由（id 列が必須）。画像は <thumbs>/<id>.jpg。
"""
from __future__ import annotations

import argparse
import csv
import math
import random
import warnings
from dataclasses import dataclass, field
from pathlib import Path

import matplotlib.pyplot as plt
import numpy as np
from matplotlib.patches import Rectangle
from PIL import Image

BLUE = "#0b5cad"
ORANGE = "#d9480f"           # 青と橙は色覚の違いがあっても区別しやすい
TEAL = "#0c8599"
PURPLE = "#862e9c"
PALETTE = [BLUE, ORANGE, TEAL, PURPLE]
NORMAL_COLOR = BLUE          # 正常・正解・変化なし
OUTLIER_COLOR = ORANGE       # 外れ値・誤り・変化あり
INK = "#1f2328"
MUTED = "#57606a"
LINE = "#d0d7de"
BG = "#f3f4f6"
FONT_CANDIDATES = ["Hiragino Sans", "Noto Sans CJK JP", "Noto Sans JP", "IPAexGothic", "Yu Gothic"]
MIN_UNIT_IN = 0.7            # これより小さいサムネイルは中身が読めない（12インチ幅の図で約70px）


def japanese_fonts() -> list[str]:
    """入っている日本語フォントだけを返す（無いフォントを指定すると警告が大量に出るため）。"""
    from matplotlib import font_manager

    have = {f.name for f in font_manager.fontManager.ttflist}
    return [f for f in FONT_CANDIDATES if f in have] + ["sans-serif"]


# ---- 表 -------------------------------------------------------------------
@dataclass(frozen=True)
class Item:
    """1画像。表の列は attrs に入り、it["列名"] で読める。score / normal / label は閾値の型で使う近道。"""
    id: str
    path: Path
    score: float = 0.0
    normal: bool = True
    label: str = ""
    role: str = ""
    attrs: dict = field(default_factory=dict, compare=False, repr=False)

    def __getitem__(self, key: str) -> str:
        return self.attrs[key]

    def get(self, key: str, default=None):
        return self.attrs.get(key, default)

    def num(self, key: str) -> float:
        return float(self.attrs[key])


def load_table(table_csv, thumbs_dir, id_col: str = "id", label_col: str | None = None,
               score_col: str | None = None, ext: str = ".jpg") -> list[Item]:
    """表（1行 = 1画像）を読む。列は it["列名"]、数値は it.num("列名")。行の順序は表のまま。"""
    items = []
    with open(table_csv, newline="", encoding="utf-8") as f:
        for r in csv.DictReader(f):
            items.append(Item(r[id_col], Path(thumbs_dir) / f"{r[id_col]}{ext}",
                              score=float(r[score_col]) if score_col else 0.0,
                              label=r[label_col] if label_col else "", role=r.get("role", ""), attrs=dict(r)))
    return items


def load_items(scores_csv, thumbs_dir, normal_group: str, role: str | None = None,
               group_col: str = "group", label_col: str = "label_ja") -> list[Item]:
    """閾値の型の表（id, role, group, label, score）を読み、スコアの小さい順に返す。"""
    items = []
    with open(scores_csv, newline="", encoding="utf-8") as f:
        for r in csv.DictReader(f):
            if role and r.get("role") != role:
                continue
            label = r.get(label_col) or r.get("label") or r[group_col]
            items.append(Item(r["id"], Path(thumbs_dir) / f"{r['id']}.jpg", float(r["score"]),
                              r[group_col] == normal_group, label, r.get("role", ""), dict(r)))
    return sorted(items, key=lambda i: i.score)


# ---- 切り口と選び方 --------------------------------------------------------
def split_by(items, key, order=None) -> list[tuple]:
    """切り口で群に分ける。[(値, その群の items), ...] を、order の順か、枚数の多い順で返す。"""
    groups: dict = {}
    for it in items:
        groups.setdefault(key(it), []).append(it)
    if order is not None:
        return [(v, groups.get(v, [])) for v in order]
    return sorted(groups.items(), key=lambda kv: -len(kv[1]))


def cross(items, row, col) -> dict:
    """2つの切り口で表にする。{(行の値, 列の値): items}。"""
    cells: dict = {}
    for it in items:
        cells.setdefault((row(it), col(it)), []).append(it)
    return cells


def pick(items, k: int | None, how: str = "even", key=None, seed: int = 0) -> list[Item]:
    """見せる画像を規則で選ぶ（恣意的に選ばない）。how = all / even（等間隔）/ top / bottom / random。

    key を渡すとその値で並べてから選ぶ（even は小さい順に等間隔、top は大きい順に k 枚、bottom は小さい順に k 枚）。
    """
    items = list(items)
    if key is not None:
        items.sort(key=key)
    if k is None or how == "all" or len(items) <= k:
        return items[::-1] if how == "top" and key is not None else items
    if how == "even":
        return pick_evenly(items, k)
    if how == "top":
        return items[::-1][:k] if key is not None else items[:k]
    if how == "bottom":
        return items[:k]
    if how == "random":
        return sorted(random.Random(seed).sample(items, k), key=items.index)
    raise ValueError(f"how は all / even / top / bottom / random のどれか: {how!r}")


def pick_evenly(items, k: int) -> list[Item]:
    """並び順に等間隔で最大 k 枚を選ぶ（k 等分した各区間の中央）。"""
    n = len(items)
    if n <= k:
        return list(items)
    return [items[min(n - 1, int((j + 0.5) * n / k))] for j in range(k)]


def pick_note(total: int, shown: int, how: str = "even", by: str = "スコア") -> str:
    """選び方を1文にする（図の下の出典行に書く）。"""
    if shown >= total or how == "all":
        return f"{total}枚をすべて表示"
    rule = {"even": f"{by}順に等間隔で", "top": f"{by}の大きい順に", "bottom": f"{by}の小さい順に",
            "random": "無作為に"}[how]
    return f"{total}枚から{rule}{shown}枚を表示"


def threshold_for_loss(normal_scores, loss: float) -> float:
    """較正用の正常画像のうち floor(loss·n) 枚だけが外れ値になる閾値。判定は「score > 閾値 → 外れ値」。"""
    s = sorted(normal_scores, reverse=True)
    m = math.floor(loss * len(s) + 1e-9)
    return s[m] if m < len(s) else -math.inf


def flagged(items, t: float) -> list[Item]:
    """閾値 t で外れ値になる画像。"""
    return [i for i in items if i.score > t]


def moved(items, t_from: float, t_to: float) -> list[Item]:
    """閾値を t_from から t_to へ動かしたときに判定が変わる画像（スコア順、全数）。"""
    lo, hi = sorted((t_from, t_to))
    return sorted((i for i in items if lo < i.score <= hi), key=lambda i: i.score)


# ---- 描画の土台 -----------------------------------------------------------
class Canvas:
    """左上が原点、1単位 = サムネイル1枚の幅。width_in × max_height_in に収まるよう全体を縮める。"""

    def __init__(self, w_units: float, h_units: float, width_in: float = 12.0, max_height_in: float = 5.6):
        plt.rcParams["font.family"] = japanese_fonts()
        scale = min(width_in / w_units, max_height_in / h_units)
        self.fig = plt.figure(figsize=(w_units * scale, h_units * scale))
        self.ax = self.fig.add_axes([0, 0, 1, 1])
        self.ax.axis("off")
        self.ax.autoscale(False)
        self.w, self.h = w_units, h_units
        self.unit_in = scale            # 1単位の実寸（インチ）
        self.pt = scale * 72.0          # 1単位あたりのポイント数

    def finish(self):
        self.ax.set_xlim(0, self.w)
        self.ax.set_ylim(self.h, 0)
        self.ax.set_aspect("equal")
        if self.unit_in < MIN_UNIT_IN:
            warnings.warn(f"サムネイルが小さい（スライド上で約{self.unit_in * 100:.0f}px）。"
                          "枚数を減らす（pick）か、図を分ける", stacklevel=3)
        return self.fig

    def text(self, x, y, s, size=0.17, color=INK, ha="center", va="center", weight="normal", **kw):
        self.ax.text(x, y, s, fontsize=size * self.pt, color=color, ha=ha, va=va, weight=weight, **kw)

    def vline(self, x, y0, y1, color=INK, lw=0.03):
        self.ax.plot([x, x], [y0, y1], color=color, lw=lw * self.pt, solid_capstyle="butt", zorder=5)

    def hline(self, y, x0, x1, color=MUTED, lw=0.012):
        self.ax.plot([x0, x1], [y, y], color=color, lw=lw * self.pt, solid_capstyle="butt", zorder=1)

    def thumb(self, item: Item, x, y, size=0.92, color=None, caption=None, caption_size=0.16):
        """(x, y) を左上とする1単位の枠の中央に、縦横比を保ったまま画像を置く（切り抜かない）。"""
        color = color or (NORMAL_COLOR if item.normal else OUTLIER_COLOR)
        off = (1 - size) / 2
        x0, y0 = x + off, y + off
        self.ax.add_patch(Rectangle((x0, y0), size, size, fc=BG, ec="none", zorder=1))
        im = Image.open(item.path).convert("RGB")
        w, h = im.size
        s = size * 0.94 / max(w, h)
        iw, ih = w * s, h * s
        ix, iy = x0 + (size - iw) / 2, y0 + (size - ih) / 2
        self.ax.imshow(np.asarray(im), extent=(ix, ix + iw, iy + ih, iy), zorder=2, interpolation="antialiased")
        self.ax.add_patch(Rectangle((x0, y0), size, size, fc="none", ec=color, lw=0.035 * self.pt, zorder=3))
        if caption:
            self.text(x + 0.5, y + 1 + caption_size * 0.7, caption, size=caption_size, color=color)


CAPTION_H = 0.3


def _grid(c: Canvas, items, x, y, cols, caption, color=None):
    pitch = 1 + (CAPTION_H if caption else 0)
    for n, it in enumerate(items):
        c.thumb(it, x + n % cols, y + (n // cols) * pitch, color=color, caption=caption(it) if caption else None)


def _rows(n, cols):
    return max(1, math.ceil(n / cols))


def _group(g, n):
    """(見出し, items[, 色]) を (見出し, items, 色) にそろえる。色が無ければ順に割り当てる。"""
    return (g[0], list(g[1]), g[2] if len(g) > 2 else PALETTE[n % len(PALETTE)])


def _counted(title, total, shown):
    return f"{title} {total}枚" + (f"（{shown}枚を表示）" if shown < total else "")


# ---- 図 -------------------------------------------------------------------
def grid_figure(items, cols: int = 10, caption=None, color=None, **canvas_kw):
    """1つの群を左上から順に並べる。caption は Item → 文字列（不要なら None）。"""
    pitch = 1 + (CAPTION_H if caption else 0)
    c = Canvas(cols, _rows(len(items), cols) * pitch, **canvas_kw)
    _grid(c, items, 0, 0, cols, caption, color)
    return c.finish()


def panels_figure(groups, cols_each=None, caption=None, k: int | None = None, how: str = "even",
                  counts: bool = False, **canvas_kw):
    """2〜3群を左右に並べて対比する。groups = [(見出し, items[, 色]), ...]。

    k を渡すと各群を pick(items, k, how) で選ぶ。counts=True か k 指定で、見出しに「N枚（k枚を表示）」を付ける。
    """
    groups = [_group(g, n) for n, g in enumerate(groups)]
    shown = [pick(items, k, how) for _, items, _ in groups]
    gap, head = 0.5, 0.5
    pitch = 1 + (CAPTION_H if caption else 0)
    cols_each = cols_each or _split_columns([len(s) for s in shown])
    rows = max(_rows(len(s), n) for s, n in zip(shown, cols_each))
    c = Canvas(sum(cols_each) + gap * (len(groups) - 1), head + rows * pitch, **canvas_kw)
    x = 0.0
    for (title, items, color), s, n in zip(groups, shown, cols_each):
        if counts or k is not None:
            title = _counted(title, len(items), len(s))
        c.text(x + 0.04, head / 2 - 0.04, title, size=0.2, ha="left", weight="bold", color=color)
        c.hline(head - 0.06, x + 0.04, x + n - 0.04, color=color, lw=0.02)
        _grid(c, s, x, head, n, caption, color)
        x += n + gap
    return c.finish()


def rows_figure(rows, cols: int = 8, caption=None, k: int | None = None, how: str = "even",
                counts: bool = True, head_w: float = 2.6, head_caption=None, **canvas_kw):
    """群を縦に積む（群が多いとき、または1枚とその相手を並べるとき）。rows = [(見出し, items[, 色]), ...]。

    見出しが文字列なら左に「見出し／N枚」を書く。見出しが Item なら、その画像を左に置き、右に相手を並べる
    （誤判定した1枚と、間違えた先の典型例。1枚とその近傍。変更前と変更後）。
    """
    rows = [_group(r, 1) for r in rows]      # 色の指定が無ければ橙（注目する群）
    shown = [pick(items, k, how) for _, items, _ in rows]
    pitch = 1 + (CAPTION_H if caption else 0)
    image_head = any(isinstance(h, Item) for h, _, _ in rows)
    if image_head:
        head_w = 1.0 + 0.5
    heights = [max(_rows(len(s), cols) * pitch, (1 + CAPTION_H) if image_head else 0.0) + 0.16 for s in shown]
    c = Canvas(head_w + cols, sum(heights), **canvas_kw)
    y = 0.0
    for (head, items, color), s, h in zip(rows, shown, heights):
        if isinstance(head, Item):
            c.thumb(head, 0, y + 0.08, color=INK, caption=head_caption(head) if head_caption else None)
            c.text(1.25, y + 0.58, "→", size=0.3, color=MUTED)
        else:
            c.text(0.04, y + 0.36, str(head), size=0.2, ha="left", weight="bold", color=color)
            if counts:
                note = f"{len(items)}枚" + (f"（{len(s)}枚を表示）" if len(s) < len(items) else "")
                c.text(0.04, y + 0.68, note, size=0.16, ha="left", color=MUTED)
        _grid(c, s, head_w, y + 0.08, cols, caption, color)
        y += h
        if y < c.h - 1e-9:
            c.hline(y, 0, c.w, color=LINE, lw=0.012)
    return c.finish()


def matrix_figure(items, row, col, rows=None, cols=None, k: int = 2, cell_cols: int | None = None,
                  row_title: str = "", col_title: str = "", mute=None, color=None, caption=None, **canvas_kw):
    """2つの切り口の表の各マスに、枚数と画像を置く（混同行列、変更の前後、群×期間）。小さい表（4×4 程度まで）向け。

    row / col は Item → 値。rows / cols は並び順（省略時は値の昇順）。各マスは枚数と、並び順に等間隔で選んだ k 枚。
    mute(r, c) が True のマスは枚数だけを灰色で書く（混同行列の対角など、見せなくてよいマス）。
    color(r, c) は枠の色（既定: 行と列の値が同じなら青、違えば橙）。
    """
    cells = cross(items, row, col)
    rows = rows or sorted({r for r, _ in cells})
    cols = cols or sorted({c_ for _, c_ in cells})
    cell_cols = cell_cols or k
    cell_rows = _rows(k, cell_cols)
    cap_h = CAPTION_H if caption else 0.0
    pad, count_h, lab_w, top = 0.14, 0.34, 1.5, 0.8
    cw, ch = cell_cols + pad, count_h + cell_rows * (1 + cap_h) + pad
    c = Canvas(lab_w + len(cols) * cw, top + len(rows) * ch, **canvas_kw)
    if col_title:
        c.text(lab_w + len(cols) * cw / 2, 0.2, col_title, size=0.17, color=MUTED)
    if row_title:
        c.text(0.2, top + len(rows) * ch / 2, row_title, size=0.17, color=MUTED, rotation=90)
    for j, cv in enumerate(cols):
        c.text(lab_w + j * cw + cw / 2, 0.58, str(cv), size=0.2, weight="bold")
    for i, rv in enumerate(rows):
        y = top + i * ch
        c.text(lab_w - 0.12, y + ch / 2, str(rv), size=0.2, weight="bold", ha="right")
        c.hline(y, 0.45, c.w, color=LINE, lw=0.012)
        for j, cv in enumerate(cols):
            x = lab_w + j * cw
            group = cells.get((rv, cv), [])
            muted = bool(mute and mute(rv, cv))
            ec = color(rv, cv) if color else (NORMAL_COLOR if rv == cv else OUTLIER_COLOR)
            c.text(x + pad / 2 + 0.04, y + count_h / 2 + 0.03, f"{len(group)}枚", size=0.18, ha="left",
                   weight="normal" if muted or not group else "bold", color=MUTED if muted or not group else ec)
            if not muted:
                for n, it in enumerate(pick_evenly(group, k)):
                    c.thumb(it, x + pad / 2 + n % cell_cols, y + count_h + (n // cell_cols) * (1 + cap_h),
                            color=ec, caption=caption(it) if caption else None)
    for j in range(len(cols) + 1):
        c.ax.plot([lab_w + j * cw - (0 if j else 0.02)] * 2, [top, c.h], color=LINE, lw=0.012 * c.pt, zorder=1)
    return c.finish()


def histogram_figure(items, edges, thresholds=(), per_bin=(1, 2), normal_name="正常", outlier_name="外れ値",
                     axis_label="外れ値スコア", caption=None, left_hint=None, right_hint=None,
                     spans=(), spans_label=None, value=None, split=None, **canvas_kw):
    """画像ヒストグラム。数値の軸に沿って区間を並べ、上段と下段にサムネイルを積み、枚数を添える。

    edges は区間の境界（閾値を境界に含めると、線がサムネイルを横切らない）。区間の幅が違っても列の幅は同じ。
    value は Item → 数値（既定: score）。split は Item → bool で、True が上段（既定: normal）。
    上段・下段の名前は normal_name / outlier_name。各区間の画像は並び順に等間隔で選ぶ（per_bin = (上段, 下段) の枚数）。
    thresholds = [(値, ラベル), ...] を境界の位置に縦線で引く。
    spans = [(値a, 値b, ラベル), ...] は、2本の線の間（＝線を動かすと判定が変わる範囲）を下端の括弧で示す。
    """
    value = value or (lambda it: it.score)
    split = split or (lambda it: it.normal)
    nb = len(edges) - 1
    k_up, k_down = per_bin
    lab_w, pad_r, axis_h, count_h, top = 1.5, 0.3, 0.55, 0.3, 0.45
    cap_h = CAPTION_H if caption else 0.0
    up_h = k_up * 1.0 + count_h
    down_h = k_down * (1.0 + cap_h) + count_h
    span_h = 0.42 if spans else 0.0
    c = Canvas(lab_w + nb + pad_r, top + up_h + axis_h + down_h + span_h, **canvas_kw)
    y_axis = top + up_h

    def xpos(v):
        for b in range(nb):
            if edges[b] <= v <= edges[b + 1]:
                return lab_w + b + (v - edges[b]) / (edges[b + 1] - edges[b])
        return lab_w + (0 if v < edges[0] else nb)

    for b in range(nb):
        last = b == nb - 1
        inbin = [i for i in items if edges[b] < value(i) <= edges[b + 1] or (b == 0 and value(i) == edges[0])
                 or (last and value(i) > edges[-1])]
        ups, downs = [i for i in inbin if split(i)], [i for i in inbin if not split(i)]
        x = lab_w + b
        shown = pick_evenly(ups, k_up)
        for n, it in enumerate(reversed(shown)):
            c.thumb(it, x, y_axis - 1 - n, color=NORMAL_COLOR)
        if ups:
            c.text(x + 0.5, y_axis - len(shown) - count_h / 2, f"{len(ups)}枚", size=0.17, color=NORMAL_COLOR)
        shown = pick_evenly(downs, k_down)
        for n, it in enumerate(shown):
            c.thumb(it, x, y_axis + axis_h + n * (1 + cap_h), color=OUTLIER_COLOR,
                    caption=caption(it) if caption else None)
        if downs:
            c.text(x + 0.5, y_axis + axis_h + len(shown) * (1 + cap_h) + count_h / 2, f"{len(downs)}枚",
                   size=0.17, color=OUTLIER_COLOR)

    y_mid = y_axis + axis_h / 2
    c.hline(y_mid - 0.1, lab_w, lab_w + nb, color=INK, lw=0.02)
    tvals = [t for t, _ in thresholds]
    for b in range(nb + 1):
        on_line = any(abs(edges[b] - t) < 1e-12 for t in tvals)
        c.vline(lab_w + b, y_mid - 0.16, y_mid - 0.04, lw=0.015)
        c.text(lab_w + b, y_mid + 0.12, f"{edges[b]:.2f}", size=0.15, color=INK if on_line else MUTED,
               weight="bold" if on_line else "normal", zorder=6,
               bbox=dict(fc="white", ec="none", pad=0.02 * c.pt) if on_line else None)
    c.text(lab_w - 0.12, y_mid - 0.1, axis_label, size=0.16, color=MUTED, ha="right")
    c.text(lab_w - 0.12, y_axis - k_up / 2, normal_name, size=0.22, color=NORMAL_COLOR, ha="right", weight="bold")
    c.text(lab_w - 0.12, y_axis + axis_h + k_down * (1 + cap_h) / 2, outlier_name, size=0.22, color=OUTLIER_COLOR,
           ha="right", weight="bold")
    y_span = c.h - span_h / 2
    for a, b, label in spans:
        xa, xb = sorted((xpos(a), xpos(b)))
        c.hline(y_span, xa + 0.06, xb - 0.06, color=INK, lw=0.02)
        c.text((xa + xb) / 2, y_span, label, size=0.17, weight="bold", zorder=6,
               bbox=dict(fc="white", ec="none", pad=0.03 * c.pt))
    if spans and spans_label:
        first = min(xpos(min(a, b)) for a, b, _ in spans)
        c.text(first - 0.12, y_span, spans_label, size=0.16, color=INK, ha="right")
    for t, label in thresholds:
        c.vline(xpos(t), top * 0.9, c.h, lw=0.035)
        c.text(xpos(t), top * 0.42, label, size=0.18, weight="bold")
    if left_hint:
        c.text(lab_w + 0.05, top * 0.42, left_hint, size=0.17, color=MUTED, ha="left")
    if right_hint:
        c.text(lab_w + nb - 0.05, top * 0.42, right_hint, size=0.17, color=MUTED, ha="right")
    return c.finish()


def _split_columns(counts, total: int = 12) -> list[int]:
    """横に並べる群の列数を、枚数に比例して total 列に割り振る（各群は2列以上、枚数以下）。"""
    counts = [max(1, n) for n in counts]
    if len(counts) == 1:
        return [min(counts[0], total)]
    cols = [max(2, round(total * n / sum(counts))) for n in counts]
    return [min(c, n) for c, n in zip(cols, counts)]


def moved_figure(items, t_from: float, t_to: float, cols_each=None, caption=None,
                 outlier_title="外れ値に移る 外れ値", normal_title="巻き添えで外れ値に移る 正常", **canvas_kw):
    """閾値を t_from → t_to に動かしたときに判定が変わる画像を、全数、正しく移る群と巻き添えの群に分けて並べる。"""
    mv = moved(items, t_from, t_to)
    out, norm = [i for i in mv if not i.normal], [i for i in mv if i.normal]
    groups = [(f"{outlier_title} {len(out)}枚", out, OUTLIER_COLOR), (f"{normal_title} {len(norm)}枚", norm, NORMAL_COLOR)]
    keep = [n for n, g in enumerate(groups) if g[1]]
    cols = [cols_each[n] for n in keep] if cols_each else _split_columns([len(groups[n][1]) for n in keep])
    cap = (lambda it: "" if it.normal else caption(it)) if caption else None
    return panels_figure([groups[n] for n in keep], cols_each=cols, caption=cap, **canvas_kw)


# ---- CLI ------------------------------------------------------------------
def _where(items, conditions):
    for cond in conditions or []:
        col, _, val = cond.partition("=")
        items = [it for it in items if it.get(col) == val]
    return items


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = ap.add_subparsers(dest="cmd", required=True)

    gr = sub.add_parser("groups", help="切り口（列の値）ごとに画像を並べる")
    gr.add_argument("--table", required=True)
    gr.add_argument("--thumbs", required=True)
    gr.add_argument("--by", required=True, help="群に分ける列。カンマ区切りで複数（例 true,pred）")
    gr.add_argument("--where", action="append", help="列=値 で絞り込む（複数可）")
    gr.add_argument("--k", type=int, help="各群で見せる枚数（省略時は全数）")
    gr.add_argument("--how", default="even", choices=["even", "top", "bottom", "random"])
    gr.add_argument("--sort", help="選ぶ前に並べる数値の列")
    gr.add_argument("--caption", help="画像の下に書く列")
    gr.add_argument("--out", required=True)

    mx = sub.add_parser("matrix", help="2つの列の表の各マスに、枚数と画像を置く")
    mx.add_argument("--table", required=True)
    mx.add_argument("--thumbs", required=True)
    mx.add_argument("--row", required=True)
    mx.add_argument("--col", required=True)
    mx.add_argument("--k", type=int, default=2)
    mx.add_argument("--show-diagonal", action="store_true", help="行と列の値が同じマスにも画像を置く")
    mx.add_argument("--out", required=True)

    mv = sub.add_parser("moved", help="2つの閾値の間で判定が変わる画像を1枚にする")
    mv.add_argument("--scores", required=True)
    mv.add_argument("--thumbs", required=True)
    mv.add_argument("--normal-group", required=True, help="正常とみなす group の値")
    mv.add_argument("--from-loss", type=float, required=True, help="いまの動作点（較正用の正常画像を失う割合。例 0.01）")
    mv.add_argument("--to-loss", type=float, required=True, help="候補の動作点（例 0.05）")
    mv.add_argument("--cal-role", default="cal")
    mv.add_argument("--eval-role", default="eval")
    mv.add_argument("--label-col", default="label_ja")
    mv.add_argument("--out", required=True)
    a = ap.parse_args()

    if a.cmd == "groups":
        items = _where(load_table(a.table, a.thumbs), a.where)
        if a.sort:
            items.sort(key=lambda it: it.num(a.sort))
        by = a.by.split(",")
        groups = split_by(items, lambda it: tuple(it[c] for c in by))
        if not groups:
            print("条件に合う画像はない")
            return 0
        cap = (lambda it: it[a.caption]) if a.caption else None
        fig = rows_figure([(" → ".join(v), g) for v, g in groups], k=a.k, how=a.how, caption=cap)
        fig.savefig(a.out, dpi=200)
        print("; ".join(f"{' → '.join(v)}: {len(g)}" for v, g in groups), "->", a.out)
        return 0

    if a.cmd == "matrix":
        items = load_table(a.table, a.thumbs)
        mute = None if a.show_diagonal else (lambda r, c: r == c)
        fig = matrix_figure(items, lambda it: it[a.row], lambda it: it[a.col], k=a.k, mute=mute,
                            row_title=a.row, col_title=a.col)
        fig.savefig(a.out, dpi=200)
        print(f"{len(items)} images -> {a.out}")
        return 0

    everything = load_items(a.scores, a.thumbs, a.normal_group, label_col=a.label_col)
    cal = [i.score for i in everything if i.role == a.cal_role and i.normal]
    ev = [i for i in everything if i.role == a.eval_role]
    t0, t1 = threshold_for_loss(cal, a.from_loss), threshold_for_loss(cal, a.to_loss)
    mvd = moved(ev, t0, t1)
    if not mvd:
        print(f"threshold {t0:.4f} -> {t1:.4f}: 判定が変わる画像はない")
        return 0
    fig = moved_figure(ev, t0, t1, caption=lambda it: it.label)
    fig.savefig(a.out, dpi=200)
    n_out = sum(not i.normal for i in mvd)
    print(f"threshold {t0:.4f} -> {t1:.4f}: {len(mvd)} images change "
          f"({n_out} outliers, {len(mvd) - n_out} normals) -> {a.out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
