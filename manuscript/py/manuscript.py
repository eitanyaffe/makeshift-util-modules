import argparse
import json
import os
import re
import shutil
import sys

import methods_registry
from methods_registry import DRAFT_MARK, VARIANTS


VAR_RE = re.compile(r'\$\(([A-Z_][A-Z0-9_]*)\)')

# the two halves of an export write disjoint trees under the same root, so
# either can be run on its own: methods is seconds and needs nothing on the
# bucket, while figures needs every placed panel and its caption to exist
WHAT = ("all", "figures", "methods")


def expand_vars(s, var_map):
    """expand $(VAR) tokens in s using var_map"""
    def replace(m):
        name = m.group(1)
        if name not in var_map:
            print(f"error: variable {name} referenced in json but not passed to script")
            sys.exit(1)
        return var_map[name]
    return VAR_RE.sub(replace, s)


def copy_file(src, dst, on_missing):
    if not os.path.exists(src):
        msg = f"missing file: {src}"
        if on_missing == "error":
            print(f"error: {msg}")
            sys.exit(1)
        else:
            print(f"warning: {msg}")
            return False
    os.makedirs(os.path.dirname(dst), exist_ok=True)
    shutil.copy2(src, dst)
    size_mb = os.path.getsize(src) / 1e6
    print(f"  copied ({size_mb:.1f}MB): {os.path.basename(src)}")
    return True


def is_stub_panel(panel):
    """true when the panel has no assets and no inline caption (placeholder only)"""
    has_files = bool(panel.get("dir") and panel.get("files"))
    has_caption = bool(panel.get("caption"))
    return not has_files and not has_caption


def is_caption_only_panel(panel):
    """inline caption with no pdf/txt assets to copy"""
    return bool(panel.get("caption")) and not (panel.get("dir") and panel.get("files"))


def caption_basename(pdf_fname):
    """caption sidecar filename for a given pdf filename (preserves subdirs)"""
    d = os.path.dirname(pdf_fname)
    base = os.path.basename(pdf_fname)
    cap = "caption_" + base[:-4] + ".txt"
    return os.path.join(d, cap) if d else cap


def data_basename(pdf_fname):
    d = os.path.dirname(pdf_fname)
    base = os.path.basename(pdf_fname)
    data = base[:-4] + ".txt"
    return os.path.join(d, data) if d else data


def export_panels(panels, label_prefix, fig_dir, var_map, odir, on_missing):
    for idx, panel in enumerate(panels):
        letter = chr(ord('a') + idx)
        panel_label = f"{label_prefix}{letter}"
        if is_stub_panel(panel):
            print(f"  panel {panel_label}: stub, skipped")
            continue
        dst_dir = os.path.join(odir, fig_dir, panel_label)
        if is_caption_only_panel(panel):
            print(f"  panel {panel_label}: caption-only")
            print(f"    dst: {dst_dir}")
            os.makedirs(dst_dir, exist_ok=True)
            with open(os.path.join(dst_dir, "caption.txt"), "w") as f:
                f.write(panel["caption"].strip() + "\n")
            continue
        src_dir = expand_vars(panel["dir"], var_map)
        print(f"  panel {panel_label}:")
        print(f"    src: {src_dir}")
        print(f"    dst: {dst_dir}")
        for fname in panel["files"]:
            src = os.path.join(src_dir, fname)
            dst = os.path.join(dst_dir, fname)
            copy_file(src, dst, on_missing)
            if not fname.endswith(".pdf"):
                continue
            # tidy-data sidecar (optional; auto-copy if present)
            data_fname = data_basename(fname)
            if data_fname not in panel["files"]:
                data_src = os.path.join(src_dir, data_fname)
                if os.path.exists(data_src):
                    copy_file(data_src, os.path.join(dst_dir, data_fname), on_missing)
            # caption sidecar (required for every panel pdf)
            cap_fname = caption_basename(fname)
            cap_src = os.path.join(src_dir, cap_fname)
            if not os.path.exists(cap_src):
                print(f"error: missing caption for panel {panel_label} pdf {fname}")
                print(f"  expected: {cap_src}")
                print(f"  (every panel pdf listed in figures.json must have a "
                      f"caption_*.txt sidecar; upgrade the plotting rule via the "
                      f"ms-manuscript skill)")
                if on_missing == "error":
                    sys.exit(1)
            else:
                copy_file(cap_src, os.path.join(dst_dir, cap_fname), on_missing)


def export_legends(legends, label_prefix, fig_dir, var_map, odir, on_missing):
    for idx, legend in enumerate(legends):
        legend_label = f"legend_{idx + 1}"
        src_dir = expand_vars(legend["dir"], var_map)
        dst_dir = os.path.join(odir, fig_dir, legend_label)
        print(f"  legend {legend_label}:")
        print(f"    src: {src_dir}")
        print(f"    dst: {dst_dir}")
        for fname in legend["files"]:
            src = os.path.join(src_dir, fname)
            dst = os.path.join(dst_dir, fname)
            copy_file(src, dst, on_missing)


