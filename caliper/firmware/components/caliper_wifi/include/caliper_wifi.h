/*
 * wifi: on demand (off by default, it costs ~100 mA).
 *   - station with the credentials from settings (wifi_ssid / wifi_pass)
 *   - SoftAP provisioning fallback ("Caliper-XXXX", WPA2 with a random password shown on the
 *     display) when there are no credentials, the station fails 5 times, or on request
 *   - an HTTP server: live page, log table, CSV download, settings form (both modes)
 *   - optional push of each recorded reading: MQTT publish and/or HTTP POST (station only)
 */
#pragma once

#include <stdbool.h>

#include "esp_err.h"

#ifdef __cplusplus
extern "C" {
#endif

esp_err_t caliper_wifi_init(void); /* registers handlers; the radio stays off */
bool caliper_wifi_active(void);

/* internal */
esp_err_t web_start(void);
void web_stop(void);
void push_start(void);  /* station up */
void push_stop(void);
void push_init(void);
void caliper_wifi_reconnect_sta(void); /* after new credentials arrive via the web form */

#ifdef __cplusplus
}
#endif
