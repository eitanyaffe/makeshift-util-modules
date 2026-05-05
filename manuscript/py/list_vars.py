import json
import re
import sys


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
    if len(sys.argv) != 2:
        print("usage: list_vars.py <figures.json>", file=sys.stderr)
        sys.exit(1)
    with open(sys.argv[1]) as f:
        data = json.load(f)
    names = set()
    collect_vars(data, names)
    print(" ".join(sorted(names)))


if __name__ == "__main__":
    main()
