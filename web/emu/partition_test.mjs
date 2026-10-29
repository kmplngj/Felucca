// SPDX-License-Identifier: GPL-3.0-only
// #87: actual web_render/web_midi/web_buttons bridge, freshly instantiated per run.
// Reproduce: node web/emu/partition_test.mjs NATIVE [TEST.wasm] [0x87]
// NATIVE and TEST.wasm both compile partition_test.c including felucca_web.c.
// Render partitions: 1024 (API maximum), 1/23/37/257/19/512, and worklet-sized 128.
// All calls stop at the same scheduled output-frame/checkpoint boundaries. The
// producer can lead the drained output: events become available at ring_w, the
// next unrendered DMA half, not their requested output timestamp. Publication
// frame, ring_w/ring_r and device ms must match across partitions. No DSP call
// ever changes CTL=32. A deliberately late note is a different-input negative.
// This bypasses the worklet's wall-clock message arrival and button hold queue;
// scheduled panel presses stay down for >24 ms. It makes no hardware/jitter or
// sample-accurate external MIDI claim. web_midi accepts channel messages only;
// USB/TRS clock/start/stop fragmentation remains in tests/partition_test.c.
// The fixture uses fixed ANALOG presets, no sample assets, seeded xorshift32 and
// an erased NOR. Signed DAC24 / 2^23 is represented exactly as float32: compare
// every PCM bit (including signed zero), not a rounded hash or tolerance.
// Within each runtime PCM/state/publication equality is mandatory. This fixture
// also requires exact native/Wasm equality, separately from those invariants.
import fs from "node:fs";
import { spawnSync } from "node:child_process";

const native = process.argv[2];
const seedOnly = /^(?:0x[0-9a-f]+|[0-9]+)$/i.test(process.argv[3] || "");
const wasmPath = seedOnly ? null : process.argv[3];
if (!native) throw new Error("usage: partition_test.mjs NATIVE [TEST.wasm] [SEED]");
const seedArg = seedOnly ? process.argv[3] : process.argv[4];
if (seedArg !== undefined && (!Number.isInteger(Number(seedArg)) || Number(seedArg) < 0 || Number(seedArg) > 0xffffffff))
  throw new Error("seed must be a uint32 (decimal or 0x...)");
const seeds = seedArg !== undefined ? [Number(seedArg)] : [0x87, 1, 2, 3];
const wasm = wasmPath ? await WebAssembly.compile(fs.readFileSync(wasmPath)) : null;
let fails = 0;
function check(label, ok) {
  console.log(`emu partition: ${label}: ${ok ? "ok" : "FAIL"}`);
  if (!ok) fails++;
}
function firstDifference(a, b) {
  if (a.length !== b.length) return `length ${a.length} vs ${b.length}`;
  for (let i = 0; i < a.length; i++) if (a[i] !== b[i]) return `${i}: ${a[i]} vs ${b[i]}`;
  return null;
}
function same(label, a, b) {
  const diff = firstDifference(a, b);
  check(label + (diff === null ? "" : ` (first word ${diff})`), diff === null);
}
async function render(runtime, seed, partition, variant = 0) {
  if (runtime === "native") {
    const r = spawnSync(native, [String(seed), String(partition), String(variant)], { maxBuffer: 4 * 1024 * 1024 });
    if (r.error || r.status !== 0) throw new Error(`native fixture failed: ${r.error || r.stderr.toString() || r.status}`);
    const buf = r.stdout;
    if (buf.readUInt32LE(0) !== 0x87321280) throw new Error("native fixture returned invalid header");
    const frames = buf.readUInt32LE(4), ns = buf.readUInt32LE(8), no = buf.readUInt32LE(12);
    if (buf.length !== 16 + 4 * (frames * 2 + ns + no + 32)) throw new Error("native fixture returned truncated output");
    // Decode explicitly little endian rather than depend on Buffer's alignment.
    const u32 = (off, n) => Uint32Array.from({ length: n }, (_, i) => buf.readUInt32LE(off + i * 4));
    return { pcm: u32(16, frames * 2), state: u32(16 + frames * 8, ns),
      observations: u32(16 + frames * 8 + ns * 4, no), checks: u32(16 + frames * 8 + (ns + no) * 4, 32) };
  }
  const { exports: ex } = await WebAssembly.instantiate(wasm, {});
  ex._initialize();
  if (ex.web_partition_run(seed, partition, variant)) throw new Error("Wasm fixture queue overflow");
  const u32 = (ptr, n) => new Uint32Array(ex.memory.buffer, ptr, n).slice();
  return { pcm: u32(ex.web_partition_pcm(), ex.web_partition_frames() * 2),
    state: u32(ex.web_partition_state(), ex.web_partition_nstate()),
    observations: u32(ex.web_partition_observations(), ex.web_partition_nobservations()),
    checks: u32(ex.web_partition_checks(), 32) };
}
function health(label, r) {
  const floats = new Float32Array(r.pcm.buffer);
  const audible = (begin, end) => floats.subarray(begin * 2, end * 2).some(v => Number.isFinite(v) && Math.abs(v) > 0.001);
  check(`${label} finite non-silent early, sustained, released/transport and late PCM`,
    floats.every(Number.isFinite) && audible(256, 1024) && audible(3072, 4096) && audible(14000, 23000) && audible(38912, 40960));
  const [held, released, stopped, restarted] = [0, 8, 16, 24].map(i => r.checks.subarray(i, i + 8));
  check(`${label} pedal retains note 60 after key-up`, held[0] === 1 && held[1] === 0x11 && held[3] > 0);
  check(`${label} pedal release drops ownership and gate 60`, released[0] === 0 && released[1] === 0 && released[3] === 0);
  check(`${label} PLAY stops then restarts, late note 72 owned and gated`,
    released[5] === 1 && stopped[5] === 0 && restarted[5] === 1 && restarted[2] === 1 && restarted[4] > 0);
  check(`${label} input queue drained without overflow at checkpoints/final`,
    [held, released, stopped, restarted].every(c => c[7] === 0) && r.state[6] === 0 && r.state[7] === 0);
}

