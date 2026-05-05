import argparse
import json
import os
import re
import shutil
import sys


def expand_vars(s, var_map):
    """expand $(VAR) tokens in s using var_map"""
    def replace(m):
        name = m.group(1)
        if name not in var_map:
            print(f"error: variable {name} referenced in json but not passed to script",
                  file=sys.stderr)
            sys.exit(1)
        return var_map[name]
    return re.sub(r'\$\(([A-Z_][A-Z0-9_]*)\)', replace, s)


def resolve_src(path, mount_dirs):
    """return the absolute path under one of the mount dirs, or path as-is if local"""
    for mount in mount_dirs:
        if path.startswith(mount):
            return path
    # path may already be absolute (local figure dir)
    return path


def copy_file(src, dst, on_missing):
    if not os.path.exists(src):
        msg = f"missing file: {src}"
        if on_missing == "error":
            print(f"error: {msg}", file=sys.stderr)
            sys.exit(1)
        else:
            print(f"warning: {msg}", file=sys.stderr)
            return
    os.makedirs(os.path.dirname(dst), exist_ok=True)
    shutil.copy2(src, dst)
    size_mb = os.path.getsize(src) / 1e6
    print(f"  copied ({size_mb:.1f}MB): {os.path.basename(src)}", file=sys.stderr)


def export_panels(panels, label_prefix, fig_dir, var_map, mount_dirs, odir, on_missing):
    for idx, panel in enumerate(panels):
        letter = chr(ord('a') + idx)
        panel_label = f"{label_prefix}{letter}"
        src_dir = expand_vars(panel["dir"], var_map)
        dst_dir = os.path.join(odir, fig_dir, panel_label)
        print(f"  panel {panel_label}:", file=sys.stderr)
        print(f"    src: {src_dir}", file=sys.stderr)
        print(f"    dst: {dst_dir}", file=sys.stderr)
        for fname in panel["files"]:
            src = os.path.join(src_dir, fname)
            dst = os.path.join(dst_dir, fname)
            copy_file(src, dst, on_missing)
            # copy .txt data sidecar alongside the PDF when present and not already listed
            if fname.endswith(".pdf"):
                data_fname = fname[:-4] + ".txt"
                if data_fname not in panel["files"]:
                    data_src = os.path.join(src_dir, data_fname)
                    if os.path.exists(data_src):
                        copy_file(data_src, os.path.join(dst_dir, data_fname), on_missing)


def export_legends(legends, label_prefix, fig_dir, var_map, mount_dirs, odir, on_missing):
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


def export_figures(figures, number_fmt, var_map, mount_dirs, odir, on_missing):
    for idx, fig in enumerate(figures):
        num = number_fmt(idx + 1)
        fig_dir = f"figure_{num}"
        title = fig.get("title", "")
        print("=" * 80, file=sys.stderr)
        print(f"figure {num}: {title}", file=sys.stderr)
        print("=" * 80, file=sys.stderr)
        export_panels(fig.get("panels", []), num, fig_dir,
                      var_map, mount_dirs, odir, on_missing)
        export_legends(fig.get("legends", []), num, fig_dir,
                       var_map, mount_dirs, odir, on_missing)


def parse_key_value_args(tokens):
    """parse KEY=value pairs from trailing argv tokens"""
    result = {}
    for tok in tokens:
        if "=" in tok:
            key, _, val = tok.partition("=")
            result[key] = val
    return result


def main():
    # argv: script key=val key=val ... — makefile passes key=value pairs
    # the fixed named args come first; key=value pairs follow
    parser = argparse.ArgumentParser(add_help=False)
    args, remainder = parser.parse_known_args()

    kv = parse_key_value_args(remainder)

    ifn        = kv.pop("ifn", None)
    mount_dirs = kv.pop("mount.dirs", "").split()
    on_missing = kv.pop("on.missing.file", "error")
    odir       = kv.pop("odir", None)

    if not ifn or not odir:
        print("error: ifn and odir are required", file=sys.stderr)
        sys.exit(1)

    # remaining kv entries are VAR_NAME=path entries from _export_variable
    var_map = kv

    with open(ifn) as f:
        data = json.load(f)

    print(f"exporting to {odir}", file=sys.stderr)

    export_figures(data.get("figures", []),
                   lambda n: str(n),
                   var_map, mount_dirs, odir, on_missing)

    export_figures(data.get("supp_figures", []),
                   lambda n: f"S{n}",
                   var_map, mount_dirs, odir, on_missing)

    n_main = len(data.get("figures", []))
    n_supp = len(data.get("supp_figures", []))
    print(f"done: {n_main} main figure(s), {n_supp} supplementary figure(s)", file=sys.stderr)


if __name__ == "__main__":
    main()
