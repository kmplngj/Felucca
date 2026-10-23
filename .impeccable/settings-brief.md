# Settings composition question — 2026-10-23

Which settings hierarchy should follow the D instrument-control work? Image exploration only; no firmware, input or protocol changes in this round.

## Recommendation

Uniform readable rows with explicit inline values and immediate changes through the current controls. Reserve deeper views for compound settings, longer choice lists, explanations and actions. Do not enlarge every selected value or make row height depend on focus.

## Three image concepts

- A — direct list: seven uniform rows, label/value alignment, a clear selected row and compact control hints. Recommended base.
- B — fixed detail area: five uniform rows above a persistent focused value and explanation. Larger reading path without moving neighboring rows; less overview.
- C — dedicated choice editor: a path/title and six LED alternatives, with applied versus proposed values distinguished. Stronger choice comparison, but introduces an extra step; use selectively.

All concepts use real DISPLAY settings and AMBER/M8 visual references. Images illustrate composition and are not verified 240-pixel renders. The existing firmware controls remain the baseline; any new APPLY/BACK behavior in C is explicitly experimental.

## Primary-source comparison

- [Digitakt II OS 1.17 manual](https://www.elektron.se/wp-content/uploads/2026/10/Digitakt-2-User-Manual_ENG_OS1.17_260930.pdf), pp. 75, 77, 81–82: list selection and submenu entry; direct change with left/right or YES; personalize choices and flags.
- [Digitone II OS 1.12 manual](https://www.elektron.se/wp-content/uploads/2026/10/Digitone-2-User-Manual_ENG_OS1.12_260930.pdf), pp. 72, 74–76: settings groups, list navigation, direct values and channel settings.

The recommendation is our adaptation for the FM-1. A uniform row layout and selective detail view are design conclusions, not a claim that these manuals prescribe our exact layout. Keep maker names out of issues as requested.

## Approval

Approved 2026-10-23: "A als Basis, C gezielt ergänzen". Approved comps are
`mocks/settings-a.png` and `mocks/settings-c.png`; B is retained for comparison.
The firmware implementation belongs to #577 / draft PR #574. Translate the
composition into real M8 pixels; do not copy generated lettering, gradients or
textures. Keep normal settings direct; provide staged choice pages selectively
for COLOR/LEDS and retain the existing AUTO OFF detail page.
