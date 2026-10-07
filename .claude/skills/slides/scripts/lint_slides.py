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
承認後: git の HEAD の版が status: approved なら、budget の書き換えを block、本編のタイトルの変更・追加を warning
      （本人の承認を取り直した記録 <!-- reapproved: 本人「…」 YYYY-MM-DD --> を新しく書けば見ない）。
行動が「選ぶ・判断する」のデッキで、最後の枚に図も表も無ければ warning（判断の根拠を付録へ送らない）。
標本: 見出しの {denominator="…"} を1枚でも書いたデッキでは、数字のある本編の枚に宣言が無ければ warning。
本文の字数・行数に <style>・<script> の中は数えない。

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
    "confirm_title_chars_block": 56,   # 確認型（kind: confirm）のタイトルは2行まで（40px で1行約28字）
    "check_chars_block": 40,   # 確認点（::: {.check}）は1行
}

REQUIRED_META = ("audience", "action", "minutes", "budget", "status")
STATUSES = ("ghost", "approved")
KINDS = ("", "confirm")        # confirm = 確認型（決めたことを伝えて齟齬を確かめる。design-doc スキル）

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
META_RE = re.compile(r"<!--\s*(audience|action|minutes|budget|status|decided-by|kind)\s*:\s*(.*?)\s*-->")
IMAGE_RE = re.compile(r"!\[([^\]]*)\]\(([^)\s]+)[^)]*\)")
PLOT_RE = re.compile(r"\b(plt|imgfig|figs|sns|px|go|alt)\.\w|\.plot\(|\.savefig\(")
IMGFIG_RE = re.compile(r"\bimgfig\.\w+_figure\(")
PICK_RE = re.compile(r"すべて|全数|全部|全\d+枚|等間隔|上位|下位|大きい順|小さい順|無作為|抜粋|代表")
# 画像の中身についての言い切り。縮小した画像では見落としやすい（小さく写るもの、よく似た種）ので、元の大きさで確かめさせる
ABSOLUTE_RE = re.compile(r"ばかり|[1一]枚も|写っていない|写らない|だけが写|しか写|例外なく|全員|全頭|どれでもない|"
                         r"だけの写真|ラベルの誤り|ラベルが誤")
