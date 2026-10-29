// SPDX-License-Identifier: GPL-3.0-only
// A short real-browser gate. No model calls; one summary, media on failure only.
import assert from "node:assert/strict";
import { createHash } from "node:crypto";
import { execFileSync } from "node:child_process";
import { createServer } from "node:http";
import { readFile, writeFile, mkdir, mkdtemp } from "node:fs/promises";
import { resolve, relative, extname, sep } from "node:path";
import { fileURLToPath } from "node:url";
import { installProbe, observeMacroWorklet } from "./browser_probe.js";

const root = fileURLToPath(new URL("../../", import.meta.url));
const build = resolve(root, "build"), site = resolve(build, "emu");
const keepMedia = process.argv.slice(2).includes("--artifacts=always");
assert(process.argv.slice(2).every((arg) => arg === "--artifacts=always"), "usage: npm test -- [--artifacts=always]");
await mkdir(resolve(build, "browser"), { recursive: true });
const out = await mkdtemp(resolve(build, "browser/run-"));
const report = { schema: 1, status: "fail", checks: [], errors: [], evidence: [], scope: "Chromium emulator; no physical FM-1" };
const hash = (data) => createHash("sha256").update(data).digest("hex");
let browser, page, server, capturedAudio, factoryEnvelope, current = "setup";
const screenshots = new Map();
const messages = [];

async function check(name, action) {
  current = name;
  const start = Date.now();
  const observed = await action();
  report.checks.push({ name, status: "pass", ms: Date.now() - start, ...(observed && { observed }) });
}
// Wrapper text sits on the page's flat background. Read actual rendered colors
// and ancestor opacity so a faded footer cannot pass on its CSS token alone.
async function wrapperContrast() {
  const rows = await page.locator(".keys, footer").evaluateAll((roots) => {
    const rgba = (value) => value.match(/[\d.]+/g).map(Number);
    const background = rgba(getComputedStyle(document.body).backgroundColor);
    const luminance = (rgb) => rgb.slice(0, 3).map((c) => {
      const s = c / 255;
      return s <= 0.04045 ? s / 12.92 : ((s + 0.055) / 1.055) ** 2.4;
    }).reduce((sum, c, i) => sum + c * [0.2126, 0.7152, 0.0722][i], 0);
    const elements = new Set();
    for (const root of roots) {
      const walker = document.createTreeWalker(root, NodeFilter.SHOW_TEXT);
      while (walker.nextNode()) if (walker.currentNode.textContent.trim()) elements.add(walker.currentNode.parentElement);
    }
    return [...elements].filter((el) => el.getClientRects().length).map((el) => {
      const ink = rgba(getComputedStyle(el).color);
      let alpha = ink[3] ?? 1;
      for (let parent = el; parent; parent = parent.parentElement) alpha *= Number(getComputedStyle(parent).opacity);
      const rendered = ink.slice(0, 3).map((c, i) => c * alpha + background[i] * (1 - alpha));
      const a = luminance(rendered), b = luminance(background);
      return { text: el.textContent.trim().slice(0, 80), ratio: (Math.max(a, b) + 0.05) / (Math.min(a, b) + 0.05) };
    });
  });
  assert(rows.length > 20, "wrapper text was not rendered");
  for (const row of rows) assert(row.ratio >= 4.5, `${row.text}: rendered contrast ${row.ratio.toFixed(2)}:1 < 4.5:1`);
  assert(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth), "horizontal page overflow");
  return { text_elements: rows.length, minimum_ratio: Math.min(...rows.map((row) => row.ratio)) };
}
async function screen(name) {
  const pixels = await page.locator("#screen").evaluate((canvas) => {
    // Read a copy so observation does not change the page canvas's rendering mode.
    const context = new OffscreenCanvas(240, 240).getContext("2d", { willReadFrequently: true });
    context.drawImage(canvas, 0, 0);
    const data = context.getImageData(0, 0, 240, 240).data;
    const colors = new Set();
    for (let i = 0; i < data.length; i += 4) colors.add((data[i] << 16) | (data[i + 1] << 8) | data[i + 2]);
    return { colors: colors.size, pixels: Array.from(data) };
  });
  assert(pixels.colors > 4, `${name}: blank or incomplete LCD (${pixels.colors} colors)`);
  screenshots.set(name, await page.locator("#screen").screenshot());
  // ui.c's default graph panel is y=76..197; exclude transient header/card highlights.
  return { sha256: hash(Buffer.from(pixels.pixels)), colors: pixels.colors,
    graph_sha256: hash(Buffer.from(pixels.pixels.slice(76 * 240 * 4, 198 * 240 * 4))) };
}
async function waitFor(fn, arg) {
  const handle = await page.waitForFunction(fn, arg, { timeout: 8000 });
  const value = await handle.jsonValue();
  await handle.dispose();
  return value;
}
async function freshAudio(predicate) {
  const after = await page.evaluate(() => __feluccaTest.samples);
  return waitFor(({ after, sounding }) => {
    const p = __feluccaTest, a = p.latest;
    return p.samples >= after + 8192 && a?.finite &&
      (sounding ? Math.min(a.left_rms, a.right_rms) > 0.001 : a.rms < 0.0001) && a;
  }, { after, sounding: predicate });
}
async function tap(name) {
  // Keyboard focus on the real target exercises its DOM listeners. A held key
  // lasts long enough for the page -> worklet -> firmware input queue.
  const target = page.getByRole("button", { name, exact: true });
  await target.focus();
  await page.keyboard.down("Enter");
  await page.waitForTimeout(80);
  await page.keyboard.up("Enter");
  await page.waitForTimeout(80);
}
function wav(blocks, rate) {
  const frames = blocks.reduce((n, b) => n + b.left.length, 0);
  const data = Buffer.alloc(44 + frames * 4);
  data.write("RIFF"); data.writeUInt32LE(data.length - 8, 4); data.write("WAVEfmt ", 8);
  data.writeUInt32LE(16, 16); data.writeUInt16LE(1, 20); data.writeUInt16LE(2, 22);
  data.writeUInt32LE(rate, 24); data.writeUInt32LE(rate * 4, 28);
  data.writeUInt16LE(4, 32); data.writeUInt16LE(16, 34);
  data.write("data", 36); data.writeUInt32LE(frames * 4, 40);
  let offset = 44;
  for (const block of blocks) for (let i = 0; i < block.left.length; i++) for (const ch of ["left", "right"]) {
    const sample = Number.isFinite(block[ch][i]) ? block[ch][i] : 0;
    data.writeInt16LE(Math.round(Math.max(-1, Math.min(1, sample)) * 32767), offset); offset += 2;
  }
  return data;
}

