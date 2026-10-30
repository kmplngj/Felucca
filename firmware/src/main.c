/* SPDX-License-Identifier: GPL-3.0-only
 * Copyright (C) 2026 Leo Kuroshita (@kurogedelic), Hügelton Instruments */
#include "isr_assert.h"                    /* FM1_ASSERT_THREAD / FM1_ISR_SIM_* (#428) */
/* FELUCCA boot and main loop. Boot order: WDT first, boot-loop guard, fatal vectors,
 * guards; then LCD, input (TIMER5 IRQ, 10 kHz), audio (ALNK0 IRQ). */
extern uint32_t _data_start[], _data_end[], _data_load[], _bss_start[], _bss_end[];
extern uint32_t _pool_start[], _pool_end[], _rt_start[], _rt_end[], _rt_load[];
#if FELUCCA_CPU2
extern uint32_t _c1_start[], _c1_end[], _c1_load[];
#endif


#include "timer5.c"                         /* shared with the nested-input host regression */
extern void isr_timer5(void);

static void timer5_start(void)                 /* OSC /4 = 6 MHz, PRD 600 -> 10 kHz */
{
    fm1_timer5_start(isr_timer5, 4);   /* above ALNK0 (3): the scan nests into the render (see fm1_timer5_irq) */
}

static void hexs(char *b, uint32_t v)
{
    uint32_t i;
    for (i = 0; i < 8u; i++)
        b[i] = "0123456789ABCDEF"[(v >> (28u - 4u * i)) & 15u];
    b[8] = 0;
}

#if BOARD_SMK37
/* pads as a step grid (1-8 top row): the DRUM grid, NAME, the layers' tiles (not SCL: notes) */
static void smk_grid(void)
{
    uint32_t l = ui.layer ? ui.layer : ui.ly;
    smk_pad_grid = (uint8_t)(grid_on() || (name_on() && !ui.menu) || (l && l != LAYER_SCL));
}

/* the SMK-37 Pro's 4 faders, tracks 1..4, by FADER BANK (ui_input.c smk_fbank), as the MIXER page: A LEVEL,
 * B PAN (the middle centre), C REV send, D DLY send. A fader takes over only once it moves (also after a bank
 * change), so nothing jumps. */
static void smk_faders(void)
{
    static uint8_t last[4] = {0xFF, 0xFF, 0xFF, 0xFF};
    uint32_t i;
    if (smk_fbank_new) {                                  /* a new bank: wait for each fader to move */
        smk_fbank_new = 0;
        for (i = 0; i < 4u; i++)
            last[i] = 0xFF;
    }
    for (i = 0; i < 4u && i < NTRK; i++) {
        uint32_t v = fm1_in.fader[i];
        int16_t *pv;
        if (last[i] == 0xFF || fm1_in.frames < 200u) {   /* (the first readings settle) */
            last[i] = (uint8_t)v;
            continue;
        }
        if (v == last[i])
            continue;
        last[i] = (uint8_t)v;
        pv = smk_fbank == 1 ? &trk[i].p[P_PAN] : smk_fbank == 2 ? &trk[i].p[P_REV] :
             smk_fbank == 3 ? &trk[i].p[P_DLY] : &trk[i].p[P_LEVEL];
        *pv = (int16_t)(smk_fbank == 1 ? (int32_t)v - 64 : (int32_t)v);   /* (PAN -64..63) */
        ui.force = 1;
    }
}

#include "smk_wheel.h"
/* the wheels (stock: mux C address 4 = pitch, 5 = mod), self-calibrating: the pitch wheel's rest is its centre
 * (taken at power-on, followed slowly while it rests), each wheel's range grows to what it has reached (the
 * travel is short: raw ~445..640 pitch, ~474..629 mod on a unit). Pitch: a 14-bit bend -8192..8191 with a dead
 * band around the centre; mod: 0..127, up (lower raw) = more. The audio ISR plays them as the selected track's
 * MIDI pitch bend and CC1 (seq.c smk_wheels_block) */
