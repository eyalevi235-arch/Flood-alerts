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

console.log('edit logic ok');
