#!/bin/sh
# SPDX-License-Identifier: GPL-3.0-only
# Actual emulator bridge partition suite shared by local and focused CI runners.
# Generated assets are prerequisites; CI passes --require-wasm to prohibit skips.
set -e
cd "$(dirname "$0")/../.."
python3 tools/profile.py --check
case "${1:-}" in
    '') required=0 ;;
    --require-wasm) required=1 ;;
    *) echo "usage: partition_test.sh [--require-wasm]" >&2; exit 2 ;;
esac
[ -f build/gen/felucca_tables.h ] || { echo "emu partition: missing build/gen" >&2; exit 1; }
command -v node >/dev/null 2>&1 || { echo "emu partition: missing node" >&2; exit 1; }
if [ "$required" = 1 ] && ! command -v emcc >/dev/null 2>&1; then
    echo "emu partition: missing required emcc" >&2
    exit 1
fi
mkdir -p build/host
# CC may include flags, as in tests/run_tests.sh; the fixture always disables FMA.
# shellcheck disable=SC2086
${CC:-cc} -O2 -ffp-contract=off -std=gnu99 -w -Ibuild/gen -Ifirmware/src \
    -o build/host/emu_partition_native web/emu/partition_test.c -lm
if command -v emcc >/dev/null 2>&1; then
    # Same Wasm options as web/emu/build.sh; test exports stay out of the page build.
    # shellcheck disable=SC2086
    emcc ${EMU_OPT:--O2} -ffp-contract=off -std=gnu99 -w ${EMU_CFLAGS:-} \
        -Ibuild/gen -Ifirmware/src --no-entry -sSTANDALONE_WASM -sSTACK_SIZE=1048576 \
        -sINITIAL_MEMORY=33554432 -sFILESYSTEM=0 -o build/host/emu_partition.wasm web/emu/partition_test.c
    node web/emu/partition_test.mjs build/host/emu_partition_native build/host/emu_partition.wasm
    if [ -n "${FELUCCA_COVERAGE_CHILD:-}" ]; then
        python3 tools/test_coverage.py partition-result passed
    fi
else
    node web/emu/partition_test.mjs build/host/emu_partition_native
    if [ -n "${FELUCCA_COVERAGE_CHILD:-}" ]; then
        python3 tools/test_coverage.py partition-result skipped
    fi
fi