static void smk_wheels(void)
{
    enum { DEAD = 12, SPAN0 = 80, MOD_LO = 485, MOD_HI = 615 };
    static int32_t pc, plo, phi, mlo, mhi;
    static uint32_t rest_ms;
    int32_t p = fm1_in.wheel[0], m = fm1_in.wheel[1], d, b, mw;
    if (fm1_in.frames < 300u)                     /* (the readings settle) */
        return;
    if (!pc) {
        pc = p;
        rest_ms = fm1_ms;
        plo = p - SPAN0;
        phi = p + SPAN0;
        mlo = m < MOD_LO ? m : MOD_LO;
        mhi = m > MOD_HI ? m : MOD_HI;
    }
    if (p < plo)
        plo = p;
    if (p > phi)
        phi = p;
    if (m < mlo)
        mlo = m;
    if (m > mhi)
        mhi = m;
    d = p - pc;
    if (d > -DEAD && d < DEAD) {
        b = 0;
        pc += smk_wheel_drift(d, fm1_ms, &rest_ms);
    } else {
        rest_ms = fm1_ms;
        b = d > 0 ? (d - DEAD) * 8191 / (phi - pc - DEAD > 1 ? phi - pc - DEAD : 1)
                  : (d + DEAD) * 8192 / (pc - plo - DEAD > 1 ? pc - plo - DEAD : 1);
        b = clamp(b, -8192, 8191);
    }
    mw = mhi - m <= DEAD ? 0 : (mhi - m - DEAD) * 127 / (mhi - mlo - DEAD > 1 ? mhi - mlo - DEAD : 1);
    smk_bend14 = (int16_t)b;
    smk_modw = (uint8_t)clamp(mw, 0, 127);
}
#endif

static void fm1_fault(const fm1_crash_t *c)
{
    char b[12];
    uint32_t t0;
    fm1_audio_stop();
    scr_wake_now();                                   /* (MENU > SCREEN OFF: the panel on first) */
    lcd_fill(0, 0, 240, 240, UI_CRASH_BG);            /* fixed, outside the palettes */
    draw_text_line(0, 8, 240, &AF_M, "FELUCCA CRASH", UI_CRASH_INK, UI_CRASH_BG, 1);
    hexs(b, c->vec);
    draw_text_line(10, 40, 220, &AF_M, b, UI_CRASH_INK, UI_CRASH_BG, 0);
    hexs(b, c->pc);
    draw_text_line(10, 60, 220, &AF_M, b, UI_CRASH_INK, UI_CRASH_BG, 0);
    hexs(b, c->emu);
    draw_text_line(10, 84, 220, &AF_M, b, UI_CRASH_INK, UI_CRASH_BG, 0);
    hexs(b, c->dbg);
    draw_text_line(10, 102, 220, &AF_M, b, UI_CRASH_INK, UI_CRASH_BG, 0);
    hexs(b, c->rets);
    draw_text_line(10, 120, 220, &AF_M, b, UI_CRASH_INK, UI_CRASH_BG, 0);
    t0 = fm1_ticks();
    while ((uint32_t)(fm1_ticks() - t0) < 4000u * 1000u * FM1_TICKS_PER_US)
        ;
    fm1_reboot();
}

