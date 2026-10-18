/* SPDX-License-Identifier: GPL-3.0-only */
/* Exercise the real splash and ABOUT drawing/lint with boundary metadata. */
#define IDENTITY_UI_RENDER 1
#include "ui_render.c"

int main(int argc, char **argv)
{
    uint32_t p, s, st;
    const uint32_t scenes[] = {S_SPLASH, S_ABOUT};
    if (argc != 2) return 2;
    scene_manifest = tmpfile();
    rep = tmpfile();
    if (!scene_manifest || !rep) return 2;
    for (st = 0; st < 2u; st++)
    for (p = 0; p < NPALETTES; p++)
        for (s = 0; s < NELEM(scenes); s++) {
            char palette[48];
            cur_name = S_NAME[scenes[s]];
            setup((int)scenes[s]);
            pal(p);
            ui_style = (uint8_t)st;
            style_apply();
            draw((int)scenes[s]);
            {
                uint32_t k, id_seen = 0, pr_seen = 0;
                for (k = 0; k < nscr; k++) {
                    id_seen |= !strcmp(scr[k].s, FELUCCA_BUILD_ID);
                    pr_seen |= !strcmp(scr[k].s, FELUCCA_BUILD_PR);
                }
                if (scenes[s] == S_ABOUT && (!id_seen || (FELUCCA_BUILD_PR[0] && !pr_seen))) {
                    fprintf(stderr, "identity UI: missing build/PR in %s\n", cur_name);
                    return 1;
                }
            }
            lint();
            mono_check();
            snprintf(palette, sizeof palette, "%s%s", st ? "LINE_" : "", UI_PALETTES[p].name);
            write_ppm(argv[1], palette, cur_name);
        }
    if (nfind || al_fail) {
        char line[512];
        rewind(rep);
        while (fgets(line, sizeof line, rep)) fputs(line, stderr);
    }
    printf("identity UI: %u palettes, splash + ABOUT, %u lint findings, %u alignment findings\n",
           (unsigned)NPALETTES, (unsigned)nfind, (unsigned)al_fail);
    return nfind || al_fail;
}
