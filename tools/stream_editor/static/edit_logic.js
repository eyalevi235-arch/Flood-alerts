/* Pure helpers for the private stream editor. No DOM and no network.
   Draft decisions mutate only the bucket object the caller passes in. */
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

  var DRAFT_STORAGE_KEY = 'flood-stream-editor-draft-v2';
  var DRAFT_LEGACY_KEY = 'flood-stream-editor-v1';
  var DRAFT_IDB_MARKER = '{"backend":"indexeddb","v":2}';
  var DRAFT_DB_NAME = 'flood-stream-editor';
  var DRAFT_DB_STORE = 'drafts';
  var DRAFT_DB_RECORD = 'current';
  var DRAFT_LOCAL_LIMIT = 4 * 1024 * 1024;
  var DRAFT_QUOTA_TEXT = 'האחסון המקומי מלא. השינויים נשמרו במאגר הדפדפן של המכשיר.';
  var DRAFT_SAVE_FAILED_TEXT = 'לא הצלחתי לשמור את השינויים במכשיר. הם עלולים ללכת לאיבוד אם סוגרים את העמוד.';
  var DRAFT_CLEAR_TEXT = 'לנקות את כל השינויים שלא נשלחו? הם יימחקו מהמכשיר ואי אפשר לשחזר אותם.';

  function draftByteLength(text) {
    var json = String(text == null ? '' : text);
    if (typeof TextEncoder !== 'undefined') return new TextEncoder().encode(json).length;
    var bytes = 0;
    for (var i = 0; i < json.length; i++) {
      var code = json.charCodeAt(i);
      if (code < 0x80) bytes += 1;
      else if (code < 0x800) bytes += 2;
      else if (code >= 0xD800 && code <= 0xDBFF) {
        bytes += 4;
        i += 1;
      } else bytes += 3;
    }
    return bytes;
  }

  function draftWritePlan(byteLength) {
    var size = Number(byteLength);
    if (isFinite(size) && size > DRAFT_LOCAL_LIMIT) return 'indexeddb';
    return 'local';
  }

  function encodeDraft(draft) {
    var saved = draft && Array.isArray(draft.saved) ? draft.saved : [];
    var originals = draft && draft.originals && typeof draft.originals === 'object' && !Array.isArray(draft.originals)
      ? draft.originals : {};
    var fileNote = draft && typeof draft.fileNote === 'string' ? draft.fileNote : '';
    return JSON.stringify({saved: saved, originals: originals, fileNote: fileNote});
  }

  function parseDraft(raw) {
    if (typeof raw !== 'string' || !raw || raw === DRAFT_IDB_MARKER) return null;
    var data;
    try {
      data = JSON.parse(raw);
    } catch (err) {
      return null;
    }
    if (!data || typeof data !== 'object' || Array.isArray(data)) return null;
    if (data.backend === 'indexeddb' && !Array.isArray(data.saved)) return null;
    if (!Array.isArray(data.saved) && typeof data.fileNote !== 'string') return null;
    return {
      saved: Array.isArray(data.saved) ? data.saved : [],
      originals: data.originals && typeof data.originals === 'object' && !Array.isArray(data.originals) ? data.originals : {},
      fileNote: typeof data.fileNote === 'string' ? data.fileNote : ''
    };
  }

  function draftHasChanges(draft) {
    if (!draft || typeof draft !== 'object') return false;
    if (Array.isArray(draft.saved) && draft.saved.length > 0) return true;
    return typeof draft.fileNote === 'string' && draft.fileNote.trim().length > 0;
  }

  function restoredDraftNotice(draft) {
    if (!draft || !Array.isArray(draft.saved)) return '';
    var count = draft.saved.length;
    if (count === 1) return 'שוחזר שינוי אחד שלא נשלח';
    if (count > 1) return 'שוחזרו ' + count + ' שינויים שלא נשלחו';
    if (typeof draft.fileNote === 'string' && draft.fileNote.trim()) return 'שוחזרה הערה שלא נשלחה';
    return '';
  }

  function isQuotaError(err) {
    if (!err) return false;
    var name = String(err.name || '');
    if (name === 'QuotaExceededError' || name === 'NS_ERROR_DOM_QUOTA_REACHED') return true;
    return err.code === 22 || err.code === 1014;
  }

  function shouldClearDraft(action) {
    return action === 'send-success' || action === 'clear-changes';
  }

  function hasStoredText(raw) {
    return typeof raw === 'string' && raw.length > 0;
  }

  function draftRestoreDecision(localRaw, legacyRaw, idbRaw, idbChecked) {
    var local = parseDraft(localRaw);
    if (local) {
      return {
        draft: local,
        notice: restoredDraftNotice(local),
        needsIndexedDb: false,
        migrate: false,
        dropLegacy: hasStoredText(legacyRaw)
      };
    }
    if (!idbChecked) {
      return {draft: null, notice: '', needsIndexedDb: true, migrate: false, dropLegacy: false};
    }
    var stored = parseDraft(idbRaw);
    if (stored) {
      return {
        draft: stored,
        notice: restoredDraftNotice(stored),
        needsIndexedDb: false,
        migrate: false,
        dropLegacy: hasStoredText(legacyRaw)
      };
    }
    var legacy = parseDraft(legacyRaw);
    if (legacy) {
      return {
        draft: legacy,
        notice: restoredDraftNotice(legacy),
        needsIndexedDb: false,
        migrate: true,
        dropLegacy: true
      };
    }
    return {
      draft: null,
      notice: '',
      needsIndexedDb: false,
      migrate: false,
      dropLegacy: hasStoredText(legacyRaw)
    };
  }

  function commitDraft(bucket, draft) {
    var warnings = [];
    if (!draftHasChanges(draft)) {
      bucket.local = null;
      bucket.session = null;
      bucket.idb = null;
      return {ok: true, target: 'cleared', warnings: warnings, json: ''};
    }
    var json = encodeDraft(draft);
    var overLimit = draftWritePlan(draftByteLength(json)) === 'indexeddb';
    var overQuota = bucket.localQuota != null && draftByteLength(json) > bucket.localQuota;
    if (!overLimit && !bucket.failLocal && !overQuota) {
      bucket.local = json;
      bucket.idb = null;
      bucket.session = null;
      return {ok: true, target: 'local', warnings: warnings, json: json};
    }
    if (!overLimit) {
      warnings.push(bucket.failLocal === 'other' ? DRAFT_SAVE_FAILED_TEXT : DRAFT_QUOTA_TEXT);
    }
    if (bucket.failIdb) {
      if (warnings.indexOf(DRAFT_SAVE_FAILED_TEXT) < 0) warnings.push(DRAFT_SAVE_FAILED_TEXT);
      return {ok: false, target: null, warnings: warnings, json: json};
    }
    bucket.idb = json;
    bucket.local = DRAFT_IDB_MARKER;
    bucket.session = null;
    return {ok: true, target: 'indexeddb', warnings: warnings, json: json};
  }

  function loadDraft(bucket) {
    var decision = draftRestoreDecision(bucket.local, bucket.session, bucket.idb, false);
    if (decision.needsIndexedDb) {
      decision = draftRestoreDecision(bucket.local, bucket.session, bucket.idb, true);
    }
    if (decision.migrate && decision.draft) commitDraft(bucket, decision.draft);
    else if (decision.dropLegacy) bucket.session = null;
    if (decision.draft && bucket.local && bucket.local !== DRAFT_IDB_MARKER && !decision.migrate) {
      bucket.idb = null;
    }
    return decision;
  }

  function clearDraftBucket(bucket) {
    bucket.local = null;
    bucket.session = null;
    bucket.idb = null;
    return {ok: true, target: 'cleared', warnings: []};
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
    SEND_URL_KEY: SEND_URL_KEY,
    SEND_AUTH_KEY: SEND_AUTH_KEY,
    SEND_OK_TEXT: SEND_OK_TEXT,
    normalizeAuthorization: normalizeAuthorization,
    webhookUrl: webhookUrl,
    sendConfirmLabel: sendConfirmLabel,
    sendFailureText: sendFailureText,
    DRAFT_STORAGE_KEY: DRAFT_STORAGE_KEY,
    DRAFT_LEGACY_KEY: DRAFT_LEGACY_KEY,
    DRAFT_IDB_MARKER: DRAFT_IDB_MARKER,
    DRAFT_DB_NAME: DRAFT_DB_NAME,
    DRAFT_DB_STORE: DRAFT_DB_STORE,
    DRAFT_DB_RECORD: DRAFT_DB_RECORD,
    DRAFT_LOCAL_LIMIT: DRAFT_LOCAL_LIMIT,
    DRAFT_QUOTA_TEXT: DRAFT_QUOTA_TEXT,
    DRAFT_SAVE_FAILED_TEXT: DRAFT_SAVE_FAILED_TEXT,
    DRAFT_CLEAR_TEXT: DRAFT_CLEAR_TEXT,
    draftByteLength: draftByteLength,
    draftWritePlan: draftWritePlan,
    encodeDraft: encodeDraft,
    parseDraft: parseDraft,
    draftHasChanges: draftHasChanges,
    restoredDraftNotice: restoredDraftNotice,
    isQuotaError: isQuotaError,
    shouldClearDraft: shouldClearDraft,
    draftRestoreDecision: draftRestoreDecision,
    commitDraft: commitDraft,
    loadDraft: loadDraft,
    clearDraftBucket: clearDraftBucket
  };
});
