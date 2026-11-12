/* Pure geometry helpers for the private stream editor. No DOM. */
(function (root, factory) {
  var api = factory();
  if (typeof module === 'object' && module.exports) module.exports = api;
  else root.EditLogic = api;
})(typeof self !== 'undefined' ? self : this, function () {
  'use strict';

  function roundCoord(c) {
    return [Math.round(Number(c[0]) * 1e5) / 1e5, Math.round(Number(c[1]) * 1e5) / 1e5];
  }

  function dropDuplicates(coords) {
    var out = [];
    for (var i = 0; i < coords.length; i++) {
      var p = roundCoord(coords[i]);
      var prev = out[out.length - 1];
      if (!prev || prev[0] !== p[0] || prev[1] !== p[1]) out.push(p);
    }
    return out;
  }

  function meters(a, b) {
    var R = 6371000;
    var dLat = (b[1] - a[1]) * Math.PI / 180;
    var dLon = (b[0] - a[0]) * Math.PI / 180;
    var la1 = a[1] * Math.PI / 180;
    var la2 = b[1] * Math.PI / 180;
    var h = Math.sin(dLat / 2) * Math.sin(dLat / 2) +
      Math.cos(la1) * Math.cos(la2) * Math.sin(dLon / 2) * Math.sin(dLon / 2);
    return 2 * R * Math.asin(Math.min(1, Math.sqrt(h)));
  }

  function lengthM(coords) {
    var total = 0;
    for (var i = 1; i < coords.length; i++) total += meters(coords[i - 1], coords[i]);
    return total;
  }

  function project(a, b, p) {
    var dx = b[0] - a[0];
    var dy = b[1] - a[1];
    var l2 = dx * dx + dy * dy;
    if (l2 === 0) return [a[0], a[1]];
    var t = ((p[0] - a[0]) * dx + (p[1] - a[1]) * dy) / l2;
    if (t < 0) t = 0;
    if (t > 1) t = 1;
    return [a[0] + t * dx, a[1] + t * dy];
  }

  function closestSegment(coords, point) {
    var best = null;
    for (var i = 0; i < coords.length - 1; i++) {
      var proj = project(coords[i], coords[i + 1], point);
      var d = meters(proj, point);
      if (!best || d < best.meters) best = {index: i, proj: proj, meters: d};
    }
    return best;
  }

  function openRing(ring) {
    var pts = ring.map(function (c) { return [Number(c[0]), Number(c[1])]; });
    if (pts.length > 1) {
      var a = pts[0];
      var b = pts[pts.length - 1];
      if (Math.abs(a[0] - b[0]) < 1e-8 && Math.abs(a[1] - b[1]) < 1e-8) pts = pts.slice(0, -1);
    }
    return pts;
  }

  function closeRing(pts) {
    var open = dropDuplicates(pts);
    if (!open.length) return open;
    var first = open[0];
    var last = open[open.length - 1];
    if (first[0] !== last[0] || first[1] !== last[1]) open.push([first[0], first[1]]);
    return open;
  }

  function sameLine(a, b) {
    var aa = dropDuplicates(a);
    var bb = dropDuplicates(b);
    if (aa.length !== bb.length) return false;
    for (var i = 0; i < aa.length; i++) {
      if (aa[i][0] !== bb[i][0] || aa[i][1] !== bb[i][1]) return false;
    }
    return true;
  }

  function extend(coords, atEnd) {
    var pts = coords.map(function (c) { return [c[0], c[1]]; });
    if (pts.length < 2) return pts;
    var i = atEnd ? pts.length - 1 : 0;
    var j = atEnd ? pts.length - 2 : 1;
    var a = pts[j];
    var b = pts[i];
    var latScale = 111320;
    var lonScale = Math.max(111320 * Math.cos(b[1] * Math.PI / 180), 1000);
    var dx = (b[0] - a[0]) * lonScale;
    var dy = (b[1] - a[1]) * latScale;
    var len = Math.hypot(dx, dy) || 1;
    var step = 80;
    var p = [b[0] + (dx / len) * step / lonScale, b[1] + (dy / len) * step / latScale];
    if (atEnd) pts.push(p);
    else pts.unshift(p);
    return pts;
  }

  function shorten(coords, atEnd) {
    var pts = coords.map(function (c) { return [c[0], c[1]]; });
    if (pts.length <= 2) return null;
    if (atEnd) pts.pop();
    else pts.shift();
    return pts;
  }

  function removeIndex(coords, index) {
    if (coords.length <= 2) return null;
    if (index < 0 || index >= coords.length) return null;
    var pts = coords.map(function (c) { return [c[0], c[1]]; });
    pts.splice(index, 1);
    return dropDuplicates(pts).length >= 2 ? pts : null;
  }

  function insertOnSegment(coords, point) {
    var hit = closestSegment(coords, point);
    if (!hit) return null;
    var pts = coords.map(function (c) { return [c[0], c[1]]; });
    pts.splice(hit.index + 1, 0, roundCoord(hit.proj));
    return pts;
  }

  function mergeLines(a, b) {
    var A = dropDuplicates(a);
    var B = dropDuplicates(b);
    if (A.length < 2 || B.length < 2) return null;
    var options = [
      {aRev: false, bRev: false, d: meters(A[A.length - 1], B[0])},
      {aRev: false, bRev: true, d: meters(A[A.length - 1], B[B.length - 1])},
      {aRev: true, bRev: false, d: meters(A[0], B[0])},
      {aRev: true, bRev: true, d: meters(A[0], B[B.length - 1])}
    ];
    options.sort(function (x, y) { return x.d - y.d; });
    var best = options[0];
    var aa = best.aRev ? A.slice().reverse() : A.slice();
    var bb = best.bRev ? B.slice().reverse() : B.slice();
    if (meters(aa[aa.length - 1], bb[0]) < 15 && bb.length > 1) bb = bb.slice(1);
    var coordinates = bb.length ? aa.concat(bb) : aa;
    if (dropDuplicates(coordinates).length < 2) return null;
    return {coordinates: coordinates, gapM: best.d};
  }

  return {
    roundCoord: roundCoord,
    dropDuplicates: dropDuplicates,
    meters: meters,
    lengthM: lengthM,
    closestSegment: closestSegment,
    openRing: openRing,
    closeRing: closeRing,
    sameLine: sameLine,
    extend: extend,
    shorten: shorten,
    removeIndex: removeIndex,
    insertOnSegment: insertOnSegment,
    mergeLines: mergeLines
  };
});
