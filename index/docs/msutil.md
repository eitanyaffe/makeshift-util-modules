# msutil

`msutil` is a small command-line tool for browsing and downloading the
analysis outputs published by makeshift.

Each published output is exposed as a **variable** (e.g. `ASSEMBLY_CONTIG_TABLE`)
with one or more instances tagged by things like the assembly id
(e.g. `ASSEMBLY_ID=BAA`). `msutil` lets you find them and pull them to
your laptop.

## Getting started

`msutil` is a single self-contained script. You can run it straight
from the index directory, or drop it on your `PATH` and call it from
anywhere. It also needs the Google Cloud SDK
(<https://cloud.google.com/sdk/docs/install>) for downloads; `msutil`
will tell you if it can't find `gcloud`.

Step into a published index directory and start poking around:

```bash
cd /makeshift/export/<pipeline>/<project>/index/<version>

msutil info                      # what modules are published, how much data
msutil ls -a                     # list every variable (quote globs!)
msutil ls 'ASSEMBLY_*'           # filter by name
msutil ls --module eggNOG        # filter by module
msutil ls ASSEMBLY_ID=BAA        # show all instances tagged with this id
```

To download, use `msutil get` with the same filters:

```bash
msutil get ASSEMBLY_CONTIG_TABLE ASSEMBLY_ID=BAA -dry    # preview
msutil get ASSEMBLY_CONTIG_TABLE ASSEMBLY_ID=BAA         # do it
msutil get --module eggNOG -o ~/data                     # whole module to ~/data
```

`msutil get` shows you how many files and total size, then asks for
confirmation. It downloads in parallel and skips files that are already
present locally (so you can re-run to resume). Hit `Ctrl-C` to abort.

## Learn more by running

Every command has focused `-h` output with examples you can copy:

```bash
msutil           # top-level help + version
msutil ls -h
msutil get -h
```

A couple of tips the help won't tell you:

- **Quote globs.** `msutil ls *` is expanded by your shell against the
  current directory. Use `msutil ls '*'` or `msutil ls -a`.
- **Tags are `KEY=VAL`.** You can pass any number of them after the
  variable name: `msutil get GENE_TABLE ASSEMBLY_ID=BAA CLUSTER=c12`.
- **Resume for free.** Re-run the same `msutil get` and it will only
  fetch files you don't already have. Use `-f` to force re-download.