# 手で書いた枚数（写真の図を使うデッキで）。数え直した後に古い値が残るので、コードで数えた値を埋める
INLINE_CODE_RE = re.compile(r"`\{(?:python|r)\}[^`]*`")
COUNT_IDIOM_RE = re.compile(r"\d+枚目|[1１一]枚(?:ずつ|[1１一]枚|あたり|につき|と引き換え)")   # 順番・1枚ずつ などは枚数でない
HAND_COUNT_RE = re.compile(r"(?<![\d.,])\d+\s*枚")
APPENDIX_RE = re.compile(r"<!--\s*appendix\s*-->")
COMMENT_RE = re.compile(r"<!--.*?-->", re.S)
QUOTE_RE = re.compile(r"「[^」]*」")
# 確認型と主張の表（design-doc スキル）
CLAIMS_RE = re.compile(r"<!--\s*claims\s*:\s*([^>]*?)\s*-->")        # この枚の主張ID（claims.csv の id）
CHECK_COMMENT_RE = re.compile(r"<!--\s*check\s*:\s*(.*?)\s*-->")     # ゴースト段階の確認点
TBD_RE = re.compile(r"\[([^\]]*)\]\{[^}]*\.tbd\b[^}]*\}")               # まだ決めていない値（灰の点線の枠）
UNDECIDED_WORDS_RE = re.compile(r"未決|未定|確認中|決めていない|要確認")
# スライドの型（Claude Design「スライド型見本」。references/slide_types.md）。型ごとに、本文に必要な書き方
TYPE_RE = re.compile(r"<!--\s*type\s*:\s*(.*?)\s*-->")
MERMAID_RE = re.compile(r"^\{mermaid")
SLIDE_TYPES = {
    "text": lambda s: True,
    "pair": lambda s: any(".pair" in a for a in s.divs),
    "outcome": lambda s: any(".outcome" in a for a in s.divs),
    "number": lambda s: any(re.search(r"\{[^}]*\.big\b", t) for _, t in s.body),
    "roles": lambda s: any(".roles" in a for a in s.divs),
    "timeline": lambda s: any("figs.timeline(" in c for _, c in s.cells),
    "direction": lambda s: any("figs.direction(" in c for _, c in s.cells),
    "chart": lambda s: any(PLOT_RE.search(c) and not IMGFIG_RE.search(c) for i, c in s.cells if not MERMAID_RE.match(i)),
    "flow": lambda s: any(MERMAID_RE.match(i) for i, _ in s.cells),
    "table": lambda s: any(re.match(r"\s*\|", t) for _, t in s.body) or any("Markdown(" in c for _, c in s.cells),
    "images": lambda s: bool(s.images) or any(IMGFIG_RE.search(c) for _, c in s.cells),
}
TYPE_MARKUP = {
    "pair": ":::: {.columns .pair}", "outcome": "::: {.outcome}", "number": "[値]{.big}",
    "roles": ":::: {.columns .roles}", "timeline": "figs.timeline(...)", "direction": "figs.direction(...)",
    "chart": "figs.bars(...) か図を描くセル", "flow": "{mermaid} のセル", "table": "Markdown の表",
    "images": "imgfig.*_figure(...) か ![…](…)",
}
INLINE_STYLE_RE = re.compile(r"\bstyle\s*=\s*[\"']")
RAW_OPEN_RE = re.compile(r"^\s*<(style|script)\b", re.I)          # 見た目の調整の <style>・<script> は本文として数えない
# 承認後の変更（budget・タイトル）を本人が承認し直した記録。本人の原文を「」で写す
REAPPROVED_RE = re.compile(r"<!--\s*reapproved\s*:\s*(.*?)\s*-->", re.S)
# 行動が「選ぶ」デッキ（最後の枚に、選択肢を比べる図か表を置く）。「決める」は確認型の「決めた点を聞く」にも出るので見ない
ACTION_CHOICE_RE = re.compile(r"選ぶ|選択|選んで|選定|採否|どれを|どちらを|判断する|承認する")
# 枚ごとの標本（分母）: 見出しの属性 {denominator="人手で分類し直した写真"}
DENOMINATOR_RE = re.compile(r"\bdenominator\s*=\s*\"([^\"]*)\"")
SOURCE_SPAN_RE = re.compile(r"\[[^\]]*\]\{[^}]*\.source\b[^}]*\}")
# 本文・見出し・div で使うクラス（{.e1} など）。テーマに定義が無いと、書いても見た目が変わらず素通りする
ATTR_BLOCK_RE = re.compile(r"\{([^{}]*)\}")
CLASS_TOKEN_RE = re.compile(r"(?<![\w-])\.([A-Za-z][\w-]*)")
CSS_PATH_RE = re.compile(r"[\w./~-]+\.s?css\b")
# Quarto・reveal.js・このリポジトリのフィルタが用意するクラス（テーマに書かなくても効く）
BUILTIN_CLASSES = {
    "columns", "column", "notes", "aside", "footer", "incremental", "nonincremental", "fragment", "smaller", "scrollable",
    "center", "nostretch", "absolute", "hidden", "unnumbered", "unlisted", "panel-tabset", "content-visible",
    "content-hidden", "lightbox", "mark", "underline", "smallcaps", "strike", "grow", "shrink", "semi-fade-out",
    "current-visible", "appendix", "stretch", "auto-animate", "nocite",
}
BUILTIN_PREFIXES = ("r-", "fade-", "highlight-", "callout", "quarto-", "cell-", "fig-", "tbl-")
DATE_RE = re.compile(r"\d{4}[-/年]\d{1,2}(?:[-/月]\d{1,2}日?)?|\d{4}年")


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
    checks: list[tuple[int, str]] = field(default_factory=list)      # ::: {.check} の中の行（確認型の確認点）
    check_divs: int = 0                                                # ::: {.check} の個数
    undecided: bool = False                                            # ::: {.undecided}（まだ決めていない点の一覧）がある
    claims: list[str] = field(default_factory=list)                    # <!-- claims: C1,C2 --> の主張ID
    types: list[str] = field(default_factory=list)                     # <!-- type: pair --> のスライドの型
    divs: list[str] = field(default_factory=list)                      # fenced div の属性（{.columns .pair} など）
    cells: list[tuple[str, str]] = field(default_factory=list)        # 実行するセル (情報 {python}/{mermaid}, 中身)
    raw_html: list[tuple[int, str]] = field(default_factory=list)     # <style>・<script> の行（本文に数えない）
    denominator: str | None = None                                    # 見出しの {denominator="…"}（この枚の数字の標本）
    heading_attrs: str = ""                                            # 見出しの {…}（{.nostretch} など）
    fig_size_opts: list[tuple[int, str]] = field(default_factory=list)  # {python} のセルの #| fig-width / fig-height


