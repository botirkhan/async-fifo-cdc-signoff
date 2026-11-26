#!/usr/bin/env python3
"""Sign-off flow for the async FIFO (Linux / GitHub Actions, OSS CAD Suite).

  python3 scripts/signoff.py lint
  python3 scripts/signoff.py cdc    --variant clean
  python3 scripts/signoff.py cdc    --variant BUG_ONE_FLOP --expect fail
  python3 scripts/signoff.py lec    --variant clean           # gate netlist from this RTL variant
  python3 scripts/signoff.py formal --variant BUG_FULL_MSB --expect fail
  python3 scripts/signoff.py sim    --variant clean           # Verilator smoke

Each step writes reports/signoff/<step>_<variant>.json and prints one line
"SIGNOFF step=... variant=... result=pass|fail ...". With --expect the exit
code is 0 only if the result matches (used for the mutant matrix in CI).
"""
import argparse
import functools
import json
import os
import re
import shutil
import subprocess
import sys
import time
from collections import defaultdict
from pathlib import Path

print = functools.partial(print, flush=True)
ROOT = Path(__file__).resolve().parent.parent
RTL = ["rtl/sync_2ff.sv", "rtl/async_fifo.sv"]
BUILD = ROOT / "build"
OUT = ROOT / "reports" / "signoff"
FORMAL_DEPTH = {"bmc": 30, "cover": 40}

SIM_CONFIGS = [  # name, wper, rper, wphase, rphase (ps)
    ("1to1_skewed", 10000, 10000, 0, 3300),
    ("wr_fast_3.7x", 4000, 14800, 0, 900),
    ("rd_fast_3.7x", 14800, 4000, 0, 900),
]


def run(cmd, cwd=ROOT, log=None, timeout=3600):
    t0 = time.time()
    p = subprocess.run(cmd, cwd=cwd, stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                       text=True, timeout=timeout)
    if log:
        Path(log).parent.mkdir(parents=True, exist_ok=True)
        Path(log).write_text("$ " + " ".join(map(str, cmd)) + "\n" + p.stdout)
    return p.returncode, p.stdout, round(time.time() - t0, 1)


def defines(variant, extra=()):
    d = list(extra)
    if variant and variant != "clean":
        d.append(variant)
    return d


def run_stream(cmd, cwd, log, timeout):
    """Like run() but echoes output live (so long formal runs show progress in CI)."""
    t0 = time.time()
    lines = []
    p = subprocess.Popen(cmd, cwd=cwd, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True)
    try:
        for line in p.stdout:
            lines.append(line)
            print("    | " + line.rstrip())
            if time.time() - t0 > timeout:
                p.kill()
                lines.append("SIGNOFF_TIMEOUT\n")
                break
        p.wait()
    finally:
        Path(log).write_text("".join(lines))
    return p.returncode, "".join(lines), round(time.time() - t0, 1)


def yosys(script, log):
    return run(["yosys", "-q", "-l", str(log), "-p", script], log=None)


# --------------------------------------------------------------------- lint
def step_lint(args):
    res = {"configs": []}
    ok = True
    for params in ([], ["-GADDR_W=2", "-GDATA_W=4"], ["-GADDR_W=6", "-GDATA_W=32"]):
        cmd = ["verilator", "--lint-only", "-Wall", "--top-module", "async_fifo"] + params + RTL
        rc, out, dt = run(cmd, log=BUILD / "lint" / f"lint{'_'.join(params) or '_default'}.log")
        warns = [l for l in out.splitlines() if l.startswith("%Warning")]
        errs = [l for l in out.splitlines() if l.startswith("%Error")]
        res["configs"].append({"params": " ".join(params) or "default", "rc": rc,
                               "warnings": len(warns), "errors": len(errs), "first": (warns + errs)[:10]})
        print(f"[lint] {' '.join(params) or 'default':24s} rc={rc} warnings={len(warns)} errors={len(errs)}")
        for l in (warns + errs)[:20]:
            print("    " + l)
        ok &= rc == 0 and not warns and not errs
    v = run(["verilator", "--version"])[1].strip()
    res["tool"] = v
    return ok, res


# ---------------------------------------------------------------------- CDC
def load_gray_list():
    names = set()
    for line in (ROOT / "cdc" / "gray_registers.txt").read_text().splitlines():
        line = line.split("#")[0].strip()
        if line:
            names.add(line)
    return names


