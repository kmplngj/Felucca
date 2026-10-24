// SPDX-License-Identifier: GPL-3.0-only
// Copyright (C) 2026 Leo Kuroshita (@kurogedelic), Hügelton Instruments
// The browser build (build/emu/felucca.wasm, web/emu/felucca_web.c) in Node, as the worklet runs it. After X0X's
// tests/host/emu_test.mjs (charlesvestal/fm1-x0x, GPL-3.0).
//   node web/emu/emu_test.mjs build/emu/felucca.wasm [NATIVE.f32]
// Checks: it boots (splash, then HOME on the screen, the HOME LED; the power-on LED sweep under the splash, over by
// 1 s), a held key sounds and lights its LED, PLAY
// starts the sequencer (PLAY's green LED), a user preset saved from the panel (SAVE, OCT+, OCT+) reaches the flash,
// and the flash sectors kept as the page keeps them bring it back in a fresh instance; the same gestures twice
// give the same audio (deterministic), with NATIVE.f32 (web/emu/native_check.c) the native build's, bit for bit.
// Then the cost: 1 s of a heavy song (FM6, PHYS, GRAIN chords, DRUM) against real time (BENCH_MAX, default 0.5:
// fails above half of real time on this machine).
import fs from "fs";
import { storeSectors, restoreSectors, midiKnob, KNOB_CC, MASTER_CC } from "./worklet.js";

const wasmPath = process.argv[2] || "build/emu/felucca.wasm", nativePath = process.argv[3], macroPath = process.argv[4];
const bytes = fs.readFileSync(wasmPath);
const B = { FX: 0, SCL: 1, ENV: 2, LFO: 3, EDIT: 4, GLO: 5, HOME: 6, SAVE: 7, ARP: 8, SEQ: 9, PLAY: 10, REC: 11, OCTDN: 12, OCTUP: 13 };
const EN = { SELECT: 0, ALGO: 1, PRESETS: 2, K1: 3, K2: 4, K3: 5, K4: 6 };
let fails = 0;
const check = (what, ok) => { console.log(`emu: ${what.padEnd(76)} ${ok ? "ok" : "FAIL"}`); if (!ok) fails++; };

async function device(saved) {
  const { instance } = await WebAssembly.instantiate(bytes, {});
  const ex = instance.exports, mem = ex.memory;
  ex._initialize();
  ex.web_nor_erase();
  if (saved) restoreSectors(new Uint8Array(mem.buffer, ex.web_nor(), ex.web_nor_size()), saved);
  ex.web_boot();
  const d = { ex, mem, peak: 0, sig: 0, rec: false, frames: 0, kept: [] };
  d.render = (ms) => {
    const n = Math.round(ms * 44.1);
    for (let k = 0; k < n; k += 128) {
      const m = Math.min(128, n - k);
      ex.web_render(m);
      const l = new Float32Array(mem.buffer, ex.web_out_l(), m), r = new Float32Array(mem.buffer, ex.web_out_r(), m);
      for (let i = 0; i < m; i++) {
        d.peak = Math.max(d.peak, Math.abs(l[i]), Math.abs(r[i]));
        if (d.rec) {
          d.sig = (d.sig * 31 + Math.round(l[i] * 32768) + 7 * Math.round(r[i] * 32768)) % 1000000007;
          d.kept.push(l[i], r[i]);
        }
      }
      d.frames += m;
    }
  };
  d.tap = (b) => { ex.web_buttons(1 << b); d.render(60); ex.web_buttons(0); d.render(60); };
  d.turn = (role, n) => { for (let i = 0; i < Math.abs(n); i++) { ex.web_enc(role, Math.sign(n)); d.render(40); } };
  Object.defineProperty(d, "samples", { get: () => new Float32Array(d.kept) });
  d.screen = () => new Uint16Array(mem.buffer, ex.web_screen(), 240 * 240).slice();
  return d;
}
const colours = (fb) => new Set(fb).size;

