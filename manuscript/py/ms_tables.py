#!/usr/bin/env python3
"""Place, generate and export the numbered tables of a manuscript.

Placement is a property of the config, like figures, and sits beside
figures.json:

    configs/{lab}/metagenomics/{config}/manuscript/tables.json

    {
      "tables":      [ ... ],
      "supp_tables": [
        { "name": "cme_ann_labels",
          "title": "Annotation label vocabulary",
          "module": "cme_ann",
          "target": "",
          "var": "CME_ANN_LABELS",
          "caption": "One row per identifier ...",
          "columns": [ { "name": "label", "desc": "..." } ] }
      ]
    }

Array order is the number: `tables` are Table 1, 2, ... and `supp_tables` are
Supp. Table 1, 2, ... Nothing is numbered by hand, so inserting an entry
renumbers what follows it, here and in every methods section citing it.

Per entry: `name` (the exported file stem and the key a methods template cites
as `{{supp:MODULE:NAME}}`), `title`, `module` (the name make knows the owning
module by), `target` (the module rule that builds the table, empty for a
tracked table no rule writes), `var` (the make variable holding its path),
`caption`, and `columns`.

The pipeline table is the manuscript table as it stands: the json describes
every column and selects, renames or reorders none. `columns` must match the
file header exactly, so a column added or renamed upstream fails the export
until someone documents it.

An entry with an empty `module`, `var` and `columns` is a stub: it holds its
number for a table that is not built yet, and is skipped by generation and
export.

Subcommands, as the make targets call them:

    vars     MODULE:NAME:VAR triples, for make to resolve each path
    run      build the selected tables by calling each entry's module target
    export   check, copy and convert every table, and write tables.md
"""

import argparse
import json
import os
import re
import shutil
import subprocess
import sys

TOP_FIELDS = ("tables", "supp_tables")
ENTRY_FIELDS = ("name", "title", "module", "target", "var", "caption", "columns")
COLUMN_FIELDS = ("name", "desc")
NAME_RE = re.compile(r"^[A-Za-z0-9_]+$")

# a cell that is a plain number, excluding ids that only look like one: a
# leading zero or more digits than a double keeps exactly
NUMBER_RE = re.compile(r"^-?(\d+\.?\d*|\.\d+)([eE][-+]?\d+)?$")
LEADING_ZERO_RE = re.compile(r"^-?0\d")
MAX_DIGITS = 15
EMPTY_CELLS = ("", "NA")


def die(msg: str) -> None:
    # stderr: the vars subcommand is read by $(shell ...), so an error on
    # stdout would be consumed as a variable triple
    print(f"error: {msg}", file=sys.stderr)
    sys.exit(1)


#####################################################################################
# model
#####################################################################################


class Entry:
    def __init__(self, d: dict, supp: bool, number: int, ifn: str):
        self.supp = supp
        self.number = number
        where = f"{ifn}: {self.label}"
        if not isinstance(d, dict):
            die(f"{where}: an entry must be an object")
        unknown = sorted(set(d) - set(ENTRY_FIELDS))
        if unknown:
            die(f"{where}: unknown field(s) {', '.join(unknown)}")
        self.name = str(d.get("name", "")).strip()
        self.title = str(d.get("title", "")).strip()
        self.module = str(d.get("module", "")).strip()
        self.target = str(d.get("target", "")).strip()
        self.var = str(d.get("var", "")).strip()
        self.caption = " ".join(str(d.get("caption", "")).split())
        columns = d.get("columns", [])
        if not isinstance(columns, list):
            die(f"{where}: 'columns' must be an array")
        self.columns: list[tuple[str, str]] = []
        for c in columns:
            if not isinstance(c, dict):
                die(f"{where}: a column must be an object with 'name' and 'desc'")
            unknown = sorted(set(c) - set(COLUMN_FIELDS))
            if unknown:
                die(f"{where}: unknown column field(s) {', '.join(unknown)}")
            cname = str(c.get("name", "")).strip()
            cdesc = " ".join(str(c.get("desc", "")).split())
            if not cname or not cdesc:
                die(f"{where}: every column needs a 'name' and a 'desc'")
            self.columns.append((cname, cdesc))
        self.validate(where)

    @property
    def label(self) -> str:
        return f"Supp. Table {self.number}" if self.supp else f"Table {self.number}"

    @property
    def key(self) -> str:
        """what x= selects the entry by"""
        return f"supp{self.number}" if self.supp else str(self.number)

    @property
    def stem(self) -> str:
        head = "Supp_Table" if self.supp else "Table"
        return f"{head}_{self.number}_{self.name}"

    @property
    def is_stub(self) -> bool:
        return not self.module and not self.var and not self.columns

    def validate(self, where: str) -> None:
        if not self.name:
            die(f"{where}: 'name' is required")
        if not NAME_RE.match(self.name):
            die(f"{where}: name {self.name!r} must be letters, digits and "
                f"underscores, since it is the exported file stem")
        if not self.title:
            die(f"{where}: 'title' is required")
        if self.is_stub:
            if self.target:
                die(f"{where}: a stub has no module, so 'target' must be empty")
            return
        for field in ("module", "var", "caption"):
            if not getattr(self, field):
                die(f"{where}: '{field}' is required (leave module, var and "
                    f"columns all empty to hold the number with a stub)")
        if not self.columns:
            die(f"{where}: 'columns' is empty — every column of the table "
                f"must be described")
        names = [n for n, _d in self.columns]
        dup = sorted({n for n in names if names.count(n) > 1})
        if dup:
            die(f"{where}: column(s) {', '.join(dup)} described twice")


