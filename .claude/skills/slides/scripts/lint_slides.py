#!/usr/bin/env python3
"""Quarto スライド (.qmd) の lint。標準ライブラリのみ。

使い方:
  python lint_slides.py decks/foo/index.qmd      # 人間向けレポート（違反＋タイトル連読リスト）
  python lint_slides.py --titles decks/foo/index.qmd  # タイトル連読リストのみ（ゴーストデッキ承認用）
  python lint_slides.py                          # decks/**/index.qmd を全部
  python lint_slides.py --hook                   # Stop hook。git で変更のある deck だけを検査し、
                                                 # 違反があれば {"decision":"block","reason":...} を出す

画像: `![代替テキスト](パス)` のファイルが無ければ block、代替テキストが空なら warning。
      図を描くコードセル（plt. / imgfig. など）に `#| fig-alt:` が無ければ warning。
      画像を並べた図（imgfig.*_figure）のスライドに選び方（すべて・等間隔・上位…）の記載が無ければ warning。

終了コード（通常モード）: 0=block違反なし / 2=block違反あり
閾値は下の LIMITS。最初の2〜3デッキで較正する（references/evidence.md）。
"""
from __future__ import annotations

import argparse
import json
import os
import re
import subprocess
import sys
import tempfile
import unicodedata
from dataclasses import dataclass, field
from pathlib import Path

SKILL_DIR = Path(__file__).resolve().parent.parent
NG_WORDS_FILE = SKILL_DIR / "references" / "ng_words.md"

# ---- 閾値（要較正） -------------------------------------------------------
LIMITS = {
    "bullets_block": 5,        # bullets > 5 で block
    "bullets_warn": 3,         # bullets > 3 で warning（目標3）
    "lines_block": 15,         # 1枚 > 15行で block
    "body_chars_block": 250,   # 本文 > 全角250字で block
    "title_chars_block": 40,   # タイトル > 全角40字で block
    "title_words_block": 15,   # 英語タイトル > 15語で block
    "code_lines_block": 10,    # 表示されるコード > 10行で block
    "hedge_per_slide_warn": 2,  # 1枚でヘッジ語 >= 2 で warning
    "hedge_ratio_warn": 0.3,   # デッキ全体でヘッジ語数 / 本編枚数 > 0.3 で warning
    "hook_max_blocks": 3,      # 同一セッションで連続 block する上限（無限ループ防止）
}

REQUIRED_META = ("audience", "action", "minutes", "budget", "status")
STATUSES = ("ghost", "approved")

# 体言止め・ラベル型タイトル
LABEL_TITLE_RE = re.compile(
    r"(について|に関して|に関する\S*|とは|の(概要|背景|現状|課題|まとめ|比較|紹介|説明|検討|分析|結果|報告|推移|一覧|全体像|ポイント))$"
    r"|^(まとめ|概要|背景|目的|はじめに|おわりに|課題|今後の(課題|展望|予定)|結論|提案|アジェンダ|目次|Q&A|質疑応答"
    r"|参考(文献|資料)?|付録|補足|考察|結果|方法|手法|現状|ご清聴ありがとうございました)$"
)
SENTENCE_END_STRIP = "。．.!！?？」』）)〕】 　"

