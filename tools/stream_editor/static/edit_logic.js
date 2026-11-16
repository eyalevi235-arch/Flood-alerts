/* Pure helpers for the private stream editor. No DOM, no storage, no network. */
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

  var JUNCTION_TOL_DEG = 1e-7;
  var SNAP_DEG = 1e-5;

  function normStreamName(text) {
    var value = String(text || '').replace(/־/g, ' ').replace(/-/g, ' ');
    value = value.split(/\s+/).filter(Boolean).join(' ');
    var prefixes = ['נחל ', 'ואדי ', 'נהר '];
    for (var i = 0; i < prefixes.length; i++) {
      if (value.indexOf(prefixes[i]) === 0) value = value.slice(prefixes[i].length);
    }
    return value.toLowerCase();
  }

  function streamIdentity(item) {
    if (!item) return '';
    var local = normStreamName(item.name_he);
    if (local) return local;
    return normStreamName(item.name);
  }

  function coordsCoincide(a, b) {
    if (!a || !b || a.length < 2 || b.length < 2) return false;
    var dlon = Math.abs(Number(a[0]) - Number(b[0]));
    var dlat = Math.abs(Number(a[1]) - Number(b[1]));
    if (dlon <= JUNCTION_TOL_DEG && dlat <= JUNCTION_TOL_DEG) return true;
    var ra = roundCoord(a);
    var rb = roundCoord(b);
    return ra[0] === rb[0] && ra[1] === rb[1];
  }

  function vertexSnapKey(coord) {
    var snapped = roundCoord(coord);
    return snapped[0].toFixed(5) + ',' + snapped[1].toFixed(5);
  }

  function findParent(parent, index) {
    var cursor = index;
    while (parent[cursor] !== cursor) {
      parent[cursor] = parent[parent[cursor]];
      cursor = parent[cursor];
    }
    return cursor;
  }

  function groupStream(segments, anchorLayer, anchorId) {
    if (!Array.isArray(segments)) return null;
    var anchor = -1;
    for (var i = 0; i < segments.length; i++) {
      var item = segments[i];
      if (item && item.layer === anchorLayer && item.id === anchorId) {
        anchor = i;
        break;
      }
    }
    if (anchor < 0) return null;
    var identity = streamIdentity(segments[anchor]);
    var parent = new Array(segments.length);
    for (var p = 0; p < segments.length; p++) parent[p] = p;
    var buckets = {};
    for (var s = 0; s < segments.length; s++) {
      if (streamIdentity(segments[s]) !== identity) continue;
      var coords = segments[s].coordinates || [];
      for (var v = 0; v < coords.length; v++) {
        var key = vertexSnapKey(coords[v]);
        var list = buckets[key];
        if (!list) {
          list = [];
          buckets[key] = list;
        }
        if (list.indexOf(s) < 0) list.push(s);
      }
    }
    var keys = Object.keys(buckets);
    for (var k = 0; k < keys.length; k++) {
      var ids = buckets[keys[k]];
      var head = findParent(parent, ids[0]);
      for (var j = 1; j < ids.length; j++) {
        var other = findParent(parent, ids[j]);
        if (head !== other) parent[other] = head;
      }
    }
    var root = findParent(parent, anchor);
    var memberSet = {};
    var members = [];
    for (var m = 0; m < segments.length; m++) {
      if (streamIdentity(segments[m]) !== identity) continue;
      if (findParent(parent, m) !== root) continue;
      memberSet[m] = true;
      members.push(m);
    }
    for (var e = 0; e < segments.length; e++) {
      if (memberSet[e]) continue;
      var ext = segments[e];
      if (ext.src_seg == null || ext.src_layer == null || ext.src_layer === '') continue;
      var linked = false;
      for (var n = 0; n < members.length; n++) {
        var src = segments[members[n]];
        if (src.layer === ext.src_layer && src.id === ext.src_seg) {
          linked = true;
          break;
        }
      }
      if (!linked) continue;
      var extIdentity = streamIdentity(ext);
      if (extIdentity && extIdentity !== identity) continue;
      memberSet[e] = true;
      members.push(e);
    }
    var memberKeys = {};
    for (var a = 0; a < members.length; a++) {
      var memberCoords = segments[members[a]].coordinates || [];
      for (var b = 0; b < memberCoords.length; b++) {
        memberKeys[vertexSnapKey(memberCoords[b])] = true;
      }
    }
    var neighbors = [];
    for (var q = 0; q < segments.length; q++) {
      if (memberSet[q]) continue;
      var otherCoords = segments[q].coordinates || [];
      for (var t = 0; t < otherCoords.length; t++) {
        if (memberKeys[vertexSnapKey(otherCoords[t])]) {
          neighbors.push(q);
          break;
        }
      }
    }
    function byId(left, right) {
      if (left.layer < right.layer) return -1;
      if (left.layer > right.layer) return 1;
      return left.id - right.id;
    }
    var memberItems = members.map(function (index) { return segments[index]; });
    var neighborItems = neighbors.map(function (index) { return segments[index]; });
    memberItems.sort(byId);
    neighborItems.sort(byId);
    return {identity: identity, members: memberItems, neighbors: neighborItems};
  }

  function sharedRefs(parts, coord) {
    var refs = [];
    if (!Array.isArray(parts)) return refs;
    for (var p = 0; p < parts.length; p++) {
      var coords = parts[p] && parts[p].coordinates;
      if (!coords) continue;
      for (var i = 0; i < coords.length; i++) {
        if (coordsCoincide(coords[i], coord)) refs.push({part: p, index: i});
      }
    }
    return refs;
  }

  function applySharedMove(parts, refs, coord, snap) {
    var next = snap ? roundCoord(coord) : [Number(coord[0]), Number(coord[1])];
    if (!Array.isArray(refs)) return next;
    for (var i = 0; i < refs.length; i++) {
      var ref = refs[i];
      var part = parts[ref.part];
      if (!part || !part.coordinates || ref.index < 0 || ref.index >= part.coordinates.length) continue;
      part.coordinates[ref.index] = [next[0], next[1]];
    }
    return next;
  }

  function vertexIsShared(parts, partIndex, vertexIndex) {
    var part = parts && parts[partIndex];
    if (!part || !part.coordinates || vertexIndex < 0 || vertexIndex >= part.coordinates.length) return false;
    var refs = sharedRefs(parts, part.coordinates[vertexIndex]);
    for (var i = 0; i < refs.length; i++) {
      if (refs[i].part !== partIndex) return true;
    }
    return false;
  }

  function partsTouch(a, b) {
    if (!a || !b) return false;
    for (var i = 0; i < a.length; i++) {
      for (var k = 0; k < b.length; k++) {
        if (coordsCoincide(a[i], b[k])) return true;
      }
    }
    return false;
  }

  function touchingPairs(parts) {
    var count = 0;
    if (!Array.isArray(parts)) return count;
    for (var i = 0; i < parts.length; i++) {
      for (var j = i + 1; j < parts.length; j++) {
        var left = parts[i].coordinates || parts[i];
        var right = parts[j].coordinates || parts[j];
        if (partsTouch(left, right)) count += 1;
      }
    }
    return count;
  }

  function removeSharedVertex(parts, partIndex, vertexIndex, minKeep) {
    if (vertexIsShared(parts, partIndex, vertexIndex)) return null;
    var part = parts[partIndex];
    return removeIndex(part.coordinates, vertexIndex, minKeep == null ? 2 : minKeep);
  }

  function shortenShared(parts, partIndex, atEnd) {
    var part = parts && parts[partIndex];
    if (!part || !part.coordinates) return null;
    var index = atEnd ? part.coordinates.length - 1 : 0;
    if (vertexIsShared(parts, partIndex, index)) return null;
    return shorten(part.coordinates, atEnd);
  }

  function reviewStreamChanges(parts, note, actions) {
    var text = typeof note === 'string' ? note.trim() : '';
    if (!text || text.length > 500 || !Array.isArray(parts)) return [];
    var changes = [];
    for (var i = 0; i < parts.length; i++) {
      var part = parts[i];
      if (!part || !part.coordinates || part.coordinates.length < 2) continue;
      if (typeof part.layer !== 'string' || !part.layer || part.layer === 'basin') continue;
      if (typeof part.id !== 'number' || !isFinite(part.id)) continue;
      var next = dropDuplicates(part.coordinates);
      if (next.length < 2) continue;
      var original = part.original || part.coordinates;
      var geometrySame = sameLine(next, original);
      var oldBasin = part.originalBasin == null || part.originalBasin === '' ? null : String(part.originalBasin);
      var newBasin = part.basin == null || part.basin === '' ? null : String(part.basin);
      if (geometrySame && oldBasin === newBasin) continue;
      changes.push({
        op: 'update_stream',
        layer: part.layer,
        id: part.id,
        name: part.name || part.name_he || '',
        note: text,
        actions: Array.isArray(actions) ? actions.slice() : [],
        old_geometry: {type: 'LineString', coordinates: original.map(function (point) {
          return [Number(point[0]), Number(point[1])];
        })},
        new_geometry: {type: 'LineString', coordinates: next},
        old_basin: oldBasin,
        new_basin: newBasin
      });
    }
    return changes;
  }

  function deleteStreamChanges(members, note) {
    if (!Array.isArray(members) || !members.length) return null;
    var ordered = members.slice().sort(function (a, b) {
      var aExt = String(a.layer || '').indexOf('extension') >= 0 ? 0 : 1;
      var bExt = String(b.layer || '').indexOf('extension') >= 0 ? 0 : 1;
      if (aExt !== bExt) return aExt - bExt;
      if (a.layer < b.layer) return -1;
      if (a.layer > b.layer) return 1;
      return a.id - b.id;
    });
    var changes = [];
    for (var i = 0; i < ordered.length; i++) {
      var item = ordered[i];
      var change = deleteStreamChange({
        mode: 'streams',
        layer: item.layer,
        id: item.id,
        name: item.name || item.name_he || '',
        note: note,
        coordinates: item.coordinates,
        basin: item.basin
      });
      if (!change) return null;
      changes.push(change);
    }
    return changes;
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

  var SEND_URL_KEY = 'flood-editor-send-url';
  var SEND_AUTH_KEY = 'flood-editor-send-auth';
  var SEND_OK_TEXT = 'נשלח ✓';

  function normalizeAuthorization(raw) {
    var value = String(raw == null ? '' : raw).trim();
    if (!value || /^bearer$/i.test(value)) return '';
    var match = /^Bearer\s+/i.exec(value);
    if (match) {
      var token = value.slice(match[0].length).trim();
      if (!token) return '';
      return 'Bearer ' + token;
    }
    return 'Bearer ' + value;
  }

  function webhookUrl(raw) {
    var value = String(raw == null ? '' : raw).trim();
    if (!value || /\s/.test(value)) return '';
    var parsed;
    try {
      parsed = new URL(value);
    } catch (err) {
      return '';
    }
    if (parsed.protocol !== 'http:' && parsed.protocol !== 'https:') return '';
    if (!parsed.hostname) return '';
    return value;
  }

  function sendConfirmLabel(count) {
    var n = Number(count);
    if (n === 1) return 'לשלוח שינוי אחד לפרוייקטור?';
    return 'לשלוח ' + n + ' שינויים לפרוייקטור?';
  }

  function sendFailureText(status) {
    if (typeof status === 'number' && isFinite(status)) {
      return 'השליחה נכשלה (סטטוס ' + status + '). אפשר להוריד את הקובץ במקום.';
    }
    return 'השליחה נכשלה (רשת או CORS, אין סטטוס HTTP). אפשר להוריד את הקובץ במקום.';
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
    deleteStreamChange: deleteStreamChange,
    JUNCTION_TOL_DEG: JUNCTION_TOL_DEG,
    SNAP_DEG: SNAP_DEG,
    normStreamName: normStreamName,
    streamIdentity: streamIdentity,
    coordsCoincide: coordsCoincide,
    vertexSnapKey: vertexSnapKey,
    groupStream: groupStream,
    sharedRefs: sharedRefs,
    applySharedMove: applySharedMove,
    vertexIsShared: vertexIsShared,
    partsTouch: partsTouch,
    touchingPairs: touchingPairs,
    removeSharedVertex: removeSharedVertex,
    shortenShared: shortenShared,
    reviewStreamChanges: reviewStreamChanges,
    deleteStreamChanges: deleteStreamChanges,
    SEND_URL_KEY: SEND_URL_KEY,
    SEND_AUTH_KEY: SEND_AUTH_KEY,
    SEND_OK_TEXT: SEND_OK_TEXT,
    normalizeAuthorization: normalizeAuthorization,
    webhookUrl: webhookUrl,
    sendConfirmLabel: sendConfirmLabel,
    sendFailureText: sendFailureText
  };
});
