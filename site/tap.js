// Tap any map location for a basin estimate. Saved points stay on the device and ride along in the push subscription.
var tapCache = null, myLayer = null, suppressTapClick = false;

function loadMyPoints() {
  try {
    var raw = JSON.parse(localStorage.myPoints || '[]');
    if (!Array.isArray(raw)) return [];
    return raw.filter(function (p) {
      if (!p || !/^M[a-z0-9]{6,16}$/.test(p.id) || !inIsrael(Number(p.lat), Number(p.lon))) return false;
      var seg = parseInt(p.seg, 10);
      if (isFinite(seg) && seg >= 0 && seg <= 20000) return true;
      return /^[0-9]{3,8}$/.test(String(p.sid)) && isFinite(Number(p.along));
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
    if (!p) return null;
    var lat = Math.round(Number(p.lat) * 1e5) / 1e5, lon = Math.round(Number(p.lon) * 1e5) / 1e5;
    var seg = parseInt(p.seg, 10);
    if (p.out_of_coverage) return null;
    if (isFinite(seg) && seg >= 0 && seg <= 20000) {
      var row = {id: p.id, seg: seg, sid: String(p.sid || ''), lat: lat, lon: lon};
      if (p.region === 'north_center') {
        row.region = 'north_center';
        if (p.nd_geom_version) row.nd_geom_version = p.nd_geom_version;
      } else if (p.dg_geom_version) row.dg_geom_version = p.dg_geom_version;
      return row;
    }
    return {id: p.id, sid: String(p.sid), along: Math.round(Number(p.along) * 1000) / 1000, lat: lat, lon: lon};
  }).filter(Boolean);
}
function loadTapData() {
  if (tapCache) return tapCache;
  function geo(url) { return fetch(url, {cache: 'no-cache'}).then(function (r) { return r.ok ? r.json() : {features: []}; }); }
  tapCache = Promise.all([
    geo('data/risk_live.geojson'),
    geo('data/channel_segments.geojson'),
    fetch('data/segment_risk.json', {cache: 'no-cache'}).then(function (r) { return r.ok ? r.json() : null; }).catch(function () { return null; }),
    geo('data/channel_segments_nondesert.geojson'),
    fetch('data/segment_risk_nondesert.json', {cache: 'no-cache'}).then(function (r) { return r.ok ? r.json() : null; }).catch(function () { return null; }),
    fetch('data/id_map_nondesert_v2_to_v3b.json', {cache: 'no-cache'}).then(function (r) { return r.ok ? r.json() : {}; }).catch(function () { return {}; }),
    geo('data/coverage.geojson'),
    fetch('data/risk_nondesert.geojson', {cache: 'no-cache'}).then(function (r) { return r.ok ? r.text() : ''; }).then(function (t) {
      if (!t) return {features: []};
      try { return JSON.parse(t.replace(/\bNaN\b/g, 'null')); } catch (e) { return {features: []}; }
    }).catch(function () { return {features: []}; })
  ]).then(function (pair) {
    var nahal = {};
    (pair[0].features || []).forEach(function (f) {
      var p = f.properties || {};
      if (p.sid != null && p.main_nahal) nahal[String(p.sid)] = String(p.main_nahal);
    });
    var lines = [];
    (pair[1].features || []).forEach(function (f) {
      var g = f.geometry, p = f.properties || {};
      if (!g || g.type !== 'LineString' || !g.coordinates || g.coordinates.length < 2) return;
      var id = parseInt(p.id, 10);
      if (!isFinite(id)) return;
      lines.push({coords: g.coordinates, id: id, name: p.name || '', nameHe: p.name_he || '', flowsInto: p.flows_into || '', mainNahal: p.main_nahal || '', area: Number(p.a), basin: p.b != null ? String(p.b) : '', region: 'desert', perennial: false});
    });
    var northLines = [];
    (pair[3].features || []).forEach(function (f) {
      var g = f.geometry, p = f.properties || {};
      if (!g || g.type !== 'LineString' || !g.coordinates || g.coordinates.length < 2) return;
      var id = parseInt(p.id, 10);
      if (!isFinite(id)) return;
      northLines.push({coords: g.coordinates, id: id, name: p.name || '', nameHe: p.name_he || '', flowsInto: p.flows_into || '', mainNahal: p.main_nahal || '', area: Number(p.a), basin: p.b != null ? String(p.b) : '', region: 'north', perennial: p.p === 1 || p.p === true});
    });
    var geomVersion = (pair[3] && pair[3].nd_geom_version) || (typeof ND_GEOM_VERSION !== 'undefined' ? ND_GEOM_VERSION : 'v3b');
    var northSids = {};
    northLines.forEach(function (line) { if (line.basin) northSids[line.basin] = 1; });
    ((pair[7] && pair[7].features) || []).forEach(function (f) {
      var sid = f.properties && f.properties.sid;
      if (sid != null) northSids[String(sid)] = 1;
    });
    return {nahal: nahal, lines: lines, northLines: northLines, risk: pair[2], northRisk: pair[4], fc: pair[0], coverage: (pair[6] && pair[6].features) || [], northSids: northSids, idMap: pair[5] || {}, ndGeomVersion: geomVersion, dgGeomVersion: (pair[1] && pair[1].desert_geom_version) || DESERT_GEOM_VERSION};
  });
  return tapCache;
}
function segmentLabel(line, nahal) {
  if (line.name) return streamTitle(line.name);
  var n = nahal[line.basin] || '';
  if (!n) return 'יובל';
  return 'יובל של ' + (String(n).indexOf('נחל') === 0 ? n : 'נחל ' + n);
}
function bareStream(value) {
  return String(value || '').replace(/^נחל\s+/, '').trim();
}
function placeName(value) {
  var s = String(value || '').replace(/[\u0000-\u001f<>]/g, '').trim();
  if (!s) return '';
  if (s.indexOf('נחל ') === 0) return s;
  var body = s.replace(/^ה/, '');
  if (/^(ים|מפרץ)(\s|$)/.test(s) || /^(ים|מפרץ)(\s|$)/.test(body)) return s;
  return 'נחל ' + s;
}
// Named segment: "נחל X" or "נחל X, יובל של נחל Y", plus "נשפך אל: Z" when it adds a place.
function segmentTitle(line) {
  var he = String(line.nameHe || '').trim();
  var name = he || String(line.name || '').trim();
  if (!name) return null;
  var main = String(line.mainNahal || '').trim();
  var flows = String(line.flowsInto || '').trim();
  var title = (main && bareStream(name) !== bareStream(main))
    ? placeName(name) + ', יובל של ' + placeName(main)
    : placeName(name);
  var flowsLine = '';
  if (flows && bareStream(flows) !== bareStream(name) && (!main || bareStream(flows) !== bareStream(main))) {
    flowsLine = 'נשפך אל: ' + placeName(flows);
  }
  return {title: title, flowsLine: flowsLine};
}
function distLabel(m) {
  if (m >= 1000) return (m / 1000).toFixed(1) + ' ק"מ';
  return Math.round(m) + ' מ׳';
}
function streamTitle(nahal) {
  var s = String(nahal || '').replace(/[\u0000-\u001f<>]/g, '').trim();
  if (!s) return 'ערוץ';
  return s.indexOf('נחל') === 0 ? s : 'נחל ' + s;
}
var snapGfx = null;
function clearSnapGfx() {
  if (snapGfx) { map.removeLayer(snapGfx.group); snapGfx = null; }
}
function showSnapGfx(tapLat, tapLon, markLat, markLon, onDragEnd) {
  clearSnapGfx();
  var group = L.layerGroup().addTo(map);
  var moved = _hav(tapLat, tapLon, markLat, markLon) > 0.015;
  var line = L.polyline([[tapLat, tapLon], [markLat, markLon]], {color: '#0b4f6c', weight: 2, dashArray: '6 6', interactive: false, opacity: moved ? 1 : 0}).addTo(group);
  if (moved) L.circleMarker([tapLat, tapLon], {radius: 5, color: '#0b4f6c', weight: 2, fillColor: '#fff', fillOpacity: 1, interactive: false}).addTo(group);
  var marker = L.marker([markLat, markLon], {draggable: true, zIndexOffset: 800, icon: L.divIcon({className: 'pin', iconSize: [18, 18], iconAnchor: [9, 9]})}).addTo(group);
  marker.on('dragstart', function () { suppressTapClick = true; });
  marker.on('drag', function () {
    if (!snapGfx || !snapGfx.line) return;
    var p = marker.getLatLng();
    snapGfx.line.setLatLngs([[tapLat, tapLon], [p.lat, p.lng]]);
  });
  marker.on('dragend', function () {
    var p = marker.getLatLng();
    suppressTapClick = true;
    if (onDragEnd) onDragEnd(p.lat, p.lng);
  });
  snapGfx = {group: group, line: line || null, marker: marker, tapLat: tapLat, tapLon: tapLon};
}
function northEnabled() {
  var box = document.getElementById('north');
  return !box || box.checked;
}
function linesForSnap(data) {
  var lines = data.lines || [];
  if (northEnabled() && data.northLines && data.northLines.length) return lines.concat(data.northLines);
  return lines;
}
function nameSegmentHits(hits, lines, nahal) {
  var named = [], seen = {};
  hits.forEach(function (h) {
    var line = lines[h.index];
    if (!line) return;
    var key = (line.region || 'desert') + ':' + line.id;
    if (seen[key]) return;
    seen[key] = 1;
    var area = isFinite(line.area) ? line.area : null;
    var titled = segmentTitle(line);
    var label = titled ? titled.title : (line.region === 'north'
      ? (line.perennial ? 'צפון/מרכז – נחל איתן' : 'צפון/מרכז – נחל אכזב')
      : segmentLabel(line, nahal || {}));
    named.push({name: label, flowsLine: titled ? titled.flowsLine : '', stream: line.name || '', lat: h.lat, lon: h.lon, distM: h.distM, seg: line.id, area: area, basin: line.basin, region: line.region || 'desert', perennial: !!line.perennial});
  });
  return named;
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
  box.appendChild(el('div', null, 'בודקים את הערוץ…'));
  var popW = Math.min(250, Math.max(160, (window.innerWidth || 320) - 36));
  L.popup({maxWidth: popW, autoPan: true, autoPanPaddingTopLeft: L.point(12, 200), autoPanPaddingBottomRight: L.point(12, 120)}).setLatLng([lat, lon]).setContent(box).openOn(map);
  loadTapData().then(function (data) {
    resolveTap(box, lat, lon, lat, lon, data, true);
  }).catch(function () {
    box.textContent = 'לא הצלחנו לטעון את שכבת הערוצים.';
  });
}
function hitsWithin(data, lat, lon) {
  var lines = linesForSnap(data);
  var tol = snapToleranceMeters(lat, map.getZoom());
  var ranked = closestStreams(lines, lat, lon, 4);
  var within = [];
  for (var i = 0; i < ranked.length; i++) if (ranked[i].distM <= tol) within.push(ranked[i]);
  return {tol: tol, lines: lines, ranked: ranked, choices: nameSegmentHits(within, lines, data.nahal)};
}
function resolveTap(box, tapLat, tapLon, lat, lon, data, fresh) {
  var hit = hitsWithin(data, lat, lon);
  if (hit.choices.length) {
    var picked = hit.choices[0];
    if (fresh) {
      showSnapGfx(tapLat, tapLon, picked.lat, picked.lon, function (la, lo) {
        resolveTap(box, tapLat, tapLon, la, lo, data, false);
      });
    } else if (snapGfx) {
      if (snapGfx.marker) snapGfx.marker.setLatLng([picked.lat, picked.lon]);
      if (snapGfx.line) {
        var show = _hav(tapLat, tapLon, picked.lat, picked.lon) > 0.015;
        snapGfx.line.setStyle({opacity: show ? 1 : 0});
        snapGfx.line.setLatLngs([[tapLat, tapLon], [picked.lat, picked.lon]]);
      }
    }
    paintTap(box, tapLat, tapLon, picked, hit.choices, data, picked.lat, picked.lon, hit.tol);
    return;
  }
  if (fresh) {
    showSnapGfx(tapLat, tapLon, lat, lon, function (la, lo) {
      resolveTap(box, tapLat, tapLon, la, lo, data, false);
    });
  } else if (snapGfx) {
    if (snapGfx.marker) snapGfx.marker.setLatLng([lat, lon]);
    if (snapGfx.line) snapGfx.line.setStyle({opacity: 0});
  }
  data._snapLines = hit.lines;
  paintBasin(box, lat, lon, data, hit.ranked[0] || null);
}
function segRisk(data, seg, region) {
  var north = region === 'north' || region === 'north_center';
  var r = north ? data.northRisk : data.risk;
  if (!r || !r.p || seg < 0 || seg >= r.p.length) return null;
  var em = r.em ? r.em[seg] : -1;
  var when = null;
  if (em != null && em !== -1 && r.t0) when = new Date((r.t0 + em * 60) * 1000);
  return {p: Number(r.p[seg]), rain: r.rain ? Number(r.rain[seg]) : null, lead: r.lead ? r.lead[seg] : null, tp: r.tp ? r.tp[seg] : null, tm: r.tm ? r.tm[seg] : null, when: when, strong: r.strong ? r.strong[seg] : 0};
}
function paintTap(box, tapLat, tapLon, picked, choices, data, lat, lon, tol) {
  while (box.firstChild) box.removeChild(box.firstChild);
  if (map._popup) map._popup.setLatLng([lat, lon]);
  if (!picked) {
    box.appendChild(el('b', null, 'אין ערוץ במפה'));
    box.appendChild(el('p', 'muted', 'שכבת הערוצים לא נטענה, אז אין חישוב לנקודה.'));
    if (map._popup) map._popup.update();
    return;
  }
  if (choices && choices.length > 1) {
    box.appendChild(el('div', 'muted', 'יותר מערוץ אחד בטווח של ' + Math.round(tol) + ' מ׳. בחרו:'));
    choices.forEach(function (c) {
      var area = c.area == null ? '' : ' · ' + (c.area < 10 ? c.area.toFixed(1) : Math.round(c.area)) + ' קמ"ר';
      var b = el('button', 'btn alt', c.name + area + ' · ' + distLabel(c.distM));
      b.type = 'button';
      b.addEventListener('click', function () {
        if (snapGfx && snapGfx.marker) snapGfx.marker.setLatLng([c.lat, c.lon]);
        if (snapGfx && snapGfx.line) snapGfx.line.setLatLngs([[tapLat, tapLon], [c.lat, c.lon]]);
        paintTap(box, tapLat, tapLon, c, choices, data, c.lat, c.lon, tol);
      });
      box.appendChild(b);
    });
  }
  fillSegment(box, picked, data, tol);
  if (map._popup) map._popup.update();
}
function fillSegment(root, hit, data, tol) {
  var risk = segRisk(data, hit.seg, hit.region);
  root.appendChild(el('b', null, hit.name));
  if (hit.flowsLine) root.appendChild(el('div', null, hit.flowsLine));
  root.appendChild(el('div', 'muted', 'נצמד לערוץ, ' + distLabel(hit.distM) + ' מההקשה.'));
  if (hit.region === 'north') {
    root.appendChild(el('div', 'muted', 'מודל צפון/מרכז — פחות מדויק, מבוסס תחנות הידרומטריות'));
    root.appendChild(el('div', 'muted', 'במודל צפון ומרכז האתראה מתייחסת לעליית ספיקה חריגה בתחנת המדידה, לא לבטיחות חצייה'));
  }
  var areaTxt = hit.area == null ? '—' : (hit.area < 10 ? hit.area.toFixed(1) : String(Math.round(hit.area)));
  root.appendChild(el('div', null, 'שטח מעלה: ' + areaTxt + ' קמ"ר'));
  if (hit.area != null && hit.area < 10) root.appendChild(el('div', 'muted', 'שטח המעלה קטן, לכן הסיכוי מוגבל.'));
  if (!risk || !isFinite(risk.p)) {
    root.appendChild(el('div', 'muted', 'התחזית השעתית לערוץ הזה עדיין לא נטענה. אין כאן סיכוי או זמן גל.'));
  } else {
    var prob = risk.p;
    root.appendChild(el('div', null, 'סיכוי לשיטפון בנקודה: ' + Math.round(prob * 100) + '% · ' + riskClass(prob)));
    root.appendChild(el('div', null, 'גשם חזוי במעלה: ' + (risk.rain == null || !isFinite(risk.rain) ? '—' : risk.rain) + ' מ"מ'));
    var medH = risk.tm != null ? risk.tm / 60 : null, p10H = risk.tp != null ? risk.tp / 60 : null;
    if (medH != null) {
      var line = 'הערכה בלבד: זמן הזרימה האופייני עד לקצה המקטע הוא ' + (fmtHours(medH) || '—');
      if (p10H != null && Math.abs(p10H - medH) > 0.2) line += ' (תרחיש מהיר ' + fmtHours(p10H) + ')';
      line += '.';
      root.appendChild(el('div', null, line));
    }
    if (hit.region === 'north' && risk.strong) root.appendChild(el('div', null, 'יש גם סימן לשיטפון חזק יותר בתחנה.'));
    if (prob >= 0.05 && risk.when) {
      var until = risk.lead != null ? risk.lead : (risk.when.getTime() - Date.now()) / 3600000;
      var when = until < 0 ? 'לפי ההערכה הגל כבר אמור היה להגיע או לעבור.' : ('הגל הראשון משוער בסביבות ' + ilClock(risk.when) + ' (' + fmtHours(Math.max(0, until)) + ').');
      root.appendChild(el('div', 'muted', when + ' זה זמן ההגעה לנקודה הזו, לא למוצא האגן.'));
    } else {
      root.appendChild(el('div', 'muted', 'אין כרגע סיכוי ממשי לגל בנקודה הזו.'));
    }
  }
  var regionKey = hit.region === 'north' ? 'north_center' : '';
  var saved = loadMyPoints().some(function (x) { return parseInt(x.seg, 10) === hit.seg && (x.region || '') === regionKey; });
  var btn = el('button', 'btn', saved ? 'הערוץ הזה כבר שמור' : 'שמור כנקודה שלי');
  btn.type = 'button';
  if (!saved) btn.addEventListener('click', function () {
    var id = 'M' + Math.random().toString(36).slice(2, 10);
    var list = loadMyPoints().filter(function (x) { return !(parseInt(x.seg, 10) === hit.seg && (x.region || '') === regionKey); });
    var savedPoint = {id: id, lat: Math.round(hit.lat * 1e5) / 1e5, lon: Math.round(hit.lon * 1e5) / 1e5, seg: hit.seg, sid: hit.basin || '', name: hit.stream || hit.name};
    if (hit.region === 'north') {
      savedPoint.region = 'north_center';
      savedPoint.nd_geom_version = (data && data.ndGeomVersion) || ND_GEOM_VERSION;
      savedPoint.out_of_coverage = false;
    } else savedPoint.dg_geom_version = (data && data.dgGeomVersion) || DESERT_GEOM_VERSION;
    list.unshift(savedPoint);
    storeMyPoints(list);
    btn.textContent = 'נשמרה. ההתראות יכללו את הערוץ.';
  });
  root.appendChild(btn);
}
function mappedChannelNote(near, nahal) {
  if (!near) return '';
  var name = '';
  if (near.stream) name = streamTitle(near.stream);
  else if (near.basin && nahal && nahal[near.basin]) name = streamTitle(nahal[near.basin]);
  else if (near.name) name = String(near.name);
  if (!name) return '';
  return 'הערוץ הממופה הקרוב: ' + name + ', במרחק ' + distLabel(near.distM);
}
function paintBasin(box, lat, lon, data, nearest) {
  while (box.firstChild) box.removeChild(box.firstChild);
  if (map._popup) map._popup.setLatLng([lat, lon]);
  var hasCoverage = !!(data.coverage && data.coverage.length);
  var region = hasCoverage ? coverageRegion(data.coverage, lat, lon) : null;
  var feature = liveBasin((data.fc && data.fc.features) || [], lat, lon, data.northSids);
  // coverage.geojson is the mask. A published polygon outside it is not a forecast.
  if (hasCoverage && !region) feature = null;
  var near = nearest && data._snapLines ? nameSegmentHits([nearest], data._snapLines, data.nahal)[0] : null;
  var note = mappedChannelNote(near, data.nahal);
  if (!feature && !region) {
    box.appendChild(el('b', null, 'מחוץ לאזור הכיסוי'));
    if (note) box.appendChild(el('div', 'muted coverage-note', note));
  } else if (!feature) {
    // Inside the mask, but the published basins have no polygon here (for example Bezeq, which is only in the withheld geometry).
    box.appendChild(el('b', null, 'בתוך אזור הכיסוי'));
    box.appendChild(el('p', 'muted', 'אין אגן במודל שמפורסם כרגע לנקודה הזו, אז אין סיכוי ואין זמן הגעה.'));
    if (note) box.appendChild(el('div', 'muted coverage-note', note));
  } else {
    var p = feature.properties || {};
    var prob = Number(p.risk);
    if (!isFinite(prob)) prob = null;
    box.appendChild(el('b', null, txt(p.name_he || p.main_nahal, 'אגן')));
    box.appendChild(el('div', 'muted', 'הנקודה אינה על ערוץ מסומן — מוצג לפי האגן'));
    box.appendChild(el('div', null, 'סיכוי לשיטפון באגן: ' + (prob == null ? '—' : Math.round(prob * 100) + '%') + (prob == null ? '' : ' · ' + riskClass(prob))));
    var rain = p.event_rain_mm;
    box.appendChild(el('div', null, 'גשם חזוי באגן: ' + (rain == null || rain === '' ? '—' : rain) + ' מ"מ'));
    if (near) box.appendChild(el('div', 'muted', 'הערוץ המסומן הקרוב: ' + near.name + ', במרחק ' + distLabel(near.distM) + '.'));
    var saved = loadMyPoints().some(function (x) { return x.seg == null && x.sid === String(p.sid) && Math.abs(x.lat - lat) < 0.002 && Math.abs(x.lon - lon) < 0.002; });
    var btn = el('button', 'btn', saved ? 'הנקודה הזו כבר שמורה' : 'שמור כנקודה שלי');
    btn.type = 'button';
    if (!saved && p.sid != null) btn.addEventListener('click', function () {
      var id = 'M' + Math.random().toString(36).slice(2, 10);
      var along = alongBasin(feature, lat, lon);
      var list = loadMyPoints().filter(function (x) { return Math.hypot((x.lat - lat) * 111, (x.lon - lon) * 111) > 0.3; });
      list.unshift({id: id, lat: Math.round(lat * 1e5) / 1e5, lon: Math.round(lon * 1e5) / 1e5, sid: String(p.sid), along: Math.round(along * 1000) / 1000, name: txt(p.name_he || p.main_nahal, 'הנקודה שלי')});
      storeMyPoints(list);
      btn.textContent = 'נשמרה. ההתראות יכללו את האגן.';
    });
    box.appendChild(btn);
  }
  if (map._popup) map._popup.update();
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
    var label = txt(p.name, 'נקודה') + (p.out_of_coverage ? ' · מחוץ לאזור הכיסוי' : '');
    var chip = el('span', 'chip', '📌 ' + label + ' ');
    var b = el('button', 'unsub', 'בטל התראות');
    b.type = 'button';
    b.addEventListener('click', function () {
      storeMyPoints(loadMyPoints().filter(function (x) { return x.id !== p.id; }));
      if (typeof confirmUnsub === 'function') confirmUnsub('ההתראות לנקודה זו בוטלו.');
    });
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
  ((data.fc && data.fc.features) || []).forEach(function (f) { if (f.properties) bySid[String(f.properties.sid)] = f.properties; });
  list.forEach(function (p) {
    if (p.out_of_coverage) {
      var gap = el('div', 'card');
      gap.appendChild(el('h3', null, txt(p.name, 'הנקודה שלי')));
      gap.appendChild(el('div', null, 'מחוץ לאזור הכיסוי'));
      gap.appendChild(el('div', 'muted', 'אין ערוץ צפון/מרכז בטווח ההצמדה, אז אין סיכוי ואין התראה לנקודה הזו.'));
      host.appendChild(gap);
      return;
    }
    var onChannel = isFinite(parseInt(p.seg, 10));
    var risk = onChannel ? (segRisk(data, p.seg, p.region) || {p: 0, rain: null, tm: null}) : null;
    var prop = onChannel ? null : (bySid[String(p.sid)] || {});
    var prob = onChannel ? (isFinite(risk.p) ? risk.p : 0) : Number(prop.risk);
    if (!isFinite(prob)) prob = 0;
    var card = el('div', 'card al' + (prob >= 0.5 ? ' hi' : prob >= 0.3 ? ' mid' : ''));
    card.appendChild(el('h3', null, txt(p.name, 'הנקודה שלי') + (prob >= (PREFS && PREFS.threshold || 0.3) ? ' · סיכוי מעל הסף' : '')));
    card.appendChild(el('div', 'muted', onChannel ? (p.region === 'north_center' ? 'מודל צפון/מרכז — פחות מדויק, מבוסס תחנות הידרומטריות' : 'נקודה על ערוץ. ההגעה היא הערכה לקצה המקטע.') : 'נקודה שאינה על ערוץ מסומן. ההערכה היא לפי האגן.'));
    card.appendChild(el('div', null, (onChannel ? 'סיכוי בנקודה: ' : 'סיכוי באגן: ') + Math.round(prob * 100) + '% · ' + riskClass(prob)));
    var rain = onChannel ? risk.rain : prop.event_rain_mm;
    card.appendChild(el('div', null, (onChannel ? 'גשם חזוי במעלה: ' : 'גשם חזוי באגן: ') + (rain == null || rain === '' || !isFinite(Number(rain)) && rain !== 0 ? '—' : rain) + ' מ"מ'));
    if (onChannel && risk.tm != null) card.appendChild(el('div', 'muted', 'זמן זרימה משוער עד לקצה המקטע: ' + fmtHours(risk.tm / 60) + '.'));
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
function resnapNorthPoints() {
  var version = (typeof CFG !== 'undefined' && CFG && CFG.nd_geom_version) || ND_GEOM_VERSION;
  return loadTapData().then(function (data) {
    var ver = (data && data.ndGeomVersion) || version;
    var list = loadMyPoints();
    var changed = false;
    var next = list.map(function (p) {
      var res = resnapNorthPoint(p, data.northLines, data.idMap, ver);
      if (res.changed) changed = true;
      var dres = resnapDesertPoint(res.point, data.lines, data.dgGeomVersion);
      if (dres.changed) changed = true;
      return dres.point;
    });
    if (changed) storeMyPoints(next);
    return changed;
  });
}
