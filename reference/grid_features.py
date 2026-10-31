"""Radar-compatible basin features from ANY gridded precipitation source.
Interface:  Grid = (times[T] UTC end-of-step, data[T,ny,nx] mm per step, Affine transform (WGS84), step_h)
            basin_features(grid, basin_feature, T) -> dict, uses only data with time <= T (real-time safe)
Adapters:   load_chirps() daily 0.05deg, load_pdir() hourly 0.04deg, radar_from_frames() IMS radar 5-10 min ~1 km.
Features (same names for every source; windows shorter than the step -> NaN):
  r1,r3,r6,r12,r24,r72 basin-mean accumulations ending at T; ante7d (168h); imax = max basin-mean rate mm/h at native step, last 24h
  cmax24 = max cell 24h sum; f5,f10,f20 = fraction of basin cells with 24h sum > 5/10/20 mm
  rw24 = 24h sum weighted toward the outlet w=1/(1+d/dmed); near24 = mean over the outlet-half of the basin
"""
import numpy as np,pandas as pd,glob,os
_ROOT=os.path.dirname(os.path.abspath(__file__))
from rasterio import features as rf
from affine import Affine
class Grid:
    def __init__(s,times,data,transform,step_h,name):
        s.t=pd.DatetimeIndex(times); s.tr=transform; s.step=step_h; s.name=name; s.shape=data.shape[1:]
        cs=np.empty((len(data)+1,)+data.shape[1:],'float32'); cs[0]=0; np.cumsum(np.nan_to_num(data),0,out=cs[1:]); s.cs=cs  # memory: only cumsum kept
        s.masks={}
    def wsum(s,T,h):
        if h<s.step: return None
        b=s.t.searchsorted(pd.Timestamp(T),'right'); a=s.t.searchsorted(pd.Timestamp(T)-pd.Timedelta(hours=h),'right')
        return s.cs[b]-s.cs[a]
def load_chirps():
    T=[];R=[]
    for f in sorted(glob.glob(os.path.join(_ROOT,'raw/chirps_cog/*.npz'))):
        z=np.load(f,allow_pickle=True); T+=list(pd.to_datetime(z['dates'])+pd.Timedelta(days=1)); R.append(z['rain'].astype('float32'))
    R=np.concatenate(R); R[R<0]=0; o=np.argsort(T); T=pd.DatetimeIndex(T)[o]; R=R[o]
    full=pd.date_range(T.min(),T.max(),freq='D'); D=np.zeros((len(full),)+R.shape[1:],'float32'); D[full.searchsorted(T)]=R
    return Grid(full,D,Affine(0.05,0,34.0,0,-0.05,33.5),24,'chirps')
def load_pdir(start='2020-10-01'):
    fs=sorted(glob.glob(os.path.join(_ROOT,'raw/pdir/*.npy'))); ts=pd.to_datetime([f[-14:-4] for f in fs],format='%Y%m%d%H')+pd.Timedelta(hours=1)
    k=ts>=pd.Timestamp(start); fs=[f for f,o in zip(fs,k) if o]; ts=ts[k]
    full=pd.date_range(ts.min(),ts.max(),freq='h'); D=np.zeros((len(full),113,64),'float32')
    for i,f in zip(full.searchsorted(ts),fs): a=np.load(f).astype("float32")/100.; a[a<0]=0; D[i]=a
    np.cumsum(D,0,out=D); g=Grid.__new__(Grid); g.t=full; g.tr=Affine(0.04,0,34.0,0,-0.04,33.52); g.step=1; g.name='pdir'; g.shape=D.shape[1:]; g.masks={}
    g.cs=np.concatenate([np.zeros((1,)+D.shape[1:],'float32'),D]); del D; return g
    return Grid(full,D,Affine(0.04,0,34.0,0,-0.04,33.52),1,'pdir')
def radar_from_frames(times,frames,transform,step_min):
    """IMS radar adapter: frames[T,ny,nx] = mm accumulated per step (dBZ -> R=(10^(dBZ/10)/200)^(1/1.6) mm/h, x step/60), regridded to WGS84 with Affine transform."""
    return Grid(times,np.asarray(frames,'float32'),transform,step_min/60,'radar')
def basin_mask(g,feat):
    p=feat['properties']; sid=p['sid']
    if sid in g.masks: return g.masks[sid]
    m=rf.rasterize([(feat['geometry'],1)],out_shape=g.shape,transform=g.tr,all_touched=True).astype(bool)
    if m.sum()==0:
        c,r=~g.tr*(p['olon'],p['olat']); m[int(np.clip(r,0,m.shape[0]-1)),int(np.clip(c,0,m.shape[1]-1))]=True
    rr,cc=np.nonzero(m); x,y=g.tr*(cc+0.5,rr+0.5); d=np.hypot((x-p['olon'])*np.cos(np.radians(p['olat'])),y-p['olat'])*111
    w=1/(1+d/max(np.median(d),1)); g.masks[sid]=(rr,cc,w/w.sum(),d<=np.median(d)); return g.masks[sid]
def basin_mean_series(g,feat):
    rr,cc,_,_=basin_mask(g,feat); return np.diff(g.cs[:,rr,cc],axis=0).mean(1)
def basin_features(g,feat,T):
    rr,cc,w,near=basin_mask(g,feat); o={}
    for h in (1,3,6,12,24,72,168):
        a=g.wsum(T,h); o[f'r{h}' if h<168 else 'ante7d']=np.nan if a is None else float(a[rr,cc].mean())
    v=g.wsum(T,24)[rr,cc]
    o.update(cmax24=float(v.max()),f5=float((v>5).mean()),f10=float((v>10).mean()),f20=float((v>20).mean()),rw24=float((v*w).sum()),near24=float(v[near].mean()))
    b=g.t.searchsorted(pd.Timestamp(T),'right'); n=max(int(24/g.step),1); s=np.diff(g.cs[max(b-n,0):b+1][:,rr,cc],axis=0).mean(1)
    o['imax']=float(s.max()/g.step) if len(s) else 0.0
    return o
GF=['r1','r3','r6','r12','r24','r72','ante7d','imax','cmax24','f5','f10','f20','rw24','near24']

def load_pdir_window(t0,t1):
    """PDIR grid for [t0,t1] (UTC). Returns (Grid, coverage = share of hours with a file)."""
    full=pd.date_range(pd.Timestamp(t0).floor('h'),pd.Timestamp(t1).floor('h'),freq='h'); D=np.zeros((len(full),113,64),'float32'); n=0
    for i,t in enumerate(full):
        f=os.path.join(_ROOT,(t-pd.Timedelta(hours=1)).strftime('raw/pdir/%Y%m%d%H.npy'))
        try: a=np.load(f).astype("float32")/100.; a[a<0]=0; D[i]=a; n+=1
        except FileNotFoundError: pass
    return Grid(full,D,Affine(0.04,0,34.0,0,-0.04,33.52),1,'pdir'),n/len(full)