FENCE_RE = re.compile(r"^(\s*)(`{3,}|~{3,})(.*)$")
DIV_OPEN_RE = re.compile(r"^\s*(:{3,})\s*(\{[^}]*\}|[\w-]+)\s*$")
DIV_CLOSE_RE = re.compile(r"^\s*(:{3,})\s*$")
HEADING_RE = re.compile(r"^(#{1,6})\s+(.*?)\s*$")
HR_RE = re.compile(r"^\s*(-{3,}|\*{3,}|_{3,})\s*$")
BULLET_RE = re.compile(r"^\s*([-*+]|\d+[.)])\s+\S")
META_RE = re.compile(r"<!--\s*(audience|action|minutes|budget|status|decided-by)\s*:\s*(.*?)\s*-->")
IMAGE_RE = re.compile(r"!\[([^\]]*)\]\(([^)\s]+)[^)]*\)")
PLOT_RE = re.compile(r"\b(plt|imgfig|sns|px|go|alt)\.\w|\.plot\(|\.savefig\(")
IMGFIG_RE = re.compile(r"\bimgfig\.\w+_figure\(")
PICK_RE = re.compile(r"すべて|全数|全部|全\d+枚|等間隔|上位|下位|大きい順|小さい順|無作為|抜粋|代表")
# 画像の中身についての言い切り。縮小した画像では見落としやすい（小さく写るもの、よく似た種）ので、元の大きさで確かめさせる
ABSOLUTE_RE = re.compile(r"ばかり|[1一]枚も|写っていない|写らない|だけが写|しか写|例外なく|全員|全頭")
APPENDIX_RE = re.compile(r"<!--\s*appendix\s*-->")
COMMENT_RE = re.compile(r"<!--.*?-->", re.S)
QUOTE_RE = re.compile(r"「[^」]*」")


# ---- 文字幅 ---------------------------------------------------------------
def zen_len(s: str) -> float:
    """全角=1、半角=0.5 で数える。"""
    n = 0.0
    for ch in s:
        if ch.isspace():
            continue
        n += 1 if unicodedata.east_asian_width(ch) in ("F", "W", "A") else 0.5
    return n


def strip_md(s: str) -> str:
    s = COMMENT_RE.sub("", s)
    s = re.sub(r"!\[[^\]]*\]\([^)]*\)(\{[^}]*\})?", "", s)       # 画像
    s = re.sub(r"\[([^\]]*)\]\([^)]*\)", r"\1", s)               # リンク
    s = re.sub(r"\[([^\]]*)\]\{[^}]*\}", r"\1", s)               # span
    s = re.sub(r"\{[.#][^}]*\}", "", s)                          # 属性
    s = re.sub(r"<[^>]+>", "", s)                                 # HTML
    s = re.sub(r"^\s*([-*+]|\d+[.)])\s+", "", s)                  # 箇条記号
    s = re.sub(r"^\s*>\s?", "", s)                                # 引用
    s = re.sub(r"[*_`~]|\|", "", s)                               # 強調・表
    s = re.sub(r"^\s*:?-{3,}:?\s*$", "", s)                       # 表の区切り
    return s.strip()


def is_mostly_ascii(s: str) -> bool:
    chars = [c for c in s if not c.isspace()]
    return bool(chars) and sum(c.isascii() for c in chars) / len(chars) > 0.8


def is_hiragana(ch: str) -> bool:
    return "ぁ" <= ch <= "ゟ"


# ---- NG 辞書 --------------------------------------------------------------
def load_ng_words(path: Path = NG_WORDS_FILE) -> dict[str, list[re.Pattern]]:
    """ng_words.md の ```ng:<class> フェンス内を1行1正規表現として読む。"""
    classes: dict[str, list[re.Pattern]] = {}
    if not path.exists():
        return classes
    current = None
    for line in path.read_text(encoding="utf-8").splitlines():
        m = re.match(r"^```ng:(\w+)\s*$", line)
        if m:
            current = classes.setdefault(m.group(1), [])
            continue
        if current is not None and line.startswith("```"):
            current = None
            continue
        if current is not None:
            pat = line.strip()
            if pat and not pat.startswith("#"):
                current.append(re.compile(pat, re.I))
    return classes


# ---- パース ---------------------------------------------------------------
@dataclass
class Slide:
    index: int                 # 1始まり（タイトルスライド除く）
    line: int                  # 見出し行（1始まり）
    title: str
    level: int                 # 1=セクション, 2=通常, 0=--- 区切り（タイトルなし）
    appendix: bool
    body: list[tuple[int, str]] = field(default_factory=list)      # 表示本文 (行番号, 行)
    code: list[tuple[int, str]] = field(default_factory=list)      # 表示コード
    notes: list[tuple[int, str]] = field(default_factory=list)     # speaker notes
    comments: list[tuple[int, str]] = field(default_factory=list)  # HTMLコメント（evidence 等）
    images: list[tuple[int, str, str]] = field(default_factory=list)   # markdown 画像 (行番号, 代替テキスト, パス)
    figures: list[tuple[int, bool, bool]] = field(default_factory=list)  # 図を描くセル (行番号, fig-alt の有無, 画像を並べる図か)