// ---- boot, keys, screen, LEDs
const a = await device(null);
a.render(200);
const splash = colours(a.screen());
{ // the power-on LED sweep (hal/fm1_led_anim.h) under the splash: at 200 ms its head on the middle of the keyboard, the
  // keys it passed glowing (DIM HI), the ones ahead dark, the buttons not yet; the UI's LEDs untouched until it ends
  const p = a.ex.web_anim_levels(), lv = p ? Array.from(new Uint8Array(a.mem.buffer, p, 41)) : [];
  const keys = lv.slice(14), head = keys.indexOf(Math.max(...keys.map((q) => q & 127)) | 128);
  check(`power-on LED sweep: at 200 ms the head on key ${head}, glow behind, dark ahead, buttons dark`,
        lv.length === 41 && head >= 8 && head <= 18 && keys.slice(0, head - 6).every((q) => q === 128) &&
        keys.slice(head + 3).every((q) => q === 0) && lv.slice(0, 14).every((q) => q === 0) &&
        a.ex.web_lit_keys() === 0 && a.ex.web_lit_buttons() === 0);
}
a.render(800);
check("  over by 1 s (~0.70 s)", a.ex.web_anim_levels() === 0);
const home = a.screen();
check(`boots: the splash, then HOME (${colours(home)} colours), the HOME LED lit`,
      splash > 1 && colours(home) > 4 && (a.ex.web_lit_buttons() >> B.HOME & 1) === 1);
check("silent at rest", a.peak === 0);
for (const id of [B.PLAY, B.HOME, 14, 40]) {
  const d = await device(null), initial = d.ex.web_screen_draws();
  d.render(5);
  const press = (on) => id < 14 ? d.ex.web_buttons(on ? 1 << id : 0) : d.ex.web_keys(on ? 1 << (id - 14) : 0);
  press(true);
  d.render(50);
  check(`splash dismissed by ${id} after scan settling`, d.ex.web_screen_draws() > initial);
  d.render(800);
  check(`dismissal ${id} stays silent while held`, d.ex.web_playing() === 0 && d.peak === 0);
  press(false);
  d.render(60);
  d.tap(B.PLAY);
  check(`PLAY works after dismissal ${id} is released`, d.ex.web_playing() === 1);
}
a.ex.web_keys(1 << 7);                                        // C4
a.render(300);
const keyLit = (a.ex.web_lit_keys() >> 7) & 1;
a.ex.web_keys(0);
a.render(400);
check(`a key sounds (peak ${a.peak.toFixed(3)}) and lights its LED`, a.peak > 0.01 && keyLit === 1);
a.render(1500);
a.peak = 0;
a.ex.web_midi(0x90, 64, 100);                                  // Web MIDI: E4 on channel 1
a.render(300);
a.ex.web_midi(0x80, 64, 0);
a.render(300);
check(`a MIDI note in (USB-MIDI's queue) sounds (peak ${a.peak.toFixed(3)})`, a.peak > 0.01);
const draws = a.ex.web_screen_draws();
a.turn(EN.K1, 3);
check("KNOB 1 redraws the screen", a.ex.web_screen_draws() > draws);
a.tap(B.PLAY);
a.render(1000);
check("PLAY: the sequencer runs, PLAY's green LED", a.ex.web_playing() === 1 && (a.ex.web_lit_buttons() >> 14 & 1) === 1);
a.tap(B.PLAY);
a.render(300);
check("PLAY again stops it", a.ex.web_playing() === 0);
a.ex.web_buttons(1 << B.FX);                                  // #119: FX held, its map: the effects breathe
a.render(800);
const brK = a.ex.web_breath_keys(), brB = a.ex.web_breath_buttons(), litK = a.ex.web_lit_keys();
a.ex.web_buttons(0);
a.render(300);
check("FX held: its button and the effects' keys breathe, none lit; let go: nothing",
      (brB >> B.FX & 1) === 1 && brK !== 0 && (brK & litK) === 0 && litK === 0 &&
      a.ex.web_breath_keys() === 0 && a.ex.web_breath_buttons() === 0);
{ // the page's breathing peaks against the firmware's (hal/fm1_input.h FM1_LED_BREATH_PK / _LO, /256 of lit): the
  // colour at 50 % between the dark and the lit one by the LED's share, gamma-encoded (sRGB), within 0.06
  const html = fs.readFileSync(new URL("./index.html", import.meta.url), "utf8");
  const hal = fs.readFileSync(new URL("../../firmware/hal/fm1_input.h", import.meta.url), "utf8");
  const pk = (n) => +hal.match(new RegExp(`#define ${n} (\\d+)u`))[1] / 256;
  const srgb = (x) => x <= 0.0031308 ? 12.92 * x : 1.055 * x ** (1 / 2.4) - 0.055;
  const red = (c) => parseInt(c.slice(1, 3), 16);
  const share = (name, lit) => {                        // (the red channel: the peak's share of dark .. lit)
    const m = html.match(new RegExp(`@keyframes ${name} \\{ 0%, 100% \\{ fill: (#[0-9a-f]{6}); \\} 50% \\{ fill: (#[0-9a-f]{6})`));
    return (red(m[2]) - red(m[1])) / (lit - red(m[1]));
  };
  const hi = srgb(pk("FM1_LED_BREATH_PK")), lo = srgb(pk("FM1_LED_BREATH_PK_LO")), litBtn = 0xff, litSlit = 0xec;
  const got = [share("breath-btn", litBtn), share("breath-slit", litSlit), share("breath-btn-lo", litBtn), share("breath-slit-lo", litSlit)];
  check(`the page's breath peaks ${got.map((x) => x.toFixed(2)).join(" ")} ~ ${hi.toFixed(2)} (HI) ${lo.toFixed(2)} (LO)`,
        Math.abs(got[0] - hi) <= 0.06 && Math.abs(got[1] - hi) <= 0.06 && Math.abs(got[2] - lo) <= 0.06 &&
        Math.abs(got[3] - lo) <= 0.06);
}

