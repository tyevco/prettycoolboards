/*
 * HTTP server (esp_http_server).
 *   GET  /               live reading page (polls /api/live at 4 Hz)
 *   GET  /api/live       {"value_nm","text","unit","flags","cap_nm","tol","profile","battery"}
 *   POST /api/cmd?c=X    X = zero | hold | record | send | unit
 *   GET  /log            log table page (fetches /api/log)
 *   GET  /api/log?from=S&n=N   JSON array of records (N <= 200)
 *   GET  /log.csv        the whole log as CSV
 *   GET  /settings       settings form;  GET /api/settings  JSON (no wifi_pass)
 *   POST /settings       form-urlencoded; an empty wifi_pass keeps the stored one
 *
 * There is no login (anyone on the network, or the setup AP, can use it, as documented). What the
 * 2026-11-07 review added is protection against *other web pages* driving it through the user's
 * browser:
 *  - DNS rebinding: a page on evil.example that re-resolves its own name to the caliper's IP is
 *    "same origin" for the browser and could read /api/log or post settings. Every request must
 *    carry a Host header naming the caliper itself (its IP, the AP address, or its DHCP hostname),
 *    else 403.
 *  - CSRF: a cross-site <form method=post> (no CORS preflight) could rewrite wifi_ssid/wifi_pass,
 *    point http_post_url at the attacker (every later reading pushed there) or press ZERO. POSTs
 *    carrying an Origin that is not this host, or Sec-Fetch-Site other than same-origin/none, get
 *    403. Clients that send neither (curl, scripts) still work.
 *  - The pages send X-Frame-Options DENY (no click-jacking of the buttons/form), nosniff, a CSP that
 *    only allows this origin, and no referrer.
 * Output: every value the pages show is set with textContent / .value, never parsed as HTML.
 */
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <strings.h>

#include "caliper_core.h"
#include "caliper_gatt.h"
#include "caliper_wifi.h"
#include "esp_http_server.h"
#include "esp_log.h"
#include "esp_netif.h"
#include "esp_timer.h"
#include "store.h"

static const char *TAG = "web";
static httpd_handle_t s_srv;

static const char PAGE_HEAD[] =
    "<!doctype html><html><head><meta charset=utf-8><meta name=viewport content='width=device-width,initial-scale=1'>"
    "<title>Caliper</title><style>body{font-family:system-ui,sans-serif;background:#0b0d10;color:#e6e8eb;margin:0;"
    "padding:16px;max-width:640px}a{color:#38bdf8}button{font-size:1rem;padding:.6em 1em;margin:.2em;border-radius:8px;"
    "border:1px solid #334155;background:#1e293b;color:#e6e8eb}#v{font-size:4rem;font-variant-numeric:tabular-nums}"
    "table{border-collapse:collapse;width:100%}td,th{padding:4px 8px;border-bottom:1px solid #1e293b;text-align:right}"
    "input,select{font-size:1rem;width:100%;box-sizing:border-box;padding:.4em;margin:.2em 0 .8em;background:#111827;"
    "color:#e6e8eb;border:1px solid #334155;border-radius:6px}.pass{color:#22c55e}.fail{color:#ef4444}.warn{color:#f59e0b}"
    "</style></head><body><nav><a href=/>Live</a> &middot; <a href=/log>Log</a> &middot; <a href=/settings>Settings</a>"
    " &middot; <a href=/log.csv>CSV</a></nav>";

static const char PAGE_LIVE[] =
    "<h1 id=v>--</h1><div id=u></div><div id=t></div><p>"
    "<button onclick=\"c('zero')\">Zero</button><button onclick=\"c('hold')\">Hold</button>"
    "<button onclick=\"c('record')\">Record</button><button onclick=\"c('unit')\">mm/in</button></p>"
    "<script>function c(x){fetch('/api/cmd?c='+x,{method:'POST'})}"
    "async function p(){try{const r=await fetch('/api/live');const j=await r.json();"
    "document.getElementById('v').textContent=j.text;"
    "document.getElementById('u').textContent=j.unit+((j.flags&1)?'  HOLD':'')+((j.flags&8)?'  SENSOR ERROR':'')+((j.flags&64)?'  PRESS ZERO':'')+"
    "'  battery '+j.battery+'%';const t=document.getElementById('t');t.className=j.tol;"
    "t.textContent=j.profile?(j.profile+': '+j.tol):''}catch(e){}setTimeout(p,250)}p()</script></body></html>";

