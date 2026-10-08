#!/usr/bin/env python3
"""スライド用の「具体例の画像」の図を matplotlib で描く。

型は1つ: 数の主張を、その数の中身の画像で見せる。
  1. 表を読む          items = load_table("data/table.csv", "data/thumbs")      # 1行 = 1画像
  2. 切り口で群に分ける   groups = split_by(items, lambda it: (it["true"], it["pred"]))
  3. 見せる画像を選ぶ    shown = pick(group, 12, how="even")   # 全数 / 等間隔 / 上位 / 無作為。選び方は pick_note で書く
  4. 並べる             grid_figure（1群） / panels_figure（2〜3群の対比） / flow_figure（小さい群がたくさん）
                       rows_figure（1枚と相手・群ごとに1段） / matrix_figure（2軸の表） / histogram_figure（数値の軸に沿う）

閾値の切り口には近道がある: threshold_for_loss / flagged / moved / moved_figure。

図の関数は図を返さない（Quarto のセルの最後の式が図だと同じ図が2つ出るため）。図が要るときだけ return_fig=True。
画像ごとの説明（caption）は、枠の幅を超える行を「＋・、」の後ろか「（」の前で折り返す（caption_lines）。
タイトルの枚数は、写真の枚数なら claim、写真の集合に当たらない測った数なら measured で確かめる。

図は1枚の画像になるので revealjs / pptx / PDF のどれでも同じ見た目で出る。
寸法は「1単位 = サムネイル1枚の幅」で組み、文字は単位に比例させる。列数を省くと、スライドの図の領域
（タイトル・bullets 2つ・出典行を除いた約1180×400px）で1枚が最も大きくなる列数を選ぶ。
1枚の大きさはスライド上で150px以上が目安（1つの図に12〜16枚まで）。100pxを切ると何が写っているかが読めない。
枚をまたいで写真の大きさを揃えるときは、どの図の関数にも thumb_in=（1枚の幅のインチ）を渡す。
自前の matplotlib の図（plt.subplots）は、描く前に use_japanese_font() を呼ぶ（呼ばないと日本語が豆腐になる）。
大きさの目安は render_check.sh が図ごとに表示する（環境変数 IMGFIG_REPORT のファイルに書き出したものを読む）。

qmd からの使い方:
    import sys; sys.path.insert(0, "../../.claude/skills/slides/scripts")
    import imgfig
    items = imgfig.load_table("data/table.csv", "data/thumbs")
    wrong = [it for it in items if it["true"] != it["pred"]]
    groups = imgfig.split_by(wrong, lambda it: (it["true"], it["pred"]))          # 枚数の多い順
    imgfig.grid_figure(groups[0][1], caption=lambda it: f"{it['true']}→{it['pred']}\n{it['note']}")    # 最も多い群を大きく
    imgfig.flow_figure([(f"{t} → {p}", g) for (t, p), g in groups[1:]])                                # 残りの小さい群を詰めて

CLI（qmd を書かずに1枚の図にする）:
    python imgfig.py groups --table table.csv --thumbs thumbs/ --by true,pred --where result=wrong --out groups.png
    python imgfig.py matrix --table table.csv --thumbs thumbs/ --row true --col pred --out matrix.png
    python imgfig.py moved  --scores scores.csv --thumbs thumbs/ --normal-group dog --from-loss 0.01 --to-loss 0.05 --out moved.png
    python imgfig.py sheet  --table table.csv --thumbs thumbs/ --where result=wrong --caption true,pred --credits credits.csv --out check.jpg
                            （確認用。見せる画像を大きく並べる。元の写真 images/ があればそれを使う。画像について書く前に Read で見る）
    python imgfig.py locate --image images/<id>.jpg --out locate.jpg
                            （確認用。元の写真に10等分の目盛りを描く。拡大して見せる範囲を 0〜1 の割合で読む）
    python imgfig.py closeup --look data/look.csv --thumbs data/thumbs --classes 犬,猫 --out _check/closeup
                            （確認用。分類の対象かラベルのクラスが写っていないとした写真を、全体と4区画の拡大で1枚ずつ）
表の列は自由（id 列が必須）。画像は <thumbs>/<id>.jpg。thumbs と同じ階層に images/ があれば、元の写真として使う
（確認用の一覧と、zoom_figure の切り出し）。
"""
from __future__ import annotations

import argparse
import csv
import json
import math
import os
import random
import re
import warnings
from dataclasses import dataclass, field
from pathlib import Path

import matplotlib.pyplot as plt
import numpy as np
from matplotlib.patches import Rectangle
from PIL import Image

BLUE = "#0b5cad"
ORANGE = "#b35900"           # 青と橙は色覚の違いがあっても区別しやすい。theme/custom.scss の $accent-2 と同じ値
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
FULL_WIDTH_IN = 13.3         # _quarto.yml の fig-width（スライドの幅いっぱい）


def japanese_fonts() -> list[str]:
    """入っている日本語フォントだけを返す（無いフォントを指定すると警告が大量に出るため）。"""
    from matplotlib import font_manager

    have = {f.name for f in font_manager.fontManager.ttflist}
    return [f for f in FONT_CANDIDATES if f in have] + ["sans-serif"]


def use_japanese_font() -> list[str]:
    """matplotlib の文字を日本語フォントにする。imgfig・figs の図の関数は中で呼ぶが、plt.subplots などで自前の図を
    描くときは呼ばれないため、描く前に1回呼ぶ（呼ばないと日本語が豆腐になる）。返り値は設定したフォントの列。"""
    fonts = japanese_fonts()
    plt.rcParams["font.family"] = fonts
    return fonts


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
    original: Path | None = field(default=None, compare=False, repr=False)   # 元の写真（縮小前）。無ければ None

    def __getitem__(self, key: str) -> str:
        return self.attrs[key]

    def get(self, key: str, default=None):
        return self.attrs.get(key, default)

    def num(self, key: str) -> float:
        return float(self.attrs[key])


def _originals(thumbs_dir, images_dir) -> Path | None:
    """元の写真の置き場所。指定が無ければ、thumbs と同じ階層の images/ があればそれ。"""
    if images_dir:
        return Path(images_dir)
    cand = Path(thumbs_dir).parent / "images"
    return cand if cand.is_dir() and cand.resolve() != Path(thumbs_dir).resolve() else None


def load_table(table_csv, thumbs_dir, id_col: str = "id", label_col: str | None = None,
               score_col: str | None = None, ext: str = ".jpg", images_dir=None) -> list[Item]:
    """表（1行 = 1画像）を読む。列は it["列名"]、数値は it.num("列名")。行の順序は表のまま。

    元の写真（縮小前）があれば it.original に入る（images_dir、無ければ thumbs と同じ階層の images/）。
    """
    orig = _originals(thumbs_dir, images_dir)
    items = []
    with open(table_csv, newline="", encoding="utf-8") as f:
        for r in csv.DictReader(f):
            o = orig / f"{r[id_col]}{ext}" if orig else None
            items.append(Item(r[id_col], Path(thumbs_dir) / f"{r[id_col]}{ext}",
                              score=float(r[score_col]) if score_col else 0.0,
                              label=r[label_col] if label_col else "", role=r.get("role", ""), attrs=dict(r),
                              original=o if o and o.exists() else None))
    return items


