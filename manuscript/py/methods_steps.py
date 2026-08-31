#!/usr/bin/env python3
"""derive a methods template's step list from saved dry runs.

The layout round needs several things that are mechanical, so they are done
here rather than by hand:

  modules   the module dirs the runs call into, and the items they walked
  resolve   the container commands that resolve every done variable to a path
  draft     the numbered `### steps` lines, in the order the pipeline ran them,
            plus a `# not used` list of everything declared but never reached
  check     the same comparison against an existing template, so a renamed or
            dropped step becomes an error instead of stale prose

A step is identified by its make done variable, which is a total key: in
practice every rule with a recipe declares one. The join works like this:

  the dry runs give resolved done-file paths in execution order
  `make -n lss v=L L="VAR1 VAR2 …"` gives one `VAR: path` pair per variable
  matching the two gives var -> position

Producing the resolution file is the caller's job, because it needs a make
invocation inside the container. `resolve` prints the exact commands:

  methods_steps.py resolve --module-dir … --ifn-runs … --pipeline long \\
      --config h40 --ofn-resolved dry/h40/resolved.txt

Item ids differ between the two sides when a fan-out is truncated (the dry run
walks the first item, `make p` resolves whatever the config defaults to), so
both sides are normalized by replacing any known item id with a placeholder.
"""
from __future__ import annotations

import argparse
import glob
import os
import re
import sys

RE_MK_DONE = re.compile(r"^([A-Z][A-Z0-9_]*_DONE)\s*[?:+]?=")
RE_START = re.compile(r"^START:\s*(\S+)")
# [^/\n] rather than [^/]: a var that resolved to nothing leaves a bare
# "ls -lart" line, and a newline-crossing match would steal the next var's path
RE_RESOLVED = re.compile(
    r'^\s*echo\s+"([A-Z][A-Z0-9_]*):\s*"\s*&&\s*ls[^/\n]*(/\S+)\s*$', re.M)
RE_PLAIN_RESOLVED = re.compile(r"^([A-Z][A-Z0-9_]*):\s*(\S+)\s*$")
RE_TRUNCATED = re.compile(r"PAR_LOCAL_RUN_ONLY_FIRST_TASK=T:\s*(\S+)\s+"
                          r"truncated to first of (\d+) tasks")

# the item a truncated fan-out actually walked, read off the recursive make
# par emits for the first task: `make m=long s_assembly ASSEMBLY_ID=AAK …`
RE_ITEM_ASSIGN = re.compile(r"\b([A-Z][A-Z0-9_]*_ID)=([A-Za-z0-9_.\-]+)")

# a bare id component such as AAK or AAK_early, used to normalize item paths
RE_ITEM = re.compile(r"^[A-Z]{2,5}(_[a-z]+)?$")


def die(msg: str) -> None:
    print(f"error: {msg}", file=sys.stderr)
    sys.exit(1)


def mk_done_vars(module_dirs: list[str]) -> list[str]:
    """every done variable the modules declare, in file then line order.

    More than one directory is normal: a module's pipeline routinely calls into
    another module's rules, so binning's dry run contains steps owned by
    genomes. Those steps still belong in binning's methods, because binning is
    what ran them.
    """
    out = []
    for module_dir in module_dirs:
        if not os.path.isdir(module_dir):
            die(f"module dir not found: {module_dir}")
        for path in sorted(glob.glob(os.path.join(module_dir, "*.mk"))):
            # the methods stages are documentation, not pipeline steps
            if os.path.basename(path).endswith("_methods.mk"):
                continue
            with open(path) as f:
                for line in f:
                    m = RE_MK_DONE.match(line)
                    if m and m.group(1) not in out:
                        out.append(m.group(1))
    return out


RE_MODULE_PATH = re.compile(r"/makeshift/modules/(\S+)")

# this script lives at modules/utils/manuscript/py/, so the modules root is
# three levels up — no environment variable needed
MODULES_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(
    os.path.dirname(os.path.abspath(__file__)))))


def module_of(rel: str, root: str) -> str | None:
    """walk up a referenced path until a directory owning a {name}_int.mk is
    found. Verifying against the filesystem beats guessing: a path may point at
    a script subdir (binning/pl), a binary (binning/bin.general/cluster_orient)
    or the module dir itself, and only the interface file settles it."""
    parts = [x for x in re.sub(r"/{2,}", "/", rel).split("/") if x]
    while parts:
        d = "/".join(parts)
        if os.path.exists(os.path.join(root, d, f"{parts[-1]}_int.mk")):
            return d
        parts = parts[:-1]
    return None


