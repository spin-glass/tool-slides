#!/usr/bin/env python3
"""検証の採点: 各実行のデッキを描画し直し、全スライドを画像にし、指標を出す。

    python score.py                 # 全部の実行を採点して results/ に書く
    python score.py image-fable-S3-r1

描画は実行時の成果物を信用せず、ここでやり直す（_freeze を消して再実行）。
指標は描画した HTML から取る（qmd の書き方が違っても同じ基準で測るため）。
"""
from __future__ import annotations

import csv
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
from html.parser import HTMLParser
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parent.parent
WORK = Path(os.environ.get("MVS_WORK", Path(tempfile.gettempdir()) / "tool-slides-mvs"))
RESULTS = HERE / "results"
DECK = "decks/farm-errors"
CHROME = "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome"

sys.path.insert(0, str(ROOT / ".claude/skills/slides/scripts"))
import lint_slides as lint  # noqa: E402

NG = lint.load_ng_words()
APPENDIX_TITLE = re.compile(r"^\s*(付録|補足|参考|出典|クレジット|画像の出典|写真の出典|Appendix|APPENDIX|Backup|Credits?|References?)")
VOID = {"img", "br", "hr", "meta", "link", "input", "source", "col", "wbr", "area", "base", "embed", "track"}
BUDGET_10MIN = 6


# ---- 描画した HTML をスライドに分ける ---------------------------------------
class Slides(HTMLParser):
    """reveal の <section> を葉の単位で取り出す（縦に積んだスライドも1枚ずつ）。"""

    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.stack: list[str] = []           # 開いている要素（section は "section"）
        self.sections: list[dict] = []       # 開いている section の入れ子
        self.leaves: list[dict] = []
        self.top = -1                        # 最上位 section の番号
        self.notes = self.skip = self.title = 0

    def handle_starttag(self, tag, attrs):
        a = dict(attrs)
        cls = a.get("class") or ""
        if tag == "section":
            depth = len(self.sections)
            if depth == 0:
                self.top += 1
                path = [self.top]
            else:
                parent = self.sections[-1]
                parent["children"] += 1
                path = parent["path"] + [parent["children"] - 1]
            self.sections.append({"path": path, "children": 0, "title": "", "text": [], "li": 0, "img": 0,
                                  "table": 0, "notes": False, "code_lines": 0,
                                  "is_title_slide": "quarto-title-block" in cls or a.get("id") == "title-slide"})
        cur = self.sections[-1] if self.sections else None
        if tag not in VOID:
            self.stack.append(tag)
            if tag == "aside" and "notes" in cls:
                self.notes += 1
                if cur:
                    cur["notes"] = True
            elif self.notes:
                self.notes += 1
            if tag in ("script", "style"):
                self.skip += 1
            if cur and not self.notes and tag in ("h1", "h2", "h3") and not cur["title"] and not self.title:
                self.title = 1
        if cur and not self.notes:
            if tag == "li":
                cur["li"] += 1
            elif tag == "img":
                cur["img"] += 1
            elif tag == "table":
                cur["table"] += 1

    def handle_endtag(self, tag):
        if tag in VOID or not self.stack:
            return
        while self.stack and self.stack[-1] != tag:       # 閉じ忘れを読み飛ばす
            self.stack.pop()
        if self.stack:
            self.stack.pop()
        if self.notes:
            self.notes -= 1
        if tag in ("script", "style") and self.skip:
            self.skip -= 1
        if tag in ("h1", "h2", "h3") and self.title:
            self.title = 0
        if tag == "section" and self.sections:
            s = self.sections.pop()
            if s["children"] == 0:
                self.leaves.append(s)

    def handle_data(self, data):
        if not self.sections or self.skip or self.notes:
            return
        cur = self.sections[-1]
        if self.title:
            cur["title"] += data
        elif data.strip():
            cur["text"].append(data.strip())


