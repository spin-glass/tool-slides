#!/usr/bin/env python3
"""設計書（Markdown＋Mermaid）の検査。標準ライブラリのみ（Mermaid の描画確認だけ quarto と Chrome を使う）。

使い方:
  python3 check_doc.py decks/<name>/design/<doc>.md            # 章参照・章ごとの図・Mermaid の種類・placeholder・claims.csv
  python3 check_doc.py --render decks/<name>/design/<doc>.md   # さらに Mermaid を PNG にする → design/_check/<doc>-fig-NN.png（Read で目視）
  python3 check_doc.py --hook                                  # Stop hook。git で変更のある decks/**/design/*.md を検査（描画も行う）
  python3 check_doc.py --candidates design/_source/<doc>.md    # 原文の削除候補・一般論の多い段落・繰り返しの一覧（書き直す前に）
  python3 check_doc.py --original design/_source/<doc>.md design/<doc>.md   # 原文と書き直しの字数・段落数・一般論の比較
  python3 check_doc.py --paragraphs design/_source/<doc>.md   # 原文の全段落の一覧（4分類の作業表）

block:   本文にない章への参照（§3.4・3.4節・3章。「基本設計 §5.1」のように文書名つきの外部参照は見ない）、
         Mermaid の1行目が図の種類でない、Mermaid の描画エラー、placeholder（TODO・TBD・XXX・〇〇。`[要確認]` は未決の印として可）、
         claims.csv の列・状態の誤り、
         冗長さ: 削除候補（数字・主張ID・§・`コード`・「固有の語」・[要確認] のどれも無く、一般論・前置き・ヘッジだけの段落）、
         文書内の同じ文の繰り返し（全角20字以上）、同じフォルダの別の設計書と同じ文（全角30字以上）
warning: `## ` の章の直後に図（Mermaid・表・画像）が無い、章番号（## 3. / ### 3.1）のない見出し、
         1段落200字超・1章の文章1000字超、一般論・前置き・ヘッジが1段落に2つ以上・文章1000字あたり3つ超、バズワード、
         表のセルが一般論だけ・表どうしで同じセル、同じ主張ID を3か所以上（再掲）、
         読む字数（文章＋表＋図のラベル）が原文（design/_source/<同じ名前>.md）より多い、ひし形のラベルの1行が10字超、
         claims.csv で設計書に載せるはずの主張が本文に出てこない（削りすぎ）
辞書: references/ng_doc.md（一般論・前置き）と slides の references/ng_words.md（ヘッジ・バズワード）。閾値は verbosity.py の LIMITS
終了コード: 0 = block なし / 2 = block あり
"""
from __future__ import annotations

import argparse
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
from dataclasses import dataclass
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
import claims as claims_mod  # noqa: E402
import verbosity  # noqa: E402

HEADING_RE = re.compile(r"^(#{1,6})\s+(.*?)\s*$")
NUMBERED_RE = re.compile(r"^(\d+(?:\.\d+)*)\.?\s+")
FENCE_RE = re.compile(r"^(`{3,}|~{3,})\s*(\{?mermaid\}?)?\s*$")
# 本文中の章参照。同じ表のセルの中で、参照の直前12字か直後6字に文書名（「基本設計 §5.1」「原文 §3.2」「§12 は原文に無い」）があれば他の文書への参照として見ない
# 「3章」は章の数（「章は11」）と区別できないので、「第3章」の形だけを参照として見る
REF_RE = re.compile(r"§\s*(?P<a>\d+(?:\.\d+)*)|(?P<b>\d+(?:\.\d+)+)節|第(?P<c>\d+)章")
DOC_WORDS = ("原文", "基本設計", "処理設計", "ML設計", "精度検証", "運用・移行", "運用設計", "移行設計", "設計書", "文書", "仕様書", "マニュアル")
MERMAID_TYPES = re.compile(r"^(flowchart|graph|gantt|sequenceDiagram|classDiagram|stateDiagram(?:-v2)?|erDiagram|pie|journey|"
                           r"timeline|mindmap|quadrantChart|gitGraph|xychart-beta|block-beta|sankey-beta|requirementDiagram|"
                           r"C4Context|C4Container|C4Component|packet-beta|kanban|architecture-beta)\b")
