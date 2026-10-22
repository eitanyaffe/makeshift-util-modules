#!/usr/bin/env python3
"""Declare, measure, budget-check and copy the artifacts a pipeline ships
alongside its manuscript.

An artifact is a table, file or directory a reader can inspect. Each module in
the pipeline's methods registry declares its artifacts in a single json next to
its methods template:

    pipes/dev/p_{pipeline}/methods/{module}/artifacts.json

    {
      "module": "long",
      "groups": [
        { "id": "global", "keys": [],
          "artifacts": [
            { "name": "libraries", "var": "LONG_LIB_TABLE", "kind": "table",
              "desc": "one row per long-read library" } ] },
        { "id": "assembly", "keys": ["ASSEMBLY_ID"], "table": "LONG_ASSEMBLY_TABLE",
          "artifacts": [
            { "name": "contigs", "var": "ASSEMBLY_CONTIG_TABLE", "kind": "table",
              "desc": "per-contig length, coverage and circularity" },
            { "name": "assembly_fasta", "var": "ASSEMBLY_CONTIG_FILE", "kind": "fasta",
              "desc": "assembled contigs", "omit": "size" } ] }
      ]
    }

A group collects the artifacts that share one instantiation path. `keys` names
the dynamic variables and `table` the make variable holding one row per
instance; a group with no keys needs no table. Make resolves each artifact's
variable with every key bound to its own name, which yields a path template
this script instantiates per row.

Exported files are named for what they are, not for where they were produced:

    {module}/{artifact}/{key1}/../{keyN}{ext}

with the extension coming from `kind` and a single-instance artifact becoming
`{module}/{artifact}{ext}` directly. This is collision-free by construction,
so nothing has to check for it: `name` is validated unique across a module's
groups and `group_rows` deduplicates instances on the key tuple. What it gives
up is distinctness between two exports that differ in a path parameter no
group declares — the export directory is versioned by ARTIFACTS_VER, and one
export is one config at one code state.

Because the name no longer says where a file came from, `artifacts.txt`
carries the source path in a `src` column.

A `table` artifact may declare `columns`, a whitelist of the columns that
ship. It exists for the cohort tables the config builds, which carry internal
input paths beside the subject and timepoint fields a reader needs. The
whitelist is fail-closed: a column added upstream does not ship until someone
declares it.

Subcommands, in the order the make targets call them:

    groups    module:group pairs over every registered module that ships a json
    keys      the group's dynamic variable names        (make: reval binding)
    vars      the group's artifact variables            (make: reval targets)
    table     the group's instantiation table variable  (make: table path)
    measure   resolve, instantiate and size one group; appends to the work tables
    check     report the inventory and enforce the size budgets
    copy      copy the shipped instances, driven by the work table
    publish   write artifacts.txt, artifacts_class.txt and README.md
"""

import argparse
import json
import os
import re
import subprocess
import sys

import methods_registry


# why an artifact is not shipped. the note field carries the specifics
OMIT_REASONS = {
    "size": "exceeds the repository size budget",
    "derived": "superseded by another artifact",
    "internal": "intermediate, not interpretable on its own",
    "restricted": "not shareable",
}

# the exported extension, from the kind rather than the source name: two of the
# cohort tables reach us with no extension at all, and one rule beats sixteen
# modules each picking between .fa and .fasta. a dir keeps none
EXTS = {
    "table": ".txt",
    "fasta": ".fasta",
    "fastq": ".fq",
    "alignment": ".bam",
    "tree": ".nwk",
    "matrix": ".txt",
    "dir": "",
    "other": "",
}

KINDS = tuple(EXTS)

# supp indices are free-form but must be dot-separated numeric parts so the
# sort order matches human intuition (1 < 1.1 < 1.10 < 2 < 10). the parser
# rejects anything with letters or empty segments up front, and supp_sort_key
# assumes this shape
SUPP_INDEX_RE = re.compile(r"^\d+(\.\d+)*$")


def supp_sort_key(idx: str) -> tuple:
    """natural sort: each dot-separated part becomes an int, and a shorter
    prefix sorts before a longer extension of itself. so '1' precedes '1.1'
    which precedes '1.10' which precedes '2'."""
    return tuple(int(p) for p in idx.split("."))

# a column whitelist means reading the table, so it is for config-scale ones
PROJECT_MAX_BYTES = 64 * 1000 * 1000

# work tables, written by measure and consumed by check / copy / publish
WORK_SUBDIR = ".work"
INSTANCE_COLS = ["module", "group", "artifact", "kind", "status",
                 "tag", "size", "found", "columns", "rel", "src"]
CLASS_COLS = ["module", "group", "artifact", "kind", "keys", "status",
              "reason", "n", "total_size", "columns", "supp",
              "desc", "template"]

ERRORS: list[str] = []


#####################################################################################
# failing loud
#####################################################################################


def fail(msg: str) -> None:
    ERRORS.append(msg)


def flush(context: str) -> None:
    if not ERRORS:
        return
    print(f"error: {len(ERRORS)} problem(s) in {context}")
    for e in ERRORS:
        print(f"  - {e}")
    sys.exit(1)