static const char PAGE_LOG[] =
    "<h2>Log</h2><table><thead><tr><th>#</th><th>time (UTC)</th><th>value</th><th>unit</th><th>flags</th>"
    "<th>profile</th></tr></thead><tbody id=b></tbody></table><button id=m>more</button>"
    "<script>let f=0;const F=['H','P','F','E','','','Z'];async function l(){const r=await fetch('/api/log?from='+f+'&n=200');"
    "const a=await r.json();const b=document.getElementById('b');for(const x of a){const tr=document.createElement('tr');"
    "const d=x.unix_s?new Date(x.unix_s*1000).toISOString().replace('T',' ').slice(0,19):'';"
    "const v=x.unit?(x.value_nm/25.4e6).toFixed(4):(x.value_nm/1e6).toFixed(2);"
    "const fl=F.filter((c,i)=>x.flags&(1<<i)).join('');"
    "for(const t of [x.seq,d,v,x.unit?'in':'mm',fl,x.profile_id||'']){const td=document.createElement('td');"
    "td.textContent=String(t);tr.appendChild(td)}b.appendChild(tr);f=x.seq+1}"
    "document.getElementById('m').style.display=a.length<200?'none':''}"
    "document.getElementById('m').onclick=l;l()</script></body></html>";

static const char PAGE_SETTINGS[] =
    "<h2>Settings</h2><form method=post action=/settings>"
    "<label>Name<input name=name maxlength=20></label>"
    "<label>Wi-Fi network<input name=wifi_ssid maxlength=32></label>"
    "<label>Wi-Fi password (blank = unchanged)<input name=wifi_pass type=password maxlength=64></label>"
    "<label>MQTT broker (mqtt://host)<input name=mqtt_url maxlength=64></label>"
    "<label>HTTP POST URL<input name=http_post_url maxlength=64></label>"
    "<label>Auto-off (s, 0 = never, 30..3600)<input name=auto_off_s type=number min=0 max=3600></label>"
    "<label>After a sent reading<select name=hid_suffix><option value=enter>Enter</option>"
    "<option value=tab>Tab</option><option value=none>nothing</option></select></label>"
    "<label>mm decimals<select name=decimals><option>1</option><option>2</option><option>3</option></select></label>"
    "<button>Save</button></form><p id=s></p>"
    "<script>fetch('/api/settings').then(r=>r.json()).then(j=>{const f=document.forms[0];"
    "for(const k of ['name','wifi_ssid','mqtt_url','http_post_url','auto_off_s','decimals'])f[k].value=j[k];"
    "f.hid_suffix.value=j.hid_suffix=='\\n'?'enter':j.hid_suffix=='\\t'?'tab':'none'});"
    "const q=new URLSearchParams(location.search);if(q.has('saved'))document.getElementById('s').textContent='Saved.';"
    "if(q.has('err'))document.getElementById('s').textContent='Rejected: '+q.get('err')</script></body></html>";

/* ---- request guard ---------------------------------------------------------------------- */

/* host[:port] -> host (lower-cased in place); false if it does not fit */
static bool host_part(char *h)
{
    for (char *c = h; *c; c++) {
        if (*c == ':') {
            *c = '\0';
            break;
        }
        if (*c >= 'A' && *c <= 'Z') {
            *c = (char)(*c - 'A' + 'a');
        }
    }
    return h[0] != '\0';
}

/* The Host header must name this device: its station IP, the setup AP address, or its DHCP
 * hostname (bare or with a domain suffix, e.g. "caliper.lan"). Anything else is DNS rebinding. */
static bool host_is_us(const char *host)
{
    cal_status_t st;
    core_get_status(&st);
    if (st.ip[0] && strcmp(host, st.ip) == 0) {
        return true;
    }
    if (st.wifi == 3 && strcmp(host, "192.168.4.1") == 0) {
        return true;
    }
    esp_netif_t *n = esp_netif_get_handle_from_ifkey("WIFI_STA_DEF");
    const char *hn = NULL;
    if (n && esp_netif_get_hostname(n, &hn) == ESP_OK && hn && hn[0]) {
        size_t l = strlen(hn);
        if (strncasecmp(host, hn, l) == 0 && (host[l] == '\0' || host[l] == '.')) {
            return true;
        }
    }
    return false;
}

