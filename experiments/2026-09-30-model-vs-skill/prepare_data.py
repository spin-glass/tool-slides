#!/usr/bin/env python3
"""検証用の課題データを作る: 牧場の動物6クラスの分類結果（正解・予測・確信度）と表示用サムネイル。

スキルの例（犬の外れ値・閾値）とは別の題材・別の型（正解×予測の混同）にするためのデータ。
写真は Open Images V7（validation / test、各作者 CC BY 2.0）。メタデータは閾値デッキの _cache を再利用する。

    uv run --no-project --python 3.12 --with torch==2.14.0 --with transformers==5.16.1 \\
        --with pillow --with numpy python experiments/2026-09-30-model-vs-skill/prepare_data.py all

段階: select → fetch → embed → classify（分類器を選ぶための件数だけ表示）→ sheets（目視用）→ export
"""
from __future__ import annotations

import csv
import hashlib
import io
import json
import sys
import urllib.request
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parent.parent
META = ROOT / "decks/2026-09-30-outlier-threshold-images/_cache"     # Open Images のメタデータ（prepare.py metadata で取得済み）
CACHE = HERE / "_cache"
IMG = CACHE / "img"
DATA = HERE / "task/data"

SEED = "model-vs-skill-2026-09-30"
CLASSES = [("Sheep", "羊"), ("Goat", "ヤギ"), ("Alpaca", "アルパカ"), ("Deer", "鹿"), ("Cattle", "牛"), ("Horse", "馬")]
N_EVAL, N_SUPPORT, N_CAND = 40, 10, 66      # クラスあたり: 評価用・少数例分類器の見本・候補
PERSON_PROB_MAX = 0.5
LONG_SIDE, THUMB_SIDE = 512, 256
PERSON_LABELS = ["Person", "Human face", "Man", "Woman", "Girl", "Boy", "Human body", "Human head", "Child"]
PERSON_PROMPTS = ["a photo of a person", "a photo of people", "a portrait of a person", "a selfie"]
OTHER_PROMPTS = ["a photo of an animal", "a photo of animals on a farm", "a photo of an object", "a photo of scenery"]
SPLITS = {"val": "validation", "test": "test"}
IMAGE_URL = "https://open-images-dataset.s3.amazonaws.com/{split}/{id}.jpg"


def order_key(image_id: str) -> str:
    return hashlib.sha1(f"{SEED}:{image_id}".encode()).hexdigest()


