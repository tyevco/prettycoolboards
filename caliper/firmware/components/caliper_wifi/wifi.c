/*
 * Wi-Fi station / provisioning AP state machine.
 *
 * Threads (2026-11-07 review): the state machine is driven from two tasks, the caliper bus task
 * (on_cmd: on / off / AP from the UI, BLE, CLI, web, sleep) and the default event loop task
 * (on_wifi: connect, disconnect, got IP). Unlocked, a DISCONNECTED handled while the bus task was
 * switching the radio off could restart it (start_ap() after "off"), and both tasks could run
 * web_start()/web_stop() on the same server handle at once. Every entry point now takes s_wlock.
 * esp_wifi_stop()/start() only post events, so holding the lock across them cannot deadlock with
 * on_wifi; on_wifi re-checks the state after taking it.
 *
 * Credentials: never logged. The station password lives in our NVS (store.c) and in RAM only for
 * the wifi_config_t handed to the driver (WIFI_STORAGE_RAM: the driver does not persist it), which
 * is wiped after use.
 */
#include <stdio.h>
#include <string.h>

#include "caliper_core.h"
#include "caliper_wifi.h"
#include "esp_check.h"
#include "esp_event.h"
#include "esp_log.h"
#include "esp_mac.h"
#include "esp_netif.h"
#include "esp_random.h"
#include "esp_wifi.h"
#include "freertos/FreeRTOS.h"
#include "freertos/semphr.h"

static const char *TAG = "wifi";

#define STA_RETRIES 5
/* Provisioning AP password: 10 characters from a 31-symbol alphabet without look-alikes (no 0/o,
 * 1/l/i), about 49.5 bits. It was 8 decimal digits (26.6 bits): a captured WPA2 handshake falls to an
 * offline search of 10^8 in minutes, and with the PSK an eavesdropper can decrypt the session in
 * which the home network's password is typed into the setup form. */
#define AP_PASS_LEN 10
static const char AP_PASS_ALPHABET[] = "abcdefghjkmnpqrstuvwxyz23456789";

typedef enum { W_OFF = 0, W_CONNECTING = 1, W_STA = 2, W_AP = 3 } wstate_t;

static bool s_inited;
static wstate_t s_state;
static int s_retries;
static esp_netif_t *s_sta, *s_ap;
static char s_ap_ssid[24], s_ap_pass[AP_PASS_LEN + 2];
static SemaphoreHandle_t s_wlock;

#define WLOCK()   xSemaphoreTakeRecursive(s_wlock, portMAX_DELAY)
#define WUNLOCK() xSemaphoreGiveRecursive(s_wlock)

bool caliper_wifi_active(void)
{
    return s_state != W_OFF; /* a single aligned word: a stale read only delays auto-off by a poll */
}

static void publish_state(const char *ip)
{
    core_set_wifi((uint8_t)s_state, ip, s_state == W_AP ? s_ap_ssid : "", s_state == W_AP ? s_ap_pass : "");
}

static esp_err_t ensure_init(void)
{
    if (s_inited) {
        return ESP_OK;
    }
    s_sta = esp_netif_create_default_wifi_sta();
    s_ap = esp_netif_create_default_wifi_ap();
    wifi_init_config_t cfg = WIFI_INIT_CONFIG_DEFAULT();
    ESP_RETURN_ON_ERROR(esp_wifi_init(&cfg), TAG, "init");
    ESP_RETURN_ON_ERROR(esp_wifi_set_storage(WIFI_STORAGE_RAM), TAG, "storage"); /* creds live in our NVS */
    s_inited = true;
    return ESP_OK;
}

static void stop_radio(void)
{
    push_stop();
    web_stop();
    if (s_inited) {
        esp_wifi_stop();
    }
    s_state = W_OFF;
    publish_state("");
}

static void start_ap(void)
{
    stop_radio();
    if (ensure_init() != ESP_OK) {
        return;
    }
    uint8_t mac[6];
    esp_read_mac(mac, ESP_MAC_WIFI_SOFTAP);
    snprintf(s_ap_ssid, sizeof(s_ap_ssid), "Caliper-%02X%02X", mac[4], mac[5]);
    /* esp_random() is a true RNG here: the BLE radio is already running (ble_init at boot) */
    for (int i = 0; i < AP_PASS_LEN; i++) {
        uint32_t r;
        do {
            r = esp_random() & 0x1Fu; /* 0..31, rejection keeps it uniform over the 31 symbols */
        } while (r >= sizeof(AP_PASS_ALPHABET) - 1);
        s_ap_pass[i] = AP_PASS_ALPHABET[r];
    }
    s_ap_pass[AP_PASS_LEN] = '\0';
    wifi_config_t ap = {0};
    strlcpy((char *)ap.ap.ssid, s_ap_ssid, sizeof(ap.ap.ssid));
    ap.ap.ssid_len = (uint8_t)strlen(s_ap_ssid);
    strlcpy((char *)ap.ap.password, s_ap_pass, sizeof(ap.ap.password));
    ap.ap.channel = 6;
    ap.ap.authmode = WIFI_AUTH_WPA2_PSK;
    ap.ap.max_connection = 2;
    esp_wifi_set_mode(WIFI_MODE_AP);
    esp_wifi_set_config(WIFI_IF_AP, &ap);
    memset(&ap, 0, sizeof(ap));
    if (esp_wifi_start() != ESP_OK) {
        ESP_LOGE(TAG, "AP start failed");
        return;
    }
    s_state = W_AP;
    publish_state("192.168.4.1");
    web_start();
    ESP_LOGI(TAG, "provisioning AP %s up", s_ap_ssid);
}

