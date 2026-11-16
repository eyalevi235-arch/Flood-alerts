"""Unit tests for engine/om_client.py. No network, no repo data/GeoJSON."""
import json, os, sys, time, tempfile, unittest
from pathlib import Path
from unittest.mock import patch, Mock
import numpy as np
import pandas as pd
import requests

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import om_client as om

def _resp(code, body='', headers=None, json_data=None):
    r=Mock()
    r.status_code=code
    r.text=body if isinstance(body,str) else json.dumps(body)
    r.headers=headers or {}
    r.json=Mock(return_value=json_data if json_data is not None else body)
    def raise_for_status():
        if code>=400:
            raise requests.HTTPError(f'{code} error', response=r)
    r.raise_for_status=raise_for_status
    return r

def _series(start, hours, nlat=2, nlon=3, value=None):
    t=pd.date_range(start, periods=hours, freq='h')
    if value is None:
        # unique, deterministic cell/time values
        base=np.arange(hours,dtype='float32')[:,None,None]
        R=(base + np.arange(nlat,dtype='float32')[None,:,None]*np.float32(0.01)
           + np.arange(nlon,dtype='float32')[None,None,:]*np.float32(0.0001))
    else:
        R=np.full((hours,nlat,nlon),value,dtype='float32')
    return t, R

class GetTests(unittest.TestCase):
    def setUp(self):
        om.reset(); self.env={'OM_RETRY_BUDGET_S':'120','OM_CHUNK_SLEEP_S':'0'}
        self.p=patch.dict(os.environ,self.env,clear=False); self.p.start()
    def tearDown(self):
        self.p.stop()

    def test_200(self):
        with patch('om_client.requests.get', return_value=_resp(200, json_data={'ok':1})) as g, \
             patch('om_client.time.sleep') as sl:
            self.assertEqual(om.get('https://api.open-meteo.com/v1/forecast',{'q':1}), {'ok':1})
            self.assertEqual(g.call_count,1); sl.assert_not_called()
            self.assertEqual(om.STATS['http_ok'],1)

    def test_daily_limit_no_retry(self):
        body='Daily API request limit exceeded. Please try again tomorrow.'
        with patch('om_client.requests.get', return_value=_resp(429, body, headers={'Retry-After':'3600'})) as g, \
             patch('om_client.time.sleep') as sl:
            with self.assertRaises(om.DailyLimitExceeded):
                om.get('https://api.open-meteo.com/v1/forecast',{'q':1},tries=4)
            self.assertEqual(g.call_count,1); sl.assert_not_called()
            self.assertEqual(om.STATS['http_daily'],1)

    def test_transient_429_respects_retry_after(self):
        seq=[_resp(429,'rate limited',headers={'Retry-After':'7'}), _resp(200, json_data={'ok':1})]
        with patch('om_client.requests.get', side_effect=seq) as g, \
             patch('om_client.time.sleep') as sl:
            self.assertEqual(om.get('u',{},tries=4), {'ok':1})
            self.assertEqual(g.call_count,2)
            sl.assert_called()
            waits=[c.args[0] for c in sl.call_args_list]
            self.assertTrue(any(abs(w-7)<0.01 for w in waits), waits)

    def test_5xx_then_ok(self):
        seq=[_resp(503,'no'), _resp(200, json_data={'v':2})]
        with patch('om_client.requests.get', side_effect=seq), patch('om_client.time.sleep'):
            self.assertEqual(om.get('u',{},tries=4), {'v':2})
            self.assertEqual(om.STATS['http_5xx'],1)

    def test_timeout_then_ok(self):
        seq=[requests.Timeout('t'), _resp(200, json_data={'v':3})]
        with patch('om_client.requests.get', side_effect=seq), patch('om_client.time.sleep'):
            self.assertEqual(om.get('u',{},tries=4), {'v':3})
            self.assertEqual(om.STATS['http_timeout'],1)

    def test_long_retry_after_is_daily(self):
        with patch('om_client.requests.get', return_value=_resp(429,'',headers={'Retry-After':'1200'})) as g, \
             patch('om_client.time.sleep') as sl:
            with self.assertRaises(om.DailyLimitExceeded):
                om.get('u',{},tries=4)
            self.assertEqual(g.call_count,1); sl.assert_not_called()

