#!/usr/bin/env python3
"""設計書の構造（読む路）の検査。標準ライブラリのみ。check_doc.py から使う（単体でも動く）。

冗長さ（verbosity.py）を0にしても、構造が同じなら読む気は戻らない。章（番号つきの最上位の見出し）ごとに
読む字数・表の割合・型（文・表・図・箇条書きの並び）・章参照・要件IDを数え、次を見つける（すべて warning）。
  front-matter-long   本文の中身が始まるまでの前置き（冒頭の表と、文書の説明の章・引く表の章）が 1000字超
  summary-missing     要点の章（§1）が無い、または文書の説明の章になっている（長い文書だけ）
  summary-rows        §1 の表が 8行以上（未決の全一覧を §1 に置いている）
  reference-in-path   引く表の章（表が7割以上・1つの表が10行以上）が読む路の途中にある
  same-shape          同じ型の章が3章以上続く（長い文書だけ）
  path-long           読み通す章（引く表の章と付録を除く）の合計が 6000字超
  reader-entry        冒頭の表の「読む人」が2者以上なのに、それぞれが読む章（§）を添えていない
  undecided-at-end    未決の一覧の章が末尾にあり、本文から3回以上参照される
  ref-share           本文の段落の半分超が本書の別の章を参照している（§1・同じ章・他の文書への参照は数えない）
  opaque-id           要件ID（FR-001 の形）が本文に5回以上（付録は除く）
区分: 冒頭／要点（§1）／前置き（文書の説明）／引く表／本文／付録。閾値は verbosity.py の LIMITS。

使い方:
  python3 structure.py design/_source/ops.md     # 章ごとの表と、見つけたこと（check_doc.py --structure と同じ）
"""
from __future__ import annotations

import re
import sys
from dataclasses import dataclass
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
import verbosity  # noqa: E402
from verbosity import LIMITS, Finding, strip_md, zen_len  # noqa: E402

RULES = frozenset(("front-matter-long", "summary-missing", "summary-rows", "reference-in-path", "same-shape",
                   "path-long", "reader-entry", "undecided-at-end", "ref-share", "opaque-id"))
REF_RE = re.compile(r"§\s*(?P<a>\d+(?:\.\d+)*)|(?P<b>\d+(?:\.\d+)+)節|第(?P<c>\d+)章")
# 参照の直前12字か直後6字にこれらがあれば、他の文書への参照（「基本設計 §5.1」「原文 §3.2」「§12 は原文に無い」）
DOC_WORDS = ("原文", "基本設計", "処理設計", "ML設計", "精度検証", "運用・移行", "運用設計", "移行設計", "設計書", "文書", "仕様書", "マニュアル")
OPAQUE_ID_RE = re.compile(r"(?<![A-Za-z0-9])[A-Z]{2,4}-\d{2,}(?:-[A-Z0-9]+)*(?![A-Za-z0-9])")
APPENDIX_RE = re.compile(r"^(付録|参考|用語|変更履歴|改訂履歴|別紙|別表)")
# 文書についての説明の章。「対象と範囲」「背景」は中身（何を変えるか）のことが多いので入れない
META_HEADING_RE = re.compile(r"位置づけ|位置付け|読み方|文書の構成|本書の構成|構成と読み方|文書一覧|関連文書|参照文書|参考文書|"
                             r"用語|記法|凡例|はじめに|本書について|この文書について|要件対応|要件との対応|章の対応|トレーサビリティ")
UNDECIDED_HEADING_RE = re.compile(r"未確定|未決|まだ決めていない|決まっていない|未定")
NAV_HEADER_RE = re.compile(r"正本|§|章|箇所|出所|出典|参照|本書")      # 参照を置くための列（数えない）
READER_ROW_RE = re.compile(r"読む人|読者")
HEADING_RE = re.compile(r"^(#{1,6})\s+(.*?)\s*$")
NUMBERED_RE = re.compile(r"^(\d+(?:\.\d+)*)\.?\s+")
FENCE_RE = re.compile(r"^(`{3,}|~{3,})\s*\{?(\w*)")
SEP_RE = re.compile(r"^\|\s*:?-{3,}")


