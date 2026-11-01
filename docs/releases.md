<!-- SPDX-License-Identifier: GPL-3.0-only -->
# Release channels

## Latest Dev

Every push to `main` whose tip is a merged PR's merge commit starts **Latest Dev**.
Merge, squash and GitHub rebase merges are identified using the commit's associated
PR and its recorded merge SHA. Direct pushes without a matching merged PR do not
publish. The workflow runs the complete release validation even for documentation-only
merges. A failed gate leaves the previous releases available and publishes no package.

There is exactly one public Dev prerelease, at the permanent
[`latest-dev` address](https://github.com/kmplngj/Felucca/releases/tag/latest-dev).
Its title and short notes identify the PR and commit. The package version remains
`0.0-devSHORTSHA` (8 SHA digits) so it fits ABOUT; full source identity remains in
provenance. Dev never sets GitHub's stable **Latest** marker and makes no hardware
qualification claim.

Builds can run concurrently, but the publisher is serialized and never cancelled
by another merge. It checks the most recently merged main PR before upload and
again before promotion; a slower older run cannot roll Dev back. Direct pushes
create no Dev release. If the newest merge fails validation, the preceding
successful Dev remains available until a newer eligible build passes.

A hidden draft stages and uploads the complete validated package first. The writer
then replaces the public `latest-dev` release and moves its lightweight tag to the
new commit. The previous rolling package is retained privately during the swap
and restored if promotion fails. The swap has a short availability gap. Successful
publication removes superseded Dev releases/tags, including legacy `dev-pr*`
releases and abandoned staging drafts; no per-merge release archive is retained.
Reserved `dev-staging-*` and `dev-retired-*` names are temporary writer state.
Tagged versions are excluded from Dev cleanup.

Dev notes contain only PR/commit/CI links, experimental risks, backup and install
prerequisites and the pinned [recovery guide](usb-rescue.md). There is no Dev
commit history. Download the matching bundle and checksum together before the
next update replaces them; keep local backups and a known-good package.

## Tagged release procedure

Tagged releases also build and attach [experimental SMK-37 Pro, Elite and
MKE-P37 packages](smk37.md), each with model-specific identity and build evidence.
The checklist and attestation below apply to the standard FM-1 package only.
SMK assets remain unqualified until separately tested on each physical model;
release notes preserve that distinction. Normal PR CI and Latest Dev build only
the standard FM-1 firmware.

1. Choose `vX.Y`, `vX.Y.Z`, `vX.Y.Z.W` or a suffix such as `v1.6-rc1`.
   Each numeric component must be one digit; suffixes are alphanumeric.
   Update the [curated changelog](changelog.md), compatibility and known limitations
   in the candidate sources first. Push the tag on the intended commit.
2. **Release** runs complete validation and produces `release-RUN_ID` artifacts;
   pushing a tag does **not** publish. Download that versioned candidate, verify
   checksums and use its exact `.fwsc` for the checklist below. An unversioned Dev
   build or an earlier PR test does not qualify the tagged package.
3. Write a test report at a durable HTTPS URL (for example a repository issue).
   Record the full tag SHA, version, `.fwsc` SHA-256, artifact run URL, hardware/flash
   chip, OS, installer/client revision, test date/operator, results for every checklist
   item, and remaining limitations. Link logs/diagnostics where relevant.
   Resolve failures before approval; explicitly delimit unsupported configurations.
4. In Actions → **Release** → **Run workflow**, select the **same tag** in the ref
   selector. Enter its version **without v**, enable `publish`, paste the full
   40-character tag SHA into `tested_commit`, enter the tested `.fwsc` SHA-256 in
   `tested_package_sha256`, check `hardware_tested`, and supply
   the report URL in `test_evidence`. This is the maintainer's explicit attestation
   that the exact-package checklist is complete, not automated device verification.
5. The workflow rejects a branch, mismatched tag/SHA, absent attestation or missing
   HTTPS report. It reruns full validation, verifies downloaded archives and source
   provenance, and checks that the rebuilt `.fwsc` matches the supplied tested-package
   SHA-256 before publishing. Numeric versions become stable **Latest**; suffix
   versions remain prereleases. An existing release is preserved without replacing
   assets. A correction requires a new version/tag.

Leave `publish` off to rehearse packaging from a branch or tag (with `version`).
A failed publication can be rerun; failures never replace a stable release.
For immutable tagged versions, protect `v*` tags with repository rulesets;
workflow checks cannot prevent an administrator from moving a tag later.
The rolling `latest-dev` tag must remain movable by its publisher.
No workflow flashes hardware or deploys the web installer.

## Device release checklist

Complete on the exact versioned standard-profile package. The report records the
actual workloads and results, not just a blanket “all tested”. Host/browser evidence
is separate from FM-1 observations; optional profiles and beta CPU2 need their own
qualification if claimed supported. See [contribution validation](../CONTRIBUTING.md),
[performance](performance.md), [diagnostics](diagnostics.md) and
[recovery qualification](usb-rescue.md).

- Backup: export projects, settings, user presets/samples; verify that the backups
  can be read. Record saved-data versions and downgrade restrictions.
- Installation: ordinary update using the supported installer, final application
  identity and ABOUT commit, cold boot and warm restart, supported flash detection.
- Instrument: panel/display/navigation, all standard engines, mixed parts/voices,
  effects, held/released notes and engine switching; listen for glitches.
- Musical I/O: sequencer/song and transport, USB and physical TRS MIDI, MIDI clock,
  USB audio at 44.1/48 kHz with realistic load; record overload/deadline diagnostics.
- Persistence/editor: save/load projects and presets, reboot/readback, compatible
  older backups/import, editor connection and backup/restore round trip.
- Recovery: OCT− power-on early USB rescue, compatible loader update/retry and final
  boot/identity. Record the reachable ROM recovery route, host setup and verified
  device backup; follow the guide's stop conditions. Do not deliberately interrupt
  power during writes just to satisfy a checkbox. If power-loss recovery or a
  bootloader/stock transition was not safely qualified, explicitly exclude it.
- Review: full CI gates succeeded, no unexplained new warnings or resource failures;
  complete commit changelog and user-facing changes reviewed; all known limitations
  disclosed, no unresolved failure within the claimed support scope.

## Changelog and evidence

Tagged release pages combine installation/risk/recovery notes, the curated changelog link,
and **every commit** since the most recently published stable release that is an
ancestor of the candidate. Dev/prerelease tags never truncate that stable range.
Without a stable ancestor, all reachable history is included. This includes direct
commits and PR commits, not just GitHub's generated PR summary. Test evidence and CI
links identify who asserted device qualification and which automated run passed.
