#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-3.0-only
"""Compile the HAL's verbatim completion/wait functions with a register oracle.

Only the register lvalue is substituted; no target addresses are accessed. This
checks acknowledgment/poll bounds, not a physical SPI abort or bus barrier.
"""
import os
from pathlib import Path
import shlex
import subprocess
import tempfile

root = Path(__file__).resolve().parents[1]
header = (root / "firmware/hal/fm1_lcd_hw.h").read_text()
functions = header[header.index("FM1_INLINE int fm1_lcd_complete"):
                   header.index("FM1_INLINE void fm1_lcd_deselect")]
source = r"""
#include <stdint.h>
#include <assert.h>
#include <stdio.h>
#define FM1_INLINE static inline
static uint32_t polls, done_after, fm1_lcd_timeouts;
static volatile uint32_t spi_con;
static volatile uint32_t *reg(void) {
    polls++;
    if (done_after && polls == done_after) spi_con |= 0x8000u;
    return &spi_con;
}
#define FM1_LCD_SPI_CON (*reg())
""" + functions + r"""
int main(void) {
    spi_con = 0x21u;
    assert(!fm1_lcd_complete() && polls == 1u && spi_con == 0x21u);
    polls = 0;
    assert(!fm1_lcd_wait());
    assert(polls == 4000000u && fm1_lcd_timeouts == 1u && spi_con == 0x21u);
    polls = 0; done_after = 17u;
    assert(fm1_lcd_wait());
    assert(polls == 18u && (spi_con & 0x4000u) && fm1_lcd_timeouts == 1u);
    polls = 0; done_after = 0;
    assert(fm1_lcd_complete() && polls == 2u && fm1_lcd_timeouts == 1u);
    puts("PASS LCD HAL: bounded polls, explicit timeout, no timeout acknowledgment, delayed and late completion");
    return 0;
}
"""
with tempfile.TemporaryDirectory(prefix="felucca-lcd-wait-") as directory:
    src = Path(directory) / "wait.c"
    binary = Path(directory) / "wait"
    src.write_text(source)
    subprocess.run(shlex.split(os.environ.get("CC", "cc")) +
                   ["-std=c11", "-O1", "-Wall", "-Wextra", "-Werror", str(src), "-o", str(binary)],
                   check=True, timeout=30)
    subprocess.run([str(binary)], check=True, timeout=10)

# The same oracle seam checks diagnostic-only first-cause publication and reset
# deadlines from their actual source bodies; no ports or firmware reset executes.
def probe_function(text, name):
    import re
    match = re.search(r"^static (?:inline )?(?:void|int|uint32_t) " + name + r"\([^;]*?\)\s*(?:/\*.*?\*/\s*)?\{", text, re.M | re.S)
    if not match:
        raise AssertionError(name)
    pos = text.index("{", match.start()) + 1
    depth = 1
    while depth:
        depth += (text[pos] == "{") - (text[pos] == "}")
        pos += 1
    return text[match.start():pos]