static bool request_ok(httpd_req_t *r, bool is_post)
{
    char host[64], v[96];
    if (httpd_req_get_hdr_value_str(r, "Host", host, sizeof(host)) != ESP_OK) {
        return false;
    }
    char raw_host[64];
    strlcpy(raw_host, host, sizeof(raw_host));
    if (!host_part(host) || !host_is_us(host)) {
        return false;
    }
    if (!is_post) {
        return true;
    }
    if (httpd_req_get_hdr_value_str(r, "Sec-Fetch-Site", v, sizeof(v)) == ESP_OK && strcmp(v, "same-origin") != 0 &&
        strcmp(v, "none") != 0) {
        return false;
    }
    esp_err_t oe = httpd_req_get_hdr_value_str(r, "Origin", v, sizeof(v));
    if (oe == ESP_ERR_HTTPD_RESULT_TRUNC) {
        return false;
    }
    if (oe == ESP_OK) {
        char want[80];
        snprintf(want, sizeof(want), "http://%s", raw_host);
        if (strcasecmp(v, want) != 0) {
            return false;
        }
    }
    return true;
}

#define GUARD(r, post)                                                         \
    do {                                                                       \
        if (!request_ok((r), (post))) {                                        \
            return httpd_resp_send_err((r), HTTPD_403_FORBIDDEN, "forbidden"); \
        }                                                                      \
    } while (0)

static esp_err_t send_page(httpd_req_t *r, const char *body)
{
    GUARD(r, false);
    httpd_resp_set_hdr(r, "X-Frame-Options", "DENY");
    httpd_resp_set_hdr(r, "X-Content-Type-Options", "nosniff");
    httpd_resp_set_hdr(r, "Referrer-Policy", "no-referrer");
    httpd_resp_set_hdr(r, "Content-Security-Policy",
                       "default-src 'self'; script-src 'self' 'unsafe-inline'; style-src 'unsafe-inline'; "
                       "frame-ancestors 'none'; form-action 'self'");
    httpd_resp_set_hdr(r, "Cache-Control", "no-store");
    httpd_resp_set_type(r, "text/html; charset=utf-8");
    httpd_resp_send_chunk(r, PAGE_HEAD, HTTPD_RESP_USE_STRLEN);
    httpd_resp_send_chunk(r, body, HTTPD_RESP_USE_STRLEN);
    return httpd_resp_send_chunk(r, NULL, 0);
}

static esp_err_t h_index(httpd_req_t *r) { return send_page(r, PAGE_LIVE); }
static esp_err_t h_log_page(httpd_req_t *r) { return send_page(r, PAGE_LOG); }
static esp_err_t h_settings_page(httpd_req_t *r) { return send_page(r, PAGE_SETTINGS); }

static const char *tol_name(meas_tol_t t)
{
    switch (t) {
    case MEAS_TOL_PASS: return "pass";
    case MEAS_TOL_WARN: return "warn";
    case MEAS_TOL_FAIL_LOW:
    case MEAS_TOL_FAIL_HIGH: return "fail";
    default: return "";
    }
}

static esp_err_t h_live(httpd_req_t *r)
{
    GUARD(r, false);
    cal_live_t lv;
    cal_status_t st;
    core_get_live(&lv);
    core_get_status(&st);
    char b[256];
    /* profile names are user text: keep only safe characters in this hand-built JSON */
    char prof[MEAS_PROFILE_NAME_LEN + 1];
    size_t k = 0;
    for (size_t i = 0; lv.profile_name[i] && k < MEAS_PROFILE_NAME_LEN; i++) {
        char ch = lv.profile_name[i];
        prof[k++] = (ch == '"' || ch == '\\' || (unsigned char)ch < 0x20) ? '_' : ch;
    }
    prof[k] = '\0';
    snprintf(b, sizeof(b),
             "{\"value_nm\":%ld,\"text\":\"%s\",\"unit\":\"%s\",\"flags\":%u,\"cap_nm\":%ld,\"tol\":\"%s\","
             "\"profile\":\"%s\",\"battery\":%u}",
             (long)lv.value_nm, lv.text, lv.unit ? "in" : "mm", (unsigned)lv.flags, (long)lv.cap_nm,
             tol_name(lv.tol), prof, (unsigned)st.battery_pct);
    httpd_resp_set_type(r, "application/json");
    httpd_resp_set_hdr(r, "Cache-Control", "no-store");
    return httpd_resp_send(r, b, HTTPD_RESP_USE_STRLEN);
}

static bool query(httpd_req_t *r, const char *key, char *val, size_t n)
{
    char q[96];
    if (httpd_req_get_url_query_str(r, q, sizeof(q)) != ESP_OK) {
        return false;
    }
    return httpd_query_key_value(q, key, val, n) == ESP_OK;
}

