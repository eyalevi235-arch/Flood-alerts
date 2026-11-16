#!/usr/bin/env python3
"""Detect near-parallel stream duplicates on the public map and, with --write, draw each once.

The public map styles north/center perennial segments as a solid line and ephemeral
segments as a dashed line (site/app.js northStyle). Desert segments are a separate
solid blue line (channel_segments.geojson). Where the two extractions trace the same
reach, or where two segments of one named stream run side by side, the map shows
both.

--check (default) exits 1 when an auto-fixable duplicate remains.
--write updates display GeoJSON and sets hidden=1 on a fully retired model segment.
Model coords, area, CN, lat/lon, basins, calibration and thresholds are left as they are.
coords_display follows the line the map draws. Shared vertices follow the editor
rule from PR #56 (1e-5 degree snap, or 1e-7 degree raw match).
"""
from __future__ import annotations

import argparse
import gzip
import json
import math
import sys
import unicodedata
from collections import defaultdict
from dataclasses import dataclass, field
from typing import Any

ROOT_DEFAULT = "."
MAX_DIST_M = 400.0
MIN_COVER_FRAC = 0.82
MIN_OVERLAP_M = 450.0
MIN_FEATURE_M = 220.0
PARALLEL_DEG = 40.0
PARALLEL_FRAC = 0.68
SAMPLE_M = 50.0
UNIQUE_KEEP_M = 280.0
SECOND_TAIL_REVIEW_M = 400.0
SNAP_DEG = 1e-5
JUNCTION_TOL_DEG = 1e-7
WELD_MAX_M = 400.0

LAYER_RANK = {
    "nondesert": 500,
    "nondesert_ext": 420,
    "desert": 300,
    "desert_ext": 220,
    "small_nd": 80,
    "small_de": 80,
    "jordan": 40,
}

LAYER_FILES = {
    "desert": [
        "site/data/channel_segments.geojson",
        "data/channel_segments.geojson",
    ],
    "nondesert": [
        "site/data/channel_segments_nondesert.geojson",
        "data/channel_segments_nondesert.geojson",
    ],
    "desert_ext": ["site/data/channel_extensions_desert.geojson"],
    "nondesert_ext": ["site/data/channel_extensions_nondesert.geojson"],
    "small_nd": ["site/data/small_streams_nd.geojson"],
    "small_de": ["site/data/small_streams_de.geojson"],
    "jordan": ["site/data/rivers_context_upper_jordan.geojson"],
}

MODEL_GZ = {
    "desert": "data/channel_segments.json.gz",
    "nondesert": "data/channel_segments_nondesert.json.gz",
}


def log(msg: str) -> None:
    print(msg, flush=True)


def norm_name(value: Any) -> str:
    if not isinstance(value, str):
        return ""
    text = "".join(ch for ch in unicodedata.normalize("NFKD", value) if not unicodedata.combining(ch))
    text = text.replace("־", " ").replace("-", " ").replace("ـ", " ")
    text = " ".join(text.split())
    for prefix in ("נחל ", "ואדי ", "وادي ", "נהר ", "نهر "):
        if text.startswith(prefix):
            text = text[len(prefix):]
    return text.strip().lower()


def meters(a: list[float], b: list[float]) -> float:
    radius = 6371000.0
    dlat = math.radians(b[1] - a[1])
    dlon = math.radians(b[0] - a[0])
    lat1 = math.radians(a[1])
    lat2 = math.radians(b[1])
    h = math.sin(dlat / 2) ** 2 + math.cos(lat1) * math.cos(lat2) * math.sin(dlon / 2) ** 2
    return 2 * radius * math.asin(min(1.0, math.sqrt(h)))


def length_m(coords: list[list[float]]) -> float:
    return sum(meters(a, b) for a, b in zip(coords, coords[1:]))


def coincides(a: list[float], b: list[float]) -> bool:
    if abs(a[0] - b[0]) <= JUNCTION_TOL_DEG and abs(a[1] - b[1]) <= JUNCTION_TOL_DEG:
        return True
    return round(a[0], 5) == round(b[0], 5) and round(a[1], 5) == round(b[1], 5)


def vertex_key(coord: list[float]) -> tuple[float, float]:
    return (round(coord[0], 5), round(coord[1], 5))


def round_pt(coord: list[float]) -> list[float]:
    return [round(float(coord[0]), 5), round(float(coord[1]), 5)]


def xy_of(coords: list[list[float]], lat0: float) -> list[tuple[float, float]]:
    scale = 111320.0 * math.cos(math.radians(lat0))
    return [(c[0] * scale, c[1] * 110540.0) for c in coords]


def to_lonlat(x: float, y: float, lat0: float) -> list[float]:
    scale = 111320.0 * math.cos(math.radians(lat0))
    return [x / scale, y / 110540.0]


@dataclass
class Feat:
    layer: str
    index: int
    ident: Any
    name: str
    raw_name: str
    perennial: bool
    area: float
    coords: list[list[float]]
    length: float
    lat0: float
    bbox: tuple[float, float, float, float]
    key: tuple[str, int]
    rank: tuple[Any, ...] = field(default_factory=tuple)

    @property
    def model_layer(self) -> str | None:
        if self.layer in ("desert", "nondesert"):
            return self.layer
        return None