@dataclass
class Deck:
    path: Path
    meta: dict[str, tuple[int, str]]
    slides: list[Slide]
    appendix_line: int | None
    all_lines: list[str]
    preamble_line: int | None = None   # 最初のスライド見出しより前にある本文・コードの行
    front: dict = field(default_factory=dict)   # YAML の front matter（1段目のキーだけ）


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


def parse_deck(path: Path, text: str | None = None) -> Deck:
    text = path.read_text(encoding="utf-8") if text is None else text
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
    div_stack: list[tuple[int, str]] = []    # (colon数, 属性)
    in_comment = False
    preamble_line = None
    code_start = 0
    cell_info = ""
    raw_tag = None            # <style>/<script> の中（閉じタグまで本文に数えない）

    def in_notes() -> bool:
        return any(".notes" in a or a == "notes" for _, a in div_stack)

    def in_check() -> bool:
        return any(".check" in a for _, a in div_stack)

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
                    if executable and not hidden:
                        cur.cells.append((cell_info, "\n".join(l for _, l in body)))
                    if executable and re.match(r"\{python", cell_info):
                        cur.fig_size_opts.extend((n, l.strip()) for n, l in code_buf
                                                 if re.match(r"#\|\s*fig-(?:width|height)\s*:", l.strip()))
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
            cell_info = info
            in_code = (m.group(2), info.startswith("{"), default_echo)
            continue

        # <style>・<script>（見た目の調整。本文の字数・行数に数えない）
        if raw_tag:
            if cur:
                cur.raw_html.append((ln, raw))
            if re.search(rf"</{raw_tag}\s*>", raw, re.I):
                raw_tag = None
            continue
        m = RAW_OPEN_RE.match(raw)
        if m:
            if cur:
                cur.raw_html.append((ln, raw))
            if not re.search(rf"</{m.group(1)}\s*>", raw, re.I):
                raw_tag = m.group(1).lower()
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
            attrs = m.group(2)
            div_stack.append((len(m.group(1)), attrs))
            if cur:
                cur.divs.append(attrs)
            if cur and ".check" in attrs:
                cur.check_divs += 1
            if cur and ".undecided" in attrs:
                cur.undecided = True
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
            attrs = re.search(r"\{([^}]*)\}\s*$", m.group(2))
            title = re.sub(r"\s*\{[^}]*\}\s*$", "", m.group(2)).strip()
            cur = Slide(len(slides) + 1, ln, title, len(m.group(1)), appendix)
            den = DENOMINATOR_RE.search(attrs.group(1)) if attrs else None
            cur.denominator = den.group(1).strip() if den else None
            cur.heading_attrs = attrs.group(1) if attrs else ""
            slides.append(cur)
            continue
        if HR_RE.match(raw):
            cur = Slide(len(slides) + 1, ln, "", 0, appendix)
            slides.append(cur)
            continue

        if cur and raw.strip():
            cur.body.append((ln, raw))
            if in_check():
                cur.checks.append((ln, raw))
            cur.images.extend((ln, mm.group(1).strip(), mm.group(2)) for mm in IMAGE_RE.finditer(raw))
        elif cur is None and raw.strip() and preamble_line is None:
            preamble_line = ln

    for s in slides:
        for _, c in s.comments:
            for mm in CLAIMS_RE.finditer(c):
                s.claims.extend(x for x in re.split(r"[,、\s]+", mm.group(1)) if x)
            for mm in TYPE_RE.finditer(c):
                s.types.extend(x for x in re.split(r"[,、\s]+", mm.group(1)) if x)
    return Deck(path, meta, slides, appendix_line, lines, preamble_line, fm)


CLAIMS_REQUIRED_RE = re.compile(r"^\s*claims\s*:\s*[\"']?required[\"']?\s*$", re.M)


