# Companion app

**Status:** written and tested against its own demo simulator and unit tests only. No caliper
firmware or hardware exists yet, so the page has **never talked to a real caliper**. Treat
everything below as the design of record for the app side of the BLE contract.

**Live page: <https://tyevco.github.io/prettycoolboards/caliper/app/>**
(add `?demo` to the URL to start the simulator straight away).

The companion app is one static web page that talks to the caliper over **Web Bluetooth**. There
is no install, no build step and no server: the page is plain HTML, CSS and two ES modules, with
no third-party libraries and no CDN, so it works offline once loaded. VitePress copies it verbatim
from [`public/caliper/app/`](../../public/caliper/app/) into the docs site.

| File | Contents |
|---|---|
| [`index.html`](https://github.com/tyevco/prettycoolboards/blob/main/public/caliper/app/index.html) | Layout and styles (light/dark from `prefers-color-scheme`) |
| [`app.js`](../../public/caliper/app/app.js) | UI, Web Bluetooth transport, demo simulator, chart, Web Serial console |
| [`protocol.js`](../../public/caliper/app/protocol.js) | The GATT contract as pure functions: encode/decode of every characteristic, units, stats, CSV |
| [`protocol.test.mjs`](../../public/caliper/app/protocol.test.mjs) | `node --test` suite against hand-built byte arrays |

## What it does

- **Live reading.** Big caliper-style digits in the unit the caliper is set to (mm or inch),
  status chips for HOLD, PASS, FAIL, CAP (capacitive reading valid), CHG (charging) and SENSOR ERR.
  The display gets a green or red border on PASS/FAIL, and the text chips carry the same
  information for people who can't tell the colours apart.
- **Magnetic vs capacitive.** The AS5311 reading, the experimental capacitive reading and their
  difference (cap − mag, in µm or 10⁻⁴ in) side by side. Comparing the two is the point of
  the capacitive scale (see [architecture](architecture.md)), so the difference is always on
  screen while the CAP_VALID flag is set.
- **Buttons** that send COMMAND opcodes: Zero, Hold, Record, mm/in, Set time. The clock is set
  automatically on every connect (SET_TIME with the phone's/PC's Unix time), because the caliper
  has no RTC battery. Keyboard shortcuts: <kbd>Z</kbd>, <kbd>H</kbd>, <kbd>R</kbd>, <kbd>U</kbd>.
- **Live chart** of the last 30 s, drawn on a `<canvas>` by hand (no chart library): magnetic as
  a solid line, capacitive dashed, and the active profile's tolerance band shaded with the nominal
  as a dashed line. The y-axis autoscales; it includes the band when the readings are within
  20 band-widths of it, otherwise a "band above/below" hint is shown.
- **Session stats**: count, min, max, mean, sample σ (n−1) and range of the readings recorded
  from this page (Record or "Add current"), computed in the browser with Welford's algorithm.
  Readings recorded with the caliper's own button do not reach the page; download the log for those.
- **Log download.** LOG_READ from a chosen sequence number (0 = everything), reassembly of the
  16-byte records until the end marker, a table (newest first) and CSV export. If no
  notification arrives for 5 s before the end marker, the download stops and keeps what it has.
  "Clear log on caliper" sends LOG_CLEAR after a confirmation dialog.
- **Tolerance profiles editor**: read, add, edit, delete and write the PROFILES records, and
  select the active one (SELECT_PROFILE; "No profile" selects id 0). Values are edited in the
  current display unit and stored in nm.
- **Settings editor** for the SETTINGS JSON with a live byte counter against the 240-byte limit.
  The Wi-Fi password field is write-only: it is never filled from the caliper, and it is left out
  of the JSON when blank, which means "keep the stored password".
- **Device panel**: name, Device Information strings, battery level (notify if the
  characteristic supports it, otherwise read once on connect).
- **USB console (optional)**: a Web Serial terminal for the firmware's USB CDC console at
  115200 baud, filtered to Espressif's USB vendor ID 0x303A.

## Browser support

Web Bluetooth is a Chromium feature. Checked against the browser vendors' published status, not
tested on every platform listed:

| Browser | Connect over BLE | Demo mode | USB console |
|---|---|---|---|
| Chrome / Edge, Windows 10+, macOS, ChromeOS | yes | yes | yes |
| Chrome / Edge, Linux | listed as supported but less mature (BlueZ); some versions need `chrome://flags/#enable-experimental-web-platform-features`. Unverified | yes | yes |
| Chrome, Android 6+ | yes | yes | no (no Web Serial on Android) |
| Firefox (all platforms) | **no**, Mozilla does not implement Web Bluetooth | yes | no |
| Safari, macOS and iOS; every iOS browser (all use WebKit) | **no** | yes | no |
| Bluefy (third-party iOS browser) | probably, untested | yes | no |

When Web Bluetooth is missing the page says so in a banner, disables Connect and offers demo mode.
Web Bluetooth also needs a secure context: `https://` (the docs site) or `http://localhost`.
Opening `index.html` from disk (`file://`) does not work, because browsers block ES-module
imports from `file://`.

What was actually run: the page in desktop Chrome on Windows 11 in demo mode, at desktop width and
in a 360 px-wide frame (no horizontal scroll), plus the `node --test` suite. The BLE transport has
not run against any device.

A review pass afterwards re-ran it in desktop Chrome (Windows 11) in demo mode, served by
`vitepress preview`: deleting a profile and writing reported "2 profiles written, 1 deleted" and
a read-back returned 2; mm/in switched the reading to 4 inch decimals; an out-of-range `decimals`
was refused before writing; the log download returned 42 records in 3 notifications; the page
loaded only `app.js` and `protocol.js` (no other network requests); no console errors. In 320,
360 and 412 px frames there was no horizontal scroll. At 320 px the worst-case reading
"−150.000 mm" was clipped with the original font size, so the digits were made smaller on narrow
screens (`clamp(34px, 11.5vw, 112px)`); after that it fits. Dark mode was checked only by reading
the CSS (every colour token is redefined under `prefers-color-scheme: dark`), not on screen.

## Demo mode

Click **Demo mode** (or open the page with `?demo`). A simulated caliper runs inside the page and
speaks the same bytes as the firmware: it produces LIVE packets with `encodeLive()`, decodes every
COMMAND with `decodeCommand()`, streams the log with `encodeLogPackets()` (15 records per
notification, then the end marker in a notification of its own, as the firmware sends it) and serves PROFILES and SETTINGS as bytes. So demo mode
exercises the same decode paths as a real connection; only the Web Bluetooth calls differ.

The simulator:

- moves the jaws between "closed", a 1 in gauge block (25.40 mm), an M6 shank (≈ 5.98 mm), a
  12 mm bore and random positions, with a smoothstep move at about 40 mm/s and a 1.5–5 s dwell;
- quantizes the magnetic reading to the rev A internal step, 488.28125 nm (2 mm / 4096: the firmware interpolates
  the 1.953 µm quadrature count with the 12-bit SSI position, SPEC §4.1), with 0.25 µm of noise;
- makes the capacitive reading the magnetic one plus a 4 µm sinusoidal error at the 5.08 mm
  scale pitch, a 2.5 µm offset and 1.5 µm of noise, and marks it invalid while the jaw moves faster
  than 60 mm/s and on 2 % of samples at random. These are illustrative numbers, not predictions;
  the real error budget is in [simulation](simulation.md) and has to be measured at [bring-up](bringup.md);
- starts with three profiles and 42 past log records, reports the active profile in the 12-byte LIVE, and lets the
  battery run down and charge.

## BLE GATT contract

The firmware defines this once in `caliper/firmware/main/proto/caliper_gatt.h` (see
[firmware](firmware.md)); the app mirrors it in `protocol.js`. All integers are little-endian.

Custom service `7c0a0001-5e1f-4b8a-9c3d-2f6a1e0c7b11`. The characteristics share the base with
the second 16-bit group changed:

| UUID | Name | Properties | Payload |
|---|---|---|---|
| `7c0a0002-…` | LIVE | read, notify | 12 B: `i32 value_nm` (magnetic, zeroed), `i32 cap_nm` (capacitive, zeroed; `INT32_MIN` if invalid), `u8 unit` (0 mm, 1 inch), `u8 flags`, `u16 active_profile_id` (0 = none). Firmware from before the extension sends the first 10 B only; the page accepts both |
| `7c0a0003-…` | COMMAND | write | `u8 opcode` + payload (below) |
| `7c0a0004-…` | LOG | notify | after LOG_READ: notifications of 1…N packed 16-byte records `{u32 seq, u32 unix_s, i32 value_nm, u8 unit, u8 flags, u16 profile_id}`; the stream ends with a record whose `seq = 0xFFFFFFFF`, sent in a notification of its own |
| `7c0a0005-…` | SETTINGS | read, write (encrypted link) | UTF-8 JSON ≤ 240 B, partial update: `name`, `wifi_ssid`, `wifi_pass` (write-only), `mqtt_url`, `http_post_url`, `auto_off_s`, `hid_suffix` (`"\n"`, `"\t"` or `""`), `decimals` |
| `7c0a0006-…` | PROFILES | read, write | one or more 30-byte records `{u16 id, i32 nominal_nm, i32 tol_minus_nm, i32 tol_plus_nm, char name[16]}`, name NUL-padded; a write is a per-record upsert, all or nothing |

Flags: bit 0 HOLD, bit 1 TOL_PASS, bit 2 TOL_FAIL, bit 3 SENSOR_ERR, bit 4 CAP_VALID, bit 5 CHARGING.
The app reads the log record's `flags` byte with the same bit meanings.

| Opcode | Command | Payload |
|---|---|---|
| `0x01` | ZERO | none |
| `0x02` | HOLD_TOGGLE | none |
| `0x03` | RECORD_NOW | none |
| `0x04` | SET_UNIT | `u8` unit |
| `0x10` | LOG_READ | `u32` from_seq |
| `0x11` | LOG_CLEAR | none |
| `0x20` | SELECT_PROFILE | `u16` id |
| `0x30` | SET_TIME | `u32` Unix seconds |

Standard services alongside: Battery (0x180F), Device Information (0x180A) and HID over GATT
(0x1812, a keyboard that types the reading plus `hid_suffix` when SEND is pressed on the caliper).
The page asks for Battery and Device Information. It cannot use HID, because 0x1812 is on the
Web Bluetooth blocklist; the operating system talks to the HID keyboard directly.

COMMAND, PROFILES and SETTINGS writes fail with ATT error **0x06** (unknown opcode), **0x0D** (wrong length; PROFILES
not a multiple of 30 or over 16 records; SETTINGS over 240 B) or **0x80** (bad value). An unpaired SETTINGS write is
refused by the stack (0x05 on NimBLE, 0x0F on some stacks) and the browser pairs. `protocol.js` exports these as
`ATT_ERR`. The advertisement or scan response carries the 128-bit service UUID (rev A: the scan response).

### How the app reads the contract

These used to be the app's guesses; the contract reconciliation (SPEC §8, decision D6) made each one part of the
contract, so `protocol.js`, the firmware and `caliper_gatt.h` now agree on them:

- **Units.** `value_nm` is always nanometres; `unit` only says how to display it.
  `decimals` (1…3) is the number of mm decimals; inch shows two more (2 → 0.01 mm / 0.0001 in),
  the same rule as the firmware's `meas_fmt_for()`. The caliper's own display also rounds inch to a
  0.0005 in step (`meas_step_nm()`); the page shows the unrounded value to 0.0001 in.
- **Tolerance band** = `nominal − |tol_minus| … nominal + |tol_plus|`, inclusive. Both tolerances
  are magnitudes: the page writes them positive and ignores a sign when reading.
- **Profile names** are UTF-8, at most 16 bytes, cut on a character boundary and NUL-padded; a
  full 16-byte name has no NUL, which the firmware's `gatt_profile_unpack()` handles. Profile id 0
  means "no profile" (never stored; a record with id 0 is refused). The caliper stores at most 16
  profiles, which is also the most records per write (`CALIPER_PROFILES_MAX`, 16 × 30 = 480 B).
- **Deleting a profile.** A record with an empty name and nominal = tol− = tol+ = 0 deletes that id
  (`gatt_profile_is_delete()`). A PROFILES write is a per-record upsert, so the page sends the full
  list **plus** a delete record for every id it read from the caliper that is no longer in the list.
  The firmware applies the write all or nothing (a table that would exceed 16 is refused). Because
  of this the page insists on reading the profiles before it writes, and refuses a profile with an
  empty name.
- **SETTINGS write** is a partial update: a key that is absent keeps its stored value. The page
  sends every key in the form (an empty string clears that field), except `wifi_pass`, which is
  only sent when typed (absent = keep the stored password). Unknown keys are dropped. The page
  checks the contract's limits before writing (the firmware rejects the whole write on any bad
  value): `name` ≤ 20 B, `wifi_ssid` ≤ 32 B, `wifi_pass` 8…64 B, the URLs ≤ 64 B with an
  `mqtt://`/`mqtts://`/`ws://`/`wss://` or `http://`/`https://` prefix, `auto_off_s` 0 or
  30…3600, `decimals` 1…3. They are `CALIPER_SET_*` in `caliper_gatt.h` and SPEC §8 now.
