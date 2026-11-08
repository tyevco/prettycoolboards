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
// LIVE grew from 10 to 12 bytes (u16 active_profile_id) and then to 20 (v3, the capture modes: SPEC §8,
// 2026-11-07). Readers accept >= 10 bytes (10 = firmware before v2: active profile unknown; 12 = before v3:
// no capture modes) and ignore anything past 20.
export const LIVE_LEN = 20;
export const LIVE_LEN_V2 = 12;
export const LIVE_LEN_MIN = 10;
export const LOG_RECORD_LEN = 16;
export const PROFILE_RECORD_LEN = 30;
export const PROFILE_NAME_LEN = 16;
export const PROFILES_MAX = 16; // CALIPER_PROFILES_MAX: 16 x 30 = 480 B, also the size of the caliper's table
export const PROFILE_ID_NONE = 0; // CALIPER_PROFILE_ID_NONE: "no profile" (never a stored id)
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
  REZERO: 1 << 6, // the zero was lost in a sleep/reset: press ZERO (firmware 2026-11-07)
});

// Capture modes (caliper_gatt.h CALIPER_CAPTURE_* / _SWEEP_* / _CAPST_*). SET (3) is reserved: the firmware
// refuses it (ATT 0x80) until multi-point sets exist.
export const CAPTURE = Object.freeze({ LIVE: 0, SETTLE: 1, SWEEP: 2, SET: 3 });
export const SWEEP = Object.freeze({ AUTO: 0, MIN: 1, MAX: 2 });
export const CAPST = Object.freeze({ IDLE: 0, WAIT: 1, RUN: 2, DONE: 3, ABORT: 4 });
export const CAPTURE_NAMES = Object.freeze(['live', 'settle', 'sweep', 'set']);
export const SWEEP_NAMES = Object.freeze(['auto', 'min', 'max']);
export const CAPST_NAMES = Object.freeze(['idle', 'armed', 'tracking', 'frozen', 'aborted']);
// LOG record byte 12 (unit_kind): bit 0 unit, bits 1..3 kind, bits 4..5 reserved for SET. Only the 6-byte
// LOG_READ (opts bit 0) returns the kind; the plain one sends the unit alone.
export const LOG_KIND = Object.freeze({ PLAIN: 0, SETTLE: 1, SWEEP_MIN: 2, SWEEP_MAX: 3 });
export const LOG_KIND_NAMES = Object.freeze(['', 'settle', 'min', 'max']);
export const LOG_OPT_KIND = 0x01;

export const OP = Object.freeze({
  ZERO: 0x01,
  HOLD_TOGGLE: 0x02,
  RECORD_NOW: 0x03,
  SET_UNIT: 0x04,
  SET_CAPTURE: 0x05,
  CAPTURE_RESET: 0x06,
  LOG_READ: 0x10,
  LOG_CLEAR: 0x11,
  SELECT_PROFILE: 0x20,
  SET_TIME: 0x30,
});

// ATT error codes the firmware returns on COMMAND / SETTINGS / PROFILES writes (caliper_gatt.h CALIPER_ATT_ERR_*).
export const ATT_ERR = Object.freeze({
  REQ_NOT_SUPPORTED: 0x06, // COMMAND: unknown opcode
  INVALID_LEN: 0x0d, // wrong length for the opcode; PROFILES not a multiple of 30; SETTINGS JSON too long
  INSUFFICIENT_AUTHEN: 0x05, // SETTINGS write on an unencrypted link (NimBLE's code): pair first
  INSUFFICIENT_ENC: 0x0f, // the same condition as other stacks report it
  APP_BAD_VALUE: 0x80, // a bad argument / value, profile id 0, profile table full, JSON syntax
});

export const SETTINGS_KEYS = Object.freeze([
  'name', 'wifi_ssid', 'wifi_pass', 'mqtt_url', 'http_post_url', 'auto_off_s', 'hid_suffix', 'decimals',
]);
export const HID_SUFFIXES = Object.freeze(['\n', '\t', '']);
// Value limits the firmware enforces in settings.c (it rejects the whole write on any bad value);
// mirrored here so the page can say what is wrong before writing. Now part of the contract:
// caliper_gatt.h CALIPER_SET_* and SPEC §8.
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
    rezero: !!(f & FLAG.REZERO),
  };
}

export function encodeFlags(o) {
  return (o.hold ? FLAG.HOLD : 0) | (o.tolPass ? FLAG.TOL_PASS : 0) | (o.tolFail ? FLAG.TOL_FAIL : 0) |
    (o.sensorErr ? FLAG.SENSOR_ERR : 0) | (o.capValid ? FLAG.CAP_VALID : 0) | (o.charging ? FLAG.CHARGING : 0) |
    (o.rezero ? FLAG.REZERO : 0);
}

