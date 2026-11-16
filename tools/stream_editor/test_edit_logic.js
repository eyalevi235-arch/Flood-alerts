'use strict';
const assert = require('assert');
const Logic = require('./static/edit_logic.js');

const joined = Logic.mergeLines([[35, 30], [35.1, 30]], [[35.1, 30], [35.2, 30.1]]);
assert(joined, 'merge returns a line');
assert(joined.gapM < 1, 'touching ends have no gap');
assert.strictEqual(joined.coordinates.length, 3);
assert.deepStrictEqual(joined.coordinates[0], [35, 30]);
assert.deepStrictEqual(joined.coordinates[2], [35.2, 30.1]);

const reversed = Logic.mergeLines([[35.1, 30], [35, 30]], [[35.1, 30], [35.2, 30]]);
assert(reversed.gapM < 1);
assert.deepStrictEqual(reversed.coordinates[0], [35, 30]);
assert.deepStrictEqual(reversed.coordinates[1], [35.1, 30]);
assert.deepStrictEqual(reversed.coordinates[2], [35.2, 30]);

const extended = Logic.extend([[35, 30], [35.1, 30]], true);
assert.strictEqual(extended.length, 3);
assert(extended[2][0] > 35.1);

const shortened = Logic.shorten([[35, 30], [35.1, 30], [35.2, 30]], true);
assert.strictEqual(shortened.length, 2);
assert.strictEqual(Logic.shorten([[35, 30], [35.1, 30]], true), null);

const opened = Logic.openRing([[35, 30], [35.1, 30], [35.1, 30.1], [35, 30]]);
assert.strictEqual(opened.length, 3);
const closed = Logic.closeRing(opened);
assert.strictEqual(closed.length, 4);
assert.deepStrictEqual(closed[0], closed[3]);

assert.strictEqual(Logic.roundCoord([35.342084, 30.990416])[0], 35.34208);
assert(Logic.sameLine([[35, 30], [35, 30], [35.1, 30]], [[35, 30], [35.1, 30]]));

const line = [[35, 30], [35.2, 30], [35.4, 30], [35.6, 30]];
const inserted = Logic.insertAfter(line, 1, [35.3, 30.1]);
assert.strictEqual(inserted.length, 5);
assert.deepStrictEqual(inserted[2], Logic.roundCoord([35.3, 30.1]));
assert.strictEqual(Logic.insertAfter(line, 1, [35.2, 30]), null);
assert.strictEqual(Logic.insertAfter(line, -1, [35.1, 30]), null);
assert.strictEqual(Logic.removeIndex(line, 1).length, 3);
assert.deepStrictEqual(Logic.removeIndex(line, 1)[1], [35.4, 30]);
assert.strictEqual(Logic.removeIndex(line, 5), null);
assert.strictEqual(Logic.removeIndex([[35, 30], [35.1, 30]], 0), null);
assert.strictEqual(Logic.removeIndex([[35, 30], [35.1, 30], [35.2, 30]], 1, 3), null);
assert.strictEqual(Logic.removeIndex([[35, 30], [35.1, 30], [35.2, 30], [35.3, 30]], 1, 3).length, 3);

const mids = Logic.edgeMidpoints([[35, 30], [35.2, 30], [35.2, 30.2]], false);
assert.strictEqual(mids.length, 2);
assert.strictEqual(mids[0].after, 0);
assert.deepStrictEqual(mids[0].coord, Logic.roundCoord([35.1, 30]));
const ringMids = Logic.edgeMidpoints([[35, 30], [35.2, 30], [35.2, 30.2]], true);
assert.strictEqual(ringMids.length, 3);
assert.strictEqual(ringMids[2].after, 2);

const spaced = [];
for (let i = 0; i < 10; i++) spaced.push({x: i * 10, y: 0, inView: true});
assert.deepStrictEqual(Logic.visibleIndices(spaced, 48, 4, false), [0, 1, 2, 3, 4, 5, 6, 7, 8, 9]);
const wide = [];
for (let i = 0; i < 8; i++) wide.push({x: i * 100, y: 0, inView: i !== 3});
const visible = Logic.visibleIndices(wide, 48, 4, true);
assert.ok(visible.indexOf(3) < 0);
assert.strictEqual(visible[0], 0);
assert.strictEqual(visible[visible.length - 1], 7);

