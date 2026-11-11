# Rev B ideas

A list of directions for a second revision, collected on 2026-11-11 while costing rev A's fabrication. **None of
this is designed, built or measured.** Numbers marked *estimate* are hand estimates from datasheets or from the
[power budget](../architecture.md#_5-power-budget-and-battery-life); every part named here is a candidate to research, not a
choice. Rev A stays as it is: these are inputs for the next board and housing.

The owner's priorities for rev B: **battery life first**, Wi-Fi may go, and other chips are open. The
[electronic slide lock](slide-lock.md) is binned.

## 1. Battery life

Where the charge goes today (architecture §5, *estimates*): awake ≈ 56 mA idle, ≈ 71 mA measuring, of which the
ESP32-S3 is ≈ 25–35 mA, the AS5311 16 mA, the display logic 8 mA and the backlight 5–10 mA. The ESP32 cannot light
sleep while awake, because light sleep stops the PCNT counter that follows the AS5311's A/B pulses
(`main/app_main.c`, the `NO_LIGHT_SLEEP` lock). A typical shop day (30 min measuring) lasts ≈ 3.3 days on the
135 mAh cell.

| Idea | What it buys (*estimate*) | Cost / risk |
|---|---|---|
| **A bigger cell.** The 2026-11-09 slim housing went from a ~500 mAh 402535 to the 135 mAh 501230 | ≈ 3.7× runtime at the same load (the 500 mAh budget gave ≈ 12 days per shop day) | a taller or thicker housing; a middle size (~250–300 mAh) is a trade to study |
| **Keep the position without the main CPU awake.** Read the AS5311's absolute in-pole position over SSI at ~1 kHz and unwrap it (2.0 mm period: below 1 mm of travel per sample, so up to ~1 m/s), from a low-power core or a small MCU, instead of counting A/B pulses with PCNT | lets the main CPU sleep between display and radio work; the CPU's ≈ 25–35 mA could fall to a few mA | the unwrap must never miss a sample while the jaw moves; to prove on the bench. The ESP32-S3's ULP core doing this is unverified |
| **A lower-power position sensor.** The AS5311 draws 16 mA continuously and DigiKey marks it discontinued | the sensor term is the second-largest awake load | candidates to research: TMR (tunnel magnetoresistance) sin/cos bridges on the same 2 mm tape, duty-cycled into the ADC (µA-class averages are claimed for TMR, unverified here); an inductive scale (the method behind commercial "absolute" calipers); or the capacitive scale made to work, which is how coin-cell calipers run for a year |
| **A reflective memory LCD** (Sharp / JDI memory-in-pixel class) instead of the backlit IPS | display logic + backlight ≈ 13–18 mA down to tens of µA; readable in sunlight and always on | fewer colours and pixels: the live graph and go/no-go colours need rethinking. Panel sourcing and its FPC to check |
| **A low-Iq buck-boost** (TPS63900 class, 75 nA Iq) | sleep ≈ 40 → ≈ 24 µA (architecture §5); storage ≈ 4 → ≈ 7 months | it must still supply the radio peaks; see §2 |
| **Standby in firmware** (could ship on rev A) | set down and still for ~20 s: display and backlight off, capacitive scale paused, CPU clock down, counting kept; the 5-minute idle tail before auto-off mostly goes away | needs a few kB in an app slot that is 3 % free |

## 2. Drop Wi-Fi, look at other chips

Wi-Fi costs more than its antenna: its ≈ 0.27 A bursts from the cell set the 2C limit on the cell, the TX cap at
10 dBm, the 3.40 V cut-off and the buck-boost's peak rating (architecture §5, firmware §12.6). Without it, the
peaks fall to BLE's, which makes both a smaller converter and a different cell chemistry easier. What Wi-Fi does
today (the web page, CSV download, MQTT / HTTP POST) would move to the companion app over BLE and to USB MSC.

| Candidate | Why look | What to check |
|---|---|---|
| **Nordic nRF52840 / nRF54L15** (BLE only) | the usual low-power BLE choice: much lower active and sleep currents than the S3, PPI/DPPI lets peripherals work with the CPU asleep, native USB on the nRF52840 | the QDEC peripheral's sample rate (at most ~7.8 kHz) is far too slow for the AS5311's A/B at hand speeds, so it pairs with the SSI-unwrap idea in §1. A firmware port (Zephyr/NCS instead of ESP-IDF, NimBLE → Nordic's stack); module choice with a certified antenna |
| **Espressif ESP32-H2 / ESP32-C6** | stays in ESP-IDF, so most of the firmware ports | the H2 has BLE and 802.15.4 but no Wi-Fi and no USB-OTG; the C6 keeps Wi-Fi. Their active currents are lower than the S3's but still mA-class; check PCNT and light-sleep behaviour |
| **ST STM32WB / STM32WBA** | LPTIM encoder mode and low-power modes | whether the LPTIM can follow the AS5311's edge rate in Stop mode (unverified); toolchain change |

The magnetometer (U61) is also up for review: with the O1 beam 11 mm away its heading may be unusable
([electronics §7.16](../electronics.md#_7-16-compass-iis2mdc-magnetometer-2026-11-10)). Rev A's bring-up decides whether
it stays.

## 3. Mechanics and measurement

* **Hardened jaw faces on both jaws.** The current machined-body drawing (PCC-M-01) has an optional D2/carbide insert pocket in the moving
  jaw only, and the fixed jaw has no drawing. Aluminium faces dent and wear; a lapped 0.005 mm face needs steel.
* **A standard beam size.** 20 × 4 ground stock is not stocked in the US; 3/4 in (19.05 mm) O1 ground flat is, and
  16 mm (5/8 in) is the common caliper size. Check whether the tape pocket and the scale pocket fit a 19.05 mm beam.
* **Depth rod.** Every commercial caliper has one; rev A omits it (mechanical §8).
* **An absolute reading after sleep.** Today, if the jaw moves more than ±1 mm while asleep, the user re-zeros. A
  second track with a different period (a vernier / nonius pair) gives an absolute position over the whole range.
  The magnetic 2.00 mm and capacitive 5.08 mm periods repeat together only every 254 mm, but telling the periods
  apart over 150 mm needs the capacitive phase good to roughly ±0.02 mm (*estimate*), which the experimental scale
  has not shown.
* **Constant measuring force.** A slip-clutch thumb roller (like a micrometer's ratchet) so every reading is taken at
  the same force.
* **Temperature compensation.** The beam and the work expand differently; the IMU and the ESP32 both carry a
  temperature sensor. A firmware correction against a stated reference temperature (6.3 µm per 10 K for the 6061
  body on O1, mechanical §9).
* **Coolant and dust.** A gasketed housing and sealed buttons (an IP rating) for shop use; the magnetic tape
  tolerates coolant better than the capacitive scale.

## 4. Fabrication

Lessons from staging rev A's order (2026-11-10/11, see the [order checklist](../ordering.md)):

* **Relax the PCB rules where the layout allows**: 0.10 mm (4 mil) track/space and 0.20 mm vias push every US fab
  quoted into its premium tier. At ASC Sunstone, 6 mil rules, a 10 mil drill and 1 oz inner copper cut 5 bare
  slider boards from $2,382.60 to $1,264.05 (live online quote, 2026-11-11).
* **Panel-friendly edges**: keep copper ≥ 0.4 mm from any edge that might be V-cut (JLC's rule).
* **Parts with stock in the US** as well as at LCSC: the IIS2MDC and the LSM6DSO showed no confirmed US distributor
  stock on 2026-11-11.
* **One vendor per part family**: there is no single shop for the whole caliper. The natural split is the slider
  PCBA, the scale board, the printed parts, and the metal parts with a job shop for the beam.

## 5. Binned

* **Electronic slide lock** (2026-11-11, owner): not pursued. The research stays in [slide-lock.md](slide-lock.md)
  for reference.
