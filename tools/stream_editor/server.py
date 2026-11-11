#!/usr/bin/env python3
"""Local read-only map for editing stream paths and basin outlines.

Bind is 127.0.0.1 unless --host is set. Nothing is written to the repo.
The process only serves this tool and the GeoJSON already in the checkout.
It is not part of the public site: GitHub Pages publishes site/ only.
"""
from __future__ import annotations

import argparse
import json
import os
import sys
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any
from urllib.parse import parse_qs, unquote, urlparse


EDITOR = Path(__file__).resolve().parent
STATIC = EDITOR / "static"
REPO = EDITOR.parents[1]

STREAM_FILES = (
    ("desert", "site/data/channel_segments.geojson", False),
    ("nondesert", "site/data/channel_segments_nondesert.geojson", False),
    ("desert_extension", "site/data/channel_extensions_desert.geojson", True),
    ("nondesert_extension", "site/data/channel_extensions_nondesert.geojson", True),
)
BASIN_FILE = "site/data/basins.geojson"
VENDOR_TYPES = {".js": "text/javascript; charset=utf-8", ".css": "text/css; charset=utf-8", ".png": "image/png"}
STATIC_TYPES = {
    ".html": "text/html; charset=utf-8",
    ".js": "text/javascript; charset=utf-8",
    ".css": "text/css; charset=utf-8",
}


def assert_private(root: Path) -> None:
    site = (root / "site").resolve()
    editor = EDITOR.resolve()
    if editor == site or site in editor.parents:
        raise SystemExit("the editor must not live inside site/")
    for rel in ("site/index.html", "site/sw.js", "site/manifest.json"):
        path = root / rel
        if path.is_file() and "stream_editor" in path.read_text(encoding="utf-8"):
            raise SystemExit("%s references the private editor" % rel)


def _load(path: Path) -> dict[str, Any]:
    with path.open(encoding="utf-8") as handle:
        data = json.load(handle)
    if not isinstance(data, dict) or not isinstance(data.get("features"), list):
        raise SystemExit("not a FeatureCollection: %s" % path)
    return data


def _bbox(points: list[list[float]]) -> tuple[float, float, float, float]:
    xs = [p[0] for p in points]
    ys = [p[1] for p in points]
    return min(xs), min(ys), max(xs), max(ys)


def _hits(box: tuple[float, float, float, float], west: float, south: float, east: float, north: float) -> bool:
    return not (box[2] < west or box[0] > east or box[3] < south or box[1] > north)


def _simplify(coords: list[list[float]], step: int) -> list[list[float]]:
    if step <= 1 or len(coords) <= 2:
        return coords
    out = coords[::step]
    if out[-1] != coords[-1]:
        out = out + [coords[-1]]
    return out


def _norm(text: str) -> str:
    value = " ".join((text or "").replace("־", " ").replace("-", " ").split())
    for prefix in ("נחל ", "ואדי ", "נהר "):
        if value.startswith(prefix):
            value = value[len(prefix):]
    return value.casefold()


def _title_parts(props: dict[str, Any]) -> str:
    bits = [
        props.get("name_he"),
        props.get("name"),
        props.get("main_nahal"),
        props.get("flows_into"),
        props.get("name_en"),
    ]
    return " ".join(str(bit) for bit in bits if isinstance(bit, str))


