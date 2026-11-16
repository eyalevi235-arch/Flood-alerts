"""radar-live consumer (hourly Action). Validates radar_live/latest.json pushed by the VM radar engine
(branch radar-live) and decides the site's data source. No network and no Open-Meteo here: the file is
fetched by the workflow with git (.radar_live/latest.json). Same rules as site/data_source.js.

Mode (env RADAR_LIVE_MODE): off (default) = nothing changes; shadow = validate + log only;
on = site reads radar-live in the browser, falls back to the Open-Meteo forecast with a banner.
The file carries probabilities, arrival/lead times and ids only; any rain/mm key fails validation."""
import json, math, os, re
import datetime as dt

SCHEMA = 1
MODES = ('off', 'shadow', 'on')
# Defaults for the 30-min VM cadence (cron 13,43): one missed push is tolerated.
MAX_ISSUE_AGE_MIN = 40
MAX_FRAME_AGE_MIN = 60
MAX_FORECAST_AGE_H = 12
# Segment ids are sparse, so the forecast files carry nulls too (16.11: 1024 desert, 42 north/centre).
EXPECT = dict(desert_seg=10821, nondesert_seg=3432, desert_basins=569, nondesert_basins=216,
              desert_geom='v8p', nd_geom='v3e', desert_seg_max_null=1300, nondesert_seg_max_null=200)
ALLOW = {
    'root': {'schema', 'issued_utc', 'engine_sha', 'engine', 'source', 'radar_latest_frame_utc', 'radar_hours_used',
             'bias', 'thr', 'desert_seg', 'nondesert_seg', 'desert_basins', 'nondesert_basins', 'alerts',
             'desert_geom', 'nd_geom', 'forecast_age_h', 'engine_issued_utc'},
    'bias': {'desert', 'north', 'switch'}, 'thr': {'desert', 'north_center'},
    'desert_seg': {'v', 't0', 'issued', 'p', 'lead', 'em', 'tp', 'tm'},
    'nondesert_seg': {'v', 'region', 't0', 'issued', 'p', 'lead', 'em', 'tp', 'tm', 'strong'},
    'desert_basins': {'sid', 'risk', 'rcov'}, 'nondesert_basins': {'sid', 'risk', 'alert', 'strong', 'rcov'},
    'alert': {'point', 'name', 'nahal', 'region', 'prob', 'eta_first_wave', 'eta_peak', 'hours_until_first_wave',
              'confidence', 'estimate', 'source', 'issued'},
}
REQUIRED = ('schema', 'issued_utc', 'source', 'radar_latest_frame_utc', 'radar_hours_used', 'desert_seg',
            'nondesert_seg', 'desert_basins', 'nondesert_basins', 'alerts', 'desert_geom', 'nd_geom')
FORBID = re.compile(r'rain|_mm|mm_|^mm$|max24|r24|gauge|station|dbz|precip', re.I)
MM_TEXT = re.compile(r'מ"מ|מ״מ|\bmm\b')


def mode():
    m = (os.environ.get('RADAR_LIVE_MODE') or 'off').strip().lower()
    return m if m in MODES else 'off'


def _f(name, default):
    try:
        v = float(os.environ.get(name, ''))
        return v if math.isfinite(v) and v > 0 else default
    except ValueError:
        return default


def limits():
    return dict(max_issue_age_min=_f('RADAR_LIVE_MAX_ISSUE_AGE_MIN', MAX_ISSUE_AGE_MIN),
                max_frame_age_min=_f('RADAR_LIVE_MAX_FRAME_AGE_MIN', MAX_FRAME_AGE_MIN),
                max_forecast_age_h=_f('RADAR_LIVE_MAX_FORECAST_AGE_H', MAX_FORECAST_AGE_H))


