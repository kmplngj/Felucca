/* SPDX-License-Identifier: GPL-3.0-only */
/* Independent interval fixtures: stored scale IDs, not production mask data. */
#ifndef SCALE_EXPECTED_H
#define SCALE_EXPECTED_H
static const struct { uint8_t count, notes[12]; } SCALE_EXPECTED[] = {
    {12, {0, 1, 2, 3, 4, 5, 6, 7, 8, 9, 10, 11}},
    {7, {0, 2, 4, 5, 7, 9, 11}}, {7, {0, 2, 3, 5, 7, 8, 10}},
    {7, {0, 2, 3, 5, 7, 9, 10}}, {7, {0, 2, 4, 5, 7, 9, 10}},
    {5, {0, 2, 4, 7, 9}}, {5, {0, 3, 5, 7, 10}},
    {7, {0, 2, 3, 5, 7, 8, 11}}, {7, {0, 1, 3, 5, 7, 8, 10}},
    {7, {0, 2, 4, 6, 7, 9, 11}}, {7, {0, 1, 3, 5, 6, 8, 10}},
    {7, {0, 2, 3, 5, 7, 9, 11}}, {6, {0, 3, 5, 6, 7, 10}},
    {6, {0, 2, 4, 6, 8, 10}}, {8, {0, 1, 3, 4, 6, 7, 9, 10}},
    {8, {0, 2, 3, 5, 6, 8, 9, 11}},
    {7, {0, 1, 4, 5, 7, 8, 10}}, {7, {0, 2, 3, 6, 7, 8, 11}},
    {7, {0, 1, 4, 5, 7, 8, 11}},
};
static const char *const SCALE_NAMES_EXPECTED[] = {
    "CHR", "MAJ", "MIN", "DOR", "MIX", "PEN", "MPEN", "HARM", "PHRY", "LYD", "LOC", "MEL",
    "BLUES", "WHOLE", "DIMHW", "DIMWH", "PHDOM", "HUNG", "DHARM"
};
static int expected_snap(uint32_t scale, int root, int note)
{
    for (;;) {
        int pc = (note - root) % 12;
        if (pc < 0) pc += 12;
        for (uint32_t i = 0; i < SCALE_EXPECTED[scale].count; i++)
            if (SCALE_EXPECTED[scale].notes[i] == pc) return note;
        note--;
    }
}
#endif
