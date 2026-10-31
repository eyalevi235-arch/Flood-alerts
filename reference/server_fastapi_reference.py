"""Flood PWA backend (port 8878). API + static + web push (self-hosted VAPID) + scheduled alert_engine job."""
import json, os, sys, glob, threading, time, traceback, datetime as dt
import pandas as pd
from fastapi import FastAPI, Body
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from fastapi.middleware.gzip import GZipMiddleware
R='/workspace/flood'; A=f'{R}/app'; DATA=f'{A}/data'; os.makedirs(DATA,exist_ok=True)
app=FastAPI(); app.add_middleware(GZipMiddleware,minimum_size=1000)
def jload(p,d):
    try: return json.load(open(p))
    except Exception: return d
def jsave(p,o): json.dump(o,open(p+'.tmp','w'),ensure_ascii=False,indent=1,default=str); os.replace(p+'.tmp',p)
# ---- VAPID (generated locally once; private key never printed) ----
VK=f'{DATA}/vapid_private.pem'
def vapid_pub():
    from py_vapid import Vapid01
    from cryptography.hazmat.primitives import serialization; import base64
    if not os.path.exists(VK):
        v=Vapid01(); v.generate_keys(); v.save_key(VK); os.chmod(VK,0o600)
    v=Vapid01.from_file(VK)
    raw=v.public_key.public_bytes(serialization.Encoding.X962,serialization.PublicFormat.UncompressedPoint)
    return base64.urlsafe_b64encode(raw).decode().rstrip('=')
PUB=vapid_pub()
# ---- data ----
def risk_files(): return sorted(os.path.basename(p)[5:15] for p in glob.glob(f'{R}/gis/risk_*.geojson'))
_cache={}
def cached(p):
    m=os.path.getmtime(p)
    if _cache.get(p,(0,))[0]!=m: _cache[p]=(m,json.load(open(p)))
    return _cache[p][1]
@app.get('/api/config')
def config(): return dict(vapid_public=PUB,risk_dates=risk_files(),live=jload(f'{DATA}/risk_live.geojson',{}).get('issued') if os.path.exists(f'{DATA}/risk_live.geojson') else None,public_url=open(f'{DATA}/public_url.txt').read().strip() if os.path.exists(f'{DATA}/public_url.txt') else None,now=dt.datetime.now().isoformat())
@app.get('/api/risk')
def risk(date:str='latest', perennial:int=0):
    ds=risk_files(); live=f'{DATA}/risk_live.geojson'
    if date in ('live','latest') and os.path.exists(live): g=cached(live); d='live'
    else: d=ds[-1] if date not in ds else date; g=cached(f'{R}/gis/risk_{d}.geojson')
    f=[x for x in g['features'] if perennial or not x['properties'].get('perennial')]
    return dict(type='FeatureCollection',date=d,issued=g.get('issued'),features=f)
@app.get('/api/streams')
def streams(min_km2:float=50):
    g=cached(f'{R}/gis/streams.geojson')
    return dict(type='FeatureCollection',features=[x for x in g['features'] if (x['properties'].get('acc_km2') or 0)>=min_km2])
def first_waves():
    try: return pd.read_csv(f'{R}/viewpoints/first_wave_times.csv').fillna('')
    except Exception: return pd.DataFrame()
@app.get('/api/viewpoints')
def viewpoints(src:str='live'):
    vp=pd.read_csv(f'{R}/viewpoints/viewpoints.csv').fillna(''); fw=first_waves(); al={a['point']:a for a in latest_alerts(src)['alerts']}
    out=[]
    for _,v in vp.iterrows():
        d=v.to_dict(); key=str(v.nahal).replace('נחל ','')
        d['first_waves']=fw[fw.nahal.astype(str).str.contains(key,regex=False)].head(12)[['date','place','time_il','kind','lag_from_onset_h','lag_from_peak_h','note']].to_dict('records') if len(fw) and key else []
        d['current']=al.get(v.id); out.append(d)
    return out
# ---- subscriptions / prefs ----
PREFS=f'{DATA}/prefs.json'; PUSH=f'{DATA}/push_subs.json'; ALERTS=f'{DATA}/alerts_latest.json'
@app.get('/api/prefs/{uid}')
def get_prefs(uid:str): return jload(PREFS,{}).get(uid,dict(points=[],streams=[],threshold=0.3))
@app.post('/api/prefs/{uid}')
def set_prefs(uid:str,p:dict=Body(...)):
    a=jload(PREFS,{}); a[uid]=dict(points=p.get('points',[]),streams=p.get('streams',[]),threshold=float(p.get('threshold',0.3))); jsave(PREFS,a); return a[uid]
@app.post('/api/push/subscribe/{uid}')
def push_sub(uid:str,sub:dict=Body(...)):
    a=jload(PUSH,{}); l=[s for s in a.get(uid,[]) if s.get('endpoint')!=sub.get('endpoint')]; a[uid]=l+[sub]; jsave(PUSH,a); return dict(ok=True)
