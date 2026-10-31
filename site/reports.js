// Flood reports and forecast feedback. Queued in IndexedDB, posted only to the Apps Script URL.
var reportMap, reportPin, reportFix = null, photoJpeg = null, photoTaken = null;

function rid() { return 'r' + Math.random().toString(36).slice(2, 12) + Date.now().toString(36); }
function kmBetween(a, b, c, d) {
  var p = Math.PI / 180, R = 6371;
  var dLat = (c - a) * p, dLon = (d - b) * p;
  var x = Math.sin(dLat / 2) * Math.sin(dLat / 2) + Math.cos(a * p) * Math.cos(c * p) * Math.sin(dLon / 2) * Math.sin(dLon / 2);
  return 2 * R * Math.asin(Math.min(1, Math.sqrt(x)));
}
function reportDb() {
  return new Promise(function (resolve, reject) {
    var req = indexedDB.open('flood-reports', 1);
    req.onupgradeneeded = function () {
      if (!req.result.objectStoreNames.contains('outbox')) req.result.createObjectStore('outbox', {keyPath: 'id'});
    };
    req.onsuccess = function () { resolve(req.result); };
    req.onerror = function () { reject(req.error); };
  });
}
function outboxAll() {
  return reportDb().then(function (db) {
    return new Promise(function (resolve, reject) {
      var tx = db.transaction('outbox', 'readonly');
      var req = tx.objectStore('outbox').getAll();
      req.onsuccess = function () { resolve(req.result || []); };
      req.onerror = function () { reject(req.error); };
    });
  });
}
function outboxPut(rec) {
  return reportDb().then(function (db) {
    return new Promise(function (resolve, reject) {
      var tx = db.transaction('outbox', 'readwrite');
      tx.objectStore('outbox').put(rec);
      tx.oncomplete = function () { resolve(); };
      tx.onerror = function () { reject(tx.error); };
    });
  });
}
function outboxDel(id) {
  return reportDb().then(function (db) {
    return new Promise(function (resolve, reject) {
      var tx = db.transaction('outbox', 'readwrite');
      tx.objectStore('outbox').delete(id);
      tx.oncomplete = function () { resolve(); };
      tx.onerror = function () { reject(tx.error); };
    });
  });
}
function endpointOk() {
  return typeof subscribeUrlOk === 'function' && typeof CFG !== 'undefined' && CFG && subscribeUrlOk(CFG.subscribe_url);
}
function postPrivate(body) {
  if (!navigator.onLine) return Promise.reject(new Error('offline'));
  if (!endpointOk()) return Promise.reject(new Error('noserver'));
  return fetch(CFG.subscribe_url, {method: 'POST', mode: 'no-cors', headers: {'Content-Type': 'text/plain'}, body: JSON.stringify(body)});
}
async function flushOutbox() {
  var rows;
  try { rows = await outboxAll(); } catch (e) { return; }
  var left = 0;
  for (var i = 0; i < rows.length; i++) {
    try {
      await postPrivate(rows[i].body);
      await outboxDel(rows[i].id);
    } catch (e) { left++; }
  }
  var msg = left ? ('ממתינים לשליחה: ' + left) : (rows.length ? 'התור נשלח.' : '');
  ['report-status', 'fb-status'].forEach(function (id) {
    var n = document.getElementById(id);
    if (n && msg && !n.textContent) n.textContent = msg;
  });
}
function setStatus(id, text) { var n = document.getElementById(id); if (n) n.textContent = text; }

