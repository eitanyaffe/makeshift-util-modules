import json
import re
import sys

import methods_registry


VAR_RE = re.compile(r'\$\(([A-Z_][A-Z0-9_]*)\)')


def collect_vars(node, out):
    if isinstance(node, str):
        out.update(VAR_RE.findall(node))
    elif isinstance(node, dict):
        for v in node.values():
            collect_vars(v, out)
    elif isinstance(node, list):
        for v in node:
            collect_vars(v, out)


def main():
    # the only script here that still writes to stderr: stdout is the variable
    # list make assigns to MANUSCRIPT_REFERENCED_VARS, so a message printed
    # there would silently become one of the variables
    if len(sys.argv) not in (2, 3):
        print("usage: list_vars.py <figures.json> [methods.json]",
              file=sys.stderr)
        sys.exit(1)
    with open(sys.argv[1]) as f:
        data = json.load(f)
    names = set()
    collect_vars(data, names)
    # the methods registry names no variable: it registers a module and the
    # four doc variables follow from its prefix, so they are synthesized here
    # by the same rule the exporter looks them up with
    if len(sys.argv) == 3:
        _pipeline, entries = methods_registry.load(sys.argv[2])
        names.update(methods_registry.var_names(entries))
    print(" ".join(sorted(names)))


if __name__ == "__main__":
    main()
