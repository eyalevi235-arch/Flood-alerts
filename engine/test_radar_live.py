"""Unit tests for engine/radar_live.py. No network, no repo data. Run: python engine/test_radar_live.py"""
import copy, datetime as dt, json, os, re, sys, tempfile, unittest
from unittest.mock import patch
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import radar_live as rl

NOW = dt.datetime(2026, 11, 16, 9, 30, tzinfo=dt.timezone.utc)
EXP = dict(desert_seg=4, nondesert_seg=3, desert_basins=2, nondesert_basins=2, desert_geom='v8p', nd_geom='v3e',
           desert_seg_max_null=1, nondesert_seg_max_null=1)

def good():
    seg = lambda n: dict(v=1, t0=1794819600, issued='2026-11-16 11:00', p=[0.1] * n, lead=[None] * n, em=[-1] * n, tp=[10] * n, tm=[20] * n)
    nd = seg(3); nd.update(region='north_center', strong=[False] * 3)
    return dict(schema=1, issued_utc='2026-11-16T09:14Z', engine_sha='beb7bfa', engine='flood_engine', source='radar',
                radar_latest_frame_utc='2026-11-16 08:55:00', radar_hours_used=29,
                bias=dict(desert='uncorrected', north='uncorrected', switch='on'), thr=dict(desert=0.086, north_center=0.3),
                desert_seg=seg(4), nondesert_seg=nd, desert_basins=dict(sid=[1, 2], risk=[0.0, None], rcov=[True, False]),
                nondesert_basins=dict(sid=['3', '4'], risk=[0.0, 0.2], alert=[False, False], strong=[False, False]),
                alerts=[dict(point='VP01', name='x', nahal='y', region='desert', prob=0.0, eta_first_wave=None,
                             hours_until_first_wave=None, confidence='low', source='openmeteo_icon_seamless+ims_radar', issued='2026-11-16 11:00')],
                desert_geom='v8p', nd_geom='v3e', forecast_age_h=2.5)

LIM = dict(max_issue_age_min=40, max_frame_age_min=60, max_forecast_age_h=12)
def v(J, now=NOW): return rl.validate(J, now=now, expect=EXP, lim=LIM)

class Validate(unittest.TestCase):
    def test_ok(self):
        ok, r, d = v(good()); self.assertTrue(ok, (r, d)); self.assertEqual(r, 'ok')
    def test_schema(self):
        J = good(); J['schema'] = 2; self.assertEqual(v(J)[1], 'schema')
        J = good(); del J['desert_geom']; self.assertEqual(v(J)[1], 'schema')
    def test_rain_keys_rejected(self):
        for path, key in ((None, 'rain_summary'), ('desert_seg', 'rain'), ('desert_basins', 'basin_mean_mm'), ('nondesert_basins', 'r24')):
            J = good(); (J if path is None else J[path])[key] = [1]
            ok, r, d = v(J); self.assertFalse(ok); self.assertEqual(r, 'schema', d)
        J = good(); J['alerts'][0]['rain_summary'] = {'basin_mean_mm': 3}; self.assertEqual(v(J)[1], 'schema')
        J = good(); J['alerts'][0]['name'] = 'גשם 12 מ״מ'; self.assertEqual(v(J)[1], 'schema')
    def test_vm_forecast(self):
        J = good(); J['source'] = 'forecast'; self.assertEqual(v(J)[1], 'vm_forecast')
        J = good(); J['radar_hours_used'] = 0; self.assertEqual(v(J)[1], 'vm_forecast')
    def test_stale(self):
        self.assertEqual(v(good(), now=NOW + dt.timedelta(minutes=20))[1], 'ok')   # issued 36 min, frame 55 min
    def test_stale_issue(self):
        self.assertEqual(v(good(), now=dt.datetime(2026, 11, 16, 9, 55, tzinfo=dt.timezone.utc))[1], 'stale')
    def test_stale_frame(self):
        J = good(); J['radar_latest_frame_utc'] = '2026-11-16 08:25:00'; self.assertEqual(v(J)[1], 'stale')
    def test_future(self):
        J = good(); J['issued_utc'] = '2026-11-16T10:00Z'; self.assertEqual(v(J)[1], 'stale')
    def test_forecast_part_old(self):
        J = good(); J['forecast_age_h'] = 13; self.assertEqual(v(J)[1], 'stale')
    def test_geometry(self):
        J = good(); J['desert_geom'] = 'v8q'; self.assertEqual(v(J)[1], 'geometry')
        J = good(); J['desert_seg']['p'].append(0.1); self.assertEqual(v(J)[1], 'geometry')
        J = good(); J['nondesert_basins']['sid'].append('5'); self.assertEqual(v(J)[1], 'geometry')
        J = good(); J['desert_seg']['em'].pop(); self.assertEqual(v(J)[1], 'geometry')
    def test_values(self):
        J = good(); J['desert_seg']['p'][0] = 1.5; self.assertEqual(v(J)[1], 'values')
        J = good(); J['nondesert_basins']['risk'][0] = -0.1; self.assertEqual(v(J)[1], 'values')
        J = good(); J['alerts'][0]['prob'] = 2; self.assertEqual(v(J)[1], 'values')
        J = good(); J['desert_seg']['p'][:2] = [None, None]; self.assertEqual(v(J)[1], 'values')
    def test_timestamps(self):
        self.assertEqual(rl.parse_utc('2026-11-16T09:14Z'), dt.datetime(2026, 11, 16, 9, 14, tzinfo=dt.timezone.utc))
        self.assertEqual(rl.parse_utc('2026-11-16 08:55:00'), dt.datetime(2026, 11, 16, 8, 55, tzinfo=dt.timezone.utc))
        self.assertIsNone(rl.parse_utc('x')); self.assertIsNone(rl.parse_utc(None))

