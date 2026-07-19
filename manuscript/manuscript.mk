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
# always remakes (like figs): methods_run.py passes make -B, and
# {module}_methods targets are phony / no done-files.
methods:
	python $(_md)/py/methods_run.py \
		ifn=$(MANUSCRIPT_JSON) \
		x="$(x)" \
		make=$(MAKE) \
		c=$(PROJECT_NAME)
.PHONY: methods
