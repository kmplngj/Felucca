/* SPDX-License-Identifier: GPL-3.0-only
 * Copyright (C) 2026 Leo Kuroshita (@kurogedelic), Hügelton Instruments */
#include "isr_assert.h"                    /* FM1_ASSERT_THREAD / FM1_ISR_SIM_* (#428) */
/* FELUCCA user interface.
 * Flat: SURF cards and panels on the palette's background, no rules, one selected text family (M8Stealth by default), tracks
 * named by their numbers 1..4 on a cushion (icons.c trk_icon). Four columns <-> KNOB 1..4. Rendering is lazy:
 * every element remembers what it last drew and is redrawn only on change. */
#include "build_identity.h"             /* shared by target, host and emulator UI */

static int project_save(uint32_t slot);
static void panel_setup(void);
static void project_load(uint32_t slot);
static int project_new(void);
static int proj_changed(void);
static int project_used(uint32_t slot);
static int graph_project_used(uint32_t slot);       /* cached slot validity for display only (ui_graph.c) */
static uint32_t chain_prepare(void);
static int up_used(uint32_t k);              /* user presets: upreset.c */
static int up_load(uint32_t k);
static uint32_t up_count(void);
static uint32_t up_nth(uint32_t n);
static uint32_t up_rank(uint32_t slot);
static uint32_t up_engine(uint32_t k);
static uint32_t up_fp(uint32_t k);
static void up_name(uint32_t k, char *b);
static void up_slot_label(char *b, uint32_t k);
static void up_ui(uint32_t op, uint32_t k);
static int up_has_pat(uint32_t k);               /* user presets that hold a pattern */
static uint32_t up_pat_count(void);
static uint32_t up_pat_nth(uint32_t n);
static uint32_t up_pat_rank(uint32_t slot);
static void up_pat_load(track_t *t, uint32_t k);
static void up_auto_name(char *b, uint32_t e, uint32_t k);   /* naming (ui_name.c) */
static void up_ui_named(uint32_t op, uint32_t k, const char *name, uint32_t cat);
static uint32_t up_cat(uint32_t k);
static void ui_message(const char *s);
static int project_save_as(uint32_t slot, const char *name);
static int project_name(uint32_t slot, char *b);
static int project_info(uint32_t slot, char *b, uint16_t *len48, uint32_t *den, uint8_t *n);
static int project_rename(uint32_t slot, const char *name);
static int project_erase(uint32_t slot);
static void project_cur_name(char *b);
static uint32_t user_of(const track_t *t)    /* user preset slot its sound came from, UP_SLOTS = none */
{
    return t->user && up_used(t->user - 1u) ? t->user - 1u : UP_SLOTS;
}
static uint32_t up_gen;                      /* bumped on every user bank change (redraws) */
#include "favorites.c"
#include "category.c"                   /* sound categories (Discussion #90): PRESETS > LIST */
/* MENU's two-valued settings (ui_menu.c MENU_FLAGS), a bit each in a byte no engine uses (as ui_layer.c layer_seen):
 * saved with the settings; 0 in older ones = every setting's default (append-only: a new setting takes a new bit,
 * its default is 0) */
#define ui_prefs (settings_dev[30])
#define PREF_LATCH 1u                          /* MENU > FX LATCH ON (#40) */
#define PREF_ANIM_OFF 2u                       /* MENU > ANIM OFF (#46): values snap (no rolling digits, no glide) */
#define PREF_ACCEL 4u                          /* MENU > KNOB ACCEL ON (#52): fast turns of wide values x2..x8 */
#define PREF_USB_FIXED 8u                      /* MENU > USB LEVEL FIXED: USB audio at the full level, MASTER after */
#define PREF_BPM_LOCK 16u                      /* MENU > BPM LOCK ON (#58): SELECT sets the tempo only with GLO held */
#define PREF_LARGE 32u                         /* reserved historical size bit: round-trips for rollback; no layout effect */
#define PREF_SERIAL_OFF 64u                    /* MENU > USB SERIAL OFF (#67): no serial console, the device enumerates as
                                                * audio + MIDI only (usb.c usb_cdc_switch); clear in every older setting = ON */
#define PREF_RESTORE_OFF 128u                  /* MENU > RESTORE LAST OFF (1.2, Discussion #130): no autosave written, none
                                                * restored at power-on (project.c); clear in every older setting = ON */
#define fx_latch ui_prefs
/* MENU > AUDIO CLICK, CLICK LEVEL, COUNT-IN (1.1, Discussion #131; click.c, seq.c): two bits each in another byte no
 * engine uses, saved with the settings: bits 0-1 CLICK (OFF REC ON), 2-3 CLICK LEVEL (stored 0 MID, 1 LOW, 2 HIGH),
 * 4-5 COUNT-IN (OFF, 1 BAR, 2 BARS); 0 in older settings = OFF / MID / OFF, so nothing clicks or counts in that did
 * not; 3 (unknown) reads as 0 (settings_persist.c puts it back). Bit 6 (1.2): MENU > SCALE LEDS ON (Discussion #127,
 * ui_input.c scale_leds; 0 in older settings = OFF). Bit 7 (1.5.5, #208): MENU > MIDI > AUTO SELECT ON */
#define ui_rec_prefs (settings_dev[28])
#define PREF_REC 0xFF00u                       /* (menu_items.c MENU_FLAGS: a bit of ui_rec_prefs, << 8) */
#define PREF_SCALE_LEDS (0x40u << 8)
#define PREF_MIDI_FOLLOW (0x80u << 8)          /* 1.5.5 (#208): MENU > MIDI > AUTO SELECT ON, bit 7 of ui_rec_prefs (0 in
                                                * every older setting = OFF; ui_input.c midi_follow) */
/* 1.2: three more two-valued MENU settings, bits of another byte no engine uses, saved with the settings; 0 in older
 * settings = today's behaviour (append-only, as ui_prefs): bit 0 DISPLAY > SCOPE MIX (Discussion #165, fx.c scope_mix),
 * bit 1 CONTROL > STEP PREVIEW ON (Discussion #169, ui_input.c step_preview), bit 2 CONTROL > CHORD ENTRY ADD (#155,
 * ui_input.c seq_entry). 1.5: bit 3 SYSTEM > HELP ON (Discussion #156, ui_help.c). 1.5.5: bit 4 CONTROL > SELECT PAGE
 * (Discussion #188, ui_input.c: SELECT steps the pages; 0 = BPM, as before); bit 5 MIDI > SCREEN WAKE PANEL (scr_input:
 * only the panel wakes SCREEN OFF, as up to 1.5.1; 0, every older setting, = +MIDI, the default: a note-on too).
 * 1.5.6: bit 6 SELECT's second bit (#84: sel_mode). Bit 7 free */
#define ui_prefs2 (settings_dev[24])
#define PREF_X 0xFF0000u                       /* (menu_items.c MENU_FLAGS: a bit of ui_prefs2, << 16) */
#define PREF_SCOPE_MIX (0x01u << 16)
#define PREF_PREVIEW (0x02u << 16)
#define PREF_CHORD_ADD (0x04u << 16)
#define PREF_HELP (0x08u << 16)
#define PREF_SEL_PAGE (0x10u << 16)
#define PREF_WAKE_PANEL (0x20u << 16)
#define PREF_SEL_HI (0x40u << 16)
#define PREF_CPU2_ON (0x80u << 16)              /* MENU > SYSTEM > 2ND CORE ON (BETA): the second core from the next
                                                 * power-on (main.c); clear = OFF, one core as 1.6 (every older setting:
                                                 * 1.6 never set bit 7). It turns itself OFF when core 1 misreads
                                                 * (hal/fm1_cpu1.h). (The 1.6.1 dual-core beta build had it the other
                                                 * way round, 0 AUTO / 1 OFF) */
/* MENU > CONTROL > SELECT: 0 BPM, 1 PAGE (1.5.5, #188), 2 MODW, 3 VEL (1.5.6, #84: ui_input.c sel_play), bit 4 and bit 6 of
 * ui_prefs2 (0 in every older setting = BPM; 1.5.5's PAGE keeps its bit; firmware before 1.5.6 reads MODW as BPM and
 * VEL as PAGE (its bit 4), before 1.5.5 both as BPM) */
enum { SEL_BPM, SEL_PAGE, SEL_MODW, SEL_VEL, SEL_N };
static uint32_t sel_mode(void) { return ((ui_prefs2 >> 4) & 1u) | ((ui_prefs2 >> 5) & 2u); }
/* 1.3 (Discussions #112, #134): MENU > DISPLAY > HOME, what the HOME page shows under its four cards: 0 SCOPE (the
 * oscilloscope, as before), 1 TRACKS (the four tracks as rows: ui_graph.c draw_home_tracks), 2 LEVELS (1.5, #134: the
 * rows of TRACKS, and KNOB 1..4 the LEVEL of T1..T4 in place of the engine's four: home_param). A byte of its own no
 * engine uses, saved with the settings; 0 in older settings = SCOPE; an unknown value (a later firmware's view) reads as
 * SCOPE and is kept as saved (1.3 / 1.4 read LEVELS so) */
#define ui_home_view (settings_dev[26])
/* 1.5.6 (#212): MENU > DISPLAY > LEDS INV LO / INV HI: INV with the idle LEDs at the steady mid level (ui_input.c
 * ui_leds) instead of lit. The mode stays INV (settings_leds, panel.c: so firmware before 1.5.6 reads plain INV) and
 * this byte no engine uses holds the level: 1 LO, 2 HI; 0 (every older setting) or another value = INV as before.
 * Saved with the settings; read only while LEDS is INV (menu_items.c leds_row) */
#define ui_leds_inv (settings_dev[25])
static uint32_t leds_inv(void) { return settings_leds == LEDS_INV && ui_leds_inv - 1u < 2u ? ui_leds_inv : 0u; }
enum { HV_SCOPE, HV_TRACKS, HV_LEVELS, HV_COUNT };
static int home_tracks(void) { return ui_home_view == HV_TRACKS || ui_home_view == HV_LEVELS; }
/* #572: MENU > DISPLAY > GRAPH (menu_items.c GRAPH_N), bits 1..2 of ANIM IDLE's byte (ui_idle, settings_dev[10]: bit 0
 * IDLE; every older firmware reads bit 0 only and keeps the byte as saved). Stored 0, every older setting, is TURN, the
 * default: the codes 0 TURN, 1 SCOPE, 2 CURVE, 3 STILL swap the first two of the menu's order (GRAPH_CODE: its own
 * inverse) */
enum { GM_SCOPE, GM_TURN, GM_CURVE, GM_STILL, GM_COUNT };
#define GRAPH_CODE(v) ((v) < 2u ? (v) ^ 1u : (v))
static uint32_t graph_mode(void) { return GRAPH_CODE((settings_dev[10] >> 1) & 3u); }
static void graph_mode_put(uint32_t v)
{
    settings_dev[10] = (uint8_t)((settings_dev[10] & ~6u) | GRAPH_CODE(v & 3u) << 1);
}
static int home_levels(void) { return ui_home_view == HV_LEVELS; }
enum { RP_CLICK, RP_LEVEL, RP_COUNTIN };
static uint32_t rp_get(uint32_t f)                     /* a field as the MENU steps it: 0..2 */
{
    uint32_t v = (ui_rec_prefs >> (2u * f)) & 3u;
    v = v == 3u ? 0u : v;
    return f == RP_LEVEL ? (v == 0u ? 1u : v == 1u ? 0u : 2u) : v;   /* (LEVEL: LOW MID HIGH, MID stored as 0) */
}
static void rp_apply(void)                             /* the settings into click.c / seq.c (every frame: ui_input) */
{
    click_mode = (uint8_t)rp_get(RP_CLICK);
    click_lvl = (uint8_t)rp_get(RP_LEVEL);
    cin_bars = (uint8_t)rp_get(RP_COUNTIN);
}
static void rp_put(uint32_t f, uint32_t v)
{
    uint32_t st = f == RP_LEVEL ? (v == 1u ? 0u : v == 0u ? 1u : 2u) : v % 3u;
    ui_rec_prefs = (uint8_t)((ui_rec_prefs & ~(3u << (2u * f))) | st << (2u * f));
    rp_apply();
}
/* MENU > STYLE (ui_menu.c): ST_FLAT ST_LINE (gfx.c) in another byte no engine uses, saved with the settings;
 * 0 in older ones = FLAT; 2, the retired PIXEL (1.0.1), reads as LINE; anything else unknown as FLAT (settings_persist.c). gfx.c draws from its copy, ux.style
 * (ui_draw.c style_apply) */
#define ui_style (settings_dev[29])
static void draw_gaps(uint32_t y, uint32_t h);        /* (ui_draw.c) */

static uint8_t sync_reload;                  /* engine / preset / project / user preset loaded: editor RELOAD push */

#define ACC T_THEME                /* values, curves */
#define VAL(c) ((c) == ui.hot_col && ui.hot_t ? T_ACCENT : T_THEME)   /* the knob just turned: accent */
#define RATIO(d, v) ((d)->max > (d)->min ? ((int32_t)(v) - (d)->min) * 1000 / ((d)->max - (d)->min) : -1)
/* layout: header 0..24, four cards 28..72 (57 px at x 3 + 59 c),
 * the panel 76..198 (a SURF area; the graphs live in it), footer 202..240; BG between them. #572: a value page whose
 * panel draws on the 100 px graph scale gives its bank the X numeral's room: bank 28..94, panel 98..198 (bank_tall) */
#define Y_HEAD 0
#define H_HEAD 24
#define Y_LABEL 28                    /* the cards */
#define Y_SEP_END 72
#define CARD_W 57
#define CARD_H 44
#define CARD_H_TALL 66              /* (#572: the bank with its X numeral) */
#define CURVE_HOLD 80u              /* #572 GRAPH TURN: frames (~1.2 s) the curve outlasts the last detent */
#define CARD_X(c) (3 + 59 * (int32_t)(c))
#define Y_GRAPH 76                    /* the panel */
#define H_GRAPH 122
#define Y_FOOT 202
#define H_FOOT 38

