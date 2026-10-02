#!/usr/bin/env python3
"""設計書の冗長さの検査。標準ライブラリのみ。check_doc.py から使う（単体でも動く）。

文章を「段落・箇条書きの1項目・引用」の単位に分け、次を数える。表・コード（Mermaid）・見出し・HTML コメントは数えない。
  一般論・前置き・ヘッジ（references/ng_doc.md と slides の ng_words.md の辞書）
  削除候補: 数字・主張ID（C1）・§・`コード`・「固有の語」・[要確認] のどれも無く、一般論・前置き・ヘッジだけの単位
  同じ文の繰り返し（文書内）、同じフォルダの別の設計書と同じ文（文書間）

使い方:
  python3 verbosity.py design/_source/ops.md            # 削除候補と一般論の多い段落の一覧（原文に使う）
  python3 verbosity.py --original design/_source/ops.md design/ops.md   # 原文と書き直しの字数・段落数・一般論の比較
"""
from __future__ import annotations

import argparse
import re
import sys
from collections import Counter
from dataclasses import dataclass, field
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent.parent / "slides" / "scripts"))
from lint_slides import load_ng_words, strip_md, zen_len  # noqa: E402

NG_FILES = (HERE.parent.parent / "slides" / "references" / "ng_words.md", HERE.parent / "references" / "ng_doc.md")
FILLER_CLASSES = ("generic", "meta", "hedge")

# 閾値（初期値。最初の数文書で較正する）
LIMITS = {
    "unit_chars_warn": 200,       # 1段落（箇条書きは1項目）の字数
    "section_chars_warn": 1000,   # 1つの章（見出しから次の見出しまで）の文章の字数
    "filler_per_unit_warn": 2,    # 中身のある段落でも、一般論・前置き・ヘッジがこの数以上なら warning
    "filler_density_warn": 3.0,   # 文章1000字あたりの一般論・前置き・ヘッジ
    "dup_sentence_chars": 20,     # 文書内で同じ文（この字数以上）が2回出たら block
    "cross_dup_chars": 30,        # 同じフォルダの別の設計書と同じ文（この字数以上）なら block
}

INFO_RE = re.compile(r"[0-9０-９]|(?<![A-Za-z0-9_-])C\d+(?![A-Za-z0-9_-])|§|`[^`]+`|\[要確認\]|「[^」]+」")
QUOTE_RE = re.compile(r"「[^」]*」")
ITEM_RE = re.compile(r"^\s*([-*+]|\d+[.)])\s+")
SENT_SPLIT_RE = re.compile(r"(?<=[。！？])")


@dataclass
class Unit:
    line: int
    kind: str          # para / item / quote
    raw: str
    section: str

    @property
    def text(self) -> str:
        return strip_md(self.raw)


@dataclass
class Finding:
    severity: str      # block / warning
    line: int
    rule: str
    message: str


@dataclass
class Metrics:
    chars: float = 0.0
    units: int = 0
    filler: int = 0
    candidates: int = 0
    duplicates: int = 0
    fillers: Counter = field(default_factory=Counter)

    def fmt(self) -> str:
        return (f"文章 {self.chars:.0f}字・段落 {self.units}・一般論等 {self.filler}・削除候補 {self.candidates}・"
                f"繰り返し {self.duplicates}")


def load_ng() -> dict[str, list[re.Pattern]]:
    ng: dict[str, list[re.Pattern]] = {}
    for f in NG_FILES:
        for cls, pats in load_ng_words(f).items():
            ng.setdefault(cls, []).extend(pats)
    return ng


def units(lines: list[str]) -> list[Unit]:
    """段落・箇条書きの1項目・引用を取り出す。表・コード・見出し・HTML コメント・画像は除く。"""
    out: list[Unit] = []
    buf: list[str] = []
    start, kind, section = 0, "para", ""
    fence: str | None = None
    in_comment = False

    def flush():
        nonlocal buf
        text = " ".join(x for x in buf if x).strip()
        if text:
            out.append(Unit(start, kind, text, section))
        buf = []

    for i, raw in enumerate(lines, 1):
        s = raw.strip()
        if fence:
            if s.startswith(fence) and s.strip(fence[0]) == "":
                fence = None
            continue
        m = re.match(r"^(`{3,}|~{3,})", s)
        if m:
            flush()
            fence = m.group(1)
            continue
        if in_comment:
            if "-->" in s:
                in_comment = False
            continue
        if s.startswith("<!--"):
            flush()
            if "-->" not in s:
                in_comment = True
            continue
        s = re.sub(r"<!--.*?-->", "", s).strip()
        if not s:
            flush()
            continue
        h = re.match(r"^(#{1,6})\s+(.*)$", s)
        if h:
            flush()
            section = h.group(2).strip()
            continue
        if s.startswith(("|", "![", "<")):
            flush()
            continue
        if ITEM_RE.match(raw):
            flush()
            start, kind, buf = i, "item", [ITEM_RE.sub("", s)]
            continue
        if s.startswith(">"):
            if kind != "quote" or not buf:
                flush()
                start, kind = i, "quote"
            buf.append(s.lstrip(">").strip())
            continue
        if buf and kind == "item" and raw[:1] in (" ", "\t"):
            buf.append(s)          # 箇条書きの続きの行
            continue
        if not buf or kind != "para":
            flush()
            start, kind = i, "para"
        buf.append(s)
    flush()
    return out


def filler_hits(text: str, ng: dict[str, list[re.Pattern]]) -> list[tuple[str, str]]:
    t = QUOTE_RE.sub("", text)
    return [(cls, m.group(0)) for cls in FILLER_CLASSES for p in ng.get(cls, []) for m in p.finditer(t)]


