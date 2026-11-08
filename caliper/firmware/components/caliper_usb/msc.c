/*
 * USB mass storage: the "msc" FAT partition (wear-levelled) with one file, LOG.CSV.
 * The app owns the medium only while it rewrites the file; the rest of the time the host does.
 */
#include <stdio.h>

#include "caliper_core.h"
#include "caliper_usb.h"
#include "esp_log.h"
#include "esp_partition.h"
#include "freertos/FreeRTOS.h"
#include "freertos/semphr.h"
#include "sdkconfig.h"
#include "store.h"

#if CONFIG_CALIPER_USB_MSC
#include "tusb_msc_storage.h"
#include "wear_levelling.h"

static const char *TAG = "msc";
#define MSC_BASE "/usb"

static wl_handle_t s_wl = WL_INVALID_HANDLE;
static bool s_ready;
/* msc_export() runs from the app task (host attach) and the CLI task ("export"): two at once would
 * mount the FAT twice and write LOG.CSV from both (2026-11-07 review) */
static SemaphoreHandle_t s_xlock;

esp_err_t msc_init(void)
{
    const esp_partition_t *p =
        esp_partition_find_first(ESP_PARTITION_TYPE_DATA, ESP_PARTITION_SUBTYPE_DATA_FAT, "msc");
    if (!p) {
        ESP_LOGE(TAG, "no \"msc\" partition");
        return ESP_ERR_NOT_FOUND;
    }
    s_xlock = xSemaphoreCreateMutex();
    if (!s_xlock) {
        return ESP_ERR_NO_MEM;
    }
    esp_err_t err = wl_mount(p, &s_wl);
    if (err != ESP_OK) {
        return err;
    }
    const tinyusb_msc_spiflash_config_t cfg = {
        .wl_handle = s_wl,
        .mount_config = {.format_if_mount_failed = true, .max_files = 2},
    };
    err = tinyusb_msc_storage_init_spiflash(&cfg);
    s_ready = err == ESP_OK;
    return err;
}

static esp_err_t file_writer(void *ctx, const char *buf, size_t len)
{
    return fwrite(buf, 1, len, (FILE *)ctx) == len ? ESP_OK : ESP_FAIL;
}

esp_err_t msc_export(void)
{
    if (!s_ready) {
        return ESP_ERR_INVALID_STATE;
    }
    xSemaphoreTake(s_xlock, portMAX_DELAY);
    /* take the medium from the host (it sees "not ready" for a moment) */
    esp_err_t err = tinyusb_msc_storage_mount(MSC_BASE);
    if (err != ESP_OK) {
        xSemaphoreGive(s_xlock);
        ESP_LOGE(TAG, "mount: %s", esp_err_to_name(err));
        return err;
    }
    settings_t s;
    core_get_settings(&s);
    FILE *f = fopen(MSC_BASE "/LOG.CSV", "w");
    if (f) {
        err = store_log_export_csv(false, s.decimals, file_writer, f);
        if (fclose(f) != 0 && err == ESP_OK) {
            err = ESP_FAIL; /* the last buffered block did not fit either */
        }
    } else {
        err = ESP_FAIL;
    }
    tinyusb_msc_storage_unmount(); /* give it back to the host */
    xSemaphoreGive(s_xlock);
    if (err != ESP_OK) {
        /* most likely the FAT is full: LOG.CSV is cut short (the 4 MB layout's 192 KiB "msc"
         * partition holds a full 4096-record log only with short lines) */
        ESP_LOGE(TAG, "LOG.CSV export incomplete (%lu records in the log): %s", (unsigned long)store_log_count(),
                 esp_err_to_name(err));
    } else {
        ESP_LOGI(TAG, "LOG.CSV exported (%lu records)", (unsigned long)store_log_count());
    }
    return err;
}

#else

esp_err_t msc_init(void)
{
    return ESP_ERR_NOT_SUPPORTED;
}

esp_err_t msc_export(void)
{
    return ESP_ERR_NOT_SUPPORTED;
}

#endif
