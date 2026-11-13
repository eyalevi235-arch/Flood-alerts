#!/usr/bin/env python3
"""Apply an approved geometry-review file to repo copies of stream and basin geometry.

Default is a dry run: nothing is written. Writing requires both ``--write`` and
``--yes``. The script never touches model weights, calibration, thresholds,
catchment rasters, rain cells, or travel-time fields.

Segment ids stay as they are. A merge keeps both ids in the model table; the
absorbed id is marked hidden and is removed only from the display GeoJSON.
``delete_stream`` removes that id from the display layers and from the model
table. Other ids are not renumbered. Upstream ``ds`` pointers skip to the
deleted segment's downstream id. Rain cells, travel times, ``lat`` and ``lon``
on the remaining segments are left as they are.
"""
from __future__ import annotations

import argparse
import gzip
import io
import json
import math
import os
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Iterable


FORMAT = "flood-alerts-geometry-patch"
MAX_CHANGES = 200
MAX_VERTICES = 4000
LON_MIN, LON_MAX = 34.0, 37.2
LAT_MIN, LAT_MAX = 29.2, 34.2


class ApplyError(Exception):
    """The review file does not match the current repo, or it is invalid."""


@dataclass(frozen=True)
class Layer:
    site: str
    copies: tuple[str, ...]
    model: str | None
    kind: str
    id_prop: str


LAYERS: dict[str, Layer] = {
    "desert": Layer(
        "site/data/channel_segments.geojson",
        ("data/channel_segments.geojson",),
        "data/channel_segments.json.gz",
        "line",
        "id",
    ),
    "nondesert": Layer(
        "site/data/channel_segments_nondesert.geojson",
        ("data/channel_segments_nondesert.geojson",),
        "data/channel_segments_nondesert.json.gz",
        "line",
        "id",
    ),
    "desert_extension": Layer(
        "site/data/channel_extensions_desert.geojson",
        (),
        None,
        "line",
        "id",
    ),
    "nondesert_extension": Layer(
        "site/data/channel_extensions_nondesert.geojson",
        (),
        None,
        "line",
        "id",
    ),
    "basin": Layer(
        "site/data/basins.geojson",
        ("data/basins_simplified.geojson",),
        None,
        "polygon",
        "sid",
    ),
}


def _bad_constant(value: str) -> None:
    raise ApplyError("JSON contains %s" % value)


def load_json(path: Path) -> Any:
    try:
        if path.suffix == ".gz":
            with gzip.open(path, "rt", encoding="utf-8") as handle:
                return json.load(handle, parse_constant=_bad_constant)
        with path.open(encoding="utf-8") as handle:
            return json.load(handle, parse_constant=_bad_constant)
    except ApplyError:
        raise
    except FileNotFoundError as exc:
        raise ApplyError("missing file %s" % path) from exc
    except (OSError, json.JSONDecodeError, UnicodeError) as exc:
        raise ApplyError("cannot read %s" % path) from exc


def dump_bytes(obj: Any, gz: bool) -> bytes:
    raw = json.dumps(obj, ensure_ascii=False, separators=(",", ":")).encode("utf-8")
    if not gz:
        return raw + b"\n"
    buf = io.BytesIO()
    with gzip.GzipFile(fileobj=buf, mode="wb", mtime=0) as handle:
        handle.write(raw)
    return buf.getvalue()


def atomic_write(path: Path, payload: bytes) -> None:
    tmp = path.with_name(path.name + ".tmp")
    tmp.write_bytes(payload)
    os.replace(tmp, path)


def quantize(value: float) -> float:
    return float(f"{float(value):.5f}")


def as_position(pt: Any) -> list[float]:
    if not isinstance(pt, (list, tuple)) or len(pt) < 2:
        raise ApplyError("coordinate is not a lon/lat pair")
    try:
        lon = float(pt[0])
        lat = float(pt[1])
    except (TypeError, ValueError) as exc:
        raise ApplyError("coordinate is not numeric") from exc
    if not math.isfinite(lon) or not math.isfinite(lat):
        raise ApplyError("coordinate is not finite")
    if not (LON_MIN <= lon <= LON_MAX and LAT_MIN <= lat <= LAT_MAX):
        raise ApplyError("coordinate is outside the map extent")
    return [quantize(lon), quantize(lat)]


def canon_line(coords: Any) -> list[list[float]]:
    if not isinstance(coords, list):
        raise ApplyError("line coordinates are missing")
    out: list[list[float]] = []
    for pt in coords:
        pos = as_position(pt)
        if not out or out[-1] != pos:
            out.append(pos)
    return out


