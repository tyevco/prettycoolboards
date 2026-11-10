/* imu.c's interface to the rest of the power component (the public part is in include/power.h). */
#pragma once

#include <stdbool.h>
#include <stddef.h>
#include <stdint.h>

#include "driver/i2c_master.h"
#include "esp_err.h"

/* Adds the LSM6DSO to the bus, resets it and writes the awake configuration (accelerometer +
 * gyroscope at 52 Hz, low-power mode, wake-up on INT1). ESP_ERR_NOT_FOUND on a wrong WHO_AM_I. */
esp_err_t power_imu_init(i2c_master_bus_handle_t bus);
esp_err_t power_imu_diag_read(uint8_t reg, uint8_t *buf, size_t n);
/* Before deep sleep: stops the sampler, gyroscope off, accelerometer to ultra-low-power 12.5 Hz
 * with the wake-up interrupt on INT1, latch cleared. True only if IMU_INT1 then reads high (the
 * ext1 wake is ANY_LOW: a low INT1 would wake the caliper at once, forever). */
bool power_imu_sleep_prepare(void);
