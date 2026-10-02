#!/usr/bin/env python3
"""書き直した設計書を正解表と機械的に照らす（補助。最終判断は読んで行う）。
使い方: python3 score.py original.md rewritten.md [claims.csv]"""
import re, sys
from pathlib import Path

KEEP = {  # 残すべき事実: すべての正規表現が本文（または claims.csv）に見つかれば「残っている」
    "K1a 対象の規程3つ": [r"就業規則", r"経費規程", r"旅費規程"],
    "K1b 精算処理は対象外": [r"精算", r"対象外"],
    "K2 現行 2名・月約600件": [r"2\s*名", r"600"],
    "K3a 根拠の条文を必ず表示": [r"条文", r"表示"],
    "K3b 示せない質問は担当者へ": [r"担当者へ"],
    "K4a 類似度0.75": [r"0\.75"],
    "K4b 類似度0.8（矛盾）": [r"0\.8(?![0-9])"],
    "K5 合格 300件・2%・30%": [r"300", r"2\s*%", r"30\s*%"],
    "K6 週次40%で通知": [r"40\s*%"],
    "K7 試行1か月（想定）": [r"1\s*か月", r"想定"],
    "K8 3者の体制": [r"総務課", r"情報システム課", r"(外部)?ベンダー"],
    "K9 確認1日30分（想定・未実測）": [r"30\s*分", r"(想定|未実測)"],
    "K10 改定から3営業日": [r"3\s*営業日"],
    "K11 社員番号を伏せる": [r"社員番号"],
    "K12 ログ1年": [r"1\s*年"],
    "K13 回答期限は未決・総務課長": [r"回答期限", r"(未定|未決|要確認)", r"総務課長"],
    "K14 現行の誤回答率 約3%（参考値）": [r"3\s*%", r"(参考値|目安|再集計)"],
    "K15 毎日20件を抜き取り": [r"20\s*件"],
}
DROP = {  # 削るべき段落の目印（本文に残っていれば「残っている」）
    "F1 本書では…説明する": r"について説明する",
    "F2 近年、生成AIの活用は": r"近年",
    "F3 導入して終わりではなく": r"導入して終わり",
    "F4 共通の理解・指針": r"共通の理解",
    "F5 様々な観点から": r"様々な観点",
    "F6 信頼を得るうえで重要": r"信頼を得る",
    "F7 ユーザー体験を常に意識": r"ユーザー体験",
    "F8 極力人手を介さず": r"極力",
    "F9 迅速かつ適切に対応（未決にしてもよい）": r"迅速かつ適切",
    "F10 常に最新の状態": r"常に最新",
    "F11 柔軟に見直す": r"柔軟に見直",
    "F12 密に連携・円滑な": r"密に連携",
    "F13 セキュリティに万全（未決にしてもよい）": r"万全",
    "F14 おわりに（利便性・耳を傾け）": r"(利便性が大きく|耳を傾け)",
}
DUP = {"D1 根拠の条文の文": r"回答の根拠となる条文を必ず表示する", "D2 確認作業30分の文": r"確認作業は1日30分を想定している"}

def body(p):  # 表・コード以外も含めた本文（HTML コメントは除く）
    t = Path(p).read_text(encoding="utf-8")
    return re.sub(r"<!--.*?-->", "", t, flags=re.S)

def numbers(t):
    t = re.sub(r"(?<![A-Za-z])C\d+", "", t)                 # 主張ID
    t = re.sub(r"§\s*\d+(\.\d+)*|^#+\s*\d+(\.\d+)*", "", t, flags=re.M)   # 章番号
    t = re.sub(r"\d{4}-\d{2}-\d{2}", "", t)                  # 日付
    return set(re.findall(r"\d+(?:\.\d+)?", t))

orig, new = body(sys.argv[1]), body(sys.argv[2])
claims = Path(sys.argv[3]).read_text(encoding="utf-8") if len(sys.argv) > 3 else ""
print("## 残すべき事実（設計書の本文 / 主張の表）")
for k, pats in KEEP.items():
    in_doc = all(re.search(p, new) for p in pats)
    in_claims = all(re.search(p, claims) for p in pats) if claims else False
    print(f"- {k}: 本文 {'○' if in_doc else '×'} / 主張の表 {'○' if in_claims else '×'}")
print("## 削るべき段落（本文に残っていれば ×）")
for k, p in DROP.items():
    print(f"- {k}: {'× 残っている' if re.search(p, new) else '○ 消えた'}")
print("## 繰り返し（本文に2回以上あれば ×）")
for k, p in DUP.items():
    n = len(re.findall(p, new)); print(f"- {k}: {n}回 {'×' if n > 1 else '○'}")
print("## 参照の誤り §12")
print("- 本文に §12 が", "ある（中身を作っていないか確認）" if re.search(r"§\s*12|^#+\s*12", new, re.M) else "無い")
extra = sorted(numbers(new) - numbers(orig), key=lambda x: float(x))
print("## 原文に無い数字（作り話の疑い。章番号・ID・日付は除外済み）:", extra or "なし")
o, n = len(re.sub(r"\s", "", orig)), len(re.sub(r"\s", "", new))
print(f"## 文字数（空白除く・表とコードを含む）: 原文 {o} → 書き直し {n}（{n / o:.0%}）")
