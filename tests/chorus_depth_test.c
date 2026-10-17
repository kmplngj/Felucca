/* SPDX-License-Identifier: GPL-3.0-only */
/* Independent wide-product reference: old stationary sample-wise chorus, with
 * an optional sample-count depth slew. Instrument only its actual read delay. */
#define main hostsim_main
#include FX_TEST_HOSTSIM
#undef main
#include <assert.h>

static int16_t reference[CHO_LEN];
static int32_t zero[CTL];
static int legacy;
static void clear(void)
{
    memset(&fx, 0, sizeof fx);
    memset(&hl, 0, sizeof hl);
    memset(&pf, 0, sizeof pf);
    memset(cho_buf, 0, sizeof cho_buf);
    memset(dly_buf, 0, sizeof dly_buf);
    memset(rev_comb, 0, sizeof rev_comb);
    memset(&rev_u, 0, sizeof rev_u);
    memset(reference, 0, sizeof reference);
    host_tracks_init();
    song.g[G_DMIX] = 0;
}

static int32_t delay_at(uint32_t phase, int32_t depth)
{
    return (400 << 8) + (int32_t)(((int64_t)(osc_sine(phase) + 32768) * depth) >> 16);
}

static void trajectory(int from, int to, int rate, int partition, int rapid)
{
    uint32_t t = 0, block = 0, sizes = 0, ph = UINT32_MAX - 100u, wp = UINT32_MAX - 100u;
    int32_t depth = from * 6 * 256, input[CTL], wet[CTL];
    clear();
    fx.cho_ph = ph;
    fx.cho_w = wp;
    song.g[G_CDEPTH] = from;
    while (t < 8192u) {
        uint32_t n = partition ? 1u + (block++ * 13u % CTL) : CTL, i;
        int target = t < 1024u ? from : rapid && t < 4096u ? ((t / 32u) & 1u ? to : from) : to;
        /* Keep every size recurring during edits, independently of accumulated time. */
        if (partition && t >= 1024u && t < 4096u)
            sizes |= UINT32_C(1) << (n - 1u);
        /* Each parameter change happens at a block boundary, just like all control sources. */
        song.g[G_CDEPTH] = target;
        song.g[G_CRATE] = t >= 2048u ? 127 - rate : rate;
        for (i = 0; i < n; i++)
            input[i] = 2 + (int32_t)(14000 * sin((t + i) * 0.031));
        fx_buses(input, zero, zero, wet, n);
        for (i = 0; i < n; i++) {
            int32_t want = target * 6 * 256, r, f, y;
            if (legacy) depth = want;
            else depth += clamp(want - depth, -96, 96);
            reference[wp & (CHO_LEN - 1)] = (int16_t)(input[i] >> 1);
            ph += LFO_INC[song.g[G_CRATE]] / CTL;
            r = delay_at(ph, depth);
            assert(r == chorus_test_tap[i]);
            f = r & 255;
            y = reference[(wp - ((uint32_t)r >> 8)) & (CHO_LEN - 1)];
            y += ((reference[(wp - ((uint32_t)r >> 8) - 1u) & (CHO_LEN - 1)] - y) * f) >> 8;
            assert(wet[i] == y * 2);
            wp++;
        }
        assert(fx.cho_w == wp && fx.cho_ph == ph);
        assert(!memcmp(reference, cho_buf, sizeof reference));
#ifdef CHORUS_DEPTH_TEST_SMOOTH
        assert(fx.cho_depth == depth);
#endif
        t += n;
    }
    if (partition)
        assert(sizes == UINT32_MAX);    /* all 1..32-frame blocks occur during the edit interval */
    assert(depth == to * 6 * 256);
    /* Retarget while the tail is still live, then start directly at another target. */
    song.g[G_CDEPTH] = from;
    for (t = 0; t < CHO_LEN / CTL + 1u; t++) fx_buses(zero, zero, zero, wet, CTL);
    assert(!fx.cho_live);
    for (t = 0; t < CTL; t++)
        assert(!wet[t]);
#ifdef CHORUS_DEPTH_TEST_SMOOTH
    assert(fx.cho_depth == from * 6 * 256);
#endif
    song.g[G_CDEPTH] = 127 - to;
    fx_buses(input, zero, zero, wet, CTL);
    assert(chorus_test_tap[0] == delay_at(fx.cho_ph - (CTL - 1u) * (LFO_INC[song.g[G_CRATE]] / CTL),
                                       song.g[G_CDEPTH] * 6 * 256));
}

