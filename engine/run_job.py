"""Hourly job (GitHub Actions). Writes site/data/{alerts_latest.json,risk_live.geojson,viewpoints.json,config.json}; then sends web push.
env: FORECAST_MODEL (icon_seamless; fallback ecmwf_ifs025), VAPID_PRIVATE_KEY, VAPID_PUBLIC_KEY, VAPID_SUB (mailto:...),
     SUBSCRIPTIONS_URL + SUBSCRIPTIONS_TOKEN (private Apps Script store only; never a file in the repo),
     USE_IMS_RADAR=0 (not implemented here; needs IMS token).
Push is sent only when VAPID_PRIVATE_KEY is set (the Action). Payloads are built from this job's alert fields.
Dead endpoints (HTTP 404/410) are pruned on the private store. Secrets and endpoint URLs are not printed."""
import os,math,sys,json,re,time,traceback,datetime as dt,glob,urllib.parse,pandas as pd
sys.path.insert(0,os.path.dirname(os.path.abspath(__file__))); import importlib
ENGINE_VERSION=os.environ.get('ENGINE_VERSION','v2')   # one-line switch: 'v1' = old engine/flood_engine.py
def _load_engine(v): return importlib.import_module('flood_engine' if v=='v1' else 'flood_engine_v2')
fe=_load_engine(ENGINE_VERSION)
_CALJ=json.load(open(f'{fe.ROOT}/model/calibration.json')); DESERT_THR=float((_CALJ.get('selected') or _CALJ).get('alert_thr') or 0.3)
ROOT=fe.ROOT; SITE=f'{ROOT}/site/data'; os.makedirs(SITE,exist_ok=True); os.makedirs(f'{ROOT}/state',exist_ok=True)
def vapid_public():
    """Actions secret when set; otherwise the published vapid_public_key.txt. Never logs the key."""
    k=os.environ.get('VAPID_PUBLIC_KEY','').strip()
    if k: return k
    try: return open(f'{ROOT}/vapid_public_key.txt',encoding='utf-8').read().strip()
    except OSError: return ''
def jload(p,d):
    try: return json.load(open(p))
    except Exception: return d
def _clean(o):
    if isinstance(o,float): return o if math.isfinite(o) else None
    if isinstance(o,dict): return {k:_clean(v) for k,v in o.items()}
    if isinstance(o,(list,tuple)): return [_clean(v) for v in o]
    if hasattr(o,'item') and not isinstance(o,(str,bytes)):
        try: return _clean(o.item())
        except Exception: return o
    return o
