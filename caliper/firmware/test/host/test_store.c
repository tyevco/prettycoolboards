/*
 * Host tests for components/store/store.c (the reading log), built against the stubs in
 * test/host/stubs: the LittleFS partition is a directory (STORE_BASE_PATH, set by CMake), NVS is
 * empty (it keeps u16 values only), the mutex is a no-op. Covers the v2 segmented layout,
 * wrap-around, the boot scan (reboot = store_test_reboot), clear, capacity changes, damaged slots /
 * headers, the CSV export, and the compass calibration in NVS. POSIX files do not model LittleFS's
 * atomic commits, so power loss itself is not tested here: what is tested is that whatever state a
 * slot or the header is left in, the scan does not accept a record that is not exactly where its
 * seq says.
 */
#include <dirent.h>
#include <stdint.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <sys/stat.h>
#include <unistd.h>

#include "caliper_gatt.h"
#include "le_bytes.h"
#include "logrec.h"
#include "store.h"
#include "tiny_test.h"

/* store.c calls fsync() through this (CMake: fsync=store_host_fsync): the data is already flushed
 * to the OS by fflush(), which is all a host test needs; counting proves every write is synced. */
static long s_fsyncs;
int store_host_fsync(int fd);
int store_host_fsync(int fd)
{
    s_fsyncs++;
    return fd >= 0 ? 0 : -1;
}

int tt_failures = 0;
int tt_checks = 0;
const char *tt_current = "";

#define DIR_ STORE_BASE_PATH
#define SEG_RECS 256

static void wipe(void)
{
    DIR *d = opendir(DIR_);
    if (d) {
        struct dirent *e;
        while ((e = readdir(d)) != NULL) {
            if (e->d_name[0] == '.') {
                continue;
            }
            char p[512];
            snprintf(p, sizeof(p), "%s/%s", DIR_, e->d_name);
            unlink(p);
        }
        closedir(d);
        rmdir(DIR_);
    }
}

static long file_size(const char *name)
{
    char p[512];
    snprintf(p, sizeof(p), "%s/%s", DIR_, name);
    struct stat st;
    return stat(p, &st) == 0 ? (long)st.st_size : -1;
}

static int count_files(const char *prefix)
{
    int n = 0;
    DIR *d = opendir(DIR_);
    if (!d) {
        return 0;
    }
    struct dirent *e;
    while ((e = readdir(d)) != NULL) {
        n += strncmp(e->d_name, prefix, strlen(prefix)) == 0;
    }
    closedir(d);
    return n;
}

static void append_n(uint32_t n, uint32_t *last_seq)
{
    for (uint32_t i = 0; i < n; i++) {
        logrec_t r = {.unix_s = 1700000000u, .unit = 0, .flags = CALIPER_FLAG_TOL_PASS, .profile_id = 7};
        r.value_nm = (int32_t)(store_log_next_seq() * 10u);
        CHECK(store_log_append(&r) == ESP_OK);
        *last_seq = r.seq;
    }
}

/* Reads everything from the oldest; checks order, contiguity and the values. */
static uint32_t read_all_(uint32_t *first, uint32_t *last, int contiguous)
{
    logrec_t recs[37];
    uint32_t seq = 0, n = 0, prev = 0;
    int ok = 1;
    *first = *last = 0;
    for (;;) {
        uint32_t next;
        size_t got = store_log_read(seq, recs, 37, &next);
        if (got == 0) {
            break;
        }
        for (size_t i = 0; i < got; i++) {
            if (n == 0) {
                *first = recs[i].seq;
            } else {
                ok &= !contiguous || recs[i].seq == prev + 1;
                ok &= recs[i].seq > prev;
            }
            ok &= recs[i].value_nm == (int32_t)(recs[i].seq * 10u) && recs[i].profile_id == 7;
            prev = recs[i].seq;
            n++;
        }
        seq = next;
    }
    *last = prev;
    CHECK(ok);
    return n;
}
#define read_all(f, l) read_all_(f, l, 1)

