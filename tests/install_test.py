#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-3.0-only
# Copyright (C) 2026 Leo Kuroshita (@kurogedelic), Hügelton Instruments
"""tools/fm1_install.py against a simulated FM-1 (no hardware, no mido).
The fake device is the one in web/test_web.mjs: identity on the handshake,
then "device asks, host answers" reads of the logical image. Run from the repo root:
  python3 tests/install_test.py
The packages are genuine ones, built with tools/fm1pkg_make.py from synthetic SDK
files, app and loader; the preflight (#118) gets them damaged one cause at a time.
Also checks logical_image/product_of against web/fm1pkg.js (needs node; the
build/felucca.fwsc check is skipped without a build)."""
import contextlib
import hashlib
import json
import io
import os
import queue
import shlex
import shutil
import subprocess
import sys
import tempfile
import threading
import time
import wave
from pathlib import Path
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "tools"))
import fm1_install as I  # noqa: E402
import fm1pkg_make as M  # noqa: E402
import build as B  # noqa: E402
from test_coverage import Producer
coverage = Producer()

I.DELAY.update(open=0, start=0.01, reply=0, loader=0.01, reboot=0.01, retry=0.02, poll=0.05, hs=0.1,
               idle_check=0.4, idle_write=0.4, wait_loader=2, wait_reboot=2)
failed = 0


def ok(cond, what):
    global failed
    print(f"{what:<64} {'ok' if cond else 'FAIL'}")
    failed += not cond


# ---------------------------------------------------------- simulated FM-1 ---

class FakeLink:
    def __init__(self, dev, gen):
        self.dev, self.gen, self.q, self.closed = dev, gen, queue.Queue(), False

    @property
    def lost(self):
        return self.gen != self.dev.gen or not self.dev.connected

    def send(self, pkt):
        if self.lost:
            return False
        self.dev.sent.append(bytes(pkt))
        self.dev.rx(bytes(pkt))
        return True

    def read(self, timeout):
        try:
            return self.q.get(timeout=max(timeout, 0))
        except queue.Empty:
            return None

    def drain(self):
        while not self.q.empty():
            self.q.get_nowait()

    def close(self):
        self.closed = True


class FakeFM1:
    """a MIDI backend with one FM-1 on it"""

    def __init__(self, image, identity="FM-1_015", name="FM-1", unplug_after=None, after_write="FM-1_900",
                 stall_after=None, bad_addr=None, loader_identity="ota-FM-1_900"):
        self.image, self.unplug_after, self.after_write = image, unplug_after, after_write
        self.loader_identity = loader_identity
        self.stall_after, self.bad_addr = stall_after, bad_addr
        self.served = self.bad = self.upgrades = 0
        self.sent, self.links, self.gen, self.lock = [], [], 0, threading.Lock()
        self.opened = 0
        self.boot(identity, name)

    def boot(self, identity, name):
        with self.lock:
            self.gen += 1
            self.identity, self.name, self.connected = identity, name, True
            self.waiting, self.queue = None, []

    def input_names(self):
        return [self.name] if self.connected else []

    output_names = input_names

    def open(self, in_name, out_name):
        if in_name != self.name or not self.connected:
            raise IOError("no such port")
        self.opened += 1
        link = FakeLink(self, self.gen)
        self.links.append(link)
        return link

    def tx(self, pkt):
        for link in self.links:
            if link.gen == self.gen and not link.closed:
                link.q.put(bytes(pkt))

    def rx(self, d):
        if d == I.HS_QUERY:
            t = self.identity.encode()
            self.tx(b"\xF0" + I.pack7(bytes([0, 0x59, 0x11, 0, 0, 0]) + t + bytes(28 - len(t))) + b"\xF7")
        elif d == I.UPGRADE:
            self.upgrades += 1
            first = self.bad_addr if self.bad_addr is not None else 0
            self.queue = ([(first + k * 512, 512) for k in range(6)] + [(I.FINISH_WRITE, 8)]
                          if self.identity.startswith("ota-")
                          else [(0, 64), (0x40, 160), (0x1000, 512), (I.FINISH_CHECK, 8)])
            self.next()
        elif self.waiting:
            u = I.unpack7(d[1:-1])
            addr, n = self.waiting
            fin = addr >= I.FINISH_CHECK
            want = b"success\0" if fin else self.image[addr:addr + n]
            if u[14:14 + len(want)] != want or len(u) != 15 + len(want):
                self.bad += 1
            self.waiting = None
            self.served += 1
            if self.unplug_after and self.served >= self.unplug_after:
                self.connected = False
                return
            if self.stall_after and self.served >= self.stall_after:
                return
            if addr == I.FINISH_CHECK:
                threading.Timer(0.05, self.boot, (self.loader_identity, "Felucca Update")).start()
            elif addr == I.FINISH_WRITE:
                threading.Timer(0.05, self.boot, (self.after_write, "Felucca")).start()
            else:
                self.next()

    def next(self):
        if not self.queue:
            return
        self.waiting = addr, n = self.queue.pop(0)
        u = bytearray([0, 0x59, 0x30, 0, 0, 0, 0]) + addr.to_bytes(4, "little") + bytes([n & 0xFF, n >> 8, 0])
        u.append(~sum(u[6:14]) & 0xFF)
        self.tx(b"\xF0" + I.pack7(u) + b"\xF7")


