#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-3.0-only
"""Repeat integrated stress timelines using the existing interaction replay adapter."""
import argparse
import hashlib
import json
from pathlib import Path
import subprocess
import sys
import tempfile

ROOT = Path(__file__).resolve().parents[1]
CASES = {"panel": ("stress-panel.json", {"min_gates": 6, "min_draws": 12, "user_presets": 0}),
         "save": ("stress-save.json", {"min_gates": 1, "min_draws": 3, "user_presets": 1})}


def signature(manifest):
    return {"scenario_sha256": manifest["scenario_sha256"], "audio": manifest["audio"],
            "provenance": manifest["provenance"], "initial": manifest["initial"],
            "timeline_origin": manifest["timeline_origin"],
            "frames": manifest["screen"]["frames"], "events": manifest["events"],
            "final_state": manifest["final_state"], "timing": manifest["timing"]}


def health(manifest, checks):
    final = manifest["final_state"]
    if any(final[k] for k in ("playing", "active_voices", "gated_voices", "keys_mask", "buttons_mask")):
        raise ValueError("transport, input or voices did not release")
    if final["user_presets"] != checks["user_presets"]:
        raise ValueError("expected save operation was not observed")
    states = [e["state"] for e in manifest["events"]]
    if max(s["gated_voices"] for s in states) < checks["min_gates"]:
        raise ValueError("required simultaneous note load was not reached")
    if final["screen_draws"] - manifest["timeline_origin"]["screen_draws"] < checks["min_draws"]:
        raise ValueError("required panel redraw load was not reached")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--out", type=Path, help="new directory under build/")
    args = parser.parse_args()
    if args.out:
        out = args.out.resolve()
        if not out.is_relative_to(ROOT / "build") or out == ROOT / "build":
            raise ValueError("output must be a new directory under build/")
        out.mkdir(parents=True, exist_ok=False)
    else:
        (ROOT / "build/stress").mkdir(parents=True, exist_ok=True)
        out = Path(tempfile.mkdtemp(prefix="integrated-", dir=ROOT / "build/stress"))
    report = {"status": "running", "adapter": "tools/fm1_replay.py", "results": [],
              "device": "unmeasured", "instructions": "use direct host matrix; integrated fake clock is not a cost counter"}
    try:
        for name, (filename, checks) in CASES.items():
            manifests = []
            for repeat in range(2):
                destination = out / name / str(repeat)
                log = out / f"{name}-{repeat}.log"
                with log.open("wb") as stream:
                    subprocess.run([sys.executable, str(ROOT / "tools/fm1_replay.py"),
                                    str(ROOT / "tests/scenarios" / filename), "--out", str(destination)],
                                   cwd=ROOT, stdout=stream, stderr=subprocess.STDOUT, check=True, timeout=120)
                manifest = json.loads((destination / "manifest.json").read_text())
                health(manifest, checks)
                manifests.append(manifest)
            if signature(manifests[0]) != signature(manifests[1]):
                raise ValueError(f"{name}: repeated PCM, LCD or checkpoints differ")
            report["results"].append({"scenario": filename, "checks": checks,
                                      "pcm_sha256": manifests[0]["audio"]["pcm_sha256"],
                                      "manifest_sha256": [hashlib.sha256((out / name / str(i) / "manifest.json").read_bytes()).hexdigest() for i in range(2)]})
            print(f"stress integrated: {name}: repeated PCM/LCD/state and health ok", flush=True)
        report["status"] = "passed"
    except (ValueError, OSError, subprocess.SubprocessError) as error:
        report.update(status="failed", error=str(error))
        raise
    finally:
        (out / "report.json").write_text(json.dumps(report, indent=2) + "\n")
    print(f"stress integrated: PASS; evidence in {out}")


if __name__ == "__main__":
    main()
