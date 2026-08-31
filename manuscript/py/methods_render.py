#!/usr/bin/env python3
"""shared methods template parser / renderer for all makeshift modules.

A template is a structured document, not free prose:

    # general
    module: binning
    pipeline: long
    config: h40
    tag: methods/binning/v1.00
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
short enough to read beside the prose. `text` is the prose that reaches the
paper. `notes` never reaches the paper and is where output tables, parameters,
tool probes and reasoning live.

The file opens with a reserved `# general` block recording which module and
pipeline it describes, the tag the methods were last verified at, and the exact
dry-run commands the step list came from, so a step sequence can always be
traced back to the run that produced it.

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

The former `step`, `table` and `param` hints are retired: steps are the
`### steps` list and tables/params are `### notes` keys.

Subcommands:
  scan     validate a template and report the keys it requires
  compile  template + values -> paper.md, paper.tex, full.md, full.tex

Every anomaly is fatal. Nothing is warned about and left in the prose.
"""
from __future__ import annotations

import argparse
import glob
import os
import re
import sys
import textwrap

from methods_to_tex import convert_body, escape_tex

RESOLVED_TYPES = ("stat", "setting")
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
# a POSIX bracket class such as [[:space:]] is regex syntax, not an edit
# comment; notes recording a version parse are full of them
POSIX_CLASS = re.compile(r"^:[a-z]+:$")

# recognized keys in the general block; 'dry run' may repeat, one per file;
# 'imports' is an optional comma-separated list of module scopes cited by the
# template beyond the module's own
GENERAL_ONCE = ("module", "pipeline", "config", "tag")
GENERAL_OPTIONAL_ONCE = ("imports",)
GENERAL_MANY = ("dry run",)
GENERAL_ALL = GENERAL_ONCE + GENERAL_OPTIONAL_ONCE + GENERAL_MANY

# the git tag the methods were last verified at: major.minor, two minor digits,
# namespaced by module so it cannot collide with a code tag
RE_TAG = re.compile(r"^methods/([a-z][a-z0-9_]*)/v(\d+)\.(\d{2})$")

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

STRUCTURED = re.compile(r"^\s*([-*+]\s|\d+\.\s|[|>#])")

errors: list[str] = []


def fail(msg: str) -> None:
    errors.append(msg)


def flush(context: str) -> None:
    if not errors:
        return
    print(f"error: {context} failed with {len(errors)} problem(s):",
          file=sys.stderr)
    for e in errors:
        print(f"  - {e}", file=sys.stderr)
    sys.exit(1)


#####################################################################################
# model
#####################################################################################


class Step:
    def __init__(self, num, var, cls, loop, desc, line):
        self.num = num
        self.var = var
        self.cls = cls
        self.loop = loop
        self.desc = desc
        self.line = line


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
    """a bracket holds exactly one class, optionally plus 'loop: VAR'"""
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
                 f"optionally with 'loop: VAR'")
    if cls is None and not rejected:
        fail(f"line {lineno}: {var} has no class — one of "
             f"{', '.join(CLASSES)} is required")
    return cls, loop


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
            cls, loop = parse_classes(lineno, m.group(2), m.group(3))
            owner.steps.append(Step(int(m.group(1)), m.group(2), cls, loop,
                                    m.group(4).strip(), lineno))
            continue
        m = RE_STEP_UNNUMBERED.match(s)
        if m:
            cls, loop = parse_classes(lineno, m.group(1), m.group(2))
            owner.steps.append(Step(None, m.group(1), cls, loop,
                                    m.group(3).strip(), lineno))
            continue
        fail(f"line {lineno}: not a step line: {s[:60]!r} — expected "
             f"'NN  VAR  [class]: description' on one line")

    return blocks


#####################################################################################
# structural checks
#####################################################################################


