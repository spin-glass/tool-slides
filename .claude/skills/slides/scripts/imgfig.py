#!/usr/bin/env python3
"""スライド用の「具体例の画像」の図を matplotlib で描く。

型は1つ: 数の主張を、その数の中身の画像で見せる。
  1. 表を読む          items = load_table("data/table.csv", "data/thumbs")      # 1行 = 1画像
  2. 切り口で群に分ける   groups = split_by(items, lambda it: (it["true"], it["pred"]))
  3. 見せる画像を選ぶ    shown = pick(group, 12, how="even")   # 全数 / 等間隔 / 上位 / 無作為。選び方は pick_note で書く
  4. 並べる             grid_figure（1群） / panels_figure（2〜3群の対比） / flow_figure（小さい群がたくさん）
                       rows_figure（1枚と相手・群ごとに1段） / matrix_figure（2軸の表） / histogram_figure（数値の軸に沿う）

閾値の切り口には近道がある: threshold_for_loss / flagged / moved / moved_figure。

図は1枚の画像になるので revealjs / pptx / PDF のどれでも同じ見た目で出る。
寸法は「1単位 = サムネイル1枚の幅」で組み、文字は単位に比例させる。列数を省くと、スライドの図の領域
（タイトル・bullets 2つ・出典行を除いた約1180×400px）で1枚が最も大きくなる列数を選ぶ。
1枚の大きさはスライド上で150px以上が目安（1つの図に12〜16枚まで）。100pxを切ると何が写っているかが読めない。
大きさの目安は render_check.sh が図ごとに表示する（環境変数 IMGFIG_REPORT のファイルに書き出したものを読む）。

qmd からの使い方:
    import sys; sys.path.insert(0, "../../.claude/skills/slides/scripts")
    import imgfig
    items = imgfig.load_table("data/table.csv", "data/thumbs")
    wrong = [it for it in items if it["true"] != it["pred"]]
    groups = imgfig.split_by(wrong, lambda it: (it["true"], it["pred"]))          # 枚数の多い順
    imgfig.grid_figure(groups[0][1], caption=lambda it: f"{it['true']}→{it['pred']}\n{it['note']}");   # 最も多い群を大きく
    imgfig.flow_figure([(f"{t} → {p}", g) for (t, p), g in groups[1:]]);                               # 残りの小さい群を詰めて

CLI（qmd を書かずに1枚の図にする）:
    python imgfig.py groups --table table.csv --thumbs thumbs/ --by true,pred --where result=wrong --out groups.png
    python imgfig.py matrix --table table.csv --thumbs thumbs/ --row true --col pred --out matrix.png
    python imgfig.py moved  --scores scores.csv --thumbs thumbs/ --normal-group dog --from-loss 0.01 --to-loss 0.05 --out moved.png
    python imgfig.py sheet  --table table.csv --thumbs thumbs/ --where result=wrong --caption true,pred --credits credits.csv --out check.jpg
                            （確認用。見せる画像を元の大きさで並べる。画像について書く前に Read で見る）
表の列は自由（id 列が必須）。画像は <thumbs>/<id>.jpg。
"""
from __future__ import annotations

import argparse
import csv
import json
import math
import os
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
SLIDE_BOX = (1180, 400)      # 図に使える領域の目安（px）。1280×720 のスライドから、タイトル・bullets 2つ・出典行を除いた分
SLIDE_BOX_TALL = (1180, 500) # bullets を置かないスライドで、図に使える領域の目安
MIN_UNIT_PX = 100            # スライド上でこれより小さいサムネイルは、何が写っているかが読めない
WIDE_CELL = 0.8              # 横長の写真が大半のときの枠の高さ（幅を1として）


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
def unit_px(w_units: float, h_units: float, box=SLIDE_BOX) -> float:
    """図をスライドの図の領域（box）に入れたときの、1単位（サムネイル1枚の幅）の大きさの目安（px）。"""
    return min(box[0] / w_units, box[1] / h_units)


