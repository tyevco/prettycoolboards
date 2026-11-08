/* store: LittleFS ring log + profiles, NVS settings/state. */
#include "store.h"

#include <stdio.h>
#include <string.h>
#include <unistd.h>

#include "csv.h"
#include "esp_littlefs.h"
#include "esp_log.h"
#include "freertos/FreeRTOS.h"
#include "freertos/semphr.h"
#include "gatt_codec.h"
#include "le_bytes.h"
#include "nvs.h"
#include "sdkconfig.h"

static const char *TAG = "store";

#define LOG_PATH      STORE_BASE_PATH "/log.bin"
#define PROFILES_PATH STORE_BASE_PATH "/profiles.bin"
#define LOG_MAGIC     0x31474C43u /* "CLG1" */
#define LOG_HDR_SIZE  16
#define NVS_NS        "caliper"

static SemaphoreHandle_t s_lock;
static FILE *s_log;
static ring_t s_ring;

#define LOCK()   xSemaphoreTake(s_lock, portMAX_DELAY)
#define UNLOCK() xSemaphoreGive(s_lock)

/* ---- log file ---------------------------------------------------------------------------- */

static esp_err_t write_header(void)
{
    uint8_t h[LOG_HDR_SIZE] = {0};
    le_put_u32(h + 0, LOG_MAGIC);
    le_put_u16(h + 4, 1);
    le_put_u16(h + 6, LOGREC_SIZE);
    le_put_u32(h + 8, s_ring.capacity);
    le_put_u32(h + 12, s_ring.base_seq);
    if (fseek(s_log, 0, SEEK_SET) != 0 || fwrite(h, 1, sizeof(h), s_log) != sizeof(h)) {
        return ESP_FAIL;
    }
    fflush(s_log);
    fsync(fileno(s_log));
    return ESP_OK;
}

static esp_err_t create_log(uint32_t capacity, uint32_t base_seq)
{
    if (s_log) {
        fclose(s_log);
    }
    s_log = fopen(LOG_PATH, "w+b");
    if (!s_log) {
        return ESP_FAIL;
    }
    ring_init(&s_ring, capacity, base_seq);
    if (write_header() != ESP_OK) {
        return ESP_FAIL;
    }
    static uint8_t zeros[1024];
    size_t total = (size_t)capacity * LOGREC_SIZE;
    for (size_t done = 0; done < total; done += sizeof(zeros)) {
        size_t n = total - done < sizeof(zeros) ? total - done : sizeof(zeros);
        if (fwrite(zeros, 1, n, s_log) != n) {
            return ESP_FAIL;
        }
    }
    fflush(s_log);
    fsync(fileno(s_log));
    ESP_LOGI(TAG, "created log, %lu slots", (unsigned long)capacity);
    return ESP_OK;
}

static esp_err_t open_log(void)
{
    const uint32_t capacity = CONFIG_CALIPER_LOG_CAPACITY;
    s_log = fopen(LOG_PATH, "r+b");
    if (!s_log) {
        return create_log(capacity, 1);
    }
    uint8_t h[LOG_HDR_SIZE];
    if (fread(h, 1, sizeof(h), s_log) != sizeof(h) || le_get_u32(h) != LOG_MAGIC ||
        le_get_u16(h + 6) != LOGREC_SIZE || le_get_u32(h + 8) == 0) {
        ESP_LOGW(TAG, "log header invalid, recreating");
        return create_log(capacity, 1);
    }
    uint32_t file_cap = le_get_u32(h + 8);
    uint32_t base = le_get_u32(h + 12);
    /* scan for the newest record (with the capacity the file was written with) */
    uint32_t max_seq = 0;
    uint8_t buf[LOGREC_SIZE * 64];
    uint32_t slot = 0;
    while (slot < file_cap) {
        size_t want = (file_cap - slot) < 64 ? (file_cap - slot) : 64;
        size_t got = fread(buf, LOGREC_SIZE, want, s_log);
        if (got == 0) {
            break;
        }
        for (size_t i = 0; i < got; i++, slot++) {
            uint32_t seq = le_get_u32(buf + i * LOGREC_SIZE);
            if (seq != 0 && seq != LOGREC_END_SEQ && seq >= base && (seq - 1u) % file_cap == slot &&
                seq > max_seq) {
                max_seq = seq;
            }
        }
    }
    if (file_cap != capacity) {
        /* capacity changed (Kconfig): start a fresh file, numbering continues */
        ESP_LOGW(TAG, "log capacity %lu -> %lu, recreating", (unsigned long)file_cap, (unsigned long)capacity);
        return create_log(capacity, (max_seq >= base ? max_seq : base - 1u) + 1u);
    }
    ring_restore(&s_ring, capacity, base, max_seq);
    ESP_LOGI(TAG, "log: %lu records, next seq %lu", (unsigned long)ring_count(&s_ring),
             (unsigned long)s_ring.next_seq);
    return ESP_OK;
}

