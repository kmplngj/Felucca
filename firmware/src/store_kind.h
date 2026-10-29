/* SPDX-License-Identifier: GPL-3.0-only */
/* Stored record kinds (#310): the descriptor of every kind of record the editor's full backup (BACKUP_LIST / GET /
 * PUT) and the raw store export (STORE_LIST / STORE_GET, #456) handle. editor_backup.c holds the one table (SK_KINDS),
 * a row per kind, and its handlers only iterate it: they name no backup id, no storage type and no kind's own
 * function. Adding a persisted kind is one row here plus its codec (its stored layout, validation and install).
 * Include after storage.c (OBJ_*); like project_codec.h it defines no state and lives in felucca.c's single
 * translation unit (editor.c includes editor_backup.c). tests/store_kind_boundary_test.py checks the handlers'
 * side of that boundary; tests/backup_test.c checks the table against the wire contract (web/EDITOR_PROTOCOL.md).
 *
 * A row:
 *   bk, nbk      the backup ids bk .. bk + nbk - 1 (SK_NONE: none, the kind is not in the full backup)
 *   obj, nobj    the storage types (storage.c OBJ_*, the commit records' type) obj .. obj + nobj - 1, in step with
 *                the backup ids (backup id bk + k is stored as type obj + k); SK_NONE: not a commit-record object
 *   flags        SK_EMPTY   BACKUP_PUT takes 0 bytes (what 0 bytes means is the kind's install)
 *                SK_SAVE    the staged object is committed with st_save(obj + k) before install (A/B, rc 4 on failure)
 *                SK_EXT     listed by "BACKUP_LIST 1" only (#321), after the objects of 1.0.3
 *                SK_SCRATCH its export view is the shared staging RAM: a later project save / load makes GET stale (5)
 *   size, accepts   the stored lengths BACKUP_PUT begins with: accepts(n) when set, else n == size (+ 0 with SK_EMPTY)
 *   check        validate the whole staged object (and normalise it in place, *n its new length); the reply code:
 *                0 whole, 2 refused (4 when the kind needs flash it does not have). Nothing is written before it
 *   install      apply a checked object k (after st_save with SK_SAVE): RAM mirrors, runtime, its own flash path;
 *                the reply code. NULL: the kind is export only (BACKUP_PUT refuses it)
 *   view         the export (BACKUP_LIST / GET) of object k: its bytes and *n its length (0: none)
 *   crc, fill    a streamed export (read from flash a piece at a time): the CRC LIST gives and GET's piece reader
 *                (into ed_smp_buf; its reply code). NULL: the view's bytes are the object
 *   state        STORE_LIST's schema state of n > 0 intact stored bytes (ED_RAW_CURRENT / LEGACY / UNKNOWN), from
 *                their identification only. NULL when obj is SK_NONE */
#pragma once
#include <stdint.h>

#define SK_NONE 0xFFu
enum { SK_EMPTY = 1, SK_SAVE = 2, SK_EXT = 4, SK_SCRATCH = 8 };
enum { ED_RAW_EMPTY, ED_RAW_CURRENT, ED_RAW_LEGACY, ED_RAW_UNKNOWN, ED_RAW_DAMAGED };   /* STORE_LIST's state */

typedef struct {
    uint8_t bk, nbk, obj, nobj, flags;
    uint16_t size;
    int (*accepts)(uint32_t n);
    uint32_t (*check)(uint8_t *b, uint32_t *n);
    uint32_t (*install)(uint32_t k, const uint8_t *b, uint32_t n);
    const uint8_t *(*view)(uint32_t k, uint32_t *n);
    const uint32_t *crc;
    uint32_t (*fill)(uint32_t off, uint32_t n);
    uint32_t (*state)(const uint8_t *b, uint32_t n);
} store_kind_t;
