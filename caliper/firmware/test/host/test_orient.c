/*
 * Host tests for components/measure/orient.c: the orientation filter behind the LSM6DSO driver
 * (components/power/imu.c). Synthetic motion only: a body turning about one board axis at a known
 * rate, with the accelerometer reading the gravity direction that turn produces.
 */
#include <math.h>
#include <stdint.h>
#include <string.h>

#include "orient.h"
#include "tiny_test.h"

#define DT_US 19231u /* 52 Hz, the driver's output data rate */
#define D2R   0.01745329252f

static orient_vec_t vec(float x, float y, float z)
{
    orient_vec_t v = {x, y, z};
    return v;
}

static void feed(orient_t *o, orient_vec_t gyro, orient_vec_t acc, int n)
{
    for (int i = 0; i < n; i++) {
        orient_update(o, gyro, acc, DT_US, false);
    }
}

/* Turns about board +x at `dps` for n samples starting from display up; the accelerometer reads
 * the true gravity direction times acc_scale (1 = trusted, 1.5 = outside the gate: gyro only). */
static void turn_x(orient_t *o, float dps, int n, float acc_scale)
{
    for (int i = 1; i <= n; i++) {
        float phi = dps * (float)i * (float)DT_US * 1e-6f * D2R;
        orient_update(o, vec(dps, 0, 0), vec(0, acc_scale * sinf(phi), acc_scale * cosf(phi)), DT_US, false);
    }
}

static void test_orient_mount(void)
{
    const orient_mount_t id = {{{1, 0, 0}, {0, 1, 0}, {0, 0, 1}}};
    CHECK(orient_mount_valid(&id));
    orient_vec_t v = orient_mount_apply(&id, vec(1, 2, 3));
    CHECK_NEAR(v.x, 1, 1e-6);
    CHECK_NEAR(v.y, 2, 1e-6);
    CHECK_NEAR(v.z, 3, 1e-6);

    /* the chip turned 90 deg about z: chip x along board +y, chip y along board -x */
    const orient_mount_t rot90 = {{{0, -1, 0}, {1, 0, 0}, {0, 0, 1}}};
    CHECK(orient_mount_valid(&rot90));
    v = orient_mount_apply(&rot90, vec(1, 2, 3));
    CHECK_NEAR(v.x, -2, 1e-6);
    CHECK_NEAR(v.y, 1, 1e-6);
    CHECK_NEAR(v.z, 3, 1e-6);

    /* bottom side: turned over about x (y and z both flip): still a rotation */
    const orient_mount_t bottom = {{{1, 0, 0}, {0, -1, 0}, {0, 0, -1}}};
    CHECK(orient_mount_valid(&bottom));

    const orient_mount_t mirror = {{{1, 0, 0}, {0, 1, 0}, {0, 0, -1}}}; /* det -1 */
    CHECK(!orient_mount_valid(&mirror));
    const orient_mount_t swapped = {{{0, 1, 0}, {1, 0, 0}, {0, 0, 1}}}; /* det -1 */
    CHECK(!orient_mount_valid(&swapped));
    const orient_mount_t twice = {{{1, 0, 0}, {1, 0, 0}, {0, 0, 1}}}; /* chip x used twice */
    CHECK(!orient_mount_valid(&twice));
    const orient_mount_t scaled = {{{2, 0, 0}, {0, 1, 0}, {0, 0, 1}}};
    CHECK(!orient_mount_valid(&scaled));
    const orient_mount_t zero = {{{0, 0, 0}, {0, 0, 0}, {0, 0, 0}}};
    CHECK(!orient_mount_valid(&zero));
}

