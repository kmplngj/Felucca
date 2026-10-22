#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-3.0-only
# Copyright (C) 2026 Leo Kuroshita (@kurogedelic), Hügelton Instruments
"""Build Felucca: the app, the update loader and an installable .fwsc package.

  tools/build.py [--release X.Y[-suffix]] [--product FM-1_XXX]

Outputs in build/: felucca.bin (app), loader/ota.bin (update loader),
felucca.fwsc (package). A release build (--release X.Y) writes felucca-X.Y.fwsc and a folder
release-X.Y/ with the package, the app, SHA256SUMS, the sample attribution and the licence files.
--product sets the package identity (FELUCCA_ID and the package marker) explicitly; see BUILDING.md.
See BUILDING.md for the toolchain and the SDK.

The JieLi toolchain is Linux x86-64 only. JIELI_TOOLCHAIN points at it; on
macOS (or with JIELI_DOCKER=1) each tool runs in a linux/amd64 container.
"""
# Verified archives must not execute cached helpers before checking their source tree.
# os/sys are loaded by Python startup; defer all repository and other stdlib imports.
import os as _source_os
import sys as _source_sys

_source_root = _source_os.path.dirname(_source_os.path.dirname(_source_os.path.realpath(__file__)))
_source_verifier = None
if _source_os.path.isfile(_source_os.path.join(_source_root, "SOURCE-PINS.json")):
    _source_sys.dont_write_bytecode = True
    _source_os.environ["PYTHONDONTWRITEBYTECODE"] = "1"
    _source_import_paths = _source_sys.path[:]
    try:
        # The verifier uses only stdlib. Exclude archive paths while loading it,
        # so an unmanifested module cannot shadow a stdlib dependency either.
        _source_sys.path = [p for p in _source_import_paths
                            if not (_source_os.path.realpath(p or _source_os.getcwd()) == _source_root
                                    or _source_os.path.realpath(p or _source_os.getcwd()).startswith(_source_root + _source_os.sep))]
        _source_verifier_path = _source_os.path.join(_source_root, "tools", "source_archive.py")
        _source_verifier = {"__name__": "felucca_source_verifier", "__file__": _source_verifier_path}
        with open(_source_verifier_path, "rb") as _source_verifier_file:
            exec(compile(_source_verifier_file.read(), _source_verifier_path, "exec"), _source_verifier)
        _source_verifier["verify_tree"](_source_root)
    except (OSError, ValueError) as _source_error:
        raise SystemExit(str(_source_error))
    finally:
        _source_sys.path = _source_import_paths

import argparse
import hashlib
import json
import os
import platform
import re
import shutil
import struct
import subprocess
import sys
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

SRC = Path(__file__).resolve().parents[1]
FW = SRC / "firmware"
OUT = SRC / "build"
GEN = OUT / "gen"
LDR = OUT / "loader"
sys.path.insert(0, str(SRC / "tools"))
import fm1pkg_make  # noqa: E402
import lz4blk  # noqa: E402

APP_XIP = 0x02000120                # app.bin offset 0 in the XIP map; the SPL jumps here
APP_SLOT = fm1pkg_make.APP_SLOT
RAM_SPARE_MIN = 4096
POOL_SPARE_MIN = 8192
NOINIT_SPARE_MIN = 100              # B of app.ld's NOINIT region left unallocated (capacity plan rule A7, docs/flash-capacity.md)
# FELUCCA_CRASH_CTX=1 (hal/fm1_irq.h, #428): a diagnostic build whose crash record also keeps r0..r15, usp, ssp and
# their key (19 words). Only that build may take these bytes out of the floor; release and standard builds keep 100 B
CRASH_CTX_NOINIT = 76
DIAG_FLAGS = ("FELUCCA_CRASH_CTX", "FELUCCA_MUL64_REPRO")   # diagnostic builds for #425/#428: never a release
LOADER_LOAD = 0x01C0A800
LOADER_NAME = b"usb_hid_ota.bin"    # the file name the SPL looks for
DOCKER_IMAGE = os.environ.get("JIELI_DOCKER_IMAGE", "debian:bookworm-slim")
CFLAGS = ["-Os", "-ffunction-sections", "-fno-builtin", "-Wall", "-Wno-unused-function"]
LINE = re.compile(r"^\s*([0-9a-f]+):\s+((?:[0-9a-f]{2} )+)\s*\t(.*)$", re.I)

# SDK files of AC79NN_SDK_V1.2.1_2023-12-13 (the tested version)
SDK_SHA256 = {
    "uboot.boot": "4e3b4c220dc96641cb5a723f41e68ce41d5261ae9434bb33fbd7f2c59976ded4",
    "cfg_tool.bin": "276579954f076886a6a7694f65dc71c034a63a2c204b76749065c0ac7b010d1b",
    "cfg/eq_cfg_hw.bin": "41167491bffed4651750719c973d2758adeb9021a5670d02d6a53c85ed80ea7d",
}

DEV_PRODUCT = "FM-1_900"            # the development default identity; release builds are FM-1_9XY
PRODUCT = DEV_PRODUCT               # this build's package identity, set by main()
BUILD_IDENTITY = None               # one resolved input shared by generated UI and artifact sidecar
VERSION = None                      # FELUCCA_VERSION for release builds (default: firmware/src/felucca.c)
# FELUCCA_CPU2 (firmware/src/felucca.c), unset or 1, the default (1.6.1): the second core is built in, its entry and
# stacks (firmware/hal/fm1_cpu1.S) linked and its waiting loop (.c1_text) checked; MENU > SYSTEM > 2ND CORE starts it
# (OFF by default: one core, as 1.6). FELUCCA_CPU2=0: none of it is built (1.6's one-core code and RAM)
CPU2 = os.environ.get("FELUCCA_CPU2") != "0"

