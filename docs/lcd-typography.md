<!-- SPDX-License-Identifier: GPL-3.0-only -->
# LCD typography and layout

The 240×240 FM-1 panel defaults to M8Stealth as one family with three roles.
The existing Tamzen and Inter Tight build alternatives remain supported; their
generated capital metrics feed the same placement rules.
The goal is predictable operation within Felucca's existing four-knob layout:
read the value, identify its label, then use the graph or the control hints.
Pages, navigation, palette tokens, FLAT/LINE and LARGE keep their existing jobs.

## Metrics and roles

[`tools/gen_bitmap_font.py`](../tools/gen_bitmap_font.py) generates the native
Trash80 S/M bitmaps and the shared 2× L data. Glyphs are trimmed to their ink;
the line box is layout space, not visible letter height. All faces have one
raster weight. Do not add another font to establish hierarchy.

| Face | Native capitals | Advance | Line box / baseline | Role |
| --- | --- | --- | --- | --- |
| S | 5×7 px | 6 px | 15 / 12 px | Labels, units, hints, graph annotations, footer, document text |
| M | 8×9 px | 9 px | 19 / 15 px | Primary values, names, titles, messages, list rows |
| L | M ink at exact 2×, 18 px high | 17 px | 35 / 28 px | Priority readouts and LARGE values where supported and fitting |

The 17 px L advance is intentional: three digits fit the narrow cards. It does
not scale the bitmap horizontally. S/M each have 105 records; L has 41 and is
not a general face for names. The ten local extra marks retain their explicit
bitmap adaptations and attribution. Keycap legends use the same native S
grid, within the existing 13 px pills; icons remain the existing icon system.
Track digits 1–4 use the selected text face, centered against their actual
rounded cushion. The former extra left shift for “1” is removed. An odd-width
glyph in an even-width cushion cannot land at an integer-pixel center; the
nearest placement keeps the shared left/up half-pixel tie rule, without scaling
or blurring its ink.

[`gfx.c`](../firmware/src/gfx.c) owns the common placement rules:

- `CAP_IN(F, h)` centers a face's capital band in a declared height. Half-pixel
  remainders go left/up. Use this instead of subtracting half a line height.
- `text_w` measures advance for fit and pen placement; `text_ink`/`ink_in` center
  visible ink. They serve different purposes. A minus sign, round figure or
  lowercase name can have different ink bearings without moving its pen.
- `UI_VALUE_UNIT_GAP` reserves 3 px between a value's advance and a unit slot.
  Units use S and share the value's capital-bottom baseline.
- Key hints have a 4 px keycap-to-word gap. `cv_key_row` measures and lays out
  the complete hints, while `cv_free_hint` and the header use the same width
  decision. Keep their fit and draw paths consistent.

Use spacing and theme roles alongside size: `T_THEME` for values, `T_MID` for
secondary information, `T_ACCENT` for the active knob, and existing selected
and disabled tokens. MONO's inverted hot-label chip continues to show state
when its accent and label colors coincide.

### Readable inactive information

Muting a track changes its sound, not whether its saved settings can be read.
Inactive card values use `T_MID` while their gauge and unavailable action-keycap
fills retain `T_DIM`. Mixer/HOME track names, mixer values and PAN/REV/dB
annotations, piano-roll pitch labels and MOD settings/units also use readable
text roles. Selected drum-lane names and mute icons use `T_TEXT` on `T_RAISE`;
other lane names use `T_MID`. MOD's inactive arrows, muted meters/notes, empty
steps and genuinely unavailable graphics retain their existing state treatment.

[`tests/lcd_readability_test.c`](../tests/lcd_readability_test.c) captures actual
text ink/background pairs from these draw paths in every built-in palette,
FLAT/LINE and NORMAL/LARGE, including selected/unselected and muted states.
Affected text must reach 4.5:1 by RGB565 relative luminance. Unavailable action
keycap fills and empty/disabled graphics are intentional exceptions, not a
reason to dim existing names or values. CUSTOM retains the user's stored
colors; these built-in contrast checks do not guarantee arbitrary custom pairs.
Calculated contrast does not establish physical LCD readability.

### Physical control names

Control legends and calibration prompts use the printed **SEL** button name,
including HELP and the browser emulator panel. **SELECT** remains the separate
encoder. The musical SCL page/scale abbreviation and internal `B_SCL`/`KC_SCL`
IDs are unchanged. Bracketed button prompts use `[SEL]`, which the normal
keycap parser resolves to the established ID.

## Focused parameter bank

With the legacy LARGE option on, value pages use a shared bank in the original
44 px parameter region. The four overview positions match KNOB 1–4. Turning a
valid knob selects its larger label/value/unit path. The last physical column
stays selected after the active-turn highlight expires; when that column is
empty on a new page, the first present column supplies the readout. A different
track/engine/page always resolves fresh strings and descriptors. The workspace
below the bank keeps the normal full-height renderer, including FM6 feedback,
MOD relationships, STEP DETAIL history and MIXER meters.

The focused value uses one face over its complete declared domain: L when its
glyphs and ink fit 106 px, otherwise M/S. The compact overview independently
chooses a stable M/S face. Required strings are not abbreviated to create room;
units have their own slot. In the default M8Stealth build, focus values are 18 px
where supported, labels/units 9 px, overview labels 7 px and values 9/7 px.
Alternative fonts retain their own capital metrics and bounded fit policy.

The focused status names its editing scope: VALUE, AUTO, INACTIVE/FIXED, TEMP,
KEPT, or LOCK/BASE with the first held step number (a + marks multiple steps).
The readout takes the actual existing column formatter output. A step lock does
not show the sound's base value while editing the lock. MOMENTARY restore/KEEP
and message/layer priority remain unchanged. The selected overview label stays
inverted; active turning additionally inverts the status line, including MONO.
Motion-driven overview values have a line underneath them.

