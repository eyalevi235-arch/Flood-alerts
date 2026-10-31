"""Lightweight flood alert engine for GitHub Actions (no rasters). Port of /arrival/alert_engine.py + routing.py + app/live_risk.py
using precomputed per-point tables (data/catchments.json) on the fixed Open-Meteo 0.1deg grid.
Pipeline: Open-Meteo hourly precip grid -> basin rain features -> LightGBM (desert PDIR-feature model) + Platt -> dry gate
          -> rain-weighted time-area routing with SCS-CN -> first wave / peak ETA."""
import os,json,time,numpy as np,pandas as pd,requests,lightgbm as lgb
ROOT=os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
CAT=json.load(open(f'{ROOT}/data/catchments.json'))
LAT=np.array(CAT['grid']['lat']); LON=np.array(CAT['grid']['lon']); RES=CAT['grid']['res']; P=CAT['routing_params']
CAL=json.load(open(f'{ROOT}/model/calibration.json'))
BOOST=lgb.Booster(model_file=f'{ROOT}/model/desert_pdir_radar_np.txt'); FEAT=BOOST.feature_name()
DRY_MM=float(os.environ.get('DRY_MM',5.))   # same as arrival/alert_engine.py (see model/alert_calibration.json for tuning work)
VP=pd.read_csv(f'{ROOT}/data/viewpoints.csv')
X0,Y0=LON[0]-RES/2,LAT[0]+RES/2
def cell_ll(r,c): return Y0-RES*(np.asarray(r)+0.5), X0+RES*(np.asarray(c)+0.5)
class Grid:
    def __init__(s,times,data,step_h,name):
        s.t=pd.DatetimeIndex(times); s.step=step_h; s.name=name; s.shape=data.shape[1:]
        cs=np.empty((len(data)+1,)+data.shape[1:],'float32'); cs[0]=0; np.cumsum(np.nan_to_num(data),0,out=cs[1:]); s.cs=cs
    def wsum(s,T,h):
        if h<s.step: return None
        b=s.t.searchsorted(pd.Timestamp(T),'right'); a=s.t.searchsorted(pd.Timestamp(T)-pd.Timedelta(hours=h),'right'); return s.cs[b]-s.cs[a]
def _get(url,params,tries=4):
    for k in range(tries):
        try:
            r=requests.get(url,params=params,timeout=60)
            if r.status_code==200: return r.json()
        except requests.RequestException: pass
        time.sleep(5*(k+1))
    r.raise_for_status()
def openmeteo_grid(model='icon_seamless',days=3,chunk=150):
    la,lo=np.meshgrid(LAT,LON,indexing='ij'); la=la.ravel(); lo=lo.ravel(); out=[]
    for i in range(0,len(la),chunk):
        p=dict(latitude=','.join(map(str,la[i:i+chunk])),longitude=','.join(map(str,lo[i:i+chunk])),hourly='precipitation',models=model,timezone='GMT',forecast_days=days,past_days=1)
        j=_get('https://api.open-meteo.com/v1/forecast',p); j=j if isinstance(j,list) else [j]
        out+=[np.array([np.nan if v is None else v for v in x['hourly']['precipitation']],dtype='float32') for x in j]; t=pd.to_datetime(j[0]['hourly']['time'])
    R=np.stack(out,1).reshape(len(t),len(LAT),len(LON)); R[~np.isfinite(R)]=0
    return Grid(t,R,1,f'openmeteo_{model}')
def features(g,m,T):
    rr,cc,w,near=np.array(m['r']),np.array(m['c']),np.array(m['w']),np.array(m['near'],bool); o={}
    for h in (1,3,6,12,24,72,168):
        a=g.wsum(T,h); o[f'r{h}' if h<168 else 'ante7d']=np.nan if a is None else float(a[rr,cc].mean())
    v=g.wsum(T,24)[rr,cc]
    o.update(cmax24=float(v.max()),f5=float((v>5).mean()),f10=float((v>10).mean()),f20=float((v>20).mean()),rw24=float((v*w).sum()),near24=float(v[near].mean()))
    b=g.t.searchsorted(pd.Timestamp(T),'right'); n=max(int(24/g.step),1); s=np.diff(g.cs[max(b-n,0):b+1][:,rr,cc],axis=0).mean(1)
    o['imax']=float(s.max()/g.step) if len(s) else 0.0; return o
def platt(s): q=np.clip(s,1e-4,1-1e-4); return 1/(1+np.exp(-(CAL['platt_a']*np.log(q/(1-q))+CAL['platt_b'])))
def model_prob(g,z,lat,lon,T0,T1):
    st=dict(area=z['area_km2'],elev=z['elev'],relief=z['relief']); Ts=g.t[(g.t>=T0)&(g.t<=T1)]
    if not len(Ts): return (-1,None,None)
    rows=[]
    for T in Ts:
        f=features(g,z['mask'],T); doy=T.dayofyear
        rows.append({**{f'pd_{k}':v for k,v in f.items()},**st,'lat':lat,'lon':lon,'doy_s':np.sin(2*np.pi*doy/365),'doy_c':np.cos(2*np.pi*doy/365)})
    p=platt(BOOST.predict(pd.DataFrame(rows)[FEAT])); i=int(np.argmax(p)); return float(p[i]),Ts[i],rows[i]
