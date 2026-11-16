"""Open-Meteo HTTP client for the hourly Actions job (and the v1/v2 engines).

Retries 429/5xx/timeouts with bounded total wait (OM_RETRY_BUDGET_S, default 480).
Respects Retry-After. Does not retry a daily-quota 429 (or Retry-After >= 15 min).
Optional disk cache (OM_CACHE_DIR): reuse a fresh grid, stitch a short recent+forecast
fetch onto a once-a-day long antecedent history (ante30 still needs ~31 past days),
and fall back to a stale grid when the API is unavailable.
Does not change calibration, thresholds, or model math.
"""
import json, os, time
import numpy as np
import pandas as pd
import requests

API='https://api.open-meteo.com/v1/forecast'
STATS={'hit':0,'miss':0,'memo':0,'stale':0,'http_ok':0,'http_429':0,'http_daily':0,
       'http_5xx':0,'http_timeout':0,'http_err':0,'src':None}
_MEMO={}

class DailyLimitExceeded(requests.HTTPError):
    """Free daily Open-Meteo quota exhausted; do not retry or try another model."""

def reset():
    STATS.update(hit=0,miss=0,memo=0,stale=0,http_ok=0,http_429=0,http_daily=0,
                 http_5xx=0,http_timeout=0,http_err=0,src=None)
    _MEMO.clear()

def stats_line():
    return 'OM_CACHE '+json.dumps({k:v for k,v in STATS.items() if v}, default=str)

def _budget():
    return int(os.environ.get('OM_RETRY_BUDGET_S','480'))

def _retry_after(resp, default):
    ra=(resp.headers.get('Retry-After') if resp is not None else None) or ''
    try: return int(float(ra))
    except ValueError: pass
    try:
        from email.utils import parsedate_to_datetime
        return max(0,int(parsedate_to_datetime(ra).timestamp()-time.time()))
    except Exception:
        return default

def _is_daily(resp, wait):
    if resp is None or getattr(resp,'status_code',None)!=429: return False
    b=(getattr(resp,'text',None) or '').lower()
    if 'daily' in b and any(w in b for w in ('limit','exceeded','quota')): return True
    return wait is not None and wait>=900

def get(url, params, tries=4, timeout=60):
    """GET JSON with bounded retries. tries caps attempts; OM_RETRY_BUDGET_S caps wait."""
    t_end=time.time()+_budget(); last=None; n=max(int(tries),1)
    for k in range(n):
        wait=min(30*(2**k),120)
        try:
            r=requests.get(url,params=params,timeout=timeout); last=r
            if r.status_code==200:
                STATS['http_ok']+=1; return r.json()
            wait=_retry_after(r, wait)
            if r.status_code==429:
                STATS['http_429']+=1
                if _is_daily(r, wait):
                    STATS['http_daily']+=1
                    err=DailyLimitExceeded(f'429 daily limit: {url}', response=r)
                    raise err
            elif r.status_code>=500:
                STATS['http_5xx']+=1
            else:
                r.raise_for_status()
        except DailyLimitExceeded:
            raise
        except requests.Timeout as e:
            last=e; STATS['http_timeout']+=1; wait=min(15*(k+1),60)
        except requests.RequestException as e:
            last=e; STATS['http_err']+=1; wait=min(15*(k+1),60)
        left=t_end-time.time()
        if k>=n-1 or left<=1: break
        time.sleep(max(1,min(wait,left-1,120)))
    if hasattr(last,'raise_for_status'): last.raise_for_status()
    if isinstance(last,Exception): raise last
    raise RuntimeError('Open-Meteo request failed')

def _cache_dir():
    d=os.environ.get('OM_CACHE_DIR','').strip()
    return d or None

def _cache_path(model,nlat,nlon):
    d=_cache_dir()
    if not d: return None
    os.makedirs(d,exist_ok=True)
    safe=''.join(c if c.isalnum() or c in '-_.' else '_' for c in model)
    return os.path.join(d,f'grid_{safe}_{nlat}x{nlon}.npz')

def load_grid(model,nlat,nlon):
    p=_cache_path(model,nlat,nlon)
    if not p or not os.path.exists(p): return None
    try:
        with np.load(p,allow_pickle=False) as z:
            t=pd.to_datetime(np.asarray(z['t'],dtype='int64'),unit='ns')
            R=np.asarray(z['R'],dtype='float32')
            ts=float(np.asarray(z['ts']).reshape(-1)[0])
        if R.shape[1:]!=(nlat,nlon) or len(t)!=len(R): return None
        return dict(t=pd.DatetimeIndex(t),R=R,ts=ts)
    except Exception:
        return None