static void start_sta(void)
{
    settings_t s;
    core_get_settings(&s);
    if (s.wifi_ssid[0] == '\0') {
        start_ap();
        return;
    }
    stop_radio();
    if (ensure_init() != ESP_OK) {
        return;
    }
    wifi_config_t sta = {0};
    /* ssid[32] and password[64] are not NUL-terminated when full: a 32-byte SSID and a 64-hex-digit
     * PSK are both legal (settings allow them). strlcpy() cut them to 31 / 63 bytes, so such a
     * network could never be joined. Copy the bytes; the zeroed struct terminates shorter ones. */
    memcpy(sta.sta.ssid, s.wifi_ssid, strnlen(s.wifi_ssid, sizeof(sta.sta.ssid)));
    memcpy(sta.sta.password, s.wifi_pass, strnlen(s.wifi_pass, sizeof(sta.sta.password)));
    sta.sta.threshold.authmode = s.wifi_pass[0] ? WIFI_AUTH_WPA2_PSK : WIFI_AUTH_OPEN;
    sta.sta.pmf_cfg.capable = true;
    esp_wifi_set_mode(WIFI_MODE_STA);
    esp_wifi_set_config(WIFI_IF_STA, &sta);
    memset(&sta, 0, sizeof(sta));
    memset(&s, 0, sizeof(s));
    s_retries = 0;
    s_state = W_CONNECTING;
    publish_state("");
    if (esp_wifi_start() != ESP_OK) {
        ESP_LOGE(TAG, "STA start failed");
        s_state = W_OFF;
        publish_state("");
    }
}

void caliper_wifi_reconnect_sta(void)
{
    WLOCK();
    start_sta();
    WUNLOCK();
}

static void on_wifi_locked(esp_event_base_t base, int32_t id, void *data)
{
    if (base == WIFI_EVENT && id == WIFI_EVENT_STA_START && s_state == W_CONNECTING) {
        esp_wifi_connect();
    } else if (base == WIFI_EVENT && id == WIFI_EVENT_STA_DISCONNECTED) {
        if (s_state != W_CONNECTING && s_state != W_STA) {
            return;
        }
        push_stop();
        web_stop();
        if (++s_retries > STA_RETRIES) {
            ESP_LOGW(TAG, "station failed %d times: provisioning AP", STA_RETRIES);
            start_ap();
            return;
        }
        s_state = W_CONNECTING;
        publish_state("");
        esp_wifi_connect();
    } else if (base == IP_EVENT && id == IP_EVENT_STA_GOT_IP) {
        const ip_event_got_ip_t *e = (const ip_event_got_ip_t *)data;
        char ip[16];
        snprintf(ip, sizeof(ip), IPSTR, IP2STR(&e->ip_info.ip));
        s_state = W_STA;
        s_retries = 0;
        publish_state(ip);
        web_start();
        push_start();
        ESP_LOGI(TAG, "station up, http://%s/", ip);
    }
}

static void on_wifi(void *arg, esp_event_base_t base, int32_t id, void *data)
{
    (void)arg;
    WLOCK();
    on_wifi_locked(base, id, data);
    WUNLOCK();
}

static void on_cmd(void *arg, esp_event_base_t base, int32_t id, void *data)
{
    (void)arg;
    (void)base;
    (void)id;
    uint32_t what = *(const uint32_t *)data;
    WLOCK();
    if (what == CAL_WIFI_TOGGLE) {
        what = s_state == W_OFF ? CAL_WIFI_ON : CAL_WIFI_OFF;
    }
    switch (what) {
    case CAL_WIFI_OFF: stop_radio(); break;
    case CAL_WIFI_ON: start_sta(); break;
    case CAL_WIFI_PROVISION: s_state == W_AP ? stop_radio() : start_ap(); break;
    default: break;
    }
    WUNLOCK();
}

esp_err_t caliper_wifi_init(void)
{
    s_wlock = xSemaphoreCreateRecursiveMutex();
    if (!s_wlock) {
        return ESP_ERR_NO_MEM;
    }
    ESP_RETURN_ON_ERROR(esp_event_handler_instance_register(WIFI_EVENT, ESP_EVENT_ANY_ID, on_wifi, NULL, NULL),
                        TAG, "wifi evt");
    ESP_RETURN_ON_ERROR(esp_event_handler_instance_register(IP_EVENT, IP_EVENT_STA_GOT_IP, on_wifi, NULL, NULL),
                        TAG, "ip evt");
    push_init();
    return bus_subscribe(CAL_EVT_WIFI, on_cmd, NULL);
}
