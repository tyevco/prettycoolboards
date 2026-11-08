/* Minimal assert harness for the host tests (no external dependency, nothing to download). */
#pragma once

#include <math.h>
#include <stdio.h>
#include <string.h>

extern int tt_failures;
extern int tt_checks;
extern const char *tt_current;

#define CHECK(cond)                                                                                \
    do {                                                                                           \
        tt_checks++;                                                                               \
        if (!(cond)) {                                                                             \
            tt_failures++;                                                                         \
            printf("  FAIL %s:%d [%s] %s\n", __FILE__, __LINE__, tt_current, #cond);               \
        }                                                                                          \
    } while (0)

#define CHECK_EQ_INT(a, b)                                                                         \
    do {                                                                                           \
        long long _a = (long long)(a), _b = (long long)(b);                                        \
        tt_checks++;                                                                               \
        if (_a != _b) {                                                                            \
            tt_failures++;                                                                         \
            printf("  FAIL %s:%d [%s] %s == %s (%lld != %lld)\n", __FILE__, __LINE__, tt_current,  \
                   #a, #b, _a, _b);                                                                \
        }                                                                                          \
    } while (0)

#define CHECK_EQ_STR(a, b)                                                                         \
    do {                                                                                           \
        const char *_a = (a), *_b = (b);                                                           \
        tt_checks++;                                                                               \
        if (strcmp(_a, _b) != 0) {                                                                 \
            tt_failures++;                                                                         \
            printf("  FAIL %s:%d [%s] \"%s\" != \"%s\"\n", __FILE__, __LINE__, tt_current, _a, _b); \
        }                                                                                          \
    } while (0)

#define CHECK_NEAR(a, b, tol)                                                                      \
    do {                                                                                           \
        double _a = (double)(a), _b = (double)(b);                                                 \
        tt_checks++;                                                                               \
        if (fabs(_a - _b) > (tol)) {                                                               \
            tt_failures++;                                                                         \
            printf("  FAIL %s:%d [%s] %s ~ %s (%.9g vs %.9g)\n", __FILE__, __LINE__, tt_current,   \
                   #a, #b, _a, _b);                                                                \
        }                                                                                          \
    } while (0)

#define RUN(fn)                                                                                    \
    do {                                                                                           \
        int _before = tt_failures;                                                                 \
        tt_current = #fn;                                                                          \
        fn();                                                                                      \
        printf("%s %s\n", tt_failures == _before ? "PASS" : "FAIL", #fn);                         \
    } while (0)
