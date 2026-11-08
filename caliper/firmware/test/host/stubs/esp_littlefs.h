/* Host-test stub: the "LittleFS partition" is a plain directory (STORE_BASE_PATH). POSIX files do
 * not model LittleFS's atomic commits; the store tests cover the layout, the ring and the scan. */
#pragma once

#include <stdbool.h>
#include <stddef.h>
#include <sys/stat.h>

#include "esp_err.h"

typedef struct {
    const char *base_path;
    const char *partition_label;
    bool format_if_mount_failed;
    bool dont_mount;
} esp_vfs_littlefs_conf_t;

static inline esp_err_t esp_vfs_littlefs_register(const esp_vfs_littlefs_conf_t *c)
{
    mkdir(c->base_path, 0777);
    return ESP_OK;
}

static inline esp_err_t esp_littlefs_info(const char *label, size_t *total, size_t *used)
{
    (void)label;
    *total = 0;
    *used = 0;
    return ESP_OK;
}
