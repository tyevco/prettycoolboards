/*
 * BLE worker task: the slow jobs that must not run in the NimBLE host task or on the bus:
 *   - LOG_READ streaming (packed 16-byte records, then one record with seq 0xFFFFFFFF)
 *   - HID typing of the SEND text (press/release report pairs)
 */
#include <string.h>

#include "ble.h"
#include "caliper_core.h"
#include "caliper_gatt.h"
#include "esp_log.h"
#include "freertos/FreeRTOS.h"
#include "freertos/queue.h"
#include "freertos/task.h"
#include "gatt_codec.h"
#include "hid_keymap.h"
#include "host/ble_hs.h"
#include "store.h"

static const char *TAG = "ble_wrk";

#define HID_KEY_DELAY_MS 12 /* about one connection event per report (TVP per host) */
#define MAX_PER_NOTIFY   15 /* (247 - 3) / 16 */

typedef enum { JOB_LOG_READ, JOB_TYPE } job_type_t;

typedef struct {
    job_type_t type;
    uint16_t conn;
    uint32_t from;
    bool ext; /* LOG_READ with CALIPER_LOG_OPT_KIND: byte 12 whole */
    char text[28];
} job_t;

static QueueHandle_t s_q;

void ble_worker_log_read(uint16_t conn, uint32_t from_seq, bool ext)
{
    job_t j = {.type = JOB_LOG_READ, .conn = conn, .from = from_seq, .ext = ext};
    if (!s_q || xQueueSend(s_q, &j, 0) != pdTRUE) {
        ESP_LOGW(TAG, "log read dropped");
    }
}

static void stream_log(uint16_t conn, uint32_t from, bool ext)
{
    ble_conn_t c;
    if (!ble_conn_get(conn, &c) || !c.log_sub) {
        ESP_LOGW(TAG, "LOG_READ without a LOG subscription; ignored");
        return;
    }
    size_t per = gatt_log_records_per_notify(c.mtu);
    if (per > MAX_PER_NOTIFY) {
        per = MAX_PER_NOTIFY;
    }
    logrec_t recs[MAX_PER_NOTIFY];
    uint8_t buf[MAX_PER_NOTIFY * CALIPER_LOGREC_LEN];
    uint32_t seq = from;
    size_t total = 0;
    for (;;) {
        if (!ble_conn_get(conn, &c)) {
            return; /* disconnected mid-stream */
        }
        uint32_t next;
        size_t n = store_log_read(seq, recs, per, &next);
        if (n == 0) {
            break;
        }
        for (size_t i = 0; i < n; i++) {
            gatt_log_record_pack(&recs[i], ext, buf + i * CALIPER_LOGREC_LEN);
        }
        if (ble_notify(conn, g_h_log, buf, (uint16_t)(n * CALIPER_LOGREC_LEN)) != 0) {
            ESP_LOGW(TAG, "log stream aborted after %u records", (unsigned)total);
            return;
        }
        total += n;
        seq = next;
        core_activity();
    }
    logrec_t end = logrec_end_marker();
    logrec_pack(&end, buf);
    ble_notify(conn, g_h_log, buf, CALIPER_LOGREC_LEN);
    ESP_LOGI(TAG, "streamed %u records from seq %lu%s", (unsigned)total, (unsigned long)from, ext ? " (ext)" : "");
}

static void type_text(const char *text)
{
    uint8_t reports[2 * 28][8];
    size_t n = hid_build_reports(text, reports, sizeof(reports) / sizeof(reports[0]));
    bool sent = false;
    ble_conn_t conns[BLE_MAX_CONN];
    int nc = ble_conn_snapshot(conns); /* type outside the lock */
    for (int i = 0; i < nc; i++) {
        const ble_conn_t *c = &conns[i];
        if (!c->hid_sub || !c->encrypted) {
            continue;
        }
        for (size_t k = 0; k < n; k++) {
            ble_notify(c->handle, g_h_hid_input, reports[k], 8);
            vTaskDelay(pdMS_TO_TICKS(HID_KEY_DELAY_MS));
        }
        sent = true;
    }
    if (!sent) {
        char m[32] = "No BLE keyboard host";
        bus_post(CAL_EVT_TOAST, m, sizeof(m));
    }
}

static void on_send(void *arg, esp_event_base_t base, int32_t id, void *data)
{
    (void)arg;
    (void)base;
    (void)id;
    job_t j = {.type = JOB_TYPE};
    strlcpy(j.text, ((const cal_send_t *)data)->text, sizeof(j.text));
    xQueueSend(s_q, &j, 0);
}

static void worker(void *arg)
{
    (void)arg;
    job_t j;
    for (;;) {
        if (xQueueReceive(s_q, &j, portMAX_DELAY) != pdTRUE) {
            continue;
        }
        if (j.type == JOB_LOG_READ) {
            stream_log(j.conn, j.from, j.ext);

        } else {
            type_text(j.text);
        }
    }
}

void ble_worker_start(void)
{
    s_q = xQueueCreate(8, sizeof(job_t));
    xTaskCreatePinnedToCore(worker, "ble_wrk", 4096, NULL, 5, NULL, 0);
    bus_subscribe(CAL_EVT_SEND, on_send, NULL);
}
