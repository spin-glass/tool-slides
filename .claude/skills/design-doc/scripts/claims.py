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
任意の列（無くてもよい。あれば出典と照らす）:
  path     出典のファイルのパス（~ 可。相対パスは claims.csv のフォルダから）。本人の発言・会議なら空
  rev      出典を読んだときのコミット（短いハッシュ）
  quote    出典の該当文をそのまま写したもの。限定句（の面では・ただし・未決…）を落とさない
  terms    デックの語と原文の語の対応（「誤り=学習ラベルの誤り; 保留=確信度が低い」）。同じなら「同じ」。
           この列があれば、target が deck / both の行の空欄を warning にする（設計書に無い語の発明を表で止める）

出典と照らす検査（path があるとき）:
  block   quote-not-found     空白・* ・` を除いて比べても、quote が今の path に無い
  block   source-changed      rev より後に path が変わっている（git log <rev>..HEAD -- <path>）
  block   quote-missing       path があるのに quote が無い（状態が 事実・方針・想定・参考値・決定 のとき）
  warning source-dirty        path に未コミットの変更がある
  warning qualifier-dropped   quote にある限定の語が claim に無い（の面では・限り・ただし・場合・前提・未決・見込み・
                              想定・仮・目安・約・以上・未満・まで・だけ・のみ・暫定）

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
import subprocess
import sys
from collections import Counter
from pathlib import Path

COLUMNS = ["id", "doc", "section", "claim", "status", "evidence", "owner", "target", "note"]
STATUSES = ("事実", "参考値", "方針", "想定", "提案", "決定", "未決")
TARGETS = ("doc", "deck", "both", "none")
ID_RE = re.compile(r"^[A-Za-z][A-Za-z0-9_-]*$")
SOURCE_COLUMNS = ["path", "rev", "quote"]      # 任意の列
TERMS_RE = re.compile(r"^\s*(同じ|[^=;]+=[^=;]+(?:\s*;\s*[^=;]+=[^=;]+)*)\s*;?\s*$")
QUOTE_REQUIRED = ("事実", "方針", "想定", "参考値", "決定")
# 出典の文の射程を決める限定の語。claim に写すときに最初に落ちる（「処理能力の面では足りる」→「足りる」）
QUALIFIERS = [(w, re.compile(p)) for w, p in (
    ("の面では", r"の面では"), ("限り", r"限り"), ("ただし", r"ただし|但し"), ("場合", r"場合"), ("前提", r"前提"),
    ("未決", r"未決"), ("見込み", r"見込み"), ("想定", r"想定"), ("仮", r"仮(?!説)"), ("目安", r"目安"),
    ("約", r"約(?=\s*[0-9０-９])"), ("以上", r"以上"), ("未満", r"未満"), ("まで", r"まで"), ("だけ", r"だけ"),
    ("のみ", r"のみ"), ("暫定", r"暫定"))]


def _norm(text: str) -> str:
    """quote と出典を比べるための正規化: 空白（改行を含む）・* ・` を除く。"""
    return re.sub(r"[\s*`]", "", text)


def _source(r: dict[str, str], base: Path | None) -> Path | None:
    raw = r.get("path", "")
    if not raw:
        return None
    p = Path(raw).expanduser()
    return p if p.is_absolute() or base is None else base / p


def _git(path: Path, *args: str) -> subprocess.CompletedProcess:
    return subprocess.run(["git", "-C", str(path.parent), *args], capture_output=True, text=True)


def source_checks(rows: list[dict[str, str]], base: Path | None) -> tuple[list[str], list[str]]:
    """出典（path・rev・quote）と照らした (block, warning)。path の列が無い表は何もしない。"""
    errors: list[str] = []
    warns: list[str] = []
    for n, r in enumerate(rows, 2):
        src = _source(r, base)
        if src is None:
            continue
        where = f"{n}行目 {r.get('id')}"
        quote = r.get("quote", "")
        if not quote:
            if r.get("status") in QUOTE_REQUIRED:
                errors.append(f"{where}: quote-missing: path があるのに quote が無い。出典の該当文をそのまま quote に写す"
                              "（claim だけでは、限定句が落ちたか・出典が変わったかを確かめられない）")
            continue
        if not src.is_file():
            errors.append(f"{where}: quote-not-found: 出典のファイルが無い: {src}")
            continue
        if _norm(quote) not in _norm(src.read_text(encoding="utf-8", errors="replace")):
            errors.append(f"{where}: quote-not-found: quote「{quote[:40]}」が今の {src.name} に無い。出典を読み直し、"
                          "quote を今の文に写し直して claim を確かめる")
        rev = r.get("rev", "")
        inside = _git(src, "rev-parse", "--is-inside-work-tree").returncode == 0
        if rev and inside:
            log = _git(src, "log", "--format=%h %s", f"{rev}..HEAD", "--", src.name)
            if log.returncode != 0:
                errors.append(f"{where}: source-changed: rev {rev} が {src.name} のリポジトリに無い。出典を読んだときのコミットを書く")
            elif log.stdout.strip():
                commits = log.stdout.strip().splitlines()
                errors.append(f"{where}: source-changed: {src.name} は rev {rev} の後に{len(commits)}回変わった"
                              f"（最初: {commits[-1]}）。出典を読み直して quote と claim を確かめ、rev を今のコミットにする")
        if inside and _git(src, "status", "--porcelain", "--", src.name).stdout.strip():
            warns.append(f"{where}: source-dirty: {src.name} に未コミットの変更がある。コミットしてから rev を書く")
        dropped = [w for w, pat in QUALIFIERS if pat.search(quote) and not pat.search(r.get("claim", ""))]
        if dropped:
            warns.append(f"{where}: qualifier-dropped: quote の限定の語（{'・'.join(dropped)}）が claim に無い。"
                         "限定句は claim に残し、限定の外側の事柄は別の行にする")
    return errors, warns


def load(path: Path) -> list[dict[str, str]]:
    with open(path, encoding="utf-8", newline="") as f:
        rows = list(csv.DictReader(f))
    return [{k: (v or "").strip() for k, v in r.items() if k is not None} for r in rows]


def validate(rows: list[dict[str, str]], base: Path | None = None) -> list[str]:
    """block の一覧。base（claims.csv のフォルダ）を渡すと、path・rev・quote の列で出典とも照らす。"""
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
    if base is not None and "path" in cols:
        errors += source_checks(rows, base)[0]
    return errors


def warnings(rows: list[dict[str, str]], base: Path | None = None) -> list[str]:
    """止めないが直すもの。base を渡すと、出典の未コミットの変更と、claim で落ちた限定の語も知らせる。"""
    out = source_checks(rows, base)[1] if base is not None and rows and "path" in rows[0] else []
    has_terms = bool(rows) and "terms" in rows[0]
    for n, r in enumerate(rows, 2):
        if has_terms and r.get("target") in ("deck", "both"):
            t = r.get("terms", "")
            if not t:
                out.append(f"{n}行目 {r.get('id')}: terms が空。デックで使う語と原文の語の対応を「デックの語=原文の語」で書く（同じなら「同じ」）。"
                           "原文に無い語をデックで作らない")
            elif not TERMS_RE.match(t):
                out.append(f"{n}行目 {r.get('id')}: terms は「デックの語=原文の語」を ; で区切る（同じなら「同じ」）: {t!r}")
        if r.get("status") in ("未決", "提案") and not r.get("owner"):
            out.append(f"{n}行目 {r.get('id')}: {r.get('status')} に決める担当（owner）が無い。原文に無ければ「原文に無い」と書く（仮の担当は note に「仮: 総務課長」と書き、報告で確かめる）")
    return out


def summary(rows: list[dict[str, str]]) -> str:
    c = Counter(r["status"] for r in rows)
    return "、".join(f"{s} {c[s]}" for s in STATUSES if c[s])


def main() -> int:
    if len(sys.argv) < 2 or any(a in ("-h", "--help") for a in sys.argv[1:]):
        print(__doc__)
        return 0 if len(sys.argv) >= 2 else 2
    worst = 0
    for arg in sys.argv[1:]:
        p = Path(arg)
        rows = load(p)
        errors = validate(rows, p.parent)
        for e in errors:
            print(f"BLOCK   {p}: {e}")
        for w in warnings(rows, p.parent):
            print(f"WARNING {p}: {w}")
        print(f"-- {p}: {len(rows)}件（{summary(rows)}）/ block {len(errors)}")
        for r in rows:
            if r["status"] == "未決":
                print(f"   未決 {r['id']}: {r['claim']}（決める: {r['owner'] or '担当未記入'}）")
        if errors:
            worst = 2
    return worst


if __name__ == "__main__":
    sys.exit(main())