def claims_required(deck: Deck) -> bool:
    """`claims: required` の宣言があるか。デッキの YAML か、デッキから上に辿った _metadata.yml・_quarto.yml
    （`metadata:` の下に書いてもよい）。vault のように decks/_quarto.yml に1回書けば全デッキに効く。"""
    if str(deck.front.get("claims", "")).strip().strip("\"'") == "required":
        return True
    for d in [deck.path.resolve().parent, *deck.path.resolve().parents]:
        for name in ("_metadata.yml", "_quarto.yml"):
            f = d / name
            if f.is_file() and CLAIMS_REQUIRED_RE.search(f.read_text(encoding="utf-8", errors="replace")):
                return True
        if (d / ".git").exists():
            break
    return False


def load_claims_for(deck_dir: Path):
    """デッキのフォルダの claims.csv（主張の表。design-doc スキルの claims.py が正本）。
    (主張の辞書, block, warning)。表が無ければ (None, [], [])。表に path・rev・quote の列があれば出典とも照らす。"""
    f = deck_dir / "claims.csv"
    if not f.exists():
        return None, [], []
    try:
        sys.path.insert(0, str(SKILL_DIR.parent / "design-doc" / "scripts"))
        import claims as claims_mod  # type: ignore
    except Exception:
        return None, [f"claims.csv があるが design-doc スキルの claims.py を読めない: {f}"], []
    rows = claims_mod.load(f)
    errors = [f"claims.csv: {e}" for e in claims_mod.validate(rows, f.parent)]
    warns = [f"claims.csv: {w}" for w in claims_mod.warnings(rows, f.parent)]
    return {r["id"]: r for r in rows}, errors, warns


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


def check_title(s: Slide, title_limit: float = LIMITS["title_chars_block"]) -> list[Issue]:
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
    if n > title_limit:
        out.append(Issue("block", s.line, s, "title-length",
                         f"タイトル全角{n:g}字 > {title_limit:g}字。so-whatと数字だけ残して縮める"))
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


def approved_baseline(path: Path) -> Deck | None:
    """git の HEAD にある同じデッキの版を、承認済み（status: approved）なら返す（承認後の budget・タイトルの変更を見るため）。"""
    try:
        root = subprocess.run(["git", "rev-parse", "--show-toplevel"], cwd=Path(path).resolve().parent,
                              capture_output=True, text=True, check=True).stdout.strip()
        rel = Path(path).resolve().relative_to(Path(root).resolve()).as_posix()
        r = subprocess.run(["git", "show", f"HEAD:{rel}"], cwd=root, capture_output=True, encoding="utf-8")
    except Exception:
        return None
    if r.returncode != 0:
        return None
    base = parse_deck(Path(path), r.stdout)
    return base if base.meta.get("status", (0, ""))[1] == "approved" else None


def _reapprovals(deck: Deck) -> set[str]:
    """本人が承認し直した記録 <!-- reapproved: 本人「…」 YYYY-MM-DD -->（本人の原文と日付があるものだけ）。"""
    found = REAPPROVED_RE.findall("\n".join(deck.all_lines))
    return {" ".join(v.split()) for v in found if "「" in v and re.search(r"\d{4}-\d{2}-\d{2}", v)}


def check_approved_changes(deck: Deck, baseline: Deck | None) -> list[Issue]:
    """承認済みの版（git の HEAD）と比べて、budget とタイトルの変更を知らせる。承認し直した記録が新しく足されていれば見ない。"""
    status = deck.meta.get("status", (0, ""))[1]
    if baseline is None or status != "approved" or (_reapprovals(deck) - _reapprovals(baseline)):
        return []
    issues: list[Issue] = []
    old, new = baseline.meta.get("budget", (0, ""))[1], deck.meta.get("budget", (0, ""))[1]
    if old.isdigit() and new.isdigit() and old != new:
        issues.append(Issue("block", deck.meta["budget"][0], None, "budget-changed",
                            f"承認済みの budget を {old} から {new} に書き換えている。枚数は本人と合意した約束なので、"
                            f"超えるなら appendix へ送るか、本人に承認を取り直して `<!-- reapproved: 本人「…」 YYYY-MM-DD -->` を書く"))
    before = [t.title for t in baseline.slides if not t.appendix and t.level == 2]
    after = [t for t in deck.slides if not t.appendix and t.level == 2]
    changed = [t for t in after if t.title not in before]
    gone = [t for t in before if t not in {x.title for x in after}]
    if changed or gone:
        what = "、".join([f"「{t.title}」" for t in changed[:3]] + [f"消えた「{t}」" for t in gone[:2]])
        issues.append(Issue("warning", changed[0].line if changed else 1, changed[0] if changed else None,
                            "approved-title-changed",
                            f"承認済みの骨子から本編のタイトルが変わった（{what}）。タイトルは本人に変更を提案し、承認を得てから"
                            f"変える。承認を得たら `<!-- reapproved: 本人「…」 YYYY-MM-DD -->` を書く（references/phases.md のフェーズ3）"))
    return issues


