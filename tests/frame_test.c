/* SPDX-License-Identifier: GPL-3.0-only */
/* The shared musical frame (#297, firmware/src/main.c music_frame_*) as the integrated emulator runs it: the real UI,
 * settings, autosave, LED and drawing code against the emulator HAL and its simulated NOR, one process per case.
 * main.c's own loop (fm1_main) cannot run on a host; tests/frame_source_test.py checks that it and web_ms call these
 * same functions and copy none of their steps. Device timing, scanning, USB and DMA remain FM-1 checks. */
#include <stdint.h>
#include <stdio.h>
#include <sys/wait.h>
#include <unistd.h>

#define FT_N 8192u
static struct { uint8_t step; uint32_t ms, writes; } ft[FT_N];
static uint32_t ft_n;
static void frame_trace(uint32_t s);
#define MUSIC_FRAME_STEP(s) frame_trace(s)
#include "../web/emu/felucca_web.c"

static void frame_trace(uint32_t s)
{
    if (ft_n < FT_N) {
        ft[ft_n].step = (uint8_t)s;
        ft[ft_n].ms = fm1_ms;
        ft[ft_n].writes = web_flash_writes;
    }
    ft_n++;
}

static uint32_t scenario;
#define CHECK(ok) do { if (!(ok)) { fprintf(stderr, "frame case %u line %d: %s\n", scenario, __LINE__, #ok); return 1; } } while (0)
static void step(uint32_t ms) { while (ms--) web_ms(); }

/* the steps one millisecond ran: 1 = a whole frame (sense, input, settings, autosave, LEDs, screen), 2 = one poll
 * (input between frames), 0 = anything else (a step missing, repeated, reordered or mixed) */
static int ms_kind(uint32_t from, uint32_t to)
{
    static const uint8_t FRAME[] = {MF_SENSE, MF_INPUT, MF_SETTINGS, MF_AUTOSAVE, MF_LEDS, MF_DRAW};
    uint32_t i;
    if (to - from == 1u && ft[from].step == MF_POLL)
        return 2;
    if (to - from != sizeof FRAME)
        return 0;
    for (i = 0; i < sizeof FRAME; i++)
        if (ft[from + i].step != FRAME[i])
            return 0;
    return 1;
}
/* run ms milliseconds; each must be a whole frame exactly every 15 ms (the first at *next) or else one poll */
static int run_checked(uint32_t ms, uint32_t *next)
{
    while (ms--) {
        uint32_t from = ft_n, frames = felucca_dbg.ui_frames, kind;
        web_ms();
        if (ft_n > FT_N)
            return 0;
        kind = (uint32_t)ms_kind(from, ft_n);
        if (fm1_ms == *next) {
            if (kind != 1u || felucca_dbg.ui_frames != frames + 1u || felucca_dbg.stage != 9u ||
                felucca_dbg.page != ui.page || felucca_dbg.home != ui.home || ft[from].ms != *next)
                return 0;
            *next += 15u;
        } else if (kind != 2u || felucca_dbg.ui_frames != frames) {
            return 0;
        }
        ft_n = 0;
    }
    return 1;
}
/* the step during which the flash was written from trace entry `from` on: MF_* or -1 none, -2 several */
static int writer(uint32_t from)
{
    int w = -1;
    uint32_t i;
    for (i = from; i < ft_n && i < FT_N; i++) {
        uint32_t after = i + 1u < ft_n ? ft[i + 1u].writes : web_flash_writes;
        if (after != ft[i].writes)
            w = w == -1 || w == ft[i].step ? ft[i].step : -2;
    }
    return w;
}
static uint32_t to_frame(void)                       /* step to just before the next frame's millisecond */
{
    while (fm1_ms + 1u - web_last_frame < 15u)
        web_ms();
    return fm1_ms + 1u;
}
static int16_t *home_knob(uint32_t k)
{
    int16_t *vp;
    home_param(k, &vp);
    return vp;
}

