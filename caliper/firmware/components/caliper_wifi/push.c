/*
 * Push each recorded reading to MQTT and/or an HTTP endpoint (station mode only).
 *
 * 2026-11-07 review:
 *  - s_mqtt was destroyed by push_stop() (bus or event-loop task) while push_task could be inside
 *    esp_mqtt_client_publish() on it: a use-after-free. It is now guarded by s_mlock, and the
 *    reading is queued with esp_mqtt_client_enqueue() (non-blocking; the MQTT task sends it) so
 *    the lock is never held across network I/O.
 *  - https:// and mqtts:// / wss:// had no server verification configured, which esp-tls refuses:
 *    every TLS push failed. Both clients now verify against the ESP-IDF certificate bundle.
 *  - The URL is no longer logged: it may carry user:password@.
 */
#include <stdio.h>
#include <string.h>

#include "caliper_core.h"
#include "caliper_wifi.h"
#include "esp_crt_bundle.h"
#include "esp_http_client.h"
#include "esp_log.h"
#include "freertos/FreeRTOS.h"
#include "freertos/queue.h"
#include "freertos/semphr.h"
#include "freertos/task.h"
#include "measure.h"
#include "mqtt_client.h"

static const char *TAG = "push";

static QueueHandle_t s_q;
static esp_mqtt_client_handle_t s_mqtt; /* guarded by s_mlock */
static SemaphoreHandle_t s_mlock;
static volatile bool s_up;

static int reading_json(const logrec_t *r, const settings_t *s, char *b, size_t n)
{
    meas_fmt_t f = meas_fmt_for(r->unit ? MEAS_UNIT_INCH : MEAS_UNIT_MM, s->decimals);
    char v[16];
    meas_format(r->value_nm, &f, v, sizeof(v));
    return snprintf(b, n,
                    "{\"seq\":%lu,\"unix_s\":%lu,\"value_nm\":%ld,\"value\":\"%s\",\"unit\":\"%s\",\"flags\":%u,"
                    "\"profile_id\":%u}",
                    (unsigned long)r->seq, (unsigned long)r->unix_s, (long)r->value_nm, v, meas_unit_str(f.unit),
                    r->flags, r->profile_id);
}

static void topic_for(const settings_t *s, char *t, size_t n)
{
    /* caliper/<name>/reading, with spaces and MQTT wildcards replaced */
    char name[SETTINGS_NAME_MAX + 1];
    size_t k = 0;
    for (size_t i = 0; s->name[i] && k < SETTINGS_NAME_MAX; i++) {
        char c = s->name[i];
        name[k++] = (c == ' ' || c == '+' || c == '#' || c == '/') ? '_' : c;
    }
    name[k] = '\0';
    snprintf(t, n, "caliper/%s/reading", name);
}

static void http_post(const char *url, const char *body)
{
    esp_http_client_config_t cfg = {
        .url = url,
        .method = HTTP_METHOD_POST,
        .timeout_ms = 4000,
        .crt_bundle_attach = esp_crt_bundle_attach, /* used for https:// only */
    };
    esp_http_client_handle_t c = esp_http_client_init(&cfg);
    if (!c) {
        return;
    }
    esp_http_client_set_header(c, "Content-Type", "application/json");
    esp_http_client_set_post_field(c, body, (int)strlen(body));
    esp_err_t err = esp_http_client_perform(c);
    if (err != ESP_OK) {
        ESP_LOGW(TAG, "POST failed: %s", esp_err_to_name(err)); /* not the URL: it may hold credentials */
    } else {
        ESP_LOGI(TAG, "POST -> %d", esp_http_client_get_status_code(c));
    }
    esp_http_client_cleanup(c);
}

static void push_task(void *arg)
{
    (void)arg;
    logrec_t r;
    for (;;) {
        if (xQueueReceive(s_q, &r, portMAX_DELAY) != pdTRUE || !s_up) {
            continue;
        }
        settings_t s;
        core_get_settings(&s);
        char body[200];
        reading_json(&r, &s, body, sizeof(body));
        char topic[48];
        topic_for(&s, topic, sizeof(topic));
        xSemaphoreTake(s_mlock, portMAX_DELAY);
        if (s_mqtt) {
            /* queued in the client's outbox (QoS 1, kept until acknowledged); never blocks here */
            if (esp_mqtt_client_enqueue(s_mqtt, topic, body, 0, 1, 0, true) < 0) {
                ESP_LOGW(TAG, "MQTT enqueue failed");
            }
        }
        xSemaphoreGive(s_mlock);
        if (s.http_post_url[0]) {
            http_post(s.http_post_url, body);
        }
    }
}

static void on_recorded(void *arg, esp_event_base_t base, int32_t id, void *data)
{
    (void)arg;
    (void)base;
    (void)id;
    if (s_up) {
        xQueueSend(s_q, data, 0);
    }
}

void push_start(void)
{
    settings_t s;
    core_get_settings(&s);
    xSemaphoreTake(s_mlock, portMAX_DELAY);
    if (s.mqtt_url[0] && !s_mqtt) {
        esp_mqtt_client_config_t cfg = {
            .broker.address.uri = s.mqtt_url,
            .broker.verification.crt_bundle_attach = esp_crt_bundle_attach, /* mqtts:// and wss:// */
        };
        s_mqtt = esp_mqtt_client_init(&cfg);
        if (s_mqtt && esp_mqtt_client_start(s_mqtt) != ESP_OK) {
            esp_mqtt_client_destroy(s_mqtt);
            s_mqtt = NULL;
        }
    }
    xSemaphoreGive(s_mlock);
    s_up = true;
}

void push_stop(void)
{
    s_up = false;
    xSemaphoreTake(s_mlock, portMAX_DELAY);
    esp_mqtt_client_handle_t c = s_mqtt;
    s_mqtt = NULL;
    xSemaphoreGive(s_mlock);
    if (c) {
        esp_mqtt_client_stop(c);
        esp_mqtt_client_destroy(c);
    }
}

void push_init(void)
{
    s_mlock = xSemaphoreCreateMutex();
    s_q = xQueueCreate(16, sizeof(logrec_t));
    xTaskCreatePinnedToCore(push_task, "push", 6144, NULL, 3, NULL, 0);
    bus_subscribe(CAL_EVT_RECORDED, on_recorded, NULL);
}