def scs(Pc,CN,lam):
    S=25400/CN-254; Ia=lam*S; return np.where(Pc>Ia,(Pc-Ia)**2/(Pc-Ia+S),0)
def route(g,z,t0,t1):
    p=P; G=z['groups']; r=np.array([x['r'] for x in G]); c=np.array([x['c'] for x in G]); cn=np.array([x['cn'] for x in G])
    area=np.array([sum(x['band']) for x in G]); band=np.array([x['band'] for x in G])
    a=g.t.searchsorted(pd.Timestamp(t0)); b=g.t.searchsorted(pd.Timestamp(t1),'right'); T=g.t[a:b]
    if len(T)==0: return None
    rain=np.diff(g.cs[a:b+1][:,r,c],axis=0); step=g.step; rate=rain/step
    Pc=np.zeros_like(rain); acc=np.zeros(rain.shape[1]); dry=np.zeros(rain.shape[1])
    for i in range(len(rain)):
        dry=np.where(rain[i]>0.1,0,dry+step); acc=np.where(dry>=p['DRY_RESET'],0,acc)+rain[i]; Pc[i]=acc
    Q=scs(Pc,cn[None],p['LAMBDA']); dQ=np.diff(np.vstack([np.zeros((1,Q.shape[1])),Q]),axis=0)
    dQ=np.maximum(dQ,0)*np.clip((rate-p['I0'])/(p['I1']-p['I0']),0,1)
    nsub=int(step*60/p['DT_MIN']); maxlag=max(x['lag0']+len(x['lagh'])-1 for x in G); nb=len(T)*nsub+maxlag+2; H=np.zeros(nb)
    for gi,x in enumerate(G):
        ex=dQ[:,gi]
        if not ex.any(): continue
        lh=np.r_[np.zeros(x['lag0']),x['lagh']]; exs=np.repeat(ex/nsub,nsub); H[:len(exs)+len(lh)-1]+=np.convolve(exs,lh)
    Qs=H*1000/(p['DT_MIN']*60); times=T[0]-pd.Timedelta(hours=step)+pd.to_timedelta(np.arange(nb)*p['DT_MIN'],'min')
    o=dict(times=times,Q=Qs,cn_source=z.get('cn_source'),runoff_mm=float((dQ.sum(0)*area).sum()/z['area_km2']),
           rain_mm=float((rain.sum(0)*area).sum()/z['area_km2']),imax_cell=float(rate.max()) if rate.size else 0.)
    pk=int(Qs.argmax()); thr=max(p['QMIN'],p['QREL']*Qs[pk]); o['qpeak']=float(Qs[pk])
    o['first']=times[int(np.argmax(Qs>=thr))] if Qs[pk]>=p['QMIN'] else None; o['peak']=times[pk] if Qs[pk]>=p['QMIN'] else None
    exg=dQ.sum(0); cv=(exg[:,None]*band).sum(0); tot=max(cv.sum(),1e-9)
    o['contrib_by_tt']={k:round(float(v/tot),2) for k,v in zip(['<1h','1-3h','3-6h','6-12h','>12h'],cv)}
    vol=exg*area; top=np.argsort(vol)[::-1][:3]; ly,lx=cell_ll(r,c)
    o['top_cells']=[dict(lat=round(float(ly[i]),3),lon=round(float(lx[i]),3),share=round(float(vol[i]/max(vol.sum(),1e-9)),2),tt_h=G[i]['tt_med_h']) for i in top if vol[i]>0]
    return o
def il(t): return None if t is None else pd.Timestamp(t).tz_localize('UTC').tz_convert('Asia/Jerusalem').strftime('%Y-%m-%d %H:%M')
def evaluate_points(g,now,horizon_h=72):
    """All viewpoints, threshold-free (per-user thresholds applied at notify time / in the browser)."""
    out=[]; T1=now+pd.Timedelta(hours=horizon_h)
    for v in VP.itertuples():
        z=CAT['points'].get(v.id)
        if z is None: continue
        lat,lon=v.snap_lat,v.snap_lon; p,Tp,row=model_prob(g,z,lat,lon,now,T1); r=route(g,z,now-pd.Timedelta(hours=24),T1)
        p=max(p,0)*min(1.0,max(row['pd_r24'] if row else 0,r['rain_mm'] if r else 0)/DRY_MM)
        eta1=r['first'] if r else None; etap=r['peak'] if r else None
        if eta1 is None and p>=0.05 and Tp is not None:
            eta1=Tp+pd.Timedelta(seconds=z['tt_p10_s']); etap=Tp+pd.Timedelta(seconds=z['tt_med_s'])
        lead=(eta1-now).total_seconds()/3600 if eta1 is not None else None
        conf='low' if (lead is None or lead>36 or (r and r['qpeak']<1)) else ('high' if p>=0.5 and lead<12 else 'medium')
        a=dict(point=v.id,name=v.name_he,nahal=v.nahal,prob=round(p,2),eta_first_wave=il(eta1),eta_peak=il(etap),hours_until_first_wave=round(lead,1) if lead is not None else None,
               rain_summary=dict(basin_mean_mm=round(r['rain_mm'],1),max_cell_mm_h=round(r['imax_cell'],1),runoff_mm=round(r['runoff_mm'],2),q_peak_m3s=round(r['qpeak'],1),
                   contributing_by_travel_time=r['contrib_by_tt'],top_rain_cells=r['top_cells'],cn_source=r['cn_source'],model_r24_mm=round(row['pd_r24'],1) if row else None) if r else {},
               confidence=conf,source=g.name,issued=il(now),basin_km2=round(z['area_km2'],1))
        if a['prob']<0.05: a.update(eta_first_wave=None,eta_peak=None,hours_until_first_wave=None)   # as server._clean
        out.append(a)
    return out
