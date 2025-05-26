
export_table:
	$(call _assert,$(EXPORT_VARIABLES))
	$(call _start,$(EXPORT_DIR))
	$(_R) R/export.r export.table \
		ofn=$(EXPORT_TABLE) \
		$(call _export_variable,$(EXPORT_VARIABLES)) \
		$(EXPORT_VARIABLES_NOEVAL)
	$(_end)

export_files:
	$(call _assert,$(EXPORT_VARIABLES))
	$(call _start,$(EXPORT_DIR))
	$(_R) R/export.r export.copy \
		mount.dirs=$(EXPORT_MOUNT_DIRS) \
		config.dir=$(_cd) \
		external.dir=$(MAKESHIFT_LOCAL_PATH)/$(EXPORT_PREFIX) \
		on.missing.file=$(EXPORT_ON_MISSING_FILE) \
		ofn=$(EXPORT_TABLE) \
		odir=$(EXPORT_DIR) \
		$(call _export_variable,$(EXPORT_VARIABLES)) $(EXPORT_VARIABLES_NOEVAL)
	$(_end)

# export set of of variables based on an input table
export_set:
	$(call _start,$(EXPORT_DIR))
	$(_R) R/export_set.r export.set \
		table.ifn=$(EXPORT_TABLE_INPUT) \
		dyn.vars=$(EXPORT_DYN_VARIABLES) \
		mount.dirs=$(EXPORT_MOUNT_DIRS) \
		config.dir=$(_cd) \
		external.dir=$(MAKESHIFT_LOCAL_PATH)/$(EXPORT_PREFIX) \
		on.missing.file=$(EXPORT_ON_MISSING_FILE) \
		ofn=$(EXPORT_TABLE_SET) \
		odir=$(EXPORT_DIR) \
		$(call _export_variable,$(EXPORT_VARIABLES))
	$(_end)

# copy entire directories, place tar in tarball 
#ifneq ($(EXPORT_USER_DIRS),)
#	cp -r $(EXPORT_USER_DIRS) $(EXPORT_DIR)
#endif
#	tar cf $(EXPORT_ODIR_TAR) -C $(EXPORT_DIR) $(EXPORT_ID)
