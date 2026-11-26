#!/usr/bin/env python3
"""Constrained-random regression for the async FIFO on the Vivado simulator (xsim).

  python scripts/run_regression.py                         # clean design, all clock ratios x 4 seeds
  python scripts/run_regression.py --mutate                # also run every injected bug
  python scripts/run_regression.py --seeds 2 --txns 2000 --mutate --mutant-seeds 1

Every run uses META_INJECT (random metastability resolution in the
synchronizers). Needs xvlog/xelab/xsim on PATH (run_sim.bat sets that up).
Writes docs/test_results.md, docs/mutation_results.md, reports/junit.xml and
reports/regression.json. Exit code 0 only if every clean run passes and every
bug that simulation is expected to see is caught.
"""
import argparse
import functools
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
import time
from pathlib import Path
from xml.sax.saxutils import escape

print = functools.partial(print, flush=True)  # live output in run_logs
ROOT = Path(__file__).resolve().parent.parent
SOURCES = ["rtl/sync_2ff.sv", "rtl/async_fifo.sv", "tb/fifo_sva.sv", "tb/tb_fifo.sv"]

# name, write period, read period, write phase, read phase (ps)
CONFIGS = [
    ("1to1_aligned", 10000, 10000, 0, 0),
    ("1to1_skewed", 10000, 10000, 0, 3300),
    ("near_1to1_beat", 10000, 10130, 0, 1700),
    ("wr_fast_3.7x", 4000, 14800, 0, 900),
    ("rd_fast_3.7x", 14800, 4000, 0, 900),
    ("wr_fast_11x", 2000, 22200, 0, 500),
    ("rd_fast_11x", 22200, 2000, 0, 500),
]

# bug -> (description, should simulation catch it?)
MUTANTS = {
    "BUG_WR_WHEN_FULL":  ("write enable not gated by full, so unread data is overwritten", True),
    "BUG_RD_WHEN_EMPTY": ("read enable not gated by empty, so the read pointer passes the write pointer", True),
    "BUG_FULL_MSB":      ("full compare inverts only the MSB (binary-style compare on a Gray pointer)", True),
    "BUG_GRAY_CONV":     ("wrong binary-to-Gray conversion on the write pointer (b ^ b>>2)", True),
    "BUG_BIN_CROSS":     ("binary pointers cross the clock domains instead of Gray (a metastable glitch lasts one cycle, so sim cannot see it)", False),
    "BUG_ONE_FLOP":      ("only one synchronizer stage (functionally identical in RTL sim)", False),
}
RESULT_RE = re.compile(r"FIFO_RESULT (.*)")
SVA_RE = re.compile(r"FIFO_SVA (.*)")


def tool(name):
    for cand in (name, name + ".bat", name + ".exe"):
        p = shutil.which(cand)
        if p:
            return p
    sys.exit(f"[run] ERROR: {name} not found on PATH - run Vivado's settings64.bat first")


def sh(cmd, cwd, log):
    with open(log, "a", encoding="utf-8", errors="replace") as f:
        f.write("\n$ " + " ".join(cmd) + "\n")
        f.flush()
        proc = subprocess.run(cmd, cwd=cwd, stdout=f, stderr=subprocess.STDOUT,
                              shell=(os.name == "nt"))
    return proc.returncode


def build(variant, build_root):
    d = build_root / variant
    if d.exists():
        shutil.rmtree(d, ignore_errors=True)
    d.mkdir(parents=True)
    log = d / "build.log"
    xvlog = [tool("xvlog"), "-sv", "-d", "META_INJECT"]
    if variant != "clean":
        xvlog += ["-d", variant]
    xvlog += [str(ROOT / s) for s in SOURCES]
    if sh(xvlog, d, log) != 0:
        return None, log
    xelab = [tool("xelab"), "tb_fifo", "-s", "snap", "-timescale", "1ps/1ps"]
    if sh(xelab, d, log) != 0:
        return None, log
    return d, log


def run_one(d, cfg, seed, txns):
    name, wp, rp, wph, rph = cfg
    tag = f"{name}_s{seed}"
    log = d / f"xsim_{tag}.log"
    if log.exists():
        log.unlink()
    # options go in a file: cmd.exe / xsim.bat would split "a=b" arguments
    opts = d / f"xsim_{tag}.opts"
    opts.write_text("\n".join([
        "-R", "-sv_seed", str(seed),
        "-testplusarg", f"WPER={wp}", "-testplusarg", f"RPER={rp}",
        "-testplusarg", f"WPHASE={wph}", "-testplusarg", f"RPHASE={rph}",
        "-testplusarg", f"NUM_TXN={txns}", "-testplusarg", f"SEED={seed}",
    ]) + "\n")
    t0 = time.time()
    sh([tool("xsim"), "snap", "-f", opts.name], d, log)
    dt = time.time() - t0
    text = log.read_text(encoding="utf-8", errors="replace")
    res = {"config": name, "wper_ps": wp, "rper_ps": rp, "seed": seed, "time_s": round(dt, 1)}
    m = None
    for m in RESULT_RE.finditer(text):
        pass
    if m is None:
        res["status"] = "NO_RESULT"
        res["tail"] = "\n".join(text.splitlines()[-25:])
        return res
    for kv in m.group(1).split():
        k, _, v = kv.partition("=")
        try:
            res[k] = int(v)
        except ValueError:
            res[k] = v
    s = None
    for s in SVA_RE.finditer(text):
        pass
    res["sva_rules"] = " ".join(x for x in (s.group(1).split() if s else []) if not x.endswith(":0"))
    res["status"] = "PASS" if res.get("pass") == 1 else "FAIL"
    first = re.search(r"FIFO_(MISMATCH|OVERFLOW|UNDERFLOW|SVA_FAIL)[^\n]*", text)
    res["first_error"] = first.group(0)[:300] if first else ""
    return res


