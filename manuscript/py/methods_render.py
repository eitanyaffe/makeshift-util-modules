#!/usr/bin/env python3
"""shared methods template parser / renderer for all makeshift modules.

A template is a structured document, not free prose:

    # general
    module: binning
    module version: v1.26
    pipeline: long
    config: h40
    tag: methods/long/v1
    dry run: 01_p_binning.txt <- make plan t=p_binning c=h40 -B PAR_LOCAL_RUN_ONLY_FIRST_TASK=T

    # statistics
    min_seg [setting]: minimum segment length
    n_genomes [stat]: number of reconstructed genomes

    # block 1: genome reconstruction
    ## para 1: segment coverage
    ### steps
    04  BINNING_SEGMENTS_DONE   [complex]: cuts contigs into segments
    ### text

    Contigs were cut into segments of at least {{setting:binning:min_seg}} nt.
    ### notes
    tables: BINNING_SEGMENT_TABLE
    params: BINNING_MIN_SEGMENT_LENGTH
    // free note

A module is one or more blocks, a block is one or more paragraphs, and a
paragraph has three parts. `steps` is the accounting: one line per make done
variable, in the order the pipeline ran them, each with a one-line description
short enough to read beside the prose. A step whose output is consumed later
may end its bracket with `at: paragraph title`: the step keeps its place in
pipeline order, and its prose sits in that later paragraph. `text` is the prose
that reaches the paper. `notes` never reaches the paper and is where output tables, parameters,
tool probes and reasoning live.

The file opens with a reserved `# general` block recording which module and
pipeline it describes, the module version the methods were written against, the
tag freezing the code they describe, and the exact dry-run commands the step
list came from, so a step sequence can always be traced back to the run that
produced it.

`module version` mirrors the version the module registers with, so a bump is
staleness detectable without reading any history. It is the per-module signal
and is always checked. `tag` names one git tag shared by every template of a
pipeline, applied across every repo once the whole methods section is done; it
is a record of which code state the section describes, not a per-module
verification, and is why a methods or stats edit never needs a new one. A
template whose pipeline has not been tagged yet carries `tag: none`, which
scans and compiles — the tag is required at manuscript export, not here.

A second reserved block, `# statistics`, is the numeric inventory: one line per
key the prose cites, with a short description, in the order the module's stats
rule produces them. Every own-scope token must be declared there and every
declaration must be cited, so the inventory cannot drift from the prose.

Titles are metadata, not prose: the block title becomes a section heading and
the paragraph title becomes the bold lead-in, so `### text` holds pure prose.

A third reserved block, `# not used`, lists declared steps the pipeline never
ran.

Two versions are compiled, each in markdown and LaTeX:

  paper  values substituted, `text` only, titles injected, prose reflowed
  full   values substituted *and* their token kept, everything preserved

Only `stat` and `setting` tokens exist, both resolved by key lookup. Every
token names a scope, and by default that scope must be the module itself. A
template that needs to cite another module — a downstream module reporting the
version of a tool the upstream module already probed — declares that upstream
in the general block:

    imports: minimap, poly

Cross-module tokens then resolve against the imported modules' own values
tables, passed at compile time as 'scope=path' pairs via --ifn-import-values.
Each module still owns its own values.txt on its own version gate; the
importing module's compile just reads from more than one.

Bibliographic citations use Pandoc syntax in prose, for example
`[@yaffeBriefAntibioticUse2025]`. Scan and compile validate every cited key
against the `id` fields in the configured CSL JSON bibliography. Citation
formatting happens once over the combined methods.md so all modules share one
numbering sequence and bibliography.

The former `step`, `table` and `param` hints are retired: steps are the
`### steps` list and tables/params are `### notes` keys.

Subcommands:
  scan     validate a template and report the keys it requires
  compile  template + values -> paper.md, paper.tex, full.md, full.tex

Every structural anomaly is fatal. The one exception is an unresolved value:
a module is registered as soon as its template exists, so a section whose
stats have not run yet still compiles, with the gaps rendered as bold NA
behind a draft note leading every output. --strict restores the refusal for
the final pass.
"""
from __future__ import annotations

import argparse
import glob
import json
import os
import re
import sys
import textwrap

import artifacts as artifacts_mod
from methods_registry import DRAFT_MARK
from methods_to_tex import convert_body, escape_tex

RESOLVED_TYPES = ("stat", "setting")
# supp is resolved like a value but not from the values table: the number
# comes from a pipeline-wide walk over every module's artifacts.json
SUPP_TYPE = "supp"
RETIRED_TYPES = ("step", "table", "param")

# the reporting decision for a step; exactly one per line
CLASSES = ("external", "in-house", "complex", "ignored", "dispatch", "not used")

# a paragraph may omit its prose only if every step in it is plumbing
SILENT_CLASSES = ("dispatch", "ignored")

# a step description is one short sentence: it names the step in the prose's
# own words, and the detail lives in the mk comment above the rule
STEP_DESC_MAX = 70

# recognized keys in a notes part; tables and params are validated lists
NOTE_LIST_KEYS = ("tables", "params")
NOTE_KEYS = NOTE_LIST_KEYS + ("tools",)

TOKEN = re.compile(r"\{\{([^{}]*)\}\}")
EDIT_COMMENT = re.compile(r"\[\[(.*?)\]\]", re.S)
CITATION_CLUSTER = re.compile(r"\[([^\]\n]*@[^\]\n]+)\]")
CITATION_KEY = re.compile(r"(?<![A-Za-z0-9])@([A-Za-z0-9][A-Za-z0-9_.:+-]*)")
# a POSIX bracket class such as [[:space:]] is regex syntax, not an edit
# comment; notes recording a version parse are full of them
POSIX_CLASS = re.compile(r"^:[a-z]+:$")

# a contradiction the methods cannot fix on its own, because the main text is
# the side that is wrong. Unlike an edit comment it does not block compiling:
# it renders bold into every output so the author meets it while reading, and
# both scan and compile list it so it cannot ship unnoticed
MAIN_TEXT_FIX = re.compile(r"\*\*Main text fix:(.*?)\*\*", re.S)

# recognized keys in the general block; 'dry run' may repeat, one per file;
# 'imports' is an optional comma-separated list of module scopes cited by the
# template beyond the module's own
GENERAL_ONCE = ("module", "module version", "pipeline", "config", "tag")
GENERAL_OPTIONAL_ONCE = ("imports",)
GENERAL_MANY = ("dry run",)
GENERAL_ALL = GENERAL_ONCE + GENERAL_OPTIONAL_ONCE + GENERAL_MANY

# one tag per pipeline, applied to every repo once the whole methods section is
# done. namespaced by pipeline so it cannot collide with a code tag, and carrying
# a plain revision that only moves when the code it freezes changes materially
RE_TAG = re.compile(r"^methods/([a-z][a-z0-9_]*)/v(\d+)$")

# a pipeline whose methods section has not been frozen yet
TAG_NONE = "none"

# the module's own version is whatever it registers with, which is usually a
# variable but is occasionally a literal
RE_REGISTER = r"_register_module\s*,\s*{}\s*,\s*([^,)]+?)\s*,"
RE_VAR_NAME = re.compile(r"^[A-Z][A-Z0-9_]*$")
RE_VAR_VALUE = r"^\s*{}\s*[?:]?=\s*(\S+)\s*$"

