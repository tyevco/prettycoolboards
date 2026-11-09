/* Line CLI on the USB console. Type "help".
 * All output goes through out() -> usb_console_write(), which waits for the host: printf to the
 * console is non-blocking and truncated long output (see usb.c). */
#include <stdarg.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>

#include "bringup.h"
#include "caliper_core.h"
#include "caliper_usb.h"
#include "esp_app_desc.h"
#include "esp_system.h"
#include "freertos/FreeRTOS.h"
#include "freertos/queue.h"
#include "freertos/task.h"
#include "sdkconfig.h"
#include "soc/rtc_cntl_reg.h"
#include "store.h"

#define CLI_LINE_MAX 160

typedef struct {
    char s[CLI_LINE_MAX];
} line_t;

static QueueHandle_t s_q;

static void out(const char *fmt, ...) __attribute__((format(printf, 1, 2)));
static void out(const char *fmt, ...)
{
    char b[256];
    va_list ap;
    va_start(ap, fmt);
    int n = vsnprintf(b, sizeof(b), fmt, ap);
    va_end(ap);
    if (n <= 0) {
        return;
    }
    size_t len = (size_t)n < sizeof(b) ? (size_t)n : sizeof(b) - 1;
    /* "\n" -> "\r\n", as the console VFS does for printf */
    size_t start = 0;
    for (size_t i = 0; i < len; i++) {
        if (b[i] == '\n' && (i == 0 || b[i - 1] != '\r')) {
            usb_console_write(b + start, i - start);
            usb_console_write("\r\n", 2);
            start = i + 1;
        }
    }
    usb_console_write(b + start, len - start);
}

static char s_acc[CLI_LINE_MAX];
static size_t s_len;

void cli_feed(const char *buf, size_t len)
{
    for (size_t i = 0; i < len; i++) {
        char c = buf[i];
        if (c == '\r' || c == '\n') {
            if (s_len) {
                line_t l;
                s_acc[s_len] = '\0';
                strlcpy(l.s, s_acc, sizeof(l.s));
                s_len = 0;
                if (s_q) {
                    xQueueSend(s_q, &l, 0);
                }
            }
        } else if ((c == '\b' || c == 0x7f) && s_len) {
            s_len--;
        } else if (s_len + 1 < sizeof(s_acc) && c >= 0x20) {
            s_acc[s_len++] = c;
        }
    }
}

static esp_err_t console_writer(void *ctx, const char *buf, size_t len)
{
    (void)ctx;
    return usb_console_write(buf, len); /* an error (host gone) stops the export */
}

static void print_live(void)
{
    cal_live_t lv;
    core_get_live(&lv);
    out("%s %s flags=0x%02x%s cap=%ld nm profile=%u\n", lv.text, lv.unit ? "in" : "mm", lv.flags,
           (lv.flags & 1) ? " HOLD" : "", (long)lv.cap_nm, (unsigned)lv.profile_id);
    const cal_capture_t *c = &lv.capture;
    static const char *const modes[] = {"off", "settle", "sweep", "set"}, *const sels[] = {"auto", "min", "max"};
    static const char *const states[] = {"idle", "armed", "tracking", "frozen", "aborted"};
    out("capture %s/%s %s%s which=%d n=%lu other=%ld range=%ld sd=%ld nm\n", modes[c->mode & 3], sels[c->sel % 3],
        states[c->state % 5], c->manual_hold ? " (hand hold)" : "", c->which, (unsigned long)c->n,
        (long)c->other_nm, (long)c->range_nm, (long)c->sd_nm);
}

static void print_status(void)
{
    cal_status_t st;
    core_get_status(&st);
    out("fw %s, battery %u%% %umV%s%s, ble %s, wifi %u %s, log %lu records (next %lu), idle %lu ms\n",
           esp_app_get_description()->version, st.battery_pct, st.battery_mv, st.charging ? " charging" : "",
           st.vbus ? " vbus" : "", st.ble_connected ? "connected" : "idle", st.wifi, st.ip,
           (unsigned long)store_log_count(), (unsigned long)store_log_next_seq(), (unsigned long)core_idle_ms());
}

