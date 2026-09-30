#!/usr/bin/env python3
"""盲検評価の準備と集計。

    python judge.py prepare                        # 実行ごとのスクショを、無作為な記号のフォルダに写す（対応表は judge_key.json）
    python judge.py order <seed>                   # 評価者ごとの提示順（記号の並び）を出す
    python judge.py prompt judge <seed> <name>     # 評価者に渡す文面（rubric の前半 + 作業の決まり）
    python judge.py prompt factcheck <seed> <name> # 記述の正しさの確認者に渡す文面（rubric の後半 + 参照図）
    python judge.py collect                        # 評価者が書いた JSON を results/judge/ と results/factcheck/ に集める
    python judge.py table                          # results/judge/*.json を対応表でほどいて results/judge_scores.csv にする

評価者には文面と、記号のフォルダだけを渡す（モデル・スキルの有無・実行名は渡さない）。
記号のフォルダは、実行名の見えない場所（環境変数 MVS_EVAL。既定は MVS_WORK/eval）に作る。
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
JUDGE = Path(os.environ.get("MVS_EVAL", WORK / "eval"))    # 評価者に見せる場所（条件が分かる名前を含めない）
DECKS = JUDGE / "decks"
OUT = JUDGE / "out"
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
    DECKS.mkdir(parents=True)
    OUT.mkdir()
    key = {}
    for run, code in zip(runs, codes):
        shutil.copytree(WORK / "runs" / run / "shots", DECKS / code)
        key[code] = run
    for n in (1, 2):                      # 記述の正しさの確認に使う参照図（誤った28枚の全数）
        shutil.copy(RESULTS / f"truth-errors-{n}.jpg", JUDGE / f"reference-{n}.jpg")
    RESULTS.mkdir(exist_ok=True)
    (RESULTS / "judge_key.json").write_text(json.dumps(dict(sorted(key.items())), indent=2) + "\n")
    print(f"{len(runs)} decks -> {DECKS}")


def order(seed: str) -> list[str]:
    codes = sorted(p.name for p in DECKS.iterdir() if p.is_dir())
    random.Random(int(seed)).shuffle(codes)
    return codes


def prompt(kind: str, seed: str, name: str) -> None:
    head, tail = (HERE / "judge/rubric.md").read_text(encoding="utf-8").split("\n---\n")
    rubric = (head if kind == "judge" else tail).strip()
    rubric = rubric.split("\n", 2)[2].strip()            # 先頭の見出し（誰に渡す文面か）を除く
    text = (HERE / f"judge/prompt_{kind}.md").read_text(encoding="utf-8")
    print(text.format(RUBRIC=rubric, DIR=DECKS, ORDER=" → ".join(order(seed)), OUT=OUT / f"{kind}-{name}.json",
                      REF1=JUDGE / "reference-1.jpg", REF2=JUDGE / "reference-2.jpg"))


def collect() -> None:
    for kind, dest in (("judge", RESULTS / "judge"), ("factcheck", RESULTS / "factcheck")):
        dest.mkdir(exist_ok=True)
        for f in sorted(OUT.glob(f"{kind}-*.json")):
            data = json.loads(f.read_text(encoding="utf-8"))      # JSON として読めることを確かめてから写す
            (dest / f.name.removeprefix(f"{kind}-")).write_text(json.dumps(data, ensure_ascii=False, indent=1) + "\n",
                                                                encoding="utf-8")
            print(f"{f.name}: {len(data)} decks")


def table() -> None:
    key = json.loads((RESULTS / "judge_key.json").read_text())
    rows = []
    for f in sorted((RESULTS / "judge").glob("*.json")):
        for code, d in json.loads(f.read_text()).items():
            run = key[code]
            kind, model, skill = run.split("-")[:3]
            task = "image" if kind == "image" else "under"      # gate-* と under-* は、3点を与えない依頼で作ったデッキ
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
    {"prepare": prepare, "order": lambda: print(" ".join(order(sys.argv[2]))), "table": table, "collect": collect,
     "prompt": lambda: prompt(*sys.argv[2:5])}.get(cmd[0], lambda: sys.exit(__doc__))()