def die(msg: str) -> None:
    # stderr, unlike the rest of the manuscript scripts: the groups, keys, vars
    # and table subcommands are read by $(shell ...), so an error on stdout
    # would be consumed as the group list or a variable name
    print(f"error: {msg}", file=sys.stderr)
    sys.exit(1)


#####################################################################################
# model
#####################################################################################


class Artifact:
    def __init__(self, d: dict, module: str, group: str):
        self.module = module
        self.group = group
        self.name = str(d.get("name", "")).strip()
        self.var = str(d.get("var", "")).strip()
        self.kind = str(d.get("kind", "table")).strip()
        self.desc = str(d.get("desc", "")).strip()
        self.omit = d.get("omit")
        self.superseded_by = d.get("superseded_by")
        self.note = str(d.get("note", "")).strip()
        self.columns = [str(c).strip() for c in d.get("columns", [])]
        # supp is either absent or a free-form index string. Numeric-with-dots
        # is recommended (1, 1.1, 2, 10) and is what supp_sort_key expects
        supp = d.get("supp")
        self.supp = "" if supp in (None, False) else str(supp).strip()
        self.unknown = sorted(set(d) - {"name", "var", "kind", "desc", "omit",
                                        "superseded_by", "note", "columns",
                                        "supp"})

    @property
    def shipped(self) -> bool:
        return self.omit is None

    @property
    def status(self) -> str:
        return "shipped" if self.shipped else "omitted"

    @property
    def is_dir(self) -> bool:
        return self.kind == "dir"

    @property
    def reason(self) -> str:
        """one line saying why the artifact is not shipped"""
        if self.shipped:
            return ""
        head = OMIT_REASONS[self.omit]
        if self.omit == "derived" and self.superseded_by:
            head = f"superseded by {self.superseded_by}"
        return f"{head}; {self.note}" if self.note else head


class Group:
    def __init__(self, d: dict, module: str):
        self.id = str(d.get("id", "")).strip()
        self.keys = [str(k).strip() for k in d.get("keys", [])]
        self.table = str(d.get("table", "")).strip()
        self.artifacts = [Artifact(a, module, self.id)
                          for a in d.get("artifacts", [])]

    @property
    def scope(self) -> str:
        return ":".join(self.keys) if self.keys else "global"


def validate(ifn: str, module: str, groups: list[Group]) -> None:
    if not module:
        fail(f"{ifn}: 'module' is required")
    if not groups:
        fail(f"{ifn}: 'groups' is empty")

    names: dict[str, str] = {}
    ids: set[str] = set()
    for g in groups:
        if not g.id:
            fail(f"{ifn}: a group has no 'id'")
        if g.id in ids:
            fail(f"{ifn}: group {g.id!r} declared twice")
        ids.add(g.id)
        if g.keys and not g.table:
            fail(f"{ifn}: group {g.id!r} has keys {g.keys} but no 'table' "
                 f"naming the make variable that holds one row per instance")
        if not g.keys and g.table:
            fail(f"{ifn}: group {g.id!r} has no keys, so 'table' is unused")
        if not g.artifacts:
            fail(f"{ifn}: group {g.id!r} declares no artifacts")

        group_vars: set[str] = set()
        for a in g.artifacts:
            where = f"{ifn}: {g.id}/{a.name or '<unnamed>'}"
            if not a.name:
                fail(f"{ifn}: an artifact in group {g.id!r} has no 'name'")
            if not a.var:
                fail(f"{where}: 'var' is required")
            if not a.desc:
                fail(f"{where}: 'desc' is required")
            if a.kind not in KINDS:
                fail(f"{where}: unknown kind {a.kind!r} — expected one of "
                     f"{', '.join(KINDS)}")
            if a.omit is not None and a.omit not in OMIT_REASONS:
                fail(f"{where}: unknown omit reason {a.omit!r} — expected one "
                     f"of {', '.join(OMIT_REASONS)}")
            if a.omit == "derived" and not a.superseded_by:
                fail(f"{where}: omit 'derived' requires 'superseded_by'")
            if a.superseded_by and a.omit != "derived":
                fail(f"{where}: 'superseded_by' only applies to omit 'derived'")
            if a.columns and a.kind != "table":
                fail(f"{where}: 'columns' selects columns, so it only "
                     f"applies to kind 'table'")
            if len(set(a.columns)) != len(a.columns):
                fail(f"{where}: 'columns' lists a column twice")
            if a.supp and a.kind != "table":
                fail(f"{where}: 'supp' marks a supplementary table, so it "
                     f"only applies to kind 'table'")
            if a.supp and not a.shipped:
                fail(f"{where}: 'supp' is set but the artifact is omitted; a "
                     f"supplementary table must ship")
            if a.supp and not SUPP_INDEX_RE.match(a.supp):
                fail(f"{where}: 'supp' index {a.supp!r} is malformed — use "
                     f"digits and dots (e.g. '1', '1.1', '10')")
            if a.unknown:
                fail(f"{where}: unknown field(s) {', '.join(a.unknown)}")
            if a.name in names:
                fail(f"{where}: name already used in group {names[a.name]!r}")
            names[a.name] = g.id
            if a.var in group_vars:
                fail(f"{where}: variable {a.var} declared twice in one group")
            group_vars.add(a.var)

    for g in groups:
        for a in g.artifacts:
            if a.superseded_by and a.superseded_by not in names:
                fail(f"{ifn}: {g.id}/{a.name}: superseded_by "
                     f"{a.superseded_by!r} names no artifact in this module")


