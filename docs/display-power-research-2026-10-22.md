<!-- SPDX-License-Identifier: GPL-3.0-only -->
# FM-1 display power and a second dark stage — research, 2026-10-22

## Finding and scope

No inspected implementation demonstrates a physically extinguished FM-1 LCD
backlight **and** normal panel wake with the shared PA2 control disabled. Two
independent projects report that disabling PA2 also prevents key detection.
However, M-VAVE's own current source initializes display brightness through
`0x51=255` while keeping PA2 enabled. That is a stronger same-device lead for a
controller-only experiment than the generic controller datasheet alone; it is
not evidence that `0x51=0` extinguishes this backlight. [U-old] [U-fix] [C-hal]
[S-measurement] [M-lcd] [M-hal]

The user's clarified proposal is a second timed stage that makes **the LCD image,
its physical backlight and every panel LED completely dark**, with no heartbeat.
Audio, sequencing and MIDI should continue. **No CPU sleep is requested.** Both
thresholds are total time since the same last qualifying interaction: stage 2 is
at `last_activity + T2`, not `stage_1_started + T2`. Durations, qualifying activity
and wake policy remain product decisions; this report does not implement them.
The companion [UX proposal](display-power-ux-2026-10-22.md) records those choices.

This is online research plus source inspection. It refreshes default-branch
tips and examines seven firmware repositories, including upstream and the official
firmware, rather than treating inherited comments or a firmware's general release
status as physical proof. Existing local sources were used only as context. No
firmware, issue, PR, scan ledger or device was changed. The report checkout is
`d9c307265f6012d4df4b74128bb038580956f595`.

## Keep the five mechanisms separate

| Mechanism | What it controls | What the evidence does and does not establish |
| --- | --- | --- |
| Black pixels / LCD display commands | Image, panel scanning and controller sleep | Upstream uses `DISPOFF`/`SLPIN`; ChoralRoot instead draws black once. Neither current implementation claims to extinguish the physical backlight. [U-current] [C-ui] |
| Controller brightness/backlight outputs | Optional controller outputs associated with LCD illumination | ST7789V exposes these controls, and M-VAVE sends a brightness command. The FM-1 output wiring and effective zero-brightness behavior remain unverified. [D] [M-lcd] |
| PA2 | Shared hardware enable affecting illumination and the matrix/595 chain | PA2 low permits operation; high prevents measured key detection and is reported to extinguish LEDs/backlight. Exact transistor/net topology is not established by the inspected material. [C-hal] [S-measurement] |
| Normal LED maps | Individual button/key LED levels | Software can blank maps without disabling matrix scanning; all normal/dim/mid/breath maps and animation ownership must be covered. This does not switch off LCD backlight. [F-leds] |
| Input scanner | Column selection, row sampling, debounce and encoder decoding | The scanner requires the enabled matrix. Running its code with PA2 high cannot recover contacts that electrically read open. [S-measurement] [M-input] |

Upstream calls PA2 the 595 `/OE`; ChoralRoot describes a likely shared supply
enable. These explanations agree about observed behavior but are not an electrical
schematic. Do not assume an instantaneous `/OE` edge, a measured rail-rise time,
or that every LCD supply is disconnected. [U-fix] [C-hal] [C-boot]

## Pinned source matrix

Default-branch tips were read from GitHub on 2026-10-22. Links below identify the
exact inspected content; absence findings apply to these LCD/HAL paths and the
scoped code searches, not to every possible firmware or hardware revision.

