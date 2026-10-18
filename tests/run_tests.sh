#!/bin/sh
# SPDX-License-Identifier: GPL-3.0-only
# Copyright (C) 2026 Leo Kuroshita (@kurogedelic), Hügelton Instruments
# Host tests of the Felucca sources (no hardware). Run from the repo root after ./build.sh:
#   tests/run_tests.sh
#
# Regression suite (tests/regress.c, tests/target_budget.py; details at the top of regress.c):
#   golden renders  every engine x preset, the GM map on DRUM, voice modes, FX sends, a 4-track mix: one hash
#                   each in tests/golden.txt. A change of the sound fails with the list of renders.
#   health          clipping, DC, peak level, voices free after the release, silence at the end.
#   CPU             instructions / sample per preset and mix (tests/cpu_baseline.txt, +25 %; macOS arm64 only, other
#                   hosts/compiler versions have separate files, e.g. Linux via perf_event_open, else skipped), ns printed; again
#                   built -Os -fno-vectorize -fno-slp-vectorize as the target is (-Os, no SIMD; -O2 here vectorises
#                   with NEON: PHYS BOWED 1236 vs 1729) against tests/cpu_baseline_os.txt, the goldens too;
#                   target: loop instructions of the render functions in the pi32v2 disassembly
#                   (tests/target_budget.txt, +10 %; exact, static).
#   voices          the budget of 8, steal fades, MONO / LEGATO / UNISON keep their note, the VOICE cap,
#                   no hanging notes on any MIDI / key routing.
# FELUCCA-ENGINES (engines/tests, MIT): ANALOG LOFI TRIO WHEEL NOISE on their own host against their golden renders,
#                   once with their own tables and once with build/gen's (the two generators agree).
# ENGINE MEMORY (tests/union_test.c, 1.5): engine switches on a part (every pair and A -> B -> A of the engines that
#                   share the part's state region, with others), hashed against 1.4's (tests/union_golden.txt).
#                   Owner checks (tests/arena_test.c, FELUCCA_ARENA_CHECK=1, host only): negative fixtures and fixed-seed
#                   random runs; union_test is also run checked (and under ASan/UBSan).
# ENGINE IDS (tests/engid_test.c, #212): the id space (64) apart from the engines a build has: INFO's 49 01 bitmap,
#                   FAV_GET / FAV_SET's user marker (127, and the old one: INFO's count), favourites past id 13 in the
#                   settings (PER6), ids this build lacks kept in projects, user presets and backups (N/A, silent, never
#                   another engine). Again with placeholder engine 14 and DRUM/NOISE/FM6/SLICE omitted (10..13),
#                   including serializers, unavailable UI controls, owner checks and matching union workloads.
# UI renders (tests/ui_render.c): every screen in every palette from the real drawing code: the layout lint (no text
#                   off the screen, cut, hidden, overlapping or spilling out of its cell / card; only free text
#                   ellipsised), GREY gray, MONO neutral, the draw cost, the text audit (build/ui_new/text_audit.tsv);
#                   PNGs of GREY MONO GREEN PAPER NIGHT in build/ui_new (tests/ui_render.py), the findings in build/ui_new/report.txt;
#                   FM6's 32 algorithm charts as drawn (no box overlapping, no route through a box or crossing another), again
#                   on OPERATOR with each operator picked and its frequency text at its widest (1.2, #76);
#                   DIGITAL's screens (its algorithm charts, OP ENV) with FELUCCA_FM4=1 too (build/ui_fm4: lint, GREY, MONO);
#                   every frame of the rolling digits (lint, GREY, MONO), their filmstrips in build/ui_slot;
#                   the alignment: every text / icon / keycap meant to be centred, or on its neighbours' line, by its
#                   ink against its box (cells, chips, buttons, rows, knobs, the roll's strip, the keycaps' pills), every
#                   screen in FLAT and LINE and every palette, over every value it can show; 1 px off or more fails
#                   (build/ui_new/align.txt). MENU > LARGE: every screen again (FLAT, LINE, every palette) and the page / value
#                   sweep with the tall cards, the same lint and alignment; sheet_LARGE_GREY.png, sheet_LARGE_MONO.png.
# UI (tests/ui_test.c): the UI sources against stub display / buttons / knobs: sound loads keep the steps and
#                   the track's ARP / SCL / SLICER, the SAVE > PHRASES loader and its REPLACE? dialog, the
#                   one-step undo of both (SAVE held), REC on TRACKS / SEQ / ARP, STEP and ARP while recording,
#                   MIDI IN ROUT, saves refused while playing and the OVERWRITE? dialog, MUTE on TRACKS KNOB 1, FM6's operator
#                   pages (each byte alone, SLOT OWN, the sound, undo, the macros, projects / user presets),
#                   the DRUM grid (keys, knobs, LEDs, pages, live recording into it, BEAT from PATTERNS).
# DRUM STRESS (tests/drumfuzz_test.c, #211): ASan / UBSan, a synth sequence playing while the DRUM grid is edited at random
#                   (keys, locks, lanes, HIT / ACC, EDIT, undo, SEQ TOOLS, engines, kits, the MENU), the audio ISR emulated
#                   anywhere in the main loop; also with a SONG playing; a step over 5 s is a hang.
# Audio / persistence / editor: the real C paths against simulated DMA and NOR flash: bounded overload
#                   fades, shared-voice limits, deferred settings and retries, failed-save rollback, the autosave
#                   (1.2: when it writes, the power-on restore, damaged copies, a write cut short, wear over a session),
#                   malformed transfers, transport-stop timeouts, MIDI and UART recovery; the MENU settings over the
#                   editor (MENU_DESC / MENU_SET: every item, clamping, unknown ids, saving, USB SERIAL applied later).
# FM6 BANK (tests/fm6bank_test.c, 1.4.1): the voice bank (src/fm6_vbank.c) and its editor commands against simulated NOR:
#                   written whole and read back, its sectors (0xE7000, staged in the autosave's older copy, nothing else
#                   touched), a power cut after any programmed byte or in any erase (the old bank or the new one, the
#                   autosave kept), a wrong CRC, an autosave between requests, SLOT B1..B32 loading the exact records,
#                   empty bank slots skipped / refused, projects and user presets keeping a bank voice, stored SLOT values
#                   (projects, user presets, motion) loading as before.
# CHORD (tests/chord_test.c): the chord keys (src/chord.c): diatonic triads / sevenths of several scales and roots,
#                   the fixed shapes and voicings (at most 4 notes), names, MONO plays the root, a release ends
#                   exactly what its key / MIDI note started, recording, the ARP, MIDI IN, kits ignore CHRD.
# FUN10 (tests/fun10_test.c, 1.2): LFO 2 (SYNC one cycle per note value at several tempi and on the external clock, OFF bit
#                   for bit as before; TRIG NOTE / FREE; POL UNI 0..+1, the matrix's AMP), NUDGE (live recording keeps a
#                   note's time, QUANTIZE ON plays as before, OFF plays the nudges late and early once a pass, never twice
#                   with live notes, RATCH on its start, nudges 0 play the same either way, a tempo change of the external
#                   clock, SEQ > AUTOMATION's QUANTIZE and NUDGE rows, STEP steps held + PRESETS), 128 motion records, FUN10 round trip, FUN9 /
#                   FUN8 / FUN7 as 1.1 / 1.0 wrote them (tests/old_pack.h) loading exactly, user presets of 99 / 103.
# RATCH (tests/ratchet_test.c): a step's ratchet (x1..x4): its parts in the sequencer (equal, gated, chords and drum
#                   hits whole, one chance roll, swing, no slide or tie out, STOP), FUN8 round trip and older projects x1,
#                   user preset patterns, SEQ > AUTOMATION's RATCH rows and the roll / grid drawing.
# STEP 1.5 (tests/step15_test.c, #178 #173): SEQ > STEP's KNOB 3 LEN on a note (clean TIEs written after it and taken
#                   back, stopping at the next note and at LEN, chords, undo, TIME elsewhere, the DRUM grid untouched,
#                   the longer note played), a step's VEL as it plays (96 by default, ACC 127, drum hits) and
#                   SEQ > AUTOMATION's VEL rows (SHOW / HIDE, KNOB 4, EDIT, undo).
# DETAIL 1.5.1 (tests/detail_test.c, #199): SEQ > DETAIL (STEP -> DETAIL -> AUTOMATION), KNOB 1..4 the cursor step's
#                   CHANCE RATCH NUDGE VEL walked with PRESETS (NO NOTE on a REST / empty step), the same values as
#                   AUTOMATION's rows (gone at their default; EDIT there deletes one), EDIT resets, undo per gesture, the
#                   DRUM grid's keys picking steps (several held), a chord's ratchet, playback, STEP's marks.
# SEQ 1.5.5 (tests/seq155_test.c, #209 #186 #85): CONDITIONS (1:2 .. 4:4 by each track's loops from PLAY / a SONG
#                   section, FILL / !FILL with GLO + E4, a NUDGE early step 1, no lock on a failed one, the chance draws
#                   as before), DETAIL's KNOB 1 past 100 % and AUTOMATION's COND rows, FUN10 round trip and what 1.5 /
#                   1.5.1 do with them; SEQ TOOLS' EUCLID (hits / steps / rotation, DRUM lane or notes, OCT+ / OCT-,
#                   undo) and DOUBLE / HALF (ties, locks, the steps' own fields, 64 steps, undo).
# 1.5.5 (tests/ui155_test.c): PAN reads -100..+100 % (#199, the stored range as before); SEQ > AUTOMATION: KNOB 3 keeps
#                   its row in place (a step's records in the order they were added, #199); MENU > CONTROL > SELECT (#188):
#                   BPM by default, PAGE steps the family's pages (round, HOME MIXER CLOCK one round), GLO + SELECT the tempo;
#                   OCT- (1.5.6: #205's "OCT- held + a knob = default" taken out): the octave on the press as in 1.5.1, a
#                   knob with OCT- held an ordinary turn, the menu's OCT- back; SAVE > PROJECT ERASE (#199): KNOB 2, the dialog,
#                   refused playing / empty (tests/persistence_test.c: the flash side, a cut before the record keeps it);
#                   CLEAN INIT (#190): every engine's basic sound (no sends, INSERT, LFO / ENV / MOD amounts; neutral ENV; FM6
#                   the init voice), heard and ending; TOOLS' KNOB 2 on, EDIT + F5; one undo; INIT as before. OCT- next to
#                   EUCLID (OCT- cancels, OCT+ applies, no octave) and FILL (GLO + E4).
# 1.5.6 (tests/v156_test.c): HUMANIZE (#213): the matrix's VEL (a note-on's velocity, RAND per note, clamped 1..127) and
#                   TIME (a sequencer step late, 0..30 ms, at most 7/16 of the step, with NUDGE, a ratchet on time),
#                   appended after DEPTH; nothing changes without such a slot (RAND draws, mod_begin, timing); saved.
#                   KITS (#216): DRUM KIT DEEP TIGHT PERC (9..11) from the five kits' pieces and their three presets after
#                   DRUM KIT, the lanes' names, the 8 lanes play, saved, an older range reads them as 77.
#                   LEDS (#212): INV LO / INV HI after INV (INV's lit LEDs at the mid level), saved as INV + a level byte.
#                   SELECT (#84): MODW (the track's mod wheel, CC1 out) and VEL (the keys' velocity) after BPM / PAGE.
# 1.6 (tests/v16_test.c): SEQ's piano roll follows the play position (#242, Discussion #238): a melodic pattern over 16 steps,
#                   the transport playing: the roll's bank is the playhead's (STEP and DETAIL), the cursor and the pattern
#                   untouched; not for 16 steps, stopped, DRUM's grid, AUTOMATION, HOME; held from a knob's move of the
#                   cursor, an edit of its step or step entry, free again after 3 s or one pass round; reset by stop / track.
# MOD (tests/mod_test.c): the modulation matrix: slots that do nothing are bit-identical, every source on each
#                   kind of destination, clamping, MIDI CC1 / CC11 / aftertouch routing, the cost of 4 active
#                   slots (at most +5 %), demos in build/mod_demo/.
# SOUND (tests/sound14_test.c; #132 #104 #148): the matrix's S&H / SLEW sources (a value per LFO cycle, the glide) and
#                   DEPTH destination (the LFO's gain; none = untouched), ANALOG WAVE SYNC / SUB (pitch, no DC, bounded,
#                   the band-limited restart), SPREAD (SPRD 0 / MONO / LEGATO bit for bit, a note hard left / right, the
#                   mono sum, UNISON, the SLICER's gate and the mute key on both sides, mono sends), the cost; demos in
#                   build/sound14_demo/.
# INSERT (tests/insert_test.c, 1.5; #78 #177): the per-track INSERT (src/fx.c track_insert): TYPE OFF and MIX 0 bit for
#                   bit (POLY, SPREAD), each TYPE at its corners on 3 and 8 voices (no DC, bounded, MIX 50 % halfway
#                   to the wet), the MIX glide and TYPE changes, MIX / TYPE as automation and locks, FUN10 and user
#                   presets of 109 and 104, the pages' labels, the cost per type; demos in build/insert_demo/.
# SOUND 1.5 (tests/sound15_test.c; #104 #175): ANALOG's filter TYPE (LP bit for bit, every other engine ignores it, BP / HP
#                   responses around the cutoff, RES, bounded at the corners), ENV SYNC (OFF bit for bit, the note values
#                   on the knob, attack / decay / release times at 60 / 120 / 173 BPM and on the external clock), the cost;
#                   demos in build/sound15_demo/ (analog_bp, analog_hp, env_sync).
# PHASE FOLD 1.5.5 (tests/fold155_test.c; #104): E7 FOLD (0..127, default 0, the presets at 0), FOLD 0 bit for bit with
#                   1.5.1's loop, bounded and without DC at FOLD 1..127 (every WAVE, MIX / RING, SUB, notes 12..127),
#                   brighter with FOLD, the gain falling with the pitch above A4, the cost; build/fold155_demo/phase_fold.wav.
# ANALOG MIX 0 (tests/analog_mix0_test.c, #138): the OSC 1 alone loop against a reference copy of the two-oscillator
#                   one, call for call: PCM, phases, filter and noise state bit for bit (every WAVE x TYPE, MIX 0 / 1 / 64 /
#                   127 and changes mid-phrase, glide, bend, PWM, retrigger, unison, the parameter corners).
# PERFORM (tests/perform_test.c): the FX hold layer (src/perform.c): 1/16 starts, stereo buffer effects, the
#                   too-long REPEAT, the SLICER interplay, silent layer keys, idle bit-identical, cost; build/perform_demo/;
#                   OCT UP / DN (the harmonizer): pitch, stereo, clicks, the shimmer bounded, cost; FLANGER / PHASER (1.2): no DC,
#                   bounded, the sweep in time with the tempo, clean release, stacked with REPEAT / LPF / HPF, cost; the key
#                   map (any effect or none on any key, a key remapped while held, FX LATCH); build/fx_demo/; 1.5.1: the
#                   delay's dotted TIME (lengths, the 1/4D clamp, the knob order), REV / ECHO THROW (the sends as at 127,
#                   the glide, ECHO's capped feedback bounded, the tails ringing out, assignable); build/throw_demo/.
# REVERB (tests/reverb_test.c): REVERB TYPE (src/fx.c): ROOM bit for bit as before, SPRING's decay against SIZE,
#                   its chirp (group delay rising with frequency), stability at the corners, level, a model change
#                   without a click, its cost against ROOM (+30 % at most); demos in build/fx_demo/. 1.2's HALL: SPRING
#                   bit for bit as before, decay against SIZE and DAMP, stability, exact silence after the tail (27
#                   settings and levels), no offset, level, stereo, echo density / ringing / flutter against ROOM, SPRING
#                   and COMB8 (8 combs + 4 allpasses, host only, for comparison), model changes both ways, cost; the
#                   listening set in build/reverb_demo/ (drums, pluck, piano: dry and each model at SIZE 40 / 90 / 127).
# SLICE (tests/slice_test.c): slice tables, AUTO onsets of a user-slot loop, reverse, keys, modes, the MAN slices
#                   (SLICES page) and their store in the slot (src/slice_store.c); the presets and the loop;
#                   demos in build/slice_demo/.
# SAMPLE (tests/sample_test.c, 1.5): PIANO is the 5-zone piano of 1.0 .. 1.1.5 again: zones, splits, pitch over the
#                   keyboard (YIN), 0.75 s at a root, the aliases, GRAIN SRC 0; SLICE's PIANO its middle C zone (shared);
#                   1.2's PIANO HD user-slot file (gen_samples.py --user-slot: build/piano_hd/PIANO_HD), as old users may
#                   have installed it: valid in USR1 and bit for bit as SET 0.
# INPUT (tests/input_test.c): the key / button debounce of hal/fm1_input.h against the TIMER5 scan and bouncing
#                   contacts: a press within 2 scans (<= 2.3 ms), one note per bouncy press, no early or hanging
#                   release, stray samples ignored, fast repeats, the encoders' detents; the LED scan: lit LEDs every
#                   frame, dim ones a short pulse (the second line write) every frame, each only on its own column;
#                   the breath (#119): dark .. ~60 % of lit (DIM LO ~30 %), smooth, no dark run over ~10 ms near its peak;
#                   the power-on sweep (1.1, hal/fm1_led_anim.h): its length, every LED every frame at its level, the
#                   head left to right with its tail, the buttons, the end on the idle glow, the tick as before after;
#                   the idle animation (1.2, MENU > ANIM IDLE): endless, every LED every frame, the light there and back,
#                   the buttons breathing, a key down ends it before its next frame.
# CLICK (tests/click_test.c, 1.1): the metronome (src/click.c) and the count-in (src/seq.c) through audio.c: each beat at
#                   the first sample of its block, with a 1/16 track's steps 1 5 9 13 (internal and external clock, DIV 1/8
#                   and SWING too), the accent, the frequencies, length, LEVEL, MASTER, OFF / REC / ON, USB audio bit for bit
#                   without it; COUNT-IN 1 / 2 BARS (step 1 exactly N bars after PLAY, STOP cancels, PLAY again nothing,
#                   never with an external clock), notes in its last eighth onto step 1; build/click_demo/.
# USB audio (tests/uac_test.c): the UAC1 descriptors as a host parses them (with and without CDC; 44100 and
#                   48000 Hz), the ring and packetiser: 44.1 frames per packet, every frame in order (bit for bit),
#                   underrun / overrun, restart; SET_CUR; the 44.1 -> 48 kHz resampler (every frame against a
#                   double-precision one, response, SNR, cost); the stream at 48 kHz (47..49 frames per packet,
#                   fast and slow I2S clocks, switching rates mid-stream).
# web (web/test_web.mjs): the editor protocol against its mock device, whose tables must equal the
#                   firmware's (tests/descdump.c -> build/host/desc.json; the MENU settings: tests/editor_test.c -> build/host/menu.json),
#                   the package builder, the updater.
# Browser emulator (web/emu, when emcc is there): the firmware in WebAssembly (build/emu) boots, plays keys and MIDI,
#                   draws, lights its LEDs, keeps a save across instances, plays a song bit for bit as the same file
#                   built with cc (web/emu/native_check.c); the cost of 1 s of a heavy song against real time.
# Emulator partitions (#87, with Node): actual web_render bridge, exact PCM/state/publication equality for
#                   1024 vs irregular/128-frame drains; sustain/transport checkpoints and negative fixtures.
#                   Native always runs with generated assets; the same fixture also runs in Wasm with emcc.
# PHYS (tests/phys_test.c): stability over the whole parameter and pitch range, the worst-case cost against
#                   the heaviest factory preset, demos in build/phys_demo/; tests/phys_ref.cpp compares the
#                   fixed-point models with DaisySP's float originals when DaisySP is there (DAISYSP=path).
# DRUM (tests/drum_test.c): the drum voices (src/drum_voice.c): pitch, decay, centroid and level against
#                   Felucca's targets, the controls' directions, no clipping, DC, retriggers, the hat choke, the
#                   kick on a small speaker; the DRUM engine (src/eng_drum.c): its key map, the 8 lanes together,
#                   one hit per lane, the choke between lanes; the cost per voice; demos in build/drum_demo/.
# NOISE (tests/noise_test.c): the engine (engines/src/eng_noise.c): COLR's slope (white, pink, brown), the filter and the
#                   register clock following the key, META periodic at the key, no DC, no clipping at the
#                   corners, a note from silence the same twice, the cost per voice; demos in build/noise_demo/.
# DIGITAL -> FM6 (tests/fm4_test.c, built with FELUCCA_FM4=1): the retired four-operator engine against its conversion
#                   (src/fm4_convert.c): routes and carriers per algorithm, the presets' PTCH, and the sound (pitch,
#                   centroid, RMS envelope) of its presets and algorithms; demos in build/fm4_demo/. tests/digital_test.c
#                   (FELUCCA_FM4=1 too): DIGITAL's operator envelopes. Default builds have no DIGITAL (engine 1 reserved).
#                   tests/fm4_div0_test.c (UBSan, #61): the conversion without a divide that can be 0 gives the values the
#                   guarded form gave (every INDEX x FLT ENV, random sounds); a 0.9 project with DIGITAL ORGAN converts.
# FM6 (tests/fm6_test.c): the 6-operator FM engine (src/eng_fm6.c, src/fm6_core.c): the 32 algorithms' carriers, the
#                   operator envelopes (stages, rates, the voice ending), bit-stable notes, a click-free retrigger, no DC /
#                   clipping over the factory patches, the macros' directions, PTCH, pack / unpack and the SysEx
#                   layouts, the 6-voice cap, the cost per voice; demos in build/fm6_demo/.
# FM6 EFFECTIVE PATCH (tests/fm6_eff_test.c, #419): the audio side's copy of the patch through the macros against the
#                   published patch after accepted editor FM6_PUTs, project loads and slot loads while the track ran
#                   another engine (255+ updates: an eight-bit generation returns to the cache's), the switch back by the
#                   UI's first preset load and the first note; 1-4 tracks, macros zero / nonzero, second core on / off,
#                   CPU2=0 build, catalog without FM6; ThreadSanitizer too under TSAN=1.
# ROBUST (tests/robust_test.c): damaged or crafted stored data and editor requests: a SLICE scan bounded by the slot,
#                   a slot that fails its check leaves no zone, engine numbers past the last refused, a retained older
#                   RAM project bounded, user preset patterns inside their fields, malformed requests never stop PLAY.
# Sanitizers (ASan + UBSan, when the compiler has them; SANITIZE=0 skips): the stored-data and protocol tests again
#                   (loader, M-UPGRADE entry, editor, projects, backup, ROBUST) and three short fuzz runs with fixed
#                   seeds: tests/fuzz_ed.c (editor SysEx and raw USB-MIDI packets), tests/fuzz_proj.c (mutated project
#                   stores -> import -> restore -> render), tests/fuzz_smp.c (user sample slot headers -> scan -> SAMPLE /
#                   GRAIN / SLICE). Longer runs: build/host/asan/fuzz_ed 300000 7 (iterations, seed), the same for the others.
#                   UBSan leaves out the DSP's intended wraps (signed overflow, shifts) and the XIP rebase of a user zone's
#                   offset (bounds, object-size, pointer-overflow: correct on the device's flat flash, not in C's model).
# Change baseline entries only for reviewed, intentional differences in sound or cost;
# retain every unaffected golden / CPU / target entry. VERBOSE=1: every render.
set -e
export AC79_SDK="${AC79_SDK:-$HOME/fw-AC79_AIoT_SDK}"
cd "$(dirname "$0")/.."
OUT=build/host
mkdir -p "$OUT"
# --plan and --unit are internal scheduler entry points. Only the outer run does
# shared preflight; workers compile/run their selected unit with set -e active.
MODE=${1:-run}
SELECTED_UNIT=${2:-}
case "$MODE" in
    run)
        python3 tools/profile.py --check
        python3 tests/build_identity_test.py
        python3 tests/profile_test.py
        python3 tests/test_jobs_test.py
        exec python3 tests/test_jobs.py tests/run_tests.sh
        ;;
    --plan|--unit) ;;
    *) echo "usage: tests/run_tests.sh" >&2; exit 2 ;;