class Canvas:
    """左上が原点、1単位 = サムネイル1枚の幅。width_in × max_height_in に収まるよう全体を縮める。

    cell_h はサムネイルの枠の高さ（単位）。横長の写真が大半なら 1 より小さくすると、同じ図の高さで1枚が大きくなる。
    """

    def __init__(self, w_units: float, h_units: float, width_in: float = 12.0, max_height_in: float = 5.6,
                 cell_h: float = 1.0, kind: str = ""):
        plt.rcParams["font.family"] = japanese_fonts()
        scale = min(width_in / w_units, max_height_in / h_units)
        self.fig = plt.figure(figsize=(w_units * scale, h_units * scale))
        self.ax = self.fig.add_axes([0, 0, 1, 1])
        self.ax.axis("off")
        self.ax.autoscale(False)
        self.w, self.h = w_units, h_units
        self.unit_in = scale            # 1単位の実寸（インチ）
        self.pt = scale * 72.0          # 1単位あたりのポイント数
        self.cell_h, self.kind, self.n_thumbs = cell_h, kind, 0

    def finish(self):
        self.ax.set_xlim(0, self.w)
        self.ax.set_ylim(self.h, 0)
        self.ax.set_aspect("equal")
        px, px_tall = unit_px(self.w, self.h), unit_px(self.w, self.h, SLIDE_BOX_TALL)
        if os.environ.get("IMGFIG_REPORT"):        # render_check.sh が図ごとの大きさを表示するための記録
            with open(os.environ["IMGFIG_REPORT"], "a", encoding="utf-8") as f:
                f.write(json.dumps({"kind": self.kind, "thumbs": self.n_thumbs, "px": round(px),
                                    "px_tall": round(px_tall)}) + "\n")
        if self.n_thumbs and px_tall < MIN_UNIT_PX:
            warnings.warn(f"サムネイルが小さい（bullets を置かなくても、スライド上で約{px_tall:.0f}px）。"
                          "見せる枚数を減らす（pick）か、図を分ける。全数は appendix に回せる", stacklevel=3)
        return self.fig

    def text(self, x, y, s, size=0.17, color=INK, ha="center", va="center", weight="normal", **kw):
        self.ax.text(x, y, s, fontsize=size * self.pt, color=color, ha=ha, va=va, weight=weight, **kw)

    def vline(self, x, y0, y1, color=INK, lw=0.03):
        self.ax.plot([x, x], [y0, y1], color=color, lw=lw * self.pt, solid_capstyle="butt", zorder=5)

    def hline(self, y, x0, x1, color=MUTED, lw=0.012):
        self.ax.plot([x0, x1], [y, y], color=color, lw=lw * self.pt, solid_capstyle="butt", zorder=1)

    def thumb(self, item: Item, x, y, size=0.92, color=None, caption=None, caption_size=0.16):
        """(x, y) を左上とする枠（幅1 × 高さ cell_h）の中央に、縦横比を保ったまま画像を置く（切り抜かない）。

        caption は画像の下に書く文字列。改行で複数行にできる（1行目は枠の色、2行目以降は黒）。
        """
        color = color or (NORMAL_COLOR if item.normal else OUTLIER_COLOR)
        off = (1 - size) / 2
        x0, y0 = x + off, y + off
        fw, fh = size, self.cell_h - 2 * off
        self.ax.add_patch(Rectangle((x0, y0), fw, fh, fc=BG, ec="none", zorder=1))
        im = Image.open(item.path).convert("RGB")
        w, h = im.size
        s = 0.94 * min(fw / w, fh / h)
        iw, ih = w * s, h * s
        ix, iy = x0 + (fw - iw) / 2, y0 + (fh - ih) / 2
        self.ax.imshow(np.asarray(im), extent=(ix, ix + iw, iy + ih, iy), zorder=2, interpolation="antialiased")
        self.ax.add_patch(Rectangle((x0, y0), fw, fh, fc="none", ec=color, lw=0.035 * self.pt, zorder=3))
        self.n_thumbs += 1
        for n, line in enumerate(str(caption).split("\n") if caption else []):
            self.text(x + 0.5, y + self.cell_h + caption_size * 0.7 + n * CAPTION_LINE, line, size=caption_size,
                      color=color if n == 0 else INK)


CAPTION_H = 0.3              # 説明文1行ぶんの高さ
CAPTION_LINE = 0.24          # 2行目以降の行送り


def _cell_h(items, aspect) -> float:
    """サムネイルの枠の高さ（幅を1として）。aspect を省くと、見せる画像の4分の3以上が横長なら横長の枠にする。"""
    if aspect is not None:
        return float(aspect)
    tall = n = 0
    for it in items:
        try:
            with Image.open(it.path) as im:
                n += 1
                tall += im.height > WIDE_CELL * im.width
        except OSError:
            continue
    return WIDE_CELL if n and tall <= n / 4 else 1.0


