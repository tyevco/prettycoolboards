#!/usr/bin/env python3
"""The pin plan: every ESP32-S3 GPIO of the slider board, its state in each power mode. ONE source.

    python tools/pin_plan.py            # write components/board/pin_plan_table.c
    python tools/pin_plan.py --check    # exit 1 if the committed table is stale (the build runs this)

Consumers:
  * the firmware: components/board/pin_plan_table.c (generated from PLAN below) is what
    components/board/pin_plan_apply.c applies at sleep entry (SLEEP: levels, pulls, holds, the ext1
    wake mask), at boot (RUN: the plain GPIOs) and after the drivers are up (RUN: pulls on the pins a
    driver owns, which some drivers set themselves: PCNT turns pull-ups ON);
  * the host test (test/host/test_pin_plan.c): the invariants (no output against an internal pull, the
    straps, the wake pins, every board_pins.h pin present, ...);
  * tools/export_pinstate.py: pinstate.json for hwtools pullaudit / boardcheck (every state "assumed").

Modes:
  RESET  what the silicon leaves after reset, before any firmware: ESP32-S3 Series Datasheet v2.2
         (Espressif, 2026-03-05) Table 2-1 "Pin Overview", column "After Reset" (pp. 16-17; IE = input
         enabled, WPU / WPD = weak pull-up / -down, USB_PU = the USB D+ pull-up; note 7: MTCK = GPIO39
         has WPU while EFUSE_DIS_PAD_JTAG = 0). Blank = input and output disabled, no pull (hiz). The
         straps are sampled here (DS Table 3-1, p. 32).
  RUN    awake, steady state (sensor and UI rails on, peripherals running, idle levels of the buses).
  SLEEP  ESP32-S3 deep sleep. "hold" = pad latched (gpio_hold_en + gpio_deep_sleep_hold_en); pulls
         are the pad's (IO MUX) and, for RTC GPIOs 0-21, the RTC IO pulls too: both are written.
         Digital pads (GPIO22+) that are not held are isolated by ESP-IDF itself at sleep entry
         (sleep_gpio.c esp_sleep_isolate_digital_gpio: IE / OE / pulls off) once any digital pad is held.
  SHIP   BQ25180 ship (shutdown) mode: VSYS, +3V3 and every switched rail are off, the ESP32-S3 is
         unpowered, so every pad is "off". Listed so the export covers every mode in rails.yaml.

State fields: dir    in | out | od | hiz | periph (a peripheral owns the pad) | off (unpowered)
              level  0 / 1 / None (out, od: the driven level; od 1 = released; periph: the idle level)
              pull   up | down | none (the ESP32-S3 internal pull)
              hold   pad held through deep sleep
              wake   ext1 wake source (SLEEP only)
              io     periph only: what the pad is electrically, for the export (in | out | od | analog)
Per pin:      ext    the board circuit on the net (from caliper/hardware/design/sheets/*.py):
                     (kind, rail, ohm, what): kind pull_up | pull_down | driven (another chip drives the
                     net) | load (a CMOS input or a clamp of a chip on that rail) | none
              init   who configures the pad in RUN: board (app_main), sensor_mag, buttons, driver (a
                     peripheral driver; pin_plan_apply_pulls() then fixes its pulls), none
              untouched  never written by the pin-plan code (USB D-/D+: a pull change there would
                     disconnect the USB PHY's D+ pull-up)
"""
import argparse
import hashlib
import pathlib
import runpy
import sys

HERE = pathlib.Path(__file__).resolve().parent
FW = HERE.parent
DEFAULT_NETS = FW.parent / "hardware" / "design" / "nets.py"
DEFAULT_OUT = FW / "components" / "board" / "pin_plan_table.c"

MODES = ("RESET", "RUN", "SLEEP", "SHIP")
# rails a pin's external circuit can sit on, and the modes each is on in (rails.yaml / SPEC §3)
RAILS = {"none": (), "+3V3": ("RESET", "RUN", "SLEEP"), "+3V3_SNS": ("RUN",), "+3V3_UI": ("RUN",)}


def S(dir, level=None, pull="none", hold=False, wake=False, io=None, note=""):
    return dict(dir=dir, level=level, pull=pull, hold=hold, wake=wake, io=io, note=note)


