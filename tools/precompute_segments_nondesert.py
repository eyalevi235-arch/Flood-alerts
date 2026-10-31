"""Non-desert variant (A_STREAM=5 km2, outputs *_nondesert). Run on the box (needs /workspace/flood/gis rasters + arrival/travel_time.py).
Builds data/channel_segments.json.gz: stream-channel segments (~1.5 km) for the 234 desert basins in catchments.json,
each with upstream area, Open-Meteo 0.1deg rain-cell area fractions, soil stats, travel-time histogram to its downstream end.
Checkpoints in /workspace/flood/segwork (stage1.npz, stage2.pkl). Usage: nice -n 15 python precompute_segments.py"""
import sys,os,json,gzip,pickle,time,numpy as np,rasterio
R='/workspace/flood'; W=R+'/segwork_nd'; OUT='/workspace/flood_deploy/data'
sys.path.insert(0,R+'/arrival'); os.chdir(R+'/arrival')
import travel_time as tt, forecast as fc
from affine import Affine
A_STREAM=5.0      # km2: channel threshold
SEG_M=1500.       # target segment length
BIN_S=120         # internal histogram bin (s)
OUT_BIN_MIN=10    # output histogram bin (min) == routing DT_MIN
TR=Affine(fc.RES,0,fc.LON[0]-fc.RES/2,0,-fc.RES,fc.LAT[0]+fc.RES/2); SH=(len(fc.LAT),len(fc.LON))
g=tt.grids(); H,Wd=g['shape']; gtr=g['tr']; P=tt.PAR
cat=json.load(open(OUT+'/catchments_nondesert.json')); BAS=json.load(open(R+'/gis/station_basins.geojson'))
props={str(f['properties']['sid']):f['properties'] for f in BAS['features']}
sids=[s for s in cat['basins']]
t0=time.time(); log=lambda *a:print(f'[{time.time()-t0:7.1f}s]',*a,flush=True)

# ---------- stage 1: union of basin cells, per-cell hydraulics, global travel time ----------
f1=W+'/stage1.npz'
if not os.path.exists(f1):
    lab=np.full((H,Wd),-1,np.int16); outl={}
    order=sorted(sids,key=lambda s:-cat['basins'][s]['area_km2'])
    for i,s in enumerate(order):
        p=props[s]; z=tt.catchment(p['olat'],p['olon']); lab[z['rows'],z['cols']]=sids.index(s); outl[s]=(int(z['r0']),int(z['c0']))
        del z
        if i%40==0: log('basin',i)
    rr,cc=np.nonzero(lab>=0); bl=lab[rr,cc]; del lab
    N=len(rr); log('union cells',N)
    idx=np.full((H,Wd),-1,np.int32); idx[rr,cc]=np.arange(N,dtype=np.int32)
    code=np.asarray(g['fd'][rr,cc]).astype(np.int32); dr=np.zeros(N,np.int32); dc=np.zeros(N,np.int32)
    for k,(a,b) in tt.DR.items(): m=code==k; dr[m]=a; dc[m]=b
    r2=rr+dr; c2=cc+dc; ok=(r2>=0)&(r2<H)&(c2>=0)&(c2<Wd)&((dr!=0)|(dc!=0))
    down=np.full(N,-1,np.int32); down[ok]=idx[r2[ok],c2[ok]]
    # outlets terminate (their own catchment ends there only for the largest; keep flow-through for nested ones)
    del idx
    lat_c=gtr.f+gtr.e*(rr+0.5); dx=abs(gtr.a)*111320*np.cos(np.radians(lat_c)); dy=abs(gtr.e)*110570
    L=np.hypot(dr*dx,dc*dy).astype(np.float32); L[down<0]=0; ckm=(dx*dy/1e6).astype(np.float32)
    dem=g['dem'][rr,cc]; dz=np.where(down>=0,dem-dem[np.maximum(down,0)],0)
    S=np.clip(dz/np.maximum(L,1),0.001,1).astype(np.float32)
    A=(np.asarray(g['acc'][rr,cc]).astype(np.float32)*ckm)
    ch=A>=P['A_CH']
    v=np.where(ch,np.clip(P['VC']*(S/0.01)**0.3*(A/100)**0.15,0.5,5),np.clip(P['VH']*(S/0.1)**0.5,0.05,0.6))
    T=(L/v).astype(np.float64); T[down<0]=0; n=down.copy()
    while (n>=0).any():
        k=n>=0; T[k]+=T[n[k]]; n=np.where(k,n[np.maximum(n,0)],-1)
    log('global T done, max h',T.max()/3600)
    ol=np.array([outl[s] for s in sids])
    np.savez(f1,rr=rr,cc=cc,bl=bl,down=down,L=L,ckm=ckm,dem=dem,S=S,A=A,T=T,ol=ol); del v,n,code,dr,dc,r2,c2,ok,dz,lat_c,dx,dy
