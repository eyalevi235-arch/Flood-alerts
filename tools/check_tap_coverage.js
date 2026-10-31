// Point-in-coverage check for the published (pre-retrain) geometry.
// Run from the repo root: node tools/check_tap_coverage.js
'use strict';
var fs = require('fs');
var path = require('path');
var vm = require('vm');

var root = path.join(__dirname, '..');
function read(rel) { return JSON.parse(fs.readFileSync(path.join(root, rel), 'utf8')); }
function fail(msg) { console.error('FAIL ' + msg); process.exitCode = 1; }
function assert(cond, msg) { if (!cond) fail(msg); else console.log('ok ' + msg); }

var ctx = {console: console};
vm.createContext(ctx);
vm.runInContext(fs.readFileSync(path.join(root, 'site/tap_basin.js'), 'utf8'), ctx);
vm.runInContext(fs.readFileSync(path.join(root, 'site/tap.js'), 'utf8'), ctx);

var coverage = read('site/data/coverage.geojson').features;
var basins = read('site/data/risk_live.geojson').features;
var northRisk = JSON.parse(fs.readFileSync(path.join(root, 'site/data/risk_nondesert.geojson'), 'utf8').replace(/\bNaN\b/g, 'null'));
var northLines = read('site/data/channel_segments_nondesert.geojson');
var northSids = {};
(northLines.features || []).forEach(function (f) {
  var b = f.properties && f.properties.b;
  if (b != null) northSids[String(b)] = 1;
});
(northRisk.features || []).forEach(function (f) {
  var sid = f.properties && f.properties.sid;
  if (sid != null) northSids[String(sid)] = 1;
});

function region(lat, lon) { return ctx.coverageRegion(coverage, lat, lon); }
function live(lat, lon) {
  var f = ctx.liveBasin(basins, lat, lon, northSids);
  return f ? String(f.properties.sid) : null;
}
function nameOf(lat, lon) {
  var f = ctx.liveBasin(basins, lat, lon, northSids);
  return f ? String(f.properties.name_he || '') : '';
}

var html = fs.readFileSync(path.join(root, 'site/index.html'), 'utf8');
var app = fs.readFileSync(path.join(root, 'site/app.js'), 'utf8');
var sw = fs.readFileSync(path.join(root, 'site/sw.js'), 'utf8');
assert(html.indexOf('cartocdn') === -1 && html.indexOf('רחובות') === -1, 'streets basemap removed from the page and CSP');
assert(app.indexOf("return '#2b6cb0'") !== -1 && app.indexOf('#c6dbef') === -1, 'north layer base color is visible blue, not near-white');
assert(app.indexOf('wheelPxPerZoomLevel:120') !== -1 && app.indexOf('zoomSnap:0.5') !== -1, 'gentler cursor-anchored wheel zoom');
assert(app.indexOf('fillOpacity:perennial?0.08:0.1') !== -1, 'basin fill stays light');
assert(app.indexOf('map.removeLayer(northL)') !== -1 && app.indexOf("id=\"north\"") !== -1 || html.indexOf('id="north"') !== -1, 'north toggle removes the layer');
assert(html.indexOf('id="basins"') !== -1 && app.indexOf('basins_layer') !== -1, 'basin polygon toggle is wired');
assert(Number((sw.match(/const C='flood-v(\d+)'/)||[])[1]) >= 13, 'service worker cache bumped');
assert(ctx.snapToleranceMeters(32.5, 8) <= 60 && ctx.snapToleranceMeters(32.5, 16) <= 60, 'snap radius never exceeds 60 m');

// Gilboa / Jenin. Inside coverage v2. The published polygons do not contain a Bezeq basin.
assert(region(32.5, 35.35) === 'nondesert', '32.5, 35.35 is inside the nondesert coverage mask');
assert(live(32.5, 35.35) === null, '32.5, 35.35 is not a published basin (not Kishon)');
assert(nameOf(32.5, 35.35).indexOf('קישון') === -1, '32.5, 35.35 popup basin is not Kishon');

// Same mask, but the published Kishon polygon 8101 still covers the approximate Bezeq coordinate.
assert(region(32.48, 35.38) === 'nondesert', '32.48, 35.38 is inside coverage');
assert(live(32.48, 35.38) === '8101', '32.48, 35.38 is still published basin 8101');
console.log('CONFLICT 32.48, 35.38: coverage v2 includes this point (new model basin 990001 נחל בזק, 134 km², not shipped). The published polygon is still 8101 קישון - בגשר הרכבת. This PR does not relabel it.');

assert(region(32.48, 35.44) === null, '32.48, 35.44 is outside coverage');
assert(live(32.48, 35.44) === null, '32.48, 35.44 is not assigned a published basin');

assert(region(30.952917, 35.08125) === 'desert', 'Zin/Yamin outlet is inside desert coverage');
assert(live(30.952917, 35.08125) === '55170', 'Zin/Yamin outlet stays basin 55170');

assert(region(32.489583, 35.28375) === 'nondesert', 'Kishon 8101 outlet is inside coverage');
assert(live(32.489583, 35.28375) === '8101', 'Kishon 8101 outlet stays basin 8101');

var note = ctx.mappedChannelNote({stream: 'קישון', distM: 4100, basin: '8101'}, {'8101': 'קישון'});
assert(note === 'הערוץ הממופה הקרוב: נחל קישון, במרחק 4.1 ק"מ', 'nearest-channel note is secondary text: ' + note);

if (process.exitCode) process.exit(process.exitCode);
console.log('all checks passed');