RE_GENERAL = re.compile(r"^#\s+general\s*$", re.I)
RE_STATISTICS = re.compile(r"^#\s+statistics\s*$", re.I)
RE_NOT_USED = re.compile(r"^#\s+not\s+used\s*$", re.I)
RE_BLOCK = re.compile(r"^#\s+block\s+(\d+)\s*:\s*(.+?)\s*$", re.I)
RE_PARA = re.compile(r"^##\s+para\s+(\d+)\s*:\s*(.+?)\s*$", re.I)
RE_PART = re.compile(r"^###\s+(\S+)\s*$")
RE_ANY_HEAD = re.compile(r"^#{1,6}\s")

RE_STEP = re.compile(r"^(\d+)\s+([A-Z][A-Z0-9_]*)\s*\[([^\]]*)\]\s*:\s*(.*)$")
RE_STEP_UNNUMBERED = re.compile(r"^([A-Z][A-Z0-9_]*)\s*\[([^\]]*)\]\s*:\s*(.*)$")
RE_STAT_DECL = re.compile(r"^([a-z][a-z0-9_]*)\s*\[([^\]]*)\]\s*:\s*(.*)$")

RE_MK_DECL = re.compile(r"^([A-Z][A-Z0-9_]*)\s*[?:+]?=")

# a make variable named inside a notes bullet, which is where the template maps
# each entity the prose introduces to the thing that holds it
RE_NOTE_VAR = re.compile(r"(?<![A-Za-z0-9_])([A-Z][A-Z0-9_]{2,})(?![A-Za-z0-9_])")

STRUCTURED = re.compile(r"^\s*([-*+]\s|\d+\.\s|[|>#])")

errors: list[str] = []


def fail(msg: str) -> None:
    errors.append(msg)


def flush(context: str) -> None:
    if not errors:
        return
    print(f"error: {context} failed with {len(errors)} problem(s):")
    for e in errors:
        print(f"  - {e}")
    sys.exit(1)


#####################################################################################
# model
#####################################################################################


class Step:
    def __init__(self, num, var, cls, loop, desc, line, at=None):
        self.num = num
        self.var = var
        self.cls = cls
        self.loop = loop
        self.at = at
        self.desc = desc
        self.line = line

    @property
    def bracket(self) -> str:
        extra = (f", loop: {self.loop}" if self.loop else "") + \
                (f", at: {self.at}" if self.at else "")
        return f"[{self.cls}{extra}]"


class Stat:
    def __init__(self, name, stype, desc, line):
        self.name = name
        self.type = stype
        self.desc = desc
        self.line = line


class Para:
    def __init__(self, num, title, line):
        self.num = num
        self.title = title
        self.line = line
        self.steps: list[Step] = []
        self.text: list[tuple[int, str]] = []
        self.notes: list[tuple[int, str]] = []
        self.has_text_part = False

    @property
    def lead_in(self) -> str:
        t = self.title.strip().rstrip(".")
        return (t[:1].upper() + t[1:]) if t else t

    @property
    def prose(self) -> str:
        return "\n".join(l for _n, l in self.text)


class Block:
    def __init__(self, kind, num, title, line):
        self.kind = kind
        self.num = num
        self.title = title
        self.line = line
        self.paras: list[Para] = []
        self.steps: list[Step] = []
        self.stats: list[Stat] = []
        self.meta: list[tuple[int, str]] = []

    @property
    def is_general(self) -> bool:
        return self.kind == "general"

    @property
    def is_statistics(self) -> bool:
        return self.kind == "statistics"

    @property
    def is_not_used(self) -> bool:
        return self.kind == "not used"

    @property
    def is_prose(self) -> bool:
        return self.kind == "block"

    @property
    def heading(self) -> str:
        t = self.title.strip()
        return (t[:1].upper() + t[1:]) if t else t


#####################################################################################
# parsing
#####################################################################################


def parse_classes(lineno, var, body):
    """a bracket holds exactly one class, optionally plus 'loop: VAR', and
    optionally ends with 'at: paragraph title' naming the later paragraph
    whose prose describes the step"""
    at = None
    m = re.search(r"(?:^|,)\s*at:(.*)$", body, flags=re.IGNORECASE)
    if m:
        # the title runs to the end of the bracket, so it may hold commas
        at = m.group(1).strip()
        body = body[:m.start()]
        if not at:
            fail(f"line {lineno}: {var} has an empty 'at:' — name the title "
                 f"of the later paragraph whose prose describes it")
    cls, loop, rejected = None, None, False
    for field in (f.strip() for f in body.split(",")):
        if not field:
            continue
        low = field.lower()
        if low.startswith("loop:"):
            loop = field.split(":", 1)[1].strip()
            if not loop:
                fail(f"line {lineno}: {var} has an empty 'loop:' — name the "
                     f"item variable it fans out over")
        elif low in CLASSES:
            if cls is not None:
                fail(f"line {lineno}: {var} carries two classes "
                     f"('{cls}' and '{low}'); exactly one is allowed")
            else:
                cls = low
        else:
            rejected = True
            fail(f"line {lineno}: {var} has unknown class '{field}' — "
                 f"expected one of {', '.join(CLASSES)}, "
                 f"optionally with 'loop: VAR' and a final 'at: title'")
    if cls is None and not rejected:
        fail(f"line {lineno}: {var} has no class — one of "
             f"{', '.join(CLASSES)} is required")
    return cls, loop, at


