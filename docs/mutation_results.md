# Mutation results (simulation)

Generated 2026-11-26 13:54. Each bug is compiled in with a define and run on all 7 clock configs x 1 seed(s). Killed = runs that failed.

| Injected bug | What it breaks | Killed | Caught by | Assertions that fired |
|---|---|:-:|---|---|
| `BUG_WR_WHEN_FULL` | write enable not gated by full, so unread data is overwritten | 7/7 | SVA, drain check, overflow check, scoreboard | A3 |
| `BUG_RD_WHEN_EMPTY` | read enable not gated by empty, so the read pointer passes the write pointer | 7/7 | SVA, drain check, overflow check, scoreboard, underflow check | A4 |
| `BUG_FULL_MSB` | full compare inverts only the MSB (binary-style compare on a Gray pointer) | 7/7 | drain check, overflow check, scoreboard | - |
| `BUG_GRAY_CONV` | wrong binary-to-Gray conversion on the write pointer (b ^ b>>2) | 7/7 | SVA, drain check, overflow check, scoreboard, underflow check | A1 |
| `BUG_BIN_CROSS` | binary pointers cross the clock domains instead of Gray (a metastable glitch lasts one cycle, so sim cannot see it) | 0/7 | - (not visible to RTL sim; see CDC check) | - |
| `BUG_ONE_FLOP` | only one synchronizer stage (functionally identical in RTL sim) | 0/7 | - (not visible to RTL sim; see CDC check) | - |

**4/4 simulation-visible bugs caught.**