// ---- a user preset saved from the panel, kept across a fresh instance
const w0 = a.ex.web_flash_writes_count();
a.tap(B.SAVE);
a.tap(B.OCTUP);
a.tap(B.OCTUP);
a.render(200);
const saved = storeSectors(new Uint8Array(a.mem.buffer, a.ex.web_nor(), a.ex.web_nor_size()));
check(`SAVE, OCT+, OCT+: user preset 1 written (${Object.keys(saved).length} sectors kept)`,
      a.ex.web_test_user_preset(0) === 1 && a.ex.web_flash_writes_count() > w0 && Object.keys(saved).length > 0);
const kept = JSON.parse(JSON.stringify(Object.fromEntries(     // as the page keeps them (base64 in localStorage)
  Object.entries(saved).map(([k, v]) => [k, Buffer.from(v).toString("base64")]))));
const b = await device(Object.fromEntries(Object.entries(kept).map(([k, v]) => [k, new Uint8Array(Buffer.from(v, "base64"))])));
b.render(600);
const c = await device(null);
c.render(600);
check("a fresh instance with the kept sectors has it; one without does not",
      b.ex.web_test_user_preset(0) === 1 && c.ex.web_test_user_preset(0) === 0);

// ---- append-only SCL values and bounded quick-layer pages (#634)
{
  const d = await device(null); d.render(600);
  d.ex.web_buttons(1 << B.SCL); d.render(600);           // physical SEL held
  d.turn(EN.K2, 15);
  const at15 = d.screen();
  let ok = d.ex.web_test_param(26) === 15;              // stable P_SCALE id
  d.turn(EN.K2, 1); const at16 = d.screen();
  ok &&= d.ex.web_test_param(26) === 16 && at16.some((v, i) => v !== at15[i]);
  d.turn(EN.K2, 1); ok &&= d.ex.web_test_param(26) === 17;
  d.turn(EN.K2, 1); ok &&= d.ex.web_test_param(26) === 18;
  d.ex.web_buttons((1 << B.SCL) | (1 << B.GLO)); d.render(60);
  d.ex.web_buttons(1 << B.SCL); d.render(60);
  d.turn(EN.K2, -3); ok &&= d.ex.web_test_param(26) === 15;
  d.turn(EN.K2, 3);
  d.ex.web_buttons((1 << B.SCL) | (1 << B.OCTDN)); d.render(60);
  d.ex.web_buttons(1 << B.SCL); d.render(60);
  ok &&= d.ex.web_test_param(26) === 0;                 // opening scale restored
  d.ex.web_buttons(0); d.render(500);
  check("SCL 15/16/17/18 page crossing, GLO ownership and OCT- undo", ok);
  d.ex.web_keys(1 << 7); d.render(100); d.ex.web_keys(0); d.render(1200);
  d.tap(B.PLAY); d.tap(B.PLAY);
  check("SCL closes cleanly: notes release and PLAY/STOP still work", d.ex.web_playing() === 0 && d.peak > 0.01);
}

