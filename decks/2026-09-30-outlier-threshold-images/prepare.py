#!/usr/bin/env python3
"""外れ値スコアと表示用サムネイルを作る前処理。デッキの描画とは別に1回だけ実行し、結果を data/ にコミットする。

データ: Open Images V7 の validation / test（画像は CC BY 2.0、注釈は CC BY 4.0）。
正常クラス = Dog。外れ値 = 犬に似た動物・ほかの動物・動物以外（下の NON_DOG で構成を固定）。
スコア: CLIP ViT-B/32 の画像埋め込み（L2 正規化）で、参照の犬画像のうち K 番目に近い画像とのコサイン距離。
        大きいほど「犬らしさから遠い」。

実行（重い依存はこの前処理だけ。デッキの描画には matplotlib と pillow があればよい）:
  uv run --no-project --python 3.12 --with torch==2.14.0 --with transformers==5.16.1 \\
      --with pillow --with numpy python decks/2026-09-30-outlier-threshold-images/prepare.py all

段階: metadata → select → fetch → embed → score → sheets（目視用）→ export
目視で外した画像は exclude.csv（id,reason）に書き、score 以降をやり直す。
外す判断は _cache/sheets/ のコンタクトシートだけを見て行い、スコアは見ない（結果に合わせて画像を選ばないため）。
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
CACHE = HERE / "_cache"
IMG = CACHE / "img"
DATA = HERE / "data"

SEED = "tool-slides-2026-09-30"
N_REF, N_CAL, N_EVAL_DOG, DOG_SPARE = 800, 300, 200, 300
K = 10
PERSON_PROB_MAX = 0.5          # CLIP zero-shot で「人物の写真」側の確率がこれを超えたら全役割から除く
LONG_SIDE, THUMB_SIDE = 512, 256

DOG = "Dog"
# 評価用に混ぜる「犬以外」の構成（表示名, 日本語名, 枚数）。合計100枚。
NON_DOG = {
    "near": [("Wolf", "オオカミ", 10), ("Jackal", "ジャッカル", 5), ("Hyena", "ハイエナ", 5), ("Fox", "キツネ", 10)],
    "animal": [("Cat", "猫", 15), ("Bear", "クマ", 5), ("Raccoon", "アライグマ", 5), ("Lion", "ライオン", 5),
               ("Rabbit", "ウサギ", 5), ("Sheep", "羊", 5)],
    # 車と像は、ナンバープレート・人物・宗教的な像が多く公開に向かなかったため、飛行機と建物に替えた（スコアを見る前）
    "object": [("Teddy bear", "ぬいぐるみ", 10), ("Airplane", "飛行機", 5), ("Building", "建物", 5), ("Flower", "花", 5),
               ("Food", "料理", 5)],
}
GROUP_JA = {"dog": "犬", "near": "犬に似た動物", "animal": "ほかの動物", "object": "動物以外"}
SPARE_FACTOR = 3               # 犬以外は枚数の3倍を候補として取得する（人物除外・目視除外の補充用）
PERSON_LABELS = ["Person", "Human face", "Man", "Woman", "Girl", "Boy", "Human body", "Human head", "Child"]
PERSON_PROMPTS = ["a photo of a person", "a photo of people", "a photo of a person with a dog", "a selfie"]
OTHER_PROMPTS = ["a photo of a dog", "a photo of an animal", "a photo of an object", "a photo of scenery"]

SPLITS = {"val": "validation", "test": "test"}
IMAGE_URL = "https://open-images-dataset.s3.amazonaws.com/{split}/{id}.jpg"
GCS = "https://storage.googleapis.com/openimages"
METADATA = {                   # Open Images V7 の公開メタデータ（合計 約180MB）
    "classes.csv": f"{GCS}/v7/oidv7-class-descriptions.csv",
    "val-labels.csv": f"{GCS}/v7/oidv7-val-annotations-human-imagelabels.csv",
    "test-labels.csv": f"{GCS}/v7/oidv7-test-annotations-human-imagelabels.csv",
    "val-images.csv": f"{GCS}/2018_04/validation/validation-images-with-rotation.csv",
    "test-images.csv": f"{GCS}/2018_04/test/test-images-with-rotation.csv",
}


def order_key(image_id: str) -> str:
    return hashlib.sha1(f"{SEED}:{image_id}".encode()).hexdigest()


# ---- metadata -------------------------------------------------------------
def metadata() -> None:
    CACHE.mkdir(parents=True, exist_ok=True)
    for name, url in METADATA.items():
        if not (CACHE / name).exists():
            print("download", name)
            urllib.request.urlretrieve(url, CACHE / name)


# ---- select ---------------------------------------------------------------
def select() -> None:
    names = {r["LabelName"]: r["DisplayName"] for r in csv.DictReader(open(CACHE / "classes.csv"))}
    mid_of = {}
    for mid, name in names.items():
        mid_of.setdefault(name, mid)
    classes = [(g, en, ja, n) for g, items in NON_DOG.items() for en, ja, n in items]
    wanted = {mid_of[DOG]: DOG} | {mid_of[en]: en for _, en, _, _ in classes}
    person_mids = {mid_of[n] for n in PERSON_LABELS if n in mid_of}

    pos: dict[str, set[str]] = {name: set() for name in wanted.values()}
    person: set[str] = set()
    split_of: dict[str, str] = {}
    for sp in SPLITS:
        for r in csv.DictReader(open(CACHE / f"{sp}-labels.csv")):
            if r["Confidence"] != "1":
                continue
            mid = r["LabelName"]
            if mid in wanted:
                pos[wanted[mid]].add(r["ImageID"])
                split_of[r["ImageID"]] = sp
            elif mid in person_mids:
                person.add(r["ImageID"])

    non_dog_all = set().union(*(pos[en] for _, en, _, _ in classes))
    dogs = sorted(pos[DOG] - non_dog_all - person, key=order_key)[: N_REF + N_CAL + N_EVAL_DOG + DOG_SPARE]
    rows = [{"id": i, "group": "dog", "label": DOG, "label_ja": "犬"} for i in dogs]
    used = set(dogs)
    for g, en, ja, n in classes:
        cand = sorted(pos[en] - pos[DOG] - person - used, key=order_key)[: n * SPARE_FACTOR]
        used |= set(cand)
        rows += [{"id": i, "group": g, "label": en, "label_ja": ja} for i in cand]

    meta = {}
    for sp in SPLITS:
        for r in csv.DictReader(open(CACHE / f"{sp}-images.csv")):
            if r["ImageID"] in used:
                meta[r["ImageID"]] = r
    for row in rows:
        m = meta[row["id"]]
        row |= {"split": SPLITS[split_of[row["id"]]], "rotation": m["Rotation"], "license": m["License"],
                "author": m["Author"], "title": m["Title"], "landing_url": m["OriginalLandingURL"]}
    with open(CACHE / "candidates.csv", "w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=list(rows[0]))
        w.writeheader()
        w.writerows(rows)
    counts: dict[str, int] = {}
    for row in rows:
        counts[row["label"]] = counts.get(row["label"], 0) + 1
    print("candidates:", counts)


def candidates() -> list[dict]:
    return list(csv.DictReader(open(CACHE / "candidates.csv")))


# ---- fetch ----------------------------------------------------------------
def fetch_one(row: dict) -> str | None:
    from PIL import Image, ImageOps

    out = IMG / f"{row['id']}.jpg"
    if out.exists():
        return None
    url = IMAGE_URL.format(split=row["split"], id=row["id"])
    try:
        with urllib.request.urlopen(url, timeout=60) as r:
            raw = r.read()
        im = Image.open(io.BytesIO(raw))
        rot = row["rotation"]
        if rot not in ("", "nan") and float(rot) in (90.0, 180.0, 270.0):
            im = im.rotate(float(rot), expand=True)       # メタデータの Rotation は反時計回りの度数
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


# ---- embed ----------------------------------------------------------------
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
    chunks = []
    with torch.no_grad():
        for i in range(0, len(ids), 64):
            ims = [Image.open(IMG / f"{j}.jpg").convert("RGB") for j in ids[i:i + 64]]
            px = proc(images=ims, return_tensors="pt")["pixel_values"].to(dev)
            chunks.append(feats(model.get_image_features(pixel_values=px)))
        tok = proc(text=PERSON_PROMPTS + OTHER_PROMPTS, return_tensors="pt", padding=True).to(dev)
        text = feats(model.get_text_features(**tok))
    emb = np.concatenate(chunks)
    logits = 100.0 * emb @ text.T
    p = np.exp(logits - logits.max(1, keepdims=True))
    p /= p.sum(1, keepdims=True)
    person_prob = p[:, : len(PERSON_PROMPTS)].sum(1)
    np.savez(CACHE / "emb.npz", ids=np.array(ids), emb=emb, person_prob=person_prob)
    print(f"embedded {len(ids)} images on {dev}; person_prob > {PERSON_PROB_MAX}: {(person_prob > PERSON_PROB_MAX).sum()}")


# ---- score ----------------------------------------------------------------
def load_exclude() -> dict[str, str]:
    p = HERE / "exclude.csv"
    if not p.exists():
        return {}
    return {r["id"]: r["reason"] for r in csv.DictReader(open(p))}


def score() -> list[dict]:
    import numpy as np

    z = np.load(CACHE / "emb.npz")
    idx = {i: n for n, i in enumerate(z["ids"].tolist())}
    ok = {i for i in idx if z["person_prob"][idx[i]] <= PERSON_PROB_MAX}
    excluded = load_exclude()
    rows = [r for r in candidates() if r["id"] in ok]

    dogs = [r for r in rows if r["group"] == "dog"]
    ref, cal = dogs[:N_REF], dogs[N_REF:N_REF + N_CAL]
    pool = dogs[N_REF + N_CAL:]                      # 評価用の犬。目視で外した分は後ろから補充する
    eval_rows = [r for r in pool if r["id"] not in excluded][:N_EVAL_DOG]
    assert len(ref) == N_REF and len(cal) == N_CAL and len(eval_rows) == N_EVAL_DOG, (len(ref), len(cal), len(eval_rows))
    short = {}
    for g, items in NON_DOG.items():
        for en, _, n in items:
            got = [r for r in rows if r["label"] == en and r["id"] not in excluded][:n]
            if len(got) < n:
                short[en] = len(got)
            eval_rows += got

    bank = z["emb"][[idx[r["id"]] for r in ref]]

    def knn_dist(rs: list[dict]):
        d = 1.0 - z["emb"][[idx[r["id"]] for r in rs]] @ bank.T
        return np.sort(d, axis=1)[:, K - 1]

    out = []
    for role, rs in (("cal", cal), ("eval", eval_rows)):
        for r, s in zip(rs, knn_dist(rs)):
            out.append(r | {"role": role, "score": f"{s:.5f}"})
    info = {"n_ref": len(ref), "n_cal": len(cal), "n_eval": len(eval_rows), "k": K, "short": short,
            "n_person_filtered": len(idx) - len(ok), "n_excluded_by_eye": len(excluded),
            "pool_order": [r["id"] for r in pool]}
    (CACHE / "score_info.json").write_text(json.dumps(info, ensure_ascii=False))
    with open(CACHE / "scored.csv", "w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=list(out[0]))
        w.writeheader()
        w.writerows(out)
    print({k: v for k, v in info.items() if k != "pool_order"})
    return out


# ---- sheets（目視用のコンタクトシート）-------------------------------------
def sheets() -> None:
    from PIL import Image, ImageDraw

    rows = [r for r in csv.DictReader(open(CACHE / "scored.csv")) if r["role"] == "eval"]
    out = CACHE / "sheets"
    out.mkdir(exist_ok=True)
    for old in out.glob("*.jpg"):
        old.unlink()
    cols, per, cell = 8, 40, 200
    index = []
    for s in range(0, len(rows), per):
        chunk = rows[s:s + per]
        sheet = Image.new("RGB", (cols * cell, ((len(chunk) - 1) // cols + 1) * (cell + 18)), "white")
        d = ImageDraw.Draw(sheet)
        for n, r in enumerate(chunk):
            im = Image.open(IMG / f"{r['id']}.jpg")
            im.thumbnail((cell - 4, cell - 4))
            x, y = (n % cols) * cell, (n // cols) * (cell + 18)
            sheet.paste(im, (x + (cell - im.width) // 2, y + 18 + (cell - im.height) // 2))
            d.text((x + 4, y + 3), f"{s + n:03d} {r['label']}", fill="black")
            index.append(f"{s + n:03d},{r['id']},{r['label']}")
        sheet.save(out / f"sheet-{s // per:02d}.jpg", quality=85)
    (out / "index.csv").write_text("\n".join(index))
    print(f"{len(rows)} images -> {out}")


# ---- export ---------------------------------------------------------------
def export() -> None:
    from PIL import Image

    rows = list(csv.DictReader(open(CACHE / "scored.csv")))
    info = json.loads((CACHE / "score_info.json").read_text())
    thumbs = DATA / "thumbs"
    thumbs.mkdir(parents=True, exist_ok=True)
    for old in thumbs.glob("*.jpg"):
        old.unlink()
    for r in rows:
        if r["role"] == "eval":
            im = Image.open(IMG / f"{r['id']}.jpg")
            im.thumbnail((THUMB_SIDE, THUMB_SIDE))
            im.save(thumbs / f"{r['id']}.jpg", "JPEG", quality=85)
    with open(DATA / "scores.csv", "w", newline="") as f:
        w = csv.writer(f)
        w.writerow(["id", "role", "group", "label", "label_ja", "score"])
        w.writerows([r["id"], r["role"], r["group"], r["label"], r["label_ja"], r["score"]] for r in rows)
    with open(DATA / "credits.csv", "w", newline="") as f:
        w = csv.writer(f)
        w.writerow(["id", "label", "title", "author", "source", "license"])
        w.writerows([r["id"], r["label"], r["title"], r["author"], r["landing_url"], r["license"]]
                    for r in rows if r["role"] == "eval")
    write_credits_html([r for r in rows if r["role"] == "eval"])
    meta = {"dataset": "Open Images V7 (validation / test)", "encoder": "openai/clip-vit-base-patch32",
            "score": f"cosine distance to the {K}-th nearest reference dog image",
            "k": K, "n_ref": info["n_ref"], "n_cal": info["n_cal"], "n_eval": info["n_eval"],
            "n_person_filtered": info["n_person_filtered"], "n_excluded_by_eye": info["n_excluded_by_eye"],
            "person_prob_max": PERSON_PROB_MAX, "groups": GROUP_JA}
    (DATA / "meta.json").write_text(json.dumps(meta, ensure_ascii=False, indent=2) + "\n")
    print(f"exported {len(rows)} rows; thumbs: {len(list(thumbs.glob('*.jpg')))}")


def write_credits_html(rows: list[dict]) -> None:
    """スライドに載せうる画像（評価用300枚）の作者・出典・ライセンスの一覧。デッキと一緒に公開する。"""
    import html

    def lic(url: str) -> str:
        return "CC BY 2.0" if "licenses/by/2.0" in url else url

    body = "\n".join(
        f'<tr><td>{html.escape(r["label_ja"])}</td><td><a href="{html.escape(r["landing_url"])}">'
        f'{html.escape(r["title"] or "(無題)")}</a></td><td>{html.escape(r["author"])}</td>'
        f'<td><a href="{html.escape(r["license"])}">{html.escape(lic(r["license"]))}</a></td></tr>'
        for r in sorted(rows, key=lambda r: (r["group"] != "dog", r["label"], r["author"])))
    page = f"""<!doctype html><html lang="ja"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1"><meta name="robots" content="noindex">