/* power-on: the parts with their default sounds (TRK_DEF); the sequencers empty */
static void felucca_init(void)
{
    uint32_t i;
    chain_defaults(&chain_config);
    for (i = 0; i < G_COUNT; i++)
        song.g[i] = GP[i].def;
    undo_depth++;                             /* (no undo copy of the power-on loads) */
    fm6_init();                               /* every track's FM6 patch: the init voice */
    for (i = 0; i < NTRK; i++) {
        track_t *t = &trk[i];
        track_defaults(t);
        set_engine_of(t, TRK_DEF[i][0]);
        apply_preset_to(t, TRK_DEF[i][1]);    /* with its sends */
        t->engine = t->eng_req;
        eng_mem_claim(t);                     /* (zeros already: no note can come before) */
        track_defaults_steps(t);              /* (a sound load never touches them) */
        if (TRK_DEF[i][2])
            load_pat16(t, PATTERNS[TRK_DEF[i][2] - 1u].note, PATTERNS[TRK_DEF[i][2] - 1u].flags);
        pat_sig[i] = steps_sig(t);            /* a default pattern, not the user's */
        pat_last[i] = TRK_DEF[i][2];
    }
    undo_depth--;
    song.sel = 0;
    song.master_q12 = 2048;                   /* (the pot's level replaces it before the audio starts: master_boot) */
    ui.home = 1;
    ui.force = 1;
}

/* The power-on LED sweep (1.1, hal/fm1_led_anim.h: a soft light over the keys left to right, then the buttons swell
 * and settle on the glow; ~0.70 s), started before the scan and run by it: nothing waits for it, the splash's 430 ms
 * and the first ~0.27 s of the UI go by under it (the UI's LEDs from its end, or at once on a key or a button down).
 * Every LEDS setting: it is no idle glow; with DIM HI / DIM LO it ends on that glow (and is drawn over that glow
 * level), with OFF / INV dark. Not with MENU > ANIM OFF (no motion: the LEDs as the UI has them at once), not after a crash (a crash record newer than the last boot saw: the crash screen's
 * reset), a hang (a WDT reset) or a failed boot (bootguard: the last one died within its first 30 s): straight to the
 * UI. The UBOOT paths never get here. */
static uint32_t crash_seen __attribute__((section(".noinit")));   /* fm1_crash.count at the last boot */
static uint8_t boot_clean;                    /* no crash, hang (WDT) or failed boot before this one (boot_leds):
                                               * the sweep runs and the autosave is restored (project.c autosave_boot) */
static void boot_leds(void)
{
    fm1_crash_t c;
    uint32_t present = fm1_crash_read(&c);
    uint32_t crashed = present && c.count != crash_seen
#if FELUCCA_CPU2
                       && c.core != 1u    /* (the second core's own fault left core 0 playing) */
#endif
                       ;
    crash_seen = present ? c.count : 0;
    boot_clean = !crashed && !bootguard.failed && !(fm1_boot.p3_rst & 4u);
    fm1_led_dim_level(settings_leds == LEDS_DIM_LO);
    if (boot_clean && !(ui_prefs & PREF_ANIM_OFF))
        fm1_led_anim_start(settings_leds == LEDS_DIM || settings_leds == LEDS_DIM_LO);
}

/* Shared with the emulator: a fast boot for every build. Calibration and session
 * restore precede dismissal; interrupts keep scanning and playing MIDI meanwhile. */
#define BOOT_SPLASH_MS 430u
#define BOOT_SCAN_MS 30u
static int boot_splash_wait(uint32_t start)
{
    uint32_t pressed = fm1_input_edges(0);
    uint32_t notes = fm1_input_note_edges();
    enc_drop();                              /* no accumulated knob change on HOME */
    return !(pressed | notes | fm1_in.buttons | fm1_in.notes) &&
           (uint32_t)(fm1_ticks() - start) < BOOT_SPLASH_MS * 1000u * FM1_TICKS_PER_US;
}