typedef struct {
    char label[24], value[16], unit[12];
    uint32_t key;
    uint16_t color;
    uint8_t face, small, motion, lock, fixed;
    int16_t ratio;               /* #572: the knob's place in its range, 0..1000; -1 none (the rule full) */
} bank_field_t;

static struct {
    uint8_t home;
    uint8_t page;                /* index into PAGES */
    uint8_t fam_last[FAM_COUNT]; /* last page used per family */
    uint8_t bank;                /* SEQ: 16-step bank (follows the cursor) */
    uint8_t cursor;              /* SEQ: step being edited (STEP page KNOB 1 moves it) */
    uint8_t entry_open;          /* SEQ: keys held since the first press of this entry */
    uint8_t lane;                /* SEQ > STEP on a DRUM track (the grid): the lane the keys and KNOB 3 / 4 edit */
    uint8_t plk_src;             /* parameter locks (ui_input.c lock_*): the sound page whose KNOB 1..4 a step held
                                  * locks, PAGES index + 1; 0 = HOME's four */
    uint8_t plk_lane, plk_trk;   /* .. the grid: the lane and the track of the hits plk_rm takes away */
    uint64_t plk_rm, plk_acc;    /* .. the grid's step keys pressed on a hit (bit = step): it goes when the key is let
                                  * go, unless the key was held for a lock (its accent: plk_acc) */
    uint8_t hot_col, hot_t;      /* column whose knob was just turned (drawn white) */
    uint8_t curve_t;             /* #572 GRAPH TURN: frames the turned knob's curve stays in the scope's place */
    uint8_t menu;                /* 0 off, 1 list, 2 about + credits, 3 info, 4 AUTO OFF detail (HOME held) */
    uint8_t menu_sel;            /* MENU: the row (menu_items.c MI_*; its tab MI_TAB), kept while the device runs */
    uint8_t menu_row[5];         /* MENU: the row last picked in each tab, from its first (ALGORITHM comes back to it) */
    uint16_t menu_scroll;        /* continuous ABOUT + CREDITS position, pixels */
    uint32_t menu_sig, home_t0;  /* HOME press time (btn_hold) */
    uint8_t force;               /* full redraw pending */
    uint8_t msg_t;               /* transient message frames */
    uint8_t help_t;              /* 1.5, MENU > HELP ON: frames the page's hint stays in the footer (ui_help.c) */
    uint8_t bpm_t;               /* frames the BPM stays highlighted after a SELECT turn */
    uint8_t act;                 /* action pages: the column whose action OCT+ does, + 1; 0 = none (act_col) */
    uint8_t tl_clean;            /* SAVE > TOOLS: KNOB 2 turned on past INIT, CLEAN INIT picked (1.5.5, #190) */
    uint32_t rec_t0;             /* REC press time: a tap arms (btn_hold, no hold: held, REC opens its layer) */
    uint32_t save_t0;           /* SAVE press time (btn_hold: held = UNDO) */
    uint8_t confirm;             /* the OCT- / OCT+ dialog: CF_*, 0 = none */
    uint8_t confirm_trk;         /* the track it clears, the slot it overwrites */
    uint8_t uslot;               /* SAVE > USER: the selected user preset slot */
    uint8_t ppick;               /* SAVE > PHRASES: the pattern picked (pat_count list index) */
    uint8_t song_row;            /* SONG: the section selected, count selects + ADD */
    uint8_t song_trk;            /* SONG: the lane (track) selected, 0..NTRK-1 */
    uint16_t ev_row;             /* SEQ > AUTOMATION (ui_events.c ev_*): the row selected (0 PLAY / CLEAR, 1 QUANTIZE, the
                                  * last + ADD; 1.2: up to EV_ROWS, past 255) */
    uint8_t ev_step, ev_id;      /* .. + ADD: the step and the parameter (or EV_CHANCE, EV_RATCH, EV_NUDGE, EV_VEL) it
                                  * adds on */
    uint16_t ev_keep;            /* .. the CHANCE / RATCH / NUDGE row being edited (its EVC code, 0 none): listed at its default */
    uint8_t ev_vel;              /* .. 1.5: the VEL rows shown (+ ADD VEL's SHOW / HIDE; off when the page is entered) */
    uint8_t uboot;               /* main.c: seconds left before UPDATE MODE (OCT- + OCT+ held), 0 = none */
    uint32_t ly_t0;              /* the layer button's press time | 1, LY_* bits (ui_layer.c layer_gesture) */
    uint8_t ly;                  /* the layer whose button is down (LAYER_*), 0 = none */
    uint8_t layer;               /* the layer whose map is shown (LAYER_*), 0 = none */
    uint8_t lock;                /* #83: the layer locked open by a double tap (LAYER_*), 0 = none (ui_layer.c) */
#if BOARD_SMK37
    uint32_t pg_down;            /* SMK calibration may map a page to button 16 or 17 */
#else
    uint16_t pg_down;            /* page buttons down (panel ids) that act when let go */
#endif
    uint32_t layer_sig;          /* drawn-state cache of the map */
    char msg[24];
    char msg2[24];               /* a second message, shown when the first is over */
    uint32_t enc_t[NE];
    /* drawn-state cache */
    char col[4][32];
    struct {
        bank_field_t field[4];
        uint32_t sig[5];
        uint8_t mask, was, focus, lock_next;
    } read_bank;                    /* #572: display cache, reset/snapshotted with the rest of the UI */
    uint32_t graph_sig, head_sig, foot_sig, frame;
    /* rolling digits (ui_draw.c roll_*): the four card values and the header BPM */
    struct {
        char from[7];            /* the value rolling out; "" = idle */
        uint8_t t0;              /* (ui.frame) of the value's last change */
        int8_t dir;              /* +1: it went up (the old digit leaves upward), -1: down */
        uint8_t sig;             /* a card: what its value is of (label, unit, track, engine, palette) */
    } roll[5];
    int16_t roll_bpm;            /* the BPM last drawn */
    struct {                     /* MIDI LEARN (midi_learn.c; here, not loose globals: the audio ISR's data keeps its
                                  * layout and its cost, tests/target_budget.py) */
        uint8_t on;              /* MIDI LEARN is on */
        uint8_t pick, trk, id;   /* a parameter picked (1): its track and P_* id */
        volatile uint8_t io[2];  /* midi_control.c ml_arm, ml_heard */
    } ml;
    volatile uint8_t mpc[NTRK];  /* MIDI Program Change per track, 0x80 | program, 0 none (midi_control.c mpc_io: here
                                  * for the same reason as ml.io; midi_pc_poll) */
} ui;

enum { CF_NONE, CF_CLEAR_SEQ, CF_CLEAR_TRK, CF_OVR_PROJ, CF_OVR_USER, CF_LOAD_PAT,
       CF_DEL_ROW, CF_CLEAR_SONG, CF_INIT_SOUND, CF_CLEAR_MOTION, CF_ERASE_USER, CF_ERASE_PROJ, CF_CLEAN_SOUND,
       CF_CLEAR_ALL, CF_LOAD_PROJ, CF_LEARN_CLEAR };
                                  /* ui.confirm: TOOLS' clears; SAVE over a used slot; a pattern over the user's steps;
                                   * USER ERASE; PROJECT ERASE (1.5.5, #199); CLEAN INIT (1.5.5, #190);
                                   * MENU > SYSTEM > CLEAR ALL; PROJECT LOAD over changes not saved; MIDI LEARN CLEAR (1.8) */

/* MENU > DISPLAY > AUTO OFF (formerly SCREEN OFF): after a while with no input on the panel the screen goes dark (the backlight
 * stays on: lcd.c lcd_power)
 * (a picture held for hours can stay faintly on the panel); the sound, the sequencer, MIDI and USB go on, the LEDs
 * stay as they are for SCREEN. LEDS blanks all LED maps, BOTH also sleeps the LCD. LED-only wake acts on its input
 * normally; SCREEN/BOTH consume the wake gesture below. NEVER (the default since 1.1.5.1), 5, 15, 30, 60 minutes, kept in a byte no engine uses, saved
 * with the settings (SCR_CODE). 1.1.5 stored value ^ 3, 0 (its default and every older setting) being 30 MIN; 1.1.5.1
 * reads that 0 as NEVER (the new default: the panel went dark for good on 1.1.5, see lcd.c lcd_power) and keeps the
 * other codes, 30 MIN now 4. Bits 0..2 retain these codes; bits 3..4 select SCREEN (0), LEDS (1), BOTH (2), remembered
 * even with the first timer at NEVER. Bits 5..7 hold ALL DARK's independent NEVER/5/15/30/60 index. Both timers count
 * from the same activity, and ALL DARK, when both are on, must be later. It sleeps the LCD and suppresses every LED,
 * including the first-stage heartbeat. The physical backlight remains powered; the controller probe was removed
 * after a colour regression. PA2, input scanning, audio and MIDI stay enabled. Record size is unchanged;
 * older readers reset new bytes to NEVER.
 * Input is the panel's: a button or key held or pressed, a knob turned (not the editor or MASTER, an analogue pot);
 * WAKE +MIDI (the default since 1.5.5; PANEL: the panel only) also accepts a MIDI IN note-on,
 * USB or TRS, on any channel that plays a track (seq.c midi_seen: the ISR only sets its bit), not clock, CC or SysEx.
 * The press, key or turn that wakes it is swallowed: no note (seq.c kb_asleep), no button, no value, until everything
 * is let go and the knobs rest for SCR_EAT_MS; a MIDI note that wakes it is not: it plays, as every MIDI note does.
 * A dialog, the count-in and the UPDATE MODE countdown keep it on (and wake it); the crash screen, UPDATE and UBOOT wake it at once (lcd_wake_now).
 * Off: lcd_power(0) (DISPOFF, SLPIN) and nothing is drawn. Waking, a frame at a time (never a wait in
 * the loop): 120 ms after the SLPIN, SLPOUT (lcd_power(1)); 120 ms after that one frame redraws everything
 * (ui.force), then DISPON (lcd_power(2)) */
#define ui_scr (settings_dev[27])
/* MENU > ANIM IDLE (1.2, Discussion #135; menu_items.c, ui_input.c idle_leds): bit 0, the LEDs' idle animation, in a
 * byte no engine uses, kept with the settings; 0 in every older setting = off. Bits 1..2: GRAPH (#572, graph_mode); bits
 * 3..7: 0 (room for a delay) */
#define ui_idle (settings_dev[10])
#define SCR_DEF 0u                                     /* NEVER (1.1.5.1; 1.1.5: 30 MIN) */
static const uint8_t SCR_CODE[5] = {0, 2, 1, 4, 7};    /* the stored byte of NEVER 5 15 30 60 MIN (1.1.5: 3 2 1 0 7) */
static const uint8_t SCR_DEC[8] = {0, 2, 1, 0, 3, 0, 0, 4};   /* .. and back (3: 1.1.5's NEVER; 5, 6 unknown) */
#define SCR_EAT_MS 300u
static const uint8_t SCR_MIN[5] = {0, 5, 15, 30, 60};  /* NEVER, minutes */
enum { SCR_ON, SCR_OFF, SCR_WAKE, SCR_SLPOUT, SCR_SHOW };
static struct {
    uint8_t st;                  /* SCR_*: SCR_WAKE asked, SCR_SLPOUT sent, SCR_SHOW the frame that redraws */
    uint8_t eat;                 /* the wake gesture: panel input swallowed (ui_input) */
    uint8_t led_off;             /* SCR_LED_* latches: stay dark across a complete millisecond-clock wrap */
    uint8_t setting;             /* last applied AUTO OFF byte, including a backup/settings import */
    uint8_t recovering;          /* failed power command may have completed late; normalize wake without eating input */
    uint32_t idle;               /* fm1_ms of the last panel input (or blocker) */
    uint32_t t;                  /* fm1_ms of the last panel command (SLPIN, SLPOUT) */
    uint32_t eat_t;              /* fm1_ms of the last swallowed knob detent */
} scrn;
enum { SCR_LED_IDLE = 1u, SCR_LED_ALL = 2u };
static void scr_touch(void) { scrn.idle = fm1_ms; scrn.led_off = 0; }
static void scr_sync(void)
{
    if (scrn.setting == ui_scr)
        return;
    scrn.setting = ui_scr;
    scr_touch();
    if (scrn.st == SCR_OFF)
        scrn.st = SCR_WAKE;
}
static uint32_t scr_idle_get(void) { return SCR_DEC[ui_scr & 7u]; }
static uint32_t scr_mode_get(void)
{
    uint32_t target = (ui_scr >> 3) & 3u;
    return target < 3u ? target : 0u;
}
static uint32_t scr_dark_get(void) { return (ui_scr >> 5) < 5u ? ui_scr >> 5 : 0u; }
static uint32_t scr_get(void)                          /* legacy id 17: 0 NEVER; 1..4 SCREEN, 5..8 LEDS, 9..12 BOTH */
{
    uint32_t time = scr_idle_get();
    return ((ui_scr >> 3) & 3u) < 3u && time ? time + scr_mode_get() * 4u : SCR_DEF;
}
static int scr_write(uint32_t idle, uint32_t mode, uint32_t dark)
{
    if (idle >= NELEM(SCR_MIN) || mode >= 3u || dark >= NELEM(SCR_MIN))
        return 0;
    if (idle && dark && dark <= idle) {
        ui_message("ALL DARK MUST BE LATER");
        return 0;
    }
    ui_scr = (uint8_t)(SCR_CODE[idle] | mode << 3 | dark << 5);
    scrn.setting = ui_scr;
    scr_touch();
    if (scrn.st == SCR_OFF)
        scrn.st = SCR_WAKE;
    return 1;
}
static int scr_idle_put(uint32_t v) { return scr_write(v, scr_mode_get(), scr_dark_get()); }
static int scr_mode_put(uint32_t v) { return scr_write(scr_idle_get(), v, scr_dark_get()); }
static int scr_dark_put(uint32_t v) { return scr_write(scr_idle_get(), scr_mode_get(), v); }
static int scr_put(uint32_t v)                         /* time counts from an accepted change, including the editor's */
{
    v = v < 13u ? v : 0u;
    return scr_write(v ? (v - 1u) % 4u + 1u : 0u, v ? (v - 1u) / 4u : scr_mode_get(), scr_dark_get());
}
static int scr_blocked(void) { return ui.confirm || ui.uboot || seq_counting(); }
static uint32_t scr_limit(void)
{
    return SCR_MIN[scr_idle_get()] * 60000u;
}
static int scr_expired(void)
{
    uint32_t lim = scr_limit();
#if FELUCCA_SCREEN_CAPTURE
    if (scap_holding(fm1_ms)) return 0;
#endif
    return lim && !scr_blocked() && fm1_ms - scrn.idle >= lim;
}
static int scr_dark_active(void)
{
    uint32_t dark;
    scr_sync();
#if FELUCCA_SCREEN_CAPTURE
    if (scap_holding(fm1_ms)) {
        scrn.led_off = 0;
        return 0;
    }
#endif
    dark = scr_dark_get();
    if (!dark || scr_blocked())
        scrn.led_off &= (uint8_t)~SCR_LED_ALL;
    else if (fm1_ms - scrn.idle >= SCR_MIN[dark] * 60000u)
        scrn.led_off |= SCR_LED_ALL;
    return (scrn.led_off & SCR_LED_ALL) != 0u;
}
static int scr_led_dark(void)
{
    int all = scr_dark_active();
    if (!scr_idle_get() || !scr_mode_get() || scr_blocked())
        scrn.led_off &= (uint8_t)~SCR_LED_IDLE;
    else if (scr_expired())
        scrn.led_off |= SCR_LED_IDLE;
    return all || (scrn.led_off & SCR_LED_IDLE) != 0u;
}
static void scr_wake(void)
{
    if (scrn.st == SCR_OFF)
        scrn.st = SCR_WAKE;
    scrn.eat = 1;
}
static void scr_wake_now(void)                         /* main.c: the crash screen, UPDATE, UBOOT */
{
    if (scrn.st != SCR_ON)
        lcd_wake_now();
    if (LCD_FAILED())
        return;
    scrn.st = SCR_ON;
    scrn.recovering = 0;
    scr_touch();
}
static uint8_t mf_seen;          /* 1.5.5 (#208): the MIDI IN notes of this pass (seq.c midi_seen, taken at every pass's
                                  * start: ui_input.c midi_take), bit per track; AUTO SELECT's (midi_follow) */
