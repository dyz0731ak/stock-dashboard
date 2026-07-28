#!/usr/bin/env python3
"""Inject GA4 tag into generated static HTML files when GA4_ID is provided."""

from __future__ import annotations

import os
import sys
from pathlib import Path


def ga_tag(ga_id: str) -> str:
    return f"""<!-- Google Analytics -->
<script async src="https://www.googletagmanager.com/gtag/js?id={ga_id}"></script>
<script>window.dataLayer=window.dataLayer||[];function gtag(){{dataLayer.push(arguments);}}gtag('js',new Date());gtag('config','{ga_id}');</script>"""


def main() -> int:
    ga_id = (sys.argv[1] if len(sys.argv) > 1 else os.environ.get("GA4_ID", "")).strip()
    if not ga_id:
        print("[inject-ga] GA4_ID is empty; skipped")
        return 0

    root = Path(__file__).resolve().parents[1]
    tag = ga_tag(ga_id)
    changed = 0
    for path in root.rglob("*.html"):
        if any(part in {".git", ".github", "node_modules"} for part in path.parts):
            continue
        text = path.read_text(encoding="utf-8")
        if "googletagmanager.com/gtag/js?id=" in text:
            continue
        if "</head>" not in text:
            continue
        path.write_text(text.replace("</head>", f"{tag}\n</head>", 1), encoding="utf-8")
        changed += 1
    print(f"[inject-ga] injected GA4 tag into {changed} files")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
