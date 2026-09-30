#!/usr/bin/env python3
"""画像の難しい課題（task4、水辺の6種）: 写真の中で対象が目立たない写真を多く含む分類結果と、採点用の正解の枠。

これまでの課題では、スキルの規則が防ぎたい見落とし（写真の一部に小さく写る被写体を「写っていない」と書く、
ラベルの誤りと決めつける）が起きる写真がほとんど無く、差が出なかった。ここでは Open Images V7 の人手の枠
（bounding box）を使い、種ごとに次の「難しい写真」を最大 HARD_PER_CLASS 枚入れる。
  small     その種の枠が画面の5%未満（小さく写る）
  dominant  6種以外の物の枠が、その種の枠の3倍以上かつ画面の20%以上（別の物が主役）
  multi     6種のうち別の種も、重ならない別の枠で写る（2種が同時に写る）
残りは難しくない写真で埋める。作り方は prepare_data.py と同じ（CLIP ViT-B/32 の zero-shot 分類）。

デッキを作るモデルに渡すもの（task4/data/）: predictions.csv、thumbs/（長辺256px）、images/（長辺1024px）、
credits.csv（題名・作者・出典・ライセンス。正解の列は無い）、meta.json、README.md。
採点だけに使うもの（渡さない）: task4/gt.csv（難しさの型・各種の枠）と、枠を描いた画像（_cache_hard/gt/）。

    uv run --no-project --python 3.12 --with torch==2.14.0 --with transformers==5.16.1 --with pillow --with numpy \\
        python experiments/2026-09-30-model-vs-skill/prepare_hard.py select fetch embed classify sheets
    （sheets を目視して task4/exclude.csv を書く）
    uv run … prepare_hard.py export gt
"""
from __future__ import annotations

import csv
import json
import shutil
import sys
from collections import defaultdict
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
import prepare_data as pd  # noqa: E402

pd.CLASSES = [("Duck", "カモ"), ("Goose", "ガン"), ("Swan", "ハクチョウ"), ("Boat", "ボート"),
              ("Lighthouse", "灯台"), ("Harbor seal", "アザラシ")]
pd.SEED = "model-vs-skill-hard-2026-09-30"
pd.CACHE = HERE / "_cache_hard"
pd.IMG = pd.CACHE / "img"
pd.DATA = HERE / "task4/data"
pd.LONG_SIDE = 1024
pd.N_SUPPORT = 0
pd.OTHER_PROMPTS = ["a photo of an animal", "a photo of a bird", "a photo of the sea", "a photo of an object",
                    "a photo of scenery"]
TASK = HERE / "task4"
EXCLUDE = TASK / "exclude.csv"
HARD_PER_CLASS = 16
N_CAND = 54                       # クラスあたりの候補（人物の自動判定・目視の除外で減っても40枚残るように）
SMALL, DOMINANT, DOMINANT_RATIO, IOU_DISTINCT = 0.05, 0.20, 3.0, 0.3
PRIVACY = ["Person", "Human face", "Man", "Woman", "Girl", "Boy", "Human body", "Human head", "Child",
           "Vehicle registration plate"]
BOX_FILES = {"val": "validation-bbox.csv", "test": "test-bbox.csv"}
SUPER: set[str] = set()           # 「別の物が主役」から外す上位の分類（同じ動物に付く Animal など）。水辺の課題では空
USED: set[str] = set()            # 選ばない写真（ほかの課題で使ったもの）
FIELDS = ["id", "true", "true_ja", "pred", "pred_ja", "prob", "second", "second_ja", "margin"]


def load_exclude() -> dict[str, str]:
    return {r["id"]: r["reason"] for r in csv.DictReader(open(EXCLUDE, encoding="utf-8"))} if EXCLUDE.exists() else {}


pd.load_exclude = load_exclude


def iou(a: tuple, b: tuple) -> float:
    x0, x1 = max(a[0], b[0]), min(a[1], b[1])
    y0, y1 = max(a[2], b[2]), min(a[3], b[3])
    inter = max(0.0, x1 - x0) * max(0.0, y1 - y0)
    union = (a[1] - a[0]) * (a[3] - a[2]) + (b[1] - b[0]) * (b[3] - b[2]) - inter
    return inter / union if union > 0 else 0.0


def area(b: tuple) -> float:
    return (b[1] - b[0]) * (b[3] - b[2])


def read_boxes(ids: set[str], names: dict[str, str]) -> tuple[dict, set]:
    """画像ID → 表示名 → 枠 (XMin, XMax, YMin, YMax) のリスト。人物・ナンバーの枠がある画像の集合も返す。"""
    boxes: dict[str, dict[str, list]] = defaultdict(lambda: defaultdict(list))
    private = set()
    for sp, f in BOX_FILES.items():
        for r in csv.DictReader(open(pd.META / f)):
            if r["ImageID"] not in ids:
                continue
            n = names.get(r["LabelName"], r["LabelName"])
            if n in PRIVACY:
                private.add(r["ImageID"])
                continue
            boxes[r["ImageID"]][n].append((float(r["XMin"]), float(r["XMax"]), float(r["YMin"]), float(r["YMax"])))
    return boxes, private