function ensureReportMap() {
  if (reportMap) { setTimeout(function () { reportMap.invalidateSize(); }, 60); return; }
  var host = document.getElementById('report-map');
  if (!host || typeof L === 'undefined') return;
  reportMap = L.map(host, {zoomControl: false, attributionControl: true, zoomSnap: 0.5, zoomDelta: 0.5, wheelPxPerZoomLevel: 120, scrollWheelZoom: true}).setView([30.9, 35.0], 7);
  if (typeof addNameAttribution === 'function') addNameAttribution(reportMap);
  if (typeof addBasemap === 'function') addBasemap(reportMap, 'topo');
  setTimeout(function () { reportMap.invalidateSize(); }, 60);
}
function placePin(lat, lon) {
  ensureReportMap();
  if (!reportMap) return;
  var icon = L.divIcon({className: 'pin', iconSize: [18, 18], iconAnchor: [9, 9]});
  if (!reportPin) {
    reportPin = L.marker([lat, lon], {draggable: true, icon: icon}).addTo(reportMap);
    reportPin.on('dragend', function () {
      var p = reportPin.getLatLng();
      if (reportFix) { reportFix.lat = p.lat; reportFix.lon = p.lng; reportFix.adjusted = true; }
      suggestNear();
      setStatus('gps-status', 'הסיכה הוזזה. הדיוק של ה-GPS כבר לא מתאר את הנקודה הסופית.');
    });
  } else reportPin.setLatLng([lat, lon]);
  reportMap.setView([lat, lon], Math.max(reportMap.getZoom(), 13));
}
async function ensurePoints() {
  if (typeof VPS !== 'undefined' && Array.isArray(VPS) && VPS.length) return;
  try {
    var res = await fetch('data/viewpoints.json', {cache: 'no-cache'});
    if (res.ok) VPS = await res.json();
  } catch (e) {}
}
async function suggestNear() {
  await ensurePoints();
  var label = document.getElementById('near-label');
  var sel = document.getElementById('near-vp');
  if (!label || !sel || !reportFix) return;
  var list = (typeof VPS !== 'undefined' && Array.isArray(VPS) ? VPS : []).filter(function (v) {
    return typeof finiteCoord === 'function' && finiteCoord(v.lat, v.lon);
  }).map(function (v) {
    return {v: v, km: kmBetween(reportFix.lat, reportFix.lon, Number(v.lat), Number(v.lon))};
  }).sort(function (a, b) { return a.km - b.km; });
  while (sel.firstChild) sel.removeChild(sel.firstChild);
  var blank = document.createElement('option');
  blank.value = '';
  blank.textContent = 'בלי נקודה מהרשימה';
  sel.appendChild(blank);
  list.slice(0, 12).forEach(function (row) {
    var o = document.createElement('option');
    o.value = row.v.id;
    o.textContent = (row.v.name_he || row.v.id) + ' · ' + (row.v.nahal || '') + ' · ' + row.km.toFixed(1) + ' ק"מ';
    sel.appendChild(o);
  });
  if (list.length && list[0].km <= 40) {
    sel.value = list[0].v.id;
    label.textContent = 'הכי קרוב: ' + (list[0].v.name_he || '') + ' (' + (list[0].v.nahal || '') + '), כ-' + list[0].km.toFixed(1) + ' ק"מ. אפשר לבחור נקודה אחרת.';
  } else {
    label.textContent = 'אין נקודת תצפית קרובה מ-40 ק"מ. אפשר לבחור מהרשימה או להשאיר ריק.';
  }
}
function askGps() {
  setStatus('gps-status', 'מאתרים את המכשיר…');
  if (!navigator.geolocation) { setStatus('gps-status', 'הדפדפן לא נותן מיקום.'); return; }
  navigator.geolocation.getCurrentPosition(function (pos) {
    var lat = pos.coords.latitude, lon = pos.coords.longitude, acc = pos.coords.accuracy;
    if (!inIsrael(lat, lon)) {
      reportFix = null;
      setStatus('gps-status', 'המיקום מחוץ לאזור שהאתר מכסה (ישראל). הדיווח לא יישלח.');
      return;
    }
    reportFix = {lat: lat, lon: lon, accuracy: acc, adjusted: false};
    placePin(lat, lon);
    suggestNear();
    setStatus('gps-status', 'מיקום נקלט. דיוק כ-' + Math.round(acc) + ' מטר. אפשר לגרור את הסיכה.');
  }, function () {
    setStatus('gps-status', 'לא התקבל מיקום. צריך לאשר גישה ל-GPS כדי לדווח.');
  }, {enableHighAccuracy: true, timeout: 15000, maximumAge: 0});
}
async function onPhoto(file) {
  photoJpeg = null; photoTaken = null;
  var preview = document.getElementById('photo-preview');
  if (!file) { if (preview) preview.classList.remove('on'); setStatus('photo-status', ''); return; }
  if (!/^image\//.test(file.type || '')) { setStatus('photo-status', 'צריך קובץ תמונה.'); return; }
  var taken = null;
  try { taken = readJpegCaptureTime(await file.arrayBuffer()); } catch (e) { taken = null; }
  var bmp;
  try { bmp = await createImageBitmap(file); }
  catch (e) { setStatus('photo-status', 'לא הצלחנו לקרוא את התמונה במכשיר הזה.'); return; }
  var maxEdge = 1600, scale = Math.min(1, maxEdge / Math.max(bmp.width, bmp.height));
  var w = Math.max(1, Math.round(bmp.width * scale)), h = Math.max(1, Math.round(bmp.height * scale));
  var canvas = document.createElement('canvas');
  canvas.width = w; canvas.height = h;
  canvas.getContext('2d').drawImage(bmp, 0, 0, w, h);
  if (bmp.close) bmp.close();
  var q = 0.82, blob = null;
  while (q >= 0.45) {
    blob = await new Promise(function (resolve) { canvas.toBlob(resolve, 'image/jpeg', q); });
    if (blob && blob.size <= 2.6 * 1024 * 1024) break;
    q -= 0.08;
  }
  if (!blob || blob.size > 3 * 1024 * 1024) { setStatus('photo-status', 'התמונה גדולה מ-3 מגה אחרי הקטנה.'); return; }
  photoJpeg = await new Promise(function (resolve, reject) {
    var reader = new FileReader();
    reader.onload = function () { resolve(String(reader.result).split(',')[1]); };
    reader.onerror = function () { reject(reader.error); };
    reader.readAsDataURL(blob);
  });
  photoTaken = taken;
  if (preview) {
    var ctx = preview.getContext('2d');
    var pw = preview.width, ph = preview.height, s = Math.min(pw / w, ph / h);
    ctx.clearRect(0, 0, pw, ph);
    ctx.drawImage(canvas, (pw - w * s) / 2, (ph - h * s) / 2, w * s, h * s);
    preview.classList.add('on');
  }
  setStatus('photo-status', 'התמונה הוקטנה ל-JPEG בלי נתוני מיקום.' + (taken ? ' זמן הצילום נשמר בנפרד.' : ''));
}
function selectedWave() {
  var n = document.querySelector('input[name="wave"]:checked');
  return n ? n.value : '';
}
function buildReport() {
  if (!reportFix || !inIsrael(reportFix.lat, reportFix.lon)) throw new Error('צריך מיקום GPS בתוך ישראל.');
  if (!photoJpeg) throw new Error('צריך תמונה.');
  var wave = selectedWave();
  if (!REPORT_WAVES[wave]) throw new Error('צריך לבחור אם זה גל ראשון או שהנחל כבר זורם.');
  var unknown = document.getElementById('first-wave-unknown').checked;
  var when = document.getElementById('first-wave-time').value;
  if (wave === 'already_flowing' && !unknown && when && !/^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}$/.test(when)) throw new Error('שעת הגל הראשון לא תקינה.');
  var flow = document.getElementById('flow').value;
  if (flow && !REPORT_FLOWS[flow]) throw new Error('עוצמת הזרימה לא תקינה.');
  var note = document.getElementById('report-note').value.trim();
  if (note.length > 500) throw new Error('ההערה ארוכה מדי.');
  var sel = document.getElementById('near-vp');
  var vp = sel && sel.value && /^VP\d{2}$/.test(sel.value) ? sel.value : '';
  var stream = '';
  if (vp && Array.isArray(VPS)) {
    var found = VPS.filter(function (v) { return v.id === vp; })[0];
    if (found && found.nahal) stream = String(found.nahal).slice(0, 40);
  }
  return {
    action: 'report',
    report_id: rid(),
    device_id: UID,
    lat: Math.round(reportFix.lat * 1e5) / 1e5,
    lon: Math.round(reportFix.lon * 1e5) / 1e5,
    accuracy_m: reportFix.adjusted ? null : Math.round(reportFix.accuracy),
    location_adjusted: !!reportFix.adjusted,
    viewpoint_id: vp,
    stream: stream,
    wave: wave,
    first_wave_time: wave === 'already_flowing' && !unknown ? (when || '') : '',
    first_wave_unknown: wave === 'already_flowing' && !!unknown,
    flow: flow || '',
    note: note,
    photo_taken_at: photoTaken || '',
    reported_at: new Date().toISOString(),
    photo_jpeg_base64: photoJpeg
  };
}
async function sendOrQueue(body, statusId) {
  var rec = {id: body.report_id || body.feedback_id, body: body};
  try {
    await postPrivate(body);
    setStatus(statusId, 'נשלח לגיליון הפרטי.');
  } catch (e) {
    try { await outboxPut(rec); }
    catch (err) { setStatus(statusId, 'לא הצלחנו לשמור את הדיווח במכשיר.'); return; }
    setStatus(statusId, e.message === 'noserver'
      ? 'נשמר במכשיר. שרת הדיווחים עוד לא הוגדר, והשליחה תתבצע כשיוגדר.'
      : 'אין חיבור. הדיווח נשמר במכשיר ויישלח כשהרשת תחזור.');
  }
}
async function submitReport() {
  var body;
  try { body = buildReport(); }
  catch (e) { setStatus('report-status', e.message || 'הדיווח לא מלא.'); return; }
  await sendOrQueue(body, 'report-status');
}
function fillFeedbackPoints() {
  var sel = document.getElementById('fb-point');
  if (!sel) return;
  var current = sel.value;
  while (sel.firstChild) sel.removeChild(sel.firstChild);
  var blank = document.createElement('option');
  blank.value = '';
  blank.textContent = 'בלי נקודה מסוימת';
  sel.appendChild(blank);
  (Array.isArray(VPS) ? VPS : []).forEach(function (v) {
    if (!/^VP\d{2}$/.test(v.id || '')) return;
    var o = document.createElement('option');
    o.value = v.id;
    o.textContent = (v.name_he || v.id) + (v.nahal ? ' · ' + v.nahal : '');
    sel.appendChild(o);
  });
  if (current) sel.value = current;
}
function feedbackKind() {
  var n = document.querySelector('input[name="fb-kind"]:checked');
  return n ? n.value : 'forecast';
}
function buildFeedback() {
  var kind = feedbackKind();
  if (kind !== 'forecast' && kind !== 'app') throw new Error('סוג המשוב לא תקין.');
  var rating = document.getElementById('fb-rating').value;
  var text = document.getElementById('fb-text').value.trim();
  if (kind === 'forecast' && !FEEDBACK_RATINGS[rating]) throw new Error('בחרו מה קרה עם ההתרעה.');
  if (kind === 'app' && text.length < 2) throw new Error('כתבו בקצרה מה לשפר באפליקציה.');
  if (text.length > 500) throw new Error('הטקסט ארוך מדי.');
  var point = document.getElementById('fb-point').value;
  if (point && !/^VP\d{2}$/.test(point)) point = '';
  var contactOk = document.getElementById('fb-contact-ok').checked;
  var contact = contactOk ? document.getElementById('fb-contact').value.trim().slice(0, 80) : '';
  return {
    action: 'feedback',
    feedback_id: rid(),
    device_id: UID,
    kind: kind,
    point_id: kind === 'forecast' ? point : '',
    rating: kind === 'forecast' ? rating : '',
    text: text,
    contact_ok: contactOk,
    contact: contact,
    reported_at: new Date().toISOString()
  };
}
async function submitFeedback() {
  var body;
  try { body = buildFeedback(); }
  catch (e) { setStatus('fb-status', e.message || 'המשוב לא מלא.'); return; }
  await sendOrQueue(body, 'fb-status');
}
function openReport() {
  ensureReportMap();
  if (!reportFix) askGps();
  else { placePin(reportFix.lat, reportFix.lon); suggestNear(); }
  flushOutbox();
}
function openFeedback() {
  fillFeedbackPoints();
  document.getElementById('fb-forecast').hidden = feedbackKind() !== 'forecast';
  flushOutbox();
}
document.getElementById('gps-btn').addEventListener('click', askGps);
document.getElementById('report-photo').addEventListener('change', function (e) { onPhoto(e.target.files && e.target.files[0]); });
document.getElementById('report-send').addEventListener('click', function () { submitReport(); });
document.querySelectorAll('input[name="wave"]').forEach(function (n) {
  n.addEventListener('change', function () {
    document.getElementById('first-wave-box').hidden = selectedWave() !== 'already_flowing';
  });
});
document.getElementById('first-wave-unknown').addEventListener('change', function (e) {
  document.getElementById('first-wave-time').disabled = e.target.checked;
});
document.querySelectorAll('input[name="fb-kind"]').forEach(function (n) {
  n.addEventListener('change', function () {
    document.getElementById('fb-forecast').hidden = feedbackKind() !== 'forecast';
  });
});
document.getElementById('fb-contact-ok').addEventListener('change', function (e) {
  document.getElementById('fb-contact').hidden = !e.target.checked;
});
document.getElementById('fb-send').addEventListener('click', function () { submitFeedback(); });
window.addEventListener('online', function () { flushOutbox(); });
if (location.hash === '#report') openReport();
if (location.hash === '#feedback') openFeedback();
