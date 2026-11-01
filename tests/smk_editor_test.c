/* SPDX-License-Identifier: GPL-3.0-only */
/* Real editor framing and sample handlers with production storage ownership/marker policy. */
#define SMK_EDITOR_TEST 1
#include "editor_test.c"
#define CHECK(x) do { if (!(x)) { fprintf(stderr, "line %d: %s\n", __LINE__, #x); return 1; } } while (0)
static void smk_reset(uint32_t owner)
{
    reset();
    memset(host_nor, 255, sizeof host_nor);
    st_owner_ready = owner; flash_ok = 1;
    host_sample_reads = host_raw_reads = host_mutation_unsafe = host_marker_fail = 0;
    host_erase_count = 0;
}
int main(void)
{
    uint8_t a[640] = {0}, data[256] = {1}, backup[8] = {34,0,0,0,0,0,1,0};
    smp_user_hdr_t h;
    uint32_t n, slot, owner, cmd, len;
    /* A wake-only/silent outer key has physical ownership without a sounding note. */
    smk_reset(1); control_token(a, 1); smk_extkeys_held = 1u;
    CHECK(!fm1_in.notes && !midi_track_held(0));
    request(ED_CONTROL, a, 16);
    CHECK(host_wire[6] == 3 && !ed_control.pending && !host_restarts);
    smk_extkeys_held = 0;
    smk_reset(1); control_token(a, 1); request(ED_CONTROL, a, 16);
    CHECK(ed_control.pending && !host_wire[6]);
    smk_extkeys_held = 1u; so_done = ed_control.end; ed_control_poll();
    CHECK(!ed_control.pending && !host_restarts);
    smk_extkeys_held = 0;
    /* Every unavailable mutation replies in the existing shape, before STOP or flash/XIP access. */
    for (owner = 0; owner < 2; owner++) for (slot = 0; slot < 3; slot++) {
        if (owner && slot < 2) continue;
        for (cmd = ED_SMP_BEGIN; cmd <= ED_SMP_ERASE; cmd++) {
            smk_reset(owner); song.playing = 1; transport_req = 1;
            a[0] = slot; a[1] = 0; a[2] = 8; a[3] = 0;
            n = cmd == ED_SMP_WRITE ? 4 + pack7(data, sizeof data, a + 4) : cmd == ED_SMP_END ? 2 : 1;
            len = request(cmd, a, n);
            CHECK(len == (cmd == ED_SMP_WRITE ? 11u : 8u));
            CHECK(host_wire[cmd == ED_SMP_WRITE ? 9 : 6] != 0);
            CHECK(song.playing && transport_req == 1 && !host_erases && !host_writes &&
                  !host_sample_reads && !host_raw_reads);
        }
        smk_reset(owner); usr_nz[slot] = 1;
        CHECK(request(ED_SMP_INFO, a, 0) == 17u);
        CHECK(host_wire[7 + slot * 3] == 0 && host_sample_reads == (owner ? 2u : 0u));
        /* Backup keeps wire id USR3 (34), but its unavailable entry has zero bytes. */
        host_sample_reads = 0; len = 99;
        CHECK(ed_bk_object(32 + slot, &len) == ED_BK_RAW && len == 0 && !host_sample_reads);
        ed_bk_valid = 1; ed_bk_usb = usb.resets; backup[0] = 32 + slot;
        CHECK(request(ED_BACKUP_GET, backup, 8) > 0 && host_wire[6] != 0 && !host_sample_reads);
        a[0] = 0; a[1] = 32 + slot; song.playing = 1;
        CHECK(request(ED_BACKUP_PUT, a, 2) > 0 && host_wire[7] != 0 && song.playing);
    }
    smk_reset(1); flash_ok = 0; song.playing = 1; a[0] = 0;
    CHECK(request(ED_SMP_BEGIN, a, 1) == 8 && host_wire[6] != 0 && song.playing && !host_erases);
    /* Malformed/aligned/protected offsets cannot erase a sector or stop transport. */
    smk_reset(1); song.playing = 1; a[0] = 0;
    a[1] = 1; a[2] = 8; a[3] = 0; n = 4 + pack7(data, sizeof data, a + 4);
    CHECK(request(ED_SMP_WRITE, a, n) == 11 && host_wire[9] == 1 && song.playing && !host_erases && !host_writes);
    a[1] = 0; a[2] = 0; a[3] = 5; /* slot end: would reach the next slot */
    CHECK(request(ED_SMP_WRITE, a, n) == 11 && host_wire[9] == 1 && song.playing && !host_erases && !host_writes);
    CHECK(!request(ED_SMP_BEGIN, a, 2));
    CHECK(ed_smp_erase(2, 1) != 0 && !host_erases);
    /* The marker sector must be erased and verified before the first actual sample erase. */
    smk_reset(1); memcpy(host_nor + FL_STOCKTAG_HI - 8, "usrdata", 8); a[0] = 0;
    CHECK(request(ED_SMP_BEGIN, a, 1) == 8 && host_wire[6] == 0);
    CHECK(host_erase_count == 2 && host_erase_offsets[0] == FL_STOCKTAG_LO && host_erase_offsets[1] == FL_SMP_LO);
    CHECK(!host_mutation_unsafe);
    /* Direct data and header programs cannot bypass a still-present marker. */
    memcpy(host_nor + FL_STOCKTAG_HI - 8, "usrdata", 8);
    a[1] = 0; a[2] = 4; a[3] = 0; n = 4 + pack7(data, sizeof data, a + 4);
    CHECK(request(ED_SMP_WRITE, a, n) == 11 && host_wire[9] == 3 && !host_writes);
    memcpy(host_nor + FL_SMP_LO + SMP_USER_DATA, data, sizeof data);
    memset(&h, 0, sizeof h); h.magic = SMP_USER_MAGIC; h.version = 1; h.nz = 1;
    h.data_len = sizeof data; h.crc = st_crc32(data, sizeof data);
    n = 1 + pack7((const uint8_t *)&h, sizeof h, a + 1);
    CHECK(request(ED_SMP_END, a, n) == 8 && host_wire[6] == 4 && !host_writes);
    /* Marker erase failure prevents sample mutation. */
    smk_reset(1); memcpy(host_nor + FL_STOCKTAG_HI - 8, "usrdata", 8); host_marker_fail = 1;
    CHECK(request(ED_SMP_BEGIN, a, 1) == 8 && host_wire[6] != 0 && host_erase_count == 1 && !host_writes);
    /* WRITE's sector erase uses the same gate, then programming succeeds. */
    smk_reset(1); memcpy(host_nor + FL_STOCKTAG_HI - 8, "usrdata", 8);
    a[0] = 1; a[1] = 0; a[2] = 32; a[3] = 0; n = 4 + pack7(data, sizeof data, a + 4);
    CHECK(request(ED_SMP_WRITE, a, n) == 11 && host_wire[9] == 0 && host_writes == 1);
    CHECK(host_erase_count == 2 && host_erase_offsets[0] == FL_STOCKTAG_LO &&
          host_erase_offsets[1] == FL_SMP_LO + SMP_USER_SIZE + 4096 && !host_mutation_unsafe);
    /* The same production header validation and scan publish a completed owned sample. */
    a[1] = 0; a[2] = 4; a[3] = 0; n = 4 + pack7(data, sizeof data, a + 4);
    CHECK(request(ED_SMP_WRITE, a, n) == 11 && host_wire[9] == 0);
    h.zone[0].n = 512; h.zone[0].le = 511; h.zone[0].rate = 65536; h.zone[0].hi = 127;
    n = 1 + pack7((const uint8_t *)&h, sizeof h, a + 1);
    CHECK(request(ED_SMP_END, a, n) == 8 && host_wire[6] == 0 && usr_nz[1] == 1 && !host_mutation_unsafe);
    len = 0; CHECK(ed_bk_object(33, &len) == host_samples[1] && len == SMP_USER_DATA + sizeof data);
    puts("SMK editor sample ownership, unavailable USR3, backup and stock marker gates passed");
    return 0;
}
