#!/usr/bin/env python3
"""盲検評価の準備と集計。

    python judge.py prepare [回] [実行名 ...]              # スクショを、無作為な記号のフォルダに写す（対応表は judge_key*.json）
    python judge.py order <seed> [回]                     # 評価者ごとの提示順（記号の並び）を出す
    python judge.py prompt judge <seed> <name> [回]       # 評価者に渡す文面（rubric の前半 + 作業の決まり）
    python judge.py prompt factcheck <seed> <name> [回]   # 記述の正しさの確認者に渡す文面（rubric の後半 + 参照図）
    python judge.py collect [回] [メモから組み立てる評価者 ...]  # 評価者が書いた JSON を results/ に集める
    python judge.py table [回]                            # 集めた JSON を対応表でほどいて judge_scores*.csv にする

回（省略時は main）:
    main    主課題の全実行（rubric.md）
    retest  改訂したスキルの追試。主課題と同じ依頼で、比べる相手に主課題のデッキも混ぜる（rubric.md）
    change  追試の課題「変更の前後」（rubric_change.md）

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
EVAL = Path(os.environ.get("MVS_EVAL", WORK / "eval"))    # 評価者に見せる場所（条件が分かる名前を含めない）
RESULTS = HERE / "results"
KEY_SEED = 20260930
FACTS = ["n_slides", "n_error_images", "pick_rule", "contrast", "credit", "broken_slides"]
SCORES = ["audience", "images", "titles", "economy", "layout", "action", "overall"]
ROUNDS = {  # 回: (rubric, 参照図の名前)
    "main": ("rubric.md", "truth-errors"),
    "retest": ("rubric.md", "truth-errors"),
    "change": ("rubric_change.md", "truth-change"),
}


class Round:
    def __init__(self, name: str = "main"):
        self.name = name
        self.rubric, self.reference = ROUNDS[name]
        tag = "" if name == "main" else f"_{name}"
        self.dir = EVAL if name == "main" else EVAL.parent / f"{EVAL.name}-{name}"
        self.decks, self.out = self.dir / "decks", self.dir / "out"
        self.key = RESULTS / f"judge_key{tag}.json"
        self.judge_dir, self.fact_dir = RESULTS / f"judge{tag}", RESULTS / f"factcheck{tag}"
        self.scores = RESULTS / f"judge_scores{tag}.csv"
        self.seed = KEY_SEED + sum(map(ord, tag))


def runs_with_shots() -> list[str]:
    return sorted(d.name for d in (WORK / "runs").glob("*") if any((d / "shots").glob("slide-*.png")))


def prepare(rnd: Round, runs: list[str]) -> None:
    runs = sorted(runs) or runs_with_shots()
    codes = list(string.ascii_uppercase[:len(runs)])
    random.Random(rnd.seed).shuffle(codes)
    if rnd.dir.exists():
        sys.exit(f"既にある（評価者が使っているかもしれないので消さない）: {rnd.dir}")
    rnd.decks.mkdir(parents=True)
    rnd.out.mkdir()
    key = {}
    for run, code in zip(runs, codes):
        shutil.copytree(WORK / "runs" / run / "shots", rnd.decks / code)
        key[code] = run
    for n in (1, 2):                      # 記述の正しさの確認に使う参照図
        shutil.copy(RESULTS / f"{rnd.reference}-{n}.jpg", rnd.dir / f"reference-{n}.jpg")
    RESULTS.mkdir(exist_ok=True)
    rnd.key.write_text(json.dumps(dict(sorted(key.items())), indent=2) + "\n")
    print(f"{len(runs)} decks -> {rnd.decks}")


def order(rnd: Round, seed: str) -> list[str]:
    codes = sorted(p.name for p in rnd.decks.iterdir() if p.is_dir())
    random.Random(int(seed)).shuffle(codes)
    return codes


def prompt(rnd: Round, kind: str, seed: str, name: str) -> None:
    head, tail = (HERE / "judge" / rnd.rubric).read_text(encoding="utf-8").split("\n---\n")
    rubric = (head if kind == "judge" else tail).strip()
    rubric = rubric.split("\n", 2)[2].strip()            # 先頭の見出し（誰に渡す文面か）を除く
    text = (HERE / f"judge/prompt_{kind}.md").read_text(encoding="utf-8")
    print(text.format(RUBRIC=rubric, DIR=rnd.decks, ORDER=" → ".join(order(rnd, seed)),
                      OUT=rnd.out / f"{kind}-{name}.json",
                      REF1=rnd.dir / "reference-1.jpg", REF2=rnd.dir / "reference-2.jpg"))


def read_notes(path: Path) -> dict:
    """評価者が1デッキごとに追記したメモを、1つの辞書にまとめる。同じ記号は後の行を採る。

    1行は {記号: 答え} か、{"deck": 記号, ...答え} のどちらか（評価者によって書き方が違った）。
    """
    data: dict = {}
    for line in path.read_text(encoding="utf-8").splitlines():
        if not line.strip():
            continue
        row = json.loads(line)
        if "deck" in row:
            data[row["deck"]] = {k: v for k, v in row.items() if k != "deck"}
        else:
            data.update(row)
    return data


def collect(rnd: Round, from_notes: list[str]) -> None:
    """最終の JSON を集める。from_notes に挙げた評価者は、最終の JSON の代わりに追記メモから組み立てる。"""
    for kind, dest in (("judge", rnd.judge_dir), ("factcheck", rnd.fact_dir)):
        dest.mkdir(exist_ok=True)
        names = sorted({f.name.split(".")[0].removeprefix(f"{kind}-") for f in rnd.out.glob(f"{kind}-*.json*")})
        for name in names:
            final, notes = rnd.out / f"{kind}-{name}.json", rnd.out / f"{kind}-{name}.json.notes.jsonl"
            if name in from_notes:
                data, source = read_notes(notes), "notes"
            elif final.exists():
                data, source = json.loads(final.read_text(encoding="utf-8")), "final"
            else:
                print(f"{kind}-{name}: 最終の JSON が無い（メモを使うなら collect に名前を渡す）")
                continue
            (dest / f"{name}.json").write_text(json.dumps(data, ensure_ascii=False, indent=1) + "\n", encoding="utf-8")
            print(f"{kind}-{name}: {len(data)} decks ({source})")


def table(rnd: Round) -> None:
    key = json.loads(rnd.key.read_text())
    rows = []
    for f in sorted(rnd.judge_dir.glob("*.json")):
        for code, d in json.loads(f.read_text()).items():
            run = key[code]
            kind, model, skill = run.split("-")[:3]
            task = "under" if kind in ("gate", "under") else kind     # gate-* と under-* は、3点を与えない依頼で作ったデッキ
            d = {"n_error_images": d.get("n_changed_images"), **d}      # 追試の課題では「正誤が変わった画像」の枚数
            rows.append({"judge": f.stem, "code": code, "run_id": run, "task": task, "model": model, "skill": skill,
                         "rep": run.split("-")[-1],
                         **{k: d.get(k) for k in FACTS + SCORES}, "comment": d.get("comment", "")})
    with open(rnd.scores, "w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=list(rows[0]))
        w.writeheader()
        w.writerows(rows)
    print(f"{len(rows)} rows -> {rnd.scores}")


def main() -> None:
    args = sys.argv[1:] or ["help"]
    cmd, rest = args[0], args[1:]

    def round_of(position: int) -> Round:
        return Round(rest[position] if len(rest) > position and rest[position] in ROUNDS else "main")

    if cmd == "prepare":
        prepare(round_of(0), [a for a in rest if a not in ROUNDS])
    elif cmd == "order":
        print(" ".join(order(round_of(1), rest[0])))
    elif cmd == "prompt":
        prompt(round_of(3), *rest[:3])
    elif cmd == "collect":
        collect(round_of(0), [a for a in rest if a not in ROUNDS])
    elif cmd == "table":
        table(round_of(0))
    else:
        sys.exit(__doc__)


if __name__ == "__main__":
    main()
