#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-3.0-only
# Copyright (C) 2026 Leo Kuroshita (@kurogedelic), Hügelton Instruments
"""Install a Felucca package (.fwsc) on an FM-1 over USB-MIDI.

The same update as the web installer (web/fm1ota.js): step 1, the
running firmware reads parts of the package and starts the update loader;
step 2, the loader reads the whole package and writes it. In both steps the
device asks (SysEx read requests on the logical image) and we answer. Then
the FM-1 restarts and the installed identity is checked.

  fm1_install.py PACKAGE.fwsc [--port NAME] [--yes] [--force]
  fm1_install.py FM-1.fwsc            (the official V15 file: back to the stock firmware)
  fm1_install.py --info [--port NAME]

If the FM-1 is still in update mode (an earlier install was cut off), the
install finishes the write. Before any MIDI port is opened the package's
structure is checked (UFW header, entry list, every file's extent and CRC,
the loader heads). Only matching known package/loader families may write.
--force is a deprecated compatibility option with no effect. Needs mido with python-rtmidi.

Exit codes: 0 done, 1 cancelled or other error, 2 bad arguments or package,
3 FM-1 not found, 4 connection lost or the device stopped, 5 timeout (no
loader / no restart), 6 wrong model, or another identity after the install.
"""
import argparse
import hashlib
from pathlib import Path
import queue
import re
import shlex
import sys
import time

HS_QUERY = bytes([0xF0, 0x00, 0x32, 0x45, 0x00, 0x00, 0x00, 0x40, 0x7F, 0xF7])
UPGRADE = bytes([0xF0, 0x22, 0x24, 0x35, 0x7F, 0xF7])
FINISH_CHECK, FINISH_WRITE = 0xE0000000, 0xF0000000
MAXDATA = 512
BLOCKS, BLK, KEEP = 20, 0x30, 0x2F
LOADER_MARK = b"FELUCCA-LOADER-1"
# the unmodified official FM-1 V15 (FM-1.fwsc from M-VAVE): returning to it is allowed without --force,
# as the web installer's "Return to official V15" (web/fm1pkg.js validateStockPackage)
STOCK_V15_SHA256 = "db1642b2b6fa5c2cccb11ffd13878068bb28601678d3644049f99dc40e7edb8a"
# the host-side preflight (ufw_damage): the rules of the device's UFW parser (firmware/src/ota.c ota_ufw,
# ota_stage) and of the loader (firmware/loader/ldr_core.c), checked before any MIDI port is opened
UFW_HDR, UFW_ENT, UFW_READ = 0x40, 0x50, 0x400   # header, entry; the device reads both in one 1 KiB go
UFW_MAXENT = 11                     # ota_ufw: 1..11 entries
FL_MIN, FL_MAX = 0x93000, 0x100000  # flash.bin: the app area up to 0x93000 .. the 1 MiB part (ldr_session)
OTA_MAX, OTA_LOAD = 0x4E00, 0x01C0A800    # loader body: OTA_AREA_LEN - 0x200; its load address
# every byte of a package is something the device may read: flash.bin is at most the 1 MiB part, so twice
# that is room for any other files (V15: 684 KiB) and still refuses a wrong file before it is read whole
MAX_PKG = 0x200000
PRODUCT_RE = re.compile(r"FM-1_[A-Z0-9._-]{1,15}")
LOADER_FAMILIES = {"felucca-v1": "ota-FM-1_900", "stock-v15": "ota-FM-1_015"}
PORT_RE = re.compile(r"fm-1|felucca|ota|composite|sinco|usb-midi", re.I)   # never probe other gear

# seconds; the tests shorten them
DELAY = {"open": 0.3, "start": 2.0, "reply": 0.01, "loader": 3.0, "reboot": 3.0, "retry": 1.0,
         "poll": 1.0, "hs": 1.0, "idle_check": 8.0, "idle_write": 180.0,
         "wait_loader": 30.0, "wait_reboot": 40.0}

EXIT = {"usage": 2, "badpkg": 2, "notfound": 3, "model": 6, "lost": 4, "stopped": 4, "badreq": 4,
        "noloader": 5, "noreturn": 5, "mismatch": 6}


class InstallError(Exception):
    def __init__(self, code, msg):
        super().__init__(msg)
        self.code = code