| Project and inspected tip | Source behavior / relevant history | Evidence level |
| --- | --- | --- |
| **hugelton/Felucca** `63f88ec18b71c6ed4371d03d6f04dd93f4193ad3` | Current `lcd.c:133–157` sleeps/wakes the controller and leaves PA2 enabled. Version 1.1.5 `276f72a4…` switched PA2 off; 1.1.5.1 `213df5a0…` removed that operation. [U-current] [U-old] [U-fix] | Actual current and historical implementation; maintainer confirms the responsive-screen fix. [U-comment] |
| **m-vave/fm1_open** `4c7496daac04a95ff10d1afdcc8f9ead2dbabc41` | `app/board/lcd.inc:75–103` sends `0x51,1,255`; `fm1_lcd_hw.h:15` drives PA2 low. Input uses SPI2 column DMA and row sampling, rather than an independent wake input. No backlight-off path is exposed in these inspected board files. [M-lcd] [M-hal] [M-input] | Manufacturer's actual application/board source; no measured zero-brightness or separate backlight wiring result. The LCD file's history attributes the table to initial V12 commit `3be7fbdb…`. [M-history] |
| **Quixotic7/ChoralRootFM1** `7d97982a7db3dad2da456a3e4d4478548b6571d9` | Current FM-1 HAL drives PA2 low and never raises it in normal operation. UI draws black after ten minutes while LEDs/MIDI/UI continue. Earlier `c33647b6…` used `DISPOFF` + PA2 off; `74c168c0…` removed it after the unit became unresponsive. [C-hal] [C-ui] [C-old] [C-fix] | Author reports repeated device observations, computer SysEx recovery, and later cold-boot key/LED checks. Distinguish these from its emulator model. [C-boot] [C-release] |
| **isod89/sloop-fm1** `ec9e53721cc576816a5750220391f2d0217c01cb` | Inspected LCD driver initializes/display-on, without a separate backlight-off path. Current recovery code enables PA2 before its early scan; this changed in `beab3f62…`. Its LIGHTS/background LED maps concern key/button illumination. [S-lcd] [S-hal] [S-recovery] [S-history] | Independent hardware key-read measurement in issue #167, plus implemented recovery correction. This is not a qualified dark-while-playing mode. [S-measurement] |
| **zednaked/jangada** `249eb434b81050bf0b9129185234d58ff2dbbba3` | Inspected LCD source initializes and displays; HAL enables PA2. No separate LCD-backlight-off implementation in these paths; LCD history remains inherited 0.9/0.8 source. [J-lcd] [J-hal] [J-history] | Implementation reference; no relevant independent physical off/wake result found. |
| **zvenson/dinghy** `d44df7db09b98ccad2f1233b8f83f5f09c04829e` | Minimal firmware's LCD/HAL initialize display and PA2; no independent backlight-off mechanism in those paths. LCD introduced in `beb829f1…`. [G-lcd] [G-hal] [G-history] | Minimal-platform reference, not independent evidence for backlight shutdown. |
| **oscillr/DUELL** `0bd7f904a18efd20fd6092a8bc645945c3fedf74` | `felucca-base/firmware/src/lcd.c:133–157` retains upstream's corrected SCREEN OFF and PA2-on wake behavior. LCD entered that tree in `1df6207e…`. [V-lcd] [V-hal] [V-history] | Same-hardware implementation, substantially inherited; not an additional independent experiment. |

The first-party Groove OS manual separately says its brightness row was removed
in 1.2 because the backlight is always wired on. This is useful product experience,
but the inspected page supplies no schematic, command trace or measurement; it
does not establish that every controller-only route is impossible. [GO]

## What the history actually proves

Upstream 1.1.5 calls `fm1_lcd_backlight(s == 2u)` in its sleep/wake path. The
1.1.5.1 source removes that call from normal sleep, explicitly retaining the
backlight so panel input can wake the screen. The maintainer's issue #157 reply
confirms that 1.1.5 could remain dark until switched off. This was a deliberate
rollback of a failed shared-enable strategy, not a discovered independent
backlight switch. Current upstream keeps that correction. [U-old] [U-fix]
[U-comment] [U-current]

ChoralRoot provides a second, concrete sequence: historical `lcd_power(0)` sends
`DISPOFF` and disables PA2; its author reports that no key/button/encoder woke the
unit, while a computer screen-on request restored it. The fix eliminates this
normal PA2-high path and uses a black frame. Its boot investigation later reports
successful OCT− detection and visible LEDs after enabling PA2. [C-boot-result] The chosen
30 ms startup allowance was conservative; the document explicitly says the actual
required rise time is unknown. [C-old] [C-fix] [C-ui] [C-boot]