def modules_referenced(runs: list[str], root: str = MODULES_ROOT) -> list[str]:
    """module dirs whose scripts the dry runs invoke — the set that must be
    passed as --module-dir for every step to resolve"""
    out = []
    for path in runs:
        for m in RE_MODULE_PATH.finditer(open(path).read()):
            d = module_of(m.group(1), root)
            if d and d not in out:
                out.append(d)
    return sorted(out)


def read_runs(runs: list[str]) -> list[tuple[str, str]]:
    """(run file, resolved done path) in execution order, first occurrence only"""
    seen = set()
    out = []
    for path in runs:
        if not os.path.exists(path):
            die(f"dry run not found: {path}")
        with open(path) as f:
            for line in f:
                m = RE_START.match(line.strip())
                if not m:
                    continue
                p = m.group(1)
                if p in seen:
                    continue
                seen.add(p)
                out.append((os.path.basename(path), p))
    return out


def read_resolved(path: str) -> dict[str, str]:
    """VAR -> path, from either a plain 'VAR: path' list or `make -n lss`"""
    if not os.path.exists(path):
        die(f"resolution file not found: {path}")
    text = open(path).read()
    out = {}
    for m in RE_RESOLVED.finditer(text):
        out[m.group(1)] = m.group(2)
    if out:
        return out
    for line in text.split("\n"):
        m = RE_PLAIN_RESOLVED.match(line.strip())
        if m:
            out[m.group(1)] = m.group(2)
    if not out:
        die(f"no 'VAR: path' pairs found in {path}")
    return out


def normalize(path: str) -> str:
    """drop the item component so a first-task path and a default-item path
    for the same step compare equal"""
    parts = [("{item}" if RE_ITEM.match(p) else p) for p in path.split("/")]
    return "/".join(parts)


def truncation_notes(runs: list[str]) -> list[str]:
    out = []
    for path in runs:
        with open(path) as f:
            for line in f:
                m = RE_TRUNCATED.search(line)
                if m:
                    note = f"{os.path.basename(path)}: {m.group(1)} " \
                           f"truncated to 1 of {m.group(2)} tasks"
                    if note not in out:
                        out.append(note)
    return out


def build(module_dirs: list[str], runs: list[str], resolved_fn: str):
    declared = mk_done_vars(module_dirs)
    resolved = read_resolved(resolved_fn)
    ran = read_runs(runs)

    missing = [v for v in declared if v not in resolved]
    by_path: dict[str, list[str]] = {}
    for var in declared:
        if var in resolved:
            by_path.setdefault(normalize(resolved[var]), []).append(var)

    ordered: list[tuple[str, str]] = []   # (var, run file)
    unmatched: list[tuple[str, str]] = []
    used = set()
    for run_file, path in ran:
        cands = by_path.get(normalize(path), [])
        free = [c for c in cands if c not in used]
        if not free:
            unmatched.append((run_file, path))
            continue
        if len(free) > 1:
            # same normalized path from two variables: report, take the first
            unmatched.append((run_file, f"{path}  (ambiguous: {', '.join(free)})"))
        var = free[0]
        used.add(var)
        ordered.append((var, run_file))

    not_used = [v for v in declared if v not in used and v in resolved]
    return ordered, not_used, unmatched, missing


def hint_modules(runs: list[str]) -> None:
    refs = modules_referenced(runs)
    if refs:
        print(f"modules invoked by these runs: {', '.join(refs)}",
              file=sys.stderr)


def cmd_modules(args) -> None:
    """which module dirs the runs call into, and which item the truncation
    walked: the two things needed before the done variables can be resolved"""
    for path in args.ifn_runs:
        if not os.path.exists(path):
            die(f"dry run not found: {path}")
    for d in modules_referenced(args.ifn_runs):
        print(d)
    items = []
    for _run, path in read_runs(args.ifn_runs):
        for part in path.split("/"):
            if RE_ITEM.match(part) and part not in items:
                items.append(part)
    if items:
        print(f"items walked: {', '.join(items)}", file=sys.stderr)
    for note in truncation_notes(args.ifn_runs):
        print(note, file=sys.stderr)


