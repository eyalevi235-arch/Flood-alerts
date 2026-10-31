// Private subscription store: Google Apps Script web app bound to a Google Sheet.
// Deploy: Extensions > Apps Script, paste this file, Script property TOKEN = a long random string,
// Deploy > Web app (execute as me, access: Anyone). The project must use the V8 runtime.
//
// Public callers may only register or unregister their own push endpoint,
// or submit a flood report / forecast feedback. There is no action that sends a notification.
// Reports and feedback go to sheets named "reports" and "feedback", and photos go to the
// Drive folder in script property FOLDER_ID. They are never written back to the public repo.
// The hourly GitHub Action reads the list with doGet?token=TOKEN, and prunes dead
// endpoints with doPost {action:"prune", token, endpoints}. The token never belongs in the repo.
//
// Sheet columns: A = push endpoint (the capability URL), B = JSON record, C = updated time.
// If an older sheet used the uid in column A, delete those rows before using this version.

var MAX_BODY = 8000;
var MAX_REPORT_BODY = 7000000;
var MAX_PHOTO = 3 * 1024 * 1024;
var MAX_ROWS = 500;
var MAX_REPORTS_HOUR = 40;
var MAX_REPORTS_DEVICE_HOUR = 8;
var MAX_FEEDBACK_HOUR = 80;
var MAX_FEEDBACK_DEVICE_HOUR = 20;
var MAX_GLOBAL_HOUR = 300;
var MAX_ENDPOINT_HOUR = 60;
var MAX_PRUNE = 100;