static void four_tracks(void)
{
    uint32_t p, b;
    int32_t out[2 * CTL];
    int64_t energy[NTRK] = {0};
    clear();
    memset(trk, 0, sizeof trk);
    host_tracks_init();
    for (p = 0; p < NTRK; p++) {
        host_preset(&trk[p], 0, 0);           /* stable engine id 0: ANALOG */
        trk[p].p[P_CHOR] = 127;
        trk[p].p[P_DLY] = trk[p].p[P_REV] = 0;
        trk[p].p[P_AMODE] = 0;
        trk_note_on(&trk[p], 48 + p * 4, 90);
    }
    for (b = 0; b < 256; b++) {
        song.g[G_CDEPTH] = b < 64 ? 0 : b < 192 ? 127 : 0;
        mix_block(out, CTL);
        assert(fx.cho_live);
    }
#ifdef CHORUS_DEPTH_TEST_SMOOTH
    assert(!fx.cho_depth);              /* exactly landed after the second full-range edit */
#endif
    /* Each sending track still contributes through the real part/send mixer. */
    for (p = 0; p < NTRK; p++) {
        uint32_t i;
        for (i = 0; i < NTRK; i++) trk[i].p[P_CHOR] = i == p ? 127 : 0;
        mix_block(out, CTL);
        for (i = 0; i < CTL; i++) energy[p] += (int64_t)send_c[i] * send_c[i];
        assert(energy[p] > 0);
    }
}

static void recording(const char *dir, int chord, int jump)
{
    char path[1024];
    uint32_t t;
    int32_t in[CTL], wet[CTL], maxedit = 0, maxaudio = 0, previous = 0, edit_audio = 0, control_audio = 0;
    FILE *f;
    clear();
    song.g[G_CDEPTH] = 63;
    song.g[G_CRATE] = 0;
    fx.cho_ph = 0x40000000u;
    snprintf(path, sizeof path, "%s/%s_%s_%s.wav", dir, legacy ? "before" : "after", chord ? "chord" : "sine", jump ? "jump" : "detent");
    f = fopen(path, "wb"); assert(f); wav_hdr(f, FS * 2u);
    for (t = 0; t < FS * 2u; t += CTL) {
        uint32_t i, n = FS * 2u - t < CTL ? FS * 2u - t : CTL;
        if (t == (FS / CTL) * CTL) song.g[G_CDEPTH] = jump ? 127 : 64;
        for (i = 0; i < n; i++) {
            double x = sin(2 * 3.141592653589793 * 110 * (t + i) / FS);
            if (chord) x = (x + sin(2 * 3.141592653589793 * 138.59 * (t + i) / FS) +
                                 sin(2 * 3.141592653589793 * 164.81 * (t + i) / FS)) / 3;
            in[i] = (int32_t)(12000 * x);
        }
        fx_buses(in, zero, zero, wet, n);
        if (t == (FS / CTL) * CTL) {
            uint32_t ph = fx.cho_ph - (n - 1u) * (LFO_INC[0] / CTL);
            int32_t r = delay_at(ph, 63 * 6 * 256), f = r & 255, control;
            uint32_t wp = fx.cho_w - n, ri = (uint32_t)r >> 8;
            control = cho_buf[(wp - ri) & (CHO_LEN - 1)];
            control += ((cho_buf[(wp - ri - 1u) & (CHO_LEN - 1)] - control) * f) >> 8;
            control *= 2;
            maxedit = abs(chorus_test_tap[0] - r);
            maxaudio = abs(wet[0] - previous);
            control_audio = abs(control - previous);
            edit_audio = abs(wet[0] - control);
        }
        for (i = 0; i < n; i++) wav_put(f, (in[i] + wet[i]) / 2, (in[i] + wet[i]) / 2);
        previous = wet[n - 1u];
    }
    fclose(f);
    printf("%s %s %s: edit read delta %.4f samples, wet adjacent %d, unedited adjacent %d, edit-only audio %d Q15\n",
           legacy ? "before" : "after", chord ? "chord" : "sine", jump ? "jump" : "detent", maxedit / 256.0, maxaudio, control_audio, edit_audio);
    if (!legacy) assert(maxedit <= 96);
    else assert(maxedit > 96);
}

int main(int argc, char **argv)
{
    int d, partition, rate, chord, jump;
    assert(argc == 3); legacy = !strcmp(argv[2], "legacy");
    for (d = 0; d <= 127; d++)
        for (partition = 0; partition < 2; partition++)
            for (rate = 0; rate <= 127; rate += 127) {
                trajectory(d, 127 - d, rate, partition, 0);
                trajectory(d, (d + 1) & 127, rate, partition, 1);
                trajectory(d, d, rate, partition, 0);
            }
    for (chord = 0; chord < 2; chord++) for (jump = 0; jump < 2; jump++) recording(argv[1], chord, jump);
    four_tracks();
    /* Zero frames must not inspect pointers, advance phase or mutate state. */
    if (!legacy) {
        __typeof__(fx) before = fx;
        __typeof__(hl) hall_before = hl;
        fx_buses(NULL, NULL, NULL, NULL, 0);
        assert(!memcmp(&before, &fx, sizeof fx));
        assert(!memcmp(&hall_before, &hl, sizeof hl));
    }
    puts("chorus depth: all endpoints/directions, rapid edits, Rate changes, phase/index wraps, short blocks, exact PCM/state, drain/restart passed");
    return 0;
}
