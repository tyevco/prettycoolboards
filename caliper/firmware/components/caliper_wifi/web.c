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
 */
#include <stdio.h>
#include <stdlib.h>
#include <string.h>

#include "caliper_core.h"
#include "caliper_gatt.h"
#include "caliper_wifi.h"
#include "esp_http_server.h"
#include "esp_log.h"
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
    "document.getElementById('u').textContent=j.unit+((j.flags&1)?'  HOLD':'')+((j.flags&8)?'  SENSOR ERROR':'')+"
    "'  battery '+j.battery+'%';const t=document.getElementById('t');t.className=j.tol;"
    "t.textContent=j.profile?(j.profile+': '+j.tol):''}catch(e){}setTimeout(p,250)}p()</script></body></html>";

static const char PAGE_LOG[] =
    "<h2>Log</h2><table><thead><tr><th>#</th><th>time (UTC)</th><th>value</th><th>unit</th><th>flags</th>"
    "<th>profile</th></tr></thead><tbody id=b></tbody></table><button id=m>more</button>"
    "<script>let f=0;const F=['H','P','F','E'];async function l(){const r=await fetch('/api/log?from='+f+'&n=200');"
    "const a=await r.json();const b=document.getElementById('b');for(const x of a){const tr=document.createElement('tr');"
    "const d=x.unix_s?new Date(x.unix_s*1000).toISOString().replace('T',' ').slice(0,19):'';"
    "const v=x.unit?(x.value_nm/25.4e6).toFixed(4):(x.value_nm/1e6).toFixed(2);"
    "const fl=F.filter((c,i)=>x.flags&(1<<i)).join('');"
    "tr.innerHTML='<td>'+x.seq+'</td><td>'+d+'</td><td>'+v+'</td><td>'+(x.unit?'in':'mm')+'</td><td>'+fl+"
    "'</td><td>'+(x.profile_id||'')+'</td>';b.appendChild(tr);f=x.seq+1}"
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

static esp_err_t send_page(httpd_req_t *r, const char *body)
{
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
    char js[CALIPER_SETTINGS_MAX_LEN + 1];
    int n = core_settings_read_json(js, sizeof(js));
    if (n < 0) {
        return httpd_resp_send_500(r);
    }
    httpd_resp_set_type(r, "application/json");
    return httpd_resp_send(r, js, n);
}

static void reconnect_cb(void *arg)
{
    (void)arg;
    core_command(CORE_CMD_WIFI, CAL_WIFI_ON);
}

static esp_err_t h_settings_post(httpd_req_t *r)
{
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
        if (core_settings_set(key, val) != SETTINGS_OK && !err_key) {
            static char bad[24];
            strlcpy(bad, key, sizeof(bad));
            err_key = bad;
        }
    }
    settings_t after;
    core_get_settings(&after);
    bool creds_changed = strcmp(before.wifi_ssid, after.wifi_ssid) != 0 || strcmp(before.wifi_pass, after.wifi_pass) != 0;

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