esac
CC="${CC:-cc} -O1 -Wall -Wno-unused-function -Ibuild/gen"
NOVEC="-fno-vectorize -fno-slp-vectorize"         # clang's spelling; GCC (cc on Linux) knows only its own
echo 'int x;' | $CC $NOVEC -x c -c -o /dev/null - 2>/dev/null || NOVEC="-fno-tree-vectorize -fno-tree-slp-vectorize"
fail=0
run() { echo "== $1"; shift; "$@" || fail=1; }

# Each row is name, prerequisites, and function/arguments, separated by tabs.
# The scheduler re-enters this script to execute a unit in its own process group.
unit() {
    unit_name=$1
    prerequisites=$2
    shift 2
    if [ "$MODE" = --plan ]; then
        printf '%s\t%s' "$unit_name" "$prerequisites"
        printf '\t%s' "$@"
        printf '\n'
    elif [ "$SELECTED_UNIT" = "$unit_name" ]; then
        "$@"
        exit "$fail"
    fi
}
note() { unit "$1" "" echo "$2"; }
HALF=$(sed -n 's/^#define HALF_FRAMES \([0-9]*\).*/\1/p' firmware/src/core.h)
FV=$(sed -n 's/^#define FELUCCA_VERSION "\([^"]*\)".*/\1/p' firmware/src/felucca.c)

