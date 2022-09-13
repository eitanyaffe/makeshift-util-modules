
export_table:
	$(call _start,$(EXPORT_DIR))
	$(_R) R/export.r export.table \
		ofn=$(EXPORT_TABLE) \
		$(call _export_variable,$(EXPORT_VARIABLES)) \
		$(EXPORT_VARIABLES_NOEVAL)
	$(_end)

export_files:
	$(call _start,$(EXPORT_DIR))
	$(_R) R/export.r export.copy \
		mount.dir=$(GCP_DSUB_ODIR_BUCKET_BASE) \
		external.dir=$(MAKESHIFT_LOCAL_PATH)/$(EXPORT_PREFIX) \
		on.missing.file=$(EXPORT_ON_MISSING_FILE) \
		ofn=$(EXPORT_TABLE) \
		odir=$(EXPORT_DIR) \
		$(call _export_variable,$(EXPORT_VARIABLES)) \
		$(EXPORT_VARIABLES_NOEVAL)
	$(_end)

# copy entire directories, place tar in tarball 
#ifneq ($(EXPORT_USER_DIRS),)
#	cp -r $(EXPORT_USER_DIRS) $(EXPORT_DIR)
#endif
#	tar cf $(EXPORT_ODIR_TAR) -C $(EXPORT_DIR) $(EXPORT_ID)