def clean_line(coords: Any) -> list[list[float]]:
    line = canon_line(coords)
    if len(line) < 2:
        raise ApplyError("a line needs at least two vertices")
    if len(line) > MAX_VERTICES:
        raise ApplyError("too many vertices")
    return line


def clean_polygon(coords: Any) -> list[list[list[float]]]:
    if not isinstance(coords, list) or not coords:
        raise ApplyError("polygon coordinates are missing")
    if len(coords) > 80:
        raise ApplyError("too many polygon rings")
    rings: list[list[list[float]]] = []
    for ring in coords:
        if not isinstance(ring, list):
            raise ApplyError("polygon ring is invalid")
        pts = [as_position(pt) for pt in ring]
        if len(pts) > MAX_VERTICES:
            raise ApplyError("too many vertices")
        deduped: list[list[float]] = []
        for pt in pts:
            if not deduped or deduped[-1] != pt:
                deduped.append(pt)
        if deduped and deduped[0] != deduped[-1]:
            deduped.append(deduped[0])
        if len(deduped) < 4:
            raise ApplyError("polygon ring is too short")
        rings.append(deduped)
    return rings


def line_geometry(coords: Any) -> dict[str, Any]:
    if not isinstance(coords, dict) or coords.get("type") != "LineString":
        raise ApplyError("expected a LineString")
    return {"type": "LineString", "coordinates": clean_line(coords.get("coordinates"))}


def stored_line(coords: Any) -> dict[str, Any]:
    """Old geometry as stored, including a degenerate line of two equal points."""
    if not isinstance(coords, dict) or coords.get("type") != "LineString":
        raise ApplyError("expected a LineString")
    raw = coords.get("coordinates")
    if not isinstance(raw, list) or len(raw) < 2:
        raise ApplyError("a line needs at least two vertices")
    if len(raw) > MAX_VERTICES:
        raise ApplyError("too many vertices")
    distinct = canon_line(raw)
    if len(distinct) >= 2:
        return {"type": "LineString", "coordinates": distinct}
    if len(distinct) == 1:
        point = distinct[0]
        return {"type": "LineString", "coordinates": [point, point]}
    raise ApplyError("a line needs at least two vertices")


def polygon_geometry(coords: Any) -> dict[str, Any]:
    if not isinstance(coords, dict) or coords.get("type") != "Polygon":
        raise ApplyError("expected a Polygon")
    return {"type": "Polygon", "coordinates": clean_polygon(coords.get("coordinates"))}


def geometries_equal(kind: str, left: Any, right: Any) -> bool:
    if kind == "line":
        return canon_line(left["coordinates"]) == canon_line(right["coordinates"])
    return clean_polygon(left["coordinates"]) == clean_polygon(right["coordinates"])


def clean_note(value: Any) -> str:
    if not isinstance(value, str):
        raise ApplyError("each change needs a short note")
    text = "".join(ch for ch in value if ch == "\n" or ord(ch) >= 32).strip()
    if not text or len(text) > 500:
        raise ApplyError("each change needs a note of 1 to 500 characters")
    return text


def parse_id(value: Any) -> int:
    if isinstance(value, bool) or not isinstance(value, (int, str)):
        raise ApplyError("id must be an integer")
    raw = str(value)
    if not raw.isdigit():
        raise ApplyError("id must be an integer")
    number = int(raw)
    if number > 10_000_000:
        raise ApplyError("id is out of range")
    return number


def feature_id(feature: dict[str, Any], prop: str) -> str | None:
    props = feature.get("properties") or {}
    value = props.get(prop, feature.get("id"))
    if value is None:
        return None
    return str(value)


def find_feature(collection: dict[str, Any], prop: str, ident: int) -> dict[str, Any] | None:
    want = str(ident)
    for feature in collection.get("features") or []:
        if feature_id(feature, prop) == want:
            return feature
    return None


def find_segment(blob: dict[str, Any], ident: int) -> dict[str, Any] | None:
    for segment in blob.get("segments") or []:
        try:
            if int(segment.get("id")) == ident:
                return segment
        except (TypeError, ValueError):
            continue
    return None


