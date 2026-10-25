"""parts.py — 図解型（infographic）の部品を HTML で返す。Quarto のコードセル（#| output: asis）から呼ぶ。

figs.py（matplotlib の静止図）と同じ思想で、数値はセルで計算した値をそのまま渡す（手で写さない）。
revealjs では theme/motion-gsap.html（GSAP）が枚を開くたびに動かし（棒が伸びる・数字が数え上がる・人アイコンが順に出る・線を描く）、
render_check.sh の全枚スクショと reveal.js の ?print-pdf では動かさずに最終状態で描く（theme/motion-gsap.html）。pptx/beamer では文字だけになるので、
pptx/PDF を主な配布形にするデッキでは従来の figs.* を使う（PDF は render_check のスクショ綴じなら見た目は同じ）。

    import parts
    print(parts.badge("第6章", "ジョグの最後に、\\n毎回ダッシュする"))
    print(parts.pictos(12))
    print(parts.stack([("A組", [("楽 約8割", 80, "blue"), ("", 12, "orange"), ("", 8, "red")])]))
    print(parts.bars(["A組（楽が約8割）", "B組（楽が約7割）"], [157, 122], highlight="A組（楽が約8割）", unit="秒", prefix="−"))
    print(parts.stat(49.1, unit="mL/kg/分", label="VO₂max", dec=1))
    print(parts.cards([("観測", "何が写っているかの票"), ("規則（版付き）", "観測から機械的に導く"), ("判定", "最終カテゴリ")], arrows=True))
    print(parts.steps([("観測と判定を分ける", "観測＝票、判定＝版付きの規則"), ("上書きせず追記する", "出来事として残す")]))
"""
from __future__ import annotations

import html
import json
import hashlib
import os
import re
import shutil
import subprocess
from pathlib import Path
from typing import Sequence

import brand  # 色の正本は _brand.yml

COLORS = brand.palette()

_PERSON = (
    '<svg viewBox="0 0 40 48" class="{cls}" aria-hidden="true">'
    '<circle cx="20" cy="10" r="9"/><rect x="4" y="21" width="32" height="27" rx="12"/></svg>'
)


def _c(name: str) -> str:
    return COLORS.get(name, name)


def badge(chapter: str, title: str, brand: str = "") -> str:
    """右上の章バッジ。title の改行は \\n（<br> にする。pandoc が生の改行を空白にするため）。
    枚の見出し（h2）はバッジの分だけ右を空ける（theme/infographic.scss の :has(.ig-badge)）。"""
    small = f"<small>{html.escape(brand)}</small>" if brand else ""
    tt = "<br>".join(html.escape(line) for line in title.split("\n"))
    return (f'<div class="ig-badge"><div class="ch">{small}{html.escape(chapter)}</div>'
            f'<div class="tt">{tt}</div></div>\n')


def _fig(inner: str, alt: str) -> str:
    """alt があれば図として1つにまとめる（読み上げは alt だけ。lint の fig-alt と同じ趣旨）。"""
    if not alt:
        return inner
    return f'<div class="ig-fig" role="img" aria-label="{html.escape(alt)}">\n{inner}</div>\n'


def pictos(n: int, highlight: int = 0, label: str = "") -> str:
    """人のアイコンを n 個並べる。先頭 highlight 個を青にする。label は右に添える一言（任意）。"""
    icons = "".join(_PERSON.format(cls="hl" if i < highlight else "") for i in range(n))
    tail = f'<span class="muted" style="margin-left:24px;font-size:26px;font-weight:700">{html.escape(label)}</span>' if label else ""
    return f'<div class="ig-pictos" role="img" aria-label="{n}人">{icons}{tail}</div>\n'


def stack(rows: Sequence[tuple[str, Sequence[tuple[str, float, str]]]], total: float | None = None,
          alt: str = "") -> str:
    """構成バー。rows=[(行ラベル, [(区分ラベル, 値, 色), ...]), ...]。値は合計 total（既定は行ごとの合計）に対する幅。"""
    out = []
    for lab, segs in rows:
        tot = total or sum(v for _, v, _ in segs) or 1
        spans = "".join(
            f'<span data-w="{100 * v / tot:.2f}" style="--c:{_c(col)}">{html.escape(t)}</span>' for t, v, col in segs
        )
        out.append(f'<div class="ig-stack-row"><div class="lab">{html.escape(lab)}</div><div class="ig-stack">{spans}</div></div>')
    return _fig("\n".join(out) + "\n", alt)