The cache is part of the UI state. Identical frames send no extra bank blits;
ordinary edits update the necessary overview cells and focus band. A forced
redraw composes the complete bank before one blit, without an intermediate clear
across the old card gaps. Releasing a held step restores the ordinary roll
controls and their gaps. No new gesture, saved field, framebuffer or glyph cache
is introduced. List/menu alignment and retirement of the legacy size preference
are subsequent stages, not yet implied by these reading roles.

## Source inventory and bounded fit policy

| Surface / owner | Placement and fit policy |
| --- | --- |
| Normal cards, `ui_draw.c:draw_column` | The label uses capital band y=5, h=13 in each 57×44 card. LARGE list/graph labels use M if it fits, otherwise S, preserving that center. Values use y=18, h=17; M and dense S fallback share its center. Numeric pens start at x=5. S units end at x=54 in a reserved slot, so changing a digit count does not move the unit. The value plus 3 px gap plus unit must fit the 49 px field. |
| LARGE cards, `draw_column_tall`, `span_face` | M labels fall back to S at the same capital center. L values use exact 2× ink, with M/S fallback for width or missing glyphs. Choose one face over the knob's entire value domain where `card_span` is available; turning the knob must not change its size. Units stay on the separate centered line. |
| Header, `head_geo`, `head_msg` | M values and S annotations center in the 24 px header. BPM uses a same-length zero string for stable tabular geometry; play/stop share a slot. Messages use M then S according to bounded room. The header's hint measurement must match the renderer. |
| MENU/INFO, `ui_menu.c` | M row names/values center using `CAP_IN` in the existing density-dependent rows. HOLD/TUNE/CPU units use fixed right edges and the common 3 px gap. Tabs retain S/M according to LARGE. Long build identity uses the existing bounded continuation row. |
| MOD, `ui_graph.c:graph_mod` | M slot/source/destination/amount share each 17 px row's center. The amount starts at x=172; its S unit ends at x=228 and shares its baseline. Fit reserves the common gap, including -100%. |
| Piano roll, drum grid and STEP DETAIL, `ui_graph.c` | Piano note labels center within their row; drum labels center within the 10 px hit band; DETAIL labels center in each lane. Their native S size preserves the graph's density. |
| PRESETS, USER, PROJECT, SONG and automation | M rows carry primary names/values; S carries metadata and compact cells. Existing free-name ellipsis, selected-row detail, scrolling, parameter short names and HELP paths retain their meaning. |
| FM6/operator pages and quick layers | Retain compact S graph/cell annotations and existing M titles/values. LARGE changes the supported card role rather than enlarging every dense graph cell. |
| HELP, `ui_help.c` | Up to three keycap/action groups fit the 8..232 px footer row. Preserve every required keycap and the existing hint priority: when space runs short, optional action words yield before control legends. |
| NAME and dialogs | Preserve mixed-case names, the existing cursor/grid and bounded question fit. Names ellipsize at their assigned size instead of shrinking on each edit. |
| ABOUT/credits, `menu_text` | S text wraps by actual advance within 226 px, at 18 px line spacing. Long URL segments continue without losing characters. The same layout computes the scroll limit and draws both canvas bands. |
| Splash | The sparse L wordmark and bounded S build identity retain their existing placement and dismiss behavior. |

Fallback is a fit decision, not a global reduction of the interface. Preserve
mixed case; retain sign, decimal, degree and note marks. A required label/value
cut is a lint failure. Free names and messages may use their existing explicit
ellipsis paths. Do not expand L coverage, reduce glyph advances or relax layout
lint to make a new value fit. Reuse these roles for future UI features, including
#75/#143, without changing those features' scope here.

## Intentional changes and evidence

The #248/#249 batch changes M8 keycap ink and legend widths, fixes stationary
unit slots on normal cards and MOD rows, centers dense card fallbacks in the
same value band, and derives drum/DETAIL label positions from their ink bands.
The normal label-band expressions preserve the prior S/M pixels. Header
centering, whole-range LARGE face selection, names, navigation, scrolling and
rolling number semantics remain the existing contracts.

[`tests/lcd_typography_test.c`](../tests/lcd_typography_test.c) exercises the
real draw paths with text-emission hooks. It checks stationary units through
signed, decimal and digit-width changes, M-to-S capital-center consistency,
shared baselines and the signed MOD amount range. The ordinary UI behavior,
normal/FM4 render sweeps and alignment checks cover the surrounding workflows.
[`tests/track_badge_test.c`](../tests/track_badge_test.c) independently measures
the rendered digit pixels against an empty cushion at 12, 16 and 24 px, across
all palettes, FLAT/LINE and active/idle/dim states. The true cushion bounds also
feed the general alignment gate.
Use [BUILDING.md](../BUILDING.md) for reproducible capture and comparison commands;
retain before/after source, asset and build provenance together.

Rendered host images establish pixel placement and fit, not physical legibility
or panel latency. Inspect native-resolution normal/LARGE images, every palette
in FLAT/LINE, long names, dense lists/graphs, hint priority, and rolling frames.
Readability checks include 0/O, 1/I/l, 5/S, 8/B, signed/fractional values,
three-digit BPM and all added marks. The running browser emulator remains a
separate behavior/audio check.

**Pending real FM-1 acceptance:** compare small-label readability and LARGE
usefulness, keycap/control discovery, redraw and panel latency, and audio,
USB and MIDI under the combined test workload. Host/static resource checks
cannot establish those device observations; record them against the exact
installed commit/package in the PR's user test procedure. This change does not
alter sound, persistence or wire IDs and adds no bitmap face, glyph cache or
framebuffer.
