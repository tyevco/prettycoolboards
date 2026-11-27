"""Net names, the coupon slot pinout and the MCU pin map of the rev A testbed motherboard (the capture contract).

Draft architecture of record: SPEC.md. Designed on paper, not captured: no schematic, layout, build or measurement
yet. The pin map is a DRAFT: its pin numbers and alternate functions agree with the datasheet. The reference manual
(RM0456 Rev 7) items of SPEC §5.2/§5.3 were read on 2026-11-27 in a third-party transcription, not ST's PDF (SPEC
§11 #24), and the errata sheet ES0553 is not read (§11 #25). Sources: pin numbers from ST's STM32_open_pin_data
(mcu/STM32U5A5VJTx.xml, master 45c0459, fetched 2026-11-26); alternate functions and the Zephyr pinctrl node names
from hal_stm32 (dts/st/u5/stm32u5a5vjtx-pinctrl.dtsi, main ba344b9, fetched 2026-11-26), checked on 2026-11-27
against the revision Zephyr v4.5.0 pins, c9550199: the file is identical and all 50 node names exist. All 100 pin
numbers agree with DS13543 Rev 2 Table 27's non-SMPS LQFP100 column, and the timer, bus and USB alternate functions
with Tables 28-29 (SPEC §5.1). The KiCad 10.0.8 library symbol carries the same 100 functions; five pin names are
spelled differently (KICAD_PIN_ALIAS). SPEC §5 has the reasoning.

Run `python nets.py` to self-check: every net on an MCU pin is a power net, an intersheet net, a slot net or one of
the MCU sheet's local nets; no signal net sits on two pins; every LQFP100 pin is mapped; every slot signal reaches
the MCU or a named motherboard part; no I2C address is used twice on a bus; the USB Type-C detect chip uses no MCU
pin and its interrupt lands on an expander input.

Owner decisions of 2026-11-26 recorded here (SPEC §1): no battery and no charger on rev A (D1); the slot connector is
2 x 20 at 2.54 mm (D2); a USB Type-C detect chip on I2C reads the source's advertised current (D3). The parts named
for them are candidates.
"""

REV = "A-testbed"
DATE = "2026-11-27"
STATUS = ("draft: designed on paper, not captured; pin numbers checked against DS13543; RM0456 items read in a "
          "transcription; ES0553 errata not read")

MCU = "STM32U5A5VJT6"          # LQFP100 14 x 14 mm, 0.5 mm pitch, no SMPS (the -Q parts have it). JLC C22455480
SLOTS = (1, 2, 3, 4, 5)        # S1-S5 (SPEC §2, §4). S5 is the haptics slot: TIM1, ADC4 lanes, the 2 A 5 V rail

# Nets drawn with power symbols (SPEC §3).
POWER_NETS = [
    "GND",
    "VBUS",                    # USB-C VBUS, before the input breaker
    "VSYS",                    # 5 V after the input breaker (U2, TPS259474L) and the board-total shunt (INA226 0x40)
    "+3V3",                    # always-on digital 3.3 V (AP2112K): monitors, expanders, mux, bus switches, LEDs
    "+3V3_MCU",                # +3V3 through the 0.5 ohm MCU shunt: the MCU's VDD pins and VBAT
    "+3V3_USB",                # +3V3 through the 1 ohm shunt: VDDUSB only (the HS PHY's 3.3 V part)
    "+3V3_SLOT",               # low-noise 3.3 V (LDL1117) feeding the five slot 3V3 switches
    "+3V3A",                   # +3V3_SLOT through a ferrite: VDDA and VREF+ (ratiometric with the slot rails)
    *[f"+3V3_S{n}" for n in SLOTS],   # switched, current-limited, measured slot rails
    *[f"+5V_S{n}" for n in SLOTS],
    "+5V_KVM",                 # the optional KVM header's switched 5 V (not measured per rail)
]

# --- Coupon slot connector (SPEC §4) ----------------------------------------------------------------------------
SLOT_CONNECTOR = ("2 x 20, 2.54 mm (owner's decision D2, 2026-11-26). Motherboard: female, through-hole, 8.5 mm "
                  "(BOOMELE 2.54-2*20P, C5124634, candidate part). Coupon: male pin header (HanElectricity "
                  "2541WV-2x20P, C25503140, candidate part)")

# One entry per connector pin: (pin, signal, direction seen from the motherboard, note).
# Odd pins are one row, even pins the other. Signal names are slot-local: slot_net(n, signal) gives the net.
SLOT_PINS = [
    (1, "+5V", "pwr", "switched 5 V; three pins carry the haptics slot's motor peaks (2.5 A per contact rating)"),
    (2, "+5V", "pwr", ""),
    (3, "+5V", "pwr", ""),
    (4, "GND", "gnd", "the motor current's return: the three GND pins next to +5V"),
    (5, "GND", "gnd", ""),
    (6, "GND", "gnd", ""),
    (7, "+3V3", "pwr", "switched 3.3 V, the sensors' supply and the lanes' ratiometric reference"),
    (8, "+3V3", "pwr", ""),
    (9, "GND", "gnd", ""),
    (10, "GND", "gnd", ""),
    (11, "AN0", "in", "analog lane 0 to an ADC channel (SLOT_MCU); 47 ohm + 1 nF C0G at the MCU pin"),
    (12, "GND", "gnd", "a ground opposite every lane"),
    (13, "AN1", "in", "analog lane 1"),
    (14, "GND", "gnd", ""),
    (15, "AN2", "in", "analog lane 2"),
    (16, "GND", "gnd", ""),
    (17, "AN3", "in", "analog lane 3"),
    (18, "GND", "gnd", ""),
    (19, "INJ", "out", "latency-rig stimulus, from RIG_INJ through solder jumper JP_INJn (open by default)"),
    (20, "SYNC", "out", "scan frame tick (TIM2_CH1) through the slot's bus switch"),
    (21, "GND", "gnd", ""),
    (22, "GND", "gnd", ""),
    (23, "SCK", "out", "shared SPI2 through the slot's bus switch"),
    (24, "MISO", "in", "shared SPI2 through the slot's bus switch"),
    (25, "MOSI", "out", "shared SPI2 through the slot's bus switch"),
    (26, "GND", "gnd", ""),
    (27, "CS0_N", "out", "per-slot SPI chip select (a GPIO)"),
    (28, "CS1_N", "out", "second per-slot chip select (a GPIO)"),
    (29, "SCL", "io", "the slot's own I2C channel of the TCA9548A, 4.7 k pull-up to the slot's +3V3"),
    (30, "SDA", "io", ""),
    (31, "IRQ_N", "in", "per-slot interrupt, a distinct EXTI line per slot; pull-up on the coupon"),
    (32, "PRESENT_N", "in", "tied to GND on the coupon; 100 k pull-up on the motherboard; read by U_EXP2"),
    (33, "G0", "io", "enable/select GPIO; S4: TIM8_CH1; S5: TIM1_CH1"),
    (34, "G1", "io", "S4: TIM8_CH2; S5: TIM1_CH2"),
    (35, "G2", "io", "S4: TIM8_CH3; S5: TIM1_CH3"),
    (36, "G3", "io", "S4: TIM8_CH4; S5: TIM1_CH1N"),
    (37, "G4", "io", "S1-S4: slow, on expander U_EXP3; S5: TIM1_CH2N"),
    (38, "G5", "io", "S1-S4: slow, on expander U_EXP3; S5: TIM1_CH3N"),
    (39, "RSV", "nc", "reserved, not connected on the rev A motherboard"),
    (40, "GND", "gnd", ""),
]

