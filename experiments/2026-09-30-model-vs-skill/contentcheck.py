#!/usr/bin/env python3
"""写真の中身の検証: デッキに載った誤りの写真ごとに、スライドの図（#番号つき）と元の写真（人の枠つき）を並べた資料を作る。

    MVS_WORK=… MVS_EVAL=… uv run --no-project --python 3.12 --with opencv-python-headless --with numpy --with pillow \\
        python experiments/2026-09-30-model-vs-skill/contentcheck.py prepare <回> <課題> 実行名 ...
    MVS_EVAL=… python contentcheck.py prompts <回>        # 確認者の文面（デッキと同じ人数。各デッキを2名が見る）
    python contentcheck.py collect <回>                   # 確認者の JSON を results/content_<回>/ に集める
    python contentcheck.py table <回>                     # 判定の表と、私が確かめる候補（「事実と違う」）を出す

課題は water（task4）か farmh（task5）。確認用の資料（<MVS_EVAL>-content-<回>/<デッキ記号>/）:
  manifest.md               スライドごとのタイトル・画面の文字・確認用の画像の名前
  slide-NN-fig-K.jpg        スライドの図。誤りの写真が載っている位置に #番号
  slide-NN-fig-K-truth.jpg  同じ #番号の元の写真（人の枠つき）と、データのラベル・予測
  truth/<番号>.jpg           元の写真（長辺1024px、人の枠つき）。細部を確かめたいとき
写真の位置は birdcheck.py と同じ照合（写真の中央60%、色つきの正規化相互相関 0.9 以上）で決める。
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
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))

WORK = Path(os.environ.get("MVS_WORK", "/nonexistent"))
EVAL = Path(os.environ.get("MVS_EVAL", WORK / "eval"))
RESULTS = HERE / "results"
PROMPTS = EVAL.parent / "prompts"
TASKS = {"water": ("task4", "_cache_hard", "decks/water-errors"),
         "farmh": ("task5", "_cache_hard_farm", "decks/farm-hidden-errors")}
FONT = "/System/Library/Fonts/ヒラギノ角ゴシック W3.ttc"
MAX_W = 1600
SEED = 20260930 + 11


def out_dir(rnd: str) -> Path:
    return EVAL.parent / f"{EVAL.name}-content-{rnd}"


def key_path(rnd: str) -> Path:
    return RESULTS / f"content_key_{rnd}.json"


def errors(task: str) -> dict[str, dict]:
    base = HERE / TASKS[task][0]
    return {r["id"]: r for r in csv.DictReader(open(base / "gt.csv", encoding="utf-8")) if r["error"] == "True"}


def labels_ja(task: str) -> dict[str, dict]:
    base = HERE / TASKS[task][0] / "data"
    return {r["id"]: r for r in csv.DictReader(open(base / "predictions.csv", encoding="utf-8"))}


def slide_images(run: str, deck: str) -> tuple[list[dict], list[dict]]:
    """スライドごとの画像（図または HTML の写真）と、スライドの文字。imagecheck.leaves を使う。"""
    import imagecheck
    import score

    ws = WORK / "runs" / run / "ws"
    html = ws / "_output" / deck / "index.html"
    slides = imagecheck.leaves(html.read_text(encoding="utf-8"))
    n_main = score.n_main_slides(ws / deck / "index.qmd", score.parse_slides(html))
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
            m = re.search(r"(?:thumbs|images)/([0-9a-f]{16})\.(?:jpg|png)$", src)
            out.append({"slide": n + 1, "part": part, "path": path, "id": m.group(1) if m else None})
    return out, slides


_TMPLS: dict = {}


def match_job(job: tuple) -> list[tuple]:
    """1つの図の中で、誤りの写真すべてを探す（並列の1単位）。見つかった (id, 照合の値, 枠) のリスト。"""
    import cv2

    import birdcheck as bc

    task, path, ids = job
    bc.THUMBS = HERE / TASKS[task][0] / "data/thumbs"
    for i in ids:
        if i not in _TMPLS:
            _TMPLS[i] = bc.template(i)
    img = cv2.imread(str(path), cv2.IMREAD_COLOR)
    s = min(1.0, bc.MAX_SIDE / max(img.shape[:2]))
    small_img = cv2.resize(img, None, fx=s, fy=s, interpolation=cv2.INTER_AREA) if s < 1 else img
    hits = []
    for i in ids:
        v, (x, y, w, h) = bc.match(small_img, _TMPLS[i])
        if v >= bc.HIT:
            hits.append((i, v, (int(x / s), int(y / s), int(w / s), int(h / s))))
    return hits


def prepare(rnd: str, task: str, runs: list[str]) -> None:
    from concurrent.futures import ProcessPoolExecutor

    from PIL import Image, ImageDraw, ImageFont

    import imagecheck

    base, cache, deck = TASKS[task]
    errs = errors(task)
    lab = labels_ja(task)
    OUT = out_dir(rnd)
    if OUT.exists():
        sys.exit(f"既にある（確認者が使っているかもしれないので消さない）: {OUT}")
    codes = [a + b for a in string.ascii_uppercase for b in string.ascii_uppercase]
    rng = random.Random(SEED + sum(map(ord, rnd)))
    rng.shuffle(codes)
    font = ImageFont.truetype(FONT, 26)
    small = ImageFont.truetype(FONT, 17)
    decks = {run: slide_images(run, deck) for run in runs}
    jobs = [(run, k, f["path"]) for run, (imgs, _) in decks.items() for k, f in enumerate(imgs)
            if not f["id"] and imagecheck.photo_like(f["path"])]
    with ProcessPoolExecutor(max_workers=8) as pool:
        found = list(pool.map(match_job, [(task, path, sorted(errs)) for _, _, path in jobs]))
    matches = {(run, k): hits for (run, k, _), hits in zip(jobs, found)}
    key = {}
    for run, code in zip(sorted(runs), codes):
        d = OUT / code
        (d / "truth").mkdir(parents=True)
        imgs, slides = decks[run]
        num = 0
        body = [f"# デッキ {code}", ""]
        by_slide: dict[int, list[str]] = {}
        placed = []
        for k, f in enumerate(imgs):
            if f["id"]:                     # HTML の写真（ファイル名で分かる）
                if f["id"] in errs:
                    placed.append({**f, "fig": k, "box": None, "id": f["id"], "score": 1.0})
                continue
            for i, v, box in matches.get((run, k), []):
                placed.append({**f, "fig": k, "id": i, "score": v, "box": box})
        placed.sort(key=lambda p: (p["slide"], p["fig"], (p["box"] or (0, 0))[1] // 40, (p["box"] or (0, 0))[0]))
        for p in placed:
            num += 1
            p["n"] = num
        for k, f in enumerate(imgs):
            mine = [p for p in placed if p["fig"] == k]
            if not mine:
                continue
            name = f"slide-{f['slide']:02d}-fig-{k + 1}"
            if f["id"]:                     # HTML の写真: そのまま写し、番号は manifest に書く
                shutil.copy(f["path"], d / f"{name}.jpg")
            else:
                im = Image.open(f["path"]).convert("RGB")
                sc = min(1.0, MAX_W / im.width)
                im = im.resize((round(im.width * sc), round(im.height * sc))) if sc < 1 else im
                dr = ImageDraw.Draw(im)
                for p in mine:
                    x, y = p["box"][0] * sc, p["box"][1] * sc
                    tag = f"#{p['n']}"
                    tw = dr.textlength(tag, font=font)
                    dr.rectangle((x - 2, y - 2, x + tw + 8, y + 32), fill="#d00000")
                    dr.text((x + 3, y), tag, fill="white", font=font)
                im.save(d / f"{name}.jpg", "JPEG", quality=88)
            cols = min(4, len(mine))
            rows = (len(mine) - 1) // cols + 1
            cell_w, cell_h = 400, 400 + 52
            grid = Image.new("RGB", (cols * cell_w, rows * cell_h), "white")
            gd = ImageDraw.Draw(grid)
            for j, p in enumerate(mine):
                t = Image.open(HERE / cache / "gt" / f"{p['id']}.jpg").convert("RGB")
                t.save(d / "truth" / f"{p['n']}.jpg", "JPEG", quality=88)
                t.thumbnail((cell_w - 10, cell_w - 10))
                x0, y0 = (j % cols) * cell_w, (j // cols) * cell_h
                grid.paste(t, (x0 + 5, y0 + 5))
                r = lab[p["id"]]
                gd.text((x0 + 6, y0 + cell_w - 2), f"#{p['n']}  ラベル {r['true_ja']}／予測 {r['pred_ja']}",
                        fill="#1f2328", font=small)
            grid.save(d / f"{name}-truth.jpg", "JPEG", quality=88)
            by_slide.setdefault(f["slide"], []).append(
                f"`{name}.jpg`（スライドの図。#{', #'.join(str(p['n']) for p in mine)}）／ `{name}-truth.jpg`（同じ番号の元の写真）"
                + ("" if not f["id"] else f"。HTML の写真で、番号は #{mine[0]['n']}"))
        for sn in sorted(by_slide):
            s = slides[sn - 1]
            text = s["text"] if len(s["text"]) <= 900 else s["text"][:900] + "…"
            part = next(f["part"] for f in imgs if f["slide"] == sn)
            body += [f"## スライド {sn}（{part}）", "", f"- タイトル: {s['title']}", f"- 画面の文字: {text}",
                     f"- 確認用の画像: {' ／ '.join(by_slide[sn])}", ""]
        (d / "manifest.md").write_text("\n".join(body) + "\n", encoding="utf-8")
        key[code] = {"run": run, "images": {str(p["n"]): p["id"] for p in placed}}
        print(f"{code} {run}: {len(placed)} error photos on {len(by_slide)} slides")
    RESULTS.mkdir(exist_ok=True)
    key_path(rnd).write_text(json.dumps(dict(sorted(key.items())), indent=1) + "\n")


def groups(rnd: str) -> dict[str, list[str]]:
    """確認者はデッキと同じ人数。記号を無作為に並べ、k番目の確認者に k番目と k+1番目のデッキを渡す（各デッキを2名が見る）。"""
    codes = sorted(json.loads(key_path(rnd).read_text()))
    rng = random.Random(SEED + 1)
    rng.shuffle(codes)
    n = len(codes)
    sets = {f"c{k + 1}": [codes[k], codes[(k + 1) % n]] for k in range(n)}
    for v in sets.values():
        rng.shuffle(v)
    return sets


def prompts(rnd: str) -> None:
    rubric = (HERE / "judge/rubric_content.md").read_text(encoding="utf-8").split("\n", 2)[2].strip()
    OUT = out_dir(rnd)
    (OUT / "out").mkdir(exist_ok=True)
    PROMPTS.mkdir(exist_ok=True)
    for name, codes in groups(rnd).items():
        out = OUT / "out" / f"check-{name}.json"
        text = f"""{rubric}

