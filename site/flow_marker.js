// Animated flow markers on streams with segment probability p >= 0.7 (same p as the tap popup / #33 panel).
// Direction: segment coordinates are stored upstream -> downstream (tools/precompute_segments*.py, stage 3),
// and each segment ends at the start of its downstream segment, so segments are chained end -> start.
// Light: only the two risk arrays load first; nothing else runs when nothing is above 70%.
// At most FLOW_MAX markers, requestAnimationFrame, paused when the tab or map page is hidden.
// prefers-reduced-motion: a static arrow mid-stream pointing downstream instead.
(function () {
  'use strict';
  var FLOW_THR = 0.7, FLOW_MAX = 30, LOOP_MS = 5000, gen = 0, raf = 0, layer = null, runs = [];
  var reduce = !!(window.matchMedia && window.matchMedia('(prefers-reduced-motion: reduce)').matches);
  function j(u) { return fetch(u, {cache: 'no-cache'}).then(function (r) { return r.ok ? r.json() : null; }).catch(function () { return null; }); }
  function flowAny(r) {
    if (!r || !r.p) return false;
    for (var i = 0; i < r.p.length; i++) { var v = Number(r.p[i]); if (isFinite(v) && v >= FLOW_THR) return true; }
    return false;
  }
  function key(c) { return c[0].toFixed(4) + ',' + c[1].toFixed(4); }
  // Longest upstream -> downstream chain of hot segments in one stream group.
  function chain(segs) {
    var byStart = {}, isNext = {};
    segs.forEach(function (s, i) { byStart[key(s.coords[0])] = i; });
    segs.forEach(function (s, i) { var n = byStart[key(s.coords[s.coords.length - 1])]; if (n != null && n !== i) { s.next = n; isNext[n] = 1; } });
    var best = null, bestLen = -1;
    segs.forEach(function (s, i) {
      if (isNext[i]) return;
      var pts = [], seen = {}, k = i;
      while (k != null && !seen[k]) { seen[k] = 1; pts = pts.concat(pts.length ? segs[k].coords.slice(1) : segs[k].coords); k = segs[k].next; }
      if (pts.length > bestLen) { bestLen = pts.length; best = pts; }
    });
    return best;
  }
  function groups(data) {
    var g = {}, out = [];
    linesForSnap(data).forEach(function (line) {
      if (line.ext || !line.coords || line.coords.length < 2) return;
      var r = line.region === 'north' ? data.northRisk : data.risk;
      if (!r || !r.p || line.id < 0 || line.id >= r.p.length) return;
      var p = Number(r.p[line.id]);
      if (!isFinite(p) || p < FLOW_THR) return;
      var t = segmentTitle(line);
      var k = t ? 'n:' + t.title : 'u:' + line.region + ':' + line.basin + ':' + unnamedLabel(line, data.nahal || {});
      if (!g[k]) { g[k] = {p: p, segs: []}; out.push(g[k]); }
      if (p > g[k].p) g[k].p = p;
      g[k].segs.push({coords: line.coords});
    });
    out.sort(function (a, b) { return b.p - a.p; });
    return out.slice(0, FLOW_MAX);
  }
  function path(pts) {
    var cum = [0], lat0 = pts[0][1] * Math.PI / 180;
    for (var i = 1; i < pts.length; i++) {
      var dx = (pts[i][0] - pts[i - 1][0]) * Math.cos(lat0), dy = pts[i][1] - pts[i - 1][1];
      cum.push(cum[i - 1] + Math.sqrt(dx * dx + dy * dy));
    }
    return {pts: pts, cum: cum, len: cum[cum.length - 1]};
  }
  function at(pa, f) {
    var d = f * pa.len, c = pa.cum, lo = 1;
    while (lo < c.length - 1 && c[lo] < d) lo++;
    var a = pa.pts[lo - 1], b = pa.pts[lo], seg = c[lo] - c[lo - 1], t = seg ? (d - c[lo - 1]) / seg : 0;
    return [a[1] + (b[1] - a[1]) * t, a[0] + (b[0] - a[0]) * t];
  }
  function stop() { if (raf) cancelAnimationFrame(raf); raf = 0; }
  function clear() { stop(); runs = []; if (layer) { map.removeLayer(layer); layer = null; } }
  function visible() { var pg = document.getElementById('p-map'); return document.visibilityState !== 'hidden' && (!pg || pg.classList.contains('on')); }
  var last = 0;
  function frame(ts) {
    raf = 0;
    if (!runs.length || !visible()) return;
    if (ts - last >= 33) {
      last = ts;
      runs.forEach(function (r) { r.mk.setLatLng(at(r.pa, ((ts + r.off) % LOOP_MS) / LOOP_MS)); });
    }
    raf = requestAnimationFrame(frame);
  }
  function start() { if (!raf && runs.length && !reduce && visible()) raf = requestAnimationFrame(frame); }
  function draw(list) {
    clear();
    if (!list.length) return;
    if (!map.getPane('flowPane')) { var pn = map.createPane('flowPane'); pn.style.zIndex = 450; pn.style.pointerEvents = 'none'; }
    layer = L.layerGroup().addTo(map);
    list.forEach(function (g, i) {
      var pts = chain(g.segs);
      if (!pts || pts.length < 2) return;
      var pa = path(pts);
      if (!(pa.len > 0)) return;
      if (reduce) {
        var m = at(pa, 0.5), m2 = at(pa, Math.min(1, 0.5 + 0.02));
        var p1 = map.project(m, 10), p2 = map.project(m2, 10);
        var deg = Math.atan2(p2.y - p1.y, p2.x - p1.x) * 180 / Math.PI;
        var icon = L.divIcon({className: 'flow-arrow', html: '<span style="transform:rotate(' + deg.toFixed(0) + 'deg)">➤</span>', iconSize: [18, 18], iconAnchor: [9, 9]});
        L.marker(m, {icon: icon, pane: 'flowPane', interactive: false, keyboard: false}).addTo(layer);
        return;
      }
      var mk = L.circleMarker(at(pa, 0), {pane: 'flowPane', radius: 4.5, color: '#fff', weight: 2, fillColor: '#ff3b30', fillOpacity: 1, interactive: false}).addTo(layer);
      runs.push({mk: mk, pa: pa, off: (i * 977) % LOOP_MS});
    });
    start();
  }
  function refresh() {
    var g0 = ++gen;
    Promise.all([j('data/segment_risk.json'), northEnabled() ? j('data/segment_risk_nondesert.json') : Promise.resolve(null)]).then(function (rr) {
      if (g0 !== gen) return;
      if (!flowAny(rr[0]) && !flowAny(rr[1])) { clear(); return; }
      return loadTapData().then(function (data) { if (g0 === gen) draw(groups(data)); });
    }).catch(function () {});
  }
  document.addEventListener('visibilitychange', start);
  window.addEventListener('hashchange', function () { setTimeout(start, 60); });
  var tries = 0;
  (function wait() {
    if (typeof map === 'undefined' || !map || typeof loadTapData !== 'function' || typeof riskL === 'undefined' || !riskL) { if (++tries < 300) setTimeout(wait, 200); return; }
    refresh();
    ['per', 'north'].forEach(function (id) { var n = document.getElementById(id); if (n) n.addEventListener('change', refresh); });
  })();
  window.flowMarkersRefresh = refresh;
})();
