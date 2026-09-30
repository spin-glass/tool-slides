# slides

Quarto（revealjs）でスライドを作るリポジトリ。

- 1発表＝1フォルダ: `decks/<name>/index.qmd`
- 出力: `quarto render decks/<name>/index.qmd` → `_output/decks/<name>/index.html`
- テーマ: `theme/custom.scss`（日本語フォント設定済み、1280×720）
- Python のコードセルが使える（環境変数 `QUARTO_PYTHON` に `.venv` を設定済み。matplotlib・pillow・numpy が入っている）