u_portable() {
    run "target budget: synthetic disassembly and CLI fixtures (no toolchain)" python3 tests/target_budget_test.py
    run "firmware build safety guards (portable fixtures)" python3 tests/build_guard_test.py
    run "firmware source watch migration and recovery" python3 tests/firmware_watch_test.py
    run "generated sample inputs: stale/extra WAVs and header cache" python3 tests/gen_samples_test.py
    run "build --product: precedence, validation, no job on bad input (mocked)" python3 tests/build_product_test.py
    run "JieLi 64-bit arithmetic compile/link smoke (explicit skip without toolchain)" python3 tests/build_guard_target_test.py
    run "selective minsize: ISR symbol graph and annotation fixtures" python3 tests/size_fns_test.py
    run "selective minsize: real JieLi LLVM IR smoke (explicit skip without toolchain)" python3 tests/size_fns_target_test.py
    run "package flash boundaries (synthetic SDK)" python3 tests/fm1pkg_test.py
    run "package flash boundaries (Python -O, synthetic SDK)" python3 -O tests/fm1pkg_test.py
    run "host CPU baselines: compiler, version and platform separation" python3 tests/cpu_baseline_test.py
    run "timestamped interaction replay: portable scenario validation" python3 tests/replay_validation_test.py
    $CC -O2 -fstrict-aliasing -fno-builtin -o "$OUT/libc_test" tests/libc_test.c
    run "firmware libc: copy/fill sizes, alignments, sentinels and typed objects" "$OUT/libc_test"
    run "exact PR firmware: selection, download integrity and installer handoff" python3 tests/fm1_pr_test.py
    run "native MIDI installer: pinned setup, cache integrity and early preflight" python3 tests/m_flasher_test.py
}
unit portable "" u_portable

u_storage() {
    $CC -o "$OUT/storage_test" tests/storage_test.c
    run "flash storage (A/B, torn writes)" "$OUT/storage_test"

    $CC -o "$OUT/upreset_test" tests/upreset_test.c
    run "user presets (UP_PUT parser, bank round trip, versions, PHYS DRUM and SAMPLE PERC -> DRUM, grid records, DIGITAL kept)" "$OUT/upreset_test"
}
unit storage "" u_storage

u_input() {
    $CC -o "$OUT/input_test" tests/input_test.c
    run "keys and buttons: fast press, long release, bouncy contacts (one note each), glitches, encoders" "$OUT/input_test"

    $CC -o "$OUT/midi_uart_test" tests/midi_uart_test.c
    run "TRS MIDI parser" "$OUT/midi_uart_test"
}
unit input "" u_input

u_usb() {
    $CC -O2 -DT_CDC=1 -DHALF_FRAMES=$HALF -o "$OUT/uac_test" tests/uac_test.c -lm
    run "USB audio input: descriptors (with CDC), ring and packets, 44.1 -> 48 kHz resampler, 48 kHz stream" "$OUT/uac_test"
    $CC -O2 -DT_CDC=0 -DHALF_FRAMES=$HALF -o "$OUT/uac_test_nocdc" tests/uac_test.c -lm
    run "USB audio input: descriptors (without CDC), ring and packets, resampler, 48 kHz stream" "$OUT/uac_test_nocdc"

    for opt in O2 Os; do
        $CC -$opt -DHALF_FRAMES=$HALF -o "$OUT/uac_fir_bounds_test_$opt" tests/uac_fir_bounds_test.c
        run "USB FIR: channel/coefficient bounds, exact stereo PCM and complete state (-$opt)" "$OUT/uac_fir_bounds_test_$opt"
    done
    # USB descriptor layouts (#67): CDC UAC LAYOUT CDC-presented 48K; layout 0 and the console left out = 1.0's bytes
    # (+ the 48 kHz rate with 48K = 1, the default; 48K = 0: byte for byte; + the AC collection's audio streaming
    # interface first, FELUCCA_UAC_AS_FIRST = 1, the default since 1.6)
    for v in 1.1.0.1.1 1.1.1.1.1 1.1.2.1.1 1.1.3.1.1 1.1.0.0.1 1.1.2.0.1 0.1.0.1.1 1.1.0.1.0 1.1.0.0.0 1.1.2.1.0 0.1.0.1.0 \
             1.0.0.1.1 1.0.1.1.1 1.0.0.0.1 0.0.0.1.1; do
        IFS=. read -r t_cdc t_uac t_lay t_on t_48 <<EOF
$v
EOF
        $CC -DT_CDC="$t_cdc" -DT_UAC="$t_uac" -DT_LAYOUT="$t_lay" -DT_ON="$t_on" -DT_48K="$t_48" -o "$OUT/usb_desc_test" \
            tests/usb_desc_test.c
        run "USB descriptors: CDC $t_cdc (presented $t_on), UAC $t_uac (48 kHz $t_48), layout $t_lay" "$OUT/usb_desc_test"
    done
    # FELUCCA_UAC_AS_FIRST=0 (#67): the AC collection of 1.0 .. 1.5 (MIDI first), 1.0's bytes; the parser model of the
    # kernel AppleUSBAudio (macOS <= 15) stops before the audio streaming interface there
    for v in 1.1.0.1.1 1.1.0.0.1 1.1.0.1.0 1.1.0.0.0 0.1.0.1.1; do
        IFS=. read -r t_cdc t_uac t_lay t_on t_48 <<EOF
$v
EOF
        $CC -DT_CDC="$t_cdc" -DT_UAC="$t_uac" -DT_LAYOUT="$t_lay" -DT_ON="$t_on" -DT_48K="$t_48" -DT_ASF=0 \
            -o "$OUT/usb_desc_test" tests/usb_desc_test.c
        run "USB descriptors (AC collection MIDI first): CDC $t_cdc (presented $t_on), UAC $t_uac (48 kHz $t_48)" \
            "$OUT/usb_desc_test"
    done
}
unit usb "" u_usb

