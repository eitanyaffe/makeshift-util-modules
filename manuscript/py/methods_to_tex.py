"""Markdown -> LaTeX for methods docs, plus the export-time concatenation.

Two roles:

1. `convert_body` turns one markdown body into LaTeX. Used by
   methods_render.py when it compiles a module's paper.tex / full.tex.
2. `write_methods_tex` concatenates the already-converted per-module .tex
   bodies into a body-only methods.tex, in figures.json methods[] order.

A rendered methods doc carries no title and no headings — it is a run of
bold-led paragraphs — so the only heading structure comes from here:

  \\section{Methods}
  \\subsection{title}   one per methods[] entry, from methods[].title

`\\subsubsection` is still emitted for a stray markdown heading, so a doc
that does use headings degrades sensibly rather than losing them.
"""
from __future__ import annotations

import re


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


def write_methods_tex(entries, ofn):
    """concatenate per-module LaTeX bodies into a body-only methods.tex.

    entries: list of (title, tex_body) in methods[] order. The bodies are
    already LaTeX — methods_render.py converted them when it compiled each
    module — so this only adds the sectioning.
    ofn: path for the combined .tex.
    Returns the number of modules written.
    """
    parts = [
        "% auto-generated by manuscript_export — do not edit",
        "% body-only: \\input{} this into a paper that already has a preamble",
        "\\section{Methods}",
        "",
    ]
    for title, body in entries:
        parts.append(f"\\subsection{{{escape_tex(title)}}}")
        parts.append("")
        parts.append(body.rstrip())
        parts.append("")

    tex = "\n".join(parts).rstrip() + "\n"
    with open(ofn, "w") as f:
        f.write(tex)
    return len(entries)
