/* SPDX-License-Identifier: GPL-3.0-only */
/* Real initialization/tick against GPIO, a delayed SPI2 DMA and a 595 latch.
 * Contacts live on physical columns; rows change only after that word latches.
 * This intentionally never populates fm1_in.raw or calls decoder helpers. */
#include <stdint.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#define BOARD_SMK37 1
#include "../firmware/hal/fm1_time.h"
#include "../firmware/hal/fm1_gpio.h"
static uint32_t now;
static uint32_t host_ticks(void) { return now; }
static volatile uint32_t *host_gpio(uint32_t port, uint32_t reg);
static volatile uint32_t *host_sfr(uint32_t address);
static uint32_t host_dma_address(const void *p);
#undef FM1_PR
#define FM1_PR(p, r) (*host_gpio((p), (r)))
#define SMK_REG(a) (*host_sfr(a))
#define SMK_DMA_ADDRESS(p) host_dma_address(p)
#define fm1_ticks host_ticks
#ifndef SMK_INPUT_SOURCE
#define SMK_INPUT_SOURCE "../firmware/hal/smk_input.h"
#endif
#include SMK_INPUT_SOURCE
#undef fm1_ticks

static volatile uint32_t gpio[8][8], sfr[9];
static const uint32_t sfr_address[] = {0x11E00,0x11E04,0x11E0C,0x11E10,0x51020,0x16A0C,0x13100,0x13104,0x11900};
static uint8_t contacts[16];
static uint32_t last_out, shifted, dma_start, dma_word, latch_at, latch_count, tick_count;
static const uint32_t *dma_source;
static int selected = -1, dma_pending, shift_ready;
static uint32_t adc_physical_slot, adc_pending, init_latches;
static int flash_led_cases;
static void require(int ok, const char *message)
{
    if (!ok) { fprintf(stderr, "FAIL tick %u selected %d: %s\n", tick_count, selected, message); exit(1); }
}
static void service(void)
{
    uint32_t out = gpio[FM1_PA][FM1_OUT / 4u], column, found = 0;
    if (dma_pending && now - dma_start >= 3u * FM1_TICKS_PER_US) {
        require(*dma_source == dma_word, "DMA source mutated before transfer completion");
        shifted = dma_word;
        dma_pending = 0;
        shift_ready = 1;
        sfr[0] |= 0x8000u;
    }
    if ((out & (1u << 1)) && !(last_out & (1u << 1))) {
        require(shift_ready && !dma_pending, "latch before SPI2 completed the pending word");
        for (column = 0; column < 16u; column++) {
            uint32_t bit = column < 8u ? 0x01000000u << column : 0x00010000u << (column - 8u);
            if (!(shifted & bit)) { selected = (int)column; found++; }
        }
        require(found == 1u, "latched word selects exactly one column");
        latch_at = now; latch_count++; shift_ready = 0;
    }
    last_out = out;
    if (sfr[3]) {
        require(sfr[3] == 4u && sfr[2] == 1u && !dma_pending, "one four-byte SPI2 DMA at a time");
        dma_word = *dma_source;
        dma_start = now; dma_pending = 1; sfr[3] = 0;
    }
}
static volatile uint32_t *host_gpio(uint32_t port, uint32_t reg)
{
    service();
    if (reg == FM1_IN) {
        uint32_t r = selected < 0 ? 0xFFu : now - latch_at < 10u * FM1_TICKS_PER_US ? 0u : contacts[selected];
        if (port == FM1_PA)
            gpio[port][reg / 4u] = ~((r & 1u) << 2 | (r & 0x0Eu) << 4 | (r & 0x10u) << 5);
        if (port == FM1_PH)
            gpio[port][reg / 4u] = ~((r & 0x20u) << 1 | (r & 0xC0u) << 2);
    }
    return &gpio[port][reg / 4u];
}
static volatile uint32_t *host_sfr(uint32_t address)
{
    uint32_t i;
    service();
    for (i = 0; i < sizeof sfr_address / sizeof sfr_address[0]; i++)
        if (sfr_address[i] == address) return &sfr[i];
    require(0, "unexpected SFR address"); return NULL;
}
static uint32_t host_dma_address(const void *p)
{
    service(); require(!dma_pending, "next word cannot reuse in-flight DMA source");
    dma_source = p; return 1u;
}
static void tick(void)
{
    uint32_t delivered = adc_pending && smk_adc_slot != 0xFFu ? adc_physical_slot : 0xFFu;
    now += 100u * FM1_TICKS_PER_US; tick_count++;
    service();
    /* Capture mux/channel at the actual start, then complete between ticks.
     * A re-init may discard a conversion from the previous scan session. */
    if (adc_pending) {
        if (smk_adc_slot != 0xFFu && smk_adc_slot != adc_physical_slot)
            fprintf(stderr, "ADC labeled slot %u, physical mux/channel slot %u\n", smk_adc_slot, adc_physical_slot);
        require(smk_adc_slot == 0xFFu || smk_adc_slot == adc_physical_slot,
                "ADC result label must match the latched physical mux and channel");
        sfr[6] |= 0x80u; sfr[7] = 100u + adc_physical_slot;
    }
    fm1_input_tick(); service();
    if (delivered != 0xFFu && delivered % 3u != 2u) {
        static const uint8_t pad_at_mux[8] = {1, 2, 3, 0, 4, 7, 5, 6};
        uint32_t pad = pad_at_mux[delivered / 3u] + (delivered % 3u == 1u ? 8u : 0u);
        require(fm1_in.pad_raw[pad] == 100u + delivered,
                "physical pad conversion reaches its own pad reading");
    }
    {
        uint32_t channel = (sfr[6] >> 8) & 15u;
        uint32_t mux = (shifted >> 3) & 7u;
        require((sfr[6] & 0x50u) == 0x50u, "tick starts one ADC conversion");
        require(channel == 1u || channel == 8u || channel == 2u, "ADC uses physical pad/mux channels");
        adc_physical_slot = mux * 3u + (channel == 1u ? 0u : channel == 8u ? 1u : 2u);
        adc_pending = 1;
    }
    if (latch_count - init_latches >= 17u) {
        uint32_t common = (sfr[5] >> 17) & 3u;
        uint32_t mask = (1u << 12) | (1u << 2);
        if (flash_led_cases && common == 3u) return; /* erase paused the group until the next col0 */
        require(common == 1u || common == 2u, "exactly one LED group active");
        require((shifted & mask) == (common == 2u ? 1u << 2 : 1u << 12),
                "LED commons match the group encoded in the latched word");
    }
}
static void run(uint32_t ticks) { while (ticks--) tick(); }
static void close_contact(uint32_t code, int down)
{
    uint8_t bit = (uint8_t)(1u << (code & 15u));
    if (down) contacts[code >> 4] |= bit; else contacts[code >> 4] &= (uint8_t)~bit;
}
/* Exercise the production storage adapters with the real register-backed
 * common driver, then let the actual scan restore its own phase at col0. */
