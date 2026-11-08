# Oh, neat: things we might want in the future

A parking lot for ideas that are researched but **not planned for rev A**. Nothing on this page has been built.
Each idea gets a short summary here and a research note beside it.

| Idea | Status | Note |
|---|---|---|
| Electronic slide lock | Researched. Needs a rev B housing change | [slide-lock.md](slide-lock.md) |

## Electronic slide lock

**What:** press HOLD and the slider locks itself on the beam. It unlocks on a button press, or when you push the
slider (the encoder sees it). It holds with zero power, so the lock stays engaged through deep sleep.

**Best candidate:** motorise the existing lock screw. A Ø6 mm 700:1 planetary gearmotor (Pololu #2359) turns a
self-locking M2 × 0.4 lead screw. A keyed nut compresses a stiff spring (~100 N/mm × 0.25 mm = 25 N) onto a brass pad
that presses the brass Y gib against the beam's top edge. That adds 6–10 N of holding friction (≈ 9–18 N total). The
driver is a DRV8830 I2C H-bridge on the existing bus (0x60), so no GPIO is needed, and it adds ≈ 0.3 µA in sleep.
The motor's field at the AS5311 tape is < 0.5 mT (upper bound), against the sensor's ±5 mT stray-field tolerance.
**Rejected:** an electropermanent magnet. It drives ~0.9 T into the beam and can leave magnetised patches in
hardened O1, right under the magnetic tape. Full comparison, calculations and integration plan:
[slide-lock.md](slide-lock.md).

**Blocker:** the motor doesn't fit the current 78 × 52 × 16 mm housing (4.9 mm gap). Rev B needs a 30 mm cell or
a Ø4 mm motor.

### Making it faster

The research design takes **≈ 2 s** per lock or unlock. That's 1.13 turns of the screw (0.20 mm clearance + 0.25 mm
spring compression) at ~42–50 rpm out of the 700:1 gearbox. 2 s is a long time when you're holding a part. Ways to
cut it, roughly best first. The time estimates are scaled from the note's numbers and not verified:

| Lever | How | Estimated time | Cost / risk |
|---|---|---|---|
| **Hide the wait (UX)** | HOLD freezes the reading **instantly**, and the lock runs in the background. You only wait if you let go of the part within 2 s. On unlock, start releasing on the first touch of any button or the first µm of push, before you've finished deciding to move. | feels ~0 s | free; firmware only |
| **Shorter stroke** | Cut the pad clearance from 0.20 to ~0.05 mm (a tighter pad guide; the gib is already seated), and use a stiffer spring (≈ 200 N/mm × 0.125 mm). Stroke 0.45 → ~0.18 mm ≈ 0.45 turn | ≈ 0.8 s | the force becomes more sensitive to stack tolerance (±0.05 mm → ±10 N); needs a shim or set screw at assembly |
| **Unlock only to "off load"** | Unlock just far enough to drop the clamp force (back off the 0.25 mm spring compression), not the full clearance. The pad stays a hair from the gib. | unlock ≈ 0.3–0.6 s | must make sure the pad really clears, or it drags; the encoder can confirm |
| **Lower gear ratio** | 136:1 instead of 700:1 (same Pololu sub-micro family). ~5× the speed, ~1/5 the torque: ≈ 9 mN·m stall at 3.3 V against 6–9 mN·m needed | ≈ 0.3–0.5 s (with the shorter stroke) | marginal torque: needs a well-greased screw (μ ≈ 0.08), a lower clamp (≈ 15–20 N), or a higher VSET. Thread friction alone must then provide the self-lock (λ 4.2° vs friction angle; OK from μ ≥ 0.064) |
| **Higher drive voltage** | DRV8830 VSET up to ~4 V from VSYS (on battery VSYS ≥ 3.0 V limits this) | ~20 % faster | inconsistent near an empty cell; keep the low-voltage end approach that protects the gearbox |
| **Over-centre cam instead of a screw** | the note's variant F: half a turn into a fixed-throw cam against a stop | ≈ 0.6 s at 700:1, ≈ 0.15 s at 136:1 | packaging: the motor must lie along the beam, in the battery/antenna band (rev C) |
| **Latching solenoid** | a bistable solenoid on a lever (note variant D) | ≈ 20–50 ms | loud click, impact can jolt the jaw a few µm, weaker hold; a field near the sensor |

**Recommended direction for rev B:** hide the wait in firmware (free), shorten the stroke to ~0.18 mm, and try the
136:1 gearbox with a greased screw at a ~20 N clamp. That's an estimated **≈ 0.4 s** lock and **≈ 0.3 s** unlock
(to verify on a prototype). Keep the 700:1 as the fallback if the 136:1 can't make the force.