class Catalog:
    def __init__(self, root: Path) -> None:
        self.root = root
        self.streams: list[dict[str, Any]] = []
        self.basins: list[dict[str, Any]] = []
        self.by_key: dict[tuple[str, int], dict[str, Any]] = {}

    def load(self) -> None:
        for layer, rel, extension in STREAM_FILES:
            path = self.root / rel
            data = _load(path)
            for feature in data["features"]:
                geom = feature.get("geometry") or {}
                coords = geom.get("coordinates")
                props = feature.get("properties") or {}
                if geom.get("type") != "LineString" or not isinstance(coords, list) or len(coords) < 2:
                    continue
                try:
                    ident = int(props["id"])
                except (KeyError, TypeError, ValueError):
                    continue
                item = {
                    "layer": layer,
                    "id": ident,
                    "name": props.get("name") if isinstance(props.get("name"), str) else "",
                    "name_he": props.get("name_he") if isinstance(props.get("name_he"), str) else "",
                    "main_nahal": props.get("main_nahal") if isinstance(props.get("main_nahal"), str) else "",
                    "flows_into": props.get("flows_into") if isinstance(props.get("flows_into"), str) else "",
                    "basin": None if props.get("b") is None else str(props.get("b")),
                    "area": float(props.get("a") or 0),
                    "perennial": bool(props.get("perennial") or props.get("p")),
                    "extension": extension or int(props.get("ext") or 0) == 1,
                    "bbox": _bbox(coords),
                    "coordinates": coords,
                    "hay": _norm(_title_parts(props)),
                }
                self.streams.append(item)
                self.by_key[(layer, ident)] = item
        basins = _load(self.root / BASIN_FILE)
        for feature in basins["features"]:
            geom = feature.get("geometry") or {}
            rings = geom.get("coordinates")
            props = feature.get("properties") or {}
            if geom.get("type") != "Polygon" or not isinstance(rings, list) or not rings:
                continue
            try:
                ident = int(props["sid"])
            except (KeyError, TypeError, ValueError):
                continue
            outer = rings[0]
            item = {
                "layer": "basin",
                "id": ident,
                "name": props.get("name_he") if isinstance(props.get("name_he"), str) else "",
                "name_en": props.get("name_en") if isinstance(props.get("name_en"), str) else "",
                "main_nahal": props.get("main_nahal") if isinstance(props.get("main_nahal"), str) else "",
                "desert": int(props.get("desert") or 0),
                "perennial": bool(props.get("perennial")),
                "area": float(props.get("area_dem") or props.get("area_rep") or 0),
                "bbox": _bbox(outer),
                "coordinates": rings,
                "hay": _norm(_title_parts(props)),
            }
            self.basins.append(item)
            self.by_key[("basin", ident)] = item
        for stream in self.streams:
            basin = self.by_key.get(("basin", _maybe_int(stream.get("basin"))))
            if basin is not None:
                stream["basin_name"] = basin["name"]
                stream["hay"] = (stream["hay"] + " " + basin["hay"]).strip()

    def search(self, query: str, limit: int = 12) -> list[dict[str, Any]]:
        needle = _norm(query)
        if len(needle) < 1:
            return []
        scored: list[tuple[int, dict[str, Any]]] = []
        for item in self.streams + self.basins:
            hay = item["hay"]
            name = _norm(item.get("name") or "")
            if needle == str(item["id"]):
                score = 0
            elif needle in name:
                score = 1
            elif needle in hay:
                score = 3
            else:
                continue
            scored.append((score, item))
        scored.sort(key=lambda pair: (pair[0], -float(pair[1].get("area") or 0), pair[1]["id"]))
        out = []
        for _score, item in scored[:limit]:
            box = item["bbox"]
            out.append({
                "layer": item["layer"],
                "id": item["id"],
                "name": item.get("name") or "",
                "name_he": item.get("name_he") or item.get("name") or "",
                "main_nahal": item.get("main_nahal") or "",
                "basin": item.get("basin"),
                "basin_name": item.get("basin_name") or "",
                "area": item.get("area") or 0,
                "center": [(box[0] + box[2]) / 2, (box[1] + box[3]) / 2],
            })
        return out

    def view(self, west: float, south: float, east: float, north: float, zoom: float,
             desert: bool, north_on: bool, extensions: bool) -> dict[str, Any]:
        minimum = _min_area(zoom)
        step = 1 if zoom >= 13 else 2 if zoom >= 12 else 3 if zoom >= 11 else 5
        found: list[dict[str, Any]] = []
        for item in self.streams:
            layer = item["layer"]
            if item["extension"] or layer.endswith("_extension"):
                if not extensions:
                    continue
            elif layer == "desert" and not desert:
                continue
            elif layer == "nondesert" and not north_on:
                continue
            if item["area"] < minimum and zoom < 13:
                continue
            if not _hits(item["bbox"], west, south, east, north):
                continue
            found.append(item)
        truncated = False
        if len(found) > 900:
            found.sort(key=lambda item: -item["area"])
            found = found[:900]
            truncated = True
        streams = []
        for item in found:
            streams.append({
                "layer": item["layer"],
                "id": item["id"],
                "name": item["name"],
                "basin": item["basin"],
                "area": item["area"],
                "perennial": item["perennial"],
                "extension": item["extension"],
                "coordinates": _simplify(item["coordinates"], step),
            })
        return {"streams": streams, "truncated": truncated, "min_area": minimum}

    def feature(self, layer: str, ident: int) -> dict[str, Any] | None:
        item = self.by_key.get((layer, ident))
        if item is None:
            return None
        if layer == "basin":
            return {
                "layer": "basin",
                "id": item["id"],
                "name": item["name"],
                "name_en": item["name_en"],
                "main_nahal": item["main_nahal"],
                "desert": item["desert"],
                "perennial": item["perennial"],
                "area": item["area"],
                "geometry": {"type": "Polygon", "coordinates": item["coordinates"]},
            }
        return {
            "layer": item["layer"],
            "id": item["id"],
            "name": item["name"],
            "name_he": item["name_he"],
            "main_nahal": item["main_nahal"],
            "flows_into": item["flows_into"],
            "basin": item["basin"],
            "basin_name": item.get("basin_name") or "",
            "area": item["area"],
            "perennial": item["perennial"],
            "extension": item["extension"],
            "geometry": {"type": "LineString", "coordinates": item["coordinates"]},
        }

    def basins_payload(self) -> dict[str, Any]:
        features = []
        for item in self.basins:
            outer = item["coordinates"][0]
            step = 3 if len(outer) > 180 else 1
            rings = [_simplify(outer, step)] + [ring for ring in item["coordinates"][1:]]
            features.append({
                "id": item["id"],
                "name": item["name"],
                "main_nahal": item["main_nahal"],
                "desert": item["desert"],
                "perennial": item["perennial"],
                "coordinates": rings,
            })
        return {"basins": features}