SLOT_SIGNALS = [s for _, s, d, _ in SLOT_PINS if d not in ("pwr", "gnd", "nc")]


def slot_net(n, signal):
    """The net on slot n's connector pin for a slot-local signal (None for the reserved pin)."""
    if signal == "GND":
        return "GND"
    if signal in ("+5V", "+3V3"):
        return f"{signal}_S{n}"
    if signal == "RSV":
        return None
    return f"S{n}_{signal}"


# What sits between a slot pin and the MCU (SPEC §4.3). The MCU-side net is mcu_net(n, signal).
SLOT_PATH = {
    "AN0": "47 ohm series + 1 nF C0G to GND at the MCU pin (proposal; 680 pF C0G is the alternative if a sensor's "
           "CLoad limit, TMAG5253 1 nF max, has to cover the lane: SPEC §4.3)",
    "AN1": "as AN0", "AN2": "as AN0", "AN3": "as AN0",
    "INJ": "solder jumper JP_INJn from RIG_INJ (J_RIG pin 9); open by default",
    "SYNC": "SN74CBTLV3125 bus switch U_BSn, OE_N = BUSEN_N_Sn, from SLOT_SYNC",
    "SCK": "U_BSn from SLOT_SCK (100 k to GND on SLOT_SCK, see MCU_SIDE_PULLS)", "MISO": "U_BSn to SLOT_MISO",
    "MOSI": "U_BSn from SLOT_MOSI (100 k to GND on SLOT_MOSI)",
    "CS0_N": "direct", "CS1_N": "direct", "IRQ_N": "direct",
    "SCL": "TCA9548A U_MUX channel n-1, pull-ups to +3V3_Sn", "SDA": "as SCL",
    "PRESENT_N": "U_EXP2 input, 100 k pull-up to +3V3",
    "G0": "direct", "G1": "direct", "G2": "direct", "G3": "direct",
    "G4": "S1-S4: U_EXP3 output with 100 k pull-down; S5: direct", "G5": "as G4",
}
BUS_SWITCHED = ("SCK", "MISO", "MOSI", "SYNC")

# Pull resistors on shared MCU nets (proposal). ST's ROM bootloader probes SPI2 on PB13/PB15 with BOOT0 high, and
# AN2606 Rev 68 §4.3 asks for a pull-down on SCK and a known level on unused RX pins such as SPI_MOSI; with the bus
# switches open these nets would float on the switches' A sides (SPEC §4.3, §5.2). About 33 uA each when driven high.
MCU_SIDE_PULLS = {"SLOT_SCK": ("GND", 100e3), "SLOT_MOSI": ("GND", 100e3)}


def mcu_net(n, signal):
    """The net at the MCU (or at the motherboard part) that serves slot n's signal."""
    if signal.startswith("AN"):
        return f"S{n}_{signal}_ADC"            # the MCU side of the lane's series resistor
    if signal in BUS_SWITCHED:
        return f"SLOT_{signal}"                # shared, before the bus switches
    if signal in ("SCL", "SDA"):
        return f"I2C_SLOT_{signal}"            # the mux's upstream bus
    return f"S{n}_{signal}"


# Slot signal -> MCU pin, for the signals wired straight to the MCU (lanes through their RC). SPEC §4.4, §5.
SLOT_MCU = {
    1: {"AN0": "PC0", "AN1": "PC1", "AN2": "PC2", "AN3": "PC3",
        "G0": "PE2", "G1": "PE3", "G2": "PE4", "G3": "PE5",
        "CS0_N": "PE6", "CS1_N": "PE1", "IRQ_N": "PC14-OSC32_IN"},
    2: {"AN0": "PA0", "AN1": "PA1", "AN2": "PA2", "AN3": "PA3",
        "G0": "PD8", "G1": "PD9", "G2": "PD10", "G3": "PD14",
        "CS0_N": "PD15", "CS1_N": "PD7", "IRQ_N": "PD6"},
    3: {"AN0": "PA4", "AN1": "PA5", "AN2": "PA6", "AN3": "PA7",
        "G0": "PD0", "G1": "PD1", "G2": "PD2", "G3": "PD3",
        "CS0_N": "PD4", "CS1_N": "PD5", "IRQ_N": "PE0"},
    4: {"AN0": "PC4", "AN1": "PC5", "AN2": "PB0", "AN3": "PB1",
        "G0": "PC6", "G1": "PC7", "G2": "PC8", "G3": "PC9",
        "CS0_N": "PB12", "CS1_N": "PC12", "IRQ_N": "PB5"},
    5: {"AN0": "PB2", "AN1": "PD11", "AN2": "PD12", "AN3": "PD13",
        "G0": "PE9", "G1": "PE11", "G2": "PE13", "G3": "PE8", "G4": "PE10", "G5": "PE12",
        "CS0_N": "PE14", "CS1_N": "PE7", "IRQ_N": "PE15"},
}

# ADC channels behind each lane pin (hal_stm32 pinctrl node names adcN_inM_<pin>). ADC1/ADC2 are 14-bit, up to
# 2.5 Msps at 14 bits; ADC4 is 12-bit, up to 2.75 Msps at 12 bits (DS13543 Rev 2, Tables 97 and 100). SPEC §6.
LANE_ADC = {
    "PC0": ("ADC1_IN1", "ADC2_IN1", "ADC4_IN1"), "PC1": ("ADC1_IN2", "ADC2_IN2", "ADC4_IN2"),
    "PC2": ("ADC1_IN3", "ADC2_IN3", "ADC4_IN3"), "PC3": ("ADC1_IN4", "ADC2_IN4", "ADC4_IN4"),
    "PA0": ("ADC1_IN5", "ADC2_IN5"), "PA1": ("ADC1_IN6", "ADC2_IN6"),
    "PA2": ("ADC1_IN7", "ADC2_IN7"), "PA3": ("ADC1_IN8", "ADC2_IN8"),
    "PA4": ("ADC1_IN9", "ADC2_IN9", "ADC4_IN9"), "PA5": ("ADC1_IN10", "ADC2_IN10", "ADC4_IN10"),
    "PA6": ("ADC1_IN11", "ADC2_IN11", "ADC4_IN11"), "PA7": ("ADC1_IN12", "ADC2_IN12", "ADC4_IN20"),
    "PC4": ("ADC1_IN13", "ADC2_IN13", "ADC4_IN22"), "PC5": ("ADC1_IN14", "ADC2_IN14", "ADC4_IN23"),
    "PB0": ("ADC1_IN15", "ADC2_IN15", "ADC4_IN18"), "PB1": ("ADC1_IN16", "ADC2_IN16", "ADC4_IN19"),
    "PB2": ("ADC1_IN17", "ADC2_IN17"),
    "PD11": ("ADC4_IN15",), "PD12": ("ADC4_IN16",), "PD13": ("ADC4_IN17",),
}

