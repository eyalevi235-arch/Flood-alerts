"""Rain-grid -> hydrograph at a point: rain-weighted time-area (width-function) routing.
Runoff: SCS-CN per DEM cell (gis/curve_number.tif if present, else uniform CN_DESERT), Ia = LAMBDA*S,
 event P accumulated per cell (reset after DRY_RESET h without rain), times an intensity factor
 fi = clip((i - I0)/(I1 - I0), 0, 1) on the hourly rate (Hortonian: low-intensity rain soaks in).
Excess from each cell arrives at the point after tt_s (travel_time.catchment). Output 10-min hydrograph Q (m3/s)."""
import numpy as np,pandas as pd,os,rasterio
import travel_time as tt
D=os.path.dirname(os.path.abspath(__file__)); CNF=os.path.join(D,'..','gis','curve_number.tif')
P=dict(CN_DESERT=90.,LAMBDA=0.05,I0=0.3,I1=3.0,DRY_RESET=24,QMIN=0.5,QREL=0.03,DT_MIN=10,CN_BIN=5)
def cn_for(z,cnd=None):
    cnd=cnd or P['CN_DESERT']
    if not os.path.exists(CNF): return np.full(len(z['rows']),cnd,'float32'),'uniform'
    g=tt.grids(); x,y=g['tr']*(z['cols']+0.5,z['rows']+0.5); s=rasterio.open(CNF); c,r=~s.transform*(x,y)
    r=np.clip(r.astype(int),0,s.height-1); c=np.clip(c.astype(int),0,s.width-1); a=s.read(1)[r,c].astype('float32')
    a[~np.isfinite(a)|(a<=0)|(a>100)]=cnd; return a,'curve_number.tif'
def scs(Pc,CN,lam=None):
    S=25400/CN-254; Ia=(P['LAMBDA'] if lam is None else lam)*S; return np.where(Pc>Ia,(Pc-Ia)**2/(Pc-Ia+S),0)
def route(g,z,t0,t1,par=None):
    """g: grid_features.Grid; z: catchment; [t0,t1] UTC window of rain to use."""
    p={**P,**(par or {})}; gt=g.tr; x,y=tt.grids()['tr']*(z['cols']+0.5,z['rows']+0.5)
    c,r=~gt*(x,y); r=np.clip(r.astype(int),0,g.shape[0]-1); c=np.clip(c.astype(int),0,g.shape[1]-1)
    cn,cnsrc=cn_for(z,p['CN_DESERT']); cnb=np.round(cn/p['CN_BIN'])*p['CN_BIN']; lag=(z['tt_s']/60/p['DT_MIN']).astype(int)
    a=g.t.searchsorted(pd.Timestamp(t0)); b=g.t.searchsorted(pd.Timestamp(t1),'right'); T=g.t[a:b]
    if len(T)==0: return None
    key=pd.DataFrame(dict(r=r,c=c,cn=cnb)); grp=key.groupby(['r','c','cn']).ngroup().values; G=key.groupby(['r','c','cn']).first().reset_index()
    rain=np.diff(g.cs[a:b+1][:,G.r.values,G.c.values],axis=0)   # [T,groups] mm per step
    step=g.step; rate=rain/step
    # event cumulative with reset after dry spell
    Pc=np.zeros_like(rain); acc=np.zeros(rain.shape[1]); dry=np.zeros(rain.shape[1])
    for i in range(len(rain)):
        dry=np.where(rain[i]>0.1,0,dry+step); acc=np.where(dry>=p['DRY_RESET'],0,acc)+rain[i]; Pc[i]=acc
    Q=scs(Pc,G.cn.values[None],p['LAMBDA']); dQ=np.diff(np.vstack([np.zeros((1,Q.shape[1])),Q]),axis=0)
    dQ[np.r_[False,(np.diff(Pc,axis=0)<0).any(1)]]=np.maximum(dQ[np.r_[False,(np.diff(Pc,axis=0)<0).any(1)]],0)
    dQ=np.maximum(dQ,0)*np.clip((rate-p['I0'])/(p['I1']-p['I0']),0,1)   # mm excess per step
    nsub=int(step*60/p['DT_MIN']); nb=len(T)*nsub+lag.max()+2; H=np.zeros(nb)
    # per group: lag histogram weighted by area
    for gi in range(len(G)):
        m=grp==gi; ex=dQ[:,gi]
        if not ex.any(): continue
        lh=np.bincount(lag[m],weights=z['cellkm2'][m]); exs=np.repeat(ex/nsub,nsub)   # spread step excess uniformly
        H[:len(exs)+len(lh)-1]+=np.convolve(exs,lh)
    Qs=H*1000/(p['DT_MIN']*60)   # mm*km2 per bin -> m3/s
    times=T[0]-pd.Timedelta(hours=step)+pd.to_timedelta(np.arange(nb)*p['DT_MIN'],'min')
    o=dict(times=times,Q=Qs,cn_source=cnsrc,runoff_mm=float((dQ.sum(0)*np.bincount(grp,weights=z['cellkm2'])).sum()/z['area_km2']),
           rain_mm=float((rain.sum(0)*np.bincount(grp,weights=z['cellkm2'])).sum()/z['area_km2']),
           imax_cell=float(rate.max()) if rate.size else 0.)
    pk=int(Qs.argmax()); thr=max(p['QMIN'],p['QREL']*Qs[pk])
    o['qpeak']=float(Qs[pk]); o['first']=times[int(np.argmax(Qs>=thr))] if Qs[pk]>=p['QMIN'] else None; o['peak']=times[pk] if Qs[pk]>=p['QMIN'] else None
    # contributing sub-areas: runoff share by travel-time band + top rain cells
    exg=dQ.sum(0); w=np.bincount(grp,weights=z['cellkm2']); vol=exg*w
    band=pd.cut(z['tt_s']/3600,[-1,1,3,6,12,99],labels=['<1h','1-3h','3-6h','6-12h','>12h'])
    cv=exg[grp]*z['cellkm2']; s=pd.Series(cv).groupby(band,observed=False).sum(); o['contrib_by_tt']={k:round(float(v/max(cv.sum(),1e-9)),2) for k,v in s.items()}
    top=np.argsort(vol)[::-1][:3]; lx,ly=gt*(G.c.values+0.5,G.r.values+0.5)
    o['top_cells']=[dict(lat=round(float(ly[i]),3),lon=round(float(lx[i]),3),share=round(float(vol[i]/max(vol.sum(),1e-9)),2),
                         tt_h=round(float(np.median(z['tt_s'][grp==i])/3600),1)) for i in top if vol[i]>0]
    return o