def load_features(root: str) -> list[Feat]:
    features: list[Feat] = []
    for layer, rels in LAYER_FILES.items():
        path = f"{root}/{rels[0]}"
        with open(path, encoding="utf-8") as handle:
            collection = json.load(handle)
        for index, feature in enumerate(collection.get("features") or []):
            geom = feature.get("geometry") or {}
            coords = geom.get("coordinates")
            if geom.get("type") != "LineString" or not isinstance(coords, list) or len(coords) < 2:
                continue
            clean = [[float(c[0]), float(c[1])] for c in coords if isinstance(c, (list, tuple)) and len(c) >= 2]
            if len(clean) < 2:
                continue
            props = feature.get("properties") or {}
            raw = props.get("name_he") or props.get("name") or ""
            name = norm_name(raw)
            perennial = bool(props.get("perennial") in (1, True) or props.get("p") in (1, True))
            try:
                area = float(props.get("a") or 0)
            except (TypeError, ValueError):
                area = 0.0
            ident = props.get("id", props.get("d", props.get("ctx_id", index)))
            lat0 = sum(c[1] for c in clean) / len(clean)
            xs = [c[0] for c in clean]
            ys = [c[1] for c in clean]
            item = Feat(
                layer=layer,
                index=index,
                ident=ident,
                name=name,
                raw_name=raw if isinstance(raw, str) else "",
                perennial=perennial,
                area=area,
                coords=clean,
                length=length_m(clean),
                lat0=lat0,
                bbox=(min(xs), min(ys), max(xs), max(ys)),
                key=(layer, index),
            )
            detail = min(len(clean), 80)
            ident_sort = -int(ident) if isinstance(ident, int) or (isinstance(ident, str) and ident.lstrip("-").isdigit()) else 0
            item.rank = (
                LAYER_RANK[layer] + (40 if perennial else 0) + (20 if name else 0),
                round(item.length, 1),
                detail,
                ident_sort,
            )
            features.append(item)
    return features


def bbox_gap_m(a: Feat, b: Feat) -> float:
    ax0, ay0, ax1, ay1 = a.bbox
    bx0, by0, bx1, by1 = b.bbox
    lat = (a.lat0 + b.lat0) / 2
    dx = 0.0
    if ax1 < bx0:
        dx = bx0 - ax1
    elif bx1 < ax0:
        dx = ax0 - bx1
    dy = 0.0
    if ay1 < by0:
        dy = by0 - ay1
    elif by1 < ay0:
        dy = ay0 - by1
    return math.hypot(dx * 111320.0 * math.cos(math.radians(lat)), dy * 110540.0)


def cumul(coords: list[list[float]]) -> list[float]:
    acc = [0.0]
    for left, right in zip(coords, coords[1:]):
        acc.append(acc[-1] + meters(left, right))
    return acc


def sample_line(coords: list[list[float]], step: float = SAMPLE_M) -> list[tuple[float, list[float], float]]:
    """Return (distance_along, lonlat, bearing_deg) samples."""
    if len(coords) < 2:
        return []
    acc = cumul(coords)
    total = acc[-1]
    if total < 1:
        return [(0.0, coords[0], 0.0)]
    count = max(2, int(total / step) + 1)
    targets = [total * i / (count - 1) for i in range(count)]
    out = []
    seg = 0
    for target in targets:
        while seg < len(acc) - 2 and acc[seg + 1] < target:
            seg += 1
        span = acc[seg + 1] - acc[seg]
        frac = 0.0 if span <= 0 else min(1.0, max(0.0, (target - acc[seg]) / span))
        lon = coords[seg][0] + frac * (coords[seg + 1][0] - coords[seg][0])
        lat = coords[seg][1] + frac * (coords[seg + 1][1] - coords[seg][1])
        bearing = math.degrees(math.atan2(coords[seg + 1][0] - coords[seg][0], coords[seg + 1][1] - coords[seg][1]))
        out.append((target, [lon, lat], bearing))
    return out


def project_point(origin: list[float], dest: list[float], point: list[float], lat0: float) -> tuple[float, float, list[float]]:
    scale = 111320.0 * math.cos(math.radians(lat0))
    ax, ay = origin[0] * scale, origin[1] * 110540.0
    bx, by = dest[0] * scale, dest[1] * 110540.0
    px, py = point[0] * scale, point[1] * 110540.0
    dx, dy = bx - ax, by - ay
    length2 = dx * dx + dy * dy
    if length2 <= 1e-9:
        return 0.0, math.hypot(px - ax, py - ay), [origin[0], origin[1]]
    tee = max(0.0, min(1.0, ((px - ax) * dx + (py - ay) * dy) / length2))
    qx, qy = ax + tee * dx, ay + tee * dy
    return tee, math.hypot(px - qx, py - qy), [qx / scale, qy / 110540.0]


def nearest_on(coords: list[list[float]], point: list[float], lat0: float) -> tuple[int, float, float, list[float], float]:
    best = None
    for index in range(len(coords) - 1):
        tee, dist, proj = project_point(coords[index], coords[index + 1], point, lat0)
        bearing = math.degrees(math.atan2(coords[index + 1][0] - coords[index][0], coords[index + 1][1] - coords[index][1]))
        if best is None or dist < best[2]:
            best = (index, tee, dist, proj, bearing)
    if best is None:
        return 0, 0.0, 1e9, point, 0.0
    return best


def angle_diff(a: float, b: float) -> float:
    diff = abs(a - b) % 180.0
    return min(diff, 180.0 - diff)


