// Re-snap saved north/center points after the v2 -> v3b segment renumber.
// Run from the repo root: node tools/check_point_resnap.js
'use strict';
var fs = require('fs');
var path = require('path');
var vm = require('vm');
var root = path.join(__dirname, '..');
function fail(msg) { console.error('FAIL ' + msg); process.exitCode = 1; }
function assert(cond, msg) { if (!cond) fail(msg); else console.log('ok ' + msg); }

var ctx = {};
vm.createContext(ctx);
vm.runInContext(fs.readFileSync(path.join(root, 'site/tap_basin.js'), 'utf8'), ctx);
var geo = JSON.parse(fs.readFileSync(path.join(root, 'site/data/channel_segments_nondesert.geojson'), 'utf8'));
var lines = geo.features.map(function (f) {
  return {coords: f.geometry.coordinates, id: Number(f.properties.id), basin: String(f.properties.b), name: f.properties.name || ''};
});
var idMap = JSON.parse(fs.readFileSync(path.join(root, 'data/id_map_nondesert_v2_to_v3b.json'), 'utf8'));
var nullIds = Object.keys(idMap).filter(function (k) { return idMap[k] == null; });
assert(geo.nd_geom_version === 'v3b', 'channel file is stamped v3b');
assert(lines.length === 3392, 'v3b segment count is 3392, got ' + lines.length);
assert(nullIds.length === 73, 'id map has 73 unmapped v2 ids, got ' + nullIds.length);
assert(ctx.NORTH_RESNAP_M === 60, 'resnap radius is the 60 m cap');

function snap(seg, lat, lon) {
  return ctx.resnapNorthPoint({id: 'Msample01', region: 'north_center', seg: seg, sid: '1', lat: lat, lon: lon, name: 'old'}, lines, idMap, 'v3b');
}

// v2 segment midpoints that the id map translates. Geometry still overlaps, so the mapped id wins.
var mapped = [
  {seg: 0, lat: 32.74792, lon: 35.07458, expect: 1},
  {seg: 2, lat: 32.49958, lon: 34.98375, expect: 3}
];
mapped.forEach(function (s) {
  var r = snap(s.seg, s.lat, s.lon);
  assert(r.kind === 'snapped' && r.point.seg === s.expect && r.distM <= 60 && !r.point.out_of_coverage, 'v2 seg ' + s.seg + ' -> ' + s.expect + ' within 60 m (got ' + r.kind + ' seg ' + r.point.seg + ' dist ' + r.distM + ')');
  assert(r.point.nd_geom_version === 'v3b', 'snapped point stores v3b');
});

// All 73 removed ids are absent from the map. Their old midpoints are farther than 60 m, so re-snap must not invent an id.
var unmapped = [
  {seg: 85, lat: 32.63458, lon: 35.15042},
  {seg: 195, lat: 32.19125, lon: 35.36542}
];
unmapped.forEach(function (s) {
  assert(idMap[String(s.seg)] == null, 'v2 seg ' + s.seg + ' is one of the unmapped ids');
  var r = snap(s.seg, s.lat, s.lon);
  assert(r.kind === 'out' && r.point.out_of_coverage === true && r.point.seg === s.seg && (r.distM == null || r.distM > 60), 'unmapped v2 seg ' + s.seg + ' stays the saved point and is out of coverage (dist ' + r.distM + ')');
});

var desert = {id: 'Mdesert01', seg: 12, sid: '55170', lat: 30.95, lon: 35.08, name: 'ימין'};
var kept = ctx.resnapNorthPoint(desert, lines, idMap, 'v3b');
assert(kept.kind === 'kept' && kept.changed === false && kept.point === desert && kept.point.seg === 12, 'desert point is not resnapped');

var current = {id: 'Msample01', region: 'north_center', seg: 1, sid: '900079', lat: 32.74792, lon: 35.07458, nd_geom_version: 'v3b'};
var again = ctx.resnapNorthPoint(current, lines, idMap, 'v3b');
assert(again.changed === false && again.point.seg === 1, 'a point already stamped v3b is left alone');

if (process.exitCode) process.exit(process.exitCode);
console.log('all resnap checks passed');
