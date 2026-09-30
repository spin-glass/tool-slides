#!/usr/bin/env python3
"""検証で作らせたデッキを、公開サイトに載せる形にまとめる（条件つきの一覧と、写真の出典ページ）。

    MVS_WORK=… .venv/bin/python experiments/2026-09-30-model-vs-skill/site.py

出力は site/（git には入れない。デッキ1本あたり約6MB）。scripts/publish.sh が _output/experiments/<この検証>/ に写して公開する。
デッキは score.py が描画し直した出力（作業場所の _output）をそのまま使う。
"""
from __future__ import annotations

import csv
import html
import json
import os
import re
import shutil
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
import report  # noqa: E402

SITE = HERE / "site"
WORK = Path(os.environ["MVS_WORK"])       # run.py の作業場所（各実行の ws/_output を読む）
TITLE = "検証: 出来はモデルによるのか、スキルによるのか"
LEAD = """同じ依頼を、モデル（Fable 5.1・Opus 5.5・Sonnet 5.5）と slides スキルの有無・版を変えて作らせたデッキです。
依頼はどれも「画像分類の誤り（または新旧の版の違い）を、実際の画像で説明する10分の発表」。スキルの版は、なし・初版（画像の仕組みが無い版）・
検証時の版（具体例の画像の作り方を一般化した版）・改訂版（検証の指摘を受けて直した版）の4つです。
「総合」は、条件を伏せた評価者（Claude のモデル）による5段階の評価の平均で、括弧内は評価者の人数です。
「型」は、事前に決めた合否（本編7枚以下・言い切りタイトル80%以上・本文250字以下・数値の誤り0・画像20枚以上）です。"""


def deck_title(qmd: Path) -> str:
    m = re.search(r'^title:\s*"?(.*?)"?\s*$', qmd.read_text(encoding="utf-8"), re.M) if qmd.exists() else None
    return re.sub(r"\s*<br\s*/?>\s*", " ", m.group(1)) if m else ""     # タイトル内の改行指定は一覧では空白にする


def image_checks() -> dict[str, list[dict]]:
    """画像と主張の照合（imagecheck.py）で、合わない・一部合わないとされた主張。デッキ名 → 行。"""
    path = report.RESULTS / "imagecheck.csv"
    out: dict[str, list[dict]] = {}
    for r in csv.DictReader(open(path, encoding="utf-8")) if path.exists() else []:
        out.setdefault(r["deck"], [])
        if r["final"] in ("ng", "partial"):
            out[r["deck"]].append(r)
    return out