def shared_vertex_keys(src: Feat, dst: Feat) -> set[tuple[float, float]]:
    dst_keys = {vertex_key(coord) for coord in dst.coords}
    return {vertex_key(coord) for coord in src.coords if vertex_key(coord) in dst_keys}


def shares_endpoint(src: Feat, dst: Feat) -> bool:
    for left in (src.coords[0], src.coords[-1]):
        for right in (dst.coords[0], dst.coords[-1]):
            if coincides(left, right):
                return True
    return False


def relation_ok(src: Feat, dst: Feat, stats: dict[str, float]) -> bool:
    """True when the close run is a second trace of src, not a bend or a joining tributary."""
    same = bool(src.name and src.name == dst.name)
    mean_close = stats["mean_close"]
    parallel = stats["parallel_frac"] >= PARALLEL_FRAC or mean_close <= 30.0
    # A whole feature lying on the other line is a second drawing, even when they share an endpoint.
    coincident = stats["frac"] >= 0.9 and stats["mean_all"] <= 35.0 and stats["length"] >= 60.0
    min_overlap = 60.0 if coincident else MIN_OVERLAP_M
    if not coincident and (stats["overlap_m"] < min_overlap or not parallel or mean_close > MAX_DIST_M):
        return False
    if coincident and stats["mean_all"] <= 35.0:
        return True
    # A shared endpoint plus a line that drifts away is the next reach of the same stream.
    if stats["shares_end"] and mean_close > 100.0:
        return False
    cross = src.layer.split("_")[0] != dst.layer.split("_")[0]
    small = src.layer.startswith("small") or dst.layer.startswith("small")
    if small:
        # A long run of a hint line sitting on a model segment is the same reach drawn again.
        if mean_close <= 80.0 and stats["overlap_m"] >= 400.0 and parallel:
            return True
        return mean_close <= 45.0 and stats["frac_close_run"] >= 0.85
    # Same normalized name: one stream drawn twice. A connected next-reach was already rejected.
    if same and mean_close <= MAX_DIST_M:
        return True
    # No shared name: only a near-coincident trace (missing name or conflicting name on the same line).
    if mean_close <= 55.0 and stats["frac_close_run"] >= 0.9:
        return True
    return False


def measure(src: Feat, dst: Feat) -> dict[str, float] | None:
    if src.length < 60.0:
        return None
    step = SAMPLE_M if src.length >= SAMPLE_M * 4 else max(12.0, src.length / 6)
    samples = sample_line(src.coords, step)
    if len(samples) < 2:
        return None
    acc = cumul(src.coords)
    shared = shared_vertex_keys(src, dst)
    shared_along = [acc[index] for index, coord in enumerate(src.coords) if vertex_key(coord) in shared]
    dists = []
    flags = []
    geom_flags = []
    parallel_hits = 0
    close = 0
    for dist_along, point, bearing in samples:
        _idx, _tee, dist, _proj, other_bearing = nearest_on(dst.coords, point, src.lat0)
        dists.append(dist)
        near_join = any(abs(dist_along - marker) <= 200.0 for marker in shared_along)
        aligned = angle_diff(bearing, other_bearing) <= PARALLEL_DEG or dist <= 30.0
        on_line = dist <= MAX_DIST_M and aligned
        geom_flags.append(on_line)
        is_close = on_line and not near_join
        flags.append(is_close)
        if is_close:
            close += 1
            if aligned:
                parallel_hits += 1
    geom_close = [dist for dist, flag in zip(dists, geom_flags) if flag]
    if not geom_close:
        return None
    # Junction-adjacent samples are still the same trace. They count for the
    # drawn mask. They are left out of the qualifying overlap so a mere join
    # does not become a duplicate by itself.
    qualify_vals = [dist for dist, flag in zip(dists, flags) if flag] or geom_close
    qualify_n = close or sum(geom_flags)
    return {
        "frac": sum(geom_flags) / len(dists),
        "frac_close_run": qualify_n / len(dists),
        "overlap_m": (qualify_n / len(dists)) * src.length,
        "mean_all": sum(dists) / len(dists),
        "mean_close": sum(qualify_vals) / len(qualify_vals),
        "hausdorff": max(qualify_vals),
        "parallel_frac": (parallel_hits / close) if close else 1.0,
        "length": src.length,
        "shares_end": 1.0 if shares_endpoint(src, dst) else 0.0,
        "flags": geom_flags,
        "samples": samples,
    }


def build_grid(features: list[Feat], cell: float = 0.004) -> dict[tuple[int, int], list[int]]:
    grid: dict[tuple[int, int], list[int]] = defaultdict(list)
    for index, feat in enumerate(features):
        x0, y0, x1, y1 = feat.bbox
        for ix in range(int(math.floor((x0 - 0.004) / cell)), int(math.floor((x1 + 0.004) / cell)) + 1):
            for iy in range(int(math.floor((y0 - 0.004) / cell)), int(math.floor((y1 + 0.004) / cell)) + 1):
                grid[(ix, iy)].append(index)
    return grid