SLOOP issue #167 adds an independent test from RAM, with PLAY/REC held and the
normal column words: PA2 output-low reads closed; output-high or undriven reads
open. The current recovery code now turns PA2 on before scanning. This directly
supports the coupling and removes ambiguity from comments that call the signal
only “backlight.” It still does not identify the exact electrical net. [S-measurement]
[S-recovery]

## Controller-only route: strongest lead, still a hardware gate

The ST7789V datasheet defines `0x51` brightness, `0x53` control and optional
LED_PWM/LED_EN pads. Zero brightness is a module-dependent minimum, whereas
WRCTRLD's BL bit requests backlight off. BCTRL is bit 5, DD bit 3 and BL bit 2;
`0x20` enables manual control with BL off and `0x24` enables BL. Unused output
pads may be left open. [D]

M-VAVE already sends `0x51=255`, with no `0x53` operation in its inspected
initialization table. WRCTRLD's documented reset value is zero, with BCTRL disabled;
the brightness write might therefore be generic or unused initialization rather
than functioning brightness control. Test the actual FM-1 behavior rather than assuming
that the controller variant, initialization defaults or optional pad wiring match
one datasheet. Neither the manufacturer source nor the surveyed forks demonstrates
the result of zero brightness. A register value or emulator screenshot cannot
prove that the physical backlight LEDs have lost illumination. [M-lcd] [M-hal] [D]

