# Felucca native panel

<!-- impeccable:product-schema 1 -->

## Platform

Embedded native FM-1 LCD firmware. The browser gallery is a review tool, not the product UI.

## Users

Musicians operating the FM-1 through its physical buttons and encoders.

## Product Purpose

Make sounds and sequences, then configure the instrument without losing track of the current setting or control assignment.

## Operating Context

The native display has 240 by 240 pixels. Four parameter knobs and the existing panel encoders/buttons operate it; there is no touch input. The user chose parameter-bank variant D for instrument controls and asked to reconsider settings separately before further coding.

## Capabilities and Constraints

- Existing settings belong to DISPLAY, CONTROL, AUDIO, MIDI and SYSTEM.
- The implemented candidate is draft PR #574. The older prototype gallery is not the latest firmware menu.
- Settings include flags, named choices, numeric values, nested AUTO OFF controls, actions and information pages.
- Existing menu operation uses ALGORITHM for tabs, PRESETS for rows, KNOB 1 or OCT-/+ for values; HOME closes. New input behavior in a comp is a proposal only.
- Preserve existing saved settings and protocol IDs. The historical LARGE option is already hidden by the candidate firmware.
- The user approved A as the settings base with C selectively, after reviewing image concepts informed by official device manuals.

## Evidence on Hand

Native renderer captures from PR head 6b9dfc3 in the separate ui-polish worktree; the existing prototype gallery; current menu sources; Digitakt II OS 1.17 and Digitone II OS 1.12 official manuals.

## Product Principles

- Keep finding, comparing and changing settings easy to distinguish.
- Use real labels and values in concepts.
- Keep proposed interaction separate from implemented behavior.
- Judge physical readability on the FM-1 after implementation; concept images are not pixel or hardware evidence.
