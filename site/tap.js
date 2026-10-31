// Tap any map location for a basin estimate. Saved points stay on the device and ride along in the push subscription.
var tapCache = null, myLayer = null, suppressTapClick = false;

function loadMyPoints() {
  try {
    var raw = JSON.parse(localStorage.myPoints || '[]');
    if (!Array.isArray(raw)) return [];
    return raw.filter(function (p) {
      return p && /^M[a-z0-9]{6,16}$/.test(p.id) && inIsrael(Number(p.lat), Number(p.lon)) && /^[0-9]{3,8}$/.test(String(p.sid)) && isFinite(Number(p.along));
    }).slice(0, 8);
  } catch (e) { return []; }
}
function storeMyPoints(list) {
  localStorage.myPoints = JSON.stringify(list.slice(0, 8));
  if (typeof syncSub === 'function') syncSub(false);
  drawMyPoints();
  renderMyPointList();
}
function myPointsPayload() {
  return loadMyPoints().map(function (p) {
    return {id: p.id, sid: String(p.sid), along: Math.round(Number(p.along) * 1000) / 1000, lat: Math.round(Number(p.lat) * 1e5) / 1e5, lon: Math.round(Number(p.lon) * 1e5) / 1e5};
  });
}
function loadTapData() {
  if (tapCache) return tapCache;
  tapCache = Promise.all([
    fetch('data/risk_live.geojson', {cache: 'no-cache'}).then(function (r) { return r.ok ? r.json() : {features: []}; }),
    fetch('data/basin_tt.json', {cache: 'no-cache'}).then(function (r) { return r.ok ? r.json() : {}; })
  ]).then(function (pair) { return {fc: pair[0], tt: pair[1]}; });
  return tapCache;
}
function fmtHours(h) {
  if (h == null || !isFinite(h)) return null;
  if (h < 0.25) return 'פחות מרבע שעה';
  var n = Math.round(h);
  if (n <= 1) return 'כשעה';
  return 'כ-' + n + ' שעות';
}
function parseIsrael(s) {
  var m = /^(\d{4})-(\d{2})-(\d{2})[ T](\d{2}):(\d{2})/.exec(String(s || ''));
  if (!m) return null;
  var y = +m[1], mo = +m[2], d = +m[3], h = +m[4], mi = +m[5];
  var asUTC = Date.UTC(y, mo - 1, d, h, mi);
  var dtf = new Intl.DateTimeFormat('en-US', {timeZone: 'Asia/Jerusalem', hourCycle: 'h23', year: 'numeric', month: '2-digit', day: '2-digit', hour: '2-digit', minute: '2-digit'});
  var parts = {};
  dtf.formatToParts(new Date(asUTC)).forEach(function (p) { parts[p.type] = p.value; });
  var seen = Date.UTC(+parts.year, +parts.month - 1, +parts.day, (+parts.hour) % 24, +parts.minute);
  return new Date(asUTC - (seen - asUTC));
}
function ilClock(date) {
  try {
    return new Intl.DateTimeFormat('he-IL', {timeZone: 'Asia/Jerusalem', day: '2-digit', month: '2-digit', hour: '2-digit', minute: '2-digit'}).format(date);
  } catch (e) { return ''; }
}
function openTap(lat, lon) {
  if (!map || !isFinite(lat) || !isFinite(lon)) return;
  var box = el('div');
  box.appendChild(el('div', null, 'בודקים את האגן…'));
  L.popup({maxWidth: 280, autoPan: true}).setLatLng([lat, lon]).setContent(box).openOn(map);
  loadTapData().then(function (data) {
    var hit = locateBasin(data.fc.features || [], lat, lon, data.tt);
    while (box.firstChild) box.removeChild(box.firstChild);
    if (!hit.inside) {
      box.appendChild(el('b', null, 'מחוץ לאגנים במודל'));
      box.appendChild(el('p', 'muted', 'הנקודה הזו לא נופלת באגני המדבר שהתחזית מכירה. אין כאן חישוב — למשל בים, או במקום בלי אגן ממופה.'));
    } else if (!hit.modeled) {
      var other = (hit.feature.properties || {});
      box.appendChild(el('b', null, txt(other.name_he || other.main_nahal, 'אגן לא במודל')));
      box.appendChild(el('p', 'muted', 'המקום נמצא באגן הזה, אבל הוא לא אגן מדבר שהמודל מחשב (למשל נחל איתן או אזור צפוני). אין כאן סיכוי שיטפון מחושב.'));
    } else fillModeled(box, hit, data.tt, lat, lon);
    if (map._popup) map._popup.update();
  }).catch(function () {
    box.textContent = 'לא הצלחנו לטעון את שכבת האגנים.';
  });
}
function fillModeled(root, hit, tt, lat, lon) {
  var p = hit.feature.properties || {};
  var prob = Number(p.risk);
  if (!isFinite(prob)) prob = null;
  var travel = travelHours(tt, hit.sid, hit.along);
  root.appendChild(el('b', null, txt(p.name_he || p.main_nahal, 'אגן')));
  root.appendChild(el('div', 'muted', txt(p.main_nahal, '')));
  root.appendChild(el('div', null, 'סיכוי לשיטפון באגן: ' + (prob == null ? '—' : Math.round(prob * 100) + '%') + ' · ' + riskClass(prob)));
  var rain = p.event_rain_mm;
  root.appendChild(el('div', null, 'גשם חזוי באגן: ' + (rain == null || rain === '' ? '—' : rain) + ' מ"מ'));
  var where = Math.round(hit.along * 100);
  root.appendChild(el('div', 'muted', 'הנקודה בערך ב-' + where + '% מהדרך מקו פרשת המים אל המוצא.'));
  if (travel) {
    var line = 'הערכה בלבד: זמן הזרימה האופייני עד לכאן הוא ' + (fmtHours(travel.med) || '—');
    if (travel.p10 && Math.abs(travel.p10 - travel.med) > 0.2) line += ' (תרחיש מהיר ' + fmtHours(travel.p10) + ')';
    line += '. זו לא מדידה.';
    root.appendChild(el('div', null, line));
    if (prob != null && prob >= 0.05 && p.eta_peak_rain) {
      var peak = parseIsrael(p.eta_peak_rain);
      if (peak) {
        var arrival = new Date(peak.getTime() + travel.med * 3600000);
        var until = (arrival.getTime() - Date.now()) / 3600000;
        var when = until < 0 ? 'לפי ההערכה הגל כבר אמור היה להגיע או לעבור.' : ('הגעה משוערת בסביבות ' + ilClock(arrival) + ' (' + fmtHours(Math.max(0, until)) + ').');
        root.appendChild(el('div', 'muted', 'שיא הסיכון לגשם באגן: ' + txt(p.eta_peak_rain) + '. ' + when));
      }
    } else {
      root.appendChild(el('div', 'muted', 'אין כרגע סיכוי ממשי לגל. הזמן למעלה הוא רק כמה זמן זרימה אופיינית לוקחת עד לכאן.'));
    }
  }
  var saved = loadMyPoints().some(function (x) { return Math.abs(x.lat - lat) < 0.004 && Math.abs(x.lon - lon) < 0.004; });
  var btn = el('button', 'btn', saved ? 'כבר שמורה בנקודות שלי' : 'שמור כנקודה שלי');
  btn.type = 'button';
  if (!saved) btn.addEventListener('click', function () {
    var id = 'M' + Math.random().toString(36).slice(2, 10);
    var list = loadMyPoints().filter(function (x) { return Math.hypot((x.lat - lat) * 111, (x.lon - lon) * 111) > 0.4; });
    list.unshift({id: id, lat: Math.round(lat * 1e5) / 1e5, lon: Math.round(lon * 1e5) / 1e5, sid: hit.sid, along: Math.round(hit.along * 1000) / 1000, name: txt(p.name_he || p.main_nahal, 'הנקודה שלי')});
    storeMyPoints(list);
    btn.textContent = 'נשמרה. ההתראות יכללו אותה.';
  });
  root.appendChild(btn);
}
function drawMyPoints() {
  if (!map || typeof L === 'undefined') return;
  if (myLayer) map.removeLayer(myLayer);
  myLayer = L.layerGroup(loadMyPoints().map(function (p) {
    var mk = L.circleMarker([p.lat, p.lon], {radius: 7, color: '#fff', weight: 2, fillColor: '#f5a400', fillOpacity: 1});
    mk.on('click', function (ev) { if (ev.originalEvent) ev.originalEvent.__vp = 1; openTap(p.lat, p.lon); });
    return mk;
  })).addTo(map);
}
function renderMyPointList() {
  var host = document.getElementById('mypoints');
  if (!host) return;
  while (host.firstChild) host.removeChild(host.firstChild);
  var list = loadMyPoints();
  if (!list.length) { host.textContent = 'הקישו על המפה ושמרו נקודה. היא תיכנס להתראות.'; return; }
  list.forEach(function (p) {
    var chip = el('span', 'chip', '📌 ' + txt(p.name, 'נקודה') + ' ');
    var b = el('button', null, '✕');
    b.type = 'button';
    b.addEventListener('click', function () { storeMyPoints(loadMyPoints().filter(function (x) { return x.id !== p.id; })); });
    chip.appendChild(b);
    host.appendChild(chip);
  });
}
async function appendMyPointAlerts(host) {
  var list = loadMyPoints();
  if (!list.length || !host) return;
  var data;
  try { data = await loadTapData(); } catch (e) { return; }
  var bySid = {};
  (data.fc.features || []).forEach(function (f) { if (f.properties) bySid[String(f.properties.sid)] = f.properties; });
  list.forEach(function (p) {
    var prop = bySid[String(p.sid)] || {};
    var prob = Number(prop.risk);
    if (!isFinite(prob)) prob = 0;
    var travel = travelHours(data.tt, p.sid, p.along);
    var card = el('div', 'card al' + (prob >= 0.5 ? ' hi' : prob >= 0.3 ? ' mid' : ''));
    card.appendChild(el('h3', null, txt(p.name, 'הנקודה שלי') + (prob >= (PREFS && PREFS.threshold || 0.3) ? ' · סיכוי מעל הסף' : '')));
    card.appendChild(el('div', 'muted', 'נקודה אישית על המפה. ההגעה היא הערכה.'));
    card.appendChild(el('div', null, 'סיכוי באגן: ' + Math.round(prob * 100) + '% · ' + riskClass(prob)));
    card.appendChild(el('div', null, 'גשם חזוי באגן: ' + (prop.event_rain_mm == null ? '—' : prop.event_rain_mm) + ' מ"מ'));
    if (travel) card.appendChild(el('div', 'muted', 'זמן זרימה משוער עד לנקודה: ' + fmtHours(travel.med) + '.'));
    host.appendChild(card);
  });
}
function bindTap(target) {
  target.on('click', function (e) {
    if (suppressTapClick) { suppressTapClick = false; return; }
    if (e.originalEvent && e.originalEvent.__vp) return;
    openTap(e.latlng.lat, e.latlng.lng);
  });
  var timer = null, origin = null;
  var container = target.getContainer();
  container.addEventListener('touchstart', function (ev) {
    if (!ev.touches || ev.touches.length !== 1) return;
    var t = ev.touches[0];
    origin = {x: t.clientX, y: t.clientY, lat: null, lon: null};
    var rect = container.getBoundingClientRect();
    var ll = target.containerPointToLatLng(L.point(t.clientX - rect.left, t.clientY - rect.top));
    origin.lat = ll.lat; origin.lon = ll.lng;
    timer = setTimeout(function () { timer = null; suppressTapClick = true; openTap(origin.lat, origin.lon); }, 600);
  }, {passive: true});
  container.addEventListener('touchend', function () { if (timer) clearTimeout(timer); timer = null; }, {passive: true});
  container.addEventListener('touchmove', function (ev) {
    if (!timer || !origin || !ev.touches || !ev.touches[0]) return;
    var t = ev.touches[0];
    if (Math.hypot(t.clientX - origin.x, t.clientY - origin.y) > 12) { clearTimeout(timer); timer = null; }
  }, {passive: true});
}