@dataclass
class Deck:
    path: Path
    meta: dict[str, tuple[int, str]]
    slides: list[Slide]
    appendix_line: int | None
    all_lines: list[str]
    preamble_line: int | None = None   # 最初のスライド見出しより前にある本文・コードの行


def parse_front_matter(lines: list[str]) -> tuple[int, dict[str, str]]:
    if not lines or lines[0].strip() != "---":
        return 0, {}
    fm: dict[str, str] = {}
    for i in range(1, len(lines)):
        if lines[i].strip() in ("---", "..."):
            return i + 1, fm
        m = re.match(r"^\s*([\w-]+)\s*:\s*(.*)$", lines[i])
        if m:
            fm[m.group(1)] = m.group(2).strip().strip("\"'")
    return 0, {}


def parse_deck(path: Path) -> Deck:
    text = path.read_text(encoding="utf-8")
    lines = text.splitlines()
    start, fm = parse_front_matter(lines)
    default_echo = fm.get("echo", "false").lower() == "true"

    meta: dict[str, tuple[int, str]] = {}
    slides: list[Slide] = []
    cur: Slide | None = None
    appendix = False
    appendix_line = None
    in_code = None            # (fence, executable, echo)
    code_buf: list[tuple[int, str]] = []
    div_stack: list[tuple[int, bool]] = []   # (colon数, notesか)
    in_comment = False
    preamble_line = None
    code_start = 0

    def in_notes() -> bool:
        return any(n for _, n in div_stack)

    for i in range(start, len(lines)):
        ln = i + 1
        raw = lines[i]

        # コードフェンス
        if in_code:
            fence, executable, echo = in_code
            if raw.strip().startswith(fence) and raw.strip().strip(fence[0]) == "":
                hidden = any(re.match(r"#\|\s*include\s*:\s*false", l.strip()) for _, l in code_buf)
                if cur is None and not hidden and preamble_line is None:
                    preamble_line = code_start   # include: false 以外のセルは空スライドを作る
                if cur and not in_notes():
                    opts = [l for _, l in code_buf if l.strip().startswith("#|")]
                    body = [(n, l) for n, l in code_buf if not l.strip().startswith("#|")]
                    for o in opts:
                        m = re.match(r"#\|\s*echo\s*:\s*(\w+)", o.strip())
                        if m:
                            echo = m.group(1).lower() == "true"
                    if not executable or echo:
                        cur.code.extend(body)
                    if executable and not hidden and any(PLOT_RE.search(l) for _, l in body):
                        cur.figures.append((code_start, any(re.match(r"#\|\s*fig-alt\s*:\s*\S", o.strip()) for o in opts),
                                            any(IMGFIG_RE.search(l) for _, l in body)))
                in_code = None
                code_buf = []
            else:
                code_buf.append((ln, raw))
            continue
        m = FENCE_RE.match(raw)
        if m:
            code_start = ln
            info = m.group(3).strip()
            in_code = (m.group(2), info.startswith("{"), default_echo)
            continue

        # HTMLコメント（複数行も）
        if in_comment:
            if cur:
                cur.comments.append((ln, raw))
            if "-->" in raw:
                in_comment = False
            continue
        for mm in META_RE.finditer(raw):
            meta.setdefault(mm.group(1), (ln, mm.group(2)))
        if APPENDIX_RE.search(raw):
            appendix = True
            appendix_line = appendix_line or ln
            continue
        if "<!--" in raw:
            if cur:
                cur.comments.append((ln, raw))
            if "-->" not in raw:
                in_comment = True
            rest = COMMENT_RE.sub("", raw).strip()
            if not rest:
                continue
            raw = COMMENT_RE.sub("", raw)

        # fenced div
        m = DIV_OPEN_RE.match(raw)
        if m:
            div_stack.append((len(m.group(1)), ".notes" in m.group(2) or m.group(2) == "notes"))
            continue
        m = DIV_CLOSE_RE.match(raw)
        if m and div_stack:
            div_stack.pop()
            continue

        if in_notes():
            if cur:
                cur.notes.append((ln, raw))
            continue

        # スライド区切り
        m = HEADING_RE.match(raw)
        if m and len(m.group(1)) <= 2:
            title = re.sub(r"\s*\{[^}]*\}\s*$", "", m.group(2)).strip()
            cur = Slide(len(slides) + 1, ln, title, len(m.group(1)), appendix)
            slides.append(cur)
            continue
        if HR_RE.match(raw):
            cur = Slide(len(slides) + 1, ln, "", 0, appendix)
            slides.append(cur)
            continue

        if cur and raw.strip():
            cur.body.append((ln, raw))
            cur.images.extend((ln, mm.group(1).strip(), mm.group(2)) for mm in IMAGE_RE.finditer(raw))
        elif cur is None and raw.strip() and preamble_line is None:
            preamble_line = ln

    return Deck(path, meta, slides, appendix_line, lines, preamble_line)