def jsave(p,o,indent=None): json.dump(_clean(o),open(p+'.tmp','w'),ensure_ascii=False,indent=indent,default=str,allow_nan=False,separators=None if indent else (',',':')); os.replace(p+'.tmp',p)
norm=lambda x:str(x).replace('נחל ','').strip()
def _main():
    t0=time.time(); now=pd.Timestamp.now('UTC').tz_localize(None).floor('h'); g=None; err=None
    if os.environ.get('USE_IMS_RADAR','0')=='1': print('USE_IMS_RADAR=1 ignored: radar input not supported in the Actions engine (needs IMS token + regridding)')
    for m in [os.environ.get('FORECAST_MODEL','icon_seamless'),'ecmwf_ifs025']:
        try: g=fe.openmeteo_grid(m); break
        except Exception as e: err=e; traceback.print_exc()
    if g is None:
        out=dict(issued=dt.datetime.now(dt.timezone.utc).strftime('%Y-%m-%d %H:%M UTC'),source=f'stub ({type(err).__name__})',stub=True,alerts=[]); jsave(f'{SITE}/alerts_latest.json',out); return 1
    print(f'grid {g.name} {g.t[0]}..{g.t[-1]} max cell total {float(g.cs[-1].max()):.1f} mm ({time.time()-t0:.0f}s)')
    A=fe.evaluate_points(g,now); out=dict(issued=fe.il(now),source=f'flood_engine/{g.name}',stub=False,alerts=A); jsave(f'{SITE}/alerts_latest.json',out,1)
    try:
        segs=fe.score_channel_segments(g,now)
        t0s=int(pd.Timestamp(now).timestamp())
        # Arrays are indexed by segment id (ids are sparse after the v5arava/v7zin fixes); gaps are None.
        _n=max(int(s['id']) for s in segs)+1; _pos=[None]*_n
        for s in segs: _pos[int(s['id'])]=s
        _gap=dict(prob=None,rain=None,lead=None,eta=None,tt_p10_s=None,tt_med_s=None)
        segs_d=[x if x is not None else _gap for x in _pos]
        compact=dict(v=1,t0=t0s,issued=fe.il(now),
            p=[round(s['prob'],3) if s['prob'] is not None else None for s in segs_d],rain=[s['rain'] for s in segs_d],
            lead=[s['lead'] for s in segs_d],
            em=[int(round((s['eta']-now).total_seconds()/60)) if s['eta'] is not None else -1 for s in segs_d],
            tp=[int(round(s['tt_p10_s']/60)) if s['tt_p10_s'] is not None else None for s in segs_d],tm=[int(round(s['tt_med_s']/60)) if s['tt_med_s'] is not None else None for s in segs_d])
        jsave(f'{SITE}/segment_risk.json',compact)
        print(f'segments: {len(segs)} scored, {sum(s["prob"]>=DESERT_THR for s in segs)} with prob>={DESERT_THR} ({time.time()-t0:.0f}s)')
    except Exception:
        traceback.print_exc(); print('segment scoring failed')
    R,n=fe.live_risk(g,now,f'{ROOT}/data/basins_simplified.geojson'); jsave(f'{SITE}/risk_live.geojson',R)
    nd_dt=None
    try:
        import nondesert as nd
        t_nd=time.time()
        gN=fe.openmeteo_grid(m, past_days=31)
        info=nd.score_all(gN, now)
        geo, compact=nd.write_outputs(info, fe.il(now), now)
        compact['t0']=int(pd.Timestamp(now).tz_localize('UTC').timestamp())
        jsave(f'{SITE}/risk_nondesert.geojson', geo)
        jsave(f'{SITE}/segment_risk_nondesert.json', compact)
        for b in info['basins'].values():
            if not b['alert']: continue
            A.append(dict(point='ND'+b['sid'], name=b['name'], nahal=b['name'], region='north_center',
                prob=b['p'], eta_first_wave=None, hours_until_first_wave=None,
                rain_summary=dict(basin_mean_mm=b['rain']), confidence='low', estimate=True, source='nondesert_flow'))
        jsave(f'{SITE}/alerts_latest.json', out, 1)
        nd_dt=time.time()-t_nd
        print(f'nondesert: {info["n_basins"]} basins, {info["n_segs"]} segments, {info["n_alert"]} over threshold, grid {gN.t[0]}..{gN.t[-1]} ({nd_dt:.0f}s, job {time.time()-t0:.0f}s)')
    except Exception:
        traceback.print_exc(); print('nondesert scoring failed')
    # static viewpoints.json = viewpoints.csv + historical first waves + current alert (replaces /api/viewpoints)
    vp=pd.read_csv(f'{ROOT}/data/viewpoints.csv').fillna(''); fw=pd.read_csv(f'{ROOT}/data/first_wave_times.csv').fillna(''); al={a['point']:a for a in A}; V=[]
    for _,v in vp.iterrows():
        d=v.to_dict(); k=norm(v.nahal)
        d['first_waves']=fw[fw.nahal.astype(str).str.contains(k,regex=False)].head(12)[['date','place','time_il','kind','lag_from_onset_h','lag_from_peak_h','note']].to_dict('records') if k else []
        d['current']=al.get(v.id); V.append(d)
    jsave(f'{SITE}/viewpoints.json',V)
    dates=sorted(os.path.basename(p)[5:15] for p in glob.glob(f'{SITE}/risk_20*.geojson'))
    pub=vapid_public()
    jsave(f'{SITE}/config.json',dict(vapid_public=pub,risk_dates=dates,live=out['issued'],subscribe_url=os.environ.get('SUBSCRIBE_URL',''),now=dt.datetime.now(dt.timezone.utc).isoformat(),nd_geom_version='v3d',desert_geom_version='v8ext',desert_alert_thr=DESERT_THR),1)
    nal=sum(a['prob']>=(0.3 if a.get('region')=='north_center' else DESERT_THR) for a in A); print(f'alerts: {len(A)} points, {nal} with prob>={DESERT_THR} (engine {fe.__name__}); risk: {n} basins scored; vapid_public={"secret" if os.environ.get("VAPID_PUBLIC_KEY","").strip() else ("file" if pub else "missing")}; {time.time()-t0:.0f}s')
    notify(A,g,now); return 0
# Same 60 m cap as site/tap_basin.js NORTH_RESNAP_M / snapToleranceMeters. No zoom on the server.
NORTH_SNAP_M=60
_NORTH_SEGS=None
_NORTH_ID_MAP=None
def north_segments():
    global _NORTH_SEGS
    if _NORTH_SEGS is None:
        import gzip
        with gzip.open(f'{ROOT}/data/channel_segments_nondesert.json.gz','rt') as f:
            _NORTH_SEGS=json.load(f).get('segments') or []
    return _NORTH_SEGS