def parse_utc(s):
    """'2026-11-16T09:14Z' / '2026-11-16 08:55:00' / ISO with offset -> aware UTC datetime, else None."""
    if not isinstance(s, str) or not s.strip():
        return None
    t = s.strip().replace(' ', 'T')
    if t.endswith('Z'):
        t = t[:-1] + '+00:00'
    try:
        d = dt.datetime.fromisoformat(t)
    except ValueError:
        return None
    if d.tzinfo is None:
        d = d.replace(tzinfo=dt.timezone.utc)
    return d.astimezone(dt.timezone.utc)


def _keys(o, allowed, path, err):
    if not isinstance(o, dict):
        err.append(f'{path} not an object'); return
    for k in o:
        if k not in allowed:
            err.append(f'{path}.{k} not allowed')
        if FORBID.search(k):
            err.append(f'{path}.{k} forbidden')


def _probs(a, name, err, allow_null=True):
    if not isinstance(a, list):
        err.append(f'{name} not a list'); return 0
    nn = 0
    for x in a:
        if x is None:
            nn += 1
            if not allow_null:
                err.append(f'{name} null'); return nn
            continue
        if isinstance(x, bool) or not isinstance(x, (int, float)) or not math.isfinite(x) or x < 0 or x > 1:
            err.append(f'{name} out of range'); return nn
    return nn


def allowlist_errors(J):
    """Key allowlist + forbidden tokens (no rain/mm/radar values). Mirrors the VM sanitize.check."""
    err = []
    if not isinstance(J, dict):
        return ['root not an object']
    _keys(J, ALLOW['root'], 'root', err)
    for s in ('bias', 'thr', 'desert_seg', 'nondesert_seg', 'desert_basins', 'nondesert_basins'):
        if s in J:
            _keys(J[s], ALLOW[s], s, err)
    for a in J.get('alerts') or []:
        _keys(a, ALLOW['alert'], 'alert', err)
        if isinstance(a, dict):
            for v in a.values():
                if isinstance(v, str) and MM_TEXT.search(v):
                    err.append('alert text has mm')
    return err


