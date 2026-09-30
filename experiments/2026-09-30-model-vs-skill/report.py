#!/usr/bin/env python3
"""検証の集計: 指標・盲検評価・事実確認を合わせ、合否を判定して表にする。

    python report.py            # results/summary.md を書く

入力: results/metrics.csv（score.py）、results/judge_scores.csv（judge.py table）、
      results/factcheck/*.json（記述の正しさ）、results/number_errors.csv（数値の誤りを目で確かめた結果）、
      results/gate.csv と results/gate/*.json（ゲートの反応）
"""
from __future__ import annotations

import csv
import json
import statistics as st
from pathlib import Path

HERE = Path(__file__).resolve().parent
RESULTS = HERE / "results"
MODEL_JA = {"fable": "Fable 5.1", "opus": "Opus 5.5", "sonnet": "Sonnet 5.5", "haiku": "Haiku 4.5"}
SKILL_JA = {"S0": "なし", "S1": "初版", "S3": "検証時の版", "S4": "改訂版", "S5": "規則を足した版",
            "S6": "元の写真で確かめる版", "S7": "確認の表で照らす版"}
SCORES = ["audience", "images", "titles", "economy", "layout", "action", "overall"]
SCORE_JA = {"audience": "聴衆", "images": "画像", "titles": "タイトル", "economy": "量", "layout": "見た目",
            "action": "行動", "overall": "総合"}
TASK_JA = {"image": "主課題（聴衆・行動・時間を与えた依頼）", "under": "3点を与えない依頼（スキルなし。探索的）",
           "change": "追試: 変更の前後（聴衆・行動・時間を与えた依頼）"}


def read_csv(path: Path) -> list[dict]:
    return list(csv.DictReader(open(path, encoding="utf-8"))) if path.exists() else []


def order(m: dict) -> tuple:
    task = list(TASK_JA).index(m["task"]) if m["task"] in TASK_JA else len(TASK_JA)     # 鳥の課題などは最後
    return (task, list(MODEL_JA).index(m["model"]), m["skill"], m["rep"])


def fmt(v, spec=".1f") -> str:
    return "" if v is None else format(v, spec)


def mean(xs) -> float | None:
    xs = [x for x in xs if x is not None]
    return st.mean(xs) if xs else None


def gate_table() -> list[str]:
    """ゲートの結果。反応の分類は記録を読んで results/gate.csv に書いたもの（run_id, outcome）を使う。"""
    outcome = {r["run_id"]: r["outcome"] for r in read_csv(RESULTS / "gate.csv")}
    rows = []
    for f in sorted((RESULTS / "gate").glob("gate-*-r1.json")):
        d = json.loads(f.read_text())
        used_skill = (d["skill"] != "S0" and not d["natural"]) or "slides" in d["skill_calls"]
        cond = "なし" if d["skill"] == "S0" else ("検証時の版（`/slides` なし）" if d["natural"] else "検証時の版（`/slides` あり）")
        rows.append((list(MODEL_JA).index(d["model"]), cond,
                     f"| {MODEL_JA[d['model']]} | {cond} | {'呼んだ' if used_skill else '呼ばない'} | "
                     f"{outcome.get(d['run_id'], '')} |"))
    head = ["| モデル | スキル | スキルを呼んだか | 3点が無い依頼への反応 |", "|---|---|---|---|"]
    return head + [r[2] for r in sorted(rows)]


def compare_image(run_ids: list[str], labels: list[str], out: Path) -> None:
    """実行ごとの一覧（sheet.jpg）を縦に積み、条件の見出しを付けた1枚にする。"""
    from PIL import Image, ImageDraw, ImageFont

    font = None
    for path in ("/System/Library/Fonts/ヒラギノ角ゴシック W6.ttc", "/System/Library/Fonts/Hiragino Sans GB.ttc"):
        if Path(path).exists():
            font = ImageFont.truetype(path, 30)
            break
    sheets = [Image.open(RESULTS / r / "sheet.jpg") for r in run_ids]
    sheets = [s.crop((0, 26, s.width, s.height)) for s in sheets]        # 上端の実行名の帯を除く
    head = 56
    total = sum(s.height + head for s in sheets)
    canvas = Image.new("RGB", (1920, total), "white")
    d = ImageDraw.Draw(canvas)
    y = 0
    for s, label in zip(sheets, labels):
        d.rectangle([0, y, 1920, y + head], fill="#1f2328")
        d.text((16, y + 10), label, fill="white", font=font)
        canvas.paste(s, (0, y + head))
        y += s.height + head
    canvas.save(out, "JPEG", quality=80)


ROUND_TAG = {"main": "", "change": "_change", "retest": "_retest"}
TASK_SHORT = {"image": "主", "under": "3点なし", "change": "追試"}


