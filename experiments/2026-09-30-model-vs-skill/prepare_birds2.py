#!/usr/bin/env python3
"""独立した検証の追加（birds2）: 1回目（birds）で見つかった欠陥を直した課題データ。

1回目のデータでは、ラベルを変えた6枚の元の種が、出典の表（credits.csv の label 列）に残っていた。
6枚とも写真の題名に種の名前もあった（「Owl」「Parrot」など）。規則を足す前の版（S4）も、6枚すべてを見抜いた。
ここでは次のように直す。
  - credits.csv から label 列を除く（作者・題名・出典・ライセンスだけにする）
  - 1回目に変えた6枚は、元のラベルに戻す
  - ラベルを変える6枚（各種1枚）は、題名がカメラのファイル名か「Untitled」の写真（題名から種が分からない）で、
    モデルが正しく高い確信度（0.9以上）で当てたものから選び直す。変えた先は、1回目と同じく2番目の候補の種
画像は task3/data/thumbs をそのまま使う（写さない。run.py が作業場所に写す）。

    python prepare_birds2.py draw     # 種ごとの候補を、選ぶ順に並べて表示する（写真を目で確かめるため）
    python prepare_birds2.py write    # task3b/data と task3b/planted.csv を書く（task3b/rejected.csv の写真は飛ばす）
"""
from __future__ import annotations

import csv
import json
import random
import re
import shutil
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
SRC = HERE / "task3/data"
OUT = HERE / "task3b"
SEED = "model-vs-skill-birds2-2026-09-30"
CLASSES = ["Duck", "Swan", "Chicken", "Eagle", "Owl", "Parrot"]
# 題名から種が分からないもの: カメラのファイル名・番号だけ・Untitled
GENERIC = re.compile(r"^(img|dsc|dscn|_mg|_dsc|_brk|cimg|p\d|wp_|xoka|copia)|^[\d\s._()-]+(\.jpg)?$|^untitled$", re.I)
FIELDS = ["id", "true", "true_ja", "pred", "pred_ja", "prob", "second", "second_ja", "margin"]


def original_rows() -> list[dict]:
    """1回目に変えた6枚を、元のラベルに戻した表。"""
    rows = list(csv.DictReader(open(SRC / "predictions.csv", encoding="utf-8")))
    planted = {r["id"]: r for r in csv.DictReader(open(HERE / "task3/planted.csv", encoding="utf-8"))}
    for r in rows:
        if r["id"] in planted:
            r["true"], r["true_ja"] = planted[r["id"]]["content"], planted[r["id"]]["content_ja"]
    return rows


def candidates(rows: list[dict]) -> dict[str, list[dict]]:
    credits = {r["id"]: r for r in csv.DictReader(open(SRC / "credits.csv", encoding="utf-8"))}
    first = {r["id"] for r in csv.DictReader(open(HERE / "task3/planted.csv", encoding="utf-8"))}
    rng = random.Random(SEED)
    out = {}
    for cls in CLASSES:
        pool = sorted((r | {"title": credits[r["id"]]["title"]} for r in rows
                       if r["true"] == cls and r["pred"] == cls and float(r["prob"]) >= 0.9 and r["id"] not in first
                       and GENERIC.search(credits[r["id"]]["title"].strip())), key=lambda r: r["id"])
        rng.shuffle(pool)
        out[cls] = pool
    return out


def rejected() -> dict[str, str]:
    path = OUT / "rejected.csv"
    return {r["id"]: r["reason"] for r in csv.DictReader(open(path, encoding="utf-8"))} if path.exists() else {}


def draw() -> None:
    skip = rejected()
    for cls, pool in candidates(original_rows()).items():
        print(f"== {cls}（候補 {len(pool)}）")
        for r in pool[:4]:
            mark = f"  ×（{skip[r['id']]}）" if r["id"] in skip else ""
            print(f"   {r['id']} {float(r['prob']):.4f} → {r['second_ja']} | {r['title']}{mark}")


def write() -> None:
    if (OUT / "planted.csv").exists():
        sys.exit(f"既にある（二重に変えない）: {OUT / 'planted.csv'}")
    rows, skip = original_rows(), rejected()
    planted = []
    for cls, pool in candidates(rows).items():
        r = next(r for r in pool if r["id"] not in skip)
        planted.append({"id": r["id"], "content": cls, "content_ja": r["true_ja"], "planted": r["second"],
                        "planted_ja": r["second_ja"], "prob": r["prob"], "title": r["title"]})
    by_id = {p["id"]: p for p in planted}
    for r in rows:
        if r["id"] in by_id:
            r["true"], r["true_ja"] = by_id[r["id"]]["planted"], by_id[r["id"]]["planted_ja"]
    data = OUT / "data"
    data.mkdir(parents=True, exist_ok=True)
    with open(data / "predictions.csv", "w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=FIELDS)
        w.writeheader()
        w.writerows({k: r[k] for k in FIELDS} for r in rows)
    credits = list(csv.DictReader(open(SRC / "credits.csv", encoding="utf-8")))
    keep = [k for k in credits[0] if k != "label"]
    with open(data / "credits.csv", "w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=keep)
        w.writeheader()
        w.writerows({k: r[k] for k in keep} for r in credits)
    for name in ("README.md", "meta.json"):
        shutil.copy(SRC / name, data / name)
    with open(OUT / "planted.csv", "w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=list(planted[0]))
        w.writeheader()
        w.writerows(planted)
    wrong = sum(r["true"] != r["pred"] for r in rows)
    print(json.dumps(planted, ensure_ascii=False, indent=1))
    print(f"errors in the data: {wrong} / {len(rows)}")


if __name__ == "__main__":
    {"draw": draw, "write": write}.get((sys.argv[1:] or ["help"])[0], lambda: sys.exit(__doc__))()