def has_info(unit: Unit) -> bool:
    return bool(INFO_RE.search(unit.raw))


def sentences(unit: Unit) -> list[str]:
    return [re.sub(r"\s+", "", s) for s in SENT_SPLIT_RE.split(unit.text) if s.strip()]


def analyze(path: Path, ng: dict[str, list[re.Pattern]] | None = None, siblings: bool = True):
    """(findings, metrics, candidates) を返す。candidates は [(Unit, 理由)]。"""
    ng = ng if ng is not None else load_ng()
    us = units(path.read_text(encoding="utf-8").splitlines())
    findings: list[Finding] = []
    metrics = Metrics(units=len(us))
    candidates: list[tuple[Unit, str]] = []
    section_chars: Counter = Counter()
    section_line: dict[str, int] = {}

    for u in us:
        n = zen_len(u.text)
        metrics.chars += n
        section_chars[u.section] += n
        section_line.setdefault(u.section, u.line)
        hits = filler_hits(u.text, ng)
        metrics.filler += len(hits)
        metrics.fillers.update(w for _, w in hits)
        words = "、".join(dict.fromkeys(w for _, w in hits))
        if hits and not has_info(u):
            metrics.candidates += 1
            candidates.append((u, f"中身の語が無く、一般論・前置き・ヘッジだけ（{words}）"))
            findings.append(Finding("block", u.line, "filler-only",
                                    f"削除候補: 数字・担当の固有名「」・主張ID・§ のどれも無く、一般論・前置き・ヘッジだけの段落（{words}）。"
                                    "誰が・いつ・何を・どの値で、に書き換えられなければ段落ごと削る"))
        elif len(hits) >= LIMITS["filler_per_unit_warn"]:
            candidates.append((u, f"一般論・前置き・ヘッジが{len(hits)}個（{words}）"))
            findings.append(Finding("warning", u.line, "filler",
                                    f"一般論・前置き・ヘッジが{len(hits)}個（{words}）。中身の文だけ残す"))
        for p in ng.get("buzzword", []):
            m = p.search(QUOTE_RE.sub("", u.text))
            if m:
                findings.append(Finding("warning", u.line, "buzzword", f"`{m.group(0)}`。具体的な対象・数値に置き換える"))
                break
        if n > LIMITS["unit_chars_warn"]:
            findings.append(Finding("warning", u.line, "unit-long",
                                    f"段落が全角{n:.0f}字 > {LIMITS['unit_chars_warn']}字。1段落1論点にし、条件の列挙は表にする"))

    for sec, n in section_chars.items():
        if n > LIMITS["section_chars_warn"]:
            findings.append(Finding("warning", section_line[sec], "section-long",
                                    f"章「{sec or '(冒頭)'}」の文章が全角{n:.0f}字 > {LIMITS['section_chars_warn']}字。"
                                    "表・図に移すか、節に分ける"))
    if metrics.chars >= 300 and metrics.filler / (metrics.chars / 1000) > LIMITS["filler_density_warn"]:
        findings.append(Finding("warning", 1, "filler-density",
                                f"一般論・前置き・ヘッジが文章1000字あたり{metrics.filler / (metrics.chars / 1000):.1f}個"
                                f" > {LIMITS['filler_density_warn']}個（多い語: "
                                + "、".join(w for w, _ in metrics.fillers.most_common(5)) + "）"))

    # 文書内の繰り返し
    seen: dict[str, int] = {}
    for u in us:
        for s in sentences(u):
            if zen_len(s) < LIMITS["dup_sentence_chars"]:
                continue
            if s in seen and seen[s] != u.line:
                metrics.duplicates += 1
                candidates.append((u, f"{seen[s]}行目と同じ文"))
                findings.append(Finding("block", u.line, "dup-sentence",
                                        f"{seen[s]}行目と同じ文を繰り返している（「{s[:24]}…」）。正本の1か所だけ残し、ほかは参照にする"))
            else:
                seen.setdefault(s, u.line)

    # 同じフォルダの別の設計書と同じ文（共通事項の複製）
    if siblings:
        for other in sorted(path.parent.glob("*.md")):
            if other.resolve() == path.resolve() or other.name.startswith("_"):
                continue
            theirs = {s for ou in units(other.read_text(encoding="utf-8").splitlines()) for s in sentences(ou)
                      if zen_len(s) >= LIMITS["cross_dup_chars"]}
            for u in us:
                for s in sentences(u):
                    if s in theirs:
                        findings.append(Finding("block", u.line, "cross-dup",
                                                f"{other.name} と同じ文（「{s[:24]}…」）。共通事項は正本の1か所に書き、"
                                                "ほかの文書は「基本設計 §4.2」のように参照する"))
                        break
    return findings, metrics, candidates


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("files", nargs="+", type=Path)
    ap.add_argument("--original", type=Path, help="原文。書き直しと字数・段落数・一般論を比べる")
    args = ap.parse_args()
    ng = load_ng()
    if args.original:
        _, m0, _ = analyze(args.original, ng, siblings=False)
        print(f"原文   {args.original}: {m0.fmt()}")
    for f in args.files:
        findings, m, cands = analyze(f, ng, siblings=not args.original)
        print(f"{'書き直し' if args.original else '検査'} {f}: {m.fmt()}")
        if args.original and m0.chars:
            print(f"  原文比: 文章 {m.chars / m0.chars:.0%}・段落 {m.units}/{m0.units}・一般論等 {m.filler}/{m0.filler}・"
                  f"削除候補 {m.candidates}/{m0.candidates}")
        for u, why in cands:
            print(f"  {u.line:4}行 [{why}] {u.text[:60]}{'…' if len(u.text) > 60 else ''}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
