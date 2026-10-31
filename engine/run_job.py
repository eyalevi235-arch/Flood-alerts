"""Hourly job (GitHub Actions). Writes site/data/{alerts_latest.json,risk_live.geojson,viewpoints.json,config.json}; then sends web push.
env: FORECAST_MODEL (icon_seamless; fallback ecmwf_ifs025), VAPID_PRIVATE_KEY, VAPID_PUBLIC_KEY, VAPID_SUB (mailto:...),
     SUBSCRIPTIONS_URL + SUBSCRIPTIONS_TOKEN (optional remote store; else subscriptions/subscriptions.json), USE_IMS_RADAR=0 (not implemented here; needs IMS token)."""
import os,sys,json,time,traceback,datetime as dt,glob,pandas as pd
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
def load_subs():
    u=os.environ.get('SUBSCRIPTIONS_URL')
    if u:
        import requests
        try: return requests.get(u,params={'token':os.environ.get('SUBSCRIPTIONS_TOKEN','')},timeout=30).json()
        except Exception: traceback.print_exc()
    return jload(f'{ROOT}/subscriptions/subscriptions.json',[])
def notify(A):
    key=os.environ.get('VAPID_PRIVATE_KEY'); subs=load_subs()
    if not key or not subs: print(f'push: skipped (key={"set" if key else "missing"}, subscriptions={len(subs)})'); return
    from pywebpush import webpush,WebPushException
    if '-----BEGIN' in key:   # PEM secret -> temp file (pywebpush accepts a path or base64url DER)
        import tempfile; fd,kp=tempfile.mkstemp(suffix='.pem'); os.write(fd,key.replace('\\n','\n').encode()); os.close(fd); os.chmod(kp,0o600); key=kp
    sentp=f'{ROOT}/state/push_sent.json'; sent=jload(sentp,{}); n=0
    for s in subs:
        if not s.get('push'): continue
        pts=set(s.get('points',[])); st={norm(x):x for x in s.get('streams',[])}; thr=float(s.get('threshold',0.3))
        for a in A:
            via=a['point'] in pts or norm(a['nahal']) in st
            if not via or a['prob']<thr: continue
            k=f"{s.get('uid')}|{a['point']}|{str(a.get('eta_first_wave'))[:13]}"
            if k in sent: continue
            h=a.get('hours_until_first_wave'); rs=a.get('rain_summary') or {}
            body=(f"הגל צפוי להגיע לנקודה {a['name']} בעוד ~{h} שעות" if h is not None else f"נקודה: {a['name']}")+f" · גשם ממוצע באגן {rs.get('basin_mean_mm','?')} מ\"מ, עוצמה מרבית {rs.get('max_cell_mm_h','?')} מ\"מ/שעה"
            try:
                webpush(s['push'],json.dumps(dict(title=f"סיכוי גבוה לשיטפון ב{a['nahal']} ({int(a['prob']*100)}%)",body=body,url='./#alerts'),ensure_ascii=False),
                        vapid_private_key=key,vapid_claims={'sub':os.environ.get('VAPID_SUB','mailto:flood-app@example.invalid')}); n+=1; sent[k]=time.time()
            except WebPushException as e: print('push failed',getattr(e.response,'status_code',None))
            except Exception as e: print('push error',type(e).__name__)
    cut=time.time()-14*86400; jsave(sentp,{k:v for k,v in sent.items() if v>cut},1); print(f'push: sent {n}')
if __name__=='__main__': sys.exit(main())