Existing draft [PR #549], head `4c11bcbb8e9e944054ce3be87084215f73943eb0`,
already isolates a `0x53/0x51` probe that keeps PA2/scanning enabled. It remains
unmerged and its handoff explicitly records hardware validation pending. Reuse
that bounded experiment before designing a second implementation. This research
does not rerun its builds or convert its host/target evidence into a physical
backlight result. [P]

If the probe physically succeeds, stage 2 could blank every LED map and stop
animation ownership while independently extinguishing the LCD light, keeping
normal input scanning available. If it fails, the documented fallback is a
different wake contract, not a silent return to the old PA2-off behavior.
These are design inferences from the mechanisms above, not implemented features.

## A PA2-high second stage: feasible hypothesis with different wake behavior

Turning PA2 high is reported to extinguish the shared illumination, but loses
ordinary panel input. A deliberate second stage could keep CPU/audio/MIDI
services running and restore PA2 from an independent event. This is electrically
and architecturally plausible, with historical computer recovery as partial
evidence, but none of the inspected projects qualifies the complete proposed
mode under sustained audio/MIDI load. [C-hal] [C-boot] [C-release] [F-timer]

| Wake source | With PA2 kept low / controller light off | With PA2 kept high continuously |
| --- | --- | --- |
| Piano key, PLAY/HOME/other buttons | Matrix remains available; depends on controller-probe success and existing gesture policy | Measured contacts read open. Not a usable wake source without re-enabling the matrix. [S-measurement] |
| Encoders | Existing scanner can decode them | Same gated matrix/595 path. A turn cannot be promised to wake. [C-hal] [M-input] |
| USB MIDI accepted note-on | Existing +MIDI policy can request wake; note still plays | Candidate independent event if USB/CPU/timers remain running; needs a new PA2 restoration path and real qualification. Existing PANEL policy ignores these notes for wake. [F-midi] [F-wake] |
| TRS MIDI accepted note-on | Existing +MIDI path | Candidate independent UART event; keep TIMER5 UART polling and MIDI routing alive. Not validated with PA2 high here. [F-timer] [F-midi] |
| Explicit host/USB command | Can be designed or use the existing experiment's controls | ChoralRoot reports computer-command recovery historically. That is its protocol, not proof of an existing Felucca deep-dark wake command. [C-boot] |
| USB cable/clock/ordinary editor traffic | Not current qualifying wake events | Do not promise wake merely from attachment, clock or traffic. Felucca notes that apparent SOF status can continue with a cable absent; an explicit event/policy is needed. [F-usb] [F-wake] |
| Running timer | New policy could restore on a scheduled event | CPU is not asleep, so software can schedule re-enable; this would be a new implementation, and periodic restoration contradicts indefinite continuous darkness. [F-timer] |
| MASTER pot / independent ADC | Presently excluded from screen activity | PB6 is a separately read ADC input, suggesting an optional wake candidate. Availability with PA2 high and a noise-resistant gesture threshold are unmeasured; current firmware does not implement this wake policy. [F-adc] [F-master] [F-wake] |
| Separate physical GPIO wake key | No special route needed for ordinary panel use | No independent existing panel wake key was identified. Do not invent a direct GPIO interrupt behind the disabled 595 chain. [M-input] [C-hal] |
| Power cycle | Restarts firmware | Reported way out of the historical dark state, but it interrupts audio and is a restart, not continuous musical resume. [C-release] |

Felucca's TIMER5 handler owns more than input scanning: it advances time, polls
TRS MIDI and services USB, including USB audio during rendering. A future deep-dark
mode must not disable TIMER5 or suppress those services when suppressing matrix
work. The audio render interrupt and main loop must also keep running. These
source responsibilities establish what must be preserved, not measured
PA2-high reliability. [F-timer]

Entry/exit also needs explicit state ownership: no held panel gesture may become a
stuck note or synthetic release, encoder history must be reseeded after missing
scan phases, and wake input must follow the chosen consume/act contract. All LED
writers, including ISR-driven animations, need to respect a fully dark owner.
Otherwise simply clearing current maps can be overwritten on the next animation
frame. These are design obligations inferred from the actual scanner, keyboard
and LED owners. [F-input] [F-keys] [F-leds]

## Why brief re-enable polling is not yet a solution

No inspected implementation provides a measured, qualified PA2 duty-cycle scheme
that preserves panel wake while the physical light stays continuously off.
ChoralRoot's boot investigation explicitly leaves rail startup time unknown.
Consequently, “enable for a few microseconds and sample” is not justified by the
available evidence. [C-boot]

A polling experiment would have to establish the minimum enable/settle/scan
window, any lost 595 state, debounce recovery and both encoder directions. It
would also need to measure the backlight pulse: enabling the shared line can
illuminate the backlight even with every normal LED map zero. A blackout lasting
between polls can miss a short tap or encoder transitions. Holding PA2 enabled
longer to avoid those losses can instead cause visible glow/flicker. These are
testable consequences, not measured timings or a recommended implementation.

The exact topology also determines whether repeated switching affects controller
state or creates unintended powering through signal pins. A schematic/net trace
or measured supply waveforms are needed before treating the signal as a simple
logic `/OE`. Do not use the 30 ms boot allowance as a measured runtime minimum.

## Decision-ready next steps

1. **First resolve the independent backlight gate.** Observe the exact #549
   artifact on an FM-1, comparing physical glow with PA2/scanning unchanged.
   Test SCREEN alone so preserved LEDs make a shared-enable failure obvious.
   Success must include repeated panel/MIDI wake, stable brightness and audio;
   failed or unchanged illumination stays a failed/unknown probe.
2. **Keep the two timer semantics independent of the electrical choice.** One
   activity timestamp drives both thresholds; stage 2 means no heartbeat or
   remaining LED glow. Do not add the first-stage delay to the second threshold.
   Validate order/disabled-value semantics separately in the UX proposal.
3. **If controller-only off fails, choose the wake contract before coding.**
   PA2-high continuous darkness requires an external or independently validated
   wake route. It cannot honestly advertise ordinary button/encoder wake from
   the evidence available. A polling variant requires its own physical experiment
   and may not satisfy continuous darkness.
4. **Qualify the chosen mode as a musical mode.** Keep audio/MIDI/timers active,
   compare mixed-load audio and USB/TRS behavior, verify held-note/encoder reset,
   repeated wake and crash/update restoration. Record exact artifact/unit and
   distinguish a source hypothesis from device results. No CPU-sleep, battery
   life or power-saving claim follows from this research.

No implementation was made. The remaining gate is physical controller/wiring
evidence and an agreed wake contract; the first/second threshold values do not
resolve that hardware constraint.

## Research validation and documentation assessment

Inspected live pinned sources, selected path histories and primary hardware
reports; verified the local source paths behind the wake analysis. No build,
emulator run, hardware command, firmware-watch ledger update or external mutation
was performed. This is not an exhaustive all-firmware history scan or an
electrical teardown. General release/hardware-tested labels were not substituted
for a relevant backlight test.

README assessment: its current integration/experimentation overview already
covers this research stage; no implemented capability or installation guidance
changes, so no overview edit is needed. Changelog assessment: this is a proposal
and evidence report, with no merged behavior change, so no entry is warranted.

## Primary sources

[U-current]: https://github.com/hugelton/Felucca/blob/63f88ec18b71c6ed4371d03d6f04dd93f4193ad3/firmware/src/lcd.c#L133-L157
[U-old]: https://github.com/hugelton/Felucca/blob/276f72a4e6ea8a12499a7a6819aadf3165126755/firmware/src/lcd.c#L133-L161
[U-fix]: https://github.com/hugelton/Felucca/blob/213df5a094c24d10706fdffd7fb46678c6f07eeb/firmware/src/lcd.c#L133-L157
[U-comment]: https://github.com/hugelton/Felucca/issues/157#issuecomment-6054827008
[M-lcd]: https://github.com/m-vave/fm1_open/blob/4c7496daac04a95ff10d1afdcc8f9ead2dbabc41/app/board/lcd.inc#L75-L103
[M-hal]: https://github.com/m-vave/fm1_open/blob/4c7496daac04a95ff10d1afdcc8f9ead2dbabc41/app/board/fm1_lcd_hw.h#L13-L20
[M-input]: https://github.com/m-vave/fm1_open/blob/4c7496daac04a95ff10d1afdcc8f9ead2dbabc41/app/board/fm1_input.h#L47-L150
[M-history]: https://github.com/m-vave/fm1_open/commit/3be7fbdbd3bb137bacbd65d68412c210eb977870
[C-hal]: https://github.com/Quixotic7/ChoralRootFM1/blob/7d97982a7db3dad2da456a3e4d4478548b6571d9/firmware/hal/fm1_lcd_hw.h#L3-L14
[C-ui]: https://github.com/Quixotic7/ChoralRootFM1/blob/7d97982a7db3dad2da456a3e4d4478548b6571d9/firmware/src/cr_ui.c#L8249-L8293
[C-old]: https://github.com/Quixotic7/ChoralRootFM1/blob/c33647b692f71d952e42f618aea78b86d36516fb/firmware/src/lcd.c#L139-L152
[C-fix]: https://github.com/Quixotic7/ChoralRootFM1/commit/74c168c0de150830d3b157a120360493da58a4aa
[C-boot]: https://github.com/Quixotic7/ChoralRootFM1/blob/7d97982a7db3dad2da456a3e4d4478548b6571d9/docs/BOOT-SAFETY.md#L172-L224
[C-boot-result]: https://github.com/Quixotic7/ChoralRootFM1/blob/7d97982a7db3dad2da456a3e4d4478548b6571d9/docs/BOOT-SAFETY.md#L483-L489
[C-release]: https://github.com/Quixotic7/ChoralRootFM1/blob/7d97982a7db3dad2da456a3e4d4478548b6571d9/docs/releases/0.16.md#L1-L8
[S-lcd]: https://github.com/isod89/sloop-fm1/blob/ec9e53721cc576816a5750220391f2d0217c01cb/firmware/src/lcd.c
[S-hal]: https://github.com/isod89/sloop-fm1/blob/ec9e53721cc576816a5750220391f2d0217c01cb/firmware/hal/fm1_lcd_hw.h#L35-L46
[S-recovery]: https://github.com/isod89/sloop-fm1/blob/ec9e53721cc576816a5750220391f2d0217c01cb/firmware/src/recovery.c#L41-L57
[S-measurement]: https://github.com/isod89/sloop-fm1/issues/167
[S-history]: https://github.com/isod89/sloop-fm1/commit/beab3f62d04ff8defcc7b663505bd6bd6ad7836a
[J-lcd]: https://github.com/zednaked/jangada/blob/249eb434b81050bf0b9129185234d58ff2dbbba3/firmware/src/lcd.c
[J-hal]: https://github.com/zednaked/jangada/blob/249eb434b81050bf0b9129185234d58ff2dbbba3/firmware/hal/fm1_lcd_hw.h
[J-history]: https://github.com/zednaked/jangada/commits/249eb434b81050bf0b9129185234d58ff2dbbba3/firmware/src/lcd.c
[G-lcd]: https://github.com/zvenson/dinghy/blob/d44df7db09b98ccad2f1233b8f83f5f09c04829e/firmware/src/lcd.c
[G-hal]: https://github.com/zvenson/dinghy/blob/d44df7db09b98ccad2f1233b8f83f5f09c04829e/firmware/hal/fm1_lcd_hw.h
[G-history]: https://github.com/zvenson/dinghy/commit/beb829f146bd66fc3e8cf929080504898b1cd67a
[V-lcd]: https://github.com/oscillr/DUELL/blob/0bd7f904a18efd20fd6092a8bc645945c3fedf74/felucca-base/firmware/src/lcd.c#L133-L157
[V-hal]: https://github.com/oscillr/DUELL/blob/0bd7f904a18efd20fd6092a8bc645945c3fedf74/felucca-base/firmware/hal/fm1_lcd_hw.h
[V-history]: https://github.com/oscillr/DUELL/commit/1df6207e5a51a909223c9ccfb6280a97840490c0
[D]: https://newhavendisplay.com/content/datasheets/ST7789V.pdf
[GO]: https://www.groove-os.com/manual/settings#troubleshooting
[P]: https://github.com/kmplngj/Felucca/pull/549
[PR #549]: https://github.com/kmplngj/Felucca/pull/549
[F-leds]: https://github.com/kmplngj/Felucca/blob/d9c307265f6012d4df4b74128bb038580956f595/firmware/src/ui_input.c#L366-L461
[F-input]: https://github.com/kmplngj/Felucca/blob/d9c307265f6012d4df4b74128bb038580956f595/firmware/hal/fm1_input.h
[F-keys]: https://github.com/kmplngj/Felucca/blob/d9c307265f6012d4df4b74128bb038580956f595/firmware/src/seq.c#L811-L870
[F-timer]: https://github.com/kmplngj/Felucca/blob/d9c307265f6012d4df4b74128bb038580956f595/firmware/src/timer5.c#L14-L58
[F-midi]: https://github.com/kmplngj/Felucca/blob/d9c307265f6012d4df4b74128bb038580956f595/firmware/src/midi_control.c#L128-L147
[F-wake]: https://github.com/kmplngj/Felucca/blob/d9c307265f6012d4df4b74128bb038580956f595/firmware/src/ui.c#L238-L364
[F-usb]: https://github.com/kmplngj/Felucca/blob/d9c307265f6012d4df4b74128bb038580956f595/firmware/src/usb.c#L1252-L1280
[F-adc]: https://github.com/kmplngj/Felucca/blob/d9c307265f6012d4df4b74128bb038580956f595/firmware/hal/fm1_adc.h#L3-L16
[F-master]: https://github.com/kmplngj/Felucca/blob/d9c307265f6012d4df4b74128bb038580956f595/firmware/src/master.c
