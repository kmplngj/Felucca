/* SPDX-License-Identifier: GPL-3.0-only */
/* Native capture adapter: include the browser's real DSP/UI/flash integration,
 * rather than maintain another simulated firmware or main-loop schedule. */
#include "../web/emu/felucca_web.c"
typedef char replay_timing_contract[(FS == 44100 && CTL == 32 && HALF_FRAMES == 128) ? 1 : -1];

EXPORT void replay_init(uint32_t seed, uint32_t master, uint32_t click, uint32_t usb_fixed)
{
    rng_state = seed;
    web_nor_erase();
    web_master(master);
    web_boot();
    /* Initial configuration, through the same application path as MENU. */
    menu_put(MI_CLICK, click);
    menu_put(MI_USB, usb_fixed);
}

/* The emulator's float ring represents exact 24-bit DAC words / 2^23.
 * Recover those words and write signed little-endian PCM24, with no dither. */
EXPORT void replay_pcm(uint32_t n, uint8_t *dst)
{
    uint32_t i, ch;
    web_render(n);
    for (i = 0; i < n; i++)
        for (ch = 0; ch < 2u; ch++) {
            uint32_t v = (uint32_t)(int32_t)((ch ? out_r[i] : out_l[i]) * 8388608.0f);
            *dst++ = (uint8_t)v;
            *dst++ = (uint8_t)(v >> 8);
            *dst++ = (uint8_t)(v >> 16);
        }
}

/* Panel byte order -> RGB565 -> RGB888, matching tests/ui_render.c's PPMs.
 * Reading the screen neither draws nor advances the device. */
EXPORT void replay_rgb(uint8_t *dst)
{
    uint32_t i;
    for (i = 0; i < 240u * 240u; i++) {
        uint16_t raw = web_fb[i];
        uint32_t c = (uint16_t)((raw >> 8) | (raw << 8));
        *dst++ = (uint8_t)(((c >> 11) & 31u) * 255u / 31u);
        *dst++ = (uint8_t)(((c >> 5) & 63u) * 255u / 63u);
        *dst++ = (uint8_t)((c & 31u) * 255u / 31u);
    }
}

/* Observations are deliberately read-only. The audio producer can lead the
 * consumer; report both positions instead of promising sample-accurate input. */
EXPORT void replay_observe(uint32_t *v)
{
    uint32_t p, i, gates = 0;
    for (p = 0; p < NPART; p++)
        for (i = 0; i < NVOICE; i++)
            gates += trk[p].v[i].active && trk[p].v[i].gate;
    v[0] = fm1_ms;
    v[1] = ring_w;
    v[2] = ring_r;
    v[3] = fm1_in.notes;
    v[4] = web_btn_labels;
    v[5] = gates;
    v[6] = voices_busy();
    v[7] = song.sel;
    v[8] = TSEL->eng_req;
    v[9] = (uint32_t)(int32_t)song.octave;
    v[10] = ui.page;
    v[11] = web_draws;
    v[12] = song.playing;
    v[13] = menu_get(MI_CLICK);
    v[14] = menu_get(MI_USB);
    v[15] = ui.home;
    v[16] = cur_page()->graph;
    v[17] = TSEL->engine;
    v[18] = 0;
    for (i = 0; i < UP_SLOTS; i++) v[18] += up_used(i) != 0;
}

EXPORT void replay_features(uint32_t *v)
{
    v[0] = FELUCCA_FM4;
    v[1] = FELUCCA_SLICE;
    v[2] = FELUCCA_ICONS;
    v[3] = FELUCCA_CDC;
    v[4] = FELUCCA_FLASH;
    v[5] = FELUCCA_OTA;
    v[6] = FELUCCA_UAC;
    v[7] = FELUCCA_UART;
}
