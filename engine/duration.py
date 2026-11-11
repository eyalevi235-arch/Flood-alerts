"""Flow-duration add-on for the Flood-alerts hourly job.

Predicts hours of flow IF a flood occurs (LightGBM on rain-event features +
basin statics + derived geology). Duration is computed at the basin outlet
and inherited by every channel segment of that basin.

Writes site/data/segment_duration.json and segment_duration_nondesert.json
in the same sparse, id-indexed layout as segment_risk*.json (gaps are null).
Does not modify risk values, calibration, thresholds, or segment_risk*.json.

Model files (relative to the repo root, parent of engine/):
  model/flow_duration_geo_lgbm.txt
  model/flow_duration_features.json
  data/basin_geology.csv
"""
from __future__ import annotations

import json, math, os, traceback
from pathlib import Path

import numpy as np
import pandas as pd
import lightgbm as lgb

MIN_P = 0.05
CATS = ((3, 'פחות מ-3 שעות'), (12, '3–12 שעות'), (24, '12–24 שעות'), (1e9, 'יותר מיממה'))
# Official 5-seed MAE, p2b/flow_duration/metrics_geo.json, test from 2020-10-01.
MAE_H = {'desert': 9.26, 'nondesert': 20.14, 'all': 18.44}
MEDAE_H = {'desert': 4.89, 'nondesert': 11.76, 'all': 10.22}
STATIC = [
    'desert', 'perennial', 'cn_mean', 'f_rock', 'f_hsgAB', 'f_built', 'f_veg',
    'clay_mean', 'sand_mean', 'osm_len_km',
]
GEO_COLS = ['f_young_sed', 'f_carb', 'f_cryst']
DISCLAIMER_SHORT = (
    'הערכת משך זרימה בלבד; שגיאה טיפוסית כ-9 שעות בנחלי המדבר וכ-20 שעות בצפון ובמרכז.'
)
DISCLAIMER_LONG = (
    'הערכת משך זרימה בלבד, בהינתן שתתרחש זרימה. זו אינה אזהרה רשמית ואינה מדידה. '
    'במבחן 2020–2024 (1,943 אירועים; 303 במדבר, 1,640 בצפון/מרכז) השגיאה הממוצעת '
    'הייתה כ-9 שעות בנחלי המדבר (חציון שגיאה כ-5 שעות) וכ-20 שעות בצפון ובמרכז '
    '(חציון שגיאה כ-12 שעות). הטווח המוצג הוא טווח טיפוסי (±השגיאה הממוצעת לפי אזור), לא הבטחה.'
)

_CACHE = {}


def repo_root(explicit=None) -> Path:
    if explicit:
        return Path(explicit)
    env = os.environ.get('FLOOD_ROOT')
    if env:
        return Path(env)
    return Path(__file__).resolve().parent.parent


def _sid_key(v):
    try:
        return str(int(v))
    except (TypeError, ValueError):
        return str(v)


def _num(v, default=np.nan):
    if v is None:
        return default
    try:
        x = float(v)
        return x if math.isfinite(x) else default
    except (TypeError, ValueError):
        return default


def load(root=None):
    root = repo_root(root)
    key = str(root)
    if key in _CACHE:
        return _CACHE[key]
    booster = lgb.Booster(model_file=str(root / 'model' / 'flow_duration_geo_lgbm.txt'))
    feats = json.loads((root / 'model' / 'flow_duration_features.json').read_text())
    geo = pd.read_csv(root / 'data' / 'basin_geology.csv').drop_duplicates('sid')
    geo['sid'] = geo['sid'].map(lambda x: int(x) if pd.notna(x) and str(x).lstrip('-').isdigit() else x)
    geo = geo.set_index('sid')
    statics = {}
    basins_path = root / 'data' / 'basins_simplified.geojson'
    if basins_path.exists():
        B = json.loads(basins_path.read_text())
        for f in B.get('features') or []:
            p = f.get('properties') or {}
            if p.get('sid') is None:
                continue
            statics[_sid_key(p['sid'])] = {c: _num(p.get(c)) for c in STATIC}
            st = statics[_sid_key(p['sid'])]
            if 'area' not in st or not math.isfinite(st.get('area') or 0):
                st['area'] = _num(p.get('area_dem') or p.get('area_rep'))
            st['elev'] = _num(p.get('elev_mean'))
            st['relief'] = _num(p.get('relief'))
            st['lat'] = _num(p.get('olat') or p.get('lat'))
            st['lon'] = _num(p.get('olon') or p.get('lon'))
            st['name_he'] = p.get('name_he') or p.get('main_nahal') or ''
    blob = dict(root=root, booster=booster, feats=feats, geology=geo, statics=statics)
    _CACHE[key] = blob
    return blob


