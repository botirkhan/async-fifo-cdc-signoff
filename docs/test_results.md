# Regression results (clean design)

Generated 2026-11-26 13:54 by `scripts/run_regression.py` on Vivado xsim with metastability injection on. 4000 writes per run.

| Clock config | wclk MHz | rclk MHz | Seed | Writes | Reads checked | Mismatches | Overflow | Underflow | SVA fails | Coverage bins | Full cycles | Empty cycles | Result |
|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|:--|
| 1to1_aligned | 100.0 | 100.0 | 1 | 4000 | 4000 | 0 | 0 | 0 | 0 | 21/21 | 3405 | 3028 | PASS |
| 1to1_aligned | 100.0 | 100.0 | 2 | 4000 | 4000 | 0 | 0 | 0 | 0 | 21/21 | 2162 | 3178 | PASS |
| 1to1_aligned | 100.0 | 100.0 | 3 | 4000 | 4000 | 0 | 0 | 0 | 0 | 21/21 | 2969 | 2914 | PASS |
| 1to1_aligned | 100.0 | 100.0 | 4 | 4000 | 4000 | 0 | 0 | 0 | 0 | 21/21 | 4469 | 4375 | PASS |
| 1to1_skewed | 100.0 | 100.0 | 1 | 4000 | 4000 | 0 | 0 | 0 | 0 | 21/21 | 3355 | 3000 | PASS |
| 1to1_skewed | 100.0 | 100.0 | 2 | 4000 | 4000 | 0 | 0 | 0 | 0 | 21/21 | 2019 | 3154 | PASS |
| 1to1_skewed | 100.0 | 100.0 | 3 | 4000 | 4000 | 0 | 0 | 0 | 0 | 21/21 | 2940 | 2895 | PASS |
| 1to1_skewed | 100.0 | 100.0 | 4 | 4000 | 4000 | 0 | 0 | 0 | 0 | 21/21 | 4457 | 4359 | PASS |
| near_1to1_beat | 100.0 | 98.7 | 1 | 4000 | 4000 | 0 | 0 | 0 | 0 | 21/21 | 3490 | 3019 | PASS |
| near_1to1_beat | 100.0 | 98.7 | 2 | 4000 | 4000 | 0 | 0 | 0 | 0 | 21/21 | 2295 | 3155 | PASS |
| near_1to1_beat | 100.0 | 98.7 | 3 | 4000 | 4000 | 0 | 0 | 0 | 0 | 21/21 | 3228 | 2849 | PASS |
| near_1to1_beat | 100.0 | 98.7 | 4 | 4000 | 4000 | 0 | 0 | 0 | 0 | 21/21 | 4428 | 4297 | PASS |
| wr_fast_3.7x | 250.0 | 67.6 | 1 | 4000 | 4000 | 0 | 0 | 0 | 0 | 21/21 | 16692 | 1044 | PASS |
| wr_fast_3.7x | 250.0 | 67.6 | 2 | 4000 | 4000 | 0 | 0 | 0 | 0 | 21/21 | 17300 | 972 | PASS |
| wr_fast_3.7x | 250.0 | 67.6 | 3 | 4000 | 4000 | 0 | 0 | 0 | 0 | 21/21 | 17639 | 1211 | PASS |
| wr_fast_3.7x | 250.0 | 67.6 | 4 | 4000 | 4000 | 0 | 0 | 0 | 0 | 21/21 | 17600 | 1442 | PASS |
| rd_fast_3.7x | 67.6 | 250.0 | 1 | 4000 | 4000 | 0 | 0 | 0 | 0 | 21/21 | 1104 | 22151 | PASS |
| rd_fast_3.7x | 67.6 | 250.0 | 2 | 4000 | 4000 | 0 | 0 | 0 | 0 | 21/21 | 3121 | 18840 | PASS |
| rd_fast_3.7x | 67.6 | 250.0 | 3 | 4000 | 4000 | 0 | 0 | 0 | 0 | 21/21 | 1026 | 20212 | PASS |
| rd_fast_3.7x | 67.6 | 250.0 | 4 | 4000 | 4000 | 0 | 0 | 0 | 0 | 21/21 | 2504 | 20046 | PASS |
| wr_fast_11x | 500.0 | 45.0 | 1 | 4000 | 4000 | 0 | 0 | 0 | 0 | 21/21 | 57869 | 178 | PASS |
| wr_fast_11x | 500.0 | 45.0 | 2 | 4000 | 4000 | 0 | 0 | 0 | 0 | 21/21 | 54984 | 125 | PASS |
| wr_fast_11x | 500.0 | 45.0 | 3 | 4000 | 4000 | 0 | 0 | 0 | 0 | 21/21 | 54936 | 170 | PASS |
| wr_fast_11x | 500.0 | 45.0 | 4 | 4000 | 4000 | 0 | 0 | 0 | 0 | 21/21 | 52807 | 234 | PASS |
| rd_fast_11x | 45.0 | 500.0 | 1 | 4000 | 4000 | 0 | 0 | 0 | 0 | 21/21 | 920 | 82428 | PASS |
| rd_fast_11x | 45.0 | 500.0 | 2 | 4000 | 4000 | 0 | 0 | 0 | 0 | 21/21 | 2894 | 71555 | PASS |
| rd_fast_11x | 45.0 | 500.0 | 3 | 4000 | 4000 | 0 | 0 | 0 | 0 | 21/21 | 820 | 72973 | PASS |
| rd_fast_11x | 45.0 | 500.0 | 4 | 4000 | 4000 | 0 | 0 | 0 | 0 | 21/21 | 1997 | 71375 | PASS |

**28/28 runs passed, 112000 reads checked, 0 mismatches, 0 overflows, 0 underflows, 0 assertion failures. 28/28 runs hit all coverage bins.**

Coverage bins: every occupancy level 0..16, full flag seen, empty again after reads, write blocked by full, read blocked by empty.
