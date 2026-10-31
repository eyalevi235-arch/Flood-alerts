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
function pointInFeature(lat, lon, feature) {
  var g = feature && feature.geometry;
  if (!g || g.type !== 'Polygon' || !g.coordinates || !g.coordinates.length) return false;
  if (!_ringHas(lat, lon, g.coordinates[0])) return false;
  for (var h = 1; h < g.coordinates.length; h++) if (_ringHas(lat, lon, g.coordinates[h])) return false;
  return true;
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
function travelHours(tt, sid, along) {
  var row = tt && tt[String(sid)];
  if (!row || !isFinite(row.med)) return null;
  var a = Math.max(0, Math.min(1, Number(along)));
  return {med: row.med / 3600 * a, p10: (row.p10 || row.med) / 3600 * a};
}