def load_look(items, look_csv, id_col: str = "id") -> list[Item]:
    """確認の表（data/look.csv: id, label_class, classes, unsure, note, closeup）を items に足す。classes は元の写真に
    写っている分類の対象を「;」で区切ったもの（スライドに書く名前で）。unsure は写っているかを写真から決めきれない分類の
    対象。note はほかの物・様子。表に無い画像はそのまま返す。"""
    import dataclasses

    with open(look_csv, newline="", encoding="utf-8") as f:
        look = {r[id_col]: r for r in csv.DictReader(f)}
    missing = [it.id for it in items if it.id not in look]
    if missing:      # Quarto は warning: false で警告を隠すので、render_check も図の写真ごとに知らせる
        warnings.warn(f"確認の表 {look_csv} に無い写真 {len(missing)} 枚（{', '.join(missing[:6])}）。説明（seen）が空になる。"
                      "元の写真で見て1枚1行を足す", stacklevel=2)
    return [dataclasses.replace(it, attrs={**it.attrs, **{k: v for k, v in look[it.id].items() if k != id_col}})
            if it.id in look else it for it in items]


def _split(v) -> list[str]:
    return [c.strip() for c in str(v or "").split(";") if c.strip()]


def seen(it: Item, sep: str = "＋", note: bool = True) -> str:
    """確認の表から、説明に使う文字列を作る: classes（写っている分類の対象すべて）と、決めきれない対象（unsure）に「?」を
    付けたものをつなぎ、note があれば括弧で添える。例: 「犬＋猫（奥にオウムも）」「猫（主役はオウム）」「犬?（遠くの影）」。
    classes も unsure も空なら note だけ。"""
    names = sep.join(_split(it.get("classes")) + [f"{u}?" for u in _split(it.get("unsure"))])
    extra = str(it.get("note", "") or "").strip() if note else ""
    if not extra:
        return names
    return f"{names}（{extra}）" if names else extra


def present(it: Item, cls: str) -> bool:
    """確認の表で、cls が写っていると確かめた写真か。"""
    return cls in _split(it.get("classes"))


def absent(it: Item, cls: str) -> bool:
    """確認の表で、cls が写っていないと言える写真か。決めきれない（unsure に cls がある）写真は含めない。
    「写っていない」「〜以外」と数えるときは、これで数える（決めきれない写真は別に数える）。"""
    return cls not in _split(it.get("classes")) and cls not in _split(it.get("unsure"))


CHECKED = {"yes", "y", "1", "true", "済", "はい"}


def needs_closeup(row: dict) -> bool:
    """拡大で確かめ直す写真か: 分類の対象が1つも写っていないとした（classes が空）か、データのラベルのクラス
    （label_class の列があれば）が写っていないとした写真。どちらも「写っていない」と言うことになり、大きな別の物の後ろ・
    体や翼の陰・遠くに写る対象を落としやすい。"""
    classes = [c.strip() for c in (row.get("classes") or "").split(";") if c.strip()]
    label = (row.get("label_class") or "").strip()
    return not classes or bool(label and label not in classes)


def slide_texts(html_path) -> list[str]:
    """描画した revealjs の HTML から、スライドごとに見える文字（タイトル・本文・図の下の文字）を取り出す。ノートは除く。"""
    import html as _html
    import re as _re

    s = Path(html_path).read_text(encoding="utf-8")
    out = []
    for part in _re.split(r"<section\b", s)[1:]:
        part = _re.sub(r"<(script|style|aside)\b.*?</\1>", " ", part, flags=_re.S)
        text = _html.unescape(_re.sub(r"<[^>]+>", " ", part))
        out.append(_re.sub(r"\s+", " ", text).strip())
    return out


def label_table(data_dir, look_rows: list[dict]) -> dict[str, tuple[str, str]]:
    """data/ の表から、写真ごとの（データのラベル, 予測）を探す。確認の表の label_class と一致する列をラベル、
    クラス名を値にもつ別の列を予測とみなす。見つからなければ空。"""
    labels = {r["id"]: (r.get("label_class") or "").strip() for r in look_rows if (r.get("label_class") or "").strip()}
    for path in sorted(Path(data_dir).glob("*.csv")):
        if path.name == "look.csv":
            continue
        with open(path, newline="", encoding="utf-8") as f:
            rows = list(csv.DictReader(f))
        if not rows or "id" not in rows[0]:
            continue
        by = {r["id"]: r for r in rows}
        common = [i for i in labels if i in by]
        if len(common) < 5:
            continue
        cols = [c for c in rows[0] if c != "id"]
        lab = next((c for c in cols if sum(by[i][c] == labels[i] for i in common) >= 0.9 * len(common)), None)
        vocab = {r[lab] for r in rows} if lab else set()
        pred = next((c for c in cols if c != lab and sum(r[c] in vocab for r in rows) >= 0.9 * len(rows)
                     and any(r[c] != r[lab] for r in rows)), None) if lab else None
        if lab and pred:
            return {r["id"]: (r[lab], r[pred]) for r in rows}
    return {}


COUNT_RE = re.compile(r"(?<![\d.,])(\d+)\s*枚(?!目|ずつ)")
CLAIM_SCOPE_RE = re.compile(r"ラベル|予測|正解|答え|判定|間違え|取り違え|誤った|→|->|⇒")   # ラベル・予測で範囲を言う部分は照らさない
CLAIM_UNSURE_RE = re.compile(r"決めきれ|決められ|かどうか|不明|[?？]|かもしれ")
CLAIM_NEG_RE = re.compile(r"写っていない|写らない|写ってない|[がは]いない|[がは]無い|[がは]ない|以外|どれでもない")
CLAIM_ALL_RE = re.compile(r"両方|ともに|一緒に")
CLAIM_PRED_RE = re.compile(r"\s*(?:の(?:写真|画像))?\s*(?:は|が|とも|には|では|にも|すべて|全部|だけ)")


def _claim_parts(text: str) -> list[tuple[int, str]]:
    """文の「N枚」ごとに、その写真について言う部分を返す。「N枚は〜」なら後ろ、「〜が写るN枚」「〜の写真はN枚中」なら前。"""
    ms = list(COUNT_RE.finditer(text))
    out = []
    for k, m in enumerate(ms):
        before = text[ms[k - 1].end() if k else 0:m.start()]
        after = text[m.end():ms[k + 1].start() if k + 1 < len(ms) else len(text)]
        out.append((int(m.group(1)), after if CLAIM_PRED_RE.match(after) else before))
    return out


