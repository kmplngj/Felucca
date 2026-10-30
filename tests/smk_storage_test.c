/* SPDX-License-Identifier: GPL-3.0-only */
/* Real storage and hardware policy against a fault-injected NOR. */
#include <stdint.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#define BOARD_SMK37 1
#define __attribute__(x)
#include "../firmware/hal/fm1_flash_map.h"
#define FL_FAR(fn) fn
static uint8_t nor[0x100000];
static uint16_t abuf[8];
static int read_fail = -1, prog_cut = -1, erase_cut = -1;
static int protected_write, reads, erases, programs, erase_fail = -1, erase_noop, prog_noop;
static const uint8_t *owner_ram_window;
static int owner_xip_rejected;
static uint32_t irq_save(void) { return 0; }
static void irq_restore(uint32_t f) { (void)f; }
static int fl_read_ram(uint32_t off, uint8_t *dst, uint32_t n)
{
    if (reads++ == read_fail) return -1;
    if (FL_IN(off, n, FL_DATA_LO, FL_DATA_HI)) owner_ram_window = dst;
    memcpy(dst, nor + off, n); return 0;
}
static int fl_erase4k_ram(uint32_t off, uint32_t *took)
{
    int n = erase_cut < 0 ? 4096 : erase_cut;
    (void)took; if (erases++ == erase_fail) return -1;
    if (!FL_GUARD(off, 4096)) { protected_write++; return -1; }
    if (!erase_noop) memset(nor + off, 255, (unsigned)n);
    return erase_cut < 0 ? 0 : -1;
}
static int fl_write(uint32_t off, const void *src, uint32_t n)
{
    const uint8_t *p = src; uint32_t i;
    programs++;
    if (!FL_GUARD(off, n)) { protected_write++; return -1; }
    /* The last metadata read identifies the writable RAM staging buffer.
     * Simulate XIP being unavailable during the owner-tag program: a literal
     * or any other source outside that buffer cannot be consumed. */
    if (off == 0xAF000u && p != owner_ram_window) {
        owner_xip_rejected++;
        return -1;
    }
    for (i = 0; i < n; i++) {
        if ((int)i == prog_cut) return -1;
        if (!prog_noop) nor[off + i] &= p[i];
    }
    return 0;
}
#include "../firmware/src/storage_hw.c"
#include "../firmware/src/storage.c"
#define CHECK(x) do { if (!(x)) { fprintf(stderr, "line %d: %s\n", __LINE__, #x); exit(1); } } while (0)
static void reset(void)
{
    memset(nor, 255, sizeof nor);
    read_fail = prog_cut = erase_cut = erase_fail = -1;
    erase_noop = prog_noop = 0;
    reads = programs = erases = protected_write = 0;
    owner_ram_window = NULL; owner_xip_rejected = 0;
    st_owner_ready = 0; flash_ok = 1;
}
int main(void)
{
    int k, count; uint8_t b = 0;
    reset(); CHECK(st_owner_check() == 0 && ST_AVAILABLE);
    CHECK(erases == 0 && programs == 1);
    CHECK(owner_ram_window != NULL && owner_xip_rejected == 0);
    count = reads;
    CHECK(st_save(OBJ_SETTINGS, &b, 1) == 0);
    st_owner_ready = 0; flash_ok = 1;
    CHECK(st_read(ST_OWNER_OFF, &b, 1) < 0);
    CHECK(st_erase(ST_SMK_BASE) < 0 && st_prog(ST_SMK_BASE, &b, 1) < 0);
    CHECK(st_load(OBJ_SETTINGS, &b, 1) < 0);
    CHECK(st_owner_check() == 0 && st_load(OBJ_SETTINGS, &b, 1) == 1);
    for (k = 0; k < count; k++) {
        reset(); read_fail = k;
        CHECK(st_owner_check() < 0 && !st_owner_ready && erases == 0);
        CHECK(st_erase(ST_SMK_BASE) < 0);
    }
    for (k = 0; k < 16; k++) {
        reset(); prog_cut = k;
        CHECK(st_owner_check() < 0 && !st_owner_ready && erases == 0);
        if (k) { prog_cut = -1; CHECK(st_owner_check() < 0 && !st_owner_ready); }
    }
    /* A foreign byte in staging must also block automatic ownership, even
     * when every metadata byte is blank. Neither check nor cleanup may erase. */
    for (k = 0; k < 0x23000; k += 4096) {
        reset(); nor[ST_SMK_BASE + k + 4095] = 0;
        CHECK(st_owner_check() < 0 && !st_owner_ready && !programs && !erases);
    }
    reset(); memcpy(nor + ST_OWNER_OFF, "SMK37DATAFELUCCA", 16);
    CHECK(st_owner_check() < 0 && !programs && !erases);
    reset(); CHECK(st_owner_check() == 0);
    memset(nor + FL_STOCKTAG_LO, 0, 4096);
    reads = 0; read_fail = 0;
    CHECK(st_erase(FL_SMP_LO) < 0 && !erases);
    read_fail = -1;
    CHECK(st_prog(FL_SMP_LO, &b, 1) < 0);
    for (k = 0; k <= 4096; k++) {
        memset(nor + FL_STOCKTAG_LO, 0, 4096);
        nor[FL_SMP_LO] = 0; erase_cut = k;
        CHECK(st_erase(FL_SMP_LO) < 0 && nor[FL_SMP_LO] == 0);
    }
    erase_cut = -1;
    memset(nor + FL_STOCKTAG_LO, 0, 4096);
    CHECK(st_erase(FL_SMP_LO) == 0 && nor[FL_SMP_LO] == 255);
    CHECK(st_prog(FL_SMP_LO, &b, 1) == 0);
    CHECK(st_erase(0xEA000) < 0 && st_erase(0xC0000) < 0);
    reset(); memset(nor + FL_DATA_LO, 0, FL_OTA_HI - FL_DATA_LO);
    memset(nor + FL_SMP_LO, 0x63, FL_SMP_HI - FL_SMP_LO);
    CHECK(st_owner_initialize() == 0 && st_owner_ready);
    CHECK(erases == 35 && nor[FL_OTA_LO] == 0xFFu && nor[FL_OTA_HI - 1u] == 0xFFu);
    CHECK(nor[FL_SMP_LO] == 0x63 && nor[FL_SMP_HI - 1] == 0x63);
    count = reads;
    for (k = 0; k < count; k++) {
        reset(); memset(nor + FL_DATA_LO, 0, FL_OTA_HI - FL_DATA_LO); read_fail = k;
        CHECK(st_owner_initialize() < 0 && !st_owner_ready);
    }
    for (k = 0; k < 35; k++) {
        reset(); memset(nor + FL_DATA_LO, 0, FL_OTA_HI - FL_DATA_LO); erase_fail = k;
        CHECK(st_owner_initialize() < 0 && !st_owner_ready);
        read_fail = -1; CHECK(st_owner_check() < 0 && !st_owner_ready);
    }
    for (k = 0; k < 16; k++) {
        reset(); memset(nor + FL_DATA_LO, 0, FL_OTA_HI - FL_DATA_LO); prog_cut = k;
        CHECK(st_owner_initialize() < 0 && !st_owner_ready);
    }
    reset(); memset(nor + FL_DATA_LO, 0, FL_OTA_HI - FL_DATA_LO); erase_noop = 1;
    CHECK(st_owner_initialize() < 0 && !st_owner_ready && erases == 1);
    reset(); prog_noop = 1; CHECK(st_owner_check() < 0 && !st_owner_ready);
    /* All protected bytes remain sentinels through explicit initialization. */
    reset(); memset(nor + 0xC0000, 0x27, 0x2000); memset(nor + 0xF4000, 0x38, 0xA000);
    memset(nor + 0xFF000, 0x49, 0x1000);
    CHECK(st_owner_initialize() == 0);
    for (k = 0; k < 0x2000; k++) CHECK(nor[0xC0000 + k] == 0x27);
    for (k = 0; k < 0xA000; k++) CHECK(nor[0xF4000 + k] == 0x38);
    for (k = 0; k < 0x1000; k++) CHECK(nor[0xFF000 + k] == 0x49);
    CHECK(!protected_write);
    /* Negative control: the simulated flash-busy hook rejects an XIP tag. */
    {
        static const uint8_t flash_tag[16] = "FELUCCA-SMK-V1";
        reset();
        CHECK(st_owner_prog(ST_OWNER_OFF, flash_tag, sizeof flash_tag) < 0);
        CHECK(owner_xip_rejected == 1 && nor[ST_OWNER_OFF] == 0xFFu);
    }
    puts("SMK ownership, interrupted initialization, marker and flash policy passed");
    return 0;
}