@dataclass
class Chapter:
    line: int
    num: str
    title: str
    chars: float = 0.0       # 文章
    table: float = 0.0       # 表のセル
    figure: float = 0.0      # 図のラベル
    units: int = 0
    meta_units: int = 0      # 文書についての前置きの語を含む段落
    rows_max: int = 0        # いちばん大きい表の行数（見出し行を除く）
    shape: str = ""          # 文→表→文 のような並び
    refs: int = 0            # 章参照（§1・同じ章への参照と、正本・箇所の列は除く）
    ref_units: int = 0       # 本書の別の章を参照する段落（§1・同じ章・他の文書への参照は除く）
    ids: int = 0             # 要件ID（FR-001 の形）
    id_example: str = ""
    kind: str = "本文"       # 冒頭 / 要点 / 前置き / 引く表 / 本文 / 付録

    @property
    def read(self) -> float:
        return self.chars + self.table + self.figure

    @property
    def share(self) -> float:
        return self.table / self.read if self.read else 0.0

    @property
    def label(self) -> str:
        return f"§{self.num} {self.title}" if self.num else self.title


def headings(lines: list[str]) -> list[tuple[int, int, str, str]]:
    """(0始まりの行, レベル, 番号, 番号を除いた題)。コードの中は見ない。"""
    out = []
    fence: str | None = None
    for i, raw in enumerate(lines):
        s = raw.strip()
        if fence:
            if s.startswith(fence) and s.strip(fence[0]) == "":
                fence = None
            continue
        m = FENCE_RE.match(s)
        if m:
            fence = m.group(1)
            continue
        h = HEADING_RE.match(raw)
        if h:
            title = h.group(2)
            n = NUMBERED_RE.match(title)
            out.append((i, len(h.group(1)), n.group(1) if n else "", NUMBERED_RE.sub("", title).strip()))
    return out


def yaml_end(lines: list[str]) -> int:
    if lines and lines[0].strip() == "---":
        return next((i for i in range(1, len(lines)) if lines[i].strip() in ("---", "...")), 0) + 1
    return 0


def visible_lines(body: list[str]):
    """コード・HTML コメント・見出しを除いた行を (表か, 文字列) で返す。空行は (False, '')。"""
    fence: str | None = None
    in_comment = False
    for raw in body:
        s = raw.strip()
        if fence:
            if s.startswith(fence) and s.strip(fence[0]) == "":
                fence = None
            continue
        if FENCE_RE.match(s):
            fence = FENCE_RE.match(s).group(1)
            continue
        if in_comment:
            if "-->" not in s:
                continue
            in_comment = False
            s = s.split("-->", 1)[1].strip()
        if "<!--" in s and "-->" not in s.split("<!--", 1)[1]:
            in_comment = True
            s = s.split("<!--", 1)[0].strip()
        s = re.sub(r"<!--.*?-->", "", s).strip()
        if s.startswith("#"):
            s = ""
        yield s.startswith("|"), s, raw


def shape_of(body: list[str]) -> str:
    """章の要素の並び（文・表・図・箇条書き・コード）。同じ要素が続く分は1つにまとめる。"""
    seq: list[str] = []

    def push(k: str):
        if not seq or seq[-1] != k:
            seq.append(k)

    fence: str | None = None
    in_comment = False
    for raw in body:
        s = raw.strip()
        if fence:
            if s.startswith(fence) and s.strip(fence[0]) == "":
                fence = None
            continue
        m = FENCE_RE.match(s)
        if m:
            fence = m.group(1)
            push("図" if m.group(2) == "mermaid" else "コード")
            continue
        if in_comment:
            if "-->" in s:
                in_comment = False
            continue
        if s.startswith("<!--"):
            if "-->" not in s:
                in_comment = True
            continue
        s = re.sub(r"<!--.*?-->", "", s).strip()
        if not s or s.startswith("#"):
            continue
        if s.startswith("|"):
            push("表")
        elif s.startswith(("![", "<img")):
            push("図")
        elif verbosity.ITEM_RE.match(raw):
            push("箇条書き")
        elif raw[:1] in (" ", "\t") and seq and seq[-1] == "箇条書き":
            continue                        # 箇条書きの続きの行
        else:
            push("文")
    return "→".join(seq)


def refs_and_ids(body: list[str], own: str) -> tuple[int, int, str]:
    """章参照と要件IDの数。§1・同じ章（own）への参照、表の見出し行、参照を置くための列は数えない。"""
    refs = ids = 0
    example = ""
    nav: dict[int, bool] = {}
    prev_table = False
    for is_table, s, _ in visible_lines(body):
        if not s:
            prev_table = False
            continue
        if is_table:
            if SEP_RE.match(s):
                continue
            cells = [c.strip() for c in s.strip("|").split("|")]
            if not prev_table:
                nav = {k: bool(NAV_HEADER_RE.search(c)) for k, c in enumerate(cells)}
                prev_table = True
                continue
            texts = [c for k, c in enumerate(cells) if not nav.get(k)]
        else:
            prev_table = False
            texts = [s]
        for t in texts:
            for m in OPAQUE_ID_RE.finditer(t):
                ids += 1
                example = example or m.group(0)
            for m in REF_RE.finditer(t):
                num = m.group("a") or m.group("b") or m.group("c")
                top = num.split(".")[0]
                if top == "1" or (own and top == own):
                    continue
                refs += 1
    return refs, ids, example