def load(ifn: str) -> tuple[str, list[Group]]:
    if not os.path.exists(ifn):
        die(f"artifacts json not found: {ifn}")
    with open(ifn) as f:
        try:
            data = json.load(f)
        except json.JSONDecodeError as e:
            die(f"{ifn}: {e}")
    module = str(data.get("module", "")).strip()
    unknown = sorted(set(data) - {"module", "groups"})
    if unknown:
        fail(f"{ifn}: unknown top-level field(s) {', '.join(unknown)}")
    groups = [Group(g, module) for g in data.get("groups", [])]
    validate(ifn, module, groups)
    flush(ifn)
    return module, groups


def find_group(ifn: str, groups: list[Group], gid: str) -> Group:
    for g in groups:
        if g.id == gid:
            return g
    die(f"{ifn}: no group {gid!r} (have {', '.join(g.id for g in groups)})")


#####################################################################################
# paths and sizes
#####################################################################################


def key_re(key: str) -> re.Pattern:
    """a key matches only as a whole path token, so LIB_ID never eats RNA_LIB_ID"""
    return re.compile(r"(?<![A-Za-z0-9_])" + re.escape(key) + r"(?![A-Za-z0-9_])")


def instantiate(template: str, keys: list[str], row: dict) -> str:
    out = template
    for k in keys:
        out = key_re(k).sub(str(row[k]), out)
    return out


def dest_path(a: "Artifact", keys: list[str], row: dict) -> str:
    """where the artifact ships: module/artifact/key1/../keyN

    unique by construction, so nothing has to check for collisions: 'name' is
    validated unique across a module's groups, and group_rows deduplicates
    instances on the key tuple. with no keys the name is the file itself.
    """
    parts = [a.module]
    if keys:
        parts += [a.name] + [str(row[k]) for k in keys[:-1]]
        leaf = str(row[keys[-1]])
    else:
        leaf = a.name
    return os.path.join(*parts, leaf + EXTS[a.kind])


def under_mount(src: str, mount_dirs: list[str], config_dir: str) -> bool:
    """validation only: an artifact ships from the bucket or the config, and
    nowhere else. the export path no longer derives from this prefix"""
    src = os.path.normpath(src)
    roots = [os.path.normpath(m) for m in mount_dirs]
    if config_dir:
        roots.append(os.path.normpath(config_dir))
    return any(src.startswith(r + "/") for r in roots)


def dir_size(path: str) -> int:
    total = 0
    for root, _dirs, files in os.walk(path):
        for fn in files:
            try:
                total += os.path.getsize(os.path.join(root, fn))
            except OSError:
                pass
    return total


def project_table(src: str, columns: list[str]) -> str:
    """the table cut to its declared columns, which is what ships"""
    size = os.path.getsize(src)
    if size > PROJECT_MAX_BYTES:
        die(f"{src} is {human(size)}: 'columns' is for the config-scale "
            f"cohort tables, since projecting one means reading it")
    with open(src) as f:
        lines = [l.rstrip("\n") for l in f]
    if not lines:
        die(f"empty table: {src}")
    header = lines[0].split("\t")
    absent = [c for c in columns if c not in header]
    if absent:
        die(f"{src}: no column(s) {', '.join(absent)} — the whitelist names "
            f"columns the table does not have, so either it was renamed "
            f"upstream or the declaration is wrong")
    idx = [header.index(c) for c in columns]
    out = []
    for l in lines:
        fields = l.split("\t")
        out.append("\t".join(fields[i] if i < len(fields) else ""
                             for i in idx))
    return "\n".join(out) + "\n"


def measure_path(path: str, is_dir: bool, columns: list[str]) -> int:
    if is_dir:
        return dir_size(path) if os.path.isdir(path) else 0
    if not os.path.isfile(path):
        return 0
    if columns:
        return len(project_table(path, columns).encode())
    return os.path.getsize(path)


def human(n: float) -> str:
    for unit, scale in (("G", 1e9), ("M", 1e6), ("K", 1e3)):
        if n >= scale:
            return f"{n / scale:.1f}{unit}"
    return f"{int(n)}B"


#####################################################################################
# tab tables
#####################################################################################


def read_table(ifn: str) -> list[dict]:
    with open(ifn) as f:
        lines = [l.rstrip("\n") for l in f if l.strip()]
    if not lines:
        die(f"empty table: {ifn}")
    header = lines[0].split("\t")
    rows = []
    for l in lines[1:]:
        fields = l.split("\t")
        rows.append(dict(zip(header, fields)))
    return rows


def write_table(ofn: str, cols: list[str], rows: list[dict]) -> None:
    os.makedirs(os.path.dirname(os.path.abspath(ofn)), exist_ok=True)
    with open(ofn, "w") as f:
        f.write("\t".join(cols) + "\n")
        for r in rows:
            f.write("\t".join(str(r.get(c, "")) for c in cols) + "\n")


