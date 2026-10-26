/* SPDX-License-Identifier: GPL-3.0-only */
/* Reuse the existing console fixture. Kernel/state contracts have their own test;
 * these canned samples isolate actual command grammar, output and disabled dispatch. */
#include <stdint.h>
#if FELUCCA_CHIP_PROBES
#define CP_KINDS 9u
#define CP_PASSES 2u
static struct { uint32_t ticks, checksum, reference; } cp_result[18];
static uint32_t fixture_rc, cp_done;
static uint32_t cp_run(void) { cp_done = fixture_rc == 4u ? 5u : 0u; return fixture_rc; }
#endif
#define main diagnostics_fixture_main
#include "console_diagnostics.c"
#undef main
int main(int argc, char **argv)
{
    size_t n;
    if (argc < 2 || argc > 3) return 2;
#if FELUCCA_CHIP_PROBES
    if (argc == 3) fixture_rc = (uint32_t)atoi(argv[2]);
#endif
    n = strlen(argv[1]);
    if (n + 1u > CI_N) return 2;
    memcpy(cdc_in, argv[1], n); cdc_in[n] = '\r'; ci_w = (uint32_t)n + 1u;
    con.dtr_seen = 1;
    cdc_task();
    if (con.stalled || co_w >= CO_N) return 2;
    return fwrite(cdc_out, 1, co_w, stdout) == co_w ? 0 : 2;
}