def _style_files(deck: Deck) -> list[Path]:
    """デッキに効くスタイルのファイル: スキルのリポジトリの theme/custom.scss（render_check.sh がプロジェクトの外の
    デッキに当てる）、デッキを含む Quarto プロジェクトの _quarto.yml とデッキの YAML が名指す .scss/.css。"""
    deck_dir = deck.path.resolve().parent
    files = [SKILL_DIR.parent.parent.parent / "theme" / "custom.scss"]
    front_end, _ = parse_front_matter(deck.all_lines)
    refs = [(deck_dir, "\n".join(deck.all_lines[:front_end]))]
    for d in [deck_dir, *deck_dir.parents]:
        if (d / "_quarto.yml").exists():
            refs.append((d, (d / "_quarto.yml").read_text(encoding="utf-8")))
            break
    for base, text in refs:
        files += [base / Path(m).expanduser() for m in CSS_PATH_RE.findall(text)]
    return [f for f in dict.fromkeys(files) if f.is_file()]


def defined_classes(deck: Deck) -> set[str] | None:
    """テーマ・デッキの <style> に定義のあるクラス。スタイルのファイルが1つも見つからなければ None（検査しない）。"""
    files = _style_files(deck)
    if not files:
        return None
    text = "\n".join(f.read_text(encoding="utf-8", errors="replace") for f in files)
    text += "\n".join(t for s in deck.slides for _, t in s.raw_html)
    text = re.sub(r"/\*.*?\*/|//[^\n]*", "", text, flags=re.S)   # コメントの中の「.e1」は定義でない
    return set(re.findall(r"\.([A-Za-z][\w-]*)", text))


def used_classes(s: Slide) -> list[tuple[int, str]]:
    """スライドで使うクラス（見出しの {…}、fenced div、本文の [文字]{.cls}）。"""
    found = [(s.line, c) for c in CLASS_TOKEN_RE.findall(s.heading_attrs)]
    found += [(s.line, c) for a in s.divs for c in CLASS_TOKEN_RE.findall(a if a.startswith("{") else "." + a)]
    for ln, t in s.body:
        for block in ATTR_BLOCK_RE.findall(INLINE_CODE_RE.sub("", t)):
            found += [(ln, c) for c in CLASS_TOKEN_RE.findall(block)]
    return found


def has_content(s: Slide) -> bool:
    """表紙・区切りの枚（見出しだけで本文の無い枚）でないか。"""
    return bool(s.body or s.cells or s.images or s.figures)


def sentence_count(lines: list[tuple[int, str]]) -> int:
    """見える文の数（1行に「。」が複数あればその数、無ければ1）。"""
    n = 0
    for _, t in lines:
        t = strip_md(t)
        if t:
            n += max(1, len([x for x in re.split(r"[。！？]", t) if x.strip()]))
    return n


def scope_line(deck: Deck) -> str:
    """検査が見た範囲の1行。block 0 は「出典と照合した」ことを意味しない（10-06 のデッキでは、本文の平叙文を出典と
    突き合わせたものが0文だったのに「NG語0件・数値未照合0件」とだけ報告した）。"""
    main = [s for s in deck.slides if not s.appendix and has_content(s)]
    with_claims = [s for s in main if s.claims]
    unchecked = sum(sentence_count(s.body) for s in main if not s.claims)
    return (f"-- 見た範囲: 本編 {len(main)}枚（本文のある枚）／ claims のある枚 {len(with_claims)}枚／"
            f" claims の無い枚の文 {unchecked}文（出典の文と照らしていない。lint は数字と決まった文字列しか見ない）")


