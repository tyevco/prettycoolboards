/* Host-test stub: an NVS with nothing stored that accepts and forgets writes. */
#pragma once

#include <stddef.h>
#include <stdint.h>

#include "esp_err.h"

typedef uint32_t nvs_handle_t;
typedef enum { NVS_READONLY, NVS_READWRITE } nvs_open_mode_t;
#define ESP_ERR_NVS_NOT_FOUND 0x1102

static inline esp_err_t nvs_open(const char *ns, nvs_open_mode_t m, nvs_handle_t *h)
{
    (void)ns;
    *h = 1;
    return m == NVS_READONLY ? ESP_ERR_NVS_NOT_FOUND : ESP_OK;
}
static inline void nvs_close(nvs_handle_t h) { (void)h; }
static inline esp_err_t nvs_get_str(nvs_handle_t h, const char *k, char *v, size_t *l)
{
    (void)h, (void)k, (void)v, (void)l;
    return ESP_ERR_NVS_NOT_FOUND;
}
static inline esp_err_t nvs_set_str(nvs_handle_t h, const char *k, const char *v)
{
    (void)h, (void)k, (void)v;
    return ESP_OK;
}
static inline esp_err_t nvs_get_u8(nvs_handle_t h, const char *k, uint8_t *v)
{
    (void)h, (void)k, (void)v;
    return ESP_ERR_NVS_NOT_FOUND;
}
static inline esp_err_t nvs_get_u16(nvs_handle_t h, const char *k, uint16_t *v)
{
    (void)h, (void)k, (void)v;
    return ESP_ERR_NVS_NOT_FOUND;
}
static inline esp_err_t nvs_set_u8(nvs_handle_t h, const char *k, uint8_t v)
{
    (void)h, (void)k, (void)v;
    return ESP_OK;
}
static inline esp_err_t nvs_set_u16(nvs_handle_t h, const char *k, uint16_t v)
{
    (void)h, (void)k, (void)v;
    return ESP_OK;
}
static inline esp_err_t nvs_commit(nvs_handle_t h)
{
    (void)h;
    return ESP_OK;
}
