# Electronic slide lock: research note

Status: desk research and hand calculations only. Nothing here has been built or measured.
**[UNVERIFIED]** marks values I could not confirm from a primary datasheet. **[EST]** marks my own
estimates or models. **(TVP)** follows the project's convention: to verify on the prototype.

> **Superseded context (2026-11-08).** This note was written against the 2026-11-07 mechanics. Since then the
> manual lock moved to u 19 (left of the battery pocket, pushing through a GFRP rod), the back cover became a closed
> back web plus a battery door, and the sliding force is 3.9 N oiled ([Mechanics](../mechanical.md)). The
> mounting positions and loads below were not re-checked against that layout.

Context used (read only): `caliper/hardware/design/SPEC.md` §1, §2.1, §3, §5, §7; `caliper/docs/mechanical.md`
§2 and §4 (the Y loop, the M3 lock screw at u 63 that clamps the brass Y gib, the 8 N sliding force, the back-cover
defect); `hardware/mechanical/params.py` (housing u 0.5…78, y −2.8…49.2, z −8.6…+7.4; roller at u 74.6);
`calcs_output.txt` §2–3; `dial-me-spinner/docs/mechanical.md` §7 (VSM08102 linear stepper, self-locking M2 lead
screw, DRV8837).

---

## 0. Answer in one paragraph

**Motorise the lock screw that's already there.** Use a Ø6 mm planetary gearmotor (Pololu #2359, 700:1, 6 × 21 mm)
to turn a self-locking M2 × 0.4 lead screw. A keyed travelling nut then compresses a stiff spring (~100 N/mm) onto
a brass pad that bears on the **existing brass Y gib**, which rides on the beam's **upper edge** (y = 20). That is
the same load path as today's M3 thumb screw. The clamp is **25 N normal**, which adds 6–10 N of holding friction
on top of the free sliding friction. Thread friction holds the clamp, with the 700:1 gearbox as a second lock, so
**holding power is zero**. Each lock or unlock costs **≈ 0.35 J** and takes **≈ 2 s**. An **I2C** H-bridge drives
the motor: a **DRV8830DGQR** (LCSC **C127591**) on the existing I2C bus. That needs **no GPIO**, adds 0.3 µA typ in
sleep, and its VSET DAC sets the motor voltage independent of the 3.0–4.4 V VSYS. The motor's magnet ends up
≥ 30 mm from the tape and ≥ 40 mm from the AS5311. The dipole upper bound there is **< 0.5 mT** at the tape and
**< 0.15 mT** at the AS5311. The AS5311 tolerates **±5 mT** of constant stray field, and the tape's coercivity is
~100× higher. Every magnetic option (EPM, latching solenoid, MR fluid) puts flux into an O1 beam that sits 2 mm
under the tape. An EPM also doesn't work on a 1.4301 beam at all. **Runner-up:** SMA (Flexinol) wires with a
bistable toggle. It's the only option with zero magnetic field and no piezo-level cost, but it's slow, weak and
sensitive to tolerances. **Integration catch:** the housing is full. The motor needs a Ø6.5 × 22 mm pocket that
doesn't exist in the 78 × 52 × 16 envelope today (§7). Rev B must give up something (cell length or the manual lock
location), and the mechanics clash check decides which.

---

## 1. Requirements as I read them

| Item | Target | Source |
|---|---|---|
| Axial hold | ≥ 5–10 N (measuring force 5 N + handling) | brief |
| Holding power | 0 (deep-sleep budget 40 µA, ≈ 38 µA already used; 35 / 33 when this note was written) | SPEC §3 |
| Supply | VSYS 3.0–4.4 V (1S LiPo ~500 mAh), +3V3 from the TPS63802 | SPEC §3 |
| GPIO | **none free** (SPEC §5 / `nets.py` MCU_PINS uses every bonded pin) | SPEC §5 |
| Jaw shift on engagement | ≪ 10 µm (0.01 mm display), ideally < 2 µm | brief, SPEC §1 |
| Beam surface | ground; must not be marked | SPEC §7 |
| Magnetic | nothing that disturbs the AS5311 or re-magnetises the 2 mm-pole-pair tape 1.25 mm under the beam face | SPEC §4.1, §7 |
| Envelope | housing ≤ 78 × 52 × 16; already packed (battery u 29.5–65.5, antenna keep-out u 8.6–24 + 5 mm, roller at u 74.6) | SPEC §7, params.py |

**Friction budget.** A normal clamp force N applied through the Y gib reacts at the gib/upper-edge contact *and* at
the reference-strip/edge-E contact. The added holding force is therefore **ΔF = 2 μ N**.

| μ (brass on ground steel) | N = 20 N | **N = 25 N** | N = 30 N |
|---|---|---|---|
| 0.12 (oiled) | 4.8 | **6.0** | 7.2 |
| 0.15 (light oil) | 6.0 | **7.5** | 9.0 |
| 0.20 (dry) | 8.0 | **10.0** | 12.0 |