static void test_orient_gravity(void)
{
    orient_t o;
    orient_out_t out;
    orient_init(&o, NULL);
    orient_get(&o, &out);
    CHECK(!out.valid);
    CHECK_EQ_INT(out.face, ORIENT_FACE_TILTED);
    CHECK_NEAR(out.yaw_unc_deg, 180, 1e-3);

    /* no gravity yet (free fall, or a dead accelerometer): nothing becomes valid, nothing is NaN */
    feed(&o, vec(0, 0, 0), vec(0, 0, 0), 5);
    orient_get(&o, &out);
    CHECK(!out.valid);
    CHECK(out.roll_deg == out.roll_deg && out.pitch_deg == out.pitch_deg);
    feed(&o, vec(0, 0, 0), vec(0, 0, 1.4f), 5); /* 1.4 g is not gravity either */
    orient_get(&o, &out);
    CHECK(!out.valid);

    static const struct {
        float x, y, z, roll, pitch, tilt;
        orient_face_t face;
    } c[] = {
        {0, 0, 1, 0, 0, 0, ORIENT_FACE_DISPLAY_UP},
        {0, 1, 0, 90, 0, 90, ORIENT_FACE_TOP_UP},
        {0, -1, 0, -90, 0, 90, ORIENT_FACE_TOP_DOWN},
        {1, 0, 0, 0, 90, 90, ORIENT_FACE_USB_UP},
        {-1, 0, 0, 0, -90, 90, ORIENT_FACE_USB_DOWN},
        {0, 0.5f, 0.8660254f, 30, 0, 30, ORIENT_FACE_DISPLAY_UP},
        {0.5f, 0, 0.8660254f, 0, 30, 30, ORIENT_FACE_DISPLAY_UP},
        {0, 0.70710678f, 0.70710678f, 45, 0, 45, ORIENT_FACE_TILTED},
    };
    for (size_t i = 0; i < sizeof(c) / sizeof(c[0]); i++) {
        orient_init(&o, NULL);
        orient_update(&o, vec(0, 0, 0), vec(c[i].x, c[i].y, c[i].z), DT_US, false);
        orient_get(&o, &out);
        CHECK(out.valid);
        CHECK_NEAR(out.pitch_deg, c[i].pitch, 0.01);
        CHECK_NEAR(out.tilt_deg, c[i].tilt, 0.01);
        if (fabsf(c[i].pitch) < 89.0f) { /* roll means nothing with the beam vertical */
            CHECK_NEAR(out.roll_deg, c[i].roll, 0.01);
        }
        CHECK_EQ_INT(out.face, c[i].face);
        CHECK_NEAR(out.yaw_deg, 0, 1e-6); /* yaw starts at the first gravity reference */
        CHECK_NEAR(out.yaw_unc_deg, 0, 0.1);
    }

    /* display down: roll is +-180 */
    orient_init(&o, NULL);
    orient_update(&o, vec(0, 0, 0), vec(0, 0, -1), DT_US, false);
    orient_get(&o, &out);
    CHECK_NEAR(fabsf(out.roll_deg), 180, 0.01);
    CHECK_NEAR(out.tilt_deg, 180, 0.01);
    CHECK_EQ_INT(out.face, ORIENT_FACE_DISPLAY_DOWN);

    /* a part with a 6 % sensitivity error still gives the direction */
    orient_init(&o, NULL);
    orient_update(&o, vec(0, 0, 0), vec(0, 1.06f, 0), DT_US, false);
    orient_get(&o, &out);
    CHECK_NEAR(out.roll_deg, 90, 0.01);
    CHECK_NEAR(out.acc_abs_g, 1.06, 1e-4);

    CHECK_EQ_STR(orient_face_name(ORIENT_FACE_TOP_DOWN), "top edge down");
    CHECK_EQ_STR(orient_face_name(ORIENT_FACE_TILTED), "tilted");
}

