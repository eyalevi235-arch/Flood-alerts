#!/usr/bin/env python3
"""The static catalog must answer like server.Catalog, and the hidden page stays unlinked."""
from __future__ import annotations

import json
import subprocess
import tempfile
import unittest
from pathlib import Path

import build_static_page
import server
import test_apply


ROOT = Path(__file__).resolve().parents[2]
NODE = ROOT / "tools" / "stream_editor" / "test_static_catalog.js"
PUBLIC_TEXT = {".html", ".js", ".css", ".json", ".webmanifest"}


def quantize(value: float) -> float:
    return float(f"{float(value):.5f}")


def walk(value):
    if isinstance(value, float):
        return quantize(value)
    if isinstance(value, list):
        return [walk(item) for item in value]
    if isinstance(value, dict):
        return {key: walk(item) for key, item in value.items()}
    return value


def node_catalog(root: Path, queries: dict) -> dict:
    proc = subprocess.run(
        ["node", str(NODE), str(root)],
        input=json.dumps(queries),
        text=True,
        capture_output=True,
        check=False,
    )
    if proc.returncode != 0:
        raise AssertionError(proc.stderr or proc.stdout)
    return json.loads(proc.stdout)


def python_answers(catalog: server.Catalog, queries: dict) -> dict:
    return {
        "health": {
            "ok": True,
            "private": True,
            "writes": False,
            "streams": len(catalog.streams),
            "basins": len(catalog.basins),
        },
        "search": [catalog.search(text) for text in queries.get("search", [])],
        "view": [
            catalog.view(
                item["west"], item["south"], item["east"], item["north"], item["zoom"],
                item["desert"], item["north_on"], item["ext"],
            )
            for item in queries.get("view", [])
        ],
        "feature": [catalog.feature(layer, ident) for layer, ident in queries.get("feature", [])],
        "basins": catalog.basins_payload() if queries.get("basins") else None,
    }


def assert_same(testcase: unittest.TestCase, expect: dict, got: dict) -> None:
    testcase.assertEqual(walk(expect["health"]), walk(got["health"]))
    testcase.assertEqual(walk(expect["search"]), walk(got["search"]))
    testcase.assertEqual(walk(expect["view"]), walk(got["view"]))
    testcase.assertEqual(walk(expect["feature"]), walk(got["feature"]))
    if expect.get("basins") is not None:
        testcase.assertEqual(walk(expect["basins"]), walk(got["basins"]))


class StaticCatalogTests(unittest.TestCase):
    def test_fixture_matches_server_catalog(self) -> None:
        root = Path(tempfile.mkdtemp(prefix="static-catalog-"))
        test_apply.build_repo(root)
        catalog = server.Catalog(root)
        catalog.load()
        queries = {
            "search": ["צין", "נחל־צין", "בשפך", "7", ""],
            "view": [
                {"west": 34.9, "south": 30.3, "east": 35.8, "north": 32.3, "zoom": 8,
                 "desert": True, "north_on": True, "ext": True},
                {"west": 34.9, "south": 30.3, "east": 35.8, "north": 32.3, "zoom": 13,
                 "desert": False, "north_on": True, "ext": False},
            ],
            "feature": [["desert", 1], ["basin", 10], ["desert", 99]],
            "basins": True,
            "http": [
                {"path": "/api/health"},
                {"path": "/api/feature", "query": {"layer": "nope", "id": "1"}},
                {"path": "/api/feature", "query": {"layer": "desert", "id": "99"}},
                {"path": "/api/view", "query": {"west": "2", "south": "1", "east": "0", "north": "3", "zoom": "8"}},
                {"path": "/api/search", "query": {"q": "צין"}},
            ],
        }
        got = node_catalog(root, queries)
        assert_same(self, python_answers(catalog, queries), got)
        self.assertEqual(got["http"][0]["status"], 200)
        self.assertEqual(got["http"][0]["body"]["writes"], False)
        self.assertEqual(got["http"][1]["status"], 400)
        self.assertEqual(got["http"][2]["status"], 404)
        self.assertEqual(got["http"][3]["status"], 400)
        self.assertEqual(got["http"][4]["body"]["results"][0]["id"], 1)

    def test_published_geometry_matches_server_catalog(self) -> None:
        catalog = server.Catalog(ROOT)
        catalog.load()
        self.assertGreater(len(catalog.streams), 1000)
        self.assertGreater(len(catalog.basins), 100)
        sample = catalog.streams[0]
        box = sample["bbox"]
        pad = 0.05
        queries = {
            "search": ["צין", "כישון", str(sample["id"])],
            "view": [{
                "west": box[0] - pad, "south": box[1] - pad, "east": box[2] + pad, "north": box[3] + pad,
                "zoom": 12, "desert": True, "north_on": True, "ext": True,
            }],
            "feature": [[sample["layer"], sample["id"]], ["basin", catalog.basins[0]["id"]]],
            "basins": True,
        }
        got = node_catalog(ROOT, queries)
        assert_same(self, python_answers(catalog, queries), got)
        feature = got["feature"][0]
        self.assertEqual(feature["geometry"]["type"], "LineString")
        self.assertGreaterEqual(len(feature["geometry"]["coordinates"]), 2)


class HiddenPageTests(unittest.TestCase):
    def test_page_matches_sources_and_stays_unlinked(self) -> None:
        self.assertEqual(build_static_page.stale(), [])
        folder = ROOT / "site" / build_static_page.FOLDER
        html = (folder / "index.html").read_text(encoding="utf-8")
        self.assertIn('content="noindex,nofollow"', html)
        self.assertIn("static_catalog.js", html)
        self.assertNotIn("serviceWorker", html)
        self.assertNotIn("/api/", html)
        self.assertIn("../data/", (folder / "static_catalog.js").read_text(encoding="utf-8"))
        sw = (ROOT / "site" / "sw.js").read_text(encoding="utf-8")
        self.assertNotIn(build_static_page.FOLDER, sw)
        self.assertNotIn("editor-", sw)
        self.assertIn("SHELL=", sw)
        for path in (ROOT / "site").rglob("*"):
            if not path.is_file() or path.suffix not in PUBLIC_TEXT:
                continue
            if build_static_page.FOLDER in path.parts:
                continue
            text = path.read_text(encoding="utf-8", errors="replace")
            self.assertNotIn(build_static_page.FOLDER, text, str(path))
            self.assertNotIn("stream_editor", text, str(path))
        server.assert_private(ROOT)


if __name__ == "__main__":
    unittest.main()
