/*
 * store: LittleFS ring log + profiles, NVS settings/state.
 *
 * Log layout (v2, 2026-11-07 review). The log used to be one LittleFS file of capacity x 16 bytes,
 * overwritten in place. LittleFS stores a file as a backward-linked CTZ skip-list, so a write in the
 * middle of a file rewrites every block from the written one to the end of the file
 * (lfs_file_flush: "copy over anything after current branch"). One 16-byte reading therefore cost
 * on average half the file: 32 KiB (8 sector erases) in the 4 MB build, 128 KiB (32 erases) in the
 * 8 MB one, each erase stalling both cores (and the 100 Hz sensor task) for tens of ms, for up to
 * ~1 s per reading, plus that much wear. Now:
 *   /fs/log.hdr       16 bytes: magic "CLG2", version, record size, capacity, base_seq
 *   /fs/logNNN.bin    segment NNN = slots NNN*256 .. NNN*256+255, 4 KiB = one LittleFS block
 * A record write rewrites at most the rest of one 4 KiB segment. Every write is followed by fsync(),
 * which LittleFS commits atomically: after a power loss a slot holds either its old or its new
 * record, never a torn one; the boot scan only accepts a slot whose seq maps to it.
 * The header changes only on clear / capacity change, by an in-place overwrite (also atomic).
 */
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

#define LOG_HDR_PATH  STORE_BASE_PATH "/log.hdr"
#define LOG_V1_PATH   STORE_BASE_PATH "/log.bin" /* v1 single-file layout (pre-release builds only) */
#define PROFILES_PATH STORE_BASE_PATH "/profiles.bin"
#define LOG_MAGIC     0x32474C43u /* "CLG2" */
#define LOG_VERSION   2
#define LOG_HDR_SIZE  16
#define SEG_RECS      256u /* records per segment file: 4 KiB, one LittleFS block */
#define SEG_MAX       ((65536u + SEG_RECS - 1u) / SEG_RECS) /* CONFIG_CALIPER_LOG_CAPACITY range max */
#define NVS_NS        "caliper"

static SemaphoreHandle_t s_lock;
static bool s_log_ok;
static ring_t s_ring;
static uint32_t s_cfg_capacity = CONFIG_CALIPER_LOG_CAPACITY;
/* one open segment at a time */
static FILE *s_seg;
static uint32_t s_seg_idx = UINT32_MAX;

#define LOCK()   xSemaphoreTake(s_lock, portMAX_DELAY)
#define UNLOCK() xSemaphoreGive(s_lock)

/* ---- log files ----------------------------------------------------------------------------- */

static void seg_path(uint32_t idx, char *buf, size_t n)
{
    snprintf(buf, n, STORE_BASE_PATH "/log%03u.bin", (unsigned)(idx % 1000u)); /* idx < SEG_MAX = 256 */
}

static void seg_close(void)
{
    if (s_seg) {
        fclose(s_seg);
    }
    s_seg = NULL;
    s_seg_idx = UINT32_MAX;
}

static FILE *seg_get(uint32_t idx, bool create)
{
    if (s_seg && s_seg_idx == idx) {
        return s_seg;
    }
    seg_close();
    char path[sizeof(STORE_BASE_PATH) + 24];
    seg_path(idx, path, sizeof(path));
    FILE *f = fopen(path, "r+b");
    if (!f && create) {
        f = fopen(path, "w+b");
    }
    if (f) {
        s_seg = f;
        s_seg_idx = idx;
    }
    return f;
}

static esp_err_t write_header(void)
{
    uint8_t h[LOG_HDR_SIZE] = {0};
    le_put_u32(h + 0, LOG_MAGIC);
    le_put_u16(h + 4, LOG_VERSION);
    le_put_u16(h + 6, LOGREC_SIZE);
    le_put_u32(h + 8, s_ring.capacity);
    le_put_u32(h + 12, s_ring.base_seq);
    /* overwrite in place when it exists (one atomic commit at fsync); "w" would truncate first */
    FILE *f = fopen(LOG_HDR_PATH, "r+b");
    if (!f) {
        f = fopen(LOG_HDR_PATH, "w+b");
    }
    if (!f) {
        return ESP_FAIL;
    }
    bool ok = fseek(f, 0, SEEK_SET) == 0 && fwrite(h, 1, sizeof(h), f) == sizeof(h) && fflush(f) == 0 &&
              fsync(fileno(f)) == 0;
    ok = fclose(f) == 0 && ok;
    return ok ? ESP_OK : ESP_FAIL;
}

