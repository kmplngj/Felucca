<!-- SPDX-License-Identifier: GPL-3.0-only -->
# LCD typography and layout

The 240×240 FM-1 panel uses M8Stealth as one family with task-specific roles.
Tamzen and Inter Tight firmware alternatives are retired; explicit legacy build
selections fail rather than silently producing another font.
The goal is predictable operation within Felucca's existing four-knob layout:
read the value, identify its label, then use the graph or the control hints.
Pages, navigation, palette tokens, FLAT/LINE retain their existing jobs. There is one native layout; font sizes
follow reading tasks rather than a global size preference.

## Metrics and roles

[`tools/gen_bitmap_font.py`](../tools/gen_bitmap_font.py) generates the native
Trash80 S/M bitmaps and shared 2× L/N roles. Glyphs are trimmed to their ink;
the line box is layout space, not visible letter height. All faces have one
raster weight. Do not add another font to establish hierarchy.

| Face | Native capitals | Advance | Line box / baseline | Role |
| --- | --- | --- | --- | --- |
| S | 5×7 px | 6 px | 15 / 12 px | Labels, units, hints, graph annotations, footer, document text |
| M | 8×9 px | 9 px | 19 / 15 px | Primary values, names, titles, messages, list rows |
| L | M ink at exact 2×, 18 px high | 17 px | 35 / 28 px | Focused values where supported and fitting |
| N | Full M ink at exact 2×, 18 px high | 18 px | 35 / 28 px | Selected names and NAME field |

The 17 px L advance is intentional: three digits fit the narrow cards. It does
not scale the bitmap horizontally. S/M/N each have 105 records; L has 41 and is
not a general face for names. L/N share every bitmap byte with M;
only glyph metadata and descriptors are added, without a decode cache. The
two native bitmap sets are the only stored text rasters. The ten local extra marks retain their explicit
bitmap adaptations and attribution. Keycap legends use the same native S
grid, within the existing 13 px pills; icons remain the existing icon system.
Track digits 1–4 use the selected text face, centered against their actual
rounded cushion. The former extra left shift for “1” is removed. An odd-width
glyph in an even-width cushion cannot land at an integer-pixel center; the
nearest placement keeps the shared left/up half-pixel tie rule, without scaling
or blurring its ink.

The source check compares each original WOFF2's 95 ASCII glyphs at 8→16 and
12→24 ppem: direct monochrome rasterisation equals exact 2× native ink,
bearings and advance. Independent upstream bitmap atlases verify the packed
1×/2× output too. This is evidence for these font files and our renderer;
another application's smoothing or the M8 device renderer is outside that check.
L's deliberately tighter advance is the stated exception, not a different shape.
Exact 2× S (14 px capitals) is technically available from the same raster, but
no current reading task justifies emitting its metadata. Settings use consistent
M content on parent and detail pages; S is reserved for supporting hints.

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
FLAT/LINE and both historical size-bit values, including selected/unselected and muted states.
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

Value pages use a shared bank in the original
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
is introduced. Focused values snap to the actual edited value; compact controls
and the independent header retain their existing numeric animation policies.

## Lists, menus and names

PRESETS, USER and PHRASES show five M rows with existing slot/category/favorite/
pattern metadata and a full selected-name header. The header uses N when the
whole name fits, otherwise M. PROJECT keeps its four slots and uses the same
name header. HOME TRACKS keeps four track timelines with M names; SONG keeps
its dense timeline with M slot letters. AUTOMATION keeps seven M rows so locks,
steps and values remain visible together. Piano-roll and drum annotations stay
S. Quick layers retain compact controls, their full maps and existing gestures.

Settings show up to seven uniform 19 px rows with 2 px gaps. Labels, values and
units use M, with explicit ON/OFF words on every row. Focus changes the row's
contrast, never its height or type size. The window scrolls at its lower edge;
the selected/total indicator stays above the control hints. Tab labels are M.
Every single-value row, including COLOR and LEDS, changes immediately through
the existing knobs or OCT−/+. COLOR displays the result immediately; LEDS uses
the same direct-edit rule. Neither needs a second selection/apply path.
Chevrons and the OPEN hint identify grouped details or independent views only.
AUTO OFF opens five uniform detail rows, validation feedback and its BACK action. INFO uses
28 px rows with bounded build-identity continuation; ABOUT keeps wrapped S text.
NAME shows up to 12 mixed-case characters in N with an underline caret, a distinct
cycling state and an end caret. Its keyboard map, category, length and save/cancel
hints stay visible. Dialogs keep bounded M/S questions and their explicit actions.