def _ids(items) -> list[str]:
    return [getattr(it, "id", str(it)) for it in items]


def _claim_warnings(text: str, counts: dict, outside) -> list[str]:
    """claim の文の名前（確認の表のクラス）と、渡した写真を照らす。名前が写っていない写真と、「N枚のうちM枚」の
    M枚に入れなかった写真にも名前が写るときを返す。ラベル・予測で範囲を言う部分と、決めきれないと言う部分は照らさない。"""
    vocab = set()
    for items in counts.values():
        for it in items:
            if hasattr(it, "get"):
                for col in ("classes", "unsure", "label_class"):
                    vocab |= set(_split(it.get(col)))
    if not vocab:
        return []
    out, said = [], {}
    for n, part in _claim_parts(text):
        if n not in counts or CLAIM_SCOPE_RE.search(part) or CLAIM_UNSURE_RE.search(part):
            continue
        names = [c for c in sorted(vocab, key=len, reverse=True) if c in part]
        if not names:
            continue
        both = bool(CLAIM_ALL_RE.search(part))

        def has(it, names=names, both=both):
            hits = [present(it, c) for c in names]
            return all(hits) if both else any(hits)

        if CLAIM_NEG_RE.search(part):
            bad = [it for it in counts[n] if not all(absent(it, c) for c in names)]
            what = "写っている（か決めきれない）"
        else:
            bad = [it for it in counts[n] if not has(it)]
            what = "写っていない（か決めきれない）"
            said[n] = has
        if bad:
            out.append(f"{n}枚のうち{len(bad)}枚は、確認の表で{'・'.join(names)}が{what}（{', '.join(_ids(bad)[:6])}）。"
                       "文が指す写真を確認の表から選び直す")
    skip = set(_ids(outside or []))
    for n2, has in said.items():
        inner = set(_ids(counts[n2]))
        for n1, items in counts.items():
            if n1 <= n2 or not inner <= set(_ids(items)):
                continue
            rest = [i for i, it in zip(_ids(items), items) if i not in inner and i not in skip and has(it)]
            if rest:
                out.append(f"{n1}枚のうち{n2}枚に入れなかった写真のうち{len(rest)}枚にも、文の名前が写る（{', '.join(rest[:6])}）。"
                           "文が指す写真をすべて数えるか、文の形容（色・大きさなど）で外した写真なら outside= に渡す")
    return out


def claim(text: str, counts: dict, outside=None, where: dict | None = None) -> str:
    """タイトルなどで写真の枚数を言う文を、数ごとの写真で確かめる（描画のコードで呼ぶ。数が合わなければ止まる）。

        imgfig.claim("ラベルが犬の誤り12枚のうち7枚は、猫かオウムの写真だ",
                     {12: dog_wrong, 7: [it for it in dog_wrong if imgfig.present(it, "猫") or imgfig.present(it, "オウム")]})

    数ごとに、文が指す範囲の写真を確認の表から選び直して渡す（図や前の計算の一部を流用しない）。文の「N枚」はすべて
    counts に入れる。文の名前（確認の表のクラス）が写っていない写真や、「N枚のうちM枚」のM枚に入れなかった写真にも
    名前が写るときは、render_check が知らせる。文の形容（「白い猫」の白いなど）で外した写真は outside に渡す。
    render_check は、claim の無いタイトルの枚数も知らせる。返り値は text。

    where は、主張の根拠になる列の値。渡した写真すべてで確かめる（合わなければ止まる）。写真に何が写るか（classes）だけでは
    「今のモデルが犬と判定した中に混じる例」のような主張は確かめられない（今の判定は写真に写らない）。確認の表かデータの表に
    根拠の列を持たせて渡す:

        imgfig.claim("今のモデルが犬と判定した写真に混じる猫6枚", {6: mixed}, where={"現行の判定": "犬"})

    値には文字列（一致）、文字列の組（どれか）、関数（真なら合格）を渡せる。"""
    nums = [int(n) for n in COUNT_RE.findall(text)]
    counts = {int(n): list(items) for n, items in counts.items()}
    missing = sorted(set(nums) - set(counts))
    if missing:
        raise AssertionError(f"「{text}」の {'・'.join(map(str, missing))} 枚に当たる写真を渡していない")
    for n, items in counts.items():
        if len(items) != n:
            raise AssertionError(f"「{text}」の {n} 枚は、渡した写真では {len(items)} 枚。文が指す範囲の写真を確認の表から"
                                 "選び直し、数か文を直す")
    for col, want in (where or {}).items():
        ok = want if callable(want) else (lambda v, w=want: v in w) if isinstance(want, (set, tuple, list, frozenset)) \
            else (lambda v, w=want: v == w)
        for n, items in counts.items():
            lacking = [it.id for it in items if col not in getattr(it, "attrs", {})]
            if lacking:
                raise AssertionError(f"「{text}」の根拠の列「{col}」が表に無い写真がある（{', '.join(lacking[:6])}）。"
                                     "確認の表かデータの表に列を足す")
            bad = [it.id for it in items if not ok(str(it.get(col, "")).strip())]
            if bad:
                raise AssertionError(f"「{text}」の {n} 枚のうち {len(bad)} 枚は「{col}」が条件に合わない（{', '.join(bad[:6])}）。"
                                     "主張を支持しない写真を実例にしない。写真を選び直すか、文を直す")
    if os.environ.get("IMGFIG_REPORT"):
        with open(os.environ["IMGFIG_REPORT"], "a", encoding="utf-8") as f:
            f.write(json.dumps({"claim": text, "counts": {str(n): _ids(items) for n, items in counts.items()},
                                "outside": _ids(outside or []), "warnings": _claim_warnings(text, counts, outside)},
                               ensure_ascii=False) + "\n")
    return text


def measured(text: str, counts: dict) -> str:
    """写真の集合に当たらない枚数（人手で数え直した件数・データから測った値）をタイトルで言う文を、計算した値で確かめる。

        imgfig.measured("人手で分類し直した120枚では、誤りは9枚だった", {120: len(relabeled), 9: n_wrong})

    文の「N枚」はすべて counts に入れ、値は計算した数（int）を渡す。合わなければ止まる（assert と同じ）。
    render_check は、claim か measured で確かめていないタイトルの枚数を知らせる。写真を並べて見せる枚数は
    measured ではなく claim で確かめる（写っている対象を確認の表と照らすため）。返り値は text。"""
    nums = [int(n) for n in COUNT_RE.findall(text)]
    counts = {int(n): v for n, v in counts.items()}
    missing = sorted(set(nums) - set(counts))
    if missing:
        raise AssertionError(f"「{text}」の {'・'.join(map(str, missing))} 枚に当たる値を渡していない")
    for n, v in counts.items():
        if isinstance(v, bool) or not isinstance(v, (int, np.integer)):
            raise TypeError(f"「{text}」の {n} 枚には、計算した数（int）を渡す（{type(v).__name__} を渡した）")
        if int(v) != n:
            raise AssertionError(f"「{text}」の {n} 枚は、計算した値では {int(v)}。数か文を直す")
    if os.environ.get("IMGFIG_REPORT"):
        with open(os.environ["IMGFIG_REPORT"], "a", encoding="utf-8") as f:
            f.write(json.dumps({"measured": text, "counts": {str(n): int(v) for n, v in counts.items()}},
                               ensure_ascii=False) + "\n")
    return text


