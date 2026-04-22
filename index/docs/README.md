# Makeshift pipeline index

This directory is an auto-generated index of pipeline outputs.

## Files

- `all_class.txt` — one row per output variable, with a description and a
  `gs://` path template that uses `{KEY}` placeholders for dynamic fields
  (e.g. `{ASSEMBLY_ID}`, `{LIB_ID}`).
- `all.txt` — one row per concrete instance: resolved `gs://` path, size,
  and whether the file currently exists.
- `index.txt` — per-module summary.
- `msutil.py` — CLI to browse and fetch from this index.

## Quick start

The CLI is self-documenting. From this directory:

```bash
./msutil.py                  # top-level help
./msutil.py <cmd> -h         # per-command help
./msutil.py ls               # list indexed variables
./msutil.py get VAR          # download a variable (supports globs and tag filters)
./msutil.py info             # per-module summary
```

From elsewhere, point at this dir: `./msutil.py -i <index_dir> <cmd>`.