def append_table(ofn: str, cols: list[str], rows: list[dict]) -> None:
    with open(ofn, "a") as f:
        for r in rows:
            f.write("\t".join(str(r.get(c, "")) for c in cols) + "\n")


def work_paths(odir: str) -> tuple[str, str]:
    work = os.path.join(odir, WORK_SUBDIR)
    return os.path.join(work, "instances.txt"), os.path.join(work, "class.txt")


#####################################################################################
# queries used by the make loop
#####################################################################################


def enumerate_pairs(ifn_methods: str, src_dir: str, quiet: bool = False) -> list[str]:
    """every group of every registered module that ships a json, validating each"""
    _pipeline, entries = methods_registry.load(ifn_methods)
    pairs = []
    for entry in entries:
        module = entry.module
        ifn = os.path.join(src_dir, module, "artifacts.json")
        if not os.path.exists(ifn):
            if not quiet:
                print(f"note: {module} ships no artifacts.json")
            continue
        mod, groups = load(ifn)
        if mod != module:
            die(f"{ifn}: declares module {mod!r} but sits under {module!r}")
        pairs += [f"{module}:{g.id}" for g in groups]
    return pairs


def cmd_groups(args) -> None:
    # quiet: this stdout is the group list make loops over, so a note would
    # become a pair. init reports the modules shipping nothing instead
    print(" ".join(enumerate_pairs(args.ifn_methods, args.src_dir, quiet=True)))


def enumerate_supp(ifn_methods: str, src_dir: str) -> list[tuple[str, str, str]]:
    """pipeline-wide list of supp tables as (module, name, index) tuples. See
    enumerate_supp_full for the rich form."""
    return [(r["module"], r["name"], r["supp"])
            for r in enumerate_supp_full(ifn_methods, src_dir)]


def enumerate_supp_full(ifn_methods: str, src_dir: str) -> list[dict]:
    """pipeline-wide list of supp tables, sorted by supp_sort_key so a reader
    sees them in the same order the paper does. Each dict carries the index,
    the module, the artifact name, the make variable, the kind (for the
    exported extension), and the description. Duplicate indices fail loudly."""
    _pipeline, entries = methods_registry.load(ifn_methods)
    collected: list[dict] = []
    for entry in entries:
        module = entry.module
        ifn = os.path.join(src_dir, module, "artifacts.json")
        if not os.path.exists(ifn):
            continue
        mod, groups = load(ifn)
        if mod != module:
            die(f"{ifn}: declares module {mod!r} but sits under {module!r}")
        for g in groups:
            if a_supp_in_keyed_group(g):
                die(f"{ifn}: group {g.id!r} carries keys {g.keys}; supp tables "
                    f"must be keyless (a paper cites one table, not one per "
                    f"instance). move the supp artifact to a keyless group")
            for a in g.artifacts:
                if a.supp:
                    collected.append({"module": module, "name": a.name,
                                      "supp": a.supp, "var": a.var,
                                      "kind": a.kind, "desc": a.desc})
    seen: dict[str, tuple[str, str]] = {}
    for r in collected:
        idx = r["supp"]
        if idx in seen:
            m0, n0 = seen[idx]
            die(f"supp index {idx!r} is used by {m0}:{n0} and "
                f"{r['module']}:{r['name']}; each supp index must be unique "
                f"across the pipeline")
        seen[idx] = (r["module"], r["name"])
    return sorted(collected, key=lambda r: supp_sort_key(r["supp"]))


def a_supp_in_keyed_group(g: "Group") -> bool:
    return bool(g.keys) and any(a.supp for a in g.artifacts)


def cmd_supp(args) -> None:
    """one row per supp artifact: module, name, index. Stable across compiles
    for the same registry, and readable by methods_render.py at compile time."""
    for module, name, idx in enumerate_supp(args.ifn_methods, args.src_dir):
        print(f"{module}\t{name}\t{idx}")


def cmd_supp_vars(args) -> None:
    """space-separated list of the make variables that hold the source paths
    of the supp tables. the make rule expands each with $() and passes them
    to supp_export as 'MODULE:NAME=path' pairs."""
    rows = enumerate_supp_full(args.ifn_methods, args.src_dir)
    print(" ".join(f"{r['module']}:{r['name']}:{r['var']}" for r in rows))


