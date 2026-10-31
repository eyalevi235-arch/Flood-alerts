"""Non-desert (north/center) variant. Run on the box (needs DEM/CN rasters): precompute per-point tables on the Open-Meteo 0.1deg grid."""
import sys,os,json,numpy as np,pandas as pd,time
R='/workspace/flood'; sys.path.insert(0,R); sys.path.insert(0,R+'/arrival'); os.chdir(R+'/arrival')
import travel_time as tt, routing as rt, forecast as fc
from affine import Affine
TR=Affine(fc.RES,0,fc.LON[0]-fc.RES/2,0,-fc.RES,fc.LAT[0]+fc.RES/2); SH=(len(fc.LAT),len(fc.LON)); P=rt.P
def table(lat,lon,full):
    z=tt.catchment(lat,lon); g=tt.grids(); x,y=g['tr']*(z['cols']+0.5,z['rows']+0.5); c,r=~TR*(x,y)
    r=np.clip(r.astype(int),0,SH[0]-1); c=np.clip(c.astype(int),0,SH[1]-1)
    k=pd.DataFrame(dict(r=r,c=c)).drop_duplicates(); rr,cc=k.r.values,k.c.values; gx,gy=TR*(cc+0.5,rr+0.5)
    d=np.hypot((gx-lon)*np.cos(np.radians(lat)),gy-lat)*111; w=1/(1+d/max(np.median(d),1))
    dem=g['dem'][z['rows'],z['cols']]
    o=dict(area_km2=float(z['area_km2']),elev=float(dem.mean()),relief=float(dem.max()-dem.min()),
           mask=dict(r=rr.tolist(),c=cc.tolist(),w=np.round(w/w.sum(),6).tolist(),near=(d<=np.median(d)).astype(int).tolist()),
           tt_p10_s=float(np.percentile(z['tt_s'],10)),tt_med_s=float(np.median(z['tt_s'])))
    if full:
        cn,src=rt.cn_for(z,P['CN_DESERT']); cnb=np.round(cn/P['CN_BIN'])*P['CN_BIN']; lag=(z['tt_s']/60/P['DT_MIN']).astype(int)
        key=pd.DataFrame(dict(r=r,c=c,cn=cnb)); gr=key.groupby(['r','c','cn'],sort=True).ngroup().values; G=key.drop_duplicates().sort_values(['r','c','cn'])
        band=pd.cut(z['tt_s']/3600,[-1,1,3,6,12,99],labels=False).astype(int)
        groups=[]
        for gi,(_,row) in enumerate(G.iterrows()):
            m=gr==gi; lh=np.bincount(lag[m],weights=z['cellkm2'][m]); nz=np.nonzero(lh)[0]
            groups.append(dict(r=int(row.r),c=int(row.c),cn=float(row.cn),lag0=int(nz[0]),lagh=np.round(lh[nz[0]:nz[-1]+1],5).tolist(),
                band=np.round(np.bincount(band[m],weights=z['cellkm2'][m],minlength=5),5).tolist(),tt_med_h=round(float(np.median(z['tt_s'][m])/3600),2)))
        o.update(cn_source=src,groups=groups)
    return o
out=dict(grid=dict(lat=fc.LAT.tolist(),lon=fc.LON.tolist(),res=fc.RES),routing_params=P,points={},basins={})
t0=time.time()
S=pd.read_csv(f'{R}/gis/station_basins.csv').drop_duplicates('sid').set_index('sid')
B=json.load(open(f'{R}/gis/station_basins.geojson'))
for f in B['features']:
    p=f['properties']
    s=p['sid']; r=S.loc[s] if s in S.index else None
    ok=r is not None and r.desert==0 and r.status!='bad_basin' and 3<=r.area_dem<=3000 and (pd.isna(r.area_rep) or 0.5<=r.area_dem/r.area_rep<=2)
    if ok and p.get('olat'):
        try: out['basins'][str(p['sid'])]=dict(table(p['olat'],p['olon'],False),region='north_center',perennial=bool(r.perennial),name=r.main_nahal,name_station=r.name_he)
        except Exception as e: print('fail',p['sid'],e)
print('basins',len(out['basins']),time.time()-t0)
json.dump(out,open('/workspace/flood_deploy/data/catchments_nondesert.json','w'),separators=(',',':'))
