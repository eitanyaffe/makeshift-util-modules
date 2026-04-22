
# index global variables (no dyn vars, one row per variable)
index_files:
	$(call _assert,INDEX_VARIABLES INDEX_TABLE INDEX_DESCRIPTIONS)
	$(_R) R/index.r index.table \
		ofn=$(INDEX_TABLE) \
		descriptions.ifn=$(INDEX_DESCRIPTIONS) \
		mount.dirs=$(INDEX_MOUNT_DIRS) \
		output.bucket=$(INDEX_OUTPUT_BUCKET) \
		on.missing.file=$(INDEX_ON_MISSING_FILE) \
		max.items=$(INDEX_MAX_ITEMS) \
		$(call _export_variable,$(INDEX_VARIABLES))

# index a set of variables driven by an input table with dyn vars (e.g. per assembly, per lib)
index_set:
	$(call _assert,INDEX_VARIABLES INDEX_TABLE INDEX_TABLE_INPUT INDEX_DYN_VARIABLES INDEX_DESCRIPTIONS)
	$(_R) R/index_set.r index.set \
		ofn=$(INDEX_TABLE) \
		descriptions.ifn=$(INDEX_DESCRIPTIONS) \
		table.ifn=$(INDEX_TABLE_INPUT) \
		dyn.vars=$(INDEX_DYN_VARIABLES) \
		mount.dirs=$(INDEX_MOUNT_DIRS) \
		output.bucket=$(INDEX_OUTPUT_BUCKET) \
		on.missing.file=$(INDEX_ON_MISSING_FILE) \
		max.items=$(INDEX_MAX_ITEMS) \
		$(call _export_variable,$(INDEX_VARIABLES))

# loop over INDEX_MODULES and invoke each module's {module}_index target
index_build:
	$(call _assert,INDEX_MODULES)
	for mod in $(INDEX_MODULES); do \
		$(MAKE) m=$$mod $${mod}_index || exit 1; \
	done

# derive per-module index dirs from module names: long -> $(LONG_INDEX_DIR)
_index_module_dirs=$(foreach mod,$(INDEX_MODULES),$(call reval3,$(shell echo $(mod) | tr a-z A-Z)_INDEX_DIR))

# copy all per-module index tables to INDEX_EXPORT_DIR and produce a summary table
index_combine:
	$(call _assert,INDEX_MODULES)
	$(call _start,$(INDEX_EXPORT_DIR))
	$(_R) R/index_combine.r index.combine \
		modules="$(INDEX_MODULES)" \
		module.dirs="$(_index_module_dirs)" \
		odir=$(INDEX_EXPORT_DIR) \
		summary.ofn=$(INDEX_EXPORT_DIR)/index.txt
	install -m 755 $(_dir)/msutil.py $(INDEX_EXPORT_DIR)/msutil.py
	install -m 644 $(_md)/docs/README.md $(INDEX_EXPORT_DIR)/README.md
	$(_end)

# build per-module indices and combine into the export dir
index_all: index_build index_combine