def cmd_supp_export(args) -> None:
    """copy every supp table to supp_tables/supp_table_{index}_{name}.{ext},
    and write supp_tables.txt. this bypasses the full artifact measure/copy
    pass -- the manuscript ships supp tables far more often than a bundle,
    so they get their own light path."""
    rows = enumerate_supp_full(args.ifn_methods, args.src_dir)
    paths: dict[tuple[str, str], str] = {}
    for pair in args.pairs:
        head, sep, val = pair.partition("=")
        if not sep:
            die(f"expected MODULE:NAME=/path, got {pair!r}")
        mod, sep2, name = head.partition(":")
        if not sep2:
            die(f"expected MODULE:NAME=/path, got {pair!r}")
        paths[(mod.strip(), name.strip())] = val.strip()

    supp_dir = os.path.join(args.odir, "supp_tables")
    os.makedirs(supp_dir, exist_ok=True)
    published: list[dict] = []
    for r in rows:
        key = (r["module"], r["name"])
        src = paths.get(key)
        if not src:
            die(f"no --pairs entry for {r['module']}:{r['name']}; pass "
                f"'{r['module']}:{r['name']}=$({r['var']})' from make")
        if not os.path.isfile(src):
            die(f"supp source not found: {src} (for {r['module']}:{r['name']})")
        ext = EXTS.get(r["kind"], "")
        fn = f"supp_table_{r['supp']}_{r['name']}{ext}"
        rel = os.path.join("supp_tables", fn)
        dst = os.path.join(args.odir, rel)
        with open(src, "rb") as fs, open(dst, "wb") as fd:
            fd.write(fs.read())
        published.append({"supp": r["supp"], "path": rel,
                          "module": r["module"], "artifact": r["name"],
                          "src_path": src, "desc": r["desc"]})
        print(f"  {r['supp']:<6} {rel:<48} {human(os.path.getsize(src)):>8}")
    write_table(os.path.join(args.odir, "supp_tables.txt"),
                ["supp", "path", "module", "artifact", "src_path", "desc"],
                published)
    print(f"exported {len(published)} supp table(s) to {supp_dir}")


def publish_supp_folder(odir: str, classes: list[dict],
                        instances: list[dict]) -> None:
    """copy every supp table into 'supp_tables/table_{index}{ext}' beside the
    normal export, and write 'supp_tables.txt' at the bundle root mapping
    'Supp. Table N' to the file, its source and its description.

    hard copies rather than symlinks: a bundle that reviewers zip and email
    is not the place to trust link semantics."""
    supp_classes = {(c["module"], c["artifact"]): c
                    for c in classes if c.get("supp")}
    if not supp_classes:
        return
    supp_dir = os.path.join(odir, "supp_tables")
    os.makedirs(supp_dir, exist_ok=True)

    rows: list[dict] = []
    seen_indices: set[str] = set()
    for i in instances:
        if i["status"] != "shipped" or i["found"] != "1":
            continue
        key = (i["module"], i["artifact"])
        c = supp_classes.get(key)
        if c is None:
            continue
        idx = c["supp"]
        if idx in seen_indices:
            die(f"supp index {idx!r} appears more than once during publish; "
                f"a keyed group with per-instance supp tables is not supported")
        seen_indices.add(idx)
        ext = EXTS.get(c["kind"], "")
        rel = os.path.join("supp_tables", f"supp_table_{idx}_{i['artifact']}{ext}")
        src = os.path.join(odir, i["rel"])
        dst = os.path.join(odir, rel)
        if not os.path.isfile(src):
            die(f"supp source not exported: {src}")
        # a fresh publish overwrites a stale copy without symlink concerns
        with open(src, "rb") as fs, open(dst, "wb") as fd:
            fd.write(fs.read())
        rows.append({"supp": idx, "path": rel,
                     "module": i["module"], "artifact": i["artifact"],
                     "src_path": i["rel"], "desc": c["desc"]})
    rows.sort(key=lambda r: supp_sort_key(r["supp"]))
    write_table(os.path.join(odir, "supp_tables.txt"),
                ["supp", "path", "module", "artifact", "src_path", "desc"],
                rows)


def cmd_keys(args) -> None:
    _module, groups = load(args.ifn)
    print(" ".join(find_group(args.ifn, groups, args.group).keys))


def cmd_vars(args) -> None:
    _module, groups = load(args.ifn)
    g = find_group(args.ifn, groups, args.group)
    print(" ".join(a.var for a in g.artifacts))


def cmd_table(args) -> None:
    _module, groups = load(args.ifn)
    print(find_group(args.ifn, groups, args.group).table)


#####################################################################################
# measure
#####################################################################################


def parse_templates(tokens: list[str]) -> dict[str, str]:
    out = {}
    for tok in tokens:
        var, sep, val = tok.partition("=")
        if not sep:
            die(f"expected VAR=template, got {tok!r}")
        out[var.strip()] = val.strip()
    return out


def group_rows(g: Group, ifn_table: str) -> list[dict]:
    """one row per instance of the group, deduplicated on the key tuple"""
    if not g.keys:
        return [{}]
    if not ifn_table:
        die(f"group {g.id!r} needs --ifn-table (the resolved {g.table})")
    rows = read_table(ifn_table)
    missing = [k for k in g.keys if k not in rows[0]]
    if missing:
        die(f"{ifn_table}: no column(s) {', '.join(missing)} for group "
            f"{g.id!r}")
    seen, out = set(), []
    for r in rows:
        tup = tuple(r[k] for k in g.keys)
        if tup in seen:
            continue
        seen.add(tup)
        out.append({k: r[k] for k in g.keys})
    if len(out) < len(rows):
        print(f"  {len(rows)} rows collapse to {len(out)} distinct "
              f"{'/'.join(g.keys)}")
    return out