def check_general(blocks: list[Block], module: str) -> list[str]:
    """the provenance header: what module, what pipeline, and the exact dry
    runs the step list was derived from. Returns the imports list (empty when
    the template declares no cross-module citations)."""
    generals = [b for b in blocks if b.is_general]
    if not generals:
        fail("template has no '# general' block; it must open with one "
             f"carrying {', '.join(GENERAL_ONCE)} and at least one 'dry run:'")
        return []
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
    tag = seen.get("tag")
    if tag is not None:
        m = RE_TAG.match(tag)
        if not m:
            fail(f"line {g.line}: tag '{tag}' is malformed — expected "
                 f"'methods/{module}/vN.NN'")
        elif m.group(1) != module:
            fail(f"line {g.line}: tag '{tag}' names module '{m.group(1)}' but "
                 f"the compile was invoked with '{module}'")
    if n_runs == 0:
        fail(f"line {g.line}: '# general' lists no 'dry run:' — record the "
             f"file and the exact command behind the step list")
    return imports


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
            if not p.steps:
                fail(f"line {p.line}: para {p.num} '{p.title}' has no steps")
            if p.has_text_part and not p.prose.strip():
                fail(f"line {p.line}: para {p.num} '{p.title}' has an empty "
                     f"'### text'")
    for b in blocks:
        if b.is_not_used and not b.steps:
            fail(f"line {b.line}: '# not used' block is empty; delete it or "
                 f"list the steps")


def check_silent_paras(blocks: list[Block]) -> None:
    """a paragraph may skip its prose only when it is pure plumbing"""
    for b in blocks:
        for p in b.paras:
            if p.prose.strip():
                continue
            loud = [s for s in p.steps if s.cls not in SILENT_CLASSES]
            if loud:
                names = ", ".join(f"{s.var} [{s.cls}]" for s in loud[:3])
                fail(f"line {p.line}: para {p.num} '{p.title}' has no prose "
                     f"but carries reportable steps ({names}) — write the "
                     f"text, or reclassify")


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
                    if ttype not in RESOLVED_TYPES:
                        fail(f"line {lineno}: unknown token type '{ttype}' in "
                             f"{{{{{body}}}}} — known types: "
                             f"{', '.join(RESOLVED_TYPES)}")
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

    own = [t for t in tokens if t.scope == module]
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


#####################################################################################
# values table
#####################################################################################


def load_values(ifn: str) -> dict[str, str]:
    if not os.path.exists(ifn):
        print(f"error: values table not found: {ifn}", file=sys.stderr)
        sys.exit(1)
    values = {}
    with open(ifn) as f:
        header = f.readline().rstrip("\n").split("\t")
        if header[:2] != ["key", "value"]:
            print(f"error: {ifn} must start with a 'key\\tvalue' header, "
                  f"got {header}", file=sys.stderr)
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
                 module: str) -> None:
    required = {(t.scope, t.key) for t in tokens}
    for t in tokens:
        if (t.scope, t.key) not in values:
            fail(f"line {t.line}: {t.raw} has no entry in the values table "
                 f"for scope '{t.scope}'")
    # only the module's own values are checked for unreferenced keys;
    # imported modules validate their own values via their own scan+compile
    own_extra = sorted(k for k in set(values) - required if k[0] == module)
    for _scope, name in own_extra:
        fail(f"values table key '{name}' is not referenced by the template")


#####################################################################################
# rendering
#####################################################################################


def tidy(s: str) -> str:
    s = re.sub(r"\s+", " ", s)
    s = re.sub(r"\s+([.,;:!?)\]])", r"\1", s)
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
               for_full: bool) -> str:
    def repl(m):
        body = m.group(1)
        fields = [f.strip() for f in body.split(":")]
        if len(fields) != 3:
            return m.group(0)
        _ttype, scope, name = fields
        key = (scope, name)
        if key not in values:
            return m.group(0)
        return f"`{body}:{values[key]}`" if for_full else values[key]

    return TOKEN.sub(repl, text)


def render_paper_md(blocks: list[Block], values: dict[str, str],
                    width: int) -> str:
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
            body = substitute(prose, values, for_full=False)
            body = reflow(f"**{p.lead_in}.** {body}", width)
            parts.append(body)
    return "\n\n".join(parts).strip() + "\n"


def render_full_md(raw: str, values: dict[str, str]) -> str:
    """the template as written, with every value substituted beside its token"""
    return substitute(raw, values, for_full=True).strip() + "\n"


def render_full_tex(blocks: list[Block], values: dict[str, str]) -> str:
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
                f"% {s.num or ''} {s.var} [{s.cls}"
                f"{', loop: ' + s.loop if s.loop else ''}]: {s.desc}".strip()
                for s in p.steps))
            prose = p.prose.strip()
            if prose:
                body = substitute(prose, values, for_full=True)
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
    imports = check_general(blocks, args.module)
    check_shape(blocks)
    check_numbering(blocks)
    check_classes(blocks)
    check_duplicates(blocks)
    check_silent_paras(blocks)
    check_stray_tokens(blocks)
    tokens = collect_tokens(blocks, args.module, imports)
    decls = check_statistics(blocks, args.module, tokens)
    if args.module_dir:
        check_step_vars(blocks, args.module_dir)
        check_note_vars(blocks, args.module, args.module_dir[0])
    return raw, blocks, tokens, imports, decls