def parse(text: str) -> list[Block]:
    blocks: list[Block] = []
    block = None
    para = None
    part = None

    for lineno, raw in enumerate(text.split("\n"), start=1):
        line = raw.rstrip()
        s = line.strip()

        if RE_GENERAL.match(s):
            block = Block("general", None, "general", lineno)
            blocks.append(block)
            para, part = None, None
            continue

        if RE_STATISTICS.match(s):
            block = Block("statistics", None, "statistics", lineno)
            blocks.append(block)
            para, part = None, None
            continue

        if RE_NOT_USED.match(s):
            block = Block("not used", None, "not used", lineno)
            blocks.append(block)
            para, part = None, None
            continue

        m = RE_BLOCK.match(s)
        if m:
            block = Block("block", int(m.group(1)), m.group(2), lineno)
            blocks.append(block)
            para, part = None, None
            continue

        m = RE_PARA.match(s)
        if m:
            if block is None:
                fail(f"line {lineno}: '## para' before any '# block N:' header")
                continue
            if not block.is_prose:
                fail(f"line {lineno}: the '# {block.title}' block takes no "
                     f"paragraphs")
                continue
            para = Para(int(m.group(1)), m.group(2), lineno)
            block.paras.append(para)
            part = None
            continue

        m = RE_PART.match(s)
        if m:
            name = m.group(1).lower()
            if name not in ("steps", "text", "notes"):
                fail(f"line {lineno}: unknown part '### {m.group(1)}' — "
                     f"expected steps, text or notes")
                part = None
                continue
            if block is None:
                fail(f"line {lineno}: '### {name}' before any block header")
                continue
            if block.is_general or block.is_statistics:
                fail(f"line {lineno}: the '# {block.title}' block holds bare "
                     f"declaration lines, not '### {name}'")
                continue
            if para is None and not block.is_not_used:
                fail(f"line {lineno}: '### {name}' outside a '## para' header")
                continue
            if block.is_not_used and name != "steps":
                fail(f"line {lineno}: the '# not used' block holds only "
                     f"'### steps', not '### {name}'")
                continue
            part = name
            if name == "text" and para is not None:
                para.has_text_part = True
            continue

        if RE_ANY_HEAD.match(s):
            fail(f"line {lineno}: unexpected heading {s!r} — the only headings "
                 f"are '# block N: title', '# not used', '## para N: title' "
                 f"and '### steps|text|notes'")
            continue

        if not s:
            if part == "text" and para is not None:
                para.text.append((lineno, ""))
            continue

        if block is not None and block.is_general:
            block.meta.append((lineno, line))
            continue

        if block is not None and block.is_statistics:
            if s.startswith("//"):
                block.meta.append((lineno, line))
                continue
            m = RE_STAT_DECL.match(s)
            if not m:
                fail(f"line {lineno}: not a statistics line: {s[:60]!r} — "
                     f"expected 'key [stat|setting]: description'")
                continue
            stype = m.group(2).strip().lower()
            if stype not in RESOLVED_TYPES:
                fail(f"line {lineno}: '{m.group(1)}' has unknown type "
                     f"'{m.group(2).strip()}' — expected one of "
                     f"{', '.join(RESOLVED_TYPES)}")
                continue
            block.stats.append(Stat(m.group(1), stype, m.group(3).strip(),
                                    lineno))
            continue

        if part is None:
            fail(f"line {lineno}: content outside any '### steps|text|notes' "
                 f"part: {s[:60]!r}")
            continue

        if part == "text":
            para.text.append((lineno, line))
            continue

        if part == "notes":
            para.notes.append((lineno, line))
            continue

        # part == steps. a step is one line: there is no continuation syntax,
        # so a description cannot grow past the one-sentence budget
        owner = para if para is not None else block
        m = RE_STEP.match(s)
        if m:
            cls, loop, at = parse_classes(lineno, m.group(2), m.group(3))
            owner.steps.append(Step(int(m.group(1)), m.group(2), cls, loop,
                                    m.group(4).strip(), lineno, at))
            continue
        m = RE_STEP_UNNUMBERED.match(s)
        if m:
            cls, loop, at = parse_classes(lineno, m.group(1), m.group(2))
            owner.steps.append(Step(None, m.group(1), cls, loop,
                                    m.group(3).strip(), lineno, at))
            continue
        fail(f"line {lineno}: not a step line: {s[:60]!r} — expected "
             f"'NN  VAR  [class]: description' on one line")

    return blocks


#####################################################################################
# structural checks
#####################################################################################


def check_general(blocks: list[Block], module: str,
                  module_dir: str | None = None,
                  module_ver: str | None = None) -> tuple[list[str], str]:
    """the provenance header: what module, what pipeline, and the exact dry
    runs the step list was derived from. Returns the imports list (empty when
    the template declares no cross-module citations) and the tag."""
    generals = [b for b in blocks if b.is_general]
    if not generals:
        fail("template has no '# general' block; it must open with one "
             f"carrying {', '.join(GENERAL_ONCE)} and at least one 'dry run:'")
        return [], TAG_NONE
    if len(generals) > 1:
        fail(f"line {generals[1].line}: more than one '# general' block")
    if not blocks[0].is_general:
        fail(f"line {generals[0].line}: '# general' must be the first block")

    g = generals[0]
    seen: dict[str, str] = {}
    n_runs = 0
    imports: list[str] = []
    for lineno, line in g.meta:
        s = line.strip()
        if s.startswith("//"):
            continue
        key, sep, val = s.partition(":")
        key, val = key.strip().lower(), val.strip()
        if not sep:
            fail(f"line {lineno}: '# general' takes 'key: value' lines, "
                 f"got {s[:50]!r}")
            continue
        if not val:
            fail(f"line {lineno}: '{key}:' has no value")
            continue
        if key in GENERAL_MANY:
            n_runs += 1
        elif key in GENERAL_ONCE or key in GENERAL_OPTIONAL_ONCE:
            if key in seen:
                fail(f"line {lineno}: '{key}:' given twice")
            seen[key] = val
            if key == "imports":
                imports = [m.strip() for m in val.split(",") if m.strip()]
                if not imports:
                    fail(f"line {lineno}: 'imports:' is empty; list at least "
                         f"one module")
                if module in imports:
                    fail(f"line {lineno}: 'imports:' lists the module itself "
                         f"({module!r})")
        else:
            fail(f"line {lineno}: unknown general key '{key}' — expected "
                 f"{', '.join(GENERAL_ALL)}, or a // comment")
    for key in GENERAL_ONCE:
        if key not in seen:
            fail(f"line {g.line}: '# general' is missing '{key}:'")
    if seen.get("module") not in (None, module):
        fail(f"line {g.line}: '# general' says module '{seen['module']}' but "
             f"the compile was invoked with '{module}'")
    check_module_ver(g.line, module, module_dir, seen.get("module version"),
                     module_ver)
    tag = seen.get("tag")
    pipeline = seen.get("pipeline")
    if tag is not None and tag != TAG_NONE:
        m = RE_TAG.match(tag)
        if not m:
            fail(f"line {g.line}: tag '{tag}' is malformed — expected "
                 f"'methods/{pipeline}/vN', one tag shared by the whole "
                 f"pipeline, or '{TAG_NONE}' until it is cut")
        elif pipeline is not None and m.group(1) != pipeline:
            fail(f"line {g.line}: tag '{tag}' names pipeline '{m.group(1)}' "
                 f"but the template says '{pipeline}'")
    if n_runs == 0:
        fail(f"line {g.line}: '# general' lists no 'dry run:' — record the "
             f"file and the exact command behind the step list")
    return imports, tag


def read_module_ver(module: str, module_dir: str) -> str | None:
    """the version the module registers with, read out of the interface file.

    this is the fallback for when make did not pass --module-ver, and it can
    only see the interface file's own default: a version the pipeline or the
    config overrides reads here as whatever the module declared, which may be
    a value that never takes effect. prefer --module-ver.

    the second argument of _register_module is usually a variable name but is
    sometimes the version itself, and a few modules register under a name other
    than their own, so {MODULE}_VER is the last resort."""
    ifn = os.path.join(module_dir, f"{module}_int.mk")
    if not os.path.isfile(ifn):
        return None
    with open(ifn) as f:
        text = f.read()
    expr = None
    m = re.search(RE_REGISTER.format(re.escape(module)), text)
    if m:
        expr = m.group(1).strip()
        if not RE_VAR_NAME.match(expr):
            return expr
    else:
        expr = f"{module.upper()}_VER"
    m = re.search(RE_VAR_VALUE.format(re.escape(expr)), text, re.M)
    return m.group(1) if m else None


def check_module_ver(line: int, module: str, module_dir: str | None,
                     declared: str | None, resolved: str | None = None) -> None:
    """the declared module version is the per-module staleness signal: a bump of
    the module's own version is drift that needs no git history to detect, while
    a methods or stats edit leaves it alone and so stays quiet.

    the version make resolved is authoritative when given, since a pipeline or a
    config may override what the module declares and the overridden value is the
    one that shaped the data."""
    if declared is None:
        return
    if resolved:
        cur = resolved
    elif module_dir and os.path.isdir(module_dir):
        cur = read_module_ver(module, module_dir)
    else:
        return
    if cur is None:
        fail(f"cannot read the version {module} registers with from "
             f"{module_dir} — the template's 'module version:' cannot be checked")
    elif cur != declared:
        fail(f"line {line}: methods were written against {module} {declared} "
             f"but it now resolves to {cur} — review the methods against the "
             f"new version and set 'module version: {cur}'")