static int run_case(void)
{
    uint32_t next;
    if (scenario == 1u)
        fm1_ms = UINT32_MAX - BOOT_SPLASH_MS - 300u;  /* wrap during the checked frames, after the splash */
    web_nor_erase();
    web_boot();
    step(BOOT_SPLASH_MS);
    CHECK(!web_splash && flash_ok);
    ft_n = 0;
    next = web_last_frame + 15u;                      /* (a frame ran at the splash's end) */

    if (scenario <= 1u) {                             /* cadence: a whole frame every 15 ms, one poll every ms between */
        uint32_t start = fm1_ms;
        if (scenario == 1u)
            CHECK(start > UINT32_MAX - 1000u);
        CHECK(run_checked(1000u, &next));
        if (scenario == 1u)
            CHECK(fm1_ms < start);                   /* fail if setup moves the wrap outside run_checked */
        return 0;
    }
    if (scenario == 2u) {                             /* input between frames and at a frame's own millisecond */
        int16_t *vp = home_knob(0), v0;
        uint32_t f;
        CHECK(ui.home && vp);
        step(40);
        v0 = *vp;
        f = to_frame();
        step(7);                                      /* mid-gap: the poll takes the detent in this millisecond */
        ft_n = 0;
        web_enc(EN_K1, 1);
        step(1);
        CHECK(ms_kind(0, ft_n) == 2 && *vp != v0);
        CHECK(fm1_ms - f == 7u);                       /* (the frame at f, then 6 polls) */
        f = to_frame();
        ft_n = 0;
        web_enc(EN_K1, -1);                           /* due with the frame: its input step takes it, no poll */
        step(1);
        CHECK(fm1_ms == f && ms_kind(0, ft_n) == 1 && *vp == v0);
        ft_n = 0;
        next = web_last_frame + 15u;
        CHECK(run_checked(100u, &next) && *vp == v0);   /* neither repeated nor lost later */
        return 0;
    }
    if (scenario == 3u) {                             /* a queued settings save: committed by a frame once stopped */
        static persist_rec_t old, got;
        uint32_t w0, n;
        step(40);
        old = persist_saved;
        web_buttons(1u << B_PLAY);
        step(30);
        web_buttons(0);
        step(20);
        CHECK(song.playing);
        settings.lowcut ^= 1u;
        w0 = web_flash_writes;
        settings_save();                              /* (as MENU's close, or a deferred panel request, asks) */
        CHECK(persist_pending == 1u && web_flash_writes == w0);
        ft_n = 0;
        step(300);                                    /* playing: every frame's settings step waits */
        CHECK(persist_pending == 1u && web_flash_writes == w0);
        web_buttons(1u << B_PLAY);
        step(1);
        web_buttons(0);
        ft_n = 0;
        for (n = 0; song.playing && n < 1000u; n++)
            step(1);
        CHECK(!song.playing);
        ft_n = 0;
        step(16);                                     /* the next frame */
        CHECK(!persist_pending && web_flash_writes > w0 && writer(0) == MF_SETTINGS);
        memset(&got, 0, sizeof got);
        n = (uint32_t)st_load(OBJ_SETTINGS, &got, sizeof got);
        CHECK(n == persist_len(&persist_saved) && !memcmp(&got, &persist_saved, n) && !settings_unsaved());
        CHECK(got.lowcut == settings.lowcut && got.lowcut != old.lowcut);
        return 0;
    }
    if (scenario == 4u) {                             /* the idle autosave: a frame's autosave step writes it, once */
        int16_t *vp = home_knob(0), v0;
        uint32_t t, n, w0;
        int found = 0;
        step(40);
        v0 = *vp;
        web_enc(EN_K1, 3);
        step(1);
        CHECK(*vp != v0 && as.writes == 0u);
        t = fm1_ms;
        w0 = web_flash_writes;
        step(AS_IDLE_MS - 500u);                      /* unchanged and quiet, not yet for 10 s */
        CHECK(as.writes == 0u && web_flash_writes == w0);
        while (!as.writes && fm1_ms - t < AS_IDLE_MS + 2000u) {
            ft_n = 0;
            step(1);
        }
        CHECK(as.writes == 1u && !as.err && writer(0) == MF_AUTOSAVE);
        CHECK(fm1_ms - t >= AS_IDLE_MS && fm1_ms - t <= AS_IDLE_MS + 2u * AS_POLL_MS);
        n = (uint32_t)st_load(OBJ_AUTOSAVE, &proj_wire, sizeof proj_wire);
        CHECK(n > 0u && proj_import(&proj_scratch, &proj_wire, (int)n));
        found = proj_scratch.t[song.sel].p[vp - TSEL->p] == *vp;
        CHECK(found);
        w0 = web_flash_writes;
        step(AS_GAP_MS);                              /* nothing changed: no second write */
        CHECK(as.writes == 1u && web_flash_writes == w0);
        return 0;
    }
    return 1;
}

int main(void)
{
    for (scenario = 0; scenario < 5u; scenario++) {
        int status;
        pid_t pid = fork();
        if (pid == 0) _exit(run_case());
        if (pid < 0 || waitpid(pid, &status, 0) < 0 || !WIFEXITED(status) || WEXITSTATUS(status))
            return 1;
    }
    puts("musical frame: 15 ms cadence and step order (and across fm1_ms wrap), input between/at frames, "
         "queued settings commit and idle autosave in their frame steps: ok");
    return 0;
}
