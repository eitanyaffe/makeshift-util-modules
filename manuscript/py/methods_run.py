#!/usr/bin/env python3
"""dispatch per-module methods renders from the pipeline's methods registry.

reads methods.json, filters by module name(s) in x, and runs
`make m={module} {target}` for each entry. no generate_methods.mk —
the list is short enough to dispatch straight from the json.

a stage may be selected so the gated and the always-fresh work can be invoked
separately over the same module set: measure is what writes values onto the
bucket, compile is what renders the docs from them. measure is the one stage
that does not run on the top machine -- the manuscript module dispatches a
single machine for the whole registry, and this runs there.

a module that fails stops the sweep: the registry lists code that is expected
to work, so a broken module is news rather than something to step over.
"""

import os
import subprocess
import sys

import methods_registry

# stage -> the make target, derived from {module}_methods. the names match
# the wiring every module's {module}_methods.mk declares. measure is the
# ungated rule itself, not a dispatch: it runs on the one machine the
# manuscript module sends out for the whole registry.
STAGES = {
    "all": "{base}",
    "scan": "{base}_scan",
    "measure": "{base}_stats",
    "compile": "{base}_compile",
}


def parse_key_value_args(tokens):
    result = {}
    for tok in tokens:
        if "=" in tok:
            key, _, val = tok.partition("=")
            result[key] = val
    return result


def run_entry(entry, make_bin, c, stage, extra_make_args):
    target = STAGES[stage].format(base=entry.target)
    # no -B: scan and compile are phony and always run, while measure is
    # deliberately gated by a done file. -B would defeat that gate and
    # recompute every module's stats on every invocation.
    cmd = [make_bin, f"m={entry.m}", target, f"c={c}"] + extra_make_args
    print("=" * 80)
    print(f"methods {stage} {entry.module}: {entry.title}")
    print(f"  {' '.join(cmd)}")
    print("=" * 80)
    subprocess.run(cmd, check=True)


def main():
    # stdout is block-buffered when it is a pipe, which would flush every
    # header after the sub-makes they label have already printed
    sys.stdout.reconfigure(line_buffering=True)
    kv = parse_key_value_args(sys.argv[1:])
    ifn = kv.pop("ifn", None)
    x = kv.pop("x", "all")
    stage = kv.pop("stage", "all") or "all"
    make_bin = kv.pop("make", "make")
    c = kv.pop("c", None)

    if not ifn or not c:
        print("error: ifn and c are required")
        sys.exit(1)
    if stage not in STAGES:
        print(f"error: unknown stage '{stage}' — expected one of "
              f"{', '.join(STAGES)}")
        sys.exit(1)

    _pipeline, entries = methods_registry.load(ifn)
    if not entries:
        print("the methods registry is empty — nothing to render")
        return

    selected = methods_registry.select(entries, x)
    print(f"methods {stage}: {len(selected)} module(s)")
    for entry in selected:
        run_entry(entry, make_bin, c, stage, [])
    print(f"done: methods {stage} over {len(selected)} module(s)")


if __name__ == "__main__":
    main()