PRODUCT_RE = re.compile(r"FM-1_[A-Z0-9._-]{1,15}")    # 20 characters at most: the package marker's room;
# upper case only, so two products never name the same file on a case-insensitive file system
# identities an explicit --product must not take: the stock firmware's (the loader's USB identity
# "ota-FM-1_015" is derived from it, firmware/src/ota.c); the loader's own "ota-FM-1_900" never matches
RESERVED_PRODUCTS = ("FM-1_015",)


def check_product(product):
    """Raise SystemExit unless product is a package identity this build may use (syntax only: a valid
    identity is not registered with, or accepted by, any host or Hub)."""
    if not product.isascii() or not PRODUCT_RE.fullmatch(product):
        raise SystemExit(f"--product {product!r}: use FM-1_ and 1..15 of A-Z 0-9 . _ - (ASCII, 20 characters at most)")
    if product in RESERVED_PRODUCTS:
        raise SystemExit(f"--product {product}: reserved for the stock firmware / the update loader")
    if any((ord(c) + i + 1) & 0xFF == 0x7D for i, c in enumerate(product)):
        raise SystemExit(f"--product {product}: a character encodes to the unused package marker (0x7D)")


def resolve(argv):
    """Command line -> the build's identity and output names, before anything is generated or written.
    product: --product > the --release derived FM-1_9XY > DEV_PRODUCT.
    Only an explicit product that differs from the one the other options give is part of the output names,
    so two products at one display version keep separate files and the default names do not change."""
    ap = argparse.ArgumentParser()
    ap.add_argument("--release", metavar="X.Y", help="release build: identity FM-1_9XY, version string vX.Y")
    ap.add_argument("--product", metavar="FM-1_XXX",
                    help="package identity (FELUCCA_ID and package marker); default FM-1_9XY with --release, else FM-1_900")
    ap.add_argument("--sdk", type=Path, help="JieLi AC79 SDK checkout (default: $AC79_SDK)")
    a = ap.parse_args(argv)
    product, version, tag = DEV_PRODUCT, None, ""
    if a.release:                   # one digit each: the identity has room for two (X.Y.Z and X.Y.Z.W keep X.Y's)
        m = re.fullmatch(r"([0-9])\.([0-9])(?:\.[0-9]){0,2}(-[A-Za-z0-9]+)?", a.release)
        if not m:
            raise SystemExit(f"--release {a.release}: use X.Y, X.Y.Z, X.Y.Z.W or X.Y-suffix, one digit each")
        product = "FM-1_9" + m[1] + m[2]
        version = "v" + a.release.lower()      # e.g. v1.0, v1.1-rc1
    if a.product is not None:
        check_product(a.product)
        if a.product != product:
            tag = "-" + a.product
        product = a.product
    diag = [flag for flag in DIAG_FLAGS if os.environ.get(flag) == "1"]
    if a.release and diag:
        raise SystemExit(f"--release with a diagnostic build ({', '.join(diag)}=1): build the release without them")
    profile_name = os.environ.get("FELUCCA_PROFILE", "standard")
    if not re.fullmatch(r"[a-z0-9]+(?:-[a-z0-9]+)*", profile_name):
        raise SystemExit("invalid FELUCCA_PROFILE name")
    if profile_name != "standard":
        if a.release and (a.product is None or not tag):
            raise SystemExit("non-standard release profile requires a distinct --product identity")
        tag += "-" + profile_name
    base = f"felucca-{a.release}{tag}" if a.release else f"felucca{tag}"
    return {"product": product, "version": version, "release": a.release, "sdk": a.sdk,
            "explicit": a.product is not None, "name": base + ".fwsc",
            "rel": f"release-{a.release}{tag}", "app": f"{base}-app.bin"}


def toolchain():
    tc = os.environ.get("JIELI_TOOLCHAIN")
    if not tc or not (Path(tc) / "pi32v2" / "bin" / "clang").exists():
        raise SystemExit("JIELI_TOOLCHAIN must point at the JieLi Linux toolchain "
                         "(the directory with pi32v2/ and common/; see tools/get_toolchain.sh)")
    return Path(tc).resolve()


def use_docker():
    native = platform.system() == "Linux" and platform.machine() in ("x86_64", "AMD64")
    return os.environ.get("JIELI_DOCKER", "0" if native else "1") == "1"


def tc(tool, *args):
    """run a toolchain binary (pi32v2/bin/..., common/bin/...) with cwd SRC; paths relative to SRC"""
    rel = [str(Path(a).resolve().relative_to(SRC)) if isinstance(a, Path) else a for a in args]
    if tool == "cc":                # the toolchain's cc wrapper needs python3; call clang directly
        tool, rel = "pi32v2/bin/clang", ["-target", "pi32v2", *rel]
    if use_docker():
        cmd = ["docker", "run", "--rm", "--platform", "linux/amd64", "-v", f"{SRC}:/work",
               "-v", f"{toolchain()}:/opt/jieli:ro", "-w", "/work", DOCKER_IMAGE, f"/opt/jieli/{tool}", *rel]
    else:
        cmd = [str(toolchain() / tool), *rel]
    r = subprocess.run(cmd, cwd=SRC, capture_output=True, text=True)
    if r.returncode:
        sys.stderr.write(r.stdout + r.stderr)
        raise SystemExit(f"build: {tool} failed")
    if r.stderr.strip():
        sys.stderr.write(r.stderr)
    return r.stdout


def tc_all(*cmds):
    with ThreadPoolExecutor(len(cmds)) as ex:
        return list(ex.map(lambda c: tc(*c), cmds))


