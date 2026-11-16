#!/usr/bin/env python3
"""Public-data guard (CI): fails if any JSON/GeoJSON under the given site dir has a rain/mm key
(same rule as engine/run_job.py _public / tools/strip_public_rain.py), or if an internal radar rain
grid (radar_rain_grid*) exists anywhere in the checkout. IMS rule: model outputs may be public,
raw radar and rain amounts may not.
Usage: python tools/check_public_no_rain.py [site/data] [repo_root]"""
import glob, json, os, re, sys
NO_PUBLIC = re.compile(r'(^|_)rain|(^|_)mm(_|$)')
def bad_keys(o, path, out):
    if isinstance(o, dict):
        for k, v in o.items():
            if isinstance(k, str) and NO_PUBLIC.search(k): out.append(f'{path}.{k}')
            bad_keys(v, f'{path}.{k}', out)
    elif isinstance(o, list):
        for i, v in enumerate(o[:100000]): bad_keys(v, path + '[]', out)
def main():
    d = sys.argv[1] if len(sys.argv) > 1 else 'site/data'
    root = sys.argv[2] if len(sys.argv) > 2 else '.'
    err = 0
    for dp, dn, fn in os.walk(root):
        dn[:] = [x for x in dn if x not in ('.git', '.om_cache', '.venv', 'node_modules')]
        for f in fn:
            if f.startswith('radar_rain_grid'):
                err += 1; print('FAIL internal radar rain grid in checkout:', os.path.join(dp, f))
    fs = sorted(glob.glob(os.path.join(d, '**', '*.json'), recursive=True) + glob.glob(os.path.join(d, '**', '*.geojson'), recursive=True))
    for f in fs:
        try: o = json.load(open(f, encoding='utf-8'))
        except Exception: continue  # syntax is check_json_strict.py's job
        out = []; bad_keys(o, '', out)
        if out:
            err += 1; print('FAIL rain/mm keys in', f, sorted(set(out))[:5])
    print(f'{len(fs)} public JSON files checked; {err} problem(s)')
    sys.exit(1 if err else 0)
if __name__ == '__main__': main()