def _cap_h(items, caption) -> float:
    """説明文の高さ（単位）。caption が改行を含む文字列を返すときは行数ぶん取る。"""
    if not caption:
        return 0.0
    lines = max((str(caption(it)).count("\n") + 1 for it in items), default=1)
    return CAPTION_H + (lines - 1) * CAPTION_LINE


def _text_w(text: str, size: float) -> float:
    """文字列のおおよその幅（単位）。全角は size、半角はその半分強とみなす。"""
    return sum(size if ord(ch) > 0x2E7F else size * 0.58 for ch in text) + 0.12


def _best(candidates):
    """(列数など, 幅, 高さ) の候補から、スライド上で1枚が最も大きくなるものを返す（同じなら先の候補）。"""
    return max(candidates, key=lambda c: round(unit_px(c[1], c[2]), 1))[0]


def _grid(c: Canvas, items, x, y, cols, caption, color=None, cap_h=None):
    pitch = c.cell_h + (_cap_h(items, caption) if cap_h is None else cap_h)
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
def grid_figure(items, cols: int | None = None, caption=None, color=None, aspect=None, **canvas_kw):
    """1つの群を左上から順に並べる。caption は Item → 文字列（不要なら None。改行で2行にできる）。

    cols を省くと、スライド上で1枚が最も大きくなる列数にする。aspect は枠の高さ（幅を1として。省くと写真に合わせる）。
    """
    items = list(items)
    ch, cap = _cell_h(items, aspect), _cap_h(items, caption)
    pitch = ch + cap
    cols = cols or _best((n, n, _rows(len(items), n) * pitch) for n in range(1, 13))
    c = Canvas(cols, _rows(len(items), cols) * pitch, cell_h=ch, kind="grid", **canvas_kw)
    _grid(c, items, 0, 0, cols, caption, color, cap)
    return c.finish()


def panels_figure(groups, cols_each=None, caption=None, k: int | None = None, how: str = "even",
                  counts: bool = False, aspect=None, **canvas_kw):
    """2〜3群を左右に並べて対比する。groups = [(見出し, items[, 色]), ...]。

    k を渡すと各群を pick(items, k, how) で選ぶ。counts=True か k 指定で、見出しに「N枚（k枚を表示）」を付ける。
    cols_each を省くと、スライド上で1枚が最も大きくなる列数の割り振りにする。
    """
    groups = [_group(g, n) for n, g in enumerate(groups)]
    shown = [pick(items, k, how) for _, items, _ in groups]
    every = [it for s in shown for it in s]
    gap, head = 0.5, 0.5
    ch, cap = _cell_h(every, aspect), _cap_h(every, caption)
    pitch = ch + cap

    def size(cols):
        return sum(cols) + gap * (len(groups) - 1), head + max(_rows(len(s), n) for s, n in zip(shown, cols)) * pitch

    if not cols_each:
        splits = [_split_columns([len(s) for s in shown], total) for total in range(2 * len(groups), 13)]
        cols_each = _best((cols, *size(cols)) for cols in splits)
    c = Canvas(*size(cols_each), cell_h=ch, kind="panels", **canvas_kw)
    x = 0.0
    for (title, items, color), s, n in zip(groups, shown, cols_each):
        if counts or k is not None:
            title = _counted(title, len(items), len(s))
        c.text(x + 0.04, head / 2 - 0.04, title, size=0.2, ha="left", weight="bold", color=color)
        c.hline(head - 0.06, x + 0.04, x + n - 0.04, color=color, lw=0.02)
        _grid(c, s, x, head, n, caption, color, cap)
        x += n + gap
    return c.finish()


def _flow_lines(counts, label_ws, width: float, gap: float = 0.4) -> list[list[tuple]]:
    """群を左から詰め、幅を超えたら折り返す。各段は [(群の番号, 列数, 幅, x), ...]。"""
    lines, x = [[]], 0.0
    for g, (n, label_w) in enumerate(zip(counts, label_ws)):
        cols = max(1, min(n, int(width)))
        w = max(cols, label_w)
        if lines[-1] and x + w > width + 1e-9:
            lines.append([])
            x = 0.0
        lines[-1].append((g, cols, w, x))
        x += w + gap
    return lines