def find_covers(features: list[Feat]) -> list[dict[str, Any]]:
    grid = build_grid(features)
    covers = []
    seen: set[tuple[tuple[str, int], tuple[str, int]]] = set()
    for index, src in enumerate(features):
        x0, y0, x1, y1 = src.bbox
        cand: set[int] = set()
        for ix in range(int(math.floor((x0 - 0.004) / 0.004)), int(math.floor((x1 + 0.004) / 0.004)) + 1):
            for iy in range(int(math.floor((y0 - 0.004) / 0.004)), int(math.floor((y1 + 0.004) / 0.004)) + 1):
                cand.update(grid.get((ix, iy), ()))
        for other_index in cand:
            if other_index == index:
                continue
            dst = features[other_index]
            if dst.rank <= src.rank:
                continue
            pair_key = (src.key, dst.key)
            if pair_key in seen:
                continue
            if bbox_gap_m(src, dst) > MAX_DIST_M + 40:
                continue
            stats = measure(src, dst)
            if stats is None or not relation_ok(src, dst, stats):
                continue
            seen.add(pair_key)
            covers.append({"src": src, "dst": dst, "stats": stats})
    return covers


def slice_coords(coords: list[list[float]], start_m: float, end_m: float) -> list[list[float]]:
    acc = cumul(coords)
    total = acc[-1]
    start_m = max(0.0, min(total, start_m))
    end_m = max(0.0, min(total, end_m))
    if end_m - start_m < 30:
        return []

    def at(distance: float) -> list[float]:
        seg = 0
        while seg < len(acc) - 2 and acc[seg + 1] < distance:
            seg += 1
        span = acc[seg + 1] - acc[seg]
        frac = 0.0 if span <= 0 else min(1.0, max(0.0, (distance - acc[seg]) / span))
        return round_pt([
            coords[seg][0] + frac * (coords[seg + 1][0] - coords[seg][0]),
            coords[seg][1] + frac * (coords[seg + 1][1] - coords[seg][1]),
        ])

    out = [at(start_m)]
    for index, coord in enumerate(coords):
        if start_m + 1 < acc[index] < end_m - 1:
            out.append([coord[0], coord[1]])
    out.append(at(end_m))
    deduped = []
    for point in out:
        if not deduped or not coincides(deduped[-1], point):
            deduped.append(point)
    return deduped if len(deduped) >= 2 else []


def coverage_runs(src: Feat, keepers: list[Feat]) -> list[tuple[float, float, bool]]:
    samples = sample_line(src.coords, 40.0)
    if len(samples) < 2:
        return [(0.0, src.length, False)]
    flags = []
    for _dist, point, bearing in samples:
        hit = False
        for keeper in keepers:
            _i, _t, dist, _p, other = nearest_on(keeper.coords, point, src.lat0)
            if dist <= MAX_DIST_M and (angle_diff(bearing, other) <= PARALLEL_DEG or dist <= 30.0):
                hit = True
                break
        flags.append(hit)
    runs: list[tuple[float, float, bool]] = []
    for index, (_dist, _point, _bearing) in enumerate(samples):
        start = samples[index][0]
        end = samples[index + 1][0] if index + 1 < len(samples) else src.length
        covered = flags[index]
        if runs and runs[-1][2] == covered:
            runs[-1] = (runs[-1][0], end, covered)
        else:
            runs.append((start, end, covered))
    return runs


def subcurve_between(donor: list[list[float]], start: list[float], end: list[float], lat0: float) -> list[list[float]] | None:
    s_idx, s_tee, s_dist, s_proj, _b = nearest_on(donor, start, lat0)
    e_idx, e_tee, e_dist, e_proj, _b2 = nearest_on(donor, end, lat0)
    if s_dist > 180 or e_dist > 180:
        return None
    forward = (s_idx, s_tee) <= (e_idx, e_tee)
    if forward:
        points = [round_pt(s_proj)]
        for coord in donor[s_idx + 1:e_idx + 1]:
            points.append([coord[0], coord[1]])
        points.append(round_pt(e_proj))
    else:
        points = [round_pt(s_proj)]
        for coord in reversed(donor[e_idx + 1:s_idx + 1]):
            points.append([coord[0], coord[1]])
        points.append(round_pt(e_proj))
    deduped = []
    for point in points:
        if not deduped or not coincides(deduped[-1], point):
            deduped.append(point)
    if len(deduped) < 2 or length_m(deduped) < 80:
        return None
    return deduped


def spacing(coords: list[list[float]], line_length: float) -> float:
    return line_length / max(len(coords) - 1, 1)


def dump_json(path: str, payload: dict[str, Any]) -> None:
    text = json.dumps(payload, ensure_ascii=False, separators=(",", ":"))
    with open(path, "w", encoding="utf-8") as handle:
        handle.write(text)


def load_json(path: str) -> dict[str, Any]:
    with open(path, encoding="utf-8") as handle:
        return json.load(handle)


def endpoint_index(features: list[Feat]) -> dict[tuple[float, float], list[tuple[str, int]]]:
    index: dict[tuple[float, float], list[tuple[str, int]]] = defaultdict(list)
    for feat in features:
        for coord in (feat.coords[0], feat.coords[-1]):
            index[vertex_key(coord)].append(feat.key)
    return index


def runs_from_flags(samples: list[tuple[float, list[float], float]], flags: list[bool], total: float) -> list[tuple[float, float, bool]]:
    runs: list[tuple[float, float, bool]] = []
    for index, flag in enumerate(flags):
        start = samples[index][0]
        end = samples[index + 1][0] if index + 1 < len(samples) else total
        if runs and runs[-1][2] == flag:
            runs[-1] = (runs[-1][0], end, flag)
        else:
            runs.append((start, end, flag))
    return runs


