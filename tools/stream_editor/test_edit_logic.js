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

console.log('edit logic ok');