def walked_items(runs: list[str]) -> dict[str, list[str]]:
    """VAR -> the item ids the runs pinned, first occurrence first.

    Only recursive make lines are read: the task tables par echoes carry every
    id in the config, which is the opposite of what a truncated run walked.
    """
    out: dict[str, list[str]] = {}
    for path in runs:
        with open(path) as f:
            for line in f:
                s = line.strip()
                if not s.startswith("make "):
                    continue
                for var, val in RE_ITEM_ASSIGN.findall(s):
                    vals = out.setdefault(var, [])
                    if val not in vals:
                        vals.append(val)
    return out


def cmd_resolve(args) -> None:
    """print the commands that produce the resolution file.

    Resolving is a make call inside the container, so this cannot run it; what
    it can do is remove every way of getting it wrong — the full done-variable
    list, the items the truncated runs walked, and one call per module.
    """
    for path in args.ifn_runs:
        if not os.path.exists(path):
            die(f"dry run not found: {path}")
    modules = [os.path.basename(d.rstrip("/")) for d in args.module_dir]
    variables = mk_done_vars(args.module_dir)
    if not variables:
        die(f"no done variables declared under {', '.join(args.module_dir)}")

    items = walked_items(args.ifn_runs)
    pins = " ".join(f"{var}={vals[0]}" for var, vals in sorted(items.items()))
    container = args.container or f"{args.pipeline}-{args.config}-ro"
    pipeline_dir = args.pipeline_dir or f"/makeshift/pipes/dev/p_{args.pipeline}"

    for i, module in enumerate(modules):
        inner = (f"cd {pipeline_dir} && make -n lss m={module} "
                 f"{pins} v=L L=\\\"{' '.join(variables)}\\\"")
        redirect = ">" if i == 0 else ">>"
        print(f'docker exec {container} bash -c "{inner}" | tr \';\' \'\\n\' '
              f'{redirect} {args.ofn_resolved}')

    print(f"resolving {len(variables)} done variable(s) over "
          f"{len(modules)} module(s): {', '.join(modules)}", file=sys.stderr)
    print(f"pinned items: {pins or '(none found)'}", file=sys.stderr)
    for var, vals in sorted(items.items()):
        if len(vals) > 1:
            print(f"note: {var} appears as {', '.join(vals)}; pinned the "
                  f"first — item components are normalized out of the match",
                  file=sys.stderr)


def cmd_draft(args) -> None:
    ordered, not_used, unmatched, missing = build(
        args.module_dir, args.ifn_runs, args.ifn_resolved)
    hint_modules(args.ifn_runs)

    width = max([len(v) for v, _ in ordered] + [len(v) for v in not_used] + [1])
    lines = ["# general", ""]
    lines.append(f"module: {args.module}")
    lines.append(f"pipeline: {args.pipeline}")
    lines.append(f"config: {args.config}")
    lines.append(f"tag: methods/{args.module}/v1.00")
    for run in args.ifn_runs:
        lines.append(f"dry run: {os.path.basename(run)} <- {args.command}"
                     .replace("{target}", "?"))
    for note in truncation_notes(args.ifn_runs):
        lines.append(f"// {note}")
    lines += ["", "# statistics", "",
              "// one line per key the prose cites, in the order the stats "
              "rule produces them",
              "// TODO  key [stat|setting]: short description",
              "", "# block 1: TODO title", "", "## para 1: TODO title", "",
              "### steps"]
    for i, (var, _run) in enumerate(ordered, start=1):
        lines.append(f"{i:02d}  {var:<{width}}  [TODO]: TODO one short line")
    lines += ["", "### text", "", "TODO prose", "", "### notes",
              "tables: ", "params: "]
    if not_used:
        lines += ["", "# not used", "", "### steps"]
        for var in not_used:
            lines.append(f"{var:<{width}}  [not used]: TODO why")

    body = "\n".join(lines) + "\n"
    if args.ofn_draft == "-":
        sys.stdout.write(body)
    else:
        os.makedirs(os.path.dirname(os.path.abspath(args.ofn_draft)),
                    exist_ok=True)
        with open(args.ofn_draft, "w") as f:
            f.write(body)
        print(f"wrote {args.ofn_draft}", file=sys.stderr)

    print(f"steps that ran: {len(ordered)}   declared but never reached: "
          f"{len(not_used)}", file=sys.stderr)
    for run_file, path in unmatched:
        print(f"warning: {run_file}: no done variable matches {path}",
              file=sys.stderr)
    if missing:
        print(f"warning: {len(missing)} declared done var(s) absent from the "
              f"resolution file: {', '.join(missing[:8])}"
              f"{' …' if len(missing) > 8 else ''}", file=sys.stderr)


