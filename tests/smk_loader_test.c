/* SPDX-License-Identifier: GPL-3.0-only */
/* Reuse the native SysEx host, package reader and fault controls. All loader
 * decisions below execute the production ldr_core.c on synthetic packages. */
#define SMK_LOADER_TEST 1
#define main native_ota_test_main
#include "ota_test.c"
#undef main
#define FL_RANGE_OK(off, n) FL_LDR_RANGE_OK(off, n)
#include "../firmware/hal/fm1_flash_map.h"
static uint32_t clears, writes, unsafe, state, progress;
static int fail_page, fail_erase, fail_read;
static int ldr_fread(uint32_t off, void *p, uint32_t n)
{
    if (fail_read) return -1;
    memcpy(p, nor + off, n); return 0;
}
static int ldr_erase(uint32_t off)
{
    if (!FL_GUARD(off, 4096) || (off & 4095)) { unsafe++; return -1; }
    if (fail_erase) return -1;
    erases++; memset(nor + off, 255, 4096); return 0;
}
static int ldr_prog(uint32_t off, const void *src, uint32_t n)
{
    const uint8_t *p = src; uint32_t i;
    if (!FL_GUARD(off, n) || off >= 0x9D000u) { unsafe++; return -1; }
    if (fail_page) return -1;
    for (i = 0; i < n; i++) nor[off + i] &= p[i];
    writes++; return 0;
}
static void ldr_record_clear(void) { clears++; }
static void ldr_status(uint32_t s, int32_t c) { state = s; (void)c; }
static void ldr_progress(uint32_t d, uint32_t t) { if (d > t) unsafe++; progress = d; }
#include "../firmware/loader/ldr_core.c"
static uint8_t before[sizeof nor];
static void setup(void)
{
    reset_dev(); memset(nor + 0x9D000, 0x53, 0x63000);
    /* A record-shaped sample/metadata tail must never be classified/erased. */
    for (uint32_t a = 0x9D000; a < 0x100000; a += 4096) {
        uint8_t *r = nor + a + 0xF00;
        ota_wr16(r + 6, 0x5441); ota_wr16(r, ota_crc16(r + 2, 78, 0));
    }
    memcpy(before, nor, sizeof nor);
    clears = writes = unsafe = progress = 0;
    fail_page = fail_erase = fail_read = 0;
}
int main(int argc, char **argv)
{
    int bad = 0, rc; uint32_t off, len;
    if ((argc != 2 && argc != 3) || load(argv[1])) return 2;
    off = entry_of(0, &len); memcpy(dev_head, logical + off, sizeof dev_head);
    setup();
    ota_reply_identity();
    bad += check("loader identity matches selected model", ident_replies == 1 &&
                 !memcmp(ota_msg + 6, FELUCCA_ID, sizeof FELUCCA_ID - 1));
    rc = ldr_session();
    bad += check("SMK loader installs exact app area", rc == 0 && state == LDR_SUCCESS && clears == 1 &&
                 !memcmp(nor + 0x4000, logical + off + 0x4000, 0x99000) && !unsafe && progress == 0x99000);
    bad += check("head, metadata, samples and protected tail unchanged", !memcmp(nor, before, 0x4000) &&
                 !memcmp(nor + 0x9D000, before + 0x9D000, 0x1E000) &&
                 !memcmp(nor + 0xC0000, before + 0xC0000, 0x40000));
    setup(); set_fl_size(logical, 0x93000); rc = ldr_session();
    bad += check("FM1 layout refused before any erase", rc == -14 && !erases && !writes && !clears);
    set_fl_size(logical, len);
    for (int fault = 0; fault < 3; fault++) {
        setup(); fail_read = fault == 0; fail_erase = fault == 1; fail_page = fault == 2;
        rc = ldr_session();
        bad += check("flash failure preserves boot head and user tail, no commit", rc < 0 && !clears &&
                     !memcmp(nor, before, 0x4000) && !memcmp(nor + 0x9D000, before + 0x9D000, 0x63000));
        fail_read = fail_erase = fail_page = 0;
        bad += check("retry completes after flash failure", ldr_session() == 0 && clears == 1 && !unsafe);
    }
    if (argc == 3) {
        if (load(argv[2])) return 2;
        reset_dev(); rc = ota_session();
        bad += check("official FM1 package rejected before first SMK erase", rc == -5 && !erases && !committed);
    }
    puts(bad ? "SMK LOADER FAILED" : "SMK loader passed");
    free(logical); return bad ? 1 : 0;
}
