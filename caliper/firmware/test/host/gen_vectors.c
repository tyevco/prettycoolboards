/*
 * Prints the byte vectors of public/caliper/app/protocol.vectors.test.mjs, produced by the firmware's
 * own portable codec (gatt_codec.c, logrec.c), so the page and the firmware agree byte for byte.
 * Built with the host tests (target gen_vectors, not a test):  ./gen_vectors
 * Each line: <name> <hex>. Paste the hex into the .mjs when the contract changes.
 */
#include <stdint.h>
#include <stdio.h>

#include "caliper_gatt.h"
#include "gatt_codec.h"
#include "logrec.h"

static void hex(const char *name, const uint8_t *b, size_t n)
{
    printf("%-28s ", name);
    for (size_t i = 0; i < n; i++) printf("%02x", b[i]);
    printf("\n");
}

static void live(const char *name, gatt_live_t l)
{
    uint8_t b[CALIPER_LIVE_LEN];
    gatt_live_pack(&l, b);
    hex(name, b, sizeof(b));
}

static void rec(const char *name, logrec_t r, bool ext)
{
    uint8_t b[CALIPER_LOGREC_LEN];
    gatt_log_record_pack(&r, ext, b);
    hex(name, b, sizeof(b));
}

static void cmd(const char *name, gatt_cmd_t c)
{
    uint8_t b[8];
    size_t n = gatt_cmd_build(&c, b, sizeof(b));
    hex(name, b, n);
}