def cmd_measure(args) -> None:
    module, groups = load(args.ifn)
    g = find_group(args.ifn, groups, args.group)
    templates = parse_templates(args.templates)
    mount_dirs = args.mount_dirs.split()

    for a in g.artifacts:
        if a.var not in templates:
            die(f"no template passed for {a.var} (group {g.id!r})")
        # about the source, not the export: the export path carries the keys
        # structurally, so a key missing here means every instance reads the
        # same file and we would ship N identical copies under N names
        for k in g.keys:
            if not key_re(k).search(templates[a.var]):
                fail(f"{a.name}: {k} does not appear in the resolved source "
                     f"{templates[a.var]} — every instance would read the "
                     f"same file. declare {a.var} in a group whose keys it "
                     f"actually carries")
    flush(f"group {module}:{g.id}")

    rows = group_rows(g, args.ifn_table)
    print(f"{module}:{g.id} — {len(g.artifacts)} artifact(s) x {len(rows)} "
          f"instance(s) [{g.scope}]")

    instances, classes = [], []
    for a in g.artifacts:
        n_found, total = 0, 0
        for row in rows:
            src = instantiate(templates[a.var], g.keys, row)
            if not under_mount(src, mount_dirs, args.config_dir):
                fail(f"{a.name}: {src} is under neither the output mounts "
                     f"({args.mount_dirs}) nor the config dir "
                     f"({args.config_dir})")
                continue
            rel = dest_path(a, g.keys, row)
            size = measure_path(src, a.is_dir, a.columns)
            found = size > 0
            n_found += int(found)
            total += size
            tag = ":".join(f"{k}={row[k]}" for k in g.keys) or "global"
            instances.append({
                "module": module, "group": g.id, "artifact": a.name,
                "kind": a.kind, "status": a.status, "tag": tag,
                "size": size, "found": int(found),
                "columns": ",".join(a.columns), "rel": rel, "src": src})
        classes.append({
            "module": module, "group": g.id, "artifact": a.name,
            "kind": a.kind, "keys": ",".join(g.keys), "status": a.status,
            "reason": a.reason, "n": len(rows), "total_size": total,
            "columns": ",".join(a.columns),
            "supp": a.supp,
            "desc": a.desc, "template": templates[a.var]})
        missing = len(rows) - n_found
        print(f"  {a.status:<8} {a.name:<28} {human(total):>8}"
              f"{f'   {missing} missing' if missing else ''}")
        if missing and a.shipped and args.on_missing_file == "error":
            fail(f"{a.name}: {missing} of {len(rows)} instance(s) missing")
    flush(f"group {module}:{g.id}")

    ofn_inst, ofn_class = work_paths(args.odir)
    append_table(ofn_inst, INSTANCE_COLS, instances)
    append_table(ofn_class, CLASS_COLS, classes)


def cmd_init(args) -> None:
    # validating here rather than in the make expansion of the group list: a
    # $(shell) that dies leaves an empty loop, and the run would measure nothing
    if args.ifn_methods:
        pairs = enumerate_pairs(args.ifn_methods, args.src_dir)
        print(f"{len(pairs)} group(s) declared")
    ofn_inst, ofn_class = work_paths(args.odir)
    write_table(ofn_inst, INSTANCE_COLS, [])
    write_table(ofn_class, CLASS_COLS, [])


#####################################################################################
# check
#####################################################################################


def cmd_check(args) -> None:
    ofn_inst, ofn_class = work_paths(args.odir)
    instances = read_table(ofn_inst)
    classes = read_table(ofn_class)
    if not classes:
        die(f"nothing measured: {ofn_class} is empty")

    shipped = [c for c in classes if c["status"] == "shipped"]
    omitted = [c for c in classes if c["status"] == "omitted"]
    total = sum(int(c["total_size"]) for c in shipped)

    def report(rows, header, with_reason):
        if not rows:
            return
        print(f"\n{header}")
        for c in sorted(rows, key=lambda r: -int(r["total_size"])):
            scope = c["keys"] or "global"
            line = (f"  {c['module']:<10} {c['artifact']:<28} {scope:<24} "
                    f"{c['n']:>5} {human(int(c['total_size'])):>8}")
            print(f"{line}   {c['reason']}" if with_reason else line)

    report(shipped, "shipped", False)
    report(omitted, "omitted", True)

    n_files = sum(1 for i in instances
                  if i["status"] == "shipped" and i["found"] == "1")
    print(f"\ntotal shipped: {human(total)} over {n_files} file(s)")

    # a mirrored layout collides only when two instances resolve to one path
    seen: dict[str, str] = {}
    for i in instances:
        if i["status"] != "shipped":
            continue
        who = f"{i['module']}:{i['artifact']}[{i['tag']}]"
        if i["rel"] in seen:
            fail(f"{i['rel']} is the target of both {seen[i['rel']]} and {who}")
        seen[i["rel"]] = who

    cap_group = args.max_group_gb * 1e9
    for c in shipped:
        if int(c["total_size"]) > cap_group:
            fail(f"{c['module']}:{c['artifact']} totals "
                 f"{human(int(c['total_size']))} over {c['n']} instance(s), "
                 f"above the {args.max_group_gb:g} GB per-artifact cap — omit "
                 f"it or raise ARTIFACTS_MAX_GROUP_GB")
    if total > args.max_total_gb * 1e9:
        fail(f"the bundle totals {human(total)}, above the "
             f"{args.max_total_gb:g} GB cap — omit artifacts or raise "
             f"ARTIFACTS_MAX_TOTAL_GB")

    if not args.strict:
        if ERRORS:
            print(f"\n{len(ERRORS)} problem(s) would fail an export:")
            for e in ERRORS:
                print(f"  - {e}")
            ERRORS.clear()
        return
    flush("the artifact inventory")


