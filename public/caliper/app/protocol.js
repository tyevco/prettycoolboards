// PrettyCool Caliper rev A: BLE GATT protocol (pure functions, no DOM, no Web Bluetooth).
//
// This file mirrors the GATT contract that the firmware implements in
// caliper/firmware/main/proto/caliper_gatt.h. All integers are little-endian.
// It is imported by index.html (app.js) in the browser and by protocol.test.mjs under `node --test`.

// ---------------------------------------------------------------------------------------------
// UUIDs
// ---------------------------------------------------------------------------------------------

/** Build a characteristic UUID on the custom base by replacing the 2nd 16-bit group. */
export function caliperUuid(short16) {
  const hex = (short16 & 0xffff).toString(16).padStart(4, '0');
  return `7c0a${hex}-5e1f-4b8a-9c3d-2f6a1e0c7b11`;
}

export const UUID = Object.freeze({
  SERVICE: caliperUuid(0x0001),
  LIVE: caliperUuid(0x0002),
  COMMAND: caliperUuid(0x0003),
  LOG: caliperUuid(0x0004),
  SETTINGS: caliperUuid(0x0005),
  PROFILES: caliperUuid(0x0006),
  // Standard SIG services/characteristics (Web Bluetooth accepts these names).
  BATTERY_SERVICE: 'battery_service', // 0x180F
  BATTERY_LEVEL: 'battery_level', // 0x2A19
  DEVICE_INFO_SERVICE: 'device_information', // 0x180A
  // HID over GATT (0x1812) is on the Web Bluetooth blocklist, so the page never asks for it.
});

export const DIS_CHARS = Object.freeze([
  ['manufacturer', 'manufacturer_name_string'], // 0x2A29
  ['model', 'model_number_string'], // 0x2A24
  ['hardware', 'hardware_revision_string'], // 0x2A27
  ['firmware', 'firmware_revision_string'], // 0x2A26
  // serial_number_string (0x2A25) is blocklisted for reads in Chrome.
]);

// ---------------------------------------------------------------------------------------------
// Constants
// ---------------------------------------------------------------------------------------------

export const INT32_MIN = -0x80000000;
export const LOG_END_SEQ = 0xffffffff;
export const LIVE_LEN = 10;
export const LOG_RECORD_LEN = 16;
export const PROFILE_RECORD_LEN = 30;
export const PROFILE_NAME_LEN = 16;
export const PROFILES_MAX = 16; // CALIPER_PROFILES_MAX: 16 x 30 = 480 B
export const SETTINGS_MAX_BYTES = 240;

export const UNIT = Object.freeze({ MM: 0, INCH: 1 });
export const NM_PER_MM = 1e6;
export const NM_PER_INCH = 25.4e6;

export const FLAG = Object.freeze({
  HOLD: 1 << 0,
  TOL_PASS: 1 << 1,
  TOL_FAIL: 1 << 2,
  SENSOR_ERR: 1 << 3,
  CAP_VALID: 1 << 4,
  CHARGING: 1 << 5,
});

export const OP = Object.freeze({
  ZERO: 0x01,
  HOLD_TOGGLE: 0x02,
  RECORD_NOW: 0x03,
  SET_UNIT: 0x04,
  LOG_READ: 0x10,
  LOG_CLEAR: 0x11,
  SELECT_PROFILE: 0x20,
  SET_TIME: 0x30,
});

export const SETTINGS_KEYS = Object.freeze([
  'name', 'wifi_ssid', 'wifi_pass', 'mqtt_url', 'http_post_url', 'auto_off_s', 'hid_suffix', 'decimals',
]);
export const HID_SUFFIXES = Object.freeze(['\n', '\t', '']);
// Value limits the firmware enforces in settings.c (it rejects the whole write on any bad value);
// mirrored here so the page can say what is wrong before writing. Not part of caliper_gatt.h.
export const SETTINGS_STR_BYTES = Object.freeze({
  name: [0, 20], wifi_ssid: [0, 32], wifi_pass: [8, 64], mqtt_url: [0, 64], http_post_url: [0, 64],
});
export const SETTINGS_URL_PREFIXES = Object.freeze({
  mqtt_url: ['mqtt://', 'mqtts://', 'ws://', 'wss://'], http_post_url: ['http://', 'https://'],
});
export const AUTO_OFF_MIN_S = 30;
export const AUTO_OFF_MAX_S = 3600;
export const DECIMALS_MIN = 1;
export const DECIMALS_MAX = 3;

