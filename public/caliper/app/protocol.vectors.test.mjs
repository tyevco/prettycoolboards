// Second, independent set of test vectors for protocol.js (written in review, not by the app's author).
// The expected hex strings were produced by the firmware's own portable C codec
// (caliper/firmware/components/measure/gatt_codec.c and logrec.c, compiled with gcc on the host),
// so these tests check that the page and the firmware agree byte for byte, edge values included.
// Run from the repo root:  node --test public/caliper/app/protocol.vectors.test.mjs
import { test } from 'node:test';
import assert from 'node:assert/strict';
import * as P from './protocol.js';

const fromHex = (h) => Uint8Array.from(h.match(/../g).map((b) => parseInt(b, 16)));
const toHex = (u8) => Array.from(u8, (b) => b.toString(16).padStart(2, '0')).join('');

test('LIVE: value -1, cap INT32_MIN, inch, every flag bit (firmware gatt_live_pack)', () => {
  const fw = 'ffffffff00000080013f';
  const l = P.decodeLive(fromHex(fw));
  assert.equal(l.valueNm, -1);
  assert.equal(l.capRaw, -2147483648);
  assert.equal(l.capNm, null, 'INT32_MIN is invalid even with CAP_VALID set');
  assert.equal(l.unit, 1);
  assert.deepEqual(P.flagNames(l.flags), ['HOLD', 'TOL_PASS', 'TOL_FAIL', 'SENSOR_ERR', 'CAP_VALID', 'CHARGING']);
  assert.equal(toHex(P.encodeLive({ valueNm: -1, capNm: null, unit: 1, flags: 0x3f })), fw);
});

test('LIVE: INT32_MAX value, cap -25.4 mm, mm, TOL_PASS|CAP_VALID', () => {
  const fw = 'ffffff7f406d7cfe0012';
  const l = P.decodeLive(fromHex(fw));
  assert.equal(l.valueNm, 2147483647);
  assert.equal(l.capNm, -25_400_000);
  assert.equal(toHex(P.encodeLive({ valueNm: 2147483647, capNm: -25_400_000, unit: 0, flags: 0x12 })), fw);
});

test('LIVE: a legitimate cap value of INT32_MIN + 1 is kept', () => {
  const l = P.decodeLive(fromHex('00000000' + '01000080' + '0010'));
  assert.equal(l.capNm, -2147483647);
});

test('LOG: high-bit seq, unix_s, value -1, inch, profile 0xBEEF (firmware logrec_pack)', () => {
  const fw = 'd4c3b2a100f15365ffffffff0106efbe';
  const [r] = P.decodeLogPacket(fromHex(fw));
  assert.deepEqual(r, { seq: 0xa1b2c3d4, unixS: 1_700_000_000, valueNm: -1, unit: 1, flags: 6, profileId: 0xbeef, end: false });
  assert.equal(toHex(P.encodeLogRecord(r)), fw);
});

test('LOG: end marker is seq 0xFFFFFFFF with 12 zero bytes (firmware logrec_end_marker)', () => {
  const fw = 'ffffffff000000000000000000000000';
  assert.equal(toHex(P.encodeLogEnd()), fw);
  const a = new P.LogAssembler();
  // an empty log is just the end marker
  assert.equal(a.feed(fromHex(fw)), true);
  assert.equal(a.records.length, 0);
});

test('LOG: seq 0xFFFFFFFE is a real record, not the end marker; records after the marker are ignored', () => {
  const rec = (seq) => toHex(P.encodeLogRecord({ seq, valueNm: 5 }));
  const a = new P.LogAssembler();
  assert.equal(a.feed(fromHex(rec(0xfffffffe))), false);
  assert.equal(a.feed(fromHex(rec(3) + 'ffffffff000000000000000000000000' + rec(4))), true);
  assert.deepEqual(a.records.map((r) => r.seq), [0xfffffffe, 3]);
  assert.equal(a.feed(fromHex(rec(9))), true, 'feeding after done changes nothing');
  assert.equal(a.records.length, 2);
});

test('PROFILES: 16-byte name with no NUL, negative nominal (firmware gatt_profile_pack)', () => {
  const fw = '3412fbffffff204e0000000000004142434445464748494a4b4c4d4e4f50';
  const [p] = P.decodeProfiles(fromHex(fw));
  assert.deepEqual(p, { id: 0x1234, nominalNm: -5, tolMinusNm: 20000, tolPlusNm: 0, name: 'ABCDEFGHIJKLMNOP' });
  assert.equal(toHex(P.encodeProfiles([p])), fw);
});

test('PROFILES: UTF-8 name "µm Ø", NUL padded (firmware gatt_profile_pack)', () => {
  const fw = '3412fbffffff204e000000000000c2b56d20c39800000000000000000000';
  const [p] = P.decodeProfiles(fromHex(fw));
  assert.equal(p.name, 'µm Ø');
  assert.equal(toHex(P.encodeProfiles([p])), fw);
});