def step_cdc(args):
    d = BUILD / f"cdc_{args.variant}"
    d.mkdir(parents=True, exist_ok=True)
    js = d / "netlist.json"
    defs = " ".join(f"-D{x}" for x in defines(args.variant))
    script = (f"read_verilog -sv {defs} {' '.join(str(ROOT / f) for f in RTL)}; "
              f"hierarchy -top async_fifo; proc; flatten; memory; opt_clean; write_json {js}")
    rc, out, _ = yosys(script, d / "yosys.log")
    if rc != 0:
        print(out[-3000:])
        return False, {"error": "yosys failed"}
    rep = analyze_cdc(json.loads(js.read_text()), load_gray_list())
    rep["variant"] = args.variant
    write_cdc_md(rep, d / "cdc_report.md")
    shutil.copy(d / "cdc_report.md", OUT / f"cdc_{args.variant}.md")
    for c in rep["crossings"]:
        print(f"[cdc] crossing {c['src']} ({c['src_clk']}) -> {c['dst']} ({c['dst_clk']}): "
              f"{c['bits']} bit(s){', Gray' if c['gray'] else ''}")
    for v in rep["violations"]:
        print(f"[cdc] VIOLATION {v['rule']}: {v['msg']}")
    print(f"[cdc] flops={rep['flops']} crossings={len(rep['crossings'])} violations={len(rep['violations'])}")
    return len(rep["violations"]) == 0, rep


def analyze_cdc(data, gray_regs):
    mod = data["modules"]["async_fifo"]
    cells = mod["cells"]
    names = defaultdict(list)
    for n, info in mod["netnames"].items():
        hidden = info.get("hide_name", 0) or n.startswith("$")
        for i, b in enumerate(info["bits"]):
            if isinstance(b, int):
                names[b].append((hidden, n.count("."), len(n), n, i, len(info["bits"])))

    def bitname(b):
        if b not in names:
            return f"net{b}", f"net{b}"
        hidden, _, _, n, i, w = sorted(names[b])[0]
        return n, (f"{n}[{i}]" if w > 1 else n)

    out_bits = set()
    for p in mod["ports"].values():
        if p["direction"] == "output":
            out_bits.update(b for b in p["bits"] if isinstance(b, int))

    driver, consumers = {}, defaultdict(list)
    for cn, c in cells.items():
        for port, bits in c["connections"].items():
            dirn = c["port_directions"].get(port, "input")
            for i, b in enumerate(bits):
                if not isinstance(b, int):
                    continue
                if dirn == "output":
                    driver[b] = (cn, port, i)
                else:
                    consumers[b].append((cn, port, i))

    def is_flop(c):
        return "CLK" in c["connections"] and "Q" in c["connections"]

    flops = {cn: c for cn, c in cells.items() if is_flop(c)}
    clk_of = {cn: bitname(c["connections"]["CLK"][0])[0] for cn, c in flops.items()}

    def cone(bit):
        """Flop bits feeding `bit` through combinational logic; and whether any logic was crossed."""
        d0 = driver.get(bit)
        direct = d0 is not None and d0[0] in flops and d0[1] == "Q"
        srcs, seen, stack = set(), set(), [bit]
        while stack:
            b = stack.pop()
            if b in seen:
                continue
            seen.add(b)
            dr = driver.get(b)
            if dr is None:
                continue
            cn, port, i = dr
            if cn in flops:
                srcs.add((cn, i))
                continue
            c = cells[cn]
            for p, bits in c["connections"].items():
                if c["port_directions"].get(p) == "input":
                    stack.extend(x for x in bits if isinstance(x, int))
        return srcs, direct

    crossings = defaultdict(lambda: {"bits": 0, "logic": False})
    violations = []
    for cn, c in flops.items():
        dom = clk_of[cn]
        dbits = c["connections"].get("D", [])
        en = [b for b in c["connections"].get("EN", []) if isinstance(b, int)]
        for i, db in enumerate(dbits):
            if not isinstance(db, int):
                continue
            srcs, direct = cone(db)
            for eb in en:
                srcs |= cone(eb)[0]
            xs = {(s, j) for (s, j) in srcs if clk_of[s] != dom}
            if not xs:
                continue
            qb = c["connections"]["Q"][i]
            dst_reg, dst_bit = bitname(qb)
            for s, j in xs:
                src_reg, src_bit = bitname(flops[s]["connections"]["Q"][j])
                key = (src_reg, clk_of[s], dst_reg, dom)
                crossings[key]["bits"] += 1
                if not direct or len(srcs) > 1 or en:
                    crossings[key]["logic"] = True
            if not direct or len(srcs) > 1 or en:
                violations.append({"rule": "CDC-LOGIC",
                                   "msg": f"{dst_bit} ({dom}) samples {', '.join(sorted(bitname(flops[s]['connections']['Q'][j])[1] for s, j in xs))} "
                                          f"from another clock domain through combinational logic"})
                continue
            # first synchronizer stage: its output may only feed one flop in the same domain, directly
            uses = consumers.get(qb, [])
            bad = [u for u in uses if not (u[0] in flops and u[1] == "D" and clk_of[u[0]] == dom)]
            if qb in out_bits or bad or len(uses) != 1:
                what = ", ".join(sorted({cells[u[0]]["type"] for u in bad})) or ("output port" if qb in out_bits else f"{len(uses)} loads")
                violations.append({"rule": "CDC-1FF",
                                   "msg": f"{dst_bit} ({dom}) is the first synchronizer stage but drives {what} "
                                          f"instead of exactly one second-stage flop"})
    rows = []
    for (src, sclk, dst, dclk), v in sorted(crossings.items()):
        gray = src.split(".")[-1] in gray_regs
        rows.append({"src": src, "src_clk": sclk, "dst": dst, "dst_clk": dclk,
                     "bits": v["bits"], "gray": gray, "logic": v["logic"]})
        if v["bits"] > 1 and not gray:
            violations.append({"rule": "CDC-BUS",
                               "msg": f"{v['bits']}-bit bus {src} ({sclk}) -> {dst} ({dclk}) is not a "
                                      f"registered Gray-coded pointer (see cdc/gray_registers.txt)"})
    # de-duplicate per-bit 1FF/LOGIC messages by register
    seen, uniq = set(), []
    for v in violations:
        k = (v["rule"], re.sub(r"\[\d+\]", "", v["msg"]))
        if k not in seen:
            seen.add(k)
            uniq.append({"rule": v["rule"], "msg": k[1]})
    return {"flops": sum(len(c["connections"]["Q"]) for c in flops.values()),
            "clocks": sorted(set(clk_of.values())), "crossings": rows, "violations": uniq}


