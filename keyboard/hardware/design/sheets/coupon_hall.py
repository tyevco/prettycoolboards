"""Hall-effect coupon (default slot S1, standard 58 x 60 mm): SPEC §4.8 (its row), §4.9, §6.3, §11 #3 and #21;
concept §2.4 and §7. Every part below is a **candidate** picked for this capture (2026-11-27), not an owner decision;
JLC stock and qty-1 price are the JLC parts API's on 2026-11-27 (re-checked 2026-11-28, below). Captured on
2026-11-27; re-captured on 2026-11-28 for the owner's decisions of 2026-11-27 (SPEC §1), below, and reviewed the same
day (every pinout read again in the datasheets named below; the latch's address rule and the D3 numbers corrected);
not built, not measured.

**The owner's decisions of 2026-11-27 on this coupon** (SPEC §1; risks.md):

* **D1, stage A1.** This coupon is in stage A1 with the motherboard and the test coupon: released, ordered and
  brought up first (SPEC §1, §10).
* **D2, the slot key.** J1 comes from sheets/coupon_common.py: no pin 39 (the keyed 39-pin symbol on the footprint
  without pad 39), DNP for the assembler and fitted by hand after the header's pin 39 is pulled (SPEC §4.2, §11 #31).
  Nothing on this coupon used pin 39 (it was RSV).
* **D3, 100 Ohm at the socket** on CS0_N, CS1_N, IRQ_N and G0-G3 (SPEC §4.3). Of those lines this coupon uses
  G0-G3 (CS0_N, CS1_N and IRQ_N are open here; its G4 and G5 are U_EXP3's slow lines on S1-S4, with no resistor, and
  on S5 they would get one too, with the same arithmetic). Behind each resistor here: the header, up to about 61 mm of
  track on the routed board (G3 with its probe pad TP14, 60.5 mm; G0-G2 48-50 mm; about 0.1 pF/mm), a TMUX1208
  select (C_IN 2 pF max, SCDS389C) and an SN74HC259 input (C_i 10 pF max, SCLS134F), about 20 pF in all: tau = 2 ns,
  against the mux's 25 ns maximum transition time at 3.3 V (tTRAN, SCDS389C §7.6; 33 ns is the 5 V table's) and
  the descriptor's 1 us select settle; the 100 k pull-down's 33 uA drops 3.3 mV across the 100 Ohm (*estimates*;
  corrected by the review of 2026-11-28, which first read 45 mm and 33 ns). No change here.
* **D5, the coupons' via rule** (0.60 / 0.30 mm) is boards/coupon_common.RULES, which this coupon uses. D4, D6 and
  D7 change nothing on this coupon (D6's ordering banner is release.py's).

**Risk register SE-2 and SE-4** (risks.md; the board's answer to each, *estimates* from the register's own models):

* **SE-2, the references sit closer to the keys than the key pitch.** REF1 and REF2 are 17.3 mm from two keys each (K1
  and K3, K2 and K4). With the register's field model (an exact cylinder model of a 4 x 2 mm NdFeB at Br 1.25 T, 6.3
  mm from the Hall element at rest, risks.md SE-1), a press to the 4 mm stop moves the nearer reference's Bz by -205
  uT, 8 x the sensor's 25.8 uT rms, and the farther one by -8 uT. A key's row or column neighbour moves by -137 uT and
  its diagonal by -28 uT, so the keys' own readings need the same correction. No place on this 58 x 60 mm outline is
  far from every key: the best, the lower corners beside the header at about (3, 12) and (55, 12), gives -73 uT from
  one key (2.8 x), but sits 24 mm nearer the slot edge than the key block's centre line, among the slot's own
  currents, so it would read a different stray field from the keys'; the block's centre (H14) would read -569 uT from
  all four. **The references stay** (a trade-off, an open owner item), and the firmware rule of SE-2 applies: update a
  reference's common mode only while every key reads at rest, or subtract a calibrated 4 x 6 crosstalk matrix. The
  all-on mode reads all six sensors every frame, so the matrix is one press per key (SE-2's test, SPEC §10 step 8).
* **SE-4, the ADC lane, not the sensor, sets the noise figure.** **Handled on AN0**: SEL 6 and 7 (TEMP1, TEMP2) put
  the two thermistor taps through the same mux, buffer U12A, R18 and lane in every frame, in both modes, and each tap
  is a quiet source near mid-scale (1.65 V at 25 C, 1.35 V at 35 C). Behind its 1 uF a tap's kT/C noise is 64 nV;
  U12A's 4.5 nV/rtHz (SBOS365G) over the lane's 2.3 MHz pole (22 + 47 Ohm into 1 nF) adds 8.6 uV rms; together about
  9 uV rms, against the ADC's 233-464 uV rms (DS13543 Table 99, SNR 68-74 dB: 1.2-2.3 LSB, 31-62 uT at the BA4's
  7.5 mV/mT), under 0.2 % of the floor's variance. A tap filtered at 32 Hz does not carry the slot rail's noise,
  which a ratiometric sensor shares with VREF+: about 30 uV rms at mid-scale (half the LDL1117's 60 uV rms, JLC
  listing), about 2 % of the ADC's variance. Both taps follow REF2 and TEMP1 in the walk, not a key, so a press does
  not reach them through the mux's charge sharing (85 uV per volt of difference into 1 uF, 5 ms to recover). So the
  floor is measured through the same lane in every run, as SE-4 asks. **AN1 (K1 direct) has no floor source of its
  own**: with K1 gated off, R20 holds U12B's input at 0 V, at the bottom of the ADC's range and of the buffer's swing
  (its offset is 200 uV max, 1 LSB), where the ADC's noise clips; AN1's floor is AN0's by proxy (the same op-amp
  package, the neighbouring pin, PC1 against PC0). A mid-supply pull in place of R20 (1 M to +3V3 and 1 M to GND:
  500 kOhm at 1.65 V, 29 uV rms kT/C into 5 pF) would give AN1 a floor while K1 is off, but hide K1's turn-on step
  from 0 V, which that lane is for: an open owner item. The sensor's own share of the variance: its 25.8 uT rms
  (BN 0.17 mTpp / 6.6, SBASAI5E) is 193 uV on the BA4, 15-41 % of what the lane measures; on the BA3 (15 mV/mT) it
  would be 41-73 %, but the BA3 saturates at 80 mT, below the concept magnet's 95 mT stop (83-102 mT across
  tolerances, risks.md SE-3): the fixture's magnet and gap (not chosen) set that trade.

What it carries (the coupon's design decides what SPEC §4.8 leaves open; these are this capture's proposals):

* **Four keys** K1-K4 on a 19.05 mm grid (2 x 2), a TMAG5253 under each key's centre, where the magnet in the stem's
  pole sits (concept §7); the positions are in boards/coupon_hall.py. A printed key fixture (keyboard/hardware/
  mechanical) holds the stems; any key can take the compliant stop of an aftertouch site, the electronics are the same.
* **Two reference sensors** REF1, REF2 with no key (the same part), about 17 mm beside the key block: offset drift and
  stray field (and the keys' crosstalk at that distance) to subtract, as common mode only while every key is at rest
  (SE-2 above).
* **Two NTC thermistors**, TH10 beside K1's sensor and TH11 beside REF1's, for the temperature correction.
* **One 8:1 analog mux** (U10) on lane AN0 behind a unity-gain buffer, so the six sensors and two thermistors share
  one lane: the shared-bus topology of SPEC §4.8 at its full depth of eight sites per lane.
* **An enable latch** (U11) that either keeps every sensor on (8 kHz: "at 8 kHz the sensors stay on behind an analog
  mux", SPEC §4.8, §6.3) or turns on only the selected one (1 kHz: enable-gating, the lower-current mode).
* **A direct buffered lane** AN1 for K1 alone, so the same key is read with and without the mux: the mux's own
  effect (settling, charge injection, crosstalk, noise) and, in the gated mode, K1's turn-on transient at the full
  scan rate (tON to 14 bits: SPEC §6.3, §10 step 3, §11 #3).
* **An unbuffered option** on AN2 (R26, 0 Ohm, **not fitted**): fitted, the mux output also drives lane AN2's
  47 Ohm + 1 nF directly, the "lane source drive" experiment of SPEC §11 #21, side by side with the buffered AN0.

**The lane source (SPEC §4.3, §4.9, §11 #21).** SPEC keeps 1 nF C0G behind 47 Ohm at the MCU pin until a breakout
shows the sensor stable into it, and notes that the 1 nF alone uses the TMAG5253's whole rated load (CLoad 1 nF max,
SBASAI5E §6.3), before the mux, the other sensors and the traces add to it. So this coupon **buffers its lanes**: an
OPA2365 follower drives each lane through 22 Ohm (TI recommends 10-20 Ohm in series for a capacitive load, SBOS365G
§8.3.3; the lane's 47 Ohm + 1 nF follows on the motherboard), and a sensor sees only the mux, a buffer input and the
traces, about 0.1 nF (*estimate*: TMUX1208 drain capacitance 85 pF in JLC's listing, op-amp 4 pF, traces). The
coupon therefore works with either lane capacitor (1 nF or 680 pF) and changes nothing on the motherboard.
Declared R_src (descriptor): 22 Ohm + the buffer's closed-loop output impedance (*estimate* < 1 Ohm at DC), so the
lane settles with tau = (22 + 47) Ohm x 1 nF = 69 ns, 0.72 us to half an LSB at 14 bits (*estimate*); the ADC's
5 pF kickback recovers through the same 69 Ohm (about 1 LSB left after a 12-cycle t_s at 40 MHz, 0.06 LSB after 20
cycles: *estimate*, SPEC §6.3's method). The OPA2365 is a zero-crossover part: a TLV906x-class RRIO op-amp has an
input-pair transition at (V+) - 1.4 V to (V+) - 0.8 V (TLV9064 SBOS839N §7.3.1), 1.9-2.5 V here, in the middle of a
key's travel (1.75-2.66 V for the BA4 at the concept's 12-135 mT, *estimate*), where its offset steps; the bottom-out
knee would sit on that step.

**Modes (G-lines, SPEC §4.8: G0-G2 = SEL[2:0], G3 = SEL_EN, all off when low).** G0-G2 drive the mux address A0-A2
and the latch address S0-S2, G3 the mux EN and the latch data D, G4 the latch G (enable, active low) and G5 the latch
CLR (active low). SN74HC259 function table (SCLS134F Table 7-1): CLR H / G L = addressable latch, H / H = memory,
L / L = 8-line demultiplexer (addressed Q = D, the others low), L / H = clear.

| Mode | G5 (CLR) | G4 (G) | Sensors | Use |
|---|---|---|---|---|
| Off (power-up: every G-line pulled down) | L | L | none (G3 low) | the default; about 9.6 mA (the buffers), *estimate* |
| Gated | L | L | only the one SEL addresses, while G3 is high | 1 kHz: SEL = k and G3 high turn on sensor k and mux channel k together; wait tON (20 us typ, 45 us max, to 5 % only) plus the settling to 14 bits that bring-up measures |
| All-on, set up | H | L | each address written with G3 high latches its Q high | walk SEL 0-5 with G3 high: every address a changing SEL passes through on the way is also set high, or is Q6/Q7 (not connected), so the result is all six on |
| Subset, set up | H | H, pulsed L | the Q addressed while G4 is low takes G3 | for each k: SEL = k and G3 = bit k with G4 high, then G4 low and back high. TI: "G should be held high (inactive) while the address lines are changing" (SCLS134F §7.3), else a passing address takes D |
| All-on, run | H | H | Q0-Q5 held | 8 kHz: the latch ignores SEL and G3, which now only walk the mux |
| Clear | L | H | none | back to Off (then G4 low) |

The subset row is the review's correction of 2026-11-28: this docstring first offered "write any subset" with G4 held
low, which TI's address rule forbids. On S1-S4 G4 is a slow expander line, so a subset costs two expander writes per
address; the all-on walk needs none.

On S1-S4, G4 and G5 are slow lines on the motherboard's expander U_EXP3 (SPEC §4.3): fine, they only set the mode.
Every G-line has a 100 k pull-down here (S5 drives G4/G5 straight from the MCU, with no pull-down on the motherboard),
so an undriven line (an MCU pin still in its reset state after an NRST with the slot rails on, SPEC §3.5) leaves
everything off. The SN74HC259 has no I_off: like every coupon it relies on the firmware rule of SPEC §3.5 (drive
every line into an unpowered slot low) not to be back-powered through its inputs. The TMUX1208's logic inputs are
fail-safe (SCDS389C §1). SN74HC259 at 3.3 V: TI specifies V_IH at 2 / 4.5 / 6 V only (1.5 / 3.15 / 4.2 V); about
2.4 V at 3.3 V by interpolation (*estimate*), under the MCU's and the TCA9535's 3.3 V outputs.

**Mux map (U10 S1-S8 = SEL 0-7) and latch map (U11 Q0-Q5):** SEL 0 K1 (U20), 1 K2 (U21), 2 K3 (U22), 3 K4 (U23),
4 REF1 (U24), 5 REF2 (U25), 6 TEMP1 (TH10, at K1), 7 TEMP2 (TH11, at REF1). Q6 and Q7 are not connected.

**Parts (candidates; pinouts read in the datasheets named, symbol and footprint checked pin by pin):**

* **TMAG5253BA4IQDMRR** (TI, LCSC C22452022; 717 at JLC, $0.767), x 6. SBASAI5E (May 2023, revised April 2026,
  SHA-256 e3ddc027..., the copy SPEC §11 cites): X2SON-4 DMR, 1.1 x 1.4 mm. Pins (Figure 5-1, Table 5-1): 1 VCC,
  2 GND, 3 EN (active high: active above V_IH = 0.65 VCC, shutdown below 0.35 VCC, §6.5), 4 OUT, 5 thermal pad "No
  connect. Leave this pin floating or tied to ground. The pin must be soldered" (left unconnected here). Symbol
  generated (KiCad has none). Footprint `Package_SON:Texas_X2SON-4-1EP_1.1x1.4mm_P0.5mm_EP0.8x0.6mm`, checked
  against TI's DMR0004A example land pattern: pads 1/4 at (-0.25 / +0.25, -0.70), 2/3 at (-0.25 / +0.25, +0.70),
  0.22 x 0.40, EP 0.8 x 0.6; KiCad's pads sit at the same pitch, 0.25 x 0.55 at +-0.775 (0.2 mm to the EP, as
  TI's), EP 0.8 x 0.6, paste 0.64 x 0.48 on it. Hall element centred (+-25 um), 130 +- 15 um under the package top,
  package 0.4 mm max (§8.3.2). Positive B (output above VQ = 1.65 V) with a south pole over the marked top (§8.3.1).
  BA4: +-160 mT, 7.5 mV/mT at 3.3 V; the concept's magnet model (12 mT at rest, 95 mT at the 4 mm stop, 135 mT into
  the compliant stop, *estimate*) stays inside it, where a BA3 (+-80 mT, C22401868, 2673 in stock, $0.638, same
  footprint) would saturate near the stop. 2.6 mA typ, 5 mA max at 3.3 V; ROUT 1.27 Ohm on, 9 MOhm off. 100 nF at
  VCC (§9.4: "at least 0.1uF"). K1's OUT has a 1 MOhm pull-down (R20; §9.1.4: "A pulldown resistor can be used to
  pull the output to ground when both the devices are placed in shutdown mode"), so the direct lane AN1 reads about
  0 V while K1 is gated off and shows its turn-on from there. The other outputs reach only the mux, which selects a
  sensor only while it is on, so they need none.
* **TMUX1208PWR** (TI, C494728; 20,822, $0.572), 8:1, 1.08-5.5 V, TSSOP-16. SCDS389C pin functions: 1 A0, 2 EN
  (active high: "When this pin is low, all switches are turned off"), 3 N.C., 4-7 S1-S4, 8 D, 9 S8, 10 S7, 11 S6,
  12 S5, 13 VDD, 14 GND, 15 A2, 16 A1; Table 1: A2..A0 = 000 -> S1 ... 111 -> S8. At 3.3 V: RON 9 Ohm typ (15 max),
  V_IH 1.35 V, charge injection 7 pC, I_D(on) +-200 nA at 25 C (§7.6; 1 mV on a thermistor tap's 5 kOhm,
  0.03 C, *estimate*). Symbol generated: KiCad's `Analog_Switch:TMUX1208PW` extends TMUX1108PW / ADG1408YRUZ
  and calls pin 3 "VSS", which is N.C. on this part. Footprint `Package_SO:TSSOP-16_4.4x5mm_P0.65mm` (TI PW0016A,
  JEDEC MO-153).
* **SN74HC259PWR** (TI, C2652971; 2000, $0.467), 8-bit addressable latch, 2-6 V, TSSOP-16. SCLS134F Figure 4:
  1 S0, 2 S1, 3 S2, 4-7 Q0-Q3, 8 GND, 9-12 Q4-Q7, 13 D, 14 G (active low), 15 CLR (active low), 16 VCC = KiCad
  `74xx:74LS259` (A0-A2, Q0-Q7, D, E, Clr) pin for pin. 100 nF at VCC.
* **OPA2365AIDR** (TI, C130011; 4265, $1.534), dual, 50 MHz, 25 V/us, zero-crossover RRIO, 2.2-5.5 V, 4.6 mA per
  channel typ, SOIC-8. SBOS365G Figure 6-3: 1 OUT A, 2 -IN A, 3 +IN A, 4 V-, 5 +IN B, 6 -IN B, 7 OUT B, 8 V+ =
  KiCad `Amplifier_Operational:Opamp_Dual` units A / B / power. "Stable with a pure capacitive load up to
  approximately 1 nF" at unity gain (§8.3.3). 100 nF at V+.
* **NCP15XH103F03RC** (Murata, C77131; 284,649, $0.0158), NTC 10 kOhm 1 %, B25/50 3380 K, 0402, 1 mW/C dissipation
  (JLC listing). Below a **10 kOhm 0.1 % 25 ppm/K** thin-film resistor (YAGEO RT0603BRD0710KL, C95204; 1.92 M, $0.0235)
  from +3V3: 1.65 V at 25 C, about 31 mV/K there, ratiometric with the lane reference (*estimate*). 0.27 mW in the NTC
  at 25 C: about 0.27 C of self-heating, a constant offset (*estimate*). 1 uF at the tap: the mux's 85 pF drain
  shares its charge with 1 uF (85 uV per volt of difference), refilled through 5 kOhm (tau 5 ms).

**Stock re-checked on 2026-11-28** (JLC parts API, 03:55 UTC, by the review; the parts are unchanged): C22452022 717
($0.768), the BA3 fallback C22401868 5673 ($0.669), C494728 20,766 ($0.573), C2652971 2000 ($0.468), C130011 4260
($1.535), C77131 283,645, C95204 1,834,435, the slot header C25503140 506 ($0.138, hand-fitted), C7562 220,930; the
basic passives (C25092, C26083, C25741, C52923, C1525, C19702, C17168) 3-28 million each. EasyEDA still has no record
of C22452022 (fetched again 03:57 UTC).

Draw on +3V3 (*estimate*): all-on 6 x 2.6 mA + 9.2 mA (buffers) + 0.33 mA (thermistors) = about 25 mA typ
(41 mA max); gated, one sensor on at a time, about 12 mA, of which the buffers are 9.2 mA, so a sensor's own share
is the difference of two readings. Inside the 250 mA coupon rule (SPEC §4.9). +5V is not used.

**Not used:** INJ, SYNC, SPI (SCK, MISO, MOSI, CS0_N, CS1_N), IRQ_N and AN3 (header pins left open). The latency rig
reaches no sensor node on this coupon: the electrical rig path is calibrated on the test coupon.
"""

