---
name: Felucca native panel
description: Direction A, the concert-poster grid on a 240 × 240 instrument LCD
colors:
  grey-bg: "#080808"
  grey-text: "#cecbce"
  grey-theme: "#efebef"
  grey-accent: "#fffbff"
  green-bg: "#001008"
  green-text: "#e7f7e7"
  green-theme: "#52d77b"
  green-accent: "#ffd75a"
  amber-bg: "#100c08"
  amber-text: "#f7efde"
  amber-theme: "#ffaa29"
  amber-accent: "#63d7e7"
  ice-bg: "#081018"
  ice-theme: "#52baef"
  ice-accent: "#ff8e63"
  violet-bg: "#100c18"
  violet-theme: "#b58af7"
  violet-accent: "#6be7ad"
  rose-bg: "#180810"
  rose-theme: "#f771b5"
  rose-accent: "#ffd76b"
  paper-bg: "#f7efe7"
  paper-text: "#211c18"
  paper-theme: "#085542"
  paper-accent: "#ad3808"
  hicon-bg: "#000000"
  hicon-theme: "#ffeb00"
  hicon-accent: "#00e7ff"
  night-bg: "#000000"
  night-text: "#94e7ad"
  night-theme: "#39df63"
  mono-bg: "#000000"
  mono-ink: "#ffffff"
typography:
  s:
    fontFamily: "M8Stealth57 (bitmap)"
    fontSize: "7px capitals, 6px advance"
    lineHeight: "15px box, baseline 12"
  m:
    fontFamily: "M8Stealth89 (bitmap)"
    fontSize: "9px capitals, 9px advance"
    lineHeight: "19px box, baseline 15"
  l:
    fontFamily: "M8Stealth89 ×2"
    fontSize: "18px capitals, 17px advance"
  n:
    fontFamily: "M8Stealth89 ×2 (full set)"
    fontSize: "18px capitals, 18px advance"
  x:
    fontFamily: "M8Stealth89 ×3 (numerals and capitals)"
    fontSize: "27px capitals, 26px advance"
rounded:
  none: "0px"
  cushion: "8px"
spacing:
  margin: "3px"
  column: "57px"
  column-pitch: "59px"
  header: "24px"
  bank-tall: "66px"
  bank: "44px"
  panel-scaled: "100px"
  panel-full: "122px"
  footer: "38px"
  settings-row: "19px"
  settings-gap: "2px"
components:
  knob-rule-rest:
    backgroundColor: "{colors.grey-text}"
    height: "1px"
  knob-rule-focus:
    height: "3px"
  knob-rule-turning:
    backgroundColor: "{colors.grey-accent}"
    height: "3px"
  settings-row-selected:
    backgroundColor: "{colors.grey-theme}"
    textColor: "{colors.grey-bg}"
    height: "19px"
  curve-marker:
    size: "5px"
---

# Design System: Felucca native panel

## Overview

**Creative north star: the concert-poster grid.** The screen is a strict typographic grid in the spirit
of the Zurich concert posters: four knob columns, one dominant numeral, rules instead of boxes, and one
signal colour that appears only where a control is acting. It reads like a well-set score sheet, not an
app dashboard. Felucca's own signature is behavioural: the graph follows the knob being turned, and a value's
editing state is carried by the form of its rule, so every theme and MONO read alike.

The canonical layout is the 240 × 240 panel at 1×. Every element sits on whole pixels; nothing is
antialiased except the pre-rendered icons and keycap pills.

## Colors

Each palette stores five colours (BG, SURF, TEXT, THEME, ACCENT, `build/gen/ui_palettes.h`); the rest are
fixed blends (`firmware/src/gfx.c palette_set`). Direction A draws on BG only (SURF equals BG).

- **TEXT** primary type and labels in focus; **MID** (70 % TEXT on BG) labels, units, hints and the resting
  focus rule; **DIM** (42 %) inactive; **LINE** (18 %) hairlines, rule tracks and dividers.
- **THEME** values, curves and the palette's identity.
- **ACCENT** the one active thing: the knob turning now (its rule, numeral and curve dot), the step edited,
  the tab underline. Never on a resting label.
- GREY and MONO are strictly neutral (a test enforces it). In every palette a turning knob also inverts
  its state text, a cue that remains where the accent matches the theme or MID.