const kept = Logic.keptMidpoints([
  {after: 0, x: 0, y: 0, len: 40, inView: true},
  {after: 1, x: 80, y: 0, len: 90, inView: true},
  {after: 2, x: 100, y: 0, len: 90, inView: true},
  {after: 3, x: 200, y: 0, len: 80, inView: false}
], 56);
assert.deepStrictEqual(kept.map((item) => item.after), [1]);

const redrawn = Logic.redrawSection(line, 0, 3, [[35.3, 30.2]]);
assert.strictEqual(redrawn.length, 3);
assert.deepStrictEqual(redrawn[1], Logic.roundCoord([35.3, 30.2]));
const reversedDraw = Logic.redrawSection(line, 3, 1, [[35.5, 30.2], [35.3, 30.2]]);
assert.deepStrictEqual(reversedDraw[2], Logic.roundCoord([35.3, 30.2]));
assert.deepStrictEqual(reversedDraw[3], Logic.roundCoord([35.5, 30.2]));
assert.strictEqual(Logic.redrawSection(line, 1, 1, [[35.3, 30]]), null);
const straightened = Logic.redrawSection(line, 0, 3, []);
assert.strictEqual(straightened.length, 2);

function transition(dirty, action, choice) {
  return Logic.editTransition(dirty, action, choice);
}
assert.deepStrictEqual(transition(true, 'finish'), {commit: true, revert: false, deselect: true, stay: false, prompt: false});
assert.deepStrictEqual(transition(false, 'finish'), {commit: false, revert: false, deselect: true, stay: false, prompt: false});
assert.deepStrictEqual(transition(true, 'cancel'), {commit: false, revert: true, deselect: true, stay: false, prompt: false});
assert.deepStrictEqual(transition(false, 'cancel'), {commit: false, revert: true, deselect: true, stay: false, prompt: false});
assert.strictEqual(transition(false, 'select-other', null).prompt, false);
assert.strictEqual(transition(false, 'select-other', null).deselect, true);
assert.strictEqual(transition(true, 'select-other', null).prompt, true);
assert.strictEqual(transition(true, 'select-other', null).stay, true);
assert.deepStrictEqual(transition(true, 'select-other', 'commit'), {commit: true, revert: false, deselect: true, stay: false, prompt: false});
assert.deepStrictEqual(transition(true, 'select-other', 'discard'), {commit: false, revert: true, deselect: true, stay: false, prompt: false});
assert.deepStrictEqual(transition(true, 'select-other', 'stay'), {commit: false, revert: false, deselect: false, stay: true, prompt: false});
assert.strictEqual(transition(true, 'nope'), null);

assert.ok(Logic.tapSlopPx(true) >= 16, 'touch tap slop is at least 16px');
assert.ok(Logic.tapSlopPx(false) > 0 && Logic.tapSlopPx(false) < Logic.tapSlopPx(true));
assert.ok(2.5 / 2 + Logic.tapSlopPx(true) >= 16, 'a thin stream stays hittable with a finger');

assert.strictEqual(Logic.acceptTap('streams', 'stream'), true);
assert.strictEqual(Logic.acceptTap('streams', 'basin'), false);
assert.strictEqual(Logic.acceptTap('basins', 'basin'), true);
assert.strictEqual(Logic.acceptTap('basins', 'stream'), false);
assert.strictEqual(Logic.acceptTap('other', 'stream'), false);
assert.strictEqual(Logic.searchMatchesMode('streams', 'desert'), true);
assert.strictEqual(Logic.searchMatchesMode('streams', 'nondesert_extension'), true);
assert.strictEqual(Logic.searchMatchesMode('streams', 'basin'), false);
assert.strictEqual(Logic.searchMatchesMode('basins', 'basin'), true);
assert.strictEqual(Logic.searchMatchesMode('basins', 'desert'), false);
assert.strictEqual(Logic.basinChrome(false).interactive, false);
assert.ok(Logic.basinChrome(false).fillOpacity < Logic.basinChrome(true).fillOpacity);
assert.strictEqual(Logic.basinChrome(true).interactive, true);
assert.strictEqual(Logic.streamChrome(true).interactive, true);
assert.strictEqual(Logic.streamChrome(false).interactive, false);