def cmd_scan(args) -> None:
    """validate the template and report what it requires. Nothing is written:
    the key inventory is the template's own '# statistics' block, and a derived
    copy of it on disk would only drift."""
    _raw, blocks, tokens, _imports, _decls = prepare(args)
    flush(f"scan of {args.ifn_template}")

    seen = {}
    for t in tokens:
        if t.key not in seen:
            seen[t.key] = t
    rows = sorted(seen.values(), key=lambda t: (t.type, t.scope, t.key))

    n_stat = sum(1 for t in rows if t.type == "stat")
    n_steps = sum(len(p.steps) for b in blocks for p in b.paras)
    n_unused = sum(len(b.steps) for b in blocks if b.is_not_used)
    print(f"scanned {args.ifn_template}", file=sys.stderr)
    print(f"  blocks: {len([b for b in blocks if b.is_prose])}   "
          f"paragraphs: {sum(len(b.paras) for b in blocks)}", file=sys.stderr)
    print(f"  steps: {n_steps} numbered, {n_unused} not used",
          file=sys.stderr)
    print(f"  required keys: {n_stat} stat, {len(rows) - n_stat} setting",
          file=sys.stderr)
    for t in rows:
        scope = "" if t.scope == args.module else f"{t.scope}:"
        print(f"    {t.type:<7} {scope}{t.key} <- {t.lead_in}",
              file=sys.stderr)


def cmd_compile(args) -> None:
    raw, blocks, tokens, imports, _decls = prepare(args)

    own = load_values(args.ifn_values)
    values: dict[tuple[str, str], str] = {
        (args.module, k): v for k, v in own.items()}

    provided = {args.module: args.ifn_values}
    for pair in args.ifn_import_values or []:
        scope, sep, path = pair.partition("=")
        scope, path = scope.strip(), path.strip()
        if not sep or not scope or not path:
            print(f"error: --ifn-import-values takes 'scope=path' pairs, "
                  f"got {pair!r}", file=sys.stderr)
            sys.exit(1)
        if scope == args.module:
            print(f"error: --ifn-import-values scope {scope!r} is the module "
                  f"itself; use --ifn-values", file=sys.stderr)
            sys.exit(1)
        if scope in provided:
            print(f"error: --ifn-import-values scope {scope!r} given twice",
                  file=sys.stderr)
            sys.exit(1)
        provided[scope] = path
        for k, v in load_values(path).items():
            values[(scope, k)] = v

    missing = sorted(set(imports) - provided.keys())
    if missing:
        print(f"error: template imports {missing} but no "
              f"--ifn-import-values pair was passed for them", file=sys.stderr)
        sys.exit(1)
    extra = sorted(provided.keys() - {args.module} - set(imports))
    if extra:
        print(f"error: --ifn-import-values passed for {extra} but the "
              f"template does not declare them under 'imports:'",
              file=sys.stderr)
        sys.exit(1)

    check_values(tokens, values, args.module)
    flush(f"compile of {args.ifn_template}")

    paper_md = render_paper_md(blocks, values, args.width)
    outputs = [
        (args.ofn_paper_md, paper_md),
        (args.ofn_paper_tex, convert_body(paper_md).strip() + "\n"),
        (args.ofn_full_md, render_full_md(raw, values)),
        (args.ofn_full_tex, render_full_tex(blocks, values)),
    ]
    for ofn, body in outputs:
        os.makedirs(os.path.dirname(os.path.abspath(ofn)), exist_ok=True)
        with open(ofn, "w") as f:
            f.write(body)
        print(f"wrote {ofn}", file=sys.stderr)


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
    c.add_argument("--width", type=int, default=90,
                   help="wrap width of the paper doc (default 90)")
    c.set_defaults(func=cmd_compile)

    args = ap.parse_args()
    if not os.path.exists(args.ifn_template):
        print(f"error: template not found: {args.ifn_template}",
              file=sys.stderr)
        sys.exit(1)
    args.func(args)


if __name__ == "__main__":
    main()