#include "../firmware/hal/fm1_flash_map.h"
#define FL_FAR(fn) fn
static uint16_t abuf[8];
static int erase_irq_off, erase_fail, marker_erased;
static uint32_t erase_commands;
static uint32_t irq_save(void) { erase_irq_off = 1; return 0; }
static void irq_restore(uint32_t flags)
{
    (void)flags; erase_irq_off = 0;
    if (flash_led_cases) tick();                 /* an interrupt may run after any read/erase window */
}
static void fm1_wdt_feed(void) {}
static int fl_read_ram(uint32_t off, uint8_t *dst, uint32_t n)
{
    memset(dst, FL_IN(off, n, FL_STOCKTAG_LO, FL_STOCKTAG_HI) && !marker_erased ? 0 : 255, n);
    return 0;
}
static int fl_write(uint32_t off, const uint8_t *src, uint32_t n)
{ (void)off; (void)src; (void)n; return 0; }
static int fl_erase4k_ram(uint32_t off, uint32_t *took)
{
    require(erase_irq_off && ((sfr[5] >> 17) & 3u) == 3u,
            "both physical LED commons must be off before the flash erase command");
    erase_commands++; *took = 400000u; now += *took * FM1_TICKS_PER_US;
    if (erase_fail) return -1;
    if (off == FL_STOCKTAG_LO) marker_erased = 1;
    return 0;
}
#include "../firmware/src/storage_hw.c"
static void erase_led_test(void)
{
    uint32_t group, failed, kind, waited;
    flash_ok = st_owner_ready = 1;
    flash_led_cases = 1;
    for (group = 0; group < 2u; group++)
        for (failed = 0; failed < 2u; failed++)
            for (kind = 0; kind < 3u; kind++) {
                int rc;
                for (waited = 0; waited < 32u && ((sfr[5] >> 17) & 3u) != (group ? 1u : 2u); waited++) tick();
                require(((sfr[5] >> 17) & 3u) == (group ? 1u : 2u),
                        "test begins with either physically active LED common in the scan's own phase");
                erase_commands = 0; erase_fail = (int)failed; marker_erased = kind != 2u;
                rc = kind == 0u ? st_owner_erase(FL_DATA_LO) : st_erase(kind == 1u ? FL_DATA_LO : FL_SMP_LO);
                require((rc != 0) == (failed != 0), "erase adapter preserves success/failure result");
                require(erase_commands == (kind == 2u && !failed ? 2u : 1u),
                        "sample prerequisite and sample erases each blank the commons");
                for (waited = 0; waited < 16u && ((sfr[5] >> 17) & 3u) == 3u; waited++) tick();
                require(((sfr[5] >> 17) & 3u) != 3u, "actual scan re-enables an LED common within one frame");
                run(32);                       /* existing group/latch assertions verify resumed phase */
            }
    flash_led_cases = 0;
}