def build() -> None:
    shutil.rmtree(SITE, ignore_errors=True)
    SITE.mkdir()
    recs = report.records()
    checks = image_checks()
    sections: dict[str, list[str]] = {}
    for r in recs:
        summary = json.loads((report.RESULTS / r["run_id"] / "summary.json").read_text())
        deck_dir = Path(summary.get("deck_path") or "decks/farm-errors/index.qmd").parent
        src = WORK / "runs" / r["run_id"] / "ws" / "_output" / deck_dir
        if not (src / "index.html").exists():
            print(f"skip (no output): {r['run_id']}")
            continue
        shutil.copytree(src, SITE / r["run_id"])
        n = len(r["judges"])
        overall = "" if r["overall"] is None else f"{r['overall']:.1f}（{n}）"
        images = "" if r["images"] is None else f"{r['images']:.1f}"
        rep = "手順確認" if r["rep"] == "0" else r["rep"]
        title = html.escape(deck_title(report.RESULTS / r["run_id"] / "index.qmd"))
        ok = "合格" if r["ok"] else "不合格"
        bad = checks.get(r["run_id"])
        ic = "" if bad is None else ("なし" if not bad else
             f"<a href=\"imagecheck.html#{r['run_id']}\">合わない{sum(b['final'] == 'ng' for b in bad)}・"
             f"一部{sum(b['final'] == 'partial' for b in bad)}</a>")
        sections.setdefault(r["task"], []).append(
            f"<tr><td>{report.MODEL_JA[r['model']]}</td><td>{report.SKILL_JA[r['skill']]}</td><td>{rep}</td>"
            f"<td><a href=\"{r['run_id']}/index.html\">{title or r['run_id']}</a></td>"
            f"<td>{r['n_main']}枚</td><td>{ok}</td><td>{overall}</td><td>{images}</td><td>{ic}</td></tr>")
    body = []
    for task, title in report.TASK_JA.items():
        if task not in sections:
            continue
        body.append(f"<h2>{html.escape(title)}</h2><table><tr><th>モデル</th><th>スキル</th><th>回</th><th>デッキ</th>"
                    f"<th>本編</th><th>型</th><th>総合</th><th>画像</th><th>画像と主張</th></tr>{''.join(sections[task])}</table>")
    notes = ("<p class=\"n\">「画像と主張」は、スライドの主張（タイトル・箇条書き・図の見出し・画像ごとの説明）を、載っている画像と"
             "1件ずつ照らした結果（確認者は Claude のモデル。一部は元画像を拡大して確かめ直した）。件数を押すと中身を見られる。</p>"
             "<p class=\"n\">3点を与えない依頼の Fable は、ゲート課題（8ターンまで）でそのまま作り切ったデッキ。"
             "Haiku 4.5 は手順確認のための1回で、事前の条件には含まない（このデッキには写真の出典が無いので、下の一覧を参照）。"
             "主課題の改訂版の点は、改訂前のデッキと並べて採点した別の回の評価（評価者1名）。</p>")
    page = f'''<!doctype html><html lang="ja"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1"><title>{html.escape(TITLE)}</title>
<meta name="robots" content="noindex">
<style>
body{{font-family:"Hiragino Sans","Noto Sans JP",sans-serif;max-width:960px;margin:40px auto;padding:0 16px;color:#1f2328;background:#fff}}
h1{{font-size:1.35em}} h2{{font-size:1.1em;margin-top:2em}} p{{line-height:1.7}} .n{{color:#57606a;font-size:.9em}}
table{{border-collapse:collapse;width:100%;font-size:.92em}} th,td{{border-bottom:1px solid #d0d7de;padding:6px 8px;text-align:left}}
th{{color:#57606a;font-weight:600}} a{{color:#0b5cad}}
</style></head><body><h1>{html.escape(TITLE)}</h1><p>{html.escape(LEAD).replace(chr(10), "")}</p>{notes}
{"".join(body)}
<p class="n"><a href="credits.html">写真の出典</a>（Open Images V7 に収録された Flickr の写真。各作者が CC BY 2.0 で公開）｜<a href="../../index.html">デッキの一覧へ</a></p>
</body></html>'''
    (SITE / "index.html").write_text(page, encoding="utf-8")

    blocks = []
    for r in recs:
        bad = checks.get(r["run_id"]) or []
        if not bad:
            continue
        items = "".join(f"<li><b>{'合わない' if b['final'] == 'ng' else '一部合わない'}</b>（{b['slide']}枚目）"
                        f"{html.escape(b['claim'])}<br><span class=\"d\">{html.escape(b['detail'])}"
                        f"{'（確かめ直し: ' + html.escape(b['adjudication']) + '）' if b['adjudication'] else ''}</span></li>"
                        for b in sorted(bad, key=lambda b: int(b["slide"] or 0)))
        blocks.append(f"<h2 id=\"{r['run_id']}\">{report.MODEL_JA[r['model']]} × {report.SKILL_JA[r['skill']]}"
                      f"（{report.TASK_JA[r['task']].split('（')[0]}、{r['rep']}回目）</h2>"
                      f"<p><a href=\"{r['run_id']}/index.html\">デッキを開く</a></p><ul>{items}</ul>")
    detail = f'''<!doctype html><html lang="ja"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1"><title>画像と主張の照合</title><meta name="robots" content="noindex">
<style>body{{font-family:"Hiragino Sans","Noto Sans JP",sans-serif;max-width:960px;margin:40px auto;padding:0 16px;color:#1f2328;background:#fff}}
h2{{font-size:1.05em;margin-top:2em}} li{{margin:8px 0;line-height:1.6}} .d{{color:#57606a;font-size:.92em}} a{{color:#0b5cad}}</style>
</head><body><h1>画像と主張の照合：合わなかった主張</h1>
<p>スライドの主張と、そこに載っている画像が合わないもの（「合わない」）と、多くの画像には合うが当てはまらない画像があるもの・言い過ぎのもの（「一部合わない」）の一覧。</p>
{"".join(blocks)}<p><a href="index.html">検証のデッキ一覧へ</a></p></body></html>'''
    (SITE / "imagecheck.html").write_text(detail, encoding="utf-8")

    rows = list(csv.DictReader(open(HERE / "task/data/credits.csv", encoding="utf-8")))
    items = "".join(f'<li>{html.escape(r["title"] or "（無題）")} — {html.escape(r["author"])} '
                    f'（<a href="{html.escape(r["source"])}">元の写真</a>）</li>' for r in rows)
    credits = f'''<!doctype html><html lang="ja"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1"><title>写真の出典</title><meta name="robots" content="noindex">
<style>body{{font-family:"Hiragino Sans","Noto Sans JP",sans-serif;max-width:960px;margin:40px auto;padding:0 16px;color:#1f2328;background:#fff}}
li{{margin:4px 0;font-size:.9em}} a{{color:#0b5cad}}</style></head><body><h1>写真の出典</h1>
<p>この検証のデッキに載る写真は、すべて Open Images V7（validation / test）に収録された Flickr の写真で、各作者が
<a href="https://creativecommons.org/licenses/by/2.0/">CC BY 2.0</a> で公開したものです。表示用に長辺256pxへ縮小しています。</p>
<ol>{items}</ol><p><a href="index.html">検証のデッキ一覧へ</a></p></body></html>'''
    (SITE / "credits.html").write_text(credits, encoding="utf-8")
    n_files = sum(1 for p in SITE.rglob("*") if p.is_file())
    size = sum(p.stat().st_size for p in SITE.rglob("*") if p.is_file())
    print(f"{sum(len(v) for v in sections.values())} decks, {n_files} files, {size / 1e6:.0f} MB -> {SITE}")


if __name__ == "__main__":
    build()