def is_external(text: str, m: re.Match) -> bool:
    before, after = text[max(0, m.start() - 12):m.start()], text[m.end():m.end() + 6]
    return any(w in before or w in after for w in DOC_WORDS)


def ref_unit_count(us: list[verbosity.Unit], own: str) -> int:
    """本書の別の章を参照する段落の数。§1・同じ章・他の文書への参照と、「」の中は数えない。"""
    n = 0
    for u in us:
        t = verbosity.QUOTE_RE.sub("", u.text)
        for m in REF_RE.finditer(t):
            top = (m.group("a") or m.group("b") or m.group("c")).split(".")[0]
            if top == "1" or (own and top == own) or is_external(t, m):
                continue
            n += 1
            break
    return n


def measure(ch: Chapter, body: list[str], ng: dict[str, list[re.Pattern]]) -> Chapter:
    us = verbosity.units([""] + body)             # 先頭を空行にして、本文の「---」を YAML と取り違えない
    own = ch.num.split(".")[0] if ch.num else ""
    ch.units = len(us)
    ch.chars = sum(zen_len(u.text) for u in us)
    meta = ng.get("meta", [])
    ch.meta_units = sum(1 for u in us if any(p.search(verbosity.QUOTE_RE.sub("", u.text)) for p in meta))
    ch.ref_units = ref_unit_count(us, own)
    ch.table, ch.figure = verbosity.table_and_figure_chars(body)
    ch.rows_max = max((len(rows) - 1 for _, rows in verbosity.tables(body)), default=0)
    ch.shape = shape_of(body)
    ch.refs, ch.ids, ch.id_example = refs_and_ids(body, own)
    return ch


def classify(ch: Chapter) -> str:
    if APPENDIX_RE.match(ch.title):
        return "付録"
    if META_HEADING_RE.search(ch.title):
        return "前置き"
    if ch.num == "1":
        return "要点"                     # 題が文書の説明でなければ、§1 は位置で要点とみなす（長い §1 は summary-long が知らせる）
    if ch.units >= 3 and ch.meta_units * 3 >= ch.units * 2:
        return "前置き"                   # 段落の3分の2以上が「本書は」「本節では」の説明
    if ch.read and ch.share >= LIMITS["ref_table_share"] and ch.rows_max >= LIMITS["ref_table_rows"]:
        return "引く表"
    return "本文"


def split(lines: list[str], ng: dict[str, list[re.Pattern]]) -> tuple[Chapter, list[Chapter], list[tuple[int, int, str, str]]]:
    """(冒頭, 章の一覧, 全見出し)。章は番号つきの見出しのうち最上位のレベルで切る（無ければ ##）。"""
    hs = headings(lines)
    start = yaml_end(lines)
    levels = [lv for _, lv, num, _ in hs if num and "." not in num]
    level = min(levels) if levels else 2
    heads = [(i, num, title) for i, lv, num, title in hs if lv == level]
    pre_end = heads[0][0] if heads else len(lines)
    pre = measure(Chapter(start + 1, "", "(冒頭)"), lines[start:pre_end], ng)
    pre.kind = "冒頭"
    chapters: list[Chapter] = []
    for k, (i, num, title) in enumerate(heads):
        end = heads[k + 1][0] if k + 1 < len(heads) else len(lines)
        ch = measure(Chapter(i + 1, num, title), lines[i + 1:end], ng)
        ch.kind = classify(ch)
        chapters.append(ch)
    return pre, chapters, hs


def longest_same_shape(chapters: list[Chapter]) -> list[Chapter]:
    best: list[Chapter] = []
    run: list[Chapter] = []
    for c in chapters:
        if c.kind == "付録" or not c.shape:
            run = []
            continue
        run = run + [c] if run and c.shape == run[-1].shape else [c]
        if len(run) > len(best):
            best = list(run)
    return best


