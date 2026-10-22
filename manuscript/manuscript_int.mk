####################################################################################################
# register module
####################################################################################################

units=manuscript.mk manuscript_artifacts.mk
MANUSCRIPT_VER?=v1
$(call _register_module,manuscript,MANUSCRIPT_VER,$(units))

####################################################################################################
# input
####################################################################################################

MANUSCRIPT_JSON?=$(_cd)/manuscript/figures.json

# methods templates live with the pipeline that ran the steps they describe,
# not with the module: one directory holds the paper's whole methods coverage.
# per module: {module}/{module}.md and dry/$(PROJECT_NAME)/
MANUSCRIPT_METHODS_SRC_DIR?=$(PIPELINE_DIR)/methods

# which modules the methods section covers, and in what order. a pipeline
# property, not a config one: a methods section describes what the code does.
# an entry is the module name and its title -- the target and the four doc
# variables are derived from the module's own prefix
MANUSCRIPT_METHODS_JSON?=$(MANUSCRIPT_METHODS_SRC_DIR)/methods.json

# the bibliography is maintained by Zotero as Better CSL JSON; the CSL
# stylesheet controls both citations and the bibliography at final rendering
MANUSCRIPT_REFERENCES_JSON?=
MANUSCRIPT_CSL?=

####################################################################################################
# stats
####################################################################################################

# every module's measured values live under this one root, because a dsub job
# delocalizes a single output directory: one machine measuring all modules
# means one tree to sync back. each module nests {module}/{ver}/{stats_ver}
# beneath it, so bumping one module's stats version still invalidates only it
METHODS_STATS_ROOT?=$(OUTPUT_DIR)/methods

# thousands separators for a count that a stats rule quotes as a setting, so a
# cap reads the way the paper prints it. perl rather than printf's %'d, which
# does not group under /bin/sh, or a sed loop, whose syntax is not portable.
# measured counts are commified by the helper that computes them.
_commify=perl -e '$$n=shift; 1 while $$n =~ s/^(\d+)(\d{3})/$$1,$$2/; print $$n' $(1)

####################################################################################################
# export
####################################################################################################

MANUSCRIPT_MOUNT_DIRS?=$(EXPORT_MOUNT_DIRS)
MANUSCRIPT_ON_MISSING_FILE?=error

# a compile renders a value the stats rule has not produced as bold NA behind a
# draft note, so a registered module always yields a readable section. set
# METHODS_STRICT=--strict for the final pass, where a gap should refuse instead
METHODS_STRICT?=

# everything a manuscript generates lives under here, outside the bucket and
# gitignored: these are derived files, regenerated on demand. MAKESHIFT_ROOT is
# /makeshift in denv and the host repo path on macOS, so host-side exports
# (live Zotero DOCX) and container PDFs share one tree.
MANUSCRIPT_BASE_DIR?=$(MAKESHIFT_ROOT)/manuscripts/$(PIPELINE_NAME)/$(PROJECT_NAME)

MANUSCRIPT_EXPORT_VER?=v1
MANUSCRIPT_EXPORT_DIR?=$(MANUSCRIPT_BASE_DIR)/$(MANUSCRIPT_EXPORT_VER)

# where each module compiles its methods docs. deliberately outside the
# versioned export dir: a module must not need to know MANUSCRIPT_EXPORT_VER,
# so it writes a stable current copy here and the export snapshots it.
MANUSCRIPT_METHODS_DIR?=$(MANUSCRIPT_BASE_DIR)/methods

# variable names the export must resolve: the $(VAR) tokens figures.json spells
# out, plus the four doc variables derived from each registered module
MANUSCRIPT_REFERENCED_VARS:=$(shell python $(_manuscript_path)/py/list_vars.py $(MANUSCRIPT_JSON) $(MANUSCRIPT_METHODS_JSON) 2>/dev/null)

####################################################################################################
# artifacts
####################################################################################################

# what a module ships is decided in the same pass that writes its methods, so
# the declaration sits beside the template: {module}/artifacts.json. the module
# list is the methods registry — a module in scope for the paper's methods is
# in scope for its data
ARTIFACTS_SRC_DIR?=$(MANUSCRIPT_METHODS_SRC_DIR)

# the exported bundle. versioned like the manuscript export: bumping the version
# points the next run at a fresh directory and recomputes nothing
ARTIFACTS_VER?=v1
ARTIFACTS_EXPORT_DIR?=$(MANUSCRIPT_BASE_DIR)/artifacts/$(ARTIFACTS_VER)

# the audit pass writes only here, which is what makes it safe to run anywhere
ARTIFACTS_SCAN_DIR?=/tmp/artifacts/$(PIPELINE_NAME)/$(PROJECT_NAME)

# where the measured tables land, scan dir unless the export target overrides it
ARTIFACTS_ODIR?=$(ARTIFACTS_SCAN_DIR)

# size caps, both on the instantiated total: a 10 Mb table over 168 libraries is
# 1.7 Gb, so a per-file cap would let the bundle grow unnoticed
ARTIFACTS_MAX_GROUP_GB?=1
ARTIFACTS_MAX_TOTAL_GB?=45

ARTIFACTS_MOUNT_DIRS?=$(MANUSCRIPT_MOUNT_DIRS)
ARTIFACTS_ON_MISSING_FILE?=error

# the code state the bundle was produced from, recorded in its README. set this
# to the pipeline's methods tag once the pipeline is frozen
ARTIFACTS_TAG?=none

# supp tables have their own light export path, since they ship far more often
# than the full artifact bundle. one file per supp table, named for its index
# and the artifact, with supp_tables.txt at the folder root.
SUPP_TABLES_VER?=v1
SUPP_TABLES_DIR?=$(MANUSCRIPT_BASE_DIR)/supp_tables/$(SUPP_TABLES_VER)
