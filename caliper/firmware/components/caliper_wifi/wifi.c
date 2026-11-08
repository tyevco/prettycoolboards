/* Wi-Fi station / provisioning AP state machine. */
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

static const char *TAG = "wifi";

#define STA_RETRIES 5

typedef enum { W_OFF = 0, W_CONNECTING = 1, W_STA = 2, W_AP = 3 } wstate_t;

static bool s_inited;
static wstate_t s_state;
static int s_retries;
static esp_netif_t *s_sta, *s_ap;
static char s_ap_ssid[24], s_ap_pass[12];

bool caliper_wifi_active(void)
{
    return s_state != W_OFF;
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
    snprintf(s_ap_pass, sizeof(s_ap_pass), "%08lu", (unsigned long)(esp_random() % 100000000u));
    wifi_config_t ap = {0};
    strlcpy((char *)ap.ap.ssid, s_ap_ssid, sizeof(ap.ap.ssid));
    ap.ap.ssid_len = (uint8_t)strlen(s_ap_ssid);
    strlcpy((char *)ap.ap.password, s_ap_pass, sizeof(ap.ap.password));
    ap.ap.channel = 6;
    ap.ap.authmode = WIFI_AUTH_WPA2_PSK;
    ap.ap.max_connection = 2;
    esp_wifi_set_mode(WIFI_MODE_AP);
    esp_wifi_set_config(WIFI_IF_AP, &ap);
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
    strlcpy((char *)sta.sta.ssid, s.wifi_ssid, sizeof(sta.sta.ssid));
    strlcpy((char *)sta.sta.password, s.wifi_pass, sizeof(sta.sta.password));
    sta.sta.threshold.authmode = s.wifi_pass[0] ? WIFI_AUTH_WPA2_PSK : WIFI_AUTH_OPEN;
    sta.sta.pmf_cfg.capable = true;
    esp_wifi_set_mode(WIFI_MODE_STA);
    esp_wifi_set_config(WIFI_IF_STA, &sta);
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
    start_sta();
}

static void on_wifi(void *arg, esp_event_base_t base, int32_t id, void *data)
{
    (void)arg;
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

static void on_cmd(void *arg, esp_event_base_t base, int32_t id, void *data)
{
    (void)arg;
    (void)base;
    (void)id;
    uint32_t what = *(const uint32_t *)data;
    if (what == CAL_WIFI_TOGGLE) {
        what = s_state == W_OFF ? CAL_WIFI_ON : CAL_WIFI_OFF;
    }
    switch (what) {
    case CAL_WIFI_OFF: stop_radio(); break;
    case CAL_WIFI_ON: start_sta(); break;
    case CAL_WIFI_PROVISION: s_state == W_AP ? stop_radio() : start_ap(); break;
    default: break;
    }
}

esp_err_t caliper_wifi_init(void)
{
    ESP_RETURN_ON_ERROR(esp_event_handler_instance_register(WIFI_EVENT, ESP_EVENT_ANY_ID, on_wifi, NULL, NULL),
                        TAG, "wifi evt");
    ESP_RETURN_ON_ERROR(esp_event_handler_instance_register(IP_EVENT, IP_EVENT_STA_GOT_IP, on_wifi, NULL, NULL),
                        TAG, "ip evt");
    push_init();
    return bus_subscribe(CAL_EVT_WIFI, on_cmd, NULL);
}
