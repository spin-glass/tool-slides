"""brand.py — _brand.yml（Quarto の brand.yml）を Python から読む。色・書体の正本は _brand.yml だけ。

    import brand
    brand.color("blue")          # "#0b5cad"（palette の名前、または foreground/primary などの役割名）
    brand.palette()              # {"blue": "#0b5cad", ...}

探す順: 環境変数 SLIDES_BRAND → カレントから上へ → このスクリプトから上へ（リポジトリ根の _brand.yml）。
見つからないときは下の FALLBACK（_brand.yml と同じ値）を使う。他リポジトリ向けの書き出し:
    python brand.py --css   → :root { --brand-blue: #0b5cad; ... }
    python brand.py --json  → {"blue": "#0b5cad", ...}
"""
from __future__ import annotations

import json
import os
import sys
from functools import lru_cache
from pathlib import Path

FALLBACK = {"blue": "#0b5cad", "orange": "#b35900", "orange-text": "#8a4500", "gray": "#9aa4ae", "red": "#c0392b",
            "teal": "#1f5f5b", "ink": "#1f2328", "heading": "#111418", "muted": "#57606a", "line": "#d0d7de",
            "track": "#e9ecef", "blue-pale": "#eaf1fb", "white": "#ffffff"}


def _find() -> Path | None:
    env = os.environ.get("SLIDES_BRAND")
    if env and Path(env).is_file():
        return Path(env)
    for start in (Path.cwd(), Path(__file__).resolve().parent):
        for d in (start, *start.parents):
            if (d / "_brand.yml").is_file():
                return d / "_brand.yml"
    return None


@lru_cache(maxsize=1)
def _load() -> dict:
    p = _find()
    if p is None:
        return {"color": {"palette": dict(FALLBACK)}}
    import yaml  # matplotlib・jupyter の依存で入っている
    return yaml.safe_load(p.read_text(encoding="utf-8")) or {}


def palette() -> dict[str, str]:
    pal = dict(FALLBACK)
    pal.update((_load().get("color") or {}).get("palette") or {})
    return pal


def color(name: str) -> str:
    """palette の名前か役割名（foreground・background・primary など）を色に。どちらでもなければ name をそのまま返す（#rrggbb を通す）。"""
    pal = palette()
    if name in pal:
        return pal[name]
    role = (_load().get("color") or {}).get(name)
    if isinstance(role, str):
        return pal.get(role, role)
    return name


if __name__ == "__main__":
    pal = palette()
    if "--css" in sys.argv:
        print(":root {\n" + "".join(f"  --brand-{k}: {v};\n" for k, v in pal.items()) + "}")
    else:
        print(json.dumps(pal, ensure_ascii=False, indent=2))
