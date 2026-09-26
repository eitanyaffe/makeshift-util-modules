# the export has two independent halves writing into one directory, each with
# its own target, because their costs and failure modes have nothing in common:
# figures needs every placed panel and caption on the bucket and fails loudly
# when one is missing, while methods is seconds of local work.
_manuscript_export=python $(_md)/py/manuscript.py \
		ifn=$(MANUSCRIPT_JSON) \
		ifn.methods=$(MANUSCRIPT_METHODS_JSON) \
		$(if $(MANUSCRIPT_REFERENCES_JSON),ifn.references=$(MANUSCRIPT_REFERENCES_JSON)) \
		$(if $(MANUSCRIPT_CSL),ifn.csl=$(MANUSCRIPT_CSL)) \
		mount.dirs=$(MANUSCRIPT_MOUNT_DIRS) \
		on.missing.file=$(MANUSCRIPT_ON_MISSING_FILE) \
		odir=$(MANUSCRIPT_EXPORT_DIR) \
		$(call _export_variable,$(MANUSCRIPT_REFERENCED_VARS))

# copy figure files described in the manuscript json to the export directory.
# also auto-copies per-pdf sidecars and caption_*.txt, and generates
# captions.txt from all rendered captions (see ms-manuscript skill).
manuscript_export_figs:
	$(call _start,$(MANUSCRIPT_EXPORT_DIR))
	$(_manuscript_export) what=figures
	$(_end)

# copy every registered module's methods docs and concatenate them into
# methods.md / methods.tex, recording each module's status.
manuscript_export_methods:
	$(call _start,$(MANUSCRIPT_EXPORT_DIR))
	$(_manuscript_export) what=methods
	$(_end)

manuscript_export:
	$(call _start,$(MANUSCRIPT_EXPORT_DIR))
	$(_manuscript_export) what=all
	$(_end)
.PHONY: manuscript_export manuscript_export_figs manuscript_export_methods

# regenerate ms figures for the current config by dispatching to
# {config}/manuscript/generate.mk. usage:
#   make figs c={config}              → generate_all
#   make figs x=1a c={config}         → one panel
#   make figs x=1 c={config}          → whole figure 1
#   make figs x=S1a c={config}        → one supp panel
#   make figs x="2 S2" c={config}     → multiple figures / panels
#   make figs x=2,S2 c={config}       → same (comma-separated)
comma:=,
x?=all
figs:
	$(MAKE) -f $(_cd)/manuscript/generate.mk \
		$(foreach lab,$(subst $(comma), ,$(x)),generate_$(lab)) \
		c=$(PROJECT_NAME)
.PHONY: figs

# regenerate ms methods for the current config by dispatching straight
# from the pipeline's methods.json (no generate_methods.mk). usage:
#   make methods c={config}           → every registered module
#   make methods x=cme c={config}     → one module
#   make methods x="cme cdyn" c={config}
#   make methods x=cme,cdyn c={config}
# scan and compile always re-run (phony); the stats stage is gated by a
# done file per module and only recomputes when its version is bumped.
# the three stages are sequenced here rather than per module, because the
# measuring is one job for the whole registry.
# see the ms-methods skill.
methods:
	$(MAKE) methods_scan
	$(MAKE) methods_stats
	$(MAKE) methods_compile

# the stages of the above, over the same x= module selection, so template
# validation, the gated measuring and the always-fresh rendering can each be
# invoked separately. scan reads no data and is the cheapest authoring check.
methods_scan:
	python $(_md)/py/methods_run.py \
		ifn=$(MANUSCRIPT_METHODS_JSON) \
		x="$(x)" \
		stage=scan \
		make=$(MAKE) \
		c=$(PROJECT_NAME)

# the measuring, on one machine for every module in turn. a dsub job
# delocalizes a single output directory, so one machine means one tree: the
# modules all write under METHODS_STATS_ROOT. not gated here -- the job
# localizes the root first, so each module's own .done_stats decides whether it
# recomputes, and a run after one version bump measures only that module.
# a space-separated x is first re-issued comma-separated, since an escaped space
# does not survive the par -> dsub parameter chain
methods_stats:
ifneq ($(words $(x)),1)
	$(MAKE) methods_stats x=$(subst $(__space),$(comma),$(strip $(x)))
