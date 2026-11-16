// node tools/test_data_source.js : site/data_source.js validator + synthesis + off-mode passthrough. No network.
'use strict';
const assert = require('assert');
let fetched = [];
globalThis.fetch = (u, o) => { fetched.push(String(u)); return Promise.resolve(new Response(JSON.stringify({features: [{type: 'Feature', geometry: null, properties: {sid: 1, risk: 0.5, risk_live: 0.5, risk_raw: 0.4}}]}), {status: 200})); };
const FD = require('../site/data_source.js');
const EX = {desert_seg: 4, nondesert_seg: 3, desert_basins: 2, nondesert_basins: 2, desert_geom: 'v8p', nd_geom: 'v3e', desert_seg_max_null: 1, nondesert_seg_max_null: 1};
const C = {expect: EX, max_issue_age_min: 40, max_frame_age_min: 60, max_forecast_age_h: 12};
const NOW = Date.parse('2026-11-16T09:30:00Z');
function good() {
  const seg = n => ({v: 1, t0: 1794819600, issued: '2026-11-16 11:00', p: Array(n).fill(0.1), lead: Array(n).fill(null), em: Array(n).fill(-1), tp: Array(n).fill(10), tm: Array(n).fill(20)});
  const nd = Object.assign(seg(3), {region: 'north_center', strong: [false, false, false]});
  return {schema: 1, issued_utc: '2026-11-16T09:14Z', engine_sha: 'beb7bfa', engine: 'flood_engine', source: 'radar', radar_latest_frame_utc: '2026-11-16 08:55:00', radar_hours_used: 29,
    bias: {desert: 'uncorrected', north: 'uncorrected', switch: 'on'}, thr: {desert: 0.086, north_center: 0.3}, desert_seg: seg(4), nondesert_seg: nd,
    desert_basins: {sid: [1, 2], risk: [0.2, null], rcov: [true, false]}, nondesert_basins: {sid: ['3', '4'], risk: [0, 0.2], alert: [false, true], strong: [false, false]},
    alerts: [{point: 'VP01', name: 'x', nahal: 'y', region: 'desert', prob: 0.3, confidence: 'low', issued: '2026-11-16 11:00'}], desert_geom: 'v8p', nd_geom: 'v3e', forecast_age_h: 2};
}
const r = (J, now) => FD.validate(J, now || NOW, C).reason;
let n = 0; const t = (name, f) => { f(); n++; };
t('ok', () => assert.strictEqual(r(good()), 'ok'));
t('schema', () => { const J = good(); J.schema = 2; assert.strictEqual(r(J), 'schema'); });
t('rain key', () => { const J = good(); J.desert_seg.rain = [1]; assert.strictEqual(r(J), 'schema'); });
t('mm key', () => { const J = good(); J.desert_basins.basin_mean_mm = [1]; assert.strictEqual(r(J), 'schema'); });
t('alert rain', () => { const J = good(); J.alerts[0].rain_summary = {}; assert.strictEqual(r(J), 'schema'); });
t('alert mm text', () => { const J = good(); J.alerts[0].name = '12 מ״מ'; assert.strictEqual(r(J), 'schema'); });
t('vm forecast', () => { const J = good(); J.source = 'forecast'; assert.strictEqual(r(J), 'vm_forecast'); });
t('fresh at +20', () => assert.strictEqual(r(good(), NOW + 20 * 60000), 'ok'));
t('stale issue', () => assert.strictEqual(r(good(), Date.parse('2026-11-16T09:55:00Z')), 'stale'));
t('stale frame', () => { const J = good(); J.radar_latest_frame_utc = '2026-11-16 08:25:00'; assert.strictEqual(r(J), 'stale'); });
t('future', () => { const J = good(); J.issued_utc = '2026-11-16T10:00Z'; assert.strictEqual(r(J), 'stale'); });
t('forecast part old', () => { const J = good(); J.forecast_age_h = 13; assert.strictEqual(r(J), 'stale'); });
t('geom', () => { const J = good(); J.nd_geom = 'v3f'; assert.strictEqual(r(J), 'geometry'); });
t('count', () => { const J = good(); J.desert_seg.p.push(0); assert.strictEqual(r(J), 'geometry'); });
t('values', () => { const J = good(); J.desert_seg.p[0] = 1.2; assert.strictEqual(r(J), 'values'); });
t('nulls', () => { const J = good(); J.desert_seg.p[0] = null; J.desert_seg.p[1] = null; assert.strictEqual(r(J), 'values'); });
t('synth segments/alerts', () => {
  const J = good();
  assert.deepStrictEqual(FD.synth('data/segment_risk.json', J), J.desert_seg);
  assert.deepStrictEqual(FD.synth('data/segment_risk_nondesert.json', J), J.nondesert_seg);
  const A = FD.synth('data/alerts_latest.json', J); assert.strictEqual(A.alerts.length, 1); assert.ok(A.source.startsWith('radar_live'));
  const V = FD.synth('data/viewpoints.json', J, [{id: 'VP01', current: {prob: 0.9}}, {id: 'VP02', current: {prob: 0.9}}]);
  assert.strictEqual(V[0].current.prob, 0.3); assert.strictEqual(V[1].current, null);
});
t('synth basins', () => {
  const J = good();
  const g = FD.synth('data/risk_live.geojson', J, {type: 'FeatureCollection', features: [{type: 'Feature', geometry: null, properties: {sid: 1, risk: 0.9, risk_live: 0.9, eta_peak_rain: 'x'}}, {type: 'Feature', geometry: null, properties: {sid: 77, risk: 0.4}}]});
  assert.strictEqual(g.features[0].properties.risk, 0.2); assert.strictEqual(g.features[0].properties.eta_peak_rain, null); assert.strictEqual(g.features[0].properties.radar_cov, true);
  assert.strictEqual(g.features[1].properties.risk, 0.4);
  const h = FD.synth('data/risk_nondesert.geojson', J, {features: [{type: 'Feature', properties: {sid: '4', risk: 0, risk_raw: 0.1, alert: false}}]});
  assert.strictEqual(h.features[0].properties.risk, 0.2); assert.strictEqual(h.features[0].properties.alert, true); assert.strictEqual(h.features[0].properties.risk_raw, null);
});
(async () => {
  // off mode: config without radar_live -> plain fetch, same URL, no extra requests, no banner state
  await FD.configure({live: '2026-11-16 11:00'});
  fetched = [];
  const res = await globalThis.floodFetch('data/risk_live.geojson', {cache: 'no-cache'});
  const j = await res.json();
  assert.deepStrictEqual(fetched, ['data/risk_live.geojson']); assert.strictEqual(j.features[0].properties.risk, 0.5);
  assert.strictEqual(FD.state().mode, 'off'); n++;
  // the real file shape, if given: node tools/test_data_source.js path/to/latest.json ISO_NOW
  if (process.argv[2]) {
    const J = JSON.parse(require('fs').readFileSync(process.argv[2], 'utf8'));
    const v = FD.validate(J, Date.parse(process.argv[3] || new Date().toISOString()), {});
    console.log('real file:', JSON.stringify(v));
  }
  console.log(n + ' data_source tests OK');
  process.exit(0);
})().catch(e => { console.error(e); process.exit(1); });
