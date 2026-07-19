#!/usr/bin/env python3
"""dispatch per-module methods renders from figures.json methods[].

reads the manuscript json, filters by module name(s) in x, and runs
`make m={module} {target}` for each entry. no generate_methods.mk —
the list is short enough to dispatch straight from the json.
"""

import json
import os
import subprocess
import sys


def parse_key_value_args(tokens):
    result = {}
    for tok in tokens:
        if "=" in tok:
            key, _, val = tok.partition("=")
            result[key] = val
    return result


def load_methods(ifn):
    with open(ifn) as f:
        data = json.load(f)
    methods = data.get("methods", [])
    if not isinstance(methods, list):
        print("error: figures.json 'methods' must be an array", file=sys.stderr)
        sys.exit(1)
    return methods


def select_entries(methods, x):
    """x=all → all entries; otherwise space/comma-separated module names."""
    x = x.replace(",", " ").strip()
    if x == "" or x == "all":
        return methods
    wanted = set(x.split())
    by_module = {}
    for entry in methods:
        mod = entry.get("module")
        if not mod:
            print("error: methods entry missing 'module'", file=sys.stderr)
            sys.exit(1)
        by_module[mod] = entry
    missing = sorted(wanted - set(by_module.keys()))
    if missing:
        known = ", ".join(sorted(by_module.keys())) or "(none)"
        print(f"error: unknown methods module(s): {', '.join(missing)}",
              file=sys.stderr)
        print(f"  known modules in figures.json methods[]: {known}",
              file=sys.stderr)
        sys.exit(1)
    # preserve json order among the selected set
    return [e for e in methods if e["module"] in wanted]


def run_entry(entry, make_bin, c, extra_make_args):
    module = entry.get("module")
    target = entry.get("target")
    if not module or not target:
        print("error: methods entry requires 'module' and 'target'",
              file=sys.stderr)
        print(f"  got: {entry}", file=sys.stderr)
        sys.exit(1)
    title = entry.get("title") or module
    # always remake — methods are documentation, like plot targets (no
    # done-file gating). -B covers any leftover .done_* from older wiring.
    cmd = [make_bin, "-B", f"m={module}", target, f"c={c}"] + extra_make_args
    print("=" * 80, file=sys.stderr)
    print(f"methods {module}: {title}", file=sys.stderr)
    print(f"  {' '.join(cmd)}", file=sys.stderr)
    print("=" * 80, file=sys.stderr)
    subprocess.run(cmd, check=True)


def main():
    kv = parse_key_value_args(sys.argv[1:])
    ifn = kv.pop("ifn", None)
    x = kv.pop("x", "all")
    make_bin = kv.pop("make", "make")
    c = kv.pop("c", None)

    if not ifn or not c:
        print("error: ifn and c are required", file=sys.stderr)
        sys.exit(1)
    if not os.path.exists(ifn):
        print(f"error: figures.json not found: {ifn}", file=sys.stderr)
        sys.exit(1)

    methods = load_methods(ifn)
    if len(methods) == 0:
        print("methods[] is empty — nothing to render", file=sys.stderr)
        return

    selected = select_entries(methods, x)
    print(f"rendering {len(selected)} methods module(s)", file=sys.stderr)
    for entry in selected:
        run_entry(entry, make_bin, c, [])
    print(f"done: {len(selected)} methods module(s) rendered", file=sys.stderr)


if __name__ == "__main__":
    main()