static bool read_header(uint32_t *capacity, uint32_t *base)
{
    uint8_t h[LOG_HDR_SIZE];
    FILE *f = fopen(LOG_HDR_PATH, "rb");
    if (!f) {
        return false;
    }
    bool ok = fread(h, 1, sizeof(h), f) == sizeof(h);
    fclose(f);
    if (!ok || le_get_u32(h) != LOG_MAGIC || le_get_u16(h + 4) != LOG_VERSION || le_get_u16(h + 6) != LOGREC_SIZE ||
        le_get_u32(h + 8) == 0 || le_get_u32(h + 8) > SEG_MAX * SEG_RECS || le_get_u32(h + 12) == 0) {
        return false;
    }
    *capacity = le_get_u32(h + 8);
    *base = le_get_u32(h + 12);
    return true;
}

static esp_err_t create_log(uint32_t capacity, uint32_t base_seq)
{
    seg_close();
    /* segments first, header last: a power loss in between leaves the old header with fewer (or no)
     * segments, which the scan reads as fewer records */
    for (uint32_t i = 0; i < SEG_MAX; i++) {
        char path[sizeof(STORE_BASE_PATH) + 24];
        seg_path(i, path, sizeof(path));
        unlink(path);
    }
    ring_init(&s_ring, capacity, base_seq);
    esp_err_t err = write_header();
    ESP_LOGI(TAG, "created log, %lu slots, next seq %lu", (unsigned long)capacity, (unsigned long)s_ring.next_seq);
    return err;
}

/* Largest valid seq in the segments of a log written with `capacity` slots (0 if none). */
static uint32_t scan_max_seq(uint32_t capacity, uint32_t base)
{
    uint32_t max_seq = 0;
    uint8_t buf[LOGREC_SIZE * 64];
    for (uint32_t idx = 0; idx * SEG_RECS < capacity; idx++) {
        FILE *f = seg_get(idx, false);
        if (!f || fseek(f, 0, SEEK_SET) != 0) {
            continue;
        }
        uint32_t slot = idx * SEG_RECS;
        uint32_t end = slot + SEG_RECS < capacity ? slot + SEG_RECS : capacity;
        while (slot < end) {
            size_t want = end - slot < 64 ? end - slot : 64;
            size_t got = fread(buf, LOGREC_SIZE, want, f);
            if (got == 0) {
                break;
            }
            for (size_t i = 0; i < got; i++, slot++) {
                uint32_t seq = le_get_u32(buf + i * LOGREC_SIZE);
                if (seq != 0 && seq != LOGREC_END_SEQ && seq >= base && (seq - 1u) % capacity == slot &&
                    seq > max_seq) {
                    max_seq = seq;
                }
            }
        }
    }
    return max_seq;
}