static void print_log(uint32_t from, uint32_t n)
{
    logrec_t r[16];
    uint32_t seq = from, shown = 0;
    while (shown < n) {
        uint32_t next;
        size_t want = n - shown < 16 ? n - shown : 16;
        size_t got = store_log_read(seq, r, want, &next);
        if (!got) {
            break;
        }
        for (size_t i = 0; i < got; i++) {
            out("%lu\t%lu\t%ld nm\t%s\tflags 0x%02x\tprofile %u\n", (unsigned long)r[i].seq,
                   (unsigned long)r[i].unix_s, (long)r[i].value_nm, r[i].unit ? "in" : "mm", r[i].flags,
                   r[i].profile_id);
        }
        shown += (uint32_t)got;
        seq = next;
    }
}

static void print_profiles(void)
{
    meas_profile_t p[16];
    size_t n = core_get_profiles(p, 16);
    for (size_t i = 0; i < n; i++) {
        out("%u\t%-16s nominal %ld nm  -%ld / +%ld nm\n", p[i].id, p[i].name, (long)p[i].nominal_nm,
               (long)p[i].tol_minus_nm, (long)p[i].tol_plus_nm);
    }
    if (!n) {
        out("no profiles\n");
    }
}

#if CONFIG_CALIPER_BRINGUP
/* For the bring-up checks: the next console line (an operator's y/n), read from the CLI queue
 * while a "bu" command runs in this task. */
static bool ask(char *line, size_t len, uint32_t timeout_ms)
{
    line_t l;
    if (!s_q || xQueueReceive(s_q, &l, pdMS_TO_TICKS(timeout_ms)) != pdTRUE) {
        return false;
    }
    strlcpy(line, l.s, len);
    return true;
}

static const bu_io_t s_bu_io = {.out = out, .ask = ask};
#endif

static void help(void)
{
    /* out() formats into 256 bytes: the four lines in one call (257 bytes) lost their last two
     * characters ("bootloader\n" printed as "bootloade") */
    out("read | status | zero | hold | rec | send | unit mm|in | log [from] [n] | csv | clear yes\n"
           "capture off|settle|sweep [auto|min|max] | rearm\n");
    out("get | set <key> <value> | profiles | profile <id> | time <unix_s> | wifi on|off|ap\n"
           "export | sleep | reboot | bootloader\n");
#if CONFIG_CALIPER_BRINGUP
    out("bu help: bring-up checks\n");
#endif
}