// Touch tap with nothing open: the stream is accepted and select-other does not prompt.
var idle = Logic.editTransition(false, 'select-other', null);
assert.ok(idle, 'select-other returns a decision when the edit is clean');
assert.strictEqual(idle.prompt, false);
assert.strictEqual(idle.deselect, true);
assert.strictEqual(Logic.acceptTap('streams', 'stream'), true);

// Finish, then another stream: the cleared edit does not prompt.
var finished = Logic.editTransition(true, 'finish');
assert.deepStrictEqual(finished, {commit: true, revert: false, deselect: true, stay: false, prompt: false});
var nextStream = Logic.editTransition(false, 'select-other', null);
assert.strictEqual(nextStream.prompt, false);
assert.strictEqual(nextStream.deselect, true);

// Switching tabs during a dirty edit uses the same save / discard / stay decision.
var tabPrompt = Logic.editTransition(true, 'select-other', null);
assert.strictEqual(tabPrompt.prompt, true);
assert.strictEqual(tabPrompt.stay, true);
assert.strictEqual(Logic.editTransition(true, 'select-other', 'commit').deselect, true);
assert.strictEqual(Logic.editTransition(true, 'select-other', 'discard').revert, true);
assert.strictEqual(Logic.editTransition(true, 'select-other', 'stay').stay, true);
assert.ok(Logic.editTransition(false, 'select-other', 'stay'), 'select-other with a choice still returns');

var deleted = Logic.deleteStreamChange({
  mode: 'streams',
  layer: 'desert',
  id: 5620,
  name: 'אזור בוקק',
  note: 'מחיקה',
  coordinates: [[35.34458, 31.17208], [35.35542, 31.18292]],
  basin: 48188
});
assert.strictEqual(deleted.op, 'delete_stream');
assert.strictEqual(deleted.layer, 'desert');
assert.strictEqual(deleted.id, 5620);
assert.strictEqual(deleted.name, 'אזור בוקק');
assert.strictEqual(deleted.old_basin, '48188');
assert.strictEqual(deleted.old_geometry.type, 'LineString');
assert.strictEqual(deleted.old_geometry.coordinates.length, 2);
assert.strictEqual(Logic.deleteStreamChange({
  mode: 'basins', layer: 'desert', id: 1, note: 'מחיקה', coordinates: [[35, 30], [35.1, 30]]
}), null);
assert.strictEqual(Logic.deleteStreamChange({
  mode: 'streams', layer: 'basin', id: 1, note: 'מחיקה', coordinates: [[35, 30], [35.1, 30]]
}), null);
assert.strictEqual(Logic.deleteStreamChange({
  mode: 'streams', layer: 'desert', id: 1, note: '   ', coordinates: [[35, 30], [35.1, 30]]
}), null);

assert.strictEqual(Logic.normalizeAuthorization('abc'), 'Bearer abc');
assert.strictEqual(Logic.normalizeAuthorization('  Bearer abc  '), 'Bearer abc');
assert.strictEqual(Logic.normalizeAuthorization('bearer abc'), 'Bearer abc');
assert.strictEqual(Logic.normalizeAuthorization('BEARER abc'), 'Bearer abc');
assert.strictEqual(Logic.normalizeAuthorization('Bearer   abc'), 'Bearer abc');
assert.strictEqual(Logic.normalizeAuthorization(''), '');
assert.strictEqual(Logic.normalizeAuthorization('   '), '');
assert.strictEqual(Logic.normalizeAuthorization('Bearer'), '');
assert.strictEqual(Logic.normalizeAuthorization('Bearer   '), '');
assert.strictEqual(Logic.normalizeAuthorization(null), '');
assert.strictEqual(Logic.webhookUrl('https://example.com/hook'), 'https://example.com/hook');
assert.strictEqual(Logic.webhookUrl(' http://127.0.0.1:9/fail '), 'http://127.0.0.1:9/fail');
assert.strictEqual(Logic.webhookUrl('ftp://example.com/hook'), '');
assert.strictEqual(Logic.webhookUrl('javascript:alert(1)'), '');
assert.strictEqual(Logic.webhookUrl(''), '');
assert.strictEqual(Logic.webhookUrl('https://example.com/hook extra'), '');
assert.strictEqual(Logic.sendConfirmLabel(1), 'לשלוח שינוי אחד לפרוייקטור?');
assert.strictEqual(Logic.sendConfirmLabel(3), 'לשלוח 3 שינויים לפרוייקטור?');
assert.strictEqual(Logic.SEND_OK_TEXT, 'נשלח ✓');
assert.ok(Logic.sendFailureText(403).indexOf('סטטוס 403') > 0);
assert.ok(Logic.sendFailureText(500).indexOf('להוריד את הקובץ') > 0);
assert.ok(Logic.sendFailureText(null).indexOf('אין סטטוס') > 0);
assert.ok(Logic.sendFailureText(null).indexOf('403') < 0);
assert.strictEqual(Logic.SEND_URL_KEY, 'flood-editor-send-url');
assert.strictEqual(Logic.SEND_AUTH_KEY, 'flood-editor-send-auth');