def generate():
    """generated headers (UI fonts, icons, keycaps, palettes, tables, samples)"""
    font = os.environ.get("FELUCCA_FONT", "m8stealth")
    if font not in ("inter-tight", "tamzen", "m8stealth"):
        raise SystemExit("FELUCCA_FONT must be inter-tight, tamzen or m8stealth")
    from build_identity import write as write_identity
    write_identity(SRC, GEN, VERSION, BUILD_IDENTITY)
    from profile import generated
    selection = generated(SRC, os.environ.get("FELUCCA_PROFILE", "standard"))
    resolved = json.loads(selection["resolved-profile.json"])
    for name, content in selection.items():
        GEN.mkdir(parents=True, exist_ok=True)
        (GEN / name).write_text(content)
    print(f"Engine profile: {os.environ.get('FELUCCA_PROFILE', 'standard')}")
    GEN.mkdir(parents=True, exist_ok=True)
    for old in ("felucca_font.h", "felucca_icons.h"):     # headers of the bitmap font and icon atlas
        (GEN / old).unlink(missing_ok=True)
    tools = SRC / "tools"
    font_cmd = ([tools / "gen_bitmap_font.py", GEN / "ui_fonts.h", "--preset", font] if font != "inter-tight" else
                [tools / "gen_aa_font.py", GEN / "ui_fonts.h", "--preset", "inter-tight"])
    print(f"UI font: {font}")
    cmds = [font_cmd,
            [tools / "gen_aa_icons.py", GEN / "ui_icons.h"],
            [tools / "gen_aa_keycaps.py", GEN / "ui_keycaps.h"],
            [tools / "gen_ui_palettes.py", GEN / "ui_palettes.h"],
            [tools / "gen_tables.py", GEN / "felucca_tables.h"],
            [tools / "gen_fm6_patches.py", GEN / "felucca_fm6.h"],
            [tools / "gen_samples.py", GEN / "felucca_samples.h"]]
    if 14 in resolved["engine_ids"]:
        cmds += [[tools / "gen_braids.py", GEN / "felucca_braids.h"],
                 [tools / "gen_macro.py", GEN / "felucca_macro.h"]]
    else:
        for old in ("felucca_braids.h", "felucca_macro.h"):
            (GEN / old).unlink(missing_ok=True)
    procs = [subprocess.Popen([sys.executable, *map(str, c)], stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                              text=True) for c in cmds]
    failed = []
    for c, p in zip(cmds, procs):
        sys.stdout.write(p.communicate()[0])
        if p.returncode:
            failed.append(c[0].name)
    if failed:
        raise SystemExit(f"build: {', '.join(failed)} failed")


# ---- update loader

def crc16(d, c=0):
    for b in d:
        c ^= b << 8
        for _ in range(8):
            c = ((c << 1) ^ 0x1021) if c & 0x8000 else c << 1
        c &= 0xFFFF
    return c


def ldr_head(dcrc, a, b, attr, name):
    body = struct.pack("<HIIBBH16s", dcrc, a, b, attr, 0, 0, name)
    return struct.pack("<H", crc16(body)) + body


def ldr_wrap(image):
    """ota.bin = outer JLFS head (32 B) + inner head (32 B, load address) +
    blocks [clen u32][dlen u32][LZ4 block], dlen 4096 except the last"""
    blocks = bytearray()
    for i in range(0, len(image), 4096):
        raw = image[i:i + 4096]
        c = lz4blk.compress(raw)
        if len(c) > 4096 or lz4blk.decompress(c) != raw:
            raise SystemExit(f"loader: block {i // 4096} does not compress below 4096 B")
        blocks += struct.pack("<II", len(c), len(raw)) + c
    inner = ldr_head(crc16(image), len(image), LOADER_LOAD, 0, LOADER_NAME)
    body = inner + bytes(blocks)
    return ldr_head(crc16(body), 0x20, len(body), 0x41, LOADER_NAME) + body


def loader_check(hdr, syms):
    """Check allocated loader sections and startup symbols against loader.ld's RAM window."""
    errors, text_start, text_end = [], None, None
    lo, hi = LOADER_LOAD, LOADER_LOAD + 0x14000
    for line in hdr.splitlines():
        p = line.split()
        if len(p) < 2 or not p[0].isdigit() or not p[1].startswith("."):
            continue
        try:
            size, addr = int(p[2], 16), int(p[3], 16)
            if size < 0 or addr < 0:
                raise ValueError
        except (ValueError, IndexError):
            errors.append(f"loader: malformed section row: {line.strip()}")
            continue
        allocated = p[1] in (".text", ".bss", ".data", ".ram_text") or bool(set(p[4:]) & {"TEXT", "DATA", "BSS"})
        if allocated and size and not (lo <= addr and addr + size <= hi):
            errors.append(f"loader: section {p[1]} [{addr:#x}, {addr + size:#x}) is outside RAM [{lo:#x}, {hi:#x})")
        if p[1] == ".text" and size:
            text_start = addr
            text_end = addr + size
    if text_end is None:
        errors.append("loader: missing or empty .text section")
    elif text_start != lo:
        errors.append(f"loader: .text does not start at {lo:#x}")
    values = {}
    for name in ("_start", "_bss_start", "_bss_end"):
        m = re.search(r"^([0-9a-fA-F]+) .*\s" + name + r"$", syms, re.M)
        if m:
            values[name] = int(m.group(1), 16)
        else:
            errors.append(f"loader: missing symbol {name}")
    if "_start" in values and values["_start"] != lo:
        errors.append(f"loader: _start is not at {lo:#x}")
    if "_bss_start" in values and "_bss_end" in values:
        start, end = values["_bss_start"], values["_bss_end"]
        if not (lo <= start <= end <= hi) or (text_end is not None and start < text_end):
            errors.append("loader: BSS symbols are outside RAM, reversed or overlap .text")
    return errors