static void test_orient_gyro(void)
{
    orient_t o;
    orient_out_t out;

    /* gyro and accelerometer agree: a quarter turn about the beam in 0.5 s */
    orient_init(&o, NULL);
    orient_update(&o, vec(0, 0, 0), vec(0, 0, 1), DT_US, false);
    turn_x(&o, 180, 26, 1.0f);
    orient_get(&o, &out);
    CHECK_NEAR(out.roll_deg, 90, 0.2);
    CHECK_NEAR(out.rate_dps.x, 180, 1e-3);
    CHECK_NEAR(out.rate_abs_dps, 180, 1e-3);
    CHECK(!out.steady);
    CHECK(!out.at_rest);

    /* the accelerometer outside the gate (1.5 g: a shake): the gyro alone carries it */
    orient_init(&o, NULL);
    orient_update(&o, vec(0, 0, 0), vec(0, 0, 1), DT_US, false);
    turn_x(&o, 180, 26, 1.5f);
    orient_get(&o, &out);
    CHECK_NEAR(out.roll_deg, 90, 0.2);
    CHECK_NEAR(out.up.y, 1, 1e-3);
    CHECK_EQ_INT(out.face, ORIENT_FACE_TOP_UP);
    /* 500 dps for 1.44 s (two full turns, 9.6 deg per sample): exact integration, no creep */
    orient_init(&o, NULL);
    orient_update(&o, vec(0, 0, 0), vec(0, 0, 1), DT_US, false);
    turn_x(&o, 500, 75, 1.5f); /* 75 x 19.231 ms x 500 dps = 721.2 deg */
    orient_get(&o, &out);
    CHECK_NEAR(out.roll_deg, 1.16, 0.3);
    CHECK_NEAR(out.up.x * out.up.x + out.up.y * out.up.y + out.up.z * out.up.z, 1, 1e-4);

    /* sign of pitch: a right-handed turn about board +y lowers the USB end */
    orient_init(&o, NULL);
    orient_update(&o, vec(0, 0, 0), vec(0, 0, 1), DT_US, false);
    feed(&o, vec(0, 90, 0), vec(0, 0, 1.5f), 26);
    orient_get(&o, &out);
    CHECK_NEAR(out.pitch_deg, -45, 0.2);
    CHECK_NEAR(out.roll_deg, 0, 0.01);

    /* the gyro says nothing moved, the accelerometer says 20 deg of roll: converges with tau 0.5 s */
    orient_init(&o, NULL);
    orient_update(&o, vec(0, 0, 0), vec(0, 0, 1), DT_US, false);
    const orient_vec_t a20 = vec(0, sinf(20 * D2R), cosf(20 * D2R));
    feed(&o, vec(0, 0, 0), a20, 26); /* 0.5 s = one time constant: about 63 % */
    orient_get(&o, &out);
    CHECK(out.roll_deg > 10 && out.roll_deg < 15);
    feed(&o, vec(0, 0, 0), a20, 130); /* 3 s in all */
    orient_get(&o, &out);
    CHECK_NEAR(out.roll_deg, 20, 0.2);

    /* a custom time constant is honoured */
    orient_cfg_t cfg;
    orient_cfg_default(&cfg);
    cfg.tau_s = 0.05f;
    orient_init(&o, &cfg);
    orient_update(&o, vec(0, 0, 0), vec(0, 0, 1), DT_US, false);
    feed(&o, vec(0, 0, 0), a20, 26);
    orient_get(&o, &out);
    CHECK_NEAR(out.roll_deg, 20, 0.1);
}

