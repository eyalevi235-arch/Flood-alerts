"""Hourly job (GitHub Actions). Writes site/data/{alerts_latest.json,risk_live.geojson,viewpoints.json,config.json}; then sends web push.
env: FORECAST_MODEL (icon_seamless; fallback ecmwf_ifs025), VAPID_PRIVATE_KEY, VAPID_PUBLIC_KEY, VAPID_SUB (mailto:...),
     SUBSCRIPTIONS_URL + SUBSCRIPTIONS_TOKEN (private Apps Script store only; never a file in the repo),
     USE_IMS_RADAR=0 (not implemented here; needs IMS token).
Push is sent only when VAPID_PRIVATE_KEY is set (the Action). Payloads are built from this job's alert fields.
Dead endpoints (HTTP 404/410) are pruned on the private store. Secrets and endpoint URLs are not printed."""
import os,sys,json,re,time,traceback,datetime as dt,glob,urllib.parse,pandas as pd
sys.path.insert(0,os.path.dirname(os.path.abspath(__file__))); import flood_engine as fe
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
def jsave(p,o,indent=None): json.dump(o,open(p+'.tmp','w'),ensure_ascii=False,indent=indent,default=str,separators=None if indent else (',',':')); os.replace(p+'.tmp',p)
norm=lambda x:str(x).replace('נחל ','').strip()
def main():
    t0=time.time(); now=pd.Timestamp.now('UTC').tz_localize(None).floor('h'); g=None; err=None
    if os.environ.get('USE_IMS_RADAR','0')=='1': print('USE_IMS_RADAR=1 ignored: radar input not supported in the Actions engine (needs IMS token + regridding)')
    for m in [os.environ.get('FORECAST_MODEL','icon_seamless'),'ecmwf_ifs025']:
        try: g=fe.openmeteo_grid(m); break
        except Exception as e: err=e; traceback.print_exc()
    if g is None:
        out=dict(issued=dt.datetime.now(dt.timezone.utc).strftime('%Y-%m-%d %H:%M UTC'),source=f'stub ({type(err).__name__})',stub=True,alerts=[]); jsave(f'{SITE}/alerts_latest.json',out); return 1
    print(f'grid {g.name} {g.t[0]}..{g.t[-1]} max cell total {float(g.cs[-1].max()):.1f} mm ({time.time()-t0:.0f}s)')
    A=fe.evaluate_points(g,now); out=dict(issued=fe.il(now),source=f'flood_engine/{g.name}',stub=False,alerts=A); jsave(f'{SITE}/alerts_latest.json',out,1)
    R,n=fe.live_risk(g,now,f'{ROOT}/data/basins_simplified.geojson'); jsave(f'{SITE}/risk_live.geojson',R)
    # static viewpoints.json = viewpoints.csv + historical first waves + current alert (replaces /api/viewpoints)
    vp=pd.read_csv(f'{ROOT}/data/viewpoints.csv').fillna(''); fw=pd.read_csv(f'{ROOT}/data/first_wave_times.csv').fillna(''); al={a['point']:a for a in A}; V=[]
    for _,v in vp.iterrows():
        d=v.to_dict(); k=norm(v.nahal)
        d['first_waves']=fw[fw.nahal.astype(str).str.contains(k,regex=False)].head(12)[['date','place','time_il','kind','lag_from_onset_h','lag_from_peak_h','note']].to_dict('records') if k else []
        d['current']=al.get(v.id); V.append(d)
    jsave(f'{SITE}/viewpoints.json',V)
    dates=sorted(os.path.basename(p)[5:15] for p in glob.glob(f'{SITE}/risk_20*.geojson'))
    pub=vapid_public()
    jsave(f'{SITE}/config.json',dict(vapid_public=pub,risk_dates=dates,live=out['issued'],subscribe_url=os.environ.get('SUBSCRIBE_URL',''),now=dt.datetime.now(dt.timezone.utc).isoformat()),1)
    nal=sum(a['prob']>=0.3 for a in A); print(f'alerts: {len(A)} points, {nal} with prob>=0.3; risk: {n} basins scored; vapid_public={"secret" if os.environ.get("VAPID_PUBLIC_KEY","").strip() else ("file" if pub else "missing")}; {time.time()-t0:.0f}s')
    notify(A); return 0
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
    try: thr=float(s.get('threshold',0.3))
    except (TypeError,ValueError): return None
    if not (0.05<=thr<=0.9): thr=0.3
    uid=s.get('uid')
    if not isinstance(uid,str) or not re.fullmatch(r'u[a-z0-9]{6,20}',uid): uid='anon'
    return dict(uid=uid,points=pts,streams=streams,threshold=thr,push=dict(endpoint=push['endpoint'],keys=dict(p256dh=keys['p256dh'],auth=keys['auth'])))
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
    if not isinstance(a,dict) or not isinstance(a.get('point'),str) or not re.fullmatch(r'VP\d{2}',a['point']): return None
    try: pct=int(round(float(a.get('prob'))*100))
    except (TypeError,ValueError): return None
    if pct<0 or pct>100: return None
    name=_clip(a.get('name'),80) or a['point']; nahal=_clip(a.get('nahal'),80) or 'נחל'
    h=a.get('hours_until_first_wave'); rs=a.get('rain_summary') if isinstance(a.get('rain_summary'),dict) else {}
    when=f"בעוד ~{_clip(h,8)} שעות" if h is not None else 'בלי שעת הגעה'
    rain=_clip(rs.get('basin_mean_mm'),8) or '?'; intensity=_clip(rs.get('max_cell_mm_h'),8) or '?'
    title=_clip(f"סיכוי גבוה לשיטפון ב{nahal} ({pct}%)",120)
    body=_clip(f"הגל צפוי להגיע לנקודה {name} {when} · גשם ממוצע באגן {rain} מ\"מ, עוצמה מרבית {intensity} מ\"מ/שעה",240)
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
def notify(A):
    key=os.environ.get('VAPID_PRIVATE_KEY'); subs=load_subs()
    if not key or not subs: print(f'push: skipped (key={"set" if key else "missing"}, subscriptions={len(subs)})'); return
    from pywebpush import webpush,WebPushException
    pem=None
    if '-----BEGIN' in key:   # PEM secret -> temp file (pywebpush accepts a path or base64url DER)
        import tempfile; fd,pem=tempfile.mkstemp(suffix='.pem'); os.write(fd,key.replace('\\n','\n').encode()); os.close(fd); os.chmod(pem,0o600); key=pem
    sentp=f'{ROOT}/state/push_sent.json'; sent=jload(sentp,{}); n=0; dead=[]
    try:
        for s in subs:
            pts=set(s['points']); st={norm(x) for x in s['streams']}; thr=s['threshold']
            for a in A:
                via=a.get('point') in pts or norm(a.get('nahal')) in st
                if not via or not isinstance(a.get('prob'),(int,float)) or a['prob']<thr: continue
                payload=push_payload(a)
                if not payload: continue
                k=f"{s['uid']}|{a['point']}|{_clip(a.get('eta_first_wave'),13)}"
                if k in sent: continue
                try:
                    webpush(s['push'],json.dumps(payload,ensure_ascii=False),vapid_private_key=key,vapid_claims={'sub':os.environ.get('VAPID_SUB','mailto:flood-app@example.invalid')}); n+=1; sent[k]=time.time()
                except WebPushException as e:
                    code=getattr(getattr(e,'response',None),'status_code',None)
                    print('push failed',code)
                    if code in (404,410): dead.append(s['push']['endpoint'])
                except Exception as e: print('push error',type(e).__name__)
    finally:
        if pem:
            try: os.remove(pem)
            except OSError: pass
    cut=time.time()-14*86400; jsave(sentp,{k:v for k,v in sent.items() if v>cut},1)
    if dead: prune_remote(list(dict.fromkeys(dead)))
    print(f'push: sent {n}; pruned {len(set(dead))}')
if __name__=='__main__': sys.exit(main())