class Evaluate(unittest.TestCase):
    def test_missing_and_bad_json(self):
        st, J = rl.evaluate('/nonexistent/latest.json', now=NOW, expect=EXP)
        self.assertEqual((st['server_choice'], st['reason'], J), ('forecast', 'missing', None))
        with tempfile.NamedTemporaryFile('w', suffix='.json', delete=False) as f: f.write('{"schema":1,')
        st, J = rl.evaluate(f.name, now=NOW, expect=EXP); os.unlink(f.name)
        self.assertEqual(st['reason'], 'missing')
        with tempfile.NamedTemporaryFile('w', suffix='.json', delete=False) as f: f.write('{"a": NaN}')
        st, J = rl.evaluate(f.name, now=NOW, expect=EXP); os.unlink(f.name)
        self.assertEqual(st['reason'], 'missing')
    def test_status_has_no_probabilities(self):
        with tempfile.NamedTemporaryFile('w', suffix='.json', delete=False) as f: json.dump(good(), f)
        with patch.dict(os.environ, {'RADAR_LIVE_MODE': 'on'}):
            st, J = rl.evaluate(f.name, now=NOW, expect=EXP)
        os.unlink(f.name)
        self.assertEqual(st['server_choice'], 'radar'); self.assertIsNotNone(J)
        self.assertFalse(any(isinstance(x, list) for x in st.values()))
        self.assertFalse(any(re.search(r'rain|mm', k) for k in st))

class Mode(unittest.TestCase):
    def test_default_off(self):
        with patch.dict(os.environ, {}, clear=True): self.assertEqual(rl.mode(), 'off')
        with patch.dict(os.environ, {'RADAR_LIVE_MODE': 'ON'}): self.assertEqual(rl.mode(), 'on')
        with patch.dict(os.environ, {'RADAR_LIVE_MODE': 'yes'}): self.assertEqual(rl.mode(), 'off')
    def test_limits_30min_cadence(self):
        with patch.dict(os.environ, {}, clear=True):
            self.assertEqual(rl.limits(), dict(max_issue_age_min=40, max_frame_age_min=60, max_forecast_age_h=12))
    def test_site_config(self):
        c = rl.site_config(); self.assertEqual(c['mode'], 'on'); self.assertEqual(c['refresh_min'], 30)
        self.assertIsNone(c['radar_push_thr'])
        self.assertTrue(c['url'].startswith('https://raw.githubusercontent.com/eyalevi235-arch/Flood-alerts/radar-live/'))

class NoOpenMeteo(unittest.TestCase):
    """The radar path must never call Open-Meteo or the network."""
    def test_no_network_imports(self):
        import ast
        here = os.path.dirname(os.path.abspath(__file__))
        with open(os.path.join(here, 'radar_live.py'), encoding='utf-8') as f: src = f.read()
        mods = set()
        for node in ast.walk(ast.parse(src)):
            if isinstance(node, ast.Import): mods |= {a.name.split('.')[0] for a in node.names}
            elif isinstance(node, ast.ImportFrom) and node.module: mods.add(node.module.split('.')[0])
        self.assertFalse(mods & {'requests', 'urllib', 'http', 'socket', 'om_client', 'flood_engine', 'flood_engine_v2'}, mods)
        self.assertNotIn('api.open-meteo', src)
        with open(os.path.join(here, '..', 'site', 'data_source.js'), encoding='utf-8') as f: js = f.read().lower()
        self.assertNotIn('api.open-meteo', js)

class RunJobOff(unittest.TestCase):
    """With RADAR_LIVE_MODE unset, run_job.radar_live_step returns None and writes nothing."""
    def test_off_is_noop(self):
        with open(os.path.join(os.path.dirname(os.path.abspath(__file__)), 'run_job.py'), encoding='utf-8') as f: src = f.read()
        self.assertIn("if m=='off': return None", src)
        self.assertIn("if m!='on': return None", src)

if __name__ == '__main__':
    unittest.main()
