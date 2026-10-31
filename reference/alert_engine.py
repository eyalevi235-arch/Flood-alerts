"""Flood alerts per user subscription: forecast rain grid -> flood probability (desert LightGBM, PDIR-feature model)
 -> arrival time (rain-weighted time-area routing) -> JSON alerts.
usage: alert_engine.py live [model]            current Open-Meteo forecast (default icon_seamless; also ecmwf_ifs025)
       alert_engine.py replay YYYY-MM-DD [src]  src = icon_seamless|ecmwf_ifs025 (archived forecasts) | pdir (satellite, as 'forecast')
Subscriptions: subscriptions.json  [{"user":..,"point":"VP11","threshold":0.3} | {"user":..,"stream":"נחל צין","threshold":0.2}]"""
import sys,os,json,numpy as np,pandas as pd,lightgbm as lgb
D=os.path.dirname(os.path.abspath(__file__)); ROOT=os.path.join(D,'..'); sys.path.insert(0,ROOT); sys.path.insert(0,D)
import grid_features as gf,travel_time as tt,routing as rt,forecast as fc,rain_sources as rs
M=json.load(open(f'{ROOT}/model/desert_metrics_pdir.json'))['results']['radar_pdir_nonperennial']
BOOST=lgb.Booster(model_file=f'{ROOT}/model/desert_pdir_radar_np.txt'); FEAT=BOOST.feature_name()
PDIR_UNITS=1.; DRY_MM=5.   # grid_features now returns PDIR in mm (fixed 31.10.2026); kept as 1 for clarity
VP=pd.read_csv(f'{ROOT}/viewpoints/viewpoints.csv')
def logit(q): q=np.clip(q,1e-4,1-1e-4); return np.log(q/(1-q))
def platt(s): return 1/(1+np.exp(-(M['platt_a']*logit(s)+M['platt_b'])))
def stat(z):
    dem=tt.grids()['dem'][z['rows'],z['cols']]; return dict(area=z['area_km2'],elev=float(dem.mean()),relief=float(dem.max()-dem.min()))
def model_prob(g,z,pid,lat,lon,T0,T1):
    """max over hourly alert times T in [T0,T1] of Platt-calibrated desert-model probability; also returns argmax T and features."""
    gu=rs.scaled(g,PDIR_UNITS); x,y=tt.grids()['tr']*(z['cols']+0.5,z['rows']+0.5); c,r=~g.tr*(x,y)
    k=pd.DataFrame(dict(r=np.clip(r.astype(int),0,g.shape[0]-1),c=np.clip(c.astype(int),0,g.shape[1]-1))).drop_duplicates()
    rr,cc=k.r.values,k.c.values; gx,gy=g.tr*(cc+0.5,rr+0.5); d=np.hypot((gx-lon)*np.cos(np.radians(lat)),gy-lat)*111
    w=1/(1+d/max(np.median(d),1)); gu.masks[pid]=(rr,cc,w/w.sum(),d<=np.median(d))
    feat={'properties':{'sid':pid,'olat':lat,'olon':lon}}; st=stat(z); best=(-1,None,None)
    for T in g.t[(g.t>=T0)&(g.t<=T1)]:
        f=gf.basin_features(gu,feat,T); doy=T.dayofyear
        row={**{f'pd_{k}':v for k,v in f.items()},**st,'lat':lat,'lon':lon,'doy_s':np.sin(2*np.pi*doy/365),'doy_c':np.cos(2*np.pi*doy/365)}
        s=float(BOOST.predict(pd.DataFrame([row])[FEAT])[0]); p=float(platt(s))
        if p>best[0]: best=(p,T,row)
    return best
def interim_rule(r):
    """fallback when model unavailable: logistic on basin 24h rain & max cell intensity (documented, uncalibrated)."""
    return float(1/(1+np.exp(-(0.12*r['rain_mm']+0.25*r['imax_cell']-4))))
def il(t): return None if t is None else pd.Timestamp(t).tz_localize('UTC').tz_convert('Asia/Jerusalem').strftime('%Y-%m-%d %H:%M')
def subs_points(subs):
    out=[]
    for s in subs:
        sel=VP[VP.id==s['point']] if 'point' in s else VP[VP.nahal.str.contains(s['stream'].replace('נחל ',''),na=False)]
        out+=[(s,row) for _,row in sel.iterrows()]
    return out