def midi_dependency_message(script, argv):
    """Retry the same trusted script with its locked MIDI environment from any directory."""
    script = Path(script).resolve()
    command = ["uv", "run", "--project", str(script.parents[1]), "--locked", "--group", "midi",
               "python", str(script), *map(str, argv)]
    if sys.platform == "win32":
        # PowerShell recognizes typographic apostrophes as string delimiters too.
        escapes = {ord(char): char * 2 for char in "'\u2018\u2019\u201a\u201b"}
        quoted = " ".join("'" + arg.translate(escapes) + "'" for arg in command)
        return "needs mido and python-rtmidi. Run in PowerShell:\n  & " + quoted
    return "needs mido and python-rtmidi. Run:\n  " + shlex.join(command)


# ------------------------------------------------------------ wire format ---

def pack7(data):
    out, acc, nb = [], 0, 0
    for b in data:
        acc |= b << nb
        nb += 8
        while nb >= 7:
            out.append(acc & 0x7F)
            acc >>= 7
            nb -= 7
    if nb:
        out.append(acc & 0x7F)
    return bytes(out)


def unpack7(s):
    out, acc, nb = [], 0, 0
    for b in s:
        acc |= (b & 0x7F) << nb
        nb += 7
        while nb >= 8:
            out.append(acc & 0xFF)
            acc >>= 8
            nb -= 8
    return bytes(out)


def response(addr, data, fl=0):
    n = len(data)
    body = bytearray([0x00, 0x59, 0x30, (n + 8) & 0xFF, ((n + 8) >> 8) & 0xFF, 0, fl])
    body += addr.to_bytes(4, "little") + bytes([n & 0xFF, (n >> 8) & 0xFF, 0]) + bytes(data)
    body.append(~sum(body[6:]) & 0xFF)
    return b"\xF0" + pack7(body) + b"\xF7"


def parse_request(pkt):
    """-> (flags, addr, len) or None"""
    if len(pkt) < 2 or pkt[0] != 0xF0 or pkt[-1] != 0xF7:
        return None
    u = unpack7(pkt[1:-1])
    if len(u) != 15 or u[:3] != b"\x00\x59\x30" or ~sum(u[6:14]) & 0xFF != u[14]:
        return None
    return u[6], int.from_bytes(u[7:11], "little"), int.from_bytes(u[11:14], "little")


class Identity:
    def __init__(self, text, model, version):
        self.text, self.model, self.version = text, model, version

    @property
    def loader(self):
        return self.model.lower().startswith("ota-")


def printable(b):
    """bytes from the device as text for the terminal: printable ASCII only (no escape sequences)"""
    return "".join(chr(c) if 32 <= c < 127 else "?" for c in b)


def parse_identity(pkt):
    if len(pkt) < 2 or pkt[0] != 0xF0 or pkt[-1] != 0xF7:
        return None
    d = unpack7(pkt[1:-1])
    if len(d) != 34 or d[:3] != b"\x00\x59\x11":
        return None
    txt = printable(d[6:33].rstrip(b"\0"))
    m = re.fullmatch(r"([^_]+)_([A-Z0-9._-]{1,15})", txt)
    return Identity(txt, m[1], int(m[2]) if m[2].isdigit() else m[2]) if m else None


# --------------------------------------------------------------- package ---

def product_of(raw):
    """the package identity ("FM-1_906"): one marker byte after each of the first 20 blocks"""
    if len(raw) < BLOCKS * BLK:
        raise InstallError("badpkg", "not an FM-1 package (too short)")
    return "".join(chr((m - i - 1) & 0xFF) for i in range(BLOCKS) if (m := raw[i * BLK + KEEP]) != 0x7D)


def logical_image(raw):
    """the image the device reads during an update: the package without the 20 marker bytes"""
    out = bytearray()
    for i in range(BLOCKS):
        out += raw[i * BLK:i * BLK + KEEP]
    return bytes(out + raw[BLOCKS * BLK:])


def _crc_table():
    t = []
    for i in range(256):
        c = i << 8
        for _ in range(8):
            c = ((c << 1) ^ 0x1021) if c & 0x8000 else (c << 1)
        t.append(c & 0xFFFF)
    return t


_T = _crc_table()


def crc16(data, crc=0):
    for b in data:
        crc = ((crc << 8) & 0xFFFF) ^ _T[((crc >> 8) ^ b) & 0xFF]
    return crc


def jl_dec(data):
    """JieLi ENC (key 0xFFFF) of a UFW header or entry; its own inverse"""
    out, key = bytearray(data), 0xFFFF
    for i in range(len(out)):
        out[i] ^= key & 0xFF
        key = ((key << 1) ^ (0x1021 if key & 0x8000 else 0)) & 0xFFFF
    return out


