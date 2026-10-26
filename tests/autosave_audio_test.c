/* SPDX-License-Identifier: GPL-3.0-only */
/* Real FX/master output and automatic saves against the persistence fixture's NOR.
 * No active voices remain during the tail: their existing guard cannot hide this bug. */
#define PERSISTENCE_FIXTURE
#include "persistence_test.c"

static uint32_t audio_frame, audio_start, last_loud, first_save, write_peak;
static uint32_t audible_blocks, late_blocks, unsafe_writes, test_phase;
static uint32_t dirty_start;
enum { AUTO_PROGRAMS = (PROJ_STORE_SIZE + 255u) / 256u + 1u }; /* payload pages plus commit */
static int32_t rendered[2u * CTL];

static uint32_t channel_peak(const int32_t *out, uint32_t ch)
{
    uint32_t i, peak = 0;
    for (i = ch; i < 2u * CTL; i += 2u) {
        uint32_t a = (uint32_t)(out[i] < 0 ? -out[i] : out[i]);
        if (a > peak) peak = a;
    }
    return peak;
}

static void audio_fresh(uint32_t start)
{
    reset();
    as_power_on();
    memset(&fx, 0, sizeof fx);
    memset(&hl, 0, sizeof hl);
    memset(dly_buf, 0, sizeof dly_buf);
    memset(cho_buf, 0, sizeof cho_buf);
    memset(rev_comb, 0, sizeof rev_comb);
    memset(&rev_u, 0, sizeof rev_u);
    memset(&pf, 0, sizeof pf);
    pf.src = pf.next = PF_N;
    pf.lc = PF_TOP;
    for (uint32_t i = 0; i < NTRK; i++) pf.mg[i] = 32768;
    perf_held = perf_latched = perf_act = perf_kill = perf_solo = 0;
    memset((void *)perf_k, 0, sizeof perf_k);
    fm1_in.notes = fm1_in.buttons = 0;
    ui_prefs = fx_usb_fixed = fx_lowcut = scope_mix = 0;
    dc_l = dc_r = dce_l = dce_r = 0;
    lim_env = LIM_T;
    audio_frame = last_loud = first_save = write_peak = 0;
    audible_blocks = late_blocks = unsafe_writes = test_phase = 0;
    audio_start = fm1_ms = start;
    as_erases = as_programs = as_commits = as_mutations = 0;
    if (dirty_start) nor[0xE5FFFu] = 0;   /* blank header, dirty tail: exercise the erase path too */
}

static void audio_begin(void)
{
    autosave_boot(1);
    as_edit(0);
}

/* The independent oracle observes final stereo Q15 PCM, not the activity publication. */
static void audio_poll(void)
{
    uint32_t l = channel_peak(rendered, 0), r = channel_peak(rendered, 1), before = as_mutations;
    uint32_t peak = l > r ? l : r, elapsed;
    audio_frame += CTL;
    elapsed = (uint32_t)((uint64_t)audio_frame * 1000u / FS);
    fm1_ms = audio_start + elapsed;
    uint64_t energy[2] = {0, 0};
    for (uint32_t i = 0; i < CTL; i++)
        for (uint32_t ch = 0; ch < 2; ch++) {
            int64_t v = rendered[2u * i + ch];
            energy[ch] += (uint64_t)(v * v);
        }
    uint32_t loud = energy[0] > 1024u * CTL || energy[1] > 1024u * CTL;
    if (loud) {
        last_loud = elapsed;
        audible_blocks++;
        late_blocks += elapsed >= AS_IDLE_MS;
    }
    autosave_poll();
    if (as_mutations != before) {
        if (!first_save) first_save = elapsed;
        write_peak = peak;
        unsafe_writes += loud || elapsed - last_loud < AS_IDLE_MS;
    }
}

static void sine_send(int32_t *signal)
{
    const uint32_t inc = (uint32_t)(((uint64_t)440u << 32) / FS);
    for (uint32_t i = 0; i < CTL; i++) {
        signal[i] = mulq15(osc_sine(test_phase), 16000);
        test_phase += inc;
    }
}

