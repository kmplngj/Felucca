/* SPDX-License-Identifier: GPL-3.0-only */
/* Early recovery runs before persistence, synth, CPU1, audio or TIMER5 startup.
 * Interrupts remain masked: this loop is the sole USB SIE owner. */
static uint32_t rescue_last, rescue_frac, rescue_usb_at, rescue_input_at;

static void rescue_clock(void)
{
    uint32_t now = fm1_ticks(), elapsed = now - rescue_last;
    rescue_last = now;
    /* Split before adding the remainder: even a near-full TIMER4 wrap cannot
     * overflow the fraction. The poll cadence stays far below one wrap. */
    fm1_ms += elapsed / (1000u * FM1_TICKS_PER_US);
    rescue_frac += elapsed % (1000u * FM1_TICKS_PER_US);
    if (rescue_frac >= 1000u * FM1_TICKS_PER_US) {
        rescue_frac -= 1000u * FM1_TICKS_PER_US;
        fm1_ms++;
    }
}

static void rescue_poll(void)
{
    rescue_clock();
    fm1_wdt_feed();
    if ((uint32_t)(rescue_last - rescue_input_at) >= 100u * FM1_TICKS_PER_US) {
        rescue_input_at = rescue_last;
        fm1_input_tick();                      /* panel scan only; no note consumer */
    }
    if ((uint32_t)(rescue_last - rescue_usb_at) >= 500u * FM1_TICKS_PER_US) {
        rescue_usb_at = rescue_last;
        usb_poll();
    }
    usb_retry(fm1_ms);                          /* late cable / failed SIE start */
}

static void rescue_wait(uint32_t ms)
{
    uint32_t start = fm1_ms;
    while ((uint32_t)(fm1_ms - start) < ms)
        rescue_poll();
}

static void rescue_screen(void)
{
    lcd_fill(0, 0, 240, 240, 0);
    draw_text_box(0, 54, 240, &AF_M, "USB RESCUE", 0xFFFFu, 1);
    draw_text_box(0, 94, 240, &AF_S, "CONNECT INSTALLER", 0xFFFFu, 1);
#if FELUCCA_OTA
    draw_text_box(0, 124, 240, &AF_S, flash_ok ? "READY TO UPDATE" : "FLASH NOT SUPPORTED", 0x07FFu, 1);
#endif
    draw_text_box(0, 172, 240, &AF_S, "RESET FOR ROM USB", 0xFFFFu, 1);
}

/* Called after RAM/vector/guard setup, before any normal startup routine. No
 * settings or flash layout is trusted to decide whether recovery is needed. */
static uint32_t rescue_boot_buttons(void)
{
    uint32_t start, scanned_at;
    /* PA2 also supplies the matrix/595 rail; lcd_init normally enables it,
     * but recovery must read keys before initializing the display. Allow the
     * rail to rise before debounce can count any samples. */
    fm1_panel_power_on();
    fm1_input_init();
    fm1_wdt_feed();
    fm1_delay_ms(30);
    start = scanned_at = fm1_ticks();
    do {
        uint32_t now = fm1_ticks();
        fm1_wdt_feed();
        /* Match TIMER5: latch a column, then sample on the next 100 us tick.
         * The old full-frame scanner samples after
         * only 10 us and can miss/shift a held OCT key on the physical panel.
         * No interrupt or USB service starts during this decision. */
        if ((uint32_t)(now - scanned_at) >= 100u * FM1_TICKS_PER_US) {
            scanned_at = now;
            fm1_input_tick();
        }
    } while ((uint32_t)(fm1_ticks() - start) < 30000u * FM1_TICKS_PER_US);
#if BOARD_SMK37
    /* The SMK bank buttons occupy bits 0/1; boot policy takes normalized OCT bits. */
    return ((fm1_in.buttons >> FM1_BTN_OCT_DOWN) & 1u) |
           (((fm1_in.buttons >> FM1_BTN_OCT_UP) & 1u) << 1);
#else
    return fm1_in.buttons & 3u;                 /* physical OCT-, OCT+; no saved panel mapping */
#endif
}

#if FELUCCA_OTA
static void rescue_init(void)
{
    usb_rescue_mode = 1;
    rescue_last = fm1_ticks();
    rescue_usb_at = rescue_input_at = rescue_last;
    rescue_frac = 0;
    fm1_ms = 0;
    /* JEDEC is read-only. Avoid irq_restore(), which unconditionally enables
     * interrupts on this HAL, and never import or clean up persisted data. */
#if BOARD_SMK37
    flash_ok = FL_JEDEC_OK(FL_FAR(fl_jedec_ram)());
#else
    flash_ok = FL_FAR(fl_jedec_ram)() == 0x856014u;
#endif
    lcd_init();
    rescue_screen();
    usb_start();
}

static void rescue_step(void)
{
    rescue_poll();
    if (usb.uboot_req) {                        /* explicit stock soft key */
        usb_detach();
        rescue_wait(30);
        boot_policy_intentional(&bootguard);
        fm1_enter_uboot();
    }
    ota_service();                             /* identity only; editor requests are discarded */
    if (usb.ota_req) {
        usb.ota_req = 0;
        if (flash_ok)
            ota_session();                    /* refused / failed / aborted: keep serving recovery */
        rescue_screen();
    }
}

static void rescue_run(void)
{
    rescue_init();
    for (;;)
        rescue_step();
}
#endif
