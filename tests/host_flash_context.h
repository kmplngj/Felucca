/* SPDX-License-Identifier: GPL-3.0-only */
#ifndef HOST_FLASH_CONTEXT_H
#define HOST_FLASH_CONTEXT_H

#include <stdint.h>
#include "../firmware/hal/fm1_flash_context_contract.h"

/* Single-threaded host flash context: no IRQ or encrypted XIP window exists.
 * Storage fixtures enable flash directly; the emulator runs persist_boot and
 * selects the FM-1's JEDEC ID before including this header. The rescue fixture
 * keeps its dynamic chip ID to exercise the real rescue decision paths. */
#ifndef HOST_FLASH_JEDEC
#define HOST_FLASH_JEDEC 0u
#endif
static irq_save_fn irq_save;
static uint32_t irq_save(void) { return 0; }
static irq_restore_fn irq_restore;
static void irq_restore(uint32_t f) { (void)f; }
static fl_jedec_ram_fn fl_jedec_ram;
static uint32_t fl_jedec_ram(void) { return HOST_FLASH_JEDEC; }
static fl_plain_window_init_fn fl_plain_window_init;
static void fl_plain_window_init(void) {}
#define FL_FAR(fn) (fn)

#endif