def caught_by(r):
    who = []
    if r.get("mismatches", 0):
        who.append("scoreboard")
    if r.get("overflow", 0):
        who.append("overflow check")
    if r.get("underflow", 0):
        who.append("underflow check")
    if r.get("sva_fail", 0):
        who.append("SVA")
    if r.get("status") == "FAIL" and r.get("drained") == 0:
        who.append("drain check")
    if r.get("timeout") == 1:
        who.append("timeout")
    return who


def mhz(ps):
    return f"{1e6 / ps:.1f}"


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--seeds", type=int, default=4)
    ap.add_argument("--txns", type=int, default=4000)
    ap.add_argument("--mutate", action="store_true")
    ap.add_argument("--mutant-seeds", type=int, default=1)
    ap.add_argument("--only-mutants", action="store_true")
    args = ap.parse_args()

    build_root = Path(tempfile.gettempdir()) / "afifo_build"
    print(f"[run] build dir: {build_root}")
    summary = {"clean": [], "mutants": {}, "txns": args.txns, "configs": [c[0] for c in CONFIGS]}
    ok = True

    if not args.only_mutants:
        d, log = build("clean", build_root)
        if d is None:
            print(f"[run] clean build FAILED - see {log}")
            print(log.read_text(errors="replace")[-4000:])
            return 2
        for cfg in CONFIGS:
            for seed in range(1, args.seeds + 1):
                r = run_one(d, cfg, seed, args.txns)
                summary["clean"].append(r)
                ok &= r["status"] == "PASS"
                print("[run] {:15s} seed {}  writes {:>5}  checks {:>5}  mism {}  ovf {}  unf {}  sva {}  "
                      "cov {}/{}  full {:>5}  empty {:>5}  {}  ({}s)".format(
                          cfg[0], seed, r.get("writes", "-"), r.get("checks", "-"), r.get("mismatches", "-"),
                          r.get("overflow", "-"), r.get("underflow", "-"), r.get("sva_fail", "-"),
                          r.get("cov_hit", "-"), r.get("cov_bins", "-"), r.get("full_cycles", "-"),
                          r.get("empty_cycles", "-"), r["status"], r["time_s"]))
                if r["status"] != "PASS":
                    print("        " + (r.get("first_error") or r.get("tail", ""))[:1500])
        passed = sum(1 for r in summary["clean"] if r["status"] == "PASS")
        checks = sum(r.get("checks", 0) for r in summary["clean"])
        print(f"[run] {passed}/{len(summary['clean'])} clean runs passed, {checks} checks")

    if args.mutate:
        for bug, (desc, expect_sim) in MUTANTS.items():
            d, log = build(bug, build_root)
            if d is None:
                print(f"[{bug}] build FAILED - see {log}")
                print(log.read_text(errors="replace")[-2000:])
                summary["mutants"][bug] = {"desc": desc, "expect_sim": expect_sim, "runs": [], "killed": 0, "build": "FAILED"}
                ok = False
                continue
            runs = []
            for cfg in CONFIGS:
                for seed in range(1, args.mutant_seeds + 1):
                    r = run_one(d, cfg, seed, args.txns)
                    runs.append(r)
                    print(f"[{bug}] {cfg[0]:15s} seed {seed}  {r['status']}  caught by: "
                          f"{', '.join(caught_by(r)) or '-'}  {r.get('sva_rules', '')}")
            killed = sum(1 for r in runs if r["status"] == "FAIL")
            summary["mutants"][bug] = {"desc": desc, "expect_sim": expect_sim, "runs": runs, "killed": killed}
            print(f"[run] {bug}: {'KILLED' if killed else 'SURVIVED'} in {killed}/{len(runs)} runs"
                  f"{'' if expect_sim else ' (expected: RTL sim cannot see this one; the CDC structure check does)'}")
            if expect_sim and killed == 0:
                ok = False

    write_reports(summary, args)
    print(f"[run] overall {'PASS' if ok else 'FAIL'}")
    return 0 if ok else 1