// ---------------------------------------------------------------------------------------------
// Byte helpers
// ---------------------------------------------------------------------------------------------

/** Accept a DataView, ArrayBuffer, typed array or plain array of bytes; return a DataView. */
export function toDataView(data) {
  if (data instanceof DataView) return data;
  if (data instanceof ArrayBuffer) return new DataView(data);
  if (ArrayBuffer.isView(data)) return new DataView(data.buffer, data.byteOffset, data.byteLength);
  if (Array.isArray(data)) return new DataView(Uint8Array.from(data).buffer);
  throw new TypeError('expected bytes (DataView, ArrayBuffer, typed array or array)');
}

export function toBytes(data) {
  const dv = toDataView(data);
  return new Uint8Array(dv.buffer, dv.byteOffset, dv.byteLength);
}

export function hex(data) {
  return Array.from(toBytes(data), (b) => b.toString(16).padStart(2, '0')).join(' ');
}

function checkI32(name, v) {
  if (!Number.isInteger(v) || v < INT32_MIN || v > 0x7fffffff) throw new RangeError(`${name} must be an int32, got ${v}`);
}
function checkU(name, v, bits) {
  const max = 2 ** bits - 1;
  if (!Number.isInteger(v) || v < 0 || v > max) throw new RangeError(`${name} must be a u${bits}, got ${v}`);
}

// ---------------------------------------------------------------------------------------------
// Flags
// ---------------------------------------------------------------------------------------------

export function decodeFlags(f) {
  return {
    hold: !!(f & FLAG.HOLD),
    tolPass: !!(f & FLAG.TOL_PASS),
    tolFail: !!(f & FLAG.TOL_FAIL),
    sensorErr: !!(f & FLAG.SENSOR_ERR),
    capValid: !!(f & FLAG.CAP_VALID),
    charging: !!(f & FLAG.CHARGING),
  };
}

export function encodeFlags(o) {
  return (o.hold ? FLAG.HOLD : 0) | (o.tolPass ? FLAG.TOL_PASS : 0) | (o.tolFail ? FLAG.TOL_FAIL : 0) |
    (o.sensorErr ? FLAG.SENSOR_ERR : 0) | (o.capValid ? FLAG.CAP_VALID : 0) | (o.charging ? FLAG.CHARGING : 0);
}

export function flagNames(f) {
  return Object.entries(FLAG).filter(([, bit]) => f & bit).map(([n]) => n);
}

// ---------------------------------------------------------------------------------------------
// LIVE (7c0a0002): 10 bytes {i32 value_nm, i32 cap_nm, u8 unit, u8 flags}
// ---------------------------------------------------------------------------------------------

/**
 * Decode a LIVE notification/read.
 * capNm is null when cap_nm == INT32_MIN or the CAP_VALID flag is clear.
 */
export function decodeLive(data) {
  const dv = toDataView(data);
  if (dv.byteLength < LIVE_LEN) throw new RangeError(`LIVE needs ${LIVE_LEN} bytes, got ${dv.byteLength}`);
  const valueNm = dv.getInt32(0, true);
  const capRaw = dv.getInt32(4, true);
  const unit = dv.getUint8(8);
  const flags = dv.getUint8(9);
  const f = decodeFlags(flags);
  const capNm = capRaw === INT32_MIN || !f.capValid ? null : capRaw;
  return { valueNm, capNm, capRaw, unit, flags, ...f };
}

/** Encode a LIVE packet (used by demo mode and tests). capNm null -> INT32_MIN. */
export function encodeLive({ valueNm, capNm = null, unit = UNIT.MM, flags = 0 }) {
  checkI32('valueNm', valueNm);
  const cap = capNm === null || capNm === undefined ? INT32_MIN : capNm;
  checkI32('capNm', cap);
  checkU('unit', unit, 8);
  checkU('flags', flags, 8);
  const out = new Uint8Array(LIVE_LEN);
  const dv = new DataView(out.buffer);
  dv.setInt32(0, valueNm, true);
  dv.setInt32(4, cap, true);
  dv.setUint8(8, unit);
  dv.setUint8(9, flags);
  return out;
}

// ---------------------------------------------------------------------------------------------
// COMMAND (7c0a0003): u8 opcode + payload
// ---------------------------------------------------------------------------------------------