static esp_err_t h_cmd(httpd_req_t *r)
{
    GUARD(r, true);
    char c[12];
    if (!query(r, "c", c, sizeof(c))) {
        return httpd_resp_send_err(r, HTTPD_400_BAD_REQUEST, "c missing");
    }
    if (strcmp(c, "zero") == 0) core_command(CORE_CMD_ZERO, 0);
    else if (strcmp(c, "hold") == 0) core_command(CORE_CMD_HOLD_TOGGLE, 0);
    else if (strcmp(c, "record") == 0) core_command(CORE_CMD_RECORD, 0);
    else if (strcmp(c, "send") == 0) core_command(CORE_CMD_SEND, 0);
    else if (strcmp(c, "unit") == 0) core_command(CORE_CMD_TOGGLE_UNIT, 0);
    else return httpd_resp_send_err(r, HTTPD_400_BAD_REQUEST, "unknown command");
    return httpd_resp_send(r, "ok", 2);
}

static esp_err_t h_log_json(httpd_req_t *r)
{
    GUARD(r, false);
    char v[12];
    uint32_t from = query(r, "from", v, sizeof(v)) ? (uint32_t)strtoul(v, NULL, 10) : 0;
    uint32_t n = query(r, "n", v, sizeof(v)) ? (uint32_t)strtoul(v, NULL, 10) : 100;
    if (n == 0 || n > 200) {
        n = 200;
    }
    httpd_resp_set_type(r, "application/json");
    httpd_resp_send_chunk(r, "[", 1);
    logrec_t recs[20];
    uint32_t seq = from, sent = 0;
    bool first = true;
    while (sent < n) {
        uint32_t next;
        size_t want = n - sent < 20 ? n - sent : 20;
        size_t got = store_log_read(seq, recs, want, &next);
        if (got == 0) {
            break;
        }
        char b[20 * 110];
        size_t used = 0;
        for (size_t i = 0; i < got; i++) {
            int l = snprintf(b + used, sizeof(b) - used,
                             "%s{\"seq\":%lu,\"unix_s\":%lu,\"value_nm\":%ld,\"unit\":%u,\"flags\":%u,\"profile_id\":%u}",
                             first ? "" : ",", (unsigned long)recs[i].seq, (unsigned long)recs[i].unix_s,
                             (long)recs[i].value_nm, recs[i].unit, recs[i].flags, recs[i].profile_id);
            if (l < 0 || (size_t)l >= sizeof(b) - used) {
                break; /* cannot happen with 20 x <= 106 bytes; never run past the buffer */
            }
            first = false;
            used += (size_t)l;
        }
        if (httpd_resp_send_chunk(r, b, (ssize_t)used) != ESP_OK) {
            return ESP_FAIL;
        }
        sent += (uint32_t)got;
        seq = next;
    }
    httpd_resp_send_chunk(r, "]", 1);
    return httpd_resp_send_chunk(r, NULL, 0);
}

static esp_err_t csv_chunk(void *ctx, const char *buf, size_t len)
{
    return httpd_resp_send_chunk((httpd_req_t *)ctx, buf, (ssize_t)len);
}

static esp_err_t h_csv(httpd_req_t *r)
{
    GUARD(r, false);
    settings_t s;
    core_get_settings(&s);
    httpd_resp_set_type(r, "text/csv");
    httpd_resp_set_hdr(r, "Content-Disposition", "attachment; filename=\"caliper-log.csv\"");
    esp_err_t err = store_log_export_csv(true, s.decimals, csv_chunk, r);
    if (err != ESP_OK) {
        return err;
    }
    return httpd_resp_send_chunk(r, NULL, 0);
}

static esp_err_t h_api_settings(httpd_req_t *r)
{
    GUARD(r, false);
    char js[CALIPER_SETTINGS_MAX_LEN + 1];
    int n = core_settings_read_json(js, sizeof(js));
    if (n < 0) {
        return httpd_resp_send_500(r);
    }
    httpd_resp_set_type(r, "application/json");
    httpd_resp_set_hdr(r, "Cache-Control", "no-store");
    return httpd_resp_send(r, js, n);
}

static void reconnect_cb(void *arg)
{
    (void)arg;
    core_command(CORE_CMD_WIFI, CAL_WIFI_ON);
}

