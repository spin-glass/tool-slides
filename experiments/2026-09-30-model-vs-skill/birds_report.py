#!/usr/bin/env python3
"""独立した検証（鳥の課題）の集計: 指標1・2と副次の値を条件ごとにまとめ、README の判定規則を当てはめる。

    MVS_WORK=… .venv/bin/python experiments/2026-09-30-model-vs-skill/birds_report.py [birds2]   # results/<課題>_summary.md

課題は birds（省略時）か、その追加の birds2（欠陥を直したデータ。指標1は行わない）。読むもの（先に作っておく）:
  results/metrics.csv                 score.py（本編の枚数・タイトル・字数・ターン・時間・費用）
  results/<課題>_shown.csv            birdcheck.py（誤りの画像29枚が載ったか）
  results/<課題>_planted.csv          仕込みの6枚を見抜いたか（birdcheck.py の材料を読んで決めたもの。根拠つき）
  results/imagecheck_birds_rates.csv  imagecheck.py table birds（確認者ごと・デッキごとの食い違いの率。birds だけ）
"""
from __future__ import annotations

import csv
import os
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parent.parent
RESULTS = HERE / "results"
WORK = Path(os.environ["MVS_WORK"])
sys.path.insert(0, str(ROOT / ".claude/skills/slides/scripts"))
import lint_slides as lint  # noqa: E402  現在の lint（S5 の版）で、どの版のデッキも同じ基準で数える

MODELS = ("opus", "sonnet")
SKILLS = ("S4", "S5")
MODEL_JA = {"opus": "Opus 5.5", "sonnet": "Sonnet 5.5"}
SKILL_JA = {"S4": "改訂版（S4）", "S5": "規則を足した版（S5）"}


def read(name: str) -> list[dict]:
    path = RESULTS / name
    return list(csv.DictReader(open(path, encoding="utf-8"))) if path.exists() else []


def cond(run: str) -> tuple[str, str]:
    _, model, skill = run.split("-")[:3]
    return model, skill


def mean(xs: list[float]) -> float | None:
    return sum(xs) / len(xs) if xs else None


def image_absolute(run: str) -> int:
    qmd = WORK / "runs" / run / "ws/decks/bird-errors/index.qmd"
    if not qmd.exists():
        return 0
    issues = lint.check_deck(lint.parse_deck(qmd), lint.load_ng_words())
    return sum(i.rule == "image-absolute" for i in issues)