for (const seed of seeds) {
  const refs = {};
  for (const runtime of wasm ? ["native", "wasm"] : ["native"]) {
    const label = `${runtime} seed 0x${seed.toString(16)}`;
    const a = await render(runtime, seed, 0);
    refs[runtime] = a;
    health(label, a);
    for (const partition of [1, 2]) {
      const b = await render(runtime, seed, partition);
      const part = partition === 1 ? "irregular" : "128";
      same(`${label} ${part} exact complete PCM`, a.pcm, b.pcm);
      same(`${label} ${part} musical/transport final state`, a.state, b.state);
      same(`${label} ${part} actual event publication boundaries`, a.observations, b.observations);
      same(`${label} ${part} sustain/transport checkpoints`, a.checks, b.checks);
    }
    if (seed === seeds[0]) {
      const noRepeats = await render(runtime, seed, 0, 5);
      same(`${label} unchanged CC repetitions preserve complete PCM`, a.pcm, noRepeats.pcm);
      same(`${label} unchanged CC repetitions preserve final state`, a.state, noRepeats.state);
      for (const [variant, name] of [[1, "dropped note-on"], [2, "reordered pedal/note-off"],
        [3, "dropped pedal-up"], [4, "later arrival crossing DMA boundary"]]) {
        const m = await render(runtime, seed, 0, variant);
        check(`${label} negative ${name} changes complete PCM`, firstDifference(a.pcm, m.pcm) !== null);
        if (variant === 2) check(`${label} negative reordered events lose held gate`, m.checks[3] === 0);
        if (variant === 3) check(`${label} negative missing release retains note/gate at release checkpoint`,
          m.checks[8] === 1 && m.checks[9] === 0x11 && m.checks[11] > 0);
      }
    }
  }
  if (wasm) {
    same(`seed 0x${seed.toString(16)} cross-runtime exact DAC24/float32 PCM`, refs.native.pcm, refs.wasm.pcm);
    same(`seed 0x${seed.toString(16)} cross-runtime musical/transport state`, refs.native.state, refs.wasm.state);
  }
}
if (!wasm) console.log("emu partition: skip WebAssembly bridge (no test Wasm supplied)");
console.log(fails ? `emu partition: ${fails} FAILED` : "emu partition: all ok");
process.exitCode = fails ? 1 : 0;