- **LOG**: the record flags use the LIVE bit meanings. A notification whose length is not a
  multiple of 16 is rejected; duplicate `seq` values are dropped. The end marker comes in its own
  notification; one inside a packet would still end the stream, and anything after it is ignored.
- **The active profile** comes in the 12-byte LIVE (`active_profile_id`), and the page follows it, so
  a profile chosen on the caliper shows up. From a 10-byte LIVE (firmware from before the extension)
  the page keeps the profile it last selected (remembered in the browser), which may be stale.
- **Advertising**: the page filters the device chooser on the custom service UUID, which the
  firmware puts in the scan response.

## Tests

```sh
node --test public/caliper/app/protocol.test.mjs public/caliper/app/protocol.vectors.test.mjs
```

(Give the file paths; `node --test public/caliper/app/` with a folder does not find them on Node 24.)

`protocol.test.mjs`: 22 tests, run with Node 24.11 on Windows: all pass (36 with the vectors file, re-run
after the 12-byte LIVE change). They check the UUIDs; LIVE decode
(positive/negative values, `INT32_MIN` and CAP_VALID handling, a `DataView` with an offset, short
packets, 12-byte packets with `active_profile_id`, 10- and 11-byte packets without it, trailing bytes) and
encode (12 bytes, and the 10-byte legacy form); every COMMAND encoding; LOG packets, multi-notification
streams, the end marker in its own notification, empty logs and duplicates; PROFILES decode/encode including a 16-character name without
a NUL and UTF-8 truncation; tolerance evaluation; SETTINGS encode/decode and the 240-byte limit;
formatting, stats and CSV. Each expected byte array is written out by hand from the contract, not
generated by the code under test.

