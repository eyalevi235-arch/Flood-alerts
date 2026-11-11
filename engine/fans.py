"""Alluvial-fan add-on for the hourly job.

Does not change model probabilities, calibration.json, or thresholds.
Writes site/data/segment_fans.json and segment_fans_nondesert.json with a
"possible spreading" flag (התפשטות אפשרית) and an arrival-time range.

The probability used to colour a fan is the probability at the fan-head
(apex) segment. Arrays p/lead/em/tp/tm in segment_risk*.json are never
opened for writing. Road crossings are information only, not an alert.
Push logic is unchanged.
"""
from __future__ import annotations

import json
import math
from pathlib import Path

VEL_MS = (0.5, 2.0)  # remaining-distance travel on the fan


def repo_root(root=None):
    if root is not None:
        return Path(root)
    return Path(__file__).resolve().parents[1]


def jload(path, default=None):
    try:
        return json.loads(Path(path).read_text(encoding='utf-8'))
    except Exception:
        return default


def jsave(path, obj):
    path = Path(path)
    tmp = path.with_suffix(path.suffix + '.tmp')
    tmp.write_text(json.dumps(obj, ensure_ascii=False, separators=(',', ':'), allow_nan=False), encoding='utf-8')
    tmp.replace(path)


def _travel_min(remaining_km):
    L = max(float(remaining_km or 0.0), 0.0) * 1000.0
    return round(L / VEL_MS[1] / 60.0, 1), round(L / VEL_MS[0] / 60.0, 1)


def load_mapping(root):
    root = repo_root(root)
    raw = jload(root / 'data' / 'fan_segments.json', [])
    if isinstance(raw, dict):
        rows = raw.get('segments') or raw.get('rows') or []
    else:
        rows = raw
    desert, north, exts_d, exts_n = [], [], [], []
    for r in rows:
        layer = r.get('layer') or ''
        rec = dict(r)
        rec['id'] = int(r['id'])
        if r.get('kind') == 'ext' or 'extension' in layer:
            (exts_n if 'nondesert' in layer else exts_d).append(rec)
        elif 'nondesert' in layer or layer.endswith('v3e_segment'):
            north.append(rec)
        else:
            desert.append(rec)
    return desert, north, exts_d, exts_n


def _n_array(risk):
    p = (risk or {}).get('p') or []
    return len(p)


def compact(rows, exts, risk, *, region, issued, t0, extra=None):
    n = _n_array(risk) if risk else (max((r['id'] for r in rows), default=-1) + 1)
    spread = [0] * n
    fan_id = [None] * n
    fan_pos = [None] * n
    apex = [None] * n
    rel_lo = [None] * n
    rel_hi = [None] * n
    eta_lo = [None] * n
    eta_hi = [None] * n
    flag_he = [None] * n
    em = (risk or {}).get('em') or []

    def abs_range(apex_id, lo, hi):
        if apex_id is None or apex_id < 0 or apex_id >= len(em):
            return None, None
        a = em[apex_id]
        if a is None or a < 0:
            return None, None
        return int(round(a + lo)), int(round(a + hi))

    for r in rows:
        i = int(r['id'])
        if i >= n:
            # sparse id beyond current risk array: skip rather than change risk length
            continue
        lo, hi = _travel_min(r.get('remaining_km'))
        if lo is None and r.get('fan_pos') is not None:
            # no remaining_km stored; leave relative range empty
            lo, hi = None, None
        aid = r.get('fan_apex_seg')
        aid = int(aid) if aid is not None and aid != '' else None
        alo, ahi = abs_range(aid, lo or 0, hi or 0) if lo is not None else (None, None)
        spread[i] = 1
        fan_id[i] = r.get('fan_id')
        fan_pos[i] = r.get('fan_pos')
        apex[i] = aid
        rel_lo[i] = lo
        rel_hi[i] = hi
        eta_lo[i] = alo
        eta_hi[i] = ahi
        flag_he[i] = 'התפשטות אפשרית'

    ext_out = []
    for r in exts:
        lo, hi = _travel_min(r.get('remaining_km'))
        aid = r.get('fan_apex_seg')
        aid = int(aid) if aid is not None and aid != '' else None
        alo, ahi = abs_range(aid, lo or 0, hi or 0) if lo is not None else (None, None)
        ext_out.append(dict(
            id=int(r['id']), fan_id=r.get('fan_id'), name_he=r.get('name_he') or '',
            fan_pos=r.get('fan_pos'), fan_apex_seg=aid, possible_spreading=True,
            flag_he='התפשטות אפשרית', rel_lo=lo, rel_hi=hi, eta_lo=alo, eta_hi=ahi,
            info_only=True,
        ))

    out = dict(
        v=1, kind='alluvial_fans', region=region, issued=issued, t0=t0,
        n_array=n, n_flagged=int(sum(spread)), n_extensions=len(ext_out),
        note='spread=1 means possible spreading on an alluvial fan. '
             'Display probability for the fan polygon is p[fan_apex_seg]. '
             'segment_risk p/lead/em are unchanged. Crossings are information only.',
        credit='Copernicus DEM GLO-30 (© DLR/ESA, European Union) + OpenStreetMap contributors (ODbL) for road crossings',
        spread=spread, fan_id=fan_id, fan_pos=fan_pos, apex=apex,
        rel_lo=rel_lo, rel_hi=rel_hi, eta_lo=eta_lo, eta_hi=eta_hi, flag_he=flag_he,
        extensions=ext_out,
    )
    if extra:
        out.update(extra)
    return out