def main() -> None:
    task = (sys.argv[1:] or ["birds"])[0]
    metrics = {m["run_id"]: m for m in read("metrics.csv") if m["task"] == task}
    runs = sorted(metrics)
    shown = read(f"{task}_shown.csv")
    planted = {(r["run_id"], r["id"]): r for r in read(f"{task}_planted.csv")}
    rates: dict[str, list[float]] = {}
    for r in read("imagecheck_birds_rates.csv") if task == "birds" else []:
        if r["rate"] != "":
            rates.setdefault(r["deck"], []).append(float(r["rate"]))

    per_run = {}
    for run in runs:
        m = metrics[run]
        mine = [s for s in shown if s["run_id"] == run]
        plant = [s for s in mine if s["planted"] == "True"]
        caught = [p for p in plant if planted.get((run, p["id"]), {}).get("caught") == "yes"]
        msg_only = [p for p in plant if planted.get((run, p["id"]), {}).get("final_message_only") == "yes"]
        misled = [p for p in plant if p["shown"] == "True" and planted.get((run, p["id"]), {}).get("caught") != "yes"]
        per_run[run] = {
            "renders": m["renders"] == "True",
            "m1": mean(rates.get(run, [])), "m1_n": len(rates.get(run, [])),
            "caught": len(caught), "misled": len(misled), "msg_only": len(msg_only),
            "decided": all((run, p["id"]) in planted for p in plant) and bool(plant),
            "shown": sum(s["shown"] == "True" for s in mine), "shown_main": sum(s["shown_main"] == "True" for s in mine),
            "n_main": m.get("n_main", ""), "title_ok": m.get("title_ok_rate", ""),
            "chars": m.get("chars_max_nocap", ""), "turns": m.get("num_turns", ""),
            "min": round(float(m["wall_s"]) / 60) if m.get("wall_s") else "", "cost": m.get("cost_usd", ""),
            "absolute": image_absolute(run),
        }

    lines = [f"# 独立した検証（鳥の課題{'' if task == 'birds' else '・追加'}）の集計", "",
             "`birds_report.py` が書いた。指標と判定規則は README「独立した検証の計画」。", "",
             "## デッキごと", "",
             "| 実行 | 指標1 食い違い（確認者数） | 見抜いた | 誤ったラベルのまま見せた | 応答でだけ触れた | 誤りの画像を載せた（本編） "
             "| 本編 | 言い切り率 | 最大字数 | 言い切りの warning | ターン | 分 | 費用 |",
             "|---|---|---|---|---|---|---|---|---|---|---|---|---|"]
    for run, v in per_run.items():
        m1 = "" if v["m1"] is None else f"{100 * v['m1']:.1f}%（{v['m1_n']}）"
        lines.append(f"| {run} | {m1} | {v['caught'] if v['decided'] else '未判定'} | {v['misled']} | {v['msg_only']} | "
                     f"{v['shown']}（{v['shown_main']}） | {v['n_main']} | {v['title_ok']} | {v['chars']} | {v['absolute']} | "
                     f"{v['turns']} | {v['min']} | {v['cost']} |")

    def cell(model: str | None, skill: str, key: str, agg=sum):
        vals = [v[key] for run, v in per_run.items() if cond(run)[1] == skill and (model is None or cond(run)[0] == model)
                and v[key] is not None]
        return agg(vals) if vals else None

    lines += ["", "## 条件ごと", "",
              "| モデル | スキル | デッキ | 指標1（デッキの平均） | 見抜いた（合計） | 誤ったラベルのまま見せた（合計） |",
              "|---|---|---|---|---|---|"]
    for model in (*MODELS, None):
        for skill in SKILLS:
            n = sum(1 for run in per_run if cond(run)[1] == skill and (model is None or cond(run)[0] == model))
            m1 = cell(model, skill, "m1", mean)
            lines.append(f"| {MODEL_JA.get(model, '両方')} | {SKILL_JA[skill]} | {n} | "
                         f"{'' if m1 is None else f'{100 * m1:.1f}%'} | {cell(model, skill, 'caught')} | "
                         f"{cell(model, skill, 'misled')} |")

    # 判定規則（README のとおり）
    verdicts = ["", "## 判定規則の当てはめ", ""]
    c = {(m, s): cell(m, s, "caught") or 0 for m in (*MODELS, None) for s in SKILLS}
    if not all(v["decided"] for v in per_run.values()):
        verdicts.append("- 規則(8): 見抜いたかの判定が済んでいないデッキがある（results/birds_planted.csv）")
    elif c[(None, "S5")] >= c[(None, "S4")] + 4 and all(c[(m, "S5")] > c[(m, "S4")] for m in MODELS):
        verdicts.append(f"- 規則(8)（ラベル）: **効いた**（S5 {c[(None, 'S5')]}枚 対 S4 {c[(None, 'S4')]}枚。"
                        f"Opus {c[('opus', 'S5')]} 対 {c[('opus', 'S4')]}、Sonnet {c[('sonnet', 'S5')]} 対 {c[('sonnet', 'S4')]}）")
    elif c[(None, "S5")] <= c[(None, "S4")]:
        verdicts.append(f"- 規則(8)（ラベル）: **効かなかった**（S5 {c[(None, 'S5')]}枚 対 S4 {c[(None, 'S4')]}枚）")
    else:
        verdicts.append(f"- 規則(8)（ラベル）: **はっきりしない**（S5 {c[(None, 'S5')]}枚 対 S4 {c[(None, 'S4')]}枚。"
                        f"Opus {c[('opus', 'S5')]} 対 {c[('opus', 'S4')]}、Sonnet {c[('sonnet', 'S5')]} 対 {c[('sonnet', 'S4')]}）")
    r = {(m, s): cell(m, s, "m1", mean) for m in (*MODELS, None) for s in SKILLS}
    if task != "birds":
        verdicts.append("- 規則(7): この課題では照合（指標1）を行わない")
    elif any(v is None for v in r.values()):
        verdicts.append("- 規則(7): 照合の結果がそろっていない（results/imagecheck_birds_rates.csv）")
    else:
        d = 100 * (r[(None, "S5")] - r[(None, "S4")])
        lower = all(r[(m, "S5")] < r[(m, "S4")] for m in MODELS)
        higher = all(r[(m, "S5")] > r[(m, "S4")] for m in MODELS)
        word = "減った" if d <= -3 and lower else "増えた" if d >= 3 and higher else "差は見えない"
        verdicts.append(f"- 規則(7)（照合）: **{word}**（S5 {100 * r[(None, 'S5')]:.1f}% 対 S4 {100 * r[(None, 'S4')]:.1f}%、"
                        f"差 {d:+.1f} ポイント。Opus {100 * r[('opus', 'S5')]:.1f}% 対 {100 * r[('opus', 'S4')]:.1f}%、"
                        f"Sonnet {100 * r[('sonnet', 'S5')]:.1f}% 対 {100 * r[('sonnet', 'S4')]:.1f}%）")
    lines += verdicts
    out = RESULTS / f"{task}_summary.md"
    out.write_text("\n".join(lines) + "\n", encoding="utf-8")
    print("\n".join(lines))


if __name__ == "__main__":
    main()