static void test_orient_yaw(void)
{
    orient_t o;
    orient_out_t out;

    /* flat, turning counter-clockwise seen from above at 90 dps: a constant rate is NOT a bias */
    orient_init(&o, NULL);
    orient_update(&o, vec(0, 0, 0), vec(0, 0, 1), DT_US, false);
    feed(&o, vec(0, 0, 90), vec(0, 0, 1), 52); /* 1.000 s */
    orient_get(&o, &out);
    CHECK_NEAR(out.yaw_deg, 90, 0.1);
    CHECK_NEAR(out.yaw_unc_deg, 1.0, 0.05); /* 1 dps of uncertainty without a bias estimate */
    CHECK(!out.bias_valid);
    CHECK(!out.at_rest);
    CHECK_NEAR(out.roll_deg, 0, 0.01);
    CHECK_NEAR(out.pitch_deg, 0, 0.01);
    feed(&o, vec(0, 0, 90), vec(0, 0, 1), 78); /* 2.5 s in all: 225 deg wraps to -135 */
    orient_get(&o, &out);
    CHECK_NEAR(out.yaw_deg, -135, 0.2);
    CHECK(!out.bias_valid);

    orient_zero_yaw(&o);
    orient_get(&o, &out);
    CHECK_NEAR(out.yaw_deg, 0, 1e-6);
    CHECK_NEAR(out.yaw_unc_deg, 0, 1e-6);
    feed(&o, vec(0, 0, -90), vec(0, 0, 1), 26); /* clockwise */
    orient_get(&o, &out);
    CHECK_NEAR(out.yaw_deg, -45, 0.1);

    /* display down: the same turn of the board about its +z is clockwise seen from above */
    orient_init(&o, NULL);
    orient_update(&o, vec(0, 0, 0), vec(0, 0, -1), DT_US, false);
    feed(&o, vec(0, 0, 90), vec(0, 0, -1), 52);
    orient_get(&o, &out);
    CHECK_NEAR(out.yaw_deg, -90, 0.1);

    /* standing on the jaws' edge (top edge up): the vertical is board +y */
    orient_init(&o, NULL);
    orient_update(&o, vec(0, 0, 0), vec(0, 1, 0), DT_US, false);
    feed(&o, vec(0, 60, 0), vec(0, 1, 0), 52);
    orient_get(&o, &out);
    CHECK_NEAR(out.yaw_deg, 60, 0.1);
    CHECK_NEAR(out.roll_deg, 90, 0.01);
    /* ... and a turn about the beam there is roll, not yaw */
    orient_zero_yaw(&o);
    feed(&o, vec(20, 0, 0), vec(0, 1, 0), 5);
    orient_get(&o, &out);
    CHECK(fabsf(out.yaw_deg) < 0.2f);

    /* a clipped gyro sample or a gap in the samples voids the yaw, not the tilt */
    orient_init(&o, NULL);
    orient_update(&o, vec(0, 0, 0), vec(0, 0, 1), DT_US, false);
    feed(&o, vec(0, 0, 10), vec(0, 0, 1), 10);
    orient_get(&o, &out);
    CHECK(out.yaw_unc_deg < 1.0f);
    orient_update(&o, vec(0, 0, 1000), vec(0, 0, 1), DT_US, true);
    orient_get(&o, &out);
    CHECK_NEAR(out.yaw_unc_deg, 180, 1e-3);
    CHECK(out.valid);
    CHECK_NEAR(out.tilt_deg, 0, 0.01);
    orient_zero_yaw(&o);
    orient_update(&o, vec(0, 0, 0), vec(0, 0, 1), 500000, false); /* half a second without a sample */
    orient_get(&o, &out);
    CHECK_NEAR(out.yaw_unc_deg, 180, 1e-3);
    orient_zero_yaw(&o);
    orient_update(&o, vec(0, 0, 0), vec(0, 0, 1), ORIENT_DT_MAX_US, false); /* the limit itself is fine */
    orient_get(&o, &out);
    CHECK(out.yaw_unc_deg < 1.0f);

    /* the uncertainty saturates at 180 (unknown) */
    orient_init(&o, NULL);
    orient_update(&o, vec(0, 0, 0), vec(0, 0, 1), DT_US, false);
    feed(&o, vec(0, 0, 30), vec(0, 0, 1), 52 * 200);
    orient_get(&o, &out);
    CHECK_NEAR(out.yaw_unc_deg, 180, 1e-3);
    CHECK(out.yaw_deg >= -180.0f && out.yaw_deg <= 180.0f);
}