def write_from_job(fe=None, now=None, site_dir=None, *, root=None, issued=None, t0=None):
    """Called from run_job.py after segment_risk*.json have been written.

    Never writes those files. Never raises to the caller if wrapped in try/except.
    """
    root = repo_root(root)
    site = Path(site_dir or (root / 'site' / 'data'))
    if issued is None:
        issued = None
        if fe is not None and now is not None and hasattr(fe, 'il'):
            issued = fe.il(now)
    risk_d = jload(site / 'segment_risk.json', {})
    risk_n = jload(site / 'segment_risk_nondesert.json', {})
    if issued is None:
        issued = (risk_d or {}).get('issued') or (risk_n or {}).get('issued')
    if t0 is None:
        t0 = (risk_d or {}).get('t0') or (risk_n or {}).get('t0')
    desert, north, exts_d, exts_n = load_mapping(root)
    d_compact = compact(desert, exts_d, risk_d, region='desert', issued=issued, t0=t0,
                        extra={'geom_version': 'v8p'})
    n_compact = compact(north, exts_n, risk_n, region='north_center', issued=issued, t0=t0,
                        extra={'geom_version': 'v3e'})
    jsave(site / 'segment_fans.json', d_compact)
    jsave(site / 'segment_fans_nondesert.json', n_compact)
    print(
        f"alluvial fans: desert {d_compact['n_flagged']} segments / {d_compact['n_extensions']} extensions; "
        f"nondesert {n_compact['n_flagged']} segments / {n_compact['n_extensions']} extensions"
    )
    return dict(desert=d_compact, nondesert=n_compact)


def probabilities_unchanged(before, after, keys=('p', 'lead', 'em', 'tp', 'tm', 'rain')):
    """Numeric identity check. Returns (ok, report). `rain` may already be stripped in public files."""
    diffs = []
    for k in keys:
        if k not in before and k not in after:
            continue
        a, b = before.get(k), after.get(k)
        if a == b:
            continue
        if not isinstance(a, list) or not isinstance(b, list) or len(a) != len(b):
            diffs.append(dict(key=k, reason='length_or_type', n_before=len(a) if isinstance(a, list) else None,
                              n_after=len(b) if isinstance(b, list) else None))
            continue
        n = 0
        mx = 0.0
        for i, (x, y) in enumerate(zip(a, b)):
            if x is None and y is None:
                continue
            if x != y:
                n += 1
                try:
                    mx = max(mx, abs(float(x) - float(y)))
                except (TypeError, ValueError):
                    mx = math.inf
        if n:
            diffs.append(dict(key=k, n_changed=n, max_abs=mx, n=len(a)))
    return (not diffs), diffs