class Tree(HTMLParser):
    """画像に付いた説明文（キャプション）を見分けるための、要素の木。"""

    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.root = {"tag": "root", "cls": "", "kids": [], "up": None}
        self.cur = self.root

    def handle_starttag(self, tag, attrs):
        node = {"tag": tag, "cls": dict(attrs).get("class") or "", "kids": [], "up": self.cur}
        self.cur["kids"].append(node)
        if tag not in VOID:
            self.cur = node

    def handle_endtag(self, tag):
        n = self.cur
        while n is not self.root and n["tag"] != tag:
            n = n["up"]
        if n is not self.root:
            self.cur = n["up"]

    def handle_data(self, data):
        if data.strip():
            self.cur["kids"].append({"tag": "#text", "text": data.strip(), "up": self.cur})


def n_imgs(node: dict) -> int:
    if "imgs" not in node:
        node["imgs"] = (node["tag"] == "img") + sum(n_imgs(k) for k in node.get("kids", []))
    return node["imgs"]


def caption_chars(html_text: str) -> list[float]:
    """葉のスライドごとに、画像1枚ごとの説明文の字数を返す（parse_slides と同じ順）。

    画像を2枚以上並べたスライドで、「画像をちょうど1枚含む要素」の中にある文字を、その画像の説明文とみなす。
    図の中に説明文を描き込むデッキ（文字が HTML に出ない）と、HTML で画像の下に書くデッキを、同じ基準で比べるために使う。
    """
    t = Tree()
    start = html_text.find('<div class="slides')
    t.feed(html_text[start:] if start >= 0 else html_text)
    out: list[float] = []

    def walk_text(node, section, acc):
        for k in node.get("kids", []):
            if k["tag"] == "#text":
                up, cap = k["up"], False
                while up is not section and up is not None:
                    if up["tag"] in ("script", "style") or (up["tag"] == "aside" and "notes" in up["cls"]):
                        cap = None
                        break
                    if up["tag"] in ("h1", "h2", "h3"):
                        cap = None
                        break
                    if n_imgs(up) == 1:
                        cap = True
                    up = up["up"]
                if cap:
                    acc[0] += lint.zen_len(k["text"])
            elif k["tag"] != "section":
                walk_text(k, section, acc)

    def walk(node):
        for k in node.get("kids", []):
            if k["tag"] == "section":
                if any(c["tag"] == "section" for c in k["kids"]):
                    walk(k)
                else:
                    acc = [0.0]
                    if n_imgs(k) >= 2:
                        walk_text(k, k, acc)
                    out.append(acc[0])
            elif k["tag"] != "#text":
                walk(k)

    walk(t.root)
    return out


def parse_slides(html_path: Path) -> list[dict]:
    p = Slides()
    text = html_path.read_text(encoding="utf-8")
    start = text.find('<div class="slides')
    p.feed(text[start:] if start >= 0 else text)
    caps = caption_chars(text)
    for n, s in enumerate(p.leaves):
        s["caption_chars"] = caps[n] if len(caps) == len(p.leaves) else 0.0
    return p.leaves


# ---- 描画とスクショ --------------------------------------------------------
def render(ws: Path, deck: str) -> tuple[bool, str]:
    for d in ("_freeze", "_output", ".quarto"):
        shutil.rmtree(ws / d, ignore_errors=True)
    env = {k: v for k, v in os.environ.items() if not k.startswith("CLAUDE")}
    env["QUARTO_PYTHON"] = str(ws / ".venv/bin/python")
    r = subprocess.run(["quarto", "render", f"{deck}/index.qmd", "--to", "revealjs"], cwd=ws, env=env,
                       capture_output=True, text=True, timeout=900)
    html = ws / "_output" / deck / "index.html"
    return r.returncode == 0 and html.exists(), (r.stderr or r.stdout)[-1500:]


def shots(ws: Path, deck: str, slides: list[dict], out: Path) -> None:
    shutil.rmtree(out, ignore_errors=True)
    out.mkdir(parents=True)
    html = ws / "_output" / deck / "index.html"
    procs = []
    for n, s in enumerate(slides):
        url = f"file://{html}?fragments=false#/" + "/".join(str(i) for i in s["path"])
        procs.append(subprocess.Popen(
            [CHROME, "--headless=new", "--disable-gpu", "--hide-scrollbars", "--window-size=1280,720",
             "--run-all-compositor-stages-before-draw", "--virtual-time-budget=8000",
             f"--screenshot={out / f'slide-{n + 1:02d}.png'}", url],
            stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL))
        if len(procs) == 4:
            for p in procs:
                p.wait()
            procs = []
    for p in procs:
        p.wait()