int main(void)
{
    uint32_t i, e, k;
    /* Undefined power-on 595 selection is not a valid sample. Even if the
     * floating rows look closed, no decoded key may appear before col0 settles. */
    memset((void *)&fm1_in, 0, sizeof fm1_in);
    fm1_led[0] = fm1_led[1] = 1;                 /* distinct lit bits in opposite common groups */
    fm1_input_init(); service();
    require(latch_count == 0u && dma_pending, "init shifts col0 without prematurely latching it");
    close_contact(0x66u, 1);                    /* physical OCT-; adjacent 0x76 is FADER BANK */
    tick();
    for (i = 0; i < FM1_NCOL; i++)
        require(fm1_in.raw[i] == 0u, "undefined power-on rows are not a valid first sample");
    require(!fm1_in.frames, "first latch alone cannot complete a sampled frame");
    run(15);
    require(!fm1_in.frames, "frame waits for the actual column15 sample");
    tick();
    require(fm1_in.frames == 1u, "first frame follows 16 settled column samples");
    run(63);
    if (fm1_in.buttons != (1u << FM1_BTN_OCT_DOWN))
        fprintf(stderr, "physical OCT- produced button mask 0x%X (wanted 0x%X)\n", fm1_in.buttons, 1u << FM1_BTN_OCT_DOWN);
    require(fm1_in.buttons == (1u << FM1_BTN_OCT_DOWN), "physical OCT- must never become FADER BANK");
    close_contact(0x66u, 0); run(80);
    require(!fm1_in.buttons, "physical OCT- releases");
    for (i = 0; i < FM1_NBTN; i++) {
        close_contact(SMK_BTNC[i], 1); run(64);
        require(fm1_in.buttons == (1u << i), "every physical button decodes in its own column");
        close_contact(SMK_BTNC[i], 0); run(80);
        require(!fm1_in.buttons, "every physical button releases across frame wrap");
    }
    for (k = 0; k < FM1_NKEY; k++) {
        close_contact(SMK_KEYC[k][0], 1); run(32);
        require(!fm1_in.keys, "first contact does not trigger a note");
        close_contact(SMK_KEYC[k][1], 1); run(32);
        require(fm1_in.keys == ((uint64_t)1u << k) && fm1_in.key_vel[k] > 0u,
                "all physical key pairs retain their key number and velocity");
        close_contact(SMK_KEYC[k][0], 0); close_contact(SMK_KEYC[k][1], 0); run(80);
        require(!fm1_in.keys && !fm1_in.notes, "all physical notes release");
        /* Outer-key events are not consumed by this scan-only fixture. */
        smk_extq_r = smk_extq_w;
    }
    for (e = 0; e < FM1_NENC; e++) {
        static const uint8_t states[] = {2, 3, 1, 0};
        int16_t before[FM1_NENC]; uint32_t other;
        for (other = 0; other < FM1_NENC; other++) before[other] = fm1_in.enc_steps[other];
        for (i = 0; i < 8u; i++) {
            uint32_t state = states[i & 3u];
            close_contact(SMK_ENCC[e][0], state & 1u);
            close_contact(SMK_ENCC[e][1], state & 2u);
            run(48);
        }
        require(abs(fm1_in.enc_steps[e] - before[e]) == 1,
                "physical encoder pair emits the expected detent through the pipeline");
        for (other = 0; other < FM1_NENC; other++)
            require(other == e || fm1_in.enc_steps[other] == before[other],
                    "physical encoder movement never appears on a neighboring encoder");
    }
    /* Rescue scans before normal main startup initializes this same HAL again.
     * Re-init from a nonzero mux phase must restart the slot/address together. */
    for (i = 0; i < 2u; i++) {
        for (e = 0; e < 96u && (smk_slot != 12u || smk_grp != i); e++) tick();
        require(smk_slot == 12u && smk_grp == i, "nonzero analog phase reached in either LED group");
        now += 10u * FM1_TICKS_PER_US; service();      /* DMA finished before the second init */
        fm1_input_init(); service();
        init_latches = latch_count;
        require(smk_sample_col == 0xFFu && smk_adc_slot == 0xFFu,
                "re-init invalidates the previous row and ADC sample labels");
        run(96);                                      /* four ADC cycles, either LED common group */
    }
    erase_led_test();
    require(fm1_in.adc_miss == 0u, "all completed conversions were delivered");
    puts("SMK register-backed startup/OCT/buttons/37 keys/8 encoders/frame-wrap/re-init ADC scan passed");
    return 0;
}
