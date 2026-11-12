#!/usr/bin/env python3
"""The static catalog must answer like server.Catalog, and the hidden page stays unlinked."""
from __future__ import annotations

import json
import struct
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
        "search": [
            catalog.search(text) if isinstance(text, str) else catalog.search(text["q"], kind=text.get("kind"))
            for text in queries.get("search", [])
        ],
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
            "search": ["צין", "כישון", str(sample["id"]), {"q": "צין", "kind": "basin"}, {"q": "צין", "kind": "stream"}],
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
        basin_hits = got["search"][3]
        stream_hits = got["search"][4]
        self.assertTrue(basin_hits)
        self.assertTrue(all(item["layer"] == "basin" for item in basin_hits))
        self.assertTrue(any("צין" in (item.get("name") or "") for item in basin_hits))
        self.assertTrue(stream_hits)
        self.assertTrue(all(item["layer"] != "basin" for item in stream_hits))


class HiddenPageTests(unittest.TestCase):
    def test_page_matches_sources_and_stays_unlinked(self) -> None:
        self.assertEqual(build_static_page.stale(), [])
        folder = ROOT / "site" / build_static_page.FOLDER
        html = (folder / "index.html").read_text(encoding="utf-8")
        self.assertIn('content="noindex,nofollow"', html)
        self.assertIn('id="tab-streams"', html)
        self.assertIn(">נחלים<", html)
        stream_tools = html.split('id="stream-tools"', 1)[1].split('id="basin-tools"', 1)[0]
        basin_tools = html.split('id="basin-tools"', 1)[1].split('id="note"', 1)[0]
        self.assertIn('id="btn-delete-stream"', stream_tools)
        self.assertIn(">מחק נחל<", stream_tools)
        self.assertNotIn("btn-delete-stream", basin_tools)
        self.assertIn('id="delete-prompt"', html)
        self.assertIn('id="btn-delete-stream-confirm"', html)
        self.assertIn('id="tab-basins"', html)
        self.assertIn(">אגנים<", html)
        self.assertIn('role="tablist"', html)
        editor_js = (folder / "editor.js").read_text(encoding="utf-8")
        self.assertIn("Logic.deleteStreamChange", editor_js)
        self.assertIn("state.mode !== 'streams'", editor_js)
        self.assertIn("Logic.tapSlopPx", editor_js)
        self.assertIn("Logic.acceptTap", editor_js)
        self.assertIn("Logic.searchMatchesMode", editor_js)
        self.assertIn('target="_blank"', editor_js)
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

    def test_editor_manifest_is_scoped_and_distinct(self) -> None:
        folder = ROOT / "site" / build_static_page.FOLDER
        html = (folder / "index.html").read_text(encoding="utf-8")
        self.assertIn('rel="manifest" href="./manifest.webmanifest"', html)
        self.assertIn('rel="apple-touch-icon" href="./apple-touch-icon.png"', html)
        self.assertIn('name="apple-mobile-web-app-title" content="עורך נחלים"', html)
        self.assertIn('name="apple-mobile-web-app-capable" content="yes"', html)
        self.assertIn('name="mobile-web-app-capable" content="yes"', html)
        self.assertIn('name="theme-color" content="#0f4c5c"', html)
        manifest = json.loads((folder / "manifest.webmanifest").read_text(encoding="utf-8"))
        self.assertEqual(manifest["name"], "עורך נחלים")
        self.assertEqual(manifest["short_name"], "עורך נחלים")
        self.assertEqual(manifest["dir"], "rtl")
        self.assertEqual(manifest["lang"], "he")
        self.assertEqual(manifest["start_url"], "./")
        self.assertEqual(manifest["scope"], "./")
        self.assertEqual(manifest["display"], "standalone")
        self.assertEqual(manifest["theme_color"], "#0f4c5c")
        sizes = {icon["sizes"] for icon in manifest["icons"]}
        self.assertIn("192x192", sizes)
        self.assertIn("512x512", sizes)
        site_manifest = json.loads((ROOT / "site" / "manifest.json").read_text(encoding="utf-8"))
        self.assertEqual(site_manifest["name"], "שיטפון בדרך – חיזוי שיטפונות")
        self.assertNotIn("עורך נחלים", site_manifest["name"])
        self.assertEqual(png_size(folder / "icon-192.png"), (192, 192))
        self.assertEqual(png_size(folder / "icon-512.png"), (512, 512))
        self.assertEqual(png_size(folder / "apple-touch-icon.png"), (180, 180))
        self.assertNotEqual((folder / "icon-192.png").read_bytes(), (ROOT / "site" / "icon-192.png").read_bytes())
        self.assertNotEqual((folder / "icon-512.png").read_bytes(), (ROOT / "site" / "icon-512.png").read_bytes())
        self.assertGreater(png_redness(folder / "icon-192.png"), png_redness(ROOT / "site" / "icon-192.png"))


def png_size(path: Path) -> tuple[int, int]:
    data = path.read_bytes()
    if data[1:4] != b"PNG":
        raise AssertionError("not a png: %s" % path)
    return struct.unpack(">II", data[16:24])


def png_redness(path: Path) -> int:
    pixel = png_center(path)
    return pixel[0] - pixel[2]


def _paeth(left: int, up: int, up_left: int) -> int:
    estimate = left + up - up_left
    da = abs(estimate - left)
    db = abs(estimate - up)
    dc = abs(estimate - up_left)
    if da <= db and da <= dc:
        return left
    if db <= dc:
        return up
    return up_left


def png_center(path: Path) -> tuple[int, int, int, int]:
    data = path.read_bytes()
    pos = 8
    compressed = b""
    width = height = 0
    color_type = 0
    while pos + 8 <= len(data):
        length = struct.unpack(">I", data[pos:pos + 4])[0]
        kind = data[pos + 4:pos + 8]
        chunk = data[pos + 8:pos + 8 + length]
        if kind == b"IHDR":
            width, height, _depth, color_type = struct.unpack(">IIBB", chunk[:10])
        elif kind == b"IDAT":
            compressed += chunk
        elif kind == b"IEND":
            break
        pos += 12 + length
    raw = __import__("zlib").decompress(compressed)
    stride = {2: 3, 6: 4}.get(color_type)
    if stride is None:
        raise AssertionError("unsupported png color type %s" % color_type)
    rows: list[bytearray] = []
    cursor = 0
    row_bytes = width * stride
    for _y in range(height):
        filt = raw[cursor]
        cursor += 1
        row = bytearray(raw[cursor:cursor + row_bytes])
        cursor += row_bytes
        prev = rows[-1] if rows else bytearray(row_bytes)
        for i in range(row_bytes):
            left = row[i - stride] if i >= stride else 0
            up = prev[i]
            up_left = prev[i - stride] if i >= stride else 0
            if filt == 0:
                extra = 0
            elif filt == 1:
                extra = left
            elif filt == 2:
                extra = up
            elif filt == 3:
                extra = (left + up) // 2
            elif filt == 4:
                extra = _paeth(left, up, up_left)
            else:
                raise AssertionError("unsupported png filter %s" % filt)
            row[i] = (row[i] + extra) & 255
        rows.append(row)
    x = width // 2
    y = height // 2
    start = x * stride
    px = rows[y][start:start + stride]
    if stride == 3:
        return px[0], px[1], px[2], 255
    return px[0], px[1], px[2], px[3]


if __name__ == "__main__":
    unittest.main()