def _maybe_int(value: Any) -> int:
    try:
        return int(value)
    except (TypeError, ValueError):
        return -1


def _min_area(zoom: float) -> float:
    if zoom <= 8:
        return 200
    if zoom <= 9:
        return 80
    if zoom <= 10:
        return 30
    if zoom <= 11:
        return 8
    if zoom <= 12:
        return 2
    return 0.0


def _safe_child(root: Path, relative: str, suffixes: set[str]) -> Path | None:
    if not relative or relative.startswith("/") or "\\" in relative or "\x00" in relative:
        return None
    parts = Path(relative).parts
    if ".." in parts:
        return None
    path = (root / relative).resolve()
    try:
        path.relative_to(root.resolve())
    except ValueError:
        return None
    if path.suffix.lower() not in suffixes or not path.is_file():
        return None
    return path


def make_handler(catalog: Catalog) -> type[BaseHTTPRequestHandler]:
    vendor_root = catalog.root / "site" / "vendor"

    class Handler(BaseHTTPRequestHandler):
        protocol_version = "HTTP/1.1"

        def log_message(self, fmt: str, *args: Any) -> None:
            sys.stderr.write("stream-editor %s\n" % (fmt % args))

        def do_POST(self) -> None:  # noqa: N802
            self._send_json(405, {"error": "read-only"})

        def do_PUT(self) -> None:  # noqa: N802
            self._send_json(405, {"error": "read-only"})

        def do_DELETE(self) -> None:  # noqa: N802
            self._send_json(405, {"error": "read-only"})

        def do_GET(self) -> None:  # noqa: N802
            parsed = urlparse(self.path)
            path = unquote(parsed.path)
            query = parse_qs(parsed.query)
            if path in ("/", "/index.html"):
                self._send_file(STATIC / "index.html", "text/html; charset=utf-8", cache=False)
                return
            if path.startswith("/vendor/"):
                target = _safe_child(vendor_root, path[len("/vendor/"):], set(VENDOR_TYPES))
                if target is None:
                    self._send_json(404, {"error": "not found"})
                    return
                self._send_file(target, VENDOR_TYPES[target.suffix.lower()], cache=True)
                return
            if path.startswith("/") and path.count("/") == 1:
                target = _safe_child(STATIC, path[1:], set(STATIC_TYPES))
                if target is not None:
                    self._send_file(target, STATIC_TYPES[target.suffix.lower()], cache=False)
                    return
            if path == "/api/health":
                self._send_json(200, {
                    "ok": True,
                    "private": True,
                    "writes": False,
                    "streams": len(catalog.streams),
                    "basins": len(catalog.basins),
                })
                return
            if path == "/api/search":
                text = (query.get("q") or [""])[0][:80]
                self._send_json(200, {"results": catalog.search(text)})
                return
            if path == "/api/basins":
                self._send_json(200, catalog.basins_payload())
                return
            if path == "/api/view":
                try:
                    west, south, east, north, zoom = (
                        float((query.get(key) or ["nan"])[0])
                        for key in ("west", "south", "east", "north", "zoom")
                    )
                except ValueError:
                    self._send_json(400, {"error": "bad bounds"})
                    return
                if not all(map(_finite, (west, south, east, north, zoom))):
                    self._send_json(400, {"error": "bad bounds"})
                    return
                if east <= west or north <= south or zoom < 0 or zoom > 22:
                    self._send_json(400, {"error": "bad bounds"})
                    return
                payload = catalog.view(
                    west, south, east, north, zoom,
                    _flag(query, "desert"),
                    _flag(query, "north_on"),
                    _flag(query, "ext"),
                )
                self._send_json(200, payload)
                return
            if path == "/api/feature":
                layer = (query.get("layer") or [""])[0]
                raw = (query.get("id") or [""])[0]
                if layer not in {name for name, _rel, _ext in STREAM_FILES} | {"basin"} or not raw.isdigit():
                    self._send_json(400, {"error": "bad feature"})
                    return
                feature = catalog.feature(layer, int(raw))
                if feature is None:
                    self._send_json(404, {"error": "not found"})
                    return
                self._send_json(200, feature)
                return
            self._send_json(404, {"error": "not found"})

        def _send_json(self, status: int, payload: dict[str, Any]) -> None:
            body = json.dumps(payload, ensure_ascii=False, separators=(",", ":")).encode("utf-8")
            self._send(status, "application/json; charset=utf-8", body, cache=False)

        def _send_file(self, path: Path, content_type: str, cache: bool) -> None:
            try:
                body = path.read_bytes()
            except OSError:
                self._send_json(404, {"error": "not found"})
                return
            extra = {}
            if path.suffix == ".html":
                extra["Content-Security-Policy"] = (
                    "default-src 'self'; script-src 'self'; style-src 'self' 'unsafe-inline'; "
                    "img-src 'self' data: https://server.arcgisonline.com https://services.arcgisonline.com "
                    "https://tiles.maps.eox.at; connect-src 'self'; font-src 'self'; "
                    "worker-src 'none'; object-src 'none'; base-uri 'self'; form-action 'none'; frame-ancestors 'none'"
                )
                extra["X-Robots-Tag"] = "noindex, nofollow"
            self._send(200, content_type, body, cache=cache, extra=extra)

        def _send(self, status: int, content_type: str, body: bytes, cache: bool,
                  extra: dict[str, str] | None = None) -> None:
            self.send_response(status)
            self.send_header("Content-Type", content_type)
            self.send_header("Content-Length", str(len(body)))
            self.send_header("X-Content-Type-Options", "nosniff")
            self.send_header("Referrer-Policy", "no-referrer")
            self.send_header("Cache-Control", "public, max-age=86400" if cache else "no-store")
            for key, value in (extra or {}).items():
                self.send_header(key, value)
            self.end_headers()
            self.wfile.write(body)

    return Handler