function doPost(e) {
  try {
    if (!e || !e.postData || typeof e.postData.contents !== 'string') return text_('bad');
    var raw = e.postData.contents;
    if (raw.length > MAX_REPORT_BODY) return text_('bad');
    var r = JSON.parse(raw);
    if (!r || typeof r !== 'object' || Array.isArray(r)) return text_('bad');
    if (r.action === 'report') return handleReport_(r);
    if (r.action === 'feedback') {
      if (raw.length > MAX_BODY) return text_('bad');
      return handleFeedback_(r);
    }
    if (raw.length > MAX_BODY) return text_('bad');
    if (limited_('rl:g', MAX_GLOBAL_HOUR)) return text_('limited');
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
  var custom = [];
  if (Array.isArray(r.custom)) {
    for (var k = 0; k < r.custom.length && custom.length < 8; k++) {
      var c = r.custom[k];
      if (!c || typeof c.id !== 'string' || !/^M[a-z0-9]{6,16}$/.test(c.id)) continue;
      if (!/^\d{3,8}$/.test(String(c.sid))) continue;
      var along = Number(c.along), lat = Number(c.lat), lon = Number(c.lon);
      if (!isFinite(along) || along < 0 || along > 1 || !inIsrael_(lat, lon)) continue;
      custom.push({id: c.id, sid: String(c.sid), along: Math.round(along * 1000) / 1000, lat: lat, lon: lon});
    }
  }
  return {
    uid: uid,
    points: points,
    streams: streams,
    threshold: thr,
    custom: custom,
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

function handleReport_(r) {
  if (!deviceIdOk_(r.device_id) || !reportIdOk_(r.report_id)) return text_('bad');
  var row = cleanReport_(r);
  if (!row) return text_('bad');
  var lock = LockService.getScriptLock();
  lock.waitLock(20000);
  try {
    var sh = namedSheet_('reports', ['report_id', 'received_at', 'device_id', 'lat', 'lon', 'accuracy_m', 'location_adjusted', 'viewpoint_id', 'stream', 'wave', 'first_wave_time', 'first_wave_unknown', 'flow', 'note', 'photo_taken_at', 'photo_file_id']);
    if (findId_(sh, r.report_id)) return text_('ok');
    if (limited_('rl:rep:g', MAX_REPORTS_HOUR) || limited_('rl:rep:' + r.device_id, MAX_REPORTS_DEVICE_HOUR)) return text_('limited');
    var fileId = savePhoto_(r.photo_jpeg_base64, r.report_id);
    if (!fileId) return text_('bad');
    row.splice(1, 0, new Date());
    row.push(fileId);
    sh.appendRow(row);
  } finally {
    lock.releaseLock();
  }
  return text_('ok');
}

function handleFeedback_(r) {
  if (!deviceIdOk_(r.device_id) || !reportIdOk_(r.feedback_id)) return text_('bad');
  var row = cleanFeedback_(r);
  if (!row) return text_('bad');
  var lock = LockService.getScriptLock();
  lock.waitLock(15000);
  try {
    var sh = namedSheet_('feedback', ['feedback_id', 'received_at', 'device_id', 'kind', 'point_id', 'rating', 'text', 'contact']);
    if (findId_(sh, r.feedback_id)) return text_('ok');
    if (limited_('rl:fb:g', MAX_FEEDBACK_HOUR) || limited_('rl:fb:' + r.device_id, MAX_FEEDBACK_DEVICE_HOUR)) return text_('limited');
    row.splice(1, 0, new Date());
    sh.appendRow(row);
  } finally {
    lock.releaseLock();
  }
  return text_('ok');
}

function cleanReport_(r) {
  var lat = Number(r.lat), lon = Number(r.lon);
  if (!inIsrael_(lat, lon)) return null;
  var adjusted = r.location_adjusted === true;
  var acc = r.accuracy_m == null || r.accuracy_m === '' ? null : Number(r.accuracy_m);
  if (!adjusted && (!isFinite(acc) || acc < 0 || acc > 10000)) return null;
  if (adjusted) acc = '';
  var wave = r.wave === 'first_now' || r.wave === 'already_flowing' ? r.wave : '';
  if (!wave) return null;
  var unknown = r.first_wave_unknown === true;
  var when = '';
  if (wave === 'already_flowing' && !unknown) {
    when = typeof r.first_wave_time === 'string' && /^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}$/.test(r.first_wave_time) ? r.first_wave_time : '';
  }
  var flow = r.flow === 'weak' || r.flow === 'medium' || r.flow === 'strong' ? r.flow : '';
  var vp = typeof r.viewpoint_id === 'string' && /^VP\d{2}$/.test(r.viewpoint_id) ? r.viewpoint_id : '';
  var taken = typeof r.photo_taken_at === 'string' && /^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}$/.test(r.photo_taken_at) ? r.photo_taken_at : '';
  if (typeof r.photo_jpeg_base64 !== 'string' || r.photo_jpeg_base64.length < 100 || r.photo_jpeg_base64.length > 5600000) return null;
  return [r.report_id, r.device_id, lat, lon, acc === null ? '' : acc, adjusted ? 'yes' : 'no', vp, safeText_(r.stream, 40), wave, when, unknown ? 'yes' : 'no', flow, safeText_(r.note, 500), taken];
}

function cleanFeedback_(r) {
  var kind = r.kind === 'forecast' || r.kind === 'app' ? r.kind : '';
  if (!kind) return null;
  var rating = '';
  if (kind === 'forecast') {
    if (r.rating !== 'correct' && r.rating !== 'false_alarm' && r.rating !== 'missed' && r.rating !== 'eta_wrong' && r.rating !== 'other') return null;
    rating = r.rating;
  }
  var text = safeText_(r.text, 500);
  if (kind === 'app' && text.replace(/^'/, '').length < 2) return null;
  var point = kind === 'forecast' && typeof r.point_id === 'string' && /^VP\d{2}$/.test(r.point_id) ? r.point_id : '';
  var contact = r.contact_ok === true ? safeText_(r.contact, 80) : '';
  return [r.feedback_id, r.device_id, kind, point, rating, text, contact];
}

function savePhoto_(b64, reportId) {
  try {
    var folderId = PropertiesService.getScriptProperties().getProperty('FOLDER_ID') || '';
    if (!folderId) return '';
    var clean = String(b64).replace(/\s/g, '');
    var bytes = Utilities.base64Decode(clean);
    if (!jpegOk_(bytes)) return '';
    var blob = Utilities.newBlob(bytes, 'image/jpeg', 'report-' + reportId + '.jpg');
    return DriveApp.getFolderById(folderId).createFile(blob).getId();
  } catch (e) {
    return '';
  }
}

function jpegOk_(bytes) {
  if (!bytes || bytes.length < 3 || bytes.length > MAX_PHOTO) return false;
  return ((bytes[0] + 256) % 256) === 0xff && ((bytes[1] + 256) % 256) === 0xd8;
}

function inIsrael_(lat, lon) {
  return isFinite(lat) && isFinite(lon) && lat >= 29.3 && lat <= 33.5 && lon >= 34.1 && lon <= 36.0;
}

function deviceIdOk_(id) { return typeof id === 'string' && /^u[a-z0-9]{6,20}$/.test(id); }
function reportIdOk_(id) { return typeof id === 'string' && /^[a-z0-9]{8,40}$/.test(id); }

function safeText_(s, max) {
  if (typeof s !== 'string') return '';
  s = s.replace(/[\u0000-\u001f<>]/g, ' ').trim();
  if (s.length > max) s = s.slice(0, max);
  if (/^[=+\-@]/.test(s)) s = "'" + s;
  return s;
}

function namedSheet_(name, headers) {
  var ss = SpreadsheetApp.getActiveSpreadsheet();
  var sh = ss.getSheetByName(name);
  if (!sh) sh = ss.insertSheet(name);
  if (sh.getLastRow() === 0) sh.appendRow(headers);
  return sh;
}

function findId_(sh, id) {
  var last = Math.max(sh.getLastRow(), 1);
  var v = sh.getRange(1, 1, last, 1).getValues();
  for (var i = 1; i < v.length; i++) if (String(v[i][0]) === id) return i + 1;
  return 0;
}

function text_(s) { return ContentService.createTextOutput(s); }
function json_(o) { return ContentService.createTextOutput(JSON.stringify(o)).setMimeType(ContentService.MimeType.JSON); }