def _num(v: float, dec: int, prefix: str, sign: bool) -> str:
    """値の属性。sign=True なら正に「+」、負は常に「−」＋絶対値（prefix は正のときだけ）。"""
    return (f'data-count="{v}" data-dec="{dec}" data-prefix="{html.escape(prefix)}" data-sign="{1 if sign else 0}">'
            f'{"+" if sign else prefix}{0:.{dec}f}')


def bars(labels: Sequence[str], values: Sequence[float], highlight: str | Sequence[str] = (), unit: str = "",
         prefix: str = "", dec: int = 0, max_value: float | None = None, accent: str | Sequence[str] = (),
         alt: str = "", sign: bool = False) -> str:
    """横棒＋値（型 chart の動く版）。figs.bars と同じ引数。主張の棒だけ青（highlight）、注目は橙（accent）、残りは灰。
    棒の長さは絶対値。sign=True で +／− を自動で付ける（増減の図）。"""
    if len(labels) != len(values):
        raise ValueError("labels と values の数が違う")
    hl = {highlight} if isinstance(highlight, str) else set(highlight)
    ac = {accent} if isinstance(accent, str) else set(accent)
    unknown = (hl | ac) - set(labels)
    if unknown:
        raise ValueError(f"highlight/accent が labels にない: {sorted(unknown)}")
    top = max_value or max(abs(v) for v in values) or 1
    out = []
    for lab, v in zip(labels, values):
        col = COLORS["blue"] if lab in hl else COLORS["orange"] if lab in ac else COLORS["gray"]
        u = f"<small>{html.escape(unit)}</small>" if unit else ""
        out.append(
            f'<div class="ig-hbar" style="--c:{col}"><div class="lab">{html.escape(lab)}</div>'
            f'<div class="track"><div class="fill" data-w="{100 * abs(v) / top:.2f}"></div></div>'
            f'<div class="val"><span {_num(v, dec, prefix, sign)}</span>{u}</div></div>'
        )
    return _fig("\n".join(out) + "\n", alt)


def stat(value: float, unit: str = "", label: str = "", dec: int = 0, prefix: str = "", sign: bool = False) -> str:
    """大きな数字（型 number の動く版）。sign=True で +／− を自動で付ける。"""
    lab = f'<div class="small muted">{html.escape(label)}</div>' if label else ""
    u = f"<small>{html.escape(unit)}</small>" if unit else ""
    return f'{lab}<div class="ig-stat"><span {_num(value, dec, prefix, sign)}</span>{u}</div>\n'


def callout(text: str) -> str:
    """赤い吹き出し（注目の一言）。"""
    return f'<span class="ig-callout">{html.escape(text)}</span>\n'


def _lines(body: str | Sequence[str]) -> str:
    """本文。文字列なら1段落、列なら1行ずつ（箇条書きの代わり。記号は付けない）。"""
    items = [body] if isinstance(body, str) else list(body)
    return "".join(f'<div class="b">{html.escape(t)}</div>' for t in items if t)


def cards(items: Sequence[tuple[str, str | Sequence[str]]], arrows: bool = False, highlight: str | Sequence[str] = (),
          numbered: bool = False, alt: str = "") -> str:
    """カード列（型 cards）。items=[(見出し, 本文), ...] を横に並べる（2〜4枚）。本文は文字列か行の列。
    arrows=True でカードの間に矢印（段階・流れ）。highlight の見出しのカードだけ青い枠（推す案・いまの段階）。
    numbered=True で左上に 1, 2, 3。revealjs では枚を開くと左から順に出る（theme/motion-gsap.html）。"""
    hl = {highlight} if isinstance(highlight, str) else set(highlight)
    out = []
    for i, (title, body) in enumerate(items):
        if arrows and i:
            out.append('<div class="ig-arrow" aria-hidden="true">→</div>')
        n = f'<div class="n">{i + 1}</div>' if numbered else ""
        cls = "ig-card hl" if title in hl else "ig-card"
        out.append(f'<div class="{cls}">{n}<div class="t">{html.escape(title)}</div>{_lines(body)}</div>')
    return _fig(f'<div class="ig-cards">{"".join(out)}</div>\n', alt)