# --- Motherboard nets -------------------------------------------------------------------------------------------
# Signals that cross sheet boundaries on the motherboard (global labels), apart from the per-slot nets below.
MOTHERBOARD_INTERSHEET = [
    "USB_DP", "USB_DM",                            # the 90 ohm pair: J1 -> ESD -> MCU, hand-routed (SPEC §7.1)
    "SWDIO", "SWCLK", "SWO", "NRST",               # J_SWD (STDC14)
    "CON_TX", "CON_RX",                            # USART1 console on J_SWD's VCP pins
    "I2C_PM_SCL", "I2C_PM_SDA",                    # I2C1: 13 x INA226 + 3 x TCA9535 (SPEC §3.4)
    "I2C_SLOT_SCL", "I2C_SLOT_SDA",                # I2C4: the TCA9548A upstream (SPEC §4.5)
    "SLOT_SCK", "SLOT_MISO", "SLOT_MOSI",          # SPI2, shared, before the per-slot bus switches
    "SLOT_SYNC",                                   # TIM2_CH1 frame tick: bus switches and J_RIG
    "RIG_MARK", "RIG_TRIG", "RIG_INJ", "USB_SOF",  # J_RIG (SPEC §7.3)
    "EXP_INT_N",                                   # U_EXP2 interrupt (open drain)
    "USBC_INT_N",                                  # U_CC (Type-C detect) interrupt, open drain, into U_EXP2 P14
    "PM_ALERT_N", "SLOT_FAULT_N", "MUX_RST_N",     # wired-OR INA226 alerts, wired-OR switch faults, mux reset
    "VSYS_PG", "S5_PG",                            # TPS259474L power-good flags (input breaker, S5 5 V breaker)
    *[f"EN_3V3_S{n}" for n in SLOTS], *[f"EN_5V_S{n}" for n in SLOTS],
    *[f"BUSEN_N_S{n}" for n in SLOTS], "EN_5V_KVM",
    "KVM_TX", "KVM_RX", "KVM_SCL", "KVM_SDA", "KVM_RST_N", "KVM_PRESENT_N",   # J_KVM (SPEC §7.4)
    *[f"LED_S{n}" for n in SLOTS],                 # slot-powered LEDs on U_EXP3
]

# Per-slot nets: the connector side (slot_net) plus the lanes' MCU side (S<n>_AN<k>_ADC).
SLOT_NETS = sorted({net for n in SLOTS for s in SLOT_SIGNALS for net in (slot_net(n, s), mcu_net(n, s))
                    if net and net.startswith(f"S{n}_")})

# Nets local to the MCU sheet.
MCU_LOCAL = ["HSE_IN", "HSE_OUT", "VCAP", "BOOT0", "LED_N"]

# Nets local to the USB-C input sheet (J1, the ESD array, U_CC). No 5.1 k Rd resistors are fitted: U_CC presents Rd
# itself, powered or not (SPEC §3.8). Two 5.1 k footprints on USB_CC1/USB_CC2 stay unfitted (a board without U_CC).
USBC_LOCAL = ["USB_CC1", "USB_CC2", "CC_VBUS_DET", "CC_ADDR"]

INTERSHEET = MOTHERBOARD_INTERSHEET + SLOT_NETS

# --- MCU -------------------------------------------------------------------------------------------------------
# LQFP100 pin number -> pin name (ST STM32_open_pin_data, STM32U5A5VJTx.xml; the non-SMPS package: pin 48 is VCAP,
# so PB11 is not bonded out). Names keep ST's form ("PC14-OSC32_IN"). KiCad's symbol spells five of them as bare GPIO
# names: KICAD_PIN_ALIAS below.
LQFP100 = {
    1: "PE2", 2: "PE3", 3: "PE4", 4: "PE5", 5: "PE6", 6: "VBAT", 7: "PC13", 8: "PC14-OSC32_IN",
    9: "PC15-OSC32_OUT", 10: "VSS", 11: "VDD", 12: "PH0-OSC_IN", 13: "PH1-OSC_OUT", 14: "NRST", 15: "PC0", 16: "PC1",
    17: "PC2", 18: "PC3", 19: "VSSA", 20: "VREF-", 21: "VREF+", 22: "VDDA", 23: "PA0", 24: "PA1",
    25: "PA2", 26: "PA3", 27: "VSS", 28: "VDD", 29: "PA4", 30: "PA5", 31: "PA6", 32: "PA7",
    33: "PC4", 34: "PC5", 35: "PB0", 36: "PB1", 37: "PB2", 38: "PE7", 39: "PE8", 40: "PE9",
    41: "PE10", 42: "PE11", 43: "PE12", 44: "PE13", 45: "PE14", 46: "PE15", 47: "PB10", 48: "VCAP",
    49: "VSS", 50: "VDD", 51: "PB12", 52: "PB13", 53: "PB14", 54: "PB15", 55: "PD8", 56: "PD9",
    57: "PD10", 58: "PD11", 59: "PD12", 60: "PD13", 61: "PD14", 62: "PD15", 63: "PC6", 64: "PC7",
    65: "PC8", 66: "PC9", 67: "PA8", 68: "PA9", 69: "PA10", 70: "PA11", 71: "PA12", 72: "PA13",
    73: "VDDUSB", 74: "VSS", 75: "VDD", 76: "PA14", 77: "PA15", 78: "PC10", 79: "PC11", 80: "PC12",
    81: "PD0", 82: "PD1", 83: "PD2", 84: "PD3", 85: "PD4", 86: "PD5", 87: "PD6", 88: "PD7",
    89: "PB3", 90: "PB4", 91: "PB5", 92: "PB6", 93: "PB7", 94: "PH3-BOOT0", 95: "PB8", 96: "PB9",
    97: "PE0", 98: "PE1", 99: "VSS", 100: "VDD",
}

# KiCad 10.0.8 library symbol MCU_ST_STM32U5:STM32U5A5VJTx (kicad-symbols tag 10.0.8, footprint
# Package_QFP:LQFP-100_14x14mm_P0.5mm), parsed on 2026-11-27: every pin number carries the same function as LQFP100,
# and 95 names match exactly. The symbol name -> the LQFP100 name for the other five, for the future
# check_contract.py (as the caliper's PIN_ALIAS). check(): each alias lands on its own pin number.
KICAD_SYMBOL = "MCU_ST_STM32U5:STM32U5A5VJTx"
KICAD_PIN_ALIAS = {"PC14": "PC14-OSC32_IN", "PC15": "PC15-OSC32_OUT", "PH0": "PH0-OSC_IN", "PH1": "PH1-OSC_OUT",
                   "PH3": "PH3-BOOT0"}
KICAD_ALIAS_PIN_NUMBER = {"PC14": 8, "PC15": 9, "PH0": 12, "PH1": 13, "PH3": 94}