def plan(features: list[Feat]) -> dict[str, Any]:
    covers = find_covers(features)
    by_src: dict[tuple[str, int], list[dict[str, Any]]] = defaultdict(list)
    for cover in covers:
        by_src[cover["src"].key].append(cover)
    actions = []
    review = []
    for src_key, rows in by_src.items():
        src = rows[0]["src"]
        rows.sort(key=lambda row: (-row["stats"]["overlap_m"], row["stats"]["mean_close"]))
        best = rows[0]
        samples = best["stats"]["samples"]
        mask = [False] * len(samples)
        for row in rows:
            flags = row["stats"]["flags"]
            if len(flags) != len(mask):
                continue
            for index, flag in enumerate(flags):
                if flag:
                    mask[index] = True
        runs = runs_from_flags(samples, mask, src.length)
        unique = [(a, b) for a, b, covered in runs if not covered and b - a >= 40]
        unique_m = sum(b - a for a, b in unique)
        primary = best["dst"]
        record = {
            "layer": src.layer,
            "id": src.ident,
            "name": src.raw_name or src.name,
            "perennial": src.perennial,
            "length_m": round(src.length),
            "keeper_layer": primary.layer,
            "keeper_id": primary.ident,
            "keeper_name": primary.raw_name or primary.name,
            "mean_m": round(best["stats"]["mean_close"], 1),
            "hausdorff_m": round(best["stats"]["hausdorff"], 1),
            "overlap_m": round(best["stats"]["overlap_m"]),
            "frac": round(best["stats"]["frac"], 3),
            "unique_m": round(unique_m),
            "src_key": src.key,
            "keeper_keys": [row["dst"].key for row in rows],
        }
        if unique_m < UNIQUE_KEEP_M or unique_m < 0.16 * src.length:
            record["op"] = "retire"
            actions.append(record)
            continue
        unique.sort(key=lambda span: span[1] - span[0], reverse=True)
        longest = unique[0]
        second = (unique[1][1] - unique[1][0]) if len(unique) > 1 else 0.0
        if second >= SECOND_TAIL_REVIEW_M:
            record["second_tail_m"] = round(second)
            record["tails"] = [(round(a, 1), round(b, 1)) for a, b in unique if b - a >= 40]
            if src.layer.startswith("small"):
                # Hint lines have no model id, so the two remaining arms can both be kept.
                record["op"] = "split"
                actions.append(record)
            else:
                record["op"] = "review_split"
                review.append({k: v for k, v in record.items() if k not in ("src_key", "keeper_keys", "tails")})
            continue
        record["op"] = "trim"
        record["keep_from_m"] = round(longest[0], 1)
        record["keep_to_m"] = round(longest[1], 1)
        record["dropped_tail_m"] = round(second)
        actions.append(record)
        if second >= 180:
            review.append({k: v for k, v in record.items() if k not in ("src_key", "keeper_keys")} | {"op": "review_short_tail"})
    # Drop a retirement whose covering lines are themselves retired, unless another listed keeper stays.
    retired = {row["src_key"] for row in actions if row["op"] == "retire"}
    changed = True
    while changed:
        changed = False
        for row in actions:
            if row["op"] != "retire":
                continue
            if any(key not in retired for key in row["keeper_keys"]):
                continue
            row["op"] = "review_cycle"
            retired.discard(row["src_key"])
            review.append({k: v for k, v in row.items() if k not in ("src_key", "keeper_keys")})
            changed = True
    actions = [row for row in actions if row["op"] in ("retire", "trim", "split")]
    transplants = []
    # A keeper adopts a more detailed donor when that donor is being retired or trimmed
    # and it traces the keeper more finely.
    acted = {(row["layer"], row["id"], row["op"]) for row in actions}
    donor_rows = [row for row in actions if row["op"] in ("retire", "trim")]
    by_keeper: dict[tuple[str, Any], list[dict[str, Any]]] = defaultdict(list)
    for row in donor_rows:
        by_keeper[(row["keeper_layer"], row["keeper_id"])].append(row)
    feat_by = {(feat.layer, feat.ident, feat.key): feat for feat in features}
    # ident can repeat for small streams; keeper ids for model layers are unique per layer
    lookup = {}
    for feat in features:
        lookup.setdefault((feat.layer, feat.ident), []).append(feat)
    for (keeper_layer, keeper_id), rows in by_keeper.items():
        candidates = lookup.get((keeper_layer, keeper_id), [])
        if len(candidates) != 1:
            continue
        keeper = candidates[0]
        best_donor = None
        best_spacing = spacing(keeper.coords, keeper.length)
        for row in rows:
            donors = [feat for feat in features if feat.layer == row["layer"] and feat.ident == row["id"]]
            # small-stream ids repeat; require the same length signature via the action length
            donors = [feat for feat in donors if abs(feat.length - row["length_m"]) < 5]
            if len(donors) != 1:
                continue
            donor = donors[0]
            donor_spacing = spacing(donor.coords, donor.length)
            if donor_spacing > best_spacing * 0.72:
                continue
            if len(donor.coords) < len(keeper.coords) + 3:
                continue
            stats = measure(keeper, donor)
            if stats is None or stats["frac"] < 0.70 or not (12 <= stats["mean_all"] <= MAX_DIST_M):
                continue
            if best_donor is None or donor_spacing < best_spacing:
                best_donor = donor
                best_spacing = donor_spacing
        if best_donor is None:
            continue
        proposed = subcurve_between(best_donor.coords, keeper.coords[0], keeper.coords[-1], keeper.lat0)
        if proposed is None:
            review.append({
                "op": "review_geometry",
                "keeper_layer": keeper.layer,
                "keeper_id": keeper.ident,
                "donor_layer": best_donor.layer,
                "donor_id": best_donor.ident,
                "name": keeper.raw_name or keeper.name,
                "reason": "endpoints sit more than 180 m off the finer trace",
            })
            continue
        new_len = length_m(proposed)
        if new_len < keeper.length * 0.55 or new_len > keeper.length * 1.55:
            review.append({
                "op": "review_geometry",
                "keeper_layer": keeper.layer,
                "keeper_id": keeper.ident,
                "donor_layer": best_donor.layer,
                "donor_id": best_donor.ident,
                "name": keeper.raw_name or keeper.name,
                "reason": "finer trace length does not match the kept segment",
            })
            continue
        pinned = [keeper.coords[0]] + [p for p in proposed[1:-1] if not coincides(p, keeper.coords[0]) and not coincides(p, keeper.coords[-1])] + [keeper.coords[-1]]
        deduped = []
        for point in pinned:
            if not deduped or not coincides(deduped[-1], point):
                deduped.append(point)
        if len(deduped) < 2:
            continue
        transplants.append({
            "layer": keeper.layer,
            "id": keeper.ident,
            "name": keeper.raw_name or keeper.name,
            "donor_layer": best_donor.layer,
            "donor_id": best_donor.ident,
            "old_vertices": len(keeper.coords),
            "new_vertices": len(deduped),
            "coords": deduped,
        })
    return {"covers": covers, "actions": actions, "review": review, "transplants": transplants, "acted_note": len(acted)}


