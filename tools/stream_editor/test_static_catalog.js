'use strict';
const fs = require('fs');
const path = require('path');
const Cat = require('./static_catalog.js');

function readJson(file) {
  return JSON.parse(fs.readFileSync(file, 'utf8'));
}

function load(root) {
  const dataRoot = path.join(root, 'site', 'data');
  return Cat.createCatalog({
    streams: Cat.STREAM_FILES.map(function (spec) {
      return {layer: spec[0], extension: spec[2], collection: readJson(path.join(dataRoot, spec[1]))};
    }),
    basins: readJson(path.join(dataRoot, Cat.BASIN_FILE))
  });
}

function main() {
  const root = process.argv[2];
  const catalog = load(root);
  const queries = JSON.parse(fs.readFileSync(0, 'utf8'));
  const out = {health: catalog.health()};
  out.search = (queries.search || []).map(function (text) { return catalog.search(text); });
  out.view = (queries.view || []).map(function (item) {
    return catalog.view(item.west, item.south, item.east, item.north, item.zoom, item.desert, item.north_on, item.ext);
  });
  out.feature = (queries.feature || []).map(function (pair) { return catalog.feature(pair[0], pair[1]); });
  if (queries.basins) out.basins = catalog.basinsPayload();
  out.http = (queries.http || []).map(function (item) {
    return catalog.answer(item.path, new URLSearchParams(item.query || {}));
  });
  process.stdout.write(JSON.stringify(out));
}

main();