# ---- 検査 -----------------------------------------------------------------
@dataclass
class Issue:
    severity: str   # block / warning
    line: int
    slide: Slide | None
    rule: str
    message: str

    def fmt(self, path: Path) -> str:
        where = f"{path}:{self.line}"
        if self.slide:
            t = self.slide.title or "(タイトルなし)"
            where += f" [{self.slide.index}枚目「{t}」]"
        return f"{self.severity.upper():7} {where} {self.rule}: {self.message}"


def check_title(s: Slide) -> list[Issue]:
    out: list[Issue] = []
    if s.level == 0 or not s.title:
        out.append(Issue("block", s.line, s, "title-missing",
                         "タイトルのないスライド。承認済みアクションタイトルを `## 完全文` で付ける"))
        return out
    plain = strip_md(s.title)
    if is_mostly_ascii(plain):
        words = len(plain.split())
        if words > LIMITS["title_words_block"]:
            out.append(Issue("block", s.line, s, "title-length",
                             f"タイトル{words}語 > {LIMITS['title_words_block']}語。結論だけ残して縮める"))
        return out
    n = zen_len(plain)
    if n > LIMITS["title_chars_block"]:
        out.append(Issue("block", s.line, s, "title-length",
                         f"タイトル全角{n:g}字 > {LIMITS['title_chars_block']}字。so-whatと数字だけ残して縮める"))
    if s.level == 1:
        return out   # セクション扉はラベル可（本編枚数には数える）
    core = plain.rstrip(SENTENCE_END_STRIP)
    if LABEL_TITLE_RE.search(core):
        out.append(Issue("block", s.line, s, "title-label",
                         "ラベル型タイトル（「〜について」「まとめ」等）。この枚で言いたい結論を完全文で書く"))
    elif core and not is_hiragana(core[-1]):
        out.append(Issue("block", s.line, s, "title-taigen",
                         "体言止め。述語で終える完全文にする（例: 「〜は3か月で20%増えた」「〜を半減できる」）"))
    return out


