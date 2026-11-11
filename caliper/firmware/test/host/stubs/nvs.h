/* Host-test stub: an NVS with nothing stored that accepts and forgets writes, except the u16 values:
 * those it keeps (NVS_STUB_U16 of them, in RAM, one table per source file), so that a save / load
 * pair can be tested. */
#pragma once

#include <stddef.h>
#include <stdint.h>
#include <string.h>

#include "esp_err.h"

typedef uint32_t nvs_handle_t;
typedef enum { NVS_READONLY, NVS_READWRITE } nvs_open_mode_t;
#define ESP_ERR_NVS_NOT_FOUND 0x1102

#define NVS_STUB_U16 8
static struct {
    const char *k; /* NULL = free; the keys are string literals */
    uint16_t v;
} nvs_stub_u16[NVS_STUB_U16];

/* the slot of key k, or of the first free one if k is NULL; -1 if there is none */
static inline int nvs_stub_slot(const char *k)
{
    for (int i = 0; i < NVS_STUB_U16; i++) {
        if (k ? nvs_stub_u16[i].k && strcmp(nvs_stub_u16[i].k, k) == 0 : !nvs_stub_u16[i].k) {
            return i;
        }
    }
    return -1;
}

static inline esp_err_t nvs_open(const char *ns, nvs_open_mode_t m, nvs_handle_t *h)
{
    (void)ns;
    *h = 1;
    /* as the real one: a namespace nothing was ever written to cannot be opened read-only */
    return m == NVS_READONLY && !nvs_stub_u16[0].k ? ESP_ERR_NVS_NOT_FOUND : ESP_OK;
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
    (void)h;
    int i = nvs_stub_slot(k);
    if (i < 0) {
        return ESP_ERR_NVS_NOT_FOUND;
    }
    *v = nvs_stub_u16[i].v;
    return ESP_OK;
}
static inline esp_err_t nvs_set_u8(nvs_handle_t h, const char *k, uint8_t v)
{
    (void)h, (void)k, (void)v;
    return ESP_OK;
}
static inline esp_err_t nvs_set_u16(nvs_handle_t h, const char *k, uint16_t v)
{
    (void)h;
    int i = nvs_stub_slot(k);
    i = i < 0 ? nvs_stub_slot(NULL) : i;
    if (i < 0) {
        return ESP_FAIL;
    }
    nvs_stub_u16[i].k = k;
    nvs_stub_u16[i].v = v;
    return ESP_OK;
}
static inline esp_err_t nvs_commit(nvs_handle_t h)
{
    (void)h;
    return ESP_OK;
}