from sheets import coupon_common as cc
from sheets.parts import R0603, TP, cap, mounting_hole, res, testpoints

POWER_NETS = cc.POWER_NETS
REV = "A"
DATE = "2026-11-28"

DS = {
    "TMAG5253": "https://www.ti.com/lit/ds/symlink/tmag5253.pdf",       # SBASAI5E
    "TMUX1208": "https://www.ti.com/lit/ds/symlink/tmux1208.pdf",       # SCDS389C
    "SN74HC259": "https://www.ti.com/lit/ds/symlink/sn74hc259.pdf",     # SCLS134F
    "OPA2365": "https://www.ti.com/lit/ds/symlink/opa365.pdf",          # SBOS365G
    "NCP15": "https://www.lcsc.com/datasheet/lcsc_datasheet_2304140030_Murata-Electronics-NCP15XH103F03RC_C77131.pdf",
}
FP = {
    "DMR": "Package_SON:Texas_X2SON-4-1EP_1.1x1.4mm_P0.5mm_EP0.8x0.6mm",
    "TSSOP16": "Package_SO:TSSOP-16_4.4x5mm_P0.65mm",
    "SOIC8": "Package_SO:SOIC-8_3.9x4.9mm_P1.27mm",
    "R0402": "Resistor_SMD:R_0402_1005Metric",
    "M2": "MountingHole:MountingHole_2.2mm_M2",
}
HALL = {"MPN": "TMAG5253BA4IQDMRR", "Manufacturer": "Texas Instruments", "LCSC": "C22452022"}
MUX = {"MPN": "TMUX1208PWR", "Manufacturer": "Texas Instruments", "LCSC": "C494728"}
LATCH = {"MPN": "SN74HC259PWR", "Manufacturer": "Texas Instruments", "LCSC": "C2652971"}
OPAMP = {"MPN": "OPA2365AIDR", "Manufacturer": "Texas Instruments", "LCSC": "C130011"}
NTC = {"MPN": "NCP15XH103F03RC", "Manufacturer": "Murata Electronics", "LCSC": "C77131"}
R10K_01 = {"MPN": "RT0603BRD0710KL", "Manufacturer": "YAGEO", "LCSC": "C95204"}

