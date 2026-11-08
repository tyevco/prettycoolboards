// Tests for protocol.js against hand-built byte arrays that follow the GATT contract.
// Run from the repo root:  node --test public/caliper/app/protocol.test.mjs
import { test } from 'node:test';
import assert from 'node:assert/strict';
import * as P from './protocol.js';

const ascii = (s) => Array.from(s, (c) => c.charCodeAt(0));
const pad = (arr, n) => [...arr, ...new Array(n - arr.length).fill(0)];

// 25.4 mm = 25 400 000 nm = 0x018392C0 ; -25.4 mm = 0xFE7C6D40
const NM_25_4 = [0xc0, 0x92, 0x83, 0x01];
const NM_NEG_25_4 = [0x40, 0x6d, 0x7c, 0xfe];

test('UUIDs share the base with the 2nd 16-bit group changed', () => {
  assert.equal(P.UUID.SERVICE, '7c0a0001-5e1f-4b8a-9c3d-2f6a1e0c7b11');
  assert.equal(P.UUID.LIVE, '7c0a0002-5e1f-4b8a-9c3d-2f6a1e0c7b11');
  assert.equal(P.UUID.COMMAND, '7c0a0003-5e1f-4b8a-9c3d-2f6a1e0c7b11');
  assert.equal(P.UUID.LOG, '7c0a0004-5e1f-4b8a-9c3d-2f6a1e0c7b11');
  assert.equal(P.UUID.SETTINGS, '7c0a0005-5e1f-4b8a-9c3d-2f6a1e0c7b11');
  assert.equal(P.UUID.PROFILES, '7c0a0006-5e1f-4b8a-9c3d-2f6a1e0c7b11');
});

test('LIVE decode: positive value, valid cap, inch, HOLD|TOL_PASS|CAP_VALID', () => {
  const bytes = Uint8Array.from([0x04, 0x03, 0x02, 0x01, 0xff, 0xff, 0xff, 0xff, 0x01, 0x13]);
  const l = P.decodeLive(bytes);
  assert.equal(l.valueNm, 0x01020304);
  assert.equal(l.capNm, -1);
  assert.equal(l.unit, P.UNIT.INCH);
  assert.equal(l.flags, 0x13);
  assert.equal(l.hold, true);
  assert.equal(l.tolPass, true);
  assert.equal(l.tolFail, false);
  assert.equal(l.sensorErr, false);
  assert.equal(l.capValid, true);
  assert.equal(l.charging, false);
});

test('LIVE decode: negative value, cap INT32_MIN is invalid, TOL_FAIL|SENSOR_ERR|CHARGING', () => {
  const bytes = [...NM_NEG_25_4, 0x00, 0x00, 0x00, 0x80, 0x00, 0x2c];
  const l = P.decodeLive(bytes);
  assert.equal(l.valueNm, -25_400_000);
  assert.equal(l.capRaw, P.INT32_MIN);
  assert.equal(l.capNm, null);
  assert.equal(l.unit, P.UNIT.MM);
  assert.deepEqual(P.flagNames(l.flags), ['TOL_FAIL', 'SENSOR_ERR', 'CHARGING']);
});

test('LIVE decode: cap value ignored when CAP_VALID is clear', () => {
  const l = P.decodeLive([...NM_25_4, ...NM_25_4, 0, 0x00]);
  assert.equal(l.capRaw, 25_400_000);
  assert.equal(l.capNm, null);
});

test('LIVE decode works on a DataView with an offset (as Web Bluetooth may hand over)', () => {
  const buf = new Uint8Array([0xaa, 0xbb, ...NM_25_4, ...NM_NEG_25_4, 0x00, 0x10, 0x03, 0x00, 0xcc]);
  const l = P.decodeLive(new DataView(buf.buffer, 2, 12));
  assert.equal(l.valueNm, 25_400_000);
  assert.equal(l.capNm, -25_400_000);
  assert.equal(l.activeProfileId, 3);
  assert.equal(P.decodeLive(new DataView(buf.buffer, 2, 10)).activeProfileId, null);
});

