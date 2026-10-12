<!-- SPDX-License-Identifier: GPL-3.0-only -->
# Target-budget fixtures

Run `python3 tests/target_budget_test.py` from the repository root. The host runner
also executes it, even without a target disassembly. It uses only the Python
standard library, loads the production estimator, and invokes its real CLI against
temporary inputs under ignored `build/`. `BUDGET_UPDATE` inherited from the host
runner is cleared for each subprocess; update tests only rewrite temporary files.

`loops.dis` is original synthetic objdump-format text. Its byte columns are parser
placeholders, not assembled instructions; function names select existing `FUNCS`
entries and do not represent those functions' real firmware costs. Expected results
are literal observations of the current heuristic, not execution-cycle claims:

| Function | Case | Loop instructions | Weighted cost |
| --- | --- | ---: | ---: |
| `analog_render` | Simple loop | 2 | 2 |
| `phase_render` | Nested loops | 4 | 10 |
| `lofi_render` | Sibling loops | 4 | 4 |
| `sample_render` | Split back edges to one head; farthest end wins | 4 | 4 |
| `formant_render` | Acyclic backward alternative path | 4 | 4 |
| `trio_render` | Call inside a loop; callee cost not added | 3 | 3 |
| `trio_pass` | Separately counted callee with a divide | 3 | 11 |
| `wheel_render` | One divide inside, one outside | 3 | 11 |
| `grain_render` | Ordinary instruction inside a loop | 2 | 2 |
| `grain_block` | Five nested spans, depth capped at four | 10 | 298 |
| `mod_begin` | Call and divide outside loops | 0 | 0 |

The parser fixture also checks local labels, excluded jump-table data, malformed
instruction lines, untracked function boundaries and empty tracked functions.
CLI fixtures cover the 10% boundary, lower-cost notes, required/optional functions,
explicit and fallback budgets, default paths, skip behavior and isolated updates.
They preserve current input limitations: missing budget entries/files warn and pass;
numeric extra entries are ignored; single-word lines are skipped; nonnumeric values
fail with an explicit diagnostic, including on extra entries and before an update. A nonempty
`BUDGET_UPDATE` value, including `0`, rewrites the file. Updates omit optional
functions, bypass over-budget checks, and still fail for missing required functions.

Incomplete instruction rows in tracked functions fail before any budget update: address
rows without byte columns, empty instruction text and explicit objdump undecoded
markers (`.word`, `(bad)`, `unknown`, `unknown_instruction`). This prevents an
undecoded back edge from silently turning a loop into a zero-cost success. The
check recognizes these output markers, not the complete pi32v2 ISA; it cannot
prove the semantic accuracy of an otherwise decoded instruction or its timing.
Negative/nonnumeric budgets fail cleanly, with no traceback or file rewrite.
A valid loop-free function can update/read a zero budget; subsequent nonzero cost
fails explicitly without attempting a percentage division by zero.
Missing budgets/disassembly retain the documented existing warning/skip policy;
CI policy remains issue #35's scope.

`real_pi32v2.dis` retains the actual `dv_out` instruction bytes from the unchanged
firmware tree of main `19a7081`, built with JieLi Clang 4.0.1, `-Os` and selective
minsize. Its literal expected result is 40 instructions, 35 loop instructions,
no divides/calls in loops, cost 35. This tests real objdump syntax independently
of the synthetic byte placeholders. All 62 current `FUNCS` entries were compared
on the same complete target disassembly; their costs are unchanged. The separate fresh MACRO build at `c2d91aa` compares all 79 entries in that
configuration, including MACRO and Braids helpers; their results are also unchanged.
See [the complete per-function report](cost-comparison.md).

## Known approximation and possible future accounting

Every recognized backward branch creates an inclusive address span, whether or not
it closes a control-flow cycle. Overlapping spans contribute nesting even when they
belong to alternative paths. Instructions outside spans receive no cost; calls count
as one instruction without adding their callees; division recognition depends on
the textual register form. The fixtures deliberately retain these approximations.

In `formant_render`, entry `500` either falls through to `502` or jumps to `506`.
The alternative path `506 -> 508 -> 502` then follows `504 -> 50a` to return.
There is no cycle, yet the heuristic counts the span `502..508` as a loop. This is
a reduced example of the layout artifact investigated in issue #7: an audio-IRQ
alternative output path branched backward across intervening mixer instructions
without executing that mixer again. The existing gate rejected that experiment;
these fixtures do not authorize accepting it or rewriting its budget.

A control-flow-aware estimator could build basic blocks and predecessor/successor
edges, distinguish a numerical backward branch from a natural-loop back edge whose
target dominates its source, and count actual loop bodies rather than address spans.
That would exclude this acyclic example. It still needs explicit handling of jump
tables, indirect branches, irreducible cycles, nesting and calls; dominance alone
does not establish iteration counts or hardware timing.

Such accounting cannot silently replace the current counts. Before any estimator
change, compare old/new results for **all `FUNCS`** on the same fresh target builds,
review each changed function and coverage gap, and separately review any proposed
budget changes. Host regressions and real-device deadlines remain independent
evidence. The input-rejection changes preserve `FUNCS`, weights, tolerance, valid-input costs
and checked-in budget baselines. No control-flow accounting change is selected.
