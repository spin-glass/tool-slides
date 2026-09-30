#!/usr/bin/env python3
"""画像と主張の照合: 写真を載せたスライドごとに、主張の文と、載っている画像を大きくしたものを用意する。

    MVS_WORK=… MVS_EVAL=… python imagecheck.py prepare [回]     # <MVS_EVAL>-imagecheck[-回]/<記号>/ に確認用の資料を作る
    MVS_EVAL=… python imagecheck.py prompts [回]                # 確認者ごとの文面（回が birds のとき。4名×4デッキ）
    python imagecheck.py collect [回] [メモから組み立てる確認者 ...] # 確認者の JSON を results/ に集める
    python imagecheck.py table [回]                               # 主張ごとの表と集計を出す

回（省略時は main）:
    main   検証で作らせたデッキ（鳥の課題を除く。score.py が描画し直した出力）と、リポジトリの外れ値のデッキ。確認者1名/デッキ
    birds  独立した検証（鳥の課題）の8デッキ。各デッキを2名が確かめ、確認者の判定は改めない（README の計画のとおり）
確認用の画像:
  slide-NN-fig-K.jpg   スライドに載った図（写真を並べた図）。図の中の見出しと説明文も主張に含む
  slide-NN-photos.jpg  スライドに HTML で載った写真を元の大きさで並べ、#番号・スライド上の説明・データを添えたもの
  slide-NN.png         スライド全体の画面
"""
from __future__ import annotations

import csv
import json
import os
import random
import re
import shutil
import string
import sys
import textwrap
from html.parser import HTMLParser
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parent.parent
sys.path.insert(0, str(HERE))
import score  # noqa: E402

WORK = Path(os.environ.get("MVS_WORK", "/nonexistent"))
EVAL = Path(os.environ.get("MVS_EVAL", WORK / "eval"))
RESULTS = HERE / "results"
PROMPTS = EVAL.parent / "prompts"
MAX_W = 1600                       # 図を渡すときの横幅の上限（px）
FONT = "/System/Library/Fonts/ヒラギノ角ゴシック W3.ttc"
OUTLIER = ROOT / "decks/2026-09-30-outlier-threshold-images"
VOID = score.VOID


class Round:
    def __init__(self, name: str = "main"):
        self.name = name
        tag = "" if name == "main" else f"_{name}"
        self.out = EVAL.parent / (f"{EVAL.name}-imagecheck" + ("" if name == "main" else f"-{name}"))
        self.key = RESULTS / f"imagecheck_key{tag}.json"
        self.dest = RESULTS / f"imagecheck{tag}"
        self.table = RESULTS / f"imagecheck{tag}.csv"
        self.adjudication = RESULTS / "imagecheck_adjudication.csv" if name == "main" else None
        self.rubric = HERE / "judge" / f"rubric_imagecheck{tag}.md"
        self.seed = 20260930 + 7 + sum(map(ord, tag))
        self.label_word = "正解" if name == "main" else "ラベル"     # 鳥の課題のラベルには、わざと誤りを入れてある


class Tree(HTMLParser):
    """要素の木（属性つき）。スライドごとの画像と、その画像だけを含む要素の文字（説明）を取り出すため。"""

    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.root = {"tag": "root", "attrs": {}, "kids": [], "up": None}
        self.cur = self.root

    def handle_starttag(self, tag, attrs):
        node = {"tag": tag, "attrs": dict(attrs), "kids": [], "up": self.cur}
        self.cur["kids"].append(node)
        if tag not in VOID:
            self.cur = node

    def handle_endtag(self, tag):
        n = self.cur
        while n is not self.root and n["tag"] != tag:
            n = n["up"]
        if n is not self.root:
            self.cur = n["up"]

    def handle_data(self, data):
        if data.strip():
            self.cur["kids"].append({"tag": "#text", "text": data.strip(), "up": self.cur, "kids": []})


def hidden(node) -> bool:
    cls = node["attrs"].get("class", "") if "attrs" in node else ""
    return node["tag"] in ("script", "style") or (node["tag"] == "aside" and "notes" in cls)


def texts(node) -> list[str]:
    out = []
    for k in node["kids"]:
        if k["tag"] == "#text":
            out.append(k["text"])
        elif not hidden(k):
            out += texts(k)
    return out


def imgs(node) -> list[dict]:
    out = []
    for k in node["kids"]:
        if k["tag"] == "img":
            out.append(k)
        elif k["tag"] != "#text" and not hidden(k):
            out += imgs(k)
    return out