test('LIVE decode rejects a short packet', () => {
  assert.throws(() => P.decodeLive([1, 2, 3]), RangeError);
  assert.throws(() => P.decodeLive(new Uint8Array(9)), RangeError);
});

test('LIVE decode: 12-byte packet carries active_profile_id; 10-byte (pre-extension) gives null', () => {
  const v2 = P.decodeLive([...NM_25_4, 0x00, 0x00, 0x00, 0x80, 0x00, 0x02, 0x07, 0x01]);
  assert.equal(v2.valueNm, 25_400_000);
  assert.equal(v2.activeProfileId, 0x0107);
  assert.equal(v2.tolPass, true);
  assert.equal(P.decodeLive([...NM_25_4, 0x00, 0x00, 0x00, 0x80, 0x00, 0x00, 0x00, 0x00]).activeProfileId, 0);
  assert.equal(P.decodeLive([...NM_25_4, 0x00, 0x00, 0x00, 0x80, 0x00, 0x02]).activeProfileId, null);
  // 11 bytes: not enough for the id, treated as the 10-byte form; 14 bytes: the id, no capture block
  assert.equal(P.decodeLive([...NM_25_4, 0, 0, 0, 0x80, 0, 0, 0x05]).activeProfileId, null);
  const v14 = P.decodeLive([...NM_25_4, 0, 0, 0, 0x80, 0, 0, 0x05, 0x00, 0xee, 0xff]);
  assert.equal(v14.activeProfileId, 5);
  assert.equal(v14.capture, null, 'no capture fields below 20 bytes: the page hides the capture UI');
  // 19 bytes (one short of v3, e.g. a truncated notification): still no capture block, the v2 fields intact
  const v19 = P.decodeLive(P.encodeLive({ valueNm: 7, activeProfileId: 9, capture: { mode: P.CAPTURE.SWEEP, state: P.CAPST.DONE, which: 'min', n: 3, auxNm: 9 } }).slice(0, 19));
  assert.equal(v19.capture, null);
  assert.equal(v19.valueNm, 7);
  assert.equal(v19.activeProfileId, 9);
  assert.equal(v2.capture, null);
});

test('LIVE decode: v3 capture block (a frozen SWEEP MIN, the other extreme, n)', () => {
  // value 20.012 mm, HOLD|TOL_PASS, profile 7; capture = sweep|auto, state = done|min, n = 214, aux = 20.041 mm
  const b = [0xe0, 0x5b, 0x31, 0x01, 0x00, 0x00, 0x00, 0x80, 0x00, 0x03, 0x07, 0x00,
    0x02, 0x13, 0xd6, 0x00, 0x28, 0xcd, 0x31, 0x01];
  const l = P.decodeLive(b);
  assert.equal(l.valueNm, 20_012_000);
  assert.equal(l.hold, true, 'a frozen capture is a hold for old clients too');
  assert.equal(l.capture.mode, P.CAPTURE.SWEEP);
  assert.equal(l.capture.modeName, 'sweep');
  assert.equal(l.capture.selName, 'auto');
  assert.equal(l.capture.state, P.CAPST.DONE);
  assert.equal(l.capture.stateName, 'frozen');
  assert.equal(l.capture.which, 'min');
  assert.equal(l.capture.n, 214);
  assert.equal(l.capture.otherNm, 20_041_000);
  assert.equal(l.capture.rangeNm, 29_000);
  assert.equal(l.capture.sdNm, null);
  assert.equal(P.judgedLabel(l.capture), 'min');
  // 24 bytes: anything past 20 is ignored
  assert.equal(P.decodeLive([...b, 1, 2, 3, 4]).capture.n, 214);
  // SETTLE frozen: aux is the standard deviation
  const s = P.decodeLive(P.encodeLive({ valueNm: 25_000_000, flags: P.FLAG.HOLD,
    capture: { mode: P.CAPTURE.SETTLE, state: P.CAPST.DONE, n: 32, auxNm: 412 } }));
  assert.equal(s.capture.sdNm, 412);
  assert.equal(s.capture.otherNm, null);
  assert.equal(P.judgedLabel(s.capture), 'median');
  // waiting: no which, aux n/a
  const w = P.decodeLive(P.encodeLive({ valueNm: 5, capture: { mode: P.CAPTURE.SWEEP, sel: P.SWEEP.MAX, state: P.CAPST.WAIT } }));
  assert.equal(w.capture.which, null);
  assert.equal(w.capture.auxNm, null);
  assert.equal(w.capture.selName, 'max');
  assert.equal(P.judgedLabel(w.capture), '');
});

