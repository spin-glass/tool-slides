#!/usr/bin/env python3
"""新しい最終確認の課題（task6、果物と野菜の6種）: prepare_hard.py と同じ作り方で、果物の写真から作る。

牧場の課題（task5）の最終確認で S12 が失敗し、その結果を見てスキルを直した（S13）ので、牧場は開発用に回した。
この課題は、S13 以降の版で開発用の課題（水辺・牧場）の基準を満たすまで実行しない。動物と別の分野にして、盛り合わせで
複数の種類が一緒に写る写真・小さく写る写真・見た目の近い種類（リンゴ・モモ・トマト）を多く含める。
「別の物が主役」には、同じ果物に付く上位の分類（Fruit・Food など）の枠を数えない。

    uv run --no-project --python 3.12 --with torch==2.14.0 --with transformers==5.16.1 --with pillow --with numpy \\
        python experiments/2026-09-30-model-vs-skill/prepare_hard_fruit.py select fetch embed classify sheets
    （sheets を目視して task6/exclude.csv を書く）
    uv run … prepare_hard_fruit.py export gt
"""
from __future__ import annotations

import csv
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
import prepare_hard as ph  # noqa: E402

pd = ph.pd
pd.CLASSES = [("Apple", "リンゴ"), ("Banana", "バナナ"), ("Grape", "ブドウ"), ("Strawberry", "イチゴ"),
              ("Peach", "モモ"), ("Tomato", "トマト")]
pd.SEED = "model-vs-skill-fruit-hidden-2026-10-01"
pd.CACHE = HERE / "_cache_hard_fruit"
pd.IMG = pd.CACHE / "img"
pd.DATA = HERE / "task6/data"
pd.OTHER_PROMPTS = ["a photo of food", "a photo of a market", "a photo of an object", "a photo of scenery"]
ph.TASK = HERE / "task6"
ph.EXCLUDE = ph.TASK / "exclude.csv"
ph.SUPER = {"Fruit", "Food", "Vegetable", "Plant", "Berry", "Produce", "Citrus"}
ph.USED = {r["id"] for r in csv.DictReader(open(HERE / "_cache/candidates.csv"))} | \
    {r["id"] for r in csv.DictReader(open(HERE / "task/data/predictions.csv"))} | \
    {r["id"] for r in csv.DictReader(open(HERE / "task4/data/predictions.csv"))} | \
    {r["id"] for r in csv.DictReader(open(HERE / "task5/data/predictions.csv"))}

if __name__ == "__main__":
    for a in sys.argv[1:]:
        print(f"== {a}")
        ph.STAGES[a]()