static bool read_slot(uint32_t seq, logrec_t *out)
{
    uint8_t b[LOGREC_SIZE];
    long off = LOG_HDR_SIZE + (long)ring_slot(&s_ring, seq) * LOGREC_SIZE;
    if (fseek(s_log, off, SEEK_SET) != 0 || fread(b, 1, sizeof(b), s_log) != sizeof(b)) {
        return false;
    }
    logrec_unpack(b, out);
    return out->seq == seq;
}

esp_err_t store_init(void)
{
    s_lock = xSemaphoreCreateMutex();
    esp_vfs_littlefs_conf_t conf = {
        .base_path = STORE_BASE_PATH,
        .partition_label = "storage",
        .format_if_mount_failed = true,
        .dont_mount = false,
    };
    esp_err_t err = esp_vfs_littlefs_register(&conf);
    if (err != ESP_OK) {
        ESP_LOGE(TAG, "LittleFS mount failed: %s", esp_err_to_name(err));
        return err;
    }
    size_t total = 0, used = 0;
    esp_littlefs_info("storage", &total, &used);
    ESP_LOGI(TAG, "LittleFS %u / %u bytes used", (unsigned)used, (unsigned)total);
    LOCK();
    err = open_log();
    UNLOCK();
    return err;
}

esp_err_t store_log_append(logrec_t *rec)
{
    if (!s_log) {
        return ESP_ERR_INVALID_STATE;
    }
    LOCK();
    rec->seq = ring_append(&s_ring);
    uint8_t b[LOGREC_SIZE];
    logrec_pack(rec, b);
    long off = LOG_HDR_SIZE + (long)ring_slot(&s_ring, rec->seq) * LOGREC_SIZE;
    esp_err_t err = ESP_OK;
    if (fseek(s_log, off, SEEK_SET) != 0 || fwrite(b, 1, sizeof(b), s_log) != sizeof(b)) {
        err = ESP_FAIL;
    } else {
        fflush(s_log);
        fsync(fileno(s_log));
    }
    UNLOCK();
    return err;
}

bool store_log_get(uint32_t seq, logrec_t *out)
{
    if (!s_log) {
        return false;
    }
    LOCK();
    bool ok = ring_contains(&s_ring, seq) && read_slot(seq, out);
    UNLOCK();
    return ok;
}

size_t store_log_read(uint32_t from_seq, logrec_t *out, size_t max, uint32_t *next)
{
    size_t n = 0;
    if (!s_log) {
        if (next) {
            *next = from_seq;
        }
        return 0;
    }
    LOCK();
    uint32_t seq = ring_first_from(&s_ring, from_seq);
    while (n < max && seq < s_ring.next_seq) {
        if (read_slot(seq, &out[n])) {
            n++;
        }
        seq++;
    }
    if (next) {
        *next = seq;
    }
    UNLOCK();
    return n;
}

uint32_t store_log_count(void)
{
    LOCK();
    uint32_t c = ring_count(&s_ring);
    UNLOCK();
    return c;
}

uint32_t store_log_next_seq(void)
{
    LOCK();
    uint32_t s = s_ring.next_seq;
    UNLOCK();
    return s;
}

esp_err_t store_log_clear(void)
{
    if (!s_log) {
        return ESP_ERR_INVALID_STATE;
    }
    LOCK();
    ring_clear(&s_ring);
    esp_err_t err = write_header();
    UNLOCK();
    return err;
}

esp_err_t store_log_export_csv(bool with_utc, uint8_t mm_decimals, store_write_fn fn, void *ctx)
{
    char out[1024];
    int len = csv_header(with_utc, out, sizeof(out));
    if (len < 0) {
        return ESP_FAIL;
    }
    esp_err_t err = fn(ctx, out, (size_t)len);
    uint32_t seq = 0;
    logrec_t recs[16];
    while (err == ESP_OK) {
        uint32_t next;
        size_t n = store_log_read(seq, recs, 16, &next); /* the lock is released between batches */
        if (n == 0) {
            break;
        }
        size_t used = 0;
        for (size_t i = 0; i < n; i++) {
            int l = csv_line(&recs[i], mm_decimals, with_utc, out + used, sizeof(out) - used);
            if (l < 0) {
                break;
            }
            used += (size_t)l;
        }
        err = fn(ctx, out, used);
        seq = next;
    }
    return err;
}

