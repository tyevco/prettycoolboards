// PrettyCool Caliper companion page: UI, Web Bluetooth transport, demo simulator, Web Serial console.
// All byte-level work is in protocol.js (pure, unit-tested); this file only moves bytes and draws.
import * as P from './protocol.js';

const $ = (id) => document.getElementById(id);
const CHART_SPAN_S = 30;
const LOG_IDLE_TIMEOUT_MS = 5000;

// ---------------------------------------------------------------------------------------------
// Transport: Web Bluetooth
// ---------------------------------------------------------------------------------------------

class BleTransport {
  constructor() {
    this.kind = 'ble';
    this.device = null;
    this.chars = {};
    this.handlers = { live: () => {}, log: () => {}, battery: () => {}, disconnect: () => {} };
    this._q = Promise.resolve(); // Chrome allows one GATT operation at a time
  }
  on(evt, fn) { this.handlers[evt] = fn; }
  _op(fn) { const p = this._q.then(fn); this._q = p.catch(() => {}); return p; }

  async connect(device) {
    if (!device) {
      device = await navigator.bluetooth.requestDevice({
        filters: [{ services: [P.UUID.SERVICE] }],
        optionalServices: [P.UUID.BATTERY_SERVICE, P.UUID.DEVICE_INFO_SERVICE],
      });
    }
    this.device = device;
    this._onDisc = () => this.handlers.disconnect();
    device.removeEventListener('gattserverdisconnected', this._onDisc);
    device.addEventListener('gattserverdisconnected', this._onDisc);
    const server = await device.gatt.connect();
    const svc = await server.getPrimaryService(P.UUID.SERVICE);
    for (const k of ['LIVE', 'COMMAND', 'LOG', 'SETTINGS', 'PROFILES']) {
      try { this.chars[k] = await svc.getCharacteristic(P.UUID[k]); } catch (e) { console.warn(`missing ${k}`, e); }
    }
    if (!this.chars.LIVE || !this.chars.COMMAND) throw new Error('caliper service is missing LIVE or COMMAND');
    this.chars.LIVE.addEventListener('characteristicvaluechanged', (e) => this.handlers.live(e.target.value));
    await this.chars.LIVE.startNotifications();
    if (this.chars.LOG) {
      this.chars.LOG.addEventListener('characteristicvaluechanged', (e) => this.handlers.log(e.target.value));
      await this.chars.LOG.startNotifications();
    }
    try {
      const bs = await server.getPrimaryService(P.UUID.BATTERY_SERVICE);
      this.chars.BATTERY = await bs.getCharacteristic(P.UUID.BATTERY_LEVEL);
      try {
        this.chars.BATTERY.addEventListener('characteristicvaluechanged', (e) => this.handlers.battery(e.target.value.getUint8(0)));
        await this.chars.BATTERY.startNotifications();
      } catch { /* read-only battery level is fine; polled instead */ }
    } catch { /* no battery service */ }
    try { this.dis = await server.getPrimaryService(P.UUID.DEVICE_INFO_SERVICE); } catch { this.dis = null; }
    return device.name || 'caliper';
  }
  get name() { return this.device?.name || 'caliper'; }
  get connected() { return !!this.device?.gatt?.connected; }
  disconnect() { if (this.device?.gatt?.connected) this.device.gatt.disconnect(); }
  readLive() { return this._op(() => this.chars.LIVE.readValue()); }
  command(bytes) { return this._op(() => this.chars.COMMAND.writeValueWithResponse(bytes)); }
  _need(k) { if (!this.chars[k]) throw new Error(`${k} characteristic not present`); return this.chars[k]; }
  readSettings() { return this._op(() => this._need('SETTINGS').readValue()); }
  writeSettings(bytes) { return this._op(() => this._need('SETTINGS').writeValueWithResponse(bytes)); }
  readProfiles() { return this._op(() => this._need('PROFILES').readValue()); }
  writeProfiles(bytes) { return this._op(() => this._need('PROFILES').writeValueWithResponse(bytes)); }
  async readBattery() {
    if (!this.chars.BATTERY) return null;
    const v = await this._op(() => this.chars.BATTERY.readValue());
    return v.getUint8(0);
  }
  async deviceInfo() {
    const out = {};
    if (!this.dis) return out;
    const td = new TextDecoder();
    for (const [key, name] of P.DIS_CHARS) {
      try {
        const c = await this._op(() => this.dis.getCharacteristic(name));
        out[key] = td.decode(await this._op(() => c.readValue())).replace(/\0+$/, '');
      } catch { /* optional */ }
    }
    return out;
  }
}

// ---------------------------------------------------------------------------------------------
// Transport: demo simulator. It speaks the same bytes as the firmware, so demo mode exercises
// the same decode paths (LIVE/LOG/PROFILES/SETTINGS) as a real connection.
// ---------------------------------------------------------------------------------------------

// Rev A firmware combines the PCNT quadrature count (2 mm / 1024 edges = 1953.125 nm) with the 12-bit SSI
// position inside the pole pair, so its internal step is the SSI step: 2 mm / 4096 = 488.28125 nm (SPEC §4.1).
const AS5311_COUNT_NM = 488.28125;

function gauss() { // Box-Muller
  let u = 0, v = 0;
  while (u === 0) u = Math.random();
  while (v === 0) v = Math.random();
  return Math.sqrt(-2 * Math.log(u)) * Math.cos(2 * Math.PI * v);
}