- Built-in palettes keep every emitted text pair at or above 4.5:1. CUSTOM is user-controlled.

## Typography

M8Stealth only: the 5×7 and 8×9 bitmap sets plus exact integer scales that share their bitmaps.

- **X** (27 px): the focused value on tall value pages. **L** (18 px): the focused value in the 44 px band.
  **N** (18 px): full selected names (presets, NAME).
- **M** (9 px): values, names, titles, settings labels and values, footer names.
- **S** (7 px): column labels, units, the knob/state line, hints, graph letters.
- A focused value keeps one face over its whole domain (no size jumps while turning).
- L and X keep tabular digit cells; only the point is proportional ("1.18", not "1. 18").
- Words are the firmware's own, in capitals except mixed-case names. An ordinary value's state reads only
  `K1`; states add a word (`AUTO`, `LOCK 7`, `BASE 7`, `TEMP`, `KEPT`, `INACTIVE`, `FIXED`).

## Layout

- **Header** 0–24: `T1` (slot letter), play state, BPM in M with `BPM` in S, BPM LOCK's lock, the REC mark;
  octave or song row and battery at the right. Messages centre on x 120.
- **Bank** from 28: tall (66 px) on pages whose panel draws on the 100 px graph scale (scope, ENV, LFO, FX,
  SCALE, SLICER, INSERT, engine diagrams); otherwise 44 px (MIXER, CHORD, MOD, MACRO, FM6 charts, lists).
- **Four knob columns** 57 px wide at x 3 + 59 c, left to right KNOB 1–4.
- **Panel** to 198 (100 px scaled or 122 px full); **footer** 202–240: the step row, then sound (M),
  engine (S), page (M) and its family index (S).
- **Settings**: tab names justified across the bar with a sliding underline, seven 19 px rows with 2 px gaps
  and hairlines, hints at the bottom. Selection changes contrast, never size.

## Elevation & Depth

Flat. No shadows, no fills behind content. Depth is only the ink ramp TEXT → MID → DIM → LINE.

## Shapes

Square corners everywhere. The only rounded forms are the track cushions (mixer, song lanes) and the
pre-rendered keycap pills, because they depict physical things. Rules are 1 px; the focused knob's rule is
3 px.

## Components

- **Knob rule (the rule is the knob):** a LINE track the column wide, filled from the left to the knob's
  place in its range (full when the value has no range), at least 3 px. Form = state: solid value, dashed
  automation, doubled step lock, dotted MOMENTARY. Colour: MID at rest, ACCENT while turning, THEME under
  automation, DIM inactive. Focus makes it 3 px.
- **Focused readout:** label (M) and `K1`/state (S) on one line; the numeral (X or L) flush left with its
  unit (M or S) on the numeral's baseline.
- **Curves:** 2 px THEME traces on a RAISE baseline with dotted RAISE guides. ADSR stages carry dotted
  guides and A D S R letters.
- **Curve marker:** the focused value's point, drawn last: a 5 × 5 dot centred on the trace, cut free by a
  1 px ring of the ground (it reads apart from a curve of its own colour, dark or light), a 3 px stub above,
  and for a point in time (cutoff, attack peak, decay end, release end) a 1 px line to the baseline; a level
  (sustain) has the dot alone. At rest the dot is TEXT and the line MID; while the knob turns, all ACCENT.
- **GRAPH (MENU > DISPLAY):** TURN (default) swaps the live scope for the turned knob's curve while it turns
  and about 1.2 s after; SCOPE, CURVE (curve plus a small scope strip) and STILL.
- **Lists:** selected full name in N above five rows; the selected row inverted in THEME.
- **Hints:** physical control first (keycap pill or name), the action word in S.

## Do's and Don'ts

- Do keep every piece of information the screen showed before; rearrange it into the grid instead.
- Do keep settings and sound lists compact and identical in rhythm; single values edit inline.
- Do let the form of a rule carry state; colour only says "acting now".
- Don't add boxes, rounded cards, gradients, glows, shadows or decorative icons.
- Don't put the accent on anything at rest.
- Don't add a font, a size outside the five roles, or a setting for decoration.
- Don't change saved or wire ids; append, and keep retired ones reserved.
