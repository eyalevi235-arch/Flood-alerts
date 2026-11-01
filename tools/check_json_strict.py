#!/usr/bin/env python3
"""Strict JSON check: fails on NaN/Infinity or any invalid JSON in site/data."""
import glob,json,sys
def bad(c): raise ValueError('non-standard constant '+c)
d=sys.argv[1] if len(sys.argv)>1 else 'site/data'
fs=sorted(glob.glob(d+'/*.json')+glob.glob(d+'/*.geojson'));err=0
for f in fs:
    try: json.load(open(f,encoding='utf-8'),parse_constant=bad)
    except Exception as e: err+=1;print('FAIL',f,e)
print(f'{len(fs)-err}/{len(fs)} strict JSON OK');sys.exit(1 if err else 0)