u_midi_partition() {
    # MIDI transport partition invariance (#87; tests/partition_test.c): one event schedule through the real USB / TRS queues and
    # parsers, rendered with 4096-sample spans and with irregular small ones (events at the same CTL boundaries): same PCM, same state
    if [ -f build/gen/felucca_tables.h ]; then
        $CC -w -Ibuild/gen -Ifirmware/src -o "$OUT/partition_test" tests/partition_test.c -lm
        run "MIDI partition invariance: USB / TRS / mixed schedule, large vs irregular partitions, negative self-checks" "$OUT/partition_test"
    else
        echo "== skip MIDI partition invariance (run ./build.sh once)"
    fi
}
unit midi_partition "" u_midi_partition

u_cc_scale() {
    $CC -O1 -w -Ibuild/gen -Ifirmware/src -o "$OUT/cc_scale_test" tests/cc_scale_test.c -lm
    run "MIDI CC scaling (#164): reachable descriptor bounds, x * 33027 >> 22 == x / 127, candidate == reference (host only)" "$OUT/cc_scale_test"
    $CC -O1 -w -fsanitize=undefined -fno-sanitize-recover=undefined -Ibuild/gen -Ifirmware/src \
        -o "$OUT/cc_scale_test_ubsan" tests/cc_scale_test.c -lm
    run "MIDI CC scaling candidate (UBSan)" "$OUT/cc_scale_test_ubsan"
}
unit cc_scale "" u_cc_scale

[ -f build/felucca.fwsc ] || { echo "run ./build.sh first"; exit 1; }

u_loader() {
    $CC -DOWN_PKG=1 -o "$OUT/ota_test" tests/ota_test.c
    run "M-UPGRADE entry (own loader)" "$OUT/ota_test" build/felucca.fwsc

    head -c 200000 build/felucca.bin > "$OUT/old_app.bin"
    python3 tools/fm1pkg_make.py "$OUT/old_app.bin" build/loader/ota.bin "$OUT/old.fwsc" >/dev/null
    $CC -o "$OUT/ldr_test" tests/ldr_test.c
    run "update loader: other app -> this build" "$OUT/ldr_test" "$OUT/old.fwsc" build/felucca.fwsc
}
unit loader "" u_loader