def round_of(m: dict) -> str:
    """その実行を採点した回。追試の課題は change、主課題で改訂版スキル（S4）を使った実行は retest。"""
    if m["task"] == "change":
        return "change"
    return "retest" if m["skill"] == "S4" else "main"


def judged(rnd: str) -> tuple[list[dict], dict[str, list[dict]]]:
    """その回の盲検評価の行と、記述の確認（実行名 → 確認者ごとの答え）。"""
    tag = ROUND_TAG[rnd]
    judge = read_csv(RESULTS / f"judge_scores{tag}.csv")
    key_path = RESULTS / f"judge_key{tag}.json"
    key = json.loads(key_path.read_text()) if key_path.exists() else {}
    facts: dict[str, list[dict]] = {}
    for f in sorted((RESULTS / f"factcheck{tag}").glob("*.json")) if (RESULTS / f"factcheck{tag}").exists() else []:
        for code, d in json.loads(f.read_text()).items():
            if code in key:
                facts.setdefault(key[code], []).append(d)
    return judge, facts


def record(m: dict, rnd: str, number_errors: dict) -> dict:
    judge, facts = judged(rnd)
    js = [j for j in judge if j["run_id"] == m["run_id"]]
    renders = m["renders"] == "True"
    shown = st.median(int(float(j["n_error_images"])) for j in js if j["n_error_images"] not in ("", None)) if js else None
    nerr = number_errors.get(m["run_id"])
    chars = int(m["chars_max_nocap"]) if m["task"] == "change" else int(m["chars_max"])   # 追試は説明文を除いて数える（計画どおり）
    checks = {}
    if renders:
        checks = {"数値の誤り": nerr == 0, "枚数": int(m["n_main"]) <= 7, "タイトル": float(m["title_ok_rate"]) >= 0.8,
                  "本文の字数": chars <= 250, "画像の枚数": shown is not None and shown >= 20}
    fc = facts.get(m["run_id"], [])
    return {
        **m, "round": rnd, "renders": renders, "judges": js, "shown": shown, "nerr": nerr, "checks": checks,
        "ok": renders and all(checks.values()),
        # 参考: 画像ごとの説明文を除いた字数で判定し直した場合
        "ok_nocap": renders and all(v for k, v in checks.items() if k != "本文の字数") and int(m["chars_max_nocap"]) <= 250,
        "failed": [k for k, v in checks.items() if not v] if renders else ["描画"],
        "sup": mean(d["n_supported"] for d in fc), "uns": mean(d["n_unsupported"] for d in fc),
        "unc": mean(d["n_uncheckable"] for d in fc),
        "main_ok": f"{sum(bool(d['main_finding_correct']) for d in fc)}/{len(fc)}" if fc else "",
        **{s: mean(float(j[s]) for j in js) for s in SCORES},
    }


def records() -> list[dict]:
    """盲検評価をした課題の実行。鳥の課題（独立した検証）は、指標が違うので birds_report.py がまとめる。"""
    number_errors = {r["run_id"]: int(r["errors"]) for r in read_csv(RESULTS / "number_errors.csv")}
    return [record(m, round_of(m), number_errors) for m in sorted(read_csv(RESULTS / "metrics.csv"), key=order)
            if m["task"] not in ("birds", "birds2", "water", "farmh")]


def label(r: dict) -> str:
    rep = "手順確認" if r["rep"] == "0" else r["rep"]
    return f"| {MODEL_JA[r['model']]} | {SKILL_JA[r['skill']]} | {rep} |"


