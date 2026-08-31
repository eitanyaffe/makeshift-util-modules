# copy figure files described in the manuscript json to the export directory.
# also auto-copies per-pdf sidecars and caption_*.txt, and generates
# captions.txt from all rendered captions (see ms-manuscript skill).
# also copies methods[] docs and concatenates them into methods.md /
# methods.tex.
manuscript_export:
	$(call _start,$(MANUSCRIPT_EXPORT_DIR))
	python $(_md)/py/manuscript.py \
		ifn=$(MANUSCRIPT_JSON) \
		mount.dirs=$(MANUSCRIPT_MOUNT_DIRS) \
		on.missing.file=$(MANUSCRIPT_ON_MISSING_FILE) \
		odir=$(MANUSCRIPT_EXPORT_DIR) \
		$(call _export_variable,$(MANUSCRIPT_REFERENCED_VARS))
	cp $(MANUSCRIPT_JSON) $(MANUSCRIPT_EXPORT_DIR)/
	$(_end)

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
# from figures.json methods[] (no generate_methods.mk). usage:
#   make methods c={config}           → all modules in methods[]
#   make methods x=cme c={config}     → one module
#   make methods x="cme cdyn" c={config}
#   make methods x=cme,cdyn c={config}
# scan and compile always re-run (phony); the stats stage is gated by a
# done file per module and only recomputes when its version is bumped.
# see the ms-methods skill.
methods:
	python $(_md)/py/methods_run.py \
		ifn=$(MANUSCRIPT_JSON) \
		x="$(x)" \
		make=$(MAKE) \
		c=$(PROJECT_NAME)

# the stages of the above, over the same x= module selection, so template
# validation, the gated measuring and the always-fresh rendering can each be
# invoked separately. scan reads no data and is the cheapest authoring check.
methods_scan:
	python $(_md)/py/methods_run.py \
		ifn=$(MANUSCRIPT_JSON) \
		x="$(x)" \
		stage=scan \
		make=$(MAKE) \
		c=$(PROJECT_NAME)

methods_stats:
	python $(_md)/py/methods_run.py \
		ifn=$(MANUSCRIPT_JSON) \
		x="$(x)" \
		stage=stats \
		make=$(MAKE) \
		c=$(PROJECT_NAME)

methods_compile:
	python $(_md)/py/methods_run.py \
		ifn=$(MANUSCRIPT_JSON) \
		x="$(x)" \
		stage=compile \
		make=$(MAKE) \
		c=$(PROJECT_NAME)
.PHONY: methods methods_scan methods_stats methods_compile