def u16(b, o):
    return int.from_bytes(b[o:o + 2], "little")


def u32(b, o):
    return int.from_bytes(b[o:o + 4], "little")


def ufw_damage(img):
    """what is wrong with the UFW structure of a logical image, None if the FM-1 takes it: header and
    entry list CRCs, the entry count, every file's extent and data CRC, one flash.bin and one ota.bin
    in the sizes the firmware and the loader accept, the loader's two heads and body CRC"""
    if len(img) < UFW_HDR:
        return f"shorter than the UFW header ({len(img)} B)"
    h = jl_dec(img[:UFW_HDR])
    if crc16(h[2:]) != u16(h, 0):
        return "UFW header CRC mismatch"
    nent = u16(h, 8)
    if not 1 <= nent <= UFW_MAXENT:
        return f"{nent} UFW entries (the FM-1 takes 1..{UFW_MAXENT})"
    lend = UFW_HDR + nent * UFW_ENT
    if len(img) < lend:
        return f"UFW entry list cut off ({nent} entries end at {lend:#x}, the image at {len(img):#x})"
    if crc16(img[UFW_HDR:lend]) != u16(h, 2):
        return "UFW entry list CRC mismatch"
    if len(img) < UFW_READ:
        return f"shorter than the 1 KiB UFW header the FM-1 reads ({len(img)} B)"
    files = {}
    for i in range(nent):
        e = jl_dec(img[UFW_HDR + i * UFW_ENT:UFW_HDR + (i + 1) * UFW_ENT])
        typ, dcrc, off, size = u16(e, 0), u16(e, 4), u32(e, 8), u32(e, 12)
        name = printable(e[0x40:].split(b"\0")[0]) or "?"
        what = f"file {i} ({name}, type {typ})"
        if off < lend or off + size > len(img):
            return (f"{what}: data [{off:#x}, {off + size:#x}) outside the package "
                    f"(files from {lend:#x} to {len(img):#x})")
        if typ in (0, 100) and typ in files:        # the device takes the last one, fm1pkg.js the first
            return f"{what}: a second type-{typ} file"
        if crc16(img[off:off + size]) != dcrc:
            return f"{what}: data CRC mismatch"
        files.setdefault(typ, (off, size, what))
    if 0 not in files:
        return "no flash.bin (type 0)"
    off, size, what = files[0]
    if not FL_MIN <= size <= FL_MAX:
        return f"{what}: {size:#x} B (the loader takes {FL_MIN:#x}..{FL_MAX:#x})"
    if 100 not in files:
        return "no ota.bin (type 100)"
    off, size, what = files[100]
    # ota_stage reads 512 bytes before consulting the loader's declared size.
    if off + 512 > len(img):
        return f"{what}: initial 512-byte loader read extends outside the package"
    b = img[off:off + min(size, 0x40)]
    n = u32(b, 8)
    if (size < 0x40 or crc16(b[2:32]) != u16(b, 0) or u32(b, 4) != 0x20 or b[12] != 0x41 or size != n + 0x20
            or n > OTA_MAX or crc16(b[0x22:0x40]) != u16(b, 0x20) or u32(b, 0x28) != OTA_LOAD):
        return f"{what}: not an update loader the FM-1 starts (loader heads)"
    if crc16(img[off + 0x20:off + 0x20 + n]) != u16(b, 2):
        return f"{what}: loader body CRC mismatch"
    return None


def package_bytes(image, product):
    """Rebuild canonical .fwsc bytes so the direct updater also pins the complete stock file."""
    out = bytearray()
    for i in range(BLOCKS):
        marker = (ord(product[i]) + i + 1) & 0xFF if i < len(product) else 0x7D
        out += image[i * KEEP:(i + 1) * KEEP] + bytes([marker])
    return bytes(out + image[BLOCKS * KEEP:])


