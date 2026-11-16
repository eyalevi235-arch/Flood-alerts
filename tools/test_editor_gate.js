'use strict';

const assert = require('assert');
const fs = require('fs');
const path = require('path');
const Gate = require('../site/editor_gate.js');

function b64(bytes) {
  return Buffer.from(bytes).toString('base64');
}

async function encryptPath(password, relativePath) {
  const subtle = globalThis.crypto.subtle;
  const salt = globalThis.crypto.getRandomValues(new Uint8Array(16));
  const iv = globalThis.crypto.getRandomValues(new Uint8Array(12));
  const material = await subtle.importKey(
    'raw',
    new TextEncoder().encode(password.normalize('NFC')),
    'PBKDF2',
    false,
    ['deriveKey']
  );
  const key = await subtle.deriveKey(
    {name: 'PBKDF2', salt: salt, iterations: 250000, hash: 'SHA-256'},
    material,
    {name: 'AES-GCM', length: 256},
    false,
    ['encrypt']
  );
  const ct = new Uint8Array(await subtle.encrypt(
    {name: 'AES-GCM', iv: iv},
    key,
    new TextEncoder().encode(relativePath)
  ));
  return {
    v: 1,
    kdf: 'PBKDF2-SHA256',
    iterations: 250000,
    salt: b64(salt),
    iv: b64(iv),
    ct: b64(ct)
  };
}

function assertMainSiteOmitsPrivateDirs() {
  const site = path.join(__dirname, '..', 'site');
  const skip = new Set(['data', 'vendor']);
  const privateNames = fs.readdirSync(site, {withFileTypes: true})
    .filter((ent) => ent.isDirectory() && !skip.has(ent.name))
    .map((ent) => ent.name);
  assert.ok(privateNames.length >= 1);
  for (const ent of fs.readdirSync(site, {withFileTypes: true})) {
    if (ent.isDirectory()) continue;
    if (!/\.(html|js|css)$/.test(ent.name)) continue;
    const text = fs.readFileSync(path.join(site, ent.name), 'utf8');
    for (const name of privateNames) {
      assert.strictEqual(text.includes(name), false);
    }
  }
}

async function main() {
  assert.ok(globalThis.crypto && globalThis.crypto.subtle, 'WebCrypto subtle is required');

  const blob = Gate.EDITOR_BLOB;
  assert.strictEqual(blob.v, 1);
  assert.strictEqual(blob.kdf, 'PBKDF2-SHA256');
  assert.strictEqual(blob.iterations, 250000);
  const salt = Buffer.from(blob.salt, 'base64');
  const iv = Buffer.from(blob.iv, 'base64');
  const ct = Buffer.from(blob.ct, 'base64');
  assert.strictEqual(salt.length, 16);
  assert.strictEqual(iv.length, 12);
  assert.ok(ct.length > 16);
  assert.strictEqual(atob(blob.salt).length, 16);
  assert.strictEqual(atob(blob.iv).length, 12);
  assert.ok(atob(blob.ct).length > 16);

  let wrong = 'threw';
  try {
    wrong = await Gate.decryptEditorPath('incorrect-password', blob);
  } catch (e) {
    assert.fail('wrong password should fail cleanly');
  }
  assert.strictEqual(wrong, null);
  assert.strictEqual(await Gate.decryptEditorPath('', blob), null);
  assert.strictEqual(await Gate.decryptEditorPath('incorrect-password', null), null);

  const nfd = 'cafe\u0301-throwaway';
  const nfc = nfd.normalize('NFC');
  assert.notStrictEqual(nfd, nfc);
  const relativePath = 'sample-entry/';
  const made = await encryptPath(nfc, relativePath);
  assert.strictEqual(await Gate.decryptEditorPath(nfd, made), relativePath);
  assert.strictEqual(await Gate.decryptEditorPath('incorrect-password', made), null);
  const lowered = Object.assign({}, made, {iterations: 1000});
  assert.strictEqual(await Gate.decryptEditorPath(nfd, lowered), null);

  const base = 'https://eyalevi235-arch.github.io/Flood-alerts/index.html';
  assert.strictEqual(
    Gate.resolveEditorUrl(relativePath, base),
    'https://eyalevi235-arch.github.io/Flood-alerts/sample-entry/'
  );
  assert.strictEqual(Gate.resolveEditorUrl('../sample-entry/', base), null);
  assert.strictEqual(Gate.resolveEditorUrl('/sample-entry/', base), null);
  assert.strictEqual(Gate.resolveEditorUrl('//evil.example/sample-entry/', base), null);
  assert.strictEqual(Gate.resolveEditorUrl('https://evil.example/sample-entry/', base), null);
  assert.strictEqual(Gate.resolveEditorUrl('sample-entry', base), null);
  assert.strictEqual(Gate.resolveEditorUrl('sample-entry/?x=1', base), null);
  assert.deepStrictEqual(Gate.planEntry(null, base), {action: 'prompt'});
  assert.deepStrictEqual(Gate.planEntry('not-a-path', base), {action: 'prompt'});
  assert.deepStrictEqual(Gate.planEntry(relativePath, base), {
    action: 'go',
    href: 'https://eyalevi235-arch.github.io/Flood-alerts/sample-entry/'
  });
  assert.strictEqual(Gate.STORE_KEY, 'editor_rel_v1');

  assertMainSiteOmitsPrivateDirs();
  console.log('editor gate: wrong password rejected; round-trip ok');
}

main().catch((err) => {
  console.error(err && err.message ? err.message : err);
  process.exit(1);
});