/* The musical frame (#297): the steady-state work main.c's loop and the emulator (web/emu/felucca_web.c web_ms, and
 * through it native replay and the partition tests) share, in this one order. Each platform keeps its own scheduling
 * and services around it:
 *
 *   step                 firmware fm1_main                     emulator web_ms (1 ms of device time)
 *   frame gate           busy wait: fm1_ms - m >= 15           fm1_ms - web_last_frame >= 15
 *   before               WDT, usb_retry, bootguard, 2ND CORE   (the audio halves due by this ms)
 *   music_frame_sense    battery IIR, MASTER                   the same
 *   between              UBOOT hold, editor/OTA, UBOOT (USB),  nothing (no USB, editor, console)
 *                        console (cdc_task)
 *   music_frame_run      breadcrumbs, input, settings save, autosave, LEDs, screen (felucca_dbg.stage 1 -> 2 -> 9)
 *   music_frame_poll     ui_input on every pass of the wait     ui_input on each ms without a frame
 *                        (+ ed_service, #425 mr_step)
 *
 * Input precedes the queued settings save (settings_poll: stopped only), which precedes the autosave, which
 * precedes the LED composition and the drawing. Boot, splash, calibration and recovery are not frame work.
 * MUSIC_FRAME_STEP marks each step for the host frame test (tests/frame_test.c); empty in the firmware and emulator builds */
#ifndef MUSIC_FRAME_STEP
#define MUSIC_FRAME_STEP(s) ((void)0)
#endif
enum { MF_SENSE, MF_INPUT, MF_SETTINGS, MF_AUTOSAVE, MF_LEDS, MF_DRAW, MF_POLL };
static void music_frame_sense(void)
{
    int32_t b;
    MUSIC_FRAME_STEP(MF_SENSE);
    b = fm1_adc_read(FM1_ADC_BATT);                     /* battery: slow IIR */
    if (b > 0)
        song.batt_raw = song.batt_raw ? song.batt_raw + (b - song.batt_raw) / 32 : b;
    master_poll();
}
static void music_frame_run(void)
{
    felucca_dbg.ui_frames++;
    felucca_dbg.page = ui.page;
    felucca_dbg.home = ui.home;
    felucca_dbg.stage = 1;
    MUSIC_FRAME_STEP(MF_INPUT);
    ui_input();
    MUSIC_FRAME_STEP(MF_SETTINGS);
    settings_poll();                                    /* queued settings save: only while stopped */
    MUSIC_FRAME_STEP(MF_AUTOSAVE);
    autosave_poll();                                    /* (1.2) the music, stopped and idle: project.c */
    felucca_dbg.stage = 2;
    MUSIC_FRAME_STEP(MF_LEDS);
#if BOARD_SMK37
    smk_grid();
#endif
    ui_leds();
#if BOARD_SMK37
    smk_faders();
    smk_wheels();
    padled_flush();
#endif
    MUSIC_FRAME_STEP(MF_DRAW);
    ui_draw();
    felucca_dbg.stage = 9;
}
static void music_frame_poll(void)                      /* between frames: input is not held to the frame rate */
{
    MUSIC_FRAME_STEP(MF_POLL);
    ui_input();
#if BOARD_SMK37
    smk_wheels();
    smk_grid();
#endif
}

#if FELUCCA_CPU2
/* the notice for a retained exclusion (ui.msg: 23 characters at most); reasons from hal/fm1_sys.h */
static const char *c1_held_msg(uint32_t reason)
{
    static const char *const m[] = {"2ND CORE HELD", "2ND CORE HELD: BAD JOB", "2ND CORE HELD: TIMEOUT",
                                    "2ND CORE HELD: FAULT", "2ND CORE HELD: HANG", "2ND CORE HELD: CORRUPT"};
    return m[reason <= FM1_C1X_CORRUPT ? reason : 0u];
}
#endif

#if BOARD_SMK37 && FELUCCA_FLASH
#include "smk_storage_setup.h"
/* Before audio/TIMER5/USB startup: polling owns the matrix and watchdog. The
 * ordinary boot never initializes foreign data. Both BANK buttons opt into
 * this screen; all four controls must be released before a new OCT+ confirms. */