def package_family(image, product):
    """Validate the expected app identity and classify only known package layouts/loaders.

    None is an unmarked, otherwise valid native package. No connected loader is
    approved to write an unknown loader family.
    """
    if (not isinstance(product, str) or not PRODUCT_RE.fullmatch(product)
            or any((ord(c) + i + 1) & 0xFF == 0x7D for i, c in enumerate(product))):
        raise InstallError("badpkg", f"unsupported expected app identity {product!r}")
    if (product == "FM-1_015"
            and hashlib.sha256(package_bytes(image, product)).hexdigest() == STOCK_V15_SHA256):
        return "stock-v15"
    if product == "FM-1_015":
        raise InstallError("badpkg", "FM-1_015 is reserved for the exact approved official V15 package")
    if why := ufw_damage(image):
        raise InstallError("badpkg", f"damaged or unsupported package, nothing was sent: {why}")
    files = {}
    for i in range(u16(jl_dec(image[:UFW_HDR]), 8)):
        e = jl_dec(image[UFW_HDR + i * UFW_ENT:UFW_HDR + (i + 1) * UFW_ENT])
        files[u16(e, 0)] = (u32(e, 8), u32(e, 12))
    if files[0][1] != FL_MIN:
        raise InstallError("badpkg", f"unsupported flash.bin layout: expected exactly {FL_MIN:#x} bytes")
    off, size = files[100]
    loader = image[off:off + size]
    # Match ota_stage: only the first LZ4 literal window of the actual type-100 loader.
    if LOADER_MARK in loader[0x48:0x48 + 64] and u32(loader, 0x24) <= 0x14000:
        return "felucca-v1"
    return None


def require_loader(ota, family):
    expected = LOADER_FAMILIES.get(family)
    if expected is None or ota.id.text != expected:
        ota.link.close()
        raise InstallError("model", f"incompatible update loader {ota.id.text}: "
                           f"package requires {expected or 'a known loader family'}; no update START/data was sent to the loader")


def model_of(text):
    return text.split("_")[0].removeprefix("ota-")


# ------------------------------------------------------------------ MIDI ---

class MidoLink:
    """one MIDI in/out pair with a SysEx queue"""

    def __init__(self, backend, in_name, out_name):
        import mido
        self.backend, self.name, self.mido = backend, in_name, mido
        self.q = queue.Queue()
        self.inp = mido.open_input(in_name, callback=self._rx)
        try:
            self.out = mido.open_output(out_name)
        except Exception:
            self.inp.close()
            raise
        time.sleep(DELAY["open"])   # CoreMIDI may drop a message sent just after opening

    def _rx(self, msg):
        if msg.type == "sysex":
            self.q.put(bytes([0xF0, *msg.data, 0xF7]))

    @property
    def lost(self):
        return self.name not in self.backend.input_names()

    def send(self, pkt):
        try:
            self.out.send(self.mido.Message("sysex", data=pkt[1:-1]))
            return True
        except Exception:
            return False

    def read(self, timeout):
        try:
            return self.q.get(timeout=max(timeout, 0))
        except queue.Empty:
            return None

    def drain(self):
        while not self.q.empty():
            self.q.get_nowait()

    def close(self):
        for p in (self.inp, self.out):
            try:
                p.close()
            except Exception:
                pass


class MidoBackend:
    def __init__(self):
        import mido
        import rtmidi  # Check the required backend before MIDI discovery.
        self.mido = mido

    def input_names(self):
        return list(dict.fromkeys(self.mido.get_input_names()))

    def output_names(self):
        return list(dict.fromkeys(self.mido.get_output_names()))

    def open(self, in_name, out_name):
        return MidoLink(self, in_name, out_name)


def pair_output(name, outs):
    if name in outs:
        return name
    base = re.sub(r"\s+\d+$", "", name)     # Windows numbers each port
    same = [o for o in outs if re.sub(r"\s+\d+$", "", o) == base]
    if len(same) == 1:
        return same[0]
    return outs[0] if len(outs) == 1 else None


# --------------------------------------------------------------- updater ---

class Device:
    def __init__(self, link, ident, name):
        self.link, self.id, self.name = link, ident, name


def handshake(link, tries=3):
    link.drain()
    for _ in range(tries):
        if not link.send(HS_QUERY):
            return None
        end = time.monotonic() + DELAY["hs"]
        while (left := end - time.monotonic()) > 0:
            p = link.read(left)
            if p is None:
                break
            ident = parse_identity(p)
            if ident:
                return ident
    return None