PLACEHOLDER_RE = re.compile(r"\bTODO\b|\bTBD\b|\bFIXME\b|lorem|\[insert[^\]]*\]|\bXXX\b|\[__\]|〇〇|○○", re.I)
HOOK_MAX_BLOCKS = 3
# Mermaid の見た目をデッキ（theme/custom.scss）にそろえる1行。図の先頭に置く（設計書は16px、スライドは fontSize を 24px に）
MERMAID_INIT = ('%%{init: {"theme": "base", "themeVariables": {"fontSize": "16px", "fontFamily": "Hiragino Sans, Noto Sans JP, sans-serif", '
                '"primaryColor": "#eef4fb", "primaryBorderColor": "#0b5cad", "primaryTextColor": "#1f2328", "lineColor": "#57606a", '
                '"edgeLabelBackground": "#ffffff", "taskBkgColor": "#eef4fb", "taskBorderColor": "#0b5cad", "taskTextColor": "#1f2328", '
                '"critBkgColor": "#b35900", "critBorderColor": "#b35900", "gridColor": "#d0d7de", "sectionBkgColor": "#ffffff"}}}%%')


@dataclass
class Issue:
    severity: str   # block / warning
    line: int
    rule: str
    message: str

    def fmt(self, path) -> str:
        return f"{self.severity.upper():7} {path}:{self.line} {self.rule}: {self.message}"


def parse(path: Path):
    """見出し（行, レベル, 番号, 題）と Mermaid ブロック（開始行, 本文）と本文行（コード以外）を返す。"""
    lines = path.read_text(encoding="utf-8").splitlines()
    headings, blocks, prose = [], [], []
    in_fence = None
    in_comment = False
    buf: list[str] = []
    start = 0
    for i, raw in enumerate(lines, 1):
        m = FENCE_RE.match(raw.strip())
        if in_comment and not in_fence:          # 複数行の HTML コメントは本文として扱わない
            if "-->" in raw:
                in_comment = False
                prose.append((i, raw.split("-->", 1)[1]))
            continue
        if not in_fence and "<!--" in raw and "-->" not in raw.split("<!--", 1)[1]:
            in_comment = True
            prose.append((i, raw.split("<!--", 1)[0]))
            continue
        if in_fence:
            if raw.strip().startswith(in_fence[0]) and raw.strip().strip(in_fence[0][0]) == "":
                if in_fence[1]:
                    blocks.append((start, "\n".join(buf)))
                in_fence = None
                buf = []
            else:
                buf.append(raw)
            continue
        if m:
            in_fence = (m.group(1), bool(m.group(2)))
            start = i
            continue
        prose.append((i, raw))
        h = HEADING_RE.match(raw)
        if h:
            title = h.group(2)
            n = NUMBERED_RE.match(title)
            headings.append((i, len(h.group(1)), n.group(1) if n else "", title))
    return lines, headings, blocks, prose