enum { T_SILENCE, T_DELAY, T_ROOM, T_SPRING, T_HALL, T_CHORUS, T_ROOM_SWITCH };
static int tail_case(const char *name, uint32_t kind, uint32_t fixed, uint32_t perf, uint32_t start)
{
    int32_t zero[CTL] = {0}, signal[CTL], bus[CTL], dac[2u * CTL];
    uint32_t b, dac_peak = 0, sig, note;
    int bad = 0;
    int32_t lo[2] = {32767, 32767}, hi[2] = {-32768, -32768};
    double sum[2] = {0}, sq[2] = {0};
    uint32_t samples = 0;
    audio_fresh(start);
    song.g[G_BPM] = GP[G_BPM].min;                 /* 40: the current valid minimum, maximum delay */
    song.g[G_DTIME] = 0;
    song.g[G_DFDBK] = GP[G_DFDBK].max;
    song.g[G_DCOLOR] = song.g[G_DMIX] = 127;
    song.g[G_RTYPE] = kind == T_SPRING ? 1 : kind == T_HALL ? 2 : 0;
    song.g[G_RSIZE] = kind == T_ROOM ? 0 : 127;
    song.g[G_RDAMP] = 0;
    song.g[G_CDEPTH] = 127;
    for (b = 0; b < FS / CTL; b++) {
        sine_send(signal);
        fx_buses(kind == T_CHORUS ? signal : zero, kind == T_DELAY ? signal : zero,
                 (kind >= T_ROOM && kind <= T_HALL) || kind == T_ROOM_SWITCH ? signal : zero, bus, CTL);
    }
    if (fixed) { fx_usb_fixed = 1; song.master_q12 = 0; }
    if (perf) perf_latched = PF_BIT(PF_FLG);        /* actual perf_begin -> perf_master branch */
    scope_mix = kind & 1u;                         /* no HOME/scope dependency */
    ui.page = (uint8_t)page_first(FAM_FX);
    audio_begin();
    sig = autosave_sig();
    note = trk[0].step[0].note[0];
    for (b = 0; b < 200u * FS / CTL; b++) {
        if (kind == T_ROOM_SWITCH && b == 150u * FS / CTL) {
            bad += check("ROOM127 varying residual still holds automatic saves", !as_mutations && last_loud > 149000u);
            song.g[G_RTYPE] = 2;                    /* real model switch clears the old resonator */
            sig = autosave_sig();
        }
        mix_block(rendered, CTL);
        if (fixed) {
            memcpy(dac, rendered, sizeof dac);
            usb_fixed_dac(dac, CTL);
            dac_peak |= channel_peak(dac, 0) | channel_peak(dac, 1);
        }
        audio_poll();
        if (b >= 149u * FS / CTL && b < 150u * FS / CTL) {
            for (uint32_t i = 0; i < CTL; i++)
                for (uint32_t ch = 0; ch < 2; ch++) {
                    int32_t v = rendered[2u * i + ch];
                    if (v < lo[ch]) lo[ch] = v;
                    if (v > hi[ch]) hi[ch] = v;
                    sum[ch] += v;
                    sq[ch] += (double)v * v;
                }
            samples += CTL;
        }
        if (first_save && (uint32_t)(fm1_ms - audio_start) >= first_save + 11000u) break;
    }
    if (samples)
        for (uint32_t ch = 0; ch < 2; ch++) {
            double mean = sum[ch] / samples;
            printf("residual ch%u: samples=%u min=%d max=%d mean=%.6f rms=%.6f ac_rms=%.6f\n",
                   ch, samples, lo[ch], hi[ch], mean, sqrt(sq[ch] / samples), sqrt(sq[ch] / samples - mean * mean));
        }
    printf("autosave audio: %s: last loud %u ms, first write %u ms, write peak %u, erases %u, commits %u, late blocks %u\n",
           name, last_loud, first_save, write_peak, as_erases, as_commits, late_blocks);
    bad += check(name, !unsafe_writes && first_save && as.writes == 1u && as_commits == 1u && as_programs == AUTO_PROGRAMS && as_erases == dirty_start &&
                 as.saved == sig && (kind == T_SILENCE || audible_blocks) &&
                 (kind != T_DELAY || late_blocks) && (!fixed || !dac_peak));
    /* Delayed writes keep the edited project, not merely an acknowledged signature. */
    as_power_on();
    bad += check("  deferred project restores the edited music", autosave_boot(1) == 1 && trk[0].step[0].n == 1u && trk[0].step[0].note[0] == note &&
                 song.g[G_BPM] == GP[G_BPM].min);
    return bad;
}


/* A real final-master right-only burst just before the old deadline. It ends before the next main
 * poll, with no active voices at either poll: sampling instantaneous PCM or left-only scope misses it. */