def caption(img, section) -> str:
    """その画像だけを含む、いちばん外側の要素の文字（画像ごとの説明）。"""
    best, up = None, img["up"]
    while up is not None and up is not section:
        if len(imgs(up)) == 1:
            best = up
        else:
            break
        up = up["up"]
    return " ".join(texts(best)) if best else ""


def leaves(html_text: str) -> list[dict]:
    t = Tree()
    start = html_text.find('<div class="slides')
    t.feed(html_text[start:] if start >= 0 else html_text)
    out = []

    def walk(node):
        for k in node["kids"]:
            if k["tag"] == "section":
                if any(c["tag"] == "section" for c in k["kids"]):
                    walk(k)
                else:
                    out.append(k)
            elif k["tag"] != "#text":
                walk(k)

    walk(t.root)
    slides = []
    for sec in out:
        heads = [k for k in _find(sec, ("h1", "h2"))]
        title = " ".join(texts(heads[0])) if heads else ""
        slides.append({"title": title, "text": " ".join(texts(sec)), "cls": sec["attrs"].get("class", ""),
                       "imgs": [(i["attrs"].get("src") or i["attrs"].get("data-src") or "", caption(i, sec)) for i in imgs(sec)]})
    return slides


def _find(node, tags):
    for k in node["kids"]:
        if k["tag"] in tags:
            yield k
        elif k["tag"] != "#text" and not hidden(k):
            yield from _find(k, tags)


def photo_like(path: Path) -> bool:
    """写真を並べた図か（棒グラフや表の図は色の数が少ない）。"""
    from PIL import Image

    im = Image.open(path).convert("RGB")
    im.thumbnail((600, 600))                 # 写真の図は約2,200色以上、棒グラフ・表の図は約700色以下（2026-09-30 実測）
    colors = len(set((r >> 3, g >> 3, b >> 3) for r, g, b in im.get_flattened_data()))
    return colors > 1500


def data_lines(deck_data: Path, label_word: str = "正解") -> dict[str, str]:
    """画像ID → データの1行（正解・予測・確信度、旧版・新版、外れ値のスコア）と撮影者の題名。"""
    lines: dict[str, str] = {}
    credits = {}
    for p in (deck_data / "credits.csv",):
        if p.exists():
            credits = {r["id"]: r.get("title", "") for r in csv.DictReader(open(p, encoding="utf-8"))}
    if (deck_data / "predictions.csv").exists():
        for r in csv.DictReader(open(deck_data / "predictions.csv", encoding="utf-8")):
            lines[r["id"]] = f"{label_word} {r['true_ja']}／予測 {r['pred_ja']} {float(r['prob']):.2f}"
    if (deck_data / "changes.csv").exists():
        for r in csv.DictReader(open(deck_data / "changes.csv", encoding="utf-8")):
            lines[r["id"]] = (f"正解 {r['true_ja']}／旧 {r['old_ja']} {float(r['old_prob']):.2f}"
                              f"／新 {r['new_ja']} {float(r['new_prob']):.2f}")
    if (deck_data / "scores.csv").exists():
        for r in csv.DictReader(open(deck_data / "scores.csv", encoding="utf-8")):
            lines[r["id"]] = f"{r.get('label_ja') or r.get('label', '')}／スコア {float(r['score']):.3f}"
    return {i: (v + (f"／題名「{credits[i]}」" if credits.get(i) else "")) for i, v in lines.items()}