def contact_sheet(shots_dir: Path, out: Path, label: str) -> None:
    from PIL import Image, ImageDraw

    files = sorted(shots_dir.glob("slide-*.png"))
    if not files:
        return
    cols, w, h, head = 4, 480, 270, 26
    rows = (len(files) - 1) // cols + 1
    sheet = Image.new("RGB", (cols * w, head + rows * h), "white")
    ImageDraw.Draw(sheet).text((8, 6), label, fill="black")
    for n, f in enumerate(files):
        im = Image.open(f).convert("RGB").resize((w - 4, h - 4))
        sheet.paste(im, ((n % cols) * w + 2, head + (n // cols) * h + 2))
    out.parent.mkdir(parents=True, exist_ok=True)
    sheet.save(out, "JPEG", quality=82)


# ---- 指標 -----------------------------------------------------------------
def n_main_slides(qmd: Path, slides: list[dict]) -> int:
    """本編の枚数（表紙を除く）。appendix の印があればそこまで。無ければ付録・出典らしい見出しの手前まで。"""
    body = [s for s in slides if not s["is_title_slide"]]
    text = qmd.read_text(encoding="utf-8")
    if lint.APPENDIX_RE.search(text):
        deck = lint.parse_deck(qmd)
        n = sum(not s.appendix for s in deck.slides)
        if len(deck.slides) == len(body):
            return n
    for n, s in enumerate(body):
        if APPENDIX_TITLE.search(s["title"]):
            return n
    return len(body)


def title_ok(title: str) -> bool:
    fake = lint.Slide(1, 1, title.strip(), 2, False)
    return not lint.check_title(fake)


def count_ng(texts: list[str], cls: str) -> int:
    n = 0
    for t in texts:
        t = lint.QUOTE_RE.sub("", t)
        n += sum(len(p.findall(t)) for p in NG.get(cls, []))
    return n


NUM_RE = re.compile(r"(\d+(?:\.\d+)?)\s*(枚|件|%|％)")


def truth() -> dict:
    rows = list(csv.DictReader(open(HERE / "task/data/predictions.csv", encoding="utf-8")))
    classes = sorted({r["true_ja"] for r in rows})
    cell = {(t, p): sum(r["true_ja"] == t and r["pred_ja"] == p for r in rows) for t in classes for p in classes}
    wrong = sum(v for (t, p), v in cell.items() if t != p)
    counts = {len(rows), wrong, len(rows) - wrong, 40}
    counts |= set(cell.values())
    counts |= {sum(cell[(t, p)] for p in classes if p != t) for t in classes}          # クラスごとの誤り
    counts |= {sum(cell[(t, p)] for t in classes if t != p) for p in classes}          # クラスごとの誤って入った数
    counts |= {40 - sum(cell[(t, p)] for p in classes if p != t) for t in classes}     # クラスごとの正解
    pct = {round(100 * (len(rows) - wrong) / len(rows), 1), round(100 * wrong / len(rows), 1)}
    for (t, p), v in cell.items():
        pct |= {round(100 * v / 40, 1), round(100 * v / wrong, 1) if t != p else -1}
    for t in classes:
        e = sum(cell[(t, p)] for p in classes if p != t)
        pct |= {round(100 * e / wrong, 1), round(100 * e / 40, 1), round(100 * (40 - e) / 40, 1)}
    return {"counts": counts, "pct": pct, "n": len(rows), "wrong": wrong}


def numeric_claims(slides: list[dict], t: dict) -> list[dict]:
    """スライドの「N枚・N件・N%」を拾い、データから出る値と自動で照合する。合わないものは目で確かめる候補。"""
    out = []
    for n, s in enumerate(slides):
        for text in [s["title"]] + s["text"]:
            for m in NUM_RE.finditer(text):
                v, unit = float(m.group(1)), m.group(2)
                if unit in ("枚", "件"):
                    ok = v == int(v) and int(v) in t["counts"]
                else:
                    ok = any(abs(v - p) <= 0.6 for p in t["pct"])      # 丸めの違いを許す
                out.append({"slide": n + 1, "value": m.group(0), "auto_ok": ok, "context": text[:80]})
    return out


def score(run_dir: Path) -> dict | None:
    summary = json.loads((run_dir / "summary.json").read_text())
    ws = run_dir / "ws"
    if summary["task"] == "gate":          # ゲートの依頼で質問せずにデッキまで作った実行は、under として採点する
        made = [p for p in (ws / "decks").glob("*/index.qmd") if p.parent.name != "_template"]
        if not made or summary["stop_reasons"] != ["success"]:
            return None
        summary = summary | {"task": "under", "deck_path": str(made[0].relative_to(ws))}
    deck = str(Path(summary.get("deck_path") or f"{DECK}/index.qmd").parent)
    qmd = ws / deck / "index.qmd"
    row = {k: summary[k] for k in ("run_id", "task", "model", "skill", "rep", "followups", "num_turns", "wall_s", "cost_usd")}
    row |= {"skill_calls": "|".join(summary["skill_calls"]), "stop_hook_blocks": summary["stop_hook_blocks"],
            "deck_exists": qmd.exists(), "renders": False}
    out = RESULTS / summary["run_id"]
    out.mkdir(parents=True, exist_ok=True)
    (out / "summary.json").write_text(json.dumps(summary, ensure_ascii=False, indent=2) + "\n")
    if not qmd.exists():
        return row
    shutil.copy(qmd, out / "index.qmd")
    ok, log = render(ws, deck)
    row["renders"] = ok
    if not ok:
        (out / "render_error.txt").write_text(log)
        return row
    slides = parse_slides(ws / "_output" / deck / "index.html")
    shots(ws, deck, slides, run_dir / "shots")
    contact_sheet(run_dir / "shots", out / "sheet.jpg", summary["run_id"])
    body = [s for s in slides if not s["is_title_slide"]]
    n_main = n_main_slides(qmd, slides)
    main = body[:n_main]
    chars = [sum(lint.zen_len(t) for t in s["text"]) for s in main]
    nocap = [max(0.0, c - s["caption_chars"]) for c, s in zip(chars, main)]   # 画像ごとの説明文を除いた字数
    row |= {
        "n_main": n_main, "n_appendix": len(body) - n_main, "over_budget": max(0, n_main - BUDGET_10MIN),
        "title_ok_rate": round(sum(title_ok(s["title"]) for s in main) / max(1, n_main), 2),
        "title_len_max": max((lint.zen_len(s["title"]) for s in main), default=0),
        "chars_mean": round(sum(chars) / max(1, n_main)), "chars_max": round(max(chars, default=0)),
        "chars_max_nocap": round(max(nocap, default=0)),
        "bullets_mean": round(sum(s["li"] for s in main) / max(1, n_main), 1),
        "bullets_max": max((s["li"] for s in main), default=0),
        "hedges": count_ng([t for s in main for t in [s["title"]] + s["text"]], "hedge"),
        "buzzwords": count_ng([t for s in main for t in [s["title"]] + s["text"]], "buzzword"),
        "notes_slides": sum(s["notes"] for s in main), "image_slides": sum(s["img"] > 0 for s in main),
    }
    claims = numeric_claims(main, truth())
    row |= {"numbers": len(claims), "numbers_to_check": sum(not c["auto_ok"] for c in claims)}
    with open(out / "numbers.csv", "w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=["slide", "value", "auto_ok", "context"])
        w.writeheader()
        w.writerows(claims)
    (out / "titles.txt").write_text("\n".join(f"{n + 1}. {s['title'].strip()}" + ("" if n < n_main else "  (appendix)")
                                              for n, s in enumerate(body)) + "\n")
    return row


def main() -> None:
    only = set(sys.argv[1:])
    rows = []
    for run_dir in sorted((WORK / "runs").glob("*")):
        if not (run_dir / "summary.json").exists() or (only and run_dir.name not in only):
            continue
        row = score(run_dir)
        if row:
            rows.append(row)
            print({k: row.get(k) for k in ("run_id", "renders", "n_main", "title_ok_rate", "chars_max", "bullets_max",
                                           "numbers_to_check", "image_slides")})
    if not rows or only:
        return
    fields = list(dict.fromkeys(k for r in rows for k in r))
    with open(RESULTS / "metrics.csv", "w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=fields)
        w.writeheader()
        w.writerows(rows)


if __name__ == "__main__":
    main()