def check_shape(blocks: list[Block]) -> None:
    if not blocks:
        fail("template is empty")
        return
    real = [b for b in blocks if b.is_prose]
    if not real:
        fail("template has no '# block N:' header")
    if len([b for b in blocks if b.is_not_used]) > 1:
        fail("template has more than one '# not used' block")
    stats_blocks = [b for b in blocks if b.is_statistics]
    if len(stats_blocks) > 1:
        fail(f"line {stats_blocks[1].line}: more than one '# statistics' block")
    if stats_blocks and blocks.index(stats_blocks[0]) != 1:
        fail(f"line {stats_blocks[0].line}: '# statistics' must follow "
             f"'# general' and precede the first '# block N:'")
    for i, b in enumerate(real, start=1):
        if b.num != i:
            fail(f"line {b.line}: block numbered {b.num} but is block {i}; "
                 f"blocks are numbered in order from 1")
        if not b.paras:
            fail(f"line {b.line}: block {b.num} has no paragraphs")
        for j, p in enumerate(b.paras, start=1):
            if p.num != j:
                fail(f"line {p.line}: paragraph numbered {p.num} but is "
                     f"paragraph {j} of its block")
            if p.has_text_part and not p.prose.strip():
                fail(f"line {p.line}: para {p.num} '{p.title}' has an empty "
                     f"'### text'")
    for b in blocks:
        if b.is_not_used and not b.steps:
            fail(f"line {b.line}: '# not used' block is empty; delete it or "
                 f"list the steps")


def check_silent_paras(blocks: list[Block]) -> None:
    """a paragraph may skip its prose only when it is pure plumbing, or when
    every reportable step it carries is described later ('at:')"""
    for b in blocks:
        for p in b.paras:
            if p.prose.strip():
                continue
            loud = [s for s in p.steps
                    if s.cls not in SILENT_CLASSES and not s.at]
            if loud:
                names = ", ".join(f"{s.var} [{s.cls}]" for s in loud[:3])
                fail(f"line {p.line}: para {p.num} '{p.title}' has no prose "
                     f"but carries reportable steps ({names}) — write the "
                     f"text, or reclassify")


def check_deferred(blocks: list[Block]) -> None:
    """a step keeps its place in pipeline order, while 'at:' moves its prose
    to the later paragraph that consumes what it produced. The target must be
    a unique paragraph title of this module, strictly later, and carry prose"""
    paras = [p for b in blocks if b.is_prose for p in b.paras]
    by_title: dict[str, list[int]] = {}
    for i, p in enumerate(paras):
        by_title.setdefault(p.title.strip().lower(), []).append(i)
    for b in blocks:
        if b.is_not_used:
            for s in b.steps:
                if s.at:
                    fail(f"line {s.line}: {s.var} is under '# not used' and "
                         f"cannot carry 'at:' — it never ran")
    for i, p in enumerate(paras):
        for s in p.steps:
            if not s.at:
                continue
            if s.cls in SILENT_CLASSES:
                fail(f"line {s.line}: {s.var} is '{s.cls}', which no prose "
                     f"describes; 'at:' is only for reportable steps")
                continue
            hits = by_title.get(s.at.strip().lower(), [])
            if not hits:
                fail(f"line {s.line}: {s.var} 'at: {s.at}' names no paragraph "
                     f"of this module — use a '## para' title as written")
                continue
            if len(hits) > 1:
                fail(f"line {s.line}: {s.var} 'at: {s.at}' matches "
                     f"{len(hits)} paragraphs; paragraph titles must be "
                     f"unique to be a target")
                continue
            target = paras[hits[0]]
            if hits[0] <= i:
                fail(f"line {s.line}: {s.var} 'at: {s.at}' points to its own "
                     f"or an earlier paragraph; prose may only move later, "
                     f"to where the step's output is consumed")
            elif not target.prose.strip():
                fail(f"line {s.line}: {s.var} 'at: {s.at}' targets a "
                     f"paragraph with no prose")


def check_numbering(blocks: list[Block]) -> None:
    """numbers run 1..N across the whole module, in document order.

    This is what makes the chronological rule enforceable: the sequence is the
    order the pipeline ran, so a gap or a swap is a reordering of the method.
    """
    numbered = [s for b in blocks if b.is_prose
                for p in b.paras for s in p.steps]
    for i, s in enumerate(numbered, start=1):
        if s.num != i:
            fail(f"line {s.line}: {s.var} is numbered {s.num} but is step {i} "
                 f"in document order; steps run 1..N in pipeline order")
            return
    for b in blocks:
        if not b.is_not_used:
            continue
        for s in b.steps:
            if s.num is not None:
                fail(f"line {s.line}: {s.var} is under '# not used' and must "
                     f"not be numbered — it never ran")


def check_classes(blocks: list[Block]) -> None:
    for b in blocks:
        steps = b.steps + [s for p in b.paras for s in p.steps]
        for s in steps:
            if b.is_not_used and s.cls != "not used":
                fail(f"line {s.line}: {s.var} is under '# not used' so its "
                     f"class must be 'not used', not '{s.cls}'")
            if b.is_prose and s.cls == "not used":
                fail(f"line {s.line}: {s.var} is classed 'not used' but sits "
                     f"in block {b.num}; move it to the '# not used' block")
            if not s.desc:
                fail(f"line {s.line}: {s.var} has no description")
            elif len(s.desc) > STEP_DESC_MAX:
                fail(f"line {s.line}: {s.var} description is "
                     f"{len(s.desc)} characters, over the {STEP_DESC_MAX} "
                     f"limit — one short sentence in the prose's own words; "
                     f"the detail belongs in the mk comment above the rule")


def check_duplicates(blocks: list[Block]) -> None:
    seen: dict[str, int] = {}
    for b in blocks:
        for s in b.steps + [x for p in b.paras for x in p.steps]:
            if s.var in seen:
                fail(f"line {s.line}: {s.var} already listed at line "
                     f"{seen[s.var]}; every step appears exactly once")
            else:
                seen[s.var] = s.line


#####################################################################################
# checks against the mk sources
#####################################################################################


def mk_declarations(module_dir: str, pattern: str = "*.mk") -> set[str] | None:
    if not os.path.isdir(module_dir):
        return None
    names = set()
    for path in sorted(glob.glob(os.path.join(module_dir, pattern))):
        with open(path) as f:
            for line in f:
                m = RE_MK_DECL.match(line)
                if m:
                    names.add(m.group(1))
    return names


def check_step_vars(blocks: list[Block], module_dirs: list[str]) -> None:
    """a step variable may be declared by another module: a pipeline routinely
    calls into one, and the step still belongs to whoever ran it"""
    declared: set[str] = set()
    for d in module_dirs:
        names = mk_declarations(d)
        if names is None:
            fail(f"module dir not found: {d}")
            continue
        declared |= names
    for b in blocks:
        for s in b.steps + [x for p in b.paras for x in p.steps]:
            if s.var not in declared:
                fail(f"line {s.line}: {s.var} is not declared in any .mk under "
                     f"{', '.join(module_dirs)} — renamed, a typo, or a module "
                     f"dir missing from --module-dir")