OFF = S("off", note="ESP32-S3 unpowered (+3V3 off in ship mode)")

# ---- RESET states (DS v2.2 Table 2-1 "After Reset", pp. 16-17) ----
R_IE = S("in", note="DS Table 2-1: IE")
R_NONE = S("hiz", note="DS Table 2-1: no setting (IE / OE / pulls off)")
R_IE_WPU = S("in", pull="up", note="DS Table 2-1: WPU, IE")
R_IE_WPD = S("in", pull="down", note="DS Table 2-1: WPD, IE")

# ---- common SLEEP states ----
SLP_HIZ_HOLD = S("hiz", hold=True, note="isolated (IE / OE / pulls off) and held")
SLP_HIZ = S("hiz", note="isolated; not held: ESP-IDF isolates it at sleep entry")
SLP_LOW_HOLD = S("out", 0, hold=True, note="driven low, pulls off, held")
SLP_WAKE = S("in", wake=True, note="ext1 ANY_LOW wake input, pulls (pad and RTC) off")


def pin(net, ext, init, run, sleep, reset, untouched=False, owner=""):
    return dict(net=net, ext=ext, init=init, owner=owner, untouched=untouched,
                states={"RESET": reset, "RUN": run, "SLEEP": sleep, "SHIP": OFF})


