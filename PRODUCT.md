# Felucca native panel

<!-- impeccable:product-schema 1 -->

## Platform

Embedded firmware for the M-VAVE FM-1 (JieLi AC791N): a 240 × 240 RGB565 LCD drawn in strips by the main
loop, no framebuffer, no touch. The browser emulator (`web/emu/`) and the host renderer
(`tests/ui_render.c`) draw the same C sources and are review tools, not the product UI. The editor and
installer client lives in Felucca-WebApp and consumes the firmware's descriptors.

## Users

Musicians playing and programming the FM-1 by hand: four knobs (KNOB 1–4), the SELECT, ALGORITHM and
PRESETS encoders, the panel buttons and the 2-octave keys. Many are experienced groovebox and tracker users
who read the screen in glances between knob moves, often at arm's length, on stage or in dim rooms.

## Product Purpose

Make sounds and patterns, perform them, and configure the instrument without losing track of what the knob
under your hand changes, what the sequencer is doing and which state (automation, lock, temporary edit) a
value is in.

## Operating Context

- Mode: Operate. The screen serves the hands; expression lives in precise details.
- Four fixed knob positions map left to right to KNOB 1–4 on every value page.
- The screen is read during playback: transport, pattern slot, REC and the step playhead must stay visible
  on value pages.
- Main-loop drawing with bounded cost; the audio interrupt has priority. Flash and RAM are budgeted
  (`docs/performance.md`, `docs/flash-capacity.md`).

## Capabilities and Constraints

- Saved settings, MENU ids and protocol ids are contracts: append only, retired ids stay reserved
  (STYLE id 1, LARGE id 2 are retired native choices kept for rollback).
- Text is M8Stealth only: two native bitmap sets (5×7, 8×9) and exact integer-scaled roles; no new font data.
- Ten built-in palettes plus CUSTOM; GREY and MONO must stay neutral. Text pairs meet 4.5:1 in built-in palettes.
- Settings: uniform rows, single values edit inline, compound tasks open a detail page.
- No touch, no pointer: every state is reached with the physical controls; hints name the physical control.

## Evidence on Hand

Host renderer captures (all scenes × palettes), lint/alignment/contrast audits, the browser emulator gate,
CI target builds with resource budgets. Physical FM-1 readability and latency checks are tracked as pending
in each PR.

## Product Principles

- Show the knob, its value and its effect: the focused value large, its curve below while it turns.
- State by form, colour only for "acting now": a value's state is readable in MONO.
- Keep everything the screen already tells; rearrange rather than remove.
- Settings and lists stay compact and identical in rhythm across tabs and pages.
- Real labels and values only; abbreviations follow the firmware's existing words.