Today's free sliding force is 8 N (mechanical.md §4, flagged as too high). The target is 2–5 N. With N = 25 N, the
total hold is **≈ 9–18 N**, and ≥ 8.5 N even in the worst case (oiled, 2.5 N free). That meets 5–10 N without
leaning on the high free friction. A high-μ elastomer pad would need less N, but it is **rejected**: a 4 × 8 × 1 mm
PU-90A pad has a shear stiffness of ~480 N/mm **[EST]**, so a 10 N push moves the "locked" jaw ~20 µm. Hard pads
only.

---

## 2. Comparison of candidates

Scores: ✔ good, ~ marginal, ✘ disqualifying.

| # | Mechanism | Hold in envelope | Size / mass | Energy per action | Hold power | Drive electronics | Noise / feel | Wear / beam surface | Jaw shift on engage | Magnetic risk to AS5311 + tape | Cost | Maturity / real parts | Verdict |
|---|---|---|---|---|---|---|---|---|---|---|---|---|---|
| **A** | **Micro gearmotor + self-locking lead screw + spring + pad on the Y gib** (recommended) | ✔ 25 N normal → +6–10 N axial; set by spring compression, not motor torque | Ø6 × 21 mm motor + Ø4 screw/nut/spring column ≈ 6.5 × 35 mm; ~3 g **[UNVERIFIED]** | ≈ 0.35 J, ≈ 2 s | **0** (thread λ 4.2° < friction angle; 700:1 gearbox resists back-drive too) | 1 × DRV8830 (I2C, C127591): **0 GPIO** | soft whirr ~2 s; no click | ✔ brass pad on the brass gib; the gib already slides on the edge; no new contact on the beam | ✔ load is purely in Y into an already seated loop; ≈ 1–4 µm yaw at the jaw tip in printed PETG **[EST]**, < 0.2 µm in 6061 | ✔ motor magnet ≥ 30 mm from the tape: < 0.5 mT (dipole upper bound) vs ±5 mT tolerance | ~$15–25 motor + $1.3–2.3 driver | ✔ catalogue parts (Pololu #2359; generic Ø6 planetary motors) | **Pick** |
| B | Micro linear stepper with a self-locking lead screw (reuse VSM08102 from dial-me-spinner) | ✘ 0.78 N thrust (dial-me-spinner §7, already marginal there). 25 N needs ≥ 35:1 leverage (toggle or wedge) → tolerance-critical | Ø8 × ~33 mm **[UNVERIFIED drawing]** | ~0.5–1 J (2 phases × 165 mA × 1–2 s) **[EST]** | 0 (lead screw) | 2 H-bridges (2 × DRV8837 C39159, or DRV8833): **4 GPIO** → needs a TCA9534 expander | quiet ticking | as A | as A, if a toggle can be built | ~ PM can-stack: steel can + magnet rotor ≈ motor A | ~$5–10 | ✔ real part, ✘ too weak | Reject: force. The *principle* (self-locking screw, zero hold) carries over to A |
| C | Electropermanent magnet (AlNiCo + NdFeB, coil) clamping on the beam | ~ needs **B ≈ 0.89 T** at a zero-gap 80 mm² pole face for 25 N (B²A/2μ0). Any air gap (gib play) kills it. **Works only on O1**; 1.4301 is ~non-magnetic | ≥ 10 × 10 × 8 mm + pole shoes; smallest catalogue unit (Zubax FluxGrip FG40) is 41 × 41 × 22 mm | ~50–200 mJ in a 2–10 A, ~1 ms pulse **[EST]** | 0 | custom coil; high-current H-bridge + capacitor bank; no LCSC module | sharp click; magnetic snap | slider pulled sideways onto the beam; the clamp load goes through the **Z datum pads** (sets the sensor gaps) and the back cover (known defect) | ✘ magnetic snap-down moves the slider by its gib play (tens of µm) | ✘✘ 0.9 T driven into an O1 beam 2 mm behind the tape; leaves **remanent patches in hardened O1** (≈ 7.6 mT at 10 mm from a 160 mm³, 0.3 T patch [EST]) ≥ the ±5 mT spec; patches vary along the beam, collect swarf | custom | ✘ no small catalogue part; OpenGrab v3 discontinued | Reject |
| D | Latching (bistable, permanent-magnet) solenoid driving a brake lever | ~ latched holding force of miniature units ~2–6 N **[UNVERIFIED]**; needs a ×5 lever and a spring | 8–12 mm Ø × 15–20 mm (GEEPLUS T1L-0420 / T1L-0742; Weilong WL0837, 3.6 V min) **[UNVERIFIED]** | ~0.1–0.2 J (0.5–1 A × 20–50 ms) **[EST]** | 0 at the end positions | reversing pulse: DRV8830 or DRV8837 OK | ✘ loud click; impact jolts the slider | lever pad as A | ~ the impact can shift the jaw several µm **[EST]** | ~ open-frame magnet, ~1–5 mT at 10 mm **[EST]**; acceptable only ≥ 20 mm from the AS5311 | ~$5–15 | ✔ real parts, few at ≤ 3.6 V | Possible, but noisier and less certain than A |
| E | SMA (Flexinol) wires + bistable over-centre toggle (one wire to lock, one to unlock) | ~ 0.15 mm wire pulls 3.2 N (330 gf). 25 N needs ~10:1 toggle advantage near dead centre → tolerance and wear sensitive | 30–40 mm of wire along u (≈ 1 mm stroke at 3 %), very thin; < 1 g | ≈ 0.25 J (0.4 A, ~1.6 Ω, 1 s) | 0 (bistable) | 2 × low-side MOSFET (AO3400A C20917, already in the BOM) + PWM: 2 GPIO or expander | **silent** | as A | ✔ slow, smooth | ✔✔ **no field at all** | ~$5 wire | ✔ Dynalloy Flexinol; 0.4–2 s relax; ~10⁵–10⁶ cycles at ≤ 3–4 % strain **[UNVERIFIED]** | **Runner-up**; best if the O1/magnet worry dominates |
| F | Micro gearmotor + over-centre eccentric cam (variant of A) | ✔ deterministic (fixed throw × spring rate), 0.5 turn, ≈ 0.6 s | cam axis must be ⟂ y → motor along u: needs 25 mm along u in the y 21–28 band (the battery's and antenna's space) | ≈ 0.15 J | 0 (over-centre against a stop) | DRV8830 | soft | as A | as A | as A | as A | as A | Better kinematics, worse packaging; rev C option |
| G | Piezo (PiezoMotor LEGS LL06 driving the pad, or a stick-slip clamp) | ~ 6.5 N stall, holding ≈ 7 N unpowered **[UNVERIFIED]** → still needs leverage | LL06 ≈ 22 × 11 × 19 mm, 16 g | small (mJ) | 0 | ~42 V 4-phase driver (PMD-series) or a custom HV inverter; nothing at LCSC | ultrasonic hiss | as A | ✔ | ✔ none | ✘ ~$300–600 **[UNVERIFIED]** | real, niche | Reject: cost, size, HV |
| H | Electroadhesion pad | ✘ ~1–10 kPa shear → < 5 N on the available 20 × 60 mm | thin film | ~0; charge leaks, so it must be refreshed → **not zero-power** | ✘ | 1–5 kV converter | silent | dielectric on the ground face | – | ✘ kV next to the capacitive scale (4 cm away), ESD risk to the AS5311 | – | lab | Reject |
| I | Magnetorheological fluid brake | ✔ in principle | needs a sealed fluid gap on the beam | – | ✘ coil current to hold, or a PM bias that keeps a field on the beam | coil driver | – | ✘ iron-loaded fluid on the ground beam and **on the magnetic tape** | – | ✘ | – | – | Reject |
| J | Spring-applied, electrically released brake (power-off brake) | ✔ | – | – | ✘ draws current whenever *unlocked*, i.e. during all use | – | – | – | – | ~ coil field | – | – | Reject (power inverted) |

---

## 3. Recommendation: the motorised lock screw (A)

### 3.1 Concept sketch

Section in the u–y plane at the lock bore (looking along −z, from the display side). Today the same bore carries the
manual M3 thumb screw (`LOCK_U`, `LOCK_BORE_D` in params.py).

```
 y 49.2 ──────────────┬───────┬────────────  housing top face
                      │ cap / │  <- removable cap: manual override (1.5 mm hex
                      │ clip  │     on the motor-to-screw coupler, see 3.6)
                      ├───────┤
                      │ MOTOR │  Ø6 coreless/iron-core DC motor  (magnet ≈ here,
                      │  (M)  │   ≥ 30 mm above the tape)
                      │ ───── │
                      │ GEAR- │  700:1 planetary, plastic
                      │ BOX   │
                      ├──┬┬───┤  <- output shaft + coupler (hex socket)
                      │  ││   │  <- PTFE thrust washer (collar), screw is axially fixed
                      │  ││   │     M2 x 0.4 lead screw (stainless A2 or brass), Ø2
                      │  ││   │     runs under the board's upper band (z ≈ -2.5)
 y 34 ── board top ── │  ││   │ ──────────────────
                      │ ┌┴┴┐  │  <- travelling nut (brass, square, keyed in the bore:
                      │ │NUT│ │     no rotation, slides in y)  stop shoulders at both ends
                      │ └┬┬┘  │
                      │ ▒▒▒▒  │  <- spring stack, ~100 N/mm (2-3 miniature disc springs
                      │ ▒▒▒▒  │     OD ≤ 4 mm, or a machined flexure)  0.25 mm compressed = 25 N
                      │ ┌──┐  │
                      │ │PAD│ │  <- brass pad, Ø3, guided in y, 0.20 mm clear of the gib when unlocked
 y 21.2 ──────────────┴─┴──┴──┴───────────  Y gib (brass 1.0 thick, spring plungers each side)
 y 20.0 ═══════════════════════════════════  beam UPPER edge (ground)
          beam 20 x 4  (O1 or 1.4301)        tape channel y 1.9…10.1 is on the FRONT face,
                                               ≥ 10 mm below this edge
 y  0.0 ═══════════════════════════════════  beam LOWER edge = reference edge E
 y -1.0 ───────────────────────────────────  brass reference strip  (reaction side)
```

Load path when locked: nut → spring → pad → Y gib → upper edge → beam → edge E → reference strip → lower rail →
housing side walls → bore → thrust washer → screw. The loop is closed in **y only**. It does not pass through the
four front pads that set both sensor gaps (z), and it doesn't load the back cover, which has the open bending
defect.

### 3.2 Force and torque

* **Clamp:** N = k × δ = 100 N/mm × 0.25 mm = **25 N** at the nut's end stop. The force is set by geometry, not by
  motor torque. Stack tolerance ±0.05 mm gives **±5 N (20–30 N)**. A softer 40 N/mm spring halves the tolerance
  sensitivity but adds 0.4 mm of stroke (≈ 1 turn, +1.2 s).
* **Hold:** ΔF = 2μN = **6.0 / 7.5 / 10 N** at μ 0.12 / 0.15 / 0.20, on top of the 2.5–8 N free friction (§1 table).
* **Self-locking:** M2 × 0.4, d_m ≈ 1.74 mm, lead angle λ = atan(0.4 / π d_m) = **4.2°**. The thread holds if
  tan λ (0.073) < μ / cos 30°. That holds for μ ≥ 0.064, so it is self-locking from μ_thread 0.08 (well-greased)
  upward. On top of that, the PTFE collar adds back-drive friction and a 700:1 plastic planetary barely back-drives.
  **Holding power = 0.**
* **Drive torque at full load** (25 N): T_thread = N·(d_m/2)·(tan λ + μ/cos β)/(1 − tan λ·μ/cos β). With
  μ = 0.08 / 0.15 / 0.20 this is 3.6 / 5.4 / 6.7 mN·m. The collar adds 25 N × 0.08 × 1.25 mm = 2.5 mN·m. **Total:
  6.1 / 7.9 / 9.2 mN·m.**
* **Motor: Pololu #2359**, 700:1 sub-micro plastic planetary, 6 × 21 mm. Rated at 6 V: stall 12 oz·in
  (85 mN·m), 400 mA, 90 rpm free (Pololu). Stall torque, stall current and speed scale ≈ linearly with voltage.
  Pololu's gearbox guidance: ≤ 3.5 oz·in (**24.7 mN·m**) instantaneous, continuous load ≤ 20–30 % of stall.

  | DRV8830 VSET | stall torque | stall current | free speed | use |
  |---|---|---|---|---|
  | 3.29 V (0x29) | 46.6 mN·m | 220 mA | 50 rpm | main stroke: 9.2 mN·m worst = 20 % of stall ✔ |
  | 1.60 V (0x14) | 22.6 mN·m | 107 mA | 24 rpm | last ~0.1 turn into both end stops: stall ≤ 24.7 mN·m, gearbox-safe ✔ |
  | 0.96 V (0x0C) | 14.1 mN·m | 67 mA | 15 rpm | homing after an unknown state (full-travel time-out) |

* **Stroke and time:** 0.20 mm clearance + 0.25 mm compression = 0.45 mm = **1.13 turns**. 0.5 turn free at
  ~50 rpm (0.6 s) + 0.53 turn loaded at ~42 rpm (0.75 s) + 0.1 turn at 1.6 V (~0.4 s) ≈ **1.8–2.0 s**. Unlock is
  about the same (the spring helps at first, then the nut runs free).
* **Energy:** ≈ 3.3 V × 65 mA × 1.6 s + 1.6 V × 0.1 A × 0.3 s ≈ **0.35–0.4 J** from VSYS per action
  (I0 of the motor [UNVERIFIED], taken as 30 mA). At 50 lock/unlock pairs a day that's ≈ 40 J ≈ 3 mAh/day,
  about 0.6 % of the cell per day. **Peak current ≈ 0.22 A** (stall at 3.3 V), within the TPS63802/VSYS headroom
  (the Wi-Fi peaks are 0.5 A).

### 3.3 Effect on the measurement

* **Engagement is normal (y) only.** The pad is guided in y and touches the gib before the spring builds load, so no
  x drag is applied to the slider. The screw's tangential friction is reacted in the bore, not by the pad.
* **Yaw:** the Y loop is already seated by the two Y plungers (≥ 3.5 N each, design 6 N). Extra load at one u
  compresses the strip and rail more at that end. Model [EST]: 5 µm of differential compression over the ~60 mm
  strip baseline in printed PETG gives 83 µrad. The Abbe arm is ≈ 43 mm (AS5311 at y 6, jaw tip at y −37), so the
  jaw tip moves ≈ **3.6 µm**. PA-CF is ~2× stiffer, so ≈ 2 µm. Rev B 6061 (E ≈ 69 GPa) gives < 0.2 µm. With the
  lock at mid-strip (u ≈ 39) the yaw term would vanish, but that's the battery's place.
* **Built-in check:** the encoder stays live while locking. Firmware logs the reading change between "before lock"
  and "locked" (0.488 µm resolution) and flags it if > 5 µm. That measures the effect on every unit **(TVP)**.
* **Gaps:** unaffected. The lock loads y only; the z pads and the back gib aren't in the loop.
* **Thermal:** 0.35 J into a 23 g PETG slider is < 0.02 K. Negligible.
* **Creep:** 25 N held for minutes or hours in printed PETG is fine. Days of continuous lock relax the spring
  slightly (PETG creep, mechanical.md §8), which changes force, not position.

### 3.4 Drive circuit (rev B)

```
 VSYS ──┬──────────────┬────────────── DRV8830DGQR (U70, MSOP-10 PowerPAD, LCSC C127591)
        │              │  VCC (pin 1)   2.75–6.8 V, sleep 0.3 µA typ / 1 µA max (25 °C, 5 V)
       10µF          0.1µF
        │              │               OUT1 ──┬──── M+   ┐
       GND            GND              OUT2 ──┼──── M−   ┘ Pololu #2359 (2 wires, or JST-SH 2p
                                              │            like J2 (SM02B-SRSS-TB), LCSC no. TVP)
                                           0.1µF X7R across the motor (EMI)
 +3V3 ── 4.7k (existing) ── I2C_SDA (GPIO13) ── SDA       A0, A1 → GND  → addr 0xC0/0xC1 (7-bit 0x60)
 +3V3 ── 4.7k (existing) ── I2C_SCL (GPIO14) ── SCL       (no clash with 0x6A, 0x36, 0x6B)
                                         ISENSE ── R 0.82 Ω 0603 → GND  (ILIMIT = 0.2 V/R ≈ 244 mA)
                                         FAULTn ── NC, or wire-OR onto FG_ALRT_N (open-drain, IO2)
                                         PowerPAD → GND copper
```

* **Why DRV8830:** an I2C H-bridge with a **voltage-regulating PWM** (VSET DAC 0.48 V up in ≈ 0.08 V steps (Table 1; 0x0C = 0.96 V, 0x14 = 1.60 V, 0x29 = 3.29 V; the datasheet formula
  4 × VREF × (VSET+1)/64 does not match its own table exactly: use the table). Motor speed and torque don't depend on the battery state, which also gives the
  gearbox-safe low-voltage end approach. Current limit = 200 mV / R_ISENSE, R < 1 Ω. A limit held for 275 ms sets
  the FAULT and ILIMIT register bits, but **the bridge keeps running**: firmware must stop it. Sleep happens when
  IN1 = IN2 = 0. R_DS(on) HS + LS ≈ 0.5 Ω. All from TI SLVSAB2G (extracted from the PDF).
* The 0.82 Ω limit (244 mA) sits just above the motor's 3.3 V stall current (220 mA). It's a short-circuit and
  jam guard only. End stops are detected by time, not current, because the stall current at the low end-approach
  voltage is under the 200 mA minimum limit.
* **Sleep budget:** +0.3 µA typ (≤ 1 µA). The SPEC §3 estimate goes from ≈ 38 to ≈ 38.3–39 µA, still ≤ 40 µA (figures updated on 2026-11-10 for the
  LSM6DSO; they were 33 / 35). That
  is tight, so measure it **(TVP)**.
* **Alternative with GPIO:** DRV8837DSGR (LCSC **C39159**, already in the dial-me-spinner library) needs IN1, IN2
  and nSLEEP. There are no free pins, so that means a **TCA9534PWR** I2C expander (LCSC **C783615**, 0x20–0x27)
  as well. Two parts instead of one, no regulated motor voltage, and speed changes with VSYS. Only worth it if the
  expander is wanted anyway, for example for end-stop switches or more I/O.
* **Reusing a line instead:** the only plausible donors are the **8 CAP_TX lines** (the capacitive scale is
  experimental and DNP-able through R60–R67). Taking CAP_TX6/7 (GPIO43/44) for IN1/IN2 kills the 8-phase
  experiment. Not recommended while the experiment is alive. The I2C driver avoids the question entirely.

### 3.5 Magnetic interference analysis

**What the sensor tolerates** (AS5311 datasheet, extracted from the Infineon/ams PDF):

* Bpk 10–40 mT required (vertical field at the die). Yellow range ≈ 3.4–54.5 mT.
* **B_off: constant magnetic stray field ±5 mT.**
* "Magnetic input field variation, including offset gradient: ±2 %".
* Recommended magnet: plastic- or rubber-bonded ferrite or NdFeB, pole length 1.0 mm.

**Tape coercivity:** I found no number for the ams/2 mm-pole-pair strip **[UNVERIFIED]**. Hutchinson's bonded
magnetic elastomer rings quote 240 kA/m (H-type not stated). Bonded strontium/barium ferrite tapes are typically
HcJ ≈ 200–280 kA/m, so μ0·HcJ ≈ 250–350 mT **[EST]**. Bonded NdFeB is higher. Irreversible loss in bonded ferrite
starts at a reverse field around ~0.3–0.5 HcJ **[EST]**, so a field of ≳ 75–100 mT is needed to damage the tape.

**Field from the recommended actuator.** Upper bound: treat the motor magnet as a bare NdFeB dipole, Ø4 × 5 mm,
Br 1.2 T (m = Br V/μ0 = 0.06 A·m²), on-axis B = (μ0/4π)·2m/r³. The real magnet sits inside a steel can that
returns most of the flux, so the true field is lower by an unknown factor **(TVP)**.

| Point | Distance | Upper-bound B | Limit | Margin |
|---|---|---|---|---|
| Tape directly under the lock (y ≤ 10.1 vs magnet y ≈ 40) | ≈ 30 mm | **0.44 mT** | ~75 mT damage; ±5 mT if it were at the head | > 150× (damage) |
| AS5311 die (u 39, y 6 vs u ≈ 66, y ≈ 40) | ≈ 44 mm | **0.14 mT** | ±5 mT constant offset | 35× |
| Gradient across the AS5311's Hall array (~2 mm) | – | ≈ 3B/r × 2 mm ≈ 0.02 mT | ±2 % of 10–40 mT = 0.2–0.8 mT | > 10× |

* The motor moves **with** the slider, so at the AS5311 its field is a **constant** offset. That is exactly the kind
  of field B_off covers. It doesn't vary along the beam, so it doesn't add non-linearity.
* **Ferrous parts:** a steel screw or can more than 10 mm from the tape has no effect on the tape's field. The
  2 mm-pitch field decays as e^(−2π d / 2 mm), ≈ e^(−31) at 10 mm. Use a **brass pad** and an A2 or brass screw
  anyway.
* **O1 beam:** a sub-mT field can't usefully magnetise hardened O1 (Hc of the order of a few kA/m **[EST]**, i.e.
  ≳ 5 mT). No remanence is left along the beam.
* **Motor current while running:** 65 mA through a tiny coil makes µT-level fields. Freeze the reading and pause the
  capacitive burst during the ~2 s stroke (DRV8830 PWM noise vs. the 5 kHz cap measurement).
* **Contrast with the EPM (C):** 25 N needs ≈ 0.89 T at the pole face, driven into the beam. On O1 that flux
  spreads through 4 mm of steel with the tape 2 mm above the back face. A remanent patch left in hardened O1 is
  estimated at ≈ 7.6 mT at 10 mm (0.3 T patch, 160 mm³ dipole) **[EST]**. That exceeds B_off, varies along the
  beam, and attracts chips. On 1.4301 the EPM holds nothing.
* **Built-in gaussmeter:** the AS5311's 12-bit magnitude word (M11:M0, SSI) and MagINC/MagDEC show any field
  change. Bring-up test: log MAG with the motor fitted and removed, and running and idle, over the full travel on
  both beam materials **(TVP)**.

### 3.6 UX and firmware

* **States:** UNLOCKED → LOCKING → LOCKED → UNLOCKING, plus UNKNOWN (after a brown-out or reset with no record).
  Persist the state in RTC memory and NVS. On UNKNOWN, home by running "unlock" at VSET 0.96 V for the full-travel
  time-out (stall-safe).
* **Lock:** HOLD press freezes the display at once (existing HOLD behaviour), then locks. A setting chooses
  "HOLD = freeze + lock" or "long-press HOLD = lock", because HOLD/SEND is already dual-use. The display shows a
  padlock icon, animated while moving and solid when locked.
* **Unlock:** any button press, or a **push on the slider** detected by the encoder. Brass pads are stiff, so a
  push below the hold force shows up only as a few µm of elastic movement. Trigger on > 10 µm sustained 100 ms, or
  any PCNT count beyond ±2 pole edges (slip). Then beep, unlock, and keep the frozen value on screen. The IMU
  detects pickup and orientation, not a slider push. It can still wake the MCU, which then re-checks the encoder.
* **Sleep:** the lock persists through deep sleep (zero hold power). The AS5311 is unpowered in sleep (SNS rail
  off), so push-to-unlock works only while awake.
* **Low battery:** refuse to lock below VSYS 3.5 V, and **auto-unlock before the low-battery shutdown**, so the
  caliper is never stranded locked with a flat cell.
* **Manual override:** a removable top cap gives access to a 1.5 mm hex in the motor-to-screw coupler. Back-driving
  through the gearbox is not an option. This replaces the manual M3 lock's function if the lock jams or the cell
  is dead.
* **Stop control:** time-based profile per stroke (VSET 3.29 V, then 1.6 V for the last 0.4 s), with a total
  time-out of 1.5× nominal. Clear the DRV8830 FAULT after every stroke and read it. ILIMIT set means a jam: stop,
  report, retry once at the homing voltage. Never stall at > 1.6 V for more than 100 ms.

---

## 4. Runner-up detail: SMA + bistable toggle (E)

Pick this if field-free matters more than speed and simplicity, for example if the O1 tape tests show the AS5311
is marginal.

* Two 0.15 mm (0.006") Flexinol wires, antagonistic, about 35 mm long along u, on a printed toggle: one pulls "over
  centre to lock", the other pulls back. Flexinol table: 330 gf ≈ 3.2 N, ≈ 400 mA, 1 s contraction, 1.2–2 s relax,
  1.3 Ω/in. At ≤ 3 % strain that gives ~1 mm of stroke.
* The toggle has to multiply 3.2 N into 25 N at the pad, which means working within a few degrees of dead centre.
  The final clamp force then becomes very sensitive to the pad gap: a ±0.05 mm tolerance gives several N. A stiff
  spring in series (as in A) still sets the force.
* Drive: two AO3400A low-side MOSFETs (C20917, already in the BOM), PWM from VSYS for ~400 mA. That needs 2 GPIO,
  so a TCA9534 (C783615) expander or a DRV8830 used as two half-bridges. **[EST]** ≈ 0.25 J per action, silent,
  1–3 s per action including cooling.
* Fatigue and creep of the wire attachments (crimps in a printed part) are the risks **(TVP)**.

---

## 5. Rough rev B integration plan

**Space (the hard part).** The motor + screw column needs a **Ø6.5 mm pocket ~22 mm long for the motor** plus a
Ø4 bore down to the Y gib at y 21.2. Today:

* u 29.5–65.5, y 22.4–48 is the battery pocket (antenna rule, SPEC D4).
* u 8.6–24 (+5 mm, no metal) is the antenna.
* u 70.4–78 holds the right tower, and above y 20 the thumb roller (u 74.6, Ø8) and the USB-C plug relief
  (y ≈ 20–33).
* The board's upper band covers u ≤ 70, z 0.15–1.15, in y 20–34.
* The housing top is y 49.2, and the gap between the battery pocket and the tower is only **4.9 mm** (u 65.5–70.4).

Under the board the screw column fits (axis z ≈ −2.5 to −3.2, Ø4). The **motor body** (Ø6) doesn't fit anywhere
without a change. Options, best first:

1. **Shorter cell:** a 30 mm-long cell instead of the 35 mm 402535 (capacity TVP, roughly −15 %). The pocket becomes
   u 29.5–60.5. The motor sits vertical at u ≈ 64, y ≈ 25–47, z ≈ −3.2 (back cover locally pocketed ≈ 1 mm), with
   the screw down to the gib at u 64. That is about where the manual lock screw (u 63) sits now, so the manual M3
   lock and its insert go.
2. **Ø4 mm gearmotor** (generic 4 mm planetary micro gearmotors, 3 V **[UNVERIFIED torque]**) in the existing
   4.9 mm gap at u ≈ 68. Torque likely ≤ 10 mN·m, so either drop N to ~15 N (hold +3.6–6 N) or use a 0.3 mm-pitch
   M1.6 screw. Keeps the cell.
3. **Cam variant (F)** with the motor along u. Needs the y 21–28 band: only if the battery moves up, which the
   49.2 mm top face doesn't allow. Rev C or a new layout.

**Board.** Add U70 DRV8830DGQR plus 4 passives (≈ 6 × 8 mm incl. courtyard) and two motor pads or a JST-SH 2p. Put
them on the top side near the power cluster (x 50.5–61.5, y 2.5–20.5, ≤ 4.2 tall; the MSOP is 1.1 mm). Or in the
upper band if layout frees space. Keep it ≥ 10 mm from U40/RX feed like L1 (SPEC §2.1 rule). Motor leads twisted,
under 30 mm. VCC from VSYS, not +3V3, so the 3V3 rail and its 11 µA Iq path don't see the motor's current.

**GPIO.** None. The driver sits on the existing I2C bus (GPIO13/14) at 0x60. FAULTn is optional, wire-ORed onto
FG_ALRT_N. Update `nets.py`, the SPEC §6 I2C table (add 0x60) and the §3 sleep budget (+0.3 µA typ / 1 µA max).

**Mechanics.**
* Lock column: thrust washer (PTFE) under the coupler.
* Square brass nut keyed in the bore, with end shoulders at the unlocked and locked positions.
* Spring stack (2–3 miniature disc springs, OD ≤ 4 mm, ~100 N/mm **[UNVERIFIED part]**; or a machined 6061 flexure
  in rev B).
* Ø3 brass pad, 0.20 mm clearance to the Y gib.
* Keep the right Y plunger within ±5 mm of the lock so the gib doesn't rock.
* Re-run `clash_check.py` and add the lock to `calcs.py` (force, torque, yaw shift).
* The 6061 body makes the yaw term negligible.

**Firmware.** A `lock` component:
* DRV8830 I2C driver (CONTROL reg: VSET + IN1/IN2; FAULT reg: read and clear).
* Stroke profile with time-outs, and the state machine in §3.6.
* Encoder push-detect while locked, and lock-shift logging.
* Low-battery auto-unlock, homing on UNKNOWN.
* Display icon, BLE/GATT lock state characteristic, settings for "HOLD locks".

**Bring-up tests (TVP).**
1. Hold force with a push-pull gauge on oiled O1 and on 1.4301: ≥ 10 N.
2. Lock-induced jaw shift: logged by firmware, and checked with a gauge block + dial indicator. ≤ 2 µm (rev B),
   ≤ 5 µm (rev A).
3. AS5311 MAG word and MagINC/MagDEC with and without the motor, idle and running, full travel, both beams.
4. 10,000 lock cycles: force retention, gearbox wear, pad and gib marking.
5. Deep-sleep current with U70 fitted.
6. Lock time at VSYS 3.0 and 4.4 V (should be the same thanks to VSET).
7. Self-lock under 2 h of vibration or a drop: the clamp must not loosen.

---

## 6. What I could not verify

* Pololu #2359: no-load current, mass, shaft details, magnet type, can shielding, actual stray field. Only the
  6 V stall/speed/current and the 3.5 oz·in gearbox guidance are from Pololu pages.
* The magnetic tape's coercivity, which isn't published for the ams strip (bonded-ferrite typical values used).
* The external field of any specific micromotor or latching solenoid (the dipole upper bound used is conservative).
* Latching solenoid holding forces and 3 V availability (aggregator listings only; GEEPLUS/TLX datasheets not read).
* PiezoMotor LL06 holding force (≈ 10 % above the 6.5 N stall per the vendor's definition) and price.
* Miniature disc-spring part numbers at OD ≤ 4 mm and 100 N/mm.
* EPM pulse energy and size (no small catalogue part found; the estimates are mine).
* Hardened O1 coercivity / remanence (order-of-magnitude estimate).
* Live LCSC stock: C127591 (DRV8830DGQR) showed conflicting stock across two LCSC pages. C783615 (TCA9534PWR) was
  in stock at search time. C39159 and C20917 are taken from the projects' own files.

## Sources

* AS5311 datasheet (magnetic input table, Boff ±5 mT, Bpk 10–40 mT): https://www.infineon.com/assets/row/public/documents/24/49/infineon-as5311-datasheet-en.pdf
* DRV8830 datasheet SLVSAB2G (VSET, ILIMIT 200 mV/R, 275 ms fault, sleep 0.3/1 µA, addresses): https://www.ti.com/lit/ds/symlink/drv8830.pdf
* DRV8830DGQR at LCSC (C127591): https://www.lcsc.com/product-detail/C127591.html
* TCA9534PWR at LCSC (C783615): https://www.lcsc.com/product-detail/C783615.html
* Pololu 700:1 sub-micro plastic planetary gearmotor #2359 (specs and gearbox torque FAQ): https://www.pololu.com/product/2359 , https://www.pololu.com/product/2359/faqs
* Flexinol technical data: https://cdn.robotshop.com/media/d/dyn/rb-dyn-01/pdf/flexinol-technical-data.pdf , https://imagesco.com/nitinol/wire.html
* OpenGrab EPM v3 (discontinued) / Zubax FluxGrip: https://ardupilot.org/copter/docs/common-electro-permanent-magnet-V3.html , https://eu.robotshop.com/products/zubax-zubax-fg401m-electro-permanent-magnetic-gripper-epm
* Latching solenoids (aggregator listings): https://datasheets.globalspec.com/ds/GEEPLUS/model-t1l-0420/80cd6bac-02c1-40c9-80ff-6007d80ea37d , https://www.directindustry.com/prod/weilong-intelligent-technology-dongguan-co-ltd/product-4620622-2851587.html
* PiezoMotor LEGS LL06: https://directindustry.com/prod/piezomotor-ab/product-26742-1994820.html
* Bonded magnetic elastomer coercivity (Hutchinson, 240 kA/m): https://www.directindustry.com/prod/hutchinson/product-157589-2811320.html
* Sister project actuator: `C:\source\tyevco\dial-me-spinner\docs\mechanical.md` §7
