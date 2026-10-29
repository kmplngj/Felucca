/* SPDX-License-Identifier: GPL-3.0-only */
/* A real stored LOFI sound and its favourites pass between separately compiled profiles. */
#define FELUCCA_ENGID_HELPERS_ONLY 1
#include "engid_test.c"

static int roundtrip(const char *input, const char *output)
{
    project_t p, q;
    project_store_t stored, after;
    up_rec_t preset;
    persist_rec_t prefs;
    FILE *f;
    uint32_t i;
    reset();
    panel = PANEL_DEFAULT;
    if (input) {
        if (!(f = fopen(input, "rb"))) return 1;
        if (fread(&stored, sizeof stored, 1, f) != 1 || fread(&preset, sizeof preset, 1, f) != 1 ||
            fread(&prefs, sizeof prefs, 1, f) != 1 || fgetc(f) != EOF) return 2;
        fclose(f);
    } else {
        host_preset(&trk[1], 3, 2);
        project_capture(&p);
        /* Normalize the existing historical-project defaults once before crossing profiles. */
        if (!proj_encode(&stored, &p) || !proj_import(&q, &stored, sizeof stored) || project_restore_runtime(&q)) return 3;
        project_capture(&p);
        if (!proj_encode(&stored, &p)) return 3;
        song.sel = 1;
        up_store(5, "PROFILE");
        preset = *up_rec(5);
        favorite_set(3, 2, 1);
        settings_export_rec(&prefs);
    }
    if (!proj_import(&q, &stored, sizeof stored) || project_restore_runtime(&q) ||
        trk[1].eng_req != 3 || trk[1].preset != 2) return 4;
    project_capture(&p);
    if (!proj_encode(&after, &p) || memcmp(&stored, &after, sizeof stored)) return 5;
    *up_rec(5) = preset;
    song.sel = 1;
    if (up_load(5) || TSEL->eng_req != 3 || memcmp(&preset, up_rec(5), sizeof preset)) return 6;
    if (bk_put((const uint8_t *)&prefs, persist_len(&prefs))) return 7;
    if (!favorite_has(3, 2)) return 8;
#if FELUCCA_PROFILE_ENGINE_3
    if (!eng_ok(3) || eng_of(3) == &ENG_NONE || play_peak() <= 0) return 9;
#else
    if (eng_ok(3) || eng_of(3) != &ENG_NONE || play_peak() != 0) return 9;
    set_engine_of(TSEL, 3); /* Activation refusal keeps the original unavailable stored sound. */
    if (TSEL->eng_req != 3) return 10;
#endif
    if (!(f = fopen(output, "wb"))) return 11;
    if (fwrite(&after, sizeof after, 1, f) != 1 || fwrite(&preset, sizeof preset, 1, f) != 1 ||
        fwrite(&prefs, sizeof prefs, 1, f) != 1) return 12;
    fclose(f);
    return 0;
}
int main(int argc, char **argv)
{
    int rc;
    if (argc != 3) return 1;
    rc = roundtrip(strcmp(argv[1], "create") ? argv[1] : 0, argv[2]);
    printf("stored sound %s: %s (%d)\n", FELUCCA_PROFILE_NAME, rc ? "FAIL" : "ok", rc);
    return rc;
}