if [ -f build/gen/felucca_tables.h ]; then
    u_profiles() {
        run "profiles: isolated host selection, metadata and stored-sound round trips" python3 tests/profile_integration_test.py
    }
    unit profiles "" u_profiles

    u_replay() {
        run "timestamped interaction replay: PCM/LCD determinism and real emulator" python3 tests/replay_test.py NativeReplayTests
    }
    unit replay "" u_replay

    u_hostsim() {
        $CC -O2 -w -Ibuild/gen -Ifirmware/src -o "$OUT/hostsim" tests/hostsim.c -lm
    }
    unit hostsim "" u_hostsim

    u_scales() {
        $CC -O2 -w -Ibuild/gen -Ifirmware/src -o "$OUT/scale_test" tests/scale_test.c -lm
        run "scales: white-key mapping and note lifecycle" "$OUT/scale_test"
    }
    unit scales "" u_scales

    u_chords() {
        $CC -w -Ibuild/gen -Ifirmware/src -o "$OUT/chord_test" tests/chord_test.c -lm
        run "chord keys: diatonic and fixed chords, voicings, MONO root, releases, recording, ARP, MIDI IN, kits" "$OUT/chord_test"
    }
    unit chords "" u_chords

    u_speaker() {
        $CC -O2 -w -Ibuild/gen -Ifirmware/src -o "$OUT/speaker_test" tests/speaker_test.c -lm
        run "SPEAKER EQ: FLAT / LOWCUT / BASS+ responses, BASS+ harmonics of the bass, the sub cut, no offset after, headroom on a full-scale kick (#180)" "$OUT/speaker_test"
    }
    unit speaker "" u_speaker

    u_render() {
        run "DSP render (ANALOG preset 0)" "$OUT/hostsim" 0 0 1 "$OUT/render.wav"
    }
    unit render "hostsim" u_render

    u_stress_fixtures() {
        run "stress replay: bounded schedule and health guard fixtures" python3 tests/stress_matrix_test.py
    }
    unit stress_fixtures "" u_stress_fixtures

    u_stress_matrix() {
        run "stress matrix: repeated PCM/state, voice load, effects and switches (-O2/-Os)" python3 tests/stress_matrix.py
    }
    unit stress_matrix "" u_stress_matrix

    u_stress_replay() {
        run "stress integrated: repeated panel redraw/throw and stopped save PCM/LCD/state" python3 tests/stress_replay.py
    }
    unit stress_replay "replay" u_stress_replay

    u_tracks() {
        mkdir -p build/tracks_demo
        run "TRACKS: 4-track pattern, live recording (lengths, swing), voice budget, engine switch, cost" env TRACKS=build/tracks_demo "$OUT/hostsim" 0 0 1 "$OUT/tracks.wav"
    }
    unit tracks "hostsim" u_tracks

    u_project() {
        $CC -w -Ibuild/gen -Ifirmware/src -o "$OUT/project_test" tests/project_test.c -lm
        run "project formats (FUN1..FUN5 -> FUN6, the grid and song chain; DIGITAL tracks -> FM6, SAMPLE PERC -> DRUM)" "$OUT/project_test"
    }
    unit project "" u_project

    u_motion() {
        $CC -O1 -w -Ibuild/gen -Ifirmware/src -o "$OUT/motion_test" tests/motion_test.c -lm
        run "motion, whole-step chance, FUN7 migration, song restore, ARP repeat and the 1.2 ARP modes" "$OUT/motion_test"
    }
    unit motion "" u_motion

    u_ratchet() {
        $CC -O1 -w -Ibuild/gen -Ifirmware/src -o "$OUT/ratchet_test" tests/ratchet_test.c -lm
        run "RATCH: x1..x4 in a step (notes, chords, drum hits), gates, chance, swing, projects, user presets, AUTOMATION RATCH rows" "$OUT/ratchet_test"
    }
    unit ratchet "" u_ratchet

    u_step() {
        $CC -O1 -w -Ibuild/gen -Ifirmware/src -o "$OUT/step15_test" tests/step15_test.c -lm
        run "1.5 STEP: a note's LEN (TIEs on KNOB 3), a step's VEL (playback, AUTOMATION's VEL rows)" "$OUT/step15_test"
    }
    unit step "" u_step

    u_detail() {
        $CC -O1 -w -Ibuild/gen -Ifirmware/src -o "$OUT/detail_test" tests/detail_test.c -lm
        run "1.5.1 SEQ > DETAIL: a step's CHANCE RATCH NUDGE VEL on KNOB 1..4 (walk, entries, undo, DRUM, chords, playback, marks)" "$OUT/detail_test"
    }
    unit detail "" u_detail

    u_seq155() {
        $CC -O1 -w -Ibuild/gen -Ifirmware/src -o "$OUT/seq155_test" tests/seq155_test.c -lm
        run "1.5.5 SEQ: conditions and FILL, SONG, storage, editor; SEQ TOOLS EUCLID, DOUBLE, HALF" "$OUT/seq155_test"
    }
    unit seq155 "" u_seq155

    u_ui155() {
        $CC -O1 -w -Ibuild/gen -Ifirmware/src -o "$OUT/ui155_test" tests/ui155_test.c -lm
        run "1.5.5 fixes and UI: PAN +-100, AUTOMATION KNOB 3, SELECT PAGE, OCT- on the press (1.5.6), PROJECT ERASE, CLEAN INIT" "$OUT/ui155_test"
    }
    unit ui155 "" u_ui155

    u_v156() {
        $CC -O1 -w -Ibuild/gen -Ifirmware/src -o "$OUT/v156_test" tests/v156_test.c -lm
        run "1.5.6: the matrix's VEL / TIME (#213), DRUM kits DEEP TIGHT PERC (#216), LEDS INV LO / HI (#212), SELECT MODW / VEL (#84)" "$OUT/v156_test"
    }
    unit v156 "" u_v156

    u_v16() {
        $CC -O1 -w -Ibuild/gen -Ifirmware/src -o "$OUT/v16_test" tests/v16_test.c -lm
        run "1.6: SEQ's piano roll follows the play position (#242: STEP, DETAIL; held by the knobs, 3 s or one pass)" "$OUT/v16_test"
    }
    unit v16 "" u_v16

    u_fun10() {
        $CC -O1 -w -Ibuild/gen -Ifirmware/src -o "$OUT/fun10_test" tests/fun10_test.c -lm
        run "1.2 (FUN10): LFO 2 SYNC / TRIG / POL, NUDGE (record, QUANTIZE, play, controls), 128 motion records, FUN10 / FUN9 / FUN8 / FUN7, user presets" "$OUT/fun10_test"
    }
    unit fun10 "" u_fun10

    u_midi_control() {
        $CC -O1 -w -Ibuild/gen -Ifirmware/src -o "$OUT/midi_control_test" tests/midi_control_test.c -lm
        run "USB/TRS clock, bend, sustain, ownership and panic recovery" "$OUT/midi_control_test"
    }
    unit midi_control "" u_midi_control

    u_digital() {
        $CC -O1 -w -DFELUCCA_FM4=1 -Ibuild/gen -Ifirmware/src -o "$OUT/digital_test" tests/digital_test.c -lm
        run "DIGITAL (retired, built here with FELUCCA_FM4=1): operator envelopes/levels" "$OUT/digital_test"
    }
    unit digital "" u_digital

    u_fm4() {
        $CC -O2 -w -DFELUCCA_FM4=1 -Ibuild/gen -Ifirmware/src -o "$OUT/fm4_test" tests/fm4_test.c -lm
        mkdir -p build/fm4_demo
        run "DIGITAL -> FM6: the conversion against DIGITAL (FELUCCA_FM4=1): pitch, centroid, RMS envelope; demos" \
            "$OUT/fm4_test" build/fm4_demo
    }
    unit fm4 "" u_fm4

    u_fm4_div0() {
        $CC -O2 -w -fsanitize=integer-divide-by-zero -fno-sanitize-recover=all -Ibuild/gen -Ifirmware/src \
            -o "$OUT/fm4_div0_test" tests/fm4_div0_test.c -lm
        run "DIGITAL -> FM6 without a divide by zero (#61): the same values as before, a 0.9 ORGAN project (UBSan)" \
            "$OUT/fm4_div0_test"
    }
    unit fm4_div0 "" u_fm4_div0

    u_text() {
        $CC -O1 -w -Ibuild/gen -Ifirmware/src -o "$OUT/theme_test" tests/theme_test.c -lm
        run "themes: contrast, text blending and font metrics" "$OUT/theme_test"
        $CC -O1 -w -Ibuild/gen -Ifirmware/src -o "$OUT/text_ref_test" tests/text_ref_test.c -lm
        run "text: pens, kerning and pixels equal the reference renderer" "$OUT/text_ref_test"
        if python3 -c "import PIL" 2>/dev/null; then
            run "bitmap font storage: reject narrowed glyph metrics" python3 tests/bitmap_font_test.py
            run "text: M8Stealth ASCII matches upstream bitmaps" python3 tests/m8_font_test.py build/gen/ui_fonts.h
            run "text spacing: glyph gaps against the font's own (16x supersampled), S M <= 0.25 px, L <= 0.5 px" \
                python3 tests/text_spacing_test.py build/gen/ui_fonts.h
        else
            echo "font Python checks skipped (Pillow unavailable)"
        fi
    }
    unit text "" u_text

    u_settings() {
        $CC -O1 -w -Ibuild/gen -o "$OUT/settings_test" tests/settings_test.c
        run "settings: PER1..PER4 migration, PER6 (#212: engine ids to 63, PER4 <-> PER6, malformed, PER5), palette ids and preference preservation" "$OUT/settings_test"
    }
    unit settings "" u_settings

    u_boot_splash() {
        $CC -w -ffp-contract=off -Ibuild/gen -Ifirmware/src -o "$OUT/boot_splash_test" tests/boot_splash_test.c -lm
        run "startup splash: all buttons/keys, dismissal through release, MIDI/MASTER, timeout and wrap" "$OUT/boot_splash_test"
    }
    unit boot_splash "" u_boot_splash

    u_ui() {
        $CC -w -Ibuild/gen -Ifirmware/src -o "$OUT/ui_test" tests/ui_test.c -lm
        run "UI: sounds keep steps, undo, recording, MIDI overflow, pending saves, panel recovery, drum grid, song chain, GREY gray, MONO neutral" "$OUT/ui_test"
        $CC -w -DFELUCCA_CPU2=0 -Ibuild/gen -Ifirmware/src -o "$OUT/ui_test_c1" tests/ui_test.c -lm
        run "UI, a FELUCCA_CPU2=0 build: MENU > SYSTEM without 2ND CORE, the rest as the default build" "$OUT/ui_test_c1"
    }
    unit ui "" u_ui

    u_drumfuzz() {
        $CC -DPREEMPT -g -fwrapv -fsanitize=address,undefined -fno-sanitize=shift -fno-sanitize-recover=all -w \
            -Ibuild/gen -Ifirmware/src -o "$OUT/drumfuzz" tests/drumfuzz_test.c -lm
        run "DRUM grid stress (#211, ASan / UBSan): random grid editing, locks, undo, engines over a playing synth, the ISR anywhere" \
            "$OUT/drumfuzz" 1 6 1500
        run "DRUM grid stress (#211) with a SONG playing" "$OUT/drumfuzz" 101 3 1500 song
    }
    unit drumfuzz "" u_drumfuzz

    u_ui_render() {
        mkdir -p build/ui_new/ppm build/ui_slot
        if python3 -c "import PIL" 2>/dev/null; then
            run "UI renders: real renderer, layout lint, alignment, PNGs and comparison manifest" \
                python3 tests/ui_render.py build/ui_new build/ui_slot --renderer "$OUT/ui_render" --cc "$CC"
        else
            $CC -O1 -w "-DFELUCCA_VERSION=\"$FV\"" -Ibuild/gen -Ifirmware/src -Itests -o "$OUT/ui_render" tests/ui_render.c -lm
            run "UI renders: layout lint and alignment (Pillow unavailable; PNG/manifest/comparison skipped)" \
                "$OUT/ui_render" build/ui_new build/ui_slot
        fi
    }
    unit ui_render "" u_ui_render

    # These generators use their own directories, independent of ui_new/ui_fm4.
    if python3 -c "import PIL" 2>/dev/null; then
        u_identity_ui() {
            run "Build identity UI: bounded metadata in all fonts and palettes" python3 tests/build_identity_ui_test.py
        }
        unit identity_ui "" u_identity_ui
        u_settings_identity() {
            run "Settings identity: release, commit and PR in all fonts, palettes, styles and sizes" python3 tests/settings_identity_test.py
        }
        unit settings_identity "" u_settings_identity
        u_ui_compare() {
            run "UI comparison: exact pixels, scene matching, settings and strict gate fixtures" python3 tests/ui_compare_test.py
        }
        unit ui_compare "" u_ui_compare
    fi

    u_ui_fm4() {
        $CC -w -DFELUCCA_FM4=1 -Ibuild/gen -Ifirmware/src -o "$OUT/ui_test_fm4" tests/ui_test.c -lm
        run "UI built with FELUCCA_FM4=1 (DIGITAL, kept in the tree): its OP pages, EDIT cycle, algorithm charts" "$OUT/ui_test_fm4"
        mkdir -p build/ui_fm4/ppm build/ui_fm4_slot
        if python3 -c "import PIL" 2>/dev/null; then
            run "UI renders with FELUCCA_FM4=1: DIGITAL screens, lint, PNGs and comparison manifest" \
                python3 tests/ui_render.py build/ui_fm4 build/ui_fm4_slot --renderer "$OUT/ui_render_fm4" --fm4 --cc "$CC"
        else
            $CC -O1 -w -DFELUCCA_FM4=1 "-DFELUCCA_VERSION=\"$FV\"" -Ibuild/gen -Ifirmware/src -Itests -o "$OUT/ui_render_fm4" tests/ui_render.c -lm
            run "UI renders with FELUCCA_FM4=1: DIGITAL screens and lint (PNG/manifest skipped)" \
                "$OUT/ui_render_fm4" build/ui_fm4 build/ui_fm4_slot
        fi
    }
    unit ui_fm4 "ui_render" u_ui_fm4

    u_audio() {
        $CC -w -Ibuild/gen -Ifirmware/src -o "$OUT/audio_test" tests/audio_test.c -lm
        run "audio: overload protection, bounded fades and DMA diagnostics" "$OUT/audio_test"
    }
    unit audio "" u_audio

    u_click() {
        $CC -O2 -w -Ibuild/gen -Ifirmware/src -o "$OUT/click_test" tests/click_test.c -lm
        run "metronome and count-in: beats sample for sample (internal and external clock), accent, level, MASTER, not in USB, count-in timing, notes onto step 1" "$OUT/click_test"
    }
    unit click "" u_click

    u_persistence() {
        $CC -w -Ibuild/gen -Ifirmware/src -o "$OUT/persistence_test" tests/persistence_test.c -lm
        run "persistence: deferred settings, retry and failed-save rollback" "$OUT/persistence_test"
    }
    unit persistence "" u_persistence

    u_autosave() {
        $CC -w -Ibuild/gen -Ifirmware/src -o "$OUT/autosave_audio_test" tests/autosave_audio_test.c -lm
        run "autosave: real stereo FX tails, quiet window, short bursts, USB FIXED and wrap/retry" "$OUT/autosave_audio_test"
        $CC -Os -w -Ibuild/gen -Ifirmware/src -o "$OUT/autosave_audio_test_os" tests/autosave_audio_test.c -lm
        run "autosave audio (-Os)" "$OUT/autosave_audio_test_os"
    }
    unit autosave "" u_autosave

    u_backup() {
        $CC -w -Ibuild/gen -Ifirmware/src -o "$OUT/backup_test" tests/backup_test.c -lm
        run "full backup: CRC before writes, stale runtime, USB reset / timeout, malformed objects, older projects" "$OUT/backup_test"
    }
    unit backup "" u_backup

    u_fm6bank() {
        $CC -w -Ibuild/gen -Ifirmware/src -o "$OUT/fm6bank_test" tests/fm6bank_test.c -lm
        run "FM6 voice bank (1.4.1): write / read, power cuts, CRC, SLOT B1..B32, stored SLOT values as before" "$OUT/fm6bank_test"
    }
    unit fm6bank "" u_fm6bank

    u_editor() {
        $CC -w -Ibuild/gen -Ifirmware/src -o "$OUT/editor_test" tests/editor_test.c -lm
        run "editor: real C protocol, malformed transfers, queue recovery, MENU settings (writes build/host/menu.json)" \
            env MENU_JSON="$OUT/menu.json" "$OUT/editor_test"
        $CC -w -DFELUCCA_CPU2=0 -Ibuild/gen -Ifirmware/src -o "$OUT/editor_test_c1" tests/editor_test.c -lm
        run "editor, a FELUCCA_CPU2=0 build: MENU settings without 2ND CORE (ids 0..31)" "$OUT/editor_test_c1"
    }
    unit editor "" u_editor

    u_robust() {
        $CC -w -Ibuild/gen -Ifirmware/src -o "$OUT/robust_test" tests/robust_test.c -lm
        run "robustness: crafted sample slots, engine numbers, retained old projects, preset patterns, malformed requests" \
            "$OUT/robust_test"
    }
    unit robust "" u_robust

    u_engid() {
        $CC -w -Ibuild/gen -Ifirmware/src -o "$OUT/engid_test" tests/engid_test.c -lm
        run "engine ids (#212): the catalog, INFO's id bitmap, FAV markers old / new, ids this build lacks kept in projects, presets, backups" \
            "$OUT/engid_test"
    }
    unit engid "" u_engid

    # #212/#306: IDs and serializers run even when DRUM/FM6 are absent. Full-catalog union controls exclude
    # the same engine from their workload, preserving the existing default 720 goldens without new golden files.
    u_catalog() {
        omit=$1
        ENGX="-DFELUCCA_ENG_TEST14=1 -DFELUCCA_ENG_OMIT=$omit"
        for t in engid_test editor_test project_test upreset_test backup_test robust_test; do
            $CC -w $ENGX -Ibuild/gen -Ifirmware/src -o "$OUT/${t}_omit$omit" tests/$t.c -lm
            run "test build, engine 14 + catalog without $omit (#306): $t" "$OUT/${t}_omit$omit"
        done
        $CC -w $ENGX -Ibuild/gen -Ifirmware/src -o "$OUT/ui_test_omit$omit" tests/ui_test.c -lm
        run "test build, catalog without $omit: page visibility, stale engine controls and N/A rendering" \
            "$OUT/ui_test_omit$omit" --catalog
        if [ "$omit" = 11 ]; then
            union_ref=tests/union_golden.txt
        else
            union_ref="$OUT/union_control$omit.txt"
            $CC -O2 -w -DFELUCCA_ENG_TEST14=1 -DFELUCCA_UNION_OMIT=$omit -Ibuild/gen -Ifirmware/src \
                -o "$OUT/union_control$omit" tests/union_test.c -lm
            "$OUT/union_control$omit" > "$union_ref"
        fi
        $CC -O2 -w $ENGX -DFELUCCA_ARENA_CHECK=1 -Ibuild/gen -Ifirmware/src \
            -o "$OUT/union_test_omit$omit" tests/union_test.c -lm
        run "test build, catalog without $omit: owner-checked engine switches against full-catalog control" \
            "$OUT/union_test_omit$omit" "$union_ref"
    }
    for omit in 10 11 12 13; do
        unit "catalog_$omit" "" u_catalog "$omit"
    done

    u_noslice() {
        $CC -w -DFELUCCA_SLICE=0 -Ibuild/gen -Ifirmware/src -o "$OUT/engid_test_noslice" tests/engid_test.c -lm
        run "engine ids: FELUCCA_SLICE=0 retains unavailable SLICE records" "$OUT/engid_test_noslice"
    }
    unit noslice "" u_noslice

    u_mod() {
        $CC -O2 -w -Ibuild/gen -Ifirmware/src -o "$OUT/mod_test" tests/mod_test.c -lm
        mkdir -p build/mod_demo
        run "modulation matrix: off = bit-identical, the math, MIDI CC1 / CC11 / aftertouch, cost, demos" "$OUT/mod_test" build/mod_demo
    }
    unit mod "" u_mod

    u_sound14() {
        $CC -O2 -w -Ibuild/gen -Ifirmware/src -o "$OUT/sound14_test" tests/sound14_test.c -lm
        mkdir -p build/sound14_demo
        run "sound items: matrix S&H / SLEW / DEPTH, ANALOG SYNC / SUB, SPREAD (bit for bit at 0, L / R, mono sum), cost, demos" \
            "$OUT/sound14_test" build/sound14_demo
    }
    unit sound14 "" u_sound14

    u_insert() {
        $CC -O2 -w -Ibuild/gen -Ifirmware/src -o "$OUT/insert_test" tests/insert_test.c -lm
        mkdir -p build/insert_demo
        run "INSERT (1.5): OFF / MIX 0 bit for bit, each TYPE (no DC, bounded, dry / wet), MIX glide, automation, stored, cost, demos" \
            "$OUT/insert_test" build/insert_demo
        run "INSERT coefficient table: generator guards, original-formula PCM/state and mutation sensitivity" \
            python3 tests/insert_lpk_test.py --mutation-check
    }
    unit insert "" u_insert

    u_sound15() {
        $CC -O2 -w -Ibuild/gen -Ifirmware/src -o "$OUT/sound15_test" tests/sound15_test.c -lm
        mkdir -p build/sound15_demo
        run "1.5 sound items: ANALOG filter TYPE LP / BP / HP (responses, LP and other engines bit for bit), ENV SYNC (times at several tempi), cost, demos" \
            "$OUT/sound15_test" build/sound15_demo
    }
    unit sound15 "" u_sound15

    u_fold() {
        $CC -O2 -w -Ibuild/gen -Ifirmware/src -o "$OUT/fold155_test" tests/fold155_test.c -lm
        mkdir -p build/fold155_demo
        run "PHASE FOLD (1.5.5): FOLD 0 bit for bit, bounded, no DC, brighter with FOLD, alias-aware gain, cost, demo" \
            "$OUT/fold155_test" build/fold155_demo
    }
    unit fold "" u_fold

    u_analog_mix0() {
        $CC -O2 -w -Ibuild/gen -Ifirmware/src -o "$OUT/analog_mix0_test" tests/analog_mix0_test.c -lm
        run "ANALOG MIX 0 (#138): OSC 2 left out, PCM and voice state as the two-oscillator reference (WAVE x TYPE x MIX)" \
            "$OUT/analog_mix0_test"
        $CC -Os $NOVEC -w -Ibuild/gen -Ifirmware/src -o "$OUT/analog_mix0_test_os" tests/analog_mix0_test.c -lm
        run "ANALOG MIX 0 (#138) built as the target (-Os, no vectorising): PCM/state reference and mutation sensitivity" \
            "$OUT/analog_mix0_test_os"
    }
    unit analog_mix0 "" u_analog_mix0

    u_slicer() {
        $CC -O2 -w -Ibuild/gen -Ifirmware/src -o "$OUT/slicer_test" tests/slicer_test.c -lm
        mkdir -p build/slicer_demo
        run "SLICER: no clicks, timing, sync with the sequencer, STUT, cost, demos" "$OUT/slicer_test" build/slicer_demo
    }
    unit slicer "" u_slicer

    u_swing() {
        $CC -O2 -w -Ibuild/gen -Ifirmware/src -o "$OUT/swing_test" tests/swing_test.c -lm
        run "SWING: track + global at most 100, sequencer and SLICER step lengths, the SWG display" "$OUT/swing_test"
    }
    unit swing "" u_swing

    u_perform() {
        $CC -O2 -w -Ibuild/gen -Ifirmware/src -o "$OUT/perform_test" tests/perform_test.c -lm
        mkdir -p build/perform_demo build/fx_demo build/throw_demo
        run "FX layer effects: on the 1/16, stereo, too-long REPEAT, SLICER, silent keys, idle bit-identical, clicks, OCT UP / DN, FLANGER, PHASER, the key map, dotted TIME, REV / ECHO THROW, cost, demos" "$OUT/perform_test" build/perform_demo build/fx_demo build/throw_demo
    }
    unit perform "" u_perform

    u_stage() {
        $CC -O2 -w -Ibuild/gen -Ifirmware/src -o "$OUT/stage_unroll_test" tests/stage_unroll_test.c -lm
        run "SPRING and both PHASER callers: original-loop PCM/state equivalence and mutation sensitivity (-O2)" "$OUT/stage_unroll_test"
    }
    unit stage "" u_stage

    u_reverb() {
        $CC -O2 -w -Ibuild/gen -Ifirmware/src -o "$OUT/reverb_test" tests/reverb_test.c -lm
        mkdir -p build/reverb_demo
        run "REVERB TYPE: ROOM / SPRING bit-identical, SPRING and HALL decay / stability / level, HALL silence / stereo / ringing, model changes, cost, demos" "$OUT/reverb_test" build/fx_demo build/reverb_demo
    }
    unit reverb "perform" u_reverb

    u_fx_rest() {
        run "FX rest: burst/silence audio and state equivalence (-O2/-Os)" python3 tests/fx_rest_test.py --require-rest
    }
    unit fx_rest "" u_fx_rest

    u_chorus() {
        run "Chorus depth: continuity, exact PCM, short blocks and restart" python3 tests/chorus_depth_test.py
    }
    unit chorus "" u_chorus

    u_sends() {
        run "Shared sends: exact steady PCM, all transitions/short blocks, MOD, loads and worker fallback" python3 tests/send_gain_test.py
    }
    unit sends "" u_sends

    u_regression() {
        # Probe the actual CC (including wrappers), never the executable's alias.
        CPU_PATHS=$(python3 tests/cpu_baseline.py $CC)
        CPU_B=$(printf '%s\n' "$CPU_PATHS" | sed -n '1p')
        CPU_B_OS=$(printf '%s\n' "$CPU_PATHS" | sed -n '2p')
        echo "== CPU baselines: $CPU_B / $CPU_B_OS"
        [ -f "$CPU_B" ] || [ -n "$BUDGET_UPDATE" ] || CPU_B=-
        [ -f "$CPU_B_OS" ] || [ -n "$BUDGET_UPDATE" ] || CPU_B_OS=-
        $CC -O2 -w -Ibuild/gen -Ifirmware/src -o "$OUT/regress" tests/regress.c -lm
        run "regression: golden renders, health, voices, CPU budget" "$OUT/regress" tests/golden.txt "$CPU_B"
        $CC -Os $NOVEC -w -Ibuild/gen -Ifirmware/src -o "$OUT/stage_unroll_test_os" tests/stage_unroll_test.c -lm
        run "SPRING and both PHASER callers: original-loop PCM/state equivalence and mutation sensitivity (-Os, no SIMD)" "$OUT/stage_unroll_test_os"
        $CC -Os $NOVEC -w -Ibuild/gen -Ifirmware/src -o "$OUT/regress_os" tests/regress.c -lm
        run "regression built as the target (-Os, no vectorising): the same goldens, CPU budget" \
            "$OUT/regress_os" tests/golden.txt "$CPU_B_OS"
        run "regression CPU counter failures: whole-budget skip, exit status and baseline preservation" \
            python3 tests/regress_counter_test.py "$OUT/regress" "$OUT/regress_os"
        $CC -O2 -w -DFELUCCA_CPU2=0 -Ibuild/gen -Ifirmware/src -o "$OUT/regress_cpu2_0" tests/regress.c -lm
        run "regression, a FELUCCA_CPU2=0 build (none of the second core): the same golden renders and CPU budget" \
            "$OUT/regress_cpu2_0" tests/golden.txt "$CPU_B"
        # the second core (2ND CORE ON: fx.c mix_block, tests/c1_host.h): a thread renders the parts handed to it, bit for
        # bit
        $CC -O2 -w -Ibuild/gen -Ifirmware/src -DC1_HOST -pthread -o "$OUT/regress_c1" tests/regress.c -lm
        run "second core: the golden renders with a thread taking every split of the parts in turn" \
            "$OUT/regress_c1" tests/golden.txt -
    }
    unit regression "" u_regression

    u_dualcore() {
        $CC -O2 -w -Ibuild/gen -Ifirmware/src -pthread -o "$OUT/dualcore_test" tests/dualcore_test.c -lm
        run "second core: 4 parts of every preset, mixes: bit for bit on one core and on two, every split" \
            "$OUT/dualcore_test"
    }
    unit dualcore "" u_dualcore

    u_dualcore_failure() {
        $CC -O2 -w -Ibuild/gen -Ifirmware/src -o "$OUT/dualcore_failure_test" tests/dualcore_failure_test.c -lm
        run "second core failures: discard sums, restore canonical/stored parameters through partial modulation/fades; no state replay" "$OUT/dualcore_failure_test"
    }
    unit dualcore_failure "" u_dualcore_failure

    u_cpu1_protocol() {
        run "second core HAL: actual mailbox publication/acquisition, boot, failures and fence mutations" python3 tests/cpu1_protocol_test.py
    }
    unit cpu1_protocol "" u_cpu1_protocol

    u_crash_record() {
        run "fault records: publish only a complete owning-core snapshot" python3 tests/crash_record_test.py
    }
    unit crash_record "" u_crash_record

    u_crash_snapshot() {
        run "fault consumers: stable snapshots across per-word publication interleavings" python3 tests/crash_snapshot_test.py
    }
    unit crash_snapshot "" u_crash_snapshot

    u_tsan() {
        if [ -n "$TSAN" ]; then                     # TSAN=1: the same under ThreadSanitizer (~6 min): shared state
            TSAN_CC="cc -O1 -g -w -Ibuild/gen -Ifirmware/src -fsanitize=thread -pthread"
            $TSAN_CC -o "$OUT/dualcore_tsan" tests/dualcore_test.c -lm
            run "second core under ThreadSanitizer: 4 parts of every preset, mixes" \
                env TSAN_OPTIONS=halt_on_error=1 "$OUT/dualcore_tsan"
            $TSAN_CC -o "$OUT/fm6_eff_tsan" tests/fm6_eff_test.c -lm
            run "FM6 effective patch with the second core under ThreadSanitizer" \
                env TSAN_OPTIONS=halt_on_error=1 "$OUT/fm6_eff_tsan"
        fi
    }
    unit tsan "" u_tsan

    u_engines() {
        run "Felucca-Engines contract: real firmware host accepts v1 and rejects old/future APIs" python3 tests/engine_contract_test.py
        # Felucca-Engines (firmware/engines, MIT): its own test, then its standalone host built with Felucca's generated
        # tables against its golden renders (the same hashes: build/gen/felucca_tables.h has the engines' tables)
        run "Felucca-Engines: its own tables, host and golden renders" sh firmware/engines/tests/run.sh
        $CC -O2 -w '-DFE_TABLES_H="felucca_tables.h"' -Ibuild/gen -o "$OUT/fe_host" firmware/engines/tests/fe_host.c
        "$OUT/fe_host" > "$OUT/fe_renders.txt" || fail=1
        run "Felucca-Engines with Felucca's tables: the engines' golden renders" diff -u firmware/engines/tests/golden.txt "$OUT/fe_renders.txt"
    }
    unit engines "" u_engines

    u_union() {
        $CC -O2 -w -Ibuild/gen -Ifirmware/src -o "$OUT/union_test" tests/union_test.c -lm
        run "engine memory (1.5): every switch between the engines with per-part state sounds as in 1.4 (720 sequences)" \
            "$OUT/union_test" tests/union_golden.txt
        $CC -O2 -w -DFELUCCA_ARENA_CHECK=1 -Ibuild/gen -Ifirmware/src -o "$OUT/union_test_chk" tests/union_test.c -lm
        run "engine memory, owner-checked (FELUCCA_ARENA_CHECK=1): the same 720 hashes, every arena access by its owner" \
            "$OUT/union_test_chk" tests/union_golden.txt
    }
    unit union "" u_union

    u_arena() {
        $CC -O2 -w -DFELUCCA_ARENA_CHECK=1 -Ibuild/gen -Ifirmware/src -o "$OUT/arena_test" tests/arena_test.c -lm
        run "engine memory owner checker: negative fixtures, fixed-seed random notes / switches / fades on all parts" \
            "$OUT/arena_test" 48
    }
    unit arena "" u_arena

    u_descriptors() {
        $CC -w -Ibuild/gen -Ifirmware/src -o "$OUT/descdump" tests/descdump.c -lm
        echo "== parameter and engine tables as JSON (for the editor mock test)"
        "$OUT/descdump" > "$OUT/desc.json" || fail=1
    }
    unit descriptors "" u_descriptors

    u_phys() {
        $CC -O2 -w -Ibuild/gen -Ifirmware/src -o "$OUT/phys_test" tests/phys_test.c -lm
        mkdir -p build/phys_demo
        run "PHYS: stability C-1..G9 over the parameter corners, worst-case cost against PHASE WIRE, demos" "$OUT/phys_test" build/phys_demo
    }
    unit phys "" u_phys

    u_phys_ref() {
        D=${DAISYSP:-vendor/DaisySP}/Source
        if [ -d "$D/PhysicalModeling" ] && command -v c++ >/dev/null 2>&1; then
            $CC -O2 -w -Ibuild/gen -Ifirmware/src -Itests -c -o "$OUT/phys_fixed.o" tests/phys_fixed.c
            c++ -O2 -std=c++14 -w -I"$D" -I"$D/Utility" -o "$OUT/phys_ref" tests/phys_ref.cpp \
                "$D/PhysicalModeling/modalvoice.cpp" "$D/PhysicalModeling/resonator.cpp" "$D/PhysicalModeling/stringvoice.cpp" \
                "$D/PhysicalModeling/KarplusString.cpp" "$D/Filters/svf.cpp" "$D/Utility/dcblock.cpp" \
                "$D/Dynamics/crossfade.cpp" "$OUT/phys_fixed.o"
            run "PHYS: the fixed-point models against DaisySP's float originals (mode frequencies, decays, Svf)" "$OUT/phys_ref"
        else
            echo "== skip PHYS reference test (no DaisySP: set DAISYSP to a checkout)"
        fi
    }
    unit phys_ref "" u_phys_ref

    u_tom_tail() {
        $CC -O2 -w -Ibuild/gen -Ifirmware/src -o "$OUT/tom_tail_test" tests/tom_tail_test.c -lm
        run "TOM TAIL: exact-zero boundary, PCM and complete voice state" "$OUT/tom_tail_test"
        $CC -Os $NOVEC -w -Ibuild/gen -Ifirmware/src -o "$OUT/tom_tail_test_os" tests/tom_tail_test.c -lm
        run "TOM TAIL (-Os, no vectorising): exact-zero boundary, PCM and complete voice state" "$OUT/tom_tail_test_os"
    }
    unit tom_tail "" u_tom_tail

    u_drum() {
        $CC -O2 -w -Ibuild/gen -Ifirmware/src -o "$OUT/drum_test" tests/drum_test.c -lm
        mkdir -p build/drum_demo
        run "DRUM: voice targets, controls, no clipping, retrigger, hat choke, the kick on a small speaker, keys, 8 lanes, cost, demos" "$OUT/drum_test" build/drum_demo
    }
    unit drum "" u_drum

    u_noise() {
        $CC -O2 -w -Ibuild/gen -Ifirmware/src -o "$OUT/noise_test" tests/noise_test.c -lm
        mkdir -p build/noise_demo
        run "NOISE: colour slopes, key-tracked filter and clock, META period, DC, clipping, retrigger, cost, demos" "$OUT/noise_test" build/noise_demo
    }
    unit noise "" u_noise

    u_fm6() {
        $CC -O2 -w -Ibuild/gen -Ifirmware/src -o "$OUT/fm6_test" tests/fm6_test.c -lm
        mkdir -p build/fm6_demo
        run "FM6: algorithms, envelopes, retrigger, DC, clipping, macros, patch formats, voices, cost, demos" "$OUT/fm6_test" build/fm6_demo
    }
    unit fm6 "" u_fm6

    u_fm6_effective() {
        # #419: the effective-patch cache across engine switches and eight-bit generation aliasing, the editor/UI/audio paths
        $CC -w -Ibuild/gen -Ifirmware/src -o "$OUT/fm6_eff_test" tests/fm6_eff_test.c -lm -lpthread
        run "FM6 effective patch (#419): PUT / project / slot updates under another engine, 255+ updates, switch back, first note; second core on and off" \
            "$OUT/fm6_eff_test"
        $CC -w -DFELUCCA_CPU2=0 -Ibuild/gen -Ifirmware/src -o "$OUT/fm6_eff_test_c1" tests/fm6_eff_test.c -lm
        run "FM6 effective patch, a FELUCCA_CPU2=0 build" "$OUT/fm6_eff_test_c1"
        $CC -w -DFELUCCA_ENG_TEST14=1 -DFELUCCA_ENG_OMIT=12 -Ibuild/gen -Ifirmware/src -o "$OUT/fm6_eff_test_omit12" \
            tests/fm6_eff_test.c -lm -lpthread
        run "FM6 effective patch, catalog without FM6: the latent patch is kept, nothing renders it" "$OUT/fm6_eff_test_omit12"
    }
    unit fm6_effective "" u_fm6_effective

    u_slice() {
        # SLICE is in the standard build (firmware/src/core.h): its test always runs (after #22 by andreahaku)
        if grep -q '^#define SLC_BREAK_BPM ' build/gen/felucca_samples.h; then
            mkdir -p build/slice_demo
            python3 tests/slice_loop.py build/slice_demo/loop
            python3 tools/fm1_sample_upload.py build LOOP build/slice_demo/loop build/slice_demo/loop.wav:60 >/dev/null
            $CC -O2 -w -Ibuild/gen -Ifirmware/src -o "$OUT/slice_test" tests/slice_test.c -lm
            run "SLICE: tables, onsets, reverse, keys, modes, MAN slices and their store, demos" "$OUT/slice_test" \
                build/slice_demo/loop build/slice_demo
        else
            echo "== SLICE: build/ was made with FELUCCA_SLICE=0 (no BREAK); run ./build.sh without it first"
            fail=1
        fi
    }
    unit slice "" u_slice

    u_sample() {
        # SAMPLE's PIANO (1.5: as 1.1.5), SLICE's PIANO (its middle C zone), 1.2's PIANO HD in a user slot
        if grep -q '^    {"PIANO", 0, 5},' build/gen/felucca_samples.h; then
            mkdir -p build/sample_demo build/piano_hd
            python3 tools/gen_samples.py --user-slot PIANO "PIANO HD" build/piano_hd/PIANO_HD >/dev/null
            $CC -O2 -w -Ibuild/gen -Ifirmware/src -o "$OUT/sample_test" tests/sample_test.c -lm
            run "SAMPLE: PIANO (5 zones as 1.1.5: splits, pitch, length, GRAIN), SLICE's PIANO, a PIANO HD slot" "$OUT/sample_test" \
                build/piano_hd/PIANO_HD build/sample_demo
        else
            echo "== skip SAMPLE's PIANO (no CC0 library: assets/samples-cc0, tools/fetch_cc0.py)"
        fi
    }
    unit sample "" u_sample