def check_note_vars(blocks: list[Block], module: str, module_dir: str) -> None:
    """tables: and params: name make variables, and must be interface ones"""
    declared = mk_declarations(module_dir, f"{module}_int.mk")
    if declared is None:
        return
    if not declared:
        fail(f"no {module}_int.mk under {module_dir}")
        return
    for b in blocks:
        for p in b.paras:
            for lineno, line in p.notes:
                s = line.strip()
                if s.startswith("//"):
                    continue
                key, _, rest = s.partition(":")
                key = key.strip().lower()
                if key not in NOTE_LIST_KEYS:
                    continue
                for name in (x.strip() for x in rest.split(",")):
                    if not name:
                        continue
                    if not RE_MK_DECL.match(name + "="):
                        fail(f"line {lineno}: '{name}' in {key}: is not a make "
                             f"variable name")
                    elif name not in declared:
                        fail(f"line {lineno}: {name} in {key}: is not declared "
                             f"in {module}_int.mk")


#####################################################################################
# tokens
#####################################################################################


class Token:
    def __init__(self, raw, ttype, scope, name, line, lead_in):
        self.raw = raw
        self.type = ttype
        self.scope = scope
        self.name = name
        self.line = line
        self.lead_in = lead_in

    @property
    def key(self):
        return self.name


def collect_tokens(blocks: list[Block], module: str,
                   imports: list[str]) -> list[Token]:
    """tokens live in prose only; anything else is an error"""
    allowed_scopes = {module} | set(imports)
    out = []
    for b in blocks:
        for p in b.paras:
            for lineno, line in p.text:
                for tm in TOKEN.finditer(line):
                    body = tm.group(1)
                    fields = body.split(":")
                    if len(fields) != 3 or not all(f.strip() for f in fields):
                        fail(f"line {lineno}: malformed token {{{{{body}}}}} — "
                             f"expected exactly 3 non-empty fields "
                             f"type:scope:name")
                        continue
                    ttype, scope, name = (f.strip() for f in fields)
                    if ttype in RETIRED_TYPES:
                        where = ("the '### steps' list" if ttype == "step"
                                 else f"'### notes' as a {ttype}s: entry")
                        fail(f"line {lineno}: '{ttype}' tokens are retired — "
                             f"move {{{{{body}}}}} to {where}")
                        continue
                    if ttype == SUPP_TYPE:
                        # supp tokens name a supp-marked artifact declared in
                        # that module's artifacts.json. scope may be any module,
                        # since a paper reference is pipeline-wide by nature.
                        if not scope:
                            fail(f"line {lineno}: {tm.group(0)} has an empty "
                                 f"scope; supp tokens are 'supp:MODULE:NAME'")
                            continue
                        out.append(Token(tm.group(0), ttype, scope, name,
                                         lineno, p.lead_in))
                        continue
                    if ttype not in RESOLVED_TYPES:
                        fail(f"line {lineno}: unknown token type '{ttype}' in "
                             f"{{{{{body}}}}} — known types: "
                             f"{', '.join(RESOLVED_TYPES + (SUPP_TYPE,))}")
                        continue
                    if scope not in allowed_scopes:
                        extra = (f"; declared imports: "
                                 f"{', '.join(sorted(imports))}"
                                 if imports else
                                 "; template declares no imports")
                        fail(f"line {lineno}: {tm.group(0)} scope '{scope}' "
                             f"is not the module ('{module}'){extra}")
                        continue
                    before = line[tm.start() - 1] if tm.start() > 0 else " "
                    after = line[tm.end()] if tm.end() < len(line) else " "
                    if before.isalnum() or after.isalnum():
                        fail(f"line {lineno}: {tm.group(0)} is embedded "
                             f"mid-word; it must stand free")
                        continue
                    out.append(Token(tm.group(0), ttype, scope, name, lineno,
                                     p.lead_in))
    return out


def check_stray_tokens(blocks: list[Block]) -> None:
    for b in blocks:
        for st in b.stats:
            if TOKEN.search(st.desc):
                fail(f"line {st.line}: '# statistics' descriptions must not "
                     f"carry {{{{…}}}} tokens")
        for p in b.paras:
            for lineno, line in p.notes:
                if TOKEN.search(line):
                    fail(f"line {lineno}: '### notes' must not carry {{{{…}}}} "
                         f"tokens; notes are never rendered or resolved")
            for s in p.steps:
                if TOKEN.search(s.desc):
                    fail(f"line {s.line}: step descriptions must not carry "
                         f"{{{{…}}}} tokens")


def check_statistics(blocks: list[Block], module: str,
                     tokens: list[Token]) -> dict[str, Stat]:
    """the '# statistics' block declares every key the prose cites, so the
    inventory, the prose and the stats rule stay in step. Imported keys are
    declared by the module that owns them, not here."""
    decls: dict[str, Stat] = {}
    for b in blocks:
        for st in b.stats:
            if st.name in decls:
                fail(f"line {st.line}: '{st.name}' is declared twice in "
                     f"'# statistics' (first at line {decls[st.name].line})")
                continue
            if not st.desc:
                fail(f"line {st.line}: '{st.name}' has no description")
            decls[st.name] = st

    own = [t for t in tokens if t.type in RESOLVED_TYPES and t.scope == module]
    for t in own:
        st = decls.get(t.key)
        if st is None:
            fail(f"line {t.line}: {t.raw} is not declared in the "
                 f"'# statistics' block — every key the prose cites is "
                 f"listed there with a short description")
        elif st.type != t.type:
            fail(f"line {t.line}: {t.raw} is a '{t.type}' but "
                 f"'# statistics' declares '{t.key}' as a '{st.type}' "
                 f"(line {st.line})")
    cited = {t.key for t in own}
    for name, st in decls.items():
        if name not in cited:
            fail(f"line {st.line}: '{name}' is declared in '# statistics' but "
                 f"no token cites it")
    return decls


def check_edit_comments(text: str) -> None:
    for m in EDIT_COMMENT.finditer(text):
        if POSIX_CLASS.match(m.group(1)):
            continue
        lineno = text[:m.start()].count("\n") + 1
        fail(f"line {lineno}: unresolved edit comment [[{m.group(1).strip()}]]")


def collect_citations(blocks: list[Block]) -> list[tuple[str, int, str]]:
    """collect Pandoc citation keys from prose, where citations are rendered"""
    found = []
    for b in blocks:
        for p in b.paras:
            for lineno, line in p.text:
                for cluster in CITATION_CLUSTER.finditer(line):
                    for match in CITATION_KEY.finditer(cluster.group(1)):
                        found.append((match.group(1), lineno, p.lead_in))
    return found