try {
  execFileSync(process.env.PYTHON || "python3", ["tools/profile.py", "--check"], { cwd: root, stdio: "pipe" });
  report.build = JSON.parse(await readFile(resolve(build, "gen/build-identity.json"), "utf8"));
  report.inputs = {};
  for (const name of ["felucca.wasm", "index.html", "worklet.js"]) report.inputs[name] = hash(await readFile(resolve(site, name)));
  const { chromium } = await import("playwright");
  server = createServer(async (req, res) => {
    try {
      const path = new URL(req.url, "http://localhost").pathname;
      if (path === "/favicon.ico") { res.writeHead(204).end(); return; }
      const file = resolve(site, "." + decodeURIComponent(path === "/" ? "/index.html" : path));
      if (!file.startsWith(site + sep)) { res.writeHead(403).end(); return; }
      let bytes = await readFile(file);
      if (file === resolve(site, "worklet.js")) {
        bytes = Buffer.from(observeMacroWorklet(bytes.toString("utf8")));
        report.inputs.observed_worklet = hash(bytes);
      }
      const mime = { ".html": "text/html", ".js": "text/javascript", ".wasm": "application/wasm", ".woff": "font/woff" };
      res.writeHead(200, { "Content-Type": mime[extname(file)] || "application/octet-stream", "Cache-Control": "no-store" }).end(bytes);
    } catch { res.writeHead(404).end(); }
  });
  await new Promise((res, rej) => { server.once("error", rej); server.listen(0, "127.0.0.1", res); });
  browser = await chromium.launch({ headless: true, ...(process.env.PLAYWRIGHT_CHROMIUM_EXECUTABLE_PATH && {
    executablePath: process.env.PLAYWRIGHT_CHROMIUM_EXECUTABLE_PATH,
  }) });
  report.browser = { version: browser.version(), playwright: JSON.parse(await readFile(new URL("node_modules/playwright/package.json", import.meta.url), "utf8")).version };
  page = await browser.newPage({ viewport: { width: 1200, height: 900 } });
  page.setDefaultTimeout(8000);
  // Keep errors bounded; never stream a console, framebuffer or PCM into an agent.
  const error = (message) => { if (messages.length < 20) messages.push(message.slice(0, 1000)); };
  page.on("pageerror", (e) => error(String(e)));
  page.on("console", (m) => { if (m.type() === "error" || m.type() === "warning") error(`${m.type()}: ${m.text()}`); });
  page.on("requestfailed", (r) => error(`request failed: ${r.url()} ${r.failure()?.errorText}`));
  page.on("response", (r) => { if (r.status() >= 400) error(`HTTP ${r.status()}: ${r.url()}`); });
  await page.addInitScript(installProbe);
  await check("boot and LCD", async () => {
    await page.goto(`http://127.0.0.1:${server.address().port}/`);
    await page.evaluate(() => document.fonts.ready);
    assert.equal(await page.getByRole("button", { name: "SEL", exact: true }).count(), 1);
    assert.equal(await page.getByRole("button", { name: "SCL", exact: true }).count(), 0);
    assert.equal(await page.getByRole("slider", { name: "SELECT", exact: true }).count(), 1);
    await page.getByRole("button", { name: "Switch on", exact: true }).click();
    await page.locator("#start").waitFor({ state: "hidden" });
    await waitFor(() => __feluccaTest.frames > 5 && (__feluccaTest.leds[0] & (1 << 6)));
    assert.equal(await page.evaluate(() => __feluccaTest.context.state), "running");
    await page.evaluate(() => __feluccaTest.listen());
    assert.equal(await page.evaluate(() => __feluccaTest.context.sampleRate), 44100);
    return screen("home");
  });
  await check("desktop wrapper text contrast", wrapperContrast);
  await check("keyboard note produces stereo PCM", async () => {
    await page.keyboard.down("z");
    assert.equal(await page.getByRole("button", { name: "F3", exact: true }).getAttribute("aria-pressed"), "true");
    const observed = await freshAudio(true);
    assert(observed.peak <= 1, `out-of-range audio: ${observed.peak}`);
    await page.keyboard.up("z");
    assert.equal(await page.getByRole("button", { name: "F3", exact: true }).getAttribute("aria-pressed"), "false");
    return observed;
  });
  await check("note release becomes quiet", () => freshAudio(false));
  await check("focused note keys support Enter, Space and blur release", async () => {
    const key = page.getByRole("button", { name: "F3", exact: true });
    const other = page.getByRole("button", { name: "G3", exact: true });
    for (const code of ["Enter", "Space", "NumpadEnter"]) {
      await key.focus();
      const scroll = await page.evaluate(() => scrollY);
      await page.keyboard.down(code);
      assert.equal(await key.getAttribute("aria-pressed"), "true");
      await freshAudio(true);
      await page.keyboard.down(code);                    // auto-repeat must keep the same held note
      assert.equal(await key.getAttribute("aria-pressed"), "true");
      assert.equal(await page.evaluate(() => scrollY), scroll, `${code} scrolled the page`);
      await page.keyboard.up(code);
      assert.equal(await key.getAttribute("aria-pressed"), "false");
      await freshAudio(false);
    }
    await key.focus();
    await page.keyboard.down("NumpadEnter");
    await page.keyboard.down("Space");
    await freshAudio(true);
    await page.keyboard.up("Space");
    assert.equal(await key.getAttribute("aria-pressed"), "true", "NumpadEnter still owns the held key");
    await other.focus();
    assert.equal(await key.getAttribute("aria-pressed"), "false", "blur left the key pressed");
    await freshAudio(false);
    await page.keyboard.up("NumpadEnter");
    assert.equal(await other.getAttribute("aria-pressed"), "false", "focus transfer pressed another key");
    return { activation: ["Enter", "Space", "NumpadEnter"], repeat_held: true, blur_released: true };
  });
  await check("click-only note activation is momentary and does not duplicate physical input", async () => {
    const key = page.getByRole("button", { name: "F3", exact: true });
    const other = page.getByRole("button", { name: "G3", exact: true });
    await key.focus();
    const click = await key.evaluate((el) => {
      const after = __feluccaTest.samples;                  // snapshot before the click in this same browser task
      el.click();                                           // click-only DOM activation, not a real AT test
      return { after, pressed: el.getAttribute("aria-pressed") };
    });
    assert.equal(click.pressed, "true");
    await page.waitForTimeout(500);                          // retained PCM must survive the short note's release
    await waitFor((after) => {
      const p = __feluccaTest, size = 2048;
      const first = p.samples - p.audio.length * size;
      if (first > after) throw new Error("click audio window expired from the PCM tap");
      return p.audio.some((block, i) => {
        if (first + (i + 1) * size <= after) return false;
        return [block.left, block.right].every((channel) =>
          channel.every(Number.isFinite) && Math.sqrt(channel.reduce((sum, x) => sum + x*x, 0) / channel.length) > 0.001);
      });
    }, click.after);
    await waitFor(() => document.querySelector('[aria-label="F3"]').getAttribute("aria-pressed") === "false");
    await freshAudio(false);
    const pressedBeforeBlur = await key.evaluate((el) => { el.click(); return el.getAttribute("aria-pressed"); });
    assert.equal(pressedBeforeBlur, "true");
    await other.focus();
    assert.equal(await key.getAttribute("aria-pressed"), "false", "blur left virtual note held");
    await freshAudio(false);
    await key.focus();
    await key.evaluate((el) => el.dispatchEvent(new MouseEvent("click", { bubbles: true, detail: 1 })));
    assert.equal(await key.getAttribute("aria-pressed"), "false", "pointer click duplicated note");
    await page.keyboard.down("Enter");
    await key.evaluate((el) => el.click());                 // synthesized click while keyboard owns it
    await page.keyboard.up("Enter");
    assert.equal(await key.getAttribute("aria-pressed"), "false", "keyboard click duplicated note");
    await key.evaluate((el) => {
      el.dispatchEvent(new KeyboardEvent("keydown", { key: "Enter", code: "Enter", bubbles: true }));
      el.dispatchEvent(new KeyboardEvent("keyup", { key: "Enter", code: "Enter", bubbles: true }));
      el.click();                                         // follow-on click in the same event turn
    });
    assert.equal(await key.getAttribute("aria-pressed"), "false", "follow-on keyboard click duplicated note");
    await freshAudio(false);
    await key.focus();
    await page.keyboard.down("Enter");
    const previousKey = await key.elementHandle();
    // Model browsers that omit blur on target removal, even if this one emits it.
    await previousKey.evaluate((el) => el.addEventListener("blur", (e) => e.stopImmediatePropagation(), { capture: true, once: true }));
    await page.setViewportSize({ width: 390, height: 844 }); // rebuild removes the focused key while held
    await waitFor((el) => !el.isConnected, previousKey);
    await previousKey.dispose();
    await page.keyboard.up("Enter");
    const afterRebuild = await key.evaluate((el) => { el.click(); return el.getAttribute("aria-pressed"); });
    assert.equal(afterRebuild, "true", "layout rebuild left the virtual-click guard set");
    await waitFor(() => document.querySelector('[aria-label="F3"]').getAttribute("aria-pressed") === "false");
    await freshAudio(false);
    await page.setViewportSize({ width: 1200, height: 900 });
    return { click_only: true, timed_release: true, blur_release: true, physical_click_suppressed: true };
  });
  await check("pointer opens ENV and encoder redraws LCD", async () => {
    await page.getByRole("button", { name: "SEL", exact: true }).click();
    await waitFor(() => (__feluccaTest.leds[0] & (1 << 1)) !== 0);
    const before = await screen("before-env");
    await page.getByRole("button", { name: "ENV", exact: true }).click();
    await waitFor(() => (__feluccaTest.leds[0] & (1 << 2)) !== 0);
    const env = await screen("env");
    factoryEnvelope = env.graph_sha256;
    assert.notEqual(env.sha256, before.sha256, "ENV did not change the LCD");
    // Capture the count before input; LED/load messages are not LCD updates.
    const draws = await page.evaluate(() => __feluccaTest.draws);
    // A distinctive attack change must affect the graph, not just knob emphasis.
    for (let i = 0; i < 24; i++) await page.getByRole("slider", { name: "KNOB 1", exact: true }).press("ArrowUp");
    await waitFor((n) => __feluccaTest.draws > n, draws);
    const edited = await screen("env-edited");
    assert.notEqual(edited.sha256, env.sha256, "encoder did not change the LCD");
    return edited;
  });
  await check("GRAPH TURN: a turned knob's curve replaces the scope, then the scope returns", async () => {
    // #572: HOME's panel (tall bank: rows 98..198) in silence is the flat scope; KNOB 1 (ANALOG's CUT) shows the
    // filter curve while it turns and about 1.2 s after; then the same flat scope again.
    const panel = () => page.locator("#screen").evaluate((canvas) => {
      const context = new OffscreenCanvas(240, 240).getContext("2d", { willReadFrequently: true });
      context.drawImage(canvas, 0, 0);
      return Array.from(context.getImageData(0, 100, 240, 96).data).join(",");
    });
    await tap("HOME");
    await page.waitForTimeout(400);
    const rest = await panel();
    const draws = await page.evaluate(() => __feluccaTest.draws);
    for (let i = 0; i < 4; i++) await page.getByRole("slider", { name: "KNOB 1", exact: true }).press("ArrowUp");
    await waitFor((n) => __feluccaTest.draws > n, draws);
    await page.waitForTimeout(150);
    const turning = await panel();
    assert.notEqual(turning, rest, "turning KNOB 1 did not replace the scope with its curve");
    await screen("graph-turn");
    await page.waitForTimeout(2000);
    assert.equal(await panel(), rest, "the scope did not return after the curve's hold");
    await tap("ENV");                                 // (back on ENV, as the following checks expect)
    await waitFor(() => (__feluccaTest.leds[0] & (1 << 2)) !== 0);
    await page.waitForTimeout(200);
    return { curve_shown: true, scope_returned: true };
  });
  await check("portrait layout remains playable", async () => {
    await page.setViewportSize({ width: 390, height: 844 });
    await waitFor(() => document.getElementById("panel").viewBox.baseVal.width === 600);
    assert.equal(await page.getByRole("button", { name: "SEL", exact: true }).count(), 1);
    await check("portrait wrapper text contrast", wrapperContrast);
    const key = page.getByRole("button", { name: "F3", exact: true });
    await key.scrollIntoViewIfNeeded();
    const box = await key.boundingBox();
    assert(box && box.width > 0 && box.x >= 0 && box.x + box.width <= 391, "key outside portrait viewport");
    await page.mouse.move(box.x + box.width / 2, box.y + box.height / 2);
    await page.mouse.down();
    assert.equal(await key.getAttribute("aria-pressed"), "true");
    const observed = await freshAudio(true);
    await page.mouse.up();
    assert.equal(await key.getAttribute("aria-pressed"), "false");
    await freshAudio(false);
    await screen("portrait");
    return observed;
  });
  await check("panel save reaches browser storage and reload", async () => {
    await page.setViewportSize({ width: 1200, height: 900 });
    await waitFor(() => document.getElementById("panel").viewBox.baseVal.width === 1000);
    const expected = await screen("before-save");
    assert.notEqual(expected.graph_sha256, factoryEnvelope, "saved attack must differ from factory state");
    await tap("SAVE"); await tap("OCT+"); await tap("OCT+");
    const saved = await waitFor(() => {
      const value = localStorage.getItem("felucca-emu-flash");
      return value && Object.keys(JSON.parse(value)).length && value;
    });
    capturedAudio = await page.evaluate(() => ({ blocks: __feluccaTest.audio, rate: __feluccaTest.context.sampleRate }));
    messages.push(...await page.evaluate(() => __feluccaTest.errors));
    await page.reload();
    assert.equal(await page.evaluate(() => localStorage.getItem("felucca-emu-flash")), saved);
    await page.getByRole("button", { name: "Switch on", exact: true }).click();
    await page.locator("#start").waitFor({ state: "hidden" });
    await waitFor(() => __feluccaTest.frames > 5 && (__feluccaTest.leds[0] & (1 << 6)));
    assert.equal(await page.evaluate(() => __feluccaTest.restoredSectors), Object.keys(JSON.parse(saved)).length,
      "saved sectors were not delivered to the restarted worklet");
    await screen("reloaded");
    // Load USER slot 1 through the real panel and observe the applied parameters.
    await tap("SAVE");
    await page.getByRole("slider", { name: "KNOB 2", exact: true }).press("ArrowUp");
    await tap("OCT+"); await tap("HOME"); await tap("ENV");
    await waitFor(() => (__feluccaTest.leds[0] & (1 << 2)) !== 0);
    const restored = await screen("restored-env");
    assert.equal(restored.graph_sha256, expected.graph_sha256, "saved envelope was not restored and applied");
    return { sectors: Object.keys(JSON.parse(saved)).length, storage_sha256: hash(saved),
      restored_graph_sha256: restored.graph_sha256 };
  });
  // MACRO stays opt-in. Read availability and applied controls from the real
  // worklet's observed frame; every edit below still travels through DOM input.
  await waitFor(() => __feluccaTest.macro);
  const macroCount = await page.evaluate(() => __feluccaTest.macro.count);
  if (macroCount) {
    // The generic persistence check restarted the worklet; attach its new output
    // to the PCM observer before exercising MACRO audio.
    await page.evaluate(() => __feluccaTest.listen());
    const turn = async (name, delta) => {
      const slider = page.getByRole("slider", { name, exact: true });
      for (let i = 0; i < Math.abs(delta); i++) await slider.press(delta > 0 ? "ArrowUp" : "ArrowDown");
    };
    const state = () => page.evaluate(() => __feluccaTest.macro);
    const model = async (value) => waitFor((v) => {
      const m = __feluccaTest.macro;
      return m.engine === 14 && m.params[0] === v && m;
    }, value);
    await check("MACRO profile and real panel model controls", async () => {
      assert.equal(macroCount, 51);
      await tap("HOME");
      // Hold EDIT for the profile's engine map, then press its actual white key.
      const rank = (await state()).rank;
      const names = ["F3", "G3", "A3", "B3", "C4", "D4", "E4", "F4", "G4", "A4", "B4", "C5", "D5", "E5", "F5", "G5"];
      assert(rank < names.length, "MACRO missing from engine map");
      const edit = page.getByRole("button", { name: "EDIT", exact: true });
      await edit.focus(); await page.keyboard.down("Enter");
      await page.waitForTimeout(800);
      await page.getByRole("button", { name: names[rank], exact: true }).click();
      // Deliver keyup to EDIT even if the pointer interaction changed focus.
      await edit.focus(); await page.keyboard.up("Enter");
      await page.waitForTimeout(500);
      await model(0);
      const before = (await state()).params;
      await turn("KNOB 1", 3); await turn("KNOB 2", -2);
      await waitFor(({ a, b }) => __feluccaTest.macro.params[1] !== a && __feluccaTest.macro.params[2] !== b,
        { a: before[1], b: before[2] });
      await page.getByRole("button", { name: "F3", exact: true }).focus();
      await page.keyboard.down("z"); const audio = await freshAudio(true); await page.keyboard.up("z");
      await screen("macro-desktop-wave");
      // HOME KNOB 4 is MODEL; visit an added model and the highest stored ID.
      await turn("KNOB 4", 3); await model(3);
      await page.getByRole("button", { name: "F3", exact: true }).focus();
      await page.keyboard.down("z"); await freshAudio(true); await page.keyboard.up("z");
      await turn("KNOB 4", 44); const last = await model(47);
      await page.getByRole("button", { name: "F3", exact: true }).focus();
      await page.keyboard.down("z"); await freshAudio(true); await page.keyboard.up("z");
      await screen("macro-desktop-question");
      return { engine: last.engine, models: [0, 3, 47], params: last.params, audio };
    });
    await check("MACRO portrait controls and sound", async () => {
      await page.setViewportSize({ width: 390, height: 844 });
      await waitFor(() => document.getElementById("panel").viewBox.baseVal.width === 600);
      assert(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth), "portrait horizontal overflow");
      const before = (await state()).params[1];
      await turn("KNOB 1", 2);
      await waitFor((v) => __feluccaTest.macro.params[1] !== v, before);
      assert.equal((await state()).params[0], 47);
      await page.getByRole("button", { name: "F3", exact: true }).focus();
      await page.keyboard.down("z"); const audio = await freshAudio(true); await page.keyboard.up("z");
      await screen("macro-portrait-question");
      return audio;
    });
    await check("MACRO saved controls survive browser worklet restart", async () => {
      await page.setViewportSize({ width: 1200, height: 900 });
      await waitFor(() => document.getElementById("panel").viewBox.baseVal.width === 1000);
      const expected = (await state()).params;
      // Existing generic test occupied U01: explicitly confirm overwrite, then NAME.
      const previous = await page.evaluate(() => localStorage.getItem("felucca-emu-flash"));
      await tap("SAVE"); await tap("OCT+"); await tap("OCT+"); await tap("OCT+");
      const saved = await waitFor((before) => {
        const value = localStorage.getItem("felucca-emu-flash");
        return value && value !== before && value;
      }, previous);
      messages.push(...await page.evaluate(() => __feluccaTest.errors));
      capturedAudio = await page.evaluate(() => ({ blocks: __feluccaTest.audio, rate: __feluccaTest.context.sampleRate }));
      await page.reload();
      await page.getByRole("button", { name: "Switch on", exact: true }).click();
      await page.locator("#start").waitFor({ state: "hidden" });
      await waitFor(() => __feluccaTest.frames > 5 && (__feluccaTest.leds[0] & (1 << 6)));
      assert.equal(await page.evaluate(() => __feluccaTest.restoredSectors), Object.keys(JSON.parse(saved)).length);
      await page.evaluate(() => __feluccaTest.listen());
      await tap("SAVE"); await turn("KNOB 2", 1); await tap("OCT+"); await tap("HOME");
      const restored = await model(47);
      assert.deepEqual(restored.params, expected, "MACRO controls changed across saved-sector restart/load");
      await page.getByRole("button", { name: "F3", exact: true }).focus();
      await page.keyboard.down("z"); const audio = await freshAudio(true); await page.keyboard.up("z");
      await screen("macro-restored-question");
      capturedAudio = await page.evaluate(() => ({ blocks: __feluccaTest.audio, rate: __feluccaTest.context.sampleRate }));
      return { params: restored.params, sectors: Object.keys(JSON.parse(saved)).length, audio };
    });
  }
  await check("no browser or worklet errors", async () => {
    messages.push(...await page.evaluate(() => __feluccaTest.errors));
    assert.deepEqual(messages, []);
  });
  report.status = "pass";
} catch (e) {
  report.checks.push({ name: current, status: "fail", error: String(e.message || e).slice(0, 2000) });
  // Startup/input failures can precede the normal error check. Keep the worklet's
  // actual cause in the small report even when the visible failure is a timeout.
  const probeErrors = page ? await page.evaluate(() => globalThis.__feluccaTest?.errors || []).catch(() => []) : [];
  report.errors = [...new Set([...probeErrors, ...messages])].slice(0, 20).map((s) => String(s).slice(0, 1000));
} finally {
  if (page && (report.status === "fail" || keepMedia)) {
    try {
      await page.screenshot({ path: resolve(out, "page.png"), fullPage: true, timeout: 2000 });
      report.evidence.push("page.png");
      for (const [name, png] of screenshots) {
        await writeFile(resolve(out, `${name}.png`), png); report.evidence.push(`${name}.png`);
      }
      const audio = capturedAudio || await page.evaluate(() => ({ blocks: __feluccaTest.audio, rate: __feluccaTest.context?.sampleRate }));
      if (audio.blocks.length) {
        await writeFile(resolve(out, "audio.wav"), wav(audio.blocks, audio.rate)); report.evidence.push("audio.wav");
      }
    } catch (e) { report.errors.push(`evidence: ${String(e.message || e).slice(0, 500)}`); }
  }
  await browser?.close();
  if (server) await new Promise((res) => server.close(res));
  await writeFile(resolve(out, "summary.json"), JSON.stringify(report, null, 2) + "\n");
  const summary = `browser: ${report.status.toUpperCase()} (${report.checks.filter((c) => c.status === "pass").length} checks); ${relative(root, out)}/summary.json`;
  console.log(summary);
  if (report.status === "fail") console.error(`${current}: ${report.checks.at(-1).error}`);
  if (process.env.GITHUB_STEP_SUMMARY) await writeFile(process.env.GITHUB_STEP_SUMMARY, summary + "\n", { flag: "a" });
  process.exitCode = report.status === "pass" ? 0 : 1;
}