class Updater:
    def __init__(self, backend, port=None):
        self.backend = backend
        self.port = port

    def candidates(self, only_port):
        names = self.backend.input_names()
        if self.port:
            mine = [n for n in names if self.port.lower() in n.lower()]
            if only_port:
                return mine
            return mine + [n for n in names if n not in mine and PORT_RE.search(n)]
        return [n for n in names if PORT_RE.search(n)]

    def find(self, want=None, only_port=True):
        """the first matching port that answers the handshake (and want(identity))"""
        outs = self.backend.output_names()
        for name in self.candidates(only_port):
            out = pair_output(name, outs)
            if not out:
                continue
            try:
                link = self.backend.open(name, out)
            except Exception:
                continue
            ident = handshake(link, 2)
            if ident and (want is None or want(ident)):
                return Device(link, ident, name)
            link.close()
        return None

    def wait_for(self, want, secs):
        end = time.monotonic() + secs
        while time.monotonic() < end:
            dev = self.find(want, only_port=False)
            if dev:
                return dev
            time.sleep(DELAY["retry"])
        return None

    def serve(self, link, image, finish, idle, progress):
        """answer read requests until the device asks for `finish`; -> (served, finished, lost)"""
        served, last = 0, time.monotonic()
        while True:
            pkt = link.read(DELAY["poll"])
            if pkt is None:
                if link.lost:
                    return served, False, True
                if time.monotonic() - last > idle:
                    return served, False, False
                continue
            r = parse_request(pkt)
            if not r:
                continue
            fl, addr, n = r
            last = time.monotonic()
            if addr in (FINISH_CHECK, FINISH_WRITE):
                link.send(response(addr, b"success\0"))
                if addr == finish:
                    return served, True, False
                continue
            if n > MAXDATA or addr + n > len(image):
                raise InstallError("badreq", f"the device asked for {addr:#x}+{n}, outside the package")
            time.sleep(DELAY["reply"])
            if not link.send(response(addr, image[addr:addr + n], fl)):
                return served, False, True
            served += 1
            progress(served, addr + n)

    def check(self, dev, image, step):
        """step 1: the running firmware checks the package and starts the loader"""
        step("start", dev.id.text)
        dev.link.send(UPGRADE)
        time.sleep(DELAY["start"])
        served, finished, lost = self.serve(dev.link, image, FINISH_CHECK, DELAY["idle_check"],
                                            lambda k, end: step("check", k))
        dev.link.close()
        if not finished:
            raise InstallError("lost" if lost else "stopped",
                               f"the FM-1 {'was disconnected' if lost else 'stopped answering'} after "
                               f"{served} requests; nothing was written")
        step("loader")
        time.sleep(DELAY["loader"])
        ota = self.wait_for(lambda i: i.loader, DELAY["wait_loader"])
        if not ota:
            raise InstallError("noloader", "the update loader did not appear. Replug the USB cable and "
                                           "run the install again: the FM-1 stays in update mode until it is done")
        return ota

    def write(self, ota, image, step):
        """step 2: the loader reads and writes the whole package, then restarts"""
        step("write", 0)
        ota.link.send(UPGRADE)
        time.sleep(DELAY["start"])
        served, finished, lost = self.serve(ota.link, image, FINISH_WRITE, DELAY["idle_write"],
                                            lambda k, end: step("write", min(99, end * 100 // len(image))))
        ota.link.close()
        if not finished:
            raise InstallError("lost" if lost else "stopped",
                               f"the loader {'was disconnected' if lost else 'stopped answering'} after "
                               f"{served} requests. Replug the USB cable and run the install again to finish")
        step("write", 100)

    def verify(self, product, step):
        step("reboot")
        time.sleep(DELAY["reboot"])
        back = self.wait_for(lambda i: not i.loader, DELAY["wait_reboot"])
        if not back:
            raise InstallError("noreturn", "the FM-1 did not come back: power-cycle it")
        back.link.close()
        if back.id.text != product:
            raise InstallError("mismatch", f"written, but the FM-1 reports {back.id.text} (expected {product})")
        step("done", back.id.text)
        return back.id.text

    def install(self, dev, image, product, step=lambda *a: None):
        """running firmware -> loader -> new firmware; dev from find(). A device already in
        update mode only needs the write."""
        try:
            family = package_family(image, product)
            if family is None:
                raise InstallError("model", "unknown package loader family; cannot establish loader compatibility")
        except InstallError:
            dev.link.close()
            raise
        if model_of(dev.id.text) != model_of(product):
            dev.link.close()
            raise InstallError("model", f"the device is {dev.id.text}, the package is for {product}")
        ota = dev if dev.id.loader else self.check(dev, image, step)
        require_loader(ota, family)    # both direct resume and the loader discovered after staging
        self.write(ota, image, step)
        return self.verify(product, step)


# ------------------------------------------------------------------- CLI ---

def load_package(path, force):
    """Validate before MIDI discovery; force is retained for caller compatibility only."""
    try:
        with open(path, "rb") as f:
            raw = f.read(MAX_PKG + 1)
    except OSError as e:
        raise InstallError("badpkg", f"cannot read {path}: {e.strerror}")
    if len(raw) > MAX_PKG:
        raise InstallError("badpkg", f"{path}: not an FM-1 package (larger than {MAX_PKG // 1024} KiB)")
    product = product_of(raw)
    image = logical_image(raw)
    family = package_family(image, product)
    if family == "stock-v15" and hashlib.sha256(raw).hexdigest() != STOCK_V15_SHA256:
        raise InstallError("badpkg", "official V15 requires the exact approved whole-file digest")
    if family is None:
        raise InstallError("badpkg", f"{path}: no Felucca update loader in this package; only Felucca's own "
                                     "packages and the unmodified official V15 (FM-1.fwsc) are installed "
                                     "(--force cannot approve an unknown loader family)")
    return product, image


def not_found(up):
    names = up.backend.input_names()
    where = f"no MIDI port matching {up.port!r} answered" if up.port else "FM-1 not found"
    return InstallError("notfound", f"{where} (USB data cable? another app using it?)"
                        f"\n  MIDI inputs: {', '.join(names) if names else '(none)'}")


class Progress:
    def __init__(self, out):
        self.out, self.line = out, False

    def __call__(self, k, a=None):
        if k == "check":
            self.put(f"checking the package ({a} reads)")
        elif k == "write":
            self.put(f"writing {a:3d}%")
        else:
            self.end()
            msg = {"start": f"starting the update on {a}", "loader": "switching to update mode",
                   "reboot": "restarting", "done": f"done: the FM-1 runs {a}"}[k]
            print(msg, file=self.out, flush=True)

    def put(self, s):
        print(f"\r{s}\033[K", end="", file=self.out, flush=True)
        self.line = True

    def end(self):
        if self.line:
            print(file=self.out, flush=True)
            self.line = False


def run(a, backend, out, ask):
    up = Updater(backend, a.port)
    if a.info:
        dev = up.find()
        if not dev:
            raise not_found(up)
        dev.link.close()
        mode = "update loader (update not finished)" if dev.id.loader else "running"
        print(f"{dev.id.text}  [{mode}]  port: {dev.name}", file=out)
        return 0
    product, image = load_package(a.package, a.force)
    print(f"package: {product}  ({a.package})", file=out)
    dev = up.find()
    if not dev:
        raise not_found(up)
    print(f"device:  {dev.id.text}  ({dev.name})" + ("  in update mode: the write will be finished" if dev.id.loader else ""),
          file=out)
    if not a.yes and not ask("Install? Do not unplug the FM-1 while writing. [y/N] "):
        dev.link.close()
        print("cancelled", file=out)
        return 1
    prog = Progress(out)
    try:
        up.install(dev, image, product, prog)
    finally:
        prog.end()
    return 0


def ask_tty(prompt):
    try:
        return input(prompt).strip().lower() in ("y", "yes")
    except EOFError:
        return False


def main(argv=None, backend=None, out=sys.stdout, ask=ask_tty):
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("package", nargs="?", help="Felucca package (.fwsc)")
    ap.add_argument("--info", action="store_true", help="print the identity of the connected FM-1")
    ap.add_argument("--port", metavar="NAME", help="MIDI port to use (part of its name)")
    ap.add_argument("--yes", action="store_true", help="do not ask for confirmation")
    ap.add_argument("--force", action="store_true", help="deprecated compatibility option; has no effect "
                    "(unknown loader families are rejected before MIDI access)")
    a = ap.parse_args(argv)
    if bool(a.info) == bool(a.package):
        ap.error("give a PACKAGE.fwsc or --info")
    try:
        if backend is None:
            try:
                backend = MidoBackend()
            except ImportError:
                raise InstallError("usage", midi_dependency_message(
                    __file__, argv if argv is not None else sys.argv[1:])) from None
        return run(a, backend, out, ask)
    except InstallError as e:
        print(f"error: {e}", file=sys.stderr)
        return EXIT.get(e.code, 1)
    except KeyboardInterrupt:
        print("\ninterrupted: if the FM-1 is in update mode, run the install again to finish", file=sys.stderr)
        return 130


if __name__ == "__main__":
    sys.exit(main())