test('LIVE encode matches the hand-built bytes and round-trips', () => {
  const NO_CAPTURE = [0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x80]; // live mode, idle, n 0, aux INT32_MIN
  const e = P.encodeLive({ valueNm: 25_400_000, capNm: null, unit: 0, flags: P.FLAG.HOLD | P.FLAG.CHARGING });
  assert.deepEqual(Array.from(e), [...NM_25_4, 0x00, 0x00, 0x00, 0x80, 0x00, 0x21, 0x00, 0x00, ...NO_CAPTURE]);
  const v2 = P.encodeLive({ valueNm: 25_400_000, flags: P.FLAG.HOLD | P.FLAG.CHARGING }, { version: 2 });
  assert.deepEqual(Array.from(v2), [...NM_25_4, 0x00, 0x00, 0x00, 0x80, 0x00, 0x21, 0x00, 0x00]);
  const e2 = P.encodeLive({ valueNm: -25_400_000, capNm: 0x01020304, unit: 1, flags: P.FLAG.CAP_VALID, activeProfileId: 0x0102 });
  assert.deepEqual(Array.from(e2), [...NM_NEG_25_4, 0x04, 0x03, 0x02, 0x01, 0x01, 0x10, 0x02, 0x01, ...NO_CAPTURE]);
  const e3 = P.encodeLive({ valueNm: 0, capture: { mode: P.CAPTURE.SWEEP, sel: P.SWEEP.MAX, state: P.CAPST.RUN, which: 'max', n: 70000, auxNm: -1 } });
  assert.deepEqual(Array.from(e3).slice(12), [0x22, 0x22, 0xff, 0xff, 0xff, 0xff, 0xff, 0xff], 'n saturates at 65535');
  assert.throws(() => P.encodeLive({ valueNm: 0, capture: { mode: 16 } }), RangeError);
  assert.deepEqual(P.decodeLive(e2).capNm, 0x01020304);
  assert.equal(P.decodeLive(e2).activeProfileId, 0x0102);
  const legacy = P.encodeLive({ valueNm: 25_400_000, flags: P.FLAG.HOLD | P.FLAG.CHARGING }, { legacy: true });
  assert.deepEqual(Array.from(legacy), [...NM_25_4, 0x00, 0x00, 0x00, 0x80, 0x00, 0x21]);
  assert.throws(() => P.encodeLive({ valueNm: 2 ** 31 }), RangeError);
  assert.throws(() => P.encodeLive({ valueNm: 0, activeProfileId: 0x10000 }), RangeError);
});

test('COMMAND encodings', () => {
  const c = P.encodeCommand;
  assert.deepEqual(Array.from(c.zero()), [0x01]);
  assert.deepEqual(Array.from(c.holdToggle()), [0x02]);
  assert.deepEqual(Array.from(c.recordNow()), [0x03]);
  assert.deepEqual(Array.from(c.setUnit(1)), [0x04, 0x01]);
  assert.deepEqual(Array.from(c.setCapture(P.CAPTURE.SWEEP, P.SWEEP.MIN)), [0x05, 0x02, 0x01]);
  assert.deepEqual(Array.from(c.setCapture(P.CAPTURE.LIVE)), [0x05, 0x00, 0x00]);
  assert.throws(() => c.setCapture(4), RangeError);
  assert.throws(() => c.setCapture(2, 3), RangeError);
  assert.deepEqual(Array.from(c.captureReset()), [0x06]);
  assert.deepEqual(Array.from(c.logRead(0)), [0x10, 0, 0, 0, 0]);
  assert.deepEqual(Array.from(c.logRead(0x12345678)), [0x10, 0x78, 0x56, 0x34, 0x12]);
  assert.deepEqual(Array.from(c.logRead(9, { kind: true })), [0x10, 9, 0, 0, 0, 0x01]);
  assert.deepEqual(Array.from(c.logClear()), [0x11]);
  assert.deepEqual(Array.from(c.selectProfile(0x0102)), [0x20, 0x02, 0x01]);
  // 1 700 000 000 = 0x6553F100
  assert.deepEqual(Array.from(c.setTime(1_700_000_000)), [0x30, 0x00, 0xf1, 0x53, 0x65]);
  assert.throws(() => c.selectProfile(70000), RangeError);
});

