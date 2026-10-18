/* SPDX-License-Identifier: GPL-3.0-only */
/* Real INFO rendering and metadata presence, including both canvas bands. */
#define IDENTITY_UI_RENDER 1
#define UI_RENDER_TEXT_MAX 64
#include "ui_render.c"

int main(int argc, char **argv)
{
    uint32_t p, st, large;
    if (argc != 2) return 2;
    scene_manifest = tmpfile();
    rep = tmpfile();
    if (!scene_manifest || !rep) return 2;
    for (p = 0; p < NPALETTES; p++)
        for (st = 0; st < 2; st++)
            for (large = 0; large < 2; large++) {
                char name[64];
                uint32_t k, identity = 0, commit = 0, usb_seen = 0, cpu_seen = 0;
                snprintf(name, sizeof name, "info_%u_%u", st, large);
                cur_name = name;
                setup(S_MENU_INFO);
                pal(p);
                ui_style = (uint8_t)st;
                style_apply();
                ui_prefs = large ? PREF_LARGE : 0;
                draw(S_MENU_INFO);
                for (k = 0; k < nscr; k++) {
                    uint32_t j;
                    identity |= !strcmp(scr[k].s, FELUCCA_SPLASH_ID);
                    for (j = k + 1; j < nscr; j++) {
                        char joined[128];
                        snprintf(joined, sizeof joined, "%s%s", scr[k].s, scr[j].s);
                        identity |= !strcmp(joined, FELUCCA_SPLASH_ID);
                    }
                    commit |= !strcmp(scr[k].s, FELUCCA_BUILD_ID);
                    usb_seen |= !strcmp(scr[k].s, "OFF");
                    cpu_seen |= !strcmp(scr[k].s, "33");
                    if (strcmp(FELUCCA_SPLASH_ID, FELUCCA_VERSION) && !strcmp(scr[k].s, FELUCCA_VERSION)) {
                        fprintf(stderr, "INFO shows source version instead of build identity\n");
                        return 1;
                    }
                }
                if (!identity || (FELUCCA_BUILD_PR[0] && !commit) || !usb_seen || !cpu_seen) {
                    fprintf(stderr, "INFO missing identity/commit/USB/CPU: %u/%u/%u/%u\n",
                            identity, commit, usb_seen, cpu_seen);
                    for (k = 0; k < nscr; k++) fprintf(stderr, "text: %s\n", scr[k].s);
                    return 1;
                }
                lint();
                mono_check();
                write_ppm(argv[1], UI_PALETTES[p].name, cur_name);
            }
    if (nfind || al_fail) {
        char line[512];
        rewind(rep);
        while (fgets(line, sizeof line, rep)) fputs(line, stderr);
    }
    printf("settings identity: %u palettes, FLAT/LINE, normal/LARGE: %u lint, %u alignment findings\n",
           (unsigned)NPALETTES, (unsigned)nfind, (unsigned)al_fail);
    return nfind || al_fail;
}