## Historical size compatibility

The native DISPLAY menu no longer includes LARGE. `PREF_LARGE` remains reserved
at `settings_dev[30]` bit 5, and MENU index/id 2 keeps its OFF/ON wire meaning.
Both old values render the same chosen UI. Import/export preserves that bit and
unrelated bytes; old records with no bit also use this UI. A legacy MENU_SET still
stores its historical value through the existing deferred settings-save path,
so a downgrade restores the last saved size choice. No setting/id is reused.
INFO/UI_STATE `uiCaps` bit 4 advertises the unified UI for current clients to hide
id 2; the separately routed client adaptation is
[#582](https://github.com/kmplngj/Felucca/issues/582). Older clients may still show
the harmless legacy control. See the [wire contract](../web/EDITOR_PROTOCOL.md#menu-settings-72-73-104).

## Source inventory and bounded fit policy

| Surface / owner | Placement and fit policy |
| --- | --- |
| Compact controls, `ui_draw.c:draw_column` | The label uses capital band y=5, h=13 in each 57×44 card. List/graph labels use M if it fits, otherwise S, preserving that center. Values use y=18, h=17; M and dense S fallback share its center. Numeric pens start at x=5. S units end at x=54 in a reserved slot, so changing a digit count does not move the unit. The value plus 3 px gap plus unit must fit the 49 px field. |
| Header, `head_geo`, `head_msg` | M values and S annotations center in the 24 px header. BPM uses a same-length zero string for stable tabular geometry; play/stop share a slot. Messages use M then S according to bounded room. The header's hint measurement must match the renderer. |
| MENU/INFO, `ui_menu.c` | Seven uniform M label/value rows; AUTO OFF detail rows use the same M content. COLOR/LEDS edit directly. HOLD/TUNE units use fixed right edges and the common 3 px gap. Tabs use M. INFO retains its bounded identity continuation. |
| MOD, `ui_graph.c:graph_mod` | M slot/source/destination/amount share each 17 px row's center. The amount starts at x=172; its S unit ends at x=228 and shares its baseline. Fit reserves the common gap, including -100%. |
| Piano roll, drum grid and STEP DETAIL, `ui_graph.c` | Piano note labels center within their row; drum labels center within the 10 px hit band; DETAIL labels center in each lane. Their native S size preserves the graph's density. |
| PRESETS, USER, PROJECT, SONG and automation | M rows carry primary names/values; S carries metadata and compact cells. Existing free-name ellipsis, selected-row detail, scrolling, parameter short names and HELP paths retain their meaning. |
| FM6/operator pages and quick layers | Retain compact S graph/cell annotations and existing M titles/values. Focused banks retain the complete graph. |
| HELP, `ui_help.c` | Up to three keycap/action groups fit the 8..232 px footer row. Preserve every required keycap and the existing hint priority: when space runs short, optional action words yield before control legends. |
| NAME and dialogs | N names preserve mixed case and a caret; dialogs retain bounded question fit. Names ellipsize at their assigned size instead of shrinking on each edit. |
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
centering, whole-range bank face selection, names, navigation, scrolling and
header and compact-control rolling semantics remain the existing contracts.

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
or panel latency. Inspect native-resolution unified-layout images with both historical size bits, every palette
in FLAT/LINE, long names, dense lists/graphs, hint priority, and rolling frames.
Readability checks include 0/O, 1/I/l, 5/S, 8/B, signed/fractional values,
three-digit BPM and all added marks. The running browser emulator remains a
separate behavior/audio check.

**Pending real FM-1 acceptance:** compare small-label readability and focus/menu/name reading roles, keycap/control discovery, redraw and panel latency, and audio,
USB and MIDI under the combined test workload. Host/static resource checks
cannot establish those device observations; record them against the exact
installed commit/package in the PR's user test procedure. This change does not
alter sound, persistence or wire IDs and adds no bitmap bytes, glyph cache or
framebuffer; the N role adds shared-bitmap metadata only.