def check_document(path: Path, render: bool = False) -> list[Issue]:
    issues: list[Issue] = []
    lines, headings, blocks, prose = parse(path)
    numbers = {num for _, _, num, _ in headings if num}

    # 章番号のない見出し（## 以下）
    for ln, level, num, title in headings:
        if level >= 2 and not num and not re.match(r"^(付録|参考|用語|変更履歴)", title):
            issues.append(Issue("warning", ln, "heading-number",
                                f"章番号がない見出し「{title}」。`## 3. 題` / `### 3.1 題` の形にすると参照を検査できる"))

    # 章参照
    for ln, raw in prose:
        text = re.sub(r"<!--.*?-->", "", raw)
        for m in REF_RE.finditer(text):
            cell_start = text.rfind("|", 0, m.start()) + 1
            cell_end = text.find("|", m.end())
            cell_end = len(text) if cell_end < 0 else cell_end
            # 「原文の §3.1・§3.3・§5.2」のように並んだ参照は、先頭の文書名を引き継ぐ
            head = re.sub(r"(?:(?:§\s*\d+(?:\.\d+)*|\d+(?:\.\d+)+節|\d+章)[–〜~\-]?\d*(?:\.\d+)*\s*[・、,，と及びおよび\s]*)+$", "",
                          text[cell_start:m.start()])
            before = head[-12:]
            after = text[m.end():min(cell_end, m.end() + 6)]
            if any(w in before or w in after for w in DOC_WORDS):
                continue   # 「基本設計 §5.1」「§12 は原文に無い」など、他の文書への参照（同じセルの中だけ見る）
            num = m.group("a") or m.group("b") or m.group("c")
            if num not in numbers:
                issues.append(Issue("block", ln, "ref-missing",
                                    f"本文にない章への参照 §{num}。章を書くか、参照を直す（他の文書なら文書名を前に付ける: 基本設計 §{num}）"))

    # 章（##）の直後に図があるか
    for idx, (ln, level, num, title) in enumerate(headings):
        if level != 2:
            continue
        j = ln   # 0-based index of next line
        while j < len(lines):
            s = lines[j].strip()
            if not s or s.startswith("<!--"):
                j += 1
                continue
            break
        first = lines[j].strip() if j < len(lines) else ""
        if not (first.startswith("```") or first.startswith("|") or first.startswith("![") or first.startswith("<img")):
            issues.append(Issue("warning", ln, "figure-first",
                                f"章「{title}」の見出しの直後に図（Mermaid・表・画像）が無い。章の要点を1つの図か表で先に示し、本文はその説明にする"))

    # Mermaid の種類と描画
    for ln, body in blocks:
        head = next((l.strip() for l in body.splitlines() if l.strip() and not l.strip().startswith("%%")), "")
        if not MERMAID_TYPES.match(head):
            issues.append(Issue("block", ln, "mermaid-type",
                                f"Mermaid の1行目が図の種類でない: {head[:40]!r}（flowchart / gantt / sequenceDiagram など）"))
        for lab in re.findall(r'\{"?([^}"]+)"?\}', "\n".join(l for l in body.splitlines() if not l.strip().startswith("%%"))):
            longest = max(zen_len_safe(x) for x in re.split(r"<br\s*/?>", lab))
            if longest > 10:
                issues.append(Issue("warning", ln, "mermaid-diamond",
                                    f"ひし形のラベルの1行が全角{longest:.0f}字（「{lab[:16]}…」）。ひし形は字が欠けやすいので、"
                                    "1行10字以内にして <br> で折る"))
                break
        if "%%{init" not in body:
            issues.append(Issue("warning", ln, "mermaid-theme",
                                "Mermaid に色と文字の指定（%%{init: …}%%）が無い。既定の紫の図になり、スライドの色とそろわない。"
                                "`check_doc.py --mermaid-init` が出す1行を図の先頭に置く"))
    if render and blocks:
        pngs, errors = render_mermaid([b for _, b in blocks], path.parent / "_check", path.stem)
        for e in errors:
            issues.append(Issue("block" if "失敗" in e else "warning", blocks[0][0], "mermaid-render", e))
        for (ln, _), png in zip(blocks, pngs):
            issues.append(Issue("info", ln, "mermaid-png", str(png)))

    # placeholder（[要確認] は未決の印として許す）
    for ln, raw in prose:
        m = PLACEHOLDER_RE.search(raw)
        if m:
            issues.append(Issue("block", ln, "placeholder",
                                f"未確定の記述 `{m.group(0)}`。値を確かめて埋めるか、未決なら [要確認] と書いて未決事項の節に載せる"))

    # 冗長さ（一般論・前置き・ヘッジ、削除候補、繰り返し、長すぎる段落・章）
    findings, metrics, _ = verbosity.analyze(path)
    issues.extend(Issue(f.severity, f.line, f.rule, f.message) for f in findings)
    issues.append(Issue("info", 1, "metrics", metrics.fmt()))

    # 主張の表（デッキのフォルダの claims.csv）
    for cand in (path.parent / "claims.csv", path.parent.parent / "claims.csv"):
        if cand.exists():
            rows = claims_mod.load(cand)
            for e in claims_mod.validate(rows):
                issues.append(Issue("block", 1, "claims-file", f"{cand.name}: {e}"))
            # 削りすぎの検知: 設計書に載せるはずの主張（target が doc / both）が、同じフォルダのどの設計書にも出てこない
            text = "\n".join(re.sub(r"<!--.*?-->", "", p.read_text(encoding="utf-8"), flags=re.S)
                             for p in path.parent.glob("*.md") if not p.name.startswith("_"))
            missing = [r["id"] for r in rows if r.get("target") in ("doc", "both") and r.get("id")
                       and not re.search(rf"(?<![A-Za-z0-9_-]){re.escape(r['id'])}(?![A-Za-z0-9_-])", text)]
            if missing:
                issues.append(Issue("warning", 1, "claims-unused",
                                    f"設計書に載せるはずの主張が本文に出てこない: {', '.join(missing)}。"
                                    "削りすぎていないか確かめ、載せるなら本文に（C1）の形で添える"))
            break

    order = {"block": 0, "warning": 1, "info": 2}
    issues.sort(key=lambda x: (order[x.severity], x.line))
    return issues