static esp_err_t h_settings_post(httpd_req_t *r)
{
    GUARD(r, true);
    char body[768];
    if (r->content_len >= sizeof(body)) {
        return httpd_resp_send_err(r, HTTPD_400_BAD_REQUEST, "too long");
    }
    int got = 0;
    while (got < (int)r->content_len) {
        int n = httpd_req_recv(r, body + got, r->content_len - (size_t)got);
        if (n <= 0) {
            return ESP_FAIL;
        }
        got += n;
    }
    body[got] = '\0';

    settings_t before;
    core_get_settings(&before);
    const char *err_key = NULL;
    char *save = NULL;
    for (char *pair = strtok_r(body, "&", &save); pair; pair = strtok_r(NULL, "&", &save)) {
        char *eq = strchr(pair, '=');
        if (!eq) {
            continue;
        }
        *eq = '\0';
        char key[24], val[160];
        settings_url_decode(key, sizeof(key), pair, strlen(pair));
        settings_url_decode(val, sizeof(val), eq + 1, strlen(eq + 1));
        if (strcmp(key, "wifi_pass") == 0 && val[0] == '\0') {
            continue; /* blank = keep */
        }
        int rc = core_settings_set(key, val);
        memset(val, 0, sizeof(val)); /* may be the password */
        if (rc != SETTINGS_OK && !err_key) {
            /* the key goes into the Location header: keep [a-z_] only (a failed flash write can
             * reject even an unknown, attacker-chosen key) */
            static char bad[24];
            size_t k = 0;
            for (size_t i = 0; key[i] && k + 1 < sizeof(bad); i++) {
                char ch = key[i];
                if ((ch >= 'a' && ch <= 'z') || ch == '_') {
                    bad[k++] = ch;
                }
            }
            bad[k] = '\0';
            err_key = k ? bad : "value";
        }
    }
    memset(body, 0, sizeof(body));
    settings_t after;
    core_get_settings(&after);
    bool creds_changed = strcmp(before.wifi_ssid, after.wifi_ssid) != 0 || strcmp(before.wifi_pass, after.wifi_pass) != 0;
    memset(before.wifi_pass, 0, sizeof(before.wifi_pass));
    memset(after.wifi_pass, 0, sizeof(after.wifi_pass));

    char loc[48];
    snprintf(loc, sizeof(loc), err_key ? "/settings?err=%s" : "/settings?saved=1", err_key ? err_key : "");
    httpd_resp_set_status(r, "303 See Other");
    httpd_resp_set_hdr(r, "Location", loc);
    httpd_resp_send(r, NULL, 0);

    if (creds_changed && after.wifi_ssid[0]) {
        /* switch from the AP (or the old network) to the new one after the reply is out */
        static esp_timer_handle_t t;
        if (!t) {
            esp_timer_create_args_t a = {.callback = reconnect_cb, .name = "wifi_re"};
            esp_timer_create(&a, &t);
        }
        esp_timer_stop(t);
        esp_timer_start_once(t, 1500 * 1000);
    }
    return ESP_OK;
}

esp_err_t web_start(void)
{
    if (s_srv) {
        return ESP_OK;
    }
    httpd_config_t cfg = HTTPD_DEFAULT_CONFIG();
    cfg.max_uri_handlers = 12;
    cfg.stack_size = 6144;
    cfg.lru_purge_enable = true;
    /* LWIP_MAX_SOCKETS is 12: httpd's default 7 (+3 internal) left 2 for MQTT, the HTTP POST client
     * and DNS, so a push could fail while a browser held a few keep-alive connections */
    cfg.max_open_sockets = 4;
    esp_err_t err = httpd_start(&s_srv, &cfg);
    if (err != ESP_OK) {
        ESP_LOGE(TAG, "httpd_start: %s", esp_err_to_name(err));
        return err;
    }
    const httpd_uri_t uris[] = {
        {.uri = "/", .method = HTTP_GET, .handler = h_index},
        {.uri = "/api/live", .method = HTTP_GET, .handler = h_live},
        {.uri = "/api/cmd", .method = HTTP_POST, .handler = h_cmd},
        {.uri = "/log", .method = HTTP_GET, .handler = h_log_page},
        {.uri = "/api/log", .method = HTTP_GET, .handler = h_log_json},
        {.uri = "/log.csv", .method = HTTP_GET, .handler = h_csv},
        {.uri = "/settings", .method = HTTP_GET, .handler = h_settings_page},
        {.uri = "/settings", .method = HTTP_POST, .handler = h_settings_post},
        {.uri = "/api/settings", .method = HTTP_GET, .handler = h_api_settings},
    };
    for (size_t i = 0; i < sizeof(uris) / sizeof(uris[0]); i++) {
        httpd_register_uri_handler(s_srv, &uris[i]);
    }
    return ESP_OK;
}

void web_stop(void)
{
    if (s_srv) {
        httpd_stop(s_srv);
        s_srv = NULL;
    }
}