def build_loader():
    LDR.mkdir(parents=True, exist_ok=True)
    src = FW / "loader"
    flags = [*CFLAGS, "-Ifirmware/hal", "-Ifirmware/src"]
    tc_all(("cc", "-c", src / "crt0_ldr.S", "-o", LDR / "crt0_ldr.o"),
           ("cc", *flags, "-c", src / "loader.c", "-o", LDR / "loader.o"))
    elf = LDR / "loader.elf"
    tc("pi32v2/bin/ld", "--gc-sections", "-e", "_start", "-T", src / "loader.ld",
       LDR / "crt0_ldr.o", LDR / "loader.o", "-o", elf)
    _, dis, hdr, syms = tc_all(("common/bin/objcopy", "-O", "binary", "-j", ".text", elf, LDR / "loader.bin"),
                               ("common/bin/objdump", "-d", elf),
                               ("common/bin/objdump", "-h", elf),
                               ("common/bin/objdump", "-t", elf))
    (LDR / "loader.dis").write_text(dis)
    errors = loader_check(hdr, syms)
    if errors:
        raise SystemExit("\n".join(errors))
    image = (LDR / "loader.bin").read_bytes()
    if not image or len(image) > 0x14000:
        raise SystemExit("loader: image empty or too big")
    ota = ldr_wrap(image)
    (LDR / "ota.bin").write_bytes(ota)
    bss = [int(ln.split()[0], 16) for ln in syms.splitlines() if ln.rstrip().endswith("_bss_end")]
    print(f"loader: image {len(image)} B at {LOADER_LOAD:#x}" + (f", bss end {bss[0]:#x}" if bss else ""))
    print(f"loader: ota.bin {len(ota)} B")
    return ota


# ---- app

def noinit_used(hdr, syms, org):
    """Bytes of the NOINIT region in use, or None without a .noinit section: the larger of the section's end in
    `objdump -h` (covers allocations that carry no sized symbol, such as `.space` data or tail padding) and the
    end of the highest .noinit object in `objdump -t`"""
    ends = []
    for p in map(str.split, hdr.splitlines()):
        if len(p) >= 4 and p[0].isdigit() and p[1] == ".noinit" and re.fullmatch(r"[0-9a-f]+", p[2] + p[3]):
            ends.append(int(p[3], 16) + int(p[2], 16))
    if not ends:
        return None
    ends += [int(p[0], 16) + int(p[-2], 16) for p in map(str.split, syms.splitlines())
             if len(p) >= 5 and p[-3] == ".noinit" and re.fullmatch(r"[0-9a-f]+", p[0] + p[-2])]
    return max(ends) - org


def ld_regions():
    """firmware/app.ld's MEMORY regions: name -> (origin, length)"""
    regs = {}
    for m in re.finditer(r"^\s*(\w+)\s*\([rwx]+\)\s*:\s*ORIGIN\s*=\s*(\w+),\s*LENGTH\s*=\s*(\w+)",
                         (FW / "app.ld").read_text(), re.M):
        n = m.group(3)
        regs[m.group(1)] = (int(m.group(2), 0), int(n[:-1], 0) * 1024 if n.endswith("K") else int(n, 0))
    return regs


def app_flags():
    flags = [*CFLAGS, "-Ifirmware/hal", "-Ifirmware/src", "-Ibuild/gen"]
    for flag in ("FELUCCA_FLASH", "FELUCCA_OTA", "FELUCCA_OTA_DRYRUN", "FELUCCA_OTA_RAMONLY", "FELUCCA_CDC",
                 "FELUCCA_UART", "FELUCCA_UAC", "FELUCCA_UAC_TONE", "FELUCCA_UAC_48K", "FELUCCA_ICONS", "FELUCCA_SLICE", "FELUCCA_FM4",
                 "FELUCCA_CDC_DEFAULT", "FELUCCA_UAC_AS_FIRST", "FELUCCA_CPU2", "FELUCCA_ISR_ASSERT",
                 "FELUCCA_CRASH_CTX", "FELUCCA_MUL64_REPRO"):
        v = os.environ.get(flag)    # unset: the default in firmware/src/felucca.c
        if v in ("0", "1"):
            flags.append(f"-D{flag}={v}")
    v = os.environ.get("FELUCCA_USB_LAYOUT")   # firmware/src/usb.c: how the USB composite presents itself (#67), 0..3
    if v in ("0", "1", "2", "3"):
        flags.append(f"-DFELUCCA_USB_LAYOUT={v}")
    flags.append(f'-DFELUCCA_ID="{PRODUCT}"')
    if VERSION:
        flags.append(f'-DFELUCCA_VERSION="{VERSION}"')
    return flags