@app.post('/api/push/test/{uid}')
def push_test(uid:str): return dict(sent=send_push(uid,dict(title='בדיקת התראה',body='התראות שיטפון פעילות במכשיר הזה ✔')))
def send_push(uid,payload):
    from pywebpush import webpush, WebPushException
    a=jload(PUSH,{}); n=0; keep=[]
    for s in a.get(uid,[]):
        try: webpush(s,json.dumps(payload,ensure_ascii=False),vapid_private_key=VK,vapid_claims={'sub':'mailto:flood-app@example.invalid'}); n+=1; keep.append(s)
        except WebPushException as e:
            if e.response is None or e.response.status_code not in (404,410): keep.append(s)
        except Exception: keep.append(s)
    a[uid]=keep; jsave(PUSH,a); return n
# ---- alert job ----
def _clean(L):
    for a in L['alerts']:
        if a.get('prob',0)<0.05: a.update(eta_first_wave=None,eta_peak=None,hours_until_first_wave=None)
    return L
def latest_alerts(src='live'): return _clean(jload(f'{DATA}/alerts_demo.json' if src=='demo' else ALERTS,dict(issued=None,source=None,stub=True,alerts=[])))
@app.get('/api/alerts/{uid}')
def alerts(uid:str,src:str='live'):
    L=latest_alerts(src); P=get_prefs(uid); pts=set(P['points']); norm=lambda x:str(x).replace('נחל ','').strip()
    st={norm(s):s for s in P['streams']}; mine=[]
    for a in L['alerts']:
        if a['point'] in pts: why=dict(via='point')
        elif norm(a.get('nahal')) in st: why=dict(via='stream',stream=st[norm(a.get('nahal'))])
        else: continue
        mine.append(dict(a,alert=a['prob']>=P['threshold'],**why))
    return dict(L,alerts=sorted(mine,key=lambda a:-a['prob']),threshold=P['threshold'])
def build_subs():
    s=[]
    for uid,p in jload(PREFS,{}).items():
        s+=[dict(user=uid,point=x,threshold=p['threshold']) for x in p['points']]+[dict(user=uid,stream=x,threshold=p['threshold']) for x in p['streams']]
    return s
def run_engine():
    """Run arrival/alert_engine.evaluate on live forecast for all points; stub if unavailable."""
    vp=pd.read_csv(f'{R}/viewpoints/viewpoints.csv'); subs=[dict(user='_all',point=i,threshold=0.0) for i in vp.id]
    try:
        sys.path.insert(0,f'{R}/arrival'); os.chdir(f'{R}/arrival'); import alert_engine as ae
        g=ae.fc.openmeteo_grid('icon_seamless'); now=pd.Timestamp.now('UTC').tz_localize(None).floor('h')
        res=ae.evaluate(g,subs,now); out=dict(issued=ae.il(now),source='alert_engine/open-meteo icon_seamless',stub=False,alerts=res)
    except Exception as e:
        traceback.print_exc()
        out=dict(issued=dt.datetime.now().strftime('%Y-%m-%d %H:%M'),source=f'stub ({type(e).__name__})',stub=True,
                 alerts=[dict(point=v.id,name=v.name_he,nahal=v.nahal,prob=0.0,eta_first_wave=None,eta_peak=None,hours_until_first_wave=None,rain_summary={},confidence='low') for v in vp.itertuples()])
    jsave(ALERTS,out); notify(out)
    if not out.get('stub'):
        try:
            import importlib; sys.path.insert(0,A); import live_risk; live_risk.build(g,now)
        except Exception: traceback.print_exc()
    return out
def notify(out):
    if out.get('stub'): return
    sent=jload(f'{DATA}/sent.json',{}); P=jload(PREFS,{})
    for uid in P:
        for a in alerts(uid)['alerts']:
            if not a['alert']: continue
            k=f"{uid}|{a['point']}|{str(a.get('eta_first_wave'))[:13]}"
            if k in sent: continue
            h=a.get('hours_until_first_wave'); rs=a.get('rain_summary') or {}
            body=f"הגל צפוי להגיע לנקודה {a['name']} בעוד ~{h} שעות" if h is not None else f"נקודה: {a['name']}"
            body+=f" · גשם ממוצע באגן {rs.get('basin_mean_mm','?')} מ\"מ, עוצמה מרבית {rs.get('max_cell_mm_h','?')} מ\"מ/שעה"
            send_push(uid,dict(title=f"סיכוי גבוה לשיטפון ב{a['nahal']} ({int(a['prob']*100)}%)"+(f" · במעקב: {a['stream']}" if a.get('via')=='stream' and a['stream'].replace('נחל ','')!=str(a['nahal']).replace('נחל ','') else ''),body=body,url='/#alerts')); sent[k]=time.time()
    jsave(f'{DATA}/sent.json',sent)
@app.post('/api/alerts/run')
def run_now(): return {'n':len(run_engine()['alerts'])}
def loop():
    while True:
        try: run_engine()
        except Exception: traceback.print_exc()
        time.sleep(int(os.environ.get('ALERT_INTERVAL_S',3600)))
@app.on_event('startup')
def start(): threading.Thread(target=loop,daemon=True).start()
@app.get('/')
def index(): return FileResponse(f'{A}/static/index.html')
@app.get('/sw.js')
def sw(): return FileResponse(f'{A}/static/sw.js',media_type='application/javascript')
app.mount('/',StaticFiles(directory=f'{A}/static'),name='static')