// ---- legacy and added MACRO models through the panel's save/name/load flow
// Read the controls as well as slot occupancy: an occupied slot alone cannot prove that
// the new engine ID, its eight controls and the category survived the flash round trip.
const macroParams = (d) => Array.from({ length: 8 }, (_, i) => d.ex.web_test_param(d.ex.web_test_engine_param_base() + i));
const userName = (d) => Buffer.from(new Uint8Array(d.mem.buffer, d.ex.web_test_user_name(0), 12))
  .toString("ascii").replace(/\0.*$/, "");
if (a.ex.web_test_macro_count()) for (const [model, pi, category] of [["WAVE", 0, 4], ["FOLD", 2, 3], ["FBFM", 4, 5], ["PLUCKED", 32, 5], ["WAVE MAP", 42, 3], ["QPSK", 49, 8]]) {
  const d = await device(null);
  d.render(600);
  d.ex.web_buttons(1 << B.EDIT); d.render(600);            // EDIT held: the engine map
  const rank = d.ex.web_test_engine_rank(14);
  // White engine-map keys start at F3; derive the physical key from this profile's rank.
  const whiteKeys = [0, 2, 4, 6, 7, 9, 11, 12, 14, 16, 18, 19, 21, 23, 24, 26];
  check(`MACRO has a selectable engine-map key (rank ${rank})`, rank < whiteKeys.length);
  d.ex.web_keys(1 << whiteKeys[rank]); d.render(60);
  d.ex.web_keys(0); d.ex.web_buttons(0); d.render(500);    // let the layer's knob guard expire
  d.turn(EN.PRESETS, pi);
  const original = macroParams(d);
  d.turn(EN.K1, 3); d.turn(EN.K2, -2); d.turn(EN.K3, -2);  // TIMBRE, COLOR, CUT on HOME
  d.tap(B.EDIT); d.turn(EN.K4, 1);                         // OSC: TUNE
  d.render(500);                                        // a second page tap, outside EDIT's double-tap lock window
  d.tap(B.EDIT); d.turn(EN.K2, 1); d.turn(EN.K3, 1); d.turn(EN.K4, 1); // TONE: RES, DRIVE, FINE
  d.tap(B.HOME);
  const expected = macroParams(d), writes = d.ex.web_flash_writes_count();
  check(`MACRO ${model}: panel edits seven controls while retaining the model`,
        expected[0] === original[0] && expected.slice(1).every((v, i) => v !== original[i + 1]));
  d.tap(B.SAVE); d.tap(B.OCTUP);                          // USER -> NAME, empty U01
  d.ex.web_keys(1 << 19); d.render(60);                   // C5 / XYZ: append X to MACRO 01
  d.ex.web_keys(0); d.render(900);
  d.turn(EN.K3, 1);                                     // pick the next category
  d.tap(B.OCTUP); d.render(200);
  check(`MACRO ${model}: named user preset saved (category ${d.ex.web_test_user_category(0)}, expected ${category})`,
        d.ex.web_test_user_preset(0) === 1 && d.ex.web_flash_writes_count() > writes &&
        userName(d) === "MACRO 01X" && d.ex.web_test_user_category(0) === category);
  d.tap(B.HOME); d.turn(EN.PRESETS, 1); d.tap(B.SAVE);    // change sound before LOAD
  d.turn(EN.K2, 1); d.tap(B.OCTUP); d.render(100);        // USER: select LOAD, confirm
  check(`MACRO ${model}: LOAD restores engine 14 and all eight edited controls`,
        d.ex.web_test_engine() === 14 && JSON.stringify(macroParams(d)) === JSON.stringify(expected));
  const sectors = storeSectors(new Uint8Array(d.mem.buffer, d.ex.web_nor(), d.ex.web_nor_size()));
  const json = JSON.parse(JSON.stringify(Object.fromEntries(
    Object.entries(sectors).map(([k, v]) => [k, Buffer.from(v).toString("base64")]))));
  const fresh = await device(Object.fromEntries(Object.entries(json)
    .map(([k, v]) => [k, new Uint8Array(Buffer.from(v, "base64"))])));
  fresh.render(600); fresh.tap(B.SAVE); fresh.turn(EN.K2, 1); fresh.tap(B.OCTUP); fresh.render(100);
  check(`MACRO ${model}: fresh instance restores controls, custom name and category`,
        fresh.ex.web_test_engine() === 14 && JSON.stringify(macroParams(fresh)) === JSON.stringify(expected) &&
        userName(fresh) === "MACRO 01X" && fresh.ex.web_test_user_category(0) === category);
  fresh.peak = 0; fresh.ex.web_keys(1 << 7); fresh.render(300); fresh.ex.web_keys(0); fresh.render(400);
  check(`MACRO ${model}: the reloaded custom sound plays`, fresh.peak > 0.01 && fresh.peak <= 1);
}

