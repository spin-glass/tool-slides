#!/usr/bin/env python3
"""最終確認の課題（task5、牧場の6種）: prepare_hard.py と同じ作り方で、牧場の動物の写真から作る。

同じ草地の背景で見分けにくく、目立たない対象を取り違えやすい。主課題（task/）で使った写真・候補は選ばない。
「別の物が主役」には、同じ動物に付く上位の分類（Animal・Mammal など）の枠を数えない。

    uv run --no-project --python 3.12 --with torch==2.14.0 --with transformers==5.16.1 --with pillow --with numpy \\
        python experiments/2026-09-30-model-vs-skill/prepare_hard_farm.py select fetch embed classify sheets
    （sheets を目視して task5/exclude.csv を書く）
    uv run … prepare_hard_farm.py export gt
"""
from __future__ import annotations

import csv
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
import prepare_hard as ph  # noqa: E402

pd = ph.pd
pd.CLASSES = [("Cattle", "牛"), ("Horse", "馬"), ("Sheep", "羊"), ("Goat", "ヤギ"), ("Deer", "鹿"), ("Pig", "ブタ")]
pd.SEED = "model-vs-skill-farm-hidden-2026-09-30"
pd.CACHE = HERE / "_cache_hard_farm"
pd.IMG = pd.CACHE / "img"
pd.DATA = HERE / "task5/data"
pd.OTHER_PROMPTS = ["a photo of an animal", "a photo of animals on a farm", "a photo of an object", "a photo of scenery"]
ph.TASK = HERE / "task5"
ph.EXCLUDE = ph.TASK / "exclude.csv"
ph.SUPER = {"Animal", "Mammal", "Carnivore", "Bird"}
ph.USED = {r["id"] for r in csv.DictReader(open(HERE / "_cache/candidates.csv"))} | \
    {r["id"] for r in csv.DictReader(open(HERE / "task/data/predictions.csv"))}

if __name__ == "__main__":
    for a in sys.argv[1:]:
        print(f"== {a}")
        ph.STAGES[a]()