test('PROFILES: garbage after the NUL is ignored; a name cut mid-character never splits it', () => {
  const b = fromHex('0100' + '00000000'.repeat(3) + '414200ff' + 'ff'.repeat(12));
  assert.equal(P.decodeProfiles(b)[0].name, 'AB');
  // 15 ASCII + "€" (3 bytes) = 18 bytes -> only the 15 ASCII fit, then NUL
  const e = P.encodeProfiles([{ id: 1, nominalNm: 1, tolMinusNm: 0, tolPlusNm: 0, name: 'x'.repeat(15) + '€' }]);
  assert.equal(P.decodeProfiles(e)[0].name, 'x'.repeat(15));
  assert.equal(e[29], 0);
});

test('PROFILES: at most 16 records per write (CALIPER_PROFILES_MAX)', () => {
  const mk = (id) => ({ id, nominalNm: 1, tolMinusNm: 1, tolPlusNm: 1, name: 'p' + id });
  assert.equal(P.encodeProfiles(Array.from({ length: 16 }, (_, i) => mk(i + 1))).length, 480);
  assert.throws(() => P.encodeProfiles(Array.from({ length: 17 }, (_, i) => mk(i + 1))), RangeError);
});

test('PROFILES: write records add a delete record for each id that was removed', () => {
  const a = { id: 1, nominalNm: 10, tolMinusNm: 1, tolPlusNm: 1, name: 'a' };
  const recs = P.profilesWriteRecords([a], [1, 2, 3]);
  assert.deepEqual(recs.map((r) => r.id), [1, 2, 3]);
  assert.ok(P.isProfileDelete(recs[1]) && P.isProfileDelete(recs[2]) && !P.isProfileDelete(recs[0]));
  // a delete record on the wire: id, then 12 zero bytes and 16 zero name bytes
  assert.equal(toHex(P.encodeProfiles([recs[1]])), '0200' + '00'.repeat(28));
  assert.throws(() => P.profilesWriteRecords([{ ...a, name: '' }]), RangeError, 'empty names are refused');
  assert.throws(() => P.profilesWriteRecords([a, { ...a }]), RangeError, 'duplicate ids');
  assert.throws(() => P.profilesWriteRecords([{ ...a, id: 0 }]), RangeError, 'id 0');
});

test('COMMAND: u32 and u16 extremes (firmware gatt_cmd_build)', () => {
  assert.equal(toHex(P.encodeCommand.setTime(0xdeadbeef)), '30efbeadde');
  assert.equal(toHex(P.encodeCommand.selectProfile(0xffff)), '20ffff');
  assert.equal(toHex(P.encodeCommand.logRead(0xfffffffe)), '10feffffff');
  assert.equal(toHex(P.encodeCommand.setUnit(0)), '0400');
  assert.throws(() => P.encodeCommand.logRead(2 ** 32), RangeError);
  assert.throws(() => P.encodeCommand.setTime(-1), RangeError);
});

test('SETTINGS: limits mirrored from firmware settings.c', () => {
  assert.throws(() => P.encodeSettings({ decimals: 0 }), RangeError);
  assert.throws(() => P.encodeSettings({ decimals: 4 }), RangeError);
  assert.throws(() => P.encodeSettings({ auto_off_s: 29 }), RangeError);
  assert.throws(() => P.encodeSettings({ auto_off_s: 3601 }), RangeError);
  assert.equal(new TextDecoder().decode(P.encodeSettings({ auto_off_s: 0 })), '{"auto_off_s":0}');
  assert.throws(() => P.encodeSettings({ wifi_pass: '1234567' }), RangeError, 'WPA2 needs 8+');
  assert.throws(() => P.encodeSettings({ name: 'é'.repeat(11) }), RangeError, '22 bytes > 20');
  assert.throws(() => P.encodeSettings({ mqtt_url: 'http://x' }), RangeError);
  assert.throws(() => P.encodeSettings({ http_post_url: 'ftp://x' }), RangeError);
  // all fields at their own maximum is well over 240 bytes of JSON
  const big = { name: 'n'.repeat(20), wifi_ssid: 's'.repeat(32), wifi_pass: 'p'.repeat(64),
    mqtt_url: 'mqtt://' + 'm'.repeat(57), http_post_url: 'http://' + 'h'.repeat(57) };
  assert.throws(() => P.encodeSettings(big), (e) => e instanceof RangeError && e.bytes > 240);
  // non-ASCII is sent as raw UTF-8 and counted in bytes
  const b = P.encodeSettings({ name: 'Øl' });
  assert.equal(toHex(b), toHex(new TextEncoder().encode('{"name":"Øl"}')));
  assert.equal(b.length, 14);
});

test('display decimals follow the firmware rule: inch shows two more than mm (meas_fmt_for)', () => {
  assert.equal(P.decimalsFor(P.UNIT.MM, 2), 2);
  assert.equal(P.decimalsFor(P.UNIT.INCH, 1), 3);
  assert.equal(P.decimalsFor(P.UNIT.INCH, 2), 4);
  assert.equal(P.decimalsFor(P.UNIT.INCH, 3), 5);
  assert.equal(P.formatReading(-12_700, P.UNIT.INCH, 2), '−0.0005');
});