def select() -> None:
    names = {r["LabelName"]: r["DisplayName"] for r in csv.DictReader(open(META / "classes.csv"))}
    mid_of: dict[str, str] = {}
    for mid, name in names.items():
        mid_of.setdefault(name, mid)
    wanted = {mid_of[en]: en for en, _ in CLASSES}
    person_mids = {mid_of[n] for n in PERSON_LABELS if n in mid_of}
    pos: dict[str, set[str]] = {en: set() for en, _ in CLASSES}
    person: set[str] = set()
    split_of: dict[str, str] = {}
    for sp in SPLITS:
        for r in csv.DictReader(open(META / f"{sp}-labels.csv")):
            if r["Confidence"] != "1":
                continue
            if r["LabelName"] in wanted:
                pos[wanted[r["LabelName"]]].add(r["ImageID"])
                split_of[r["ImageID"]] = sp
            elif r["LabelName"] in person_mids:
                person.add(r["ImageID"])
    rows = []
    for en, ja in CLASSES:
        others = set().union(*(pos[o] for o, _ in CLASSES if o != en))
        clean = sorted(pos[en] - others - person, key=order_key)[:N_CAND]      # 6クラスのうち1つだけが付いた写真
        rows += [{"id": i, "true": en, "true_ja": ja} for i in clean]
    used = {r["id"] for r in rows}
    meta = {}
    for sp in SPLITS:
        for r in csv.DictReader(open(META / f"{sp}-images.csv")):
            if r["ImageID"] in used:
                meta[r["ImageID"]] = r
    for row in rows:
        m = meta[row["id"]]
        row |= {"split": SPLITS[split_of[row["id"]]], "rotation": m["Rotation"], "license": m["License"],
                "author": m["Author"], "title": m["Title"], "landing_url": m["OriginalLandingURL"]}
    CACHE.mkdir(parents=True, exist_ok=True)
    with open(CACHE / "candidates.csv", "w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=list(rows[0]))
        w.writeheader()
        w.writerows(rows)
    print({en: sum(r["true"] == en for r in rows) for en, _ in CLASSES})


def candidates() -> list[dict]:
    return list(csv.DictReader(open(CACHE / "candidates.csv")))


def fetch_one(row: dict) -> str | None:
    from PIL import Image, ImageOps

    out = IMG / f"{row['id']}.jpg"
    if out.exists():
        return None
    try:
        with urllib.request.urlopen(IMAGE_URL.format(split=row["split"], id=row["id"]), timeout=60) as r:
            raw = r.read()
        im = Image.open(io.BytesIO(raw))
        rot = row["rotation"]
        if rot not in ("", "nan") and float(rot) in (90.0, 180.0, 270.0):
            im = im.rotate(float(rot), expand=True)
        else:
            im = ImageOps.exif_transpose(im)
        im = im.convert("RGB")
        im.thumbnail((LONG_SIDE, LONG_SIDE))
        im.save(out, "JPEG", quality=88)
        return None
    except Exception as e:  # noqa: BLE001
        return f"{row['id']}: {e}"


def fetch() -> None:
    IMG.mkdir(parents=True, exist_ok=True)
    rows = candidates()
    with ThreadPoolExecutor(8) as ex:
        errors = [e for e in ex.map(fetch_one, rows) if e]
    print(f"fetched {len(rows) - len(errors)}/{len(rows)}; errors: {errors[:5]}")


def embed() -> None:
    import os

    os.environ.setdefault("HF_HUB_OFFLINE", "1")
    import numpy as np
    import torch
    from PIL import Image
    from transformers import CLIPModel, CLIPProcessor

    name = "openai/clip-vit-base-patch32"
    model = CLIPModel.from_pretrained(name).eval()
    proc = CLIPProcessor.from_pretrained(name)
    dev = "mps" if torch.backends.mps.is_available() else "cpu"
    model.to(dev)

    def feats(out):
        t = out if isinstance(out, torch.Tensor) else out.pooler_output
        return torch.nn.functional.normalize(t.float(), dim=-1).cpu().numpy()

    ids = [r["id"] for r in candidates() if (IMG / f"{r['id']}.jpg").exists()]
    class_prompts = [f"a photo of a {en.lower()}" for en, _ in CLASSES]
    chunks = []
    with torch.no_grad():
        for i in range(0, len(ids), 64):
            ims = [Image.open(IMG / f"{j}.jpg").convert("RGB") for j in ids[i:i + 64]]
            px = proc(images=ims, return_tensors="pt")["pixel_values"].to(dev)
            chunks.append(feats(model.get_image_features(pixel_values=px)))
        tok = proc(text=PERSON_PROMPTS + OTHER_PROMPTS + class_prompts, return_tensors="pt", padding=True).to(dev)
        text = feats(model.get_text_features(**tok))
    emb = np.concatenate(chunks)
    n_p, n_o = len(PERSON_PROMPTS), len(OTHER_PROMPTS)
    logits = 100.0 * emb @ text[: n_p + n_o].T
    p = np.exp(logits - logits.max(1, keepdims=True))
    p /= p.sum(1, keepdims=True)
    np.savez(CACHE / "emb.npz", ids=np.array(ids), emb=emb, person_prob=p[:, :n_p].sum(1), class_text=text[n_p + n_o:])
    print(f"embedded {len(ids)} on {dev}; person_prob > {PERSON_PROB_MAX}: {(p[:, :n_p].sum(1) > PERSON_PROB_MAX).sum()}")


def load_exclude() -> dict[str, str]:
    p = HERE / "exclude.csv"
    return {r["id"]: r["reason"] for r in csv.DictReader(open(p))} if p.exists() else {}


def splits():
    """人物の自動判定と目視除外を通った候補を、クラスごとに 評価用 N_EVAL / 見本 N_SUPPORT に分ける。"""
    import numpy as np

    z = np.load(CACHE / "emb.npz")
    idx = {i: n for n, i in enumerate(z["ids"].tolist())}
    excluded = load_exclude()
    ok = [r for r in candidates() if r["id"] in idx and z["person_prob"][idx[r["id"]]] <= PERSON_PROB_MAX
          and r["id"] not in excluded]
    ev, sup = [], []
    for en, _ in CLASSES:
        rows = [r for r in ok if r["true"] == en]
        assert len(rows) >= N_EVAL + N_SUPPORT, (en, len(rows))
        ev += rows[:N_EVAL]
        sup += rows[N_EVAL:N_EVAL + N_SUPPORT]
    return z, idx, ev, sup


def predict(z, idx, ev, sup, method: str):
    """(予測クラス番号, 確率行列)。zero-shot は文との近さ、few-shot は見本の平均との近さ（どちらも softmax）。"""
    import numpy as np

    e = z["emb"][[idx[r["id"]] for r in ev]]
    if method == "zeroshot":
        ref = z["class_text"]
    else:
        ref = np.stack([z["emb"][[idx[r["id"]] for r in sup if r["true"] == en]].mean(0) for en, _ in CLASSES])
        ref /= np.linalg.norm(ref, axis=1, keepdims=True)
    logits = 100.0 * e @ ref.T
    p = np.exp(logits - logits.max(1, keepdims=True))
    p /= p.sum(1, keepdims=True)
    return p.argmax(1), p


def classify() -> None:
    """分類器を選ぶために、誤りの件数だけを出す（個々の画像は見ない）。"""
    z, idx, ev, sup = splits()
    names = [en for en, _ in CLASSES]
    for method in ("zeroshot", "fewshot"):
        pred, _ = predict(z, idx, ev, sup, method)
        wrong = sum(names[k] != r["true"] for k, r in zip(pred, ev))
        print(f"{method}: {wrong} errors / {len(ev)}")


def sheets() -> None:
    from PIL import Image, ImageDraw

    _, _, ev, _ = splits()
    out = CACHE / "sheets"
    out.mkdir(exist_ok=True)
    for old in out.glob("*.jpg"):
        old.unlink()
    cols, per, cell = 8, 40, 200
    index = []
    for s in range(0, len(ev), per):
        chunk = ev[s:s + per]
        sheet = Image.new("RGB", (cols * cell, ((len(chunk) - 1) // cols + 1) * (cell + 18)), "white")
        d = ImageDraw.Draw(sheet)
        for n, r in enumerate(chunk):
            im = Image.open(IMG / f"{r['id']}.jpg")
            im.thumbnail((cell - 4, cell - 4))
            x, y = (n % cols) * cell, (n // cols) * (cell + 18)
            sheet.paste(im, (x + (cell - im.width) // 2, y + 18 + (cell - im.height) // 2))
            d.text((x + 4, y + 3), f"{s + n:03d} {r['true']}", fill="black")
            index.append(f"{s + n:03d},{r['id']},{r['true']}")
        sheet.save(out / f"sheet-{s // per:02d}.jpg", quality=85)
    (out / "index.csv").write_text("\n".join(index))
    print(f"{len(ev)} images -> {out}")


def export(method: str = "zeroshot") -> None:
    from PIL import Image

    z, idx, ev, sup = splits()
    pred, p = predict(z, idx, ev, sup, method)
    thumbs = DATA / "thumbs"
    thumbs.mkdir(parents=True, exist_ok=True)
    for old in thumbs.glob("*.jpg"):
        old.unlink()
    rows = []
    for r, k, pr in zip(ev, pred, p):
        order = pr.argsort()[::-1]
        rows.append([r["id"], r["true"], r["true_ja"], CLASSES[k][0], CLASSES[k][1], f"{pr[order[0]]:.4f}",
                     CLASSES[order[1]][0], CLASSES[order[1]][1], f"{pr[order[0]] - pr[order[1]]:.4f}"])
        im = Image.open(IMG / f"{r['id']}.jpg")
        im.thumbnail((THUMB_SIDE, THUMB_SIDE))
        im.save(thumbs / f"{r['id']}.jpg", "JPEG", quality=85)
    with open(DATA / "predictions.csv", "w", newline="") as f:
        w = csv.writer(f)
        w.writerow(["id", "true", "true_ja", "pred", "pred_ja", "prob", "second", "second_ja", "margin"])
        w.writerows(rows)
    with open(DATA / "credits.csv", "w", newline="") as f:
        w = csv.writer(f)
        w.writerow(["id", "label", "title", "author", "source", "license"])
        w.writerows([r["id"], r["true"], r["title"], r["author"], r["landing_url"], r["license"]] for r in ev)
    meta = {"dataset": "Open Images V7 (validation / test)", "encoder": "openai/clip-vit-base-patch32", "method": method,
            "classes": dict(CLASSES), "n_eval": len(ev), "n_support_per_class": N_SUPPORT if method == "fewshot" else 0,
            "n_excluded_by_eye": len(load_exclude())}
    (DATA / "meta.json").write_text(json.dumps(meta, ensure_ascii=False, indent=2) + "\n")
    wrong = sum(r[1] != r[3] for r in rows)
    print(f"exported {len(rows)} rows ({method}); errors {wrong}; thumbs {len(list(thumbs.glob('*.jpg')))}")


STAGES = {"select": select, "fetch": fetch, "embed": embed, "classify": classify, "sheets": sheets, "export": export}

if __name__ == "__main__":
    args = sys.argv[1:] or ["all"]
    if args == ["all"]:
        args = list(STAGES)
    for a in args:
        name, _, opt = a.partition("=")
        print(f"== {name}")
        STAGES[name](opt) if opt else STAGES[name]()