export function flagNames(f) {
  return Object.entries(FLAG).filter(([, bit]) => f & bit).map(([n]) => n);
}

// ---------------------------------------------------------------------------------------------
// LIVE (7c0a0002): 20 bytes
//   {i32 value_nm, i32 cap_nm, u8 unit, u8 flags, u16 active_profile_id,                 (v2: 12 bytes)
//    u8 capture, u8 capture_state, u16 capture_n, i32 capture_aux_nm}                     (v3: 20 bytes)
//   capture: bits 0..3 mode (CAPTURE), bits 4..5 sweep selection (SWEEP)
//   capture_state: bits 0..2 state (CAPST), bits 4..5 which extreme value_nm is (0 n/a, 1 min, 2 max)
//   capture_aux_nm: SWEEP the other extreme, SETTLE the window's standard deviation, INT32_MIN n/a
//   value_nm is always the SHOWN value (the capture result when frozen, the running extreme in contact).
// ---------------------------------------------------------------------------------------------

/**
 * Decode a LIVE notification/read (10, 12 or 20 bytes; bytes past 20 are ignored).
 * capNm is null when cap_nm == INT32_MIN or the CAP_VALID flag is clear.
 * activeProfileId is null on a 10-byte packet (the caliper did not say), else 0 (none) or the profile id.
 * capture is null on a packet shorter than 20 bytes (firmware without capture modes), else
 * { mode, modeName, sel, selName, state, stateName, which: 'min'|'max'|null, n, auxNm, otherNm, rangeNm, sdNm }.
 */
export function decodeLive(data) {
  const dv = toDataView(data);
  if (dv.byteLength < LIVE_LEN_MIN) throw new RangeError(`LIVE needs ${LIVE_LEN_MIN}, ${LIVE_LEN_V2} or ${LIVE_LEN} bytes, got ${dv.byteLength}`);
  const valueNm = dv.getInt32(0, true);
  const capRaw = dv.getInt32(4, true);
  const unit = dv.getUint8(8);
  const flags = dv.getUint8(9);
  const activeProfileId = dv.byteLength >= LIVE_LEN_V2 ? dv.getUint16(10, true) : null;
  const f = decodeFlags(flags);
  const capNm = capRaw === INT32_MIN || !f.capValid ? null : capRaw;
  let capture = null;
  if (dv.byteLength >= LIVE_LEN) {
    const c = dv.getUint8(12), s = dv.getUint8(13);
    const mode = c & 0x0f, sel = (c >> 4) & 3, state = s & 7, w = (s >> 4) & 3;
    const n = dv.getUint16(14, true);
    const auxRaw = dv.getInt32(16, true);
    const auxNm = auxRaw === INT32_MIN ? null : auxRaw;
    const which = w === 1 ? 'min' : w === 2 ? 'max' : null;
    const sweep = mode === CAPTURE.SWEEP && which !== null && auxNm !== null;
    capture = {
      mode, modeName: CAPTURE_NAMES[mode] ?? `mode ${mode}`, sel, selName: SWEEP_NAMES[sel] ?? `sel ${sel}`,
      state, stateName: CAPST_NAMES[state] ?? `state ${state}`, which, n, auxNm,
      otherNm: sweep ? auxNm : null,
      rangeNm: sweep ? Math.abs(valueNm - auxNm) : null,
      sdNm: mode === CAPTURE.SETTLE && state === CAPST.DONE ? auxNm : null,
    };
  }
  return { valueNm, capNm, capRaw, unit, flags, activeProfileId, capture, ...f };
}

/**
 * Encode a LIVE packet (used by demo mode and tests). capNm null -> INT32_MIN, auxNm null -> INT32_MIN.
 * 20 bytes; { version: 2 } gives the 12-byte form of firmware without capture modes, { legacy: true }
 * (or version 1) the 10-byte form of firmware from before the profile id.
 * capture: { mode, sel, state, which: 'min'|'max'|null, n, auxNm } (default: LIVE mode, idle).
 */