def build_app():
    flags = app_flags()
    # felucca.c goes to LLVM IR without the optimizer, the main-loop functions (UI, stores, editor) are
    # marked minsize (tools/size_fns.py), then the IR is compiled at -Os. FELUCCA_SIZE=0: -Os everywhere
    size = os.environ.get("FELUCCA_SIZE") != "0"
    cmain = (("cc", *flags, "-S", "-emit-llvm", "-Xclang", "-disable-llvm-optzns", "-c",
              FW / "src" / "felucca.c", "-o", OUT / "felucca.ll") if size else
             ("cc", *flags, "-c", FW / "src" / "felucca.c", "-o", OUT / "felucca.o"))
    (OUT / "fm1_cpu1.o").unlink(missing_ok=True)
    tc_all(("cc", "-c", FW / "crt0.S", "-o", OUT / "crt0.o"),
           ("cc", "-c", FW / "hal" / "fm1_vec.S", "-o", OUT / "fm1_vec.o"),
           ("cc", "-c", FW / "hal" / "fm1_isr.S", "-o", OUT / "fm1_isr.o"),
           *([("cc", "-c", FW / "hal" / "fm1_cpu1.S", "-o", OUT / "fm1_cpu1.o")] if CPU2 else []),
           cmain)
    if size:
        subprocess.run([sys.executable, SRC / "tools" / "size_fns.py", OUT / "felucca.ll", OUT / "felucca_size.ll"],
                       check=True)
        tc("cc", *[f for f in flags if not f.startswith(("-I", "-D", "-W"))], "-c",
           OUT / "felucca_size.ll", "-o", OUT / "felucca.o")
    elf = OUT / "felucca.elf"
    tc("pi32v2/bin/ld", "-T", FW / "app.ld", OUT / "crt0.o", OUT / "fm1_vec.o", OUT / "fm1_isr.o",
       *([OUT / "fm1_cpu1.o"] if CPU2 else []), OUT / "felucca.o", "-o", elf)
    for sect in ("text.bin", "data.bin", "ramtext.bin", "c1text.bin"):
        (OUT / sect).unlink(missing_ok=True)
    *_, hdr, syms, dis, rt = tc_all(("common/bin/objcopy", "-O", "binary", "-j", ".text", elf, OUT / "text.bin"),
                               ("common/bin/objcopy", "-O", "binary", "-j", ".data", elf, OUT / "data.bin"),
                               ("common/bin/objcopy", "-O", "binary", "-j", ".ram_text", elf, OUT / "ramtext.bin"),
                               *([("common/bin/objcopy", "-O", "binary", "-j", ".c1_text", elf, OUT / "c1text.bin")]
                                 if CPU2 else []),
                               ("common/bin/objdump", "-h", elf),
                               ("common/bin/objdump", "-t", elf),
                               ("common/bin/objdump", "-d", elf),
                               ("common/bin/objdump", "-d", "-j", ".ram_text", *(("-j", ".c1_text") if CPU2 else ()),
                                elf))
    dis_path = OUT / "felucca.dis"
    dis_path.write_text(dis)
    # Preserved disassembly must carry the selection that produced these exact bytes.
    dis_path.with_suffix(".dis.profile.json").write_text(json.dumps({
        "schema_version": 1,
        "dis_sha256": hashlib.sha256(dis_path.read_bytes()).hexdigest(),
        "resolved_profile": json.loads((GEN / "resolved-profile.json").read_text()),
    }, indent=2, sort_keys=True) + "\n")

    def symv(name):
        return int(re.search(r"^([0-9a-f]+) .*\s" + name + r"$", syms, re.M).group(1), 16)
    img = bytearray((OUT / "text.bin").read_bytes())
    # .ram_text, .c1_text and .data follow .text at their load addresses; crt0 / main copy them by words
    for sect, lname in (("ramtext.bin", "_rt_load"), ("c1text.bin", "_c1_load"), ("data.bin", "_data_load")):
        load = symv(lname)
        if load % 4:
            raise SystemExit(f"{lname} {load:#x} is not word aligned")
        blob = (OUT / sect).read_bytes() if (OUT / sect).exists() else b""
        if blob:
            if load - APP_XIP < len(img):
                raise SystemExit(f"{lname} overlaps the image")
            img += b"\xff" * (load - APP_XIP - len(img))
            img += blob
    img += b"\xff" * (-len(img) % 4)
    (OUT / "felucca.bin").write_bytes(img)
    return bytes(img), hdr, syms, dis, rt


def objdump_data_row(line):
    """Recognize pi32v2's ASCII and scalar data displays, checking their byte values."""
    m = re.match(r"^\s*[0-9a-f]+:\t ((?:[0-9a-f]{2} ){1,8})( {2,}.*)$", line, re.I)
    if m:
        ascii_text = "".join(chr(v) if 32 <= v <= 126 else "." for v in bytes.fromhex(m[1]))
        padding = m[2][:-len(ascii_text)]
        if m[2].endswith(ascii_text) and len(padding) >= 2 and not padding.strip():
            return True
    m = re.match(r"^\s*[0-9a-f]+:\s+((?:[0-9a-f]{2} ){1,4})\s+< (\d+) : (0x[0-9a-f]+) >$", line, re.I)
    return bool(m and int.from_bytes(bytes.fromhex(m[1]), "little") == int(m[2]) == int(m[3], 16))


def disassembly_rows(text, label, empty_ok=False):
    """Parsed address rows; an empty RAM section needs actual objdump header output."""
    rows, errors = [], []
    for line in text.splitlines():
        m = LINE.match(line)
        if m and m.group(3).strip():
            if label in (".ram_text", ".c1_text") and re.match(r"^(?:\.\w+|\(bad\)|unknown\b)", m.group(3).strip(), re.I):
                errors.append(f"{label}: undecoded instruction row: {line.strip()}")
            rows.append(m)
        elif label == "app" and objdump_data_row(line):
            continue                # .text also holds tables; RAM flash-busy code must decode
        elif re.match(r"^\s*[0-9a-f]+:", line, re.I):
            errors.append(f"{label}: malformed instruction row: {line.strip()}")
        elif label in (".ram_text", ".c1_text") and line.strip() and not (
                re.fullmatch(r".*file format ELF32-pi32v2", line.strip()) or
                line.strip() == f"Disassembly of section {label}:" or
                re.fullmatch(r"(?:[0-9a-f]+ <[^>]+>|[^\s:]+):", line.strip(), re.I)):
            errors.append(f"{label}: malformed disassembly line: {line.strip()}")
    if not rows:
        lines = [line.strip() for line in text.splitlines() if line.strip()]
        header = any(re.fullmatch(r".*file format ELF32-pi32v2", line) for line in lines)
        header_only = all(re.fullmatch(r".*file format ELF32-pi32v2", line) or
                          line == f"Disassembly of section {label}:" for line in lines)
        if not (empty_ok and header and header_only and not errors):
            errors.append(f"missing or malformed {label} disassembly")
    return rows, errors