# STM32U5A5VJT6 pin name -> net. None = no-connect (none in this draft: every I/O is used).
# DRAFT: pin numbers checked against DS13543 Rev 2; capture still to come. SPEC §5 has the constraints behind each.
MCU_PINS = {
    # supplies (DS13543 Rev 2 Figure 23: n x 100 nF + 10 uF on VDD, 4.7 uF on VCAP, 100 nF + 1 uF on VDDA and VREF+)
    "VDD": "+3V3_MCU", "VSS": "GND", "VBAT": "+3V3_MCU",       # no backup battery: VBAT tied to VDD
    "VDDA": "+3V3A", "VREF+": "+3V3A", "VSSA": "GND", "VREF-": "GND",
    "VDDUSB": "+3V3_USB",      # its own shunt; the PHY's 1.1 V part has no pin on this package (SPEC §3.3)
    "VCAP": "VCAP",            # LDO output: 4.7 uF (or 2 x 2.2 uF), ESR < 20 mohm at 3 MHz, >= 10 V
    "NRST": "NRST", "PH3-BOOT0": "BOOT0",
    # clocks and debug
    "PH0-OSC_IN": "HSE_IN", "PH1-OSC_OUT": "HSE_OUT",          # 16 MHz crystal, the Nucleo's HSE
    "PC14-OSC32_IN": "S1_IRQ_N", "PC15-OSC32_OUT": "LED_N",    # no LSE in rev A (SPEC §5.2)
    "PA13": "SWDIO", "PA14": "SWCLK", "PB3": "SWO",
    # USB high speed (on-chip PHY) and its SOF pulse
    "PA11": "USB_DM", "PA12": "USB_DP", "PA8": "USB_SOF",
    # console, KVM link
    "PA9": "CON_TX", "PA10": "CON_RX",                          # USART1, as on the Nucleo
    "PC10": "KVM_TX", "PC11": "KVM_RX",                         # UART4
    # buses
    "PB13": "SLOT_SCK", "PB14": "SLOT_MISO", "PB15": "SLOT_MOSI",   # SPI2
    "PB6": "I2C_SLOT_SCL", "PB7": "I2C_SLOT_SDA",                   # I2C4 -> TCA9548A
    "PB8": "I2C_PM_SCL", "PB9": "I2C_PM_SDA",                       # I2C1 -> INA226 x 13, TCA9535 x 3
    # scan timing and the latency rig
    "PA15": "SLOT_SYNC",       # TIM2_CH1: frame tick out
    "PB10": "RIG_TRIG",        # TIM2_CH3: input capture of the rig's stimulus, on the frame timer
    "PB4": "RIG_MARK",         # GPIO: toggled when a report is queued (NJTRST pull-up at reset: goes to the rig only)
    "PC13": "EXP_INT_N",       # input only (PC13-PC15 may not source current)
    # S1 (lanes on ADC1/ADC2 IN1-IN4, also ADC4 IN1-IN4)
    "PC0": "S1_AN0_ADC", "PC1": "S1_AN1_ADC", "PC2": "S1_AN2_ADC", "PC3": "S1_AN3_ADC",
    "PE2": "S1_G0", "PE3": "S1_G1", "PE4": "S1_G2", "PE5": "S1_G3",
    "PE6": "S1_CS0_N", "PE1": "S1_CS1_N",
    # S2 (lanes on ADC1/ADC2 IN5-IN8)
    "PA0": "S2_AN0_ADC", "PA1": "S2_AN1_ADC", "PA2": "S2_AN2_ADC", "PA3": "S2_AN3_ADC",
    "PD8": "S2_G0", "PD9": "S2_G1", "PD10": "S2_G2", "PD14": "S2_G3",
    "PD15": "S2_CS0_N", "PD7": "S2_CS1_N", "PD6": "S2_IRQ_N",
    # S3 (lanes on ADC1/ADC2 IN9-IN12, also ADC4)
    "PA4": "S3_AN0_ADC", "PA5": "S3_AN1_ADC", "PA6": "S3_AN2_ADC", "PA7": "S3_AN3_ADC",
    "PD0": "S3_G0", "PD1": "S3_G1", "PD2": "S3_G2", "PD3": "S3_G3",
    "PD4": "S3_CS0_N", "PD5": "S3_CS1_N", "PE0": "S3_IRQ_N",
    # S4 (lanes on ADC1/ADC2 IN13-IN16, also ADC4; G0-G3 on TIM8 CH1-CH4)
    "PC4": "S4_AN0_ADC", "PC5": "S4_AN1_ADC", "PB0": "S4_AN2_ADC", "PB1": "S4_AN3_ADC",
    "PC6": "S4_G0", "PC7": "S4_G1", "PC8": "S4_G2", "PC9": "S4_G3",
    "PB12": "S4_CS0_N", "PC12": "S4_CS1_N", "PB5": "S4_IRQ_N",
    # S5, haptics (AN0 on ADC1/ADC2 IN17, AN1-AN3 on ADC4 IN15-IN17; G0-G5 on TIM1 for the DRV8316)
    "PB2": "S5_AN0_ADC", "PD11": "S5_AN1_ADC", "PD12": "S5_AN2_ADC", "PD13": "S5_AN3_ADC",
    "PE9": "S5_G0", "PE11": "S5_G1", "PE13": "S5_G2",           # TIM1_CH1-CH3: INHA-INHC
    "PE8": "S5_G3", "PE10": "S5_G4", "PE12": "S5_G5",           # TIM1_CH1N-CH3N: INLA-INLC (GPIO high in 3x PWM)
    "PE14": "S5_CS0_N", "PE7": "S5_CS1_N",
    "PE15": "S5_IRQ_N",        # TIM1_BKIN: the DRV8316's nFAULT stops the PWM in hardware (never gpio_pin_configure)
}