def analyze(path: Path, ng: dict[str, list[re.Pattern]] | None = None):
    """(findings, 冒頭, 章の一覧) を返す。"""
    ng = ng if ng is not None else verbosity.load_ng()
    lines = path.read_text(encoding="utf-8").splitlines()
    pre, chapters, hs = split(lines, ng)
    findings: list[Finding] = []
    total = pre.read + sum(c.read for c in chapters)
    long = total >= LIMITS["short_doc_chars"]
    lim = LIMITS

    # 前置き: 冒頭と、文書の説明・引く表の章が、本文の中身まで続く分
    front = [pre]
    for c in chapters:
        if c.kind not in ("前置き", "引く表"):
            break
        front.append(c)
    first = next((c for c in chapters if c.kind in ("要点", "本文")), None)
    front_chars = sum(c.read for c in front)
    if first and front_chars > lim["front_matter_chars"]:
        names = "、".join(c.label for c in front[1:]) or "冒頭の表"
        findings.append(Finding("warning", front[1].line if len(front) > 1 else pre.line, "front-matter-long",
                                f"本文の中身（{first.label}）が始まるまでに {front_chars:.0f}字（{names}）> {lim['front_matter_chars']}字。"
                                "冒頭に置くのは「扱うこと／読む人／原文／状態」の表と §1 の要点だけ。文書の説明は要点1〜2行に縮め、"
                                "引く表は付録へ移す（ここで多くの読み手が降りる）"))

    # 要点の章
    c1 = next((c for c in chapters if c.num == "1"), None)
    if long and (c1 is None or c1.kind != "要点"):
        why = "無い" if c1 is None else f"文書の説明（{c1.label}）になっている"
        findings.append(Finding("warning", c1.line if c1 else (chapters[0].line if chapters else 1), "summary-missing",
                                f"要点の章（§1）が{why}。先頭の章に、何を変えるか・次へ進む条件（値）・まだ決めていない点（件数）・"
                                "決めたこと、の4行を置く"))
    if c1 and c1.kind == "要点" and c1.rows_max > lim["summary_rows_warn"]:
        findings.append(Finding("warning", c1.line, "summary-rows",
                                f"§1 の表が {c1.rows_max}行 > {lim['summary_rows_warn']}行。判断に関わる行（次へ進む条件に関わる未決・矛盾）だけ残し、"
                                "残りは付録「未決の一覧」へ移して、§1 には件数と付録の参照を書く"))

    # 引く表の章が読む路の途中にある
    for k, c in enumerate(chapters):
        if c.kind != "引く表":
            continue
        later = [d for d in chapters[k + 1:] if d.kind in ("要点", "本文")]
        if later:
            span = f"§{later[0].num}" + (f"〜§{later[-1].num}" if len(later) > 1 else "")
            findings.append(Finding("warning", c.line, "reference-in-path",
                                    f"引くための表の章「{c.label}」（表 {c.share:.0%}・{c.rows_max}行）が読む路の途中にある（あとに {span} が続く）。"
                                    "付録へ移し、本文からは「付録B」と参照する"))

    # 同じ型の章が続く
    run = longest_same_shape(chapters)
    if long and len(run) >= lim["same_shape_run"]:
        findings.append(Finding("warning", run[0].line, "same-shape",
                                f"§{run[0].num}〜§{run[-1].num} の{len(run)}章が同じ型「{run[0].shape}」。章の問いに合わせて型を変える"
                                "（判断・分岐の章は図を主役に、担当×周期の取り決めは表、順序は工程表、2案の差は対照表）。"
                                "同じ手触りが続くと、読み手は進んでいる感覚を失う"))

    # 読み通す章の合計
    path_read = sum(c.read for c in chapters if c.kind in ("要点", "本文"))
    if path_read > lim["path_chars_warn"]:
        heavy = sorted((c for c in chapters if c.kind == "本文" and c.share >= 0.5), key=lambda c: -c.table)[:3]
        hint = ("表の割合が高い章（" + "、".join(f"{c.label} {c.share:.0%}" for c in heavy) + "）を付録へ出すか、") if heavy else ""
        findings.append(Finding("warning", 1, "path-long",
                                f"読み通す章の合計が {path_read:.0f}字 > {lim['path_chars_warn']}字（引く表の章と付録を除く）。1回で読める量を超える。"
                                f"{hint}読む人ごとに分冊する"))

    # 読む人が複数なら、それぞれが読む章
    pre_lines = lines[yaml_end(lines):(chapters[0].line - 1 if chapters else len(lines))]
    for start, rows in verbosity.tables(pre_lines):
        for row in rows:
            if len(row) >= 2 and READER_ROW_RE.search(row[0]):
                cell = strip_md(row[1])
                plain = re.sub(r"（[^）]*）|\([^)]*\)", "", cell).split("。")[0]      # 読む人は最初の文に並ぶ
                readers = [x.strip() for x in re.split(r"[・、,，/／]|と、|および|及び|ならびに", plain) if x.strip()]
                if len(readers) >= 2 and cell.count("§") < 2:
                    findings.append(Finding("warning", yaml_end(lines) + start, "reader-entry",
                                            f"読む人が{len(readers)}者（{'・'.join(r[:10] for r in readers[:4])}）なのに、それぞれが読む章が無い。"
                                            "「経理課（§3〜§4）・部長（§1 だけ）」のように、読む人ごとに読む章を添える"))

    # 未決の一覧が末尾にあり、本文から参照される
    visible = re.sub(r"<!--.*?-->", "", "\n".join(lines), flags=re.S)
    for i, _, num, title in hs:
        if not num or not UNDECIDED_HEADING_RE.search(title) or i < len(lines) * 2 / 3:
            continue
        n = len(re.findall(rf"§\s*{re.escape(num)}(?![\d.])|(?<![\d.]){re.escape(num)}節|第{re.escape(num)}章", visible))
        if n >= 3:
            findings.append(Finding("warning", i + 1, "undecided-at-end",
                                    f"未決の一覧「§{num} {title}」が末尾にあり、本文から{n}回参照される。読み手は末尾に着くまで何件が未決か分からない。"
                                    "件数と判断に関わる行を §1 に置き、本文では「未決（§1.1）」と参照する"))
            break

    # 本書の別の章を参照する段落の割合と、要件ID
    body = [c for c in chapters if c.kind == "本文"]
    n_units = sum(c.units for c in body)
    n_ref = sum(c.ref_units for c in body)
    if n_units >= 6 and n_ref / n_units > lim["ref_unit_share_warn"]:
        findings.append(Finding("warning", body[0].line, "ref-share",
                                f"本文の段落の{n_ref / n_units:.0%}（{n_ref}/{n_units}）が本書の別の章を参照している（§1・同じ章・他の文書への"
                                f"参照は除く）> {lim['ref_unit_share_warn']:.0%}。1つの話題は1か所で読み終えられるように正本の章に書き、"
                                "参照は §1 の正本の列と「未決（§1.1）」に寄せる"))
    n_ids = pre.ids + sum(c.ids for c in chapters if c.kind != "付録")
    if n_ids >= lim["opaque_id_warn"]:
        ex = next((c.id_example for c in [pre] + chapters if c.id_example), "")
        findings.append(Finding("warning", 1, "opaque-id",
                                f"要件ID（{ex}）が本文に{n_ids}回（付録を除く）。読み手は ID の中身を知れないので、本文では要件の内容を書き、"
                                "ID は付録の対応表だけに置く"))
    return findings, pre, chapters