class DemoTransport {
  constructor() {
    this.kind = 'demo';
    this.handlers = { live: () => {}, log: () => {}, battery: () => {}, disconnect: () => {} };
    this.connected = false;
    this.unit = P.UNIT.MM;
    this.hold = false;
    this.holdNm = 0;
    this.zeroNm = 0;
    this.posNm = 0; // absolute jaw opening
    this.from = 0; this.to = 0; this.t0 = 0; this.t1 = 0; this.dwellUntil = 0;
    this.battery = 78;
    this.charging = false;
    this.timeOffsetS = 0;
    this.activeProfile = 0;
    this.settings = { name: 'PCC-demo', wifi_ssid: 'workshop', mqtt_url: '', http_post_url: '', auto_off_s: 300, hid_suffix: '\n', decimals: 2 };
    this.profiles = [
      { id: 1, nominalNm: 25_400_000, tolMinusNm: 20_000, tolPlusNm: 20_000, name: '1in gauge' },
      { id: 2, nominalNm: 6_000_000, tolMinusNm: 50_000, tolPlusNm: 0, name: 'M6 shank' },
      { id: 3, nominalNm: 12_000_000, tolMinusNm: 0, tolPlusNm: 18_000, name: 'Bore 12H7' },
    ];
    this.seq = 0;
    this.log = [];
    const now = Math.floor(Date.now() / 1000);
    for (let i = 0; i < 42; i++) { // a few days of past readings
      const p = this.profiles[i % 3];
      const v = Math.round(p.nominalNm + (p.tolPlusNm - p.tolMinusNm) / 2 + gauss() * 15_000);
      const ok = P.evaluateTolerance(v, p) === 'pass';
      this.log.push({ seq: ++this.seq, unixS: now - (42 - i) * 5400, valueNm: v, unit: 0,
        flags: P.FLAG.HOLD | (ok ? P.FLAG.TOL_PASS : P.FLAG.TOL_FAIL), profileId: p.id });
    }
  }
  on(evt, fn) { this.handlers[evt] = fn; }
  get name() { return this.settings.name + ' (simulated)'; }

  async connect() {
    this.connected = true;
    this.t1 = performance.now();
    this._timer = setInterval(() => this._tick(), 50); // 20 Hz LIVE, the firmware's planned rate is similar
    this._batt = setInterval(() => {
      this.battery = Math.max(5, Math.min(100, this.battery + (this.charging ? 1 : -1)));
      if (this.battery >= 100) this.charging = false;
      if (this.battery <= 20) this.charging = true;
      this.handlers.battery(this.battery);
    }, 8000);
    return this.name;
  }
  disconnect() {
    if (!this.connected) return;
    this.connected = false;
    clearInterval(this._timer); clearInterval(this._batt);
    setTimeout(() => this.handlers.disconnect(), 0);
  }

  _pickTarget(now) {
    const r = Math.random();
    let target;
    if (r < 0.15) target = 0; // jaws closed
    else if (r < 0.40) target = 25_400_000 + gauss() * 14_000;
    else if (r < 0.60) target = 5_975_000 + gauss() * 25_000;
    else if (r < 0.80) target = 12_009_000 + gauss() * 8_000;
    else target = Math.random() * 150e6;
    this.from = this.posNm; this.to = Math.max(0, Math.min(150e6, target));
    const dist = Math.abs(this.to - this.from);
    this.t0 = now; this.t1 = now + 300 + dist / 40e6 * 1000; // ~40 mm/s hand speed
    this.dwellUntil = this.t1 + 1500 + Math.random() * 3500;
  }

  _absNm(now) {
    if (now >= this.dwellUntil) this._pickTarget(now);
    if (now >= this.t1) return { pos: this.to, speed: 0 };
    const x = (now - this.t0) / (this.t1 - this.t0);
    const s = x * x * (3 - 2 * x); // smoothstep
    const speed = Math.abs(this.to - this.from) * 6 * x * (1 - x) / ((this.t1 - this.t0) / 1000);
    return { pos: this.from + (this.to - this.from) * s, speed };
  }

  _sample() {
    const now = performance.now();
    const { pos, speed } = this._absNm(now);
    this.posNm = pos;
    const magAbs = Math.round((pos + gauss() * 250) / AS5311_COUNT_NM) * AS5311_COUNT_NM;
    let mag = Math.round(magAbs - this.zeroNm);
    // capacitive: a few um of periodic (scale-pitch) error + noise, drops out when moving fast
    const capErr = 4_000 * Math.sin((2 * Math.PI * pos) / 5.08e6) + gauss() * 1_500 + 2_500;
    const capValid = speed < 60e6 && Math.random() > 0.02;
    let cap = capValid ? Math.round(mag + capErr) : null;
    if (this.hold) { mag = this.holdNm; cap = this.holdCap; }
    let flags = 0;
    if (this.hold) flags |= P.FLAG.HOLD;
    if (cap !== null) flags |= P.FLAG.CAP_VALID;
    if (this.charging) flags |= P.FLAG.CHARGING;
    const prof = this.profiles.find((p) => p.id === this.activeProfile);
    if (prof) flags |= P.evaluateTolerance(mag, prof) === 'pass' ? P.FLAG.TOL_PASS : P.FLAG.TOL_FAIL;
    return { valueNm: mag, capNm: cap, unit: this.unit, flags, activeProfileId: this.activeProfile };
  }
  _tick() {
    const s = this._sample();
    this.last = s;
    this.handlers.live(P.toDataView(P.encodeLive(s)));
  }
  _nowS() { return Math.floor(Date.now() / 1000) + this.timeOffsetS; }

  async readLive() { return P.toDataView(P.encodeLive(this.last ?? this._sample())); }