static void smk_storage_screen(const char *title, const char *line, uint32_t stage)
{
    lcd_fill(0, 0, 240, 240, 0);
    draw_text_box(3, 24, 234, &AF_M, title, 0xFFFFu, 1);
    if (stage < 2u) {
        draw_text_box(3, 62, 234, &AF_S, "ERASE SAVED PROJECTS,", 0xFFFFu, 1);
        draw_text_box(3, 82, 234, &AF_S, "PRESETS AND SETTINGS", 0xFFFFu, 1);
        draw_text_box(3, 112, 234, &AF_S, "SAMPLES AND CALIBRATION KEPT", 0xFFFFu, 1);
    }
    draw_text_box(3, 144, 234, &AF_S, line, 0xFFFFu, 1);
    if (stage < 2u) {
        draw_text_box(3, 180, 234, &AF_S, stage ? "OCT- CANCEL" : "RELEASE BANK AND OCT KEYS", 0xFFFFu, 1);
        draw_text_box(3, 204, 234, &AF_S, stage ? "OCT+ INITIALIZE" : "THEN CHOOSE WITH OCT-/+", 0xFFFFu, 1);
    } else if (stage == 3u) {
        draw_text_box(3, 180, 234, &AF_S, "CONTINUING WITHOUT SAVES", 0xFFFFu, 1);
        draw_text_box(3, 204, 234, &AF_S, "RESTART TO RETRY OR RECOVER", 0xFFFFu, 1);
    }
    lcd_sync();
}
static void smk_storage_setup(void)
{
    const uint32_t banks = (1u << SMK_BTN_KNOB_BANK) | (1u << SMK_BTN_FADER_BANK);
    const uint32_t down = 1u << FM1_BTN_OCT_DOWN, up = 1u << FM1_BTN_OCT_UP;
    uint32_t start, scanned, action = SMK_SETUP_WAIT, was_armed = 0;
    smk_setup_t state;
    if (!flash_ok || st_owner_ready || (fm1_in.buttons & banks) != banks)
        return;
    start = scanned = fm1_ticks();
    state.started = state.previous = state.armed = 0;
    smk_storage_screen("INITIALIZE STORAGE?", "FOREIGN DATA WILL BE ERASED", 0);
    while (action == SMK_SETUP_WAIT) {
        uint32_t now = fm1_ticks();
        fm1_wdt_feed();
        if ((uint32_t)(now - scanned) >= 100u * FM1_TICKS_PER_US) {
            scanned = now;
            fm1_input_tick();
        }
        action = smk_setup_step(&state, (now - start) / (1000u * FM1_TICKS_PER_US),
                                fm1_in.buttons, banks, down, up);
        if (state.armed != was_armed) {
            was_armed = state.armed;
            smk_storage_screen("INITIALIZE STORAGE?", "FOREIGN DATA WILL BE ERASED", 1);
        }
    }
    if (action != SMK_SETUP_CONFIRM)
        return;                                      /* cancel/timeout: no flash mutation */
    smk_storage_screen("INITIALIZING", "KEEP POWER CONNECTED", 2);
    fm1_wdt_feed();
    if (!st_owner_initialize()) {
        boot_policy_intentional(&bootguard);
        fm1_reboot();                                 /* reload defaults through normal boot */
    }
    smk_storage_screen("INITIALIZATION FAILED", "RAM ONLY / DATA NOT LOADED", 3);
    start = fm1_ticks();
    while ((uint32_t)(fm1_ticks() - start) < 1500000u * FM1_TICKS_PER_US) {
        fm1_wdt_feed();
        if ((uint32_t)(fm1_ticks() - scanned) >= 100u * FM1_TICKS_PER_US) {
            scanned = fm1_ticks();
            fm1_input_tick();
        }
    }
}
#endif