/* ---- profiles ---------------------------------------------------------------------------- */

size_t store_profiles_load(meas_profile_t *out, size_t max)
{
    LOCK();
    FILE *f = fopen(PROFILES_PATH, "rb");
    size_t n = 0;
    if (f) {
        uint8_t b[CALIPER_PROFILE_LEN];
        while (n < max && fread(b, 1, sizeof(b), f) == sizeof(b)) {
            gatt_profile_unpack(b, &out[n]);
            if (out[n].id != 0) {
                n++;
            }
        }
        fclose(f);
    }
    UNLOCK();
    return n;
}

esp_err_t store_profiles_save(const meas_profile_t *p, size_t n)
{
    LOCK();
    FILE *f = fopen(PROFILES_PATH ".tmp", "wb");
    esp_err_t err = f ? ESP_OK : ESP_FAIL;
    for (size_t i = 0; f && i < n && err == ESP_OK; i++) {
        uint8_t b[CALIPER_PROFILE_LEN];
        gatt_profile_pack(&p[i], b);
        if (fwrite(b, 1, sizeof(b), f) != sizeof(b)) {
            err = ESP_FAIL;
        }
    }
    if (f) {
        fclose(f);
    }
    if (err == ESP_OK) {
        unlink(PROFILES_PATH);
        if (rename(PROFILES_PATH ".tmp", PROFILES_PATH) != 0) {
            err = ESP_FAIL;
        }
    }
    UNLOCK();
    return err;
}

/* ---- NVS ----------------------------------------------------------------------------------- */

esp_err_t store_settings_load(settings_t *s)
{
    settings_defaults(s);
    nvs_handle_t h;
    if (nvs_open(NVS_NS, NVS_READONLY, &h) != ESP_OK) {
        return ESP_OK; /* nothing stored yet */
    }
    char json[SETTINGS_JSON_MAX + 1];
    size_t len = sizeof(json);
    if (nvs_get_str(h, "settings", json, &len) == ESP_OK) {
        if (settings_from_json(s, json, strlen(json)) != SETTINGS_OK) {
            ESP_LOGW(TAG, "stored settings invalid, using defaults");
            settings_defaults(s);
        }
    }
    len = sizeof(s->wifi_pass);
    if (nvs_get_str(h, "wifi_pass", s->wifi_pass, &len) != ESP_OK) {
        s->wifi_pass[0] = '\0';
    }
    nvs_close(h);
    return ESP_OK;
}

esp_err_t store_settings_save(const settings_t *s)
{
    char json[SETTINGS_JSON_MAX + 1];
    if (settings_to_json(s, json, sizeof(json)) < 0) {
        return ESP_ERR_INVALID_SIZE;
    }
    nvs_handle_t h;
    esp_err_t err = nvs_open(NVS_NS, NVS_READWRITE, &h);
    if (err != ESP_OK) {
        return err;
    }
    err = nvs_set_str(h, "settings", json);
    if (err == ESP_OK) {
        err = nvs_set_str(h, "wifi_pass", s->wifi_pass);
    }
    if (err == ESP_OK) {
        err = nvs_commit(h);
    }
    nvs_close(h);
    return err;
}

esp_err_t store_state_load(store_state_t *st)
{
    st->unit = 0;
    st->profile_id = 0;
    st->autohold = true;
    nvs_handle_t h;
    if (nvs_open(NVS_NS, NVS_READONLY, &h) != ESP_OK) {
        return ESP_OK;
    }
    uint8_t u8;
    uint16_t u16;
    if (nvs_get_u8(h, "unit", &u8) == ESP_OK && u8 <= 1) {
        st->unit = u8;
    }
    if (nvs_get_u16(h, "profile", &u16) == ESP_OK) {
        st->profile_id = u16;
    }
    if (nvs_get_u8(h, "autohold", &u8) == ESP_OK) {
        st->autohold = u8 != 0;
    }
    nvs_close(h);
    return ESP_OK;
}

esp_err_t store_state_save(const store_state_t *st)
{
    nvs_handle_t h;
    esp_err_t err = nvs_open(NVS_NS, NVS_READWRITE, &h);
    if (err != ESP_OK) {
        return err;
    }
    nvs_set_u8(h, "unit", st->unit);
    nvs_set_u16(h, "profile", st->profile_id);
    nvs_set_u8(h, "autohold", st->autohold ? 1 : 0);
    err = nvs_commit(h);
    nvs_close(h);
    return err;
}
