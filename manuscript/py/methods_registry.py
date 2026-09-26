#!/usr/bin/env python3
"""the methods registry: which modules the paper's methods section covers.

The registry is a property of the pipeline, not of a config — a methods
section describes what the code does, and nothing about that is
config-specific — so it sits beside the templates it lists:

    pipes/dev/p_{pipeline}/methods/methods.json

    {
      "pipeline": "long",
      "modules": [
        { "module": "long",   "title": "long-read metagenomic assembly" },
        { "module": "eggNOG", "prefix": "EGG", "title": "orthology assignment" },
        { "module": "rna",    "m": "mrna",     "title": "RNA expression" }
      ]
    }

Array order is the order the sections concatenate in. Everything else is
derived: the make target is `{module}_methods` and the four compiled docs are
`{PREFIX}_METHODS_{PAPER,FULL}_{MD,TEX}`, with PREFIX the uppercased module
name. Deriving is what keeps registration a one-line edit, so a module joins
the sweep as soon as its template exists rather than once someone writes out
four variable names by hand.

Two fields exist for the modules the derivation does not fit: `prefix` when
the variables do not carry the uppercased name, and `m` when the module
registers with make under another name. `module` always stays the methods
name — the template directory, the token scope and the exported basename.

`"render": false` keeps a module in the sweep but out of the paper. Its
template is still scanned and its values still measured, which is what another
module's `imports:` needs, but it contributes no section. This is for a module
whose work is one sentence and reads better inside a neighbour's paragraph than
under a heading of its own.

A registered module with no prose yet is not an error: it compiles, its
missing values render as bold NA, and the export records it as a draft. The
status is always read off what is on disk rather than declared here, so it
cannot go stale.
"""

import json
import os
import sys


# one export subdir and one combined file per (version, format) pair
VARIANTS = {
    "paper_md":  ("methods", "md", "methods.md"),
    "paper_tex": ("methods", "tex", "methods.tex"),
    "full_md":   ("methods_full", "md", "methods_full.md"),
    "full_tex":  ("methods_full", "tex", "methods_full.tex"),
}

# the variable each variant is derived as, under the module's own prefix
VAR_SUFFIX = {
    "paper_md":  "METHODS_PAPER_MD",
    "paper_tex": "METHODS_PAPER_TEX",
    "full_md":   "METHODS_FULL_MD",
    "full_tex":  "METHODS_FULL_TEX",
}

ENTRY_FIELDS = ("module", "title", "prefix", "m", "render")

# the compile writes this at the head of every doc it could not fully resolve.
# shared so the export detects a draft by the marker rather than by eye
DRAFT_MARK = "**Draft:"


def die(msg: str) -> None:
    # stderr, unlike the rest of the manuscript scripts: list_vars.py imports
    # this loader and its stdout is the variable list make consumes, so an
    # error on stdout would end up inside MANUSCRIPT_REFERENCED_VARS
    print(f"error: {msg}", file=sys.stderr)
    sys.exit(1)


class Entry:
    def __init__(self, d: dict, ifn: str):
        unknown = sorted(set(d) - set(ENTRY_FIELDS))
        if unknown:
            die(f"{ifn}: unknown field(s) {', '.join(unknown)} in {d}")
        self.module = str(d.get("module", "")).strip()
        if not self.module:
            die(f"{ifn}: a modules[] entry has no 'module'")
        self.title = str(d.get("title", "")).strip() or self.module
        self.prefix = str(d.get("prefix", "")).strip() or self.module.upper()
        # the name make knows the module by, which is usually the methods name
        self.m = str(d.get("m", "")).strip() or self.module
        self.target = f"{self.module}_methods"
        # measured either way; false keeps it out of the exported section
        render = d.get("render", True)
        if not isinstance(render, bool):
            die(f"{ifn}: 'render' must be true or false in {d}")
        self.render = render

    def var(self, variant: str) -> str:
        return f"{self.prefix}_{VAR_SUFFIX[variant]}"

    @property
    def vars(self) -> dict[str, str]:
        return {k: self.var(k) for k in VARIANTS}


def load(ifn: str) -> tuple[str, list[Entry]]:
    if not os.path.exists(ifn):
        die(f"methods registry not found: {ifn}")
    with open(ifn) as f:
        try:
            data = json.load(f)
        except json.JSONDecodeError as e:
            die(f"{ifn}: {e}")
    unknown = sorted(set(data) - {"pipeline", "modules"})
    if unknown:
        die(f"{ifn}: unknown top-level field(s) {', '.join(unknown)}")
    pipeline = str(data.get("pipeline", "")).strip()
    if not pipeline:
        die(f"{ifn}: 'pipeline' is required")
    modules = data.get("modules", [])
    if not isinstance(modules, list):
        die(f"{ifn}: 'modules' must be an array")
    entries = [Entry(d, ifn) for d in modules]
    seen: set[str] = set()
    for e in entries:
        if e.module in seen:
            die(f"{ifn}: module {e.module!r} registered twice")
        seen.add(e.module)
    return pipeline, entries


def select(entries: list[Entry], x: str) -> list[Entry]:
    """x=all or empty -> every entry; otherwise space/comma-separated modules"""
    x = (x or "").replace(",", " ").strip()
    if x in ("", "all"):
        return entries
    wanted = set(x.split())
    known = {e.module for e in entries}
    missing = sorted(wanted - known)
    if missing:
        die(f"unknown methods module(s): {', '.join(missing)}\n"
            f"  registered: {', '.join(sorted(known)) or '(none)'}")
    return [e for e in entries if e.module in wanted]


def var_names(entries: list[Entry]) -> list[str]:
    """every variable the export needs make to resolve"""
    return sorted({e.var(k) for e in rendered(entries) for k in VARIANTS})


def rendered(entries: list[Entry]) -> list[Entry]:
    """the entries that contribute a section to the paper"""
    return [e for e in entries if e.render]
