#!/usr/bin/env python3
"""独立した検証用の課題データ: 鳥6種の分類結果（正解・予測・確信度）と表示用サムネイル。

牧場の動物（主課題）と犬（外れ値のデッキ）とは別の題材で、スキルの改訂（S5）を作るのには使っていない。
作り方は prepare_data.py と同じ（Open Images V7、CLIP ViT-B/32 の zero-shot 分類）で、定数だけを差し替える。
正解ラベルのうち6枚（各種1枚）は、検証のために意図的に別の種へ変える（plant）。どれを変えたかは task3/planted.csv に
残し、デッキを作るモデルには渡さない。

    uv run --no-project --python 3.12 --with torch==2.14.0 --with transformers==5.16.1 --with pillow --with numpy \\
        python experiments/2026-09-30-model-vs-skill/prepare_birds.py select fetch embed classify sheets
    （sheets を目視して task3/exclude.csv を書く）
    uv run … prepare_birds.py export plant
"""
from __future__ import annotations

import csv
import random
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
import prepare_data as pd  # noqa: E402

pd.CLASSES = [("Duck", "カモ"), ("Swan", "ハクチョウ"), ("Chicken", "ニワトリ"),
              ("Eagle", "ワシ"), ("Owl", "フクロウ"), ("Parrot", "オウム")]
pd.SEED = "model-vs-skill-birds-2026-09-30"
pd.CACHE = HERE / "_cache_birds"
pd.IMG = pd.CACHE / "img"
pd.DATA = HERE / "task3/data"
pd.OTHER_PROMPTS = ["a photo of an animal", "a photo of birds", "a photo of an object", "a photo of scenery"]
EXCLUDE = HERE / "task3/exclude.csv"
PLANTED = HERE / "task3/planted.csv"
FIELDS = ["id", "true", "true_ja", "pred", "pred_ja", "prob", "second", "second_ja", "margin"]


def load_exclude() -> dict[str, str]:
    return {r["id"]: r["reason"] for r in csv.DictReader(open(EXCLUDE, encoding="utf-8"))} if EXCLUDE.exists() else {}


pd.load_exclude = load_exclude


def plant() -> None:
    """各種1枚、正しく高い確信度（0.9以上）で判定された写真の正解ラベルを、2番目の候補の種に変える。"""
    path = pd.DATA / "predictions.csv"
    rows = list(csv.DictReader(open(path, encoding="utf-8")))
    if PLANTED.exists():
        sys.exit(f"既にある（二重に変えない）: {PLANTED}")
    rng = random.Random(pd.SEED + ":plant")
    planted = []
    for en, ja in pd.CLASSES:
        pool = sorted((r for r in rows if r["true"] == en and r["pred"] == en and float(r["prob"]) >= 0.9),
                      key=lambda r: r["id"])
        r = rng.choice(pool)
        planted.append({"id": r["id"], "content": en, "content_ja": ja, "planted": r["second"],
                        "planted_ja": r["second_ja"], "prob": r["prob"]})
        r["true"], r["true_ja"] = r["second"], r["second_ja"]
    with open(path, "w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=FIELDS)
        w.writeheader()
        w.writerows(rows)
    with open(PLANTED, "w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=list(planted[0]))
        w.writeheader()
        w.writerows(planted)
    wrong = sum(r["true"] != r["pred"] for r in rows)
    print(f"planted {len(planted)}; errors in the data now {wrong} / {len(rows)}")


STAGES = pd.STAGES | {"plant": plant}

if __name__ == "__main__":
    for a in sys.argv[1:]:
        name, _, opt = a.partition("=")
        print(f"== {name}")
        STAGES[name](opt) if opt else STAGES[name]()