function cmd(op, payloadLen, fill) {
  const out = new Uint8Array(1 + payloadLen);
  out[0] = op;
  if (fill) fill(new DataView(out.buffer, 1));
  return out;
}

export const encodeCommand = Object.freeze({
  zero: () => cmd(OP.ZERO, 0),
  holdToggle: () => cmd(OP.HOLD_TOGGLE, 0),
  recordNow: () => cmd(OP.RECORD_NOW, 0),
  setUnit: (unit) => { checkU('unit', unit, 8); return cmd(OP.SET_UNIT, 1, (d) => d.setUint8(0, unit)); },
  logRead: (fromSeq = 0) => { checkU('fromSeq', fromSeq, 32); return cmd(OP.LOG_READ, 4, (d) => d.setUint32(0, fromSeq, true)); },
  logClear: () => cmd(OP.LOG_CLEAR, 0),
  selectProfile: (id) => { checkU('profile id', id, 16); return cmd(OP.SELECT_PROFILE, 2, (d) => d.setUint16(0, id, true)); },
  setTime: (unixS) => { checkU('unix_s', unixS, 32); return cmd(OP.SET_TIME, 4, (d) => d.setUint32(0, unixS, true)); },
});

const OP_NAMES = Object.fromEntries(Object.entries(OP).map(([k, v]) => [v, k]));

/** Decode a COMMAND write (used by the demo-mode simulator and tests). */
export function decodeCommand(data) {
  const dv = toDataView(data);
  if (dv.byteLength < 1) throw new RangeError('empty command');
  const op = dv.getUint8(0);
  const name = OP_NAMES[op];
  if (!name) throw new RangeError(`unknown opcode 0x${op.toString(16)}`);
  const need = { SET_UNIT: 2, LOG_READ: 5, SELECT_PROFILE: 3, SET_TIME: 5 }[name] ?? 1;
  if (dv.byteLength !== need) throw new RangeError(`${name} needs ${need} bytes, got ${dv.byteLength}`);
  const c = { op, name };
  if (name === 'SET_UNIT') c.unit = dv.getUint8(1);
  if (name === 'LOG_READ') c.fromSeq = dv.getUint32(1, true);
  if (name === 'SELECT_PROFILE') c.profileId = dv.getUint16(1, true);
  if (name === 'SET_TIME') c.unixS = dv.getUint32(1, true);
  return c;
}

// ---------------------------------------------------------------------------------------------
// LOG (7c0a0004): notifications of packed 16-byte records
//   {u32 seq, u32 unix_s, i32 value_nm, u8 unit, u8 flags, u16 profile_id}
//   The stream ends with a record whose seq == 0xFFFFFFFF.
// ---------------------------------------------------------------------------------------------

export function decodeLogRecord(dv, off = 0) {
  const seq = dv.getUint32(off, true);
  const flags = dv.getUint8(off + 13);
  return {
    seq,
    unixS: dv.getUint32(off + 4, true),
    valueNm: dv.getInt32(off + 8, true),
    unit: dv.getUint8(off + 12),
    flags,
    profileId: dv.getUint16(off + 14, true),
    end: seq === LOG_END_SEQ,
  };
}

/** Decode one LOG notification into its records (the end marker is returned too, with end: true). */
export function decodeLogPacket(data) {
  const dv = toDataView(data);
  if (dv.byteLength === 0 || dv.byteLength % LOG_RECORD_LEN !== 0) {
    throw new RangeError(`LOG notification must be a non-zero multiple of ${LOG_RECORD_LEN} bytes, got ${dv.byteLength}`);
  }
  const out = [];
  for (let off = 0; off < dv.byteLength; off += LOG_RECORD_LEN) out.push(decodeLogRecord(dv, off));
  return out;
}

export function encodeLogRecord({ seq, unixS = 0, valueNm = 0, unit = 0, flags = 0, profileId = 0 }) {
  checkU('seq', seq, 32); checkU('unixS', unixS, 32); checkI32('valueNm', valueNm);
  checkU('unit', unit, 8); checkU('flags', flags, 8); checkU('profileId', profileId, 16);
  const out = new Uint8Array(LOG_RECORD_LEN);
  const dv = new DataView(out.buffer);
  dv.setUint32(0, seq, true);
  dv.setUint32(4, unixS, true);
  dv.setInt32(8, valueNm, true);
  dv.setUint8(12, unit);
  dv.setUint8(13, flags);
  dv.setUint16(14, profileId, true);
  return out;
}