SYMBOLS = [
    dict(name="TMAG5253_DMR", ref="U", footprint=FP["DMR"], datasheet=DS["TMAG5253"],
         description="Low-power linear Hall-effect sensor with enable pin, 1.65-3.6 V, ratiometric analog output, "
                     "high-impedance output in shutdown, X2SON-4 DMR 1.1 x 1.4 mm (thermal pad: no connect)",
         keywords="hall linear magnetic sensor analog enable TI",
         pins=[(1, "VCC", "power_in", "T"), (3, "EN", "input", "L"), (4, "OUT", "tri_state", "R"),
               (5, "EP", "passive", "R"), (2, "GND", "power_in", "B")]),
    dict(name="TMUX1208PW", ref="U", footprint=FP["TSSOP16"], datasheet=DS["TMUX1208"],
         description="8:1 analog multiplexer, 1.08-5.5 V, 5 Ohm at 5 V (9 Ohm typ, 15 max at 3.3 V), fail-safe "
                     "logic, active-high EN, TSSOP-16",
         keywords="analog multiplexer mux 8:1 TI",
         pins=[(4, "S1", "bidirectional", "L"), (5, "S2", "bidirectional", "L"), (6, "S3", "bidirectional", "L"),
               (7, "S4", "bidirectional", "L"), (12, "S5", "bidirectional", "L"),
               (11, "S6", "bidirectional", "L"), (10, "S7", "bidirectional", "L"), (9, "S8", "bidirectional", "L"),
               (8, "D", "bidirectional", "R"), (1, "A0", "input", "R"), (16, "A1", "input", "R"),
               (15, "A2", "input", "R"), (2, "EN", "input", "R"),
               (13, "VDD", "power_in", "T"), (14, "GND", "power_in", "B"), (3, "NC", "passive", "B")]),
]

