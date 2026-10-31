// Pure checks shared by the report screens. No network, no DOM.
var ISRAEL = {latMin: 29.3, latMax: 33.5, lonMin: 34.1, lonMax: 36.0};
var REPORT_WAVES = {first_now: 1, already_flowing: 1};
var REPORT_FLOWS = {weak: 1, medium: 1, strong: 1};
var FEEDBACK_RATINGS = {correct: 1, false_alarm: 1, missed: 1, eta_wrong: 1, other: 1};

function inIsrael(lat, lon) {
  return typeof lat === 'number' && typeof lon === 'number' && isFinite(lat) && isFinite(lon) &&
    lat >= ISRAEL.latMin && lat <= ISRAEL.latMax && lon >= ISRAEL.lonMin && lon <= ISRAEL.lonMax;
}
function deviceIdOk(id) { return typeof id === 'string' && /^u[a-z0-9]{6,20}$/.test(id); }
function reportIdOk(id) { return typeof id === 'string' && /^[a-z0-9]{8,40}$/.test(id); }

// JPEG APP1 Exif date only (DateTimeOriginal, else DateTimeDigitized, else DateTime). GPS is ignored.
function readJpegCaptureTime(input) {
  var u8 = input instanceof Uint8Array ? input : new Uint8Array(input);
  if (u8.length < 4 || u8[0] !== 0xff || u8[1] !== 0xd8) return null;
  var o = 2;
  while (o + 4 < u8.length) {
    if (u8[o] !== 0xff) return null;
    var marker = u8[o + 1];
    if (marker === 0xd9 || marker === 0xda) break;
    if (marker === 0x01 || (marker >= 0xd0 && marker <= 0xd7)) { o += 2; continue; }
    var len = (u8[o + 2] << 8) | u8[o + 3];
    if (len < 2 || o + 2 + len > u8.length) return null;
    if (marker === 0xe1 && len >= 8 &&
        u8[o + 4] === 0x45 && u8[o + 5] === 0x78 && u8[o + 6] === 0x69 && u8[o + 7] === 0x66 &&
        u8[o + 8] === 0 && u8[o + 9] === 0) {
      var found = tiffCaptureTime_(u8, o + 10, o + 2 + len);
      if (found) return found;
    }
    o += 2 + len;
  }
  return null;
}

function tiffCaptureTime_(u8, tiff, end) {
  if (tiff + 8 > end) return null;
  var le = u8[tiff] === 0x49 && u8[tiff + 1] === 0x49;
  var be = u8[tiff] === 0x4d && u8[tiff + 1] === 0x4d;
  if (!le && !be) return null;
  function u16(p) { return le ? u8[p] | (u8[p + 1] << 8) : (u8[p] << 8) | u8[p + 1]; }
  function u32(p) {
    return le ? (u8[p] | (u8[p + 1] << 8) | (u8[p + 2] << 16) | (u8[p + 3] << 24)) >>> 0
              : ((u8[p] << 24) | (u8[p + 1] << 16) | (u8[p + 2] << 8) | u8[p + 3]) >>> 0;
  }
  if (u16(tiff + 2) !== 42) return null;
  var plain = null, original = null;
  function asciiAt(type, count, valuePos) {
    if (type !== 2 || count < 19 || count > 32) return null;
    var pos = count <= 4 ? valuePos : tiff + u32(valuePos);
    if (pos < tiff || pos + 19 > end) return null;
    var s = '';
    for (var i = 0; i < 19; i++) s += String.fromCharCode(u8[pos + i]);
    return /^\d{4}:\d{2}:\d{2} \d{2}:\d{2}:\d{2}$/.test(s) ? s.slice(0, 10).replace(/:/g, '-') + 'T' + s.slice(11) : null;
  }
  function walk(ifd) {
    if (ifd < tiff || ifd + 2 > end) return;
    var n = u16(ifd), exifPtr = 0;
    for (var i = 0; i < n; i++) {
      var e = ifd + 2 + i * 12;
      if (e + 12 > end) return;
      var tag = u16(e), type = u16(e + 2), count = u32(e + 4);
      if (tag === 0x0132) plain = plain || asciiAt(type, count, e + 8);
      if (tag === 0x8769 && type === 4 && count === 1) exifPtr = u32(e + 8);
      if (tag === 0x9003) original = asciiAt(type, count, e + 8) || original;
      if (tag === 0x9004 && !original) original = asciiAt(type, count, e + 8) || original;
    }
    if (exifPtr) walk(tiff + exifPtr);
  }
  walk(tiff + u32(tiff + 4));
  return original || plain || null;
}
