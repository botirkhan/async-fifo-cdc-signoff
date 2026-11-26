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

### Sign-off in CI

The lint, CDC, formal, LEC and Verilator jobs run on every push. See the Actions tab.

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
| Formal | SymbiYosys, `multiclock on`, yices | no overflow/underflow (P1), empty safe (P2), full safe (P3), data out in order (P4, any write index), Gray pointers change ≤1 bit; covers prove the bound reaches full, drain and pointer wrap |
| LEC | Yosys `synth` → netlist → `equiv_make/equiv_simple/equiv_induct` | the gate-level netlist matches the RTL |
| Sim | xsim (local), Verilator `--timing` (CI) | queue scoreboard, overflow/underflow from true occupancy, drain check, 6 SVA properties, coverage bins |

**Metastability injection** (`META_INJECT`): in sim, any bit that changed since the last destination edge may randomly resolve to its old value. In formal, the solver picks how each such bit resolves. So the clean design is checked against every way a synchronizer can resolve, not just the ideal one.

## How the checks split the bugs

See [docs/mutation_results.md](docs/mutation_results.md).

`BUG_BIN_CROSS` and `BUG_ONE_FLOP` show why structural CDC checks are needed. Even with metastability injection, a binary-pointer glitch lasts only one destination cycle, and a FIFO pointer moves by one per cycle, so neither the testbench nor the bounded formal run can see a failure. The CDC script flags both bugs straight from the netlist.

## Running it

```
run_sim.bat                          # Windows + Vivado: 28 clean runs + mutants, writes docs/ and reports/
python3 scripts/signoff.py lint      # Linux + OSS CAD Suite
python3 scripts/signoff.py cdc    --variant clean
python3 scripts/signoff.py formal --variant clean
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