def check_deck(deck: Deck, ng: dict[str, list[re.Pattern]]) -> list[Issue]:
    issues: list[Issue] = []

    # 生成前ゲートの記録
    for key in REQUIRED_META:
        if key not in deck.meta:
            issues.append(Issue("block", 1, None, "gate-missing",
                                f"`<!-- {key}: ... -->` がない。聴衆・行動・持ち時間・budget・status を合意してから書く"))
    for key, (ln, v) in deck.meta.items():
        if not v or any(p.search(v) for p in ng.get("placeholder", [])):
            issues.append(Issue("block", ln, None, "gate-missing",
                                f"`{key}` が未確定: {v!r}。本人に確かめてから書く"))
    if "minutes" in deck.meta and not deck.meta["minutes"][1].isdigit():
        issues.append(Issue("block", deck.meta["minutes"][0], None, "gate-minutes",
                            f"minutes が整数でない: {deck.meta['minutes'][1]!r}"))
    budget = None
    if "budget" in deck.meta:
        ln, v = deck.meta["budget"]
        if v.isdigit():
            budget = int(v)
        else:
            issues.append(Issue("block", ln, None, "gate-budget", f"budget が整数でない: {v!r}"))
    status = deck.meta.get("status", (0, ""))[1]
    if "status" in deck.meta and status not in STATUSES:
        issues.append(Issue("block", deck.meta["status"][0], None, "gate-status",
                            f"status は {'/'.join(STATUSES)} のどれか: {status!r}"))

    if deck.preamble_line:
        issues.append(Issue("block", deck.preamble_line, None, "preamble",
                            "最初の `##` より前の本文・コードセルは空のスライドになる。1枚目の中へ移す（計算だけのセルは `#| include: false` なら可）"))

    main = [s for s in deck.slides if not s.appendix]
    if budget is not None and len(main) > budget:
        issues.append(Issue("block", main[budget].line, main[budget], "budget",
                            f"本編{len(main)}枚 > budget {budget}枚。統合・削除するか `<!-- appendix -->` 以降へ移す"))

    hedge_total = 0
    for s in deck.slides:
        issues.extend(check_title(s))

        # placeholder はどこにあっても block（タイトル・本文・ノート・コード）
        texts = [(s.line, s.title)] + s.body + s.notes + s.code
        for ln, t in texts:
            for p in ng.get("placeholder", []):
                if p.search(t):
                    issues.append(Issue("block", ln, s, "placeholder",
                                        f"未確定の記述 `{p.search(t).group(0)}`。値を確かめて埋めるか、不足情報を本人に尋ねる"))
                    break

        # ゴーストデッキ段階では本文を書かない
        if status == "ghost" and (s.body or s.code or s.notes):
            issues.append(Issue("block", (s.body or s.code or s.notes)[0][0], s, "ghost-body",
                                "status: ghost のうちは本文・コード・ノートを書かない（タイトルと `<!-- evidence: -->` のみ）"))

        visible = [(ln, strip_md(t)) for ln, t in s.body]
        visible = [(ln, t) for ln, t in visible if t]
        # 「」内は語の引用（例示）なので NG 語検査から外す
        unquoted = [(ln, QUOTE_RE.sub("", t)) for ln, t in visible + [(s.line, strip_md(s.title))]]
        for ln, t in unquoted:
            for p in ng.get("buzzword", []):
                m = p.search(t)
                if m:
                    issues.append(Issue("warning", ln, s, "buzzword",
                                        f"`{m.group(0)}`。具体的な対象・数値に置き換える"))
        hedges = []
        for ln, t in unquoted:
            for p in ng.get("hedge", []):
                for m in p.finditer(t):
                    hedges.append((ln, m.group(0)))
        hedge_total += len(hedges) if not s.appendix else 0
        if len(hedges) >= LIMITS["hedge_per_slide_warn"]:
            words = "、".join(w for _, w in hedges[:4])
            issues.append(Issue("warning", hedges[0][0], s, "hedge",
                                f"ヘッジ・言い訳語が{len(hedges)}個（{words}）。言い切れる所は言い切り、未確認は本人に確認"))

        # 画像と図（appendix も対象）
        for ln, alt, src in s.images:
            local = not re.match(r"^(https?:|data:|\{\{)", src)
            if local and not (deck.path.parent / src).exists():
                issues.append(Issue("block", ln, s, "image-missing",
                                    f"画像 `{src}` がない。パスを直すか、画像をデッキのフォルダに置く"))
            if not alt:
                issues.append(Issue("warning", ln, s, "image-alt",
                                    f"画像 `{src}` に代替テキストがない。`![何が写っていて何を見てほしいか](…)` と書く"))
        for ln, has_alt, _ in s.figures:
            if not has_alt:
                issues.append(Issue("warning", ln, s, "fig-alt",
                                    "図を描くセルに `#| fig-alt:` がない。図が何を示すかを1〜2文で書く"))
        image_figs = [ln for ln, _, is_images in s.figures if is_images]
        if image_figs and not any(PICK_RE.search(strip_md(t)) for _, t in s.body):
            issues.append(Issue("warning", image_figs[0], s, "pick-rule",
                                "画像を並べた図に選び方の記載がない。「N枚をすべて表示」「N枚から等間隔でk枚」などを `{.source}` に書く"))
        if image_figs or s.images:
            hits = [(ln, m.group(0)) for ln, t in [(s.line, s.title)] + s.body for m in ABSOLUTE_RE.finditer(strip_md(t))]
            if hits:
                words = "、".join(dict.fromkeys(w for _, w in hits))
                issues.append(Issue("warning", hits[0][0], s, "image-absolute",
                                    f"画像について言い切っている（{words}）。`imgfig.py sheet` で該当する画像を元の大きさで"
                                    "全枚見て、1枚も外れないことを確かめる"))

        if s.appendix:
            continue   # appendix は密度制限を免除

        bullets = sum(1 for _, t in s.body if BULLET_RE.match(t))
        if bullets > LIMITS["bullets_block"]:
            issues.append(Issue("block", s.line, s, "bullets",
                                f"bullets {bullets} > {LIMITS['bullets_block']}。根拠を3点に絞り、残りは appendix かノートへ"))
        elif bullets > LIMITS["bullets_warn"]:
            issues.append(Issue("warning", s.line, s, "bullets",
                                f"bullets {bullets} > 目標{LIMITS['bullets_warn']}"))

        nlines = len(visible) + len(s.code)
        if nlines > LIMITS["lines_block"]:
            issues.append(Issue("block", s.line, s, "lines",
                                f"{nlines}行 > {LIMITS['lines_block']}行。話す内容は ::: {{.notes}} へ移す"))

        chars = sum(zen_len(t) for _, t in visible)
        if chars > LIMITS["body_chars_block"]:
            issues.append(Issue("block", s.line, s, "body-chars",
                                f"本文 全角{chars:g}字 > {LIMITS['body_chars_block']}字。説明文はノートへ、スライドには証拠だけ"))

        if len(s.code) > LIMITS["code_lines_block"]:
            issues.append(Issue("block", s.code[0][0], s, "code-lines",
                                f"表示コード{len(s.code)}行 > {LIMITS['code_lines_block']}行。要所だけ抜粋するか `#| echo: false`"))

    if main and hedge_total / len(main) > LIMITS["hedge_ratio_warn"]:
        issues.append(Issue("warning", 1, None, "hedge-density",
                            f"本編のヘッジ・言い訳語 {hedge_total}個 / {len(main)}枚。素材不足なら書き足さず本人に不足情報を尋ねる"))

    issues.sort(key=lambda x: (x.severity != "block", x.line))
    return issues