def write_cdc_md(rep, path):
    lines = [f"# CDC structure report ({rep['variant']})", "",
             f"Clocks: {', '.join(rep['clocks'])}. Flop bits analysed: {rep['flops']}.", "",
             "| Source register | From | Synchronizer stage 1 | To | Bits | Gray | Logic on path |",
             "|---|---|---|---|---:|:-:|:-:|"]
    for c in rep["crossings"]:
        lines.append(f"| `{c['src']}` | {c['src_clk']} | `{c['dst']}` | {c['dst_clk']} | {c['bits']} | "
                     f"{'yes' if c['gray'] else 'no'} | {'yes' if c['logic'] else 'no'} |")
    lines += ["", f"**Violations: {len(rep['violations'])}**", ""]
    lines += [f"- `{v['rule']}` {v['msg']}" for v in rep["violations"]]
    lines += ["", "Rules: CDC-LOGIC = no combinational logic between the source flop and the first "
              "synchronizer flop; CDC-1FF = the first stage feeds exactly one second-stage flop; "
              "CDC-BUS = a multi-bit crossing must come from a listed Gray-coded register.", ""]
    path.write_text("\n".join(lines))


# ---------------------------------------------------------------------- LEC
def step_lec(args):
    d = BUILD / f"lec_{args.variant}"
    d.mkdir(parents=True, exist_ok=True)
    net = d / "async_fifo_syn.v"
    rtl = " ".join(str(ROOT / f) for f in RTL)
    defs = " ".join(f"-D{x}" for x in defines(args.variant))
    rc, out, _ = yosys(f"read_verilog -sv {defs} {rtl}; synth -flatten -top async_fifo; "
                       f"tee -o {d / 'stat.txt'} stat; write_verilog -noattr {net}", d / "synth.log")
    if rc != 0:
        print(out[-3000:])
        return False, {"error": "synth failed"}
    stat = (d / "stat.txt").read_text()
    cells = re.search(r"Number of cells:\s+(\d+)", stat) or re.search(r"^\s*(\d+)\s+cells\s*$", stat, re.M)
    ffs = sum(int(n) for n in re.findall(r"\$_\w*DFF\w*\s+(\d+)", stat))
    script = (f"read_verilog -sv {rtl}; hierarchy -top async_fifo; proc; opt_clean; memory; opt_clean; flatten; "
              f"rename async_fifo gold; design -stash gold; "
              f"read_verilog {net}; hierarchy -top async_fifo; proc; opt_clean; rename async_fifo gate; design -stash gate; "
              f"design -copy-from gold -as gold gold; design -copy-from gate -as gate gate; "
              f"equiv_make gold gate equiv; hierarchy -top equiv; async2sync; "
              f"equiv_simple -seq 5; equiv_induct -seq 5; tee -o {d / 'equiv_status.txt'} equiv_status; equiv_status -assert")
    rc, out, dt = run(["yosys", "-l", str(d / "lec.log"), "-p", script])
    st = (d / "equiv_status.txt").read_text() if (d / "equiv_status.txt").exists() else ""
    m = re.search(r"Found (\d+) \$equiv cells", st)
    m2 = re.search(r"Of those cells (\d+) are proven and (\d+) are unproven", st)
    total = int(m.group(1)) if m else 0
    proven, unproven = (int(m2.group(1)), int(m2.group(2))) if m2 else (0, total)
    if not m2 and "Equivalence successfully proven" in st:
        proven, unproven = total, 0
    res = {"gate_from": args.variant, "equiv_cells": total, "proven": proven, "unproven": unproven,
           "gate_cells": int(cells.group(1)) if cells else None, "gate_flops": ffs, "time_s": dt}
    unp = re.findall(r"Unproven \$equiv [^\n]*", st)
    print(f"[lec] gate netlist from {args.variant}: {res['gate_cells']} cells, {ffs} flops; "
          f"$equiv cells {total}: {proven} proven, {unproven} unproven")
    for l in unp[:15]:
        print("    " + l)
    if rc != 0 and not unp:
        print(out[-2500:])
    return rc == 0 and unproven == 0 and total > 0, res