# Pin -> (function, mode, Zephyr pinctrl node). Mode is the alternate function (AFn), ANALOG, or the GPIO direction.
# AF numbers and node names: hal_stm32 dts/st/u5/stm32u5a5vjtx-pinctrl.dtsi (main ba344b9, 2026-11-26), identical to
# the copy at c9550199, the revision Zephyr v4.5.0 pins (checked 2026-11-27).
MCU_FUNC = {
    "PA11": ("OTG_HS_DM", "ANALOG", "usb_otg_hs_dm_pa11"),
    "PA12": ("OTG_HS_DP", "ANALOG", "usb_otg_hs_dp_pa12"),
    "PA8": ("OTG_HS_SOF", "AF10", "usb_otg_hs_sof_pa8"),
    "PA13": ("SWDIO", "AF0", "debug_jtms_swdio_pa13"),
    "PA14": ("SWCLK", "AF0", "debug_jtck_swclk_pa14"),
    "PB3": ("SWO", "AF0", "debug_jtdo_swo_pb3"),
    "PH0-OSC_IN": ("RCC_OSC_IN (HSE)", "ANALOG", None),
    "PH1-OSC_OUT": ("RCC_OSC_OUT (HSE)", "ANALOG", None),
    "PA9": ("USART1_TX", "AF7", "usart1_tx_pa9"),
    "PA10": ("USART1_RX", "AF7", "usart1_rx_pa10"),
    "PC10": ("UART4_TX", "AF8", "uart4_tx_pc10"),
    "PC11": ("UART4_RX", "AF8", "uart4_rx_pc11"),
    "PB13": ("SPI2_SCK", "AF5", "spi2_sck_pb13"),
    "PB14": ("SPI2_MISO", "AF5", "spi2_miso_pb14"),
    "PB15": ("SPI2_MOSI", "AF5", "spi2_mosi_pb15"),
    "PB6": ("I2C4_SCL", "AF5", "i2c4_scl_pb6"),
    "PB7": ("I2C4_SDA", "AF5", "i2c4_sda_pb7"),
    "PB8": ("I2C1_SCL", "AF4", "i2c1_scl_pb8"),
    "PB9": ("I2C1_SDA", "AF4", "i2c1_sda_pb9"),
    "PA15": ("TIM2_CH1", "AF1", "tim2_ch1_pa15"),
    "PB10": ("TIM2_CH3 (input capture)", "AF1", "tim2_ch3_pb10"),
    "PB4": ("GPIO", "out", None),
    "PC13": ("GPIO, EXTI13", "in", None),
    "PC14-OSC32_IN": ("GPIO, EXTI14", "in", None),
    "PC15-OSC32_OUT": ("GPIO, sink only", "out", None),
    "PH3-BOOT0": ("BOOT0", "in", None),
    "PE2": ("GPIO", "io", None), "PE3": ("GPIO", "io", None), "PE4": ("GPIO", "io", None),
    "PE5": ("GPIO", "io", None), "PE6": ("GPIO", "out", None), "PE1": ("GPIO", "out", None),
    "PD8": ("GPIO", "io", None), "PD9": ("GPIO", "io", None), "PD10": ("GPIO", "io", None),
    "PD14": ("GPIO", "io", None), "PD15": ("GPIO", "out", None), "PD7": ("GPIO", "out", None),
    "PD6": ("GPIO, EXTI6", "in", None),
    "PD0": ("GPIO", "io", None), "PD1": ("GPIO", "io", None), "PD2": ("GPIO", "io", None),
    "PD3": ("GPIO", "io", None), "PD4": ("GPIO", "out", None), "PD5": ("GPIO", "out", None),
    "PE0": ("GPIO, EXTI0", "in", None),
    "PC6": ("TIM8_CH1 or GPIO", "AF3", "tim8_ch1_pc6"),
    "PC7": ("TIM8_CH2 or GPIO", "AF3", "tim8_ch2_pc7"),
    "PC8": ("TIM8_CH3 or GPIO", "AF3", "tim8_ch3_pc8"),
    "PC9": ("TIM8_CH4 or GPIO", "AF3", "tim8_ch4_pc9"),
    "PB12": ("GPIO", "out", None), "PC12": ("GPIO", "out", None),
    "PB5": ("GPIO, EXTI5", "in", None),
    "PE9": ("TIM1_CH1", "AF1", "tim1_ch1_pe9"),
    "PE11": ("TIM1_CH2", "AF1", "tim1_ch2_pe11"),
    "PE13": ("TIM1_CH3", "AF1", "tim1_ch3_pe13"),
    "PE8": ("TIM1_CH1N or GPIO", "AF1", "tim1_ch1n_pe8"),
    "PE10": ("TIM1_CH2N or GPIO", "AF1", "tim1_ch2n_pe10"),
    "PE12": ("TIM1_CH3N or GPIO", "AF1", "tim1_ch3n_pe12"),
    "PE14": ("GPIO", "out", None), "PE7": ("GPIO", "out", None),
    # S5_IRQ_N: take it as TIM1_BRK; EXTI15 via gpio_pin_interrupt_configure only (SPEC §5.3)
    "PE15": ("TIM1_BKIN (EXTI15 usable only without gpio_pin_configure)", "AF1", "tim1_bkin_pe15"),
}
for _pin, _chs in LANE_ADC.items():
    MCU_FUNC[_pin] = (" / ".join(_chs), "ANALOG", f"{_chs[0].lower()}_{_pin.lower()}")

# Interrupt inputs: each needs its own EXTI line (one port per line number). SPEC §5.3.
EXTI_INPUTS = ["EXP_INT_N", *[f"S{n}_IRQ_N" for n in SLOTS]]

# --- I2C (SPEC §3.4, §3.8, §4.5) --------------------------------------------------------------------------------
# The bus address maps are built by i2c_buses() below, from these parts.
EXPANDER_I2C = {               # on I2C1; TCA9535 address = 0x20 + its A2-A0 straps
    0x20: "U_EXP1 TCA9535 (rail enables, bus-switch enables)",
    0x21: "U_EXP2 TCA9535 (PRESENT_N, faults, alerts, mux and KVM resets, the USB-C detect interrupt)",
    0x22: "U_EXP3 TCA9535 (S1-S4 G4/G5, slot LEDs)",
}
# INA226 address -> (rail, shunt ohms, the coupon rule on that rail in A or None). Full scale = 81.92 mV / R,
# LSB = 2.5 uV / R (INA226 datasheet SBOS547). Address pins A1/A0 per its Table 2.
INA226_FULL_SCALE_V = 0.08192
INA226_RAILS = {
    0x40: ("VSYS", 0.020, None),         # the whole board, after the input breaker; firmware budget <= 2.8 A (§3.2)
    0x41: ("+3V3_MCU", 0.5, None),       # MCU VDD pins (and, inferred, the HS PHY's internal 1.1 V part: SPEC §3.3)
    0x42: ("+3V3_USB", 1.0, None),       # VDDUSB: the HS PHY's 3.3 V part
    **{0x43 + n: (f"+3V3_S{n}", 0.24, 0.25) for n in SLOTS},           # 0x44-0x48
    **{0x48 + n: (f"+5V_S{n}", 0.1 if n < 5 else 0.020, 0.5 if n < 5 else 2.0) for n in SLOTS},   # 0x49-0x4D
}
# Zephyr's ti,ina226 current-lsb-microamps per monitor (SPEC §3.4, §8.4). The driver sets CAL = 0.00512 / (LSB x R),
# so the LSB is rounded UP: 32768 x LSB must reach the shunt's full scale, or the current register clips below it
# (10 uA on 0.24 ohm would clip at about 328 mA, under the switch's 335 mA maximum trip). check() enforces it.
INA226_CURRENT_LSB_UA = {0x40: 125, 0x41: 5, 0x42: 3, **{0x43 + n: 11 for n in SLOTS},
                         **{0x48 + n: (25 if n < 5 else 125) for n in SLOTS}}