def steps(items: Sequence[tuple[str, str | Sequence[str]]], alt: str = "") -> str:
    """番号付きの要点（型 cards の縦版。結論の3点・手順）。items=[(見出し, 本文), ...]（2〜4行）。
    1行＝大きな番号＋見出し＋本文。revealjs では枚を開くと上から順に出る。"""
    rows = "".join(f'<div class="row"><div class="n">{i + 1}</div><div><div class="t">{html.escape(t)}</div>{_lines(b)}</div></div>'
                   for i, (t, b) in enumerate(items))
    return _fig(f'<div class="ig-steps">{rows}</div>\n', alt)


def echart(option: dict, height: int = 320, alt: str = "", dec: int = 0, prefix: str = "", sign: bool = False) -> str:
    """ECharts の図。option は ECharts の設定（JSON にできるもの）。描画と動きは theme/motion-gsap.html。
    値ラベルの書式（dec/prefix/sign）は data-* で渡し、JS 側が formatter にする（JSON に関数を書けないため）。"""
    o = html.escape(json.dumps(option, ensure_ascii=False), quote=True)
    lab = f' role="img" aria-label="{html.escape(alt)}"' if alt else ""
    return (f'<div class="ig-echart" style="height:{height}px" data-option="{o}" data-dec="{dec}" '
            f'data-prefix="{html.escape(prefix)}" data-sign="{1 if sign else 0}"{lab}></div>\n')


def echart_bars(labels: Sequence[str], values: Sequence[float], highlight: str | Sequence[str] = (), unit: str = "",
                prefix: str = "", dec: int = 0, accent: str | Sequence[str] = (), alt: str = "", sign: bool = False,
                height: int | None = None) -> str:
    """横棒＋値を ECharts で描く（parts.bars と同じ引数・同じ配色）。棒が伸びながら値が数え上がる（label.valueAnimation）。
    負の値は 0 から左に伸びる。"""
    if len(labels) != len(values):
        raise ValueError("labels と values の数が違う")
    hl = {highlight} if isinstance(highlight, str) else set(highlight)
    ac = {accent} if isinstance(accent, str) else set(accent)
    unknown = (hl | ac) - set(labels)
    if unknown:
        raise ValueError(f"highlight/accent が labels にない: {sorted(unknown)}")
    cols = [COLORS["blue"] if l in hl else COLORS["orange"] if l in ac else COLORS["gray"] for l in labels]
    lo, hi = min(min(values), 0), max(max(values), 0)
    pad = (hi - lo) * 0.2 or 1
    option = {
        "textStyle": {"fontFamily": "Noto Sans JP, sans-serif"},
        "grid": {"left": 0, "right": 140, "top": 6, "bottom": 6, "containLabel": True},
        "xAxis": {"type": "value", "show": False, "min": lo - (pad if lo < 0 else 0), "max": hi + pad},
        "yAxis": {"type": "category", "data": list(labels), "inverse": True,
                  "axisLine": {"show": False}, "axisTick": {"show": False},
                  "axisLabel": {"fontSize": 26, "fontWeight": 700, "color": COLORS["ink"], "margin": 20}},
        "series": [{
            "type": "bar", "barWidth": 40, "showBackground": True,
            "backgroundStyle": {"color": COLORS["track"], "borderRadius": 20},
            "itemStyle": {"borderRadius": 20},
            "label": {"show": True, "position": "right", "fontSize": 36, "fontWeight": 900, "valueAnimation": True,
                      "distance": 16, "color": "inherit"},   # 値の色は棒の色。項目ごとの label は valueAnimation を無効にするので書かない
            "data": [{"value": float(v), "itemStyle": {"color": c}} for v, c in zip(values, cols)],
        }],
    }
    h = height or 40 + 70 * len(labels)
    tail = f'<div class="small muted" style="text-align:right;margin-top:-6px">単位：{html.escape(unit)}</div>' if unit else ""
    return echart(option, height=h, alt=alt, dec=dec, prefix=prefix, sign=sign) + tail


_REPO = Path(__file__).resolve().parents[4]          # <repo>/.claude/skills/slides/scripts → <repo>
_D2_DIR = _REPO / "tools" / "d2"
_FONT_NAME = "NotoSansJP[wght].ttf"
_FONT_URL = "https://github.com/google/fonts/raw/main/ofl/notosansjp/NotoSansJP%5Bwght%5D.ttf"   # OFL