# Sensor sites: ref, name, mux channel (SEL), latch output, the key it sits under (None = reference)
SENSORS = [("U20", "K1", 0, "Q0", "K1"), ("U21", "K2", 1, "Q1", "K2"), ("U22", "K3", 2, "Q2", "K3"),
           ("U23", "K4", 3, "Q3", "K4"), ("U24", "REF1", 4, "Q4", None), ("U25", "REF2", 5, "Q5", None)]
THERMISTORS = [("TH10", "R16", "C16", "TEMP1", 6, "beside K1's sensor"),
               ("TH11", "R17", "C17", "TEMP2", 7, "beside REF1's sensor")]
FIXTURE_HOLES = ["H10", "H11", "H12", "H13", "H14"]       # M2, positions in boards/coupon_hall.py
UNUSED = ("INJ", "SYNC", "SCK", "MISO", "MOSI", "CS0_N", "CS1_N", "IRQ_N", "AN3")

INTERSHEET = cc.INTERSHEET + [f"HALL_{n}" for _, n, *_ in SENSORS] + [f"EN_{n}" for _, n, *_ in SENSORS]

LANE_R_OUT = 22.0
# The facts the coupon's descriptor will carry once compiler v0 defines its format (SPEC §4.6, §11 #18).
DESCRIPTOR_FACTS = {
    "type": "hall", "rev": REV, "stage": "A1",
    "rails": {"+3V3": "about 25 mA all-on, 12 mA gated, 9.6 mA off (estimates; buffers 9.2 mA)", "+5V": "not used"},
    "lanes": {"AN0": {"source": "U10 mux -> OPA2365 follower -> 22 ohm", "r_src_ohm": LANE_R_OUT,
                      "sites": ["K1", "K2", "K3", "K4", "REF1", "REF2", "TEMP1", "TEMP2"]},
              "AN1": {"source": "K1 direct -> OPA2365 follower -> 22 ohm", "r_src_ohm": LANE_R_OUT, "sites": ["K1"]},
              "AN2": {"source": "mux output unbuffered through R26 (0 ohm, NOT FITTED: open)",
                      "r_src_ohm": "sensor 1.27 + TMUX1208 RON 9 (typ); only if R26 is fitted"},
              "AN3": None},
    "sensor": {"part": "TMAG5253BA4", "range_mT": 160, "sens_mV_per_mT": 7.5, "vq_V": 1.65, "cload_max_nF": 1.0,
               "t_on_us": (20, 45), "polarity": "south pole over the package top: output rises"},
    "thermistor": {"part": "NCP15XH103F03RC", "r25_ohm": 10000, "b25_50_K": 3380,
                   "divider": "10k 0.1 % from +3V3 to the tap, NTC from the tap to GND"},
    "g_lines": {"G0": "SEL0 (mux A0, latch S0)", "G1": "SEL1", "G2": "SEL2",
                "G3": "SEL_EN (mux EN, latch D)", "G4": "latch G (low = transparent)",
                "G5": "latch CLR (low = clear/demux)"},
    "mux_map": {k: n for _, n, k, *_ in SENSORS} | {6: "TEMP1", 7: "TEMP2"},
    "latch_map": {q: n for _, n, _, q, _ in SENSORS},
    "modes": {"off": "G5 L, G4 L, G3 L", "gated": "G5 L, G4 L; SEL = k, G3 H turns on sensor k and mux channel k",
              "all_on": "G5 H, G4 L, G3 H, SEL 0..5, then G4 H; SEL/G3 then walk the mux only",
              "subset": "G5 H; for each k: with G4 H set SEL = k and G3 = bit k, then G4 L and back to H",
              "address_rule": "change SEL only while G4 is H (SCLS134F §7.3), except in the all_on walk, where "
                              "every address passed through is set as well",
              "clear": "G5 L, G4 H"},
    # risks.md SE-2: Bz change in uT at each sensor when one key goes rest -> 4 mm (the register's field model,
    # an estimate); a reference is common mode only while every key reads at rest
    "crosstalk_uT": {"REF1": {"K1": -205, "K2": -8, "K3": -205, "K4": -8},
                     "REF2": {"K1": -8, "K2": -205, "K3": -8, "K4": -205},
                     "key_row_or_column_neighbour": -137, "key_diagonal": -28, "sensor_rms": 25.8},
    # risks.md SE-4: the electronic floor through the same lane in every frame (estimates)
    "floor": {"AN0": {"sites": ["TEMP1", "TEMP2"], "source_uV_rms": 9, "adc_uV_rms": (233, 464)},
              "AN1": None},
}


