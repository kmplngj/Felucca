/* SPDX-License-Identifier: GPL-3.0-only */
/* Included after ota.c, before ldr_install.c. Diagnostics only, IRQs off.
 * ota_service is NOT called from ldr_poll: no queries or formatting during
 * measured draw callbacks, nor while erase/program code is running. */
#if FELUCCA_LDR_LCD_TRACE
static void ldr_trace_reply(const uint8_t *request, uint32_t n)
{
    uint8_t reply[32];
    if (ldr_trace_pack(request, n, reply))
        ota_send_msg(0x3Eu, reply, sizeof reply);
}
/* Allow the diagnostic host to read the SUCCESS record before normal reset.
 * This changes restart timing of the diagnostic variant only. It never starts
 * another install or writes flash and ends even if no diagnostic host exists. */
static void ldr_trace_read_window(void)
{
    uint32_t start = ldr_ms();
    while (ldr_ms() - start < 3000u) {
        ldr_poll();
        ota_service();
    }
}
#endif
