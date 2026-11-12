#!/usr/bin/env python3
"""Apply-script tests use a temporary fixture. They never open the real repo data."""
from __future__ import annotations

import gzip
import hashlib
import json
import threading
import unittest
import urllib.error
import urllib.request
from pathlib import Path

import apply_change
import server


ROOT = Path(__file__).resolve().parents[2]


def line(ident: int, coords: list, name: str, basin: str = "10") -> dict:
    return {
        "type": "Feature",
        "id": ident,
        "geometry": {"type": "LineString", "coordinates": coords},
        "properties": {"id": ident, "name": name, "a": 12.0, "b": basin, "name_he": None},
    }


def basin(ident: int, ring: list, name: str, hole: list | None = None) -> dict:
    rings = [ring]
    if hole:
        rings.append(hole)
    return {
        "type": "Feature",
        "geometry": {"type": "Polygon", "coordinates": rings},
        "properties": {"sid": ident, "name_he": name, "main_nahal": name, "desert": 1},
    }


def segment(ident: int, coords: list, basin_id: str = "10", display: list | None = None, ds: int = -1) -> dict:
    return {
        "id": ident,
        "ds": ds,
        "basin": basin_id,
        "name": "נחל",
        "coords": coords,
        "coords_display": display if display is not None else coords,
        "lat": coords[-1][1],
        "lon": coords[-1][0],
        "area_km2": 4.5,
        "cells": [[3, 4, 1.0]],
        "cn": 82.0,
    }