static void test_orient_rest(void)
{
    orient_t o;
    orient_out_t out;
    const orient_vec_t bias = vec(0.5f, -0.3f, 0.8f), flat = vec(0, 0, 1);

    orient_init(&o, NULL);
    feed(&o, bias, flat, 10); /* 192 ms */
    orient_get(&o, &out);
    CHECK(out.valid);
    CHECK(!out.steady);
    CHECK(!out.at_rest);
    CHECK(!out.bias_valid);
    CHECK_NEAR(out.rate_dps.z, 0.8, 1e-4); /* uncorrected so far */
    feed(&o, bias, flat, 10); /* 385 ms: steady needs 300 ms */
    orient_get(&o, &out);
    CHECK(out.steady);
    CHECK(!out.at_rest);
    feed(&o, bias, flat, 34); /* 1.04 s: the first rest window closed */
    orient_get(&o, &out);
    CHECK(out.at_rest);
    CHECK(out.bias_valid);
    CHECK_NEAR(out.bias_dps.x, 0.5, 1e-4);
    CHECK_NEAR(out.bias_dps.y, -0.3, 1e-4);
    CHECK_NEAR(out.bias_dps.z, 0.8, 1e-4);
    CHECK_NEAR(out.rate_abs_dps, 0, 1e-3);
    float yaw_1s = out.yaw_deg;
    CHECK(yaw_1s > 0.6f && yaw_1s < 1.0f); /* 0.8 dps drifted for the first second ... */
    feed(&o, bias, flat, 53 * 9 - 1); /* 530 samples in all: ten whole windows of 53 */
    orient_get(&o, &out);
    CHECK_NEAR(out.yaw_deg, yaw_1s, 0.01); /* ... and not at all once the bias is known */
    CHECK(out.yaw_unc_deg >= fabsf(out.yaw_deg)); /* the uncertainty covers the drift */
    CHECK(out.yaw_unc_deg < 2.0f);                /* 1 dps x 1 s + 0.05 dps x 9 s */
    CHECK_NEAR(out.roll_deg, 0, 0.01);

    /* the bias moved (temperature): the next quiet windows follow with weight 0.25 each */
    const orient_vec_t bias2 = vec(0.5f, -0.3f, 0.9f);
    feed(&o, bias2, flat, 53);
    orient_get(&o, &out);
    CHECK(out.at_rest);
    CHECK_NEAR(out.bias_dps.z, 0.825, 2e-3);
    feed(&o, bias2, flat, 53 * 20);
    orient_get(&o, &out);
    CHECK_NEAR(out.bias_dps.z, 0.9, 5e-3);

    /* picked up: rest and steady drop at once, the bias stays */
    orient_update(&o, vec(40, 0, 0), flat, DT_US, false);
    orient_get(&o, &out);
    CHECK(!out.at_rest);
    CHECK(!out.steady);
    CHECK(out.bias_valid);
    CHECK_NEAR(out.rate_dps.x, 39.5, 1e-3);

    /* held in a hand: +-2 dps of tremor is steady, but it is not rest and teaches no bias */
    orient_init(&o, NULL);
    for (int i = 0; i < 52 * 3; i++) {
        float t = (i & 1) ? 2.0f : -2.0f;
        orient_update(&o, vec(t, -t, t), flat, DT_US, false);
    }
    orient_get(&o, &out);
    CHECK(out.steady);
    CHECK(!out.at_rest);
    CHECK(!out.bias_valid);

    /* a quiet gyro on a moving accelerometer (a slide along the bench) is not rest either */
    orient_init(&o, NULL);
    for (int i = 0; i < 52 * 3; i++) {
        orient_update(&o, vec(0, 0, 0), vec((i & 1) ? 0.03f : -0.03f, 0, 1), DT_US, false);
    }
    orient_get(&o, &out);
    CHECK(!out.at_rest);
    CHECK(!out.bias_valid);

    /* a slow steady turn about the vertical looks exactly like a bias; above bias_max it is refused */
    orient_init(&o, NULL);
    feed(&o, vec(0, 0, 8), flat, 52 * 3);
    orient_get(&o, &out);
    CHECK(!out.at_rest);
    CHECK(!out.bias_valid);
    CHECK_NEAR(out.yaw_deg, 24, 0.5);

    /* steady needs 1 g: a quiet gyro in a 1.1 g swing is not steady */
    orient_init(&o, NULL);
    feed(&o, vec(0, 0, 0), flat, 5);
    feed(&o, vec(0, 0, 0), vec(0, 0, 1.1f), 52);
    orient_get(&o, &out);
    CHECK(!out.steady);
    /* ... nor is a turn above steady_dps */
    orient_init(&o, NULL);
    feed(&o, vec(0, 0, 7), flat, 52);
    orient_get(&o, &out);
    CHECK(!out.steady);
    feed(&o, vec(0, 0, 5), flat, 52);
    orient_get(&o, &out);
    CHECK(out.steady);
}

static void test_orient_recover(void)
{
    orient_t o;
    orient_out_t out;

    /* tracking lost (the estimate and gravity more than 90 deg apart): restart from gravity */
    orient_init(&o, NULL);
    orient_update(&o, vec(0, 0, 0), vec(0, 0, 1), DT_US, false);
    orient_update(&o, vec(0, 0, 0), vec(0, 0, -1), DT_US, false);
    orient_get(&o, &out);
    CHECK_EQ_INT(out.face, ORIENT_FACE_DISPLAY_DOWN);
    CHECK_NEAR(out.tilt_deg, 180, 0.01);

    /* zero dt and zero vectors never produce NaN or a non-unit `up` */
    orient_update(&o, vec(0, 0, 0), vec(0, 0, 0), 0, false);
    orient_update(&o, vec(300, -200, 100), vec(0, 0, 0), DT_US, false);
    orient_update(&o, vec(0, 0, 0), vec(0, 0, -1), 0, false);
    orient_get(&o, &out);
    CHECK(out.roll_deg == out.roll_deg && out.pitch_deg == out.pitch_deg && out.yaw_deg == out.yaw_deg);
    CHECK_NEAR(out.up.x * out.up.x + out.up.y * out.up.y + out.up.z * out.up.z, 1, 1e-4);

    /* a long tumble on the gyro alone, then gravity again: back within a few time constants */
    orient_init(&o, NULL);
    orient_update(&o, vec(0, 0, 0), vec(0, 0, 1), DT_US, false);
    feed(&o, vec(137, -211, 59), vec(0.2f, 0.1f, 0.3f), 200); /* thrown: 0.37 g, not gravity */
    feed(&o, vec(0, 0, 0), vec(0, 1, 0), 156);                /* caught, top edge up, 3 s */
    orient_get(&o, &out);
    CHECK_NEAR(out.roll_deg, 90, 0.5);
    CHECK_NEAR(out.pitch_deg, 0, 0.5);
    CHECK_EQ_INT(out.face, ORIENT_FACE_TOP_UP);
}