def flow_figure(groups, width: float | None = None, caption=None, k: int | None = None, how: str = "even",
                counts: bool = True, aspect=None, **canvas_kw):
    """群を左から詰めて並べ、幅を超えたら次の段に折り返す（小さい群がたくさんあるとき。誤りの組ごと、など）。

    groups = [(見出し, items[, 色]), ...]。見出しには「N枚」が付く。width は図の横幅（単位 = サムネイルの枚数）で、
    省くとスライド上で1枚が最も大きくなる幅にする。1群が width より多いときは、その群の中で折り返す。
    """
    groups = [_group(g, 1) for g in groups]       # 色の指定が無ければ橙（注目する群）
    shown = [pick(items, k, how) for _, items, _ in groups]
    every = [it for s in shown for it in s]
    gap, head, line_gap = 0.4, 0.5, 0.2
    ch, cap = _cell_h(every, aspect), _cap_h(every, caption)
    pitch = ch + cap
    labels = [_counted(str(t), len(items), len(s)) if counts else str(t) for (t, items, _), s in zip(groups, shown)]

    def layout(width):
        lines = _flow_lines([len(s) for s in shown], [_text_w(label, 0.2) for label in labels], width, gap)
        heights = [head + max(_rows(len(shown[g]), cols) for g, cols, _, _ in line) * pitch for line in lines]
        return lines, heights, sum(heights) + line_gap * (len(lines) - 1)

    width = width or _best((w, w, layout(w)[2]) for w in range(4, 13))
    lines, heights, total = layout(width)
    c = Canvas(width, total, cell_h=ch, kind="flow", **canvas_kw)
    y = 0.0
    for line, h in zip(lines, heights):
        for g, cols, w, x in line:
            color = groups[g][2]
            c.text(x + 0.04, y + head / 2 - 0.04, labels[g], size=0.2, ha="left", weight="bold", color=color)
            c.hline(y + head - 0.06, x + 0.04, x + w - 0.04, color=color, lw=0.02)
            _grid(c, shown[g], x, y + head, cols, caption, color, cap)
        y += h + line_gap
    return c.finish()


def rows_figure(rows, cols: int | None = None, caption=None, k: int | None = None, how: str = "even",
                counts: bool = True, head_w: float = 2.6, head_caption=None, aspect=None, **canvas_kw):
    """群ごとに1段ずつ縦に積む（1枚とその相手を並べるとき、群を段で比べたいとき）。rows = [(見出し, items[, 色]), ...]。

    見出しが文字列なら左に「見出し／N枚」を書く。見出しが Item なら、その画像を左に置き、右に相手を並べる
    （誤判定した1枚と、間違えた先の典型例。1枚とその近傍。変更前と変更後）。
    小さい群がたくさんあるときは、段が増えて1枚が小さくなる。そのときは flow_figure を使う。
    """
    rows = [_group(r, 1) for r in rows]      # 色の指定が無ければ橙（注目する群）
    shown = [pick(items, k, how) for _, items, _ in rows]
    every = [it for s in shown for it in s] + [h for h, _, _ in rows if isinstance(h, Item)]
    ch, cap = _cell_h(every, aspect), _cap_h([it for s in shown for it in s], caption)
    pitch = ch + cap
    image_head = any(isinstance(h, Item) for h, _, _ in rows)
    if image_head:
        head_w = 1.0 + 0.5

    def heights(cols):
        return [max(_rows(len(s), cols) * pitch, (ch + CAPTION_H) if image_head else 0.78) + 0.16 for s in shown]

    most = max((len(s) for s in shown), default=1)
    cols = cols or _best((n, head_w + n, sum(heights(n))) for n in range(1, max(2, min(most, 12)) + 1))
    hs = heights(cols)
    c = Canvas(head_w + cols, sum(hs), cell_h=ch, kind="rows", **canvas_kw)
    y = 0.0
    for (head, items, color), s, h in zip(rows, shown, hs):
        if isinstance(head, Item):
            c.thumb(head, 0, y + 0.08, color=INK, caption=head_caption(head) if head_caption else None)
            c.text(1.25, y + 0.08 + ch / 2, "→", size=0.3, color=MUTED)
        else:
            c.text(0.04, y + 0.36, str(head), size=0.2, ha="left", weight="bold", color=color)
            if counts:
                note = f"{len(items)}枚" + (f"（{len(s)}枚を表示）" if len(s) < len(items) else "")
                c.text(0.04, y + 0.68, note, size=0.16, ha="left", color=MUTED)
        _grid(c, s, head_w, y + 0.08, cols, caption, color, cap)
        y += h
        if y < c.h - 1e-9:
            c.hline(y, 0, c.w, color=LINE, lw=0.012)
    return c.finish()


