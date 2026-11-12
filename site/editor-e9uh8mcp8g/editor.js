(function () {
  'use strict';

  var L = window.L;
  var Logic = window.EditLogic;
  var $ = function (id) { return document.getElementById(id); };

  var IMAGERY = {
    esri: {
      url: 'https://server.arcgisonline.com/ArcGIS/rest/services/World_Imagery/MapServer/tile/{z}/{y}/{x}',
      maxZoom: 18,
      maxNativeZoom: 17,
      label: 'esri-world-imagery',
      credit: 'Tiles © Esri — Source: Esri, Maxar, Earthstar Geographics, and the GIS User Community. <a href="https://www.esri.com/en-us/legal/terms/data-attributions" rel="noopener noreferrer">Esri data attributions</a>'
    },
    sentinel: {
      url: 'https://tiles.maps.eox.at/wmts/1.0.0/s2cloudless-2020_3857/default/GoogleMapsCompatible/{z}/{y}/{x}.jpg',
      maxZoom: 18,
      maxNativeZoom: 16,
      label: 'sentinel-2-cloudless',
      credit: 'Sentinel-2 cloudless by <a href="https://s2maps.eu" rel="noopener noreferrer">EOX</a> (CC BY 4.0). Contains modified Copernicus Sentinel data 2020.'
    }
  };

  var LAYER_HE = {
    desert: 'מדבר',
    nondesert: 'צפון ומרכז',
    desert_extension: 'הארכה, מדבר',
    nondesert_extension: 'הארכה, צפון',
    basin: 'אגן'
  };

  var state = {
    map: null,
    base: null,
    imagery: 'esri',
    filters: {desert: true, north: true, ext: true, basins: true},
    basins: [],
    view: [],
    viewSeq: 0,
    originals: {},
    saved: [],
    undo: [],
    live: null,
    merge: null,
    stream: null,
    focus: null,
    basin: null,
    basinLayer: null,
    streamLayer: null,
    editLayer: null
  };

  function clone(value) { return JSON.parse(JSON.stringify(value)); }

  function keyOf(layer, id) { return layer + ':' + id; }

  function streamTitle(item) {
    var raw = ((item && (item.name_he || item.name)) || '').trim();
    if (!raw) return 'קטע ' + (item ? item.id : '');
    if (raw.indexOf('נחל ') === 0 || raw.indexOf('ואדי ') === 0) return raw;
    return 'נחל ' + raw;
  }

  function basinTitle(item) {
    return item && item.name ? item.name : ('אגן ' + (item ? item.id : ''));
  }

  function setStatus(text) { $('status').textContent = text; }

  function api(path) {
    return fetch(path, {cache: 'no-store'}).then(function (res) {
      if (!res.ok) throw new Error('בקשה נכשלה (' + res.status + ')');
      return res.json();
    });
  }

  function filtersFromForm() {
    state.filters.desert = $('chk-desert').checked;
    state.filters.north = $('chk-north').checked;
    state.filters.ext = $('chk-ext').checked;
    state.filters.basins = $('chk-basins').checked;
  }

  function styleStream(feature) {
    var ext = feature.properties.extension;
    var north = feature.properties.layer === 'nondesert';
    return {
      color: ext ? '#00838f' : (north ? '#1a365d' : '#1565c0'),
      weight: ext ? 3 : 2.5,
      opacity: 0.9,
      dashArray: north && !feature.properties.perennial ? '6 4' : null
    };
  }

  function remember(full) {
    var key = keyOf(full.layer, full.id);
    if (!state.originals[key]) {
      state.originals[key] = {
        geometry: clone(full.geometry),
        basin: full.basin == null ? null : String(full.basin),
        name: full.name || full.name_he || ''
      };
    }
  }

  function savedForStream(layer, id) {
    var found = null;
    state.saved.forEach(function (change) {
      if (change.op === 'update_stream' && change.layer === layer && change.id === id) found = change;
      if (change.op === 'merge_streams' && change.layer === layer && change.survivor_id === id) found = change;
    });
    return found;
  }

  function isHidden(layer, id) {
    return state.saved.some(function (change) {
      return change.op === 'merge_streams' && change.layer === layer && change.absorbed_id === id;
    });
  }

  function currentStreamCoords(layer, id, fallback) {
    if (state.live && state.live.kind === 'stream' && state.live.layer === layer && state.live.id === id) {
      return state.live.coordinates;
    }
    var saved = savedForStream(layer, id);
    if (saved) return saved.new_geometry.coordinates;
    return fallback;
  }

  function currentBasinRings(id, fallback) {
    if (state.live && state.live.kind === 'basin' && state.live.id === id) {
      return state.live.rings;
    }
    var saved = null;
    state.saved.forEach(function (change) {
      if (change.op === 'update_basin' && change.id === id) saved = change;
    });
    if (saved) return saved.new_geometry.coordinates;
    return fallback;
  }

  function latLngs(coords) {
    return coords.map(function (c) { return [c[1], c[0]]; });
  }

  function pushUndo() {
    state.undo.push(clone(state.saved));
    if (state.undo.length > 30) state.undo.shift();
  }

  function persist() {
    try {
      sessionStorage.setItem('flood-stream-editor-v1', JSON.stringify({
        saved: state.saved,
        originals: state.originals,
        fileNote: $('file-note').value
      }));
    } catch (err) { /* private mode can refuse storage */ }
  }

  function restore() {
    try {
      var raw = sessionStorage.getItem('flood-stream-editor-v1');
      if (!raw) return;
      var data = JSON.parse(raw);
      if (Array.isArray(data.saved)) state.saved = data.saved;
      if (data.originals && typeof data.originals === 'object') state.originals = data.originals;
      if (typeof data.fileNote === 'string') $('file-note').value = data.fileNote;
    } catch (err) { /* ignore a broken draft */ }
  }

  function buildDocument() {
    var imagery = IMAGERY[state.imagery];
    return {
      format: 'flood-alerts-geometry-patch',
      version: 1,
      created_at: new Date().toISOString(),
      imagery: imagery.label,
      imagery_attribution: imagery.credit.replace(/<[^>]+>/g, ''),
      note: $('file-note').value.trim(),
      does_not_change: ['model_weights', 'calibration', 'thresholds', 'rain_cells', 'travel_time', 'segment_ids'],
      changes: state.saved
    };
  }

  function renderList() {
    var list = $('change-list');
    list.textContent = '';
    state.saved.forEach(function (change, index) {
      var li = document.createElement('li');
      var label = document.createElement('span');
      label.textContent = changeLabel(change);
      var btn = document.createElement('button');
      btn.type = 'button';
      btn.textContent = 'הסר';
      btn.addEventListener('click', function () { removeChange(index); });
      li.appendChild(label);
      li.appendChild(btn);
      list.appendChild(li);
    });
    $('change-count').textContent = String(state.saved.length);
    $('btn-export').disabled = state.saved.length === 0;
    $('btn-undo').disabled = state.undo.length === 0;
    var doc = state.saved.length ? buildDocument() : {changes: []};
    $('preview').textContent = JSON.stringify(doc, null, 2);
    persist();
  }

  function changeLabel(change) {
    if (change.op === 'merge_streams') {
      return 'מיזוג ' + change.survivor_id + ' + ' + change.absorbed_id + ' (' + (LAYER_HE[change.layer] || '') + ')';
    }
    if (change.op === 'update_basin') return 'אגן ' + change.id;
    var basin = change.old_basin !== change.new_basin ? ' · שיוך ' + change.new_basin : '';
    return streamTitle(change) + ' · ' + (LAYER_HE[change.layer] || '') + basin;
  }

  function removeChange(index) {
    pushUndo();
    state.saved.splice(index, 1);
    renderList();
    redraw();
  }

  function noteFor(action) {
    if (state.stream && state.live && state.live.kind === 'stream') {
      return action + ' ' + streamTitle(state.stream) + ' (' + (LAYER_HE[state.stream.layer] || '') + ', מזהה ' + state.stream.id + ')';
    }
    if (state.basin && state.live && state.live.kind === 'basin') {
      return action + ' גבול ' + basinTitle(state.basin) + ' (מזהה ' + state.basin.id + ')';
    }
    return action;
  }

  function setNote(text) {
    if (!$('note').value.trim()) $('note').value = text;
  }

  function selectionDirty() {
    return !!(state.live && state.live.dirty);
  }

  function guardSwitch() {
    if (!selectionDirty()) return false;
    setStatus('שמרו או בטלו את העריכה הפתוחה לפני מעבר.');
    return true;
  }

  function clearEditGraphics() {
    state.editLayer.clearLayers();
  }

  function vertexIcon(on) {
    return L.divIcon({
      className: 'vx' + (on ? ' on' : ''),
      iconSize: [44, 44],
      iconAnchor: [22, 22],
      html: '<span></span>'
    });
  }

  function drawVertices(coords, onDrag, onPick) {
    coords.forEach(function (coord, index) {
      var marker = L.marker([coord[1], coord[0]], {
        icon: vertexIcon(state.live && state.live.vertex === index),
        draggable: true,
        autoPan: true,
        keyboard: false
      });
      marker.on('drag', function (ev) {
        var ll = ev.target.getLatLng();
        onDrag(index, [ll.lng, ll.lat]);
      });
      marker.on('dragend', function (ev) {
        var ll = ev.target.getLatLng();
        onDrag(index, Logic.roundCoord([ll.lng, ll.lat]), true);
      });
      marker.on('click', function (ev) {
        L.DomEvent.stop(ev);
        onPick(index);
      });
      state.editLayer.addLayer(marker);
    });
  }

  function showStreamEditor() {
    clearEditGraphics();
    if (!state.stream) return;
    var coords = currentStreamCoords(state.stream.layer, state.stream.id, state.stream.geometry.coordinates);
    var line = L.polyline(latLngs(coords), {color: '#e65100', weight: 5, opacity: 0.95, interactive: false});
    var hit = L.polyline(latLngs(coords), {color: '#e65100', weight: 18, opacity: 0.01, interactive: true});
    state.editLayer.addLayer(line);
    state.editLayer.addLayer(hit);
    hit.on('click', function (ev) {
      if (!state.live || state.live.kind !== 'stream') beginStreamLive();
      var point = [ev.latlng.lng, ev.latlng.lat];
      var nearest = Logic.closestSegment(state.live.coordinates, point);
      if (!nearest) return;
      var px = state.map.latLngToContainerPoint(ev.latlng);
      var proj = state.map.latLngToContainerPoint(L.latLng(nearest.proj[1], nearest.proj[0]));
      if (px.distanceTo(proj) > 28) return;
      state.live.coordinates = Logic.insertOnSegment(state.live.coordinates, point);
      touchLive('insert_vertex');
      showStreamEditor();
    });
    drawVertices(coords, function (index, coord, end) {
      if (!state.live || state.live.kind !== 'stream') beginStreamLive();
      state.live.coordinates[index] = coord;
      line.setLatLngs(latLngs(state.live.coordinates));
      hit.setLatLngs(latLngs(state.live.coordinates));
      if (end) touchLive('move');
    }, function (index) {
      if (!state.live || state.live.kind !== 'stream') beginStreamLive();
      state.live.vertex = index;
      showStreamEditor();
    });
    var km = Logic.lengthM(coords) / 1000;
    $('sel-meta').textContent = coords.length + ' קודקודים · ' + km.toFixed(2) + ' ק״מ · ' + (LAYER_HE[state.stream.layer] || '');
  }

  function showBasinEditor() {
    clearEditGraphics();
    if (!state.basin) return;
    var rings = currentBasinRings(state.basin.id, state.basin.geometry.coordinates);
    var outer = Logic.openRing(rings[0]);
    var polygon = L.polygon(rings.map(function (ring) { return latLngs(Logic.openRing(ring)); }), {
      color: '#e65100', weight: 3, fillColor: '#e65100', fillOpacity: 0.12, interactive: true
    });
    state.editLayer.addLayer(polygon);
    polygon.on('click', function (ev) {
      if (!state.live || state.live.kind !== 'basin') beginBasinLive();
      var point = [ev.latlng.lng, ev.latlng.lat];
      var outerNow = Logic.openRing(state.live.rings[0]);
      var nearest = Logic.closestSegment(outerNow.concat([outerNow[0]]), point);
      if (!nearest) return;
      var px = state.map.latLngToContainerPoint(ev.latlng);
      var proj = state.map.latLngToContainerPoint(L.latLng(nearest.proj[1], nearest.proj[0]));
      if (px.distanceTo(proj) > 28) return;
      var next = outerNow.slice();
      next.splice(nearest.index + 1, 0, Logic.roundCoord(nearest.proj));
      state.live.rings[0] = Logic.closeRing(next);
      touchLive('insert_vertex');
      showBasinEditor();
    });
    var bounds = state.map.getBounds().pad(0.15);
    var shown = [];
    var lastPt = null;
    outer.forEach(function (coord, index) {
      var ll = L.latLng(coord[1], coord[0]);
      if (!bounds.contains(ll)) return;
      var pt = state.map.latLngToContainerPoint(ll);
      if (lastPt && pt.distanceTo(lastPt) < 48) return;
      shown.push({coord: coord, index: index});
      lastPt = pt;
    });
    if (shown.length < 4) {
      shown = [];
      var step = Math.max(1, Math.ceil(outer.length / 12));
      outer.forEach(function (coord, index) {
        if (index % step === 0) shown.push({coord: coord, index: index});
      });
    }
    drawVertices(shown.map(function (item) { return item.coord; }), function (pos, coord, end) {
      if (!state.live || state.live.kind !== 'basin') beginBasinLive();
      var open = Logic.openRing(state.live.rings[0]);
      var real = shown[pos].index;
      if (real < 0 || real >= open.length) return;
      open[real] = coord;
      state.live.rings[0] = Logic.closeRing(open);
      polygon.setLatLngs(state.live.rings.map(function (ring) { return latLngs(Logic.openRing(ring)); }));
      if (end) {
        state.live.vertex = real;
        touchLive('move');
      }
    }, function (pos) {
      if (!state.live || state.live.kind !== 'basin') beginBasinLive();
      state.live.vertex = shown[pos].index;
      showBasinEditor();
    });
    $('sel-meta').textContent = 'גבול חיצוני: ' + outer.length + ' קודקודים · מוצגים ' + shown.length + (rings.length > 1 ? ' · חורים נשמרים' : '');
  }

  function beginStreamLive() {
    var coords = currentStreamCoords(state.stream.layer, state.stream.id, state.stream.geometry.coordinates);
    var basin = state.stream.basin == null ? null : String(state.stream.basin);
    var saved = savedForStream(state.stream.layer, state.stream.id);
    if (saved && saved.new_basin != null) basin = String(saved.new_basin);
    state.live = {
      kind: 'stream',
      layer: state.stream.layer,
      id: state.stream.id,
      coordinates: coords.map(function (c) { return [c[0], c[1]]; }),
      basin: basin,
      actions: [],
      dirty: false,
      vertex: null
    };
  }

  function beginBasinLive() {
    var rings = currentBasinRings(state.basin.id, state.basin.geometry.coordinates);
    state.live = {
      kind: 'basin',
      id: state.basin.id,
      rings: clone(rings),
      actions: [],
      dirty: false,
      vertex: null,
      vertexCoord: null
    };
  }

  function touchLive(action) {
    state.live.dirty = true;
    if (state.live.actions.indexOf(action) < 0) state.live.actions.push(action);
    setNote(noteFor(action === 'move' ? 'הזזת נתיב' : action === 'insert_vertex' ? 'הוספת קודקוד' : 'עדכון'));
    refreshTools();
  }

  function refreshTools() {
    var stream = !!state.stream;
    var basin = !!state.basin;
    $('stream-tools').hidden = !stream;
    $('basin-tools').hidden = !basin;
    $('merge-box').hidden = !state.merge;
    if (state.focus === 'basin' && basin) $('sel-title').textContent = basinTitle(state.basin);
    else if (stream) $('sel-title').textContent = streamTitle(state.stream);
    else if (basin) $('sel-title').textContent = basinTitle(state.basin);
    else $('sel-title').textContent = 'לא נבחר נחל';
    if (state.focus !== 'basin' && stream && (!state.live || state.live.kind !== 'stream')) {
      var basinName = state.stream.basin_name || state.stream.basin || 'ללא אגן';
      $('sel-meta').textContent = (LAYER_HE[state.stream.layer] || '') + ' · מזהה ' + state.stream.id + ' · אגן ' + basinName;
    }
    $('btn-save').disabled = !selectionDirty();
  }

  function redraw() {
    drawBasins();
    drawStreams();
    if (state.focus === 'basin' && state.basin) showBasinEditor();
    else if (state.stream) showStreamEditor();
    else if (state.basin) showBasinEditor();
    else clearEditGraphics();
    if (state.merge && state.merge.preview) {
      state.editLayer.addLayer(L.polyline(latLngs(state.merge.preview), {
        color: '#2e7d32', weight: 4, dashArray: '8 6', interactive: false
      }));
    }
    refreshTools();
  }

  function drawBasins() {
    state.basinLayer.clearLayers();
    if (!state.filters.basins) return;
    var features = state.basins.filter(function (item) {
      return !(state.focus === 'basin' && state.basin && state.basin.id === item.id);
    }).map(function (item) {
      return {
        type: 'Feature',
        properties: {id: item.id, desert: item.desert},
        geometry: {type: 'Polygon', coordinates: currentBasinRings(item.id, item.coordinates)}
      };
    });
    state.basinLayer.addData({type: 'FeatureCollection', features: features});
  }

  function drawStreams() {
    state.streamLayer.clearLayers();
    var features = [];
    state.view.forEach(function (item) {
      if (isHidden(item.layer, item.id)) return;
      if (state.focus !== 'basin' && state.stream && state.stream.layer === item.layer && state.stream.id === item.id) return;
      features.push({
        type: 'Feature',
        properties: {layer: item.layer, id: item.id, extension: item.extension, perennial: item.perennial},
        geometry: {type: 'LineString', coordinates: currentStreamCoords(item.layer, item.id, item.coordinates)}
      });
    });
    state.streamLayer.addData({type: 'FeatureCollection', features: features});
  }

  function loadView() {
    var seq = ++state.viewSeq;
    var bounds = state.map.getBounds();
    var params = new URLSearchParams({
      west: String(bounds.getWest()),
      south: String(bounds.getSouth()),
      east: String(bounds.getEast()),
      north: String(bounds.getNorth()),
      zoom: String(state.map.getZoom()),
      desert: state.filters.desert ? '1' : '0',
      north_on: state.filters.north ? '1' : '0',
      ext: state.filters.ext ? '1' : '0'
    });
    return api('/api/view?' + params.toString()).then(function (data) {
      if (seq !== state.viewSeq) return;
      state.view = data.streams || [];
      $('count').textContent = data.truncated
        ? 'מוצגים ' + state.view.length + ' נחלים גדולים. התקרבו כדי לראות עוד.'
        : 'נחלים במסך: ' + state.view.length;
      drawStreams();
    }).catch(function () {
      setStatus('לא הצלחתי לטעון נחלים. רעננו את העמוד.');
    });
  }

  function selectStream(layer, id) {
    if (guardSwitch()) return Promise.resolve();
    if (state.merge && (state.merge.survivor.layer !== layer)) {
      setStatus('אפשר למזג רק שני קטעים מאותה שכבה. המזהים נשארים יציבים.');
      return Promise.resolve();
    }
    return api('/api/feature?layer=' + encodeURIComponent(layer) + '&id=' + id).then(function (full) {
      if (isHidden(full.layer, full.id)) {
        setStatus('הקטע הזה כבר סומן למיזוג ולא מוצג.');
        return;
      }
      remember(full);
      if (state.merge) {
        armMerge(full);
        return;
      }
      state.stream = full;
      state.focus = 'stream';
      state.live = null;
      $('note').value = '';
      redraw();
      setStatus('גררו קודקוד, או לחצו על הקו כדי להוסיף קודקוד.');
    }).catch(function () { setStatus('לא מצאתי את הנחל.'); });
  }

  function selectBasin(id) {
    if (guardSwitch()) return Promise.resolve();
    return api('/api/feature?layer=basin&id=' + id).then(function (full) {
      remember(full);
      state.basin = full;
      state.focus = 'basin';
      state.live = null;
      $('note').value = '';
      redraw();
      setStatus('גררו קודקוד של גבול האגן. חורים פנימיים נשמרים.');
    }).catch(function () { setStatus('לא מצאתי את האגן.'); });
  }

  function ensureStreamLive() {
    if (!state.stream) return false;
    if (!state.live || state.live.kind !== 'stream') beginStreamLive();
    return true;
  }

  function mutateStream(action, producer) {
    if (!ensureStreamLive()) return;
    var next = producer(state.live.coordinates.map(function (c) { return [c[0], c[1]]; }));
    if (!next || Logic.dropDuplicates(next).length < 2) {
      setStatus('נחל חייב להישאר עם שני קודקודים לפחות.');
      return;
    }
    state.live.coordinates = next;
    state.live.vertex = action === 'extend_end' ? next.length - 1 : 0;
    touchLive(action);
    showStreamEditor();
  }

  function armMerge(absorbed) {
    var survivor = state.merge.survivor;
    if (absorbed.layer !== survivor.layer || absorbed.id === survivor.id) {
      setStatus('בחרו נחל אחר מאותה שכבה.');
      return;
    }
    var a = currentStreamCoords(survivor.layer, survivor.id, survivor.geometry.coordinates);
    var b = currentStreamCoords(absorbed.layer, absorbed.id, absorbed.geometry.coordinates);
    var merged = Logic.mergeLines(a, b);
    if (!merged) {
      setStatus('לא הצלחתי לחבר את שני הקווים.');
      return;
    }
    if (merged.gapM > 20000) {
      setStatus('הנחלים רחוקים מדי למיזוג (יותר מ-20 ק״מ).');
      return;
    }
    state.merge.absorbed = absorbed;
    state.merge.preview = merged.coordinates;
    state.merge.gapM = merged.gapM;
    $('merge-text').textContent = 'נשאר מזהה ' + survivor.id + '. נבלע מזהה ' + absorbed.id +
      '. מרחק בין הקצוות: ' + Math.round(merged.gapM) + ' מ׳. המזהים לא משתנים.';
    $('merge-box').hidden = false;
    redraw();
    setStatus(merged.gapM > 500 ? 'הקצוות רחוקים. אפשר לאשר ואז לגרור את החיבור.' : 'בדקו את החיבור הירוק ואשרו.');
  }

  function confirmMerge() {
    if (!state.merge || !state.merge.absorbed) {
      setStatus('בחרו קודם את הנחל שייבלע.');
      return;
    }
    var survivor = state.merge.survivor;
    var absorbed = state.merge.absorbed;
    var origS = state.originals[keyOf(survivor.layer, survivor.id)];
    var origA = state.originals[keyOf(absorbed.layer, absorbed.id)];
    pushUndo();
    state.saved = state.saved.filter(function (change) {
      if (change.layer !== survivor.layer) return true;
      if (change.op === 'update_stream' && (change.id === survivor.id || change.id === absorbed.id)) return false;
      if (change.op === 'merge_streams' && (change.survivor_id === survivor.id || change.absorbed_id === absorbed.id || change.survivor_id === absorbed.id)) return false;
      return true;
    });
    var basin = state.live && state.live.kind === 'stream' && state.live.id === survivor.id ? state.live.basin : (survivor.basin == null ? null : String(survivor.basin));
    state.saved.push({
      op: 'merge_streams',
      layer: survivor.layer,
      survivor_id: survivor.id,
      absorbed_id: absorbed.id,
      survivor_name: survivor.name || '',
      absorbed_name: absorbed.name || '',
      note: $('note').value.trim() || noteFor('מיזוג'),
      survivor_old_geometry: clone(origS.geometry),
      absorbed_old_geometry: clone(origA.geometry),
      new_geometry: {type: 'LineString', coordinates: Logic.dropDuplicates(state.merge.preview)},
      old_basin: origS.basin,
      new_basin: basin
    });
    state.merge = null;
    state.live = null;
    $('note').value = '';
    state.stream = survivor;
    renderList();
    redraw();
    setStatus('המיזוג נכנס לרשימה. המזהה שנשאר הוא ' + survivor.id + '.');
  }

  function saveLive() {
    if (!state.live || !state.live.dirty) {
      setStatus('אין עריכה פתוחה לשמירה.');
      return;
    }
    var note = $('note').value.trim() || noteFor('עדכון');
    if (state.live.kind === 'stream') {
      var orig = state.originals[keyOf(state.live.layer, state.live.id)];
      var coords = Logic.dropDuplicates(state.live.coordinates);
      var same = Logic.sameLine(coords, orig.geometry.coordinates);
      var basin = state.live.basin == null ? orig.basin : String(state.live.basin);
      if (same && basin === orig.basin) {
        setStatus('אין שינוי לעומת הנתונים המקוריים.');
        return;
      }
      var merge = state.saved.find(function (change) {
        return change.op === 'merge_streams' && change.layer === state.live.layer && change.survivor_id === state.live.id;
      });
      pushUndo();
      if (merge) {
        merge.new_geometry = {type: 'LineString', coordinates: coords};
        merge.new_basin = basin;
        merge.note = note;
      } else {
        state.saved = state.saved.filter(function (change) {
          return !(change.op === 'update_stream' && change.layer === state.live.layer && change.id === state.live.id);
        });
        state.saved.push({
          op: 'update_stream',
          layer: state.live.layer,
          id: state.live.id,
          name: state.stream.name || '',
          note: note,
          actions: state.live.actions.slice(),
          old_geometry: clone(orig.geometry),
          new_geometry: {type: 'LineString', coordinates: coords},
          old_basin: orig.basin,
          new_basin: basin
        });
      }
    } else {
      var origBasin = state.originals[keyOf('basin', state.live.id)];
      var rings = state.live.rings.slice();
      rings[0] = Logic.closeRing(Logic.openRing(rings[0]));
      if (JSON.stringify(rings) === JSON.stringify(origBasin.geometry.coordinates)) {
        setStatus('גבול האגן לא השתנה.');
        return;
      }
      pushUndo();
      state.saved = state.saved.filter(function (change) {
        return !(change.op === 'update_basin' && change.id === state.live.id);
      });
      state.saved.push({
        op: 'update_basin',
        layer: 'basin',
        id: state.live.id,
        name: state.basin.name || '',
        note: note,
        old_geometry: clone(origBasin.geometry),
        new_geometry: {type: 'Polygon', coordinates: rings}
      });
    }
    state.live.dirty = false;
    $('note').value = '';
    renderList();
    redraw();
    setStatus('השינוי נשמר ברשימה. אפשר להוריד קובץ כשתסיימו.');
  }

  function discardLive() {
    state.live = null;
    $('note').value = '';
    redraw();
    setStatus('העריכה הפתוחה בוטלה. הרשימה השמורה נשארה.');
  }

  function exportFile() {
    if (selectionDirty()) {
      setStatus('שמרו את העריכה הפתוחה לרשימה לפני ההורדה.');
      return;
    }
    if (!state.saved.length) {
      setStatus('הרשימה ריקה.');
      return;
    }
    var doc = buildDocument();
    var blob = new Blob([JSON.stringify(doc, null, 2)], {type: 'application/json'});
    var link = document.createElement('a');
    var now = new Date();
    var pad = function (n) { return String(n).padStart(2, '0'); };
    var stamp = now.getFullYear() + pad(now.getMonth() + 1) + pad(now.getDate()) + '-' + pad(now.getHours()) + pad(now.getMinutes());
    link.href = URL.createObjectURL(blob);
    link.download = 'geometry-review-' + stamp + '.json';
    document.body.appendChild(link);
    link.click();
    link.remove();
    setStatus('הקובץ ירד למכשיר. הנתונים במאגר לא שונו.');
  }

  function fitCoords(coords) {
    if (!coords || coords.length < 1) return;
    var bounds = L.latLngBounds(latLngs(coords.length > 1 ? coords : coords.concat(coords)));
    state.map.fitBounds(bounds.pad(0.4), {maxZoom: 16});
  }

  function setBasemap(kind) {
    state.imagery = IMAGERY[kind] ? kind : 'esri';
    if (state.base) state.map.removeLayer(state.base);
    var spec = IMAGERY[state.imagery];
    state.base = L.tileLayer(spec.url, {maxZoom: spec.maxZoom, maxNativeZoom: spec.maxNativeZoom, attribution: ''});
    state.base.on('tileerror', function () {
      setStatus('לא הצלחתי לטעון תצלום לוויין. בדקו חיבור לאינטרנט.');
    });
    state.base.addTo(state.map);
    state.base.bringToBack();
    $('credit-en').innerHTML = spec.credit;
  }

  function showResults(results) {
    var list = $('results');
    list.textContent = '';
    if (!results.length) {
      list.hidden = true;
      setStatus('אין תוצאות.');
      return;
    }
    results.forEach(function (item) {
      var li = document.createElement('li');
      var btn = document.createElement('button');
      btn.type = 'button';
      var title = item.layer === 'basin' ? basinTitle(item) : streamTitle(item);
      btn.textContent = title + ' · ' + (LAYER_HE[item.layer] || '') + ' · ' + item.id;
      btn.addEventListener('click', function () {
        list.hidden = true;
        var go = item.layer === 'basin' ? selectBasin(item.id) : selectStream(item.layer, item.id);
        go.then(function () {
          var target = item.layer === 'basin' ? state.basin : state.stream;
          if (!target) return;
          var coords = target.geometry.type === 'Polygon' ? Logic.openRing(target.geometry.coordinates[0]) : target.geometry.coordinates;
          fitCoords(coords);
        });
      });
      li.appendChild(btn);
      list.appendChild(li);
    });
    list.hidden = false;
  }

  function boot() {
    restore();
    var canvas = L.canvas({padding: 0.4});
    state.map = L.map('map', {
      zoomControl: true,
      attributionControl: false,
      preferCanvas: true,
      tap: true,
      maxZoom: 18
    }).setView([31.2, 35.2], 8);
    state.map.zoomControl.setPosition('topleft');
    L.control.scale({imperial: false, position: 'bottomleft'}).addTo(state.map);
    setBasemap('esri');
    state.basinLayer = L.geoJSON({type: 'FeatureCollection', features: []}, {
      renderer: canvas,
      style: function (feature) {
        var desert = feature.properties.desert === 1;
        return {color: desert ? '#6d4c41' : '#455a64', weight: 1.2, fillColor: desert ? '#c4a574' : '#90a4ae', fillOpacity: 0.16};
      },
      onEachFeature: function (feature, layer) {
        layer.on('click', function (ev) {
          L.DomEvent.stopPropagation(ev);
          selectBasin(feature.properties.id);
        });
      }
    }).addTo(state.map);
    state.streamLayer = L.geoJSON({type: 'FeatureCollection', features: []}, {
      renderer: canvas,
      style: styleStream,
      onEachFeature: function (feature, layer) {
        layer.on('click', function (ev) {
          L.DomEvent.stopPropagation(ev);
          selectStream(feature.properties.layer, feature.properties.id);
        });
      }
    }).addTo(state.map);
    state.editLayer = L.layerGroup().addTo(state.map);
    window.__editorMap = state.map;
    state.map.on('moveend', function () { loadView(); });
    window.addEventListener('resize', function () { state.map.invalidateSize(); });
    setTimeout(function () { state.map.invalidateSize(); }, 0);
    $('imagery').addEventListener('change', function () { setBasemap($('imagery').value); });
    ['chk-desert', 'chk-north', 'chk-ext', 'chk-basins'].forEach(function (id) {
      $(id).addEventListener('change', function () {
        filtersFromForm();
        redraw();
        loadView();
      });
    });
    $('search-form').addEventListener('submit', function (ev) {
      ev.preventDefault();
      var q = $('q').value.trim();
      if (!q) return;
      api('/api/search?q=' + encodeURIComponent(q)).then(function (data) {
        showResults(data.results || []);
      }).catch(function () { setStatus('החיפוש נכשל.'); });
    });
    $('btn-extend-end').addEventListener('click', function () {
      mutateStream('extend_end', function (coords) { return Logic.extend(coords, true); });
    });
    $('btn-extend-start').addEventListener('click', function () {
      mutateStream('extend_start', function (coords) { return Logic.extend(coords, false); });
    });
    $('btn-shorten-end').addEventListener('click', function () {
      mutateStream('shorten_end', function (coords) { return Logic.shorten(coords, true); });
    });
    $('btn-shorten-start').addEventListener('click', function () {
      mutateStream('shorten_start', function (coords) { return Logic.shorten(coords, false); });
    });
    $('btn-delete-vertex').addEventListener('click', function () {
      if (!ensureStreamLive() || state.live.vertex == null) {
        setStatus('בחרו קודקוד בלחיצה, ואז מחקו אותו.');
        return;
      }
      mutateStream(state.live.vertex === 0 ? 'shorten_start' : (state.live.vertex === state.live.coordinates.length - 1 ? 'shorten_end' : 'delete_vertex'), function (coords) {
        return Logic.removeIndex(coords, state.live.vertex);
      });
    });
    $('btn-merge').addEventListener('click', function () {
      if (!state.stream) return;
      if (guardSwitch()) return;
      state.merge = {survivor: state.stream, absorbed: null, preview: null};
      $('merge-text').textContent = 'בחרו על המפה את הנחל שייבלע לתוך מזהה ' + state.stream.id + '.';
      $('merge-box').hidden = false;
      setStatus('מצב מיזוג. הנחל שנשאר הוא ' + streamTitle(state.stream) + '.');
    });
    $('btn-merge-confirm').addEventListener('click', confirmMerge);
    $('btn-merge-cancel').addEventListener('click', function () {
      state.merge = null;
      redraw();
      setStatus('המיזוג בוטל.');
    });
    $('btn-reassign').addEventListener('click', function () {
      if (!state.stream || !state.basin) {
        setStatus('בחרו נחל וגם אגן, ואז שייכו.');
        return;
      }
      if (selectionDirty()) {
        setStatus('שמרו או בטלו את העריכה הפתוחה לפני שיוך.');
        return;
      }
      var orig = state.originals[keyOf(state.stream.layer, state.stream.id)];
      var next = String(state.basin.id);
      var saved = savedForStream(state.stream.layer, state.stream.id);
      var current = saved && saved.new_basin != null ? String(saved.new_basin) : (orig.basin == null ? null : String(orig.basin));
      if (current === next) {
        setStatus('הנחל כבר משויך לאגן הזה.');
        return;
      }
      pushUndo();
      var note = 'שיוך ' + streamTitle(state.stream) + ' לאגן ' + basinTitle(state.basin);
      if (saved && saved.op === 'merge_streams') {
        saved.new_basin = next;
        saved.note = note;
      } else if (saved && saved.op === 'update_stream') {
        saved.new_basin = next;
        saved.note = note;
        if (saved.actions.indexOf('reassign_basin') < 0) saved.actions.push('reassign_basin');
      } else {
        state.saved.push({
          op: 'update_stream',
          layer: state.stream.layer,
          id: state.stream.id,
          name: state.stream.name || '',
          note: note,
          actions: ['reassign_basin'],
          old_geometry: clone(orig.geometry),
          new_geometry: clone(orig.geometry),
          old_basin: orig.basin,
          new_basin: next
        });
      }
      renderList();
      setStatus('השיוך נכנס לרשימה. תאי הגשם והמודל לא משתנים.');
    });
    $('btn-delete-basin-vertex').addEventListener('click', function () {
      if (!state.basin) return;
      if (!state.live || state.live.kind !== 'basin') beginBasinLive();
      var open = Logic.openRing(state.live.rings[0]);
      var index = state.live.vertex;
      if (index == null || index < 0 || index >= open.length) {
        setStatus('בחרו קודקוד על הגבול, ואז מחקו אותו.');
        return;
      }
      if (open.length <= 3) {
        setStatus('גבול צריך לפחות שלושה קודקודים.');
        return;
      }
      open.splice(index, 1);
      state.live.rings[0] = Logic.closeRing(open);
      state.live.vertex = null;
      touchLive('delete_vertex');
      showBasinEditor();
    });
    $('btn-fit').addEventListener('click', function () {
      if (!state.stream) return;
      fitCoords(currentStreamCoords(state.stream.layer, state.stream.id, state.stream.geometry.coordinates));
    });
    $('btn-fit-basin').addEventListener('click', function () {
      if (!state.basin) return;
      fitCoords(Logic.openRing(currentBasinRings(state.basin.id, state.basin.geometry.coordinates)[0]));
    });
    $('btn-save').addEventListener('click', saveLive);
    $('btn-discard').addEventListener('click', discardLive);
    $('btn-export').addEventListener('click', exportFile);
    $('btn-undo').addEventListener('click', function () {
      var prev = state.undo.pop();
      if (!prev) return;
      state.saved = prev;
      state.live = null;
      renderList();
      redraw();
      setStatus('השינוי האחרון ברשימה בוטל.');
    });
    $('btn-clear').addEventListener('click', function () {
      if (!state.saved.length) return;
      pushUndo();
      state.saved = [];
      renderList();
      redraw();
      setStatus('הרשימה נוקתה במכשיר הזה. המאגר לא השתנה.');
    });
    $('file-note').addEventListener('input', persist);
    $('sheet-toggle').addEventListener('click', function () {
      document.body.classList.toggle('sheet-min');
      var open = !document.body.classList.contains('sheet-min');
      $('sheet-toggle').setAttribute('aria-expanded', open ? 'true' : 'false');
      $('sheet-toggle').textContent = open ? 'מפה' : 'כלים';
      setTimeout(function () { state.map.invalidateSize(); }, 50);
    });
    if (window.matchMedia('(max-width: 800px)').matches) {
      document.body.classList.add('sheet-min');
      $('sheet-toggle').setAttribute('aria-expanded', 'false');
      $('sheet-toggle').textContent = 'כלים';
    }
    api('/api/basins').then(function (data) {
      state.basins = data.basins || [];
      drawBasins();
      return loadView();
    }).then(function () {
      renderList();
      setStatus('בחרו נחל או אגן. השינויים נשארים ברשימה עד להורדת הקובץ.');
    }).catch(function () {
      setStatus('לא הצלחתי לטעון את נתוני המאגר.');
    });
  }

  boot();
})();
