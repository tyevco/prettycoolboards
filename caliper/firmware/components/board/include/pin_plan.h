/*
 * The pin plan: the state of every ESP32-S3 GPIO in each power mode (RESET, RUN, SLEEP, SHIP).
 *
 * Source of truth: firmware/tools/pin_plan.py (PLAN). It generates components/board/pin_plan_table.c
 * (checked at CMake time like board_pins.h) and, through tools/export_pinstate.py, the hwtools
 * pinstate.json that the leakage check (pullaudit) reads. The firmware APPLIES this table
 * (pin_plan_apply.c): the sleep entry, the plain GPIOs at boot and the pulls of the driver-owned pads,
 * so what the leakage check sees is what the firmware does. Invariants: test/host/test_pin_plan.c.
 * Background and the hwtools result: docs/firmware.md "Pin plan and sleep leakage".
 *
 * The table and the helpers below are portable C (host-tested); the apply functions need ESP-IDF.
 */
#pragma once

#include <stdbool.h>
#include <stddef.h>
#include <stdint.h>

#ifdef __cplusplus
extern "C" {
#endif

typedef enum { PP_MODE_RESET, PP_MODE_RUN, PP_MODE_SLEEP, PP_MODE_SHIP, PP_MODE_COUNT } pp_mode_t;

typedef enum {
    PP_DIR_OFF,    /* unpowered (SHIP) */
    PP_DIR_IN,     /* input enabled */
    PP_DIR_OUT,    /* push-pull output, level = driven level */
    PP_DIR_OD,     /* open-drain output, level 1 = released */
    PP_DIR_HIZ,    /* input and output disabled */
    PP_DIR_PERIPH, /* a peripheral owns the pad: only the pulls are the plan's, level = idle level */
} pp_dir_t;

typedef enum { PP_PULL_NONE, PP_PULL_UP, PP_PULL_DOWN } pp_pull_t;

#define PP_LEVEL_NONE 0xFFu

typedef enum {
    PP_EXT_NONE,      /* nothing that conducts DC */
    PP_EXT_PULL_UP,   /* a resistor (or a chip's internal pull) to ext.rail */
    PP_EXT_PULL_DOWN, /* a resistor to GND */
    PP_EXT_DRIVEN,    /* another chip drives the net (push-pull, from ext.rail) */
    PP_EXT_LOAD,      /* a CMOS input / ESD clamp of a chip powered from ext.rail */
} pp_ext_kind_t;

typedef enum { PP_RAIL_NONE, PP_RAIL_3V3, PP_RAIL_SNS, PP_RAIL_UI } pp_rail_t;

typedef enum {
    PP_INIT_NONE,
    PP_INIT_BOARD,      /* app_main applies the RUN state at boot */
    PP_INIT_SENSOR_MAG, /* sensor_mag_init applies it (it sequences the rail itself) */
    PP_INIT_BUTTONS,    /* the buttons task applies it */
    PP_INIT_DRIVER,     /* a peripheral driver configures it; pin_plan_apply_pulls() sets the pulls after */
} pp_init_t;

typedef struct {
    uint8_t dir;   /* pp_dir_t */
    uint8_t level; /* 0, 1 or PP_LEVEL_NONE */
    uint8_t pull;  /* pp_pull_t */
    bool hold;     /* latched through deep sleep */
    bool wake;     /* ext1 wake source */
} pp_state_t;

typedef struct {
    uint8_t kind; /* pp_ext_kind_t */
    uint8_t rail; /* pp_rail_t */
    uint32_t ohm; /* 0 = not a resistor / unknown */
    const char *what;
} pp_ext_t;

typedef struct {
    uint8_t gpio;
    const char *net;
    const char *owner; /* the peripheral that owns the pad in RUN, "" for a plain GPIO */
    uint8_t init;      /* pp_init_t */
    bool untouched;    /* never written by the pin-plan code (USB D-/D+) */
    pp_ext_t ext;
    pp_state_t st[PP_MODE_COUNT];
} pin_plan_t;

extern const pin_plan_t PIN_PLAN[];
extern const size_t PIN_PLAN_COUNT;
extern const char PIN_PLAN_HASH[];

/* ---- portable helpers (pin_plan.c) ---- */
const pin_plan_t *pin_plan_find(int gpio);
bool pin_plan_is_rtc_gpio(int gpio);                 /* ESP32-S3 RTC GPIOs: 0-21 */
bool pin_plan_rail_on(uint8_t rail, pp_mode_t mode); /* is that rail powered in that mode */
uint64_t pin_plan_init_mask(pp_init_t init);         /* pins whose RUN state that owner applies */
uint64_t pin_plan_wake_mask(void);                   /* SLEEP wake pins (the ext1 mask) */
uint64_t pin_plan_rail_mask(pp_rail_t rail);         /* pins whose external circuit sits on that rail */
const char *pin_plan_mode_name(pp_mode_t mode);

/* ---- ESP-IDF only (pin_plan_apply.c) ---- */
#ifndef PIN_PLAN_HOST
#include "esp_err.h"
#define PP_APPLY_LEVEL 0x1u /* drive out / od pins to the plan's level (else keep the output register) */
#define PP_APPLY_HOLD 0x2u  /* latch the pins the plan holds in that mode (+ gpio_deep_sleep_hold_en) */
/* Configures every pin in mask (except periph and untouched ones) to its state in mode. */
esp_err_t pin_plan_apply(pp_mode_t mode, uint64_t mask, unsigned flags);
/* Sets only the internal pulls (pad and, in SLEEP, RTC) of the pins in mask, periph pins included. */
esp_err_t pin_plan_apply_pulls(pp_mode_t mode, uint64_t mask);
/* Releases every pad the SLEEP plan holds (call first thing after a deep-sleep wake). */
void pin_plan_release_holds(void);
#endif

#ifdef __cplusplus
}
#endif
