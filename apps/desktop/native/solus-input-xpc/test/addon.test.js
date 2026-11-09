// Runs the addon built against the LOCAL Node headers (`npm test`): the
// Electron build cannot load in plain Node. Real XPC needs the signed,
// registered agent (QA pass); this proves the module's contract and that it
// fails closed while the team ID is the placeholder.
'use strict';
const test = require('node:test');
const assert = require('node:assert');
const path = require('node:path');

const addon = require(path.join(__dirname, '..', process.env.SOLUS_XPC_ADDON || 'build/Release/solus_input_xpc.node'));
const trust = '{"v":1,"op":"trust","prompt":false}';

test('exports request, cancel and checkOwnBundle', () => {
  assert.deepStrictEqual(Object.keys(addon).sort(), ['cancel', 'checkOwnBundle', 'request']);
});

test('request returns its id and a promise', async () => {
  const first = addon.request(trust, 1000);
  const second = addon.request(trust, 1000);
  assert.deepStrictEqual(Object.keys(first).sort(), ['id', 'promise']);
  assert.ok(Number.isSafeInteger(first.id) && first.id > 0);
  assert.strictEqual(second.id, first.id + 1, 'ids are per request');
  assert.ok(first.promise instanceof Promise);
  await assert.rejects(first.promise, /team ID is not set/);
  await assert.rejects(second.promise, /team ID is not set/);
});

test('checkOwnBundle is false while the team ID is the placeholder', async () => {
  const result = addon.checkOwnBundle();
  assert.ok(result instanceof Promise);
  assert.strictEqual(await result, false);
});

test('a request must be a JSON object (the module adds its id)', async () => {
  for (const json of ['', 'garbage', '[]', '1', 'null']) {
    await assert.rejects(addon.request(json, 1000).promise, /JSON object/, json);
  }
});

test('validates its arguments', () => {
  assert.throws(() => addon.request(), TypeError);
  assert.throws(() => addon.request(1, 1000), TypeError);
  assert.throws(() => addon.request('{}', 'soon'), TypeError);
  for (const ms of [0, -1, NaN, Infinity, 600001]) {
    assert.throws(() => addon.request('{}', ms), RangeError, String(ms));
  }
});

test('refuses an oversize request before anything is sent', async () => {
  await assert.rejects(addon.request('x'.repeat(65537), 1000).promise, /64 KiB/);
});

test('cancel takes one request id; an unknown id is a no-op', () => {
  assert.strictEqual(addon.cancel(123456), undefined);
  for (const bad of [undefined, '1', 0, -1, 1.5, NaN]) {
    assert.throws(() => addon.cancel(bad), /request id/, String(bad));
  }
});
