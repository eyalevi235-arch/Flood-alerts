"""Live forecast risk layer: per desert basin, max calibrated probability over next 48h (alert_engine.model_prob) -> data/risk_live.geojson"""
import sys,os,json,time,pandas as pd,numpy as np
R='/workspace/flood'; sys.path.insert(0,f'{R}/arrival')
def build(g,now,hours=48,out=f'{R}/app/data/risk_live.geojson',limit=None):
    import alert_engine as ae, travel_time as tt
    B=json.load(open(f'{R}/gis/station_basins.geojson')); feats=[]; t0=time.time(); n=0
    for f in B['features']:
        p=f['properties']; q=dict(p,risk=None,risk_live=None,eta_peak_rain=None,model='live')
        if p.get('desert') and not p.get('perennial') and p.get('olat') and (limit is None or n<limit):
            n+=1
            try:
                z=tt.catchment(p['olat'],p['olon']); pr,T,row=ae.model_prob(g,z,f"b{p['sid']}",p['olat'],p['olon'],now,now+pd.Timedelta(hours=hours))
                r24=(row or {}).get('pd_r24',0)/ae.PDIR_UNITS
                pr=0.0 if r24<ae.DRY_MM else pr   # dry gate, as in alert_engine
                q.update(risk=round(pr,3),risk_live=round(pr,3),event_rain_mm=round(float(r24),1),eta_peak_rain=ae.il(T) if T is not None else None)
            except Exception as e: q['error']=type(e).__name__
        feats.append(dict(f,properties=q))
    o=dict(type='FeatureCollection',issued=ae.il(now),hours=hours,source=getattr(g,'name','forecast'),features=feats)
    json.dump(o,open(out+'.tmp','w'),ensure_ascii=False,default=str); os.replace(out+'.tmp',out)
    print(f'live risk: {n} basins in {time.time()-t0:.0f}s',flush=True); return o
if __name__=='__main__':
    os.chdir(f'{R}/arrival'); import alert_engine as ae
    g=ae.fc.openmeteo_grid('icon_seamless'); now=pd.Timestamp.now('UTC').tz_localize(None).floor('h')
    build(g,now,limit=int(sys.argv[1]) if len(sys.argv)>1 else None)
