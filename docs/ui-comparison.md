<!-- SPDX-License-Identifier: GPL-3.0-only -->
# Comparing real UI renders

`tests/ui_render.c` renders the firmware drawing code against the host display stubs.
Its existing layout, alignment, antialiasing, icon and ink-box checks still run before
PNG conversion. The comparator uses these Felucca scenes; it does not match another
firmware’s screens or assess physical FM-1 readability.

## Capture each revision

Follow [BUILDING.md](../BUILDING.md) to generate that revision’s assets first. Use
separate checkouts and output directories for baseline and candidate. From each root:

```sh
python3 tests/ui_render.py build/ui-baseline --renderer build/host/ui_render
# In the candidate checkout, after its build:
python3 tests/ui_render.py build/ui-candidate --renderer build/host/ui_render
```

`--renderer` compiles the current C renderer with `-O1 -w`, the firmware version,
current generated headers, and optionally `--fm4` (`FELUCCA_FM4=1`). `--cc` defaults
to `CC` or `clang`. Capture includes the Git revision and dirty flag, compiler version
and command, binary SHA256, Pillow version, source/generator/font/asset/generated-header
hashes, and the actual compiled display and engine settings. Font inputs include nested
TTF/WOFF2/BDF files and bitmap references as well as both font generators. Input hashes
are checked across compilation and rendering. Generated-header hashes describe exactly what was
used; regenerate assets for each revision rather than assuming an old header is current.

The manifest lists the C renderer’s expected scenes and hashes each produced PNG.
Normal dimensions are exactly 240 × 240 RGB, converted from RGB565. Scene identity is
`palette/style/name`, independent of file names. Today the PNG outputs cover FLAT
(GREY, MONO, GREEN, PAPER, NIGHT), LINE (GREY, MONO, NIGHT, PAPER), LARGE (GREY, MONO),
and LARGE-LINE (GREY). The C lint also sweeps palettes not saved as PNGs.

The legacy conversion-only command `python3 tests/ui_render.py OUTDIR [SLOTDIR]`
still produces PNG/contact sheets, using `scenes.txt` and `render_settings.json` from
the renderer. Its manifest marks provenance as `conversion-only`; the comparator
reports this as invalid because conversion cannot establish which source built a
pre-existing executable. Old render folders without manifests need a fresh capture.

## Report and strict gate

```sh
python3 tests/ui_compare.py build/ui-baseline build/ui-candidate --out build/ui-compare
python3 tests/ui_compare.py build/ui-baseline build/ui-candidate --out build/ui-gate --strict
```

A candidate directory from another checkout may be an absolute path. Keep the report
separate from both input directories. Comparison never modifies inputs or approves or
updates a baseline. Approval is a human decision about a reviewed render capture.

`summary.json` records both provenances/settings, selected scenes, changed pixel counts,
per-scene bounding boxes (right/bottom exclusive), added/removed scenes, missing files
or required scenes, invalid comparison errors, and output sheet names. Each native-size
PNG sheet shows up to twelve before/after/diff rows; changed pixels are magenta on black.
Counts use exact RGB equality, including a change in only one channel, with no tolerance,
resampling, perceptual metric or automatic golden update. Sheets are streamed a page at
a time so the comparator does not keep the full render set in memory.
Reusing a report directory removes its previous generated `comparison_NNN.png` pages
before writing the new report, including for invalid captures. Other files are preserved.

Default report mode returns **0**, including when the summary is `different` or
`invalid`; read the summary when gathering evidence. `--strict` returns **0** only
for an identical valid selection, **1** for pixel differences, additions/removals or
missing images/scenes, and **2** for invalid input/settings/provenance/dimensions/hashes.
CLI usage errors also return **2**. Firmware version strings may differ; dimensions,
pixel mode/conversion, FM4, icons and SLICE settings must match. Source, font and generator
hash changes remain visible in provenance rather than hiding intended rendering changes.

For an economical visual review, choose explicit scenes (repeat options to add more):

```sh
python3 tests/ui_compare.py build/ui-baseline build/ui-candidate --out build/ui-sample \
  --scene home --scene step --scene menu_hold
```

This selection includes those names across every saved palette/style group. Optional
`--palette GREY` and `--style LINE` narrow it further. Unknown selections are invalid.
An approved baseline gate should use the full scene set or an explicitly agreed selection;
required scenes are enforced inside that selection.

Rolling-digit filmstrips are captured only when a slot directory is explicitly supplied:

```sh
python3 tests/ui_render.py build/ui-candidate build/ui-slot --renderer build/host/ui_render
python3 tests/ui_compare.py build/ui-baseline build/ui-candidate --out build/ui-film --filmstrips
```

The renderer lists the current capture's filmstrips in `filmstrips.txt`; older files
in a reused slot directory are not attributed to the new capture. Requesting
`--filmstrips` when neither capture contains them is an invalid comparison.
Filmstrip entries have their own dimensions/style and remain excluded from ordinary
comparisons. Supply slot directories for both captures to compare them. Filmstrips are
copied inside their render directory so a copied manifest remains portable.

## Verification boundaries

`python3 tests/ui_compare_test.py` checks identical and one-pixel images, moved elements,
scene pairing, added/removed/missing scenes, dimensions/modes, configuration, provenance,
image hashes, selection, filmstrip opt-in and both CLI exit policies. With Pillow installed,
[the full test runner](../tests/run_tests.sh) captures manifests for its normal and FM4
real renders and runs these fixtures. Without Pillow it retains the C renderer/lint and
reports the PNG/manifest/comparison skip.

These tools change no firmware sources, font/assets or sound baselines. Host images and
lint establish host-rendered pixels and geometry. Real FM-1 panel readability, viewing
angle, motion and hardware behavior still need device observation under
[CONTRIBUTING.md](../CONTRIBUTING.md).
