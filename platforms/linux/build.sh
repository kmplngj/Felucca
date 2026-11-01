#!/bin/sh
# SPDX-License-Identifier: GPL-3.0-only
# Copyright (C) 2026 Leo Kuroshita (@kurogedelic), Hügelton Instruments
# Felucca on a desktop with SDL2 (platforms/linux/felucca_sdl.c): Linux, and macOS for development.
#   platforms/linux/build.sh   ->  build/linux/felucca
# Run after one ./build.sh (build/gen: the tables, the fonts, the CC0 samples). Needs a C compiler and SDL2
# (sdl2-config; Debian / Ubuntu: libsdl2-dev), and for MIDI ALSA (libasound2-dev) or, on macOS, CoreMIDI.
# -ffp-contract=off as the host build. LINUX_OPT replaces -O2, LINUX_CFLAGS adds flags.
# LINUX_OUT overrides build/linux; SDL2_CONFIG overrides sdl2-config (e.g. a local installation).
set -e
cd "$(dirname "$0")/../.."
[ -f build/gen/felucca_tables.h ] || { echo "linux: run ./build.sh once first (build/gen)"; exit 1; }
python3 tools/profile.py --check
SDL2_CONFIG=${SDL2_CONFIG:-sdl2-config}
command -v "$SDL2_CONFIG" >/dev/null 2>&1 || { echo "linux: no $SDL2_CONFIG (SDL2)"; exit 1; }
VERSION=$(sed -n 's/^#define FELUCCA_VERSION "\([^"]*\)".*/\1/p' firmware/src/felucca.c | head -n 1)
# MIDI (platforms/linux/midi.c): CoreMIDI on macOS, ALSA where pkg-config finds it (libasound2-dev), else none
case "$(uname -s)" in
Darwin) MIDI="-framework CoreMIDI -framework CoreFoundation" ;;
*) if pkg-config --exists alsa 2>/dev/null; then MIDI="-DFELUCCA_ALSA $(pkg-config --cflags --libs alsa)"; else MIDI=""; echo "linux: no ALSA (libasound2-dev): no MIDI"; fi ;;
esac
LINUX_OUT=${LINUX_OUT:-build/linux}
mkdir -p "$LINUX_OUT"
# shellcheck disable=SC2046,SC2086
${CC:-cc} ${LINUX_OPT:--O2} -ffp-contract=off -std=gnu99 -w ${LINUX_CFLAGS:-} \
    "-DFELUCCA_VERSION=\"$VERSION\"" -Ibuild/gen -Ifirmware/src -Ifirmware/hal \
    $("$SDL2_CONFIG" --cflags) -o "$LINUX_OUT/felucca" platforms/linux/felucca_sdl.c $("$SDL2_CONFIG" --libs) $MIDI -lm
echo "linux: $LINUX_OUT/felucca ($VERSION)"