/* ui_input, every pass: 1 = the pass is swallowed (the screen dark or waking, or the wake gesture going on) */
static int scr_input(uint32_t pressed, uint32_t notes)
{
    uint32_t held = fm1_in.buttons | fm1_in.notes, k;
    int32_t moved = 0;
#if BOARD_SMK37
    uint32_t outer;
    notes |= smk_extkey_activity(&outer);
    held |= outer;
#endif
    scr_sync();
    if (pressed | notes | held | panel_moved)
        scr_touch();
    if (LCD_FAILED() && scrn.st == SCR_OFF && (pressed | notes | held | panel_moved))
        scr_wake();
    panel_moved = 0;
    if (mf_seen && !(ui_prefs2 & (PREF_WAKE_PANEL >> 16))) {     /* +MIDI: a note-on since the last pass keeps it on,
                                                                 * wakes it; nothing swallowed (the note has played) */
        scr_touch();
        if (scrn.st == SCR_OFF)
            scrn.st = SCR_WAKE;
    }
    if (LCD_FAILED() || scrn.recovering) {
        scrn.eat = kb_asleep = 0;                       /* a failed display cannot hold musical input asleep */
#if BOARD_SMK37
        smk_extkeys_asleep = kb_boot_hold;             /* future presses play; queued wake marks stay consumed */
#endif
        return 0;
    }
    if (scrn.st == SCR_ON && !scrn.eat)
        return 0;
    for (k = 0; k < NE; k++)                           /* (every knob's turns go) */
        moved |= panel_enc(k);
    panel_moved = 0;
    if (moved) {
        scrn.eat_t = fm1_ms;
        scr_touch();
    }
    if (pressed | notes | held | (uint32_t)moved)
        scr_wake();
    if (scrn.st != SCR_ON || held || fm1_ms - scrn.eat_t < SCR_EAT_MS)
        return 1;
    scrn.eat = 0;                                       /* all let go, the knobs at rest: input again */
    kb_asleep = 0;
#if BOARD_SMK37
    smk_extkeys_asleep = 0;
#endif
    return 0;
}
/* ui_draw, every frame: 1 = draw it */
static int scr_frame(void)
{
    scr_sync();
    if (scr_blocked()) {                            /* (never dark under these) */
        scr_touch();
        if (scrn.st == SCR_OFF)
            scr_wake();
    }
    switch (scrn.st) {
    case SCR_ON:
        if (!scr_dark_active() && (scr_mode_get() == 1u || !scr_expired()))
            return 1;
        lcd_power(0);
        if (LCD_FAILED())
            return 0;
        scrn.st = SCR_OFF;
        scrn.t = fm1_ms;
        scrn.eat = 1;
#if BOARD_SMK37
        smk_extkeys_asleep = 1;              /* mark new events before audio suppression becomes visible */
#endif
        kb_asleep = 1;
        break;
    case SCR_WAKE:
        if (fm1_ms - scrn.t >= 120u) {
            lcd_power(1);
            if (LCD_FAILED())
                return 0;
            scrn.st = SCR_SLPOUT;
            scrn.t = fm1_ms;
        }
        break;
    case SCR_SLPOUT:
        if (fm1_ms - scrn.t >= 120u) {
            scrn.st = SCR_SHOW;
            ui.force = 1;
            return 1;
        }
        break;
    case SCR_SHOW:
        return 1;
    }
    ui.msg_t = 0;                                      /* (dark: what would have shown is over; a clean page back) */
    ui.msg2[0] = 0;
    ui.hot_t = ui.bpm_t = ui.curve_t = 0;
    return 0;
}
static void scr_shown(void)                            /* after the frame: the redrawn page on */
{
    if (scrn.st != SCR_SHOW)
        return;
    lcd_power(2);
    if (LCD_FAILED())
        return;
    scrn.st = SCR_ON;
    scrn.recovering = 0;
#if FELUCCA_SCREEN_CAPTURE
    /* Explicit capture already touched once at BEGIN. Keep input invalidation
     * separate from the asynchronous wake redraw's completion. */
    if (scap.state == SCAP_WAKING && scap.wake) return;
#endif
    scr_touch();
}

static const page_t *page_over;   /* a quick layer's own four knobs (ui_layer.c), while it edits or draws them */
static const page_t *cur_page(void) { return page_over ? page_over : &PAGES[ui.page]; }

/* Reading roles are chosen by task, independent of the reserved legacy size bit.
 * Value pages keep one focused bank; dense graphs/lists and held layers retain
 * four compact controls. Every surface keeps the full native workspace. */
enum { RK_COMPACT, RK_BANK };
static uint32_t reading_kind(void)
{
    uint32_t g;
    if (ui.layer) return RK_COMPACT;
    if (ui.home) return home_tracks() ? RK_COMPACT : RK_BANK;
    g = cur_page()->graph;
    return g == GR_BROWSE || g == GR_SLOTS || g == GR_USER || g == GR_PATS || g == GR_SONG || g == GR_ROLL ||
           g == GR_SLICES || g == GR_EVENTS || g == GR_TOOLS ? RK_COMPACT : RK_BANK;
}
static int macro_page(void);
/* #572: the panel draws on the 100 px graph scale (GOY) and needs no margin above it: the scope, ADSR, LFO, SCALE, FX,
 * SLICER, INSERT and the engine diagrams. The lists, the roll, MIXER, CHORD, MOD, MACRO's page and FM6's charts (their
 * captions in the margin above the chart) use the panel's full height */
static int panel_scaled(void)
{
    uint32_t g;
    if (ui.home)
        return !home_tracks();
    g = cur_page()->graph;
    if (g == GR_NONE)
        return !macro_page() && !(cur_page()->scope == SC_ENGINE && eng_is(TSEL->eng_req, ENGI_FM6));
    return g == GR_ADSR || g == GR_LFO || g == GR_SCALE || g == GR_FX || g == GR_SLCR || g == GR_INS || g == GR_ARP ||
           g == GR_STEPS;
}
static int bank_tall(void) { return !ui.layer && reading_kind() == RK_BANK && panel_scaled(); }
static uint32_t card_h(void) { return bank_tall() ? CARD_H_TALL : CARD_H; }
static uint32_t graph_y(void) { return Y_LABEL + card_h() + 4u; }
static uint32_t graph_h(void) { return Y_FOOT - 4u - graph_y(); }
static int large_face_has(const char *s)                /* every glyph of s in the sparse L face */
{
    for (; *s; s++)
        if (glyph_at(&AF_L, fold(&AF_L, (uint8_t)*s)) < 0)
            return 0;
    return 1;
}
static int32_t ink_w(const aafont_t *f, const char *s)
{
    int32_t b[4];
    text_ink(f, s, b);
    return b[2] > b[0] ? b[2] - b[0] : 0;
}

/* the quick layers (ui_layer.c): a button held, the keys and KNOB 1..4 are its shortcuts, its map over the page */
enum { LAYER_NONE, LAYER_FX, LAYER_GLO, LAYER_SCL, LAYER_EDIT, LAYER_SEQ, LAYER_REC, LAYER_N };
static void draw_layer(void);
static const char *layer_head(void);
static int layer_locked(void);
static uint32_t layer_leds(uint32_t *br);
static uint32_t layer_btn(void);

/* FM operator pages belong to DIGITAL; they never appear on other instruments (without FELUCCA_FM4: never). SLICES:
 * a SLICE track's (ui_slice.c); LANES / LANES 2 a DRUM track's (its lane levels); FILTER an ANALOG track's; OPERATOR, OP ENV, OPERATOR 2 an FM6
 * track's (its patch's operators, ui_fm6op.c) */
static int page_visible(uint32_t i)
{
    if (PAGES[i].scope == SC_TRACK && PAGES[i].id[0] >= P_LN0 && PAGES[i].id[0] <= P_LN7)
        return eng_is(TSEL->eng_req, ENGI_DRUM);
    if (PAGES[i].id[0] == P_FTYPE)                    /* FILTER (1.5, #104): ANALOG's */
        return eng_of(TSEL->eng_req) == &ENG_ANALOG;
    if (PAGES[i].graph >= GR_FMOP && PAGES[i].graph <= GR_FMENV)
        return eng_is(TSEL->eng_req, ENGI_FM6);
#if FELUCCA_SLICE
    if (PAGES[i].graph == GR_SLICES)
        return eng_of(TSEL->eng_req) == &ENG_SLICE;
#else
    if (PAGES[i].graph == GR_SLICES)
        return 0;
#endif
    return !(PAGES[i].fam == FAM_EDIT && PAGES[i].id[0] >= P_FM1_ATK &&
             PAGES[i].id[0] <= P_FM4_LEVEL) || (FELUCCA_FM4 && TSEL->eng_req == ENGI_DIGITAL);
}

static uint32_t page_first(uint32_t fam)
{
    uint32_t i;
    for (i = 0; i < NPAGES; i++)
        if (PAGES[i].fam == fam)
            return i;
    return 0;
}

/* transient message in the top bar, right of the transport and the BPM: a + b */
static void ui_say(const char *a, const char *b)
{
    uint32_t n;
    str_cpy(ui.msg, a, sizeof ui.msg);
    n = str_len(ui.msg);
    str_cpy(ui.msg + n, b, sizeof ui.msg - n);
    n = str_len(ui.msg);
    ui.msg_t = (uint8_t)(n > 25u ? 90u : 40u + 2u * n);   /* (1.8: longer words stay longer, ~0.7..1.5 s) */
    ui.msg2[0] = 0;
}

static void ui_message(const char *s) { ui_say(s, ""); }
/* a message led by an icon: its first byte (ui_draw.c draw_head draws the icon, then the words) */
#define MSG_NOFILE "\x01"                      /* the no-file icon (ICON_X_NOFILE) */
/* a missing sample (ui_input.c sample_notice): NO SAMPLE (SAMPLE NOT FOUND, the SLICES page's, is 4 px too wide
 * for the header's 130 px after the icon) */
#define MSG_NO_SAMPLE MSG_NOFILE "NO SAMPLE"

static int chain_busy(void) { return chain.running || chain.armed; }
/* Main loop only, with interrupts enabled. PLAY may be consumed between reads;
 * take one coherent snapshot before a flash operation or song preparation. */
static int transport_busy(void)
{
    int busy;
    fm1_irq_off();
    busy = song.playing || chain_busy() || transport_req == 1u || seq_counting();   /* (a count-in: as playing) */
    fm1_irq_on();
    return busy;
}
static void chain_play_ui(void)
{
    uint32_t rc = chain_prepare();
    if (!rc) {
        ui.force = 1;
    } else if (rc >= 3u) {
        char b[8] = "A EMPTY";
        b[0] = (char)('A' + rc - 3u);
        ui_say("PATTERN ", b);
    } else {
        ui_message(rc == 1u ? "ADD A SECTION" : "STOP FIRST");
    }
}


/* parameter locks: a page whose KNOB 1..4 can lock (a track's sound: one of its parameters can be motion; not MOD's
 * slots), the parameter KNOB k locks (ui.plk_src's page, HOME's four), 0xFF = none */
static int lock_page_ok(uint32_t i)
{
    uint32_t k;
    if (i >= NPAGES || (PAGES[i].scope != SC_TRACK && PAGES[i].scope != SC_ENGINE) || PAGES[i].graph == GR_MOD)
        return 0;
    for (k = 0; k < 4u; k++)
        if (PAGES[i].id[k] != 0xFFu && motion_param(PAGES[i].id[k]))
            return 1;
    return 0;
}
static uint32_t lock_id(uint32_t k)
{
    uint32_t id = ui.plk_src && lock_page_ok(ui.plk_src - 1u) ? PAGES[ui.plk_src - 1u].id[k & 3u]
                                                               : eng_of(TSEL->eng_req)->knob[k & 3u];
    return id < P_COUNT && motion_param(id) ? id : 0xFFu;
}

