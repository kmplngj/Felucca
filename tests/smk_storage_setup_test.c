/* SPDX-License-Identifier: GPL-3.0-only */
#include <stdio.h>
#include <stdlib.h>
#include "../firmware/src/smk_storage_setup.h"
#define BANKS 3u
#define DOWN 16u
#define UP 32u
static void check(int ok, const char *why) { if (!ok) { fprintf(stderr, "FAIL: %s\n", why); exit(1); } }
int main(void)
{
    smk_setup_t s = {0};
    uint32_t n;
    check(smk_setup_step(&s, 1, BANKS | UP, BANKS, DOWN, UP) == SMK_SETUP_WAIT && !s.armed,
          "held boot combo and OCT+ cannot confirm");
    check(smk_setup_step(&s, 2, UP, BANKS, DOWN, UP) == SMK_SETUP_WAIT && !s.armed,
          "OCT+ must also release before arming");
    check(smk_setup_step(&s, 3, 0, BANKS, DOWN, UP) == SMK_SETUP_WAIT && s.armed, "all controls released arms");
    check(smk_setup_step(&s, 4, BANKS | UP, BANKS, DOWN, UP) == SMK_SETUP_WAIT, "banks held block confirmation");
    check(smk_setup_step(&s, 5, UP, BANKS, DOWN, UP) == SMK_SETUP_WAIT, "held OCT+ cannot confirm by bank release");
    smk_setup_step(&s, 6, 0, BANKS, DOWN, UP);
    check(smk_setup_step(&s, 7, UP, BANKS, DOWN, UP) == SMK_SETUP_CONFIRM, "fresh OCT+ confirms");
    s = (smk_setup_t){0}; smk_setup_step(&s, 1, 0, BANKS, DOWN, UP);
    check(smk_setup_step(&s, 2, DOWN | UP, BANKS, DOWN, UP) == SMK_SETUP_CANCEL, "OCT- wins over confirm");
    s = (smk_setup_t){0};
    for (n = 0; n < SMK_SETUP_TIMEOUT_MS; n++)
        check(smk_setup_step(&s, n, BANKS | UP, BANKS, DOWN, UP) == SMK_SETUP_WAIT,
              "waiting returns every poll for watchdog/input service");
    check(smk_setup_step(&s, n, 0, BANKS, DOWN, UP) == SMK_SETUP_TIMEOUT, "held controls time out");
    s = (smk_setup_t){.started = 0xFFFFFFF0u};
    check(smk_setup_step(&s, 0xFFFFFFF0u + SMK_SETUP_TIMEOUT_MS, 0, BANKS, DOWN, UP) == SMK_SETUP_TIMEOUT,
          "deadline subtraction survives clock wrap");
    puts("SMK storage confirmation release/edge/cancel/timeout contracts passed");
    return 0;
}