def _d2_classes() -> str:
    """D2 の classes を _brand.yml の色から作る。q＝問い・処理、out＝結果、go＝推す結果、warn＝注意、e＝線。"""
    c = COLORS
    box = 'stroke-width: 2; border-radius: 8; font-size: 30'
    return f"""classes: {{
  q: {{ style: {{ fill: "{c['white']}"; stroke: "{c['blue']}"; {box}; font-color: "{c['ink']}"; bold: false }} }}
  out: {{ style: {{ fill: "{c['blue-pale']}"; stroke: "{c['blue']}"; {box}; font-color: "{c['ink']}"; bold: true }} }}
  go: {{ style: {{ fill: "{c['blue']}"; stroke: "{c['blue']}"; {box}; font-color: "{c['white']}"; bold: true }} }}
  warn: {{ style: {{ fill: "{c['white']}"; stroke: "{c['orange']}"; {box}; font-color: "{c['orange-text']}"; bold: true }} }}
  e: {{ style: {{ stroke: "{c['muted']}"; stroke-width: 2; font-size: 24; font-color: "{c['muted']}" }} }}
}}
*.class: q
*.height: 74
(* -> *)[*].class: e
"""   # 高さを固定するのは、D2（wasm）が仮名・漢字だけのラベルの高さを0と測るため（実測 2026-10-25）。2行のラベルは {height: 120}


def _font_source() -> Path:
    """Noto Sans JP（可変フォント）の置き場。SLIDES_FONT_TTF → theme/fonts → ~/.cache/tool-slides（無ければ取得）。"""
    env = os.environ.get("SLIDES_FONT_TTF")
    if env and Path(env).is_file():
        return Path(env)
    for p in (_REPO / "theme" / "fonts" / _FONT_NAME, Path.home() / ".cache" / "tool-slides" / _FONT_NAME):
        if p.is_file():
            return p
    import urllib.request
    dst = Path.home() / ".cache" / "tool-slides" / _FONT_NAME
    dst.parent.mkdir(parents=True, exist_ok=True)
    urllib.request.urlretrieve(_FONT_URL, dst)
    return dst


def _subset_fonts(text: str, d: Path) -> tuple[Path, Path]:
    """図の文字だけの静的フォント（400・700）を作る。D2 に 9MB の可変フォントを渡すと遅く、SVG にも全部入るため。"""
    from fontTools import subset
    from fontTools.ttLib import TTFont
    from fontTools.varLib import instancer
    chars = "".join(sorted(set(text) | set(" 0123456789.,:;!?%+-−()[]/ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz")))
    out = []
    for w in (400, 700):
        static = Path.home() / ".cache" / "tool-slides" / f"NotoSansJP-{w}.ttf"   # 可変→静的は重い（約10秒）ので1回だけ
        if not static.is_file():
            static.parent.mkdir(parents=True, exist_ok=True)
            instancer.instantiateVariableFont(TTFont(_font_source()), {"wght": w}).save(static)
        f = TTFont(static)
        sub = subset.Subsetter(subset.Options())
        sub.populate(text=chars)
        sub.subset(f)
        p = d / f"font-{w}.ttf"
        f.save(p)
        out.append(p)
    return out[0], out[1]


def _center_labels(svg: str) -> str:
    """箱（rect）の直後の文字を、箱の縦の中央に置き直す。D2 の ELK は箱を高くしても文字を元の高さに置くため（実測 2026-10-25）。"""
    def fix(m: re.Match) -> str:
        y, h, ty, fs, inner = float(m["y"]), float(m["h"]), float(m["ty"]), float(m["fs"]), m["inner"]
        n = len(re.findall(r"<tspan\b", inner))
        whole = m.group(0)
        if n > 1:
            # 2行目以降の送り（dy）を行の高さで引き直す。D2（wasm）は仮名・漢字だけの行の高さを 0 と測り、dy が 0 や小さい値になって
            # 行が重なる（実測 2026-10-25。"規則\\n（版付き）" の2行が同じ位置に出た）
            lh = fs * 1.2
            i = [0]
            def dy(mm: re.Match) -> str:
                i[0] += 1
                return 'dy="0.000000"' if i[0] == 1 else f'dy="{lh:.2f}"'
            fixed_inner = re.sub(r'dy="[-\d.]+"', dy, inner)
            whole = whole.replace(inner, fixed_inner, 1)
            block = lh * (n - 1)
        else:
            block = 0.0
        new = y + h / 2 - block / 2 + fs * 0.35                  # 1行目のベースライン
        return whole.replace(f'y="{m["ty"]}"', f'y="{new:.2f}"', 1)
    pat = (r'<rect x="[-\d.]+" y="(?P<y>[-\d.]+)" width="[-\d.]+" height="(?P<h>[-\d.]+)"[^>]*/></g>'
           r'<text x="[-\d.]+" y="(?P<ty>[-\d.]+)"[^>]*font-size:(?P<fs>[\d.]+)px[^>]*>(?P<inner>.*?)</text>')
    return re.sub(pat, fix, svg)