def validate(J, now=None, expect=None, lim=None):
    """-> (ok, reason, detail). reason in: ok, schema, vm_forecast, stale, geometry, values."""
    now = now or dt.datetime.now(dt.timezone.utc)
    expect = expect or EXPECT
    lim = lim or limits()
    if not isinstance(J, dict):
        return False, 'schema', 'not an object'
    miss = [k for k in REQUIRED if k not in J]
    if miss or J.get('schema') != SCHEMA:
        return False, 'schema', f'missing {miss[:4]}' if miss else f'schema {J.get("schema")!r}'
    al = allowlist_errors(J)
    if al:
        return False, 'schema', '; '.join(al[:4])
    if J.get('source') != 'radar':
        return False, 'vm_forecast', f'source {J.get("source")!r}'
    try:
        if int(J.get('radar_hours_used') or 0) < 1:
            return False, 'vm_forecast', 'no radar hours'
    except (TypeError, ValueError):
        return False, 'schema', 'radar_hours_used'
    iss = parse_utc(J.get('issued_utc')); fr = parse_utc(J.get('radar_latest_frame_utc'))
    if iss is None or fr is None:
        return False, 'schema', 'bad timestamps'
    ia = (now - iss).total_seconds() / 60; fa = (now - fr).total_seconds() / 60
    if ia < -10 or fa < -10:
        return False, 'stale', f'future timestamp (issued {ia:.0f} min, frame {fa:.0f} min)'
    if ia > lim['max_issue_age_min'] or fa > lim['max_frame_age_min']:
        return False, 'stale', f'issued {ia:.0f} min, frame {fa:.0f} min'
    fh = J.get('forecast_age_h')
    if isinstance(fh, (int, float)) and not isinstance(fh, bool) and fh > lim['max_forecast_age_h']:
        return False, 'stale', f'forecast part {fh:.1f} h old'
    if J.get('desert_geom') != expect['desert_geom'] or J.get('nd_geom') != expect['nd_geom']:
        return False, 'geometry', f'geom {J.get("desert_geom")}/{J.get("nd_geom")}'
    ds, ns, db, nb = J['desert_seg'], J['nondesert_seg'], J['desert_basins'], J['nondesert_basins']
    try:
        lens = dict(desert_seg=len(ds['p']), nondesert_seg=len(ns['p']), desert_basins=len(db['sid']),
                    nondesert_basins=len(nb['sid']))
    except (TypeError, KeyError):
        return False, 'schema', 'arrays missing'
    for k, n in lens.items():
        if n != expect[k]:
            return False, 'geometry', f'{k} {n} != {expect[k]}'
    for o, keys in ((ds, ('lead', 'em', 'tp', 'tm')), (ns, ('lead', 'em', 'tp', 'tm'))):
        for k in keys:
            if k in o and (not isinstance(o[k], list) or len(o[k]) != len(o['p'])):
                return False, 'geometry', f'{k} length'
    if len(db.get('risk') or []) != lens['desert_basins'] or len(nb.get('risk') or []) != lens['nondesert_basins']:
        return False, 'geometry', 'basin risk length'
    err = []
    nd = _probs(ds['p'], 'desert_seg.p', err); nn = _probs(ns['p'], 'nondesert_seg.p', err)
    _probs(db['risk'], 'desert_basins.risk', err); _probs(nb['risk'], 'nondesert_basins.risk', err)
    for a in J['alerts']:
        if not isinstance(a, dict) or not isinstance(a.get('point'), str):
            err.append('alert shape'); break
        p = a.get('prob')
        if p is not None and (isinstance(p, bool) or not isinstance(p, (int, float)) or not math.isfinite(p) or p < 0 or p > 1):
            err.append('alert prob'); break
    if err:
        return False, 'values', err[0]
    if nd > expect.get('desert_seg_max_null', 1300) or nn > expect.get('nondesert_seg_max_null', 200):
        return False, 'values', f'too many nulls ({nd}/{nn})'
    return True, 'ok', dict(issue_age_min=round(ia, 1), frame_age_min=round(fa, 1))


def load(path):
    try:
        with open(path, encoding='utf-8') as f:
            return json.load(f, parse_constant=lambda c: (_ for _ in ()).throw(ValueError(c))), None
    except FileNotFoundError:
        return None, 'missing'
    except (OSError, ValueError) as e:
        return None, f'unreadable {type(e).__name__}'


def evaluate(path, now=None, expect=None):
    """-> status dict for logs / site/data/source_status.json (no probabilities, no rain)."""
    now = now or dt.datetime.now(dt.timezone.utc)
    J, e = load(path)
    st = dict(mode=mode(), checked_utc=now.strftime('%Y-%m-%dT%H:%MZ'))
    if J is None:
        st.update(server_choice='forecast', reason='missing', detail=e)
        return st, None
    ok, reason, detail = validate(J, now=now, expect=expect)
    st.update(server_choice='radar' if ok else 'forecast', reason=reason,
              detail=detail if isinstance(detail, str) else None,
              radar_issued_utc=J.get('issued_utc') if isinstance(J, dict) else None,
              radar_frame_utc=J.get('radar_latest_frame_utc') if isinstance(J, dict) else None)
    if ok:
        st.update(detail)
    return st, (J if ok else None)


def site_config(expect=None):
    """config.json block that switches the browser path on (mode=on only)."""
    lim = limits()
    return dict(mode='on',
                url=os.environ.get('RADAR_LIVE_URL') or
                'https://raw.githubusercontent.com/eyalevi235-arch/Flood-alerts/radar-live/radar_live/latest.json',
                fallback_url='data/radar_live.json', refresh_min=30,
                max_issue_age_min=lim['max_issue_age_min'], max_frame_age_min=lim['max_frame_age_min'],
                max_forecast_age_h=lim['max_forecast_age_h'], expect=dict(expect or EXPECT),
                radar_push_thr=None)