def ram_text_empty(hdr, syms):
    """True only with ELF proof of emptiness; False for conflicting/nonempty evidence, None if unavailable."""
    evidence = []
    for p in map(str.split, hdr.splitlines()):
        if len(p) >= 2 and p[0].isdigit() and p[1] == ".ram_text":
            evidence.append(len(p) >= 4 and bool(re.fullmatch(r"[0-9a-f]+", p[2], re.I)) and int(p[2], 16) == 0)
    bounds = [re.search(r"^([0-9a-f]+) .*\s" + name + r"$", syms, re.M | re.I)
              for name in ("_rt_start", "_rt_end")]
    if any(re.search(r"\s" + name + r"$", syms, re.M) for name in ("_rt_start", "_rt_end")):
        evidence.append(all(bounds) and int(bounds[0][1], 16) == int(bounds[1][1], 16))
    return all(evidence) if evidence else None


def check(img, hdr, syms, dis, rt, *, resources=None):
    errors, notes = [], []
    m = re.search(r"^([0-9a-f]+) .*\s_start$", syms, re.M)
    if not m or int(m.group(1), 16) != APP_XIP:
        errors.append(f"_start is not at {APP_XIP:#x}")
    if img[:4] != bytes.fromhex("04818000"):
        errors.append(f"image starts with {img[:4].hex()}, not the entry stub")
    app_rows, app_errors = disassembly_rows(dis, "app")
    sections, preamble = {}, []
    section = None
    for line in rt.splitlines():
        match = re.match(r"^Disassembly of section (\S+):", line)
        if match:
            section = match.group(1)
        if section:
            sections.setdefault(section, []).append(line)
        else:
            preamble.append(line)
    unexpected = set(sections) - {".ram_text", ".c1_text"}
    if unexpected:
        errors.append(f"unexpected RAM disassembly sections: {sorted(unexpected)}")
    rt_text = "\n".join(preamble + sections.get(".ram_text", [])) if sections else rt
    c1_text = "\n".join(sections.get(".c1_text", []))
    empty = ram_text_empty(hdr, syms)
    # objdump omits an empty .ram_text when .c1_text is present. Keep the file
    # header, but require ELF evidence before accepting that missing section.
    # Preserve standalone header-only fixtures unless the ELF says nonempty.
    rt_rows, rt_errors = disassembly_rows(rt_text, ".ram_text",
                                         empty_ok=empty is True or (not sections and empty is None))
    c1_rows, c1_errors = disassembly_rows(c1_text, ".c1_text") if c1_text or CPU2 else ([], [])
    errors += app_errors + rt_errors + c1_errors
    rt_calls = [ln for ln in rt_text.splitlines() if re.search(r"\bcall\b", ln)]
    c1_calls = [ln for ln in c1_text.splitlines() if re.search(r"\bcall\b", ln)
                and not re.search(r"\bcall\s+r\d+\b", ln)]
    c1_insns = len(c1_rows)
    if rt_calls:
        errors.append(f".ram_text contains calls: {rt_calls[:3]}")
    elif not rt_errors:
        notes.append(f".ram_text: {len(rt_rows)} insns, no calls")
    c1_syms = re.findall(r"\s(fm1_c1_\w+|_c1_ustack\w*|_c1_sstack\w*)$", syms, re.M)
    if not CPU2:                    # FELUCCA_CPU2=0: nothing of the second core (no stack, waiting loop, mailbox)
        if c1_insns or c1_syms:
            errors.append(f"FELUCCA_CPU2=0 build holds second-core code or data: {sorted(set(c1_syms))[:4]}")
        else:
            notes.append("one core: no second-core code, stack or mailbox")
    elif c1_calls:
        errors.append(f".c1_text calls other than its job: {c1_calls[:3]}")
    elif not c1_insns:
        errors.append(".c1_text: the second core's waiting loop is missing (firmware/hal/fm1_cpu1.h fm1_c1_main)")
    else:
        notes.append(f".c1_text: {c1_insns} insns, only its job called")
    for mm in app_rows:             # nothing may call or load an address in the chip ROM
        for v in re.findall(r"(?<![<>=!+*/%&|^-])=\s*(-?(?:0x[0-9a-f]+|\d+))\b|\bcall -?\d+ <[^:>]*: ([0-9a-f]+) >", mm.group(3), re.I):
            val = (int(v[0], 16 if "0x" in v[0].lower() else 10) & 0xFFFFFFFF) if v[0] else int(v[1], 16) & 0xFFFFFFFF
            if 0xFFC00000 <= val < 0xFFD00000:
                errors.append(f"reference to ROM address {val:#010x}")
    if len(img) > APP_SLOT:
        errors.append(f"image {len(img)} B exceeds the app slot")

    def sym(name):
        mm = re.search(r"^([0-9a-f]+) .*\s" + name + r"$", syms, re.M)
        if not mm:
            errors.append(f"missing symbol {name}")
            return None
        return int(mm.group(1), 16)
    try:
        region = ld_regions()
    except (OSError, ValueError) as e:
        errors.append(f"app.ld: invalid memory regions: {e}")
        return errors, notes
    if any(name not in region or region[name][1] <= 0 for name in ("RAM", "POOL", "NOINIT")):
        errors.append("app.ld: missing or empty RAM/POOL/NOINIT region")
        return errors, notes
    ram_org, ram_len = region["RAM"]
    pool_org, pool_len = region["POOL"]
    noinit_org, noinit_len = region["NOINIT"]
    bss_end, pool_start, pool_end = sym("_bss_end"), sym("_pool_start"), sym("_pool_end")
    if None in (bss_end, pool_start, pool_end):
        return errors, notes
    bss, pool = bss_end - ram_org, pool_end - pool_start
    if bss < 0 or pool_start != pool_org or pool < 0:
        errors.append("RAM/POOL symbols are outside their regions or reversed")
    noinit = noinit_used(hdr, syms, noinit_org)  # app.ld defines no NOINIT symbols; the section's end gives the extent
    if noinit is None:
        errors.append("missing .noinit section")
        return errors, notes
    if noinit < 0 or noinit > noinit_len:
        errors.append("NOINIT section is outside its region")
    notes.append(f"image {len(img)} B; RAM .data+.bss {bss} B of {ram_len}; pool {pool} B of {pool_len}; "
                 f"NOINIT {noinit} B of {noinit_len} ({noinit_len - noinit} B spare)")
    if region["RAM"][0] + ram_len != region["POOL"][0]:
        errors.append("app.ld: POOL does not start where RAM ends")
    if ram_len - bss < RAM_SPARE_MIN:                      # keep >= 4 KiB of .bss spare (state the audio side touches)
        errors.append(f"RAM headroom {ram_len - bss} B < 4096 B")
    if pool_len - pool < POOL_SPARE_MIN:                    # keep >= 8 KiB of the pool spare
        errors.append(f"pool headroom {pool_len - pool} B < 8192 B")
    floor = NOINIT_SPARE_MIN - (CRASH_CTX_NOINIT if os.environ.get("FELUCCA_CRASH_CTX") == "1" else 0)
    if noinit_len - noinit < floor:               # NOINIT gets no new users (A7): keep >= 100 B unallocated
        errors.append(f"NOINIT headroom {noinit_len - noinit} B < {floor} B")
    elif floor != NOINIT_SPARE_MIN:
        notes.append(f"NOINIT floor {floor} B: FELUCCA_CRASH_CTX=1 diagnostic build ({CRASH_CTX_NOINIT} B register "
                     f"context; release/standard builds keep {NOINIT_SPARE_MIN} B)")
    if resources is not None:
        for name, used, origin, capacity, minimum, authority in (
                ('app', len(img), APP_XIP, APP_SLOT, 0, 'tools/build.py APP_SLOT'),
                ('RAM', bss, ram_org, ram_len, RAM_SPARE_MIN, 'tools/build.py check'),
                ('POOL', pool, pool_org, pool_len, POOL_SPARE_MIN, 'tools/build.py check'),
                ('NOINIT', noinit, noinit_org, noinit_len, floor, 'tools/build.py check')):
            resources[name] = dict(origin=origin, capacity_bytes=capacity, used_bytes=used,
                                   spare_bytes=capacity-used, enforced_spare_min_bytes=minimum,
                                   margin_bytes=capacity-used-minimum, authority=authority)
    return errors, notes