#####################################################################################
# copy and publish
#####################################################################################


def copy_one(src: str, dst: str, is_dir: bool, columns: list[str]) -> None:
    if os.path.normpath(src) == os.path.normpath(dst):
        die(f"source and target are the same path: {src}")
    if columns:
        os.makedirs(os.path.dirname(dst), exist_ok=True)
        with open(dst, "w") as f:
            f.write(project_table(src, columns))
        return
    if is_dir:
        os.makedirs(dst, exist_ok=True)
        cmd = ["rsync", "-rt", src.rstrip("/") + "/", dst.rstrip("/") + "/"]
    else:
        os.makedirs(os.path.dirname(dst), exist_ok=True)
        cmd = ["rsync", "-rt", src, dst]
    subprocess.run(cmd, check=True)


def cmd_copy(args) -> None:
    ofn_inst, _ofn_class = work_paths(args.odir)
    instances = [i for i in read_table(ofn_inst) if i["status"] == "shipped"]
    total = sum(int(i["size"]) for i in instances)
    print(f"copying {len(instances)} instance(s), {human(total)} to "
          f"{args.odir}")

    done = 0
    for i in instances:
        dst = os.path.join(args.odir, i["rel"])
        if i["found"] != "1":
            msg = f"missing: {i['module']}:{i['artifact']}[{i['tag']}] {i['src']}"
            if args.on_missing_file == "error":
                die(msg)
            print(f"warning: {msg}")
            continue
        columns = i["columns"].split(",") if i["columns"] else []
        copy_one(i["src"], dst, i["kind"] == "dir", columns)
        done += 1
        print(f"  [{done}/{len(instances)}] {human(int(i['size'])):>8}  "
              f"{i['rel']}")
    print(f"copied {done} of {len(instances)} instance(s)")


README = """# {pipeline} / {config} artifacts

Tables and files produced by the `{pipeline}` pipeline, exported so that the
results can be inspected directly. Code state: `{tag}`.

## Files

- `artifacts_class.txt` — one row per declared artifact, including the ones
  that were **not** exported and why. Columns: `module`, `artifact`, `kind`,
  `keys` (the dynamic fields, empty for a single global instance), `status`,
  `reason`, `n` (instances), `total_size` (bytes), `columns` (set when only
  the listed columns of the source table were exported), `desc`.
- `artifacts.txt` — one row per exported file: `module`, `artifact`, `tag`
  (the dynamic field values), `path` (relative to this directory), `size` in
  bytes and `src` (the path it was produced at inside the pipeline).
- the data itself, one directory per module. An artifact with a single
  instance is a file named after it (`long/subjects.txt`); one with several is
  a directory named after it holding a file per instance, named by the
  instance key (`long/library_fastq/L1.fq`, `minimap/alignment/S1/L1.bam`).

## Reading it

Every table is tab-separated with a header line. To find an artifact, look up
its description in `artifacts_class.txt`, then filter `artifacts.txt` on the
`artifact` column:

```bash
awk -F'\\t' 'NR==1 || $2=="contigs"' artifacts.txt
```

The methods section describes how each artifact was produced.
"""


def cmd_publish(args) -> None:
    ofn_inst, ofn_class = work_paths(args.odir)
    instances = read_table(ofn_inst)
    classes = read_table(ofn_class)

    # src travels with the row: the exported name no longer encodes where the
    # file came from, so this column is the only provenance a reader has
    shipped = [{"module": i["module"], "artifact": i["artifact"],
                "tag": i["tag"], "path": i["rel"], "size": i["size"],
                "src": i["src"]}
               for i in instances
               if i["status"] == "shipped" and i["found"] == "1"]
    write_table(os.path.join(args.odir, "artifacts.txt"),
                ["module", "artifact", "tag", "path", "size", "src"], shipped)
    write_table(os.path.join(args.odir, "artifacts_class.txt"),
                ["module", "artifact", "kind", "keys", "status", "reason",
                 "n", "total_size", "columns", "supp", "desc"], classes)

    publish_supp_folder(args.odir, classes, instances)

    ofn = os.path.join(args.odir, "README.md")
    with open(ofn, "w") as f:
        f.write(README.format(pipeline=args.pipeline, config=args.config,
                              tag=args.tag))
    print(f"published {len(shipped)} instance(s) and {len(classes)} "
          f"declaration(s) to {args.odir}")


#####################################################################################
# the methods section, rendered into the full docs only
#####################################################################################