static void ev_enter(void);
/* 1.5 (Discussion #156): MENU > HELP ON: a page entered (here, go_home) shows its hint in the footer for ~2 s
 * (ui_help.c, ui_draw.c draw_foot) */
#define HELP_FRAMES 120u                       /* (~2 s at the UI's ~60 frames a second) */
static int help_on(void) { return (ui_prefs2 & (PREF_HELP >> 16)) != 0u; }
/* 1.5.5 (#208): a MIDI IN note into track k lights its number cushion for MLIT_MS (the header's for the selected track,
 * HOME TRACKS / LEVELS, the MIXER); midi_lit_ms[k]: fm1_ms | 1 of the last (ui_input.c midi_take), 0 none */
#define MLIT_MS 90u
static uint32_t midi_lit_ms[NTRK];
static int midi_lit(uint32_t k) { return midi_lit_ms[k % NTRK] && (fm1_ms | 1u) - midi_lit_ms[k % NTRK] < MLIT_MS; }
static void help_start(void) { ui.help_t = (uint8_t)(help_on() ? HELP_FRAMES : 0u); }
static void page_entered(void)
{
    const page_t *pg = cur_page();
    if (!ui.home && pg->graph == GR_EVENTS)      /* AUTOMATION: + ADD on the SEQ cursor's step */
        ev_enter();
    if (!ui.home && lock_page_ok(ui.page))
        ui.plk_src = (uint8_t)(ui.page + 1u);
    song.seq_mode = !ui.home && pg->fam == FAM_SEQ;
    ui.entry_open = 0;
    ui.hot_t = ui.curve_t = 0;                   /* clear the previous page's emphasis (#572: and its curve) */
    ui.act = pg->graph == GR_USER ? 4u : 0u;     /* the save screen is ready for OCT+ */
    ui.tl_clean = 0;
    help_start();
    ui.force = 1;
}

static int step_on(const step_t *st) { return st->time == ST_NOTE && (st->n || st->hit); }
/* 1.5.1 (#199): a step whose CHANCE, RATCH or NUDGE is off its default: marked on the roll and the grid (ui_graph.c).
 * Not VEL: every recorded step has one */
static int step_detailed(const step_t *st)
{
    return step_chance_v(st) != 100u || step_ratchet(st) > 1u || step_nudge(st) != 0;
}

static void step_clear(step_t *st)
{
    st->n = 0;
    st->time = ST_REST;
    st->flags = 0;
    st->vel = 0;
    st->hit = st->acc = 0;
    st->probability = 0;
}

/* LEN (1.5, Discussions #178, #173): a NOTE step's length on the piano roll is the step and the TIE steps after it
 * (inside LEN, no wrap); SEQ > STEP's KNOB 3 on a note sets it (ui_input.c step_edit). Longer: the steps after it
 * become clean TIEs (a REST or an empty step; it stops at the next step holding notes or hits, a REST's kept ones too,
 * which stays, and at LEN);
 * shorter: its last TIEs become RESTs (step_clear). The steps' locks stay. Returns the length it got */
static uint32_t note_len(const track_t *t, uint32_t i)
{
    uint32_t len = (uint32_t)clamp(t->p[P_SLEN], 1, NSTEP), n = 1;
    while (i + n < len && t->step[i + n].time == ST_TIE)
        n++;
    return n;
}
static uint32_t note_set_len(track_t *t, uint32_t i, uint32_t want)
{
    uint32_t len = (uint32_t)clamp(t->p[P_SLEN], 1, NSTEP), n = note_len(t, i);
    for (; n > want && n > 1u; n--)
        step_clear(&t->step[i + n - 1u]);
    for (; n < want && i + n < len && !t->step[i + n].n && !t->step[i + n].hit; n++) {
        step_clear(&t->step[i + n]);
        t->step[i + n].time = ST_TIE;
    }
    return n;
}

/* ------------------------------------------------------- the DRUM grid --- */
/* SEQ > STEP on a DRUM track is the grid: 8 lanes x the 16 steps of a page. The white keys are the
 * steps of the page shown (a tap toggles the selected lane there), black keys 1..8 select the lane (and play
 * it), black key 9 held is ACC (white keys toggle accents, their LEDs show them), black keys 10 / 11 the page
 * down / up. KNOB 1 STEP, 2 LANE, 3 HIT, 4 ACC edit the cursor step. A sound load never converts the
 * steps: the grid shows a step's notes on their lanes (eng_drum.c step_lanes) and an edit makes the lane its
 * own (grid_own). Live recording on a DRUM track writes hits (seq.c rec_note) */
static int grid_on(void) { return !ui.home && !ui.menu && !ui.confirm && cur_page()->graph == GR_ROLL && drum_track(TSEL); }
/* SEQ > DETAIL (1.5.1, Discussion #199; params.c, between STEP and AUTOMATION): a step page as STEP (the cursor, the
 * roll's keys, the grid's lane and page keys), its knobs the cursor step's CHANCE RATCH NUDGE VEL (ui_input.c sd_turn),
 * its panel their lanes (ui_graph.c graph_detail). No state of its own: the page is what says so */
static int detail_on(void)
{
    return !ui.home && !ui.menu && !ui.confirm && cur_page()->scope == SC_STEP && str_eq(cur_page()->title, "DETAIL");
}
/* GLO > SONG (1.2): the white keys A B C D (A3 B3 C4 D4, white places 2..5: seq.c song_key) set the selected cell's slot;
 * they do not sound there, the other keys play as anywhere (seq.c keyboard_block: song.grid 3) */
static int song_keys_on(void) { return !ui.home && !ui.menu && !ui.confirm && !ui.layer && cur_page()->graph == GR_SONG; }

/* black key place p (seq.c key_place) held, 0 = not */
static int black_held(uint32_t p)
{
    uint32_t k;
    for (k = 0; k < 27u; k++)
        if (key_black(k) && key_place(k) == p)
            return (int)(((fm1_in.notes & ~kb_layer) >> k) & 1u);
    return 0;
}

/* lane l of step s from now on is its hit alone: the step's lane notes become hits (nothing sounds different),
 * a note of another pitch on the lane (a low tom 41) becomes the lane's own */
static void grid_own(step_t *s, uint32_t l)
{
    uint32_t k, j = 0;
    step_to_grid(s);
    for (k = 0; k < s->n; k++)
        if (drum_lane(s->note[k]) == l)
            s->hit |= (uint8_t)(1u << l);
        else
            s->note[j++] = s->note[k];
    for (k = j; k < 4u; k++)
        s->note[k] = 0;
    s->n = (uint8_t)j;
}

/* lane l of step i: on 1, off 0, toggled 2 */
static void grid_hit(track_t *t, uint32_t i, uint32_t l, uint32_t on)
{
    step_t *s = &t->step[i % NSTEP];
    uint32_t b = 1u << (l % NLANE);
    if (on == 2u)
        on = !(step_lanes(s) & b);
    if (s->time != ST_NOTE) {                    /* a REST or a TIE: an empty step (nothing to turn off) */
        if (!on)
            return;
        step_clear(s);
        s->time = ST_NOTE;
    }
    grid_own(s, l % NLANE);
    if (on) {
        s->hit |= (uint8_t)b;
    } else {
        s->hit &= (uint8_t)~b;
        s->acc &= (uint8_t)~b;
        if (!s->n && !s->hit)
            step_clear(s);
    }
}

/* the accent of lane l at step i (on 1, off 0, toggled 2); an accent on an empty lane adds the hit */
static void grid_acc(track_t *t, uint32_t i, uint32_t l, uint32_t on)
{
    step_t *s = &t->step[i % NSTEP];
    uint32_t b = 1u << (l % NLANE);
    if (on == 2u)
        on = !(step_accents(s) & b);
    if (on)
        grid_hit(t, i, l, 1);
    if (!(step_lanes(s) & b))
        return;
    grid_own(s, l % NLANE);
    if (s->flags & SF_ACCENT) {                  /* a step accent: each hit's own from now on */
        s->acc |= s->hit;
        s->flags &= (uint8_t)~SF_ACCENT;
    }
    s->acc = (uint8_t)(on ? s->acc | b : s->acc & ~b);
}

/* SEQ cursor: wraps inside the pattern length, the bank follows, a step entry ends */
static void cursor_set(int32_t c)
{
    int32_t len = TSEL->p[P_SLEN] > 0 ? TSEL->p[P_SLEN] : 1;
    ui.cursor = (uint8_t)((c % len + len) % len);
    ui.bank = (uint8_t)(ui.cursor / 16u);
    ui.entry_open = 0;
}

static void cursor_fix(void)                           /* LEN got shorter: onto the last step */
{
    if (ui.cursor >= (uint32_t)TSEL->p[P_SLEN])
        cursor_set(TSEL->p[P_SLEN] - 1);
}

/* COLOR's value v (the menu, the editor): a built-in palette, or CUSTOM when one is stored */
static void palette_choose(uint32_t v)
{
    if (v >= palette_n())                              /* (CUSTOM with none stored: nothing changes) */
        return;
    if (v >= NPALETTES) {
        ui_cpal_flags |= CPAL_ACTIVE;
    } else {
        ui_cpal_flags &= (uint8_t)~CPAL_ACTIVE;
        settings.palette = v;
    }
    palette_apply();
    ui.force = 1;
}

/* SEQ > STEP / DETAIL follows the play position (1.6, #242, Discussion #238): a melodic pattern longer than the 16
 * steps on the screen shows the bank the playhead is in while the transport plays (ui.bank only: the cursor, the
 * pattern and the saved project are untouched; DRUM's grid keeps its bank, its keys edit what the grid shows). The
 * roll is left alone ("held") from the moment a knob moves the cursor or edits the cursor's step, or step entry has the
 * keys: the bank goes back to the cursor's, so what is being edited stays on the screen. Following starts again after
 * FOLLOW_MS without that, or once the playhead has gone one pass round the pattern, whichever is first. The transport
 * stopped, another track, or the roll left: nothing held any more */
#define FOLLOW_MS 3000u
static struct {
    uint32_t t;                                        /* fm1_ms of the last touch of the cursor's step */
    uint16_t prev, steps;                              /* the playhead at the last poll, the steps it has gone since */
    uint8_t hold;
} follow;

static void follow_hold(void)
{
    follow.hold = 1;
    follow.t = fm1_ms;
    follow.prev = TSEL->seq_idx;
    follow.steps = 0;
    ui.bank = (uint8_t)(ui.cursor / 16u);
}

/* every pass of ui_input() */
static void follow_poll(void)
{
    uint32_t len = (uint32_t)TSEL->p[P_SLEN], want;
    if (ui.home || ui.menu || ui.confirm || cur_page()->graph != GR_ROLL || drum_track(TSEL)) {
        follow.hold = 0;
        return;
    }
    if (!song.playing) {
        follow.hold = 0;
        ui.bank = (uint8_t)(ui.cursor / 16u);            /* stopped edits must be on the visible bank */
        return;
    }
    if (len <= 16u)
        return;
    if (ui.entry_open)                                 /* step entry has the keys: stay at the cursor */
        follow_hold();
    if (follow.hold) {
        uint32_t idx = TSEL->seq_idx;
        follow.steps = (uint16_t)(follow.steps + (idx + len - follow.prev) % len);
        follow.prev = (uint16_t)idx;
        if (fm1_ms - follow.t < FOLLOW_MS && follow.steps < len)
            return;
        follow.hold = 0;
    }
    want = TSEL->seq_idx / 16u;
    if (want * 16u < len && want != ui.bank)
        ui.bank = (uint8_t)want;
}

static void note_name(char *b, uint32_t n)
{
    str_cpy(b, N_NOTE[n % 12u], 4);
    fmt_int(b + str_len(b), (int32_t)(n / 12u) - 1);
}

/* a page button tapped (1.2, Discussion #153: SEQ STEP <-> AUTOMATION, GLO SONG (its only page: GLOBAL became HOME's
 * CLOCK, SYSTEM went to the MENU), SAVE USER -> PRESETS -> PHRASES -> PROJECT -> TOOLS (1.5, #173: PRESETS second; up
 * to 1.4.1 the last); HOME: home_tap). From another
 * family the family's page shown last (SAVE: USER); one that is not the family's any more (a page that moved, as GLOBAL
 * and SYSTEM in 1.2), or not shown for this track, gives the family's first. rev (#176: OCT- held over the
 * tap, ui_input.c page_tap): the same family's previous shown page, the first one wrapping to the last */
static void open_family_dir(uint32_t fam, uint32_t rev)
{
    if (!ui.home && cur_page()->fam == fam) {          /* same button again: next page */
        uint32_t n, i = ui.page;
        for (n = 0; n < NPAGES; n++) {                 /* (at most one lap: a family of one shown page stays) */
            i = (i + (rev ? NPAGES - 1u : 1u)) % NPAGES;
            if (PAGES[i].fam == fam && page_visible(i)) break;
        }
        ui.page = (uint8_t)i;
    } else if (fam == FAM_SAVE) {
        uint32_t i;
        for (i = 0; i < NPAGES; i++)
            if (PAGES[i].graph == GR_USER) break;
        ui.page = (uint8_t)i;                         /* SAVE enters the sound save screen directly */
    } else {
        uint32_t i = ui.fam_last[fam];
        ui.page = (uint8_t)(i && i < NPAGES && PAGES[i].fam == fam && page_visible(i) ? i : page_first(fam));
    }
    ui.fam_last[fam] = ui.page;
    ui.home = 0;
    page_entered();
}

static void open_family(uint32_t fam) { open_family_dir(fam, 0); }

