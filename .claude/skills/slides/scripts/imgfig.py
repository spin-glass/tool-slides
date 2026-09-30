#!/usr/bin/env python3
"""スライド用の画像図を matplotlib で描く（サムネイルの格子・画像ヒストグラム・閾値の間で動く画像）。

図は1枚の PNG になるので revealjs / pptx / PDF のどれでも同じ見た目で出る。
寸法は「1単位 = サムネイル1枚の幅」で組み、文字は単位に比例させる。横12インチの図で1単位が1インチ前後
（スライド上で約100px）になる枚数に抑えると、サムネイルの中身とラベルが読める。

qmd からの使い方:
    import sys; sys.path.insert(0, "../../.claude/skills/slides/scripts")
    import imgfig
    items = imgfig.load_items("data/scores.csv", "data/thumbs", normal_group="dog", role="eval")
    t1 = imgfig.threshold_for_loss(cal_scores, 0.01)
    imgfig.moved_figure(items, t_from=t1, t_to=t5, caption=lambda it: it.label)

CLI（自分のデータで「2つの閾値の間で判定が変わる画像」を1枚にする）:
    python imgfig.py moved --scores scores.csv --thumbs thumbs/ --normal-group dog \\
        --from-loss 0.01 --to-loss 0.05 --out moved.png
scores.csv の列: id, role(cal/eval), group, label, score（大きいほど外れ値）。画像は <thumbs>/<id>.jpg。
"""
from __future__ import annotations

import argparse
import csv
import math
from dataclasses import dataclass
from pathlib import Path

import matplotlib.pyplot as plt
import numpy as np
from matplotlib.patches import Rectangle
from PIL import Image

NORMAL_COLOR = "#0b5cad"     # 正常（青）
OUTLIER_COLOR = "#d9480f"    # 外れ値（橙）。青と橙は色覚の違いがあっても区別しやすい
INK = "#1f2328"
MUTED = "#57606a"
BG = "#f3f4f6"
FONT_CANDIDATES = ["Hiragino Sans", "Noto Sans CJK JP", "Noto Sans JP", "IPAexGothic", "Yu Gothic"]


def japanese_fonts() -> list[str]:
    """入っている日本語フォントだけを返す（無いフォントを指定すると警告が大量に出るため）。"""
    from matplotlib import font_manager

    have = {f.name for f in font_manager.fontManager.ttflist}
    return [f for f in FONT_CANDIDATES if f in have] + ["sans-serif"]


@dataclass(frozen=True)
class Item:
    id: str
    path: Path
    score: float
    normal: bool
    label: str
    role: str = ""


def load_items(scores_csv, thumbs_dir, normal_group: str, role: str | None = None,
               group_col: str = "group", label_col: str = "label_ja") -> list[Item]:
    """scores.csv を読み、スコアの小さい順に返す。"""
    items = []
    with open(scores_csv, newline="", encoding="utf-8") as f:
        for r in csv.DictReader(f):
            if role and r.get("role") != role:
                continue
            label = r.get(label_col) or r.get("label") or r[group_col]
            items.append(Item(r["id"], Path(thumbs_dir) / f"{r['id']}.jpg", float(r["score"]),
                              r[group_col] == normal_group, label, r.get("role", "")))
    return sorted(items, key=lambda i: i.score)


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


def pick_evenly(items, k: int) -> list[Item]:
    """スコア順に等間隔で最大 k 枚を選ぶ（k 等分した各区間の中央）。見せる画像を恣意的に選ばないための規則。"""
    n = len(items)
    if n <= k:
        return list(items)
    return [items[min(n - 1, int((j + 0.5) * n / k))] for j in range(k)]


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


def _grid(c: Canvas, items, x, y, cols, caption):
    pitch = 1 + (CAPTION_H if caption else 0)
    for n, it in enumerate(items):
        c.thumb(it, x + n % cols, y + (n // cols) * pitch, caption=caption(it) if caption else None)


def _rows(n, cols):
    return max(1, math.ceil(n / cols))


# ---- 図 -------------------------------------------------------------------
def grid_figure(items, cols: int = 10, caption=None, **canvas_kw):
    """サムネイルを左上から順に並べる。caption は Item → 文字列（不要なら None）。"""
    pitch = 1 + (CAPTION_H if caption else 0)
    c = Canvas(cols, _rows(len(items), cols) * pitch, **canvas_kw)
    _grid(c, items, 0, 0, cols, caption)
    return c.finish()


def panels_figure(groups, cols_each=None, caption=None, **canvas_kw):
    """複数の群を左右に並べる。groups = [(見出し, items, 色), ...]。caption は Item → 文字列。"""
    gap, head = 0.5, 0.5
    pitch = 1 + (CAPTION_H if caption else 0)
    cols_each = cols_each or [max(1, min(6, len(g[1]))) for g in groups]
    rows = max(_rows(len(g[1]), n) for g, n in zip(groups, cols_each))
    c = Canvas(sum(cols_each) + gap * (len(groups) - 1), head + rows * pitch, **canvas_kw)
    x = 0.0
    for (title, items, color), n in zip(groups, cols_each):
        c.text(x + 0.04, head / 2 - 0.04, title, size=0.2, ha="left", weight="bold", color=color)
        c.hline(head - 0.06, x + 0.04, x + n - 0.04, color=color, lw=0.02)
        _grid(c, items, x, head, n, caption)
        x += n + gap
    return c.finish()


def histogram_figure(items, edges, thresholds=(), per_bin=(1, 2), normal_name="正常", outlier_name="外れ値",
                     axis_label="外れ値スコア", caption=None, left_hint=None, right_hint=None,
                     spans=(), spans_label=None, **canvas_kw):
    """画像ヒストグラム。横に区間を並べ、上に正常・下に外れ値のサムネイルを積み、枚数を添える。

    edges は区間の境界（閾値を境界に含めると、線がサムネイルを横切らない）。区間の幅が違っても列の幅は同じ。
    各区間の画像は pick_evenly で選ぶ（per_bin = (正常の枚数, 外れ値の枚数)）。
    thresholds = [(値, ラベル), ...] を境界の位置に縦線で引く。
    spans = [(値a, 値b, ラベル), ...] は、2本の線の間（＝線を動かすと判定が変わる範囲）を下端の括弧で示す。
    """
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
        inbin = [i for i in items if edges[b] < i.score <= edges[b + 1] or (b == 0 and i.score == edges[0])
                 or (last and i.score > edges[-1])]
        normals, outliers = [i for i in inbin if i.normal], [i for i in inbin if not i.normal]
        x = lab_w + b
        shown = pick_evenly(normals, k_up)
        for n, it in enumerate(reversed(shown)):
            c.thumb(it, x, y_axis - 1 - n)
        if normals:
            c.text(x + 0.5, y_axis - len(shown) - count_h / 2, f"{len(normals)}枚", size=0.17, color=NORMAL_COLOR)
        shown = pick_evenly(outliers, k_down)
        for n, it in enumerate(shown):
            c.thumb(it, x, y_axis + axis_h + n * (1 + cap_h), caption=caption(it) if caption else None)
        if outliers:
            c.text(x + 0.5, y_axis + axis_h + len(shown) * (1 + cap_h) + count_h / 2, f"{len(outliers)}枚",
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
    if len(counts) == 1:
        return [min(counts[0], total)]
    cols = [max(2, round(total * c / sum(counts))) for c in counts]
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
def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = ap.add_subparsers(dest="cmd", required=True)
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
