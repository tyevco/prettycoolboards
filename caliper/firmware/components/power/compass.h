/* compass.c's interface to the rest of the power component (the public part is in include/power.h). */
#pragma once

#include <stdbool.h>
#include <stddef.h>
#include <stdint.h>

#include "driver/i2c_master.h"
#include "esp_err.h"
#include "orient.h"

/* Adds the IIS2MDC to the bus, resets it and writes the awake configuration (continuous 10 Hz,
 * low-power, offset cancellation, low-pass filter, temperature compensation, BDU).
 * ESP_ERR_NOT_FOUND if nothing answers at 0x1E or on a wrong WHO_AM_I: logged once, and the caliper
 * works without it (U61 not populated). */
esp_err_t power_compass_init(i2c_master_bus_handle_t bus);
esp_err_t power_compass_diag_read(uint8_t reg, uint8_t *buf, size_t n);
/* One poll, from the IMU sampler at 10 Hz (the part has no interrupt line). True with a NEW sample
 * in uT, board frame, nothing calibrated out; false: no compass, no new sample yet, or a failed read. */
bool power_compass_poll(orient_vec_t *b_ut);
/* Before deep sleep, after power_imu_sleep_prepare() has stopped the sampler: power-down. */
void power_compass_sleep_prepare(void);