static esp_err_t open_log(void)
{
    const uint32_t capacity = s_cfg_capacity;
    seg_close();
    if (unlink(LOG_V1_PATH) == 0) {
        ESP_LOGW(TAG, "removed the v1 single-file log (pre-release layout)");
    }
    uint32_t file_cap = 0, base = 0;
    if (!read_header(&file_cap, &base)) {
        ESP_LOGW(TAG, "no valid log header: new log");
        return create_log(capacity, 1);
    }
    uint32_t max_seq = scan_max_seq(file_cap, base);
    if (file_cap != capacity) {
        /* capacity changed (Kconfig): start a fresh log, numbering continues */
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
    uint32_t slot = ring_slot(&s_ring, seq);
    FILE *f = seg_get(slot / SEG_RECS, false);
    uint8_t b[LOGREC_SIZE];
    if (!f || fseek(f, (long)((slot % SEG_RECS) * LOGREC_SIZE), SEEK_SET) != 0 || fread(b, 1, sizeof(b), f) != sizeof(b)) {
        return false;
    }
    logrec_unpack(b, out);
    return out->seq == seq;
}

esp_err_t store_init(void)
{
    if (!s_lock) {
        s_lock = xSemaphoreCreateMutex();
    }
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
    s_log_ok = err == ESP_OK;
    UNLOCK();
    return err;
}

#ifdef STORE_HOST_TEST
/* Host tests: forget everything in RAM and open the log again, as a reboot would. */
esp_err_t store_test_reboot(uint32_t capacity)
{
    LOCK();
    seg_close();
    memset(&s_ring, 0, sizeof(s_ring));
    s_cfg_capacity = capacity;
    esp_err_t err = open_log();
    s_log_ok = err == ESP_OK;
    UNLOCK();
    return err;
}
#endif

esp_err_t store_log_append(logrec_t *rec)
{
    if (!s_log_ok) {
        return ESP_ERR_INVALID_STATE;
    }
    LOCK();
    rec->seq = ring_append(&s_ring);
    uint8_t b[LOGREC_SIZE];
    logrec_pack(rec, b);
    uint32_t slot = ring_slot(&s_ring, rec->seq);
    FILE *f = seg_get(slot / SEG_RECS, true);
    esp_err_t err = ESP_OK;
    if (!f || fseek(f, (long)((slot % SEG_RECS) * LOGREC_SIZE), SEEK_SET) != 0 || fwrite(b, 1, sizeof(b), f) != sizeof(b) ||
        fflush(f) != 0 || fsync(fileno(f)) != 0) {
        err = ESP_FAIL;
        s_ring.next_seq = rec->seq; /* not stored: the number is not used up */
        seg_close();               /* the stream may be in an error state */
    }
    UNLOCK();
    return err;
}

bool store_log_get(uint32_t seq, logrec_t *out)
{
    if (!s_log_ok) {
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
    if (!s_log_ok) {
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
    if (!s_lock) {
        return 0;
    }
    LOCK();
    uint32_t c = s_log_ok ? ring_count(&s_ring) : 0;
    UNLOCK();
    return c;
}

uint32_t store_log_next_seq(void)
{
    if (!s_lock) {
        return 0;
    }
    LOCK();
    uint32_t s = s_ring.next_seq;
    UNLOCK();
    return s;
}

esp_err_t store_log_clear(void)
{
    if (!s_log_ok) {
        return ESP_ERR_INVALID_STATE;
    }
    LOCK();
    ring_t before = s_ring;
    ring_clear(&s_ring);
    esp_err_t err = write_header();
    if (err != ESP_OK) {
        s_ring = before; /* still on flash: keep showing it */
    }
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
        /* whole lines only; a batch that does not fit goes out in several writes (the old loop
         * silently dropped the records after the first line that did not fit) */
        for (size_t done = 0; done < n && err == ESP_OK;) {
            size_t used = 0;
            size_t k = csv_pack(recs + done, n - done, mm_decimals, with_utc, out, sizeof(out), &used);
            if (k == 0) {
                err = ESP_FAIL;
                break;
            }
            err = fn(ctx, out, used);
            done += k;
        }
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
        if (err == ESP_OK && (fflush(f) != 0 || fsync(fileno(f)) != 0)) {
            err = ESP_FAIL;
        }
        if (fclose(f) != 0) {
            err = ESP_FAIL;
        }
    }
    if (err == ESP_OK) {
        /* LittleFS rename() replaces an existing target atomically; no unlink first, so a power
         * loss leaves either the old or the new table, never none */
        if (rename(PROFILES_PATH ".tmp", PROFILES_PATH) != 0) {
            unlink(PROFILES_PATH); /* a VFS that refuses to replace: fall back */
            if (rename(PROFILES_PATH ".tmp", PROFILES_PATH) != 0) {
                err = ESP_FAIL;
            }
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
    st->capture = CALIPER_CAPTURE_SETTLE; /* the old default (auto-hold on) */
    st->sweep_sel = CALIPER_SWEEP_AUTO;
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
    if (nvs_get_u8(h, "capture", &u8) == ESP_OK && u8 <= CALIPER_CAPTURE_SWEEP) {
        st->capture = u8;
    } else if (nvs_get_u8(h, "autohold", &u8) == ESP_OK) {
        /* firmware before the capture modes: auto-hold on = SETTLE, off = LIVE */
        st->capture = u8 ? CALIPER_CAPTURE_SETTLE : CALIPER_CAPTURE_LIVE;
    }
    if (nvs_get_u8(h, "sweep_sel", &u8) == ESP_OK && u8 <= CALIPER_SWEEP_MAX) {
        st->sweep_sel = u8;
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
    nvs_set_u8(h, "capture", st->capture);
    nvs_set_u8(h, "sweep_sel", st->sweep_sel);
    /* kept for one release, so a downgrade still finds its auto-hold setting */
    nvs_set_u8(h, "autohold", st->capture == CALIPER_CAPTURE_SETTLE ? 1 : 0);

    err = nvs_commit(h);
    nvs_close(h);
    return err;
}
