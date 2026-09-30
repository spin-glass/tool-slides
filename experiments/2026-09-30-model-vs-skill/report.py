#!/usr/bin/env python3
"""検証の集計: 指標・盲検評価・事実確認を合わせ、合否を判定して表にする。

    python report.py            # results/summary.md と比較用の画像を書く

入力: results/metrics.csv（score.py）、results/judge_scores.csv（judge.py table）、
      results/factcheck/*.json（記述の正しさ）、results/number_errors.csv（数値の誤りを目で確かめた結果）
"""
from __future__ import annotations

import csv
import json
import os
import statistics as st
import tempfile
from pathlib import Path

HERE = Path(__file__).resolve().parent
WORK = Path(os.environ.get("MVS_WORK", Path(tempfile.gettempdir()) / "tool-slides-mvs"))
RESULTS = HERE / "results"
MODEL_JA = {"fable": "Fable 5.1", "opus": "Opus 5.5", "sonnet": "Sonnet 5.5", "haiku": "Haiku 4.5"}
SKILL_JA = {"S0": "なし", "S1": "初版", "S3": "現行"}
SCORES = ["audience", "images", "titles", "economy", "layout", "action", "overall"]


def read_csv(path: Path) -> list[dict]:
    return list(csv.DictReader(open(path, encoding="utf-8"))) if path.exists() else []


def gate_table() -> list[str]:
    """ゲートの結果。反応の分類は記録を読んで results/gate.csv に書いたもの（run_id, outcome）を使う。"""
    outcome = {r["run_id"]: r["outcome"] for r in read_csv(RESULTS / "gate.csv")}
    rows = []
    for f in sorted((WORK / "runs").glob("gate-*-r1/summary.json")):
        d = json.loads(f.read_text())
        used_skill = (d["skill"] != "S0" and not d["natural"]) or "slides" in d["skill_calls"]
        cond = "なし" if d["skill"] == "S0" else ("現行（`/slides` なし）" if d["natural"] else "現行（`/slides` あり）")
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
    sheets = [Image.open(RESULTS / r / "sheet.jpg").crop((0, 26, 1920, 10**6)) for r in run_ids]
    sheets = [s.crop((0, 0, s.width, s.height)) for s in sheets]
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


def main() -> None:
    metrics = {r["run_id"]: r for r in read_csv(RESULTS / "metrics.csv")}
    judge = read_csv(RESULTS / "judge_scores.csv")
    number_errors = {r["run_id"]: int(r["errors"]) for r in read_csv(RESULTS / "number_errors.csv")}
    key = json.loads((RESULTS / "judge_key.json").read_text()) if (RESULTS / "judge_key.json").exists() else {}
    facts: dict[str, list[dict]] = {}
    for f in sorted((RESULTS / "factcheck").glob("*.json")) if (RESULTS / "factcheck").exists() else []:
        for code, d in json.loads(f.read_text()).items():
            facts.setdefault(key[code], []).append(d)

    lines = ["## 実行ごとの結果", "",
             "| モデル | スキル | 回 | 本編 | 言い切り | 本文最大 | bullets最大 | ヘッジ | 誤り画像 | 数値誤り | 合否 | 総合 | 記述○/× | 費用 | 分 |",
             "|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|"]
    cells: dict[tuple, list[dict]] = {}
    for run_id, m in sorted(metrics.items(), key=lambda kv: (list(MODEL_JA).index(kv[1]["model"]), kv[1]["skill"], kv[1]["rep"])):
        js = [j for j in judge if j["run_id"] == run_id]
        shown = st.median(int(float(j["n_error_images"])) for j in js) if js else None
        overall = st.mean(float(j["overall"]) for j in js) if js else None
        nerr = number_errors.get(run_id)
        renders = m["renders"] == "True"
        ok = (renders and nerr == 0 and int(m["n_main"]) <= 7 and float(m["title_ok_rate"]) >= 0.8
              and int(m["chars_max"]) <= 250 and shown is not None and shown >= 20) if renders else False
        fc = facts.get(run_id, [])
        sup = st.mean(d["n_supported"] for d in fc) if fc else None
        uns = st.mean(d["n_unsupported"] for d in fc) if fc else None
        rec = {"ok": ok, "overall": overall, "shown": shown, "uns": uns, "sup": sup, **m,
               **{s: st.mean(float(j[s]) for j in js) if js else None for s in SCORES}}
        cells.setdefault((m["model"], m["skill"]), []).append(rec)
        if not renders:
            lines.append(f"| {MODEL_JA[m['model']]} | {SKILL_JA[m['skill']]} | {m['rep']} | 描画できず | | | | | | | 不合格 | | | "
                         f"${float(m['cost_usd']):.2f} | {int(m['wall_s']) / 60:.0f} |")
            continue
        lines.append(
            f"| {MODEL_JA[m['model']]} | {SKILL_JA[m['skill']]} | {m['rep']} | {m['n_main']}枚 | "
            f"{float(m['title_ok_rate']):.0%} | {m['chars_max']}字 | {m['bullets_max']} | {m['hedges']} | "
            f"{'' if shown is None else f'{shown:.0f}/28'} | {'' if nerr is None else nerr} | {'合格' if ok else '不合格'} | "
            f"{'' if overall is None else f'{overall:.1f}'} | {'' if sup is None else f'{sup:.1f}/{uns:.1f}'} | "
            f"${float(m['cost_usd']):.2f} | {int(m['wall_s']) / 60:.0f} |")

    lines += ["", "## 条件ごとの平均（盲検評価、5点満点）", "",
              "| モデル | スキル | n | 合格 | " + " | ".join(SCORES) + " |", "|---|---|---|---|" + "---|" * len(SCORES)]
    for (model, skill), recs in sorted(cells.items(), key=lambda kv: (list(MODEL_JA).index(kv[0][0]), kv[0][1])):
        vals = [(st.mean(r[s] for r in recs if r[s] is not None) if any(r[s] is not None for r in recs) else None)
                for s in SCORES]
        lines.append(f"| {MODEL_JA[model]} | {SKILL_JA[skill]} | {len(recs)} | {sum(r['ok'] for r in recs)}/{len(recs)} | "
                     + " | ".join("" if v is None else f"{v:.1f}" for v in vals) + " |")

    lines += ["", "## ゲート（聴衆・行動・時間の無い依頼）", ""] + gate_table()
    (RESULTS / "summary.md").write_text("\n".join(lines) + "\n", encoding="utf-8")
    print("\n".join(lines))


if __name__ == "__main__":
    main()