def live_risk(g,now,basins_geojson,hours=48):
    B=json.load(open(basins_geojson)); feats=[]; n=0
    for f in B['features']:
        p=f['properties']; q=dict(p,risk=None,risk_live=None,eta_peak_rain=None,model='live'); z=CAT['basins'].get(str(p.get('sid')))
        if z is not None:
            n+=1
            try:
                pr,T,row=model_prob(g,z,p['olat'],p['olon'],now,now+pd.Timedelta(hours=hours)); r24=(row or {}).get('pd_r24',0)
                pr=0.0 if r24<DRY_MM else pr
                q.update(risk=round(pr,3),risk_live=round(pr,3),event_rain_mm=round(float(r24),1),eta_peak_rain=il(T) if T is not None else None)
            except Exception as e: q['error']=type(e).__name__
        feats.append(dict(f,properties=q))
    return dict(type='FeatureCollection',issued=il(now),hours=hours,source=g.name,features=feats),n
_BASIN_META=None
_FCACHE={}
def basin_meta(sid):
    global _BASIN_META
    if _BASIN_META is None:
        B=json.load(open(f'{ROOT}/data/basins_simplified.geojson'))
        _BASIN_META={}
        for f in B['features']:
            p=f['properties']
            _BASIN_META[str(p.get('sid'))]=dict(name=p.get('name_he') or '',nahal=p.get('main_nahal') or '',olat=p.get('olat'),olon=p.get('olon'))
    return _BASIN_META.get(str(sid),{})
def evaluate_basin(g,now,sid,horizon_h=72):
    """One modeled basin, memoized. eta is the outlet arrival (Timestamp or None)."""
    sid=str(sid)
    if sid in _FCACHE: return _FCACHE[sid]
    z=CAT['basins'].get(sid)
    if z is None:
        _FCACHE[sid]=None; return None
    meta=basin_meta(sid)
    try:
        lat,lon=float(meta.get('olat') or 0),float(meta.get('olon') or 0)
        T1=now+pd.Timedelta(hours=horizon_h)
        p,Tp,row=model_prob(g,z,lat,lon,now,T1)
        r=route(g,z,now-pd.Timedelta(hours=24),T1)
        p=max(p,0)*min(1.0,max(row['pd_r24'] if row else 0,r['rain_mm'] if r else 0)/DRY_MM)
        eta=r['first'] if r else None
        if eta is None and p>=0.05 and Tp is not None: eta=Tp+pd.Timedelta(seconds=z['tt_p10_s'])
        rain=round(r['rain_mm'],1) if r else None
    except Exception:
        _FCACHE[sid]=None; return None
    out=dict(prob=round(float(p),2),eta=eta,tt_med_h=float(z['tt_med_s'])/3600.0,rain=rain,name=meta.get('name') or sid,nahal=meta.get('nahal') or '')
    _FCACHE[sid]=out
    return out
def scale_arrival(eta_outlet,now,tt_med_h,along):
    """along is 0 at the divide and 1 at the outlet. The outlet wave is earlier upstream by the remaining travel."""
    along=min(1.0,max(0.0,float(along)))
    if eta_outlet is None: return None,None
    eta=eta_outlet-pd.Timedelta(hours=tt_med_h*(1.0-along))
    lead=(eta-now).total_seconds()/3600.0
    if lead<0: lead=0.0
    return eta,round(lead,1)
def custom_point_alert(g,now,c):
    fc=evaluate_basin(g,now,c.get('sid'))
    if not fc: return None
    eta,lead=scale_arrival(fc['eta'],now,fc['tt_med_h'],c.get('along',1))
    if fc['prob']<0.05: lead=None; eta=None
    return dict(point=c['id'],name='הנקודה שלי · '+(fc['name'] or ''),nahal=fc['nahal'] or 'נחל',prob=fc['prob'],
        eta_first_wave=il(eta),eta_peak=None,hours_until_first_wave=lead,
        rain_summary=dict(basin_mean_mm=fc['rain'],max_cell_mm_h=None),confidence='low',estimate=True,source='custom_point')