def score_tables(recs: list[dict], title: str) -> list[str]:
    """盲検評価の表: 実行ごと、条件ごと、評価者ごと、評価者が数えた事実、記述の正しさ。"""
    lines = [f"## {title}: 盲検評価（評価者の平均、5点満点）", "",
             "| 課題 | モデル | スキル | 回 | n | " + " | ".join(SCORE_JA[s] for s in SCORES) + " |",
             "|---|---|---|---|---|" + "---|" * len(SCORES)]
    for r in recs:
        lines.append(f"| {TASK_SHORT[r['task']]} {label(r)} {len(r['judges'])} | " + " | ".join(fmt(r[s]) for s in SCORES) + " |")
    judges = sorted({j["judge"] for r in recs for j in r["judges"]})
    if judges:
        lines += ["", f"### {title}: 評価者ごとの総合点", "",
                  "| 課題 | モデル | スキル | 回 | " + " | ".join(judges) + " |", "|---|---|---|---|" + "---|" * len(judges)]
        for r in recs:
            by = {j["judge"]: j["overall"] for j in r["judges"]}
            lines.append(f"| {TASK_SHORT[r['task']]} {label(r)} " + " | ".join(str(by.get(j, "")) for j in judges) + " |")
        lines += ["", f"### {title}: 評価者が数えた事実", "",
                  "| 課題 | モデル | スキル | 回 | 総枚数 | 画像の枚数 | 選び方の記載 | 対比 | 出典 | 破綻のある枚数 |",
                  "|---|---|---|---|---|---|---|---|---|---|"]
        for r in recs:
            js = r["judges"]
            if not js:
                continue
            votes = lambda k: f"{sum(str(j[k]).lower() == 'true' for j in js)}/{len(js)}"   # noqa: E731
            lines.append(f"| {TASK_SHORT[r['task']]} {label(r)} {st.median(int(float(j['n_slides'])) for j in js):.0f} | "
                         f"{'/'.join(str(int(float(j['n_error_images']))) for j in js)} | {votes('pick_rule')} | "
                         f"{votes('contrast')} | {votes('credit')} | "
                         f"{'/'.join(str(int(float(j['broken_slides']))) for j in js)} |")
    if any(r["sup"] is not None for r in recs):
        lines += ["", f"### {title}: 記述の正しさ（参照図と照合。確認者の平均）", "",
                  "| 課題 | モデル | スキル | 回 | 支持される | 支持されない | 確かめられない | 中心の説明が合う |",
                  "|---|---|---|---|---|---|---|---|"]
        for r in recs:
            if r["sup"] is not None:
                lines.append(f"| {TASK_SHORT[r['task']]} {label(r)} {fmt(r['sup'])} | {fmt(r['uns'])} | {fmt(r['unc'])} | "
                             f"{r['main_ok']} |")
    return lines + [""]


def main() -> None:
    recs = records()
    lines: list[str] = []
    for task, title in TASK_JA.items():
        rows = [r for r in recs if r["task"] == task]
        if not rows:
            continue
        lines += [f"## {title}: 型の指標と合否", "",
                  "| モデル | スキル | 回 | 本編 | 言い切り | 本文最大 | 説明文を除く | bullets最大 | 画像の枚数 | 数値誤り | 合否 | 不合格の理由 | 費用 | 分 |",
                  "|---|---|---|---|---|---|---|---|---|---|---|---|---|---|"]
        for r in rows:
            if not r["renders"]:
                lines.append(f"{label(r)} 描画できず | | | | | | | 不合格 | 描画 | ${float(r['cost_usd']):.2f} | "
                             f"{int(r['wall_s']) / 60:.0f} |")
                continue
            lines.append(
                f"{label(r)} {r['n_main']}枚 | {float(r['title_ok_rate']):.0%} | {r['chars_max']}字 | "
                f"{r['chars_max_nocap']}字 | {r['bullets_max']} | {'' if r['shown'] is None else f'{r['shown']:.0f}/28'} | "
                f"{'' if r['nerr'] is None else r['nerr']} | {'合格' if r['ok'] else '不合格'} | "
                f"{'・'.join(r['failed'])} | ${float(r['cost_usd']):.2f} | {int(r['wall_s']) / 60:.0f} |")
        lines.append("")

    lines += score_tables([r for r in recs if r["round"] == "main"], "主課題と3点なし（1回目の評価）")
    retest = [record(m, "retest", {r["run_id"]: r["nerr"] for r in recs}) for m in
              sorted(read_csv(RESULTS / "metrics.csv"), key=order)
              if m["run_id"] in json.loads((RESULTS / "judge_key_retest.json").read_text()).values()] \
        if (RESULTS / "judge_key_retest.json").exists() else []
    if retest:
        lines += score_tables(retest, "主課題の改訂版（改訂前のデッキと並べて同じ評価者が採点）")
    lines += score_tables([r for r in recs if r["round"] == "change"], "追試（変更の前後）")

    lines += ["## 条件ごとの平均（その課題を採点した回の評価者）", "",
              "| 課題 | モデル | スキル | n | 合格 | 説明文を除く字数なら | " + " | ".join(SCORE_JA[s] for s in SCORES) + " |",
              "|---|---|---|---|---|---|" + "---|" * len(SCORES)]
    cells: dict[tuple, list[dict]] = {}
    for r in recs:
        if r["rep"] != "0":
            cells.setdefault((r["task"], r["model"], r["skill"]), []).append(r)
    for (task, model, skill), rows in cells.items():
        lines.append(f"| {TASK_SHORT[task]} | {MODEL_JA[model]} | {SKILL_JA[skill]} | {len(rows)} | "
                     f"{sum(r['ok'] for r in rows)}/{len(rows)} | {sum(r['ok_nocap'] for r in rows)}/{len(rows)} | "
                     + " | ".join(fmt(mean(r[s] for r in rows)) for s in SCORES) + " |")

    lines += ["", "## ゲート（聴衆・行動・時間の無い依頼）", ""] + gate_table()
    (RESULTS / "summary.md").write_text("\n".join(lines) + "\n", encoding="utf-8")
    print("\n".join(lines))


if __name__ == "__main__":
    main()
