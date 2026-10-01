#!/usr/bin/env python3
"""主張の表 claims.csv を読む・検査する。標準ライブラリのみ。

設計書と確認型スライドは、同じ主張の表から作る。表が正本で、スライドの `<!-- claims: C1,C2 -->` と
設計書の本文はこの表の id を参照する（lint_slides.py と check_doc.py がこのモジュールで検査する）。

列（この順。先頭行は列名）:
  id       主張ID（C1, C2, …。英数字と - _）
  doc      原文の文書名（例: 運用・移行設計）。本人の説明や会議なら「本人 2026-10-01」のように出所
  section  原文の章・箇所（例: §8.1–8.4、12–16行）。版が複数あるなら版も
  claim    主張を1文で（原文の言葉を保つ。数値は単位・母数つき）
  status   事実 / 参考値 / 方針 / 想定 / 提案 / 決定 / 未決
  evidence 根拠（測定・原文の引用・決めた人と日付）。無ければ空
  owner    決める担当（未決・提案のとき）。無ければ空
  target   掲載先: doc / deck / both / none
  note     補足（矛盾する別の記述、注意点）

status の意味:
  事実   測定・記録で確かめたこと（測定日・データ版つき）
  参考値 原文に数値があるが、測定条件が残っていない・再測定前（「約1%（再集計する）」など）。実績と書かない
  方針   原文に「こうする」と書いてあること。実施済み・実績ではない
  想定   原文の見積り・仮の期間（「3か月」「1日20分」など）。確約と書かない
  提案   レビューで足した案。原文にはない。本人未採択なら note に書く
  決定   決めた人と日付がある決定（本人の原文を evidence に）
  未決   まだ決まっていない。スライドでは `[…]{.tbd}` か「まだ決めていない点」の一覧に出す

使い方: python3 claims.py decks/<name>/claims.csv
"""
from __future__ import annotations

import csv
import re
import sys
from collections import Counter
from pathlib import Path

COLUMNS = ["id", "doc", "section", "claim", "status", "evidence", "owner", "target", "note"]
STATUSES = ("事実", "参考値", "方針", "想定", "提案", "決定", "未決")
TARGETS = ("doc", "deck", "both", "none")
ID_RE = re.compile(r"^[A-Za-z][A-Za-z0-9_-]*$")


def load(path: Path) -> list[dict[str, str]]:
    with open(path, encoding="utf-8", newline="") as f:
        rows = list(csv.DictReader(f))
    return [{k: (v or "").strip() for k, v in r.items() if k is not None} for r in rows]


def validate(rows: list[dict[str, str]]) -> list[str]:
    errors: list[str] = []
    if not rows:
        return ["行がない（先頭行は列名: " + ",".join(COLUMNS) + "）"]
    cols = list(rows[0].keys())
    missing = [c for c in COLUMNS if c not in cols]
    if missing:
        errors.append(f"列が足りない: {', '.join(missing)}（列は {', '.join(COLUMNS)}）")
        return errors
    seen = Counter(r["id"] for r in rows)
    for n, r in enumerate(rows, 2):   # 2 = 先頭行の次
        where = f"{n}行目 {r['id'] or '(idなし)'}"
        if not ID_RE.match(r["id"]):
            errors.append(f"{where}: id は英字で始まる英数字（例 C1）")
        elif seen[r["id"]] > 1:
            errors.append(f"{where}: id が重複")
        if not r["claim"]:
            errors.append(f"{where}: claim が空")
        if r["status"] not in STATUSES:
            errors.append(f"{where}: status は {'/'.join(STATUSES)} のどれか: {r['status']!r}")
        if r["target"] not in TARGETS:
            errors.append(f"{where}: target は {'/'.join(TARGETS)} のどれか: {r['target']!r}")
        if r["status"] in ("事実", "決定") and not r["evidence"]:
            errors.append(f"{where}: {r['status']} には evidence（測定・決めた人と日付）が要る")
        if r["status"] not in ("提案", "未決", "決定") and not (r["doc"] and r["section"]):
            errors.append(f"{where}: 原文の doc と section を書く（原文に無い主張なら status を 提案 か 未決 に）")
    return errors


def summary(rows: list[dict[str, str]]) -> str:
    c = Counter(r["status"] for r in rows)
    return "、".join(f"{s} {c[s]}" for s in STATUSES if c[s])


def main() -> int:
    if len(sys.argv) < 2:
        print(__doc__)
        return 2
    worst = 0
    for arg in sys.argv[1:]:
        p = Path(arg)
        rows = load(p)
        errors = validate(rows)
        for e in errors:
            print(f"BLOCK   {p}: {e}")
        print(f"-- {p}: {len(rows)}件（{summary(rows)}）/ block {len(errors)}")
        for r in rows:
            if r["status"] == "未決":
                print(f"   未決 {r['id']}: {r['claim']}（決める: {r['owner'] or '担当未記入'}）")
        if errors:
            worst = 2
    return worst


if __name__ == "__main__":
    sys.exit(main())