# Every hardware register access lives in hal/. In src/, engines/src/ and loader/ (comments stripped):
#  - no volatile pointer cast, except of a C object's address (`*(volatile T *)&x`: a read-once
#    of a RAM flag shared with an ISR, e.g. usb.c ota_wire_send);
#  - no literal in a register or reserved window (core SFRs 0x10000-0x13FFF, SFC 0x40000-0x43FFF,
#    GPIO/IOMAP 0x50000-0x51FFF, CPU 0x1EE0000-0x1EEFFFF, RAM top 0x01C7F000- (boot info,
#    mailbox, vectors), XIP 0x02000000-0x020FFFFF);
#  - no inline asm, except the empty compiler barrier RING_PUBLISH() (emits no instruction);
#  - no HAL register macro (a hal/ #define that is, or expands to, a volatile access).
# Linker symbols (_bss_start[], _rt_load[], ...) are plain C objects and pass.
MMIO_LIT = re.compile(r"\b0x0*(1[0-3][0-9a-f]{3}|4[0-3][0-9a-f]{3}|5[01][0-9a-f]{3}|1ee[0-9a-f]{4}|"
                      r"1c7f[0-9a-f]{3}|20[0-9a-f]{5})u?l?\b", re.I)
MMIO_CAST = re.compile(r"\(\s*(?:const\s+)?volatile\b[^()]*\*\s*\)(?!\s*&)")
MMIO_ASM = re.compile(r"\b(?:__asm__|asm)\b(?!\s+volatile\s*\(\s*\"\"\s*:::\s*\"memory\"\s*\))")


def mmio_check():
    def strip(s):
        s = re.sub(r"/\*.*?\*/", lambda m: "\n" * m.group(0).count("\n"), s, flags=re.S)
        return re.sub(r"//[^\n]*", "", s)
    defs = {}
    for h in sorted((FW / "hal").glob("*.h")):
        for m in re.finditer(r"^#define\s+(\w+)(?:\([^)]*\))?\s+(.*)$", strip(h.read_text()).replace("\\\n", " "), re.M):
            defs[m.group(1)] = m.group(2)
    regs = {n for n, b in defs.items() if re.search(r"\bvolatile\b", b)}
    while True:                                   # macros built on register macros (FM1_WR_LIMIT_H -> FM1_X2)
        more = {n for n, b in defs.items() if n not in regs and set(re.findall(r"\w+", b)) & regs}
        if not more:
            break
        regs |= more
    errors = []
    for f in sorted([*(FW / "src").glob("*.[ch]"), *(FW / "engines" / "src").glob("*.[ch]"),
                     *(FW / "loader").glob("*.c")]):
        for no, ln in enumerate(strip(f.read_text()).splitlines(), 1):
            where = f"{f.relative_to(FW)}:{no}"
            for rx, what in ((MMIO_LIT, "register/window address"), (MMIO_CAST, "volatile pointer cast"),
                             (MMIO_ASM, "inline asm")):
                m = rx.search(ln)
                if m:
                    errors.append(f"{where}: {what} outside hal/ ({m.group(0).strip()}); add a hal/ helper")
            used = set(re.findall(r"\b[A-Z_][A-Z0-9_]*\b", ln)) & regs
            if used:
                errors.append(f"{where}: HAL register macro {sorted(used)[0]} outside hal/; use a hal/ helper")
    return errors