class Workspace:
    def __init__(self, root: Path) -> None:
        self.root = root.resolve()
        self.docs: dict[str, Any] = {}
        self.dirty: set[str] = set()
        self.warnings: list[str] = []
        self.basin_ids: set[str] = set()

    def load(self) -> None:
        paths: set[str] = set()
        for layer in LAYERS.values():
            paths.add(layer.site)
            paths.update(layer.copies)
            if layer.model:
                paths.add(layer.model)
        for rel in sorted(paths):
            self.docs[rel] = load_json(self.root / rel)
        basins = self.docs[LAYERS["basin"].site]
        for feature in basins.get("features") or []:
            sid = feature_id(feature, "sid")
            if sid is not None:
                self.basin_ids.add(sid)

    def require_basin(self, ident: str) -> None:
        if ident not in self.basin_ids:
            raise ApplyError("basin %s is not in the basin file" % ident)

    def site_feature(self, layer: Layer, ident: int) -> dict[str, Any]:
        feature = find_feature(self.docs[layer.site], layer.id_prop, ident)
        if feature is None:
            raise ApplyError("id %s is missing from %s" % (ident, layer.site))
        return feature

    def model_segment(self, layer: Layer, ident: int) -> dict[str, Any] | None:
        if not layer.model:
            return None
        segment = find_segment(self.docs[layer.model], ident)
        if segment is None:
            raise ApplyError("id %s is missing from %s" % (ident, layer.model))
        return segment

    def copies_of(self, layer: Layer, ident: int) -> Iterable[tuple[str, dict[str, Any]]]:
        for rel in layer.copies:
            feature = find_feature(self.docs[rel], layer.id_prop, ident)
            if feature is not None:
                yield rel, feature

    def write(self) -> list[str]:
        written: list[str] = []
        for rel in sorted(self.dirty):
            path = self.root / rel
            atomic_write(path, dump_bytes(self.docs[rel], path.suffix == ".gz"))
            written.append(rel)
        return written


def _note_and_layer(change: dict[str, Any], kind: str) -> tuple[str, Layer]:
    if not isinstance(change, dict):
        raise ApplyError("a change must be an object")
    note = clean_note(change.get("note"))
    name = change.get("layer")
    layer = LAYERS.get(name) if isinstance(name, str) else None
    if layer is None or layer.kind != kind:
        raise ApplyError("unknown layer for this change")
    return note, layer


def _match_old(kind: str, feature: dict[str, Any], old: Any, label: str) -> None:
    geometry = feature.get("geometry")
    if not isinstance(geometry, dict) or not geometries_equal(kind, geometry, old):
        raise ApplyError("old geometry does not match %s" % label)


def _set_line(feature: dict[str, Any], line: list[list[float]]) -> None:
    feature["geometry"] = {"type": "LineString", "coordinates": line}


def _set_polygon(feature: dict[str, Any], rings: list[list[list[float]]]) -> None:
    feature["geometry"] = {"type": "Polygon", "coordinates": rings}


def _set_stream_basin(feature: dict[str, Any], basin: str) -> None:
    props = feature.setdefault("properties", {})
    props["b"] = basin


def _apply_line_to_copies(
    ws: Workspace,
    layer: Layer,
    ident: int,
    old: dict[str, Any],
    new_line: list[list[float]] | None,
    basin: str | None,
) -> None:
    for rel, feature in ws.copies_of(layer, ident):
        current = feature.get("geometry")
        if new_line is not None:
            if not isinstance(current, dict) or not geometries_equal("line", current, old):
                ws.warnings.append(
                    "עותק %s של מזהה %s היה שונה מהאתר. הגאומטריה החדשה הוחלה עליו."
                    % (rel, ident)
                )
            _set_line(feature, new_line)
        if basin is not None:
            _set_stream_basin(feature, basin)
        ws.dirty.add(rel)


def _apply_model_line(
    segment: dict[str, Any],
    new_line: list[list[float]] | None,
    basin: str | None,
) -> None:
    if new_line is not None:
        segment["coords"] = new_line
        segment["coords_display"] = new_line
    if basin is not None:
        segment["basin"] = basin


def _retire_model_segment(segment: dict[str, Any], survivor: int, anchor: list[float]) -> None:
    segment["hidden"] = 1
    segment["merged_into"] = survivor
    segment["coords"] = [anchor, anchor]
    segment["coords_display"] = [anchor, anchor]


def _remove_feature(collection: dict[str, Any], prop: str, ident: int) -> None:
    want = str(ident)
    features = collection.get("features") or []
    collection["features"] = [ft for ft in features if feature_id(ft, prop) != want]