_D2_LABEL_RE = re.compile(r'^\s*([A-Za-z_][\w.]*)\s*:\s*"((?:[^"\\]|\\.)*)"', re.M)


def _multiline_heights(body: str) -> str:
    """2行以上のラベル（"1行目\\n2行目" と書く）の箱を、行数に合わせて高くする行を足す。
    箱の高さは _d2_classes() の `*.height: 74`（1行）で固定しているので、改行があっても高くならず文字が重なる（実測 2026-10-25）。
    自分で `X.height:` を書いた箱には足さない。"""
    out = []
    for m in _D2_LABEL_RE.finditer(body):
        name, label = m.group(1), m.group(2)
        lines = label.count("\\n") + 1
        if lines > 1 and not re.search(rf"^\s*{re.escape(name)}\.height\s*:", body, re.M):
            out.append(f"{name}.height: {74 + 36 * (lines - 1)}")
    return ("\n" + "\n".join(out)) if out else ""


def flow(d2: str, alt: str = "", cache_dir: str | os.PathLike = "_flow", layout: str = "elk") -> str:
    """D2 で描いた図（フロー・分岐）を SVG で埋める。revealjs では theme/motion-gsap.html が線の順に描く（DrawSVG）。

        A: クリック率の差は有意か
        G: 全ユーザーをBへ {class: go}
        A -> G: はい

    既定で向きは右（縦に並べるなら先頭に direction: down）、箱は class q（問い）・高さ74px（2行のラベルは "1行目\\n2行目" と引用符で書くと箱が高くなる）、線は class e。結果の箱は {class: out}、推す結果は {class: go}、注意は {class: warn}。
    色は _brand.yml から。SVG は本文・色・版のハッシュで cache_dir（デッキのフォルダ）にキャッシュする。"""
    body = d2.strip()
    if not body.startswith("direction:"):
        body = "direction: right\n" + body
    body += _multiline_heights(body)
    src = _d2_classes() + body + "\n"
    d = Path(cache_dir).resolve(); d.mkdir(parents=True, exist_ok=True)
    h = hashlib.sha256((src + layout + (_D2_DIR / "package.json").read_text(encoding="utf-8")).encode("utf-8")).hexdigest()[:10]
    svg = d / f"flow-{h}.svg"
    if not svg.exists():
        if not (_D2_DIR / "node_modules" / "@terrastruct" / "d2").is_dir():
            subprocess.run(["npm", "ci", "--silent", "--prefix", str(_D2_DIR)], check=True)
        work = d / f"flow-{h}"; work.mkdir(exist_ok=True)
        (work / "in.d2").write_text(src, encoding="utf-8")
        reg, bold = _subset_fonts(body, work)
        subprocess.run(["node", str(_D2_DIR / "render.mjs"), str(work / "in.d2"), str(svg), str(reg), str(bold), layout],
                       check=True, cwd=_D2_DIR)
        shutil.rmtree(work, ignore_errors=True)
    text = _center_labels(svg.read_text(encoding="utf-8"))
    text = re.sub(r"^<\?xml[^>]*>\s*", "", text)
    text = re.sub(r"\n[ \t]*\n+", "\n", text)   # 空行を消す。pandoc は raw HTML の中の空行で HTML を閉じ、残りを本文の文字にする（実測 2026-10-25）
    text = text.replace('preserveAspectRatio="xMinYMin meet"', 'preserveAspectRatio="xMidYMin meet"', 1)   # 枠の中で左右中央
    lab = f' role="img" aria-label="{html.escape(alt)}"' if alt else ""
    return f'<div class="ig-draw"{lab}>{text}</div>\n'