def dedupe_line(coords: list[list[float]]) -> list[list[float]]:
    out: list[list[float]] = []
    for point in coords:
        if not out or not coincides(out[-1], point):
            out.append(point)
    return out


def insert_on_line(coords: list[list[float]], point: list[float], lat0: float) -> tuple[list[list[float]], list[float]]:
    """Return the line with `point` as a vertex, reusing a vertex that is already within 12 m."""
    index, _tee, _dist, proj, _bearing = nearest_on(coords, point, lat0)
    for vertex in (coords[index], coords[index + 1]):
        if meters(vertex, proj) <= 12:
            return coords, [vertex[0], vertex[1]]
    snapped = round_pt(proj)
    return coords[: index + 1] + [snapped] + coords[index + 1 :], snapped


def snap_cut_ends(original: list[list[float]], sliced: list[list[float]], keeper: list[list[float]], lat0: float) -> tuple[list[list[float]], list[list[float]]]:
    """Move a trim-created endpoint onto the keeper and insert that vertex on the keeper."""
    out = [list(point) for point in sliced]
    target = [list(point) for point in keeper]
    for end, orig in ((0, original[0]), (-1, original[-1])):
        if coincides(out[end], orig):
            continue
        _index, _tee, dist, _proj, _bearing = nearest_on(target, out[end], lat0)
        if dist > WELD_MAX_M:
            continue
        target, snapped = insert_on_line(target, out[end], lat0)
        out[end] = snapped
    return dedupe_line(out), target