def slide_titles(html_path) -> list[str]:
    """描画した revealjs の HTML から、スライドごとのタイトル（h2 の文字。無ければ空）を取り出す。"""
    import html as _html

    s = Path(html_path).read_text(encoding="utf-8")
    out = []
    for part in re.split(r"<section\b", s)[1:]:
        m = re.search(r"<h2[^>]*>(.*?)</h2>", part, flags=re.S)
        out.append(re.sub(r"\s+", " ", _html.unescape(re.sub(r"<[^>]+>", "", m.group(1)))).strip() if m else "")
    return out


COUNTS_CHECKED_RE = re.compile(r"<!--\s*counts\s*:\s*checked\b\s*(.*?)\s*-->", re.S)


def _plain_title(md: str) -> str:
    """qmd の見出しの文字を、描画した HTML の h2 の文字に近づける（属性 {…}・[文字]{.cls}・強調の記号を除き、空白を詰める）。"""
    t = re.sub(r"\s*\{[^{}]*\}\s*$", "", md.strip())
    t = re.sub(r"\[([^\]]*)\]\{[^{}]*\}", r"\1", t)
    t = re.sub(r"[*_`]", "", t)
    return "".join(t.split())


def checked_titles(qmd_path) -> dict[str, str]:
    """qmd で `<!-- counts: checked 理由 -->` を書いたスライドの、タイトル（空白を詰めたもの）→ 理由。
    数値一覧（設計書の数の表など）で検算済みの、写真の集合に当たらない数のタイトルを、claim・measured の検査から外す。
    理由が空の宣言は数えない（何で確かめたかを残す）。"""
    if not qmd_path or not Path(qmd_path).exists():
        return {}
    out, title = {}, None
    for line in Path(qmd_path).read_text(encoding="utf-8").splitlines():
        m = re.match(r"^##\s+(.*)$", line)
        if m:
            title = _plain_title(m.group(1))
            continue
        for reason in COUNTS_CHECKED_RE.findall(line):
            if title is not None and reason.strip():
                out[title] = reason.strip()
    return out


def check_claims(html_path, report, qmd_path=None) -> list[str]:
    """claim の文と写真の食い違いと、タイトルで枚数を言うのに imgfig.claim・imgfig.measured で確かめていないスライドを知らせる。
    qmd を渡すと、`<!-- counts: checked 理由 -->` を書いたスライドは「確かめていない」の対象から外す。"""
    recs = [json.loads(line) for line in open(report, encoding="utf-8") if line.strip()] \
        if report and Path(report).exists() else []
    claims = [r for r in recs if "claim" in r]
    out = [f"「{r['claim']}」: {w}" for r in claims for w in r.get("warnings", [])]
    said = {"".join(r["claim"].split()) for r in claims} | {"".join(r["measured"].split()) for r in recs if "measured" in r}
    said |= set(checked_titles(qmd_path))
    for sn, title in enumerate(slide_titles(html_path), 1):
        if COUNT_RE.search(title) and "".join(title.split()) not in said:
            out.append(f"スライド{sn}: タイトル「{title}」の枚数を確かめていない。写真の枚数なら `imgfig.claim(タイトル, {{数: 写真, …}})`、"
                       "写真の集合に当たらない測った数（人手で数え直した件数など）なら `imgfig.measured(タイトル, {数: 計算した値})` で確かめる。"
                       "数値一覧などで検算済みなら、その枚に `<!-- counts: checked 何で確かめたか -->` と書く")
    return out


def check_counts(html_path, look_csv, data_dir=None, id_col: str = "id") -> list[str]:
    """スライドの文字の「N枚は〇〇の写真」「〇〇が写る N枚」が、ラベルで数えた枚数と同じで、確認の表で数えた枚数と
    違うとき知らせる（ラベルの数を、写真に写っているものの数として書いている）。「ラベルが〇〇」と書いていれば数えない。"""
    import re as _re

    with open(look_csv, newline="", encoding="utf-8") as f:
        rows = list(csv.DictReader(f))
    table = label_table(data_dir or Path(look_csv).parent, rows)
    if not table:
        return []
    errs = {i for i, (lab, pred) in table.items() if lab != pred}
    vocab = sorted({lab for lab, _ in table.values()}, key=len, reverse=True)
    look = {r[id_col]: (set(_split(r.get("classes"))), set(_split(r.get("unsure")))) for r in rows}
    out = []
    for sn, text in enumerate(slide_texts(html_path), 1):
        for cls in vocab:
            label_n = {sum(1 for i in errs if table[i][0] == cls), sum(1 for lab, _ in table.values() if lab == cls)}
            seen_n = {sum(1 for i, (c, u) in look.items() if cls in c and (i in errs or not errs)),
                      sum(1 for c, u in look.values() if cls in c),
                      sum(1 for i, (c, u) in look.items() if cls in c | u and i in errs)}
            pats = [rf"(\d+)\s*枚(?!目)\s*(?:は|が|の|とも|すべて|全部)?\s*{_re.escape(cls)}(?:の写真|の画像|が写)",
                    rf"{_re.escape(cls)}(?:の写真|の画像|が写る写真|が写る)\s*(?:は|が)?\s*(\d+)\s*枚(?!目)"]
            for pat in pats:
                for m in _re.finditer(pat, text):
                    head = text[max(0, m.start() - 6):m.start()] + m.group(0)[:m.group(0).find(cls)]
                    if _re.search(r"ラベル|正解|予測|答え|判定", head):
                        continue
                    n = int(m.group(1))
                    if n in label_n and n not in seen_n:
                        out.append(f"スライド{sn}: 「{m.group(0)}」の {n} 枚は、ラベルが{cls}の枚数と同じで、確認の表で{cls}が写る"
                                   f"枚数（{'・'.join(str(x) for x in sorted(seen_n))}）と違う。ラベルの数なら「ラベルが{cls}の写真」と書き、"
                                   "写っている数なら確認の表で数える")
    return out