`protocol.vectors.test.mjs`: 14 more tests added in review, all pass. Their expected bytes were
produced by the firmware's portable C codec (`gatt_codec.c`, `logrec.c`), compiled with gcc in
WSL, so they check that page and firmware agree byte for byte: every LIVE flag bit, `INT32_MIN`
and `INT32_MAX`, a high-bit LOG seq and the end marker, a 16-byte name with no NUL, a UTF-8 name,
delete records, the 16-record limit and the u32/u16 command extremes. **Exception:** the two LIVE
vectors were 10 bytes from `gatt_live_pack()`; for the 12-byte LIVE their last two bytes (the profile
id) were appended by hand, and the 10-byte originals stay as decode-only checks. The firmware track
regenerates them from C once its codec writes 12 bytes. The other direction was
checked once by hand and is not automated: profiles, SETTINGS JSON and commands encoded by
`protocol.js` were fed to the firmware's `gatt_profile_unpack()`, `settings_from_json()` and
`gatt_cmd_parse()`, which accepted all of them and decoded the same values (a throwaway harness,
not in the repo). That was the firmware code as it stood during the review; it was still being written.

Not tested: the DOM code, the chart, the Web Bluetooth transport and Web Serial. Those were only
exercised by hand in demo mode in Chrome.

## To verify on the prototype

- Connect from Chrome on Windows, Android and macOS; check the chooser finds the caliper by service UUID.
- LIVE notification rate and latency; the chart assumes ≈ 10–20 Hz and keeps 30 s.
- LOG_READ of a full log (thousands of records): time, and whether the 5 s idle timeout is long enough.
- Long reads of SETTINGS (240 B) and PROFILES (up to 480 B) through Chrome's Read Blob handling.
- Reconnect after the caliper's auto-off; the page offers "Reconnect" to the same device without the chooser.