static int burst_case(uint32_t wrap)
{
    uint32_t b, l = 0, r = 0;
    int bad = 0;
    audio_fresh(0);
    audio_begin();
    if (wrap) fx_audio_activity = as.audio = UINT32_MAX;
    as_run(9750u);
    audio_frame = 9750u * FS / 1000u;
    for (uint32_t i = 0; i < CTL; i++) {
        mix_l[i] = wet[i] = 0;
        mix_r[i] = wrap ? (i == 0 ? -16000 : 0) : (i & 1u ? -16000 : 16000);
    }
    perf_master(rendered, CTL);
    l = channel_peak(rendered, 0); r = channel_peak(rendered, 1);
    audio_poll();
    for (b = 0; b < 22000u * FS / (1000u * CTL); b++) {
        mix_block(rendered, CTL);
        audio_poll();
    }
    bad += check(wrap ? "generation wrap retains an isolated right-channel pulse between polls" :
                 "right-only burst between polls restarts the full quiet window",
                 !l && r > 32u && !unsafe_writes && as_commits == 1u && as_erases == dirty_start && first_save >= 19750u);
    return bad;
}

/* Feed the native final master alternating tiny samples continuously. Test actual final PCM at
 * both threshold edges, not a manually supplied busy flag; rounded residuals must not hold forever. */
static int threshold_case(int32_t input, uint32_t audible)
{
    uint32_t b, low = UINT32_MAX, high = 0;
    int bad;
    audio_fresh(0);
    song.master_q12 = 1024;                       /* exact quarter gain avoids the mixer's pre-shift asymmetry */
    audio_begin();
    for (b = 0; b < 12000u * FS / (1000u * CTL); b++) {
        for (uint32_t i = 0; i < CTL; i++) {
            mix_l[i] = wet[i] = 0;
            mix_r[i] = i & 1u ? -input : input;
        }
        perf_master(rendered, CTL);
        for (uint32_t i = 0; i < CTL; i++) {
            uint32_t a = (uint32_t)(rendered[2u * i + 1u] < 0 ? -rendered[2u * i + 1u] : rendered[2u * i + 1u]);
            if (a < low) low = a;
            if (a > high) high = a;
        }
        audio_poll();
    }
    printf("threshold: input +/- %d -> final abs %u..%u Q15, erases %u\n", input, low, high, as_erases);
    bad = check(audible ? "+/-33 final PCM continually defers autosave" : "+/-32 final residual saves once",
                low == (audible ? 33u : 32u) && high == low &&
                (audible ? !as_mutations : as_commits == 1u && as_erases == dirty_start && !unsafe_writes));
    return bad;
}

static int retry_case(void)
{
    int bad = 0;
    uint32_t before;
    audio_fresh(UINT32_MAX - 5000u);
    audio_begin();
    fail_after = 0;
    as_run(10500u);
    bad += check("failed automatic save preserves dirty data", as.err && !as.writes && as.saved != as.seen && !as_commits && as_programs == 1u && as_erases == dirty_start);
    before = fm1_ms;
    as_run(29000u);
    bad += check("failed save retries wait thirty seconds across timer wrap", !as_commits && as_programs == 1u && as_erases == dirty_start);
    fail_after = -1;
    as_run(1500u);
    bad += check("retry commits once, then respects the wear gap", !as.err && as.writes == 1u && as_commits == 1u && as_programs == 1u + AUTO_PROGRAMS && as_erases == dirty_start &&
                 fm1_ms - before >= AS_RETRY_MS);
    as_edit(1);
    as_run(59000u);
    bad += check("next dirty edit still waits sixty seconds", as.writes == 1u && as_commits == 1u && as_programs == 1u + AUTO_PROGRAMS && as_erases == dirty_start);
    as_run(1500u);
    bad += check("dirty edit commits once after wear gap", as.writes == 2u && as_commits == 2u && as_programs == 1u + 2u * AUTO_PROGRAMS && as_erases == dirty_start);
    return bad;
}

int main(void)
{
    int bad = 0;
    for (dirty_start = 0; dirty_start < 2u; dirty_start++) {
        printf("autosave destination: %s\n", dirty_start ? "dirty tail" : "blank");
        bad += tail_case("silence: one save after idle", T_SILENCE, 0, 0, 0);
        bad += tail_case("long delay: no write through audible tail", T_DELAY, 0, 0, 0);
        bad += tail_case("ROOM minimum-size tail", T_ROOM, 0, 0, 0);
        bad += tail_case("SPRING tail", T_SPRING, 0, 0, 0);
        bad += tail_case("stereo HALL tail", T_HALL, 0, 0, 0);
        bad += tail_case("ROOM127 residual, then model switch", T_ROOM_SWITCH, 0, 0, 0);
        bad += tail_case("chorus tail", T_CHORUS, 0, 0, 0);
        bad += tail_case("USB FIXED: full USB tail with silent DAC", T_DELAY, 1, 0, 0);
        bad += tail_case("performance master and millisecond wrap", T_DELAY, 0, 1, UINT32_MAX - 5000u);
        bad += burst_case(0);
        bad += burst_case(1);
        bad += threshold_case(132, 0);
        bad += threshold_case(136, 1);
        bad += retry_case();
    }
    return bad != 0;
}
