/* SPDX-License-Identifier: GPL-3.0-only */
/* Real boot controller, UI and audio against the emulator HAL; fresh process per
 * scenario. Hardware scan debounce/calibration and USB remain device checks. */
#include "../web/emu/felucca_web.c"

#define CHECK(ok) do { if (!(ok)) { fprintf(stderr, "boot splash case %u line %d: %s\n", scenario, __LINE__, #ok); return 1; } } while (0)
static void step(uint32_t ms) { while (ms--) web_ms(); }
static void input(uint32_t id, uint32_t on)
{
    if (id < NB) web_buttons(on ? 1u << id : 0);
    else web_keys(on ? 1u << (id - NB) : 0);
}
static int run_case(uint32_t scenario)
{
    uint32_t id = scenario % 41u, late = scenario >= 41u;
    if (scenario == 83u) fm1_ms = ~0u - 200u; /* wrap-safe automatic deadline */
    if (scenario == 85u) web_ticks = ~0u - 200u * 1000u * FM1_TICKS_PER_US;
    web_nor_erase();
    web_boot();
    if (scenario == 84u) fm1_ms += 5000u;     /* target TIMER5's first tick can publish pre-scan uptime */
    if (scenario >= 82u) {
        step(BOOT_SPLASH_MS - 1u);
        CHECK(web_splash && kb_boot_hold);
        step(1);
        CHECK(!web_splash && !kb_boot_hold);
        return 0;
    }
    if (scenario == 0u) {                    /* MASTER and MIDI remain live under the splash */
        web_master(0);
        web_midi(0x90, 64, 100);
        step(100);
        CHECK(web_splash && voices_busy());
        CHECK(song.master_q12 < 256);
        web_midi(0x80, 64, 0);
        step(200);
    } else {
        step(late ? BOOT_SPLASH_MS - 10u : 1u);
    }
    input(id, 1);
    if (scenario == 1u) input(id, 0);          /* tap entirely inside the required settling interval */
    step(late || scenario == 0u ? 1u : BOOT_SCAN_MS);
    CHECK(!web_splash);
    step(800);                               /* longer than HOME's hold: no menu/layer/note/PLAY */
    CHECK(!song.playing && !song.rec && !ui.menu && !ui.layer && !ui.ly && !ui.lock);
    CHECK(ui.home && song.sel == 0 && song.octave == 0);
    CHECK(!voices_busy());
    input(id, 0);
    step(20);
    CHECK(!kb_boot_hold);
    CHECK(!song.playing && !ui.menu && !ui.layer && !ui.ly);
    web_buttons(1u << B_PLAY);
    step(30);
    CHECK(song.playing);
    web_buttons(0);
    step(20);
    web_buttons(1u << B_PLAY);
    step(30);
    CHECK(!song.playing);
    web_buttons(0);
    step(20);
    web_keys(1u << 7);
    step(30);
    CHECK(voices_busy());
    web_keys(0);
    step(1500);
    CHECK(!voices_busy());
    return 0;
}
int main(void)
{
    uint32_t s;
    for (s = 0; s < 86u; s++) {
        int status;
        pid_t pid = fork();
        if (pid == 0) _exit(run_case(s));
        if (pid < 0 || waitpid(pid, &status, 0) < 0 || !WIFEXITED(status) || WEXITSTATUS(status))
            return 1;
    }
    puts("boot splash: 86 cases, all 41 buttons/keys, early/late/held/released, MIDI/MASTER, clock jump/wrap: ok");
    return 0;
}