# ----------------------------------------------------------------- helpers ---

TMP = Path(tempfile.mkdtemp(prefix="felucca-install-"))


def synth(n, seed):
    return bytes((i * seed + (i >> 7) * 29 + seed) & 0xFF for i in range(n))


# synthetic SDK files (not the Apache-2.0 ones): fm1pkg_make only places them
for rel, n, seed in (("uboot.boot", 0x600, 11), ("cfg_tool.bin", 0x200, 13), ("cfg/eq_cfg_hw.bin", 0x100, 17)):
    f = TMP / "sdk/cpu/wl82/tools" / rel
    f.parent.mkdir(parents=True, exist_ok=True)
    f.write_bytes(synth(n, seed))
M.SDK = TMP / "sdk"
FLASH = M.flash_image(synth(60000, 7), M.KEY)


def loader(marker=True):
    """a loader in build.py's ota.bin format; the body starts with the marker (crt0_ldr.S)"""
    return B.ldr_wrap((I.LOADER_MARK if marker else b"NOT-THE-LOADER-1") + synth(3000, 101))


def package(product="FM-1_900", marker=True, extra=(), ota=None):
    return M.ufw(FLASH, ota or loader(marker), product, extra)


def fwsc(logical, raw):
    """logical image -> .fwsc with raw's 20 identity markers"""
    out = bytearray()
    for i in range(I.BLOCKS):
        out += logical[i * I.KEEP:(i + 1) * I.KEEP] + raw[i * I.BLK + I.KEEP:i * I.BLK + I.BLK]
    return bytes(out + logical[I.BLOCKS * I.KEEP:])


def reheader(raw, hdr=None, ent=None):
    """change the decoded UFW header (hdr(h)) or entries (ent(i, e)), CRCs recomputed: one cause at a time"""
    img = bytearray(I.logical_image(raw))
    h = I.jl_dec(img[:0x40])
    n = I.u16(h, 8)
    for i in range(n):
        o = 0x40 + i * 0x50
        e = I.jl_dec(img[o:o + 0x50])
        if ent:
            ent(i, e)
        img[o:o + 0x50] = I.jl_dec(e)
    if hdr:
        hdr(h)
    lend = 0x40 + I.u16(h, 8) * 0x50
    h[2:4] = I.crc16(img[0x40:lend]).to_bytes(2, "little")
    h[0:2] = I.crc16(h[2:]).to_bytes(2, "little")
    img[:0x40] = I.jl_dec(h)
    return fwsc(img, raw)


def flip(raw, logical_off):
    img = bytearray(I.logical_image(raw))
    img[logical_off] ^= 0x40
    return fwsc(img, raw)


def entry_of(raw, typ):
    img = I.logical_image(raw)
    for i in range(I.u16(I.jl_dec(img[:0x40]), 8)):
        e = I.jl_dec(img[0x40 + i * 0x50:0x90 + i * 0x50])
        if I.u16(e, 0) == typ:
            return I.u32(e, 8), I.u32(e, 12)


def pkgfile(name, raw):
    p = TMP / name
    p.write_bytes(raw)
    return str(p)


def cli(args, dev, answer=True, prompts=None):
    out, err = io.StringIO(), io.StringIO()
    old, sys.stderr = sys.stderr, err
    def ask(prompt):
        if prompts is not None:
            prompts.append(prompt)
        return answer
    try:
        rc = I.main(args, backend=dev, out=out, ask=ask)
    finally:
        sys.stderr = old
    return rc, out.getvalue(), err.getvalue()


# ------------------------------------------------------------------- tests ---

def wire():
    data = bytes(range(256)) * 3
    ok(I.unpack7(I.pack7(data))[:len(data)] == data, "pack7 / unpack7 round trip")
    pkt = I.response(0x12345, b"\x01\x02\x03", fl=5)
    u = I.unpack7(pkt[1:-1])
    ok(u[:3] == b"\x00\x59\x30" and int.from_bytes(u[7:11], "little") == 0x12345 and u[14:17] == b"\x01\x02\x03"
       and ~sum(u[6:17]) & 0xFF == u[17], "response: header, address, data, checksum")
    raw = package("FM-1_906")
    ok(I.product_of(raw) == "FM-1_906" and len(I.logical_image(raw)) == len(raw) - 20, "product_of / logical_image (synthetic)")


