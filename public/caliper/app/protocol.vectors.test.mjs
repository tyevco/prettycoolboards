// Second, independent set of test vectors for protocol.js (written in review, not by the app's author).
// The expected hex strings were produced by the firmware's own portable C codec
// (caliper/firmware/components/measure/gatt_codec.c and logrec.c, compiled with gcc on the host),
// so these tests check that the page and the firmware agree byte for byte, edge values included.
// Since the capture modes (2026-11-07) they come from caliper/firmware/test/host/gen_vectors.c, which is
// built with the host tests: run ./gen_vectors in the host build directory and paste its hex here.
// Run from the repo root:  node --test public/caliper/app/protocol.vectors.test.mjs
import { test } from 'node:test';
import assert from 'node:assert/strict';
import * as P from './protocol.js';

const fromHex = (h) => Uint8Array.from(h.match(/../g).map((b) => parseInt(b, 16)));
const toHex = (u8) => Array.from(u8, (b) => b.toString(16).padStart(2, '0')).join('');

// LIVE grew to 12 bytes (u16 active_profile_id), then to 20 (v3: the capture block). The 20-byte vectors
// below are the firmware's gatt_live_pack() output (CALIPER_LIVE_LEN = 20), regenerated from the C codec on
// 2026-11-07 (gcc 13.3, gen_vectors.c). Their first 12 bytes are the v2 vectors as before and their first 10
// what pre-extension firmware sent; both stay as decode tests: the page must accept 10 and 12 bytes.
test('LIVE: value -1, cap INT32_MIN, inch, every flag bit, profile 0xFFFF (firmware gatt_live_pack)', () => {
  const fw20 = 'ffffffff00000080013fffff0000000000000080';
  const fw = fw20.slice(0, 24);
  const fw10 = fw.slice(0, 20);
  assert.equal(toHex(P.encodeLive({ valueNm: -1, capNm: null, unit: 1, flags: 0x3f, activeProfileId: 0xffff })), fw20);
  assert.equal(P.decodeLive(fromHex(fw20)).capture.mode, P.CAPTURE.LIVE);
  assert.equal(P.decodeLive(fromHex(fw20)).capture.auxNm, null);
  assert.equal(P.decodeLive(fromHex(fw)).capture, null, 'v2 firmware: no capture block');
  const l = P.decodeLive(fromHex(fw));
  assert.equal(l.valueNm, -1);
  assert.equal(l.capRaw, -2147483648);
  assert.equal(l.capNm, null, 'INT32_MIN is invalid even with CAP_VALID set');
  assert.equal(l.unit, 1);
  assert.equal(l.activeProfileId, 0xffff);
  assert.deepEqual(P.flagNames(l.flags), ['HOLD', 'TOL_PASS', 'TOL_FAIL', 'SENSOR_ERR', 'CAP_VALID', 'CHARGING']);
  assert.equal(toHex(P.encodeLive({ valueNm: -1, capNm: null, unit: 1, flags: 0x3f, activeProfileId: 0xffff }, { version: 2 })), fw);
  // pre-extension firmware: the same fields, no profile id
  const old = P.decodeLive(fromHex(fw10));
  assert.equal(old.valueNm, -1);
  assert.equal(old.flags, 0x3f);
  assert.equal(old.activeProfileId, null);
  assert.equal(toHex(P.encodeLive({ valueNm: -1, capNm: null, unit: 1, flags: 0x3f }, { legacy: true })), fw10);
});

test('LIVE: INT32_MAX value, cap -25.4 mm, mm, TOL_PASS|CAP_VALID, profile 0x1234 (firmware gatt_live_pack)', () => {
  const fw20 = 'ffffff7f406d7cfe001234120000000000000080';
  const fw = fw20.slice(0, 24);
  const fw10 = fw.slice(0, 20);
  const l = P.decodeLive(fromHex(fw20));
  assert.equal(l.valueNm, 2147483647);
  assert.equal(l.capNm, -25_400_000);
  assert.equal(l.activeProfileId, 0x1234);
  assert.equal(toHex(P.encodeLive({ valueNm: 2147483647, capNm: -25_400_000, unit: 0, flags: 0x12, activeProfileId: 0x1234 })), fw20);
  assert.equal(P.decodeLive(fromHex(fw)).activeProfileId, 0x1234);
  assert.equal(P.decodeLive(fromHex(fw10)).capNm, -25_400_000);
});

