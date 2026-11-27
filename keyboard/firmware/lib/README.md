# lib: the testbed's pure logic

> **Status (2026-11-27): written and unit-tested on native_sim; no hardware.** The tests prove the code and its
> arithmetic against the datasheets' worked examples, SPEC's figures and `nets.py`'s numbers. They say nothing
> about the parts or the board, which do not exist yet.

Plain C (C11, `stdint`/`stdbool`/`string.h` only, no Zephyr and no I/O) for the decisions the bring-up firmware
and, later, the testbed firmware make. Each module takes numbers in and gives decisions out; the caller does the
I2C and the GPIO.

| Header (`include/tb/`) | What | Rests on |
|---|---|---|
| `rails.h` | the eleven switched rails and their ids (3V3_S1-S5 = 0-4, 5V_S1-S5 = 5-9, 5V_KVM = 10) | SPEC §3.1 |
| `budget.h` | the VSYS budget state machine: USB states, U_CC's report, the rules, shedding S5 first, the override, a bench-supply mode, peak checks for self-test loads | SPEC §3.2, §3.5, §8.4; `nets.vsys_budget` |
| `ina226.h` | INA226 CAL, conversions, configuration, alert limits, the coupon-voltage correction | TI SBOS547 (Eq. 1-4, §7.6.7); Zephyr's `ina226.c` CAL formula |
| `tusb320.h` | U_CC's DEVICE_ID, attach state, current mode, the INTERRUPT_STATUS clear, and a write guard | TI SLLSEQ8D Tables 7-12; SPEC §8.4's never-write list |
| `desc.h` | the coupon descriptor, **format 1.0, a proposal** (SPEC §4.6 leaves the format to compiler v0, §11 #18): parse, encode, CRC-16/CCITT-FALSE, slot rules, and the test coupon's descriptor | SPEC §4.6, §4.9; `sheets/test_coupon.py` |
| `trip.h` | fault and alert classification from a snapshot (SLOT_FAULT_N, PM_ALERT_N, PGs, PRESENT_N, the monitors) and what to switch off | SPEC §3.1, §3.5, §8.4; TI SLVS841E (FAULT) |
| `selftest.h` | lane ratios, converter agreement, the slot's series resistance from two lane readings, the '165 loopback frame, load-step and current-limit checks | SPEC §3.1, §10 step 7; the test coupon's design |

Use it from a Zephyr application:

```cmake
include(${CMAKE_CURRENT_SOURCE_DIR}/../lib/tb_lib.cmake)
target_sources(app PRIVATE ${TB_LIB_SOURCES})
target_include_directories(app PRIVATE ${TB_LIB_INCLUDE})
```

## Tests

```sh
source /root/zephyrproject/ENV.sh
west build -p always -b native_sim/native/64 keyboard/firmware/lib/tests -d <build>
<build>/zephyr/zephyr.exe
# or: python3 $ZEPHYR_BASE/scripts/twister -T keyboard/firmware/lib/tests -p native_sim/native/64 -O <out>
python3 -m pytest -q -p no:cacheprovider keyboard/firmware/lib/tools     # the Python descriptor encoder
```

Result (2026-11-27): **49 of 49 ztest cases pass** in 7 suites (`west build` + `zephyr.exe`, and twister); the
Python encoder's **11 pytest cases pass**, and `tools/test_fuzz_desc.py` builds `tools/fuzz_desc.c` with the host
gcc under ASan and UBSan and feeds the C parser noise and mutated copies of the test coupon's descriptor (3,000,000
inputs on 2026-11-27: no crash, overread or undefined behaviour, and every accepted descriptor re-encodes byte for
byte; with the parser's `length > n` check removed it reports a heap overflow at once). Two deliberate bugs (CAL truncated instead of rounded; S5 not shed
first) each made the suites fail, so the tests can fail. What they check, beyond each function's own cases:

* **CAL** for every one of the 13 monitors of the generated board map equals Zephyr's formula, and the values SPEC
  §3.4 quotes (1939, 2048, 1707; 2133 and the 328 mA clip for the rejected 10 uA LSB); every LSB covers its
  shunt's full scale and every switch's maximum trip sits inside it; the datasheet's own example (2 mOhm, 1 mA,
  CAL 2560, 8000 -> 10000, 119.8 W).
* **The budget** reproduces SPEC §3.2's table with the map's numbers, refuses power before configuration and while
  suspended, sheds everything on VBUS removal and on a reset out of suspend or in bench mode, sheds when a measured
  base load replaces the estimate, keeps the 3.3 V-first order, the coupon rules and the slot LDO's 300 mA, sheds S5 first and then in
  reverse order of enabling, never lets an override raise the budget, and confines bench mode to the unconfigured
  state.
* **The descriptor**: the C parser decodes what the Python reference encoder (`tools/coupon_desc.py`, run at build
  time to make the test vectors) writes, the C encoder reproduces its bytes exactly, and the C twin of the test
  coupon's descriptor equals the Python one byte for byte; the Python tests check its lanes against the hardware
  design's `DESCRIPTOR_FACTS` (they caught the design moving from a 1 kOhm to a 499 ohm ladder during this work).
* **Trips**: removal while powered, the S5 breaker, a switch limit found by current or by sag, an unattributed
  fault, the unmeasured KVM rail, alerts, VSYS over budget, dead, sagging and live-while-off rails.
* **The rail ids** of the generated board map equal this lib's (compile-time asserts).

## The descriptor format (proposal)

`include/tb/desc.h` has the layout: a 24-byte header (magic `PCKD`, major 1, minor 0, length, type, revision,
flags, serial, the declared +3V3 and +5V currents and bulk capacitances), then type-length-value records (name,
lane, G-line, I2C device, SPI device, allowed slots, test load, calibration), then a CRC-16/CCITT-FALSE. A reader
refuses another major, skips record types it does not know, and checks every index. The test coupon's descriptor
is 167 bytes of the M24C02's 256. **Open for compiler v0 and the owner:** whether a declared current is the
coupon's steady draw or its maximum including firmware-switched test loads (this draft declares the maximum,
120 mA for the test coupon, so at most two test coupons fit the slot LDO's 300 mA at once), and whether the format
should carry a discovery current (see the bring-up's `probe=`).

## Not verified

* Every module encodes this repository's reading of the datasheets; none has met a part.
* The trip classifier's thresholds (80 % of a switch's minimum trip; 3.0 V and 4.3 V sag limits) are proposals.