  async command(bytes) {
    const c = P.decodeCommand(bytes);
    const cur = this.last ?? this._sample();
    switch (c.name) {
      case 'ZERO': this.zeroNm = this.posNm; this.hold = false; break;
      case 'HOLD_TOGGLE':
        this.hold = !this.hold;
        if (this.hold) { this.holdNm = cur.valueNm; this.holdCap = cur.capNm; }
        break;
      case 'RECORD_NOW':
        if (this.log.length >= 4000) this.log.shift();
        this.log.push({ seq: ++this.seq, unixS: this._nowS(), valueNm: cur.valueNm, unit: cur.unit,
          flags: cur.flags & (P.FLAG.HOLD | P.FLAG.TOL_PASS | P.FLAG.TOL_FAIL), profileId: this.activeProfile });
        break;
      case 'SET_UNIT': this.unit = c.unit ? P.UNIT.INCH : P.UNIT.MM; break;
      case 'LOG_READ': {
        const recs = this.log.filter((r) => r.seq >= c.fromSeq);
        const packets = P.encodeLogPackets(recs, { perPacket: 15 }); // 15 x 16 = 240 B fits a 247 B MTU
        packets.forEach((p, i) => setTimeout(() => this.connected && this.handlers.log(P.toDataView(p)), 30 * (i + 1)));
        break;
      }
      case 'LOG_CLEAR': this.log = []; break;
      case 'SELECT_PROFILE': this.activeProfile = c.profileId; break;
      case 'SET_TIME': this.timeOffsetS = c.unixS - Math.floor(Date.now() / 1000); break;
    }
    await new Promise((r) => setTimeout(r, 15));
  }
  async readSettings() {
    return P.toDataView(new TextEncoder().encode(JSON.stringify(this.settings)));
  }
  async writeSettings(bytes) {
    const obj = JSON.parse(new TextDecoder().decode(P.toBytes(bytes)));
    if (obj.wifi_pass !== undefined) { this._wifiPass = obj.wifi_pass; delete obj.wifi_pass; }
    Object.assign(this.settings, obj);
  }
  async readProfiles() { return P.toDataView(P.encodeProfiles(this.profiles)); }
  async writeProfiles(bytes) {
    // Upsert each record; a delete record (empty name, all values 0) removes that id, as in the
    // firmware's gatt_profile_is_delete(). The page also works against a "replace all" firmware.
    const recs = P.decodeProfiles(bytes);
    if (recs.length > P.PROFILES_MAX) throw new Error('too many profile records');
    for (const r of recs) {
      const i = this.profiles.findIndex((p) => p.id === r.id);
      if (P.isProfileDelete(r)) { if (i >= 0) this.profiles.splice(i, 1); }
      else if (i >= 0) this.profiles[i] = r;
      else this.profiles.push(r);
    }
    if (this.profiles.length > P.PROFILES_MAX) throw new Error('caliper profile table full');
  }
  async readBattery() { return this.battery; }
  async deviceInfo() {
    return { manufacturer: 'prettycoolboards', model: 'PrettyCool Caliper', hardware: 'rev A (simulated)', firmware: 'demo' };
  }
}

// ---------------------------------------------------------------------------------------------
// App state
// ---------------------------------------------------------------------------------------------

const S = {
  t: null, // transport
  live: null,
  lastLiveAt: 0,
  unit: P.UNIT.MM,
  decimals: 2,
  samples: [], // {t, mag, cap}
  session: [], // nm values
  log: [],
  profiles: [],
  activeProfile: 0,
  logAsm: null,
  logTimer: null,
  chartDirty: true,
};

function loadPrefs() {
  try {
    const p = JSON.parse(localStorage.getItem('pcc-app') || '{}');
    if (Number.isInteger(p.activeProfile)) S.activeProfile = p.activeProfile;
    if (Array.isArray(p.profiles)) S.profiles = p.profiles;
  } catch { /* storage may be blocked */ }
}
function savePrefs() {
  try { localStorage.setItem('pcc-app', JSON.stringify({ activeProfile: S.activeProfile, profiles: S.profiles })); } catch { /* ignore */ }
}

let toastTimer;
function toast(msg, ms = 4000) {
  const el = $('toast');
  el.textContent = msg; el.hidden = false;
  clearTimeout(toastTimer);
  toastTimer = setTimeout(() => { el.hidden = true; }, ms);
}
function fail(what, e) {
  console.error(what, e);
  toast(`${what}: ${e?.message || e}`, 6000);
}

function setStatus(text, cls = '') {
  $('statusText').textContent = text;
  $('statusDot').className = 'dot ' + cls;
}

const fmt = (nm, unit = S.unit) => (nm === null || nm === undefined || Number.isNaN(nm) ? '--' : P.formatReading(nm, unit, S.decimals));
function fmtDelta(nm, unit = S.unit) {
  if (nm === null || nm === undefined || Number.isNaN(nm)) return '--';
  const sign = nm > 0 ? '+' : nm < 0 ? '−' : '±';
  if (unit === P.UNIT.INCH) return `${sign}${(Math.abs(nm) / 25.4e6 * 1e4).toFixed(1)} ×10⁻⁴ in`;
  return `${sign}${(Math.abs(nm) / 1000).toFixed(1)} µm`;
}

// ---------------------------------------------------------------------------------------------
// Connection lifecycle
// ---------------------------------------------------------------------------------------------

function setConnectedUi(on) {
  for (const id of ['cZero', 'cHold', 'cRecord', 'cUnit', 'cTime', 'logRead', 'logClear', 'profRead', 'profWrite', 'profNone', 'setRead', 'setWrite', 'sAdd']) {
    $(id).disabled = !on;
  }
  $('btnDisconnect').hidden = !on;
  $('btnConnect').hidden = on;
  $('btnDemo').hidden = on;
  renderProfiles();
}

async function start(transport, device) {
  if (S.t) S.t.disconnect();
  S.t = transport;
  S.deviceProfileIds = null; // unknown until PROFILES is read from this caliper
  // Guard every handler: Chrome may hand a reconnecting transport the same characteristic objects as an old one.
  const mine = (fn) => (...a) => { if (S.t === transport) fn(...a); };
  transport.on('live', mine(onLive));
  transport.on('log', mine(onLog));
  transport.on('battery', mine((b) => { $('battery').textContent = `${b}%`; S.battery = b; renderDevice(); }));
  transport.on('disconnect', () => onDisconnect(transport));
  setStatus('Connecting…', 'busy');
  try {
    const name = await transport.connect(device);
    setStatus(transport.kind === 'demo' ? `Demo: ${name}` : `Connected: ${name}`, transport.kind === 'demo' ? 'demo' : 'on');
    setConnectedUi(true);
    S.samples = [];
    await sendTime(true);
    try { onLive(await transport.readLive()); } catch { /* notification will come */ }
    try { const b = await transport.readBattery(); if (b !== null) { S.battery = b; $('battery').textContent = `${b}%`; } } catch { /* optional */ }
    S.info = await transport.deviceInfo().catch(() => ({}));
    renderDevice();
    await readSettings(true);
    await readProfiles(true);
  } catch (e) {
    if (e?.name === 'NotFoundError') { setStatus('Not connected'); return; } // chooser cancelled
    setStatus('Connection failed');
    try { transport.disconnect(); } catch { /* ignore */ } // don't leave a half-set-up GATT link open
    setConnectedUi(false);
    fail('Connect', e);
  }
}