def evaluate(g,subs,now,horizon_h=72,label=''):
    alerts=[]; T1=now+pd.Timedelta(hours=horizon_h); cache={}
    for s,v in subs_points(subs):
        lat,lon=v.snap_lat,v.snap_lon
        if v.id not in cache:
            z=tt.catchment(lat,lon); p,Tp,row=model_prob(g,z,v.id,lat,lon,now,T1)
            r=rt.route(g,z,now-pd.Timedelta(hours=24),T1)   # 24h spin-up of observed/analysed rain in the grid
            cache[v.id]=(z,p,Tp,row,r)
        z,p,Tp,row,r=cache[v.id]
        p=p*min(1.0,max(row['pd_r24']/PDIR_UNITS if row else 0, r['rain_mm'] if r else 0)/DRY_MM)   # dry gate: model has a ~0.1-0.4 floor with no rain
        eta1=r['first'] if r else None; etap=r['peak'] if r else None
        if eta1 is None and p>=s['threshold']:   # model says likely but routed runoff small: rain-peak + median travel time
            eta1=Tp+pd.Timedelta(seconds=float(np.percentile(z['tt_s'],10))); etap=Tp+pd.Timedelta(seconds=float(np.median(z['tt_s'])))
        lead=(eta1-now).total_seconds()/3600 if eta1 is not None else None
        conf='low' if (lead is None or lead>36 or (r and r['qpeak']<1)) else ('high' if p>=0.5 and lead<12 else 'medium')
        a=dict(user=s.get('user'),point=v.id,name=v.name_he,nahal=v.nahal,prob=round(p,2),threshold=s['threshold'],alert=bool(p>=s['threshold']),
               eta_first_wave=il(eta1),eta_peak=il(etap),hours_until_first_wave=round(lead,1) if lead is not None else None,
               rain_summary=dict(basin_mean_mm=round(r['rain_mm'],1),max_cell_mm_h=round(r['imax_cell'],1),runoff_mm=round(r['runoff_mm'],2),
                                 q_peak_m3s=round(r['qpeak'],1),contributing_by_travel_time=r['contrib_by_tt'],top_rain_cells=r['top_cells'],
                                 cn_source=r['cn_source'],model_r24_mm=round(row['pd_r24']/PDIR_UNITS,1) if row else None),
               confidence=conf,source=g.name,issued=il(now),basin_km2=round(z['area_km2'],1))
        if a['alert']: a['message_he']=f"התראת שיטפון: {v.name_he} – סיכוי {int(p*100)}%. גל ראשון צפוי בעוד כ-{a['hours_until_first_wave']} שעות ({a['eta_first_wave']}), שיא ~{a['eta_peak']}."
        alerts.append(a)
    return alerts
if __name__=='__main__':
    subs=json.load(open(f'{D}/subscriptions.json'))
    if sys.argv[1]=='live':
        m=sys.argv[2] if len(sys.argv)>2 else 'icon_seamless'; g=fc.openmeteo_grid(m); now=pd.Timestamp.now('UTC').tz_localize(None).floor('h'); tag='live'
    else:
        day=pd.Timestamp(sys.argv[2]); src=sys.argv[3] if len(sys.argv)>3 else 'icon_seamless'; now=day-pd.Timedelta(hours=12); tag=f'replay_{day.date()}_{src}'
        g=rs.pdir_window(now-pd.Timedelta(hours=30),now+pd.Timedelta(hours=60))[0] if src=='pdir' else fc.openmeteo_grid(src,start=(now-pd.Timedelta(days=1)).strftime('%Y-%m-%d'),end=(now+pd.Timedelta(days=2)).strftime('%Y-%m-%d'))
    A=evaluate(g,subs,now); json.dump(A,open(f'{D}/alerts_{tag}.json','w'),ensure_ascii=False,indent=1,default=str)
    for a in A: print(a['point'],a['nahal'],a['prob'],a['alert'],a['eta_first_wave'],a['eta_peak'],a['rain_summary']['basin_mean_mm'],a['confidence'])
