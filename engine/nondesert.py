"""North/center and perennial streams. Separate from the desert engine.

Scores catchments_nondesert.json with model/nondesert_flow.txt (and the
significant-flood booster). Desert files and desert scoring are not used here.
"""
import gzip, json, os
import numpy as np
import pandas as pd
import lightgbm as lgb

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
METRICS = json.load(open(f'{ROOT}/model/nondesert_metrics.json'))
FEATS = METRICS['features']
FLOW = METRICS['results']['nondesert_flow']
SIG = METRICS['results']['nondesert_sig']
FLOW_THR = float(FLOW['thr'])
SIG_THR = float(SIG['thr'])
DRY_MM = 3.0
WET = 0.1
BY_ID = {}


def _load():
    cat = json.load(open(f'{ROOT}/data/catchments_nondesert.json'))
    static = json.load(open(f'{ROOT}/data/nondesert_basin_features.json'))
    with gzip.open(f'{ROOT}/data/channel_segments_nondesert.json.gz', 'rt') as f:
        segs = json.load(f)
    flow = lgb.Booster(model_file=f'{ROOT}/model/nondesert_flow.txt')
    sig = lgb.Booster(model_file=f'{ROOT}/model/nondesert_sig.txt')
    return cat, static, segs, flow, sig


def _platt(p, a, b):
    p = np.clip(np.asarray(p, dtype=float), 1e-4, 1 - 1e-4)
    logit = np.log(p / (1 - p))
    return 1 / (1 + np.exp(-(a * logit + b)))


def _roll_max(x, w):
    x = np.asarray(x, dtype=float)
    if len(x) == 0:
        return 0.0
    if len(x) <= w:
        return float(x.sum())
    c = np.cumsum(x)
    prev = np.concatenate([[0.0], c[:-w]])
    return float((c[w - 1:] - prev).max())


def _weighted_series(g, mask):
    r = np.array(mask['r'], dtype=int)
    c = np.array(mask['c'], dtype=int)
    w = np.array(mask['w'], dtype=float)
    w = w / max(float(w.sum()), 1e-12)
    hourly = np.diff(g.cs, axis=0)
    return (hourly[:, r, c] * w).sum(1)


def event_features(series, times, now):
    """Next rain event in the forecast, plus antecedent rain before it starts."""
    times = pd.DatetimeIndex(times)
    series = np.asarray(series, dtype=float)
    wet = series >= WET
    horizon = np.where((times >= now) & (times <= now + pd.Timedelta(hours=72)))[0]
    max24 = _roll_max(series[horizon], 24) if len(horizon) else 0.0
    wet_h = [int(i) for i in horizon if wet[i]]
    if wet_h:
        start = wet_h[0]
        while start > 0:
            j = start - 1
            while j >= 0 and not wet[j]:
                j -= 1
            if j >= 0 and (start - j) <= 24:
                start = j
            else:
                break
        end = start
        dry = 0
        for k in range(start, len(series)):
            if wet[k]:
                dry = 0
                end = k
            else:
                dry += 1
                if dry >= 24:
                    break
        sl = series[start:end + 1]
    else:
        start = int(horizon[0]) if len(horizon) else 0
        sl = np.zeros(0)
    def ante(hours):
        a = max(0, start - hours)
        return float(series[a:start].sum())
    peak_off = int(np.argmax(sl)) if len(sl) else 0
    peak_i = start + peak_off
    return dict(
        dur_h=float(len(sl)),
        total=float(sl.sum()) if len(sl) else 0.0,
        max1=float(sl.max()) if len(sl) else 0.0,
        max3=_roll_max(sl, 3),
        max6=_roll_max(sl, 6),
        max12=_roll_max(sl, 12),
        max24=_roll_max(sl, 24),
        ante3=ante(72),
        ante7=ante(168),
        ante30=ante(720),
        forecast_max24=max24,
        peak_time=times[min(peak_i, len(times) - 1)],
    )


def _static_row(sid, basin, static):
    st = static.get(str(sid), {})
    def num(key, default=0.0):
        v = st.get(key, default)
        if v is None or (isinstance(v, float) and not np.isfinite(v)):
            return -1.0 if key == 'summer_flow_frac' else default
        return float(v)
    per = st.get('perennial', basin.get('perennial'))
    return dict(
        area=num('area_dem', basin.get('area_km2') or 0),
        elev=num('elev_mean', basin.get('elev') or 0),
        relief=num('relief', basin.get('relief') or 0),
        lat=num('olat', 0),
        lon=num('olon', 0),
        perennial=1.0 if per in (1, 1.0, True, '1') else 0.0,
        cn_mean=num('cn_mean'),
        f_built=num('f_built'),
        f_crop=num('f_crop'),
        f_veg=num('f_veg'),
        f_rock=num('f_rock'),
        f_hsgAB=num('f_hsgAB'),
        f_hsgD=num('f_hsgD'),
        clay_mean=num('clay_mean'),
        sand_mean=num('sand_mean'),
        summer_flow_frac=num('summer_flow_frac', -1.0),
    )


