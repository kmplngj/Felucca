#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-3.0-only
"""Bounded native stereo transition oracles (#479); see BUILDING.md.

No frozen PCM or universal click threshold. Each channel is compared with its
own steady waveform before/after the edit. Failure WAVs and counters stay in out.
"""
import argparse
from array import array
import hashlib
import json
import os
from pathlib import Path
import shlex
import struct
import subprocess
import sys
import wave

ROOT = Path(__file__).resolve().parents[1]
EVENT = 16384
FRAMES = 49152
# All edits finish by EVENT+1024. Keep their entire response, including the
# engine fade, separate from reference windows; never remove ringing FX tails.
REFERENCE = ((EVENT - 4096, EVENT - 256), (EVENT + 4096, EVENT + 8192))
TRANSITION = (EVENT, EVENT + 2048)
CASES = (
    "preset-held", "engine-held-queued", "engine-release-tail", "steal-low",
    "performance-mute-return", "dist-on", "insert-type", "insert-bypass",
    "sends-full", "chorus-depth", "rapid-edits", "multipart-fx-tails",
    "silence", "near-zero", "sharp-high-attack", "quiet-right",
)


def run(command, **kwargs):
    return subprocess.run([str(a) for a in command], cwd=ROOT, check=True,
                          timeout=180, **kwargs)


def compiler():
    # The full runner exports CC with the common generated include. A reduced
    # selection must precede that include, so remove it and add it explicitly.
    words = shlex.split(os.environ.get("CC", "cc"))
    result = []
    i = 0
    while i < len(words):
        separate = words[i] == "-I" and i + 1 < len(words)
        path = words[i + 1] if separate else words[i][2:] if words[i].startswith("-I") else None
        if path is not None and (ROOT / path).resolve() == ROOT / "build/gen":
            i += 2 if separate else 1
        else:
            result.append(words[i])
            i += 1
    return result


def differences(pcm, start, end, channel):
    first = second = 0
    for frame in range(start, end):
        x, y, z = (pcm[2 * (frame - k) + channel] for k in range(3))
        first = max(first, abs(x - y))
        second = max(second, abs(x - 2 * y + z))
    return first, second


def metric(pcm, case, attack=None):
    channels = []
    for channel in (0, 1):
        refs = [differences(pcm, a, b, channel) for a, b in REFERENCE]
        reference = [max(r[k] for r in refs) for k in (0, 1)]
        if attack is not None:
            onset = differences(attack, *TRANSITION, channel)
            reference = [max(a, b) for a, b in zip(reference, onset)]
        peak = max(abs(pcm[2 * f + channel]) for a, b in REFERENCE for f in range(a, b))
        observed = differences(pcm, *TRANSITION, channel)
        # Fixed-point floors: a few Q15 counts are not a general audibility
        # claim. Ratios cover phase/voice-sum variation in these smooth fixtures.
        limits = [max(6, 3 * reference[0]), max(12, 6 * reference[1])]
        if case == 5:
            # DIST currently changes transfer function abruptly. Bound it by
            # the measured envelope, without asserting smooth-control behavior.
            limits = [max(limits[0], 3 * peak), max(limits[1], 6 * peak)]
        if case == 14:
            # Both steady windows contain the sharp saw. Its large natural
            # derivatives permit beating/attack variation but must still reject
            # a full-range single-sample corruption below the output limit.
            limits = [max(6, 2 * reference[0]), max(12, 2 * reference[1])]
        channels.append(dict(reference=reference, peak=peak, observed=observed,
                             limits=limits, passed=all(a <= b for a, b in zip(observed, limits))))
    return channels


def write_failure(out, key, pcm, info):
    start, end = EVENT - 4096, EVENT + 8192
    with wave.open(str(out / (key + ".wav")), "wb") as wav:
        wav.setparams((2, 2, 44100, 0, "NONE", "not compressed"))
        wav.writeframes(b"".join(struct.pack("<h", max(-32768, min(32767, x)))
                                 for x in pcm[2 * start:2 * end]))
    (out / (key + ".json")).write_text(json.dumps(info, indent=2) + "\n")