export function encodeLogEnd() {
  return encodeLogRecord({ seq: LOG_END_SEQ });
}

/** Pack records (and optionally the end marker) into notifications of at most perPacket records each. */
export function encodeLogPackets(records, { perPacket = 15, withEnd = true } = {}) {
  const all = records.map(encodeLogRecord);
  if (withEnd) all.push(encodeLogEnd());
  const packets = [];
  for (let i = 0; i < all.length; i += perPacket) {
    const chunk = all.slice(i, i + perPacket);
    const p = new Uint8Array(chunk.length * LOG_RECORD_LEN);
    chunk.forEach((r, j) => p.set(r, j * LOG_RECORD_LEN));
    packets.push(p);
  }
  return packets;
}

/**
 * Collects a LOG_READ stream. feed() each notification; it returns true once the end marker arrived.
 * Records after the end marker in the same packet are ignored. Duplicate seq numbers are dropped.
 */
export class LogAssembler {
  constructor() { this.records = []; this.done = false; this.packets = 0; this._seen = new Set(); }
  feed(data) {
    if (this.done) return true;
    this.packets++;
    for (const r of decodeLogPacket(data)) {
      if (r.end) { this.done = true; break; }
      if (this._seen.has(r.seq)) continue;
      this._seen.add(r.seq);
      const { end, ...rec } = r;
      this.records.push(rec);
    }
    return this.done;
  }
}

// ---------------------------------------------------------------------------------------------
// PROFILES (7c0a0006): 30-byte records {u16 id, i32 nominal_nm, i32 tol_minus_nm, i32 tol_plus_nm, char name[16]}
// ---------------------------------------------------------------------------------------------

const enc = new TextEncoder();
// ignoreBOM: a name that happens to start with EF BB BF must not lose those bytes.
const dec = new TextDecoder('utf-8', { ignoreBOM: true });

/** UTF-8 encode, truncated on a character boundary to at most maxBytes. */
export function utf8Truncate(str, maxBytes) {
  let bytes = enc.encode(str);
  if (bytes.length <= maxBytes) return bytes;
  let cut = maxBytes;
  while (cut > 0 && (bytes[cut] & 0xc0) === 0x80) cut--; // don't split a multi-byte sequence
  return bytes.slice(0, cut);
}

export function decodeProfiles(data) {
  const dv = toDataView(data);
  if (dv.byteLength % PROFILE_RECORD_LEN !== 0) {
    throw new RangeError(`PROFILES must be a multiple of ${PROFILE_RECORD_LEN} bytes, got ${dv.byteLength}`);
  }
  const out = [];
  for (let off = 0; off < dv.byteLength; off += PROFILE_RECORD_LEN) {
    const nameBytes = new Uint8Array(dv.buffer, dv.byteOffset + off + 14, PROFILE_NAME_LEN);
    const nul = nameBytes.indexOf(0);
    out.push({
      id: dv.getUint16(off, true),
      nominalNm: dv.getInt32(off + 2, true),
      tolMinusNm: dv.getInt32(off + 6, true),
      tolPlusNm: dv.getInt32(off + 10, true),
      name: dec.decode(nul < 0 ? nameBytes : nameBytes.subarray(0, nul)),
    });
  }
  return out;
}

/**
 * Encode profiles. Names are UTF-8, truncated on a character boundary to at most 16 bytes, then
 * NUL-padded to 16 (a full 16-byte name has no NUL; the firmware's gatt_profile_unpack handles that).
 * At most PROFILES_MAX records per write.
 */
export function encodeProfiles(list) {
  if (list.length > PROFILES_MAX) throw new RangeError(`at most ${PROFILES_MAX} profile records per write, got ${list.length}`);
  const out = new Uint8Array(list.length * PROFILE_RECORD_LEN);
  const dv = new DataView(out.buffer);
  list.forEach((p, i) => {
    const off = i * PROFILE_RECORD_LEN;
    checkU('id', p.id, 16); checkI32('nominalNm', p.nominalNm);
    checkI32('tolMinusNm', p.tolMinusNm); checkI32('tolPlusNm', p.tolPlusNm);
    dv.setUint16(off, p.id, true);
    dv.setInt32(off + 2, p.nominalNm, true);
    dv.setInt32(off + 6, p.tolMinusNm, true);
    dv.setInt32(off + 10, p.tolPlusNm, true);
    out.set(utf8Truncate(p.name ?? '', PROFILE_NAME_LEN), off + 14);
  });
  return out;
}