PLAN = [
    pin("BOOT_N", ("pull_up", "+3V3", 10e3, "R21 10k pull-up; SW20 BOOT to GND"), "board",
        run=S("in", note="strap only; reset WPU switched off (R21 holds it high)"),
        sleep=SLP_HIZ_HOLD, reset=S("in", pull="up", note="DS Table 2-1: WPU, IE; strap GPIO0 = 1: SPI boot")),
    pin("CAP_RX", ("driven", "+3V3_SNS", 3.9e3, "R85 3.9k from the U40 charge-amp low-pass"), "driver",
        owner="sensor_cap: ADC1_CH0 (adc_continuous)",
        run=S("periph", io="analog"), sleep=SLP_HIZ_HOLD, reset=R_IE),
    pin("FG_ALRT_N", ("pull_up", "+3V3", 10e3, "R9 10k pull-up; U4 MAX17048 ALRT open drain"), "board",
        run=S("in"), sleep=SLP_HIZ_HOLD, reset=R_IE),
    pin("CHG_INT_N", ("pull_up", "+3V3", 10e3, "R8 10k pull-up; U2 BQ25180 /INT open drain"), "board",
        run=S("in"), sleep=SLP_WAKE, reset=S("in", note="DS Table 2-1: IE; strap GPIO3 (JTAG source), ignored "
                                                        "while EFUSE_STRAP_JTAG_SEL = 0")),
    pin("MAG_A", ("driven", "+3V3_SNS", None, "U30 AS5311 A, push-pull"), "driver",
        owner="sensor_mag: PCNT (the driver enables the pad pull-up; pin_plan_apply_pulls removes it)",
        run=S("periph", io="in"), sleep=SLP_HIZ_HOLD, reset=R_NONE),
    pin("MAG_B", ("driven", "+3V3_SNS", None, "U30 AS5311 B, push-pull"), "driver",
        owner="sensor_mag: PCNT (the driver enables the pad pull-up; pin_plan_apply_pulls removes it)",
        run=S("periph", io="in"), sleep=SLP_HIZ_HOLD, reset=R_NONE),
    pin("MAG_IDX", ("driven", "+3V3_SNS", None, "U30 AS5311 Index, push-pull"), "sensor_mag",
        run=S("in", note="rising-edge interrupt"), sleep=SLP_HIZ_HOLD, reset=R_NONE),
    pin("MAG_CLK", ("load", "+3V3_SNS", None, "U30 AS5311 CLK (Schmitt input)"), "sensor_mag",
        run=S("out", 1, note="SSI clock, idles high"), sleep=SLP_LOW_HOLD, reset=R_NONE),
    pin("MAG_DO", ("driven", "+3V3_SNS", None, "U30 AS5311 DO, tri-state while CSn is high"), "sensor_mag",
        run=S("in", pull="up", note="DO is tri-state between frames (CSn high): the pad pull-up keeps it "
                                    "from floating; DO drives only during a 40 us SSI read"),
        sleep=SLP_HIZ_HOLD, reset=R_NONE),
    pin("MAG_CSN", ("pull_up", "+3V3_SNS", 50e3, "U30 AS5311 CSn internal pull-up (30-100 uA at 5 V)"), "sensor_mag",
        run=S("out", 1, note="SSI chip select, idles high (A/B/Index stay unlocked once enabled)"),
        sleep=SLP_LOW_HOLD, reset=R_IE),
    pin("MAG_INC_N", ("pull_up", "+3V3_SNS", 10e3, "R30 10k to +3V3_SNS; U30 MagINCn open drain"), "sensor_mag",
        run=S("in"), sleep=SLP_HIZ_HOLD, reset=R_IE),
    pin("MAG_DEC_N", ("pull_up", "+3V3_SNS", 10e3, "R31 10k to +3V3_SNS; U30 MagDECn open drain"), "sensor_mag",
        run=S("in"), sleep=SLP_HIZ_HOLD, reset=R_IE),
    pin("SNS_PWR_EN", ("pull_down", "+3V3", 100e3, "R5 100k pull-down; U5 / U6 TPS22917 ON"), "sensor_mag",
        run=S("out", 1, note="both switched rails on (R5 costs 33 uA while awake, by design)"),
        sleep=SLP_LOW_HOLD, reset=R_IE),
    pin("I2C_SDA", ("pull_up", "+3V3", 2.2e3, "R6 2.2k pull-up; U2, U4, U60, U61"), "driver",
        owner="power: I2C0 master (open drain, internal pull-up off)",
        run=S("periph", 1, io="od"), sleep=SLP_HIZ_HOLD, reset=R_IE),
    pin("I2C_SCL", ("pull_up", "+3V3", 2.2e3, "R7 2.2k pull-up; U2, U4, U60, U61"), "driver",
        owner="power: I2C0 master (open drain, internal pull-up off)",
        run=S("periph", 1, io="od"), sleep=SLP_HIZ_HOLD, reset=R_IE),
    pin("IMU_INT1", ("driven", "+3V3", None, "U60 LSM6DSO INT1, push-pull active low (CTRL3_C 0x64)"), "board",
        run=S("in"), sleep=SLP_WAKE, reset=R_NONE),
    pin("IMU_INT2", ("driven", "+3V3", None, "U60 LSM6DSO INT2, push-pull (no source routed)"), "board",
        run=S("in"), sleep=SLP_HIZ_HOLD, reset=R_NONE),
    pin("BTN_ZERO_N", ("pull_up", "+3V3", 100e3, "R52 100k pull-up + C52 100n; SW50 to GND"), "buttons",
        run=S("in"), sleep=SLP_WAKE, reset=R_IE),
    pin("BTN_HOLD_N", ("pull_up", "+3V3", 100e3, "R53 100k pull-up + C53 100n; SW51 to GND"), "buttons",
        run=S("in"), sleep=SLP_WAKE, reset=R_IE),
    pin("USB_DM", ("load", "none", None, "U1 USBLC6 ESD, J1 (host pull-downs only with a cable)"), "driver",
        owner="USB PHY (TinyUSB / USB-Serial-JTAG)", untouched=True,
        run=S("periph", io="in"), sleep=S("periph", io="in", note="USB PHY pad, not touched"),
        reset=R_NONE),
    pin("USB_DP", ("load", "none", None, "U1 USBLC6 ESD, J1 (host pull-downs only with a cable)"), "driver",
        owner="USB PHY (TinyUSB / USB-Serial-JTAG)", untouched=True,
        run=S("periph", pull="up", io="in", note="the PHY's 1.5k D+ pull-up while the device stack is attached"),
        sleep=S("periph", io="in", note="USB PHY pad, not touched; the D+ pull-up is assumed off with the "
                                        "digital domain (not verified)"),
        reset=S("in", pull="up", note="DS Table 2-1: USB_PU (the USB D+ pull-up)")),
    pin("BTN_MODE_N", ("pull_up", "+3V3", 100e3, "R54 100k pull-up + C54 100n; SW52 to GND"), "buttons",
        run=S("in"), sleep=SLP_WAKE, reset=R_NONE),
    pin("LCD_SCK", ("load", "+3V3_UI", None, "J50 ST7789 SCL input"), "driver", owner="ui: SPI2 (esp_lcd)",
        run=S("periph", 0, io="out"), sleep=SLP_LOW_HOLD, reset=R_IE),
    pin("LCD_MOSI", ("load", "+3V3_UI", None, "J50 ST7789 SDA input"), "driver", owner="ui: SPI2 (esp_lcd)",
        run=S("periph", 0, io="out"), sleep=SLP_LOW_HOLD, reset=R_IE),
    pin("LCD_CS_N", ("load", "+3V3_UI", None, "J50 ST7789 CS input"), "driver", owner="ui: SPI2 (esp_lcd)",
        run=S("periph", 1, io="out"), sleep=SLP_LOW_HOLD, reset=R_IE),
    pin("LCD_DC", ("load", "+3V3_UI", None, "J50 ST7789 RS (D/C) input"), "driver", owner="ui: esp_lcd D/C GPIO",
        run=S("periph", 0, io="out"), sleep=SLP_LOW_HOLD, reset=R_IE),
    pin("LCD_RST_N", ("load", "+3V3_UI", None, "J50 ST7789 RESET input"), "driver", owner="ui: esp_lcd reset GPIO",
        run=S("periph", 1, io="out"), sleep=SLP_LOW_HOLD, reset=R_IE),
    pin("LCD_BL", ("pull_down", "+3V3", 100e3, "R51 100k gate pull-down; Q50 AO3400A gate"), "driver",
        owner="power: LEDC channel 0 (backlight PWM)",
        run=S("periph", 1, io="out", note="PWM; 1 = on part of the cycle (R51 33 uA while high)"),
        sleep=SLP_LOW_HOLD, reset=R_IE),
    *[pin(f"CAP_TX{i}", ("load", "none", None, f"R6{i} 0R + R7{i} 100R to the TX{i} electrode (capacitive)"),
          "driver", owner="sensor_cap: dedicated-GPIO bundle",
          run=S("periph", 0, io="out", note="0 between bursts"), sleep=SLP_HIZ,
          reset={0: S("in", pull="up", note="DS Table 2-1: IE, WPU (MTCK, note 7: EFUSE_DIS_PAD_JTAG = 0)"),
                 6: S("periph", 1, pull="up", io="out", note="U0TXD: ROM boot log (DS Table 2-1: WPU, IE)"),
                 7: R_IE_WPU}.get(i, R_IE))
      for i in range(8)],
    pin("BUZZ", ("pull_down", "+3V3", 100e3, "R56 100k gate pull-down; Q51 AO3400A gate"), "driver",
        owner="power: LEDC channel 1 (piezo)",
        run=S("periph", 0, io="out", note="square wave while beeping; the reset WPD is switched off"),
        sleep=SLP_LOW_HOLD, reset=S("in", pull="down", note="DS Table 2-1: WPD, IE; strap GPIO45 = 0: VDD_SPI 3.3 V")),
    pin("RGB_DIN", ("pull_down", "+3V3", 100e3, "R55 100k pull-down; D50 WS2812 DIN on +3V3_UI"), "driver",
        owner="power: RMT (led_strip)",
        run=S("periph", 0, io="out", note="WS2812 data, idles low; the reset WPD is switched off"),
        sleep=SLP_LOW_HOLD, reset=S("in", pull="down", note="DS Table 2-1: WPD, IE; strap GPIO46 = 0 / float")),
]