def installs():
    raw = package()
    image = I.logical_image(raw)
    p = pkgfile("ok.fwsc", raw)

    dev = FakeFM1(image)
    rc, out, err = cli([p, "--yes"], dev)
    ok(rc == 0 and dev.bad == 0 and dev.upgrades == 2 and dev.served == 11 and "done: the FM-1 runs FM-1_900" in out
       and "100%" in out, f"install: running -> loader -> Felucca ({dev.served} reads)")

    dev = FakeFM1(image, identity="ota-FM-1_900", name="Felucca Update")
    rc, out, err = cli([p, "--yes"], dev)
    ok(rc == 0 and dev.bad == 0 and dev.upgrades == 1 and "update mode" in out, "install: device already in update mode -> finishes the write")

    dev = FakeFM1(image)
    rc, out, err = cli([p], dev, answer=False)
    ok(rc == 1 and dev.upgrades == 0 and "cancelled" in out, "install: answer no -> nothing sent but the handshake")

    dev = FakeFM1(image, identity="FM-1_905", name="Felucca")
    rc, out, err = cli(["--info"], dev)
    ok(rc == 0 and "FM-1_905" in out and "running" in out and dev.upgrades == 0, "--info: identity of the connected FM-1")

    dev = FakeFM1(image, identity="ota-FM-1_900", name="Felucca Update")
    rc, out, err = cli(["--info"], dev)
    ok(rc == 0 and "update loader" in out, "--info: device in update mode")

    dev = FakeFM1(image, identity="\x1b[2J\x1b]0;x\x07FM-1_905", name="Felucca")
    rc, out, err = cli(["--info"], dev)
    ok(rc == 0 and "FM-1_905" in out and not any(c in out for c in "\x1b\x07"),
       "--info: control bytes in the device's identity are not printed")
    import fm1_sample_upload as U
    lines = U.slot_info([3, 80, 2, 0x41, 0x1B, 0x5B, 0x32, 0x4A, 0, 40, 0, 0, 0, 0, 0, 0])
    ok(lines[0] == "USR1: 2 zones, A?[2J, 40 KiB" and lines[1] == "USR2: empty", "sample upload: slot names printable only")
    try:
        U.slot_info([3, 80, 2, 0x41])
        ok(False, "sample upload: a malformed SMP_INFO reply is an error")
    except ValueError:
        ok(True, "sample upload: a malformed SMP_INFO reply is an error")


def errors():
    raw = package()
    image = I.logical_image(raw)
    p = pkgfile("ok.fwsc", raw)

    rc, out, err = cli([p, "--yes"], FakeFM1(image, name="IAC Driver Bus 1"))
    ok(rc == 3 and "not found" in err and "IAC Driver" in err, "no FM-1 port -> exit 3, lists the MIDI inputs")
    dev = FakeFM1(image)
    rc, out, err = cli([p, "--yes", "--port", "Felucca"], dev)
    ok(rc == 3 and dev.upgrades == 0, "--port that matches nothing -> exit 3")
    dev = FakeFM1(image, name="My Interface")
    rc, out, err = cli(["--info", "--port", "my int"], dev)
    ok(rc == 0 and "FM-1_015" in out, "--port picks a port the default match skips")

    t0 = time.monotonic()
    rc, out, err = cli([p, "--yes"], FakeFM1(image, unplug_after=2))
    ok(rc == 4 and "disconnected" in err and "nothing was written" in err and time.monotonic() - t0 < 3,
       "unplugged in step 1 -> exit 4 'lost', nothing written")
    t0 = time.monotonic()
    rc, out, err = cli([p, "--yes"], FakeFM1(image, identity="ota-FM-1_900", name="Felucca Update", unplug_after=3))
    ok(rc == 4 and "run the install again" in err and time.monotonic() - t0 < 3, "unplugged during the write -> exit 4 at once")
    rc, out, err = cli([p, "--yes"], FakeFM1(image, identity="ota-FM-1_900", name="Felucca Update", stall_after=3))
    ok(rc == 4 and "stopped answering" in err, "loader stops answering -> exit 4 after the idle time")
    rc, out, err = cli([p, "--yes"], FakeFM1(image, identity="ota-FM-1_900", name="Felucca Update", bad_addr=len(image)))
    ok(rc == 4 and "outside the package" in err, "read past the package -> exit 4")

    rc, out, err = cli([p, "--yes"], FakeFM1(image, after_write="FM-1_015"))
    ok(rc == 6 and "reports FM-1_015" in err, "another identity after the restart -> exit 6")
    dev = FakeFM1(image, identity="XY-9_001", name="usb-midi")
    rc, out, err = cli([p, "--yes"], dev)
    ok(rc == 6 and dev.upgrades == 0, "another model -> exit 6, nothing sent")

    class Stuck(FakeFM1):          # the loader never shows up
        def boot(self, identity, name):
            super().boot(identity, name)
            if identity.startswith("ota-"):
                self.connected = False
    rc, out, err = cli([p, "--yes"], Stuck(image))
    ok(rc == 5 and "loader did not appear" in err, "no loader after step 1 -> exit 5")

    plain = pkgfile("plain.fwsc", package(marker=False))
    class NoDiscovery(FakeFM1):
        def input_names(self):
            raise AssertionError("unapproved package must fail before MIDI discovery")
        output_names = input_names
    for force in ([], ["--force"]):
        for confirmation in ([], ["--yes"]):
            dev = NoDiscovery(I.logical_image(package(marker=False)))
            prompts = []
            rc, out, err = cli([plain, *confirmation, *force], dev, prompts=prompts)
            ok(rc == 2 and "no Felucca update loader" in err and "--force cannot approve" in err
               and dev.opened == 0 and dev.sent == [] and prompts == [],
               f"unknown package -> exit 2 before MIDI or confirmation ({confirmation + force})")
    for identity, upgrades in (("FM-1_015", 2), ("ota-FM-1_900", 1)):
        dev = FakeFM1(image, identity=identity)
        rc, out, err = cli([p, "--yes", "--force"], dev)
        ok(rc == 0 and dev.bad == 0 and dev.upgrades == upgrades,
           f"deprecated --force leaves a supported install unchanged ({identity})")
    rc, out, err = cli([pkgfile("short.fwsc", b"\0" * 100), "--yes"], FakeFM1(image))
    ok(rc == 2 and "too short" in err, "not a package -> exit 2")
    rc, out, err = cli([str(TMP / "missing.fwsc"), "--yes"], FakeFM1(image))
    ok(rc == 2, "missing file -> exit 2")