def save_grid(model,nlat,nlon,t,R):
    p=_cache_path(model,nlat,nlon)
    if not p: return
    tmp=p+'.tmp.npz'
    try:
        t_ns=np.asarray(pd.DatetimeIndex(t).astype('datetime64[ns]'),dtype='datetime64[ns]').astype('int64')
        np.savez_compressed(tmp,t=t_ns,R=np.asarray(R,dtype='float32'),ts=np.array([time.time()],dtype='float64'))
        os.replace(tmp,p)
    except Exception:
        try: os.remove(tmp)
        except OSError: pass

def stitch(hist_t, hist_R, new_t, new_R):
    """Keep history only before the first new timestamp; new values win on overlap."""
    hist_t=pd.DatetimeIndex(hist_t); new_t=pd.DatetimeIndex(new_t)
    if not len(new_t): return hist_t, hist_R
    cut=new_t[0]; mask=hist_t<cut
    t=hist_t[mask].append(new_t)
    R=np.concatenate([np.asarray(hist_R)[mask], np.asarray(new_R)],axis=0)
    return pd.DatetimeIndex(t), np.asarray(R,dtype='float32')

def covers(t, past_days, now=None, forecast_hours=1):
    """True if the series starts early enough for ante30 and reaches 'now'."""
    t=pd.DatetimeIndex(t)
    if not len(t): return False
    now=pd.Timestamp(now) if now is not None else pd.Timestamp.now('UTC').tz_localize(None)
    if t.tz is not None: now=now.tz_localize(t.tz) if now.tzinfo is None else now.tz_convert(t.tz)
    start_ok=t[0]<=now-pd.Timedelta(days=int(past_days)-0.05)
    end_ok=t[-1]>=now-pd.Timedelta(hours=forecast_hours)
    return bool(start_ok and end_ok)

def http_grid(get, la, lo, nlat, nlon, model, days, past_days, chunk=150):
    out=[]; t=None
    for i in range(0,len(la),chunk):
        p=dict(latitude=','.join(map(str,la[i:i+chunk])),longitude=','.join(map(str,lo[i:i+chunk])),
               hourly='precipitation',models=model,timezone='GMT',forecast_days=int(days),past_days=int(past_days))
        if i: time.sleep(float(os.environ.get('OM_CHUNK_SLEEP_S','0.5') or 0))
        j=get(API,p); j=j if isinstance(j,list) else [j]
        out+=[np.array([np.nan if v is None else v for v in x['hourly']['precipitation']],dtype='float32') for x in j]
        t=pd.to_datetime(j[0]['hourly']['time'])
    R=np.stack(out,1).reshape(len(t),nlat,nlon); R[~np.isfinite(R)]=0
    return pd.DatetimeIndex(t), R

def precip_grid(get, la, lo, nlat, nlon, model, days, past_days, chunk=150, now=None):
    """Return (times, R, src). Memoizes identical calls. Uses OM_CACHE_DIR when set."""
    mk=json.dumps([model,int(days),int(past_days),nlat,nlon,len(la)],default=str)
    if mk in _MEMO:
        STATS['memo']+=1; return _MEMO[mk]
    fresh=float(os.environ.get('OM_CACHE_FRESH_H','1.5'))*3600
    stale=float(os.environ.get('OM_CACHE_STALE_H','6'))*3600
    hist_max=float(os.environ.get('OM_HISTORY_H','24'))*3600
    short_past=int(os.environ.get('OM_SHORT_PAST_DAYS','2'))
    cached=load_grid(model,nlat,nlon)
    age=(time.time()-cached['ts']) if cached else None
    clock=pd.Timestamp(now) if now is not None else pd.Timestamp.now('UTC').tz_localize(None)

    if cached and age is not None and age<fresh and covers(cached['t'], past_days, now=clock):
        STATS['hit']+=1; STATS['src']='cache_fresh'
        out=(cached['t'],cached['R'],'cache_fresh'); _MEMO[mk]=out; return out

    def _full():
        t,R=http_grid(get,la,lo,nlat,nlon,model,days,past_days,chunk)
        return t,R,'http_full'
    def _short():
        t2,R2=http_grid(get,la,lo,nlat,nlon,model,days,short_past,chunk)
        t,R=stitch(cached['t'],cached['R'],t2,R2)
        if not covers(t, past_days, now=clock):
            return _full()
        return t,R,'http_short'

    try:
        if cached and age is not None and age<hist_max and covers(cached['t'], past_days, now=clock):
            t,R,src=_short()
        else:
            t,R,src=_full()
        save_grid(model,nlat,nlon,t,R)
        STATS['miss']+=1; STATS['src']=src
        out=(t,R,src)
    except Exception as e:
        if cached and age is not None and age<stale:
            STATS['stale']+=1; STATS['src']=f'cache_stale:{type(e).__name__}'
            out=(cached['t'],cached['R'],STATS['src'])
        else:
            raise
    _MEMO[mk]=out; return out
