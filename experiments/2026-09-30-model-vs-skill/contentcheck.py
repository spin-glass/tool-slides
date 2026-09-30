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
載った写真は、デッキを描き直して取る imgfig の図の記録（図ごとに描いた写真の ID。環境変数 IMGFIG_REPORT）で決める。
図の記録と図のファイルの対応、#番号の位置は、照合（写真の中央60%、色つきの正規化相互相関、縮尺 0.2〜4.0）で決める。
記録の無い図（imgfig 以外で描いた図）は、birdcheck.py と同じ照合（縮尺 0.2〜1.6、0.9 以上）で決める。
D までは照合だけで決めていたため、大きく載せた写真（2枚だけの図・拡大の図）と、小さく載せて値が 0.9 に届かない写真が漏れた。
D の漏れは、前の回で渡した分を除いた追加の回（D2、`prepare D2 water … --skip D`）で確認者に渡した。

    python contentcheck.py coverage D D2                  # 渡した資料が、デッキの図の記録にある誤りの写真をすべて含むか
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
        s["part"] = "付録" if n > n_main or "appendix" in s["cls"] else "本編"
        if n == 0 or "quarto-title-block" in s["cls"]:
            s["part"] = ""
            continue
        part = s["part"]
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


def match_job(job: tuple) -> dict[str, tuple]:
    """1つの図の中で、渡した写真それぞれが最もよく合う位置を探す（並列の1単位）。
    {ID: (照合の値, 枠, 縮尺1.6までの照合の値, その枠)}。広い縮尺は図の記録にある写真の位置と対応づけに、
    狭い縮尺（A〜D と同じ）は記録の無い図で「載った」を決めるのに使う（広い縮尺は棒グラフでも値が上がるため）。"""
    import cv2
    import numpy as np

    import birdcheck as bc

    task, path, ids = job
    bc.THUMBS = HERE / TASKS[task][0] / "data/thumbs"
    for i in ids:
        if i not in _TMPLS:
            _TMPLS[i] = bc.template(i)
    img = cv2.imread(str(path), cv2.IMREAD_COLOR)
    s = min(1.0, bc.MAX_SIDE / max(img.shape[:2]))
    small_img = cv2.resize(img, None, fx=s, fy=s, interpolation=cv2.INTER_AREA) if s < 1 else img

    def best(scales):
        bc.SCALES = scales
        v, (x, y, w, h) = bc.match(small_img, _TMPLS[i])
        return v, (int(x / s), int(y / s), int(w / s), int(h / s))

    out = {}
    for i in ids:
        narrow = best(np.geomspace(0.2, 1.6, 36))
        wide = best(np.geomspace(1.6, 4.0, 14))       # 大きく載せた写真（2枚だけの図・拡大の図）。D までは探していなかった
        out[i] = (*max(narrow, wide, key=lambda t: t[0]), *narrow)
    return out


def drawn(run: str, task: str) -> list[list[str]]:
    """デッキを描き直し、imgfig が図ごとに記録した写真の ID を、描いた順に返す（環境変数 IMGFIG_REPORT）。"""
    import score

    report = EVAL.parent / f"drawn-{run}.jsonl"
    html = WORK / "runs" / run / "ws/_output" / TASKS[task][2] / "index.html"
    if report.exists() and html.exists() and report.stat().st_mtime < html.stat().st_mtime:
        return [[c["id"] for c in json.loads(line).get("captions", []) if c.get("id")]
                for line in open(report, encoding="utf-8")]      # 記録を取ったときの描画がそのまま残っている
    report.unlink(missing_ok=True)
    os.environ["IMGFIG_REPORT"] = str(report)
    try:
        ok, err = score.render(WORK / "runs" / run / "ws", TASKS[task][2])
    finally:
        os.environ.pop("IMGFIG_REPORT", None)
    if not ok:
        sys.exit(f"描き直せない: {run}\n{err}")
    if not report.exists():
        return []
    return [[c["id"] for c in json.loads(line).get("captions", []) if c.get("id")]
            for line in open(report, encoding="utf-8")]


HIT = 0.9       # 図の記録が無い図で「載った」とする照合の値（birdcheck と同じ）


