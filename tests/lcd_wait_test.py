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
