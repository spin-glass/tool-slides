#!/usr/bin/env python3
"""書き直した設計書を正解表と機械的に照らす（補助。最終判断は読んで行う）。
使い方: python3 score.py original.md rewritten.md [claims.csv]"""
import re, sys
from pathlib import Path

KEEP = {  # 残すべき事実: すべての正規表現が本文（または claims.csv）に見つかれば「残っている」
    "K1a 第2工場のプレス機12台": [r"第2工場", r"12\s*台"],
    "K1b 第1工場・搬送機は対象外": [r"搬送機", r"対象外"],
    "K2 週1回の巡回": [r"週1回", r"巡回"],
    "K3 1台約15分（目安）": [r"15\s*分", r"目安"],
    "K4 見逃し月3件（実績）": [r"3\s*件", r"実績"],
    "K5 1分ごとに異常スコア": [r"1\s*分ごと", r"異常スコア"],
    "K6a 0.7以上・注意域3回連続": [r"0\.7(?![0-9])", r"3\s*回連続"],
    "K6b 0.65に限り": [r"0\.65"],
    "K7 必ず30分以内に現地確認": [r"必ず", r"30\s*分以内"],
    "K8 現地確認20分（想定・未実測）": [r"20\s*分", r"(想定|未実測)"],
    "K9 製造課が停止を判断": [r"製造課", r"止め"],
    "K10 再学習・しきい値の調整": [r"再学習", r"(しきい値|閾値)"],
    "K11 誤通知率 月次50%超で報告": [r"50\s*%", r"生産技術課"],
    "K12 合格 見逃し0件・誤通知率30%以下": [r"0\s*件", r"30\s*%"],
    "K13 試行3台・2か月（想定）": [r"3\s*台", r"2\s*か月", r"想定"],
    "K14 第1工場への展開を検討": [r"第1工場", r"検討"],
    "K15 3者の体制": [r"保全課", r"製造課", r"生産技術課"],
    "K16 音声30日で消去・スコア1年": [r"30\s*日", r"1\s*年"],
    "K17 夜間の宛先は未決・保全課長": [r"夜間", r"(未定|未決|要確認)", r"保全課長"],
}
DROP = {  # 削るべき段落の目印（本文に残っていれば「残っている」）
    "F1 本書では…述べる": r"について述べる",
    "F2 製造業を取り巻く環境": r"取り巻く環境",
    "F3 変革する可能性": r"可能性を秘め",
    "F4 万能ではない・肝要": r"(万能|肝要)",
    "F5 緊密に連携": r"緊密に連携",
    "F6 必要に応じて見直す": r"必要に応じて見直",
    "F7 段階的かつ慎重": r"慎重に",
    "F8 関連規程に従い適切に（未決にしてもよい）": r"関連規程に従い",
    "F9 おわりに（突発停止・生産性）": r"(生産性が向上|期待される)",
}
DUP = {"D1 必ず30分以内の文": r"必ず30分以内に現地で音を確かめ", "D2 現地確認20分の文": r"現地確認は1回あたり20分を想定"}

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
print("## 参照の誤り §13")
print("- 本文に §13 が", "ある（中身を作っていないか確認）" if re.search(r"§\s*13|^#+\s*13", new, re.M) else "無い")
extra = sorted(numbers(new) - numbers(orig), key=lambda x: float(x))
print("## 原文に無い数字（作り話の疑い。章番号・ID・日付は除外済み）:", extra or "なし")
o, n = len(re.sub(r"\s", "", orig)), len(re.sub(r"\s", "", new))
print(f"## 文字数（空白除く・表とコードを含む）: 原文 {o} → 書き直し {n}（{n / o:.0%}）")