static void go_home(void)
{
    ui.home = 1;
    ui.plk_src = 0;                              /* (parameter locks: HOME's four) */
    ui.entry_open = 0;
    ui.hot_t = ui.curve_t = 0;
    song.seq_mode = 0;
    ui.force = 1;
    help_start();
}

/* HOME tapped (1.2): HOME -> MIXER (up to 1.1.5 GLO's first page) -> CLOCK (up to 1.1.5 GLO > GLOBAL) -> HOME; from any
 * other page HOME. HOME's pages are FAM_TRK's, in PAGES order, always from the first (none remembered). Held: the menu
 * (ui_input) */
static void home_tap(void)
{
    uint32_t i = ui.page + 1u;
    if (ui.home) {
        ui.fam_last[FAM_TRK] = 0;                     /* (open_family: the family's first, the MIXER) */
        open_family(FAM_TRK);
    } else if (cur_page()->fam == FAM_TRK && i < NPAGES && PAGES[i].fam == FAM_TRK) {
        open_family(FAM_TRK);                         /* (on HOME's page again: the next one) */
    } else {
        go_home();
    }
}

/* MENU > CONTROL > SELECT PAGE (1.5.5, Discussion #188): the SELECT knob steps the pages of the family shown, a detent
 * each: right as a tap of the family's button does, left back, round (the pages that show for the track's engine);
 * HOME, MIXER and CLOCK are one round, as HOME's taps go. A family of one page (GLO's SONG) stays */
static void page_turn(int32_t dir)
{
    uint32_t fam = ui.home ? (uint32_t)FAM_TRK : cur_page()->fam, i, m = 0, at = 0;
    uint8_t ring[NPAGES + 1u];                          /* the round: page indices, 0xFF HOME */
    if (fam == FAM_TRK)
        ring[m++] = 0xFFu;
    for (i = 0; i < NPAGES; i++)
        if (PAGES[i].fam == fam && page_visible(i)) {
            if (!ui.home && i == ui.page)
                at = m;
            ring[m++] = (uint8_t)i;
        }
    if (m < 2u)
        return;
    i = ring[(at + (dir > 0 ? 1u : m - 1u)) % m];
    if (i == 0xFFu) {
        go_home();
        return;
    }
    ui.page = (uint8_t)i;
    ui.fam_last[fam] = ui.page;
    ui.home = 0;
    page_entered();
}

/* ------------------------------------------------------- track setup --- */
static int seq_is_empty(const track_t *t)
{
    uint32_t i;
    for (i = 0; i < NSTEP; i++)
        if (t->step[i].n || t->step[i].hit)
            return 0;
    return 1;
}

/* One-step UNDO of a load. A sound load (a factory or user preset, an engine jump, TOOLS INIT, the
 * editor's PRESET / G_ENGSEL / UP_LOAD) changes the sound only; a pattern load (SAVE > PHRASES) changes
 * the steps and the pattern parameters only. Each first copies the track as it was; SAVE held 0.7 s
 * swaps back what the loads changed (held again: the loads again), so steps recorded after a sound
 * load, or a sound edited after a pattern load, stay as they are. One copy for all tracks: the last
 * load wins. Loads in a row on one track with nothing changed in between (the PRESETS knob through the
 * list, one pattern after the other, an editor audition) keep the copy from before the first, so the
 * undo goes back past the whole browse. Not snapshotted: power-on, projects.
 * 1.1.5: a lock or automation edit by hand (a step held and a knob turned, a step's locks cleared, SEQ > AUTOMATION)
 * takes the copy too (UNDO_MOT: SAVE held puts the track's motion back, the sound and the steps stay; motion_undo_take).
 * A sound load keeps the track's motion on the parameters every engine has (load_end, motion.c motion_sound_loaded);
 * a pattern load drops it all (the steps it was on are gone) */
enum { UNDO_SOUND = 1, UNDO_PAT = 2, UNDO_MOT = 4, UNDO_EUCLID = 8 }; /* EUCLID: cancellable preview owns this copy */
static struct {
    uint8_t trk;                 /* track + 1, 0 = nothing to undo */
    uint8_t keep;                /* the track is as the last load left it (undo.after): a next load keeps the copy */
    uint8_t what;                /* UNDO_SOUND | UNDO_PAT: what the loads since the copy changed (undo_swap) */
    uint8_t eng, preset, user, patn;
    uint8_t fm6_slot;            /* the track's FM6 patch and its SLOT (eng_fm6.c): an edited or a project's */
    uint8_t fm6[FP_SIZE + 1u];   /* patch is the track's own, not a factory one */
    int16_t p[P_COUNT];
    step_t step[NSTEP];
    motion_store_t motion_backup; /* one track only, swaps with the shared event pool on undo */
    uint32_t after;              /* track_sig right after the last load */
    uint32_t pat;                /* pat_sig[] of the copy */
    uint32_t from_h;             /* pat_from_h[], pat_from[] of the copy (the header's slot letter) */
    uint8_t from;
    uint32_t t_ms;               /* time of the last load (the editor's SETs after it belong to it) */
} undo __attribute__((section(".pool")));   /* (main loop only: off the audio code's .bss) */
static uint8_t undo_depth;       /* loads nest (an engine jump loads its first preset): the outer one counts;
                                  * felucca_init / project_load raise it to take no copy at all */
static uint32_t pat_sig[NTRK];   /* steps_sig of the pattern the last pattern load put into each track: such
                                  * steps, untouched, are replaced by the next pattern without asking */
static uint8_t pat_last[NTRK];   /* that pattern's list index + 1, 0 = none */
/* the header's slot letter (ui_draw.c head_slot): the PROJECT slot each track's working pattern came from (the last
 * PROJECT load or save: 1..4 = A..D; 0 none: power-on, a PHRASES pattern, the editor's restore) and pat_from_sig() of
 * it then: an edit since shows the letter with a mark */
static uint8_t pat_from[NTRK];
static uint32_t pat_from_h[NTRK];
static uint8_t load_from;        /* a sound load (the outer one): the engine before it (load_end) */
static uint8_t load_mo;          /* .. the track's motion paused while the sound changes: bit 0 set, bit 1 it was ON */

static uint32_t fnv(uint32_t h, const void *p, uint32_t n)
{
    const uint8_t *b = (const uint8_t *)p;
    while (n--)
        h = (h ^ *b++) * 16777619u;
    return h;
}
static uint32_t steps_sig(const track_t *t) { return fnv(2166136261u, t->step, sizeof t->step); }
static uint32_t track_sig(const track_t *t)      /* the sound (an FM6 track's patch too), the steps */
{
    uint8_t id[3] = {t->eng_req, t->preset, t->user};
    uint32_t h = fnv(fnv(steps_sig(t), t->p, sizeof t->p), id, 3), k = trk_index(t);
    h = fnv(h, fm6_patch[k], sizeof fm6_patch[k]); /* (a patch the editor sent between two loads) */
    for (uint32_t j = 0; j < motion.count; j++)
        if ((motion.event[j].place >> 6) == k) h = fnv(h, &motion.event[j], sizeof motion.event[j]);
    return h ^ ((motion.on >> k) & 1u);
}
static uint32_t motion_sig(const track_t *t)     /* the track's motion only (the sound moves while it plays) */
{
    uint32_t h = 2166136261u, k = trk_index(t);
    for (uint32_t j = 0; j < motion.count; j++)
        if ((motion.event[j].place >> 6) == k) h = fnv(h, &motion.event[j], sizeof motion.event[j]);
    return h ^ ((motion.on >> k) & 1u);
}
/* the track's pattern as a song plays it from a slot: the steps, LEN DIV SWING GATE, QUANTIZE, the automation (the
 * editable ones: while a song plays the header shows the section's slot instead) */
static uint32_t pat_from_sig(const track_t *t)
{
    int16_t q = t->p[P_SQNT];
    uint32_t h = fnv(fnv(steps_sig(t), &t->p[P_SLEN], 4u * sizeof t->p[0]), &q, sizeof q);
    return h ^ motion_sig(t);
}
static void pat_from_set(uint32_t slot)             /* every track's pattern is slot's now (1..4), 0 none */
{
    for (uint32_t k = 0; k < NTRK; k++) {
        pat_from[k] = (uint8_t)slot;
        pat_from_h[k] = pat_from_sig(&trk[k]);
    }
}

/* load_begin, the copy taken: a pattern load drops the track's motion (its steps go); a sound load pauses it (PLAY
 * OFF while the sound changes under it) and load_end keeps what still means the same (motion_sound_loaded) */
static void load_motion_hold(track_t *t, uint32_t what)
{
    if (what & UNDO_PAT) {
        motion_reset(t);
        load_mo = 0;
        return;
    }
    load_from = t->eng_req;
    load_mo = (uint8_t)(1u | (motion_enabled(t) ? 2u : 0u));
    motion_set_enabled(t, 0);
}

/* MOMENTARY (ui_input.c mom_turn: LFO held, the knobs' changes go back when it is let go): the values turned, where
 * they are (a track's p[], song.g[]) and what they were. In the main loop's pool (no .bss) */
#define MOM_N 8u
#define MOM_ST_READY 1u                          /* mom.st: LFO held, nothing turned yet */
#define MOM_ST_KEPT 2u                           /* .. OCT+ kept them */
#define MOM_ST_N 2u                              /* .. MOM_ST_N + n: n values held */
static struct {
    uint8_t n;                                    /* values held, 0 = none */
    int16_t *vp[MOM_N];
    int16_t v[MOM_N];
    uint8_t kept;                                 /* OCT+ kept them, LFO still held: the header says KEPT */
    uint8_t st;                                   /* the header's status (ui_input.c mom_status; ui_draw.c mom_head) */
} mom __attribute__((section(".pool")));
static void mom_restore(void)                     /* LFO let go: every value back */
{
    while (mom.n) {
        mom.n--;
        *mom.vp[mom.n] = mom.v[mom.n];
    }
}
static void mom_back(const track_t *t)            /* a sound load into t (0: a project): its values back first */
{
    uint32_t i, k = 0;
    for (i = 0; i < mom.n; i++)
        if (!t || (mom.vp[i] >= t->p && mom.vp[i] < t->p + P_COUNT) || (mom.vp[i] >= song.g && mom.vp[i] < song.g + G_COUNT)) {
            *mom.vp[i] = mom.v[i];                /* (a global: back too, before the load's undo copy) */
        } else {
            mom.vp[k] = mom.vp[i];
            mom.v[k++] = mom.v[i];
        }
    mom.n = (uint8_t)k;
    mom.kept = 0;
}
static void load_begin(track_t *t, uint32_t what)
{
    uint32_t i = trk_index(t);
    if (what & UNDO_SOUND) {
        mom_back(t);                              /* (MOMENTARY: the sound as it was, then the load) */
        drum_mute[i] = 0;                         /* (1.4.1: the lanes' mutes go with the sound) */
    }
    if (undo_depth++)
        return;
    motion_restore(t);
    if (undo.keep && undo.trk == i + 1u && !(undo.what & UNDO_MOT) && track_sig(t) == undo.after) {
        undo.what |= (uint8_t)what;               /* browsing on: the copy from before the first load stays */
        load_motion_hold(t, what);
        return;
    }
    undo.trk = (uint8_t)(i + 1u);
    undo.what = (uint8_t)what;
    undo.eng = t->eng_req;
    undo.preset = t->preset;
    undo.user = t->user;
    memcpy(undo.p, t->p, sizeof undo.p);
    memcpy(undo.step, t->step, sizeof undo.step);
    memcpy(undo.fm6, fm6_patch[i], FP_SIZE);
    undo.fm6_slot = fm6_slot[i];
    undo.pat = pat_sig[i];
    undo.from = pat_from[i];
    undo.from_h = pat_from_h[i];
    undo.patn = pat_last[i];
    motion_snapshot_track(t, &undo.motion_backup);
    load_motion_hold(t, what);
}

static void load_end(track_t *t)
{
    if (--undo_depth)
        return;
    if (load_mo & 1u) {                           /* a sound load: the motion on the common parameters stays */
        (void)motion_sound_loaded(t, load_from, t->eng_req);
        if ((load_mo & 2u) && motion_count(t))
            motion_set_enabled(t, 1);
        load_mo = 0;
    }
    motion_rebase(t);
    undo.after = track_sig(t);
    undo.keep = 1;
    undo.t_ms = fm1_ms;
}

/* the editor's SET right after a load on the selected track (an audition: G_ENGSEL, then the patch's
 * values): part of that load, the copy from before it stays */
static void load_extend(track_t *t)
{
    if (undo.keep && undo.trk == trk_index(t) + 1u && !(undo.what & UNDO_MOT) && fm1_ms - undo.t_ms < 1500u) {
        undo.after = track_sig(t);
        undo.t_ms = fm1_ms;
    }
}

/* 1.1.5: a lock / automation edit by hand on track t is about to happen: the undo copy of the track as it is (as
 * ui_tools.c tl_undo_take, UNDO_MOT: the swap puts back its motion only). A knob turned on (the same tag, not 0:
 * the same knob of the same gesture), on the same track, nothing else changed and less than 1.5 s apart, shares the
 * copy from before its first detent; tag 0 (an add, a delete, a clear, a kind) always takes its own.
 * motion_undo_done after each */
static uint32_t undo_mot_tag;
/* what an edit's copy compares (undo.after): the motion; with the steps (UNDO_PAT: step_undo_take) the steps too */
static uint32_t edit_sig(const track_t *t) { return undo.what & UNDO_PAT ? motion_sig(t) ^ steps_sig(t) : motion_sig(t); }
static void edit_undo_take(track_t *t, uint32_t tag, uint32_t what)
{
    uint32_t i = trk_index(t);
    if (tag && tag == undo_mot_tag && undo.keep && undo.trk == i + 1u && undo.what == what &&
        edit_sig(t) == undo.after && fm1_ms - undo.t_ms < 1500u)
        return;
    undo_mot_tag = tag;
    undo.trk = (uint8_t)(i + 1u);
    undo.what = (uint8_t)what;
    undo.eng = t->eng_req;
    undo.preset = t->preset;
    undo.user = t->user;
    memcpy(undo.p, t->p, sizeof undo.p);
    memcpy(undo.step, t->step, sizeof undo.step);
    memcpy(undo.fm6, fm6_patch[i], FP_SIZE);
    undo.fm6_slot = fm6_slot[i];
    undo.pat = pat_sig[i];
    undo.from = pat_from[i];
    undo.from_h = pat_from_h[i];
    undo.patn = pat_last[i];
    motion_snapshot_track(t, &undo.motion_backup);
    undo.keep = 0;
}
static void motion_undo_take(track_t *t, uint32_t tag) { edit_undo_take(t, tag, UNDO_MOT); }
/* 1.2: a step's CHANCE / RATCH edited on SEQ > AUTOMATION (ui_events.c): the swap puts back the steps (and LEN DIV
 * SWING GATE, as copied) and the motion, the sound stays. motion_undo_done after each, as for a lock */
