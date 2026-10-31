"""Build site/data/channel_points.json on the box that has the DEM and flow rasters.

This repo does not contain those rasters. Run this next to the same tree that
tools/precompute_catchments.py already uses:

    /workspace/flood/gis/fdir.tif
    /workspace/flood/gis/fdir.npy
    /workspace/flood/gis/acc.npy
    /workspace/flood/gis/dem.tif
    /workspace/flood/gis/curve_number.tif   (optional; missing -> CN 90)
    /workspace/flood/arrival/travel_time.py
    /workspace/flood/arrival/routing.py
    /workspace/flood/arrival/forecast.py    (fc.LAT, fc.LON, fc.RES)

Input lines are site/data/streams.geojson in this repo, feature order unchanged.
`seg` is that feature's index. Samples are the first vertex, then every vertex
at least 500 m from the previous sample, then the last vertex.

Each sample is the D8 catchment draining TO that channel pixel (travel_time.catchment),
not the basin outlet. Travel times are seconds from each upstream cell to THIS point.

Output schema (compact JSON, one object):

{
  "v": 1,
  "sample_m": 500,
  "grid": {"res": 0.1, "lat0": 33.4, "lon0": 34.2, "nlat": 41, "nlon": 19},
  "dt_min": 10,
  "cn_bin": 5,
  "points": [
    {
      "id": "c000000",
      "seg": 0,
      "lat": 30.46683,
      "lon": 35.16853,
      "area_km2": 18.42,
      "elev_m": 412,
      "relief_m": 155,
      "tt_p10_s": 840,
      "tt_med_s": 2100,
      "acc_km2": 43.0,
      "cells": [[28, 9, 4200, 90, 600, 710]]
    }
  ]
}

grid row 0 is lat0 (33.4), column 0 is lon0 (34.2), same (r, c) as data/catchments.json.
cells tuple: [r, c, w_1e4, cn, tt_s, km2_1e2]
  w_1e4   weight * 10000, sums to 10000 across the point (rain weight, split by km2 if one
          Open-Meteo cell has more than one CN bin, so the cell is not counted twice)
  cn      curve number binned to 5
  tt_s    median travel time, in seconds, of the DEM cells in this bin to THIS channel point
  km2_1e2 upstream area of this bin, in hundredths of a km2

area_km2 is the upstream contributing area of the sample. tt_p10_s / tt_med_s are the
10th percentile and median of DEM-cell travel times to the sample. They must be the
catchment of the sample, not copied from the basin outlet.
"""
import json, os, sys, time
import numpy as np
import pandas as pd
from affine import Affine

R = os.environ.get('FLOOD_ROOT', '/workspace/flood')
sys.path.insert(0, R)
sys.path.insert(0, os.path.join(R, 'arrival'))
os.chdir(os.path.join(R, 'arrival'))
import travel_time as tt  # noqa: E402
import routing as rt  # noqa: E402
import forecast as fc  # noqa: E402

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
STREAMS = os.path.join(ROOT, 'site', 'data', 'streams.geojson')
OUT = os.path.join(ROOT, 'site', 'data', 'channel_points.json')
SAMPLE_M = 500
TR = Affine(fc.RES, 0, fc.LON[0] - fc.RES / 2, 0, -fc.RES, fc.LAT[0] + fc.RES / 2)
SH = (len(fc.LAT), len(fc.LON))
P = rt.P


def samples(coords):
    kept = [coords[0]]
    acc = 0.0
    for i in range(1, len(coords)):
        lon0, lat0 = coords[i - 1]
        lon1, lat1 = coords[i]
        acc += np.hypot((lon1 - lon0) * np.cos(np.radians(lat1)) * 111320, (lat1 - lat0) * 110540)
        if acc >= SAMPLE_M:
            kept.append(coords[i])
            acc = 0.0
    if kept[-1] != coords[-1]:
        kept.append(coords[-1])
    return kept