def compatibility():
    """#119: connected loader identity, not an ota- prefix, decides phase-two safety."""
    raw = package()
    image = I.logical_image(raw)
    p = pkgfile("compatibility.fwsc", raw)
    ok(I.package_bytes(image, "FM-1_900") == raw and I.package_family(image, "FM-1_900") == "felucca-v1",
       "classifier: native layout and loader window identify current Felucca")
    for identity in ("ota-FM-1_015", "ota-FM-1_901", "ota-FM-1_CUSTOM", "ota-XY-9_900"):
        dev = FakeFM1(image, identity=identity, name="Felucca Update")
        rc, out, err = cli([p, "--yes"], dev)
        ok(rc == 6 and dev.upgrades == 0 and dev.served == 0,
           f"resume: custom package refuses {identity} before START/data")
        dev = FakeFM1(image, loader_identity=identity)
        rc, out, err = cli([p, "--yes"], dev)
        ok(rc == 6 and dev.upgrades == 1 and dev.served == 4,
           f"fresh: custom package refuses discovered {identity} before phase two")
    override = "FM-1_ACME.V2_X-1"
    custom = package(product=override)
    dev = FakeFM1(I.logical_image(custom), identity=override, after_write=override)
    rc, out, err = cli([pkgfile("override.fwsc", custom), "--yes"], dev)
    ok(rc == 0 and dev.upgrades == 2 and override in out,
       "identity: supported build override handshakes and verifies exactly")
    # Install is also a public entry point: reject the expected identity before START or reads.
    for product in ("", "ota-FM-1_900", "FM-1_lower", "FM-1_" + "A" * 16, "FM-1_015", "FM-1_9\n", "FM-1_9é"):
        dev = FakeFM1(image)
        link = FakeLink(dev, dev.gen)
        d = I.Device(link, I.Identity("FM-1_900", "FM-1", 900), "FM-1")
        try:
            I.Updater(dev).install(d, image, product)
            refused = False
        except I.InstallError as e:
            refused = e.code == "badpkg"
        ok(refused and dev.sent == [] and dev.upgrades == 0 and link.closed,
           f"identity: invalid expected {product!r} causes no device operations")
    # Recompute all CRCs so these test classification, not accidental structural damage.
    unmarked = package(marker=False, extra=[(200, "marker.bin", I.LOADER_MARK)])
    misplaced = package(ota=B.ldr_wrap(synth(256, 101) + I.LOADER_MARK + synth(3000, 7)))
    wrong_size = M.ufw(FLASH + bytes(0x100), loader(), "FM-1_900")
    huge_loader = bytearray(loader())
    huge_loader[0x24:0x28] = (0x14001).to_bytes(4, "little")
    huge_loader[0x20:0x22] = I.crc16(huge_loader[0x22:0x40]).to_bytes(2, "little")
    huge_loader[2:4] = I.crc16(huge_loader[0x20:]).to_bytes(2, "little")
    huge_loader[0:2] = I.crc16(huge_loader[2:0x20]).to_bytes(2, "little")
    for what, bad in (("marker in another file", unmarked), ("marker outside loader window", misplaced),
                      ("non-native flash size", wrong_size), ("oversized expanded loader", package(ota=bytes(huge_loader)))):
        for force in ([], ["--force"]):
            dev = FakeFM1(I.logical_image(bad))
            rc, out, err = cli([pkgfile("unknown-family.fwsc", bad), "--yes", *force], dev)
            ok(rc == 2 and dev.opened == 0 and dev.sent == [] and dev.upgrades == 0 and dev.served == 0,
               f"classifier: {what} refused before MIDI ({force})")


