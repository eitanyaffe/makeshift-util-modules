"""Convert exported per-module methods docs into a body-only methods.tex.

Walks figures.json methods[] order and methods/{module}.txt (already copied
by manuscript_export). Titles come from methods[].title, not from the body's
# slug (which can disagree, e.g. module=mrna vs H1=# rna).

Heading map:
  \\section{Methods}
  \\subsection{title}          — one per methods[] entry
  \\subsubsection{...}        — ### (and stray ## other than Methods)

Drops the module one-liner summary, ---, and the redundant ## Methods frame.
"""
from __future__ import annotations

import re
import sys


UNICODE_MAP = {
    "—": "---",
    "–": "--",
    "−": "$-$",
    "×": "$\\times$",
    "±": "$\\pm$",
    "≥": "$\\geq$",
    "≤": "$\\leq$",
    "→": "$\\rightarrow$",
    "…": "\\ldots{}",
    "“": "``",
    "”": "''",
    "′": "$\\prime$",
    "₁": "$_1$",
    "₀": "$_0$",
    "⁹": "$^9$",
    "ε": "$\\varepsilon$",
    "⁻": "$^{-}$",
    "¹": "$^1$",
    "⁰": "$^0$",
    "é": "\\'e",
    "á": "\\'a",
    "í": "\\'i",
    "ó": "\\'o",
    "ú": "\\'u",
    "ñ": "\\~n",
}


def escape_tex(s):
    s = s.replace("\\", "\x00")
    for a, b in [
        ("&", "\\&"),
        ("%", "\\%"),
        ("$", "\\$"),
        ("#", "\\#"),
        ("_", "\\_"),
        ("{", "\\{"),
        ("}", "\\}"),
        ("~", "\\textasciitilde{}"),
        ("^", "\\textasciicircum{}"),
    ]:
        s = s.replace(a, b)
    s = s.replace("\x00", "\\textbackslash{}")
    for u, tex in UNICODE_MAP.items():
        s = s.replace(u, tex)
    return s


def inline_md(s):
    spans = []

    def stash(tex):
        spans.append(tex)
        return f"\x01{len(spans) - 1}\x02"

    s = re.sub(
        r"`([^`]+)`",
        lambda m: stash("\\texttt{" + escape_tex(m.group(1)) + "}"),
        s,
    )
    s = re.sub(
        r"\*\*([^*]+)\*\*",
        lambda m: stash("\\textbf{" + escape_tex(m.group(1)) + "}"),
        s,
    )
    s = re.sub(
        r"(?<!\*)\*([^*]+)\*(?!\*)",
        lambda m: stash("\\textit{" + escape_tex(m.group(1)) + "}"),
        s,
    )
    s = re.sub(
        r"(?<![A-Za-z0-9])_([A-Za-z][^_\n]{0,60}?)_(?![A-Za-z0-9_])",
        lambda m: stash("\\textit{" + escape_tex(m.group(1)) + "}"),
        s,
    )
    out = escape_tex(s)
    for i, tex in enumerate(spans):
        out = out.replace(f"\x01{i}\x02", tex)
    return out


def parse_blocks(text):
    lines = text.splitlines()
    blocks = []
    i = 0
    n = len(lines)
    while i < n:
        line = lines[i]
        if not line.strip():
            i += 1
            continue
        if line.strip() == "---":
            blocks.append({"type": "hr"})
            i += 1
            continue
        m = re.match(r"^(#{1,6})\s+(.*)$", line)
        if m:
            blocks.append({
                "type": "heading",
                "level": len(m.group(1)),
                "text": m.group(2).strip(),
            })
            i += 1
            continue
        if line.startswith("> "):
            buf = [line[2:]]
            i += 1
            while i < n and lines[i].startswith("> "):
                buf.append(lines[i][2:])
                i += 1
            blocks.append({"type": "quote", "text": " ".join(buf)})
            continue
        if re.match(r"^[-*] ", line):
            items = []
            while i < n and re.match(r"^[-*] ", lines[i]):
                items.append(lines[i][2:])
                i += 1
            blocks.append({"type": "ul", "items": items})
            continue
        if re.match(r"^\d+\. ", line):
            items = []
            while i < n and re.match(r"^\d+\. ", lines[i]):
                items.append(re.sub(r"^\d+\. ", "", lines[i]))
                i += 1
            blocks.append({"type": "ol", "items": items})
            continue
        if line.startswith("|") and "|" in line[1:]:
            rows = []
            while i < n and lines[i].startswith("|"):
                row = lines[i].strip()
                if re.match(r"^\|[\s|:-]+\|$", row):
                    i += 1
                    continue
                cells = [c.strip() for c in row.strip("|").split("|")]
                rows.append(cells)
                i += 1
            blocks.append({"type": "table", "rows": rows})
            continue
        buf = [line]
        i += 1
        while (
            i < n
            and lines[i].strip()
            and not re.match(r"^(#{1,6}\s|---$|> |[-*] |\d+\. |\|)", lines[i])
        ):
            buf.append(lines[i])
            i += 1
        blocks.append({"type": "p", "text": " ".join(x.strip() for x in buf)})
    return blocks