class StitchTests(unittest.TestCase):
    def test_identity_with_full_series(self):
        now=pd.Timestamp('2026-11-16 06:00')
        hours=34*24
        start=now-pd.Timedelta(days=31)
        t_full,R_full=_series(start, hours)
        # History from 20h earlier, with the same values on hours that also appear in the current full series.
        t_hist=pd.date_range(start-pd.Timedelta(hours=20), periods=hours, freq='h')
        R_hist=np.zeros((hours,)+R_full.shape[1:],dtype='float32')
        overlap=t_full.get_indexer(t_hist)
        for i,j in enumerate(overlap):
            if j>=0: R_hist[i]=R_full[j]
        short_start=now-pd.Timedelta(days=2)
        short_hours=(2+3)*24
        idx=t_full.get_indexer(pd.date_range(short_start, periods=short_hours, freq='h'))
        self.assertTrue((idx>=0).all())
        t_short=t_full[idx]; R_short=R_full[idx]
        t,R=om.stitch(t_hist,R_hist,t_short,R_short)
        pos=t.get_indexer(t_full)
        self.assertTrue((pos>=0).all())
        np.testing.assert_array_equal(np.asarray(R[pos],dtype="float32"), np.asarray(R_full,dtype="float32"))
        self.assertTrue(om.covers(t, 31, now=now))
        i_now=t.get_loc(now); j_now=t_full.get_loc(now)
        np.testing.assert_array_equal(np.asarray(R[i_now-720:i_now+1],dtype="float32"), np.asarray(R_full[j_now-720:j_now+1],dtype="float32"))

    def test_new_values_win_overlap(self):
        t1,R1=_series('2026-11-01', 10, value=1)
        t2,R2=_series('2026-11-01 07:00', 5, value=9)
        t,R=om.stitch(t1,R1,t2,R2)
        self.assertEqual(len(t), 7+5)
        np.testing.assert_array_equal(R[:7], R1[:7])
        np.testing.assert_array_equal(R[7:], R2)

