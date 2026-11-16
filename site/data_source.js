// radar-live data source. OFF unless data/config.json has radar_live.mode==='on' (set by the hourly job when the repo
// variable RADAR_LIVE_MODE=on). Off: floodFetch(url,opts) is exactly fetch(url,opts) and nothing is added to the page.
// On: the browser reads radar_live/latest.json straight from the radar-live branch (no Pages redeploy), every
// refresh_min (30) minutes and when the tab comes back. A valid, fresh file replaces the five risk files below;
// anything else falls back to the Open-Meteo forecast files with a clear banner. The file has probabilities,
// arrival/lead times and ids only (no rain amounts, no radar values). Same rules as engine/radar_live.py.
(function (root) {
  'use strict';
  var FORBID = /rain|_mm|mm_|^mm$|max24|r24|gauge|station|dbz|precip/i, MM_TEXT = /מ"מ|מ״מ|\bmm\b/;
  var ALLOW = {
    root: ['schema', 'issued_utc', 'engine_sha', 'engine', 'source', 'radar_latest_frame_utc', 'radar_hours_used', 'bias', 'thr', 'desert_seg', 'nondesert_seg', 'desert_basins', 'nondesert_basins', 'alerts', 'desert_geom', 'nd_geom', 'forecast_age_h', 'engine_issued_utc'],
    bias: ['desert', 'north', 'switch'], thr: ['desert', 'north_center'],
    desert_seg: ['v', 't0', 'issued', 'p', 'lead', 'em', 'tp', 'tm'],
    nondesert_seg: ['v', 'region', 't0', 'issued', 'p', 'lead', 'em', 'tp', 'tm', 'strong'],
    desert_basins: ['sid', 'risk', 'rcov'], nondesert_basins: ['sid', 'risk', 'alert', 'strong', 'rcov'],
    alert: ['point', 'name', 'nahal', 'region', 'prob', 'eta_first_wave', 'eta_peak', 'hours_until_first_wave', 'confidence', 'estimate', 'source', 'issued']
  };
  var REQUIRED = ['schema', 'issued_utc', 'source', 'radar_latest_frame_utc', 'radar_hours_used', 'desert_seg', 'nondesert_seg', 'desert_basins', 'nondesert_basins', 'alerts', 'desert_geom', 'nd_geom'];
  var DEF = {max_issue_age_min: 40, max_frame_age_min: 60, max_forecast_age_h: 12, refresh_min: 30,
    expect: {desert_seg: 10821, nondesert_seg: 3432, desert_basins: 569, nondesert_basins: 216, desert_geom: 'v8p', nd_geom: 'v3e', desert_seg_max_null: 1300, nondesert_seg_max_null: 200}};

  function parseUtc(s) {
    if (typeof s !== 'string' || !s.trim()) return null;
    var t = s.trim().replace(' ', 'T');
    if (!/(Z|[+-]\d\d:?\d\d)$/.test(t)) t += 'Z';
    var ms = Date.parse(t);
    return isFinite(ms) ? ms : null;
  }
  function keysOk(o, allowed, err, path) {
    if (!o || typeof o !== 'object' || Array.isArray(o)) { err.push(path + ' not an object'); return; }
    Object.keys(o).forEach(function (k) {
      if (allowed.indexOf(k) < 0) err.push(path + '.' + k + ' not allowed');
      if (FORBID.test(k)) err.push(path + '.' + k + ' forbidden');
    });
  }
  function probs(a, err, name) {
    if (!Array.isArray(a)) { err.push(name + ' not a list'); return 0; }
    var nn = 0;
    for (var i = 0; i < a.length; i++) {
      var x = a[i];
      if (x === null) { nn++; continue; }
      if (typeof x !== 'number' || !isFinite(x) || x < 0 || x > 1) { err.push(name + ' out of range'); return nn; }
    }
    return nn;
  }
  // -> {ok, reason, detail, issueAge, frameAge}
  function validate(J, nowMs, c) {
    c = c || {}; var ex = c.expect || DEF.expect;
    var maxI = Number(c.max_issue_age_min) || DEF.max_issue_age_min, maxF = Number(c.max_frame_age_min) || DEF.max_frame_age_min;
    var maxFc = Number(c.max_forecast_age_h) || DEF.max_forecast_age_h;
    function no(reason, detail) { return {ok: false, reason: reason, detail: detail || ''}; }
    if (!J || typeof J !== 'object' || Array.isArray(J)) return no('schema', 'not an object');
    for (var i = 0; i < REQUIRED.length; i++) if (!(REQUIRED[i] in J)) return no('schema', 'missing ' + REQUIRED[i]);
    if (J.schema !== 1) return no('schema', 'schema');
    var err = [];
    keysOk(J, ALLOW.root, err, 'root');
    ['bias', 'thr', 'desert_seg', 'nondesert_seg', 'desert_basins', 'nondesert_basins'].forEach(function (s) { if (s in J) keysOk(J[s], ALLOW[s], err, s); });
    if (!Array.isArray(J.alerts)) err.push('alerts');
    else J.alerts.forEach(function (a) {
      keysOk(a, ALLOW.alert, err, 'alert');
      if (a && typeof a === 'object') Object.keys(a).forEach(function (k) { if (typeof a[k] === 'string' && MM_TEXT.test(a[k])) err.push('alert text has mm'); });
    });
    if (err.length) return no('schema', err[0]);
    if (J.source !== 'radar' || !(Number(J.radar_hours_used) >= 1)) return no('vm_forecast', String(J.source));
    var iss = parseUtc(J.issued_utc), fr = parseUtc(J.radar_latest_frame_utc);
    if (iss == null || fr == null) return no('schema', 'timestamps');
    var ia = (nowMs - iss) / 60000, fa = (nowMs - fr) / 60000;
    if (ia < -10 || fa < -10 || ia > maxI || fa > maxF) return no('stale', Math.round(ia) + '/' + Math.round(fa) + ' min');
    if (typeof J.forecast_age_h === 'number' && J.forecast_age_h > maxFc) return no('stale', 'forecast part');
    if (J.desert_geom !== ex.desert_geom || J.nd_geom !== ex.nd_geom) return no('geometry', 'geom');
    var ds = J.desert_seg, ns = J.nondesert_seg, db = J.desert_basins, nb = J.nondesert_basins;
    if (!Array.isArray(ds.p) || !Array.isArray(ns.p) || !Array.isArray(db.sid) || !Array.isArray(nb.sid)) return no('schema', 'arrays');
    if (ds.p.length !== ex.desert_seg || ns.p.length !== ex.nondesert_seg || db.sid.length !== ex.desert_basins || nb.sid.length !== ex.nondesert_basins) return no('geometry', 'counts');
    var bad = false;
    [[ds, ['lead', 'em', 'tp', 'tm']], [ns, ['lead', 'em', 'tp', 'tm']]].forEach(function (x) {
      x[1].forEach(function (k) { if (k in x[0] && (!Array.isArray(x[0][k]) || x[0][k].length !== x[0].p.length)) bad = true; });
    });
    if (bad || !Array.isArray(db.risk) || db.risk.length !== db.sid.length || !Array.isArray(nb.risk) || nb.risk.length !== nb.sid.length) return no('geometry', 'lengths');
    var nd = probs(ds.p, err, 'desert'), nn = probs(ns.p, err, 'north');
    probs(db.risk, err, 'desert_basins'); probs(nb.risk, err, 'north_basins');
    J.alerts.forEach(function (a) { if (typeof a.point !== 'string' || (a.prob != null && (typeof a.prob !== 'number' || !isFinite(a.prob) || a.prob < 0 || a.prob > 1))) err.push('alert'); });
    if (err.length) return no('values', err[0]);
    if (nd > (ex.desert_seg_max_null || 1300) || nn > (ex.nondesert_seg_max_null || 200)) return no('values', 'nulls');
    return {ok: true, reason: 'ok', detail: '', issueAge: ia, frameAge: fa};
  }

  // ---- synthesis: same shapes as the forecast files written by engine/run_job.py ----
  function bySid(sids, vals) { var m = {}; for (var i = 0; i < sids.length; i++) m[String(sids[i])] = i; return {idx: m, vals: vals}; }
  function synth(name, J, base) {
    if (name === 'data/segment_risk.json') return J.desert_seg;
    if (name === 'data/segment_risk_nondesert.json') return J.nondesert_seg;
    if (name === 'data/alerts_latest.json') return {issued: J.desert_seg.issued || null, source: 'radar_live/' + (J.engine || 'flood_engine'), stub: false, alerts: J.alerts};
    if (name === 'data/viewpoints.json') {
      var am = {}; J.alerts.forEach(function (a) { am[a.point] = a; });
      return (Array.isArray(base) ? base : []).map(function (v) { var o = {}; for (var k in v) o[k] = v[k]; o.current = am[v.id] || null; return o; });
    }
    if (!base || !Array.isArray(base.features)) return base;
    var desert = name === 'data/risk_live.geojson', B = desert ? J.desert_basins : J.nondesert_basins, m = bySid(B.sid, B.risk);
    var out = {}; for (var k2 in base) out[k2] = base[k2];
    out.issued = J.desert_seg.issued || base.issued; out.source = 'radar_live';
    out.features = base.features.map(function (f) {
      var p = f.properties || {}, i = m.idx[String(p.sid)];
      if (i == null) return f;
      var q = {}; for (var k3 in p) q[k3] = p[k3];
      q.risk = B.risk[i];
      if (desert) { q.risk_live = B.risk[i]; q.eta_peak_rain = null; }
      else { q.alert = !!(B.alert && B.alert[i]); q.strong = !!(B.strong && B.strong[i]); q.risk_raw = null; q.p_sig = null; }
      if (Array.isArray(B.rcov)) q.radar_cov = !!B.rcov[i];
      return {type: f.type, geometry: f.geometry, properties: q};
    });
    return out;
  }
  var MAPPED = {'data/segment_risk.json': 0, 'data/segment_risk_nondesert.json': 0, 'data/alerts_latest.json': 0, 'data/viewpoints.json': 1, 'data/risk_live.geojson': 1, 'data/risk_nondesert.geojson': 1};
  function norm(u) { u = String(u || ''); var q = u.indexOf('?'); if (q >= 0) u = u.slice(0, q); return u.replace(/^\.\//, ''); }

  // ---- state ----
  var C = null, RL = null, state = {mode: 'off', source: 'forecast', reason: 'off'}, okStreak = 0, nChecks = 0, lastCheck = 0, subs = [], timer = null, inflight = null;
  var resolveReady, configured = false, ready = new Promise(function (r) { resolveReady = r; });
  setTimeout(function () { if (!configured) { configured = true; resolveReady(); } }, 5000);

  function getJSON(url, ms) {
    var ctl = typeof AbortController === 'function' ? new AbortController() : null;
    var t = setTimeout(function () { if (ctl) ctl.abort(); }, ms);
    return fetch(url, ctl ? {signal: ctl.signal} : {}).then(function (r) { if (!r.ok) throw r.status; return r.json(); })
      .finally(function () { clearTimeout(t); });
  }
  function check() {
    if (!C) return Promise.resolve(state);
    if (inflight) return inflight;
    lastCheck = Date.now();
    var prev = state.source + '|' + (RL && RL.issued_utc);
    inflight = getJSON(C.url, 6000).catch(function () { return C.fallback_url ? getJSON(C.fallback_url + '?t=' + Math.floor(Date.now() / 600000), 4000) : null; })
      .catch(function () { return null; })
      .then(function (J) {
        var v = J ? validate(J, Date.now(), C) : {ok: false, reason: 'missing'};
        if (v.ok) {
          okStreak++;
          // first check switches at once; after a fallback, two good checks in a row before returning to radar (no flicker)
          if (state.source === 'radar' || state.first !== false || okStreak >= 2) { RL = J; state = {mode: 'on', source: 'radar', reason: 'ok', issued: J.issued_utc, frame: J.radar_latest_frame_utc, first: false}; }
        } else {
          okStreak = 0; RL = null; state = {mode: 'on', source: 'forecast', reason: v.reason, detail: v.detail, first: false};
        }
        renderBanner();
        var now = state.source + '|' + (RL && RL.issued_utc);
        if (now !== prev && nChecks > 0) subs.forEach(function (f) { try { f(state); } catch (e) {} });
        nChecks++;
        return state;
      }).finally(function () { inflight = null; });
    return inflight;
  }

  // ---- banner (only in mode on) ----
  function hm(ms) { try { return new Date(ms).toLocaleTimeString('he-IL', {hour: '2-digit', minute: '2-digit', timeZone: 'Asia/Jerusalem'}); } catch (e) { return ''; } }
  function renderBanner() {
    if (typeof document === 'undefined' || state.mode !== 'on') return;
    var b = document.getElementById('src-banner');
    if (!b) {
      b = document.createElement('div'); b.id = 'src-banner'; b.setAttribute('role', 'status');
      var h = document.querySelector('header');
      if (h && h.parentNode) h.parentNode.insertBefore(b, h.nextSibling); else document.body.insertBefore(b, document.body.firstChild);
    }
    while (b.firstChild) b.removeChild(b.firstChild);
    var main = document.createElement('div'), sub = document.createElement('div'); sub.className = 'src-sub';
    var cfgNow = C && C._siteNow ? Date.parse(C._siteNow) : null, fcAgeH = cfgNow ? (Date.now() - cfgNow) / 3600000 : 0;
    var fcTime = C && C._live ? String(C._live).slice(11, 16) : '';
    if (state.source === 'radar') {
      b.className = 'src-banner src-radar';
      main.textContent = 'מבוסס מכ״ם בזמן אמת · מכ״ם ' + hm(parseUtc(state.frame)) + ' · חושב ' + hm(parseUtc(state.issued));
      sub.textContent = 'משך זרימה ושעות קדימה – לפי תחזית מזג אוויר. הערכת מודל, לא התרעה רשמית.';
    } else if (fcAgeH > 3) {
      b.className = 'src-banner src-old';
      main.textContent = 'הנתונים לא עודכנו מאז ' + (cfgNow ? hm(cfgNow) : fcTime) + ' – ייתכן שאינם עדכניים.';
      sub.textContent = 'נתוני מכ״ם לא זמינים כרגע; מוצגת תחזית מזג אוויר (Open-Meteo).';
    } else {
      b.className = 'src-banner src-forecast';
      main.textContent = '⚠ נתוני מכ״ם לא זמינים כרגע – מוצגת תחזית מזג אוויר (Open-Meteo)' + (fcTime ? ' מ-' + fcTime : '') + '. פחות מדויק לשעות הקרובות.';
    }
    b.appendChild(main); if (sub.textContent) b.appendChild(sub);
    var hdr = document.getElementById('hdr');
    if (hdr) hdr.textContent = state.source === 'radar' ? 'מכ״ם · עודכן ' + hm(parseUtc(state.issued)) : (cfgNow ? 'תחזית · עודכן ' + hm(cfgNow) : hdr.textContent);
  }

  // ---- public API ----
  function configure(cfg) {
    var c = cfg && cfg.radar_live;
    if (c && c.mode === 'on' && typeof c.url === 'string' && /^https:\/\//.test(c.url)) {
      C = {}; for (var k in DEF) C[k] = DEF[k]; for (var k2 in c) C[k2] = c[k2];
      C._siteNow = cfg.now || null; C._live = cfg.live || null;
      state = {mode: 'on', source: 'forecast', reason: 'pending'};
      var every = Math.max(10, Number(C.refresh_min) || 30) * 60000;
      var p = check();
      if (!timer) {
        timer = setInterval(check, every);
        if (typeof document !== 'undefined') document.addEventListener('visibilitychange', function () { if (document.visibilityState === 'visible' && Date.now() - lastCheck >= every) check(); });
      }
      return p.then(function () { if (!configured) { configured = true; resolveReady(); } });
    }
    if (!configured) { configured = true; resolveReady(); }
    return Promise.resolve(state);
  }
  function floodFetch(url, opts) {
    var n = norm(url);
    if (!(n in MAPPED)) return fetch(url, opts);
    if (!configured) return ready.then(function () { return floodFetch(url, opts); });
    if (!RL || state.source !== 'radar') return fetch(url, opts);
    var J = RL;
    var basep = MAPPED[n] ? fetch(url, opts).then(function (r) { return r.ok ? r.json() : null; }).catch(function () { return null; }) : Promise.resolve(null);
    return basep.then(function (base) {
      var o = synth(n, J, base);
      if (o == null) return fetch(url, opts);
      return new Response(JSON.stringify(o), {status: 200, headers: {'Content-Type': 'application/json'}});
    });
  }
  var api = {configure: configure, check: check, validate: validate, synth: synth, parseUtc: parseUtc,
    state: function () { return state; }, onChange: function (f) { subs.push(f); }};
  root.FloodData = api; root.floodFetch = floodFetch;
  if (typeof module !== 'undefined' && module.exports) module.exports = api;
})(typeof window !== 'undefined' ? window : globalThis);