## 作業の決まり

- 資料のフォルダ: `{OUT}`。見てよいのは、この下の次の記号のフォルダだけです: {"、".join(codes)}。ほかの場所は読まず、検索もしないでください。
- 次の順に進めてください: {" → ".join(codes)}
- 1つのデッキで、まず `manifest.md` を読み、スライドごとに図と元の写真の画像を Read で開きます。小さく写る物を確かめたいときは `truth/<番号>.jpg` を開きます。
- 1つのデッキを終えるたびに、そのデッキの答えを `{out}.notes.jsonl` に1行の JSON で追記してください（{{"記号": 答え}} の形）。追記だけにし、ファイル全体を書き直さないでください。
- 全デッキを終えたら、基準がデッキの間でそろっているかをメモを読み返して確かめ（画像は開き直さない）、全デッキの答えを1つの JSON にして `{out}` に保存してください。
- 最後の返答には、保存したファイルの場所と、デッキごとの wrong と overclaim の件数だけを書いてください（JSON の本文は返答に書かない）。
- これは確認の作業だけです。外部サービスは使わず、送信・コミットもしません。書き込むのは上の2つのファイルだけです。
"""
        path = PROMPTS / f"content-{rnd}-{name}.md"
        path.write_text(text, encoding="utf-8")
        print(f"{name}: {' → '.join(codes)} -> {path}")


def collect(rnd: str) -> None:
    codes = set(json.loads(key_path(rnd).read_text()))
    dest = RESULTS / f"content_{rnd}"
    dest.mkdir(exist_ok=True)
    for f in sorted((out_dir(rnd) / "out").glob("check-*.json")):
        name = f.name.split(".")[0].removeprefix("check-")
        data = json.loads(f.read_text(encoding="utf-8"))
        data = {k: v for k, v in data.items() if k in codes}
        (dest / f"{name}.json").write_text(json.dumps(data, ensure_ascii=False, indent=1) + "\n", encoding="utf-8")
        print(f"{name}: {len(data)} decks")


def table(rnd: str) -> None:
    key = json.loads(key_path(rnd).read_text())
    rows = []
    for f in sorted((RESULTS / f"content_{rnd}").glob("*.json")):
        for code, d in json.loads(f.read_text(encoding="utf-8")).items():
            for it in d.get("images", []):
                n = str(it.get("n"))
                rows.append({"checker": f.stem, "code": code, "kind": "image", "slide": it.get("slide"), "n": n,
                             "id": key[code]["images"].get(n, ""), "verdict": it.get("verdict"),
                             "claim": it.get("claim", ""), "detail": it.get("detail", "")})
            for it in d.get("slide_claims", []):
                rows.append({"checker": f.stem, "code": code, "kind": "slide", "slide": it.get("slide"), "n": "",
                             "id": "", "verdict": it.get("verdict"), "claim": it.get("text", ""),
                             "detail": it.get("detail", "")})
    adj_path = RESULTS / f"content_{rnd}_adjudication.csv"
    adj = {(a["code"], a["kind"], a["slide"], a["n"], a["claim_prefix"]): a
           for a in csv.DictReader(open(adj_path, encoding="utf-8"))} if adj_path.exists() else {}
    for r in rows:
        a = next((v for (c, k, s, n, pre), v in adj.items() if c == r["code"] and k == r["kind"]
                  and s == str(r["slide"]) and n == r["n"] and r["claim"].startswith(pre)), None) \
            if r["verdict"] in ("wrong", "overclaim") else None           # 確かめ直すのは、指摘のあった判定だけ
        r["final"] = a["final"] if a else ("" if r["verdict"] in ("wrong", "overclaim") else r["verdict"])
        r["adjudication"] = a["reason"] if a else ""
    with open(RESULTS / f"content_{rnd}.csv", "w", newline="", encoding="utf-8") as fh:
        w = csv.DictWriter(fh, fieldnames=list(rows[0]))
        w.writeheader()
        w.writerows(rows)
    pending = [r for r in rows if r["verdict"] in ("wrong", "overclaim") and not r["final"]]
    print(f"{len(rows)} rows -> results/content_{rnd}.csv; 確かめる候補（未判定）{len(pending)} 件")
    for code in sorted(key):
        mine = [r for r in rows if r["code"] == code]
        wrong = {(r["kind"], r["slide"], r["n"]) for r in mine if r["final"] == "wrong"}
        over = {(r["kind"], r["slide"], r["n"]) for r in mine if r["final"] == "overclaim"}
        imgs = {r["n"] for r in mine if r["kind"] == "image"}
        none = {r["n"] for r in mine if r["kind"] == "image" and r["verdict"] == "none"}
        print(f"{code} {key[code]['run']:28s} images {len(key[code]['images']):2d}  judged {len(imgs):2d}  "
              f"not described {len(none):2d}  confirmed wrong {len(wrong)}  overclaim {len(over)}")


if __name__ == "__main__":
    a = sys.argv[1:] or ["help"]
    if a[0] == "prepare":
        prepare(a[1], a[2], a[3:])
    elif a[0] in ("prompts", "collect", "table"):
        {"prompts": prompts, "collect": collect, "table": table}[a[0]](a[1])
    else:
        sys.exit(__doc__)