def pack(lat, lon, acc_km2):
    z = tt.catchment(lat, lon)
    g = tt.grids()
    x, y = g['tr'] * (z['cols'] + 0.5, z['rows'] + 0.5)
    col, row = ~TR * (x, y)
    row = np.clip(row.astype(int), 0, SH[0] - 1)
    col = np.clip(col.astype(int), 0, SH[1] - 1)
    cn, _src = rt.cn_for(z, P['CN_DESERT'])
    cnb = np.round(cn / P['CN_BIN']) * P['CN_BIN']
    uniq = pd.DataFrame({'r': row, 'c': col}).drop_duplicates()
    gx, gy = TR * (uniq.c.values + 0.5, uniq.r.values + 0.5)
    dist = np.hypot((gx - lon) * np.cos(np.radians(lat)), gy - lat) * 111
    dw = 1 / (1 + dist / max(float(np.median(dist)), 1))
    weight = {(int(rr), int(cc)): float(ww) for rr, cc, ww in zip(uniq.r, uniq.c, dw)}
    frame = pd.DataFrame({
        'r': row, 'c': col, 'cn': cnb,
        'tt': np.asarray(z['tt_s'], dtype='float64'),
        'km': np.asarray(z['cellkm2'], dtype='float64'),
    })
    grouped = frame.groupby(['r', 'c', 'cn'], sort=True)
    rows = []
    raw = []
    for (rr, cc, cn_v), part in grouped:
        km = float(part.km.sum())
        raw.append(km * weight[(int(rr), int(cc))])
        rows.append([int(rr), int(cc), 0, int(cn_v), int(round(float(np.median(part.tt)))), int(round(km * 100))])
    scale = sum(raw) or 1
    for i, w in enumerate(raw):
        rows[i][2] = int(round(10000 * w / scale))
    drift = 10000 - sum(row[2] for row in rows)
    if rows:
        rows[0][2] += drift
    dem = g['dem'][z['rows'], z['cols']]
    return dict(
        lat=round(float(lat), 5), lon=round(float(lon), 5),
        area_km2=round(float(z['area_km2']), 2),
        elev_m=int(round(float(dem.mean()))),
        relief_m=int(round(float(dem.max() - dem.min()))),
        tt_p10_s=int(round(float(np.percentile(z['tt_s'], 10)))),
        tt_med_s=int(round(float(np.median(z['tt_s'])))),
        acc_km2=None if acc_km2 is None else round(float(acc_km2), 1),
        cells=rows,
    )


def main():
    fc_streams = json.load(open(STREAMS))
    points = []
    t0 = time.time()
    for seg, feat in enumerate(fc_streams['features']):
        geom = feat.get('geometry') or {}
        coords = geom.get('coordinates') or []
        if geom.get('type') != 'LineString' or len(coords) < 2:
            continue
        acc = (feat.get('properties') or {}).get('acc_km2')
        for lon, lat in samples(coords):
            try:
                row = pack(lat, lon, acc)
            except Exception as exc:
                print('fail', seg, lat, lon, exc, flush=True)
                continue
            row['id'] = 'c%06d' % len(points)
            row['seg'] = seg
            points.append(row)
        if seg and seg % 200 == 0:
            print('segments', seg, 'points', len(points), 'sec', int(time.time() - t0), flush=True)
    out = dict(
        v=1, sample_m=SAMPLE_M,
        grid=dict(res=float(fc.RES), lat0=float(fc.LAT[0]), lon0=float(fc.LON[0]), nlat=int(len(fc.LAT)), nlon=int(len(fc.LON))),
        dt_min=int(P['DT_MIN']), cn_bin=int(P['CN_BIN']),
        points=points,
    )
    json.dump(out, open(OUT, 'w'), separators=(',', ':'))
    print('wrote', OUT, 'points', len(points), 'bytes', os.path.getsize(OUT), 'sec', int(time.time() - t0))


if __name__ == '__main__':
    main()
