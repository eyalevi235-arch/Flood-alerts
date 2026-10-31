# non-desert (north/center, incl. perennial) flood model. Target A: gauge 'flood' flow (Hydro Service גאות flag, q>=max(0.5,2*baseflow)) or FB yes.
# Target B (significant): gauge qpeak>=max(2, 4*station thr). Features computable from forecast: POWER-style rain stats + ante3/7/30 + static + soil + urban.
import json,numpy as np,pandas as pd,lightgbm as lgb
from sklearn.metrics import roc_auc_score,average_precision_score,roc_curve
from sklearn.linear_model import LogisticRegression
S=pd.read_csv('gis/station_basins.csv').drop_duplicates('sid').set_index('sid')
X=pd.read_parquet('data/ev_D_src.parquet'); X=X[X.sid.map(S.desert)==0].sort_values('t_start').reset_index(drop=True)
X['perennial']=X.sid.map(S.perennial).fillna(0)
BR=pd.read_parquet('data/basin_rain_hourly_power.parquet'); idx=BR.index; X['ante3']=np.nan
for sid,g in X.groupby('sid'):
    r=np.r_[0,np.nancumsum(BR[str(sid)].to_numpy(np.float32))]; a=idx.searchsorted(g.t_start.values); X.loc[g.index,'ante3']=r[a]-r[np.maximum(a-72,0)]
SOIL=['cn_mean','f_built','f_crop','f_veg','f_rock','f_hsgAB','f_hsgD','clay_mean','sand_mean','summer_flow_frac']
for c in SOIL: X[c]=X.sid.map(S[c])
X['summer_flow_frac']=X.summer_flow_frac.fillna(-1)
thr=pd.read_csv('labels/hydro_flood_events.csv').groupby('sid').thr.max(); X['thr']=X.sid.map(thr).fillna(0.5)
gauge=X.src.str.startswith('hydro')
X['y_sig']=np.where(gauge,((X.y==1)&(X.qpeak.fillna(0)>=np.maximum(2,4*X.thr))).astype(int),X.y)
RAIN=['dur_h','total','max1','max3','max6','max12','max24','ante3','ante7','ante30']; STAT=['area','elev','relief','lat','lon','doy_s','doy_c','perennial']
F=RAIN+STAT+SOIL; CUT=pd.Timestamp('2020-10-01')
def fit(d,yc): return lgb.LGBMClassifier(n_estimators=400,learning_rate=0.03,num_leaves=15,min_child_samples=30,subsample=0.8,subsample_freq=1,colsample_bytree=0.8,n_jobs=2,verbose=-1).fit(d[F],d[yc],sample_weight=d.w)
lgt=lambda q:np.log(np.clip(q,1e-4,1-1e-4)/(1-np.clip(q,1e-4,1-1e-4)))
R={}
for yc,name in [('y','nondesert_flow'),('y_sig','nondesert_sig')]:
    tr=X[X.t_start<CUT]; v=tr.t_start.iloc[int(len(tr)*0.8)]; a=tr[tr.t_start<v]; b=tr[(tr.t_start>=v)&(tr.w>=1)]
    m=fit(a,yc); pv=m.predict_proba(b[F])[:,1]; fpr,tpr,th=roc_curve(b[yc],pv); t=float(th[np.argmax(tpr-fpr)])
    L=LogisticRegression().fit(lgt(pv).reshape(-1,1),b[yc]); A,B=float(L.coef_[0][0]),float(L.intercept_[0])
    m=fit(tr,yc); te=X[(X.t_start>=CUT)&(X.w>=1)]; s=m.predict_proba(te[F])[:,1]; out=dict(train_n=len(tr),train_pos=round(tr[yc].mean(),3),thr=round(t,4),platt_a=round(A,4),platt_b=round(B,4))
    for k,mk in [('all',te.sid>0),('gauge',te.src.str.startswith('hydro')),('perennial',te.perennial==1),('non_perennial',te.perennial==0),('fb',~te.src.str.startswith('hydro'))]:
        y=te[yc][mk].values==1; ss=s[mk.values]; yh=ss>=t
        if mk.sum()<20 or y.all() or (~y).all(): out[k]=dict(n=int(mk.sum()),pos=int(y.sum())); continue
        o=dict(n=int(mk.sum()),pos=round(y.mean(),3),roc=round(roc_auc_score(y,ss),3),pr=round(average_precision_score(y,ss),3),hit=round((yh&y).sum()/y.sum(),3),fa=round((yh&~y).sum()/(~y).sum(),3))
        thr70=np.quantile(ss[y],0.3); o['fa_at_70pct_hit']=round(((ss>=thr70)&~y).sum()/(~y).sum(),3); out[k]=o
    out['baseline_total_roc']=round(roc_auc_score(te[yc],te.total),3); out['baseline_max24_roc']=round(roc_auc_score(te[yc],te.max24),3)
    imp=dict(zip(F,m.booster_.feature_importance('gain'))); out['top_features']=[k for k,_ in sorted(imp.items(),key=lambda kv:-kv[1])[:8]]
    m.booster_.save_model(f'model/{name}.txt'); R[name]=out; print(name,json.dumps(out,ensure_ascii=False),flush=True)
json.dump(dict(split=str(CUT),features=F,stations=int(X.sid.nunique()),gauged_stations=int(X[gauge].sid.nunique()),results=R),open('model/nondesert_metrics.json','w'),indent=1,ensure_ascii=False)
