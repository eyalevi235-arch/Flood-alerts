#!/usr/bin/env python3
"""Build site/data/israel_border.geojson from Natural Earth 10m admin-0 countries (public domain).

Keeps only the land borders of the outer boundary of Israel + Palestine (NE 'ISR' + 'PSX'), i.e. the parts
shared with Lebanon, Syria, Jordan and Egypt. No coastline, no Green Line, no internal West Bank/Gaza lines.
NE puts the Golan Heights inside ISR, so the Syria part follows the 1974 ceasefire line.

Usage: python tools/build_israel_border.py SRC.geojson [OUT] [--no-gaza-egypt]
SRC: https://raw.githubusercontent.com/nvkelso/natural-earth-vector/master/geojson/ne_10m_admin_0_countries.geojson
Then run tools/splice_osm_arava_border.py to replace the Arava stretch (NE is 1-4 km off there) with OSM (ODbL).
"""
import json, sys
from shapely.geometry import shape, mapping
from shapely.ops import unary_union, linemerge

NEIGHBORS = ('LBN', 'SYR', 'JOR', 'EGY')
SNAP = 0.0005      # deg, to match shared edges
SIMPLIFY = 0.0004  # deg, ~40 m


def main():
    args = [a for a in sys.argv[1:] if not a.startswith('--')]
    src = args[0]
    out = args[1] if len(args) > 1 else 'site/data/israel_border.geojson'
    feats = {f['properties']['ADM0_A3']: shape(f['geometry']) for f in json.load(open(src, encoding='utf-8'))['features']
             if f['properties'].get('ADM0_A3') in ('ISR', 'PSX') + NEIGHBORS}
    land = unary_union([feats['ISR'], feats['PSX']])
    edge = land.boundary
    parts = []
    for n in NEIGHBORS:
        nb = feats[n].buffer(SNAP)
        if n == 'EGY' and '--no-gaza-egypt' in sys.argv:
            nb = nb.difference(feats['PSX'].buffer(SNAP * 4))
        parts.append(edge.intersection(nb))
    lines = linemerge(unary_union(parts)).simplify(SIMPLIFY, preserve_topology=True)
    geoms = list(lines.geoms) if hasattr(lines, 'geoms') else [lines]
    geoms = [g for g in geoms if g.geom_type == 'LineString' and g.length > 0.005]
    coords = [[[round(x, 5), round(y, 5)] for x, y in g.coords] for g in geoms]
    fc = {'type': 'FeatureCollection', 'features': [{'type': 'Feature', 'properties': {
        'source': 'Natural Earth 10m admin-0 countries (public domain)', 'kind': 'israel_land_border'},
        'geometry': {'type': 'MultiLineString', 'coordinates': coords}}]}
    with open(out, 'w', encoding='utf-8') as fh:
        json.dump(fc, fh, separators=(',', ':'))
    print(out, len(coords), 'lines', sum(len(c) for c in coords), 'points')


if __name__ == '__main__':
    main()
