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

  function removeIndex(coords, index, minKeep) {
    var keep = minKeep == null ? 2 : minKeep;
    if (!coords || coords.length <= keep) return null;
    if (index < 0 || index >= coords.length) return null;
    var pts = coords.map(function (c) { return [c[0], c[1]]; });
    pts.splice(index, 1);
    return dropDuplicates(pts).length >= keep ? pts : null;
  }

  function insertAfter(coords, index, point) {
    if (!coords || index < 0 || index >= coords.length) return null;
    var pts = coords.map(function (c) { return [c[0], c[1]]; });
    var before = dropDuplicates(pts).length;
    pts.splice(index + 1, 0, roundCoord(point));
    var cleaned = dropDuplicates(pts);
    return cleaned.length > before ? cleaned : null;
  }

  function insertOnSegment(coords, point) {
    var hit = closestSegment(coords, point);
    if (!hit) return null;
    return insertAfter(coords, hit.index, hit.proj);
  }

  function edgeMidpoints(coords, closed) {
    var n = coords ? coords.length : 0;
    if (n < 2) return [];
    var count = closed ? n : n - 1;
    var out = [];
    for (var i = 0; i < count; i++) {
      var j = (i + 1) % n;
      out.push({
        after: i,
        coord: roundCoord([
          (Number(coords[i][0]) + Number(coords[j][0])) / 2,
          (Number(coords[i][1]) + Number(coords[j][1])) / 2
        ])
      });
    }
    return out;
  }

  function visibleIndices(points, minPx, minCount, keepEnds) {
    var gap = minPx == null ? 48 : minPx;
    var least = minCount == null ? 4 : minCount;
    var shown = [];
    var last = null;
    for (var i = 0; i < points.length; i++) {
      var pt = points[i];
      if (!pt || !pt.inView) continue;
      if (last && Math.hypot(pt.x - last.x, pt.y - last.y) < gap) continue;
      shown.push(i);
      last = pt;
    }
    if (shown.length < least && points.length) {
      shown = [];
      var step = Math.max(1, Math.ceil(points.length / 12));
      for (var j = 0; j < points.length; j += step) shown.push(j);
      if (shown[shown.length - 1] !== points.length - 1) shown.push(points.length - 1);
    }
    if (keepEnds && points.length) {
      if (points[0] && points[0].inView && shown.indexOf(0) < 0) shown.unshift(0);
      var end = points.length - 1;
      if (points[end] && points[end].inView && shown.indexOf(end) < 0) shown.push(end);
    }
    return shown;
  }

  function keptMidpoints(items, minPx) {
    var gap = minPx == null ? 56 : minPx;
    var kept = [];
    for (var i = 0; i < items.length; i++) {
      var item = items[i];
      if (!item || !item.inView || !(item.len >= gap)) continue;
      var close = false;
      for (var k = 0; k < kept.length; k++) {
        if (Math.hypot(item.x - kept[k].x, item.y - kept[k].y) < gap) {
          close = true;
          break;
        }
      }
      if (!close) kept.push(item);
    }
    return kept;
  }

  function redrawSection(coords, start, end, points) {
    if (!coords || coords.length < 2) return null;
    if (start == null || end == null) return null;
    if (start < 0 || end < 0 || start >= coords.length || end >= coords.length) return null;
    if (start === end) return null;
    var a = Math.min(start, end);
    var b = Math.max(start, end);
    var anchorA = roundCoord(coords[a]);
    var anchorB = roundCoord(coords[b]);
    var mid = dropDuplicates((points || []).map(function (p) { return roundCoord(p); }));
    mid = mid.filter(function (p) {
      var onA = p[0] === anchorA[0] && p[1] === anchorA[1];
      var onB = p[0] === anchorB[0] && p[1] === anchorB[1];
      return !onA && !onB;
    });
    if (start > end) mid = mid.slice().reverse();
    var next = coords.slice(0, a + 1).concat(mid).concat(coords.slice(b));
    var cleaned = dropDuplicates(next);
    return cleaned.length >= 2 ? cleaned : null;
  }

  var TOUCH_SLOP_PX = 24;
  var POINTER_SLOP_PX = 8;

  function tapSlopPx(hasTouch) {
    return hasTouch ? TOUCH_SLOP_PX : POINTER_SLOP_PX;
  }

  function acceptTap(mode, kind) {
    if (mode === 'basins') return kind === 'basin';
    if (mode === 'streams') return kind === 'stream';
    return false;
  }

  function searchMatchesMode(mode, layer) {
    var kind = layer === 'basin' ? 'basin' : 'stream';
    return acceptTap(mode, kind);
  }

  function basinChrome(active) {
    if (active) return {opacity: 1, fillOpacity: 0.16, interactive: true};
    return {opacity: 0.4, fillOpacity: 0.05, interactive: false};
  }

  function streamChrome(active) {
    if (active) return {opacity: 0.9, interactive: true};
    return {opacity: 0.55, interactive: false};
  }

  function editTransition(dirty, action, choice) {
    if (action === 'finish') {
      return {commit: !!dirty, revert: false, deselect: true, stay: false, prompt: false};
    }
    if (action === 'cancel') {
      return {commit: false, revert: true, deselect: true, stay: false, prompt: false};
    }
    if (action === 'select-other') {
      if (!dirty) {
        return {commit: false, revert: false, deselect: true, stay: false, prompt: false};
      }
      if (choice === 'commit') {
        return {commit: true, revert: false, deselect: true, stay: false, prompt: false};
      }
      if (choice === 'discard') {
        return {commit: false, revert: true, deselect: true, stay: false, prompt: false};
      }
      if (choice === 'stay') {
        return {commit: false, revert: false, deselect: false, stay: true, prompt: false};
      }
      return {commit: false, revert: false, deselect: false, stay: true, prompt: true};
    }
    return null;
  }

  function deleteStreamChange(spec) {
    if (!spec || spec.mode !== 'streams') return null;
    if (typeof spec.layer !== 'string' || !spec.layer || spec.layer === 'basin') return null;
    if (typeof spec.id !== 'number' || !isFinite(spec.id)) return null;
    if (!Array.isArray(spec.coordinates) || spec.coordinates.length < 2) return null;
    var note = typeof spec.note === 'string' ? spec.note.trim() : '';
    if (!note || note.length > 500) return null;
    var coords = [];
    for (var i = 0; i < spec.coordinates.length; i++) {
      coords.push(roundCoord(spec.coordinates[i]));
    }
    if (coords.length < 2) return null;
    var basin = spec.basin == null || spec.basin === '' ? null : String(spec.basin);
    return {
      op: 'delete_stream',
      layer: spec.layer,
      id: spec.id,
      name: spec.name == null ? '' : String(spec.name),
      note: note,
      old_geometry: {type: 'LineString', coordinates: coords},
      old_basin: basin
    };
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
    insertAfter: insertAfter,
    insertOnSegment: insertOnSegment,
    edgeMidpoints: edgeMidpoints,
    visibleIndices: visibleIndices,
    keptMidpoints: keptMidpoints,
    redrawSection: redrawSection,
    editTransition: editTransition,
    tapSlopPx: tapSlopPx,
    acceptTap: acceptTap,
    searchMatchesMode: searchMatchesMode,
    basinChrome: basinChrome,
    streamChrome: streamChrome,
    mergeLines: mergeLines,
    deleteStreamChange: deleteStreamChange
  };
});
