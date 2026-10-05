# 検査が通る設計書の例

| 項目 | 内容 |
|---|---|
| この文書で決めること | 例 |

## 1. 要点

| 項目 | 内容 |
|---|---|
| 要点 | §2 の規則と 第3章 の計画 |

### 1.1 目的

基本設計 §9.9 は他の文書への参照なので検査しない。原文 §12・§13 も同じ。[要確認] は未決の印。

## 2. 規則

```mermaid
%%{init: {"theme": "base", "fontFamily": "Hiragino Sans, Noto Sans JP, sans-serif", "themeCSS": ".edgeLabel rect{opacity:1}", "flowchart": {"padding": 24, "htmlLabels": false}, "themeVariables": {"fontSize": "16px", "fontFamily": "Hiragino Sans, Noto Sans JP, sans-serif", "primaryColor": "#eef4fb", "primaryBorderColor": "#0b5cad", "primaryTextColor": "#1f2328", "lineColor": "#57606a", "edgeLabelBackground": "#ffffff", "taskBkgColor": "#eef4fb", "taskBorderColor": "#0b5cad", "taskTextColor": "#1f2328", "critBkgColor": "#b35900", "critBorderColor": "#b35900", "gridColor": "#d0d7de", "sectionBkgColor": "#ffffff"}}}%%
flowchart TB
  A[入力] --> B{閾値以上?}
  B -->|はい| C[採用]
```

図1 採用の規則

本文は 1.1節 を参照する。

## 3. 計画

```mermaid
%%{init: {"theme": "base", "fontFamily": "Hiragino Sans, Noto Sans JP, sans-serif", "themeCSS": ".edgeLabel rect{opacity:1}", "flowchart": {"padding": 24, "htmlLabels": false}, "themeVariables": {"fontSize": "16px", "fontFamily": "Hiragino Sans, Noto Sans JP, sans-serif", "primaryColor": "#eef4fb", "primaryBorderColor": "#0b5cad", "primaryTextColor": "#1f2328", "lineColor": "#57606a", "edgeLabelBackground": "#ffffff", "taskBkgColor": "#eef4fb", "taskBorderColor": "#0b5cad", "taskTextColor": "#1f2328", "critBkgColor": "#b35900", "critBorderColor": "#b35900", "gridColor": "#d0d7de", "sectionBkgColor": "#ffffff"}}}%%
gantt
  dateFormat YYYY-MM-DD
  section 移行
  テスト :a1, 2026-11-01, 30d
```

図2 移行の計画

## 付録A 用語

| 用語 | 意味 |
|---|---|
| 閾値 | 下限 |
