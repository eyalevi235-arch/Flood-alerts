/* Password gate for the unlisted editor.
   The relative path is not stored in this file. A correct password decrypts it
   in the browser (PBKDF2-SHA256, 250000 iterations, AES-GCM) and this device
   remembers only that relative path. */
(function (root, factory) {
  'use strict';
  var api = factory();
  if (typeof module === 'object' && module.exports) module.exports = api;
  else root.EditorGate = api;
  if (typeof document !== 'undefined') api.boot();
})(typeof globalThis !== 'undefined' ? globalThis : this, function () {
  'use strict';

  var STORE_KEY = 'editor_rel_v1';
  var ITERATIONS = 250000;
  var EDITOR_BLOB = {
    v: 1,
    kdf: 'PBKDF2-SHA256',
    iterations: 250000,
    salt: 'ikgiVJLRRbNgD97tIGjgRg==',
    iv: 'spl1cWQlzsAZfuyv',
    ct: 'fz6pmJhupTvGFQvJxnNZJwQe5wlO47N4NZK0X7ogGOFVBQ=='
  };

  function bytesFromBase64(value) {
    if (typeof value !== 'string' || !value) return null;
    var bin;
    try {
      bin = atob(value);
    } catch (e) {
      return null;
    }
    var out = new Uint8Array(bin.length);
    for (var i = 0; i < bin.length; i++) out[i] = bin.charCodeAt(i) & 255;
    return out;
  }

  function isSafeRelativeDir(text) {
    return typeof text === 'string' &&
      text.length >= 2 &&
      text.length <= 128 &&
      /^[A-Za-z0-9._~-]+(?:\/[A-Za-z0-9._~-]+)*\/$/.test(text);
  }

  function resolveEditorUrl(relativePath, baseHref) {
    if (!isSafeRelativeDir(relativePath)) return null;
    try {
      var base = new URL('./', baseHref);
      var target = new URL(relativePath, base);
      if (target.origin !== base.origin) return null;
      if (target.search !== '' || target.hash !== '') return null;
      var basePath = base.pathname;
      if (basePath.charAt(basePath.length - 1) !== '/') basePath += '/';
      if (target.pathname.indexOf(basePath) !== 0) return null;
      if (target.pathname.charAt(target.pathname.length - 1) !== '/') return null;
      return target.href;
    } catch (e) {
      return null;
    }
  }

  function planEntry(storedValue, baseHref) {
    var href = resolveEditorUrl(storedValue, baseHref);
    if (!href) return {action: 'prompt'};
    return {action: 'go', href: href};
  }

  async function decryptEditorPath(password, blob) {
    try {
      if (typeof password !== 'string' || password.length === 0) return null;
      if (!blob || blob.v !== 1 || blob.kdf !== 'PBKDF2-SHA256' || blob.iterations !== ITERATIONS) return null;
      var subtle = globalThis.crypto && globalThis.crypto.subtle;
      if (!subtle) return null;
      var salt = bytesFromBase64(blob.salt);
      var iv = bytesFromBase64(blob.iv);
      var ct = bytesFromBase64(blob.ct);
      if (!salt || salt.length !== 16 || !iv || iv.length !== 12 || !ct || ct.length <= 16) return null;
      var encoded = new TextEncoder().encode(password.normalize('NFC'));
      var material = await subtle.importKey('raw', encoded, 'PBKDF2', false, ['deriveKey']);
      var key = await subtle.deriveKey(
        {name: 'PBKDF2', salt: salt, iterations: ITERATIONS, hash: 'SHA-256'},
        material,
        {name: 'AES-GCM', length: 256},
        false,
        ['decrypt']
      );
      var plainBuf = await subtle.decrypt({name: 'AES-GCM', iv: iv}, key, ct);
      var text = new TextDecoder('utf-8', {fatal: true}).decode(plainBuf);
      if (!isSafeRelativeDir(text)) return null;
      return text;
    } catch (e) {
      return null;
    }
  }

  function boot() {
    if (typeof document === 'undefined') return;
    var openBtn = document.getElementById('open-editor');
    var gate = document.getElementById('editor-gate');
    var form = document.getElementById('editor-gate-form');
    var input = document.getElementById('editor-pass');
    var err = document.getElementById('editor-gate-err');
    var goBtn = document.getElementById('editor-gate-go');
    var cancelBtn = document.getElementById('editor-gate-cancel');
    if (!openBtn || !gate || !form || !input || !err || !goBtn || !cancelBtn) return;
    if (openBtn.dataset.gateReady === '1') return;
    openBtn.dataset.gateReady = '1';

    var ticket = 0;

    function readStored() {
      var value = null;
      try {
        value = localStorage.getItem(STORE_KEY);
      } catch (e) {
        return null;
      }
      if (!value) return null;
      if (!resolveEditorUrl(value, document.baseURI)) {
        try { localStorage.removeItem(STORE_KEY); } catch (e2) {}
        return null;
      }
      return value;
    }

    function setBusy(on) {
      input.disabled = on;
      goBtn.disabled = on;
      goBtn.textContent = on ? 'בודק…' : 'כניסה';
      if (on) form.setAttribute('aria-busy', 'true');
      else form.removeAttribute('aria-busy');
    }

    function clearError() {
      err.hidden = true;
      input.removeAttribute('aria-invalid');
    }

    function showError() {
      setBusy(false);
      err.hidden = false;
      input.setAttribute('aria-invalid', 'true');
      input.focus();
      input.select();
    }

    function closeModal() {
      ticket += 1;
      setBusy(false);
      clearError();
      input.value = '';
      gate.hidden = true;
      openBtn.focus();
    }

    function openModal() {
      clearError();
      input.value = '';
      setBusy(false);
      gate.hidden = false;
      input.focus();
    }

    openBtn.addEventListener('click', function () {
      var plan = planEntry(readStored(), document.baseURI);
      if (plan.action === 'go') {
        window.location.assign(plan.href);
        return;
      }
      openModal();
    });

    cancelBtn.addEventListener('click', closeModal);
    gate.addEventListener('click', function (e) {
      if (e.target === gate) closeModal();
    });
    gate.addEventListener('keydown', function (e) {
      if (e.key === 'Escape') {
        e.preventDefault();
        closeModal();
      }
    });
    input.addEventListener('input', clearError);

    form.addEventListener('submit', function (e) {
      e.preventDefault();
      if (goBtn.disabled) return;
      var password = input.value;
      clearError();
      var my = ++ticket;
      setBusy(true);
      decryptEditorPath(password, EDITOR_BLOB).then(function (rel) {
        if (my !== ticket) return;
        var href = rel ? resolveEditorUrl(rel, document.baseURI) : null;
        if (!href) {
          showError();
          return;
        }
        try { localStorage.setItem(STORE_KEY, rel); } catch (errSave) {}
        input.value = '';
        window.location.assign(href);
      });
    });
  }

  return {
    EDITOR_BLOB: EDITOR_BLOB,
    STORE_KEY: STORE_KEY,
    decryptEditorPath: decryptEditorPath,
    isSafeRelativeDir: isSafeRelativeDir,
    resolveEditorUrl: resolveEditorUrl,
    planEntry: planEntry,
    boot: boot
  };
});