def export_figures(figures, number_fmt, var_map, odir, on_missing):
    for idx, fig in enumerate(figures):
        num = number_fmt(idx + 1)
        fig_dir = f"figure_{num}"
        title = fig.get("title", "")
        print("=" * 80)
        print(f"figure {num}: {title}")
        print("=" * 80)
        export_panels(fig.get("panels", []), num, fig_dir,
                      var_map, odir, on_missing)
        export_legends(fig.get("legends", []), num, fig_dir,
                       var_map, odir, on_missing)


def read_caption(path):
    if not os.path.exists(path):
        return None
    with open(path) as f:
        return f.read().strip()


CAPTIONS_TXT_SEP = "-" * 80


def render_figure_block(fig, num, odir):
    """lines for one figure: a '=== Figure N: title ===' header, then one
    'label: caption' line per panel"""
    title = fig.get("title", "")
    lines = [f"=== Figure {num}: {title} ==="]
    fig_dir = f"figure_{num}"
    for j, panel in enumerate(fig.get("panels", [])):
        letter = chr(ord('a') + j)
        label = f"{num}{letter}"
        lines.append("")
        if is_stub_panel(panel):
            lines.append(f"{label}: TBD.")
            continue
        if is_caption_only_panel(panel):
            lines.append(f"{label}: {panel['caption'].strip()}")
            continue
        panel_dir = os.path.join(odir, fig_dir, label)
        pdfs = [f for f in panel.get("files", []) if f.endswith(".pdf")]
        caps = []
        for pdf in pdfs:
            cap = read_caption(os.path.join(panel_dir, caption_basename(pdf)))
            if cap is not None:
                caps.append(cap)
        caption_text = "\n\n".join(caps) if caps else "TBD."
        lines.append(f"{label}: {caption_text}")
    return lines


def emit_captions_txt(figures, supp_figures, odir):
    """assemble captions.txt (plain text) from rendered caption files in the export dir"""
    blocks = [render_figure_block(fig, str(i + 1), odir) for i, fig in enumerate(figures)]
    blocks += [render_figure_block(fig, f"S{i + 1}", odir) for i, fig in enumerate(supp_figures)]

    lines = []
    for i, block in enumerate(blocks):
        if i > 0:
            lines.append(CAPTIONS_TXT_SEP)
            lines.append("")
        lines.extend(block)
        lines.append("")

    ofn = os.path.join(odir, "captions.txt")
    with open(ofn, "w") as f:
        f.write("\n".join(lines).rstrip() + "\n")
    print(f"generated: {ofn}")


def write_methods_md(ofn, entries, label, banner=""):
    """concatenate rendered bodies under a '## title' per registered module.

    no rule between sections: the heading already separates them, and pandoc
    renders a markdown rule as a centred line across the page in the PDF. the
    LaTeX writer in methods_to_tex.py drops rules for the same reason."""
    with open(ofn, "w") as f:
        f.write("# Methods\n\n")
        if banner:
            f.write(f"**{banner}**\n\n")
        for i, (title, body) in enumerate(entries):
            if i > 0:
                f.write("\n")
            f.write(f"## {title}\n\n{body}\n")
    print(f"generated: {ofn} ({len(entries)} module(s), {label})")


STATUS_COLS = ["module", "title", "status", "note"]


def doc_status(bodies):
    """what the compiled docs say about themselves: read off disk, never declared"""
    absent = [k for k in VARIANTS if k not in bodies]
    if absent:
        return "missing", "not compiled: " + ", ".join(absent)
    head = bodies["paper_md"].lstrip().split("\n", 1)[0].strip()
    if head.startswith(DRAFT_MARK):
        return "draft", head.strip("* ")
    return "complete", ""


def write_status_table(ofn, rows):
    with open(ofn, "w") as f:
        f.write("\t".join(STATUS_COLS) + "\n")
        for r in rows:
            f.write("\t".join(r.get(c, "") for c in STATUS_COLS) + "\n")
    print(f"generated: {ofn}")