def preflight():
    """#118: structure and CRCs on the host, before any MIDI port; --force skips none of it"""
    raw = package()
    fl_off, fl_size = entry_of(raw, 0)
    ota_off, ota_size = entry_of(raw, 100)
    ok(I.ufw_damage(I.logical_image(raw)) is None and I.load_package(pkgfile("v.fwsc", raw), False)
       == ("FM-1_900", I.logical_image(raw)), "preflight: a valid package -> same identity and logical image")
    many = lambda n: package(extra=[(200 + k, f"x{k}.bin", synth(100 + k, k + 3)) for k in range(n - 2)])
    for n in (8, 11):
        r = many(n)
        ok(I.ufw_damage(I.logical_image(r)) is None and I.load_package(pkgfile("n.fwsc", r), False)[1]
           == I.logical_image(r), f"preflight: {n} UFW entries are taken (ota.c: up to 11)")
    dev = FakeFM1(I.logical_image(many(11)))
    rc, out, err = cli([pkgfile("n11.fwsc", many(11)), "--yes"], dev)
    ok(rc == 0 and dev.bad == 0, "install: an 11-entry package")
    plain = package(marker=False)
    for force in (False, True):
        try:
            I.load_package(pkgfile("p.fwsc", plain), force)
            refused = False
        except I.InstallError as e:
            refused = e.code == "badpkg" and "unknown loader family" in str(e)
        ok(refused, f"preflight: unmarked package refused (force={force})")

    def lay(t, size):          # flash.bin entry with another size, its data CRC kept true
        def f(i, e):
            if I.u16(e, 0) == 0:
                e[12:16] = size.to_bytes(4, "little")
                e[4:6] = I.crc16(I.logical_image(raw)[fl_off:fl_off + size]).to_bytes(2, "little")
        return f
    bad_head = bytearray(loader())
    bad_head[0x28] ^= 1                                 # inner head: load address (and its CRC) off
    bad_body = bytearray(loader())
    bad_body[-1] ^= 1                                   # loader body, the UFW entry CRC recomputed by the maker
    short_ota = B.ldr_wrap(I.LOADER_MARK)
    short_pkg = package(ota=short_ota)
    ok(0x40 <= len(short_ota) < 512, "initial loader-read fixture has valid short loader heads/body")
    padded = short_pkg + bytes(512 - len(short_ota))
    ok(I.load_package(pkgfile("loader-read-fit.fwsc", padded), False)[1] == I.logical_image(padded),
       "preflight: exactly 512 addressable bytes at a short loader are accepted")
    retype = lambda old, new: lambda i, e: e.__setitem__(slice(0, 2), new.to_bytes(2, "little")) \
        if I.u16(e, 0) == old else None
    move = lambda typ, off: lambda i, e: e.__setitem__(slice(8, 12), off.to_bytes(4, "little")) \
        if I.u16(e, 0) == typ else None
    cases = [
        ("too short", b"\0" * 100, "too short"),
        ("short header (1 KiB the FM-1 reads)", raw[:0x3F0 + I.BLOCKS], "1 KiB UFW header"),
        ("short entry list", many(11)[:I.BLOCKS * I.BLK], "entry list cut off"),
        ("0 entries", reheader(raw, hdr=lambda h: h.__setitem__(slice(8, 10), b"\0\0")), "0 UFW entries"),
        ("12 entries (first count ota.c refuses)", many(12), "12 UFW entries"),
        ("0xFFFF entries", reheader(raw, hdr=lambda h: h.__setitem__(slice(8, 10), b"\xff\xff")),
         "65535 UFW entries"),
        ("header CRC", flip(raw, 0x30), "UFW header CRC mismatch"),
        ("entry list CRC", flip(raw, 0x60), "entry list CRC mismatch"),
        ("flash.bin CRC", flip(raw, fl_off + 0x5000), "(flash.bin, type 0): data CRC mismatch"),
        ("ota.bin CRC", flip(raw, ota_off + ota_size - 1), "(ota.bin, type 100): data CRC mismatch"),
        ("extra file CRC", flip(many(8), len(I.logical_image(many(8))) - 1), "(x5.bin, type 205): data CRC"),
        ("truncated file", raw[:-100], "(ota.bin, type 100): data [0x"),
        ("extent out of bounds", reheader(raw, ent=move(100, 0x7FFFFFF0)), "outside the package"),
        ("extent over the header", reheader(raw, ent=move(0, 0)), "outside the package"),
        ("no flash.bin", reheader(raw, ent=retype(0, 7)), "no flash.bin"),
        ("no ota.bin", reheader(raw, ent=retype(100, 5)), "no ota.bin"),
        ("two flash.bin", package(extra=[(0, "flash.bin", FLASH)]), "a second type-0 file"),
        ("flash.bin too small", reheader(raw, ent=lay(0, 0x90000)), "the loader takes"),
        ("loader heads", package(ota=bytes(bad_head)), "loader heads"),
        ("loader body CRC", package(ota=bytes(bad_body)), "loader body CRC mismatch"),
        ("short initial loader read", short_pkg, "initial 512-byte loader read"),
        ("initial loader read one byte short", short_pkg + bytes(511 - len(short_ota)),
         "initial 512-byte loader read"),
        ("oversized", raw + bytes(I.MAX_PKG), "larger than 2048 KiB"),
    ]
    for what, bad, msg in cases:
        p = pkgfile("bad.fwsc", bad)
        res = []
        for force in ([], ["--force"]):
            dev = FakeFM1(I.logical_image(raw))
            rc, out, err = cli([p, "--yes", *force], dev)
            res.append(rc == 2 and msg in err and dev.opened == 0 and dev.sent == [])
        ok(all(res), f"preflight: {what} -> exit 2, no port (also --force)")
        if not all(res):
            print("   ", err.strip())
    dev = FakeFM1(I.logical_image(raw))
    rc, out, err = cli([pkgfile("pb.fwsc", flip(plain, fl_off + 0x5000)), "--yes", "--force"], dev)
    ok(rc == 2 and "data CRC mismatch" in err and dev.opened == 0, "preflight: --force on a damaged unmarked package")
    dev = FakeFM1(I.logical_image(raw))
    rc, out, err = cli(["--info"], dev)
    ok(rc == 0 and dev.opened == 1, "--info: no package, no preflight")
    good, bad = pkgfile("o_good.fwsc", raw), pkgfile("o_bad.fwsc", flip(raw, 0x60))
    code = ("import sys; sys.path.insert(0, %r); import fm1_install as I\n"
            "assert False\n"
            "I.load_package(%r, False)\n"
            "try:\n    I.load_package(%r, True)\nexcept I.InstallError as e:\n    print('refused', e)\n"
            % (str(ROOT / "tools"), good, bad))
    r = subprocess.run([sys.executable, "-O", "-c", code], capture_output=True, text=True)
    ok(r.returncode == 0 and "refused" in r.stdout and "list CRC" in r.stdout, "preflight: active under python -O")