test('COMMAND decode (used by demo mode) round-trips and rejects bad lengths', () => {
  assert.deepEqual(P.decodeCommand([0x30, 0x00, 0xf1, 0x53, 0x65]), { op: 0x30, name: 'SET_TIME', unixS: 1_700_000_000 });
  assert.deepEqual(P.decodeCommand([0x10, 5, 0, 0, 0]), { op: 0x10, name: 'LOG_READ', fromSeq: 5, opts: 0 });
  assert.deepEqual(P.decodeCommand([0x10, 5, 0, 0, 0, 1]), { op: 0x10, name: 'LOG_READ', fromSeq: 5, opts: 1 });
  assert.deepEqual(P.decodeCommand([0x05, 2, 2]), { op: 0x05, name: 'SET_CAPTURE', mode: 2, sel: 2 });
  assert.deepEqual(P.decodeCommand([0x06]), { op: 0x06, name: 'CAPTURE_RESET' });
  assert.throws(() => P.decodeCommand([0x05, 2]), RangeError);
  assert.deepEqual(P.decodeCommand([0x20, 7, 0]), { op: 0x20, name: 'SELECT_PROFILE', profileId: 7 });
  assert.throws(() => P.decodeCommand([0x04]), RangeError);
  assert.throws(() => P.decodeCommand([0x99]), RangeError);
});

// seq 1, unix 1 700 000 000, -25.4 mm, mm, HOLD|TOL_PASS, profile 0x0102
const LOG_REC_1 = [0x01, 0, 0, 0, 0x00, 0xf1, 0x53, 0x65, ...NM_NEG_25_4, 0x00, 0x03, 0x02, 0x01];
// seq 2, unix 1 700 000 001, 25.4 mm, inch, TOL_FAIL, profile 0
const LOG_REC_2 = [0x02, 0, 0, 0, 0x01, 0xf1, 0x53, 0x65, ...NM_25_4, 0x01, 0x04, 0x00, 0x00];
const LOG_END = [0xff, 0xff, 0xff, 0xff, ...new Array(12).fill(0)];

test('LOG packet decode: two records', () => {
  const recs = P.decodeLogPacket(Uint8Array.from([...LOG_REC_1, ...LOG_REC_2]));
  assert.equal(recs.length, 2);
  assert.deepEqual(recs[0], { seq: 1, unixS: 1_700_000_000, valueNm: -25_400_000, unit: 0, kind: 0, flags: 3, profileId: 0x0102, end: false });
  assert.deepEqual(recs[1], { seq: 2, unixS: 1_700_000_001, valueNm: 25_400_000, unit: 1, kind: 0, flags: 4, profileId: 0, end: false });
});

test('LOG packet decode rejects lengths that are not a multiple of 16', () => {
  assert.throws(() => P.decodeLogPacket(new Uint8Array(17)), RangeError);
  assert.throws(() => P.decodeLogPacket(new Uint8Array(0)), RangeError);
});

test('LogAssembler: stream across notifications ends at seq 0xFFFFFFFF', () => {
  const a = new P.LogAssembler();
  assert.equal(a.feed(Uint8Array.from(LOG_REC_1)), false);
  assert.equal(a.feed(Uint8Array.from([...LOG_REC_2, ...LOG_END])), true);
  assert.equal(a.records.length, 2);
  assert.equal(a.records[1].seq, 2);
  assert.equal('end' in a.records[0], false);
  // anything after the end is ignored
  assert.equal(a.feed(Uint8Array.from(LOG_REC_1)), true);
  assert.equal(a.records.length, 2);
});