def title_list(deck: Deck) -> str:
    out = [f"# タイトル連読（{deck.path}）"]
    main = [s for s in deck.slides if not s.appendix]
    budget = deck.meta.get("budget", (0, "?"))[1]
    out.append(f"本編 {len(main)} / budget {budget}")
    if "decided-by" in deck.meta:
        out.append(f"決めた人: {deck.meta['decided-by'][1]}")
    in_appendix = False
    for s in deck.slides:
        if s.appendix and not in_appendix:
            out.append("--- appendix ---")
            in_appendix = True
        ev = next((c for _, c in s.comments if "evidence" in c), "")
        ev = re.sub(r"^.*?evidence\s*:\s*|\s*-->.*$", "", ev.strip())
        line = f"{s.index:2}. {s.title or '(タイトルなし)'}"
        if ev:
            line += f"\n      証拠予定: {ev}"
        out.append(line)
    return "\n".join(out)


# ---- 対象ファイル ---------------------------------------------------------
def repo_root(start: Path) -> Path:
    try:
        r = subprocess.run(["git", "rev-parse", "--show-toplevel"], cwd=start,
                           capture_output=True, text=True, check=True)
        return Path(r.stdout.strip())
    except Exception:
        return start


def all_decks(root: Path) -> list[Path]:
    # "_" で始まるフォルダ（_template 等）は Quarto と同じく対象外
    return sorted(p for p in (root / "decks").glob("**/index.qmd")
                  if not any(part.startswith("_") for part in p.relative_to(root).parts))


