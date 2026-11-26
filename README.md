# Async FIFO & CDC Sign-off Flow

[![ci](https://github.com/botirkhan/async-fifo-cdc-signoff/actions/workflows/ci.yml/badge.svg)](https://github.com/botirkhan/async-fifo-cdc-signoff/actions/workflows/ci.yml)

This repo contains a parameterized dual-clock FIFO with Gray-code pointers and 2-flop synchronizers, plus a scripted sign-off flow:

- **Verilator lint** with `-Wall` on three parameter sets
- a **CDC structure check** that runs on the Yosys netlist
- **SymbiYosys formal** with free-running, unrelated clocks
- **Yosys RTL-vs-netlist equivalence (LEC)**
- a **constrained-random testbench** that sweeps 7 clock ratios with metastability injection in the synchronizers

Six bugs are injected on purpose to show which check catches each one.

## Results

### Simulation (Vivado xsim 2026.1, metastability injection on)

There are 7 clock configs × 4 seeds and 4,000 writes per run ([full table](docs/test_results.md)).

| | |
|---|---|
| Runs passing | **28 / 28** |
| Reads checked against the scoreboard | **112,000**, 0 mismatches |
| Overflow / underflow / SVA failures | 0 / 0 / 0 |
| Functional coverage | **21/21 bins in every run**: each occupancy level 0–16, full, re-empty, write blocked by full, read blocked by empty |
| Clock ratios | 1:1 aligned, 1:1 skewed, 1:1.013 (beat), 3.7× and 11× in both directions (45–500 MHz) |

### Sign-off in CI (GitHub Actions, OSS CAD Suite)

| Step | Clean design | Bugs it must catch |
|---|---|---|
| Verilator lint `-Wall` | **0 warnings** on 3 parameter sets (16×16, 4×4, 64×32) | — |
| CDC structure check | **0 violations**: 2 crossings, both 5-bit Gray pointers into 2-flop synchronizers | `BUG_BIN_CROSS` → 2× CDC-BUS; `BUG_ONE_FLOP` → 3× CDC-1FF |
| Formal BMC (`abc bmc3`, free-running clocks, metastability injection) | **PASS to depth 40** (368 s) | 4/4 fail with counterexamples (steps 2–10) |
| Formal cover (non-vacuity) | 3/3 reached: full at step 8, fill-then-drain at step 23, pointer wrap at step 30 | — |
| Yosys LEC, RTL vs synthesized netlist | **381/381** equivalence points proven (237 flops) | netlist from `BUG_FULL_MSB` RTL → 1 unproven point (`wfull_next`) |
| Verilator `--timing` sim, 3 clock ratios | 3/3 pass, 9,000 reads checked, 21/21 bins | 4/4 fail |

Formal is a **bounded** proof (40 solver steps with both clocks free). An unbounded `abc pdr` proof is wired up (`--task prove`), but it did not converge within 35 minutes on a CI runner, so this README doesn't claim it.

## The design

`rtl/async_fifo.sv` (`DATA_W`, `ADDR_W`; depth = 2^ADDR_W, 16 by default).

- Each side keeps a binary pointer (which addresses the RAM) and a Gray copy. The pointers are `ADDR_W+1` bits, and the extra MSB tells full from empty.
- Only the **Gray** pointers cross clock domains, each through `sync_2ff` (two `ASYNC_REG` flops).
- `wr_full` is true when the next write Gray pointer equals the synchronized read pointer with its two MSBs inverted.
- `rd_empty` is true when the next read Gray pointer equals the synchronized write pointer.
- Both flags are registered and conservative: a flag can stay up a few cycles late, but it is never wrong in the unsafe direction.
- `rdata` is first-word-fall-through: it shows the head entry whenever `!rd_empty`.

## The sign-off flow

| Step | Tool | What it checks |
|---|---|---|
| Lint | Verilator `--lint-only -Wall` | default, 4×4 and 64×32 parameter sets must give 0 warnings |
| CDC | Yosys netlist + `scripts/signoff.py` | (1) no logic between the source flop and synchronizer stage 1; (2) stage 1 drives exactly one stage-2 flop; (3) multi-bit crossings only from registers listed in `cdc/gray_registers.txt` |
| Formal | SymbiYosys, `multiclock on`, `abc bmc3` (clean) / `smtbmc yices` (mutants) | no overflow/underflow (P1), empty safe (P2), full safe (P3), data out in order (P4, any write index), Gray pointers change ≤1 bit; covers prove the bound reaches full, drain and pointer wrap |
| LEC | Yosys `synth` → netlist → `equiv_make/equiv_simple/equiv_induct` | the gate-level netlist matches the RTL |
| Sim | xsim (local), Verilator `--timing` (CI) | queue scoreboard, overflow/underflow from true occupancy, drain check, 6 SVA properties, coverage bins |

**Metastability injection** (`META_INJECT`): in sim, any bit that changed since the last destination edge may randomly resolve to its old value. In formal, the solver picks how each such bit resolves. So the clean design is checked against every way a synchronizer can resolve, not just the ideal one.

## How the checks split the bugs

| Injected bug | What it breaks | Sim (xsim, 7 runs) | Formal BMC | CDC check | LEC |
|---|---|---|---|---|---|
| `BUG_WR_WHEN_FULL` | write not gated by full, overwrites unread data | **7/7** (scoreboard, overflow, SVA A3) | **fail**, P3 full-safe, step 10 | — | — |
| `BUG_RD_WHEN_EMPTY` | read not gated by empty, passes the write pointer | **7/7** (scoreboard, underflow, SVA A4) | **fail**, P4 data-in-order, step 2 | — | — |
| `BUG_FULL_MSB` | full compare inverts only the MSB (binary-style compare on Gray) | **7/7** (scoreboard, overflow) | **fail**, P3 full-safe, step 8 | — | **fail**, `wfull_next` unproven |
| `BUG_GRAY_CONV` | wrong binary-to-Gray conversion (`b ^ b>>2`) | **7/7** (scoreboard, SVA A1) | **fail**, F_WGRAY_ONEHOT0, step 4 | — | — |
| `BUG_BIN_CROSS` | binary pointers cross clock domains | 0/7 (not visible) | not run | **fail**, CDC-BUS ×2 | — |
| `BUG_ONE_FLOP` | single-flop synchronizer | 0/7 (not visible) | not run | **fail**, CDC-1FF ×3 | — |

Every injected bug is caught by at least one check, **6/6**. Full sim details: [docs/mutation_results.md](docs/mutation_results.md).

`BUG_BIN_CROSS` and `BUG_ONE_FLOP` show why structural CDC checks are needed. Even with metastability injection, a binary-pointer glitch lasts only one destination cycle, and a FIFO pointer moves by one per cycle, so neither the testbench nor the bounded formal run can see a failure. The CDC script flags both bugs straight from the netlist.

## Running it

```
run_sim.bat                          # Windows + Vivado: 28 clean runs + mutants, writes docs/ and reports/
python3 scripts/signoff.py lint      # Linux + OSS CAD Suite
python3 scripts/signoff.py cdc    --variant clean
python3 scripts/signoff.py formal --variant clean --task bmc
python3 scripts/signoff.py lec    --variant clean
python3 scripts/signoff.py sim    --variant clean
```

## Files

```
rtl/async_fifo.sv       FIFO (+ injected bugs under `ifdef BUG_*, formal Gray checks under `ifdef FORMAL)
rtl/sync_2ff.sv         2-flop synchronizer (+ META_INJECT model)
tb/tb_fifo.sv           constrained-random self-checking testbench
tb/fifo_sva.sv          SVA properties A1-A6
formal/fifo_formal.sv   formal harness: free clocks, reset assumptions, shadow counters, P1-P4, covers
cdc/gray_registers.txt  registers allowed to cross as multi-bit buses
scripts/run_regression.py   xsim regression + mutation testing -> docs/, reports/junit.xml
scripts/signoff.py          lint / cdc / lec / formal / sim steps used by CI
ci/ci.yml               GitHub Actions workflow (copied to .github/workflows by push.bat)
```

MIT License.
