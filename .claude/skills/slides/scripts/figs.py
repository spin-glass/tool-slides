"""Claude Design「スライド型見本」の図の型を matplotlib で描く。qmd から import して使う。

    import sys; from pathlib import Path
    sys.path.insert(0, str(Path("../../.claude/skills/slides/scripts").resolve()))
    import figs
    figs.setup()                                   # 文字・色をデッキにそろえる（最初のセルで1回）
    figs.timeline([("試験導入", 0, 0.9), ("並行運用", 1.1, 0.8, figs.ORANGE)], ["1か月目", "2か月目"])
    figs.direction([("閾値を上げる", [("読み誤り ↓", 0.6), ("「保留」↑", 0.7, figs.ORANGE)])])
    figs.bars(["A", "B", "C"], [12, 30, 8], highlight="B", unit="件")

型の一覧と使い分けは references/slide_types.md。色は theme/custom.scss と imgfig と同じ値。
"""
from __future__ import annotations

from typing import Sequence

import matplotlib.pyplot as plt

from imgfig import BLUE, INK, LINE, MUTED, ORANGE, japanese_fonts

GRAY = "#9aa4ae"     # 強調しない系列・枠線（$series-gray）。白地の文字には使わない（2.6:1）
FONT_SIZE = 18       # fig-width 7〜13 のとき、スライド上で約20px
LABEL_SIZE = 20      # 段の見出し（流れ図の箱と同じ20px以上）


def setup(font_size: float = FONT_SIZE) -> None:
    """日本語フォントと文字の大きさをそろえる。"""
    plt.rcParams["font.family"] = japanese_fonts()
    plt.rcParams["font.size"] = font_size
    plt.rcParams["text.color"] = INK
    plt.rcParams["axes.edgecolor"] = LINE


def _bare(ax) -> None:
    for side in ("top", "right", "bottom", "left"):
        ax.spines[side].set_visible(False)
    ax.tick_params(length=0)


def timeline(stages: Sequence[tuple], periods: Sequence[str], ax=None):
    """工程表（型 timeline）。stages は (名前, 開始, 長さ[, 色]) で、単位は periods の1区切り。

    既定の色は青。注目させる段（並行運用など、聴衆の作業が増える段）だけ橙にする。
    """
    if ax is None:
        _, ax = plt.subplots()
    for i, st in enumerate(stages):
        name, start, length = st[:3]
        color = st[3] if len(st) > 3 else BLUE
        ax.broken_barh([(start, length)], (-i - 0.3, 0.6), color=color)
    ax.set_yticks([-i for i in range(len(stages))], [st[0] for st in stages])
    ax.set_xticks(range(len(periods)), periods, ha="left", color=MUTED)
    ax.xaxis.tick_top()
    ax.set_xlim(0, len(periods))
    ax.set_ylim(-len(stages) + 0.4, 0.5)
    for x in range(len(periods)):
        ax.axvline(x, color=LINE, lw=1)
    _bare(ax)
    plt.tight_layout()
    return ax


def direction(groups: Sequence[tuple[str, Sequence[tuple]]], ax=None):
    """関係の向きの図（型 direction）。実測値が無いとき「AするとBが増え、Cが減る」を棒の向きで示す。

    groups は (見出し, [(ラベル, 長さ0〜1[, 色]), ...])。棒の長さは向きの目安で、実測値ではない。
    スライドには「棒の長さは関係の向きを示す。実測値ではない」と但し書きを添える。
    """
    if ax is None:
        _, ax = plt.subplots()
    y = 0.0
    for head, rows in groups:
        top = y
        for row in rows:
            label, w = row[:2]
            color = row[2] if len(row) > 2 else BLUE
            if not 0 <= w <= 1:
                raise ValueError(f"長さは0〜1（向きの目安）: {label} {w}")
            ax.barh(y, w, height=0.6, color=color)
            ax.text(w + 0.03, y, label, va="center")
            y -= 1
        ax.text(-0.05, (top + y + 1) / 2, head, ha="right", va="center", fontsize=LABEL_SIZE)
        y -= 0.4
    ax.set_xlim(-0.75, 1.25)
    ax.axis("off")
    plt.tight_layout()
    return ax


def bars(labels: Sequence[str], values: Sequence[float], highlight: str | Sequence[str] = (),
         unit: str = "", fmt: str = "{:g}", ax=None):
    """横棒（型 chart）。主張に関わる棒だけ青、残りは灰。値は棒の右に書き、軸は消す。"""
    if len(labels) != len(values):
        raise ValueError("labels と values の数が違う")
    hl = {highlight} if isinstance(highlight, str) else set(highlight)
    unknown = hl - set(labels)
    if unknown:
        raise ValueError(f"highlight が labels にない: {sorted(unknown)}")
    if ax is None:
        _, ax = plt.subplots()
    top = max(values) if values else 1
    for i, (lab, v) in enumerate(zip(labels, values)):
        on = lab in hl
        ax.barh(-i, v, height=0.6, color=BLUE if on else GRAY)
        ax.text(v + top * 0.02, -i, fmt.format(v) + unit, va="center",
                color=INK if on else MUTED, weight="bold" if on else "normal")
    ax.set_yticks([-i for i in range(len(labels))], labels)
    ax.set_xticks([])
    ax.set_xlim(0, top * 1.18)
    _bare(ax)
    plt.tight_layout()
    return ax