static void test_orient_flip(void)
{
    orient_flip_t f = {0};
    orient_out_t o;
    memset(&o, 0, sizeof(o));
    o.valid = true;

    o.up = vec(0, -1, 0); /* top edge down */
    for (int i = 0; i < 5; i++) {
        CHECK(!orient_flip_update(&f, &o, 100));
    }
    CHECK(!f.flipped); /* 500 ms: not yet */
    CHECK(orient_flip_update(&f, &o, 100));
    CHECK(f.flipped);
    CHECK(!orient_flip_update(&f, &o, 100));

    /* lying flat, standing on end, or only a little past level: keeps the last state */
    o.up = vec(0, 0, 1);
    for (int i = 0; i < 50; i++) {
        CHECK(!orient_flip_update(&f, &o, 100));
    }
    o.up = vec(1, 0, 0);
    for (int i = 0; i < 50; i++) {
        CHECK(!orient_flip_update(&f, &o, 100));
    }
    o.up = vec(0, 0.2f, 0.98f);
    for (int i = 0; i < 50; i++) {
        CHECK(!orient_flip_update(&f, &o, 100));
    }
    CHECK(f.flipped);

    /* a swing through the other side shorter than the hold does nothing, and restarts the count */
    o.up = vec(0, 0.5f, 0.866f);
    for (int i = 0; i < 5; i++) {
        CHECK(!orient_flip_update(&f, &o, 100));
    }
    o.up = vec(0, -0.5f, 0.866f);
    CHECK(!orient_flip_update(&f, &o, 100));
    o.up = vec(0, 0.5f, 0.866f);
    for (int i = 0; i < 5; i++) {
        CHECK(!orient_flip_update(&f, &o, 100));
    }
    CHECK(f.flipped);
    CHECK(orient_flip_update(&f, &o, 100));
    CHECK(!f.flipped);

    /* no gravity reference: nothing changes */
    o.valid = false;
    o.up = vec(0, -1, 0);
    for (int i = 0; i < 50; i++) {
        CHECK(!orient_flip_update(&f, &o, 100));
    }
    CHECK(!f.flipped);

    /* end to end: turn the caliper over about the beam and the flip follows the filter */
    orient_t flt;
    orient_flip_t g = {0};
    orient_init(&flt, NULL);
    orient_update(&flt, vec(0, 0, 0), vec(0, 1, 0), DT_US, false); /* top edge up */
    int changes = 0;
    for (int i = 1; i <= 52 * 3; i++) {
        /* 180 deg about x in 1 s, then held */
        float phi = (i <= 52 ? (float)i * 180.0f / 52.0f : 180.0f) * D2R;
        orient_update(&flt, vec(i <= 52 ? 180.0f : 0.0f, 0, 0), vec(0, cosf(phi), -sinf(phi)), DT_US, false);
        orient_get(&flt, &o);
        changes += orient_flip_update(&g, &o, 19);
    }
    CHECK(g.flipped);
    CHECK_EQ_INT(changes, 1);
    CHECK_EQ_INT(o.face, ORIENT_FACE_TOP_DOWN);
}

void orient_tests(void)
{
    RUN(test_orient_mount);
    RUN(test_orient_gravity);
    RUN(test_orient_gyro);
    RUN(test_orient_yaw);
    RUN(test_orient_rest);
    RUN(test_orient_recover);
    RUN(test_orient_flip);
}