else
    note hostsim_unavailable "== skip hostsim (run ./build.sh once)"
fi

# ASan + UBSan: the stored-data and protocol paths, and short fuzz runs (fixed seeds: the same inputs every run)
SAN="-O1 -g -fsanitize=address,undefined -fno-sanitize=signed-integer-overflow,shift,bounds,object-size,pointer-overflow"
SAN="$SAN -fno-sanitize-recover=undefined -w"
san_ok() {
    printf 'int main(void){return 0;}\n' > "$OUT/san_probe.c" &&
        ${CC%% *} $SAN -o "$OUT/san_probe" "$OUT/san_probe.c" 2>/dev/null && "$OUT/san_probe"
}
if [ "${SANITIZE:-1}" = 0 ]; then
    note sanitizer_disabled "== skip the sanitizer runs (SANITIZE=0)"
elif [ ! -f build/gen/felucca_tables.h ]; then
    note sanitizer_no_assets "== skip the sanitizer runs (run ./build.sh once)"
elif [ "$SELECTED_UNIT" = sanitizer_unavailable ] || { [ "$MODE" = --plan ] && ! san_ok; }; then
    note sanitizer_unavailable "== skip the sanitizer runs (the compiler has no ASan / UBSan)"
else
    mkdir -p "$OUT/asan"
    A="$OUT/asan"
    SCC="${CC%% *} $SAN -Ibuild/gen -Ifirmware/src"
    u_asan_libc() {
        # The libc harness needs none of the DSP sanitizer exclusions above.
        ${CC%% *} -O1 -g -Wall -Wno-unused-function -fsanitize=address,undefined \
            -fno-sanitize-recover=all -fno-builtin -o "$A/libc_test" tests/libc_test.c
        run "ASan/UBSan: firmware libc, including exact allocation boundaries" "$A/libc_test"
    }
    unit asan_libc "" u_asan_libc

    export ASAN_OPTIONS="${ASAN_OPTIONS:-detect_leaks=0}"

    u_asan_insert() {
        run "ASan/UBSan: INSERT coefficient table against the original formula" \
            python3 tests/insert_lpk_test.py --sanitize
    }
    unit asan_insert "insert" u_asan_insert

    u_asan_usb() {
        # Unlike the general DSP harness below, retain every UBSan bounds/pointer/shift check here.
        ${CC%% *} -O1 -g -Wall -Wno-unused-function -fsanitize=address,undefined -fno-sanitize-recover=all \
            -DHALF_FRAMES=$HALF -o "$A/uac_fir_bounds_test" tests/uac_fir_bounds_test.c
        run "ASan/UBSan (all checks): USB FIR channel/coefficient bounds and exact PCM/state" "$A/uac_fir_bounds_test"
    }
    unit asan_usb "" u_asan_usb

    u_asan_loader() {
        $SCC -o "$A/ldr_test" tests/ldr_test.c
        run "ASan/UBSan: update loader (other app -> this build)" "$A/ldr_test" "$OUT/old.fwsc" build/felucca.fwsc
        $SCC -DOWN_PKG=1 -o "$A/ota_test" tests/ota_test.c
        run "ASan/UBSan: M-UPGRADE entry (own loader)" "$A/ota_test" build/felucca.fwsc
    }
    unit asan_loader "loader" u_asan_loader

    u_asan_record() {
        t=$1
        $SCC -o "$A/$t" tests/$t.c -lm -lpthread
        run "ASan/UBSan: $t" "$A/$t"
    }
    for t in editor_test project_test backup_test robust_test fun10_test fm6bank_test engid_test autosave_audio_test fm6_eff_test; do
        unit "asan_$t" "" u_asan_record "$t"
    done
    u_asan_catalog() {
        omit=$1
        $SCC -DFELUCCA_ARENA_CHECK=1 -DFELUCCA_ENG_TEST14=1 -DFELUCCA_ENG_OMIT=$omit \
            -o "$A/engid_test_omit$omit" tests/engid_test.c -lm
        run "ASan/UBSan: engine ids + arena checks, catalog without $omit" "$A/engid_test_omit$omit"
    }
    for omit in 10 11 12 13; do
        unit "asan_catalog_$omit" "" u_asan_catalog "$omit"
    done
    u_asan_arena() {
        $SCC -DFELUCCA_ARENA_CHECK=1 -o "$A/arena_test" tests/arena_test.c -lm
        run "ASan/UBSan: engine memory owner checker (fixtures + 12 random runs)" "$A/arena_test" 12
    }
    unit asan_arena "" u_asan_arena

    u_asan_union() {
        $SCC -DFELUCCA_ARENA_CHECK=1 -o "$A/union_test_chk" tests/union_test.c -lm
        run "ASan/UBSan: engine memory switches, owner-checked (720 sequences)" "$A/union_test_chk" tests/union_golden.txt
    }
    unit asan_union "" u_asan_union

    u_asan_fuzz_ed() {
        $SCC -o "$A/fuzz_ed" tests/fuzz_ed.c -lm
        run "ASan/UBSan fuzz: editor SysEx and raw USB-MIDI packets (20000, seed 7)" "$A/fuzz_ed" 20000 7
    }
    unit asan_fuzz_ed "" u_asan_fuzz_ed

    u_asan_fuzz_proj() {
        $SCC -o "$A/fuzz_proj" tests/fuzz_proj.c -lm
        run "ASan/UBSan fuzz: project stores -> import -> restore -> render (5000, seed 13)" "$A/fuzz_proj" 5000 13
    }
    unit asan_fuzz_proj "" u_asan_fuzz_proj

    u_asan_fuzz_smp() {
        $SCC -o "$A/fuzz_smp" tests/fuzz_smp.c -lm
        run "ASan/UBSan fuzz: user sample slot headers -> scan -> SAMPLE / GRAIN / SLICE (1000, seed 17)" "$A/fuzz_smp" 1000 17
    }
    unit asan_fuzz_smp "" u_asan_fuzz_smp

