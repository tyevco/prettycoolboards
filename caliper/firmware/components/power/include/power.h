/*
 * power: charger (BQ25180), fuel gauge (MAX17048), IMU (LSM6DSO: orientation while awake, pickup
 * wake while asleep), backlight / buzzer / RGB LED, die-temperature charge guard, and deep sleep.
 */
#pragma once

#include <stdbool.h>
#include <stddef.h>
#include <stdint.h>

#include "driver/i2c_master.h"
#include "esp_err.h"
#include "orient.h"

#ifdef __cplusplus
extern "C" {
#endif

typedef struct {
    bool charger_ok;
    bool gauge_ok;
    bool imu_ok;
    uint8_t soc_pct;      /* MAX17048 state of charge */
    uint16_t vcell_mv;
    bool vbus;            /* BQ25180 VIN_PGOOD */
    uint8_t chg_stat;     /* 0 not charging, 1 CC, 2 CV, 3 done */
    bool charging;        /* CC or CV */
    bool chg_disabled;    /* by the temperature guard or a TS fault */
    bool ts_open;         /* STAT0.TS_OPEN_STAT: NTC missing or open */
    float die_c;
    uint8_t stat0, stat1, flag0;
} power_status_t;

esp_err_t power_init(void);             /* I2C bus + all three chips; individual failures are logged */
i2c_master_bus_handle_t power_i2c_bus(void);
void power_poll(power_status_t *out);   /* call at about 1 Hz */
void power_usb_configured(bool configured); /* ILIM 100 mA before enumeration, 500 mA after */

/* ---- bring-up diagnostics (the CLI "bu" commands) ---- */
typedef struct {
    uint8_t reg, val;
} power_reg_t;
void power_get_last(power_status_t *out); /* the last power_poll() result (about 1 s old) */
/* The BQ25180 register values power_init writes, with the live ICHG_CTRL (CHG_DIS from the
 * temperature guard) and TMR_ILIM (USB input limit). Returns the entry count (fills up to max). */
size_t power_bq_table(power_reg_t *out, size_t max);
/* Reads n bytes from reg of one of the three chips (I2C_ADDR_BQ25180 / _MAX17048 / _LSM6DSO):
 * ESP_ERR_NOT_FOUND for any other address. Thread-safe (the I2C driver's bus lock). */
esp_err_t power_diag_read(uint8_t addr, uint8_t reg, uint8_t *buf, size_t n);

/* ---- IMU / orientation (imu.c) ---- */
/* Starts the 50 Hz sampler task that reads the LSM6DSO (accelerometer + gyroscope at 52 Hz,
 * low-power mode) and runs the orientation filter of components/measure/orient.h. Call once, after
 * power_init(). ESP_ERR_INVALID_STATE if the IMU did not answer: the caliper works without it. */
esp_err_t power_imu_start(void);
/* The latest orientation, in the board frame of orient.h (+x beam toward the USB end, +y toward the
 * buttons, +z out of the display). False (and out->valid false) until the filter has seen gravity,
 * and for good when there is no IMU. Thread-safe; about 20 ms old at most. */
bool power_orient_get(orient_out_t *out);
void power_orient_zero_yaw(void); /* the relative yaw counts from here; thread-safe */
/* The last sample as the filter got it (board frame, no bias removed), for the bring-up commands. */
typedef struct {
    float acc_g[3];
    float gyro_dps[3];
    float temp_c;      /* the IMU's own die temperature */
    bool gyro_clipped; /* an axis at full scale (+-1000 dps) */
    uint32_t samples;  /* samples taken since power_imu_start() */
    uint32_t errors;   /* I2C reads that failed */
} power_imu_sample_t;
bool power_imu_last(power_imu_sample_t *out); /* false until the first sample */

/* ---- user-facing outputs ---- */
esp_err_t power_outputs_init(void);
void power_backlight(uint8_t pct);      /* 0..100, LEDC PWM on LCD_BL */
void power_beep(uint32_t ms);           /* piezo on BUZZ */
void power_led(uint8_t r, uint8_t g, uint8_t b);

/* ---- sleep ---- */
/* Puts the IMU into its sleep mode (gyroscope off, accelerometer ultra-low-power 12.5 Hz, wake-up
 * interrupt on INT1), ext1 wake on IMU_INT1 + buttons + CHG_INT_N, gates the sensor rail and enters
 * deep sleep. Does not return. */
void power_deep_sleep(void) __attribute__((noreturn));
/* Ship mode (BQ25180 disconnects the battery). Rev A has no button on TS/MR: only USB wakes it.
 * Puts the MAX17048 (which stays on VBAT) into sleep first: in ship mode +3V3 and the I2C pull-ups
 * are gone and its SDA/SCL float. ESP_ERR_INVALID_STATE without a charger, ESP_FAIL if the BQ25180
 * write failed. With VBUS present the BQ25180 enters ship mode only once the cable is removed
 * (SLUSE99C §8.3.11: a pending ship request waits for the adapter removal); the gauge is then left
 * awake but armed (MODE.EnSleep, forced hibernate) and sleeps once its bus is held low (power.c). */
esp_err_t power_ship_mode(void);
/* Drives the LCD and RGB LED lines low with no pull (they feed +3V3_UI, which SNS_PWR_EN switches
 * off): their SLEEP state from the pin plan. */
void power_ui_lines_low(void);
const char *power_wake_cause(void);
/* Call first thing after boot: releases the pads held through deep sleep. */
void power_release_holds(void);

#ifdef __cplusplus
}
#endif
