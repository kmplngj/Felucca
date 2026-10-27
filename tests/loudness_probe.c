/* SPDX-License-Identifier: GPL-3.0-only */
/* Role-render harness adapted from Optimist tests/preset_level.c and drum_level.c,
 * commit 2ab989d5a2012160d6488bf56f23d89000d9f855. Native hostsim/DSP retain
 * Copyright (C) 2026 Leo Kuroshita (@kurogedelic), Hügelton Instruments.
 * Audit only: no trim tables, attenuate/rescale trick, or firmware hooks. */
#define main hostsim_main
#include "hostsim.c"
#undef main
#include <errno.h>
#include <limits.h>

typedef struct { uint32_t frame, note, velocity; } audit_event;
typedef struct { int32_t l, r, le, re, env; } audit_state;
static audit_state state_get(void)
{
    audit_state s = {dc_l, dc_r, dce_l, dce_r, lim_env};
    return s;
}
static void state_set(audit_state s)
{
    dc_l = s.l; dc_r = s.r; dce_l = s.le; dce_r = s.re; lim_env = s.env;
}
static int number(const char *s, uint32_t *v)
{
    char *end;
    unsigned long n;
    if (!s[0] || s[0] == '-' || s[0] == '+') return 0;
    errno = 0; n = strtoul(s, &end, 10);
    if (errno || *end || n > UINT32_MAX) return 0;
    *v = (uint32_t)n;
    return 1;
}
static void string_json(const char *s)
{
    unsigned char c;
    putchar('"');
    while ((c = (unsigned char)*s++)) {
        if (c == '"' || c == '\\') { putchar('\\'); putchar(c); }
        else if (c < 32u || c >= 127u) printf("\\u%04x", c);
        else putchar(c);
    }
    putchar('"');
}
static int sample_write(FILE *f, int32_t v)
{
    uint32_t u = (uint32_t)v;
    unsigned char b[4] = {u & 255u, (u >> 8) & 255u, (u >> 16) & 255u, u >> 24};
    return fwrite(b, 1, 4, f) == 4;
}
/* Exact production expression, with explicit rejection of unsupported arithmetic.
 * The fixed master policy is 4096; do not algebraically drop its quantization. */