else
	$(MAKE) m=par par \
		PAR_WORK_DIR=$(TOP_WORK_DIR)/methods_stats \
		PAR_MODULE=manuscript \
		PAR_NAME=t_methods \
		PAR_ODIR_VAR=METHODS_STATS_ROOT \
		PAR_TARGET=methods_measure \
		PAR_PREEMTIBLE=0 \
		PAR_WAIT=$(TOP_WAIT) \
		PAR_MAKEFLAGS="$(PAR_MAKEOVERRIDES)"
endif

# runs on the measuring machine, not on the top one: walks the registry and
# invokes each module's own stats rule
methods_measure:
	python $(_md)/py/methods_run.py \
		ifn=$(MANUSCRIPT_METHODS_JSON) \
		x="$(x)" \
		stage=measure \
		make=$(MAKE) \
		c=$(PROJECT_NAME)

methods_compile:
	python $(_md)/py/methods_run.py \
		ifn=$(MANUSCRIPT_METHODS_JSON) \
		x="$(x)" \
		stage=compile \
		make=$(MAKE) \
		c=$(PROJECT_NAME)
.PHONY: methods methods_scan methods_stats methods_measure methods_compile

# render the combined paper markdown through citeproc so every module shares
# one citation sequence and one bibliography. pandoc uses pdflatex internally;
# the full developer documents remain available as markdown and LaTeX.
ifneq ($(strip $(MANUSCRIPT_REFERENCES_JSON)$(MANUSCRIPT_CSL)),)
MANUSCRIPT_PDF_BODY?=$(MANUSCRIPT_EXPORT_DIR)/methods.md
MANUSCRIPT_PDF_REFERENCES?=$(MANUSCRIPT_EXPORT_DIR)/references.json
MANUSCRIPT_PDF_CSL?=$(MANUSCRIPT_EXPORT_DIR)/citation-style.csl
MANUSCRIPT_PDF?=$(MANUSCRIPT_EXPORT_DIR)/methods_paper.pdf
MANUSCRIPT_PDF_ENGINE?=xelatex

# contents listing depth: 2 lists Methods and one line per module, 3 also lists
# the blocks inside the modules that have more than one
MANUSCRIPT_PDF_TOC_DEPTH?=2
manuscript_pdf:
	@command -v pandoc >/dev/null || { echo "error: pandoc not found" >&2; exit 1; }
	@command -v $(MANUSCRIPT_PDF_ENGINE) >/dev/null || { echo "error: $(MANUSCRIPT_PDF_ENGINE) not found" >&2; exit 1; }
	@[ -f $(MANUSCRIPT_PDF_BODY) ] || { echo "error: missing $(MANUSCRIPT_PDF_BODY)" >&2; exit 1; }
	@[ -f $(MANUSCRIPT_PDF_REFERENCES) ] || { echo "error: missing $(MANUSCRIPT_PDF_REFERENCES)" >&2; exit 1; }
	@[ -f $(MANUSCRIPT_PDF_CSL) ] || { echo "error: missing $(MANUSCRIPT_PDF_CSL)" >&2; exit 1; }
	@buildlog=$(MANUSCRIPT_EXPORT_DIR)/methods_paper.build.log; \
	echo "rendering methods.md -> methods_paper.pdf"; \
	pandoc \
		--from=markdown \
		--standalone \
		--citeproc \
		--number-sections \
		--toc --toc-depth=$(MANUSCRIPT_PDF_TOC_DEPTH) \
		--shift-heading-level-by=-1 \
		--bibliography=$(MANUSCRIPT_PDF_REFERENCES) \
		--csl=$(MANUSCRIPT_PDF_CSL) \
		--pdf-engine=$(MANUSCRIPT_PDF_ENGINE) \
		--output=$(MANUSCRIPT_PDF) \
		$(MANUSCRIPT_PDF_BODY) >$$buildlog 2>&1 || \
		{ echo "error: pandoc failed (see $$buildlog)" >&2; exit 1; }; \
	rm -f $$buildlog; \
	echo "created: $(MANUSCRIPT_PDF)"