def align(imgs: list[dict], lines: list[list[str]], scores: dict[int, dict]) -> dict[int, list[str]]:
    """図の記録（描いた順）を、図のファイル（スライドの順）に対応づける。{ファイルの番号: 記録の ID}。
    順を保ったまま、記録の写真の照合の値（下側の中央値）の合計が最大になる対応を選ぶ（動的計画法）。
    写真の図の正しい対応は 0.9 前後（拡大の図は 0.75〜0.8）、違う図との値は 0.5〜0.8（D で実測）で、しきい値1つでは分けられない。"""
    ks = [k for k, f in enumerate(imgs) if not f["id"] and k in scores]
    js = [j for j, ln in enumerate(lines) if ln]

    def val(k: int, j: int) -> float:
        v = sorted(scores[k][i][0] for i in lines[j] if i in scores[k])
        return v[(len(v) - 1) // 2] if v else 0.0

    n, m = len(js), len(ks)
    if n > m:
        print(f"   図の記録 {n} が図のファイル {m} より多い。記録は使わない（目で確かめる）")
        return {}
    NEG = float("-inf")
    f = [[NEG] * (m + 1) for _ in range(n + 1)]       # f[a][b]: 記録 a 個をファイル b 個までに当てたときの最大
    f[0] = [0.0] * (m + 1)
    for a in range(1, n + 1):
        for b in range(a, m + 1):
            f[a][b] = max(f[a][b - 1], f[a - 1][b - 1] + val(ks[b - 1], js[a - 1]))
    out, a, b = {}, n, m
    while a > 0:
        if b > a and f[a][b] == f[a][b - 1]:
            b -= 1
            continue
        out[ks[b - 1]] = lines[js[a - 1]]
        a, b = a - 1, b - 1
    return out


def checked(rnd: str) -> dict[str, set[tuple[int, int, str]]]:
    """その回で確認者に渡した (スライド, 図の番号, 写真の ID)。実行名ごと。manifest の「slide-NN-fig-K.jpg（スライドの図。#1, #2）」から読む。"""
    key = json.loads(key_path(rnd).read_text())
    out: dict[str, set[tuple[int, int, str]]] = {}
    for code, v in key.items():
        text = (out_dir(rnd) / code / "manifest.md").read_text(encoding="utf-8")
        for sn, fig, nums in re.findall(r"`slide-(\d+)-fig-(\d+)\.jpg`（スライドの図。([^）]*)）", text):
            out.setdefault(v["run"], set()).update((int(sn), int(fig), v["images"][n]) for n in re.findall(r"#(\d+)", nums))
    return out


def coverage(rnds: list[str]) -> None:
    """渡した回の資料が、デッキに載った誤りの写真をすべて含むかを、デッキの図の記録（imgfig の IMGFIG_REPORT）と照らす。
    デッキを描き直して記録を取り、記録の図ごとに、その図の誤りの写真すべてを含む図が資料にあるかを見る。"""
    runs: dict[str, set[tuple[int, int, str]]] = {}
    for rnd in rnds:
        for run, s in checked(rnd).items():
            runs.setdefault(run, set()).update(s)
    for run in sorted(runs):
        task = next(t for t in TASKS if run.startswith(t + "-"))
        errs = errors(task)
        lines = drawn(run, task)
        figs: dict[int, set[str]] = {}
        for _, fig, i in runs[run]:
            figs.setdefault(fig, set()).add(i)
        missing = []
        for k, ln in enumerate(lines):
            want = {i for i in ln if i in errs}
            if want and not any(want <= got for got in figs.values()):
                best = max(figs.values(), key=lambda got: len(want & got), default=set())
                missing.append((k + 1, sorted(want - best)))
        print(f"{run}: 図の記録 {len(lines)}、記録にある誤りの写真 {len({i for ln in lines for i in ln if i in errs})} 枚、"
              f"資料に入れた（スライド・図・写真）{len(runs[run])}、渡っていない記録の図 {len(missing)}")
        for k, ids in missing:
            print(f"   記録の図 {k}: 資料に無い {ids}")


def prepare(rnd: str, task: str, runs: list[str], skip: str | None = None) -> None:
    """skip に前の回を渡すと、その回で渡した (スライド, 写真) を除いて、照合で新しく見つかった分だけを資料にする。"""
    from concurrent.futures import ProcessPoolExecutor

    from PIL import Image, ImageDraw, ImageFont

    base, cache, deck = TASKS[task]
    done = checked(skip) if skip else {}
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
    lines = {run: drawn(run, task) for run in runs}      # 先に描き直して図の記録を取る（図のファイルも描き直される）
    decks = {run: slide_images(run, deck) for run in runs}
    jobs = [(run, k, f["path"]) for run, (imgs, _) in decks.items() for k, f in enumerate(imgs)
            if not f["id"]]          # 図はすべて照らす（D までは写真らしい図だけで、拡大の図が漏れた）
    want = {run: sorted(set(errs) | {i for ln in lines[run] for i in ln}) for run in runs}
    with ProcessPoolExecutor(max_workers=8) as pool:
        found = list(pool.map(match_job, [(task, path, want[run]) for run, _, path in jobs]))
    scores: dict[str, dict[int, dict]] = {}
    for (run, k, _), sc in zip(jobs, found):
        scores.setdefault(run, {})[k] = sc
    key = {}
    for run, code in zip(sorted(runs), codes):
        d = OUT / code
        (d / "truth").mkdir(parents=True)
        imgs, slides = decks[run]
        num = 0
        body = [f"# デッキ {code}", ""]
        by_slide: dict[int, list[str]] = {}
        placed = []
        rec = align(imgs, lines[run], scores.get(run, {}))
        if len(rec) < sum(1 for ln in lines[run] if ln):
            print(f"   {run}: 図の記録 {sum(1 for ln in lines[run] if ln)} のうち {len(rec)} だけが図のファイルに対応した。目で確かめる")
        for k, f in enumerate(imgs):
            if f["id"]:                     # HTML の写真（ファイル名で分かる）
                if f["id"] in errs and (f["slide"], k + 1, f["id"]) not in done.get(run, set()):
                    placed.append({**f, "fig": k, "box": None, "id": f["id"], "score": 1.0})
                continue
            sc = scores[run][k]
            if k in rec:                    # 図の記録（imgfig）がある図: 記録にある誤りの写真すべて。位置は照合で
                ids = [(i, *sc[i][:2]) for i in dict.fromkeys(rec[k]) if i in errs]
            else:                           # 記録の無い図（imgfig 以外で描いた図）: A〜D と同じ照合で 0.9 以上
                ids = [(i, *sc[i][2:]) for i in errs if sc[i][2] >= HIT]
            for i, v, box in ids:
                if (f["slide"], k + 1, i) in done.get(run, set()):
                    continue
                if v < 0.75:
                    print(f"   {run} スライド {f['slide']} 図 {k + 1}: {i} は記録にあるが照合の値 {v:.2f}。#番号の位置を目で確かめる")
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
        for sn, s in enumerate(slides, start=1):
            text = s["text"] if len(s["text"]) <= 900 else s["text"][:900] + "…"
            if sn in by_slide:
                body += [f"## スライド {sn}（{s['part']}）", "", f"- タイトル: {s['title']}", f"- 画面の文字: {text}",
                         f"- 確認用の画像: {' ／ '.join(by_slide[sn])}", ""]
            elif s["part"] and (s["title"] or text).strip() and not skip:
                # 誤りの写真が無いスライドも、箇条書きなどで写真の中身に触れることがある（D まではここを渡していなかった）
                body += [f"## スライド {sn}（{s['part']}・誤りの写真なし）", "", f"- タイトル: {s['title']}",
                         f"- 画面の文字: {text}", ""]
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
            if r["verdict"] in ("wrong", "overclaim", "unknown") else None  # 確かめ直すのは、指摘と「確かめられない」の判定だけ
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
        skip = a[a.index("--skip") + 1] if "--skip" in a else None
        prepare(a[1], a[2], [r for r in a[3:] if r not in ("--skip", skip)], skip)
    elif a[0] == "coverage":
        coverage(a[1:])
    elif a[0] in ("prompts", "collect", "table"):
        {"prompts": prompts, "collect": collect, "table": table}[a[0]](a[1])
    else:
        sys.exit(__doc__)