def load(ifn: str) -> list[Entry]:
    """main tables then supp tables, each numbered by its array position"""
    if not os.path.exists(ifn):
        die(f"tables json not found: {ifn}")
    with open(ifn) as f:
        try:
            data = json.load(f)
        except json.JSONDecodeError as e:
            die(f"{ifn}: {e}")
    unknown = sorted(set(data) - set(TOP_FIELDS))
    if unknown:
        die(f"{ifn}: unknown top-level field(s) {', '.join(unknown)}")
    entries: list[Entry] = []
    for field, supp in (("tables", False), ("supp_tables", True)):
        items = data.get(field, [])
        if not isinstance(items, list):
            die(f"{ifn}: '{field}' must be an array")
        entries += [Entry(d, supp, i + 1, ifn) for i, d in enumerate(items)]
    seen: dict[tuple[str, str], str] = {}
    for e in entries:
        if e.is_stub:
            continue
        pair = (e.module, e.name)
        if pair in seen:
            die(f"{ifn}: {e.module}:{e.name} is placed twice, as "
                f"{seen[pair]} and {e.label}")
        seen[pair] = e.label
    return entries


def supp_numbers(ifn: str) -> dict[tuple[str, str], str]:
    """(module, name) -> number of each supp table, for the methods compile"""
    return {(e.module, e.name): str(e.number)
            for e in load(ifn) if e.supp and not e.is_stub}


def select(entries: list[Entry], x: str) -> list[Entry]:
    """x=all or empty -> every entry; otherwise space/comma-separated keys"""
    x = (x or "").replace(",", " ").strip()
    if x in ("", "all"):
        return entries
    wanted = x.split()
    known = {e.key: e for e in entries}
    missing = [k for k in wanted if k not in known]
    if missing:
        die(f"unknown table(s): {', '.join(missing)}\n"
            f"  placed: {', '.join(known) or '(none)'} "
            f"(N is Table N, suppN is Supp. Table N)")
    return [known[k] for k in dict.fromkeys(wanted)]


#####################################################################################
# vars and run
#####################################################################################


def cmd_vars(args) -> None:
    print(" ".join(f"{e.module}:{e.name}:{e.var}"
                   for e in load(args.ifn) if not e.is_stub))


def cmd_run(args) -> None:
    selected = select(load(args.ifn), args.x)
    # one module rule may build several tables, so each rule runs once
    calls: dict[tuple[str, str], list[str]] = {}
    for e in selected:
        if e.is_stub:
            print(f"{e.label} ({e.name}): stub, skipped")
        elif not e.target:
            print(f"{e.label} ({e.name}): tracked table, no rule to run")
        else:
            calls.setdefault((e.module, e.target), []).append(e.label)
    for (module, target), labels in calls.items():
        cmd = [args.make, f"m={module}", target, f"c={args.c}"]
        print("=" * 80)
        print(f"{', '.join(labels)}: {' '.join(cmd)}")
        print("=" * 80)
        subprocess.run(cmd, check=True)
    print(f"done: {len(calls)} rule(s) over {len(selected)} table(s)")


#####################################################################################
# export
#####################################################################################


def parse_pairs(tokens: list[str]) -> dict[tuple[str, str], str]:
    paths = {}
    for tok in tokens:
        head, sep, val = tok.partition("=")
        module, sep2, name = head.partition(":")
        if not sep or not sep2:
            die(f"expected MODULE:NAME=/path, got {tok!r}")
        paths[(module.strip(), name.strip())] = val.strip()
    return paths


