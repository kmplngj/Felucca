<!-- SPDX-License-Identifier: GPL-3.0-only -->
# Maintainer build bundles

`tools/build_manifest.py` seals one already-built, clean, explicitly selected revision
and existing canonical profile into a locally verifiable bundle. It includes the
installable FWSC, exact resource report and declared native outputs, generated inputs,
complete source archive, actual Git-free reproduction, notices and check receipts.
An optional fresh Wasm receipt adds the simulator that was built to accompany that
exact native report. This is maintainer staging: no public build service, deployment,
installer change, new profile/default, compatibility guarantee or installation approval.

Use the [build prerequisites](../BUILDING.md), [profile guide](build-profiles.md) and
[resource verification](build-profiles.md#machine-readable-build-evidence) first. The
JieLi tools/SDK remain necessary when creating a bundle; offline verification needs
neither a compiler nor a device. New bundle tooling and runtime files must be committed
before source export, because the complete archive contains committed blobs. Do not
export an older tree and attach newer uncommitted helper code to it.

## Prepare the actual build and reproduction

For a clean reviewed checkout on a local maintainer machine, the following example uses
standard, the current source version and development product FM-1_900. Run under the
applicable local storage/test guard and exclusive validation lock. Keep the same effective
options and locked build dependencies for the original and reproduced build. CPU2=0 or a
nonstandard profile must remain explicit through all commands; do not substitute another
profile's package. No golden or budget updates are involved.

```sh
export FELUCCA_PROFILE=standard
revision=$(git rev-parse HEAD)
uv run --locked --group build ./build.sh
python3 tools/source_archive.py export 1.6.1-bundle
mkdir -p build/bundle-reproduce
tar -xzf build/felucca-1.6.1-bundle-source.tar.gz -C build/bundle-reproduce
```

Build the actual extracted sources without Git. Keep the virtual environment outside
that verified tree; see [archive environments](../BUILDING.md#python-environments).
For example, select an external absolute environment path on your own machine:

```sh
export UV_PROJECT_ENVIRONMENT="$HOME/.cache/felucca-bundle-build-venv"
(
  cd build/bundle-reproduce/felucca-1.6.1-bundle-source
  uv run --locked --group build ./build.sh
)
```

Both environments must have identical generator versions and dependencies. `create`
requires literal app/FWSC equality and equal effective configuration, resources and
reserved stack spans. It preserves both exact resource reports: Git and verified-archive
origin/inventory metadata can legitimately differ even when compiled bytes agree.
The source archive label above names the source distribution; it does not change the
firmware display version or create a release.

## Optional matched simulator

With Emscripten and its frozen installed SDK/cache prepared, build through the existing
entry point, pointing to the exact native report:

```sh
uv run --locked --group build sh web/emu/build.sh --target-report build/resource-report.json
```

The runtime producer records the actual compiler/preprocessing arguments, source and
generated inputs, profile/identity, tool/SDK fingerprints and the explicit logical
configuration mapping. A successful matched build writes
`build/emu/runtime-report.json` last, binding all Wasm/worklet/page/font/license files to
the native report SHA256. Attempt logs are retained under `build/wasm-report/`.
The paired driver refuses unsupported extra flags/compiler search-path injections,
stale inputs, missing SDK provenance, output leftovers or source/tool changes during
compilation. It does not stamp an existing Wasm as freshly built. A normal unpaired
`sh web/emu/build.sh` stays available for development and does not claim a native match.

Matching means source/profile/logical build correspondence, with documented simulator
adapters. It does not mean equal target/Emscripten flags or device execution. The runtime
has simulated flash, no real USB/editor/updates/TRS MIDI, and no second-core execution.
For example, CPU2 configuration shape can match while worker operations remain stubbed.
Native/Wasm oracles, the fresh browser gate and physical qualification remain distinct.
A build receipt alone establishes none of those results.
The browser retains its existing enabled simulated-ISR misuse assertions; the native
target defaults to disabled assertions. The mapping records this deliberate difference
and requires browser assertions to stay enabled, without changing compiler arguments.

## Seal and verify

Use a new ignored destination. The source allowlist is one explicit full SHA from the
reviewed checkout; the tool neither resolves moving remote refs nor changes Git state.
The package name is selected by the native resource report, including its profile and
product naming, rather than a FWSC glob.

```sh
uv run --locked --group build python3 tools/build_manifest.py create \
  --root . --allow-revision "$revision" --profile "$FELUCCA_PROFILE" \
  --source-archive build/felucca-1.6.1-bundle-source.tar.gz \
  --reproduction-root build/bundle-reproduce/felucca-1.6.1-bundle-source \
  --runtime-receipt build/emu/runtime-report.json --out build/bundles/reviewed
python3 tools/build_manifest.py verify build/bundles/reviewed
```

`create` reruns the existing native report verifier, static target budget checker,
package validator and source-archive verifier; it verifies the reproduced target report
and compares its actual app/package/configuration/resources. Those native checks must
pass before a complete destination is emitted. It does not rebuild either target.
The offline `verify` command checks the sealed bytes and evidence relationships; its
success is not fresh compiler, full-suite or device acceptance.

For a deliberate native-only result omit `--runtime-receipt`. The manifest explicitly
records `unavailable/not_requested` and advertises no simulator. After an actual runtime
failure, use `--runtime-unavailable build_failed` (or `provenance_missing`) and retain the
failure log with `--evidence PATH`. An absent/stale receipt never selects another Wasm.
Do not use an unavailable-only result as completion of the successful matching-runtime
implementation/validation stage of [#466](https://github.com/kmplngj/Felucca/issues/466).

Repeat `--evidence PATH` to bind exact additional host/browser/diagnostic receipts. They
are copied byte for byte; the tool does not reinterpret their outcomes. The manifest's
broader acceptance remains host/browser **not evaluated**, physical **not performed**.
Known local full-suite cost/strict failures stay failed in the accompanying handoff;
a hosted run without PMU counters does not replace them. No bundle field claims full CI,
live CPU/deadline, stack watermark, successful flashing or real-device acceptance.

## Identity and immutability

`manifest.json` is canonical JSON, schema version 1, kind `felucca-build-manifest`.
Its `identity` binds the exact source/Engines inventory, profile/contract, generator input
and compiled-header hashes, complete effective target configuration, compiler/header/SDK
and generator provenance, and runtime configuration when recorded. Client payload is
explicitly not included; GPL collection consumption remains unsupported under #360.
If the producer exports #422 engine keys, their reviewed reference and selected metadata
are bound as external inputs. Older producers remain explicitly without that metadata;
this tool invents no runtime key, wire field or compatibility policy.

The native header inventory covers the fixed JieLi4.0.1 roots
`pi32v2/lib/clang/4.0.1/include` and `pi32v2/include`, including their content hashes.
Missing roots/stdint.h and symlinked header paths fail before generation. Unsupported
nonempty compiler search/configuration/loader injection variables also fail at that
initial capture; clearing them only when sealing cannot qualify an older build.

This is a declared-input identity, not a fingerprint of every execution dependency.
`configuration.execution_environment` records native/Docker execution and the image
reference when used; its system-runtime fingerprint is explicitly null. A floating
Docker image can change runtime libraries without changing that reference. Actual image
content IDs and host/system library closure are not bound by v1; cross-environment cache
equivalence remains unresolved. Do not claim reproducibility under arbitrary Docker or
host installations. The actual same-environment Git-free app/FWSC reproduction is still
mandatory, and full execution-environment identity remains follow-up work.

The configuration key is SHA256 of `felucca-build-key-v1` followed by a NUL byte and the
canonical identity object. A profile name, display version or selection SHA alone is
insufficient: CPU2 variants can share a selection SHA while their binaries differ.
Canonical JSON sorts keys, uses compact separators and ASCII escapes, and refuses NaN,
Infinity and duplicate keys. Source/archive provenance and final artifact/evidence hashes
remain bound in the exact manifest, outside the configuration-key inputs.

Detached `SHA256SUMS` covers all payload files plus the final manifest, excluding itself.
No embedded self-hash or mutable index is introduced. Reuse requires the exact manifest
content hash and every file to verify; a configuration-key match alone is insufficient.
The same inputs can have different preserved diagnostic/origin records. Existing
identical destinations are idempotent; a different destination inventory is never
rewritten. Paths, symlinks, case aliases, extra files, wrong source/report/runtime pairs
and borrowed reproduction receipts are rejected.

A seal uses a destination-specific exclusive lock file and an adjacent temporary directory.
On ordinary failure the destination is absent and the owned temporary evidence is retained
as `.NAME.failed-*`; it is not a complete bundle. Process termination/power loss can leave
an adjacent `.NAME.seal-lock` and staging directory. Do not remove a live owner's lock.
A maintainer must establish that its creating process has stopped before explicitly
removing that stale lock and choosing a new destination; the tool does not perform global
cleanup or silently recover another owner's state.

## User checks and remaining work

After preparing the exact inputs above, create and verify a bundle, copy it to a new
directory and verify again. On a disposable copy, change one FWSC, resource report,
source archive, reproduced report, Wasm, worklet or font: verification must fail. Changing
only an outer checksum must not make a wrong source/configuration pair valid. Preserve
the original bundle and report the exact revision/profile, command and observed error.
No device installation is required to test this tool. Real FM-1 install/recovery,
audio deadlines, USB/TRS and panel behavior remain pending unless separately performed.

Public authorization, request parsing/quotas, job cancellation, cache/index/retention,
CORS/delivery and end-to-end explicit backup/install remain #466 work. Browser consumption
belongs to #467, the editor-preview protocol adapter to #413, arbitrary profile estimates
to #465, GPL source/pin integration to #360 and runtime compatibility policy/transport to
#422. Existing release/PR workflows and site staging are unchanged.