def export_methods(ifn_methods, var_map, odir):
    """copy every registered module's four docs, combine them, record status.

    Every module in the registry is exported, whatever state it is in: a
    module whose stats have not run yet compiles with bold NA values and
    exports as a draft, so the combined docs are the place the gaps are read
    rather than something the export hides. That is why a missing doc is
    recorded here instead of honouring MANUSCRIPT_ON_MISSING_FILE."""
    _pipeline, registered = methods_registry.load(ifn_methods)
    # a module marked render:false is measured but contributes no section
    entries = methods_registry.rendered(registered)
    skipped = [e.module for e in registered if not e.render]
    if skipped:
        print(f"not rendered, measured only: {', '.join(skipped)}")
    if not entries:
        print("the methods registry has nothing to render — skipping methods export")
        return 0

    for subdir, _ext, _combined in VARIANTS.values():
        os.makedirs(os.path.join(odir, subdir), exist_ok=True)

    collected = {k: [] for k in VARIANTS}
    statuses = []
    print("=" * 80)
    print("methods")
    print("=" * 80)

    for entry in entries:
        print(f"  {entry.module} ({entry.title}):")
        bodies = {}
        for key, (subdir, ext, _combined) in VARIANTS.items():
            var = entry.var(key)
            if var not in var_map:
                print(f"error: {var} is not defined — {entry.module} derives "
                      f"its docs from prefix {entry.prefix}; declare a "
                      f"'prefix' in the registry if the module uses another")
                sys.exit(1)
            src = var_map[var]
            if not src:
                print(f"error: {var} resolves to an empty path")
                sys.exit(1)
            dst = os.path.join(odir, subdir, f"{entry.module}.{ext}")
            print(f"    {src} -> {dst}")
            if not copy_file(src, dst, "warning"):
                continue
            with open(dst) as f:
                bodies[key] = f.read().rstrip()

        status, note = doc_status(bodies)
        statuses.append({"module": entry.module, "title": entry.title,
                         "status": status, "note": note})
        print(f"    status: {status}{'  ' + note if note else ''}")
        for key, body in bodies.items():
            collected[key].append((entry.title, body))

    incomplete = [s for s in statuses if s["status"] != "complete"]
    banner = ""
    if incomplete:
        banner = (f"Draft export: {len(incomplete)} of {len(statuses)} methods "
                  f"sections are incomplete — see the Draft note in each "
                  f"section and methods_status.txt.")

    from methods_to_tex import write_methods_tex
    for key, (_subdir, ext, combined) in VARIANTS.items():
        ofn = os.path.join(odir, combined)
        if ext == "md":
            write_methods_md(ofn, collected[key], key, banner)
        else:
            n = write_methods_tex(collected[key], ofn, banner)
            print(f"generated: {ofn} ({n} module(s), {key})")

    write_status_table(os.path.join(odir, "methods_status.txt"), statuses)
    for s in statuses:
        if s["status"] != "complete":
            print(f"warning: methods {s['module']} is {s['status']} — "
                  f"{s['note']}")
    return len(entries)


def parse_key_value_args(tokens):
    """parse KEY=value pairs from trailing argv tokens"""
    result = {}
    for tok in tokens:
        if "=" in tok:
            key, _, val = tok.partition("=")
            result[key] = val
    return result


def main():
    parser = argparse.ArgumentParser(add_help=False)
    args, remainder = parser.parse_known_args()

    kv = parse_key_value_args(remainder)

    ifn         = kv.pop("ifn", None)
    ifn_methods = kv.pop("ifn.methods", None)
    ifn_references = kv.pop("ifn.references", None)
    ifn_csl     = kv.pop("ifn.csl", None)
    kv.pop("mount.dirs", None)
    on_missing  = kv.pop("on.missing.file", "error")
    odir        = kv.pop("odir", None)
    what        = kv.pop("what", "all")

    if not ifn or not odir:
        print("error: ifn and odir are required")
        sys.exit(1)
    if what not in WHAT:
        print(f"error: unknown what '{what}' — expected one of "
              f"{', '.join(WHAT)}")
        sys.exit(1)

    var_map = kv

    with open(ifn) as f:
        data = json.load(f)

    if "methods" in data:
        print(f"error: {ifn} still carries a 'methods' list. the registry "
              f"moved to the pipeline's methods.json — methods and figures "
              f"are independent, and a methods section is not "
              f"config-specific")
        sys.exit(1)

    print(f"exporting {what} to {odir}")
    os.makedirs(odir, exist_ok=True)

    figures = data.get("figures", [])
    supp_figures = data.get("supp_figures", [])
    n_main = n_supp = n_methods = 0

    if what in ("all", "figures"):
        export_figures(figures, lambda n: str(n), var_map, odir, on_missing)
        export_figures(supp_figures, lambda n: f"S{n}", var_map, odir,
                       on_missing)
        emit_captions_txt(figures, supp_figures, odir)
        copy_file(ifn, os.path.join(odir, os.path.basename(ifn)), on_missing)
        n_main, n_supp = len(figures), len(supp_figures)

    if what in ("all", "methods") and ifn_methods:
        if bool(ifn_references) != bool(ifn_csl):
            print("error: methods export requires both ifn.references and "
                  "ifn.csl, or neither")
            sys.exit(1)
        n_methods = export_methods(ifn_methods, var_map, odir)
        copy_file(ifn_methods,
                  os.path.join(odir, os.path.basename(ifn_methods)),
                  on_missing)
        if ifn_references:
            copy_file(ifn_references, os.path.join(odir, "references.json"),
                      on_missing)
            copy_file(ifn_csl, os.path.join(odir, "citation-style.csl"),
                      on_missing)

    print(f"done: {n_main} main figure(s), {n_supp} supplementary figure(s), "
          f"{n_methods} methods module(s)")


if __name__ == "__main__":
    main()