static void step_undo_take(track_t *t, uint32_t tag) { edit_undo_take(t, tag, UNDO_MOT | UNDO_PAT); }
static void motion_undo_done(track_t *t)
{
    undo.after = edit_sig(t);
    undo.keep = 1;
    undo.t_ms = fm1_ms;
}

/* SAVE held: what the loads changed (undo.what) and the copy change places, so held again = the loads
 * again. The sound: engine, preset and its parameters (not param_kept); the pattern: the steps and LEN
 * DIV SWING GATE. The mix (LEVEL PAN MUTE) stays: no load changes it */
static void undo_swap(void)
{
    track_t *t;
    uint32_t i;
    char b[16] = {'T', 0, ' ', 0};
    if (!undo.trk) {
        ui_message("NOTHING TO UNDO");
        return;
    }
    t = &trk[(undo.trk - 1u) % NTRK];
    motion_restore(t);
    motion_store_t current_motion;
    motion_snapshot_track(t, &current_motion);
    if (motion_replace_track(t, &undo.motion_backup) != 0) {
        ui_message("AUTOMATION FULL");
        return;
    }
    undo.motion_backup = current_motion;
    fm1_irq_off();                                /* the audio ISR must not see half a sound */
    if (undo.what & UNDO_SOUND) {                 /* the copy's sound back (sound.c: nested in this window) */
        uint8_t e = t->eng_req, pr = t->preset, u = t->user;
        int16_t p[P_COUNT];
        for (i = 0; i < P_COUNT; i++) {
            p[i] = undo.p[i];
            if (!param_kept(i))
                undo.p[i] = t->p[i];
        }
        t->user = undo.user;
        sound_install(t, undo.eng, undo.preset, p, 0, SND_PANIC);
        undo.eng = e;
        undo.preset = pr;
        undo.user = u;
    }
    if (undo.what & UNDO_PAT) {
        uint32_t ps = pat_sig[trk_index(t)];
        uint8_t pn = pat_last[trk_index(t)];
        pat_sig[trk_index(t)] = undo.pat;
        undo.pat = ps;
        pat_last[trk_index(t)] = undo.patn;
        undo.patn = pn;
        pn = pat_from[trk_index(t)];
        ps = pat_from_h[trk_index(t)];
        pat_from[trk_index(t)] = undo.from;
        pat_from_h[trk_index(t)] = undo.from_h;
        undo.from = pn;
        undo.from_h = ps;
        for (i = P_SLEN; i <= P_SGATE; i++) {
            int16_t v = t->p[i];
            t->p[i] = undo.p[i];
            undo.p[i] = v;
        }
        for (i = 0; i < NSTEP; i++) {
            step_t s = t->step[i];
            t->step[i] = undo.step[i];
            undo.step[i] = s;
        }
    }
    fm1_irq_on();
    if (undo.what & UNDO_SOUND) {                 /* FM6: the track's patch as it was (edited, a project's, a
                                                   * converted DIGITAL sound), not a factory one */
        uint32_t tr = trk_index(t);
        uint8_t v[FP_SIZE + 1u], sl = fm6_slot[tr];
        memcpy(v, fm6_patch[tr], FP_SIZE);
        fm6_set_patch(tr, undo.fm6);
        fm6_slot[tr] = undo.fm6_slot;             /* (fm6_poll: the patch stays) */
        fm6_own_ok &= (uint8_t)~(1u << tr);
        memcpy(undo.fm6, v, FP_SIZE);
        undo.fm6_slot = sl;
    }
    undo.keep = 0;                                /* the next load copies the track as it is now */
    if (t == TSEL)
        sync_reload = 1;
    b[1] = (char)('1' + trk_index(t));             /* (1.8: and what came back) */
    str_cpy(b + 3, undo.what & UNDO_SOUND ? (undo.what & UNDO_PAT ? "SOUND+STEPS" : "SOUND") :
            undo.what & UNDO_PAT ? "STEPS" : "AUTO", sizeof b - 3u);
    ui_say("UNDO/REDO ", b);
    ui.force = 1;
}

/* a 16-step pattern (PATTERNS[] format, user presets too) into steps 1..16, the rest empty, LEN 16 */
static void load_pat16(track_t *t, const uint8_t *note, const uint8_t *flags)
{
    uint32_t i;
    for (i = 0; i < NSTEP; i++) {
        step_t *s = &t->step[i];
        uint8_t n = i < 16u ? note[i] : 0, fl = i < 16u ? flags[i] : 0;
        s->note[0] = n;
        s->n = n ? 1 : 0;
        s->time = (fl & 4u) ? ST_TIE : n ? ST_NOTE : ST_REST;
        s->flags = n ? (fl & (SF_ACCENT | SF_SLIDE | SF_RATCH)) : 0;
        s->vel = n ? 96 : 0;
        s->hit = s->acc = 0;
        s->probability = 0;
        if (drum_track(t))                           /* a DRUM track: the lanes' notes as its grid */
            step_to_grid(s);
    }
    t->p[P_SLEN] = 16;
}

/* a 16-step drum grid (user presets of version 3: lane hits, their accents) into steps 1..16, the rest empty,
 * LEN 16 */
static void load_grid16(track_t *t, const uint8_t *hit, const uint8_t *acc)
{
    uint32_t i;
    for (i = 0; i < NSTEP; i++) {
        step_t *s = &t->step[i];
        step_clear(s);
        if (i < 16u && hit[i]) {
            s->time = ST_NOTE;
            s->hit = hit[i];
            s->acc = acc[i] & hit[i];
        }
    }
    t->p[P_SLEN] = 16;
}

static void track_defaults_steps(track_t *t)
{
    uint32_t i;
    motion_reset(t);
    for (i = 0; i < NSTEP; i++)
        step_clear(&t->step[i]);
}

/* SAVE > PHRASES: the factory patterns (PATTERNS[], "01".."13"), then the used user presets that hold
 * one ("U07"): list index n. Loading one replaces the track's steps 1..16 (the rest cleared) and LEN;
 * a user preset's pattern brings its stored LEN (at most 16), DIV, SWING and GATE too. The notes are
 * loaded as they are: the patterns are written for the register of their kind of sound, DRUM and
 * SLICE patterns are drum and slice numbers, and SCL TRANS / OCT transpose what plays */
static uint32_t pat_count(void) { return NPATTERNS + up_pat_count(); }

static void pat_label(uint32_t n, char *tag, char *name)   /* tag: 4 bytes ("01", "U07"), name: 13 */
{
    if (n < NPATTERNS) {
        tag[0] = (char)('0' + (n + 1u) / 10u);
        tag[1] = (char)('0' + (n + 1u) % 10u);
        tag[2] = 0;
        str_cpy(name, PATTERNS[n].name, 13);
    } else {
        uint32_t k = up_pat_nth(n - NPATTERNS);
        up_slot_label(tag, k);
        up_name(k, name);
    }
}

static void pat_load(track_t *t, uint32_t n)
{
    load_begin(t, UNDO_PAT);
    if (n < NPATTERNS)
        load_pat16(t, PATTERNS[n].note, PATTERNS[n].flags);
    else
        up_pat_load(t, up_pat_nth(n - NPATTERNS));
    pat_sig[trk_index(t)] = steps_sig(t);
    pat_last[trk_index(t)] = (uint8_t)(n + 1u);
    pat_from[trk_index(t)] = 0;                     /* (a phrase: no PROJECT slot) */
    load_end(t);
    ui.force = 1;
}

/* a pattern load would throw away steps of the user's (recorded, edited, from a project): ask first */
static int pat_needs_confirm(const track_t *t)
{
    return !seq_is_empty(t) && steps_sig(t) != pat_sig[trk_index(t)];
}

static uint32_t pat_pick(void)                   /* ui.ppick inside the list (user presets may be gone) */
{
    uint32_t n = pat_count();
    return ui.ppick < n ? ui.ppick : n - 1u;
}

/* SAVE > PHRASES LOAD: pattern n into track t, "LOADED 03 MELODY" */
static void pat_load_ui(track_t *t, uint32_t n)
{
    char tag[4], nm[13], b[20];
    pat_label(n, tag, nm);
    pat_load(t, n);
    str_cpy(b, tag, sizeof b);
    str_cpy(b + str_len(b), " ", 2);
    str_cpy(b + str_len(b), nm, sizeof b - str_len(b));
    ui_say("LOADED ", b);
}

/* (the track's own settings, param_kept, and the preset aliases, preset_orig: sound.c, the Sound install) */

/* the presets of engine e that browsing shows before preset k (k = npresets: all of them) */
static uint32_t preset_rank(const engine_t *e, uint32_t k)
{
    uint32_t i, n = 0;
    if (e->presets != SMP_PRESET_TABLE)
        return k;
    for (i = 0; i < k; i++)
        n += preset_orig(e, i) == i;
    return n;
}

#define preset_shown(e) (eng_of(e)->npresets - (eng_of(e)->presets == SMP_PRESET_TABLE ? SMP_NALIAS : 0u))

#if !FELUCCA_FM4
/* DIGITAL (engine 1, retired): t's sound = p, values as DIGITAL has them, converted to FM6 with a patch of its own
 * (fm4_convert.c) and installed (sound.c; SLOT OWN or the factory patch it equals). Every path that brings a DIGITAL
 * sound into a track ends here: a track never keeps engine 1. flags: SND_PANIC or 0 */
static void fm4_apply(track_t *t, int16_t *p, uint32_t flags)
{
    uint8_t v[FP_SIZE + 1u];
    uint32_t pr = fm4_convert(p, v);
    sound_install(t, ENGI_FM6, pr, p, v, flags | SND_ALL);
}
static void fm4_track(track_t *t)                     /* t holds a DIGITAL sound (engine 1): convert it */
{
    int16_t p[P_COUNT];
    memcpy(p, t->p, sizeof p);
    fm4_apply(t, p, 0);
}
/* DIGITAL preset k (a stored preset number of engine 1: the editor's PRESET, SET G_ENGSEL, an old project's
 * power-on sound): its sound as a preset load sets it, converted. The sound only (not the steps, not param_kept) */
static void fm4_load_preset(track_t *t, uint32_t k)
{
    int16_t p[P_COUNT];
    load_begin(t, UNDO_SOUND);
    t->user = 0;
    if (t == TSEL)
        sync_reload = 1;
    memcpy(p, t->p, sizeof p);
    sound_defaults(p);
    fm4_preset_values(p, k);
    fm4_apply(t, p, SND_PANIC);
    load_end(t);
}
#endif

/* a factory sound (sound.c sound_load_factory) as one undoable load of the panel's: the user preset slot gone, the
 * editor told; what sounds is released (MONO/POLY or the engine may change) */
static void factory_load(track_t *t, uint32_t ei, uint32_t pi, uint32_t flags)
{
    load_begin(t, UNDO_SOUND);
    t->user = 0;
    if (t == TSEL)
        sync_reload = 1;
    sound_load_factory(t, ei, pi, flags | SND_PANIC);
    load_end(t);
}

static void set_engine_of(track_t *t, uint32_t ei);
/* preset pi of the engine the track asked for: the sound only (not the steps, not param_kept) */
static void apply_preset_to(track_t *t, uint32_t pi)
{
    FM1_ASSERT_THREAD();                        /* preset loads are main-loop work (#428) */
#if !FELUCCA_FM4
    if (t->eng_req == ENGI_DIGITAL) {
        fm4_load_preset(t, pi);
        return;
    }
#endif
    if (t->eng_req == ENGI_SAMPLE && pi == SMP_SET_PERC) {   /* SAMPLE preset 4 was PERC (retired, a stored */
        set_engine_of(t, ENGI_DRUM);                  /* number: the editor's PRESET, a favourite): DRUM's kit */
        return;                                       /* (core.h drum_from_perc) */
    }
    factory_load(t, t->eng_req, pi, 0);
}

/* the engine's defaults and its first preset, installed as one sound (sound.c: the audio side sees the old engine
 * with its values or the new one with its own, voice.c engine_block, never one with the other's) */
static void set_engine_of(track_t *t, uint32_t ei)
{
#if !FELUCCA_FM4
    if (ei == ENGI_DIGITAL) {             /* DIGITAL (retired): its first preset, as FM6 */
        fm4_load_preset(t, 0);
        return;
    }
#endif
    if (!eng_ok(ei))                                  /* (#212: an engine this build lacks: the sound stays) */
        return;
    factory_load(t, ei, 0, SND_EDIT_DEF);
}

static void apply_preset(uint32_t pi) { apply_preset_to(TSEL, pi); }
static void set_engine(uint32_t ei) { set_engine_of(TSEL, ei); }

/* CLEAN INIT (1.5.5, #190): the engine's basic sound, nothing added: E1..E8 at the engine's own defaults (not its first
 * preset's), every other sound value at its default (TP: no FX sends DIST CHO DLY REV, INSERT OFF, no LFO or ENV DEST
 * amounts, the MOD slots off, no GLIDE, POLY), the ENV neutral (ATK 0, SUS 100 %, a short REL; DRUM: its kit's own, so
 * the hits ring as they should); FM6 the init voice (one sine carrier, ALGORITHM 1; SLOT OWN). What INIT keeps stays
 * (param_kept: LEVEL PAN MUTE, ARP, SCL, the sequence, SLICER, the chord keys); the steps stay. One undo, as INIT
 * (SAVE held). INIT itself is unchanged (the engine's defaults and its first preset). The preset number: INIT's (the
 * first preset; an engine without presets keeps it). One install (sound.c), as INIT's */