def apply_update_stream(ws: Workspace, change: dict[str, Any]) -> str:
    _note, layer = _note_and_layer(change, "line")
    ident = parse_id(change.get("id"))
    old = stored_line(change.get("old_geometry"))
    new = line_geometry(change.get("new_geometry"))
    feature = ws.site_feature(layer, ident)
    _match_old("line", feature, old, layer.site)
    old_basin = None if change.get("old_basin") is None else str(change.get("old_basin"))
    new_basin = None if change.get("new_basin") is None else str(change.get("new_basin"))
    if new_basin is not None:
        ws.require_basin(new_basin)
    current_b = str((feature.get("properties") or {}).get("b") or "")
    if old_basin is not None and current_b and old_basin != current_b:
        raise ApplyError("old basin does not match id %s" % ident)
    geom_changed = clean_line(new["coordinates"]) != canon_line(old["coordinates"])
    basin_changed = new_basin is not None and new_basin != current_b
    if not geom_changed and not basin_changed:
        raise ApplyError("change for id %s does not modify geometry or basin" % ident)
    new_line = clean_line(new["coordinates"]) if geom_changed else None
    basin_value = new_basin if basin_changed else None
    if new_line is not None:
        _set_line(feature, new_line)
    if basin_value is not None:
        _set_stream_basin(feature, basin_value)
    ws.dirty.add(layer.site)
    _apply_line_to_copies(ws, layer, ident, old, new_line, basin_value)
    segment = ws.model_segment(layer, ident)
    if segment is not None and (new_line is not None or basin_value is not None):
        _apply_model_line(segment, new_line, basin_value)
        if layer.model:
            ws.dirty.add(layer.model)
    kept = "coords ו-coords_display" if new_line is not None else "שיוך אגן בלבד"
    return "עדכון %s מזהה %s (%s). lat, lon, cells וזמני זרימה לא שונו." % (
        change.get("layer"),
        ident,
        kept,
    )


def apply_merge(ws: Workspace, change: dict[str, Any]) -> str:
    _note, layer = _note_and_layer(change, "line")
    survivor_id = parse_id(change.get("survivor_id"))
    absorbed_id = parse_id(change.get("absorbed_id"))
    if survivor_id == absorbed_id:
        raise ApplyError("a stream cannot be merged with itself")
    old_survivor = stored_line(change.get("survivor_old_geometry"))
    old_absorbed = stored_line(change.get("absorbed_old_geometry"))
    new = line_geometry(change.get("new_geometry"))
    new_line = clean_line(new["coordinates"])
    survivor = ws.site_feature(layer, survivor_id)
    absorbed = ws.site_feature(layer, absorbed_id)
    _match_old("line", survivor, old_survivor, layer.site)
    _match_old("line", absorbed, old_absorbed, layer.site)
    new_basin = None if change.get("new_basin") is None else str(change.get("new_basin"))
    if new_basin is not None:
        ws.require_basin(new_basin)
    _set_line(survivor, new_line)
    current_b = str((survivor.get("properties") or {}).get("b") or "")
    if new_basin is not None and new_basin != current_b:
        _set_stream_basin(survivor, new_basin)
    else:
        new_basin = None
    _remove_feature(ws.docs[layer.site], layer.id_prop, absorbed_id)
    ws.dirty.add(layer.site)
    for rel, feature in list(ws.copies_of(layer, survivor_id)):
        current = feature.get("geometry")
        if not isinstance(current, dict) or not geometries_equal("line", current, old_survivor):
            ws.warnings.append(
                "עותק %s של מזהה %s היה שונה מהאתר. הגאומטריה הממוזגת הוחלה עליו."
                % (rel, survivor_id)
            )
        _set_line(feature, new_line)
        if new_basin is not None:
            _set_stream_basin(feature, new_basin)
        _remove_feature(ws.docs[rel], layer.id_prop, absorbed_id)
        ws.dirty.add(rel)
    survivor_seg = ws.model_segment(layer, survivor_id)
    absorbed_seg = ws.model_segment(layer, absorbed_id)
    if survivor_seg is not None:
        _apply_model_line(survivor_seg, new_line, new_basin)
    if absorbed_seg is not None:
        if int(absorbed_seg.get("hidden") or 0) == 1:
            raise ApplyError("absorbed id %s is already hidden" % absorbed_id)
        _retire_model_segment(absorbed_seg, survivor_id, new_line[0])
    if layer.model and (survivor_seg is not None or absorbed_seg is not None):
        ws.dirty.add(layer.model)
    return (
        "מיזוג %s: נשאר מזהה %s, מזהה %s סומן כמוסתר ולא מוצג. שאר המזהים לא מוספרו מחדש."
        % (change.get("layer"), survivor_id, absorbed_id)
    )