# Trip points of the switch on each measured rail, (min, typ, max) in A (SPEC §3.1). TPS2553: SLVS841E Eq. 1 at
# R_ILIM = 90.9 k (3.3 V) and 45.3 k (5 V), widened for a 1 % resistor (the minimum at R + 1 %, the maximum at
# R - 1 %; an estimate), since Eq. 1 excludes the resistor's tolerance. Eq. 1 names no VIN: SLVS841E's tables hold
# over its recommended VIN of 2.5-6.5 V. TPS259474L circuit breakers: I_LIM = 3334 / R_ILM (ZHCSL91B Eq. 5) at
# 1.47 k (S5) and 1.0 k (input), min/max interpolated from the datasheet's table (-11 % / +9 %): an estimate.
# check(): every minimum is above the rail's coupon rule, and every maximum is inside the INA226's full scale.
SWITCH_TRIP = {
    "VSYS": (2.96, 3.33, 3.62),
    **{f"+3V3_S{n}": (0.256, 0.292, 0.335) for n in SLOTS},
    **{f"+5V_S{n}": (0.519, 0.577, 0.644) for n in SLOTS if n < 5},
    "+5V_S5": (2.01, 2.27, 2.46),
}
VSYS_BUDGET_MAX = 2.8          # A: the firmware's ceiling on the VSYS budget, below the input breaker's minimum

# --- USB Type-C detect, U_CC (SPEC §3.8; owner decision D3, 2026-11-26; the part is a candidate) ---------------
# A sink-only CC controller that presents Rd on CC1/CC2 powered or not (dead-battery Rd: SLLSEQ8D §7.3.3, RCC_DB
# 4.1-6.1 k) and reports the source's Rp advertisement over I2C. It uses no MCU pin.
TYPEC = {
    "ref": "U_CC",
    "part": "TUSB320LAIRWBR",  # TI, X2QFN-12 1.6 x 1.6 mm, 0.4 mm pitch; JLC C132554, 4353 at $1.306 on 2026-11-27
    "bus": "I2C_PM",           # I2C1, which no coupon sees. Fallback if I2C1 exceeds U_CC's 100 pF: mux channel 6
    "addr_strap": "VDD",       # ADDR 4.7 k to +3V3 -> 0x67. Tied low it would be 0x47, INA226 +3V3_S4's address
    "int": "USBC_INT_N",       # INT_N, open drain, 200 k to +3V3, into U_EXP2 P14 (never an MCU pin)
}
TUSB320_ADDR = {"VDD": 0x67, "GND": 0x47}      # SLLSEQ8D Table 5. ADDR left floating = GPIO mode, I2C off
# TUSB320LA X2QFN-12 pin -> (pin name, net). SLLSEQ8D Pin Functions.
TYPEC_PINS = {
    1: ("CC1", "USB_CC1"), 2: ("CC2", "USB_CC2"),   # from J1 through the TPD4E05U06 ESD array
    3: ("PORT", "GND"),                    # tied low: UFP (sink) only
    4: ("VBUS_DET", "CC_VBUS_DET"),        # 887 k 1 % to VBUS at J1 (Rev D: 855-920 k); the pin itself is rated 4 V
    5: ("ADDR", "CC_ADDR"),                # 4.7 k to +3V3: I2C mode, address 0x67
    6: ("INT_N/OUT3", "USBC_INT_N"),
    7: ("SDA/OUT1", "I2C_PM_SDA"), 8: ("SCL/OUT2", "I2C_PM_SCL"),
    9: ("ID", None),                       # attach flag for a source role: not used by a sink
    10: ("GND", "GND"),
    11: ("EN_N", "GND"),                   # always enabled
    12: ("VDD", "+3V3"),                   # 2.7-5 V, >= 3.0 V with 3.3 V I2C, ramp within 25 ms; 100 nF at the pin
}
TYPEC_BUS_NETS = {"I2C_PM": ("I2C_PM_SDA", "I2C_PM_SCL"), "I2C_SLOT": ("I2C_SLOT_SDA", "I2C_SLOT_SCL")}
# CURRENT_MODE_DETECT (register 0x08 bits 5:4), valid in Attached.SNK (register 0x09 bits 7:6 = 0b10), SLLSEQ8D
# Table 8. 0b10 is a charge-through audio accessory (500 mA): treated as Default.
TUSB320_CURRENT_MODE = {0b00: "default", 0b01: "1.5A", 0b10: "default", 0b11: "3.0A"}
# Advertisement -> VSYS budget in A once the host has configured the device (SPEC §3.2, §8.4), capped at
# VSYS_BUDGET_MAX. Before configuration, and again after a USB bus reset or SET_CONFIGURATION(0), the budget is USB
# 2.0's 100 mA whatever is advertised, and no slot is powered. "accessory": ATTACHED_STATE 0b11 (an audio or debug
# accessory). "unreadable": no answer on I2C, which the firmware decides only after U_CC's t_I2C_EN (SLLSEQ8D §6.7).
VSYS_BUDGET_UNCONFIGURED = 0.1
TUSB320_I2C_READY_S = 0.100    # t_I2C_EN max: VDD up and EN_N low to I2C access available (SLLSEQ8D §6.7)
TYPEC_BUDGET = {"default": 0.5, "1.5A": 1.5, "3.0A": 3.0, "accessory": 0.5, "not attached": 0.5, "unreadable": 0.5}


def typec_address():
    """U_CC's 7-bit I2C address from its ADDR strap (None if the strap selects GPIO mode)."""
    return TUSB320_ADDR.get(TYPEC["addr_strap"])


def vsys_budget(advertisement, configured=True):
    """The firmware's VSYS budget in A for what U_CC reports. An operator override may only lower it (SPEC §8.4)."""
    if not configured:
        return VSYS_BUDGET_UNCONFIGURED
    return min(TYPEC_BUDGET[advertisement], VSYS_BUDGET_MAX)


I2C_SLOT_UPSTREAM = {          # I2C4, 400 kHz, 2.2 k pull-ups to +3V3, upstream of the mux
    0x70: "U_MUX TCA9548A: ch0-ch4 = S1-S5, ch5 = KVM, ch6/ch7 = test pads",
}


def i2c_buses():
    """Bus -> [(7-bit address, device)] for every device on it (SPEC §3.4, §4.5). check(): no address twice."""
    buses = {
        "I2C_PM": [*EXPANDER_I2C.items(), *((a, f"INA226 {r[0]}") for a, r in INA226_RAILS.items())],
        "I2C_SLOT": list(I2C_SLOT_UPSTREAM.items()),
    }
    if typec_address() is not None and TYPEC["bus"] in buses:
        buses[TYPEC["bus"]].append((typec_address(), f"{TYPEC['ref']} {TYPEC['part']} (USB-C source advertisement)"))
    return buses


I2C_PM = dict(i2c_buses()["I2C_PM"])       # I2C1, 400 kHz, 2.2 k pull-ups to +3V3. Coupons never see this bus.
I2C_SLOT = dict(i2c_buses()["I2C_SLOT"])   # I2C4 upstream of the mux: every device here is seen on every channel
I2C_RESERVED = (range(0x00, 0x08), range(0x78, 0x80))   # I2C's reserved addresses
COUPON_I2C_RESERVED = {0x70: "the mux itself (visible on every channel)"}
COUPON_I2C_KNOWN = {           # addresses the coupons are expected to use on their own channel (SPEC §4.5, §4.6)
    0x50: "M24C02 coupon descriptor EEPROM (every coupon)",
    0x5A: "DRV2605L (fixed)",
    0x2A: "LDC1614 with ADDR low (the one selected; the others held at 0x2B; addresses unverified here)",
    0x2B: "LDC1614 with ADDR high",
}