lp_source = (root / "firmware/src/lcd_inflight.c").read_text()
main_source = (root / "firmware/src/main.c").read_text()
snapshot_source = probe_function(header.replace("FM1_INLINE ", "static inline "), "fm1_lcd_snapshot")
probe = r"""
#include <stdint.h>
#include <string.h>
#include <assert.h>
#define FELUCCA_LCD_INFLIGHT 1
#include "lcd_inflight.h"
#define FM1_LCD_READ_MASK 5u
static uint32_t fm1_ms, ticks, raw[4] = {0x8021, 0, 59520, 0};
static uint32_t issued_baud=4, baud_writes=2, con_reads, cnt_reads;
#define FM1_LCD_SPI_CON (con_reads++, raw[0])
#define FM1_LCD_SPI_CNT (cnt_reads++, raw[2])
#define FM1_LCD_SPI_ADR FORBIDDEN_WRITE_ONLY_LOAD
#define FM1_LCD_SPI_BAUD FORBIDDEN_WRITE_ONLY_LOAD
static uint8_t lcd_busy=1, lcd_fault, lcd_initialized=1;
static uint32_t fm1_ticks(void) { return ++ticks; }
static void fm1_lcd_baud_state(uint32_t out[2]) { out[0]=issued_baud; out[1]=baud_writes; }
""" + snapshot_source + r"""
""" + "\n".join(probe_function(lp_source, name) for name in
                    ("lp_reset_latch", "lp_request_reset", "lp_baud_allowed", "lp_record")) + r"""
static uint32_t order, resets, bootguard;
static void fm1_audio_stop(void) { assert(order++ == 0); }
static void usb_detach(void) { assert(order++ == 1); }
static void fm1_delay_ms(uint32_t n) { assert(n == 30 && order++ == 2); }
static void boot_policy_intentional(uint32_t *p) { assert(order++ == 3); *p=0; }
static void fm1_reboot(void) { assert(order++ == 4); resets++; }
""" + probe_function(main_source, "lp_reset_if_requested") + r"""
static void setup(uint32_t now) {
    memset(&lp,0,sizeof lp); lp.active=lp.hold=1; lp.arm_ms=now; fm1_ms=now;
    order=resets=0; raw[3]=0; issued_baud=4; baud_writes=lp.baud_epoch=2;
}
int main(void) {
    setup(1000); issued_baud=0x80000004; lp_record(LP_ARM,0,1);
    assert(lp.reset && lp.reset_cause==LP_RST_ISSUED_BAUD && lp.reset_issued_baud==0x80000004 && !lp.reset_raw[3] && lp.reset_read_mask==5);
    assert(lp.reset_meta==0x10001 && lp.hold);
    uint32_t when=lp.reset_ms, first=lp.reset_ticks;
    issued_baud=4; fm1_ms+=99; lp_request_reset(LP_RST_ABORT); lp_reset_if_requested();
    assert(!resets && lp.reset_ms==when && lp.reset_ticks==first && lp.reset_cause==LP_RST_ISSUED_BAUD);
    fm1_ms++; lp_reset_if_requested(); assert(resets==1 && order==5);
    setup(UINT32_MAX-50); lp.count=LP_TRACE_CAP; lp_record(LP_ARM,0,1);
    assert(lp.reset_cause==LP_RST_TRACE && lp.count==LP_TRACE_CAP);
    fm1_ms+=99; lp_reset_if_requested(); assert(!resets);
    fm1_ms++; lp_reset_if_requested(); assert(resets);
    setup(100); fm1_ms+=LP_HOLD_MS-1; lp_request_reset(LP_RST_ABORT);
    lp_reset_if_requested(); assert(!resets);
    fm1_ms++; lp_reset_if_requested(); assert(resets);
    setup(100); fm1_ms+=LP_HOLD_MS; lp_request_reset(LP_RST_HOLD);
    lp_reset_if_requested(); assert(resets);
    setup(100); uint32_t observed[4]; fm1_lcd_snapshot(observed);
    assert(observed[0]==raw[0] && observed[2]==raw[2] && !observed[1] && !observed[3] && con_reads && cnt_reads);
    assert(!lp_baud_allowed(4) && lp.reset_cause==LP_RST_BAUD_ATTEMPT && lp.reset_attempt_valid && lp.reset_attempt_baud==4 && lp.reset_issued_baud==4 && baud_writes==2);
    setup(100); lp.released=1; lp.hold=0; lp.phase=LP_REPAINT; lcd_busy=lcd_fault=0;
    assert(lp_baud_allowed(4) && !lp.reset); assert(!lp_baud_allowed(5) && lp.reset_attempt_baud==5);

    return 0;
}
"""
with tempfile.TemporaryDirectory(prefix="felucca-lcd-reset-") as directory:
    src = Path(directory) / "reset.c"
    binary = Path(directory) / "reset"
    src.write_text(probe)
    subprocess.run(shlex.split(os.environ.get("CC", "cc")) +
                   ["-std=c11", "-O1", "-Wall", "-Wextra", "-Werror", "-Wno-unused-function",
                    "-I" + str(root / "firmware/src"), str(src), "-o", str(binary)],
                   check=True, timeout=30)
    subprocess.run([str(binary)], check=True, timeout=10)