def zen_len_safe(s: str) -> float:
    return verbosity.zen_len(s)


def render_mermaid(blocks: list[str], out_dir: Path, stem: str) -> tuple[list[Path], list[str]]:
    """Mermaid を quarto（html, mermaid-format: png）で PNG にし、out_dir/<stem>-fig-NN.png に置く。"""
    if not shutil.which("quarto"):
        return [], ["quarto が無いので Mermaid の描画確認を省略した"]
    tmp = Path(tempfile.mkdtemp(prefix="check_doc_"))
    qmd = ["---", "format:", "  html:", "    mermaid-format: png", "---", ""]
    for b in blocks:
        qmd += ["```{mermaid}", "%%| fig-width: 8", *b.splitlines(), "```", ""]
    (tmp / "figs.qmd").write_text("\n".join(qmd), encoding="utf-8")
    r = subprocess.run(["quarto", "render", "figs.qmd", "--to", "html", "--quiet"], cwd=tmp,
                       capture_output=True, text=True)
    # quarto の出力番号は文書の順と限らないので、HTML に出てくる <img> の順で並べる
    html = (tmp / "figs.html").read_text(encoding="utf-8") if (tmp / "figs.html").exists() else ""
    order = list(dict.fromkeys(re.findall(r'src="(figs_files/figure-html/mermaid-figure-[^"]+\.png)"', html)))
    pngs = [tmp / o for o in order if (tmp / o).exists()]
    if len(pngs) != len(blocks):     # HTML から読めないときは番号順（文書の順と違うことがある）
        pngs = sorted((tmp / "figs_files" / "figure-html").glob("mermaid-figure-*.png"),
                      key=lambda p: int(re.search(r"(\d+)", p.stem).group(1)))
    errors: list[str] = []
    if r.returncode != 0 or len(pngs) != len(blocks):
        tail = [l for l in (r.stderr + r.stdout).splitlines() if l.strip()][-3:]
        errors.append(f"Mermaid の描画に失敗（図 {len(pngs)}/{len(blocks)}）: " + " / ".join(tail))
    out_dir.mkdir(parents=True, exist_ok=True)
    for old in out_dir.glob(f"{stem}-fig-*.png"):
        old.unlink()
    copies = []
    for i, p in enumerate(pngs, 1):
        dst = out_dir / f"{stem}-fig-{i:02d}.png"
        shutil.copy(p, dst)
        copies.append(dst)
    shutil.rmtree(tmp, ignore_errors=True)
    return copies, errors


# ---- 対象ファイルと hook ---------------------------------------------------
def repo_root(start: Path) -> Path:
    try:
        r = subprocess.run(["git", "rev-parse", "--show-toplevel"], cwd=start, capture_output=True, text=True, check=True)
        return Path(r.stdout.strip())
    except Exception:
        return start


def changed_docs(root: Path) -> list[Path]:
    try:
        r = subprocess.run(["git", "status", "--porcelain", "--untracked-files=all", "--", "decks"],
                           cwd=root, capture_output=True, text=True, check=True)
    except Exception:
        return []
    out = []
    for line in r.stdout.splitlines():
        p = line[3:].split(" -> ")[-1].strip().strip('"')
        parts = Path(p).parts
        if p.endswith(".md") and "design" in parts and (root / p).exists() and not any(x.startswith("_") for x in parts):
            out.append(root / p)
    return sorted(set(out))