def sensors_sheet(d):
    d.sheet("sensors", "sensors.kicad_sch", "Hall sensors: four keys, two references")
    for ref, name, sel, q, key in SENSORS:
        where = f"under key {key}" if key else "reference, no key"
        direct = name == "K1"
        d.group(f"{ref} {name}: TMAG5253BA4, {where}",
                f"EN from U11 {q} (latch), OUT to mux S{sel + 1} (SEL {sel})"
                + (" and to the direct buffer U12B (lane AN1).\nR20 1M: AN1 reads 0 V while K1 is gated off "
                   "(SBASAI5E §9.1.4)." if direct else ".") + " Thermal pad: no connect.",
                anchor=ref)
        d.add(ref, "keyboard:TMAG5253_DMR", "TMAG5253BA4", FP["DMR"], datasheet=DS["TMAG5253"],
              pins={"VCC": "+3V3", "GND": "GND", "EN": f"EN_{name}", "OUT": f"HALL_{name}", "EP": None},
              fields=dict(HALL))
        cap(d, f"C{int(ref[1:])}", "100n", "+3V3", "GND", near=f"{ref}.1")
        if direct:
            res(d, "R20", "1M", f"HALL_{name}", "GND")


def frontend_sheet(d):
    d.sheet("frontend", "frontend.kicad_sch", "Mux, enable latch, lane buffers, thermistors")
    d.group("U10 TMUX1208: 8:1 mux onto lane AN0 (SEL = G0-G2, EN = G3)",
            "S1-S6 = K1, K2, K3, K4, REF1, REF2 (SEL 0-5); S7, S8 = the thermistor taps TEMP1, TEMP2 (SEL 6, 7).\n"
            "EN low: every switch off (AN0 undefined). RON 9 Ohm typ at 3.3 V; the buffer's input takes no current.",
            anchor="U10")
    pins = {f"S{sel + 1}": f"HALL_{name}" for _, name, sel, *_ in SENSORS}
    pins.update({"S7": "TEMP1", "S8": "TEMP2", "D": "MUX_D", "A0": "G0", "A1": "G1", "A2": "G2", "EN": "G3",
                 "VDD": "+3V3", "GND": "GND", "NC": None})
    d.add("U10", "keyboard:TMUX1208PW", "TMUX1208PWR", FP["TSSOP16"], datasheet=DS["TMUX1208"], pins=pins,
          fields=dict(MUX))
    cap(d, "C10", "100n", "+3V3", "GND", near="U10.13")
    for th, r, c, net, sel, where in THERMISTORS:
        d.add(r, "Device:R", "10k", R0603, pins={"1": "+3V3", "2": net}, fields=dict(R10K_01),
              description="Thin-film resistor, 10 kOhm, 0.1 %, 25 ppm/K, 0603 (thermistor divider)")
        d.add(th, "Device:Thermistor_NTC", "10k B3380", FP["R0402"], pins={"1": net, "2": "GND"}, fields=dict(NTC),
              datasheet=DS["NCP15"], description=f"NTC thermistor 10 kOhm 1 %, B25/50 3380 K, 0402, {where}")
        cap(d, c, "1u", net, "GND")

    d.group("U12 OPA2365: lane buffers (AN0 = mux, AN1 = K1 direct)",
            "Unity-gain followers, 22 Ohm in series to the slot pin (SBOS365G §8.3.3); the lane's 47 Ohm + 1 nF\n"
            "follow on the motherboard. R26 (0 Ohm, NOT FITTED) puts the mux output straight onto AN2: the unbuffered\n"
            "lane-drive experiment of SPEC §11 #21 (fitted, the selected sensor drives the lane's 1 nF).",
            anchor="U12")
    d.add("U12", "Amplifier_Operational:Opamp_Dual", "OPA2365AIDR", FP["SOIC8"], unit=1, datasheet=DS["OPA2365"],
          pins={"3": "MUX_D", "2": "BUF0", "1": "BUF0"}, fields=dict(OPAMP))
    res(d, "R18", "22", "BUF0", "AN0")
    res(d, "R26", "0R", "MUX_D", "AN2", dnp=True)
    d.add("U12", "Amplifier_Operational:Opamp_Dual", "OPA2365AIDR", FP["SOIC8"], unit=2, datasheet=DS["OPA2365"],
          pins={"5": "HALL_K1", "6": "BUF1", "7": "BUF1"}, fields=dict(OPAMP))
    res(d, "R19", "22", "BUF1", "AN1")

    d.group("U12C: buffer supply", "100n at V+ (pin 8). 4.6 mA per channel typ (SBOS365G).")
    cap(d, "C12", "100n", "+3V3", "GND")
    d.add("U12", "Amplifier_Operational:Opamp_Dual", "OPA2365AIDR", FP["SOIC8"], unit=3, datasheet=DS["OPA2365"],
          pins={"8": "+3V3", "4": "GND"}, fields=dict(OPAMP))

    d.group("U11 SN74HC259: sensor enables (Q0-Q5 = K1, K2, K3, K4, REF1, REF2)",
            "S0-S2 = G0-G2 (SEL), D = G3 (SEL_EN), G = G4, CLR = G5. CLR low + G low: demultiplexer, only the\n"
            "addressed sensor on while G3 is high (gated, 1 kHz). CLR high: write each address with G3 high, then\n"
            "G high holds them all on (8 kHz). CLR low + G high: all off. 100k pull-downs: every G-line low = all off.\n"
            "A subset: set SEL and G3 with G high, then pulse G low (SCLS134F 7.3: G high while the address changes).",
            anchor="U11")
    pins = {f"Q{k}": f"EN_{name}" for _, name, k, *_ in SENSORS}
    pins.update({"Q6": None, "Q7": None, "A0": "G0", "A1": "G1", "A2": "G2", "D": "G3", "E": "G4", "Clr": "G5",
                 "VCC": "+3V3", "GND": "GND"})
    d.add("U11", "74xx:74LS259", "SN74HC259PWR", FP["TSSOP16"], datasheet=DS["SN74HC259"], pins=pins,
          description="8-bit addressable latch, 2-6 V, TSSOP-16", fields=dict(LATCH))
    cap(d, "C11", "100n", "+3V3", "GND", near="U11.16")
    for k in range(6):
        res(d, f"R{10 + k}", "100k", f"G{k}", "GND")

    d.group("Probe pads", "Lanes, the mux output, K1's output and SEL_EN, for a scope at bring-up.")
    testpoints(d, 10, ["AN0", "AN1", "MUX_D", "HALL_K1", "G3"], fp=TP)

    d.group("Key fixture holes", "M2, unplated: the printed key fixture (keyboard/hardware/mechanical) is screwed "
            "here. Positions in boards/coupon_hall.py.")
    for h in FIXTURE_HOLES:
        mounting_hole(d, h, "M2", fp=FP["M2"])


def build(d):
    cc.slot_sheet(d, unused=UNUSED, rails=("+3V3",))
    sensors_sheet(d)
    frontend_sheet(d)