test('LIVE: a legitimate cap value of INT32_MIN + 1 is kept; no profile is id 0 (firmware gatt_live_pack)', () => {
  const fw20 = '0000000001000080001000000000000000000080';
  const fw = fw20.slice(0, 24);
  const l = P.decodeLive(fromHex(fw20));
  assert.equal(l.capNm, -2147483647);
  assert.equal(l.activeProfileId, 0);
  assert.equal(toHex(P.encodeLive({ valueNm: 0, capNm: -2147483647, unit: 0, flags: 0x10, activeProfileId: 0 })), fw20);
  assert.equal(P.decodeLive(fromHex(fw)).capNm, -2147483647);
  assert.equal(P.decodeLive(fromHex(fw.slice(0, 20))).capNm, -2147483647);
});

test('LIVE v3: a frozen SWEEP MIN 20.012 mm, other extreme 20.041, n 214, auto, HOLD|TOL_PASS (firmware gatt_live_pack)', () => {
  const fw = 'e05b310100000080000307000213d60028cd3101';
  const l = P.decodeLive(fromHex(fw));
  assert.equal(l.valueNm, 20_012_000);
  assert.equal(l.hold, true);
  assert.equal(l.activeProfileId, 7);
  assert.deepEqual(l.capture, {
    mode: P.CAPTURE.SWEEP, modeName: 'sweep', sel: P.SWEEP.AUTO, selName: 'auto', state: P.CAPST.DONE, stateName: 'frozen',
    which: 'min', n: 214, auxNm: 20_041_000, otherNm: 20_041_000, rangeNm: 29_000, sdNm: null,
  });
  assert.equal(toHex(P.encodeLive({ valueNm: 20_012_000, unit: 0, flags: 0x03, activeProfileId: 7,
    capture: { mode: P.CAPTURE.SWEEP, sel: P.SWEEP.AUTO, state: P.CAPST.DONE, which: 'min', n: 214, auxNm: 20_041_000 } })), fw);
  // what a v2 reader of the same notification sees: the frozen extreme, held
  const old = P.decodeLive(fromHex(fw.slice(0, 24)));
  assert.equal(old.valueNm, 20_012_000);
  assert.equal(old.hold, true);
});

test('LIVE v3: a running SWEEP MAX (forced), inch, n saturated, the other extreme below zero (firmware gatt_live_pack)', () => {
  const fw = '64ceffff00000080010000002222ffffc063ffff';
  const l = P.decodeLive(fromHex(fw));
  assert.equal(l.valueNm, -12_700);
  assert.equal(l.hold, false, 'a running capture is not a hold');
  assert.equal(l.capture.state, P.CAPST.RUN);
  assert.equal(l.capture.selName, 'max');
  assert.equal(l.capture.which, 'max');
  assert.equal(l.capture.n, 65535);
  assert.equal(l.capture.otherNm, -40_000);
  assert.equal(l.capture.rangeNm, 27_300);
  assert.equal(toHex(P.encodeLive({ valueNm: -12_700, unit: 1, flags: 0,
    capture: { mode: P.CAPTURE.SWEEP, sel: P.SWEEP.MAX, state: P.CAPST.RUN, which: 'max', n: 65535, auxNm: -40_000 } })), fw);
});