#define CLEAN_REL 40                                   /* ~18 ms */
static void clean_engine_of(track_t *t)
{
    uint32_t ei = t->eng_req, i, fm6 = eng_is(ei, ENGI_FM6);
    const engine_t *e = eng_of(ei);
    int16_t p[P_COUNT];
    uint8_t v[FP_SIZE + 1u];
#if !FELUCCA_FM4
    if (ei == ENGI_DIGITAL) {                         /* (retired: it becomes FM6, fm4_track) */
        set_engine_of(t, ei);
        return;
    }
#endif
    if (!eng_ok(ei))                                  /* (#212: an unavailable engine: its sound is kept) */
        return;
    load_begin(t, UNDO_SOUND);
    t->user = 0;
    if (t == TSEL)
        sync_reload = 1;
    memcpy(p, t->p, sizeof p);
    sound_defaults(p);
    for (i = 0; i < 8u; i++)
        p[P_E0 + i] = e->edit[i].def;
    if (eng_is(ei, ENGI_DRUM) && e->npresets) {
        p[P_ATK] = e->presets[0].env[0];
        p[P_DEC] = e->presets[0].env[1];
        p[P_SUS] = e->presets[0].env[2];
        p[P_REL] = e->presets[0].env[3];
    } else {
        p[P_ATK] = 0;
        p[P_SUS] = TP[P_SUS].max;
        p[P_REL] = CLEAN_REL;
    }
    if (fm6)                                          /* the init voice as the track's own patch (SLOT: OWN) */
        fm6_unpack(FM6_INIT, v);
    sound_install(t, ei, e->npresets ? preset_orig(e, 0) : t->preset, p, fm6 ? v : 0, SND_PANIC);
    load_end(t);
}
static void clean_engine(void) { clean_engine_of(TSEL); }

/* MIDI Program Change (1.5.1, #179 by renebohne): program n on track t, as the PRESETS list numbers the engine's sounds
 * from 0: its n-th preset, the aliases skipped (preset_orig), loaded as from there (the track's own settings kept, one
 * undo for a run of them). DRUM: its n-th KIT, the retired variants skipped (enum_orig); FM6: its presets (F1..F8),
 * then the voice bank's B1..B32 through SLOT as the knob loads them (fm6_poll; the rest of the sound stays), an empty
 * one ignored. A program past the last is ignored, not wrapped: a number is always the same sound */
static volatile uint8_t *const mpc_io = ui.mpc;
static void midi_pc_load(track_t *t, uint32_t n)
{
    uint32_t e = t->eng_req, k;                   /* (#212: an unavailable engine has no presets: ignored) */
    if (eng_is(e, ENGI_DRUM)) {
        const param_desc_t *d = param_desc_of(e, P_E0);
        for (k = (uint32_t)d->min; k <= (uint32_t)d->max && (enum_orig(d, (int32_t)k) != (int32_t)k || n--); k++)
            ;
        if (k <= (uint32_t)d->max)
            t->p[P_E0] = (int16_t)k;
        return;
    }
    if (n >= preset_shown(e)) {
        int32_t s = (int32_t)(FM6_OWN + 1u + n - preset_shown(e));
        if (eng_is(e, ENGI_FM6) && fm6_bank_slot(s) >= 0 && fm6_slot_ok(s))
            t->p[P_E7] = (int16_t)s;
        return;
    }
    for (k = 0; preset_orig(eng_of(e), k) != k || n--; k++)   /* the n-th shown preset */
        ;
    apply_preset_to(t, k);
}
static void midi_pc_poll(void)                       /* main loop (ui_input) */
{
    uint32_t k, v;
    for (k = 0; k < NTRK; k++) {
        if (!ui.mpc[k])
            continue;
        fm1_irq_off();                               /* (the ISR may note another meanwhile) */
        v = ui.mpc[k];
        ui.mpc[k] = 0;
        fm1_irq_on();
        midi_pc_load(&trk[k], v & 127u);
        ui.force = 1;
    }
}

static void track_defaults(track_t *t)
{
    uint32_t i;
    for (i = 0; i < P_E0; i++)
        t->p[i] = TP[i].def;
    track_defaults_steps(t);
}

/* switch engine (its defaults + first preset) and say so */
static void select_engine(uint32_t e)
{
    set_engine(e);
    ui_say("ENGINE ", eng_of(TSEL->eng_req)->name);
    ui.force = 1;
}

/* the presets of every engine (in ENGINE_ORDER), then the used user presets, as one list (the PRESETS knob and the
 * PRESETS page browse it) */
static uint32_t preset_all_pos(uint32_t *total)          /* list index of the selected track's preset */
{
    uint32_t n = 0, cur = 0, e, r;
    for (r = 0; r < NENG_SHOWN; r++) {                  /* (engines.c ENGINE_ORDER) */
        const engine_t *en = ENGINES[e = eng_vis(r)];
        if (e == TSEL->eng_req)
            cur = n + preset_rank(en, preset_orig(en, TSEL->preset % (en->npresets ? en->npresets : 1u)));
        n += preset_shown(e);
    }
    if (user_of(TSEL) < UP_SLOTS)
        cur = n + up_rank(user_of(TSEL));
    *total = n + up_count();
    return cur;
}

/* list index n (< total) -> engine, *k its preset; ENG_USER = user preset, *k its slot */
static uint32_t preset_all_at(uint32_t n, uint32_t *k)
{
    uint32_t e = 0, i, r;
    for (r = 0; r < NENG_SHOWN && n >= preset_shown(eng_vis(r)); r++)
        n -= preset_shown(eng_vis(r));
    if (r == NENG_SHOWN) {
        *k = up_nth(n);
        return ENG_USER;
    }
    e = eng_vis(r);
    for (i = 0; preset_orig(ENGINES[e], i) != i || n--; i++)    /* the n-th shown preset */
        ;
    *k = i;
    return e;
}

/* PRESETS > LIST (KNOB 4): ALL, FAV (favorites.filter, as up to 1.1.5), or one category (1.2, Discussion #90: BASS ..
 * OTHER, category.c): the list mode 0 ALL, 1 FAV, 1 + CAT_* a category. The category is kept with the settings in a
 * byte no engine uses (ui_lcat: 0 = none; firmware before reads ALL there, and favorites.filter stays 0 / 1 for it, the
 * editor and backups); the PRESETS knob and page browse that list */
#define ui_lcat (settings_dev[11])
#define LIST_N (1u + CAT_N)                              /* ALL FAV BASS LEAD PAD PLUCK KEYS DRUM FX OTHER */
#define LIST_RECENT LIST_N                               /* then RECENT (#80): this session's last sounds, RAM only */
#define RECENT_N 8u
/* RECENT: the last RECENT_N sounds loaded (newest first), by identity: a factory preset (engine, preset) or a user slot
 * (e = ENG_USER, k = slot, fp = up_fp of its sound when loaded: a deleted / replaced / restored slot no longer matches and
 * is skipped). Main loop only, never saved (no flash write, no protocol field). on: the browser shows it (the persisted
 * LIST is left as it was); hold: a load made by browsing it does not reorder it */
static struct { uint8_t n, on, hold, e[RECENT_N], k[RECENT_N]; uint16_t fp[RECENT_N]; } recent __attribute__((section(".pool")));
static uint32_t list_mode(void)
{
    return recent.on ? LIST_RECENT : favorites.filter ? 1u : ui_lcat && ui_lcat < CAT_N ? 1u + ui_lcat : 0u;
}
static uint32_t list_set(uint32_t m)                     /* 1 = the persisted LIST changed (settings_later) */
{
    uint8_t f = favorites.filter, c = ui_lcat;
    recent.on = m == LIST_RECENT;
    if (recent.on)
        return 0;
    favorites.filter = m == 1u;
    ui_lcat = (uint8_t)(m >= 2u && m < LIST_N ? m - 1u : 0u);
    return f != favorites.filter || c != ui_lcat;
}
static const char *list_name(uint32_t m)
{
    return m == 0u ? "ALL" : m == 1u ? "FAV" : m == LIST_RECENT ? "RECENT" : CAT_NAME[(m - 1u) % CAT_N];
}
/* the category of list entry e, k (preset_all_at: ENG_USER = user preset k) */
static uint32_t sound_cat(uint32_t e, uint32_t k) { return e == ENG_USER ? up_cat(k) : preset_cat(e, k); }
static int list_keep(uint32_t e, uint32_t k)
{
    uint32_t m = list_mode();
    return m == 1u ? favorite_has(e, k) : m ? sound_cat(e, k) == m - 1u : 1;
}
/* the category of the sound track t plays: its user preset's, else its factory preset's (the NAME screen's default) */
static uint32_t track_cat(const track_t *t)
{
    uint32_t u = user_of(t);
    return u < UP_SLOTS ? up_cat(u) : preset_cat(t->eng_req, t->preset);
}

static int recent_ok(uint32_t i)                         /* entry i still names a loadable sound */
{
    uint32_t e = recent.e[i], k = recent.k[i], r;
    if (e == ENG_USER)
        return up_used(k) && up_fp(k) == recent.fp[i];
    for (r = 0; r < NENG_SHOWN; r++)
        if (eng_vis(r) == e)
            return k < ENGINES[e]->npresets && preset_orig(ENGINES[e], k) == k;
    return 0;
}
static void recent_id(uint32_t *e, uint32_t *k)          /* the selected track's sound: (engine | ENG_USER, preset | slot) */
{
    uint32_t u = user_of(TSEL);
    *e = u < UP_SLOTS ? ENG_USER : TSEL->eng_req;
    *k = u < UP_SLOTS ? u : preset_orig(eng_of(*e), TSEL->preset % (eng_of(*e)->npresets ? eng_of(*e)->npresets : 1u));
}
static void recent_note(void)                            /* after a sound load of the selected track */
{
    uint32_t e, k, i, n = 1;
    uint8_t ne[RECENT_N], nk[RECENT_N];
    uint16_t nf[RECENT_N];
    if (recent.hold)
        return;
    recent_id(&e, &k);
    ne[0] = (uint8_t)e;
    nk[0] = (uint8_t)k;
    nf[0] = (uint16_t)(e == ENG_USER ? up_fp(k) : 0u);
    for (i = 0; i < recent.n && n < RECENT_N; i++)       /* the rest: valid, not this sound again (the oldest drops out) */
        if (recent_ok(i) && !(recent.e[i] == e && recent.k[i] == k)) {
            ne[n] = recent.e[i];
            nk[n] = recent.k[i];
            nf[n++] = recent.fp[i];
        }
    memcpy(recent.e, ne, sizeof ne);
    memcpy(recent.k, nk, sizeof nk);
    memcpy(recent.fp, nf, sizeof nf);
    recent.n = (uint8_t)n;
}
static uint32_t recent_at(uint32_t n, uint32_t *k)       /* n-th valid entry -> engine (ENG_USER = user), *k; else UP_SLOTS */
{
    uint32_t i;
    for (i = 0; i < recent.n; i++)
        if (recent_ok(i) && !n--) {
            *k = recent.k[i];
            return recent.e[i];
        }
    *k = UP_SLOTS;
    return ENG_USER;
}
static uint32_t recent_pos(uint32_t *total)              /* its length; the current sound's place (= total if absent) */
{
    uint32_t e, k, i, n = 0, pos = RECENT_N;
    recent_id(&e, &k);
    for (i = 0; i < recent.n; i++)
        if (recent_ok(i)) {
            if (recent.e[i] == e && recent.k[i] == k && pos == RECENT_N)
                pos = n;
            n++;
        }
    *total = n;
    return pos == RECENT_N ? n : pos;
}

static uint32_t preset_pos(uint32_t *total)
{
    if (list_mode() == LIST_RECENT)
        return recent_pos(total);
    uint32_t all, current = preset_all_pos(&all), n = 0, pos = 0xFFFFFFFFu;
    if (!list_mode()) { *total = all; return current; }
    for (uint32_t i = 0; i < all; i++) {
        uint32_t k, e = preset_all_at(i, &k);
        if (!list_keep(e, k)) continue;
        if (i == current) pos = n;
        n++;
    }
    *total = n;
    return pos == 0xFFFFFFFFu ? n : pos; /* current sound need not be in the list */
}
static uint32_t preset_at(uint32_t n, uint32_t *k)
{
    uint32_t all;
    if (list_mode() == LIST_RECENT)
        return recent_at(n, k);
    if (!list_mode()) return preset_all_at(n, k);
    preset_all_pos(&all);
    for (uint32_t i = 0; i < all; i++) {
        uint32_t e = preset_all_at(i, k);
        if (list_keep(e, *k) && !n--) return e;
    }
    *k = UP_SLOTS;
    return ENG_USER;
}
static int preset_favorite(void)
{
    uint32_t k = user_of(TSEL);
    return favorite_has(k < UP_SLOTS ? ENG_USER : TSEL->eng_req,
                                        k < UP_SLOTS ? k : TSEL->preset);
}
/* #197: a settings change made by a knob (PRESETS > LIST, the FAV mark on PRESETS and in the EDIT layer) is written
 * later, as MENU's are when it closes: a write erases a flash sector with the interrupts off (~40 ms), which stops the
 * LED scan (every LED but one column's goes dark: a flash of the whole panel) and the audio. Written once the view it
 * was made in is left (another page, HOME, a layer opened or let go, the MENU) or after SET_LATER_MS without panel
 * input (ui.c scrn.idle; the autosave's wait), never on every detent; settings_poll still waits for the transport */