def apply_plan(root: str, features: list[Feat], result: dict[str, Any]) -> dict[str, int]:
    by_key = {feat.key: feat for feat in features}
    override: dict[tuple[str, int], list[list[float]]] = {}
    remove: set[tuple[str, int]] = set()
    counts = {"retired": 0, "trimmed": 0, "transplanted": 0, "welded": 0, "hidden": 0}

    for row in result["transplants"]:
        twins = [feat for feat in features if feat.layer == row["layer"] and feat.ident == row["id"]]
        if len(twins) != 1:
            continue
        override[twins[0].key] = [list(point) for point in row["coords"]]
        counts["transplanted"] += 1

    def current(feat: Feat) -> list[list[float]]:
        return override.get(feat.key, feat.coords)

    keeper_for: dict[tuple[str, int], Feat] = {}
    for row in result["actions"]:
        src = by_key.get(row.get("src_key"))
        if src is None:
            continue
        twins = [feat for feat in features if feat.layer == row["keeper_layer"] and feat.ident == row["keeper_id"]]
        if len(twins) == 1:
            keeper_for[src.key] = twins[0]

    for row in result["actions"]:
        if row["op"] != "trim":
            continue
        src = by_key.get(row.get("src_key"))
        keeper = keeper_for.get(src.key) if src else None
        if src is None or keeper is None:
            continue
        sliced = slice_coords(src.coords, row["keep_from_m"], row["keep_to_m"])
        if len(sliced) < 2:
            remove.add(src.key)
            counts["retired"] += 1
            continue
        sliced, keeper_line = snap_cut_ends(src.coords, sliced, current(keeper), src.lat0)
        if len(sliced) < 2 or length_m(sliced) < 40:
            remove.add(src.key)
            counts["retired"] += 1
            continue
        override[src.key] = sliced
        override[keeper.key] = keeper_line
        counts["trimmed"] += 1
        counts["welded"] += 1

    split_pieces: dict[tuple[str, int], list[list[list[float]]]] = {}
    for row in result["actions"]:
        if row["op"] != "split":
            continue
        src = by_key.get(row.get("src_key"))
        if src is None:
            continue
        pieces = []
        for start_m, end_m in row.get("tails") or []:
            sliced = slice_coords(src.coords, start_m, end_m)
            if len(sliced) >= 2 and length_m(sliced) >= 40:
                pieces.append(sliced)
        if len(pieces) < 2:
            continue
        remove.add(src.key)
        split_pieces[src.key] = pieces
        counts["trimmed"] += 1

    for row in result["actions"]:
        if row["op"] != "retire":
            continue
        src = by_key.get(row.get("src_key"))
        if src is None:
            continue
        remove.add(src.key)
        counts["retired"] += 1

    shares: dict[tuple[float, float], set[tuple[str, int]]] = defaultdict(set)
    for feat in features:
        for coord in (feat.coords[0], feat.coords[-1]):
            shares[vertex_key(coord)].add(feat.key)

    for src_key in list(remove) + [key for key in override if key not in remove]:
        src = by_key[src_key]
        keeper = keeper_for.get(src_key)
        if keeper is None or keeper.key in remove:
            continue
        final = None if src_key in remove else current(src)
        lost = {vertex_key(src.coords[0]), vertex_key(src.coords[-1])}
        if final is not None and len(final) >= 2:
            lost -= {vertex_key(final[0]), vertex_key(final[-1])}
        if not lost:
            continue
        lat0 = keeper.lat0
        target = current(keeper)
        for lost_key in lost:
            partners = [key for key in shares.get(lost_key, ()) if key != src_key and key not in remove]
            if not partners:
                continue
            anchor = None
            for partner_key in partners:
                partner_line = current(by_key[partner_key])
                for coord in (partner_line[0], partner_line[-1]):
                    if vertex_key(coord) == lost_key:
                        anchor = coord
                        break
                if anchor is not None:
                    break
            if anchor is None:
                continue
            _index, _tee, dist, _proj, _bearing = nearest_on(target, anchor, lat0)
            if dist < 1.5 or dist > WELD_MAX_M:
                continue
            target, snapped = insert_on_line(target, anchor, lat0)
            for partner_key in partners:
                if partner_key == keeper.key:
                    continue
                partner = by_key[partner_key]
                line = [list(point) for point in current(partner)]
                changed = False
                for end in (0, -1):
                    if vertex_key(line[end]) == lost_key:
                        line[end] = [snapped[0], snapped[1]]
                        changed = True
                if changed:
                    override[partner_key] = dedupe_line(line)
                    counts["welded"] += 1
            override[keeper.key] = target

    # One write per site file, using the original feature index.
    site_coords_by_id: dict[str, dict[Any, list[list[float]]]] = defaultdict(dict)
    for layer, rels in LAYER_FILES.items():
        path = f"{root}/{rels[0]}"
        payload = load_json(path)
        kept = []
        changed = False
        for index, feature in enumerate(payload.get("features") or []):
            key = (layer, index)
            if key in remove:
                changed = True
                for piece in split_pieces.get(key, []):
                    clone = json.loads(json.dumps(feature))
                    clone["geometry"] = {"type": "LineString", "coordinates": piece}
                    kept.append(clone)
                continue
            if key in override:
                feature = json.loads(json.dumps(feature))
                feature["geometry"] = {"type": "LineString", "coordinates": override[key]}
                changed = True
            kept.append(feature)
            props = feature.get("properties") or {}
            if "id" in props and isinstance(props["id"], int):
                site_coords_by_id[layer][props["id"]] = feature["geometry"]["coordinates"]
        if changed:
            payload["features"] = kept
            dump_json(path, payload)
        for rel in rels[1:]:
            data_path = f"{root}/{rel}"
            try:
                data_payload = load_json(data_path)
            except FileNotFoundError:
                continue
            removed_ids = {by_key[key].ident for key in remove if key[0] == layer}
            new_features = []
            data_changed = False
            for feature in data_payload.get("features") or []:
                ident = (feature.get("properties") or {}).get("id")
                if ident in removed_ids:
                    data_changed = True
                    continue
                if ident in site_coords_by_id[layer] and feature["geometry"]["coordinates"] != site_coords_by_id[layer][ident]:
                    feature["geometry"]["coordinates"] = site_coords_by_id[layer][ident]
                    data_changed = True
                new_features.append(feature)
            if data_changed:
                data_payload["features"] = new_features
                dump_json(data_path, data_payload)

    hidden_ids: dict[str, set[int]] = defaultdict(set)
    display_updates: dict[str, dict[int, list[list[float]]]] = defaultdict(dict)
    for key in remove:
        feat = by_key[key]
        if feat.model_layer and isinstance(feat.ident, int):
            hidden_ids[feat.model_layer].add(feat.ident)
    for key, coords in override.items():
        if key in remove:
            continue
        feat = by_key[key]
        if feat.model_layer and isinstance(feat.ident, int):
            display_updates[feat.model_layer][feat.ident] = coords
    for layer, rel in MODEL_GZ.items():
        path = f"{root}/{rel}"
        with gzip.open(path, "rt", encoding="utf-8") as handle:
            payload = json.load(handle)
        changed = False
        for segment in payload.get("segments") or []:
            ident = segment.get("id")
            if ident in hidden_ids[layer] and int(segment.get("hidden") or 0) != 1:
                segment["hidden"] = 1
                changed = True
                counts["hidden"] += 1
            if ident in display_updates[layer]:
                segment["coords_display"] = display_updates[layer][ident]
                changed = True
        if changed:
            text = json.dumps(payload, ensure_ascii=False, separators=(",", ":"))
            with gzip.open(path, "wt", encoding="utf-8") as handle:
                handle.write(text)
    return counts