def write_reports(summary, args):
    (ROOT / "docs").mkdir(exist_ok=True)
    (ROOT / "reports").mkdir(exist_ok=True)
    stamp = time.strftime("%Y-%m-%d %H:%M")
    clean = summary["clean"]
    if clean:
        tot = lambda k: sum(r.get(k, 0) for r in clean if isinstance(r.get(k, 0), int))
        lines = ["# Regression results (clean design)", "",
                 f"Generated {stamp} by `scripts/run_regression.py` on Vivado xsim with metastability "
                 f"injection on. {summary['txns']} writes per run.", "",
                 "| Clock config | wclk MHz | rclk MHz | Seed | Writes | Reads checked | Mismatches | Overflow | Underflow | SVA fails | Coverage bins | Full cycles | Empty cycles | Result |",
                 "|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|:--|"]
        for r in clean:
            lines.append("| {} | {} | {} | {} | {} | {} | {} | {} | {} | {} | {}/{} | {} | {} | {} |".format(
                r["config"], mhz(r["wper_ps"]), mhz(r["rper_ps"]), r["seed"], r.get("writes", "-"),
                r.get("checks", "-"), r.get("mismatches", "-"), r.get("overflow", "-"), r.get("underflow", "-"),
                r.get("sva_fail", "-"), r.get("cov_hit", "-"), r.get("cov_bins", "-"),
                r.get("full_cycles", "-"), r.get("empty_cycles", "-"), r["status"]))
        passed = sum(1 for r in clean if r["status"] == "PASS")
        full_cov = sum(1 for r in clean if r.get("cov_hit") == r.get("cov_bins"))
        lines += ["", f"**{passed}/{len(clean)} runs passed, {tot('checks')} reads checked, "
                      f"{tot('mismatches')} mismatches, {tot('overflow')} overflows, {tot('underflow')} underflows, "
                      f"{tot('sva_fail')} assertion failures. {full_cov}/{len(clean)} runs hit all coverage bins.**", "",
                  "Coverage bins: every occupancy level 0..16, full flag seen, empty again after reads, "
                  "write blocked by full, read blocked by empty.", ""]
        (ROOT / "docs" / "test_results.md").write_text("\n".join(lines), encoding="utf-8")

    if summary["mutants"]:
        lines = ["# Mutation results (simulation)", "",
                 f"Generated {stamp}. Each bug is compiled in with a define and run on all "
                 f"{len(CONFIGS)} clock configs x {args.mutant_seeds} seed(s). Killed = runs that failed.", "",
                 "| Injected bug | What it breaks | Killed | Caught by | Assertions that fired |",
                 "|---|---|:-:|---|---|"]
        for bug, m in summary["mutants"].items():
            who = sorted({w for r in m["runs"] for w in caught_by(r)})
            rules = sorted({x.split(":")[0] for r in m["runs"] for x in r.get("sva_rules", "").split()})
            note = "" if m["expect_sim"] else " (not visible to RTL sim; see CDC check)"
            lines.append(f"| `{bug}` | {m['desc']} | {m['killed']}/{len(m['runs'])} | "
                         f"{', '.join(who) or '-'}{note} | {', '.join(rules) or '-'} |")
        exp = [m for m in summary["mutants"].values() if m["expect_sim"]]
        killed = sum(1 for m in exp if m["killed"])
        lines += ["", f"**{killed}/{len(exp)} simulation-visible bugs caught.**", ""]
        (ROOT / "docs" / "mutation_results.md").write_text("\n".join(lines), encoding="utf-8")

    cases = []
    for r in clean:
        body = "" if r["status"] == "PASS" else \
            f'<failure message="{escape(r["status"])}">{escape(r.get("first_error") or r.get("tail", ""))}</failure>'
        cases.append(f'  <testcase classname="async_fifo" name="{r["config"]}.seed{r["seed"]}" time="{r["time_s"]}">{body}</testcase>')
    for bug, m in summary["mutants"].items():
        bad = m["expect_sim"] and not m["killed"]
        body = '<failure message="mutant survived">no checker failed</failure>' if bad else ""
        t = sum(r["time_s"] for r in m["runs"])
        cases.append(f'  <testcase classname="async_fifo.mutation" name="{bug}" time="{t:.1f}">{body}</testcase>')
    fails = sum(1 for c in cases if "<failure" in c)
    xml = ['<?xml version="1.0" encoding="UTF-8"?>',
           f'<testsuite name="async-fifo" tests="{len(cases)}" failures="{fails}">'] + cases + ["</testsuite>", ""]
    (ROOT / "reports" / "junit.xml").write_text("\n".join(xml), encoding="utf-8")
    (ROOT / "reports" / "regression.json").write_text(json.dumps(summary, indent=2, default=str), encoding="utf-8")
    print("[run] wrote docs/test_results.md, docs/mutation_results.md, reports/junit.xml, reports/regression.json")


if __name__ == "__main__":
    sys.exit(main())