def dependency_guidance():
    """Missing MIDI packages give a complete retry; offline paths still run without them."""
    import fm1_sample_upload as U
    arguments = ["--info", "--port", "FM-1 user's port"]
    sample_arguments = ["erase", "1"]
    for missing, modules in (("mido", {"mido": None}),
                             ("rtmidi", {"mido": object(), "rtmidi": None})):
        error = io.StringIO()
        with patch.dict(sys.modules, modules), contextlib.redirect_stderr(error):
            result = I.main(arguments)
        command = shlex.split(error.getvalue().split("Run:\n  ", 1)[1])
        expected = ["uv", "run", "--project", str(ROOT), "--locked", "--group", "midi",
                    "python", str(ROOT / "tools/fm1_install.py"), *arguments]
        ok(result == 2 and command == expected, f"missing {missing}: installer gives locked MIDI retry with original flags")
        with patch.dict(sys.modules, modules), patch.object(sys, "argv", [U.__file__, *sample_arguments]):
            try:
                U.Link()
                ok(False, f"missing {missing}: sample uploader stops before MIDI discovery")
            except SystemExit as error:
                command = shlex.split(str(error).split("Run:\n  ", 1)[1])
                expected = ["uv", "run", "--project", str(ROOT), "--locked", "--group", "midi",
                            "python", str(ROOT / "tools/fm1_sample_upload.py"), *sample_arguments]
                ok(command == expected, f"missing {missing}: sample uploader gives locked MIDI retry")
    help_ok = False
    with patch.dict(sys.modules, {"mido": None, "rtmidi": None}), contextlib.redirect_stdout(io.StringIO()):
        try:
            I.main(["--help"])
        except SystemExit as error:
            help_ok = error.code == 0
    ok(help_ok, "installer help needs no MIDI dependencies")
    wav = TMP / "offline sample.wav"
    with wave.open(str(wav), "wb") as output:
        output.setnchannels(1)
        output.setsampwidth(2)
        output.setframerate(22050)
        output.writeframes(bytes(128))
    prefix = TMP / "offline slot"
    with patch.dict(sys.modules, {"mido": None, "rtmidi": None}), \
            patch.object(sys, "argv", [U.__file__, "build", "Offline", str(prefix), str(wav)]), \
            contextlib.redirect_stdout(io.StringIO()):
        U.main()
    ok(prefix.with_suffix(".hdr").is_file() and prefix.with_suffix(".bin").is_file(),
       "sample slot build needs no MIDI dependencies")