static int tap(int32_t mix, int32_t bus, int32_t *out)
{
    int64_t sum = (int64_t)mix + bus, product;
    if (sum < INT32_MIN || sum > INT32_MAX) return 0;
    product = ((int32_t)sum >> 2) * (int64_t)4096;
    if (product < INT32_MIN || product > INT32_MAX) return 0;
    *out = (int32_t)product >> 10;
    return 1;
}
static int master_fixture(void)
{
    static const int32_t sums[] = {1, 2, 3, 4, -1, -2, -3, -4, -2097152, 2097151};
    static const int32_t expected[] = {0, 0, 0, 4, -4, -4, -4, -4, -2097152, 2097148};
    static const int32_t values[] = {0, 1, -1, 31, -31, 200000, -200000, 512, -512, 0};
    audit_state initial = state_get(), finish;
    int32_t direct[20], quiet[20];
    uint32_t i;
    int different = 0;
    for (i = 0; i < sizeof sums / sizeof sums[0]; i++) {
        int32_t result;
        if (!tap(sums[i], 0, &result) || result != expected[i]) return 1;
    }
    {
        int32_t result;
        if (tap(INT32_MAX, 1, &result) || tap(INT32_MIN, -1, &result) ||
            tap(2097152, 0, &result) || tap(-2097153, 0, &result)) return 1;
    }
    fx_lowcut = 0;
    for (i = 0; i < 10u; i++) {
        int32_t l = values[i], r = -values[i];
        master_out(&l, &r); direct[2*i] = l; direct[2*i+1] = r;
    }
    finish = state_get(); state_set(initial);
    for (i = 0; i < 10u; i++) {
        int32_t l = values[i], r = -values[i];
        master_out(&l, &r);
        if (l != direct[2*i] || r != direct[2*i+1]) return 1;
    }
    state_set(initial);
    for (i = 0; i < 10u; i++) {
        int32_t l = values[i] / 32, r = -values[i] / 32;
        master_out(&l, &r); quiet[2*i] = l * 32; quiet[2*i+1] = r * 32;
        different |= quiet[2*i] != direct[2*i] || quiet[2*i+1] != direct[2*i+1];
    }
    state_set(finish);
    if (!different) return 1;
    puts("{\"tap_boundaries\":true,\"master_replay\":true,\"attenuate_rescale_is_not_equivalent\":true}");
    return 0;
}
int main(int argc, char **argv)
{
    uint32_t engine, preset, kit, reverb, frames, f, i, ne = 0, next = 0;
    audit_event ev[256];
    int32_t out[2*CTL], pre[2*CTL];
    FILE *events, *before, *after;
    const engine_t *e;
    if (argc == 2 && !strcmp(argv[1], "--self-test")) return master_fixture();
    if (argc == 2 && !strcmp(argv[1], "--overflow-self-test")) {
        /* A real native DC operation must terminate under the mandatory guard.
         * Volatile keeps this an actual runtime input rather than a folded probe. */
        volatile int32_t unsafe = INT32_MAX;
        int32_t l = unsafe, r = 0;
        master_out(&l, &r);
        return 0;                                    /* success here means the guard failed */
    }
    if (argc != 9 || !number(argv[1], &engine) || !number(argv[2], &preset) ||
        !number(argv[3], &kit) || !number(argv[4], &reverb) || !number(argv[5], &frames) ||
        !eng_ok(engine) || !frames || frames % CTL || frames > FS*12u || (reverb != 0u && reverb != 2u))
        return 2;
    e = eng_of(engine);
    if (preset >= e->npresets || (engine != ENGI_DRUM && kit != 255u) ||
        (engine == ENGI_DRUM && (kit >= DK_COUNT || drum_kit_plays(kit) != kit))) return 2;
    events = fopen(argv[6], "r");
    if (!events) return 3;
    { char line[128], extra;
      while (fgets(line, sizeof line, events)) {
        if (ne == 256u || sscanf(line, "%u %u %u %c", &ev[ne].frame, &ev[ne].note, &ev[ne].velocity, &extra) != 3) {
            fclose(events); return 2;
        }
        if (ev[ne].frame >= frames || ev[ne].frame % CTL || ev[ne].note > 127u || ev[ne].velocity > 127u ||
            (ne && ev[ne].frame < ev[ne-1].frame)) { fclose(events); return 2; }
        ne++;
      }
      if (!ne || ferror(events)) { fclose(events); return 2; } }
    fclose(events);
    before = fopen(argv[7], "wb"); after = fopen(argv[8], "wb");
    if (!before || !after) { if (before) fclose(before); if (after) fclose(after); return 3; }
    host_tracks_init(); host_preset(&trk[0], engine, preset);
    song.g[G_BPM] = 100; song.g[G_RTYPE] = reverb; song.sel = 0;
    song.master_q12 = 4096; fx_usb_fixed = 0; fx_lowcut = 0;
    if (engine == ENGI_DRUM) trk[0].p[P_E0] = (int16_t)kit;
    for (f = 0; f < frames; f += CTL) {
        audit_state start, finish;
        while (next < ne && ev[next].frame == f) {
            if (ev[next].velocity) trk_note_on(&trk[0], ev[next].note, ev[next].velocity);
            else trk_note_off(&trk[0], ev[next].note);
            next++;
        }
        start = state_get();
        mix_block(out, CTL);
        finish = state_get();
        if (perf_act || pf.busy || perf_held || perf_latched || perf_solo ||
            perf_k[0] || perf_k[1] || perf_k[2]) return 4;
        /* Consume THIS block now: the next mix_block clears/reuses these buffers. */
        for (i = 0; i < CTL; i++)
            if (!tap(mix_l[i], wet[i], &pre[2*i]) || !tap(mix_r[i], wet[i], &pre[2*i+1])) return 4;
        state_set(start);
        for (i = 0; i < CTL; i++) {
            int32_t l = pre[2*i], r = pre[2*i+1];
            master_out(&l, &r);
            if (l != out[2*i] || r != out[2*i+1]) return 4;
        }
        state_set(finish);
        for (i = 0; i < 2u*CTL; i++)
            if (!sample_write(before, pre[i]) || !sample_write(after, out[i])) return 3;
    }
    if (fclose(before) || fclose(after)) return 3;
    printf("{\"schema\":1,\"compiled_engine_ids\":[");
    { int separator = 0;
      for (i = 0; i < 64u; i++)
        if (eng_ok(i)) { printf("%s%u", separator ? "," : "", i); separator = 1; } }
    printf("],\"engine_id\":%u,\"engine_name\":", engine); string_json(e->name);
    printf(",\"preset\":%u,\"preset_name\":", preset); string_json(e->presets[preset].name);
    printf(",\"kit\":%u,\"frames\":%u,\"sample_rate\":%u,\"ctl\":%u,\"tap_replay_blocks\":%u,", kit, frames, FS, CTL, frames/CTL);
    printf("\"flags\":{\"cpu2\":%u,\"fm4\":%u,\"slice\":%u,\"macro\":%u},", FELUCCA_CPU2, FELUCCA_FM4, FELUCCA_SLICE, FELUCCA_PROFILE_ENGINE_14);
    printf("\"master_q12\":4096,\"lowcut\":0,\"usb_fixed\":0,\"performance\":false,\"reverb\":%u,\"track_parameter_count\":%u,\"global_parameter_count\":%u,\"track_parameters\":[", reverb, (unsigned)P_COUNT, (unsigned)G_COUNT);
    for (i = 0; i < P_COUNT; i++) printf("%s%d", i ? "," : "", trk[0].p[i]);
    printf("],\"global_parameters\":[");
    for (i = 0; i < G_COUNT; i++) printf("%s%d", i ? "," : "", song.g[i]);
    puts("]}");
    return ferror(stdout) ? 3 : 0;
}
