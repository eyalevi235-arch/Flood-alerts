#!/usr/bin/env python3
"""Drop rain amounts from public JSON/GeoJSON under site/data (same rule as engine/run_job.py _public).
Usage: python tools/strip_public_rain.py FILE... (rewrites in place; alerts_*.json keep indent=1)."""
import json, re, sys
NO_PUBLIC = re.compile(r'(^|_)rain|(^|_)mm(_|$)')
def public(o):
    if isinstance(o, dict): return {k: public(v) for k, v in o.items() if not (isinstance(k, str) and NO_PUBLIC.search(k))}
    if isinstance(o, list): return [public(v) for v in o]
    return o
for p in sys.argv[1:]:
    o = json.load(open(p, encoding='utf-8'))
    n = public(o)
    if n == o: continue
    ind = 1 if '/alerts_' in p else None
    with open(p, 'w', encoding='utf-8') as fh:
        json.dump(n, fh, ensure_ascii=False, indent=ind, separators=None if ind else (',', ':'))
    print('stripped', p)
