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
  const buf = new Uint8Array([0xaa, 0xbb, ...NM_25_4, ...NM_NEG_25_4, 0x00, 0x10, 0xcc]);
  const l = P.decodeLive(new DataView(buf.buffer, 2, 10));
  assert.equal(l.valueNm, 25_400_000);
  assert.equal(l.capNm, -25_400_000);
});

test('LIVE decode rejects a short packet', () => {
  assert.throws(() => P.decodeLive([1, 2, 3]), RangeError);
});

test('LIVE encode matches the hand-built bytes and round-trips', () => {
  const e = P.encodeLive({ valueNm: 25_400_000, capNm: null, unit: 0, flags: P.FLAG.HOLD | P.FLAG.CHARGING });
  assert.deepEqual(Array.from(e), [...NM_25_4, 0x00, 0x00, 0x00, 0x80, 0x00, 0x21]);
  const e2 = P.encodeLive({ valueNm: -25_400_000, capNm: 0x01020304, unit: 1, flags: P.FLAG.CAP_VALID });
  assert.deepEqual(Array.from(e2), [...NM_NEG_25_4, 0x04, 0x03, 0x02, 0x01, 0x01, 0x10]);
  assert.deepEqual(P.decodeLive(e2).capNm, 0x01020304);
  assert.throws(() => P.encodeLive({ valueNm: 2 ** 31 }), RangeError);
});

test('COMMAND encodings', () => {
  const c = P.encodeCommand;
  assert.deepEqual(Array.from(c.zero()), [0x01]);
  assert.deepEqual(Array.from(c.holdToggle()), [0x02]);
  assert.deepEqual(Array.from(c.recordNow()), [0x03]);
  assert.deepEqual(Array.from(c.setUnit(1)), [0x04, 0x01]);
  assert.deepEqual(Array.from(c.logRead(0)), [0x10, 0, 0, 0, 0]);
  assert.deepEqual(Array.from(c.logRead(0x12345678)), [0x10, 0x78, 0x56, 0x34, 0x12]);
  assert.deepEqual(Array.from(c.logClear()), [0x11]);
  assert.deepEqual(Array.from(c.selectProfile(0x0102)), [0x20, 0x02, 0x01]);
  // 1 700 000 000 = 0x6553F100
  assert.deepEqual(Array.from(c.setTime(1_700_000_000)), [0x30, 0x00, 0xf1, 0x53, 0x65]);
  assert.throws(() => c.selectProfile(70000), RangeError);
});

test('COMMAND decode (used by demo mode) round-trips and rejects bad lengths', () => {
  assert.deepEqual(P.decodeCommand([0x30, 0x00, 0xf1, 0x53, 0x65]), { op: 0x30, name: 'SET_TIME', unixS: 1_700_000_000 });
  assert.deepEqual(P.decodeCommand([0x10, 5, 0, 0, 0]), { op: 0x10, name: 'LOG_READ', fromSeq: 5 });
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
  assert.deepEqual(recs[0], { seq: 1, unixS: 1_700_000_000, valueNm: -25_400_000, unit: 0, flags: 3, profileId: 0x0102, end: false });
  assert.deepEqual(recs[1], { seq: 2, unixS: 1_700_000_001, valueNm: 25_400_000, unit: 1, flags: 4, profileId: 0, end: false });
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

test('LOG encode matches the hand-built bytes; encodeLogPackets splits and terminates', () => {
  const r1 = { seq: 1, unixS: 1_700_000_000, valueNm: -25_400_000, unit: 0, flags: 3, profileId: 0x0102 };
  assert.deepEqual(Array.from(P.encodeLogRecord(r1)), LOG_REC_1);
  assert.deepEqual(Array.from(P.encodeLogEnd()), LOG_END);
  const recs = Array.from({ length: 31 }, (_, i) => ({ ...r1, seq: i + 1 }));
  const packets = P.encodeLogPackets(recs, { perPacket: 15 });
  assert.deepEqual(packets.map((p) => p.length / 16), [15, 15, 2]);
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
  assert.equal(lines[0], 'seq,unix_s,time_utc,value_nm,value,unit,hold,tol_pass,tol_fail,flags_hex,profile_id,profile_name');
  assert.equal(lines[1], '1,1700000000,2023-11-14T22:13:20.000Z,-25400000,-25.4000,mm,1,1,0,0x03,7,"BORE, A"');
});