# ------------------------------------------------------------------- formal
def prop_names(path):
    names = {}
    for i, line in enumerate(path.read_text().splitlines(), 1):
        m = re.search(r"// (?:PROP|COVER) (\w+)", line)
        if m:
            names[(path.name, i)] = m.group(1)
    return names


def step_formal(args):
    d = BUILD / f"formal_{args.variant}"
    if d.exists():
        shutil.rmtree(d)
    d.mkdir(parents=True)
    files = [ROOT / "rtl/sync_2ff.sv", ROOT / "rtl/async_fifo.sv", ROOT / "formal/fifo_formal.sv"]
    pnames = {}
    for f in files:
        pnames.update(prop_names(f))
    defs = " ".join(f"-D{x}" for x in defines(args.variant, ["META_INJECT"]))
    tasks = ["bmc", "cover"] if args.variant == "clean" else ["bmc"]
    sby = "\n".join([
        "[tasks]", *tasks, "",
        "[options]",
        *[l for t in tasks for l in (f"{t}: mode {t}", f"{t}: depth {FORMAL_DEPTH[t]}")],
        "multiclock on", "",
        "[engines]", "smtbmc yices", "",
        "[script]",
        f"verilog_defines {defs}",
        "read -formal sync_2ff.sv async_fifo.sv fifo_formal.sv",
        "prep -top fifo_formal", "",
        "[files]", *[str(f) for f in files], ""])
    (d / "fifo.sby").write_text(sby)
    res = {"variant": args.variant, "depth": FORMAL_DEPTH, "tasks": {}}
    ok = True
    for t in tasks:
        rc, out, dt = run_stream(["sby", "-f", "fifo.sby", t], cwd=d, log=d / f"sby_{t}.log",
                                 timeout=args.formal_timeout)
        status = "PASS" if re.search(r"DONE \(PASS", out) else ("FAIL" if re.search(r"DONE \(FAIL", out) else
                                                                ("TIMEOUT" if "SIGNOFF_TIMEOUT" in out else "ERROR"))
        failed = []
        for m in re.finditer(r"Assert failed in \S+: (\S+?):(\d+)", out):
            key = (Path(m.group(1)).name, int(m.group(2)))
            failed.append(pnames.get(key, f"{key[0]}:{key[1]}"))
        step = re.search(r"BMC failed!|Assert failed.*?step (\d+)", out)
        fstep = re.search(r"Checking assertions in step (\d+)\.\.\.\s*\n.*?BMC failed", out, re.S)
        reached = []
        for m in re.finditer(r"Reached cover statement at (\S+?):(\d+)", out):
            key = (Path(m.group(1)).name, int(m.group(2)))
            reached.append(pnames.get(key, f"{key[0]}:{key[1]}"))
        unreached = len(re.findall(r"Unreached cover statement", out))
        res["tasks"][t] = {"status": status, "time_s": dt, "failed_props": sorted(set(failed)),
                           "fail_step": int(fstep.group(1)) if fstep else None,
                           "covers_reached": sorted(set(reached)), "covers_unreached": unreached}
        print(f"[formal] {args.variant} {t} depth {FORMAL_DEPTH[t]}: {status} ({dt}s)"
              + (f" failed: {', '.join(sorted(set(failed)))}" if failed else "")
              + (f" at step {fstep.group(1)}" if fstep else "")
              + (f" covers reached: {', '.join(sorted(set(reached)))}; unreached {unreached}" if t == "cover" else ""))
        if status in ("ERROR", "TIMEOUT"):
            print(out[-3000:])
            res["error"] = f"sby {t} {status}"
        if t == "bmc":
            ok &= status == "PASS"
        else:
            ok &= status == "PASS" and unreached == 0
    return ok, res