def hard_types(i: str, cls: str, boxes: dict) -> list[str]:
    own = boxes[i].get(cls, [])
    if not own:
        return []
    big = max(area(b) for b in own)
    targets = {en for en, _ in pd.CLASSES}
    types = []
    if big < SMALL:
        types.append("small")
    other = max((area(b) for n, bs in boxes[i].items() if n not in targets and n not in SUPER for b in bs),
                default=0.0)
    if other >= DOMINANT and other >= DOMINANT_RATIO * big:
        types.append("dominant")
    for n, bs in boxes[i].items():
        if n in targets and n != cls and any(all(iou(b, o) < IOU_DISTINCT for o in own) for b in bs):
            types.append("multi")
            break
    return types


def select() -> None:
    names = {r["LabelName"]: r["DisplayName"] for r in csv.DictReader(open(pd.META / "classes.csv"))}
    mid_of: dict[str, str] = {}
    for m, n in names.items():
        mid_of.setdefault(n, m)
    wanted = {mid_of[en]: en for en, _ in pd.CLASSES}
    privacy_mids = {mid_of[n] for n in PRIVACY if n in mid_of}
    pos: dict[str, set[str]] = {en: set() for en, _ in pd.CLASSES}
    private: set[str] = set()
    split_of: dict[str, str] = {}
    for sp in pd.SPLITS:
        for r in csv.DictReader(open(pd.META / f"{sp}-labels.csv")):
            if r["Confidence"] != "1":
                continue
            if r["LabelName"] in wanted:
                pos[wanted[r["LabelName"]]].add(r["ImageID"])
                split_of[r["ImageID"]] = sp
            elif r["LabelName"] in privacy_mids:
                private.add(r["ImageID"])
    allpos = set().union(*pos.values())
    boxes, private_boxes = read_boxes(allpos, names)
    private |= private_boxes
    rows, assigned, gt = [], set(USED), {}
    for en, ja in pd.CLASSES:
        cands = sorted((i for i in pos[en] - private - assigned if boxes[i].get(en)), key=pd.order_key)
        typed = [(i, hard_types(i, en, boxes)) for i in cands]
        first = [i for i, t in typed if "small" in t or "dominant" in t]        # 小さい・別の物が主役を先に
        second = [i for i, t in typed if t and i not in first]
        hard = (first + second)[:HARD_PER_CLASS]
        normal = [i for i, t in typed if not t][:N_CAND - len(hard)]
        for i in hard + normal:
            assigned.add(i)
            rows.append({"id": i, "true": en, "true_ja": ja})
            gt[i] = {"class": en, "types": hard_types(i, en, boxes), "boxes": {n: bs for n, bs in boxes[i].items()}}
        print(f"{en:12s} candidates {len(cands):4d}  hard {len(hard):2d}  normal {len(normal):2d}")
    meta = {}
    for sp in pd.SPLITS:
        for r in csv.DictReader(open(pd.META / f"{sp}-images.csv")):
            if r["ImageID"] in assigned:
                meta[r["ImageID"]] = r
    for row in rows:
        m = meta[row["id"]]
        row |= {"split": pd.SPLITS[split_of[row["id"]]], "rotation": m["Rotation"], "license": m["License"],
                "author": m["Author"], "title": m["Title"], "landing_url": m["OriginalLandingURL"]}
    pd.CACHE.mkdir(parents=True, exist_ok=True)
    with open(pd.CACHE / "candidates.csv", "w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=list(rows[0]))
        w.writeheader()
        w.writerows(rows)
    (pd.CACHE / "gt_candidates.json").write_text(json.dumps(gt))


def export() -> None:
    """モデルに渡すデータ（task4/data/）。正解の列は出典の表に入れない。"""
    from PIL import Image

    z, idx, ev, sup = pd.splits()
    pred, p = pd.predict(z, idx, ev, sup, "zeroshot")
    data = pd.DATA
    for sub in ("thumbs", "images"):
        shutil.rmtree(data / sub, ignore_errors=True)
        (data / sub).mkdir(parents=True)
    rows = []
    for r, k, pr in zip(ev, pred, p):
        order = pr.argsort()[::-1]
        rows.append({"id": r["id"], "true": r["true"], "true_ja": r["true_ja"], "pred": pd.CLASSES[k][0],
                     "pred_ja": pd.CLASSES[k][1], "prob": f"{pr[order[0]]:.4f}", "second": pd.CLASSES[order[1]][0],
                     "second_ja": pd.CLASSES[order[1]][1], "margin": f"{pr[order[0]] - pr[order[1]]:.4f}"})
        shutil.copy(pd.IMG / f"{r['id']}.jpg", data / "images" / f"{r['id']}.jpg")
        im = Image.open(pd.IMG / f"{r['id']}.jpg")
        im.thumbnail((pd.THUMB_SIDE, pd.THUMB_SIDE))
        im.save(data / "thumbs" / f"{r['id']}.jpg", "JPEG", quality=85)
    with open(data / "predictions.csv", "w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=FIELDS)
        w.writeheader()
        w.writerows(rows)
    with open(data / "credits.csv", "w", newline="", encoding="utf-8") as f:
        w = csv.writer(f)
        w.writerow(["id", "title", "author", "source", "license"])
        w.writerows([r["id"], r["title"], r["author"], r["landing_url"], r["license"]] for r in ev)
    meta = {"dataset": "Open Images V7 (validation / test)", "encoder": "openai/clip-vit-base-patch32",
            "method": "zeroshot", "classes": dict(pd.CLASSES), "n_eval": len(ev),
            "n_excluded_by_eye": len(load_exclude())}
    (data / "meta.json").write_text(json.dumps(meta, ensure_ascii=False, indent=2) + "\n")
    wrong = sum(r["true"] != r["pred"] for r in rows)
    print(f"exported {len(rows)} rows; errors {wrong}")


def gt() -> None:
    """採点用の正解: task4/gt.csv（評価用の240枚。難しさの型・その種の枠の最大面積・写っている6種・主役の物）と、
    枠を描いた画像（_cache_hard/gt/<id>.jpg。6種の枠は太線と名前、6種以外で最も大きい物は細線）。"""
    from PIL import Image, ImageDraw, ImageFont

    cand = json.loads((pd.CACHE / "gt_candidates.json").read_text())
    rows = list(csv.DictReader(open(pd.DATA / "predictions.csv", encoding="utf-8")))
    ja = dict(pd.CLASSES)
    targets = set(ja)
    out_dir = pd.CACHE / "gt"
    out_dir.mkdir(exist_ok=True)
    font = ImageFont.truetype("/System/Library/Fonts/ヒラギノ角ゴシック W3.ttc", 22)
    out = []
    for r in rows:
        g = cand[r["id"]]
        bx = {n: [tuple(b) for b in bs] for n, bs in g["boxes"].items()}
        present = sorted(n for n in bx if n in targets)
        others = sorted(((max(area(b) for b in bs), n) for n, bs in bx.items() if n not in targets and n not in SUPER),
                        reverse=True)
        out.append({"id": r["id"], "true": r["true"], "pred": r["pred"], "error": r["true"] != r["pred"],
                    "types": "|".join(g["types"]), "class_area": round(max(area(b) for b in bx[r["true"]]), 4),
                    "present": "|".join(present), "pred_present": r["pred"] in present,
                    "dominant_other": f"{others[0][1]}:{others[0][0]:.2f}" if others else ""})
        im = Image.open(pd.IMG / f"{r['id']}.jpg").convert("RGB")
        d = ImageDraw.Draw(im)
        W, H = im.size
        order = sorted(bx, key=lambda n: n == r["true"])          # データのラベルの種（赤）を最後に描いて上に出す
        for n in order:
            bs = bx[n]
            if n not in targets and (not others or n != others[0][1]):
                continue
            color, width = ("#ff2020", 5) if n == r["true"] else ("#1e90ff", 5) if n in targets else ("#ffd000", 2)
            for b in bs:
                box = (b[0] * W, b[2] * H, b[1] * W, b[3] * H)
                d.rectangle(box, outline=color, width=width)
                d.text((box[0] + 4, box[1] + 2), ja.get(n, n), fill=color, font=font, stroke_width=2, stroke_fill="black")
        im.save(out_dir / f"{r['id']}.jpg", "JPEG", quality=88)
    with open(TASK / "gt.csv", "w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=list(out[0]))
        w.writeheader()
        w.writerows(out)
    err = [o for o in out if o["error"]]
    print(f"gt {len(out)} rows; errors {len(err)}; hard errors {sum(bool(o['types']) for o in err)} "
          f"(small {sum('small' in o['types'] for o in err)}, dominant {sum('dominant' in o['types'] for o in err)}, "
          f"multi {sum('multi' in o['types'] for o in err)}); errors whose predicted class is also boxed "
          f"{sum(o['pred_present'] for o in err)}")


STAGES = pd.STAGES | {"select": select, "export": export, "gt": gt}

if __name__ == "__main__":
    for a in sys.argv[1:]:
        print(f"== {a}")
        STAGES[a]()