def north_id_map():
    global _NORTH_ID_MAP
    if _NORTH_ID_MAP is None:
        raw=jload(f'{ROOT}/data/id_map_nondesert_v2_to_v3b.json',{})
        _NORTH_ID_MAP=raw if isinstance(raw,dict) else {}
    return _NORTH_ID_MAP
def _seg_dist_m(lat,lon,coords):
    import math
    kx=111320*math.cos(math.radians(lat)); ky=110540
    px,py=lon*kx, lat*ky
    best=1e18
    for k in range(1,len(coords)):
        ax,ay=coords[k-1][0]*kx, coords[k-1][1]*ky
        bx,by=coords[k][0]*kx, coords[k][1]*ky
        dx,dy=bx-ax, by-ay
        L2=dx*dx+dy*dy
        t=0 if L2==0 else max(0.0,min(1.0,((px-ax)*dx+(py-ay)*dy)/L2))
        d=math.hypot(px-(ax+t*dx), py-(ay+t*dy))
        if d<best: best=d
    return best
def resolve_north_segment(lat,lon,old_seg=None):
    """Nearest current north/center segment within 60 m. A v2->v3b id is used only if that segment is inside the radius."""
    mapped=None
    if old_seg is not None:
        raw=north_id_map().get(str(int(old_seg)))
        if raw is not None:
            try: mapped=int(raw)
            except (TypeError,ValueError): mapped=None
    nearest=None
    mapped_d=None
    for s in north_segments():
        coords=s.get('coords') or []
        if len(coords)<2: continue
        d=_seg_dist_m(lat,lon,coords)
        sid=int(s['id'])
        if mapped is not None and sid==mapped: mapped_d=d
        if d<=NORTH_SNAP_M and (nearest is None or d<nearest[0]): nearest=(d,sid)
    if mapped is not None and mapped_d is not None and mapped_d<=NORTH_SNAP_M: return mapped
    return None if nearest is None else nearest[1]
_DESERT_IDS=None
def desert_segments():
    import gzip
    with gzip.open(f'{ROOT}/data/channel_segments.json.gz','rt') as f: return json.load(f)['segments']
def resolve_desert_segment(lat,lon,seg):
    """Desert seg id if it still exists (v7zin). Removed ids re-snap to the nearest desert segment within 60 m, else None."""
    global _DESERT_IDS
    segs=None
    if _DESERT_IDS is None:
        segs=desert_segments(); _DESERT_IDS=set(int(s['id']) for s in segs)
    if seg in _DESERT_IDS: return seg
    segs=segs or desert_segments()
    best=None
    for s in segs:
        co=s.get('coords') or []
        if len(co)==1: co=co*2
        if len(co)<2: continue
        d=_seg_dist_m(lat,lon,co)
        if d<=NORTH_SNAP_M and (best is None or d<best[0]): best=(d,int(s['id']))
    return None if best is None else best[1]
_PUSH_HOSTS=frozenset({'fcm.googleapis.com','updates.push.services.mozilla.com'})
_PUSH_SUFFIXES=('.push.apple.com','.notify.windows.com')
def push_endpoint_ok(url):
    """https endpoints on known browser push services only."""
    if not isinstance(url,str) or not (12<=len(url)<=500) or not url.startswith('https://'): return False
    try: p=urllib.parse.urlparse(url)
    except Exception: return False
    if p.scheme!='https' or p.username or p.password or not p.hostname: return False
    host=p.hostname.lower().rstrip('.')
    if host in _PUSH_HOSTS: return True
    return any(host.endswith(suf) and len(host)>len(suf) for suf in _PUSH_SUFFIXES)
def _b64url(s,lo,hi): return isinstance(s,str) and lo<=len(s)<=hi and re.fullmatch(r'[A-Za-z0-9_-]+',s) is not None
def _clip(v,n):
    s='' if v is None else str(v).replace('\r',' ').replace('\n',' ')
    return s[:n]