def load_reference_ids(ifn: str | None,
                       citations: list[tuple[str, int, str]]) -> set[str] | None:
    """validate a CSL JSON bibliography and return its Pandoc identifiers"""
    if not ifn:
        if citations:
            fail("template cites references but --ifn-references was not passed")
            return None
        return set()
    if not os.path.isfile(ifn):
        fail(f"references file not found: {ifn}")
        return set()
    try:
        with open(ifn) as f:
            records = json.load(f)
    except (OSError, json.JSONDecodeError) as e:
        fail(f"cannot read CSL JSON references {ifn}: {e}")
        return set()
    if not isinstance(records, list):
        fail(f"{ifn}: CSL JSON must be an array of reference objects")
        return set()

    ids = set()
    for i, record in enumerate(records, start=1):
        if not isinstance(record, dict):
            fail(f"{ifn}: reference {i} is not an object")
            continue
        key = str(record.get("id", "")).strip()
        if not key:
            fail(f"{ifn}: reference {i} has no 'id'")
        elif key in ids:
            fail(f"{ifn}: duplicate reference id '{key}'")
        else:
            ids.add(key)
    return ids


def check_citations(blocks: list[Block],
                    ifn_references: str | None) -> list[tuple[str, int, str]]:
    citations = collect_citations(blocks)
    ids = load_reference_ids(ifn_references, citations)
    if ids is None:
        return citations
    seen = set()
    for key, lineno, _lead_in in citations:
        if key not in ids and key not in seen:
            fail(f"line {lineno}: citation '@{key}' is absent from "
                 f"{ifn_references}")
        seen.add(key)
    return citations


def report_main_text_fixes(blocks: list[Block]) -> None:
    found = [(p.lead_in, " ".join(m.group(1).split()))
             for b in blocks for p in b.paras
             for m in MAIN_TEXT_FIX.finditer(p.prose)]
    if not found:
        return
    print(f"  main text fixes: {len(found)}")
    for lead_in, text in found:
        print(f"    {lead_in}: {text}")


def note_vars(blocks: list[Block], module: str, module_dir: str) -> set[str]:
    """the interface variables the notes name, which is the artifact candidate set"""
    declared = mk_declarations(module_dir, f"{module}_int.mk") or set()
    found = set()
    for b in blocks:
        for p in b.paras:
            for _lineno, line in p.notes:
                found |= set(RE_NOTE_VAR.findall(line))
    return found & declared


def report_artifacts(blocks: list[Block], module: str, module_dir: str | None,
                     ifn: str) -> None:
    """the shipped / omitted inventory, and the note entities it has not ruled on"""
    _mod, groups = artifacts_mod.load(ifn)
    flat = [a for g in groups for a in g.artifacts]
    n_shipped = sum(1 for a in flat if a.shipped)
    print(f"  artifacts: {n_shipped} shipped, {len(flat) - n_shipped} omitted "
          f"over {len(groups)} group(s)")
    for g in groups:
        for a in g.artifacts:
            tail = a.desc if a.shipped else a.reason
            print(f"    {a.status:<8} {a.name:<26} [{g.scope}] {tail}")

    # informational: an entity the prose introduces but the inventory never
    # decided on is the one gap a comprehensive list cannot see by itself
    if module_dir is None:
        return
    undecided = sorted(note_vars(blocks, module, module_dir)
                       - {a.var for a in flat})
    if undecided:
        print(f"  note entities not declared as artifacts: "
              f"{', '.join(undecided)}")


#####################################################################################
# values table
#####################################################################################


def load_values(ifn: str, required: bool = True) -> dict[str, str]:
    if not os.path.exists(ifn):
        if required:
            print(f"error: values table not found: {ifn}")
            sys.exit(1)
        print(f"warning: values table not found: {ifn} — every value it "
              f"would supply renders as NA")
        return {}
    values = {}
    with open(ifn) as f:
        header = f.readline().rstrip("\n").split("\t")
        if header[:2] != ["key", "value"]:
            print(f"error: {ifn} must start with a 'key\\tvalue' header, "
                  f"got {header}")
            sys.exit(1)
        for lineno, line in enumerate(f, start=2):
            line = line.rstrip("\n")
            if not line.strip():
                continue
            parts = line.split("\t")
            if len(parts) < 2:
                fail(f"{ifn} line {lineno}: not a key/value row: {line!r}")
                continue
            key, value = parts[0].strip(), parts[1].strip()
            if not key:
                fail(f"{ifn} line {lineno}: empty key")
                continue
            if value == "":
                fail(f"{ifn} line {lineno}: key '{key}' has an empty value")
                continue
            if key in values and values[key] != value:
                fail(f"{ifn} line {lineno}: key '{key}' redefined "
                     f"({values[key]!r} -> {value!r})")
            values[key] = value
    return values


def check_values(tokens: list[Token], values: dict[tuple[str, str], str],
                 supp_map: dict[tuple[str, str], str],
                 module: str, strict: bool) -> list[Token]:
    """report what the values table does not cover, and return it.

    Unresolved values do not block the compile unless --strict is given: a
    module is registered as soon as its template exists, so a section whose
    stats have not run yet must still render. The gaps surface as bold NA in
    the prose and as a Draft note at the head of every doc, which is louder
    in the compiled pdf than a refusal is in a terminal."""
    report = fail if strict else (
        lambda msg: print(f"warning: {msg}"))
    value_tokens = [t for t in tokens if t.type in RESOLVED_TYPES]
    supp_tokens = [t for t in tokens if t.type == SUPP_TYPE]
    required = {(t.scope, t.key) for t in value_tokens}
    unresolved, seen = [], set()
    for t in value_tokens:
        if (t.scope, t.key) in values or (t.scope, t.key) in seen:
            continue
        seen.add((t.scope, t.key))
        unresolved.append(t)
        report(f"line {t.line}: {t.raw} has no entry in the values table "
               f"for scope '{t.scope}'")
    for t in supp_tokens:
        if (t.scope, t.key) in supp_map or (t.scope, t.key) in seen:
            continue
        seen.add((t.scope, t.key))
        unresolved.append(t)
        report(f"line {t.line}: {t.raw} names no supp-marked artifact "
               f"'{t.key}' in module '{t.scope}' — mark it 'supp: true' in "
               f"the module's artifacts.json, or fix the reference")
    # only the module's own values are checked for unreferenced keys;
    # imported modules validate their own values via their own scan+compile
    own_extra = sorted(k for k in set(values) - required if k[0] == module)
    for _scope, name in own_extra:
        report(f"values table key '{name}' is not referenced by the template")
    return unresolved


#####################################################################################
# rendering
#####################################################################################


def tidy(s: str) -> str:
    s = re.sub(r"\s+", " ", s)
    # a dot that starts a word is part of it, as in a ".srt file", so only a dot
    # acting as punctuation loses the space in front of it
    s = re.sub(r"\s+\.(?![0-9A-Za-z])", ".", s)
    s = re.sub(r"\s+([,;:!?)\]])", r"\1", s)
    s = re.sub(r"([(\[])\s+", r"\1", s)
    return s.strip()


def reflow(text: str, width: int) -> str:
    out = []
    for para in re.split(r"\n\s*\n", text):
        lines = [l for l in para.split("\n") if l.strip()]
        if not lines:
            continue
        if any(STRUCTURED.match(l) for l in lines):
            out.append("\n".join(tidy(l) for l in lines))
            continue
        out.append("\n".join(textwrap.wrap(tidy(" ".join(lines)),
                                           width=width) or [""]))
    return "\n\n".join(out)