def read_table(src: str, label: str) -> tuple[list[str], list[list[str]]]:
    with open(src) as f:
        lines = [l.rstrip("\n") for l in f]
    while lines and not lines[-1]:
        lines.pop()
    if not lines:
        die(f"{label}: empty table {src}")
    header = lines[0].split("\t")
    rows = [l.split("\t") for l in lines[1:]]
    for i, r in enumerate(rows):
        if len(r) != len(header):
            die(f"{label}: {src} line {i + 2} has {len(r)} field(s), the "
                f"header has {len(header)}")
    return header, rows


def check_header(e: Entry, header: list[str], src: str, ifn: str) -> None:
    """the json describes the table as it stands, so the two must agree"""
    declared = [n for n, _d in e.columns]
    if declared == header:
        return
    lines = [f"{e.label} ({e.name}): the columns in {ifn} do not match the "
             f"header of {src}"]
    undocumented = [c for c in header if c not in declared]
    absent = [c for c in declared if c not in header]
    if undocumented:
        lines.append(f"  in the table, not described: {', '.join(undocumented)}")
    if absent:
        lines.append(f"  described, not in the table: {', '.join(absent)}")
    if not undocumented and not absent:
        lines.append(f"  same columns, different order: table has "
                     f"{', '.join(header)}")
    die("\n".join(lines))


def is_number(cell: str) -> bool:
    if not NUMBER_RE.match(cell) or LEADING_ZERO_RE.match(cell):
        return False
    # significant digits of the mantissa
    mantissa = re.split("[eE]", cell)[0].lstrip("-").replace(".", "")
    return len(mantissa.lstrip("0")) <= MAX_DIGITS


def numeric_columns(header: list[str], rows: list[list[str]]) -> list[bool]:
    """a column is written as numbers only when every filled cell is one"""
    out = []
    for j in range(len(header)):
        cells = [r[j] for r in rows if r[j] not in EMPTY_CELLS]
        out.append(bool(cells) and all(is_number(c) for c in cells))
    return out


def to_number(cell: str):
    return int(cell) if re.match(r"^-?\d+$", cell) else float(cell)