def clean_sub(s):
    """Whitelist fields. Drop anything that is not a real push subscription."""
    if not isinstance(s,dict): return None
    push=s.get('push')
    if not isinstance(push,dict) or not push_endpoint_ok(push.get('endpoint')): return None
    keys=push.get('keys') if isinstance(push.get('keys'),dict) else {}
    if not _b64url(keys.get('p256dh'),80,120) or not _b64url(keys.get('auth'),16,40): return None
    pts=[]
    for p in (s.get('points') or [])[:40]:
        if isinstance(p,str) and re.fullmatch(r'VP\d{2}',p): pts.append(p)
    streams=[]
    for x in (s.get('streams') or [])[:12]:
        if isinstance(x,str) and 1<=len(x)<=40 and not re.search(r'[\x00-\x1f<>]',x): streams.append(x)
    try: thr=None if s.get('threshold') is None else float(s['threshold'])   # None = desert default (calibration.json alert_thr)
    except (TypeError,ValueError): return None
    if thr is not None and not (0.05<=thr<=0.9): thr=None
    uid=s.get('uid')
    if not isinstance(uid,str) or not re.fullmatch(r'u[a-z0-9]{6,20}',uid): uid='anon'
    custom=[]
    for c in (s.get('custom') or [])[:8]:
        if not isinstance(c,dict): continue
        if not isinstance(c.get('id'),str) or not re.fullmatch(r'M[a-z0-9]{6,16}',c['id']): continue
        try: lat=float(c.get('lat')); lon=float(c.get('lon'))
        except (TypeError,ValueError): continue
        if not (29.3<=lat<=33.5 and 34.1<=lon<=36.0): continue
        if c.get('region')=='north_center':
            try: old_seg=int(c.get('seg'))
            except (TypeError,ValueError): old_seg=None
            new_seg=resolve_north_segment(lat,lon,old_seg)
            if new_seg is None: continue
            custom.append(dict(id=c['id'],seg=new_seg,sid=str(c.get('sid') or ''),lat=round(lat,5),lon=round(lon,5),region='north_center'))
            continue
        seg=c.get('seg')
        try: seg=int(seg)
        except (TypeError,ValueError): seg=None
        if seg is not None and 0<=seg<=20000:
            seg=resolve_desert_segment(lat,lon,seg)
            if seg is None: continue
            item=dict(id=c['id'],seg=seg,sid=str(c.get('sid') or ''),lat=round(lat,5),lon=round(lon,5))
            if c.get('region')=='north_center': item['region']='north_center'
            custom.append(item)
            continue
        try: along=float(c.get('along'))
        except (TypeError,ValueError): continue
        if not (isinstance(c.get('sid'),str) and re.fullmatch(r'\d{3,8}',str(c['sid'])) and 0<=along<=1): continue
        custom.append(dict(id=c['id'],sid=str(c['sid']),along=round(along,3),lat=round(lat,5),lon=round(lon,5)))
    return dict(uid=uid,points=pts,streams=streams,threshold=thr,custom=custom,push=dict(endpoint=push['endpoint'],keys=dict(p256dh=keys['p256dh'],auth=keys['auth'])))
def _store_url():
    u=os.environ.get('SUBSCRIPTIONS_URL','').strip()
    if not u: return ''
    p=urllib.parse.urlparse(u)
    if p.scheme!='https' or (p.hostname or '').lower() not in ('script.google.com','script.googleusercontent.com'):
        print('subscriptions url rejected'); return ''
    return u
def load_subs():
    """Remote store only. A file in the public repo is never a subscription source."""
    u=_store_url()
    if not u: print('push: no remote subscription store'); return []
    import requests
    try:
        r=requests.get(u,params={'token':os.environ.get('SUBSCRIPTIONS_TOKEN','')},timeout=30,allow_redirects=True)
        r.raise_for_status(); data=r.json()
    except Exception as e:
        print('subscriptions fetch failed',type(e).__name__); return []
    if not isinstance(data,list): print('subscriptions payload rejected'); return []
    out=[]
    for item in data[:500]:
        c=clean_sub(item)
        if c: out.append(c)
    return out
def push_payload(a):
    """Notification text comes only from this job's alert record, trimmed and single-line."""
    if not isinstance(a,dict) or not isinstance(a.get('point'),str) or not re.fullmatch(r'(VP\d{2}|M[a-z0-9]{6,16})',a['point']): return None
    try: pct=int(round(float(a.get('prob'))*100))
    except (TypeError,ValueError): return None
    if pct<0 or pct>100: return None
    name=_clip(a.get('name'),80) or a['point']; nahal=_clip(a.get('nahal'),80) or 'נחל'
    h=a.get('hours_until_first_wave'); rs=a.get('rain_summary') if isinstance(a.get('rain_summary'),dict) else {}
    when=f"בעוד ~{_clip(h,8)} שעות" if h is not None else 'בלי שעת הגעה'
    rain=_clip(rs.get('basin_mean_mm'),8) or '?'; intensity=_clip(rs.get('max_cell_mm_h'),8) or '?'
    title=_clip(('הערכה: ' if a.get('estimate') else '')+f"סיכוי גבוה לשיטפון ב{nahal} ({pct}%)",120)
    where='גשם במעלה הערוץ' if a.get('channel') else 'גשם ממוצע באגן'
    extra='' if a.get('channel') else f", עוצמה מרבית {intensity} מ\"מ/שעה"
    body=_clip(('הערכה בלבד. ' if a.get('estimate') else '')+f"הגל צפוי להגיע לנקודה {name} {when} · {where} {rain} מ\"מ{extra}",240)
    return dict(title=title,body=body,url='./#alerts')
