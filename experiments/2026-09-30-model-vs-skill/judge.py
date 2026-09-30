#!/usr/bin/env python3
"""盲検評価の準備と集計。

    python judge.py prepare            # 実行ごとのスクショを、無作為な記号のフォルダに写す（対応表は key.json）
    python judge.py order <seed>       # 評価者ごとの提示順（記号の並び）を出す
    python judge.py table              # results/judge/*.json を対応表でほどいて results/judge_scores.csv にする

評価者には rubric.md と、記号のフォルダだけを渡す（モデル・スキルの有無・実行名は渡さない）。
"""
from __future__ import annotations

import csv
import json
import os
import random
import shutil
import string
import sys
import tempfile
from pathlib import Path

HERE = Path(__file__).resolve().parent
WORK = Path(os.environ.get("MVS_WORK", Path(tempfile.gettempdir()) / "tool-slides-mvs"))
JUDGE = WORK / "eval"           # 評価者に見せる場所（条件が分かる名前を含めない）
RESULTS = HERE / "results"
KEY_SEED = 20260930
FACTS = ["n_slides", "n_error_images", "pick_rule", "contrast", "credit", "broken_slides"]
SCORES = ["audience", "images", "titles", "economy", "layout", "action", "overall"]


def runs_with_shots() -> list[str]:
    return sorted(d.name for d in (WORK / "runs").glob("*") if any((d / "shots").glob("slide-*.png")))


def prepare() -> None:
    runs = runs_with_shots()
    codes = list(string.ascii_uppercase[:len(runs)])
    random.Random(KEY_SEED).shuffle(codes)
    shutil.rmtree(JUDGE, ignore_errors=True)
    JUDGE.mkdir(parents=True)
    key = {}
    for run, code in zip(runs, codes):
        shutil.copytree(WORK / "runs" / run / "shots", JUDGE / code)
        key[code] = run
    RESULTS.mkdir(exist_ok=True)
    (RESULTS / "judge_key.json").write_text(json.dumps(dict(sorted(key.items())), indent=2) + "\n")
    print(f"{len(runs)} decks -> {JUDGE}")


def order(seed: str) -> None:
    codes = sorted(p.name for p in JUDGE.iterdir() if p.is_dir())
    random.Random(int(seed)).shuffle(codes)
    print(" ".join(codes))


def table() -> None:
    key = json.loads((RESULTS / "judge_key.json").read_text())
    rows = []
    for f in sorted((RESULTS / "judge").glob("*.json")):
        for code, d in json.loads(f.read_text()).items():
            run = key[code]
            task, model, skill, rep = run.split("-")[:4]
            rows.append({"judge": f.stem, "code": code, "run_id": run, "task": task, "model": model, "skill": skill,
                         "rep": run.split("-")[-1],
                         **{k: d.get(k) for k in FACTS + SCORES}, "comment": d.get("comment", "")})
    with open(RESULTS / "judge_scores.csv", "w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=list(rows[0]))
        w.writeheader()
        w.writerows(rows)
    print(f"{len(rows)} rows -> {RESULTS / 'judge_scores.csv'}")


if __name__ == "__main__":
    cmd = sys.argv[1:] or ["help"]
    {"prepare": prepare, "order": lambda: order(sys.argv[2]), "table": table}.get(cmd[0], lambda: sys.exit(__doc__))()