def substitute(text: str, values: dict[tuple[str, str], str],
               for_full: bool,
               supp_map: dict[tuple[str, str], str] | None = None) -> str:
    def repl(m):
        body = m.group(1)
        fields = [f.strip() for f in body.split(":")]
        if len(fields) != 3:
            return m.group(0)
        ttype, scope, name = fields
        if ttype == SUPP_TYPE:
            num = (supp_map or {}).get((scope, name))
            if num is None:
                return f"**{body}:NA**" if for_full else "**NA**"
            return f"`{body}:{num}`" if for_full else num
        key = (scope, name)
        # a value the stats rule has not produced renders bold, so a gap is
        # impossible to skim past in a compiled pdf
        if key not in values:
            return f"**{body}:NA**" if for_full else "**NA**"
        return f"`{body}:{values[key]}`" if for_full else values[key]

    return TOKEN.sub(repl, text)


def draft_banner(unresolved: list[Token], n_tokens: int, module: str) -> str:
    """the one line that says a section is not finished, in every output"""
    if not unresolved:
        return ""
    return (f"{DRAFT_MARK} {len(unresolved)} of {n_tokens} values are "
            f"unresolved and render as NA below. Run p_methods_stats to "
            f"measure {module} before using this section.**")


def render_paper_md(blocks: list[Block], values: dict[str, str],
                    width: int,
                    supp_map: dict[tuple[str, str], str] | None = None) -> str:
    real = [b for b in blocks if b.is_prose]
    multi = len(real) > 1
    parts = []
    for b in real:
        if multi:
            parts.append(f"### {b.heading}")
        for p in b.paras:
            prose = p.prose.strip()
            if not prose:
                continue
            body = substitute(prose, values, for_full=False, supp_map=supp_map)
            body = reflow(f"**{p.lead_in}.** {body}", width)
            parts.append(body)
    return "\n\n".join(parts).strip() + "\n"


def render_full_md(raw: str, values: dict[str, str],
                   supp_map: dict[tuple[str, str], str] | None = None) -> str:
    """the template as written, with every value substituted beside its token"""
    return substitute(raw, values, for_full=True, supp_map=supp_map).strip() + "\n"


def render_full_tex(blocks: list[Block], values: dict[str, str],
                    supp_map: dict[tuple[str, str], str] | None = None) -> str:
    """prose becomes LaTeX; steps and notes become % lines, present in the
    source and absent from a compiled PDF"""
    def comment(lines):
        out = []
        for _n, l in lines:
            s = l.strip()
            if not s:
                continue
            out.append("% " + re.sub(r"^//\s*", "", s))
        return "\n".join(out)

    parts = []
    for b in blocks:
        if b.is_general:
            parts.append("% general")
            parts.append(comment(b.meta))
            continue
        if b.is_statistics:
            parts.append("% statistics")
            parts.append("\n".join(
                f"% {st.name} [{st.type}]: {st.desc}" for st in b.stats))
            continue
        if b.is_not_used:
            parts.append("% not used")
            parts.append("\n".join(
                f"% {s.var} [{s.cls}]: {s.desc}" for s in b.steps))
            continue
        parts.append(f"\\subsubsection{{{escape_tex(b.heading)}}}")
        for p in b.paras:
            parts.append("\n".join(
                f"% {s.num or ''} {s.var} {s.bracket}: {s.desc}".strip()
                for s in p.steps))
            prose = p.prose.strip()
            if prose:
                body = substitute(prose, values, for_full=True, supp_map=supp_map)
                tex = convert_body(f"**{p.lead_in}.** {body}").rstrip()
                if tex:
                    parts.append(tex)
            if p.notes:
                parts.append(comment(p.notes))
    return "\n\n".join(x for x in parts if x).strip() + "\n"


#####################################################################################
# subcommands
#####################################################################################


def prepare(args):
    raw = open(args.ifn_template).read()
    check_edit_comments(raw)
    blocks = parse(raw)
    imports, tag = check_general(blocks, args.module,
                                 args.module_dir[0] if args.module_dir else None,
                                 args.module_ver)
    check_shape(blocks)
    check_numbering(blocks)
    check_classes(blocks)
    check_duplicates(blocks)
    check_deferred(blocks)
    check_silent_paras(blocks)
    check_stray_tokens(blocks)
    tokens = collect_tokens(blocks, args.module, imports)
    decls = check_statistics(blocks, args.module, tokens)
    citations = check_citations(blocks, args.ifn_references)
    if args.module_dir:
        check_step_vars(blocks, args.module_dir)
        check_note_vars(blocks, args.module, args.module_dir[0])
    return raw, blocks, tokens, citations, imports, decls, tag


def cmd_scan(args) -> None:
    """validate the template and report what it requires. Nothing is written:
    the key inventory is the template's own '# statistics' block, and a derived
    copy of it on disk would only drift."""
    _raw, blocks, tokens, citations, _imports, _decls, tag = prepare(args)
    flush(f"scan of {args.ifn_template}")

    seen = {}
    for t in tokens:
        if t.key not in seen:
            seen[t.key] = t
    rows = sorted(seen.values(), key=lambda t: (t.type, t.scope, t.key))

    n_stat = sum(1 for t in rows if t.type == "stat")
    n_steps = sum(len(p.steps) for b in blocks for p in b.paras)
    n_unused = sum(len(b.steps) for b in blocks if b.is_not_used)
    print(f"scanned {args.ifn_template}")
    print(f"  tag: {tag}"
          f"{' (pipeline not frozen, cannot export)' if tag == TAG_NONE else ''}")
    print(f"  blocks: {len([b for b in blocks if b.is_prose])}   "
          f"paragraphs: {sum(len(b.paras) for b in blocks)}")
    print(f"  steps: {n_steps} numbered, {n_unused} not used")
    deferred = [(p, s) for b in blocks for p in b.paras for s in p.steps
                if s.at]
    if deferred:
        print(f"  described later: {len(deferred)} step(s)")
        for p, s in deferred:
            print(f"    {s.num:02d} {s.var} ({p.lead_in}) -> {s.at}")
    print(f"  required keys: {n_stat} stat, {len(rows) - n_stat} setting")
    for t in rows:
        scope = "" if t.scope == args.module else f"{t.scope}:"
        print(f"    {t.type:<7} {scope}{t.key} <- {t.lead_in}")
    unique_citations = sorted({key for key, _line, _lead in citations})
    print(f"  citations: {len(unique_citations)} reference(s), "
          f"{len(citations)} mention(s)")
    for key in unique_citations:
        leads = sorted({lead for cited, _line, lead in citations if cited == key})
        print(f"    @{key} <- {', '.join(leads)}")
    if args.ifn_artifacts:
        report_artifacts(blocks, args.module,
                         args.module_dir[0] if args.module_dir else None,
                         args.ifn_artifacts)
    report_main_text_fixes(blocks)


def load_supp_map(args) -> dict[tuple[str, str], str]:
    """the pipeline-wide supp table numbering. auto-discovers methods.json and
    the methods dir from the template path when neither is passed explicitly,
    so the compile command in a module's _methods.mk needs no new flags."""
    ifn_methods = getattr(args, "ifn_methods", None)
    src_dir = getattr(args, "src_dir", None)
    if not ifn_methods and not src_dir:
        # a template lives at {src_dir}/{module}/{module}.md by convention
        guess = os.path.dirname(os.path.dirname(os.path.abspath(args.ifn_template)))
        cand = os.path.join(guess, "methods.json")
        if os.path.isfile(cand):
            ifn_methods = cand
            src_dir = guess
    if not ifn_methods or not src_dir:
        return {}
    return {(m, n): str(i)
            for m, n, i in artifacts_mod.enumerate_supp(ifn_methods, src_dir)}