export function encodeLive({ valueNm, capNm = null, unit = UNIT.MM, flags = 0, activeProfileId = PROFILE_ID_NONE, capture = null },
  { legacy = false, version = legacy ? 1 : 3 } = {}) {
  checkI32('valueNm', valueNm);
  const cap = capNm === null || capNm === undefined ? INT32_MIN : capNm;
  checkI32('capNm', cap);
  checkU('unit', unit, 8);
  checkU('flags', flags, 8);
  checkU('activeProfileId', activeProfileId, 16);
  const out = new Uint8Array(version === 1 ? LIVE_LEN_MIN : version === 2 ? LIVE_LEN_V2 : LIVE_LEN);
  const dv = new DataView(out.buffer);
  dv.setInt32(0, valueNm, true);
  dv.setInt32(4, cap, true);
  dv.setUint8(8, unit);
  dv.setUint8(9, flags);
  if (version >= 2) dv.setUint16(10, activeProfileId, true);
  if (version >= 3) {
    const c = { mode: CAPTURE.LIVE, sel: SWEEP.AUTO, state: CAPST.IDLE, which: null, n: 0, auxNm: null, ...(capture ?? {}) };
    checkU('capture mode', c.mode, 4); checkU('sweep sel', c.sel, 2); checkU('capture state', c.state, 3);
    const n = Math.min(Math.max(0, Math.round(c.n)), 0xffff);
    const aux = c.auxNm === null || c.auxNm === undefined ? INT32_MIN : c.auxNm;
    checkI32('auxNm', aux);
    dv.setUint8(12, c.mode | (c.sel << 4));
    dv.setUint8(13, c.state | ((c.which === 'min' ? 1 : c.which === 'max' ? 2 : 0) << 4));
    dv.setUint16(14, n, true);
    dv.setInt32(16, aux, true);
  }
  return out;
}

/** The label for what a reading is ("min", "max", "median") when it is a capture result, else ''. */
export function judgedLabel(capture) {
  if (!capture) return '';
  if (capture.mode === CAPTURE.SWEEP && capture.which && (capture.state === CAPST.RUN || capture.state === CAPST.DONE)) return capture.which;
  if (capture.mode === CAPTURE.SETTLE && capture.state === CAPST.DONE) return 'median';
  return '';
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
  // mode 0 live, 1 settle, 2 sweep (3 = SET is reserved: the firmware answers 0x80); sel 0 auto, 1 min, 2 max
  setCapture: (mode, sel = SWEEP.AUTO) => {
    checkU('capture mode', mode, 8); checkU('sweep sel', sel, 8);
    if (mode > CAPTURE.SET || sel > SWEEP.MAX) throw new RangeError(`capture mode 0..3 and sel 0..2, got ${mode}, ${sel}`);
    return cmd(OP.SET_CAPTURE, 2, (d) => { d.setUint8(0, mode); d.setUint8(1, sel); });
  },
  captureReset: () => cmd(OP.CAPTURE_RESET, 0),
  // { kind: true } = the 6-byte form: the records' byte 12 comes whole (unit + kind). Firmware without it
  // answers ATT 0x0D; send it only to a caliper whose LIVE is 20 bytes (the same release added both).
  logRead: (fromSeq = 0, { kind = false } = {}) => {
    checkU('fromSeq', fromSeq, 32);
    return kind
      ? cmd(OP.LOG_READ, 5, (d) => { d.setUint32(0, fromSeq, true); d.setUint8(4, LOG_OPT_KIND); })
      : cmd(OP.LOG_READ, 4, (d) => d.setUint32(0, fromSeq, true));
  },
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
  const need = { SET_UNIT: 2, SET_CAPTURE: 3, LOG_READ: 5, SELECT_PROFILE: 3, SET_TIME: 5 }[name] ?? 1;
  const ok = dv.byteLength === need || (name === 'LOG_READ' && dv.byteLength === 6);
  if (!ok) throw new RangeError(`${name} needs ${need} bytes, got ${dv.byteLength}`);
  const c = { op, name };
  if (name === 'SET_UNIT') c.unit = dv.getUint8(1);
  if (name === 'SET_CAPTURE') { c.mode = dv.getUint8(1); c.sel = dv.getUint8(2); }
  if (name === 'LOG_READ') { c.fromSeq = dv.getUint32(1, true); c.opts = dv.byteLength === 6 ? dv.getUint8(5) : 0; }
  if (name === 'SELECT_PROFILE') c.profileId = dv.getUint16(1, true);
  if (name === 'SET_TIME') c.unixS = dv.getUint32(1, true);
  return c;
}