test('LIVE v3: a frozen SETTLE median, sd 412 nm, n 32; a SWEEP aborted by a sensor error (firmware gatt_live_pack)', () => {
  const settle = '34797d010000008000010000110320009c010000';
  const s = P.decodeLive(fromHex(settle));
  assert.equal(s.valueNm, 25_000_244);
  assert.equal(s.capture.modeName, 'settle');
  assert.equal(s.capture.selName, 'min', 'the sweep selection is kept while settling');
  assert.equal(s.capture.which, null);
  assert.equal(s.capture.sdNm, 412);
  assert.equal(s.capture.n, 32);
  assert.equal(toHex(P.encodeLive({ valueNm: 25_000_244, flags: 0x01,
    capture: { mode: P.CAPTURE.SETTLE, sel: P.SWEEP.MIN, state: P.CAPST.DONE, n: 32, auxNm: 412 } })), settle);
  const abort = '0500000000000080000800000204000000000080';
  const a = P.decodeLive(fromHex(abort));
  assert.equal(a.sensorErr, true);
  assert.equal(a.capture.stateName, 'aborted');
  assert.equal(a.capture.auxNm, null);
  assert.equal(toHex(P.encodeLive({ valueNm: 5, flags: 0x08, capture: { mode: P.CAPTURE.SWEEP, state: P.CAPST.ABORT } })), abort);
});

test('LOG: high-bit seq, unix_s, value -1, inch, profile 0xBEEF (firmware logrec_pack)', () => {
  const fw = 'd4c3b2a100f15365ffffffff0106efbe';
  const [r] = P.decodeLogPacket(fromHex(fw));
  assert.deepEqual(r, { seq: 0xa1b2c3d4, unixS: 1_700_000_000, valueNm: -1, unit: 1, kind: 0, flags: 6, profileId: 0xbeef, end: false });
  assert.equal(toHex(P.encodeLogRecord(r)), fw);
});

test('LOG: byte 12 = unit | kind << 1; the plain LOG_READ masks it to the unit (firmware gatt_log_record_pack)', () => {
  const masked = 'd4c3b2a100f15365ffffffff0106efbe'; // a SWEEP-MAX inch record, plain read
  const ext = 'd4c3b2a100f15365ffffffff0706efbe'; // the same record, LOG_READ with opts bit 0
  const [m] = P.decodeLogPacket(fromHex(masked));
  const [e] = P.decodeLogPacket(fromHex(ext));
  assert.equal(m.unit, 1);
  assert.equal(m.kind, P.LOG_KIND.PLAIN, 'the plain read never carries the kind');
  assert.equal(e.unit, 1, 'an extended byte still decodes the unit: inch is never read as mm');
  assert.equal(e.kind, P.LOG_KIND.SWEEP_MAX);
  assert.equal(toHex(P.encodeLogRecord(e)), ext);
  assert.equal(toHex(P.encodeLogRecord(e, { ext: false })), masked);
  const min = P.decodeLogPacket(fromHex('0900000000000000e05b310104030700'))[0];
  assert.deepEqual([min.unit, min.kind, min.valueNm, min.flags, min.profileId], [0, P.LOG_KIND.SWEEP_MIN, 20_012_000, 3, 7]);
  const settle = P.decodeLogPacket(fromHex('0900000000000000e05b310103030700'))[0];
  assert.deepEqual([settle.unit, settle.kind], [1, P.LOG_KIND.SETTLE]);
  assert.equal(P.LOG_KIND_NAMES[min.kind], 'min');
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
  assert.equal(toHex(P.encodeCommand.logRead(0x12345678, { kind: true })), '107856341201');
  assert.equal(toHex(P.encodeCommand.setCapture(P.CAPTURE.SWEEP)), '050200');
  assert.equal(toHex(P.encodeCommand.setCapture(P.CAPTURE.SWEEP, P.SWEEP.MAX)), '050202');
  assert.equal(toHex(P.encodeCommand.setCapture(P.CAPTURE.SETTLE)), '050100');
  assert.equal(toHex(P.encodeCommand.setCapture(P.CAPTURE.LIVE)), '050000');
  assert.equal(toHex(P.encodeCommand.captureReset()), '06');
  // the firmware's parser refuses SET (reserved) and selection 3 with 0x80; the page cannot build the latter
  assert.throws(() => P.encodeCommand.setCapture(P.CAPTURE.SWEEP, 3), RangeError);

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
