"""Per-cell travel time to a point on the GLO-90 D8 grid (gis/fdir.tif, acc.tif, dem.tif).
Velocity: channel cells (A>=A_CH km2): v = VC*(S/0.01)^0.3*(A/100)^0.15, clip [0.5,5] m/s
          hillslope cells: v = VH*(S/0.1)^0.5, clip [0.05,0.6] m/s.  VC,VH calibrated in calibrate.py.
catchment(lat,lon) -> dict(rows,cols,len_m (flow length to point),tt_s (travel time),A_km2,lat,lon); cached in cache/."""
import numpy as np,rasterio,os,hashlib
from affine import Affine
D=os.path.dirname(os.path.abspath(__file__)); R=os.path.join(D,'..','gis')
PAR=dict(VC=3.5,VH=0.15,A_CH=0.5)
_g={}
def grids():
    if not _g:
        s=rasterio.open(f'{R}/fdir.tif'); _g['tr']=s.transform; _g['shape']=s.shape
        _g['fd']=np.load(f'{R}/fdir.npy',mmap_mode='r'); _g['acc']=np.load(f'{R}/acc.npy',mmap_mode='r')
        _g['dem']=rasterio.open(f'{R}/dem.tif').read(1,out_dtype='float32')
    return _g
DR={64:(-1,0),128:(-1,1),1:(0,1),2:(1,1),4:(1,0),8:(1,-1),16:(0,-1),32:(-1,-1)}
def snap(lat,lon,rad=3):
    g=grids(); c,r=~g['tr']*(lon,lat); r,c=int(r),int(c); w=g['acc'][r-rad:r+rad+1,c-rad:c+rad+1]
    i,j=np.unravel_index(np.argmax(w),w.shape); return r-rad+i,c-rad+j
def _upstream(r0,c0):
    """BFS upstream on D8 (cells whose receiver is in the set)."""
    g=grids(); fd=g['fd']; H,W=g['shape']; seen={(r0,c0)}; fr=[(r0,c0)]; out=[(r0,c0)]
    nb=[(dr,dc,code) for code,(dr,dc) in DR.items()]
    while fr:
        R_=np.array(fr); nxt=[]
        for code,(dr,dc) in DR.items():   # neighbour at (r-dr,c-dc) drains into (r,c) if its code==code
            rr=R_[:,0]-dr; cc=R_[:,1]-dc; ok=(rr>=0)&(rr<H)&(cc>=0)&(cc<W); rr,cc=rr[ok],cc[ok]
            m=np.asarray(fd[rr,cc])==code
            for a,b in zip(rr[m],cc[m]):
                if (a,b) not in seen: seen.add((a,b)); nxt.append((a,b))
        out+=nxt; fr=nxt
    return np.array(out)
def catchment(lat,lon,par=None,snapped=False):
    par=par or PAR; g=grids()
    r0,c0=(lambda c,r:(int(r),int(c)))(*(~g['tr']*(lon,lat))) if snapped else snap(lat,lon)
    key=os.path.join(D,'cache',f'c_{r0}_{c0}.npz')
    if os.path.exists(key): z=dict(np.load(key))
    else:
        rc=_upstream(r0,c0); rows,cols=rc[:,0],rc[:,1]
        code=np.asarray(g['fd'][rows,cols]); dr=np.array([DR.get(int(k),(0,0))[0] for k in code]); dc=np.array([DR.get(int(k),(0,0))[1] for k in code])
        lat_c=g['tr'].f+g['tr'].e*(rows+0.5); dx=abs(g['tr'].a)*111320*np.cos(np.radians(lat_c)); dy=abs(g['tr'].e)*110570
        L=np.hypot(dr*dx,dc*dy); L[0]=0
        idx={(a,b):i for i,(a,b) in enumerate(zip(rows,cols))}
        down=np.array([idx.get((a+x,b+y),-1) for a,b,x,y in zip(rows,cols,dr,dc)]); down[0]=-1
        z0=g['dem'][rows,cols]; dz=np.where(down>=0,z0-z0[np.maximum(down,0)],0)
        z=dict(rows=rows,cols=cols,down=down,L=L,S=np.clip(dz/np.maximum(L,1),0.001,1),
               A=np.asarray(g['acc'][rows,cols]).astype('float32')*(dx*dy/1e6),cellkm2=(dx*dy/1e6).astype('float32'))
        np.savez_compressed(key,**z)
    ch=z['A']>=par['A_CH']
    v=np.where(ch,np.clip(par['VC']*(z['S']/0.01)**0.3*(z['A']/100)**0.15,0.5,5),np.clip(par['VH']*(z['S']/0.1)**0.5,0.05,0.6))
    t=z['L']/v; t[0]=0; ln=z['L'].copy(); n=z['down'].copy()
    while (n>=0).any():   # pointer doubling: sum along downstream path
        k=n>=0; t[k]+=t[n[k]]; ln[k]+=ln[n[k]]; n=np.where(k,n[np.maximum(n,0)],-1)
    z.update(tt_s=t,len_m=ln,ch=ch,r0=r0,c0=c0,area_km2=float(z['cellkm2'].sum())); return z
def time_between(up,down,par=None):
    """Travel time (h) from upstream point to downstream point (up must be in down's catchment)."""
    z=catchment(*down,par=par); r,c=snap(*up); k=np.nonzero((z['rows']==r)&(z['cols']==c))[0]
    return float(z['tt_s'][k[0]]/3600) if len(k) else np.nan