// ---------------------------------------------------------------------------------------------
// LOG (7c0a0004): notifications of packed 16-byte records
//   {u32 seq, u32 unix_s, i32 value_nm, u8 unit_kind, u8 flags, u16 profile_id}
//   unit_kind: bit 0 unit, bits 1..3 kind (LOG_KIND), bits 4..5 reserved (SET). The plain LOG_READ sends
//   bit 0 only; the 6-byte LOG_READ sends the whole byte. Decoding always masks, so both read correctly.
//   The stream ends with a record whose seq == 0xFFFFFFFF, sent in a notification of its own.
//   The flags byte uses the LIVE bit meanings (FLAG).
// ---------------------------------------------------------------------------------------------

export function decodeLogRecord(dv, off = 0) {
  const seq = dv.getUint32(off, true);
  const flags = dv.getUint8(off + 13);
  const uk = dv.getUint8(off + 12);
  return {
    seq,
    unixS: dv.getUint32(off + 4, true),
    valueNm: dv.getInt32(off + 8, true),
    unit: uk & 1,
    kind: (uk >> 1) & 7,
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

/** kind is only sent by the 6-byte LOG_READ; { ext: false } encodes the plain read's byte 12 (unit only). */
export function encodeLogRecord({ seq, unixS = 0, valueNm = 0, unit = 0, flags = 0, profileId = 0, kind = 0 }, { ext = true } = {}) {
  checkU('seq', seq, 32); checkU('unixS', unixS, 32); checkI32('valueNm', valueNm);
  checkU('unit', unit, 1); checkU('flags', flags, 8); checkU('profileId', profileId, 16); checkU('kind', kind, 3);
  const out = new Uint8Array(LOG_RECORD_LEN);
  const dv = new DataView(out.buffer);
  dv.setUint32(0, seq, true);
  dv.setUint32(4, unixS, true);
  dv.setInt32(8, valueNm, true);
  dv.setUint8(12, unit | (ext ? kind << 1 : 0));
  dv.setUint8(13, flags);
  dv.setUint16(14, profileId, true);
  return out;
}

export function encodeLogEnd() {
  return encodeLogRecord({ seq: LOG_END_SEQ });
}

/**
 * Pack records into notifications of at most perPacket records each, then (optionally) the end
 * marker in a notification of its own, as the firmware sends it (SPEC §8).
 */
export function encodeLogPackets(records, { perPacket = 15, withEnd = true, ext = true } = {}) {
  const all = records.map((r) => encodeLogRecord(r, { ext }));
  const packets = [];
  for (let i = 0; i < all.length; i += perPacket) {
    const chunk = all.slice(i, i + perPacket);
    const p = new Uint8Array(chunk.length * LOG_RECORD_LEN);
    chunk.forEach((r, j) => p.set(r, j * LOG_RECORD_LEN));
    packets.push(p);
  }
  if (withEnd) packets.push(encodeLogEnd());
  return packets;
}

/**
 * Collects a LOG_READ stream. feed() each notification; it returns true once the end marker arrived.
 * The contract sends the marker in its own notification; a marker inside a packet is still honoured
 * and anything after it is ignored. Duplicate seq numbers are dropped.
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
 * The records to write so the caliper ends up holding exactly `list`. A PROFILES write is a per-record
 * upsert by id (SPEC §8), so this is the profiles themselves plus a delete record for every id the
 * caliper had (`deviceIds`) that is no longer in the list. The firmware applies a write all or nothing.
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
 * Tolerance band of a profile, in nm. Both tolerances are magnitudes (SPEC §8): the band is
 * nominal - |tol_minus| .. nominal + |tol_plus|; a sign on the wire is ignored, as the firmware does.
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
//   A write is a partial update: a key that is absent keeps its stored value (an absent wifi_pass
//   keeps the stored password; "" clears it). The write needs an encrypted (paired) link.
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
  const head = ['seq', 'unix_s', 'time_utc', 'value_nm', 'value', 'unit', 'hold', 'tol_pass', 'tol_fail', 'flags_hex', 'profile_id', 'profile_name', 'kind'];
  const rows = records.map((r) => {
    const f = decodeFlags(r.flags);
    return [
      r.seq, r.unixS, r.unixS ? new Date(r.unixS * 1000).toISOString() : '', r.valueNm,
      nmToUnit(r.valueNm, r.unit).toFixed(r.unit === UNIT.INCH ? 5 : 4), unitLabel(r.unit),
      f.hold ? 1 : 0, f.tolPass ? 1 : 0, f.tolFail ? 1 : 0, '0x' + r.flags.toString(16).padStart(2, '0'),
      r.profileId, names.get(r.profileId) ?? '', LOG_KIND_NAMES[r.kind ?? 0] ?? '',
    ];
  });

  return [head, ...rows].map((row) => row.map(csvCell).join(',')).join('\r\n') + '\r\n';
}