def cmd_check(args) -> None:
    ordered, not_used, unmatched, _missing = build(
        args.module_dir, args.ifn_runs, args.ifn_resolved)
    expected = [v for v, _ in ordered]

    listed: list[str] = []
    listed_unused: set[str] = set()
    in_not_used = False
    for line in open(args.ifn_template):
        s = line.strip()
        if re.match(r"^#\s+not\s+used\s*$", s, re.I):
            in_not_used = True
            continue
        if re.match(r"^#\s+(block|general)\b", s, re.I):
            in_not_used = False
            continue
        m = re.match(r"^(?:\d+\s+)?([A-Z][A-Z0-9_]*)\s*\[", s)
        if not m:
            continue
        (listed_unused.add if in_not_used else listed.append)(m.group(1))

    problems = []
    missing = [v for v in expected if v not in listed and v not in listed_unused]
    extra = [v for v in listed if v not in expected]
    for v in missing:
        problems.append(f"{v} ran but is not listed in the template")
    for v in extra:
        problems.append(f"{v} is listed but did not run in these dry runs")
    if [v for v in expected if v in listed] != [v for v in listed
                                                if v in expected]:
        problems.append("template step order differs from execution order")
    for v in sorted(set(not_used) - listed_unused - set(listed)):
        problems.append(f"{v} is declared, never ran, and is not under "
                        f"'# not used'")

    for run_file, path in unmatched:
        print(f"warning: {run_file}: no done variable matches {path}",
              file=sys.stderr)

    if problems:
        print(f"error: {args.ifn_template} disagrees with the dry runs "
              f"({len(problems)} problem(s)):", file=sys.stderr)
        for p in problems:
            print(f"  - {p}", file=sys.stderr)
        sys.exit(1)
    print(f"ok: {len(expected)} step(s) accounted for, "
          f"{len(not_used)} under 'not used'", file=sys.stderr)


def main() -> None:
    ap = argparse.ArgumentParser(
        description=__doc__,
        formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = ap.add_subparsers(dest="cmd", required=True)

    m = sub.add_parser("modules", help="module dirs and items the runs used")
    m.add_argument("--ifn-runs", required=True, nargs="+")
    m.set_defaults(func=cmd_modules)

    r = sub.add_parser("resolve",
                       help="print the container commands that resolve every "
                            "done variable to a path")
    r.add_argument("--module-dir", required=True, nargs="+",
                   help="the module's dir, plus any other module dirs the "
                        "dry runs call into")
    r.add_argument("--ifn-runs", required=True, nargs="+")
    r.add_argument("--pipeline", required=True)
    r.add_argument("--config", required=True)
    r.add_argument("--ofn-resolved", required=True,
                   help="where the commands write their output, beside the "
                        "runs")
    r.add_argument("--container", default=None,
                   help="default {pipeline}-{config}-ro")
    r.add_argument("--pipeline-dir", default=None,
                   help="default /makeshift/pipes/dev/p_{pipeline}")
    r.set_defaults(func=cmd_resolve)

    for name, fn in (("draft", cmd_draft), ("check", cmd_check)):
        p = sub.add_parser(name)
        p.add_argument("--module", required=True)
        p.add_argument("--module-dir", required=True, nargs="+",
                       help="the module's dir, plus any other module dirs the "
                            "dry runs call into")
        p.add_argument("--ifn-runs", required=True, nargs="+",
                       help="saved dry runs, in pipeline order")
        p.add_argument("--ifn-resolved", required=True,
                       help="'VAR: path' pairs, or the output of make -n lss")
        if name == "draft":
            p.add_argument("--pipeline", required=True)
            p.add_argument("--config", required=True)
            p.add_argument("--command", default="make plan t={target} -B "
                                               "PAR_LOCAL_RUN_ONLY_FIRST_TASK=T")
            p.add_argument("--ofn-draft", default="-")
        else:
            p.add_argument("--ifn-template", required=True)
        p.set_defaults(func=fn)

    args = ap.parse_args()
    args.func(args)


if __name__ == "__main__":
    main()
