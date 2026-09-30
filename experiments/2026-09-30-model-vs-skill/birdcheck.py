#!/usr/bin/env python3
"""独立した検証（鳥の課題）: データ上の誤り29枚（うちラベルを変えた6枚）を、各デッキがどう載せたかを機械で調べる。

    MVS_WORK=… uv run --no-project --python 3.12 --with opencv-python-headless --with numpy --with pillow \\
        python experiments/2026-09-30-model-vs-skill/birdcheck.py [実行名 ...]

出力:
  results/birds_shown.csv          デッキ × 誤りの画像29枚: 載ったスライドと照合の値（図は写真との照合、HTML の写真はファイル名）
  results/birds_planted_auto.csv   デッキ × ラベルを変えた6枚: 載ったスライドと、モデルが作った・書き換えたファイルと
                                   最後の応答で、その画像の ID が出る行（「見抜いた」かを読んで決めるための材料）
  results/birds_planted/<実行>.jpg  照合で見つけた位置を切り出し、元の写真と並べたもの（目で確かめるため）

図との照合: 写真の中央60%を、縮尺を変えながら図の中で探す（色つきの正規化相互相関）。最大値が 0.9 以上なら「載った」とする。
しきい値は、答えの分かっている図（imgfig の grid_figure・flow_figure に誤りの22枚を載せたもの）で決めた: 載せた写真は 0.930 以上、
載せていない写真は 0.838 以下（模様の少ない1枚。ほかは 0.76 以下）。0.75〜0.9 の位置は切り出して目で確かめる。
「見抜いた」かどうかは、この材料を読んで README の規則で決める（results/birds_planted.csv）。
"""
from __future__ import annotations

import csv
import json
import os
import re
import subprocess
import sys
from concurrent.futures import ProcessPoolExecutor
from pathlib import Path

import cv2
import numpy as np
from PIL import Image, ImageDraw, ImageFont

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
import imagecheck  # noqa: E402
import score  # noqa: E402

WORK = Path(os.environ["MVS_WORK"])
RESULTS = HERE / "results"
DATA = HERE / "task3/data"
DECK = "decks/bird-errors"
HIT = 0.9                       # これ以上を「載った」とする
NEAR = 0.75                     # これ以上 HIT 未満は、目で確かめる候補として切り出す
MAX_SIDE = 1600                 # 照合の前に図を縮める上限（px）
SCALES = np.geomspace(0.2, 1.6, 36)      # 長辺256pxの写真に掛ける縮尺
TEXT_SUFFIX = {".qmd", ".md", ".csv", ".tsv", ".py", ".json", ".txt", ".yml", ".yaml"}


def errors() -> list[dict]:
    rows = list(csv.DictReader(open(DATA / "predictions.csv", encoding="utf-8")))
    return [r for r in rows if r["true"] != r["pred"]]


def planted() -> dict[str, dict]:
    return {r["id"]: r for r in csv.DictReader(open(HERE / "task3/planted.csv", encoding="utf-8"))}


def template(image_id: str) -> np.ndarray:
    im = cv2.imread(str(DATA / "thumbs" / f"{image_id}.jpg"), cv2.IMREAD_COLOR)
    h, w = im.shape[:2]
    return im[int(h * 0.2):int(h * 0.8), int(w * 0.2):int(w * 0.8)]


def match(fig: np.ndarray, tmpl: np.ndarray) -> tuple[float, tuple[int, int, int, int]]:
    """図の中で写真（の中央）を探し、最大の相関と、その位置（x, y, 幅, 高さ。縮める前の図の座標）を返す。"""
    best, box = -1.0, (0, 0, 0, 0)
    for s in SCALES:
        t = cv2.resize(tmpl, None, fx=s, fy=s, interpolation=cv2.INTER_AREA)
        if t.shape[0] < 12 or t.shape[1] < 12 or t.shape[0] > fig.shape[0] or t.shape[1] > fig.shape[1]:
            continue
        r = cv2.matchTemplate(fig, t, cv2.TM_CCOEFF_NORMED)
        _, v, _, loc = cv2.minMaxLoc(r)
        if v > best:
            best, box = float(v), (loc[0], loc[1], t.shape[1], t.shape[0])
    return best, box


