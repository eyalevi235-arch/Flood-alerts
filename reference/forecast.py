"""Open-Meteo forecast adapter (free, no key) -> grid_features.Grid (mm per hour, UTC end-of-step).
live:   api.open-meteo.com/v1/forecast            (models: icon_seamless = ICON-D2 -> ICON-EU -> ICON global; ecmwf_ifs025; best_match)
replay: historical-forecast-api.open-meteo.com   (archived forecasts of the same models, for back-testing)
Grid: 0.1 deg over Israel + upstream (Sinai/Jordan edge) 29.4-33.4N, 34.2-36.0E. Cached in cache/om_*.npz."""
import numpy as np,pandas as pd,requests,os,time,sys
sys.path.insert(0,os.path.join(os.path.dirname(os.path.abspath(__file__)),'..'))
import grid_features as gf
from affine import Affine
D=os.path.dirname(os.path.abspath(__file__))
LAT=np.round(np.arange(33.4,29.39,-0.1),2); LON=np.round(np.arange(34.2,36.01,0.1),2); RES=0.1
def _get(url,params,tries=4):
    for k in range(tries):
        r=requests.get(url,params=params,timeout=60)
        if r.status_code==200: return r.json()
        time.sleep(5*(k+1))
    r.raise_for_status()
def openmeteo_grid(model='icon_seamless',start=None,end=None,days=3,chunk=150,cache=True):
    hist=start is not None
    key=os.path.join(D,'cache',f"om_{model}_{start or pd.Timestamp.now("UTC").strftime('%Y%m%d%H')}_{end or days}.npz".replace(':','').replace(' ',''))
    if cache and os.path.exists(key):
        z=np.load(key,allow_pickle=True); t=pd.DatetimeIndex(z['t'])
    else:
        la,lo=np.meshgrid(LAT,LON,indexing='ij'); la=la.ravel(); lo=lo.ravel(); out=[]
        url='https://historical-forecast-api.open-meteo.com/v1/forecast' if hist else 'https://api.open-meteo.com/v1/forecast'
        for i in range(0,len(la),chunk):
            p=dict(latitude=','.join(map(str,la[i:i+chunk])),longitude=','.join(map(str,lo[i:i+chunk])),hourly='precipitation',models=model,timezone='GMT')
            if hist: p.update(start_date=start,end_date=end)
            else: p.update(forecast_days=days,past_days=1)
            j=_get(url,p); j=j if isinstance(j,list) else [j]
            out+= [np.array(x['hourly']['precipitation'],dtype='float32') for x in j]; t=pd.to_datetime(j[0]['hourly']['time'])
        R=np.stack(out,1).reshape(len(t),len(LAT),len(LON)); R[~np.isfinite(R)]=0
        np.savez_compressed(key,t=t.values,R=R)
        z=dict(R=R)
    R=z['R']
    # open-meteo hourly precipitation = sum over preceding hour, labelled at hour end -> matches Grid convention
    return gf.Grid(t,R,Affine(RES,0,LON[0]-RES/2,0,-RES,LAT[0]+RES/2),1,f'openmeteo_{model}')
def radar_grid(hours=3,root='/workspace/flood/raw/ims_radar'):
    """IMS radar from the live archive (tools/live_poller.py). Filenames are ISRAEL LOCAL time -> converted to UTC
    by radar_to_mmh.png_time_utc. Returns grid_features.Grid (UTC, mm per 5 min, 0.01deg WGS84) for the last `hours`."""
    import sys,glob; sys.path.insert(0,'/workspace/flood/tools'); import radar_to_mmh as RM
    fs=sorted(glob.glob(f'{root}/*/IMSRadar4GIS_*_0.png'))
    if not fs: raise FileNotFoundError('no radar frames')
    t1=RM.png_time_utc(fs[-1]); fs=[f for f in fs if RM.png_time_utc(f)>t1-pd.Timedelta(hours=hours)]
    return RM.grid_from_pngs(fs)
if __name__=='__main__':
    g=openmeteo_grid(); print(g.name,g.t[0],g.t[-1],g.shape,float(g.cs[-1].max()))