z1=dict(np.load(f1)); rr,cc,bl,down,L,ckm,dem,S,A,T,ol=[z1[k] for k in 'rr cc bl down L ckm dem S A T ol'.split()]; N=len(rr); log('stage1 loaded',N)

# ---------- stage 2: segmentation + aggregation ----------
f2=W+'/stage2.pkl'
if not os.path.exists(f2):
    full=np.full((H,Wd),-1,np.int32); full[rr,cc]=np.arange(N,dtype=np.int32)
    outc=full[ol[:,0],ol[:,1]]; assert (outc>=0).all(); del full
    isout=np.zeros(N,bool); isout[outc]=True
    chan=(A>=A_STREAM)|isout
    ci=np.nonzero(chan)[0]; ci=ci[np.argsort(np.round(A[ci]/ckm[ci]),kind='stable')]   # raw D8 cell count: strictly increases downstream; log('channel cells',len(ci))
    nin=np.zeros(N,np.int32); d=down[ci]; np.add.at(nin,d[d>=0],1)
    oneup=np.full(N,-1,np.int32); oneup[d[d>=0]]=ci[d>=0]
    seg=np.full(N,-1,np.int32); slen=[]; nseg=0
    for i in ci:
        if nin[i]==1:
            u=oneup[i]; s=seg[u]
            if not isout[u] and slen[s]+L[u]<SEG_M: seg[i]=s; slen[s]+=L[u]; continue
        seg[i]=nseg; slen.append(0.); nseg+=1
    log('segments',nseg)
    # end cell = channel cell whose downstream is not in same segment
    dn=down[ci]; endm=(dn<0)|(seg[np.maximum(dn,0)]!=seg[ci]); ends=np.full(nseg,-1,np.int64); ends[seg[ci[endm]]]=ci[endm]
    # every cell -> first channel cell downstream -> segment
    nx=np.where(chan,np.arange(N,dtype=np.int32),down)
    for _ in range(64):   # pointer doubling to first channel cell
        m=(nx>=0); m[m]&=~chan[nx[m]]
        if not m.any(): break
        nx[m]=nx[nx[m]]
    # downstream segment via first channel cell below the end (an outlet cell below A_STREAM may drain over hillslope cells)
    dseg=np.array([seg[nx[down[e]]] if down[e]>=0 and nx[down[e]]>=0 else -1 for e in ends],np.int32)
    cs=np.where(nx>=0,seg[np.maximum(nx,0)],-1); log('unassigned cells',(cs<0).sum())
    # local aggregates
    lat=gtr.f+gtr.e*(rr+0.5); lon=gtr.c+gtr.a*(cc+0.5)
    def rd(name): return rasterio.open(f'{R}/gis/{name}.tif').read(1)[rr,cc]
    cn=rd('curve_number').astype(np.float32); cn[(cn<=0)|(cn>100)]=90
    rock=(rd('soil_rock')==2); sand=rd('soil_sand').astype(np.float32); hsg=rd('soil_hsg')
    ok=cs>=0; s_=cs[ok]; w_=ckm[ok]
    def bc(x): return np.bincount(s_,weights=w_*x[ok],minlength=nseg)
    area=bc(np.ones(N)); cnA=bc(cn); rkA=bc(rock); sdA=bc(sand); haA=bc(hsg==1); habA=bc(hsg<=2); slA=bc(S)
    zmax=np.full(nseg,-1e9); zmin=np.full(nseg,1e9); np.maximum.at(zmax,s_,dem[ok]); np.minimum.at(zmin,s_,dem[ok])
    gx,gy=~TR*(lon[ok],lat[ok]); gr=np.clip(gy.astype(int),0,SH[0]-1); gc=np.clip(gx.astype(int),0,SH[1]-1)
    key=s_.astype(np.int64)*10000+gr*100+gc; uk,inv=np.unique(key,return_inverse=True); ga=np.bincount(inv,weights=w_)
    loc_g=[dict() for _ in range(nseg)]
    for k,a in zip(uk,ga): loc_g[int(k//10000)][int(k%10000)]=a
    rel=T[ok]-T[ends[s_]]; b=np.maximum(rel,0)//BIN_S; b=b.astype(np.int64)
    o2=np.lexsort((b,s_)); loc_h=[None]*nseg
    ss=s_[o2]; bb=b[o2]; ww=w_[o2]; cut=np.r_[0,np.nonzero(np.diff(ss))[0]+1,len(ss)]
    for j in range(len(cut)-1):
        a0,a1=cut[j],cut[j+1]; loc_h[ss[a0]]=np.bincount(bb[a0:a1],weights=ww[a0:a1]).astype(np.float32)
    del o2,ss,bb,ww,rel,b,key,inv
    log('local aggregates done')
    # accumulate along tree (ends sorted by A ascending => children before parents)
    kids=[[] for _ in range(nseg)]
    for s in range(nseg):
        if dseg[s]>=0: kids[dseg[s]].append(s)
    nk=np.array([len(k) for k in kids]); st=list(np.nonzero(nk==0)[0]); tord=[]
    while st:
        s=st.pop(); tord.append(s); d_=dseg[s]
        if d_>=0:
            nk[d_]-=1
            if nk[d_]==0: st.append(d_)
    assert len(tord)==nseg,(len(tord),nseg)
    up=dict(area=area.copy(),cn=cnA.copy(),rk=rkA.copy(),sd=sdA.copy(),ha=haA.copy(),hab=habA.copy(),sl=slA.copy(),zmax=zmax.copy(),zmin=zmin.copy())
    G=[None]*nseg; Hh=[None]*nseg; res={}
    for s in tord:
        gd=dict(loc_g[s]); h=loc_h[s] if loc_h[s] is not None else np.zeros(1,np.float32)
        for k in kids[s]:
            for kk in ('area','cn','rk','sd','ha','hab','sl'): up[kk][s]+=up[kk][k]
            up['zmax'][s]=max(up['zmax'][s],up['zmax'][k]); up['zmin'][s]=min(up['zmin'][s],up['zmin'][k])
            for c_,a in G[k].items(): gd[c_]=gd.get(c_,0)+a
            sh=(T[ends[k]]-T[ends[s]])/BIN_S; i0=int(sh); fr=sh-i0; hk=Hh[k]
            n_=max(len(h),i0+len(hk)+1); h2=np.zeros(n_,np.float32); h2[:len(h)]=h
            h2[i0:i0+len(hk)]+=hk*(1-fr); h2[i0+1:i0+1+len(hk)]+=hk*fr; h=h2
            G[k]=None; Hh[k]=None   # free
            res[k]['_hfree']=True
        G[s]=gd; Hh[s]=h
        cdf=np.cumsum(h); tot=cdf[-1]
        def pct(q):
            j=int(np.searchsorted(cdf,q*tot)); prev=cdf[j-1] if j>0 else 0
            return (j+(q*tot-prev)/max(h[j],1e-12))*BIN_S
        k10=OUT_BIN_MIN*60//BIN_S; ho=np.add.reduceat(h,np.arange(0,len(h),k10)) if len(h) else h
        nz=np.nonzero(ho>1e-6)[0]
        tbin=(np.arange(len(h))+0.5)*BIN_S/3600; band=np.bincount(np.digitize(tbin,[1,3,6,12]),weights=h,minlength=5)
        res[s]=dict(g=None,p10=pct(.1),med=pct(.5),lag0=int(nz[0]) if len(nz) else 0,lagh=ho[nz[0]:nz[-1]+1] if len(nz) else ho,band=band)
        res[s]['g']=gd
    log('tree accumulation done')
    # geometry: channel cells of each segment ordered upstream->downstream
    segcells=[[] for _ in range(nseg)]
    for i in ci: segcells[seg[i]].append(i)
    # stream names: main stem (max-A upstream path) of each basin outlet, smallest basin wins
    name=[None]*nseg; nbas=[-1]*nseg
    kidmax={}
    for s in range(nseg):
        if kids[s]: kidmax[s]=max(kids[s],key=lambda k:up['area'][k])
    for bi in sorted(range(len(sids)),key=lambda i:cat['basins'][sids[i]]['area_km2']):   # smallest first, never overwrite
        s=seg[outc[bi]]; nm=props[sids[bi]].get('main_nahal')
        while s is not None and name[s] is None:
            name[s]=nm; s=kidmax.get(s)
    # basin id = smallest basin (by area) containing the segment end cell: bl stores smallest basin label already
    sbas=bl[ends]
    outseg={sids[bi]:int(seg[outc[bi]]) for bi in range(len(sids))}
    pickle.dump(dict(nseg=nseg,ends=ends,dseg=dseg,up=up,res=res,segcells=segcells,name=name,sbas=sbas,outseg=outseg),open(f2,'wb'),protocol=4)
    log('stage2 saved')
z2=pickle.load(open(f2,'rb')); log('stage2 loaded',z2['nseg'])

# ---------- stage 3: write outputs ----------
from shapely.geometry import LineString
lat=gtr.f+gtr.e*(rr+0.5); lon=gtr.c+gtr.a*(cc+0.5)
nseg=z2['nseg']; up=z2['up']; res=z2['res']; ends=z2['ends']; segs=[]; feats=[]
for s in range(nseg):
    cl=list(z2['segcells'][s]); e=ends[s]
    if down[e]>=0: cl.append(int(down[e]))   # connect to downstream segment start
    xy=[(float(lon[i]),float(lat[i])) for i in cl]
    if len(xy)==1: xy=xy*2
    ls=LineString(xy).simplify(0.0004)
    co=[[round(x,5),round(y,5)] for x,y in ls.coords]
    a=up['area'][s]; r=res[s]; tot=sum(r['g'].values())
    cells=sorted(r['g'].items())
    o=dict(id=s,region='north_center',perennial=bool(cat['basins'][sids[z2['sbas'][s]]].get('perennial')),ds=int(z2['dseg'][s]),basin=sids[z2['sbas'][s]],name=z2['name'][s],coords=co,
           lat=round(float(lat[e]),5),lon=round(float(lon[e]),5),area_km2=round(float(a),3),
           cells=[[k//100,k%100,round(v/tot,5)] for k,v in cells],
           cn=round(up['cn'][s]/a,1),f_rock=round(up['rk'][s]/a,3),sand=round(up['sd'][s]/a,1),f_hsgA=round(up['ha'][s]/a,3),f_hsgAB=round(up['hab'][s]/a,3),
           slope=round(up['sl'][s]/a,4),relief=round(float(up['zmax'][s]-up['zmin'][s]),1),elev_end=round(float(dem[e]),1),
           tt_p10_s=round(r['p10']),tt_med_s=round(r['med']),lag0=r['lag0'],lagh=np.round(r['lagh'],4).tolist(),band=np.round(r['band'],3).tolist())
    segs.append(o)
    feats.append(dict(type='Feature',id=s,geometry=dict(type='LineString',coordinates=co),properties=dict(id=s,region='north_center',p=int(o['perennial']),name=o['name'],a=round(float(a),1),b=o['basin'])))
meta=dict(version=1,region='north_center',grid=cat['grid'],a_stream_km2=A_STREAM,seg_target_m=SEG_M,hist_bin_min=OUT_BIN_MIN,bands_h=[1,3,6,12],
          basin_outlet_segment=z2['outseg'],fields=list(segs[0].keys()))
with gzip.open(OUT+'/channel_segments_nondesert.json.gz','wt') as f: json.dump(dict(meta=meta,segments=segs),f,separators=(',',':'),ensure_ascii=False)
json.dump(dict(type='FeatureCollection',features=feats),open(OUT+'/channel_segments_nondesert.geojson','w'),separators=(',',':'),ensure_ascii=False)
log('written',nseg)
