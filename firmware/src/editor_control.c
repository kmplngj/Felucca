/* SPDX-License-Identifier: GPL-3.0-only */
/* Main-loop control. A supported client owns all editor transfers exclusively;
 * legacy stateless transfers stay latched until that owner explicitly releases.
 * Challenges correlate one request, not authentication or device identity. */
#ifndef FELUCCA_RESTART
#define FELUCCA_RESTART 0
#endif
#define ED_CONTROL 84u
#define ED_CONTROL_CAPS (1u | (FELUCCA_RESTART ? 2u : 0u) | 4u)
#define ED_CONTROL_TTL 2000u
#define ED_CONTROL_QUIET_MS 100u
static struct {
    uint32_t generation, serial, challenge, issued, epoch;
    uint32_t end, started, midi, audio, quiet_audio, quiet_since;
    uint8_t pending, transfer;
} ed_control __attribute__((section(".pool")));
#if FELUCCA_RESTART
static void ed_restart_platform(void);
#endif
static void ed_control_boot(uint32_t generation)
{
    memset(&ed_control, 0, sizeof ed_control);
    ed_control.generation = generation;
    ed_control.quiet_audio = fx_audio_activity;
    ed_control.quiet_since = fm1_ms;
}
static int ed_control_u32_ok(const uint8_t *a) { return a[4] <= 15u; }
/* Called only with interrupts disabled: one snapshot, including the final
 * check immediately before stopping audio and handing off to the reset HAL. */
static uint32_t ed_control_busy(void)
{
    uint32_t busy = 0, k, i;
    if (song.playing || song.rec || chain_busy() || transport_req || seq_counting()) busy |= 1u;
    if (fm1_in.notes || fm1_in.buttons || kb_boot_hold ||
        fx_audio_activity != ed_control.quiet_audio || fm1_ms - ed_control.quiet_since < ED_CONTROL_QUIET_MS)
        busy |= 2u;
#if BOARD_SMK37
    if (smk_extkeys_held) busy |= 2u;            /* silent/wake-only outer keys still have physical ownership */
#endif
    for (k = 0; k < NTRK; k++) {
        if (midi_track_held(k) || trk[k].nheld || trk[k].arp_phys || trk[k].latched || trk[k].seq_n || trk[k].rh_n)
            busy |= 2u;
        for (i = 0; i < NVOICE; i++) if (trk[k].v[i].active) busy |= 2u;
    }
    if (ui.menu || ui.confirm || ui.uboot || ui.ml.on || ui.ly || ui.layer || ui.entry_open || name_on())
        busy |= 4u;
    if (ed_control.transfer || ed_bk_put || fvb_tx.on) busy |= 8u;
    if (set_later.on) busy |= 16u;
#if FELUCCA_FLASH
    if (persist_pending != PERSIST_IDLE) busy |= 16u;
#endif
#if FELUCCA_SLICE
    if (slc_man_save || slice_page_on()) busy |= 16u;
#endif
    if (!usb.up || !usb.config || usb.suspended || usb.ota_req || usb.uboot_req || usb_rescue_mode) busy |= 32u;
#if FELUCCA_UAC
    if (uac.alt) busy |= 32u;
#endif
#if FELUCCA_SCREEN_CAPTURE
    if (scap_live()) busy |= 64u;
#endif
    if (mi_r != mi_w || mo_r != mo_w || midi_in_overflow || usb.rx_pend || sx_collect) busy |= 128u;
#if FELUCCA_CDC
    if (ci_r != ci_w || cdc.rx_pend) busy |= 128u;
#endif
    return busy;
}
static void ed_control_poll(void)
{
    uint32_t audio = fx_audio_activity;          /* one scalar; audio ISR publishes no associated payload */
    if (audio != ed_control.quiet_audio) {
        ed_control.quiet_audio = audio;
        ed_control.quiet_since = fm1_ms;
    }
    if (!ed_control.pending) return;
    fm1_irq_off();
    if (sx_ready || so_epoch != ed_control.epoch || fm1_ms - ed_control.started >= ED_CONTROL_TTL ||
        ed_control_busy() || mi_w != ed_control.midi || fx_audio_activity != ed_control.audio) {
        ed_control.pending = 0;
    } else if ((int32_t)(so_done - ed_control.end) >= 0) {
        ed_control.pending = 0;
#if FELUCCA_RESTART
        ed_restart_platform();                    /* target never returns; CPU1 is held by HAL */
#endif
    }
    fm1_irq_on();
}
static void ed_control_handle(const uint8_t *a, uint32_t n)
{
    uint32_t op = n ? a[0] : 127u, request = n >= 6u ? ed_bk_r32(a + 1) : 0u;
    uint32_t rc = 0, busy = 0, end, epoch;
    ed_control.pending = 0;                      /* every new control request cancels the old transaction */
    if (n < 6u || !ed_control_u32_ok(a + 1) || op > 2u ||
        (op == 0u ? (n != 6u && (n != 7u || a[6] != 1u)) :
         n != 16u || !ed_control_u32_ok(a + 6) || !ed_control_u32_ok(a + 11)))
        rc = 1;
    fm1_irq_off();
    if (!rc) {
        busy = ed_control_busy();
        if (!op) {
            if (!++ed_control.serial) ++ed_control.serial;
            ed_control.challenge = ed_control.serial;
            ed_control.issued = fm1_ms;
            ed_control.epoch = so_epoch;
        } else {
            if (!ed_control.challenge || ed_bk_r32(a + 6) != ed_control.generation ||
                ed_bk_r32(a + 11) != ed_control.challenge || so_epoch != ed_control.epoch ||
                fm1_ms - ed_control.issued >= ED_CONTROL_TTL) rc = 2;
            ed_control.challenge = 0;             /* busy and refused requests consume their token too */
            if (!rc && op == 2u) {
                if (ed_bk_put || fvb_tx.on || (busy & (16u | 32u))) rc = 3;
                else ed_control.transfer = 0;     /* explicit complete/cancel declaration from the single owner */
            } else if (!rc && !FELUCCA_RESTART) rc = 4;
            else if (!rc && busy) rc = 3;
        }
    }
    ed_begin(ED_CONTROL);
    ed_b(op); ed_b(rc); ed_bk_u32(request);
    ed_bk_u32(ed_control.generation);
    if (!op && !rc) {
        ed_bk_u32(ed_control.challenge); ed_bk_u32(fm1_ms); ed_bk_u32(busy);
        ed_b(FELUCCA_BUILD_DIRTY); ed_str(FELUCCA_BUILD_COMMIT, 40); ed_str(FELUCCA_VERSION, 24);
        if (n == 7u) {
            ed_str(FELUCCA_BUILD_PR, 32); ed_str(FELUCCA_PROFILE_NAME, 64);
        }
    }
    ed_out[ed_n++] = 0xF7;
    if (!ota_wire_control(ed_out, ed_n, &end, &epoch) && op == 1u && !rc) {
        ed_control.end = end;
        ed_control.epoch = epoch;
        ed_control.started = fm1_ms;
        ed_control.midi = mi_w;
        ed_control.audio = fx_audio_activity;
        ed_control.pending = 1;
    }
    fm1_irq_on();
}
