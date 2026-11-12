/* Client-side stand-in for the private editor's /api/* routes.
   Reads the GeoJSON already published under site/data. No network writes. */
(function (root, factory) {
  var api = factory();
  if (typeof module === 'object' && module.exports) module.exports = api;
  else {
    root.StaticCatalog = api;
    api.install();
  }
})(typeof self !== 'undefined' ? self : this, function () {
  'use strict';

  var STREAM_FILES = [
    ['desert', 'channel_segments.geojson', false],
    ['nondesert', 'channel_segments_nondesert.geojson', false],
    ['desert_extension', 'channel_extensions_desert.geojson', true],
    ['nondesert_extension', 'channel_extensions_nondesert.geojson', true]
  ];
  var BASIN_FILE = 'basins.geojson';
  var LAYERS = {
    desert: true,
    nondesert: true,
    desert_extension: true,
    nondesert_extension: true,
    basin: true
  };

  function asString(value) {
    return typeof value === 'string' ? value : '';
  }

  function asNumber(value) {
    var number = Number(value || 0);
    return Number.isFinite(number) ? number : 0;
  }

  function asInt(value) {
    return Math.trunc(asNumber(value));
  }

  function asId(value) {
    if (typeof value === 'number' && Number.isInteger(value)) return value;
    if (typeof value === 'string' && /^-?\d+$/.test(value)) return parseInt(value, 10);
    return null;
  }

  function maybeInt(value) {
    var ident = asId(value);
    return ident == null ? -1 : ident;
  }

  function bbox(points) {
    var minX = Infinity;
    var minY = Infinity;
    var maxX = -Infinity;
    var maxY = -Infinity;
    for (var i = 0; i < points.length; i++) {
      var x = points[i][0];
      var y = points[i][1];
      if (x < minX) minX = x;
      if (y < minY) minY = y;
      if (x > maxX) maxX = x;
      if (y > maxY) maxY = y;
    }
    return [minX, minY, maxX, maxY];
  }

  function hits(box, west, south, east, north) {
    return !(box[2] < west || box[0] > east || box[3] < south || box[1] > north);
  }

  function samePoint(a, b) {
    return a[0] === b[0] && a[1] === b[1];
  }

  function simplify(coords, step) {
    if (step <= 1 || coords.length <= 2) return coords;
    var out = [];
    for (var i = 0; i < coords.length; i += step) out.push(coords[i]);
    var last = coords[coords.length - 1];
    if (!samePoint(out[out.length - 1], last)) out.push(last);
    return out;
  }

  function copyPoint(point) {
    var out = new Array(point.length);
    for (var i = 0; i < point.length; i++) out[i] = point[i];
    return out;
  }

  function copyLine(coords) {
    var out = new Array(coords.length);
    for (var i = 0; i < coords.length; i++) out[i] = copyPoint(coords[i]);
    return out;
  }

  function copyRings(rings) {
    var out = new Array(rings.length);
    for (var i = 0; i < rings.length; i++) out[i] = copyLine(rings[i]);
    return out;
  }

  function norm(text) {
    var value = String(text || '').replace(/־/g, ' ').replace(/-/g, ' ');
    value = value.split(/\s+/).filter(Boolean).join(' ');
    var prefixes = ['נחל ', 'ואדי ', 'נהר '];
    for (var i = 0; i < prefixes.length; i++) {
      if (value.indexOf(prefixes[i]) === 0) value = value.slice(prefixes[i].length);
    }
    return value.toLowerCase();
  }

  function titleParts(props) {
    var keys = ['name_he', 'name', 'main_nahal', 'flows_into', 'name_en'];
    var bits = [];
    for (var i = 0; i < keys.length; i++) {
      var bit = props[keys[i]];
      if (typeof bit === 'string') bits.push(bit);
    }
    return bits.join(' ');
  }

  function minArea(zoom) {
    if (zoom <= 8) return 200;
    if (zoom <= 9) return 80;
    if (zoom <= 10) return 30;
    if (zoom <= 11) return 8;
    if (zoom <= 12) return 2;
    return 0;
  }

  function finite(value) {
    return typeof value === 'number' && Number.isFinite(value);
  }

  function createCatalog(parts) {
    var streams = [];
    var basins = [];
    var byKey = new Map();
    (parts.streams || []).forEach(function (entry) {
      var collection = entry.collection || {};
      var features = collection.features;
      if (!Array.isArray(features)) throw new Error('not a FeatureCollection: ' + entry.layer);
      features.forEach(function (feature) {
        var geom = feature.geometry || {};
        var coords = geom.coordinates;
        var props = feature.properties || {};
        if (geom.type !== 'LineString' || !Array.isArray(coords) || coords.length < 2) return;
        var ident = asId(props.id);
        if (ident == null) return;
        var item = {
          layer: entry.layer,
          id: ident,
          name: asString(props.name),
          name_he: asString(props.name_he),
          main_nahal: asString(props.main_nahal),
          flows_into: asString(props.flows_into),
          basin: props.b == null ? null : String(props.b),
          area: asNumber(props.a),
          perennial: !!(props.perennial || props.p),
          extension: !!entry.extension || asInt(props.ext) === 1,
          bbox: bbox(coords),
          coordinates: coords,
          hay: norm(titleParts(props))
        };
        streams.push(item);
        byKey.set(entry.layer + ':' + ident, item);
      });
    });
    var basinCollection = parts.basins || {};
    if (!Array.isArray(basinCollection.features)) throw new Error('not a FeatureCollection: basin');
    basinCollection.features.forEach(function (feature) {
      var geom = feature.geometry || {};
      var rings = geom.coordinates;
      var props = feature.properties || {};
      if (geom.type !== 'Polygon' || !Array.isArray(rings) || !rings.length) return;
      var ident = asId(props.sid);
      if (ident == null) return;
      var item = {
        layer: 'basin',
        id: ident,
        name: asString(props.name_he),
        name_en: asString(props.name_en),
        main_nahal: asString(props.main_nahal),
        desert: asInt(props.desert),
        perennial: !!props.perennial,
        area: asNumber(props.area_dem || props.area_rep),
        bbox: bbox(rings[0]),
        coordinates: rings,
        hay: norm(titleParts(props))
      };
      basins.push(item);
      byKey.set('basin:' + ident, item);
    });
    streams.forEach(function (stream) {
      var basin = byKey.get('basin:' + maybeInt(stream.basin));
      if (basin) {
        stream.basin_name = basin.name;
        stream.hay = (stream.hay + ' ' + basin.hay).trim();
      }
    });

    function search(query, limit, kind) {
      var needle = norm(query);
      var cap = limit == null ? 12 : limit;
      if (needle.length < 1) return [];
      var scored = [];
      streams.concat(basins).forEach(function (item) {
        if (kind === 'basin' && item.layer !== 'basin') return;
        if (kind === 'stream' && item.layer === 'basin') return;
        var name = norm(item.name || '');
        var score;
        if (needle === String(item.id)) score = 0;
        else if (name.indexOf(needle) !== -1) score = 1;
        else if (item.hay.indexOf(needle) !== -1) score = 3;
        else return;
        scored.push({score: score, item: item});
      });
      scored.sort(function (a, b) {
        if (a.score !== b.score) return a.score - b.score;
        if (a.item.area !== b.item.area) return b.item.area - a.item.area;
        return a.item.id - b.item.id;
      });
      return scored.slice(0, cap).map(function (pair) {
        var item = pair.item;
        var box = item.bbox;
        return {
          layer: item.layer,
          id: item.id,
          name: item.name || '',
          name_he: item.name_he || item.name || '',
          main_nahal: item.main_nahal || '',
          basin: Object.prototype.hasOwnProperty.call(item, 'basin') ? item.basin : null,
          basin_name: item.basin_name || '',
          area: item.area || 0,
          center: [(box[0] + box[2]) / 2, (box[1] + box[3]) / 2]
        };
      });
    }

    function view(west, south, east, north, zoom, desertOn, northOn, extensions) {
      var minimum = minArea(zoom);
      var step = zoom >= 13 ? 1 : zoom >= 12 ? 2 : zoom >= 11 ? 3 : 5;
      var found = [];
      for (var i = 0; i < streams.length; i++) {
        var item = streams[i];
        var layer = item.layer;
        if (item.extension || layer.endsWith('_extension')) {
          if (!extensions) continue;
        } else if (layer === 'desert' && !desertOn) continue;
        else if (layer === 'nondesert' && !northOn) continue;
        if (item.area < minimum && zoom < 13) continue;
        if (!hits(item.bbox, west, south, east, north)) continue;
        found.push(item);
      }
      var truncated = false;
      if (found.length > 900) {
        found.sort(function (a, b) { return b.area - a.area; });
        found = found.slice(0, 900);
        truncated = true;
      }
      return {
        streams: found.map(function (item) {
          return {
            layer: item.layer,
            id: item.id,
            name: item.name,
            basin: item.basin,
            area: item.area,
            perennial: item.perennial,
            extension: item.extension,
            coordinates: copyLine(simplify(item.coordinates, step))
          };
        }),
        truncated: truncated,
        min_area: minimum
      };
    }

    function feature(layer, ident) {
      var item = byKey.get(layer + ':' + ident);
      if (!item) return null;
      if (layer === 'basin') {
        return {
          layer: 'basin',
          id: item.id,
          name: item.name,
          name_en: item.name_en,
          main_nahal: item.main_nahal,
          desert: item.desert,
          perennial: item.perennial,
          area: item.area,
          geometry: {type: 'Polygon', coordinates: copyRings(item.coordinates)}
        };
      }
      return {
        layer: item.layer,
        id: item.id,
        name: item.name,
        name_he: item.name_he,
        main_nahal: item.main_nahal,
        flows_into: item.flows_into,
        basin: item.basin,
        basin_name: item.basin_name || '',
        area: item.area,
        perennial: item.perennial,
        extension: item.extension,
        geometry: {type: 'LineString', coordinates: copyLine(item.coordinates)}
      };
    }

    function basinsPayload() {
      return {
        basins: basins.map(function (item) {
          var outer = item.coordinates[0];
          var step = outer.length > 180 ? 3 : 1;
          var rings = [copyLine(simplify(outer, step))];
          for (var i = 1; i < item.coordinates.length; i++) rings.push(copyLine(item.coordinates[i]));
          return {
            id: item.id,
            name: item.name,
            main_nahal: item.main_nahal,
            desert: item.desert,
            perennial: item.perennial,
            coordinates: rings
          };
        })
      };
    }

    function health() {
      return {
        ok: true,
        private: true,
        writes: false,
        streams: streams.length,
        basins: basins.length
      };
    }

    function flag(params, key) {
      var value = params.get(key);
      if (value == null || value === '') return true;
      return value !== '0';
    }

    function answer(pathname, params) {
      if (pathname === '/api/health') return {status: 200, body: health()};
      if (pathname === '/api/search') {
        var kind = params.get('kind') || '';
        if (kind !== '' && kind !== 'stream' && kind !== 'basin') {
          return {status: 400, body: {error: 'bad kind'}};
        }
        return {status: 200, body: {results: search((params.get('q') || '').slice(0, 80), null, kind)}};
      }
      if (pathname === '/api/basins') return {status: 200, body: basinsPayload()};
      if (pathname === '/api/view') {
        var numbers = ['west', 'south', 'east', 'north', 'zoom'].map(function (key) {
          return Number(params.get(key));
        });
        if (!numbers.every(finite)) return {status: 400, body: {error: 'bad bounds'}};
        var west = numbers[0];
        var south = numbers[1];
        var east = numbers[2];
        var north = numbers[3];
        var zoom = numbers[4];
        if (east <= west || north <= south || zoom < 0 || zoom > 22) {
          return {status: 400, body: {error: 'bad bounds'}};
        }
        return {
          status: 200,
          body: view(west, south, east, north, zoom, flag(params, 'desert'), flag(params, 'north_on'), flag(params, 'ext'))
        };
      }
      if (pathname === '/api/feature') {
        var layer = params.get('layer') || '';
        var raw = params.get('id') || '';
        if (!LAYERS[layer] || !/^\d+$/.test(raw)) return {status: 400, body: {error: 'bad feature'}};
        var found = feature(layer, parseInt(raw, 10));
        if (!found) return {status: 404, body: {error: 'not found'}};
        return {status: 200, body: found};
      }
      return {status: 404, body: {error: 'not found'}};
    }

    return {
      streams: streams,
      basins: basins,
      search: search,
      view: view,
      feature: feature,
      basinsPayload: basinsPayload,
      health: health,
      answer: answer
    };
  }

  function dataBase() {
    return new URL('../data/', window.location.href);
  }

  function loadCatalog(fetchFn) {
    var base = dataBase();
    var jobs = STREAM_FILES.map(function (spec) {
      return fetchFn(new URL(spec[1], base).href, {cache: 'no-cache'}).then(function (res) {
        if (!res.ok) throw new Error(spec[1]);
        return res.json().then(function (collection) {
          return {layer: spec[0], extension: spec[2], collection: collection};
        });
      });
    });
    jobs.push(fetchFn(new URL(BASIN_FILE, base).href, {cache: 'no-cache'}).then(function (res) {
      if (!res.ok) throw new Error(BASIN_FILE);
      return res.json();
    }));
    return Promise.all(jobs).then(function (loaded) {
      var basinCollection = loaded[loaded.length - 1];
      return createCatalog({streams: loaded.slice(0, -1), basins: basinCollection});
    });
  }

  function install() {
    if (typeof window === 'undefined' || typeof window.fetch !== 'function') return;
    var original = window.fetch.bind(window);
    var pending = null;
    function ensure() {
      if (!pending) {
        pending = loadCatalog(original).catch(function (err) {
          pending = null;
          throw err;
        });
      }
      return pending;
    }
    window.fetch = function (input, init) {
      var raw = typeof input === 'string' ? input : (input && input.url ? input.url : '');
      var parsed;
      try {
        parsed = new URL(raw, window.location.href);
      } catch (err) {
        return original(input, init);
      }
      if (parsed.origin !== window.location.origin || parsed.pathname.indexOf('/api/') !== 0) {
        return original(input, init);
      }
      return ensure().then(function (catalog) {
        var result = catalog.answer(parsed.pathname, parsed.searchParams);
        return new Response(JSON.stringify(result.body), {
          status: result.status,
          headers: {'Content-Type': 'application/json; charset=utf-8'}
        });
      }, function () {
        return new Response(JSON.stringify({error: 'load failed'}), {
          status: 503,
          headers: {'Content-Type': 'application/json; charset=utf-8'}
        });
      });
    };
  }

  return {
    STREAM_FILES: STREAM_FILES,
    BASIN_FILE: BASIN_FILE,
    createCatalog: createCatalog,
    install: install,
    norm: norm,
    simplify: simplify
  };
});