def cmd_compile(args) -> None:
    raw, blocks, tokens, _citations, imports, _decls, tag = prepare(args)

    # an untagged template compiles: the pipeline's tag is cut once, after every
    # module is done, so requiring it here would block reading values against the
    # prose. keeping untagged work out of the paper belongs at manuscript export,
    # where the tag can also be checked against the repos it is meant to freeze;
    # that check is not built yet, so for now this is a warning only.
    if tag == TAG_NONE:
        print(f"note: {args.ifn_template} carries no tag; its pipeline has not "
              f"been frozen yet and must not be exported")

    own = load_values(args.ifn_values, required=args.strict)
    values: dict[tuple[str, str], str] = {
        (args.module, k): v for k, v in own.items()}

    provided = {args.module: args.ifn_values}
    for pair in args.ifn_import_values or []:
        scope, sep, path = pair.partition("=")
        scope, path = scope.strip(), path.strip()
        if not sep or not scope or not path:
            print(f"error: --ifn-import-values takes 'scope=path' pairs, "
                  f"got {pair!r}")
            sys.exit(1)
        if scope == args.module:
            print(f"error: --ifn-import-values scope {scope!r} is the module "
                  f"itself; use --ifn-values")
            sys.exit(1)
        if scope in provided:
            print(f"error: --ifn-import-values scope {scope!r} given twice")
            sys.exit(1)
        provided[scope] = path
        for k, v in load_values(path, required=args.strict).items():
            values[(scope, k)] = v

    missing = sorted(set(imports) - provided.keys())
    if missing:
        print(f"error: template imports {missing} but no "
              f"--ifn-import-values pair was passed for them")
        sys.exit(1)
    extra = sorted(provided.keys() - {args.module} - set(imports))
    if extra:
        print(f"error: --ifn-import-values passed for {extra} but the "
              f"template does not declare them under 'imports:'")
        sys.exit(1)

    supp_map = load_supp_map(args)
    unresolved = check_values(tokens, values, supp_map, args.module, args.strict)
    flush(f"compile of {args.ifn_template}")

    paper_md = render_paper_md(blocks, values, args.width, supp_map=supp_map)
    full_md = render_full_md(raw, values, supp_map=supp_map)
    full_tex = render_full_tex(blocks, values, supp_map=supp_map)

    # the draft note leads every output, including the paper: the pdf is how
    # the section gets read, so that is where an unfinished one must say so
    banner = draft_banner(unresolved, len({(t.scope, t.key) for t in tokens}),
                          args.module)
    if banner:
        print(f"warning: {banner.strip('*')}")
        paper_md = f"{banner}\n\n{paper_md}"
        full_md = f"{banner}\n\n{full_md}"
        full_tex = f"{convert_body(banner).strip()}\n\n{full_tex}"

    # the artifact inventory reaches the full docs only: the paper's prose never
    # describes what was shipped, and the full docs are read by a developer
    if args.ifn_artifacts:
        full_md += "\n" + artifacts_mod.render_artifacts_md(args.ifn_artifacts) + "\n"
        full_tex += "\n" + artifacts_mod.render_artifacts_tex(args.ifn_artifacts) + "\n"

    outputs = [
        (args.ofn_paper_md, paper_md),
        (args.ofn_paper_tex, convert_body(paper_md).strip() + "\n"),
        (args.ofn_full_md, full_md),
        (args.ofn_full_tex, full_tex),
    ]
    for ofn, body in outputs:
        os.makedirs(os.path.dirname(os.path.abspath(ofn)), exist_ok=True)
        with open(ofn, "w") as f:
            f.write(body)
        print(f"wrote {ofn}")
    report_main_text_fixes(blocks)


def main() -> None:
    ap = argparse.ArgumentParser(
        description=__doc__,
        formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = ap.add_subparsers(dest="cmd", required=True)

    s = sub.add_parser("scan", help="validate the template and report the "
                                    "stat/setting keys it requires")
    s.add_argument("--ifn-template", required=True)
    s.add_argument("--module", required=True)
    s.add_argument("--module-dir", default=[], nargs="+",
                   help="the module's own dir first, then any other module "
                        "dirs whose steps appear in the template")
    s.add_argument("--module-ver", default=None,
                   help="the module's version as make resolves it; pass "
                        "$({MODULE}_VER) so pipeline and config overrides are "
                        "seen. falls back to parsing the interface file")
    s.add_argument("--ifn-artifacts", default=None,
                   help="the module's artifacts.json; validated and reported "
                        "when given")
    s.add_argument("--ifn-references", default=None,
                   help="CSL JSON bibliography used to validate Pandoc "
                        "citation keys in prose")
    s.set_defaults(func=cmd_scan)

    c = sub.add_parser("compile", help="write the paper and full docs")
    c.add_argument("--ifn-template", required=True)
    c.add_argument("--ifn-values", required=True)
    c.add_argument("--ifn-import-values", default=[], nargs="+",
                   help="values from imported modules, as 'scope=path' pairs, "
                        "one per module named in the template's 'imports:' "
                        "line")
    c.add_argument("--ofn-paper-md", required=True)
    c.add_argument("--ofn-paper-tex", required=True)
    c.add_argument("--ofn-full-md", required=True)
    c.add_argument("--ofn-full-tex", required=True)
    c.add_argument("--module", required=True)
    c.add_argument("--module-dir", default=[], nargs="+",
                   help="the module's own dir first, then any other module "
                        "dirs whose steps appear in the template")
    c.add_argument("--module-ver", default=None,
                   help="the module's version as make resolves it; pass "
                        "$({MODULE}_VER) so pipeline and config overrides are "
                        "seen. falls back to parsing the interface file")
    c.add_argument("--ifn-artifacts", default=None,
                   help="the module's artifacts.json; its inventory is appended "
                        "to the full docs when given")
    c.add_argument("--ifn-references", default=None,
                   help="CSL JSON bibliography used to validate Pandoc "
                        "citation keys in prose")
    c.add_argument("--ifn-methods", default=None,
                   help="the pipeline's methods.json, needed to resolve "
                        "'supp:' tokens against a pipeline-wide table "
                        "numbering. auto-discovered from the template path "
                        "when omitted")
    c.add_argument("--src-dir", default=None,
                   help="the pipeline's methods dir, holding one "
                        "{module}/artifacts.json per module. auto-discovered "
                        "from the template path when omitted")
    c.add_argument("--width", type=int, default=90,
                   help="wrap width of the paper doc (default 90)")
    c.add_argument("--strict", action="store_true",
                   help="refuse to compile an unresolved value instead of "
                        "rendering it as NA behind a draft note. for the "
                        "final pass, when the section is meant to be done")
    c.set_defaults(func=cmd_compile)

    args = ap.parse_args()
    if not os.path.exists(args.ifn_template):
        print(f"error: template not found: {args.ifn_template}")
        sys.exit(1)
    args.func(args)


if __name__ == "__main__":
    main()