fi

u_target_budget() {
    run "regression: target cost of the render loops (pi32v2 disassembly)" python3 tests/target_budget.py \
        build/felucca.dis tests/target_budget.txt
}
unit target_budget "" u_target_budget

u_install() {
    run "installer CLI (fm1_install.py) against a simulated FM-1" python3 tests/install_test.py
}
unit install "" u_install

u_diagnostics() {
    run "CDC diagnostics: real console/parser contract, fixtures, bounded transport and interval evidence" python3 tests/diagnostics_test.py
}
unit diagnostics "" u_diagnostics

if command -v node >/dev/null 2>&1; then
u_web() {
        run "web pages: editor protocol + samples, package builder, update protocol" node web/test_web.mjs
        run "web backup: capture, validation before writes, restore order" node web/test_backup.mjs
}
unit web "editor descriptors" u_web

else
    note web_unavailable "== skip web tests (no node)"
fi

u_emulator_partitions() {
    if command -v node >/dev/null 2>&1 && [ -f build/gen/felucca_tables.h ]; then
        run "emulator partitions: exact PCM/state/publication, native and optional WebAssembly, negative fixtures" \
            sh web/emu/partition_test.sh
    else
        echo "== skip emulator partitions (needs node and build/gen)"
    fi
}
unit emulator_partitions "" u_emulator_partitions

u_emulator() {
    if ! command -v emcc >/dev/null 2>&1; then
        echo "== skip the browser emulator (no emcc: Emscripten builds web/emu)"
    elif ! command -v node >/dev/null 2>&1 || [ ! -f build/gen/felucca_tables.h ]; then
        echo "== skip the browser emulator (needs node and build/gen)"
    else
        run "browser emulator: the firmware to WebAssembly (web/emu/build.sh -> build/emu)" sh web/emu/build.sh
        cc -O2 -ffp-contract=off -w -Ibuild/gen -Ifirmware/src -o "$OUT/emu_native" web/emu/native_check.c -lm
        run "browser emulator: the same song from the native build" "$OUT/emu_native" "$OUT/emu_native.f32"
        run "browser emulator: boot, keys, MIDI, screen, LEDs, PLAY, a save kept across instances, = native, cost" \
            node web/emu/emu_test.mjs build/emu/felucca.wasm "$OUT/emu_native.f32"
    fi
}
unit emulator "" u_emulator

if [ "$MODE" = --unit ]; then
    echo "unknown host test unit: $SELECTED_UNIT" >&2
    exit 2
fi