else
# configs without a bibliography retain the original LaTeX-only review PDFs
MANUSCRIPT_PDF_BODIES?=methods.tex methods_full.tex
manuscript_pdf:
	@command -v pdflatex >/dev/null || { echo "error: pdflatex not found" >&2; exit 1; }
	@for body in $(MANUSCRIPT_PDF_BODIES); do \
		src=$(MANUSCRIPT_EXPORT_DIR)/$$body; \
		[ -f $$src ] || { echo "warning: missing $$src, skipping" >&2; continue; }; \
		stem=$${body%.tex}; \
		wrap=$(MANUSCRIPT_EXPORT_DIR)/$${stem}_paper.tex; \
		buildlog=$(MANUSCRIPT_EXPORT_DIR)/$${stem}_paper.build.log; \
		echo "wrapping $$body -> $${stem}_paper.pdf"; \
		printf '%s\n' \
			'% auto-generated by manuscript_pdf --- do not edit' \
			'\documentclass[11pt]{article}' \
			'\begin{document}' \
			"\\input{$$body}" \
			'\end{document}' \
			> $$wrap; \
		( cd $(MANUSCRIPT_EXPORT_DIR) && \
			pdflatex -interaction=nonstopmode -halt-on-error $${stem}_paper.tex >$$buildlog 2>&1 && \
			pdflatex -interaction=nonstopmode -halt-on-error $${stem}_paper.tex >>$$buildlog 2>&1 ) || \
			{ echo "error: pdflatex failed on $$body (see $$buildlog and $(MANUSCRIPT_EXPORT_DIR)/$${stem}_paper.log)" >&2; exit 1; }; \
		( cd $(MANUSCRIPT_EXPORT_DIR) && rm -f $${stem}_paper.aux $${stem}_paper.log $${stem}_paper.out $${stem}_paper.toc $${stem}_paper.build.log ); \
		echo "created: $(MANUSCRIPT_EXPORT_DIR)/$${stem}_paper.pdf"; \
	done
endif
.PHONY: manuscript_pdf

# host-side live Zotero DOCX: needs macOS pandoc + running Zotero/BBT. do not
# pass --citeproc; zotero.lua writes ADDIN ZOTERO_ITEM fields instead.
MANUSCRIPT_DOCX_BODY?=$(MANUSCRIPT_EXPORT_DIR)/methods.md
MANUSCRIPT_DOCX?=$(MANUSCRIPT_EXPORT_DIR)/methods_live.docx
MANUSCRIPT_ZOTERO_LUA?=$(_md)/pandoc/zotero.lua
# optional BBT style id (e.g. apa, cell); empty leaves Word/Zotero document prefs
MANUSCRIPT_DOCX_ZOTERO_STYLE?=
manuscript_docx:
	@command -v pandoc >/dev/null || { echo "error: pandoc not found (install on the host)" >&2; exit 1; }
	@[ -f $(MANUSCRIPT_DOCX_BODY) ] || { echo "error: missing $(MANUSCRIPT_DOCX_BODY); run manuscript_export_methods first" >&2; exit 1; }
	@[ -f $(MANUSCRIPT_ZOTERO_LUA) ] || { echo "error: missing $(MANUSCRIPT_ZOTERO_LUA)" >&2; exit 1; }
	@buildlog=$(MANUSCRIPT_EXPORT_DIR)/methods_live.build.log; \
	echo "rendering methods.md -> methods_live.docx (live Zotero fields; Zotero must be running)"; \
	pandoc \
		--from=markdown \
		--to=docx \
		--standalone \
		--lua-filter=$(MANUSCRIPT_ZOTERO_LUA) \
		$(if $(MANUSCRIPT_DOCX_ZOTERO_STYLE),--metadata=zotero_csl_style:$(MANUSCRIPT_DOCX_ZOTERO_STYLE)) \
		--output=$(MANUSCRIPT_DOCX) \
		$(MANUSCRIPT_DOCX_BODY) >$$buildlog 2>&1 || \
		{ echo "error: pandoc/zotero.lua failed (see $$buildlog); is Zotero running with Better BibTeX?" >&2; exit 1; }; \
	rm -f $$buildlog; \
	echo "created: $(MANUSCRIPT_DOCX)"; \
	echo "in Word: open Zotero document preferences (OK), then Refresh, then Add/Edit Bibliography"
.PHONY: manuscript_docx