def matrix_figure(items, row, col, rows=None, cols=None, k: int = 2, cell_cols: int | None = None,
                  row_title: str = "", col_title: str = "", mute=None, color=None, caption=None, aspect=None,
                  **canvas_kw):
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
    muted = {(r, c_) for r in rows for c_ in cols if mute and mute(r, c_)}
    shown = {rc: pick_evenly(cells.get(rc, []), k) for rc in ((r, c_) for r in rows for c_ in cols) if rc not in muted}
    every = [it for s_ in shown.values() for it in s_]
    th, cap_h = _cell_h(every, aspect), _cap_h(every, caption)
    pad, count_h, lab_w, top = 0.14, 0.34, 1.5, 0.8
    cw, ch = cell_cols + pad, count_h + cell_rows * (th + cap_h) + pad
    c = Canvas(lab_w + len(cols) * cw, top + len(rows) * ch, cell_h=th, kind="matrix", **canvas_kw)
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
            dim = (rv, cv) in muted or not group
            ec = color(rv, cv) if color else (NORMAL_COLOR if rv == cv else OUTLIER_COLOR)
            c.text(x + pad / 2 + 0.04, y + count_h / 2 + 0.03, f"{len(group)}枚", size=0.18, ha="left",
                   weight="normal" if dim else "bold", color=MUTED if dim else ec)
            for n, it in enumerate(shown.get((rv, cv), [])):
                c.thumb(it, x + pad / 2 + n % cell_cols, y + count_h + (n // cell_cols) * (th + cap_h),
                        color=ec, caption=caption(it) if caption else None)
    for j in range(len(cols) + 1):
        c.ax.plot([lab_w + j * cw - (0 if j else 0.02)] * 2, [top, c.h], color=LINE, lw=0.012 * c.pt, zorder=1)
    return c.finish()


def histogram_figure(items, edges, thresholds=(), per_bin=(1, 2), normal_name="正常", outlier_name="外れ値",
                     axis_label="外れ値スコア", caption=None, left_hint=None, right_hint=None,
                     spans=(), spans_label=None, value=None, split=None, aspect=None, **canvas_kw):
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

    def in_bin(b):
        return [i for i in items if edges[b] < value(i) <= edges[b + 1] or (b == 0 and value(i) == edges[0])
                or (b == nb - 1 and value(i) > edges[-1])]

    bins = [([i for i in in_bin(b) if split(i)], [i for i in in_bin(b) if not split(i)]) for b in range(nb)]
    shown = [(pick_evenly(ups, k_up), pick_evenly(downs, k_down)) for ups, downs in bins]
    th = _cell_h([it for u, d in shown for it in u + d], aspect)
    lab_w, pad_r, axis_h, count_h, top = 1.5, 0.3, 0.55, 0.3, 0.45
    cap_h = _cap_h([it for _, d in shown for it in d], caption)
    up_h = k_up * th + count_h
    down_h = k_down * (th + cap_h) + count_h
    span_h = 0.42 if spans else 0.0
    c = Canvas(lab_w + nb + pad_r, top + up_h + axis_h + down_h + span_h, cell_h=th, kind="histogram", **canvas_kw)
    y_axis = top + up_h

    def xpos(v):
        for b in range(nb):
            if edges[b] <= v <= edges[b + 1]:
                return lab_w + b + (v - edges[b]) / (edges[b + 1] - edges[b])
        return lab_w + (0 if v < edges[0] else nb)

    for b, ((ups, downs), (up_shown, down_shown)) in enumerate(zip(bins, shown)):
        x = lab_w + b
        for n, it in enumerate(reversed(up_shown)):
            c.thumb(it, x, y_axis - (n + 1) * th, color=NORMAL_COLOR)
        if ups:
            c.text(x + 0.5, y_axis - len(up_shown) * th - count_h / 2, f"{len(ups)}枚", size=0.17, color=NORMAL_COLOR)
        for n, it in enumerate(down_shown):
            c.thumb(it, x, y_axis + axis_h + n * (th + cap_h), color=OUTLIER_COLOR,
                    caption=caption(it) if caption else None)
        if downs:
            c.text(x + 0.5, y_axis + axis_h + len(down_shown) * (th + cap_h) + count_h / 2, f"{len(downs)}枚",
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
    c.text(lab_w - 0.12, y_axis - k_up * th / 2, normal_name, size=0.22, color=NORMAL_COLOR, ha="right", weight="bold")
    c.text(lab_w - 0.12, y_axis + axis_h + k_down * (th + cap_h) / 2, outlier_name, size=0.22, color=OUTLIER_COLOR,
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


# ---- 確認用のシート（スライドには載せない） --------------------------------------
def review_sheet(items, out, caption=None, cols: int = 6, per_sheet: int = 24) -> list[Path]:
    """画像を元の大きさ（長辺256pxまで）で並べ、#番号と説明を添えた確認用の画像を書く。

    図の縮小画像やスライドのスクショでは、小さく写るもの（車の中の動物、遠くの群れ）や、よく似た種を見分けられない。
    画像について書く前に、この画像を Read で開いて1枚ずつ確かめる。caption は Item → 文字列（改行可。ラベル・データ・
    撮影者の題名など）。枚数が per_sheet を超えると、out の名前に -2, -3 … を付けて分ける。返り値は書いたファイル。
    """
    from PIL import ImageDraw, ImageFont

    font = None
    for path in ("/System/Library/Fonts/ヒラギノ角ゴシック W3.ttc", "/usr/share/fonts/opentype/noto/NotoSansCJK-Regular.ttc"):
        if Path(path).exists():
            font = ImageFont.truetype(path, 17)
            break
    font = font or ImageFont.load_default()
    items, out = list(items), Path(out)
    written = []
    for k in range(0, max(1, len(items)), per_sheet):
        chunk = items[k:k + per_sheet]
        if not chunk:
            break
        c = min(cols, len(chunk))
        rows = (len(chunk) - 1) // c + 1
        cell, text_h = 262, 96
        sheet = Image.new("RGB", (c * cell + 8, rows * (cell + text_h) + 8), "white")
        d = ImageDraw.Draw(sheet)
        for n, it in enumerate(chunk):
            x, y = 4 + (n % c) * cell, 4 + (n // c) * (cell + text_h)
            im = Image.open(it.path).convert("RGB")
            im.thumbnail((256, 256))
            sheet.paste(im, (x + (256 - im.width) // 2, y + (256 - im.height) // 2))
            lines = [f"#{k + n + 1} {it.id}"]
            for part in (str(caption(it)) if caption else "").split("\n"):
                lines += [part[i:i + 15] for i in range(0, len(part), 15)] or [""]
            d.multiline_text((x + 2, y + 258), "\n".join(lines[:5]), fill=INK, font=font, spacing=2)
        name = out if k == 0 else out.with_name(f"{out.stem}-{k // per_sheet + 1}{out.suffix}")
        sheet.save(name, quality=88)
        written.append(name)
    return written


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
    mx.add_argument("--where", action="append", help="列=値 で絞り込む（複数可）")
    mx.add_argument("--k", type=int, default=2)
    mx.add_argument("--show-diagonal", action="store_true", help="行と列の値が同じマスにも画像を置く")
    mx.add_argument("--out", required=True)

    sh = sub.add_parser("sheet", help="画像を元の大きさで並べた確認用の画像を書く（スライドには載せない）")
    sh.add_argument("--table", required=True)
    sh.add_argument("--thumbs", required=True)
    sh.add_argument("--where", action="append", help="列=値 で絞り込む（複数可）")
    sh.add_argument("--ids", help="画像IDをカンマ区切りで（前方一致）")
    sh.add_argument("--caption", help="画像の下に書く列（カンマ区切りで複数）")
    sh.add_argument("--credits", help="撮影者の題名を添える出典の表（id, title の列）")
    sh.add_argument("--out", required=True)

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
        fig = flow_figure([(" → ".join(v), g) for v, g in groups], k=a.k, how=a.how, caption=cap)
        fig.savefig(a.out, dpi=200)
        print("; ".join(f"{' → '.join(v)}: {len(g)}" for v, g in groups), "->", a.out)
        return 0

    if a.cmd == "sheet":
        items = _where(load_table(a.table, a.thumbs), a.where)
        if a.ids:
            want = [x.strip() for x in a.ids.split(",") if x.strip()]
            items = [it for it in items if any(it.id.startswith(w) for w in want)]
        titles = {}
        if a.credits:
            with open(a.credits, newline="", encoding="utf-8") as f:
                titles = {r["id"]: r.get("title", "") for r in csv.DictReader(f)}
        cols = a.caption.split(",") if a.caption else []

        def cap(it):
            parts = [" ".join(it.get(c, "") for c in cols)] if cols else []
            if titles.get(it.id):
                parts.append(f"題名「{titles[it.id]}」")
            return "\n".join(parts)

        files = review_sheet(items, a.out, caption=cap)
        print(f"{len(items)} images -> {', '.join(str(f) for f in files)}")
        return 0

    if a.cmd == "matrix":
        items = _where(load_table(a.table, a.thumbs), a.where)
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