ENUM = {
    "dir": {"off": "PP_DIR_OFF", "in": "PP_DIR_IN", "out": "PP_DIR_OUT", "od": "PP_DIR_OD", "hiz": "PP_DIR_HIZ",
            "periph": "PP_DIR_PERIPH"},
    "pull": {"none": "PP_PULL_NONE", "up": "PP_PULL_UP", "down": "PP_PULL_DOWN"},
    "kind": {"none": "PP_EXT_NONE", "pull_up": "PP_EXT_PULL_UP", "pull_down": "PP_EXT_PULL_DOWN",
             "driven": "PP_EXT_DRIVEN", "load": "PP_EXT_LOAD"},
    "rail": {"none": "PP_RAIL_NONE", "+3V3": "PP_RAIL_3V3", "+3V3_SNS": "PP_RAIL_SNS", "+3V3_UI": "PP_RAIL_UI"},
    "init": {"none": "PP_INIT_NONE", "board": "PP_INIT_BOARD", "sensor_mag": "PP_INIT_SENSOR_MAG",
             "buttons": "PP_INIT_BUTTONS", "driver": "PP_INIT_DRIVER"},
}


def load(nets_path=DEFAULT_NETS):
    """PLAN with the GPIO numbers from nets.py; checks that the plan covers every MCU net exactly once."""
    gpio = runpy.run_path(str(nets_path))["GPIO"]
    nets = [p["net"] for p in PLAN]
    dup = sorted({n for n in nets if nets.count(n) > 1})
    missing = sorted(set(gpio) - set(nets))
    extra = sorted(set(nets) - set(gpio))
    if dup or missing or extra:
        raise SystemExit(f"pin_plan: duplicate {dup}, not in the plan {missing}, not in nets.py {extra}")
    out = []
    for p in PLAN:
        q = dict(p, gpio=gpio[p["net"]])
        for m in MODES:
            st = q["states"][m]
            for k, allowed in (("dir", ENUM["dir"]), ("pull", ENUM["pull"])):
                if st[k] not in allowed:
                    raise SystemExit(f"pin_plan: {p['net']} {m}: bad {k} {st[k]!r}")
        out.append(q)
    return sorted(out, key=lambda q: q["gpio"])