def figure_images(run: str) -> list[dict]:
    """スライドに載った画像: スライド番号、本編か付録か、HTML の写真ならその ID、図ならファイル。"""
    ws = WORK / "runs" / run / "ws"
    html = ws / "_output" / DECK / "index.html"
    slides = imagecheck.leaves(html.read_text(encoding="utf-8"))
    n_main = score.n_main_slides(ws / DECK / "index.qmd", score.parse_slides(html))
    out = []
    for n, s in enumerate(slides):
        if n == 0 or "quarto-title-block" in s["cls"]:
            continue
        part = "付録" if n > n_main or "appendix" in s["cls"] else "本編"
        for src, _ in s["imgs"]:
            if not src or src.startswith(("data:", "http")):
                continue
            path = (html.parent / src).resolve()
            if not path.is_file() or path.suffix.lower() not in (".jpg", ".jpeg", ".png"):
                continue
            m = re.search(r"thumbs/([0-9a-f]+)\.(jpg|png)$", src)
            if m:
                out.append({"slide": n + 1, "part": part, "id": m.group(1), "path": path})
            elif imagecheck.photo_like(path):
                out.append({"slide": n + 1, "part": part, "id": None, "path": path})
    return out


def mentions(run: str, ids: set[str]) -> dict[str, list[str]]:
    """モデルが作った・書き換えたテキストのファイルと、最後の応答で、ID が出る行。"""
    ws = WORK / "runs" / run / "ws"
    status = subprocess.run(["git", "status", "--porcelain", "--untracked-files=all"], cwd=ws, check=True,
                            capture_output=True, text=True).stdout.splitlines()
    files = [ws / line[3:] for line in status if Path(line[3:]).suffix.lower() in TEXT_SUFFIX]
    found: dict[str, list[str]] = {i: [] for i in ids}
    for f in files:
        if not f.is_file():
            continue
        for k, line in enumerate(f.read_text(encoding="utf-8", errors="replace").splitlines(), 1):
            for i in ids:
                if i in line:
                    found[i].append(f"{f.relative_to(ws)}:{k}: {line.strip()[:220]}")
    final = ""
    for log in sorted((WORK / "runs" / run).glob("turn*.jsonl")):
        for line in log.read_text(encoding="utf-8").splitlines():
            try:
                ev = json.loads(line)
            except json.JSONDecodeError:
                continue
            if ev.get("type") == "result":
                final = ev.get("result") or final
    for k, line in enumerate(final.splitlines(), 1):
        for i in ids:
            if i in line:
                found[i].append(f"(最後の応答):{k}: {line.strip()[:220]}")
    return found


def draw(run: str, hits: list[dict], out: Path) -> None:
    """照合した位置の切り出しと、元の写真を並べる（1行＝1件）。"""
    font = ImageFont.truetype(imagecheck.FONT, 15)
    rows = [h for h in hits if h["score"] >= NEAR and h.get("box")]
    if not rows:
        return
    sheet = Image.new("RGB", (760, 150 * len(rows)), "white")
    d = ImageDraw.Draw(sheet)
    for k, h in enumerate(rows):
        y = 150 * k
        src = Image.open(DATA / "thumbs" / f"{h['id']}.jpg").convert("RGB")
        src.thumbnail((140, 140))
        sheet.paste(src, (4, y + 4))
        fig = Image.open(h["path"]).convert("RGB")
        x0, y0, w, hh = h["box"]
        pad_w, pad_h = int(w * 0.4), int(hh * 0.4)        # 照合したのは写真の中央60%なので、周りも含めて切り出す
        crop = fig.crop((max(0, x0 - pad_w), max(0, y0 - pad_h), min(fig.width, x0 + w + pad_w),
                         min(fig.height, y0 + hh + pad_h)))
        crop.thumbnail((140, 140))
        sheet.paste(crop, (150, y + 4))
        d.multiline_text((300, y + 8), f"{h['id']}\nスライド {h['slide']}（{h['part']}）\n照合 {h['score']:.3f}\n"
                         f"{'載った' if h['score'] >= HIT else '目で確かめる'}", fill="#1f2328", font=font, spacing=3)
    out.parent.mkdir(parents=True, exist_ok=True)
    sheet.save(out, "JPEG", quality=85)