def region_of(desert_flag) -> str:
    v = _num(desert_flag)
    if not math.isfinite(v):
        return 'desert'
    return 'desert' if int(v) == 1 else 'nondesert'


def cat_of(h: float):
    for i, (thr, name) in enumerate(CATS):
        if h < thr:
            return i, name
    return 3, CATS[-1][1]


def interval(h: float, region: str):
    mae = MAE_H['desert' if region == 'desert' else 'nondesert']
    return max(0.0, round(h - mae, 1)), round(h + mae, 1)


def predict(sid, row, *, root=None):
    """Return a site-safe duration record, or None if the prediction is not finite."""
    art = load(root)
    feats, booster, geology, statics = art['feats'], art['booster'], art['geology'], art['statics']
    key = _sid_key(sid)
    try:
        sid_i = int(sid)
    except (TypeError, ValueError):
        sid_i = None
    st = statics.get(key) or {}
    x = {k: row.get(k) for k in feats if k in (row or {})}
    for c in STATIC:
        if _num(x.get(c), default=None) is None:
            x[c] = st.get(c, np.nan)
    if _num(x.get('desert'), default=None) is None:
        x['desert'] = 1 if not st else st.get('desert', 1)
    if sid_i is not None and sid_i in geology.index:
        for c in GEO_COLS:
            val = geology[c].loc[sid_i] if c in geology.columns else np.nan
            x[c] = _num(val)
    else:
        for c in GEO_COLS:
            x.setdefault(c, np.nan)
    area = _num(x.get('area') if x.get('area') is not None else row.get('area', st.get('area')), 0.0)
    x['area'] = area
    x['young_x_area'] = (_num(x.get('f_young_sed'), 0.0) or 0.0) * (area or 0.0)
    df = pd.DataFrame([x])
    for c in feats:
        if c not in df:
            df[c] = np.nan
        df[c] = pd.to_numeric(df[c], errors='coerce')
    h = float(np.expm1(booster.predict(df[feats]))[0])
    if not math.isfinite(h) or h < 0:
        return None
    h = round(h, 1)
    region = region_of(x.get('desert'))
    lo, hi = interval(h, region)
    ci, che = cat_of(h)
    return dict(dur=h, lo=lo, hi=hi, cat=ci, cat_he=che, region=region,
                sid=sid_i if sid_i is not None else sid,
                name_he=st.get('name_he') or row.get('name_he') or '')


def compact_arrays(segments, by_sid, *, region, issued, t0, source=None, extra=None):
    """Same layout as site/data/segment_risk.json: arrays indexed by segment id."""
    n = (max(int(s['id']) for s in segments) + 1) if segments else 0
    dur, lo, hi, cat = [None] * n, [None] * n, [None] * n, [None] * n
    n_fill = 0
    for s in segments:
        rec = by_sid.get(_sid_key(s.get('basin')))
        if rec is None:
            continue
        i = int(s['id'])
        dur[i], lo[i], hi[i], cat[i] = rec['dur'], rec['lo'], rec['hi'], rec['cat']
        n_fill += 1
    mae_key = 'desert' if region == 'desert' else 'nondesert'
    out = dict(
        v=1, kind='flow_duration', region=region, issued=issued, t0=t0,
        source=source, unit='hours', min_risk=MIN_P,
        model='flow_duration_geo_lgbm',
        n_segments=len(segments), n_array=n, n_with_duration=n_fill,
        mae_h=MAE_H[mae_key], medae_h=MEDAE_H[mae_key],
        disclaimer_he=DISCLAIMER_SHORT,
        cat_labels=[name for _, name in CATS],
        inherit='basin_outlet',
    )
    if extra:
        out.update(extra)
    out.update(dur=dur, lo=lo, hi=hi, cat=cat)
    return out


def _clean(o):
    if isinstance(o, float):
        return o if math.isfinite(o) else None
    if isinstance(o, dict):
        return {k: _clean(v) for k, v in o.items()}
    if isinstance(o, (list, tuple)):
        return [_clean(v) for v in o]
    if hasattr(o, 'item') and not isinstance(o, (str, bytes)):
        try:
            return _clean(o.item())
        except Exception:
            return o
    return o


def jsave(path, obj):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + '.tmp')
    tmp.write_text(json.dumps(_clean(obj), ensure_ascii=False, separators=(',', ':')), encoding='utf-8')
    tmp.replace(path)


def _load_segments(root, name):
    import gzip
    p = Path(root) / 'data' / name
    with gzip.open(p, 'rt') as f:
        blob = json.load(f)
    return blob.get('segments') or [], p