# ---------------------------------------------------------------- Verilator
def step_sim(args):
    d = BUILD / f"sim_{args.variant}"
    if d.exists():
        shutil.rmtree(d)
    d.mkdir(parents=True)
    defs = [f"-D{x}" for x in defines(args.variant, ["META_INJECT"])]
    cmd = ["verilator", "--binary", "--timing", "--assert", "-Wno-fatal", "-Wno-lint", "-Wno-style",
           "--top-module", "tb_fifo", "-Mdir", str(d / "obj"), "-o", "sim"] + defs + \
          [str(ROOT / f) for f in RTL + ["tb/fifo_sva.sv", "tb/tb_fifo.sv"]]
    rc, out, dt = run(cmd, log=d / "build.log")
    if rc != 0:
        print(out[-4000:])
        return False, {"error": "verilator build failed"}
    res = {"runs": []}
    ok = True
    for name, wp, rp, wph, rph in SIM_CONFIGS:
        rc, out, dt = run([str(d / "obj" / "sim"), f"+WPER={wp}", f"+RPER={rp}", f"+WPHASE={wph}",
                           f"+RPHASE={rph}", f"+NUM_TXN={args.txns}", f"+SEED={args.seed}",
                           f"+verilator+seed+{args.seed}"], log=d / f"{name}.log", timeout=1800)
        m = None
        for m in re.finditer(r"FIFO_RESULT (.*)", out):
            pass
        r = {"config": name, "rc": rc}
        if m:
            for kv in m.group(1).split():
                k, _, v = kv.partition("=")
                r[k] = int(v) if v.isdigit() else v
        s = re.findall(r"FIFO_SVA (.*)", out)
        r["sva"] = s[-1] if s else ""
        passed = r.get("pass") == 1
        ok &= passed
        res["runs"].append(r)
        print(f"[sim] {name:14s} pass={r.get('pass', 0)} writes={r.get('writes', '-')} checks={r.get('checks', '-')} "
              f"mismatches={r.get('mismatches', '-')} overflow={r.get('overflow', '-')} underflow={r.get('underflow', '-')} "
              f"sva_fail={r.get('sva_fail', '-')} cov={r.get('cov_hit', '-')}/{r.get('cov_bins', '-')} {r['sva']}")
        if not m:
            print("    no FIFO_RESULT; tail:\n    " + "\n    ".join(out.splitlines()[-15:]))
    return ok, res


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("step", choices=["lint", "cdc", "lec", "formal", "sim"])
    ap.add_argument("--variant", default="clean")
    ap.add_argument("--expect", choices=["pass", "fail"])
    ap.add_argument("--txns", type=int, default=3000)
    ap.add_argument("--seed", type=int, default=1)
    ap.add_argument("--formal-timeout", type=int, default=1200, help="seconds per sby task")
    args = ap.parse_args()
    OUT.mkdir(parents=True, exist_ok=True)
    BUILD.mkdir(parents=True, exist_ok=True)
    ok, res = {"lint": step_lint, "cdc": step_cdc, "lec": step_lec,
               "formal": step_formal, "sim": step_sim}[args.step](args)
    result = "error" if res.get("error") else ("pass" if ok else "fail")
    res.update(step=args.step, variant=args.variant, result=result, expect=args.expect)
    (OUT / f"{args.step}_{args.variant}.json").write_text(json.dumps(res, indent=2))
    line = f"SIGNOFF step={args.step} variant={args.variant} result={result}" + \
           (f" expect={args.expect}" if args.expect else "")
    print(line)
    if os.environ.get("GITHUB_STEP_SUMMARY"):
        with open(os.environ["GITHUB_STEP_SUMMARY"], "a") as f:
            f.write(f"### {args.step} / {args.variant}: **{result}**"
                    + (f" (expected {args.expect})" if args.expect else "") + "\n\n```\n"
                    + json.dumps(res, indent=1)[:6000] + "\n```\n")
    if args.expect:
        return 0 if result == args.expect else 1
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