function onDisconnect(transport) {
  if (S.t !== transport) return;
  setConnectedUi(false);
  $('reading').classList.add('stale');
  if (transport.kind === 'ble' && transport.device) {
    setStatus('Disconnected');
    $('btnConnect').textContent = 'Reconnect';
    S.lastDevice = transport.device;
  } else {
    setStatus('Not connected');
  }
  S.t = null;
  renderDevice();
}

function renderDevice() {
  const dl = $('devInfo');
  const rows = [];
  const t = S.t;
  rows.push(['State', t ? (t.kind === 'demo' ? 'Demo mode (simulated caliper)' : 'Connected over BLE') : 'Not connected']);
  if (t) {
    rows.push(['Name', t.name]);
    for (const [k, label] of [['manufacturer', 'Manufacturer'], ['model', 'Model'], ['hardware', 'Hardware'], ['firmware', 'Firmware']]) {
      if (S.info?.[k]) rows.push([label, S.info[k]]);
    }
    if (S.battery !== undefined) rows.push(['Battery', `${S.battery}%${S.live?.charging ? ' (charging)' : ''}`]);
    if (S.timeSentAt) rows.push(['Clock set', new Date(S.timeSentAt).toLocaleTimeString()]);
  }
  dl.replaceChildren(...rows.flatMap(([k, v]) => { const dt = document.createElement('dt'); dt.textContent = k; const dd = document.createElement('dd'); dd.textContent = v; return [dt, dd]; }));
}

async function sendCmd(bytes, label) {
  if (!S.t) return;
  try { await S.t.command(bytes); } catch (e) { fail(label, e); throw e; }
}
async function sendTime(quiet) {
  try {
    await sendCmd(P.encodeCommand.setTime(Math.floor(Date.now() / 1000)), 'Set time');
    S.timeSentAt = Date.now();
    renderDevice();
    if (!quiet) toast('Caliper clock set from this device');
  } catch { /* reported */ }
}

// ---------------------------------------------------------------------------------------------
// LIVE
// ---------------------------------------------------------------------------------------------

function onLive(dv) {
  let l;
  try { l = P.decodeLive(dv); } catch (e) { console.warn('bad LIVE', e); return; }
  const prevCharging = S.live?.charging;
  S.live = l;
  S.unit = l.unit === P.UNIT.INCH ? P.UNIT.INCH : P.UNIT.MM;
  S.lastLiveAt = performance.now();
  // A 12-byte LIVE says which profile the caliper is using (it may have been changed on the caliper);
  // a 10-byte one (older firmware) does not, and the page keeps the profile it last selected.
  if (l.activeProfileId !== null && l.activeProfileId !== S.activeProfile) {
    S.activeProfile = l.activeProfileId; savePrefs(); renderProfiles(); S.chartDirty = true;
  }
  const t = performance.now() / 1000;
  S.samples.push({ t, mag: l.sensorErr ? null : l.valueNm, cap: l.capNm });
  while (S.samples.length && S.samples[0].t < t - CHART_SPAN_S - 1) S.samples.shift();
  S.chartDirty = true;
  renderLive();
  if (prevCharging !== l.charging) renderDevice();
}

function setChip(id, on) { $(id).classList.toggle('on', !!on); }

function renderLive() {
  const l = S.live;
  if (!l) return;
  $('reading').classList.remove('stale');
  $('readingVal').textContent = l.sensorErr ? 'Err' : fmt(l.valueNm);
  $('readingUnit').textContent = P.unitLabel(S.unit);
  setChip('fHold', l.hold); setChip('fPass', l.tolPass); setChip('fFail', l.tolFail);
  setChip('fCap', l.capValid); setChip('fChg', l.charging); setChip('fErr', l.sensorErr);
  const lcd = $('lcd');
  lcd.classList.toggle('pass', l.tolPass && !l.tolFail);
  lcd.classList.toggle('fail', l.tolFail);
  $('cHold').setAttribute('aria-pressed', String(l.hold));
  $('vMag').textContent = `${fmt(l.valueNm)} ${P.unitLabel(S.unit)}`;
  $('vCap').textContent = l.capNm === null ? 'invalid' : `${fmt(l.capNm)} ${P.unitLabel(S.unit)}`;
  $('vDiff').textContent = l.capNm === null ? '--' : fmtDelta(l.capNm - l.valueNm);
  $('profUnit').textContent = P.unitLabel(S.unit);
  if (S.renderedUnit !== S.unit) { S.renderedUnit = S.unit; renderProfiles(); renderStats(); renderLog(); }
}

// Mark the reading stale when notifications stop.
setInterval(() => {
  if (S.t && S.live && performance.now() - S.lastLiveAt > 2500) $('reading').classList.add('stale');
}, 1000);

// ---------------------------------------------------------------------------------------------
// Chart (hand-drawn canvas)
// ---------------------------------------------------------------------------------------------

const canvas = $('chart');
const ctx = canvas.getContext('2d');
$('chartSpan').textContent = CHART_SPAN_S;

function cssVar(name) { return getComputedStyle(document.documentElement).getPropertyValue(name).trim(); }
let colors = {};
function readColors() {
  colors = { accent: cssVar('--accent'), cap: cssVar('--cap'), band: cssVar('--band'), grid: cssVar('--grid'),
    muted: cssVar('--muted'), text: cssVar('--text'), pass: cssVar('--pass') };
  S.chartDirty = true;
}
readColors();
matchMedia('(prefers-color-scheme: dark)').addEventListener?.('change', readColors);
new ResizeObserver(() => { S.chartDirty = true; }).observe(canvas);

function niceStep(range, target = 5) {
  const raw = range / target;
  const mag = 10 ** Math.floor(Math.log10(raw));
  const n = raw / mag;
  return (n < 1.5 ? 1 : n < 3 ? 2 : n < 7 ? 5 : 10) * mag;
}

