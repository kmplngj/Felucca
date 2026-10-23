#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-3.0-only
"""Target-only CI checks, runnable from the workflow revision against older PR sources.

The workflow copies this file outside the source checkout before selecting its PR
revision. Build tools and firmware still come from that selected revision.
"""
import argparse
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import platform
import subprocess
import sys


def require_target_support(ci):
    if not all(callable(getattr(ci, name, None)) for name in ("engine_provenance", "resolved_identity")):
        raise ValueError("This historical revision lacks build-identity/pinned-engine provenance APIs; "
                         "use --validation full instead of target")


def preflight(ci):
    require_target_support(ci)
    from PIL import features
    if not features.check("raqm"):
        raise ValueError("Pillow needs Raqm for the reference font layout")
    tc = ci.build.toolchain()
    if tc.name != ci.TOOLCHAIN or "clang version 4.0.1" not in ci.build.tc("pi32v2/bin/clang", "--version"):
        raise ValueError(f"expected {ci.TOOLCHAIN}, JieLi Clang 4.0.1")
    ci.check_sdk(Path(os.environ["AC79_SDK"]))
    ci.engine_provenance()
    if not list((ci.build.SRC / "assets/samples-cc0/PIANO").glob("*.wav")):
        raise ValueError("required checked-in CC0 piano samples missing")
    if os.environ.get("GOLDEN_UPDATE") or os.environ.get("BUDGET_UPDATE"):
        raise ValueError("CI must never update goldens or budgets")


def provenance(ci):
    require_target_support(ci)
    import PIL
    import fontTools
    import brotli
    from PIL import features
    tc = ci.build.toolchain()
    data = {
        "revision": subprocess.check_output(["git", "rev-parse", "HEAD"], text=True).strip(),
        "built_at_utc": datetime.now(timezone.utc).isoformat(),
        "build_identity": ci.resolved_identity(),
        "runner": platform.platform(), "python": sys.version,
        "Pillow": PIL.__version__, "fontTools": fontTools.__version__, "Brotli": brotli.__version__,
        "ui_font": os.environ.get("FELUCCA_FONT", "m8stealth"),
        "raqm": features.version("raqm"), "freetype": features.version("freetype2"),
        "toolchain": tc.name, "compiler": ci.build.tc("pi32v2/bin/clang", "--version").strip(),
        "compiler_sha256": hashlib.sha256((tc / "pi32v2/bin/clang").read_bytes()).hexdigest(),
        "sdk_reference": ci.SDK_REF, "sdk_sha256": ci.build.SDK_SHA256,
        "build_flags": ci.build.CFLAGS, "selective_minsize": "tools/size_fns.py defaults",
        "engines": ci.engine_provenance(), "version": "",
        "sample_sha256": {str(p.relative_to(ci.build.SRC)): hashlib.sha256(p.read_bytes()).hexdigest()
                          for p in sorted((ci.build.SRC / "assets/samples-cc0").rglob("*.wav"))},
        "limitations": ["Target-only checks; no host, sanitizer, browser or reproducibility validation",
                        "Target instruction budgets are static estimates, not FM-1 cycle timing",
                        "No real-device audio, panel, USB/MIDI or flashing validation"],
    }
    if (ci.build.SRC / "profiles/catalog.json").is_file():
        import profile
        data["profile"] = json.loads(profile.generated(
            ci.build.SRC, os.environ.get("FELUCCA_PROFILE", "standard"))["resolved-profile.json"])
    output = ci.build.OUT / "ci/provenance.json"
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(data, indent=2) + "\n")


def package(ci, scope):
    output = ci.build.OUT
    record = output / "ci/provenance.json"
    data = json.loads(record.read_text())
    if scope == "target":
        require_target_support(ci)
    identity_api = getattr(ci, "resolved_identity", None)
    engine_api = getattr(ci, "engine_provenance", None)
    identity = identity_api() if callable(identity_api) else None
    revision = (identity["revision"] if identity is not None else
                subprocess.check_output(["git", "rev-parse", "HEAD"], text=True).strip())
    if (data["revision"] != revision or
            (identity is not None and data.get("build_identity") != identity) or
            (callable(engine_api) and data.get("engines") != engine_api())):
        raise ValueError("Package provenance differs from the selected sources")
    # Legacy full CI predates compiled identity and modular Engines provenance.
    # Keep its existing guarantees, but never silently weaken a target request.
    if identity is not None:
        built = json.loads((output / "build-identity.json").read_text())
        if built != identity:
            raise ValueError("Package build identity differs from provenance")
    profile_name = os.environ.get("FELUCCA_PROFILE", "standard")
    if profile_name != "standard" and (ci.build.SRC / "profiles/catalog.json").is_file():
        import profile
        expected = json.loads(profile.generated(ci.build.SRC, profile_name)["resolved-profile.json"])
        built_profile = json.loads((output / "gen/resolved-profile.json").read_text())
        target_profile = json.loads((output / "felucca.dis.profile.json").read_text())["resolved_profile"]
        if data.get("profile") != expected or built_profile != expected or target_profile != expected:
            raise ValueError("Package profile differs from provenance or selected sources")
    elif profile_name != "standard":
        raise ValueError("Selected sources do not support the requested profile")
    # fwsc is the installable app + loader, never the raw firmware binary.
    path = output / ("felucca.fwsc" if profile_name == "standard" else f"felucca-{profile_name}.fwsc")
    ci.fm1_install.load_package(path, False)
    digest = hashlib.sha256(path.read_bytes()).hexdigest()
    (output / "ci/package.sha256").write_text(f"{digest}  build/{path.name}\n")
    if scope == "target":
        data["validation"] = {
            "scope": "target",
            "target_checks": ["build/resource/loader guards", "static instruction budgets", "FWSC structure/CRC", "SHA-256"],
            "omitted": ["host", "sanitizer", "web/emulator/browser", "clean-checkout reproducibility"],
        }
        record.write_text(json.dumps(data, indent=2) + "\n")
    elif data.get("validation", {}).get("scope", "full") != "full":
        raise ValueError("Cannot label target-only provenance as full validation")
    print(f"Verified {scope} package: {path}; SHA-256 {digest}")


def cache_key(ci):
    """Invalidate downloaded inputs only for their actual pins/install recipe."""
    pins = {"toolchain": ci.TOOLCHAIN, "sdk_ref": ci.SDK_REF, "sdk_files": ci.build.SDK_SHA256,
            "installer": hashlib.sha256((ci.build.SRC / "tools/get_toolchain.sh").read_bytes()).hexdigest()}
    return hashlib.sha256(json.dumps(pins, sort_keys=True).encode()).hexdigest()


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("command", choices=("preflight", "provenance", "package", "cache-key"))
    parser.add_argument("--validation", choices=("target", "full"), default="target")
    args = parser.parse_args(argv)
    # Explicitly load build/CI code from the checked-out source, including old PRs
    # that predate this orchestration file. It must not be copied into their tree.
    sys.path.insert(0, str(Path.cwd() / "tools"))
    import ci
    try:
        if args.command == "cache-key":
            print(cache_key(ci))
        elif args.command == "package":
            package(ci, args.validation)
        else:
            if os.environ.get("VERSION"):
                raise ValueError("target-only validation cannot produce a release")
            (preflight if args.command == "preflight" else provenance)(ci)
    except (ValueError, KeyError, OSError, ci.fm1_install.InstallError) as error:
        parser.exit(2, f"error: {error}\n")


if __name__ == "__main__":
    main()