def defects(pcm, case):
    """Use the same evaluator on rendered PCM, including isolated quiet R.

    A gain step is placed at a nonzero sample; multiplying silence cannot make
    a detectable defect. One-sample impulses test silence and quantization floor.
    """
    channels = (1,) if case == 15 else (0, 1)
    checks = []
    for channel in channels:
        at = max(range(EVENT, EVENT + 512), key=lambda f: abs(pcm[2 * f + channel]))
        if case in (0, 15) and abs(pcm[2 * at + channel]) > 6:
            broken = array("i", pcm)
            for frame in range(at, len(broken) // 2):
                broken[2 * frame + channel] *= -2
            checks.append((f"gain-step-ch{channel}", broken))
        broken = array("i", pcm)
        # Quiet impulses must clear a 12-count second-difference floor; loud
        # controls use a large but Q15-sized sample to clear waveform derivatives.
        if case == 14:
            at = max(range(EVENT + 2, TRANSITION[1] - 2),
                     key=lambda f: abs(pcm[2 * (f - 1) + channel] + pcm[2 * (f + 1) + channel]))
            neighbor = pcm[2 * (at - 1) + channel] + pcm[2 * (at + 1) + channel]
            broken[2 * at + channel] = -32700 if neighbor >= 0 else 32700
        else:
            broken[2 * (EVENT + 17) + channel] += 32 if case in (12, 13, 15) else 16000
        checks.append((f"impulse-ch{channel}", broken))
    return checks


def capture(binary, case, block, route, path, attack=False):
    env = dict(os.environ, C1_MASK="7")
    try:
        result = run([binary, case, block, route, path] + (["attack"] if attack else []),
                     env=env, capture_output=True, text=True)
    except subprocess.CalledProcessError as error:
        path.with_suffix(".stderr").write_text(error.stdout + error.stderr)
        raise ValueError(f"capture failed; raw PCM/stderr retained at {path}") from error
    info = json.loads(result.stdout)
    pcm = array("i")
    pcm.frombytes(path.read_bytes())
    path.unlink()
    if pcm.itemsize != 4 or len(pcm) != 2 * FRAMES or info["frames"] != FRAMES:
        raise ValueError("invalid native int32 stereo capture extent")
    if route == "on" and (not info["taken"] or info["refused"] or not info["affected"]):
        raise ValueError("CPU2 on route never took work or unexpectedly refused")
    if route == "fallback" and not (info["taken"] and info["refused"]):
        raise ValueError("CPU2 fallback must take work, then refuse at the edit")
    if route == "off" and info["calls"]:
        raise ValueError("CPU2 off route submitted work")
    if case in (1, 2) and (info["engine"] != 12 or not info["queued"]):
        raise ValueError("engine switch/queued gated note did not complete to native FM6")
    if not attack and case in (2, 11) and not info["pre_released"]:
        raise ValueError("release fixture has no live release tail at the edit")
    if not attack and case == 3 and info["kills"] < 2:
        raise ValueError("voice-steal fixture did not steal two voices")
    return pcm, info


def sanitizer_capture_probe(cc, flags, out):
    """An actual overflow in the real renderer must fail through capture()."""
    binary = out / "sanitizer-overflow-probe"
    command = cc + ["-O1", "-g"] + flags + ["-w", "-DAUDIO_TRANSITION_UBSAN_PROBE=1",
                  "-I" + str(ROOT / "build/gen"), "-I" + str(ROOT / "firmware/src"),
                  str(ROOT / "tests/audio_transition_test.c"), "-lm", "-pthread", "-o", str(binary)]
    run(command)
    path = out / "sanitizer-overflow.pcm"
    try:
        capture(binary, 12, 32, "off", path)
    except ValueError as error:
        failure = error.__cause__
        diagnostic = path.with_suffix(".stderr")
        if (not isinstance(failure, subprocess.CalledProcessError) or not failure.returncode
                or not diagnostic.exists() or "signed integer overflow" not in diagnostic.read_text()):
            raise ValueError("sanitizer probe failed without a retained signed-overflow diagnostic") from error
        print(f"audio transitions: sanitizer overflow rejected (exit {failure.returncode}); {diagnostic}", flush=True)
        return dict(command=command, returncode=failure.returncode, stderr=str(diagnostic), pcm=str(path))
    raise ValueError("sanitizer overflow capture unexpectedly passed; undefined behavior must be fatal")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--out", type=Path, default=ROOT / "build/host/audio-transitions")
    parser.add_argument("--optimization", choices=("O2", "Os"), action="append",
                        help="limit focused builds; default runs both")
    parser.add_argument("--inject", choices=("gain-step", "impulse"),
                        help="leave a defect in preset-held; must exit unsuccessfully")
    args = parser.parse_args()
    out = args.out.resolve()
    out.mkdir(parents=True, exist_ok=True)
    cc = compiler()
    run([sys.executable, "tools/profile.py", "--check"])
    profile = json.loads((ROOT / "build/gen/resolved-profile.json").read_text())
    novec = ["-fno-vectorize", "-fno-slp-vectorize"]
    probe = subprocess.run(cc + novec + ["-x", "c", "-c", "-o", os.devnull, "-"],
                           input="", text=True, capture_output=True, check=False, timeout=180)
    if probe.returncode:
        novec = ["-fno-tree-vectorize", "-fno-tree-slp-vectorize"]
    builds = [(name, ["-" + name] + (novec if name == "Os" else []), ROOT / "build/gen", 1)
              for name in (args.optimization or ("O2", "Os"))]
    skips = []
    sanitizer_probe = None
    if os.environ.get("SANITIZE", "1") != "0":
        san = ["-fsanitize=address,undefined", "-fno-sanitize=shift", "-fno-sanitize-recover=undefined"]
        probe_path = out / "sanitizer-probe"
        probe = subprocess.run(cc + san + ["-x", "c", "-o", str(probe_path), "-"],
                               input="int main(void) { return 0; }", text=True, capture_output=True,
                               check=False, timeout=180)
        if not probe.returncode and not subprocess.run([str(probe_path)], capture_output=True,
                                                       check=False, timeout=60).returncode:
            sanitizer_probe = sanitizer_capture_probe(cc, san, out)
            builds.append(("sanitize", ["-O1", "-g"] + san, ROOT / "build/gen", 1))
        else:
            skips.append("sanitizers: compiler/runtime unavailable")
    else:
        skips.append("sanitizers: SANITIZE=0")
    # Compile out the second core too; runtime OFF alone cannot establish this.
    builds.append(("cpu2-zero", ["-O2"], ROOT / "build/gen", 0))
    reduced = out / "reduced-gen"
    env = dict(os.environ, FELUCCA_FONT=profile["asset_variant"])
    run([sys.executable, "tools/profile.py", "--profile", "reduced-lofi", "--out", reduced], env=env)
    builds.append(("reduced-lofi", ["-O2"], reduced, 1))
    rows, references, commands, mutations, errors = [], {}, {}, 0, []
    for name, flags, gen, cpu2 in builds:
        binary = out / name
        command = cc + flags + ["-w", f"-DFELUCCA_CPU2={cpu2}", "-I" + str(gen),
                               "-I" + str(ROOT / "build/gen"), "-I" + str(ROOT / "firmware/src"),
                               str(ROOT / "tests/audio_transition_test.c"), "-lm", "-pthread", "-o", str(binary)]
        print(f"audio transitions: build {name}: {shlex.join(command)}", flush=True)
        commands[name] = command
        run(command)
        for case, label in enumerate(CASES):
            for block in (32, 128):
                attack = None
                if case in (1, 2):
                    attack, _ = capture(binary, case, block, "off", out / "capture.pcm", attack=True)
                    repeated_attack, _ = capture(binary, case, block, "off", out / "capture.pcm", attack=True)
                    if attack != repeated_attack:
                        raise ValueError("isolated FM6 attack reference is nondeterministic")
                control = None
                for route in (("off", "on", "fallback") if cpu2 else ("off",)):
                    key = f"{name}-{label}-n{block}-{route}"
                    pcm, info = capture(binary, case, block, route, out / (key + ".pcm"))
                    repeated, again = capture(binary, case, block, route, out / (key + "-repeat.pcm"))
                    channels = metric(pcm, case, attack)
                    failures = []
                    if pcm != repeated or info != again:
                        failures.append("repeat capture/counters differ")
                    expected_profile = "reduced-lofi" if name == "reduced-lofi" else profile["profile"]
                    if info["profile"] != expected_profile or info["cpu2"] != cpu2:
                        failures.append("compiled catalog/CPU2 selection differs from requested build")
                    if route == "off":
                        control = (pcm, info["state"])
                    elif (pcm, info["state"]) != control:
                        failures.append("CPU2 route differs from matched runtime OFF PCM")
                    # Same selected engines/workloads: reduced omits only LOFI,
                    # which none of these fixtures require. Do not skip cases.
                    refkey = case
                    if name == builds[0][0] and route == "off" and block == 32:
                        references[refkey] = (pcm, info["state"])
                    elif route == "off" and (pcm, info["state"]) != references[refkey]:
                        failures.append("build/profile differs from matched reference PCM")
                    if any(abs(x) > 32767 for x in pcm):
                        failures.append("sample exceeds Q15")
                    if not all(c["passed"] for c in channels):
                        failures.append("transition exceeds waveform-relative limit")
                    if case in (0, 2, 3, 11, 14) and max(c["peak"] for c in channels) < 100:
                        failures.append("expected sounding fixture is silent")
                    if case == 12 and any(pcm):
                        failures.append("silence fixture produced output")
                    if case == 13 and not 0 < max(c["peak"] for c in channels) < 32:
                        failures.append("near-zero fixture is not between 0 and 32 Q15 counts")
                    if case == 15 and not (channels[0]["peak"] > 100 and 0 < channels[1]["peak"] < 32):
                        failures.append("independent loud-left/quiet-right fixture lost its level contrast")
                    if route == "off" and case in (0, 12, 13, 14, 15):
                        for defect, broken in defects(pcm, case):
                            broken_metric = metric(broken, case)
                            if all(c["passed"] for c in broken_metric):
                                failures.append(f"undetected deliberate {defect}")
                                write_failure(out, key + "-undetected-" + defect, broken,
                                              dict(info, defect=defect, channels=broken_metric))
                            mutations += 1
                    if args.inject and case == 0 and route == "off":
                        defect, pcm = next((d, p) for d, p in defects(pcm, case) if d.startswith(args.inject))
                        channels = metric(pcm, case)
                        if not all(c["passed"] for c in channels):
                            failures.append(f"requested deliberate {defect} detected")
                    info.update(case=label, block=block, route=route, build=name,
                                sha256=hashlib.sha256(pcm.tobytes()).hexdigest(),
                                channels=channels, failures=failures,
                                attack_reference=[differences(attack, *TRANSITION, c) for c in (0, 1)] if attack else None)
                    rows.append(info)
                    if failures:
                        errors.append(key + ": " + "; ".join(failures))
                        write_failure(out, key, pcm, info)
        print(f"audio transitions: {name}: 16 cases x 2 partitions, repeated captures and CPU2 routes checked", flush=True)
    sources = [ROOT / "tests/audio_transition_test.c", ROOT / "tests/audio_transition_test.py",
               ROOT / "tests/hostsim.c", ROOT / "tests/c1_host.h"]
    report = dict(cases=CASES, frames=FRAMES, event=EVENT, references=REFERENCE,
                  transition=TRANSITION, compiler=cc, profile=profile,
                  commands=commands, source_sha256={str(p.relative_to(ROOT)): hashlib.sha256(p.read_bytes()).hexdigest()
                                                   for p in sources},
                  mutations=mutations, sanitizer_probe=sanitizer_probe, skips=skips, rows=rows, errors=errors)
    (out / "summary.json").write_text(json.dumps(report, indent=2) + "\n")
    for skip in skips:
        print("audio transitions: SKIP " + skip)
    if errors:
        print("\n".join(errors), file=sys.stderr)
        raise ValueError(f"{len(errors)} failed captures; WAV/counters: {out}")
    print(f"audio transitions: PASS {len(rows)} captures repeated exactly; {mutations} injected defects rejected; {out / 'summary.json'}")


if __name__ == "__main__":
    try:
        main()
    except (OSError, ValueError, subprocess.SubprocessError) as error:
        print(f"audio transitions: FAIL: {error}", file=sys.stderr)
        sys.exit(1)