assert.strictEqual(Logic.streamIdentity({name_he: 'נחל צין', name: 'בשור'}), 'צין');
assert.strictEqual(Logic.streamIdentity({name_he: '', name: 'נחל־פארן'}), 'פארן');
assert.strictEqual(Logic.streamIdentity({name_he: null, name: ''}), '');
assert.ok(Logic.coordsCoincide([35.1, 30.1], [35.1 + 4e-8, 30.1]));
assert.ok(Logic.coordsCoincide([35.100004, 30.100004], [35.1, 30.1]));
assert.ok(!Logic.coordsCoincide([35.10002, 30.10002], [35.1, 30.1]));

var segments = [
  {layer: 'desert', id: 1, name: 'צין', name_he: 'נחל צין', perennial: false, coordinates: [[35, 30], [35.1, 30.1]]},
  {layer: 'desert', id: 2, name: 'צין', name_he: 'נחל צין', perennial: false, coordinates: [[35.1, 30.1], [35.2, 30.2]]},
  {layer: 'desert', id: 3, name: 'צין', name_he: 'נחל צין', perennial: false, coordinates: [[35.1, 30.1], [35.1, 30.3]]},
  {layer: 'desert', id: 4, name: 'צין', name_he: 'נחל צין', perennial: false, coordinates: [[36, 31], [36.1, 31]]},
  {layer: 'nondesert', id: 8, name: 'צין', name_he: 'נחל צין', perennial: true, coordinates: [[35, 30], [34.9, 29.9]]},
  {layer: 'nondesert', id: 9, name: 'יובל', name_he: 'נחל יובל', perennial: true, coordinates: [[35.2, 30.2], [35.3, 30.4]]},
  {layer: 'desert', id: 5, name: 'צין', name_he: '', perennial: false, coordinates: [[35.2, 30.2], [35.25, 30.25]]},
  {layer: 'desert', id: 6, name: 'אחר', name_he: 'נחל אחר', perennial: false, coordinates: [[35.100004, 30.100004], [35.4, 30.4]]},
  {layer: 'desert_extension', id: 10, name: '', name_he: '', src_layer: 'desert', src_seg: 2, coordinates: [[35.25, 30.25], [35.26, 30.26]]}
];
var group = Logic.groupStream(segments, 'desert', 1);
assert.strictEqual(group.identity, 'צין');
var memberIds = group.members.map(function (item) { return item.layer + ':' + item.id; }).sort();
assert.deepStrictEqual(memberIds, ['desert:1', 'desert:2', 'desert:3', 'desert:5', 'desert_extension:10', 'nondesert:8']);
assert.ok(memberIds.indexOf('desert:4') < 0, 'disconnected same name stays out');
assert.ok(memberIds.indexOf('nondesert:9') < 0, 'other stream at the junction stays out');
assert.ok(memberIds.indexOf('desert:6') < 0, 'different name is not the same stream');
var neighborIds = group.neighbors.map(function (item) { return item.id; }).sort();
assert.ok(neighborIds.indexOf(9) >= 0);
assert.ok(neighborIds.indexOf(6) >= 0);
assert.ok(group.members.some(function (item) { return item.perennial; }));
assert.ok(group.members.some(function (item) { return !item.perennial; }));