def dump(path: Path, obj: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    if path.suffix == ".gz":
        payload = json.dumps(obj, ensure_ascii=False, separators=(",", ":")).encode("utf-8")
        with gzip.open(path, "wt", encoding="utf-8") as handle:
            handle.write(payload.decode("utf-8"))
        return
    path.write_text(json.dumps(obj, ensure_ascii=False, separators=(",", ":")) + "\n", encoding="utf-8")


def build_repo(root: Path) -> None:
    ring = [[35.0, 30.4], [35.3, 30.4], [35.3, 30.8], [35.0, 30.8], [35.0, 30.4]]
    hole = [[35.1, 30.5], [35.15, 30.5], [35.15, 30.55], [35.1, 30.55], [35.1, 30.5]]
    other = [[35.4, 30.8], [35.6, 30.8], [35.6, 31.0], [35.4, 31.0], [35.4, 30.8]]
    basins = {"type": "FeatureCollection", "features": [basin(10, ring, "צין - בשפך לים", hole), basin(11, other, "אחר")]}
    desert = {
        "type": "FeatureCollection",
        "features": [
            line(1, [[35.1, 30.5], [35.2, 30.6]], "צין"),
            line(2, [[35.2, 30.6], [35.3, 30.7]], "יובל"),
            line(3, [[35.4, 30.8], [35.5, 30.9]], "אחר", "11"),
        ],
    }
    desert_data = {
        "type": "FeatureCollection",
        "features": [
            line(1, [[35.11, 30.51], [35.21, 30.61]], "צין"),
            line(2, [[35.2, 30.6], [35.3, 30.7]], "יובל"),
            line(3, [[35.4, 30.8], [35.5, 30.9]], "אחר", "11"),
            line(4, [[35.6, 31.0], [35.7, 31.1]], "נוסף"),
        ],
    }
    north = {
        "type": "FeatureCollection",
        "features": [line(7, [[35.0, 32.0], [35.1, 32.1]], "שורק", "11")],
    }
    ext = {
        "type": "FeatureCollection",
        "features": [
            line(10, [[35.2, 30.7], [35.25, 30.75]], "הארכה"),
            line(11, [[35.25, 30.75], [35.28, 30.8]], "הארכה"),
        ],
    }
    dump(root / "site/data/channel_segments.geojson", desert)
    dump(root / "data/channel_segments.geojson", desert_data)
    dump(root / "site/data/channel_segments_nondesert.geojson", north)
    dump(root / "data/channel_segments_nondesert.geojson", north)
    dump(root / "site/data/channel_extensions_desert.geojson", ext)
    dump(root / "site/data/channel_extensions_nondesert.geojson", {"type": "FeatureCollection", "features": []})
    dump(root / "site/data/basins.geojson", basins)
    dump(root / "data/basins_simplified.geojson", basins)
    dump(root / "data/channel_segments.json.gz", {
        "meta": {"version": 1},
        "segments": [
            segment(1, [[35.1, 30.5], [35.2, 30.6]], display=[[35.1, 30.5], [35.15, 30.55], [35.2, 30.6]], ds=2),
            segment(2, [[35.2, 30.6], [35.3, 30.7]], ds=3),
            segment(3, [[35.4, 30.8], [35.5, 30.9]], "11", ds=9),
            segment(9, [[35.8, 31.2], [35.9, 31.3]]),
        ],
    })
    dump(root / "data/channel_segments_nondesert.json.gz", {
        "meta": {"version": 1},
        "segments": [segment(7, [[35.0, 32.0], [35.1, 32.1]], "11")],
    })
    model = root / "model"
    model.mkdir(parents=True, exist_ok=True)
    (model / "calibration.json").write_text('{"alert_thr": 0.3}\n', encoding="utf-8")
    engine = root / "engine"
    engine.mkdir()
    (engine / "flood_engine.py").write_text("# untouched\n", encoding="utf-8")


def load(path: Path):
    if path.suffix == ".gz":
        with gzip.open(path, "rt", encoding="utf-8") as handle:
            return json.load(handle)
    return json.loads(path.read_text(encoding="utf-8"))


def digest(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


class ApplyTests(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = Path(self.id().split(".")[-1])
        import tempfile
        self.dir = Path(tempfile.mkdtemp(prefix="stream-editor-"))
        build_repo(self.dir)
        self.before = {
            "model": digest(self.dir / "model/calibration.json"),
            "engine": digest(self.dir / "engine/flood_engine.py"),
            "north_gz": digest(self.dir / "data/channel_segments_nondesert.json.gz"),
        }

    def assert_untouched_model(self) -> None:
        self.assertEqual(self.before["model"], digest(self.dir / "model/calibration.json"))
        self.assertEqual(self.before["engine"], digest(self.dir / "engine/flood_engine.py"))

    def test_dry_run_writes_nothing(self) -> None:
        before = digest(self.dir / "site/data/channel_segments.geojson")
        doc = {
            "format": apply_change.FORMAT,
            "version": 1,
            "changes": [{
                "op": "update_stream",
                "layer": "desert",
                "id": 1,
                "note": "הזזה לפי התצלום",
                "old_geometry": {"type": "LineString", "coordinates": [[35.1, 30.5], [35.2, 30.6]]},
                "new_geometry": {"type": "LineString", "coordinates": [[35.1, 30.5], [35.12, 30.55], [35.2, 30.6]]},
                "old_basin": "10",
                "new_basin": "10",
            }],
        }
        result = apply_change.apply_document(self.dir, doc, write=False)
        self.assertFalse(result["wrote"])
        self.assertEqual(before, digest(self.dir / "site/data/channel_segments.geojson"))
        self.assertTrue(result["warnings"])

    def test_geometry_update_keeps_model_fields_and_ids(self) -> None:
        doc = {
            "format": apply_change.FORMAT,
            "version": 1,
            "changes": [{
                "op": "update_stream",
                "layer": "desert",
                "id": 1,
                "note": "הזזה לפי התצלום",
                "old_geometry": {"type": "LineString", "coordinates": [[35.1, 30.5], [35.2, 30.6]]},
                "new_geometry": {"type": "LineString", "coordinates": [[35.1, 30.5], [35.12, 30.55], [35.2, 30.6]]},
                "old_basin": "10",
                "new_basin": "10",
            }],
        }
        result = apply_change.apply_document(self.dir, doc, write=True)
        self.assertIn("site/data/channel_segments.geojson", result["files"])
        self.assertNotIn("data/channel_segments_nondesert.json.gz", result["files"])
        site = load(self.dir / "site/data/channel_segments.geojson")
        self.assertEqual([ft["properties"]["id"] for ft in site["features"]], [1, 2, 3])
        self.assertEqual(site["features"][0]["geometry"]["coordinates"][1], [35.12, 30.55])
        data = load(self.dir / "data/channel_segments.geojson")
        self.assertEqual([ft["properties"]["id"] for ft in data["features"]], [1, 2, 3, 4])
        self.assertEqual(data["features"][0]["geometry"]["coordinates"][1], [35.12, 30.55])
        self.assertEqual(data["features"][3]["properties"]["name"], "נוסף")
        blob = load(self.dir / "data/channel_segments.json.gz")
        self.assertEqual([seg["id"] for seg in blob["segments"]], [1, 2, 3, 9])
        seg = blob["segments"][0]
        self.assertEqual(seg["coords"][1], [35.12, 30.55])
        self.assertEqual(seg["coords_display"], seg["coords"])
        self.assertEqual(seg["lat"], 30.6)
        self.assertEqual(seg["lon"], 35.2)
        self.assertEqual(seg["cells"], [[3, 4, 1.0]])
        self.assertEqual(seg["cn"], 82.0)
        self.assertEqual(seg["basin"], "10")
        self.assertEqual(self.before["north_gz"], digest(self.dir / "data/channel_segments_nondesert.json.gz"))
        self.assert_untouched_model()

    def test_reassign_does_not_replace_coords(self) -> None:
        doc = {
            "format": apply_change.FORMAT,
            "version": 1,
            "changes": [{
                "op": "update_stream",
                "layer": "desert",
                "id": 3,
                "note": "שיוך לאגן צין",
                "old_geometry": {"type": "LineString", "coordinates": [[35.4, 30.8], [35.5, 30.9]]},
                "new_geometry": {"type": "LineString", "coordinates": [[35.4, 30.8], [35.5, 30.9]]},
                "old_basin": "11",
                "new_basin": "10",
            }],
        }
        apply_change.apply_document(self.dir, doc, write=True)
        blob = load(self.dir / "data/channel_segments.json.gz")
        seg = next(item for item in blob["segments"] if item["id"] == 3)
        self.assertEqual(seg["basin"], "10")
        self.assertEqual(seg["coords"], [[35.4, 30.8], [35.5, 30.9]])
        self.assertEqual(seg["lat"], 30.9)
        site = load(self.dir / "site/data/channel_segments.geojson")
        self.assertEqual(site["features"][2]["properties"]["b"], "10")
        self.assert_untouched_model()

    def test_merge_keeps_both_ids(self) -> None:
        doc = {
            "format": apply_change.FORMAT,
            "version": 1,
            "changes": [{
                "op": "merge_streams",
                "layer": "desert",
                "survivor_id": 1,
                "absorbed_id": 2,
                "note": "מיזוג יובל אל צין",
                "survivor_old_geometry": {"type": "LineString", "coordinates": [[35.1, 30.5], [35.2, 30.6]]},
                "absorbed_old_geometry": {"type": "LineString", "coordinates": [[35.2, 30.6], [35.3, 30.7]]},
                "new_geometry": {"type": "LineString", "coordinates": [[35.1, 30.5], [35.2, 30.6], [35.3, 30.7]]},
                "old_basin": "10",
                "new_basin": "10",
            }],
        }
        apply_change.apply_document(self.dir, doc, write=True)
        site = load(self.dir / "site/data/channel_segments.geojson")
        self.assertEqual([ft["properties"]["id"] for ft in site["features"]], [1, 3])
        self.assertEqual(len(site["features"][0]["geometry"]["coordinates"]), 3)
        data = load(self.dir / "data/channel_segments.geojson")
        self.assertEqual([ft["properties"]["id"] for ft in data["features"]], [1, 3, 4])
        blob = load(self.dir / "data/channel_segments.json.gz")
        self.assertEqual([seg["id"] for seg in blob["segments"]], [1, 2, 3, 9])
        absorbed = blob["segments"][1]
        self.assertEqual(absorbed["hidden"], 1)
        self.assertEqual(absorbed["merged_into"], 1)
        self.assertEqual(absorbed["coords"], [[35.1, 30.5], [35.1, 30.5]])
        self.assertEqual(blob["segments"][0]["coords"][-1], [35.3, 30.7])
        self.assertEqual(blob["segments"][0]["lat"], 30.6)
        self.assert_untouched_model()

    def test_basin_edit_keeps_hole_and_skips_model_table(self) -> None:
        gz_before = digest(self.dir / "data/channel_segments.json.gz")
        doc = {
            "format": apply_change.FORMAT,
            "version": 1,
            "changes": [{
                "op": "update_basin",
                "layer": "basin",
                "id": 10,
                "note": "הזזת גבול האגן",
                "old_geometry": {"type": "Polygon", "coordinates": [
                    [[35.0, 30.4], [35.3, 30.4], [35.3, 30.8], [35.0, 30.8], [35.0, 30.4]],
                    [[35.1, 30.5], [35.15, 30.5], [35.15, 30.55], [35.1, 30.55], [35.1, 30.5]],
                ]},
                "new_geometry": {"type": "Polygon", "coordinates": [
                    [[35.0, 30.42], [35.3, 30.4], [35.3, 30.8], [35.0, 30.8], [35.0, 30.42]],
                    [[35.1, 30.5], [35.15, 30.5], [35.15, 30.55], [35.1, 30.55], [35.1, 30.5]],
                ]},
            }],
        }
        result = apply_change.apply_document(self.dir, doc, write=True)
        self.assertNotIn("data/channel_segments.json.gz", result["files"])
        self.assertEqual(gz_before, digest(self.dir / "data/channel_segments.json.gz"))
        site = load(self.dir / "site/data/basins.geojson")
        rings = site["features"][0]["geometry"]["coordinates"]
        self.assertEqual(rings[0][0][1], 30.42)
        self.assertEqual(len(rings), 2)
        copy = load(self.dir / "data/basins_simplified.geojson")
        self.assertEqual(copy["features"][0]["geometry"]["coordinates"][1][0], [35.1, 30.5])
        self.assertEqual([ft["properties"]["sid"] for ft in site["features"]], [10, 11])
        self.assert_untouched_model()

    def test_mismatch_writes_nothing(self) -> None:
        before = digest(self.dir / "site/data/channel_segments.geojson")
        doc = {
            "format": apply_change.FORMAT,
            "version": 1,
            "changes": [{
                "op": "update_stream",
                "layer": "desert",
                "id": 1,
                "note": "לא תואם",
                "old_geometry": {"type": "LineString", "coordinates": [[35.0, 30.0], [35.2, 30.6]]},
                "new_geometry": {"type": "LineString", "coordinates": [[35.1, 30.5], [35.2, 30.62]]},
                "old_basin": "10",
                "new_basin": "10",
            }],
        }
        with self.assertRaises(apply_change.ApplyError):
            apply_change.apply_document(self.dir, doc, write=True)
        self.assertEqual(before, digest(self.dir / "site/data/channel_segments.geojson"))

    def test_rejects_coordinate_outside_extent_and_unknown_op(self) -> None:
        doc = {
            "format": apply_change.FORMAT,
            "version": 1,
            "path": "model/calibration.json",
            "changes": [{
                "op": "update_stream",
                "layer": "desert",
                "id": 1,
                "note": "מחוץ למפה",
                "old_geometry": {"type": "LineString", "coordinates": [[35.1, 30.5], [35.2, 30.6]]},
                "new_geometry": {"type": "LineString", "coordinates": [[0, 0], [35.2, 30.6]]},
            }],
        }
        with self.assertRaises(apply_change.ApplyError):
            apply_change.apply_document(self.dir, doc, write=True)
        self.assert_untouched_model()
        doc["changes"][0]["op"] = "delete_everything"
        doc["changes"][0]["new_geometry"]["coordinates"] = [[35.1, 30.5], [35.2, 30.62]]
        with self.assertRaises(apply_change.ApplyError):
            apply_change.apply_document(self.dir, doc, write=True)

    def test_cli_requires_yes(self) -> None:
        change = self.dir / "review.json"
        change.write_text(json.dumps({
            "format": apply_change.FORMAT,
            "version": 1,
            "changes": [{
                "op": "update_stream",
                "layer": "nondesert",
                "id": 7,
                "note": "הזזה",
                "old_geometry": {"type": "LineString", "coordinates": [[35.0, 32.0], [35.1, 32.1]]},
                "new_geometry": {"type": "LineString", "coordinates": [[35.0, 32.0], [35.12, 32.1]]},
                "old_basin": "11",
                "new_basin": "11",
            }],
        }, ensure_ascii=False), encoding="utf-8")
        code = apply_change.main(["apply", str(change), "--repo", str(self.dir), "--write"])
        self.assertEqual(code, 2)
        self.assertEqual(self.before["north_gz"], digest(self.dir / "data/channel_segments_nondesert.json.gz"))
        code = apply_change.main(["apply", str(change), "--repo", str(self.dir)])
        self.assertEqual(code, 0)
        self.assertEqual(self.before["north_gz"], digest(self.dir / "data/channel_segments_nondesert.json.gz"))
        code = apply_change.main(["apply", str(change), "--repo", str(self.dir), "--write", "--yes"])
        self.assertEqual(code, 0)
        blob = load(self.dir / "data/channel_segments_nondesert.json.gz")
        self.assertEqual(blob["segments"][0]["coords"][1][0], 35.12)
        self.assertEqual(blob["segments"][0]["lat"], 32.1)
        self.assert_untouched_model()

    def test_extension_merge_does_not_touch_model_table(self) -> None:
        gz_before = digest(self.dir / "data/channel_segments.json.gz")
        doc = {
            "format": apply_change.FORMAT,
            "version": 1,
            "changes": [{
                "op": "merge_streams",
                "layer": "desert_extension",
                "survivor_id": 10,
                "absorbed_id": 11,
                "note": "מיזוג הארכה",
                "survivor_old_geometry": {"type": "LineString", "coordinates": [[35.2, 30.7], [35.25, 30.75]]},
                "absorbed_old_geometry": {"type": "LineString", "coordinates": [[35.25, 30.75], [35.28, 30.8]]},
                "new_geometry": {"type": "LineString", "coordinates": [[35.2, 30.7], [35.25, 30.75], [35.28, 30.8]]},
            }],
        }
        apply_change.apply_document(self.dir, doc, write=True)
        ext = load(self.dir / "site/data/channel_extensions_desert.geojson")
        self.assertEqual([ft["properties"]["id"] for ft in ext["features"]], [10])
        self.assertEqual(gz_before, digest(self.dir / "data/channel_segments.json.gz"))

    def test_delete_stream_removes_id_and_skips_downstream(self) -> None:
        ext = load(self.dir / "site/data/channel_extensions_desert.geojson")
        ext["features"][0]["properties"]["src_seg"] = 2
        dump(self.dir / "site/data/channel_extensions_desert.geojson", ext)
        doc = {
            "format": apply_change.FORMAT,
            "version": 1,
            "changes": [
                {
                    "op": "delete_stream",
                    "layer": "desert",
                    "id": 3,
                    "name": "אחר",
                    "note": "מחיקה של קטע אמצעי",
                    "old_geometry": {"type": "LineString", "coordinates": [[35.4, 30.8], [35.5, 30.9]]},
                    "old_basin": "11",
                },
                {
                    "op": "delete_stream",
                    "layer": "desert",
                    "id": 2,
                    "name": "יובל",
                    "note": "מחיקה של היובל",
                    "old_geometry": {"type": "LineString", "coordinates": [[35.2, 30.6], [35.3, 30.7]]},
                    "old_basin": "10",
                },
            ],
        }
        result = apply_change.apply_document(self.dir, doc, write=True)
        self.assertTrue(any("ds עודכן אצל 1" in line for line in result["report"]))
        site = load(self.dir / "site/data/channel_segments.geojson")
        self.assertEqual([ft["properties"]["id"] for ft in site["features"]], [1])
        data = load(self.dir / "data/channel_segments.geojson")
        self.assertEqual([ft["properties"]["id"] for ft in data["features"]], [1, 4])
        blob = load(self.dir / "data/channel_segments.json.gz")
        self.assertEqual([seg["id"] for seg in blob["segments"]], [1, 9])
        kept = blob["segments"][0]
        self.assertEqual(kept["ds"], 9)
        self.assertEqual(kept["lat"], 30.6)
        self.assertEqual(kept["lon"], 35.2)
        self.assertEqual(kept["cells"], [[3, 4, 1.0]])
        self.assertEqual(kept["coords"], [[35.1, 30.5], [35.2, 30.6]])
        extensions = load(self.dir / "site/data/channel_extensions_desert.geojson")
        self.assertEqual([ft["properties"]["id"] for ft in extensions["features"]], [11])
        self.assert_untouched_model()

    def test_delete_rejects_mismatch_and_degenerate_update_is_allowed(self) -> None:
        before = digest(self.dir / "site/data/channel_segments.geojson")
        bad = {
            "format": apply_change.FORMAT,
            "version": 1,
            "changes": [{
                "op": "delete_stream",
                "layer": "desert",
                "id": 1,
                "name": "צין",
                "note": "גאומטריה לא תואמת",
                "old_geometry": {"type": "LineString", "coordinates": [[35.0, 30.0], [35.2, 30.6]]},
                "old_basin": "10",
            }],
        }
        with self.assertRaises(apply_change.ApplyError):
            apply_change.apply_document(self.dir, bad, write=True)
        self.assertEqual(before, digest(self.dir / "site/data/channel_segments.geojson"))
        site = load(self.dir / "site/data/channel_segments.geojson")
        site["features"][0]["geometry"]["coordinates"] = [[35.1, 30.5], [35.1, 30.5]]
        dump(self.dir / "site/data/channel_segments.geojson", site)
        doc = {
            "format": apply_change.FORMAT,
            "version": 1,
            "changes": [{
                "op": "update_stream",
                "layer": "desert",
                "id": 1,
                "note": "החלפת קו מנוון",
                "old_geometry": {"type": "LineString", "coordinates": [[35.1, 30.5], [35.1, 30.5]]},
                "new_geometry": {"type": "LineString", "coordinates": [[35.1, 30.5], [35.2, 30.62]]},
                "old_basin": "10",
                "new_basin": "10",
            }],
        }
        apply_change.apply_document(self.dir, doc, write=True)
        updated = load(self.dir / "site/data/channel_segments.geojson")
        self.assertEqual(updated["features"][0]["geometry"]["coordinates"][1], [35.2, 30.62])
        blob = load(self.dir / "data/channel_segments.json.gz")
        self.assertEqual(blob["segments"][0]["lat"], 30.6)
        self.assertEqual(blob["segments"][0]["cells"], [[3, 4, 1.0]])
        self.assertEqual([seg["id"] for seg in blob["segments"]], [1, 2, 3, 9])
        self.assert_untouched_model()


class ServerTests(unittest.TestCase):
    def test_public_site_does_not_reference_editor(self) -> None:
        server.assert_private(ROOT)
        workflow = (ROOT / ".github/workflows/hourly.yml").read_text(encoding="utf-8")
        self.assertIn("path: site", workflow)
        self.assertNotIn("stream_editor", workflow)
        self.assertNotIn("stream_editor", (ROOT / "site/index.html").read_text(encoding="utf-8"))

    def test_http_is_read_only(self) -> None:
        import tempfile
        root = Path(tempfile.mkdtemp(prefix="stream-editor-http-"))
        build_repo(root)
        catalog = server.Catalog(root)
        catalog.load()
        found = {(item["layer"], item["id"]) for item in catalog.search("צין")}
        self.assertIn(("desert", 1), found)
        self.assertIn(("basin", 10), found)
        mouth = catalog.search("בשפך")
        self.assertTrue(mouth)
        self.assertEqual(mouth[0]["layer"], "basin")
        self.assertEqual(mouth[0]["id"], 10)
        feature = catalog.feature("desert", 1)
        self.assertEqual(feature["geometry"]["type"], "LineString")
        self.assertIsNone(catalog.feature("desert", 99))
        httpd = server.serve(catalog, "127.0.0.1", 0)
        thread = threading.Thread(target=httpd.serve_forever, daemon=True)
        thread.start()
        port = httpd.server_address[1]
        try:
            with urllib.request.urlopen("http://127.0.0.1:%s/api/health" % port) as res:
                health = json.load(res)
            self.assertTrue(health["private"])
            self.assertFalse(health["writes"])
            with urllib.request.urlopen("http://127.0.0.1:%s/api/feature?layer=desert&id=1" % port) as res:
                body = json.load(res)
            self.assertEqual(body["id"], 1)
            request = urllib.request.Request("http://127.0.0.1:%s/api/feature" % port, data=b"{}", method="POST")
            with self.assertRaises(urllib.error.HTTPError) as caught:
                urllib.request.urlopen(request)
            self.assertEqual(caught.exception.code, 405)
            with self.assertRaises(urllib.error.HTTPError) as missing:
                urllib.request.urlopen("http://127.0.0.1:%s/vendor/../../model/calibration.json" % port)
            self.assertEqual(missing.exception.code, 404)
        finally:
            httpd.shutdown()
            httpd.server_close()


if __name__ == "__main__":
    unittest.main()