// ---- the panel's knobs from a MIDI controller: the page turns them by midiKnob (worklet.js), as a drag does
{
  const last = [], cc = KNOB_CC + EN.PRESETS, k = (c, v, mode) => midiKnob(last, c, v, mode);
  const a = [k(cc, 40), k(cc, 43), k(cc, 41), k(MASTER_CC, 127), k(74, 10), k(28, 10)];
  check("absolute (the default) CC 22 (PRESETS): its first value takes its place, then +3, -2; CC 27 MASTER; CC 74, 28 the firmware's",
        a[0].role === EN.PRESETS && a[0].n === 0 && a[1].n === 3 && a[2].n === -2 && a[3].master === 1023 &&
        a[4] === null && a[5] === null);
  const n = (mode, vs) => vs.map((v) => k(cc, v, mode).n).join();
  check("relative CC 22: 64+-n, two's complement, sign bit; CC 27 absolute in each",
        n("bin", [65, 63, 64, 70, 0, 127]) === "1,-1,0,6,-64,63" && n("twos", [1, 127, 0, 63, 64]) === "1,-1,0,63,-64" &&
        n("sign", [1, 65, 0, 64, 127]) === "1,-1,0,0,-63" &&
        ["bin", "twos", "sign"].every((m) => k(MASTER_CC, 0, m).master === 0 && k(MASTER_CC, 127, m).master === 1023) &&
        k(20, 65, "bin").role === EN.SELECT && k(26, 65, "bin").role === EN.K4 && k(19, 65, "bin") === null);
  const t = await device(null), u = await device(null);             // u: left alone
  t.render(1200);
  u.render(1200);
  t.render(40);
  t.turn(EN.PRESETS, 3);
  t.render(300);
  u.render(460);
  const ts = t.screen(), us = u.screen();
  for (const [mode, vs] of [["abs", [64, 65, 66, 67]], ["bin", [65, 65, 65]], ["twos", [1, 1, 1]], ["sign", [1, 1, 1]]]) {
    const m = await device(null), knob = [];                   // a controller's knob: three detents
    m.render(1200);
    for (const v of vs) {
      const r = midiKnob(knob, cc, v, mode);
      if (r.n) m.ex.web_enc(r.role, r.n);
      m.render(40);
    }
    if (mode !== "abs") m.render(40);                           // as many 40 ms steps as the four absolute values
    m.render(300);
    const ms = m.screen();
    check(`CC 22 ${mode} ${vs.join(" ")} turns PRESETS as three detents of the panel's knob do`,
          ms.some((v, i) => v !== us[i]) && ms.every((v, i) => v === ts[i]));
  }
}