class CacheGridTests(unittest.TestCase):
    def setUp(self):
        om.reset()
        self.tmp=tempfile.TemporaryDirectory()
        self.env=patch.dict(os.environ,{
            'OM_CACHE_DIR':self.tmp.name,
            'OM_CACHE_FRESH_H':'1.5',
            'OM_CACHE_STALE_H':'6',
            'OM_HISTORY_H':'24',
            'OM_SHORT_PAST_DAYS':'2',
            'OM_CHUNK_SLEEP_S':'0',
            'OM_RETRY_BUDGET_S':'60',
        },clear=False)
        self.env.start()

    def tearDown(self):
        self.env.stop(); self.tmp.cleanup()

    def _payload(self, t, R, la, lo):
        """One Open-Meteo response list: one location per cell, same times."""
        times=[x.strftime('%Y-%m-%dT%H:%M') for x in t]
        n=len(la); hours=len(t)
        locs=[]
        R2=R.reshape(hours, n)
        for i in range(n):
            locs.append({'hourly':{'time':times,'precipitation':[float(R2[h,i]) for h in range(hours)]}})
        return locs if len(locs)>1 else locs[0]

    def test_roundtrip_and_memo(self):
        now=pd.Timestamp('2026-11-16 06:00')
        t,R=_series(now-pd.Timedelta(days=31), 34*24, nlat=2, nlon=2)
        nlat,nlon=2,2
        la=np.array([0.,0.,1.,1.]); lo=np.array([0.,1.,0.,1.])
        payload=self._payload(t,R,la,lo)
        def fake_get(url,params,tries=4,timeout=60):
            return payload
        t1,R1,src=om.precip_grid(fake_get,la,lo,nlat,nlon,'icon_seamless',3,31,chunk=10,now=now)
        self.assertEqual(src,'http_full')
        np.testing.assert_allclose(R1,R,atol=1e-5)
        # second identical call: memo, no extra src change
        t2,R2,src2=om.precip_grid(fake_get,la,lo,nlat,nlon,'icon_seamless',3,31,chunk=10,now=now)
        self.assertEqual(src2,'http_full')  # memo returns cached tuple including original src
        self.assertEqual(om.STATS['memo'],1)
        np.testing.assert_array_equal(R1,R2)
        self.assertTrue(t1.equals(t2))

    def test_fresh_hit_zero_http(self):
        now=pd.Timestamp('2026-11-16 06:00')
        t,R=_series(now-pd.Timedelta(days=31), 34*24, nlat=2, nlon=2)
        om.save_grid('icon_seamless',2,2,t,R)
        om.reset()
        la=np.array([0.,0.,1.,1.]); lo=np.array([0.,1.,0.,1.])
        def boom(*a,**k): raise AssertionError('HTTP should not be called')
        t2,R2,src=om.precip_grid(boom,la,lo,2,2,'icon_seamless',3,31,chunk=10,now=now)
        self.assertEqual(src,'cache_fresh')
        np.testing.assert_allclose(R2,R,atol=1e-5)
        self.assertEqual(om.STATS['hit'],1)

    def test_short_fetch_matches_full(self):
        now=pd.Timestamp('2026-11-16 06:00')
        t_full,R_full=_series(now-pd.Timedelta(days=31), 34*24, nlat=2, nlon=2)
        # yesterday's history: 20h older start, 34d length (prefix still covers ante30)
        t_hist,R_hist=_series(now-pd.Timedelta(days=31, hours=20), 34*24, nlat=2, nlon=2)
        # make the overlapping older hours identical to t_full's prefix where they overlap,
        # but that is NOT required: stitch drops hist at short start. Only need hist start early enough.
        # Age the cache file to 3 hours (not fresh, within history window).
        om.save_grid('icon_seamless',2,2,t_hist,R_hist)
        p=om._cache_path('icon_seamless',2,2)
        st=os.stat(p)
        old=time.time()-3*3600
        os.utime(p,(old,old))
        # rewrite ts inside npz to 3h ago
        z=np.load(p)
        np.savez_compressed(p,t=z['t'],R=z['R'],ts=np.array([old],dtype='float64'))
        om.reset()
        la=np.array([0.,0.,1.,1.]); lo=np.array([0.,1.,0.,1.])
        short_start=now-pd.Timedelta(days=2)
        short_hours=(2+3)*24
        t_short=pd.date_range(short_start, periods=short_hours, freq='h')
        idx=t_full.get_indexer(t_short)
        R_short=R_full[idx]
        calls={'n':0,'past':[]}
        def fake_get(url,params,tries=4,timeout=60):
            calls['n']+=1
            calls['past'].append(int(params['past_days']))
            self.assertEqual(int(params['past_days']),2)
            return self._payload(t_short,R_short,la,lo)
        t,R,src=om.precip_grid(fake_get,la,lo,2,2,'icon_seamless',3,31,chunk=10,now=now)
        self.assertEqual(src,'http_short')
        self.assertEqual(calls['n'],1)
        self.assertEqual(calls['past'],[2])
        # stitched result equals a current full series on the overlapping + new hours,
        # and equals hist before short_start
        expected_t, expected_R=om.stitch(t_hist,R_hist,t_short,R_short)
        self.assertTrue(t.equals(expected_t))
        np.testing.assert_array_equal(R, expected_R)
        self.assertTrue(om.covers(t,31,now=now))

    def test_stale_on_daily_limit(self):
        now=pd.Timestamp('2026-11-16 06:00')
        t,R=_series(now-pd.Timedelta(days=31), 34*24, nlat=2, nlon=2)
        om.save_grid('icon_seamless',2,2,t,R)
        p=om._cache_path('icon_seamless',2,2)
        old=time.time()-3*3600
        z=np.load(p); np.savez_compressed(p,t=z['t'],R=z['R'],ts=np.array([old],dtype='float64'))
        om.reset()
        la=np.array([0.,0.,1.,1.]); lo=np.array([0.,1.,0.,1.])
        def daily(*a,**k):
            r=_resp(429,'Daily API request limit exceeded. Please try again tomorrow.')
            raise om.DailyLimitExceeded('daily', response=r)
        t2,R2,src=om.precip_grid(daily,la,lo,2,2,'icon_seamless',3,31,chunk=10,now=now)
        self.assertTrue(src.startswith('cache_stale'))
        np.testing.assert_allclose(R2,R,atol=1e-5)

    def test_no_cache_daily_limit_raises(self):
        la=np.array([0.,0.,1.,1.]); lo=np.array([0.,1.,0.,1.])
        now=pd.Timestamp('2026-11-16 06:00')
        def daily(*a,**k):
            raise om.DailyLimitExceeded('daily', response=_resp(429,'Daily API request limit exceeded.'))
        with self.assertRaises(om.DailyLimitExceeded):
            om.precip_grid(daily,la,lo,2,2,'icon_seamless',3,31,chunk=10,now=now)

class PublishFlagTests(unittest.TestCase):
    def test_writes_github_output_and_summary(self):
        # Exercise the helper from run_job without importing the engine (no data/model).
        src=Path(os.path.join(os.path.dirname(__file__),'run_job.py')).read_text(encoding='utf-8')
        # extract function by exec of a tiny prefix
        start=src.index('def _publish_output')
        end=src.index('\ndef vapid_public')
        ns={'os':os}
        exec(src[start:end], ns)
        with tempfile.TemporaryDirectory() as d:
            out=os.path.join(d,'out'); summ=os.path.join(d,'sum')
            with patch.dict(os.environ,{'GITHUB_OUTPUT':out,'GITHUB_STEP_SUMMARY':summ},clear=False):
                ns['_publish_output'](False, 'Open-Meteo unavailable (DailyLimitExceeded)')
            self.assertEqual(Path(out).read_text().strip(), 'publish=false')
            text=Path(summ).read_text()
            self.assertIn('forecast not published', text)
            self.assertIn('previous site forecast', text)
            os.remove(out)
            with patch.dict(os.environ,{'GITHUB_OUTPUT':out,'GITHUB_STEP_SUMMARY':summ},clear=False):
                ns['_publish_output'](True)
            self.assertEqual(Path(out).read_text().strip(), 'publish=true')

if __name__=='__main__':
    unittest.main()