function drawChart() {
  const dpr = window.devicePixelRatio || 1;
  const w = canvas.clientWidth, h = canvas.clientHeight;
  if (!w || !h) return;
  if (canvas.width !== Math.round(w * dpr) || canvas.height !== Math.round(h * dpr)) {
    canvas.width = Math.round(w * dpr); canvas.height = Math.round(h * dpr);
  }
  ctx.setTransform(dpr, 0, 0, dpr, 0, 0);
  ctx.clearRect(0, 0, w, h);
  const now = performance.now() / 1000;
  const unit = S.unit;
  const conv = (nm) => P.nmToUnit(nm, unit);
  const pts = S.samples.filter((s) => s.t >= now - CHART_SPAN_S);
  const vals = [];
  for (const s of pts) { if (s.mag !== null) vals.push(conv(s.mag)); if (s.cap !== null) vals.push(conv(s.cap)); }
  ctx.font = '12px ' + cssVar('--sans');
  const prof = S.profiles.find((p) => p.id === S.activeProfile);
  const band = prof ? P.toleranceBand(prof) : null;
  if (!vals.length) {
    ctx.fillStyle = colors.muted; ctx.textAlign = 'center';
    ctx.fillText(S.t ? 'Waiting for readings…' : 'Connect, or start demo mode, to see live readings', w / 2, h / 2);
    return;
  }
  let lo = Math.min(...vals), hi = Math.max(...vals);
  if (band) { // include the band when the readings are near it, so the band stays visible while measuring
    const bl = conv(band.lo), bh = conv(band.hi), span = Math.max(bh - bl, unit === P.UNIT.INCH ? 0.0004 : 0.01);
    if (hi >= bl - 20 * span && lo <= bh + 20 * span) { lo = Math.min(lo, bl - span); hi = Math.max(hi, bh + span); }
  }
  const minSpan = unit === P.UNIT.INCH ? 0.0004 : 0.01;
  if (hi - lo < minSpan) { const c = (hi + lo) / 2; lo = c - minSpan / 2; hi = c + minSpan / 2; }
  const padY = (hi - lo) * 0.08; lo -= padY; hi += padY;
  const step = niceStep(hi - lo);
  const decs = Math.max(0, Math.min(6, -Math.floor(Math.log10(step) + 1e-9)));
  const left = Math.max(...[lo, hi].map((v) => ctx.measureText(v.toFixed(decs)).width)) + 12;
  const L = left, R = w - 8, T = 8, B = h - 20;
  const x = (t) => L + ((t - (now - CHART_SPAN_S)) / CHART_SPAN_S) * (R - L);
  const y = (v) => B - ((v - lo) / (hi - lo)) * (B - T);

  // grid + y labels
  ctx.strokeStyle = colors.grid; ctx.lineWidth = 1; ctx.fillStyle = colors.muted; ctx.textAlign = 'right'; ctx.textBaseline = 'middle';
  for (let v = Math.ceil(lo / step) * step; v <= hi; v += step) {
    const yy = Math.round(y(v)) + 0.5;
    ctx.beginPath(); ctx.moveTo(L, yy); ctx.lineTo(R, yy); ctx.stroke();
    ctx.fillText(v.toFixed(decs), L - 6, yy);
  }
  ctx.textAlign = 'center'; ctx.textBaseline = 'alphabetic';
  for (let s = 0; s <= CHART_SPAN_S; s += 10) {
    const xx = x(now - CHART_SPAN_S + s);
    ctx.fillText(s === CHART_SPAN_S ? 'now' : `−${CHART_SPAN_S - s} s`, Math.min(Math.max(xx, L + 14), R - 14), h - 4);
  }
  // tolerance band
  if (band) {
    const y1 = y(conv(band.hi)), y2 = y(conv(band.lo));
    const top = Math.max(T, Math.min(y1, B)), bot = Math.max(T, Math.min(y2, B));
    if (bot > top) { ctx.fillStyle = colors.band; ctx.fillRect(L, top, R - L, bot - top); }
    else { ctx.fillStyle = colors.muted; ctx.textAlign = 'right'; ctx.fillText(`band ${y1 < T ? 'above' : 'below'} →`, R - 4, y1 < T ? T + 12 : B - 4); }
    if (y(conv(prof.nominalNm)) > T && y(conv(prof.nominalNm)) < B) {
      ctx.strokeStyle = colors.pass; ctx.setLineDash([4, 4]); ctx.beginPath();
      ctx.moveTo(L, y(conv(prof.nominalNm))); ctx.lineTo(R, y(conv(prof.nominalNm))); ctx.stroke(); ctx.setLineDash([]);
    }
  }
  // series
  ctx.save(); ctx.beginPath(); ctx.rect(L, T, R - L, B - T); ctx.clip();
  const line = (key, color, width, dash) => {
    ctx.strokeStyle = color; ctx.lineWidth = width; ctx.setLineDash(dash); ctx.lineJoin = 'round';
    ctx.beginPath(); let pen = false;
    for (const s of pts) {
      if (s[key] === null) { pen = false; continue; }
      const xx = x(s.t), yy = y(conv(s[key]));
      if (pen) ctx.lineTo(xx, yy); else { ctx.moveTo(xx, yy); pen = true; }
    }
    ctx.stroke(); ctx.setLineDash([]);
  };
  line('cap', colors.cap, 1.5, [5, 3]);
  line('mag', colors.accent, 2.25, []);
  ctx.restore();
}

function frame() {
  if (S.chartDirty || S.t) { drawChart(); S.chartDirty = false; } // scrolls while connected
  requestAnimationFrame(frame);
}
requestAnimationFrame(frame);

// ---------------------------------------------------------------------------------------------
// Session stats
// ---------------------------------------------------------------------------------------------

function addSession(nm) {
  if (nm === null || nm === undefined) return;
  S.session.push(nm);
  $('sLast').textContent = `last: ${fmt(nm)} ${P.unitLabel(S.unit)}`;
  renderStats();
}
function renderStats() {
  const s = P.computeStats(S.session);
  const u = P.unitLabel(S.unit);
  $('sCount').textContent = s.count;
  $('sMin').textContent = s.count ? fmt(s.min) : '--';
  $('sMax').textContent = s.count ? fmt(s.max) : '--';
  $('sMean').textContent = s.count ? fmt(s.mean) : '--';
  $('sSd').textContent = s.count > 1 ? fmtDelta(s.sd).replace(/^[+−±]/, '') : '--';
  $('sRange').textContent = s.count ? fmtDelta(s.range).replace(/^[+−±]/, '') : '--';
  $('hStats').querySelector('.note').textContent = `readings you record in this page (${u})`;
}