/**
 * A delete record: empty name and nominal = tol_minus = tol_plus = 0 deletes that id
 * (firmware gatt_profile_is_delete()). A real profile therefore needs a non-empty name.
 */
export function profileDeleteRecord(id) {
  return { id, nominalNm: 0, tolMinusNm: 0, tolPlusNm: 0, name: '' };
}
export function isProfileDelete(p) {
  return (p.name ?? '') === '' && p.nominalNm === 0 && p.tolMinusNm === 0 && p.tolPlusNm === 0;
}

/**
 * The records to write so the caliper ends up holding exactly `list`, whether the firmware treats a
 * PROFILES write as "replace all" or as "upsert each record": the profiles themselves, plus a delete
 * record for every id the caliper had (`deviceIds`) that is no longer in the list.
 * Throws on duplicate ids, id 0, an empty name, or more than PROFILES_MAX records.
 */
export function profilesWriteRecords(list, deviceIds = []) {
  const ids = new Set();
  for (const p of list) {
    if (p.id === 0) throw new RangeError('profile id 0 is reserved for "no profile"');
    if (ids.has(p.id)) throw new RangeError(`duplicate profile id ${p.id}`);
    if (!(p.name ?? '').length) throw new RangeError(`profile ${p.id} needs a name (an empty name with zero values is a delete record)`);
    ids.add(p.id);
  }
  const dels = [...new Set(deviceIds)].filter((id) => id !== 0 && !ids.has(id)).map(profileDeleteRecord);
  const all = [...list, ...dels];
  if (all.length > PROFILES_MAX) {
    throw new RangeError(`${list.length} profiles + ${dels.length} deletions = ${all.length} records; the limit per write is ${PROFILES_MAX}`);
  }
  return all;
}

/**
 * Tolerance band of a profile, in nm. tol_minus_nm is treated as a magnitude below nominal
 * (abs() so that a firmware that stores it signed, e.g. -20000, gives the same band).
 */
export function toleranceBand(p) {
  return { lo: p.nominalNm - Math.abs(p.tolMinusNm), hi: p.nominalNm + Math.abs(p.tolPlusNm) };
}

/** 'pass' | 'fail' for a value against a profile (inclusive limits). */
export function evaluateTolerance(valueNm, p) {
  const { lo, hi } = toleranceBand(p);
  return valueNm >= lo && valueNm <= hi ? 'pass' : 'fail';
}

// ---------------------------------------------------------------------------------------------
// SETTINGS (7c0a0005): UTF-8 JSON, at most 240 bytes. wifi_pass is write-only.
// ---------------------------------------------------------------------------------------------

/** Decode a SETTINGS read. wifi_pass is dropped even if a firmware bug sends it. */
export function decodeSettings(data) {
  const text = dec.decode(toBytes(data)).replace(/\0+$/, '');
  if (!text.trim()) return {};
  const obj = JSON.parse(text);
  if (obj === null || typeof obj !== 'object' || Array.isArray(obj)) throw new TypeError('SETTINGS is not a JSON object');
  delete obj.wifi_pass;
  return obj;
}

/**
 * Encode a SETTINGS write. Unknown keys are dropped; wifi_pass is only sent when non-empty
 * (an empty field means "leave unchanged"). Throws if the JSON exceeds 240 bytes.
 */