def check_look(report, look_csv, id_col: str = "id") -> list[str]:
    """図に書いた写真ごとの説明と群の見出しを、確認の表と照らす。食い違いの文を返す（無ければ空）。

    - 説明に、その写真の classes のどれかが入っていない（主役だけを書いて、ほかに写る対象を落としている）
    - 説明に、その写真の note が入っていない（分類の対象以外の主役や目立つ物を落としている）
    - 見出しが1つのクラスだけを言う群に、そのクラス以外も写る写真や、そのクラスが写らない写真が入っている
      （見出しに「ラベル」「予測」「正解」「答え」「判定」「→」があるときは、データの値の見出しとみなして照らさない）
    - 分類の対象が写っていない、またはラベルのクラスが写っていないとした写真（needs_closeup）を、拡大
      （closeup の全体と4区画）で確かめていない（look.csv の closeup 列が yes でない）
    - 「写っていない」「以外」などを言う見出しの群に、決めきれない（unsure のある）写真が入っている
    - note に「不明」「決めきれない」などとあるのに、unsure 列が空（決めきれない写真を「写っていない」と数えてしまう）
    - 図に載せた写真が確認の表に無い（群を足したときに表へ足し忘れると、説明が空になる）
    見出しが「猫でない」「犬が写っていない」のように否定なら、そのクラスが写る写真を知らせる。
    """
    import re as _re

    with open(look_csv, newline="", encoding="utf-8") as f:
        rows = list(csv.DictReader(f))
    look = {r[id_col]: _split(r.get("classes")) for r in rows}
    unsure = {r[id_col]: _split(r.get("unsure")) for r in rows}
    notes = {r[id_col]: (r.get("note") or "").strip() for r in rows}
    vague = [r[id_col] for r in rows if not unsure[r[id_col]]
             and _re.search(r"不明|決めきれ|決められ|わから|分から|判別でき|見分けられ", notes[r[id_col]])]
    unchecked = {r[id_col] for r in rows
                 if needs_closeup(r) and (r.get("closeup") or "").strip().lower() not in CHECKED}
    vocab = sorted({c for cs in look.values() for c in cs}, key=len, reverse=True)
    out = []
    if vague:
        out.append(f"確認の表: note に「不明」などとあるのに unsure 列が空の写真 {len(vague)} 枚（{', '.join(vague[:8])}"
                   f"{' ほか' if len(vague) > 8 else ''}）。決めきれない分類の対象を unsure 列に書く（「写っていない」と数えないため）")
    figs = [json.loads(line) for line in open(report, encoding="utf-8") if line.strip()]
    for n, rec in enumerate((r for r in figs if "claim" not in r), 1):
        todo = list(dict.fromkeys(c["id"] for c in rec.get("captions", []) if c["id"] in unchecked))
        if todo:
            out.append(f"図{n}: 分類の対象またはラベルのクラスが写っていないとした写真のうち、拡大で確かめていない "
                       f"{len(todo)} 枚（{', '.join(todo)}）。`imgfig.py closeup` で全体と4区画の拡大を作って1枚ずつ "
                       "Read で開き、区画ごとに分類の対象を探す。確かめたら look.csv の closeup 列に yes と書く")
        unknown = list(dict.fromkeys(c["id"] for c in rec.get("captions", []) if c["id"] not in look))
        if unknown:
            out.append(f"図{n}: 確認の表（{Path(look_csv).name}）に無い写真 {len(unknown)} 枚（{', '.join(unknown[:8])}"
                       f"{' ほか' if len(unknown) > 8 else ''}）。群を足したときは、元の写真で見て1枚1行を確認の表に足す"
                       "（無いと説明 imgfig.seen が空になる）")
        for cap in rec.get("captions", []):
            classes = look.get(cap["id"])
            if cap["id"] in look and cap["caption"]:
                missing = [c for c in classes + unsure.get(cap["id"], []) if c not in cap["caption"]]
                note = notes.get(cap["id"], "")
                if note and note not in cap["caption"].replace("\n", ""):
                    missing.append(f"note: {note}")
                if missing:
                    out.append(f"図{n}: {cap['id']} の説明「{cap['caption'].replace(chr(10), ' ')}」に、確認の表の"
                               f"「{'・'.join(missing)}」が無い")
        for g in rec.get("groups", []):
            title = g["title"]
            vague_in = [i for i in g["ids"] if unsure.get(i)]
            if vague_in and _re.search(r"写っていない|写らない|いない|無い|ない写真|以外|どれでもない", title):
                out.append(f"図{n}: 見出し「{title}」は写っていないことを言うが、決めきれない写真 {', '.join(vague_in)} が"
                           "入っている。「決めきれない」の群に分ける")
            if _re.search(r"ラベル|予測|正解|答え|判定|→", title):
                continue
            named = [c for c in vocab if c in title]
            if len(named) != 1:
                continue
            k = named[0]
            negative = bool(_re.search(rf"{_re.escape(k)}\s*(?:が|は)?\s*(?:写っていない|写らない|いない|無い|ない|でない|ではない|以外)", title))
            for i in g["ids"]:
                classes = look.get(i)
                if i not in look:
                    continue
                shown = "・".join(classes) if classes else "（分類の対象なし）"
                if negative and k in classes:
                    out.append(f"図{n}: 見出し「{title}」は{k}が写らない群だと述べているが、確認の表（classes 列）では "
                               f"{i} に{k}が写る（{shown}）。{i} を別の群に移すか、見出しを直す")
                elif not negative and classes and k not in classes:
                    out.append(f"図{n}: 見出し「{title}」は{k}の群だと述べているが、確認の表（classes 列）では {i} に"
                               f"{k}が写っていない（{shown}）。{i} を別の群に移すか、見出しを直す")
                elif not negative and any(c != k for c in classes):
                    out.append(f"図{n}: 見出し「{title}」は{k}だけの群に読めるが、確認の表（classes 列）では {i} に"
                               f"{k}以外も写る（{shown}）。「両方写る」などの群に分けるか、見出しを直す")
    return out


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
    thumb_in を渡すと、width_in・max_height_in によらず1枚の幅をその実寸（インチ）にする。図全体の大きさは
    列数・段数・見出し・説明の行数で決まる。枚をまたいで写真の大きさを揃えるときに、各枚の図に同じ値を渡す
    （max_height_in を揃えても、説明が2行の図と3行の図では写真の大きさが変わる）。
    """

    def __init__(self, w_units: float, h_units: float, width_in: float = 12.0, max_height_in: float = 5.6,
                 cell_h: float = 1.0, kind: str = "", return_fig: bool = False, thumb_in: float | None = None):
        use_japanese_font()
        scale = float(thumb_in) if thumb_in else min(width_in / w_units, max_height_in / h_units)
        if thumb_in and w_units * scale > FULL_WIDTH_IN + 0.05:
            warnings.warn(f"thumb_in={thumb_in} では図の幅が {w_units * scale:.1f} インチになり、スライドの幅"
                          f"（{FULL_WIDTH_IN} インチ）を超えて縮められる。列数を減らすか thumb_in を小さくする", stacklevel=3)
        self.fig = plt.figure(figsize=(w_units * scale, h_units * scale))
        self.ax = self.fig.add_axes([0, 0, 1, 1])
        self.ax.axis("off")
        self.ax.autoscale(False)
        self.w, self.h = w_units, h_units
        self.unit_in = scale            # 1単位の実寸（インチ）
        self.pt = scale * 72.0          # 1単位あたりのポイント数
        self.cell_h, self.kind, self.n_thumbs = cell_h, kind, 0
        self.return_fig = return_fig    # 既定は None を返す（Quarto のセルの最後の式が図だと、同じ図が2つ出る）
        self.captions: list[dict] = []     # 写真ごとの説明（render_check が確認の表 data/look.csv と照らす）
        self.groups: list[dict] = []       # 群の見出しと、その群の写真

    def finish(self):
        self.ax.set_xlim(0, self.w)
        self.ax.set_ylim(self.h, 0)
        self.ax.set_aspect("equal")
        px, px_tall = unit_px(self.w, self.h), unit_px(self.w, self.h, SLIDE_BOX_TALL)
        if os.environ.get("IMGFIG_REPORT"):        # render_check.sh が図ごとの大きさを表示するための記録
            with open(os.environ["IMGFIG_REPORT"], "a", encoding="utf-8") as f:
                f.write(json.dumps({"kind": self.kind, "thumbs": self.n_thumbs, "px": round(px),
                                    "px_tall": round(px_tall), "captions": self.captions, "groups": self.groups},
                                   ensure_ascii=False) + "\n")
        if self.n_thumbs and px_tall < MIN_UNIT_PX:
            warnings.warn(f"サムネイルが小さい（bullets を置かなくても、スライド上で約{px_tall:.0f}px）。"
                          "見せる枚数を減らす（pick）か、図を分ける。全数は appendix に回せる", stacklevel=3)
        return self.fig if self.return_fig else None

    def group(self, title, items):
        """群の見出しと写真を記録する（見出しが1つのクラスを言うとき、ほかのクラスも写る写真が入っていないかを照らすため）。"""
        self.groups.append({"title": str(title), "ids": [it.id for it in items]})

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
        self.captions.append({"id": item.id, "caption": str(caption) if caption else ""})
        for n, (line, first) in enumerate(caption_lines(caption, caption_size) if caption else []):
            self.text(x + 0.5, y + self.cell_h + caption_size * 0.7 + n * CAPTION_LINE, line, size=caption_size,
                      color=color if first else INK)


CAPTION_H = 0.3              # 説明文1行ぶんの高さ
CAPTION_LINE = 0.24          # 2行目以降の行送り
CAPTION_W = 1.12             # 説明文1行の幅の上限（_text_w の値。余白0.12を含むので、文字の幅で1単位＝枠の幅。超えると隣の列の説明と重なる）
CAPTION_BREAK_RE = re.compile(r"(?<=[＋・、，,／/ ])|(?=[（(])")   # 「犬＋」「猫（…）」のように、区切り・空白の後ろか括弧の前で折る


def caption_lines(text, size: float = 0.16, width: float = CAPTION_W) -> list[tuple[str, bool]]:
    """説明文を、枠の幅に収まるよう折り返した行にする。返り値は (行, 1行目の段落の行か)。

    改行はそのまま行を分ける。1行が枠より長いとき（「犬＋猫＋オウム（主役は車）」など）は、「＋・、」の後ろか
    「（」の前で折り、それでも長い語は文字で折る。折らないと、隣の列の説明と重なる。"""
    out: list[tuple[str, bool]] = []
    for n, para in enumerate(str(text).split("\n")):
        line = ""
        for tok in (t for t in CAPTION_BREAK_RE.split(para) if t):
            if line and _text_w(line + tok, size) > width:
                out.append((line.rstrip(), n == 0))
                line = ""
            line += tok
            while _text_w(line, size) > width and len(line) > 1:
                k = max(1, max((i for i in range(1, len(line)) if _text_w(line[:i], size) <= width), default=1))
                out.append((line[:k], n == 0))
                line = line[k:]
        out.append((line, n == 0))
    return out


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
    """説明文の高さ（単位）。改行と、枠の幅での折り返し（caption_lines）の行数ぶん取る。"""
    if not caption:
        return 0.0
    lines = max((len(caption_lines(caption(it))) for it in items), default=1)
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
def grid_figure(items, cols: int | None = None, caption=None, color=None, aspect=None, title=None,
                counts: bool = False, **canvas_kw):
    """1つの群を左上から順に並べる。caption は Item → 文字列（不要なら None。改行で2行にできる）。

    cols を省くと、スライド上で1枚が最も大きくなる列数にする。aspect は枠の高さ（幅を1として。省くと写真に合わせる）。
    title を渡すと、panels_figure と同じ形の見出し（何の例か）を図の上に書く。counts=True で見出しに「N枚」を付ける。
    見出しは群の見出しとして記録され、render_check が確認の表と照らす。
    """
    items = list(items)
    ch, cap = _cell_h(items, aspect), _cap_h(items, caption)
    pitch = ch + cap
    head = 0.5 if title else 0.0
    cols = cols or _best((n, n, head + _rows(len(items), n) * pitch) for n in range(1, 13))
    c = Canvas(cols, head + _rows(len(items), cols) * pitch, cell_h=ch, kind="grid", **canvas_kw)
    if title:
        line = color or BLUE
        title = _counted(title, len(items), len(items)) if counts else str(title)
        c.text(0.04, head / 2 - 0.04, title, size=0.2, ha="left", weight="bold", color=line)
        c.group(title, items)
        c.hline(head - 0.06, 0.04, cols - 0.04, color=line, lw=0.02)
    _grid(c, items, 0, head, cols, caption, color, cap)
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
        c.group(title, s)
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
            c.group(labels[g], shown[g])
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
            c.group(head, s)
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
def review_sheet(items, out, caption=None, cols: int | None = None, per_sheet: int | None = None,
                 size: int | None = None) -> list[Path]:
    """画像を大きく並べ、#番号と説明を添えた確認用の画像を書く。

    図の縮小画像やスライドのスクショでは、小さく写るもの（車の中の動物、遠くの群れ、端の鳥）や、よく似た種を見分けられない。
    画像について書く前に、この画像を Read で開いて1枚ずつ確かめる。元の写真（it.original）があれば、それを長辺480pxで
    3列・1枚9つずつ並べる（無ければ縮小画像を256pxで6列・24ずつ）。それでも小さい物は、元の写真を直接 Read で開く。
    caption は Item → 文字列（改行可。ラベル・データ・撮影者の題名など）。枚数が per_sheet を超えると、out の名前に
    -2, -3 … を付けて分ける。返り値は書いたファイル。
    """
    from PIL import ImageDraw, ImageFont

    font = None
    for path in ("/System/Library/Fonts/ヒラギノ角ゴシック W3.ttc", "/usr/share/fonts/opentype/noto/NotoSansCJK-Regular.ttc"):
        if Path(path).exists():
            font = ImageFont.truetype(path, 17)
            break
    font = font or ImageFont.load_default()
    items, out = list(items), Path(out)
    big = size or (480 if any(it.original for it in items) else 256)
    cols = cols or (3 if big > 300 else 6)
    per_sheet = per_sheet or (9 if big > 300 else 24)
    written = []
    for k in range(0, max(1, len(items)), per_sheet):
        chunk = items[k:k + per_sheet]
        if not chunk:
            break
        c = min(cols, len(chunk))
        rows = (len(chunk) - 1) // c + 1
        cell, text_h = big + 6, 96
        wrap = max(15, big // 17)
        sheet = Image.new("RGB", (c * cell + 8, rows * (cell + text_h) + 8), "white")
        d = ImageDraw.Draw(sheet)
        for n, it in enumerate(chunk):
            x, y = 4 + (n % c) * cell, 4 + (n // c) * (cell + text_h)
            im = Image.open(it.original or it.path).convert("RGB")
            im.thumbnail((big, big))
            sheet.paste(im, (x + (big - im.width) // 2, y + (big - im.height) // 2))
            lines = [f"#{k + n + 1} {it.id}" + ("" if it.original or big <= 256 else "（縮小画像）")]
            for part in (str(caption(it)) if caption else "").split("\n"):
                lines += [part[i:i + wrap] for i in range(0, len(part), wrap)] or [""]
            d.multiline_text((x + 2, y + big + 2), "\n".join(lines[:5]), fill=INK, font=font, spacing=2)
        name = out if k == 0 else out.with_name(f"{out.stem}-{k // per_sheet + 1}{out.suffix}")
        sheet.save(name, quality=88)
        written.append(name)
    return written


TILES = (("左上", 0.0, 0.0), ("右上", 0.45, 0.0), ("左下", 0.0, 0.45), ("右下", 0.45, 0.45))   # 区画の左上（幅・高さは0.55。境目の物が切れないよう重ねる）


def closeup_image(item: Item, out, header: str = "", full: int = 640, tile: int = 400) -> Path:
    """確認用（スライドには載せない）: 写真全体と、4つの区画（左上・右上・左下・右下。少し重ねる）の拡大を並べた画像を書く。

    縮小した写真を眺めるだけでは、大きな別の物の後ろ・体や翼の陰・遠くに写る対象を落とす。区画ごとに見ると気づきやすい。
    元の写真（it.original）があれば、そこから切り出す。header は上に書く文字（例: 「探す: 犬・猫」）。"""
    from PIL import ImageDraw, ImageFont

    try:
        font = ImageFont.truetype("/System/Library/Fonts/ヒラギノ角ゴシック W3.ttc", 22)
    except OSError:
        font = ImageFont.load_default()
    src = Image.open(item.original or item.path).convert("RGB")
    W, H = src.size
    whole = src.copy()
    whole.thumbnail((full, full))
    crops = []
    for name, x0, y0 in TILES:
        crop = src.crop((int(x0 * W), int(y0 * H), int(min(1.0, x0 + 0.55) * W), int(min(1.0, y0 + 0.55) * H)))
        s = min(tile / crop.width, tile / crop.height)
        crops.append((name, crop.resize((max(1, round(crop.width * s)), max(1, round(crop.height * s))), Image.LANCZOS)))
    top, gap, label_h = 40, 10, 34
    row_h = max(c.height for _, c in crops) + label_h
    sheet = Image.new("RGB", (whole.width + gap + 2 * (tile + gap), top + max(whole.height, 2 * row_h)), "white")
    d = ImageDraw.Draw(sheet)
    d.text((4, 6), f"{item.id}  {header}".strip(), fill=INK, font=font)
    sheet.paste(whole, (0, top))
    for k, (name, crop) in enumerate(crops):
        x = whole.width + gap + (k % 2) * (tile + gap)
        y = top + (k // 2) * row_h
        d.text((x, y), name, fill=INK, font=font)
        sheet.paste(crop, (x, y + label_h - 4))
    sheet.save(out, quality=88)
    return Path(out)


def zoom_figure(entries, caption=None, cols: int | None = None, color=ORANGE, caption_size=0.16, **canvas_kw):
    """小さく写る・端に写る・物の陰にいる対象を、写真全体（枠つき）と、その部分を拡大したものの組で見せる。

    entries は [(item, (x0, y0, x1, y1)), ...]。枠は写真の幅・高さに対する割合（0〜1、左上が 0,0）。拡大は元の写真
    （it.original）があればそこから切り出す（縮小画像を拡大すると細部が出ない）。枠は locate の目盛りつき画像で位置を
    読んで決め、描いた図を Read で開いて、枠の中に対象が入っていることを必ず確かめる。caption は Item → 文字列（改行可）。
    """
    entries = list(entries)
    cols = cols or min(2, len(entries))
    rows = (len(entries) - 1) // cols + 1
    pair_w, gap, cell_h = 2.1, 0.35, 1.0
    lines = [str(caption(it)).split("\n") for it, _ in entries] if caption else []
    cap_lines = max((len(ls) for ls in lines), default=0)
    cap_h = CAPTION_H + max(0, cap_lines - 1) * CAPTION_LINE if cap_lines else 0.0
    cap_w = max((_text_w(line, caption_size) for ls in lines for line in ls), default=0.0)
    pair_w = max(pair_w, cap_w + 0.1)             # 説明文が組の幅より長いときは、組の間を空ける
    c = Canvas(cols * pair_w + (cols - 1) * gap, rows * (cell_h + cap_h + 0.15), cell_h=cell_h, kind="zoom",
               **canvas_kw)
    for n, (it, box) in enumerate(entries):
        x, y = (n % cols) * (pair_w + gap), (n // cols) * (cell_h + cap_h + 0.15)
        x += (pair_w - 2.1) / 2                   # 写真の組は、広げた幅の中央に置く
        x0, y0, x1, y1 = box
        for k, (img, is_crop) in enumerate(((Image.open(it.path).convert("RGB"), False),
                                           (Image.open(it.original or it.path).convert("RGB"), True))):
            if is_crop:
                W, H = img.size
                img = img.crop((int(x0 * W), int(y0 * H), max(int(x1 * W), int(x0 * W) + 1),
                                max(int(y1 * H), int(y0 * H) + 1)))
            cx = x + k * 1.1
            c.ax.add_patch(Rectangle((cx, y), 1.0, cell_h, fc=BG, ec="none", zorder=1))
            w, h = img.size
            s = 0.94 * min(1.0 / w, cell_h / h)
            iw, ih = w * s, h * s
            ix, iy = cx + (1.0 - iw) / 2, y + (cell_h - ih) / 2
            c.ax.imshow(np.asarray(img), extent=(ix, ix + iw, iy + ih, iy), zorder=2, interpolation="antialiased")
            if not is_crop:
                c.ax.add_patch(Rectangle((ix + x0 * iw, iy + y0 * ih), (x1 - x0) * iw, (y1 - y0) * ih,
                                         fc="none", ec=color, lw=0.03 * c.pt, zorder=3))
            else:
                c.ax.add_patch(Rectangle((ix, iy), iw, ih, fc="none", ec=color, lw=0.035 * c.pt, zorder=3))
            c.n_thumbs += 1
        c.text(x + 1.05, y + cell_h / 2, "→", size=0.2, color=color)
        c.captions.append({"id": it.id, "caption": str(caption(it)) if caption else ""})
        for k, line in enumerate(str(caption(it)).split("\n") if caption else []):
            c.text(x + 1.05, y + cell_h + caption_size * 0.7 + k * CAPTION_LINE, line, size=caption_size,
                   color=color if k == 0 else INK)
    return c.finish()


def locate_image(image, out, divisions: int = 10) -> Path:
    """元の写真に目盛り（幅・高さを divisions 等分、0〜1 の割合）を描いた確認用の画像を書く。zoom_figure の枠を読むため。"""
    from PIL import ImageDraw, ImageFont

    im = Image.open(image).convert("RGB")
    im.thumbnail((1024, 1024))
    W, H = im.size
    d = ImageDraw.Draw(im)
    try:
        font = ImageFont.truetype("/System/Library/Fonts/ヒラギノ角ゴシック W3.ttc", 18)
    except OSError:
        font = ImageFont.load_default()
    for k in range(1, divisions):
        x, y = W * k / divisions, H * k / divisions
        d.line([(x, 0), (x, H)], fill=(255, 255, 0), width=1)
        d.line([(0, y), (W, y)], fill=(255, 255, 0), width=1)
        d.text((x + 2, 2), f"{k / divisions:.1f}", fill=(255, 255, 0), font=font, stroke_width=2, stroke_fill="black")
        d.text((2, y + 2), f"{k / divisions:.1f}", fill=(255, 255, 0), font=font, stroke_width=2, stroke_fill="black")
    im.save(out, quality=88)
    return Path(out)


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
    sh.add_argument("--images", help="元の写真の置き場所（省略時は thumbs と同じ階層の images/ があればそれ）")
    sh.add_argument("--out", required=True)

    ck = sub.add_parser("check-look", help="図の説明・群の見出しを確認の表（data/look.csv）と照らす（render_check.sh が呼ぶ）")
    ck.add_argument("--report", required=True)
    ck.add_argument("--look", required=True)
    ck.add_argument("--html", help="描画した HTML。スライドの文字の枚数を、ラベルの数・確認の表の数と照らす")
    ck.add_argument("--data", help="データの表の置き場所（省略時は look.csv と同じフォルダ）")
    ck.add_argument("--qmd", help="デッキの qmd。`<!-- counts: checked 理由 -->` を書いた枚を、タイトルの枚数の検査から外す")

    cu = sub.add_parser("closeup", help="写っていないとした写真を、全体と4区画の拡大で並べた確認用の画像にする（1枚ずつ）")
    cu.add_argument("--look", required=True, help="確認の表（data/look.csv）。classes が空か、label_class が classes に無い行を選ぶ")
    cu.add_argument("--thumbs", required=True)
    cu.add_argument("--images", help="元の写真の置き場所（省略時は thumbs と同じ階層の images/ があればそれ）")
    cu.add_argument("--ids", help="画像IDをカンマ区切りで（前方一致）。指定すると、表の条件によらずその画像を書く")
    cu.add_argument("--classes", help="探す分類の対象（カンマ区切り）。画像の上に書く")
    cu.add_argument("--out", required=True, help="書き出すフォルダ（<id>.jpg）")

    lo = sub.add_parser("locate", help="元の写真に0〜1の目盛りを描く（拡大して見せる範囲を読むため）")
    lo.add_argument("--image", required=True)
    lo.add_argument("--out", required=True)

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
        fig = flow_figure([(" → ".join(v), g) for v, g in groups], k=a.k, how=a.how, caption=cap, return_fig=True)
        fig.savefig(a.out, dpi=200)
        print("; ".join(f"{' → '.join(v)}: {len(g)}" for v, g in groups), "->", a.out)
        return 0

    if a.cmd == "check-look":
        found = check_look(a.report, a.look)
        if a.html and Path(a.html).exists():
            found += check_counts(a.html, a.look, a.data)
            found += check_claims(a.html, a.report, a.qmd)
        for line in found:
            print(f"WARNING {line}")
        print(f"確認の表との照合: 食い違い {len(found)} 件")
        return 0

    if a.cmd == "locate":
        print(locate_image(a.image, a.out))
        return 0

    if a.cmd == "closeup":
        with open(a.look, newline="", encoding="utf-8") as f:
            rows = list(csv.DictReader(f))
        if a.ids:
            want = [x.strip() for x in a.ids.split(",") if x.strip()]
            ids = [r["id"] for r in rows if any(r["id"].startswith(w) for w in want)]
        else:
            ids = [r["id"] for r in rows if needs_closeup(r)]
        orig = _originals(a.thumbs, a.images)
        Path(a.out).mkdir(parents=True, exist_ok=True)
        header = f"探す: {a.classes.replace(',', '・')}（区画ごとに、後ろ・陰・遠くまで）" if a.classes else ""
        files = []
        for i in ids:
            o = orig / f"{i}.jpg" if orig else None
            it = Item(i, Path(a.thumbs) / f"{i}.jpg", original=o if o and o.exists() else None)
            files.append(closeup_image(it, Path(a.out) / f"{i}.jpg", header=header))
        print(f"{len(files)} images -> {a.out}（1枚ずつ Read で開き、確かめたら look.csv の closeup 列に yes と書く）")
        return 0

    if a.cmd == "sheet":
        items = _where(load_table(a.table, a.thumbs, images_dir=a.images), a.where)
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
                            row_title=a.row, col_title=a.col, return_fig=True)
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
    fig = moved_figure(ev, t0, t1, caption=lambda it: it.label, return_fig=True)
    fig.savefig(a.out, dpi=200)
    n_out = sum(not i.normal for i in mvd)
    print(f"threshold {t0:.4f} -> {t1:.4f}: {len(mvd)} images change "
          f"({n_out} outliers, {len(mvd) - n_out} normals) -> {a.out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
