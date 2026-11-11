#!/usr/bin/env python3
"""Replace the Arava stretch (south end of the Dead Sea -> Gulf of Aqaba/Eilat) of the Israel-Jordan line in
site/data/israel_border.geojson with the OpenStreetMap international boundary (admin_level=2), which is more
accurate there than Natural Earth 10m (NE puts the line 1-4 km too far west, e.g. Ein Yahav fell into Jordan).

Source: OSM ways shared by the Israel (r1473946) and Jordan (r184818) admin_level=2 relations, read from the
public OSM API (api.openstreetmap.org/api/0.6). Data (c) OpenStreetMap contributors, ODbL 1.0.
The rest of the border (Lebanon, Golan, Jordan north of the splice, Egypt) is left exactly as it was.

Usage: python tools/splice_osm_arava_border.py [BORDER] [--cache DIR]
  BORDER defaults to site/data/israel_border.geojson (rewritten in place). Run it on a Natural Earth border
  built by tools/build_israel_border.py; it refuses to run twice (checks the source property).
"""
import json, os, sys, urllib.request
from shapely.geometry import LineString, Point
from shapely.ops import linemerge, substring

ISR, JOR = 1473946, 184818
SPLICE_LAT = (31.05, 31.45)   # splice inside the Dead Sea southern basin/Lisan, where NE and OSM are closest
SOUTH_LAT = 29.48             # cut the OSM line at the head of the gulf (the OSM line continues offshore)
SIMPLIFY = 0.0004             # deg, ~40 m (same as build_israel_border.py)
UA = {'User-Agent': 'flood-alerts-border-build/1.0 (github.com/eyalevi235-arch/Flood-alerts)'}
JOR_START = (35.75744, 32.74428)   # first vertex of the Jordan line in the NE build (used by consumers to find it)


def get(url, cache, name):
    p = os.path.join(cache, name) if cache else None
    if p and os.path.exists(p):
        return json.load(open(p))
    d = json.load(urllib.request.urlopen(urllib.request.Request(url, headers=UA), timeout=60))
    if p:
        os.makedirs(cache, exist_ok=True); json.dump(d, open(p, 'w'))
    return d


def osm_line(cache):
    api = 'https://api.openstreetmap.org/api/0.6/'
    mem = [{m['ref'] for m in get(api + 'relation/%d.json' % r, cache, 'rel_%d.json' % r)['elements'][0]['members']
            if m['type'] == 'way'} for r in (ISR, JOR)]
    lines = []
    for w in sorted(mem[0] & mem[1]):
        el = get(api + 'way/%d/full.json' % w, cache, 'way_%d.json' % w)['elements']
        n = {e['id']: (e['lon'], e['lat']) for e in el if e['type'] == 'node'}
        way = [e for e in el if e['type'] == 'way'][0]
        lines.append(LineString([n[i] for i in way['nodes']]))
    m = linemerge(lines)
    south = [g for g in getattr(m, 'geoms', [m]) if min(y for _, y in g.coords) < 30]
    assert len(south) == 1, 'expected one continuous southern OSM Israel-Jordan line'
    g = south[0]
    return g if g.coords[0][1] > g.coords[-1][1] else LineString(g.coords[::-1])   # north -> south


def main():
    argv = sys.argv[1:]
    cache = None
    if '--cache' in argv:
        i = argv.index('--cache'); cache = argv[i + 1]; del argv[i:i + 2]
    path = argv[0] if argv else 'site/data/israel_border.geojson'
    fc = json.load(open(path, encoding='utf-8'))
    f = fc['features'][0]
    assert 'OpenStreetMap' not in f['properties'].get('source', ''), 'already spliced'
    L = f['geometry']['coordinates']
    k = [i for i, l in enumerate(L) if abs(l[0][0] - JOR_START[0]) < 1e-3 and abs(l[0][1] - JOR_START[1]) < 1e-3]
    assert len(k) == 1, 'Jordan line not found'
    ne = LineString(L[k[0]]); osm = osm_line(cache)
    # splice point: NE vertex in the Dead Sea window closest to the OSM line
    cand = [Point(c) for c in ne.coords if SPLICE_LAT[0] <= c[1] <= SPLICE_LAT[1]]
    sp = min(cand, key=lambda p: osm.distance(p))
    ne_part = substring(ne, 0, ne.project(sp))
    o0 = osm.project(osm.interpolate(osm.project(sp)))
    cut = osm.intersection(LineString([(34.5, SOUTH_LAT), (36, SOUTH_LAT)]))
    o1 = osm.project(cut if cut.geom_type == 'Point' else list(cut.geoms)[0]) if not cut.is_empty else osm.length
    osm_part = substring(osm, o0, o1).simplify(SIMPLIFY, preserve_topology=True)
    coords = [list(c) for c in ne_part.coords] + [list(c) for c in osm_part.coords]
    L[k[0]] = [[round(x, 5), round(y, 5)] for x, y in coords]
    f['properties']['source'] = ('Natural Earth 10m admin-0 countries (public domain); Arava stretch %.3fN-%.3fN: '
                                 '(c) OpenStreetMap contributors, ODbL (Israel-Jordan admin_level=2 boundary)'
                                 % (osm_part.coords[0][1], osm_part.coords[-1][1]))
    with open(path, 'w', encoding='utf-8') as fh:
        json.dump(fc, fh, separators=(',', ':'))
    print(path, 'splice at %.5f,%.5f (gap %.0f m); OSM part %d points, %.3fN -> %.3fN' % (
        sp.x, sp.y, osm.distance(sp) * 1e5, len(osm_part.coords), osm_part.coords[0][1], osm_part.coords[-1][1]))


if __name__ == '__main__':
    main()