def _c_str(s):
    return '"' + s.replace("\\", "\\\\").replace('"', '\\"') + '"'


def _c_state(st):
    lvl = "PP_LEVEL_NONE" if st["level"] is None else str(int(st["level"]))
    return (f"{{{ENUM['dir'][st['dir']]}, {lvl}, {ENUM['pull'][st['pull']]}, "
            f"{'true' if st['hold'] else 'false'}, {'true' if st['wake'] else 'false'}}}")


def render(nets_path=DEFAULT_NETS):
    plan = load(nets_path)
    digest = hashlib.sha256(pathlib.Path(__file__).read_bytes() + nets_path.read_bytes()).hexdigest()[:16]
    L = [
        "/*",
        " * GENERATED by firmware/tools/pin_plan.py (the pin plan: per-mode state of every ESP32-S3 GPIO).",
        " * Do not edit: change PLAN in tools/pin_plan.py and regenerate. See components/board/include/pin_plan.h.",
        " */",
        '#include "board_pins.h"',
        '#include "pin_plan.h"',
        "",
        f'const char PIN_PLAN_HASH[] = "{digest}";',
        "",
        "const pin_plan_t PIN_PLAN[] = {",
    ]
    for p in plan:
        kind, rail, ohm, what = p["ext"]
        L.append(f"    {{.gpio = PIN_{p['net']}, .net = {_c_str(p['net'])}, .owner = {_c_str(p['owner'])},")
        L.append(f"     .init = {ENUM['init'][p['init']]}, .untouched = {'true' if p['untouched'] else 'false'},")
        L.append(f"     .ext = {{{ENUM['kind'][kind]}, {ENUM['rail'][rail]}, {int(ohm or 0)}u, {_c_str(what)}}},")
        L.append("     .st = {")
        for m in MODES:
            L.append(f"         [PP_MODE_{m}] = {_c_state(p['states'][m])},")
        L.append("     }},")
    L += ["};", "", "const size_t PIN_PLAN_COUNT = sizeof(PIN_PLAN) / sizeof(PIN_PLAN[0]);", ""]
    return "\n".join(L)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--nets", type=pathlib.Path, default=DEFAULT_NETS)
    ap.add_argument("--out", type=pathlib.Path, default=DEFAULT_OUT)
    ap.add_argument("--check", action="store_true")
    a = ap.parse_args()
    text = render(a.nets)
    if a.check:
        cur = a.out.read_text(encoding="utf-8") if a.out.exists() else ""
        if cur != text:
            print(f"pin_plan: {a.out} is stale; run: python tools/pin_plan.py", file=sys.stderr)
            return 1
        print("pin_plan: pin_plan_table.c up to date")
        return 0
    a.out.write_text(text, encoding="utf-8", newline="\n")
    print(f"pin_plan: wrote {a.out}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
