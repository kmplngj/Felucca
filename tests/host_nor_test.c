/* SPDX-License-Identifier: GPL-3.0-only */
/* Self-test of the shared host NOR model (tests/host_nor.h): aligned erase and program, the 0 -> 1 counter, and the
 * aborts on an unaligned / out-of-range erase and a program that leaves the array or crosses a page. The aborting
 * cases run in a child process (this binary again with a case name). */
#include "host_nor.h"

#define CHECK(x) do { if (!(x)) { fprintf(stderr, "host_nor_test line %d: %s\n", __LINE__, #x); return 1; } } while (0)

static int functional(void)
{
    uint8_t a[4] = {0x0F, 0xF0, 0xFF, 0x00}, got[4];
    memset(nor, 0xFF, sizeof nor);
    CHECK(st_erase(0x2000) == 0 && erases == 1 && nor[0x2000] == 0xFF && nor[0x2FFF] == 0xFF);
    CHECK(st_erase(sizeof nor - 4096u) == 0 && erases == 2);
    CHECK(st_prog(0x2000, a, 4) == 0 && progs == 4 && host_nor_set_bits == 0);
    CHECK(st_read(0x2000, got, 4) == 0 && !memcmp(got, a, 4));
    CHECK(st_prog(sizeof nor - 4u, a, 4) == 0 && st_prog(0x2000, a, 0) == 0 && host_nor_set_bits == 0);
    CHECK(st_prog(0x2000, a, 4) == 0 && host_nor_set_bits == 0);       /* same value again: clears nothing, sets nothing */
    a[0] = 0xFF;                                                       /* 0x0F -> 0xFF: bits 4..7 would be set */
    CHECK(st_prog(0x2000, a, 4) == 0 && host_nor_set_bits == 1);
    CHECK(nor[0x2000] == 0x0F && nor[0x2001] == 0xF0 && nor[0x2003] == 0x00);   /* AND semantics kept, no abort */
    a[1] = 0xFF;                                                       /* two bytes in one call: counted once */
    CHECK(st_prog(0x2000, a, 4) == 0 && host_nor_set_bits == 2);
    a[0] = a[1] = 0x00;
    CHECK(st_prog(0x2000, a, 4) == 0 && host_nor_set_bits == 2 && nor[0x2000] == 0 && nor[0x2001] == 0);
    puts("host NOR aligned erase, program, AND and 0 -> 1 counter passed");
    return 0;
}

static int abort_case(const char *name)
{
    uint8_t b[8] = {0};
    memset(nor, 0xFF, sizeof nor);
    if (!strcmp(name, "erase-unaligned")) st_erase(0x1001);
    else if (!strcmp(name, "erase-end")) st_erase(sizeof nor);
    else if (!strcmp(name, "erase-last-partial")) st_erase(sizeof nor - 2048u);
    else if (!strcmp(name, "erase-wrap")) st_erase(0xFFFFF000u);
    else if (!strcmp(name, "prog-end")) st_prog(sizeof nor - 4u, b, 8);
    else if (!strcmp(name, "prog-past")) st_prog(sizeof nor, b, 1);
    else if (!strcmp(name, "prog-huge")) st_prog(0x10, b, UINT32_MAX);
    else if (!strcmp(name, "prog-page")) st_prog(0xFE, b, 4);
    else return 2;
    fputs("the bad access was accepted\n", stderr);
    return 0;
}

static int child(const char *argv0, const char *name, const char *expect)
{
    char cmd[512], out[256] = "";
    FILE *p;
    int st;
    snprintf(cmd, sizeof cmd, "'%s' %s 2>&1", argv0, name);
    p = popen(cmd, "r");
    CHECK(p);
    if (!fgets(out, sizeof out, p)) out[0] = 0;
    st = pclose(p);
    if (!(st != -1 && (st & 0x7F) == 0 && ((st >> 8) & 0xFF) == 1 && strstr(out, expect))) {
        fprintf(stderr, "host_nor_test: %s: status %#x, output \"%s\"\n", name, st, out);
        return 1;
    }
    return 0;
}

int main(int argc, char **argv)
{
    int bad = 0;
    if (argc > 1) return abort_case(argv[1]);
    bad += functional();
    bad += child(argv[0], "erase-unaligned", "erase outside the array or unaligned at 0x1001");
    bad += child(argv[0], "erase-end", "erase outside the array or unaligned");
    bad += child(argv[0], "erase-last-partial", "erase outside the array or unaligned");
    bad += child(argv[0], "erase-wrap", "erase outside the array or unaligned");
    bad += child(argv[0], "prog-end", "program outside the array");
    bad += child(argv[0], "prog-past", "program outside the array");
    bad += child(argv[0], "prog-huge", "program outside the array");
    bad += child(argv[0], "prog-page", "page wrap at 0xfe");
    if (!bad) puts("host NOR aborts: unaligned / out-of-range erase, program out of the array, page crossing passed");
    return bad ? 1 : 0;
}