def strip_module_frame(text, drop_summary=True):
    """drop leading # slug, optional summary, ---, ## Methods; keep the rest."""
    lines = text.splitlines()
    i = 0
    while i < len(lines) and not lines[i].strip():
        i += 1
    if i < len(lines) and re.match(r"^#\s+", lines[i]):
        i += 1
    while i < len(lines) and not lines[i].strip():
        i += 1
    if drop_summary:
        while i < len(lines):
            if lines[i].strip() == "---":
                i += 1
                break
            if re.match(r"^##\s+Methods\s*$", lines[i], re.I):
                break
            i += 1
        while i < len(lines) and not lines[i].strip():
            i += 1
    if i < len(lines) and re.match(r"^##\s+Methods\s*$", lines[i], re.I):
        i += 1
    while i < len(lines) and not lines[i].strip():
        i += 1
    return "\n".join(lines[i:])


def convert_body(body):
    blocks = parse_blocks(body)
    out = []
    for b in blocks:
        t = b["type"]
        if t == "hr":
            continue
        if t == "heading":
            out.append(f"\\subsubsection{{{escape_tex(b['text'])}}}")
            out.append("")
            continue
        if t == "p":
            out.append(inline_md(b["text"]))
            out.append("")
        elif t == "quote":
            out += [
                "\\begin{quote}",
                inline_md(b["text"]),
                "\\end{quote}",
                "",
            ]
        elif t == "ul":
            out.append("\\begin{itemize}")
            out += [f"  \\item {inline_md(it)}" for it in b["items"]]
            out += ["\\end{itemize}", ""]
        elif t == "ol":
            out.append("\\begin{enumerate}")
            out += [f"  \\item {inline_md(it)}" for it in b["items"]]
            out += ["\\end{enumerate}", ""]
        elif t == "table":
            rows = b["rows"]
            if not rows:
                continue
            ncol = max(len(r) for r in rows)
            rows = [r + [""] * (ncol - len(r)) for r in rows]
            out.append("\\begin{tabular}{" + ("l" * ncol) + "}")
            out.append("\\hline")
            for i, r in enumerate(rows):
                out.append(" & ".join(inline_md(c) for c in r) + " \\\\")
                if i == 0:
                    out.append("\\hline")
            out += ["\\hline", "\\end{tabular}", ""]
    return "\n".join(out)


def write_methods_tex(methods, methods_dir, ofn, drop_summary=True):
    """write body-only methods.tex from copied methods/{module}.txt files.

    methods: figures.json methods[] entries (order preserved).
    methods_dir: export dir/methods containing {module}.txt.
    ofn: path for methods.tex.
    Returns number of modules written.
    """
    parts = [
        "% auto-generated by manuscript_export — do not edit",
        "% body-only: \\input{} this into a paper that already has a preamble",
        "\\section{Methods}",
        "",
    ]
    n_ok = 0
    for entry in methods:
        module = entry.get("module")
        if not module:
            continue
        title = entry.get("title") or module
        src = f"{methods_dir}/{module}.txt"
        try:
            with open(src) as f:
                text = f.read()
        except FileNotFoundError:
            print(f"warning: methods tex skip missing {src}", file=sys.stderr)
            continue
        body = strip_module_frame(text, drop_summary=drop_summary)
        parts.append(f"\\subsection{{{escape_tex(title)}}}")
        parts.append("")
        parts.append(convert_body(body).rstrip())
        parts.append("")
        n_ok += 1

    tex = "\n".join(parts).rstrip() + "\n"
    with open(ofn, "w") as f:
        f.write(tex)
    return n_ok