static void fm1_main(void)
{
    uint32_t splash_start, master_ms;
    boot_policy_live_t boot_live;
#if FELUCCA_CPU2
    uint8_t c1_told = 0;                                /* 2ND CORE HELD shown (and ON cleared) */
    uint32_t c1_refused = 0;                            /* the retained exclusion that kept it from starting (fm1_c1g_*) */
#endif
    persist_boot();
#if FELUCCA_OTA
    if (flash_ok)
        ota_boot_cleanup();                             /* staging area left by an update */
#endif
    settings_init();
    usb_serial_apply();                                 /* (#67: the saved USB SERIAL before usb_start) */
    lcd_init();
#if BOARD_SMK37 && FELUCCA_FLASH
    smk_storage_setup();
#endif
    draw_splash();                                      /* ui_draw.c (1.1.5) */
    if (felucca_dbg.magic != DBG_MAGIC) {
        memset(&felucca_dbg, 0, sizeof felucca_dbg);
        felucca_dbg.magic = DBG_MAGIC;
    }
    felucca_dbg.boots++;
    felucca_dbg.max_us = 0;
    felucca_dbg.in_audio = 0;                       /* .noinit: a reset inside the audio ISR left it set, and
                                                       TIMER5 would treat every tick as nested (no USB poll) */
    felucca_dbg.prev_stage = felucca_dbg.stage;     /* a WDT reset leaves the last breadcrumb here */
    felucca_dbg.prev_page = felucca_dbg.page;
    felucca_dbg.prev_home = felucca_dbg.home;
    felucca_dbg.prev_frames = felucca_dbg.ui_frames;
    felucca_dbg.prev_rst = fm1_boot.p3_rst;
    fm1_input_init();
    fm1_adc_init();
#if BOARD_SMK37 && FELUCCA_FLASH
    if (flash_ok)                                   /* the factory key / pad velocity curves (USRTRIM, read only) */
        smk_trim_load(fm1_xip_ptr(SMK_TRIM_FLASH));
#endif
    panel_init();
    felucca_init();
    master_boot();
    kb_boot_hold = 1;                         /* #137: no notes from the keys before the UI (seq.c keyboard_block) */
#if FELUCCA_CPU2
    if (ui_prefs2 & (PREF_CPU2_ON >> 16)) {
        /* the second core (hal/fm1_cpu1.h; fx.c mix_block hands it parts), at power-on, before the audio and
         * the timers (started later it never reaches its entry). It starts in the chip's ROM: the PC limits open
         * meanwhile. MENU > 2ND CORE OFF (the default), a crash in the last boot's first 30 s, a retained exclusion
         * (a bad job, a timeout, core 0's fault or a hang while it answered: fm1_c1g_refuse, hal/fm1_sys.h; the saved
         * ON does not override it, MENU > 2ND CORE set ON again does) or no answer: it is never started, one core,
         * as 1.6. The exclusion is read even after a bootguard failure (the worker's own watchdog reset is one): the
         * notice and the cleared ON preference follow from it, or a lost RAM would start the failed worker again */
        c1_refused = fm1_c1g_refuse();
        if (!bootguard.failed && !c1_refused) {
            fm1_guard_pc_open();
            fm1_cpu1_start();
            fm1_guard_enable(FM1_GUARD_PC);
        }
    }
#endif
    audio_init();
    usb_start();
#if FELUCCA_UART
    uart_midi_init();
#endif
    boot_leds();
    timer5_start();
    fm1_guard_lock_top();
    fm1_irq_enable_all();
    splash_start = fm1_ticks();               /* fm1_ms may jump when TIMER5 first seeds its clock */
    fm1_delay_ms(BOOT_SCAN_MS);
    if ((fm1_in.buttons & FM1_OCT_BOTH) == FM1_OCT_BOTH) {
        panel_setup();                        /* OCT- + OCT+ held at power-on */
        settings_save();
    }
    autosave_boot(boot_clean);                /* (1.2) the last session's music, under the splash */
    master_ms = fm1_ms;
    while (boot_splash_wait(splash_start)) { /* dismiss at the next debounced input scan */
        fm1_wdt_feed();
        usb_retry(fm1_ms);
        if ((uint32_t)(fm1_ms - master_ms) >= 10u) {
            master_ms = fm1_ms;
            master_poll();                  /* preserve the pot smoothing cadence */
        }
    }
    /* ui_input releases kb_boot_hold after every dismissal key is up. */
    lcd_fill(0, 0, 240, 240, T_BG);
    scrn.idle = fm1_ms;                        /* (MENU > SCREEN OFF: from here) */
#if BOARD_SMK37 && FELUCCA_FLASH
    if (flash_ok && !st_owner_ready)
        ui_say("STORAGE LOCKED", "FOREIGN DATA KEPT");
#endif

    boot_policy_live_begin(&boot_live, fm1_ms);
    for (;;) {
        uint32_t m = fm1_ms;
        fm1_wdt_feed();
        usb_retry(fm1_ms);
        boot_policy_service(&bootguard, &boot_live, fm1_ms);
#if FELUCCA_CPU2
        if (!c1_told) {                                 /* (fm1_c1_gave_up is the ISR's) */
            uint32_t why = c1_refused;
            if (!why && *(volatile uint8_t *)&fm1_c1_gave_up)
                why = fm1_c1g_read(0);                  /* its wait recorded BAD_JOB or TIMEOUT before holding it */
            if (why) {
                c1_told = 1;                            /* (once: ON set again afterwards stays, for the next power-on) */
                if (ui_prefs2 & (PREF_CPU2_ON >> 16)) {
                    ui_prefs2 &= (uint8_t)~(PREF_CPU2_ON >> 16);   /* one core from now on: a bad job, a timeout or a
                                                         * retained exclusion; MENU > 2ND CORE ON tries again */
                    settings_later();                   /* (main loop only: never from the ISR or before the exclusion) */
                }
                ui_message(c1_held_msg(why));
            }
        }
#endif
        music_frame_sense();                            /* battery, MASTER (before the platform services, as ever) */
        {   /* OCT- + OCT+ held 5 s: enter UBOOT with RAM intact (debug / update); a countdown
             * shows from 2 s over the whole screen (the menu and the dialogs too: ui_draw), letting
             * go cancels it */
            static uint32_t t0;
            uint32_t both = (1u << panel.btn[B_OCTDN]) | (1u << panel.btn[B_OCTUP]);
            if (kb_boot_hold || (fm1_in.buttons & both) != both) {
                if (ui.uboot) {
                    ui.uboot = 0;
                    ui.force = 1;                       /* what the countdown covered */
                    ui_message("UPDATE CANCELLED");
                }
                t0 = fm1_ms;
            } else if (fm1_ms - t0 > 2000u && fm1_ms - t0 <= 5000u) {
                uint32_t left = (5000u - (fm1_ms - t0) + 999u) / 1000u;
                if (left != ui.uboot) {
                    ui.uboot = (uint8_t)left;
                    ui.force = 1;
                }
            } else if (fm1_ms - t0 > 5000u) {
                fm1_audio_stop();
                scr_wake_now();
                lcd_fill(0, 0, 240, 240, T_BG);
                draw_text_box(0, 110, 240, &AF_M, "UBOOT", T_THEME, 1);
                usb_detach();
                fm1_delay_ms(30);
                boot_policy_intentional(&bootguard);     /* intentional reset */
                fm1_enter_uboot();
            }
        }
#if FELUCCA_OTA
        if (ed_service())                               /* OTA only for a held non-editor frame */
            ota_service();                              /* M-UPGRADE handshake */
        if (usb.ota_req) {                              /* M-UPGRADE upgrade command */
            usb.ota_req = 0;
            panic_req = (1u << NTRK) - 1u;               /* every track (bit per track) */
            scr_wake_now();                             /* (its progress on the screen) */
            if (flash_ok)
                ota_session();                          /* returns only if nothing was committed */
            lcd_fill(0, 0, 240, 240, T_BG);
            ui.force = 1;
        }
#endif
        if (usb.uboot_req) {                            /* SysEx F0 22 24 35 7D F7 from the host */
            fm1_audio_stop();
            scr_wake_now();
            lcd_fill(0, 0, 240, 240, T_BG);
            draw_text_box(0, 110, 240, &AF_M, "UBOOT (USB)", T_THEME, 1);
            fm1_delay_ms(20);
            usb_detach();
            fm1_delay_ms(30);
            boot_policy_intentional(&bootguard);
            fm1_enter_uboot();
        }
#if FELUCCA_CDC
        cdc_task();
#endif
        music_frame_run();                              /* input, settings, autosave, LEDs, screen */
        while (fm1_ms - m < 15u) {                               /* ~60 UI frames/s at most */
            music_frame_poll();
#if FELUCCA_OTA
            ed_service();                       /* editor replies without waiting for the next frame */
#endif
#if FELUCCA_MUL64_REPRO
            mr_step();                          /* #425 reproducer: one bounded step of idle time (mul64_repro.c) */
#endif
        }
    }
}