def _finite(value: float) -> bool:
    return value == value and value not in (float("inf"), float("-inf"))


def _flag(query: dict[str, list[str]], key: str) -> bool:
    return (query.get(key) or ["1"])[0] != "0"


def serve(catalog: Catalog, host: str, port: int) -> ThreadingHTTPServer:
    httpd = ThreadingHTTPServer((host, port), make_handler(catalog))
    httpd.daemon_threads = True
    return httpd


def main(argv: list[str]) -> int:
    parser = argparse.ArgumentParser(
        description="Private local stream-path editor. Read-only. Not the public site. "
                    "עורך נתיבים פרטי ומקומי. לא כותב למאגר ולא עולה לאתר."
    )
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=8765)
    parser.add_argument("--root", default=str(REPO))
    args = parser.parse_args(argv[1:])
    root = Path(args.root).resolve()
    assert_private(root)
    if args.host not in ("127.0.0.1", "localhost", "::1", "0.0.0.0"):
        print("host must be localhost or 0.0.0.0", file=sys.stderr)
        return 2
    catalog = Catalog(root)
    catalog.load()
    try:
        httpd = serve(catalog, args.host, args.port)
    except OSError as exc:
        print("cannot listen: %s" % exc, file=sys.stderr)
        return 1
    host, port = httpd.server_address[:2]
    print("עורך נתיבים פרטי. לא חלק מהאתר. לא נכתב כלום למאגר.")
    print("private stream editor. read-only. not deployed with the site.")
    print("streams %s, basins %s" % (len(catalog.streams), len(catalog.basins)))
    print("open http://%s:%s/" % ("127.0.0.1" if host in ("0.0.0.0", "") else host, port))
    if args.host == "0.0.0.0":
        print("השרת מאזין ברשת המקומית בלבד לצורך הטלפון. אל תפתחו את הפורט לאינטרנט.")
    try:
        httpd.serve_forever()
    except KeyboardInterrupt:
        print("stop")
    finally:
        httpd.server_close()
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
