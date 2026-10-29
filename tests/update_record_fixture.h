/* SPDX-License-Identifier: GPL-3.0-only */
#ifndef FELUCCA_TESTS_UPDATE_RECORD_FIXTURE_H
#define FELUCCA_TESTS_UPDATE_RECORD_FIXTURE_H
#include <stdint.h>
#include <string.h>

/* Bytes produced by ota.c's native record fields: mode/magic, name and staging
 * address, CRC-16/XMODEM over bytes 2..79, zero remainder. The loader fixture
 * checks the CRC with production ota_crc16. These literal fields do not prove
 * which fields an external SPL validates or which record it would select. */
static const uint8_t UPDATE_RECORD_FIXTURE[112] = {
    0x1D, 0xB7, 0x0D, 0x5A, 0x01, 0x5A, 0x41, 0x54,
    'o', 't', 'a', '-', 'F', 'M', '-', '1', '_', '0', '1', '5',
    [74] = 0x0E,                                      /* little-endian 0xE0000 at +72 */
};
#define UPDATE_RECORD_PAYLOAD_OFF 0xE00u             /* storage payload+0x100 -> sector+0xF00 */
#define UPDATE_RECORD_UPFM6_SIZE 3728u
_Static_assert(UPDATE_RECORD_PAYLOAD_OFF + sizeof UPDATE_RECORD_FIXTURE <= UPDATE_RECORD_UPFM6_SIZE,
               "the complete fixture fits the existing UPF6 payload");

/* Valid current UPF6 header, no used entries. Inactive entry bytes are opaque
 * data accepted/preserved by BACKUP_PUT id 9; no patch sanitizer runs over them.
 * backup_test additionally pins this against the production upf_t layout. */
static void update_record_upfm6(uint8_t *p)
{
    memset(p, 0, UPDATE_RECORD_UPFM6_SIZE);
    memcpy(p, "UPF6", 4);
    p[4] = 1; p[6] = 32;
    memcpy(p + UPDATE_RECORD_PAYLOAD_OFF, UPDATE_RECORD_FIXTURE, sizeof UPDATE_RECORD_FIXTURE);
}
#endif