def apply_update_basin(ws: Workspace, change: dict[str, Any]) -> str:
    _note, layer = _note_and_layer(change, "polygon")
    ident = parse_id(change.get("id"))
    old = polygon_geometry(change.get("old_geometry"))
    new = polygon_geometry(change.get("new_geometry"))
    if clean_polygon(old["coordinates"]) == clean_polygon(new["coordinates"]):
        raise ApplyError("basin %s geometry is unchanged" % ident)
    feature = ws.site_feature(layer, ident)
    _match_old("polygon", feature, old, layer.site)
    rings = clean_polygon(new["coordinates"])
    _set_polygon(feature, rings)
    ws.dirty.add(layer.site)
    for rel, copy in ws.copies_of(layer, ident):
        current = copy.get("geometry")
        if not isinstance(current, dict) or not geometries_equal("polygon", current, old):
            ws.warnings.append(
                "עותק %s של אגן %s היה שונה מהאתר. הגבול החדש הוחל עליו." % (rel, ident)
            )
        _set_polygon(copy, rings)
        ws.dirty.add(rel)
    return "עדכון גבול אגן %s. תאי הגשם והמודל לא שונו." % ident


SOURCE_EXTENSIONS = {
    "desert": "desert_extension",
    "nondesert": "nondesert_extension",
}


def _src_seg(feature: dict[str, Any]) -> int | None:
    props = feature.get("properties") or {}
    try:
        return int(props.get("src_seg"))
    except (TypeError, ValueError):
        return None


def _remove_line_features(ws: Workspace, layer: Layer, ident: int) -> None:
    _remove_feature(ws.docs[layer.site], layer.id_prop, ident)
    ws.dirty.add(layer.site)
    want = str(ident)
    for rel in layer.copies:
        features = ws.docs[rel].get("features") or []
        if any(feature_id(feature, layer.id_prop) == want for feature in features):
            _remove_feature(ws.docs[rel], layer.id_prop, ident)
            ws.dirty.add(rel)


def _drop_extensions_sourced_from(ws: Workspace, source_layer: str, ident: int) -> int:
    ext_name = SOURCE_EXTENSIONS.get(source_layer)
    if ext_name is None:
        return 0
    layer = LAYERS[ext_name]
    removed = 0
    for rel in (layer.site, *layer.copies):
        collection = ws.docs[rel]
        features = collection.get("features") or []
        kept: list[dict[str, Any]] = []
        changed = False
        for feature in features:
            if _src_seg(feature) == ident:
                changed = True
                removed += 1
            else:
                kept.append(feature)
        if changed:
            collection["features"] = kept
            ws.dirty.add(rel)
    return removed


def _delete_model_segment(ws: Workspace, layer: Layer, ident: int) -> list[int]:
    if not layer.model:
        return []
    blob = ws.docs[layer.model]
    found: dict[str, Any] | None = None
    kept: list[dict[str, Any]] = []
    for segment in blob.get("segments") or []:
        try:
            sid = int(segment.get("id"))
        except (TypeError, ValueError):
            kept.append(segment)
            continue
        if sid == ident:
            found = segment
        else:
            kept.append(segment)
    if found is None:
        raise ApplyError("id %s is missing from %s" % (ident, layer.model))
    if int(found.get("hidden") or 0) == 1:
        raise ApplyError("id %s is already hidden" % ident)
    try:
        nxt = int(found.get("ds"))
    except (TypeError, ValueError):
        nxt = -1
    if nxt == ident:
        nxt = -1
    retargeted: list[int] = []
    for segment in kept:
        try:
            sid = int(segment.get("id"))
            downstream = int(segment.get("ds"))
        except (TypeError, ValueError):
            continue
        if downstream == ident:
            segment["ds"] = nxt
            retargeted.append(sid)
    blob["segments"] = kept
    ws.dirty.add(layer.model)
    return retargeted