def score_basins(g, now):
    cat, static, segs, flow_b, sig_b = _load()
    rows = []
    meta = []
    for sid, basin in cat['basins'].items():
        series = _weighted_series(g, basin['mask'])
        ev = event_features(series, g.t, now)
        st = _static_row(sid, basin, static)
        doy = ev['peak_time'].dayofyear
        row = dict(ev)
        row.update(st)
        row['doy_s'] = float(np.sin(2 * np.pi * doy / 365))
        row['doy_c'] = float(np.cos(2 * np.pi * doy / 365))
        rows.append(row)
        meta.append((sid, basin, ev, st))
    X = np.array([[float(r.get(f, -1.0 if f == 'summer_flow_frac' else 0.0)) for f in FEATS] for r in rows], dtype=float)
    raw_f = flow_b.predict(X)
    raw_s = sig_b.predict(X)
    cal_f = _platt(raw_f, FLOW['platt_a'], FLOW['platt_b'])
    cal_s = _platt(raw_s, SIG['platt_a'], SIG['platt_b'])
    out = {}
    for i, (sid, basin, ev, st) in enumerate(meta):
        dry = ev['forecast_max24'] < DRY_MM
        pf = 0.0 if dry else float(cal_f[i])
        ps = 0.0 if dry else float(cal_s[i])
        alert = (not dry) and float(raw_f[i]) >= FLOW_THR
        strong = (not dry) and float(raw_s[i]) >= SIG_THR
        out[str(sid)] = dict(
            sid=str(sid), name=basin.get('name') or sid, station=basin.get('name_station') or '',
            perennial=bool(st['perennial']), region='north_center',
            lat=st['lat'], lon=st['lon'], area=float(basin.get('area_km2') or st['area']),
            p=round(pf, 3), p_raw=round(float(raw_f[i]), 3), p_sig=round(ps, 3),
            alert=alert, strong=strong, rain=round(ev['total'], 1),
            max24=round(ev['forecast_max24'], 1), peak=ev['peak_time'], dry=dry,
        )
    return out, segs['segments']


def score_all(g, now):
    """Basin scores, then each segment inherits its basin and keeps its own travel time."""
    global BY_ID
    import flood_engine as fe
    basins, segments = score_basins(g, now)
    T1 = now + pd.Timedelta(hours=72)
    recs = []
    by = {}
    for s in segments:
        b = basins.get(str(s.get('basin')))
        area_b = float(b['area']) if b else 1.0
        scale = min(1.0, float(s.get('area_km2') or 0) / max(area_b, 1e-6)) ** 0.3
        p = 0.0 if not b else round(min(1.0, b['p'] * scale), 3)
        routed = fe.route_segment(g, s, now - pd.Timedelta(hours=24), T1)
        eta = routed['first'] if routed else None
        if eta is None and b and p >= 0.05 and b.get('peak') is not None:
            eta = b['peak'] + pd.Timedelta(seconds=float(s.get('tt_p10_s') or 0))
        if p < 0.05:
            eta = None
        lead = None
        if eta is not None:
            lead = (eta - now).total_seconds() / 3600.0
            if lead < 0:
                lead = 0.0
        rec = dict(
            id=int(s['id']), prob=p, rain=b['rain'] if b else 0.0, eta=eta,
            lead=None if lead is None else round(float(lead), 1),
            tt_p10_s=int(s.get('tt_p10_s') or 0), tt_med_s=int(s.get('tt_med_s') or 0),
            area=round(float(s.get('area_km2') or 0), 2),
            name=s.get('name') or (b['name'] if b else ''),
            perennial=bool(s.get('perennial')), strong=bool(b and b['strong'] and p >= 0.05),
            region='north_center', basin=str(s.get('basin') or ''),
            nahal=s.get('name') or (b['name'] if b else ''),
        )
        recs.append(rec)
        by[rec['id']] = rec
    BY_ID = by
    n_alert = sum(1 for b in basins.values() if b['alert'])
    return dict(basins=basins, segments=recs, n_basins=len(basins), n_segs=len(recs), n_alert=n_alert)


def write_outputs(info, issued, now):
    feats = []
    for b in info['basins'].values():
        if not (np.isfinite(b['lat']) and np.isfinite(b['lon'])):
            continue
        feats.append(dict(
            type='Feature',
            geometry=dict(type='Point', coordinates=[round(b['lon'], 5), round(b['lat'], 5)]),
            properties=dict(
                sid=b['sid'], name=b['name'], name_station=b['station'], region='north_center',
                perennial=b['perennial'], risk=b['p'], risk_raw=b['p_raw'], p_sig=b['p_sig'],
                alert=b['alert'], strong=b['strong'], event_rain_mm=b['rain'], max24_mm=b['max24'],
            ),
        ))
    geo = dict(type='FeatureCollection', issued=issued, hours=48, region='north_center', features=feats)
    segs = info['segments']
    compact = dict(
        v=1, region='north_center', issued=issued,
        p=[s['prob'] for s in segs],
        rain=[s['rain'] for s in segs],
        lead=[s['lead'] if s['lead'] is not None else None for s in segs],
        em=[int(round((s['eta'] - now).total_seconds() / 60)) if s['eta'] is not None else -1 for s in segs],
        strong=[1 if s['strong'] else 0 for s in segs],
        tp=[int(round(s['tt_p10_s'] / 60)) for s in segs],
        tm=[int(round(s['tt_med_s'] / 60)) for s in segs],
    )
    return geo, compact


def lookup(seg_id):
    try:
        return BY_ID.get(int(seg_id))
    except (TypeError, ValueError):
        return None