// ---- deterministic: the same gestures, the same samples
async function song() {
  const d = await device(null);
  d.render(500);
  d.ex.web_test_heavy();
  d.tap(B.PLAY);
  d.rec = true;
  d.render(2000);
  return d;
}
const s1 = await song(), s2 = await song();
check(`the heavy song plays (peak ${s1.peak.toFixed(3)}), twice the same samples`, s1.peak > 0.05 && s1.sig === s2.sig);
if (nativePath) {                                             // web/emu/native_check.c: the same song, built with cc
  const nat = new Float32Array(new Uint8Array(fs.readFileSync(nativePath)).buffer);
  const web = s1.samples;
  let diff = nat.length > 0 && nat.length === web.length ? 0 : Infinity;
  for (let i = 0; i < web.length && diff === 0; i++) if (nat[i] !== web[i]) diff = i + 1;
  check(`the same song from the native build (cc): ${web.length / 2} frames, ${diff === 0 ? "bit for bit" : "differs at " + diff}`, diff === 0);
}

// ---- the cost: 1 s of the heavy song against real time (the best of 3, after 2 s to settle)
let best = Infinity;
s1.rec = false;
for (let i = 0; i < 3; i++) {
  const t0 = performance.now();
  s1.render(1000);
  best = Math.min(best, performance.now() - t0);
}
const ratio = best / 1000, max = +(process.env.BENCH_MAX || 0.5);
check(`1 s of the heavy song (FM6 PHYS GRAIN chords + DRUM) in ${best.toFixed(1)} ms: ${(ratio * 100).toFixed(1)} % of real time`, ratio < max);
// All 51 MACRO presets, real key events, TIMBRE/COLOR knob turns and release tails.
// Keep this gesture/render/record sequence paired with native_check.c's macro replay.
if (a.ex.web_test_macro_count()) {
check("MACRO bank exposes 51 presets", a.ex.web_test_macro_count() === 51);
const models = new Set();
const macro = await device(null);
macro.render(500);
for (let pi = 0; pi < macro.ex.web_test_macro_count(); pi++) {
  macro.ex.web_test_macro(pi); macro.render(100);
  models.add(macro.ex.web_test_param(macro.ex.web_test_engine_param_base()));
  // Include the attack: triggered percussion can have decayed after 300 ms.
  macro.rec = true; macro.peak = 0;
  macro.ex.web_keys((1 << 7) | (1 << 11) | (1 << 14) | (1 << 19)); macro.render(300);
  macro.render(400);
  macro.ex.web_enc(EN.K1, 20); macro.render(200);
  macro.ex.web_enc(EN.K2, -20); macro.render(200);
  macro.ex.web_keys(0); macro.render(1000);
  macro.rec = false; macro.render(3000);
  check(`MACRO preset ${pi}: keys, TIMBRE/COLOR gestures and release (peak ${macro.peak.toFixed(3)})`, macro.peak > 0.01 && macro.peak <= 1);
}
check("all 48 MACRO models exercised by factory bank", models.size === 48 && Math.min(...models) === 0 && Math.max(...models) === 47);
check("MACRO native oracle supplied", !!macroPath);
if (macroPath) {
  const nat = new Float32Array(new Uint8Array(fs.readFileSync(macroPath)).buffer), web = macro.samples;
  let diff = nat.length > 0 && nat.length === web.length ? 0 : Infinity;
  for (let i = 0; i < web.length && diff === 0; i++) if (nat[i] !== web[i]) diff = i + 1;
  check(`51 MACRO presets native/Wasm: ${web.length / 2} frames, ${diff === 0 ? "bit for bit" : "differs at " + diff}`, diff === 0);
}
}
console.log(fails ? `emu: ${fails} FAILED` : "emu: all ok");
process.exit(fails ? 1 : 0);
