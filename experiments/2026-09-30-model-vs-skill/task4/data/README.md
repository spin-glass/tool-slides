# データの説明

水辺の6種（カモ・ガン・ハクチョウ・ボート・灯台・アザラシ）を、画像分類モデルで判定した結果。評価用の写真は240枚。

- `predictions.csv` … 1行＝1画像
  - `id`: 画像のID
  - `true` / `true_ja`: 正解クラス（データに付いたラベル。英語名 / 日本語名）
  - `pred` / `pred_ja`: モデルの予測クラス
  - `prob`: 予測クラスの確信度（0〜1）
  - `second` / `second_ja`: 2番目に確信度が高かったクラス
  - `margin`: 1番目と2番目の確信度の差（小さいほど迷っている）
- `images/` … 写真（長辺1024px）。`images/<id>.jpg`
- `thumbs/` … 表示用の縮小画像（長辺256px）。`thumbs/<id>.jpg`
- `credits.csv` … 写真の題名・作者・出典・ライセンス（Open Images V7 に収録された写真で、各作者が CC BY 2.0 で公開。写真を載せるときは出典を示す）
- `meta.json` … 作成条件（CLIP ViT-B/32 の zero-shot 分類。正解は Open Images V7 の人手確認済みラベル）