// ---------------------------------------------------------------------------------------------
// Log download
// ---------------------------------------------------------------------------------------------

function onLog(dv) {
  if (!S.logAsm) return; // unsolicited
  try {
    const done = S.logAsm.feed(dv);
    $('logStatus').textContent = `receiving… ${S.logAsm.records.length} records`;
    clearTimeout(S.logTimer);
    if (done) finishLog(true);
    else S.logTimer = setTimeout(() => finishLog(false), LOG_IDLE_TIMEOUT_MS);
  } catch (e) {
    fail('Log packet', e);
  }
}
function finishLog(ok) {
  clearTimeout(S.logTimer);
  const asm = S.logAsm; S.logAsm = null;
  if (!asm) return;
  const from = Number($('logFrom').value) || 0;
  const keep = from > 0 ? S.log.filter((r) => r.seq < from) : [];
  S.log = [...keep, ...asm.records].sort((a, b) => a.seq - b.seq);
  $('logStatus').textContent = ok
    ? `${asm.records.length} records in ${asm.packets} notifications`
    : `stopped: no end marker after ${LOG_IDLE_TIMEOUT_MS / 1000} s (${asm.records.length} records kept)`;
  $('logRead').disabled = !S.t;
  $('logCsv').disabled = !S.log.length;
  renderLog();
}
async function readLog() {
  const from = Math.max(0, Math.min(0xffffffff, Math.floor(Number($('logFrom').value) || 0)));
  S.logAsm = new P.LogAssembler();
  $('logRead').disabled = true;
  $('logStatus').textContent = 'requesting…';
  S.logTimer = setTimeout(() => finishLog(false), LOG_IDLE_TIMEOUT_MS);
  try { await sendCmd(P.encodeCommand.logRead(from), 'Log read'); } catch { S.logAsm = null; clearTimeout(S.logTimer); $('logRead').disabled = false; $('logStatus').textContent = ''; }
}
function renderLog() {
  const names = new Map(S.profiles.map((p) => [p.id, p.name]));
  const body = $('logBody');
  const rows = S.log.slice(-2000).reverse().map((r) => {
    const tr = document.createElement('tr');
    const f = P.decodeFlags(r.flags);
    const tags = [f.hold && 'HOLD', f.tolPass && 'PASS', f.tolFail && 'FAIL'].filter(Boolean);
    const cells = [
      [String(r.seq), 'num'],
      [r.unixS ? new Date(r.unixS * 1000).toLocaleString() : '(no clock)', ''],
      [P.formatReading(r.valueNm, r.unit, S.decimals), 'num'],
      [P.unitLabel(r.unit), ''],
      [null, ''],
      [r.profileId ? `${r.profileId}${names.has(r.profileId) ? ' · ' + names.get(r.profileId) : ''}` : '–', ''],
    ];
    for (const [text, cls] of cells) {
      const td = document.createElement('td');
      if (cls) td.className = cls;
      if (text === null) {
        for (const tg of tags) { const s = document.createElement('span'); s.className = 'tag ' + (tg === 'PASS' ? 'pass' : tg === 'FAIL' ? 'fail' : ''); s.textContent = tg + ' '; td.append(s); }
      } else td.textContent = text;
      tr.append(td);
    }
    return tr;
  });
  body.replaceChildren(...rows);
  $('logWrap').hidden = S.log.length === 0;
  $('logNote').textContent = S.log.length ? `${S.log.length} records downloaded${S.log.length > 2000 ? ' (table shows the newest 2000; CSV has all)' : ''}` : 'stored on the caliper';
}
function exportCsv() {
  const blob = new Blob([P.logToCsv(S.log, S.profiles)], { type: 'text/csv' });
  const a = document.createElement('a');
  a.href = URL.createObjectURL(blob);
  a.download = `caliper-log-${new Date().toISOString().slice(0, 19).replace(/[:T]/g, '-')}.csv`;
  document.body.append(a); a.click(); a.remove();
  setTimeout(() => URL.revokeObjectURL(a.href), 1000);
}
async function clearLog() {
  if (!confirm('Erase every stored reading on the caliper? This cannot be undone.')) return;
  try {
    await sendCmd(P.encodeCommand.logClear(), 'Clear log');
    S.log = []; renderLog(); $('logCsv').disabled = true;
    $('logStatus').textContent = 'log cleared on the caliper';
  } catch { /* reported */ }
}

// ---------------------------------------------------------------------------------------------
// Profiles
// ---------------------------------------------------------------------------------------------