def changed_decks(root: Path) -> list[Path]:
    """git で未コミットの変更がある decks/**/*.qmd。git が無ければ全 deck。"""
    try:
        r = subprocess.run(["git", "status", "--porcelain", "--untracked-files=all", "--", "decks"],
                           cwd=root, capture_output=True, text=True, check=True)
    except Exception:
        return all_decks(root)
    paths = []
    for line in r.stdout.splitlines():
        p = line[3:].split(" -> ")[-1].strip().strip('"')
        if (p.endswith(".qmd") and (root / p).exists()
                and not any(part.startswith("_") for part in Path(p).parts)):
            paths.append(root / p)
    return sorted(set(paths))


# ---- hook -----------------------------------------------------------------
def hook_counter(session: str, reset: bool = False) -> int:
    f = Path(tempfile.gettempdir()) / f"lint_slides_{re.sub(r'[^A-Za-z0-9_-]', '', session) or 'default'}.count"
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
    ng = load_ng_words()

    blocks: list[str] = []
    for p in changed_decks(root):
        deck = parse_deck(p)
        rel = p.relative_to(root) if p.is_relative_to(root) else p
        for i in check_deck(deck, ng):
            if i.severity == "block":
                blocks.append(i.fmt(rel))

    if not blocks:
        hook_counter(session, reset=True)
        return 0
    n = hook_counter(session)
    if n > LIMITS["hook_max_blocks"]:
        # 無限ループ防止: 上限を超えたら止めずに本人へ知らせる
        print(json.dumps({"systemMessage": f"lint_slides: {len(blocks)}件の違反が{LIMITS['hook_max_blocks']}回の修正後も残っています。"
                                           f"手動確認が必要です。先頭: {blocks[0]}"}, ensure_ascii=False))
        hook_counter(session, reset=True)
        return 0
    head = blocks[:10]
    more = f"\n…ほか{len(blocks) - 10}件" if len(blocks) > 10 else ""
    reason = ("スライド lint が不合格です。該当スライドだけを Edit で直し（全再生成しない）、"
              "素材不足が原因なら書き足さず本人に不足情報を尋ねてください。\n" + "\n".join(head) + more)
    print(json.dumps({"decision": "block", "reason": reason}, ensure_ascii=False))
    return 0


# ---- main -----------------------------------------------------------------
def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("files", nargs="*", type=Path)
    ap.add_argument("--hook", action="store_true", help="Claude Code Stop hook として動く")
    ap.add_argument("--titles", action="store_true", help="タイトル連読リストだけを出す")
    args = ap.parse_args()

    if args.hook:
        return run_hook()

    files = args.files or all_decks(repo_root(Path.cwd()))
    if not files:
        print("対象の .qmd がない", file=sys.stderr)
        return 0
    ng = load_ng_words()
    worst = 0
    for f in files:
        deck = parse_deck(f)
        if args.titles:
            print(title_list(deck))
            continue
        issues = check_deck(deck, ng)
        nb = sum(i.severity == "block" for i in issues)
        nw = len(issues) - nb
        for i in issues:
            print(i.fmt(f))
        print(f"-- {f}: block {nb} / warning {nw}")
        print()
        print(title_list(deck))
        print()
        if nb:
            worst = 2
    return worst


if __name__ == "__main__":
    sys.exit(main())