void fm1_cstart(void)
{
    uint32_t *s, *d, p3, src, wdt;
    boot_policy_path_t boot_path;
#if FELUCCA_CDC && defined(__PI32V2__)
    fm1_clock_snapshot_t boot_clock;
#endif
#if FELUCCA_CPU2
    fm1_cpu1_halt();                           /* (after Jangada, X0X): a second core still running from before
                                                * this reset (a watchdog, a fault, another firmware) would read the RAM
                                                * cleared below */
#endif
#if FELUCCA_CDC && defined(__PI32V2__)
    fm1_clock_read(&boot_clock);                /* after the optional core-1 hold; before peripheral initialization */
#endif
    fm1_time_init();
    fm1_reset_reason();
    p3 = fm1_boot.p3_rst;
#if FELUCCA_CPU2
    fm1_c1g_boot(p3);                          /* the retained worker guard, settled before anything reads it (fm1_sys.h) */
#endif
    src = fm1_boot.rst_src;
    wdt = fm1_boot.wdt_con;
    fm1_wdt_arm(0x0D);
    boot_path = boot_policy_begin(&bootguard, p3, src);
    if (boot_path == BOOT_POLICY_ROM)
        fm1_enter_uboot();                     /* another reset while in rescue */
    fm1_irq_init();
    for (d = _bss_start; d < _bss_end; d++)
        *d = 0;
    for (d = _pool_start; d < _pool_end; d++)
        *d = 0;
    for (s = _data_load, d = _data_start; d < _data_end; s++, d++)
        *d = *s;
#if FELUCCA_CDC && defined(__PI32V2__)
    fm1_boot_clock = boot_clock;                /* RAM is initialized; normal-startup CDC reports this boot only */
#endif
    for (s = _rt_load, d = _rt_start; d < _rt_end; s++, d++)
        *d = *s;                                /* flash driver code that must run from RAM */
#if FELUCCA_CPU2
    for (s = _c1_load, d = _c1_start; d < _c1_end; s++, d++)
        *d = *s;                                /* the second core's waiting loop (hal/fm1_cpu1.h) */
#endif
    fm1_mailbox_clear();
    fm1_guard_enable(FM1_GUARD_STACK | FM1_GUARD_WRITE | FM1_GUARD_BUS | FM1_GUARD_PC);
    fm1_boot.p3_rst = (uint8_t)p3;
    fm1_boot.rst_src = src;
    fm1_boot.wdt_con = (uint8_t)wdt;
    boot_path = boot_policy_select(&bootguard, boot_path, rescue_boot_buttons(), FELUCCA_OTA);
    if (boot_path == BOOT_POLICY_ROM)
        fm1_enter_uboot();                     /* builds without OTA retain the ROM fallback */
#if FELUCCA_OTA
    if (boot_path == BOOT_POLICY_RESCUE)
        rescue_run();
#endif
    fm1_main();
    for (;;)
        ;
}