static void test_store_ring(void)
{
    wipe();
    CHECK(store_init() == ESP_OK);
    CHECK_EQ_INT(store_log_count(), 0);
    CHECK_EQ_INT(store_log_next_seq(), 1);
    CHECK_EQ_INT(file_size("log.hdr"), 16);

    uint32_t last = 0, first = 0, end = 0;
    append_n(700, &last); /* capacity 600 (stubs/sdkconfig.h): wraps once */
    CHECK_EQ_INT(last, 700);
    CHECK(s_fsyncs >= 700); /* every record is synced */
    CHECK_EQ_INT(store_log_count(), 600);
    CHECK_EQ_INT(read_all(&first, &end), 600);
    CHECK_EQ_INT(first, 101);
    CHECK_EQ_INT(end, 700);

    /* 600 slots = segments 0, 1 (256 each) and 2 (88): every one at most one 4 KiB block */
    CHECK_EQ_INT(count_files("log0"), 3);
    CHECK_EQ_INT(file_size("log000.bin"), SEG_RECS * 16);
    CHECK_EQ_INT(file_size("log001.bin"), SEG_RECS * 16);
    CHECK_EQ_INT(file_size("log002.bin"), (600 - 2 * SEG_RECS) * 16);

    logrec_t r;
    CHECK(store_log_get(700, &r) && r.seq == 700);
    CHECK(!store_log_get(100, &r)); /* overwritten */
    CHECK(store_log_get(101, &r) && r.seq == 101);

    /* reboot: the scan finds the newest record across the segments */
    CHECK(store_test_reboot(600) == ESP_OK);
    CHECK_EQ_INT(store_log_next_seq(), 701);
    CHECK_EQ_INT(read_all(&first, &end), 600);
    CHECK_EQ_INT(first, 101);
    append_n(1, &last);
    CHECK_EQ_INT(last, 701);

    /* clear survives a reboot; numbering continues */
    CHECK(store_log_clear() == ESP_OK);
    CHECK_EQ_INT(store_log_count(), 0);
    CHECK(store_test_reboot(600) == ESP_OK);
    CHECK_EQ_INT(store_log_count(), 0);
    CHECK_EQ_INT(store_log_next_seq(), 702);
    append_n(3, &last);
    CHECK_EQ_INT(last, 704);
    CHECK_EQ_INT(read_all(&first, &end), 3);
    CHECK_EQ_INT(first, 702);

    /* capacity change: fresh log, numbering continues, old segments gone */
    CHECK(store_test_reboot(300) == ESP_OK);
    CHECK_EQ_INT(store_log_count(), 0);
    CHECK_EQ_INT(store_log_next_seq(), 705);
    CHECK_EQ_INT(count_files("log0"), 0);
    append_n(301, &last);
    CHECK_EQ_INT(store_log_count(), 300);
    CHECK_EQ_INT(count_files("log0"), 2);
    CHECK(store_test_reboot(300) == ESP_OK);
    CHECK_EQ_INT(read_all(&first, &end), 300);
    CHECK_EQ_INT(end, 1005);
    CHECK_EQ_INT(first, 706);
}

static void corrupt_slot(uint32_t slot, uint32_t seq_value)
{
    char p[512];
    snprintf(p, sizeof(p), "%s/log%03u.bin", DIR_, (unsigned)(slot / SEG_RECS));
    FILE *f = fopen(p, "r+b");
    CHECK(f != NULL);
    if (!f) {
        return;
    }
    uint8_t b[4];
    le_put_u32(b, seq_value);
    fseek(f, (long)((slot % SEG_RECS) * 16), SEEK_SET);
    fwrite(b, 1, 4, f);
    fclose(f);
}