def hook_counter(session: str, reset: bool = False) -> int:
    f = Path(tempfile.gettempdir()) / f"check_doc_{re.sub(r'[^A-Za-z0-9_-]', '', session) or 'default'}.count"
    if reset:
        f.unlink(missing_ok=True)
        return 0
    n = int(f.read_text()) + 1 if f.exists() else 1
    f.write_text(str(n))
    return n


def run_hook() -> int:
    try:
        data = json.load(sys.stdin)
    except Exception:
        data = {}
    cwd = Path(data.get("cwd") or os.environ.get("CLAUDE_PROJECT_DIR") or os.getcwd())
    root = repo_root(cwd)
    session = str(data.get("session_id", "default"))
    blocks: list[str] = []
    for p in changed_docs(root):
        rel = p.relative_to(root) if p.is_relative_to(root) else p
        blocks += [i.fmt(rel) for i in check_document(p, render=True) if i.severity == "block"]
    if not blocks:
        hook_counter(session, reset=True)
        return 0
    n = hook_counter(session)
    if n > HOOK_MAX_BLOCKS:
        print(json.dumps({"systemMessage": f"check_doc: {len(blocks)}件の違反が{HOOK_MAX_BLOCKS}回の修正後も残っています。"
                                           f"手動確認が必要です。先頭: {blocks[0]}"}, ensure_ascii=False))
        hook_counter(session, reset=True)
        return 0
    head = blocks[:10]
    more = f"\n…ほか{len(blocks) - 10}件" if len(blocks) > 10 else ""
    reason = ("設計書の検査が不合格です。該当箇所だけを Edit で直し（全文を書き直さない）、"
              "原文に無い情報は補わず未決として書いてください。\n" + "\n".join(head) + more)
    print(json.dumps({"decision": "block", "reason": reason}, ensure_ascii=False))
    return 0


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("files", nargs="*", type=Path)
    ap.add_argument("--render", action="store_true", help="Mermaid を PNG にして design/_check/ に置く")
    ap.add_argument("--hook", action="store_true", help="Claude Code Stop hook として動く")
    ap.add_argument("--candidates", action="store_true", help="削除候補・一般論の多い段落・繰り返しの一覧を出す（原文に使う）")
    ap.add_argument("--original", type=Path, help="原文。書き直しと字数・段落数・一般論を比べる")
    ap.add_argument("--paragraphs", action="store_true", help="原文の全段落の一覧（4分類の作業表）を出す")
    ap.add_argument("--mermaid-init", nargs="?", const="16px", metavar="SIZE",
                    help="Mermaid の先頭に置く色と文字の1行を出す（スライドでは 24px）")
    args = ap.parse_args()
    if args.mermaid_init:
        print(MERMAID_INIT.replace('"16px"', f'"{args.mermaid_init}"'))
        return 0
    if args.hook:
        return run_hook()
    if not args.files:
        print("対象の .md を指定する", file=sys.stderr)
        return 2
    if args.paragraphs:
        sys.argv = [sys.argv[0], "--paragraphs"] + [str(f) for f in args.files]
        return verbosity.main()
    if args.candidates or args.original:
        argv = (["--original", str(args.original)] if args.original else []) + [str(f) for f in args.files]
        sys.argv = [sys.argv[0]] + argv
        if not args.original:
            rc = verbosity.main()
            for f in args.files:          # 原文の章参照の誤り（存在しない章を指す）も出す
                for i in check_document(f):
                    if i.rule in ("ref-missing", "placeholder"):
                        print("  原文の" + i.fmt(f))
            return rc
        verbosity.main()      # 比べた上で、書き直しの検査も続けて行う
    worst = 0
    for f in args.files:
        issues = check_document(f, render=args.render)
        nb = sum(i.severity == "block" for i in issues)
        nw = sum(i.severity == "warning" for i in issues)
        for i in issues:
            print(i.fmt(f))
        print(f"-- {f}: block {nb} / warning {nw}")
        if nb:
            worst = 2
    return worst


if __name__ == "__main__":
    sys.exit(main())
