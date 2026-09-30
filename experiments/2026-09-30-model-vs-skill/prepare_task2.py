#!/usr/bin/env python3
"""追試用の課題データを作る: 同じ評価用240枚を、旧版と新版の分類器で判定した結果（切り口は「変更の前後」）。

旧版は主課題と同じ zero-shot 分類。新版は、同じ画像特徴で各クラス10枚の見本の平均に近いクラスを選ぶ few-shot 分類。
画像特徴は prepare_data.py の _cache を使うので、モデルは動かさない（numpy だけで足りる）。

    .venv/bin/python experiments/2026-09-30-model-vs-skill/prepare_task2.py
"""
from __future__ import annotations

import csv
import json
from pathlib import Path

import prepare_data as pd

HERE = Path(__file__).resolve().parent
OUT = HERE / "task2"

README = """# データの説明

牧場の動物6クラス（羊・ヤギ・アルパカ・鹿・牛・馬）の画像分類で、モデルを旧版から新版に替えたときの判定結果。
評価用の写真は各クラス40枚、計240枚で、新旧とも同じ写真を判定した。

- `changes.csv` … 1行＝1画像
  - `id`: 画像のID（画像は `thumbs/<id>.jpg`）
  - `true` / `true_ja`: 正解クラス（英語名 / 日本語名）
  - `old` / `old_ja`: 旧版の予測クラス、`old_prob`: その確信度（0〜1）
  - `new` / `new_ja`: 新版の予測クラス、`new_prob`: その確信度（0〜1）
- `thumbs/` … 表示用の画像（長辺256px）
- `credits.csv` … 写真の作者・出典・ライセンス（Open Images V7 に収録された写真で、各作者が CC BY 2.0 で公開。写真を載せるときは出典を示す）
- `meta.json` … 作成条件（旧版は CLIP ViT-B/32 の zero-shot 分類。新版は同じ画像特徴で、各クラス10枚の見本の平均に近いクラスを選ぶ分類。
  見本60枚は評価用240枚に含まれない。正解は Open Images V7 の人手確認済みラベル）
"""


def main() -> None:
    z, idx, ev, sup = pd.splits()
    names = [en for en, _ in pd.CLASSES]
    ja = dict(pd.CLASSES)
    old, p_old = pd.predict(z, idx, ev, sup, "zeroshot")
    new, p_new = pd.predict(z, idx, ev, sup, "fewshot")
    OUT.mkdir(exist_ok=True)
    rows = []
    for r, a, b, pa, pb in zip(ev, old, new, p_old, p_new):
        rows.append([r["id"], r["true"], r["true_ja"], names[a], ja[names[a]], f"{pa[a]:.4f}",
                     names[b], ja[names[b]], f"{pb[b]:.4f}"])
    with open(OUT / "changes.csv", "w", newline="", encoding="utf-8") as f:
        w = csv.writer(f)
        w.writerow(["id", "true", "true_ja", "old", "old_ja", "old_prob", "new", "new_ja", "new_prob"])
        w.writerows(rows)
    meta = {"dataset": "Open Images V7 (validation / test)", "encoder": "openai/clip-vit-base-patch32",
            "old": "zeroshot", "new": "fewshot (mean of 10 support images per class)", "classes": ja,
            "n_eval": len(ev), "n_support_per_class": pd.N_SUPPORT, "n_excluded_by_eye": len(pd.load_exclude())}
    (OUT / "meta.json").write_text(json.dumps(meta, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    (OUT / "README.md").write_text(README, encoding="utf-8")
    ok_old = sum(r[1] == r[3] for r in rows)
    ok_new = sum(r[1] == r[6] for r in rows)
    fixed = sum(r[1] != r[3] and r[1] == r[6] for r in rows)
    broken = sum(r[1] == r[3] and r[1] != r[6] for r in rows)
    print(f"{len(rows)} rows; correct old {ok_old}, new {ok_new}; fixed {fixed}, broken {broken}, "
          f"wrong in both {sum(r[1] != r[3] and r[1] != r[6] for r in rows)}")


if __name__ == "__main__":
    main()