static void test_store_damage(void)
{
    wipe();
    mkdir(DIR_, 0777);
    CHECK(store_test_reboot(600) == ESP_OK);
    uint32_t last = 0, first = 0, end = 0;
    append_n(10, &last);

    /* a slot holding a seq that does not belong there (stale, or a garbage write) is never taken as
     * the newest record, and reads skip it */
    corrupt_slot(4, 0x7FFFFFFFu);
    CHECK(store_test_reboot(600) == ESP_OK);
    CHECK_EQ_INT(store_log_next_seq(), 11);
    CHECK_EQ_INT(read_all_(&first, &end, 0), 9); /* seq 5 skipped */
    CHECK_EQ_INT(end, 10);

    /* the newest slot blank (a write that never committed): the log ends one earlier */
    corrupt_slot(9, 0);
    CHECK(store_test_reboot(600) == ESP_OK);
    CHECK_EQ_INT(store_log_next_seq(), 10);

    /* a missing middle segment: its records are simply absent */
    append_n(600, &last);
    char p[512];
    snprintf(p, sizeof(p), "%s/log001.bin", DIR_);
    unlink(p);
    CHECK(store_test_reboot(600) == ESP_OK);
    CHECK_EQ_INT(store_log_next_seq(), last + 1);
    CHECK_EQ_INT(store_log_count(), 600);
    logrec_t recs[64];
    uint32_t next = 0, total = 0, seq = 0;
    size_t got;
    while ((got = store_log_read(seq, recs, 64, &next)) > 0) {
        total += (uint32_t)got;
        seq = next;
    }
    CHECK_EQ_INT(total, 600 - SEG_RECS);
    append_n(248, &last); /* seq 857 lands in slot 256: the segment comes back when written */
    CHECK_EQ_INT(last, 857);
    CHECK_EQ_INT(file_size("log001.bin"), 16);
    CHECK(store_log_get(857, &recs[0]) && recs[0].seq == 857);

    /* a torn / foreign header: a new log from seq 1 (and no stale segment survives) */
    snprintf(p, sizeof(p), "%s/log.hdr", DIR_);
    FILE *f = fopen(p, "wb");
    fwrite("CLG", 1, 3, f);
    fclose(f);
    CHECK(store_test_reboot(600) == ESP_OK);
    CHECK_EQ_INT(store_log_count(), 0);
    CHECK_EQ_INT(store_log_next_seq(), 1);
    CHECK_EQ_INT(count_files("log0"), 0);

    /* the v1 single file of pre-release builds is removed */
    snprintf(p, sizeof(p), "%s/log.bin", DIR_);
    f = fopen(p, "wb");
    fwrite("x", 1, 1, f);
    fclose(f);
    CHECK(store_test_reboot(600) == ESP_OK);
    CHECK_EQ_INT(file_size("log.bin"), -1);
}

typedef struct {
    char *buf;
    size_t len, cap;
    int calls;
} sink_t;

static esp_err_t sink_write(void *ctx, const char *b, size_t n)
{
    sink_t *s = ctx;
    if (s->len + n + 1 > s->cap) {
        return ESP_FAIL;
    }
    memcpy(s->buf + s->len, b, n);
    s->len += n;
    s->buf[s->len] = '\0';
    s->calls++;
    return ESP_OK;
}

static void test_store_csv(void)
{
    wipe();
    mkdir(DIR_, 0777);
    CHECK(store_test_reboot(600) == ESP_OK);
    uint32_t last = 0;
    append_n(650, &last);
    /* (the split of a batch that does not fit the 1 KiB buffer is covered by test_csv / csv_pack) */
    sink_t s = {.buf = malloc(200000), .cap = 200000};
    CHECK(store_log_export_csv(true, 3, sink_write, &s) == ESP_OK);
    int lines = 0;
    for (size_t i = 0; i < s.len; i++) {
        lines += s.buf[i] == '\n';
    }
    CHECK_EQ_INT(lines, 1 + 600); /* header + every stored record, none dropped */
    CHECK(strncmp(s.buf, "seq,unix_s,utc,value,unit,flags,profile,kind\r\n", 46) == 0);
    CHECK(strstr(s.buf, "\r\n51,") != NULL);  /* the oldest kept (650 - 600 + 1) */
    CHECK(strstr(s.buf, "\r\n50,") == NULL);  /* overwritten */
    CHECK(strstr(s.buf, "\r\n650,") != NULL); /* the newest */
    /* every line is complete: seq, unix_s, utc, value, unit, flags, profile, kind */
    int bad = 0;
    char *line = strstr(s.buf, "\r\n") + 2;
    while (*line) {
        char *eol = strstr(line, "\r\n");
        if (!eol) {
            bad++;
            break;
        }
        int commas = 0;
        for (char *c = line; c < eol; c++) {
            commas += *c == ',';
        }
        bad += commas != 7;
        line = eol + 2;
    }
    CHECK_EQ_INT(bad, 0);
    /* a failing writer stops the export with an error */
    sink_t small = {.buf = malloc(100), .cap = 100};
    CHECK(store_log_export_csv(true, 3, sink_write, &small) != ESP_OK);
    free(s.buf);
    free(small.buf);
    wipe();
}