def desert_from_live_risk(fe, g, now, fc, hours=48, root=None):
    """Duration for desert basins with risk >= MIN_P, using the engine's feature row."""
    by = {}
    if not fc:
        return by
    T1 = now + pd.Timedelta(hours=hours)
    for f in fc.get('features') or []:
        p = f.get('properties') or {}
        sid = p.get('sid')
        risk = p.get('risk')
        if sid is None or risk is None or risk < MIN_P:
            continue
        z = fe.CAT['basins'].get(str(sid))
        if z is None:
            continue
        try:
            pr, T, row = fe.model_prob(g, z, p.get('olat'), p.get('olon'), now, T1, sid=sid)
        except Exception:
            continue
        if not row:
            continue
        row = dict(row)
        row['name_he'] = p.get('name_he') or p.get('main_nahal') or ''
        if row.get('desert') is None:
            row['desert'] = 1 if p.get('desert') is None else p.get('desert')
        rec = predict(sid, row, root=root)
        if rec is None:
            continue
        rec['risk'] = round(float(risk), 3)
        rec['name_he'] = rec.get('name_he') or row['name_he']
        by[_sid_key(sid)] = rec
    return by


def _nondesert_rows(fe, g, now, info, root=None):
    """POWER-style event features for nondesert basins already scored at p >= MIN_P."""
    import nondesert as nd
    by = {}
    if not info:
        return by
    cat, static, _segs, _fb, _sb = nd._load()
    # evaluate at `now` (same instant the nondesert model used for the event)
    try:
        k_now = int(g.t.get_loc(now))
    except KeyError:
        k_now = int(g.t.searchsorted(now, 'right') - 1)
        k_now = max(0, min(k_now, len(g.t) - 1))
    doy = pd.Timestamp(now).dayofyear
    doy_s, doy_c = float(np.sin(2 * np.pi * doy / 365)), float(np.cos(2 * np.pi * doy / 365))
    for sid, b in (info.get('basins') or {}).items():
        p = b.get('p')
        if p is None or p < MIN_P:
            continue
        basin = cat['basins'].get(str(sid))
        if basin is None:
            continue
        series = nd._weighted_series(g, basin['mask'])
        ev = fe.event_feats(series, [k_now])[0]
        st = nd._static_row(sid, basin, static)
        row = dict(zip(fe.POW, ev))
        row.update(st)
        row['desert'] = 0
        row['doy_s'], row['doy_c'] = doy_s, doy_c
        rec = predict(sid, row, root=root)
        if rec is None:
            continue
        rec['risk'] = round(float(p), 3)
        rec['name_he'] = rec.get('name_he') or b.get('name') or ''
        rec['region'] = 'nondesert'
        by[_sid_key(sid)] = rec
    return by


def write_from_job(fe, g, now, desert_fc, nd_info, site_dir, *, hours=48, root=None, source=None):
    """Called from run_job.py. Writes duration files next to segment_risk*.json.

    Never raises: the caller should still wrap this in try/except so a duration
    failure cannot change risk outputs.
    """
    root = repo_root(root)
    issued = fe.il(now)
    t0 = int(pd.Timestamp(now).tz_localize('UTC').timestamp()) if pd.Timestamp(now).tzinfo is None else int(pd.Timestamp(now).timestamp())
    source = source or getattr(g, 'name', None)
    desert_by = desert_from_live_risk(fe, g, now, desert_fc, hours=hours, root=root)
    nd_by = _nondesert_rows(fe, g, now, nd_info, root=root)
    d_segs, d_path = _load_segments(root, 'channel_segments.json.gz')
    n_segs, n_path = _load_segments(root, 'channel_segments_nondesert.json.gz')
    d_compact = compact_arrays(
        d_segs, desert_by, region='desert', issued=issued, t0=t0, source=source,
        extra={'n_basins': len(desert_by), 'geom_version': 'v8p'},
    )
    n_compact = compact_arrays(
        n_segs, nd_by, region='north_center', issued=issued, t0=t0, source=source,
        extra={'n_basins': len(nd_by), 'geom_version': 'v3e', 'region_flag': 'nondesert',
               'mae_h': MAE_H['nondesert'], 'medae_h': MEDAE_H['nondesert']},
    )
    site = Path(site_dir)
    jsave(site / 'segment_duration.json', d_compact)
    jsave(site / 'segment_duration_nondesert.json', n_compact)
    print(
        f'flow duration: desert {len(desert_by)} basins / {d_compact["n_with_duration"]} segments; '
        f'nondesert {len(nd_by)} basins / {n_compact["n_with_duration"]} segments'
    )
    return dict(desert=d_compact, nondesert=n_compact, desert_by=desert_by, nd_by=nd_by)