export function encodeSettings(obj) {
  const clean = {};
  for (const k of SETTINGS_KEYS) {
    if (!(k in obj) || obj[k] === undefined || obj[k] === null) continue;
    if (k === 'wifi_pass' && obj[k] === '') continue;
    if (k === 'auto_off_s' || k === 'decimals') {
      const n = Number(obj[k]);
      if (!Number.isInteger(n)) throw new RangeError(`${k} must be an integer`);
      if (k === 'auto_off_s' && n !== 0 && (n < AUTO_OFF_MIN_S || n > AUTO_OFF_MAX_S)) {
        throw new RangeError(`auto_off_s must be 0 (never) or ${AUTO_OFF_MIN_S}..${AUTO_OFF_MAX_S}`);
      }
      if (k === 'decimals' && (n < DECIMALS_MIN || n > DECIMALS_MAX)) throw new RangeError(`decimals must be ${DECIMALS_MIN}..${DECIMALS_MAX}`);
      clean[k] = n;
    } else if (k === 'hid_suffix') {
      if (!HID_SUFFIXES.includes(obj[k])) throw new RangeError('hid_suffix must be "\\n", "\\t" or ""');
      clean[k] = obj[k];
    } else {
      const s = String(obj[k]);
      const n = enc.encode(s).length;
      const [min, max] = SETTINGS_STR_BYTES[k];
      if (n > max || (n && n < min)) throw new RangeError(min > 1 ? `${k} must be ${min}..${max} bytes` : `${k} must be at most ${max} bytes`);
      const prefixes = SETTINGS_URL_PREFIXES[k];
      if (prefixes && s && !prefixes.some((p) => s.startsWith(p))) throw new RangeError(`${k} must start with ${prefixes.join(', ')}`);
      clean[k] = s;
    }
  }
  const bytes = enc.encode(JSON.stringify(clean));
  if (bytes.length > SETTINGS_MAX_BYTES) {
    const e = new RangeError(`SETTINGS JSON is ${bytes.length} bytes; the limit is ${SETTINGS_MAX_BYTES}`);
    e.bytes = bytes.length;
    throw e;
  }
  return bytes;
}

// ---------------------------------------------------------------------------------------------
// Units, formatting, statistics, CSV
// ---------------------------------------------------------------------------------------------

export function nmToUnit(nm, unit) {
  return unit === UNIT.INCH ? nm / NM_PER_INCH : nm / NM_PER_MM;
}
export function unitToNm(v, unit) {
  return Math.round(unit === UNIT.INCH ? v * NM_PER_INCH : v * NM_PER_MM);
}
export function unitLabel(unit) {
  return unit === UNIT.INCH ? 'in' : 'mm';
}
/**
 * Decimal places for a unit. `decimals` (the SETTINGS key) is the mm figure; inch shows two more,
 * the same rule as the caliper's own display (firmware meas_fmt_for(): mm 2 -> inch 4, 0.01 mm ~ 0.0004 in).
 */
export function decimalsFor(unit, decimals = 2) {
  return unit === UNIT.INCH ? Math.min(decimals + 2, 6) : decimals;
}
export function formatReading(nm, unit, decimals = 2) {
  const v = nmToUnit(nm, unit);
  const d = decimalsFor(unit, decimals);
  const s = Math.abs(v).toFixed(d);
  const isZero = Number(s) === 0;
  return (v < 0 && !isZero ? '−' : '') + s; // U+2212 minus, like an LCD
}

/** count/min/max/mean/sd (sample, n-1) of numbers, using Welford's algorithm. */
export function computeStats(values) {
  let n = 0, mean = 0, m2 = 0, min = Infinity, max = -Infinity;
  for (const x of values) {
    n++;
    const d = x - mean;
    mean += d / n;
    m2 += d * (x - mean);
    if (x < min) min = x;
    if (x > max) max = x;
  }
  if (n === 0) return { count: 0, min: NaN, max: NaN, mean: NaN, sd: NaN, range: NaN };
  return { count: n, min, max, mean, sd: n > 1 ? Math.sqrt(m2 / (n - 1)) : 0, range: max - min };
}

function csvCell(v) {
  const s = String(v ?? '');
  return /[",\n\r]/.test(s) ? `"${s.replace(/"/g, '""')}"` : s;
}

/** CSV of log records. profiles: optional array, used to add a profile-name column. */
export function logToCsv(records, profiles = []) {
  const names = new Map(profiles.map((p) => [p.id, p.name]));
  const head = ['seq', 'unix_s', 'time_utc', 'value_nm', 'value', 'unit', 'hold', 'tol_pass', 'tol_fail', 'flags_hex', 'profile_id', 'profile_name'];
  const rows = records.map((r) => {
    const f = decodeFlags(r.flags);
    return [
      r.seq, r.unixS, r.unixS ? new Date(r.unixS * 1000).toISOString() : '', r.valueNm,
      nmToUnit(r.valueNm, r.unit).toFixed(r.unit === UNIT.INCH ? 5 : 4), unitLabel(r.unit),
      f.hold ? 1 : 0, f.tolPass ? 1 : 0, f.tolFail ? 1 : 0, '0x' + r.flags.toString(16).padStart(2, '0'),
      r.profileId, names.get(r.profileId) ?? '',
    ];
  });
  return [head, ...rows].map((row) => row.map(csvCell).join(',')).join('\r\n') + '\r\n';
}