test('LogAssembler: empty log is just the end marker; duplicates are dropped', () => {
  const a = new P.LogAssembler();
  assert.equal(a.feed(Uint8Array.from(LOG_END)), true);
  assert.equal(a.records.length, 0);
  const b = new P.LogAssembler();
  b.feed(Uint8Array.from([...LOG_REC_1, ...LOG_REC_1]));
  assert.equal(b.records.length, 1);
});

test('LOG encode matches the hand-built bytes; encodeLogPackets splits, then the end marker alone', () => {
  const r1 = { seq: 1, unixS: 1_700_000_000, valueNm: -25_400_000, unit: 0, flags: 3, profileId: 0x0102 };
  assert.deepEqual(Array.from(P.encodeLogRecord(r1)), LOG_REC_1);
  assert.deepEqual(Array.from(P.encodeLogEnd()), LOG_END);
  const recs = Array.from({ length: 31 }, (_, i) => ({ ...r1, seq: i + 1 }));
  const packets = P.encodeLogPackets(recs, { perPacket: 15 });
  assert.deepEqual(packets.map((p) => p.length / 16), [15, 15, 1, 1]);
  assert.deepEqual(Array.from(packets.at(-1)), LOG_END, 'the end marker is a notification of its own (SPEC §8)');
  assert.deepEqual(P.encodeLogPackets([]).map((p) => Array.from(p)), [LOG_END]);
  const a = new P.LogAssembler();
  packets.forEach((p) => a.feed(p));
  assert.equal(a.done, true);
  assert.equal(a.records.length, 31);
});

// id 7, nominal 25.4 mm, tol -0.020 / +0.050 mm, name "BORE-A"
const PROF_1 = [0x07, 0x00, ...NM_25_4, 0x20, 0x4e, 0, 0, 0x50, 0xc3, 0, 0, ...pad(ascii('BORE-A'), 16)];
// id 0x0201, nominal -1 nm, tol 0 / 0, name exactly 16 chars with no NUL
const PROF_2 = [0x01, 0x02, 0xff, 0xff, 0xff, 0xff, 0, 0, 0, 0, 0, 0, 0, 0, ...ascii('ABCDEFGHIJKLMNOP')];

test('PROFILES decode: two 30-byte records (NUL-padded and full-length names)', () => {
  assert.equal(PROF_1.length, 30);
  const ps = P.decodeProfiles(Uint8Array.from([...PROF_1, ...PROF_2]));
  assert.deepEqual(ps, [
    { id: 7, nominalNm: 25_400_000, tolMinusNm: 20_000, tolPlusNm: 50_000, name: 'BORE-A' },
    { id: 0x0201, nominalNm: -1, tolMinusNm: 0, tolPlusNm: 0, name: 'ABCDEFGHIJKLMNOP' },
  ]);
  assert.deepEqual(P.decodeProfiles(new Uint8Array(0)), []);
  assert.throws(() => P.decodeProfiles(new Uint8Array(31)), RangeError);
});

test('PROFILES encode matches the hand-built bytes; long names truncate to 16 bytes (no NUL)', () => {
  const e = P.encodeProfiles([{ id: 7, nominalNm: 25_400_000, tolMinusNm: 20_000, tolPlusNm: 50_000, name: 'BORE-A' }]);
  assert.deepEqual(Array.from(e), PROF_1);
  const long = P.encodeProfiles([{ id: 1, nominalNm: 0, tolMinusNm: 0, tolPlusNm: 0, name: 'ABCDEFGHIJKLMNOPQRS' }]);
  assert.equal(long.length, 30);
  assert.equal(long[29], 0x50); // 'P': a full 16-byte name, as the firmware's gatt_profile_pack() writes it
  assert.equal(P.decodeProfiles(long)[0].name, 'ABCDEFGHIJKLMNOP');
  // multi-byte UTF-8 is not split: "a" + 8 x "ø" (2 bytes each) = 17 bytes -> "a" + 7 "ø" = 15 bytes + NUL
  const utf = P.encodeProfiles([{ id: 1, nominalNm: 0, tolMinusNm: 0, tolPlusNm: 0, name: 'aøøøøøøøø' }]);
  assert.equal(utf[29], 0);
  assert.equal(P.decodeProfiles(utf)[0].name, 'aøøøøøøø');
});

