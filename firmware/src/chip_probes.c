/* SPDX-License-Identifier: GPL-3.0-only */
/* Bounded developer probes, adapted from Joakim Eriksson's fm1-dock
 * probes/{cycles.c,cache.c,probe.h} at e177e83e560483f419baad80511d9dd1acfdeffe.
 * The cache traversal retains ca_time's offset/sum loop; storage is owned,
 * IRQs remain enabled, and raw timings are never overhead-subtracted.
 * Main-loop only. Nothing starts from boot, playback or the idle service. */
#if FELUCCA_CHIP_PROBES
#define CP_WORDS 256u
#define CP_REPS 256u
#define CP_PASSES 2u
#define CP_KINDS 9u
#define CP_LIMIT 2400000u          /* raw TIMER4 deadline; checked between finite kernels */
#define CP_VALUE(i) ((uint32_t)(i) * 0x9E3779B9u + 0x01234567u)
#define CP_ROW(i) CP_VALUE(i), CP_VALUE(i+1u), CP_VALUE(i+2u), CP_VALUE(i+3u), \
                  CP_VALUE(i+4u), CP_VALUE(i+5u), CP_VALUE(i+6u), CP_VALUE(i+7u), \
                  CP_VALUE(i+8u), CP_VALUE(i+9u), CP_VALUE(i+10u), CP_VALUE(i+11u), \
                  CP_VALUE(i+12u), CP_VALUE(i+13u), CP_VALUE(i+14u), CP_VALUE(i+15u)
static const uint32_t cp_xip[CP_WORDS] = {
    CP_ROW(0u), CP_ROW(16u), CP_ROW(32u), CP_ROW(48u), CP_ROW(64u), CP_ROW(80u), CP_ROW(96u), CP_ROW(112u),
    CP_ROW(128u), CP_ROW(144u), CP_ROW(160u), CP_ROW(176u), CP_ROW(192u), CP_ROW(208u), CP_ROW(224u), CP_ROW(240u)
};
#undef CP_ROW
static uint32_t cp_ram[CP_WORDS];
static struct {
    uint32_t ticks, checksum, reference;
} cp_result[CP_KINDS * CP_PASSES];
static uint32_t cp_done;

static int cp_quiet(void)
{
    uint32_t p, v;
    if (song.playing || fm1_in.notes || fm1_in.buttons || mi_w != mi_r || usb.uboot_req)
        return 0;
#if FELUCCA_UAC
    if (uac.alt) return 0;
#endif
#if FELUCCA_CPU2
    /* Refuse the worker; never halt/restart it or take its mailbox. */
    if (fm1_c1_on) return 0;
#endif
#if FELUCCA_OTA
    if (sx_busy || sx_ready || sx_collect) return 0;
#endif
#if FELUCCA_SCREEN_CAPTURE
    if (scap_live()) return 0;
#endif
    for (p = 0; p < NPART; p++)
        for (v = 0; v < NVOICE; v++)
            if (trk[p].v[v].active) return 0;
    return 1;
}

/* Separate noinline kernels keep their actual target loops visible in disassembly.
 * Include loop/control work in raw ticks; these are not per-instruction costs. */
static __attribute__((noinline)) uint32_t cp_control(void)
{
    uint32_t i;
    for (i = 0; i < CP_REPS; i++) fm1_probe_barrier();
    return CP_REPS;
}
static __attribute__((noinline)) uint32_t cp_integer(void)
{
    uint32_t i, a = 12345u, b = 679u;
    for (i = 0; i < CP_REPS; i++) {
        a = fm1_probe_mul(a + i, b);
        a = fm1_probe_div(a, b | 1u) ^ 0xA5A5A5A5u;
        fm1_probe_barrier();
    }
    return a;
}
static __attribute__((noinline)) uint32_t cp_load(const volatile uint32_t *x, uint32_t stride)
{
    uint32_t i, o = 0, sum = 0;
    for (i = 0; i < CP_REPS; i++) {
        sum += x[o];
        o += stride;
        if (o >= CP_WORDS) o = 0;
    }
    return sum;
}
static uint32_t cp_stride(uint32_t kind)
{
    uint32_t n = (kind - 3u) % 3u;
    return n == 0u ? 1u : n == 1u ? 8u : 32u;
}
static uint32_t cp_reference(uint32_t kind)
{
    uint32_t i, a = 12345u, o = 0, sum = 0;
    uint32_t stride = kind >= 3u ? cp_stride(kind) : 0u;
    if (kind == 0u) return 0u;
    if (kind == 1u) return CP_REPS;
    if (kind == 2u) {
        for (i = 0; i < CP_REPS; i++) a = ((a + i) * 679u) / 679u ^ 0xA5A5A5A5u;
        return a;
    }
    for (i = 0; i < CP_REPS; i++) {
        sum += CP_VALUE(o);
        o = (o + stride) % CP_WORDS;
    }
    return sum;
}
/* Return code: 0 complete, 1 unsupported timer/build, 2 busy/changed, 3 deadline,
 * 4 reference mismatch. Partial samples never become a complete result. */
static uint32_t cp_run(void)
{
    uint32_t i, kind, pass, start, t0, t1, sum, reference, stride;
    cp_done = 0;
    if (!fm1_probe_ready() || FS != 44100u || HALF_FRAMES != 128u) return 1;
    if (!cp_quiet()) return 2;
    start = fm1_ticks();
    for (i = 0; i < CP_WORDS; i++) cp_ram[i] = cp_xip[i];
    for (kind = 0; kind < CP_KINDS; kind++) {
        reference = cp_reference(kind);
        stride = kind >= 3u ? cp_stride(kind) : 0u;
        for (pass = 0; pass < CP_PASSES; pass++) {
            if (!cp_quiet()) return 2;
            if ((uint32_t)(fm1_ticks() - start) >= CP_LIMIT) return 3;
            fm1_wdt_feed();
            fm1_probe_barrier();
            t0 = fm1_ticks();
            if (kind == 0u) sum = 0;                /* timer pair + dispatch, no kernel */
            else if (kind == 1u) sum = cp_control();
            else if (kind == 2u) sum = cp_integer();
            else sum = cp_load(kind < 6u ? cp_xip : cp_ram, stride);
            fm1_probe_barrier();
            t1 = fm1_ticks();
            i = kind * CP_PASSES + pass;
            cp_result[i].ticks = t1 - t0;           /* uint32 wrap, no scaling/subtraction */
            cp_result[i].checksum = sum;
            cp_result[i].reference = reference;
            cp_done = i + 1u;
            if (!cp_quiet()) return 2;
            if ((uint32_t)(t1 - start) >= CP_LIMIT) return 3;
            if (sum != reference) return 4;
        }
    }
    return 0;
}
#endif
