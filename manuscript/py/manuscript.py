import argparse
import json
import os
import re
import shutil
import sys


VAR_RE = re.compile(r'\$\(([A-Z_][A-Z0-9_]*)\)')


def expand_vars(s, var_map):
    """expand $(VAR) tokens in s using var_map"""
    def replace(m):
        name = m.group(1)
        if name not in var_map:
            print(f"error: variable {name} referenced in json but not passed to script",
                  file=sys.stderr)
            sys.exit(1)
        return var_map[name]
    return VAR_RE.sub(replace, s)


def copy_file(src, dst, on_missing):
    if not os.path.exists(src):
        msg = f"missing file: {src}"
        if on_missing == "error":
            print(f"error: {msg}", file=sys.stderr)
            sys.exit(1)
        else:
            print(f"warning: {msg}", file=sys.stderr)
            return False
    os.makedirs(os.path.dirname(dst), exist_ok=True)
    shutil.copy2(src, dst)
    size_mb = os.path.getsize(src) / 1e6
    print(f"  copied ({size_mb:.1f}MB): {os.path.basename(src)}", file=sys.stderr)
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
            print(f"  panel {panel_label}: stub, skipped", file=sys.stderr)
            continue
        dst_dir = os.path.join(odir, fig_dir, panel_label)
        if is_caption_only_panel(panel):
            print(f"  panel {panel_label}: caption-only", file=sys.stderr)
            print(f"    dst: {dst_dir}", file=sys.stderr)
            os.makedirs(dst_dir, exist_ok=True)
            with open(os.path.join(dst_dir, "caption.txt"), "w") as f:
                f.write(panel["caption"].strip() + "\n")
            continue
        src_dir = expand_vars(panel["dir"], var_map)
        print(f"  panel {panel_label}:", file=sys.stderr)
        print(f"    src: {src_dir}", file=sys.stderr)
        print(f"    dst: {dst_dir}", file=sys.stderr)
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
                print(f"error: missing caption for panel {panel_label} pdf {fname}",
                      file=sys.stderr)
                print(f"  expected: {cap_src}", file=sys.stderr)
                print(f"  (every panel pdf listed in figures.json must have a "
                      f"caption_*.txt sidecar; upgrade the plotting rule via the "
                      f"ms-manuscript skill)", file=sys.stderr)
                if on_missing == "error":
                    sys.exit(1)
            else:
                copy_file(cap_src, os.path.join(dst_dir, cap_fname), on_missing)


def export_legends(legends, label_prefix, fig_dir, var_map, odir, on_missing):
    for idx, legend in enumerate(legends):
        legend_label = f"legend_{idx + 1}"
        src_dir = expand_vars(legend["dir"], var_map)
        dst_dir = os.path.join(odir, fig_dir, legend_label)
        print(f"  legend {legend_label}:", file=sys.stderr)
        print(f"    src: {src_dir}", file=sys.stderr)
        print(f"    dst: {dst_dir}", file=sys.stderr)
        for fname in legend["files"]:
            src = os.path.join(src_dir, fname)
            dst = os.path.join(dst_dir, fname)
            copy_file(src, dst, on_missing)


def export_figures(figures, number_fmt, var_map, odir, on_missing):
    for idx, fig in enumerate(figures):
        num = number_fmt(idx + 1)
        fig_dir = f"figure_{num}"
        title = fig.get("title", "")
        print("=" * 80, file=sys.stderr)
        print(f"figure {num}: {title}", file=sys.stderr)
        print("=" * 80, file=sys.stderr)
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
    print(f"generated: {ofn}", file=sys.stderr)


def write_methods_md(ofn, entries, label):
    """concatenate rendered bodies under a '## title' per methods[] entry"""
    with open(ofn, "w") as f:
        f.write("# Methods\n\n")
        for i, (title, body) in enumerate(entries):
            if i > 0:
                f.write("\n---\n\n")
            f.write(f"## {title}\n\n{body}\n")
    print(f"generated: {ofn} ({len(entries)} module(s), {label})",
          file=sys.stderr)


# one export subdir and one combined file per (version, format) pair.
# key = methods[] field name; value = (subdir, extension, combined basename)
METHODS_VARIANTS = {
    "paper_md":  ("methods", "md", "methods.md"),
    "paper_tex": ("methods", "tex", "methods.tex"),
    "full_md":   ("methods_full", "md", "methods_full.md"),
    "full_tex":  ("methods_full", "tex", "methods_full.tex"),
}


def export_methods(methods, var_map, odir, on_missing):
    """copy each module's paper/full docs in both formats, then combine"""
    if not methods:
        print("no methods[] entries — skipping methods export", file=sys.stderr)
        return

    for subdir, _ext, _combined in METHODS_VARIANTS.values():
        os.makedirs(os.path.join(odir, subdir), exist_ok=True)

    collected = {k: [] for k in METHODS_VARIANTS}
    print("=" * 80, file=sys.stderr)
    print("methods", file=sys.stderr)
    print("=" * 80, file=sys.stderr)

    for entry in methods:
        module = entry.get("module")
        missing = [k for k in METHODS_VARIANTS if not entry.get(k)]
        if not module or missing:
            print(f"error: methods entry requires 'module' and "
                  f"{', '.join(sorted(METHODS_VARIANTS))}", file=sys.stderr)
            print(f"  missing: {', '.join(missing) or 'module'}",
                  file=sys.stderr)
            print(f"  got: {entry}", file=sys.stderr)
            sys.exit(1)
        title = entry.get("title") or module
        print(f"  {module} ({title}):", file=sys.stderr)
        for key, (subdir, ext, _combined) in METHODS_VARIANTS.items():
            src = expand_vars(entry[key], var_map)
            dst = os.path.join(odir, subdir, f"{module}.{ext}")
            print(f"    {src} -> {dst}", file=sys.stderr)
            if not copy_file(src, dst, on_missing):
                continue
            with open(dst) as f:
                collected[key].append((title, f.read().rstrip()))

    from methods_to_tex import write_methods_tex
    for key, (_subdir, ext, combined) in METHODS_VARIANTS.items():
        ofn = os.path.join(odir, combined)
        if ext == "md":
            write_methods_md(ofn, collected[key], key)
        else:
            n = write_methods_tex(collected[key], ofn)
            print(f"generated: {ofn} ({n} module(s), {key})", file=sys.stderr)


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

    ifn        = kv.pop("ifn", None)
    kv.pop("mount.dirs", None)
    on_missing = kv.pop("on.missing.file", "error")
    odir       = kv.pop("odir", None)

    if not ifn or not odir:
        print("error: ifn and odir are required", file=sys.stderr)
        sys.exit(1)

    var_map = kv

    with open(ifn) as f:
        data = json.load(f)

    print(f"exporting to {odir}", file=sys.stderr)

    figures = data.get("figures", [])
    supp_figures = data.get("supp_figures", [])
    methods = data.get("methods", [])

    export_figures(figures, lambda n: str(n), var_map, odir, on_missing)
    export_figures(supp_figures, lambda n: f"S{n}", var_map, odir, on_missing)

    emit_captions_txt(figures, supp_figures, odir)
    export_methods(methods, var_map, odir, on_missing)

    n_main = len(figures)
    n_supp = len(supp_figures)
    n_methods = len(methods)
    print(f"done: {n_main} main figure(s), {n_supp} supplementary figure(s), "
          f"{n_methods} methods module(s)", file=sys.stderr)


if __name__ == "__main__":
    main()