static void run(char *line)
{
#if CONFIG_CALIPER_BRINGUP
    if (!strncmp(line, "bu", 2) && (line[2] == ' ' || line[2] == '\0')) {
        bringup_cmd(&s_bu_io, line + 2);
        return;
    }
#endif
    char *save = NULL;
    char *cmd = strtok_r(line, " ", &save);
    char *a1 = strtok_r(NULL, " ", &save);
    char *a2 = save && *save ? save : strtok_r(NULL, "", &save);
    if (!cmd) {
        return;
    }
    if (!strcmp(cmd, "help") || !strcmp(cmd, "?")) help();
    else if (!strcmp(cmd, "read")) print_live();
    else if (!strcmp(cmd, "status")) print_status();
    else if (!strcmp(cmd, "zero")) core_command(CORE_CMD_ZERO, 0);
    else if (!strcmp(cmd, "hold")) core_command(CORE_CMD_HOLD_TOGGLE, 0);
    else if (!strcmp(cmd, "rec")) core_command(CORE_CMD_RECORD, 0);
    else if (!strcmp(cmd, "send")) core_command(CORE_CMD_SEND, 0);
    else if (!strcmp(cmd, "unit") && a1) core_command(CORE_CMD_SET_UNIT, !strcmp(a1, "in") ? 1 : 0);
    else if (!strcmp(cmd, "capture") && a1) {
        uint32_t mode = !strcmp(a1, "sweep") ? CALIPER_CAPTURE_SWEEP : !strcmp(a1, "settle") ? CALIPER_CAPTURE_SETTLE
                                                                                               : CALIPER_CAPTURE_LIVE;
        uint32_t sel = a2 && !strcmp(a2, "min") ? CALIPER_SWEEP_MIN : a2 && !strcmp(a2, "max") ? CALIPER_SWEEP_MAX
                                                                                                : CALIPER_SWEEP_AUTO;
        core_command(CORE_CMD_SET_CAPTURE, mode | (sel << 8));
    } else if (!strcmp(cmd, "rearm")) core_command(CORE_CMD_CAPTURE_RESET, 0);

    else if (!strcmp(cmd, "log")) print_log(a1 ? (uint32_t)strtoul(a1, NULL, 10) : 0, a2 ? (uint32_t)strtoul(a2, NULL, 10) : 20);
    else if (!strcmp(cmd, "csv")) {
        settings_t s;
        core_get_settings(&s);
        store_log_export_csv(true, s.decimals, console_writer, NULL);
    } else if (!strcmp(cmd, "clear") && a1 && !strcmp(a1, "yes")) core_command(CORE_CMD_LOG_CLEAR, 0);
    else if (!strcmp(cmd, "get")) {
        char js[256];
        if (core_settings_read_json(js, sizeof(js)) > 0) {
            out("%s\n", js);
        }
    } else if (!strcmp(cmd, "set") && a1) {
        int rc = core_settings_set(a1, a2 ? a2 : "");
        if (rc == SETTINGS_OK) {
            out("ok\n");
        } else {
            out("rejected (%d)\n", rc);
        }
    } else if (!strcmp(cmd, "profiles")) print_profiles();
    else if (!strcmp(cmd, "profile") && a1) core_command(CORE_CMD_SELECT_PROFILE, (uint32_t)strtoul(a1, NULL, 10));
    else if (!strcmp(cmd, "time") && a1) core_command(CORE_CMD_SET_TIME, (uint32_t)strtoul(a1, NULL, 10));
    else if (!strcmp(cmd, "wifi") && a1) {
        uint32_t w = !strcmp(a1, "on") ? CAL_WIFI_ON : !strcmp(a1, "ap") ? CAL_WIFI_PROVISION : CAL_WIFI_OFF;
        core_command(CORE_CMD_WIFI, w);
    } else if (!strcmp(cmd, "export")) out("%s\n", esp_err_to_name(msc_export()));
    else if (!strcmp(cmd, "sleep")) core_command(CORE_CMD_SLEEP, 0);
    else if (!strcmp(cmd, "reboot")) esp_restart();
    else if (!strcmp(cmd, "bootloader")) {
        /* ROM download mode on the next reset (flash over USB-Serial-JTAG) */
        out("rebooting into the ROM bootloader\n");
        fflush(stdout);
        vTaskDelay(pdMS_TO_TICKS(100));
        REG_WRITE(RTC_CNTL_OPTION1_REG, RTC_CNTL_FORCE_DOWNLOAD_BOOT);
        esp_restart();
    } else {
        out("? (help)\n");
    }
}

static void cli_task(void *arg)
{
    (void)arg;
    line_t l;
    for (;;) {
        if (xQueueReceive(s_q, &l, portMAX_DELAY) == pdTRUE) {
            core_activity();
            run(l.s);
            fflush(stdout);
        }
    }
}

void cli_start(void)
{
    if (s_q) {
        return;
    }
    s_q = xQueueCreate(4, sizeof(line_t));
    xTaskCreatePinnedToCore(cli_task, "cli", 4096, NULL, 3, NULL, 0);
}