def gap_report(root: str) -> list[str]:
    """Endpoints that used to be shared should still lie on some drawn line."""
    features = load_features(root)
    problems = []
    index_pts: list[tuple[Feat, list[float]]] = []
    for feat in features:
        index_pts.append((feat, feat.coords[0]))
        index_pts.append((feat, feat.coords[-1]))
    # A gap is an endpoint more than 25 m from every other feature and more than 25 m
    # from its own line only. True sources are allowed. We only flag endpoints whose
    # nearest other line is between 25 and 80 m: a small new gap. Larger separations
    # are distinct channels.
    for feat in features:
        for end in (feat.coords[0], feat.coords[-1]):
            best = 1e9
            for other in features:
                if other.key == feat.key:
                    continue
                if bbox_gap_m(feat, other) > 200:
                    continue
                _i, _t, dist, _p, _b = nearest_on(other.coords, end, feat.lat0)
                if dist < best:
                    best = dist
            if 8 < best <= 22:
                problems.append(f"{feat.layer}:{feat.ident} end {end[0]:.5f},{end[1]:.5f} is {best:.0f} m from every other line")
                if len(problems) > 30:
                    return problems
    return problems


def summarize(result: dict[str, Any]) -> None:
    actions = result["actions"]
    log(f"זוגות כיסוי: {len(result['covers'])}")
    log(f"פעולות: {len(actions)} (הסרה {sum(1 for a in actions if a['op']=='retire')}, קיצור {sum(1 for a in actions if a['op']=='trim')})")
    log(f"העברת גיאומטריה למזהה שנשמר: {len(result['transplants'])}")
    log(f"לבדיקה ידנית: {len(result['review'])}")
    log("--- דוגמאות ---")
    for row in actions[:25]:
        log(
            f"  {row['op']:6} {row['layer']}:{row['id']} {row['name'] or '-'} "
            f"{row['length_m']}m mean {row['mean_m']}m haus {row['hausdorff_m']}m "
            f"-> {row['keeper_layer']}:{row['keeper_id']} {row['keeper_name'] or '-'}"
        )
    if result["review"]:
        log("--- review ---")
        for row in result["review"][:15]:
            log(f"  {row.get('op')} {row.get('layer')}:{row.get('id')} {row.get('name')} {row.get('reason','')}")


def self_test() -> None:
    def line(lon0: float, lat0: float, lon1: float, lat1: float, n: int = 8) -> list[list[float]]:
        return [[lon0 + (lon1 - lon0) * i / (n - 1), lat0 + (lat1 - lat0) * i / (n - 1)] for i in range(n)]

    # ~2 km north-south near the coast, and a parallel line ~120 m to the east.
    main = line(34.80, 31.70, 34.80, 31.718, 12)
    shifted = [[c[0] + 0.00125, c[1]] for c in main]
    crossing = line(34.79, 31.709, 34.82, 31.709, 6)
    features = [
        Feat("nondesert", 0, 1, "בדיקה", "נחל בדיקה", True, 10, main, length_m(main), 31.71, (34.8, 31.7, 34.8, 31.72), ("nondesert", 0)),
        Feat("desert", 1, 2, "בדיקה", "נחל בדיקה", False, 10, shifted, length_m(shifted), 31.71, (34.801, 31.7, 34.801, 31.72), ("desert", 1)),
        Feat("nondesert", 2, 3, "אחר", "נחל אחר", False, 4, crossing, length_m(crossing), 31.709, (34.79, 31.709, 34.82, 31.709), ("nondesert", 2)),
    ]
    for feat in features:
        feat.rank = (LAYER_RANK[feat.layer] + (40 if feat.perennial else 0) + 20, feat.length, len(feat.coords), -int(feat.ident))
    covers = find_covers(features)
    pairs = {(c["src"].ident, c["dst"].ident) for c in covers}
    if (2, 1) not in pairs:
        raise SystemExit(f"self-test failed: shifted desert twin was not covered, got {pairs}")
    if any(src == 3 or dst == 3 for src, dst in pairs):
        raise SystemExit(f"self-test failed: crossing line was treated as a duplicate {pairs}")
    log("self-test ok")


def main() -> None:
    parser = argparse.ArgumentParser(description="Find or merge near-parallel duplicate streams on the public map.")
    parser.add_argument("--root", default=ROOT_DEFAULT)
    parser.add_argument("--write", action="store_true", help="retire or trim duplicate display lines")
    parser.add_argument("--self-test", action="store_true")
    args = parser.parse_args()
    self_test()
    if args.self_test:
        return
    features = load_features(args.root)
    result = plan(features)
    summarize(result)
    if not args.write:
        if result["actions"]:
            log(f"FAIL {len(result['actions'])} near-parallel duplicates remain (mean/Hausdorff under {MAX_DIST_M:.0f} m)")
            sys.exit(1)
        log("ok no near-parallel duplicates above the threshold")
        return
    counts = apply_plan(args.root, features, result)
    log(f"write {counts}")
    again = plan(load_features(args.root))
    if again["actions"]:
        log(f"FAIL {len(again['actions'])} duplicates remain after write")
        summarize(again)
        sys.exit(1)
    gaps = gap_report(args.root)
    if gaps:
        log("WARN possible new gaps:")
        for line in gaps:
            log("  " + line)
    log("ok duplicates cleared")


if __name__ == "__main__":
    main()
