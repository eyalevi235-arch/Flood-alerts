#!/usr/bin/env python3
"""Copy the private editor into an unlisted static page under site/.

The page fetches GeoJSON that GitHub Pages already publishes in site/data.
It does not register a service worker and it is not added to site/sw.js.
"""
from __future__ import annotations

import filecmp
import shutil
import sys
from pathlib import Path


TOKEN = "e9uh8mcp8g"
FOLDER = "editor-" + TOKEN
EDITOR = Path(__file__).resolve().parent
REPO = EDITOR.parents[1]
SITE = REPO / "site"
PAGE = EDITOR / "page" / "index.html"
CATALOG = EDITOR / "static_catalog.js"
COPIES = ("editor.css", "editor.js", "edit_logic.js")


def target_dir(site: Path | None = None) -> Path:
    return (site or SITE) / FOLDER


def publish(site: Path | None = None) -> Path:
    folder = target_dir(site)
    folder.mkdir(parents=True, exist_ok=True)
    for name in COPIES:
        shutil.copyfile(EDITOR / "static" / name, folder / name)
    shutil.copyfile(CATALOG, folder / "static_catalog.js")
    shutil.copyfile(PAGE, folder / "index.html")
    return folder


def stale(site: Path | None = None) -> list[str]:
    folder = target_dir(site)
    expected = {
        "index.html": PAGE,
        "static_catalog.js": CATALOG,
    }
    for name in COPIES:
        expected[name] = EDITOR / "static" / name
    missing = []
    for name, source in expected.items():
        dest = folder / name
        if not dest.is_file() or not filecmp.cmp(dest, source, shallow=False):
            missing.append(name)
    return missing


def main(argv: list[str]) -> int:
    check = "--check" in argv
    if check:
        drifted = stale()
        if drifted:
            print("static page is stale: " + ", ".join(drifted), file=sys.stderr)
            return 1
        print(FOLDER)
        return 0
    folder = publish()
    print(folder.relative_to(REPO))
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