def js_synthetic():
    """the synthetic packages through web/fm1pkg.js: same identity, logical image, entries; same CRC refusals"""
    if not shutil.which("node"):
        print("preflight vs fm1pkg.js: skipped (needs node)")
        coverage.outcome('js-synthetic', 'skipped', 'node-unavailable')
        return
    js = ("import { Package, logicalImage, productOf } from %r; import { readFileSync } from 'node:fs';"
          "const out = []; for (const f of process.argv.slice(1)) { const p = readFileSync(f);"
          "let e = null; try { e = new Package(p).entries.map((x) => [x.type, x.dcrc, x.dataOff, x.size, x.name]); }"
          "catch (err) { e = String(err.message); }"
          "out.push({ product: productOf(p), image: Buffer.from(logicalImage(p)).toString('hex'), entries: e }); }"
          "process.stdout.write(JSON.stringify(out));") % str(ROOT / "web/fm1pkg.js")
    raw = package(extra=[(200, "x.bin", synth(300, 5))])
    fl_off, _ = entry_of(raw, 0)
    files = [pkgfile(f"js{k}.fwsc", r) for k, r in enumerate(
        (raw, flip(raw, 0x30), flip(raw, 0x60), flip(raw, fl_off + 0x5000)))]
    r = subprocess.run(["node", "--input-type=module", "-e", js, *files], capture_output=True, text=True)
    if r.returncode:
        ok(False, f"fm1pkg.js on the synthetic packages: {r.stderr.strip()[:80]}")
        return
    res = json.loads(r.stdout)
    img = I.logical_image(raw)
    ents = []
    for i in range(3):
        e = I.jl_dec(img[0x40 + i * 0x50:0x90 + i * 0x50])
        ents.append([I.u16(e, 0), I.u16(e, 4), I.u32(e, 8), I.u32(e, 12), e[0x40:].split(b"\0")[0].decode()])
    ok(res[0]["product"] == I.product_of(raw) and bytes.fromhex(res[0]["image"]) == img and res[0]["entries"] == ents,
       "synthetic package: identity, logical image, UFW entries == fm1pkg.js")
    ok(all(isinstance(x["entries"], str) and I.ufw_damage(bytes.fromhex(x["image"])) for x in res[1:]),
       "header / list / flash.bin CRC damage: fm1pkg.js refuses it too")
    coverage.outcome('js-synthetic', 'failed' if failed else 'passed')


def against_js():
    profile = os.environ.get("FELUCCA_PROFILE", "standard")
    clean = ROOT / "build" / ("felucca" + ("-" + profile if profile != "standard" else "") + ".fwsc")
    if not clean.exists():
        print("built package preflight / fm1pkg.js parity: skipped (needs build/felucca.fwsc)")
        coverage.outcome('built-package-parity', 'skipped', 'package-missing')
        return
    raw = clean.read_bytes()
    ok(I.load_package(clean, False) == (I.product_of(raw), I.logical_image(raw)),
       f"preflight accepts the actual build ({clean.name}) without changing its image or identity")
    if not shutil.which("node"):
        print("logical image vs fm1pkg.js: skipped (needs node)")
        coverage.outcome('built-package-parity', 'skipped', 'node-unavailable')
        return
    js = ("import { logicalImage, productOf } from %r; import { readFileSync } from 'node:fs';"
          "const p = readFileSync(process.argv[1]); process.stderr.write(productOf(p));"
          "process.stdout.write(logicalImage(p));") % str(ROOT / "web/fm1pkg.js")
    r = subprocess.run(["node", "--input-type=module", "-e", js, str(clean)], capture_output=True, check=True)
    ok(I.logical_image(raw) == r.stdout and I.product_of(raw) == r.stderr.decode(),
       f"logical_image / product_of == fm1pkg.js ({clean.name}, {I.product_of(raw)})")
    ok(I.LOADER_MARK in raw, f"{clean.name} carries the Felucca loader marker")
    coverage.outcome('built-package-parity', 'failed' if failed else 'passed', package=str(clean),
                     sha256=hashlib.sha256(raw).hexdigest())


