// Private subscription store: Google Apps Script web app bound to a Google Sheet.
// Deploy: Extensions > Apps Script, paste this file, Script property TOKEN = a long random string,
// Deploy > Web app (execute as me, access: Anyone). The project must use the V8 runtime.
//
// Public callers may only register or unregister their own push endpoint.
// There is no action that sends a notification.
// The hourly GitHub Action reads the list with doGet?token=TOKEN, and prunes dead
// endpoints with doPost {action:"prune", token, endpoints}. The token never belongs in the repo.
//
// Sheet columns: A = push endpoint (the capability URL), B = JSON record, C = updated time.
// If an older sheet used the uid in column A, delete those rows before using this version.

var MAX_BODY = 8000;
var MAX_ROWS = 500;
var MAX_GLOBAL_HOUR = 300;
var MAX_ENDPOINT_HOUR = 60;
var MAX_PRUNE = 100;

function doPost(e) {
  try {
    if (!e || !e.postData || typeof e.postData.contents !== 'string' || e.postData.contents.length > MAX_BODY) return text_('bad');
    if (limited_('rl:g', MAX_GLOBAL_HOUR)) return text_('limited');
    var r = JSON.parse(e.postData.contents);
    if (!r || typeof r !== 'object' || Array.isArray(r)) return text_('bad');
    if (r.action === 'prune') return handlePrune_(r);
    if (r.action === 'unregister') return handleUnregister_(r);
    if (r.action && r.action !== 'register') return text_('bad');
    return handleRegister_(r);
  } catch (err) {
    return text_('bad');
  }
}

function doGet(e) {
  try {
    if (!e || !tokenOk_(e.parameter && e.parameter.token)) return json_([]);
    var out = [];
    var rows = sheet_().getDataRange().getValues();
    for (var i = 0; i < rows.length && out.length < MAX_ROWS; i++) {
      var rec = parseStored_(rows[i][1]);
      if (rec) out.push(rec);
    }
    return json_(out);
  } catch (err) {
    return json_([]);
  }
}

function handleRegister_(r) {
  var rec = cleanRecord_(r);
  if (!rec) return text_('bad');
  if (limited_('rl:e:' + digest_(rec.push.endpoint), MAX_ENDPOINT_HOUR)) return text_('limited');
  var lock = LockService.getScriptLock();
  lock.waitLock(15000);
  try {
    if (upsert_(sheet_(), rec) === 'full') return text_('full');
  } finally {
    lock.releaseLock();
  }
  return text_('ok');
}

function handleUnregister_(r) {
  var endpoint = r.push && r.push.endpoint;
  if (!hostOk_(endpoint)) return text_('bad');
  if (limited_('rl:e:' + digest_(endpoint), MAX_ENDPOINT_HOUR)) return text_('limited');
  var lock = LockService.getScriptLock();
  lock.waitLock(15000);
  try {
    deleteEndpoints_(sheet_(), [endpoint]);
  } finally {
    lock.releaseLock();
  }
  return text_('ok');
}

function handlePrune_(r) {
  if (!tokenOk_(r.token)) return text_('bad');
  if (!Array.isArray(r.endpoints) || r.endpoints.length < 1 || r.endpoints.length > MAX_PRUNE) return text_('bad');
  var eps = [];
  for (var i = 0; i < r.endpoints.length; i++) if (hostOk_(r.endpoints[i])) eps.push(r.endpoints[i]);
  if (!eps.length) return text_('bad');
  var lock = LockService.getScriptLock();
  lock.waitLock(15000);
  try {
    deleteEndpoints_(sheet_(), eps);
  } finally {
    lock.releaseLock();
  }
  return text_('ok');
}