#define SET_LATER_MS 10000u
static struct { uint8_t on, page, home, layer; } set_later __attribute__((section(".pool")));   /* (.bss as before) */
static void settings_later(void)
{
    set_later.on = 1;
    set_later.page = ui.page;
    set_later.home = ui.home;
    set_later.layer = ui.layer;
}
static void settings_later_poll(void)                  /* ui_input, every pass */
{
    if (set_later.on && (set_later.page != ui.page || set_later.home != ui.home || set_later.layer != ui.layer ||
                         ui.menu || fm1_ms - scrn.idle >= SET_LATER_MS)) {
        set_later.on = 0;
        settings_save();
    }
}
static void preset_mark(int on)
{
    uint32_t k = user_of(TSEL);
    if (favorite_set(k < UP_SLOTS ? ENG_USER : TSEL->eng_req, k < UP_SLOTS ? k : TSEL->preset, on)) {
        ui.force = 1;
        settings_later();
    }
}

/* the pattern the selected track's sound suggests: its index in the SAVE > PHRASES list, or -1. A factory
 * preset's PAT(n); a user preset that holds a pattern: that one ("U07") */
static int32_t preset_pat_hint(void)
{
    const engine_t *e = eng_of(TSEL->eng_req);
    uint32_t u = user_of(TSEL);
    if (u < UP_SLOTS)
        return up_has_pat(u) ? (int32_t)(NPATTERNS + up_pat_rank(u)) : -1;
    if (!e->npresets)
        return -1;
    u = e->presets[TSEL->preset % e->npresets].pat;
    return u && u <= NPATTERNS ? (int32_t)u - 1 : -1;
}

static void preset_hinted(void)                     /* after a sound load: SAVE > PHRASES starts at the suggested pattern */
{
    int32_t h;
    if ((h = preset_pat_hint()) >= 0)
        ui.ppick = (uint8_t)h;
    ui.force = 1;
}

static void preset_go(uint32_t n)                    /* load list index n into the selected track (the sound only) */
{
    uint32_t k, e = preset_at(n, &k);
    if (e == ENG_USER) {
        if (up_load(k))
            return;
    } else {
        if (e != TSEL->eng_req)
            select_engine(e);
        apply_preset(k);
    }
    preset_hinted();
    recent_note();
}

/* the EDIT layer's KNOB 2 (ui_layer.c): the selected track's engine only: its factory presets, then the used user presets
 * made with it (slot order). List index of the current sound; *total the length */
static uint32_t eng_list_pos(uint32_t *total)
{
    const engine_t *en = eng_of(TSEL->eng_req);
    uint32_t e = TSEL->eng_req, np = preset_shown(e), u = user_of(TSEL), k, n = 0;
    uint32_t cur = np ? preset_rank(en, preset_orig(en, TSEL->preset % en->npresets)) : 0u;   /* (#124: the aliases
                                        * skipped, as on PRESETS: SAMPLE 1 loads as 0, so counting it stuck KNOB 2) */
    for (k = 0; k < UP_SLOTS; k++)
        if (up_used(k) && up_engine(k) == e) {
            if (k == u)
                cur = np + n;
            n++;
        }
    *total = np + n;
    return cur;
}

static void eng_list_step(int32_t direction)         /* the next / previous sound of the engine (wraps) */
{
    uint32_t total, cur = eng_list_pos(&total), e = TSEL->eng_req, np = preset_shown(e), k, n;
    if (total < 2u)
        return;
    n = (cur + (direction > 0 ? 1u : total - 1u)) % total;
    if (n < np) {
        for (k = 0; preset_orig(eng_of(e), k) != k || n--; k++)   /* the n-th shown preset */
            ;
        apply_preset(k);
    } else {
        n -= np;
        for (k = 0; k < UP_SLOTS; k++)
            if (up_used(k) && up_engine(k) == e && !n--) {
                up_load(k);
                break;
            }
    }
    preset_hinted();
    recent_note();
}

static void preset_step(int32_t direction)
{
    uint32_t total, cur = preset_pos(&total);
    if (!total) { ui_message(list_mode() == 1u ? "NO FAVORITES" : "NO SOUNDS IN LIST"); return; }
    recent.hold = list_mode() == LIST_RECENT;          /* (browsing RECENT keeps its order) */
    preset_go(cur >= total ? (direction > 0 ? 0 : total - 1) :
              (cur + (direction > 0 ? 1u : total - 1u)) % total);
    recent.hold = 0;
}

static uint32_t sound_list_rows(void) { return 5u; }
/* The selected name leaves five display rows. FAV and a category use a bounded window, not a repeating carousel.
 * Return total for an empty row; a current sound not in the list shows the start. */
static uint32_t preset_visible(uint32_t cur, uint32_t total, uint32_t row)
{
    uint32_t first, last, rows = sound_list_rows(), middle = rows / 2u;
    if (!total || row >= rows) return total;
    if (!list_mode())
        return (cur + total * 4u + row - middle) % total;
    first = cur < total && cur > middle ? cur - middle : 0u;
    last = total > rows ? total - rows : 0u;
    if (first > last) first = last;
    return first + row < total ? first + row : total;
}

/* HOME: the track KNOB k edits (MENU > HOME LEVELS, 1.5: track k; else the selected one) and what: the engine's four
 * main parameters, or (LEVELS) the track's LEVEL, as the GLO layer's knobs */
static track_t *home_trk(uint32_t k) { return home_levels() ? &trk[k & 3u] : TSEL; }
static const param_desc_t *home_param(uint32_t k, int16_t **vp)
{
    uint32_t id = home_levels() ? (uint32_t)P_LEVEL : eng_of(TSEL->eng_req)->knob[k & 3u];
    *vp = &home_trk(k)->p[id];
    return track_desc(home_trk(k), id);
}

/* Display words only: the engine's DESC labels, parameter IDs and saved values remain stable. */
static const char *ui_param_label(const track_t *t, uint32_t id)
{
#if FELUCCA_PROFILE_ENGINE_14 && FELUCCA_ENG_OMIT != 14
    if (eng_is(t->eng_req, ENGI_MACRO)) {
        if (id == P_E0) return "MODEL";
        if (id == P_E1 || id == P_E2) return MACRO_LABEL[(uint32_t)t->p[P_E0] % MAC_NSHAPE][id - P_E1];
    }
#endif
    return track_desc(t, id)->label;
}
/* Compact value cells (MOD, AUTOMATION) have less room than control labels. */
static const char *ui_param_short_label(const track_t *t, uint32_t id)
{
#if FELUCCA_PROFILE_ENGINE_14 && FELUCCA_ENG_OMIT != 14
    if (eng_is(t->eng_req, ENGI_MACRO) && id == P_E2) {
        uint32_t shape = (uint32_t)t->p[P_E0] % MAC_NSHAPE;
        if (shape == MAC_WAVE) return "TEX";
        if (shape == MAC_FBFM) return "MPIT";
    }
#endif
    return ui_param_label(t, id);
}
static const char *ui_mod_dst_name(const track_t *t, int32_t v)
{
#if FELUCCA_PROFILE_ENGINE_14 && FELUCCA_ENG_OMIT != 14
    if (MD_ENGINE(v) && eng_is(t->eng_req, ENGI_MACRO))
        return ui_param_short_label(t, P_E0 + (uint32_t)(v - MD_E1));
#endif
    return mod_dst_name(t, v);
}
static void ui_param_format(const track_t *t, uint32_t id, const param_desc_t *d, int32_t v, char *val, const char **unit)
{
    (void)t; (void)id;
    /* FBFM's COLOR is one semitone per detent; 127 reaches +63.992 st, displayed rounded to +64.
     * The editor still exposes its original 0..127 control, and modulation/locks use that range. */
#if FELUCCA_PROFILE_ENGINE_14 && FELUCCA_ENG_OMIT != 14
    if (eng_is(t->eng_req, ENGI_MACRO) && (uint32_t)t->p[P_E0] % MAC_NSHAPE == MAC_FBFM && id == P_E2)
        param_format(&ENG_MACRO.edit[3], v == 127 ? 64 : v - 64, val, unit);
    else
#endif
        param_format(d, v, val, unit);
}

/* select track i (KNOB 1 on TRACKS, the editor): its sound, pages and pattern from now on */
static void track_select(uint32_t i)
{
    if (i >= NTRK || i == song.sel)
        return;
    song.sel = (uint8_t)i;
    ui.entry_open = 0;
    ui.hot_t = ui.curve_t = 0;
    ui.ev_keep = 0;                              /* (AUTOMATION: a row kept at its default was the other track's) */
    ui.cursor = 0;
    ui.bank = 0;
    follow.hold = 0;                             /* (1.6, #242: the roll follows the new track's playhead) */
    sync_reload = 1;
    ui.force = 1;
}

#include "ui_slice.c"                             /* EDIT > SLICES: SLICE's slices by hand (an action page too) */
#include "ui_events.c"                            /* SEQ > AUTOMATION: locks, events, CHANCE, RATCH as a list (an action page) */
#include "midi_learn.c"                           /* MIDI LEARN (1.5): GLO + D4, a knob, a CC */

/* ---------------------------------------------------- action pages --- */
/* Pages whose purpose is an action (SAVE > USER, PHRASES, PROJECT, TOOLS, EDIT > SLICES, SEQ > AUTOMATION): the knobs pick,
 * OCT+ does it, OCT- cancels the picked action or goes HOME (ui_input.c). There OCT- / OCT+ do not
 * shift the octave */
static int go_id(uint32_t id) { return id == G_LOAD || id == G_SAVE || id == G_CLRSEQ || id == G_INITSND; }

static uint32_t act_cols(void)                   /* the columns that are actions, a bit each; 0 = not such a page */
{
    const page_t *pg = cur_page();
    uint32_t c, m = 0;
    if (ui.home)
        return 0;
    if (pg->graph == GR_EVENTS) return 16u;     /* AUTOMATION: no knob is an action; OCT+ by the row (ev_oct) */
    if (pg->graph == GR_TOOLS) return 15u;
    if (pg->graph == GR_SONG)
        return 1u;                               /* PLAY / STOP (also the PLAY button) */
    if (pg->graph == GR_PATS)
        return 2u;                               /* LOAD */
    if (pg->graph == GR_USER)
        return 14u;                              /* LOAD ERASE SAVE */
    if (pg->graph == GR_SLICES)
        return slice_page_ok() ? 12u : 0u;       /* SPLIT JOIN (a SLICE track only) */
    if (pg->graph == GR_SLOTS)
        return 14u;                              /* PROJECT: ERASE (1.5.5, #199) LOAD SAVE */
    if (pg->scope == SC_GLOBAL)
        for (c = 0; c < 4u; c++)
            if (go_id(pg->id[c]))
                m |= 1u << c;
    return m;
}

/* the action OCT+ does: its column + 1, 0 = none picked yet (PHRASES has LOAD only) */
static uint32_t act_col(void)
{
    if (!ui.home && cur_page()->graph == GR_SONG) return 1u;
    if (!ui.home && cur_page()->graph == GR_EVENTS) return 5u;
    return !ui.home && cur_page()->graph == GR_PATS ? 2u : ui.act;
}

static const char *act_name(uint32_t c)          /* column c's action (the footer hint) */
{
    static const char *const UP_GO[3] = {"LOAD", "ERASE", "SAVE"};
    uint32_t id = cur_page()->id[c & 3u];
    if (cur_page()->graph == GR_EVENTS) return ev_act_name();
    if (cur_page()->graph == GR_TOOLS) {
        static const char *const actions[] = {"CLEAR", "INIT", "DELETE", "CLEAR"};
        return (c & 3u) == 1u && ui.tl_clean ? "CLEAN" : actions[c & 3u];   /* (1.5.5: KNOB 2 on: CLEAN INIT) */
    }
    if (cur_page()->graph == GR_SONG)
        return song.playing || chain_busy() ? "STOP" : "PLAY";
    if (cur_page()->graph == GR_PATS)
        return "LOAD";
    if (cur_page()->graph == GR_USER)
        return UP_GO[(c + 2u) % 3u];
    if (cur_page()->graph == GR_SLICES)
        return c == 3u ? "JOIN" : "SPLIT";
    if (cur_page()->graph == GR_SLOTS && (c & 3u) == 1u)
        return "ERASE";
    return id == G_CLRSEQ ? "CLEAR" : id == G_INITSND ? "INIT" : id == G_LOAD ? "LOAD" : "SAVE";
}

/* the picked action would do something now (OCT+ breathes): another pattern, a used slot, stopped for
 * a flash write, steps to clear */
static int act_ready(void)
{
    uint32_t c = act_col(), s = song.sel, id;
    if (!c--)
        return 0;
    if (cur_page()->graph == GR_EVENTS) return ev_act_ready();
    if (cur_page()->graph == GR_TOOLS)                  /* one case per column: CLEAR PAT, INIT, DELETE ROW, CLEAR SONG */
        return !chain_busy() && (c == 0u ? !seq_is_empty(TSEL) || motion_count(TSEL) : c == 1u ? 1 :
                                 c == 2u ? ui.song_row < chain_config.count : chain_config.count != 0u);
    if (cur_page()->graph == GR_SONG)
        return song.playing || chain_busy() || chain_config.count;
    if (cur_page()->graph == GR_PATS)
        return pat_last[s] != pat_pick() + 1u || steps_sig(TSEL) != pat_sig[s];
    if (cur_page()->graph == GR_USER)
        return c == 3u ? !song.playing : up_used(ui.uslot) && (c == 1u || !song.playing);
#if FELUCCA_SLICE
    if (cur_page()->graph == GR_SLICES)
        return slice_act_ready(c);
#endif
    if (cur_page()->graph == GR_SLOTS && c == 1u)       /* PROJECT ERASE: a used slot, stopped */
        return !song.playing && project_used((uint32_t)song.g[G_SLOT] - 1u);
    id = cur_page()->id[c & 3u];
    if (id == G_LOAD)                               /* display only: project_load validates the slot afresh */
        return graph_project_used((uint32_t)song.g[G_SLOT] - 1u);
    if (id == G_SAVE)
        return !song.playing;
    if (id == G_CLRSEQ)
        return !seq_is_empty(TSEL);
    return 1;
}