def artifacts_lines(ifn: str) -> list[str]:
    """the '# artifacts' inventory: what the module ships and what it withholds"""
    module, groups = load(ifn)
    lines = ["# artifacts", ""]
    for g in groups:
        lines.append(f"// {g.id} [{g.scope}]")
        for a in g.artifacts:
            supp = f" [supp {a.supp}]" if a.supp else ""
            head = f"{a.name}{supp} [{a.kind}]: {a.desc}"
            if a.columns:
                head += f" (columns: {', '.join(a.columns)})"
            lines.append(head if a.shipped
                         else f"{head} -- omitted, {a.reason}")
        lines.append("")
    return lines[:-1]


def render_artifacts_md(ifn: str) -> str:
    return "\n".join(artifacts_lines(ifn))


def render_artifacts_tex(ifn: str) -> str:
    """commented, like the other non-prose blocks: in the source, out of the pdf"""
    out = []
    for l in artifacts_lines(ifn):
        out.append("% " + re.sub(r"^//\s*", "", l) if l else "%")
    return "\n".join(out)


#####################################################################################
# main
#####################################################################################


def main() -> None:
    # stdout is block-buffered when it is a pipe, which would flush the copy
    # log after the rsync output it labels
    sys.stdout.reconfigure(line_buffering=True)
    ap = argparse.ArgumentParser(
        description=__doc__,
        formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = ap.add_subparsers(dest="cmd", required=True)

    s = sub.add_parser("groups", help="module:group pairs for the make loop")
    s.add_argument("--ifn-methods", required=True,
                   help="the pipeline's methods.json; its modules[] is the "
                        "module list")
    s.add_argument("--src-dir", required=True,
                   help="the pipeline's methods dir, holding "
                        "{module}/artifacts.json")
    s.set_defaults(func=cmd_groups)

    s = sub.add_parser("supp", help="pipeline-wide supp table numbering: "
                                    "one 'module<tab>name<tab>index' row per "
                                    "artifact carrying a 'supp' index")
    s.add_argument("--ifn-methods", required=True)
    s.add_argument("--src-dir", required=True)
    s.set_defaults(func=cmd_supp)

    s = sub.add_parser("supp_vars", help="space-separated 'MODULE:NAME:VAR' "
                                          "triples for the make foreach that "
                                          "resolves each supp path")
    s.add_argument("--ifn-methods", required=True)
    s.add_argument("--src-dir", required=True)
    s.set_defaults(func=cmd_supp_vars)

    s = sub.add_parser("supp_export", help="copy supp tables to "
                                            "supp_tables/ and write "
                                            "supp_tables.txt")
    s.add_argument("--ifn-methods", required=True)
    s.add_argument("--src-dir", required=True)
    s.add_argument("--odir", required=True)
    s.add_argument("pairs", nargs="*", metavar="MODULE:NAME=/path",
                   help="the source path of each supp table, produced by the "
                        "make foreach over supp_vars")
    s.set_defaults(func=cmd_supp_export)

    for name, fn, helptext in (
            ("keys", cmd_keys, "the group's dynamic variable names"),
            ("vars", cmd_vars, "the group's artifact variables"),
            ("table", cmd_table, "the group's instantiation table variable")):
        s = sub.add_parser(name, help=helptext)
        s.add_argument("--ifn", required=True)
        s.add_argument("--group", required=True)
        s.set_defaults(func=fn)

    s = sub.add_parser("init", help="validate every json and truncate the "
                                    "work tables")
    s.add_argument("--odir", required=True)
    s.add_argument("--ifn-methods", default=None)
    s.add_argument("--src-dir", default="")
    s.set_defaults(func=cmd_init)

    s = sub.add_parser("measure", help="resolve, instantiate and size a group")
    s.add_argument("--ifn", required=True)
    s.add_argument("--group", required=True)
    s.add_argument("--odir", required=True)
    s.add_argument("--mount-dirs", required=True,
                   help="output mount roots, space separated")
    s.add_argument("--config-dir", default="")
    s.add_argument("--ifn-table", default="",
                   help="the resolved instantiation table; required when the "
                        "group has keys")
    s.add_argument("--on-missing-file", default="warning",
                   choices=("error", "warning"))
    s.add_argument("templates", nargs="*", metavar="VAR=template",
                   help="each artifact variable as make resolved it, with "
                        "every key bound to its own name")
    s.set_defaults(func=cmd_measure)

    s = sub.add_parser("check", help="report the inventory, enforce the budgets")
    s.add_argument("--odir", required=True)
    s.add_argument("--max-group-gb", type=float, default=1.0)
    s.add_argument("--max-total-gb", type=float, default=45.0)
    s.add_argument("--strict", action="store_true",
                   help="fail on a budget breach instead of reporting it")
    s.set_defaults(func=cmd_check)

    s = sub.add_parser("copy", help="copy the shipped instances")
    s.add_argument("--odir", required=True)
    s.add_argument("--on-missing-file", default="error",
                   choices=("error", "warning"))
    s.set_defaults(func=cmd_copy)

    s = sub.add_parser("publish", help="write the published tables and README")
    s.add_argument("--odir", required=True)
    s.add_argument("--pipeline", required=True)
    s.add_argument("--config", required=True)
    s.add_argument("--tag", default="none")
    s.set_defaults(func=cmd_publish)

    args = ap.parse_args()
    args.func(args)


if __name__ == "__main__":
    main()