async function readProfiles(quiet) {
  if (!S.t) return;
  try {
    S.profiles = P.decodeProfiles(await S.t.readProfiles());
    S.deviceProfileIds = S.profiles.map((p) => p.id);
    savePrefs(); renderProfiles(); renderLog();
    $('profStatus').textContent = `${S.profiles.length} profiles read`;
  } catch (e) { if (!quiet) fail('Read profiles', e); else $('profStatus').textContent = `read failed: ${e.message}`; }
}
async function writeProfiles() {
  if (!S.deviceProfileIds) return toast('Read the profiles from the caliper first, so deletions can be sent');
  let recs;
  try { recs = P.profilesWriteRecords(S.profiles, S.deviceProfileIds); } catch (e) { return toast(e.message); }
  try {
    await S.t.writeProfiles(P.encodeProfiles(recs));
    const dels = recs.length - S.profiles.length;
    S.deviceProfileIds = S.profiles.map((p) => p.id);
    $('profStatus').textContent = `${S.profiles.length} profiles written${dels ? `, ${dels} deleted` : ''}`;
    savePrefs();
  } catch (e) { fail('Write profiles', e); }
}
async function selectProfile(id) {
  try {
    await sendCmd(P.encodeCommand.selectProfile(id), 'Select profile');
    S.activeProfile = id; savePrefs(); renderProfiles(); S.chartDirty = true;
  } catch { /* reported */ }
}
function renderProfiles() {
  const list = $('profList');
  const u = S.unit;
  const decs = u === P.UNIT.INCH ? 5 : 4;
  const step = u === P.UNIT.INCH ? '0.00001' : '0.0001';
  list.replaceChildren(...S.profiles.map((p, i) => {
    const row = document.createElement('div');
    row.className = 'profile' + (p.id === S.activeProfile ? ' active' : '');
    const field = (label, value, onChange, attrs = {}) => {
      const l = document.createElement('label'); l.className = 'field';
      const s = document.createElement('span'); s.textContent = label;
      const inp = document.createElement('input'); Object.assign(inp, attrs); inp.value = value;
      inp.addEventListener('change', () => { try { onChange(inp.value); } catch (e) { toast(e.message); } renderProfiles(); });
      l.append(s, inp); return l;
    };
    const num = (label, key) => field(label, P.nmToUnit(p[key], u).toFixed(decs), (v) => {
      const nm = P.unitToNm(Number(v), u);
      if (!Number.isFinite(nm) || Math.abs(nm) > 0x7fffffff) throw new Error(`${label} out of range`);
      p[key] = key === 'nominalNm' ? nm : Math.abs(nm);
    }, { type: 'number', step, inputMode: 'decimal' });
    row.append(
      field('Name', p.name, (v) => { p.name = new TextDecoder().decode(P.utf8Truncate(v.trim(), P.PROFILE_NAME_LEN)); }, { maxLength: P.PROFILE_NAME_LEN, required: true }),
      num('Nominal', 'nominalNm'),
      num('Tol −', 'tolMinusNm'),
      num('Tol +', 'tolPlusNm'),
      field('Id', p.id, (v) => { const n = Number(v); if (!Number.isInteger(n) || n < 1 || n > 65535) throw new Error('id must be 1..65535'); p.id = n; }, { type: 'number', min: 1, max: 65535, inputMode: 'numeric' }),
    );
    const acts = document.createElement('div'); acts.className = 'acts';
    const use = document.createElement('button'); use.type = 'button'; use.textContent = p.id === S.activeProfile ? 'Active' : 'Use';
    use.disabled = !S.t; use.setAttribute('aria-pressed', String(p.id === S.activeProfile));
    use.addEventListener('click', () => selectProfile(p.id));
    const del = document.createElement('button'); del.type = 'button'; del.className = 'danger'; del.textContent = 'Delete';
    del.setAttribute('aria-label', `Delete profile ${p.name}`);
    del.addEventListener('click', () => { S.profiles.splice(i, 1); renderProfiles(); });
    acts.append(use, del); row.append(acts);
    return row;
  }));
  if (!S.profiles.length) {
    const p = document.createElement('p'); p.className = 'small muted';
    p.textContent = 'No profiles. Read them from the caliper or add one.';
    list.append(p);
  }
  const ap = S.profiles.find((p) => p.id === S.activeProfile);
  if (ap) {
    const b = P.toleranceBand(ap);
    $('profileNote').textContent = `profile: ${ap.name} (${fmt(b.lo)} … ${fmt(b.hi)} ${P.unitLabel(u)})`;
  } else $('profileNote').textContent = '';
  $('profAdd').disabled = S.profiles.length >= P.PROFILES_MAX;
}
function addProfile() {
  const id = Math.max(0, ...S.profiles.map((p) => p.id)) + 1;
  const nominal = S.live && !S.live.sensorErr ? Math.round(S.live.valueNm / 1000) * 1000 : 10_000_000;
  S.profiles.push({ id, nominalNm: nominal, tolMinusNm: 20_000, tolPlusNm: 20_000, name: `Part ${id}` });
  renderProfiles();
}

// ---------------------------------------------------------------------------------------------
// Settings
// ---------------------------------------------------------------------------------------------

const SUFFIX_TO_UI = { '\n': 'enter', '\t': 'tab', '': 'none' };
const UI_TO_SUFFIX = { enter: '\n', tab: '\t', none: '' };

function formToSettings() {
  const f = $('setForm').elements;
  const o = {};
  for (const k of ['name', 'wifi_ssid', 'wifi_pass', 'mqtt_url', 'http_post_url']) o[k] = f[k].value;
  if (f.auto_off_s.value !== '') o.auto_off_s = Number(f.auto_off_s.value);
  if (f.decimals.value !== '') o.decimals = Number(f.decimals.value);
  o.hid_suffix = UI_TO_SUFFIX[f.hid_suffix.value];
  return o;
}
function updateSettingsBytes() {
  const el = $('setBytes');
  try {
    const n = P.encodeSettings(formToSettings()).length;
    el.textContent = `${n} / ${P.SETTINGS_MAX_BYTES} bytes`; el.classList.remove('over');
  } catch (e) {
    el.textContent = e.bytes ? `${e.bytes} / ${P.SETTINGS_MAX_BYTES} bytes: too long` : e.message;
    el.classList.add('over');
  }
}
async function readSettings(quiet) {
  if (!S.t) return;
  try {
    const s = P.decodeSettings(await S.t.readSettings());
    const f = $('setForm').elements;
    for (const k of ['name', 'wifi_ssid', 'mqtt_url', 'http_post_url', 'auto_off_s', 'decimals']) f[k].value = s[k] ?? '';
    f.wifi_pass.value = '';
    f.hid_suffix.value = SUFFIX_TO_UI[s.hid_suffix] ?? 'enter';
    if (Number.isInteger(s.decimals) && s.decimals >= P.DECIMALS_MIN && s.decimals <= P.DECIMALS_MAX) S.decimals = s.decimals;
    updateSettingsBytes();
    $('setStatus').textContent = 'read from caliper';
    renderLive(); renderStats(); renderProfiles(); renderLog();
  } catch (e) { if (!quiet) fail('Read settings', e); else $('setStatus').textContent = `read failed: ${e.message}`; }
}
async function writeSettings(ev) {
  ev.preventDefault();
  if (!S.t) return;
  let bytes;
  try { bytes = P.encodeSettings(formToSettings()); } catch (e) { return toast(e.message); }
  try {
    await S.t.writeSettings(bytes);
    $('setForm').elements.wifi_pass.value = '';
    await readSettings(true);
    $('setStatus').textContent = `written (${bytes.length} bytes) and read back`;
  } catch (e) { fail('Write settings', e); }
}

