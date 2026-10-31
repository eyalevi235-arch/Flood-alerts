// Point-in-basin lookup. along = 0 at the upstream divide, 1 at the outlet.
function _ringHas(lat, lon, ring) {
  var inside = false, n = ring.length, j = n - 1;
  for (var i = 0; i < n; i++) {
    var yi = ring[i][1], xi = ring[i][0], yj = ring[j][1], xj = ring[j][0];
    var dy = yj - yi;
    if ((yi > lat) !== (yj > lat) && lon < ((xj - xi) * (lat - yi)) / (dy === 0 ? 1e-15 : dy) + xi) inside = !inside;
    j = i;
  }
  return inside;
}
function _polyHas(lat, lon, coords) {
  if (!coords || !coords.length || !_ringHas(lat, lon, coords[0])) return false;
  for (var h = 1; h < coords.length; h++) if (_ringHas(lat, lon, coords[h])) return false;
  return true;
}
function pointInFeature(lat, lon, feature) {
  var g = feature && feature.geometry;
  if (!g || !g.coordinates) return false;
  if (g.type === 'Polygon') return _polyHas(lat, lon, g.coordinates);
  if (g.type === 'MultiPolygon') {
    for (var i = 0; i < g.coordinates.length; i++) if (_polyHas(lat, lon, g.coordinates[i])) return true;
    return false;
  }
  return false;
}
// coverage.geojson is a union mask (desert / nondesert), not one polygon per basin.
function coverageRegion(features, lat, lon) {
  var list = features || [];
  for (var i = 0; i < list.length; i++) {
    if (!pointInFeature(lat, lon, list[i])) continue;
    var region = (list[i].properties || {}).region;
    return region ? String(region) : 'covered';
  }
  return null;
}
// Published station polygons. Bad non-desert polygons (the Kishon/Jordan spills) are not a forecast.
function basinIsLive(feature, northSids) {
  var p = (feature && feature.properties) || {};
  var desert = p.desert === 1 || p.desert === true || p.desert === '1';
  if (p.status === 'bad_basin' && !desert) return false;
  if (desert) return true;
  var sid = p.sid == null ? '' : String(p.sid);
  return !!(northSids && northSids[sid]);
}
function liveBasin(features, lat, lon, northSids) {
  var hits = [];
  var list = features || [];
  for (var i = 0; i < list.length; i++) {
    if (pointInFeature(lat, lon, list[i]) && basinIsLive(list[i], northSids)) hits.push(list[i]);
  }
  if (!hits.length) return null;
  hits.sort(function (a, b) {
    var aa = Number((a.properties || {}).area_dem), bb = Number((b.properties || {}).area_dem);
    return (isFinite(aa) ? aa : 1e12) - (isFinite(bb) ? bb : 1e12);
  });
  for (var j = 0; j < hits.length; j++) if (isFinite(Number((hits[j].properties || {}).risk))) return hits[j];
  return hits[0];
}
function _hav(lat1, lon1, lat2, lon2) {
  var p = Math.PI / 180, R = 6371;
  var dLat = (lat2 - lat1) * p, dLon = (lon2 - lon1) * p;
  var x = Math.sin(dLat / 2) * Math.sin(dLat / 2) + Math.cos(lat1 * p) * Math.cos(lat2 * p) * Math.sin(dLon / 2) * Math.sin(dLon / 2);
  return 2 * R * Math.asin(Math.min(1, Math.sqrt(x)));
}
function alongBasin(feature, lat, lon) {
  var p = feature.properties || {};
  var oLat = Number(p.olat), oLon = Number(p.olon);
  var ring = feature.geometry.coordinates[0];
  if (!ring || !ring.length || !isFinite(oLat) || !isFinite(oLon)) return 1;
  var far = ring[0], best = -1;
  for (var i = 0; i < ring.length; i++) {
    var d = _hav(ring[i][1], ring[i][0], oLat, oLon);
    if (d > best) { best = d; far = ring[i]; }
  }
  var dDiv = _hav(lat, lon, far[1], far[0]);
  var dOut = _hav(lat, lon, oLat, oLon);
  var den = dDiv + dOut;
  if (den < 1e-6) return 1;
  return Math.max(0, Math.min(1, dDiv / den));
}
function basinModeled(feature, tt) {
  var p = feature.properties || {};
  if (p.perennial) return false;
  var sid = String(p.sid == null ? '' : p.sid);
  return !!(tt && tt[sid]);
}
// Smallest modeled desert basin containing the point. Otherwise the smallest hit, flagged unmodeled.
function locateBasin(features, lat, lon, tt) {
  var hits = [];
  for (var i = 0; i < features.length; i++) if (pointInFeature(lat, lon, features[i])) hits.push(features[i]);
  if (!hits.length) return {inside: false};
  function area(f) { var a = Number((f.properties || {}).area_dem); return isFinite(a) ? a : 1e12; }
  hits.sort(function (a, b) { return area(a) - area(b); });
  var modeled = [];
  for (var j = 0; j < hits.length; j++) if (basinModeled(hits[j], tt)) modeled.push(hits[j]);
  if (!modeled.length) return {inside: true, modeled: false, feature: hits[0]};
  var feature = modeled[0];
  return {inside: true, modeled: true, feature: feature, along: alongBasin(feature, lat, lon), sid: String(feature.properties.sid)};
}
function riskClass(p) {
  if (p == null || !isFinite(p)) return 'אין תחזית';
  if (p >= 0.7) return 'גבוה מאוד';
  if (p >= 0.5) return 'גבוה';
  if (p >= 0.3) return 'בינוני';
  if (p >= 0.1) return 'נמוך';
  return 'נמוך מאוד';
}
function metersPerPixel(lat, zoom) {
  return 156543.03392 * Math.cos(lat * Math.PI / 180) / Math.pow(2, zoom);
}
function snapToleranceMeters(lat, zoom) {
  // Snap only when the channel is within 60 m and within 25 px (the 20–30 px cap). The smaller distance wins.
  var screenM = 25 * metersPerPixel(lat, zoom);
  return Math.min(60, screenM);
}
function _toXY(lat, lon, lat0) {
  var kx = 111320 * Math.cos(lat0 * Math.PI / 180), ky = 110540;
  return [lon * kx, lat * ky];
}
function closestOnSegment(lat, lon, aLat, aLon, bLat, bLon) {
  var A = _toXY(aLat, aLon, lat), B = _toXY(bLat, bLon, lat), P = _toXY(lat, lon, lat);
  var dx = B[0] - A[0], dy = B[1] - A[1], len2 = dx * dx + dy * dy;
  var t = len2 ? ((P[0] - A[0]) * dx + (P[1] - A[1]) * dy) / len2 : 0;
  if (t < 0) t = 0; else if (t > 1) t = 1;
  var sx = A[0] + t * dx, sy = A[1] + t * dy;
  return {distM: Math.hypot(P[0] - sx, P[1] - sy), lat: sy / 110540, lon: sx / (111320 * Math.cos(lat * Math.PI / 180))};
}
// lines: [{coords:[[lon,lat],...], acc:number|null}]. Returns the closest point on each line within tolM.
function nearestStreams(lines, lat, lon, tolM, limit) {
  var hits = [], n = Math.min(lines.length, 20000);
  for (var i = 0; i < n; i++) {
    var coords = lines[i].coords;
    if (!coords || coords.length < 2) continue;
    var best = null;
    for (var k = 1; k < coords.length; k++) {
      var c = closestOnSegment(lat, lon, coords[k - 1][1], coords[k - 1][0], coords[k][1], coords[k][0]);
      if (!best || c.distM < best.distM) best = c;
    }
    if (best && best.distM <= tolM) hits.push({lat: best.lat, lon: best.lon, distM: best.distM, acc: lines[i].acc, index: i});
  }
  hits.sort(function (a, b) { return a.distM - b.distM; });
  return hits.slice(0, limit || 6);
}
function closestStreams(lines, lat, lon, limit) {
  var best = [], n = Math.min(lines.length, 20000), keep = limit || 4;
  for (var i = 0; i < n; i++) {
    var coords = lines[i].coords;
    if (!coords || coords.length < 2) continue;
    var hit = null;
    for (var k = 1; k < coords.length; k++) {
      var c = closestOnSegment(lat, lon, coords[k - 1][1], coords[k - 1][0], coords[k][1], coords[k][0]);
      if (!hit || c.distM < hit.distM) hit = c;
    }
    if (!hit) continue;
    var item = {lat: hit.lat, lon: hit.lon, distM: hit.distM, index: i};
    if (best.length < keep) best.push(item);
    else if (item.distM < best[best.length - 1].distM) best[best.length - 1] = item;
    else continue;
    best.sort(function (a, b) { return a.distM - b.distM; });
  }
  return best;
}
function travelHours(tt, sid, along) {
  var row = tt && tt[String(sid)];
  if (!row || !isFinite(row.med)) return null;
  var a = Math.max(0, Math.min(1, Number(along)));
  return {med: row.med / 3600 * a, p10: (row.p10 || row.med) / 3600 * a};
}