EXPANDERS = {
    "U_EXP1": {
        "P00": "EN_3V3_S1", "P01": "EN_3V3_S2", "P02": "EN_3V3_S3", "P03": "EN_3V3_S4", "P04": "EN_3V3_S5",
        "P05": "EN_5V_S1", "P06": "EN_5V_S2", "P07": "EN_5V_S3", "P10": "EN_5V_S4", "P11": "EN_5V_S5",
        "P12": "BUSEN_N_S1", "P13": "BUSEN_N_S2", "P14": "BUSEN_N_S3", "P15": "BUSEN_N_S4", "P16": "BUSEN_N_S5",
        "P17": "EN_5V_KVM",
    },
    "U_EXP2": {
        "P00": "S1_PRESENT_N", "P01": "S2_PRESENT_N", "P02": "S3_PRESENT_N", "P03": "S4_PRESENT_N",
        "P04": "S5_PRESENT_N", "P05": "KVM_PRESENT_N", "P06": "SLOT_FAULT_N", "P07": "PM_ALERT_N",
        "P10": "MUX_RST_N", "P11": "KVM_RST_N", "P12": "VSYS_PG", "P13": "S5_PG",
        "P14": "USBC_INT_N", "P15": None, "P16": None, "P17": None,     # P14: U_CC's interrupt (input)
    },
    "U_EXP3": {
        "P00": "S1_G4", "P01": "S1_G5", "P02": "S2_G4", "P03": "S2_G5",
        "P04": "S3_G4", "P05": "S3_G5", "P06": "S4_G4", "P07": "S4_G5",
        "P10": "LED_S1", "P11": "LED_S2", "P12": "LED_S3", "P13": "LED_S4", "P14": "LED_S5",
        "P15": None, "P16": None, "P17": None,
    },
}
# TCA9535 has no internal pull-ups (SCPS201D) and its pins are inputs after reset: every output gets a resistor that
# holds the safe state until firmware drives it (SPEC §3.5).
EXPANDER_RESET_STATE = {
    "EN_": "100 k pull-down: rail off", "BUSEN_N_": "10 k pull-up: bus switch open",
    "_G4": "100 k pull-down: low into an unpowered slot", "_G5": "100 k pull-down",
    "MUX_RST_N": "10 k pull-up: mux running", "KVM_RST_N": "10 k pull-down: KVM coupon held in reset",
    "LED_S": "LED off (cathode to the pin)",
}
# These hold only after a power-on: the TCA9535 has no reset pin (SCPS201D §10) and the TCA9548A resets only at
# power-on or on RESET, so after an MCU reset the firmware restores them at boot (SPEC §3.5, §8.4).

# --- Headers (SPEC §7) ------------------------------------------------------------------------------------------
J_RIG_PINS = {                 # 2 x 5, 2.54 mm (CJT A2541WV-2x5P, C225520, candidate), ribbon to the latency rig
    1: "RIG_MARK", 2: "GND", 3: "RIG_TRIG", 4: "GND", 5: "SLOT_SYNC", 6: "GND", 7: "USB_SOF", 8: "GND",
    9: "RIG_INJ", 10: "RIG_VREF",          # RIG_VREF: +3V3 through 1 k, a logic-level reference, not a supply
}
J_KVM_PINS = {                 # 2 x 6, 2.54 mm (CJT A2541WV-2x6P, C225521, candidate), the optional KVM coupon
    1: "+5V_KVM", 2: "+5V_KVM", 3: "GND", 4: "GND", 5: "KVM_TX", 6: "KVM_RX", 7: "GND", 8: "KVM_RST_N",
    9: "KVM_SCL", 10: "KVM_SDA", 11: "KVM_PRESENT_N", 12: "GND",
}
J_SWD_PINS = {                 # STDC14 (Samtec FTSH-107-01-L-DV-K, C5307809): UM2448 Rev 5 Table 6, read 2026-11-27
    1: None, 2: None, 3: "+3V3_MCU", 4: "SWDIO", 5: "GND", 6: "SWCLK", 7: "GND", 8: "SWO", 9: None, 10: None,
    11: "GND", 12: "NRST", 13: "CON_RX", 14: "CON_TX",   # 1-2 reserved, do not connect; 11 GNDDetect; 13 T_VCP_RX
}                              # is the target's RX (the probe's TX), 14 T_VCP_TX the target's TX (UM2448 §7.3.4)

ROOT_NOTES = [
    "PrettyCool Keyboard rev A testbed motherboard - DRAFT contract, not captured.\n"
    "Architecture of record: keyboard/hardware/design/SPEC.md; nets and pin map: nets.py.\n"
    "Designed on paper: no schematic, layout, build or measurement yet.",
]


def _gpio(pin):
    """'PC14-OSC32_IN' -> ('C', 14); None for supply pins."""
    if pin.startswith("P") and len(pin) > 2 and pin[1] in "ABCDEH" and pin[2].isdigit():
        num = "".join(ch for ch in pin[2:5] if ch.isdigit())
        return pin[1], int(num)
    return None