/* The compass's hard-iron calibration: four u16 keys of 0.1 uT in NVS. */
static void test_store_compass(void)
{
    orient_compass_cal_t c = {{1, 2, 3}, 4};
    CHECK(!store_compass_load(&c)); /* nothing stored */
    CHECK(c.off_ut.x == 0 && c.off_ut.y == 0 && c.off_ut.z == 0 && c.ref_ut == 0); /* = not calibrated */

    /* does not fit, or is not one: refused, and nothing written */
    const orient_compass_cal_t far = {{3300.0f, 0, 0}, 48.0f}, far_neg = {{0, 0, -3276.8f}, 48.0f};
    const orient_compass_cal_t none = {{1, 2, 3}, 0}, neg = {{1, 2, 3}, -48.0f}, big = {{1, 2, 3}, 6553.6f};
    const orient_compass_cal_t nan_off = {{0, NAN, 0}, 48.0f}, nan_ref = {{0, 0, 0}, NAN};
    CHECK_EQ_INT(store_compass_save(&far), ESP_ERR_INVALID_ARG);
    CHECK_EQ_INT(store_compass_save(&far_neg), ESP_ERR_INVALID_ARG);
    CHECK_EQ_INT(store_compass_save(&none), ESP_ERR_INVALID_ARG);
    CHECK_EQ_INT(store_compass_save(&neg), ESP_ERR_INVALID_ARG);
    CHECK_EQ_INT(store_compass_save(&big), ESP_ERR_INVALID_ARG);
    CHECK_EQ_INT(store_compass_save(&nan_off), ESP_ERR_INVALID_ARG);
    CHECK_EQ_INT(store_compass_save(&nan_ref), ESP_ERR_INVALID_ARG);
    CHECK(!store_compass_load(&c));

    /* a round trip, to 0.1 uT, negative offsets and the ends of the range included */
    const orient_compass_cal_t in = {{-12.34f, 250.06f, -3276.7f}, 48.27f};
    CHECK_EQ_INT(store_compass_save(&in), ESP_OK);
    CHECK(store_compass_load(&c));
    CHECK_NEAR(c.off_ut.x, -12.3, 1e-3);
    CHECK_NEAR(c.off_ut.y, 250.1, 1e-3);
    CHECK_NEAR(c.off_ut.z, -3276.7, 1e-3);
    CHECK_NEAR(c.ref_ut, 48.3, 1e-3);
    const orient_compass_cal_t in2 = {{3276.7f, -0.04f, 0.06f}, 6553.5f};
    CHECK_EQ_INT(store_compass_save(&in2), ESP_OK); /* replaces the first */
    CHECK(store_compass_load(&c));
    CHECK_NEAR(c.off_ut.x, 3276.7, 1e-3);
    CHECK_NEAR(c.off_ut.y, 0.0, 1e-6);
    CHECK_NEAR(c.off_ut.z, 0.1, 1e-3);
    CHECK_NEAR(c.ref_ut, 6553.5, 1e-2);
    /* a refused save leaves the stored one alone */
    CHECK_EQ_INT(store_compass_save(&none), ESP_ERR_INVALID_ARG);
    CHECK(store_compass_load(&c));
    CHECK_NEAR(c.ref_ut, 6553.5, 1e-2);
}

int main(void)
{
    printf("store tests (%s)\n", STORE_BASE_PATH);
    RUN(test_store_ring);
    RUN(test_store_damage);
    RUN(test_store_csv);
    RUN(test_store_compass);
    printf("\n%d checks, %d failures\n", tt_checks, tt_failures);
    return tt_failures ? 1 : 0;
}