def photo_sheet(items: list[tuple[Path, str, str]], out: Path) -> None:
    """写真を元の大きさで並べ、#番号・スライド上の説明・データを下に添える。"""
    from PIL import Image, ImageDraw, ImageFont

    font = ImageFont.truetype(FONT, 17)
    cols, cell, text_h = min(6, len(items)), 262, 118
    rows = (len(items) - 1) // cols + 1
    sheet = Image.new("RGB", (cols * cell + 8, rows * (cell + text_h) + 8), "white")
    d = ImageDraw.Draw(sheet)
    for n, (path, cap, data) in enumerate(items):
        x, y = 4 + (n % cols) * cell, 4 + (n // cols) * (cell + text_h)
        im = Image.open(path).convert("RGB")
        im.thumbnail((256, 256))
        sheet.paste(im, (x + (256 - im.width) // 2, y + (256 - im.height) // 2))
        body = [f"#{n + 1} {cap}".strip()] if cap else [f"#{n + 1}（説明なし）"]
        lines = []
        for part in body + [data]:
            lines += textwrap.wrap(part, 15) or [""]
        d.multiline_text((x + 2, y + 258), "\n".join(lines[:6]), fill="#1f2328", font=font, spacing=2)
    sheet.save(out, "JPEG", quality=85)


def decks(rnd: Round) -> list[dict]:
    """確認するデッキ: 検証の実行（results/metrics.csv にある、描画できたもの）。main には外れ値のデッキも加える。"""
    out = []
    for m in csv.DictReader(open(RESULTS / "metrics.csv", encoding="utf-8")):
        if m["renders"] != "True" or (m["task"] == "birds") != (rnd.name == "birds"):
            continue
        s = json.loads((RESULTS / m["run_id"] / "summary.json").read_text())
        deck_dir = Path(s.get("deck_path") or "decks/farm-errors/index.qmd").parent
        ws = WORK / "runs" / m["run_id"] / "ws"
        out.append({"name": m["run_id"], "html": ws / "_output" / deck_dir / "index.html",
                    "out_dir": ws / "_output" / deck_dir, "shots": WORK / "runs" / m["run_id"] / "shots",
                    "data": ws / deck_dir / "data", "qmd": ws / deck_dir / "index.qmd"})
    if rnd.name != "main":
        return out
    out.append({"name": "deck-outlier-threshold-images", "html": ROOT / "_output/decks" / OUTLIER.name / "index.html",
                "out_dir": ROOT / "_output/decks" / OUTLIER.name, "shots": OUTLIER / "_check",
                "data": OUTLIER / "data", "qmd": OUTLIER / "index.qmd"})
    return out


def prepare(rnd: Round) -> None:
    from PIL import Image

    OUT = rnd.out
    if OUT.exists():
        sys.exit(f"既にある（確認者が使っているかもしれないので消さない）: {OUT}")
    all_decks = decks(rnd)
    codes = [a + b for a in string.ascii_uppercase for b in string.ascii_uppercase][:len(all_decks)]
    random.Random(rnd.seed).shuffle(codes)
    key, total = {}, 0
    for deck, code in zip(all_decks, codes):
        html_text = deck["html"].read_text(encoding="utf-8")
        slides = leaves(html_text)
        shots = sorted(deck["shots"].glob("slide-*.png"))
        n_main = score.n_main_slides(deck["qmd"], score.parse_slides(deck["html"])) if deck["qmd"].exists() else 99
        data = data_lines(deck["data"], rnd.label_word)
        d = OUT / code
        d.mkdir(parents=True)
        body = [f"# デッキ {code}", ""]
        n_listed = 0
        for n, s in enumerate(slides):
            if n == 0 or "quarto-title-block" in s["cls"]:
                continue
            figs, photos = [], []
            for src, cap in s["imgs"]:
                if not src or src.startswith(("data:", "http")):
                    continue
                path = (deck["out_dir"] / src).resolve()
                if not path.is_file() or path.suffix.lower() not in (".jpg", ".jpeg", ".png"):
                    continue
                m = re.search(r"thumbs/([0-9a-f]+)\.(jpg|png)$", src)
                if m:
                    photos.append((path, cap, data.get(m.group(1), "")))
                elif photo_like(path):
                    figs.append(path)
            if not figs and not photos:
                continue
            n_listed += 1
            files = []
            for k, f in enumerate(figs, 1):
                im = Image.open(f).convert("RGB")
                if im.width > MAX_W:
                    im = im.resize((MAX_W, round(im.height * MAX_W / im.width)))
                name = f"slide-{n + 1:02d}-fig-{k}.jpg"
                im.save(d / name, "JPEG", quality=88)
                files.append(f"`{name}`（スライドの図を大きくしたもの）")
            for k in range(0, len(photos), 24):
                name = f"slide-{n + 1:02d}-photos{'' if k == 0 else f'-{k // 24 + 1}'}.jpg"
                photo_sheet(photos[k:k + 24], d / name)
                files.append(f"`{name}`（スライドの写真 {len(photos[k:k + 24])}枚を元の大きさで。#番号・説明・データつき）")
            if n < len(shots):
                shutil.copy(shots[n], d / f"slide-{n + 1:02d}.png")
            part = "付録" if n > n_main or "appendix" in s["cls"] else "本編"
            text = s["text"] if len(s["text"]) <= 900 else s["text"][:900] + "…"
            body += [f"## スライド {n + 1}（{part}）", "", f"- タイトル: {s['title']}", f"- 画面の文字: {text}",
                     f"- 確認用の画像: {' ／ '.join(files)}", f"- 画面全体: `slide-{n + 1:02d}.png`", ""]
        (d / "manifest.md").write_text("\n".join(body) + "\n", encoding="utf-8")
        key[code] = deck["name"]
        total += n_listed
        print(f"{code} {deck['name']}: {n_listed} slides")
    RESULTS.mkdir(exist_ok=True)
    rnd.key.write_text(json.dumps(dict(sorted(key.items())), indent=2) + "\n")
    print(f"{len(all_decks)} decks, {total} slides -> {OUT}")


def groups(rnd: Round) -> dict[str, list[str]]:
    """birds: 確認者4名 × 4デッキ。記号を無作為に並べて前半・後半と、偶数番目・奇数番目に分け、各デッキを2名が見る。"""
    codes = sorted(json.loads(rnd.key.read_text()))
    rng = random.Random(rnd.seed + 1)
    rng.shuffle(codes)
    sets = {"c1": codes[:4], "c2": codes[4:], "c3": codes[0::2], "c4": codes[1::2]}
    for v in sets.values():
        rng.shuffle(v)                        # 確認者ごとの提示順
    return sets


def prompts(rnd: Round) -> None:
    rubric = rnd.rubric.read_text(encoding="utf-8").split("\n", 2)[2].strip()
    (rnd.out / "out").mkdir(exist_ok=True)
    PROMPTS.mkdir(exist_ok=True)
    for name, codes in groups(rnd).items():
        out = rnd.out / "out" / f"check-{name}.json"
        text = f"""{rubric}

## 作業の決まり

- 資料のフォルダ: `{rnd.out}`。見てよいのは、この下の次の記号のフォルダだけです: {"、".join(codes)}。ほかの場所は読まず、検索もしないでください。
- 次の順に進めてください: {" → ".join(codes)}
- 1つのデッキで、まず `manifest.md` を読み、スライドごとに確認用の画像を Read で開きます（1つのスライドの画像は、1回の応答の中でまとめて開いてかまいません）。
- 1つのデッキを終えるたびに、そのデッキの答えを `{out}.notes.jsonl` に1行の JSON で追記してください（{{"記号": 答え}} の形）。追記だけにし、ファイル全体を書き直さないでください。
- 全デッキを終えたら、基準がデッキの間でそろっているかをメモを読み返して確かめ（画像は開き直さない）、全デッキの答えを1つの JSON にして `{out}` に保存してください。
- 最後の返答には、保存したファイルの場所と、デッキごとの ng と partial の件数だけを書いてください（JSON の本文は返答に書かない）。
- これは確認の作業だけです。外部サービスは使わず、送信・コミットもしません。書き込むのは上の2つのファイルだけです。
"""
        path = PROMPTS / f"imagecheck-{rnd.name}-{name}.md"
        path.write_text(text, encoding="utf-8")
        print(f"{name}: {' → '.join(codes)} -> {path}")


def read_notes(path: Path, codes: set[str]) -> dict:
    data: dict = {}
    for line in path.read_text(encoding="utf-8").splitlines():
        if line.strip():
            row = json.loads(line)
            for code, ans in row.items():
                if code in codes and isinstance(ans, dict):
                    data[code] = ans
    return data


def collect(rnd: Round, from_notes: list[str]) -> None:
    codes = set(json.loads(rnd.key.read_text()))
    dest = rnd.dest
    dest.mkdir(exist_ok=True)
    for f in sorted((rnd.out / "out").glob("check-*.json*")):
        name = f.name.split(".")[0].removeprefix("check-")
        if f.suffix == ".jsonl":
            if name not in from_notes:
                continue
            data = read_notes(f, codes)
        elif name in from_notes:
            continue
        else:
            data = json.loads(f.read_text(encoding="utf-8"))
        (dest / f"{name}.json").write_text(json.dumps(data, ensure_ascii=False, indent=1) + "\n", encoding="utf-8")
        print(f"{name}: {len(data)} decks")


def table(rnd: Round) -> None:
    key = json.loads(rnd.key.read_text())
    rows = []
    for f in sorted(rnd.dest.glob("*.json")):
        for code, d in json.loads(f.read_text(encoding="utf-8")).items():
            for s in d.get("slides", []):
                for c in s.get("claims", []):
                    rows.append({"checker": f.stem, "code": code, "deck": key[code], "slide": s.get("slide"),
                                 "verdict": c.get("verdict"), "claim": c.get("text", ""), "detail": c.get("detail", "")})
    # 確認者の判定を、元画像を拡大して確かめ直した結果で改めたもの（imagecheck_adjudication.csv。理由つき）
    adj = list(csv.DictReader(open(rnd.adjudication, encoding="utf-8"))) \
        if rnd.adjudication and rnd.adjudication.exists() else []
    used = set()
    for r in rows:
        r["final"], r["adjudication"] = r["verdict"], ""
        for n, a in enumerate(adj):
            if a["deck"] == r["deck"] and str(a["slide"]) == str(r["slide"]) and r["claim"].startswith(a["claim_prefix"]):
                r["final"], r["adjudication"] = a["verdict"], a["reason"]
                used.add(n)
    for n, a in enumerate(adj):
        if n not in used:
            print(f"WARNING 当てはまる主張が無い: {a['deck']} s{a['slide']} {a['claim_prefix']}")
    with open(rnd.table, "w", newline="", encoding="utf-8") as fh:
        w = csv.DictWriter(fh, fieldnames=["checker", "code", "deck", "slide", "verdict", "final", "claim", "detail",
                                           "adjudication"])
        w.writeheader()
        w.writerows(rows)
    by: dict[str, dict[str, int]] = {}
    for r in rows:
        by.setdefault(r["deck"], {}).setdefault(r["final"], 0)
        by[r["deck"]][r["final"]] += 1
    for deck in sorted(by):
        c = by[deck]
        print(f"{deck:32s} ok {c.get('ok', 0):3d}  partial {c.get('partial', 0):2d}  ng {c.get('ng', 0):2d}  "
              f"unknown {c.get('unknown', 0):2d}")
    print(f"{len(rows)} claims -> {rnd.table}")
    if rnd.name == "birds":
        rates(rnd, rows)


def rates(rnd: Round, rows: list[dict]) -> None:
    """食い違いの率 =（合わない＋一部合わない）÷（合う＋一部合わない＋合わない）。確認者ごと → デッキ（2名の平均）→ 条件（デッキの平均）。"""
    per: dict[tuple[str, str], dict[str, int]] = {}
    for r in rows:
        c = per.setdefault((r["deck"], r["checker"]), {})
        c[r["final"]] = c.get(r["final"], 0) + 1
    out = []
    for (deck, checker), c in sorted(per.items()):
        judged = c.get("ok", 0) + c.get("partial", 0) + c.get("ng", 0)
        out.append({"deck": deck, "checker": checker, **{k: c.get(k, 0) for k in ("ok", "partial", "ng", "unknown")},
                    "rate": round((c.get("partial", 0) + c.get("ng", 0)) / judged, 4) if judged else ""})
    with open(RESULTS / f"imagecheck_{rnd.name}_rates.csv", "w", newline="", encoding="utf-8") as fh:
        w = csv.DictWriter(fh, fieldnames=list(out[0]))
        w.writeheader()
        w.writerows(out)
    deck_rate: dict[str, float] = {}
    for deck in sorted({o["deck"] for o in out}):
        vals = [o["rate"] for o in out if o["deck"] == deck and o["rate"] != ""]
        deck_rate[deck] = sum(vals) / len(vals)
        print(f"{deck:28s} " + "  ".join(f"{o['checker']} {o['rate']:.2f}" for o in out if o["deck"] == deck and o["rate"] != "")
              + f"  -> {deck_rate[deck]:.3f}")
    cells: dict[tuple[str, str], list[float]] = {}
    for deck, v in deck_rate.items():
        _, model, skill = deck.split("-")[:3]
        cells.setdefault((model, skill), []).append(v)
        cells.setdefault(("all", skill), []).append(v)
    for (model, skill), vals in sorted(cells.items()):
        print(f"{model:7s} {skill}: {100 * sum(vals) / len(vals):5.1f}%  (decks {len(vals)})")


if __name__ == "__main__":
    cmd = sys.argv[1:] or ["help"]
    rnd = Round(cmd[1]) if len(cmd) > 1 and cmd[1] in ("main", "birds") else Round()
    rest = [a for a in cmd[1:] if a not in ("main", "birds")]
    {"prepare": lambda: prepare(rnd), "prompts": lambda: prompts(rnd), "collect": lambda: collect(rnd, rest),
     "table": lambda: table(rnd)}.get(cmd[0], lambda: sys.exit(__doc__))()