def report(path: Path, pre: Chapter, chapters: list[Chapter], findings: list[Finding]) -> str:
    out = [f"# {path} の構造（章ごと。読む字数＝文章＋表＋図のラベル）", "",
           "| 章 | 読む字数 | 表の割合 | 型 | 参照 | ID | 区分 |", "|---|---|---|---|---|---|---|"]
    for c in ([pre] if pre.read else []) + chapters:
        out.append(f"| {c.label} | {c.read:.0f} | {c.share:.0%} | {c.shape or '—'} | {c.refs} | {c.ids} | {c.kind} |")
    front = [pre] + [c for c in chapters[:next((k for k, c in enumerate(chapters) if c.kind not in ('前置き', '引く表')), len(chapters))]]
    path_read = sum(c.read for c in chapters if c.kind in ("要点", "本文"))
    body = [c for c in chapters if c.kind == "本文"]
    n_units = sum(c.units for c in body)
    run = longest_same_shape(chapters)
    out += ["",
            f"前置き {sum(c.read for c in front):.0f}字（本文の中身まで）／読み通す章の合計 {path_read:.0f}字（引く表の章と付録を除く）／"
            f"本文の章参照 {sum(c.refs for c in body)}回・別の章を参照する段落 {sum(c.ref_units for c in body)}/{n_units}／"
            f"同じ型の最長の連続 {len(run)}章" + (f"（{run[0].shape}）" if run else "")]
    out += [f"  WARNING {path}:{f.line} {f.rule}: {f.message}" for f in findings] or ["  構造の warning なし"]
    return "\n".join(out)


def main() -> int:
    files = [Path(a) for a in sys.argv[1:] if not a.startswith("-")]
    if not files or any(a in ("-h", "--help") for a in sys.argv[1:]):
        print(__doc__)
        return 0 if files else 2
    ng = verbosity.load_ng()
    for f in files:
        findings, pre, chapters = analyze(f, ng)
        print(report(f, pre, chapters, findings))
    return 0


if __name__ == "__main__":
    sys.exit(main())