def check_deck(deck: Deck, ng: dict[str, list[re.Pattern]], baseline: Deck | None = None) -> list[Issue]:
    issues: list[Issue] = []
    uses_imgfig = any("imgfig" in line for line in deck.all_lines)    # 写真の図を使うデッキ（枚数を手で書かせない）
    asserted = {int(n) for line in deck.all_lines if re.match(r"\s*assert\b", line)
                for n in re.findall(r"(?<![\w.])\d+(?![\w.])", line)}   # 描画のコードで検算した数（手で書いてもよい）

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

    kind = deck.meta.get("kind", (0, ""))[1]
    if kind not in KINDS:
        issues.append(Issue("block", deck.meta["kind"][0], None, "gate-kind", f"kind は confirm（確認型）だけ: {kind!r}"))
    confirm = kind == "confirm"
    title_limit = LIMITS["confirm_title_chars_block"] if confirm else LIMITS["title_chars_block"]
    has_undecided = any(s.undecided for s in deck.slides)
    claims, claim_errors, claim_warns = load_claims_for(deck.path.parent)
    required = claims_required(deck)
    if required and claims is None and not claim_errors:
        issues.append(Issue("block", 1, None, "claims-file",
                            "`claims: required` なのに、デッキのフォルダに claims.csv が無い。本文の各枚の主張を、出典の文（quote）と"
                            "版（rev）つきで表にする（design-doc/references/claims.md）"))
    for w in claim_warns:
        issues.append(Issue("warning", 1, None, "claims-source", w))
    known_classes = defined_classes(deck)
    for e in claim_errors:
        issues.append(Issue("block", 1, None, "claims-file", e))

    if deck.preamble_line:
        issues.append(Issue("block", deck.preamble_line, None, "preamble",
                            "最初の `##` より前の本文・コードセルは空のスライドになる。1枚目の中へ移す（計算だけのセルは `#| include: false` なら可）"))

    main = [s for s in deck.slides if not s.appendix]
    if budget is not None and len(main) > budget:
        issues.append(Issue("block", main[budget].line, main[budget], "budget",
                            f"本編{len(main)}枚 > budget {budget}枚。統合・削除するか `<!-- appendix -->` 以降へ移す"))
    issues.extend(check_approved_changes(deck, baseline))

    # 行動が「選ぶ」デッキ: 最後の枚（行動を頼む枚）に、選択肢を比べる図か表を置く（根拠を付録へ送らない）
    action = deck.meta.get("action", (0, ""))[1]
    if main and status == "approved" and not confirm and ACTION_CHOICE_RE.search(action):
        last = main[-1]
        shown = (last.figures or last.images or any(re.match(r"\s*\|", t) for _, t in last.body)
                 or any(IMGFIG_RE.search(c) or MERMAID_RE.match(i) or "Markdown(" in c for i, c in last.cells))
        if not shown and (last.body or last.cells):
            moved = any(t.figures or t.images for t in deck.slides if t.appendix)
            issues.append(Issue("warning", last.line, last, "action-evidence",
                                "行動が「選ぶ・判断する」のデッキなのに、最後の枚（行動を頼む枚）に図も表も無い。選択肢を比べる図か表を"
                                "この枚に置く" + ("（付録の図を本編へ戻す。本編の字数・箇条書きの上限に当たるなら、文を減らす）" if moved else "")))

    # 枚ごとの標本（分母）。1枚でも {denominator="…"} を書いたデッキでは、数字のある本編の枚すべてに書く
    if any(t.denominator for t in deck.slides):
        for t in main:
            if t.level != 2 or t.denominator:
                continue
            texts = [t.title] + [x for _, x in t.body]
            if any(INLINE_CODE_RE.search(x) or re.search(r"\d", DATE_RE.sub("", SOURCE_SPAN_RE.sub("", x))) for x in texts):
                issues.append(Issue("warning", t.line, t, "denominator-missing",
                                    "数字のある枚に標本の宣言が無い。見出しの末尾に `{denominator=\"人手で分類し直した写真\"}` のように、"
                                    "この枚の数字が何の集まりから数えたものかを書く（デッキに標本が2つ以上あるとき、取り違えを防ぐ）"))

    hedge_total = 0
    for s in deck.slides:
        issues.extend(check_title(s, title_limit))

        # placeholder はどこにあっても block（タイトル・本文・ノート・コード）。
        # まだ決めていない値 `[…]{.tbd}` は、1枚目に「まだ決めていない点」の一覧があるときだけ許す（未決を隠さず示す型）
        texts = [(s.line, s.title)] + s.body + s.notes + s.code
        tbd_lines = [ln for ln, t in texts if TBD_RE.search(t)]
        for ln, t in texts:
            if TBD_RE.search(t):
                if not has_undecided:
                    issues.append(Issue("block", ln, s, "tbd-without-list",
                                        "まだ決めていない値 `[…]{.tbd}` を置くなら、1枚目に `::: {.undecided}` で"
                                        "「まだ決めていない点」の一覧も置く（design-doc/references/confirm_deck.md）"))
                    continue
                t = TBD_RE.sub("", t)
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

        # 確認型: 1枚＝決めたこと1つ＋確認点1つ（ゴースト段階は <!-- check: --> のコメントでよい）
        if confirm and not s.appendix and status != "ghost":
            if s.check_divs == 0:
                issues.append(Issue("block", s.line, s, "check-missing",
                                    "確認型は各枚に確認点を1つ置く: `::: {.check}` 聴衆に確かめてほしい点を1行 `:::`"))
            elif s.check_divs > 1:
                issues.append(Issue("block", s.checks[0][0] if s.checks else s.line, s, "check-multiple",
                                    f"確認点が{s.check_divs}個。1枚に1つにする（決めたことが2つなら枚を分ける）"))
            else:
                n = sum(zen_len(strip_md(t)) for _, t in s.checks)
                if n > LIMITS["check_chars_block"]:
                    issues.append(Issue("block", s.checks[0][0], s, "check-length",
                                        f"確認点 全角{n:g}字 > {LIMITS['check_chars_block']}字。確かめてほしい点だけを1行で"))

        # スライドの型（references/slide_types.md）。骨子で選んだ型の書き方で本文を書く
        unknown_types = [t for t in s.types if t not in SLIDE_TYPES]
        if unknown_types:
            issues.append(Issue("block", s.line, s, "type-unknown",
                                f"知らない型 {', '.join(unknown_types)}。{'/'.join(SLIDE_TYPES)} から選ぶ（references/slide_types.md）"))
        elif len(s.types) > 1:
            issues.append(Issue("block", s.line, s, "type-multiple",
                                f"型が{len(s.types)}つ（{', '.join(s.types)}）。1枚に1つ。主のほうを書くか、主張が2つなら枚を分ける"))
        elif not s.types and not s.appendix and s.level == 2:
            issues.append(Issue("warning", s.line, s, "type-missing",
                                "`<!-- type: text -->` などで、この枚の型を選ぶ（pair・outcome・number・roles・timeline・"
                                "direction・chart・flow・table・images。references/slide_types.md）"))
        elif s.types and status != "ghost" and (s.body or s.cells) and not SLIDE_TYPES[s.types[0]](s):
            issues.append(Issue("warning", s.line, s, "type-markup",
                                f"型 {s.types[0]} なのに `{TYPE_MARKUP[s.types[0]]}` が無い。型の書き方で書くか、型を選び直す"))
        if known_classes is not None:
            unknown_cls = [(ln, c) for ln, c in used_classes(s) if c not in known_classes
                           and c not in BUILTIN_CLASSES and not c.startswith(BUILTIN_PREFIXES)]
            if unknown_cls:
                names = ", ".join(dict.fromkeys(f".{c}" for _, c in unknown_cls))
                issues.append(Issue("warning", unknown_cls[0][0], s, "class-undefined",
                                    f"クラス {names} はテーマ（theme/custom.scss）にもデッキの <style> にも定義が無く、書いても"
                                    "見た目が変わらない。テーマにある部品（slide_types.md）を使うか、theme/custom.scss に足す"))
        for ln, opt in s.fig_size_opts:
            issues.append(Issue("warning", ln, s, "cell-fig-size",
                                f"`{opt}` は Jupyter（{{python}} のセル）では効かず、文書の既定（_quarto.yml の fig-width・"
                                "fig-height）で描かれる。図の大きさは `plt.subplots(figsize=(幅, 高さ))` か imgfig の "
                                "max_height_in・thumb_in で決める"))
        styled = [ln for ln, t in s.body if INLINE_STYLE_RE.search(t)]
        if styled:
            issues.append(Issue("warning", styled[0], s, "inline-style",
                                "本文に style= を直接書かない。theme/custom.scss の部品を使うか、足りなければ部品を足す"))

        # 主張の表（claims.csv）との対応。未決の主張を載せる枚は、未決と分かる形にする
        if claims is not None:
            unknown = [c for c in s.claims if c not in claims]
            if unknown:
                issues.append(Issue("block", s.line, s, "claims-unknown", f"claims.csv にない主張ID: {', '.join(unknown)}"))
            pending = [c for c in s.claims if c in claims and claims[c]["status"] == "未決"]
            shown = bool(tbd_lines) or s.undecided or any(
                UNDECIDED_WORDS_RE.search(strip_md(t)) for _, t in [(s.line, s.title)] + s.body)
            if pending and not shown:
                issues.append(Issue("block", s.line, s, "claims-undecided-hidden",
                                    f"未決の主張（{', '.join(pending)}）を載せる枚は、未決と分かる形にする"
                                    "（`[…]{.tbd}`、`::: {.undecided}`、または「確認中」「未決」の語）"))
            if confirm and not required and not s.appendix and not s.claims and status != "ghost":
                issues.append(Issue("warning", s.line, s, "claims-missing",
                                    "`<!-- claims: C1,C2 -->` で、この枚の主張の出所（claims.csv の id）を記録する"))
        if required and not s.appendix and not s.claims and status != "ghost" and has_content(s):
            issues.append(Issue("block", s.line, s, "claims-missing",
                                "`claims: required` のデッキでは、本編の各枚に `<!-- claims: C1,C2 -->` を書く。数字が無く決まった文字列も"
                                "含まない文（限定句を落とした言い換え・原文に無い否定）は lint では捕まらないので、出典の文と表で照らす"))
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
                                    f"画像について言い切っている（{words}）。`imgfig.py sheet` で該当する画像を元の写真で"
                                    "全枚見て（端・奥・物の陰まで）、1枚も外れないことを確かめる"))

        if uses_imgfig:                # 手で書いた枚数（タイトルは見ない。appendix も対象）
            hand = [(ln, m.group(0)) for ln, t in s.body
                    for m in HAND_COUNT_RE.finditer(COUNT_IDIOM_RE.sub("", strip_md(INLINE_CODE_RE.sub("〇", t))))
                    if int(re.match(r"\d+", m.group(0)).group(0)) not in asserted]
            if hand:
                words = "、".join(dict.fromkeys(w for _, w in hand))
                issues.append(Issue("block", hand[0][0], s, "hand-count",
                                    f"枚数を手で書いている（{words}）。コードで数えた値を `{{python}} len(...)` で埋めるか、"
                                    "描画のコードに assert で検算を書く（分け直した後に古い数が残るのを防ぐ）。"
                                    "選び方の注記は `imgfig.pick_note` で書く"))

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
    if deck.meta.get("kind", (0, ""))[1]:
        out.append(f"型: {deck.meta['kind'][1]}（1枚＝決めたこと1つ＋確認点1つ）")
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
        chk = " ".join(strip_md(t) for _, t in s.checks) or next(
            (CHECK_COMMENT_RE.search(c).group(1) for _, c in s.comments if CHECK_COMMENT_RE.search(c)), "")
        if chk:
            line += f"\n      確認点: {chk}"
        if s.types:
            line += f"\n      型: {', '.join(s.types)}"
        if s.denominator:
            line += f"\n      標本: {s.denominator}"
        if s.claims:
            line += f"\n      主張: {', '.join(s.claims)}"
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
        for i in check_deck(deck, ng, approved_baseline(p)):
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
        issues = check_deck(deck, ng, approved_baseline(f))
        nb = sum(i.severity == "block" for i in issues)
        nw = len(issues) - nb
        for i in issues:
            print(i.fmt(f))
        print(f"-- {f}: block {nb} / warning {nw}")
        print(scope_line(deck))
        print()
        print(title_list(deck))
        print()
        if nb:
            worst = 2
    return worst


if __name__ == "__main__":
    sys.exit(main())