def main(argv=None):
    global PRODUCT, VERSION, BUILD_IDENTITY
    try:
        c = resolve(sys.argv[1:] if argv is None else argv)  # validated before any job starts
    except SystemExit as error:
        if error.code:  # --help is read-only; invalid build arguments invalidate old evidence.
            (OUT / 'resource-report.json').unlink(missing_ok=True)
        raise
    (OUT / 'resource-report.json').unlink(missing_ok=True)
    PRODUCT, VERSION, name = c["product"], c["version"], c["name"]
    if _source_verifier is not None:
        _source_verifier["verify_tree"](SRC)
    from profile import validate_selection
    try:
        validate_selection(SRC, os.environ.get("FELUCCA_PROFILE", "standard"))  # before jobs/writes
    except (ValueError, KeyError, OSError) as error:
        raise SystemExit(f"profile: {error}")
    from build_identity import resolve as resolve_identity
    BUILD_IDENTITY = resolve_identity(SRC, VERSION)  # reject unverified PR metadata before jobs/writes
    fm1pkg_make.SDK = c["sdk"]
    if not (FW / "engines" / "src" / "felucca_engine.h").exists():
        raise SystemExit("firmware/engines is empty: the Felucca-Engines submodule "
                         "(git submodule update --init, or clone with --recurse-submodules)")
    for rel, sha in SDK_SHA256.items():          # fail early without the SDK
        if hashlib.sha256(fm1pkg_make.sdk_file(rel)).hexdigest() != sha:
            print(f"warning: SDK {rel} differs from AC79NN_SDK_V1.2.1; the package will not match the reference")
    OUT.mkdir(parents=True, exist_ok=True)
    import build_report
    report_sources = build_report.input_hashes(SRC, include_generated=False)
    report_tools = build_report.tool_fingerprints(sys.modules[__name__])
    with ThreadPoolExecutor(2) as ex:
        gen, ldr = ex.submit(generate), ex.submit(build_loader)
        gen.result()
        ota = ldr.result()
    from profile import contract_json
    (OUT / 'profile-contract.json').write_text(contract_json(SRC))
    report_inputs = build_report.input_hashes(SRC)
    report_config = build_report.configuration(sys.modules[__name__])
    build_report.check_initial_inputs(sys.modules[__name__], report_sources, report_tools)
    img, hdr, syms, dis, rt = build_app()
    errors, notes = check(img, hdr, syms, dis, rt)
    hal_err = mmio_check()
    errors += hal_err
    if not hal_err:
        notes.append("register access: hal/ only (src/, engines/src/, loader/ clean)")
    for n in notes:
        print("  ok   ", n)
    for e in errors:
        print("  FAIL ", e)
    if errors:
        raise SystemExit("build: checks failed")
    pkg = fm1pkg_make.ufw(fm1pkg_make.flash_image(img, fm1pkg_make.KEY), ota, PRODUCT)
    (OUT / name).write_bytes(pkg)
    att = SRC / "assets" / "samples-cc0" / "ATTRIBUTION.txt"
    if att.exists():
        shutil.copy(att, OUT / "ATTRIBUTION.txt")
    if os.environ.get("GITHUB_ACTIONS") == "true" and (OUT / "ci/provenance.json").is_file():
        recorded = json.loads((OUT / "ci/provenance.json").read_text())
        if recorded.get("build_identity") != BUILD_IDENTITY:
            raise SystemExit("CI provenance differs from the compiled build identity")
    shutil.copy(GEN / "build-identity.json", OUT / "build-identity.json")
    build_report.write(sys.modules[__name__], (img, hdr, syms, dis, rt), name,
                       report_inputs, report_config)
    print(f"app      {OUT / 'felucca.bin'}  {len(img)} B")
    print(f"loader   {LDR / 'ota.bin'}  {len(ota)} B")
    print(f"package  {OUT / name}  {len(pkg)} B, identity {PRODUCT}" + (" (--product)" if c["explicit"] else ""))
    if c["release"]:                   # what a release carries: the package, the app and every licence they need
        rel = OUT / c["rel"]
        shutil.rmtree(rel, ignore_errors=True)
        (rel / "LICENSES").mkdir(parents=True)
        shutil.copy(GEN / "resolved-profile.json", rel / "resolved-profile.json")
        shutil.copy(GEN / "build-identity.json", rel / "build-identity.json")
        shutil.copy(OUT / 'resource-report.json', rel / 'resource-report.json')
        shutil.copy(OUT / 'profile-contract.json', rel / 'profile-contract.json')
        app = c["app"]
        (rel / name).write_bytes(pkg)
        (rel / app).write_bytes(img)
        (rel / "SHA256SUMS").write_text("".join(f"{hashlib.sha256(b).hexdigest()}  {n}\n"
                                                for n, b in ((name, pkg), (app, bytes(img)))))
        for f in sorted((SRC / "LICENSES").glob("*.txt")):
            shutil.copy(f, rel / "LICENSES" / f.name)
        if not (rel / "LICENSES" / "MIT-Felucca-Engines.txt").exists():     # ANALOG LOFI TRIO WHEEL NOISE (engines/)
            raise SystemExit("release: LICENSES/MIT-Felucca-Engines.txt is missing")
        for doc in ("LICENSE", "LICENSING.md"):
            shutil.copy(SRC / doc, rel / doc)
        if att.exists():
            shutil.copy(att, rel / "ATTRIBUTION.txt")
        if c["explicit"]:           # the inputs the file names' version does not show
            (rel / "BUILD-INPUTS.txt").write_text(f"release {c['release']}\nversion {VERSION}\nproduct {PRODUCT}\n")
            print(f"inputs   release {c['release']}, version {VERSION}, identity {PRODUCT}")
        (rel / 'SHA256SUMS').write_text(''.join(
            f'{hashlib.sha256(path.read_bytes()).hexdigest()}  {path.relative_to(rel)}\n'
            for path in sorted(rel.rglob('*')) if path.is_file() and path.name != 'SHA256SUMS'))
        print(f"release  {rel}/")
    return 0


if __name__ == "__main__":
    sys.exit(main())
