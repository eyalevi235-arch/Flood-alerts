"""Merge observed IMS-radar hourly rain (radar_rain_grid.json[.gz], produced by tools/publish_radar_rain_grid.py) into the
Open-Meteo hourly grid used by flood_engine_v2. Any problem -> returns the forecast grid unchanged with a reason (fallback).
Rules: file must parse and match the grid; latest frame age <= RADAR_MAX_AGE_MIN (default 90); only hours with frame
coverage >= RADAR_COV_MIN (0.8) and only cells flagged valid (<=RMAX km from radar, low artefact) are replaced.
Open-Meteo convention: value at hour t = rain in (t-1h, t]; the file uses the same hour-end labels (UTC)."""
import os,json,gzip,io,numpy as np,pandas as pd
MAX_AGE_MIN=float(os.environ.get('RADAR_MAX_AGE_MIN',90)); COV_MIN=float(os.environ.get('RADAR_COV_MIN',0.8))
def _now(): v=os.environ.get('RADAR_NOW'); return pd.Timestamp(v) if v else pd.Timestamp.utcnow().tz_localize(None)
def _load(src):
    if src.startswith('http'):
        import requests; r=requests.get(src,timeout=20); r.raise_for_status(); b=r.content
    else: b=open(src,'rb').read()
    if b[:2]==b'\x1f\x8b': b=gzip.decompress(b)
    return json.loads(b)
def merge(t,R,LAT,LON,src=None):
    src=src or os.environ.get('RADAR_FEATURES',os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))),'data','radar_rain_grid.json.gz'))
    try: J=_load(src)
    except FileNotFoundError: return R,dict(used=False,reason='radar file missing',src=src)
    except Exception as e: return R,dict(used=False,reason=f'radar file unreadable: {type(e).__name__}',src=src)
    try:
        if not (np.allclose(J['grid']['lat'],LAT) and np.allclose(J['grid']['lon'],LON)): return R,dict(used=False,reason='grid mismatch')
        latest=pd.Timestamp(J['latest_frame_utc']); age=(_now()-latest).total_seconds()/60
        if not np.isfinite(age) or age>MAX_AGE_MIN or age< -15: return R,dict(used=False,reason=f'stale radar (age {age:.0f} min)',latest=str(latest))
        hrs=pd.DatetimeIndex(J['hours_utc']); cov=np.asarray(J['coverage'],float); V=np.asarray(J['valid'],int); M=np.asarray(J['mm'],float)
        if V.ndim!=2 or M.shape!=(len(hrs),len(V)): return R,dict(used=False,reason='bad shapes')
        R=R.copy(); used=[]
        for i,h in enumerate(hrs):
            if cov[i]<COV_MIN or h>latest: continue
            k=t.get_indexer([h])[0]
            if k<0: continue
            v=M[i]; ok=np.isfinite(v)&(v>=0)&(v<300); R[k,V[ok,0],V[ok,1]]=v[ok]; used.append(str(h))
        if not used: return R,dict(used=False,reason='no radar hour passed coverage/time checks')
        return R,dict(used=True,reason='ok',hours=len(used),first=used[0],last=used[-1],cells=int(len(V)),age_min=round(age,1),latest=str(latest))
    except Exception as e: return R,dict(used=False,reason=f'radar merge error: {type(e).__name__}: {e}')