int main(void)
{
    /* LIVE (v3, 20 bytes) */
    live("live_all_flags", (gatt_live_t){.value_nm = -1, .cap_nm = CALIPER_CAP_INVALID, .unit = 1, .flags = 0x3f,
                                         .active_profile_id = 0xffff, .capture_aux_nm = CALIPER_AUX_INVALID});
    live("live_int32max", (gatt_live_t){.value_nm = INT32_MAX, .cap_nm = -25400000, .unit = 0, .flags = 0x12,
                                        .active_profile_id = 0x1234, .capture_aux_nm = CALIPER_AUX_INVALID});
    live("live_cap_min1", (gatt_live_t){.value_nm = 0, .cap_nm = INT32_MIN + 1, .unit = 0, .flags = 0x10,
                                        .active_profile_id = 0, .capture_aux_nm = CALIPER_AUX_INVALID});
    /* a frozen SWEEP MIN of 20.012 mm, the other extreme 20.041, n 214, auto, HOLD | TOL_PASS */
    live("live_sweep_done_min", (gatt_live_t){.value_nm = 20012000, .cap_nm = CALIPER_CAP_INVALID, .unit = 0,
                                              .flags = 0x03, .active_profile_id = 7,
                                              .capture_mode = CALIPER_CAPTURE_SWEEP, .sweep_sel = CALIPER_SWEEP_AUTO,
                                              .capture_state = CALIPER_CAPST_DONE, .which = CALIPER_CAPST_WHICH_MIN,
                                              .capture_n = 214, .capture_aux_nm = 20041000});
    /* a running SWEEP MAX (forced), inch, n saturated, aux below zero */
    live("live_sweep_run_max", (gatt_live_t){.value_nm = -12700, .cap_nm = CALIPER_CAP_INVALID, .unit = 1,
                                             .flags = 0x00, .active_profile_id = 0,
                                             .capture_mode = CALIPER_CAPTURE_SWEEP, .sweep_sel = CALIPER_SWEEP_MAX,
                                             .capture_state = CALIPER_CAPST_RUN, .which = CALIPER_CAPST_WHICH_MAX,
                                             .capture_n = 0xffff, .capture_aux_nm = -40000});
    /* a frozen SETTLE median, sd 412 nm, n 32 */
    live("live_settle_done", (gatt_live_t){.value_nm = 25000244, .cap_nm = CALIPER_CAP_INVALID, .unit = 0,
                                           .flags = 0x01, .active_profile_id = 0,
                                           .capture_mode = CALIPER_CAPTURE_SETTLE, .sweep_sel = CALIPER_SWEEP_MIN,
                                           .capture_state = CALIPER_CAPST_DONE, .capture_n = 32,
                                           .capture_aux_nm = 412});
    /* a SWEEP aborted by a sensor error */
    live("live_sweep_abort", (gatt_live_t){.value_nm = 5, .cap_nm = CALIPER_CAP_INVALID, .unit = 0, .flags = 0x08,
                                           .active_profile_id = 0, .capture_mode = CALIPER_CAPTURE_SWEEP,
                                           .capture_state = CALIPER_CAPST_ABORT, .capture_aux_nm = CALIPER_AUX_INVALID});

    /* LOG records: plain read (byte 12 = unit only) and the extended read (unit + kind) */
    logrec_t r = {.seq = 0xa1b2c3d4u, .unix_s = 1700000000u, .value_nm = -1, .unit = 1, .flags = 6,
                  .profile_id = 0xbeef};
    rec("log_plain", r, false);
    r.kind = CALIPER_LOG_KIND_SWEEP_MAX;
    rec("log_sweepmax_masked", r, false);
    rec("log_sweepmax_ext", r, true);
    logrec_t s = {.seq = 9, .unix_s = 0, .value_nm = 20012000, .unit = 0, .flags = 3, .profile_id = 7,
                  .kind = CALIPER_LOG_KIND_SWEEP_MIN};
    rec("log_sweepmin_ext", s, true);
    s.kind = CALIPER_LOG_KIND_SETTLE;
    s.unit = 1;
    rec("log_settle_inch_ext", s, true);
    logrec_t e = logrec_end_marker();
    rec("log_end", e, true);

    /* COMMAND */
    cmd("cmd_set_time", (gatt_cmd_t){.op = CALIPER_OP_SET_TIME, .arg = 0xdeadbeef});
    cmd("cmd_select_profile", (gatt_cmd_t){.op = CALIPER_OP_SELECT_PROFILE, .arg = 0xffff});
    cmd("cmd_log_read", (gatt_cmd_t){.op = CALIPER_OP_LOG_READ, .arg = 0xfffffffe});
    cmd("cmd_log_read_kind", (gatt_cmd_t){.op = CALIPER_OP_LOG_READ, .arg = 0x12345678, .opts = CALIPER_LOG_OPT_KIND});
    cmd("cmd_set_unit", (gatt_cmd_t){.op = CALIPER_OP_SET_UNIT, .arg = 0});
    cmd("cmd_set_capture_sweep_auto", (gatt_cmd_t){.op = CALIPER_OP_SET_CAPTURE, .arg = CALIPER_CAPTURE_SWEEP});
    cmd("cmd_set_capture_sweep_max",
        (gatt_cmd_t){.op = CALIPER_OP_SET_CAPTURE, .arg = CALIPER_CAPTURE_SWEEP | (CALIPER_SWEEP_MAX << 8)});
    cmd("cmd_set_capture_settle", (gatt_cmd_t){.op = CALIPER_OP_SET_CAPTURE, .arg = CALIPER_CAPTURE_SETTLE});
    cmd("cmd_set_capture_off", (gatt_cmd_t){.op = CALIPER_OP_SET_CAPTURE, .arg = CALIPER_CAPTURE_LIVE});
    cmd("cmd_capture_reset", (gatt_cmd_t){.op = CALIPER_OP_CAPTURE_RESET});
    /* what the parser refuses: SET (reserved), a bad selection, an unknown LOG_READ option */
    const uint8_t refused[3][6] = {{0x05, 0x03, 0x00}, {0x05, 0x02, 0x03}, {0x10, 0, 0, 0, 0, 0x02}};
    const size_t rl[3] = {3, 3, 6};
    for (int i = 0; i < 3; i++) {
        gatt_cmd_t c;
        printf("refused_%d %d\n", i, gatt_cmd_parse(refused[i], rl[i], &c));
    }
    return 0;
}