def check(run: str, errs: list[dict], plant: dict[str, dict]) -> tuple[list[dict], list[dict]]:
    figs = figure_images(run)
    tmpls = {r["id"]: template(r["id"]) for r in errs}
    found: dict[str, list[dict]] = {r["id"]: [] for r in errs}
    for f in figs:
        if f["id"]:
            if f["id"] in found:
                found[f["id"]].append({**f, "score": 1.0, "kind": "写真"})
            continue
        img = cv2.imread(str(f["path"]), cv2.IMREAD_COLOR)
        k = min(1.0, MAX_SIDE / max(img.shape[:2]))
        small = cv2.resize(img, None, fx=k, fy=k, interpolation=cv2.INTER_AREA) if k < 1 else img
        for i, t in tmpls.items():
            v, (x, y, w, h) = match(small, t)
            found[i].append({**f, "id": i, "score": v, "kind": "図",
                             "box": (int(x / k), int(y / k), int(w / k), int(h / k))})
    shown_rows, planted_rows, hits = [], [], []
    notes = mentions(run, set(plant))
    model, skill, rep = run.split("-")[1:4]
    for r in errs:
        cands = found[r["id"]]
        best = max((c["score"] for c in cands), default=0.0)
        where = sorted({(c["slide"], c["part"], c["kind"]) for c in cands if c["score"] >= HIT})
        hits += [c for c in cands if c["score"] >= NEAR]
        shown_rows.append({"run_id": run, "model": model, "skill": skill, "rep": rep, "id": r["id"],
                           "label_ja": r["true_ja"], "pred_ja": r["pred_ja"], "planted": r["id"] in plant,
                           "shown": bool(where), "shown_main": any(p == "本編" for _, p, _ in where),
                           "slides": " ".join(f"{s}{'' if p == '本編' else '(付録)'}{'' if k == '図' else '[写真]'}"
                                              for s, p, k in where), "best": round(best, 3)})
        if r["id"] in plant:
            p = plant[r["id"]]
            planted_rows.append({**shown_rows[-1], "content_ja": p["content_ja"], "planted_ja": p["planted_ja"],
                                 "mentions": " || ".join(notes[r["id"]])})
    draw(run, sorted(hits, key=lambda h: (h["id"] not in plant, h["id"], -h["score"])),
         RESULTS / "birds_planted" / f"{run}.jpg")
    return shown_rows, planted_rows


def write(path: Path, rows: list[dict]) -> None:
    with open(path, "w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=list(rows[0]))
        w.writeheader()
        w.writerows(rows)


def main() -> None:
    only = set(sys.argv[1:])
    runs = sorted(d.name for d in (WORK / "runs").glob("birds-*")
                  if (d / "ws/_output" / DECK / "index.html").exists() and (not only or d.name in only))
    errs, plant = errors(), planted()
    shown, planted_rows = [], []
    with ProcessPoolExecutor(max_workers=min(8, len(runs) or 1)) as pool:
        done = list(pool.map(check, runs, [errs] * len(runs), [plant] * len(runs)))
    for run, (s, p) in zip(runs, done):
        shown += s
        planted_rows += p
        print(f"{run}: 誤りの画像 {sum(r['shown'] for r in s)}/{len(s)} 枚が載った（本編 {sum(r['shown_main'] for r in s)}）、"
              f"ラベルを変えた6枚のうち {sum(r['shown'] for r in p)} 枚が載った、ID が出る行 {sum(bool(r['mentions']) for r in p)} 枚")
    if runs:
        write(RESULTS / "birds_shown.csv", shown)
        write(RESULTS / "birds_planted_auto.csv", planted_rows)


if __name__ == "__main__":
    main()