function cleanRecord_(r) {
  if (!r || typeof r.push !== 'object' || !r.push) return null;
  var endpoint = r.push.endpoint;
  if (!hostOk_(endpoint) || String(endpoint).length > 500) return null;
  var keys = r.push.keys || {};
  if (!b64url_(keys.p256dh, 80, 120) || !b64url_(keys.auth, 16, 40)) return null;
  var points = [];
  if (Array.isArray(r.points)) {
    for (var i = 0; i < r.points.length && points.length < 40; i++) {
      if (typeof r.points[i] === 'string' && /^VP\d{2}$/.test(r.points[i])) points.push(r.points[i]);
    }
  }
  var streams = [];
  if (Array.isArray(r.streams)) {
    for (var j = 0; j < r.streams.length && streams.length < 12; j++) {
      if (streamOk_(r.streams[j])) streams.push(r.streams[j]);
    }
  }
  var thr = Number(r.threshold);
  if (!isFinite(thr) || thr < 0.05 || thr > 0.9) thr = 0.3;
  var uid = (typeof r.uid === 'string' && /^u[a-z0-9]{6,20}$/.test(r.uid)) ? r.uid : ('e' + digest_(endpoint).slice(0, 12));
  return {
    uid: uid,
    points: points,
    streams: streams,
    threshold: thr,
    push: {endpoint: endpoint, expirationTime: null, keys: {p256dh: keys.p256dh, auth: keys.auth}},
    updated: new Date().toISOString()
  };
}

function parseStored_(cell) {
  try { return cleanRecord_(JSON.parse(cell)); } catch (e) { return null; }
}

function hostOk_(endpoint) {
  if (typeof endpoint !== 'string' || endpoint.length < 12 || endpoint.length > 500) return false;
  var u;
  try { u = new URL(endpoint); } catch (e) { return false; }
  if (u.protocol !== 'https:' || u.username || u.password) return false;
  var h = u.hostname.toLowerCase().replace(/\.$/, '');
  if (h === 'fcm.googleapis.com' || h === 'updates.push.services.mozilla.com') return true;
  if (h.length > '.push.apple.com'.length && h.endsWith('.push.apple.com')) return true;
  if (h.length > '.notify.windows.com'.length && h.endsWith('.notify.windows.com')) return true;
  return false;
}

function streamOk_(s) {
  return typeof s === 'string' && s.length >= 1 && s.length <= 40 && !/[\u0000-\u001f<>]/.test(s);
}

function b64url_(s, lo, hi) {
  return typeof s === 'string' && s.length >= lo && s.length <= hi && /^[A-Za-z0-9_-]+$/.test(s);
}

function tokenOk_(got) {
  var want = PropertiesService.getScriptProperties().getProperty('TOKEN') || '';
  got = got == null ? '' : String(got);
  if (!want || want.length < 16 || want.length !== got.length) return false;
  var diff = 0;
  for (var i = 0; i < want.length; i++) diff |= want.charCodeAt(i) ^ got.charCodeAt(i);
  return diff === 0;
}

function limited_(key, max) {
  var cache = CacheService.getScriptCache();
  var n = Number(cache.get(key) || '0') + 1;
  cache.put(key, String(n), 3600);
  return n > max;
}

function digest_(s) {
  var bytes = Utilities.computeDigest(Utilities.DigestAlgorithm.SHA_256, s, Utilities.Charset.UTF_8);
  var hex = '';
  for (var i = 0; i < bytes.length; i++) {
    var v = (bytes[i] + 256) % 256;
    hex += (v < 16 ? '0' : '') + v.toString(16);
  }
  return hex.slice(0, 32);
}

function sheet_() {
  return SpreadsheetApp.getActiveSpreadsheet().getSheets()[0];
}

function upsert_(sh, rec) {
  var v = sh.getDataRange().getValues();
  for (var i = 0; i < v.length; i++) {
    if (String(v[i][0]) === rec.push.endpoint) {
      sh.getRange(i + 1, 1, 1, 3).setValues([[rec.push.endpoint, JSON.stringify(rec), new Date()]]);
      return 'ok';
    }
  }
  var count = 0;
  for (var j = 0; j < v.length; j++) if (String(v[j][0])) count++;
  if (count >= MAX_ROWS) return 'full';
  sh.appendRow([rec.push.endpoint, JSON.stringify(rec), new Date()]);
  return 'ok';
}

function deleteEndpoints_(sh, endpoints) {
  var want = {};
  for (var i = 0; i < endpoints.length; i++) want[endpoints[i]] = true;
  var v = sh.getDataRange().getValues();
  for (var r = v.length - 1; r >= 0; r--) if (want[String(v[r][0])]) sh.deleteRow(r + 1);
}

function text_(s) { return ContentService.createTextOutput(s); }
function json_(o) { return ContentService.createTextOutput(JSON.stringify(o)).setMimeType(ContentService.MimeType.JSON); }
