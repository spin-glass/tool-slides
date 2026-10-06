# 図の検査の fixtures

`before-*.mmd` は、実際の設計書の図で見つかった読みにくさ（互いにつながらない流れの並び、分岐の無い6個の一本道、「。」で2文を詰めた箱、辺の長い条件、番号の置き方の不ぞろい、図と説明文の食い違い）を、架空の題材（請求書の OCR への切替。`decks/2026-10-01-invoice-ocr-confirm/` と同じ）で同じ形に再現したもの。
`after-*.mmd` は、同じ中身を図の規則（`.claude/skills/design-doc/references/design_doc_guide.md` の「図」）で描き直したもの。周期ごとの確認（cycles）と通知の3段（alert-levels）は表にする見立てなので after が無い。
`tests/test_design_doc.py` の `Figures` が、before は警告に掛かり、after は図の警告が0件になることを確かめる。
