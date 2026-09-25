"""WCAG contrast check for the demo's theme tokens.

Parses the dark and light token blocks in docs/product/demo.html (layer 1) and
checks every text token against every surface it sits on (≥ 4.5:1, WCAG AA
small text) and the non-text pairs (≥ 3:1, WCAG 1.4.11). It exits non-zero on
any failure.

    python docs/product/tools/contrast_check.py [path/to/page.html]
"""
from __future__ import annotations

import re
import sys

TEXT = ["text", "text-2", "muted", "faint", "mark-text", "up", "dn", "ok", "warn"]
SURFACES = ["base", "panel", "raised"]
NON_TEXT = [("line", "panel", 1.5), ("panel", "base", 1.15), ("mark", "panel", 3.0)]  # house targets


def lum(hex_: str) -> float:
    h = hex_.lstrip("#")
    r, g, b = (int(h[i:i + 2], 16) / 255 for i in (0, 2, 4))
    f = lambda c: c / 12.92 if c <= 0.03928 else ((c + 0.055) / 1.055) ** 2.4  # noqa: E731
    return 0.2126 * f(r) + 0.7152 * f(g) + 0.0722 * f(b)


def ratio(a: str, b: str) -> float:
    hi, lo = sorted((lum(a), lum(b)), reverse=True)
    return (hi + 0.05) / (lo + 0.05)


def tokens(css: str, selector: str) -> dict[str, str]:
    block = re.search(re.escape(selector) + r"\{(.*?)\}", css, re.S).group(1)
    return dict(re.findall(r"--([\w-]+):(#[0-9A-Fa-f]{6})", block))


def main(path: str) -> int:
    css = open(path, encoding="utf-8").read()
    themes = {"dark": tokens(css, ':root,:root[data-pl-theme="dark"]'),
              "light": tokens(css, ':root[data-pl-theme="light"]')}
    bad = 0
    for name, t in themes.items():
        print(f"\n{name}")
        for fg in TEXT:
            row = []
            for bg in SURFACES:
                r = ratio(t[fg], t[bg]); ok = r >= 4.5; bad += not ok
                row.append(f"{bg} {r:5.2f}{'' if ok else ' ✗'}")
            print(f"  {fg:10} " + " | ".join(row))
        for fg, bg, need in NON_TEXT:
            r = ratio(t[fg], t[bg]); ok = r >= need; bad += not ok
            print(f"  {fg}/{bg:6} {r:5.2f} (≥{need}){'' if ok else ' ✗'}")
    print("\nPASS" if not bad else f"\nFAIL: {bad} pair(s) below target")
    return 1 if bad else 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1] if len(sys.argv) > 1 else "docs/product/demo.html"))