<title>画像の作者と出典</title>
<style>body{{font-family:"Hiragino Sans","Noto Sans JP",sans-serif;max-width:900px;margin:32px auto;padding:0 16px;color:#1f2328}}
table{{border-collapse:collapse;width:100%;font-size:.9em}}td,th{{border-bottom:1px solid #d0d7de;padding:6px 8px;text-align:left}}
th,td:first-child,td:last-child{{white-space:nowrap}}
a{{color:#0b5cad}}</style></head><body>
<h1>画像の作者と出典</h1>
<p>スライド「閾値を動かすと、どの画像が外れ値に移るか」の図は、下の写真 {len(rows)} 枚を縮小して並べたものです。
写真は <a href="https://storage.googleapis.com/openimages/web/index.html">Open Images V7</a> に収録されたもので、
各作者が CC BY 2.0 で公開しています。ラベルは同データセットの人手確認済みラベル（CC BY 4.0）です。</p>
<table><thead><tr><th>ラベル</th><th>題名（出典へのリンク）</th><th>作者</th><th>ライセンス</th></tr></thead>
<tbody>
{body}
</tbody></table></body></html>
"""
    (HERE / "credits.html").write_text(page, encoding="utf-8")


STAGES = {"metadata": metadata, "select": select, "fetch": fetch, "embed": embed, "score": score, "sheets": sheets, "export": export}

if __name__ == "__main__":
    todo = sys.argv[1:] or ["all"]
    if todo == ["all"]:
        todo = list(STAGES)
    for name in todo:
        print(f"== {name}")
        STAGES[name]()