test('tolerance band and evaluation (inclusive, tol_minus taken as a magnitude)', () => {
  const p = { id: 7, nominalNm: 25_400_000, tolMinusNm: 20_000, tolPlusNm: 50_000, name: 'x' };
  assert.deepEqual(P.toleranceBand(p), { lo: 25_380_000, hi: 25_450_000 });
  assert.equal(P.evaluateTolerance(25_380_000, p), 'pass');
  assert.equal(P.evaluateTolerance(25_450_001, p), 'fail');
  assert.deepEqual(P.toleranceBand({ ...p, tolMinusNm: -20_000 }), { lo: 25_380_000, hi: 25_450_000 });
});

test('SETTINGS: encode drops empty wifi_pass and unknown keys, enforces 240 bytes; decode drops wifi_pass', () => {
  const bytes = P.encodeSettings({ name: 'PCC-1', wifi_pass: '', hid_suffix: '\t', decimals: '3', junk: 1 });
  const text = new TextDecoder().decode(bytes);
  assert.equal(text, '{"name":"PCC-1","hid_suffix":"\\t","decimals":3}');
  const withPass = new TextDecoder().decode(P.encodeSettings({ wifi_pass: 'hunter22' }));
  assert.equal(withPass, '{"wifi_pass":"hunter22"}');
  assert.throws(() => P.encodeSettings({ mqtt_url: 'x'.repeat(240) }), RangeError);
  assert.throws(() => P.encodeSettings({ hid_suffix: ' ' }), RangeError);
  const d = P.decodeSettings(new TextEncoder().encode('{"name":"a","wifi_pass":"leak","decimals":2}\0\0'));
  assert.deepEqual(d, { name: 'a', decimals: 2 });
  assert.deepEqual(P.decodeSettings(new Uint8Array(0)), {});
});

test('formatting and units', () => {
  assert.equal(P.formatReading(25_400_000, P.UNIT.MM, 2), '25.40');
  assert.equal(P.formatReading(25_400_000, P.UNIT.INCH, 2), '1.0000');
  assert.equal(P.formatReading(-1_234_567, P.UNIT.MM, 3), '−1.235');
  assert.equal(P.formatReading(-1_000, P.UNIT.MM, 2), '0.00'); // no "-0.00"
  assert.equal(P.unitToNm(1, P.UNIT.INCH), 25_400_000);
});

test('stats: count/min/max/mean/sample sd', () => {
  const s = P.computeStats([2, 4, 4, 4, 5, 5, 7, 9]);
  assert.equal(s.count, 8);
  assert.equal(s.min, 2);
  assert.equal(s.max, 9);
  assert.equal(s.mean, 5);
  assert.ok(Math.abs(s.sd - Math.sqrt(32 / 7)) < 1e-12);
  assert.equal(P.computeStats([]).count, 0);
  assert.equal(P.computeStats([3]).sd, 0);
});

test('CSV export', () => {
  const csv = P.logToCsv(
    [{ seq: 1, unixS: 1_700_000_000, valueNm: -25_400_000, unit: 0, flags: 3, profileId: 7 }],
    [{ id: 7, name: 'BORE, A' }],
  );
  const lines = csv.trim().split('\r\n');
  assert.equal(lines[0], 'seq,unix_s,time_utc,value_nm,value,unit,hold,tol_pass,tol_fail,flags_hex,profile_id,profile_name,kind');
  assert.equal(lines[1], '1,1700000000,2023-11-14T22:13:20.000Z,-25400000,-25.4000,mm,1,1,0,0x03,7,"BORE, A",');
  const k = P.logToCsv([{ seq: 2, unixS: 0, valueNm: 1, unit: 1, flags: 1, profileId: 0, kind: P.LOG_KIND.SWEEP_MAX }]);
  assert.match(k.trim().split('\r\n')[1], /,max$/);

});