var parts = [
  {layer: 'desert', id: 1, name: 'צין', basin: '10', originalBasin: '10', original: [[35, 30], [35.1, 30.1]], coordinates: [[35, 30], [35.1, 30.1]]},
  {layer: 'desert', id: 2, name: 'צין', basin: '10', originalBasin: '10', original: [[35.1, 30.1], [35.15, 30.15], [35.2, 30.2]], coordinates: [[35.1, 30.1], [35.15, 30.15], [35.2, 30.2]]},
  {layer: 'nondesert', id: 9, name: 'יובל', name_he: 'נחל יובל', perennial: true, basin: '11', originalBasin: '11', original: [[35.1, 30.1], [35.15, 30.3]], coordinates: [[35.1, 30.1], [35.15, 30.3]]}
];
var beforePairs = Logic.touchingPairs(parts);
var refs = Logic.sharedRefs(parts, [35.1, 30.1]);
assert.strictEqual(refs.length, 3);
Logic.applySharedMove(parts, refs, [35.11, 30.12], true);
var moved = Logic.roundCoord([35.11, 30.12]);
assert.deepStrictEqual(parts[0].coordinates[1], moved);
assert.deepStrictEqual(parts[1].coordinates[0], moved);
assert.deepStrictEqual(parts[2].coordinates[0], moved);
assert.deepStrictEqual(parts[0].coordinates[0], [35, 30]);
assert.deepStrictEqual(parts[1].coordinates[parts[1].coordinates.length - 1], [35.2, 30.2]);
assert.strictEqual(Logic.touchingPairs(parts), beforePairs);
assert.ok(Logic.partsTouch(parts[0].coordinates, parts[2].coordinates));
assert.strictEqual(Logic.removeSharedVertex(parts, 0, 1, 2), null);
assert.strictEqual(Logic.shortenShared(parts, 1, false), null);
var trimmed = Logic.removeSharedVertex(parts, 1, 1, 2);
assert.ok(trimmed);
assert.deepStrictEqual(trimmed[0], moved);
assert.strictEqual(Logic.touchingPairs([
  {coordinates: parts[0].coordinates},
  {coordinates: trimmed},
  {coordinates: parts[2].coordinates}
]), 3);

var reviewed = Logic.reviewStreamChanges(parts, 'הזזת חיבור', ['move']);
assert.strictEqual(reviewed.length, 3);
var reviewIds = reviewed.map(function (change) { return change.layer + ':' + change.id; }).sort();
assert.deepStrictEqual(reviewIds, ['desert:1', 'desert:2', 'nondesert:9']);
reviewed.forEach(function (change) {
  var line = change.new_geometry.coordinates;
  assert.ok(line.some(function (point) { return point[0] === moved[0] && point[1] === moved[1]; }));
});
assert.strictEqual(Logic.touchingPairs(reviewed.map(function (change) {
  return {coordinates: change.new_geometry.coordinates};
})), 3);

var redrawnJunction = Logic.redrawSection(parts[0].coordinates, 0, 1, [[35.05, 30.05]]);
assert.deepStrictEqual(redrawnJunction[0], parts[0].coordinates[0]);
assert.deepStrictEqual(redrawnJunction[redrawnJunction.length - 1], parts[0].coordinates[parts[0].coordinates.length - 1]);

var deletedWhole = Logic.deleteStreamChanges([
  {layer: 'desert', id: 2, name: 'צין', coordinates: [[35.1, 30.1], [35.2, 30.2]], basin: '10'},
  {layer: 'desert_extension', id: 10, name: '', coordinates: [[35.25, 30.25], [35.26, 30.26]], basin: '10'}
], 'מחיקת הנחל כולו');
assert.strictEqual(deletedWhole.length, 2);
assert.strictEqual(deletedWhole[0].layer, 'desert_extension');
assert.strictEqual(deletedWhole[1].op, 'delete_stream');
assert.strictEqual(deletedWhole[1].id, 2);

console.log('edit logic ok');