def prune_remote(endpoints):
    u=_store_url(); token=os.environ.get('SUBSCRIPTIONS_TOKEN','').strip()
    if not u or not token or not endpoints: return
    import requests
    body=json.dumps(dict(action='prune',token=token,endpoints=endpoints[:100]))
    try:
        r=requests.post(u,data=body.encode(),headers={'Content-Type':'text/plain'},timeout=30,allow_redirects=True)
        print('prune http',r.status_code,'n',len(endpoints[:100]))
    except Exception as e:
        print('prune failed',type(e).__name__)
def _push_one(s,a,key,sent,dead):
    payload=push_payload(a)
    if not payload: return 0
    k=f"{s['uid']}|{a['point']}|{_clip(a.get('eta_first_wave'),13)}"
    if k in sent: return 0
    from pywebpush import webpush,WebPushException
    try:
        webpush(s['push'],json.dumps(payload,ensure_ascii=False),vapid_private_key=key,vapid_claims={'sub':os.environ.get('VAPID_SUB','mailto:flood-app@example.invalid')}); sent[k]=time.time(); return 1
    except WebPushException as e:
        code=getattr(getattr(e,'response',None),'status_code',None)
        print('push failed',code)
        if code in (404,410): dead.append(s['push']['endpoint'])
    except Exception as e: print('push error',type(e).__name__)
    return 0
def notify(A,g=None,now=None):
    key=os.environ.get('VAPID_PRIVATE_KEY'); subs=load_subs()
    if not key or not subs: print(f'push: skipped (key={"set" if key else "missing"}, subscriptions={len(subs)})'); return
    pem=None
    if '-----BEGIN' in key:   # PEM secret -> temp file (pywebpush accepts a path or base64url DER)
        import tempfile; fd,pem=tempfile.mkstemp(suffix='.pem'); os.write(fd,key.replace('\\n','\n').encode()); os.close(fd); os.chmod(pem,0o600); key=pem
    sentp=f'{ROOT}/state/push_sent.json'; sent=jload(sentp,{}); n=0; dead=[]
    try:
        for s in subs:
            pts=set(s['points']); st={norm(x) for x in s['streams']}; thr0=s['threshold']
            for a in A:
                via=a.get('point') in pts or norm(a.get('nahal')) in st
                thr=thr0 if thr0 is not None else (0.3 if a.get('region')=='north_center' else DESERT_THR)
                if not via or not isinstance(a.get('prob'),(int,float)) or a['prob']<thr: continue
                n+=_push_one(s,a,key,sent,dead)
            for c in s.get('custom') or []:
                if g is None or now is None: break
                ca=fe.custom_point_alert(g,now,c)
                cthr=thr0 if thr0 is not None else (0.3 if c.get('region')=='north_center' else DESERT_THR)
                if not ca or not isinstance(ca.get('prob'),(int,float)) or ca['prob']<cthr: continue
                n+=_push_one(s,ca,key,sent,dead)
    finally:
        if pem:
            try: os.remove(pem)
            except OSError: pass
    cut=time.time()-14*86400; jsave(sentp,{k:v for k,v in sent.items() if v>cut},1)
    if dead: prune_remote(list(dict.fromkeys(dead)))
    print(f'push: sent {n}; pruned {len(set(dead))}')
def main():
    global fe
    try:
        if os.environ.get('FORCE_V2_FAIL')=='1' and fe.__name__=='flood_engine_v2': raise RuntimeError('forced v2 failure (test)')
        return _main()
    except Exception:
        if fe.__name__!='flood_engine_v2': raise
        traceback.print_exc(); print('ENGINE FALLBACK: flood_engine_v2 failed -> running old flood_engine (v1)')
        fe=_load_engine('v1'); return _main()

if __name__=='__main__': sys.exit(main())