def write_xlsx(ofn: str, e: Entry, header: list[str],
               rows: list[list[str]]) -> None:
    try:
        import xlsxwriter
    except ImportError:
        die("the xlsx export needs the python package xlsxwriter, which the "
            "makeshift image ships; run the export inside the container")
    # cells are written with an explicit type, so nothing is re-interpreted
    # the way a spreadsheet does when it opens text (gene names as dates)
    book = xlsxwriter.Workbook(ofn, {"strings_to_numbers": False,
                                     "strings_to_formulas": False,
                                     "strings_to_urls": False})
    bold = book.add_format({"bold": True})
    wrap = book.add_format({"text_wrap": True, "valign": "top"})

    sheet = book.add_worksheet("table")
    numeric = numeric_columns(header, rows)
    for j, name in enumerate(header):
        sheet.write_string(0, j, name, bold)
        widest = max([len(name)] + [len(r[j]) for r in rows[:1000]])
        sheet.set_column(j, j, min(widest + 2, 60))
    for i, r in enumerate(rows):
        for j, cell in enumerate(r):
            if numeric[j] and cell not in EMPTY_CELLS:
                sheet.write_number(i + 1, j, to_number(cell))
            else:
                sheet.write_string(i + 1, j, cell)
    sheet.freeze_panes(1, 0)

    info = book.add_worksheet("columns")
    info.set_column(0, 0, 24)
    info.set_column(1, 1, 100)
    info.write_string(0, 0, f"{e.label}. {e.title}", bold)
    info.merge_range(1, 0, 1, 1, e.caption, wrap)
    info.set_row(1, 15 * max(1, len(e.caption) // 110 + 1))
    info.write_string(3, 0, "column", bold)
    info.write_string(3, 1, "description", bold)
    for i, (name, desc) in enumerate(e.columns):
        info.write_string(4 + i, 0, name)
        info.write_string(4 + i, 1, desc, wrap)
    book.close()


def md_cell(text: str) -> str:
    return text.replace("|", "\\|")


def entry_md(e: Entry) -> list[str]:
    title = e.title if e.title[-1] in ".!?" else e.title + "."
    if e.is_stub:
        return [f"**{e.label}. {title}** TBD.", ""]
    lines = [f"**{e.label}. {title}** {e.caption}", "",
             "| column | description |", "|---|---|"]
    lines += [f"| `{md_cell(n)}` | {md_cell(d)} |" for n, d in e.columns]
    return lines + [""]


def write_tables_md(ofn: str, entries: list[Entry]) -> None:
    lines: list[str] = []
    for heading, supp in (("# Tables", False), ("# Supplementary tables", True)):
        part = [e for e in entries if e.supp == supp]
        if not part:
            continue
        lines += [heading, ""]
        for e in part:
            lines += entry_md(e)
    with open(ofn, "w") as f:
        f.write("\n".join(lines).rstrip() + "\n")
    print(f"generated: {ofn}")


INDEX_COLS = ["table", "name", "module", "file", "rows", "columns", "src"]


def cmd_export(args) -> None:
    entries = load(args.ifn)
    paths = parse_pairs(args.pairs)
    tdir = os.path.join(args.odir, "tables")
    os.makedirs(tdir, exist_ok=True)
    print(f"exporting {len(entries)} table(s) to {tdir}")

    index: list[dict] = []
    n_done = 0
    for e in entries:
        if e.is_stub:
            print(f"  {e.label} ({e.name}): stub, skipped")
            continue
        src = paths.get((e.module, e.name))
        if not src:
            die(f"{e.label}: no path passed for {e.module}:{e.name} — "
                f"{e.var} resolves to nothing under m={e.module}")
        if not os.path.isfile(src):
            msg = (f"{e.label} ({e.name}): missing table {src}"
                   + (f" — build it with 'make p_tables x={e.key}'"
                      if e.target else ""))
            if args.on_missing_file == "error":
                die(msg)
            print(f"warning: {msg}")
            continue
        header, rows = read_table(src, e.label)
        check_header(e, header, src, args.ifn)
        shutil.copyfile(src, os.path.join(tdir, e.stem + ".txt"))
        write_xlsx(os.path.join(tdir, e.stem + ".xlsx"), e, header, rows)
        index.append({"table": e.label, "name": e.name, "module": e.module,
                      "file": f"tables/{e.stem}", "rows": len(rows),
                      "columns": len(header), "src": src})
        n_done += 1
        print(f"  {e.label}: {e.stem}.txt/.xlsx, {len(rows)} row(s) x "
              f"{len(header)} column(s)")

    write_tables_md(os.path.join(args.odir, "tables.md"), entries)
    ofn = os.path.join(args.odir, "tables.txt")
    with open(ofn, "w") as f:
        f.write("\t".join(INDEX_COLS) + "\n")
        for r in index:
            f.write("\t".join(str(r[c]) for c in INDEX_COLS) + "\n")
    print(f"generated: {ofn}")
    shutil.copyfile(args.ifn, os.path.join(args.odir, os.path.basename(args.ifn)))
    n_stub = sum(1 for e in entries if e.is_stub)
    print(f"done: {n_done} table(s) exported, {n_stub} stub(s), "
          f"{len(entries) - n_done - n_stub} missing")


#####################################################################################
# main
#####################################################################################


def main() -> None:
    # stdout is block-buffered when it is a pipe, which would flush every
    # header after the sub-makes they label have already printed
    sys.stdout.reconfigure(line_buffering=True)
    ap = argparse.ArgumentParser(
        description=__doc__,
        formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = ap.add_subparsers(dest="cmd", required=True)

    s = sub.add_parser("vars", help="space-separated MODULE:NAME:VAR triples "
                                    "for the make foreach that resolves each path")
    s.add_argument("--ifn", required=True)
    s.set_defaults(func=cmd_vars)

    s = sub.add_parser("run", help="build the selected tables")
    s.add_argument("--ifn", required=True)
    s.add_argument("--x", default="all",
                   help="all, or space/comma-separated keys: N for Table N, "
                        "suppN for Supp. Table N")
    s.add_argument("--make", default="make")
    s.add_argument("--c", required=True, help="the config name")
    s.set_defaults(func=cmd_run)

    s = sub.add_parser("export", help="check, copy and convert every table")
    s.add_argument("--ifn", required=True)
    s.add_argument("--odir", required=True)
    s.add_argument("--on-missing-file", default="error",
                   choices=("error", "warning"))
    s.add_argument("pairs", nargs="*", metavar="MODULE:NAME=/path",
                   help="the source path of each table, produced by the make "
                        "foreach over vars")
    s.set_defaults(func=cmd_export)

    args = ap.parse_args()
    args.func(args)


if __name__ == "__main__":
    main()
