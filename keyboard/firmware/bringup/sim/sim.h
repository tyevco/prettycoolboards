/*
 * The simulated testbed motherboard (native_sim): a model of what the bring-up firmware sees through its buses,
 * shared by the register models of the parts (emul_*.c) and the sim commands (sim_cmds.c).
 *
 * A SIMULATION. It is built from the same devicetree as the board (gen_board.py's sim overlay) and the same
 * nets.py numbers, so it tests the firmware's logic and protocol: sequencing, budget rules, fault handling,
 * descriptor handling, the self-test's arithmetic. It cannot test the hardware: its physics are a few lines of
 * Ohm's law and the switches' trip windows, its timing is native_sim's, and every part behaves as its register
 * model here says, which is this code's reading of the datasheets.
 *
 * SPDX-License-Identifier: Apache-2.0
 */
#ifndef TB_SIM_H_
#define TB_SIM_H_

#include <stdbool.h>
#include <stdint.h>

#include "tb/rails.h"

enum sim_coupon_kind {
	SIM_NONE = 0,
	SIM_TEST,       /* the test coupon, its descriptor written */
	SIM_TEST_BLANK, /* the test coupon, its EEPROM erased */
	SIM_HALL,       /* a coupon with a minimal Hall descriptor and a 30 mA 3.3 V draw */
	/* The test coupon plugged in turned 180 degrees. The slot key (D2 of 2026-11-27: coupon pin 39 absent,
	 * socket hole 39 plugged) stops this, so it models a socket whose plug was not fitted. Slot pin p meets
	 * coupon pin 41 - p (nets.SLOT_PINS): PRESENT_N (32) meets its GND (9), so the slot reads present; SCL (29)
	 * meets its GND (12), so nothing answers on the slot's channel (modelled as a NAK: the real bus is held low,
	 * which jams I2C4 while the channel is selected, risks.md EL-2, not modelled); IRQ_N (31) meets a GND (10);
	 * CS0_N (27) a GND (14); G0/G1 (33, 34) its +3V3 (8, 7). */
	SIM_TURNED,
};

struct sim_exp {
	uint16_t out, pol, cfg;
	uint16_t last_read; /* the input register as last read (TCA9535 INT: a change since then) */
	bool int_pending;
};

struct sim_world {
	enum sim_coupon_kind coupon[TB_SLOTS];
	uint8_t eeprom[TB_SLOTS][256];
	struct sim_exp exp[3];
	uint8_t mux_ctrl;
	/* U_CC */
	uint8_t cc_attach; /* ATTACHED_STATE 0..3 */
	uint8_t cc_mode;   /* CURRENT_MODE_DETECT 0..3 */
	bool cc_int;
	bool cc_absent;    /* no U_CC on the bus */
	/* injected */
	uint32_t extra_ua[TB_RAIL_COUNT];
	bool vsys_pg_low;
	/* derived each update */
	bool on[TB_RAIL_COUNT];
	bool limiting[TB_RAIL_COUNT];
	int64_t limit_since_ms[TB_RAIL_COUNT], limit_end_ms[TB_RAIL_COUNT];
	bool s5_latched;
	int32_t ua[TB_RAIL_COUNT], mv[TB_RAIL_COUNT];
	int32_t uv3[TB_SLOTS]; /* each slot's +3V3 at the coupon, uV */
	int32_t vsys_ua, vsys_mv;
	bool fault_n, alert_n;
	uint32_t updates;
	/* the USB state the sim's own "sim usb" commands have put the host in (for the rule monitor below) */
	bool usb_configured, usb_suspended;
	int64_t usb_change_ms;
};

extern struct sim_world sim;

/*
 * The SPEC §3.5 rule monitor. Each sim_update() checks the board's physical state, as the expanders, the mux
 * and the MCU's pins set it, against the slot power rules, independently of the firmware's own bookkeeping:
 *  - +5V_Sn on while +3V3_Sn is off (3.3 V first, and off last);
 *  - a rail of slot n switched on or off while its bus switch is closed ("close the slot's bus switch only after
 *    its rails are up, open it before they go down");
 *  - a rail of slot n switched on while no coupon is in it (PRESENT_N high);
 *  - slot n's bus switch closed, or its mux channel selected, while +3V3_Sn is off;
 *  - a line that goes straight to slot n (CS0_N, CS1_N, IRQ_N, G0-G5, U_EXP3's G4/G5 included) driven high
 *    while +3V3_Sn is off (SPEC §3.5: low or high-impedance only);
 *  - an MCU line that goes straight to slot n (CS0_N, CS1_N, G0-G5) driven at either level, or its bus switch
 *    closed, while a turned coupon (SIM_TURNED) is in it: the firmware drives a slot's lines only after a valid
 *    descriptor (SPEC §4.6, risks.md EL-2), which a turned coupon cannot give;
 *  - a rail switched on while the host has not configured the device, or is suspending it (bench mode, the
 *    operator's declaration, excepted), and a rail still on SIM_USB_GRACE_MS after the host left that state.
 * A violation is counted and the first one kept; "sim state" prints both and every test asserts none.
 * SIM_USB_GRACE_MS is a native_sim allowance for the service thread to run, not USB 2.0's 10 ms suspend limit.
 */
#define SIM_USB_GRACE_MS 200
extern uint32_t sim_rule_violations;
extern char sim_first_violation[64];

/* Re-evaluate the model (rails, loads, flags, the MCU's input pins). Cheap; call after anything changes. */
void sim_update(void);
/* The TCA9535 input register of expander i (0..2), as the pins read now. */
uint16_t sim_exp_inputs(int i);
/* Is a slot's +3V3 on and its coupon the test coupon (the loopback and lane models)? */
bool sim_test_coupon_powered(int slot);
/* The physical level the firmware drives on an MCU pin of a slot (G-lines, CS, SYNC), 0 if not an output. */
int sim_mcu_out(const void *gpio_dt_spec);
/* Slot whose bus switch is closed, or 0 (the first if several). */
int sim_bus_slot(void);
/* A G-line's level on a slot (MCU pin or U_EXP3), 0 if not driven. */
int sim_gline(int slot, int g);
/* The current and voltage an INA226 at addr measures. */
void sim_monitor(uint8_t addr, int32_t *ua, int32_t *mv);
/* Program a coupon into a slot (its EEPROM image too). */
void sim_set_coupon(int slot, enum sim_coupon_kind kind);
/* The firmware's PM_ALERT_N input: any INA226 model with its latched alert flag set. */
bool sim_ina_any_alert(void);

#endif /* TB_SIM_H_ */