def apply_delete_stream(ws: Workspace, change: dict[str, Any]) -> str:
    _note, layer = _note_and_layer(change, "line")
    ident = parse_id(change.get("id"))
    if change.get("name") is not None and not isinstance(change.get("name"), str):
        raise ApplyError("name must be a string")
    old = stored_line(change.get("old_geometry"))
    feature = ws.site_feature(layer, ident)
    _match_old("line", feature, old, layer.site)
    old_basin = None if change.get("old_basin") is None else str(change.get("old_basin"))
    current_b = str((feature.get("properties") or {}).get("b") or "")
    if old_basin is not None and current_b and old_basin != current_b:
        raise ApplyError("old basin does not match id %s" % ident)
    if layer.model:
        segment = ws.model_segment(layer, ident)
        if segment is not None and int(segment.get("hidden") or 0) == 1:
            raise ApplyError("id %s is already hidden" % ident)
    _remove_line_features(ws, layer, ident)
    retargeted = _delete_model_segment(ws, layer, ident)
    dropped = _drop_extensions_sourced_from(ws, str(change.get("layer")), ident)
    where = "מהתצוגה ומהטבלה" if layer.model else "מהתצוגה"
    parts = ["מחיקה %s מזהה %s. הוסר %s." % (change.get("layer"), ident, where)]
    if retargeted:
        parts.append("ds עודכן אצל %s." % ", ".join(str(item) for item in retargeted))
    if dropped:
        parts.append("הוסרו %s הארכות שמקורן במזהה." % dropped)
    parts.append("שאר המזהים לא מוספרו מחדש. lat, lon, cells וזמני זרימה לא שונו.")
    return " ".join(parts)


OPS = {
    "update_stream": apply_update_stream,
    "merge_streams": apply_merge,
    "update_basin": apply_update_basin,
    "delete_stream": apply_delete_stream,
}


def apply_document(root: Path, document: dict[str, Any], write: bool) -> dict[str, Any]:
    if not isinstance(document, dict):
        raise ApplyError("review file must be a JSON object")
    if document.get("format") != FORMAT or document.get("version") != 1:
        raise ApplyError("unsupported review-file format")
    changes = document.get("changes")
    if not isinstance(changes, list) or not changes or len(changes) > MAX_CHANGES:
        raise ApplyError("changes must be a list of 1 to %s items" % MAX_CHANGES)
    ws = Workspace(root)
    ws.load()
    report: list[str] = []
    for index, change in enumerate(changes, start=1):
        if not isinstance(change, dict):
            raise ApplyError("change %s is not an object" % index)
        op = change.get("op")
        handler = OPS.get(op) if isinstance(op, str) else None
        if handler is None:
            raise ApplyError("change %s has an unknown op" % index)
        try:
            report.append(handler(ws, change))
        except ApplyError as exc:
            raise ApplyError("change %s: %s" % (index, exc)) from exc
    written: list[str] = []
    if write:
        written = ws.write()
    return {
        "wrote": write,
        "files": written,
        "report": report,
        "warnings": ws.warnings,
    }


def _print_result(result: dict[str, Any]) -> None:
    if result["wrote"]:
        print("נכתב. הקבצים עודכנו.")
    else:
        print("בדיקה בלבד. לא נכתב שום קובץ.")
    for line in result["report"]:
        print(line)
    for line in result["warnings"]:
        print("אזהרה:", line)
    if result["files"]:
        print("קבצים:")
        for rel in result["files"]:
            print(" ", rel)
    print("לא שונו: model/, calibration, thresholds, cells, lat, lon, זמני זרימה, catchments.")


def main(argv: list[str]) -> int:
    parser = argparse.ArgumentParser(
        description=(
            "Apply an approved flood-alerts geometry review file. "
            "Dry-run unless --write and --yes are both set. "
            "החלה של קובץ גיאומטריה מאושר. בלי --write וגם --yes לא נכתב כלום."
        )
    )
    parser.add_argument("change", help="path to the review JSON")
    parser.add_argument("--repo", default=None, help="repository root (default: this repo)")
    parser.add_argument("--write", action="store_true", help="write the approved geometry")
    parser.add_argument("--yes", action="store_true", help="confirm the write")
    args = parser.parse_args(argv[1:])
    root = Path(args.repo) if args.repo else Path(__file__).resolve().parents[2]
    root = root.resolve()
    if not (root / "site" / "data").is_dir() or not (root / "data").is_dir():
        print("repo root does not look like Flood-alerts", file=sys.stderr)
        return 2
    change_path = Path(args.change)
    if not change_path.is_file():
        print("review file not found", file=sys.stderr)
        return 2
    if args.write and not args.yes:
        print("לא נכתב כלום. להחלה צריך גם --write וגם --yes.", file=sys.stderr)
        return 2
    try:
        document = load_json(change_path)
        result = apply_document(root, document, write=bool(args.write and args.yes))
    except ApplyError as exc:
        print("שגיאה:", exc, file=sys.stderr)
        return 1
    _print_result(result)
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