def stock_policy():
    """Exercise the exact-digest exception with a synthetic stand-in, not real V15 format/device evidence."""
    raw = flip(package(product="FM-1_015", marker=False), 0x30)
    ok(I.ufw_damage(I.logical_image(raw)) is not None, "stock policy fixture would fail ordinary preflight")
    digest = I.STOCK_V15_SHA256
    try:
        I.STOCK_V15_SHA256 = hashlib.sha256(raw).hexdigest()
        dev = FakeFM1(I.logical_image(raw), identity="FM-1_900", name="Felucca", after_write="FM-1_015",
                      loader_identity="ota-FM-1_015")
        rc, out, err = cli([pkgfile("digest-approved.fwsc", raw), "--yes"], dev)
        ok(rc == 0 and dev.bad == 0 and dev.identity == "FM-1_015",
           "stock policy: exactly approved bytes bypass preflight and marker restrictions")
        bad = bytearray(raw)
        bad[-1] ^= 1
        for force in ([], ["--force"]):
            dev = FakeFM1(I.logical_image(bytes(bad)))
            rc, out, err = cli([pkgfile("digest-modified.fwsc", bytes(bad)), "--yes", *force], dev)
            ok(rc == 2 and dev.opened == 0 and dev.sent == [],
               f"stock policy: changed bytes lose the digest exception, no MIDI ({force})")
        unlisted = package(product="FM-1_015", marker=False)
        dev = FakeFM1(I.logical_image(unlisted))
        rc, out, err = cli([pkgfile("digest-unlisted.fwsc", unlisted), "--yes"], dev)
        ok(rc == 2 and "reserved" in err and dev.opened == 0 and dev.sent == [],
           "stock policy: matching identity alone does not grant the digest exception")
    finally:
        I.STOCK_V15_SHA256 = digest


def official():
    """#32: back to the official V15 from Felucca, without --force (only the unmodified file)"""
    v15 = ROOT / "FM-1_v15.fwsc"
    if not v15.exists():
        v15 = ROOT / "build/recovery-inputs/FM-1_v15.fwsc"
    if not v15.exists():
        print("official V15 restore: skipped (needs FM-1_v15.fwsc in the repo root)")
        coverage.outcome('official-v15', 'skipped', 'proprietary-fixture-absent')
        return
    raw = v15.read_bytes()
    dev = FakeFM1(I.logical_image(raw), identity="FM-1_900", name="Felucca", after_write="FM-1_015",
                      loader_identity="ota-FM-1_015")
    rc, out, err = cli([str(v15), "--yes"], dev)
    ok(rc == 0 and dev.bad == 0 and "FM-1_015" in out and dev.identity == "FM-1_015",
       "official V15 (FM-1.fwsc) from Felucca: installed without --force, back as FM-1_015")
    ok(I.package_family(I.logical_image(raw), "FM-1_015") == "stock-v15",
       "official V15: classifier recognizes complete approved file")
    for identity in ("ota-FM-1_015", "ota-FM-1_900", "ota-FM-1_901", "ota-FM-1_CUSTOM"):
        dev = FakeFM1(I.logical_image(raw), identity=identity, name="Felucca Update", after_write="FM-1_015")
        rc, out, err = cli([str(v15), "--yes"], dev)
        compatible = identity == "ota-FM-1_015"
        ok((rc == 0 and dev.upgrades == 1 and dev.served == 7) if compatible
           else (rc == 6 and dev.upgrades == 0 and dev.served == 0),
           f"official V15 resume: loader {identity}, compatible={compatible}")
        dev = FakeFM1(I.logical_image(raw), identity="FM-1_900", after_write="FM-1_015", loader_identity=identity)
        rc, out, err = cli([str(v15), "--yes"], dev)
        ok((rc == 0 and dev.upgrades == 2 and dev.served == 11) if compatible
           else (rc == 6 and dev.upgrades == 1 and dev.served == 4),
           f"official V15 fresh: loader {identity}, compatible={compatible}")
    shifted = bytearray(raw)
    product = "FM-1_015"
    for i in range(I.BLOCKS):
        shifted[i * I.BLK + I.KEEP] = ((ord(product[i - 1]) + i + 1) & 0xFF) if 1 <= i <= len(product) else 0x7D
    ok(I.product_of(shifted) == product and I.logical_image(shifted) == I.logical_image(raw),
       "official digest fixture: noncanonical markers keep logical image and identity")
    dev = FakeFM1(I.logical_image(raw))
    rc, out, err = cli([pkgfile("v15-shifted-markers.fwsc", shifted), "--yes", "--force"], dev)
    ok(rc == 2 and dev.opened == 0 and "whole-file digest" in err,
       "official V15: modified marker bytes fail exact-file digest before MIDI")
    bad = bytearray(raw)
    bad[-1] ^= 1
    dev = FakeFM1(I.logical_image(bytes(bad)), identity="FM-1_900", name="Felucca")
    rc, out, err = cli([pkgfile("v15mod.fwsc", bytes(bad)), "--yes"], dev)
    ok(rc == 2 and dev.opened == 0 and dev.sent == [], "a modified V15 is still refused (no MIDI)")
    coverage.outcome('official-v15', 'failed' if failed else 'passed', sha256=hashlib.sha256(raw).hexdigest())


wire()
installs()
errors()
compatibility()
preflight()
dependency_guidance()
js_synthetic()
against_js()
stock_policy()
official()
shutil.rmtree(TMP, ignore_errors=True)
print(f"INSTALL TESTS FAILED ({failed})" if failed else "install tests passed")
sys.exit(1 if failed else 0)