def check():
    """Return a list of problems (empty when the contract is self-consistent)."""
    problems = []
    names = list(LQFP100.values())
    if len(LQFP100) != 100 or sorted(LQFP100) != list(range(1, 101)):
        problems.append("LQFP100 must list pins 1-100")
    if set(names) != set(MCU_PINS):
        problems.append(f"MCU_PINS keys != LQFP100 names: missing {sorted(set(names) - set(MCU_PINS))}, "
                        f"extra {sorted(set(MCU_PINS) - set(names))}")
    known = set(POWER_NETS) | set(INTERSHEET) | set(MCU_LOCAL)
    seen = {}
    for pin, net in MCU_PINS.items():
        if net is None:
            continue
        if net not in known:
            problems.append(f"{pin}: net {net} is not a power, intersheet, slot or MCU-local net")
        if net not in POWER_NETS:
            if net in seen:
                problems.append(f"{net} on two pins: {seen[net]} and {pin}")
            seen[net] = pin
    for pin, net in MCU_PINS.items():
        if _gpio(pin) and net and pin not in MCU_FUNC:
            problems.append(f"{pin}: no entry in MCU_FUNC")
    for n in SLOTS:
        for sig in SLOT_SIGNALS:
            pin = SLOT_MCU[n].get(sig)
            if pin is not None:
                if MCU_PINS.get(pin) != mcu_net(n, sig):
                    problems.append(f"S{n} {sig}: SLOT_MCU says {pin}, MCU_PINS has {MCU_PINS.get(pin)}")
                if sig.startswith("AN") and pin not in LANE_ADC:
                    problems.append(f"S{n} {sig}: {pin} has no ADC channel")
                continue
            other = mcu_net(n, sig)
            in_exp = any(other in pins.values() for pins in EXPANDERS.values())
            if sig in BUS_SWITCHED or sig in ("SCL", "SDA", "INJ"):
                if sig != "INJ" and other not in MCU_PINS.values():
                    problems.append(f"S{n} {sig}: shared net {other} is on no MCU pin")
            elif not in_exp:
                problems.append(f"S{n} {sig}: not on the MCU and not on an expander")
    lines = {}
    for net in EXTI_INPUTS:
        pin = next((p for p, x in MCU_PINS.items() if x == net), None)
        if pin is None:
            problems.append(f"interrupt {net} is on no MCU pin")
            continue
        line = _gpio(pin)[1]
        if line in lines:
            problems.append(f"EXTI{line} shared by {lines[line]} and {net}")
        lines[line] = net
    exp_nets = [x for pins in EXPANDERS.values() for x in pins.values() if x]
    for x in exp_nets:
        if exp_nets.count(x) > 1:
            problems.append(f"{x} on two expander pins")
        if x not in known:
            problems.append(f"expander net {x} is not declared")
    lq_names = set(LQFP100.values())
    for alias, name in KICAD_PIN_ALIAS.items():
        if alias in lq_names or name not in lq_names:
            problems.append(f"KiCad alias {alias} -> {name}: the alias must be new and the name an LQFP100 pin")
        elif LQFP100.get(KICAD_ALIAS_PIN_NUMBER.get(alias)) != name:
            problems.append(f"KiCad alias {alias} is not on the pin number of {name}")
    for net, (to, ohms) in MCU_SIDE_PULLS.items():
        if net not in known or to not in POWER_NETS or not ohms > 0:
            problems.append(f"pull on {net}: unknown net or rail")
    if any(not 0x40 <= a <= 0x4F for a in INA226_RAILS):
        problems.append("INA226 addresses must be 0x40-0x4F")
    # I2C: no address twice on one bus, none in I2C's reserved ranges (SPEC §3.4)
    buses = i2c_buses()
    for bus, devices in buses.items():
        on_bus = {}
        for a, dev in devices:
            if any(a in r for r in I2C_RESERVED):
                problems.append(f"{bus}: 0x{a:02X} ({dev}) is a reserved I2C address")
            if a in on_bus:
                problems.append(f"0x{a:02X} used twice on {bus}: {on_bus[a]} and {dev}")
            on_bus[a] = dev
    for a, dev in buses["I2C_SLOT"]:          # upstream of the mux: seen on every coupon's channel (SPEC §4.5)
        if a not in COUPON_I2C_RESERVED:
            problems.append(f"I2C_SLOT 0x{a:02X} ({dev}) is seen on every mux channel but not reserved for coupons")
    # USB Type-C detect U_CC (SPEC §3.8): sink only, on its bus, interrupt on an expander, no MCU pin
    if typec_address() is None:
        problems.append(f"U_CC ADDR strap {TYPEC['addr_strap']} is not an I2C address (floating = GPIO mode)")
    if TYPEC["bus"] not in buses:
        problems.append(f"U_CC bus {TYPEC['bus']} is not an I2C bus of this board")
    cc = {name: net for name, net in TYPEC_PINS.values()}
    if sorted(TYPEC_PINS) != list(range(1, 13)):
        problems.append("TYPEC_PINS must list pins 1-12")
    if cc.get("PORT") != "GND":
        problems.append("U_CC PORT must be tied low: sink (UFP) only")
    if cc.get("EN_N") != "GND":
        problems.append("U_CC EN_N must be tied low: always enabled")
    if (cc.get("SDA/OUT1"), cc.get("SCL/OUT2")) != TYPEC_BUS_NETS.get(TYPEC["bus"]):
        problems.append(f"U_CC SDA/SCL are not on {TYPEC['bus']}")
    if cc.get("INT_N/OUT3") != TYPEC["int"]:
        problems.append("U_CC INT_N is not on its interrupt net")
    if TYPEC["int"] in MCU_PINS.values():
        problems.append(f"{TYPEC['int']} is on an MCU pin: the Type-C detect must use none")
    if not any(TYPEC["int"] in pins.values() for pins in EXPANDERS.values()):
        problems.append(f"{TYPEC['int']} reaches no expander input")
    for name, net in cc.items():
        if net and net not in known and net not in USBC_LOCAL:
            problems.append(f"U_CC {name}: net {net} is not declared")
    for adv in TYPEC_BUDGET:
        if not 0 < vsys_budget(adv) <= VSYS_BUDGET_MAX:
            problems.append(f"VSYS budget for {adv} is outside 0-{VSYS_BUDGET_MAX} A")
    if set(TUSB320_CURRENT_MODE.values()) - set(TYPEC_BUDGET):
        problems.append("a U_CC current mode has no VSYS budget")
    for a in COUPON_I2C_KNOWN:
        if a in COUPON_I2C_RESERVED:
            problems.append(f"coupon address 0x{a:02X} collides with the mux")
    if set(INA226_CURRENT_LSB_UA) != set(INA226_RAILS):
        problems.append("INA226_CURRENT_LSB_UA must list every INA226")
    for a, (rail, shunt, _) in INA226_RAILS.items():
        lsb = INA226_CURRENT_LSB_UA.get(a, 0) * 1e-6
        if 32768 * lsb < INA226_FULL_SCALE_V / shunt * (1 - 1e-9):
            problems.append(f"INA226 0x{a:02X} {rail}: current LSB {lsb * 1e6:g} uA clips below the shunt's full scale")
    for rail, shunt, rule in INA226_RAILS.values():
        if rail not in POWER_NETS:
            problems.append(f"INA226 rail {rail} is not a power net")
        trip = SWITCH_TRIP.get(rail)
        if rule is not None and trip is None:
            problems.append(f"{rail}: a coupon rule but no switch trip point")
        if trip is None:
            continue
        lo, typ, hi = trip
        if not lo <= typ <= hi:
            problems.append(f"{rail}: trip points out of order {trip}")
        if rule is not None and lo <= rule:
            problems.append(f"{rail}: switch minimum trip {lo} A is not above the coupon rule {rule} A")
        if hi > INA226_FULL_SCALE_V / shunt:
            problems.append(f"{rail}: switch maximum trip {hi} A is beyond the INA226 full scale "
                            f"{INA226_FULL_SCALE_V / shunt:.3f} A")
    if VSYS_BUDGET_MAX >= SWITCH_TRIP["VSYS"][0]:
        problems.append("the VSYS budget ceiling must sit below the input breaker's minimum trip")
    for hdr in (J_RIG_PINS, J_KVM_PINS, J_SWD_PINS):
        for net in hdr.values():
            if net and net not in known and net != "RIG_VREF":
                problems.append(f"header net {net} is not declared")
    return problems


if __name__ == "__main__":
    issues = check()
    used = sum(1 for p, net in MCU_PINS.items() if _gpio(p) and net)
    io = sum(1 for p in MCU_PINS if _gpio(p))
    free_exp = sum(1 for pins in EXPANDERS.values() for net in pins.values() if net is None)
    print(f"{MCU} rev {REV} ({DATE}): {io} I/O pins, {used} used, {len(SLOT_NETS)} slot nets, "
          f"{len(INA226_RAILS)} INA226 rails, {free_exp} free expander pins")
    for bus, devices in i2c_buses().items():
        print(f"{bus}: " + ", ".join(f"0x{a:02X}" for a, _ in sorted(devices)))
    print("\n".join(issues) if issues else "OK: contract self-consistent")
    raise SystemExit(1 if issues else 0)