// ---------------------------------------------------------------------------------------------
// Web Serial console (optional)
// ---------------------------------------------------------------------------------------------

const SER = { port: null, reader: null, writer: null };
function serPrint(text) {
  const out = $('serOut');
  out.textContent += text;
  if (out.textContent.length > 60000) out.textContent = out.textContent.slice(-40000);
  out.scrollTop = out.scrollHeight;
}
async function serOpen() {
  try {
    const port = await navigator.serial.requestPort({ filters: [{ usbVendorId: 0x303a }] }); // Espressif VID
    await port.open({ baudRate: 115200 });
    SER.port = port;
    $('serOut').hidden = false; $('serForm').hidden = false; $('serClose').hidden = false; $('serConnect').hidden = true;
    serPrint('[port open]\n');
    const enc = new TextEncoderStream();
    SER.writerClosed = enc.readable.pipeTo(port.writable).catch(() => {});
    SER.writer = enc.writable.getWriter();
    const dec = new TextDecoderStream();
    SER.readerClosed = port.readable.pipeTo(dec.writable).catch(() => {});
    SER.reader = dec.readable.getReader();
    (async () => {
      try { for (;;) { const { value, done } = await SER.reader.read(); if (done) break; serPrint(value); } }
      catch (e) { serPrint(`\n[read error: ${e.message}]\n`); }
    })();
  } catch (e) { if (e?.name !== 'NotFoundError') fail('Serial', e); }
}
async function serClose() {
  try { await SER.reader?.cancel(); await SER.readerClosed; } catch { /* ignore */ }
  try { await SER.writer?.close(); await SER.writerClosed; } catch { /* ignore */ }
  try { await SER.port?.close(); } catch { /* ignore */ }
  SER.port = null;
  serPrint('[port closed]\n');
  $('serForm').hidden = true; $('serClose').hidden = true; $('serConnect').hidden = false;
}

// ---------------------------------------------------------------------------------------------
// Wiring
// ---------------------------------------------------------------------------------------------

function bleUnavailableReason() {
  if (!window.isSecureContext) return 'This page is not in a secure context (it needs https:// or localhost).';
  if (!('bluetooth' in navigator)) return 'This browser does not implement the Web Bluetooth API (Firefox and Safari do not; every iOS browser is Safari underneath).';
  return '';
}

async function init() {
  loadPrefs();
  renderProfiles(); renderStats(); renderDevice(); updateSettingsBytes();
  const why = bleUnavailableReason();
  if (why) {
    $('noBle').hidden = false; $('noBleWhy').textContent = why;
    $('btnConnect').disabled = true; $('btnConnect').title = why;
  } else {
    try {
      if (navigator.bluetooth.getAvailability && !(await navigator.bluetooth.getAvailability())) {
        $('noBle').hidden = false; $('noBleWhy').textContent = 'No Bluetooth adapter is available (or it is switched off).';
      }
    } catch { /* ignore */ }
  }
  if (!('serial' in navigator)) {
    $('serConnect').disabled = true;
    $('serialNote').textContent = 'Web Serial is not available in this browser (Chrome/Edge on desktop only). The console is optional.';
  }

  $('btnConnect').addEventListener('click', () => {
    const dev = S.lastDevice; S.lastDevice = null; $('btnConnect').textContent = 'Connect';
    start(new BleTransport(), dev);
  });
  const demo = () => start(new DemoTransport());
  $('btnDemo').addEventListener('click', demo);
  $('btnDemo2').addEventListener('click', demo);
  $('btnDisconnect').addEventListener('click', () => { S.lastDevice = null; S.t?.disconnect(); });

  $('cZero').addEventListener('click', () => sendCmd(P.encodeCommand.zero(), 'Zero').catch(() => {}));
  $('cHold').addEventListener('click', () => sendCmd(P.encodeCommand.holdToggle(), 'Hold').catch(() => {}));
  $('cRecord').addEventListener('click', async () => {
    const v = S.live && !S.live.sensorErr ? S.live.valueNm : null;
    try { await sendCmd(P.encodeCommand.recordNow(), 'Record'); addSession(v); } catch { /* reported */ }
  });
  $('cUnit').addEventListener('click', () => sendCmd(P.encodeCommand.setUnit(S.unit === P.UNIT.MM ? 1 : 0), 'Unit').catch(() => {}));
  $('cTime').addEventListener('click', () => sendTime(false));
  $('sAdd').addEventListener('click', () => { if (S.live && !S.live.sensorErr) addSession(S.live.valueNm); });
  $('sReset').addEventListener('click', () => { S.session = []; $('sLast').textContent = ''; renderStats(); });

  $('logRead').addEventListener('click', readLog);
  $('logCsv').addEventListener('click', exportCsv);
  $('logClear').addEventListener('click', clearLog);
  $('profRead').addEventListener('click', () => readProfiles(false));
  $('profWrite').addEventListener('click', writeProfiles);
  $('profAdd').addEventListener('click', addProfile);
  $('profNone').addEventListener('click', () => selectProfile(0));
  $('setRead').addEventListener('click', () => readSettings(false));
  $('setForm').addEventListener('submit', writeSettings);
  $('setForm').addEventListener('input', updateSettingsBytes);
  $('serConnect').addEventListener('click', serOpen);
  $('serClose').addEventListener('click', serClose);
  $('serForm').addEventListener('submit', async (e) => {
    e.preventDefault();
    const inp = $('serIn');
    if (!SER.writer) return;
    try { await SER.writer.write(inp.value + '\r\n'); serPrint(`> ${inp.value}\n`); inp.value = ''; } catch (err) { fail('Serial write', err); }
  });

  document.addEventListener('keydown', (e) => {
    if (e.ctrlKey || e.metaKey || e.altKey || !S.t) return;
    if (e.target.closest('input, select, textarea, [contenteditable]')) return;
    const map = { z: 'cZero', h: 'cHold', r: 'cRecord', u: 'cUnit' };
    const id = map[e.key.toLowerCase()];
    if (id) { e.preventDefault(); $(id).click(); }
  });

  if (new URLSearchParams(location.search).has('demo')) demo();
}

init();
